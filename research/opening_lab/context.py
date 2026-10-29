"""Raw context for the opening lab: Alpaca (Benzinga) headlines and scheduled macro events.

``attach_context`` fills ``news`` and ``macro`` on a SessionData copy with
everything in the window and exact timestamps. It does NOT decide what was
visible at a checkpoint; ``packet.py`` applies that causal cut.

News window: prior session 16:00 ET through 10:30 ET of the session date.
Pages are fetched newest-first and the NEWEST ~300 items are kept, so a busy
day loses overnight items, never the open. Macro coverage is CPI / FOMC / jobs only (no GDP, ISM, PCE, retail sales...).
"""

import argparse
import copy
import html
import json
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

try:
    from .contract import ET, UTC, et_datetime
except ImportError:  # run as a plain script
    from contract import ET, UTC, et_datetime

NEWS_URL = "https://data.alpaca.markets/v1beta1/news"
ENV_PATH = Path("/Users/user/TradeJournal/backend/.env")
REPO_ROOT = Path(__file__).resolve().parents[2]
MACRO_PATH = REPO_ROOT / "backend/app/data/macro_calendar.json"
CACHE_DIR = Path(__file__).resolve().parent / ".cache" / "news"

PAGE_LIMIT = 50
MAX_ITEMS = 300
SUMMARY_CHARS = 400
WINDOW_END_ET = "10:30"
MAX_REQUESTS_PER_MIN = 150
MAX_RETRIES = 4
QUERIES = (("broad", None), ("spy_qqq", "SPY,QQQ"))

_request_times = []  # monotonic times of recent requests, for throttling


# --- helpers -----------------------------------------------------------------
def _strip_html(text):
    text = html.unescape(text or "")
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _utc_z(value):
    """Normalize a provider timestamp to ISO-8601 UTC with a trailing Z."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_news(item):
    """Provider article -> contract NewsItem."""
    return {
        "id": str(item["id"]),
        "headline": _strip_html(item.get("headline")),
        "summary": _strip_html(item.get("summary"))[:SUMMARY_CHARS],
        "symbols": list(item.get("symbols") or []),
        "source": item.get("source") or "",
        "created_at": _utc_z(item["created_at"]),
    }


def _merge(items):
    """Dedupe by id and sort by created_at (then id)."""
    unique = {}
    for item in items:
        unique.setdefault(item["id"], item)
    return sorted(unique.values(), key=lambda i: (i["created_at"], i["id"]))


def _prior_date(session):
    """Prior session date: last daily bar if present, else previous weekday."""
    daily = (session.get("symbols", {}).get("SPY") or {}).get("daily") or []
    if daily:
        return daily[-1]["date"]
    day = date.fromisoformat(session["date"]) - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day.isoformat()


def _prior_weekday(day):
    d = date.fromisoformat(day) - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


def _window(day, prior):
    start = et_datetime(prior, "16:00").astimezone(UTC)
    end = et_datetime(day, WINDOW_END_ET).astimezone(UTC)
    return start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ")


def _headers():
    from dotenv import dotenv_values

    env = dotenv_values(ENV_PATH)
    key = os.environ.get("ALPACA_API_KEY") or env.get("ALPACA_API_KEY")
    secret = os.environ.get("ALPACA_API_SECRET") or env.get("ALPACA_API_SECRET")
    if not key or not secret:
        raise RuntimeError("ALPACA_API_KEY / ALPACA_API_SECRET not found")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def _throttle():
    now = time.monotonic()
    _request_times[:] = [t for t in _request_times if now - t < 60]
    if len(_request_times) >= MAX_REQUESTS_PER_MIN:
        time.sleep(60 - (now - _request_times[0]) + 0.05)
    _request_times.append(time.monotonic())


def _get(client, params):
    """GET one news page with throttling and retry on 429/5xx."""
    for attempt in range(MAX_RETRIES + 1):
        _throttle()
        resp = client.get(NEWS_URL, params=params)
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt == MAX_RETRIES:
                resp.raise_for_status()
            time.sleep(2 ** attempt)
            continue
        resp.raise_for_status()
        return resp.json()


def _fetch_query(client, start, end, symbols):
    params = {"start": start, "end": end, "sort": "desc", "limit": PAGE_LIMIT,
              "include_content": "false", "exclude_contentless": "false"}
    if symbols:
        params["symbols"] = symbols
    items, token = [], None
    while len(items) < MAX_ITEMS:
        page = dict(params, **({"page_token": token} if token else {}))
        data = _get(client, page)
        items += [normalize_news(a) for a in data.get("news") or []]
        token = data.get("next_page_token")
        if not token:
            break
    return items[:MAX_ITEMS]


# --- cache -------------------------------------------------------------------
def _cache_path(day):
    return CACHE_DIR / f"{day}.json"


def _read_cache(day):
    try:
        return json.loads(_cache_path(day).read_text())
    except (OSError, ValueError):
        return None


def _write_cache(day, payload):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    gitignore = CACHE_DIR.parent / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n")
    _cache_path(day).write_text(json.dumps(payload, indent=1))


def fetch_news_day(day, prior=None, client=None):
    """Fetch (network) and cache one session's headlines. Returns the cache payload."""
    prior = prior or _prior_weekday(day)
    start, end = _window(day, prior)
    own = client is None
    client = client or httpx.Client(headers=_headers(), timeout=30)
    try:
        items, per_query = [], []
        for _, symbols in QUERIES:
            got = _fetch_query(client, start, end, symbols)
            per_query.append(len(got))
            items += got
    finally:
        if own:
            client.close()
    merged = _merge(items)
    capped = len(merged) > MAX_ITEMS or any(n >= MAX_ITEMS for n in per_query)
    payload = {"date": day, "window": [start, end], "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "capped": capped, "items": merged[-MAX_ITEMS:]}
    _write_cache(day, payload)
    return payload


# --- macro -------------------------------------------------------------------
def load_macro(day, path=MACRO_PATH):
    """(events, coverage dict) for a session date from the local macro calendar."""
    cal = json.loads(Path(path).read_text())
    covered = cal["covers_from"] <= day <= cal["covers_through"]
    events = []
    if covered:
        for e in cal["events"]:
            if e["date"] == day:
                at = et_datetime(day, e["time"]).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                events.append({"kind": e["kind"], "name": e["name"], "scheduled_at": at})
    events.sort(key=lambda e: e["scheduled_at"])
    return events, {"status": "ok" if covered else "outside_coverage",
                    "covers_from": cal["covers_from"], "covers_through": cal["covers_through"]}


# --- public API --------------------------------------------------------------
def attach_context(session, *, fetch=False):
    """Return a copy of SessionData with ``news``, ``macro`` and provenance["context"] filled.

    ``fetch=False`` reads only the on-disk news cache; ``fetch=True`` hits Alpaca
    when a day is not cached. Missing coverage is recorded, never silent.
    """
    out = copy.deepcopy(session)
    day = out["date"]
    prior = _prior_date(out)
    errors = []

    payload = _read_cache(day)
    news_status = "cache" if payload else "missing"
    if payload is None and fetch:
        try:
            payload = fetch_news_day(day, prior)
            news_status = "fetched"
        except Exception as exc:  # report, never crash a replay
            errors.append(f"news_fetch_failed: {type(exc).__name__}: {str(exc)[:200]}")
            news_status = "error"
    news = payload["items"] if payload else []
    if payload and payload.get("capped"):
        errors.append(f"news_capped_at_{MAX_ITEMS}_oldest_dropped")

    macro, macro_cov = load_macro(day)
    out["news"] = news
    out["macro"] = macro
    out.setdefault("provenance", {})["context"] = {
        "news": {
            "source": "alpaca_news_benzinga",
            "queries": [name for name, _ in QUERIES],
            "status": news_status,
            "count": len(news),
            "window": payload["window"] if payload else list(_window(day, prior)),
            "fetched_at": payload.get("fetched_at") if payload else None,
            "note": "created_at is the provider timestamp, possibly later than first publication",
        },
        "macro": dict(macro_cov, source="backend/app/data/macro_calendar.json", count=len(macro),
                      note="CPI/FOMC/jobs only; no GDP, ISM, PCE or other releases"),
        "errors": errors,
    }
    return out


def weekdays(start, end):
    day, last = date.fromisoformat(start), date.fromisoformat(end)
    while day <= last:
        if day.weekday() < 5:
            yield day.isoformat()
        day += timedelta(days=1)


def prefetch_news(start, end, days=None):
    """Fetch and cache headlines for each weekday in [start, end] (or ``days``).

    Already-cached days are skipped. Returns {"counts": {day: n}, "failures": {day: msg}}.
    """
    counts, failures = {}, {}
    todo = days if days is not None else list(weekdays(start, end))
    with httpx.Client(headers=_headers(), timeout=30) as client:
        for day in todo:
            payload = _read_cache(day)
            try:
                if payload is None:
                    payload = fetch_news_day(day, client=client)
                counts[day] = len(payload["items"])
            except Exception as exc:
                failures[day] = f"{type(exc).__name__}: {str(exc)[:200]}"
    return {"counts": counts, "failures": failures}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m research.opening_lab.context")
    sub = parser.add_subparsers(dest="cmd", required=True)
    pre = sub.add_parser("prefetch", help="cache Alpaca headlines for a date range")
    pre.add_argument("--start", required=True)
    pre.add_argument("--end", required=True)
    args = parser.parse_args(argv)
    result = prefetch_news(args.start, args.end)
    counts = sorted(result["counts"].values())
    print(f"sessions={len(counts)} failures={len(result['failures'])}")
    if counts:
        print(f"items min={counts[0]} median={counts[len(counts) // 2]} max={counts[-1]}")
    for day, msg in result["failures"].items():
        print(f"FAILED {day}: {msg}")


if __name__ == "__main__":
    main()
