"""Offline side-by-side trial bundle; no host installation or startup."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path, PurePosixPath
import shutil
import tarfile

import advisor_mcp_stage as stage

OWNER_UNITS = ("tradejournal-advisor-owner.socket", "tradejournal-advisor-owner.service")
ROOT = "/opt/tradejournal-advisor-v2"
CONFIG = "/etc/tradejournal-advisor-v2"
STATE = "/var/lib/tradejournal-advisor-v2"
RUN = "/run/tradejournal-advisor-v2"
OWNER_RUN = "/run/tradejournal-advisor-owner-v2"
WEB_ACCOUNT = "tj-advisor-web-owner"
READER_ACCOUNT = "tj-advisor-owner"
FRONTEND = "tradejournal-dot-trial-owner.service"


def add_release(destination, archive, approved):
    stage.exact(archive)
    if stage.digest(archive) != approved:
        raise ValueError("Release archive digest differs from reviewed artifact")
    with tarfile.open(archive) as release:
        members = release.getmembers()
        prefixes = {PurePosixPath(m.name).parts[0] for m in members if m.name}
        if len(prefixes) != 1:
            raise ValueError("Require one release root")
        prefix = prefixes.pop()
        names = set()
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or member.name in names or not (member.isfile() or member.isdir()):
                raise ValueError("Release traversal, duplicate, link or special file refused")
            names.add(member.name)
        metadata = json.load(release.extractfile(prefix + "/release.json"))
        if metadata["platform"] != {"os": "ubuntu", "version": "24.04", "arch": "x86_64", "python": "3.12"} or not metadata["node"].startswith("v22."):
            raise ValueError("Require reviewed Ubuntu 24.04 x86_64 / Node 22 artifact")
        # A newer controller may use an older matching frontend artifact, but
        # only when its entire tracked frontend source is unchanged.
        stage.reviewed_git("diff", "--exit-code", metadata["commit"], "--", "frontend")
        for member in members:
            relative = PurePosixPath(member.name).relative_to(prefix)
            if not relative.parts or relative.parts[0] not in {"frontend", "bin"}:
                continue
            target = destination / str(relative)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with release.extractfile(member) as stream, target.open("xb") as output:
                    shutil.copyfileobj(stream, output)
        for required in ("frontend/server.js", "frontend/.next/server/app/advisor-review/page.js", "bin/node"):
            if not (destination / required).is_file():
                raise ValueError("Compiled owner frontend missing: " + required)
    return metadata


def prepare(destination, *, archive, archive_sha256, wheels, guards):
    stage.stage(destination, wheels=wheels)
    try:
        metadata = add_release(destination, archive, archive_sha256)
        operators = destination / "operator"
        operators.mkdir()
        for name in ("advisor_mcp_stage.py", "advisor_mcp_control.py", "advisor_trial_stage.py", "advisor_trial_control.py"):
            shutil.copyfile(stage.SOURCE / "deploy" / name, operators / name)
        shutil.copyfile(stage.SOURCE / "backend/cloud_advisor_owner.py", destination / "backend/cloud_advisor_owner.py")
        for name in (*stage.UNITS, *OWNER_UNITS):
            text = (stage.TEMPLATES / name).read_text()
            replacements = dict((("/opt/tradejournal-advisor-owner/backend", ROOT + "/backend"),
                    ("/etc/tradejournal-advisor-owner", CONFIG + "/owner"),
                    ("/run/tradejournal-advisor-owner", OWNER_RUN),
                    ("/opt/tradejournal-advisor", ROOT), ("/etc/tradejournal-advisor", CONFIG + "/advisor"),
                    ("/var/lib/tradejournal-advisor", STATE), ("/run/tradejournal-advisor", RUN)))
            text = re.sub("|".join(re.escape(k) for k in replacements), lambda m: replacements[m[0]], text)
            if name.endswith("owner.socket"):
                text = text.replace("SocketGroup=tradejournal", "SocketGroup=" + WEB_ACCOUNT)
            (destination / "units" / name).write_text(text)
        advisor = json.loads((destination / "config/config.json").read_text())
        advisor.update(backend_socket=RUN + "/backend.sock", jwks_file=CONFIG + "/advisor/public-keys.json")
        (destination / "config/config.json").write_text(json.dumps(advisor, indent=2) + "\n")
        owner = json.loads((stage.TEMPLATES / "owner-config.example.json").read_text())
        owner.update(socket_path=OWNER_RUN + "/owner.sock", database_path=STATE + "/fixture.db", binding=advisor["profiles"][0])
        (destination / "config/owner.json").write_text(json.dumps(owner, indent=2) + "\n")
        (destination / "config/frontend.env").write_text("TJ_ADVISOR_OWNER_ENABLED=false\nTJ_ADVISOR_OWNER_SOCKET=" + OWNER_RUN + "/owner.sock\nTJ_ADVISOR_OWNER_SOCKET_UID=0\n")
        (destination / "units/frontend.conf").write_text(
            "[Service]\nDynamicUser=no\nUser=" + WEB_ACCOUNT + "\nGroup=" + WEB_ACCOUNT +
            "\nWorkingDirectory=" + ROOT + "/frontend\nExecStart=\nExecStart=" + ROOT +
            "/bin/node " + ROOT + "/frontend/server.js\nEnvironmentFile=" + CONFIG + "/frontend.env\n")
        proxy = destination / "proxy/Caddyfile.example"
        proxy.write_text(proxy.read_text().replace("/run/tradejournal-advisor/mcp.sock", RUN + "/mcp.sock"))
        (destination / "trial.json").write_text(json.dumps({"format": "advisor-trial-disabled-v1", "guards": guards,
            "artifact_sha256": archive_sha256, "release": metadata}, indent=2) + "\n")
        for path in destination.rglob("*"):
            path.chmod(0o600 if path.is_file() else 0o700)
        manifest = json.loads((destination / "manifest.json").read_text())
        manifest["inventory"] = stage.inventory(destination)
        (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        stage.validate(destination)
        return manifest
    except BaseException:
        shutil.rmtree(destination)  # Only this call's exclusive new staging path.
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--wheels", required=True, type=Path)
    parser.add_argument("--guards", required=True, type=Path, help="Reviewed read-only host guards; no credentials")
    args = parser.parse_args()
    prepare(args.destination, archive=args.archive, archive_sha256=args.archive_sha256,
        wheels=args.wheels, guards=json.loads(args.guards.read_text()))
    print(json.dumps({"manifest_sha256": stage.digest(args.destination / "manifest.json"), "enabled": False}))


if __name__ == "__main__":
    main()
