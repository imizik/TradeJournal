"""When Check received each imported morning briefing.

Revision ID: e4b7c1d9f2a6
Revises: d0f6b2c4e8a3
"""
from alembic import op
import sqlalchemy as sa

revision = "e4b7c1d9f2a6"
down_revision = "d0f6b2c4e8a3"
branch_labels = None
depends_on = None


def upgrade():
    # A new table, not a column: saved records stay unchanged and the migration stays additive.
    # No backfill: earlier imports kept no submission time in the database.
    if "morning_briefing_submission" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table("morning_briefing_submission",
            sa.Column("briefing_id", sa.Uuid(), sa.ForeignKey("morning_briefing_record.id"), primary_key=True),
            sa.Column("submitted_at", sa.DateTime(), nullable=False))


def downgrade():
    op.drop_table("morning_briefing_submission")
