"""The market backdrop from one recorded Radar pass: benchmark rows kept, computed as Movers now computes them."""
from app.engine import radar_regime
from tests.test_radar_movers import UNIVERSE, _pass, _q, _quotes


def test_benchmark_day_keeps_the_rows_movers_drops():
    latest = _pass("14:34")
    marks = radar_regime.benchmark_day(UNIVERSE, _quotes(), None, latest=latest)
    assert set(marks) == {"SPY", "QQQ", "SMH"}  # the benchmark ETFs only; stocks are the movers' business
    assert marks["SPY"] == {"last": 99.0, "day_pct": -1.0, "from_open_pct": -1.0, "open_gap_pct": 0.0, "last_15m_pct": None}
    assert marks["SMH"]["day_pct"] == -4.0


def test_day_moves_takes_the_earlier_pass_for_15_minutes_and_skips_unusable_quotes():
    latest, earlier = _pass("14:34"), _pass("14:19")
    earlier_quotes = [_q("SPY", 100.0, minute="14:19"), _q("AAA", 95.0, minute="14:19")]
    moves = radar_regime.day_moves(UNIVERSE, _quotes(), earlier_quotes, latest=latest, earlier=earlier, symbols=["SPY", "AAA", "DDD", "ZZZ"])
    assert moves["SPY"]["last_15m_pct"] == -1.0 and moves["AAA"]["last_15m_pct"] == round((90 / 95 - 1) * 100, 3)
    assert moves["AAA"]["from_open_pct"] == round((90 / 91 - 1) * 100, 3) and moves["AAA"]["open_gap_pct"] == -9.0
    assert "DDD" not in moves and "ZZZ" not in moves  # a zero price, and a symbol Radar does not track, are missing, never 0%


def test_an_earlier_quote_outside_its_pass_leaves_15_minutes_blank():
    latest, earlier = _pass("14:34"), _pass("14:19")
    stale = [_q("SPY", 100.0, minute="14:34")]  # retrieved after the earlier pass finished
    moves = radar_regime.day_moves(UNIVERSE, _quotes(), stale, latest=latest, earlier=earlier, symbols=["SPY"])
    assert moves["SPY"]["last_15m_pct"] is None


def test_sector_of_reads_the_universe():
    assert radar_regime.sector_of(UNIVERSE, "AAA") == "SMH"
    assert radar_regime.sector_of(UNIVERSE, "CCC") is None and radar_regime.sector_of(UNIVERSE, "SPY") is None
    assert radar_regime.sector_of(UNIVERSE, "NOPE") is None
