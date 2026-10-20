"""Owner links from saved Jo checks to later journal activity (Dots step 5).

Revision ID: c7e2a9d4b1f8
Revises: e4b7c1d9f2a6
"""
from alembic import op
import sqlalchemy as sa

revision = "c7e2a9d4b1f8"
down_revision = "e4b7c1d9f2a6"
branch_labels = None
depends_on = None


def upgrade():
    # A new table only: existing tables and rows stay unchanged.
    if "check_link" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "check_link",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("check_id", sa.String(), nullable=False),
            sa.Column("account_id", sa.Uuid(), nullable=False),
            sa.Column("source_key", sa.String(), nullable=False),
            sa.Column("target", sa.String(), nullable=False),
            sa.Column("method", sa.String(), nullable=False),
            sa.Column("linked_at", sa.DateTime(), nullable=False),
            sa.Column("unlinked_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_check_link_check_id", "check_link", ["check_id"])
        op.create_index("ix_check_link_source_key", "check_link", ["source_key"])
        active = sa.text("unlinked_at IS NULL")
        op.create_index("uq_check_link_active", "check_link", ["check_id", "account_id", "source_key"], unique=True,
                        sqlite_where=active, postgresql_where=active)


def downgrade():
    op.drop_table("check_link")
