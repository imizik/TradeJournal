"""Reply buttons and typed questions on Telegram pings, written back into the app, with no inbound port.

One long-polling task in the API process (started from the app lifespan beside the level alert monitor, only when
``telegram.configured()``) asks Telegram for new button taps and messages (``getUpdates`` with an offset,
``callback_query`` and ``message`` only). A tap or message is handled only when it is in ``TELEGRAM_CHAT_ID`` and from
that same id (the owner's private chat with the bot, whose id is the owner's user id); everything else is ignored. When
Telegram cannot be reached the task sleeps and tries again; nothing else waits on it.

A button's callback data is ``<verb>:<id>[:<answer>]``, at most 64 bytes:

- ``fb:<position alert id>:<rating>``: the owner's feedback on an open-trade alert, saved through the trade page's
  own route (``PUT /trades/{trade_id}/phone-alerts/{alert_id}/feedback``, base version 0), so a repeated tap saves
  nothing new and a different answer after the first is refused as the page refuses it;
- ``rr:<Radar alert id>:<rating>``: a Radar event's rating through the Radar page's own route
  (``POST /radar/events/{event_id}/feedback``, what ``&rate=`` posts), skipped when it is already the latest rating;
- ``why:<position alert id>``: one bounded copilot turn on the alert (``position_alerts.ask_context``, the configured
  backend and its turn and daily budgets), answered in the chat with the Verdict line and body cut to 1,500
  characters; with Copilot Lab off the reply says so. One turn runs at a time, and a message's Why? is asked once.

A typed message is a question for copilot: one bounded turn, as Why? runs, answered as a reply to it. Sent as a
reply to a ping, the ping is its context: a position alert's (found from the ping's ``fb:``/``why:``/``done:`` button) is
``ask_context`` on that alert, any other ping's is its text. ``/start`` and ``/help`` (or any command) get a short
note on what the bot does. One turn runs at a time, shared with Why?; a question while one runs is not asked, and the
reply says so. A question is cut to ``QUESTION_MAX`` characters.

Every handled tap is answered (``answerCallbackQuery``) and the message's keyboard is edited to show the answer
chosen. Each tap is recorded once in the rows those routes already write; there is no table of its own. Known
limit: the offset lives in memory, so a tap handled just before a restart may be read again after it; the feedback
and rating writes are idempotent, a repeated ``why`` or question asks once more.
"""

import asyncio
import logging
import re
import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlmodel import Session

from app.engine import telegram

log = logging.getLogger(__name__)

POLL_SECONDS = 10  # Telegram holds the request open this long when nothing is new; a shutdown waits for it
RETRY_SECONDS = 30
ANSWER_MAX = 1500
QUESTION_MAX = 1000
HELP = ("I send TradeJournal's phone pings. Tap a ping's buttons to answer it, or type a question for copilot. "
        "Reply to a ping to ask about that alert.")
BUSY = "Copilot is still answering the last question; ask again in a moment."
FEEDBACK_LABELS = {"prompted_review": "Prompted review", "already_aware": "Already aware", "too_late": "Too late",
                   "not_useful": "Not useful"}
RADAR_LABELS = {"useful": "Useful", "already_knew": "Already knew", "too_late": "Too late", "irrelevant": "Not useful"}
DONE = "done"  # a button that shows a chosen answer (``done:<id>``, so a reply still finds the alert); a tap does nothing
WHY = object()  # _mark's marker for a Why? tap
SYMBOL = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def feedback_buttons(alert_id, ratings: tuple[str, ...] = ("prompted_review", "already_aware")) -> tuple[tuple[str, str], ...]:
    """Reply buttons for an open-trade alert: its feedback answers and Why?"""
    return tuple((FEEDBACK_LABELS[r], f"fb:{alert_id}:{r}") for r in ratings) + (("Why?", f"why:{alert_id}"),)


def rating_buttons(radar_alert_id, ratings: tuple[str, ...] = ("useful", "irrelevant")) -> tuple[tuple[str, str], ...]:
    """Reply buttons for a Radar ping, keyed by its ``RadarAlert`` row (an event id can be longer than 64 bytes)."""
    return tuple((RADAR_LABELS[r], f"rr:{radar_alert_id}:{r}") for r in ratings)


class Replies:
    def __init__(self, engine, *, call=None):
        self.engine = engine
        self.call = call or telegram.call
        self.offset: int | None = None
        self.last_error: str | None = None
        self._tasks: set[asyncio.Task] = set()
        self._asked: set = set()  # messages whose Why? was asked in this process

    async def loop(self) -> None:
        while True:
            try:
                await self.poll_once()
                self.last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - Telegram unreachable or refusing: wait and try again
                self.last_error = str(exc) if isinstance(exc, telegram.TelegramError) else type(exc).__name__
                log.warning("Telegram replies: %s", self.last_error)
                await asyncio.sleep(RETRY_SECONDS)

    async def poll_once(self) -> None:
        payload = {"timeout": POLL_SECONDS, "allowed_updates": ["callback_query", "message"]}
        if self.offset is not None:
            payload["offset"] = self.offset
        updates = await asyncio.to_thread(self.call, "getUpdates", json=payload, timeout=POLL_SECONDS + 10)
        for update in updates or []:
            self.offset = int(update["update_id"]) + 1
            try:
                await self.handle(update)
            except Exception:  # noqa: BLE001 - one bad tap never stops the others
                log.exception("Telegram reply could not be handled")

    async def handle(self, update: dict) -> str | None:
        """Handle one update; returns what was done (for tests), or None when it was ignored."""
        query = update.get("callback_query")
        if not query:
            return await self.handle_message(update.get("message"))
        message = query.get("message") or {}
        owner = telegram.chat_id()
        # The owner's private chat with the bot: its id is the owner's user id, so a tap by anyone else is ignored.
        if str((message.get("chat") or {}).get("id")) != owner or str((query.get("from") or {}).get("id")) != owner:
            return None
        verb, _, rest = str(query.get("data") or "").partition(":")
        if verb == "fb":
            reply, chosen = await asyncio.to_thread(self._feedback, *rest.partition(":")[::2])
        elif verb == "rr":
            reply, chosen = await asyncio.to_thread(self._rating, *rest.partition(":")[::2])
        elif verb == "why":
            if message.get("message_id") in self._asked:  # once per message
                reply, chosen = "Already asked; the answer comes in the chat.", None
            elif self._tasks:  # one turn at a time
                reply, chosen = BUSY, None
            else:
                self._asked.add(message.get("message_id"))
                reply, chosen = "Asking copilot…", WHY
                task = asyncio.create_task(self._why(rest, message))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
        elif verb == DONE:
            reply, chosen = None, None
        else:
            return None
        await asyncio.to_thread(self._answer, query, reply)
        if chosen is not None:
            await asyncio.to_thread(self._mark, message, query.get("data"), chosen)
        return verb

    async def handle_message(self, message: dict | None) -> str | None:
        """A typed message from the owner: a copilot question (``ask``), or the help note for a command."""
        owner = telegram.chat_id()
        if not message or str((message.get("chat") or {}).get("id")) != owner or str((message.get("from") or {}).get("id")) != owner:
            return None
        text = str(message.get("text") or "").strip()
        if not text:
            return None
        if text.startswith("/"):
            await asyncio.to_thread(self._reply, message, HELP)
            return "help"
        if self._tasks:
            await asyncio.to_thread(self._reply, message, BUSY)
            return "busy"
        task = asyncio.create_task(self._ask(text[:QUESTION_MAX], message))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return "ask"

    # -------------------------------------------------------------- the writes

    def _feedback(self, alert_id: str, rating: str) -> tuple[str, str | None]:
        from app.models import PositionAlert
        from app.routers.position_alerts import FeedbackBody, save_feedback
        alert_uuid = _uuid(alert_id)
        if alert_uuid is None or rating not in FEEDBACK_LABELS:
            return "That button is not one the app knows.", None
        with Session(self.engine) as db:
            alert = db.get(PositionAlert, alert_uuid)
            trade_id = _trade_for(db, alert) if alert is not None else None
            if trade_id is None:
                return "That alert is no longer in the journal.", None
            try:
                save_feedback(trade_id, alert.id, FeedbackBody(rating=rating, base_version=0), db)
            except HTTPException as exc:
                if exc.status_code == 409:
                    db.rollback()
                    from app.engine import alert_feedback
                    saved = alert_feedback.for_alerts(db, [alert.id]).get(alert.id)
                    if saved:
                        label = FEEDBACK_LABELS.get(saved["rating"], saved["rating"])
                        return f"Already answered: {label}.", label
                return str(exc.detail), None
        return f"Saved: {FEEDBACK_LABELS[rating]}.", FEEDBACK_LABELS[rating]

    def _rating(self, radar_alert_id: str, rating: str) -> tuple[str, str | None]:
        from app.models import RadarAlert
        from app.routers import radar
        alert_uuid = _uuid(radar_alert_id)
        if alert_uuid is None or rating not in RADAR_LABELS:
            return "That button is not one the app knows.", None
        with Session(self.engine) as db:
            alert = db.get(RadarAlert, alert_uuid)
            event_id = alert.event_id if alert is not None else None
        if event_id is None:
            return "That Radar alert is no longer in the journal.", None
        try:
            if radar._require_store().latest_ratings().get(event_id) != rating:
                radar.event_feedback(event_id, radar.FeedbackBody(rating=rating))
        except HTTPException as exc:
            return str(exc.detail), None
        return f"Saved: {RADAR_LABELS[rating]}.", RADAR_LABELS[rating]

    async def _why(self, alert_id: str, message: dict) -> None:
        try:
            text = await self.why_text(alert_id)
        except Exception:  # noqa: BLE001 - the owner hears that it failed, never silence
            log.exception("Telegram Why? turn failed")
            text = "The copilot turn failed unexpectedly."
        await asyncio.to_thread(self._reply, message, text)

    async def _ask(self, text: str, message: dict) -> None:
        try:
            answer = await self.question_text(text, message.get("reply_to_message"))
        except Exception:  # noqa: BLE001 - the owner hears that it failed, never silence
            log.exception("Telegram question turn failed")
            answer = "The copilot turn failed unexpectedly."
        await asyncio.to_thread(self._reply, message, answer)

    def _alert_context(self, alert_id: str) -> tuple[str, str | None] | None:
        """``ask_context`` on a position alert and its symbol, or None when the alert is not in the journal."""
        from app.engine import position_alerts
        from app.models import PositionAlert
        alert_uuid = _uuid(alert_id)
        with Session(self.engine) as db:
            alert = db.get(PositionAlert, alert_uuid) if alert_uuid else None
            if alert is None:
                return None
            symbol = (alert.contract or "").split(" ")[0]
            return position_alerts.ask_context(alert), symbol if SYMBOL.match(symbol) else None

    async def why_text(self, alert_id: str) -> str:
        """One bounded copilot turn on the alert, as plain text for the chat."""
        from app.ai import copilot
        if not copilot.settings().enabled:
            return "Copilot Lab is off on this server, so there is no answer here."
        found = await asyncio.to_thread(self._alert_context, alert_id)
        if found is None:
            return "That alert is no longer in the journal."
        return await self.turn(*found)

    async def question_text(self, text: str, replied: dict | None) -> str:
        """One bounded copilot turn on a typed question; a reply to a ping carries that ping as its context."""
        from app.ai import copilot
        if not copilot.settings().enabled:
            return "Copilot Lab is off on this server, so there is no answer here."
        context, symbol = None, None
        if replied:
            alert_id = next((data.split(":")[1] for row in ((replied.get("reply_markup") or {}).get("inline_keyboard") or [])
                             for data in (str(b.get("callback_data") or "") for b in row)
                             if data.startswith(("fb:", "why:", f"{DONE}:"))), None)
            found = await asyncio.to_thread(self._alert_context, alert_id) if alert_id else None
            if found is not None:
                context, symbol = found
            else:
                context = str(replied.get("text") or replied.get("caption") or "").strip()[:QUESTION_MAX] or None
        question = f"{context}\n\nMy question about this: {text}" if context else text
        return await self.turn(question, symbol)

    async def turn(self, question: str, symbol: str | None) -> str:
        """One bounded copilot turn (the configured backend, its turn and daily budgets), as plain text for the chat."""
        from app.ai import copilot, copilot_spend
        from app.engine.chart_math import ET
        cfg = copilot.settings()
        if cfg.backend == "anthropic":
            spent = await asyncio.to_thread(copilot_spend.spent_today)
            if spent >= cfg.daily_budget_usd:
                return f"Today's copilot API budget (${cfg.daily_budget_usd:.2f}) is spent."
        try:
            adapter = await asyncio.to_thread(copilot.adapter_for, cfg)
            evidence = copilot.evidence_for(cfg)
        except copilot.CopilotError as exc:
            return exc.message
        history = [{"role": "user", "content": question}]
        now = datetime.now(ET)
        parts: list[str] = []
        errors: list[str] = []
        done = None
        try:
            turn = (adapter.run_turn(history, symbol, cfg, evidence, now) if hasattr(adapter, "run_turn")
                    else copilot.run_turn(history, symbol, cfg, adapter, evidence, now))
            async for event in turn:
                if event.get("type") == "text":
                    parts.append(event.get("delta") or "")
                elif event.get("type") == "error":
                    errors.append(event.get("message") or "")
                elif event.get("type") == "done":
                    done = event.get("metrics")
        finally:
            if hasattr(adapter, "aclose"):
                await adapter.aclose()
            if done:
                await asyncio.to_thread(copilot_spend.record, done, symbol)
        answer = "".join(parts).strip()
        if errors:
            answer = (answer + "\n\n" if answer else "") + " ".join(errors)
        answer = answer or "The copilot gave no answer."
        return answer if len(answer) <= ANSWER_MAX else answer[: ANSWER_MAX - 1].rstrip() + "…"

    # -------------------------------------------------------------- the chat

    def _reply(self, message: dict, text: str) -> None:
        try:
            self.call("sendMessage", json={
                "chat_id": telegram.chat_id(), "text": text, "reply_parameters": {"message_id": message.get("message_id"),
                                                                                  "allow_sending_without_reply": True},
                "link_preview_options": {"is_disabled": True}})
        except telegram.TelegramError as exc:
            log.warning("Telegram answer not delivered: %s", exc)

    def _answer(self, query: dict, text: str | None) -> None:
        payload = {"callback_query_id": query.get("id")}
        if text:
            payload["text"] = text[:200]
        try:
            self.call("answerCallbackQuery", json=payload)
        except telegram.TelegramError as exc:  # an old tap can no longer be answered; what was saved stays saved
            log.info("Telegram tap not answered: %s", exc)

    def _mark(self, message: dict, data: str, chosen: str) -> None:
        """Edit the message's keyboard: an answer replaces its row with "✓ <the saved answer>"; Why? is marked asked."""
        rows = ((message.get("reply_markup") or {}).get("inline_keyboard")) or []
        done = f"{DONE}:{data.split(':')[1]}" if data.count(":") >= 1 else DONE  # keeps the alert for a typed reply
        edited = []
        for row in rows:
            tapped = next((b for b in row if b.get("callback_data") == data), None)
            if tapped is None:
                edited.append(row)
            elif chosen == WHY:
                edited.append([{"text": "✓ Why? (answer below)", "callback_data": done} if b is tapped else b for b in row])
            else:  # the answers give way to the saved one; Why? stays
                kept = [b for b in row if str(b.get("callback_data", "")).startswith(("why:", DONE)) and b is not tapped]
                edited.append([{"text": f"✓ {chosen}", "callback_data": done}, *kept])
        if edited == rows:
            return
        try:
            self.call("editMessageReplyMarkup", json={"chat_id": telegram.chat_id(), "message_id": message.get("message_id"),
                                                      "reply_markup": {"inline_keyboard": edited}})
        except telegram.TelegramError as exc:
            log.info("Telegram keyboard not updated: %s", exc)


def _trade_for(db: Session, alert) -> uuid.UUID | None:
    """The trade that holds the alert's position now: the one whose entry fill is the alert's source fill (a rebuild
    gives trades new ids, so the alert's own ``trade_id`` may be obsolete), else that stored id."""
    from sqlmodel import select
    from app.models import Fill, Trade, TradeFill
    query = (select(Trade.id).join(TradeFill, TradeFill.trade_id == Trade.id).join(Fill, Fill.id == TradeFill.fill_id)
             .where(TradeFill.role == "entry", Fill.account_id == alert.account_id))
    found = db.exec(query.where(Fill.raw_email_id == alert.source_key)).first()
    if found is None and (fill_id := _uuid(alert.source_key)) is not None:
        found = db.exec(query.where(Fill.id == fill_id)).first()
    return found or alert.trade_id


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError):
        return None
