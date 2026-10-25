"""Review my week (docs/copilot-lab.md § Review my week): a seeded Monday-to-Friday week with planned, late and unplanned
trades, a plan whose invalidation fired while held and was exited, one ridden past it, a time stop and a phone alert;
every section present, free of identifiers, within the tool bound; Webull left out; the default week; simulated in the
fixture, unavailable in replay; never given to research jobs."""
import asyncio
import json
from datetime import date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.ai import copilot, copilot_review, copilot_tools, research_job
from app.ai.copilot_fixture import FixtureEvidence
from app.ai.copilot_replay import ReplayEvidence
from app.engine import capture_links, position_alerts
from app.models import (Account, Fill, LevelAlert, LevelAlertEvent, PlanTimeStop, PositionAlert, Trade, TradeCapture, TradeFill,
                        TradePathMetrics)
from app.routers.fills import _rebuild_trades

ROTH, WEBULL = UUID(int=2001), UUID(int=2002)
TUE, WED, THU = datetime(2026, 10, 20, 10, 5), datetime(2026, 10, 21, 9, 50), datetime(2026, 10, 22, 13, 0)
EXPIRY = date(2026, 11, 20)
CALL = {"option_type": "call", "strike": 100, "expiration": EXPIRY}
NBIS, CRWV, APLD, IREN, STOCK, EARLIER = (UUID(int=n) for n in (1, 3, 5, 7, 9, 13))  # a trade's id is its first entry fill's
INVESTIGATION = str(uuid4())
SECRETS = ("8267", "4242", "RH-55501234", "WB-99887766", str(ROTH), str(WEBULL), INVESTIGATION)


def fill(n, ticker, side, qty, price, at, account=ROTH, **option):
    return Fill(id=UUID(int=n), account_id=account, ticker=ticker, instrument_type="option" if option else "stock", side=side,
                contracts=qty, price=price, executed_at=at, raw_email_id=f"week:{n}", **option)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Account(id=ROTH, name="Robinhood Roth 8267", type="roth_ira", last4="8267", broker="robinhood",
                            broker_account_id="RH-55501234"))
        session.add(Account(id=WEBULL, name="Webull 4242", type="individual", last4="4242", broker="webull",
                            broker_account_id="WB-99887766"))
        session.add_all([
            fill(1, "NBIS", "buy_to_open", 2, 310, TUE, **CALL),                                    # planned, invalidation hit,
            fill(2, "NBIS", "sell_to_close", 2, 250, TUE + timedelta(minutes=65), **CALL),           # out 10 min later: -$120
            fill(3, "CRWV", "buy_to_open", 1, 400, WED, **CALL),                                     # planned, invalidation hit,
            fill(4, "CRWV", "sell_to_close", 1, 300, WED + timedelta(minutes=130), **CALL),          # held 70 min past it: -$100
            fill(5, "APLD", "buy_to_open", 1, 200, WED + timedelta(minutes=30), **CALL),             # plan captured late: +$80
            fill(6, "APLD", "sell_to_close", 1, 280, WED + timedelta(minutes=70), **CALL),
            fill(7, "IREN", "buy_to_open", 2, 150, THU, **CALL),                                     # no plan, a give-back alert:
            fill(8, "IREN", "sell_to_close", 2, 120, THU + timedelta(minutes=90), **CALL),           # -$60
            fill(9, "SPY", "buy", 10, 500, THU + timedelta(minutes=5)),                              # a stock, no plan: +$50
            fill(10, "SPY", "sell", 10, 505, THU + timedelta(minutes=25)),
            fill(11, "NBIS", "buy", 5, 90, THU, account=WEBULL),                                     # dormant: never shown
            fill(12, "NBIS", "sell", 5, 99, THU + timedelta(minutes=10), account=WEBULL),
            fill(13, "NBIS", "buy", 5, 80, TUE - timedelta(days=7)),                                 # the week before: +$25
            fill(14, "NBIS", "sell", 5, 85, TUE - timedelta(days=7, minutes=-30)),
        ])
        session.commit()
        _rebuild_trades(session, "test")
        yield session
    engine.dispose()


def _utc(wall: datetime) -> datetime:
    return capture_links.entry_utc(wall)


def _plan(db, trade_id, client_id, received_at, symbol):
    capture = TradeCapture(client_id=client_id, received_at=received_at, account_id=ROTH, account_label="Robinhood Roth 8267",
                           underlying=symbol, side="buy_calls", instrument="option", mode="discretionary", setup_label="Copilot plan",
                           wording="Entry above 101; invalidation below 97.50; time stop 11:00.", context_state="unavailable",
                           image_state="unavailable")
    db.add(capture)
    db.commit()
    capture_links.link(db, capture, trade_id)
    return capture


def _invalidation(db, symbol, created_at, fired_at, source_id):
    alert = LevelAlert(symbol=symbol, price=97.5, created_on=created_at.date(), condition="crosses", session="regular",
                       direction="down", source_kind="copilot", source_id=source_id, label=f"{symbol} invalidation: 97.50",
                       plan_role="invalidation", created_at=created_at, armed_at=created_at, state="fired", fired_at=fired_at)
    db.add(alert)
    db.commit()
    db.add(LevelAlertEvent(alert_id=alert.id, generation=1, level=97.5, price=97.4, source="stream", event_at=fired_at,
                           delivery="sent"))


def _seed_week(db):
    """NBIS: a copilot plan an hour before the entry, its time stop (same client id, sent while held) and its invalidation
    under the time stop's investigation, fired 55 minutes in; out 10 minutes later. CRWV: a plan with no time stop, its
    invalidation armed a minute after it, fired an hour in; out 70 minutes later. APLD: a plan captured after the entry.
    IREN: no plan, path metrics and a sent give-back alert. A skipped time stop. Webull and the week before stay out."""
    nbis_plan = _plan(db, NBIS, "plan-nbis", _utc(TUE) - timedelta(hours=1), "NBIS")
    db.add(PlanTimeStop(client_id=nbis_plan.client_id, investigation_id=INVESTIGATION, symbol="NBIS", text="out by 11:00",
                        due_at=_utc(TUE) + timedelta(minutes=55), delivery="sent", trade_id=NBIS,
                        detected_at=_utc(TUE) + timedelta(minutes=55), created_at=nbis_plan.received_at))
    db.add(PlanTimeStop(client_id="plan-other", investigation_id=str(uuid4()), symbol="CIFR", text="out by 15:30",
                        due_at=_utc(THU) + timedelta(hours=2), delivery="skipped", detected_at=_utc(THU) + timedelta(hours=2)))
    _invalidation(db, "NBIS", nbis_plan.received_at, _utc(TUE) + timedelta(minutes=55), INVESTIGATION)
    crwv_plan = _plan(db, CRWV, "plan-crwv", _utc(WED) - timedelta(minutes=20), "CRWV")
    _invalidation(db, "CRWV", crwv_plan.received_at + timedelta(minutes=1), _utc(WED) + timedelta(minutes=60), str(uuid4()))
    _plan(db, APLD, "plan-apld", _utc(WED) + timedelta(minutes=45), "APLD")

    db.add(TradePathMetrics(trade_id=IREN, data_source="test", fetched_at=datetime.utcnow(), option_path_quality="ok",
                            option_mfe_pct=30.0, option_peak_unrealized_pnl=90, option_giveback_from_peak=100))
    db.add(TradePathMetrics(trade_id=NBIS, data_source="test", fetched_at=datetime.utcnow(), option_path_quality="ok",
                            option_mfe_pct=5.0, option_peak_unrealized_pnl=30, option_giveback_from_peak=150))
    db.add(TradePathMetrics(trade_id=APLD, data_source="test", fetched_at=datetime.utcnow(), option_path_quality="ok",
                            option_mfe_pct=45.0, option_peak_unrealized_pnl=90, option_giveback_from_peak=10))
    trade = db.get(Trade, IREN)
    entries = db.exec(select(Fill).join(TradeFill, TradeFill.fill_id == Fill.id)
                      .where(TradeFill.trade_id == trade.id, TradeFill.role == "entry")).all()
    db.add(PositionAlert(kind="giveback", detected_at=_utc(THU) + timedelta(minutes=40), delivery="sent", account_id=ROTH,
                         source_key=position_alerts.anchor(entries), generation=1, trade_id=trade.id, contract="IREN 100C",
                         contracts=2, avg_cost=150, mark=170, gain=40, gain_pct=0.133, peak_gain=90, peak_gain_pct=0.3))
    db.commit()


def _secret_free(out) -> str:
    text = copilot_tools.bounded(out)
    assert len(text) <= copilot_tools.MAX_RESULT_CHARS and json.loads(text) == json.loads(json.dumps(out, default=str))
    ids = {str(UUID(int=n)) for n in range(1, 15)}
    assert not [s for s in (*SECRETS, *ids) if s in text], text
    assert "trade_id" not in text and "fill_id" not in text and "client_id" not in text and "investigation" not in text.replace(
        "invalidation", "")
    return text


def test_the_week_carries_every_section(db):
    _seed_week(db)
    week = copilot_review.week_review("2026-10-21", session=db)
    text = _secret_free(week)
    assert week["state"] == "ok" and "trimmed" not in week and "NBIS stock" not in text  # Webull's and last week's are out
    assert week["week"] == {"start": "2026-10-19", "end": "2026-10-23", "default": False}
    assert set(week["provenance"]) == {"totals", "planned", "follow_through", "alerts", "habits", "exits"}
    assert week["sample"]["small"] is True and "cannot show" in week["sample"]["note"]

    t = week["totals"]
    assert (t["trades"], t["pnl_usd"], t["win_rate_pct"], t["accounts"]) == (5, -150.0, 40.0, ["Robinhood Roth"])
    assert t["pnl_on_premium_pct"] == round(100 * -150 / (620 + 400 + 200 + 300 + 5000), 1)

    p = week["planned"]
    assert (p["pre_entry"]["trades"], p["pre_entry"]["pnl_usd"], p["pre_entry"]["win_rate_pct"]) == (2, -220.0, 0.0)
    assert (p["late_or_unverified"]["trades"], p["late_or_unverified"]["pnl_usd"]) == (1, 80.0)
    assert (p["none"]["trades"], p["none"]["pnl_usd"], p["none"]["win_rate_pct"]) == (2, -10.0, 50.0)

    f = week["follow_through"]
    assert (f["planned_trades"], f["with_invalidation_alert"], f["invalidation_hit_while_held"]) == (3, 2, 2)
    assert (f["out_within_15m"], f["held_past_15m"], f["held_past_pnl_usd"]) == (1, 1, -100.0)
    assert [(h["contract"].split()[0], h["minutes_to_exit"], h["then"]) for h in f["hits"]] == [
        ("NBIS", 10, "out_15m"), ("CRWV", 70, "held_past_15m")]
    stops = f["time_stops"]
    assert (stops["due"], stops["sent"], stops["skipped"], stops["then"]) == (2, 1, 1, {"closed_15m": 1})
    assert [s["symbol"] for s in stops["rows"]] == ["NBIS", "CIFR"] and stops["rows"][0]["said"] == "out by 11:00"

    a = week["alerts"]
    assert (a["sent"], a["by_kind"], a["then"]) == (1, {"giveback": 1}, {"closed_later": 1})
    assert (a["vs_closing_at_alert_usd"], a["compared"]) == (-100.0, 1)  # sold 2 at 120 against a 170 mark

    h = week["habits"]
    assert h["state"] == "ok" and h["long_options"] == 4
    held = next(r for r in h["habits"] if r["habit"].startswith("Held an hour"))
    assert held["this_week"] == "3 of 4" and held["this_week_pnl_usd"] == -280.0  # NBIS, CRWV and IREN: red after an hour
    assert held["baseline_trades"] == 1  # NBIS on Tuesday closed before the alerts went live

    pnl = week["exits"]["by_pnl"]
    assert [r["pnl_usd"] for r in pnl["best"]] == [80.0, 50.0, -60.0] and [r["pnl_usd"] for r in pnl["worst"]] == [-120.0, -100.0]
    best = pnl["best"][0]
    assert best["contract"].startswith("APLD") and best["plan"] == "late_or_unverified" and best["entry"] == "Wed 10-21 10:20"
    assert best["exit"] == "11:00" and "gave back $10" in best["note"]
    worst = pnl["worst"][0]
    assert worst["plan"] == "pre_entry" and "invalidation hit, out 10 min later" in worst["note"]
    give = week["exits"]["by_giveback"]
    assert [r["contract"].split()[0] for r in give["best"]] == ["APLD", "IREN", "NBIS"] and give["worst"] == []
    iren = give["best"][1]
    assert iren["plan"] == "none" and "1 alert(s), then closed_later" in iren["note"]


def test_the_default_week_is_the_latest_with_closed_trades(db):
    _seed_week(db)
    week = copilot_review.week_review(session=db)
    assert week["week"] == {"start": "2026-10-19", "end": "2026-10-23", "default": True} and week["totals"]["trades"] == 5
    earlier = copilot_review.week_review("2026-10-16", session=db)
    assert earlier["totals"]["trades"] == 1 and earlier["planned"]["none"]["trades"] == 1
    assert earlier["follow_through"]["planned_trades"] == 0 and earlier["habits"]["state"] == "not_applicable"
    assert earlier["exits"]["by_giveback"]["state"] == "missing"
    empty = copilot_review.week_review("2026-10-05", session=db)
    assert empty["state"] == "none" and empty["latest_week_with_trades"] == "2026-10-19"


def test_only_webull_or_no_trades_reads_none(db):
    for trade_id in (NBIS, CRWV, APLD, IREN, STOCK, EARLIER):
        db.get(Trade, trade_id).status = "open"
    db.commit()
    assert copilot_review.week_review(session=db) == {"state": "none", "reason": "The journal has no closed trades yet."}


def test_an_oversized_week_sheds_and_fits():
    row = {"contract": "X", "note": "n" * 120, "pad": "p" * 200}
    exits = {"state": "ok", "by_pnl": {"best": [dict(row) for _ in range(3)], "worst": [dict(row) for _ in range(3)]},
             "by_giveback": {"best": [dict(row) for _ in range(3)], "worst": [dict(row) for _ in range(3)]}}
    review = {"state": "ok", "provenance": copilot_review.WEEK_PROVENANCE, "totals": {"trades": 40, "pad": "t" * 1200},
              "planned": {"none": {"trades": 40}},
              "follow_through": {"state": "ok", "planned_trades": 9, "hits": [{"pad": "h" * 150} for _ in range(6)],
                                 "time_stops": {"due": 6, "rows": [{"pad": "s" * 150} for _ in range(6)]}},
              "exits": exits}
    out = copilot_review.shed_week(review)
    assert len(json.dumps(out, separators=(",", ":"))) <= copilot_review.MAX_WEEK_CHARS and out["trimmed"] is True
    assert out["totals"]["trades"] == 40 and out["follow_through"]["planned_trades"] == 9 and out["planned"]["none"]["trades"] == 40
    assert "provenance" not in out and "rows" not in out["follow_through"]["time_stops"]


# --------------------------------------------------------------------------- the tool

def test_the_tool_is_validated_routed_labelled_and_never_a_job_tool(monkeypatch):
    assert copilot_tools.validate("get_week_review", {}) == {}
    assert copilot_tools.validate("get_week_review", {"week_start": None}) == {}
    assert copilot_tools.validate("get_week_review", {"week_start": "2026-10-21"}) == {"week_start": "2026-10-21"}
    for bad in ({"week_start": "last week"}, {"week_start": "1999-01-04"}, {"week_start": "2026-10-21", "symbol": "NBIS"}):
        with pytest.raises(copilot_tools.ToolInputError):
            copilot_tools.validate("get_week_review", bad)
    seen = []
    monkeypatch.setattr(copilot_review, "week_review", lambda week_start=None, session=None: seen.append(week_start) or {"state": "ok"})
    copilot_tools.call(copilot_tools.LiveEvidence(), "get_week_review", {})
    copilot_tools.call(copilot_tools.LiveEvidence(), "get_week_review", {"week_start": "2026-10-21"})
    assert seen == [None, "2026-10-21"]
    assert copilot_tools.provenance("get_week_review", {"state": "ok"}, "live")["kind"] == "saved"
    assert "get_week_review" not in research_job.JOB_TOOLS and "mcp__tradejournal__get_week_review" not in research_job.LAB_TOOLS
    assert "get_week_review" in copilot_tools.BOOK_CONTEXT_TOOLS


def test_replay_is_unavailable_and_the_fixture_is_simulated():
    replay = ReplayEvidence.__new__(ReplayEvidence)
    assert replay.get_week_review()["state"] == "unavailable"
    fixture = FixtureEvidence().get_week_review()
    assert fixture["simulated"] is True and fixture["state"] == "ok" and set(fixture["provenance"]) == set(copilot_review.WEEK_PROVENANCE)
    assert len(json.dumps(fixture, separators=(",", ":"))) <= copilot_review.MAX_WEEK_CHARS
    assert set(fixture["planned"]) == {k for k, _ in copilot_review.BUCKETS}


def test_the_scripted_model_reviews_the_week_from_the_button_text():
    cfg = copilot.Settings(enabled=True, backend="fake", evidence="fixture", model="m", effort="medium", fallbacks=False,
                           key_configured=False)

    async def collect():
        return [e async for e in copilot.run_turn([{"role": "user", "content": "Context: Review my week"}], None, cfg,
                                                  copilot.FakeAdapter(0), FixtureEvidence(), datetime(2026, 10, 24, 11, 12))]
    events = asyncio.run(collect())
    [tool] = [e for e in events if e["type"] == "tool" and e["name"] == "get_week_review" and e["status"] == "ok"]
    assert tool["input"] == {} and tool["provenance"]["kind"] == "simulated"
    assert tool["summary"] == "week of 2026-10-19: 8 trades -27.00 $ · planned 2/1/5"
    text = "".join(e["delta"] for e in events if e["type"] == "text")
    assert "Simulated model" in text and "Planned vs unplanned" in text and "Follow-through" in text
    assert "To practice next week" in text and "Small sample" in text


def test_the_system_prompt_asks_for_the_week_frame():
    prompt = " ".join(copilot.SYSTEM_PROMPT.split())
    assert "call get_week_review" in prompt and "Lead with planned vs unplanned" in prompt
    assert "at most one or two things to practice next week" in prompt and "grounded in a count" in prompt
    assert "when the sample is too small" in prompt and "Propose a memory only if the owner states a lesson" in prompt
