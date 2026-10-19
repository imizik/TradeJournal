"""Phone notifications through ntfy, the topic the server's own health alerts use.

On the server systemd passes ``/etc/tradejournal/alerts.env`` to the API
(``NTFY_URL``, optional ``NTFY_TOKEN`` and ``ALERT_APP_URL``); without
``NTFY_URL`` nothing is sent and callers say so. The JSON form is used, as
``deploy/alerts.py`` does, because ntfy headers are limited to Latin-1.
"""

import os
from urllib.parse import urlsplit

import httpx

TIMEOUT_SECONDS = 10


class NtfyError(Exception):
    pass


def configured() -> bool:
    return bool(os.environ.get("NTFY_URL", "").strip())


def publish(title: str, message: str, *, priority: int = 4, tags: tuple[str, ...] = ("bell",), path: str = "") -> str | None:
    """Send one notification; raises ``NtfyError`` when ntfy did not accept it.
    Tapping the notification opens it in ntfy, where the full text shows; ``path``
    is appended to ``ALERT_APP_URL`` for an "Open app" button on the notification.
    Returns ntfy's message ID when its reply carries one: proof ntfy accepted it, not that a phone showed it."""
    url = os.environ.get("NTFY_URL", "").strip()
    if not url:
        raise NtfyError("Phone alerts are not set up on this server (NTFY_URL is not set).")
    target = urlsplit(url)
    body: dict = {"topic": target.path.strip("/"), "title": title, "message": message, "priority": priority, "tags": list(tags)}
    if app_url := os.environ.get("ALERT_APP_URL", "").strip():
        body["actions"] = [{"action": "view", "label": "Open app", "url": app_url.rstrip("/") + path}]
    headers = {"Content-Type": "application/json"}
    if token := os.environ.get("NTFY_TOKEN", "").strip():
        headers["Authorization"] = f"Bearer {token}"
    try:
        endpoint = f"{target.scheme}://{target.netloc}/"
        if os.environ.get("NTFY_IPV4_ONLY", "").strip().lower() == "true":
            # A fixed source family avoids shared IPv6 /64 quotas. Never
            # change addresses or retry via another family after a refusal.
            with httpx.Client(transport=httpx.HTTPTransport(local_address="0.0.0.0"), timeout=TIMEOUT_SECONDS) as client:
                response = client.post(endpoint, json=body, headers=headers)
        else:
            response = httpx.post(endpoint, json=body, headers=headers, timeout=TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        raise NtfyError(f"ntfy could not be reached ({type(exc).__name__}).") from exc
    if not 200 <= response.status_code < 300:
        raise NtfyError(f"ntfy refused the notification ({response.status_code}).")
    try:
        receipt = response.json().get("id")
    except (ValueError, AttributeError):
        return None
    return receipt if isinstance(receipt, str) and receipt else None
