from datetime import date, datetime, time, timedelta
from decimal import Decimal

from app.engine.premarket_archive import ET
from app.engine.radar_whole_market import daily_inputs
from scripts.radar_whole_market_replay import first_seen

DAY = date(2026, 11, 3)
DAYS = [DAY - timedelta(days=i) for i in range(20, 0, -1)]


def test_liquidity_uses_only_complete_prior_history_and_split_basis():
    class Market:
        def symbols(self, day, kinds):
            assert kinds == ("CS",)
            return ["FLOOR", "BELOW", "NEW"]

        def splits(self, day, symbols):
            assert set(symbols) == {"FLOOR", "SPY"}
            return {"FLOOR": Decimal("0.5")}

        def bars(self, symbols, timeframe, start, end, asof):
            for s in symbols:
                rows = [dict(t=f"{d}T05:00:00Z", c=10, v=2_000_000, vw=10) for d in DAYS + [DAY]]
                if s == "BELOW":
                    rows[0]["v"] -= 1
                    rows[-1]["v"] *= 100
                if s == "NEW":
                    rows.pop(0)
                yield s, rows[:7]
                yield s, rows[7:]

    adv, prior, closing = daily_inputs(Market(), DAY, DAYS, include_close=True)
    assert adv == {"FLOOR": 20_000_000, "SPY": 20_000_000}
    assert prior == {"FLOOR": 5, "SPY": 10}
    assert closing == {"FLOOR": 10, "SPY": 10}


def test_v0_first_seen_uses_completed_minutes_and_closing_side():
    class Market:
        def bars(self, symbols, timeframe, start, end, asof):
            for symbol in symbols:
                rows = []
                for minute in range(39):
                    price = 10 if symbol == "SPY" or minute < 30 else 11
                    if symbol == "GAP" and minute == 31:
                        continue
                    rows.append(dict(t=(start + timedelta(minutes=minute)).isoformat(), o=10, c=price))
                yield symbol, rows

    targets = {"FAST": 10, "GAP": 9, "OPPOSITE": -7}
    result = first_seen(DAY, time(16), Market(), targets, dict.fromkeys([*targets, "SPY"], 10))
    assert result == {"FAST": "10:03", "GAP": "10:05", "OPPOSITE": "miss"}


def test_checkpoint_filters_both_sides_caps_and_publishes_once(tmp_path, monkeypatch):
    from app.engine import radar_outside_scan as scan
    from types import SimpleNamespace

    monkeypatch.setattr(scan, "ROOT", tmp_path)
    slot = datetime.combine(DAY, time(9, 45), ET)
    def snapshot(price, minutes=1):
        return dict(minuteBar=dict(t=(slot-timedelta(minutes=minutes)).isoformat(), c=price),
                    dailyBar=dict(t=slot.replace(hour=0, minute=0).isoformat(), v=1000, vw=30))

    outside = {f"UP{i:02}": 20_000_000 for i in range(11)}
    outside.update(dict.fromkeys(["BEHIND", "PENNY", "STALE", "QUIET"], 30_000_000))
    previous = dict.fromkeys([*outside, "SPY"], 10)
    prices = {s: snapshot(11) for s in outside}
    prices.update(SPY=snapshot(10.2), BEHIND=snapshot(8), PENNY=snapshot(4), STALE=snapshot(20, 2),
                  QUIET=snapshot(10.24))
    calls = []
    def snapshots(group):
        calls.append(group)
        return prices

    prepared = (time(16), outside, previous, {"BEHIND": "Utilities"})
    market = SimpleNamespace(snapshots=snapshots)
    record = scan.capture(slot, prepared, market, clock=lambda: slot)
    assert record["covered"] == 14 and record["requested"] == 15
    assert [r["symbol"] for r in record["rows"]] == ["BEHIND", *(f"UP{i:02}" for i in range(9))]
    assert record["rows"][0] == dict(kind="outside_list", symbol="BEHIND", sector="Utilities", price=8,
        move_vs_spy_pp=-22, avg_dollar_volume=30_000_000, dollar_volume=30_000)
    scan.capture(slot, prepared, market, clock=lambda: slot)
    assert calls == [sorted([*outside, "SPY"])]
    assert scan.checkpoints(DAY.isoformat()) == [record]


def test_denied_sip_records_unavailability_only_during_session(tmp_path, monkeypatch):
    import asyncio
    from app.engine import radar_outside_scan as scan

    monkeypatch.setattr(scan, "ROOT", tmp_path)
    clock = [datetime.combine(DAY, time(9), ET)]
    async def sleep(target):
        clock[0] = max(clock[0], target)
    monkeypatch.setattr(scan, "now", lambda: clock[0])
    monkeypatch.setattr(scan, "sleep_until", sleep)
    prepared = []
    def prepare(day):
        prepared.append(day)
        return time(13), {}, {}, {}
    monkeypatch.setattr(scan, "prepare", prepare)
    def denied(*args):
        raise PermissionError("SIP refused")
    monkeypatch.setattr(scan, "collect", denied)
    asyncio.run(scan.scan_day(DAY))
    assert prepared == [DAY]
    assert [(r["as_of"][11:16], r["status"], r["rows"]) for r in scan.checkpoints(DAY.isoformat())] == [
        (t, "unavailable", []) for t in ["12:00", "10:30", "09:45"]]


def test_universe_preparation_excludes_every_radar_symbol(monkeypatch):
    from app.engine import radar_outside_scan as scan
    from app.engine.radar_store import load_universe
    tracked = {r["symbol"] for r in load_universe()["symbols"]}
    assert len(tracked) == 169
    monkeypatch.setattr(scan, "Market", lambda *_: object())
    monkeypatch.setattr(scan, "sessions", lambda *_: dict.fromkeys([*DAYS, DAY], time(16)))
    prices = dict.fromkeys(tracked | {"OUTSIDE"}, 20.)
    monkeypatch.setattr(scan, "daily_inputs", lambda *_: (dict.fromkeys(prices, 20_000_000), prices, {}))
    assert scan.prepare(DAY)[1] == {"OUTSIDE": 20_000_000}


def test_checkpoint_worker_defaults_off_and_stays_out_of_the_isolated_trial(monkeypatch):
    from app.main import _maybe_start_radar_outside_scan
    monkeypatch.delenv("RADAR_WHOLE_MARKET_ENABLED", raising=False)
    assert _maybe_start_radar_outside_scan() is None
    monkeypatch.setenv("RADAR_WHOLE_MARKET_ENABLED", "true")
    monkeypatch.setenv("TJ_DOT_TRIAL_ENABLED", "true")
    assert _maybe_start_radar_outside_scan() is None


def test_duplicate_split_outside_liquid_roster_does_not_invalidate_ranking(monkeypatch):
    import pytest
    from app.engine.premarket_archive import Market
    market = Market(None, dict(ALPACA_API_KEY="", ALPACA_API_SECRET="", POLYGON_API_KEY=""))
    def action(s, divisor):
        return dict(ticker=s, execution_date=DAY.isoformat(), split_from=1, split_to=divisor)
    rows = [action("OTHER", 1.01), action("OTHER", 1.02), action("ELIGIBLE", 2)]
    monkeypatch.setattr(market, "get", lambda *_: dict(status="OK", results=rows))
    assert market.splits(DAY, {"ELIGIBLE"}) == {"ELIGIBLE": Decimal("0.5")}
    with pytest.raises(ValueError, match="Unexpected split"):
        market.splits(DAY, {"OTHER"})
    with pytest.raises(ValueError, match="Unexpected split"):
        market.splits(DAY)  # R6's original unfiltered contract
