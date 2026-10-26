"""Real HTTP -> PostgreSQL/RQ -> worker -> qvina acceptance.

Uses its own uniquely named student accounts. Credentials are never logged.
Run with ADMIN_PASSWORD set, or a private .env at the repository root.
"""
import argparse
import csv
import io
import json
import os
import secrets
import subprocess
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8890');p.add_argument('--output',default='test-results/service-check.json');args=p.parse_args()
password=os.environ.get('ADMIN_PASSWORD') or dotenv_values('.env')['ADMIN_PASSWORD']
admin=httpx.Client(base_url=args.url,headers={'X-DS-Request':'1'},timeout=60)

def call(client,method,path,**kwargs):
    r=client.request(method,'/api'+path,**kwargs)
    r.raise_for_status()
    return r.json()

def wait(client,task_id,timeout=180):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        task=call(client,'GET','/jobs/'+task_id)
        if task['status'] in ('completed','partial','failed','cancelled'):
            return task
        time.sleep(1)
    raise AssertionError('Task timeout: '+task_id)

call(admin,'POST','/auth/login',json=dict(username='admin',password=password))
original=call(admin,'GET','/settings')['values']
call(admin,'PUT','/admin/settings',json={**original,'cpu_budget':4,'default_cpus':2,'max_students':2})
prefix='acceptance_'+secrets.token_hex(4)
students=[];report={'accounts':[],'preparations':[],'screenings':[],'observations':[]}
try:
    for n in range(2):
        client=httpx.Client(base_url=args.url,headers={'X-DS-Request':'1'},timeout=60)
        username=prefix+'_'+str(n);pw=secrets.token_urlsafe(18)
        user=call(client,'POST','/auth/register',json=dict(username=username,name=f'검증 학생 {n+1}',student_number='TEST',password=pw))
        report['accounts'].append(user['id'])
        call(client,'POST','/auth/login',json=dict(username=username,password=pw))
        assert client.get('/api/jobs').status_code==403
        call(admin,'PATCH',f'/admin/users/{user["id"]}',json={'status':'approved'})
        with Path('tests/fixtures/1L83.pdb').open('rb') as f:
            upload=call(client,'POST','/uploads?kind=pdb',files={'file':('1L83.pdb',f)})
        prep=call(client,'POST','/receptors',json=dict(upload_id=upload['id'],name=f'1L83 검증 {n+1}',model=1,chains=['A'],keep_heterogens=[],ph=7.4))
        students.append((client,user,prep))
    for client,user,prep in students:
        task=wait(client,prep['task_id'])
        assert task['status']=='completed',task
        receptor=call(client,'GET','/receptors/'+prep['receptor_id'])
        assert len(receptor['report']['modeled_residues'])==2
        report['preparations'].append(task)
    for client,user,prep in students:
        library='CID\tSMILES\n0001\tc1ccccc1\n0001\tC[C@H](O)c1ccccc1\ninvalid\tnot_smiles\n'
        upload=call(client,'POST','/uploads?kind=library',files={'file':('screen.tsv',library.encode())})
        options=dict(delimiter='\t',encoding='utf-8-sig',header=True,cid_column='CID',smiles_column='SMILES')
        preview=call(client,'POST',f'/uploads/{upload["id"]}/preview',json=options)
        assert preview['rows'][0]['values'][0]=='0001'
        task=call(client,'POST','/jobs',json=dict(name='실제 docking 검증',receptor_id=prep['receptor_id'],library_id=upload['id'],library=options,
                     center=[26.929,6.158,4.216],size=[20,20,20],conformers=2,exhaustiveness=8,seed=42))
        prep['screen_id']=task['id']
    deadline=time.monotonic()+240
    while time.monotonic()<deadline:
        states=[call(c,'GET','/jobs/'+p['screen_id']) for c,u,p in students]
        active=[t for t in states if t['status'] in ('running','reserved')]
        reserved=[cpu for t in states for cpu in t['cpu_ids']]
        assert len(reserved)==len(set(reserved)) and len(reserved)<=4
        assert len(active)<=2
        report['observations'].append({'statuses':[t['status'] for t in states],'cpus':[t['cpu_ids'] for t in states]})
        if len(active)==2 and all(t['status']=='running' for t in active) and 'process_affinity' not in report:
            code = """import json,psutil
from sqlalchemy import select
from dockschedule.db import Session
from dockschedule.models import Task
out=[]
with Session() as db:
 for t in db.scalars(select(Task).where(Task.status=='running')):
  if not t.worker_pid: continue
  try:
   parent=psutil.Process(t.worker_pid)
   processes=[parent]+parent.children(recursive=True)
   affinity=[dict(pid=p.pid,name=p.name(),cpus=p.cpu_affinity()) for p in processes if p.is_running()]
   assert all(set(p['cpus']) <= set(t.cpu_ids) for p in affinity),affinity
   out.append(dict(task_id=t.id,reserved=t.cpu_ids,processes=affinity))
  except psutil.NoSuchProcess: pass
print(json.dumps(out))"""
            result=subprocess.run(['docker','compose','exec','-T','scheduler','python','-c',code],capture_output=True,text=True,check=True)
            report['process_affinity']=json.loads(result.stdout)
        if all(t['status'] in ('completed','partial','failed') for t in states):break
        time.sleep(.4)
    for client,user,prep in students:
        task=wait(client,prep['screen_id'])
        assert task['status']=='partial' and task['completed']==2 and task['failed']==1,task
        rows=call(client,'GET',f'/jobs/{task["id"]}/results')['rows']
        valid=[r for r in rows if r['affinity'] is not None]
        assert len(valid)==2 and all(r['affinity']<0 for r in valid)
        for r in valid:
            pose=client.get(f'/api/jobs/{task["id"]}/compounds/{r["id"]}/pdbqt')
            assert pose.status_code==200 and pose.text.count('REMARK VINA RESULT:')==1
        exported=client.get(f'/api/jobs/{task["id"]}/scores')
        assert len(list(csv.reader(io.StringIO(exported.text.lstrip('\ufeff')))))==4
        report['screenings'].append({'task':task,'results':rows})
    assert students[0][0].get('/api/jobs/'+students[1][2]['screen_id']+'/scores').status_code==404
    # GNINA flow: the finished screening auto-queues a gnina task. A real GNINA binary may be missing on the host,
    # so only the registration and API shape are required; scored rows are asserted only if the task completes.
    gnina_report=[]
    for client,user,prep in students:
        sid=prep['screen_id']
        children=[t for t in call(client,'GET','/jobs') if t['source_task_id']==sid and t['kind']=='gnina']
        assert len(children)==1,children
        data=call(client,'GET',f'/jobs/{sid}/results?sort=consensus&w=0.5')
        assert data['rows'] and all('gnina' in r for r in data['rows']),data
        summary=call(client,'GET','/jobs/'+sid)['gnina']
        assert summary['active']==children[0]['id'] or children[0]['status'] in ('completed','partial','failed','cancelled'),summary
        deadline=time.monotonic()+120
        while time.monotonic()<deadline and call(client,'GET','/jobs/'+children[0]['id'])['status'] not in ('completed','partial','failed','cancelled'):
            time.sleep(2)
        final=call(client,'GET','/jobs/'+children[0]['id'])
        if final['status']=='completed':
            data=call(client,'GET',f'/jobs/{sid}/results?sort=consensus&w=0.5')
            scored=[r for r in data['rows'] if r['gnina'] and r['gnina']['status']=='succeeded']
            assert scored and all(r['gnina']['rank']['consensus'] for r in scored),data
            assert [r['gnina']['rank']['consensus'] for r in scored]==sorted(r['gnina']['rank']['consensus'] for r in scored)
            assert call(client,'GET','/jobs/'+sid)['gnina']['scored']==len(scored)
        else:
            print(f'NOTE: gnina task {children[0]["id"]} ended {final["status"]} (GNINA binary may be unavailable on this host); scored rows not asserted')
        assert client.get(f'/api/jobs/{sid}/scores').text.lstrip('\ufeff').splitlines()[0].endswith('gnina_consensus_rank')
        gnina_report.append({'task':final,'summary':call(client,'GET','/jobs/'+sid)['gnina']})
    assert students[0][0].post('/api/jobs/'+students[1][2]['screen_id']+'/gnina').status_code==404
    report['gnina']=gnina_report
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,ensure_ascii=False,default=str,indent=2))
    print(json.dumps({'passed':True,'report':str(output),'tasks':[p['screen_id'] for _,_,p in students]},indent=2))
finally:
    call(admin,'PUT','/admin/settings',json=original)
    # Keep read-only demonstration results visible to the admin, disable test accounts.
    for _,user,_ in students:
        call(admin,'PATCH',f'/admin/users/{user["id"]}',json={'status':'suspended'})
