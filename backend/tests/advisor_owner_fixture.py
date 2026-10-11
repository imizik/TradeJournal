"""Disposable invented owner-reader fixtures. No grants, providers or real data."""

import json
import os
from pathlib import Path
import socket
import sys
import uuid

from alembic import command
from alembic.config import Config
from sqlmodel import Session, create_engine

from app.engine import advisor_shadow as service
from cloud_advisor_owner import OwnerConfig


def initialize(directory, *, saved=True, peer=None):
    directory = Path(directory).resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    database = directory / "fixture.db"
    if database.exists():
        raise ValueError("Refuse an existing test fixture")
    url = "sqlite:///" + str(database)
    os.environ.update(
        DATABASE_URL=url, MIGRATION_DATABASE_URL=url, PYTHON_DOTENV_DISABLED="1"
    )
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "alembic")
    )
    command.upgrade(config, "head")
    database.chmod(0o600)
    engine = create_engine(url)
    with Session(engine) as db:
        run_id, assignment_id, _ = service.create_fixture(db)
        request = service.advisor_handoff(
            db,
            run_id,
            {
                "question": "Is an invented close enough?",
                "user_plan": "Wait for verified prices and fixed risk",
            },
        )
        opportunity = request["packet"]["opportunities"][0]
        answer = {
            "summary": "Wait",
            "interpretation": "Invented evidence only",
            "risks": "Calendar unavailable",
            "conditions": "Verified prices and risk",
            "gaps": "Real prices unavailable",
            "references": [
                {
                    "opportunity_id": opportunity["opportunity_id"],
                    "fact_name": opportunity["price_facts"][0]["name"],
                }
            ],
        }
        envelope = {
            k: request[k]
            for k in (
                "version",
                "assignment_id",
                "run_id",
                "packet_sha256",
                "request_sha256",
            )
        }
        envelope["answer"] = answer
        receipt = (
            service.advisor_import(db, run_id, envelope, transport="oauth-mcp")[
                "advisor"
            ]["receipt"]
            if saved
            else None
        )
    config = {
        "enabled": True,
        "peer_uid": os.getuid() if peer is None else peer,
        "socket_uid": os.getuid(),
        "socket_path": str(directory / "owner.sock"),
        "database_path": str(database),
        "binding": {
            "enabled": False,
            "subject": "invented-owner-test-advisor",
            "id": "advisor_" + str(uuid.uuid4()),
            "binding_version": 1,
            **{
                k: request[k]
                for k in ("assignment_id", "run_id", "packet_sha256", "request_sha256")
            },
        },
    }
    OwnerConfig.model_validate(config)
    path = directory / "owner.json"
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    value = {
        "request": request,
        "receipt": receipt,
        "envelope": envelope,
        "config": config,
    }
    (directory / "expected.json").write_text(json.dumps(value))
    (directory / "expected.json").chmod(0o600)
    engine.dispose()
    return value


def change(directory, operation):
    directory = Path(directory)
    value = json.loads((directory / "expected.json").read_text())
    engine = create_engine("sqlite:///" + value["config"]["database_path"])
    with Session(engine) as db:
        if operation == "save":
            value["receipt"] = service.advisor_import(
                db,
                uuid.UUID(value["request"]["run_id"]),
                value["envelope"],
                transport="oauth-mcp",
            )["advisor"]["receipt"]
            (directory / "expected.json").write_text(json.dumps(value))
        elif operation == "revoke":
            service.set_enabled(db, uuid.UUID(value["request"]["assignment_id"]), False)
    engine.dispose()


def serve(directory):
    directory = Path(directory)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(directory / "owner.sock"))
    os.chmod(directory / "owner.sock", 0o600)
    listener.listen(8)
    os.dup2(listener.fileno(), 3, inheritable=True)
    # Keep the listener open even when dup2's source already was descriptor 3.
    os.set_inheritable(3, True)
    os.execve(
        sys.executable,
        [
            sys.executable,
            "-B",
            "cloud_advisor_owner.py",
            "--config",
            str(directory / "owner.json"),
        ],
        {
            "PATH": "/usr/bin:/bin",
            "PYTHON_DOTENV_DISABLED": "1",
            "LISTEN_FDS": "1",
            "LISTEN_PID": str(os.getpid()),
        },
    )


if __name__ == "__main__":
    operation, directory = sys.argv[1:]
    if operation in {"init", "init-empty"}:
        initialize(directory, saved=operation == "init")
    elif operation == "serve":
        serve(directory)
    else:
        change(directory, operation)
