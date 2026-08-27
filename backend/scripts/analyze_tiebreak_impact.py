"""Read-only analysis of FIFO same-timestamp tie-break candidates.

Usage:
    python scripts/analyze_tiebreak_impact.py                       # configured DATABASE_URL
    python scripts/analyze_tiebreak_impact.py --database-url URL
    python scripts/analyze_tiebreak_impact.py --json

The production reconstructor always applies its current fill-id tie-break.
Candidate runs therefore use in-memory FillInput copies with monotonic surrogate
UUIDs whose lexical order encodes the candidate. No Fill, Trade, or TradeFill
row is changed.
"""

from __future__ import annotations

import argparse
import itertools
import json
import string
import sys
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.engine.reconstructor import (  # noqa: E402
    FillInput,
    _CLOSE_SIDES,
    _OPEN_SIDES,
    _sort_dt,
    reconstruct,
)

CANDIDATES = ("id", "raw_email_id", "price_ascending", "price_descending")
CANDIDATE_LABELS = {
    "id": "id (current baseline)",
    "raw_email_id": "raw_email_id",
    "price_ascending": "price ascending (non-FIFO bound)",
    "price_descending": "price descending (non-FIFO bound)",
}


@dataclass(frozen=True)
class SourceFill:
    id: uuid.UUID
    account_id: uuid.UUID
    ticker: str
    instrument_type: str
    side: str
    contracts: Decimal
    price: Decimal
    executed_at: datetime
    raw_email_id: str
    option_type: str | None = None
    strike: Decimal | None = None
    expiration: date | None = None

    def to_fill_input(self, *, fill_id: uuid.UUID | None = None) -> FillInput:
        return FillInput(
            id=fill_id or self.id,
            account_id=self.account_id,
            ticker=self.ticker,
            instrument_type=self.instrument_type,
            side=self.side,
            contracts=self.contracts,
            price=self.price,
            executed_at=self.executed_at,
            option_type=self.option_type,
            strike=self.strike,
            expiration=self.expiration,
        )


@dataclass(frozen=True)
class _CandidateTrade:
    id: uuid.UUID
    account_id: uuid.UUID
    ticker: str
    instrument_type: str
    option_type: str | None
    strike: Decimal | None
    expiration: date | None
    status: str
    realized_pnl: Decimal | None
    fill_ids: frozenset[uuid.UUID]

    @property
    def contract_key(self) -> tuple[object, ...]:
        return (
            self.account_id,
            self.ticker,
            self.instrument_type,
            self.option_type,
            self.strike,
            self.expiration,
        )


def _fill_class(fill: SourceFill) -> str:
    if fill.side in _OPEN_SIDES:
        return "open"
    if fill.side in _CLOSE_SIDES:
        return "close"
    return f"unsupported:{fill.side}"


def _contract_key(fill: SourceFill) -> tuple[object, ...]:
    return (
        fill.account_id,
        fill.ticker,
        fill.instrument_type,
        fill.option_type if fill.instrument_type == "option" else None,
        fill.strike if fill.instrument_type == "option" else None,
        fill.expiration if fill.instrument_type == "option" else None,
    )


def _tie_groups(fills: Iterable[SourceFill]) -> list[list[SourceFill]]:
    grouped: dict[tuple[object, ...], list[SourceFill]] = defaultdict(list)
    for fill in fills:
        key = (*_contract_key(fill), _sort_dt(fill.executed_at), _fill_class(fill))
        grouped[key].append(fill)
    return [group for group in grouped.values() if len(group) > 1]


def _candidate_value(fill: SourceFill, candidate: str) -> object:
    if candidate == "id":
        return str(fill.id)
    if candidate == "raw_email_id":
        return fill.raw_email_id
    if candidate == "price_ascending":
        return fill.price
    if candidate == "price_descending":
        return -fill.price
    raise ValueError(f"Unsupported candidate: {candidate}")


def _candidate_sort_key(fill: SourceFill, candidate: str) -> tuple[object, ...]:
    return (
        _sort_dt(fill.executed_at),
        0 if fill.side in _OPEN_SIDES else 1,
        _candidate_value(fill, candidate),
        str(fill.id),
    )


def _run_candidate(
    fills: list[SourceFill],
    candidate: str,
    *,
    today: date,
) -> tuple[list[_CandidateTrade], list[str]]:
    if candidate == "id":
        inputs = [fill.to_fill_input() for fill in fills]
        original_by_run_id = {fill.id: fill.id for fill in fills}
    else:
        ordered = sorted(fills, key=lambda fill: _candidate_sort_key(fill, candidate))
        run_id_by_original = {
            fill.id: uuid.UUID(int=index)
            for index, fill in enumerate(ordered, start=1)
        }
        original_by_run_id = {
            run_id: original_id for original_id, run_id in run_id_by_original.items()
        }
        inputs = [
            fill.to_fill_input(fill_id=run_id_by_original[fill.id])
            for fill in ordered
        ]

    result = reconstruct(inputs, today=today)
    fills_by_trade: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for link in result.trade_fills:
        fills_by_trade[link.trade_id].add(original_by_run_id[link.fill_id])

    trades = [
        _CandidateTrade(
            id=original_by_run_id[trade.id],
            account_id=trade.account_id,
            ticker=trade.ticker,
            instrument_type=trade.instrument_type,
            option_type=trade.option_type,
            strike=trade.strike,
            expiration=trade.expiration,
            status=trade.status,
            realized_pnl=trade.realized_pnl,
            fill_ids=frozenset(fills_by_trade[trade.id]),
        )
        for trade in result.trades
    ]
    return trades, result.anomalies


def _realized_total(trades: Iterable[_CandidateTrade]) -> Decimal:
    return sum(
        (trade.realized_pnl for trade in trades if trade.realized_pnl is not None),
        start=Decimal("0"),
    )


def _closed_realized_total(trades: Iterable[_CandidateTrade]) -> Decimal:
    return sum(
        (
            trade.realized_pnl
            for trade in trades
            if trade.status in {"closed", "expired"} and trade.realized_pnl is not None
        ),
        start=Decimal("0"),
    )


def _match_trade(
    baseline: _CandidateTrade,
    candidates: list[_CandidateTrade],
) -> tuple[_CandidateTrade | None, str]:
    same_contract = [trade for trade in candidates if trade.contract_key == baseline.contract_key]
    exact = [trade for trade in same_contract if trade.fill_ids == baseline.fill_ids]
    if len(exact) == 1:
        return exact[0], "exact_fill_set"

    overlapping = sorted(
        (
            (len(trade.fill_ids & baseline.fill_ids), trade)
            for trade in same_contract
            if trade.fill_ids & baseline.fill_ids
        ),
        key=lambda item: (item[0], str(item[1].id)),
        reverse=True,
    )
    if overlapping:
        return overlapping[0][1], "largest_fill_overlap"
    return None, "unmatched"


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _trade_delta(
    baseline: _CandidateTrade,
    candidate: _CandidateTrade | None,
    match: str,
    account_labels: dict[uuid.UUID, str],
) -> dict[str, object]:
    baseline_value = baseline.realized_pnl or Decimal("0")
    candidate_value = (
        candidate.realized_pnl
        if candidate is not None and candidate.realized_pnl is not None
        else Decimal("0")
    )
    return {
        "trade_id": str(baseline.id),
        "candidate_trade_id": str(candidate.id) if candidate else None,
        "ticker": baseline.ticker,
        "account_id": str(baseline.account_id),
        "account": account_labels.get(baseline.account_id, str(baseline.account_id)),
        "status": baseline.status,
        "baseline_realized_pnl": (
            _decimal_text(baseline.realized_pnl) if baseline.realized_pnl is not None else None
        ),
        "candidate_realized_pnl": (
            _decimal_text(candidate.realized_pnl)
            if candidate is not None and candidate.realized_pnl is not None
            else None
        ),
        "delta": _decimal_text(candidate_value - baseline_value),
        "match": match,
    }


def _gmail_id_value(raw_email_id: str) -> int | None:
    value = raw_email_id.strip().lower()
    if not value or ":" in value or any(char not in string.hexdigits for char in value):
        return None
    try:
        return int(value, 16)
    except ValueError:
        return None


def _raw_email_chronology(fills: list[SourceFill]) -> dict[str, object]:
    gmail = [
        (_gmail_id_value(fill.raw_email_id), _sort_dt(fill.executed_at))
        for fill in fills
    ]
    observations = sorted(
        ((raw_id, executed_at) for raw_id, executed_at in gmail if raw_id is not None),
        key=lambda item: item[0],
    )
    if len(observations) < 2:
        return {
            "gmail_fill_count": len(observations),
            "comparable_pairs": 0,
            "concordant_pairs": 0,
            "discordant_pairs": 0,
            "concordance_pct": None,
            "assessment": "Insufficient Gmail ids to assess chronological ordering.",
        }

    times = sorted({executed_at for _, executed_at in observations})
    rank_by_time = {executed_at: index + 1 for index, executed_at in enumerate(times)}
    tree = [0] * (len(times) + 1)

    def prefix_count(index: int) -> int:
        total = 0
        while index:
            total += tree[index]
            index -= index & -index
        return total

    def add(index: int) -> None:
        while index < len(tree):
            tree[index] += 1
            index += index & -index

    concordant = 0
    discordant = 0
    seen = 0
    for _, same_raw_group in itertools.groupby(observations, key=lambda item: item[0]):
        group = list(same_raw_group)
        for _, executed_at in group:
            rank = rank_by_time[executed_at]
            less = prefix_count(rank - 1)
            through_equal = prefix_count(rank)
            concordant += less
            discordant += seen - through_equal
        for _, executed_at in group:
            add(rank_by_time[executed_at])
            seen += 1

    comparable = concordant + discordant
    if not comparable:
        assessment = "Gmail ids exist, but their execution timestamps provide no comparable order."
        percentage = None
    else:
        percentage = Decimal(concordant * 100) / Decimal(comparable)
        if percentage >= Decimal("99"):
            assessment = "The data supports raw_email_id as a chronological proxy."
        elif percentage >= Decimal("95"):
            assessment = "raw_email_id is mostly chronological, with some inversions."
        else:
            assessment = "The data does not support raw_email_id as a reliable chronological proxy."

    return {
        "gmail_fill_count": len(observations),
        "comparable_pairs": comparable,
        "concordant_pairs": concordant,
        "discordant_pairs": discordant,
        "concordance_pct": (
            format(percentage.quantize(Decimal("0.01")), "f") if percentage is not None else None
        ),
        "assessment": assessment,
    }


def analyze_fills(
    fills: list[SourceFill],
    *,
    account_labels: dict[uuid.UUID, str] | None = None,
    today: date | None = None,
) -> dict[str, object]:
    account_labels = account_labels or {}
    analysis_day = today or date.today()
    tie_groups = _tie_groups(fills)
    baseline_trades, baseline_anomalies = _run_candidate(fills, "id", today=analysis_day)

    group_fill_ids = [{fill.id for fill in group} for group in tie_groups]
    affected = [
        trade
        for trade in baseline_trades
        if any(len(trade.fill_ids & fill_ids) >= 2 for fill_ids in group_fill_ids)
    ]
    tie_group_rows = []
    for group in tie_groups:
        first = group[0]
        containing_trade = next(
            (
                trade
                for trade in baseline_trades
                if len(trade.fill_ids & {fill.id for fill in group}) >= 2
            ),
            None,
        )
        tie_group_rows.append({
            "trade_id": str(containing_trade.id) if containing_trade else None,
            "ticker": first.ticker,
            "account_id": str(first.account_id),
            "account": account_labels.get(first.account_id, str(first.account_id)),
            "executed_at": _sort_dt(first.executed_at).isoformat(),
            "fill_class": _fill_class(first),
            "fill_count": len(group),
            "fill_ids": [str(fill.id) for fill in sorted(group, key=lambda fill: str(fill.id))],
        })

    total_trades = len(baseline_trades)
    affected_count = len(affected)
    affected_share = (
        Decimal(affected_count * 100) / Decimal(total_trades)
        if total_trades
        else Decimal("0")
    )

    ticker_counts = Counter(trade.ticker for trade in affected)
    ticker_closed = Counter(
        trade.ticker for trade in affected if trade.status in {"closed", "expired"}
    )
    account_counts = Counter(trade.account_id for trade in affected)
    account_closed = Counter(
        trade.account_id for trade in affected if trade.status in {"closed", "expired"}
    )

    report: dict[str, object] = {
        "fill_count": len(fills),
        "total_trades": total_trades,
        "tie_group_count": len(tie_groups),
        "affected_trade_count": affected_count,
        "affected_trade_share_pct": format(affected_share.quantize(Decimal("0.01")), "f"),
        "affected_closed_trade_count": sum(
            trade.status in {"closed", "expired"} for trade in affected
        ),
        "affected_realized_pnl_trade_count": sum(
            trade.realized_pnl is not None for trade in affected
        ),
        "tickers": [
            {
                "ticker": ticker,
                "affected_trades": ticker_counts[ticker],
                "closed_or_expired": ticker_closed[ticker],
            }
            for ticker in sorted(ticker_counts)
        ],
        "accounts": [
            {
                "account_id": str(account_id),
                "account": account_labels.get(account_id, str(account_id)),
                "affected_trades": account_counts[account_id],
                "closed_or_expired": account_closed[account_id],
            }
            for account_id in sorted(account_counts, key=str)
        ],
        "tie_groups": tie_group_rows,
        "baseline_anomalies": baseline_anomalies,
        "raw_email_id_chronology": _raw_email_chronology(fills),
        "candidates": {},
    }

    if not affected:
        report["verdict"] = (
            "No trade contains a same-timestamp, same-class fill group; "
            "the current tie-break can stay."
        )
        return report

    baseline_total = _realized_total(baseline_trades)
    baseline_closed_total = _closed_realized_total(baseline_trades)
    candidate_reports: dict[str, object] = {}
    any_delta = False
    for candidate_name in CANDIDATES:
        if candidate_name == "id":
            candidate_trades = baseline_trades
            anomalies = baseline_anomalies
        else:
            candidate_trades, anomalies = _run_candidate(
                fills,
                candidate_name,
                today=analysis_day,
            )

        total = _realized_total(candidate_trades)
        delta = total - baseline_total
        closed_total = _closed_realized_total(candidate_trades)
        any_delta = any_delta or delta != 0
        per_trade = []
        for baseline_trade in affected:
            matched, match_kind = _match_trade(baseline_trade, candidate_trades)
            per_trade.append(
                _trade_delta(baseline_trade, matched, match_kind, account_labels)
            )

        candidate_reports[candidate_name] = {
            "label": CANDIDATE_LABELS[candidate_name],
            "realized_pnl_total": _decimal_text(total),
            "closed_realized_pnl_total": _decimal_text(closed_total),
            "closed_delta_vs_id": _decimal_text(closed_total - baseline_closed_total),
            "delta_vs_id": _decimal_text(delta),
            "trade_count": len(candidate_trades),
            "anomalies": anomalies,
            "affected_trades": per_trade,
        }

    report["candidates"] = candidate_reports
    if any_delta:
        report["verdict"] = (
            "At least one tested tie-break changes realized P&L; choosing a replacement "
            "requires an owner decision."
        )
    else:
        report["verdict"] = (
            f"{affected_count} trade(s) contain a tie group, but none of the tested "
            "orderings changes realized P&L for this dataset; the current tie-break can stay."
        )
    return report


def analyze_database(database_url: str) -> dict[str, object]:
    """Load source rows with SELECTs only and analyze them in memory."""
    from sqlmodel import Session, create_engine, select

    from app.models import Account, FILL_LIGHT, Fill

    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    try:
        with Session(engine) as session:
            rows = session.exec(select(Fill).options(*FILL_LIGHT)).all()
            accounts = {
                account.id: f"{account.name} (...{account.last4})"
                for account in session.exec(select(Account)).all()
            }
            fills = [
                SourceFill(
                    id=row.id,
                    account_id=row.account_id,
                    ticker=row.ticker,
                    instrument_type=row.instrument_type,
                    side=row.side,
                    contracts=Decimal(str(row.contracts)),
                    price=Decimal(str(row.price)),
                    executed_at=row.executed_at,
                    raw_email_id=row.raw_email_id,
                    option_type=row.option_type,
                    strike=Decimal(str(row.strike)) if row.strike is not None else None,
                    expiration=row.expiration,
                )
                for row in rows
            ]
    finally:
        engine.dispose()
    return analyze_fills(fills, account_labels=accounts)


def _money(value: str) -> str:
    return f"${Decimal(value):+,.2f}"


def format_human(report: dict[str, object]) -> str:
    lines = [
        "FIFO tie-break impact analysis",
        f"Fills analyzed: {report['fill_count']}",
        f"Trades reconstructed: {report['total_trades']}",
        f"Same-timestamp, same-class groups: {report['tie_group_count']}",
        (
            "Potentially affected trades: "
            f"{report['affected_trade_count']} / {report['total_trades']} "
            f"({report['affected_trade_share_pct']}%)"
        ),
        f"Closed/expired affected trades: {report['affected_closed_trade_count']}",
        f"Affected trades with realized P&L: {report['affected_realized_pnl_trade_count']}",
    ]

    tickers = report["tickers"]
    if tickers:
        lines.append("\nAffected tickers:")
        lines.extend(
            f"  {row['ticker']}: {row['affected_trades']} trade(s), "
            f"{row['closed_or_expired']} closed/expired"
            for row in tickers
        )

    accounts = report["accounts"]
    if accounts:
        lines.append("\nAffected accounts:")
        lines.extend(
            f"  {row['account']}: {row['affected_trades']} trade(s), "
            f"{row['closed_or_expired']} closed/expired"
            for row in accounts
        )

    chronology = report["raw_email_id_chronology"]
    lines.append("\nraw_email_id chronology:")
    lines.append(f"  {chronology['assessment']}")
    if chronology["concordance_pct"] is not None:
        lines.append(
            f"  {chronology['concordance_pct']}% concordant across "
            f"{chronology['comparable_pairs']} comparable pair(s); "
            f"{chronology['discordant_pairs']} inversion(s)."
        )

    candidates = report["candidates"]
    if candidates:
        lines.append("\nCandidate realized P&L (all trades with realized P&L):")
        for name in CANDIDATES:
            candidate = candidates[name]
            lines.append(
                f"  {candidate['label']}: {_money(candidate['realized_pnl_total'])}; "
                f"delta vs id {_money(candidate['delta_vs_id'])}; "
                f"closed/expired delta {_money(candidate['closed_delta_vs_id'])}"
            )
            for trade in candidate["affected_trades"]:
                lines.append(
                    f"    {trade['ticker']} {trade['account']} [{trade['trade_id']}]: "
                    f"{_money(trade['delta'])}"
                )

    lines.append(f"\nVerdict: {report['verdict']}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        help="SQLAlchemy database URL; defaults to the configured DATABASE_URL",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args()

    database_url = args.database_url
    if not database_url:
        # DATABASE_URL lives in backend/.env, which python-dotenv reads and the
        # shell does not -- so "$DATABASE_URL" is usually empty and passing it
        # produced an unparseable-URL error rather than anything actionable.
        from app.environment import resolve_database_url

        database_url = resolve_database_url()
    report = analyze_database(database_url)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_human(report))


if __name__ == "__main__":
    main()
