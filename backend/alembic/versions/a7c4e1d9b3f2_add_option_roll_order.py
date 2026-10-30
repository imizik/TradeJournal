"""Two-leg Robinhood orders (additive): the email's facts, kept until the contracts are known.

Revision ID: a7c4e1d9b3f2
Revises: c6e2a8f4d1b7
"""
from alembic import op
import sqlalchemy as sa

revision = "a7c4e1d9b3f2"
down_revision = "c6e2a8f4d1b7"
branch_labels = None
depends_on = None


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    if "optionrollorder" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "optionrollorder",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("raw_email_id", sa.String(), nullable=False),
            sa.Column("ticker", sa.String(), nullable=False),
            sa.Column("contracts", sa.Numeric(18, 6), nullable=False),
            sa.Column("net_per_contract", sa.Numeric(18, 6), nullable=False),
            sa.Column("credit_mentioned", sa.Boolean(), nullable=False),
            sa.Column("executed_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_optionrollorder_raw_email_id", "optionrollorder", ["raw_email_id"], unique=True)


def downgrade():
    op.drop_index("ix_optionrollorder_raw_email_id", table_name="optionrollorder")
    op.drop_table("optionrollorder")
