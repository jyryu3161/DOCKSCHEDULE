import hashlib
from types import SimpleNamespace as NS
import pytest
from sqlalchemy import select
from dockschedule import runner, storage
from dockschedule.db import transaction
from dockschedule.models import Compound, GninaScore, Receptor, Settings, Task, Upload, now
from dockschedule.scheduler import Scheduler, choose_tasks
from test_gnina import fake, make_pose  # noqa: F401  (fixture reused from T3)


def screen(rows, status='completed', owner=1):
    """rows: [(affinity, status)] -> row_number 1..n; returns (screen_id, [compound ids])."""
    with transaction() as db:
        upload = Upload(owner_id=owner, kind='pdb', filename='x.pdb', path='/unused', size=0, sha256='a'*64)
        db.add(upload)
        db.flush()
        rec = Receptor(owner_id=owner, upload_id=upload.id, name='r', status='ready')
        db.add(rec)
        db.flush()
        task = Task(owner_id=owner, receptor_id=rec.id, kind='screen', name='Screen', status=status, total=len(rows))
        db.add(task)
        db.flush()
        cs = [Compound(task_id=task.id, row_number=i, cid=f'c{i}', smiles='CCO', affinity=a, status=s)
              for i, (a, s) in enumerate(rows, 1)]
        db.add_all(cs)
        db.flush()
        return task.id, [c.id for c in cs]


def score_row(db, compound_id, screen_id, job_id, status='succeeded', value=1.0):
    db.add(GninaScore(compound_id=compound_id, task_id=screen_id, job_id=job_id, status=status,
                      cnn_score=value, cnn_affinity=value, cnn_vs=value, gnina_vina=-value))


def old_job(screen_id, status='completed'):
    with transaction() as db:
        s = db.get(Task, screen_id)
        t = Task(owner_id=s.owner_id, receptor_id=s.receptor_id, source_task_id=screen_id, kind='gnina', name='old', status=status)
        db.add(t)
        db.flush()
        return t.id


def set_top(n):
    with transaction() as db:
        s = db.get(Settings, 1)
        s.values = {**s.values, 'gnina_top_n': n}


# --- selection ---------------------------------------------------------------------

def test_selection_cuts_ties_by_row_number_and_includes_partial(admin_client):
    from dockschedule import gnina_jobs
    sid, ids = screen([(-7, 'succeeded'), (-9, 'partial'), (-7, 'succeeded'), (-7, 'succeeded'),
                       (None, 'succeeded'), (-12, 'failed'), (-3, 'pending')])
    with transaction() as db:
        # affinity order: -9 (row2), -7 rows 1,3,4 ; top 3 -> rows 2,1,3 (tie cut at boundary by row_number)
        assert list(gnina_jobs.select_targets(db, sid, 3)) == [ids[1], ids[0], ids[2]]
        assert list(gnina_jobs.select_targets(db, sid, 100)) == [ids[1], ids[0], ids[2], ids[3]]
        assert list(gnina_jobs.select_targets(db, sid, 0)) == []


def test_selection_skips_succeeded_but_recomputes_failed_and_pending(admin_client):
    from dockschedule import gnina_jobs
    sid, ids = screen([(-9, 'succeeded'), (-8, 'succeeded'), (-7, 'succeeded'), (-6, 'succeeded')])
    job = old_job(sid)
    with transaction() as db:
        score_row(db, ids[0], sid, job)
        score_row(db, ids[1], sid, job, status='failed')
        score_row(db, ids[2], sid, job, status='pending')
    with transaction() as db:
        assert list(gnina_jobs.select_targets(db, sid, 3)) == [ids[1], ids[2]]


def test_create_task_pending_rows_counts_and_outside_top_n_kept(admin_client):
    from dockschedule import gnina_jobs
    sid, ids = screen([(-9, 'succeeded'), (-8, 'succeeded'), (-7, 'succeeded'), (-1, 'succeeded')])
    job = old_job(sid)
    with transaction() as db:
        score_row(db, ids[0], sid, job)                      # in top-3, already succeeded -> kept, not recomputed
        score_row(db, ids[1], sid, job, status='failed')     # reset to pending
        score_row(db, ids[3], sid, job)                      # outside top-3 -> kept untouched
    with transaction() as db:
        task = gnina_jobs.create_gnina_task(db, db.get(Task, sid), 3, auto=True)
        assert task.kind == 'gnina' and task.source_task_id == sid and task.library_id is None
        assert task.parameters['top_n'] == 3 and task.status == 'queued'
        assert (task.total, task.completed, task.failed) == (3, 1, 0)
        tid = task.id
    with transaction() as db:
        rows = {r.compound_id: r for r in db.scalars(select(GninaScore))}
        assert rows[ids[0]].status == 'succeeded' and rows[ids[0]].job_id == job
        assert rows[ids[3]].status == 'succeeded' and rows[ids[3]].job_id == job
        assert rows[ids[1]].status == 'pending' and rows[ids[1]].job_id == tid and rows[ids[1]].error is None
        assert rows[ids[2]].status == 'pending' and rows[ids[2]].job_id == tid and rows[ids[2]].task_id == sid


def test_no_duplicate_while_active_but_allowed_after_finish(admin_client):
    from dockschedule import gnina_jobs
    sid, _ = screen([(-9, 'succeeded'), (-8, 'succeeded')])
    with transaction() as db:
        first = gnina_jobs.create_gnina_task(db, db.get(Task, sid), 2, auto=False)
        assert first is not None
        assert gnina_jobs.active_gnina(db, sid).id == first.id
        assert gnina_jobs.create_gnina_task(db, db.get(Task, sid), 2, auto=False) is None
        first.status = 'running'
        assert gnina_jobs.create_gnina_task(db, db.get(Task, sid), 2, auto=True) is None
        first.status, first.worker_pid = 'failed', 123   # worker still alive -> still active
        assert gnina_jobs.active_gnina(db, sid) is not None
        first.worker_pid = None
        assert gnina_jobs.active_gnina(db, sid) is None


def test_active_gnina_ignores_other_kinds(admin_client):
    from dockschedule import gnina_jobs
    sid, _ = screen([(-9, 'succeeded')])
    with transaction() as db:
        s = db.get(Task, sid)
        db.add(Task(owner_id=1, receptor_id=s.receptor_id, source_task_id=sid, kind='interactions', name='i', status='queued'))
    with transaction() as db:
        assert gnina_jobs.active_gnina(db, sid) is None


# --- auto registration -------------------------------------------------------------

@pytest.mark.parametrize('status,expected', [('completed', 1), ('partial', 1), ('failed', 0), ('cancelled', 0)])
def test_auto_registration_only_for_completed_or_partial(admin_client, status, expected):
    from dockschedule import gnina_jobs
    sid, _ = screen([(-9, 'succeeded')], status=status)
    with transaction() as db:
        gnina_jobs.maybe_queue_after_screen(db, db.get(Task, sid))
    with transaction() as db:
        assert len(list(db.scalars(select(Task).where(Task.kind == 'gnina')))) == expected


def test_auto_registration_copies_setting_and_ignores_later_changes(admin_client):
    from dockschedule import gnina_jobs
    sid, _ = screen([(-9, 'succeeded'), (-8, 'succeeded'), (-7, 'succeeded')])
    set_top(2)
    with transaction() as db:
        task = gnina_jobs.maybe_queue_after_screen(db, db.get(Task, sid))
        assert task.parameters['top_n'] == 2 and task.total == 2
        tid = task.id
    set_top(1)
    with transaction() as db:
        assert db.get(Task, tid).parameters['top_n'] == 2


def test_auto_registration_zero_empty_and_missing_setting(admin_client):
    from dockschedule import gnina_jobs
    sid, _ = screen([(-9, 'succeeded')])
    set_top(0)
    with transaction() as db:
        assert gnina_jobs.maybe_queue_after_screen(db, db.get(Task, sid)) is None
    empty, _ = screen([(None, 'failed')])
    set_top(5)
    with transaction() as db:
        assert gnina_jobs.maybe_queue_after_screen(db, db.get(Task, empty)) is None
        s = db.get(Settings, 1)
        s.values = {k: v for k, v in s.values.items() if k != 'gnina_top_n'}   # old DB without the key -> 1000
    with transaction() as db:
        assert gnina_jobs.maybe_queue_after_screen(db, db.get(Task, sid)).parameters['top_n'] == 1000
        assert gnina_jobs.maybe_queue_after_screen(db, db.get(Task, sid)) is None   # already active


def test_auto_registration_does_no_pending_cap_check(admin_client):
    from dockschedule import gnina_jobs
    sid, _ = screen([(-9, 'succeeded')])
    with transaction() as db:
        s = db.get(Task, sid)
        for _ in range(5):
            db.add(Task(owner_id=1, receptor_id=s.receptor_id, kind='screen', name='q', status='queued'))
    with transaction() as db:
        assert gnina_jobs.maybe_queue_after_screen(db, db.get(Task, sid)) is not None


# --- scheduler ---------------------------------------------------------------------

def test_choose_tasks_moves_gnina_to_students_earliest_position():
    values = dict(cpu_budget=64, max_students=8, default_cpus=4, paused=False)
    users = {i: NS(status='approved', cpu_override=None) for i in (1, 2, 3)}
    mk = lambda name, owner, kind: NS(name=name, owner_id=owner, kind=kind, cancel_requested=False)
    waiting = [mk('a-screen', 1, 'screen'), mk('b-screen', 2, 'screen'), mk('a-gnina', 1, 'gnina'),
               mk('b-gnina', 2, 'gnina'), mk('c-gnina', 3, 'gnina'), mk('c-screen', 3, 'screen')]
    assert [t.name for t, _ in choose_tasks(waiting, [], users, values, list(range(16)))] == ['a-gnina', 'b-gnina', 'c-gnina']
    # one active task per student: the screen that follows never runs together with the student's gnina
    active = [NS(owner_id=1, cpu_ids=[0, 1, 2, 3])]
    assert [t.name for t, _ in choose_tasks(waiting, active, users, values, list(range(16)))] == ['b-gnina', 'c-gnina']


def test_choose_tasks_auto_gnina_takes_the_freed_slot_before_other_students():
    values = dict(cpu_budget=64, max_students=1, default_cpus=4, paused=False)
    users = {i: NS(status='approved', cpu_override=None) for i in (1, 2)}
    mk = lambda name, owner, kind, auto=None: NS(name=name, owner_id=owner, kind=kind, cancel_requested=False,
                                                 parameters={'auto': auto} if auto is not None else {})
    waiting = [mk('a-screen', 1, 'screen'), mk('b-screen', 2, 'screen'), mk('b-gnina', 2, 'gnina', True)]
    assert [t.name for t, _ in choose_tasks(waiting, [], users, values, list(range(8)))] == ['b-gnina']
    # a manual resume keeps the normal queue order
    waiting = [mk('a-screen', 1, 'screen'), mk('b-screen', 2, 'screen'), mk('b-gnina', 2, 'gnina', False)]
    assert [t.name for t, _ in choose_tasks(waiting, [], users, values, list(range(8)))] == ['a-screen']


def test_choose_tasks_gnina_cpu_rule_and_disjoint():
    values = dict(cpu_budget=64, max_students=8, default_cpus=4, paused=False)
    users = {1: NS(status='approved', cpu_override=None), 2: NS(status='approved', cpu_override=6)}
    mk = lambda owner, kind: NS(owner_id=owner, kind=kind, cancel_requested=False)
    choices = choose_tasks([mk(1, 'gnina'), mk(2, 'gnina'), mk(1, 'interactions')], [], users, values, list(range(16)))
    assert [len(c) for _, c in choices] == [4, 6]
    assert not set(choices[0][1]) & set(choices[1][1])
    assert [len(c) for _, c in choose_tasks([mk(1, 'interactions')], [], users, values, list(range(16)))] == [1]


def test_choose_tasks_keeps_student_earliest_when_it_is_gnina():
    values = dict(cpu_budget=64, max_students=8, default_cpus=4, paused=False)
    users = {1: NS(status='approved', cpu_override=None)}
    waiting = [NS(name='g', owner_id=1, kind='gnina', cancel_requested=False), NS(name='s', owner_id=1, kind='screen', cancel_requested=False)]
    assert [t.name for t, _ in choose_tasks(waiting, [], users, values, [0, 1, 2, 3])] == ['g']


# --- runner ------------------------------------------------------------------------

@pytest.fixture
def lab(admin_client, fake, tmp_path, monkeypatch):
    """A finished screening with poses on disk, plus the runner pointed at the fake GNINA."""
    monkeypatch.setattr(runner, 'config', lambda: NS(gnina_binary=fake, qvina_binary=fake))
    monkeypatch.setattr(runner, 'GNINA_SHA256_OVERRIDE', hashlib.sha256(fake.read_bytes()).hexdigest())

    def build(rows, top_n=100):
        from dockschedule import gnina_jobs
        sid, ids = screen(rows)
        with transaction() as db:
            owner, rec = db.get(Task, sid).owner_id, db.get(Task, sid).receptor_id
        (storage.receptor_dir(owner, rec)).mkdir(parents=True, exist_ok=True)
        (storage.receptor_dir(owner, rec)/'receptor.pdb').write_text('ATOM\n')
        for n, cid in enumerate(ids, 1):
            folder = storage.compound_dir(owner, sid, cid)
            folder.mkdir(parents=True, exist_ok=True)
            make_pose(folder/'best.sdf', 'CCO', n)
        with transaction() as db:
            task = gnina_jobs.create_gnina_task(db, db.get(Task, sid), top_n, auto=True)
            tid = task.id
        return sid, ids, tid
    return build


def reserve(tid, run_id='run-1', cpus=(0, 1)):
    with transaction() as db:
        t = db.get(Task, tid)
        t.status, t.run_id, t.cpu_ids = 'reserved', run_id, list(cpus)


def state(tid):
    with transaction() as db:
        t = db.get(Task, tid)
        rows = {r.compound_id: r for r in db.scalars(select(GninaScore))}
        return t, rows


def test_end_to_end_screen_finishes_then_gnina_runs(lab, monkeypatch):
    sid, ids, _ = lab([(-9, 'succeeded')])    # fixture queues a first job; use a fresh screen for the full path
    with transaction() as db:
        for t in db.scalars(select(Task).where(Task.kind == 'gnina')):
            db.delete(t)
    # screen finalization hook: reuse the real runner finalization via a screen with no pending compounds
    with transaction() as db:
        s = db.get(Task, sid)
        s.status, s.run_id, s.cpu_ids, s.completed = 'reserved', 'run-s', [0], 1
        s.parameters = {'timeout': 5}
    monkeypatch.setattr(runner, 'check_capacity', lambda *a, **k: None)
    from dockschedule import chemistry
    monkeypatch.setattr(chemistry, 'QVINA_SHA256', hashlib.sha256(runner.config().qvina_binary.read_bytes()).hexdigest())
    runner.run_task(sid, 'run-s')
    with transaction() as db:
        assert db.get(Task, sid).status == 'completed'      # no compound is pending: finalizes at once
        queued = list(db.scalars(select(Task).where(Task.kind == 'gnina')))
        assert len(queued) == 1 and queued[0].status == 'queued' and queued[0].parameters['top_n'] == 1000
        tid = queued[0].id
    reserve(tid)
    runner.run_task(tid, 'run-1')
    task, rows = state(tid)
    assert task.status == 'completed' and (task.total, task.completed, task.failed) == (1, 1, 0)
    row = rows[ids[0]]
    assert row.status == 'succeeded' and row.job_id == tid and row.error is None
    assert row.cnn_affinity == pytest.approx(0.5) and row.gnina_vina == pytest.approx(-1.0) and row.cnn_vs == pytest.approx(0.05)
    assert row.details['options'] == 'score_only' and row.details['cpus'] == 2
    assert row.details['gnina_version'].startswith('gnina v1.3.3') and len(row.details['binary_sha256']) == 64
    with transaction() as db:   # docking results untouched
        c = db.get(Compound, ids[0])
        assert (c.status, c.affinity) == ('succeeded', -9)


def test_statuses_completed_partial_failed(lab):
    sid, ids, tid = lab([(-9, 'succeeded'), (-8, 'succeeded')])
    # break one pose -> that row fails, the other succeeds -> partial
    with transaction() as db:
        owner = db.get(Task, sid).owner_id
    (storage.compound_dir(owner, sid, ids[1])/'best.sdf').write_text('garbage')
    reserve(tid)
    runner.run_task(tid, 'run-1')
    task, rows = state(tid)
    assert task.status == 'partial' and (task.completed, task.failed) == (1, 1)
    assert rows[ids[1]].status == 'failed' and rows[ids[1]].error and rows[ids[1]].cnn_score is None
    # none succeeded -> failed
    sid, ids, tid = lab([(-9, 'succeeded')])
    with transaction() as db:
        owner = db.get(Task, sid).owner_id
    (storage.compound_dir(owner, sid, ids[0])/'best.sdf').write_text('garbage')
    reserve(tid, 'run-2')
    runner.run_task(tid, 'run-2')
    assert state(tid)[0].status == 'failed'


def test_binary_checksum_failure_fails_only_this_task(lab, monkeypatch):
    sid, ids, tid = lab([(-9, 'succeeded')])
    monkeypatch.setattr(runner, 'GNINA_SHA256_OVERRIDE', '0'*64)
    reserve(tid)
    runner.run_task(tid, 'run-1')
    task, rows = state(tid)
    assert task.status == 'failed' and '체크섬' in task.error and rows[ids[0]].status == 'pending'


def test_cancel_preserves_completed_rows_and_discards_late_results(lab, monkeypatch):
    from dockschedule import gnina
    sid, ids, tid = lab([(-9, 'succeeded'), (-8, 'succeeded'), (-7, 'succeeded')])
    reserve(tid)
    ok = dict(status='succeeded', error=None, cnn_score=.5, cnn_affinity=1., cnn_vs=.5, gnina_vina=-5.)

    def cancelling(receptor, items, cpus, binary, workdir, timeout, should_stop=None, on_result=None):
        assert cpus == 2
        on_result(items[0][0], ok)
        with transaction() as db:
            db.get(Task, tid).cancel_requested = True
        on_result(items[1][0], ok)          # arrives after the cancel: discarded
        assert should_stop()
        return {items[0][0]: ok}
    monkeypatch.setattr(gnina, 'score_batch', cancelling)
    runner.run_task(tid, 'run-1')
    task, rows = state(tid)
    assert task.status == 'running' and task.completed == 0 + 1       # not finalized; reap() cancels it
    assert [rows[i].status for i in ids] == ['succeeded', 'pending', 'pending']


def test_stale_run_id_results_are_discarded(lab, monkeypatch):
    from dockschedule import gnina
    sid, ids, tid = lab([(-9, 'succeeded'), (-8, 'succeeded')])
    reserve(tid)
    ok = dict(status='succeeded', error=None, cnn_score=.5, cnn_affinity=1., cnn_vs=.5, gnina_vina=-5.)

    def replaced(receptor, items, cpus, binary, workdir, timeout, should_stop=None, on_result=None):
        with transaction() as db:
            db.get(Task, tid).run_id = 'newer'
        for key, _ in items:
            on_result(key, ok)
        return {key: ok for key, _ in items}
    monkeypatch.setattr(gnina, 'score_batch', replaced)
    runner.run_task(tid, 'run-1')
    task, rows = state(tid)
    assert task.status == 'running' and task.run_id == 'newer' and task.completed == 0
    assert all(r.status == 'pending' for r in rows.values())


def test_recovery_resumes_only_pending_rows(lab, monkeypatch):
    from dockschedule import gnina
    sid, ids, tid = lab([(-9, 'succeeded'), (-8, 'succeeded'), (-7, 'succeeded')])
    reserve(tid)
    ok = dict(status='succeeded', error=None, cnn_score=.5, cnn_affinity=1., cnn_vs=.5, gnina_vina=-5.)
    real = gnina.score_batch

    def interrupted(receptor, items, cpus, binary, workdir, timeout, should_stop=None, on_result=None):
        on_result(items[0][0], ok)
        with transaction() as db:
            db.get(Task, tid).cancel_requested = False
        raise KeyboardInterrupt            # the worker dies mid-batch
    monkeypatch.setattr(gnina, 'score_batch', interrupted)
    with pytest.raises(KeyboardInterrupt):
        runner.run_task(tid, 'run-1')
    with transaction() as db:
        t = db.get(Task, tid)
        t.worker_pid = None
    Scheduler().recover()
    task, rows = state(tid)
    assert task.status == 'queued' and task.cpu_ids == [] and task.completed == 1
    assert [rows[i].status for i in ids] == ['succeeded', 'pending', 'pending']
    seen = []
    monkeypatch.setattr(gnina, 'score_batch', lambda r, items, *a, **k: seen.extend(k_ for k_, _ in items) or real(r, items, *a, **k))
    reserve(tid, 'run-2')
    runner.run_task(tid, 'run-2')
    task, rows = state(tid)
    assert seen == ids[1:] and task.status == 'completed' and task.completed == 3


def test_cleanup_and_reap_accept_gnina_tasks(lab, monkeypatch):
    from datetime import timedelta
    sid, ids, tid = lab([(-9, 'succeeded')])
    monkeypatch.setattr('dockschedule.scheduler.Queue', lambda *a, **kw: NS(delete=lambda **kw: None))
    with transaction() as db:
        t = db.get(Task, tid)
        t.status, t.run_id, t.cpu_ids, t.worker_pid, t.worker_created = 'running', 'r', [0], 999999999, 0
    Scheduler().reap()
    task, _ = state(tid)
    assert task.status == 'queued' and task.cpu_ids == [] and task.worker_pid is None
    with transaction() as db:   # cancel of a queued gnina task keeps GNINA rows
        db.get(Task, tid).cancel_requested = True
    Scheduler().reap()
    assert state(tid)[0].status == 'cancelled' and ids[0] in state(tid)[1]
