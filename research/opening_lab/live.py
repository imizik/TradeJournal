"""Live SessionData at a checkpoint, built from Alpaca REST at that moment.

Same shape as ``data.load_session``: today's minutes run from 04:00 ET up to
the last bar that has *finished* by ``now`` (the still-forming bar is dropped);
``daily`` and ``volume_profile`` come from the historical caches, so run
``data.prefetch`` before the open or yesterday's daily bar will be missing
(recorded in ``provenance["gaps"]``).

Caveat (unverified): Alpaca's free tier delays SIP data by 15 minutes, so a
live SIP read needs a paid market-data plan. Without one use ``feed="iex"``,
which is a partial tape and not comparable to the historical SIP replay.

Built and unit-tested only; it has not been run against the live API.
"""

from datetime import datetime

from research.opening_lab import data
from research.opening_lab.contract import ET, SYMBOLS, UTC, et_datetime

HTTP_TIMEOUT_SECONDS = 3.0


def default_http_get(url, params, headers):
    """One GET with a short timeout and no retries; returns parsed JSON."""
    import httpx

    resp = httpx.get(url, params=params, headers=headers, timeout=HTTP_TIMEOUT_SECONDS)
    resp.raise_for_status()
    return resp.json()


def _fetch_today(day, now, http_get, feed, received_at):
    """Raw minute bars per symbol for [04:00 ET, now]; logs each request's time."""
    out = {s: [] for s in SYMBOLS}
    params = {"symbols": ",".join(SYMBOLS), "timeframe": "1Min", "feed": feed,
              "adjustment": "raw", "limit": 10000,
              "start": et_datetime(day, data.WINDOW_START).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "end": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
    headers = data.alpaca_headers() if http_get is default_http_get else {}
    while True:
        page = http_get(data.DATA_URL, params, headers)
        received_at.append(datetime.now(UTC).isoformat())
        for sym, bars in (page.get("bars") or {}).items():
            if sym in out:
                out[sym].extend(bars)
        token = page.get("next_page_token")
        if not token:
            return out
        params = {**params, "page_token": token}


def live_session(day, now, *, http_get=None, feed="sip"):
    """SessionData for ``day`` as known at ``now`` (an aware datetime).

    ``http_get(url, params, headers) -> dict`` is injectable for tests.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if now.astimezone(ET).date().isoformat() != day:
        raise ValueError(f"now is not on session date {day}")
    now_epoch = int(now.timestamp())

    received_at = []
    raw = _fetch_today(day, now, http_get or default_http_get, feed, received_at)
    per_symbol, hist_prov = data.history(day, fetch=False)
    cal, _ = data.calendar(day, day, fetch=False)
    close = cal.get(day, {"close": "16:00"})["close"]

    gaps = list(hist_prov.pop("gaps"))
    prov = {"feed": feed, "adjustment": "raw", "now": now.astimezone(UTC).isoformat(),
            "received_at": received_at, "minutes": {}, **hist_prov}
    symbols = {}
    for sym in SYMBOLS:
        bars, stats = data.normalize_bars(raw[sym], day)
        finished = [b for b in bars if b["t"] + 60 <= now_epoch]
        prov["minutes"][sym] = {**stats, "forming_dropped": len(bars) - len(finished),
                                "count": len(finished),
                                "last_bar_end": finished[-1]["t"] + 60 if finished else None}
        if not finished:
            gaps.append(f"{sym}:no_completed_bars")
        symbols[sym] = {**per_symbol[sym], "minutes": finished}
    prov["gaps"] = gaps
    return {"date": day,
            "schedule": {"open": "09:30", "close": close, "early_close": close != "16:00"},
            "symbols": symbols, "news": [], "macro": [], "provenance": prov}
