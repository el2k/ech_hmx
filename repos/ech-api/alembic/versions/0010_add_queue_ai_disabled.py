"""Add ai_disabled field to waiting queue table.

Revision ID: 0010
Revises: 0009
Create Date: 2025-01-14

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0010_queue_ai_disabled"
down_revision: Union[str, None] = "0009_queue_expired_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add ai_disabled column to api_visitor_waiting_queue table.
    This field indicates whether AI responses should be disabled for the visitor in queue.
    When None, the visitor's current ai_disabled setting is preserved.
    """
    
    # Add ai_disabled column to waiting queue table (nullable)
    op.add_column(
        "api_visitor_waiting_queue",
        sa.Column(
            "ai_disabled",
            sa.Boolean(),
            nullable=True,
            server_default=None,
            comment="Whether AI responses should be disabled (None=keep current, True=disable, False=enable)",
        ),
    )


def downgrade() -> None:
    """Remove ai_disabled column."""
    
    op.drop_column("api_visitor_waiting_queue", "ai_disabled")
