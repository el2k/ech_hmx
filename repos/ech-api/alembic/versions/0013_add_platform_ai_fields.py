"""add platform ai config fields

Revision ID: 0013_add_platform_ai_fields
Revises: 0012_add_platform_usage_tracking
Create Date: 2024-12-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0013_add_platform_ai_fields'
down_revision: Union[str, None] = '0012_add_platform_usage_tracking'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add AI configuration fields to api_platforms
    op.add_column(
        'api_platforms',
        sa.Column(
            'agent_ids',
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=True,
            comment="List of AI Agent IDs assigned to this platform"
        )
    )
    op.add_column(
        'api_platforms',
        sa.Column(
            'ai_mode',
            sa.String(length=20),
            nullable=True,
            server_default='auto',
            comment="AI mode: auto (AI handles all), assist (human first, AI fallback), off (AI disabled)"
        )
    )
    op.add_column(
        'api_platforms',
        sa.Column(
            'fallback_to_ai_timeout',
            sa.Integer(),
            nullable=True,
            server_default='0',
            comment="Timeout in seconds before AI takes over when ai_mode=assist. 0 means AI never takes over."
        )
    )


def downgrade() -> None:
    op.drop_column('api_platforms', 'fallback_to_ai_timeout')
    op.drop_column('api_platforms', 'ai_mode')
    op.drop_column('api_platforms', 'agent_ids')

