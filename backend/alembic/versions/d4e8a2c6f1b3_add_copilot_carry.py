"""Copilot follow-up evidence kept across restarts (additive: a new table).

Revision ID: d4e8a2c6f1b3
Revises: 6a9e4db287f1
"""
from alembic import op
import sqlalchemy as sa

revision = "d4e8a2c6f1b3"
down_revision = "6a9e4db287f1"
branch_labels = None
depends_on = None


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    if "copilot_carry" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "copilot_carry",
        sa.Column("carry_id", sa.String(length=32), nullable=False),
        sa.Column("investigation_id", sa.Uuid(), nullable=True),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("items_json", sa.Text(), nullable=False),
        sa.Column("saved_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("carry_id"),
    )
    op.create_index("ix_copilot_carry_investigation_id", "copilot_carry", ["investigation_id"])
    op.create_index("ix_copilot_carry_saved_at", "copilot_carry", ["saved_at"])


def downgrade():
    op.drop_table("copilot_carry")
