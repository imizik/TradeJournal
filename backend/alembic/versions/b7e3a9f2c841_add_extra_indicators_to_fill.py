"""add_extra_indicators_to_fill

Revision ID: b7e3a9f2c841
Revises: a3f8c2d1b4e9
Create Date: 2026-04-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7e3a9f2c841'
down_revision: Union[str, None] = 'a3f8c2d1b4e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('fill', sa.Column('vwap_at_fill', sa.Numeric(18, 6), nullable=True))
    op.add_column('fill', sa.Column('ema_9_at_fill', sa.Numeric(18, 6), nullable=True))
    op.add_column('fill', sa.Column('sma_50_at_fill', sa.Numeric(18, 6), nullable=True))
    op.add_column('fill', sa.Column('ema_9h_at_fill', sa.Numeric(18, 6), nullable=True))


def downgrade() -> None:
    op.drop_column('fill', 'ema_9h_at_fill')
    op.drop_column('fill', 'sma_50_at_fill')
    op.drop_column('fill', 'ema_9_at_fill')
    op.drop_column('fill', 'vwap_at_fill')
