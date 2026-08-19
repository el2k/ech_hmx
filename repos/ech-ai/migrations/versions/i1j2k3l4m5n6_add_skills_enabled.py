"""add skills_enabled to ai_agents

Revision ID: i1j2k3l4m5n6
Revises: h1i2j3k4l5m6
Create Date: 2026-02-07 10:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'i1j2k3l4m5n6'
down_revision: Union[str, None] = 'h1i2j3k4l5m6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'ai_agents',
        sa.Column(
            'skills_enabled',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('true'),
            comment='Whether to enable skill discovery for this agent'
        )
    )


def downgrade() -> None:
    op.drop_column('ai_agents', 'skills_enabled')
