"""Cross-market context for the full variant: rates, dollar, oil, gold, volatility,
small caps, index heavyweights and sector breadth, from raw SIP minute bars.

Index futures are not available from Alpaca's stock feed; SPY/QQQ premarket
(04:00 on, in each symbol's features) is the overnight proxy, and these ETFs add
the cross-asset picture. Everything here is causal in the same way as
``packet.py``: a minute bar is used only once it has ENDED by the checkpoint, and
prior closes are raw daily closes of the previous session.

Cache (gitignored): ``.cache/cross/minutes/{date}.json`` = {symbol: [Bar1m]} for
04:00-11:00 ET, and ``.cache/cross/daily.json`` = {symbol: {date: close}}.
"""

from datetime import date, timedelta

from . import data
from .contract import checkpoint_ts, et_datetime, visible_bars

MACRO = ("TLT", "UUP", "USO", "GLD", "VIXY", "IWM")
MEGA_CAPS = ("NVDA", "AAPL", "MSFT", "AMZN", "META", "GOOGL", "AVGO", "TSLA")
SECTORS = ("XLK", "XLF", "XLE", "XLV", "XLY", "XLI", "XLP", "XLU", "XLC", "XLB", "XLRE")
CROSS_SYMBOLS = MACRO + MEGA_CAPS + SECTORS
COLUMNS = ("gap_pct", "since_open_pct", "last5m_pct")
CACHE_DIR = data.CACHE_DIR / "cross"
FETCH_CHUNK_SESSIONS = 2   # 25 symbols x ~420 minutes per session


def _minutes_path(day):
    return CACHE_DIR / "minutes" / f"{day}.json"


def _daily_path():
    return CACHE_DIR / "daily.json"


def ensure_cross(days, *, fetch=False):
    """Fetch and cache minutes and daily closes for completed sessions in ``days``."""
    if not fetch:
        return
    todo = [d for d in days if data._session_complete(d) and data._read_json(_minutes_path(d)) is None]
    for i in range(0, len(todo), FETCH_CHUNK_SESSIONS):
        chunk = todo[i:i + FETCH_CHUNK_SESSIONS]
        raw = data._fetch_bars("1Min", et_datetime(chunk[0], data.WINDOW_START),
                               et_datetime(chunk[-1], data.WINDOW_END), CROSS_SYMBOLS)
        for d in chunk:
            data._write_json(_minutes_path(d), {s: data.normalize_bars(raw[s], d)[0] for s in CROSS_SYMBOLS})

    closes = data._read_json(_daily_path()) or {}
    needed = [d for d in days if data._session_complete(d)]
    if needed and any(_prior_close_date(closes, s, d) is None for s in CROSS_SYMBOLS for d in needed):
        start = (date.fromisoformat(min(needed)) - timedelta(days=10)).isoformat()
        raw = data._fetch_bars("1Day", et_datetime(start, "00:00"), et_datetime(max(needed), "20:00"),
                               CROSS_SYMBOLS)
        for sym in CROSS_SYMBOLS:
            have = closes.setdefault(sym, {})
            for r in raw[sym]:
                bar = data._daily_bar(r)
                if bar and data._session_complete(bar["date"]):
                    have.setdefault(bar["date"], bar["c"])
        data._write_json(_daily_path(), closes)


def _prior_close_date(closes, sym, day):
    earlier = [d for d in (closes.get(sym) or {}) if d < day]
    return max(earlier) if earlier else None


def attach_cross(session, *, fetch=False):
    """Return ``session`` with ``cross`` = {"prior_close": {sym: close}, "minutes": {sym: bars}}
    for its date, or ``cross`` = None when nothing is cached."""
    day = session["date"]
    ensure_cross([day], fetch=fetch)
    minutes = data._read_json(_minutes_path(day))
    closes = data._read_json(_daily_path()) or {}
    if minutes is None:
        return {**session, "cross": None}
    prior = {}
    for sym in CROSS_SYMBOLS:
        d = _prior_close_date(closes, sym, day)
        # the previous session only: a stale close (missing day) would fake a gap
        prior[sym] = closes[sym][d] if d and d >= _previous_session(session) else None
    return {**session, "cross": {"prior_close": prior, "minutes": minutes}}


def _previous_session(session):
    daily = ((session.get("symbols") or {}).get("SPY") or {}).get("daily") or []
    earlier = [b["date"] for b in daily if b["date"] < session["date"]]
    return max(earlier) if earlier else "0000-00-00"


def _pct(now, ref):
    return round(100 * (now / ref - 1), 3) if now is not None and ref else None


def _row(bars, prior_close, open_ts, c_ts):
    seen = visible_bars(bars or [], c_ts)
    rth = [b for b in seen if b["t"] >= open_ts]
    pre = [b for b in seen if b["t"] < open_ts]
    gap_ref = rth[0]["o"] if rth else (pre[-1]["c"] if pre else None)
    last = rth[-1]["c"] if rth else None
    earlier = [b for b in rth if b["t"] <= rth[-1]["t"] - 300] if rth else []
    return [_pct(gap_ref, prior_close), _pct(last, rth[0]["o"] if rth else None),
            _pct(last, earlier[-1]["c"] if earlier else None)]


def cross_block(session, c_ts):
    """The packet's ``cross`` section at checkpoint epoch ``c_ts`` (None if unavailable)."""
    cross = session.get("cross")
    if not cross:
        return None
    day = session["date"]
    open_ts = checkpoint_ts(day, (session.get("schedule") or {}).get("open") or "09:30")
    rows = {s: _row(cross["minutes"].get(s), cross["prior_close"].get(s), open_ts, c_ts)
            for s in CROSS_SYMBOLS}

    def up(group, col):
        vals = [rows[s][col] for s in group if rows[s][col] is not None]
        return f"{sum(v > 0 for v in vals)}/{len(vals)}" if vals else None

    return {
        "columns": list(COLUMNS),
        "macro": {s: rows[s] for s in MACRO},
        "mega_caps": {s: rows[s] for s in MEGA_CAPS},
        "sectors": {s: rows[s] for s in SECTORS},
        "breadth": {"sectors_up_since_open": up(SECTORS, 1), "mega_caps_up_since_open": up(MEGA_CAPS, 1),
                    "sectors_gapped_up": up(SECTORS, 0)},
    }
