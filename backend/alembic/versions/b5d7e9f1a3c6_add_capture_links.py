"""Charts C3.6: capture links to trades, and capture-adherence tracking."""
from alembic import op
import sqlalchemy as sa

revision = "b5d7e9f1a3c6"
down_revision = "c3a4d5e6f7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "capture_link" not in existing:
        op.create_table(
            "capture_link",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("capture_id", sa.Uuid(), nullable=False),
            sa.Column("account_id", sa.Uuid(), nullable=False),
            sa.Column("source_key", sa.String(), nullable=False),
            sa.Column("method", sa.String(), nullable=False),
            sa.Column("linked_at", sa.DateTime(), nullable=False),
            sa.Column("unlinked_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["capture_id"], ["trade_capture.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_capture_link_capture_id", "capture_link", ["capture_id"])
        op.create_index("ix_capture_link_source_key", "capture_link", ["source_key"])
        # One active link per plan and per anchor fill, held by the database (partial unique indexes).
        active = sa.text("unlinked_at IS NULL")
        op.create_index("uq_capture_link_active_capture", "capture_link", ["capture_id"], unique=True,
                        sqlite_where=active, postgresql_where=active)
        op.create_index("uq_capture_link_active_source", "capture_link", ["account_id", "source_key"], unique=True,
                        sqlite_where=active, postgresql_where=active)
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("capture_profile")}
    with op.batch_alter_table("capture_profile") as batch:
        if "tracking_since" not in columns:
            batch.add_column(sa.Column("tracking_since", sa.DateTime(), nullable=True))
        if "tracking_accounts" not in columns:
            batch.add_column(sa.Column("tracking_accounts", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("capture_profile") as batch:
        batch.drop_column("tracking_accounts")
        batch.drop_column("tracking_since")
    op.drop_table("capture_link")
