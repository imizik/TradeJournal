import sys
from types import ModuleType, SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app


def test_gmail_auth_uses_request_base_url(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def _fake_begin(callback_base_url: str | None = None) -> str:
        captured["callback_base_url"] = callback_base_url or ""
        return "https://accounts.google.com/o/oauth2/auth"

    monkeypatch.setattr("app.routers.auth.begin_gmail_oauth", _fake_begin)

    with TestClient(app, base_url="http://127.0.0.1:8080") as client:
        response = client.get("/auth/gmail/start")

    assert response.status_code == 200
    assert captured["callback_base_url"] == "http://127.0.0.1:8080/"


def test_gmail_oauth_reuses_state_redirect_uri(monkeypatch, tmp_path) -> None:
    from app.engine import gmail_poller

    redirect_uris: list[str] = []
    fetched_codes: list[str] = []
    token_code_verifiers: list[str | None] = []

    class _FakeFlow:
        redirect_uri = ""
        credentials = SimpleNamespace(to_json=lambda: "{}")

        def __init__(self) -> None:
            self.code_verifier: str | None = None

        def authorization_url(self, **kwargs):
            self.code_verifier = "pkce-verifier"
            redirect_uris.append(self.redirect_uri)
            return (f"https://accounts.google.com/o/oauth2/auth?state={kwargs['state']}", kwargs["state"])

        def fetch_token(self, code: str) -> None:
            fetched_codes.append(code)
            redirect_uris.append(self.redirect_uri)
            token_code_verifiers.append(self.code_verifier)

    class _FakeInstalledAppFlow:
        @staticmethod
        def from_client_secrets_file(_path, _scopes):
            return _FakeFlow()

    monkeypatch.setattr(gmail_poller, "CREDENTIALS_FILE", tmp_path / "credentials.json")
    monkeypatch.setattr(gmail_poller, "TOKEN_FILE", tmp_path / "token.json")
    monkeypatch.setattr(gmail_poller, "OAUTH_STATE_FILE", tmp_path / "gmail_oauth_states.json")
    gmail_poller.CREDENTIALS_FILE.write_text("{}")

    oauth_package = ModuleType("google_auth_oauthlib")
    oauth_package.__path__ = []
    flow_module = ModuleType("google_auth_oauthlib.flow")
    flow_module.InstalledAppFlow = _FakeInstalledAppFlow
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib", oauth_package)
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib.flow", flow_module)

    auth_url = gmail_poller.begin_gmail_oauth("http://127.0.0.1:8080/")
    state = auth_url.split("state=", 1)[1]
    gmail_poller.finish_gmail_oauth(code="oauth-code", state=state)

    assert fetched_codes == ["oauth-code"]
    assert redirect_uris == [
        "http://127.0.0.1:8080/auth/gmail/callback",
        "http://127.0.0.1:8080/auth/gmail/callback",
    ]
    assert token_code_verifiers == ["pkce-verifier"]
    assert gmail_poller.OAUTH_STATE_FILE.read_text() == "{}"
