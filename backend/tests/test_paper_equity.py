"""The paper account's value over time (``app/engine/paper_equity.py``): one point a minute, the same sum as the desk's
account value, a missing price as null (never zero), an old one flagged stale, and the 1D / 1W / 1M / All ranges with the
base their change is measured from. No network."""

from types import SimpleNamespace
from uuid import uuid4

from sqlmodel import select

from app.engine import paper_book, paper_challenge, paper_equity
from app.models import PaperEquity
from tests.test_paper_book import CALL, NOW, db, market, q  # noqa: F401 -- fixtures

DAY = 86400


def buy_calls(db, qty=2, now=NOW):  # noqa: F811
    return paper_book.open_order(db, {"symbol": "NBIS", "instrument": "option", "option_type": "call", "expiry": "2026-11-20",
                                      "strike": 100, "quantity": qty, "order_key": uuid4().hex}, now)["filled"]


def opened(db, market):  # noqa: F811
    paper_book.start_run(db, None, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    buy_calls(db)  # 2 calls at the 3.40 ask: cash 10,000 − 680 = 9,320
    return paper_book.current_run(db)


def test_a_point_is_the_desks_account_value_once_a_minute(db, market):  # noqa: F811
    run = opened(db, market)
    market.marks = {CALL: {"last": 3.80, "at": NOW + 55}}
    row = paper_equity.record(db, run, NOW + 60)
    view = paper_book.view(db, NOW + 60)
    assert row.equity == view["account"]["equity"] == 9320 + 760 and row.cash == 9320 and row.open_positions == 1
    # The desk's paperValue: cash + Σ(pnl − basis), pnl = mark × 100 × held + basis.
    pos = view["positions"][0]
    assert row.equity == round(view["account"]["cash"] + (pos["mark"]["pnl"] - pos["basis"]), 2)
    market.marks = {CALL: {"last": 9.99, "at": NOW + 100}}
    assert paper_equity.record(db, run, NOW + 110) is None  # the same minute keeps its first point
    assert paper_equity.record(db, run, NOW + 120).equity == 9320 + 1998
    assert len(db.exec(select(PaperEquity)).all()) == 2


def test_a_missing_price_is_null_and_an_old_one_is_stale_never_zero(db, market):  # noqa: F811
    run = opened(db, market)
    market.marks = {}
    assert paper_equity.record(db, run, NOW + 60).equity is None
    market.marks = {CALL: {"last": 3.00, "at": NOW - 600}}
    paper_equity.record(db, run, NOW + 120)
    market.marks = {CALL: {"last": 3.10, "at": NOW + 170}}
    paper_equity.record(db, run, NOW + 180)
    points = paper_equity.series(db, "1D", NOW + 200)["points"]
    assert [(p["equity"], p["stale"]) for p in points] == [(None, False), (9920.0, True), (9940.0, False)]
    assert points[1]["prices_at"] == NOW - 600


def test_a_flat_account_is_its_cash_and_never_stale(db, market):  # noqa: F811
    paper_book.start_run(db, 5000, False, NOW)
    row = paper_equity.record(db, paper_book.current_run(db), NOW + 60)
    assert row.equity == 5000 and row.prices_at is None
    assert paper_equity.series(db, "1D", NOW + 61)["points"][0]["stale"] is False


def test_the_challenges_minute_records_at_the_prices_it_judged_with(db, market):  # noqa: F811
    paper_book.start_run(db, None, False, NOW, challenge=True)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    buy_calls(db)
    market.reads.clear()
    market.quotes = {CALL: q(CALL, 3.50, 3.70, now=NOW + 300)}  # the desk's kept price is missing: the minute reads one
    run = paper_book.current_run(db)
    paper_challenge.minute(db, run, NOW + 300)
    assert market.reads == [[CALL]]  # the challenge's one read; the recorder adds none
    [row] = db.exec(select(PaperEquity)).all()
    assert row.equity == 9320 + 720 and not paper_equity.series(db, "1D", NOW + 301)["points"][0]["stale"]
    assert paper_equity.record(db, run, NOW + 310) is None  # minute_pass's own call keeps the challenge's point


def test_ranges_their_base_and_thinning(db, market):  # noqa: F811
    run = opened(db, market)
    start = NOW + 60
    for i in range(3):  # three days of points, ten minutes each, the price rising a cent a minute
        for m in range(10):
            at = start + i * DAY + m * 60
            market.marks = {CALL: {"last": 3.40 + i + m / 100, "at": at}}
            paper_equity.record(db, run, at)
    now = start + 2 * DAY + 600
    day = paper_equity.series(db, "1D", now)
    assert len(day["points"]) == 10 and day["points"][0]["at"] == start + 2 * DAY
    assert day["base"] == {"value": 9320 + (4.40 + 0.09) * 200, "at": start + DAY + 540}  # yesterday's last point
    everything = paper_equity.series(db, "ALL", now)
    assert everything["base"] == {"value": 10000, "at": NOW} and everything["starting_cash"] == 10000
    assert len(everything["points"]) <= 3 * 10 and everything["points"][-1]["at"] == start + 2 * DAY + 540
    week = paper_equity.series(db, "1W", now)
    assert week["base"]["value"] == 10000  # the run began inside the week
    assert len(week["points"]) < 30 and week["points"][-1] == day["points"][-1]  # ten-minute buckets keep each one's last
    assert paper_equity.series(db, "1M", now)["points"][-1] == day["points"][-1]


def test_no_run_answers_empty_and_a_bad_range_is_refused(db, market):  # noqa: F811
    assert paper_equity.series(db, "1D", NOW) == {"range": "1D", "run": None, "points": [], "base": None, "starting_cash": None}
    try:
        paper_equity.series(db, "5Y", NOW)
    except paper_book.PaperError as exc:
        assert exc.status == 422
    else:
        raise AssertionError("a bad range must be refused")


def test_the_route_reads_the_series(db, market, monkeypatch):  # noqa: F811
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.access_manifest import DOMAIN_ROUTES
    from app.database import get_session
    from app.routers import copilot_paper
    assert "GET /copilot/paper/equity" in DOMAIN_ROUTES  # owner-only
    run = opened(db, market)
    market.marks = {CALL: {"last": 3.80, "at": NOW + 55}}
    paper_equity.record(db, run, NOW + 60)
    app = FastAPI()
    app.include_router(copilot_paper.router, prefix="/copilot")
    app.dependency_overrides[get_session] = lambda: db
    monkeypatch.setattr(copilot_paper.copilot, "settings", lambda: SimpleNamespace(enabled=True))
    client = TestClient(app)
    shown = client.get("/copilot/paper/equity", params={"range": "ALL"}).json()
    assert shown["points"][0]["equity"] == 10080 and shown["base"]["value"] == 10000
    assert client.get("/copilot/paper/equity", params={"range": "5Y"}).status_code == 422
