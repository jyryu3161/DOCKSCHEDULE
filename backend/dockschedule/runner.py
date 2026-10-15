"""One RQ worker per resource reservation; one compound at a time per task."""
import json
import hashlib
import multiprocessing
import os
import sys
import time
import traceback
from pathlib import Path

from sqlalchemy import func, select, update
from .config import config
from .db import transaction
from .models import Compound, Receptor, Settings, Task, Upload, now
from .processes import stop_tree
from .storage import account_compound, account_task, check_capacity, compound_dir, receptor_dir, task_dir


def _compound_process(smiles, receptor, output, parameters, cpus, binary):
    from .chemistry import dock_compound
    try:
        result = dock_compound(smiles, receptor, output, parameters, cpus, binary)
    except Exception as exc:
        result = {'error': str(exc), 'status': 'failed'}
    path = Path(output)/'result.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, ensure_ascii=False))
    temporary.replace(path)


def _active(task_id, run_id):
    with transaction() as db:
        t = db.get(Task, task_id, with_for_update=True)
        if t.run_id != run_id or t.cancel_requested:
            return False
        t.heartbeat = now()
        return True


def run_task(task_id, run_id):
    with transaction() as db:
        task = db.get(Task, task_id, with_for_update=True)
        if task.run_id != run_id or task.status != 'reserved' or task.cancel_requested:
            return
        task.status, task.heartbeat = 'running', now()
        receptor = db.get(Receptor, task.receptor_id)
        if task.kind == 'prepare':
            receptor.status = 'preparing'
        source = db.get(Upload, receptor.upload_id).path
        receptor_owner = receptor.owner_id
        params, owner, receptor_id, kind, cpus = task.parameters, task.owner_id, task.receptor_id, task.kind, len(task.cpu_ids)
    try:
        if kind == 'prepare':
            from .chemistry import prepare_receptor
            result = prepare_receptor(Path(source), receptor_dir(receptor_owner, receptor_id), params)
            with transaction() as db:
                task = db.get(Task, task_id, with_for_update=True)
                if task.run_id != run_id or task.cancel_requested:
                    return
                receptor = db.get(Receptor, receptor_id)
                account_task(db, task)
                receptor.report, receptor.structure, receptor.status = result['report'], result['structure'], 'ready'
                task.status, task.finished_at = 'completed', now()
            return

        # Preload chemistry in the job process. Forked per-compound processes isolate
        # memory/timeouts without repeatedly importing the scientific stack.
        import rdkit.Chem.AllChem
        import meeko
        from .chemistry import QVINA_SHA256
        if hashlib.sha256(config().qvina_binary.read_bytes()).hexdigest() != QVINA_SHA256:
            raise ValueError('QuickVina 바이너리 체크섬이 검증된 버전과 다릅니다.')
        context = multiprocessing.get_context('fork')
        while _active(task_id, run_id):
            with transaction() as db:
                # Recovery and retry reset interrupted rows to pending. One status
                # lets the compound_status index return the next row without sorting.
                c = db.scalar(select(Compound).where(Compound.task_id == task_id, Compound.status == 'pending').order_by(Compound.row_number).limit(1))
                if c is None:
                    break
                cfg = db.get(Settings, 1).values
                check_capacity(cfg, owner, db=db)
                c.status, c.attempts = 'running', c.attempts+1
                c.error, c.affinity, c.normalized_smiles = None, None, None
                c.details, c.elapsed = {}, None
                compound_id, smiles = c.id, c.smiles
            output = compound_dir(owner, task_id, compound_id)
            output.mkdir(parents=True, exist_ok=True)
            (output/'result.json').unlink(missing_ok=True)
            started = time.monotonic()
            proc = context.Process(target=_compound_process, args=(smiles, receptor_dir(receptor_owner, receptor_id)/'receptor.pdbqt', output, params, cpus, config().qvina_binary.resolve()))
            proc.start()
            timed_out, cancelled = False, False
            while proc.is_alive():
                proc.join(timeout=1)
                if time.monotonic()-started > params['timeout']:
                    timed_out = True
                    stop_tree(proc.pid)
                    break
                if not _active(task_id, run_id):
                    cancelled = True
                    stop_tree(proc.pid)
                    break
            proc.join(timeout=5)
            if cancelled:
                return
            if timed_out:
                result = {'status': 'failed', 'error': f'화합물 처리 시간 {params["timeout"]}초를 초과했습니다.'}
            elif (output/'result.json').exists():
                result = json.loads((output/'result.json').read_text())
            else:
                result = {'status': 'failed', 'error': f'계산 프로세스 종료 코드 {proc.exitcode}'}
            with transaction() as db:
                task = db.get(Task, task_id, with_for_update=True)
                if task.run_id != run_id or task.cancel_requested:
                    return
                c = db.get(Compound, compound_id)
                account_compound(task, c)
                c.elapsed = time.monotonic()-started
                for field in ('normalized_smiles', 'affinity', 'status', 'details', 'error'):
                    if field in result:
                        setattr(c, field, result[field])
                if timed_out and c.attempts <= params.get('max_retries', 1):
                    c.status = 'pending'
                if c.status in ('succeeded', 'partial'):
                    task.completed += 1
                elif c.status == 'failed':
                    task.failed += 1
                task.heartbeat = now()
        with transaction() as db:
            task = db.get(Task, task_id, with_for_update=True)
            if task.run_id != run_id or task.cancel_requested:
                return
            partial = db.scalar(select(func.count()).select_from(Compound).where(Compound.task_id == task_id, Compound.status == 'partial'))
            task.status = 'partial' if task.completed and (task.failed or partial) else 'completed' if task.completed else 'failed'
            task.finished_at = now()
    except Exception as exc:
        traceback.print_exc()
        with transaction() as db:
            task = db.get(Task, task_id, with_for_update=True)
            if task.run_id == run_id:
                account_task(db, task)
                task.status, task.error, task.finished_at = 'failed', str(exc), now()
                if kind == 'prepare':
                    receptor = db.get(Receptor, receptor_id)
                    receptor.status, receptor.report = 'failed', {'error': str(exc)}


if __name__ == '__main__':
    cpu_ids = [int(x) for x in os.environ['DS_CPU_IDS'].split(',')]
    os.sched_setaffinity(0, cpu_ids)
    from redis import Redis
    from rq import Queue, SimpleWorker
    from rq.serializers import JSONSerializer
    connection = Redis.from_url(config().redis_url)
    queue = Queue(sys.argv[1], connection=connection, serializer=JSONSerializer)
    worker = SimpleWorker([queue], connection=connection, serializer=JSONSerializer,
                          name='ds-'+sys.argv[2])
    worker.work(burst=True, logging_level='WARNING')
