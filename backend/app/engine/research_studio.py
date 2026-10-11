"""R1 discovery event observations. Supplied snapshots only; no outcomes or I/O.

The Factory retains its calculations. Studio adds availability masks and one
same-session move; no strategy stop, fill, result ledger or validation gate.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import json
import math
import struct
from types import MappingProxyType
from typing import Mapping

from app.engine.factory_data import FeatureContext, NYSE_EARLY_CLOSES, Series, prior
from app.engine.factory_rules import CORE_UNIVERSE, MARKET
from app.engine.market_map import Bar, ET

VERSION = 1
WARMUP_START = date(2023, 6, 1)
DISCOVERY_START = date(2023, 7, 3)
DISCOVERY_END = date(2024, 9, 30)
# Versioned R0 roster: weekday omissions in the audited 335 SPY sessions.
# Offline source evidence, not an independently reconciled exchange calendar.
CLOSED_DATES = frozenset(date.fromisoformat(x) for x in (
    "2023-06-19", "2023-07-04", "2023-09-04", "2023-11-23", "2023-12-25",
    "2024-01-01", "2024-01-15", "2024-02-19", "2024-03-29", "2024-05-27",
    "2024-06-19", "2024-07-04", "2024-09-02",
))
ROSTER_VERSION = "r0-spy-roster-335-v1"
# Explicit MU comparison protocol selected by the owner on 2026-10-11.
# V1 discovery bounds/roster/canonical identities are preserved.
NEWER_PROTOCOL = "mu-fixed-rules-20261011-v1"
NEWER_END = date(2026, 10, 9)
NEWER_PERIODS = (
    ("Late 2024", date(2024, 10, 1), date(2024, 12, 31)),
    ("2025", date(2025, 1, 1), date(2025, 12, 31)),
    ("2026 through October 9", date(2026, 1, 1), NEWER_END),
)
# Published NYSE closures, including the Jan 9, 2025 mourning closure.
NEWER_CLOSED = CLOSED_DATES | frozenset(date.fromisoformat(x) for x in (
    "2024-11-28", "2024-12-25",
    "2025-01-01", "2025-01-09", "2025-01-20", "2025-02-17", "2025-04-18",
    "2025-05-26", "2025-06-19", "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25",
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07",
))


def validate_source_version(version: int) -> None:
    if type(version) is not int or version not in (1, 2):
        raise ValueError("unsupported source protocol")


FEATURE_UNITS = MappingProxyType({
    "minutes": "minutes since 09:30 ET at completed bar close",
    "rvol": "cumulative volume / up-to-10 prior clock observations (minimum 5)",
    "gap": "prior daily ATR(14)", "day_move": "prior daily ATR(14)",
    "trend": "prior daily ATR(14), distance from prior daily EMA(20)",
    "trend_slope": "prior daily ATR(14), five-session EMA(20) change",
    "rel_strength": "percentage points versus SPY over five sessions",
    "spy_trend": "prior SPY daily ATR(14), distance from prior EMA(20)",
    "spy_day": "prior SPY daily ATR(14)",
    "vwap_distance": "chart ATR(14), distance from resampled-HLC3 session VWAP",
    "vol_ratio": "prior daily ATR(5) / ATR(20)",
    "spy_vol": "percent of prior SPY close",
    "open_trend": "prior daily ATR(14), opening distance from prior EMA(20)",
    "move_15m_atr": "15-minute close-to-close change / prior daily ATR(14)",
})
DAILY_LOOKBACK = MappingProxyType({
    "gap": 14, "day_move": 14, "trend": 20, "trend_slope": 25,
    "open_trend": 20, "vol_ratio": 20, "rel_strength": 5, "move_15m_atr": 14,
})
MARKET_LOOKBACK = MappingProxyType({"spy_trend": 20, "spy_day": 14, "spy_vol": 14, "rel_strength": 5})


def session_close(day: date) -> int:
    return NYSE_EARLY_CLOSES.get(day, 960)


@lru_cache(maxsize=512)
def session_dates(through: date = DISCOVERY_END, *, version: int = 1) -> tuple[date, ...]:
    validate_source_date(through, version=version)
    closed = CLOSED_DATES if version == 1 else NEWER_CLOSED
    return tuple(WARMUP_START + timedelta(days=k) for k in range((through - WARMUP_START).days + 1)
                 if (WARMUP_START + timedelta(days=k)).weekday() < 5
                 and WARMUP_START + timedelta(days=k) not in closed)


def validate_source_date(day: date, *, version: int = 1) -> None:
    validate_source_version(version)
    limit = DISCOVERY_END if version == 1 else NEWER_END
    if type(day) is not date or not WARMUP_START <= day <= limit:
        raise ValueError("source date outside approved warm-up/discovery interval")


def validate_symbol(symbol: str, *, market: bool = False) -> None:
    if symbol not in CORE_UNIVERSE and not (market and symbol == MARKET):
        raise ValueError("symbol outside approved core universe")


def _number(value) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("predicate bounds must be finite numbers")
    return 0.0 if value == 0 else float(value)


@dataclass(frozen=True)
class Predicate:
    feature: str
    minimum: float | None = None
    maximum: float | None = None

    def __post_init__(self):
        if self.feature not in FEATURE_UNITS:
            raise ValueError("unknown or execution-only feature")
        for name in ("minimum", "maximum"):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, _number(getattr(self, name)))
        if self.minimum is None and self.maximum is None:
            raise ValueError("predicate needs at least one inclusive bound")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("predicate minimum exceeds maximum")

    def matches(self, value: float) -> bool:
        return ((self.minimum is None or value >= self.minimum)
                and (self.maximum is None or value <= self.maximum))

    def canonical(self) -> dict:
        return {"feature": self.feature, "minimum": self.minimum, "maximum": self.maximum}


@dataclass(frozen=True)
class Definition:
    predicates: tuple[Predicate, ...]
    universe: tuple[str, ...] = CORE_UNIVERSE
    start: date = DISCOVERY_START
    end: date = DISCOVERY_END
    window_start: int = 600
    window_end: int = 690
    version: int = VERSION

    def __post_init__(self):
        if type(self.version) is not int or self.version not in (VERSION, 2):
            raise ValueError("unsupported event definition version")
        if type(self.predicates) is not tuple or not 1 <= len(self.predicates) <= 3:
            raise ValueError("one to three AND predicates required")
        if any(not isinstance(p, Predicate) for p in self.predicates):
            raise ValueError("invalid predicate")
        if type(self.universe) is not tuple or not self.universe or len(set(self.universe)) != len(self.universe):
            raise ValueError("nonempty distinct core symbols required")
        for symbol in self.universe:
            validate_symbol(symbol)
        if (type(self.start) is not date or type(self.end) is not date
                or not DISCOVERY_START <= self.start <= self.end <= (DISCOVERY_END if self.version == 1 else NEWER_END)):
            raise ValueError("event dates must remain inside discovery")
        if (type(self.window_start) is not int or type(self.window_end) is not int
                or not 575 <= self.window_start <= self.window_end <= 960
                or self.window_start % 5 or self.window_end % 5):
            raise ValueError("window uses aligned completed-bar close minutes in RTH")

        if self.version == 2:
            expected = {("move_15m_atr", None, -0.25), ("rvol", 1.5, None)}
            actual = {(p.feature, p.minimum, p.maximum) for p in self.predicates}
            variant = {("move_15m_atr", None, -0.25), ("rvol", 2.0, None)}
            if (self.universe != ("MU",) or (self.start, self.end) not in {(a, b) for _, a, b in NEWER_PERIODS}
                    or (self.window_start, self.window_end) != (600, 690)
                    or len(self.predicates) != 2 or actual not in (expected, variant)):
                raise ValueError("newer MU study requires a fixed period and the unchanged MU rules")

    def canonical(self) -> dict:
        result = {
            "version": self.version, "predicates": sorted((p.canonical() for p in self.predicates), key=_json),
            "universe": sorted(self.universe), "start": self.start.isoformat(), "end": self.end.isoformat(),
            "window_start": self.window_start, "window_end": self.window_end,
            "timeframe_minutes": 5, "rule": "first_qualifying_completed_bar_per_ticker_session",
            "direction": "price_decline_negative", "feature_units": dict(FEATURE_UNITS),
        }

        if self.version == 2:
            result["protocol"] = NEWER_PROTOCOL
            result["exploratory_exposure"] = True
        return result

    @property
    def identity(self) -> str:
        return _hash(self.canonical())


def parse_definition(raw: dict) -> Definition:
    allowed = {"version", "predicates", "universe", "start", "end", "window_start", "window_end"}
    metadata = {"timeframe_minutes": 5, "rule": "first_qualifying_completed_bar_per_ticker_session",
                "direction": "price_decline_negative", "feature_units": dict(FEATURE_UNITS)}
    if type(raw) is dict and raw.get("version") == 2:
        metadata.update(protocol=NEWER_PROTOCOL, exploratory_exposure=True)
    if (type(raw) is not dict or set(raw) - allowed - metadata.keys()
            or "predicates" not in raw or "version" not in raw):
        raise ValueError("invalid event definition fields")
    if any(raw[key] != expected for key, expected in metadata.items() if key in raw):
        raise ValueError("definition metadata differs from the versioned contract")
    if type(raw["predicates"]) is not list:
        raise ValueError("predicates must be a list")
    predicates = []
    for p in raw["predicates"]:
        if type(p) is not dict or set(p) - {"feature", "minimum", "maximum"} or "feature" not in p:
            raise ValueError("invalid predicate fields")
        predicates.append(Predicate(**p))
    args = {key: value for key, value in raw.items() if key in allowed}
    args["predicates"] = tuple(predicates)
    if "universe" in args:
        if type(args["universe"]) is not list:
            raise ValueError("universe must be a list")
        args["universe"] = tuple(args["universe"])
    for name in ("start", "end"):
        if name in args:
            args[name] = date.fromisoformat(args[name])
    return Definition(**args)


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


@dataclass(frozen=True)
class Coverage:
    day: date
    state: str  # missing, empty or present
    valid_minutes: int = 0  # bit zero is 09:30; no invented minutes
    invalid_rows: int = 0
    duplicate_minutes: int = 0
    off_grid_rows: int = 0

    def complete_to(self, close_minute: int) -> bool:
        count = close_minute - 570
        return count > 0 and self.valid_minutes & ((1 << count) - 1) == (1 << count) - 1

    @property
    def complete(self) -> bool:
        return self.complete_to(session_close(self.day))

    def bucket_complete(self, open_minute: int) -> bool:
        return (self.valid_minutes >> (open_minute - 570)) & 31 == 31


@dataclass(frozen=True)
class SymbolSnapshot:
    symbol: str
    bars: tuple[Bar, ...]  # available-minute aggregates, including flagged partial buckets
    coverage: tuple[Coverage, ...]


@dataclass(frozen=True)
class Snapshot:
    through: date
    symbols: tuple[SymbolSnapshot, ...]
    manifest: tuple[tuple[str, str, str, int], ...]  # symbol, date, byte hash/state, length
    engine_fingerprint: str
    provenance: str = "SIP directory/current raw writer; supplier receipt unavailable"
    source_version: int = 1
    prepared_fingerprint: str = field(init=False)

    def __post_init__(self):
        validate_source_date(self.through, version=self.source_version)
        if type(self.symbols) is not tuple or type(self.manifest) is not tuple:
            raise ValueError("snapshot collections must be immutable")
        names = [x.symbol for x in self.symbols]
        if len(set(names)) != len(names) or MARKET not in names:
            raise ValueError("distinct snapshot symbols and SPY required")
        if self.source_version == 2 and set(names) != {"MU", MARKET}:
            raise ValueError("newer source is bounded to MU and SPY")
        allowed_days = frozenset(session_dates(self.through, version=self.source_version))
        expected = {(name, str(day)) for name in names for day in session_dates(self.through, version=self.source_version)}
        if (any(type(row) is not tuple or len(row) != 4 for row in self.manifest)
                or len(self.manifest) != len(expected) or {(row[0], row[1]) for row in self.manifest} != expected):
            raise ValueError("manifest must describe exactly the bounded source roster")
        prepared = hashlib.sha256()
        for source in self.symbols:
            validate_symbol(source.symbol, market=True)
            prepared.update(source.symbol.encode())
            if (type(source.bars) is not tuple or type(source.coverage) is not tuple
                    or tuple(c.day for c in source.coverage) != session_dates(self.through, version=self.source_version)):
                raise ValueError("snapshot needs immutable complete roster coverage")
            coverage_by_day = {c.day: c for c in source.coverage}
            present_buckets: dict[date, int] = {}
            for c in source.coverage:
                if (c.state not in ("missing", "empty", "present") or c.valid_minutes < 0
                        or c.valid_minutes >> (session_close(c.day) - 570)):
                    raise ValueError("invalid coverage mask")
                prepared.update(_json([str(c.day), c.state, c.valid_minutes, c.invalid_rows,
                                       c.duplicate_minutes, c.off_grid_rows]).encode())
            for bar in source.bars:
                if (bar.time.tzinfo is None or bar.time.utcoffset() is None
                        or not WARMUP_START <= bar.time.astimezone(ET).date() <= self.through):
                    raise ValueError("snapshot bar outside approved interval")
                local = bar.time.astimezone(ET)
                minute = local.hour * 60 + local.minute
                if (local.second or local.microsecond or minute % 5
                        or not 570 <= minute < session_close(local.date())
                        or local.date() not in allowed_days
                        or not all(math.isfinite(v) for v in (bar.open, bar.high, bar.low, bar.close, bar.volume))):
                    raise ValueError("snapshot needs finite aligned RTH bars")
                cov = coverage_by_day[local.date()]
                bit = 1 << ((minute - 570) // 5)
                if not (cov.valid_minutes >> (minute - 570)) & 31 or present_buckets.get(cov.day, 0) & bit:
                    raise ValueError("prepared bars disagree with source coverage")
                present_buckets[cov.day] = present_buckets.get(cov.day, 0) | bit
                prepared.update(struct.pack(">6d", bar.time.timestamp(), bar.open, bar.high, bar.low, bar.close, bar.volume))
            for cov in source.coverage:
                expected_buckets = sum(1 << k for k, m in enumerate(range(570, session_close(cov.day), 5))
                                       if (cov.valid_minutes >> (m - 570)) & 31)
                if present_buckets.get(cov.day, 0) != expected_buckets:
                    raise ValueError("prepared snapshot lost source buckets")
        object.__setattr__(self, "prepared_fingerprint", prepared.hexdigest())

    @property
    def identity(self) -> str:
        metadata = {"version": VERSION, "through": str(self.through), "manifest": self.manifest,
                      "engine": self.engine_fingerprint, "provenance": self.provenance,
                      "prepared": self.prepared_fingerprint,
                      "feed": "sip", "adjustment": "Factory inferred splits within source cutoff; no dividends",
                      "roster": ROSTER_VERSION, "sessions": [str(d) for d in session_dates(self.through, version=self.source_version)],
                      "hours": [[str(d), 570, session_close(d)] for d in session_dates(self.through, version=self.source_version)]}
        if self.source_version == 2:
            metadata.update(source_protocol=NEWER_PROTOCOL, roster="nyse-mu-20261009-v1")
        return _hash(metadata)


@dataclass(frozen=True)
class FeatureValue:
    value: float | None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _Moment:
    symbol: str
    day: date
    close: datetime
    values: tuple[float, ...]


@dataclass(frozen=True)
class _Grid:
    names: tuple[str, ...]
    moments: tuple[_Moment, ...]
    examined: int
    exclusions: tuple[tuple[str, int], ...]
    unavailable: tuple[tuple[str, int], ...]
    coverage: Mapping[str, Mapping[str, int]]


class _Quality:
    def __init__(self, source: SymbolSnapshot, *, version: int = 1):
        self.coverage = {x.day: x for x in source.coverage}
        complete = {day: c.complete for day, c in self.coverage.items()}
        self.daily_reasons = {}
        for day in self.coverage:
            before = session_dates(day, version=version)[:-1]
            self.daily_reasons[day] = {
                count: ("daily_warmup" if len(before) < count else
                        "daily_history_gap" if not all(complete.get(d, False) for d in before[-count:]) else None)
                for count in (5, 14, 20, 25)
            }
        self.series = Series.build(source.symbol, source.bars, 5) if source.bars else None
        self.index = {t: i for i, t in enumerate(self.series.time)} if self.series else {}
        self.rvol_reasons: list[str | None] = []
        history: dict[int, deque[bool]] = {}
        if self.series:
            for i, minute in enumerate(self.series.minute):
                day = self.series.days[self.series.session[i]]
                cov = self.coverage[day]
                past = history.setdefault(minute, deque(maxlen=10))
                reason = ("rvol_warmup" if len(past) < 5 else "rvol_history_gap" if not all(past)
                          else "cumulative_volume_gap" if not cov.complete_to(minute + 5) else None)
                self.rvol_reasons.append(reason)
                past.append(cov.complete_to(minute + 5))

    def prior_complete(self, day: date, count: int) -> str | None:
        return self.daily_reasons[day][count]

    def consecutive(self, i: int, count: int) -> bool:
        s = self.series
        if s is None or i + 1 < count:
            return False
        day = s.days[s.session[i]]
        cov = self.coverage[day]
        return all(s.session[k] == s.session[i] and cov.bucket_complete(s.minute[k])
                   and s.time[k] == s.time[i] - timedelta(minutes=5 * (i - k))
                   for k in range(i - count + 1, i + 1))


@dataclass(frozen=True)
class Observations:
    """Prepared immutable-source calculations. No file cache or outcome columns."""

    snapshot: Snapshot
    _quality: Mapping[str, _Quality] = field(init=False, repr=False)
    _contexts: Mapping[str, FeatureContext] = field(init=False, repr=False)
    _grid_cache: dict[str, tuple[tuple, _Grid]] = field(init=False, repr=False, compare=False)
    _data_id: str = field(init=False, repr=False)

    def __post_init__(self):
        quality = {x.symbol: _Quality(x, version=self.snapshot.source_version) for x in self.snapshot.symbols}
        market = quality[MARKET].series
        object.__setattr__(self, "_quality", MappingProxyType(quality))
        object.__setattr__(self, "_contexts", MappingProxyType(
            {name: FeatureContext(q.series, market) for name, q in quality.items() if q.series}))
        object.__setattr__(self, "_grid_cache", {})
        object.__setattr__(self, "_data_id", self.snapshot.identity)

    def features(self, symbol: str, moment: datetime) -> Mapping[str, FeatureValue]:
        return self._feature_values(symbol, moment, tuple(FEATURE_UNITS))

    def _feature_values(self, symbol: str, moment: datetime, names: tuple[str, ...]) -> Mapping[str, FeatureValue]:
        validate_symbol(symbol)
        if (moment.tzinfo is None or moment.utcoffset() is None
                or not DISCOVERY_START <= moment.astimezone(ET).date() <= self.snapshot.through):
            raise ValueError("decision moment outside loaded discovery")
        local = moment.astimezone(ET)
        minute = local.hour * 60 + local.minute
        if local.second or local.microsecond or minute % 5 or not 575 <= minute <= session_close(local.date()):
            raise ValueError("decision moment must be an aligned completed RTH bar close")
        if symbol not in self._quality:
            raise ValueError("symbol not present in snapshot")
        q = self._quality[symbol]
        i = q.index.get(moment - timedelta(minutes=5))
        if i is None:
            return MappingProxyType({name: FeatureValue(None, ("missing_decision_bucket",)) for name in names})
        s = q.series
        day = s.days[s.session[i]]
        cov = q.coverage[day]
        if not cov.bucket_complete(s.minute[i]):
            return MappingProxyType({name: FeatureValue(None, ("incomplete_decision_bucket",)) for name in names})
        context = self._contexts[symbol]
        values = context.decision_at(i)
        move_ready = False
        if "move_15m_atr" in names:
            move_ready = q.consecutive(i, 4)
            denominator = prior(context.daily.atr, s.session[i])
            values["move_15m_atr"] = ((s.close[i] - s.close[i - 3]) / denominator
                                       if move_ready and math.isfinite(denominator) and denominator > 0 else math.nan)
        mq = self._quality[MARKET]
        j = mq.index.get(s.time[i])
        market_aligned = j is not None and mq.coverage[day].bucket_complete(mq.series.minute[j])
        out = {}
        for name in names:
            reasons = []
            if name in DAILY_LOOKBACK:
                reason = q.prior_complete(day, DAILY_LOOKBACK[name])
                if reason:
                    reasons.append(reason)
            if name in ("gap", "day_move", "open_trend") and not cov.valid_minutes & 1:
                reasons.append("missing_session_open")
            if name == "rvol" and q.rvol_reasons[i]:
                reasons.append(q.rvol_reasons[i])
            if name == "move_15m_atr" and not move_ready:
                reasons.append("move_15m_history_gap")
            if name == "vwap_distance":
                if not cov.complete_to(s.minute[i] + 5):
                    reasons.append("session_vwap_gap")
                if not q.consecutive(i, 14):
                    reasons.append("chart_atr_history_gap")
            if name in MARKET_LOOKBACK:
                if not market_aligned:
                    reasons.append("missing_aligned_spy")
                else:
                    reason = mq.prior_complete(day, MARKET_LOOKBACK[name])
                    if reason:
                        reasons.append("spy_" + reason)
                    if name == "spy_day" and not mq.coverage[day].valid_minutes & 1:
                        reasons.append("missing_spy_open")
            value = values[name]
            if not math.isfinite(value):
                reasons.append("undefined_value")
            out[name] = FeatureValue(None if reasons else value, tuple(sorted(set(reasons))))
        return MappingProxyType(out)

    def _prepare_grid(self, definition: Definition) -> _Grid:
        exclusions, unavailable, moments = Counter(), Counter(), []
        examined = 0
        names = tuple(sorted({p.feature for p in definition.predicates}))
        for symbol in sorted(definition.universe):
            q = self._quality[symbol]
            for day in session_dates(definition.end, version=definition.version):
                if day < definition.start:
                    continue
                for minute in range(definition.window_start, min(definition.window_end, session_close(day)) + 1, 5):
                    examined += 1
                    if q.series is None:
                        exclusions["unavailable_symbol"] += 1
                        continue
                    cov = q.coverage[day]
                    if cov.state == "missing":
                        exclusions["missing_session"] += 1
                        continue
                    close = datetime(day.year, day.month, day.day, minute // 60, minute % 60, tzinfo=ET)
                    row = self._feature_values(symbol, close, names)
                    reasons = {r for p in definition.predicates for r in row[p.feature].reasons}
                    if reasons:
                        exclusions.update(reasons)
                        unavailable.update({p.feature for p in definition.predicates if row[p.feature].value is None})
                        continue
                    moments.append(_Moment(symbol, day, close, tuple(row[name].value for name in names)))
        coverage = {}
        for name in definition.universe:
            days = [c for c in self._quality[name].coverage.values() if definition.start <= c.day <= definition.end]
            coverage[name] = MappingProxyType({
                "expected_sessions": len(days), "missing_sessions": sum(c.state == "missing" for c in days),
                "empty_sessions": sum(c.state == "empty" for c in days),
                "complete_sessions": sum(c.complete for c in days),
                "missing_minutes": sum(session_close(c.day) - 570 - c.valid_minutes.bit_count() for c in days),
                "complete_buckets": sum(c.bucket_complete(m) for c in days for m in range(570, session_close(c.day), 5)),
                "invalid_rows": sum(c.invalid_rows for c in days),
                "duplicate_minutes": sum(c.duplicate_minutes for c in days),
                "off_grid_rows": sum(c.off_grid_rows for c in days),
            })
        return _Grid(names, tuple(moments), examined, tuple(sorted(exclusions.items())),
                     tuple(sorted(unavailable.items())), MappingProxyType(coverage))

    def _grid(self, definition: Definition) -> _Grid:
        if (definition.version != self.snapshot.source_version
                or definition.end > self.snapshot.through or set(definition.universe) - self._quality.keys()):
            raise ValueError("definition exceeds snapshot dates or symbols")
        names = tuple(sorted({p.feature for p in definition.predicates}))
        key = (tuple(sorted(definition.universe)), definition.start, definition.end,
               definition.window_start, definition.window_end, names)
        cached = self._grid_cache.get("latest")
        grid = cached[1] if cached is not None and cached[0] == key else None
        if grid is None:
            grid = self._prepare_grid(definition)
            # One bounded in-memory feature grid; never shared across snapshots.
            self._grid_cache["latest"] = (key, grid)
        return grid

    def eligible_moments(self, definition: Definition) -> tuple[_Moment, ...]:
        """Outcome-free ordinary population, using the preview's exact masks."""
        return self._grid(definition).moments

    def preview(self, definition: Definition) -> dict:
        grid = self._grid(definition)
        columns = tuple((grid.names.index(p.feature), p.minimum, p.maximum) for p in definition.predicates)
        selected, dates, weeks, events = set(), Counter(), set(), []
        qualifying = 0
        for moment in grid.moments:
            if not all((lo is None or moment.values[i] >= lo) and (hi is None or moment.values[i] <= hi)
                       for i, lo, hi in columns):
                continue
            qualifying += 1
            event_key = (moment.symbol, moment.day)
            if event_key in selected:
                continue
            selected.add(event_key)
            stamp = moment.close.astimezone(timezone.utc).isoformat()
            row = self.features(moment.symbol, moment.close)
            events.append({"occurrence_id": moment.symbol + ":" + stamp, "symbol": moment.symbol,
                           "decision_time": stamp, "session": str(moment.day),
                           "features": {name: {"value": v.value, "reasons": list(v.reasons),
                                               "unit": FEATURE_UNITS[name]} for name, v in row.items()}})
            dates[str(moment.day)] += 1
            weeks.add(str(moment.day - timedelta(days=moment.day.weekday())))
        data_id = self._data_id
        return {"version": VERSION, "definition_id": definition.identity, "data_id": data_id,
                "population_id": _hash({"definition": definition.identity, "data": data_id}),
                "definition": definition.canonical(), "engine_fingerprint": self.snapshot.engine_fingerprint,
                "provenance": self.snapshot.provenance, "roster": ROSTER_VERSION,
                "coverage": {name: dict(c) for name, c in grid.coverage.items()},
                "examined_clock_buckets": grid.examined, "eligible_moments": len(grid.moments),
                "excluded_moments": grid.examined - len(grid.moments),
                "qualifying_moments": qualifying, "event_count": len(events),
                "eligible_symbols": sorted({m.symbol for m in grid.moments}),
                "unavailable_symbols": sorted(name for name in definition.universe
                                              if not any(c.valid_minutes for c in self._quality[name].coverage.values()
                                                         if definition.start <= c.day <= definition.end)
                                              or self._quality[name].series is None),
                "exclusions": dict(grid.exclusions), "unavailable_features": dict(grid.unavailable),
                "distinct_dates": len(dates), "distinct_calendar_weeks": len(weeks),
                "largest_day_fraction": max(dates.values()) / len(events) if events else None,
                "events": sorted(events, key=lambda row: (row["decision_time"], row["symbol"]))}
