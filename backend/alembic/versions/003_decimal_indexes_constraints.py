"""Add decimal numeric columns and core indexes/constraints

Revision ID: 003
Revises: 002
Create Date: 2026-04-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DECIMAL_18_6 = sa.Numeric(18, 6)
DECIMAL_18_4 = sa.Numeric(18, 4)


def upgrade() -> None:
    with op.batch_alter_table("account", recreate="always") as batch_op:
        batch_op.alter_column("last4", existing_type=sa.String(), nullable=False)
        batch_op.create_unique_constraint("uq_account_last4", ["last4"])

    with op.batch_alter_table("fill", recreate="always") as batch_op:
        batch_op.alter_column("contracts", existing_type=sa.Integer(), type_=DECIMAL_18_6, nullable=False)
        batch_op.alter_column("price", existing_type=sa.Float(), type_=DECIMAL_18_6, nullable=False)
        batch_op.alter_column("strike", existing_type=sa.Float(), type_=DECIMAL_18_6, nullable=True)
        batch_op.alter_column("iv_at_fill", existing_type=sa.Float(), type_=DECIMAL_18_6, nullable=True)
        batch_op.alter_column("delta_at_fill", existing_type=sa.Float(), type_=DECIMAL_18_6, nullable=True)
        batch_op.alter_column("iv_rank_at_fill", existing_type=sa.Float(), type_=DECIMAL_18_6, nullable=True)
        batch_op.alter_column("underlying_price_at_fill", existing_type=sa.Float(), type_=DECIMAL_18_6, nullable=True)
        batch_op.create_unique_constraint("uq_fill_raw_email_id", ["raw_email_id"])
        batch_op.create_index("ix_fill_executed_at", ["executed_at"], unique=False)
        batch_op.create_index("ix_fill_account_id", ["account_id"], unique=False)

    with op.batch_alter_table("trade", recreate="always") as batch_op:
        batch_op.alter_column("contracts", existing_type=sa.Integer(), type_=DECIMAL_18_6, nullable=False)
        batch_op.alter_column("avg_entry_premium", existing_type=sa.Float(), type_=DECIMAL_18_6, nullable=False)
        batch_op.alter_column("avg_exit_premium", existing_type=sa.Float(), type_=DECIMAL_18_6, nullable=True)
        batch_op.alter_column("total_premium_paid", existing_type=sa.Float(), type_=DECIMAL_18_6, nullable=False)
        batch_op.alter_column("realized_pnl", existing_type=sa.Float(), type_=DECIMAL_18_6, nullable=True)
        batch_op.alter_column("pnl_pct", existing_type=sa.Float(), type_=DECIMAL_18_4, nullable=True)
        batch_op.alter_column("strike", existing_type=sa.Float(), type_=DECIMAL_18_6, nullable=True)
        batch_op.create_index("ix_trade_account_id", ["account_id"], unique=False)


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for revision 003.")
