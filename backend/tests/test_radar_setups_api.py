"""/radar/setups and the web's Plan it (docs/radar.md § Setups screen): owner-only, the Telegram tap's own path."""
from datetime import datetime
import json
from types import SimpleNamespace
import uuid

from sqlmodel import Session, select

from app.engine import radar_setup_plan, telegram_replies
from app.engine.chart_math import ET
from app.main import app
from app.models import Account, LevelAlert, RadarSetup, TradeCapture
from tests.test_browser_access import boundary  # noqa: F401  (the shared access fixture)

CONTRACT = {"symbol": "NBIS261120C00062000", "option_type": "call", "strike": 62.0, "expiration": "2026-11-20",
            "bid": 1.1, "ask": 1.2, "mid": 1.15, "spread_pct": 8.7, "delta": 0.45}


def _today() -> str:
    return datetime.now(ET).date().isoformat()


def _card(engine, event="rd0-x-dip-nbis-up-1", day=None, direction="up", invalidation=59.85, contract=CONTRACT,
          created=datetime(2026, 11, 10, 15, 5), **paper) -> str:
    with Session(engine) as db:
        if db.exec(select(Account)).first() is None:
            db.add(Account(id=uuid.UUID(int=1), name="Roth", type="roth_ira", last4="8267", broker="robinhood"))
        row = RadarSetup(event_id=event, session_date=day or _today(), rule_version="rd0", kind="dip_turn", symbol="NBIS",
                         direction=direction, entry=61.2, invalidation=invalidation, created_at=created,
                         contract_json=json.dumps(contract) if contract else None, record_text="Your dips: 5 trades · +$310",
                         **paper)
        db.add(row)
        db.commit()
        return str(row.id)


def test_setups_lists_the_session_newest_first_with_the_scorecard(boundary, monkeypatch):  # noqa: F811
    monkeypatch.delenv("RADAR_ENABLED", raising=False)  # no Radar file: the cards still read from the journal
    older = _card(boundary.engine, event="a", created=datetime(2026, 11, 10, 14, 50), paper_state="closed",
                  paper_entry_price=1.2, paper_exit_price=1.6, paper_exit_reason="time_stop", paper_pnl=38.7)
    newer = _card(boundary.engine, event="b", contract=None, created=datetime(2026, 11, 10, 15, 30))
    _card(boundary.engine, event="c", day="2026-11-03")
    body = boundary.owner.get("/radar/setups").json()
    assert body["session"] == _today()
    assert [s["id"] for s in body["setups"]] == [newer, older]
    first, second = body["setups"]
    assert first["title"] == "Radar setup: NBIS dip turning up" and first["contract"] is None
    assert first["levels_line"] == "In near 61.20 · out below 59.85 (−2.2%)"
    assert first["contract_line"] == "No liquid contract found." and first["created_at_ny"] == "10:30 AM ET"
    assert second["contract_line"].startswith("Candidate: NBIS Nov 20 62C · 1.10 × 1.20 (8.7% wide)")
    assert second["paper"] == {"state": "closed", "entry_price": 1.2, "entry_at": None, "exit_price": 1.6, "exit_at": None,
                               "exit_reason": "time_stop", "pnl": 38.7, "note": None}
    assert second["record"] == "Your dips: 5 trades · +$310" and second["plan"]["state"] == "none"
    assert second["lines"][:3] == [second["levels_line"], second["contract_line"], "Your dips: 5 trades · +$310"]
    assert body["scorecard"] == [{"kind": "dip_turn", "direction": "up", "cards": 3, "with_contract": 2, "planned": 0,
                                  "paper_closed": 1, "paper_green": 1, "paper_pnl": 38.7, "unresolved": 0}]
    assert [s["event_id"] for s in boundary.owner.get("/radar/setups?session=2026-11-03").json()["setups"]] == ["c"]
    assert boundary.owner.get("/radar/setups?session=2026-02-30").status_code == 422
    assert boundary.public.get("/radar/setups").status_code in (401, 403)


def _monitor(monkeypatch):
    calls = []
    monkeypatch.setattr(app.state, "level_alerts", SimpleNamespace(changed=lambda: calls.append(1)), raising=False)
    monkeypatch.setattr(telegram_replies, "_calendar", lambda: None)
    return calls


def test_plan_it_on_the_web_plans_once_and_wakes_the_alert_monitor(boundary, monkeypatch):  # noqa: F811
    calls = _monitor(monkeypatch)
    monkeypatch.setattr(radar_setup_plan, "_live_price", lambda symbol: 61.4)
    setup_id = _card(boundary.engine)
    out = boundary.owner.post(f"/radar/setups/{setup_id}/plan")
    assert out.status_code == 200, out.text
    body = out.json()
    assert body["planned"] is True and body["plan_state"] == "planned" and body["investigation_id"] and body["reply"].startswith("Planned NBIS: out below 59.85.")
    assert calls == [1]
    again = boundary.owner.post(f"/radar/setups/{setup_id}/plan").json()
    assert (again["planned"], again["reply"]) == (True, "Already planned.")
    with Session(boundary.engine) as db:
        assert len(db.exec(select(TradeCapture)).all()) == 1
        assert [(a.plan_role, a.price) for a in db.exec(select(LevelAlert)).all()] == [("invalidation", 59.85)]
    assert boundary.owner.get("/radar/setups").json()["setups"][0]["plan"]["state"] == "planned"


def test_plan_it_refused_unknown_and_not_the_owner(boundary, monkeypatch):  # noqa: F811
    calls = _monitor(monkeypatch)
    monkeypatch.setattr(radar_setup_plan, "_live_price", lambda symbol: 59.5)  # already through the invalidation
    setup_id = _card(boundary.engine)
    body = boundary.owner.post(f"/radar/setups/{setup_id}/plan").json()
    assert (body["planned"], body["plan_state"], body["investigation_id"]) == (False, "refused", None)
    assert body["reply"] == "NBIS is already below 59.85, the level this setup was built on. No plan saved."
    assert calls == []
    assert boundary.owner.get("/radar/setups").json()["setups"][0]["plan"]["note"] == body["reply"]
    monkeypatch.setattr(radar_setup_plan, "_live_price", lambda symbol: None)  # a stale quote: nothing written
    fresh = _card(boundary.engine, event="other")
    stale = boundary.owner.post(f"/radar/setups/{fresh}/plan").json()
    assert (stale["planned"], stale["plan_state"]) == (False, "none") and "stale or missing" in stale["reply"]
    assert boundary.owner.post(f"/radar/setups/{uuid.uuid4()}/plan").status_code == 404
    assert boundary.owner.post("/radar/setups/not-a-uuid/plan").status_code == 422
    assert boundary.public.post(f"/radar/setups/{fresh}/plan").status_code in (401, 403)
    with Session(boundary.engine) as db:
        assert db.exec(select(TradeCapture)).all() == []
