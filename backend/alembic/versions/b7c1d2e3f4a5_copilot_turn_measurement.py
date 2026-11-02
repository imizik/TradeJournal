"""copilot_turn_measurement

Revision ID: b7c1d2e3f4a5
Revises: f6a8b0c2d4e6
Create Date: 2026-11-01 20:00:00.000000

What each copilot turn was for and how it went (docs/copilot-lab.md § Measuring the copilot): the kind of question,
where it came from, the thread it belongs to, the tools it read, the owner's wait, cache writes, and the error code
when it failed. Additive and nullable; older rows stay as they are.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c1d2e3f4a5"
down_revision: Union[str, None] = "f6a8b0c2d4e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = (
    ("kind", sa.String()),
    ("source", sa.String()),
    ("investigation_id", sa.Uuid()),
    ("tool_names", sa.Text()),
    ("first_text_ms", sa.Integer()),
    ("max_silence_ms", sa.Integer()),
    ("cache_creation_input_tokens", sa.Integer()),
    ("error", sa.String()),
    ("effort", sa.String()),
    ("evidence", sa.String()),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "copilot_turn" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("copilot_turn")}
    for name, column_type in COLUMNS:
        if name not in existing:
            op.add_column("copilot_turn", sa.Column(name, column_type, nullable=True))
    indexes = {index["name"] for index in inspector.get_indexes("copilot_turn")}
    if "ix_copilot_turn_investigation_id" not in indexes:
        op.create_index("ix_copilot_turn_investigation_id", "copilot_turn", ["investigation_id"])
    if "ix_copilot_turn_kind" not in indexes:
        op.create_index("ix_copilot_turn_kind", "copilot_turn", ["kind"])


def downgrade() -> None:
    # Additive columns stay; nothing reads them on an older release.
    pass
