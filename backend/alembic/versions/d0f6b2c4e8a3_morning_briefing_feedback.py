"""Owner morning briefing feedback.

Revision ID: d0f6b2c4e8a3
Revises: c9e5a1b3d7f2
"""
from alembic import op
import sqlalchemy as sa

revision = "d0f6b2c4e8a3"
down_revision = "c9e5a1b3d7f2"
branch_labels = None
depends_on = None


def upgrade():
    if "morning_briefing_feedback" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table("morning_briefing_feedback",
            sa.Column("briefing_id", sa.Uuid(), sa.ForeignKey("morning_briefing_record.id"), primary_key=True),
            sa.Column("first_opened_at", sa.DateTime(), nullable=True),
            sa.Column("rating", sa.String(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False))


def downgrade():
    op.drop_table("morning_briefing_feedback")
