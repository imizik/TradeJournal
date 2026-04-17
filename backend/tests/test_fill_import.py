from fastapi.testclient import TestClient

from app.main import app


def test_import_returns_503_for_controlled_gmail_failures(monkeypatch) -> None:
    def _raise(*_args, **_kwargs):
        from app.engine.gmail_poller import GmailPollingError

        raise GmailPollingError("gmail is temporarily unavailable")

    monkeypatch.setattr("app.engine.gmail_poller.poll_new_fills", _raise)

    with TestClient(app) as client:
        response = client.post("/fills/import")

    assert response.status_code == 503
    assert response.json() == {"detail": "gmail is temporarily unavailable"}
