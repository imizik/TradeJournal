"""Identify daily Main chat segments without reclassifying existing conversations."""
import sqlalchemy as sa
from alembic import op

revision = "6a9e4db287f1"
down_revision = "b7c1d2e3f4a5"
branch_labels = None
depends_on = None

TABLE = "copilot_investigation"
INDEX = "ix_copilot_investigation_main_day"


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "main_day" not in {col["name"] for col in inspector.get_columns(TABLE)}:
        op.add_column(TABLE, sa.Column("main_day", sa.Date(), nullable=True))
    if INDEX not in {idx["name"] for idx in inspector.get_indexes(TABLE)}:
        op.create_index(INDEX, TABLE, ["main_day"])


def downgrade():
    op.drop_index(INDEX, table_name=TABLE)
    op.drop_column(TABLE, "main_day")
