"""The Dashboard's Plans card (GET /copilot/plans/positions): each open position, marked, beside the plan it was
entered under (invalidation distance, time stop countdown, entry timing), its give-back watch and latest alert; an
unplanned one carries the link page or the plan deep link. Webull is left out. Owner-only. No network."""

from datetime import UTC, date, datetime, timedelta
import json
import re
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import pytest
from sqlmodel import Session

from app.engine import plan_positions, quotes as quote_engine
from app.engine.chart_feed import chart_feed
from app.engine.quotes import OptionQuoteResult
from app.models import Account, CaptureLink, Fill, PositionAlert, PositionWatch, Trade
from app.routers.fills import _rebuild_trades
from tests.test_browser_access import boundary, signin  # noqa: F401  (the shared access fixture)
from tests.test_copilot_plans import (  # noqa: F401  (fixtures)
    NBIS, ROTH, T0, alert, capture, engine, lab, quotes, time_stop,
)

WEBULL = UUID(int=2)
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


@pytest.fixture
def marks(monkeypatch):
    monkeypatch.setattr(quote_engine, "get_stock_quotes", lambda symbols: {s: 131.2 for s in symbols})
    monkeypatch.setattr(quote_engine, "get_option_quotes", lambda requests: [OptionQuoteResult(mid=4.0)] * len(requests))
    monkeypatch.setattr(quote_engine, "option_mark", lambda req: (OptionQuoteResult(mid=4.0), 1792000000.0))
    monkeypatch.setattr(plan_positions, "_now", lambda: epoch(T0 + timedelta(minutes=289)))  # 14:49 New York


def epoch(moment: datetime) -> int:
    """T0 and the rows are naive UTC."""
    return int(moment.replace(tzinfo=UTC).timestamp())


def buy(engine, n, symbol="NBIS", *, account=ROTH, minute=5, stock=False):
    with Session(engine) as db:
        if stock:
            db.add(Fill(id=UUID(int=n), account_id=account, ticker=symbol, instrument_type="stock", side="buy", contracts=10,
                        price=120, executed_at=datetime(2026, 10, 21, 10, minute), raw_email_id=f"gmail:{n}"))
        else:
            db.add(Fill(id=UUID(int=n), account_id=account, ticker=symbol, instrument_type="option", side="buy_to_open", contracts=2,
                        price=310, executed_at=datetime(2026, 10, 21, 10, minute), raw_email_id=f"gmail:{n}", option_type="call",
                        strike=100, expiration=date(2026, 10, 23)))
        db.commit()
        _rebuild_trades(db, "test")
        db.commit()
        return str(db.get(Trade, UUID(int=n)).id)


def link(engine, capture_id, n):
    with Session(engine) as db:
        db.add(CaptureLink(capture_id=capture_id, account_id=ROTH, source_key=f"gmail:{n}", method="manual"))
        db.commit()


def test_a_planned_position_shows_pl_invalidation_distance_time_stop_countdown_and_timing(engine, lab, marks, quotes):
    plan = capture(engine, "NBIS")  # 9:59:55, before the 10:05 fill
    time_stop(engine, NBIS, "NBIS")  # due 15:30 New York
    alert(engine, NBIS, "NBIS", "entry", 95.9, state="fired", fired=T0)
    alert(engine, NBIS, "NBIS", "invalidation", 92.3)
    trade = buy(engine, 500)
    link(engine, plan, 500)
    body = lab.get("/copilot/plans/positions").json()
    [row] = body["positions"]
    assert row["trade_id"] == trade and row["contract"] == "NBIS 10/23/26 100C"
    assert (row["quantity"], row["unrealized_usd"], row["unrealized_pct"]) == (2, 180.0, 29.0)
    assert row["plan"] == {
        "setup": "Copilot plan", "thesis": "Reclaims VWAP with the group", "timing": "pre_entry",
        "invalidation": {"price": 92.3, "condition": "crosses", "state": "armed", "distance_usd": -1.7, "distance_pct": -1.81},
        "time_stop": {"text": "out by 15:30", "due_at": epoch(T0 + timedelta(minutes=330)),
                      "clock": "15:30", "state": "pending", "minutes_left": 41},
    }
    assert row["link_path"] is None and row["plan_path"] is None
    assert quotes["asked"] == [["NBIS"]]  # one batched underlying read
    assert body["count"] == 1


def test_a_plan_saved_after_the_fill_is_late_and_a_hit_invalidation_says_so(engine, lab, marks):
    plan = capture(engine, "NBIS", minute=20)  # 10:19:55, after the 10:05 fill
    time_stop(engine, NBIS, "NBIS", minute=20, delivery="sent")
    alert(engine, NBIS, "NBIS", "invalidation", 92.3, minute=20, state="fired", fired=T0 + timedelta(minutes=40))
    buy(engine, 500)
    link(engine, plan, 500)
    [row] = lab.get("/copilot/plans/positions").json()["positions"]
    assert row["plan"]["timing"] == "late"
    assert row["plan"]["invalidation"]["state"] == "hit" and "distance_pct" not in row["plan"]["invalidation"]
    assert row["plan"]["time_stop"]["state"] == "sent" and "minutes_left" not in row["plan"]["time_stop"]


def test_an_unplanned_position_with_a_suggested_plan_carries_the_link_page(engine, lab, marks):
    capture(engine, "NBIS", minute=5)  # 10:04:55, unlinked, matches the 10:05 fill
    trade = buy(engine, 500)
    [row] = lab.get("/copilot/plans/positions").json()["positions"]
    assert row["plan"] is None and row["plan_path"] is None
    assert row["link_path"] == f"/plans/link?trade={trade}"


def test_an_unplanned_position_with_nothing_suggested_carries_the_plan_deep_link(engine, lab, marks):
    buy(engine, 500)
    [row] = lab.get("/copilot/plans/positions").json()["positions"]
    assert row["plan"] is None and row["link_path"] is None
    url = urlparse(row["plan_path"])
    assert url.path == "/copilot-lab"
    query = parse_qs(url.query)
    assert query["symbol"] == ["NBIS"] and query["context"][0].startswith("Plan this position: I just opened NBIS 10/23/26 100C")


def test_give_back_state_and_the_latest_sent_alert(engine, lab, marks):
    trade = buy(engine, 500)
    with Session(engine) as db:
        db.add(PositionWatch(account_id=ROTH, source_key="gmail:500", contracts=2, avg_cost=310, peak_mark=500,
                             armed_at=T0 + timedelta(minutes=30)))
        for kind, minute, delivery in (("hold_hour", 65, "sent"), ("giveback", 90, "sent"), ("expiry_first", 95, "failed")):
            db.add(PositionAlert(account_id=ROTH, source_key="gmail:500", kind=kind, generation=0, trade_id=UUID(trade),
                                 contract="NBIS 10/23/26 100C", contracts=2, avg_cost=310, delivery=delivery,
                                 detected_at=T0 + timedelta(minutes=minute)))
        db.commit()
    [row] = lab.get("/copilot/plans/positions").json()["positions"]
    assert row["giveback"] == "fired"
    assert row["latest_alert"] == {"kind": "giveback", "at": epoch(T0 + timedelta(minutes=90))}


def test_webull_is_left_out_and_stock_has_no_watch(engine, lab, marks):
    with Session(engine) as db:
        db.add(Account(id=WEBULL, name="Webull 4242", type="individual", last4="4242", broker="webull"))
        db.commit()
    buy(engine, 600, "CRWV", account=WEBULL)
    buy(engine, 601, "CRWV", stock=True)
    [row] = lab.get("/copilot/plans/positions").json()["positions"]
    assert (row["contract"], row["giveback"], row["unrealized_usd"]) == ("CRWV stock", None, 112.0)


def test_nothing_open_is_an_empty_list_and_the_only_id_out_is_the_trade(engine, lab, marks):
    assert lab.get("/copilot/plans/positions").json()["positions"] == []
    plan = capture(engine, "NBIS")
    time_stop(engine, NBIS, "NBIS")
    alert(engine, NBIS, "NBIS", "invalidation", 92.3)
    trade = buy(engine, 500)
    link(engine, plan, 500)
    text = json.dumps(lab.get("/copilot/plans/positions").json())
    assert set(UUID_RE.findall(text)) == {trade}
    assert "gmail:" not in text and "card-1" not in text and "Roth" not in text


def test_refused_while_the_lab_is_off(lab, monkeypatch):
    from types import SimpleNamespace
    from app.routers import copilot_plans as plan_routes
    monkeypatch.setattr(plan_routes.copilot, "settings", lambda: SimpleNamespace(enabled=False))
    assert lab.get("/copilot/plans/positions").status_code == 503


def test_assistant_sessions_cannot_reach_the_card(boundary, monkeypatch):  # noqa: F811
    boundary.patch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setattr(chart_feed, "quote_rows", lambda symbols: ([], None, None))
    monkeypatch.setattr(quote_engine, "get_stock_quotes", lambda symbols: {})
    monkeypatch.setattr(quote_engine, "get_option_quotes", lambda requests: [])
    assert boundary.owner.get("/copilot/plans/positions").status_code == 200
    assert signin(boundary).status_code == 200
    assert boundary.public.get("/copilot/plans/positions").status_code == 403
