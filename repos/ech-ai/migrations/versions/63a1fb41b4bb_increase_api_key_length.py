"""increase_api_key_length

Revision ID: 63a1fb41b4bb
Revises: 0002_remove_alias_unique
Create Date: 2025-12-31 10:05:36.604797

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '63a1fb41b4bb'
down_revision: Union[str, None] = '0002_remove_alias_unique'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Increase api_key length to 500
    with op.batch_alter_table('ai_llm_providers', schema=None) as batch_op:
        batch_op.alter_column('api_key',
               existing_type=sa.String(length=255),
               type_=sa.String(length=500),
               existing_nullable=True)


def downgrade() -> None:
    # Decrease api_key length to 255
    with op.batch_alter_table('ai_llm_providers', schema=None) as batch_op:
        batch_op.alter_column('api_key',
               existing_type=sa.String(length=500),
               type_=sa.String(length=255),
               existing_nullable=True)
