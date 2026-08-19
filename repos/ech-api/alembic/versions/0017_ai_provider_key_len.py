"""increase ai_provider api_key length

Revision ID: 0017_ai_provider_key_len
Revises: 0016_ai_disabled_null
Create Date: 2025-12-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0017_ai_provider_key_len'
down_revision: Union[str, None] = '0016_ai_disabled_null'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Increase api_key length to 500 in api_ai_providers table
    op.alter_column('api_ai_providers', 'api_key',
               existing_type=sa.String(length=255),
               type_=sa.String(length=500),
               existing_comment='API key/credential used to call the provider',
               existing_nullable=False)


def downgrade() -> None:
    # Revert api_key length to 255 in api_ai_providers table
    op.alter_column('api_ai_providers', 'api_key',
               existing_type=sa.String(length=500),
               type_=sa.String(length=255),
               existing_comment='API key/credential used to call the provider',
               existing_nullable=False)

