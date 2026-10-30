"""Jo research role (additive): red-team requests on confirmed plans and imported research submissions.

Revision ID: fa98b2a82e10
Revises: d2e7a4c9b1f6
"""
from alembic import op
import sqlalchemy as sa

revision = "fa98b2a82e10"
down_revision = "d2e7a4c9b1f6"
branch_labels = None
depends_on = None


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    tables = sa.inspect(op.get_bind()).get_table_names()
    if "jo_red_team_request" not in tables:
        op.create_table(
            "jo_red_team_request",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("investigation_id", sa.String(), nullable=False),
            sa.Column("proposal_id", sa.String(), nullable=False),
            sa.Column("symbol", sa.String(), nullable=False),
            sa.Column("direction", sa.String(), nullable=False),
            sa.Column("instrument", sa.String(), nullable=False),
            sa.Column("contract", sa.String(), nullable=True),
            sa.Column("thesis", sa.String(), nullable=False),
            sa.Column("entry", sa.String(), nullable=False),
            sa.Column("invalidation", sa.String(), nullable=False),
            sa.Column("time_stop", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("answered_at", sa.DateTime(), nullable=True),
            sa.Column("answer_investigation_id", sa.Uuid(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("investigation_id", "proposal_id"),
        )
        op.create_index("ix_jo_red_team_request_investigation_id", "jo_red_team_request", ["investigation_id"])
        op.create_index("ix_jo_red_team_request_status", "jo_red_team_request", ["status"])
    if "jo_research_import" not in tables:
        op.create_table(
            "jo_research_import",
            sa.Column("submission_key", sa.String(), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("investigation_id", sa.Uuid(), nullable=False),
            sa.Column("request_id", sa.Uuid(), nullable=True),
            sa.Column("imported_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("submission_key"),
        )


def downgrade():
    op.drop_table("jo_research_import")
    op.drop_table("jo_red_team_request")
