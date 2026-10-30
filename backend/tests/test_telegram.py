"""Telegram phone pings: the Bot API transport, the phone dispatcher, and the reply buttons. No live sends: every Bot API
call goes to a stub."""
import asyncio
from datetime import datetime
import json
from pathlib import Path

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
    receipt, state = phone.send("T", "m", kind="nudge", path="/p", buttons=(("Why?", "why:a"),), image=b"png", priority=3,
                                tags=("memo",), direct_click=True, more=(("Plan", "/plans/1"),))
    assert (receipt, state) == ("77", "attached")
    keyboard = json.loads(bot[0]["data"]["reply_markup"])["inline_keyboard"]
    assert keyboard == [[{"text": "Why?", "callback_data": "why:a"}],
                        [{"text": "Open", "url": "https://journal.example/p"}, {"text": "Plan", "url": "https://journal.example/plans/1"}]]


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


def tap(data: str, chat=CHAT, update_id=1, keyboard=None) -> dict:
    return {"update_id": update_id, "callback_query": {
        "id": f"q{update_id}", "data": data, "from": {"id": int(chat)},
        "message": {"message_id": 55, "chat": {"id": int(chat)}, "reply_markup": {"inline_keyboard": keyboard or []}}}}


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
    for _, data in telegram_replies.feedback_buttons(alert, tuple(telegram_replies.FEEDBACK_LABELS)) \
            + telegram_replies.rating_buttons(alert, tuple(telegram_replies.RADAR_LABELS)):
        assert len(data.encode()) <= telegram.CALLBACK_MAX


def test_taps_from_another_chat_and_other_updates_are_ignored(case):
    db_engine, alert = case
    bot = Bot()
    replies = telegram_replies.Replies(db_engine, call=bot)
    assert run(replies.handle(tap(f"fb:{alert}:prompted_review", chat="999"))) is None
    assert run(replies.handle({"update_id": 2, "message": {"chat": {"id": int(CHAT)}, "text": "hi"}})) is None
    assert run(replies.handle(tap("nonsense:1"))) is None
    assert bot.calls == []
    with Session(db_engine) as db:
        assert db.exec(select(PositionAlertFeedback)).all() == []


def test_feedback_tap_saves_once_answers_and_marks_the_keyboard(case):
    db_engine, alert = case
    keyboard = [[{"text": label, "callback_data": data} for label, data in telegram_replies.feedback_buttons(alert)],
                [{"text": "Open", "url": "https://journal.example/x"}]]
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
    assert edit["reply_markup"]["inline_keyboard"] == [[{"text": "✓ Prompted review", "callback_data": "done"}],
                                                       [{"text": "Open", "url": "https://journal.example/x"}]]
    # The other answer tapped later cannot overwrite it; the keyboard shows what was saved.
    assert run(replies.handle(tap(f"fb:{alert}:already_aware", update_id=3, keyboard=keyboard))) == "fb"
    assert bot.named("answerCallbackQuery")[-1]["text"] == "Already answered: Prompted review."
    assert bot.named("editMessageReplyMarkup")[-1]["reply_markup"]["inline_keyboard"][0] == [
        {"text": "✓ Prompted review", "callback_data": "done"}]
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
    keyboard = [[{"text": label, "callback_data": data} for label, data in telegram_replies.feedback_buttons(alert)]]

    async def go():
        await replies.handle(tap(f"why:{alert}", keyboard=keyboard))
        await asyncio.gather(*replies._tasks)

    run(go())
    assert bot.named("answerCallbackQuery")[0]["text"] == "Asking copilot…"
    [reply] = bot.named("sendMessage")
    assert reply["chat_id"] == CHAT and reply["reply_parameters"]["message_id"] == 55
    assert reply["text"].startswith("Verdict:") and len(reply["text"]) <= telegram_replies.ANSWER_MAX
    row = bot.named("editMessageReplyMarkup")[0]["reply_markup"]["inline_keyboard"][0]
    assert row[-1] == {"text": "✓ Why? (answer below)", "callback_data": "done"} and len(row) == 3


def test_why_with_the_lab_off_says_so(case):
    db_engine, alert = case
    replies = telegram_replies.Replies(db_engine, call=Bot())
    assert run(replies.why_text(str(alert))) == "Copilot Lab is off on this server, so there is no answer here."


def test_the_poll_advances_its_offset_and_asks_only_for_taps(case):
    db_engine, alert = case
    bot = Bot([tap(f"fb:{alert}:prompted_review", update_id=40), tap("done", update_id=41)])
    replies = telegram_replies.Replies(db_engine, call=bot)
    run(replies.poll_once())
    run(replies.poll_once())
    first, second = bot.named("getUpdates")
    assert first == {"timeout": telegram_replies.POLL_SECONDS, "allowed_updates": ["callback_query"]}
    assert second["offset"] == 42


def test_startup_polls_only_when_telegram_is_set_up(monkeypatch):
    from fastapi import FastAPI
    from app import main
    started = []

    class Fake:
        def __init__(self, _engine):
            pass

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
