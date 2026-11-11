"""Reply buttons and typed questions on Telegram pings, written back into the app, with no inbound port.

One long-polling task in the API process (started from the app lifespan beside the level alert monitor, only when
``telegram.configured()``) asks Telegram for new button taps and messages (``getUpdates`` with an offset,
``callback_query`` and ``message`` only). A tap or message is handled only when it is in ``TELEGRAM_CHAT_ID`` and from
that same id (the owner's private chat with the bot, whose id is the owner's user id); everything else is ignored. When
Telegram cannot be reached the task sleeps and tries again; nothing else waits on it.

A button's callback data is ``<verb>:<id>[:<answer>]``, at most 64 bytes:

- ``fb:<position alert id>:<rating>``: the owner's feedback on an open-trade alert (Prompted review, Already aware,
  Too late, Not useful), saved through the trade page's own route
  (``PUT /trades/{trade_id}/phone-alerts/{alert_id}/feedback``, base version 0), so a repeated tap saves nothing new
  and a different answer after the first is refused as the page refuses it;
- ``rr:<Radar alert id>:<rating>``: a Radar event's rating (Useful, Already knew, Too late, Not useful) through the
  Radar page's own route (``POST /radar/events/{event_id}/feedback``, what ``&rate=`` posts), skipped when it is
  already the latest rating;
- ``hd:<investigation id as 32 hex>:<message index>:h|d|n``: Helped / Didn't under a copilot answer the bot sent, set
  on the answer saved on the desk as the desk's buttons set it (``copilot_investigations.set_rating``, what
  ``PUT /copilot/investigations/{id}/messages/{index}/rating`` does): ``h`` helped, ``d`` didn't, ``n`` clears it (the
  checked button carries ``n``, so a second tap on it clears, as on the desk); the other button changes it;
- ``pc:<companion id>:confirm|ignore``: the position companion's adopt message (``engine/position_companion.py``):
  Confirm arms the draft plan's invalidation alert as a confirmed plan card does, Ignore stops its updates;
- ``pu:<companion id>:<update>:closed|holding``: the owner's answer to a companion update, recorded on its row;
- ``pl:<card client id>:confirm``: a trade plan a Telegram turn proposed (``_send_plans``): Confirm runs the desk's
  Confirm parts in its order (``confirm_plan``): the pre-trade plan capture on the default (or only) account, then the
  entry and invalidation alerts and a readable time stop, each with its own result on the card's outcome; a later tap
  retries only the parts not done. Nothing is placed or sized;
- ``rp:<Radar setup id>``: Plan it on a Radar setup ping (``radar_setup_plan.plan``): the setup card saved once as a
  plan with the Radar event as its origin, and its invalidation alert armed; no model call, nothing placed;
- ``why:<position alert id>``: one bounded copilot turn on the alert (``position_alerts.ask_context``, the configured
  backend and its turn and daily budgets), answered in the chat with the Verdict line and body cut to 1,500
  characters; with Copilot Lab off the reply says so. One turn runs at a time, and a message's Why? is asked once.
- ``cc:<check id as 32 hex>:pass``: Pass under a checked call's card (``engine/call_check.py``), recorded on its row
  once; the keyboard then shows "✓ Passed" (Plan it, a link, goes). ``cc:q``: Check as a call under the answer to an
  ambiguous message: the message it answered (Telegram sends it with the tap) is checked as a call;
- ``ask:<kind>``: the Why? ``phone.send`` adds to every other factual ping (Radar, thesis watch, research, plan and
  level pings, interrupts): the same bounded turn, asked about the ping's own text, as a typed reply to it is. A
  ping too old for Telegram to show its text again says so instead.

A typed message that is a trade call (``call_check.classify``: a ``check`` prefix, or two or more call markers and no
question marker; a call shared from Discord arrives as typed text) is checked instead (``call_check.run``, the
``check_call`` job): the reply is the check card in chat lines (the verdict, what was read with blanks named, the tiles,
Against, Changes if) with Plan it (a link to the desk's plan flow with the call's levels as editable text; never a
ticket), Pass and Why?. An ambiguous one is answered as a question with Check as a call beside Helped and Didn't. A photo
with no caption is first checked as a call; when the model says it is not one, it is the broker screenshot below. A
captioned photo whose caption is a call is checked with the image.

A typed message is otherwise a question for copilot: one bounded turn, as Why? runs, answered as a reply to it. Sent as a
reply to a ping, the ping is its context: a position alert's (found from the ping's ``fb:``/``why:``/``done:`` button) is
``ask_context`` on that alert, any other ping's is its text, with the symbol it is about (``ping_symbol``: from the row
behind its buttons, its Open link, or the one known ticker its text names) so the turn reads that name's owner
context. The turn runs as the ``telegram`` job (``ai/copilot_prompt.py``): a chat-shaped answer. ``/start`` and ``/help`` (or any command) get a short
note on what the bot does. One turn runs at a time, shared with Why?; a question while one runs is not asked, and the
reply says so. A question is cut to ``QUESTION_MAX`` characters.

A voice note (or audio file) is a typed question spoken: 30 seconds and 3 MB at most, downloaded (``telegram.download``),
transcribed by the app's own Whisper (``engine/transcribe.py``, primed with the owner's tickers as hold-to-talk is, so
"en bis" becomes NBIS), the words confirmed back ("Heard: …") and asked. A photo (the largest size Telegram offers, or
an image sent as a document) goes through the copilot's image store (``ai/copilot_images.py``) and is attached to one
turn whose question is its caption, or with none ``RECONCILE_QUESTION`` (the broker screenshot against the journal's
open positions); the stored image is deleted when the turn ends. The same owner check runs before any download, the
same one-turn-at-a-time rule and reply-to context apply, and a failed download, transcription or turn says what
failed. The desk keeps the heard words, or the caption or reconcile question marked "(photo)", never the image.

Each question and Why? answer is also saved on the desk (``save_on_desk``): the owner's own words, marked "From
Telegram:" (a Why? tap is saved as "Why? on a ping", never the ping's text, which may be a headline or a research
result), and the answer, as two messages on the symbol's thread (its plan, else the conversation the companion adopted
it in, else the newest open conversation about it; its ``updated_at`` left as it was, so thesis watch re-checks the
same conversation), or, with none or no symbol, in today's Main chat. No conversation is created (an open one with a
symbol would start thesis-watch pings). The saved answer keeps its turn's ``turn_id`` in its metrics, as the desk's
do, so the answer scorecard counts it (source ``telegram``) and its rating; an answer that was saved is sent with
Helped and Didn't (``hd:``) under it.

A ``trade_plan`` card the turn proposes (at most ``PLAN_CARDS``) is saved on the answer as the desk saves one (the
proposal event without its type, its id made unique in the conversation, and a client id; on Main chat ``append_main``
gives it its own plan thread), then sent after the answer as its own message: the card's lines, Confirm
(``pl:<client id>:confirm``) and Edit (the thread on the desk). The callback carries the card's client id, 32 hex
characters, because the proposal id is only unique within its conversation and the conversation's id beside it does
not fit 64 bytes; a tap finds the card by that id in the saved conversations (``find_plan``). Other cards are named at
the end of the answer, to confirm on the desk. A card message that fails to send is logged; the answer is already sent
and the card is on the desk.

Every handled tap is answered (``answerCallbackQuery``) and the message's keyboard is edited to show the answer
chosen. Each tap is recorded once in the rows those routes already write; there is no table of its own. Known
limit: the offset lives in memory, so a tap handled just before a restart may be read again after it; the feedback
and rating writes are idempotent, a repeated ``why`` or question asks once more.
"""

import asyncio
import contextlib
import json
import logging
import os
import re
import time
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
HELP = ("I send TradeJournal's phone pings. Tap a ping's buttons to answer it, or type or speak a question for copilot "
        "(or send a screenshot of your positions). Reply to a ping to ask about that alert. Share a Discord trade call "
        "here (or start a message with check) to get it checked.")
BUSY = "Copilot is still answering the last question; ask again in a moment."
WHY_QUESTION = "Why does this matter for me right now, and what should I check before acting?"
RECONCILE_QUESTION = ("What positions does this screenshot show? For each one you can read, give the contract, quantity and "
                      "mark, compare it with my open positions in the journal, and list what differs: missing, extra, or a "
                      "different quantity. Read only; change nothing.")
VOICE_TOO_LONG = "Keep a voice note under 30 seconds."
FAILED = "The copilot turn failed unexpectedly."
FEEDBACK_LABELS = {"prompted_review": "Prompted review", "already_aware": "Already aware", "too_late": "Too late",
                   "not_useful": "Not useful"}
RADAR_LABELS = {"useful": "Useful", "already_knew": "Already knew", "too_late": "Too late", "irrelevant": "Not useful"}
RATE_LABELS = {"helped": "Helped", "didnt": "Didn't"}  # the desk's ratings of a copilot answer
RATE_CODES = {"h": "helped", "d": "didnt", "n": None}  # ``hd:`` answer codes; ``n`` clears
DONE = "done"  # a button that shows a chosen answer (``done:<id>``, so a reply still finds the alert); a tap does nothing
WHY = object()  # _mark's marker for a Why? tap
CHECKING = object()  # _mark's marker for a Check as a call tap
CHECK_AS_CALL = ("Check as a call", "cc:q")
SYMBOL = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
PLAN_CARDS = 2  # trade plan cards sent per turn
PLAN_KEY = re.compile(r"^[0-9a-f]{32}$")  # a Telegram card's client id
PLAN_FOOTER = "Nothing is placed; Confirm saves the plan and arms its alerts."
FROM_TELEGRAM_NOTE = "Confirmed from Telegram"
PLAN_SIDE = {("long", "stock"): "Buy stock", ("short", "stock"): "Short stock", ("long", "calls"): "Buy calls",
             ("short", "puts"): "Buy puts"}
PLAN_CAPTURE_SIDE = {("long", "stock"): "buy_stock", ("short", "stock"): "short_stock", ("long", "calls"): "buy_calls",
                     ("short", "puts"): "buy_puts"}  # the desk's capture side (TradePlanCard: SIDE)
PART_NAME = {"plan": "Plan", "entry": "Entry", "invalidation": "Invalidation", "timeStop": "Time stop"}
HORIZON_LABEL = {"day": "Day trade", "swing": "Swing", "long": "Long hold"}
CONDITION = {"touches": "touches", "crosses": "crosses", "closes_beyond": "closes beyond"}


def feedback_buttons(alert_id, ratings: tuple[str, ...] = tuple(FEEDBACK_LABELS)) -> tuple[tuple[str, str], ...]:
    """Reply buttons for an open-trade alert: its feedback answers (all four by default) and Why?"""
    return tuple((FEEDBACK_LABELS[r], f"fb:{alert_id}:{r}") for r in ratings) + (("Why?", f"why:{alert_id}"),)


def rating_buttons(radar_alert_id, ratings: tuple[str, ...] = tuple(RADAR_LABELS)) -> tuple[tuple[str, str], ...]:
    """Reply buttons for a Radar ping (all four ratings by default), keyed by its ``RadarAlert`` row (an event id can be
    longer than 64 bytes)."""
    return tuple((RADAR_LABELS[r], f"rr:{radar_alert_id}:{r}") for r in ratings)


def plan_button(setup_id) -> tuple[str, str]:
    """Plan it on a Radar setup ping, keyed by its ``RadarSetup`` row (``radar_setup_plan.plan``)."""
    return ("Plan it", f"rp:{setup_id}")


def rate_buttons(investigation_id, index: int, rating: str | None = None) -> tuple[tuple[str, str], ...]:
    """Helped and Didn't under a copilot answer saved on the desk at ``index``: the saved one checked, carrying ``n`` so a
    second tap clears it, as the desk's buttons toggle."""
    key = uuid.UUID(str(investigation_id)).hex
    return tuple((f"✓ {label}" if value == rating else label, f"hd:{key}:{index}:{'n' if value == rating else value[0]}")
                 for value, label in RATE_LABELS.items())


class Replies:
    def __init__(self, engine, *, call=None, alerts_changed=None):
        self.engine = engine
        self.call = call or telegram.call
        self.alerts_changed = alerts_changed  # tells the level alert monitor a Confirm armed an alert
        self.offset: int | None = None
        self.last_error: str | None = None
        self._tasks: set[asyncio.Task] = set()
        self._asked: set = set()  # messages whose Why? was asked in this process
        self._plans: list[str] = []  # the client ids of the plan cards the running turn saved, sent after its answer
        self._saved: tuple[str, int] | None = None  # where the running turn's answer was saved, for its Helped / Didn't
        self.quote = None  # a test's quote reader for Confirm; None reads the copilot's fresh quote

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
        elif verb == "pc":
            reply, chosen = await asyncio.to_thread(self._companion, *rest.partition(":")[::2])
        elif verb == "pl":
            reply, chosen = await asyncio.to_thread(self._plan, *rest.partition(":")[::2])
        elif verb == "rp":
            from app.engine import radar_setup_plan
            reply, chosen = await asyncio.to_thread(radar_setup_plan.plan, self.engine, rest)
            if chosen == radar_setup_plan.PLANNED and self.alerts_changed is not None:
                self.alerts_changed()
        elif verb == "hd":
            reply, chosen = await asyncio.to_thread(self._rate, rest)
        elif verb == "pu":
            from app.engine import position_companion
            companion_id, _, tail = rest.partition(":")
            reply, chosen = await asyncio.to_thread(position_companion.answer, self.engine, companion_id, *tail.partition(":")[::2])
        elif verb in ("why", "ask"):
            if message.get("message_id") in self._asked:  # once per message
                reply, chosen = "Already asked; the answer comes in the chat.", None
            elif self._tasks:  # one turn at a time
                reply, chosen = BUSY, None
            else:
                self._asked.add(message.get("message_id"))
                reply, chosen = "Asking copilot…", WHY
                task = asyncio.create_task(self._why(rest, message) if verb == "why" else self._ask_ping(message))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
        elif verb == "cc":
            key, _, action = rest.partition(":")
            original = message.get("reply_to_message") or {}
            if key != "q":
                reply, chosen = await asyncio.to_thread(self._pass, key) if action == "pass" else ("That button is not one the app knows.", None)
            elif not str(original.get("text") or "").strip():
                reply, chosen = "Telegram no longer shows that message; send it again starting with check.", None
            elif message.get("message_id") in self._asked:
                reply, chosen = "Already checking; the card comes in the chat.", None
            elif self._tasks:
                reply, chosen = BUSY, None
            else:
                self._asked.add(message.get("message_id"))
                reply, chosen = "Checking the call…", CHECKING
                self._start(self._check(str(original["text"]).strip()[:QUESTION_MAX], original))
        elif verb == DONE:
            reply, chosen = None, None
        else:
            return None
        await asyncio.to_thread(self._answer, query, reply)
        if chosen is not None:
            await asyncio.to_thread(self._mark, message, query.get("data"), chosen)
        return verb

    async def handle_message(self, message: dict | None) -> str | None:
        """A message from the owner: a typed question (``ask``), a voice note (``voice``) or a photo (``photo``), or the
        help note for a command; ``refused`` when a voice note cannot be taken, ``busy`` while a turn runs."""
        from app.engine import captures, transcribe
        owner = telegram.chat_id()
        if not message or str((message.get("chat") or {}).get("id")) != owner or str((message.get("from") or {}).get("id")) != owner:
            return None
        text = str(message.get("text") or "").strip()
        voice = message.get("voice") or message.get("audio")
        document = message.get("document") or {}
        photo = (max(message["photo"], key=lambda p: (p.get("width") or 0) * (p.get("height") or 0)) if message.get("photo")
                 else document if str(document.get("mime_type") or "").startswith("image/") else None)
        call, said = None, ""
        if text:
            if text.startswith("/"):
                await asyncio.to_thread(self._reply, message, HELP)
                return "help"
            from app.engine import call_check
            call, said = call_check.classify(text)
            if call == "call" and not said:  # "check" alone, as a reply to a message: that message is the call
                said = str((message.get("reply_to_message") or {}).get("text") or "").strip()
            kind = "check" if call == "call" and said else "ask"
        elif voice:
            refusal = (VOICE_TOO_LONG if int(voice.get("duration") or 0) * 1000 > captures.CLIP_MS
                       or int(voice.get("file_size") or 0) > captures.AUDIO_MAX else None)
            if refusal is None and not (speech := transcribe.status()).configured:
                refusal = speech.note
            if refusal is not None:
                await asyncio.to_thread(self._reply, message, refusal)
                return "refused"
            kind = "voice"
        elif photo:
            kind = "photo"
        else:
            return None
        if self._tasks:
            await asyncio.to_thread(self._reply, message, BUSY)
            return "busy"
        work = (self._ask(text[:QUESTION_MAX], message, offer_check=call == "maybe") if kind == "ask"
                else self._check(said[:QUESTION_MAX], message) if kind == "check"
                else self._voice(str(voice.get("file_id") or ""), message) if kind == "voice"
                else self._photo(str(photo.get("file_id") or ""), message))
        self._start(work)
        return kind

    def _start(self, work) -> None:
        task = asyncio.create_task(work)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

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

    def _companion(self, companion_id: str, action: str) -> tuple[str, str | None]:
        from app.engine import position_companion
        if action == "confirm":
            reply, chosen = position_companion.confirm(self.engine, companion_id, calendar=_calendar())
            if chosen and self.alerts_changed is not None:
                self.alerts_changed()
            return reply, chosen
        if action == "ignore":
            return position_companion.ignore(self.engine, companion_id)
        return "That button is not one the app knows.", None

    def _plan(self, client_id: str, action: str) -> tuple[str, str | None]:
        if action != "confirm":
            return "That button is not one the app knows.", None
        return confirm_plan(self.engine, client_id, quote=self.quote, armed=self.alerts_changed)

    def _rate(self, rest: str) -> tuple[str, tuple | None]:
        """Helped / Didn't on an answer saved on the desk, set as the desk sets it; the chosen value is the new row."""
        from app.engine import copilot_investigations as investigations
        key, _, tail = rest.partition(":")
        index, _, code = tail.partition(":")
        if not PLAN_KEY.match(key) or not index.isdigit() or code not in RATE_CODES:
            return "That button is not one the app knows.", None
        rating = RATE_CODES[code]
        try:
            with Session(self.engine) as db:
                investigations.set_rating(uuid.UUID(key), int(index), rating, session=db)
        except investigations.InvestigationError as exc:
            return str(exc), None
        return (f"Saved: {RATE_LABELS[rating]}." if rating else "Rating cleared."), rate_buttons(key, int(index), rating)

    async def _why(self, alert_id: str, message: dict) -> None:
        try:
            text = await self.why_text(alert_id)
        except Exception:  # noqa: BLE001 - the owner hears that it failed, never silence
            log.exception("Telegram Why? turn failed")
            text = FAILED
        await asyncio.to_thread(self._reply, message, text, self._rate_row())
        await asyncio.to_thread(self._send_plans, message)

    async def _ask_ping(self, message: dict) -> None:
        """Why? on a ping that is not an open-trade alert: copilot on the ping's own text."""
        try:
            if not str(message.get("text") or message.get("caption") or "").strip():
                answer = "Telegram no longer shows that ping's text to the bot; reply to it with your question instead."
            else:
                answer = await self.question_text(WHY_QUESTION, message)
        except Exception:  # noqa: BLE001 - the owner hears that it failed, never silence
            log.exception("Telegram Why? turn failed")
            answer = FAILED
        await asyncio.to_thread(self._reply, message, answer, self._rate_row())
        await asyncio.to_thread(self._send_plans, message)

    async def _ask(self, text: str, message: dict, offer_check: bool = False) -> None:
        try:
            answer = await self.question_text(text, message.get("reply_to_message"))
        except Exception:  # noqa: BLE001 - the owner hears that it failed, never silence
            log.exception("Telegram question turn failed")
            answer = FAILED
        await asyncio.to_thread(self._reply, message, answer, self._rate_row() + ((CHECK_AS_CALL,) if offer_check else ()))
        await asyncio.to_thread(self._send_plans, message)

    async def _check(self, text: str, message: dict, images: list[dict] | None = None) -> dict | None:
        """Check a call and reply with its card; returns the check (``{"not_a_call": True}`` for an image with no call,
        not replied to: the caller decides), or None when it was refused or failed (the reply says so)."""
        from app.engine import call_check
        try:
            check = await call_check.run(text, source="telegram", images=images, db_engine=self.engine)
        except call_check.CheckRefused as exc:
            await asyncio.to_thread(self._reply, message, str(exc))
            return None
        except Exception:  # noqa: BLE001 - the owner hears that it failed, never silence
            log.exception("Telegram call check failed")
            await asyncio.to_thread(self._reply, message, FAILED)
            return None
        if not check.get("not_a_call"):
            await asyncio.to_thread(self._send_check, message, check)
        return check

    def _send_check(self, message: dict, check: dict) -> None:
        """The check card as a reply: its chat lines, then Plan it (a link, when the app's address is set), Pass and Why?.
        A check with nothing read gets no buttons."""
        from app.engine import call_check
        text = call_check.telegram_text(check)
        row = []
        if check.get("symbol"):
            app_url = os.environ.get("ALERT_APP_URL", "").strip().rstrip("/")
            if app_url and check.get("plan_href"):
                row.append({"text": "Plan it", "url": app_url + check["plan_href"]})
            row += [{"text": "Pass", "callback_data": f"cc:{uuid.UUID(check['id']).hex}:pass"}, {"text": "Why?", "callback_data": "ask:check"}]
        payload = {"chat_id": telegram.chat_id(), "text": text, "link_preview_options": {"is_disabled": True},
                   "reply_parameters": {"message_id": message.get("message_id"), "allow_sending_without_reply": True}}
        if row:
            payload["reply_markup"] = {"inline_keyboard": [row]}
        try:
            self.call("sendMessage", json=payload)
        except telegram.TelegramError as exc:
            log.warning("Telegram check card not delivered: %s", exc)

    def _pass(self, key: str) -> tuple[str, str | None]:
        from app.engine import call_check
        if not PLAN_KEY.match(key or ""):
            return "That button is not one the app knows.", None
        with Session(self.engine) as db:
            return call_check.pass_check(db, key)

    async def _voice(self, file_id: str, message: dict) -> None:
        """A voice note: downloaded, transcribed with the owner's tickers as vocabulary, confirmed back, then asked."""
        from app.engine import captures, transcribe
        try:
            data = await asyncio.to_thread(telegram.download, file_id, captures.AUDIO_MAX, call=self.call)
            kind = captures.sniff_audio(data)
            heard = await asyncio.to_thread(self._transcribe, data, captures.AUDIO_TYPES[kind])
        except telegram.FileTooLarge:
            answer = VOICE_TOO_LONG
        except telegram.TelegramError as exc:
            log.warning("Telegram voice note not downloaded: %s", exc)
            answer = "The voice note could not be downloaded from Telegram."
        except (captures.CaptureError, transcribe.TranscriptionError) as exc:
            answer = str(exc)
        except Exception:  # noqa: BLE001 - the owner hears that it failed, never silence
            log.exception("Telegram voice note failed")
            answer = FAILED
        else:
            if not heard:
                answer = "No words were heard in that voice note."
            else:
                await asyncio.to_thread(self._reply, message, f"Heard: {heard}")
                await self._ask(heard[:QUESTION_MAX], message)
                return
        await asyncio.to_thread(self._reply, message, answer)

    def _transcribe(self, data: bytes, extension: str) -> str:
        """The words in a clip, spoken tickers written as symbols, primed as the composer's hold-to-talk is."""
        from app.engine import spoken_tickers, transcribe
        with Session(self.engine) as db:
            traded = spoken_tickers.traded(db)
        known = spoken_tickers.known_symbols(traded)
        heard = transcribe.transcribe_bytes(data, extension, spoken_tickers.prompt_for(known, traded)).strip()
        return spoken_tickers.map_tickers(heard, known)[0]

    async def _photo(self, file_id: str, message: dict) -> None:
        """A photo: processed into the image store, attached to one turn (its caption, else the reconcile question),
        and deleted when the turn ends, whatever happens. With no caption, or a caption that is a call, it is first
        checked as a call; with no caption and no call in it, it is the broker screenshot."""
        from app.ai import copilot_images
        from app.engine import call_check
        image_id = None
        try:
            data = await asyncio.to_thread(telegram.download, file_id, copilot_images.MAX_IN, call=self.call)
            image_id = (await asyncio.to_thread(copilot_images.store, data))["id"]
            caption = str(message.get("caption") or "").strip()
            images = [copilot_images.block(copilot_images.load(image_id))]
            call, said = call_check.classify(caption) if caption else ("call", "")
            if call == "call":
                check = await self._check(said[:QUESTION_MAX], message, images=images)
                if check is None or not check.get("not_a_call"):
                    return  # the card, or what stopped it, is already in the chat
                if caption:
                    await asyncio.to_thread(self._reply, message, "That screenshot does not show a trade call.")
                    return
            answer = await self.question_text(caption[:QUESTION_MAX] or RECONCILE_QUESTION, message.get("reply_to_message"),
                                              images=images)
        except telegram.FileTooLarge:
            answer = "The image is larger than 8 MB."
        except telegram.TelegramError as exc:
            log.warning("Telegram photo not downloaded: %s", exc)
            answer = "The photo could not be downloaded from Telegram."
        except copilot_images.ImageError as exc:
            answer = str(exc)
        except Exception:  # noqa: BLE001 - the owner hears that it failed, never silence
            log.exception("Telegram photo turn failed")
            answer = FAILED
        finally:
            if image_id:
                copilot_images.delete(image_id)
        await asyncio.to_thread(self._reply, message, answer, self._rate_row())
        await asyncio.to_thread(self._send_plans, message)

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

    def _ping_symbol(self, ping: dict) -> str | None:
        """The symbol a ping is about (``ping_symbol``); None when it names none or more than one, or the read fails."""
        try:
            with Session(self.engine) as db:
                return ping_symbol(db, ping)
        except Exception:  # noqa: BLE001 - the question is still asked, without a symbol
            log.warning("Telegram ping symbol not resolved", exc_info=True)
            return None

    async def why_text(self, alert_id: str) -> str:
        """One bounded copilot turn on the alert, as plain text for the chat."""
        from app.ai import copilot
        if not copilot.settings().enabled:
            return "Copilot Lab is off on this server, so there is no answer here."
        found = await asyncio.to_thread(self._alert_context, alert_id)
        if found is None:
            return "That alert is no longer in the journal."
        return await self.turn(*found, said="Why? on a position alert")

    async def question_text(self, text: str, replied: dict | None, images: list[dict] | None = None) -> str:
        """One bounded copilot turn on a typed question; a reply to a ping carries that ping as its context. ``images``:
        a Telegram photo's image block, attached to the turn (the desk notes "(photo)", never keeps the image)."""
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
                # Any other ping that is about one name gets that name, so the turn reads its owner context and
                # prefetches its quote as a position alert's does.
                symbol = await asyncio.to_thread(self._ping_symbol, replied)
        question = f"{context}\n\nMy question about this: {text}" if context else text
        # The desk keeps only the owner's own words: a ping's text (a headline, a research result) never becomes theirs.
        said = "Why? on a ping" if text == WHY_QUESTION else text if not context else f"(replying to a ping) {text}"
        if images:
            return await self.turn(question, symbol, said=f"(photo) {said}", images=images)
        return await self.turn(question, symbol, said=said)

    async def turn(self, question: str, symbol: str | None, said: str | None = None, images: list[dict] | None = None) -> str:
        """One bounded copilot turn (the configured backend, its turn and daily budgets), as plain text for the chat."""
        from app.ai import copilot, copilot_spend
        from app.engine.chart_math import ET
        cfg = copilot.settings()
        if cfg.backend == "anthropic":
            spent = await asyncio.to_thread(copilot_spend.spent_today)
            if spent >= cfg.daily_budget_usd:
                await asyncio.to_thread(copilot_spend.record_refused, kind="ask", source="telegram", backend=cfg.backend,
                                        code="daily_budget", symbol=symbol)
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
        cards: list[str] = []
        plans: list[dict] = []
        turn_id: str | None = None
        self._plans, self._saved = [], None
        try:
            turn = copilot_spend.recorded_turn(history, symbol, cfg, adapter, evidence, now, kind=None, source="telegram",
                                               images=images, web=True)
            async with contextlib.aclosing(turn) as events:
                async for event in events:
                    if event.get("type") == "text":
                        parts.append(event.get("delta") or "")
                    elif event.get("type") == "error":
                        errors.append(event.get("message") or "")
                    elif event.get("type") == "done":
                        turn_id = event.get("turn_id")
                    elif event.get("type") == "proposal" and event.get("kind") == "trade_plan" and len(plans) < PLAN_CARDS:
                        # Saved as the desk saves a card: the event without its type, with a client id of its own.
                        plans.append({**{k: v for k, v in event.items() if k != "type"}, "client_id": uuid.uuid4().hex})
                    elif event.get("type") == "proposal":
                        cards.append(str(next((event[k] for k in ("label", "question", "thesis", "text") if event.get(k)), event.get("kind") or "a card"))[:160])
        finally:
            if hasattr(adapter, "aclose"):
                await adapter.aclose()
        answer = "".join(parts).strip()
        if cards:  # a card is confirmed on the desk, and a chat cannot show one: say so rather than leave "confirm it" dangling
            answer = (answer + "\n\n" if answer else "") + ("Proposed here, but a card can only be confirmed on the desk: "
                                                         + "; ".join(cards) + ". Ask there to set it up.")
        if errors:
            answer = (answer + "\n\n" if answer else "") + " ".join(errors)
        answer = answer or "The copilot gave no answer."
        answer = answer if len(answer) <= ANSWER_MAX else answer[: ANSWER_MAX - 1].rstrip() + "…"
        self._saved = await asyncio.to_thread(self._save, said or question, symbol, answer, now, plans, turn_id)
        if self._saved and plans:
            self._plans = [p["client_id"] for p in plans]  # sent after the answer (``_send_plans``)
        return answer

    def _save(self, said: str, symbol: str | None, answer: str, now: datetime, plans: list[dict] = (),
              turn_id: str | None = None) -> tuple[str, int] | None:
        """The owner's words and the answer, with its plan cards, as messages on the desk: the symbol's thread
        (``thread_for``), else today's Main chat; where the answer went (conversation id, message index). A failure only
        leaves the desk without them (and the answer without Helped / Didn't); the chat already has the answer."""
        try:
            with Session(self.engine) as db:
                return save_on_desk(db, said, symbol, answer, now, plans, turn_id=turn_id)
        except Exception:  # noqa: BLE001
            log.warning("Telegram answer not saved on the desk", exc_info=True)
            return None

    def _rate_row(self) -> tuple[tuple[str, str], ...]:
        """Helped and Didn't for the answer the last turn saved (taken once), or none when it was not saved."""
        saved, self._saved = self._saved, None
        return rate_buttons(*saved) if saved else ()

    def _send_plans(self, message: dict) -> None:
        """Each plan card the turn saved, as its own message after the answer: the card's lines, Confirm and Edit (its
        thread on the desk). A card that cannot be read or sent is logged; it stays on the desk to confirm there."""
        keys, self._plans = self._plans, []
        for key in keys:
            try:
                with Session(self.engine) as db:
                    found = find_plan(db, key)
                if found is None:
                    log.warning("Telegram plan card %s not found on the desk", key)
                    continue
                thread_id, card = found
                from app.engine.position_companion import desk_path
                markup = telegram.keyboard(desk_path(thread_id), (("Confirm", f"pl:{key}:confirm"),), open_label="Edit")
                self.call("sendMessage", json={
                    "chat_id": telegram.chat_id(), "text": plan_text(card), "reply_markup": markup,
                    "reply_parameters": {"message_id": message.get("message_id"), "allow_sending_without_reply": True},
                    "link_preview_options": {"is_disabled": True}})
            except Exception as exc:  # noqa: BLE001 - the answer is already sent and the card is on the desk
                log.warning("Telegram plan card not delivered: %s", exc if isinstance(exc, telegram.TelegramError) else type(exc).__name__,
                            exc_info=not isinstance(exc, telegram.TelegramError))

    # -------------------------------------------------------------- the chat

    def _reply(self, message: dict, text: str, buttons: tuple[tuple[str, str], ...] = ()) -> None:
        """A reply to ``message``; ``buttons``: one row of reply buttons under it (an answer's Helped / Didn't)."""
        payload = {"chat_id": telegram.chat_id(), "text": text, "reply_parameters": {"message_id": message.get("message_id"),
                                                                                     "allow_sending_without_reply": True},
                   "link_preview_options": {"is_disabled": True}}
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": [[{"text": label, "callback_data": data} for label, data in buttons]]}
        try:
            self.call("sendMessage", json=payload)
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

    def _mark(self, message: dict, data: str, chosen) -> None:
        """Edit the message's keyboard: a ping's answers, on however many rows they sit, give way to "✓ <the saved
        answer>" on the first of those rows, its Why? (and a Radar setup's Plan it) kept beside it; Why? is marked asked; Helped / Didn't (``chosen``:
        their new buttons) show the saved rating and stay tappable."""
        rows = ((message.get("reply_markup") or {}).get("inline_keyboard")) or []
        done = f"{DONE}:{data.split(':')[1]}" if data.count(":") >= 1 else DONE  # keeps the alert for a typed reply
        edited = []
        if chosen is WHY or chosen is CHECKING or isinstance(chosen, tuple):
            for row in rows:
                tapped = next((b for b in row if b.get("callback_data") == data), None)
                if tapped is None:
                    edited.append(row)
                elif chosen is WHY or chosen is CHECKING:
                    label = "✓ Why? (answer below)" if chosen is WHY else "✓ Checked (card below)"
                    edited.append([{"text": label, "callback_data": done} if b is tapped else b for b in row])
                else:
                    edited.append([{"text": label, "callback_data": value} for label, value in chosen])
        else:
            group = data.rsplit(":", 1)[0] + ":"  # this ping's answers: the tapped one's verb and id

            def answer(b):
                return str(b.get("callback_data", "")).startswith(group)
            kept, first = [], None
            for row in rows:
                if not any(answer(b) for b in row):
                    edited.append(row)
                    continue
                if first is None:
                    first = len(edited)
                    edited.append([])
                kept += [b for b in row if not answer(b) and str(b.get("callback_data", "")).startswith(("why:", "ask:", "rp:", DONE))]
            if first is not None:
                edited[first] = [{"text": f"✓ {chosen}", "callback_data": done}, *kept]
        if edited == rows:
            return
        try:
            self.call("editMessageReplyMarkup", json={"chat_id": telegram.chat_id(), "message_id": message.get("message_id"),
                                                      "reply_markup": {"inline_keyboard": edited}})
        except telegram.TelegramError as exc:
            log.info("Telegram keyboard not updated: %s", exc)


FROM_TELEGRAM = "From Telegram: "


PING_TICKER = re.compile(r"(?<![A-Za-z0-9$])\$?([A-Z][A-Z0-9]{1,4}(?:\.[A-Z])?)(?![A-Za-z0-9])")
BENCHMARKS = frozenset({"SPY", "QQQ", "IWM", "DIA", "RSP"})  # "vs SPY" in a ping is the yardstick, not its subject
YARDSTICK = re.compile(r"\b(?:vs\.?|versus|of|than)\s+\$?(SPY|QQQ|IWM|DIA|RSP)\b", re.I)
# Tickers in the Radar universe that are also words a ping writes in capitals ("AI software", "NOW reports"): never read
# from text. A ping about one of them still resolves through its own row.
WORD_TICKERS = frozenset({"AI", "AN", "DE", "MA", "CI", "PL", "NOW", "LOW", "HOOD"})
SYMBOL_IN_PATH = re.compile(r"[?&]symbol=([A-Za-z][A-Za-z0-9.\-]{0,9})(?:&|$)")


def ping_symbol(db: Session, ping: dict) -> str | None:
    """The one symbol a ping (a Telegram message the bot sent) is about, for a question or Why? on it. First from the
    row behind its buttons: a Radar ping's alert (its subject, when that is a stock and not a group), a Radar setup, a
    position companion message, a trade plan card, or the conversation under a copilot answer; then a ``symbol=`` in
    its Open link; last, the single known ticker (Radar's universe or one the owner traded) its text names. Not counted there:
    a benchmark it is compared with ("vs SPY", "ahead of SPY") or named beside another ticker, and a ticker that is also a
    word ("AI"). None when it names none, or more than one. Known limit: a one-letter ticker (F, V) is never read from
    text."""
    from app.models import CopilotInvestigation, PositionCompanion, RadarAlert, RadarSetup
    for row in (ping.get("reply_markup") or {}).get("inline_keyboard") or []:
        for button in row:
            verb, _, rest = str(button.get("callback_data") or "").partition(":")
            key = rest.split(":")[0]
            found = None
            if verb == "rr" and (row_id := _uuid(key)):
                alert = db.get(RadarAlert, row_id)
                found = alert.subject if alert else None
            elif verb == "rp" and (row_id := _uuid(key)):
                setup = db.get(RadarSetup, row_id)
                found = setup.symbol if setup else None
            elif verb in ("pc", "pu") and (row_id := _uuid(key)):
                companion = db.get(PositionCompanion, row_id)
                found = companion.ticker if companion else None
            elif verb == "pl":
                plan = find_plan(db, key)
                found = plan[1].get("symbol") if plan else None
            elif verb == "hd" and (row_id := _uuid(key)):
                thread = db.get(CopilotInvestigation, row_id)
                found = thread.symbol if thread else None
            if found and SYMBOL.match(str(found)):  # as stored: a group's name ("Semis") is not a ticker
                return str(found)
            if (link := SYMBOL_IN_PATH.search(str(button.get("url") or ""))) and SYMBOL.match(link.group(1).upper()):
                return link.group(1).upper()
    text = str(ping.get("text") or ping.get("caption") or "")
    from app.engine import spoken_tickers
    named = {m for m in PING_TICKER.findall(text)}
    if not named:
        return None
    yardsticks = {m.upper() for m in YARDSTICK.findall(text)}  # "vs SPY", "ahead of QQQ": the comparison, not the subject
    known = (named - WORD_TICKERS - yardsticks) & spoken_tickers.known_symbols(spoken_tickers.traded(db))
    if known - BENCHMARKS:  # a benchmark beside a name is the yardstick; alone, it is the subject
        known -= BENCHMARKS
    return next(iter(known)) if len(known) == 1 else None


def thread_for(db: Session, symbol: str) -> str | None:
    """The symbol's desk thread: its plan (in a position first), else the conversation the companion adopted it in,
    else the newest open conversation about it; None when it has none. Never a new conversation: an open one with a
    symbol is what thesis watch watches, so making one would start pings."""
    from sqlmodel import col, select
    from app.engine import desk_context, position_companion
    from app.models import CopilotInvestigation
    found = desk_context.symbol_thread(db, symbol).id
    if found:
        return found
    for row in position_companion.adopted_trades(db).values():
        if row.ticker == symbol and row.investigation_id:
            return str(row.investigation_id)
    latest = db.exec(select(CopilotInvestigation).where(CopilotInvestigation.symbol == symbol, CopilotInvestigation.status == "open",
                                                        CopilotInvestigation.source == "copilot", CopilotInvestigation.main_day.is_(None))
                     .order_by(col(CopilotInvestigation.updated_at).desc())).first()
    return str(latest.id) if latest is not None else None


def save_on_desk(db: Session, said: str, symbol: str | None, answer: str, now: datetime, plans: list[dict] = (), *,
                 turn_id: str | None = None) -> tuple[str, int]:
    """Append one Telegram exchange to the desk (``said``: the owner's own words, never a ping's text); the
    investigation id it went to and the answer's index there (what Helped / Didn't rate). ``turn_id``: the turn's
    ``copilot_turn`` row, kept in the answer's metrics as the desk keeps it, so the scorecard meets the two. On the
    symbol's thread its ``updated_at`` is kept as it was, so thesis watch, which re-checks each symbol's newest open
    conversation, re-checks the same one; with no thread, today's Main chat.
    ``plans``: the answer's trade plan cards as the desk saves them (the proposal event without its type, with a client
    id); one that does not validate is left out and logged, so it never costs the exchange its save."""
    from sqlalchemy import update as sql_update
    from app.engine import copilot_investigations as investigations, position_companion
    from app.models import CopilotInvestigation
    metrics = {"metrics": {"turn_id": turn_id}} if turn_id else {}
    cards = []
    for card in plans:
        try:
            cards.append(investigations._saved_proposal(card))
        except ValueError as exc:
            log.warning("Telegram plan card not saved: %s", exc)
    target = thread_for(db, symbol) if symbol else None
    if target is not None:
        before = db.get(CopilotInvestigation, uuid.UUID(target)).updated_at
        taken = {p["id"] for m in investigations.get(target, session=db)["transcript"] for p in m.get("proposals") or ()}
        for card in cards:  # unique in the conversation, as the desk makes a repeated id unique
            base, n = card["id"], 2
            while card["id"] in taken:
                card["id"], n = f"{base}.{n}", n + 1
            taken.add(card["id"])
        saved = position_companion.save_messages(target, [{"role": "user", "content": FROM_TELEGRAM + said},
                                                          {"role": "assistant", "content": answer, "proposals": cards, **metrics}], session=db)
        db.execute(sql_update(CopilotInvestigation).where(CopilotInvestigation.id == uuid.UUID(target)).values(updated_at=before))
        db.commit()
        return target, len(saved["transcript"]) - 1
    from app.engine.chart_math import ET
    main = investigations.main_chat(db, now.astimezone(ET).date())
    about = f" ({symbol})" if symbol else ""
    exchange = investigations.InvestigationFields(title=main["title"], transcript=[
        {"role": "user", "content": FROM_TELEGRAM.rstrip(": ") + about + ": " + said},
        {"role": "assistant", "content": answer, "exchange_id": (receipt := f"telegram-{uuid.uuid4().hex}"), **metrics,
         **({"proposals": cards} if cards else {})}])
    saved = investigations.append_main(db, main["id"], exchange)  # a plan card gets its own plan thread there
    return saved["id"], next(i for i, m in enumerate(saved["transcript"]) if m.get("exchange_id") == receipt)


def find_plan(db: Session, client_id: str) -> tuple[str, dict] | None:
    """The saved trade plan card with this client id and the conversation that holds it, or None. A Main chat card is
    found in its own plan thread (the Main chat row keeps only the pointer the desk opens it from)."""
    from sqlmodel import col, select
    from app.models import CopilotInvestigation
    if not PLAN_KEY.match(client_id or ""):
        return None
    rows = db.exec(select(CopilotInvestigation).where(CopilotInvestigation.main_day.is_(None),
                                                      CopilotInvestigation.transcript_json.contains(client_id, autoescape=True))
                   .order_by(col(CopilotInvestigation.created_at).desc()))
    for row in rows:
        for m in json.loads(row.transcript_json):
            for card in m.get("proposals") or ():
                if card.get("client_id") == client_id and card.get("kind") == "trade_plan":
                    return str(row.id), card
    return None


def _level(level: dict) -> str:
    """"crosses 92.3", "5m close beyond 95.9": the card's own wording of a level."""
    condition = (f"{level.get('interval')} close beyond" if level.get("condition") == "closes_beyond"
                 else CONDITION.get(level.get("condition"), level.get("condition")))
    return f"{condition} {level['price']:,.4f}".rstrip("0").rstrip(".")


def _horizon(card: dict, now: float) -> str:
    """The card's default horizon: a time stop due today is a day trade, else a swing (the desk's ``horizonFor``)."""
    from app.engine import plan_time_stops
    from app.engine.chart_math import ET
    due = plan_time_stops.parse(card.get("time_stop") or "", now).get("due_at")
    return "day" if due and datetime.fromtimestamp(due, ET).date() == datetime.fromtimestamp(now, ET).date() else "swing"


def plan_text(card: dict, now: float | None = None) -> str:
    """A plan card as one Telegram message, its lines as the desk's card shows them."""
    side = PLAN_SIDE.get((card.get("direction"), card.get("instrument")), f"{card.get('direction')} {card.get('instrument')}")
    lines = [f"Proposed trade plan · {card['symbol']} · {side}" + (f" · {card['contract']}" if card.get("contract") else ""),
             f"Thesis: {card.get('thesis') or ''}".rstrip(),
             f"Entry: {_level(card['entry_trigger'])}",
             f"Invalidation: {_level(card['invalidation'])}"]
    if card.get("time_stop"):
        lines.append(f"Time stop: {card['time_stop']}")
    lines.append(f"Horizon: {HORIZON_LABEL[_horizon(card, time.time() if now is None else now)]}")
    lines.append(PLAN_FOOTER)
    return "\n".join(lines)


def _fresh_quote(symbol: str) -> tuple[float | None, bool]:
    """The copilot's fresh quote, as the desk's Confirm reads it (``GET /copilot/quote``): ``(last, fresh)``."""
    from app.routers.copilot import quote
    try:
        read = quote(symbol)
    except HTTPException:
        return None, False
    return read.get("last"), bool(read.get("fresh"))


def _calendar():
    """The market calendar the time-stop route reads a time stop with."""
    from app.engine.chart_calendar import chart_calendar
    return chart_calendar


def _plan_account(db: Session) -> str | None:
    """The plan's journal account as the desk picks it: the capture default, else the only account."""
    from sqlmodel import select
    from app.engine import captures
    from app.models import Account
    default = captures.profile(db).default_account_id
    if default is not None:
        return str(default)
    accounts = db.exec(select(Account.id)).all()
    return str(accounts[0]) if len(accounts) == 1 else None


def confirm_plan(engine, client_id: str, *, quote=None, now: float | None = None, armed=None) -> tuple[str, str | None]:
    """Confirm on a Telegram plan card: the desk's Confirm (``TradePlanCard``), part by part, through the engine
    functions its routes call. The pre-trade plan first (``captures.build``/``save`` as ``POST /charts/captures`` with
    the card's client id, then the horizon entry the desk saves with it); only once it is saved, the entry and
    invalidation alerts (a fresh quote each, ``create_alert`` as ``POST /charts/alerts``; an invalidation the price has
    already crossed is refused) and, when the server reads it as a time, the time stop (``plan_time_stops.create`` with
    the client id). Each part has its own result, recorded on the card's outcome as the desk records it, with a note
    saying it came from Telegram; a later tap runs only the parts not done (the client id keeps the plan and time stop
    single). Saves nothing without an account to put the plan on, or for a card dismissed or confirmed on the desk.
    ``armed`` is called when an alert was armed. ``(reply, chosen label)``: the label only once every part is done, so
    the button stays for a retry."""
    from app.engine import captures, copilot_investigations as investigations, day_journal, plan_time_stops
    from app.engine.chart_math import ET
    from app.engine.level_alert_monitor import create_alert
    now = time.time() if now is None else now
    with Session(engine) as db:
        found = find_plan(db, client_id)
        if found is None:
            return "That plan is no longer on the desk.", None
        thread_id, card = found
        outcome = card.get("outcome") or {}
        if outcome.get("state") == "dismissed":
            return "Not confirmed: this plan was dismissed on the desk.", None
        if outcome.get("state") == "confirmed" and not str(outcome.get("note") or "").startswith(FROM_TELEGRAM_NOTE):
            return "Already confirmed on the desk.", "Confirmed"
        results = {part: dict(r) for part, r in (outcome.get("parts") or {}).items()}
        symbol, long = card["symbol"], card["direction"] == "long"
        stop_text = (card.get("time_stop") or "").strip()
        timed = plan_time_stops.parse(stop_text, now, _calendar()) if stop_text else {"due_at": None}
        wanted = ["plan", "entry", "invalidation", *(["timeStop"] if timed.get("due_at") or "timeStop" in results else [])]
        todo = [part for part in wanted if results.get(part, {}).get("state") != "done"]
        if not todo:
            return "Already confirmed: the plan is saved and its alerts are armed.", "Confirmed"
        account = _plan_account(db) if "plan" in todo else None
        if "plan" in todo and account is None:
            return "Set a default account for plans on the desk first; nothing was saved.", None
        horizon = _horizon(card, now)
        size = (card.get("size_note") or "").strip()
        lines, alerts = [], 0

        def result(part: str, done: bool, text: str, line: str = "") -> None:
            results[part] = {"state": "done" if done else "failed", "text": text[:500]}
            lines.append(line if done else f"{PART_NAME[part]} failed: {text}")

        if "plan" in todo:
            side = PLAN_CAPTURE_SIDE.get((card["direction"], card["instrument"]), "")
            wording = " ".join(filter(None, [f"Entry: {_level(card['entry_trigger'])}.", f"Invalidation: {_level(card['invalidation'])}.",
                                             stop_text and f"Time stop: {stop_text}.", size and f"Size: {size}."]))[:400]
            note = " ".join(filter(None, [f"Thesis: {(card.get('thesis') or '').strip()}",
                                          card.get("contract") and f"Contract: {card['contract']}.", "From a Copilot Lab plan card."]))[:500]
            try:  # the desk's savePlanCapture body, then its saveHorizon
                captures.save(db, captures.build(db, {
                    "client_id": client_id, "underlying": symbol, "account_id": account, "side": side, "wording": wording, "note": note,
                    "client_captured_at": now * 1000, "mode": "discretionary", "setup_label": "Copilot plan", "image": False,
                    "origin": {"kind": "copilot", "ref": thread_id, "text": None},
                    "context": {"state": "unavailable", "reason": "Saved from a Copilot Lab plan card.", "investigation_id": thread_id}}))
                day_journal.append(db, day=datetime.fromtimestamp(now, ET).date(), operation_id=f"horizon-{client_id}-{horizon}",
                                   kind="horizon", text=HORIZON_LABEL[horizon], symbol=symbol)
                result("plan", True, "Saved as your pre-trade plan. It is suggested for the trade when the fill arrives.", "Plan saved")
            except (captures.CaptureError, day_journal.EntryError) as exc:
                db.rollback()
                result("plan", False, str(exc))
        if results["plan"]["state"] == "done":  # the alerts and time stop only once the plan is saved, as the desk runs them
            for part in ("entry", "invalidation"):
                if part not in todo:
                    continue
                level = card["entry_trigger"] if part == "entry" else card["invalidation"]
                price, wording = level["price"], _level(level)
                last, fresh = (quote or _fresh_quote)(symbol)  # read fresh for each alert, as the desk does
                if not fresh or not last:
                    result(part, False, f"The latest {symbol} quote is stale or missing, so it was not set.")
                elif last == price:
                    result(part, False, f"{symbol} is at {price:g} now, so the alert has no side to wait on.")
                elif part == "invalidation" and (last < price if long else last > price):
                    result(part, False, f"{symbol} is at {last:g}, already past the invalidation at {price:g}, so it was not set.")
                else:
                    try:
                        create_alert(db, symbol=symbol, price=price, reference=last, condition=level["condition"], interval=level.get("interval"),
                                     session="regular", source_kind="copilot", source_id=thread_id, label=f"{symbol} {part}: {wording}"[:60],
                                     now=now, plan_role=part)
                    except ValueError as exc:
                        result(part, False, str(exc))
                    else:
                        alerts += 1
                        result(part, True, f"Set: {symbol} {wording}.", f"{PART_NAME[part]}{' alert' if part == 'entry' else ''} armed at {price:,.2f}")
            if "timeStop" in todo:
                try:
                    plan_time_stops.create(db, client_id=client_id, investigation_id=thread_id, symbol=symbol, text=stop_text, now=now,
                                           calendar=_calendar())
                    when = timed.get("when") or stop_text
                    result("timeStop", True, f"Set for {when}.", f"Time stop set: {when}")
                except ValueError as exc:
                    result("timeStop", False, str(exc))
        fields = investigations.PlanFields(
            thesis=(card.get("thesis") or "")[:300], contract=(card.get("contract") or "")[:80],
            entry=f"{card['entry_trigger']['price']:g}"[:24], invalidation=f"{card['invalidation']['price']:g}"[:24],
            time_stop=stop_text[:80], size_note=size[:120], horizon=horizon)
        investigations.set_outcome(thread_id, card["id"], investigations.ProposalOutcome(
            state="confirmed", note=f"{FROM_TELEGRAM_NOTE}.",
            parts={part: investigations.PartResult(**r) for part, r in results.items()}, fields=fields), session=db)
    if alerts and armed is not None:
        armed()
    log.info("Telegram plan confirm for %s: %s", symbol, {part: r["state"] for part, r in results.items()})
    finished = all(results.get(part, {}).get("state") == "done" for part in wanted)
    return "\n".join(lines), "Confirmed" if finished else None


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
