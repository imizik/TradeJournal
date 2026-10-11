"""Direct owner reads: immutable bytes, recovery and fail-closed private boundary."""

import asyncio
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import tempfile
import uuid

import httpx
import pytest
from sqlalchemy import text
from sqlmodel import Session

import cloud_advisor_owner as reader
from app.engine import advisor_shadow as service, decisions, practice
from tests.advisor_owner_fixture import initialize


@pytest.fixture
def owner_fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    for name in ("DATABASE_URL", "MIGRATION_DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    scratch = tempfile.TemporaryDirectory(
        prefix="tj-owner-",
        dir="/private/tmp" if Path("/private/tmp").is_dir() else "/tmp",
    )
    directory = Path(scratch.name).resolve()
    value = initialize(directory)
    for name in ("DATABASE_URL", "MIGRATION_DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(value["config"]["socket_path"])
    os.chmod(value["config"]["socket_path"], 0o600)
    listener.listen(8)
    yield directory, value
    listener.close()
    scratch.cleanup()


def read(app, uid, *, path=reader.READ_PATH, method="GET", headers=None):
    async def invoke():
        async def identified(scope, receive, send):
            scope["advisor_owner_peer_uid"] = uid
            await app(scope, receive, send)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=identified), base_url="http://owner"
        ) as client:
            return await client.request(method, path, headers=headers)

    return asyncio.run(invoke())


def test_exact_cited_receipt_reopen_revoke_expiry_and_no_mutation(
    owner_fixture, monkeypatch
):
    directory, value = owner_fixture
    database = directory / "fixture.db"
    original = hashlib.sha256(database.read_bytes()).hexdigest()
    for _ in range(2):
        result = read(reader.create_app(directory / "owner.json"), os.getuid())
        assert result.status_code == 200, result.text
        assert result.json()["request"] == value["request"]
        assert result.json()["receipt"] == value["receipt"]
        assert result.headers["cache-control"] == "no-store"
    assert hashlib.sha256(database.read_bytes()).hexdigest() == original
    engine = reader.readonly_engine(database)
    with engine.connect() as connection:
        with pytest.raises(Exception, match="readonly"):
            connection.execute(text("DELETE FROM practice_agent_call"))
    assert hashlib.sha256(database.read_bytes()).hexdigest() == original
    from sqlmodel import create_engine

    writer = create_engine("sqlite:///" + str(database))
    with Session(writer) as db:
        service.set_enabled(db, uuid.UUID(value["request"]["assignment_id"]), False)
    monkeypatch.setattr(
        practice,
        "now_utc",
        lambda: (
            decisions._utc(value["request"]["expires_at"], "expiry")
            + timedelta(seconds=1)
        ),
    )
    result = read(reader.create_app(directory / "owner.json"), os.getuid()).json()
    assert result["assignment"] == {"enabled": False, "expired": True}
    assert (
        result["receipt"] == value["receipt"] and result["request"] == value["request"]
    )
    writer.dispose()
    engine.dispose()


@pytest.mark.parametrize("uid", [None, 0, 999999])
def test_no_peer_or_wrong_peer_cannot_claim_owner(owner_fixture, uid):
    directory, _ = owner_fixture
    result = read(
        reader.create_app(directory / "owner.json"),
        uid,
        headers={"x-advisor-owner-peer-uid": str(os.getuid())},
    )
    assert result.status_code == 403
    assert "packet" not in result.text and "receipt" not in result.text


@pytest.mark.parametrize(
    "path,method,headers,status",
    [
        ("/owner/advisor?run_id=forged", "GET", {}, 404),
        ("/journal", "GET", {}, 404),
        ("/owner/advisor", "POST", {}, 404),
        ("/owner/advisor", "GET", {"authorization": "Bearer owner"}, 400),
        ("/owner/advisor", "GET", {"cookie": "owner=forged"}, 400),
        ("/owner/advisor", "GET", {"x-tj-gateway": "owner"}, 400),
        ("/owner/advisor", "GET", {"content-length": "1"}, 400),
    ],
)
def test_routes_and_forwarded_credentials_refused(
    owner_fixture, path, method, headers, status
):
    directory, _ = owner_fixture
    assert (
        read(
            reader.create_app(directory / "owner.json"),
            os.getuid(),
            path=path,
            method=method,
            headers=headers,
        ).status_code
        == status
    )


@pytest.mark.parametrize(
    "mutation",
    ["disabled", "peer", "pin", "socket_mode", "config_mode", "socket_replace"],
)
def test_config_or_socket_drift_fails_closed(owner_fixture, mutation):
    directory, value = owner_fixture
    app = reader.create_app(directory / "owner.json")
    config = value["config"]
    if mutation == "disabled":
        config["enabled"] = False
    if mutation == "peer":
        config["peer_uid"] += 1
    if mutation == "pin":
        config["binding"]["request_sha256"] = "0" * 64
    (directory / "owner.json").write_text(json.dumps(config))
    if mutation == "socket_mode":
        (directory / "owner.sock").chmod(0o666)
    if mutation == "config_mode":
        (directory / "owner.json").chmod(0o666)
    replacement = None
    if mutation == "socket_replace":
        (directory / "owner.sock").unlink()
        replacement = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        replacement.bind(str(directory / "owner.sock"))
        (directory / "owner.sock").chmod(0o600)
    try:
        assert read(app, os.getuid()).status_code == 503
    finally:
        if replacement:
            replacement.close()


@pytest.mark.parametrize("mutation", ["packet", "request", "receipt", "citation"])
def test_corrupt_identity_receipt_or_original_fact_citation_refused(
    owner_fixture, mutation
):
    directory, value = owner_fixture
    with sqlite3.connect(directory / "fixture.db") as db:
        raw = db.execute(
            "SELECT config_json FROM practice_agent_call WHERE id=?",
            (value["request"]["assignment_id"].replace("-", ""),),
        ).fetchone()[0]
        config = json.loads(raw)
        advisor = config["advisor"]
        if mutation == "packet":
            advisor["export"]["packet"]["missing"] = []
        if mutation == "request":
            advisor["export"]["question"] = "Changed question"
        if mutation == "receipt":
            advisor["receipt"]["received_at"] = "2000-01-01T00:00:00Z"
        if mutation == "citation":
            advisor["receipt"]["submitted_output"]["answer"]["references"][0][
                "fact_name"
            ] = "not-an-original-fact"
            advisor["response"] = advisor["receipt"]["submitted_output"]["answer"]
            advisor["receipt"]["receipt_sha256"] = service.digest(
                {k: v for k, v in advisor["receipt"].items() if k != "receipt_sha256"}
            )
        db.execute("UPDATE practice_agent_call SET config_json=?", (json.dumps(config),))
    with pytest.raises(Exception):
        reader.create_app(directory / "owner.json")


def test_disable_while_inflight_read_refuses_result(owner_fixture, monkeypatch):
    directory, value = owner_fixture
    app = reader.create_app(directory / "owner.json")
    original = reader.project

    def during(engine, binding):
        value["config"]["enabled"] = False
        (directory / "owner.json").write_text(json.dumps(value["config"]))
        return original(engine, binding)

    monkeypatch.setattr(reader, "project", during)
    assert read(app, os.getuid()).status_code == 503


def test_owner_templates_are_dormant_readonly_and_outside_four_unit_installer():
    root = Path(__file__).resolve().parents[2]
    unit = (
        root / "deploy/cloud-mcp-advisor/tradejournal-advisor-owner.service"
    ).read_text()
    assert (
        "Type=exec" in unit
        and "PrivateNetwork=true" in unit
        and "RestrictAddressFamilies=AF_UNIX" in unit
    )
    assert (
        "BindReadOnlyPaths=" in unit
        and "ReadWritePaths=" not in unit
        and "BindPaths=" not in unit
    )
    assert (
        "[Install]" not in unit
        and "Restart=" not in unit
        and "-B cloud_advisor_owner.py" in unit
    )
    assert (
        "[Install]"
        not in (
            root / "deploy/cloud-mcp-advisor/tradejournal-advisor-owner.socket"
        ).read_text()
    )
    import sys

    sys.path.insert(0, str(root / "deploy"))
    from advisor_mcp_stage import UNITS, BACKEND_FILES

    assert len(UNITS) == 4 and not any("owner" in name for name in UNITS)
    assert "cloud_advisor_owner.py" not in BACKEND_FILES
