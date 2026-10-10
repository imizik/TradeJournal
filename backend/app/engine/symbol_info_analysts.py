"""Analyst consensus for the Forecast tab (T2.3).

Two providers, each cached a day per symbol in memory and on disk under
``backend/data/symbol_info/v1/analysts/``:

- Webull OpenAPI (official): price targets, rating counts and reported-EPS beat or miss lead.
- Yahoo via ``yfinance`` (unofficial): a fallback for those, and the only
  source of EPS and revenue estimates and recent analyst actions.

Every block carries its own source label, and a provider that fails blanks only
the blocks it alone supplies. A failed read keeps serving the older copy with
its age, and is not retried for five minutes.
"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
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
# Webull documents no request parameters; a live call on 2026-10-08 showed these work.
WEBULL_TARGET_PATH = "/market-data/fundamentals/analysis/target-prices/get"
WEBULL_RATING_PATH = "/market-data/fundamentals/analysis/ratings/get"
WEBULL_EPS_PATH = "/market-data/fundamentals/forecast-eps/get"
WEBULL_QUERY = {"category": "US_STOCK"}
RATING_KEYS = ("strong_buy", "buy", "hold", "sell", "strong_sell")
TARGET_KEYS = ("mean", "median", "high", "low")


class ProviderError(Exception):
    pass


class PartialRead(ProviderError):
    """Some of a provider's tables failed. ``data`` holds the rest; it is kept briefly, not for a day."""

    def __init__(self, data: dict, why: str):
        super().__init__(why)
        self.data = data


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _count(value):
    number = _number(value)
    return int(number) if number is not None and number >= 0 else None


def normalize_webull_targets(payload) -> dict | None:
    """/analysis/target-prices/get: a flat object with string numbers (recorded 2026-10-08)."""
    row = payload if isinstance(payload, dict) else {}
    values = {key: _number(row.get(key)) for key in TARGET_KEYS}
    return values if any(value is not None for value in values.values()) else None


def normalize_webull_ratings(payload) -> dict | None:
    """/analysis/ratings/get: a flat object of counts; ``under_perform`` is the lowest rating."""
    row = payload if isinstance(payload, dict) else {}
    values = {key: _count(row.get(key)) for key in RATING_KEYS if key != "strong_sell"}
    values["strong_sell"] = _count(row.get("under_perform"))
    return values if any(value is not None for value in values.values()) else None


def normalize_webull_eps(payload) -> list[dict] | None:
    """Reported quarters of /forecast-eps (fiscal year, period, actual, est, reported) as beat or miss rows."""
    reported = [row for row in payload if isinstance(row, dict) and row.get("reported") is True] if isinstance(payload, list) else []
    rows = []
    for row in sorted(reported, key=lambda r: (_number(r.get("fiscal_year")) or 0, _number(r.get("fiscal_period")) or 0), reverse=True):
        actual, expected = _number(row.get("actual")), _number(row.get("est"))
        if actual is None or expected is None or row.get("fiscal_year") is None or row.get("fiscal_period") is None:
            continue
        rows.append({"quarter": f"FY{row['fiscal_year']} Q{row['fiscal_period']}", "actual": actual, "estimate": expected,
                     "surprise": (actual - expected) / abs(expected) if expected else None,
                     "result": "beat" if actual > expected else "miss" if actual < expected else "met"})
    return rows[:4] or None


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
    ticker = yf.Ticker(symbol.replace(".", "-").replace("/", "-"))  # Yahoo writes share classes as BRK-B
    parts, failed = [], []
    for name in ("analyst_price_targets", "recommendations_summary", "upgrades_downgrades", "earnings_estimate", "revenue_estimate", "earnings_history"):
        try:
            parts.append(getattr(ticker, name))
        except Exception:  # yfinance raises many types
            parts.append(None)
            failed.append(name)
    result = normalize_yahoo(*parts)
    if len(failed) == len(parts):
        raise ProviderError("Yahoo returned nothing.")
    if failed:
        raise PartialRead(result, "Yahoo answered only in part. Retrying in a few minutes.")
    return result


def fetch_webull(symbol: str) -> dict:
    from app.engine.webull_client import WebullClientError, WebullHttpClient, webull_configured
    if not webull_configured():
        raise ProviderError("Webull API keys are not set.")
    out: dict = {}
    failures = []
    try:
        client = WebullHttpClient()
        for key, path, parse in (("targets", WEBULL_TARGET_PATH, normalize_webull_targets), ("ratings", WEBULL_RATING_PATH, normalize_webull_ratings),
                                  ("history", WEBULL_EPS_PATH, normalize_webull_eps)):
            try:
                if value := parse(client.get(path, query={"symbol": symbol, **WEBULL_QUERY})):
                    out[key] = value
            except WebullClientError as exc:
                failures.append(str(exc))
    except WebullClientError as exc:
        raise ProviderError(str(exc)) from exc
    if failures:
        raise PartialRead(out, failures[0]) if out else ProviderError(failures[0])
    return out


class SymbolAnalysts:
    def __init__(self, root: Path = CACHE_DIR, clock: Callable[[], float] = time.time,
                 fetchers: dict[str, Callable[[str], dict]] | None = None):
        self.root = root
        self._clock = clock
        self._fetchers = fetchers or {WEBULL: fetch_webull, YAHOO: fetch_yahoo}
        self._lock = threading.Lock()
        self._fetching: dict[tuple[str, str], threading.Lock] = {}  # one read per provider and symbol; others reuse its result
        self._partial: dict[tuple[str, str], tuple[float, str]] = {}  # a partial read: serve it until, with why
        self._entries: dict[tuple[str, str], tuple[float, dict]] = {}
        self._retry: dict[tuple[str, str], tuple[float, str]] = {}

    def view(self, symbol: str) -> dict:
        with ThreadPoolExecutor(len(self._fetchers)) as pool:  # the providers are independent, so a slow one does not delay the other
            reads = dict(zip(self._fetchers, pool.map(lambda provider: self._read(provider, symbol), self._fetchers)))
        blocks = {}
        # Webull first, Yahoo when Webull has none. Their rating counts differ for the same analysts (NVDA: Webull
        # strong_buy 48, buy 10; Yahoo the reverse); Webull's matches what its own app shows, so it leads, and a
        # Yahoo rating block says its labels differ.
        for name in ("targets", "ratings", "history"):
            blocks[name] = self._block(name, reads, (WEBULL, YAHOO))
        for name in ("estimates", "actions"):  # Yahoo alone
            blocks[name] = self._block(name, reads, (YAHOO,))
        ready = [block for block in blocks.values() if block["state"] == "ready"]
        return {"symbol": symbol, "state": "ready" if ready else "unavailable" if any(r[2] for r in reads.values()) else "none",
                "blocks": blocks, "providers": {p: {"label": LABELS[p], "fetched_at": int(r[1]) if r[1] else None, "message": r[2]} for p, r in reads.items()}}

    def _block(self, name: str, reads: dict, order: tuple[str, ...]) -> dict:
        for provider in order:
            data, fetched, _ = reads[provider]
            if data and data.get(name):
                block = {"state": "ready", "source": LABELS[provider], "provider": provider, "fetched_at": int(fetched), "value": data[name],
                         "message": reads[provider][2]}  # set when this copy is older or partial because the latest read failed
                if name == "ratings" and provider == YAHOO:
                    block["note"] = "Yahoo's Strong Buy and Buy labels differ from Webull's for the same analysts."
                return block
        issues = [reads[p][2] for p in order if reads[p][2]]
        return {"state": "unavailable" if issues else "none", "source": " / ".join(LABELS[p] for p in order), "message": issues[0] if issues else None}

    def _read(self, provider: str, symbol: str) -> tuple[dict | None, float | None, str | None]:
        key = (provider, symbol)
        with self._lock:
            lock = self._fetching.setdefault(key, threading.Lock())
        with lock:
            entry = self._entry(key)
            now = self._clock()
            with self._lock:
                partial_until, partial_why = self._partial.get(key, (0.0, ""))
                until, why = self._retry.get(key, (0.0, ""))
            if entry and now - entry[0] < TTL_SECONDS and not partial_until:
                return entry[1], entry[0], None
            if now < partial_until:
                return entry[1], entry[0], partial_why
            if now < until:
                return (entry[1], entry[0], why) if entry else (None, None, why)
            try:
                data = self._fetchers[provider](symbol)
            except PartialRead as exc:
                with self._lock:
                    self._entries[key] = (now, exc.data)  # memory only: a restart reads again
                    self._partial[key] = (now + RETRY_SECONDS, str(exc))
                return exc.data, now, str(exc)
            except ProviderError as exc:
                why = str(exc)
            except Exception:
                log.exception("Analyst read failed: %s %s", provider, symbol)
                why = f"{LABELS[provider]} could not be read."
            else:
                self._store(key, (now, data))
                with self._lock:
                    self._retry.pop(key, None)
                    self._partial.pop(key, None)
                return data, now, None
            with self._lock:
                self._retry[key] = (now + RETRY_SECONDS, why)
                self._partial.pop(key, None)
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
