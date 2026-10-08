"""Analyst consensus for the Forecast tab (T2.3).

Two providers, each cached a day per symbol in memory and on disk under
``backend/data/symbol_info/v1/analysts/``:

- Webull OpenAPI (official): price targets and rating counts. Primary for those.
- Yahoo via ``yfinance`` (unofficial): a fallback for the same two, and the only
  source of EPS and revenue estimates, beat or miss, and recent analyst actions.

Every block carries its own source label, and a provider that fails blanks only
the blocks it alone supplies. A failed read keeps serving the older copy with
its age, and is not retried for five minutes.
"""

from collections.abc import Callable
import json
import logging
import math
from pathlib import Path
import threading
import time
from uuid import uuid4

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "symbol_info" / "v1" / "analysts"
SCHEMA = 1
TTL_SECONDS = 24 * 3600
RETRY_SECONDS = 300
ACTIONS_SHOWN = 10
WEBULL = "webull"
YAHOO = "yahoo"
LABELS = {WEBULL: "Webull", YAHOO: "Yahoo, unofficial"}
# Webull documents no request parameters; adjust these once a probe shows the real ones.
WEBULL_TARGET_PATH = "/market-data/fundamentals/analysis/target-prices/get"
WEBULL_RATING_PATH = "/market-data/fundamentals/analysis/ratings/get"
WEBULL_QUERY = {"category": "US_STOCK"}
RATING_KEYS = ("strong_buy", "buy", "hold", "sell", "strong_sell")
TARGET_KEYS = ("mean", "median", "high", "low")


class ProviderError(Exception):
    pass


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _count(value):
    number = _number(value)
    return int(number) if number is not None and number >= 0 else None


def _pick(row: dict, *names: str):
    """The first present value among differently spelled keys (case and underscores ignored)."""
    flat = {str(key).replace("_", "").lower(): value for key, value in row.items()}
    for name in names:
        value = flat.get(name.replace("_", "").lower())
        if value not in (None, ""):
            return value
    return None


def _payload_row(payload) -> dict:
    """Webull wraps results unpredictably; take the first dict that holds scalars."""
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    if isinstance(payload, dict):
        for key in ("data", "result", "results"):
            if isinstance(payload.get(key), (dict, list)):
                return _payload_row(payload[key])
        return payload
    return {}


def normalize_webull_targets(payload) -> dict | None:
    row = _payload_row(payload)
    values = {
        "mean": _number(_pick(row, "mean", "meanTargetPrice", "avgTargetPrice", "average")),
        "median": _number(_pick(row, "median", "medianTargetPrice")),
        "high": _number(_pick(row, "high", "highTargetPrice", "highest")),
        "low": _number(_pick(row, "low", "lowTargetPrice", "lowest")),
    }
    return values if any(value is not None for value in values.values()) else None


def normalize_webull_ratings(payload) -> dict | None:
    row = _payload_row(payload)
    values = {
        "strong_buy": _count(_pick(row, "strongBuy", "strong_buy")),
        "buy": _count(_pick(row, "buy")),
        "hold": _count(_pick(row, "hold")),
        "sell": _count(_pick(row, "sell")),
        "strong_sell": _count(_pick(row, "strongSell", "strong_sell")),
    }
    return values if any(value is not None for value in values.values()) else None


def _records(frame) -> list[dict]:
    if frame is None:
        return []
    try:
        return frame.reset_index().to_dict("records")
    except AttributeError:
        return [row for row in frame if isinstance(row, dict)] if isinstance(frame, list) else []


def _day(value) -> str | None:
    try:
        return value.date().isoformat()
    except AttributeError:
        text = str(value or "")[:10]
        return text if len(text) == 10 else None


def normalize_yahoo(targets, summary, actions, eps, revenue, history) -> dict:
    """Plain dicts and records from yfinance's frames into this module's shape."""
    out: dict = {}
    if isinstance(targets, dict):
        picked = {key: _number(targets.get(key)) for key in TARGET_KEYS}
        if any(value is not None for value in picked.values()):
            out["targets"] = picked
    for row in _records(summary):
        if str(row.get("period")) == "0m":
            counts = dict(zip(RATING_KEYS, (_count(row.get(key)) for key in ("strongBuy", "buy", "hold", "sell", "strongSell"))))
            if any(value is not None for value in counts.values()):
                out["ratings"] = counts
            break
    rows = []
    for row in _records(actions):
        when = _day(row.get("GradeDate"))
        if not when or not row.get("Firm"):
            continue
        current, prior = _number(row.get("currentPriceTarget")), _number(row.get("priorPriceTarget"))
        rows.append({"date": when, "firm": str(row["Firm"]), "to_grade": row.get("ToGrade") or None, "from_grade": row.get("FromGrade") or None,
                     "action": row.get("priceTargetAction") or row.get("Action") or None,
                     "target": current if current else None, "prior_target": prior if prior else None})
    if rows:
        out["actions"] = sorted(rows, key=lambda r: r["date"], reverse=True)[:ACTIONS_SHOWN]
    estimates = {}
    for label, frame in (("eps", eps), ("revenue", revenue)):
        for row in _records(frame):
            if str(row.get("period")) in ("0q", "+1q") and _number(row.get("avg")) is not None:
                estimates.setdefault(str(row["period"]), {})[label] = {
                    "avg": _number(row.get("avg")), "low": _number(row.get("low")), "high": _number(row.get("high")),
                    "analysts": _count(row.get("numberOfAnalysts")), "growth": _number(row.get("growth"))}
    if estimates:
        out["estimates"] = [{"period": "current quarter" if key == "0q" else "next quarter", **value} for key, value in sorted(estimates.items(), key=lambda item: item[0] != "0q")]
    beats = []
    for row in _records(history):
        actual, expected = _number(row.get("epsActual")), _number(row.get("epsEstimate"))
        if actual is not None and expected is not None and _day(row.get("quarter")):
            beats.append({"quarter": _day(row["quarter"]), "actual": actual, "estimate": expected,
                          "surprise": _number(row.get("surprisePercent")), "result": "beat" if actual > expected else "miss" if actual < expected else "met"})
    if beats:
        out["history"] = sorted(beats, key=lambda r: r["quarter"], reverse=True)[:4]
    return out


def fetch_yahoo(symbol: str) -> dict:
    import yfinance as yf  # imported late: it is slow to load and only this read needs it
    ticker = yf.Ticker(symbol)
    parts = []
    for name in ("analyst_price_targets", "recommendations_summary", "upgrades_downgrades", "earnings_estimate", "revenue_estimate", "earnings_history"):
        try:
            parts.append(getattr(ticker, name))
        except Exception:  # yfinance raises many types; one missing table is not a failed read
            parts.append(None)
    result = normalize_yahoo(*parts)
    if not result and all(part is None for part in parts):
        raise ProviderError("Yahoo returned nothing.")
    return result


def fetch_webull(symbol: str) -> dict:
    from app.engine.webull_client import WebullClientError, WebullHttpClient, webull_configured
    if not webull_configured():
        raise ProviderError("Webull API keys are not set.")
    out: dict = {}
    failures = []
    try:
        client = WebullHttpClient()
        for key, path, parse in (("targets", WEBULL_TARGET_PATH, normalize_webull_targets), ("ratings", WEBULL_RATING_PATH, normalize_webull_ratings)):
            try:
                if value := parse(client.get(path, query={"symbol": symbol, **WEBULL_QUERY})):
                    out[key] = value
            except WebullClientError as exc:
                failures.append(str(exc))
    except WebullClientError as exc:
        raise ProviderError(str(exc)) from exc
    if not out and failures:
        raise ProviderError(failures[0])
    return out


class SymbolAnalysts:
    def __init__(self, root: Path = CACHE_DIR, clock: Callable[[], float] = time.time,
                 fetchers: dict[str, Callable[[str], dict]] | None = None):
        self.root = root
        self._clock = clock
        self._fetchers = fetchers or {WEBULL: fetch_webull, YAHOO: fetch_yahoo}
        self._lock = threading.Lock()
        self._fetching = threading.Lock()
        self._entries: dict[tuple[str, str], tuple[float, dict]] = {}
        self._retry: dict[tuple[str, str], tuple[float, str]] = {}

    def view(self, symbol: str) -> dict:
        with self._fetching:  # one symbol at a time keeps both providers' rates low; daily caches make it brief
            reads = {provider: self._read(provider, symbol) for provider in self._fetchers}
        blocks = {}
        for name in ("targets", "ratings"):  # Webull first, Yahoo when Webull has none
            blocks[name] = self._block(name, reads, (WEBULL, YAHOO))
        for name in ("estimates", "history", "actions"):  # Yahoo alone
            blocks[name] = self._block(name, reads, (YAHOO,))
        ready = [block for block in blocks.values() if block["state"] == "ready"]
        return {"symbol": symbol, "state": "ready" if ready else "unavailable" if any(r[2] for r in reads.values()) else "none",
                "blocks": blocks, "providers": {p: {"label": LABELS[p], "fetched_at": int(r[1]) if r[1] else None, "message": r[2]} for p, r in reads.items()}}

    def _block(self, name: str, reads: dict, order: tuple[str, ...]) -> dict:
        for provider in order:
            data, fetched, _ = reads[provider]
            if data and data.get(name):
                return {"state": "ready", "source": LABELS[provider], "provider": provider, "fetched_at": int(fetched), "value": data[name]}
        issues = [reads[p][2] for p in order if reads[p][2]]
        return {"state": "unavailable" if issues else "none", "source": " / ".join(LABELS[p] for p in order), "message": issues[0] if issues else None}

    def _read(self, provider: str, symbol: str) -> tuple[dict | None, float | None, str | None]:
        key = (provider, symbol)
        entry = self._entry(key)
        now = self._clock()
        if entry and now - entry[0] < TTL_SECONDS:
            return entry[1], entry[0], None
        with self._lock:
            until, why = self._retry.get(key, (0.0, ""))
        if now < until:
            return (entry[1], entry[0], why) if entry else (None, None, why)
        try:
            data = self._fetchers[provider](symbol)
        except ProviderError as exc:
            why = str(exc)
        except Exception:
            log.exception("Analyst read failed: %s %s", provider, symbol)
            why = f"{LABELS[provider]} could not be read."
        else:
            self._store(key, (now, data))
            with self._lock:
                self._retry.pop(key, None)
            return data, now, None
        with self._lock:
            self._retry[key] = (now + RETRY_SECONDS, why)
        return (entry[1], entry[0], why) if entry else (None, None, why)

    def _path(self, key: tuple[str, str]) -> Path:
        return self.root / key[0] / f"{key[1].replace('/', '_')}.json"

    def _entry(self, key):
        with self._lock:
            if key in self._entries:
                return self._entries[key]
        try:
            record = json.loads(self._path(key).read_text())
            entry = (float(record["fetched_at"]), record["data"]) if record.get("schema") == SCHEMA else None
        except (OSError, ValueError, KeyError, TypeError):
            entry = None
        if entry:
            with self._lock:
                self._entries[key] = entry
        return entry

    def _store(self, key, entry) -> None:
        with self._lock:
            self._entries[key] = entry
        path = self._path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
            try:
                temporary.write_text(json.dumps({"schema": SCHEMA, "fetched_at": entry[0], "data": entry[1]}, separators=(",", ":")))
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        except OSError:
            pass  # memory still holds it


symbol_analysts = SymbolAnalysts()
