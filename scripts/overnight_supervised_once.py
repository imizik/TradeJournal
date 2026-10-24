"""One supervised fixture rehearsal; no application, provider or model access.

This branch-only harness deliberately stops real worker processes. It is not a
scheduler or a change to ResearchStore's evaluation/recovery implementation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid

REPO = Path(__file__).resolve().parents[1]
CLI = REPO / "backend/scripts/overnight_trial.py"


def stamp():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    os.replace(temporary, path)


def paused_worker(root, marker):
    """Fault injection only: stop the real calculation child with its lock held."""
    sys.path.insert(0, str(REPO / "backend"))
    from scripts import overnight_trial as trial
    from app.engine import research_studio_store as storage
    original = storage.subprocess.Popen

    def pause(*args, **kwargs):
        child = original(*args, **kwargs)
        os.kill(child.pid, signal.SIGSTOP)
        write(marker, {"parent": os.getpid(), "child": child.pid})
        return child

    storage.subprocess.Popen = pause
    trial.execute(root, "run")


def verify(output, *, require_isolation):
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="tj-supervised-")).resolve()
    evidence = {"started_at": stamp(), "state": "running", "checks": [], "commands": [],
                "repository_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
                "python": platform.python_version(), "platform": platform.platform(),
                "provider_calls": 0, "model_calls": 0, "tokens": 0, "api_spend_usd": 0,
                "isolation_required": require_isolation}
    process = None
    child_pid = None

    def check(name, condition):
        evidence["checks"].append({"name": name, "passed": bool(condition), "at": stamp()})
        write(output / "verification.json", evidence)
        if not condition:
            raise AssertionError(name)

    def command(root, action, expected=0, operation_id=None):
        args = [sys.executable, str(CLI), action, "--root", str(root)]
        if operation_id:
            args += ["--operation-id", operation_id]
        result = subprocess.run(args, cwd=REPO, capture_output=True, text=True, timeout=130, check=False)
        evidence["commands"].append({"root": root.name, "action": action, "returncode": result.returncode,
                                     "stdout": result.stdout, "stderr": result.stderr, "at": stamp()})
        check(f"{root.name}/{action} exit {expected}", result.returncode == expected)
        return read(root / "receipt.json")

    def identity(receipt):
        research = receipt["research"]
        return receipt["run_id"], research["run_id"], research["data_id"]

    try:
        if require_isolation:
            check("only loopback network interface", set(os.listdir("/sys/class/net")) == {"lo"})
            with socket.socket() as probe:
                probe.settimeout(1)
                denied = probe.connect_ex(("192.0.2.1", 443))
            evidence["network_probe_errno"] = denied
            check("TEST-NET address has no network route", denied == errno.ENETUNREACH)
            check("non-root evaluator", os.getuid() != 0)
            check("container memory capped at 1 GiB", Path("/sys/fs/cgroup/memory.max").read_text().strip() == "1073741824")
            quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
            check("container CPU capped at one", quota != "max" and int(quota) <= int(period))
            check("no provider or model credentials", not any(
                key for key in os.environ if any(word in key.upper() for word in
                ("TOKEN", "SECRET", "API_KEY", "DATABASE_URL", "GITHUB_", "ACTIONS_"))))

        normal = workspace / "normal"
        command(normal, "init")
        completed = command(normal, "run")
        check("normal completion", completed["state"] == "completed")
        stable = identity(completed)
        original_result = (normal / "research" / completed["research"]["run_id"] / "result.json").read_bytes()
        for action in ("run", "report"):
            repeated = command(normal, action)
            check(f"completed {action} keeps identity/attempt/exposure", identity(repeated) == stable
                  and repeated["research"]["attempt"] == 1 and repeated["research"]["exposures"] == 1)
        check("completed result unchanged", original_result ==
              (normal / "research" / completed["research"]["run_id"] / "result.json").read_bytes())

        recovery = workspace / "recovery"
        queued = command(recovery, "init")
        stable = identity(queued)
        snapshot = recovery / "research" / queued["research"]["run_id"] / "snapshot.json.gz"
        snapshot_sha = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        marker = workspace / "worker.json"
        with (workspace / "injected-worker.log").open("w") as log:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--pause-worker",
                                        str(recovery), str(marker)], cwd=REPO, stdout=log, stderr=log,
                                       start_new_session=True)
            until = time.monotonic() + 20
            while not marker.exists() and time.monotonic() < until and process.poll() is None:
                time.sleep(.02)
            check("real calculation child started", marker.exists())
            child_pid = read(marker)["child"]
            command(recovery, "run", expected=2)  # Coordinator lock held by live parent.
            check("duplicate start leaves running receipt", read(recovery / "receipt.json")["state"] == "running")
            process.kill()
            process.wait(timeout=5)
            command(recovery, "report", expected=2)  # Orphan child still holds worker lock.
            check("surviving child prevents false recovery", read(recovery / "receipt.json")["state"] == "running")
            os.kill(child_pid, signal.SIGKILL)
            child_pid = None
        # Kernel teardown is asynchronous; bounded lock inspection only, no work dispatch.
        sys.path.insert(0, str(REPO / "backend"))
        from scripts.overnight_trial import store_for
        until = time.monotonic() + 5
        while True:
            try:
                store_for(recovery).recover()
                break
            except ValueError as exc:
                if "already active" not in str(exc) or time.monotonic() >= until:
                    raise
                time.sleep(.02)
        failed = command(recovery, "report", expected=1)
        check("dead attempt fails without a result", failed["state"] == "failed"
              and failed["research"]["attempt"] == 1 and "result_summary" not in failed)
        write(workspace / "interrupted-receipt.json", failed)
        (workspace / "interrupted-morning.md").write_bytes((recovery / "morning.md").read_bytes())
        no_replay = command(recovery, "run", expected=1)
        check("restart never automatically retries", no_replay["research"]["attempt"] == 1)
        retry_id = str(uuid.uuid4())
        command(recovery, "retry", operation_id=retry_id)
        repeated = command(recovery, "retry", operation_id=retry_id)
        check("explicit retry UUID is idempotent", repeated["research"]["attempt"] == 2)
        recovered = command(recovery, "run")
        check("retry completes same research/data identity", recovered["state"] == "completed"
              and identity(recovered) == stable and recovered["research"]["attempt"] == 2)
        check("frozen snapshot survives interruption", hashlib.sha256(snapshot.read_bytes()).hexdigest() == snapshot_sha)
        command(recovery, "run")
        last = command(recovery, "report")
        check("recovered run exposed once", last["research"]["exposures"] == 1)
        before = (recovery / "receipt.json").read_bytes()
        command(recovery, "retry", expected=2, operation_id=str(uuid.uuid4()))
        check("refused extra retry preserves completion", (recovery / "receipt.json").read_bytes() == before)
        evidence["normal"] = completed
        evidence["recovered"] = last
        evidence["state"] = "passed"
    except BaseException as exc:
        evidence["state"] = "failed"
        evidence["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
        evidence["finished_at"] = stamp()
        write(output / "verification.json", evidence)
        with tarfile.open(output / "trial-artifacts.tar.gz", "w:gz") as archive:
            archive.add(workspace, arcname="trial")
        if (output / "trial-artifacts.tar.gz").stat().st_size > 128 * 1024 * 1024:
            raise ValueError("trial archive exceeded 128 MiB export bound")
        lines = ["# Supervised Ubuntu fixture trial", "", f"Outcome: **{evidence['state']}**.",
                 f"Repository SHA: `{evidence['repository_sha']}`.",
                 f"Started: {evidence['started_at']}; finished: {evidence['finished_at']}.", "",
                 "Invented MU/SPY discovery data only. No strategy acceptance or trading finding.", "",
                 "## Recovery checks", ""]
        lines += [f"- {'PASS' if c['passed'] else 'FAIL'}: {c['name']}" for c in evidence["checks"]]
        if evidence.get("error"):
            lines += ["", f"Failure: {evidence['error']}"]
        lines += ["", "## Scope and artifacts", "",
                  "Provider/model calls: 0. AI tokens and API spend: 0. No recurring schedule or production change.",
                  "`verification.json` retains command exits, identities, coverage and worker metrics.",
                  "`trial-artifacts.tar.gz` retains both stores, inputs/results, and the interrupted receipt/report.",
                  "The intentional process deaths are fault injections, not unexplained operational failures.",
                  "This verifies process-crash recovery, not host reboot or long-term unattended reliability.",
                  "Further activation still requires an approved dataset, durable storage and separate scheduling approval.", ""]
        (output / "report.md").write_text("\n".join(lines))
    return 0 if evidence["state"] == "passed" else 1


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--pause-worker":
        paused_worker(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--output", type=Path, required=True)
        parser.add_argument("--require-isolation", action="store_true")
        arguments = parser.parse_args()
        sys.exit(verify(arguments.output, require_isolation=arguments.require_isolation))
