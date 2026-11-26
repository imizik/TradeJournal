"""Model-written review tags on closed trades (additive): a new ``trade_ai_tag`` table keyed by the trade's first
entry fill. Nothing existing changes.

Revision ID: b7d2f4a9c1e3
Revises: a3c7e1f9b2d4
"""
from alembic import op
import sqlalchemy as sa

revision = "b7d2f4a9c1e3"
down_revision = "a3c7e1f9b2d4"
branch_labels = None
depends_on = None

TABLE = "trade_ai_tag"


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    if TABLE in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("source_key", sa.String(), nullable=False),
        sa.Column("trade_id_at_tagging", sa.Uuid(), nullable=True),
        sa.Column("setup", sa.String(), nullable=False),
        sa.Column("mistakes_json", sa.Text(), nullable=False),
        sa.Column("primary_mistake", sa.String(), nullable=False),
        sa.Column("broke_cut_rule", sa.Boolean(), nullable=False),
        sa.Column("rule_broken_computed", sa.Boolean(), nullable=False),
        sa.Column("grade", sa.String(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("facts_json", sa.Text(), nullable=True),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("batch_id", sa.String(), nullable=True),
        sa.Column("tagged_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("account_id", "source_key", name="uq_trade_ai_tag_anchor"),
    )
    op.create_index("ix_trade_ai_tag_account_id", TABLE, ["account_id"])
    op.create_index("ix_trade_ai_tag_source_key", TABLE, ["source_key"])


def downgrade():
    op.drop_table(TABLE)
