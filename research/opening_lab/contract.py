"""Shared contract for the opening lab: shapes, clocks and scoring rules.

Every module in this package builds against these definitions. Change them
only deliberately: a change alters what every recorded run means.

Design in one paragraph: at each opening checkpoint (09:30–10:00 ET, every five
minutes) a *packet* is frozen from data that was available at that instant.
A model or a rule baseline reads the packet and returns a *forecast*: a
probability that SPY and QQQ will be higher ten minutes after entry, and an
optional trade (LONG/SHORT one symbol, or WAIT). Every checkpoint is scored on
its own, so a session yields up to 14 probability forecasts and 7 take/skip
choices, all comparable across model and baselines on identical inputs.

Shapes
------
SessionData (JSON-serializable dict) — everything known about one session,
including the future. Only ``packet.build_packet`` may read it for decisions,
and it must filter causally. ``evaluate`` reads it for outcomes::

    {
      "date": "2026-07-15",                 # New York session date
      "schedule": {"open": "09:30", "close": "16:00", "early_close": False},
      "symbols": {
        "SPY": {
          "daily":   [Bar1D, ...],          # up to 30 sessions strictly BEFORE date, oldest first
          "minutes": [Bar1m, ...],          # this date, 04:00–11:00 ET, sorted, unique t
          "volume_profile": {"09:30": 1.2e6, ...},  # mean volume per RTH minute
                                            #   09:30–10:59 over the prior 20 sessions
        },
        "QQQ": {...},
      },
      "news":  [NewsItem, ...],             # filled by context.attach_context; may be []
      "macro": [MacroEvent, ...],           # filled by context.attach_context; may be []
      "provenance": {...},                  # free-form: sources, feed, fetched_at, gaps
    }

    Bar1m  = {"t": int epoch seconds of bar START (UTC), "o", "h", "l", "c": float,
              "v": int, "vw": float | None, "n": int | None}
    Bar1D  = {"date": "YYYY-MM-DD", "o", "h", "l", "c": float, "v": int}
    NewsItem = {"id": str, "headline": str, "summary": str, "symbols": [str],
                "source": str, "created_at": ISO-8601 UTC str}
    MacroEvent = {"kind": "cpi"|"fomc"|"jobs"|..., "name": str,
                  "scheduled_at": ISO-8601 UTC str}

Packet — see ``packet.py``; the fields every consumer may rely on are listed
in ``PACKET_FIELDS`` below. Baselines read ONLY packet fields, never SessionData.

Forecast — the one output shape for models and baselines (``FORECAST_SCHEMA``).
"""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
UTC = timezone.utc
SYMBOLS = ("SPY", "QQQ")

# Decision clock -------------------------------------------------------------
CHECKPOINTS_ET = ("09:30", "09:35", "09:40", "09:45", "09:50", "09:55", "10:00")
# A bar is visible at checkpoint C only if it ENDED by C: t + 60 <= C.
BAR_SECONDS = 60
# News is visible only if created_at <= C - NEWS_LAG_SECONDS (provider
# timestamps are not first-seen times; one minute is a conservative margin).
NEWS_LAG_SECONDS = 60
# Live responses must arrive before this; replays record latency against it.
RESPONSE_DEADLINE_SECONDS = 45

# Outcome rule ----------------------------------------------------------------
# Entry: OPEN of the bar starting at C + ENTRY_DELAY_MINUTES (the decision is
# assumed to take under a minute). Exit at horizon h: CLOSE of the bar starting
# at entry_start + (h - 1) minutes, i.e. h full minutes after entry.
ENTRY_DELAY_MINUTES = 1
HORIZONS_MINUTES = (5, 10, 15)
PRIMARY_HORIZON_MINUTES = 10
# Conservative round-trip cost charged to every take, in basis points of the
# underlying (SPY/QQQ spread plus slippage). An assumption, not a broker quote.
ROUND_TRIP_COST_BPS = 1.0

# Packet variants (information ablation) -------------------------------------
# bars   — today's completed RTH minute bars only (the narrow original design)
# market — bars + market context features (gap, premarket, prior day, VWAP, rvol...)
# full   — market + headlines + scheduled macro events
VARIANTS = ("bars", "market", "full")

PACKET_FIELDS = {
    "top": ("version", "variant", "checkpoint_et", "weekday", "minutes_since_open",
            "early_close", "symbols", "news", "macro", "prior_decisions"),
    "symbol": ("bars", "last", "features"),
    # Every feature key is always present in market/full packets (null when
    # unavailable) and the whole "features" value is null in bars packets.
    "features": ("prior_close", "gap_pct", "premarket_high", "premarket_low",
                 "premarket_last", "premarket_volume", "prior_day_high",
                 "prior_day_low", "prior_day_close", "atr20_pct", "session_vwap",
                 "session_high", "session_low", "return_since_open_pct", "rvol"),
}
# packet["symbols"][S]["bars"] = {"columns": BAR_COLUMNS, "rows": [[...], ...]}
# with "et" as "HH:MM" bar start in New York time, completed RTH bars only.
BAR_COLUMNS = ("et", "o", "h", "l", "c", "v")

# Forecast ---------------------------------------------------------------------
ACTIONS = ("WAIT", "LONG", "SHORT")
FORECAST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["spy_p_up", "qqq_p_up", "action", "symbol", "reason"],
    "properties": {
        # Probability the PRIMARY-horizon return (see outcome rule) is > 0.
        "spy_p_up": {"type": "number", "minimum": 0, "maximum": 1},
        "qqq_p_up": {"type": "number", "minimum": 0, "maximum": 1},
        "action": {"type": "string", "enum": list(ACTIONS)},
        "symbol": {"type": ["string", "null"], "enum": ["SPY", "QQQ", None]},
        "reason": {"type": "string", "maxLength": 400},
    },
}


def validate_forecast(value):
    """Return a normalized forecast dict, or raise ValueError naming the defect."""
    if not isinstance(value, dict) or set(value) != set(FORECAST_SCHEMA["required"]):
        raise ValueError("forecast_fields")
    out = {}
    for key in ("spy_p_up", "qqq_p_up"):
        p = value[key]
        if isinstance(p, bool) or not isinstance(p, (int, float)) or not 0 <= p <= 1:
            raise ValueError(f"forecast_{key}")
        out[key] = float(p)
    action, symbol = value["action"], value["symbol"]
    if action not in ACTIONS:
        raise ValueError("forecast_action")
    if action == "WAIT" and symbol is not None:
        raise ValueError("forecast_wait_symbol")
    if action != "WAIT" and symbol not in SYMBOLS:
        raise ValueError("forecast_trade_symbol")
    reason = value["reason"]
    if not isinstance(reason, str) or len(reason) > 400:
        raise ValueError("forecast_reason")
    out.update(action=action, symbol=symbol, reason=reason)
    return out


# Clock helpers ----------------------------------------------------------------
def et_datetime(day, hhmm):
    """Aware New York datetime for a session date (date or ISO str) and 'HH:MM'."""
    if isinstance(day, str):
        day = date.fromisoformat(day)
    hour, minute = (int(x) for x in hhmm.split(":"))
    return datetime.combine(day, time(hour, minute), ET)


def checkpoint_ts(day, hhmm):
    """Epoch seconds of a checkpoint."""
    return int(et_datetime(day, hhmm).timestamp())


def et_hhmm(epoch_seconds):
    """'HH:MM' New York time of an epoch-seconds instant."""
    return datetime.fromtimestamp(epoch_seconds, ET).strftime("%H:%M")


def visible_bars(minutes, checkpoint_epoch):
    """Bars that ended by the checkpoint (the only causal bar rule)."""
    return [b for b in minutes if b["t"] + BAR_SECONDS <= checkpoint_epoch]


def entry_bar_start(day, hhmm):
    return checkpoint_ts(day, hhmm) + ENTRY_DELAY_MINUTES * 60


def plus_minutes(epoch_seconds, minutes):
    return epoch_seconds + int(timedelta(minutes=minutes).total_seconds())
