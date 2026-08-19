"""add platform usage tracking fields

Revision ID: 0012_add_platform_usage_tracking
Revises: 0011_visitor_locale_fields
Create Date: 2024-12-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0012_add_platform_usage_tracking'
down_revision: Union[str, None] = '0011_visitor_locale_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add usage tracking fields to api_platforms
    op.add_column(
        'api_platforms',
        sa.Column(
            'is_used',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
            comment="Whether the platform (specifically website type) has been used"
        )
    )
    op.add_column(
        'api_platforms',
        sa.Column(
            'used_website_url',
            sa.String(length=1024),
            nullable=True,
            comment="The URL of the website where this platform was first used"
        )
    )
    op.add_column(
        'api_platforms',
        sa.Column(
            'used_website_title',
            sa.String(length=255),
            nullable=True,
            comment="The title of the website where this platform was first used"
        )
    )


def downgrade() -> None:
    op.drop_column('api_platforms', 'used_website_title')
    op.drop_column('api_platforms', 'used_website_url')
    op.drop_column('api_platforms', 'is_used')
