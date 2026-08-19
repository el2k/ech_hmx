"""Add is_active field to staff table.

Revision ID: 0008
Revises: 0007
Create Date: 2025-01-09

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0008_staff_is_active"
down_revision: Union[str, None] = "0007_service_paused"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add is_active column to api_staff table."""
    
    op.add_column(
        "api_staff",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="Whether staff is active for service (long-term switch, e.g., off-duty, resigned)"
        )
    )


def downgrade() -> None:
    """Remove is_active column from api_staff table."""
    
    op.drop_column("api_staff", "is_active")
