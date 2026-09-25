"""Reports, TradingView-shaped CSVs and export parity for the Market Map port.

Pure companion to `app.engine.market_map`: everything here works on trades
and text it is handed. R is the primary unit and follows
`backend/scripts/imm_export_cohorts.py`: net PnL over the risk budget for the
trade's size (the risk input for full size, half of it for half size), so the
Python numbers and the Strategy Tester numbers are on the same scale.
"""

from __future__ import annotations

import csv
import io
import math
import statistics
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from app.engine.market_map import ET, MarketMapConfig, Signal, Trade

GROUP_KEYS: dict[str, Callable[[Trade], str]] = {
    "ticker": lambda t: t.ticker,
    "setup": lambda t: t.setup,
    "side": lambda t: t.side_text,
    "grade": lambda t: t.grade,
    "window": lambda t: t.window,
    "exit_reason": lambda t: t.exit_reason or "open",
    "tier": lambda t: t.tier,
}

TV_HEADER = [
    "Trade number",
    "Type",
    "Date and time",
    "Signal",
    "Price USD",
    "Size (qty)",
    "Size (value)",
    "Net PnL USD",
    "Return %",
    "Commission USD",
    "Favorable excursion USD",
    "Favorable excursion %",
    "Adverse excursion USD",
    "Adverse excursion %",
    "Cumulative PnL USD",
    "Cumulative PnL %",
    "Duration (bars)",
]


# --- sl1 comments -------------------------------------------------------------


def pine_number(value: float | None) -> str:
    """`f_num`: `str.tostring(value, "#.######")`, with `na` as null."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "null"
    text = format(Decimal(repr(float(value))).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP), "f")
    text = text.rstrip("0").rstrip(".") if "." in text else text
    return "0" if text in ("-0", "") else text


def entry_comment(trade: Trade) -> str:
    """`f_entryComment`, key for key."""
    fields = [
        ("setup", trade.setup),
        ("side", trade.side_text),
        ("grade", trade.grade),
        ("size", trade.size),
        ("score", pine_number(trade.score)),
        ("window", trade.window),
        ("tier", trade.tier),
        ("rvol", pine_number(trade.rvol)),
        ("rs_vs_spy", pine_number(trade.rs_vs_spy)),
        ("gap_atr", pine_number(trade.gap_atr)),
        ("ext_atr", pine_number(trade.ext_atr)),
        ("risk_atr", pine_number(trade.risk_atr)),
    ]
    return "sl1" + "".join(f"|{key}={value}" for key, value in fields)


def exit_comment(trade: Trade) -> str:
    """`f_exitComment`."""
    return f"sl1|exit_reason={trade.exit_reason}|mfe_r={pine_number(trade.exit_mfe_r)}"


def sl1_fields(text: str) -> dict[str, str]:
    if not text.startswith("sl1|"):
        return {}
    return dict(token.split("=", 1) for token in text.split("|")[1:] if "=" in token)


# --- TradingView-shaped export --------------------------------------------------


def _stamp(moment: datetime) -> str:
    return moment.astimezone(ET).strftime("%Y-%m-%d %H:%M")


def _money(value: float) -> str:
    return f"{value:.2f}"


def tradingview_csv(trades: Iterable[Trade], config: MarketMapConfig) -> str:
    """Closed trades as a Strategy Tester "List of trades" export, exit row first."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(TV_HEADER)
    cumulative = 0.0
    closed = sorted((t for t in trades if t.closed), key=lambda t: t.entry_bar)
    for number, trade in enumerate(closed, start=1):
        assert trade.exit_time is not None and trade.exit_price is not None
        pnl = trade.pnl
        cumulative += pnl
        value = trade.entry_price * trade.quantity
        common = [
            trade.quantity,
            _money(value),
            _money(pnl),
            _money(100 * pnl / value),
            "0",
            _money(trade.run_up),
            _money(100 * trade.run_up / value),
            _money(trade.drawdown),
            _money(100 * trade.drawdown / value),
            _money(cumulative),
            _money(100 * cumulative / config.initial_capital),
            trade.bars_held,
        ]
        side = "long" if trade.side == 1 else "short"
        writer.writerow(
            [number, f"Exit {side}", _stamp(trade.exit_time), exit_comment(trade), f"{trade.exit_price:.2f}", *common]
        )
        writer.writerow(
            [number, f"Entry {side}", _stamp(trade.entry_time), entry_comment(trade), f"{trade.entry_price:.2f}", *common]
        )
    return out.getvalue()


# --- cohort report --------------------------------------------------------------


@dataclass(frozen=True)
class GroupStats:
    n: int
    total_r: float
    avg_r: float
    win_pct: float
    profit_factor: float
    max_drawdown_r: float
    pnl: float


def group_stats(trades: list[Trade]) -> GroupStats:
    """Stats for trades in time order. Max drawdown is peak-to-trough of cumulative R."""
    ordered = sorted(trades, key=lambda t: t.entry_time)
    rs = [t.r for t in ordered]
    wins = [r for r in rs if r > 0]
    losses = -sum(r for r in rs if r <= 0)
    peak = cumulative = drawdown = 0.0
    for r in rs:
        cumulative += r
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    return GroupStats(
        n=len(rs),
        total_r=sum(rs),
        avg_r=sum(rs) / len(rs) if rs else 0.0,
        win_pct=100 * len(wins) / len(rs) if rs else 0.0,
        profit_factor=sum(wins) / losses if losses else math.inf,
        max_drawdown_r=drawdown,
        pnl=sum(t.pnl for t in ordered),
    )


def _stats_line(label: str, stats: GroupStats) -> str:
    pf = "inf" if math.isinf(stats.profit_factor) else f"{stats.profit_factor:5.2f}"
    return (
        f"  {label:22s} n={stats.n:4d}  R={stats.total_r:7.1f}  avgR={stats.avg_r:6.3f}  "
        f"win%={stats.win_pct:5.1f}  pf={pf:>5s}  maxDD={stats.max_drawdown_r:5.1f}R  ${stats.pnl:9.2f}"
    )


def cohort_report(trades: Iterable[Trade], keys: Iterable[str] = GROUP_KEYS) -> str:
    closed = [t for t in trades if t.closed]
    if not closed:
        return "No closed trades."
    lines = [_stats_line("ALL", group_stats(closed))]
    for key in keys:
        groups: dict[str, list[Trade]] = defaultdict(list)
        for trade in closed:
            groups[GROUP_KEYS[key](trade)].append(trade)
        lines.append(f"\n== {key}")
        ranked = sorted(groups.items(), key=lambda item: -sum(t.r for t in item[1]))
        lines += [_stats_line(label, group_stats(members)) for label, members in ranked]
    return "\n".join(lines)


# --- parity against a Strategy Tester export ------------------------------------


@dataclass(frozen=True)
class ExportedTrade:
    entry_stamp: str
    exit_stamp: str
    side: str
    setup: str
    fields: dict[str, str]


def load_tradingview_export(text: str) -> list[ExportedTrade]:
    """Pair entry and exit rows of a "List of trades" export. Open trades are skipped."""
    groups: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        kind = "entry" if row["Type"].startswith("Entry") else "exit"
        groups[row["Trade number"]][kind] = row
    trades = []
    for pair in groups.values():
        if "entry" not in pair or "exit" not in pair:
            continue
        entry, exit_row = pair["entry"], pair["exit"]
        fields = {**sl1_fields(exit_row["Signal"]), **sl1_fields(entry["Signal"])}
        side = "long" if entry["Type"].lower().endswith("long") else "short"
        trades.append(
            ExportedTrade(entry["Date and time"], exit_row["Date and time"], side, fields.get("setup", ""), fields)
        )
    return sorted(trades, key=lambda t: t.entry_stamp)


@dataclass(frozen=True)
class Mismatch:
    stamp: str
    side: str
    setup: str
    source: str  # "tradingview" (only TradingView entered) or "python"
    cause: str
    detail: str


@dataclass
class ParityReport:
    tradingview_entries: int = 0
    python_entries: int = 0
    matched: int = 0
    mismatches: list[Mismatch] = field(default_factory=list)
    agreement: dict[str, float] = field(default_factory=dict)
    median_abs_diff: dict[str, float] = field(default_factory=dict)

    @property
    def match_rate(self) -> float:
        """Share of TradingView entries the port reproduces on timestamp, side and setup."""
        return self.matched / self.tradingview_entries if self.tradingview_entries else 0.0

    @property
    def precision(self) -> float:
        return self.matched / self.python_entries if self.python_entries else 0.0

    def causes(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for mismatch in self.mismatches:
            counts[f"{mismatch.source}: {mismatch.cause}"] += 1
        return dict(sorted(counts.items(), key=lambda item: -item[1]))


_SEQUENCE_OUTCOMES = {"in_trade", "cooldown", "max_entries", "max_losses"}
_COMPARED_FIELDS = ("rvol", "rs_vs_spy", "gap_atr", "risk_atr")


def _number(text: str | None) -> float:
    try:
        return float(text) if text not in (None, "", "null") else math.nan
    except ValueError:
        return math.nan


def _fmt(value: float) -> str:
    return "n/a" if math.isnan(value) else f"{value:.3f}"


def compare_to_export(
    trades: list[Trade], signals: list[Signal], exported: list[ExportedTrade]
) -> ParityReport:
    """Match the port's entries to an export on (timestamp, side, setup) and explain the rest.

    Only the days both sides cover are compared. A mismatch is attributed to
    the first cause the evidence supports: a knock-on from an earlier
    difference (one side was in a trade, cooling down or at a daily limit), a
    grade that came out differently (RVOL and relative strength depend on the
    data feed), a different setup on the same bar, or no signal at all (the
    levels, VWAP or EMAs saw different prices).
    """
    closed = [t for t in trades if t.closed]
    python_days = {_stamp(t.entry_time)[:10] for t in closed} | {_stamp(s.time)[:10] for s in signals}
    if not python_days or not exported:
        return ParityReport()
    first = max(min(python_days), exported[0].entry_stamp[:10])
    last = min(max(python_days), exported[-1].entry_stamp[:10])

    def in_range(stamp: str) -> bool:
        return first <= stamp[:10] <= last

    tv = [t for t in exported if in_range(t.entry_stamp)]
    py = [t for t in closed if in_range(_stamp(t.entry_time))]
    py_by_key = {(_stamp(t.entry_time), t.side_text, t.setup): t for t in py}
    tv_by_key = {(t.entry_stamp, t.side, t.setup): t for t in tv}
    signals_at: dict[str, list[Signal]] = defaultdict(list)
    for signal in signals:
        signals_at[_stamp(signal.time)].append(signal)

    report = ParityReport(tradingview_entries=len(tv), python_entries=len(py))
    pairs: list[tuple[ExportedTrade, Trade]] = []
    for key, exported_trade in tv_by_key.items():
        match = py_by_key.get(key)
        if match is not None:
            pairs.append((exported_trade, match))
            continue
        stamp, side, setup = key
        report.mismatches.append(
            Mismatch(stamp, side, setup, "tradingview", *_explain_tv_only(exported_trade, signals_at.get(stamp, [])))
        )
    for key, trade in py_by_key.items():
        if key in tv_by_key:
            continue
        stamp, side, setup = key
        cause, detail = _explain_python_only(trade, tv)
        report.mismatches.append(Mismatch(stamp, side, setup, "python", cause, detail))
    report.matched = len(pairs)
    report.mismatches.sort(key=lambda m: (m.stamp, m.source))

    if pairs:
        report.agreement = {
            "grade": _share(e.fields.get("grade") == t.grade for e, t in pairs),
            "size": _share(e.fields.get("size") == t.size for e, t in pairs),
            "exit_reason": _share(e.fields.get("exit_reason") == t.exit_reason for e, t in pairs),
            "exit_time": _share(e.exit_stamp == _stamp(t.exit_time) for e, t in pairs if t.exit_time),
        }
        for name in _COMPARED_FIELDS:
            diffs = [
                abs(_number(e.fields.get(name)) - getattr(t, name))
                for e, t in pairs
                if not math.isnan(_number(e.fields.get(name))) and not math.isnan(getattr(t, name))
            ]
            if diffs:
                report.median_abs_diff[name] = statistics.median(diffs)
    return report


def _share(flags: Iterable[bool]) -> float:
    values = list(flags)
    return sum(values) / len(values) if values else 0.0


def _explain_tv_only(exported: ExportedTrade, at_bar: list[Signal]) -> tuple[str, str]:
    same_side = [s for s in at_bar if (s.side == 1) == (exported.side == "long")]
    exact = next((s for s in same_side if s.setup == exported.setup), None)
    tv_rvol = _number(exported.fields.get("rvol"))
    tv_rs = _number(exported.fields.get("rs_vs_spy"))
    if exact is not None:
        values = (
            f"python rvol={_fmt(exact.rvol)} rs={_fmt(exact.rs_vs_spy)}; "
            f"tradingview rvol={_fmt(tv_rvol)} rs={_fmt(tv_rs)}"
        )
        if exact.outcome in _SEQUENCE_OUTCOMES:
            return "knock-on", f"python saw the signal but was blocked by {exact.outcome}"
        if exact.outcome in ("grade_c", "window"):
            grade = exact.grade or "C"
            return "grade (feed)", f"python graded {grade}, tradingview {exported.fields.get('grade')}; {values}"
        if exact.outcome == "both_sides":
            return "opposite side fired", "python also had a signal on the other side and skipped the bar"
        return "other", f"python signal outcome {exact.outcome}"
    if same_side:
        other = ", ".join(sorted({s.setup for s in same_side}))
        return "different setup", f"python fired {other} on this bar"
    return "no signal (prices)", "python had no setup on this bar: levels, VWAP or EMAs differ"


def _explain_python_only(trade: Trade, exported: list[ExportedTrade]) -> tuple[str, str]:
    stamp = _stamp(trade.entry_time)
    holding = next((e for e in exported if e.entry_stamp < stamp <= e.exit_stamp), None)
    if holding is not None:
        return "knock-on", f"tradingview was in a trade from {holding.entry_stamp} to {holding.exit_stamp}"
    same_bar = [e for e in exported if e.entry_stamp == stamp]
    if same_bar:
        other = ", ".join(f"{e.setup} {e.side}" for e in same_bar)
        return "different setup", f"tradingview entered {other} on this bar"
    detail = f"rvol={_fmt(trade.rvol)} rs={_fmt(trade.rs_vs_spy)} grade={trade.grade}"
    return "no tradingview entry", f"tradingview did not enter here (cooldown, limit or no signal); {detail}"


def parity_text(ticker: str, report: ParityReport, limit: int | None = None) -> str:
    lines = [
        f"{ticker}: {report.matched}/{report.tradingview_entries} TradingView entries matched "
        f"({100 * report.match_rate:.1f}%), {report.python_entries} Python entries "
        f"({100 * report.precision:.1f}% of them matched)",
    ]
    if report.agreement:
        lines.append(
            "  matched trades agree on: "
            + ", ".join(f"{name} {100 * share:.0f}%" for name, share in report.agreement.items())
        )
    if report.median_abs_diff:
        lines.append(
            "  median |difference| on matched entries: "
            + ", ".join(f"{name} {value:.3f}" for name, value in report.median_abs_diff.items())
        )
    for cause, count in report.causes().items():
        lines.append(f"  {count:4d}  {cause}")
    shown = report.mismatches if limit is None else report.mismatches[:limit]
    for m in shown:
        lines.append(f"    {m.stamp} {m.side:5s} {m.setup:13s} only in {m.source:11s} {m.cause}: {m.detail}")
    if limit is not None and len(report.mismatches) > limit:
        lines.append(f"    ... {len(report.mismatches) - limit} more")
    return "\n".join(lines)
