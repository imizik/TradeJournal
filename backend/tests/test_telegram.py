"""Telegram phone pings: the Bot API transport, the phone dispatcher, and the reply buttons. No live sends: every Bot API
call goes to a stub."""
import asyncio
from datetime import datetime
import json
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlmodel import Session, select

from app.engine import ntfy, phone, telegram, telegram_replies
from app.engine.radar_store import RadarStore
from app.models import PositionAlert, PositionAlertFeedback, RadarAlert
from tests.test_alert_feedback import seed
from tests.test_exit_habits import engine  # noqa: F401

TOKEN = "123456:fixture-token"
CHAT = "4242"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "ALERT_APP_URL", "NTFY_URL", "COPILOT_ENABLED", "PING_IMAGES_ENABLED"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def bot(monkeypatch):
    """Telegram configured, every POST recorded and answered ok with message id 77."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    monkeypatch.setenv("ALERT_APP_URL", "https://journal.example/")
    calls = []

    def post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 77}})

    monkeypatch.setattr(httpx, "post", post)
    return calls


def method(call) -> str:
    return call["url"].rsplit("/", 1)[1]


# ------------------------------------------------------------------ transport

def test_configured_needs_both_token_and_chat(monkeypatch):
    assert not telegram.configured()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    assert not telegram.configured()
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    assert telegram.configured()


def test_a_message_is_escaped_html_with_reply_buttons_first_and_open_last(bot):
    receipt = telegram.publish("SNDK <gave back>", "Peak +$300 & now +$80", path="/trades/1?alert=2",
                               buttons=(("Prompted review", "fb:a:prompted_review"),), links=(("Plan", "/plans/9"),))
    assert receipt == "77"
    [call] = bot
    assert call["url"] == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    body = call["json"]
    assert body["chat_id"] == CHAT and body["parse_mode"] == "HTML" and body["disable_notification"] is False
    assert body["text"] == "<b>SNDK &lt;gave back&gt;</b>\nPeak +$300 &amp; now +$80"
    assert body["reply_markup"] == {"inline_keyboard": [
        [{"text": "Prompted review", "callback_data": "fb:a:prompted_review"}],
        [{"text": "Open", "url": "https://journal.example/trades/1?alert=2"}, {"text": "Plan", "url": "https://journal.example/plans/9"}]]}


def test_four_answers_and_why_read_as_two_rows_and_three_buttons_keep_one(bot):
    def b(label, data):
        return {"text": label, "callback_data": data}
    answers = tuple((f"A{i}", f"fb:a:{i}") for i in range(4))
    telegram.publish("T", "m", path="/x", buttons=answers + (("Why?", "why:a"),))
    telegram.publish("T", "m", path="/x", buttons=answers)
    telegram.publish("T", "m", path="/x", buttons=answers[:2] + (("Why?", "why:a"),))
    five, four, three = (call["json"]["reply_markup"]["inline_keyboard"] for call in bot)
    opened = [{"text": "Open", "url": "https://journal.example/x"}]
    assert five == [[b("A0", "fb:a:0"), b("A1", "fb:a:1")], [b("A2", "fb:a:2"), b("A3", "fb:a:3"), b("Why?", "why:a")], opened]
    assert four == [[b("A0", "fb:a:0"), b("A1", "fb:a:1")], [b("A2", "fb:a:2"), b("A3", "fb:a:3")], opened]
    assert three == [[b("A0", "fb:a:0"), b("A1", "fb:a:1"), b("Why?", "why:a")], opened]


def test_low_priority_is_silent_and_no_app_url_means_no_open_button(bot, monkeypatch):
    monkeypatch.delenv("ALERT_APP_URL")
    telegram.publish("Week review", "Ready", priority=2)
    body = bot[0]["json"]
    assert body["disable_notification"] is True and "reply_markup" not in body


def test_long_text_is_cut_without_breaking_an_escape():
    text = telegram.text_for("T", "&" * 5000)
    assert len(text) <= telegram.TEXT_MAX and text.endswith("&amp;…")


def test_callback_data_over_64_bytes_is_refused(bot):
    with pytest.raises(ValueError):
        telegram.publish("T", "m", buttons=(("x", "fb:" + "a" * 70),))
    assert bot == []


def test_a_picture_goes_as_a_photo_with_the_text_as_caption(bot):
    telegram.publish("Time stop", "SNDK at 15:00", path="/x", image=b"\x89PNG", buttons=(("Why?", "why:a"),))
    [call] = bot
    assert method(call) == "sendPhoto"
    assert call["files"] == {"photo": ("chart.png", b"\x89PNG", "image/png")}
    assert call["data"]["caption"] == "<b>Time stop</b>\nSNDK at 15:00" and call["data"]["chat_id"] == CHAT
    assert json.loads(call["data"]["reply_markup"])["inline_keyboard"][0] == [{"text": "Why?", "callback_data": "why:a"}]


def test_a_reply_threads_under_its_message_and_open_can_be_renamed(bot):
    telegram.publish("NBIS 160C · update", "Hold", path="/copilot-lab?investigation=1", reply_to="501", open_label="Edit")
    telegram.publish("NBIS 160C · closed", "Out", image=b"\x89PNG", reply_to="501")
    text, photo = bot
    assert text["json"]["reply_parameters"] == {"message_id": 501, "allow_sending_without_reply": True}
    assert text["json"]["reply_markup"]["inline_keyboard"] == [[{"text": "Edit", "url": "https://journal.example/copilot-lab?investigation=1"}]]
    assert json.loads(photo["data"]["reply_parameters"]) == {"message_id": 501, "allow_sending_without_reply": True}
    telegram.publish("Plain", "No thread")
    assert "reply_parameters" not in bot[2]["json"]


@pytest.mark.parametrize("raised, unsent", [(httpx.ConnectError("no"), True), (httpx.ConnectTimeout("no"), True),
                                            (httpx.ReadTimeout("slow"), False)])
def test_network_failures_say_whether_the_message_surely_went_nowhere(monkeypatch, raised, unsent):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)

    def post(url, **kwargs):
        raise raised

    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(telegram.TelegramError) as caught:
        telegram.publish("T", "m")
    assert caught.value.surely_unsent is unsent and isinstance(caught.value, ntfy.NtfyError)
    assert TOKEN not in str(caught.value)
    from app.engine.position_alerts import _surely_unsent  # the senders' own test agrees
    assert _surely_unsent(caught.value) is unsent


def test_a_refusal_is_surely_unsent_and_a_refused_picture_is_image_refused(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    status = {"code": 400}
    monkeypatch.setattr(httpx, "post", lambda url, **kw: httpx.Response(
        status["code"], json={"ok": False, "error_code": status["code"], "description": "Bad Request: chat not found"}))
    with pytest.raises(telegram.TelegramError) as caught:
        telegram.publish("T", "m")
    assert caught.value.surely_unsent and not isinstance(caught.value, telegram.ImageRefused)
    assert "chat not found" in str(caught.value) and TOKEN not in str(caught.value)
    with pytest.raises(telegram.ImageRefused):
        telegram.publish("T", "m", image=b"png")
    status["code"] = 429
    with pytest.raises(telegram.TelegramError) as caught:
        telegram.publish("T", "m", image=b"png")
    assert not isinstance(caught.value, telegram.ImageRefused)


# ------------------------------------------------------------------ dispatcher

def test_phone_prefers_telegram_and_carries_buttons_and_links(bot, monkeypatch):
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")
    monkeypatch.setattr(ntfy, "publish", lambda *a, **k: pytest.fail("ntfy used while Telegram is set up"))
    assert phone.configured() and phone.transport() == "telegram"
    receipt, state = phone.send("T", "m", kind="nudge", path="/p", image=b"png", priority=3, tags=("memo",), direct_click=True,
                                more=(("Plan", "/plans/1"),))
    assert (receipt, state) == ("77", "attached")
    keyboard = json.loads(bot[0]["data"]["reply_markup"])["inline_keyboard"]
    # A factual ping gets Why?; the added button does not take the ping's links away.
    assert keyboard == [[{"text": "Why?", "callback_data": "ask:nudge"}],
                        [{"text": "Open", "url": "https://journal.example/p"}, {"text": "Plan", "url": "https://journal.example/plans/1"}]]
    # Reply buttons answer in place, so ntfy's answer links for the same answers are left off.
    phone.send("T", "m", kind="radar_event", path="/p", buttons=(("Useful", "rr:a:useful"),), more=(("Useful", "/radar?rate=useful"),))
    assert bot[1]["json"]["reply_markup"]["inline_keyboard"] == [
        [{"text": "Useful", "callback_data": "rr:a:useful"}, {"text": "Why?", "callback_data": "ask:radar_event"}],
        [{"text": "Open", "url": "https://journal.example/p"}]]


def test_why_goes_on_factual_pings_once_and_never_on_ai_summaries():
    assert phone.with_why("thesis_watch", ()) == (("Why?", "ask:thesis_watch"),)
    assert phone.with_why("giveback", (("Prompted", "fb:a:prompted_review"), ("Why?", "why:a"))) == (("Prompted", "fb:a:prompted_review"), ("Why?", "why:a"))
    for kind in ("prep", "week_review", "day_replay", "evening_review", "companion_adopt", "companion_update"):
        assert phone.with_why(kind, ()) == ()
    assert len(phone.with_why("x" * 80, ())[0][1].encode()) <= telegram.CALLBACK_MAX


def test_phone_sends_text_when_the_caption_is_too_long_or_the_picture_is_refused(bot, monkeypatch):
    assert phone.send("T", "x" * 2000, kind="prep", image=b"png") == ("77", "none")
    assert method(bot[-1]) == "sendMessage"
    refused = []

    def publish(title, message, *, image=None, **kw):
        if image is not None:
            refused.append(1)
            raise telegram.ImageRefused("Telegram refused the picture (400).")
        return "78"

    monkeypatch.setattr(telegram, "publish", publish)
    assert phone.send("T", "m", kind="prep", image=b"png") == ("78", "none") and refused == [1]


def test_phone_falls_back_to_ntfy_unchanged_and_drops_reply_buttons(monkeypatch):
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")
    sent = []
    monkeypatch.setattr(ntfy, "publish", lambda title, body, **kw: sent.append((title, body, kw)) or "ntfy-id")
    assert phone.transport() == "ntfy"
    assert phone.send("T", "m", kind="week_review", path="/w", buttons=(("Why?", "why:a"),), priority=3, tags=("bar_chart",),
                      direct_click=True) == ("ntfy-id", "none")
    assert sent == [("T", "m", {"path": "/w", "priority": 3, "tags": ("bar_chart",), "direct_click": True})]
    phone.send("T", "m", kind="level_alert", path="/charts")
    assert sent[-1] == ("T", "m", {"path": "/charts"})  # exactly the keywords the sender gave


def test_nothing_configured_means_not_configured():
    assert not phone.configured() and phone.transport() is None


# ------------------------------------------------------------------ replies

class Bot:
    """A stub ``telegram.call`` for the reply loop."""

    def __init__(self, updates=()):
        self.updates = list(updates)
        self.calls = []

    def __call__(self, name, *, json=None, timeout=None, **_):
        self.calls.append((name, json))
        if name == "getUpdates":
            out, self.updates = self.updates, []
            return out
        return True

    def named(self, name):
        return [body for n, body in self.calls if n == name]


def tap(data: str, chat=CHAT, update_id=1, keyboard=None, sender=None) -> dict:
    return {"update_id": update_id, "callback_query": {
        "id": f"q{update_id}", "data": data, "from": {"id": int(sender or chat)},
        "message": {"message_id": 55, "chat": {"id": int(chat)}, "reply_markup": {"inline_keyboard": keyboard or []}}}}


def rows(buttons) -> list[list[dict]]:
    """The reply rows ``telegram.keyboard`` lays these buttons out in (no Open row without ALERT_APP_URL)."""
    return telegram.keyboard(buttons=buttons)["inline_keyboard"]


def said(text: str, chat=CHAT, update_id=1, sender=None, replied=None) -> dict:
    return {"update_id": update_id, "message": {"message_id": 60 + update_id, "chat": {"id": int(chat)}, "from": {"id": int(sender or chat)},
                                                "text": text, **({"reply_to_message": replied} if replied else {})}}


@pytest.fixture
def case(engine, monkeypatch):  # noqa: F811
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    with Session(engine) as db:
        _, _, alert = seed(db)
    return engine, alert


def run(coro):
    return asyncio.run(coro)


def test_buttons_fit_telegrams_limit(case):
    _, alert = case
    assert [label for label, _ in telegram_replies.feedback_buttons(alert)] == ["Prompted review", "Already aware", "Too late",
                                                                                "Not useful", "Why?"]
    assert [label for label, _ in telegram_replies.rating_buttons(alert)] == ["Useful", "Already knew", "Too late", "Not useful"]
    for _, data in telegram_replies.feedback_buttons(alert) + telegram_replies.rating_buttons(alert) \
            + telegram_replies.rate_buttons(uuid.uuid4(), 179, "helped"):
        assert len(data.encode()) <= telegram.CALLBACK_MAX


def test_taps_from_another_chat_and_other_updates_are_ignored(case):
    db_engine, alert = case
    bot = Bot()
    replies = telegram_replies.Replies(db_engine, call=bot)
    assert run(replies.handle(tap(f"fb:{alert}:prompted_review", chat="999"))) is None
    assert run(replies.handle(tap(f"why:{alert}", sender="999"))) is None  # someone else in the owner's chat
    assert run(replies.handle({"update_id": 2, "message": {"chat": {"id": int(CHAT)}, "text": "hi"}})) is None  # no sender
    assert run(replies.handle(said("hi", sender="999"))) is None
    assert run(replies.handle(said("hi", chat="999"))) is None
    assert run(replies.handle(tap("nonsense:1"))) is None
    assert bot.calls == []
    with Session(db_engine) as db:
        assert db.exec(select(PositionAlertFeedback)).all() == []


def test_feedback_tap_saves_once_answers_and_marks_the_keyboard(case):
    db_engine, alert = case
    keyboard = rows(telegram_replies.feedback_buttons(alert)) + [[{"text": "Open", "url": "https://journal.example/x"}]]
    bot = Bot()
    replies = telegram_replies.Replies(db_engine, call=bot)
    assert run(replies.handle(tap(f"fb:{alert}:prompted_review", keyboard=keyboard))) == "fb"
    assert run(replies.handle(tap(f"fb:{alert}:prompted_review", update_id=2, keyboard=keyboard))) == "fb"  # a repeat
    with Session(db_engine) as db:
        [row] = db.exec(select(PositionAlertFeedback)).all()
        assert (row.alert_id, row.rating, row.version) == (alert, "prompted_review", 1)
    assert bot.named("answerCallbackQuery")[0] == {"callback_query_id": "q1", "text": "Saved: Prompted review."}
    edit = bot.named("editMessageReplyMarkup")[0]
    assert edit["chat_id"] == CHAT and edit["message_id"] == 55
    # All four answers, on both rows, give way to the saved one; Why? (from the second row) stays beside it.
    assert edit["reply_markup"]["inline_keyboard"] == [[{"text": "✓ Prompted review", "callback_data": f"done:{alert}"},
                                                        {"text": "Why?", "callback_data": f"why:{alert}"}],
                                                       [{"text": "Open", "url": "https://journal.example/x"}]]
    # The other answer tapped later cannot overwrite it; the keyboard shows what was saved.
    assert run(replies.handle(tap(f"fb:{alert}:already_aware", update_id=3, keyboard=keyboard))) == "fb"
    assert bot.named("answerCallbackQuery")[-1]["text"] == "Already answered: Prompted review."
    assert bot.named("editMessageReplyMarkup")[-1]["reply_markup"]["inline_keyboard"][0][0] == {
        "text": "✓ Prompted review", "callback_data": f"done:{alert}"}
    with Session(db_engine) as db:
        assert db.exec(select(PositionAlertFeedback.rating)).all() == ["prompted_review"]


def test_feedback_finds_the_current_trade_after_a_rebuild(case):
    db_engine, alert = case
    with Session(db_engine) as db:
        assert db.get(PositionAlert, alert).trade_id is not None  # an obsolete id in the fixture
    replies = telegram_replies.Replies(db_engine, call=Bot())
    run(replies.handle(tap(f"fb:{alert}:already_aware")))
    with Session(db_engine) as db:
        assert db.exec(select(PositionAlertFeedback.rating)).all() == ["already_aware"]


def test_radar_tap_writes_the_rating_once(case, tmp_path, monkeypatch):
    db_engine, _ = case
    fixture = json.loads((Path(__file__).parent / "fixtures" / "radar" / "sample_event.json").read_text())
    path = tmp_path / "radar.sqlite"
    monkeypatch.setenv("RADAR_ENABLED", "true")
    monkeypatch.setenv("RADAR_STORE", str(path))
    store = RadarStore(path)
    store.append_event(fixture["event"])
    event = fixture["event"]
    with Session(db_engine) as db:
        row = RadarAlert(event_id=event["event_id"], session_date=event["session_date"], rule_version=event["rule_version"],
                         kind=event["kind"], subject="AAA", title="Radar: AAA", body="b", first_seen_at=datetime(2026, 10, 20, 14))
        db.add(row)
        db.commit()
        radar_alert = row.id
    bot = Bot()
    replies = telegram_replies.Replies(db_engine, call=bot)
    assert run(replies.handle(tap(f"rr:{radar_alert}:useful"))) == "rr"
    assert run(replies.handle(tap(f"rr:{radar_alert}:useful", update_id=2))) == "rr"
    with store._db() as db:
        assert [tuple(r) for r in db.execute("SELECT event_id, rating FROM feedback")] == [(event["event_id"], "useful")]
    assert bot.named("answerCallbackQuery")[0]["text"] == "Saved: Useful."


def test_why_runs_one_fake_copilot_turn_and_replies_in_the_chat(case, monkeypatch):
    db_engine, alert = case
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setenv("COPILOT_BACKEND", "fake")
    monkeypatch.setenv("COPILOT_EVIDENCE", "fixture")
    from app.ai import copilot_spend
    monkeypatch.setattr(copilot_spend, "record", lambda *a, **k: None)
    bot = Bot()
    replies = telegram_replies.Replies(db_engine, call=bot)
    keyboard = rows(telegram_replies.feedback_buttons(alert))

    async def go():
        await replies.handle(tap(f"why:{alert}", keyboard=keyboard))
        await replies.handle(tap(f"why:{alert}", update_id=2, keyboard=keyboard))  # a double tap: one turn
        await asyncio.gather(*replies._tasks)
        await replies.handle(tap(f"why:{alert}", update_id=3, keyboard=keyboard))  # asked once per message

    run(go())
    assert [a["text"] for a in bot.named("answerCallbackQuery")] == ["Asking copilot…"] + 2 * ["Already asked; the answer comes in the chat."]
    [reply] = bot.named("sendMessage")
    assert reply["chat_id"] == CHAT and reply["reply_parameters"]["message_id"] == 55
    assert reply["text"].startswith("Verdict:") and len(reply["text"]) <= telegram_replies.ANSWER_MAX
    first, second = bot.named("editMessageReplyMarkup")[0]["reply_markup"]["inline_keyboard"]
    assert first == keyboard[0] and len(second) == 3  # the answers stay to tap
    assert second[-1] == {"text": "✓ Why? (answer below)", "callback_data": f"done:{alert}"}


def test_why_with_the_lab_off_says_so(case):
    db_engine, alert = case
    replies = telegram_replies.Replies(db_engine, call=Bot())
    assert run(replies.why_text(str(alert))) == "Copilot Lab is off on this server, so there is no answer here."


def test_the_poll_advances_its_offset_and_asks_for_taps_and_messages(case):
    db_engine, alert = case
    bot = Bot([tap(f"fb:{alert}:prompted_review", update_id=40), tap("done", update_id=41)])
    replies = telegram_replies.Replies(db_engine, call=bot)
    run(replies.poll_once())
    run(replies.poll_once())
    first, second = bot.named("getUpdates")
    assert first == {"timeout": telegram_replies.POLL_SECONDS, "allowed_updates": ["callback_query", "message"]}
    assert second["offset"] == 42


def test_startup_polls_only_when_telegram_is_set_up(monkeypatch):
    from fastapi import FastAPI
    from app import main
    started = []

    class Fake:
        def __init__(self, _engine, alerts_changed=None):
            self.alerts_changed = alerts_changed

        async def loop(self):
            started.append(1)

    monkeypatch.setattr(telegram_replies, "Replies", Fake)
    app = FastAPI()

    async def go():
        task = await main._maybe_start_telegram_replies(app)
        if task is not None:
            await task
        return task

    assert run(go()) is None and app.state.telegram_replies is None
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    assert run(go()) is not None and started == [1]


def lab_on(monkeypatch):
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setenv("COPILOT_BACKEND", "fake")
    monkeypatch.setenv("COPILOT_EVIDENCE", "fixture")
    from app.ai import copilot_spend
    monkeypatch.setattr(copilot_spend, "record", lambda *a, **k: None)


def test_a_typed_message_is_a_copilot_question_answered_as_a_reply(case, monkeypatch):
    db_engine, _ = case
    lab_on(monkeypatch)
    bot = Bot()
    replies = telegram_replies.Replies(db_engine, call=bot)

    async def go():
        assert await replies.handle(said("Should I trim NBIS here?")) == "ask"
        assert await replies.handle(said("And SPY?", update_id=2)) == "busy"  # one turn at a time
        await asyncio.gather(*replies._tasks)

    run(go())
    busy, answer = bot.named("sendMessage")
    assert busy["text"] == telegram_replies.BUSY and busy["reply_parameters"]["message_id"] == 62
    assert answer["chat_id"] == CHAT and answer["reply_parameters"]["message_id"] == 61
    assert answer["text"].startswith("Verdict:") and len(answer["text"]) <= telegram_replies.ANSWER_MAX


def test_a_reply_to_a_ping_carries_that_ping_as_context(case, monkeypatch):
    db_engine, alert = case
    lab_on(monkeypatch)
    asked = []

    async def turn(question, symbol, said=None):
        asked.append((question, symbol))
        return "ok"

    replies = telegram_replies.Replies(db_engine, call=Bot())
    monkeypatch.setattr(replies, "turn", turn)
    keyboard = [[{"text": label, "callback_data": data} for label, data in telegram_replies.feedback_buttons(alert)]]
    alert_ping = {"message_id": 55, "text": "SNDK give-back", "reply_markup": {"inline_keyboard": keyboard}}
    radar_ping = {"message_id": 56, "caption": "Radar: AAA +7.3% vs SPY",
                  "reply_markup": {"inline_keyboard": [[{"text": "Useful", "callback_data": "rr:x:useful"}]]}}
    run(replies.question_text("why now?", alert_ping))
    run(replies.question_text("is this real?", radar_ping))
    run(replies.question_text("hello", None))
    answered = {"message_id": 57, "text": "SNDK give-back", "reply_markup": {"inline_keyboard": [
        [{"text": "✓ Prompted review", "callback_data": f"done:{alert}"}, {"text": "✓ Why? (answer below)", "callback_data": f"done:{alert}"}]]}}
    run(replies.question_text("what if it gaps?", answered))  # both buttons used: the alert is still found
    with Session(db_engine) as db:
        from app.engine import position_alerts
        context = position_alerts.ask_context(db.get(PositionAlert, alert))
    assert asked[0] == (f"{context}\n\nMy question about this: why now?", "SNDK")
    assert asked[1] == ("Radar: AAA +7.3% vs SPY\n\nMy question about this: is this real?", None)
    assert asked[2] == ("hello", None)
    assert asked[3] == (f"{context}\n\nMy question about this: what if it gaps?", "SNDK")


def test_commands_get_the_help_note_and_the_lab_off_says_so(case):
    db_engine, _ = case
    bot = Bot()
    replies = telegram_replies.Replies(db_engine, call=bot)
    assert run(replies.handle(said("/start"))) == "help"
    assert bot.named("sendMessage")[0]["text"] == telegram_replies.HELP
    assert run(replies.question_text("hi", None)) == "Copilot Lab is off on this server, so there is no answer here."
    assert replies._rate_row() == ()  # nothing saved, so nothing to rate


def scored_turn(monkeypatch, db_engine) -> str:
    """A scripted Telegram turn whose ``copilot_turn`` row is a real (not fake) one, so the scorecard meets the answer."""
    from app.ai import copilot_spend
    from app.models import CopilotTurn
    with Session(db_engine) as db:
        row = CopilotTurn(backend="anthropic", billing="api", kind="ask", source="telegram")
        db.add(row)
        db.commit()
        turn_id = str(row.id)

    async def scripted(*args, **kwargs):
        yield {"type": "text", "delta": "Verdict: Hold. Above 95 the trade is intact."}
        yield {"type": "done", "turn_id": turn_id}
    monkeypatch.setattr(copilot_spend, "recorded_turn", scripted)
    return turn_id


@pytest.mark.parametrize("old_thread", [False, True])
def test_helped_and_didnt_under_an_answer_rate_it_as_the_desk_does_and_the_scorecard_counts_it(case, monkeypatch, old_thread):
    from datetime import timedelta
    from app.engine import copilot_investigations
    from app.models import CopilotInvestigation
    from app.routers import copilot as copilot_routes
    db_engine, alert = case
    lab_on(monkeypatch)
    turn_id = scored_turn(monkeypatch, db_engine)
    replied = None
    if old_thread:  # the symbol's thread, started long before the scorecard's window: the answer's turn id still counts it
        with Session(db_engine) as db:
            thread = copilot_investigations.create(copilot_investigations.InvestigationFields(
                title="SNDK", symbol="SNDK", transcript=[{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]), session=db)
            row = db.get(CopilotInvestigation, uuid.UUID(thread["id"]))
            row.created_at = row.updated_at = datetime.utcnow() - timedelta(days=30)
            db.add(row)
            db.commit()
        monkeypatch.setattr(telegram_replies, "thread_for", lambda db_, symbol: thread["id"])
        replied = {"message_id": 50, "text": "SNDK give-back", "reply_markup": {"inline_keyboard": rows(telegram_replies.feedback_buttons(alert))}}
    bot = Bot()
    replies = telegram_replies.Replies(db_engine, call=bot)

    async def go():
        assert await replies.handle(said("Hold or trim?", replied=replied)) == "ask"
        await asyncio.gather(*replies._tasks)
    run(go())
    [answer] = bot.named("sendMessage")
    assert answer["text"] == "Verdict: Hold. Above 95 the trade is intact." and answer["reply_parameters"]["message_id"] == 61
    [[helped, didnt]] = answer["reply_markup"]["inline_keyboard"]
    key, index = helped["callback_data"].split(":")[1:3]
    assert helped == {"text": "Helped", "callback_data": f"hd:{key}:{index}:h"}
    assert didnt == {"text": "Didn't", "callback_data": f"hd:{key}:{index}:d"}
    with Session(db_engine) as db:
        saved = copilot_investigations.get(key, session=db)
    assert saved["main_day"] is None if old_thread else saved["main_day"] is not None
    if old_thread:
        assert saved["id"] == thread["id"] and int(index) == 3
    message = saved["transcript"][int(index)]
    assert message["content"] == answer["text"] and message["metrics"] == {"turn_id": turn_id}

    def rating():
        with Session(db_engine) as db:
            return copilot_investigations.get(key, session=db)["transcript"][int(index)].get("rating")

    def last_keyboard():
        return bot.named("editMessageReplyMarkup")[-1]["reply_markup"]["inline_keyboard"]

    def scorecard():
        with Session(db_engine) as db:
            return copilot_routes.answer_scorecard(days=7, session=db)

    keyboard = answer["reply_markup"]["inline_keyboard"]
    assert run(replies.handle(tap(helped["callback_data"], keyboard=keyboard, update_id=2))) == "hd"
    assert rating() == "helped" and bot.named("answerCallbackQuery")[-1]["text"] == "Saved: Helped."
    keyboard = last_keyboard()
    assert keyboard == [[{"text": "✓ Helped", "callback_data": f"hd:{key}:{index}:n"}, didnt]]
    card = scorecard()
    assert (card["answers"]["total"], card["answers"]["rated"], card["answers"]["helped"]) == (1, 1, 1)
    assert card["by_source"]["telegram"]["helped"] == 1

    # The other button changes the rating, as the desk allows; the checked one clears it, as the desk's toggle does.
    run(replies.handle(tap(didnt["callback_data"], keyboard=keyboard, update_id=3)))
    assert rating() == "didnt" and bot.named("answerCallbackQuery")[-1]["text"] == "Saved: Didn't."
    keyboard = last_keyboard()
    assert keyboard == [[helped, {"text": "✓ Didn't", "callback_data": f"hd:{key}:{index}:n"}]]
    assert (scorecard()["answers"]["helped"], scorecard()["answers"]["didnt"]) == (0, 1)
    run(replies.handle(tap(keyboard[0][1]["callback_data"], keyboard=keyboard, update_id=4)))
    assert rating() is None and bot.named("answerCallbackQuery")[-1]["text"] == "Rating cleared."
    assert last_keyboard() == [[helped, didnt]] and scorecard()["answers"]["rated"] == 0


def test_a_rating_tap_that_matches_no_saved_answer_saves_nothing(case):
    db_engine, _ = case
    bot = Bot()
    replies = telegram_replies.Replies(db_engine, call=bot)
    assert run(replies.handle(tap("hd:nothex:1:h"))) == "hd"
    assert run(replies.handle(tap(f"hd:{uuid.uuid4().hex}:1:h", update_id=2))) == "hd"
    assert run(replies.handle(tap(f"hd:{uuid.uuid4().hex}:1:x", update_id=3))) == "hd"
    assert [a["text"] for a in bot.named("answerCallbackQuery")] == [
        "That button is not one the app knows.", "No such investigation.", "That button is not one the app knows."]
    assert bot.named("editMessageReplyMarkup") == []


def test_why_while_a_question_runs_says_busy_and_can_be_asked_later(case, monkeypatch):
    db_engine, alert = case
    lab_on(monkeypatch)
    bot = Bot()
    replies = telegram_replies.Replies(db_engine, call=bot)

    async def go():
        await replies.handle(said("how's my book?"))
        assert await replies.handle(tap(f"why:{alert}")) == "why"
        await asyncio.gather(*replies._tasks)
        await replies.handle(tap(f"why:{alert}", update_id=2))
        await asyncio.gather(*replies._tasks)

    run(go())
    assert [a["text"] for a in bot.named("answerCallbackQuery")] == [telegram_replies.BUSY, "Asking copilot…"]
    assert len(bot.named("sendMessage")) == 2  # the question's answer, then Why?'s


def test_a_typed_question_past_the_daily_budget_is_refused_before_any_turn(case, monkeypatch):
    db_engine, _ = case
    lab_on(monkeypatch)
    monkeypatch.setenv("COPILOT_BACKEND", "anthropic")
    monkeypatch.setenv("COPILOT_DAILY_BUDGET_USD", "1.5")
    from app.ai import copilot, copilot_spend
    monkeypatch.setattr(copilot_spend, "spent_today", lambda: 1.5)
    monkeypatch.setattr(copilot, "adapter_for", lambda cfg: pytest.fail("a turn was built past the budget"))
    replies = telegram_replies.Replies(db_engine, call=Bot())
    assert run(replies.question_text("hi", None)) == "Today's copilot API budget ($1.50) is spent."


def test_a_card_the_chat_cannot_show_is_named_with_a_pointer_to_the_desk(case, monkeypatch):
    db_engine, _ = case
    lab_on(monkeypatch)
    from app.ai import copilot_spend

    async def scripted(*args, **kwargs):
        yield {"type": "text", "delta": "Verdict: Wait. A deeper read would help."}
        yield {"type": "proposal", "kind": "revisit", "question": "Is the AI trade topping?", "horizon_days": 0}
        yield {"type": "done"}
    monkeypatch.setattr(copilot_spend, "recorded_turn", scripted)
    answer = run(telegram_replies.Replies(db_engine, call=Bot()).turn("Is this the top?", None))
    assert answer.startswith("Verdict: Wait.") and "only be confirmed on the desk: Is the AI trade topping?" in answer


def ping(data: str, text: str | None, update_id=1, keyboard=None) -> dict:
    update = tap(data, update_id=update_id, keyboard=keyboard)
    if text is not None:
        update["callback_query"]["message"]["text"] = text
    return update


def test_why_on_any_ping_asks_copilot_about_that_pings_text(case, monkeypatch):
    db_engine, _ = case
    lab_on(monkeypatch)
    bot = Bot()
    replies = telegram_replies.Replies(db_engine, call=bot)
    asked = []

    async def turn(question, symbol, said=None):
        asked.append((question, symbol))
        return "Verdict: Watch. The group is moving with it."
    monkeypatch.setattr(replies, "turn", turn)
    keyboard = [[{"text": "Useful", "callback_data": "rr:9:useful"}, {"text": "Why?", "callback_data": "ask:radar_event"}]]
    text = "Radar: AMD +4.2% vs SPY\nSemis leading; first seen 10:05"

    async def go():
        assert await replies.handle(ping("ask:radar_event", text, keyboard=keyboard)) == "ask"
        await replies.handle(ping("ask:radar_event", text, update_id=2, keyboard=keyboard))  # a double tap: one turn
        await asyncio.gather(*replies._tasks)

    run(go())
    [(question, symbol)] = asked
    # The ping's one name (its rr: row is gone, so from the text; "vs SPY" is the yardstick) goes with the question.
    assert question.startswith(text) and telegram_replies.WHY_QUESTION in question and symbol == "AMD"
    [reply] = bot.named("sendMessage")
    assert reply["text"].startswith("Verdict: Watch.") and reply["reply_parameters"]["message_id"] == 55
    assert [a["text"] for a in bot.named("answerCallbackQuery")] == ["Asking copilot…", "Already asked; the answer comes in the chat."]
    row = bot.named("editMessageReplyMarkup")[0]["reply_markup"]["inline_keyboard"][0]
    assert row == [{"text": "Useful", "callback_data": "rr:9:useful"}, {"text": "✓ Why? (answer below)", "callback_data": "done:radar_event"}]


def test_a_rated_radar_ping_keeps_its_why(case):
    db_engine, _ = case
    bot = Bot()
    replies = telegram_replies.Replies(db_engine, call=bot)
    keyboard = [[{"text": "Useful", "callback_data": "rr:00000000-0000-0000-0000-000000000000:useful"},
                 {"text": "Why?", "callback_data": "ask:radar_event"}]]
    replies._mark({"message_id": 55, "reply_markup": {"inline_keyboard": keyboard}}, keyboard[0][0]["callback_data"], "Useful")
    row = bot.named("editMessageReplyMarkup")[0]["reply_markup"]["inline_keyboard"][0]
    assert row[1] == {"text": "Why?", "callback_data": "ask:radar_event"}


def test_why_on_a_ping_too_old_to_read_says_so(case, monkeypatch):
    db_engine, _ = case
    lab_on(monkeypatch)
    bot = Bot()
    replies = telegram_replies.Replies(db_engine, call=bot)
    monkeypatch.setattr(replies, "turn", lambda *a: pytest.fail("no turn without the ping's text"))

    async def go():
        await replies.handle(ping("ask:thesis_watch", None))
        await asyncio.gather(*replies._tasks)

    run(go())
    assert "no longer shows that ping's text" in bot.named("sendMessage")[0]["text"]


# ------------------------------------------------------------------ voice notes and photos

OGG = b"OggS" + b"\0" * 2000  # an Ogg clip by its first bytes; the transcriber is stubbed


class FileBot(Bot):
    """``Bot`` that also answers ``getFile``."""

    def __call__(self, name, *, json=None, timeout=None, **_):
        if name == "getFile":
            self.calls.append((name, json))
            return {"file_id": json["file_id"], "file_path": f"docs/{json['file_id']}"}
        return super().__call__(name, json=json, timeout=timeout)


@pytest.fixture
def files(monkeypatch):
    """Telegram's file host, stubbed: ``files[file_id] = bytes``; every GET is recorded in ``files["gets"]``."""
    import contextlib
    held = {"gets": []}

    @contextlib.contextmanager
    def stream(verb, url, **kwargs):
        held["gets"].append(url)
        file_id = url.rsplit("/", 1)[1]
        yield httpx.Response(200, content=held[file_id]) if file_id in held else httpx.Response(404)

    monkeypatch.setattr(httpx, "stream", stream)
    return held


@pytest.fixture
def whisper(monkeypatch):
    from app.engine import transcribe
    heard = []
    monkeypatch.setattr(transcribe, "status", lambda: transcribe.Status(True, "Whisper (test)", "test"))

    def fake(data, extension, prompt=None):
        heard.append((len(data), extension, prompt))
        return "should I trim NBIS here"
    monkeypatch.setattr(transcribe, "transcribe_bytes", fake)
    return heard


def voice(update_id=1, duration=6, size=2004, chat=CHAT, sender=None, kind="voice") -> dict:
    return {"update_id": update_id, "message": {"message_id": 60 + update_id, "chat": {"id": int(chat)}, "from": {"id": int(sender or chat)},
                                                kind: {"file_id": "v1", "duration": duration, "mime_type": "audio/ogg", "file_size": size}}}


def photo(update_id=1, caption=None, document=None) -> dict:
    body = {"document": document} if document else {"photo": [
        {"file_id": "small", "width": 90, "height": 60, "file_size": 900}, {"file_id": "big", "width": 1280, "height": 853, "file_size": 9000}]}
    return {"update_id": update_id, "message": {"message_id": 60 + update_id, "chat": {"id": int(CHAT)}, "from": {"id": int(CHAT)},
                                                **body, **({"caption": caption} if caption else {})}}


def test_download_reads_to_the_cap_and_never_logs_the_token(monkeypatch, files, caplog):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    files["f1"] = b"x" * 10
    bot = FileBot()
    assert telegram.download("f1", 10, call=bot) == b"x" * 10
    assert bot.named("getFile") == [{"file_id": "f1"}] and files["gets"] == [f"https://api.telegram.org/file/bot{TOKEN}/docs/f1"]
    with pytest.raises(telegram.FileTooLarge):
        telegram.download("f1", 9, call=bot)
    with pytest.raises(telegram.TelegramError) as refused:
        telegram.download("missing", 10, call=bot)
    assert TOKEN not in str(refused.value) and TOKEN not in caplog.text


def test_a_voice_note_is_heard_confirmed_asked_and_saved_on_the_desk(case, monkeypatch, files, whisper):
    db_engine, _ = case
    lab_on(monkeypatch)
    files["v1"] = OGG
    bot = FileBot()
    replies = telegram_replies.Replies(db_engine, call=bot)
    saved = []
    monkeypatch.setattr(telegram_replies, "save_on_desk", lambda db, said, symbol, answer, now, plans=(), **_: saved.append(said) or (str(uuid.UUID(int=1)), 1))

    async def go():
        assert await replies.handle(voice()) == "voice"
        assert await replies.handle(voice(update_id=2)) == "busy"  # one turn at a time
        await asyncio.gather(*replies._tasks)

    run(go())
    assert whisper[0][:2] == (len(OGG), "ogg") and whisper[0][2]  # primed with the owner's tickers
    busy, heard, answer = bot.named("sendMessage")
    assert busy["text"] == telegram_replies.BUSY
    assert heard["text"] == "Heard: should I trim NBIS here" and heard["reply_parameters"]["message_id"] == 61
    assert answer["text"].startswith("Verdict:") and answer["reply_parameters"]["message_id"] == 61
    assert saved == ["should I trim NBIS here"]


def test_audio_files_are_taken_like_voice_notes(case, monkeypatch, files, whisper):
    db_engine, _ = case
    lab_on(monkeypatch)
    files["v1"] = OGG
    bot = FileBot()
    replies = telegram_replies.Replies(db_engine, call=bot)

    async def go():
        assert await replies.handle(voice(kind="audio")) == "voice"
        await asyncio.gather(*replies._tasks)

    run(go())
    assert bot.named("sendMessage")[0]["text"].startswith("Heard:")


@pytest.mark.parametrize("duration,size", [(31, 2004), (10, 3_000_001)])
def test_a_voice_note_too_long_or_too_large_is_refused_before_any_download(case, files, whisper, duration, size):
    db_engine, _ = case
    bot = FileBot()
    replies = telegram_replies.Replies(db_engine, call=bot)
    assert run(replies.handle(voice(duration=duration, size=size))) == "refused"
    assert bot.named("sendMessage")[0]["text"] == telegram_replies.VOICE_TOO_LONG
    assert not bot.named("getFile") and not files["gets"] and not whisper


def test_a_voice_note_larger_than_telegram_said_is_cut_off_at_the_cap(case, files, whisper):
    db_engine, _ = case
    files["v1"] = b"OggS" + b"\0" * 3_000_000
    bot = FileBot()
    replies = telegram_replies.Replies(db_engine, call=bot)

    async def go():
        await replies.handle(voice())
        await asyncio.gather(*replies._tasks)

    run(go())
    assert [m["text"] for m in bot.named("sendMessage")] == [telegram_replies.VOICE_TOO_LONG] and not whisper


def test_a_voice_note_without_a_transcriber_gets_its_note(case, monkeypatch, files):
    from app.engine import transcribe
    db_engine, _ = case
    monkeypatch.setenv("CAPTURE_TRANSCRIBER", "off")
    bot = FileBot()
    replies = telegram_replies.Replies(db_engine, call=bot)
    assert run(replies.handle(voice())) == "refused"
    assert bot.named("sendMessage")[0]["text"] == transcribe.status().note and not bot.named("getFile")


def test_a_failed_transcription_says_so_and_asks_nothing(case, monkeypatch, files):
    from app.engine import transcribe
    db_engine, _ = case
    files["v1"] = OGG
    monkeypatch.setattr(transcribe, "status", lambda: transcribe.Status(True, "Whisper (test)", "test"))

    def broken(*a, **k):
        raise transcribe.TranscriptionError("The speech-to-text engine could not read this clip.")
    monkeypatch.setattr(transcribe, "transcribe_bytes", broken)
    bot = FileBot()
    replies = telegram_replies.Replies(db_engine, call=bot)
    monkeypatch.setattr(replies, "turn", lambda *a, **k: pytest.fail("no turn without words"))

    async def go():
        await replies.handle(voice())
        await asyncio.gather(*replies._tasks)

    run(go())
    assert [m["text"] for m in bot.named("sendMessage")] == ["The speech-to-text engine could not read this clip."]


def test_messages_from_anyone_else_are_ignored_before_any_download(case, files, whisper):
    db_engine, _ = case
    bot = FileBot()
    replies = telegram_replies.Replies(db_engine, call=bot)
    assert run(replies.handle(voice(sender=999))) is None
    assert run(replies.handle(voice(chat=999))) is None
    stranger = photo()
    stranger["message"]["from"] = {"id": 999}
    assert run(replies.handle(stranger)) is None
    assert bot.calls == [] and not files["gets"] and not whisper


@pytest.fixture
def image_store(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPTURE_STORAGE_DIR", str(tmp_path))
    return tmp_path / "copilot-images"


def scripted_turn(monkeypatch, seen):
    from app.ai import copilot_spend

    async def scripted(history, symbol, *args, images=None, **kwargs):
        seen.append({"question": history[-1]["content"], "images": images})
        yield {"type": "text", "delta": "Verdict: Matches."}
        yield {"type": "done"}
    monkeypatch.setattr(copilot_spend, "recorded_turn", scripted)


def test_a_photo_with_a_caption_asks_it_with_the_image_attached_then_deletes_it(case, monkeypatch, files, image_store):
    from tests.test_copilot_images import png
    db_engine, _ = case
    lab_on(monkeypatch)
    files["big"] = png()
    seen, saved = [], []
    scripted_turn(monkeypatch, seen)
    monkeypatch.setattr(telegram_replies, "save_on_desk", lambda db, said, symbol, answer, now, plans=(), **_: saved.append(said) or (str(uuid.UUID(int=1)), 1))
    bot = FileBot()
    replies = telegram_replies.Replies(db_engine, call=bot)

    async def go():
        assert await replies.handle(photo(caption="Is my NBIS call still on?")) == "photo"
        assert await replies.handle(photo(update_id=2)) == "busy"
        await asyncio.gather(*replies._tasks)

    run(go())
    assert bot.named("getFile") == [{"file_id": "big"}]  # the largest size
    assert seen[0]["question"] == "Is my NBIS call still on?"
    assert [b["source"]["media_type"] for b in seen[0]["images"]] == ["image/jpeg"]
    assert saved == ["(photo) Is my NBIS call still on?"]
    assert [m["text"] for m in bot.named("sendMessage")] == [telegram_replies.BUSY, "Verdict: Matches."]
    assert list(image_store.glob("*.jpg")) == []  # deleted when the turn ended


def test_a_photo_without_a_caption_asks_the_reconcile_question_and_an_image_document_counts(case, monkeypatch, files, image_store):
    from tests.test_copilot_images import png
    db_engine, _ = case
    lab_on(monkeypatch)
    files["doc"] = png()
    seen = []
    scripted_turn(monkeypatch, seen)
    bot = FileBot()
    replies = telegram_replies.Replies(db_engine, call=bot)

    async def go():
        assert await replies.handle(photo(document={"file_id": "doc", "mime_type": "image/png", "file_size": 9000})) == "photo"
        await asyncio.gather(*replies._tasks)

    run(go())
    assert seen[0]["question"] == telegram_replies.RECONCILE_QUESTION and len(seen[0]["images"]) == 1
    assert list(image_store.glob("*.jpg")) == []


def test_a_failed_photo_turn_still_deletes_the_image_and_says_so(case, monkeypatch, files, image_store):
    from tests.test_copilot_images import png
    from app.ai import copilot_spend
    db_engine, _ = case
    lab_on(monkeypatch)
    files["big"] = png()

    async def broken(*a, **k):
        raise RuntimeError("boom")
        yield
    monkeypatch.setattr(copilot_spend, "recorded_turn", broken)
    bot = FileBot()
    replies = telegram_replies.Replies(db_engine, call=bot)

    async def go():
        await replies.handle(photo())
        await asyncio.gather(*replies._tasks)

    run(go())
    assert [m["text"] for m in bot.named("sendMessage")] == [telegram_replies.FAILED]
    assert list(image_store.glob("*.jpg")) == []


def test_a_document_that_is_not_an_image_is_ignored(case, files):
    db_engine, _ = case
    bot = FileBot()
    replies = telegram_replies.Replies(db_engine, call=bot)
    assert run(replies.handle(photo(document={"file_id": "pdf", "mime_type": "application/pdf"}))) is None
    assert bot.calls == [] and not files["gets"]


# ------------------------------------------------------------------ plan cards

PLAN_EVENT = {"type": "proposal", "id": "toolu_01PlanNBIS", "kind": "trade_plan", "symbol": "NBIS", "direction": "long",
              "instrument": "calls", "contract": "NBIS 100C 11/21", "thesis": "Holds the base above 95",
              "entry_trigger": {"condition": "crosses", "price": 100.0, "interval": None},
              "invalidation": {"condition": "closes_beyond", "price": 95.0, "interval": "5m"},
              "time_stop": "out by 15:30", "size_note": None, "last": 98.0, "as_of": 1_762_440_000.0}
PLAN_CARD = {k: v for k, v in PLAN_EVENT.items() if k != "type"}


def plan_turn(monkeypatch):
    from app.ai import copilot_spend

    async def scripted(*args, **kwargs):
        yield {"type": "text", "delta": "Verdict: Plan it. Wait for 100."}
        yield PLAN_EVENT
        yield {"type": "done"}
    monkeypatch.setattr(copilot_spend, "recorded_turn", scripted)


def ask_plan(db_engine, monkeypatch, bot, quote=(98.0, True)):
    lab_on(monkeypatch)
    plan_turn(monkeypatch)
    changed = []
    replies = telegram_replies.Replies(db_engine, call=bot, alerts_changed=lambda: changed.append(1))
    replies.quote = lambda symbol: quote

    async def go():
        assert await replies.handle(said("Plan NBIS for me?")) == "ask"
        await asyncio.gather(*replies._tasks)
    run(go())
    return replies, changed


def card_data(bot) -> str:
    card = next(m for m in bot.named("sendMessage") if m.get("text", "").startswith("Proposed trade plan"))
    return card["reply_markup"]["inline_keyboard"][0][0]["callback_data"]


def test_a_proposed_plan_is_saved_as_the_desk_saves_it_and_sent_after_the_answer_with_confirm_and_edit(case, monkeypatch):
    from app.engine import copilot_investigations
    from app.models import CopilotInvestigation
    db_engine, _ = case
    monkeypatch.setenv("ALERT_APP_URL", "https://journal.example/")
    bot = Bot()
    ask_plan(db_engine, monkeypatch, bot)
    answer, card = bot.named("sendMessage")
    assert answer["text"].startswith("Verdict: Plan it.") and "only be confirmed on the desk" not in answer["text"]
    lines = card["text"].splitlines()
    assert lines[:5] == ["Proposed trade plan · NBIS · Buy calls · NBIS 100C 11/21", "Thesis: Holds the base above 95",
                         "Entry: crosses 100", "Invalidation: 5m close beyond 95", "Time stop: out by 15:30"]
    assert lines[5] in ("Horizon: Day trade", "Horizon: Swing") and lines[6] == telegram_replies.PLAN_FOOTER
    assert card["reply_parameters"]["message_id"] == 61
    (confirm,), (edit,) = card["reply_markup"]["inline_keyboard"]
    assert confirm["text"] == "Confirm" and confirm["callback_data"].startswith("pl:") and confirm["callback_data"].endswith(":confirm")
    assert len(confirm["callback_data"].encode()) <= telegram.CALLBACK_MAX
    key = confirm["callback_data"].split(":")[1]
    with Session(db_engine) as db:
        thread_id, saved = telegram_replies.find_plan(db, key)
        main = db.exec(select(CopilotInvestigation).where(CopilotInvestigation.main_day.is_not(None))).one()
        thread = copilot_investigations.get(thread_id, session=db)
        assert thread["main_day"] is None and thread["symbol"] == "NBIS"
        # The desk's shape: the proposal without its event type (last and as_of kept), its id as Main chat numbers it, a client id.
        assert saved == {**PLAN_CARD, "id": saved["id"], "client_id": key}
        assert copilot_investigations.main_plan_thread(db, str(main.id), saved["id"])["id"] == thread_id
        main_card = json.loads(main.transcript_json)[-1]["proposals"][0]
        assert main_card["client_id"] == key and main_card["id"] == saved["id"]
    assert edit == {"text": "Edit", "url": f"https://journal.example/copilot-lab?investigation={thread_id}"}


def test_a_plan_on_the_symbols_thread_keeps_its_id_made_unique_in_the_conversation(case, monkeypatch):
    from app.engine import copilot_investigations
    db_engine, _ = case
    with Session(db_engine) as db:
        thread = copilot_investigations.create(copilot_investigations.InvestigationFields(
            title="NBIS", symbol="NBIS", transcript=[{"role": "user", "content": "q"},
                                                     {"role": "assistant", "content": "a", "proposals": [PLAN_CARD]}]), session=db)
        monkeypatch.setattr(telegram_replies, "thread_for", lambda db_, symbol: thread["id"])
        card = {**PLAN_CARD, "client_id": "a" * 32}
        target, index = telegram_replies.save_on_desk(db, "Plan it?", "NBIS", "Verdict: Plan it.", datetime(2026, 11, 6, 15), [card])
        assert (target, index) == (thread["id"], 3)
        last = copilot_investigations.get(target, session=db)["transcript"][-1]
        assert last["proposals"] == [{**card, "id": "toolu_01PlanNBIS.2"}]
        assert telegram_replies.find_plan(db, "a" * 32) == (thread["id"], last["proposals"][0])


FRIDAY_10 = datetime(2026, 11, 6, 10, tzinfo=ZoneInfo("America/New_York")).timestamp()


def saved_plan(db_engine, key):
    """The card's capture, level alerts, time stops, horizon entries and outcome as stored."""
    from app.models import DayJournalEntry, LevelAlert, PlanTimeStop, TradeCapture
    with Session(db_engine) as db:
        thread_id, card = telegram_replies.find_plan(db, key)
        return (thread_id, db.exec(select(TradeCapture)).all(), db.exec(select(LevelAlert)).all(), db.exec(select(PlanTimeStop)).all(),
                db.exec(select(DayJournalEntry).where(DayJournalEntry.kind == "horizon")).all(), card.get("outcome"))


def confirm(db_engine, key, last=98.0, fresh=True, armed=None):
    return telegram_replies.confirm_plan(db_engine, key, quote=lambda s: (last, fresh), now=FRIDAY_10, armed=armed)


def test_confirm_saves_the_plan_then_arms_both_alerts_and_the_time_stop_as_the_desk_does(case, monkeypatch):
    from tests.test_exit_habits import ROTH
    db_engine, _ = case
    bot = Bot()
    ask_plan(db_engine, monkeypatch, bot)
    monkeypatch.setattr(telegram_replies, "_calendar", lambda: None)
    key = card_data(bot).split(":")[1]
    armed = []
    assert confirm(db_engine, key, armed=lambda: armed.append(1)) == (
        "Plan saved\nEntry alert armed at 100.00\nInvalidation armed at 95.00\nTime stop set: today 15:30 ET", "Confirmed")
    assert confirm(db_engine, key) == ("Already confirmed: the plan is saved and its alerts are armed.", "Confirmed")
    thread_id, (capture,), alerts, (stop,), (horizon,), outcome = saved_plan(db_engine, key)
    # The desk's savePlanCapture: discretionary, "Copilot plan", the side from direction and instrument, the card's client id.
    assert (capture.client_id, capture.account_id, capture.underlying, capture.side, capture.mode, capture.setup_label) == (
        key, ROTH, "NBIS", "buy_calls", "discretionary", "Copilot plan")
    assert capture.wording == "Entry: crosses 100. Invalidation: 5m close beyond 95. Time stop: out by 15:30."
    assert capture.note == "Thesis: Holds the base above 95 Contract: NBIS 100C 11/21. From a Copilot Lab plan card."
    assert (capture.origin_kind, capture.origin_ref, json.loads(capture.context_json)["investigation_id"]) == ("copilot", thread_id, thread_id)
    assert sorted((a.plan_role, a.price, a.condition, a.interval, a.source_kind, a.source_id, a.label, a.state) for a in alerts) == [
        ("entry", 100.0, "crosses", None, "copilot", thread_id, "NBIS entry: crosses 100", "active"),
        ("invalidation", 95.0, "closes_beyond", "5m", "copilot", thread_id, "NBIS invalidation: 5m close beyond 95", "active")]
    assert (stop.client_id, stop.investigation_id, stop.symbol, stop.text) == (key, thread_id, "NBIS", "out by 15:30")
    assert (horizon.operation_id, horizon.symbol, horizon.text) == (f"horizon-{key}-day", "NBIS", "Day trade")
    assert outcome["state"] == "confirmed" and outcome["note"].startswith(telegram_replies.FROM_TELEGRAM_NOTE)
    assert outcome["parts"] == {
        "plan": {"state": "done", "text": "Saved as your pre-trade plan. It is suggested for the trade when the fill arrives."},
        "entry": {"state": "done", "text": "Set: NBIS crosses 100."},
        "invalidation": {"state": "done", "text": "Set: NBIS 5m close beyond 95."},
        "timeStop": {"state": "done", "text": "Set for today 15:30 ET."}}
    assert outcome["fields"] == {"thesis": PLAN_EVENT["thesis"], "contract": "NBIS 100C 11/21", "entry": "100", "invalidation": "95",
                                 "time_stop": "out by 15:30", "size_note": "", "horizon": "day"}
    assert armed == [1]


def test_a_tap_lists_each_part_and_marks_the_card_confirmed(case, monkeypatch):
    db_engine, _ = case
    bot = Bot()
    replies, changed = ask_plan(db_engine, monkeypatch, bot)
    monkeypatch.setattr(telegram_replies, "_calendar", lambda: None)
    data = card_data(bot)
    keyboard = [[{"text": "Confirm", "callback_data": data}]]
    assert run(replies.handle(tap(data, keyboard=keyboard, update_id=5))) == "pl"
    assert run(replies.handle(tap(data, keyboard=keyboard, update_id=6))) == "pl"  # a second tap saves and arms nothing more
    first, second = [a["text"] for a in bot.named("answerCallbackQuery")]
    assert first.splitlines()[:3] == ["Plan saved", "Entry alert armed at 100.00", "Invalidation armed at 95.00"]
    assert first.splitlines()[3].startswith("Time stop set: ")
    assert second == "Already confirmed: the plan is saved and its alerts are armed."
    assert bot.named("editMessageReplyMarkup")[0]["reply_markup"]["inline_keyboard"][0][0]["text"] == "✓ Confirmed"
    _, captures_, alerts, stops, _, _ = saved_plan(db_engine, data.split(":")[1])
    assert (len(captures_), len(alerts), len(stops)) == (1, 2, 1)
    assert changed == [1]


def test_a_crossed_invalidation_is_refused_the_rest_completes_and_a_second_tap_retries_only_it(case, monkeypatch):
    db_engine, _ = case
    bot = Bot()
    ask_plan(db_engine, monkeypatch, bot)
    monkeypatch.setattr(telegram_replies, "_calendar", lambda: None)
    key = card_data(bot).split(":")[1]
    assert confirm(db_engine, key, last=94.0) == (
        "Plan saved\nEntry alert armed at 100.00\n"
        "Invalidation failed: NBIS is at 94, already past the invalidation at 95, so it was not set.\nTime stop set: today 15:30 ET", None)
    _, captures_, alerts, stops, _, outcome = saved_plan(db_engine, key)
    assert (len(captures_), [a.plan_role for a in alerts], len(stops)) == (1, ["entry"], 1)
    assert {part: r["state"] for part, r in outcome["parts"].items()} == {
        "plan": "done", "entry": "done", "invalidation": "failed", "timeStop": "done"}
    assert confirm(db_engine, key, last=98.0) == ("Invalidation armed at 95.00", "Confirmed")
    _, captures_, alerts, stops, horizons, outcome = saved_plan(db_engine, key)
    assert (len(captures_), sorted(a.plan_role for a in alerts), len(stops), len(horizons)) == (1, ["entry", "invalidation"], 1, 1)
    assert all(r["state"] == "done" for r in outcome["parts"].values())


def test_with_no_account_for_plans_confirm_saves_nothing_and_says_so(case, monkeypatch):
    import uuid as uuid_
    from app.engine import captures
    from app.models import Account
    db_engine, _ = case
    bot = Bot()
    ask_plan(db_engine, monkeypatch, bot)
    monkeypatch.setattr(telegram_replies, "_calendar", lambda: None)
    key = card_data(bot).split(":")[1]
    second = uuid_.uuid4()
    with Session(db_engine) as db:
        db.add(Account(id=second, name="Second", type="individual", last4="1111", broker="robinhood"))
        db.commit()
    assert confirm(db_engine, key) == ("Set a default account for plans on the desk first; nothing was saved.", None)
    assert saved_plan(db_engine, key)[1:] == ([], [], [], [], None)
    with Session(db_engine) as db:
        captures.set_default_account(db, second)
    assert confirm(db_engine, key)[1] == "Confirmed"
    assert saved_plan(db_engine, key)[1][0].account_id == second


def test_a_plan_confirmed_on_the_desk_or_dismissed_arms_nothing(case, monkeypatch):
    from app.engine import copilot_investigations as inv
    from app.models import LevelAlert
    db_engine, _ = case
    bot = Bot()
    ask_plan(db_engine, monkeypatch, bot)
    key = card_data(bot).split(":")[1]
    with Session(db_engine) as db:
        thread_id, card = telegram_replies.find_plan(db, key)
        inv.set_outcome(thread_id, card["id"], inv.ProposalOutcome(state="dismissed"), session=db)
    assert telegram_replies.confirm_plan(db_engine, key, quote=lambda s: (98.0, True)) == (
        "Not confirmed: this plan was dismissed on the desk.", None)
    with Session(db_engine) as db:
        inv.set_outcome(thread_id, card["id"], inv.ProposalOutcome(state="confirmed", parts={"plan": {"state": "done", "text": "Saved."}}),
                        session=db)
    assert telegram_replies.confirm_plan(db_engine, key, quote=lambda s: (98.0, True)) == ("Already confirmed on the desk.", "Confirmed")
    with Session(db_engine) as db:
        assert db.exec(select(LevelAlert)).all() == []


@pytest.mark.parametrize("quote", [(98.0, False), (None, False)])
def test_a_stale_quote_arms_no_alert_but_the_plan_and_time_stop_are_saved(case, monkeypatch, quote):
    db_engine, _ = case
    bot = Bot()
    replies, changed = ask_plan(db_engine, monkeypatch, bot, quote=quote)
    monkeypatch.setattr(telegram_replies, "_calendar", lambda: None)
    data = card_data(bot)
    run(replies.handle(tap(data, keyboard=[[{"text": "Confirm", "callback_data": data}]], update_id=5)))
    lines = bot.named("answerCallbackQuery")[0]["text"].splitlines()
    assert lines[:3] == ["Plan saved", "Entry failed: The latest NBIS quote is stale or missing, so it was not set.",
                         "Invalidation failed: The latest NBIS quote is stale or missing, so it was not set."]
    assert bot.named("editMessageReplyMarkup") == [] and changed == []  # Confirm stays for the retry
    _, captures_, alerts, _, _, outcome = saved_plan(db_engine, data.split(":")[1])
    assert (len(captures_), alerts) == (1, [])
    assert (outcome["parts"]["entry"]["state"], outcome["parts"]["invalidation"]["state"]) == ("failed", "failed")


def test_a_failed_card_send_leaves_the_answer_sent_and_the_plan_on_the_desk(case, monkeypatch, caplog):
    from app.models import CopilotInvestigation
    db_engine, _ = case

    class Refusing(Bot):
        def __call__(self, name, *, json=None, timeout=None, **kw):
            if name == "sendMessage" and str((json or {}).get("text", "")).startswith("Proposed trade plan"):
                raise telegram.TelegramError("Bad Request: refused")
            return super().__call__(name, json=json, timeout=timeout, **kw)
    bot = Refusing()
    ask_plan(db_engine, monkeypatch, bot)
    (answer,) = bot.named("sendMessage")
    assert answer["text"].startswith("Verdict: Plan it.")
    assert "Telegram plan card not delivered" in caplog.text
    with Session(db_engine) as db:
        threads = db.exec(select(CopilotInvestigation).where(CopilotInvestigation.main_day.is_(None))).all()
    (thread,) = [t for t in threads if "trade_plan" in t.transcript_json]
    assert json.loads(thread.transcript_json)[-1]["proposals"][0]["symbol"] == "NBIS"


def test_a_plan_tap_from_anyone_else_is_ignored(case, monkeypatch):
    from app.models import LevelAlert
    db_engine, _ = case
    bot = Bot()
    replies, _changed = ask_plan(db_engine, monkeypatch, bot)
    data = card_data(bot)
    assert run(replies.handle(tap(data, chat="999", update_id=5))) is None
    assert run(replies.handle(tap(data, sender="999", update_id=6))) is None
    assert bot.named("answerCallbackQuery") == []
    with Session(db_engine) as db:
        assert db.exec(select(LevelAlert)).all() == []
    assert telegram_replies.confirm_plan(db_engine, "not-a-key", quote=lambda s: (98.0, True)) == ("That plan is no longer on the desk.", None)


def test_plan_it_on_a_radar_setup_ping_is_routed_once_and_marks_only_its_button(case, monkeypatch):
    from app.engine import radar_setup_plan
    from app.models import LevelAlert, TradeCapture
    from tests.test_radar_setup_plan import NOW, card
    db_engine, _ = case
    setup_id = card(db_engine)
    label, data = telegram_replies.plan_button(setup_id)
    # The tap passes no clock; pin it to the card's session before the close, or the result depends on the wall clock.
    planner = radar_setup_plan.plan
    monkeypatch.setattr(radar_setup_plan, "plan", lambda engine, key, **kw: planner(engine, key, now=NOW, **kw))
    assert (label, data) == ("Plan it", f"rp:{setup_id}") and len(data.encode()) <= telegram.CALLBACK_MAX
    monkeypatch.setattr(radar_setup_plan, "_live_price", lambda symbol: 61.4)
    monkeypatch.setattr(telegram_replies, "_calendar", lambda: None)  # the 60-minute check reads clock hours; no calendar fetch
    keyboard = rows(telegram_replies.rating_buttons(uuid.uuid4()) + (telegram_replies.plan_button(setup_id), ("Why?", "ask:radar")))
    bot, changed = Bot(), []
    replies = telegram_replies.Replies(db_engine, call=bot, alerts_changed=lambda: changed.append(1))
    assert run(replies.handle(tap(data, keyboard=keyboard, update_id=5))) == "rp"
    assert run(replies.handle(tap(data, keyboard=keyboard, update_id=6))) == "rp"
    assert [a["text"] for a in bot.named("answerCallbackQuery")] == ["Planned NBIS: out below 59.85. Alert armed. 60-minute check armed.",
                                                                  "Already planned."]
    edited = bot.named("editMessageReplyMarkup")[0]["reply_markup"]["inline_keyboard"]
    assert edited[:2] == keyboard[:2]  # the ratings stay
    assert edited[2] == [{"text": "✓ Planned", "callback_data": f"done:{setup_id}"}, {"text": "Why?", "callback_data": "ask:radar"}]
    with Session(db_engine) as db:
        assert len(db.exec(select(TradeCapture)).all()) == 1 and len(db.exec(select(LevelAlert)).all()) == 1
    assert changed == [1, 1]
    assert run(replies.handle(tap(f"rp:{setup_id}", chat="999", update_id=7))) is None


def test_a_why_or_reply_on_any_ping_resolves_the_symbol_it_is_about(case):
    """Before 2026-11-10 only a position alert's buttons gave the turn a symbol, so a Radar or setup ping's Why? ran with
    no owner context for the name and nothing prefetched (docs/copilot-lab.md § Jobs)."""
    from app.models import CopilotInvestigation, RadarSetup
    from tests.test_radar_setup_plan import card
    db_engine, _ = case
    setup_id = card(db_engine)
    with Session(db_engine) as db:
        hit = RadarAlert(event_id="rv0-x-lad-up-1", session_date="2026-11-10", rule_version="v0", kind="relative_to_spy",
                         subject="LAD", title="Radar: LAD +5.3% vs SPY +0.1%", body="b", first_seen_at=datetime(2026, 11, 10, 15))
        group = RadarAlert(event_id="rv0-x-semis-1", session_date="2026-11-10", rule_version="v0", kind="group_move",
                           subject="Semis", title="Radar: Semis +2.1%", body="b", first_seen_at=datetime(2026, 11, 10, 15))
        thread = CopilotInvestigation(title="CRWV thesis", symbol="CRWV", transcript_json="[]", evidence_json="[]")
        db.add_all([hit, group, thread])
        db.commit()
        ids = hit.id, group.id, thread.id
        setup_symbol = db.get(RadarSetup, uuid.UUID(setup_id)).symbol

    def ping(text, *data, url=""):
        row = [{"text": "b", "callback_data": d} for d in data] + ([{"text": "Open", "url": url}] if url else [])
        return {"message_id": 1, "text": text, "reply_markup": {"inline_keyboard": [row]}}

    with Session(db_engine) as db:
        assert telegram_replies.ping_symbol(db, ping("Radar: LAD +5.3% vs SPY", f"rr:{ids[0]}:useful", "ask:radar")) == "LAD"
        assert telegram_replies.ping_symbol(db, ping("Setup", f"rp:{setup_id}")) == setup_symbol
        assert telegram_replies.ping_symbol(db, ping("Answer", f"hd:{ids[2].hex}:3:h")) == "CRWV"
        # A group's subject is no symbol: the text decides, and two names are no one name.
        assert telegram_replies.ping_symbol(db, ping("Radar: Semis +2.1%, NVDA and AMD lead", f"rr:{ids[1]}:useful")) is None
        assert telegram_replies.ping_symbol(db, ping("Thesis watch: NBIS reclaimed VWAP", "ask:thesis_watch")) == "NBIS"
        assert telegram_replies.ping_symbol(db, ping("Research done", "ask:research", url="https://x/charts?symbol=smh&tf=5m")) == "SMH"
        assert telegram_replies.ping_symbol(db, ping("SPY gapped down 1.2%", "ask:nudge")) == "SPY"  # a benchmark alone is the subject
        assert telegram_replies.ping_symbol(db, ping("Nothing named here", "ask:nudge")) is None
        assert telegram_replies.ping_symbol(db, ping("SPY dropping, IV rising", "ask:nudge")) == "SPY"
        assert telegram_replies.ping_symbol(db, ping("AI software ahead of SPY: 3 of 4 up", "ask:radar")) is None
        assert telegram_replies.ping_symbol(db, ping("Radar digest: NOW reports, NBIS +4%", "ask:radar")) == "NBIS"
