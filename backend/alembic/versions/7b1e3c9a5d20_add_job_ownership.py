"""Record the executor and local lock namespace for background jobs."""

from alembic import op
import sqlalchemy as sa

revision = "7b1e3c9a5d20"
down_revision = "4c8e2a7d9b10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns("job_run")}
    for name in ("owner_id", "owner_host", "owner_lock_dir"):
        if name not in existing:
            op.add_column("job_run", sa.Column(name, sa.String(), nullable=True))


def downgrade() -> None:
    # Match the other additive revisions; preserve history on SQLite.
    pass
