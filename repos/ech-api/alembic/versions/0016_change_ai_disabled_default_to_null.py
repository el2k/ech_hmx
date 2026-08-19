"""change ai_disabled default to null and drop platform ai_disabled column

Revision ID: 0016_ai_disabled_null
Revises: 0015_add_vtr_retry_count
Create Date: 2025-12-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0016_ai_disabled_null'
down_revision: Union[str, None] = '0015_add_vtr_retry_count'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Update existing False values to NULL in api_visitors
    op.execute(sa.text("UPDATE api_visitors SET ai_disabled = NULL WHERE ai_disabled = FALSE"))
    
    # Migrate platform ai_disabled=True to ai_mode='off' before dropping column
    # Split into two separate updates to avoid any potential issues
    # First update: rows where ai_mode is NULL
    op.execute(sa.text("UPDATE api_platforms SET ai_mode = 'off' WHERE ai_disabled = TRUE AND ai_mode IS NULL"))
    
    # Second update: rows where ai_mode is 'auto'  
    op.execute(sa.text("UPDATE api_platforms SET ai_mode = 'off' WHERE ai_disabled = TRUE AND ai_mode = 'auto'"))
    
    # Drop ai_disabled column from api_platforms (replaced by ai_mode)
    op.drop_column("api_platforms", "ai_disabled")


def downgrade() -> None:
    # Re-add ai_disabled column to api_platforms
    op.add_column(
        "api_platforms",
        sa.Column("ai_disabled", sa.Boolean(), nullable=True, comment="Whether AI responses are disabled for this platform")
    )
    
    # Migrate ai_mode='off' back to ai_disabled=True
    op.execute("UPDATE api_platforms SET ai_disabled = TRUE WHERE ai_mode = 'off'")
    
    # Revert NULL to False in api_visitors
    op.execute("UPDATE api_visitors SET ai_disabled = FALSE WHERE ai_disabled IS NULL")

