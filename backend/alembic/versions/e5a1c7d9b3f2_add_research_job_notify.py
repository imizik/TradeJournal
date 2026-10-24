"""A research job's materiality and phone-ping delivery record (additive, nullable).

Revision ID: e5a1c7d9b3f2
Revises: c4d8e2a6f1b3
"""
from alembic import op
import sqlalchemy as sa

revision = "e5a1c7d9b3f2"
down_revision = "c4d8e2a6f1b3"
branch_labels = None
depends_on = None


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    if "notify_json" in {column["name"] for column in sa.inspect(op.get_bind()).get_columns("research_job")}:
        return
    op.add_column("research_job", sa.Column("notify_json", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("research_job", "notify_json")
