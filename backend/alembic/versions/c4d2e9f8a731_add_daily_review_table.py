"""add_daily_review_table

Revision ID: c4d2e9f8a731
Revises: b7e3a9f2c841
Create Date: 2026-05-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4d2e9f8a731"
down_revision: Union[str, None] = "b7e3a9f2c841"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "dailyreview" in inspector.get_table_names():
        return

    op.create_table(
        "dailyreview",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("review_json", sa.Text(), nullable=False),
        sa.Column("trade_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_dailyreview_day"), "dailyreview", ["day"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_dailyreview_day"), table_name="dailyreview")
    op.drop_table("dailyreview")
