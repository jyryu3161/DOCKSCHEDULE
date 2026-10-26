"""GNINA rescoring jobs: target selection and task registration. No chemistry imports: api and scheduler import this.

Only the top-N screening compounds (by QuickVina affinity) are rescored. Succeeded GnninaScore rows are never
recomputed or deleted; failed/pending ones are reset onto the new job.
"""
from sqlalchemy import func, or_, select, update

from .models import ACTIVE, Compound, GninaScore, Settings, Task
from . import interaction_index as ix

CHUNK = 500


def _top(screen_task_id, top_n):
    # Walks the compound_results (task_id, affinity) index and stops after N rows.
    return ix.eligible(screen_task_id).with_only_columns(Compound.id, Compound.affinity, Compound.row_number).order_by(
        Compound.affinity.asc(), Compound.row_number).limit(top_n).subquery()


def select_targets(db, screen_task_id, top_n):
    """Compound ids to compute, best affinity first: the top-N minus those already scored successfully."""
    top = _top(screen_task_id, top_n)
    return list(db.scalars(select(top.c.id).outerjoin(GninaScore, GninaScore.compound_id == top.c.id).where(
        or_(GninaScore.compound_id.is_(None), GninaScore.status != 'succeeded')).order_by(top.c.affinity, top.c.row_number)))


def active_gnina(db, screen_task_id):
    """A GNINA task of this screening that is queued/running or still has a worker process."""
    return db.scalar(select(Task).where(Task.source_task_id == screen_task_id, Task.kind == 'gnina',
        Task.status.in_(('queued', *ACTIVE)) | Task.worker_pid.is_not(None)).limit(1))


def create_gnina_task(db, screen, top_n, *, auto):
    """Queue a gnina task for the screening, or return None (nothing to compute / one already active).

    No capacity check here: the caller decides (auto registration never refuses). The caller commits.
    """
    if top_n < 1 or active_gnina(db, screen.id):
        return None
    targets = select_targets(db, screen.id, top_n)
    if not targets:
        return None
    selected = db.scalar(select(func.count()).select_from(_top(screen.id, top_n)))
    task = Task(owner_id=screen.owner_id, receptor_id=screen.receptor_id, source_task_id=screen.id, kind='gnina',
                name='GNINA · '+screen.name[:190], parameters={'top_n': top_n, 'auto': auto},
                total=selected, completed=selected-len(targets))
    db.add(task)
    db.flush()
    for start in range(0, len(targets), CHUNK):
        chunk = targets[start:start+CHUNK]
        existing = set(db.scalars(select(GninaScore.compound_id).where(GninaScore.compound_id.in_(chunk))))
        db.execute(update(GninaScore).where(GninaScore.compound_id.in_(existing)).values(
            task_id=screen.id, job_id=task.id, status='pending', error=None, cnn_score=None, cnn_affinity=None,
            cnn_vs=None, gnina_vina=None, details={}))
        db.add_all([GninaScore(compound_id=i, task_id=screen.id, job_id=task.id, status='pending')
                    for i in chunk if i not in existing])
        db.flush()
    return task


def maybe_queue_after_screen(db, screen_task):
    """Auto registration; call in the transaction that finalizes the screening."""
    if screen_task.kind != 'screen' or screen_task.status not in ('completed', 'partial'):
        return None
    top_n = db.get(Settings, 1).values.get('gnina_top_n', 1000)
    return create_gnina_task(db, screen_task, top_n, auto=True) if top_n else None
