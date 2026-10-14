"""Recount restored/imported artifacts during maintenance, with scheduler stopped."""
from sqlalchemy import select
from dockschedule.db import transaction
from dockschedule.models import Compound, Receptor, Task
from dockschedule.storage import account_compound, account_task, directory_bytes, receptor_dir

with transaction() as db:
    for receptor in db.scalars(select(Receptor)):
        receptor.artifact_bytes = directory_bytes(receptor_dir(receptor.owner_id, receptor.id))
    for task in db.scalars(select(Task)):
        task.artifact_bytes = 0
        for compound in db.scalars(select(Compound).where(Compound.task_id == task.id).execution_options(yield_per=500)):
            compound.artifact_bytes = 0
            account_compound(task, compound)
        account_task(db, task)
print('Retained artifact accounting reconciled.')
