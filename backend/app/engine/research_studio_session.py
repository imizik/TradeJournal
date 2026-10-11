"""R3 single-host session beside explicit cache/store roots, never app jobs/DB."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import threading
import time
import uuid

from app.engine.research_studio import CORE_UNIVERSE, DISCOVERY_END, DISCOVERY_START, FEATURE_UNITS, Observations, parse_definition
from app.engine.research_studio_analysis import canonical_bytes
from app.engine.market_map import ET
from app.engine.research_studio_store import decode_snapshot
from app.engine.research_studio_data import engine_fingerprint


class Busy(ValueError):
    pass


class ResearchSession:
    def __init__(self, source, store):
        self.source, self.store = source, store
        self.observations = None
        self.chart_snapshot = None
        self.key = None
        self.preparation = threading.Lock()
        self.execution = threading.Lock()
        self.worker = None

    @contextmanager
    def _prepare(self):
        if not self.preparation.acquire(blocking=False):
            raise Busy("Research preparation is busy; retry shortly")
        try:
            yield
        finally:
            self.preparation.release()

    def _observations(self, definition, *, fresh=False):
        key = (tuple(sorted(definition.universe)), definition.end)
        if fresh or self.key != key:
            # Drop the old population before allocating a replacement.
            self.observations = None
            self.chart_snapshot = None
            self.key = None
            self.observations = Observations(self.source.snapshot(definition.universe, through=definition.end))
            self.chart_snapshot = self.observations.snapshot
            self.key = key
        return self.observations

    def config(self):
        return {"universe": list(CORE_UNIVERSE), "start": str(DISCOVERY_START), "end": str(DISCOVERY_END),
                "features": dict(FEATURE_UNITS), "enabled": True}

    def preview(self, raw):
        definition = parse_definition(raw)
        with self._prepare():
            began = time.perf_counter()
            result = self._observations(definition).preview(definition)
            return {**result, "elapsed_ms": (time.perf_counter() - began) * 1000}

    def enqueue(self, raw, operation_id, outcome_informed=False):
        definition = parse_definition(raw)
        if type(outcome_informed) is not bool or str(uuid.UUID(operation_id)) != operation_id:
            raise ValueError("canonical operation UUID and boolean provenance required")
        with self._prepare():
            obs = self._observations(definition, fresh=True)
            status = self.store.enqueue(obs.snapshot, definition, operation_id)
            with self.store._root() as fd:
                self.store._immutable(fd, f"submission.{operation_id}.json", canonical_bytes(
                    {"run_id": status["run_id"], "outcome_informed": outcome_informed}))
            return {**status, "definition": definition.canonical()}

    def runs(self):
        with self.store._db() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM run ORDER BY created DESC LIMIT 100")]
            return {"runs": [{**self.store._status(db, r), "definition": self.store._request(db, r)["definition"]} for r in ids]}

    def execute(self):
        # Explicit finite dispatch; startup/restart never replays work.
        if not self.execution.acquire(blocking=False):
            raise Busy("Research worker is already active")
        try:
            with self._prepare():
                # Release warmed features before fork/exec; retain immutable bars.
                self.observations = None
                self.key = None
        except Exception:
            self.execution.release()
            raise
        def work():
            try:
                self.store.work_once()
            finally:
                self.execution.release()
        self.worker = threading.Thread(target=work, name="research-parent", daemon=False)
        self.worker.start()
        return {"status": "dispatched"}

    def _saved_snapshot(self, run_id):
        with self.store._db() as db:
            request = self.store._request(db, run_id)
        with self.store._run(run_id) as fd:
            payload = self.store._read(fd, "snapshot.json.gz")
        if hashlib.sha256(payload).hexdigest() != request["snapshot_sha256"]:
            raise ValueError("immutable prepared snapshot changed")
        if self.observations and self.observations.snapshot.identity == request["data_id"]:
            return self.observations.snapshot
        self.observations = None
        self.key = None
        snapshot = decode_snapshot(payload)
        if snapshot.identity != request["data_id"]:
            raise ValueError("saved snapshot identity mismatch")
        return snapshot

    def chart(self, *, symbol, decision_time, data_id=None, run_id=None, reveal=False, operation_id=None):
        if type(reveal) is not bool:
            raise ValueError("reveal must be a boolean")
        with self._prepare():
            snapshot = self._saved_snapshot(run_id) if run_id else self.chart_snapshot
            if snapshot is None or snapshot.identity != data_id:
                raise ValueError("Chart population expired; preview again or reopen the saved run")
            if snapshot.engine_fingerprint != engine_fingerprint():
                raise ValueError("Saved chart engine changed; saved analysis remains readable")
            moment = datetime.fromisoformat(decision_time)
            # Always validate discovery, timezone, alignment and symbol BEFORE any reveal/artifact.
            observations = self.observations if snapshot is getattr(self.observations, "snapshot", None) else Observations(snapshot)
            self.observations = observations
            self.chart_snapshot = snapshot
            self.key = None if run_id else self.key
            features = observations.features(symbol, moment)
            day = moment.astimezone(ET).date()
            source = next(s for s in snapshot.symbols if s.symbol == symbol)
            bars = [b for b in source.bars if b.time.astimezone(ET).date() == day
                    and (reveal or b.time.timestamp() + 300 <= moment.timestamp())]
            if str(uuid.UUID(operation_id)) != operation_id:
                raise ValueError("canonical inspection UUID required")
            record = {"kind": "chart_inspection", "future_revealed": reveal, "data_id": data_id, "run_id": run_id,
                          "symbol": symbol, "decision_time": moment.astimezone(timezone.utc).isoformat()}
            # Each inspection is an immutable research-owned artifact. Retries
            # must match the same reveal; commit before returning future bars.
            with self.store._root() as fd:
                self.store._immutable(fd, f"inspection.{operation_id}.json", canonical_bytes(record))
            return {"data_id": data_id, "symbol": symbol, "decision_time": moment.astimezone(timezone.utc).isoformat(),
                    "occurrence_id": symbol + ":" + moment.astimezone(timezone.utc).isoformat(),
                    "revealed": reveal, "exposure_id": operation_id,
                    "bars": [{"time": int(b.time.timestamp()), "open": b.open, "high": b.high,
                              "low": b.low, "close": b.close} for b in bars],
                    "features": {k: {"value": v.value, "reasons": list(v.reasons), "unit": FEATURE_UNITS[k]} for k, v in features.items()},
                    "provenance": snapshot.provenance}
