"""add toolstore fields to ai_tools

Revision ID: a1b2c3d4e5f6
Revises: b6e7d8c9a0b1
Create Date: 2026-01-12 11:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'b6e7d8c9a0b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create enum type
    # For Postgres, we need to create the enum type before using it in a column
    # Use execute to handle IF NOT EXISTS since SQLAlchemy's Enum.create doesn't always support it well in migrations
    op.execute("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tool_source_type_enum') THEN CREATE TYPE tool_source_type_enum AS ENUM ('LOCAL', 'TOOLSTORE'); END IF; END $$;")

    # 2. Add columns to ai_tools
    op.add_column('ai_tools', sa.Column('tool_source_type', sa.Enum('LOCAL', 'TOOLSTORE', name='tool_source_type_enum'), nullable=False, server_default='LOCAL', comment='Tool source (LOCAL or TOOLSTORE)'))
    op.add_column('ai_tools', sa.Column('toolstore_tool_id', sa.String(length=255), nullable=True, comment='Associated ToolStore tool ID'))


def downgrade() -> None:
    op.drop_column('ai_tools', 'toolstore_tool_id')
    op.drop_column('ai_tools', 'tool_source_type')
    # We don't drop the enum type in downgrade to avoid issues if other tables start using it
