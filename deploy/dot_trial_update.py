"""Update only the approved isolated sample runtime, with rollback on failure."""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path, PurePosixPath
from urllib.request import urlopen

RUNTIME = Path("/opt/tradejournal-dot-trial/runtime")
CONFIG = Path("/etc/tradejournal-dot-trial")
UNIT_DIR = Path("/etc/systemd/system")
CLOUD_SOCKET = "tradejournal-d1-reads.socket"
CLOUD_UNITS = (CLOUD_SOCKET, "tradejournal-d1-reads.service")
SOURCE_FILES = frozenset({"backend/app/engine/decisions.py", "backend/app/engine/access.py",
    "backend/app/engine/paper.py", "backend/app/engine/sample_replay.py",
    "backend/app/engine/sample_practice.py", "backend/app/routers/practice.py", "backend/app/routers/access.py",
    "backend/app/access_manifest.py", "backend/app/access_middleware.py", "backend/app/main.py",
    "backend/app/engine/cloud_practice_access.py", "backend/app/routers/cloud_practice.py",
    "backend/cloud_mcp_d0.py", "backend/cloud_mcp_d1_common.py",
    "backend/app/engine/market_practice.py", "deploy/dot_market_capture.py", "deploy/dot_market_import.py",
    "backend/app/engine/historical_replay.py", "deploy/dot_historical_capture.py", "deploy/dot_historical_import.py",
    "backend/dot_trial_app.py", "deploy/dot_trial_control.py", "deploy/dot_trial_seed.py"})
FRONTEND_FILES = (".next", "server.js", "package.json", "public")
SERVICES = tuple(f"tradejournal-dot-trial-{part}.service" for part in ("api", "assistant", "owner"))
SOCKETS = tuple(f"tradejournal-dot-trial-{part}-bridge.socket" for part in ("assistant", "owner"))
BRIDGES = tuple(f"tradejournal-dot-trial-{part}-bridge.service" for part in ("assistant", "owner"))


def run(*args):
    return subprocess.run(list(args), check=True, capture_output=True, text=True)


def cloud_reads_state():
    """Older trials have no D1 units; preserve only an already-active entrance."""
    units = tuple(name for name in CLOUD_UNITS if (UNIT_DIR / name).is_file())
    active = CLOUD_SOCKET in units and run("systemctl", "show", CLOUD_SOCKET,
        "--property=ActiveState", "--value").stdout.strip() in {"active", "activating"}
    return units, active


def stop_cloud_reads(units):
    if units:
        run("systemctl", "stop", *units)


def restore_cloud_reads(active):
    if active:
        # Caller must finish source replacement/rollback and readiness first.
        run("systemctl", "start", CLOUD_SOCKET)


def check_target():
    if os.geteuid() != 0 or RUNTIME.is_symlink() or not RUNTIME.is_dir() or CONFIG.is_symlink():
        raise ValueError("Run as root on the existing isolated sample installation")
    # The root updater uses only stdlib; app dependencies belong to the pinned venv.
    subprocess.run([str(RUNTIME / "backend/.venv/bin/python"), "-c",
        "from dot_trial_control import environment\nfrom dot_trial_app import validate_environment\nvalidate_environment(environment())"],
        cwd=RUNTIME / "backend", env={"PATH": os.defpath, "PYTHONPATH": str(RUNTIME / "deploy")},
        check=True, capture_output=True, text=True)
    if not json.loads((CONFIG / "manifest.json").read_text()).get("published"):
        raise ValueError("This update requires the existing approved trial")


def extract(archive_path, destination, *, backend):
    with tarfile.open(archive_path) as archive:
        members = archive.getmembers()
        if len(members) > 5000 or sum(member.size for member in members) > (4_000_000 if backend else 300_000_000):
            raise ValueError("Trial archive exceeds the bounded update size")
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                raise ValueError("Unsafe trial archive member")
            if backend:
                if not member.isfile() or member.name not in SOURCE_FILES:
                    raise ValueError("Backend archive exceeds the selected update scope")
            elif not path.parts or path.parts[0] not in FRONTEND_FILES or "node_modules" in path.parts:
                raise ValueError("Frontend archive must retain the verified Linux dependencies")
        if backend and {member.name for member in members} != SOURCE_FILES:
            raise ValueError("Backend archive must contain every selected source file exactly once")
        if len({member.name for member in members}) != len(members):
            raise ValueError("Duplicate trial archive member")
        archive.extractall(destination, filter="data")
    if backend:
        for name in SOURCE_FILES:
            compile((destination / name).read_text(), name, "exec")
    elif not (destination / "server.js").is_file() or not (destination / ".next").is_dir():
        raise ValueError("Compiled standalone frontend is missing")


def remove(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def ready():
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            for port in (3101, 3102):
                with urlopen(f"http://127.0.0.1:{port}/login", timeout=2) as response:
                    if response.status != 200:
                        raise ValueError("Trial login unavailable")
                # Both entrances must exercise their gateway, backend and database.
                # Anonymous /health through a gateway is intentionally unauthorized.
                with urlopen(f"http://127.0.0.1:{port}/api/access/challenge", timeout=2) as response:
                    if response.status != 200 or not isinstance(json.load(response).get("csrf"), str):
                        raise ValueError("Trial backend challenge unavailable")
            pids = [run("systemctl", "show", name, "--property=MainPID", "--value").stdout.strip() for name in SERVICES]
            networks = [Path(f"/proc/{pid}/ns/net").readlink() for pid in pids]
            if len(set(networks)) == 1 and networks[0] != Path("/proc/1/ns/net").readlink():
                health = run("nsenter", "--target", pids[0], "--net", "--", "python3", "-c",
                    "import json\nfrom urllib.request import urlopen\n"
                    "with urlopen('http://127.0.0.1:8091/health', timeout=2) as response: print(json.dumps(json.load(response)))")
                if json.loads(health.stdout).get("status") == "ok":
                    return
        except (OSError, ValueError, subprocess.CalledProcessError):
            pass
        time.sleep(.5)
    raise RuntimeError("Trial did not become ready in its isolated network namespace")


def update(backend_archive, frontend_archive, commit, *, enable_sample_replay=False, enable_market_decisions=False,
           enable_historical_replay=False):
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("Record the exact reviewed source commit")
    check_target()
    env_file = CONFIG / "trial-runtime.env"
    original_env = env_file.read_bytes()
    manifest_file = CONFIG / "manifest.json"
    original_manifest = manifest_file.read_bytes()
    if env_file.resolve() != env_file or manifest_file.resolve() != manifest_file:
        raise ValueError("Trial configuration cannot traverse a symlink")
    # Root-private staging retains a recovery snapshot after successful updates.
    stage = Path(tempfile.mkdtemp(prefix="sample-update-", dir=RUNTIME.parent))
    stage.chmod(0o700)
    source, frontend, backup = stage / "source", stage / "frontend", stage / "backup"
    try:
        source.mkdir()
        frontend.mkdir()
        backup.mkdir()
        extract(backend_archive, source, backend=True)
        extract(frontend_archive, frontend, backend=False)
        snapshots = {}
        for name in SOURCE_FILES:
            path = RUNTIME / name
            if path.resolve() != path:
                raise ValueError("Trial source cannot traverse a symlink")
            snapshots[name] = path.read_bytes() if path.exists() else None
        for name in FRONTEND_FILES:
            if (RUNTIME / "frontend" / name).resolve() != RUNTIME / "frontend" / name:
                raise ValueError("Trial frontend cannot be a symlink")
    except BaseException:
        shutil.rmtree(stage)
        raise
    moved = []
    processed = []
    (backup / "trial-runtime.env").write_bytes(original_env)
    (backup / "manifest.json").write_bytes(original_manifest)
    for name, content in snapshots.items():
        if content is not None:
            path = backup / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    manifest = json.loads(original_manifest)
    manifest.update(decision_trial_commit=commit, fixture_sha256=hashlib.sha256((source / "backend/dot_trial_app.py").read_bytes()).hexdigest(),
        control_sha256=hashlib.sha256((source / "deploy/dot_trial_control.py").read_bytes()).hexdigest())
    manifest.setdefault("updates", []).append({"commit": commit, "recovery_directory": str(stage),
        "backend_sha256": hashlib.sha256(Path(backend_archive).read_bytes()).hexdigest(),
        "frontend_sha256": hashlib.sha256(Path(frontend_archive).read_bytes()).hexdigest()})
    cloud_units, cloud_active = cloud_reads_state()
    try:
        stop_cloud_reads(cloud_units)
        run("systemctl", "stop", *SOCKETS, *BRIDGES, *SERVICES)
    except BaseException:
        run("systemctl", "start", *SERVICES, *SOCKETS)
        ready()
        restore_cloud_reads(cloud_active)
        raise
    try:
        for name in FRONTEND_FILES:
            path = RUNTIME / "frontend" / name
            if path.exists():
                shutil.move(path, backup / name)
                moved.append(name)
            processed.append(name)
            incoming = frontend / name
            if incoming.exists():
                shutil.move(incoming, path)
        for name in SOURCE_FILES:
            path = RUNTIME / name
            path.write_bytes((source / name).read_bytes())
            path.chmod(0o644)
        lines = [line for line in original_env.decode().splitlines() if not line.startswith("TJ_SAMPLE_DECISION_WRITES=")]
        if enable_sample_replay:
            lines = [line for line in lines if not line.startswith("TJ_SAMPLE_REPLAY_ENABLED=")]
            lines.append("TJ_SAMPLE_REPLAY_ENABLED=true")
        if enable_market_decisions:
            lines = [line for line in lines if not line.startswith("TJ_MARKET_DECISION_WRITES=")]
            lines.append("TJ_MARKET_DECISION_WRITES=true")
        if enable_historical_replay:
            lines = [line for line in lines if not line.startswith("TJ_HISTORICAL_REPLAY_ENABLED=")]
            lines.append("TJ_HISTORICAL_REPLAY_ENABLED=true")
        env_file.write_text("\n".join([*lines, "TJ_SAMPLE_DECISION_WRITES=true"]) + "\n")
        run("systemctl", "start", *SERVICES, *SOCKETS)
        ready()
        manifest_file.write_text(json.dumps(manifest, indent=2))
        restore_cloud_reads(cloud_active)
    except BaseException:
        # A failed stop is surfaced; retain snapshots instead of modifying live state.
        stop_cloud_reads(cloud_units)
        run("systemctl", "stop", *SOCKETS, *BRIDGES, *SERVICES)
        for name in processed:
            remove(RUNTIME / "frontend" / name)
            if name in moved:
                shutil.move(backup / name, RUNTIME / "frontend" / name)
        for name, content in snapshots.items():
            path = RUNTIME / name
            if content is None:
                remove(path)
            else:
                path.write_bytes(content)
        env_file.write_bytes(original_env)
        manifest_file.write_bytes(original_manifest)
        run("systemctl", "start", *SERVICES, *SOCKETS)
        ready()
        restore_cloud_reads(cloud_active)
        raise
    print("Sample runtime updated and ready. Production configuration and credentials unchanged.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-archive", type=Path, required=True)
    parser.add_argument("--frontend-archive", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--enable-sample-replay", action="store_true", help="Explicitly enable the approved sample-only replay")
    parser.add_argument("--enable-market-decisions", action="store_true", help="Explicitly enable the isolated real-market decision handoff")
    parser.add_argument("--enable-historical-replay", action="store_true", help="Explicitly enable the isolated historical exercise")
    args = parser.parse_args()
    update(args.backend_archive, args.frontend_archive, args.commit, enable_sample_replay=args.enable_sample_replay,
        enable_market_decisions=args.enable_market_decisions, enable_historical_replay=args.enable_historical_replay)


if __name__ == "__main__":
    main()
