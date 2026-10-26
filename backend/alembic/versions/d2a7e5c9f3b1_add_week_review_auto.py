"""Automatic week review (additive): one row per reviewed week, the review's outbox.

Revision ID: d2a7e5c9f3b1
Revises: c8d2f6a4e1b7
"""
from alembic import op
import sqlalchemy as sa

revision = "d2a7e5c9f3b1"
down_revision = "c8d2f6a4e1b7"
branch_labels = None
depends_on = None


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    if "week_review_auto" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "week_review_auto",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("investigation_id", sa.String(), nullable=True),
        sa.Column("fallback", sa.Boolean(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("proposal_json", sa.Text(), nullable=True),
        sa.Column("delivery", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("week_start"),
    )
    op.create_index("ix_week_review_auto_delivery", "week_review_auto", ["delivery"])


def downgrade():
    op.drop_table("week_review_auto")
