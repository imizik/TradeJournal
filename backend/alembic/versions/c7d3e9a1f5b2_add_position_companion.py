"""Options position companion (additive: a new table).

Revision ID: c7d3e9a1f5b2
Revises: 924f38989575
"""
from alembic import op
import sqlalchemy as sa

revision = "c7d3e9a1f5b2"
down_revision = "924f38989575"
branch_labels = None
depends_on = None


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    if "position_companion" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "position_companion",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("source_key", sa.String(), nullable=False),
        sa.Column("trade_id", sa.Uuid(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("contract", sa.String(), nullable=False),
        sa.Column("option_type", sa.String(), nullable=False),
        sa.Column("expiration", sa.Date(), nullable=False),
        sa.Column("opened_at", sa.DateTime(), nullable=False),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("watched", sa.Boolean(), nullable=False),
        sa.Column("investigation_id", sa.Uuid(), nullable=True),
        sa.Column("plan_json", sa.Text(), nullable=False),
        sa.Column("alert_id", sa.Uuid(), nullable=True),
        sa.Column("message_id", sa.String(), nullable=True),
        sa.Column("delivery", sa.String(), nullable=False),
        sa.Column("updates_json", sa.Text(), nullable=False),
        sa.Column("last_update_at", sa.DateTime(), nullable=True),
        sa.Column("last_underlying", sa.Float(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "source_key", name="uq_position_companion_position"),
    )
    op.create_index("ix_position_companion_source_key", "position_companion", ["source_key"])
    op.create_index("ix_position_companion_state", "position_companion", ["state"])


def downgrade():
    op.drop_table("position_companion")
