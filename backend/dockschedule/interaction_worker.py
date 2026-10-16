"""One CPU, prepared protein reused, isolated/time-limited per-pose analyses."""
import json
import multiprocessing
import time

from sqlalchemy import insert, select
from .db import transaction
from .models import CompoundAnalysis, InteractionHit, Task, now
from .processes import stop_tree
from .storage import compound_dir, task_dir


def _analyze(prepared, receptor, pose, output):
    from .interactions import analyze_pose
    from .interaction_index import summarize
    try:
        report = analyze_pose(receptor, pose, prepared=prepared)
        result = dict(hits=summarize(report))
    except Exception as exc:
        result = dict(error=str(exc)[:2000])
    temporary = output.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False))
    temporary.replace(output)


def run_index(task_id, run_id, owner, source_task_id, receptor):
    import prolif
    from .interactions import _load_protein
    from .runner import _active

    prepared = _load_protein(receptor)
    with transaction() as db:
        task = db.get(Task, task_id, with_for_update=True)
        if task.run_id != run_id or task.cancel_requested:
            return
        task.parameters = {**task.parameters, 'engine': 'ProLIF', 'engine_version': prolif.__version__, 'schema_version': 1}
    output = task_dir(owner, task_id)/'interaction.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    context = multiprocessing.get_context('fork')
    try:
        while _active(task_id, run_id):
            with transaction() as db:
                compound_id = db.scalar(select(CompoundAnalysis.compound_id).where(
                    CompoundAnalysis.job_id == task_id, CompoundAnalysis.status == 'pending').order_by(
                    CompoundAnalysis.compound_id).limit(1))
            if compound_id is None:
                break
            output.unlink(missing_ok=True)
            proc = context.Process(target=_analyze, args=(prepared, receptor,
                compound_dir(owner, source_task_id, compound_id)/'best.sdf', output))
            proc.start()
            started = time.monotonic()
            timed_out = False
            try:
                while proc.is_alive():
                    proc.join(timeout=1)
                    if not _active(task_id, run_id):
                        return
                    if time.monotonic()-started > 45:
                        timed_out = True
                        break
            finally:
                if proc.is_alive():
                    stop_tree(proc.pid)
                proc.join(timeout=5)
            if timed_out:
                result = dict(error='Pose 상호작용 분석 시간 한도 45초를 초과했습니다.')
            elif output.exists():
                result = json.loads(output.read_text())
            else:
                result = dict(error=f'분석 프로세스 종료 코드 {proc.exitcode}')
            with transaction() as db:
                task = db.get(Task, task_id, with_for_update=True)
                if task.run_id != run_id or task.cancel_requested:
                    return
                row = db.get(CompoundAnalysis, compound_id)
                if row is None or row.job_id != task_id or row.status != 'pending':
                    raise ValueError('분석 대상이 변경되었습니다. 다시 분석해 주세요.')
                row.error = result.get('error')
                row.status = 'failed' if row.error else 'succeeded'
                if row.error:
                    task.failed += 1
                else:
                    if result['hits']:
                        db.execute(insert(InteractionHit), [dict(**h, compound_id=compound_id, task_id=source_task_id) for h in result['hits']])
                    task.completed += 1
                task.heartbeat = now()
        with transaction() as db:
            task = db.get(Task, task_id, with_for_update=True)
            if task.run_id == run_id and not task.cancel_requested:
                task.status = 'partial' if task.completed and task.failed else 'completed' if task.completed else 'failed'
                task.finished_at = now()
    finally:
        output.unlink(missing_ok=True)
        output.with_suffix('.tmp').unlink(missing_ok=True)
