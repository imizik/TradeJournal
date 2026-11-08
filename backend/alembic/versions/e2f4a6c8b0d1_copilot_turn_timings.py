"""copilot_turn_timings

Revision ID: e2f4a6c8b0d1
Revises: d4e8a2c6f1b3
Create Date: 2026-11-08 18:00:00.000000

Where each copilot turn's wait went (docs/copilot-lab.md § What every turn records): the owner context read, each
round's model and tool time, and each tool call's time and split, as JSON text. Additive and nullable; older rows stay
as they are.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e2f4a6c8b0d1"
down_revision: Union[str, None] = "d4e8a2c6f1b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "copilot_turn" not in inspector.get_table_names():
        return
    if "timings" not in {column["name"] for column in inspector.get_columns("copilot_turn")}:
        op.add_column("copilot_turn", sa.Column("timings", sa.Text(), nullable=True))


def downgrade() -> None:
    # An additive column stays; nothing reads it on an older release.
    pass
