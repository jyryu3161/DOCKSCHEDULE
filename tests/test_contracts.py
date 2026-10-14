from pathlib import Path
from types import SimpleNamespace as NS
import io
import zipfile
import pytest
from sqlalchemy import select
from dockschedule.db import transaction
from dockschedule.models import User, Upload, Receptor, Task, Compound, Settings
from dockschedule.scheduler import choose_tasks
from dockschedule.security import password_hash
from dockschedule import library
from dockschedule.structure import inspect_pdb


def test_signup_approval_and_revocation(client):
    body=dict(username='student1',name='학생',student_number='20260001',password='StudentPass123!')
    r=client.post('/api/auth/register',json=body)
    assert r.status_code==201
    student_id=r.json()['id']
    assert client.post('/api/auth/login',json=body).status_code==200
    assert client.get('/api/auth/me').json()['status']=='pending'
    assert client.get('/api/jobs').status_code==403
    client.post('/api/auth/login',json={'username':'admin','password':'TestAdmin123!'})
    assert client.patch(f'/api/admin/users/{student_id}',json={'status':'approved'}).status_code==200
    client.post('/api/auth/login',json=body)
    assert client.get('/api/jobs').status_code==200
    assert client.get('/api/admin/users').status_code==403
    cookie=client.cookies.get('ds_session')
    client.post('/api/auth/login',json={'username':'admin','password':'TestAdmin123!'})
    client.patch(f'/api/admin/users/{student_id}',json={'status':'suspended'})
    client.cookies.set('ds_session',cookie)
    assert client.get('/api/jobs').status_code in (401,403)


def test_csrf_and_duplicate_user(client):
    assert client.post('/api/auth/login',headers={'X-DS-Request':''},json={'username':'admin','password':'TestAdmin123!'}).status_code==403
    assert client.post('/api/auth/login',headers={'Origin':'https://evil.example'},json={'username':'admin','password':'TestAdmin123!'}).status_code==403
    body=dict(username='student2',name='학생',student_number='1',password='StudentPass123!')
    assert client.post('/api/auth/register',json=body).status_code==201
    assert client.post('/api/auth/register',json=body).status_code==409


def test_scheduler_resource_invariants():
    values=dict(cpu_budget=8,max_students=2,default_cpus=4,paused=False)
    users={i:NS(status='approved',cpu_override=None) for i in range(1,5)}
    waiting=[NS(owner_id=i,cancel_requested=False) for i in [1,1,2,3]]
    choices=choose_tasks(waiting,[],users,values,list(range(16)))
    assert [t.owner_id for t,c in choices]==[1,2]
    assert len({x for _,c in choices for x in c})==8
    assert not set(choices[0][1])&set(choices[1][1])
    active=[NS(owner_id=1,cpu_ids=[0,1,2,3])]
    assert [t.owner_id for t,c in choose_tasks(waiting,active,users,values,list(range(16)))]==[2]
    values['cpu_budget']=2
    assert choose_tasks(waiting,active,users,values,list(range(16)))==[]
    values.update(cpu_budget=8,paused=True)
    assert choose_tasks(waiting,[],users,values,list(range(16)))==[]


def test_library_quoted_smiles_duplicate_ids_and_limits(tmp_path):
    p=tmp_path/'data.csv'
    p.write_text('CID,SMILES,note\n001,CCO,"a,b"\n001,invalid,x\n002,,x\n')
    opts=dict(delimiter=',',encoding='utf-8-sig',header=True,cid_column='CID',smiles_column='SMILES')
    rows=list(library.compounds(p,opts,3))
    assert [r['cid'] for r in rows]==['001','001','002']
    assert rows[-1]['status']=='failed'
    with pytest.raises(ValueError,match='최대'):
        list(library.compounds(p,opts,2))
    assert library.preview(p)['rows'][0]['values'][2]=='a,b'
    p.write_text('a\tb\n001\tCCO\n')
    assert library.preview(p,'\\t')['columns']==['a','b']


def _records(owner=1):
    with transaction() as db:
        upload=Upload(owner_id=owner,kind='pdb',filename='x.pdb',path='/tmp/unused',size=0,sha256='a'*64)
        db.add(upload);db.flush()
        rec=Receptor(owner_id=owner,upload_id=upload.id,name='test',status='ready',structure={'residues':[]})
        db.add(rec);db.flush()
        task=Task(owner_id=owner,receptor_id=rec.id,kind='screen',name='Test',status='completed',total=2)
        db.add(task);db.flush()
        db.add_all([Compound(task_id=task.id,row_number=2,cid='=bad()',smiles='CCO',status='failed',error='bad SMILES'),Compound(task_id=task.id,row_number=3,cid='001',smiles='CC',status='pending')])
        return task.id,rec.id


def test_export_includes_failed_pending_and_prevents_formulas(admin_client):
    task_id,_=_records()
    r=admin_client.get(f'/api/jobs/{task_id}/scores')
    assert r.status_code==200
    assert "'=bad()" in r.text and 'failed' in r.text and 'pending' in r.text
    r=admin_client.get(f'/api/jobs/{task_id}/archive')
    assert r.status_code==200
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert set(z.namelist())=={'scores.csv','manifest.json'}
    assert admin_client.get(f'/api/jobs/{task_id}/results?page_size=1').json()['total']==2


def test_ownership_on_job_results_and_downloads(admin_client):
    task_id,rec_id=_records()
    with transaction() as db:
        db.add(User(username='other',name='other',student_number='2',password_hash=password_hash('OtherPass123!'),status='approved'))
    admin_client.post('/api/auth/login',json={'username':'other','password':'OtherPass123!'})
    for path in [f'/jobs/{task_id}',f'/jobs/{task_id}/results',f'/jobs/{task_id}/scores',f'/jobs/{task_id}/archive',f'/receptors/{rec_id}/file/pdb']:
        assert admin_client.get('/api'+path).status_code==404,path


def test_failed_submission_is_atomic(admin_client):
    _,rec_id=_records()
    r=admin_client.post('/api/uploads?kind=library',files={'file':('library.csv',b'CID,SMILES\na,CC\nb,CC,extra\n')})
    body=dict(name='bad',receptor_id=rec_id,library_id=r.json()['id'],library=dict(delimiter=',',encoding='utf-8-sig',header=True,cid_column='CID',smiles_column='SMILES'),center=[1,2,3],size=[20,20,20])
    assert admin_client.post('/api/jobs',json=body).status_code==422
    assert len(admin_client.get('/api/jobs').json())==1


def test_pdb_chain_and_insertion_identity():
    fixture=Path('tests/fixtures/1L83.pdb').read_text()
    structure=inspect_pdb(fixture)
    assert structure['chains']==['A']
    assert structure['seqres']['A']
    assert any(r['name']=='BNZ' for r in structure['residues'])


def test_model_selection_and_duplicate_residue_numbers():
    atom=next(l for l in Path('tests/fixtures/1L83.pdb').read_text().splitlines() if l.startswith('ATOM  '))
    a=atom[:21]+'A'+atom[22:26]+'A'+atom[27:]
    b=atom[:21]+'B'+atom[22:]
    pdb='MODEL        2\n'+a+'\nENDMDL\nMODEL        1\n'+b+'\nENDMDL\n'
    first=inspect_pdb(pdb)
    assert first['model']==2 and len(first['residues'])==1
    assert first['residues'][0]['insertion']=='A'
    assert inspect_pdb(pdb,1)['residues'][0]['chain']=='B'


def test_checkpoint_recovery_stops_old_worker_and_preserves_results(admin_client):
    import subprocess,sys,psutil
    from dockschedule.scheduler import Scheduler
    task_id,_=_records()
    proc=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])
    try:
        with transaction() as db:
            task=db.get(Task,task_id)
            task.status='running';task.cpu_ids=[0,1];task.run_id='recovery-test'
            task.worker_pid=proc.pid;task.worker_created=psutil.Process(proc.pid).create_time()
            rows=list(db.scalars(select(Compound).where(Compound.task_id==task_id).order_by(Compound.id)))
            rows[0].status='succeeded';rows[0].affinity=-5.5;rows[0].attempts=1
            rows[1].status='running';task.completed=1;task.failed=0
        Scheduler().recover()
        proc.wait(timeout=5)
        assert proc.returncode is not None
        with transaction() as db:
            task=db.get(Task,task_id)
            assert task.status=='queued' and task.cpu_ids==[] and task.completed==1
            rows=list(db.scalars(select(Compound).where(Compound.task_id==task_id).order_by(Compound.id)))
            assert rows[0].status=='succeeded' and rows[0].affinity==-5.5 and rows[0].attempts==1
            assert rows[1].status=='pending'
    finally:
        if proc.poll() is None:proc.kill();proc.wait()


def test_retention_disabled_by_default_and_deletes_only_expired_screening(admin_client):
    from datetime import timedelta
    from dockschedule.models import now,Audit
    from dockschedule.scheduler import Scheduler
    task_id,_=_records()
    with transaction() as db:
        db.get(Task,task_id).finished_at=now()-timedelta(days=3)
    Scheduler().cleanup()
    with transaction() as db:
        assert db.get(Task,task_id) is not None
        s=db.get(Settings,1);s.values={**s.values,'retention_days':1}
    Scheduler().cleanup()
    with transaction() as db:
        assert db.get(Task,task_id) is None
        assert db.scalar(select(Audit).where(Audit.target==task_id,Audit.action=='retention_delete')) is not None


def test_storage_accounting_is_idempotent_after_restart_and_retry(admin_client):
    from dockschedule import storage
    task_id,rec_id=_records()
    baseline=storage.usage(1)['used_bytes']
    with transaction() as db:
        task=db.get(Task,task_id)
        compound=db.scalar(select(Compound).where(Compound.task_id==task_id))
        folder=storage.compound_dir(1,task_id,compound.id)
        folder.mkdir(parents=True)
        (folder/'pose.sdf').write_bytes(b'x'*200)
        storage.account_compound(task,compound)
        storage.account_compound(task,compound)
        assert task.artifact_bytes==200
        compound.status='running'
        (folder/'pose.sdf').write_bytes(b'x'*300)
        storage.account_task(db,task)
        assert task.artifact_bytes==300
    assert storage.usage(1)['used_bytes']==baseline+300
    with transaction() as db:
        db.delete(db.get(Task,task_id))
    assert storage.usage(1)['used_bytes']==baseline


def test_job_pagination_summary_and_search_use_full_history(admin_client):
    task_id,rec_id=_records()
    with transaction() as db:
        db.add_all([Task(owner_id=1,receptor_id=rec_id,kind='screen',name=f'Library {i}',status='queued') for i in range(105)])
    summary=admin_client.get('/api/jobs/summary').json()
    assert summary['total']==106 and summary['counts']['queued']==105
    first=admin_client.get('/api/jobs?limit=50').json()
    second=admin_client.get('/api/jobs?limit=50&offset=50').json()
    assert len(first)==len(second)==50
    assert not {t['id'] for t in first}&{t['id'] for t in second}
    assert len(admin_client.get('/api/jobs?state=done').json())==1
    assert len(admin_client.get('/api/jobs?search=Library%20104').json())==1
    page=admin_client.get('/api/jobs?include_total=true&limit=20&offset=20').json()
    assert page['total']==106 and page['limit']==20 and page['offset']==20 and len(page['rows'])==20
    filtered=admin_client.get('/api/jobs?include_total=true&state=done').json()
    assert filtered['total']==1 and filtered['rows'][0]['id']==task_id
    assert admin_client.get('/api/jobs?include_total=true&search=Library%20104').json()['total']==1
    assert admin_client.get('/api/jobs?include_total=true&search=no-match').json()['total']==0


def test_dispatch_failure_kills_unrecorded_worker_before_releasing_cpus(admin_client,monkeypatch):
    import subprocess,sys
    from contextlib import contextmanager
    from dockschedule import scheduler as module
    task_id,_=_records()
    with transaction() as db:
        db.get(Task,task_id).status='queued'
    scheduler=module.Scheduler()
    scheduler.connection=NS(ping=lambda:True)
    monkeypatch.setattr(scheduler,'reap',lambda:None)
    monkeypatch.setattr(scheduler,'cleanup',lambda:None)
    monkeypatch.setattr(module,'Queue',lambda *a,**kw:NS(enqueue=lambda *a,**kw:None))
    calls=0
    @contextmanager
    def transient_failure():
        nonlocal calls
        calls+=1
        if calls==2:
            raise RuntimeError('simulated commit connection failure')
        with transaction() as db:
            yield db
    monkeypatch.setattr(module,'transaction',transient_failure)
    popen=subprocess.Popen
    spawned=[]
    def start(*a,**kw):
        proc=popen([sys.executable,'-c','import time;time.sleep(60)'],**kw)
        spawned.append(proc)
        return proc
    monkeypatch.setattr(module.subprocess,'Popen',start)
    try:
        scheduler.tick()
        assert len(spawned)==1
        spawned[0].wait(timeout=5)
        assert spawned[0].returncode is not None
        with transaction() as db:
            task=db.get(Task,task_id)
            assert task.status=='queued' and task.cpu_ids==[] and task.worker_pid is None
    finally:
        for proc in spawned:
            if proc.poll() is None:proc.kill();proc.wait()


def test_nonstandard_polymer_not_silently_discarded_and_heterogen_altloc_selection():
    from dockschedule.structure import selected_pdb
    source=Path('tests/fixtures/1L83.pdb').read_text().splitlines()
    atom=next(x for x in source if x.startswith('ATOM  '))
    unknown=atom[:17]+'UNK'+atom[20:]
    assert inspect_pdb(unknown)['residues'][0]['category']=='protein'
    assert unknown in selected_pdb(unknown,1,['A'],[])[0]
    h=next(x for x in source if x.startswith('HETATM') and x[17:20]=='BNZ')
    a=h[:16]+'A'+h[17:54]+'  0.30'+h[60:]
    b=h[:16]+'B'+h[17:54]+'  0.70'+h[60:]
    key=inspect_pdb(h)['residues'][0]['key']
    _,kept=selected_pdb(atom+'\n'+a+'\n'+b,1,['A'],[key])
    assert len(kept)==1 and kept[0][16]==' ' and kept[0][54:60].strip()=='0.70'
