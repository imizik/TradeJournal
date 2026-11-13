"""Entry skill study on invented bars and trades, with hand-calculated moves."""

from datetime import date
import json
from pathlib import Path
import random

import pytest

from scripts import entry_skill_study as s
from scripts import exit_counterfactual_study as x

DAY = date(2026, 5, 6)  # a Wednesday with ten ordinary sessions either side


def flat(price: float = 100.0, start: int = s.OPEN, end: int = s.CLOSE) -> dict:
    return {m: (price, price) for m in range(start, end)}


def ramp(per_minute: float, start: int = s.OPEN, end: int = s.CLOSE, base: float = 100.0) -> dict:
    """Each bar opens where the last closed and adds ``per_minute`` dollars."""
    return {m: (base + (m - start) * per_minute, base + (m - start + 1) * per_minute) for m in range(start, end)}


def trade(tid="t1", ticker="AAA", option_type="call", pnl=50.0, premium=500.0, status="closed") -> dict:
    return {"id": tid, "ticker": ticker, "option_type": option_type, "strike": 100, "expiration": "2026-05-08",
            "status": status, "opened_at": "2026-05-06T10:15:00", "closed_at": "2026-05-06T11:00:00",
            "realized_pnl": pnl, "total_premium_paid": premium, "account_type": "roth_ira"}


def fills(tid="t1", entry="2026-05-06T10:15:00", leave="2026-05-06T11:00:00") -> list[dict]:
    out = [{"trade_id": tid, "fill_id": f"{tid}-0", "role": "entry", "side": x.ENTRY, "contracts": 1, "price": 5.0,
            "executed_at": entry}]
    if leave:
        out.append({"trade_id": tid, "fill_id": f"{tid}-1", "role": "exit", "side": x.EXIT, "contracts": 1,
                    "price": 5.5, "executed_at": leave})
    return out


def world(sessions: dict):
    return lambda ticker, day: sessions.get((ticker, day))


# ---------------------------------------------------------------- clock


def test_move_starts_at_the_next_minutes_open_and_ends_at_the_horizon_bars_close():
    session = flat()
    session[616] = (100.0, 100.5)   # 10:16, the minute after a 10:15 entry
    session[645] = (101.5, 102.0)   # reference 616 + 30 - 1
    assert s.signed_move(session, 615, 30, 1, s.CLOSE) == pytest.approx(2.0)
    assert s.signed_move(session, 615, 30, -1, s.CLOSE) == pytest.approx(-2.0)


def test_nothing_at_or_before_the_entry_minute_is_read():
    session = ramp(0.01)
    before = s.signed_move(session, 615, 30, 1, s.CLOSE)
    for m in range(s.OPEN, 616):
        session[m] = (1.0, 999.0)
    assert s.signed_move(session, 615, 30, 1, s.CLOSE) == before


def test_reference_within_three_minutes_else_unscored():
    session = flat()
    del session[616], session[617]
    session[618] = (50.0, 50.0)
    session[647] = (55.0, 55.0)  # 618 + 30 - 1
    assert s.signed_move(session, 615, 30, 1, s.CLOSE) == pytest.approx(10.0)
    del session[618]
    assert s.signed_move(session, 615, 30, 1, s.CLOSE) is None


def test_horizon_bar_falls_back_three_minutes_and_no_further():
    session = flat()
    for m in (645, 644, 643):
        del session[m]
    session[642] = (100.0, 103.0)
    assert s.signed_move(session, 615, 30, 1, s.CLOSE) == pytest.approx(3.0)
    del session[642]
    assert s.signed_move(session, 615, 30, 1, s.CLOSE) is None


def test_a_horizon_past_the_close_is_unscored_and_half_days_close_at_one():
    session = flat()
    assert s.signed_move(session, 929, 30, 1, s.CLOSE) is not None   # 15:29 entry, ends at the 15:59 bar
    assert s.signed_move(session, 930, 30, 1, s.CLOSE) is None
    assert s.close_minute(date(2025, 11, 28)) == s.EARLY_CLOSE
    assert s.signed_move(session, 760, 30, 1, s.EARLY_CLOSE) is None


def test_session_bars_keep_only_the_regular_session_of_that_day():
    raw = [{"t": "2026-05-06T13:29:00Z", "o": 1, "c": 1}, {"t": "2026-05-06T13:30:00Z", "o": 2, "c": 3},
           {"t": "2026-05-06T19:59:00Z", "o": 4, "c": 5}, {"t": "2026-05-06T20:00:00Z", "o": 6, "c": 6},
           {"t": "2026-05-07T13:30:00Z", "o": 7, "c": 7}]
    assert s.session_bars(raw, DAY) == {570: (2.0, 3.0), 959: (4.0, 5.0)}


# ---------------------------------------------------------------- controls


def test_timing_minutes_stay_in_the_bucket_and_five_minutes_away():
    minutes = s.timing_minutes(615, s.CLOSE)
    assert minutes[0] == 600 and minutes[-1] == 689
    assert 610 in minutes and 620 in minutes and not any(611 <= m <= 619 for m in minutes)
    assert s.timing_minutes(775, s.EARLY_CLOSE)[-1] == 770          # bucket cut at a 13:00 close, then the gap
    whole = s.timing_minutes(615, s.CLOSE, whole=True)
    assert whole[0] == s.OPEN and whole[-1] == s.CLOSE - 1


def test_neighbor_sessions_skip_weekends_and_holidays():
    days = s.neighbor_sessions(date(2026, 5, 26))  # the day after Memorial Day
    assert len(days) == 20 and date(2026, 5, 25) not in days and all(d.weekday() < 5 for d in days)
    assert days[9] == date(2026, 5, 22) and days[10] == date(2026, 5, 27)


def test_a_baseline_needs_five_scored_controls():
    assert s.control_mean([1.0, None, 2.0, 3.0, None, 4.0]) is None
    assert s.control_mean([1.0, 2.0, 3.0, 4.0, 5.0, None]) == pytest.approx(3.0)


# ---------------------------------------------------------------- one trade


def test_an_entry_before_a_jump_beats_every_control():
    own = flat()
    for m in range(630, s.CLOSE):
        own[m] = (102.0, 102.0)                       # the stock gaps 2% at 10:30 and stays
    sessions = {("AAA", DAY): own}
    for d in s.neighbor_sessions(DAY):
        sessions[("AAA", d)] = flat()
    for t in s.CORE_UNIVERSE:
        sessions[(t, DAY)] = flat()
    row, reason = s.score_trade(trade(), fills(), world(sessions))
    assert reason is None and row["move"]["30"] == pytest.approx(2.0)
    assert row["edge"]["day"]["30"] == pytest.approx(2.0) and row["edge"]["stock"]["30"] == pytest.approx(2.0)
    # bucket 10:00-11:30, minutes 600-610 and 620-689: a control's window reaches the jump when it enters before 10:30
    controls = [m for m in s.timing_minutes(615, s.CLOSE)]
    caught = sum(1 for m in controls if m + 1 <= 629 <= m + 30)
    later = sum(1 for m in controls if m + 1 > 629)
    assert caught + later == len(controls)
    assert row["edge"]["timing"]["30"] == pytest.approx(2.0 - 2.0 * caught / len(controls))


def test_a_put_reads_the_same_move_with_the_sign_turned():
    own = flat()
    for m in range(630, s.CLOSE):
        own[m] = (102.0, 102.0)
    sessions = {("AAA", DAY): own, **{("AAA", d): flat() for d in s.neighbor_sessions(DAY)}}
    row, _ = s.score_trade(trade(option_type="put"), fills(), world(sessions))
    assert row["side"] == "put" and row["move"]["30"] == pytest.approx(-2.0) and row["edge"]["day"]["30"] == pytest.approx(-2.0)
    assert row["edge"]["stock"]["30"] is None            # no comparison names had bars


def test_a_steady_market_gives_no_edge():
    steady = {m: (100.0 * 1.0001 ** (m - s.OPEN), 100.0 * 1.0001 ** (m - s.OPEN + 1)) for m in range(s.OPEN, s.CLOSE)}
    sessions = {("AAA", DAY): steady, **{("AAA", d): steady for d in s.neighbor_sessions(DAY)},
                **{(t, DAY): steady for t in s.CORE_UNIVERSE}}
    row, _ = s.score_trade(trade(), fills(), world(sessions))
    for name in s.BASELINES + s.EXTRA:
        assert row["edge"][name]["30"] == pytest.approx(0.0, abs=1e-9)


def test_exclusions_and_the_index_mapping():
    assert s.score_trade(trade(), [], world({}))[1] == "no buy_to_open fill"
    assert s.score_trade(trade(), fills(entry="2026-05-06T16:05:00"), world({}))[1] == "first entry outside the regular session"
    assert s.score_trade(trade(), fills(), world({}))[1] == "no minute bars for the underlying on the entry session"
    row, _ = s.score_trade(trade(ticker="SPXW"), fills(), world({("SPY", DAY): flat()}))
    assert row["underlying"] == "SPY" and row["period"] == "check"


def test_contract_cost_only_for_trades_closed_in_their_entry_session():
    own = ramp(0.01)
    right = s.contract_cost_row(trade(pnl=-20.0), fills(), own, s.first_entry(fills()), 1)
    assert right == {"stock_right": True, "option_won": False, "return_pct": pytest.approx(-4.0)}
    assert s.contract_cost_row(trade(pnl=-20.0), fills(), own, s.first_entry(fills()), -1)["stock_right"] is False
    overnight = fills(leave="2026-05-07T10:00:00")
    assert s.contract_cost_row(trade(), overnight, own, s.first_entry(overnight), 1) is None
    assert s.contract_cost_row(trade(status="expired"), fills(leave=None), own, s.first_entry(fills()), 1) is None


# ---------------------------------------------------------------- summary


def rows_with(edge_by_day: dict[str, list[float]], period="exploration", side="call") -> list[dict]:
    return [{"id": f"{d}-{i}", "day": d, "period": period, "side": side, "move": {"15": v, "30": v, "60": v}, "cost": None,
             "edge": {name: {"15": v, "30": v, "60": v} for name in s.BASELINES + s.EXTRA}}
            for d, values in edge_by_day.items() for i, v in enumerate(values)]


def test_the_interval_resamples_days_not_trades():
    one_day = [("2026-05-06", v) for v in (1.0, 2.0, 3.0)]
    interval, error = s.day_interval(one_day, random.Random(1))
    assert interval == [2.0, 2.0] and error == 0.0     # one day resampled is always itself
    spread = [(f"2026-05-{d:02d}", float(d % 3)) for d in range(1, 21)]
    interval, error = s.day_interval(spread, random.Random(1))
    assert interval[0] < 0.95 < interval[1] and error > 0


def test_decisions():
    good = rows_with({f"2026-01-{d:02d}": [0.5, 0.6] for d in range(5, 25)}) + \
        rows_with({f"2026-05-{d:02d}": [0.4, 0.7] for d in range(4, 24)}, period="check")
    b = s.summarize_baseline(good, "day", random.Random(s.SEED))
    assert b["decision"] == "beats chance" and b["large_enough_to_matter"] is True and b["n"] == 80 and b["days"] == 40
    one_period = rows_with({f"2026-01-{d:02d}": [0.5, 0.6] for d in range(5, 25)})
    assert s.summarize_baseline(one_period, "day", random.Random(s.SEED))["decision"] == "no evidence either way"
    bad = [dict(r, edge={n: {h: -v for h, v in e.items()} for n, e in r["edge"].items()}) for r in good]
    assert s.summarize_baseline(bad, "day", random.Random(s.SEED))["decision"] == "worse than chance"
    small = rows_with({f"2026-01-{d:02d}": [0.05, 0.06] for d in range(5, 25)}) + \
        rows_with({f"2026-05-{d:02d}": [0.04, 0.07] for d in range(4, 24)}, period="check")
    b = s.summarize_baseline(small, "day", random.Random(s.SEED))
    assert b["decision"] == "beats chance" and b["large_enough_to_matter"] is False
    noisy = rows_with({f"2026-01-{d:02d}": [(-1) ** d * 1.0] for d in range(5, 25)}) + \
        rows_with({f"2026-05-{d:02d}": [(-1) ** d * 1.0] for d in range(4, 24)}, period="check")
    assert s.summarize_baseline(noisy, "day", random.Random(s.SEED))["decision"] == "no evidence either way"


def test_contract_cost_table_counts_each_cell():
    rows = rows_with({"2026-05-06": [0.1, 0.1, 0.1]})
    rows[0]["cost"] = {"stock_right": True, "option_won": False, "return_pct": -10.0}
    rows[1]["cost"] = {"stock_right": True, "option_won": False, "return_pct": -30.0}
    rows[2]["cost"] = {"stock_right": False, "option_won": True, "return_pct": 5.0}
    table = s.contract_cost(rows)
    assert table["covered"] == 3
    assert table["cells"]["stock right, option lost"] == {"n": 2, "mean_return_pct": -20.0}
    assert table["cells"]["stock wrong, option won"] == {"n": 1, "mean_return_pct": 5.0}


# ---------------------------------------------------------------- end to end


def write_bars(cache: Path, ticker: str, day: date, session: dict) -> None:
    folder = cache / "stocks" / "1Min" / s.FEED / ticker
    folder.mkdir(parents=True, exist_ok=True)
    raw = [{"t": f"{day.isoformat()}T{(m + 240) // 60:02d}:{(m + 240) % 60:02d}:00Z", "o": o, "c": c}
           for m, (o, c) in sorted(session.items())]   # New York is UTC-4 in May
    (folder / f"{day.isoformat()}.json").write_text(json.dumps(raw))


def test_run_reads_the_cache_and_writes_outside_results(tmp_path):
    cache, out = tmp_path / "cache", tmp_path / "out"
    jump = flat()
    for m in range(630, s.CLOSE):
        jump[m] = (102.0, 102.0)
    write_bars(cache, "AAA", DAY, jump)
    for d in s.neighbor_sessions(DAY):
        write_bars(cache, "AAA", d, flat())
    extract = tmp_path / "trades.json"
    extract.write_text(json.dumps({"protocol_id": x.PROTOCOL_ID, "trades": [trade(), trade(tid="t2", ticker="ZZZ")],
                                   "fills": fills() + fills(tid="t2")}))
    results = s.run(extract, cache, out)
    assert results["scored"] == 1 and results["excluded"] == {"no minute bars for the underlying on the entry session": 1}
    assert results["provenance"]["extract_is_registered"] is False
    assert results["baselines"]["day"]["horizons"]["30"] == {"n": 1, "mean": 2.0}
    assert results["baselines"]["stock"]["n"] == 0 and results["baselines"]["stock"]["no_controls"] == 1
    assert results["baselines"]["stock"]["decision"] == "no evidence either way"
    assert (out / "entry-skill" / "results.json").exists() and (out / "entry-skill" / "trades.jsonl").exists()
    wanted = s.needed(*s.load(extract))
    assert wanted[DAY] >= {"AAA", "ZZZ", *s.CORE_UNIVERSE} and wanted[s.neighbor_sessions(DAY)[0]] == {"AAA", "ZZZ"}


def test_the_extract_must_be_the_exit_study_extract(tmp_path):
    other = tmp_path / "x.json"
    other.write_text(json.dumps({"protocol_id": "something-else", "trades": [], "fills": []}))
    with pytest.raises(SystemExit):
        s.load(other)
