"""Telegram notes in the day journal (additive): ``day_journal_entry.context_json``, a nullable text column holding a
note's tickers, the symbols open when it was sent and the ping it replied to. Nothing existing changes.

Revision ID: a3c7e1f9b2d4
Revises: e2b6d0f4a8c1
"""
from alembic import op
import sqlalchemy as sa

revision = "a3c7e1f9b2d4"
down_revision = "e2b6d0f4a8c1"
branch_labels = None
depends_on = None

TABLE = "day_journal_entry"


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    if "context_json" not in {col["name"] for col in sa.inspect(op.get_bind()).get_columns(TABLE)}:
        op.add_column(TABLE, sa.Column("context_json", sa.Text(), nullable=True))


def downgrade():
    op.drop_column(TABLE, "context_json")
