"""The trade origin chain (docs/copilot-lab.md § Origin): a plan records what prompted it, the trade review and the week
show it without ids, and Radar counts the events that led to a plan and to a trade."""
import uuid
from datetime import timedelta

import pytest
from sqlmodel import select

from app.ai import copilot_origins, copilot_review
from app.engine import capture_links, radar_proof
from app.engine.radar_store import RadarStore
from app.models import Trade, TradeCapture
from app.routers import radar
from tests.test_captures import client, engine, plan  # noqa: F401  (the capture route fixtures)
from tests.test_copilot_review import REVIEWED, ROTH, _secret_free, db  # noqa: F401  (a seeded journal)
from tests.test_radar_proof import UNIVERSE, _event

RADAR_LINE = "Plan a trade: Radar 10:41: MU +4.1% vs SMH"


# ------------------------------------------------------------------ the plan records it

def test_a_plan_stores_a_valid_origin_and_refuses_an_unknown_one(client):  # noqa: F811
    http, _ = client
    saved = http.post("/charts/captures", json=plan(origin={"kind": "radar_event", "ref": "evt-2026-10-22:MU", "text": RADAR_LINE + "  " + "x" * 400}))
    assert saved.status_code in (200, 201), saved.text
    origin = saved.json()["origin"]
    assert origin["kind"] == "radar_event" and origin["ref"] == "evt-2026-10-22:MU" and len(origin["text"]) == 300
    assert origin["text"].startswith(RADAR_LINE + " x")  # whitespace folded, cut to 300
    assert http.post("/charts/captures", json=plan()).json()["origin"] == {"kind": "manual", "ref": None, "text": None}
    assert http.post("/charts/captures", json=plan(origin={"kind": "chart"})).json()["origin"]["kind"] == "chart"
    for bad in ({"kind": "tip_from_a_friend"}, {"kind": "radar_event", "ref": "../../etc"}, "radar_event"):
        refused = http.post("/charts/captures", json=plan(origin=bad))
        assert refused.status_code == 422 and "origin" in refused.json()["detail"]


# ------------------------------------------------------------------ the reviews show it

@pytest.fixture
def radar_file(tmp_path, monkeypatch):
    store = RadarStore(tmp_path / "radar.sqlite")
    store.append_event({**_event(7, "MU", "10:41"), "summary": "MU +4.1% vs SMH"})
    store.append_event(_event(8, "AAA", "10:00"))
    store.append_feedback("e7", "useful", "2026-10-22T15:00:00Z")
    monkeypatch.setenv("RADAR_ENABLED", "true")
    monkeypatch.setenv("RADAR_STORE", str(tmp_path / "radar.sqlite"))
    return tmp_path / "radar.sqlite"


def _origin_plan(db, trade_id, kind, ref, text, client_id="origin-plan", link=True):  # noqa: F811
    trade = db.get(Trade, trade_id)
    capture = TradeCapture(client_id=client_id, received_at=capture_links.entry_utc(trade.opened_at) - timedelta(hours=1),
                           account_id=ROTH, account_label="Roth", underlying=trade.ticker, side="buy_calls", instrument="option",
                           mode="discretionary", context_state="unavailable", image_state="unavailable",
                           origin_kind=kind, origin_ref=ref, origin_text=text)
    db.add(capture)
    db.commit()
    if link:
        capture_links.link(db, capture, trade_id)
    return capture


def test_the_trade_review_names_the_radar_event_with_its_rating_and_no_ids(db, radar_file):  # noqa: F811
    _origin_plan(db, REVIEWED, "radar_event", "e7", RADAR_LINE)
    review = copilot_review.trade_review(str(REVIEWED), session=db)
    assert review["origin"] == {"state": "ok", "kind": "radar_event", "from": "a Radar event", "text": "Radar 10:41: MU +4.1% vs SMH",
                                "radar_event": {"state": "ok", "summary": "MU +4.1% vs SMH", "first_seen_at": review["origin"]["radar_event"]["first_seen_at"],
                                                "rating": "useful"}}
    text = _secret_free(review)
    assert '"e7"' not in text and "origin_ref" not in text


def test_a_ping_origin_loses_its_instructions_and_ids(db):  # noqa: F811
    saved = str(uuid.uuid4())
    line = (f'New since my thesis: "Nebius wins deal". What changed? Use get_investigation_changes for investigation {saved} '
            "and say whether it still holds.")
    _origin_plan(db, REVIEWED, "thesis_watch", str(uuid.uuid4()), line)
    origin = copilot_review.trade_review(str(REVIEWED), session=db)["origin"]
    assert origin == {"state": "ok", "kind": "thesis_watch", "from": "a thesis-watch ping", "text": 'New since my thesis: "Nebius wins deal".'}


def test_no_plan_or_an_older_plan_says_so(db):  # noqa: F811
    assert copilot_review.trade_review(str(REVIEWED), session=db)["origin"]["state"] == "none"
    _origin_plan(db, REVIEWED, None, None, None)
    assert copilot_review.trade_review(str(REVIEWED), session=db)["origin"]["state"] == "unknown"


def test_the_week_breaks_trades_down_by_origin(db, radar_file):  # noqa: F811
    # The seeded journal closes this trade three days before today, which is a weekend on a Tuesday or a Wednesday
    # (and, on a UTC runner, from 8pm New York on a Monday). A week review is Monday to Friday, so move it to that Friday.
    trade = db.get(Trade, REVIEWED)
    if (back := trade.closed_at.weekday() - 4) > 0:
        trade.opened_at, trade.closed_at = trade.opened_at - timedelta(days=back), trade.closed_at - timedelta(days=back)
        db.add(trade)
        db.commit()
    _origin_plan(db, REVIEWED, "radar_event", "e7", RADAR_LINE)
    trade = db.get(Trade, REVIEWED)
    week = copilot_review.week_review(trade.closed_at.date().isoformat(), session=db)
    others = week["totals"]["trades"] - 1
    pnl = float(trade.realized_pnl)
    assert week["origins"].startswith(f"no_plan {others} ") and f"; radar_event 1 {'-' if pnl < 0 else '+'}${abs(pnl):,.0f}" in week["origins"]
    assert "e7" not in week["origins"] and "trimmed" not in week


# ------------------------------------------------------------------ Radar counts it

def test_radar_counts_events_that_led_to_a_plan_and_a_trade(db, radar_file):  # noqa: F811
    _origin_plan(db, REVIEWED, "radar_event", "e7", RADAR_LINE)                        # planned and traded
    _origin_plan(db, REVIEWED, "radar_event", "e8", "Plan a trade: Radar", client_id="plan-e8", link=False)  # planned only
    _origin_plan(db, REVIEWED, "chart", None, None, client_id="plan-chart", link=False)  # not from Radar
    assert radar_proof.planned_events(db, ["e7", "e8", "e9"]) == {"e7": {"planned": True, "traded": True},
                                                                  "e8": {"planned": True, "traded": False}}
    out = radar_proof.build(RadarStore(radar_file, read_only=True), db, UNIVERSE)
    assert out["plans"] == {"planned": 2, "traded": 1}
    assert radar.event_detail("e7", db)["plans"] == {"planned": True, "traded": True}
    assert radar.event_detail("e8", db)["plans"] == {"planned": True, "traded": False}
    capture_links.unlink(db, db.exec(select(TradeCapture).where(TradeCapture.client_id == "origin-plan")).one())
    assert radar.event_detail("e7", db)["plans"] == {"planned": True, "traded": False}


def test_origin_text_is_words_only():
    assert copilot_origins.origin_text(None) is None
    assert copilot_origins.origin_text("Plan a trade: ") is None
    assert copilot_origins.origin_text(f"Plan a trade: about {uuid.uuid4()} now") == "about now"
