"""One-tap plan linking (additive): a plan nudge row's kind, no_plan or link.

Revision ID: d4f8b2c6e1a9
Revises: c7e3a9f1d5b2
"""
from alembic import op
import sqlalchemy as sa

revision = "d4f8b2c6e1a9"
down_revision = "c7e3a9f1d5b2"
branch_labels = None
depends_on = None


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    if "kind" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("plan_nudge")}:
        op.add_column("plan_nudge", sa.Column("kind", sa.String(), nullable=False, server_default="no_plan"))


def downgrade():
    op.drop_column("plan_nudge", "kind")
