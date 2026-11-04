"""The one way the app's own trading pings reach the phone: Telegram when it is set up, else ntfy.

Every trading sender asks ``notification_policy.decide`` first, then calls ``send``. With ``TELEGRAM_BOT_TOKEN`` and
``TELEGRAM_CHAT_ID`` set the ping goes to the Telegram bot (``engine/telegram.py``), with its reply ``buttons``
(label, callback data from ``engine/telegram_replies.py``) under the text; otherwise it goes to ntfy exactly as the
senders sent it before, with ``ntfy_options`` (``tags``, ``direct_click``, ``more``) passed through unchanged (ntfy
cannot carry reply buttons, so those are left off). Server health, deploy and watchdog pings (``deploy/alerts.py``)
stay on ntfy and never come here.

``send`` returns ``(receipt, image state)`` as ``ping_images.publish`` does, and raises ``SendError`` (ntfy's error,
which Telegram's extends) with the same at-most-once meaning on either transport. On Telegram ``more`` becomes extra
link buttons beside Open, unless the ping has reply ``buttons``: then ``more`` holds ntfy's answer links for the same
answers, and the buttons replace them. A picture whose text is too long for a photo caption goes as text alone.

On Telegram every factual ping also gets a Why? button (``ask:<kind>``): a tap asks copilot about that ping's own text
(``telegram_replies``). The AI-written summaries and the companion, which answer or ask for themselves, do not, and a
ping that already has its own Why? (an open-trade alert's ``why:``) keeps just that one.
"""

import logging

from app.engine import ntfy, ping_images, telegram

log = logging.getLogger(__name__)

SendError = ntfy.NtfyError
NO_WHY = frozenset({"prep", "week_review", "day_replay", "evening_review", "companion_adopt", "companion_update"})


def with_why(kind: str, buttons: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
    """``buttons`` plus a Why? for ``kind``, unless it is an AI summary or already has one."""
    if kind in NO_WHY or any(data.startswith(("why:", "ask:")) for _, data in buttons):
        return tuple(buttons)
    return (*buttons, ("Why?", f"ask:{kind}"[:64]))


def configured() -> bool:
    return telegram.configured() or ntfy.configured()


def transport() -> str | None:
    return "telegram" if telegram.configured() else "ntfy" if ntfy.configured() else None


def send(title: str, message: str, *, kind: str, path: str = "", buttons: tuple[tuple[str, str], ...] = (), image: bytes | None = None,
         priority: int | None = None, reply_to: str | None = None, open_label: str = "Open", **ntfy_options) -> tuple[str | None, str]:
    """Send one ping of ``kind`` (the policy's kind, for the log); see the module docstring. ``reply_to`` (a Telegram
    message id) and ``open_label`` are Telegram's only: ntfy has no threads, and its Open is its own."""
    if telegram.configured():
        # The ping's own answer buttons replace its answer links; the added Why? does not.
        options = {"path": path, "buttons": with_why(kind, tuple(buttons)), "priority": 4 if priority is None else priority,
                   "links": () if buttons else tuple(ntfy_options.get("more", ())), "reply_to": reply_to, "open_label": open_label}
        if image is not None and telegram.caption_fits(title, message):
            try:
                return telegram.publish(title, message, image=image, **options), "attached"
            except telegram.ImageRefused as exc:
                log.warning("%s ping: %s; sending the text alone", kind, exc)
        return telegram.publish(title, message, **options), "none" if ping_images.enabled() else "off"
    if priority is not None:
        ntfy_options["priority"] = priority
    return ping_images.publish(title, message, image, path=path, **ntfy_options)
