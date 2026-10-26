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
from .models import Compound, GninaScore, Receptor, Settings, Task, Upload, now
from .processes import stop_tree
from .gnina_jobs import maybe_queue_after_screen
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

GNINA_SHA256_OVERRIDE = None  # tests only: expected hash of a fake GNINA binary


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
        source_task_id = task.source_task_id
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

        if kind == 'interactions':
            from .interaction_worker import run_index
            run_index(task_id, run_id, owner, source_task_id, receptor_dir(receptor_owner, receptor_id)/'receptor.pdb')
            return

        if kind == 'gnina':
            _run_gnina(task_id, run_id, owner, source_task_id, receptor_dir(receptor_owner, receptor_id)/'receptor.pdb', cpus)
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
            if kind == 'screen':
                # A failure to queue GNINA must not turn a finished screening into a failed one.
                try:
                    with db.begin_nested():
                        maybe_queue_after_screen(db, task)
                except Exception:
                    traceback.print_exc()
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


def _run_gnina(task_id, run_id, owner, source_task_id, receptor, cpus):
    """Rescore the pending GnninaScore rows of this job; DB writes only under the Task lock and run_id check."""
    from . import gnina
    binary = config().gnina_binary
    expected = GNINA_SHA256_OVERRIDE or gnina.GNINA_SHA256
    version = gnina.check_binary(binary, expected_sha256=expected)
    with transaction() as db:
        timeout = db.get(Settings, 1).values.get('compound_timeout', 600)
    details = dict(gnina_version=version, binary_sha256=expected, options='score_only', cpus=cpus)
    workdir = task_dir(owner, task_id)
    workdir.mkdir(parents=True, exist_ok=True)

    def save(compound_id, result):
        # Called from gnina worker threads: one short session per result.
        with transaction() as db:
            task = db.get(Task, task_id, with_for_update=True)
            if task.run_id != run_id or task.cancel_requested:
                return
            row = db.get(GninaScore, compound_id)
            if row is None or row.job_id != task_id or row.status != 'pending':
                return
            for field in ('status', 'error', 'cnn_score', 'cnn_affinity', 'cnn_vs', 'gnina_vina'):
                setattr(row, field, result[field])
            row.details = details
            if row.status == 'succeeded':
                task.completed += 1
            else:
                task.failed += 1
            task.heartbeat = now()

    while _active(task_id, run_id):
        with transaction() as db:
            ids = list(db.scalars(select(GninaScore.compound_id).where(GninaScore.job_id == task_id, GninaScore.status == 'pending').order_by(
                GninaScore.compound_id).limit(gnina.BATCH_SIZE*cpus*4)))
        if not ids:
            break
        items = [(i, compound_dir(owner, source_task_id, i)/'best.sdf') for i in ids]
        done = gnina.score_batch(receptor, items, cpus, binary, workdir, timeout,
                                 should_stop=lambda: not _active(task_id, run_id), on_result=save)
        if len(done) < len(items) and _active(task_id, run_id):
            raise RuntimeError('GNINA 재채점이 일부 화합물을 처리하지 않고 종료했습니다.')
    with transaction() as db:
        task = db.get(Task, task_id, with_for_update=True)
        if task.run_id != run_id or task.cancel_requested:
            return
        task.status = 'partial' if task.completed and task.failed else 'completed' if task.completed else 'failed'
        task.finished_at = now()


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
