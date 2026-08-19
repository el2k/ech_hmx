"""add remote store agent fields to ai_agents

Revision ID: a2b3c4d5e6f7
Revises: f1g2h3i4j5k6
Create Date: 2026-01-19 14:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, None] = 'f1g2h3i4j5k6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add columns to ai_agents
    op.add_column('ai_agents', sa.Column('is_remote_store_agent', sa.Boolean(), nullable=False, server_default='false', comment='Whether this is a remote agent from store'))
    op.add_column('ai_agents', sa.Column('remote_agent_url', sa.String(length=255), nullable=True, comment='URL of the remote AgentOS server'))
    op.add_column('ai_agents', sa.Column('store_agent_id', sa.String(length=100), nullable=True, comment='Agent ID in the remote store'))


def downgrade() -> None:
    op.drop_column('ai_agents', 'store_agent_id')
    op.drop_column('ai_agents', 'remote_agent_url')
    op.drop_column('ai_agents', 'is_remote_store_agent')
