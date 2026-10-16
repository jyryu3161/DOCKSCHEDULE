"""Persist resumable library interaction analyses and residue/type lookup."""
from alembic import op
import sqlalchemy as sa

revision = 'b63d14a829f0'
down_revision = '9b7c31e2a640'
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == 'sqlite':
        # Recreating tasks with FK enforcement would cascade-delete compounds.
        op.execute('ALTER TABLE tasks ADD COLUMN source_task_id VARCHAR(32) REFERENCES tasks(id) ON DELETE CASCADE')
    else:
        op.add_column('tasks', sa.Column('source_task_id', sa.String(32), nullable=True))
        op.create_foreign_key('task_source_fk', 'tasks', 'tasks', ['source_task_id'], ['id'], ondelete='CASCADE')
    op.create_index('ix_tasks_source_task_id', 'tasks', ['source_task_id'])
    op.create_table('compound_analyses',
        sa.Column('compound_id', sa.Integer(), sa.ForeignKey('compounds.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('job_id', sa.String(32), sa.ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(20), nullable=False), sa.Column('error', sa.Text()))
    op.create_index('analysis_queue', 'compound_analyses', ['job_id', 'status', 'compound_id'])
    op.create_table('interaction_hits',
        sa.Column('compound_id', sa.Integer(), sa.ForeignKey('compound_analyses.compound_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('residue_key', sa.String(80), primary_key=True),
        sa.Column('kind', sa.String(30), primary_key=True),
        sa.Column('task_id', sa.String(32), sa.ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('residue', sa.JSON(), nullable=False), sa.Column('count', sa.Integer(), nullable=False),
        sa.Column('distance', sa.Float(), nullable=False))
    op.create_index('interaction_lookup', 'interaction_hits', ['task_id', 'residue_key', 'kind', 'compound_id'])


def downgrade():
    op.drop_table('interaction_hits')
    op.drop_table('compound_analyses')
    op.drop_index('ix_tasks_source_task_id', table_name='tasks')
    if op.get_bind().dialect.name != 'sqlite':
        op.drop_constraint('task_source_fk', 'tasks', type_='foreignkey')
    op.drop_column('tasks', 'source_task_id')
