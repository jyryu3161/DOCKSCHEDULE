from alembic import context
from dockschedule.db import Base, engine
import dockschedule.models

with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
