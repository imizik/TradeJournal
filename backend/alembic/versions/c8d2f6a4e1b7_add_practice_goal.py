"""Practice goal (additive): the one thing the owner chose to practice, scored by the week review.

Revision ID: c8d2f6a4e1b7
Revises: c4e8a2f6d1b9
"""
from alembic import op
import sqlalchemy as sa

revision = "c8d2f6a4e1b7"
down_revision = "c4e8a2f6d1b9"
branch_labels = None
depends_on = None


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    if "practice_goal" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "practice_goal",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("measure", sa.String(), nullable=False),
        sa.Column("target", sa.Float(), nullable=True),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("investigation_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_practice_goal_status", "practice_goal", ["status"])


def downgrade():
    op.drop_table("practice_goal")
