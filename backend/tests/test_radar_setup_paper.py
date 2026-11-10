"""The paper book behind every Radar setup card (engine/radar_setup_paper.py): fake quotes and clock, a real temp store."""
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.engine import radar_setup_paper as paper
from app.engine.chart_math import ET
from app.engine.radar_setup_paper import HOLD_MINUTES, SetupPaper, scorecard
from app.engine.radar_store import RadarStore
from app.engine.tradier import TradierError, TradierQuote
from app.models import RadarSetup

DAY = "2026-11-10"
OCC = "NBIS261120C00100000"
CARD = datetime(2026, 11, 10, 10, 0, tzinfo=ET).timestamp()  # the card, 10:00 New York
CLOSE = datetime(2026, 11, 10, 16, 0, tzinfo=ET).timestamp()


def at(minutes: float) -> float:
    return CARD + minutes * 60


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class Quotes:
    """Fake option quotes: ``book[occ] = (bid, ask, quoted_at)``; records each request."""

    def __init__(self):
        self.book, self.calls, self.fail = {}, [], False

    def set(self, bid, ask, quoted_at, occ=OCC):
        self.book[occ] = (bid, ask, quoted_at)

    def __call__(self, symbols):
        self.calls.append(list(symbols))
        if self.fail:
            raise TradierError("429")
        return {s: TradierQuote(symbol=s, bid=b, ask=a, bid_date=int(t * 1000), ask_date=int(t * 1000))
                for s in symbols if s in self.book for b, a, t in [self.book[s]]}


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def store(tmp_path):
    return RadarStore(tmp_path / "radar.sqlite")


def record(store, minutes: float, last: float, low: float, high: float, symbol="NBIS", session=DAY):
    t = at(minutes)
    store.append_pass({"session_date": session, "started_at": _iso(t), "finished_at": _iso(t), "universe_version": "u1",
                       "status": "ok", "symbols_requested": 1, "symbols_returned": 1, "unmatched": [],
                       "requests_used": 1, "error": None, "skip_reason": None},
                      [{"symbol": symbol, "last": last, "prev_close": 100.0, "open": 100.0, "high": high, "low": low,
                        "volume": 1000, "bid": last, "ask": last, "trade_time_ms": int(t * 1000), "retrieved_at": _iso(t)}])


def card(engine, *, direction="up", entry=100.0, invalidation=98.0, contract=True, session=DAY, kind="dip_turn",
         plan_state="none") -> RadarSetup:
    row = RadarSetup(event_id=f"ev-{kind}-{direction}-{datetime.now().timestamp()}", session_date=session,
                     rule_version="rd0", kind=kind, symbol="NBIS", direction=direction, entry=entry,
                     invalidation=invalidation, plan_state=plan_state,
                     contract_json=json.dumps({"symbol": OCC, "multiplier": 100, "bid": 1.9, "ask": 2.0}) if contract else None,
                     created_at=datetime.fromtimestamp(CARD, UTC).replace(tzinfo=None),
                     paper_state="pending" if contract else "none")
    with Session(engine) as db:
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def get(engine, row) -> RadarSetup:
    with Session(engine) as db:
        return db.get(RadarSetup, row.id)


def book(engine, store, clock, quotes):
    return SetupPaper(engine, store, quotes=quotes, clock=clock)


def opened(engine, store, *, direction="up", invalidation=98.0):
    """A card entered at 2.00 one minute after it was made."""
    clock, quotes = Clock(at(1)), Quotes()
    row = card(engine, direction=direction, invalidation=invalidation)
    quotes.set(1.9, 2.0, at(0.5))
    book(engine, store, clock, quotes).step(DAY, CLOSE)
    assert get(engine, row).paper_state == "open"
    return row, clock, quotes


def test_entry_on_a_fresh_quote_not_a_stale_one(engine, store):
    row, clock, quotes = card(engine), Clock(at(0.5)), Quotes()
    quotes.set(1.8, 1.95, at(-0.1))  # quoted before the card
    book(engine, store, clock, quotes).step(DAY, CLOSE)
    assert get(engine, row).paper_state == "pending"
    quotes.set(1.9, 2.0, at(0.7))
    clock.now = at(1)
    book(engine, store, clock, quotes).step(DAY, CLOSE)
    got = get(engine, row)
    assert (got.paper_state, got.paper_entry_price) == ("open", 2.0)
    assert got.paper_entry_at == datetime.fromtimestamp(at(1), UTC).replace(tzinfo=None)


def test_unresolved_after_two_minutes_without_a_fresh_quote(engine, store):
    row, clock, quotes = card(engine), Clock(at(2.5)), Quotes()
    quotes.set(1.9, 2.0, at(2.2))
    book(engine, store, clock, quotes).step(DAY, CLOSE)
    got = get(engine, row)
    assert got.paper_state == "unresolved" and "2 minutes" in got.paper_note
    assert quotes.calls == []


def test_invalidation_by_last_then_exit_waits_for_a_fresh_quote(engine, store):
    record(store, -1, 98.5, 97.0, 101.0)  # the day low already through the invalidation at card time
    row, clock, quotes = opened(engine, store)
    record(store, 2, 99.0, 97.0, 101.0)
    clock.now = at(2.1)
    book(engine, store, clock, quotes).step(DAY, CLOSE)
    assert get(engine, row).paper_state == "open" and len(quotes.calls) == 1  # no condition yet: no quote request
    record(store, 3, 97.9, 97.0, 101.0)  # last through 98
    clock.now = at(3.1)
    quotes.set(1.4, 1.5, at(2.9))  # quoted before the condition: stale
    book(engine, store, clock, quotes).step(DAY, CLOSE)
    assert get(engine, row).paper_state == "open"
    quotes.set(1.4, 1.5, at(3.5))
    clock.now = at(4)
    book(engine, store, clock, quotes).step(DAY, CLOSE)
    got = get(engine, row)
    assert (got.paper_state, got.paper_exit_reason, got.paper_exit_price) == ("closed", "invalidation", 1.4)
    assert got.paper_pnl == round((1.4 - 2.0) * 100 - 1.30, 2)


def test_pre_existing_day_low_does_not_invalidate_but_a_new_one_does(engine, store):
    record(store, -1, 98.5, 97.0, 101.0)
    row, clock, quotes = opened(engine, store)
    record(store, 2, 98.4, 97.0, 101.0)  # same day low as at the card: not new
    quotes.set(2.4, 2.5, at(2.5))
    clock.now = at(2.6)
    book(engine, store, clock, quotes).step(DAY, CLOSE)
    assert get(engine, row).paper_state == "open"
    record(store, 3, 98.3, 96.8, 101.0)  # a new low after the card, through 98, while last stays above
    quotes.set(2.2, 2.3, at(3.5))
    clock.now = at(3.6)
    book(engine, store, clock, quotes).step(DAY, CLOSE)
    got = get(engine, row)
    assert (got.paper_state, got.paper_exit_reason, got.paper_exit_price) == ("closed", "invalidation", 2.2)
    assert got.paper_pnl == round(0.2 * 100 - 1.30, 2)


def test_down_card_invalidates_on_a_new_day_high(engine, store):
    record(store, -1, 101.5, 97.0, 103.0)
    row, clock, quotes = opened(engine, store, direction="down", invalidation=102.0)
    record(store, 2, 101.8, 97.0, 103.0)  # day high existed already
    quotes.set(2.4, 2.5, at(2.5))
    clock.now = at(2.6)
    book(engine, store, clock, quotes).step(DAY, CLOSE)
    assert get(engine, row).paper_state == "open"
    record(store, 3, 101.9, 97.0, 103.2)
    quotes.set(1.0, 1.1, at(3.5))
    clock.now = at(3.6)
    book(engine, store, clock, quotes).step(DAY, CLOSE)
    got = get(engine, row)
    assert (got.paper_state, got.paper_exit_reason) == ("closed", "invalidation")


def test_down_card_invalidates_on_last(engine, store):
    row, clock, quotes = opened(engine, store, direction="down", invalidation=102.0)
    record(store, 5, 102.0, 99.0, 102.0)
    quotes.set(1.0, 1.1, at(5.5))
    clock.now = at(5.6)
    book(engine, store, clock, quotes).step(DAY, CLOSE)
    assert get(engine, row).paper_exit_reason == "invalidation"


def test_time_stop(engine, store):
    row, clock, quotes = opened(engine, store)
    record(store, 30, 101.0, 99.0, 102.0)
    quotes.set(2.9, 3.0, at(1 + HOLD_MINUTES - 1))
    clock.now = at(1 + HOLD_MINUTES) - 1
    book(engine, store, clock, quotes).step(DAY, CLOSE)
    assert get(engine, row).paper_state == "open" and len(quotes.calls) == 1  # no condition, no quote request
    quotes.set(2.9, 3.0, at(1 + HOLD_MINUTES) + 5)
    clock.now = at(1 + HOLD_MINUTES) + 10
    book(engine, store, clock, quotes).step(DAY, CLOSE)
    got = get(engine, row)
    assert (got.paper_state, got.paper_exit_reason, got.paper_pnl) == ("closed", "time_stop", round(90 - 1.30, 2))


def test_session_close_fills_on_a_later_pass_inside_the_flat_window(engine, store):
    row, clock, quotes = opened(engine, store)
    close = at(30)  # an early close half an hour after the card
    flat = close - paper.FLAT_MINUTES * 60
    quotes.set(2.5, 2.6, flat - 30)
    clock.now = flat - 10  # before the flat time: no condition, no request
    book(engine, store, clock, quotes).step(DAY, close)
    assert get(engine, row).paper_state == "open" and len(quotes.calls) == 1
    clock.now = flat + 10  # condition met, but the quote is older than it
    book(engine, store, clock, quotes).step(DAY, close)
    assert get(engine, row).paper_state == "open"
    quotes.set(2.5, 2.6, flat + 70)
    clock.now = flat + 80  # the next pass, still minutes before the close
    book(engine, store, clock, quotes).step(DAY, close)
    got = get(engine, row)
    assert (got.paper_state, got.paper_exit_reason, got.paper_exit_price) == ("closed", "session_close", 2.5)


def test_open_card_without_a_fresh_quote_by_the_close_is_unresolved_next_session(engine, store):
    row, clock, quotes = opened(engine, store)
    close = at(30)
    quotes.set(2.5, 2.6, close - paper.FLAT_MINUTES * 60 - 30)  # never refreshed after the flat time
    for minute in range(paper.FLAT_MINUTES):
        clock.now = close - paper.FLAT_MINUTES * 60 + 10 + minute * 60
        book(engine, store, clock, quotes).step(DAY, close)
    assert get(engine, row).paper_state == "open"
    clock.now = at(24 * 60)
    book(engine, store, clock, quotes).step("2026-11-11", None)
    got = get(engine, row)
    assert got.paper_state == "unresolved" and "overnight" in got.paper_note


def test_no_session_close_exit_when_close_unknown(engine, store):
    row, clock, quotes = opened(engine, store)
    quotes.set(2.5, 2.6, at(29))
    clock.now = at(29.5)
    book(engine, store, clock, quotes).step(DAY, None)
    assert get(engine, row).paper_state == "open"


def test_a_row_from_an_earlier_session_is_unresolved(engine, store):
    row = card(engine, session="2026-11-09")
    quotes = Quotes()
    book(engine, store, Clock(at(1)), quotes).step(DAY, CLOSE)
    got = get(engine, row)
    assert got.paper_state == "unresolved" and "overnight" in got.paper_note
    assert quotes.calls == []


def test_no_provider_call_or_store_read_when_nothing_is_live(engine, store, monkeypatch):
    card(engine, contract=False)  # paper_state none
    quotes = Quotes()
    monkeypatch.setattr(store, "quotes", lambda **_: pytest.fail("store read"))
    book(engine, store, Clock(at(1)), quotes).step(DAY, CLOSE)
    assert quotes.calls == []


def test_a_quote_failure_leaves_state_unchanged(engine, store):
    row, clock, quotes = card(engine), Clock(at(0.5)), Quotes()
    quotes.fail = True
    book(engine, store, clock, quotes).step(DAY, CLOSE)  # never raises
    assert get(engine, row).paper_state == "pending" and len(quotes.calls) == 1


def test_one_batched_request_for_all_live_rows(engine, store):
    card(engine), card(engine, kind="gap_reversal")
    quotes = Quotes()
    quotes.set(1.9, 2.0, at(0.5))
    book(engine, store, Clock(at(1)), quotes).step(DAY, CLOSE)
    assert quotes.calls == [[OCC]]
    with Session(engine) as db:
        assert {r.paper_state for r in db.exec(select(RadarSetup))} == {"open"}


def test_restart_mid_position_continues(engine, store):
    record(store, -1, 98.5, 97.0, 101.0)
    row, clock, quotes = opened(engine, store)
    record(store, 3, 97.5, 97.0, 101.0)  # invalidated while the process was down
    quotes.set(1.4, 1.5, at(4.5))
    clock.now = at(5)
    fresh = SetupPaper(engine, store, quotes=quotes, clock=clock)  # a new instance after a restart
    fresh.step(DAY, CLOSE)
    got = get(engine, row)
    assert (got.paper_state, got.paper_exit_reason, got.paper_entry_price) == ("closed", "invalidation", 2.0)
    before = len(quotes.calls)
    SetupPaper(engine, store, quotes=quotes, clock=clock).step(DAY, CLOSE)  # nothing repeats
    assert len(quotes.calls) == before and get(engine, row).paper_exit_at == got.paper_exit_at


def test_one_bad_row_does_not_stop_the_others(engine, store):
    bad = card(engine)
    with Session(engine) as db:
        r = db.get(RadarSetup, bad.id)
        r.contract_json = "{not json"
        db.add(r)
        db.commit()
    good, quotes = card(engine), Quotes()
    quotes.set(1.9, 2.0, at(0.5))
    book(engine, store, Clock(at(1)), quotes).step(DAY, CLOSE)
    assert get(engine, good).paper_state == "open" and get(engine, bad).paper_state == "pending"


def test_invalidation_at_ignores_rows_before_the_entry():
    rows = [{"retrieved_at": _iso(at(0.5)), "last": 97.0, "low": 97.0, "high": 101.0},
            {"retrieved_at": _iso(at(2)), "last": 99.0, "low": 97.0, "high": 101.0}]
    assert paper.invalidation_at("up", 98.0, at(0), at(1), rows) is None


def test_scorecard_counts(engine):
    card(engine, plan_state="planned")
    card(engine, contract=False)
    card(engine, direction="down", kind="gap_reversal")
    with Session(engine) as db:
        rows = list(db.exec(select(RadarSetup)))
        states = [("closed", 30.0), ("none", None), ("unresolved", None)]
        for r, (state, pnl) in zip(sorted(rows, key=lambda r: (r.kind, r.contract_json is None)), states):
            r.paper_state, r.paper_pnl = state, pnl
            db.add(r)
        db.commit()
        got = scorecard(db)
    assert got == [
        {"kind": "dip_turn", "direction": "up", "cards": 2, "with_contract": 1, "planned": 1, "paper_closed": 1,
         "paper_green": 1, "paper_pnl": 30.0, "unresolved": 0},
        {"kind": "gap_reversal", "direction": "down", "cards": 1, "with_contract": 1, "planned": 0, "paper_closed": 0,
         "paper_green": 0, "paper_pnl": 0.0, "unresolved": 1},
    ]
