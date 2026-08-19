"""Add service_paused field to staff table.

Revision ID: 0007
Revises: 0006
Create Date: 2025-01-09

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0007_service_paused"
down_revision: Union[str, None] = "0006_assignment_rule"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add service_paused column to api_staff table."""
    
    op.add_column(
        "api_staff",
        sa.Column(
            "service_paused",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Whether staff has paused accepting new visitors"
        )
    )


def downgrade() -> None:
    """Remove service_paused column from api_staff table."""
    
    op.drop_column("api_staff", "service_paused")
