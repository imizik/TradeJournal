#!/usr/bin/env python3
"""Build an immutable release from committed source on Ubuntu 24.04 / Node 22.

Run on a build machine or CI, never the small production VPS. No local .env,
OAuth tokens, database files or caches are read or copied.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile


def run(*command, **kwargs):
    return subprocess.run([str(value) for value in command], check=True, **kwargs)


def package(release: Path, output: Path) -> Path:
    archive = output / f"{release.name}.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(release, arcname=release.name)
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--output", type=Path, default=Path("dist"))
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,95}", args.release_id):
        parser.error("Use a lowercase release ID containing letters, digits, dots and hyphens")
    distro = platform.freedesktop_os_release()
    if distro.get("ID") != "ubuntu" or distro.get("VERSION_ID") != "24.04" or sys.version_info[:2] != (3, 12):
        parser.error("Build on Ubuntu 24.04 with Python 3.12, matching the VPS architecture")
    node = Path(shutil.which("node") or "missing-node").resolve()
    node_version = run(node, "--version", capture_output=True, text=True).stdout.strip()
    if not node_version.startswith("v22."):
        parser.error("Node 22 is required")
    root = Path(__file__).resolve().parents[1]
    if run("git", "status", "--porcelain", cwd=root, capture_output=True, text=True).stdout.strip():
        parser.error("Commit source changes before building; artifacts contain only HEAD")
    commit = run("git", "rev-parse", "HEAD", cwd=root, capture_output=True, text=True).stdout.strip()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tradejournal-build-") as scratch:
        scratch = Path(scratch)
        source = scratch / "source"
        source.mkdir()
        source_tar = scratch / "source.tar"
        # Explicit source roots; git archive excludes ignored machine state.
        run("git", "archive", "--format=tar", "-o", source_tar, "HEAD", "backend", "frontend", "deploy", cwd=root)
        with tarfile.open(source_tar) as archive:
            archive.extractall(source, filter="data")
        # Fail closed if credentials/runtime state ever become tracked by mistake.
        for path in source.rglob("*"):
            if path.name in {".env", ".env.local", ".env.production", ".env.tradingview", "token.json", "credentials.json"}:
                raise ValueError(f"Refusing sensitive file in source: {path.relative_to(source)}")
        if (source / "backend/data").exists():
            raise ValueError("Runtime backend/data must not be tracked")
        release = scratch / args.release_id
        release.mkdir(mode=0o755)
        shutil.copytree(source / "backend", release / "backend")
        shutil.copytree(source / "deploy", release / "deploy")
        run(sys.executable, "-m", "pip", "wheel", source / "backend", "--wheel-dir", release / "wheels")
        env = os.environ.copy()
        env.update(NEXT_PUBLIC_API_URL="/api/backend", API_PROXY_TARGET="http://127.0.0.1:8080", API_INTERNAL_URL="http://127.0.0.1:8080", NEXT_TELEMETRY_DISABLED="1")
        frontend = source / "frontend"
        run("npm", "ci", "--no-audit", "--no-fund", cwd=frontend, env=env)
        run("npm", "run", "build", cwd=frontend, env=env)
        standalone = frontend / ".next/standalone"
        if not (standalone / "server.js").is_file():
            raise ValueError("Unexpected Next standalone layout; server.js missing")
        shutil.copytree(standalone, release / "frontend")
        shutil.copytree(frontend / ".next/static", release / "frontend/.next/static")
        public = release / "frontend/public"
        if (frontend / "public").exists():
            shutil.copytree(frontend / "public", public, dirs_exist_ok=True)
        public.mkdir(exist_ok=True)
        metadata = {
            "release_id": args.release_id,
            "commit": commit,
            "node": node_version,
            "platform": {"os": "ubuntu", "version": "24.04", "arch": platform.machine(), "python": "3.12"},
        }
        (release / "release.json").write_text(json.dumps(metadata, indent=2) + "\n")
        (public / "deployment.json").write_text(json.dumps({"release_id": args.release_id, "commit": commit}) + "\n")
        (release / "bin").mkdir()
        shutil.copy2(node, release / "bin/node")
        artifact = package(release, output)
        controller = output / "tradejournal-deploy.py"
        shutil.copyfile(release / "deploy/control.py", controller)
        lines = []
        for path in (artifact, controller):
            with path.open("rb") as handle:
                lines.append(f"{hashlib.file_digest(handle, 'sha256').hexdigest()}  {path.name}\n")
        (output / "SHA256SUMS").write_text("".join(lines))
        print(f"Built {artifact} from {commit}")


if __name__ == "__main__":
    main()
