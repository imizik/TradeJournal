"""Stock split records for the chart's price basis, from Alpaca corporate actions.

Splits are display metadata for Charts: they never touch fills, P&L, the raw
history cache or the journal's Alpaca caches. One small file per symbol is
refetched once per New York date (a split can be announced any day); a failed
refresh keeps the previous copy and says so (`stale`), and with no copy at all
the symbol is `unknown`, which the chart shows instead of guessing. These
requests are one call per symbol per day, apart from the history budget.
"""

from datetime import date, datetime
import json
from math import isfinite
from pathlib import Path
import re
import threading
import time
from urllib.parse import quote
from uuid import uuid4

import httpx

from app.engine import alpaca
from app.engine.chart_adjust import SOURCE
from app.engine.chart_math import ET

SCHEMA = 1
FIRST = date(2016, 1, 1)  # the chart's history floor
RETRY_SECONDS = 60
SYMBOL = re.compile(r"^[A-Z][A-Z0-9./-]{0,14}$")
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "chart_splits" / "v1" / "alpaca"


class SplitsError(Exception):
    pass


def parse_actions(body: dict, symbol: str) -> list[dict]:
    """Normalized forward and reverse splits from one Alpaca response; anything malformed raises."""
    actions = body["corporate_actions"]
    if not isinstance(actions, dict):
        raise ValueError("actions")
    found = []
    for key in ("forward_splits", "reverse_splits"):
        for row in actions.get(key) or []:
            if row.get("symbol", symbol) != symbol:
                continue
            new, old = float(row["new_rate"]), float(row["old_rate"])
            ex = date.fromisoformat(str(row["ex_date"]))
            if not (isfinite(new) and isfinite(old) and new > 0 and old > 0):
                raise ValueError("rate")
            if new != old:
                found.append({"ex_date": ex.isoformat(), "ratio": new / old, "new_rate": new, "old_rate": old})
    return sorted({(s["ex_date"], s["ratio"]): s for s in found}.values(), key=lambda s: s["ex_date"])


class ChartSplits:
    def __init__(self, root: Path = CACHE_DIR):
        self.root = root
        self._lock = threading.Lock()  # also coalesces simultaneous misses for one symbol
        self._retry: dict[str, float] = {}

    def _path(self, symbol: str) -> Path:
        if not SYMBOL.fullmatch(symbol):
            raise SplitsError("Invalid chart symbol.")
        return self.root / f"{quote(symbol, safe='')}.json"

    def _read(self, symbol: str) -> dict | None:
        try:
            data = json.loads(self._path(symbol).read_text())
            if data["schema"] != SCHEMA or data["symbol"] != symbol or data["source"] != SOURCE:
                raise ValueError("metadata")
            date.fromisoformat(data["fetched_on"])
            int(data["fetched_at"])
            parse_actions({"corporate_actions": {"forward_splits": [
                {"new_rate": s["new_rate"], "old_rate": s["old_rate"], "ex_date": s["ex_date"]} for s in data["splits"]]}}, symbol)
            return data
        except (OSError, ValueError, TypeError, KeyError):
            return None  # absent or damaged: refetch (splits, unlike sessions, can be refreshed)

    def _fetch(self, symbol: str, today: date) -> list[dict]:
        if not alpaca.ALPACA_API_KEY or not alpaca.ALPACA_API_SECRET:
            raise SplitsError("Alpaca credentials are not configured.")
        params = {"symbols": symbol, "types": "forward_split,reverse_split", "start": FIRST.isoformat(),
                  "end": today.isoformat(), "limit": 1000}
        splits, token = [], None
        for _ in range(5):
            if token:
                params["page_token"] = token
            try:
                response = httpx.get(f"{alpaca.DATA_URL}/v1/corporate-actions", params=params, timeout=5,
                                     headers={"APCA-API-KEY-ID": alpaca.ALPACA_API_KEY, "APCA-API-SECRET-KEY": alpaca.ALPACA_API_SECRET})
            except httpx.HTTPError as exc:
                raise SplitsError("Alpaca corporate actions are unreachable.") from exc
            if response.status_code != 200:
                raise SplitsError(f"Alpaca corporate actions returned HTTP {response.status_code}.")
            try:
                body = response.json()
                splits.extend(parse_actions(body, symbol))
                token = body.get("next_page_token") or None
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                raise SplitsError("Alpaca returned malformed corporate actions.") from exc
            if not token:
                return sorted({(s["ex_date"], s["ratio"]): s for s in splits}.values(), key=lambda s: s["ex_date"])
        raise SplitsError("Alpaca corporate actions did not finish paging.")

    def _publish(self, symbol: str, today: date, splits: list[dict]) -> dict:
        record = {"schema": SCHEMA, "symbol": symbol, "source": SOURCE, "fetched_on": today.isoformat(),
                  "fetched_at": int(time.time()), "splits": splits}
        path = self._path(symbol)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(record, separators=(",", ":")))
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        return record

    def get(self, symbol: str, today: date | None = None) -> dict:
        """{"status": ok|stale|unknown, "splits": [...up to today], "as_of": epoch|None, "issue": str|None}."""
        today = today or datetime.now(ET).date()
        try:
            self._path(symbol)
        except SplitsError as exc:
            return _info("unknown", [], None, str(exc))
        with self._lock:
            saved = self._read(symbol)
            issue = None
            if saved is None or saved["fetched_on"] != today.isoformat():
                if time.monotonic() >= self._retry.get(symbol, 0.0):
                    try:
                        saved = self._publish(symbol, today, self._fetch(symbol, today))
                        self._retry.pop(symbol, None)
                    except (SplitsError, OSError) as exc:
                        self._retry[symbol] = time.monotonic() + RETRY_SECONDS
                        issue = str(exc)
                else:
                    issue = "Split data refresh is backing off after a failure."
        if saved is None:
            return _info("unknown", [], None, issue)
        status = "ok" if saved["fetched_on"] == today.isoformat() else "stale"
        # A split is effective from its ex-date; later ones are not applied yet.
        known = [s for s in saved["splits"] if s["ex_date"] <= today.isoformat()]
        return _info(status, known, int(saved["fetched_at"]), issue)


def _info(status: str, splits: list[dict], as_of: int | None, issue: str | None) -> dict:
    return {"status": status, "splits": splits, "as_of": as_of, "issue": issue}


UNAVAILABLE = _info("unknown", [], None, "Split data is not configured.")
chart_splits = ChartSplits()
