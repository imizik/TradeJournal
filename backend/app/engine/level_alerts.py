"""Level alerts (Charts C5.1): when an alert fires, and what the phone says. Pure.

An alert watches one price on the chart's split-adjusted basis and fires once
per arming. Its direction is fixed when it is armed: ``up`` when price was
below the level, ``down`` when above.

- **touches**: a trade at the level or beyond it.
- **crosses**: a trade beyond the level, by any amount.
- **closes_beyond**: a closed candle of the alert's interval closes beyond it.

Trades are judged one by one as the stream validates them, before the
browser's one-second coalescing (``chart_stream.trade_event``). Where the
stream was not connected, 1-minute bars stand in: their high or low says a
trade reached the level, and the event says it was seen on bars. A candle is
final ``LATENESS`` seconds after it closes; its close is what Tradier's
1-minute bars hold for it then, and a later correction is not judged again.
"""

from datetime import date, datetime

from app.engine.chart_adjust import factor_before
from app.engine.chart_math import ET

CONDITIONS = ("touches", "crosses", "closes_beyond")
# Candles a "closes beyond" alert can wait for: the intraday intervals the chart draws.
CLOSE_INTERVALS = ("1m", "3m", "5m", "15m", "30m", "1h", "4h")
SESSIONS = ("regular", "extended")
MAX_ACTIVE = 20
MAX_SYMBOLS = 5
LATENESS = 30  # seconds after a candle's close before its close is judged
LABEL_MAX = 60


def direction(reference: float, level: float) -> str | None:
    """Which way price must move to reach ``level`` from ``reference``; None when it is there already."""
    if reference < level:
        return "up"
    if reference > level:
        return "down"
    return None


def trade_fires(condition: str, way: str, level: float, price: float) -> bool:
    """One validated trade against a touches/crosses alert."""
    if condition == "touches":
        return price >= level if way == "up" else price <= level
    if condition == "crosses":
        return price > level if way == "up" else price < level
    return False


def minute_fires(condition: str, way: str, level: float, bar: dict) -> bool:
    """A 1-minute bar standing in for the stream: its extreme reached the level."""
    return trade_fires(condition, way, level, bar["high"] if way == "up" else bar["low"])


def close_fires(way: str, level: float, bar: dict) -> bool:
    return bar["close"] > level if way == "up" else bar["close"] < level


def final(bars: list[dict], now: float, after: float) -> list[dict]:
    """Candles that closed after ``after`` and have been final for ``LATENESS`` seconds."""
    return [bar for bar in bars if bar["end_time"] > after and bar["end_time"] + LATENESS <= now]


def on_today_basis(price: float, created_on: date, splits: list[dict]) -> float:
    """An alert's price moved by every split after the day it was made, as a saved level is."""
    return price / factor_before(splits, created_on)


def _price(value: float) -> str:
    return f"{value:,.2f}" if abs(value) >= 1 else f"{value:.4f}"


def _clock(stamp: float, seconds: bool = True) -> str:
    moment = datetime.fromtimestamp(stamp, ET)
    text = moment.strftime("%I:%M:%S %p" if seconds else "%I:%M %p").lstrip("0")
    return f"{text} ET"


def message(alert: dict, event: dict) -> tuple[str, str]:
    """The phone's title and body: the symbol, the level, the price and when it happened.

    ``alert``: symbol, condition, interval, direction, label. ``event``: level,
    price, event_at (epoch), source (stream, minute_bars or closed_bar),
    bar_time and detected_at (epoch).
    """
    side = "above" if alert["direction"] == "up" else "below"
    level, price = _price(event["level"]), _price(event["price"])
    symbol = alert["symbol"]
    if alert["condition"] == "closes_beyond":
        title = f"{symbol} {alert['interval']} closed {side} {level}"
        body = f"Close {price}, the {_clock(event['bar_time'], False).removesuffix(' ET')}–{_clock(event['event_at'], False)} candle."
    else:
        verb = "touched" if alert["condition"] == "touches" else "crossed"
        title = f"{symbol} {verb} {level}" if alert["condition"] == "touches" else f"{symbol} crossed {side} {level}"
        seen = "trade" if event["source"] == "stream" else "1-minute bar " + ("high" if alert["direction"] == "up" else "low")
        when = _clock(event["event_at"]) if event["source"] == "stream" else f"the {_clock(event['event_at'], False)} minute"
        body = f"{verb.capitalize()} at {price} ({seen}), {when}."
    if alert.get("label"):
        body += f" Alert on {alert['label']}."
    late = event["detected_at"] - event["event_at"]
    if late > 120:
        body += f" Noticed {round(late / 60)} min after it happened."
    return title, body
