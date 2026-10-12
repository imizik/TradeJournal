"""Owner-only reader for saved pre-trade checks: peer, routes, integrity, read-only."""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import sqlite3
import tempfile
import uuid

import httpx
import pytest

import cloud_check_owner as reader
from cloud_mcp_check_ledger import FORMAT, Ledger
from app.engine import pretrade_check
from tests.test_pretrade_check import IDEA, RECEIPT, analysis, cohort

PEER = 4242


def record(when=RECEIPT, **idea):
    answer = pretrade_check.run_check({**IDEA, **idea}, analysis(), cohort(10, 15.0), when)
    return {"format": FORMAT, "check_id": "chk_" + str(uuid.uuid4()), "operation_id": str(uuid.uuid4()),
        "actor": "auth0|owner", "profile_id": "check_" + str(uuid.uuid4()), "received_at": when.isoformat(),
        "idea": {**IDEA, **idea}, "free_text": None, "request_sha256": uuid.uuid4().hex * 2,
        "rules_version": answer["rules_version"], "answer": answer,
        "live_context": {"sha256": answer["live_context_sha256"], "analysis": analysis()},
        "features": {"state": "current", "features_sha256": "f" * 64, "generated_at": "2026-10-09T10:00:00+00:00",
            "age_seconds": 3600}, "timings_ms": {"context": 400.0, "history": 5.0, "check": 1.0, "total": 406.0},
        "errors": []}


@pytest.fixture
def owner(monkeypatch):
    scratch = tempfile.TemporaryDirectory(prefix="tj-chk-", dir="/private/tmp" if Path("/private/tmp").is_dir() else "/tmp")
    directory = Path(scratch.name).resolve()
    ledger = Ledger(directory / "ledger.db")
    config = {"enabled": True, "peer_uid": PEER, "socket_path": str(directory / "owner.sock"),
        "ledger_path": str(directory / "ledger.db")}
    path = directory / "owner.json"
    path.write_text(json.dumps(config))
    path.chmod(0o640)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(config["socket_path"])
    os.chmod(config["socket_path"], 0o660)
    listener.listen(8)
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    yield ledger, path, config
    listener.close()
    scratch.cleanup()


def read(app, uid, path=reader.LIST_PATH, method="GET", headers=None):
    async def invoke():
        async def identified(scope, receive, send):
            scope["check_owner_peer_uid"] = uid
            await app(scope, receive, send)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=identified), base_url="http://owner") as client:
            return await client.request(method, path, headers=headers)
    return asyncio.run(invoke())


def test_list_newest_first_and_reopen_unchanged(owner):
    ledger, path, _ = owner
    older = ledger.insert(record(datetime(2026, 10, 9, 14, 0, tzinfo=timezone.utc), ticker="QQQ"))
    newer = ledger.insert(record())
    ledger.attach(newer["actor"], newer["check_id"], "wait", "Wait for the 1m close above 580.50.")
    app = reader.create_app(path)
    listing = read(app, PEER)
    assert listing.status_code == 200 and listing.headers["cache-control"] == "no-store"
    body = listing.json()
    assert body["schema_version"] == reader.LIST_SCHEMA and body["total"] == 2
    assert [c["check_id"] for c in body["checks"]] == [newer["check_id"], older["check_id"]]
    assert body["checks"][0] | {} == {**body["checks"][0], "ticker": "SPY", "verdict": "go", "model_verdict": "wait",
        "total_ms": 406.0}
    assert body["checks"][1]["model_verdict"] is None
    detail = read(app, PEER, f"{reader.LIST_PATH}/{newer['check_id']}").json()
    assert detail["schema_version"] == reader.DETAIL_SCHEMA
    assert detail["answer"]["verdict"] == "go" and detail["answer"]["reasons"] == newer["answer"]["reasons"]
    assert detail["model_verdict"]["summary"] == "Wait for the 1m close above 580.50."
    assert "source_fill_keys" not in detail["answer"]["history"]
    assert detail["answer"]["history"]["trades_used"] == len(newer["answer"]["history"]["source_fill_keys"]) > 0
    assert "analysis" not in json.dumps(detail) and "auth0|owner" not in json.dumps(detail)
    # A fresh app (as after a service restart) reopens the same content.
    again = read(reader.create_app(path), PEER, f"{reader.LIST_PATH}/{newer['check_id']}").json()
    assert {k: v for k, v in again.items() if k != "read_at"} == {k: v for k, v in detail.items() if k != "read_at"}
    assert read(app, PEER, f"{reader.LIST_PATH}/chk_{uuid.uuid4()}").status_code == 404


@pytest.mark.parametrize("uid", [None, 0, PEER + 1])
def test_only_the_configured_peer_reads(owner, uid):
    owner[0].insert(record())
    assert read(reader.create_app(owner[1]), uid).status_code == 403


@pytest.mark.parametrize("path,method,headers", [
    (reader.LIST_PATH, "POST", None),
    (reader.LIST_PATH + "?limit=500", "GET", None),
    ("/owner/checks/../advisor", "GET", None),
    ("/owner/checks/chk_not-a-uuid", "GET", None),
    ("/owner/advisor", "GET", None),
    (reader.LIST_PATH, "GET", {"authorization": "Bearer invented"}),
    (reader.LIST_PATH, "GET", {"cookie": "session=invented"}),
])
def test_routes_selectors_and_credentials_refused(owner, path, method, headers):
    status = read(reader.create_app(owner[1]), PEER, path, method, headers).status_code
    assert status in (400, 404)


def test_tampered_record_refused(owner):
    ledger, path, config = owner
    saved = ledger.insert(record())
    db = sqlite3.connect(config["ledger_path"])
    db.execute("DROP TRIGGER check_record_no_update")
    db.execute("UPDATE check_record SET record_json = replace(record_json, '\"go\"', '\"pass\"')")
    db.commit()
    db.close()
    assert read(reader.create_app(path), PEER, f"{reader.LIST_PATH}/{saved['check_id']}").status_code == 503


def test_disable_or_config_drift_fails_closed(owner):
    ledger, path, config = owner
    ledger.insert(record())
    app = reader.create_app(path)
    path.write_text(json.dumps({**config, "enabled": False}))
    assert read(app, PEER).status_code == 503
    path.write_text(json.dumps({**config, "peer_uid": PEER + 1}))
    assert read(app, PEER).status_code == 503
    path.write_text(json.dumps(config))
    assert read(app, PEER).status_code == 200


def test_reader_never_writes(owner):
    ledger, _, config = owner
    ledger.insert(record())
    db = reader.connect(config["ledger_path"])
    try:
        with pytest.raises(sqlite3.OperationalError):
            db.execute("INSERT INTO model_verdict VALUES ('x', 'a', 'b', 'go', 's', 'h')")
    finally:
        db.close()


def test_grades_and_detail_use_only_saved_results(owner):
    ledger, path, _ = owner
    app = reader.create_app(path)
    empty = read(app, PEER, reader.GRADES_PATH).json()
    assert empty["schema_version"] == reader.GRADES_SCHEMA and empty["checks"] == 0 and empty["grade"]["final_checks"] == 0
    now = datetime.now(timezone.utc)
    saved = ledger.insert(record(now))
    pending = ledger.insert(record(now))
    ledger.attach(saved["actor"], saved["check_id"], "go", "Take it.")
    result = {"outcome": {"state": "traded", "total_pnl": 30.0}, "move": {"state": "complete", "move_pct": 0.4}}
    ledger.save_result(saved["actor"], saved["check_id"], result)
    grades = read(app, PEER, reader.GRADES_PATH).json()
    assert grades["checks"] == 2 and grades["settled"] == 1
    assert grades["grade"]["followed"] == 1 and grades["grade"]["jo"]["agrees_with_rules"] == 1
    assert read(app, PEER, f"{reader.LIST_PATH}/{saved['check_id']}").json()["result"] == result
    assert read(app, PEER, f"{reader.LIST_PATH}/{pending['check_id']}").json()["result"] is None
    assert read(app, PEER + 1, reader.GRADES_PATH).status_code == 403
    assert read(app, PEER, reader.GRADES_PATH + "?days=900").status_code == 404
