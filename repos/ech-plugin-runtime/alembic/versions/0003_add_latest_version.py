"""add latest_version to installed_plugins

Revision ID: 0003
Revises: 0002
Create Date: 2026-01-06 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('pg_installed_plugins', sa.Column('latest_version', sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column('pg_installed_plugins', 'latest_version')

