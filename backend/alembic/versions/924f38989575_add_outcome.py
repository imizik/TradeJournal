"""Outcome attribution (additive): one row per app output with what price and the owner did next.

Revision ID: 924f38989575
Revises: fa98b2a82e10
"""
from alembic import op
import sqlalchemy as sa

revision = "924f38989575"
down_revision = "fa98b2a82e10"
branch_labels = None
depends_on = None


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    if "outcome" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "outcome",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subject_kind", sa.String(), nullable=False),
        sa.Column("subject_id", sa.String(), nullable=False),
        sa.Column("source_kind", sa.String(), nullable=True),
        sa.Column("held", sa.Boolean(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=True),
        sa.Column("trade_id", sa.Uuid(), nullable=True),
        sa.Column("anchored_at", sa.DateTime(), nullable=False),
        sa.Column("reference_price", sa.Float(), nullable=True),
        sa.Column("h1", sa.Text(), nullable=True),
        sa.Column("d1", sa.Text(), nullable=True),
        sa.Column("d5", sa.Text(), nullable=True),
        sa.Column("action", sa.String(), nullable=True),
        sa.Column("alt_usd", sa.Float(), nullable=True),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subject_kind", "subject_id", name="uq_outcome_subject"),
    )
    op.create_index("ix_outcome_subject_kind", "outcome", ["subject_kind"])
    op.create_index("ix_outcome_symbol", "outcome", ["symbol"])
    op.create_index("ix_outcome_anchored_at", "outcome", ["anchored_at"])
    op.create_index("ix_outcome_complete", "outcome", ["complete"])


def downgrade():
    op.drop_table("outcome")
