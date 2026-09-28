"""The strategy factory's judge: periods, statistics, the gates and the ledger.

Searching many ideas finds some that look good by luck, so the factory's
main job is to throw those out automatically. A candidate is judged in three
stages, and each stage sees data the one before it did not:

1. **Screen**, on the discovery period only (Jul 2023 - Sep 2024). At least
   100 trades, a positive average R after costs, and entries that beat
   random entries (every bar, the same exits and stop rule) with t >= 2.
   Most ideas stop here, and the later data is never loaded for them.
2. **Confirm**, on Oct 2024 - Mar 2026 in two halves the idea has not seen.
   Positive and better than random in each half; t against random in both
   halves together above a bar that rises with every candidate that has
   ever reached this stage (Bonferroni at 5%, one-sided); still positive
   with costs tripled; money made on at least half the tickers; and not
   carried by one ticker. A candidate with a learned filter must also beat
   the same rules without it, in each half.
3. **Exam**, on the locked holdout (April 2026 onward), once, only for a
   candidate that passed both: positive and better than random.

t is clustered by week, because trades in the same week share the market's
moves. Every result goes to the ledger, and the ledger's count sets the bar.

Pure: no network, no database. The caller supplies a bar loader.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from statistics import NormalDist, median

from app.engine.factory_data import ET, FeatureContext, Series, Split
from app.engine.factory_model import LogisticModel, fit_logistic
from app.engine.factory_rules import (
    MARKET,
    MATCHED,
    AtrStop,
    Signal,
    Spec,
    SwingStop,
    Trade,
    baseline_signals,
    canonical,
    family_sides,
    run_candidate,
    run_each,
    spec_id,
)

NA = math.nan

PERIODS: dict[str, tuple[date, date]] = {
    "discovery": (date(2023, 7, 3), date(2024, 9, 30)),
    "confirm_a": (date(2024, 10, 1), date(2025, 6, 30)),
    "confirm_b": (date(2025, 7, 1), date(2026, 3, 31)),
}
HOLDOUT_START = date(2026, 4, 1)
LABELS = {
    "discovery": "discovery  Jul 2023 - Sep 2024",
    "confirm_a": "confirm A  Oct 2024 - Jun 2025",
    "confirm_b": "confirm B  Jul 2025 - Mar 2026",
    "confirm": "confirm, both halves",
    "confirm_x3": "confirm, costs x3",
    "holdout": "holdout    Apr 2026 onward",
}

SCREEN_MIN_TRADES = 100
SCREEN_T = 2.0
CONFIRM_MIN_TRADES = 30
EXAM_MIN_TRADES = 30
ALPHA = 0.05
MIN_TICKER_TRADES = 5
COST_STRESS = 3.0
# The baseline samples about one entry per 15 minutes of market time.
BASELINE_MINUTES = 15


def period_of(day: date) -> str | None:
    for name, (first, last) in PERIODS.items():
        if first <= day <= last:
            return name
    return "holdout" if day >= HOLDOUT_START else None


def signal_day(trade: Trade) -> date:
    return trade.signal_time.astimezone(ET).date()


def required_t(candidates: int) -> float:
    """The t a candidate needs at confirmation when `candidates` (it included)
    have reached that stage: one-sided 5%, Bonferroni."""
    return NormalDist().inv_cdf(1 - ALPHA / max(1, candidates))


# --- statistics -----------------------------------------------------------------


@dataclass(frozen=True)
class Stats:
    """A set of trades in R, against random entries with the same exits."""

    n: int = 0
    days: int = 0
    mean_r: float = NA
    total_r: float = 0.0
    profit_factor: float = NA
    win_pct: float = NA
    max_drawdown_r: float = 0.0
    without_best_trade: float = NA
    without_best_day: float = NA
    random_r: float = NA
    edge: float = NA
    edge_se: float = NA
    edge_t: float = NA
    tickers: int = 0
    tickers_up: int = 0
    without_best_ticker: float = NA


def clustered_mean(values: Sequence[float], clusters: Sequence[object]) -> tuple[float, float]:
    """The mean and its standard error with observations grouped by cluster."""
    n = len(values)
    if n == 0:
        return NA, NA
    mean = sum(values) / n
    groups: dict[object, float] = defaultdict(float)
    for value, cluster in zip(values, clusters):
        groups[cluster] += value - mean
    g = len(groups)
    if g < 2:
        return mean, NA
    return mean, math.sqrt(g / (g - 1) * sum(total * total for total in groups.values())) / n


def summarize(trades: Iterable[Trade], random: Mapping[tuple[str, str, int], float]) -> Stats:
    """`random[(ticker, period, side)]` is the average R of random entries."""
    closed = sorted((t for t in trades if t.closed), key=lambda t: t.entry_time)
    if not closed:
        return Stats()
    rs = [t.r for t in closed]
    wins = [r for r in rs if r > 0]
    losses = -sum(r for r in rs if r <= 0)
    peak = running = drawdown = 0.0
    for r in rs:
        running += r
        peak = max(peak, running)
        drawdown = max(drawdown, peak - running)
    by_day: dict[date, float] = defaultdict(float)
    by_ticker: dict[str, list[float]] = defaultdict(list)
    for trade in closed:
        by_day[signal_day(trade)] += trade.r
        by_ticker[trade.ticker].append(trade.r)
    excess, weeks, matched = [], [], []
    for trade in closed:
        base = random.get((trade.ticker, period_of(signal_day(trade)) or "", trade.side), NA)
        if not math.isnan(base):
            excess.append(trade.r - base)
            matched.append(base)
            weeks.append(signal_day(trade).isocalendar()[:2])
    edge, se = clustered_mean(excess, weeks)
    counted = {ticker: values for ticker, values in by_ticker.items() if len(values) >= MIN_TICKER_TRADES}
    best = max(by_ticker, key=lambda ticker: sum(by_ticker[ticker]))
    rest = [r for ticker, values in by_ticker.items() if ticker != best for r in values]
    return Stats(
        n=len(rs),
        days=len(by_day),
        mean_r=sum(rs) / len(rs),
        total_r=sum(rs),
        profit_factor=sum(wins) / losses if losses else math.inf,
        win_pct=100 * len(wins) / len(rs),
        max_drawdown_r=drawdown,
        without_best_trade=sum(rs) - max(rs),
        without_best_day=sum(rs) - max(by_day.values()),
        random_r=sum(matched) / len(matched) if matched else NA,
        edge=edge,
        edge_se=se,
        edge_t=edge / se if se and not math.isnan(se) else NA,
        tickers=len(counted),
        tickers_up=sum(sum(values) > 0 for values in counted.values()),
        without_best_ticker=sum(rest) / len(rest) if rest else NA,
    )


# --- gates ------------------------------------------------------------------------


@dataclass(frozen=True)
class Check:
    text: str
    passed: bool


@dataclass(frozen=True)
class Gate:
    name: str
    checks: tuple[Check, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)


def _r(value: float) -> str:
    return "n/a" if math.isnan(value) else f"{value:+.3f}R"


def _t(value: float) -> str:
    if math.isnan(value):
        return "n/a"
    return f"{value:.2f}" if abs(value) < 1000 else (">999" if value > 0 else "<-999")


def screen_gate(s: Stats, trained: bool) -> Gate:
    if trained:
        return Gate("screen", (Check("the model was trained on this period, so it is no test here; the confirmation decides", True),))
    return Gate("screen", (
        Check(f"{s.n} trades (at least {SCREEN_MIN_TRADES})", s.n >= SCREEN_MIN_TRADES),
        Check(f"average {_r(s.mean_r)} a trade after costs (above 0)", s.mean_r > 0),
        Check(f"beats random entries by {_r(s.edge)}, t = {_t(s.edge_t)} (at least {SCREEN_T:.2f})",
              s.edge_t >= SCREEN_T),
    ))


def confirm_gate(
    halves: Mapping[str, Stats],
    both: Stats,
    stressed: Stats,
    needed_t: float,
    candidates: int,
    parent: Mapping[str, Stats] | None = None,
) -> Gate:
    checks = []
    for name, s in halves.items():
        checks.append(Check(
            f"{LABELS[name].split('  ')[1]}: {s.n} trades, average {_r(s.mean_r)}, beats random by {_r(s.edge)} "
            f"(at least {CONFIRM_MIN_TRADES} trades, both above 0)",
            s.n >= CONFIRM_MIN_TRADES and s.mean_r > 0 and s.edge > 0,
        ))
    checks.append(Check(
        f"both halves: beats random by {_r(both.edge)}, t = {_t(both.edge_t)} (at least {needed_t:.2f}, "
        f"the bar with {candidates} candidates at this stage)",
        both.edge_t >= needed_t,
    ))
    checks.append(Check(f"with costs x{COST_STRESS:g}: average {_r(stressed.mean_r)} (above 0)", stressed.mean_r > 0))
    checks.append(Check(
        f"made money on {both.tickers_up} of {both.tickers} tickers with {MIN_TICKER_TRADES}+ trades (at least half)",
        both.tickers > 0 and 2 * both.tickers_up >= both.tickers,
    ))
    checks.append(Check(f"without its best ticker: average {_r(both.without_best_ticker)} (above 0)",
                        both.without_best_ticker > 0))
    if parent is not None:
        for name, s in halves.items():
            checks.append(Check(
                f"{LABELS[name].split('  ')[1]}: {_r(s.mean_r)} a trade against {_r(parent[name].mean_r)} without the model (better)",
                s.mean_r > parent[name].mean_r,
            ))
    return Gate("confirm", tuple(checks))


def exam_gate(s: Stats, parent: Stats | None = None) -> Gate:
    checks = [
        Check(f"{s.n} trades (at least {EXAM_MIN_TRADES})", s.n >= EXAM_MIN_TRADES),
        Check(f"average {_r(s.mean_r)} a trade (above 0)", s.mean_r > 0),
        Check(f"beats random entries by {_r(s.edge)} (above 0)", s.edge > 0),
    ]
    if parent is not None:
        checks.append(Check(f"{_r(s.mean_r)} against {_r(parent.mean_r)} without the model (better)",
                            s.mean_r > parent.mean_r))
    return Gate("exam", tuple(checks))


# --- the evaluation ---------------------------------------------------------------

# (ticker, timeframe, last day or None for everything) -> the series, or None without data.
Loader = Callable[[str, int, date | None], Series | None]


@dataclass
class Evaluation:
    spec: Spec
    id: str
    parent_id: str | None
    prior_candidates: int
    model: LogisticModel | None = None
    stats: dict[str, Stats] = field(default_factory=dict)
    parent_stats: dict[str, Stats] = field(default_factory=dict)
    by_ticker: dict[str, dict[str, Stats]] = field(default_factory=dict)
    random_stop: dict[str, str] = field(default_factory=dict)
    trades: list[Trade] = field(default_factory=list)
    screen: Gate | None = None
    confirm: Gate | None = None
    exam: Gate | None = None
    splits: dict[str, list[Split]] = field(default_factory=dict)
    missing: dict[str, list[str]] = field(default_factory=dict)  # stage -> tickers without bars

    @property
    def reached_confirmation(self) -> bool:
        return self.confirm is not None

    @property
    def candidates(self) -> int:
        """Candidates at the confirmation stage, this one included when it got there."""
        return self.prior_candidates + self.reached_confirmation

    @property
    def needed_t(self) -> float:
        return required_t(self.prior_candidates + 1)

    @property
    def verdict(self) -> str:
        if self.screen is None or not self.screen.passed:
            return "failed_screen"
        if self.confirm is None or not self.confirm.passed:
            return "failed_confirmation"
        if self.exam is None:
            return "passed_confirmation"
        if self.stats["holdout"].n < EXAM_MIN_TRADES:
            return "awaiting_exam"
        return "passed" if self.exam.passed else "failed_exam"


def _acceptor(spec: Spec, features: FeatureContext, model: LogisticModel | None) -> Callable[[Signal], bool] | None:
    if not spec.filters and model is None:
        return None

    def accept(signal: Signal) -> bool:
        values = features.at(signal.index, signal.side, signal.stop)
        if not all(rule.passes(values) for rule in spec.filters):
            return False
        return model is None or model.takes(values)

    return accept


def _in(trades: Iterable[Trade], periods: Iterable[str]) -> list[Trade]:
    wanted = set(periods)
    return [t for t in trades if t.closed and period_of(signal_day(t)) in wanted]


class _Stage:
    """One look at the data through `through`: the candidate's trades (the
    parent's too when there is a model, and the candidate's with costs
    tripled if asked), then random entries for `periods`. A model not yet
    trained is fitted here on the parent's discovery trades, before the
    candidate runs."""

    def __init__(self, ev: Evaluation, load: Loader, name: str, through: date | None, periods: Sequence[str],
                 stressed: bool, progress: Callable[[str], None]):
        spec = ev.spec
        self.ev, self.spec, self.rules, self.stressed_run = ev, spec, spec.rules(), stressed
        self.market = load(MARKET, spec.timeframe, through)
        self.trades: list[Trade] = []
        self.parent: list[Trade] = []
        self.stressed: list[Trade] = []
        # Series are kept between passes unless they are minute bars, which are too many to hold.
        kept: dict[str, Series] = {}
        available: list[str] = []
        for ticker in spec.tickers:
            series = load(ticker, spec.timeframe, through)
            if series is None or len(series) == 0:
                ev.missing.setdefault(name, []).append(ticker)
                continue
            available.append(ticker)
            if series.splits:
                ev.splits[ticker] = series.splits
            if spec.timeframe >= 5:
                kept[ticker] = series
            features = FeatureContext(series, self.market)
            if spec.model is not None:
                self.parent += run_candidate(series, self.rules.start(series), spec.exits, spec.costs, spec.window,
                                             spec.limits, _acceptor(spec, features, None), features)
            if spec.model is None or ev.model is not None:
                self._run(series, features)
            progress(f"  {ticker}: {len(series)} bars")
        if spec.model is not None and ev.model is None:
            training = _in(self.parent, ["discovery"])
            if not training:
                raise ValueError("the model has no discovery trades to learn from")
            ev.model = fit_logistic([t.features for t in training], [int(t.r > 0) for t in training],
                                    spec.model.features, spec.model.l2)
            progress(f"  trained the model on {len(training)} discovery trades")
            for ticker in available:
                series = kept.get(ticker) or load(ticker, spec.timeframe, through)
                assert series is not None
                self._run(series, FeatureContext(series, self.market))
        self.random = _random_entries(ev, load, through, periods, self.trades, kept)

    def _run(self, series: Series, features: FeatureContext) -> None:
        spec, rules, model = self.spec, self.rules, self.ev.model
        self.trades += run_candidate(series, rules.start(series), spec.exits, spec.costs, spec.window,
                                     spec.limits, _acceptor(spec, features, model), features)
        if self.stressed_run:
            self.stressed += run_candidate(series, rules.start(series), spec.exits, spec.costs.times(COST_STRESS),
                                           spec.window, spec.limits, _acceptor(spec, features, model))


def _random_entries(
    ev: Evaluation,
    load: Loader,
    through: date | None,
    periods: Sequence[str],
    trades: Sequence[Trade],
    cached: Mapping[str, Series],
) -> dict[tuple[str, str, int], float]:
    """The average R of an entry at every bar (sampled every BASELINE_MINUTES),
    with the candidate's exits and costs and its family's stop rule, per
    ticker, period and side."""
    spec = ev.spec
    rules = spec.rules()
    sides = family_sides(rules)
    stops: dict[str, SwingStop | AtrStop] = {}
    for period in periods:
        rule = rules.baseline_stop()
        if rule == MATCHED:
            risks = [t.features.get("risk", NA) for t in _in(trades, [period])]
            risks = [r for r in risks if not math.isnan(r)]
            rule = AtrStop(median(risks) if risks else 1.0, getattr(rules, "atr_length", 14))
        stops[period] = rule
        ev.random_stop[period] = rule.describe()
    stride = max(1, BASELINE_MINUTES // spec.timeframe)
    out: dict[tuple[str, str, int], float] = {}
    for ticker in spec.tickers:
        series = cached.get(ticker) or load(ticker, spec.timeframe, through)
        if series is None or len(series) == 0:
            continue
        for period in periods:
            first = PERIODS[period][0] if period in PERIODS else HOLDOUT_START
            last = PERIODS[period][1] if period in PERIODS else date.max
            signals = baseline_signals(series, stops[period], sides, first, last, spec.window, stride)
            results: dict[int, list[float]] = defaultdict(list)
            for trade in run_each(series, signals, spec.exits, spec.costs):
                if trade.closed:
                    results[trade.side].append(trade.r)
            for side, rs in results.items():
                out[(ticker, period, side)] = sum(rs) / len(rs)
    return out


def _by_ticker(trades: Sequence[Trade], random: Mapping) -> dict[str, Stats]:
    groups: dict[str, list[Trade]] = defaultdict(list)
    for trade in trades:
        groups[trade.ticker].append(trade)
    return {ticker: summarize(group, random) for ticker, group in sorted(groups.items())}


def evaluate(
    spec: Spec,
    load: Loader,
    prior_candidates: int,
    exam: bool = True,
    progress: Callable[[str], None] = lambda _: None,
) -> Evaluation:
    """Screen, confirm and examine a candidate. Each stage loads only the data
    it may see: the discovery period, then through the confirmation period,
    then (for a candidate that passed both, and only when `exam` is set)
    everything, the holdout included."""
    parent = spec.parent()
    ev = Evaluation(spec, spec_id(spec), spec_id(parent) if parent else None, prior_candidates)
    trained = spec.model is not None

    progress("screen: the discovery period")
    stage = _Stage(ev, load, "screen", PERIODS["discovery"][1], ["discovery"], stressed=False, progress=progress)
    discovery = _in(stage.trades, ["discovery"])
    ev.stats["discovery"] = summarize(discovery, stage.random)
    ev.by_ticker["discovery"] = _by_ticker(discovery, stage.random)
    ev.trades = discovery
    if trained:
        ev.parent_stats["discovery"] = summarize(_in(stage.parent, ["discovery"]), stage.random)
    ev.screen = screen_gate(ev.stats["discovery"], trained)
    if not ev.screen.passed:
        return ev

    progress("confirm: October 2024 through March 2026")
    halves = ["confirm_a", "confirm_b"]
    stage = _Stage(ev, load, "confirm", PERIODS["confirm_b"][1], halves, stressed=True, progress=progress)
    for name in halves:
        ev.stats[name] = summarize(_in(stage.trades, [name]), stage.random)
        if trained:
            ev.parent_stats[name] = summarize(_in(stage.parent, [name]), stage.random)
    confirmed = _in(stage.trades, halves)
    ev.stats["confirm"] = summarize(confirmed, stage.random)
    ev.stats["confirm_x3"] = summarize(_in(stage.stressed, halves), stage.random)
    ev.by_ticker["confirm"] = _by_ticker(confirmed, stage.random)
    ev.trades = discovery + confirmed
    ev.confirm = confirm_gate(
        {name: ev.stats[name] for name in halves},
        ev.stats["confirm"],
        ev.stats["confirm_x3"],
        ev.needed_t,
        prior_candidates + 1,
        {name: ev.parent_stats[name] for name in halves} if trained else None,
    )
    if not ev.confirm.passed or not exam:
        return ev

    progress("exam: the locked holdout, April 2026 onward")
    stage = _Stage(ev, load, "exam", None, ["holdout"], stressed=False, progress=progress)
    held = _in(stage.trades, ["holdout"])
    ev.stats["holdout"] = summarize(held, stage.random)
    ev.by_ticker["holdout"] = _by_ticker(held, stage.random)
    ev.trades = discovery + confirmed + held
    if trained:
        ev.parent_stats["holdout"] = summarize(_in(stage.parent, ["holdout"]), stage.random)
    ev.exam = exam_gate(ev.stats["holdout"], ev.parent_stats.get("holdout"))
    return ev


# --- the ledger -------------------------------------------------------------------


def _plain(value: object) -> object:
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else round(value, 6)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def ledger_record(ev: Evaluation, recorded: datetime, code: str, cache_through: date | None) -> dict:
    """One line of the ledger: what was tried, on what, and what became of it."""
    gates = [gate for gate in (ev.screen, ev.confirm, ev.exam) if gate is not None]
    return _plain({
        "id": ev.id,
        "name": ev.spec.name,
        "source": "factory",
        "recorded": recorded.isoformat(timespec="seconds"),
        "code": code,
        "cache_through": cache_through.isoformat() if cache_through else None,
        "spec": canonical(ev.spec),
        "notes": ev.spec.notes,
        "parent": ev.parent_id,
        "model": ev.model.to_json() if ev.model else None,
        "periods": {name: asdict(stats) for name, stats in ev.stats.items()},
        "gates": {gate.name: {"passed": gate.passed, "checks": [[c.text, c.passed] for c in gate.checks]}
                  for gate in gates},
        "reached_confirmation": ev.reached_confirmation,
        "bar_t": ev.needed_t if ev.reached_confirmation else None,
        "verdict": ev.verdict,
    })


def prior_candidates(records: Iterable[Mapping], excluding: str | None = None) -> int:
    """Distinct candidates, hand research included, that have reached the confirmation stage."""
    return len({r["id"] for r in records if r.get("reached_confirmation") and r["id"] != excluding})


# --- the report ---------------------------------------------------------------------

VERDICTS = {
    "failed_screen": "failed the screen. The confirmation periods and the holdout were never loaded for it.",
    "failed_confirmation": "passed the screen but failed confirmation on data it had not seen. The holdout stays locked.",
    "passed_confirmation": "passed confirmation; the exam was not run.",
    "awaiting_exam": "passed confirmation; the holdout does not have enough trades yet, so run it again later.",
    "failed_exam": "passed confirmation but failed the exam on the locked holdout.",
    "passed": "passed every gate. It is a candidate for paper trading, not yet for money.",
}


def _row(label: str, s: Stats) -> str:
    if s.n == 0:
        return f"  {label:34s} {0:6d}"
    pf = "inf" if math.isinf(s.profit_factor) else f"{s.profit_factor:4.2f}"
    return (f"  {label:34s} {s.n:6d} {s.mean_r:+7.3f} {pf:>5s} {s.total_r:+8.1f} {s.random_r:+7.3f} "
            f"{s.edge:+7.3f} {_t(s.edge_t):>6s} {s.tickers_up:4d}/{s.tickers:<3d}")


def report(ev: Evaluation) -> str:
    spec = ev.spec
    exits = spec.exits
    held = f"up to {exits.max_sessions} sessions" if exits.max_sessions > 1 else "flat by the close"
    lines = [
        f"Strategy factory: {spec.name}",
        f"id {ev.id} | {spec.family}, {spec.timeframe}-minute bars, "
        f"{'/'.join('long' if s == 1 else 'short' for s in family_sides(spec.rules()))} | "
        + (f"target {exits.target_r:g}R, " if exits.target_r is not None else "no target, ")
        + held
        + (f", at most {exits.max_minutes} minutes" if exits.max_minutes else "")
        + f" | costs {spec.costs.slippage_ticks:g} tick or {spec.costs.slippage_bps:g} bp a fill",
        f"settings: {dict(spec.params)}",
    ]
    if spec.filters:
        lines.append("filters: " + ", ".join(f.describe() for f in spec.filters))
    if ev.model is not None:
        m = ev.model
        weights = ", ".join(f"{name} {weight:+.2f}" for name, weight in
                            sorted(zip(m.features, m.weights), key=lambda item: -abs(item[1])))
        lines.append(f"model: logistic, trained on {m.trained_on} discovery trades, takes a trade when its "
                     f"chance of ending positive is at least {m.threshold:.2f}; weights per deviation: {weights}")
    for stage, tickers in ev.missing.items():
        lines.append(f"no bars at the {stage} stage for: {', '.join(tickers)}")
    if ev.splits:
        lines.append("splits taken out: " + ", ".join(
            f"{ticker} {split.day} ({split.ratio:g}:1)" for ticker, splits in ev.splits.items() for split in splits))
    lines += ["", f"  {'':34s} {'trades':>6s} {'avg R':>7s} {'PF':>5s} {'total R':>8s} {'random':>7s} "
                  f"{'edge':>7s} {'t':>6s} {'tickers up':>10s}"]
    for name in ("discovery", "confirm_a", "confirm_b", "confirm", "confirm_x3", "holdout"):
        if name in ev.stats:
            lines.append(_row(LABELS[name], ev.stats[name]))
            if name in ev.parent_stats:
                lines.append(_row("  without the model", ev.parent_stats[name]))
        elif name == "holdout":
            lines.append(f"  {LABELS[name]:34s} locked")
    stops = sorted(set(ev.random_stop.values()))
    lines.append(f"  random: an entry every {BASELINE_MINUTES} minutes with the same exits and costs, the stop "
                 + (stops[0] if len(stops) == 1 else "; ".join(f"{name}: {text}" for name, text in ev.random_stop.items())))
    for gate in (ev.screen, ev.confirm, ev.exam):
        if gate is None:
            continue
        lines += ["", f"{gate.name.capitalize()}: {'PASS' if gate.passed else 'FAIL'}"]
        lines += [f"  {'pass' if check.passed else 'FAIL'}  {check.text}" for check in gate.checks]
    lines += [
        "",
        f"Verdict: {VERDICTS[ev.verdict]}",
        f"Candidates at the confirmation stage so far: {ev.candidates} "
        f"(the next one needs t >= {required_t(ev.candidates + 1):.2f}).",
    ]
    for period, table in ev.by_ticker.items():
        lines += ["", f"By ticker, {LABELS.get(period, period).strip()}:"]
        lines += [_row(ticker, s) for ticker, s in table.items()]
    return "\n".join(lines)
