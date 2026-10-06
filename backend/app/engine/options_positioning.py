"""Option positioning by strike (Charts C4.2), and the chart levels it draws (C4.4).

Pure: no network, no database, no provider calls, held that way by
`tests/test_import_boundaries.py`. The caller hands in normalized chains
(`options_models`), the underlying's price and the time; nothing here fetches
or fills in a missing value.

What each number is:

- *Observed*: open interest and volume, the provider's fields, summed per strike.
  Open interest is OCC's overnight figure for the previous close; volume is the
  session's so far.
- *Calculated*: ratios, walls (the highest strike on a side), ranks, and gamma.
  Gamma is recomputed here with Black-Scholes from the price handed in and the
  provider's implied volatility, never taken from the provider's hourly greeks.
  Dollar gamma for a 1% move is gamma x open interest x shares per contract x
  S² x 0.01, unsigned: how much hedging a 1% move asks of whoever holds the
  contracts, without saying who that is.
- *Inferred*: max pain, the strike where the open contracts of one expiration
  would pay their holders least at expiry. It is arithmetic on open interest,
  but reading it as where price will settle is folklore, so it says so.
- *Assumed*: signed gamma and the gamma flip. Open interest does not say who
  holds a contract or which way they hedge, so a sign needs a convention
  (``DEALER_SIDE``). It is off unless asked for, and every result built on it
  says so.

Model inputs, for every contract alike: the rate and dividend yield are taken
as zero (``RATE``, ``DIVIDEND``); time runs in calendar years to the contract's
expiry, 16:00 New York (the calendar's close on an early close), or 09:30 for
an AM-settled index root; the volatility is the provider's mid IV, else its
smoothed-surface IV. A contract missing any input (an IV, a known contract
size, its open interest) has no gamma, and the count of those is reported. A
0DTE contract's gamma grows without bound near its strike as expiry nears:
that is the model, not an error, and it ends at expiry.

Roots stay apart: one SPX date lists AM-settled SPX and PM-settled SPXW at the
same strikes, and an adjusted contract after a corporate action carries a root
of its own (``NVDA1``). One positioning reads one root and counts the rest as
left out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time as wall_time, timedelta
from math import exp, log, pi, sqrt
from typing import Iterable, Mapping

from app.engine.chart_levels import Level
from app.engine.chart_math import ET
from app.engine.options_models import OptionChain, OptionContract

RATE = 0.0  # assumed: the risk-free rate
DIVIDEND = 0.0  # assumed: the dividend yield
YEAR_SECONDS = 365 * 86400
PM_EXPIRY = 16 * 60  # minutes of the New York day
AM_EXPIRY = 9 * 60 + 30
# Roots settled on the opening print; their contracts stop at the open of the expiration date.
AM_SETTLED = frozenset({"SPX", "NDX", "RUT"})
# One root by default where the underlying's own name is not the busiest: SPXW carries SPX's dailies and weeklies.
PRIMARY_ROOT = {"SPX": "SPXW"}
DEALER_SIDE = "Dealers long calls and short puts: call gamma counts positive, put gamma negative."
# The gamma flip only where open interest is deep enough for the number to mean anything.
FLIP_SYMBOLS = frozenset({"SPY", "QQQ", "SPX"})
FLIP_RANGE = 0.05  # searched within 5% of the price either way
FLIP_STEPS = 20  # grid points on each side, then bisection
FLIP_STRIKES = 0.25  # strikes further than 25% (in log terms) from the price add nothing measurable
MEASURES = ("oi", "volume", "gamma")
TOP = 10  # strikes ranked for the chart besides the walls


def primary_root(underlying: str) -> str:
    return PRIMARY_ROOT.get(underlying, underlying)


@dataclass(frozen=True, slots=True)
class StrikeRow:
    """One strike across the chosen expirations. A side with nothing listed, or
    nothing the provider reported, is None; a real zero stays zero."""
    strike: float
    call_oi: int | None = None
    put_oi: int | None = None
    call_volume: int | None = None
    put_volume: int | None = None
    # Dollar gamma for a 1% move, unsigned; None when no contract on the side had every input.
    call_gamma: float | None = None
    put_gamma: float | None = None

    def value(self, measure: str, side: str) -> float | None:
        return getattr(self, f"{side}_{'oi' if measure == 'oi' else measure}")

    def total(self, measure: str, signed: bool = False) -> float | None:
        """Both sides of one measure: summed, or for signed gamma the calls' less the puts' (assumed)."""
        call, put = self.value(measure, "call"), self.value(measure, "put")
        if call is None and put is None:
            return None
        if signed and measure == "gamma":
            return (call or 0.0) - (put or 0.0)
        return (call or 0) + (put or 0)


@dataclass(frozen=True, slots=True)
class Positioning:
    underlying: str
    root: str
    spot: float | None
    as_of: datetime  # the moment gamma is computed for
    expirations: tuple[date, ...]
    strikes: tuple[StrikeRow, ...]  # ascending
    # Contracts of other roots left out, by root.
    excluded: dict[str, int] = field(default_factory=dict)
    # Contracts missing an input, by what is missing: open_interest, volume, gamma.
    missing: dict[str, int] = field(default_factory=dict)
    fetched_at: datetime | None = None  # the oldest chain's capture time
    last_trade_at: datetime | None = None  # the newest trade in any chain
    greeks_updated_at: str | None = None  # the provider's IV stamp, verbatim (its time zone is undocumented)

    def totals(self) -> dict:
        """Call and put open interest and volume, with put/call and volume/OI ratios (None over a zero)."""
        sums = {key: sum(getattr(row, key) or 0 for row in self.strikes)
                for key in ("call_oi", "put_oi", "call_volume", "put_volume")}
        return {**sums,
                "put_call_oi": _ratio(sums["put_oi"], sums["call_oi"]),
                "put_call_volume": _ratio(sums["put_volume"], sums["call_volume"]),
                "call_volume_oi": _ratio(sums["call_volume"], sums["call_oi"]),
                "put_volume_oi": _ratio(sums["put_volume"], sums["put_oi"])}

    def wall(self, measure: str, side: str) -> StrikeRow | None:
        """The strike with the most of ``measure`` on ``side``; a tie goes to the strike nearer the price, then the lower."""
        ranked = self.ranked(measure, side)
        return ranked[0] if ranked else None

    def ranked(self, measure: str, side: str | None = None, signed: bool = False) -> list[StrikeRow]:
        """Strikes with a positive value, largest first. ``side`` None ranks both sides together
        (signed gamma by its size, either way)."""
        def value(row: StrikeRow) -> float:
            found = row.value(measure, side) if side else row.total(measure, signed)
            return abs(found) if found is not None else 0.0
        near = (lambda row: abs(row.strike - self.spot)) if self.spot else (lambda row: 0.0)
        return sorted((row for row in self.strikes if value(row) > 0), key=lambda row: (-value(row), near(row), row.strike))

    def ranks(self, measure: str, side: str | None = None, signed: bool = False) -> dict[float, int]:
        """Each ranked strike's place, from 1."""
        return {row.strike: index for index, row in enumerate(self.ranked(measure, side, signed), 1)}

    def rank(self, row: StrikeRow, measure: str, side: str | None = None, signed: bool = False) -> int | None:
        return self.ranks(measure, side, signed).get(row.strike)


def expires_at(expiration: date, root: str, closes: Mapping[date, int | None] | None = None) -> datetime:
    """When a contract stops trading, New York time: the open for an AM-settled root, else the
    session's close (16:00, or the calendar's earlier close)."""
    minute = AM_EXPIRY if root in AM_SETTLED else (closes or {}).get(expiration) or PM_EXPIRY
    return datetime.combine(expiration, wall_time(minute // 60, minute % 60), ET)


def unexpired(expirations: Iterable[date], root: str, now: datetime, closes: Mapping[date, int | None] | None = None) -> list[date]:
    return sorted(d for d in expirations if expires_at(d, root, closes) > now)


def years_left(expiration: date, root: str, now: datetime, closes: Mapping[date, int | None] | None = None) -> float:
    return max((expires_at(expiration, root, closes) - now).total_seconds(), 0.0) / YEAR_SECONDS


def bs_gamma(spot: float, strike: float, years: float, iv: float, rate: float = RATE, dividend: float = DIVIDEND) -> float | None:
    """Black-Scholes gamma per share; None when any input cannot give one (expired, no volatility)."""
    if spot <= 0 or strike <= 0 or years <= 0 or iv <= 0:
        return None
    vol = iv * sqrt(years)
    d1 = (log(spot / strike) + (rate - dividend + iv * iv / 2) * years) / vol
    return exp(-dividend * years) * exp(-d1 * d1 / 2) / (sqrt(2 * pi) * spot * vol)


def dollar_gamma(gamma: float, open_interest: int, multiplier: int, spot: float) -> float:
    """Dollar gamma for a 1% move: the change in the shares' dollar delta when the price moves 1%."""
    return gamma * open_interest * multiplier * spot * spot * 0.01


def positioning(chains: Iterable[OptionChain], underlying: str, spot: float | None, now: datetime,
                root: str | None = None, closes: Mapping[date, int | None] | None = None) -> Positioning:
    """Strike rows over ``chains`` (one expiration each) for one root, gamma at ``spot`` and ``now``.

    Without a price there is no gamma. An expired contract has none either; its
    open interest and volume still count, since they describe the session.
    """
    root = root or primary_root(underlying)
    rows: dict[float, dict] = {}
    excluded: dict[str, int] = {}
    missing = {"open_interest": 0, "volume": 0, "gamma": 0}
    chains = list(chains)
    stamps: dict[str, int] = {}
    trades = []
    for chain in chains:
        for contract in chain.contracts:
            if contract.root != root:
                excluded[contract.root] = excluded.get(contract.root, 0) + 1
                continue
            side = contract.option_type
            row = rows.setdefault(contract.strike, {})
            _add(row, f"{side}_oi", contract.open_interest)
            _add(row, f"{side}_volume", contract.volume)
            if contract.open_interest is None:
                missing["open_interest"] += 1
            if contract.volume is None:
                missing["volume"] += 1
            gamma = _contract_gamma(contract, spot, now, closes)
            if gamma is None:
                missing["gamma"] += 1
            else:
                _add(row, f"{side}_gamma", gamma)
            if contract.greeks_updated_at:
                stamps[contract.greeks_updated_at] = stamps.get(contract.greeks_updated_at, 0) + 1
            if contract.trade_time:
                trades.append(contract.trade_time)
    strikes = tuple(StrikeRow(strike, **values) for strike, values in sorted(rows.items()))
    return Positioning(
        underlying=underlying, root=root, spot=spot, as_of=now,
        expirations=tuple(sorted({chain.expiration for chain in chains})), strikes=strikes,
        excluded=excluded, missing={key: count for key, count in missing.items() if count},
        fetched_at=min((chain.fetched_at for chain in chains), default=None),
        last_trade_at=max(trades, default=None),
        # The stamp most contracts carry: the provider refreshes greeks in batches.
        greeks_updated_at=max(stamps, key=lambda stamp: (stamps[stamp], stamp)) if stamps else None,
    )


def _contract_gamma(contract: OptionContract, spot: float | None, now: datetime, closes) -> float | None:
    iv = contract.iv or contract.iv_smoothed
    if spot is None or iv is None or contract.multiplier is None or contract.open_interest is None:
        return None
    gamma = bs_gamma(spot, contract.strike, years_left(contract.expiration, contract.root, now, closes), iv)
    return None if gamma is None else dollar_gamma(gamma, contract.open_interest, contract.multiplier, spot)


def _add(row: dict, key: str, value: float | None) -> None:
    if value is not None:
        row[key] = row.get(key, 0) + value


def _ratio(top: float, bottom: float) -> float | None:
    return top / bottom if bottom else None


# ---------------------------------------------------------------------------
# Gamma flip (assumed)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GammaFlip:
    price: float | None  # where signed dollar gamma crosses zero, nearest the price; None without a crossing
    searched: tuple[float, float]  # the prices searched
    note: str


def net_gamma_at(chains: Iterable[OptionChain], root: str, price: float, now: datetime,
                 closes: Mapping[date, int | None] | None = None) -> float:
    """Signed dollar gamma (``DEALER_SIDE``) if the underlying stood at ``price``, each contract's IV held."""
    return _signed(_inputs(chains, root, price, now, closes), price)


def gamma_flip(chains: Iterable[OptionChain], underlying: str, spot: float, now: datetime,
               root: str | None = None, closes: Mapping[date, int | None] | None = None) -> GammaFlip:
    """Where signed dollar gamma changes sign, searched within ``FLIP_RANGE`` of ``spot``: a model
    estimate on an assumed dealer side, with each strike's IV and the time held where they are."""
    root = root or primary_root(underlying)
    low, high = spot * (1 - FLIP_RANGE), spot * (1 + FLIP_RANGE)
    if underlying not in FLIP_SYMBOLS:
        return GammaFlip(None, (low, high), f"Shown for {', '.join(sorted(FLIP_SYMBOLS))} only: a single name's open interest is too thin for it.")
    inputs = _inputs(chains, root, spot, now, closes)
    if not inputs:
        return GammaFlip(None, (low, high), "No contract has every input gamma needs.")
    grid = [spot * (1 + FLIP_RANGE * i / FLIP_STEPS) for i in range(-FLIP_STEPS, FLIP_STEPS + 1)]
    values = [_signed(inputs, price) for price in grid]
    crossings = [(grid[i], grid[i + 1], values[i], values[i + 1]) for i in range(len(grid) - 1)
                 if (values[i] < 0) != (values[i + 1] < 0)]
    if not crossings:
        return GammaFlip(None, (low, high), f"Signed gamma does not change sign within {FLIP_RANGE:.0%} of the price.")
    a, b, fa, _ = min(crossings, key=lambda c: min(abs(c[0] - spot), abs(c[1] - spot)))
    for _ in range(30):
        middle = (a + b) / 2
        value = _signed(inputs, middle)
        if (value < 0) == (fa < 0):
            a, fa = middle, value
        else:
            b = middle
        if b - a < 0.005:
            break
    return GammaFlip(round((a + b) / 2, 2), (low, high), "Model estimate: " + DEALER_SIDE)


def _inputs(chains, root, spot, now, closes) -> list[tuple[float, float, float, float]]:
    """(sign, strike, iv, years) x weight per contract that can carry gamma near ``spot``."""
    out = []
    for chain in chains:
        for c in chain.contracts:
            iv = c.iv or c.iv_smoothed
            years = years_left(c.expiration, c.root, now, closes)
            if (c.root != root or iv is None or years <= 0 or c.multiplier is None or not c.open_interest
                    or abs(log(c.strike / spot)) > FLIP_STRIKES):
                continue
            out.append((1.0 if c.option_type == "call" else -1.0, c.strike, iv, years, c.open_interest * c.multiplier))
    return out


def _signed(inputs, price: float) -> float:
    total = 0.0
    for sign, strike, iv, years, weight in inputs:
        gamma = bs_gamma(price, strike, years, iv)
        if gamma is not None:
            total += sign * gamma * weight
    return total * price * price * 0.01


# ---------------------------------------------------------------------------
# Max pain (inferred, C4.7)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MaxPain:
    price: float  # the strike
    expiration: date
    payout: float  # what the open contracts would pay at that strike, dollars


def max_pain_missing(chain: OptionChain, root: str | None = None) -> int:
    """Count relevant contracts whose payout weight is unknown, not zero."""
    root = root or primary_root(chain.underlying)
    return sum(c.open_interest is None or (c.open_interest > 0 and c.multiplier is None)
               for c in chain.contracts if c.root == root)


def max_pain(chain: OptionChain, root: str | None = None) -> MaxPain | None:
    """The listed strike of one expiration where its open contracts would pay their holders
    least if the underlying settled there: for each candidate strike K, call open interest
    pays (K - strike) below it and put open interest (strike - K) above it, times the
    contracts' size. A tie goes to the lower strike. None without any open interest.

    Arithmetic on observed open interest; the idea that price drifts to it is not
    established, so it is *inferred* wherever it is shown.
    """
    root = root or primary_root(chain.underlying)
    if max_pain_missing(chain, root):
        return None  # A partial chain can put the minimum at a different strike.
    calls: dict[float, float] = {}
    puts: dict[float, float] = {}
    for contract in chain.contracts:
        if contract.root != root or not contract.open_interest or contract.multiplier is None:
            continue
        side = calls if contract.option_type == "call" else puts
        side[contract.strike] = side.get(contract.strike, 0) + contract.open_interest * contract.multiplier
    if not calls and not puts:
        return None
    strikes = sorted({c.strike for c in chain.contracts if c.root == root})

    def payout(settle: float) -> float:
        return (sum(size * (settle - strike) for strike, size in calls.items() if strike < settle)
                + sum(size * (strike - settle) for strike, size in puts.items() if strike > settle))

    best = min(strikes, key=lambda strike: (payout(strike), strike))
    return MaxPain(best, chain.expiration, payout(best))


# ---------------------------------------------------------------------------
# Chart levels (C4.4)
# ---------------------------------------------------------------------------

WALL_KINDS = {
    ("oi", "call"): ("call_wall", "Call wall"), ("oi", "put"): ("put_wall", "Put wall"),
    ("volume", "call"): ("call_volume_wall", "Call vol wall"), ("volume", "put"): ("put_volume_wall", "Put vol wall"),
}
RANK_NAMES = {"oi": "OI", "volume": "Vol", "gamma": "Gamma"}


def chart_levels(found: Positioning, measure: str, signed: bool = False, flip: GammaFlip | None = None,
                 pain: MaxPain | None = None) -> list[Level]:
    """The strikes the chart draws for ``measure``: the call and put walls (open interest's, or
    volume's in volume mode), then the ``TOP`` strikes by the measure on both sides together,
    leaving out the walls' strikes, the gamma flip when there is one, and max pain (inferred)
    when it is given.

    Open-interest levels hold still through a session. Volume and gamma ones can
    move (volume trades, gamma follows the price), so they are ``developing``.
    """
    if measure not in MEASURES:
        raise ValueError(f"unknown measure {measure!r}")
    walls_by = "volume" if measure == "volume" else "oi"
    levels: list[Level] = []
    taken: set[float] = set()
    for side in ("call", "put"):
        row = found.wall(walls_by, side)
        if row is not None:  # both walls on one strike are two members of one zone
            kind, label = WALL_KINDS[(walls_by, side)]
            levels.append(Level(kind, label, row.strike, "calculated", None, "tradier", developing=walls_by == "volume"))
            taken.add(row.strike)
    assumed = signed and measure == "gamma"
    for index, row in enumerate(found.ranked(measure, None, signed)[:TOP], 1):
        if row.strike in taken:
            continue
        levels.append(Level(f"options_{measure}", f"{RANK_NAMES[measure]} #{index}", row.strike,
                            "assumed" if assumed else "calculated", None, "tradier", developing=measure != "oi"))
        taken.add(row.strike)
    if flip is not None and flip.price is not None:
        levels.append(Level("gamma_flip", "Gamma flip", flip.price, "assumed", None, "tradier", developing=True))
    if pain is not None:
        # Open interest holds still through a session, so max pain does too.
        levels.append(Level("max_pain", "Max pain", pain.price, "inferred", None, "tradier"))
    return levels


# ---------------------------------------------------------------------------
# Which expirations a scope covers
# ---------------------------------------------------------------------------

SCOPES = ("nearest", "week", "all")
HORIZON_DAYS = 45


def scope_expirations(listed: Iterable[date], scope: str, now: datetime, root: str,
                      closes: Mapping[date, int | None] | None = None) -> list[date]:
    """The unexpired expirations a scope covers, within 45 days.

    *nearest*: the next to expire (0DTE when it is today's). *week*: those in
    the nearest one's Monday-to-Friday week. *all*: every one within 45 days.
    """
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r}")
    today = now.astimezone(ET).date()
    live = [d for d in unexpired(listed, root, now, closes) if d <= today + timedelta(days=HORIZON_DAYS)]
    if not live:
        return []
    if scope == "nearest":
        return live[:1]
    if scope == "week":
        friday = live[0] + timedelta(days=4 - live[0].weekday()) if live[0].weekday() <= 4 else live[0]
        return [d for d in live if d <= friday]
    return live
