"""Prepare a disabled fixture-only journal gateway bundle; never install or start it."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import uuid

SOURCE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SOURCE / "backend"))
from cloud_mcp_journal import JournalConfig  # noqa: E402
from journal_coach_snapshot import Snapshot  # noqa: E402

RUNTIME_FILES = ("cloud_mcp_d0.py", "cloud_mcp_journal.py", "journal_coach_snapshot.py")
UNITS = ("tradejournal-journal-coach.service", "tradejournal-journal-coach.socket")


def fixture_snapshot(now=None):
    now = now or datetime.now(timezone.utc)
    # Fixed historical dates and invented rows: never read the journal or DB.
    return Snapshot.model_validate_json(json.dumps({
        "schema_version": "journal-coach-snapshot-v1", "generated_at": now.isoformat(),
        "start_day": "2026-01-02", "end_day": "2026-01-02",
        "source": "approved_journal_export", "sample_data": True,
        "trades": [{"id": str(uuid.UUID(int=index + 1)), "ticker": symbol,
            "instrument_type": "stock", "quantity": "1.000000", "realized_pnl": pnl,
            "status": "closed", "opened_at": "2026-01-02T09:30:00", "closed_at": "2026-01-02T10:00:00"}
            for index, (symbol, pnl) in enumerate((("MU", "-1.250000"), ("NBIS", None)))],
    }))


def stage(destination, *, issuer_url, resource_url, client_id, subject, profile_id, source=SOURCE):
    destination = Path(destination)
    if not destination.is_absolute() or ".." in destination.parts or destination.exists() or destination.is_symlink():
        raise ValueError("Use a new exact absolute staging directory")
    if not destination.parent.is_dir() or destination.parent.resolve() != destination.parent:
        raise ValueError("Staging parent must exist without symlinks")
    source = Path(source)
    if not source.is_absolute() or ".." in source.parts:
        raise ValueError("Use an exact absolute reviewed source directory")
    sources = {f"runtime/backend/{name}": source / "backend" / name for name in RUNTIME_FILES}
    sources.update({f"units/{name}": source / "deploy/cloud-mcp-journal" / name for name in UNITS})
    if any(not p.is_file() or any(part.is_symlink() for part in (p, *p.parents))
            for p in sources.values()):
        raise ValueError("Require regular reviewed source files")
    payload = (fixture_snapshot().model_dump_json(indent=2) + "\n").encode()
    config = JournalConfig.model_validate_json(json.dumps({
        "enabled": False, "journal_only": True, "issuer_url": issuer_url,
        "resource_url": resource_url, "jwks_url": issuer_url + ".well-known/jwks.json",
        "jwks_file": "/var/lib/tradejournal-journal/jwks.json", "client_id": client_id,
        "profiles": [{"subject": subject, "id": profile_id, "enabled": False}],
        "snapshot_file": "/var/lib/tradejournal-journal/approved.json",
        "snapshot_sha256": hashlib.sha256(payload).hexdigest(),
        "start_day": "2026-01-02", "end_day": "2026-01-02", "sample_data": True,
    }))
    destination.mkdir(mode=0o700)
    try:
        for relative, original in sources.items():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(original.read_bytes())
            target.chmod(0o600)
        for relative, body in {"state/approved.json": payload,
                "config/config.json": (config.model_dump_json(indent=2) + "\n").encode()}.items():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
            target.chmod(0o600)
        hashes = {str(p.relative_to(destination)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in destination.rglob("*") if p.is_file()}
        manifest = {"format_version": 1, "fixture_only": True, "enabled": False,
            "source_sha256": hashes, "production_reads": False, "service_installed": False,
            "os_user_created": False, "oauth_registered": False,
            "dependencies": {"mcp": "1.28.1", "PyJWT[crypto]": "2.13.0"}}
        target = destination / "manifest.json"
        target.write_text(json.dumps(manifest, indent=2) + "\n")
        target.chmod(0o600)
        return manifest
    except BaseException:
        # Only the new directory created by this invocation is removed.
        shutil.rmtree(destination)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--issuer-url", required=True)
    parser.add_argument("--resource-url", required=True)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--profile-id", required=True)
    args = parser.parse_args()
    try:
        result = stage(**vars(args))
        print(json.dumps({"fixture_only": result["fixture_only"], "enabled": result["enabled"],
            "file_count": len(result["source_sha256"]), "activation": "not performed"}))
    except Exception:
        raise SystemExit("Fixture staging refused; no service or access was activated") from None


if __name__ == "__main__":
    main()
