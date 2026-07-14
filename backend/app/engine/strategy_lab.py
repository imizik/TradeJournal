"""Strategy Lab domain services for Pine versions and imported strategy runs."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from threading import RLock
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import JSON, cast, func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.engine.strategy_csv import TradingViewParseResult
from app.engine.strategy_metrics import (
    CALCULATION_VERSION,
    MetricCalculationError,
    MetricTrade,
    calculate_run_metrics,
)
from app.models import (
    STRATEGY_RUN_DETAIL_LIGHT,
    STRATEGY_RUN_LIGHT,
    STRATEGY_RUN_TRADE_LIGHT,
    STRATEGY_VERSION_LIGHT,
    StrategyDefinition,
    StrategyRun,
    StrategyRunMetrics,
    StrategyRunTrade,
    StrategyVersion,
)


# These fields describe the exact executable/versioned strategy. Once a run
# exists, changing one would sever the result from the code that produced it.
LOCKED_AFTER_RUN_FIELDS = {
    "version_label",
    "pine_source",
    "parameters",
    "entry_rule_summary",
    "exit_rule_summary",
    "execution_timing",
    "session_mode",
    "commission_type",
    "commission_value",
    "slippage_type",
    "slippage_value",
    "pyramiding",
}

# Version edits and first-run imports are rare, but their ordering is critical:
# a run must never lock a different source than the fingerprint it snapshots.
# The process lock protects local SQLite/single-process use; SELECT FOR UPDATE
# below extends the same ordering across workers on databases that support it.
_VERSION_MUTATION_LOCK = RLock()
_METRICS_CALCULATION_LOCK = RLock()
CSV_IMPORT_CONTRACT_VERSION = "1"


class StrategyLabError(ValueError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class ImportedStrategyRun:
    id: uuid.UUID
    strategy_version_id: uuid.UUID
    version_fingerprint: str
    source_sha256: str
    source_file_name: str | None


@dataclass(frozen=True)
class StrategyRunRead:
    run: StrategyRun
    strategy: StrategyDefinition
    version: StrategyVersion
    trade_count: int
    observed_start_at: datetime | None
    observed_end_at: datetime | None
    metrics_status: str
    metrics_calculated_at: datetime | None
    total_net_pnl: Decimal | None
    net_return_pct: Decimal | None
    expectancy: Decimal | None
    max_drawdown_pct: Decimal | None
    win_rate: Decimal | None


def canonical_json(value: Any) -> str:
    """Stable JSON used for persistence and source fingerprints."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def calculate_import_preview_fingerprint(
    *,
    source_sha256: str,
    source_timezone: str,
    strategy_version_id: uuid.UUID,
    version_fingerprint: str,
) -> str:
    """Bind a non-persistent preview to bytes, timezone, and exact Pine version."""
    payload = {
        "contract_version": CSV_IMPORT_CONTRACT_VERSION,
        "source_sha256": source_sha256.lower(),
        "source_timezone": source_timezone,
        "strategy_version_id": str(strategy_version_id),
        "version_fingerprint": version_fingerprint.lower(),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _canonical_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def calculate_version_fingerprint(
    *,
    pine_source: str,
    parameters: dict[str, Any],
    execution_timing: str,
    session_mode: str,
    commission_type: str,
    commission_value: Decimal | None,
    slippage_type: str,
    slippage_value: Decimal | None,
    pyramiding: int,
) -> str:
    """Hash the executable Pine source and all result-affecting assumptions."""
    normalized_source = pine_source.replace("\r\n", "\n").replace("\r", "\n")
    payload = {
        "pine_source": normalized_source,
        "parameters": parameters,
        "execution_timing": execution_timing,
        "session_mode": session_mode,
        "commission_type": commission_type,
        "commission_value": _canonical_decimal(commission_value),
        "slippage_type": slippage_type,
        "slippage_value": _canonical_decimal(slippage_value),
        "pyramiding": pyramiding,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _clean_required(value: str, label: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise StrategyLabError(422, f"{label} must not be blank")
    return cleaned


def _clean_pine_source(value: str) -> str:
    if not value.strip():
        raise StrategyLabError(422, "pine_source must not be blank")
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _validate_cost_assumption(
    assumption_type: str,
    value: Decimal | None,
    label: str,
) -> None:
    if assumption_type == "none" and value not in (None, Decimal("0")):
        raise StrategyLabError(422, f"{label}_value must be empty or zero when type is none")
    if assumption_type != "none" and value is None:
        raise StrategyLabError(422, f"{label}_value is required when type is {assumption_type}")


def _commit(session: Session, row, conflict_detail: str):
    try:
        session.add(row)
        session.commit()
        session.refresh(row)
        return row
    except IntegrityError as exc:
        session.rollback()
        raise StrategyLabError(409, conflict_detail) from exc


def get_strategy(session: Session, strategy_id: uuid.UUID) -> StrategyDefinition:
    row = session.get(StrategyDefinition, strategy_id)
    if row is None:
        raise StrategyLabError(404, "Strategy not found")
    return row


def list_strategies(session: Session) -> list[StrategyDefinition]:
    return list(session.exec(select(StrategyDefinition).order_by(StrategyDefinition.name)).all())


def create_strategy(
    session: Session,
    *,
    name: str,
    description: str | None,
    setup_type: str,
) -> StrategyDefinition:
    row = StrategyDefinition(
        name=_clean_required(name, "name"),
        description=description.strip() if description and description.strip() else None,
        setup_type=_clean_required(setup_type, "setup_type"),
    )
    return _commit(session, row, "A strategy with this name already exists")


def update_strategy(
    session: Session,
    strategy_id: uuid.UUID,
    changes: dict[str, Any],
) -> StrategyDefinition:
    row = get_strategy(session, strategy_id)
    if "name" in changes:
        row.name = _clean_required(changes["name"], "name")
    if "setup_type" in changes:
        row.setup_type = _clean_required(changes["setup_type"], "setup_type")
    if "description" in changes:
        value = changes["description"]
        row.description = value.strip() if value and value.strip() else None
    row.updated_at = datetime.utcnow()
    return _commit(session, row, "A strategy with this name already exists")


def get_version(session: Session, version_id: uuid.UUID) -> StrategyVersion:
    row = session.get(StrategyVersion, version_id)
    if row is None:
        raise StrategyLabError(404, "Strategy version not found")
    return row


def get_version_for_import(
    session: Session,
    version_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> StrategyVersion:
    """Load import assumptions while leaving the potentially large Pine text deferred."""
    query = (
        select(StrategyVersion)
        .options(*STRATEGY_VERSION_LIGHT)
        .where(StrategyVersion.id == version_id)
    )
    if for_update:
        query = query.with_for_update()
    row = session.exec(query).first()
    if row is None:
        raise StrategyLabError(404, "Strategy version not found")
    return row


def list_versions(session: Session, strategy_id: uuid.UUID) -> list[StrategyVersion]:
    return list(
        session.exec(
            select(StrategyVersion)
            .options(*STRATEGY_VERSION_LIGHT)
            .where(StrategyVersion.strategy_definition_id == strategy_id)
            .order_by(StrategyVersion.created_at.desc())
        ).all()
    )


def _validate_parent(
    session: Session,
    strategy_id: uuid.UUID,
    parent_version_id: uuid.UUID | None,
) -> None:
    if parent_version_id is None:
        return
    parent = get_version(session, parent_version_id)
    if parent.strategy_definition_id != strategy_id:
        raise StrategyLabError(422, "Parent version must belong to the same strategy")


def _demote_current_champion(
    session: Session,
    strategy_id: uuid.UUID,
    *,
    excluding: uuid.UUID | None = None,
) -> None:
    query = select(StrategyVersion).where(
        StrategyVersion.strategy_definition_id == strategy_id,
        StrategyVersion.status == "champion",
    )
    if excluding is not None:
        query = query.where(StrategyVersion.id != excluding)
    champions = session.exec(query).all()
    now = datetime.utcnow()
    for champion in champions:
        champion.status = "challenger"
        champion.updated_at = now
        session.add(champion)
    if champions:
        # The partial unique index requires demotion to reach the DB before a
        # replacement champion is inserted or promoted.
        session.flush()


def _version_values(data: dict[str, Any]) -> dict[str, Any]:
    parameters = data.get("parameters") or {}
    values = {
        "version_label": _clean_required(data["version_label"], "version_label"),
        "pine_source": _clean_pine_source(data["pine_source"]),
        "source_reference": data.get("source_reference"),
        "change_summary": data.get("change_summary"),
        "hypothesis": data.get("hypothesis"),
        "parameters_json": canonical_json(parameters),
        "entry_rule_summary": data.get("entry_rule_summary"),
        "exit_rule_summary": data.get("exit_rule_summary"),
        "execution_timing": data.get("execution_timing", "unknown"),
        "session_mode": data.get("session_mode", "regular"),
        "commission_type": data.get("commission_type", "none"),
        "commission_value": data.get("commission_value"),
        "slippage_type": data.get("slippage_type", "none"),
        "slippage_value": data.get("slippage_value"),
        "pyramiding": data.get("pyramiding", 0),
        "known_limitations": data.get("known_limitations"),
        "repainting_risk_notes": data.get("repainting_risk_notes"),
        "lookahead_risk_notes": data.get("lookahead_risk_notes"),
        "status": data.get("status", "draft"),
    }
    _validate_cost_assumption(
        values["commission_type"], values["commission_value"], "commission"
    )
    _validate_cost_assumption(
        values["slippage_type"], values["slippage_value"], "slippage"
    )
    values["source_fingerprint"] = calculate_version_fingerprint(
        pine_source=values["pine_source"],
        parameters=parameters,
        execution_timing=values["execution_timing"],
        session_mode=values["session_mode"],
        commission_type=values["commission_type"],
        commission_value=values["commission_value"],
        slippage_type=values["slippage_type"],
        slippage_value=values["slippage_value"],
        pyramiding=values["pyramiding"],
    )
    return values


def create_version(
    session: Session,
    strategy_id: uuid.UUID,
    data: dict[str, Any],
) -> StrategyVersion:
    get_strategy(session, strategy_id)
    parent_version_id = data.get("parent_version_id")
    _validate_parent(session, strategy_id, parent_version_id)
    values = _version_values(data)
    if values["status"] == "champion":
        _demote_current_champion(session, strategy_id)
    row = StrategyVersion(
        strategy_definition_id=strategy_id,
        parent_version_id=parent_version_id,
        **values,
    )
    return _commit(
        session,
        row,
        "This strategy already has a version with that label or a champion transition conflicted",
    )


def version_has_runs(session: Session, version_id: uuid.UUID) -> bool:
    return session.exec(
        select(StrategyRun.id).where(StrategyRun.strategy_version_id == version_id)
    ).first() is not None


def locked_version_ids(session: Session, strategy_id: uuid.UUID) -> set[uuid.UUID]:
    """Return all run-backed version ids for a strategy in one query."""
    return set(
        session.exec(
            select(StrategyRun.strategy_version_id)
            .join(
                StrategyVersion,
                StrategyVersion.id == StrategyRun.strategy_version_id,
            )
            .where(StrategyVersion.strategy_definition_id == strategy_id)
            .distinct()
        ).all()
    )


def _current_locked_value(row: StrategyVersion, field: str):
    if field == "parameters":
        return json.loads(row.parameters_json)
    return getattr(row, field)


def update_version(
    session: Session,
    version_id: uuid.UUID,
    changes: dict[str, Any],
) -> StrategyVersion:
    with _VERSION_MUTATION_LOCK:
        return _update_version_locked(session, version_id, changes)


def _update_version_locked(
    session: Session,
    version_id: uuid.UUID,
    changes: dict[str, Any],
) -> StrategyVersion:
    query = select(StrategyVersion).where(StrategyVersion.id == version_id).with_for_update()
    row = session.exec(query).first()
    if row is None:
        raise StrategyLabError(404, "Strategy version not found")

    if version_has_runs(session, version_id):
        changed_locked = sorted(
            field
            for field in LOCKED_AFTER_RUN_FIELDS.intersection(changes)
            if changes[field] != _current_locked_value(row, field)
        )
        if changed_locked:
            raise StrategyLabError(
                409,
                "Version is locked because it has runs; fork it to change: "
                + ", ".join(changed_locked),
            )

    if changes.get("status") == "champion" and row.status != "champion":
        _demote_current_champion(
            session,
            row.strategy_definition_id,
            excluding=row.id,
        )

    for field, value in changes.items():
        if field == "parameters":
            row.parameters_json = canonical_json(value or {})
        elif field == "version_label":
            row.version_label = _clean_required(value, field)
        elif field == "pine_source":
            row.pine_source = _clean_pine_source(value)
        elif hasattr(row, field):
            setattr(row, field, value)

    try:
        _validate_cost_assumption(
            row.commission_type, row.commission_value, "commission"
        )
        _validate_cost_assumption(
            row.slippage_type, row.slippage_value, "slippage"
        )
    except StrategyLabError:
        session.rollback()
        raise

    if LOCKED_AFTER_RUN_FIELDS.intersection(changes):
        row.source_fingerprint = calculate_version_fingerprint(
            pine_source=row.pine_source,
            parameters=json.loads(row.parameters_json),
            execution_timing=row.execution_timing,
            session_mode=row.session_mode,
            commission_type=row.commission_type,
            commission_value=row.commission_value,
            slippage_type=row.slippage_type,
            slippage_value=row.slippage_value,
            pyramiding=row.pyramiding,
        )
    row.updated_at = datetime.utcnow()
    return _commit(
        session,
        row,
        "This strategy already has a version with that label or a champion transition conflicted",
    )


def fork_version(
    session: Session,
    source_version_id: uuid.UUID,
    data: dict[str, Any],
) -> StrategyVersion:
    source = get_version(session, source_version_id)
    copied = {
        "version_label": data["version_label"],
        "pine_source": data.get("pine_source") or source.pine_source,
        "source_reference": data.get("source_reference", source.source_reference),
        "change_summary": data["change_summary"],
        "hypothesis": data["hypothesis"],
        "parameters": data.get("parameters", json.loads(source.parameters_json)),
        "entry_rule_summary": data.get("entry_rule_summary", source.entry_rule_summary),
        "exit_rule_summary": data.get("exit_rule_summary", source.exit_rule_summary),
        "execution_timing": data.get("execution_timing", source.execution_timing),
        "session_mode": data.get("session_mode", source.session_mode),
        "commission_type": data.get("commission_type", source.commission_type),
        "commission_value": data.get("commission_value", source.commission_value),
        "slippage_type": data.get("slippage_type", source.slippage_type),
        "slippage_value": data.get("slippage_value", source.slippage_value),
        "pyramiding": data.get("pyramiding", source.pyramiding),
        "known_limitations": data.get("known_limitations", source.known_limitations),
        "repainting_risk_notes": data.get(
            "repainting_risk_notes", source.repainting_risk_notes
        ),
        "lookahead_risk_notes": data.get(
            "lookahead_risk_notes", source.lookahead_risk_notes
        ),
        "status": data.get("status", "challenger"),
        "parent_version_id": source.id,
    }
    return create_version(session, source.strategy_definition_id, copied)


def find_duplicate_run_id(
    session: Session,
    strategy_version_id: uuid.UUID,
    source_sha256: str,
) -> uuid.UUID | None:
    """Return the matching run id without loading the stored CSV payload."""
    return session.exec(
        select(StrategyRun.id).where(
            StrategyRun.strategy_version_id == strategy_version_id,
            StrategyRun.source_sha256 == source_sha256,
        )
    ).first()


def _import_warnings(result: TradingViewParseResult) -> list[dict[str, Any]]:
    # Parser result warnings are the canonical aggregate; ParsedTrade.warnings
    # is a filtered view for per-trade preview and must not be counted twice.
    return [issue.to_dict() for issue in result.warnings]


def _validate_backtest_contains_trades(
    result: TradingViewParseResult,
    *,
    source_timezone: str,
    backtest_start,
    backtest_end,
) -> None:
    if backtest_start is None and backtest_end is None:
        return
    zone = ZoneInfo(source_timezone)
    observed_dates = [
        value.replace(tzinfo=timezone.utc).astimezone(zone).date()
        for trade in result.trades
        for value in (trade.entry_at, trade.exit_at)
    ]
    observed_start = min(observed_dates)
    observed_end = max(observed_dates)
    if backtest_start is not None and observed_start < backtest_start:
        raise StrategyLabError(
            422,
            f"backtest_start {backtest_start} excludes an imported trade on "
            f"{observed_start} in {source_timezone}",
        )
    if backtest_end is not None and observed_end > backtest_end:
        raise StrategyLabError(
            422,
            f"backtest_end {backtest_end} excludes an imported trade on "
            f"{observed_end} in {source_timezone}",
        )


def create_run_from_csv(session: Session, **kwargs: Any) -> ImportedStrategyRun:
    with _VERSION_MUTATION_LOCK:
        return _create_run_from_csv_locked(session, **kwargs)


def _create_run_from_csv_locked(
    session: Session,
    *,
    strategy_version_id: uuid.UUID,
    expected_version_fingerprint: str,
    expected_source_sha256: str,
    expected_preview_fingerprint: str,
    result: TradingViewParseResult,
    source_file_name: str | None,
    source_csv_text: str,
    symbol: str,
    timeframe: str,
    source_timezone: str,
    backtest_start,
    backtest_end,
    initial_capital: Decimal | None,
    currency: str,
    extended_hours: bool,
    notes: str | None,
) -> ImportedStrategyRun:
    """Persist one parsed export and all paired trades in one transaction."""
    version = get_version_for_import(session, strategy_version_id, for_update=True)
    if version.source_fingerprint != expected_version_fingerprint:
        raise StrategyLabError(
            409,
            "The strategy version changed after preview; preview the file again",
        )
    if result.source_sha256 != expected_source_sha256.lower():
        raise StrategyLabError(
            409,
            "The uploaded file does not match the previewed SHA-256",
        )
    preview_fingerprint = calculate_import_preview_fingerprint(
        source_sha256=result.source_sha256,
        source_timezone=source_timezone,
        strategy_version_id=version.id,
        version_fingerprint=version.source_fingerprint,
    )
    if preview_fingerprint != expected_preview_fingerprint.lower():
        raise StrategyLabError(
            409,
            "The import settings do not match the preview; preview the file again",
        )
    if result.rejected_trades:
        raise StrategyLabError(
            422,
            f"Import has {len(result.rejected_trades)} rejected trade group(s); "
            "resolve them before committing",
        )
    if not result.trades:
        raise StrategyLabError(422, "Import contains no valid paired trades")
    _validate_backtest_contains_trades(
        result,
        source_timezone=source_timezone,
        backtest_start=backtest_start,
        backtest_end=backtest_end,
    )
    if version.session_mode == "regular" and extended_hours:
        raise StrategyLabError(
            422,
            "extended_hours must be false for a regular-session strategy version",
        )
    if version.session_mode == "extended" and not extended_hours:
        raise StrategyLabError(
            422,
            "extended_hours must be true for an extended-session strategy version",
        )

    duplicate_id = find_duplicate_run_id(
        session,
        strategy_version_id,
        result.source_sha256,
    )
    if duplicate_id is not None:
        raise StrategyLabError(
            409,
            f"This file is already imported for the version as run {duplicate_id}",
        )

    run = StrategyRun(
        strategy_version_id=version.id,
        version_fingerprint=version.source_fingerprint,
        source="tradingview",
        symbol=symbol,
        timeframe=timeframe,
        source_timezone=source_timezone,
        backtest_start=backtest_start,
        backtest_end=backtest_end,
        initial_capital=initial_capital,
        currency=currency,
        commission_type=version.commission_type,
        commission_value=version.commission_value,
        slippage_type=version.slippage_type,
        slippage_value=version.slippage_value,
        execution_timing=version.execution_timing,
        session_mode=version.session_mode,
        extended_hours=extended_hours,
        pyramiding=version.pyramiding,
        parameters_json=version.parameters_json,
        notes=notes,
        source_file_name=source_file_name,
        source_sha256=result.source_sha256,
        source_headers_json=canonical_json(result.headers),
        source_mapping_json=canonical_json(result.mapping),
        source_warnings_json=canonical_json(_import_warnings(result)),
        source_csv_text=source_csv_text,
    )

    try:
        session.add(run)
        session.flush()
        for trade in result.trades:
            session.add(
                StrategyRunTrade(
                    run_id=run.id,
                    trade_number=trade.trade_number,
                    direction=trade.direction,
                    entry_at=trade.entry_at,
                    exit_at=trade.exit_at,
                    entry_at_raw=trade.entry_at_raw,
                    exit_at_raw=trade.exit_at_raw,
                    entry_price=trade.entry_price,
                    exit_price=trade.exit_price,
                    quantity=trade.quantity,
                    net_pnl=trade.net_pnl,
                    return_pct=trade.return_pct,
                    mfe=trade.mfe,
                    mfe_pct=trade.mfe_pct,
                    mae=trade.mae,
                    mae_pct=trade.mae_pct,
                    cumulative_pnl=trade.cumulative_pnl,
                    cumulative_return_pct=trade.cumulative_return_pct,
                    duration_bars=trade.duration_bars,
                    duration_minutes=trade.duration_minutes,
                    entry_signal=trade.entry_signal,
                    exit_signal=trade.exit_signal,
                    entry_comment=trade.entry_comment,
                    exit_comment=trade.exit_comment,
                    feature_snapshot_json=canonical_json(trade.feature_snapshot),
                    raw_entry_row_json=canonical_json(trade.raw_entry_row),
                    raw_exit_row_json=canonical_json(trade.raw_exit_row),
                )
            )
        imported = ImportedStrategyRun(
            id=run.id,
            strategy_version_id=run.strategy_version_id,
            version_fingerprint=run.version_fingerprint,
            source_sha256=result.source_sha256,
            source_file_name=run.source_file_name,
        )
        session.commit()
        return imported
    except IntegrityError as exc:
        session.rollback()
        duplicate_id = find_duplicate_run_id(
            session,
            strategy_version_id,
            result.source_sha256,
        )
        if duplicate_id is not None:
            raise StrategyLabError(
                409,
                "This file was already imported for the selected strategy version",
            ) from exc
        raise
    except Exception:
        session.rollback()
        raise


def _strategy_run_read_query(*run_loaders: Any):
    trade_stats = (
        select(
            StrategyRunTrade.run_id.label("run_id"),
            func.count(StrategyRunTrade.id).label("trade_count"),
            func.min(StrategyRunTrade.entry_at).label("observed_start_at"),
            func.max(StrategyRunTrade.exit_at).label("observed_end_at"),
        )
        .group_by(StrategyRunTrade.run_id)
        .subquery()
    )
    return (
        select(
            StrategyRun,
            StrategyDefinition,
            StrategyVersion,
            func.coalesce(trade_stats.c.trade_count, 0),
            trade_stats.c.observed_start_at,
            trade_stats.c.observed_end_at,
            StrategyRunMetrics.calculation_version,
            StrategyRunMetrics.calculated_at,
            StrategyRunMetrics.total_net_pnl,
            StrategyRunMetrics.net_return_pct,
            StrategyRunMetrics.expectancy,
            StrategyRunMetrics.max_drawdown_pct,
            StrategyRunMetrics.win_rate,
        )
        .join(
            StrategyVersion,
            StrategyVersion.id == StrategyRun.strategy_version_id,
        )
        .join(
            StrategyDefinition,
            StrategyDefinition.id == StrategyVersion.strategy_definition_id,
        )
        .outerjoin(trade_stats, trade_stats.c.run_id == StrategyRun.id)
        .outerjoin(StrategyRunMetrics, StrategyRunMetrics.run_id == StrategyRun.id)
        .options(*run_loaders, *STRATEGY_VERSION_LIGHT)
    )


def _strategy_run_read(row: Any) -> StrategyRunRead:
    calculation_version = row[6]
    if calculation_version is None:
        metrics_status = "pending"
    elif calculation_version == CALCULATION_VERSION:
        metrics_status = "ready"
    else:
        metrics_status = "stale"
    return StrategyRunRead(
        run=row[0],
        strategy=row[1],
        version=row[2],
        trade_count=int(row[3] or 0),
        observed_start_at=row[4],
        observed_end_at=row[5],
        metrics_status=metrics_status,
        metrics_calculated_at=row[7],
        total_net_pnl=row[8],
        net_return_pct=row[9],
        expectancy=row[10],
        max_drawdown_pct=row[11],
        win_rate=row[12],
    )


def list_strategy_runs(
    session: Session,
    *,
    strategy_id: uuid.UUID | None,
    version_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> tuple[list[StrategyRunRead], int]:
    filters = []
    if strategy_id is not None:
        filters.append(StrategyVersion.strategy_definition_id == strategy_id)
    if version_id is not None:
        filters.append(StrategyRun.strategy_version_id == version_id)

    count_query = select(func.count(StrategyRun.id)).join(
        StrategyVersion,
        StrategyVersion.id == StrategyRun.strategy_version_id,
    )
    if filters:
        count_query = count_query.where(*filters)
    total = int(session.exec(count_query).one())

    query = _strategy_run_read_query(*STRATEGY_RUN_LIGHT)
    if filters:
        query = query.where(*filters)
    rows = session.exec(
        query.order_by(StrategyRun.imported_at.desc(), StrategyRun.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return [_strategy_run_read(row) for row in rows], total


def get_strategy_run(session: Session, run_id: uuid.UUID) -> StrategyRunRead:
    row = session.exec(
        _strategy_run_read_query(*STRATEGY_RUN_DETAIL_LIGHT).where(
            StrategyRun.id == run_id
        )
    ).first()
    if row is None:
        raise StrategyLabError(404, "Strategy run not found")
    return _strategy_run_read(row)


def get_strategy_run_warning_count(session: Session, run_id: uuid.UUID) -> int:
    """Count persisted import warnings in SQL without returning the JSON payload."""
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        warning_array = cast(StrategyRun.source_warnings_json, JSON)
    else:
        warning_array = StrategyRun.source_warnings_json
    value = session.exec(
        select(func.coalesce(func.json_array_length(warning_array), 0)).where(
            StrategyRun.id == run_id
        )
    ).one()
    return int(value or 0)


def _source_day_start(value: date, source_zone: ZoneInfo) -> datetime:
    return (
        datetime.combine(value, time.min, tzinfo=source_zone)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )


def list_strategy_run_trades(
    session: Session,
    run_id: uuid.UUID,
    *,
    direction: str | None,
    outcome: str | None,
    entry_date_from: date | None,
    entry_date_to: date | None,
    limit: int,
    offset: int,
) -> tuple[list[StrategyRunTrade], int]:
    source_timezone = session.exec(
        select(StrategyRun.source_timezone).where(StrategyRun.id == run_id)
    ).first()
    if source_timezone is None:
        raise StrategyLabError(404, "Strategy run not found")
    if (
        entry_date_from is not None
        and entry_date_to is not None
        and entry_date_from > entry_date_to
    ):
        raise StrategyLabError(
            422,
            "entry_date_from must be on or before entry_date_to",
        )
    try:
        source_zone = ZoneInfo(source_timezone.strip())
    except (AttributeError, OSError, TypeError, ValueError, ZoneInfoNotFoundError) as exc:
        raise StrategyLabError(422, "Strategy run has an invalid source timezone") from exc

    filters = [StrategyRunTrade.run_id == run_id]
    if direction is not None:
        filters.append(StrategyRunTrade.direction == direction)
    if outcome == "winner":
        filters.append(StrategyRunTrade.net_pnl > 0)
    elif outcome == "loser":
        filters.append(StrategyRunTrade.net_pnl < 0)
    elif outcome == "breakeven":
        filters.append(StrategyRunTrade.net_pnl == 0)
    elif outcome == "unknown":
        filters.append(StrategyRunTrade.net_pnl.is_(None))
    if entry_date_from is not None:
        filters.append(
            StrategyRunTrade.entry_at >= _source_day_start(entry_date_from, source_zone)
        )
    if entry_date_to is not None:
        try:
            day_after = entry_date_to + timedelta(days=1)
        except OverflowError as exc:
            raise StrategyLabError(422, "entry_date_to is out of supported range") from exc
        filters.append(
            StrategyRunTrade.entry_at < _source_day_start(day_after, source_zone)
        )

    total = int(
        session.exec(
            select(func.count(StrategyRunTrade.id)).where(*filters)
        ).one()
    )
    rows = list(
        session.exec(
            select(StrategyRunTrade)
            .options(*STRATEGY_RUN_TRADE_LIGHT)
            .where(*filters)
            .order_by(StrategyRunTrade.trade_number, StrategyRunTrade.id)
            .offset(offset)
            .limit(limit)
        ).all()
    )
    return rows, total


def _get_run_for_metrics(
    session: Session,
    run_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> StrategyRun:
    """Load metric inputs while keeping the imported CSV payload deferred."""
    query = (
        select(StrategyRun)
        .options(*STRATEGY_RUN_LIGHT)
        .where(StrategyRun.id == run_id)
    )
    if for_update:
        query = query.with_for_update()
    row = session.exec(query).first()
    if row is None:
        raise StrategyLabError(404, "Strategy run not found")
    return row


def get_run_metrics(session: Session, run_id: uuid.UUID) -> StrategyRunMetrics:
    """Return persisted metrics without loading the run's source CSV."""
    _get_run_for_metrics(session, run_id)
    row = session.get(StrategyRunMetrics, run_id)
    if row is None:
        raise StrategyLabError(
            404,
            "Strategy run metrics have not been calculated",
        )
    return row


def recalculate_run_metrics(
    session: Session,
    run_id: uuid.UUID,
) -> StrategyRunMetrics:
    """Deterministically calculate and upsert one metric row for a run."""
    with _METRICS_CALCULATION_LOCK:
        return _recalculate_run_metrics_locked(session, run_id)


def _recalculate_run_metrics_locked(
    session: Session,
    run_id: uuid.UUID,
) -> StrategyRunMetrics:
    run = _get_run_for_metrics(session, run_id, for_update=True)
    trades = session.exec(
        select(StrategyRunTrade)
        .options(*STRATEGY_RUN_TRADE_LIGHT)
        .where(StrategyRunTrade.run_id == run_id)
        .order_by(StrategyRunTrade.trade_number)
    ).all()
    metric_trades = [
        MetricTrade(
            trade_number=trade.trade_number,
            direction=trade.direction,
            entry_at=trade.entry_at,
            exit_at=trade.exit_at,
            net_pnl=trade.net_pnl,
            return_pct=trade.return_pct,
            mfe=trade.mfe,
            mae=trade.mae,
            duration_minutes=trade.duration_minutes,
            cumulative_return_pct=trade.cumulative_return_pct,
        )
        for trade in trades
    ]

    try:
        result = calculate_run_metrics(
            metric_trades,
            initial_capital=run.initial_capital,
            source_timezone=run.source_timezone,
        )
    except MetricCalculationError as exc:
        session.rollback()
        raise StrategyLabError(422, str(exc)) from exc

    row = session.get(StrategyRunMetrics, run_id)
    if row is None:
        row = StrategyRunMetrics(
            run_id=run_id,
            calculation_version=result.calculation_version,
        )

    row.calculation_version = result.calculation_version
    row.calculated_at = datetime.utcnow()
    row.trade_count = result.trade_count
    row.winning_trades = result.winning_trades
    row.losing_trades = result.losing_trades
    row.win_rate = result.win_rate
    row.average_winner = result.average_winner
    row.average_loser = result.average_loser
    row.payoff_ratio = result.payoff_ratio
    row.expectancy = result.expectancy
    row.profit_factor = result.profit_factor
    row.total_net_pnl = result.total_net_pnl
    row.net_return_pct = result.net_return_pct
    row.max_drawdown = result.max_drawdown
    row.max_drawdown_pct = result.max_drawdown_pct
    row.average_mfe = result.average_mfe
    row.median_mfe = result.median_mfe
    row.average_mae = result.average_mae
    row.median_mae = result.median_mae
    row.average_holding_minutes = result.average_holding_minutes
    row.top_1_profit_contribution_pct = result.top_1_profit_contribution_pct
    row.top_3_profit_contribution_pct = result.top_3_profit_contribution_pct
    row.top_5_profit_contribution_pct = result.top_5_profit_contribution_pct
    row.long_summary_json = canonical_json(result.long_summary)
    row.short_summary_json = canonical_json(result.short_summary)
    row.time_bucket_summary_json = canonical_json(result.time_bucket_summary)
    row.coverage_json = canonical_json(result.coverage)
    row.equity_curve_json = canonical_json(result.equity_curve)
    row.drawdown_curve_json = canonical_json(result.drawdown_curve)
    row.findings_json = canonical_json(result.findings)

    try:
        session.add(row)
        session.commit()
        session.refresh(row)
        return row
    except Exception:
        session.rollback()
        raise
