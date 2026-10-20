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
    # Nullable with no backfill: earlier imports kept no submission time in the database.
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("morning_briefing_record")}
    if "submitted_at" not in columns:
        op.add_column("morning_briefing_record", sa.Column("submitted_at", sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table("morning_briefing_record") as batch:
        batch.drop_column("submitted_at")
