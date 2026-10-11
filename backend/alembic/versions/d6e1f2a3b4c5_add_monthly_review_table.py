"""add_monthly_review_table

Revision ID: d6e1f2a3b4c5
Revises: b1a7c8d9e201
Create Date: 2026-10-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d6e1f2a3b4c5"
down_revision: Union[str, None] = "b1a7c8d9e201"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "monthly_review" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "monthly_review",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("month", sa.String(), nullable=False),
        sa.Column("review_json", sa.Text(), nullable=False),
        sa.Column("trade_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_monthly_review_month"), "monthly_review", ["month"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_monthly_review_month"), table_name="monthly_review")
    op.drop_table("monthly_review")
