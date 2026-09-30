"""Server-saved Charts workspace: one JSON document with a save revision."""
from alembic import op
import sqlalchemy as sa

revision = "3c5e7a9b1d24"
down_revision = "8d4f2a6b9c10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A database built by the retired startup create_all() may already have it.
    if "chart_settings" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "chart_settings",
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("data_json", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("name"),
    )


def downgrade() -> None:
    op.drop_table("chart_settings")
