"""Queued background research jobs for Copilot Lab (additive).

Revision ID: c4d8e2a6f1b3
Revises: a7c1e3f5b9d2
"""
from alembic import op
import sqlalchemy as sa

revision = "c4d8e2a6f1b3"
down_revision = "a7c1e3f5b9d2"
branch_labels = None
depends_on = None


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    if "research_job" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "research_job",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("input_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("dedupe_key", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("spend_json", sa.Text(), nullable=False),
        sa.Column("investigation_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key"),
    )
    op.create_index(op.f("ix_research_job_status"), "research_job", ["status"])
    op.create_index(op.f("ix_research_job_created_at"), "research_job", ["created_at"])


def downgrade():
    op.drop_index(op.f("ix_research_job_created_at"), table_name="research_job")
    op.drop_index(op.f("ix_research_job_status"), table_name="research_job")
    op.drop_table("research_job")
