"""add visitor fallback retry count field

Revision ID: 0015_add_vtr_retry_count
Revises: 0014_add_visitor_message_stats
Create Date: 2024-12-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0015_add_vtr_retry_count'
down_revision: Union[str, None] = '0014_add_visitor_message_stats'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add ai_fallback_retry_count column to api_visitors table
    op.add_column(
        'api_visitors',
        sa.Column(
            'ai_fallback_retry_count',
            sa.Integer(),
            nullable=False,
            server_default=sa.text('0'),
            comment="Number of failed AI fallback attempts"
        )
    )


def downgrade() -> None:
    # Drop ai_fallback_retry_count column from api_visitors table
    op.drop_column('api_visitors', 'ai_fallback_retry_count')
