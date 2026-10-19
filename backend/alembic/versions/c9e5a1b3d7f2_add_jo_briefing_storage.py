"""Private Jo memory revisions and saved morning briefing evidence.

Revision ID: c9e5a1b3d7f2
Revises: b8d4f0a2c3e5
"""
from alembic import op
import sqlalchemy as sa

revision = "c9e5a1b3d7f2"
down_revision = "b8d4f0a2c3e5"
branch_labels = None
depends_on = None


def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "jo_memory_revision" not in tables:
        op.create_table("jo_memory_revision",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("memory_id", sa.Uuid(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("operation_id", sa.String(), nullable=False, unique=True),
            sa.Column("request_sha256", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("symbol", sa.String(), nullable=True),
            sa.Column("body_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("redacted_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("memory_id", "revision", name="uq_jo_memory_revision"))
        op.create_index("ix_jo_memory_revision_memory_id", "jo_memory_revision", ["memory_id"])
        op.create_index("ix_jo_memory_revision_symbol", "jo_memory_revision", ["symbol"])
    if "morning_briefing_packet" not in tables:
        op.create_table("morning_briefing_packet",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("operation_id", sa.String(), nullable=False, unique=True),
            sa.Column("request_sha256", sa.String(), nullable=False),
            sa.Column("day", sa.Date(), nullable=False),
            sa.Column("body_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("redacted_at", sa.DateTime(), nullable=True))
        op.create_index("ix_morning_briefing_packet_day", "morning_briefing_packet", ["day"])
    if "morning_briefing_record" not in tables:
        op.create_table("morning_briefing_record",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("packet_id", sa.Uuid(), sa.ForeignKey("morning_briefing_packet.id"), nullable=False),
            sa.Column("operation_id", sa.String(), nullable=False, unique=True),
            sa.Column("request_sha256", sa.String(), nullable=False),
            sa.Column("body_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("redacted_at", sa.DateTime(), nullable=True))
        op.create_index("ix_morning_briefing_record_packet_id", "morning_briefing_record", ["packet_id"])


def downgrade():
    op.drop_table("morning_briefing_record")
    op.drop_table("morning_briefing_packet")
    op.drop_table("jo_memory_revision")
