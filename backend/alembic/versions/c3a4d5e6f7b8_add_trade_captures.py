"""Charts C3.4, C3.5: pre-trade captures, their templates and later notes."""
from alembic import op
import sqlalchemy as sa

revision = "c3a4d5e6f7b8"
down_revision = "8d4f6a2c9e17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A database built by the retired startup create_all() may already have them.
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "capture_template" not in existing:
        _templates()
    if "capture_profile" not in existing:
        _profile()
    if "trade_capture" not in existing:
        _captures()
    if "trade_capture_note" not in existing:
        _notes()


def _templates() -> None:
    op.create_table(
        "capture_template",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("setup_label", sa.String(), nullable=False),
        sa.Column("wording", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def _profile() -> None:
    op.create_table(
        "capture_profile",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("default_account_id", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def _captures() -> None:
    op.create_table(
        "trade_capture",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("client_captured_at", sa.DateTime(), nullable=True),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("account_label", sa.String(), nullable=False),
        sa.Column("underlying", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("instrument", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=True),
        sa.Column("template_revision", sa.Integer(), nullable=True),
        sa.Column("setup_label", sa.String(), nullable=True),
        sa.Column("wording", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("strike", sa.Float(), nullable=True),
        sa.Column("expiration", sa.Date(), nullable=True),
        sa.Column("quantity", sa.Float(), nullable=True),
        sa.Column("context_state", sa.String(), nullable=False),
        sa.Column("context_json", sa.Text(), nullable=False),
        sa.Column("image_state", sa.String(), nullable=False),
        sa.Column("image_type", sa.String(), nullable=True),
        sa.Column("image_bytes", sa.Integer(), nullable=True),
        sa.Column("image_note", sa.Text(), nullable=True),
        sa.Column("image_received_at", sa.DateTime(), nullable=True),
        sa.Column("audio_type", sa.String(), nullable=True),
        sa.Column("audio_bytes", sa.Integer(), nullable=True),
        sa.Column("audio_ms", sa.Integer(), nullable=True),
        sa.Column("audio_sha256", sa.String(), nullable=True),
        sa.Column("transcript_status", sa.String(), nullable=True),
        sa.Column("transcript_text", sa.Text(), nullable=True),
        sa.Column("transcript_provider", sa.String(), nullable=True),
        sa.Column("transcript_error", sa.Text(), nullable=True),
        sa.Column("transcribed_at", sa.DateTime(), nullable=True),
        sa.Column("transcript_job_id", sa.Uuid(), nullable=True),
        sa.Column("not_taken_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", name="uq_trade_capture_client_id"),
    )
    op.create_index("ix_trade_capture_received_at", "trade_capture", ["received_at"])
    op.create_index("ix_trade_capture_account_id", "trade_capture", ["account_id"])
    op.create_index("ix_trade_capture_underlying", "trade_capture", ["underlying"])


def _notes() -> None:
    op.create_table(
        "trade_capture_note",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("capture_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["capture_id"], ["trade_capture.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trade_capture_note_capture_id", "trade_capture_note", ["capture_id"])


def downgrade() -> None:
    op.drop_table("trade_capture_note")
    op.drop_table("trade_capture")
    op.drop_table("capture_profile")
    op.drop_table("capture_template")
