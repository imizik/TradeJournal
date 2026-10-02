"""Charts C4.3: daily option open interest/volume snapshots and their per-session status."""
from alembic import op
import sqlalchemy as sa

revision = "5e8b2d7c4a19"
down_revision = "3c5e7a9b1d24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A database built by the retired startup create_all() may already have them.
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "option_chain_snapshot" not in existing:
        _create_snapshots()
    if "option_snapshot_day" not in existing:
        _create_days()


def _create_snapshots() -> None:
    op.create_table(
        "option_chain_snapshot",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("underlying", sa.String(), nullable=False),
        sa.Column("expiration", sa.Date(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("last_trade_at", sa.DateTime(), nullable=True),
        sa.Column("contracts", sa.Integer(), nullable=False),
        sa.Column("data_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_date", "underlying", "expiration", name="uq_option_chain_snapshot_session"),
    )


def _create_days() -> None:
    op.create_table(
        "option_snapshot_day",
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("underlying", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("expirations", sa.Integer(), nullable=False),
        sa.Column("recorded", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("session_date", "underlying"),
    )


def downgrade() -> None:
    op.drop_table("option_snapshot_day")
    op.drop_table("option_chain_snapshot")
