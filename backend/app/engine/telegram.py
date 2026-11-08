"""Phone pings through a Telegram bot: the trading senders' two-way channel (``engine/phone.py`` picks it).

Configured by ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID`` (both, or nothing is sent through Telegram); on the
server systemd passes them with ``ALERT_APP_URL`` in ``/etc/tradejournal/alerts.env``. Every message goes to the one
chat. The bot only ever calls out to ``api.telegram.org``: replies are read by long polling
(``engine/telegram_replies.py``), never by an inbound webhook, so the private API stays private.

``publish`` sends ``sendMessage`` (or ``sendPhoto`` with the PNG when ``image`` is given, the text as its caption)
with the title bold, the text HTML-escaped, and an inline keyboard: the reply ``buttons`` (label, callback data) on
the first rows (``keyboard``), and an "Open" button to ``ALERT_APP_URL + path`` (then any ``links``) on the last. It returns
Telegram's message id. A failure raises ``TelegramError``, a ``ntfy.NtfyError`` so every sender's at-most-once
handling is unchanged: a refusal with a status, or no connection, certainly sent nothing (``surely_unsent``); any
other failure (a read timeout) may have reached the phone. No retries here: the senders own them.

``download`` fetches one file the owner sent the bot (a voice note, a photo): ``getFile`` for its path, then the bytes
from Telegram's file host, capped (``FileTooLarge`` above the cap). The bytes are untrusted data held in memory only.
"""

import html
import json
import logging
import os

import httpx

from app.engine import ntfy

API_URL = "https://api.telegram.org"
TIMEOUT_SECONDS = 10
CALLBACK_MAX = 64  # Telegram's limit on a button's callback data, in bytes
TEXT_MAX = 4096
CAPTION_MAX = 1024

# httpx logs each request line at INFO, and the bot token is part of a Bot API URL: keep those lines out of the logs.
logging.getLogger("httpx").setLevel(logging.WARNING)


class TelegramError(ntfy.NtfyError):
    @property
    def surely_unsent(self) -> bool:
        """True when the message certainly never reached Telegram: refused with a status, or no connection."""
        cause = self.__cause__
        return cause is None or isinstance(cause, (httpx.ConnectError, httpx.ConnectTimeout))


class ImageRefused(TelegramError):
    """Telegram refused the picture with a 4xx (not a rate limit): nothing was sent, so the caller sends the text."""


def configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() and os.environ.get("TELEGRAM_CHAT_ID", "").strip())


def chat_id() -> str:
    return os.environ.get("TELEGRAM_CHAT_ID", "").strip()


def text_for(title: str, message: str, limit: int = TEXT_MAX) -> str:
    """The message as Telegram HTML: the title bold over the text, both escaped, cut to ``limit`` characters
    (the raw text is cut, never an escape sequence)."""
    head = f"<b>{html.escape(title, quote=False)}</b>\n"
    body = html.escape(message, quote=False)
    if len(head) + len(body) <= limit:
        return head + body
    room, kept = limit - len(head) - 1, []
    for char in message:
        piece = html.escape(char, quote=False)
        if len(piece) > room:
            break
        kept.append(piece)
        room -= len(piece)
    return head + "".join(kept) + "…"


def caption_fits(title: str, message: str) -> bool:
    """Whether the text fits a photo's caption whole; a longer one goes as a text message instead."""
    return len(text_for(title, message, limit=TEXT_MAX)) <= CAPTION_MAX


def keyboard(path: str = "", buttons: tuple[tuple[str, str], ...] = (), links: tuple[tuple[str, str], ...] = (),
             open_label: str = "Open") -> dict | None:
    """The inline keyboard: reply buttons first, then Open (``open_label``, and ``links``) when ``ALERT_APP_URL`` is set.
    Up to three reply buttons share one row; more go two to a row, an odd last one (an alert's Why?) joining the row
    before it, so four answers and Why? read as two rows on a phone."""
    rows = []
    reply = []
    for label, data in buttons:
        if len(data.encode()) > CALLBACK_MAX:
            raise ValueError(f"Callback data longer than {CALLBACK_MAX} bytes: {data!r}")
        reply.append({"text": label, "callback_data": data})
    if len(reply) > 3:
        pairs = [reply[i:i + 2] for i in range(0, len(reply), 2)]
        if len(pairs[-1]) == 1:
            last = pairs.pop()
            pairs[-1] = pairs[-1] + last
        rows.extend(pairs)
    elif reply:
        rows.append(reply)
    if app_url := os.environ.get("ALERT_APP_URL", "").strip():
        rows.append([{"text": label, "url": app_url.rstrip("/") + link} for label, link in ((open_label, path), *links)])
    return {"inline_keyboard": rows} if rows else None


def publish(title: str, message: str, *, path: str = "", buttons: tuple[tuple[str, str], ...] = (), image: bytes | None = None,
            priority: int = 4, links: tuple[tuple[str, str], ...] = (), reply_to: str | None = None, open_label: str = "Open") -> str | None:
    """Send one message to the configured chat; raises ``TelegramError`` when Telegram did not accept it (``ImageRefused``
    for a refused picture). Priority 2 or lower sends silently. ``reply_to``: a message id this one replies to, so one
    conversation reads as one thread (sent anyway when that message is gone). Returns the message id: proof Telegram
    accepted it."""
    if not configured():
        raise TelegramError("Telegram is not set up on this server (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID).")
    markup = keyboard(path, buttons, links, open_label)
    fields: dict = {"chat_id": chat_id(), "parse_mode": "HTML", "disable_notification": priority <= 2}
    if reply_to:
        fields["reply_parameters"] = {"message_id": int(reply_to), "allow_sending_without_reply": True}
    if image is not None:
        fields["caption"] = text_for(title, message, limit=CAPTION_MAX)
        if markup:
            fields["reply_markup"] = json.dumps(markup)
        if "reply_parameters" in fields:
            fields["reply_parameters"] = json.dumps(fields["reply_parameters"])
        data = {k: (str(v).lower() if isinstance(v, bool) else str(v)) for k, v in fields.items()}
        result = call("sendPhoto", data=data, files={"photo": ("chart.png", image, "image/png")}, image=True)
    else:
        fields.update(text=text_for(title, message), link_preview_options={"is_disabled": True})
        if markup:
            fields["reply_markup"] = markup
        result = call("sendMessage", json=fields)
    message_id = result.get("message_id") if isinstance(result, dict) else None
    return str(message_id) if message_id is not None else None


def call(method: str, *, json: dict | None = None, data: dict | None = None, files: dict | None = None, timeout: float = TIMEOUT_SECONDS,
         image: bool = False):
    """One Bot API call: its ``result``, or ``TelegramError`` (never the token in the message)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    try:
        response = httpx.post(f"{API_URL}/bot{token}/{method}", json=json, data=data, files=files, timeout=timeout)
    except httpx.HTTPError as exc:
        raise TelegramError(f"Telegram could not be reached ({type(exc).__name__}).") from exc
    try:
        body = response.json()
    except ValueError:
        body = {}
    if 200 <= response.status_code < 300 and body.get("ok"):
        return body.get("result")
    status = body.get("error_code") or response.status_code
    reason = str(body.get("description") or "")[:200]
    if image and 400 <= response.status_code < 500 and response.status_code != 429:
        raise ImageRefused(f"Telegram refused the picture ({status}: {reason}).")
    raise TelegramError(f"Telegram refused {method} ({status}{': ' + reason if reason else ''}).")


class FileTooLarge(TelegramError):
    """A file the owner sent is larger than the caller's cap; nothing more of it was read."""


def download(file_id: str, max_bytes: int, *, call=call) -> bytes:
    """One file the owner sent the bot, at most ``max_bytes`` (read to the cap + 1, then refused with ``FileTooLarge``);
    ``TelegramError`` when Telegram refuses or cannot be reached (never the token in the message)."""
    info = call("getFile", json={"file_id": file_id}) or {}
    path = str(info.get("file_path") or "") if isinstance(info, dict) else ""
    if not path:
        raise TelegramError("Telegram gave no file to download.")
    if int(info.get("file_size") or 0) > max_bytes:
        raise FileTooLarge("The file is too large.")
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    data = bytearray()
    try:
        with httpx.stream("GET", f"{API_URL}/file/bot{token}/{path}", timeout=TIMEOUT_SECONDS) as response:
            if response.status_code != 200:
                raise TelegramError(f"Telegram refused the file download ({response.status_code}).")
            for chunk in response.iter_bytes():
                data += chunk
                if len(data) > max_bytes:
                    raise FileTooLarge("The file is too large.")
    except httpx.HTTPError as exc:
        raise TelegramError(f"Telegram could not be reached ({type(exc).__name__}).") from exc
    return bytes(data)
