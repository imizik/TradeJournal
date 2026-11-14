"""The desk's account value line (additive): one row per account per reading of the live account feed, kept a week.

Revision ID: c5e9a3d7f1b4
Revises: d7f3b9e5a1c8
"""
from alembic import op
import sqlalchemy as sa

revision = "c5e9a3d7f1b4"
down_revision = "d7f3b9e5a1c8"
branch_labels = None
depends_on = None


def upgrade():
    # A new table only: existing tables and rows stay unchanged (and the create_all-before-upgrade path is tolerated).
    if "desk_account_value" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "desk_account_value",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("day", sa.String(), nullable=False),
        sa.Column("at", sa.Integer(), nullable=False),
        sa.Column("masked", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("total_value", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("at", "masked", name="uq_desk_account_value_reading"),
    )
    op.create_index("ix_desk_account_value_day", "desk_account_value", ["day"])
    op.create_index("ix_desk_account_value_at", "desk_account_value", ["at"])


def downgrade():
    op.drop_table("desk_account_value")
