"""Weekly review: one exit rule per week and how it went.

Revision ID: d4f1a7c3e9b2
Revises: a3d8f6c2e9b1
"""
from alembic import op
import sqlalchemy as sa

revision = "d4f1a7c3e9b2"
down_revision = "a3d8f6c2e9b1"
branch_labels = None
depends_on = None


def upgrade():
    # A new table only: existing tables and rows stay unchanged.
    if "weekly_review" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "weekly_review",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("week_start", sa.Date(), nullable=False),
            sa.Column("rule_key", sa.String(), nullable=True),
            sa.Column("rule_params_json", sa.Text(), nullable=True),
            sa.Column("note", sa.String(), nullable=True),
            sa.Column("chosen_at", sa.DateTime(), nullable=False),
            sa.Column("result", sa.String(), nullable=True),
            sa.Column("result_source", sa.String(), nullable=True),
            sa.Column("evidence_json", sa.Text(), nullable=True),
            sa.Column("checked_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_weekly_review_week_start", "weekly_review", ["week_start"], unique=True)


def downgrade():
    op.drop_table("weekly_review")
