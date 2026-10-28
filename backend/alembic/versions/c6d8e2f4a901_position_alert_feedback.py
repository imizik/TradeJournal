"""Owner feedback on position alerts (additive).

Revision ID: c6d8e2f4a901
Revises: 9ff22204d1d2
"""
from alembic import op
import sqlalchemy as sa

revision = "c6d8e2f4a901"
down_revision = "9ff22204d1d2"
branch_labels = None
depends_on = None


def upgrade():
    if "position_alert_feedback" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table("position_alert_feedback",
            sa.Column("alert_id", sa.Uuid(), sa.ForeignKey("position_alert.id"), primary_key=True),
            sa.Column("rating", sa.String(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False))


def downgrade():
    op.drop_table("position_alert_feedback")
