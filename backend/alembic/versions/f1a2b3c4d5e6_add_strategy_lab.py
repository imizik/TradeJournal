"""add_strategy_lab

Revision ID: f1a2b3c4d5e6
Revises: a4b5c6d7e8f9
Create Date: 2026-07-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "a4b5c6d7e8f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DECIMAL_18_6 = sa.Numeric(18, 6)


def _table_exists(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _ensure_index(
    table_name: str,
    index_name: str,
    columns: list[str],
    *,
    unique: bool = False,
    sqlite_where=None,
    postgresql_where=None,
) -> None:
    """Create an index unless create_all (or a partial prior run) made it."""
    inspector = sa.inspect(op.get_bind())
    existing = {index["name"] for index in inspector.get_indexes(table_name)}
    if index_name in existing:
        return
    kwargs = {}
    if sqlite_where is not None:
        kwargs["sqlite_where"] = sqlite_where
    if postgresql_where is not None:
        kwargs["postgresql_where"] = postgresql_where
    op.create_index(index_name, table_name, columns, unique=unique, **kwargs)


def upgrade() -> None:
    # The app calls SQLModel.metadata.create_all() on startup. Each table and
    # index is therefore guarded independently so Alembic can safely stamp a
    # database where create_all (or an interrupted migration) created a subset.
    if not _table_exists("strategy_definition"):
        op.create_table(
            "strategy_definition",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("setup_type", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name", name="uq_strategy_definition_name"),
        )
    _ensure_index(
        "strategy_definition",
        "ix_strategy_definition_name",
        ["name"],
    )
    _ensure_index(
        "strategy_definition",
        "ix_strategy_definition_setup_type",
        ["setup_type"],
    )

    if not _table_exists("strategy_version"):
        op.create_table(
            "strategy_version",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("strategy_definition_id", sa.Uuid(), nullable=False),
            sa.Column("parent_version_id", sa.Uuid(), nullable=True),
            sa.Column("version_label", sa.String(), nullable=False),
            sa.Column("pine_source", sa.Text(), nullable=False),
            sa.Column("source_fingerprint", sa.String(), nullable=False),
            sa.Column("source_reference", sa.String(), nullable=True),
            sa.Column("change_summary", sa.Text(), nullable=True),
            sa.Column("hypothesis", sa.Text(), nullable=True),
            sa.Column("parameters_json", sa.Text(), nullable=False),
            sa.Column("entry_rule_summary", sa.Text(), nullable=True),
            sa.Column("exit_rule_summary", sa.Text(), nullable=True),
            sa.Column("execution_timing", sa.String(), nullable=False),
            sa.Column("session_mode", sa.String(), nullable=False),
            sa.Column("commission_type", sa.String(), nullable=False),
            sa.Column("commission_value", DECIMAL_18_6, nullable=True),
            sa.Column("slippage_type", sa.String(), nullable=False),
            sa.Column("slippage_value", DECIMAL_18_6, nullable=True),
            sa.Column("pyramiding", sa.Integer(), nullable=False),
            sa.Column("known_limitations", sa.Text(), nullable=True),
            sa.Column("repainting_risk_notes", sa.Text(), nullable=True),
            sa.Column("lookahead_risk_notes", sa.Text(), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint(
                "status IN ('draft', 'challenger', 'champion', 'shadow', 'retired')",
                name="ck_strategy_version_status",
            ),
            sa.CheckConstraint(
                "pyramiding >= 0",
                name="ck_strategy_version_pyramiding",
            ),
            sa.CheckConstraint(
                "parent_version_id IS NULL OR parent_version_id <> id",
                name="ck_strategy_version_not_own_parent",
            ),
            sa.ForeignKeyConstraint(
                ["strategy_definition_id"],
                ["strategy_definition.id"],
            ),
            sa.ForeignKeyConstraint(
                ["parent_version_id"],
                ["strategy_version.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "strategy_definition_id",
                "version_label",
                name="uq_strategy_version_definition_label",
            ),
        )
    _ensure_index(
        "strategy_version",
        "ix_strategy_version_strategy_definition_id",
        ["strategy_definition_id"],
    )
    _ensure_index(
        "strategy_version",
        "ix_strategy_version_parent_version_id",
        ["parent_version_id"],
    )
    _ensure_index(
        "strategy_version",
        "ix_strategy_version_source_fingerprint",
        ["source_fingerprint"],
    )
    _ensure_index(
        "strategy_version",
        "ix_strategy_version_status",
        ["status"],
    )
    champion_predicate = sa.text("status = 'champion'")
    _ensure_index(
        "strategy_version",
        "uq_strategy_version_one_champion",
        ["strategy_definition_id"],
        unique=True,
        sqlite_where=champion_predicate,
        postgresql_where=champion_predicate,
    )

    if not _table_exists("strategy_run"):
        op.create_table(
            "strategy_run",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("strategy_version_id", sa.Uuid(), nullable=False),
            sa.Column("version_fingerprint", sa.String(), nullable=False),
            sa.Column("source", sa.String(), nullable=False),
            sa.Column("symbol", sa.String(), nullable=False),
            sa.Column("timeframe", sa.String(), nullable=False),
            sa.Column("source_timezone", sa.String(), nullable=False),
            sa.Column("backtest_start", sa.Date(), nullable=True),
            sa.Column("backtest_end", sa.Date(), nullable=True),
            sa.Column("initial_capital", DECIMAL_18_6, nullable=True),
            sa.Column("currency", sa.String(), nullable=False),
            sa.Column("commission_type", sa.String(), nullable=False),
            sa.Column("commission_value", DECIMAL_18_6, nullable=True),
            sa.Column("slippage_type", sa.String(), nullable=False),
            sa.Column("slippage_value", DECIMAL_18_6, nullable=True),
            sa.Column("execution_timing", sa.String(), nullable=False),
            sa.Column("session_mode", sa.String(), nullable=False),
            sa.Column("extended_hours", sa.Boolean(), nullable=False),
            sa.Column("pyramiding", sa.Integer(), nullable=False),
            sa.Column("parameters_json", sa.Text(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("source_file_name", sa.String(), nullable=True),
            sa.Column("source_sha256", sa.String(), nullable=True),
            sa.Column("source_headers_json", sa.Text(), nullable=False),
            sa.Column("source_mapping_json", sa.Text(), nullable=False),
            sa.Column("source_warnings_json", sa.Text(), nullable=False),
            sa.Column("source_csv_text", sa.Text(), nullable=True),
            sa.Column("imported_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint(
                "pyramiding >= 0",
                name="ck_strategy_run_pyramiding",
            ),
            sa.ForeignKeyConstraint(
                ["strategy_version_id"],
                ["strategy_version.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "strategy_version_id",
                "source_sha256",
                name="uq_strategy_run_version_source_sha256",
            ),
        )
    _ensure_index(
        "strategy_run",
        "ix_strategy_run_strategy_version_id",
        ["strategy_version_id"],
    )
    _ensure_index(
        "strategy_run",
        "ix_strategy_run_version_fingerprint",
        ["version_fingerprint"],
    )
    _ensure_index(
        "strategy_run",
        "ix_strategy_run_source",
        ["source"],
    )
    _ensure_index(
        "strategy_run",
        "ix_strategy_run_symbol",
        ["symbol"],
    )
    _ensure_index(
        "strategy_run",
        "ix_strategy_run_source_sha256",
        ["source_sha256"],
    )

    if not _table_exists("strategy_run_trade"):
        op.create_table(
            "strategy_run_trade",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("run_id", sa.Uuid(), nullable=False),
            sa.Column("trade_number", sa.Integer(), nullable=False),
            sa.Column("direction", sa.String(), nullable=False),
            sa.Column("entry_at", sa.DateTime(), nullable=True),
            sa.Column("exit_at", sa.DateTime(), nullable=True),
            sa.Column("entry_at_raw", sa.String(), nullable=True),
            sa.Column("exit_at_raw", sa.String(), nullable=True),
            sa.Column("entry_price", DECIMAL_18_6, nullable=True),
            sa.Column("exit_price", DECIMAL_18_6, nullable=True),
            sa.Column("quantity", DECIMAL_18_6, nullable=True),
            sa.Column("net_pnl", DECIMAL_18_6, nullable=True),
            sa.Column("return_pct", DECIMAL_18_6, nullable=True),
            sa.Column("mfe", DECIMAL_18_6, nullable=True),
            sa.Column("mfe_pct", DECIMAL_18_6, nullable=True),
            sa.Column("mae", DECIMAL_18_6, nullable=True),
            sa.Column("mae_pct", DECIMAL_18_6, nullable=True),
            sa.Column("cumulative_pnl", DECIMAL_18_6, nullable=True),
            sa.Column("cumulative_return_pct", DECIMAL_18_6, nullable=True),
            sa.Column("duration_bars", sa.Integer(), nullable=True),
            sa.Column("duration_minutes", sa.Integer(), nullable=True),
            sa.Column("entry_signal", sa.String(), nullable=True),
            sa.Column("exit_signal", sa.String(), nullable=True),
            sa.Column("entry_comment", sa.Text(), nullable=True),
            sa.Column("exit_comment", sa.Text(), nullable=True),
            sa.Column("feature_snapshot_json", sa.Text(), nullable=False),
            sa.Column("raw_entry_row_json", sa.Text(), nullable=False),
            sa.Column("raw_exit_row_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint(
                "direction IN ('long', 'short')",
                name="ck_strategy_run_trade_direction",
            ),
            sa.ForeignKeyConstraint(["run_id"], ["strategy_run.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "run_id",
                "trade_number",
                name="uq_strategy_run_trade_number",
            ),
        )
    _ensure_index(
        "strategy_run_trade",
        "ix_strategy_run_trade_run_id",
        ["run_id"],
    )
    _ensure_index(
        "strategy_run_trade",
        "ix_strategy_run_trade_direction",
        ["direction"],
    )
    _ensure_index(
        "strategy_run_trade",
        "ix_strategy_run_trade_entry_at",
        ["entry_at"],
    )
    _ensure_index(
        "strategy_run_trade",
        "ix_strategy_run_trade_exit_at",
        ["exit_at"],
    )

    if not _table_exists("strategy_run_metrics"):
        op.create_table(
            "strategy_run_metrics",
            sa.Column("run_id", sa.Uuid(), nullable=False),
            sa.Column("calculation_version", sa.String(), nullable=False),
            sa.Column("calculated_at", sa.DateTime(), nullable=False),
            sa.Column("trade_count", sa.Integer(), nullable=False),
            sa.Column("winning_trades", sa.Integer(), nullable=False),
            sa.Column("losing_trades", sa.Integer(), nullable=False),
            sa.Column("win_rate", DECIMAL_18_6, nullable=True),
            sa.Column("average_winner", DECIMAL_18_6, nullable=True),
            sa.Column("average_loser", DECIMAL_18_6, nullable=True),
            sa.Column("payoff_ratio", DECIMAL_18_6, nullable=True),
            sa.Column("expectancy", DECIMAL_18_6, nullable=True),
            sa.Column("profit_factor", DECIMAL_18_6, nullable=True),
            sa.Column("total_net_pnl", DECIMAL_18_6, nullable=True),
            sa.Column("net_return_pct", DECIMAL_18_6, nullable=True),
            sa.Column("max_drawdown", DECIMAL_18_6, nullable=True),
            sa.Column("max_drawdown_pct", DECIMAL_18_6, nullable=True),
            sa.Column("average_mfe", DECIMAL_18_6, nullable=True),
            sa.Column("median_mfe", DECIMAL_18_6, nullable=True),
            sa.Column("average_mae", DECIMAL_18_6, nullable=True),
            sa.Column("median_mae", DECIMAL_18_6, nullable=True),
            sa.Column("average_holding_minutes", DECIMAL_18_6, nullable=True),
            sa.Column("top_1_profit_contribution_pct", DECIMAL_18_6, nullable=True),
            sa.Column("top_3_profit_contribution_pct", DECIMAL_18_6, nullable=True),
            sa.Column("top_5_profit_contribution_pct", DECIMAL_18_6, nullable=True),
            sa.Column("long_summary_json", sa.Text(), nullable=False),
            sa.Column("short_summary_json", sa.Text(), nullable=False),
            sa.Column("time_bucket_summary_json", sa.Text(), nullable=False),
            sa.Column("coverage_json", sa.Text(), nullable=False),
            sa.Column("equity_curve_json", sa.Text(), nullable=False),
            sa.Column("drawdown_curve_json", sa.Text(), nullable=False),
            sa.Column("findings_json", sa.Text(), nullable=False),
            sa.ForeignKeyConstraint(["run_id"], ["strategy_run.id"]),
            sa.PrimaryKeyConstraint("run_id"),
        )

    if not _table_exists("strategy_experiment"):
        op.create_table(
            "strategy_experiment",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("strategy_definition_id", sa.Uuid(), nullable=False),
            sa.Column("baseline_version_id", sa.Uuid(), nullable=True),
            sa.Column("challenger_version_id", sa.Uuid(), nullable=True),
            sa.Column("baseline_run_id", sa.Uuid(), nullable=True),
            sa.Column("challenger_run_id", sa.Uuid(), nullable=True),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("hypothesis", sa.Text(), nullable=False),
            sa.Column("variable_changed", sa.Text(), nullable=True),
            sa.Column("expected_effect", sa.Text(), nullable=True),
            sa.Column("training_start", sa.Date(), nullable=True),
            sa.Column("training_end", sa.Date(), nullable=True),
            sa.Column("validation_start", sa.Date(), nullable=True),
            sa.Column("validation_end", sa.Date(), nullable=True),
            sa.Column("test_start", sa.Date(), nullable=True),
            sa.Column("test_end", sa.Date(), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("conclusion", sa.Text(), nullable=True),
            sa.Column("metrics_snapshot_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint(
                "status IN ('proposed', 'running', 'passed', 'failed', 'inconclusive', 'deployed')",
                name="ck_strategy_experiment_status",
            ),
            sa.ForeignKeyConstraint(
                ["strategy_definition_id"],
                ["strategy_definition.id"],
            ),
            sa.ForeignKeyConstraint(
                ["baseline_version_id"],
                ["strategy_version.id"],
            ),
            sa.ForeignKeyConstraint(
                ["challenger_version_id"],
                ["strategy_version.id"],
            ),
            sa.ForeignKeyConstraint(
                ["baseline_run_id"],
                ["strategy_run.id"],
            ),
            sa.ForeignKeyConstraint(
                ["challenger_run_id"],
                ["strategy_run.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
        )
    _ensure_index(
        "strategy_experiment",
        "ix_strategy_experiment_strategy_definition_id",
        ["strategy_definition_id"],
    )
    _ensure_index(
        "strategy_experiment",
        "ix_strategy_experiment_baseline_version_id",
        ["baseline_version_id"],
    )
    _ensure_index(
        "strategy_experiment",
        "ix_strategy_experiment_challenger_version_id",
        ["challenger_version_id"],
    )
    _ensure_index(
        "strategy_experiment",
        "ix_strategy_experiment_baseline_run_id",
        ["baseline_run_id"],
    )
    _ensure_index(
        "strategy_experiment",
        "ix_strategy_experiment_challenger_run_id",
        ["challenger_run_id"],
    )
    _ensure_index(
        "strategy_experiment",
        "ix_strategy_experiment_status",
        ["status"],
    )


def downgrade() -> None:
    # Reverse dependency order; guards also make downgrade safe after a partial
    # upgrade on SQLite, whose DDL is not fully transactional.
    for table_name in (
        "strategy_experiment",
        "strategy_run_metrics",
        "strategy_run_trade",
        "strategy_run",
        "strategy_version",
        "strategy_definition",
    ):
        if _table_exists(table_name):
            op.drop_table(table_name)
