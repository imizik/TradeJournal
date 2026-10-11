"""Private calculation child: parent supplies a bounded immutable envelope."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import signal
import resource
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.engine.research_studio import Observations, parse_definition  # noqa: E402
from app.engine.research_studio_analysis import analyze, analysis_id, canonical_bytes  # noqa: E402
from app.engine.research_studio_data import engine_fingerprint  # noqa: E402
from app.engine.research_studio_store import MAX_BYTES, code_identity, decode_snapshot  # noqa: E402


def main():
    started = time.perf_counter()
    cancelled = False
    def stop(signum, frame):
        nonlocal cancelled
        cancelled = True
    signal.signal(signal.SIGTERM, stop)
    try:
        envelope = sys.stdin.buffer.read(MAX_BYTES + 1)
        if len(envelope) > MAX_BYTES:
            raise ValueError("worker envelope exceeded bound")
        raw = json.loads(envelope)
        request = raw["request"]
        definition = parse_definition(request["definition"])
        if request["code_id"] != code_identity() or analysis_id(definition, request["data_id"], request["code_id"]) != request["run_id"]:
            raise ValueError("worker input identity changed")
        snapshot = decode_snapshot(base64.b64decode(raw["snapshot"], validate=True))
        if snapshot.engine_fingerprint != engine_fingerprint() or snapshot.identity != request["data_id"]:
            raise ValueError("worker snapshot identity changed")
        parent = raw["parent"]
        del envelope, raw
        result = analyze(Observations(snapshot), definition, request["code_id"],
                         cancel=lambda: cancelled or os.getppid() != parent)
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        metrics = {"elapsed_seconds": time.perf_counter() - started,
                   "peak_rss_bytes": rss * 1024 if sys.platform.startswith("linux") else rss}
        payload = canonical_bytes({"result": result, "worker_metrics": metrics})
        if len(payload) > MAX_BYTES:
            raise ValueError("worker result exceeded bound")
        sys.stdout.buffer.write(payload)
    except Exception as exc:
        print(f"research calculation refused ({type(exc).__name__})", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
