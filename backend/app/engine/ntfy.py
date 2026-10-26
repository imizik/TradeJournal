"""Phone notifications through ntfy, the topic the server's own health alerts use.

On the server systemd passes ``/etc/tradejournal/alerts.env`` to the API
(``NTFY_URL``, optional ``NTFY_TOKEN`` and ``ALERT_APP_URL``); without
``NTFY_URL`` nothing is sent and callers say so. The JSON form is used, as
``deploy/alerts.py`` does, because ntfy headers are limited to Latin-1.

``publish_image`` sends a ping with a picture (``engine/ping_images.py``): the PNG
is the PUT body, stored by ntfy as the notification's attachment, and the text
rides in headers, each RFC 2047 encoded so any UTF-8 survives. A server that
refuses the attachment (attachments off, too large) raises ``ImageRefused``,
which certainly sent nothing, so the caller sends the text alone.
"""

import base64
import json
import os
from urllib.parse import urlsplit

import httpx

TIMEOUT_SECONDS = 10


class NtfyError(Exception):
    pass


class ImageRefused(NtfyError):
    """ntfy answered the picture with a 4xx refusal: nothing was sent."""


def configured() -> bool:
    return bool(os.environ.get("NTFY_URL", "").strip())


def publish(title: str, message: str, *, priority: int = 4, tags: tuple[str, ...] = ("bell",), path: str = "", direct_click: bool = False,
            more: tuple[tuple[str, str], ...] = ()) -> str | None:
    """Send one notification; raises ``NtfyError`` when ntfy did not accept it.
    Tapping the notification opens it in ntfy, where the full text shows; ``path``
    is appended to ``ALERT_APP_URL`` for an "Open app" button on the notification.
    Position alerts opt into ``direct_click`` to open that same URL on tap, and ``more`` adds (label, path)
    buttons after it (ntfy shows at most three).
    Returns ntfy's message ID when its reply carries one: proof ntfy accepted it, not that a phone showed it."""
    url = os.environ.get("NTFY_URL", "").strip()
    if not url:
        raise NtfyError("Phone alerts are not set up on this server (NTFY_URL is not set).")
    target = urlsplit(url)
    body: dict = {"topic": target.path.strip("/"), "title": title, "message": message, "priority": priority, "tags": list(tags)}
    if app_url := os.environ.get("ALERT_APP_URL", "").strip():
        body["actions"] = [{"action": "view", "label": label, "url": app_url.rstrip("/") + link}
                           for label, link in (("Open app", path), *more)]
        if direct_click:
            body["click"] = app_url.rstrip("/") + path
    headers = {"Content-Type": "application/json"}
    if token := os.environ.get("NTFY_TOKEN", "").strip():
        headers["Authorization"] = f"Bearer {token}"
    response = _send("post", f"{target.scheme}://{target.netloc}/", json=body, headers=headers)
    if not 200 <= response.status_code < 300:
        raise NtfyError(f"ntfy refused the notification ({response.status_code}).")
    return _receipt(response)


def publish_image(title: str, message: str, image: bytes, *, priority: int = 4, tags: tuple[str, ...] = ("bell",), path: str = "",
                  direct_click: bool = False, more: tuple[tuple[str, str], ...] = ()) -> str | None:
    """``publish`` with ``image`` (PNG bytes) attached as ``chart.png``. Raises ``ImageRefused`` when ntfy refused
    the request with a 4xx (nothing was sent: the caller sends the text alone), else as ``publish`` does."""
    url = os.environ.get("NTFY_URL", "").strip()
    if not url:
        raise NtfyError("Phone alerts are not set up on this server (NTFY_URL is not set).")
    target = urlsplit(url)
    headers = {"Title": _encoded(title), "Message": _encoded(message), "Priority": str(priority), "Tags": ",".join(tags),
               "Filename": "chart.png", "Content-Type": "image/png"}
    if app_url := os.environ.get("ALERT_APP_URL", "").strip():
        actions = [{"action": "view", "label": label, "url": app_url.rstrip("/") + link} for label, link in (("Open app", path), *more)]
        headers["Actions"] = json.dumps(actions, ensure_ascii=True, separators=(",", ":"))
        if direct_click:
            headers["Click"] = app_url.rstrip("/") + path
    if token := os.environ.get("NTFY_TOKEN", "").strip():
        headers["Authorization"] = f"Bearer {token}"
    response = _send("put", f"{target.scheme}://{target.netloc}/{target.path.strip('/')}", content=image, headers=headers)
    if 400 <= response.status_code < 500:
        raise ImageRefused(f"ntfy refused the picture ({response.status_code}).")
    if not 200 <= response.status_code < 300:
        raise NtfyError(f"ntfy refused the notification ({response.status_code}).")
    return _receipt(response)


def _encoded(text: str) -> str:
    """An RFC 2047 encoded word: ASCII on the wire, decoded by ntfy back to the UTF-8 text, newlines included."""
    return "=?UTF-8?B?" + base64.b64encode(text.encode()).decode() + "?="


def _send(method: str, endpoint: str, **kwargs) -> httpx.Response:
    try:
        if os.environ.get("NTFY_IPV4_ONLY", "").strip().lower() == "true":
            # A fixed source family avoids shared IPv6 /64 quotas. Never
            # change addresses or retry via another family after a refusal.
            with httpx.Client(transport=httpx.HTTPTransport(local_address="0.0.0.0"), timeout=TIMEOUT_SECONDS) as client:
                return getattr(client, method)(endpoint, **kwargs)
        return getattr(httpx, method)(endpoint, timeout=TIMEOUT_SECONDS, **kwargs)
    except httpx.HTTPError as exc:
        raise NtfyError(f"ntfy could not be reached ({type(exc).__name__}).") from exc


def _receipt(response: httpx.Response) -> str | None:
    try:
        receipt = response.json().get("id")
    except (ValueError, AttributeError):
        return None
    return receipt if isinstance(receipt, str) and receipt else None
