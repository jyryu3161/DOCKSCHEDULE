from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select

from dockschedule.db import engine, transaction
from dockschedule.models import Compound, Receptor, Task, Upload, User, now
from dockschedule.scheduler import Scheduler
from dockschedule import storage
from dockschedule.config import DEFAULT_SETTINGS


def records(kind='prepare', status='running', receptor_status='preparing'):
    with transaction() as db:
        upload = Upload(owner_id=1, kind='pdb', filename='test.pdb', path='/unused', size=0, sha256='a' * 64)
        db.add(upload)
        db.flush()
        receptor = Receptor(owner_id=1, upload_id=upload.id, name='test', status=receptor_status)
        db.add(receptor)
        db.flush()
        task = Task(owner_id=1, receptor_id=receptor.id, kind=kind, name='test', status=status,
                    run_id='test-run', cpu_ids=[0], worker_pid=999999999, worker_created=0,
                    started_at=now() - timedelta(hours=2))
        db.add(task)
        db.flush()
        return task.id, receptor.id


def test_reap_keeps_completed_preparation_ready(admin_client, monkeypatch):
    task_id, receptor_id = records(status='completed', receptor_status='ready')
    # The worker completed before reaping, even though its start is past the timeout.
    monkeypatch.setattr('dockschedule.scheduler.Queue', lambda *a, **kw: SimpleNamespace(delete=lambda **kw: None))
    Scheduler().reap()
    with transaction() as db:
        task = db.get(Task, task_id)
        assert task.status == 'completed'
        assert task.cpu_ids == [] and task.worker_pid is None
        assert db.get(Receptor, receptor_id).status == 'ready'


@pytest.mark.parametrize('cancelled', [False, True])
def test_recovery_synchronizes_preparation_status(admin_client, cancelled):
    task_id, receptor_id = records()
    with transaction() as db:
        db.get(Task, task_id).cancel_requested = cancelled
    Scheduler().recover()
    with transaction() as db:
        task = db.get(Task, task_id)
        expected = 'cancelled' if cancelled else 'queued'
        assert task.status == db.get(Receptor, receptor_id).status == expected
        assert (task.finished_at is not None) == cancelled


def test_retry_preserves_invalid_rows_and_clears_old_results(admin_client):
    task_id, _ = records(kind='screen', status='partial', receptor_status='ready')
    with transaction() as db:
        task = db.get(Task, task_id)
        task.cpu_ids, task.worker_pid, task.worker_created = [], None, None
        task.total, task.completed, task.failed = 3, 2, 1
        db.add_all([
            Compound(task_id=task_id, row_number=1, cid='', smiles='CC', status='failed', error='CID 또는 SMILES가 비어 있습니다.'),
            Compound(task_id=task_id, row_number=2, cid='retry', smiles='CC', status='partial', affinity=-4,
                     normalized_smiles='CC', details={'old': True}, elapsed=30, attempts=2),
            Compound(task_id=task_id, row_number=3, cid='keep', smiles='CCC', status='succeeded', affinity=-5, attempts=1),
        ])
    response = admin_client.post(f'/api/jobs/{task_id}/retry')
    assert response.status_code == 200
    assert response.json()['failed'] == 1
    assert response.json()['completed'] == 1
    with transaction() as db:
        invalid, retry, keep = db.scalars(select(Compound).where(Compound.task_id == task_id).order_by(Compound.row_number)).all()
        assert invalid.status == 'failed' and invalid.error
        assert retry.status == 'pending' and retry.affinity is None
        assert retry.details == {} and retry.elapsed is None and retry.normalized_smiles is None
        assert retry.attempts == 0
        assert keep.status == 'succeeded' and keep.affinity == -5 and keep.attempts == 1


def test_explicit_null_user_status_is_validation_error(admin_client):
    response = admin_client.patch('/api/admin/users/1', json={'status': None})
    assert response.status_code == 422
    # Explicit null is still supported to remove a CPU override.
    assert admin_client.patch('/api/admin/users/1', json={'cpu_override': None}).status_code == 200


def test_job_list_fetches_owner_names_without_per_row_queries(admin_client):
    _, receptor_id = records(status='completed', receptor_status='ready')
    with transaction() as db:
        for i in range(8):
            user = User(username=f'owner{i}', name=f'Owner {i}', password_hash='unused')
            db.add(user)
            db.flush()
            db.add(Task(owner_id=user.id, receptor_id=receptor_id, kind='screen', name=f'job{i}'))
    statements = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('SELECT'):
            statements.append(statement)
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        response = admin_client.get('/api/jobs?include_total=true')
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    assert response.status_code == 200
    assert {row['owner_name'] for row in response.json()['rows']} >= {f'Owner {i}' for i in range(8)}
    # Session + authenticated user + total + one joined page query.
    assert len(statements) <= 4


def test_storage_quota_reads_uncommitted_accounting_in_one_query(admin_client):
    task_id, _ = records(kind='screen')
    statements = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('SELECT'):
            statements.append(statement)
    with transaction() as db:
        db.get(Task, task_id).artifact_bytes = 2 * 1024**3
        db.flush()
        event.listen(engine, 'before_cursor_execute', capture)
        try:
            with pytest.raises(ValueError, match='학생별'):
                storage.check_capacity({**DEFAULT_SETTINGS, 'user_storage_limit_gb': 1}, 1, db=db)
        finally:
            event.remove(engine, 'before_cursor_execute', capture)
    assert len(statements) == 1


def test_reap_requeues_interrupted_preparation(admin_client, monkeypatch):
    task_id, receptor_id = records()
    with transaction() as db:
        db.get(Task, task_id).started_at = now()
    monkeypatch.setattr('dockschedule.scheduler.Queue', lambda *a, **kw: SimpleNamespace(delete=lambda **kw: None))
    Scheduler().reap()
    with transaction() as db:
        assert db.get(Task, task_id).status == db.get(Receptor, receptor_id).status == 'queued'


def test_retry_and_delete_wait_for_worker_exit(admin_client):
    task_id, _ = records(kind='screen', status='failed', receptor_status='ready')
    with transaction() as db:
        db.get(Task, task_id).cpu_ids = []
    assert admin_client.post(f'/api/jobs/{task_id}/retry').status_code == 409
    assert admin_client.delete(f'/api/jobs/{task_id}').status_code == 409


def test_success_after_automatic_timeout_retry_has_no_stale_error(admin_client, monkeypatch, tmp_path):
    import hashlib
    import json
    from pathlib import Path
    from dockschedule import chemistry, runner

    binary = tmp_path / 'qvina-test'
    binary.write_bytes(b'worker regression fixture')
    monkeypatch.setattr(runner, 'config', lambda: SimpleNamespace(qvina_binary=binary))
    monkeypatch.setattr(chemistry, 'QVINA_SHA256', hashlib.sha256(binary.read_bytes()).hexdigest())

    task_id, _ = records(kind='screen', status='reserved', receptor_status='ready')
    with transaction() as db:
        task = db.get(Task, task_id)
        task.parameters = {'timeout': 1, 'max_retries': 1}
        task.total = 1
        db.add(Compound(task_id=task_id, row_number=1, cid='retry', smiles='CC'))
    clock, attempts = [0], []

    class Process:
        pid, exitcode = 999999999, 0

        def __init__(self, target, args):
            self.output = Path(args[2])

        def start(self):
            attempts.append(1)
            self.alive = len(attempts) == 1
            if not self.alive:
                (self.output / 'result.json').write_text(json.dumps({
                    'status': 'succeeded', 'affinity': -4, 'normalized_smiles': 'CC', 'details': {},
                }))

        def is_alive(self):
            return self.alive

        def join(self, timeout):
            clock[0] += 2
            self.alive = False

    monkeypatch.setattr(runner.multiprocessing, 'get_context', lambda _: SimpleNamespace(Process=Process))
    monkeypatch.setattr(runner, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(runner, 'stop_tree', lambda *args: None)
    runner.run_task(task_id, 'test-run')
    with transaction() as db:
        task = db.get(Task, task_id)
        compound = db.scalar(select(Compound).where(Compound.task_id == task_id))
        assert task.status == 'completed' and task.completed == 1 and task.failed == 0
        assert compound.status == 'succeeded' and compound.attempts == 2
        assert compound.error is None and compound.affinity == -4
