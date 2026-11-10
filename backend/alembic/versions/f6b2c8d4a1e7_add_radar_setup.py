"""Radar setup cards (additive): one frozen trade idea per setup-kind Radar event, its Plan it tap and paper result.

Revision ID: f6b2c8d4a1e7
Revises: e2f4a6c8b0d1
"""
from alembic import op
import sqlalchemy as sa

revision = "f6b2c8d4a1e7"
down_revision = "e2f4a6c8b0d1"
branch_labels = None
depends_on = None


def upgrade():
    # A new table only: existing tables and rows stay unchanged (and the create_all-before-upgrade path is tolerated).
    if "radar_setup" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "radar_setup",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("session_date", sa.String(), nullable=False),
        sa.Column("rule_version", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("entry", sa.Float(), nullable=False),
        sa.Column("invalidation", sa.Float(), nullable=False),
        sa.Column("contract_json", sa.Text(), nullable=True),
        sa.Column("record_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("plan_state", sa.String(), server_default="none", nullable=False),
        sa.Column("planned_at", sa.DateTime(), nullable=True),
        sa.Column("investigation_id", sa.String(), nullable=True),
        sa.Column("plan_note", sa.Text(), nullable=True),
        sa.Column("paper_state", sa.String(), server_default="none", nullable=False),
        sa.Column("paper_entry_price", sa.Float(), nullable=True),
        sa.Column("paper_entry_at", sa.DateTime(), nullable=True),
        sa.Column("paper_exit_price", sa.Float(), nullable=True),
        sa.Column("paper_exit_at", sa.DateTime(), nullable=True),
        sa.Column("paper_exit_reason", sa.String(), nullable=True),
        sa.Column("paper_pnl", sa.Float(), nullable=True),
        sa.Column("paper_note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_radar_setup_event"),
    )
    op.create_index("ix_radar_setup_event_id", "radar_setup", ["event_id"])
    op.create_index("ix_radar_setup_session_date", "radar_setup", ["session_date"])
    op.create_index("ix_radar_setup_symbol", "radar_setup", ["symbol"])
    op.create_index("ix_radar_setup_paper_state", "radar_setup", ["paper_state"])


def downgrade():
    op.drop_table("radar_setup")
