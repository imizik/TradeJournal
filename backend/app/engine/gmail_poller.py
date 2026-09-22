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
GMAIL_SKIPPED_MESSAGE_IDS_FILE = _BACKEND_DIR / "data" / "gmail_skipped_message_ids.json"
GMAIL_HISTORY_CURSOR_FILE = _BACKEND_DIR / "data" / "gmail_history_cursor.json"
GMAIL_AUTH_STATE_FILE = _BACKEND_DIR / "data" / "gmail_auth_state.json"
ROBINHOOD_SENDER = "noreply@robinhood.com"
FILL_SUBJECTS = frozenset({OPTION_SUBJECT, OPTION_PARTIAL_SUBJECT, STOCK_SUBJECT})
BACKEND_PUBLIC_URL = os.getenv("BACKEND_PUBLIC_URL", "http://localhost:8000").rstrip("/")
GMAIL_OAUTH_CALLBACK_PATH = "/auth/gmail/callback"
DEFAULT_GMAIL_OAUTH_CALLBACK_URL = f"{BACKEND_PUBLIC_URL}{GMAIL_OAUTH_CALLBACK_PATH}"
OAUTH_STATE_TTL_SECONDS = 15 * 60


class GmailPollingError(RuntimeError):
    """Raised when Gmail polling cannot be started or completed safely."""


class GmailAuthRequired(GmailPollingError):
    """Raised when Gmail needs an interactive OAuth login."""


class GmailHistoryExpired(GmailPollingError):
    """Raised when Gmail no longer retains history from the stored cursor."""


def write_private_file(path: Path, text: str) -> None:
    """Replace a file atomically, readable only by the service account.

    On the VPS the token and data files are symlinks from a read-only release
    into /var/lib/tradejournal. Replacing the resolved target keeps the link;
    replacing the link itself would fail, or detach the file from its state.
    Readers in other processes never observe a partial write.
    """
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp")
    try:
        temp_path.write_text(text)
        temp_path.chmod(0o600)
        temp_path.replace(target)
    finally:
        temp_path.unlink(missing_ok=True)


def _read_json_object(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def gmail_auth_state() -> dict[str, object] | None:
    return _read_json_object(GMAIL_AUTH_STATE_FILE)


def _record_gmail_auth(status: str, error: str | None = None) -> None:
    """Remember whether Gmail needs reconnecting; written only on change."""
    current = gmail_auth_state() or {}
    if current.get("status") == status:
        return
    try:
        write_private_file(
            GMAIL_AUTH_STATE_FILE,
            json.dumps({"status": status, "since": int(time.time()), "error": error}, indent=2),
        )
    except OSError as exc:
        log.warning("Could not persist Gmail authorization state: %s", exc)


def load_history_cursor() -> str | None:
    state = _read_json_object(GMAIL_HISTORY_CURSOR_FILE) or {}
    value = state.get("history_id")
    return str(value) if value else None


def save_history_cursor(history_id: str) -> None:
    write_private_file(
        GMAIL_HISTORY_CURSOR_FILE,
        json.dumps({"history_id": str(history_id), "updated_at": int(time.time())}, indent=2),
    )


def _save_gmail_watch_state(state: dict[str, object]) -> None:
    write_private_file(GMAIL_WATCH_STATE_FILE, json.dumps(state, indent=2))


def gmail_watch_state() -> dict[str, object] | None:
    if not GMAIL_WATCH_STATE_FILE.exists():
        return None
    try:
        raw = json.loads(GMAIL_WATCH_STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _load_skipped_message_ids() -> set[str]:
    """Load Gmail ids that were fetched and intentionally produced no fill."""
    if not GMAIL_SKIPPED_MESSAGE_IDS_FILE.exists():
        return set()
    try:
        raw = json.loads(GMAIL_SKIPPED_MESSAGE_IDS_FILE.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Could not read skipped Gmail message ids: %s", exc)
        return set()

    ids = raw.get("ids") if isinstance(raw, dict) and raw.get("version") == 1 else None
    if not isinstance(ids, list) or any(not isinstance(value, str) for value in ids):
        log.warning("Ignoring malformed skipped Gmail message id state")
        return set()
    return set(ids)


def _save_skipped_message_ids(message_ids: set[str]) -> None:
    """Atomically persist skipped ids without involving Fill.raw_email_id."""
    GMAIL_SKIPPED_MESSAGE_IDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_path = GMAIL_SKIPPED_MESSAGE_IDS_FILE.with_name(
        f".{GMAIL_SKIPPED_MESSAGE_IDS_FILE.name}.{secrets.token_hex(8)}.tmp"
    )
    try:
        temp_path.write_text(json.dumps({"version": 1, "ids": sorted(message_ids)}, indent=2))
        temp_path.replace(GMAIL_SKIPPED_MESSAGE_IDS_FILE)
    finally:
        temp_path.unlink(missing_ok=True)


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
    write_private_file(TOKEN_FILE, flow.credentials.to_json())
    _record_gmail_auth("ok")
    log.info("Saved Gmail OAuth token")


def _get_service():
    try:
        service = _build_service()
    except GmailAuthRequired as exc:
        _record_gmail_auth("needs_reconnect", str(exc))
        raise
    _record_gmail_auth("ok")
    return service


def _build_service():
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

            write_private_file(TOKEN_FILE, creds.to_json())

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


def _configured_watch_labels() -> list[str]:
    raw = os.getenv("GMAIL_WATCH_LABELS") or os.getenv("GMAIL_WATCH_LABEL_IDS") or "INBOX"
    return [value.strip() for value in raw.split(",") if value.strip()]


def _resolve_label_ids(service, labels: list[str]) -> list[str]:
    """Accept Gmail label names (e.g. "TradeJournal/Fills") as well as ids."""
    try:
        listed = service.users().labels().list(userId="me").execute().get("labels", [])
    except Exception as exc:
        raise GmailPollingError(f"Unable to list Gmail labels: {exc}") from exc
    by_id = {label.get("id"): label.get("id") for label in listed}
    by_name = {str(label.get("name", "")).casefold(): label.get("id") for label in listed}
    resolved = []
    for label in labels:
        label_id = by_id.get(label) or by_name.get(label.casefold())
        if not label_id:
            raise GmailPollingError(
                f"Gmail label {label!r} does not exist. Create the Gmail filter and label first."
            )
        resolved.append(label_id)
    return resolved


def register_gmail_watch(
    *,
    topic_name: str | None = None,
    label_ids: list[str] | None = None,
) -> dict[str, object]:
    """
    Register/renew Gmail push notifications via Google Pub/Sub.

    Gmail sends only mailbox-change metadata to Pub/Sub. The listener still
    runs the existing importer so fill parsing and dedupe stay in one place.
    Renewal never moves the import cursor; it only seeds a missing one.
    """
    service = _get_service()
    topic = (topic_name or os.getenv("GMAIL_PUBSUB_TOPIC") or "").strip()
    if not topic:
        raise GmailPollingError("GMAIL_PUBSUB_TOPIC is required to register a Gmail watch.")

    if label_ids is None:
        label_ids = _resolve_label_ids(service, _configured_watch_labels())

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
    if result.get("historyId") and load_history_cursor() is None:
        save_history_cursor(str(result["historyId"]))
    return state


def watch_label_id() -> str | None:
    """The single watched label, used to narrow history reads."""
    labels = (gmail_watch_state() or {}).get("label_ids")
    if isinstance(labels, list) and len(labels) == 1 and isinstance(labels[0], str):
        return labels[0]
    return None


def mailbox_history_id(service) -> str:
    try:
        return str(service.users().getProfile(userId="me").execute()["historyId"])
    except Exception as exc:
        raise GmailPollingError(f"Unable to read the Gmail mailbox history id: {exc}") from exc


def _is_not_found(exc: Exception) -> bool:
    return getattr(getattr(exc, "resp", None), "status", None) == 404


def history_message_ids(service, start_history_id: str, label_id: str | None) -> tuple[list[str], str]:
    """Message ids added (or labelled) since start_history_id, oldest first.

    Returns the ids and the mailbox history id to store once they are imported.
    """
    ids: list[str] = []
    latest = str(start_history_id)
    page_token = None
    while True:
        kwargs: dict[str, object] = {
            "userId": "me",
            "startHistoryId": start_history_id,
            "historyTypes": ["messageAdded", "labelAdded"],
            "maxResults": 500,
        }
        if label_id:
            kwargs["labelId"] = label_id
        if page_token:
            kwargs["pageToken"] = page_token
        try:
            result = service.users().history().list(**kwargs).execute()
        except Exception as exc:
            if _is_not_found(exc):
                raise GmailHistoryExpired(f"Gmail history from {start_history_id} is no longer available") from exc
            raise GmailPollingError(f"Unable to read Gmail history: {exc}") from exc
        for record in result.get("history", []):
            for added in record.get("messagesAdded", []):
                ids.append(added["message"]["id"])
            for labelled in record.get("labelsAdded", []):
                if label_id is None or label_id in labelled.get("labelIds", []):
                    ids.append(labelled["message"]["id"])
        latest = str(result.get("historyId") or latest)
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return list(dict.fromkeys(ids)), latest


def pending_history_message_ids() -> tuple[list[str] | None, str]:
    """What arrived since the stored cursor, and the cursor to store afterwards.

    Returns (None, current) when there is no usable cursor; the caller then
    runs the search import. The current id is read before that search, so a
    message arriving during it is replayed next time and deduplicated.
    """
    service = _get_service()
    cursor = load_history_cursor()
    if cursor:
        try:
            return history_message_ids(service, cursor, watch_label_id())
        except GmailHistoryExpired:
            log.warning("Gmail history cursor %s expired; falling back to a search import", cursor)
    return None, mailbox_history_id(service)


def _fetch_and_parse(
    service, message_ids: list[str], known_ids: set[str], skipped_ids: set[str], *, strict: bool = False
) -> list[ParsedFill]:
    """Fetch, parse and remember skipped emails, preserving input order.

    strict (history imports): a fetch error aborts the batch so the history
    cursor is not advanced past a message that was never read. A message that
    fails to *parse* is still logged and skipped either way; retrying it would
    fail the same way.
    """
    import time as _time

    parsed: list[ParsedFill] = []
    newly_skipped_ids: set[str] = set()
    t_fetch = _time.monotonic()
    fetched = 0

    # Skip known IDs rather than breaking on the first one. Once the stock and
    # option result sets are merged, a known option email does not guarantee
    # there are no newer unseen stock emails later in the combined list.
    for msg_id in message_ids:
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
            elif subject.strip() == OPTION_PARTIAL_SUBJECT:
                # Partial option emails report cumulative quantities and must
                # never become fills. Remember the fetched id outside the fill
                # table so later polls skip the full-message API call.
                newly_skipped_ids.add(msg_id)

        except EmailParseError as exc:
            log.warning("Failed to parse email %s: %s", msg_id, exc)
        except Exception as exc:
            if strict:
                raise GmailPollingError(f"Unable to read Gmail message {msg_id}: {exc}") from exc
            log.warning("Unexpected error processing email %s: %s", msg_id, exc)

    if newly_skipped_ids:
        try:
            _save_skipped_message_ids(skipped_ids | newly_skipped_ids)
        except OSError as exc:
            # Losing this cache only costs future Gmail API calls. It must not
            # block otherwise-valid fills from being imported.
            log.warning("Could not persist skipped Gmail message ids: %s", exc)

    log.info(
        "Fetched %d emails, parsed %d fills in %.1fs",
        fetched,
        len(parsed),
        _time.monotonic() - t_fetch,
    )
    return parsed


def poll_new_fills(
    known_ids: set[str] | None = None,
    since_date: str | None = None,
) -> list[ParsedFill]:
    """
    Fetch new Robinhood fill emails from Gmail.

    known_ids: full set of raw_email_ids already in the DB. Persisted ids for
        fetched messages that are intentionally skipped are merged in here.
    since_date: Gmail date string like "2025/06/01" to bound the search window.

    Returns a list of ParsedFill objects, oldest first.
    """
    import time as _time

    if known_ids is None:
        known_ids = set()
    else:
        known_ids = set(known_ids)

    skipped_ids = _load_skipped_message_ids()
    known_ids.update(skipped_ids)

    log.info(
        "poll_new_fills start: known_ids=%d skipped_ids=%d since_date=%s",
        len(known_ids),
        len(skipped_ids),
        since_date,
    )
    service = _get_service()

    date_filter = f" after:{since_date}" if since_date else " after:2024/01/01"
    opt_query = f'subject:"{OPTION_SUBJECT}" from:{ROBINHOOD_SENDER}{date_filter}'
    opt_partial_query = f'subject:"{OPTION_PARTIAL_SUBJECT}" from:{ROBINHOOD_SENDER}{date_filter}'
    stk_query = f'subject:"{STOCK_SUBJECT}" from:{ROBINHOOD_SENDER}{date_filter}'

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

    parsed = _fetch_and_parse(service, all_ids, known_ids, skipped_ids)
    log.info("poll_new_fills complete")

    # Return oldest-first so the reconstructor processes fills in chronological order.
    return list(reversed(parsed))


def _is_fill_email(headers: dict[str, str]) -> bool:
    return ROBINHOOD_SENDER in headers.get("From", "").lower() and headers.get("Subject", "").strip() in FILL_SUBJECTS


def poll_fills_by_ids(message_ids: list[str], known_ids: set[str] | None = None) -> list[ParsedFill]:
    """Import specific messages (from Gmail history), oldest first.

    Only the From/Subject headers of other mail are read: a message that is
    not a Robinhood execution email is never downloaded in full.
    """
    skipped_ids = _load_skipped_message_ids()
    known_ids = set(known_ids or ()) | skipped_ids
    candidates = [msg_id for msg_id in message_ids if msg_id not in known_ids]
    if not candidates:
        return []
    service = _get_service()
    fill_ids = []
    for msg_id in candidates:
        try:
            msg = service.users().messages().get(
                userId="me", id=msg_id, format="metadata", metadataHeaders=["From", "Subject"]
            ).execute()
        except Exception as exc:
            if _is_not_found(exc):
                continue  # deleted before we read it
            raise GmailPollingError(f"Unable to read Gmail message {msg_id}: {exc}") from exc
        headers = {header["name"]: header["value"] for header in msg.get("payload", {}).get("headers", [])}
        if _is_fill_email(headers):
            fill_ids.append(msg_id)
    log.info("Gmail history: %d new message(s), %d Robinhood execution email(s)", len(candidates), len(fill_ids))
    return _fetch_and_parse(service, fill_ids, known_ids, skipped_ids, strict=True) if fill_ids else []
