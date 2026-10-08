"""Revocable app principals, opaque sessions and bounded security evidence."""
from alembic import op
import sqlalchemy as sa

revision = "b1a7c8d9e201"
down_revision = "a3f6c9d2e814"
branch_labels = None
depends_on = None


def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "access_principal" not in tables:
        op.create_table("access_principal", sa.Column("id", sa.String(), primary_key=True),
            sa.Column("key_hash", sa.String()), sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False), sa.Column("grants_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("credential_expires_at", sa.DateTime()))
    if "access_session" not in tables:
        op.create_table("access_session", sa.Column("digest", sa.String(), primary_key=True),
            sa.Column("principal_id", sa.String(), sa.ForeignKey("access_principal.id")),
            sa.Column("version", sa.Integer(), nullable=False), sa.Column("audience", sa.String(), nullable=False),
            sa.Column("csrf", sa.String(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False), sa.Column("expires_at", sa.DateTime(), nullable=False))
    if "access_login_limit" not in tables:
        op.create_table("access_login_limit", sa.Column("id", sa.String(), primary_key=True),
            sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("window_at", sa.DateTime(), nullable=False),
            sa.Column("blocked_until", sa.DateTime()))
    if "access_audit" not in tables:
        op.create_table("access_audit", sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("principal_id", sa.String()), sa.Column("operation", sa.String(), nullable=False),
            sa.Column("resource", sa.String()), sa.Column("outcome", sa.String(), nullable=False),
            sa.Column("request_id", sa.String(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    if "ix_access_audit_created_at" not in {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("access_audit")}:
        op.create_index("ix_access_audit_created_at", "access_audit", ["created_at"])

def downgrade():
    for table in ("access_audit", "access_login_limit", "access_session", "access_principal"):
        op.drop_table(table)
