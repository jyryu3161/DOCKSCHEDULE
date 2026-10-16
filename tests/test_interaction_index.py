import csv
import io
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from dockschedule import interaction_index as ix, interaction_worker, interactions, runner
from dockschedule.db import transaction
from dockschedule.models import Compound, CompoundAnalysis, InteractionHit, Receptor, Task, Upload, User
from dockschedule.scheduler import choose_tasks
from dockschedule.security import password_hash


def residue(chain='A', insertion=''):
    return dict(key=f'{chain}:42:{insertion}', chain=chain, number=42, insertion=insertion, name='ASN', category='protein')


@pytest.fixture
def library(admin_client):
    with transaction() as db:
        upload = Upload(owner_id=1, kind='pdb', filename='test.pdb', path='/unused', size=0, sha256='a'*64)
        db.add(upload); db.flush()
        receptor = Receptor(owner_id=1, upload_id=upload.id, name='test', status='ready',
                            structure={'residues': [residue(), residue('B'), residue(insertion='A')]})
        db.add(receptor); db.flush()
        task = Task(owner_id=1, receptor_id=receptor.id, kind='screen', name='library', status='partial', total=6, completed=5)
        db.add(task); db.flush()
        batch = Task(owner_id=1, receptor_id=receptor.id, source_task_id=task.id, kind='interactions', name='analysis',
                     status='completed', total=5, completed=4, failed=1, parameters={'engine_version': '2.2.3'})
        db.add(batch); db.flush()
        ids = []
        for i in range(1, 7):
            c = Compound(task_id=task.id, row_number=i, cid='=unsafe' if i == 1 else f'CID{i}', smiles='N',
                         status='succeeded' if i < 6 else 'pending', affinity=-10+i if i < 6 else None)
            db.add(c); db.flush(); ids.append(c.id)
            if i < 6:
                db.add(CompoundAnalysis(compound_id=c.id, job_id=batch.id, status='succeeded' if i < 5 else 'failed',
                                        error='invalid SDF' if i == 5 else None))
        db.flush()
        for index, res, kind in [(0, residue(), 'hydrogen_bond'), (0, residue('B'), 'hydrophobic'),
                                 (1, residue(), 'hydrogen_bond'), (1, residue('B'), 'hydrogen_bond'),
                                 (2, residue(insertion='A'), 'hydrogen_bond')]:
            db.add(InteractionHit(compound_id=ids[index], task_id=task.id, residue_key=res['key'], kind=kind,
                                  residue=res, count=2, distance=3.0))
        return task.id, batch.id, ids


def filters(*residues, kinds=('hydrogen_bond',), match='any'):
    return [('interaction', 'true'), ('match', match)] + [('residue', r) for r in residues] + [('kind', k) for k in kinds]


def test_exact_residue_type_any_all_pagination_and_csv(admin_client, library):
    task, _, ids = library
    path = f'/api/jobs/{task}'
    query = filters('A:42:', 'B:42:')
    result = admin_client.get(path+'/results', params=query).json()
    assert result['total'] == 2 and [c['id'] for c in result['rows']] == ids[:2]
    assert len(result['rows'][0]['matched_interactions']) == 1
    assert admin_client.get(path+'/results', params=query+[('page_size', 1), ('page', 2)]).json()['rows'][0]['id'] == ids[1]
    result = admin_client.get(path+'/results', params=filters('A:42:', 'B:42:', match='all')).json()
    assert [c['id'] for c in result['rows']] == [ids[1]]
    result = admin_client.get(path+'/results', params=filters('A:42:', 'B:42:', match='all', kinds=('hydrogen_bond', 'hydrophobic'))).json()
    assert result['total'] == 2
    result = admin_client.get(path+'/results', params=filters('A:42:A')).json()
    assert [c['id'] for c in result['rows']] == [ids[2]]
    assert admin_client.get(path+'/results', params=filters('A:42:', kinds=('salt_bridge',))).json()['total'] == 0
    export = admin_client.get(path+'/interaction-candidates.csv', params=query)
    assert export.status_code == 200
    rows = list(csv.DictReader(io.StringIO(export.text.lstrip('\ufeff'))))
    assert len(rows) == 2 and rows[0]['CID'] == "'=unsafe"
    assert 'hydrogen_bond' in rows[0]['matched_interactions'] and 'hydrophobic' not in rows[0]['matched_interactions']
    assert rows[0]['engine_version'] == '2.2.3'
    assert len(list(csv.DictReader(io.StringIO(admin_client.get(path+'/interaction-candidates.csv',
        params=query+[('search', 'CID2')]).text.lstrip('\ufeff'))))) == 1
    for invalid in [[], [('interaction', 'true')], filters('Z:42:'), filters('A:42:', kinds=('bad_type',))]:
        assert admin_client.get(path+'/interaction-candidates.csv', params=invalid).status_code == 422


def test_backfill_snapshot_counts_retry_invalidation_and_deletion(admin_client, library):
    task, old_batch, ids = library
    path = f'/api/jobs/{task}'
    status = admin_client.get(path+'/interaction-index').json()
    assert (status['eligible'], status['analyzed'], status['failed'], status['remaining']) == (5, 4, 1, 0)
    assert status['failures'][0]['error'] == 'invalid SDF'
    response = admin_client.post(path+'/interaction-index')
    assert response.status_code == 201, response.text
    batch = response.json()
    assert batch['total'] == 1 and batch['source_task_id'] == task
    assert admin_client.post(path+'/interaction-index').status_code == 409
    assert admin_client.post(path+'/retry').status_code == 409
    assert admin_client.delete(path).status_code == 409
    with transaction() as db:
        assert db.get(CompoundAnalysis, ids[3]).job_id == old_batch  # zero contacts is a success
        assert db.get(CompoundAnalysis, ids[4]).job_id == batch['id']
        db.get(Task, batch['id']).status = 'cancelled'
        db.get(Compound, ids[0]).status = 'partial'
    assert admin_client.post(path+'/retry').status_code == 200
    with transaction() as db:
        assert db.get(CompoundAnalysis, ids[0]) is None
        assert db.scalar(select(func.count()).select_from(InteractionHit).where(InteractionHit.compound_id == ids[0])) == 0
        assert db.get(CompoundAnalysis, ids[1]).status == 'succeeded'
        db.get(Task, task).status = 'cancelled'
    assert admin_client.delete(path).status_code == 200
    with transaction() as db:
        assert db.get(Task, old_batch) is None and db.get(Task, batch['id']) is None
        assert db.scalar(select(func.count()).select_from(InteractionHit)) == 0


def test_ownership_covers_status_submission_filter_export_and_cancel(admin_client, library):
    task, batch, _ = library
    with transaction() as db:
        db.add(User(username='other', name='other', password_hash=password_hash('OtherPass123!'), status='approved'))
    admin_client.post('/api/auth/login', json={'username': 'other', 'password': 'OtherPass123!'})
    path = f'/api/jobs/{task}'
    assert admin_client.get(path+'/interaction-index').status_code == 404
    assert admin_client.post(path+'/interaction-index').status_code == 404
    assert admin_client.get(path+'/results', params=filters('A:42:')).status_code == 404
    assert admin_client.get(path+'/interaction-candidates.csv', params=filters('A:42:')).status_code == 404
    assert admin_client.post(f'/api/jobs/{batch}/cancel').status_code == 404


def test_worker_resumes_pending_rows_and_distinguishes_empty_success_and_failure(admin_client, library, monkeypatch):
    task_id, batch_id, ids = library
    with transaction() as db:
        ix.invalidate(db, ids)
        for i in ids[:3]:
            db.add(CompoundAnalysis(compound_id=i, job_id=batch_id, status='pending'))
        task = db.get(Task, batch_id)
        task.status, task.run_id, task.completed, task.failed = 'running', 'run', 0, 0
    monkeypatch.setattr(interactions, '_load_protein', lambda _: 'prepared once')
    calls = []
    def analyze(prepared, receptor, pose, output):
        assert prepared == 'prepared once'
        i = int(pose.parent.name)
        result = {'hits': []} if i != ids[2] else {'error': 'invalid ligand'}
        if i == ids[0]:
            result['hits'] = [dict(residue_key='A:42:', residue=residue(), kind='hydrogen_bond', count=2, distance=3)]
        output.write_text(json.dumps(result))
    monkeypatch.setattr(interaction_worker, '_analyze', analyze)
    original_active = runner._active
    # A process restart preserves already committed compounds, including no-hit results.
    # Invoke the worker with a bounded first pass, then resume the same persisted job.
    class Process:
        pid = 999999
        exitcode = 0
        def __init__(self, target, args): self.target, self.args = target, args
        def start(self): self.target(*self.args)
        def is_alive(self): return False
        def join(self, **kwargs): pass
    monkeypatch.setattr(interaction_worker.multiprocessing, 'get_context', lambda _: SimpleNamespace(Process=Process))
    def active(task, run):
        calls.append(1)
        if len(calls) == 2:
            # Simulate a cancellation between poses. Pending rows remain resumable.
            with transaction() as db: db.get(Task, task).cancel_requested = True
            return False
        return original_active(task, run)
    monkeypatch.setattr(runner, '_active', active)
    interaction_worker.run_index(batch_id, 'run', 1, task_id, None)
    with transaction() as db:
        task = db.get(Task, batch_id)
        assert task.completed == 1 and task.failed == 0
        task.cancel_requested = False
    monkeypatch.setattr(runner, '_active', original_active)
    interaction_worker.run_index(batch_id, 'run', 1, task_id, None)
    with transaction() as db:
        task = db.get(Task, batch_id)
        assert (task.status, task.completed, task.failed) == ('partial', 2, 1)
        assert db.get(CompoundAnalysis, ids[1]).status == 'succeeded'
        assert db.get(CompoundAnalysis, ids[2]).error == 'invalid ligand'
        assert db.scalar(select(func.count()).select_from(InteractionHit)) == 1


def test_analysis_uses_one_cpu_and_respects_existing_user_reservation():
    users = {1: SimpleNamespace(status='approved', cpu_override=8)}
    waiting = [SimpleNamespace(kind='interactions', owner_id=1, cancel_requested=False)]
    values = dict(cpu_budget=4, default_cpus=4, max_students=4, paused=False)
    assert choose_tasks(waiting, [], users, values, [0, 1, 2, 3])[0][1] == [0]
    assert choose_tasks(waiting, [SimpleNamespace(owner_id=1, cpu_ids=[0])], users, values, [0, 1, 2, 3]) == []
