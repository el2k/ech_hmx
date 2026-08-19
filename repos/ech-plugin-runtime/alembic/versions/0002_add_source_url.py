"""add source_url to installed_plugins

Revision ID: 0002
Revises: 0001
Create Date: 2026-01-06 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('pg_installed_plugins', sa.Column('source_url', sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column('pg_installed_plugins', 'source_url')

