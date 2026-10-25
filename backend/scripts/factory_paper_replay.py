"""Disabled Factory replay adapter. Manual synthetic demo only; never an evaluator.

Caller-supplied completed bars produce ideal Factory events, not executable fills.
No provider, broker, application database, Factory loader, gate or ledger imports.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.engine.factory_data import ET, NYSE_EARLY_CLOSES, FeatureContext, Series
from app.engine.factory_rules import Context, canonical, parse_spec, run_candidate, spec_id
from app.engine.market_map import Bar

ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / "research/specs/opening_range_breakout_rvol2_v1.json"
SPEC_ID = "op-998d19a73d"
MAX_BARS = 2000  # fixture adapter: recompute prefixes, not a production streaming loop


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _stamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _moment(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    _stamp(result)
    return result


def frozen_spec():
    spec = parse_spec(json.loads(SPEC_PATH.read_text()))
    if spec_id(spec) != SPEC_ID:
        raise ValueError("frozen ORB specification changed")
    return spec


def _implementation():
    paths = [Path(__file__), *(ROOT / "backend/app/engine" / name for name in
                              ("factory_rules.py", "factory_data.py", "market_map.py"))]
    return _digest([hashlib.sha256(p.read_bytes()).hexdigest() for p in paths])


@dataclass(frozen=True)
class Observation:
    bar: Bar
    observed_at: datetime
    complete: bool = True
    # Optional contemporaneous stock quote for comparison only, never a fill.
    # Fields: event_at, received_at (aware ISO timestamps), bid, ask, bid_size, ask_size.
    quote: dict | None = None

    def record(self):
        return {"bar": {**asdict(self.bar), "time": _stamp(self.bar.time)},
                "observed_at": _stamp(self.observed_at), "complete": self.complete,
                "quote": self.quote}

    @classmethod
    def restore(cls, raw):
        bar = dict(raw["bar"])
        bar["time"] = _moment(bar["time"])
        return cls(Bar(**bar), _moment(raw["observed_at"]), raw["complete"], raw["quote"])


def _end(bar):
    return bar.time + timedelta(minutes=5)


def _session_end(bar):
    local = bar.time.astimezone(ET)
    minute = NYSE_EARLY_CLOSES.get(local.date(), 960)
    return local.replace(hour=minute // 60, minute=minute % 60, second=0, microsecond=0)


def _validate(observations):
    if not observations or len(observations) > MAX_BARS:
        raise ValueError("replay requires 1..2000 fixture bars")
    previous = None
    for obs in observations:
        b = obs.bar
        _stamp(b.time)
        _stamp(obs.observed_at)
        local = b.time.astimezone(ET)
        minute = local.hour * 60 + local.minute
        if obs.complete is not True:
            raise ValueError("incomplete bar: replay stopped without an invented fill")
        if local.weekday() >= 5 or minute < 570 or _end(b) > _session_end(b) or minute % 5 or local.second or local.microsecond:
            raise ValueError("expected aligned regular-session five-minute bar")
        if obs.observed_at < _end(b):
            raise ValueError("bar observed before its close")
        values = (b.open, b.high, b.low, b.close, b.volume)
        if any(not math.isfinite(v) for v in values) or min(values[:4]) <= 0 or b.volume < 0:
            raise ValueError("invalid OHLCV")
        if b.low > min(b.open, b.close) or b.high < max(b.open, b.close) or b.low > b.high:
            raise ValueError("invalid OHLC bounds")
        if previous is not None:
            if b.time <= previous.bar.time or obs.observed_at < previous.observed_at:
                raise ValueError("bars and receipt times must be ordered")
            if local.date() != previous.bar.time.astimezone(ET).date() and _end(previous.bar) != _session_end(previous.bar):
                raise ValueError("missing session close: replay stopped, no retrospective liquidation")
        previous = obs


def _quote_comparison(obs, side, ideal_price):
    """A supplied quote can explain model slippage; it never proves a fill."""
    q = obs.quote
    result = {"paper_fill_at": None, "paper_fill_price": None, "paper_refusal": "completed_bar_is_not_an_order_receipt",
              "quote_status": "missing"}
    if q is None:
        return result
    try:
        event, received = _moment(q["event_at"]), _moment(q["received_at"])
        bid, ask = float(q["bid"]), float(q["ask"])
        sizes = [float(q[k]) for k in ("bid_size", "ask_size")]
        if not all(math.isfinite(v) for v in [bid, ask, *sizes]) or not 0 < bid <= ask or min(sizes) <= 0:
            raise ValueError("invalid book")
        if not event <= received <= obs.observed_at or obs.observed_at - event > timedelta(seconds=5):
            result["quote_status"] = "stale_or_out_of_order"
            return result
        price = ask if side == 1 else bid
        result.update(quote_status="comparison_only", quote_at=_stamp(event), quote_received_at=_stamp(received),
                      quote_price=price, adverse_price_difference=round(side * (price - ideal_price), 10))
    except (KeyError, TypeError, ValueError, OverflowError):
        result["quote_status"] = "invalid"
    return result


def replay_snapshot(ticker: str, observations: list[Observation]) -> list[dict]:
    """Recompute this prefix through the unmodified Factory runner/on_bar code.

    Only the frozen RVOL spec is supported. SPY-dependent features are unused;
    no market data or historical caches are loaded. Split inference changes the
    price basis, so this adapter refuses it rather than rewriting old events.
    """
    spec = frozen_spec()
    if ticker not in spec.tickers:
        raise ValueError("ticker is outside the frozen core universe")
    _validate(observations)
    series = Series.build(ticker, [obs.bar for obs in observations], spec.timeframe)
    if series.splits:
        raise ValueError("split/price-basis change requires a separate reviewed replay")
    # Series.build marks the end of every prefix as last. Only the actual
    # calendar close is an end-of-session instruction in a completed-bar stream.
    series.last = [_end(obs.bar) == _session_end(obs.bar) for obs in observations]
    features = FeatureContext(series, None)
    decisions = []
    family = spec.rules().start(series)

    class TraceFamily:
        def on_bar(self, i, ctx):
            def accept(signal):
                values = features.at(signal.index, signal.side, signal.stop)
                passed = ctx.accept(signal)
                decisions.append((signal, passed, values["rvol"]))
                return passed
            return family.on_bar(i, Context(ctx.flat, ctx.halted, accept))

    trades = run_candidate(series, TraceFamily(), spec.exits, spec.costs, spec.window, spec.limits,
                           lambda signal: all(rule.passes(features.at(signal.index, signal.side, signal.stop))
                                              for rule in spec.filters), features)
    events = []

    def event(kind, signal_index, side, index, **fields):
        obs = observations[index]
        key = f"{SPEC_ID}:{ticker}:{_stamp(series.time[signal_index])}:{side}:{kind}"
        events.append({"id": hashlib.sha256(key.encode()).hexdigest(), "kind": kind, "ticker": ticker,
                       "side": side, "signal_bar_open_at": _stamp(series.time[signal_index]),
                       "signal_close_at": _stamp(_end(observations[signal_index].bar)),
                       "order_eligible_at": _stamp(max(_end(observations[signal_index].bar),
                                                      observations[signal_index].observed_at)),
                       "observed_at": _stamp(obs.observed_at), "bar_open_at": _stamp(obs.bar.time),
                       "bar_close_at": _stamp(_end(obs.bar)), **fields})

    entered = {t.signal_index for t in trades}
    for signal, accepted, rvol in decisions:
        event("signal", signal.index, signal.side, signal.index, stop=signal.stop, accepted=accepted,
              rvol=rvol if math.isfinite(rvol) else None,
              reason="accepted" if accepted else "rvol_filter")
        next_index = signal.index + 1
        if accepted and next_index < len(series) and signal.index not in entered:
            reason = "session_expired" if series.session[next_index] != series.session[signal.index] else "gap_through_stop"
            event("unfilled", signal.index, signal.side, next_index, reason=reason)
    for trade in trades:
        i = trade.entry_index
        event("model_entry", trade.signal_index, trade.side, i, price=trade.entry_price, stop=trade.stop,
              model_fill_at=_stamp(trade.entry_time), execution="ideal_bar_model_only",
              retroactive_open=True, **_quote_comparison(observations[i], trade.side, trade.entry_price))
        if trade.closed:
            i = trade.exit_index
            event("model_exit", trade.signal_index, trade.side, i, price=trade.exit_price, reason=trade.exit_reason,
                  # Intrabar order is unknown. Never label bar-open as the exact stop timestamp.
                  model_fill_at=_stamp(_end(observations[i].bar)) if trade.exit_reason == "session" else None,
                  execution="ideal_bar_model_only", **_quote_comparison(observations[i], -trade.side, trade.exit_price))
    return sorted(events, key=lambda e: (e["bar_open_at"], {"model_entry": 0, "model_exit": 1, "signal": 2, "unfilled": 3}[e["kind"]], e["id"]))


class ReplayJournal:
    """One explicit scratch directory/ticker. Append-only, locked, fsynced receipts.

    Each line commits an input and all new derived events together. Restart
    checks the hash chain and recomputes the saved prefix before accepting more.
    A torn/corrupt journal is refused, never silently truncated or replayed away.
    """
    def __init__(self, directory: Path, ticker: str):
        self.directory = Path(directory)
        self.ticker = ticker
        if ticker not in frozen_spec().tickers:
            raise ValueError("ticker is outside the frozen core universe")
        self.header = {"format": "factory-paper-replay-v1", "mode": "disabled_fixture_replay",
                       "ticker": ticker, "spec": canonical(frozen_spec()), "implementation": _implementation()}

    def _sync(self, handle):
        handle.flush()
        os.fsync(handle.fileno())
        # Persist both the journal entry and a newly created output directory.
        # Its parent must already exist; no unsynced recursive mkdir chain.
        for directory in (self.directory, self.directory.parent):
            fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    def append(self, observation: Observation) -> list[dict]:
        self.directory.mkdir(exist_ok=True)
        path = self.directory / "factory-paper-replay.jsonl"
        with path.open("a+b") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            handle.seek(0)
            raw = handle.read()
            if raw and not raw.endswith(b"\n"):
                raise ValueError("torn journal: manual recovery required")
            rows = [json.loads(line) for line in raw.splitlines()]
            if rows and rows[0] != self.header:
                raise ValueError("journal specification, ticker or implementation differs")
            observations, recorded = [], {}
            previous = _digest(self.header)
            for row in rows[1:]:
                payload = {k: v for k, v in row.items() if k != "hash"}
                if row["previous"] != previous or row["hash"] != _digest(payload):
                    raise ValueError("journal hash chain mismatch")
                previous = row["hash"]
                observations.append(Observation.restore(row["input"]))
                for ev in row["events"]:
                    if ev["id"] in recorded:
                        raise ValueError("duplicate event in journal")
                    recorded[ev["id"]] = ev
            if observations:
                restored = {ev["id"]: ev for ev in replay_snapshot(self.ticker, observations)}
                if restored != recorded:
                    raise ValueError("journal replay differs from recorded events")
            incoming = observation.record()
            for old in observations:
                if old.bar.time == observation.bar.time:
                    if old.record() != incoming:
                        raise ValueError("revised observation for committed bar")
                    self._sync(handle)  # retry after an earlier directory-sync failure
                    return []
            observations.append(observation)
            snapshot = {ev["id"]: ev for ev in replay_snapshot(self.ticker, observations)}
            if any(snapshot.get(key) != value for key, value in recorded.items()):
                raise ValueError("prefix changed a committed event")
            fresh = [ev for key, ev in snapshot.items() if key not in recorded]
            row = {"previous": previous, "input": incoming, "events": fresh}
            row["hash"] = _digest(row)
            data = ((_json(self.header) + "\n") if not raw else "") + _json(row) + "\n"
            handle.write(data.encode())
            self._sync(handle)
            return fresh


def synthetic_demo():
    """Invented warmup and one breakout, no data provider or filesystem input."""
    first = datetime(2024, 1, 22, 9, 30, tzinfo=ET)
    for day in (0, 1, 2, 3, 4, 7):
        start = first + timedelta(days=day)
        # Sparse but explicitly complete bars; final bar is the calendar close.
        for offset in (0, 5, 10, 385):
            time = start + timedelta(minutes=offset)
            active = day == 7
            o = 102 if active and offset >= 10 else 100
            c = 102 if active and offset >= 5 else 100
            b = Bar(time, o, max(o, c) + .5, min(o, c) - .5, c, 3000 if active else 1000)
            yield Observation(b, _end(b))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", required=True, help="invented fixture only; no live mode")
    parser.add_argument("--output", type=Path, required=True, help="explicit scratch directory for replay receipts")
    args = parser.parse_args(argv)
    journal = ReplayJournal(args.output, "MU")
    count = sum(len(journal.append(obs)) for obs in synthetic_demo())
    print(f"Disabled synthetic replay: {count} new events. No executable fills or candidate evaluation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
