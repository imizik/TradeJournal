"""Add append-only Practice paper events (A2).

Revision ID: a2e5b8c1d7f4
Revises: a1d4c7e9f2b3
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a2e5b8c1d7f4"
down_revision: Union[str, None] = "a1d4c7e9f2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if "decision_event" not in set(sa.inspect(bind).get_table_names()):
        op.create_table(
            "decision_event",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("record_id", sa.Uuid(), nullable=False),
            sa.Column("seq", sa.Integer(), nullable=False),
            sa.Column("key", sa.String(), nullable=False),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("effective_at", sa.DateTime(), nullable=False),
            sa.Column("recorded_at", sa.DateTime(), nullable=False),
            sa.Column("exec_version", sa.String(), nullable=False),
            sa.Column("source", sa.String(), nullable=False),
            sa.Column("reconstructed", sa.Boolean(), nullable=False),
            sa.Column("data_json", sa.Text(), nullable=False),
            sa.Column("delivery", sa.String(), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
            sa.Column("claimed_at", sa.DateTime(), nullable=True),
            sa.Column("delivered_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["record_id"], ["decision_record.id"], ondelete="RESTRICT"),
            sa.UniqueConstraint("record_id", "key", name="uq_decision_event_key"),
            sa.UniqueConstraint("record_id", "seq", name="uq_decision_event_seq"),
        )
    existing = {index["name"] for index in sa.inspect(bind).get_indexes("decision_event")}
    for column in ("record_id", "delivery"):
        if f"ix_decision_event_{column}" not in existing:
            op.create_index(f"ix_decision_event_{column}", "decision_event", [column])


def downgrade() -> None:
    op.drop_index("ix_decision_event_delivery", table_name="decision_event")
    op.drop_index("ix_decision_event_record_id", table_name="decision_event")
    op.drop_table("decision_event")
