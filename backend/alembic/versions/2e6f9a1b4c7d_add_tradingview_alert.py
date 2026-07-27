"""add_tradingview_alert

Revision ID: 2e6f9a1b4c7d
Revises: f1a2b3c4d5e6
Create Date: 2026-07-25 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2e6f9a1b4c7d"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# SQLite's NUMERIC affinity round-trips through binary float in SQLAlchemy.
# Store the canonical decimal text there; Postgres keeps a queryable NUMERIC.
TRADINGVIEW_PRICE = sa.Numeric(precision=28, scale=12).with_variant(
    sa.String(length=48),
    "sqlite",
)

EXPECTED_COLUMN_SPECS = {
    "alert_id": (sa.String(length=200), False),
    "contract_version": (sa.Integer(), False),
    "parser_revision": (sa.String(length=64), False),
    "indicator_version": (sa.String(length=32), False),
    "content_sha256": (sa.String(length=64), False),
    "raw_payload_sha256": (sa.String(length=64), False),
    "symbol": (sa.String(length=32), False),
    "timeframe": (sa.String(length=16), False),
    "setup": (sa.String(length=64), False),
    "side": (sa.String(length=5), False),
    "price": (TRADINGVIEW_PRICE, False),
    "bar_time_ms": (sa.BigInteger(), False),
    "bar_time": (sa.DateTime(), False),
    "received_at": (sa.DateTime(), False),
    "updated_at": (sa.DateTime(), False),
    "payload_json": (sa.Text(), False),
    "levels_json": (sa.Text(), False),
    "context_json": (sa.Text(), False),
    "analysis_status": (sa.String(), False),
    "analysis_attempts": (sa.Integer(), False),
    "analysis_started_at": (sa.DateTime(), True),
    "analysis_completed_at": (sa.DateTime(), True),
    "scorer_revision": (sa.String(length=64), True),
    "verdict": (sa.String(length=32), True),
    "confidence": (sa.String(length=16), True),
    "assessment_json": (sa.Text(), True),
    "analysis_error_code": (sa.String(length=64), True),
    "analysis_error": (sa.Text(), True),
}
EXPECTED_COLUMNS = frozenset(EXPECTED_COLUMN_SPECS)

EXPECTED_CHECK_SQL = {
    "ck_tradingview_alert_contract_version": "contract_version >= 1",
    "ck_tradingview_alert_side": "side IN ('long', 'short')",
    "ck_tradingview_alert_price_positive": "CAST(price AS NUMERIC) > 0",
    "ck_tradingview_alert_analysis_attempts": "analysis_attempts >= 0",
    "ck_tradingview_alert_analysis_status": (
        "analysis_status IN ('pending', 'running', 'done', 'skipped', 'error')"
    ),
    "ck_tradingview_alert_verdict": (
        "verdict IS NULL OR verdict IN "
        "('no_trade', 'wait', 'long_scalp', 'short_scalp')"
    ),
    "ck_tradingview_alert_confidence": (
        "confidence IS NULL OR confidence IN ('low', 'medium', 'high')"
    ),
    "ck_tradingview_alert_content_sha256": "length(content_sha256) = 64",
    "ck_tradingview_alert_raw_payload_sha256": (
        "length(raw_payload_sha256) = 64"
    ),
    "ck_tradingview_alert_v1_bar_time": (
        "contract_version <> 1 OR "
        "(bar_time_ms >= 946684800000 AND bar_time_ms < 4102444800000)"
    ),
    "ck_tradingview_alert_v1_text_bounds": (
        "contract_version <> 1 OR "
        "(length(alert_id) <= 200 "
        "AND length(indicator_version) <= 32 "
        "AND length(symbol) <= 32 "
        "AND length(timeframe) <= 16 "
        "AND length(setup) <= 64)"
    ),
}
EXPECTED_CHECKS = frozenset(EXPECTED_CHECK_SQL)

INDEXES = (
    ("ix_tradingview_alert_received_at", ["received_at"]),
    ("ix_tradingview_alert_bar_time", ["bar_time"]),
    (
        "ix_tradingview_alert_symbol_received_at",
        ["symbol", "received_at"],
    ),
    (
        "ix_tradingview_alert_setup_received_at",
        ["setup", "received_at"],
    ),
    (
        "ix_tradingview_alert_analysis_status_updated_at",
        ["analysis_status", "updated_at"],
    ),
)

def _table_exists(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _type_signature(column_type: sa.types.TypeEngine, dialect) -> str:
    compiled = column_type.compile(dialect=dialect)
    return "".join(compiled.upper().split())


def _normalized_check_sql(value: str) -> str:
    return "".join(value.lower().split()).replace('"', "")


def _verify_existing_table() -> None:
    """Fail loudly instead of stamping an incompatible create_all artifact."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    actual_columns = {
        column["name"]: column
        for column in inspector.get_columns("tradingview_alert")
    }
    actual_column_names = frozenset(actual_columns)
    missing_columns = EXPECTED_COLUMNS - actual_column_names
    unexpected_columns = actual_column_names - EXPECTED_COLUMNS
    if missing_columns or unexpected_columns:
        details: list[str] = []
        if missing_columns:
            details.append(
                f"missing column(s): {', '.join(sorted(missing_columns))}"
            )
        if unexpected_columns:
            details.append(
                "unexpected column(s): "
                f"{', '.join(sorted(unexpected_columns))}"
            )
        raise RuntimeError(
            "existing tradingview_alert table is incompatible; "
            + "; ".join(details)
        )

    for name, (expected_type, expected_nullable) in EXPECTED_COLUMN_SPECS.items():
        actual = actual_columns[name]
        actual_type = _type_signature(actual["type"], bind.dialect)
        required_type = _type_signature(expected_type, bind.dialect)
        actual_nullable = bool(actual["nullable"])
        if (
            actual_type != required_type
            or actual_nullable != expected_nullable
            or actual.get("default") is not None
        ):
            raise RuntimeError(
                "existing tradingview_alert table is incompatible; "
                f"column {name} must be {required_type}, "
                f"nullable={expected_nullable}, with no server default"
            )

    primary_key = set(
        inspector.get_pk_constraint("tradingview_alert").get(
            "constrained_columns", []
        )
    )
    if primary_key != {"alert_id"}:
        raise RuntimeError(
            "existing tradingview_alert table is incompatible; "
            "primary key must be alert_id"
        )

    actual_checks = {
        check["name"]: check.get("sqltext", "")
        for check in inspector.get_check_constraints("tradingview_alert")
        if check.get("name")
    }
    actual_check_names = frozenset(actual_checks)
    missing_checks = EXPECTED_CHECKS - actual_check_names
    unexpected_checks = actual_check_names - EXPECTED_CHECKS
    if missing_checks or unexpected_checks:
        details = []
        if missing_checks:
            details.append(
                "missing check constraint(s): "
                f"{', '.join(sorted(missing_checks))}"
            )
        if unexpected_checks:
            details.append(
                "unexpected check constraint(s): "
                f"{', '.join(sorted(unexpected_checks))}"
            )
        raise RuntimeError(
            "existing tradingview_alert table is incompatible; "
            + "; ".join(details)
        )

    # SQLite preserves our authored CHECK SQL. Verify expressions as well as
    # names so a same-name no-op constraint cannot pass the create_all guard.
    # PostgreSQL reflects semantically equivalent CHECKs in rewritten form;
    # there the exact type/nullability/PK/name checks above remain portable.
    if bind.dialect.name == "sqlite":
        for name, expected_sql in EXPECTED_CHECK_SQL.items():
            if _normalized_check_sql(actual_checks[name]) != (
                _normalized_check_sql(expected_sql)
            ):
                raise RuntimeError(
                    "existing tradingview_alert table is incompatible; "
                    f"check constraint {name} has the wrong expression"
                )


def _ensure_indexes() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {
        index["name"]: tuple(index["column_names"])
        for index in inspector.get_indexes("tradingview_alert")
    }
    for index_name, columns in INDEXES:
        expected_columns = tuple(columns)
        actual_columns = existing.get(index_name)
        if actual_columns is None:
            op.create_index(
                index_name,
                "tradingview_alert",
                columns,
                unique=False,
            )
        elif actual_columns != expected_columns:
            raise RuntimeError(
                "existing tradingview_alert index is incompatible; "
                f"{index_name} must cover {expected_columns}, "
                f"found {actual_columns}"
            )


def upgrade() -> None:
    # App startup calls SQLModel.metadata.create_all(). Guard the table and
    # every index so Alembic can safely follow create_all or resume a partial
    # SQLite DDL run without masking a malformed pre-existing schema.
    if not _table_exists("tradingview_alert"):
        op.create_table(
            "tradingview_alert",
            sa.Column("alert_id", sa.String(length=200), nullable=False),
            sa.Column("contract_version", sa.Integer(), nullable=False),
            sa.Column("parser_revision", sa.String(length=64), nullable=False),
            sa.Column("indicator_version", sa.String(length=32), nullable=False),
            sa.Column("content_sha256", sa.String(length=64), nullable=False),
            sa.Column("raw_payload_sha256", sa.String(length=64), nullable=False),
            sa.Column("symbol", sa.String(length=32), nullable=False),
            sa.Column("timeframe", sa.String(length=16), nullable=False),
            sa.Column("setup", sa.String(length=64), nullable=False),
            sa.Column("side", sa.String(length=5), nullable=False),
            sa.Column("price", TRADINGVIEW_PRICE, nullable=False),
            sa.Column("bar_time_ms", sa.BigInteger(), nullable=False),
            sa.Column("bar_time", sa.DateTime(), nullable=False),
            sa.Column("received_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("levels_json", sa.Text(), nullable=False),
            sa.Column("context_json", sa.Text(), nullable=False),
            sa.Column("analysis_status", sa.String(), nullable=False),
            sa.Column("analysis_attempts", sa.Integer(), nullable=False),
            sa.Column("analysis_started_at", sa.DateTime(), nullable=True),
            sa.Column("analysis_completed_at", sa.DateTime(), nullable=True),
            sa.Column("scorer_revision", sa.String(length=64), nullable=True),
            sa.Column("verdict", sa.String(length=32), nullable=True),
            sa.Column("confidence", sa.String(length=16), nullable=True),
            sa.Column("assessment_json", sa.Text(), nullable=True),
            sa.Column("analysis_error_code", sa.String(length=64), nullable=True),
            sa.Column("analysis_error", sa.Text(), nullable=True),
            sa.CheckConstraint(
                "contract_version >= 1",
                name="ck_tradingview_alert_contract_version",
            ),
            sa.CheckConstraint(
                "side IN ('long', 'short')",
                name="ck_tradingview_alert_side",
            ),
            sa.CheckConstraint(
                "CAST(price AS NUMERIC) > 0",
                name="ck_tradingview_alert_price_positive",
            ),
            sa.CheckConstraint(
                "analysis_attempts >= 0",
                name="ck_tradingview_alert_analysis_attempts",
            ),
            sa.CheckConstraint(
                "analysis_status IN "
                "('pending', 'running', 'done', 'skipped', 'error')",
                name="ck_tradingview_alert_analysis_status",
            ),
            sa.CheckConstraint(
                "verdict IS NULL OR verdict IN "
                "('no_trade', 'wait', 'long_scalp', 'short_scalp')",
                name="ck_tradingview_alert_verdict",
            ),
            sa.CheckConstraint(
                "confidence IS NULL OR confidence IN ('low', 'medium', 'high')",
                name="ck_tradingview_alert_confidence",
            ),
            sa.CheckConstraint(
                "length(content_sha256) = 64",
                name="ck_tradingview_alert_content_sha256",
            ),
            sa.CheckConstraint(
                "length(raw_payload_sha256) = 64",
                name="ck_tradingview_alert_raw_payload_sha256",
            ),
            sa.CheckConstraint(
                "contract_version <> 1 OR "
                "(bar_time_ms >= 946684800000 "
                "AND bar_time_ms < 4102444800000)",
                name="ck_tradingview_alert_v1_bar_time",
            ),
            sa.CheckConstraint(
                "contract_version <> 1 OR "
                "(length(alert_id) <= 200 "
                "AND length(indicator_version) <= 32 "
                "AND length(symbol) <= 32 "
                "AND length(timeframe) <= 16 "
                "AND length(setup) <= 64)",
                name="ck_tradingview_alert_v1_text_bounds",
            ),
            sa.PrimaryKeyConstraint("alert_id"),
        )
    else:
        _verify_existing_table()

    _ensure_indexes()


def downgrade() -> None:
    if _table_exists("tradingview_alert"):
        op.drop_table("tradingview_alert")
