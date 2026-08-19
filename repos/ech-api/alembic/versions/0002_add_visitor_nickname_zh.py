"""Add nickname_zh to api_visitors table."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "api_0002_add_visitor_nickname_zh"
down_revision = "6595c48378f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add nickname_zh column to api_visitors table."""
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [c['name'] for c in inspector.get_columns('api_visitors')]

    if 'nickname_zh' not in columns:
        op.add_column(
            'api_visitors',
            sa.Column(
                'nickname_zh',
                sa.String(100),
                nullable=True,
                comment='Visitor nickname in Chinese'
            )
        )


def downgrade() -> None:
    """Remove nickname_zh column from api_visitors table."""
    op.drop_column('api_visitors', 'nickname_zh')

