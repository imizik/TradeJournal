"""Plan follow-through (additive): a level alert's plan role and a plan time-stop table.

Revision ID: c7e3a9f1d5b2
Revises: b2c9e4f7a1d3
"""
from alembic import op
import sqlalchemy as sa

revision = "c7e3a9f1d5b2"
down_revision = "b2c9e4f7a1d3"
branch_labels = None
depends_on = None


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    inspector = sa.inspect(op.get_bind())
    if "plan_role" not in {c["name"] for c in inspector.get_columns("level_alert")}:
        op.add_column("level_alert", sa.Column("plan_role", sa.String(), nullable=True))
    if "plan_time_stop" in inspector.get_table_names():
        return
    op.create_table(
        "plan_time_stop",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("investigation_id", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("due_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("delivery", sa.String(), nullable=False),
        sa.Column("trade_id", sa.Uuid(), nullable=True),
        sa.Column("detected_at", sa.DateTime(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id"),
    )
    op.create_index("ix_plan_time_stop_investigation_id", "plan_time_stop", ["investigation_id"])
    op.create_index("ix_plan_time_stop_delivery", "plan_time_stop", ["delivery"])


def downgrade():
    op.drop_table("plan_time_stop")
    op.drop_column("level_alert", "plan_role")
