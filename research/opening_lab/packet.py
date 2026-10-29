"""Freeze a causal decision packet from SessionData at one opening checkpoint.

``build_packet`` is the only reader of SessionData for decisions, so it is where
look-ahead is prevented. Everything in a packet is derived from data that was
available at the checkpoint C (epoch seconds of ``checkpoint_et`` on the
session date):

- minute bars: only bars that ENDED by C (``contract.visible_bars``);
  regular-session (RTH) bars start at or after 09:30, premarket bars start
  04:00–09:29;
- daily bars: only sessions strictly before the session date;
- news: only items with ``created_at <= C - NEWS_LAG_SECONDS``;
- macro: the day's *scheduled* events (times are published in advance), each
  marked ``released`` if ``scheduled_at <= C`` else ``upcoming``. No release
  figures are ever included.

The calendar date is never written into a packet (only ``weekday``) so a model
cannot look up what happened. Times are New York "HH:MM".

Feature definitions (market/full variants; every key present, null when not
computable). Prices are rounded to 2 dp, percentages and rvol to 3 dp.

- ``prior_close``: close of the last daily bar before the session (``daily[-1]``).
- ``gap_pct``: 100 * (open / prior_close - 1), where open is the open of the
  first visible RTH bar; before any RTH bar is visible (the 09:30 checkpoint)
  ``premarket_last`` stands in for it.
- ``premarket_high`` / ``premarket_low`` / ``premarket_last`` /
  ``premarket_volume``: max high, min low, last close and summed volume of the
  visible 04:00–09:29 bars.
- ``prior_day_high`` / ``prior_day_low`` / ``prior_day_close``: ``daily[-1]``.
- ``atr20_pct``: mean true range of the last 20 daily bars as % of
  prior_close; TR = max(h - l, |h - prev_c|, |l - prev_c|), and h - l for a bar
  with no earlier bar in the list. Null with fewer than 20 daily bars.
- ``session_vwap``: sum(p * v) / sum(v) over visible RTH bars, p = the bar's
  ``vw`` when present, else the typical price (h + l + c) / 3.
- ``session_high`` / ``session_low``: max high / min low of visible RTH bars.
- ``return_since_open_pct``: 100 * (last RTH close / first RTH open - 1).
- ``rvol``: visible RTH volume divided by the sum of ``volume_profile`` over
  the RTH clock minutes that have ended by C (09:30 .. C-1m). Null at 09:30,
  or when any of those minutes is missing from the profile or it sums to 0.

News selection (full variant): visible items are deduplicated by headline and
kept only if relevant to the index: market-wide first (an index/macro symbol
such as SPY or QQQ in ``symbols``, or a macro / Fed / market term in the
headline), then index heavyweights (``_HEAVYWEIGHTS``) unless the headline is
routine tape (``_NOISE``: halts, analyst actions, explainers). The long tail is
dropped. Within a tier newer wins; the top ``NEWS_LIMIT`` are listed newest
first with ids n1, n2, ...
"""

from datetime import date, datetime
import json
import re

from .contract import (BAR_COLUMNS, CHECKPOINTS_ET, ET, NEWS_LAG_SECONDS, PACKET_FIELDS,
                       SYMBOLS, UTC, VARIANTS, checkpoint_ts, et_hhmm, visible_bars)

VERSION = "opening-lab-packet-v1"
NEWS_LIMIT = 12
HEADLINE_CHARS = 200
SUMMARY_CHARS = 240
NEWS_SYMBOLS = 5
CHARS_PER_TOKEN = 3.5

_MARKET_SYMBOLS = {"SPY", "QQQ", "DIA", "IWM", "VOO", "IVV", "SPX", "$SPX", "NDX", "VIX",
                   "TLT", "ES", "NQ"}
_MARKET_TERMS = re.compile(
    r"\b(fed|fomc|powell|rate cut|rate hike|interest rates?|inflation|cpi|ppi|pce|"
    r"payrolls?|jobs report|jobless|unemployment|gdp|retail sales|ism|consumer "
    r"(?:sentiment|confidence)|treasur(?:y|ies)|yields?|tariffs?|recession|economy|"
    r"stock market|futures|s&p|nasdaq|dow|wall street|equities|crude|oil prices|"
    r"geopolitic\w*|sanctions|war|shutdown)\b",
    re.IGNORECASE,
)
# Index heavyweights: their news can move SPY/QQQ, unlike the long tail.
_HEAVYWEIGHTS = {"AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "AVGO", "TSLA",
                 "BRK.B", "JPM", "LLY", "NFLX", "COST", "AMD"}
# Benzinga's routine single-name tape (halts, analyst actions, explainers) is
# dropped outright: fewer, relevant headlines beat a full list of noise.
_NOISE = re.compile(
    r"(price target|maintains|reiterates|initiates coverage|upgrades|downgrades|"
    r"halted|circuit breaker|reverse (stock )?split|stock of the day|what's going on with|"
    r"shares are trading|shares (are )?(higher|lower)|stock (is )?(rising|falling|rises|falls|gains)|"
    r"52-week|options activity|unusual options|whale)",
    re.IGNORECASE,
)


def _price(x):
    return None if x is None else round(float(x), 2)


def _pct(x):
    return None if x is None else round(float(x), 3)


def _parse_utc(value):
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment


def _clip(text, limit):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _true_ranges(daily):
    out = []
    for i, bar in enumerate(daily):
        h, l = float(bar["h"]), float(bar["l"])
        if i == 0:
            out.append(h - l)
        else:
            pc = float(daily[i - 1]["c"])
            out.append(max(h - l, abs(h - pc), abs(l - pc)))
    return out


def _features(rth, pre, daily, profile, open_ts, c_ts):
    prior = daily[-1] if daily else None
    prior_close = float(prior["c"]) if prior else None

    pre_last = float(pre[-1]["c"]) if pre else None
    first_open = float(rth[0]["o"]) if rth else None
    gap_ref = first_open if first_open is not None else pre_last
    gap = 100 * (gap_ref / prior_close - 1) if gap_ref is not None and prior_close else None

    atr = None
    if len(daily) >= 20 and prior_close:
        atr = 100 * (sum(_true_ranges(daily)[-20:]) / 20) / prior_close

    vwap = None
    volume = sum(int(b["v"]) for b in rth)
    if volume > 0:
        weighted = sum((b["vw"] if b.get("vw") is not None else (b["h"] + b["l"] + b["c"]) / 3)
                       * int(b["v"]) for b in rth)
        vwap = weighted / volume

    ret = 100 * (float(rth[-1]["c"]) / first_open - 1) if rth and first_open else None

    rvol = None
    elapsed = [et_hhmm(t) for t in range(open_ts, c_ts, 60)]
    if elapsed and profile and all(m in profile for m in elapsed):
        expected = sum(float(profile[m]) for m in elapsed)
        if expected > 0:
            rvol = volume / expected

    return {
        "prior_close": _price(prior_close),
        "gap_pct": _pct(gap),
        "premarket_high": _price(max(b["h"] for b in pre)) if pre else None,
        "premarket_low": _price(min(b["l"] for b in pre)) if pre else None,
        "premarket_last": _price(pre_last),
        "premarket_volume": sum(int(b["v"]) for b in pre) if pre else None,
        "prior_day_high": _price(prior["h"]) if prior else None,
        "prior_day_low": _price(prior["l"]) if prior else None,
        "prior_day_close": _price(prior_close),
        "atr20_pct": _pct(atr),
        "session_vwap": _price(vwap),
        "session_high": _price(max(b["h"] for b in rth)) if rth else None,
        "session_low": _price(min(b["l"] for b in rth)) if rth else None,
        "return_since_open_pct": _pct(ret),
        "rvol": _pct(rvol),
    }


def _symbol_block(data, day, open_ts, c_ts, variant):
    data = data or {}
    premarket_ts = checkpoint_ts(day, "04:00")
    seen = visible_bars(data.get("minutes") or [], c_ts)
    rth = [b for b in seen if b["t"] >= open_ts]
    pre = [b for b in seen if premarket_ts <= b["t"] < open_ts]
    daily = [b for b in data.get("daily") or [] if b["date"] < day]
    last_bar = rth[-1] if rth else (pre[-1] if pre else None)
    block = {
        "bars": {
            "columns": list(BAR_COLUMNS),
            "rows": [[et_hhmm(b["t"]), _price(b["o"]), _price(b["h"]), _price(b["l"]),
                      _price(b["c"]), int(b["v"])] for b in rth],
        },
        "last": _price(last_bar["c"]) if last_bar else None,
        "features": None,
    }
    if variant != "bars":
        block["features"] = _features(rth, pre, daily, data.get("volume_profile") or {},
                                      open_ts, c_ts)
    return block


def _relevance(item):
    """0 market-wide, 1 index heavyweight, None for the long tail and routine noise."""
    symbols = {str(s).upper() for s in item.get("symbols") or []}
    headline = item.get("headline") or ""
    if symbols & _MARKET_SYMBOLS or _MARKET_TERMS.search(headline):
        return 0
    if _NOISE.search(headline):
        return None
    if symbols & _HEAVYWEIGHTS:
        return 1
    return None


def _news(items, c_ts):
    cutoff = c_ts - NEWS_LAG_SECONDS
    visible, seen = [], set()
    for item in sorted(items or [], key=lambda i: _parse_utc(i["created_at"]), reverse=True):
        created = int(_parse_utc(item["created_at"]).timestamp())
        key = " ".join((item.get("headline") or "").lower().split())
        if created > cutoff or key in seen:
            continue
        seen.add(key)
        tier = _relevance(item)
        if tier is not None:
            visible.append((created, item, tier))
    ranked = [(created, item) for created, item, _ in sorted(visible, key=lambda row: (row[2], -row[0]))]
    chosen = sorted(ranked[:NEWS_LIMIT], key=lambda pair: -pair[0])
    return [{
        "id": f"n{n}",
        "age_min": (c_ts - created) // 60,
        "headline": _clip(item.get("headline"), HEADLINE_CHARS),
        "summary": _clip(item.get("summary"), SUMMARY_CHARS),
        "symbols": [str(s) for s in (item.get("symbols") or [])][:NEWS_SYMBOLS],
    } for n, (created, item) in enumerate(chosen, 1)]


def _macro(events, day, c_ts):
    out = []
    for event in events or []:
        moment = _parse_utc(event["scheduled_at"]).astimezone(ET)
        if moment.date().isoformat() != day:
            continue
        out.append({
            "time_et": moment.strftime("%H:%M"),
            "kind": event.get("kind"),
            "name": event.get("name"),
            "status": "released" if moment.timestamp() <= c_ts else "upcoming",
        })
    return sorted(out, key=lambda e: (e["time_et"], str(e["name"])))


def _prior_decisions(prior, checkpoint_et):
    out, last = [], None
    for row in prior or ():
        cp = row["checkpoint_et"]
        if cp not in CHECKPOINTS_ET:
            raise ValueError(f"prior_decision_checkpoint:{cp}")
        if cp >= checkpoint_et:
            raise ValueError(f"prior_decision_not_earlier:{cp}")
        if last is not None and cp <= last:
            raise ValueError(f"prior_decisions_order:{cp}")
        last = cp
        out.append({
            "checkpoint_et": cp,
            "action": row["action"],
            "symbol": row["symbol"],
            "spy_p_up": _pct(row["spy_p_up"]),
            "qqq_p_up": _pct(row["qqq_p_up"]),
        })
    return out


def build_packet(session, checkpoint_et, variant, prior_decisions=()):
    """Packet with exactly ``PACKET_FIELDS`` keys, causal at ``checkpoint_et``."""
    if checkpoint_et not in CHECKPOINTS_ET:
        raise ValueError(f"checkpoint:{checkpoint_et}")
    if variant not in VARIANTS:
        raise ValueError(f"variant:{variant}")
    day = session["date"]
    schedule = session.get("schedule") or {}
    open_ts = checkpoint_ts(day, schedule.get("open") or "09:30")
    c_ts = checkpoint_ts(day, checkpoint_et)
    symbols = session.get("symbols") or {}
    full = variant == "full"
    packet = {
        "version": VERSION,
        "variant": variant,
        "checkpoint_et": checkpoint_et,
        "weekday": date.fromisoformat(day).strftime("%A"),
        "minutes_since_open": (c_ts - open_ts) // 60,
        "early_close": bool(schedule.get("early_close", False)),
        "symbols": {s: _symbol_block(symbols.get(s), day, open_ts, c_ts, variant)
                    for s in SYMBOLS},
        "news": _news(session.get("news"), c_ts) if full else [],
        "macro": _macro(session.get("macro"), day, c_ts) if full else [],
        "prior_decisions": _prior_decisions(prior_decisions, checkpoint_et),
    }
    if tuple(packet) != PACKET_FIELDS["top"]:
        raise AssertionError("packet_fields")
    return packet


def render_user_message(packet):
    """The exact user message sent to a model: compact, key-sorted JSON."""
    return json.dumps(packet, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def estimate_tokens(text):
    """Rough token count (chars / 3.5) for size budgeting."""
    return int(len(text) / CHARS_PER_TOKEN + 0.999)
