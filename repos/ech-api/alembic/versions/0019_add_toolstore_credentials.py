"""add toolstore credentials table

Revision ID: 0019_add_toolstore_credentials
Revises: 0018_channel_mem_clearance
Create Date: 2026-01-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0019_add_toolstore_credentials'
down_revision: Union[str, None] = '0018_channel_mem_clearance'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'api_toolstore_credentials',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('toolstore_user_id', sa.String(length=255), nullable=False),
        sa.Column('toolstore_email', sa.String(length=255), nullable=False),
        sa.Column('api_key_encrypted', sa.String(length=1024), nullable=False),
        sa.Column('refresh_token_encrypted', sa.String(length=1024), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['api_projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id')
    )


def downgrade() -> None:
    op.drop_table('api_toolstore_credentials')
