"""Single-server durable dispatcher with disjoint CPU reservations."""
import fcntl
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import timedelta

import psutil
from redis import Redis
from rq import Queue
from rq.serializers import JSONSerializer
from sqlalchemy import select, update
from .config import config
from .db import transaction
from .models import ACTIVE, FINISHED, Audit, Compound, Receptor, Settings, Task, User, now, uid
from .processes import matches, stop_tree
from .storage import account_task, root, task_dir

log = logging.getLogger(__name__)


def choose_tasks(waiting, active, users, values, available):
    used_cpus = {i for t in active for i in t.cpu_ids}
    active_users = {t.owner_id for t in active}
    free = [i for i in available if i not in used_cpus]
    remaining = values['cpu_budget'] - sum(len(t.cpu_ids) for t in active)
    if values['paused']:
        return []
    choices = []
    # A student's gnina tasks go to the position of that student's earliest waiting task; other students keep their order.
    gnina = {}
    for task in waiting:
        if task.kind == 'gnina':
            gnina.setdefault(task.owner_id, []).append(task)
    ordered, seen = [], set()
    for task in waiting:
        if task.owner_id not in seen:
            seen.add(task.owner_id)
            ordered.extend(gnina.get(task.owner_id, []))
        if task.kind != 'gnina':
            ordered.append(task)
    # An auto-registered gnina task finishes its screening's set: it takes the slot that screening just freed
    # before any other student's waiting task. Manually requested gnina tasks keep the normal order.
    auto = lambda t: t.kind == 'gnina' and (getattr(t, 'parameters', None) or {}).get('auto')
    ordered = [t for t in ordered if auto(t)] + [t for t in ordered if not auto(t)]
    for task in ordered:
        user = users.get(task.owner_id)
        if task.cancel_requested or user is None or user.status != 'approved' or task.owner_id in active_users:
            continue
        count = 1 if task.kind == 'interactions' else user.cpu_override or values['default_cpus']
        if len(active_users) >= values['max_students']:
            break
        if count > remaining or count > len(free):
            continue
        choices.append((task, free[:count]))
        free, remaining = free[count:], remaining-count
        active_users.add(task.owner_id)
    return choices


class Scheduler:
    def __init__(self):
        self.connection = Redis.from_url(config().redis_url, socket_connect_timeout=3, socket_timeout=3)
        self.available = sorted(os.sched_getaffinity(0))
        self.children = {}
        self.stopping = False
        self.last_cleanup = 0

    def recover(self):
        with transaction() as db:
            for task in db.scalars(select(Task).where((Task.status.in_(ACTIVE)) | (Task.worker_pid.is_not(None))).with_for_update()):
                # The dispatcher owns these processes in one host/container PID namespace.
                # Check creation time before killing to avoid unrelated reused PIDs.
                if matches(task.worker_pid, task.worker_created):
                    stop_tree(task.worker_pid, task.worker_created)
                # Cover a dispatcher crash between spawning a worker and recording its PID.
                if task.run_id:
                    for process in psutil.process_iter(['pid', 'cmdline', 'create_time']):
                        args = process.info['cmdline'] or []
                        if 'dockschedule.runner' in args and task.run_id in args:
                            stop_tree(process.pid, process.info['create_time'])
                account_task(db, task)
                if task.status in ACTIVE:
                    task.status = 'cancelled' if task.cancel_requested else 'queued'
                    task.finished_at = now() if task.cancel_requested else None
                    task.error = '이전 실행 중단 후 미완료 화합물부터 재개합니다.'
                    if task.kind == 'prepare':
                        db.get(Receptor, task.receptor_id).status = task.status
                    db.execute(update(Compound).where(Compound.task_id == task.id, Compound.status == 'running').values(status='pending'))
                task.cpu_ids, task.worker_pid, task.worker_created = [], None, None

    def cleanup(self):
        if time.monotonic()-self.last_cleanup < 300:
            return
        self.last_cleanup = time.monotonic()
        with transaction() as db:
            days = db.get(Settings, 1).values['retention_days']
            if days == 0:
                return
            cutoff = now()-timedelta(days=days)
            for task in db.scalars(select(Task).where(Task.kind == 'screen', Task.status.in_(FINISHED),
                                                      Task.worker_pid.is_(None), Task.finished_at < cutoff).limit(100).with_for_update()):
                from .interaction_index import active_analysis
                if active_analysis(db, task.id):
                    continue
                for child in db.scalars(select(Task).where(Task.source_task_id == task.id)):
                    shutil.rmtree(task_dir(child.owner_id, child.id), ignore_errors=True)
                shutil.rmtree(task_dir(task.owner_id, task.id), ignore_errors=True)
                db.add(Audit(action='retention_delete', target=task.id, detail={'retention_days': days, 'owner_id': task.owner_id}))
                db.delete(task)

    def reap(self):
        with transaction() as db:
            for task in db.scalars(select(Task).where(Task.worker_pid.is_not(None)).with_for_update()):
                live = matches(task.worker_pid, task.worker_created)
                expired = task.status in ACTIVE and task.kind == 'prepare' and task.started_at and (now()-task.started_at).total_seconds() > db.get(Settings, 1).values['preparation_timeout']
                if task.status in ACTIVE and (task.cancel_requested or expired):
                    if live:
                        stop_tree(task.worker_pid, task.worker_created)
                    task.status = 'cancelled' if task.cancel_requested else 'failed'
                    task.error = None if task.cancel_requested else '단백질 전처리 제한 시간을 초과했습니다.'
                    task.finished_at = now()
                    if task.kind == 'prepare':
                        db.get(Receptor, task.receptor_id).status = task.status
                    live = False
                if not live:
                    account_task(db, task)
                    if task.status in ACTIVE:
                        task.status = 'queued'
                        task.finished_at = None
                        task.error = 'Worker 중단 후 미완료 항목을 다시 실행합니다.'
                        if task.kind == 'prepare':
                            db.get(Receptor, task.receptor_id).status = 'queued'
                        db.execute(update(Compound).where(Compound.task_id == task.id, Compound.status == 'running').values(status='pending'))
                    task.cpu_ids, task.worker_pid, task.worker_created = [], None, None
                    try:
                        Queue('ds-'+task.run_id, connection=self.connection).delete(delete_jobs=True)
                    except Exception:
                        pass
            for task in db.scalars(select(Task).where(Task.status == 'queued', Task.cancel_requested.is_(True))):
                task.status, task.finished_at = 'cancelled', now()
                if task.kind == 'prepare':
                    db.get(Receptor, task.receptor_id).status = 'cancelled'
        for key, (process, output) in list(self.children.items()):
            if process.poll() is not None:
                output.close()
                del self.children[key]

    def tick(self):
        self.reap()
        self.cleanup()
        try:
            self.connection.ping()
        except Exception as exc:
            with transaction() as db:
                s = db.get(Settings, 1)
                s.heartbeat, s.available_cpus, s.scheduler_error = now(), self.available, 'Redis 연결 실패: 신규 작업 배정을 멈췄습니다.'
            return
        with transaction() as db:
            s = db.get(Settings, 1)
            s.heartbeat, s.available_cpus, s.scheduler_error = now(), self.available, None
            active = list(db.scalars(select(Task).where(Task.status.in_(ACTIVE) | Task.worker_pid.is_not(None))))
            waiting = list(db.scalars(select(Task).where(Task.status == 'queued').order_by(Task.created_at, Task.id)))
            users = {u.id: u for u in db.scalars(select(User))}
            choices = choose_tasks(waiting, active, users, s.values, self.available)
            reserved = []
            for task, cpus in choices:
                task.status, task.cpu_ids, task.run_id = 'reserved', cpus, uid()
                task.started_at, task.heartbeat, task.error = now(), now(), None
                reserved.append((task.id, task.run_id, task.owner_id, cpus))
        for task_id, run_id, owner, cpus in reserved:
            proc, output, created = None, None, None
            try:
                queue = Queue('ds-'+run_id, connection=self.connection, serializer=JSONSerializer)
                queue.enqueue('dockschedule.runner.run_task', task_id, run_id,
                              job_id=run_id, job_timeout=-1, result_ttl=60, failure_ttl=86400)
                env = os.environ.copy()
                env.update(DS_CPU_IDS=','.join(map(str, cpus)), OPENMM_CPU_THREADS=str(len(cpus)),
                           OMP_NUM_THREADS=str(len(cpus)), OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1')
                folder = task_dir(owner, task_id)
                folder.mkdir(parents=True, exist_ok=True)
                output = (folder/'worker.log').open('ab')
                proc = subprocess.Popen([sys.executable, '-m', 'dockschedule.runner', 'ds-'+run_id, run_id], env=env,
                                        stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
                self.children[task_id] = proc, output
                created = psutil.Process(proc.pid).create_time()
                with transaction() as db:
                    task = db.get(Task, task_id)
                    task.worker_pid, task.worker_created = proc.pid, created
            except Exception as exc:
                log.exception('Worker dispatch failed')
                # Never release a reservation while an unrecorded worker still lives.
                if proc is not None and proc.poll() is None:
                    stop_tree(proc.pid, created)
                if output is not None:
                    output.close()
                self.children.pop(task_id, None)
                with transaction() as db:
                    task = db.get(Task, task_id)
                    account_task(db, task)
                    if task.status in ACTIVE:
                        task.status, task.finished_at, task.error = 'queued', None, str(exc)
                        if task.kind == 'prepare':
                            db.get(Receptor, task.receptor_id).status = 'queued'
                        db.execute(update(Compound).where(Compound.task_id == task.id, Compound.status == 'running').values(status='pending'))
                    task.cpu_ids = []
                    task.worker_pid, task.worker_created = None, None

    def run(self):
        root().mkdir(parents=True, exist_ok=True)
        with (root()/'scheduler.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.recover()
            def stop(*_):
                self.stopping = True
            signal.signal(signal.SIGTERM, stop)
            signal.signal(signal.SIGINT, stop)
            try:
                while not self.stopping:
                    try:
                        self.tick()
                    except Exception:
                        log.exception('Scheduler tick failed; reservations retained')
                    time.sleep(1)
            finally:
                for proc, output in self.children.values():
                    if proc.poll() is None:
                        stop_tree(proc.pid)
                    output.close()
                self.recover()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    Scheduler().run()
