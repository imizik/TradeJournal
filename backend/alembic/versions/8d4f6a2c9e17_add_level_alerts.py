"""Charts C5.1: level alerts and each firing, with its phone delivery."""
from alembic import op
import sqlalchemy as sa

revision = "8d4f6a2c9e17"
down_revision = "5e8b2d7c4a19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A database built by the retired startup create_all() may already have them.
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "level_alert" not in existing:
        _create_alerts()
    if "level_alert_event" not in existing:
        _create_events()


def _create_alerts() -> None:
    op.create_table(
        "level_alert",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("created_on", sa.Date(), nullable=False),
        sa.Column("condition", sa.String(), nullable=False),
        sa.Column("interval", sa.String(), nullable=True),
        sa.Column("session", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("source_kind", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=True),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("armed_at", sa.DateTime(), nullable=False),
        sa.Column("checked_through", sa.BigInteger(), nullable=True),
        sa.Column("fired_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_level_alert_symbol", "level_alert", ["symbol"])
    op.create_index("ix_level_alert_state", "level_alert", ["state"])


def _create_events() -> None:
    op.create_table(
        "level_alert_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("alert_id", sa.Uuid(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("level", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("event_at", sa.DateTime(), nullable=False),
        sa.Column("bar_time", sa.BigInteger(), nullable=True),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("delivery", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["alert_id"], ["level_alert.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("alert_id", "generation", name="uq_level_alert_event_firing"),
    )
    op.create_index("ix_level_alert_event_alert_id", "level_alert_event", ["alert_id"])
    op.create_index("ix_level_alert_event_delivery", "level_alert_event", ["delivery"])


def downgrade() -> None:
    op.drop_table("level_alert_event")
    op.drop_table("level_alert")
