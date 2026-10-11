"""Finite R4 comparison child; supplied frozen inputs only, no source/store/DB."""
import base64
import gc
import json
import os
import resource
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.engine.research_studio import Observations, parse_definition
from app.engine.research_studio_store import MAX_BYTES, code_identity, decode_snapshot
from app.engine.research_studio_data import engine_fingerprint
from app.engine.research_studio_comparison import compare
from app.engine.research_studio_analysis import analysis_id, canonical_bytes

if __name__ == "__main__":
    started = time.perf_counter()
    raw = sys.stdin.buffer.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("comparison envelope exceeds bound")
    envelope = json.loads(raw)
    del raw
    snapshot = decode_snapshot(base64.b64decode(envelope["snapshot"], validate=True))
    results, parent = envelope["results"], envelope["parent"]
    del envelope
    definitions = [parse_definition(r["population"]["definition"]) for r in results]
    code = code_identity()
    if snapshot.engine_fingerprint != engine_fingerprint() or any(
            r["analysis_code_id"] != code or analysis_id(d, snapshot.identity, code) != r["run_id"]
            for d, r in zip(definitions, results)):
        raise ValueError("comparison input identity changed")
    gc.collect()
    result = compare(Observations(snapshot),
                     definitions, results, cancel=lambda: os.getppid() != parent)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result["worker_metrics"] = {"elapsed_seconds": time.perf_counter()-started,
                                "peak_rss_bytes": peak if sys.platform=="darwin" else peak*1024}
    payload = canonical_bytes(result)
    if len(payload) > MAX_BYTES:
        raise ValueError("comparison response exceeds bound")
    sys.stdout.buffer.write(payload)
