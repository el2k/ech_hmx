"""add channel memory clearance table

Revision ID: 0018_add_channel_memory_clearance
Revises: 0017_ai_provider_key_len
Create Date: 2026-01-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0018_channel_mem_clearance'
down_revision: Union[str, None] = '0017_ai_provider_key_len'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'api_channel_memory_clearances',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_type', sa.String(length=20), nullable=False),
        sa.Column('channel_id', sa.String(length=255), nullable=False),
        sa.Column('channel_type', sa.Integer(), nullable=False),
        sa.Column('cleared_message_seq', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['api_projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'user_type', 'channel_id', 'channel_type', name='uq_user_channel_clearance')
    )
    op.create_index('ix_clearance_user_channel', 'api_channel_memory_clearances', ['user_id', 'user_type', 'channel_id', 'channel_type'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_clearance_user_channel', table_name='api_channel_memory_clearances')
    op.drop_table('api_channel_memory_clearances')
