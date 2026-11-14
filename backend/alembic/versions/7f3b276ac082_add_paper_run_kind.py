"""Paper replay runs (additive): ``paper_run.kind`` (``live``, the default every existing run keeps, or ``replay``) and
``paper_run.replay_day``. Two new columns; nothing existing changes.

Revision ID: 7f3b276ac082
Revises: a7c3e9f1b5d2
"""
from alembic import op
import sqlalchemy as sa

revision = "7f3b276ac082"
down_revision = "a7c3e9f1b5d2"
branch_labels = None
depends_on = None


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("paper_run")}
    if "kind" not in columns:
        op.add_column("paper_run", sa.Column("kind", sa.String(), nullable=False, server_default="live"))
    if "replay_day" not in columns:
        op.add_column("paper_run", sa.Column("replay_day", sa.Date(), nullable=True))


def downgrade():
    with op.batch_alter_table("paper_run") as batch:
        batch.drop_column("replay_day")
        batch.drop_column("kind")
