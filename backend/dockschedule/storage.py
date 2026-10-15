import shutil
import os
from contextlib import nullcontext
from sqlalchemy import func, select
from .db import Session
from .models import Compound, Receptor, Task, Upload
from pathlib import Path
from .config import config


def root():
    return config().storage_root.resolve()


def receptor_dir(owner, receptor_id):
    return root()/str(owner)/'receptors'/receptor_id


def task_dir(owner, task_id):
    return root()/str(owner)/'tasks'/task_id


def compound_dir(owner, task_id, compound_id):
    return task_dir(owner, task_id)/f'{compound_id//1000:05d}'/str(compound_id)


def inside(path):
    path = Path(path).resolve()
    if not path.is_relative_to(root()):
        raise ValueError('허용되지 않은 저장 경로입니다.')
    return path


def directory_bytes(path):
    """Used only for a single completed compound/receptor, never the whole library."""
    total = 0
    if not path.exists():
        return total
    with os.scandir(path) as entries:
        for entry in entries:
            if entry.is_file(follow_symlinks=False):
                total += entry.stat(follow_symlinks=False).st_size
            elif entry.is_dir(follow_symlinks=False):
                total += directory_bytes(Path(entry.path))
    return total


def account_compound(task, compound):
    size = directory_bytes(compound_dir(task.owner_id, task.id, compound.id))
    task.artifact_bytes += size - compound.artifact_bytes
    compound.artifact_bytes = size


def account_task(db, task):
    """Reconcile only in-flight artifacts after interruption and the small worker log."""
    for compound in db.scalars(select(Compound).where(Compound.task_id == task.id, Compound.status == 'running')):
        account_compound(task, compound)
    if task.kind == 'prepare':
        receptor = db.get(Receptor, task.receptor_id)
        receptor.artifact_bytes = directory_bytes(receptor_dir(receptor.owner_id, receptor.id))
    log = task_dir(task.owner_id, task.id)/'worker.log'
    task.log_bytes = log.stat().st_size if log.exists() else 0


def _used_bytes(owner=None):
    # Aggregate the small upload/receptor/task tables in a single round trip.
    totals = []
    for model, expression in ((Upload, Upload.size), (Receptor, Receptor.artifact_bytes),
                              (Task, Task.artifact_bytes + Task.log_bytes)):
        query = select(func.coalesce(func.sum(expression), 0))
        if owner is not None:
            query = query.where(model.owner_id == owner)
        totals.append(query.scalar_subquery())
    return sum(totals)


def usage(owner=None, fresh=False, db=None):
    with nullcontext(db) if db is not None else Session() as query_db:
        total = query_db.scalar(select(_used_bytes(owner)))
    return dict(used_bytes=total, free_bytes=shutil.disk_usage(root()).free)


def check_capacity(settings, owner, additional=0, db=None):
    with nullcontext(db) if db is not None else Session() as query_db:
        total, owned = query_db.execute(select(_used_bytes(), _used_bytes(owner))).one()
    if total + additional > settings['storage_limit_gb'] * 1024**3:
        raise ValueError('플랫폼 저장 공간 한도에 도달했습니다.')
    if owned + additional > settings['user_storage_limit_gb'] * 1024**3:
        raise ValueError('학생별 저장 공간 한도에 도달했습니다.')
    if shutil.disk_usage(root()).free < additional + 2*1024**3:
        raise ValueError('서버 디스크 여유 공간이 부족합니다.')
