"""Add expired_at to waiting queue and queue_wait_timeout_minutes to assignment rules.

Revision ID: 0009
Revises: 0008
Create Date: 2025-01-09

"""

from datetime import datetime, timedelta
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0009_queue_expired_at"
down_revision: Union[str, None] = "0008_staff_is_active"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add expired_at column to api_visitor_waiting_queue table.
    Add queue_wait_timeout_minutes column to api_visitor_assignment_rules table.
    Remove retry_count column from api_visitor_waiting_queue table.
    """
    
    # Add expired_at column to waiting queue
    op.add_column(
        "api_visitor_waiting_queue",
        sa.Column(
            "expired_at",
            sa.DateTime(),
            nullable=True,
            comment="When this entry should expire if not assigned",
        ),
    )
    
    # Add queue_wait_timeout_minutes to assignment rules
    op.add_column(
        "api_visitor_assignment_rules",
        sa.Column(
            "queue_wait_timeout_minutes",
            sa.Integer(),
            nullable=True,
            server_default="30",
            comment="Maximum wait time in queue before expiring (minutes)",
        ),
    )
    
    # Set expired_at for existing WAITING entries (30 minutes from now)
    # This ensures existing entries don't immediately expire
    op.execute(
        """
        UPDATE api_visitor_waiting_queue
        SET expired_at = NOW() + INTERVAL '30 minutes'
        WHERE status = 'waiting' AND expired_at IS NULL
        """
    )
    
    # Drop retry_count column as it's no longer needed
    op.drop_column("api_visitor_waiting_queue", "retry_count")


def downgrade() -> None:
    """Reverse the changes."""
    
    # Add back retry_count column
    op.add_column(
        "api_visitor_waiting_queue",
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Number of assignment retry attempts",
        ),
    )
    
    # Drop queue_wait_timeout_minutes from assignment rules
    op.drop_column("api_visitor_assignment_rules", "queue_wait_timeout_minutes")
    
    # Drop expired_at column from waiting queue
    op.drop_column("api_visitor_waiting_queue", "expired_at")
