"""Offline, disabled invented advisor bundle. Never installs or starts services."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

SOURCE = Path(__file__).resolve().parent.parent
TEMPLATES = SOURCE / "deploy/cloud-mcp-advisor"
UNITS = tuple(f"tradejournal-advisor-{role}.{kind}" for role in ("backend", "mcp") for kind in ("socket", "service"))
ADAPTER_FILES = ("cloud_mcp_advisor.py", "cloud_mcp_advisor_common.py", "cloud_mcp_d0.py")
BACKEND_FILES = (*ADAPTER_FILES, "cloud_mcp_advisor_bridge.py", "pyproject.toml", "alembic.ini")
FORMAT = "advisor-disabled-bundle-v1"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def exact(path, *, exists=True):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts or str(path) != str(path.absolute()):
        raise ValueError("Require an exact absolute path")
    if any(p.is_symlink() for p in (path, *path.parents)) or (exists and not path.exists()):
        raise ValueError("Require existing paths without symlinks")
    return path


def inventory(directory):
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError("No symlinks or special files in a staged bundle")
        mode = path.stat().st_mode & 0o777
        if mode != (0o600 if path.is_file() else 0o700):
            raise ValueError("Bundle files/directories must be private 0600/0700")
        if path != directory / "manifest.json":
            result[str(path.relative_to(directory))] = {"mode": mode,
                "sha256": digest(path) if path.is_file() else None}
    return result


def validate(destination):
    destination = exact(destination)
    if not destination.is_dir() or destination.stat().st_mode & 0o777 != 0o700:
        raise ValueError("Require a private staging directory")
    record = destination / "manifest.json"
    if record.is_symlink() or record.stat().st_mode & 0o777 != 0o600:
        raise ValueError("Require private manifest")
    manifest = json.loads(record.read_text())
    if (set(manifest) != {"format", "enabled", "fixture_only", "source_commit", "inventory"}
            or manifest["format"] != FORMAT or manifest["enabled"] is not False
            or manifest["fixture_only"] is not True or inventory(destination) != manifest["inventory"]):
        raise ValueError("Staged inventory, modes or disabled provenance changed")
    expected = {f"units/{name}" for name in UNITS} | {"config/config.json", "config/public-keys.json",
        "state/fixture.db", "recovery/request.json", "proxy/Caddyfile.example"}
    if not expected <= set(manifest["inventory"]):
        raise ValueError("Incomplete advisor bundle")
    config = json.loads((destination / "config/config.json").read_text())
    if config.get("enabled") is not False or any(p.get("enabled") is not False for p in config["profiles"]):
        raise ValueError("Staging must remain disabled")
    return manifest


def stage(destination, *, wheels=None):
    destination = exact(destination, exists=False)
    exact(destination.parent)
    if destination.exists():
        raise ValueError("Refuse an existing staging destination")
    # Source allowlist excludes dotenv, backend/data, tests, caches and credentials.
    originals = {f"adapter/{name}": SOURCE / "backend" / name for name in ADAPTER_FILES}
    originals.update({f"backend/{name}": SOURCE / "backend" / name for name in BACKEND_FILES})
    tracked = subprocess.check_output(["git", "ls-files", "-z", "backend/app", "backend/alembic"], cwd=SOURCE).decode().split("\0")
    for relative in filter(None, tracked):
        file = SOURCE / relative
        if file.suffix in {".py", ".mako"}:
            originals[relative] = file
    originals.update({f"units/{name}": TEMPLATES / name for name in UNITS})
    originals["proxy/Caddyfile.example"] = TEMPLATES / "Caddyfile.example"
    if wheels is not None:
        wheels = exact(wheels)
        if not wheels.is_dir() or not list(wheels.glob("*.whl")):
            raise ValueError("Require verified offline wheel artifacts")
        originals.update({f"wheels/{p.name}": p for p in wheels.glob("*.whl")})
    for file in originals.values():
        exact(file)
        if not file.is_file():
            raise ValueError("Require regular source files")
    destination.mkdir(mode=0o700)
    try:
        for relative, source in originals.items():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        for folder in ("state", "config", "recovery"):
            (destination / folder).mkdir(exist_ok=True)
        database = destination / "state/fixture.db"
        database.touch(mode=0o600)
        # Only this new private SQLite is migrated; ambient URL/keys are discarded.
        url = "sqlite:///" + str(database)
        env = {"PATH": os.environ.get("PATH", ""), "PYTHON_DOTENV_DISABLED": "1",
            "DATABASE_URL": url, "MIGRATION_DATABASE_URL": url}
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=SOURCE / "backend", env=env, check=True, capture_output=True)
        script = '''import json,sys
from pathlib import Path
from sqlmodel import Session,create_engine
from app.engine import advisor_shadow as service
engine=create_engine(sys.argv[1])
with Session(engine) as db:
    run,assignment,_discarded_capability=service.create_fixture(db)
    exported=service.advisor_handoff(db,run,{"question":"What is missing from this invented setup?","user_plan":"Wait for verified trigger and risk inputs."})
    service.set_enabled(db,assignment,False)
Path(sys.argv[2]).write_text(json.dumps(exported,indent=2)+"\\n")
engine.dispose()
'''
        subprocess.run([sys.executable, "-c", script, url, str(destination / "recovery/request.json")],
            cwd=SOURCE / "backend", env=env, check=True, capture_output=True)
        request = json.loads((destination / "recovery/request.json").read_text())
        config = json.loads((TEMPLATES / "config.example.json").read_text())
        config["profiles"][0].update({k: request[k] for k in ("assignment_id", "run_id", "packet_sha256", "request_sha256")})
        (destination / "config/config.json").write_text(json.dumps(config, indent=2) + "\n")
        (destination / "config/public-keys.json").write_text(json.dumps({"issuer_url": config["issuer_url"],
            "jwks_url": config["jwks_url"], "fetched_at": 0, "expires_at": 0, "keys": []}) + "\n")
        for path in destination.rglob("*"):
            path.chmod(0o600 if path.is_file() else 0o700)
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SOURCE, text=True).strip()
        manifest = {"format": FORMAT, "enabled": False, "fixture_only": True,
            "source_commit": commit, "inventory": inventory(destination)}
        (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        (destination / "manifest.json").chmod(0o600)
        validate(destination)
        return manifest
    except BaseException:
        shutil.rmtree(destination)  # Only this exclusively created destination.
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["stage", "preflight"])
    parser.add_argument("destination", type=Path)
    parser.add_argument("--wheels", type=Path, help="Already verified artifact wheels; no downloading")
    args = parser.parse_args()
    manifest = stage(args.destination, wheels=args.wheels) if args.action == "stage" else validate(args.destination)
    print(json.dumps({"enabled": False, "fixture_only": True, "entries": len(manifest["inventory"]),
        "manifest_sha256": digest(args.destination / "manifest.json"), "activation": "not performed"}))


if __name__ == "__main__":
    main()
