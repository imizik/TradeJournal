"""Paper it from a Telegram ping (``app/engine/telegram_paper.py``): the button only under an idea with enough to place
an order, one paper market order per ping through the paper book's own path, the reply line (the fill or the refusal),
his rules and paper goals named but never blocking, and the exact rows and texts he sees. No network, no Robinhood."""

from datetime import UTC, datetime
import asyncio
import json
import uuid

import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy.pool import StaticPool

from app.engine import day_journal, paper_book, phone, telegram, telegram_paper, telegram_replies, trading_rules, weekly_goals
from app.models import PaperEvent, RadarSetup
from tests.test_paper_book import q

NOW = datetime(2026, 11, 13, 15, 42, 30, tzinfo=UTC).timestamp()  # Friday 10:42:30 New York
TODAY = datetime(2026, 11, 13).date()
CALL = "NVDA261120C00150000"
CHAT = "4242"
PLAN_KEY = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def engine(monkeypatch):
    for name in ("ALERT_APP_URL", "NTFY_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:fixture")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setenv("COPILOT_BACKEND", "fake")
    monkeypatch.setenv("COPILOT_EVIDENCE", "live")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def market(monkeypatch):
    state = type("Market", (), {})()
    state.open, state.reads = True, []
    state.quotes = {CALL: q(CALL, 3.35, 3.45, now=NOW), "NVDA": q("NVDA", 151.0, 151.05, last=151.02, now=NOW),
                    "AMD": q("AMD", 150.0, 150.10, last=150.05, now=NOW)}
    monkeypatch.setattr(paper_book, "_market_open", lambda now: state.open)

    def quotes(symbols):
        state.reads.append(sorted(symbols))
        return {s: state.quotes[s] for s in symbols if s in state.quotes}
    monkeypatch.setattr(paper_book, "_live_quotes", quotes)
    monkeypatch.setattr(telegram_paper.time, "time", lambda: NOW)
    return state


def setup_row(engine, contract=True, symbol="NVDA") -> RadarSetup:
    with Session(engine) as db:
        row = RadarSetup(event_id=f"rd0-2026-11-13-dip-{symbol.lower()}-up-1", session_date="2026-11-13", rule_version="radar-dip-v0",
                         kind="dip_turn", symbol=symbol, direction="up", entry=151.0, invalidation=148.5,
                         contract_json=json.dumps({"symbol": CALL, "option_type": "call", "strike": 150.0, "expiration": "2026-11-20",
                                                   "bid": 3.3, "ask": 3.4}) if contract else None)
        db.add(row)
        db.commit()
        db.refresh(row)
        return row


def run_paper(engine, cash=10_000.0):
    with Session(engine) as db:
        paper_book.start_run(db, cash, False, NOW - 3600)


class Bot:
    def __init__(self):
        self.calls = []

    def __call__(self, name, *, json=None, timeout=None, **_):
        self.calls.append((name, json))
        return True

    def named(self, name):
        return [body for n, body in self.calls if n == name]


def tap(data, keyboard, update_id=1, chat=CHAT):
    return {"update_id": update_id, "callback_query": {"id": f"q{update_id}", "data": data, "from": {"id": int(chat)},
            "message": {"message_id": 55, "chat": {"id": int(chat)}, "reply_markup": {"inline_keyboard": keyboard}}}}


def radar_keyboard(engine, setup) -> list[list[dict]]:
    """The Radar setup ping's reply rows exactly as Telegram gets them (ratings, Plan it, Paper it, then phone's Why?)."""
    from app.engine import radar_alerts
    alert_id = uuid.UUID(int=7)
    with Session(engine) as db:
        paper = telegram_paper.radar_button(db, setup.id)
    buttons = phone.with_why("radar_setup", radar_alerts.reply_buttons(alert_id, setup.id, paper))
    return telegram.keyboard(buttons=buttons)["inline_keyboard"]


# --- the idea ------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("words, want", [
    ("NBIS 100C 11/21", ("call", "2026-11-21", 100.0)),
    ("$95 call Nov 20 '26", ("call", "2026-11-20", 95.0)),
    ("2026-12-18 102.5 C", ("call", "2026-12-18", 102.5)),
    ("Nov 6 95C", ("call", "2027-11-06", 95.0)),  # a date with no year is its next one
])
def test_plan_contract_words_read_as_the_desk_reads_them(words, want):
    order = telegram_paper.plan_order("NBIS", "calls", "long", words, TODAY)
    assert (order["option_type"], order["expiry"], order["strike"]) == want


@pytest.mark.parametrize("instrument, direction, words, why", [
    ("calls", "long", "", "No contract named"),
    ("calls", "long", "95/100 call spread Nov 21", "names a spread"),
    ("calls", "long", "2 calls Nov 21", "does not name one strike"),
    ("calls", "long", "100C Nov 21 at 3.40", "does not name one strike"),
    ("calls", "long", "95P 11/21", "is a put, but this plan buys calls"),
    ("stock", "short", "", "cannot short them"),
])
def test_a_plan_without_one_plain_contract_has_no_order(instrument, direction, words, why):
    assert why in telegram_paper.plan_order("NBIS", instrument, direction, words, TODAY)


def test_radar_and_plan_ideas_carry_the_desks_size_stop_target_and_note(engine):
    setup = setup_row(engine)
    idea = telegram_paper.radar_idea(setup)
    assert idea["order"] == {"instrument": "option", "symbol": "NVDA", "option_type": "call", "expiry": "2026-11-20", "strike": 150.0}
    assert (idea["quantity"], idea["stop"], idea["target"], idea["source"], idea["idea_id"]) == (1, 148.5, None, "radar", str(setup.id))
    assert idea["note"] == "Radar: NVDA dip turning up. In near 151.00 · out below 148.50 (−1.7%)"
    card = {"symbol": "AMD", "direction": "long", "instrument": "stock", "invalidation": {"price": 140.0}, "target_price": 160.0,
            "thesis": "Base breakout", "client_id": PLAN_KEY}
    plan = telegram_paper.plan_idea(card, TODAY)
    assert (plan["quantity"], plan["stop"], plan["target"], plan["note"], plan["idea_id"]) == (10, 140.0, 160.0, "Copilot: Base breakout", PLAN_KEY)
    # A card confirmed on the desk is read with the fields he left there.
    confirmed = {**card, "outcome": {"state": "confirmed", "fields": {"invalidation": "142", "target": "", "thesis": "Edited"}}}
    plan = telegram_paper.plan_idea(confirmed, TODAY)
    assert (plan["stop"], plan["target"], plan["note"]) == (142.0, None, "Copilot: Edited")


# --- the button ----------------------------------------------------------------------------------------------------------

def test_the_radar_setup_ping_shows_paper_it_beside_plan_it_and_why(engine):
    setup = setup_row(engine)
    rows = radar_keyboard(engine, setup)
    assert [[b["text"] for b in row] for row in rows] == [["Useful", "Already knew"], ["Too late", "Not useful"],
                                                          ["Plan it", "📝 Paper it", "Why?"]]
    assert rows[2][1]["callback_data"] == f"pp:r:{setup.id.hex}"
    assert all(len(b["callback_data"].encode()) <= telegram.CALLBACK_MAX for row in rows for b in row)


def test_no_button_without_a_contract_on_a_hidden_ticker_or_with_the_lab_off(engine, monkeypatch):
    bare = setup_row(engine, contract=False, symbol="AMD")
    assert [b["text"] for b in radar_keyboard(engine, bare)[2]] == ["Plan it", "Why?"]
    hidden = setup_row(engine, symbol="TSLA")
    with Session(engine) as db:
        day_journal.append(db, day=TODAY, operation_id="follow-tsla", kind="follow", text="Not following", symbol="TSLA")
        assert telegram_paper.radar_button(db, hidden.id) is None
    shown = setup_row(engine)
    monkeypatch.setenv("COPILOT_ENABLED", "false")
    with Session(engine) as db:
        assert telegram_paper.radar_button(db, shown.id) is None


# --- the tap -------------------------------------------------------------------------------------------------------------

def test_one_tap_papers_the_radar_idea_once_and_replies_with_the_fill(engine, market):
    run_paper(engine)
    setup = setup_row(engine)
    keyboard = radar_keyboard(engine, setup)
    bot = Bot()
    replies = telegram_replies.Replies(engine, call=bot)
    data = f"pp:r:{setup.id.hex}"
    assert asyncio.run(replies.handle(tap(data, keyboard))) == "pp"
    [reply] = bot.named("sendMessage")
    assert reply["text"] == ("PAPER · bought 1 NVDA 11/20 150C at 3.45 (ask, 10:42 ET) · 1 contract, the desk's size for a "
                             "Radar idea · not real money")
    assert reply["reply_parameters"]["message_id"] == 55
    assert bot.named("answerCallbackQuery")[0]["text"] == "Papered: the fill is in the chat."
    [edit] = bot.named("editMessageReplyMarkup")
    assert [b["text"] for b in edit["reply_markup"]["inline_keyboard"][2]] == ["✓ Papered", "Plan it", "Why?"]
    with Session(engine) as db:
        [event] = db.exec(select(PaperEvent)).all()
        filled = json.loads(event.data_json)
    assert event.order_key == f"tg-r-{setup.id.hex}"
    assert (filled["source"], filled["idea_id"], filled["quantity"], filled["per_share"], filled["stop"], filled["target"]) == (
        "radar", str(setup.id), 1, -3.45, 148.5, None)
    assert filled["note"].startswith("Radar: NVDA dip turning up.")
    reads = len(market.reads)

    # A second tap (or a tap read again after a restart) places nothing and reads no quote.
    again = Bot()
    asyncio.run(telegram_replies.Replies(engine, call=again).handle(tap(data, keyboard, update_id=2)))
    assert again.named("sendMessage")[0]["text"] == ("Already papered from this ping: PAPER · bought 1 NVDA 11/20 150C at 3.45 "
                                                     "(ask, 10:42 ET) · not real money")
    assert len(market.reads) == reads
    with Session(engine) as db:
        assert len(db.exec(select(PaperEvent)).all()) == 1


@pytest.mark.parametrize("change, said", [
    ("closed", "PAPER · not placed: The market is closed: paper orders fill only in the regular session, on a live quote."),
    ("stale", "PAPER · not placed: The quote for the $150 call is from Nov 13 10:31 AM ET, not live: no paper fill on a stale price."),
    ("poor", "PAPER · not placed: Not enough paper buying power: this needs $345.00 and you have $100.00."),
    ("hidden", "PAPER · not placed: you set NVDA to not followed."),
    ("simulated", "PAPER · not placed: paper fills need live quotes, and the desk is on simulated evidence."),
])
def test_a_refusal_says_why_places_nothing_and_leaves_the_button(engine, market, monkeypatch, change, said):
    run_paper(engine, cash=100.0 if change == "poor" else 10_000.0)
    setup = setup_row(engine)
    keyboard = radar_keyboard(engine, setup)
    if change == "closed":
        market.open = False
    elif change == "stale":
        market.quotes[CALL] = q(CALL, 3.35, 3.45, age=11 * 60 + 30, now=NOW)
    elif change == "hidden":
        with Session(engine) as db:
            day_journal.append(db, day=TODAY, operation_id="follow-nvda", kind="follow", text="Not following", symbol="NVDA")
    elif change == "simulated":
        monkeypatch.setenv("COPILOT_EVIDENCE", "fixture")
    bot = Bot()
    asyncio.run(telegram_replies.Replies(engine, call=bot).handle(tap(f"pp:r:{setup.id.hex}", keyboard)))
    assert bot.named("sendMessage")[0]["text"] == said
    assert bot.named("answerCallbackQuery")[0]["text"] == "Not placed: why is in the chat."
    assert bot.named("editMessageReplyMarkup") == []  # Paper it stays for a later tap
    with Session(engine) as db:
        assert db.exec(select(PaperEvent)).all() == []


def test_a_tap_from_another_chat_is_ignored(engine, market):
    run_paper(engine)
    setup = setup_row(engine)
    bot = Bot()
    assert asyncio.run(telegram_replies.Replies(engine, call=bot).handle(tap(f"pp:r:{setup.id.hex}", [], chat="999"))) is None
    assert bot.calls == [] and market.reads == []


def test_broken_rules_and_goals_are_named_on_one_line_and_never_block(engine, market):
    run_paper(engine)
    with Session(engine) as db:
        rules = trading_rules.save(db, [{"text": "", "check": {"kind": "stop_set"}}, {"text": "", "check": {"kind": "max_open", "n": 1}},
                                        {"text": "Waited for the 5-minute close"}], NOW - 7200)
        weekly_goals.save(db, [{"kind": "max_trades_day", "n": 1, "book": "paper"}, {"kind": "max_loss", "n": 200, "book": "paper"}], NOW - 7200)
        paper_book.open_order(db, {"symbol": "AMD", "instrument": "stock", "quantity": 1, "order_key": uuid.uuid4().hex}, NOW - 60)
    setup = setup_row(engine)
    bot = Bot()
    asyncio.run(telegram_replies.Replies(engine, call=bot).handle(tap(f"pp:r:{setup.id.hex}", radar_keyboard(engine, setup))))
    first, second = bot.named("sendMessage")[0]["text"].splitlines()
    assert first.startswith("PAPER · bought 1 NVDA 11/20 150C at 3.45")
    assert second == ("Breaks rule “At most 1 open positions”; goal: 2 paper trades today (at most 1); "
                      "goal: can lose $345.00 (max loss $200.00). Placed anyway, as on the desk.")
    with Session(engine) as db:
        entry = next(json.loads(e.data_json) for e in db.exec(select(PaperEvent)).all() if json.loads(e.data_json)["symbol"] == "NVDA")
    by_id = {r["id"]: r for r in entry["rules"]}
    assert by_id[rules[0]["id"]]["status"] == "pass" and by_id[rules[1]["id"]]["status"] == "fail"
    assert (by_id[rules[2]["id"]]["status"], by_id[rules[2]["id"]]["reason"]) == ("ask", "Not answered (phone).")
    assert trading_rules.outcome(entry["rules"]) == "broken"


def test_a_share_plan_card_papers_ten_shares_with_its_stop_and_target(engine, market, monkeypatch):
    run_paper(engine)
    card = {"kind": "trade_plan", "symbol": "AMD", "direction": "long", "instrument": "stock", "invalidation": {"price": 140.0},
            "target_price": 160.0, "thesis": "Base breakout", "client_id": PLAN_KEY}
    monkeypatch.setattr(telegram_replies, "find_plan", lambda db, key: ("thread-1", card) if key == PLAN_KEY else None)
    with Session(engine) as db:
        paper = telegram_paper.plan_button(db, card, PLAN_KEY, now=NOW)
    assert paper == ("📝 Paper it", f"pp:p:{PLAN_KEY}")
    rows = telegram.keyboard("/copilot-lab", (("Confirm", f"pl:{PLAN_KEY}:confirm"), paper))["inline_keyboard"]
    assert [[b["text"] for b in row] for row in rows] == [["Confirm", "📝 Paper it"]]
    bot = Bot()
    asyncio.run(telegram_replies.Replies(engine, call=bot).handle(tap(f"pp:p:{PLAN_KEY}", rows)))
    assert bot.named("sendMessage")[0]["text"] == ("PAPER · bought 10 AMD shares at 150.10 (ask, 10:42 ET) · 10 shares, the desk's "
                                                   "size for a plan · not real money")
    assert bot.named("editMessageReplyMarkup")[0]["reply_markup"]["inline_keyboard"] == [
        [{"text": "✓ Papered", "callback_data": "done:p"}, {"text": "Confirm", "callback_data": f"pl:{PLAN_KEY}:confirm"}]]
    with Session(engine) as db:
        [event] = db.exec(select(PaperEvent)).all()
        filled = json.loads(event.data_json)
    assert (filled["source"], filled["idea_id"], filled["quantity"], filled["stop"], filled["target"]) == ("copilot", PLAN_KEY, 10, 140.0, 160.0)


def test_a_confirm_tap_on_a_plan_card_keeps_paper_it():
    edits = []
    replies = telegram_replies.Replies(None, call=lambda method, **kw: edits.append(kw["json"]))
    rows = [[{"text": "Confirm", "callback_data": f"pl:{PLAN_KEY}:confirm"}, {"text": "📝 Paper it", "callback_data": f"pp:p:{PLAN_KEY}"}]]
    replies._mark({"message_id": 55, "reply_markup": {"inline_keyboard": rows}}, f"pl:{PLAN_KEY}:confirm", "Confirmed")
    assert edits[0]["reply_markup"]["inline_keyboard"] == [[{"text": "✓ Confirmed", "callback_data": f"done:{PLAN_KEY}"},
                                                             {"text": "📝 Paper it", "callback_data": f"pp:p:{PLAN_KEY}"}]]


def test_the_rules_goal_is_named_only_when_this_entry_broke_a_rule(engine, market):
    run_paper(engine)
    with Session(engine) as db:
        trading_rules.save(db, [{"text": "", "check": {"kind": "stop_set"}}], NOW - 7200)
        weekly_goals.save(db, [{"kind": "rules_pct", "n": 100, "book": "paper"}], NOW - 7200)
        paper_book.open_order(db, {"symbol": "AMD", "instrument": "stock", "quantity": 1, "order_key": uuid.uuid4().hex}, NOW - 60)
    setup = setup_row(engine)  # its stop is set, so this entry follows the rule though the week is below the goal
    bot = Bot()
    asyncio.run(telegram_replies.Replies(engine, call=bot).handle(tap(f"pp:r:{setup.id.hex}", radar_keyboard(engine, setup))))
    assert "\n" not in bot.named("sendMessage")[0]["text"]


def test_an_unexpected_failure_is_answered_and_stores_nothing(engine, market, monkeypatch):
    run_paper(engine)
    setup = setup_row(engine)

    def broken(symbols):
        raise RuntimeError("feed down")
    monkeypatch.setattr(paper_book, "_live_quotes", broken)
    bot = Bot()
    asyncio.run(telegram_replies.Replies(engine, call=bot).handle(tap(f"pp:r:{setup.id.hex}", radar_keyboard(engine, setup))))
    assert bot.named("sendMessage")[0]["text"] == telegram_paper.FAILED
    assert bot.named("answerCallbackQuery")[0]["text"] == "Not placed: why is in the chat."
    with Session(engine) as db:
        assert db.exec(select(PaperEvent)).all() == []
