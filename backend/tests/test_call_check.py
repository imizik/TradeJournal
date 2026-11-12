"""Check a call (engine/call_check.py): telling a call from a question, the reading with nothing guessed, the facts,
the saved check with its check-time price, Pass and planned, the desk routes and the Telegram card."""
import asyncio
import json
import uuid
from datetime import date, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.database import get_session
from app.engine import call_check
from app.models import CallCheck, Trade
from tests.test_exit_habits import ROTH, engine  # noqa: F401

TODAY = date(2026, 11, 11)
AAPL = "i think AAPL $320 11/27 hits"
QQQ = "entry: odte qqq 660 p"
STALE = "NBIS 105c 11/14 @ 4.20 stop 3.20 🚀 (posted 40 min ago)"


@pytest.fixture
def lab(monkeypatch):
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setenv("COPILOT_BACKEND", "fake")
    monkeypatch.setenv("COPILOT_EVIDENCE", "fixture")
    from app.ai import copilot_spend
    monkeypatch.setattr(copilot_spend, "record", lambda *a, **k: None)
    monkeypatch.setattr(call_check, "today", lambda: TODAY)


def scripted(monkeypatch, text: str, seen: list | None = None):
    """The model's answer, fixed: what the check does with a given reading and card."""
    from app.ai import copilot_spend

    async def turn(history, symbol, *args, kind=None, source=None, images=None, **kwargs):
        if seen is not None:
            seen.append({"question": history[-1]["content"], "kind": kind, "source": source, "images": images})
        yield {"type": "text", "delta": text}
        yield {"type": "done", "turn_id": str(uuid.UUID(int=7))}
    monkeypatch.setattr(copilot_spend, "recorded_turn", turn)


def check(raw, db_engine, minute=41, **kwargs):
    return asyncio.run(call_check.run(raw, source=kwargs.pop("source", "desk"), db_engine=db_engine,
                                      now=datetime(2026, 11, 11, 10, minute, tzinfo=call_check_et()), **kwargs))


def call_check_et():
    from app.engine.chart_math import ET
    return ET


# ------------------------------------------------------------------ call or question


@pytest.mark.parametrize("text,kind", [
    (AAPL, "call"), (QQQ, "call"), (STALE, "call"), ("TSLA 400p fri", "call"), ("$NVDA 150c", "call"),
    ("check this one: NVDA looks ready", "call"), ("check nvda", "call"),
    ("Why is NVDA moving?", "question"), ("what matters right now", "question"), ("NVDA looks strong today", "question"),
    ("Should I take NBIS 105c?", "maybe"), ("how is my nbis 105c 11/14 doing", "maybe"), ("stop on NBIS is 96", "maybe"),
    # His own trade, not a stranger's call: never checked at once.
    ("I bought 5 NVDA 190c today", "maybe"), ("Bought 2 APLD 30c 11/14 @ 1.20, stop 1.00", "maybe"),
    ("took profit on spy 600p", "maybe"), ("take profits on NVDA at $200 target", "maybe"),
    # "check" that asks something is a question, not a forced check.
    ("Check my positions", "question"), ("check on NVDA for me, is it holding?", "question"), ("check the market breadth", "question"),
    ("check positions", "question"), ("check spy levels", "question"), ("Took a starter in SPY 590c 0dte @ .50", "maybe"),
])
def test_a_call_is_told_from_a_question(text, kind):
    assert call_check.classify(text)[0] == kind


def test_the_check_prefix_forces_a_check_and_is_removed():
    assert call_check.classify("Check: AAPL looks like it wants 320") == ("call", "AAPL looks like it wants 320")
    assert call_check.classify("check nvda 150c fri") == ("call", "nvda 150c fri")
    # "check" or "check this" alone: the message it replies to is the call.
    assert call_check.classify("check") == ("call", "") and call_check.classify("check this", replying=True) == ("call", "")
    assert call_check.classify("check this one out", replying=True) == ("call", "")


def test_a_reply_is_never_checked_without_the_prefix():
    assert call_check.classify("adding 2 more at 1.05, stop 0.80", replying=True)[0] == "maybe"
    assert call_check.classify(QQQ, replying=True)[0] == "maybe"
    assert call_check.classify(f"check {QQQ}", replying=True)[0] == "call"


# ------------------------------------------------------------------ the reading: nothing guessed


def test_the_reading_is_parsed_and_blanks_stay_blank():
    answer = call_check.parse("""Reading: ticker AAPL | expiry 2026-11-27 | strike ? | side ? | entry ? | stop ? | target 320
Verdict: Wait — no contract or entry to check yet
Tile: AAPL now | $307.40 at 10:41
Tile: To the target | +4.1% in 16 days
Tile: Your AAPL record | 9 trades, 4 up
Against: The move it needs is a little more than the market prices.
Changes if: you name the contract.""", TODAY)
    assert answer["reading"] == {"ticker": "AAPL", "expiry": "2026-11-27", "strike": None, "side": None, "entry": None,
                                 "stop": None, "target": 320.0}
    assert answer["verdict"] == "Wait" and answer["headline"] == "no contract or entry to check yet"
    assert answer["tiles"][0] == ["AAPL now", "$307.40 at 10:41"] and len(answer["tiles"]) == 3
    assert answer["against"].startswith("The move") and answer["changes_if"] == "you name the contract."


def test_odte_reads_as_todays_expiry_and_a_value_the_text_does_not_hold_is_blanked():
    answer = call_check.parse("Reading: ticker QQQ | expiry 0DTE | strike 660 | side put | entry 0.85 | stop ? | target ?\n"
                              "Verdict: Pass — QQQ is above the strike and rising", TODAY)
    assert answer["reading"]["expiry"] == "2026-11-11"
    confirmed = call_check.confirm(answer["reading"], QQQ, TODAY)
    # 0.85 is not in the message: the model's entry is dropped, never kept as a guess.
    assert confirmed == {"ticker": "QQQ", "expiry": "2026-11-11", "strike": 660.0, "side": "put", "entry": None, "stop": None,
                         "target": None}


def test_a_side_a_ticker_or_an_expiry_the_message_does_not_state_is_blanked():
    guessed = {"ticker": "AAPL", "expiry": "2026-11-27", "strike": 320.0, "side": "call", "entry": None, "stop": None, "target": None}
    # "hits" is not a call marker: the side is not stated. 320 is written, so the strike stays as the model read it.
    assert call_check.confirm(guessed, AAPL, TODAY)["side"] is None
    assert call_check.confirm({**guessed, "ticker": "AAPL"}, "apple to 320 by thanksgiving", TODAY)["ticker"] is None
    assert call_check.confirm({**guessed, "expiry": "2026-11-28"}, AAPL, TODAY)["expiry"] is None
    assert call_check.confirm({**guessed, "expiry": "2026-11-13"}, "nbis 105c fri", TODAY)["expiry"] == "2026-11-13"  # Friday


def test_a_price_written_with_a_leading_dot_is_kept_and_a_dates_numbers_are_not_prices():
    read = {"ticker": "SPY", "expiry": None, "strike": 590.0, "side": "call", "entry": 0.5, "stop": 0.3, "target": None}
    assert call_check.confirm(read, "SPY 590c 0dte @ .50 sl .30", TODAY)["entry"] == 0.5
    assert call_check.confirm({**read, "entry": 11.0}, "IWM 590c 11/14", TODAY)["entry"] is None
    assert call_check.confirm({**read, "side": "put"}, "SPY 590 p/l looks good", TODAY)["side"] is None
    assert call_check.confirm({**read, "expiry": "2026-11-16"}, "SPY 590c money setup", TODAY)["expiry"] is None
    assert call_check.confirm({**read, "expiry": "2026-11-27"}, "spy nov 27th 590c", TODAY)["expiry"] == "2026-11-27"


@pytest.mark.parametrize("text,expiry", [
    ("QQQ 660p today @ .5", "2026-11-11"), ("SPY 590c tmrw @ .5", "2026-11-12"), ("SPY 590c 1dte @ .5", "2026-11-12"),
    ("NVDA 590c 14 Nov", "2026-11-14"), ("TSLA 590c 11-14 @ .5", "2026-11-14"),
])
def test_the_ways_discord_writes_an_expiry_are_kept(text, expiry):
    read = {"ticker": text.split()[0], "expiry": expiry, "strike": 590.0, "side": None, "entry": None, "stop": None, "target": None}
    assert call_check.confirm(read, text, TODAY)["expiry"] == expiry


def test_a_level_pair_after_pt_stays_a_price_not_a_date():
    read = {"ticker": "NVDA", "expiry": "2026-11-14", "strike": 190.0, "side": "call", "entry": 2.0, "stop": None, "target": 3.0}
    assert call_check.confirm(read, "NVDA 190c 11/14 @ 2 PT 3/4", TODAY)["target"] == 3.0


def test_several_calls_check_the_first_and_list_the_rest():
    answer = call_check.parse("Reading: ticker NVDA | expiry 2026-11-21 | strike 150 | side call | entry 2.10 | stop ? | target ?\n"
                              "Verdict: Draft — at the posted entry\nTile: NVDA now | $147.20\n"
                              "Also: TSLA 400p 11/14; AMD 180c 11/21", TODAY)
    assert answer["reading"]["ticker"] == "NVDA" and answer["others"] == ["TSLA 400p 11/14", "AMD 180c 11/21"]


# ------------------------------------------------------------------ the facts


def test_the_facts_weigh_the_post_the_cost_and_the_record():
    reading = {"side": "call", "expiry": "2026-11-14", "strike": 105.0, "entry": 4.20, "stop": 3.20}
    contract = {"state": "ok", "label": "NBIS 11/14 105C", "bid": 5.50, "ask": 5.65, "mid": 5.575, "as_of": "x"}
    facts = call_check.combine("NBIS", reading, {"last": 101.2}, contract, 310.0, {"symbol": {"trades": 3}}, TODAY, "now")
    assert facts["vs_posted_entry"] == {"entry": 4.2, "mid_now": 5.575, "move_pct": 32.74, "past_entry": True}
    assert facts["cost"] == {"one_contract_usd": 565.0, "usual_opening_premium_usd": 310.0, "vs_usual": 1.82}
    assert facts["expiry"] == {"date": "2026-11-14", "days_to_expiry": 3, "kind": "1-7 days", "expired": False}
    assert facts["stop"] == {"value": 3.2, "reads_as": "option premium"}
    missing = call_check.combine("AAPL", {"expiry": "2026-11-27", "target": 320.0}, {"last": 307.4}, None, None, {}, TODAY, "now")
    assert missing["contract"] == {"state": "not_identified", "missing": ["strike", "side"]}
    assert missing["target"]["reads_as"] == "stock level" and missing["target"]["from_last_pct"] == 4.1


def test_the_record_counts_trades_like_it_by_symbol_side_and_kind_of_expiry(engine):  # noqa: F811
    with Session(engine) as db:
        def trade(ticker, side, opened, expiry, pnl):
            db.add(Trade(account_id=ROTH, ticker=ticker, instrument_type="option", contracts=1, option_type=side, strike=100,
                         expiration=expiry, total_premium_paid=200, realized_pnl=pnl, opened_at=opened, status="closed",
                         avg_entry_premium=200))
        day = datetime(2026, 10, 1, 10, 0)
        trade("QQQ", "put", day, day.date(), -150)
        trade("QQQ", "put", day, day.date(), 90)
        trade("SPY", "put", day, day.date(), -300)
        trade("QQQ", "call", day, day.date() + timedelta(days=10), 400)
        db.commit()
        record = call_check.record_like(db, "QQQ", "put", "0DTE")
    assert record["symbol"] == {"trades": 3, "up": 2, "pnl": 340.0, "small_sample": True}
    assert record["symbol_side"] == {"trades": 2, "up": 1, "pnl": -60.0, "small_sample": True}
    assert record["same_expiry_kind"] == {"kind": "0DTE", "side": "put", "trades": 3, "up": 1, "pnl": -360.0, "small_sample": True}


def test_the_facts_tool_is_the_check_jobs_alone_and_validates_its_input():
    from app.ai import copilot_prompt, copilot_tools
    assert "get_call_facts" in {t["name"] for t in copilot_prompt.TOOLS["check_call"]}
    assert "get_call_facts" not in {t["name"] for t in copilot_prompt.TOOLS["desk"]}
    assert copilot_tools.validate("get_call_facts", {"symbol": "qqq", "side": "put", "expiry": "2026-11-11", "strike": 660}) == \
        {"symbol": "QQQ", "side": "put", "expiry": "2026-11-11", "strike": 660.0}
    with pytest.raises(copilot_tools.ToolInputError):
        copilot_tools.validate("get_call_facts", {"symbol": "QQQ", "side": "straddle"})


def test_the_check_prompt_gives_no_orders_and_weighs_the_record():
    from app.ai import copilot_prompt
    prompt = copilot_prompt.PROMPTS["check_call"]
    assert "Never tell them to buy, sell, take or skip it" in prompt
    assert "weighs the owner's record, not only whether the call is fresh" in prompt
    assert copilot_prompt.job_for("check_call", "telegram") == "check_call"


# ------------------------------------------------------------------ one check, end to end on the demo model


def test_his_aapl_message_is_checked_with_the_blanks_named(engine, lab):  # noqa: F811
    done = check(AAPL, engine)
    assert done["reading"] == {"ticker": "AAPL", "expiry": "2026-11-27", "strike": None, "side": None, "entry": None,
                               "stop": None, "target": 320.0}
    assert done["verdict"] == "Wait" and done["symbol"] == "AAPL"
    assert done["underlying_price"] and done["quote"]["simulated"]  # the price when he checked, kept with the check
    text = call_check.telegram_text(done)
    assert text.startswith("Verdict: Wait — ")
    assert "call or put: not stated" in text and "entry price: not stated" in text and "stop: not stated" in text
    with Session(engine) as db:
        row = db.exec(select(CallCheck)).one()
    assert row.source == "desk" and row.raw_text == AAPL and row.day == TODAY and row.outcome is None


def test_his_qqq_odte_message_reads_todays_put_and_its_quote(engine, lab):  # noqa: F811
    done = check(QQQ, engine)
    assert done["reading"]["expiry"] == "2026-11-11" and done["reading"]["strike"] == 660 and done["reading"]["side"] == "put"
    assert done["quote"]["contract"]["state"] == "ok" and done["quote"]["contract"]["bid"]
    assert "11/11 (0DTE)" in call_check.telegram_text(done)


def test_a_stale_call_is_read_whole_and_judged_from_the_price_now(engine, lab):  # noqa: F811
    done = check(STALE, engine)
    assert done["reading"] == {"ticker": "NBIS", "expiry": "2026-11-14", "strike": 105.0, "side": "call", "entry": 4.2,
                               "stop": 3.2, "target": None}
    # The demo record on trades like it is net negative: a Pass even though the facts are fresh.
    assert done["verdict"] == "Pass" and done["quote"]["contract"]["label"] == "NBIS 11/14 105C"


def test_a_call_already_past_its_posted_entry_reads_as_stale(engine, lab, monkeypatch):  # noqa: F811
    from app.ai import copilot_fixture
    monkeypatch.setattr(copilot_fixture.FixtureEvidence, "get_quotes", lambda self, symbols: {"prices": {"NBIS": 112.0}, "quotes": {}})
    done = check(STALE, engine)
    assert done["verdict"] == "Pass" and "past the posted entry" in done["card"]["headline"]


def test_no_ticker_guessed(engine, lab):  # noqa: F811
    done = check("this one is going to rip 🚀🚀", engine)
    assert done["symbol"] is None and done["verdict"] is None and done["card"]["headline"] == call_check.NO_TICKER
    assert done["plan_href"] is None and done["quote"] is None


def test_a_ticker_the_model_made_up_becomes_no_ticker(engine, lab, monkeypatch):  # noqa: F811
    scripted(monkeypatch, "Reading: ticker AAPL | expiry ? | strike 320 | side ? | entry ? | stop ? | target ?\n"
                          "Verdict: Wait — no contract yet\nTile: AAPL now | $307")
    done = check("apple to 320 by thanksgiving", engine)
    assert done["symbol"] is None and done["verdict"] is None and done["card"]["tiles"] == []


def test_a_value_the_model_read_but_the_message_does_not_state_leaves_no_card_judged_on_it(engine, lab, monkeypatch):  # noqa: F811
    scripted(monkeypatch, "Reading: ticker QQQ | expiry 2026-11-11 | strike 660 | side put | entry ? | stop ? | target ?\n"
                          "Verdict: Pass — QQQ is above the strike\nTile: QQQ 11/11 660P | 0.84 × 0.88")
    done = check("entry: odte qqq 660", engine)  # no p: the side is not stated
    assert done["reading"]["side"] is None and done["verdict"] == "Wait" and done["card"]["tiles"] == []
    assert done["card"]["headline"] == "the message does not state the call or put"


def test_the_check_runs_as_its_own_job_with_the_message_quoted(engine, lab, monkeypatch):  # noqa: F811
    seen = []
    scripted(monkeypatch, "Reading: ticker QQQ | expiry 2026-11-11 | strike 660 | side put | entry ? | stop ? | target ?\n"
                          "Verdict: Pass — QQQ is 0.9% above the strike and rising", seen)
    done = check(QQQ, engine, source="telegram")
    assert seen[0]["kind"] == "check_call" and seen[0]["source"] == "telegram"
    assert seen[0]["question"].startswith(call_check.CHECK_HEAD) and f'"""\n{QQQ}\n"""' in seen[0]["question"]
    with Session(engine) as db:
        assert db.exec(select(CallCheck)).one().turn_id == str(uuid.UUID(int=7))
    assert done["source"] == "telegram"


def test_a_spent_daily_budget_refuses_the_check(engine, lab, monkeypatch):  # noqa: F811
    from app.ai import copilot_spend
    monkeypatch.setenv("COPILOT_BACKEND", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(copilot_spend, "spent_today", lambda: 999.0)
    monkeypatch.setattr(copilot_spend, "record_refused", lambda **k: None)
    with pytest.raises(call_check.CheckRefused, match="budget"):
        check(QQQ, engine)


# ------------------------------------------------------------------ the log, Pass and planned


def test_the_days_checks_carry_pass_and_planned(engine, lab):  # noqa: F811
    from app.models import TradeCapture
    first, second = check(AAPL, engine), check(QQQ, engine, minute=48)
    with Session(engine) as db:
        assert call_check.pass_check(db, first["id"]) == ("Passed. It stays in today's checked calls.", "Passed")
        db.add(TradeCapture(client_id="cc1", received_at=datetime(2026, 11, 11, 16), account_id=ROTH, account_label="Roth",
                            underlying="QQQ", side="buy_puts", instrument="option", mode="discretionary",
                            context_state="unavailable", image_state="none", origin_kind="checked_call", origin_ref=second["id"], context_json="{}"))
        db.commit()
        rows = call_check.day_checks(db, TODAY)
    assert [r["symbol"] for r in rows] == ["QQQ", "AAPL"]  # newest first
    assert rows[1]["outcome"] == "passed" and not rows[1]["planned"]
    assert rows[0]["planned"] and rows[0]["outcome"] is None
    assert rows[0]["underlying_price"] is not None and rows[0]["checked_at"].endswith("Z")


def test_plan_it_opens_the_plan_flow_with_the_posted_levels_never_a_ticket(engine, lab):  # noqa: F811
    from urllib.parse import parse_qs, urlsplit
    done = check(STALE, engine)
    query = parse_qs(urlsplit(done["plan_href"]).query)
    assert urlsplit(done["plan_href"]).path == "/copilot-lab"
    assert query["symbol"] == ["NBIS"] and query["origin"] == [f"checked_call:{done['id']}"]
    context = query["context"][0]
    assert context.startswith("Plan a trade: NBIS 105 call 11/14") and "posted entry 4.2" in context and "posted stop 3.2" in context
    assert len(context) <= call_check.CONTEXT_MAX and "ticket" not in done["plan_href"]


def test_checked_call_is_a_plan_origin_the_journal_knows():
    from app.engine import captures
    assert captures.origin({"origin": {"kind": "checked_call", "ref": str(uuid.uuid4())}})[0] == "checked_call"


# ------------------------------------------------------------------ the desk routes


@pytest.fixture
def client(engine, lab, monkeypatch):  # noqa: F811
    from app.routers import copilot_checks
    real = call_check.run
    from app.engine.chart_math import ET
    noon = datetime(TODAY.year, TODAY.month, TODAY.day, 12, tzinfo=ET)  # the check is saved on the pinned day, not the real one
    monkeypatch.setattr(call_check, "run", lambda raw, **k: real(raw, db_engine=engine, **{"now": noon, **k}))
    app = FastAPI()
    app.include_router(copilot_checks.router, prefix="/copilot")

    def session():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_session] = session
    with TestClient(app) as test:
        yield test


def test_the_desk_checks_lists_and_passes(client):
    made = client.post("/copilot/checks", json={"text": QQQ}).json()
    assert made["symbol"] == "QQQ" and made["source"] == "desk"
    # The day the check was stored on (New York's, by the real clock the save uses), not a fixed date that stops
    # matching at midnight.
    from app.engine.chart_math import ET
    day = datetime.fromisoformat(made["checked_at"].replace("Z", "+00:00")).astimezone(ET).date().isoformat()
    listed = client.get("/copilot/checks", params={"day": day}).json()
    assert listed["day"] == day and [c["id"] for c in listed["checks"]] == [made["id"]]
    assert client.post(f"/copilot/checks/{made['id']}/pass").json()["outcome"] == "passed"
    assert client.post(f"/copilot/checks/{uuid.uuid4()}/pass").status_code == 404
    assert client.post("/copilot/checks", json={"text": ""}).status_code == 422


def test_the_desk_routes_refuse_while_the_lab_is_off(client, monkeypatch):
    monkeypatch.setenv("COPILOT_ENABLED", "false")
    assert client.get("/copilot/checks").status_code == 503
    assert client.post("/copilot/checks", json={"text": QQQ}).status_code == 503


def test_no_order_words_in_the_check_text():
    """The card, the plan link and the prompt hand facts to him; none tells him to buy, sell or take it."""
    from app.ai import copilot_prompt
    done = {"id": str(uuid.uuid4()), "day": "2026-11-11", "symbol": "QQQ", "verdict": "Draft",
            "reading": {"ticker": "QQQ", "expiry": "2026-11-11", "strike": 660.0, "side": "put", "entry": None, "stop": None, "target": None},
            "card": {"headline": "at the posted entry", "tiles": [], "against": None, "changes_if": None, "others": [], "note": None}}
    words = (call_check.telegram_text(done) + " " + call_check.plan_context(done)).lower()
    for order in ("buy ", "sell ", "take it", "enter now", "ticket"):
        assert order not in words, order
    assert json.dumps(copilot_prompt.CHECK_FORMAT).count("Draft (") == 1
