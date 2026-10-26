"""Trade origin chain (additive): what prompted a pre-trade plan.

Revision ID: c4e8a2f6d1b9
Revises: f3b7d1e9a2c4
"""
from alembic import op
import sqlalchemy as sa

revision = "c4e8a2f6d1b9"
down_revision = "f3b7d1e9a2c4"
branch_labels = None
depends_on = None

COLUMNS = (("origin_kind", sa.String()), ("origin_ref", sa.String()), ("origin_text", sa.String()))


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    inspector = sa.inspect(op.get_bind())
    existing = {c["name"] for c in inspector.get_columns("trade_capture")}
    for name, kind in COLUMNS:
        if name not in existing:
            op.add_column("trade_capture", sa.Column(name, kind, nullable=True))
    indexes = {i["name"] for i in inspector.get_indexes("trade_capture")}
    for name in ("origin_kind", "origin_ref"):
        if f"ix_trade_capture_{name}" not in indexes:
            op.create_index(f"ix_trade_capture_{name}", "trade_capture", [name])


def downgrade():
    for name in ("origin_ref", "origin_kind"):
        op.drop_index(f"ix_trade_capture_{name}", table_name="trade_capture")
    for name, _ in reversed(COLUMNS):
        op.drop_column("trade_capture", name)
