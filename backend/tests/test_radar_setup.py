"""Radar setup cards: levels, the candidate contract, the record lines, the card text and the frozen row."""
from datetime import date, datetime, timezone
import json

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.engine import pretrade_check, radar_setup
from app.engine.options_models import OptionChain, OptionContract
from app.models import RadarSetup
from tests.test_radar_dip import dip_path, run

TODAY = date(2026, 11, 10)  # a Tuesday
NOW = datetime(2026, 11, 10, 14, 52, 30, tzinfo=timezone.utc)  # 9:52:30 AM ET


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


def reversal(direction="up", extreme=59.85, first=61.20) -> dict:
    """A hand-made gap_reversal event in the sibling rule's shape."""
    return {
        "event_id": f"rr0-2026-11-10-rev-nbis-{direction}-1", "session_date": "2026-11-10", "rule_version": "radar-reversal-v0",
        "kind": "gap_reversal", "direction": direction, "symbols": ["NBIS"], "first_seen_at": "2026-11-10T14:52:02.000Z",
        "summary": "NBIS reversing after a gap", "measures": {"last_price": first, "extreme_price": extreme},
        "evidence": [{"symbol": "NBIS", "pass_id": 8, "retrieved_at": "x", "last": 60.5, "change_pct": -3.0},
                     {"symbol": "SPY", "pass_id": 23, "retrieved_at": "x", "last": 500.0, "change_pct": 0.1},
                     {"symbol": "NBIS", "pass_id": 23, "retrieved_at": "x", "last": first, "change_pct": -1.0}],
    }


def contract(kind="call", strike=62.0, bid=2.10, ask=2.20, delta=0.36, oi=900, volume=300, expiration=date(2026, 11, 14)):
    return OptionContract(
        symbol=f"NBIS{expiration:%y%m%d}{kind[0].upper()}{round(strike * 1000):08d}", underlying="NBIS", root="NBIS",
        expiration=expiration, option_type=kind, strike=strike, multiplier=100, bid=bid, ask=ask, last=None, bid_size=10,
        ask_size=10, volume=volume, open_interest=oi, bid_time=datetime(2026, 11, 10, 14, 52, tzinfo=timezone.utc),
        ask_time=datetime(2026, 11, 10, 14, 52, tzinfo=timezone.utc), trade_time=None, iv=0.6, iv_smoothed=None,
        delta=delta, gamma=None, theta=None, vega=None, greeks_updated_at=None)


class FakeOptions:
    def __init__(self, contracts=(), expirations=(date(2026, 11, 12), date(2026, 11, 14)), fail=None):
        self.contracts, self.expirations_list, self.fail, self.calls = tuple(contracts), list(expirations), fail, []

    def expirations(self, symbol, wait=False, timeout=None):
        self.calls.append(("expirations", symbol, wait))
        if self.fail:
            raise self.fail
        return self.expirations_list

    def chain(self, symbol, expiration, wait=False, timeout=None):
        self.calls.append(("chain", symbol, expiration, wait))
        return OptionChain(underlying=symbol, expiration=expiration, provider="fake", fetched_at=NOW, contracts=self.contracts)


GOOD = [contract(), contract(strike=64.0, bid=1.0, ask=1.05, delta=0.25, oi=100),  # thin open interest
        contract(kind="put", strike=60.0, bid=1.9, ask=2.0, delta=-0.34)]


def rows_of(*specs):
    """``(side, opened 'HH:MM', pnl)`` → feature rows."""
    return [{"side": side, "opened_at": f"2026-10-01T{at}:00", "realized_pnl": pnl, "time_bucket": None}
            for side, at, pnl in specs]


@pytest.fixture
def feature_rows(monkeypatch):
    holder = {"rows": []}
    monkeypatch.setattr(pretrade_check, "build_feature_rows", lambda db: holder["rows"])
    return holder


# ------------------------------------------------------------------ switches


def test_kinds_and_switch(monkeypatch):
    assert radar_setup.is_setup({"kind": "dip_turn"}) and radar_setup.is_setup({"kind": "gap_reversal"})
    assert not radar_setup.is_setup({"kind": "relative_to_spy"})
    monkeypatch.delenv("RADAR_SETUP_CARDS", raising=False)
    assert not radar_setup.enabled()
    monkeypatch.setenv("RADAR_SETUP_CARDS", "true")
    assert radar_setup.enabled()
    monkeypatch.setenv("RADAR_SETUP_CARDS", "1")
    assert not radar_setup.enabled()


# ------------------------------------------------------------------ levels


def test_levels_for_a_real_dip_event_are_the_first_sighting_and_the_low_pass():
    [event] = run({"AAA": dip_path()})
    # Evidence: the low pass (id 11, 97.0) and the first sighting (id 17, 98.0); no extreme_price on dip events.
    assert radar_setup.levels(event) == {"entry": 98.0, "invalidation": 97.0, "risk_pct": pytest.approx(1.020, abs=1e-3)}


def test_levels_for_a_gap_reversal_use_the_extreme_price_both_ways():
    up = radar_setup.levels(reversal("up", extreme=59.85, first=61.20))
    assert (up["entry"], up["invalidation"], up["risk_pct"]) == (61.20, 59.85, pytest.approx(2.206, abs=1e-3))
    down = radar_setup.levels(reversal("down", extreme=63.0, first=61.20))
    assert (down["entry"], down["invalidation"]) == (61.20, 63.0)


def test_levels_fall_back_to_the_evidence_extreme_without_extreme_price():
    event = reversal("up")
    del event["measures"]["extreme_price"]
    assert radar_setup.levels(event)["invalidation"] == 60.5


@pytest.mark.parametrize("direction,extreme", [("up", 61.20), ("up", 62.0), ("down", 61.20), ("down", 60.0)])
def test_levels_none_when_the_level_is_on_the_wrong_side(direction, extreme):
    assert radar_setup.levels(reversal(direction, extreme=extreme)) is None


# ------------------------------------------------------------------ the contract


def test_pick_contract_takes_the_liquid_call_for_up_and_put_for_down_in_two_reads():
    options = FakeOptions(GOOD)
    picked = radar_setup.pick_contract("NBIS", "up", TODAY, options=options)
    assert picked["symbol"] == "NBIS261114C00062000" and picked["option_type"] == "call"
    assert picked["mid"] == 2.15 and picked["spread_pct"] == 4.65
    for key in ("symbol", "multiplier", "bid", "ask", "bid_time", "ask_time", "option_type", "strike", "expiration", "delta"):
        assert key in picked
    # 11-12 is 2 days out (never 1-2); 11-14 is 4. No waiting for a budget slot.
    assert options.calls == [("expirations", "NBIS", False), ("chain", "NBIS", date(2026, 11, 14), False)]
    assert radar_setup.pick_contract("NBIS", "down", TODAY, options=FakeOptions(GOOD))["option_type"] == "put"


def test_pick_contract_none_when_nothing_is_liquid_or_the_reader_fails():
    wide = [contract(bid=1.0, ask=1.5), contract(volume=10)]
    assert radar_setup.pick_contract("NBIS", "up", TODAY, options=FakeOptions(wide)) is None
    assert radar_setup.pick_contract("NBIS", "up", TODAY, options=FakeOptions(GOOD, expirations=[date(2026, 12, 19)])) is None
    assert radar_setup.pick_contract("NBIS", "up", TODAY, options=FakeOptions(fail=RuntimeError("down"))) is None


# ------------------------------------------------------------------ records


def test_owner_record_prefers_the_first_hour(engine, feature_rows):
    first = [("call", "09:45", 1500.0)] * 6 + [("call", "10:29", -100.0)] * 2
    feature_rows["rows"] = rows_of(*first, ("call", "10:30", 50.0), ("call", "09:29", 50.0), ("put", "09:40", 10.0))
    with Session(engine) as db:
        assert radar_setup.owner_record(db, "up") == "Your first-hour calls: 6 of 8 green, +$8.8k"


def test_owner_record_falls_back_to_all_trades_then_none(engine, feature_rows):
    feature_rows["rows"] = rows_of(*[("put", "13:00", -100.0)] * 7, ("put", "09:31", 50.0), ("put", "11:00", None))
    with Session(engine) as db:
        assert radar_setup.owner_record(db, "down") == "Your puts: 1 of 8 green, −$650"
        assert radar_setup.owner_record(db, "up") is None


def test_owner_record_never_raises(engine, monkeypatch):
    def boom(db):
        raise RuntimeError("db")
    monkeypatch.setattr(pretrade_check, "build_feature_rows", boom)
    with Session(engine) as db:
        assert radar_setup.owner_record(db, "up") is None


def _setup_row(i, pnl, kind="gap_reversal", direction="up", state="closed"):
    return RadarSetup(event_id=f"e{i}", session_date="2026-11-01", rule_version="v", kind=kind, symbol="NBIS",
                      direction=direction, entry=10, invalidation=9, paper_state=state, paper_pnl=pnl)


def test_paper_record_needs_five_closed(engine):
    with Session(engine) as db:
        db.add_all([_setup_row(i, p) for i, p in enumerate([100.0, 200.0, -30.0, 70.0])]
                   + [_setup_row(10, 500.0, state="open"), _setup_row(11, 500.0, direction="down"),
                      _setup_row(12, 500.0, kind="dip_turn")])
        db.commit()
        assert radar_setup.paper_record(db, "gap_reversal", "up") is None
        db.add(_setup_row(5, 0.0))
        db.commit()
        assert radar_setup.paper_record(db, "gap_reversal", "up") == "Paper record for this setup: 3 of 5 green, +$340"


# ------------------------------------------------------------------ the card


def _card_row(event, contract_dict=None, record=None):
    lv = radar_setup.levels(event)
    return RadarSetup(event_id=event["event_id"], session_date="2026-11-10", rule_version="v", kind=event["kind"],
                      symbol=event["symbols"][0], direction=event["direction"], entry=lv["entry"],
                      invalidation=lv["invalidation"], record_text=record,
                      contract_json=json.dumps(contract_dict) if contract_dict else None)


def test_card_text_gap_reversal_up_with_contract_record_and_paper():
    event = reversal("up")
    picked = radar_setup.pick_contract("NBIS", "up", TODAY, options=FakeOptions(GOOD))
    title, body = radar_setup.card_text(event, _card_row(event, picked, "Your first-hour calls: 33 of 45 green, +$8.7k"),
                                        "Paper record for this setup: 7 of 12 green, +$340")
    assert title == "Radar setup: NBIS reversing up after a gap down"
    assert body == ("In near 61.20 · out below 59.85 (−2.2%)\n"
                    "Candidate: NBIS Nov 14 62C · 2.10 × 2.20 (4.7% wide) · Δ0.36\n"
                    "Your first-hour calls: 33 of 45 green, +$8.7k\n"
                    "Paper record for this setup: 7 of 12 green, +$340\n"
                    "NBIS reversing after a gap · 9:52 AM ET")


def test_card_text_gap_reversal_down_without_contract_or_record():
    event = reversal("down", extreme=63.0)
    title, body = radar_setup.card_text(event, _card_row(event))
    assert title == "Radar setup: NBIS reversing down after a gap up"
    assert body == ("In near 61.20 · out above 63.00 (+2.9%)\n"
                    "No liquid contract found.\n"
                    "NBIS reversing after a gap · 9:52 AM ET")


def test_card_text_dip_turn_with_a_put_style_delta_and_never_says_buy():
    [event] = run({"AAA": dip_path()})
    title, body = radar_setup.card_text(event, _card_row(event))
    assert title == "Radar setup: AAA dip turning up"
    assert body.splitlines()[0] == "In near 98.00 · out below 97.00 (−1.0%)"
    assert body.splitlines()[-1].endswith(" · 9:46 AM ET")
    put = radar_setup.pick_contract("NBIS", "down", TODAY, options=FakeOptions(GOOD))
    _, body = radar_setup.card_text(reversal("down", 63.0), _card_row(reversal("down", 63.0), put))
    assert "Candidate: NBIS Nov 14 60P · 1.90 × 2.00 (5.1% wide) · Δ−0.34" in body
    assert "buy" not in body.lower()


# ------------------------------------------------------------------ build


def test_build_freezes_one_row_per_event(engine, feature_rows):
    feature_rows["rows"] = rows_of(*[("call", "09:45", 100.0)] * 8)
    options = FakeOptions(GOOD)
    with Session(engine) as db:
        row = radar_setup.build(db, reversal("up"), now=NOW, options=options)
        assert (row.kind, row.symbol, row.direction, row.entry, row.invalidation) == ("gap_reversal", "NBIS", "up", 61.20, 59.85)
        assert row.paper_state == "pending" and row.plan_state == "none"
        assert row.created_at == datetime(2026, 11, 10, 14, 52, 30) and row.created_at.tzinfo is None
        assert row.session_date == "2026-11-10" and row.rule_version == "radar-reversal-v0"
        assert row.record_text == "Your first-hour calls: 8 of 8 green, +$800"
        frozen = json.loads(row.contract_json)
        assert {"symbol", "multiplier", "bid", "ask", "bid_time", "ask_time", "option_type", "strike", "expiration",
                "delta", "mid", "spread_pct"} <= set(frozen)
        assert frozen["symbol"] == "NBIS261114C00062000" and frozen["multiplier"] == 100
        # A second build changes nothing and costs no option reads.
        feature_rows["rows"] = []
        again = radar_setup.build(db, reversal("up"), now=NOW, options=FakeOptions(fail=RuntimeError("no")))
        assert again.id == row.id and again.record_text == row.record_text
        assert len(db.exec(select(RadarSetup)).all()) == 1


def test_build_without_a_contract_or_levels(engine, feature_rows):
    with Session(engine) as db:
        row = radar_setup.build(db, reversal("down", extreme=63.0), now=NOW, options=FakeOptions(fail=RuntimeError("x")))
        assert row.paper_state == "none" and row.contract_json is None and row.record_text is None
        assert radar_setup.build(db, reversal("up", extreme=62.0), now=NOW, options=FakeOptions(GOOD)) is None
        assert len(db.exec(select(RadarSetup)).all()) == 1


def test_build_returns_the_row_another_writer_saved_first(engine, feature_rows, monkeypatch):
    event = reversal("up")
    with Session(engine) as other:
        other.add(_card_row(event, record="theirs"))
        other.commit()
    real = radar_setup._existing
    calls = []

    def miss_first(db, event_id):
        calls.append(event_id)
        return None if len(calls) == 1 else real(db, event_id)
    monkeypatch.setattr(radar_setup, "_existing", miss_first)
    with Session(engine) as db:
        row = radar_setup.build(db, event, now=NOW, options=FakeOptions(GOOD))
        assert row.record_text == "theirs" and len(db.exec(select(RadarSetup)).all()) == 1


def test_a_card_never_picks_a_same_day_expiry_and_takes_the_nearest_three_to_ten_days_out():
    from app.engine import scanner_rules
    listed = [TODAY, date(2026, 11, 11), date(2026, 11, 12), date(2026, 11, 13), date(2026, 11, 20), date(2026, 11, 27)]
    assert radar_setup.card_expiration(listed, TODAY) == date(2026, 11, 13)  # 3 days out; today, 1 and 2 days are skipped
    assert radar_setup.card_expiration([TODAY, date(2026, 11, 20)], TODAY) == date(2026, 11, 20)  # 10 days out
    assert radar_setup.card_expiration([TODAY, date(2026, 11, 21)], TODAY) is None  # 11 days out
    assert scanner_rules.pick_expiration(listed, TODAY) == TODAY  # the scanner's frozen rule is untouched
    options = FakeOptions(GOOD, expirations=listed)
    radar_setup.pick_contract("NBIS", "up", TODAY, options=options)
    assert options.calls[-1] == ("chain", "NBIS", date(2026, 11, 13), False)
