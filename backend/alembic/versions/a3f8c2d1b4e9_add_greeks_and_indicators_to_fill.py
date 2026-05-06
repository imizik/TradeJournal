"""add_greeks_and_indicators_to_fill

Revision ID: a3f8c2d1b4e9
Revises: 84a8bf1dd0ab
Create Date: 2026-04-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3f8c2d1b4e9'
down_revision: Union[str, None] = '84a8bf1dd0ab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('fill', sa.Column('gamma_at_fill', sa.Numeric(18, 6), nullable=True))
    op.add_column('fill', sa.Column('theta_at_fill', sa.Numeric(18, 6), nullable=True))
    op.add_column('fill', sa.Column('vega_at_fill', sa.Numeric(18, 6), nullable=True))
    op.add_column('fill', sa.Column('sma_20_at_fill', sa.Numeric(18, 6), nullable=True))
    op.add_column('fill', sa.Column('ema_20_at_fill', sa.Numeric(18, 6), nullable=True))
    op.add_column('fill', sa.Column('rsi_14_at_fill', sa.Numeric(18, 6), nullable=True))
    op.add_column('fill', sa.Column('macd_at_fill', sa.Numeric(18, 6), nullable=True))
    op.add_column('fill', sa.Column('macd_signal_at_fill', sa.Numeric(18, 6), nullable=True))


def downgrade() -> None:
    op.drop_column('fill', 'macd_signal_at_fill')
    op.drop_column('fill', 'macd_at_fill')
    op.drop_column('fill', 'rsi_14_at_fill')
    op.drop_column('fill', 'ema_20_at_fill')
    op.drop_column('fill', 'sma_20_at_fill')
    op.drop_column('fill', 'vega_at_fill')
    op.drop_column('fill', 'theta_at_fill')
    op.drop_column('fill', 'gamma_at_fill')
