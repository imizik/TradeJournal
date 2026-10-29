"""Replay and live drivers: packets in, forecasts out, one JSONL record each.

A run directory holds ``run.json`` (the pinned configuration), ``records.jsonl``
(one line per session x checkpoint x agent x variant), ``packets/`` (the exact
packets sent, for audit) and the scored ``report.json`` / ``report.txt``.
Re-running the same command resumes: finished records are skipped, and model
answers come from the response cache, so nothing is billed twice.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import json
from pathlib import Path
import threading
import time

from . import contract
from .contract import CHECKPOINTS_ET, UTC, VARIANTS

PACKAGE = Path(__file__).resolve().parent
# Baselines read structured features only; headlines cannot change a rule, so
# they always see the market packet.
BASELINE_VARIANT = "market"


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha(value):
    data = value if isinstance(value, bytes) else _canonical(value).encode()
    return hashlib.sha256(data).hexdigest()


def source_fingerprint():
    """Hash of the lab's code and prompt, so a run cannot silently mix versions."""
    files = sorted(PACKAGE.glob("*.py")) + sorted(PACKAGE.glob("prompt*.txt"))
    return {p.name: _sha(p.read_bytes()) for p in files if p.exists()}


class Run:
    """Append-only record store for one run directory."""

    def __init__(self, directory, config):
        config = json.loads(json.dumps(config))  # compare as stored (tuples become lists)
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "packets").mkdir(exist_ok=True)
        pinned = self.dir / "run.json"
        if pinned.exists():
            saved = json.loads(pinned.read_text())
            if saved != config:
                changed = sorted(k for k in set(saved) | set(config) if saved.get(k) != config.get(k))
                raise SystemExit(f"{self.dir} was started with different settings ({', '.join(changed)}); "
                                 "use a new run directory.")
        else:
            pinned.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        self.path = self.dir / "records.jsonl"
        self.lock = threading.Lock()
        self.records = {}
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                if line.strip():
                    row = json.loads(line)
                    self.records[self.key(row)] = row

    @staticmethod
    def key(row):
        return (row["date"], row["checkpoint_et"], row["agent"], row["variant"])

    def has(self, key):
        return key in self.records

    def add(self, row, packet):
        with self.lock:
            with self.path.open("a") as stream:
                stream.write(_canonical(row) + "\n")
                stream.flush()
            with (self.dir / "packets" / f"{row['date']}.jsonl").open("a") as stream:
                stream.write(_canonical({"key": list(self.key(row)), "packet": packet}) + "\n")
            self.records[self.key(row)] = row

    def rows(self):
        return list(self.records.values())


def _record(day, checkpoint, agent, variant, packet, result):
    return {
        "date": day,
        "checkpoint_et": checkpoint,
        "agent": agent,
        "variant": variant,
        "packet_sha256": _sha(packet),
        "status": result["status"],
        "forecast": result.get("forecast"),
        "error": result.get("error"),
        "latency_s": result.get("latency_s"),
        "cost_usd": result.get("cost_usd"),
        "cache_hit": result.get("cache_hit", False),
        "usage": result.get("usage"),
        "model_reported": result.get("model_reported"),
        "recorded_at": datetime.now(UTC).isoformat(),
    }


def _baseline_result(fn, packet):
    started = time.monotonic()
    try:
        forecast = contract.validate_forecast(fn(packet))
        status, error = "ok", None
    except Exception as exc:  # a broken rule is a recorded failure, not a crash
        forecast, status, error = None, "error", type(exc).__name__
    return {"status": status, "forecast": forecast, "error": error,
            "latency_s": round(time.monotonic() - started, 6), "cost_usd": 0.0}


def _prior(row):
    forecast = row["forecast"]
    return {"checkpoint_et": row["checkpoint_et"], "action": forecast["action"],
            "symbol": forecast["symbol"], "spy_p_up": forecast["spy_p_up"],
            "qqq_p_up": forecast["qqq_p_up"]}


# Provider failures that a later invocation may ask again; an answered but
# schema-invalid forecast ("invalid") is the model's result and is kept.
RETRYABLE = {"error", "timeout"}
MAX_ERRORS_PER_INVOCATION = 20


def _charge(row):
    """Spend a record adds: 0 for cache hits and failed requests; an answered
    request with unknown cost counts as unbounded, so the cap stops the run."""
    if row.get("cache_hit") or row["status"] in RETRYABLE:
        return 0.0
    cost = row.get("cost_usd")
    return cost if isinstance(cost, (int, float)) else float("inf")


class Budget:
    """Caps TOTAL recorded spend in the run directory, across invocations, and
    stops after repeated provider errors (an outage or a rejected request shape)."""

    def __init__(self, cap_usd, rows=()):
        self.cap = cap_usd
        self.spent = sum(_charge(r) for r in rows if r["status"] not in ("missed", "data_missing"))
        self.errors = 0
        self.lock = threading.Lock()

    def open(self):
        with self.lock:
            return (self.cap is None or self.spent < self.cap) and self.errors < MAX_ERRORS_PER_INVOCATION

    def charge(self, row):
        with self.lock:
            self.spent += _charge(row)
            self.errors += row["status"] in RETRYABLE


def replay(run_dir, days, *, sessions, model=None, model_name=None, variants=VARIANTS,
           baselines=None, workers=4, max_cost_usd=None, log=print):
    """Replay ``days`` (already-loaded ``sessions``: {date: SessionData}).

    The model's chain within one session and variant is sequential (it sees its
    own earlier decisions); separate chains run in parallel.
    """
    from .packet import build_packet

    baselines = baselines or {}
    run = Run(run_dir, {
        "kind": "replay",
        "days": list(days),
        "variants": list(variants),
        "model": model_name,
        "model_settings": getattr(model, "settings", None),
        "baselines": sorted(baselines),
        "baseline_variant": BASELINE_VARIANT,
        "source": source_fingerprint(),
        "contract": {"checkpoints": CHECKPOINTS_ET, "entry_delay": contract.ENTRY_DELAY_MINUTES,
                     "horizons": contract.HORIZONS_MINUTES, "cost_bps": contract.ROUND_TRIP_COST_BPS,
                     "news_lag_s": contract.NEWS_LAG_SECONDS},
    })
    budget = Budget(max_cost_usd, run.rows())

    for day in days:
        for checkpoint in CHECKPOINTS_ET:
            packet = None
            for name, fn in sorted(baselines.items()):
                key = (day, checkpoint, name, BASELINE_VARIANT)
                if run.has(key):
                    continue
                packet = packet or build_packet(sessions[day], checkpoint, BASELINE_VARIANT)
                run.add(_record(day, checkpoint, name, BASELINE_VARIANT, packet,
                                _baseline_result(fn, packet)), packet)

    def chain(day, variant):
        prior = []
        redo = False  # an earlier answer changed, so later packets (prior_decisions) differ
        for checkpoint in CHECKPOINTS_ET:
            key = (day, checkpoint, model_name, variant)
            row = run.records.get(key)
            if row is None or redo or row["status"] in RETRYABLE:
                if not budget.open():
                    return "budget"
                packet = build_packet(sessions[day], checkpoint, variant, prior)
                result = model.forecast(packet)
                new = _record(day, checkpoint, model_name, variant, packet, result)
                budget.charge(new)
                redo = redo or row is not None and new["status"] == "ok"
                row = new
                run.add(row, packet)
            if row["status"] == "ok":
                prior.append(_prior(row))
        return "done"

    if model is not None:
        jobs = [(d, v) for d in days for v in variants]
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            outcomes = list(pool.map(lambda job: chain(*job), jobs))
        if "budget" in outcomes:
            if budget.errors >= MAX_ERRORS_PER_INVOCATION:
                log(f"Stopped after {budget.errors} provider errors; check the error labels in "
                    "records.jsonl, then re-run the same command to retry them.")
            else:
                log(f"Stopped at the cost cap: ${budget.spent:.2f} recorded in this run directory. "
                    "--max-cost-usd caps the run's TOTAL spend; raise it to continue.")
    return run


def write_report(run, sessions):
    from .evaluate import render_text, score

    report = score(run.rows(), sessions)
    (run.dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    text = render_text(report)
    (run.dir / "report.txt").write_text(text + "\n")
    return text


def estimate(days, sessions, variants, model):
    """Calls a full run makes and its input size, without calling anything.

    An upper bound: it ignores what a run directory or the response cache
    already holds, and packets without prior_decisions are slightly smaller."""
    from .packet import build_packet, render_user_message

    prompt_chars = len(getattr(model, "prompt_text", "") or "")
    calls, chars = 0, 0
    for day in days:
        for variant in variants:
            for checkpoint in CHECKPOINTS_ET:
                calls += 1
                chars += prompt_chars + len(render_user_message(build_packet(sessions[day], checkpoint, variant)))
    return {"calls": calls, "approx_input_tokens": int(chars / 3.5)}


def live(run_dir, day, *, model, model_name, variant="full", feed="sip", baselines=None,
         clock=None, sleep=time.sleep, log=print):
    """Run one live morning: freeze at each checkpoint + 5 s, ask, record.

    Must start before 09:30 ET on ``day``. A checkpoint whose packet cannot be
    built in time, or whose answer misses RESPONSE_DEADLINE_SECONDS, is recorded
    as missed/late, never retried or backfilled. Score it after the close with
    ``report`` (historical bars then supply the outcomes).
    """
    from .context import attach_context
    from .live import live_session
    from .packet import build_packet

    clock = clock or (lambda: datetime.now(UTC))
    baselines = baselines or {}
    run = Run(run_dir, {"kind": "live", "day": day, "variant": variant, "model": model_name,
                        "model_settings": getattr(model, "settings", None), "feed": feed,
                        "baselines": sorted(baselines), "source": source_fingerprint()})
    prior = []
    for checkpoint in CHECKPOINTS_ET:
        at = contract.checkpoint_ts(day, checkpoint)
        freeze = at + 5
        done = run.records.get((day, checkpoint, model_name, variant))
        if done is not None:  # restarted: never re-ask a recorded checkpoint
            if done["status"] == "ok":
                prior.append(_prior(done))
            continue
        if clock().timestamp() > at + 30:
            run.add(_record(day, checkpoint, model_name, variant, {}, {"status": "missed"}), {})
            continue
        while clock().timestamp() < freeze:
            sleep(min(1.0, freeze - clock().timestamp()))
        try:
            session = attach_context(live_session(day, clock(), feed=feed), refresh=True)
            packet = build_packet(session, checkpoint, variant, prior)
            rules_packet = build_packet(session, checkpoint, BASELINE_VARIANT)
        except Exception as exc:
            log(f"{checkpoint}: no packet ({type(exc).__name__})")
            run.add(_record(day, checkpoint, model_name, variant, {}, {"status": "data_missing",
                                                                       "error": type(exc).__name__}), {})
            continue
        for name, fn in sorted(baselines.items()):
            run.add(_record(day, checkpoint, name, BASELINE_VARIANT, rules_packet,
                            _baseline_result(fn, rules_packet)), rules_packet)
        result = model.forecast(packet)
        if clock().timestamp() > at + contract.RESPONSE_DEADLINE_SECONDS and result["status"] == "ok":
            result = {**result, "status": "late"}
        row = _record(day, checkpoint, model_name, variant, packet, result)
        run.add(row, packet)
        if row["status"] == "ok":
            prior.append(_prior(row))
        forecast = row["forecast"] or {}
        log(f"{checkpoint} {row['status']}: {forecast.get('action')} {forecast.get('symbol') or ''} "
            f"SPY {forecast.get('spy_p_up')} QQQ {forecast.get('qqq_p_up')} — {forecast.get('reason', '')}")
    return run
