"""Index pending compounds in input order for large screening libraries.

Revision ID: 9b7c31e2a640
Revises: 742e1d0bc899
"""
from alembic import op

revision = '9b7c31e2a640'
down_revision = '742e1d0bc899'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index('compound_status', table_name='compounds')
    op.create_index('compound_status', 'compounds', ['task_id', 'status', 'row_number'])


def downgrade():
    op.drop_index('compound_status', table_name='compounds')
    op.create_index('compound_status', 'compounds', ['task_id', 'status'])
