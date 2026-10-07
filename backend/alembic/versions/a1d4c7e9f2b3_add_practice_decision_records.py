"""Add immutable Practice decision records.

Revision ID: a1d4c7e9f2b3
Revises: b5d7e9f1a3c6
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1d4c7e9f2b3"
down_revision: Union[str, None] = "b5d7e9f1a3c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "decision_context" not in tables:
        op.create_table(
            "decision_context",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("operation_id", sa.String(), nullable=False),
            sa.Column("symbol", sa.String(), nullable=False),
            sa.Column("captured_at", sa.DateTime(), nullable=False),
            sa.Column("provider", sa.String(), nullable=False),
            sa.Column("data_json", sa.Text(), nullable=False),
            sa.Column("context_sha256", sa.String(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("operation_id", name="uq_decision_context_operation_id"),
        )
    inspector = sa.inspect(bind)
    if "decision_record" not in set(inspector.get_table_names()):
        op.create_table(
            "decision_record",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("operation_id", sa.String(), nullable=False),
            sa.Column("opportunity_id", sa.String(), nullable=False),
            sa.Column("actor", sa.String(), nullable=False),
            sa.Column("decision", sa.String(), nullable=False),
            sa.Column("symbol", sa.String(), nullable=False),
            sa.Column("context_id", sa.Uuid(), nullable=False),
            sa.Column("received_at", sa.DateTime(), nullable=False),
            sa.Column("input_cutoff", sa.DateTime(), nullable=False),
            sa.Column("policy_version", sa.String(), nullable=False),
            sa.Column("policy_hash", sa.String(), nullable=False),
            sa.Column("evidence_json", sa.Text(), nullable=False),
            sa.Column("evidence_sha256", sa.String(), nullable=False),
            sa.Column("decision_json", sa.Text(), nullable=False),
            sa.Column("record_sha256", sa.String(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["context_id"], ["decision_context.id"], ondelete="RESTRICT"),
            sa.UniqueConstraint("operation_id", name="uq_decision_record_operation_id"),
        )
    for table, columns in {
        "decision_context": ("operation_id", "symbol", "captured_at"),
        "decision_record": ("operation_id", "opportunity_id", "actor", "symbol", "context_id", "received_at"),
    }.items():
        existing = {index["name"] for index in sa.inspect(bind).get_indexes(table)}
        for column in columns:
            name = f"ix_{table}_{column}"
            if name not in existing:
                op.create_index(name, table, [column])


def downgrade() -> None:
    for name in ("received_at", "context_id", "symbol", "actor", "opportunity_id", "operation_id"):
        op.drop_index(f"ix_decision_record_{name}", table_name="decision_record")
    op.drop_table("decision_record")
    op.drop_index("ix_decision_context_captured_at", table_name="decision_context")
    op.drop_index("ix_decision_context_symbol", table_name="decision_context")
    op.drop_index("ix_decision_context_operation_id", table_name="decision_context")
    op.drop_table("decision_context")
