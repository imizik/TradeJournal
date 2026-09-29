"""Version context and position path calculations without relabeling legacy rows."""
from alembic import op
import sqlalchemy as sa

revision = "8d4f2a6b9c10"
down_revision = "7b1e3c9a5d20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table, additions in (
        ("fill_market_context", [("calculation_version", sa.String()), ("entry_context_as_of", sa.DateTime())]),
        ("trade_path_metrics", [(name, sa.String()) for name in (
            "calculation_version", "market_inputs_fingerprint", "option_path_quality",
        )] + [("option_peak_total_pnl", sa.Numeric(18, 6))]),
    ):
        existing = {column["name"] for column in inspector.get_columns(table)}
        for name, column_type in additions:
            if name not in existing:
                op.add_column(table, sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("trade_path_metrics") as batch:
        for name in ("option_peak_total_pnl", "option_path_quality", "market_inputs_fingerprint", "calculation_version"):
            batch.drop_column(name)
    with op.batch_alter_table("fill_market_context") as batch:
        batch.drop_column("entry_context_as_of")
        batch.drop_column("calculation_version")
