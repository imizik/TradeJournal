"""Notes on the Telegram bot: a message or voice note starting with note or idea is saved to the day journal, never asked,
and the Sunday digest sends the week's notes back. Every Bot API call goes to a stub; no model call."""
import asyncio
import json
from datetime import datetime

from sqlmodel import Session, select

from app.engine import note_digest, notification_policy, telegram_replies
from app.engine.chart_math import ET
from app.models import DayJournalEntry, Trade
from tests.test_telegram import OGG, Bot, FileBot, case, env, files, lab_on, said, voice, whisper  # noqa: F401
from tests.test_exit_habits import engine  # noqa: F401


def notes(db_engine) -> list[DayJournalEntry]:
    with Session(db_engine) as db:
        return list(db.exec(select(DayJournalEntry).where(DayJournalEntry.context_json.is_not(None))).all())


def test_a_note_is_saved_with_its_tickers_and_open_positions_and_not_asked(case, monkeypatch):  # noqa: F811
    db_engine, _ = case
    lab_on(monkeypatch)
    with Session(db_engine) as db:  # MU held now (the fixture's option has expired)
        mu = db.exec(select(Trade).where(Trade.ticker == "MU")).one()
        mu.status = "open"
        db.add(mu)
        db.commit()
    bot = Bot()
    replies = telegram_replies.Replies(db_engine, call=bot)
    assert asyncio.run(replies.handle(said("Note: SNDK keeps fading after the open, $mu holds"))) == "note"
    assert not replies._tasks  # no copilot turn
    (reply,) = bot.named("sendMessage")
    assert reply["text"] == telegram_replies.NOTE_SAVED and reply["reply_parameters"]["message_id"] == 61
    (row,) = notes(db_engine)
    assert row.text == "SNDK keeps fading after the open, $mu holds" and row.kind == "update" and row.symbol is None
    assert row.day == datetime.now(ET).date() and row.operation_id == "telegram:61"
    assert json.loads(row.context_json) == {"source": "telegram", "word": "note", "tickers": ["SNDK", "MU"], "open": ["MU"]}


def test_an_idea_replying_to_a_ping_keeps_that_ping_and_its_symbol(case):  # noqa: F811
    db_engine, alert = case
    bot = Bot()
    ping = {"message_id": 9, "text": "Give-back on SNDK",
            "reply_markup": {"inline_keyboard": [[{"text": "Why?", "callback_data": f"why:{alert}"}]]}}
    asyncio.run(telegram_replies.Replies(db_engine, call=bot).handle(said("idea   take half at 2R", replied=ping)))
    (row,) = notes(db_engine)
    assert row.kind == "idea" and row.text == "take half at 2R" and row.symbol == "SNDK"
    assert json.loads(row.context_json)["ping"] == {"message_id": 9, "kind": "position_alert"}


def test_plain_questions_still_go_to_copilot(case, monkeypatch):  # noqa: F811
    db_engine, _ = case
    lab_on(monkeypatch)
    bot = Bot()
    replies = telegram_replies.Replies(db_engine, call=bot)

    async def go():
        assert await replies.handle(said("Notable moves in MU today?")) == "ask"  # "notable" is not the word note
        await asyncio.gather(*replies._tasks)

    asyncio.run(go())
    assert bot.named("sendMessage")[0]["text"].startswith("Verdict:") and notes(db_engine) == []


def test_a_bare_note_is_not_saved(case):  # noqa: F811
    db_engine, _ = case
    bot = Bot()
    asyncio.run(telegram_replies.Replies(db_engine, call=bot).handle(said("note")))
    assert bot.named("sendMessage")[0]["text"] == telegram_replies.NOTE_EMPTY and notes(db_engine) == []


def test_a_spoken_note_is_saved_and_not_asked(case, monkeypatch, files, whisper):  # noqa: F811
    db_engine, _ = case
    lab_on(monkeypatch)
    from app.engine import transcribe
    monkeypatch.setattr(transcribe, "transcribe_bytes", lambda data, extension, prompt=None: "Note, MU looks heavy into earnings")
    files["v1"] = OGG
    bot = FileBot()
    replies = telegram_replies.Replies(db_engine, call=bot)

    async def go():
        assert await replies.handle(voice()) == "voice"
        await asyncio.gather(*replies._tasks)

    asyncio.run(go())
    (reply,) = bot.named("sendMessage")  # no "Heard:" and no answer: one line
    assert reply["text"] == "Saved: MU looks heavy into earnings"
    (row,) = notes(db_engine)
    assert row.symbol == "MU" and json.loads(row.context_json)["tickers"] == ["MU"]


def test_the_digest_renders_with_zero_notes(engine):  # noqa: F811
    with Session(engine) as db:
        _, title, body = note_digest.build(db, datetime(2026, 11, 22, 18, 5, tzinfo=ET).timestamp())
    assert title == "NOTES · week of Nov 16"
    assert body.splitlines() == ["No notes this week. Start a message or voice note with note or idea to save one.",
                                 "No alert or Radar pings this week."]


def test_the_digest_counts_themes_ratings_and_quotes_an_idea_once_on_sunday(case, monkeypatch):  # noqa: F811
    db_engine, _ = case
    bot = Bot()
    replies = telegram_replies.Replies(db_engine, call=bot)
    for i, text in enumerate(("note MU fading into the close again", "note MU gap fill worked", "idea buy MU dips at VWAP")):
        asyncio.run(replies.handle(said(text, update_id=i + 1)))
    now = datetime.now(ET).timestamp()
    with Session(db_engine) as db:
        _, title, body = note_digest.build(db, now)
    lines = body.splitlines()
    assert lines[0] == "3 notes this week." and lines[1].startswith("Themes: MU ×3")
    assert lines[-1].startswith("Worth testing? “buy MU dips at VWAP”") and len(lines) <= 12

    sent = []
    monkeypatch.setattr(notification_policy, "enabled", lambda: False)
    digest = note_digest.NoteDigest(db_engine, clock=lambda: now, send=lambda t, b, path: sent.append((t, b, path)))
    assert digest.run() == "sent" and sent[0][2] == "/daily"
    assert note_digest.NoteDigest(db_engine, clock=lambda: now, send=lambda *a, **k: sent.append(a)).run().startswith("held")
    assert len(sent) == 1  # once a week, across restarts


def test_the_digest_is_due_sunday_evening_new_york_and_off_by_default(monkeypatch):
    monkeypatch.delenv("NOTE_DIGEST_ENABLED", raising=False)
    assert not note_digest.enabled()
    digest = note_digest.NoteDigest(None)
    assert digest.due(datetime(2026, 11, 22, 18, 0, tzinfo=ET).timestamp())
    assert not digest.due(datetime(2026, 11, 22, 17, 59, tzinfo=ET).timestamp())
    assert not digest.due(datetime(2026, 11, 23, 18, 30, tzinfo=ET).timestamp())
