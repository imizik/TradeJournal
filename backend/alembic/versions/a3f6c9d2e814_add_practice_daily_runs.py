"""Durable A3 daily runs, shared opportunities and reserved agent attempts."""
from alembic import op
import sqlalchemy as sa

revision = "a3f6c9d2e814"
down_revision = "a2e5b8c1d7f4"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "practice_run" not in tables:
        op.create_table("practice_run",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("session_key", sa.String(), nullable=False, unique=True),
            sa.Column("day", sa.Date(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("parent_id", sa.Uuid(), sa.ForeignKey("practice_run.id")),
            sa.Column("job_id", sa.Uuid(), sa.ForeignKey("job_run.id"), nullable=False),
            *[sa.Column(name, sa.String(), nullable=False) for name in ("mode", "comparison", "status", "policy_version", "policy_hash")],
            sa.Column("result", sa.String()), sa.Column("error", sa.String()),
            sa.Column("late", sa.Boolean(), nullable=False),
            sa.Column("deadline", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime()),
            *[sa.Column(name, sa.Text(), nullable=False) for name in ("calendar_json", "brief_json", "timings_json")])
    if "ix_practice_run_day" not in {i["name"] for i in sa.inspect(bind).get_indexes("practice_run")}:
        op.create_index("ix_practice_run_day", "practice_run", ["day"])
    if "practice_opportunity" not in tables:
        op.create_table("practice_opportunity",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("run_id", sa.Uuid(), sa.ForeignKey("practice_run.id"), nullable=False),
            sa.Column("symbol", sa.String(), nullable=False),
            sa.Column("context_id", sa.Uuid(), sa.ForeignKey("decision_context.id")),
            sa.Column("revealed_at", sa.DateTime()),
            sa.Column("benchmark_json", sa.Text(), nullable=False),
            sa.Column("feedback_json", sa.Text(), nullable=False),
            sa.UniqueConstraint("run_id", "symbol", name="uq_practice_opportunity_symbol"))
    if "ix_practice_opportunity_run_id" not in {i["name"] for i in sa.inspect(bind).get_indexes("practice_opportunity")}:
        op.create_index("ix_practice_opportunity_run_id", "practice_opportunity", ["run_id"])
    if "practice_agent_call" not in tables:
        op.create_table("practice_agent_call",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("day", sa.Date(), nullable=False, unique=True),
            sa.Column("run_id", sa.Uuid(), sa.ForeignKey("practice_run.id"), nullable=False, unique=True),
            *[sa.Column(name, sa.String(), nullable=False) for name in ("status", "model", "prompt_version")],
            *[sa.Column(name, sa.Text(), nullable=False) for name in ("payload_json", "config_json")],
            sa.Column("output_json", sa.Text()), sa.Column("usage_json", sa.String()),
            sa.Column("cost_usd", sa.Float()),
            sa.Column("started_at", sa.DateTime(), nullable=False), sa.Column("finished_at", sa.DateTime()),
            sa.Column("error", sa.String()))

def downgrade():
    op.drop_table("practice_agent_call")
    op.drop_index("ix_practice_opportunity_run_id", table_name="practice_opportunity")
    op.drop_table("practice_opportunity")
    op.drop_index("ix_practice_run_day", table_name="practice_run")
    op.drop_table("practice_run")
