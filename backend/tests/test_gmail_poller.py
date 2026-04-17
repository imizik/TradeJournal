from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.engine.email_parser import ParsedFill
from app.engine.gmail_poller import poll_new_fills

ET = ZoneInfo("America/New_York")


class _FakeMessagesApi:
    def __init__(self, payloads: dict[str, dict]):
        self.payloads = payloads

    def get(self, userId: str, id: str, format: str):
        assert userId == "me"
        assert format == "full"
        return SimpleNamespace(execute=lambda: self.payloads[id])


class _FakeUsersApi:
    def __init__(self, payloads: dict[str, dict]):
        self.payloads = payloads

    def messages(self):
        return _FakeMessagesApi(self.payloads)


class _FakeService:
    def __init__(self, payloads: dict[str, dict]):
        self.payloads = payloads

    def users(self):
        return _FakeUsersApi(self.payloads)


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

    result = poll_new_fills(known_ids={"option-known"})

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
