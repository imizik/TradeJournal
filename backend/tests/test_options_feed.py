"""The chart's option chains (C4.4, C4.5) and the implied move (T2.1), with a fake
chain client and a clock the tests move. No network.

The budget test is the C4.4 acceptance check: an hour of a chart polling every
15 seconds, its main symbol on the 45-day scope and two held symbols, the
ladder and the Forecast tab open, never needs more than the options budget of
30 requests in any minute.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.engine.chart_math import ET
from app.engine.options_chain import OptionsChainError
from app.engine.options_feed import FAST_TTL, LADDER_STRIKES, PER_PASS, SLOW_TTL, Layer, OptionsFeed
from app.engine.options_implied import straddle, targets
from app.engine.options_models import OptionChain, OptionContract

START = datetime(2026, 10, 5, 10, 0, tzinfo=ET)  # Monday


class Clock:
    def __init__(self, at: datetime = START):
        self.now = at.timestamp()

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Calendar:
    def hours(self, day):
        return {"status": "open", "open": 570, "close": 960} if day.weekday() < 5 else {"status": "closed", "open": None, "close": None}


def leg(underlying, expiration, strike, side, oi=100, volume=10, bid=1.0, ask=1.1, iv=0.2, quoted=None, root=None):
    root = root or underlying
    letter = "C" if side == "call" else "P"
    return OptionContract(f"{root}{expiration:%y%m%d}{letter}{int(strike * 1000):08d}", underlying, root, expiration, side,
                          float(strike), 100, bid, ask, None, None, None, volume, oi, quoted, quoted, None, iv, None,
                          None, None, None, None, None)


class FakeClient:
    """Lists expirations as Tradier did for SPY in October 2026 (dailies for two weeks, then
    Fridays) and Fridays only for anything but SPY and QQQ, and builds a small chain for each."""

    def __init__(self, clock: Clock, fail: str | None = None):
        self.clock = clock
        self.calls: list[tuple[float, str, str]] = []
        self.fail = fail
        self.chains: dict[tuple[str, date], list[OptionContract]] = {}

    def expirations(self, symbol, wait=False):
        self._call("list", symbol)
        today = datetime.fromtimestamp(self.clock(), ET).date()
        days = [today + timedelta(days=i) for i in range(0, 60)]
        daily = symbol in ("SPY", "QQQ")
        return [d for d in days if d.weekday() == 4 or (daily and d.weekday() < 5 and d < today + timedelta(days=14))]

    def chain(self, symbol, expiration, wait=False):
        self._call("chain", symbol)
        rows = self.chains.get((symbol, expiration)) or [
            leg(symbol, expiration, strike, side, oi=1000 + 10 * strike if side == "call" else 3000 - 10 * strike)
            for strike in range(90, 111) for side in ("call", "put")]
        return OptionChain(symbol, expiration, "tradier", datetime.fromtimestamp(self.clock(), timezone.utc), tuple(rows))

    def _call(self, kind, symbol):
        if self.fail:
            raise OptionsChainError("Option reads are pacing to stay within their data allowance.", self.fail)
        self.calls.append((self.clock(), kind, symbol))


def feed(clock=None, client=None):
    clock = clock or Clock()
    client = client or FakeClient(clock)
    return OptionsFeed(client=client, calendar=Calendar(), clock=clock, spawn=lambda work: work()), client, clock


# --- the chart layer -------------------------------------------------------


def test_the_layer_answers_from_memory_and_fills_in_over_a_few_polls():
    options, client, clock = feed()
    levels, info = options.chart("SPY", Layer("oi", "all"), 100.0)
    # Nothing was in memory: the background pass read the list and the first chains, and this answer says so.
    assert levels == [] and info["state"] == "loading" and info["message"] == f"Loaded {PER_PASS} of 14 expirations."
    assert len(client.calls) == 1 + PER_PASS
    for _ in range(2):
        clock.advance(15)
        levels, info = options.chart("SPY", Layer("oi", "all"), 100.0)
    assert info["state"] == "ready" and levels
    # Dailies through Oct 16, then the Fridays to Nov 13 (Nov 20 is past 45 days).
    assert info["expirations"] == [d.isoformat() for d in (*(date(2026, 10, d) for d in (5, 6, 7, 8, 9, 12, 13, 14, 15, 16, 23, 30)),
                                                          date(2026, 11, 6), date(2026, 11, 13))]
    assert info["scope_note"] == "Within 45 days: 14 expirations"
    shown = {level.price for level in levels}
    assert {row["strike"] for row in info["strikes"]} == shown
    wall = next(row for row in info["strikes"] if row["strike"] == next(level.price for level in levels if level.kind == "call_wall"))
    assert wall["call_oi_rank"] == 1 and wall["call_oi"] is not None


def test_a_held_symbol_reads_only_its_nearest_expiration():
    options, client, clock = feed()
    options.chart("QQQ", Layer("oi", "nearest"), 600.0)
    assert [kind for _, kind, _ in client.calls] == ["list", "chain"]
    _, info = options.chart("QQQ", Layer("oi", "nearest"), 600.0)
    assert info["expirations"] == ["2026-10-05"] and info["scope_note"] == "0DTE Oct 5"


def test_a_refused_read_keeps_the_older_copy_with_why_and_cools_down():
    options, client, clock = feed()
    options.chart("SPY", Layer("oi", "nearest"), 660.0)
    clock.advance(FAST_TTL + 1)
    client.fail = "rate_limited"
    levels, info = options.chart("SPY", Layer("oi", "nearest"), 660.0)
    assert levels and info["state"] == "ready"  # the copy a minute old still draws
    assert "pacing" in info["message"]
    client.fail = None
    clock.advance(30)
    options.chart("SPY", Layer("oi", "nearest"), 660.0)
    assert len(client.calls) == 2  # still cooling down: no read for a minute after a refusal
    clock.advance(31)
    options.chart("SPY", Layer("oi", "nearest"), 660.0)
    assert len(client.calls) == 3


def test_a_chain_read_on_an_earlier_new_york_date_is_not_used():
    options, client, clock = feed()
    options.chart("SPY", Layer("oi", "week"), 660.0)
    clock.advance(24 * 3600)  # Tuesday: yesterday's open interest is out of date
    client.fail = "provider_unavailable"
    levels, info = options.chart("SPY", Layer("oi", "week"), 660.0)
    assert levels == [] and info["state"] == "unavailable"


def test_the_layer_parses_its_query_and_refuses_anything_else():
    assert Layer.parse("gamma.all.1") == Layer("gamma", "all", True)
    for bad in ("oi.week", "delta.week.0", "oi.month.0", "oi.week.2"):
        with pytest.raises(ValueError):
            Layer.parse(bad)


def test_signed_gamma_on_spy_adds_the_flip_as_an_assumed_level():
    options, client, clock = feed()
    expiry = date(2026, 10, 5)
    # Calls above and puts below the price: signed gamma changes sign between them.
    client.chains[("SPY", expiry)] = [leg("SPY", expiry, 105, "call", oi=1000), leg("SPY", expiry, 95, "put", oi=1000)]
    options.chart("SPY", Layer("gamma", "nearest", True), 100.0)
    levels, info = options.chart("SPY", Layer("gamma", "nearest", True), 100.0)
    flip = next(level for level in levels if level.kind == "gamma_flip")
    assert flip.evidence == "assumed" and 95 < flip.price < 105
    assert info["flip"]["price"] == flip.price and "short puts" in info["flip"]["assumption"]


# --- the budget (C4.4 done-when) -------------------------------------------


def test_an_hour_of_polling_stays_inside_the_options_budget():
    options, client, clock = feed()
    end = clock() + 3600
    fresh_ages = []
    while clock() < end:
        # The workspace every 15 seconds: the main symbol on the 45-day scope, two held symbols at their nearest.
        options.chart("SPY", Layer("gamma", "all", True), 660.0)
        options.chart("QQQ", Layer("gamma", "nearest", True), 600.0)
        options.chart("IWM", Layer("gamma", "nearest", True), 240.0)
        if int(clock() - START.timestamp()) % 60 == 0:
            options.ladder("SPY", "all", True, 660.0)  # the ladder's own minute
            options.forecast("SPY", 660.0, {"date": "2026-10-28", "status": "confirmed"})
        if clock() - START.timestamp() > 120:
            chains = options._chains["SPY"]
            nearest = sorted(chains)[:3]
            fresh_ages.append(max(clock() - chains[d].fetched for d in nearest))
        clock.advance(15)
    times = [at for at, _, _ in client.calls]
    busiest = max(sum(1 for t in times if start <= t < start + 60) for start in times)
    assert busiest <= 30
    # After the first look, about ten a minute: three near chains each, the farther ones every ten minutes.
    steady = [t for t in times if t >= START.timestamp() + 600]
    assert len(steady) / ((end - START.timestamp() - 600) / 60) < 12
    # The nearest three expirations are never more than a minute and a poll old.
    assert max(fresh_ages) <= FAST_TTL + 15
    assert SLOW_TTL >= 600


# --- the ladder (C4.5) -----------------------------------------------------


def test_the_ladder_centres_on_the_price_and_reads_what_it_needs():
    options, client, clock = feed()
    expiry = date(2026, 10, 5)
    client.chains[("SPY", expiry)] = [leg("SPY", expiry, strike, side) for strike in range(500, 701) for side in ("call", "put")]
    ladder = options.ladder("SPY", "nearest", False, 600.2)
    strikes = [row["strike"] for row in ladder["rows"]]
    assert len(strikes) == 2 * LADDER_STRIKES + 1 and strikes[LADDER_STRIKES] == 600.0
    assert ladder["state"] == "ready" and ladder["walls"]["call_oi"] is not None
    row = ladder["rows"][LADDER_STRIKES]
    assert (row["call_oi"], row["put_oi"], row["call_volume"], row["put_volume"]) == (100, 100, 10, 10)
    assert row["gamma"] > 0 and ladder["flip"] is None


# --- the implied move (T2.1) -----------------------------------------------


EXPIRY = date(2026, 10, 9)
QUOTED = datetime(2026, 10, 5, 14, 0, tzinfo=timezone.utc)


def _chain(rows):
    return OptionChain("NVDA", EXPIRY, "tradier", QUOTED, tuple(rows))


def test_the_straddle_is_at_the_strike_nearest_the_price_with_both_legs():
    rows = [leg("NVDA", EXPIRY, 180, "call", bid=4.0, ask=4.2, iv=0.5, quoted=QUOTED),
            leg("NVDA", EXPIRY, 180, "put", bid=3.8, ask=4.0, iv=0.48, quoted=QUOTED - timedelta(minutes=2)),
            leg("NVDA", EXPIRY, 182.5, "call", bid=3.0, ask=3.1),  # nearer 182, but no put listed
            leg("NVDA", EXPIRY, 185, "call", bid=2.0, ask=2.1), leg("NVDA", EXPIRY, 185, "put", bid=5.9, ask=6.1)]
    move = straddle(_chain(rows), 182.0)
    # 180 is 2.00 away and 185 is 3.00 away; 182.5 has no put, so it is no straddle.
    assert move["state"] == "ready" and move["strike"] == 180
    # (4.0 + 4.2) / 2 + (3.8 + 4.0) / 2 = 4.1 + 3.9 = 8.00, which is 8 / 182 = 4.40% of the price.
    assert move["move"] == pytest.approx(8.0) and move["percent"] == pytest.approx(8 / 182)
    assert move["iv"] == pytest.approx(0.49)
    assert move["quoted_at"] == int((QUOTED - timedelta(minutes=2)).timestamp())  # the staler leg


def test_a_leg_without_a_bid_or_wider_than_its_price_gives_no_number():
    no_bid = [leg("NVDA", EXPIRY, 180, "call", bid=0.0, ask=0.3), leg("NVDA", EXPIRY, 180, "put", bid=3.8, ask=4.0)]
    refused = straddle(_chain(no_bid), 180.0)
    assert refused["state"] == "too_wide" and "no bid" in refused["reason"] and "move" not in refused
    wide = [leg("NVDA", EXPIRY, 180, "call", bid=1.0, ask=3.5), leg("NVDA", EXPIRY, 180, "put", bid=3.8, ask=4.0)]
    assert straddle(_chain(wide), 180.0)["state"] == "too_wide"


def test_the_earnings_expiration_is_the_first_one_after_the_report_date():
    listed = [date(2026, 10, d) for d in (5, 7, 9, 28, 30)]
    chosen = targets(listed, "NVDA", START, date(2026, 10, 28))
    # A report's time of day is unknown, so the expiration on the report date may close before it.
    assert chosen == {"nearest": date(2026, 10, 5), "friday": date(2026, 10, 9), "earnings": date(2026, 10, 30)}
    assert targets(listed, "NVDA", START, None)["earnings"] is None


def test_the_forecast_reads_each_expiration_once_and_tags_shared_ones():
    options, client, clock = feed()
    forecast = options.forecast("NVDA", 100.0, {"date": "2026-10-28", "status": "estimated", "label": "Q3"})
    assert forecast["state"] == "ready"
    # NVDA lists Fridays only here: the nearest expiration is the nearest Friday.
    assert [(m["tags"], m["expiration"]) for m in forecast["moves"]] == [(["nearest", "friday"], "2026-10-09"), (["earnings"], "2026-10-30")]
    assert all(m["state"] == "ready" for m in forecast["moves"])
    assert [kind for _, kind, _ in client.calls] == ["list", "chain", "chain"]
    options.forecast("NVDA", 100.0, None)
    assert len(client.calls) == 3  # cached for a minute
    assert options.forecast("NVDA", None, None)["state"] == "unavailable"
