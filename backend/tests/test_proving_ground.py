"""The paper proving ground: intake per source, the fixed bracket, the board and the PAPER label. No provider calls."""

from datetime import UTC, date, datetime
import json
from types import SimpleNamespace

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


def closed(source, days, pnl_2x=1.0):
    """Closed one-contract trades at a 2.00 entry: ``days`` is one list of net dollars per session."""
    return [{"source": source, "state": "closed", "day": f"d{d:04d}", "entry": 2.0, "contract": {"multiplier": 100},
             "pnl": float(pnl), "pnl_2x": pnl_2x, "reason": "time_stop"} for d, day in enumerate(days) for pnl in day]


def test_board_graduation_and_the_paper_label(tmp_path):
    store = pg.Store(tmp_path / "pg.sqlite3")
    for i in range(40):  # 20 sessions, two trades each: +30 and -10 or +10, so the sessions differ but all are green
        store.add("radar_setup", f"e{i}", f"2026-11-{i // 2 + 1:02d}", "MU", "up", contract("MU1"), 0.0)
        store.update(i + 1, "pending", state="closed", entry=2.0, pnl=30.0 if i % 2 else (-10.0 if i % 4 else 10.0),
                     pnl_2x=1.0, reason="time_stop")
    board = {r["source"]: r for r in pg.board(store.trades())}
    row = board["radar_setup"]
    assert (row["closed"], row["pnl"], row["days"], row["reviewed_days"]) == (40, 600.0, 20, 20)
    assert row["graduated"] and row["status"] == "Graduated" and row["score"] > pg.GRADUATE_SCORE
    assert pg.board(store.trades())[0]["source"] == "radar_setup"
    assert pg.label("radar_setup", "Radar setup: MU", tmp_path / "pg.sqlite3") == "Radar setup: MU"
    assert pg.label("jo_morning", "x", tmp_path / "pg.sqlite3") == "PAPER · x"
    assert board["jo_morning"]["status"] == "PAPER · 0 of 20 days, 0 of 40 trades"
    assert pg.label("radar_setup", "x", tmp_path / "missing.sqlite3") == "PAPER · x"
    assert not (tmp_path / "missing.sqlite3").exists()


def test_a_green_record_is_not_enough_to_graduate():
    win = [[30.0, 10.0], [30.0, -10.0]] * 10  # 20 sessions, 40 trades, every session green
    assert pg.judge(closed("x", win))["graduated"]
    short = pg.judge(closed("x", win[:19] + [[]]))  # 19 sessions
    assert not short["graduated"] and short["status"] == "PAPER · 19 of 20 days, 38 of 40 trades"
    thin = pg.judge(closed("x", [[30.0], [20.0]] * 10))  # 20 sessions but 20 trades
    assert not thin["graduated"] and thin["status"] == "PAPER · 20 of 20 days, 20 of 40 trades"
    # The rule this replaced: 40 trades, net above zero. Green by a little on wide swings is what luck looks like.
    noisy = pg.judge(closed("x", [[40.0, 40.0], [-38.0, -38.0]] * 10))
    assert sum(t["pnl"] for t in closed("x", [[40.0, 40.0], [-38.0, -38.0]] * 10)) > 0
    assert not noisy["graduated"] and noisy["status"] == f"PAPER · score {noisy['score']:.1f} of 3.0, next look at day 30"
    # Forty trades in one morning are one session's evidence, not forty.
    assert not pg.judge(closed("x", [[30.0] * 40]))["graduated"]
    # Green ask in, bid out but red at twice the spread: not yet.
    wide = pg.judge(closed("x", win, pnl_2x=-1.0))
    assert not wide["graduated"] and wide["status"] == "PAPER · in the red at twice the spread"


def test_a_session_counts_only_once_it_is_over():
    """Codex on #907: the tenth session's first close must not be judged before its second."""
    trades = closed("x", [[30.0, 10.0], [30.0, -10.0]] * 10)
    last = trades[-1]["day"]
    assert not pg.judge(trades[:-1], today=last)["graduated"]  # day 20 is still open: 19 sessions count
    assert pg.judge(trades[:-1], today=last)["status"] == "PAPER · 19 of 20 days, 38 of 40 trades"
    assert pg.judge(trades, today="d9999")["graduated"]
    board = pg.board([{**t, "source": "radar_setup"} for t in trades], today=last)
    assert not next(r for r in board if r["source"] == "radar_setup")["graduated"]


def test_identical_sessions_score_by_their_sign():
    assert pg.judge(closed("x", [[40.0, 40.0]] * 20))["graduated"]
    assert pg.judge(closed("x", [[-40.0, -40.0]] * 20))["score"] == -99.0


def test_a_dear_contract_weighs_no_more_than_a_cheap_one():
    cheap = closed("x", [[30.0, 10.0], [30.0, -10.0]] * 10)
    dear = [{**t, "entry": 20.0, "pnl": t["pnl"] * 10} for t in cheap]  # the same percentages on a 20.00 contract
    assert abs(pg.judge(dear)["score"] - pg.judge(cheap)["score"]) < 0.5  # commissions aside, the same evidence


def test_the_record_is_judged_at_every_tenth_session_only():
    win = [[30.0, 10.0], [30.0, -10.0]] * 10
    bad = [[-30.0, -30.0]] * 9
    held = pg.judge(closed("x", win + bad))  # nine red sessions since the review at day 20: still on that review
    assert (held["days"], held["reviewed_days"], held["graduated"]) == (29, 20, True)
    dropped = pg.judge(closed("x", win + bad + [[-30.0, -30.0]]))  # the review at day 30 sees them
    assert (dropped["reviewed_days"], dropped["graduated"]) == (30, False)


def _sessions(rng, green: float, days: int) -> list[list[float]]:
    """Two bracket trades a session, +40 or -34 on a 2.00 contract; half the sessions both trades share one outcome."""
    out = []
    for _ in range(days):
        first = 40.0 if rng.random() < green else -34.0
        out.append([first, first if rng.random() < 0.5 else (40.0 if rng.random() < green else -34.0)])
    return out


def _first_graduation(sessions: list[list[float]]) -> int | None:
    trades = closed("x", sessions)
    for day in range(pg.REVIEW_DAYS, len(sessions) + 1, pg.REVIEW_DAYS):
        if pg.judge(trades[:2 * day])["graduated"]:
            return day
    return None


def test_break_even_sources_rarely_graduate_and_a_real_edge_does():
    """The bar holds for every source at once: break-even sources watched for a year of sessions. Adding a source
    without raising ``GRADUATE_SCORE`` fails here."""
    import random
    rng = random.Random(20261125)
    even = 34.0 / 74.0  # the green share at which +40 / -34 nets zero
    runs = 1000
    lucky = old_rule = 0
    for _ in range(runs):
        sessions = _sessions(rng, even, 250)
        lucky += _first_graduation(sessions) is not None
        old_rule += sum(sum(day) for day in sessions[:20]) > 0  # 40 trades, net above zero
    assert old_rule / runs > 0.4  # the rule this replaced: a coin flip
    assert 1 - (1 - lucky / runs) ** len(pg.SOURCES) <= 0.07  # any source of all of them, within the year (about 4.5% over many more runs)
    edge = [_first_graduation(_sessions(rng, 0.65, 120)) for _ in range(100)]
    assert sum(day is not None for day in edge) >= 90  # a source that is green 65% of the time gets through
    assert sorted(day or 999 for day in edge)[50] <= 60  # typically within 60 sessions


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
