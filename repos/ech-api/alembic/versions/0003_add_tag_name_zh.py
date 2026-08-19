"""Add name_zh field to api_tags table.

Revision ID: 0003_add_tag_name_zh
Revises: api_0002_add_visitor_nickname_zh
Create Date: 2024-12-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0003_add_tag_name_zh"
down_revision: Union[str, None] = "api_0002_add_visitor_nickname_zh"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add name_zh column to api_tags table."""
    # Check if column already exists to ensure idempotency
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col["name"] for col in inspector.get_columns("api_tags")]
    
    if "name_zh" not in columns:
        op.add_column(
            "api_tags",
            sa.Column(
                "name_zh",
                sa.String(50),
                nullable=True,
                comment="Tag name in Chinese",
            ),
        )


def downgrade() -> None:
    """Remove name_zh column from api_tags table."""
    op.drop_column("api_tags", "name_zh")

