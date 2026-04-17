"""
Gmail poller: fetches Robinhood fill emails via the Gmail API.

Auth flow:
  - First run: opens a browser, you log in, saves token.json to backend/
  - Subsequent runs: uses token.json automatically

Entrypoint: poll_new_fills() -> list[ParsedFill]
"""

import base64
import logging
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


class GmailPollingError(RuntimeError):
    """Raised when Gmail polling cannot be started or completed safely."""


def _is_invalid_grant_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "invalid_grant" in text or "token has been expired or revoked" in text


def _run_oauth_flow(installed_app_flow):
    if not CREDENTIALS_FILE.exists():
        raise GmailPollingError(f"Missing Gmail credentials file: {CREDENTIALS_FILE}")
    flow = installed_app_flow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    return flow.run_local_server(port=0)


def _get_service():
    log.info("Initializing Gmail API client")
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
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
                    log.warning("Gmail token expired or revoked; starting a fresh OAuth login")
                    creds = _run_oauth_flow(InstalledAppFlow)
            else:
                creds = _run_oauth_flow(InstalledAppFlow)

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
