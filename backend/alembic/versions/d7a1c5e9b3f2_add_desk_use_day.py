"""How he uses the desk (additive): ``desk_use_day`` holds daily opens, taps and seconds on screen per desk piece and
device size. A new table only; nothing existing changes.

Revision ID: d7a1c5e9b3f2
Revises: c4e8a2d6f0b3
"""
from alembic import op
import sqlalchemy as sa

revision = "d7a1c5e9b3f2"
down_revision = "c4e8a2d6f0b3"
branch_labels = None
depends_on = None


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    if "desk_use_day" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "desk_use_day",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("size", sa.String(), nullable=False),
        sa.Column("piece", sa.String(), nullable=False),
        sa.Column("opens", sa.Integer(), nullable=False),
        sa.Column("taps", sa.Integer(), nullable=False),
        sa.Column("seen_s", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("day", "size", "piece", name="uq_desk_use_day_piece"),
    )
    op.create_index("ix_desk_use_day_day", "desk_use_day", ["day"])


def downgrade():
    op.drop_index("ix_desk_use_day_day", table_name="desk_use_day")
    op.drop_table("desk_use_day")
