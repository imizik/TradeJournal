"""add_webull_support

Adds:
  - account.broker, account.broker_account_id (nullable, additive)
  - webull_raw_event table (raw event store, dedupe key = event_id)

Revision ID: b1c2d3e4f5a6
Revises: e3f4a5b6c7d8
Create Date: 2026-05-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_col_if_missing(inspector, table: str, col: str, col_type) -> None:
    existing = {c["name"] for c in inspector.get_columns(table)}
    if col not in existing:
        op.add_column(table, sa.Column(col, col_type, nullable=True))


def _has_index(inspector, table: str, index_name: str) -> bool:
    return any(ix["name"] == index_name for ix in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # ---- account: broker linkage (additive, nullable) ----
    if "account" in existing_tables:
        _add_col_if_missing(inspector, "account", "broker", sa.String())
        _add_col_if_missing(inspector, "account", "broker_account_id", sa.String())
        # Refresh inspector view after add_column
        inspector = sa.inspect(bind)
        if not _has_index(inspector, "account", "ix_account_broker"):
            op.create_index("ix_account_broker", "account", ["broker"])
        if not _has_index(inspector, "account", "ix_account_broker_account_id"):
            op.create_index("ix_account_broker_account_id", "account", ["broker_account_id"])

    # ---- webull_raw_event ----
    if "webull_raw_event" not in existing_tables:
        op.create_table(
            "webull_raw_event",
            sa.Column("event_id", sa.String(), nullable=False),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("scene_type", sa.String(), nullable=True),
            sa.Column("order_status", sa.String(), nullable=True),
            sa.Column("account_id", sa.String(), nullable=True),
            sa.Column("client_order_id", sa.String(), nullable=True),
            sa.Column("symbol", sa.String(), nullable=True),
            sa.Column("category", sa.String(), nullable=True),
            sa.Column("received_at", sa.DateTime(), nullable=False),
            sa.Column("filled_time", sa.DateTime(), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("normalized", sa.Boolean(), nullable=False),
            sa.Column("fill_id", sa.Uuid(), nullable=True),
            sa.Column("normalize_error", sa.Text(), nullable=True),
            sa.Column("normalize_reason", sa.String(), nullable=True),
            sa.PrimaryKeyConstraint("event_id"),
            sa.ForeignKeyConstraint(["fill_id"], ["fill.id"]),
        )
        op.create_index("ix_webull_raw_event_event_type", "webull_raw_event", ["event_type"])
        op.create_index("ix_webull_raw_event_scene_type", "webull_raw_event", ["scene_type"])
        op.create_index("ix_webull_raw_event_account_id", "webull_raw_event", ["account_id"])
        op.create_index("ix_webull_raw_event_client_order_id", "webull_raw_event", ["client_order_id"])
        op.create_index("ix_webull_raw_event_received_at", "webull_raw_event", ["received_at"])
        op.create_index("ix_webull_raw_event_normalized", "webull_raw_event", ["normalized"])


def downgrade() -> None:
    # Additive-only migration. SQLite DROP COLUMN is limited; leave fields in place.
    pass
