"""Paper it on the desk's ideas (``app/engine/paper_book.py`` § Whose idea): every paper order records whose idea it was
(``mine``, ``copilot``, ``radar`` or ``scanner``) and the idea's id, through the same order path and the same fresh-quote
rule; the scorecard splits closed paper trades by source; the copilot's read shows the tag; Radar's and the scanner's
candidate contracts are named for Paper it. Invented numbers, no network."""

from datetime import UTC, datetime
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlmodel import select

from app.ai import copilot_paper_book
from app.database import get_session
from app.engine import paper_book
from app.models import PaperEvent
from app.routers import copilot_paper
from tests.test_paper_book import CALL, CLOSE, NOW, db, key, market, q  # noqa: F401 -- fixtures

OPEN = datetime(2026, 11, 13, 14, 30, tzinfo=UTC).timestamp()  # 09:30 New York


@pytest.fixture(autouse=True)
def session(monkeypatch, market):  # noqa: F811
    monkeypatch.setattr(paper_book, "_window", lambda now: ("regular", (int(OPEN), int(CLOSE))))
    paper_book._checks.clear()
    yield
    paper_book._checks.clear()


def buy(db, now=NOW, **extra):  # noqa: F811
    return paper_book.open_order(db, {"symbol": "NBIS", "instrument": "option", "option_type": "call", "expiry": "2026-11-20",
                                      "strike": 100, "quantity": 1, "order_key": key(), **extra}, now)["filled"]


def sell(db, position_id, now):  # noqa: F811
    return paper_book.close_order(db, {"position_id": position_id, "order_key": key()}, now)["filled"]


def test_paper_it_records_whose_idea_it_was_through_the_same_fill(db, market):  # noqa: F811
    paper_book.start_run(db, None, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    filled = buy(db, source="copilot", idea_id="card-7f3a", note="Thesis: reclaim of 98", stop=95, target=105)
    assert filled["cash"] == -340.0  # the ask, ×100: the same fill as his own ticket
    mine = buy(db)  # his own ticket names no source
    [event, _] = db.exec(select(PaperEvent).where(PaperEvent.kind == "open").order_by(PaperEvent.recorded_at)).all()
    assert json.loads(event.data_json)["source"] == "copilot" and json.loads(event.data_json)["idea_id"] == "card-7f3a"
    book = paper_book.view(db, NOW + 1)
    shown = {p["id"]: p for p in book["positions"]}
    assert (shown[filled["position_id"]]["source"], shown[filled["position_id"]]["idea_id"]) == ("copilot", "card-7f3a")
    assert (shown[mine["position_id"]]["source"], shown[mine["position_id"]]["idea_id"]) == ("mine", None)
    assert shown[filled["position_id"]]["note"] == "Thesis: reclaim of 98"


def test_a_stale_quote_still_refuses_paper_it_with_the_quotes_time(db, market):  # noqa: F811
    paper_book.start_run(db, None, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40, age=600), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    with pytest.raises(paper_book.PaperError) as refused:
        buy(db, source="radar", idea_id="setup-1")
    assert refused.value.status == 409 and "not live" in str(refused.value) and "ET" in str(refused.value)
    assert db.exec(select(PaperEvent)).all() == []


@pytest.mark.parametrize("extra, why", [
    ({"source": "robinhood"}, "source is one of"),
    ({"idea_id": "card-1"}, "cannot be recorded"),  # his own ticket carries no idea id
    ({"source": "scanner", "idea_id": "bad id with spaces"}, "cannot be recorded"),
    ({"source": "scanner", "idea_id": "x" * 65}, "cannot be recorded"),
])
def test_an_unknown_source_or_a_bad_idea_id_is_refused_before_any_quote(db, market, extra, why):  # noqa: F811
    paper_book.start_run(db, None, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    with pytest.raises(paper_book.PaperError, match=why):
        buy(db, **extra)
    assert market.reads == [] and db.exec(select(PaperEvent)).all() == []


def test_a_paper_it_limit_keeps_its_source_when_it_fills_later(db, market):  # noqa: F811
    paper_book.start_run(db, None, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    placed = paper_book.place_limit(db, {"action": "open", "symbol": "NBIS", "instrument": "option", "option_type": "call",
                                         "expiry": "2026-11-20", "strike": 100, "quantity": 1, "limit_price": 3.20,
                                         "order_key": key(), "source": "scanner", "idea_id": "cand-42", "stop": 95}, NOW)
    [working] = paper_book.view(db, NOW + 1)["orders"]
    assert working["source"] == "scanner" and working["idea_id"] == "cand-42"
    market.quotes = {CALL: q(CALL, 3.05, 3.15, now=NOW + 120), "NBIS": q("NBIS", 97, 97.1, last=97.05, now=NOW + 120)}
    paper_book.minute_pass(db, NOW + 120, lambda symbol, at: [])
    [held] = paper_book.view(db, NOW + 121)["positions"]
    assert held["id"] == placed["working"]["id"] and (held["source"], held["idea_id"], held["stop"]) == ("scanner", "cand-42", 95)


def test_the_scorecard_splits_closed_paper_trades_by_source(db, market):  # noqa: F811
    paper_book.start_run(db, None, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    a = buy(db)  # mine: 3.40 → 3.90 = +50
    b = buy(db, source="copilot", idea_id="c1")  # copilot: 3.40 → 3.90 = +50
    c = buy(db, source="copilot", idea_id="c2")  # copilot: 3.40 → 2.90 = −50
    d = buy(db, source="radar", idea_id="r1")  # radar: 3.40 → 2.90 = −50
    e = buy(db, source="scanner", idea_id="s1")  # scanner: still open, not counted
    later = NOW + 600
    market.quotes = {CALL: q(CALL, 3.90, 4.00, now=later), "NBIS": q("NBIS", 99, 99.1, last=99.05, now=later)}
    assert sell(db, a["position_id"], later)["pnl"] == 50.0
    assert sell(db, b["position_id"], later)["pnl"] == 50.0
    market.quotes = {CALL: q(CALL, 2.90, 3.00, now=later + 60), "NBIS": q("NBIS", 97, 97.1, last=97.05, now=later + 60)}
    assert sell(db, c["position_id"], later + 60)["pnl"] == -50.0
    assert sell(db, d["position_id"], later + 60)["pnl"] == -50.0
    score = paper_book.view(db, later + 61)["score"]["paper"]
    assert score["trades"] == 4 and score["pnl"] == 0.0
    assert score["by_source"] == [
        {"source": "mine", "trades": 1, "pnl": 50.0, "win_rate": 100.0},
        {"source": "copilot", "trades": 2, "pnl": 0.0, "win_rate": 50.0},
        {"source": "radar", "trades": 1, "pnl": -50.0, "win_rate": 0.0},
        {"source": "scanner", "trades": 0, "pnl": 0.0, "win_rate": None},
    ]
    assert sum(s["pnl"] for s in score["by_source"]) == score["pnl"]  # the split adds up to the whole
    assert e["position_id"] in {p["id"] for p in paper_book.view(db, later + 61)["positions"]}


def test_a_position_recorded_before_sources_counts_as_his_own(db, market):  # noqa: F811
    paper_book.start_run(db, None, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    filled = buy(db)
    event = db.exec(select(PaperEvent)).one()
    data = json.loads(event.data_json)
    data.pop("source"), data.pop("idea_id")
    event.data_json = json.dumps(data)
    db.add(event)
    db.commit()
    market.quotes = {CALL: q(CALL, 3.90, 4.00, now=NOW + 60), "NBIS": q("NBIS", 99, 99.1, last=99.05, now=NOW + 60)}
    sell(db, filled["position_id"], NOW + 60)
    book = paper_book.view(db, NOW + 61)
    assert book["closed"][0]["source"] == "mine" and book["score"]["paper"]["by_source"][0]["trades"] == 1


def test_the_route_takes_the_source_and_refuses_one_it_does_not_know(db, market, monkeypatch):  # noqa: F811
    monkeypatch.setattr(copilot_paper, "_settings", lambda: type("S", (), {"enabled": True, "evidence": "live"})())
    monkeypatch.setattr(copilot_paper.time, "time", lambda: NOW)
    app = FastAPI()
    app.include_router(copilot_paper.router, prefix="/copilot")
    app.dependency_overrides[get_session] = lambda: db
    client = TestClient(app)
    paper_book.start_run(db, None, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    order = {"action": "open", "symbol": "NBIS", "instrument": "option", "option_type": "call", "expiry": "2026-11-20",
             "strike": 100, "quantity": 1}
    assert client.post("/copilot/paper/orders", json={**order, "source": "elsewhere", "order_key": key()}).status_code == 422
    reply = client.post("/copilot/paper/orders", json={**order, "source": "radar", "idea_id": "setup-9", "order_key": key()})
    assert reply.status_code == 200, reply.text
    [held] = client.get("/copilot/paper").json()["positions"]
    assert (held["source"], held["idea_id"]) == ("radar", "setup-9")


def test_the_copilots_read_shows_the_source_and_the_split(db, market):  # noqa: F811
    paper_book.start_run(db, None, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    held = buy(db, source="copilot", idea_id="c1")
    closed = buy(db, source="radar", idea_id="r1")
    market.quotes = {CALL: q(CALL, 3.90, 4.00, now=NOW + 60), "NBIS": q("NBIS", 99, 99.1, last=99.05, now=NOW + 60)}
    sell(db, closed["position_id"], NOW + 60)
    out = copilot_paper_book.compact(paper_book.view(db, NOW + 61, settle_expired=False), set(), NOW + 61)
    assert [r["source"] for r in out["open"]] == ["copilot"] and [r["source"] for r in out["closed"]] == ["radar"]
    assert out["score"]["paper_by_source"] == [{"source": "radar", "trades": 1, "pnl": 50.0, "win_rate": 100.0}]
    assert held["position_id"]


def test_radar_and_scanner_candidates_name_their_contract_for_paper_it():
    assert paper_book.idea_contract({"option_type": "call", "expiration": "2026-11-21", "strike": "95", "delta": 0.46}) == {
        "option_type": "call", "expiry": "2026-11-21", "strike": 95.0}
    assert paper_book.idea_contract({"option_type": "put", "expiry": "2026-11-21", "strike": 52}) == {
        "option_type": "put", "expiry": "2026-11-21", "strike": 52.0}
    for missing in (None, {}, {"option_type": "call", "strike": 95}, {"option_type": "call", "expiration": "2026-11-21"},
                    {"option_type": "straddle", "expiration": "2026-11-21", "strike": 95},
                    {"option_type": "call", "expiration": "soon", "strike": 95}):
        assert paper_book.idea_contract(missing) is None
