"""The copilot's macro series and history base rates (docs/copilot-lab.md § Macro and base rates). Offline: FRED and the
chart feed are stubbed."""
from datetime import date, datetime, timedelta

import pytest

from app.ai import copilot, copilot_macro as m, copilot_tools
from app.engine.chart_math import ET
from tests.test_copilot import _text, _turn


def csv(rows):
    return "observation_date,X\n" + "".join(f"{d.isoformat()},{v}\n" for d, v in rows)


def test_observations_skip_missing_values_and_cut_before_a_day():
    text = "observation_date,DGS10\n2026-10-28,5.05\n2026-10-29,.\n2026-10-30,4.94\n"
    assert m.observations(text) == [(date(2026, 10, 28), 5.05), (date(2026, 10, 30), 4.94)]
    assert m.observations(text, until=date(2026, 10, 30)) == [(date(2026, 10, 28), 5.05)]


def test_a_rate_changes_in_basis_points_a_level_in_percent_an_index_by_difference():
    end = date(2026, 10, 30)
    rows = [(end - timedelta(days=d), v) for d, v in ((364, 4.0), (91, 4.5), (30, 5.0), (7, 4.9), (0, 4.94))]
    rate = m.summarize("DGS10", "10y", "rate", sorted(rows))
    assert (rate["value"], rate["chg_1w"], rate["chg_1m"], rate["chg_3m"]) == (4.94, 4.0, -6.0, 44.0)
    assert (rate["low_1y"], rate["high_1y"], rate["range_pct_1y"]) == (4.0, 5.0, 94)
    assert m.summarize("DCOILWTICO", "oil", "level", sorted(rows))["chg_1m"] == pytest.approx(-1.2)
    assert m.summarize("NFCI", "nfci", "index", sorted(rows))["chg_1w"] == pytest.approx(0.04)
    assert m.summarize("X", "x", "rate", []) == {"id": "X", "label": "x", "state": "unavailable"}


def test_one_failed_series_leaves_the_rest_standing():
    now = datetime(2026, 11, 2, 12, tzinfo=ET).timestamp()
    good = csv([(date(2026, 10, 1), 3.0), (date(2026, 10, 30), 3.4)])

    def fetch(series_id, start, at):
        return (None, None) if series_id == "NFCI" else (good, at)
    out = m.macro(now, fetch=fetch)
    assert out["state"] == "partial" and out["latest_date"] == "2026-10-30" and "as_of" not in out  # a date is not a time
    assert [r for r in out["series"] if r["id"] == "NFCI"] == [{"id": "NFCI", "label": m.SERIES[-1][1], "state": "unavailable"}]
    assert out["fetched_at"].startswith("2026-11-02T12:00")


def test_a_stale_cache_is_used_and_said_when_fred_is_down(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "FRED_DIR", tmp_path)
    (tmp_path / "DGS10.csv").write_text(csv([(date(2026, 10, 30), 4.94)]))
    old = (tmp_path / "DGS10.csv").stat().st_mtime

    def down(*_):
        raise OSError("no network")
    monkeypatch.setattr(m, "_fetch", down)
    text, stamp = m._cached("DGS10", date(2025, 9, 1), old + m.FRED_TTL_S + 1)
    assert "4.94" in text and stamp == old
    assert m._cached("DGS2", date(2025, 9, 1), old) == (None, None)


def bars(closes, end=date(2026, 10, 30)):
    days, day = [], end
    while len(days) < len(closes):
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    return [{"time": int(datetime(d.year, d.month, d.day, 16, tzinfo=ET).timestamp()), "close": c} for d, c in zip(reversed(days), closes)]


def test_base_rates_count_each_drawdown_once_against_the_baseline():
    # A year flat at 100, a drop to 75 that recovers to 110, flat, then today 20% off the 110 high.
    closes = [100.0] * 260 + [90.0, 80.0, 75.0] + [80.0 + i for i in range(31)] + [110.0] * 140 + [88.0]
    out = m.base_rates("XYZ", bars(closes))
    assert out["state"] == "ok" and out["threshold_pct"] == 20 and out["current"]["drawdown_pct"] == -20.0
    first, now = out["recent"]
    assert first["drawdown_pct"] == -20.0 and first["fwd_5d_pct"] == pytest.approx(83 / 80 * 100 - 100)
    assert first["further_drop_63d_pct"] == pytest.approx(-6.25) and first["recovered_high_in_days"] == 22  # back to the 100 high it fell from
    assert now["ongoing"] is True and "fwd_5d_pct" not in now
    assert out["episodes"] == 2 and out["horizons"]["5d"]["episodes"]["n"] == 1
    assert out["horizons"]["5d"]["baseline"]["n"] == 179  # every day from the first full year on and out["recovered_high"] == {"of": 1, "recovered": 1, "median_days": 22}


def test_base_rates_need_history_and_a_drawdown():
    assert m.base_rates("NEW", bars([10.0] * 100))["state"] == "unavailable"
    flat = m.base_rates("SPY", bars([100.0] * 400))
    assert flat["state"] == "not_in_drawdown" and flat["current"]["drawdown_pct"] == 0.0
    assert m.base_rates("SPY", bars([100.0] * 400), drawdown_pct=10)["episodes"] == 0


@pytest.mark.parametrize("args", [{"symbol": "SMH", "drawdown_pct": 2}, {"symbol": "SMH", "drawdown_pct": 81}, {"symbol": "SMH", "drawdown_pct": True},
                                  {"symbol": "SMH", "drawdown_pct": float("nan")}, {"symbol": "../x"}])
def test_base_rate_inputs_are_bounded(args):
    with pytest.raises(copilot_tools.ToolInputError):
        copilot_tools.validate("get_base_rates", args)


def test_replay_cuts_the_history_before_the_frozen_day(monkeypatch):
    closes = [100.0] * 400 + [70.0]
    monkeypatch.setattr(m, "history_bars", lambda symbol, today, live=True: bars(closes, end=date(2026, 10, 30)))
    out = m.replay_base_rates("XYZ", None, datetime(2026, 10, 30, 11, tzinfo=ET))
    assert out["current"]["date"] == "2026-10-29" and out["state"] == "not_in_drawdown" and "before 2026-10-30" in out["cut"]


def test_the_fixture_turns_read_both_tools():
    rates = _turn([{"role": "user", "content": "How do drawdowns like this usually end for NBIS?"}], copilot.FakeAdapter(0))
    assert [e["name"] for e in rates if e["type"] == "tool" and e.get("status") == "ok"][-1] == "get_base_rates"
    assert "base rates" in _text(rates) and "baseline" in _text(rates)
    macro = _turn([{"role": "user", "content": "What are credit spreads and yields doing?"}], copilot.FakeAdapter(0))
    assert "get_macro" in [e["name"] for e in macro if e["type"] == "tool"] and "FRED" in _text(macro)
