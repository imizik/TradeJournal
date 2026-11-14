"""His own trading rules (additive): ``trading_rule_record`` holds each saved list of his rules and each real order's
checklist kept when he copies it from the Ticket. A new table only; nothing existing changes.

Revision ID: c4e8a2d6f0b3
Revises: 7f3b276ac082
"""
from alembic import op
import sqlalchemy as sa

revision = "c4e8a2d6f0b3"
down_revision = "7f3b276ac082"
branch_labels = None
depends_on = None


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    if "trading_rule_record" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "trading_rule_record",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("record_key", sa.String(), nullable=False),
        sa.Column("investigation_id", sa.String(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.Column("data_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_key"),
    )
    op.create_index("ix_trading_rule_record_kind", "trading_rule_record", ["kind"])
    op.create_index("ix_trading_rule_record_investigation_id", "trading_rule_record", ["investigation_id"])
    op.create_index("ix_trading_rule_record_recorded_at", "trading_rule_record", ["recorded_at"])


def downgrade():
    op.drop_index("ix_trading_rule_record_recorded_at", table_name="trading_rule_record")
    op.drop_index("ix_trading_rule_record_investigation_id", table_name="trading_rule_record")
    op.drop_index("ix_trading_rule_record_kind", table_name="trading_rule_record")
    op.drop_table("trading_rule_record")
