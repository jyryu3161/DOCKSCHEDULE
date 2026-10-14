"""Account retained artifact bytes without scanning whole libraries.

Revision ID: 742e1d0bc899
Revises: 21f4ef049b76
"""
from alembic import op
import sqlalchemy as sa

revision = '742e1d0bc899'
down_revision = '21f4ef049b76'
branch_labels = None
depends_on = None


def upgrade():
    for table, column in [('receptors', 'artifact_bytes'), ('tasks', 'artifact_bytes'),
                          ('tasks', 'log_bytes'), ('compounds', 'artifact_bytes')]:
        op.add_column(table, sa.Column(column, sa.BigInteger(), nullable=False, server_default='0'))


def downgrade():
    for table, column in [('compounds', 'artifact_bytes'), ('tasks', 'log_bytes'),
                          ('tasks', 'artifact_bytes'), ('receptors', 'artifact_bytes')]:
        op.drop_column(table, column)
