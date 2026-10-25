"""Persist bounded personal synthetic replay attempts.

Revision ID: c2f8a1d4e6b9
Revises: b2c9e4f7a1d3
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c2f8a1d4e6b9"
down_revision: Union[str, None] = "b2c9e4f7a1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("practice_replay_attempt"):
        op.create_table(
            "practice_replay_attempt",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("operation_id", sa.Uuid(), nullable=False),
            sa.Column("scenario_id", sa.String(), nullable=False),
            sa.Column("state_json", sa.Text(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("operation_id", name="uq_practice_replay_operation_id"),
        )
    existing = {index["name"] for index in sa.inspect(bind).get_indexes("practice_replay_attempt")}
    for column in ("operation_id", "scenario_id", "created_at"):
        name = f"ix_practice_replay_attempt_{column}"
        if name not in existing:
            op.create_index(name, "practice_replay_attempt", [column])


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("practice_replay_attempt"):
        existing = {index["name"] for index in sa.inspect(bind).get_indexes("practice_replay_attempt")}
        for column in ("created_at", "scenario_id", "operation_id"):
            name = f"ix_practice_replay_attempt_{column}"
            if name in existing:
                op.drop_index(name, table_name="practice_replay_attempt")
        op.drop_table("practice_replay_attempt")
