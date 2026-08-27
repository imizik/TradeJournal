from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.engine.email_parser import ParsedFill
from app.engine.gmail_poller import poll_new_fills

ET = ZoneInfo("America/New_York")


class _FakeMessagesApi:
    def __init__(self, payloads: dict[str, dict], fetched_ids: list[str] | None = None):
        self.payloads = payloads
        self.fetched_ids = fetched_ids

    def get(self, userId: str, id: str, format: str):
        assert userId == "me"
        assert format == "full"
        if self.fetched_ids is not None:
            self.fetched_ids.append(id)
        return SimpleNamespace(execute=lambda: self.payloads[id])


class _FakeUsersApi:
    def __init__(self, payloads: dict[str, dict], fetched_ids: list[str] | None = None):
        self.payloads = payloads
        self.fetched_ids = fetched_ids

    def messages(self):
        return _FakeMessagesApi(self.payloads, self.fetched_ids)


class _FakeService:
    def __init__(self, payloads: dict[str, dict], fetched_ids: list[str] | None = None):
        self.payloads = payloads
        self.fetched_ids = fetched_ids

    def users(self):
        return _FakeUsersApi(self.payloads, self.fetched_ids)


def test_poll_new_fills_does_not_stop_after_known_option_email(monkeypatch) -> None:
    payloads = {
        "stock-new": {
            "payload": {
                "headers": [{"name": "Subject", "value": "Your order has been executed"}],
                "body": {},
            }
        }
    }

    monkeypatch.setattr("app.engine.gmail_poller._get_service", lambda: _FakeService(payloads))

    def _fake_fetch(_service, query: str) -> list[str]:
        # The poller issues three subject queries. Partial-fill option emails
        # are still listed here but are dropped later by parse_option_email.
        if 'subject:"Option order partially executed"' in query:
            return ["option-partial-known"]
        if 'subject:"Option order executed"' in query:
            return ["option-known"]
        if 'subject:"Your order has been executed"' in query:
            return ["stock-new"]
        raise AssertionError(f"unexpected query: {query}")

    monkeypatch.setattr("app.engine.gmail_poller._fetch_all_message_ids", _fake_fetch)
    monkeypatch.setattr("app.engine.gmail_poller._message_body", lambda _msg: "body")

    parsed_fill = ParsedFill(
        ticker="AFRM",
        side="sell",
        contracts=Decimal("4"),
        price=Decimal("58.52"),
        executed_at=datetime(2026, 4, 15, 9, 46, tzinfo=ET),
        instrument_type="stock",
        raw_email_id="stock-new",
        account_last4="8267",
        account_type="roth_ira",
    )

    monkeypatch.setattr(
        "app.engine.gmail_poller.parse_option_email",
        lambda subject, body, imap_uid: parsed_fill if imap_uid == "stock-new" else None,
    )

    result = poll_new_fills(known_ids={"option-known", "option-partial-known"})

    assert [fill.raw_email_id for fill in result] == ["stock-new"]


def test_poll_new_fills_queries_partial_option_subject(monkeypatch) -> None:
    monkeypatch.setattr("app.engine.gmail_poller._get_service", lambda: _FakeService({}))

    seen_queries: list[str] = []

    def _fake_fetch(_service, query: str) -> list[str]:
        seen_queries.append(query)
        return []

    monkeypatch.setattr("app.engine.gmail_poller._fetch_all_message_ids", _fake_fetch)

    result = poll_new_fills(known_ids=set())

    assert result == []
    assert any('subject:"Option order partially executed"' in query for query in seen_queries)


def test_partial_option_email_is_not_refetched_on_second_poll(monkeypatch, tmp_path) -> None:
    skipped_path = tmp_path / "gmail_skipped_message_ids.json"
    monkeypatch.setattr(
        "app.engine.gmail_poller.GMAIL_SKIPPED_MESSAGE_IDS_FILE",
        skipped_path,
    )

    partial_id = "option-partial"
    payloads = {
        partial_id: {
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Option order partially executed"}
                ],
                "body": {},
            }
        }
    }
    fetched_ids: list[str] = []
    monkeypatch.setattr(
        "app.engine.gmail_poller._get_service",
        lambda: _FakeService(payloads, fetched_ids),
    )

    def _fake_fetch(_service, query: str) -> list[str]:
        if 'subject:"Option order partially executed"' in query:
            return [partial_id]
        return []

    monkeypatch.setattr("app.engine.gmail_poller._fetch_all_message_ids", _fake_fetch)
    monkeypatch.setattr("app.engine.gmail_poller._message_body", lambda _msg: "body")

    assert poll_new_fills(known_ids=set()) == []
    assert fetched_ids == [partial_id]
    assert skipped_path.exists()

    assert poll_new_fills(known_ids=set()) == []
    assert fetched_ids == [partial_id]
