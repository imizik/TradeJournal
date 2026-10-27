"""Shadow book (additive): the copilot's own paper decisions on Radar events and their append-only paper facts.

Revision ID: 9ff22204d1d2
Revises: b7d3f1a9c5e2
"""
from alembic import op
import sqlalchemy as sa

revision = "9ff22204d1d2"
down_revision = "b7d3f1a9c5e2"
branch_labels = None
depends_on = None


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    tables = sa.inspect(op.get_bind()).get_table_names()
    if "shadow_book_decision" not in tables:
        op.create_table(
            "shadow_book_decision",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("radar_event_id", sa.String(), nullable=False),
            sa.Column("session_date", sa.Date(), nullable=False),
            sa.Column("symbol", sa.String(), nullable=True),
            sa.Column("event_json", sa.Text(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("plan_json", sa.Text(), nullable=True),
            sa.Column("model", sa.String(), nullable=True),
            sa.Column("claimed_at", sa.DateTime(), nullable=False),
            sa.Column("decided_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("radar_event_id"),
        )
        op.create_index("ix_shadow_book_decision_session_date", "shadow_book_decision", ["session_date"])
    if "shadow_book_event" not in tables:
        op.create_table(
            "shadow_book_event",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("decision_id", sa.Uuid(), nullable=False),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("effective_at", sa.DateTime(), nullable=False),
            sa.Column("recorded_at", sa.DateTime(), nullable=False),
            sa.Column("data_json", sa.Text(), nullable=False),
            sa.ForeignKeyConstraint(["decision_id"], ["shadow_book_decision.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("decision_id", "event_type", name="uq_shadow_book_event_type"),
        )
        op.create_index("ix_shadow_book_event_decision_id", "shadow_book_event", ["decision_id"])


def downgrade():
    op.drop_index("ix_shadow_book_event_decision_id", table_name="shadow_book_event")
    op.drop_table("shadow_book_event")
    op.drop_index("ix_shadow_book_decision_session_date", table_name="shadow_book_decision")
    op.drop_table("shadow_book_decision")
