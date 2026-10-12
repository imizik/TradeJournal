"""add_setup_scanner_tables

Revision ID: a7c3e9f1b2d4
Revises: d6e1f2a3b4c5
Create Date: 2026-10-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7c3e9f1b2d4"
down_revision: Union[str, None] = "d6e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scanner_candidate",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scanner_version", sa.String(), nullable=False),
        sa.Column("params_hash", sa.String(), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("setup", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("bar_start", sa.DateTime(), nullable=False),
        sa.Column("bar_end", sa.DateTime(), nullable=False),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("stop", sa.Float(), nullable=False),
        sa.Column("target", sa.Float(), nullable=False),
        sa.Column("flags_json", sa.Text(), nullable=False),
        sa.Column("facts_json", sa.Text(), nullable=False),
        sa.Column("contract_json", sa.Text(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scanner_version", "symbol", "setup", "bar_end", name="uq_scanner_candidate_bar"),
    )
    op.create_index(op.f("ix_scanner_candidate_session_date"), "scanner_candidate", ["session_date"], unique=False)
    op.create_table(
        "scanner_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("effective_at", sa.DateTime(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.Column("data_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["scanner_candidate.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id", "key", name="uq_scanner_event_key"),
    )
    op.create_index(op.f("ix_scanner_event_candidate_id"), "scanner_event", ["candidate_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_scanner_event_candidate_id"), table_name="scanner_event")
    op.drop_table("scanner_event")
    op.drop_index(op.f("ix_scanner_candidate_session_date"), table_name="scanner_candidate")
    op.drop_table("scanner_candidate")
