"""Strategy Lab API — Stage 1 strategy definitions and Pine versions."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import (
    BaseModel,
    ConfigDict,
    Field as PydanticField,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlmodel import Session
from starlette.concurrency import run_in_threadpool

from app.database import get_session
from app.engine import strategy_lab as service
from app.engine.strategy_csv import (
    MAX_CSV_BYTES,
    TradingViewCSVError,
    TradingViewParseResult,
    parse_tradingview_csv,
)
from app.models import StrategyRunMetrics, StrategyRunTrade, StrategyVersion

router = APIRouter()

VersionStatus = Literal["draft", "challenger", "champion", "shadow", "retired"]
ExecutionTiming = Literal["bar_close", "next_bar", "intrabar", "unknown"]
SessionMode = Literal["regular", "extended", "custom"]
CommissionType = Literal[
    "none", "percent", "cash_per_order", "cash_per_contract", "custom"
]
SlippageType = Literal["none", "ticks", "percent", "cash_per_order", "custom"]


def _not_blank(value: str, label: str) -> str:
    if not value.strip():
        raise ValueError(f"{label} must not be blank")
    return value


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StrategyCreate(StrictRequest):
    name: str = PydanticField(min_length=1, max_length=200)
    description: str | None = None
    setup_type: str = PydanticField(default="custom", min_length=1, max_length=100)

    @field_validator("name", "setup_type")
    @classmethod
    def validate_required_text(cls, value: str, info):
        return _not_blank(value, info.field_name)


class StrategyUpdate(StrictRequest):
    name: str | None = PydanticField(default=None, min_length=1, max_length=200)
    description: str | None = None
    setup_type: str | None = PydanticField(default=None, min_length=1, max_length=100)

    @field_validator("name", "setup_type")
    @classmethod
    def validate_optional_text(cls, value: str | None, info):
        return _not_blank(value, info.field_name) if value is not None else value


class StrategyOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    description: str | None
    setup_type: str
    created_at: datetime
    updated_at: datetime


class VersionCreate(StrictRequest):
    version_label: str = PydanticField(min_length=1, max_length=100)
    parent_version_id: uuid.UUID | None = None
    pine_source: str = PydanticField(min_length=1)
    source_reference: str | None = None
    change_summary: str | None = None
    hypothesis: str | None = None
    parameters: dict[str, Any] = PydanticField(default_factory=dict)
    entry_rule_summary: str | None = None
    exit_rule_summary: str | None = None
    execution_timing: ExecutionTiming = "unknown"
    session_mode: SessionMode = "regular"
    commission_type: CommissionType = "none"
    commission_value: Decimal | None = PydanticField(
        default=None, ge=0, max_digits=18, decimal_places=6
    )
    slippage_type: SlippageType = "none"
    slippage_value: Decimal | None = PydanticField(
        default=None, ge=0, max_digits=18, decimal_places=6
    )
    pyramiding: int = PydanticField(default=0, ge=0, le=2_147_483_647)
    known_limitations: str | None = None
    repainting_risk_notes: str | None = None
    lookahead_risk_notes: str | None = None
    status: VersionStatus = "draft"

    @field_validator("version_label", "pine_source")
    @classmethod
    def validate_required_text(cls, value: str, info):
        return _not_blank(value, info.field_name)


class VersionUpdate(StrictRequest):
    version_label: str | None = PydanticField(default=None, min_length=1, max_length=100)
    pine_source: str | None = PydanticField(default=None, min_length=1)
    source_reference: str | None = None
    change_summary: str | None = None
    hypothesis: str | None = None
    parameters: dict[str, Any] | None = None
    entry_rule_summary: str | None = None
    exit_rule_summary: str | None = None
    execution_timing: ExecutionTiming | None = None
    session_mode: SessionMode | None = None
    commission_type: CommissionType | None = None
    commission_value: Decimal | None = PydanticField(
        default=None, ge=0, max_digits=18, decimal_places=6
    )
    slippage_type: SlippageType | None = None
    slippage_value: Decimal | None = PydanticField(
        default=None, ge=0, max_digits=18, decimal_places=6
    )
    pyramiding: int | None = PydanticField(
        default=None, ge=0, le=2_147_483_647
    )
    known_limitations: str | None = None
    repainting_risk_notes: str | None = None
    lookahead_risk_notes: str | None = None
    status: VersionStatus | None = None

    @field_validator("version_label", "pine_source")
    @classmethod
    def validate_optional_required_text(cls, value: str | None, info):
        return _not_blank(value, info.field_name) if value is not None else value

    @model_validator(mode="after")
    def reject_null_for_required_fields(self):
        required = {
            "version_label",
            "pine_source",
            "parameters",
            "execution_timing",
            "session_mode",
            "commission_type",
            "slippage_type",
            "pyramiding",
            "status",
        }
        invalid = sorted(
            field
            for field in required.intersection(self.model_fields_set)
            if getattr(self, field) is None
        )
        if invalid:
            raise ValueError("Fields may not be null: " + ", ".join(invalid))
        return self


class VersionForkRequest(StrictRequest):
    version_label: str = PydanticField(min_length=1, max_length=100)
    change_summary: str = PydanticField(min_length=1)
    hypothesis: str = PydanticField(min_length=1)
    pine_source: str | None = PydanticField(default=None, min_length=1)
    source_reference: str | None = None
    parameters: dict[str, Any] | None = None
    entry_rule_summary: str | None = None
    exit_rule_summary: str | None = None
    execution_timing: ExecutionTiming | None = None
    session_mode: SessionMode | None = None
    commission_type: CommissionType | None = None
    commission_value: Decimal | None = PydanticField(
        default=None, ge=0, max_digits=18, decimal_places=6
    )
    slippage_type: SlippageType | None = None
    slippage_value: Decimal | None = PydanticField(
        default=None, ge=0, max_digits=18, decimal_places=6
    )
    pyramiding: int | None = PydanticField(
        default=None, ge=0, le=2_147_483_647
    )
    known_limitations: str | None = None
    repainting_risk_notes: str | None = None
    lookahead_risk_notes: str | None = None
    status: VersionStatus = "challenger"

    @field_validator("version_label", "change_summary", "hypothesis", "pine_source")
    @classmethod
    def validate_text(cls, value: str | None, info):
        return _not_blank(value, info.field_name) if value is not None else value

    @model_validator(mode="after")
    def reject_null_for_overrides(self):
        required_when_present = {
            "parameters",
            "execution_timing",
            "session_mode",
            "commission_type",
            "slippage_type",
            "pyramiding",
        }
        invalid = sorted(
            field
            for field in required_when_present.intersection(self.model_fields_set)
            if getattr(self, field) is None
        )
        if invalid:
            raise ValueError("Override fields may not be null: " + ", ".join(invalid))
        return self


class VersionSummary(BaseModel):
    id: uuid.UUID
    strategy_definition_id: uuid.UUID
    parent_version_id: uuid.UUID | None
    version_label: str
    source_fingerprint: str
    source_reference: str | None
    change_summary: str | None
    hypothesis: str | None
    parameters: dict[str, Any]
    entry_rule_summary: str | None
    exit_rule_summary: str | None
    execution_timing: str
    session_mode: str
    commission_type: str
    commission_value: Decimal | None
    slippage_type: str
    slippage_value: Decimal | None
    pyramiding: int
    known_limitations: str | None
    repainting_risk_notes: str | None
    lookahead_risk_notes: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    locked: bool = False


class VersionDetail(VersionSummary):
    pine_source: str


class StrategyDetail(StrategyOut):
    versions: list[VersionSummary]


class ImportIssueOut(BaseModel):
    level: str
    code: str
    message: str
    trade_number: int | None = None
    row_number: int | None = None


class RejectedTradeOut(BaseModel):
    trade_number: int | None
    issue_count: int
    issues: list[ImportIssueOut]
    issues_truncated: bool
    raw_row_count: int
    raw_rows: list[dict[str, str | None]]
    raw_rows_truncated: bool


class ParsedTradePreview(BaseModel):
    trade_number: int
    direction: str
    entry_at: datetime
    exit_at: datetime
    entry_at_raw: str
    exit_at_raw: str
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    net_pnl: Decimal | None
    return_pct: Decimal | None
    mfe: Decimal | None
    mfe_pct: Decimal | None
    mae: Decimal | None
    mae_pct: Decimal | None
    cumulative_pnl: Decimal | None
    cumulative_return_pct: Decimal | None
    duration_bars: int | None
    duration_minutes: int
    entry_signal: str | None
    exit_signal: str | None
    entry_comment: str | None
    exit_comment: str | None
    feature_snapshot: dict[str, Any]
    raw_entry_row: dict[str, str | None]
    raw_exit_row: dict[str, str | None]
    warning_count: int
    warnings: list[ImportIssueOut]
    warnings_truncated: bool


class ImportVersionContext(BaseModel):
    id: uuid.UUID
    version_label: str
    source_fingerprint: str
    hypothesis: str | None
    parameters: dict[str, Any]
    execution_timing: str
    session_mode: str
    commission_type: str
    commission_value: Decimal | None
    slippage_type: str
    slippage_value: Decimal | None
    pyramiding: int


class RunImportPreview(BaseModel):
    source_file_name: str | None
    source_sha256: str
    source_timezone: str
    preview_fingerprint: str
    encoding: str
    headers: list[str]
    mapping: dict[str, str]
    source_row_count: int
    accepted_row_count: int
    skipped_row_count: int
    rejected_row_count: int
    accepted_trade_count: int
    rejected_trade_count: int
    warning_count: int
    warnings: list[ImportIssueOut]
    warnings_truncated: bool
    rejected_trades: list[RejectedTradeOut]
    rejected_trades_truncated: bool
    trades: list[ParsedTradePreview]
    preview_truncated: bool
    observed_start_at: datetime | None
    observed_end_at: datetime | None
    duplicate_run_id: uuid.UUID | None
    can_commit: bool
    version: ImportVersionContext


class RunImportRequest(StrictRequest):
    strategy_version_id: uuid.UUID
    expected_version_fingerprint: str = PydanticField(
        pattern=r"^[0-9a-fA-F]{64}$"
    )
    expected_source_sha256: str = PydanticField(pattern=r"^[0-9a-fA-F]{64}$")
    expected_preview_fingerprint: str = PydanticField(
        pattern=r"^[0-9a-fA-F]{64}$"
    )
    symbol: str = PydanticField(min_length=1, max_length=64)
    timeframe: str = PydanticField(min_length=1, max_length=50)
    source_timezone: str = PydanticField(min_length=1, max_length=100)
    backtest_start: date | None = None
    backtest_end: date | None = None
    initial_capital: Decimal | None = PydanticField(
        default=None, ge=0, max_digits=18, decimal_places=6
    )
    currency: str = PydanticField(
        default="USD", min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$"
    )
    extended_hours: bool = False
    notes: str | None = PydanticField(default=None, max_length=10_000)

    @field_validator("symbol", "timeframe", "source_timezone")
    @classmethod
    def validate_import_text(cls, value: str, info):
        return _not_blank(value, info.field_name).strip()

    @field_validator(
        "expected_version_fingerprint",
        "expected_source_sha256",
        "expected_preview_fingerprint",
    )
    @classmethod
    def normalize_hash(cls, value: str):
        return value.lower()

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str):
        return value.upper()

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None):
        return value.strip() if value and value.strip() else None

    @model_validator(mode="after")
    def validate_backtest_range(self):
        if (
            self.backtest_start is not None
            and self.backtest_end is not None
            and self.backtest_start > self.backtest_end
        ):
            raise ValueError("backtest_start must be on or before backtest_end")
        return self


class RunImportOut(BaseModel):
    run_id: uuid.UUID
    strategy_version_id: uuid.UUID
    version_fingerprint: str
    source_sha256: str
    source_file_name: str | None
    imported_trade_count: int
    imported_row_count: int
    skipped_row_count: int
    rejected_row_count: int
    warning_count: int
    metrics_status: Literal["pending"] = "pending"


class StrategyRunSummaryOut(BaseModel):
    id: uuid.UUID
    strategy_definition_id: uuid.UUID
    strategy_name: str
    setup_type: str
    strategy_version_id: uuid.UUID
    version_label: str
    version_status: str
    symbol: str
    timeframe: str
    source_timezone: str
    backtest_start: date | None
    backtest_end: date | None
    observed_start_at: datetime | None
    observed_end_at: datetime | None
    currency: str
    source_file_name: str | None
    imported_at: datetime
    trade_count: int
    metrics_status: Literal["pending", "ready", "stale"]
    metrics_calculated_at: datetime | None
    total_net_pnl: Decimal | None
    net_return_pct: Decimal | None
    expectancy: Decimal | None
    max_drawdown_pct: Decimal | None
    win_rate: Decimal | None


class StrategyRunPageOut(BaseModel):
    items: list[StrategyRunSummaryOut]
    total: int
    limit: int
    offset: int


class StrategyRunDetailOut(StrategyRunSummaryOut):
    version_hypothesis: str | None
    version_change_summary: str | None
    version_fingerprint: str
    source: str
    initial_capital: Decimal | None
    parameters: dict[str, Any]
    commission_type: str
    commission_value: Decimal | None
    slippage_type: str
    slippage_value: Decimal | None
    execution_timing: str
    session_mode: str
    extended_hours: bool
    pyramiding: int
    notes: str | None
    source_sha256: str | None
    source_warning_count: int
    created_at: datetime


class StrategyRunTradeOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    run_id: uuid.UUID
    trade_number: int
    direction: str
    entry_at: datetime | None
    exit_at: datetime | None
    entry_at_raw: str | None
    exit_at_raw: str | None
    entry_price: Decimal | None
    exit_price: Decimal | None
    quantity: Decimal | None
    net_pnl: Decimal | None
    return_pct: Decimal | None
    mfe: Decimal | None
    mfe_pct: Decimal | None
    mae: Decimal | None
    mae_pct: Decimal | None
    cumulative_pnl: Decimal | None
    cumulative_return_pct: Decimal | None
    duration_bars: int | None
    duration_minutes: int | None
    entry_signal: str | None
    exit_signal: str | None
    created_at: datetime


class StrategyRunTradePageOut(BaseModel):
    items: list[StrategyRunTradeOut]
    total: int
    limit: int
    offset: int


class StrategyRunMetricsOut(BaseModel):
    run_id: uuid.UUID
    calculation_version: str
    calculated_at: datetime
    trade_count: int
    winning_trades: int
    losing_trades: int
    win_rate: Decimal | None
    average_winner: Decimal | None
    average_loser: Decimal | None
    payoff_ratio: Decimal | None
    expectancy: Decimal | None
    profit_factor: Decimal | None
    total_net_pnl: Decimal | None
    net_return_pct: Decimal | None
    max_drawdown: Decimal | None
    max_drawdown_pct: Decimal | None
    average_mfe: Decimal | None
    median_mfe: Decimal | None
    average_mae: Decimal | None
    median_mae: Decimal | None
    average_holding_minutes: Decimal | None
    top_1_profit_contribution_pct: Decimal | None
    top_3_profit_contribution_pct: Decimal | None
    top_5_profit_contribution_pct: Decimal | None
    long_summary: dict[str, Any]
    short_summary: dict[str, Any]
    time_bucket_summary: dict[str, Any]
    coverage: dict[str, Any]
    equity_curve: list[dict[str, Any]]
    drawdown_curve: list[dict[str, Any]]
    findings: list[Any]


def _version_summary(row: StrategyVersion, *, locked: bool = False) -> VersionSummary:
    return VersionSummary(
        id=row.id,
        strategy_definition_id=row.strategy_definition_id,
        parent_version_id=row.parent_version_id,
        version_label=row.version_label,
        source_fingerprint=row.source_fingerprint,
        source_reference=row.source_reference,
        change_summary=row.change_summary,
        hypothesis=row.hypothesis,
        parameters=json.loads(row.parameters_json),
        entry_rule_summary=row.entry_rule_summary,
        exit_rule_summary=row.exit_rule_summary,
        execution_timing=row.execution_timing,
        session_mode=row.session_mode,
        commission_type=row.commission_type,
        commission_value=row.commission_value,
        slippage_type=row.slippage_type,
        slippage_value=row.slippage_value,
        pyramiding=row.pyramiding,
        known_limitations=row.known_limitations,
        repainting_risk_notes=row.repainting_risk_notes,
        lookahead_risk_notes=row.lookahead_risk_notes,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
        locked=locked,
    )


def _version_detail(
    session: Session, row: StrategyVersion
) -> VersionDetail:
    summary = _version_summary(row, locked=service.version_has_runs(session, row.id))
    return VersionDetail(**summary.model_dump(), pine_source=row.pine_source)


def _http_error(exc: service.StrategyLabError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


def _run_summary_out(row: service.StrategyRunRead) -> StrategyRunSummaryOut:
    run = row.run
    return StrategyRunSummaryOut(
        id=run.id,
        strategy_definition_id=row.strategy.id,
        strategy_name=row.strategy.name,
        setup_type=row.strategy.setup_type,
        strategy_version_id=run.strategy_version_id,
        version_label=row.version.version_label,
        version_status=row.version.status,
        symbol=run.symbol,
        timeframe=run.timeframe,
        source_timezone=run.source_timezone,
        backtest_start=run.backtest_start,
        backtest_end=run.backtest_end,
        observed_start_at=row.observed_start_at,
        observed_end_at=row.observed_end_at,
        currency=run.currency,
        source_file_name=run.source_file_name,
        imported_at=run.imported_at,
        trade_count=row.trade_count,
        metrics_status=row.metrics_status,
        metrics_calculated_at=row.metrics_calculated_at,
        total_net_pnl=row.total_net_pnl,
        net_return_pct=row.net_return_pct,
        expectancy=row.expectancy,
        max_drawdown_pct=row.max_drawdown_pct,
        win_rate=row.win_rate,
    )


def _run_detail_out(
    row: service.StrategyRunRead,
    *,
    source_warning_count: int,
) -> StrategyRunDetailOut:
    run = row.run
    return StrategyRunDetailOut(
        **_run_summary_out(row).model_dump(),
        version_hypothesis=row.version.hypothesis,
        version_change_summary=row.version.change_summary,
        version_fingerprint=run.version_fingerprint,
        source=run.source,
        initial_capital=run.initial_capital,
        parameters=json.loads(run.parameters_json),
        commission_type=run.commission_type,
        commission_value=run.commission_value,
        slippage_type=run.slippage_type,
        slippage_value=run.slippage_value,
        execution_timing=run.execution_timing,
        session_mode=run.session_mode,
        extended_hours=run.extended_hours,
        pyramiding=run.pyramiding,
        notes=run.notes,
        source_sha256=run.source_sha256,
        source_warning_count=source_warning_count,
        created_at=run.created_at,
    )


def _run_metrics_out(row: StrategyRunMetrics) -> StrategyRunMetricsOut:
    return StrategyRunMetricsOut(
        run_id=row.run_id,
        calculation_version=row.calculation_version,
        calculated_at=row.calculated_at,
        trade_count=row.trade_count,
        winning_trades=row.winning_trades,
        losing_trades=row.losing_trades,
        win_rate=row.win_rate,
        average_winner=row.average_winner,
        average_loser=row.average_loser,
        payoff_ratio=row.payoff_ratio,
        expectancy=row.expectancy,
        profit_factor=row.profit_factor,
        total_net_pnl=row.total_net_pnl,
        net_return_pct=row.net_return_pct,
        max_drawdown=row.max_drawdown,
        max_drawdown_pct=row.max_drawdown_pct,
        average_mfe=row.average_mfe,
        median_mfe=row.median_mfe,
        average_mae=row.average_mae,
        median_mae=row.median_mae,
        average_holding_minutes=row.average_holding_minutes,
        top_1_profit_contribution_pct=row.top_1_profit_contribution_pct,
        top_3_profit_contribution_pct=row.top_3_profit_contribution_pct,
        top_5_profit_contribution_pct=row.top_5_profit_contribution_pct,
        long_summary=json.loads(row.long_summary_json),
        short_summary=json.loads(row.short_summary_json),
        time_bucket_summary=json.loads(row.time_bucket_summary_json),
        coverage=json.loads(row.coverage_json),
        equity_curve=json.loads(row.equity_curve_json),
        drawdown_curve=json.loads(row.drawdown_curve_json),
        findings=json.loads(row.findings_json),
    )


PREVIEW_TRADE_LIMIT = 100
PREVIEW_WARNING_LIMIT = 200
PREVIEW_REJECTED_TRADE_LIMIT = 100
PREVIEW_RAW_VALUE_LIMIT = 1_000
PREVIEW_TRADE_WARNING_LIMIT = 20
PREVIEW_REJECTED_ISSUE_LIMIT = 20
PREVIEW_REJECTED_RAW_ROW_LIMIT = 20


def _safe_file_name(value: str | None) -> str | None:
    if not value:
        return None
    name = value.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return name[:255] or None


def _preview_issue(issue) -> dict[str, Any]:
    payload = issue.to_dict()
    payload["message"] = payload["message"][:PREVIEW_RAW_VALUE_LIMIT]
    return payload


def _preview_raw_row(row: dict[str, str | None]) -> dict[str, str | None]:
    return {
        key: (
            value
            if value is None or len(value) <= PREVIEW_RAW_VALUE_LIMIT
            else value[:PREVIEW_RAW_VALUE_LIMIT] + "…"
        )
        for key, value in row.items()
    }


def _preview_trade(trade) -> ParsedTradePreview:
    payload = trade.preview_dict()
    payload["raw_entry_row"] = _preview_raw_row(trade.raw_entry_row)
    payload["raw_exit_row"] = _preview_raw_row(trade.raw_exit_row)
    payload["warning_count"] = len(trade.warnings)
    payload["warnings"] = [
        _preview_issue(issue)
        for issue in trade.warnings[:PREVIEW_TRADE_WARNING_LIMIT]
    ]
    payload["warnings_truncated"] = (
        len(trade.warnings) > PREVIEW_TRADE_WARNING_LIMIT
    )
    return ParsedTradePreview(**payload)


def _preview_rejected_trade(item) -> RejectedTradeOut:
    payload = item.to_dict()
    payload["issue_count"] = len(item.issues)
    payload["issues"] = [
        _preview_issue(issue)
        for issue in item.issues[:PREVIEW_REJECTED_ISSUE_LIMIT]
    ]
    payload["issues_truncated"] = (
        len(item.issues) > PREVIEW_REJECTED_ISSUE_LIMIT
    )
    payload["raw_row_count"] = len(item.raw_rows)
    payload["raw_rows"] = [
        _preview_raw_row(row)
        for row in item.raw_rows[:PREVIEW_REJECTED_RAW_ROW_LIMIT]
    ]
    payload["raw_rows_truncated"] = (
        len(item.raw_rows) > PREVIEW_REJECTED_RAW_ROW_LIMIT
    )
    return RejectedTradeOut(**payload)


def _version_import_context(row: StrategyVersion) -> ImportVersionContext:
    return ImportVersionContext(
        id=row.id,
        version_label=row.version_label,
        source_fingerprint=row.source_fingerprint,
        hypothesis=row.hypothesis,
        parameters=json.loads(row.parameters_json),
        execution_timing=row.execution_timing,
        session_mode=row.session_mode,
        commission_type=row.commission_type,
        commission_value=row.commission_value,
        slippage_type=row.slippage_type,
        slippage_value=row.slippage_value,
        pyramiding=row.pyramiding,
    )


async def _parse_upload(
    file: UploadFile,
    source_timezone: str,
) -> tuple[bytes, TradingViewParseResult]:
    data = await file.read(MAX_CSV_BYTES + 1)
    try:
        result = await run_in_threadpool(
            parse_tradingview_csv,
            data,
            source_timezone,
        )
        return data, result
    except TradingViewCSVError as exc:
        status_code = (
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            if getattr(exc, "code", None) == "file_too_large"
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


def _preview_response(
    *,
    file_name: str | None,
    version: StrategyVersion,
    result: TradingViewParseResult,
    source_timezone: str,
    duplicate_run_id: uuid.UUID | None,
) -> RunImportPreview:
    accepted_rows = len(result.trades) * 2
    rejected_rows = sum(len(item.raw_rows) for item in result.rejected_trades)
    skipped_rows = max(0, result.row_count - accepted_rows - rejected_rows)
    warning_count = len(result.warnings)
    preview_trades = result.trades[:PREVIEW_TRADE_LIMIT]
    preview_warnings = result.warnings[:PREVIEW_WARNING_LIMIT]
    preview_rejected = result.rejected_trades[:PREVIEW_REJECTED_TRADE_LIMIT]
    return RunImportPreview(
        source_file_name=file_name,
        source_sha256=result.source_sha256,
        source_timezone=source_timezone,
        preview_fingerprint=service.calculate_import_preview_fingerprint(
            source_sha256=result.source_sha256,
            source_timezone=source_timezone,
            strategy_version_id=version.id,
            version_fingerprint=version.source_fingerprint,
        ),
        encoding=result.encoding,
        headers=result.headers,
        mapping=result.mapping,
        source_row_count=result.row_count,
        accepted_row_count=accepted_rows,
        skipped_row_count=skipped_rows,
        rejected_row_count=rejected_rows,
        accepted_trade_count=len(result.trades),
        rejected_trade_count=len(result.rejected_trades),
        warning_count=warning_count,
        warnings=[ImportIssueOut(**_preview_issue(item)) for item in preview_warnings],
        warnings_truncated=len(result.warnings) > PREVIEW_WARNING_LIMIT,
        rejected_trades=[
            _preview_rejected_trade(item) for item in preview_rejected
        ],
        rejected_trades_truncated=(
            len(result.rejected_trades) > PREVIEW_REJECTED_TRADE_LIMIT
        ),
        trades=[
            _preview_trade(trade) for trade in preview_trades
        ],
        preview_truncated=len(result.trades) > PREVIEW_TRADE_LIMIT,
        observed_start_at=min(
            (trade.entry_at for trade in result.trades), default=None
        ),
        observed_end_at=max((trade.exit_at for trade in result.trades), default=None),
        duplicate_run_id=duplicate_run_id,
        can_commit=(
            bool(result.trades)
            and not result.rejected_trades
            and duplicate_run_id is None
        ),
        version=_version_import_context(version),
    )


@router.get("/strategies", response_model=list[StrategyOut])
def get_strategies(session: Session = Depends(get_session)):
    return service.list_strategies(session)


@router.post(
    "/strategies",
    response_model=StrategyOut,
    status_code=status.HTTP_201_CREATED,
)
def post_strategy(body: StrategyCreate, session: Session = Depends(get_session)):
    try:
        return service.create_strategy(session, **body.model_dump())
    except service.StrategyLabError as exc:
        raise _http_error(exc) from exc


@router.get("/strategies/{strategy_id}", response_model=StrategyDetail)
def get_strategy_detail(strategy_id: uuid.UUID, session: Session = Depends(get_session)):
    try:
        strategy = service.get_strategy(session, strategy_id)
        locked_ids = service.locked_version_ids(session, strategy_id)
        versions = [
            _version_summary(v, locked=v.id in locked_ids)
            for v in service.list_versions(session, strategy_id)
        ]
        return StrategyDetail(
            **StrategyOut.model_validate(strategy).model_dump(),
            versions=versions,
        )
    except service.StrategyLabError as exc:
        raise _http_error(exc) from exc


@router.patch("/strategies/{strategy_id}", response_model=StrategyOut)
def patch_strategy(
    strategy_id: uuid.UUID,
    body: StrategyUpdate,
    session: Session = Depends(get_session),
):
    try:
        return service.update_strategy(
            session,
            strategy_id,
            body.model_dump(exclude_unset=True),
        )
    except service.StrategyLabError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/strategies/{strategy_id}/versions",
    response_model=VersionDetail,
    status_code=status.HTTP_201_CREATED,
)
def post_version(
    strategy_id: uuid.UUID,
    body: VersionCreate,
    session: Session = Depends(get_session),
):
    try:
        row = service.create_version(session, strategy_id, body.model_dump())
        return _version_detail(session, row)
    except service.StrategyLabError as exc:
        raise _http_error(exc) from exc


@router.get("/versions/{version_id}", response_model=VersionDetail)
def get_version_detail(version_id: uuid.UUID, session: Session = Depends(get_session)):
    try:
        return _version_detail(session, service.get_version(session, version_id))
    except service.StrategyLabError as exc:
        raise _http_error(exc) from exc


@router.patch("/versions/{version_id}", response_model=VersionDetail)
def patch_version(
    version_id: uuid.UUID,
    body: VersionUpdate,
    session: Session = Depends(get_session),
):
    try:
        row = service.update_version(
            session,
            version_id,
            body.model_dump(exclude_unset=True),
        )
        return _version_detail(session, row)
    except service.StrategyLabError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/versions/{version_id}/fork",
    response_model=VersionDetail,
    status_code=status.HTTP_201_CREATED,
)
def post_version_fork(
    version_id: uuid.UUID,
    body: VersionForkRequest,
    session: Session = Depends(get_session),
):
    try:
        row = service.fork_version(
            session,
            version_id,
            body.model_dump(exclude_unset=True),
        )
        return _version_detail(session, row)
    except service.StrategyLabError as exc:
        raise _http_error(exc) from exc


@router.post("/imports/preview", response_model=RunImportPreview)
async def post_run_import_preview(
    strategy_version_id: uuid.UUID = Form(...),
    source_timezone: str = Form(..., min_length=1, max_length=100),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    """Parse an export without persisting it and bind the preview to a version."""
    normalized_timezone = source_timezone.strip()
    _, result = await _parse_upload(file, normalized_timezone)
    try:
        version = service.get_version_for_import(session, strategy_version_id)
    except service.StrategyLabError as exc:
        raise _http_error(exc) from exc

    duplicate_run_id = service.find_duplicate_run_id(
        session,
        strategy_version_id,
        result.source_sha256,
    )
    return _preview_response(
        file_name=_safe_file_name(file.filename),
        version=version,
        result=result,
        source_timezone=normalized_timezone,
        duplicate_run_id=duplicate_run_id,
    )


@router.post(
    "/runs/import",
    response_model=RunImportOut,
    status_code=status.HTTP_201_CREATED,
)
async def post_run_import(
    metadata: str = Form(..., min_length=2, max_length=20_000),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    """Reparse the previewed bytes and atomically persist the run and trades."""
    try:
        body = RunImportRequest.model_validate_json(metadata)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(include_context=False),
        ) from exc

    data, result = await _parse_upload(file, body.source_timezone)
    try:
        run = service.create_run_from_csv(
            session,
            strategy_version_id=body.strategy_version_id,
            expected_version_fingerprint=body.expected_version_fingerprint,
            expected_source_sha256=body.expected_source_sha256,
            expected_preview_fingerprint=body.expected_preview_fingerprint,
            result=result,
            source_file_name=_safe_file_name(file.filename),
            source_csv_text=data.decode("utf-8-sig"),
            symbol=body.symbol.upper(),
            timeframe=body.timeframe,
            source_timezone=body.source_timezone,
            backtest_start=body.backtest_start,
            backtest_end=body.backtest_end,
            initial_capital=body.initial_capital,
            currency=body.currency,
            extended_hours=body.extended_hours,
            notes=body.notes,
        )
    except service.StrategyLabError as exc:
        raise _http_error(exc) from exc

    warning_count = len(result.warnings)
    return RunImportOut(
        run_id=run.id,
        strategy_version_id=run.strategy_version_id,
        version_fingerprint=run.version_fingerprint,
        source_sha256=run.source_sha256 or result.source_sha256,
        source_file_name=run.source_file_name,
        imported_trade_count=len(result.trades),
        imported_row_count=len(result.trades) * 2,
        skipped_row_count=max(0, result.row_count - (len(result.trades) * 2)),
        rejected_row_count=0,
        warning_count=warning_count,
    )


@router.get("/runs", response_model=StrategyRunPageOut)
def get_strategy_runs(
    strategy_id: uuid.UUID | None = Query(default=None),
    version_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
):
    rows, total = service.list_strategy_runs(
        session,
        strategy_id=strategy_id,
        version_id=version_id,
        limit=limit,
        offset=offset,
    )
    return StrategyRunPageOut(
        items=[_run_summary_out(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/runs/{run_id}", response_model=StrategyRunDetailOut)
def get_strategy_run_detail(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
):
    try:
        row = service.get_strategy_run(session, run_id)
        return _run_detail_out(
            row,
            source_warning_count=service.get_strategy_run_warning_count(
                session,
                run_id,
            ),
        )
    except service.StrategyLabError as exc:
        raise _http_error(exc) from exc


@router.get("/runs/{run_id}/trades", response_model=StrategyRunTradePageOut)
def get_strategy_run_trades(
    run_id: uuid.UUID,
    direction: Literal["long", "short"] | None = Query(default=None),
    outcome: Literal["winner", "loser", "breakeven", "unknown"] | None = Query(
        default=None
    ),
    entry_date_from: date | None = Query(default=None),
    entry_date_to: date | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
):
    try:
        rows, total = service.list_strategy_run_trades(
            session,
            run_id,
            direction=direction,
            outcome=outcome,
            entry_date_from=entry_date_from,
            entry_date_to=entry_date_to,
            limit=limit,
            offset=offset,
        )
        return StrategyRunTradePageOut(
            items=[StrategyRunTradeOut.model_validate(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )
    except service.StrategyLabError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/runs/{run_id}/metrics",
    response_model=StrategyRunMetricsOut,
)
def get_run_metrics(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
):
    try:
        return _run_metrics_out(service.get_run_metrics(session, run_id))
    except service.StrategyLabError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/runs/{run_id}/metrics/recalculate",
    response_model=StrategyRunMetricsOut,
)
def post_run_metrics_recalculate(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
):
    try:
        return _run_metrics_out(service.recalculate_run_metrics(session, run_id))
    except service.StrategyLabError as exc:
        raise _http_error(exc) from exc
