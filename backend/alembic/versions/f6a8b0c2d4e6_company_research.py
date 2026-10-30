"""Company research history (additive)."""
from alembic import op
import sqlalchemy as sa

revision = "f6a8b0c2d4e6"
down_revision = "924f38989575"
branch_labels = None
depends_on = None


def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    definitions = {
        "company_research_company": [
            sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("symbol", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False), sa.Column("cik", sa.String()),
            sa.Column("followed", sa.Boolean(), nullable=False), sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("thesis", sa.String(), nullable=False), sa.Column("assumptions_json", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False),
        ],
        "company_research_snapshot": [
            sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("company_id", sa.Uuid(), nullable=False),
            sa.Column("component", sa.String(), nullable=False), sa.Column("operation_id", sa.String(), nullable=False),
            sa.Column("provider", sa.String(), nullable=False), sa.Column("state", sa.String(), nullable=False), sa.Column("observed_at", sa.DateTime(), nullable=False),
            sa.Column("payload_json", sa.String(), nullable=False), sa.Column("digest", sa.String(), nullable=False),
            sa.UniqueConstraint("company_id", "component", "operation_id"),
        ],
        "company_research_assignment": [
            sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("company_id", sa.Uuid(), nullable=False),
            sa.Column("question", sa.String(), nullable=False), sa.Column("actor", sa.String(), nullable=False),
            sa.Column("context_json", sa.String(), nullable=False), sa.Column("context_hash", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
        ],
        "company_research_finding": [
            sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("company_id", sa.Uuid(), nullable=False),
            sa.Column("assignment_id", sa.Uuid(), nullable=False), sa.Column("operation_id", sa.String(), nullable=False),
            sa.Column("actor", sa.String(), nullable=False), sa.Column("payload_json", sa.String(), nullable=False),
            sa.Column("digest", sa.String(), nullable=False), sa.Column("disposition", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("assignment_id", "operation_id"),
        ],
    }
    for name, columns in definitions.items():
        if name in tables:
            continue
        op.create_table(name, *columns)
        field = "symbol" if name == "company_research_company" else "company_id"
        op.create_index(f"ix_{name}_{field}", name, [field], unique=field == "symbol")


def downgrade():
    for name in ("finding", "assignment", "snapshot", "company"):
        op.drop_table("company_research_" + name)
