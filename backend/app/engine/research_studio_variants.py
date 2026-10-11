"""R4 lineage, paired exposures and append-only conclusions in the research root."""
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

from app.engine.research_studio_analysis import HORIZONS, UNITS, analysis_id, canonical_bytes
from app.engine.research_studio_store import MAX_BYTES, code_identity

NOTE_NAME = re.compile(r"conclusion\.([0-9a-f-]{36})\.json\Z")


class Variants:
    def __init__(self, store):
        self.store = store

    def _request(self, run_id, *, completed=True):
        state = self.store.status(run_id)
        if completed and state["status"] != "completed":
            raise ValueError("a completed research run is required")
        with self.store._db() as db:
            return self.store._request(db, run_id)

    def _artifact(self, name):
        with self.store._root() as fd:
            try:
                raw = self.store._read(fd, name)
            except FileNotFoundError:
                return None
        with self.store._db() as db:
            hashes = [json.loads(r[0])["sha256"] for r in db.execute(
                "SELECT detail FROM event WHERE kind='r4_artifact'")
                if json.loads(r[0])["artifact"] == name]
        if hashes != [hashlib.sha256(raw).hexdigest()]:
            raise ValueError("immutable R4 artifact changed or was not committed")
        return json.loads(raw)

    def _publish(self, name, record, run_id):
        raw = canonical_bytes(record)
        digest = hashlib.sha256(raw).hexdigest()
        with self.store._root() as fd:
            self.store._immutable(fd, name, raw)
        with self.store._db(write=True) as db:
            found = [json.loads(r[0])["sha256"] for r in db.execute(
                "SELECT detail FROM event WHERE kind='r4_artifact'")
                if json.loads(r[0])["artifact"] == name]
            if found and found != [digest]:
                raise ValueError("immutable R4 artifact conflicts")
            if not found:
                state = self.store._status(db, run_id)
                self.store._event(db, run_id, state["attempt"], "r4_artifact",
                    canonical_bytes({"artifact": name, "sha256": digest}).decode())

    def parent(self, run_id):
        self.store.status(run_id)  # Validate identity before deriving a filename.
        record = self._artifact(f"parent.{run_id}.json")
        if record is not None and (record["variant_run_id"] != run_id or
                                   record["kind"] != "predicate_variant"):
            raise ValueError("invalid saved variant lineage")
        return record["parent_run_id"] if record else None

    def definition(self, parent_id, definition):
        request = self._request(parent_id)
        if request["code_id"] != code_identity():
            raise ValueError("parent execution version changed; run a new question before creating variants; saved analysis remains readable")
        parent = request["definition"]
        child = definition.canonical()
        if {k: v for k, v in parent.items() if k != "predicates"} != {
                k: v for k, v in child.items() if k != "predicates"}:
            raise ValueError("a variant changes conditions only; keep the parent's targets, dates and window")
        return request

    def _reserve(self, operation_id, record, enqueue_id=None):
        if str(uuid.UUID(operation_id)) != operation_id:
            raise ValueError("canonical operation UUID required")
        anchor = record.get("parent") or record["run_ids"][0]
        expected = (enqueue_id, "enqueue") if enqueue_id else (anchor, "r4:" + record["action"])
        with self.store._db() as db:
            previous = db.execute("SELECT run_id,action FROM operation WHERE id=?", (operation_id,)).fetchone()
            if previous is not None and previous != expected:
                raise ValueError("operation id reused for another research action")
        if previous is not None and enqueue_id and self._artifact(f"r4-operation.{operation_id}.json") is None:
            raise ValueError("operation id reused for another research action")
        self._publish(f"r4-operation.{operation_id}.json", record, anchor)
        if not enqueue_id:
            with self.store._db(write=True) as db:
                self.store._operation(db, operation_id, *expected)

    def enqueue(self, definition, parent_id, operation_id, outcome_informed):
        parent = self.definition(parent_id, definition)
        child_id = analysis_id(definition, parent["data_id"], code_identity())
        if child_id == parent_id:
            raise ValueError("change a condition before running a variant")
        with self.store._run(parent_id) as fd:
            payload = self.store._read(fd, "snapshot.json.gz")
        if hashlib.sha256(payload).hexdigest() != parent["snapshot_sha256"]:
            raise ValueError("immutable prepared snapshot changed")
        with self.store._lock("variants.lock", nonblocking=True):
            ancestor = parent_id
            for _ in range(100):
                if ancestor == child_id:
                    raise ValueError("variant lineage cannot form a cycle")
                ancestor = self.parent(ancestor)
                if ancestor is None:
                    break
            else:
                raise ValueError("variant ancestry exceeds the bounded limit")
            prior = self._artifact(f"r4-operation.{operation_id}.json")
            informed = prior["recorded_outcome_informed"] if prior and "recorded_outcome_informed" in prior else (
                outcome_informed or self.store.status(parent_id)["exposures"] > 0)
            self._reserve(operation_id, {"action": "variant", "parent": parent_id,
                          "variant": child_id, "definition": definition.canonical(),
                          "outcome_informed": outcome_informed,
                          "recorded_outcome_informed": informed}, child_id)
            self._publish(f"parent.{child_id}.json", {
                    "kind": "predicate_variant", "parent_run_id": parent_id,
                    "variant_run_id": child_id, "data_id": parent["data_id"]}, parent_id)
            status = self.store._enqueue_prepared(parent["data_id"], payload, definition, operation_id)
            self._publish(f"submission.{operation_id}.json", {
                    "run_id": child_id, "outcome_informed": informed}, child_id)
            return {**status, "definition": definition.canonical(), "parent_run_id": parent_id}

    def _result(self, run_id):
        self._request(run_id)
        with self.store._db() as db:
            expected = db.execute("SELECT result_sha FROM run WHERE id=?", (run_id,)).fetchone()[0]
        with self.store._run(run_id) as fd:
            raw = self.store._read(fd, "result.json")
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("immutable research result changed")
        return json.loads(raw)

    def comparison(self, parent_id, variant_id, operation_id):
        if parent_id == variant_id or self.parent(variant_id) != parent_id:
            raise ValueError("compare a variant with its saved parent")
        requests = [self._request(r) for r in (parent_id, variant_id)]
        if requests[0]["data_id"] != requests[1]["data_id"] or any(
                requests[0][key] != requests[1][key] for key in ("code_id", "analysis_spec", "numpy_version")):
            raise ValueError("comparison requires identical frozen data and analysis definitions")
        name = f"comparison.{parent_id}.{variant_id}.json"
        with self.store._lock("variants.lock", nonblocking=True):
            self._reserve(operation_id, {"action": "compare", "parent": parent_id, "variant": variant_id})
            result = self._artifact(name)
            if result is None:
                if requests[0]["code_id"] != code_identity():
                    raise ValueError("comparison engine changed; archived analysis remains readable")
                results = [self._result(r) for r in (parent_id, variant_id)]
                # The child needs the saved selection/outcomes/estimates, not
                # duplicate data manifests or preview feature dictionaries.
                inputs = [{"run_id": r["run_id"], "analysis_code_id": r["analysis_code_id"],
                    "population": {"definition": r["population"]["definition"],
                        "data_id": r["population"]["data_id"],
                        "events": [{"symbol": e["symbol"], "decision_time": e["decision_time"]}
                                   for e in r["population"]["events"]]},
                    "events": r["events"], "horizons": r["horizons"]} for r in results]
                with self.store._run(parent_id) as fd:
                    payload = self.store._read(fd, "snapshot.json.gz")
                if hashlib.sha256(payload).hexdigest() != requests[0]["snapshot_sha256"]:
                    raise ValueError("immutable prepared snapshot changed")
                script = Path(__file__).resolve().parents[2] / "scripts/research_studio_compare.py"
                envelope = canonical_bytes({"snapshot": base64.b64encode(payload).decode(),
                                            "results": inputs, "parent": os.getpid()})
                if len(envelope) > MAX_BYTES:
                    raise ValueError("comparison envelope exceeds bound")
                with self.store._lock("worker.lock", nonblocking=True) as worker_fd:
                    try:
                        child = subprocess.run([sys.executable, str(script)], input=envelope,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, pass_fds=(worker_fd,))
                    except subprocess.TimeoutExpired as exc:
                        raise ValueError("comparison exceeded the bounded 60-second limit") from exc
                if child.returncode != 0 or len(child.stdout) > MAX_BYTES:
                    raise ValueError("isolated comparison failed")
                result = json.loads(child.stdout)
                code = hashlib.sha256((Path(__file__).with_name("research_studio_comparison.py").read_bytes()
                                       + script.read_bytes() + code_identity().encode())).hexdigest()
                result["comparison_code_id"] = code
                result["comparison_id"] = hashlib.sha256(canonical_bytes({
                    "parent": parent_id, "variant": variant_id, "code": code})).hexdigest()
                self._publish(name, result, variant_id)
            if result["parent_run_id"] != parent_id or result["variant_run_id"] != variant_id or result["data_id"] != requests[0]["data_id"]:
                raise ValueError("saved comparison identity differs")
            # Commit both exposures before any comparison or result bytes return.
            namespace = uuid.UUID(operation_id)
            parent = self.store.result(parent_id, str(uuid.uuid5(namespace, "parent-result")))
            variant = self.store.result(variant_id, str(uuid.uuid5(namespace, "variant-result")))
            return {**result, "parent_result": parent, "variant_result": variant}

    def _notes(self):
        with self.store._root() as fd:
            names = [name for name in os.listdir(fd) if NOTE_NAME.fullmatch(name)]
            if len(names) > 1000:
                raise ValueError("conclusion history exceeds the bounded limit")
        return [self._artifact(name) for name in names]

    def notes(self, run_ids):
        ids = self._note_scope(run_ids)
        with self.store._lock("variants.lock", nonblocking=True):
            return {"notes": sorted((n for n in self._notes() if n["run_ids"] == ids),
                                    key=lambda n: n["sequence"])}

    def _note_scope(self, run_ids):
        if type(run_ids) is not list or len(run_ids) not in (1, 2) or len(set(run_ids)) != len(run_ids):
            raise ValueError("one run or a parent/variant pair is required")
        for run_id in run_ids:
            self._request(run_id)
        if len(run_ids) == 2 and self.parent(run_ids[1]) != run_ids[0]:
            raise ValueError("conclusion pair must be a variant and its parent")
        return run_ids

    def conclude(self, run_ids, verdict, reason, horizon, unit, operation_id):
        ids = self._note_scope(run_ids)
        if verdict not in ("Promising", "Rejected", "Unclear") or type(reason) is not str or not reason.strip() or len(reason) > 2000:
            raise ValueError("choose a verdict and a reason of 1–2000 characters")
        if horizon not in HORIZONS or unit not in UNITS:
            raise ValueError("unknown conclusion horizon or return unit")
        references = [self._request(r) for r in ids]
        comparison = self._artifact(f"comparison.{ids[0]}.{ids[1]}.json") if len(ids) == 2 else None
        if len(ids) == 2 and comparison is None:
            raise ValueError("reveal the paired comparison before concluding")
        record = {"action": "conclusion", "run_ids": ids, "verdict": verdict,
                  "reason": reason.strip(), "horizon": horizon, "unit": unit}
        with self.store._lock("variants.lock", nonblocking=True):
            self._reserve(operation_id, record)
            name = f"conclusion.{operation_id}.json"
            note = self._artifact(name)
            if note is None:
                notes = self._notes()
                if len(notes) >= 1000:
                    raise ValueError("conclusion history is full")
                note = {**record, "operation_id": operation_id,
                    "sequence": max((n["sequence"] for n in notes), default=0)+1,
                    "created": datetime.now(timezone.utc).isoformat(),
                    "references": [{k: r[k] for k in ("run_id", "data_id", "code_id", "analysis_spec", "numpy_version")}
                                   for r in references],
                    "comparison_id": comparison["comparison_id"] if comparison else None,
                    "outcome_informed": any(self.store.status(r)["exposures"] > 0 for r in ids)}
                self._publish(name, note, ids[-1])
            return note
