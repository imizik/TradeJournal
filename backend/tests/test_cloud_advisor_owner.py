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
        db.execute(
            "UPDATE practice_agent_call SET config_json=?", (json.dumps(config),)
        )
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
    assert "User=tj-advisor-owner" in unit and "Group=tj-advisor-owner" in unit
    assert "User=tj-advisor-backend" not in unit
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
    from advisor_mcp_stage import ADAPTER_FILES, BACKEND_FILES, UNITS

    assert len(UNITS) == 4 and not any("owner" in name for name in UNITS)
    # The bridge uses the kernel-peer protocol, without installing owner units
    # or giving the adapter the owner reader implementation.
    assert "cloud_advisor_owner.py" in BACKEND_FILES
    assert "cloud_advisor_owner.py" not in ADAPTER_FILES


@pytest.mark.parametrize(
    "mutation",
    [
        "valid",
        "uid",
        "write",
        "group",
        "extra",
        "directory",
        "mode",
        "absent",
        "unsupported",
    ],
)
def test_named_uid_acl_is_exact_live_and_not_a_group_read_relaxation(
    tmp_path, monkeypatch, mutation
):
    from cloud_mcp_advisor_common import fixture_acl, private_fixture

    directory = tmp_path.resolve()
    database = directory / "fixture.db"
    database.write_bytes(b"invented only")
    database.chmod(0o640)
    directory.chmod(0o710)
    uid = os.getuid() + 10000  # Different dedicated reader, never the writer UID.
    file_acl = fixture_acl(uid)
    dir_acl = fixture_acl(uid, directory=True)
    if mutation == "uid":
        file_acl = fixture_acl(uid + 1)
    if mutation == "write":
        file_acl = file_acl[:14] + b"\x06\x00" + file_acl[16:]
    if mutation == "group":
        file_acl = file_acl[:22] + b"\x04\x00" + file_acl[24:]
    if mutation == "extra":
        file_acl += file_acl[12:20]
    if mutation == "directory":
        dir_acl = fixture_acl(uid + 1, directory=True)
    if mutation == "mode":
        database.chmod(0o660)

    def attrs(path, name):
        assert name == "system.posix_acl_access"
        if mutation == "absent":
            raise OSError("ACL not supported/present")
        return file_acl if Path(path) == database else dir_acl

    if mutation == "unsupported":
        monkeypatch.delattr(os, "getxattr", raising=False)
    else:
        monkeypatch.setattr(os, "getxattr", attrs, raising=False)
    # Even an apparently readable group mode is denied unless an exact named
    # UID grant was separately configured; group membership is irrelevant.
    with pytest.raises(ValueError):
        private_fixture(database)
    if mutation == "valid":
        private_fixture(database, owner_reader_uid=uid)
        with pytest.raises(ValueError):
            private_fixture(database, owner_reader_uid=os.getuid())
    else:
        with pytest.raises((ValueError, OSError)):
            private_fixture(database, owner_reader_uid=uid)


def test_reader_config_uid_requires_actual_process_and_acl_grant(owner_fixture):
    directory, value = owner_fixture
    value["config"]["reader_uid"] = os.getuid() + 1
    (directory / "owner.json").write_text(json.dumps(value["config"]))
    with pytest.raises(ValueError, match="dedicated UID"):
        reader.create_app(directory / "owner.json")
    value["config"]["reader_uid"] = os.getuid()
    (directory / "owner.json").write_text(json.dumps(value["config"]))
    with pytest.raises(ValueError, match="read-only owner UID grant"):
        reader.create_app(directory / "owner.json")


def status(directory):
    result = read(reader.create_app(directory / "owner.json"), os.getuid(), path=reader.STATUS_PATH)
    assert result.status_code == 200, result.text
    assert result.headers["cache-control"] == "no-store"
    return result


def test_status_reports_states_and_times_without_secrets(owner_fixture, monkeypatch):
    from tests import advisor_owner_fixture as fixture

    directory, value = owner_fixture
    result = status(directory)
    body = result.json()
    assert body["schema_version"] == "advisor-owner-status-v1"
    assert body["keys"]["state"] == "fresh" and body["keys"]["expires_at"]
    assert body["advisor"] == {"state": "enabled"}
    assert body["assignment"] == {"state": "answered", "expires_at": value["request"]["expires_at"]}
    assert body["last_save_at"] == value["receipt"]["received_at"] and body["last_read_at"] is None
    advisor = json.loads((directory / "advisor.json").read_text())
    secrets = [advisor["client_id"], advisor["profiles"][0]["subject"], "invented-public-key", "RSA",
        value["request"]["request_sha256"], value["request"]["packet_sha256"], value["receipt"]["receipt_sha256"],
        "Invented evidence only", str(directory)]
    assert not any(secret in result.text for secret in secrets)

    fixture.write_keys(directory, 600)
    assert status(directory).json()["keys"]["state"] == "expiring"
    fixture.write_keys(directory, -1)
    assert status(directory).json()["keys"]["state"] == "expired"
    (directory / "public-keys.json").unlink()
    (directory / "public-keys.json").symlink_to(directory / "advisor.json")
    assert status(directory).json()["keys"] == {"state": "unreadable", "expires_at": None}
    fixture.write_advisor(directory, value["config"]["binding"], profile_enabled=False)
    assert status(directory).json()["advisor"] == {"state": "profile-disabled"}
    fixture.write_advisor(directory, value["config"]["binding"], enabled=False)
    assert status(directory).json()["advisor"] == {"state": "config-disabled"}
    fixture.write_advisor(directory, {**value["config"]["binding"], "subject": "someone-else"})
    assert status(directory).json()["advisor"] == {"state": "profile-mismatch"}
    (directory / "advisor.json").write_text("{not json")
    assert status(directory).json()["advisor"] == {"state": "unreadable"}


def test_status_assignment_states_and_unconfigured_grant(owner_fixture, monkeypatch, tmp_path):
    from sqlmodel import create_engine

    directory, value = owner_fixture
    writer = create_engine("sqlite:///" + str(directory / "fixture.db"))
    with Session(writer) as db:
        service.set_enabled(db, uuid.UUID(value["request"]["assignment_id"]), False)
    writer.dispose()
    assert status(directory).json()["assignment"]["state"] == "revoked"
    config = json.loads((directory / "owner.json").read_text())
    del config["advisor_config_path"]
    (directory / "owner.json").write_text(json.dumps(config))
    body = status(directory).json()
    assert body["keys"] == {"state": "not-configured", "expires_at": None}
    assert body["advisor"] == {"state": "not-configured"}


def test_status_reports_pending_then_expired_before_any_save(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    scratch = tempfile.TemporaryDirectory(prefix="tj-owner-", dir="/private/tmp" if Path("/private/tmp").is_dir() else "/tmp")
    directory = Path(scratch.name).resolve()
    try:
        value = initialize(directory, saved=False)
        for name in ("DATABASE_URL", "MIGRATION_DATABASE_URL"):
            monkeypatch.delenv(name, raising=False)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(value["config"]["socket_path"])
        os.chmod(value["config"]["socket_path"], 0o600)
        body = status(directory).json()
        assert body["assignment"]["state"] == "pending" and body["last_save_at"] is None
        monkeypatch.setattr(practice, "now_utc", lambda: decisions._utc(value["request"]["expires_at"], "expiry")
            + timedelta(seconds=1))
        assert status(directory).json()["assignment"]["state"] == "expired"
        listener.close()
    finally:
        scratch.cleanup()


def test_status_route_keeps_owner_peer_and_no_selector_rules(owner_fixture):
    directory, _ = owner_fixture
    app = reader.create_app(directory / "owner.json")
    assert read(app, 999999, path=reader.STATUS_PATH).status_code == 403
    assert read(app, os.getuid(), path=reader.STATUS_PATH + "?state=x").status_code == 404
    assert read(app, os.getuid(), path=reader.STATUS_PATH, method="POST").status_code == 404
    assert read(app, os.getuid(), path=reader.STATUS_PATH, headers={"cookie": "owner=forged"}).status_code == 400


def test_status_follows_managed_questions_even_without_advisor_config(owner_fixture):
    from sqlmodel import create_engine
    from app.engine import advisor_assignments as managed
    from cloud_mcp_advisor_common import AdvisorProfile

    directory, value = owner_fixture
    config = json.loads((directory / "owner.json").read_text())
    del config["advisor_config_path"]  # Mode must come from the ledger, not the config.
    (directory / "owner.json").write_text(json.dumps(config))
    writer = create_engine("sqlite:///" + str(directory / "fixture.db"))
    with Session(writer) as db:
        managed.mutate(db, AdvisorProfile.model_validate(value["config"]["binding"]), {
            "operation_id": str(uuid.uuid4()), "question": "Invented follow-up?", "user_plan": "Wait",
            "invented_only": True}, lambda: None)
    writer.dispose()
    body = status(directory).json()
    assert body["assignment"]["state"] == "pending" and body["assignment"]["expires_at"]
    assert body["assignment"]["expires_at"] != value["request"]["expires_at"]
    assert body["last_save_at"] == value["receipt"]["received_at"]  # The original answer is still the latest save.
    assert "Invented follow-up" not in json.dumps(body)
