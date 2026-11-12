"""Sign in to Robinhood's agent connection for TradeJournal's read-only feed, on your own Mac (docs/robinhood-read-feed.md).

    python3 backend/scripts/robinhood_signin.py [where-to-save.json]

It registers this app with Robinhood, opens Robinhood's own sign-in page in your browser, waits for the sign-in to come
back to this Mac (http://localhost:8799/callback), and saves it to one file readable only by you (mode 0600; default
~/robinhood-token.json). It calls no Robinhood tool, prints no token and writes nothing else. Then copy that file to
the server with the one command docs/robinhood-read-feed.md gives, and delete the local copy.

Python standard library only.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
from pathlib import Path
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

RESOURCE = "https://agent.robinhood.com/mcp/trading"  # the connection this sign-in is for (sent as the OAuth resource)
AUTHORIZE = "https://robinhood.com/oauth"
TOKEN = "https://api.robinhood.com/oauth2/token/"
REGISTER = "https://agent.robinhood.com/oauth/trading/register"
PORT = 8799
REDIRECT = f"http://localhost:{PORT}/callback"
WAIT_SECONDS = 300


def post(url: str, body: bytes, content_type: str) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": content_type, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as reply:
            status, text = reply.status, reply.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        status, text = exc.code, exc.read().decode("utf-8", "replace")
    try:
        data = json.loads(text)
    except ValueError:
        data = {}
    return status, data if isinstance(data, dict) else {}


def register() -> str:
    status, data = post(REGISTER, json.dumps({
        "client_name": "TradeJournal read-only feed", "redirect_uris": [REDIRECT],
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
        "token_endpoint_auth_method": "none"}).encode(), "application/json")
    if status not in (200, 201) or not data.get("client_id"):
        sys.exit(f"Robinhood did not register this app (status {status}). Nothing was saved.")
    return str(data["client_id"])


def wait_for_code(url: str, state: str) -> str:
    got: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            parts = urllib.parse.urlsplit(self.path)
            if parts.path == "/callback":
                q = urllib.parse.parse_qs(parts.query)
                got.update({k: (q.get(k) or [None])[0] for k in ("code", "state", "error")})
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h3>Done. You can close this tab and go back to the terminal.</h3>")

        def log_message(self, *args):  # the callback address carries the code: never print it
            pass

    server = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    server.timeout = 5
    print("Opening Robinhood's sign-in in your browser. If it does not open, paste this address into it:\n")
    print(url + "\n")
    webbrowser.open(url)
    print(f"Waiting up to {WAIT_SECONDS // 60} minutes for the sign-in to come back...")
    deadline = time.time() + WAIT_SECONDS
    while "state" not in got and time.time() < deadline:
        server.handle_request()
    server.server_close()
    if "state" not in got:
        sys.exit("Timed out waiting for the sign-in. Nothing was saved.")
    if got.get("error") or not got.get("code"):
        sys.exit(f"Robinhood sent back an error instead of a sign-in ({got.get('error')}). Nothing was saved.")
    if got.get("state") != state:
        sys.exit("The reply did not match this sign-in request, so it was ignored. Nothing was saved.")
    return got["code"]


def save(path: Path, signin: dict) -> None:
    """Write through a 0600 temporary file and an atomic rename, so the file is never readable by anyone else."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as out:
        os.fchmod(out.fileno(), 0o600)
        json.dump(signin, out)
    os.replace(tmp, path)


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "~/robinhood-token.json").expanduser()
    client_id = register()
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    url = AUTHORIZE + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT, "scope": "internal", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256", "resource": RESOURCE})
    code = wait_for_code(url, state)
    status, tok = post(TOKEN, urllib.parse.urlencode({
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT, "client_id": client_id,
        "code_verifier": verifier, "resource": RESOURCE}).encode(), "application/x-www-form-urlencoded")
    if status != 200 or not tok.get("access_token") or not tok.get("expires_in"):
        sys.exit(f"The sign-in came back but Robinhood refused to finish it (status {status}). Nothing was saved.")
    save(path, {"access_token": tok["access_token"], "refresh_token": tok.get("refresh_token") or "",
                "expires_at": int(time.time() + float(tok["expires_in"])), "client_id": client_id})
    days = float(tok["expires_in"]) / 86400
    print(f"\nSigned in. Saved to {path} (readable only by you).")
    print(f"It lasts about {days:.1f} days; the server renews it on its own: {'yes' if tok.get('refresh_token') else 'NO (no renewal token came back)'}.")
    print("Next: copy it to the server with the command in docs/robinhood-read-feed.md, then delete this copy.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("Stopped. Nothing was saved.")
