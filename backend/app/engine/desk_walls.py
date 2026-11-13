"""The desk's walls (docs/copilot-lab.md § Walls): the Charts strike ladder's dealer-positioning read, cut down to what
the desk chart draws and the Chain tab's one-line read: put wall, call wall, gamma flip, max pain and the expected move
for one expiry (the nearest unless the Chain tab shows another).

No second model. Everything comes from ``options_feed.ladder`` (signed, on the assumed dealer side), the same call the
Charts ladder makes, so the two share one chain cache, one budget and one pacing: the desk reading it a minute after
Charts did reads nothing new. The stock's price is the chart feed's shared 15-second quote (as the Chain tab's). Never
Robinhood, never a ping, nothing written.

- **Assumed, never fact.** Gamma's sign rests on dealers being long calls and short puts; open interest does not say who
  holds a contract. The answer carries that sentence for the desk to show beside the numbers.
- **Stale or missing says so.** In the regular session a read older than ``STALE_S`` is ``stale`` (three missed
  minutes); the desk then draws nothing and greys the Chain read with its time. Outside the session today's last read
  stands (open interest changes overnight, and the feed drops a chain read on an earlier New York date).
"""
from __future__ import annotations

from datetime import date, datetime
import time

from app.engine.options_positioning import FLIP_SYMBOLS

REFRESH_SECONDS = 60  # as the Charts ladder: once a minute while the desk is visible
STALE_S = 180  # in the session, a read older than this is not shown on the chart

NAMES = {"put_wall": "Put wall", "call_wall": "Call wall", "gamma_flip": "Gamma flip", "max_pain": "Max pain"}
HINTS = {
    "call_wall": "Call wall: the strike with the most call open interest in this expiry; often acts as a ceiling.",
    "put_wall": "Put wall: the strike with the most put open interest in this expiry; often acts as a floor.",
    "gamma_flip": ("Gamma flip: where dealer gamma is modelled to change sign. Above it hedging tends to damp moves, below "
                   "it to speed them up. A model estimate on an assumed dealer side."),
    "max_pain": ("Max pain: the strike where this expiry's open contracts would pay their holders least. Arithmetic on open "
                 "interest; that price drifts there is folklore, so it is a reference, not a target."),
}
EXPECTED_HINT = "Expected move: what the at-the-money straddle prices for this expiry, either way. A model estimate, not a forecast."
ASSUMPTION = ("Dealer side assumed: dealers long calls and short puts. Open interest does not say who holds a contract, "
              "so the walls are positioning, the flip and the gamma a model.")


def summary(ladder: dict, *, now: float, live_session: bool, simulated: bool = False) -> dict:
    """The ladder's answer cut to the desk's lines: each level (name, price, plain-words hint), the expected-move band and
    whether the read is fresh enough to draw."""
    state = ladder.get("state")
    expirations = ladder.get("expirations") or []
    base = {"symbol": ladder.get("symbol"), "expiration": expirations[0] if len(expirations) == 1 else None,
            "spot": ladder.get("spot"), "fetched_at": ladder.get("fetched_at"), "age_s": None, "levels": [],
            "expected_move": None, "flip_note": None, "assumption": ASSUMPTION, "message": ladder.get("message"),
            "simulated": simulated, "refresh_seconds": REFRESH_SECONDS}
    if state != "ready":
        return {**base, "state": "loading" if state == "loading" else "none" if state == "none" else "unavailable"}
    walls = ladder.get("walls") or {}
    flip = ladder.get("flip")
    pain = ladder.get("max_pain")
    found = {"put_wall": walls.get("put_oi"), "call_wall": walls.get("call_oi"),
             "gamma_flip": flip.get("price") if flip else None, "max_pain": pain.get("price") if pain else None}
    levels = [{"kind": kind, "name": NAMES[kind], "price": value, "hint": HINTS[kind]}
              for kind, value in found.items() if isinstance(value, (int, float))]
    spot = ladder.get("spot")
    move = ladder.get("expected_move") or {}
    band = None
    if move.get("state") == "ready" and isinstance(move.get("move"), (int, float)) and isinstance(spot, (int, float)):
        band = {"move": round(move["move"], 2), "percent": move.get("percent"), "low": round(spot - move["move"], 2),
                "high": round(spot + move["move"], 2), "expiration": move.get("expiration"), "hint": EXPECTED_HINT}
    flip_note = None
    if flip is None:
        flip_note = ("No gamma flip without a current price." if ladder.get("symbol") in FLIP_SYMBOLS
                     else "The gamma flip is modelled on SPY, QQQ and SPX only.")
    elif flip.get("price") is None:
        flip_note = flip.get("note")
    fetched = ladder.get("fetched_at")
    age = max(now - fetched, 0) if isinstance(fetched, (int, float)) and not simulated else None
    stale = bool(live_session and age is not None and age > STALE_S)
    return {**base, "state": "stale" if stale else "ready", "age_s": int(age) if age is not None else None,
            "levels": levels, "expected_move": band, "flip_note": flip_note,
            "message": ladder.get("message") or ("The option chain could not be read again just now." if stale else None)}


def _live(symbol: str, expiration: date | None) -> dict:
    from app.engine import copilot_plans
    from app.engine.options_feed import options_feed
    last, _at, _issue = copilot_plans._quotes([symbol])
    return options_feed.ladder(symbol, "nearest", True, last.get(symbol), expiration)


class _FixtureClient:
    """SIMULATED: the copilot fixture's NBIS chains served as if read (``copilot_fixture.simulated_chains``)."""

    def __init__(self, chains: dict):
        self.chains = chains

    def expirations(self, symbol):
        return sorted(self.chains)

    def chain(self, symbol, expiration, wait=False):
        return self.chains[expiration]


class _FixtureCalendar:
    def hours(self, day):
        return {"status": "open", "open": 570, "close": 960}


def _fixture(symbol: str, expiration: date | None) -> dict:
    """SIMULATED: the ladder on the fixture's NBIS chains at its fixed price and time, through the same feed code."""
    from app.ai.copilot_fixture import AT, SESSION, simulated_chains
    from app.engine.options_feed import OptionsFeed
    if symbol != "NBIS":
        return {"symbol": symbol, "state": "unavailable", "expirations": [],
                "message": "The sandbox fixture has a simulated NBIS chain only."}
    at = datetime.fromisoformat(AT.replace("Z", "+00:00")).timestamp()
    feed = OptionsFeed(client=_FixtureClient(simulated_chains("NBIS", 94.35, date.fromisoformat(SESSION), walls=True)),
                       calendar=_FixtureCalendar(), clock=lambda: at, spawn=lambda work: None)
    return feed.ladder("NBIS", "nearest", True, 94.35, expiration)


def read(symbol: str, expiration: date | None = None, *, mode: str = "live", now: float | None = None, ladder=None) -> dict:
    """The walls for ``symbol``'s nearest expiry (or ``expiration`` when it is listed). ``mode``: the copilot's evidence
    (``live``; ``fixture`` reads the simulated NBIS chain; ``replay`` reads none)."""
    from app.engine.desk_chain import _session
    from app.engine.options_chain import _symbol
    now = time.time() if now is None else now
    symbol = (symbol or "").strip().upper()
    try:
        symbol = _symbol(symbol)
    except ValueError:
        return {"symbol": symbol, "state": "none", "levels": [], "expected_move": None, "assumption": ASSUMPTION,
                "message": f"{symbol!r} is not a ticker.", "refresh_seconds": REFRESH_SECONDS}
    if mode == "replay":
        return summary({"symbol": symbol, "state": "unavailable", "message": "Replay reads no live quotes."}, now=now, live_session=False)
    simulated = mode == "fixture"
    got = (ladder or (_fixture if simulated else _live))(symbol, expiration)
    phase, regular = ("closed", None) if simulated else _session(now)
    return summary(got, now=now, live_session=phase == "regular" and regular is not None, simulated=simulated)
