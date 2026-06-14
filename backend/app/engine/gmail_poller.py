"""
Gmail poller: fetches Robinhood fill emails via the Gmail API.

Auth flow:
  - First run: opens a browser, you log in, saves token.json to backend/
  - Subsequent runs: uses token.json automatically

Entrypoint: poll_new_fills() -> list[ParsedFill]
"""

import base64
import json
import logging
import os
import secrets
import time
from pathlib import Path

from app.engine.email_parser import (
    EmailParseError,
    OPTION_PARTIAL_SUBJECT,
    OPTION_SUBJECT,
    ParsedFill,
    STOCK_SUBJECT,
    parse_option_email,
)

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
CREDENTIALS_FILE = _BACKEND_DIR / "credentials.json"
TOKEN_FILE = _BACKEND_DIR / "token.json"
OAUTH_STATE_FILE = _BACKEND_DIR / "data" / "gmail_oauth_states.json"
GMAIL_WATCH_STATE_FILE = _BACKEND_DIR / "data" / "gmail_watch_state.json"
BACKEND_PUBLIC_URL = os.getenv("BACKEND_PUBLIC_URL", "http://localhost:8000").rstrip("/")
GMAIL_OAUTH_CALLBACK_PATH = "/auth/gmail/callback"
DEFAULT_GMAIL_OAUTH_CALLBACK_URL = f"{BACKEND_PUBLIC_URL}{GMAIL_OAUTH_CALLBACK_PATH}"
OAUTH_STATE_TTL_SECONDS = 15 * 60


class GmailPollingError(RuntimeError):
    """Raised when Gmail polling cannot be started or completed safely."""


class GmailAuthRequired(GmailPollingError):
    """Raised when Gmail needs an interactive OAuth login."""


def _save_gmail_watch_state(state: dict[str, object]) -> None:
    GMAIL_WATCH_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    GMAIL_WATCH_STATE_FILE.write_text(json.dumps(state, indent=2))


def gmail_watch_state() -> dict[str, object] | None:
    if not GMAIL_WATCH_STATE_FILE.exists():
        return None
    try:
        raw = json.loads(GMAIL_WATCH_STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _is_invalid_grant_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "invalid_grant" in text or "token has been expired or revoked" in text


def _build_oauth_flow(installed_app_flow, redirect_uri: str):
    if not CREDENTIALS_FILE.exists():
        raise GmailPollingError(f"Missing Gmail credentials file: {CREDENTIALS_FILE}")
    flow = installed_app_flow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    flow.redirect_uri = redirect_uri
    return flow


def _load_oauth_states() -> dict[str, dict[str, object]]:
    if not OAUTH_STATE_FILE.exists():
        return {}
    try:
        raw = json.loads(OAUTH_STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}

    now = time.time()
    states: dict[str, dict[str, object]] = {}
    for state, value in raw.items():
        if not isinstance(state, str) or not isinstance(value, dict):
            continue
        redirect_uri = value.get("redirect_uri")
        code_verifier = value.get("code_verifier")
        created_at = value.get("created_at")
        if not isinstance(redirect_uri, str) or not isinstance(created_at, (int, float)):
            continue
        if now - float(created_at) <= OAUTH_STATE_TTL_SECONDS:
            state_data: dict[str, object] = {"redirect_uri": redirect_uri, "created_at": float(created_at)}
            if isinstance(code_verifier, str):
                state_data["code_verifier"] = code_verifier
            states[state] = state_data
    return states


def _save_oauth_states(states: dict[str, dict[str, object]]) -> None:
    OAUTH_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    OAUTH_STATE_FILE.write_text(json.dumps(states))


def begin_gmail_oauth(callback_base_url: str | None = None) -> str:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise GmailPollingError(
            "Gmail import dependencies are not installed. Install the Google API packages for the backend before syncing emails."
        ) from exc

    if callback_base_url:
        redirect_uri = f"{callback_base_url.rstrip('/')}{GMAIL_OAUTH_CALLBACK_PATH}"
    else:
        redirect_uri = DEFAULT_GMAIL_OAUTH_CALLBACK_URL

    flow = _build_oauth_flow(InstalledAppFlow, redirect_uri)
    state = secrets.token_urlsafe(24)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )

    state_data: dict[str, object] = {"redirect_uri": redirect_uri, "created_at": time.time()}
    code_verifier = getattr(flow, "code_verifier", None)
    if isinstance(code_verifier, str):
        state_data["code_verifier"] = code_verifier
    states = _load_oauth_states()
    states[state] = state_data
    _save_oauth_states(states)
    return auth_url


def finish_gmail_oauth(code: str, state: str) -> None:
    states = _load_oauth_states()
    state_data = states.pop(state, None)
    _save_oauth_states(states)
    redirect_uri = state_data.get("redirect_uri") if state_data else None
    if not redirect_uri:
        raise GmailPollingError("Invalid Gmail OAuth state. Start Gmail authorization again.")

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise GmailPollingError(
            "Gmail import dependencies are not installed. Install the Google API packages for the backend before syncing emails."
        ) from exc

    flow = _build_oauth_flow(InstalledAppFlow, redirect_uri)
    code_verifier = state_data.get("code_verifier") if state_data else None
    if isinstance(code_verifier, str):
        flow.code_verifier = code_verifier
    try:
        flow.fetch_token(code=code)
    except Exception as exc:
        log.warning("Unable to finish Gmail authorization", exc_info=exc)
        raise GmailPollingError(f"Unable to finish Gmail authorization: {exc}") from exc
    TOKEN_FILE.write_text(flow.credentials.to_json())
    log.info("Saved Gmail OAuth token")


def _get_service():
    log.info("Initializing Gmail API client")
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise GmailPollingError(
            "Gmail import dependencies are not installed. Install the Google API packages for the backend before syncing emails."
        ) from exc

    creds = None

    try:
        if TOKEN_FILE.exists():
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    log.info("Refreshing Gmail OAuth token")
                    creds.refresh(Request())
                except Exception as exc:
                    if not _is_invalid_grant_error(exc):
                        raise
                    log.warning("Gmail token expired or revoked; Gmail authorization is required")
                    raise GmailAuthRequired("Gmail authorization is required. Connect Gmail from the app, then retry sync.") from exc
            else:
                raise GmailAuthRequired("Gmail authorization is required. Connect Gmail from the app, then retry sync.")

            TOKEN_FILE.write_text(creds.to_json())

        log.info("Gmail API client ready")
        return build("gmail", "v1", credentials=creds)
    except GmailPollingError:
        raise
    except Exception as exc:
        raise GmailPollingError(f"Unable to initialize the Gmail client: {exc}") from exc


def _message_body(msg: dict) -> str:
    """Extract plain-text body from a Gmail message dict, falling back to stripped HTML."""
    payload = msg.get("payload", {})
    text = _extract_part(payload, "text/plain") or _extract_part(payload, "text/html")
    if not text:
        return ""
    if "<" in text and ">" in text:
        text = _strip_html(text)
    return text


def _extract_part(payload: dict, mime_type: str) -> str:
    """Recursively search payload parts for a given MIME type."""
    if payload.get("mimeType") == mime_type:
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        result = _extract_part(part, mime_type)
        if result:
            return result
    return ""


def _strip_html(html: str) -> str:
    """Strip HTML tags and normalize whitespace, fixing split decimal numbers."""
    import re

    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;", " ", text)
    # Older Robinhood emails split prices across elements: "$650\n00" -> "$650.00"
    text = re.sub(r"(\$[\d,]+)\s+(\d{2})(?=\s)", r"\1.\2", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _fetch_all_message_ids(service, query: str) -> list[str]:
    """Fetch all message IDs matching a query, handling pagination."""
    ids = []
    page_token = None
    while True:
        kwargs = {"userId": "me", "q": query, "maxResults": 500}
        if page_token:
            kwargs["pageToken"] = page_token
        result = service.users().messages().list(**kwargs).execute()
        ids.extend(message["id"] for message in result.get("messages", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return ids


def register_gmail_watch(
    *,
    topic_name: str | None = None,
    label_ids: list[str] | None = None,
) -> dict[str, object]:
    """
    Register/renew Gmail push notifications via Google Pub/Sub.

    Gmail sends only mailbox-change metadata to Pub/Sub. The webhook should
    still call the existing importer so fill parsing and dedupe stay in one
    place.
    """
    service = _get_service()
    topic = (topic_name or os.getenv("GMAIL_PUBSUB_TOPIC") or "").strip()
    if not topic:
        raise GmailPollingError("GMAIL_PUBSUB_TOPIC is required to register a Gmail watch.")

    if label_ids is None:
        raw_labels = os.getenv("GMAIL_WATCH_LABEL_IDS", "INBOX")
        label_ids = [value.strip() for value in raw_labels.split(",") if value.strip()]

    body: dict[str, object] = {"topicName": topic}
    if label_ids:
        body["labelIds"] = label_ids
        body["labelFilterBehavior"] = "INCLUDE"

    try:
        result = service.users().watch(userId="me", body=body).execute()
    except Exception as exc:
        raise GmailPollingError(f"Unable to register Gmail watch: {exc}") from exc

    state = {
        "topic_name": topic,
        "label_ids": label_ids,
        "history_id": result.get("historyId"),
        "expiration": result.get("expiration"),
        "registered_at": int(time.time()),
    }
    _save_gmail_watch_state(state)
    return state


def poll_new_fills(
    known_ids: set[str] | None = None,
    since_date: str | None = None,
) -> list[ParsedFill]:
    """
    Fetch new Robinhood fill emails from Gmail.

    known_ids: full set of raw_email_ids already in the DB.
    since_date: Gmail date string like "2025/06/01" to bound the search window.

    Returns a list of ParsedFill objects, oldest first.
    """
    import time as _time

    if known_ids is None:
        known_ids = set()

    log.info("poll_new_fills start: known_ids=%d since_date=%s", len(known_ids), since_date)
    service = _get_service()

    date_filter = f" after:{since_date}" if since_date else " after:2024/01/01"
    opt_query = f'subject:"{OPTION_SUBJECT}" from:noreply@robinhood.com{date_filter}'
    opt_partial_query = f'subject:"{OPTION_PARTIAL_SUBJECT}" from:noreply@robinhood.com{date_filter}'
    stk_query = f'subject:"{STOCK_SUBJECT}" from:noreply@robinhood.com{date_filter}'

    t_list = _time.monotonic()
    try:
        log.info("Listing candidate option and stock emails from Gmail")
        opt_ids = _fetch_all_message_ids(service, opt_query)
        opt_partial_ids = _fetch_all_message_ids(service, opt_partial_query)
        stk_ids = _fetch_all_message_ids(service, stk_query)
    except Exception as exc:
        raise GmailPollingError(f"Unable to list Gmail messages: {exc}") from exc

    # Each query returns newest-first, but the combined list is not globally
    # ordered across both subjects.
    all_ids = list(dict.fromkeys(opt_ids + opt_partial_ids + stk_ids))
    log.info("Gmail list: %d candidate IDs in %.1fs", len(all_ids), _time.monotonic() - t_list)

    if not all_ids:
        return []

    parsed: list[ParsedFill] = []
    t_fetch = _time.monotonic()
    fetched = 0

    # Skip known IDs rather than breaking on the first one. Once the stock and
    # option result sets are merged, a known option email does not guarantee
    # there are no newer unseen stock emails later in the combined list.
    for msg_id in all_ids:
        if msg_id in known_ids:
            log.info("Skipping known email %s", msg_id)
            continue

        try:
            msg = service.users().messages().get(
                userId="me", id=msg_id, format="full"
            ).execute()
            fetched += 1

            headers = {header["name"]: header["value"] for header in msg["payload"].get("headers", [])}
            subject = headers.get("Subject", "")
            body = _message_body(msg)

            fill = parse_option_email(subject, body, imap_uid=msg_id)
            if fill:
                parsed.append(fill)

        except EmailParseError as exc:
            log.warning("Failed to parse email %s: %s", msg_id, exc)
        except Exception as exc:
            log.warning("Unexpected error processing email %s: %s", msg_id, exc)

    log.info(
        "Fetched %d emails, parsed %d fills in %.1fs",
        fetched,
        len(parsed),
        _time.monotonic() - t_fetch,
    )
    log.info("poll_new_fills complete")

    # Return oldest-first so the reconstructor processes fills in chronological order.
    return list(reversed(parsed))
