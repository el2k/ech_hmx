"""remove device model configuration fields

Revision ID: 0004_rm_device_model_config
Revises: 0003_add_device_model_config
Create Date: 2026-02-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0004_rm_device_model_config"
down_revision: Union[str, None] = "0003_add_device_model_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remove AI model configuration fields from dc_devices
    op.drop_column("dc_devices", "model")
    op.drop_column("dc_devices", "ai_provider_id")


def downgrade() -> None:
    # Re-add AI model configuration fields to dc_devices
    op.add_column(
        "dc_devices",
        sa.Column(
            "ai_provider_id",
            sa.String(length=100),
            nullable=True,
            comment="AI Provider ID for this device",
        ),
    )
    op.add_column(
        "dc_devices",
        sa.Column(
            "model",
            sa.String(length=100),
            nullable=True,
            comment="LLM model identifier for this device",
        ),
    )
