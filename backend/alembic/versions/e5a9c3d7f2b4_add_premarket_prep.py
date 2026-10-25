"""Pre-market prep (additive): one row per trading morning, the prep's outbox.

Revision ID: e5a9c3d7f2b4
Revises: d4f8b2c6e1a9
"""
from alembic import op
import sqlalchemy as sa

revision = "e5a9c3d7f2b4"
down_revision = "d4f8b2c6e1a9"
branch_labels = None
depends_on = None


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    if "premarket_prep" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "premarket_prep",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("investigation_id", sa.String(), nullable=True),
        sa.Column("fallback", sa.Boolean(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("delivery", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("day"),
    )
    op.create_index("ix_premarket_prep_delivery", "premarket_prep", ["delivery"])


def downgrade():
    op.drop_table("premarket_prep")
