"""The options position companion: adopt an unplanned long option, watch it, update it and close it in one Telegram
thread. Model turns are scripted (one test runs the copilot's own ``fake`` backend); Telegram is a recorded stub."""

import asyncio
from datetime import UTC, date, datetime
import json
from uuid import UUID

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.engine import copilot_investigations, copilot_plans, notification_policy, position_companion, reconstructor, telegram
from app.engine.chart_math import ET
from app.engine.position_companion import Companion
from app.engine.telegram_replies import Replies
from app.models import Account, CopilotInvestigation, Fill, LevelAlert, PhonePing, PositionCompanion, ThesisWatchTrigger, TradeCapture
from app.routers.fills import _rebuild_trades

ROTH, WEBULL = UUID(int=1), UUID(int=2)
WED = date(2026, 10, 21)
FRI = date(2026, 10, 23)
CHAT = "4242"
n = iter(range(100, 10_000))

ADOPT_ANSWER = """Verdict: Draft — NBIS is holding above VWAP with the group firm.
Read: NBIS 165.00 is 1.2% over VWAP 163.00 as of 10:03, group +0.8% vs SPY.
Against: the last hour's headline is old news and the move is already 4% on the day.
Thesis: a guess: a recovery bounce with AI infrastructure strength.
Invalidation: 158.20
Time stop: 11:00 today"""


def at(hhmm: str, day: date = WED) -> float:
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=ET).timestamp()


def utc(hhmm: str, day: date = WED) -> datetime:
    return datetime.fromtimestamp(at(hhmm, day), UTC).replace(tzinfo=None)


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class Calendar:
    def hours(self, day):
        return {"status": "open", "open": 570, "close": 960}


class _Wednesday(date):
    @classmethod
    def today(cls):
        return WED


class Turns:
    """A scripted copilot turn: the adopt answer, then numbered updates; records each question."""

    def __init__(self):
        self.questions: list[str] = []

    async def __call__(self, question, symbol, now):
        self.questions.append(question)
        if "Adopted after the entry" in question:
            return ADOPT_ANSWER, None
        if "is closed" in question:
            return "Verdict: Pattern — Out 40 minutes in, above the invalidation.\nThe plan said out below 158.20; he sold at a gain.", None
        return f"Verdict: Hold — Update {len(self.questions)}: nothing changes the plan.\n- NBIS still above 158.20.", None


class Phone:
    """Telegram's Bot API, recorded: every sendMessage gets the next message id."""

    def __init__(self):
        self.sent: list[dict] = []
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, method, *, json=None, data=None, files=None, timeout=None, image=False):
        self.calls.append((method, json or data))
        if method == "sendMessage":
            self.sent.append(json)
            return {"message_id": 500 + len(self.sent)}
        return True


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setattr(reconstructor, "date", _Wednesday)
    monkeypatch.setenv("POSITION_COMPANION_ENABLED", "true")
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    monkeypatch.setenv("ALERT_APP_URL", "https://journal.test")
    for name in ("COMPANION_MAX_UPDATES", "COMPANION_MAX_POSITIONS", "COMPANION_MOVE_PCT", "PLAN_NUDGE_GRACE_MINUTES",
                 "PING_DAILY_CAP", "PING_BUDGET_NUDGE", "PING_BUDGET_COMPANION_UPDATE", "ALERT_POLICY_ENABLED", "NTFY_URL"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def phone(monkeypatch):
    stub = Phone()
    monkeypatch.setattr(telegram, "call", stub)
    return stub


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Account(id=ROTH, name="Roth", type="roth_ira", last4="8267", broker="robinhood"))
        db.add(Account(id=WEBULL, name="Webull", type="individual", last4="4242", broker="webull"))
        db.commit()
    yield engine
    engine.dispose()


class World:
    def __init__(self, engine):
        self.engine = engine
        self.clock = Clock(at("09:50"))
        self.turns = Turns()
        self.prices = {"NBIS": 165.0, "AMD": 240.0}
        self.radar_events: list[tuple[datetime, str]] = []  # (first seen, UTC; summary)
        self.chart = {"vwap": {"vwap": 163.0},
                      "levels": {"below": [{"low": 158.2, "high": 158.9, "label": "prior day low"}],
                                 "above": [{"low": 171.0, "high": 171.6, "label": "day high"}]}}
        self.companion = Companion(engine, Calendar(), clock=self.clock, turn=self.turns,
                                   chart=lambda s: {**self.chart, "last": self.prices[s]},
                                   underlying=lambda symbols: {s: self.prices[s] for s in symbols if s in self.prices},
                                   marks=lambda occs, now: {o: {"mark": 412.0, "bid": 405.0} for o in occs},
                                   radar=lambda symbol, since, now: [text for seen, text in self.radar_events if seen > since])

    def tick(self, hhmm: str, day: date = WED):
        self.clock.now = at(hhmm, day)
        asyncio.run(self.companion.run_once())


@pytest.fixture
def world(engine, phone):
    return World(engine)


def fill(engine, when="10:00", ticker="NBIS", qty=2, price=310, account=ROTH, side="buy_to_open", option_type="call", strike=160,
         day=WED):
    i = next(n)
    option = {} if side in ("buy", "sell") else {"option_type": option_type, "strike": strike, "expiration": FRI}
    with Session(engine) as db:
        db.add(Fill(id=UUID(int=i), account_id=account, ticker=ticker, instrument_type="stock" if side in ("buy", "sell") else "option",
                    side=side, contracts=qty, price=price, executed_at=datetime.combine(day, datetime.strptime(when, "%H:%M").time()),
                    raw_email_id=f"gmail:{i}", **option))
        db.commit()
        _rebuild_trades(db, "test")
        db.commit()


def companions(engine) -> list[PositionCompanion]:
    with Session(engine) as db:
        return db.exec(select(PositionCompanion).order_by(PositionCompanion.opened_at)).all()


def investigation(engine, row: PositionCompanion) -> dict:
    with Session(engine) as db:
        return copilot_investigations.get(row.investigation_id, session=db)


def ping(engine, kind="giveback", when="10:15", sender="position_alerts"):
    row = companions(engine)[0]
    with Session(engine) as db:
        db.add(PhonePing(sender=sender, source_id=f"ping-{next(n)}", kind=kind, rank=notification_policy.rank(kind), symbol=row.ticker,
                         anchor=notification_policy.anchor(row.account_id, row.source_key), trade_id=row.trade_id,
                         title=f"{row.contract} gave back its gain", body="Up 40% at 10:10, now +2%.", decided_at=utc(when),
                         decision="sent", delivered_at=utc(when)))
        db.commit()


def buttons(message: dict) -> list[tuple[str, str]]:
    return [(b["text"], b.get("callback_data") or b.get("url")) for row in message["reply_markup"]["inline_keyboard"] for b in row]


# ------------------------------------------------------------------ adopt


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("POSITION_COMPANION_ENABLED")
    assert position_companion.enabled() is False
    assert position_companion.companion_from_env(None) is None


def test_adopt_saves_the_draft_plan_and_sends_once(world, engine, phone):
    fill(engine, "10:00")
    world.tick("10:02")  # inside the grace period: nothing yet
    assert companions(engine) == [] and phone.sent == []
    world.tick("10:03")
    [row] = companions(engine)
    assert row.state == "draft" and row.watched
    plan = json.loads(row.plan_json)
    assert plan["invalidation"] == 158.2 and plan["direction"] == "long" and plan["horizon"] == "day"
    assert plan["thesis"].startswith("a guess") and plan["entry_underlying"] == 165.0
    saved = investigation(engine, row)
    assert saved["title"] == "Adopted: NBIS 160C" and saved["status"] == "open" and saved["symbol"] == "NBIS"
    assert [m["role"] for m in saved["transcript"]] == ["user", "assistant"]
    assert saved["transcript"][0]["content"].startswith(f"Review this position: {row.trade_id}.")
    assert "Nothing here places, changes or suggests an order" in saved["transcript"][0]["content"]
    [message] = phone.sent
    assert message["text"].startswith("<b>Adopted: NBIS 160C</b>\nNBIS is holding above VWAP")
    assert "Draft plan: invalidation 158.20 (NBIS)" in message["text"]
    assert buttons(message) == [("Confirm", f"pc:{row.id}:confirm"), ("Ignore", f"pc:{row.id}:ignore"),
                                ("Edit", f"https://journal.test/copilot-lab?investigation={row.investigation_id}")]
    assert row.message_id == "501" and row.delivery == "sent"
    with Session(engine) as db:
        [record] = db.exec(select(PhonePing).where(PhonePing.sender == "position_companion")).all()
    assert record.kind == "companion_adopt" and record.decision == "sent"
    world.tick("10:04")
    world.tick("10:05")
    assert len(phone.sent) == 1 and len(world.turns.questions) == 1


def test_a_put_takes_the_nearest_level_above(world, engine, phone):
    fill(engine, "10:00", option_type="put")
    world.turns = None  # the turn fails: the drafted plan still stands

    async def failing(question, symbol, now):
        return "", "The model declined."
    world.companion.turn = failing
    world.tick("10:03")
    [row] = companions(engine)
    plan = json.loads(row.plan_json)
    assert plan["invalidation"] == 171.6 and plan["direction"] == "short" and row.state == "draft"
    assert "Copilot turn failed" in row.last_error
    assert "Draft plan: invalidation 171.60 (NBIS)" in phone.sent[0]["text"]


@pytest.mark.parametrize("case", ["before_start", "webull", "stock", "planned", "sold_to_open", "yesterday"])
def test_not_adopted(world, engine, phone, case):
    if case == "before_start":
        fill(engine, "09:45")
    elif case == "webull":
        fill(engine, "10:00", account=WEBULL)
    elif case == "stock":
        fill(engine, "10:00", side="buy", price=120)
    elif case == "sold_to_open":
        fill(engine, "10:00", side="sell_to_open")
    elif case == "yesterday":
        fill(engine, "10:00", day=date(2026, 10, 20))
    else:
        fill(engine, "10:00")
        with Session(engine) as db:
            from app.models import Trade
            from app.routers.captures import link
            trade = db.exec(select(Trade)).one()
            capture = TradeCapture(client_id="client-plan-1", received_at=utc("09:58"), account_id=ROTH, account_label="Roth",
                                   underlying="NBIS", side="buy_calls", instrument="option", mode="discretionary",
                                   wording="Out below 158.", context_state="unavailable", image_state="unavailable")
            db.add(capture)
            db.commit()
            from app.routers.captures import LinkBody
            link(capture.id, LinkBody(trade_id=trade.id), db)
    world.tick("10:03")
    world.tick("10:30")
    assert companions(engine) == [] and phone.sent == []


def test_a_rebuild_never_readopts(world, engine, phone):
    fill(engine, "10:00")
    world.tick("10:03")
    with Session(engine) as db:
        _rebuild_trades(db, "test")  # new trade ids, same first entry fill
        db.commit()
    world.tick("10:05")
    [row] = companions(engine)
    with Session(engine) as db:
        assert position_companion.trade_of(db, row).status == "open"
    assert len(phone.sent) == 1


def test_off_while_the_lab_is_off(world, engine, phone, monkeypatch):
    monkeypatch.setenv("COPILOT_ENABLED", "false")
    fill(engine, "10:00")
    world.tick("10:03")
    assert companions(engine) == []


# ------------------------------------------------------------------ Confirm, Ignore, answers


def tap(engine, data: str, alerts_changed=None) -> str | None:
    replies = Replies(engine, call=telegram.call, alerts_changed=alerts_changed)
    update = {"update_id": 1, "callback_query": {"id": "q1", "data": data, "from": {"id": int(CHAT)},
                                                  "message": {"message_id": 501, "chat": {"id": int(CHAT)},
                                                              "reply_markup": {"inline_keyboard": [[
                                                                  {"text": "Confirm", "callback_data": data},
                                                                  {"text": "Ignore", "callback_data": "x"}]]}}}}
    return asyncio.run(replies.handle(update))


def test_confirm_arms_the_invalidation_as_a_plan_card_does(world, engine, phone, monkeypatch):
    fill(engine, "10:00")
    world.tick("10:03")
    [row] = companions(engine)
    monkeypatch.setattr(position_companion, "read_underlying", lambda symbols: {"NBIS": 165.0})
    changed = []
    assert tap(engine, f"pc:{row.id}:confirm", alerts_changed=lambda: changed.append(1)) == "pc"
    [row] = companions(engine)
    assert row.state == "armed" and changed == [1]
    with Session(engine) as db:
        alert = db.get(LevelAlert, row.alert_id)
        assert (alert.symbol, alert.price, alert.plan_role, alert.source_kind, alert.source_id, alert.state, alert.direction) == (
            "NBIS", 158.2, "invalidation", "copilot", str(row.investigation_id), "active", "down")
        board = copilot_plans.board(db, quotes=lambda symbols: ({"NBIS": 165.0}, None, None))
    [plan] = board["plans"]
    assert plan["investigation_id"] == str(row.investigation_id) and plan["position"] == "in_position"
    assert plan["direction"] == "long" and plan["instrument"] == "10/23/26 160C"
    assert plan["entry"]["price"] == 165.0 and plan["entry"]["state"] == "hit" and plan["invalidation"]["state"] == "armed"
    answered = [c for c in phone.calls if c[0] == "answerCallbackQuery"]
    assert answered[-1][1]["text"].startswith("Confirmed: invalidation 158.20")
    edited = [c for c in phone.calls if c[0] == "editMessageReplyMarkup"][-1][1]
    assert edited["reply_markup"]["inline_keyboard"][0][0]["text"] == "✓ Confirmed"
    # A second tap arms nothing more.
    tap(engine, f"pc:{row.id}:confirm")
    with Session(engine) as db:
        assert len(db.exec(select(LevelAlert)).all()) == 1


def test_confirm_refuses_an_invalidation_already_crossed(world, engine, phone):
    fill(engine, "10:00")
    world.tick("10:03")
    [row] = companions(engine)
    reply, chosen = position_companion.confirm(engine, str(row.id), quote=lambda symbol: 157.0)
    assert chosen is None and "already past the invalidation" in reply
    assert companions(engine)[0].state == "draft"


def test_ignore_stops_updates(world, engine, phone):
    fill(engine, "10:00")
    world.tick("10:03")
    [row] = companions(engine)
    assert tap(engine, f"pc:{row.id}:ignore") == "pc"
    assert companions(engine)[0].state == "ignored"
    ping(engine, "giveback", "10:15")
    world.tick("10:30")
    world.tick("11:05")
    assert len(phone.sent) == 1 and len(world.turns.questions) == 1


# ------------------------------------------------------------------ watch and update


def adopted(world, engine):
    fill(engine, "10:00")
    world.tick("10:03")
    return companions(engine)[0]


def trigger(world, engine, kind: str) -> str:
    """Make one kind of trigger happen after 10:15; returns the reason text the update question carries."""
    if kind == "ping":
        ping(engine, "giveback", "10:15")
        return "a give-back alert went out"
    if kind == "thesis":
        with Session(engine) as db:
            db.add(ThesisWatchTrigger(symbol="NBIS", kind="news", dedupe_key="nbis-news-1", day=WED.isoformat(), fired_at=utc("10:15"),
                                      text="NBIS signs a data center lease", path="/copilot-lab"))
            db.commit()
        return "thesis watch fired (news: NBIS signs a data center lease)"
    if kind == "radar":
        world.radar_events.append((utc("10:15"), "Semis group up 1.4% vs SPY over 15 min"))
        return "Radar: Semis group up 1.4% vs SPY"
    if kind == "move":
        world.prices["NBIS"] = 170.0
        return "NBIS moved +3.0% since then"
    raise AssertionError(kind)


@pytest.mark.parametrize("kind", ["ping", "thesis", "radar", "move"])
def test_an_update_is_due_on_each_trigger(world, engine, phone, kind):
    row = adopted(world, engine)
    world.tick("10:20")  # nothing new yet
    assert len(phone.sent) == 1
    reason = trigger(world, engine, kind)
    world.tick("10:26")  # after the give-back ping's quiet window
    assert len(world.turns.questions) == 2
    question = world.turns.questions[1]
    assert reason in question and "invalidation 158.20 on NBIS" in question and "option mark $4.12" in question
    assert "at most 80 words" in question and "Nothing here places" in question
    update = phone.sent[1]
    assert update["text"].startswith("<b>NBIS 160C · update</b>\nVerdict: Hold")
    assert update["reply_parameters"] == {"message_id": 501, "allow_sending_without_reply": True}
    assert buttons(update)[:2] == [("Closed it", f"pu:{row.id}:0:closed"), ("Holding", f"pu:{row.id}:0:holding")]
    saved = investigation(engine, row)
    assert [m["role"] for m in saved["transcript"]] == ["user", "assistant", "user", "assistant"]
    [entry] = json.loads(companions(engine)[0].updates_json)
    assert entry["delivery"] == "sent" and entry["message_id"] == "502" and entry["day"] == WED.isoformat()
    world.tick("10:40")  # nothing new since
    assert len(phone.sent) == 2
    assert tap(engine, f"pu:{row.id}:0:holding") == "pu"
    assert json.loads(companions(engine)[0].updates_json)[0]["answer"] == "holding"


def test_an_update_waits_for_the_quiet_window(world, engine, phone):
    adopted(world, engine)
    ping(engine, "giveback", "10:15")
    world.tick("10:20")  # the give-back went out 5 minutes ago: no turn spent on a ping the policy would hold
    assert len(world.turns.questions) == 1
    world.tick("10:26")
    assert len(world.turns.questions) == 2


def test_the_cadence_floor_an_hour_in_and_at_1530(world, engine, phone):
    adopted(world, engine)
    world.tick("10:59")
    assert len(world.turns.questions) == 1
    world.tick("11:00")
    assert "an hour since the entry at 10:00" in world.turns.questions[1]
    world.tick("13:00")
    assert len(world.turns.questions) == 2
    world.tick("15:30")
    assert "15:30 and still open" in world.turns.questions[2]
    world.tick("15:59")
    assert len(world.turns.questions) == 3


def test_no_overnight_updates_and_the_next_session_resumes(world, engine, phone):
    adopted(world, engine)
    world.tick("16:05")  # after the close
    world.tick("08:00", date(2026, 10, 22))
    assert len(world.turns.questions) == 1
    with Session(engine) as db:
        db.add(ThesisWatchTrigger(symbol="NBIS", kind="news", dedupe_key="overnight", day="2026-10-22",
                                  fired_at=utc("08:00", date(2026, 10, 22)), text="NBIS raised to buy", path="/copilot-lab"))
        db.commit()
    world.tick("09:31", date(2026, 10, 22))
    assert len(world.turns.questions) == 2 and "NBIS raised to buy" in world.turns.questions[1]


def test_the_daily_ceiling(world, engine, phone, monkeypatch):
    monkeypatch.setenv("COMPANION_MAX_UPDATES", "2")
    adopted(world, engine)
    for minute, price in (("10:20", 170.0), ("10:40", 175.5), ("11:30", 181.0)):
        world.prices["NBIS"] = price
        world.tick(minute)
    assert len(world.turns.questions) == 3  # the adopt and two updates; the third move waits for tomorrow
    world.prices["NBIS"] = 190.0
    world.tick("09:40", date(2026, 10, 22))
    assert len(world.turns.questions) == 4


def test_the_newest_positions_are_watched(world, engine, phone, monkeypatch):
    monkeypatch.setenv("COMPANION_MAX_POSITIONS", "1")
    fill(engine, "10:00")
    world.tick("10:03")
    fill(engine, "10:05", ticker="AMD", strike=250)
    world.tick("10:08")
    first, second = companions(engine)
    assert (first.ticker, first.watched, second.ticker, second.watched) == ("NBIS", False, "AMD", True)
    world.prices["NBIS"], world.prices["AMD"] = 175.0, 250.0
    world.tick("10:30")
    assert [q.split("Position companion update for the adopted ")[1][:3] for q in world.turns.questions[2:]] == ["AMD"]


# ------------------------------------------------------------------ close


def test_close_writes_the_exit_note_as_the_conclusion(world, engine, phone):
    row = adopted(world, engine)
    fill(engine, "10:40", side="sell_to_close", price=420)
    world.tick("10:41")
    [row] = companions(engine)
    assert row.state == "closed"
    question = world.turns.questions[-1]
    assert "is closed" in question and "out 10:40 at $4.20" in question and "P&L +220 dollars" in question
    saved = investigation(engine, row)
    assert saved["status"] == "closed" and saved["conclusion"] == "Pattern — Out 40 minutes in, above the invalidation."
    last = phone.sent[-1]
    assert last["text"].startswith("<b>NBIS 160C · closed</b>") and last["reply_parameters"]["message_id"] == 501
    world.tick("11:30")
    assert len(phone.sent) == 2  # nothing after the close


def test_close_removes_an_armed_invalidation_that_never_fired(world, engine, phone):
    row = adopted(world, engine)
    position_companion.confirm(engine, str(row.id), quote=lambda symbol: 165.0)
    fill(engine, "10:40", side="sell_to_close", price=420)
    world.tick("10:41")
    with Session(engine) as db:
        assert db.exec(select(LevelAlert)).all() == []
    assert companions(engine)[0].state == "closed"


def test_an_adopt_only_position_closes_quietly(world, engine, phone, monkeypatch):
    monkeypatch.setenv("COMPANION_MAX_POSITIONS", "0")
    adopted(world, engine)
    fill(engine, "10:40", side="sell_to_close", price=420)
    world.tick("10:41")
    assert companions(engine)[0].state == "closed" and len(world.turns.questions) == 1


# ------------------------------------------------------------------ the policy and the desk


def test_adopt_shares_the_nudge_budget(world, engine, phone, monkeypatch):
    monkeypatch.setenv("PING_BUDGET_NUDGE", "1")
    fill(engine, "10:00")
    fill(engine, "10:01", ticker="AMD", strike=250)
    world.tick("10:04")
    first, second = companions(engine)
    assert {first.delivery, second.delivery} == {"sent", "held"}
    assert len(phone.sent) == 1
    held = first if first.delivery == "held" else second
    assert held.last_error == "Not sent: Plan nudges' 1 ping for today is spent."


def test_desk_lists_an_adopted_position(world, engine, phone, monkeypatch):
    from app.routers import copilot_desk
    adopted(world, engine)
    with Session(engine) as db:
        adopted_map = copilot_desk._adopted(db)
    [(trade_id, entry)] = adopted_map.items()
    found = {"positions": [{"trade_id": trade_id, "symbol": "NBIS", "contract": "NBIS 10/23/26 160C", "instrument": "option",
                            "unrealized_usd": 20.0, "plan": None, "link_path": None, "plan_path": None}], "flagged": {}}
    _act, watch, covered = copilot_desk._position_rows(found, {}, {}, {}, adopted_map)
    [row] = watch
    assert row["adopted"] is True and row["investigation_id"] == entry["investigation_id"] and row["path"] is None
    assert row["status"]["text"] == "Adopted · draft plan to confirm"
    assert covered == {entry["investigation_id"]}


def test_the_timeline_shows_the_companions_pings(world, engine, phone):
    from app.engine import desk_context
    row = adopted(world, engine)
    world.prices["NBIS"] = 170.0
    world.tick("10:20")
    with Session(engine) as db:
        inv = db.get(CopilotInvestigation, row.investigation_id)
        rows = desk_context.timeline(db, inv, at("10:30"))["rows"]
    texts = [r["text"] for r in rows if r["kind"] == "ping"]
    assert "Ping sent · companion update" in texts and "Ping sent · adopted position" in texts


def test_a_real_fake_backend_turn_adopts(engine, phone, monkeypatch):
    """The copilot's own scripted backend end to end: the turn runs and its answer is saved, the draft stands."""
    monkeypatch.setenv("COPILOT_BACKEND", "fake")
    monkeypatch.setenv("COPILOT_EVIDENCE", "fixture")
    from app.ai import copilot_spend
    monkeypatch.setattr(copilot_spend, "record", lambda *a, **k: None)
    world = World(engine)
    world.companion.turn = position_companion.run_turn
    fill(engine, "10:00")
    world.tick("10:03")
    [row] = companions(engine)
    assert row.state == "draft" and json.loads(row.plan_json)["invalidation"] == 158.2
    reply = investigation(engine, row)["transcript"][1]["content"]
    assert reply and "Simulated" in reply
    assert len(phone.sent) == 1


# ------------------------------------------------------------------ review regressions


def test_a_failure_after_the_update_turn_never_repeats_it(world, engine, phone, monkeypatch):
    adopted(world, engine)

    def broken(*args, **kwargs):
        raise ValueError("the transcript is full")
    monkeypatch.setattr(position_companion, "save_messages", broken)
    world.prices["NBIS"] = 170.0
    for minute in ("10:20", "10:21", "10:22", "10:25"):
        world.tick(minute)
    assert len(world.turns.questions) == 2  # one update turn; the failure did not bring it back every pass
    [entry] = json.loads(companions(engine)[0].updates_json)
    assert entry["delivery"] == "sent" and "Not saved on the desk thread" in entry["error"]
    assert len(phone.sent) == 2  # the ping still went


def test_a_failure_after_the_close_turn_never_repeats_it(world, engine, phone, monkeypatch):
    adopted(world, engine)

    def broken(*args, **kwargs):
        raise ValueError("the transcript is full")
    monkeypatch.setattr(position_companion, "save_messages", broken)
    fill(engine, "10:40", side="sell_to_close", price=420)
    for minute in ("10:41", "10:42", "10:50"):
        world.tick(minute)
    assert companions(engine)[0].state == "closed" and len(world.turns.questions) == 2


def test_updates_are_paced_by_the_quiet_window(world, engine, phone):
    adopted(world, engine)
    world.radar_events.append((utc("10:14"), "first"))
    world.tick("10:15")
    world.radar_events.append((utc("10:16"), "second"))
    world.tick("10:17")
    assert len(world.turns.questions) == 2  # the second waits for the window after the first
    world.tick("10:26")
    assert len(world.turns.questions) == 3


def test_the_exit_note_waits_out_the_quiet_window(world, engine, phone):
    adopted(world, engine)
    ping(engine, "giveback", "10:35")
    fill(engine, "10:40", side="sell_to_close", price=420)
    world.tick("10:41")
    assert companions(engine)[0].state == "draft"  # a give-back went out 6 minutes ago: the note would be held
    world.tick("10:46")
    assert companions(engine)[0].state == "closed"
    assert phone.sent[-1]["text"].startswith("<b>NBIS 160C · closed</b>")
    with Session(engine) as db:
        close = db.exec(select(PhonePing).where(PhonePing.source_id.like("%:close"))).one()
    assert close.decision == "sent"


def test_no_exit_note_after_hours_until_the_next_session(world, engine, phone):
    adopted(world, engine)
    fill(engine, "16:45", side="sell_to_close", price=420)
    world.tick("16:46")
    world.tick("20:00")
    assert companions(engine)[0].state == "draft" and len(world.turns.questions) == 1
    world.tick("09:31", date(2026, 10, 22))
    assert companions(engine)[0].state == "closed" and len(world.turns.questions) == 2


def test_a_confirm_racing_the_close_arms_nothing(world, engine, phone):
    row = adopted(world, engine)

    def quote_while_closing(symbol):  # the close loop claims the row while Confirm reads its quote
        with Session(engine) as db:
            found = db.get(PositionCompanion, row.id)
            found.state = "closed"
            db.add(found)
            db.commit()
        return 165.0
    reply, chosen = position_companion.confirm(engine, str(row.id), quote=quote_while_closing)
    assert chosen is None and "closed or was ignored meanwhile" in reply
    with Session(engine) as db:
        assert db.exec(select(LevelAlert)).all() == []
    assert companions(engine)[0].state == "closed"


def test_ignore_after_confirm_disarms_and_closes_the_thread(world, engine, phone):
    row = adopted(world, engine)
    position_companion.confirm(engine, str(row.id), quote=lambda symbol: 165.0)
    reply, chosen = position_companion.ignore(engine, str(row.id))
    assert chosen == "Ignored"
    with Session(engine) as db:
        assert db.exec(select(LevelAlert)).all() == []
    saved = investigation(engine, companions(engine)[0])
    assert saved["status"] == "closed" and saved["conclusion"].startswith("Ignored")


def test_an_adopt_only_close_closes_its_thread(world, engine, phone, monkeypatch):
    monkeypatch.setenv("COMPANION_MAX_POSITIONS", "0")
    row = adopted(world, engine)
    fill(engine, "10:40", side="sell_to_close", price=420)
    world.tick("10:41")
    assert investigation(engine, companions(engine)[0])["status"] == "closed"
    assert row.watched is False


def test_a_held_adopt_is_adopt_only(world, engine, phone, monkeypatch):
    monkeypatch.setenv("PING_BUDGET_NUDGE", "0")
    adopted(world, engine)
    [row] = companions(engine)
    assert row.delivery == "held" and row.watched is False
    world.prices["NBIS"] = 175.0
    world.tick("11:05")
    assert len(world.turns.questions) == 1 and phone.sent == []


def test_one_failing_adopt_never_stops_the_others(world, engine, phone):
    fill(engine, "10:00")
    fill(engine, "10:00", ticker="AMD", strike=250)
    real = world.companion.chart

    def chart(symbol):
        if symbol == "AMD":
            raise RuntimeError("feed down")
        return real(symbol)
    world.companion.chart = chart
    world.tick("10:03")
    states = {r.ticker: r.state for r in companions(engine)}
    assert states == {"NBIS": "draft", "AMD": "adopting"}


def test_the_alert_goes_at_once_while_the_exit_note_waits(world, engine, phone):
    row = adopted(world, engine)
    position_companion.confirm(engine, str(row.id), quote=lambda symbol: 165.0)
    ping(engine, "giveback", "10:38")
    fill(engine, "10:40", side="sell_to_close", price=420)
    world.tick("10:41")
    [row] = companions(engine)
    assert row.state == "armed" and len(world.turns.questions) == 1  # the note waits for the quiet window
    with Session(engine) as db:
        assert db.exec(select(LevelAlert)).all() == []


def test_confirm_refuses_a_position_already_closed(world, engine, phone):
    row = adopted(world, engine)
    fill(engine, "10:40", side="sell_to_close", price=420)
    reply, chosen = position_companion.confirm(engine, str(row.id), quote=lambda symbol: 165.0)
    assert chosen is None and "has closed" in reply
    with Session(engine) as db:
        assert db.exec(select(LevelAlert)).all() == []


def test_a_failed_read_or_turn_at_the_close_still_closes_the_thread(world, engine, phone):
    row = adopted(world, engine)

    def down(symbols):
        raise RuntimeError("feed down")

    async def failing(question, symbol, now):
        raise RuntimeError("model down")
    world.companion.underlying, world.companion.turn = down, failing
    fill(engine, "10:40", side="sell_to_close", price=420)
    world.tick("10:41")
    [row] = companions(engine)
    saved = investigation(engine, row)
    assert row.state == "closed" and saved["status"] == "closed" and saved["conclusion"].startswith("Unclear")
