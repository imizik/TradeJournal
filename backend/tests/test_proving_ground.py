"""The paper proving ground: intake per source, the fixed bracket, the board and the PAPER label. No provider calls."""

from datetime import UTC, date, datetime
import json
from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.engine import proving_ground as pg
from app.engine.chart_math import ET
from app.models import MorningBriefingPacket, MorningBriefingRecord, RadarSetup

DAY = date(2026, 11, 24)
HOURS = {"status": "open", "open": 570, "close": 960}


def et(hhmm: str) -> float:
    h, m = map(int, hhmm.split(":"))
    return datetime(DAY.year, DAY.month, DAY.day, h, m, tzinfo=ET).timestamp()


def quote(symbol, bid=None, ask=None, at=None, last=None, open_=None):
    ms = None if at is None else int(at * 1000)
    return SimpleNamespace(symbol=symbol, bid=bid, ask=ask, bid_date=ms, ask_date=ms, last=last,
                           raw={"open": open_} if open_ is not None else {})


def contract(symbol):
    return {"symbol": symbol, "expiration": "2026-11-28", "option_type": "call", "strike": 100.0, "multiplier": 100,
            "bid": 1.9, "ask": 2.0, "delta": 0.35}


class World:
    """A fake clock, calendar, quote book and contract picker around a real store and an in-memory journal."""

    def __init__(self, tmp_path):
        self.now = et("09:40")
        self.book: dict = {}
        self.picked: list = []
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)
        self.store = pg.Store(tmp_path / "pg.sqlite3")
        self.ground = pg.ProvingGround(self.engine, SimpleNamespace(hours=lambda day: HOURS), store=self.store,
                                       quotes=lambda symbols: {s: self.book[s] for s in symbols if s in self.book},
                                       pick=self.pick, clock=lambda: self.now)

    def pick(self, symbol, direction, today):
        self.picked.append((symbol, direction))
        return contract(f"{symbol}261128C00100000")

    def at(self, hhmm, **book):
        self.now = et(hhmm)
        self.book.update(book)
        self.ground._last_run = 0.0
        self.ground.run()
        assert self.ground.last_error is None
        return {(t["source"], t["symbol"]): t for t in self.store.trades()}


def test_the_bracket():
    row = {"entry": 2.0, "entry_at": et("10:00")}
    fresh = lambda bid: quote("X", bid=bid, ask=bid + 0.1, at=et("10:05"))  # noqa: E731
    assert pg.bracket(row, fresh(2.40), et("10:05"), et("16:00")) == "take_profit"
    assert pg.bracket(row, fresh(2.39), et("10:05"), et("16:00")) is None
    assert pg.bracket(row, fresh(1.70), et("10:05"), et("16:00")) == "stop"
    assert pg.bracket(row, quote("X", bid=1.0, ask=1.1, at=et("09:59")), et("10:05"), et("16:00")) is None  # stale: no price exit
    assert pg.bracket(row, None, et("11:00"), et("16:00")) == "time_stop"
    assert pg.bracket(row, None, et("15:55"), et("16:00")) == "time_stop"  # the earlier condition wins
    assert pg.bracket({**row, "entry_at": et("15:30")}, None, et("15:55"), et("16:00")) == "session_close"


def test_jo_direction_reads_bearish_words_only():
    assert pg.jo_direction({"entry_trigger": "Reclaim of 120 with volume", "what_matters": "AI capex"}) == "up"
    assert pg.jo_direction({"entry_trigger": "Puts on a break below 50", "what_matters": ""}) == "down"
    assert pg.jo_direction({"entry_trigger": "Fade the gap", "what_matters": ""}) == "down"


def test_the_open_window_rule_enters_and_takes_profit(tmp_path):
    w = World(tmp_path)
    assert w.at("09:44", MU=quote("MU", last=101, open_=100), NBIS=quote("NBIS", last=49, open_=50)) == {}
    rows = w.at("09:45")
    assert w.picked == [("MU", "up"), ("NBIS", "down")]
    assert {k: r["state"] for k, r in rows.items()} == {("open_window", "MU"): "pending", ("open_window", "NBIS"): "pending"}
    mu, nbis = "MU261128C00100000", "NBIS261128C00100000"
    rows = w.at("09:46", **{mu: quote(mu, 1.9, 2.0, et("09:46")), nbis: quote(nbis, 0.95, 1.0, et("09:46"))})
    assert (rows[("open_window", "MU")]["state"], rows[("open_window", "MU")]["entry"]) == ("open", 2.0)
    rows = w.at("09:47", **{mu: quote(mu, 2.45, 2.5, et("09:47")), nbis: quote(nbis, 0.84, 0.9, et("09:47"))})
    assert rows[("open_window", "MU")]["reason"] == "take_profit"
    assert rows[("open_window", "MU")]["pnl"] == round((2.45 - 2.0) * 100 - 1.3, 2)
    assert rows[("open_window", "NBIS")]["reason"] == "stop"
    w.at("09:48")
    assert len(w.picked) == 2  # one trade per symbol per day


def test_radar_cards_and_jo_picks_are_entered_once(tmp_path):
    w = World(tmp_path)
    with Session(w.engine) as db:
        db.add(RadarSetup(event_id="dip-1", session_date=DAY.isoformat(), rule_version="v1", kind="dip_turn", symbol="IREN",
                          direction="up", entry=10, invalidation=9.5, contract_json=json.dumps(contract("IREN1")),
                          created_at=datetime.fromtimestamp(et("09:50"), UTC).replace(tzinfo=None)))
        db.add(RadarSetup(event_id="dip-2", session_date=DAY.isoformat(), rule_version="v1", kind="dip_turn", symbol="HOOD",
                          direction="up", entry=10, invalidation=9.5, contract_json=None))
        packet = MorningBriefingPacket(operation_id="p", request_sha256="x", day=DAY, body_json="{}")
        db.add(packet)
        db.flush()
        picks = [{"symbol": "AMD", "status": "conditional", "entry_trigger": "Short a break below 200", "what_matters": ""},
                 {"symbol": "LLY", "status": "research_only", "entry_trigger": "", "what_matters": ""}]
        db.add(MorningBriefingRecord(packet_id=packet.id, operation_id="r", request_sha256="y",
                                     body_json=json.dumps({"opportunities": picks})))
        db.commit()
    w.book.update(MU=quote("MU", last=101, open_=100), NBIS=quote("NBIS", last=49, open_=50))
    rows = w.at("09:50")
    assert ("radar_setup", "IREN") in rows and ("radar_setup", "HOOD") not in rows
    assert ("jo_morning", "AMD") not in rows  # two picks a minute: MU and NBIS took them
    rows = w.at("09:51")
    assert rows[("jo_morning", "AMD")]["direction"] == "down" and ("jo_morning", "LLY") not in rows
    w.at("09:52")
    assert w.picked.count(("AMD", "down")) == 1


def test_anything_left_after_its_session_is_unresolved(tmp_path):
    w = World(tmp_path)
    w.store.add("open_window", "2026-11-23:MU", "2026-11-23", "MU", "up", contract("MU1"), et("09:45") - 86400)
    rows = w.at("08:00")
    assert rows[("open_window", "MU")]["state"] == "unresolved"


def test_board_graduation_and_the_paper_label(tmp_path):
    store = pg.Store(tmp_path / "pg.sqlite3")
    for i in range(40):
        store.add("radar_setup", f"e{i}", "2026-11-24", "MU", "up", contract("MU1"), 0.0)
        store.update(i + 1, "pending", state="closed", pnl=10.0 if i % 2 else -5.0, pnl_2x=1.0, reason="time_stop")
    board = {r["source"]: r for r in pg.board(store.trades())}
    assert (board["radar_setup"]["closed"], board["radar_setup"]["pnl"], board["radar_setup"]["graduated"]) == (40, 100.0, True)
    assert pg.board(store.trades())[0]["source"] == "radar_setup"
    assert pg.label("radar_setup", "Radar setup: MU", tmp_path / "pg.sqlite3") == "Radar setup: MU"
    assert pg.label("jo_morning", "x", tmp_path / "pg.sqlite3") == "PAPER · x"
    assert pg.label("radar_setup", "x", tmp_path / "missing.sqlite3") == "PAPER · x"
    assert not (tmp_path / "missing.sqlite3").exists()


@pytest.mark.parametrize("closed,pnl", [(39, 100.0), (40, 0.0)])
def test_no_graduation_short_of_forty_or_at_breakeven(tmp_path, closed, pnl):
    store = pg.Store(tmp_path / "pg.sqlite3")
    for i in range(closed):
        store.add("open_window", f"d{i}", "2026-11-24", "MU", "up", contract("MU1"), 0.0)
        store.update(i + 1, "pending", state="closed", pnl=pnl / closed, pnl_2x=0.0, reason="stop")
    assert not next(r for r in pg.board(store.trades()) if r["source"] == "open_window")["graduated"]


def test_an_entered_trade_with_no_exit_quote_closes_at_its_last_bid_next_session(tmp_path):
    w = World(tmp_path)
    c = "MU1"
    w.store.add("open_window", f"{DAY}:MU", DAY.isoformat(), "MU", "up", contract(c), et("09:45"))
    w.book.update(MU=quote("MU", last=100, open_=100), NBIS=quote("NBIS", last=50, open_=50))
    w.at("09:46", **{c: quote(c, 1.9, 2.0, et("09:46"))})
    w.at("09:50", **{c: quote(c, 1.8, 1.9, et("09:50"))})  # seen, no bracket hit
    w.book[c] = quote(c, 1.0, 1.1, et("09:50"))  # stale from here on: no fresh exit quote
    w.now = et("09:40") + 86400
    w.ground._last_run = 0.0
    w.ground.run()
    row = next(t for t in w.store.trades() if t["symbol"] == "MU" and t["source"] == "open_window" and t["day"] == DAY.isoformat())
    assert (row["state"], row["reason"], row["exit"]) == ("closed", "no_exit", 1.8)
    assert row["pnl"] == round((1.8 - 2.0) * 100 - 1.3, 2)
