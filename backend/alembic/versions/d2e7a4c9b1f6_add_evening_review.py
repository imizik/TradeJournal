"""Evening review ping (additive): one row per trading day's count of what waits for review, its ping's outbox.

Revision ID: d2e7a4c9b1f6
Revises: c6d8e2f4a901
"""
from alembic import op
import sqlalchemy as sa

revision = "d2e7a4c9b1f6"
down_revision = "c6d8e2f4a901"
branch_labels = None
depends_on = None


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    if "evening_review" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "evening_review",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("review", sa.Integer(), nullable=False),
        sa.Column("alerts", sa.Integer(), nullable=False),
        sa.Column("radar", sa.Integer(), nullable=False),
        sa.Column("fills", sa.Integer(), nullable=False),
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
    op.create_index("ix_evening_review_delivery", "evening_review", ["delivery"])


def downgrade():
    op.drop_table("evening_review")
