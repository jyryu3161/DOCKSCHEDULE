"""Add GNINA rescoring table and the gnina_top_n admin setting."""
import json

from alembic import op
import sqlalchemy as sa

revision = 'c4e8a1d57f23'
down_revision = 'b63d14a829f0'
branch_labels = None
depends_on = None

settings = sa.table('settings', sa.column('id', sa.Integer), sa.column('values', sa.JSON))


def upgrade():
    op.create_table('gnina_scores',
        sa.Column('compound_id', sa.Integer(), sa.ForeignKey('compounds.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('task_id', sa.String(32), sa.ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('job_id', sa.String(32), sa.ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(20), nullable=False), sa.Column('error', sa.Text()),
        sa.Column('cnn_score', sa.Float()), sa.Column('cnn_affinity', sa.Float()),
        sa.Column('cnn_vs', sa.Float()), sa.Column('gnina_vina', sa.Float()),
        sa.Column('details', sa.JSON(), nullable=False))
    op.create_index('gnina_queue', 'gnina_scores', ['task_id', 'status'])
    # DEFAULT_SETTINGS only seeds a brand-new settings row, and readers index settings(db)['key'] directly.
    bind = op.get_bind()
    for row in bind.execute(sa.select(settings.c.id, settings.c['values'])).fetchall():
        values = row[1] if isinstance(row[1], dict) else json.loads(row[1] or '{}')
        if 'gnina_top_n' not in values:
            values = {**values, 'gnina_top_n': min(1000, values.get('max_compounds', 1000))}
            bind.execute(settings.update().where(settings.c.id == row[0]).values(values=values))


def downgrade():
    bind = op.get_bind()
    for row in bind.execute(sa.select(settings.c.id, settings.c['values'])).fetchall():
        values = row[1] if isinstance(row[1], dict) else json.loads(row[1] or '{}')
        if 'gnina_top_n' in values:
            values = {k: v for k, v in values.items() if k != 'gnina_top_n'}
            bind.execute(settings.update().where(settings.c.id == row[0]).values(values=values))
    op.drop_table('gnina_scores')
