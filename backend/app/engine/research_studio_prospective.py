"""Frozen MU prospective study. No provider, app database, orders or Factory ledger."""
from datetime import datetime, time, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys

import numpy as np

from app.engine.market_map import ET
from app.engine.research_studio import (
    Definition, Predicate, Snapshot, SymbolSnapshot, Observations, NEWER_END, PROSPECTIVE_PROTOCOL,
    PROSPECTIVE_START, PROSPECTIVE_END, WARMUP_START, session_dates, session_close,
)
from app.engine.research_studio_analysis import SPEC, canonical_bytes, analyze
from app.engine.research_studio_data import DiscoveryCache, _decode, engine_fingerprint
from app.engine.research_studio_store import ResearchStore, code_identity, encode_snapshot, decode_snapshot

BUDGET = 250 * 1024 * 1024
FREE_RESERVE = 2 * 1024 * 1024 * 1024
SESSION_BYTES = 2 * 1024 * 1024


def definitions():
    return tuple(Definition((Predicate("move_15m_atr", maximum=-.25), Predicate("rvol", minimum=v)),
                            universe=("MU",), start=PROSPECTIVE_START, end=PROSPECTIVE_END, version=3)
                 for v in (1.5, 2))


def protocol():
    return {"id": PROSPECTIVE_PROTOCOL, "start": str(PROSPECTIVE_START), "end": str(PROSPECTIVE_END),
            "definitions": [d.canonical() for d in definitions()], "primary": "1.5x / 30m / percent / event minus ordinary baseline",
            "secondary": "2x; 15m, 60m, session close; prior daily ATR14 units",
            "analysis_spec": SPEC, "feed": "sip", "adjustment": "raw; existing Factory inferred splits, no dividends",
            "review": "after final session collection; no early performance review or adaptive extension",
            "claim": "prospective relative to registration; not proof of globally unseen data or Factory validation"}


def sessions():
    return tuple(d for d in session_dates(PROSPECTIVE_END, version=3) if d >= PROSPECTIVE_START)


def _now(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("aware operator clock required")
    return value.astimezone(ET)


def due_sessions(now):
    now = _now(now)
    return tuple(d for d in sessions() if datetime.combine(d, time(20, 30), ET) <= now)


def _size(fd):
    total = 0
    for name in os.listdir(fd):
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if info.st_uid != os.geteuid() or info.st_mode & 0o022:
            raise ValueError("study files must remain owner-controlled")
        if stat.S_ISDIR(info.st_mode):
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            try:
                total += _size(child)
            finally:
                os.close(child)
        elif stat.S_ISREG(info.st_mode):
            total += info.st_size
        else:
            raise ValueError("study storage refuses links and special files")
    return total


class ProspectiveStudy:
    """All writes stay in separate approved records/cache roots; warm-up is read-only."""

    def __init__(self, records: Path, cache: Path, warmup: Path):
        self.cache = DiscoveryCache(cache, prospective_through=PROSPECTIVE_END)
        self.warmup = DiscoveryCache(warmup, allow_newer_mu=True)
        self.store = ResearchStore(records, source_root=self.cache.root)
        self.cache_store = ResearchStore(self.cache.root, source_root=self.store.root)
        if self.warmup.root.is_relative_to(self.store.root) or self.store.root.is_relative_to(self.warmup.root):
            raise ValueError("study records must not overlap warm-up")
        if self.cache.root.is_relative_to(self.warmup.root) or self.warmup.root.is_relative_to(self.cache.root):
            raise ValueError("future cache must be separate from warm-up")
        for symbol in ("MU", "SPY"):
            with self._cache_root() as fd:
                child = os.open(symbol, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    info = os.fstat(child)
                    if info.st_uid != os.geteuid() or info.st_mode & 0o022:
                        raise ValueError("future symbol directories must be owner-controlled")
                finally:
                    os.close(child)

    def _cache_root(self):
        # Reuse the pinned no-follow root discipline without creating a ledger.
        return self.cache_store._root()

    def _artifact(self, name):
        with self.store._root() as fd:
            try:
                return json.loads(self.store._read(fd, name))
            except FileNotFoundError:
                return None

    def _write(self, name, payload):
        self._capacity(len(payload))
        with self.store._root() as fd:
            self.store._immutable(fd, name, payload)

    def _capacity(self, extra=0):
        with self.store._root() as records, self._cache_root() as cache:
            used = _size(records) + _size(cache)
        if used + extra > BUDGET or shutil.disk_usage(self.store.root).free - extra < FREE_RESERVE:
            raise ValueError("prospective storage budget or free-space reserve reached")
        return used

    def registration(self):
        record = self._artifact("registration.json")
        if record is None or record.get("protocol") != protocol():
            raise ValueError("matching immutable prospective registration required")
        frozen = _now(datetime.fromisoformat(record["frozen_at"]))
        if frozen >= datetime.combine(PROSPECTIVE_START, time(9, 30), ET):
            raise ValueError("study must be registered before its first session opens")
        with self.store._root() as fd:
            payload = self.store._read(fd, "warmup.snapshot.gz")
        if hashlib.sha256(payload).hexdigest() != record["warmup_sha256"]:
            raise ValueError("frozen warm-up changed")
        return record

    def register(self, now):
        with self.store._lock("collection.lock", nonblocking=True):
            if self._artifact("registration.json") is not None:
                return self.registration()
            now = _now(now)
            if now >= datetime.combine(PROSPECTIVE_START, time(9, 30), ET):
                raise ValueError("cannot retrospectively register this study")
            with self._cache_root() as fd:
                if _size(fd):
                    raise ValueError("registration must precede future source collection")
            snapshot = self.warmup.snapshot(("MU",), through=NEWER_END, version=2)
            payload = encode_snapshot(snapshot)
            self._write("warmup.snapshot.gz", payload)
            record = {"protocol": protocol(), "frozen_at": now.astimezone(timezone.utc).isoformat(),
                      "warmup_data_id": snapshot.identity, "warmup_sha256": hashlib.sha256(payload).hexdigest(),
                      "planned_source_files": self._source_files()}
            self._write("registration.json", canonical_bytes(record))
            return record

    def seal(self):
        registration = self.registration()
        if registration.get("planned_source_files") != self._source_files():
            raise ValueError("runtime source differs from the pre-registered study")
        record = self._runtime()
        with self.store._lock("collection.lock", nonblocking=True):
            self._write("runtime-seal.json", canonical_bytes(record))
        return record

    @staticmethod
    def _source_files():
        backend = Path(__file__).resolve().parents[2]
        names = ["app/engine/"+n for n in ("research_studio.py", "research_studio_data.py", "research_studio_analysis.py",
                 "research_studio_store.py", "research_studio_prospective.py", "factory_data.py", "factory_rules.py", "market_map.py")]
        names.extend(("scripts/research_studio_worker.py", "scripts/research_studio_prospective.py"))
        return {n: hashlib.sha256((backend/n).read_bytes()).hexdigest() for n in names}

    @staticmethod
    def _runtime():
        provider = Path(__file__).resolve().parents[2] / "scripts/research_studio_prospective.py"
        return {"engine": engine_fingerprint(), "analysis": code_identity(),
                "collector": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "provider": hashlib.sha256(provider.read_bytes()).hexdigest(),
                "python": sys.version, "numpy": np.__version__}

    def _check_seal(self):
        registration = self.registration()
        expected = self._runtime()
        if registration.get("planned_source_files") != self._source_files() or self._artifact("runtime-seal.json") != expected:
            raise ValueError("prospective runtime changed or is not sealed; operator review required")

    def status(self, now):
        registration = self.registration()
        completed = [d for d in sessions() if self._artifact(f"session.{d}.json") is not None]
        due = due_sessions(now)
        return {"protocol": registration["protocol"]["id"], "frozen_at": registration["frozen_at"],
                "start": str(PROSPECTIVE_START), "end": str(PROSPECTIVE_END), "expected_sessions": len(sessions()),
                "completed_sessions": len(completed), "due_sessions": len(due),
                "missing_sessions": [str(d) for d in due if d not in completed],
                "bytes": self._capacity(), "byte_budget": BUDGET, "review_completed": self._artifact("review.json") is not None}

    def collect(self, fetch, now):
        now = _now(now)
        with self.store._lock("collection.lock", nonblocking=True):
            self._check_seal()
            if self._artifact("terminal-collection.json") is not None:
                return []
            self._capacity()
            terminal = PROSPECTIVE_END in due_sessions(now)
            pending = [d for d in due_sessions(now)[-5:] if self._artifact(f"session.{d}.json") is None]
            attempted = []
            for day in pending[:5]:
                attempt = f"attempt.{day}.{now.date()}.json"
                if self._artifact(attempt) is not None:
                    continue
                payloads = {s: self.cache._read(s, day, version=3) for s in ("MU", "SPY")}
                missing = tuple(s for s, value in payloads.items() if value is None)
                try:
                    if missing:
                        rows = fetch(day, missing)
                        if type(rows) is not dict or set(rows) != set(missing):
                            raise ValueError("provider must return exactly the requested symbols")
                        for symbol in missing:
                            payloads[symbol] = canonical_bytes(rows[symbol])
                    quality = {}
                    for symbol, payload in payloads.items():
                        if len(payload) > SESSION_BYTES:
                            raise ValueError("prospective session exceeded byte bound")
                        _, cov = _decode(payload, day)
                        quality[symbol] = {"missing_minutes": session_close(day)-570-cov.valid_minutes.bit_count(),
                                           "invalid": cov.invalid_rows, "duplicates": cov.duplicate_minutes, "off_grid": cov.off_grid_rows}
                    if any(any(q.values()) for q in quality.values()):
                        self._write(attempt, canonical_bytes({"session": str(day), "state": "incomplete", "coverage": quality}))
                        attempted.append({"session": str(day), "state": "incomplete"})
                        continue
                    receipt = {"session": str(day), "collected_at": now.astimezone(timezone.utc).isoformat(), "source": {}}
                    for symbol, payload in payloads.items():
                        self._capacity(len(payload) if symbol in missing else 0)
                        with self._cache_root() as fd:
                            child = os.open(symbol, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                            try:
                                self.store._immutable(child, f"{day}.json", payload)
                            finally:
                                os.close(child)
                        receipt["source"][symbol] = {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
                    self._write(f"session.{day}.json", canonical_bytes(receipt))
                    self._write(attempt, canonical_bytes({"session": str(day), "state": "complete"}))
                    attempted.append({"session": str(day), "state": "complete"})
                except (ValueError, OSError) as exc:
                    # No provider response, URL or credential is logged by the engine.
                    self._write(attempt, canonical_bytes({"session": str(day), "state": "failed", "error_type": type(exc).__name__}))
                    if terminal:
                        self._write("terminal-collection.json", canonical_bytes({"state": "closed_with_gap", "at": now.isoformat()}))
                    raise ValueError("prospective collection failed; inspect bounded attempt status") from None
            if terminal:
                self._write("terminal-collection.json", canonical_bytes({"state": "closed", "at": now.isoformat()}))
            return attempted

    def review(self, now):
        if PROSPECTIVE_END not in due_sessions(now):
            raise ValueError("performance review is not due before the final session closes")
        with self.store._lock("collection.lock", nonblocking=True):
            self._check_seal()
            previous = self._artifact("review.json")
            if previous is not None:
                return previous
            exposure = {"kind": "scheduled_prospective_review", "protocol": PROSPECTIVE_PROTOCOL,
                        "source_start": str(WARMUP_START), "source_end": str(PROSPECTIVE_END),
                        "cohort_start": str(PROSPECTIVE_START), "Factory_validation": False}
            self._write("review-exposure.json", canonical_bytes(exposure))
            with self.store._root() as fd:
                warmup = decode_snapshot(self.store._read(fd, "warmup.snapshot.gz"))
            reader = DiscoveryCache(self.cache.root, prospective_through=PROSPECTIVE_END)
            if reader._root_identity != self.cache._root_identity:
                raise ValueError("future cache root changed")
            raw_read = reader._read
            def committed_read(symbol, day, *, version=1):
                receipt = self._artifact(f"session.{day}.json") if day >= PROSPECTIVE_START else None
                if receipt is None:
                    return None  # Interrupted/uncommitted bytes never supply a feature or outcome.
                expected = receipt["source"][symbol]
                payload = raw_read(symbol, day, version=version)
                if payload is None or (hashlib.sha256(payload).hexdigest(), len(payload)) != (expected["sha256"], expected["bytes"]):
                    raise ValueError("future payload differs from its immutable session receipt")
                return payload
            reader._read = committed_read
            future = reader.snapshot(("MU",), through=PROSPECTIVE_END, version=3)
            symbols = tuple(SymbolSnapshot(old.symbol, old.bars + new.bars,
                            old.coverage + tuple(c for c in new.coverage if c.day >= PROSPECTIVE_START))
                            for old, new in zip(warmup.symbols, future.symbols, strict=True))
            manifest = warmup.manifest + tuple(r for r in future.manifest if r[1] >= str(PROSPECTIVE_START))
            snapshot = Snapshot(PROSPECTIVE_END, symbols, manifest, engine_fingerprint(), source_version=3)
            report = {"protocol": PROSPECTIVE_PROTOCOL, "data_id": snapshot.identity, "runs": [],
                      "interpretation": "fixed prospective study; secondary outcomes exploratory; no trading or Factory validation claim"}
            observations = Observations(snapshot)
            packed = encode_snapshot(snapshot)
            results = []
            for definition in definitions():
                result = analyze(observations, definition, code_identity())
                result["interpretation"] = report["interpretation"]
                results.append(result)
                report["runs"].append({"run_id": result["run_id"], "volume_threshold": definition.predicates[1].minimum,
                                       "primary_30m_percent": result["horizons"]["30m"]["percent"]})
            payloads = [canonical_bytes(r) for r in results]
            self._capacity(len(packed) + sum(map(len, payloads)) + len(canonical_bytes(report)))
            self._write("review.snapshot.gz", packed)
            for result, payload in zip(results, payloads, strict=True):
                self._write(f"result.{result['run_id']}.json", payload)
            self._write("review.json", canonical_bytes(report))
            return report
