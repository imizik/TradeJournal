"""A note on a trade from the desk (additive): ``trade_capture_note`` gains the trade's anchor (``account_id`` and
``source_key``, as ``capture_link`` holds them), and ``capture_id`` may be empty for a note on a trade with no plan.
Nullable, no default and no backfill: every existing note keeps its plan and reads exactly as before.

Revision ID: e2c6a8f4b1d9
Revises: c5e9a3d7f1b4
"""
from alembic import op
import sqlalchemy as sa

revision = "e2c6a8f4b1d9"
down_revision = "c5e9a3d7f1b4"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {c["name"]: c for c in sa.inspect(bind).get_columns("trade_capture_note")}
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("trade_capture_note")}
    # Also tolerate the existing supported create_all-before-upgrade path (the columns already there).
    with op.batch_alter_table("trade_capture_note") as batch:
        if "account_id" not in columns:
            batch.add_column(sa.Column("account_id", sa.Uuid(), nullable=True))
        if "source_key" not in columns:
            batch.add_column(sa.Column("source_key", sa.String(), nullable=True))
        if not columns["capture_id"]["nullable"]:
            batch.alter_column("capture_id", existing_type=sa.Uuid(), nullable=True)
    if "ix_trade_capture_note_source_key" not in indexes:
        op.create_index("ix_trade_capture_note_source_key", "trade_capture_note", ["source_key"])


def downgrade():
    # A note with no plan cannot stay once a plan is required again.
    op.execute("DELETE FROM trade_capture_note WHERE capture_id IS NULL")
    op.drop_index("ix_trade_capture_note_source_key", table_name="trade_capture_note")
    with op.batch_alter_table("trade_capture_note") as batch:
        batch.alter_column("capture_id", existing_type=sa.Uuid(), nullable=False)
        batch.drop_column("source_key")
        batch.drop_column("account_id")
