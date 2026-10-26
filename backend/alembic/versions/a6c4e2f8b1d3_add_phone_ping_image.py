"""Pictures on phone pings (additive): whether each ping carried its chart picture.

Revision ID: a6c4e2f8b1d3
Revises: d2a7e5c9f3b1
"""
from alembic import op
import sqlalchemy as sa

revision = "a6c4e2f8b1d3"
down_revision = "d2a7e5c9f3b1"
branch_labels = None
depends_on = None


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    if "image" in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("phone_ping")}:
        return
    op.add_column("phone_ping", sa.Column("image", sa.String(), nullable=True))


def downgrade():
    op.drop_column("phone_ping", "image")
