"""R3 single-host session beside explicit cache/store roots, never app jobs/DB."""
from contextlib import contextmanager
from datetime import datetime, timezone
import gc
import hashlib
import threading
import time
import uuid

from app.engine.research_studio import CORE_UNIVERSE, DISCOVERY_END, DISCOVERY_START, FEATURE_UNITS, NEWER_PERIODS, NEWER_PROTOCOL, WARMUP_START, Observations, parse_definition
from app.engine.research_studio_analysis import canonical_bytes
from app.engine.market_map import ET
from app.engine.research_studio_store import decode_snapshot
from app.engine.research_studio_data import engine_fingerprint
from app.engine.research_studio_variants import Variants


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
        self.last_submission = None
        self.variants = Variants(store)

    @contextmanager
    def _prepare(self):
        if not self.preparation.acquire(blocking=False):
            raise Busy("Research preparation is busy; retry shortly")
        try:
            yield
        finally:
            self.preparation.release()

    def _observations(self, definition, *, fresh=False, parent_run_id=None):
        if parent_run_id:
            self.variants.definition(parent_run_id, definition)
        if definition.version == 2:
            if not getattr(self.source, "allow_newer_mu", False):
                raise ValueError("newer MU study is not operator-approved")
            # Commit the source scope before reading newer bytes. This conservatively
            # marks all loaded warm-up/analysis dates exposed for future research.
            with self.store._root() as fd:
                self.store._immutable(fd, f"source-exposure.{definition.end}.json", canonical_bytes({
                    "protocol": NEWER_PROTOCOL, "symbols": ["MU", "SPY"],
                    "source_start": str(WARMUP_START), "source_end": str(definition.end),
                    "kind": "exploratory_source_exposure", "independent_validation": False}))
        key = (definition.version, tuple(sorted(definition.universe)), definition.end, parent_run_id)
        if fresh or self.key != key:
            # Drop the old population before allocating a replacement.
            self.observations = None
            self.chart_snapshot = None
            self.key = None
            snapshot = self._saved_snapshot(parent_run_id) if parent_run_id else (self.source.snapshot(definition.universe, through=definition.end) if definition.version == 1 else self.source.snapshot(definition.universe, through=definition.end, version=2))
            self.observations = Observations(snapshot)
            self.chart_snapshot = self.observations.snapshot
            self.key = key
        return self.observations

    def config(self):
        result = {"universe": list(CORE_UNIVERSE), "start": str(DISCOVERY_START), "end": str(DISCOVERY_END),
                "features": dict(FEATURE_UNITS), "enabled": True, "capabilities": ["variants", "conclusions"]}

        if getattr(self.source, "allow_newer_mu", False):
            result["newer_mu"] = {"protocol": NEWER_PROTOCOL,
                "periods": [{"label": label, "start": str(start), "end": str(end)} for label, start, end in NEWER_PERIODS]}
        return result

    def preview(self, raw, parent_run_id=None):
        definition = parse_definition(raw)
        with self._prepare():
            began = time.perf_counter()
            result = self._observations(definition, parent_run_id=parent_run_id).preview(definition)
            return {**result, "elapsed_ms": (time.perf_counter() - began) * 1000}

    def enqueue(self, raw, operation_id, outcome_informed=False):
        definition = parse_definition(raw)
        if type(outcome_informed) is not bool or str(uuid.UUID(operation_id)) != operation_id:
            raise ValueError("canonical operation UUID and boolean provenance required")
        with self._prepare():
            with self.store._lock("variants.lock", nonblocking=True):
                if self.variants._artifact(f"r4-operation.{operation_id}.json") is not None:
                    raise ValueError("operation id reused for another research action")
                return self._enqueue_question(definition, operation_id, outcome_informed)

    def _enqueue_question(self, definition, operation_id, outcome_informed):
        obs = self._observations(definition, fresh=True)
        status = self.store.enqueue(obs.snapshot, definition, operation_id)
        self.last_submission = {"run_id": status["run_id"], "data_id": status["data_id"]}
        with self.store._root() as fd:
            self.store._immutable(fd, f"submission.{operation_id}.json", canonical_bytes(
                {"run_id": status["run_id"], "outcome_informed": outcome_informed}))
        return {**status, "definition": definition.canonical()}

    def variant(self, raw, parent_run_id, operation_id, outcome_informed=False):
        definition = parse_definition(raw)
        if type(outcome_informed) is not bool or str(uuid.UUID(operation_id)) != operation_id:
            raise ValueError("canonical operation UUID and boolean provenance required")
        with self._prepare():
            self.variants.definition(parent_run_id, definition)
            # Reuse verified immutable parent bytes; submission needs neither
            # the preview grid nor another decoded/re-serialized snapshot.
            self.observations = self.chart_snapshot = self.key = None
            gc.collect()
            status = self.variants.enqueue(definition, parent_run_id, operation_id, outcome_informed)
            self.last_submission = {"run_id": status["run_id"], "data_id": status["data_id"]}
            return status

    def compare(self, parent_run_id, variant_run_id, operation_id):
        with self._prepare():
            # Comparison has its own finite child in the existing execution lane.
            # Drop warmed feature/snapshot objects before forking that child.
            self.observations = self.chart_snapshot = self.key = None
            gc.collect()
            return self.variants.comparison(parent_run_id, variant_run_id, operation_id)

    def runs(self):
        with self.store._db() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM run ORDER BY created DESC LIMIT 100")]
            runs = [{**self.store._status(db, r), "definition": self.store._request(db, r)["definition"]} for r in ids]
        return {"runs": [{**r, "parent_run_id": self.variants.parent(r["run_id"])} for r in runs]}

    def describe(self, run_id):
        status = self.store.status(run_id)
        with self.store._db() as db:
            definition = self.store._request(db, run_id)["definition"]
        return {**status, "definition": definition, "parent_run_id": self.variants.parent(run_id)}

    def execute(self):
        # Explicit finite dispatch; startup/restart never replays work.
        if not self.execution.acquire(blocking=False):
            raise Busy("Research worker is already active")
        if not self.preparation.acquire(blocking=False):
            self.execution.release()
            raise Busy("Research preparation is busy; retry shortly")
        self.observations = None
        self.chart_snapshot = None
        self.key = None
        gc.collect()
        released = False
        def child_started():
            nonlocal released
            if not released:
                self.preparation.release()
                released = True
        def work():
            try:
                # Keep preparation out of the fork window. Afterwards chart/
                # preview requests may rebuild independently from frozen data.
                self.store.work_once(on_child_started=child_started)
            finally:
                child_started()
                self.execution.release()
        self.worker = threading.Thread(target=work, name="research-parent", daemon=False)
        try:
            self.worker.start()
        except Exception:
            child_started()
            self.execution.release()
            raise
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
            frozen_run = run_id
            if frozen_run is None and self.chart_snapshot is None and self.last_submission:
                if self.last_submission["data_id"] == data_id:
                    frozen_run = self.last_submission["run_id"]
            snapshot = self._saved_snapshot(frozen_run) if frozen_run else self.chart_snapshot
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
            quality = observations._quality[symbol]
            coverage = quality.coverage.get(day)
            series = quality.series
            # Analysis and chart share the same frozen inferred-split basis.
            # Partial resamples remain absent, never apparently complete candles.
            indices = [i for i, stamp in enumerate(series.time) if stamp.astimezone(ET).date() == day
                       and coverage.bucket_complete(series.minute[i])
                       and (reveal or stamp.timestamp() + 300 <= moment.timestamp())] if series and coverage else []
            bars = [{"time": int(series.time[i].timestamp()), "open": series.open[i], "high": series.high[i],
                     "low": series.low[i], "close": series.close[i]} for i in indices]
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
                    "bars": bars,
                    "features": {k: {"value": v.value, "reasons": list(v.reasons), "unit": FEATURE_UNITS[k]} for k, v in features.items()},
                    "provenance": snapshot.provenance}
