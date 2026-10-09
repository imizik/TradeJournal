"""Prepare the separately approved, sample-only Dot trial on the existing VPS.

This does not publish an HTTPS route. Validate the private services and their
namespace isolation before adding the separate Caddy hostname.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
from datetime import datetime, timezone

ROOT = Path("/opt/tradejournal-dot-trial")
STATE = Path("/var/lib/tradejournal-dot-trial")
CONFIG = Path("/etc/tradejournal-dot-trial")
API = "tradejournal-dot-trial-api.service"
RELEASES = Path("/opt/tradejournal/releases")
UNIT_DIR = Path("/etc/systemd/system")
SOCKET_PROXY = Path("/usr/lib/systemd/systemd-socket-proxyd")
SYMBOLS = ["SPY", "QQQ", "IWM", "NVDA", "AAPL", "TSLA", "RNXT", "RCAT", "MU", "NBIS"]


def run(*args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def write(path, value, mode=0o600, created=None):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    if created is not None:
        created.append(path)
    with os.fdopen(descriptor, "w") as target:
        target.write(value)


class Installation:
    """Track only artifacts created by this invocation for failure cleanup."""
    def __init__(self):
        self.roots = []
        self.unit_paths = []
        self.user_attempted = False

    def __enter__(self):
        return self

    def mkdir(self, path, mode):
        path.mkdir(mode=mode)
        self.roots.append(path)

    def __exit__(self, kind, error, traceback):
        if kind is None:
            return False
        try:
            if self.unit_paths:
                names = [path.name for path in self.unit_paths]
                # Never remove files/state while any owned process can run.
                run("systemctl", "disable", "--now", *names, capture_output=True, text=True)
                run("systemctl", "stop", *names, capture_output=True, text=True)
            if self.user_attempted and subprocess.run(
                    ["getent", "passwd", "tj-dot-trial"], capture_output=True).returncode == 0:
                run("userdel", "tj-dot-trial", capture_output=True, text=True)
            for path in self.unit_paths:
                path.unlink()
            if self.unit_paths:
                run("systemctl", "daemon-reload")
            for path in reversed(self.roots):
                shutil.rmtree(path)
        except Exception as cleanup_error:
            raise RuntimeError("Trial installation failed and rollback is incomplete; inspect the retained trial artifacts before retrying") from cleanup_error
        return False


def units(runtime):
    common = """NoNewPrivileges=yes
PrivateTmp=yes
PrivateNetwork=yes
ProtectSystem=strict
ProtectHome=yes
ProtectProc=invisible
RestrictNamespaces=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
CapabilityBoundingSet=
UMask=0077
InaccessiblePaths=/etc/tradejournal /var/lib/tradejournal /var/backups/tradejournal
TasksMax=64
CPUQuota=50%
"""
    found = {API: f"""[Unit]
Description=TradeJournal isolated sample-data API
After=network.target
[Service]
Type=simple
User=tj-dot-trial
Group=tj-dot-trial
WorkingDirectory={runtime}/backend
EnvironmentFile={CONFIG}/access-backend.env
EnvironmentFile={CONFIG}/trial-runtime.env
ExecStart={runtime}/backend/.venv/bin/python -m uvicorn dot_trial_app:build_app --factory --host 127.0.0.1 --port 8091
Restart=on-failure
RestartSec=5
ReadWritePaths={STATE}
MemoryMax=640M
{common}[Install]
WantedBy=multi-user.target
"""}
    for profile, port in (("assistant", 3101), ("owner", 3102)):
        name = f"tradejournal-dot-trial-{profile}.service"
        found[name] = f"""[Unit]
Description=TradeJournal sample trial {profile} frontend
Requires={API}
After={API}
JoinsNamespaceOf={API}
[Service]
Type=simple
DynamicUser=yes
WorkingDirectory={runtime}/frontend
EnvironmentFile={CONFIG}/access-{profile}.env
Environment=HOSTNAME=127.0.0.1 PORT={port} API_INTERNAL_URL=http://127.0.0.1:8091 API_PROXY_TARGET=http://127.0.0.1:8091 NEXT_PUBLIC_API_URL=/api/backend
ExecStart={runtime}/bin/node {runtime}/frontend/server.js
Restart=on-failure
RestartSec=5
InaccessiblePaths={CONFIG} {STATE}
MemoryMax=384M
{common}[Install]
WantedBy=multi-user.target
"""
        bridge = f"tradejournal-dot-trial-{profile}-bridge"
        found[f"{bridge}.socket"] = f"""[Unit]
Description=Loopback frontend bridge for sample trial {profile}
[Socket]
ListenStream=127.0.0.1:{port}
Accept=no
[Install]
WantedBy=sockets.target
"""
        found[f"{bridge}.service"] = f"""[Unit]
Description=Namespace bridge for sample trial {profile} frontend
Requires={API} {name}
After={API} {name}
JoinsNamespaceOf={API}
[Service]
Type=notify
DynamicUser=yes
ExecStart=/usr/lib/systemd/systemd-socket-proxyd --connections-max=64 127.0.0.1:{port}
{common}"""
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--frontend-archive", type=Path, required=True)
    parser.add_argument("--fixture-file", type=Path, required=True)
    parser.add_argument("--control-file", type=Path, required=True)
    parser.add_argument("--assistant-origin", required=True)
    parser.add_argument("--owner-origin", required=True)
    args = parser.parse_args()
    install(args)


def install(args):
    if os.geteuid() != 0:
        raise ValueError("Run as root on the approved trial VPS")
    release = args.release.resolve(strict=True)
    metadata = json.loads((release / "release.json").read_text())
    if not release.is_relative_to(RELEASES) or not metadata["commit"].startswith("6a2f5a50d092"):
        raise ValueError("Trial requires the verified auth release used by this setup")
    if any(path.exists() or path.is_symlink() for path in (ROOT, STATE, CONFIG)):
        raise ValueError("Trial already exists; refusing to overwrite its data or credentials")
    if subprocess.run(["getent", "passwd", "tj-dot-trial"], capture_output=True).returncode == 0:
        raise ValueError("Trial user already exists")
    if not SOCKET_PROXY.is_file():
        raise ValueError("Namespace socket proxy is unavailable")
    from urllib.parse import urlsplit
    for origin in (args.assistant_origin, args.owner_origin):
        parsed = urlsplit(origin)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            raise ValueError("Trial needs canonical HTTPS origins")
    if args.assistant_origin == args.owner_origin:
        raise ValueError("Owner and assistant trial origins must differ")
    planned_units = units(ROOT / "runtime")
    if any((UNIT_DIR / name).exists() or (UNIT_DIR / name).is_symlink() for name in planned_units):
        raise ValueError("Trial unit already exists; refusing to overwrite it")
    with Installation() as owned:
        owned.mkdir(ROOT, 0o755)
        owned.mkdir(STATE, 0o700)
        owned.mkdir(CONFIG, 0o700)
        runtime = ROOT / "runtime"
        runtime.mkdir(mode=0o755)
        # Explicit exclusions prevent runtime symlinks from copying real state.
        ignored = shutil.ignore_patterns("data", ".env", "credentials.json", "token.json", "__pycache__")
        shutil.copytree(release / "backend", runtime / "backend", ignore=ignored, symlinks=True)
        shutil.copytree(release / "bin", runtime / "bin", symlinks=True)
        shutil.copytree(release / "deploy", runtime / "deploy", symlinks=True)
        frontend = runtime / "frontend"
        # Retain the verified Linux dependencies: local build output contains only
        # portable compiled JS/assets, never macOS-native node_modules.
        shutil.copytree(release / "frontend", frontend, symlinks=True, ignore=shutil.ignore_patterns("cache"))
        shutil.rmtree(frontend / ".next")
        import tarfile
        with tarfile.open(args.frontend_archive) as archive:
            if any(member.name.startswith("node_modules/") for member in archive.getmembers()):
                raise ValueError("Trial frontend archive must not replace Linux dependencies")
            archive.extractall(frontend, filter="data")
        if not (frontend / "server.js").is_file():
            raise ValueError("Standalone frontend is missing")
        for cache in frontend.glob(".next/cache"):
            if cache.is_symlink():
                cache.unlink()
            elif cache.is_dir():
                shutil.rmtree(cache)
        shutil.copyfile(args.fixture_file, runtime / "backend/dot_trial_app.py")
        shutil.copyfile(args.control_file, runtime / "deploy/dot_trial_control.py")
        data = STATE / "data"
        data.mkdir(mode=0o700)
        (runtime / "backend/data").symlink_to(data)
        write(STATE / ".sample-installation", "Isolated synthetic TradeJournal sample installation\n")
        database_url = f"sqlite:///{data}/trial.db"
        env = {"PATH": os.environ["PATH"], "DATABASE_URL": database_url, "MIGRATION_DATABASE_URL": database_url,
               "TJ_ACCESS_SAMPLE_DATA": "true"}
        python = runtime / "backend/.venv/bin/python"
        run(python, runtime / "backend/scripts/seed_dev_data.py", "--database-url", database_url,
            cwd=runtime / "backend", env=env, capture_output=True, text=True)
        run(python, runtime / "deploy/access-config.py", "--directory", CONFIG,
            "--owner-origin", args.owner_origin, "--assistant-origin", args.assistant_origin,
            "--sample-data", env=env, capture_output=True, text=True)
        assistant_file = CONFIG / "access-assistant.env"
        assistant_file.write_text(assistant_file.read_text().replace("TJ_ASSISTANT_ENABLED=false", "TJ_ASSISTANT_ENABLED=true"))
        settings = {"DATABASE_URL": database_url, "MIGRATION_DATABASE_URL": database_url,
            "TJ_DOT_TRIAL_ENABLED": "true", "APP_ENV": "dot_sample_trial", "JOB_EXECUTION_MODE": "external",
            "JOB_LOCK_DIR": str(STATE / "job-locks"), "CAPTURE_STORAGE_DIR": str(STATE / "captures"),
            "CAPTURE_TRANSCRIBER": "off", "QUOTES_PROVIDER": "fixture", "PYTHONUNBUFFERED": "1"}
        flags = ("GMAIL_WATCH_AUTOSTART", "GMAIL_LISTENER_ENABLED", "WEBULL_LISTENER_AUTOSTART",
            "LEVEL_ALERTS_AUTOSTART", "PRACTICE_AGENT_ENABLED", "PRACTICE_SCHEDULE_ENABLED")
        secrets = ("TRADIER_API_KEY", "ALPACA_API_KEY", "ALPACA_API_SECRET", "POLYGON_API_KEY",
            "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "WEBULL_USERNAME", "WEBULL_PASSWORD", "NTFY_URL")
        settings.update({key: "false" for key in flags})
        settings.update({key: "" for key in secrets})
        write(CONFIG / "trial-runtime.env", "".join(f"{key}={value}\n" for key, value in settings.items()))
        seed_script = r'''
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from sqlmodel import Session
from app.database import engine
from app.engine import decisions, paper, practice, access
from app.models import JobRun, PracticeRun, PracticeOpportunity
from app.engine.chart_math import ET
now = datetime.now(timezone.utc).replace(tzinfo=None)
day = now.replace(tzinfo=timezone.utc).astimezone(ET).date()
with Session(engine) as db:
    job = JobRun(job_type="sample_fixture", status="succeeded", total=2, done=2, finished_at=now)
    db.add(job)
    db.flush()
    run = PracticeRun(session_key="sample-trial:" + day.isoformat(), day=day, job_id=job.id,
        mode="manual", comparison="assisted", status="prepared", deadline=now + timedelta(hours=1),
        finished_at=now, policy_version=paper.POLICY_VERSION, policy_hash=paper.POLICY_HASH,
        calendar_json=json.dumps({"status":"unavailable","description":"Synthetic fixture, no live calendar"}),
        brief_json=json.dumps([{"title":"Sample-data trial", "text":"Invented journal and price data. Read-only UI inspection; no live Shadow Isaac run, alerts or paper positions.", "sources":[]}]))
    db.add(run)
    db.commit()
    for symbol in ("SPY", "QQQ"):
        context, _ = decisions.freeze_context(db, "sample-context:" + symbol, symbol,
            {"symbol":symbol, "data_source":"sample_fixture", "missing":["Synthetic demo only"], "recent_minute_bars":[]})
        opp = PracticeOpportunity(run_id=run.id, symbol=symbol, context_id=context.id,
            benchmark_json=json.dumps({"status":"unavailable","reason":"No live benchmark in sample trial"}))
        db.add(opp)
        db.commit()
        practice.choose(db, opp, {"decision":"skip","rationale":"Invented sample choice for evidence reopening; not a live trading decision."})
    key = access.create_assistant(db, "trader-jo", {"symbols":SYMBOLS,"run_ids":[str(run.id)],"journal_read":True})
    credential = {"identifier":"trader-jo","key":key,"origin":ASSISTANT_ORIGIN,"run_id":str(run.id)}
    path = Path("/etc/tradejournal-dot-trial/trader-jo-credential.json")
    descriptor = __import__('os').open(path, __import__('os').O_WRONLY | __import__('os').O_CREAT | __import__('os').O_EXCL, 0o600)
    with __import__('os').fdopen(descriptor,'w') as target:
        target.write(json.dumps(credential))
'''
        seed_script = f"SYMBOLS={SYMBOLS!r}\nASSISTANT_ORIGIN={args.assistant_origin!r}\n" + seed_script
        run(python, "-c", seed_script, cwd=runtime / "backend", env=env, capture_output=True, text=True)
        owned.user_attempted = True
        run("useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin", "tj-dot-trial")
        account = pwd.getpwnam("tj-dot-trial")
        for path in [STATE, *STATE.rglob("*")]:
            os.chown(path, account.pw_uid, account.pw_gid)
        for name, content in planned_units.items():
            write(UNIT_DIR / name, content, 0o644, created=owned.unit_paths)
        manifest = {"base_commit": metadata["commit"], "fixture_sha256": hashlib.sha256(args.fixture_file.read_bytes()).hexdigest(),
            "control_sha256": hashlib.sha256(args.control_file.read_bytes()).hexdigest(),
            "frontend_sha256": hashlib.sha256(args.frontend_archive.read_bytes()).hexdigest(), "assistant_origin": args.assistant_origin,
            "owner_origin": args.owner_origin, "created_at": datetime.now(timezone.utc).isoformat(), "published": False}
        write(CONFIG / "manifest.json", json.dumps(manifest, indent=2))
        run("systemctl", "daemon-reload")
        run("systemctl", "enable", "--now", API, "tradejournal-dot-trial-assistant.service", "tradejournal-dot-trial-owner.service",
            "tradejournal-dot-trial-assistant-bridge.socket", "tradejournal-dot-trial-owner-bridge.socket", capture_output=True, text=True)
        print("Isolated sample trial prepared. No public HTTPS route added. No secrets printed.")


if __name__ == "__main__":
    main()
