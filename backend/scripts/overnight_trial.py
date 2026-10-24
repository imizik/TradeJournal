"""Finite, invented-data overnight rehearsal using the existing ResearchStore.

No agent dispatch, provider access, application database, or schedule. POSIX only.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.engine.research_studio import Definition, Predicate  # noqa: E402
from app.engine.research_studio_data import DiscoveryCache  # noqa: E402
from app.engine.research_studio_store import ResearchStore, code_identity  # noqa: E402
from scripts.research_studio import read_definition  # noqa: E402
from scripts.seed_research_studio_fixture import seed  # noqa: E402

VERSION = "overnight-fixture-v1"
LIMITS = {"wall_seconds": 120, "concurrent_workers": 1, "assignments": 1,
          "max_attempts": 2, "factory_candidates": 0, "agent_tool_calls": 0,
          "provider_calls": 0, "model_calls": 0, "api_cost_usd": 0}


def now():
    return datetime.now(timezone.utc).isoformat()


def operation(run_id, action):
    return str(uuid.uuid5(uuid.UUID(run_id), action))


def read(path):
    return json.loads(read_definition(path))


def publish(root, name, value):
    """Replace a derived receipt atomically; never follow an existing target."""
    payload = value if isinstance(value, str) else json.dumps(value, indent=2, allow_nan=False) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=".receipt-", dir=root)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, root / name)
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def locked(root):
    fd = os.open(root / "coordinator.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


@contextmanager
def deadline(seconds):
    def expired(*_):
        raise TimeoutError("overnight wall-time budget exhausted")
    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def root_path(path):
    root = Path(path).absolute()
    # Fixture seeding is intentionally restricted to a new disposable temp root.
    # Resolve the OS temp alias, but refuse user-selected symlinks below it.
    raw_temp = Path(tempfile.gettempdir()).absolute()
    temp = raw_temp.resolve()
    if root.is_relative_to(raw_temp):
        root = temp / root.relative_to(raw_temp)
    if root == temp or not root.is_relative_to(temp):
        raise ValueError("trial root must be a child of the system temporary directory")
    for part in (root, *root.parents):
        if part == temp:
            break
        if part.is_symlink():
            raise ValueError("trial root cannot contain symlinks below the temporary directory")
    resolved = root.resolve()
    if resolved.exists():
        info = resolved.stat()
        if not resolved.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("trial root must be an owner-only directory")
    return resolved


def store_for(root):
    for path in (root / "research", root / "fixture", root / "fixture" / "sip"):
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("trial stores must remain inside the private fixture root")
    return ResearchStore(root / "research", source_root=root / "fixture" / "sip")


def report(root, receipt):
    research = receipt.get("research", {})
    result = receipt.get("result_summary")
    state = receipt["state"]
    lines = ["# Overnight report — invented data only", "",
             "## 1. Executive summary", "",
             f"Run `{receipt['run_id']}`: **{state}**.",
             "This is an orchestration rehearsal, not trading evidence.", "",
             "## 2. Research", "",
             f"Assignment: {receipt['assignment']}",
             f"Research run: `{research.get('run_id', 'not submitted')}`; "
             f"attempt {research.get('attempt', 0)}."]
    if result:
        lines += [f"Synthetic 30-minute endpoint: N={result['event_n']}; "
                  f"mean={result['event_mean']}%; baseline={result['baseline_mean']}%; "
                  f"difference={result['difference']} percentage points.",
                  f"Uncertainty unavailable: {result['uncertainty']['unavailable_reason']}.",
                  "No hypothesis accepted or rejected; no Factory validation attempted."]
    else:
        lines += ["No completed result is available. No successful research finding is claimed."]
    lines += ["", "## 3. Engineering", "",
              "No engineering agent dispatched; no code changes, tests or PRs produced by this run.",
              "", "## 4. Data quality", "",
              "Provider: invented local fixture; provider calls: 0. Radar: not assigned.",
              f"Dataset: `{research.get('data_id', 'not prepared')}`.",
              f"Coverage: {json.dumps(receipt.get('coverage', {}), sort_keys=True)}.",
              "", "## 5. Problems and limits", "",
              f"Failure: {receipt.get('failure') or research.get('reason') or 'none recorded'}.",
              f"Retry: {receipt['retry_status']}.",
              f"Limits: {json.dumps(receipt['limits'], sort_keys=True)}.",
              "AI tokens: 0; model/API spend: $0 (no calls).",
              "", "## 6. Decisions (at most three)", "",
              "1. Approve one supervised run on a dedicated nonproduction host after reviewing this rehearsal.",
              "2. Select an explicitly approved discovery-only dataset before adding real-data assignments.",
              "3. Approve scheduling only after restart, duplicate-start and report checks pass on that host.",
              "", "## Provenance", "",
              f"Repository SHA: `{receipt['repository_sha']}`; dirty at creation: {receipt['repository_dirty']}.",
              f"Started: {receipt['started_at']}; last updated: {receipt['updated_at']}.",
              f"Completed/failed: {receipt.get('finished_at') or 'pending'}.",
              "Inputs, outputs, status history and fingerprints: `receipt.json` and `research/ledger.sqlite3`.",
              "The report is owner-only output and must not be used as a hypothesis-generation brief.", ""]
    publish(root, "morning.md", "\n".join(lines))


def save(root, receipt, state, failure=None):
    changed = receipt.get("state") != state or receipt.get("failure") != failure
    receipt.update(state=state, updated_at=now(), failure=failure)
    if state in ("completed", "failed", "cancelled"):
        if changed:
            receipt["finished_at"] = now()
    else:
        receipt["finished_at"] = None
    if changed:
        receipt["history"].append({"state": state, "at": receipt["updated_at"], "failure": failure})
    publish(root, "receipt.json", receipt)
    report(root, receipt)


def initialize(root):
    root.mkdir(mode=0o700)  # Existing roots are never adopted or reset.
    repo = Path(__file__).resolve().parents[2]
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True, timeout=5).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=normal"],
                                        cwd=repo, timeout=5))
    receipt = {"version": VERSION, "run_id": str(uuid.uuid4()), "repository_sha": sha,
               "repository_dirty": dirty, "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "analysis_code_id": code_identity(), "started_at": now(), "limits": LIMITS.copy(),
               "assignment": "Fixed MU/SPY synthetic discovery event analysis, July 3–12, 2023.",
               "approval_required": True, "retry_status": "not needed", "history": [],
               "usage": {"model_calls": 0, "tokens": 0, "api_cost_usd": 0, "provider_calls": 0},
               "artifacts": {"input": "fixture/sip", "store": "research", "report": "morning.md"}}
    with locked(root):
        save(root, receipt, "initializing")
        try:
            with deadline(LIMITS["wall_seconds"]):
                seed(root / "fixture")
                (root / "research").mkdir(mode=0o700)
                definition = Definition((Predicate("minutes", minimum=30),), universe=("MU",),
                                        start=date(2023, 7, 3), end=date(2023, 7, 12),
                                        window_start=600, window_end=600)
                snapshot = DiscoveryCache(root / "fixture" / "sip").snapshot(definition.universe, through=definition.end)
                receipt["coverage"] = {s.symbol: {"sessions": len(s.coverage),
                    "valid_minutes": sum(c.valid_minutes.bit_count() for c in s.coverage),
                    "non_present_sessions": sum(c.state != "present" for c in s.coverage)} for s in snapshot.symbols}
                publish(root, "definition.json", definition.canonical())
                receipt["research"] = store_for(root).enqueue(snapshot, definition, operation(receipt["run_id"], "enqueue"))
            save(root, receipt, "queued")
        except (Exception, KeyboardInterrupt) as exc:
            receipt["retry_status"] = "initialization incomplete; inspect artifacts; use a new trial root"
            save(root, receipt, "failed", f"{type(exc).__name__}: {str(exc)[:300]}")
    return receipt


def execute(root, action, retry_id=None):
    with locked(root):
        receipt = read(root / "receipt.json")
        if receipt["version"] != VERSION or receipt["limits"] != LIMITS:
            raise ValueError("unknown trial version or changed limits")
        if "research" not in receipt:
            save(root, receipt, "failed", "initialization incomplete; inspect artifacts; use a new trial root")
            return receipt
        store = store_for(root)
        # A busy existing ResearchStore raises ValueError. Refuse without
        # overwriting the receipt of a live owner (including an orphan child).
        store.recover()
        status = store.status(receipt["research"]["run_id"])
        if action == "retry":
            if not retry_id or str(uuid.UUID(retry_id)) != retry_id:
                raise ValueError("retry requires a canonical operation UUID")
            if receipt.get("retry_operation") != retry_id:
                if status["status"] not in ("failed", "cancelled"):
                    raise ValueError("retry requires a failed or cancelled research run")
                if status["attempt"] >= LIMITS["max_attempts"]:
                    raise ValueError("trial attempt budget exhausted")
        try:
            if action in ("run", "retry"):
                if receipt["driver_sha256"] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest() or receipt["analysis_code_id"] != code_identity():
                    raise ValueError("trial code changed; preserve this run and create a new trial")
            if action == "retry":
                # Same retry operation is idempotent even after it consumed the last attempt.
                if receipt.get("retry_operation") != retry_id:
                    receipt["retry_operation"] = retry_id
                    publish(root, "receipt.json", receipt)
                if status["attempt"] < LIMITS["max_attempts"]:
                    status = store.control(status["run_id"], "retry", retry_id)
            if action == "run" and status["status"] == "queued":
                receipt["research"] = status
                save(root, receipt, "running")
                with deadline(LIMITS["wall_seconds"]):
                    store.work_once()
                status = store.status(status["run_id"])
            receipt["research"] = status
            receipt["retry_status"] = ("explicit retry required; maximum two attempts" if status["status"] in ("failed", "cancelled")
                                        else "not needed")
            if status["status"] == "completed":
                result = store.result(status["run_id"], operation(receipt["run_id"], "morning-result"))
                receipt["result_summary"] = result["horizons"]["30m"]["percent"]
                receipt["research"] = store.status(status["run_id"])
            else:
                receipt.pop("result_summary", None)
            save(root, receipt, status["status"], status.get("reason"))
        except BlockingIOError:
            raise  # Do not label another live owner's work failed.
        except (Exception, KeyboardInterrupt) as exc:
            receipt.pop("result_summary", None)
            save(root, receipt, "failed", f"{type(exc).__name__}: {str(exc)[:300]}")
        return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "run", "report", "retry"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--operation-id", help="required for explicit retry; reuse for the identical request")
    args = parser.parse_args()
    try:
        root = root_path(args.root)
        receipt = initialize(root) if args.action == "init" else execute(root, args.action, args.operation_id)
        print(json.dumps({"run_id": receipt["run_id"], "state": receipt["state"], "report": str(root / "morning.md")}))
        return 1 if receipt["state"] in ("failed", "cancelled") else 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"Overnight trial refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
