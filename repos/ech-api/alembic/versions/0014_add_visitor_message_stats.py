"""add visitor message stats fields

Revision ID: 0014_add_visitor_message_stats
Revises: 0013_add_platform_ai_fields
Create Date: 2024-12-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0014_add_visitor_message_stats'
down_revision: Union[str, None] = '0013_add_platform_ai_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add message statistics fields to api_visitors
    op.add_column(
        'api_visitors',
        sa.Column(
            'last_message_at',
            sa.DateTime(),
            nullable=True,
            comment="Time of the last message in the channel"
        )
    )
    op.add_column(
        'api_visitors',
        sa.Column(
            'visitor_send_count',
            sa.Integer(),
            nullable=False,
            server_default='0',
            comment="Total number of messages sent by the visitor"
        )
    )
    op.add_column(
        'api_visitors',
        sa.Column(
            'last_message_seq',
            sa.Integer(),
            nullable=False,
            server_default='0',
            comment="Sequence number of the last message in the channel"
        )
    )
    op.add_column(
        'api_visitors',
        sa.Column(
            'last_client_msg_no',
            sa.String(length=100),
            nullable=True,
            comment="Client message number of the last message in the channel"
        )
    )
    op.add_column(
        'api_visitors',
        sa.Column(
            'is_last_message_from_visitor',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
            comment="Whether the last message in the channel was sent by the visitor"
        )
    )
    op.add_column(
        'api_visitors',
        sa.Column(
            'is_last_message_from_ai',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
            comment="Whether the last message in the channel was sent by an AI"
        )
    )


def downgrade() -> None:
    op.drop_column('api_visitors', 'is_last_message_from_ai')
    op.drop_column('api_visitors', 'is_last_message_from_visitor')
    op.drop_column('api_visitors', 'last_client_msg_no')
    op.drop_column('api_visitors', 'last_message_seq')
    op.drop_column('api_visitors', 'visitor_send_count')
    op.drop_column('api_visitors', 'last_message_at')
