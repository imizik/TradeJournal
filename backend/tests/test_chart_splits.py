"""C0.6 price basis: one split-adjusted basis for minute, daily and weekly charts."""

from datetime import date, datetime, time as wall_time, timedelta, timezone
import json

import httpx
import pytest

from app.engine import alpaca, chart_history as history_module, chart_splits as splits_module
from app.engine.chart_adjust import adjust_daily, adjust_minutes, describe, factor_before, ratio_label, suspect_gaps
from app.engine.chart_history import ChartHistory
from app.engine.chart_math import ET, chart_bars, normalize_bars
from app.engine.chart_splits import ChartSplits, parse_actions

# NVDA's 10-for-1 split, ex-date 2024-06-10 (Alpaca corporate actions, checked live 2026-10-01).
NVDA = [{"ex_date": "2024-06-10", "ratio": 10.0, "new_rate": 10.0, "old_rate": 1.0}]
EX, BEFORE = date(2024, 6, 10), date(2024, 6, 7)


def stamp(day: date, hour=9, minute=30) -> int:
    return int(datetime.combine(day, wall_time(hour, minute), ET).timestamp())


def bar(day: date, close: float, volume: float = 100.0, hour=9, minute=30) -> dict:
    t = stamp(day, hour, minute)
    return {"time": t, "end_time": t + 60, "open": close, "high": close + 1, "low": close - 1, "close": close, "volume": volume, "source": "tradier"}


def daily(day: date, close: float, volume: float = 1000.0) -> dict:
    return {"date": day.isoformat(), "open": close, "high": close + 1, "low": close - 1, "close": close, "volume": volume}


def test_factor_and_minutes_apply_only_before_the_ex_date():
    assert factor_before(NVDA, BEFORE) == 10 and factor_before(NVDA, EX) == 1
    reverse = [{"ex_date": "2024-03-21", "ratio": 0.1}, {"ex_date": "2024-06-10", "ratio": 2.0}]
    assert factor_before(reverse, date(2024, 3, 20)) == pytest.approx(0.2)
    raw = [bar(BEFORE, 1210.0, 50)]
    (adjusted,) = adjust_minutes(raw, BEFORE, NVDA)
    assert (adjusted["close"], adjusted["open"], adjusted["volume"]) == (pytest.approx(121.0), pytest.approx(121.0), 500)
    assert adjusted["time"] == raw[0]["time"] and raw[0]["close"] == 1210.0  # markers key on time; input untouched
    assert adjust_minutes([bar(EX, 121.0)], EX, NVDA)[0]["close"] == 121.0
    assert [ratio_label(10), ratio_label(0.1)] == ["10-for-1", "1-for-10"]


def test_daily_detects_whether_the_provider_already_adjusted():
    adjusted_feed = [daily(BEFORE, 120.88, 41_238_580), daily(EX, 121.79)]
    out, states = adjust_daily(normalize_bars(adjusted_feed, daily=True), NVDA)
    assert states == {"2024-06-10": "provider_adjusted"} and out[0]["close"] == 120.88
    raw_feed = [daily(BEFORE, 1208.8, 4_123_858), daily(EX, 121.79)]
    out, states = adjust_daily(normalize_bars(raw_feed, daily=True), NVDA)
    assert states == {"2024-06-10": "adjusted_here"}
    assert out[0]["close"] == pytest.approx(120.88) and out[0]["volume"] == pytest.approx(41_238_580)
    # A split with no bar after it cannot be verified and is left alone, disclosed.
    only_before = normalize_bars([daily(BEFORE, 1208.8)], daily=True)
    assert adjust_daily(only_before, NVDA) == (only_before, {"2024-06-10": "unverified"})
    # A split outside the window changes nothing and needs no state.
    assert adjust_daily(normalize_bars([daily(EX, 121.79)], daily=True), NVDA)[1] == {}


def test_weekly_and_daily_agree_on_the_adjusted_basis():
    week = [daily(date(2024, 6, 3) + timedelta(days=i), 1200.0 + i * 10) for i in range(5)]
    raw = normalize_bars(week, daily=True)
    adjusted, _ = adjust_daily(raw, NVDA)
    # Provider-adjusted daily (value already /10) stays untouched; raw daily gets divided.
    already = normalize_bars([daily(date(2024, 6, 3) + timedelta(days=i), 120.0 + i) for i in range(5)] + [daily(EX, 121.0)], daily=True)
    fixed, _ = adjust_daily(already, NVDA)
    one_week = chart_bars([], fixed, "1W", "regular")
    day_bars = chart_bars([], fixed, "1D", "regular")
    assert one_week[0]["open"] == day_bars[0]["open"] == 120.0 and one_week[0]["close"] == day_bars[4]["close"] == 124.0
    assert adjusted[0]["close"] == 1200.0  # no bar after the split in this raw window: unverified, untouched


class Session:
    """Alpaca minute pages for two sessions: raw prices on the split's two sides."""

    def __init__(self, monkeypatch):
        self.calls = []
        monkeypatch.setattr(alpaca, "ALPACA_API_KEY", "key")
        monkeypatch.setattr(alpaca, "ALPACA_API_SECRET", "secret")
        monkeypatch.setattr(history_module, "WARMUP", 0)
        monkeypatch.setattr(history_module.httpx, "get", self.get)

    def get(self, url, *, params, headers, timeout):
        self.calls.append(params)
        day = datetime.fromisoformat(params["start"]).astimezone(ET).date()
        price = 1210.0 if day == BEFORE else 121.0
        t = datetime.combine(day, wall_time(15, 59), ET).astimezone(timezone.utc).isoformat()
        first = datetime.combine(day, wall_time(9, 30), ET).astimezone(timezone.utc).isoformat()
        rows = [{"t": first, "o": price, "h": price + 1, "l": price - 1, "c": price, "v": 10},
                {"t": t, "o": price, "h": price + 1, "l": price - 1, "c": price, "v": 10}]
        return httpx.Response(200, json={"bars": rows, "next_page_token": None}, request=httpx.Request("GET", url))


class FixedSplits:
    def __init__(self, info):
        self.info = info

    def get(self, symbol):
        return self.info


KNOWN = {"status": "ok", "splits": NVDA, "as_of": 1_790_000_000, "issue": None}


def test_minute_history_is_adjusted_for_display_while_the_cache_stays_raw(tmp_path, monkeypatch):
    provider = Session(monkeypatch)
    history = ChartHistory(tmp_path, splits=FixedSplits(KNOWN))
    before = stamp(EX, 20, 1)
    page = history.page("NVDA", "5m", "regular", before, limit=4)
    closes = [(datetime.fromtimestamp(b["time"], ET).date().isoformat(), round(b["close"], 6)) for b in page["bars"]]
    assert closes == [("2024-06-07", 121.0), ("2024-06-07", 121.0), ("2024-06-10", 121.0), ("2024-06-10", 121.0)]
    assert page["price_basis"] == "split_adjusted" and page["adjustment"]["warnings"] == []
    assert page["adjustment"]["splits"][0]["label"] == "10-for-1" and page["adjustment"]["splits"][0]["ex_date"] == "2024-06-10"
    assert page["adjustment"]["dividends"] == "unsupported"
    assert page["bars"][0]["volume"] == 100  # 10 shares * 10
    # The stored session is the provider's raw snapshot, and the basis is not a cache key.
    stored = json.loads(history._path("NVDA", BEFORE).read_text())
    assert stored["adjustment"] == "raw" and stored["minutes"][0]["close"] == 1210.0
    # Same data on the next load costs no provider call and still yields the adjusted view.
    calls = len(provider.calls)
    again = ChartHistory(tmp_path, splits=FixedSplits(KNOWN)).page("NVDA", "5m", "regular", before, limit=4)
    assert len(provider.calls) == calls and again["bars"] == page["bars"]


def test_a_missing_split_is_disclosed_and_never_guessed(tmp_path, monkeypatch):
    Session(monkeypatch)
    unknown = {"status": "unknown", "splits": [], "as_of": None, "issue": "unreachable"}
    page = ChartHistory(tmp_path, splits=FixedSplits(unknown)).page("NVDA", "5m", "regular", stamp(EX, 20, 1), limit=4)
    assert page["bars"][0]["close"] == 1210.0  # raw, not adjusted by a guess
    assert page["adjustment"]["status"] == "unknown" and page["adjustment"]["splits"] == []
    text = " ".join(page["adjustment"]["warnings"])
    assert "Split data is unavailable" in text and "jumps 10x between 2024-06-07 and 2024-06-10" in text
    no_service = ChartHistory(tmp_path).page("NVDA", "5m", "regular", stamp(EX, 20, 1), limit=4)
    assert no_service["adjustment"]["status"] == "unknown"


def test_suspect_gaps_only_warns_on_split_like_jumps():
    ordinary = [bar(BEFORE, 100.0), bar(EX, 109.0)]  # a 9% gap is just a gap
    assert suspect_gaps(ordinary) == []
    assert suspect_gaps([bar(BEFORE, 100.0, hour=9), bar(BEFORE, 10.0, hour=10)]) == []  # same day is never an overnight gap
    reverse = suspect_gaps([bar(BEFORE, 10.0), bar(EX, 100.0)])
    assert len(reverse) == 1 and "reverse split" in reverse[0]


def actions(*rows, kind="forward_splits", token=None):
    return {"corporate_actions": {kind: list(rows)}, "next_page_token": token}


def row(ex, new, old, symbol="NVDA"):
    return {"symbol": symbol, "ex_date": ex, "new_rate": new, "old_rate": old}


def test_parse_actions_reads_forward_and_reverse_ratios():
    assert parse_actions(actions(row("2024-06-10", 10, 1)), "NVDA")[0]["ratio"] == 10
    reverse = parse_actions(actions(row("2024-03-21", 1, 10, "ADVM"), kind="reverse_splits"), "ADVM")
    assert reverse[0]["ratio"] == pytest.approx(0.1)
    with pytest.raises(ValueError):
        parse_actions(actions(row("2024-06-10", 0, 1)), "NVDA")


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(alpaca, "ALPACA_API_KEY", "key")
    monkeypatch.setattr(alpaca, "ALPACA_API_SECRET", "secret")
    calls, replies = [], []

    def get(url, *, params, headers, timeout):
        calls.append((url, dict(params)))
        status, body = replies.pop(0)
        return httpx.Response(status, json=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(splits_module.httpx, "get", get)
    return ChartSplits(tmp_path), calls, replies


def test_splits_are_fetched_once_per_day_and_future_splits_wait(service):
    splits, calls, replies = service
    today = date(2026, 10, 1)
    replies.append((200, actions(row("2024-06-10", 10, 1), row("2026-10-02", 2, 1), token=None)))
    first = splits.get("NVDA", today)
    assert first["status"] == "ok" and [s["ex_date"] for s in first["splits"]] == ["2024-06-10"]  # tomorrow's split is not applied yet
    url, params = calls[0]
    assert url.endswith("/v1/corporate-actions") and params["types"] == "forward_split,reverse_split" and params["symbols"] == "NVDA"
    assert splits.get("NVDA", today) == first and len(calls) == 1  # same day: no call, also after a restart
    assert ChartSplits(splits.root).get("NVDA", today) == first and len(calls) == 1
    # On its ex-date the split joins the applied set; a new day refetches once.
    replies.append((200, actions(row("2024-06-10", 10, 1), row("2026-10-02", 2, 1))))
    assert [s["ex_date"] for s in splits.get("NVDA", date(2026, 10, 2))["splits"]] == ["2024-06-10", "2026-10-02"] and len(calls) == 2


def test_a_failed_refresh_keeps_the_last_copy_as_stale_and_no_copy_is_unknown(service):
    splits, calls, replies = service
    replies.extend([(200, actions(row("2024-06-10", 10, 1))), (503, {}), (500, {})])
    assert splits.get("NVDA", date(2026, 10, 1))["status"] == "ok"
    stale = splits.get("NVDA", date(2026, 10, 2))
    assert stale["status"] == "stale" and stale["splits"][0]["ratio"] == 10 and stale["issue"] and stale["as_of"]
    assert "could not be refreshed" in " ".join(describe(stale)["warnings"])
    assert splits.get("AMD", date(2026, 10, 2))["status"] == "unknown"
    assert "Split data is unavailable" in " ".join(describe(splits.get("AMD", date(2026, 10, 2)))["warnings"])
    assert len(calls) == 3  # NVDA, its failed refresh, AMD; each failed symbol then backs off instead of looping
    splits.get("AMD", date(2026, 10, 2))
    splits.get("NVDA", date(2026, 10, 2))
    assert len(calls) == 3


def test_malformed_or_unconfigured_split_data_is_unknown_not_empty(service, monkeypatch):
    splits, calls, replies = service
    replies.append((200, {"corporate_actions": {"forward_splits": [{"symbol": "NVDA", "ex_date": "garbage", "new_rate": 2, "old_rate": 1}]}}))
    assert splits.get("NVDA", date(2026, 10, 1))["status"] == "unknown"
    monkeypatch.setattr(alpaca, "ALPACA_API_KEY", "")
    assert splits.get("QQQ", date(2026, 10, 1))["status"] == "unknown" and len(calls) == 1
    assert splits.get("../x", date(2026, 10, 1))["status"] == "unknown"


@pytest.mark.parametrize("provider_adjusted", [True, False])
def test_workspace_daily_and_weekly_match_whichever_basis_the_provider_used(monkeypatch, provider_adjusted):
    from app.engine import chart_feed as feed_module
    from app.engine.chart_feed import ChartFeed

    monkeypatch.setattr(feed_module.tradier, "TRADIER_API_KEY", "test-secret")
    scale = 1 if provider_adjusted else 10
    days = [daily(date(2024, 6, 3) + timedelta(days=i), (120.0 + i) * scale) for i in range(5)] + [daily(EX, 121.0), daily(date(2024, 6, 11), 122.0)]

    def get(url, params, headers, timeout):
        payload = {"history": {"day": days}} if "history" in url else {"series": None} if "timesales" in url else {"quotes": {"quote": {"symbol": "NVDA", "last": 122}}}
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(feed_module.httpx, "get", get)
    data = ChartFeed(splits=FixedSplits(KNOWN)).workspace("NVDA", ["1D", "1W"], [], "regular")
    daily_bars, weekly = data["panels"]["1D"]["bars"], data["panels"]["1W"]["bars"]
    assert [round(b["close"], 6) for b in daily_bars[:5]] == [120.0, 121.0, 122.0, 123.0, 124.0]
    assert weekly[0]["open"] == 120.0 and weekly[0]["close"] == 124.0 and weekly[1]["open"] == 121.0  # no cliff at the split
    assert data["adjustment"]["daily"] == {"2024-06-10": "provider_adjusted" if provider_adjusted else "adjusted_here"}
    assert data["adjustment"]["basis"] == "split_adjusted" and data["adjustment"]["warnings"] == []
    # Without split data the same raw feed is shown as supplied, with an explicit warning.
    raw = ChartFeed(splits=FixedSplits({"status": "unknown", "splits": [], "as_of": None, "issue": "x"})).workspace("NVDA", ["1D"], [], "regular")
    assert raw["adjustment"]["status"] == "unknown" and any("Split data is unavailable" in w for w in raw["adjustment"]["warnings"])
    if not provider_adjusted:
        assert raw["panels"]["1D"]["bars"][0]["close"] == 1200.0 and any("like a forward split" in w for w in raw["adjustment"]["warnings"])


@pytest.mark.parametrize("damage", [
    lambda s: s.pop("ratio"), lambda s: s.update(ratio="10"), lambda s: s.update(ratio=2.0), lambda s: s.update(ex_date="2024-6-10x"),
])
def test_a_damaged_split_cache_is_refetched_instead_of_crashing_the_chart(service, damage):
    splits, calls, replies = service
    replies.append((200, actions(row("2024-06-10", 10, 1))))
    today = date(2026, 10, 1)
    splits.get("NVDA", today)
    path = splits._path("NVDA")
    record = json.loads(path.read_text())
    damage(record["splits"][0])
    path.write_text(json.dumps(record))
    replies.append((200, actions(row("2024-06-10", 10, 1))))
    again = splits.get("NVDA", today)
    assert len(calls) == 2 and again["status"] == "ok" and again["splits"][0]["ratio"] == 10
