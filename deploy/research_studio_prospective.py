"""Explicit operator installation for the frozen MU study; not normal app activation."""
import argparse
import ast
import hashlib
import io
import json
import os
import pwd
import shutil
import stat
import subprocess
import sys
import uuid
from pathlib import Path

SOURCE_FILES = (
    "app/__init__.py", "app/engine/__init__.py", "app/engine/market_map.py",
    "app/engine/factory_data.py", "app/engine/factory_rules.py", "app/engine/research_studio.py",
    "app/engine/research_studio_data.py", "app/engine/research_studio_analysis.py",
    "app/engine/research_studio_store.py", "app/engine/research_studio_prospective.py",
    "scripts/research_studio_worker.py", "scripts/research_studio_prospective.py",
)
RUNTIME = Path("/usr/local/lib/tradejournal-research-prospective")
ROOT = Path("/var/lib/tradejournal/data/research-studio/prospective")
WARMUP = Path("/var/lib/tradejournal/data/research-studio/cache/stocks/1Min/sip")
ENV = Path("/etc/tradejournal/research-studio-prospective.env")
UNIT = "tradejournal-research-prospective"
DEPENDENCIES = r'''
import importlib.metadata as metadata
import json
from pathlib import Path
import site
from packaging.requirements import Requirement
base = Path(site.getsitepackages()[0]).resolve()
pending, seen, versions, files = ['numpy', 'httpx'], set(), {}, set()
while pending:
    name = pending.pop()
    canonical = name.lower().replace('_', '-').replace('.', '-')
    if canonical in seen:
        continue
    seen.add(canonical)
    distribution = metadata.distribution(name)
    versions[canonical] = distribution.version
    for item in distribution.files or ():
        file = Path(distribution.locate_file(item)).resolve()
        if file.is_relative_to(base) and file.is_file():
            files.add(str(file.relative_to(base)))
    for requirement in distribution.requires or ():
        parsed = Requirement(requirement)
        if parsed.marker is None or parsed.marker.evaluate({'extra': ''}):
            pending.append(parsed.name)
print(json.dumps({'base': str(base), 'versions': versions, 'files': sorted(files)}))
'''


def copy_environment(source, target):
    """Offline dependency closure from the verified installed environment."""
    graph = json.loads(subprocess.check_output([str(source/"bin/python"), "-c", DEPENDENCIES], text=True))
    base = Path(graph["base"])
    if not base.resolve().is_relative_to(source.resolve()):
        raise ValueError("dependency metadata escaped the installed environment")
    subprocess.run([str(source/"bin/python"), "-m", "venv", "--without-pip", str(target)], check=True)
    destinations = list((target/"lib").glob("python*/site-packages"))
    if len(destinations) != 1:
        raise ValueError("unexpected frozen environment layout")
    for name in graph["files"]:
        file = base/name
        if not file.resolve().is_relative_to(base) or not stat.S_ISREG(file.lstat().st_mode):
            raise ValueError("dependency must be a regular in-environment file")
        dest = destinations[0]/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(file, dest)
    return graph["versions"]


def validate_sources(backend):
    """The allowlist is policy; walk all actual project imports to enforce it."""
    allowed = set(SOURCE_FILES)
    for name in SOURCE_FILES:
        file = backend/name
        if not stat.S_ISREG(file.lstat().st_mode) or not file.resolve().is_relative_to(backend):
            raise ValueError("runtime source must be a regular in-release file")
        for node in ast.walk(ast.parse(file.read_text())):
            modules = [n.name for n in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) and node.module else []
            for module in modules:
                if module == "app" or module.startswith("app."):
                    path = module.replace(".", "/")
                    candidate = path+".py" if (backend/(path+".py")).is_file() else path+"/__init__.py"
                    if candidate not in allowed:
                        raise ValueError("project dependency outside the frozen runtime allowlist")
    return {name: hashlib.sha256((backend/name).read_bytes()).hexdigest() for name in SOURCE_FILES}


def service_unit():
    return f"""[Unit]
Description=Frozen prospective MU market-data study
After=network-online.target
Wants=network-online.target
ConditionPathExists={ROOT}/records/registration.json

[Service]
Type=oneshot
User=tradejournal
Group=tradejournal
Environment=PYTHONNOUSERSITE=1
EnvironmentFile={ENV}
ExecStart={RUNTIME}/backend/.venv/bin/python {RUNTIME}/backend/scripts/research_studio_prospective.py run --records {ROOT}/records --cache {ROOT}/cache/sip --warmup {WARMUP}
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
ReadWritePaths={ROOT}/records {ROOT}/cache
TimeoutStartSec=600
CPUQuota=50%
MemoryMax=1G
"""


def timer_unit():
    return f"""[Unit]
Description=Collect completed MU/SPY sessions for the frozen prospective study

[Timer]
OnCalendar=*-*-* 20:30:00 America/New_York
Persistent=true
RandomizedDelaySec=30
Unit={UNIT}.service

[Install]
WantedBy=timers.target
"""


def _private_file(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "r") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077 or info.st_size>1024*1024:
            raise ValueError("credential input must be a root-owned private regular file")
        return handle.read()


def _directory(path, uid, gid):
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                os.mkdir(part, 0o700, dir_fd=fd)
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        if os.fstat(fd).st_uid not in (0, uid):
            raise ValueError("refusing to adopt another owner's study directory")
        os.fchown(fd, uid, gid)
        os.fchmod(fd, 0o700)
    finally:
        os.close(fd)


def install(release, credentials):
    if os.geteuid() != 0:
        raise ValueError("operator installation requires root")
    release = release.resolve(strict=True)
    if release.parent != Path("/opt/tradejournal/releases"):
        raise ValueError("use an installed verified release")
    backend = release/"backend"
    manifest = validate_sources(backend)
    # Import only the parser from the installed environment, never app settings.
    sys.path.insert(0, str(backend))
    from dotenv import dotenv_values
    values = dotenv_values(stream=io.StringIO(_private_file(credentials)))
    keys = {key: values.get(key) for key in ("ALPACA_API_KEY", "ALPACA_API_SECRET")}
    if not all(keys.values()) or any("\n" in v or "\r" in v or '"' in v or "\\" in v for v in keys.values()):
        raise ValueError("two valid existing Alpaca credentials required")
    if ENV.exists():
        existing = dotenv_values(stream=io.StringIO(_private_file(ENV)))
        if any(existing.get(k) != v for k, v in keys.items()):
            raise ValueError("existing study credentials differ; do not overwrite")
    else:
        fd = os.open(ENV, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write("".join(f'{k}="{v}"\n' for k, v in keys.items()))
    if RUNTIME.exists():
        if json.loads((RUNTIME/"manifest.json").read_text()) != {"release": release.name, "files": manifest}:
            raise ValueError("frozen runtime already exists for another release; do not replace")
    else:
        temporary = RUNTIME.with_name(RUNTIME.name+".pending-"+uuid.uuid4().hex)
        (temporary/"backend").mkdir(parents=True, mode=0o755)
        try:
            for name in SOURCE_FILES:
                target = temporary/"backend"/name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(backend/name, target)
                os.chmod(target, 0o644)
            versions = copy_environment(backend/".venv", temporary/"backend/.venv")
            for directory, directories, files in os.walk(temporary, followlinks=False):
                os.chmod(directory, 0o755)
                for name in files:
                    target = Path(directory)/name
                    if not target.is_symlink():
                        os.chmod(target, 0o755 if target.stat().st_mode & 0o111 else 0o644)
            (temporary/"manifest.json").write_text(json.dumps({"release": release.name, "files": manifest}, sort_keys=True))
            (temporary/"dependencies.json").write_text(json.dumps(versions, sort_keys=True))
            os.rename(temporary, RUNTIME)
        except BaseException:
            shutil.rmtree(temporary)
            raise
    user = pwd.getpwnam("tradejournal")
    for suffix in ("", "records", "cache", "cache/sip", "cache/sip/MU", "cache/sip/SPY"):
        _directory(ROOT/suffix, user.pw_uid, user.pw_gid)
    command = ["runuser", "-u", "tradejournal", "--", str(RUNTIME/"backend/.venv/bin/python"),
               str(RUNTIME/"backend/scripts/research_studio_prospective.py")]
    roots = ["--records", str(ROOT/"records"), "--cache", str(ROOT/"cache/sip"), "--warmup", str(WARMUP)]
    for action in ("register", "seal", "status"):
        subprocess.run(command+[action]+roots, check=True)
    for suffix, text in (("service", service_unit()), ("timer", timer_unit())):
        path = Path("/etc/systemd/system")/f"{UNIT}.{suffix}"
        if path.exists() and path.read_text() != text:
            raise ValueError("existing study unit differs; do not overwrite")
        if not path.exists():
            path.write_text(text)
            os.chmod(path, 0o644)
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "--now", UNIT+".timer"], check=True)
    print("Prospective study installed and scheduled; no new subscription or trading endpoint.")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("install", "disable"))
    p.add_argument("--release", type=Path, default=Path("/opt/tradejournal/current"))
    p.add_argument("--credentials-from", type=Path, default=Path("/etc/tradejournal/backend.env"))
    args = p.parse_args()
    if args.action == "install":
        install(args.release, args.credentials_from)
    else:
        subprocess.run(["systemctl", "disable", "--now", UNIT+".timer"], check=True)
        subprocess.run(["systemctl", "stop", UNIT+".service"], check=True)
        print("Collection stopped; immutable study records retained.")


if __name__ == "__main__":
    main()
