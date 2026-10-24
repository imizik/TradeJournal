"""Saved Copilot Lab investigations and research results (additive).

Revision ID: a7c1e3f5b9d2
Revises: 7c3e0a5b2d84
"""
from alembic import op
import sqlalchemy as sa

revision = "a7c1e3f5b9d2"
down_revision = "7c3e0a5b2d84"
branch_labels = None
depends_on = None


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    if "copilot_investigation" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "copilot_investigation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("conclusion", sa.String(), nullable=True),
        sa.Column("transcript_json", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("findings_json", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_copilot_investigation_updated_at"), "copilot_investigation", ["updated_at"])
    op.create_index(op.f("ix_copilot_investigation_source"), "copilot_investigation", ["source"])
    op.create_index(op.f("ix_copilot_investigation_symbol"), "copilot_investigation", ["symbol"])


def downgrade():
    op.drop_index(op.f("ix_copilot_investigation_symbol"), table_name="copilot_investigation")
    op.drop_index(op.f("ix_copilot_investigation_source"), table_name="copilot_investigation")
    op.drop_index(op.f("ix_copilot_investigation_updated_at"), table_name="copilot_investigation")
    op.drop_table("copilot_investigation")
