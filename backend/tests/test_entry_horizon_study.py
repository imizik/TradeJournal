"""Entry horizon study on invented bars and closes, with hand-calculated moves."""

from datetime import date
import json
import random

import pytest

from scripts import entry_horizon_study as h
from scripts import entry_skill_study as e
from scripts import exit_counterfactual_study as x

DAY = date(2026, 5, 6)  # a Wednesday; the next sessions are May 7, 8, 11, 12, 13
AFTER = ["2026-05-07", "2026-05-08", "2026-05-11", "2026-05-12", "2026-05-13"]


def flat(price=100.0):
    return {m: (price, price) for m in range(e.OPEN, e.CLOSE)}


def trade(tid="t1", ticker="AAA", option_type="call", closed="2026-05-06T11:00:00"):
    return {"id": tid, "ticker": ticker, "option_type": option_type, "strike": 100, "expiration": "2026-05-15",
            "status": "closed", "opened_at": "2026-05-06T10:15:00", "closed_at": closed, "realized_pnl": 10.0,
            "total_premium_paid": 500.0, "account_type": "roth_ira"}


def fills(tid="t1"):
    return [{"trade_id": tid, "fill_id": f"{tid}-0", "role": "entry", "side": x.ENTRY, "contracts": 1, "price": 5.0,
             "executed_at": "2026-05-06T10:15:00"}]


def closes(symbols, special=None):
    """Every symbol closes at 100 on every session from April 20 to May 22; ``special`` overrides {symbol: {day: close}}."""
    days = [d.isoformat() for d in e.neighbor_sessions(DAY)] + ["2026-05-06"]
    table = {s: {d: 100.0 for d in days} for s in symbols}
    for s, rows in (special or {}).items():
        table[s].update(rows)
    return table


def world(sessions):
    return lambda ticker, day: sessions.get((ticker, day))


def everything(special=None):
    symbols = ["AAA", "SPY", *e.CORE_UNIVERSE]
    raw = closes(symbols, special)
    sessions = {("AAA", DAY): flat(), **{("AAA", d): flat() for d in e.neighbor_sessions(DAY)},
                **{(t, DAY): flat() for t in e.CORE_UNIVERSE}}
    return world(sessions), h.Daily(raw, {s: dict(v) for s, v in raw.items()})


# ---------------------------------------------------------------- prices


def test_reference_is_the_next_minutes_open():
    session = flat()
    session[616] = (101.0, 105.0)
    assert h.reference(session, 615) == 101.0
    del session[616], session[617], session[618]
    assert h.reference(session, 615) is None


def test_moves_to_each_close_count_sessions_not_calendar_days():
    raw = closes(["AAA", "SPY"], {"AAA": {"2026-05-06": 102.0, AFTER[0]: 104.0, AFTER[2]: 110.0, AFTER[4]: 90.0}})
    daily = h.Daily(raw, {s: dict(v) for s, v in raw.items()})
    assert daily.moves("AAA", "2026-05-06", 100.0, 1) == {"0": pytest.approx(2.0), "1": pytest.approx(4.0),
                                                           "3": pytest.approx(10.0), "5": pytest.approx(-10.0)}
    assert daily.moves("AAA", "2026-05-06", 100.0, -1)["1"] == pytest.approx(-4.0)
    assert daily.overnight("AAA", "2026-05-06", 1) == pytest.approx((104 / 102 - 1) * 100)


def test_a_split_between_entry_and_horizon_does_not_look_like_a_crash():
    raw = closes(["AAA", "SPY"], {"AAA": {"2026-05-06": 100.0, AFTER[0]: 11.0}})    # 10-for-1 overnight, then +10%
    split = {s: dict(v) for s, v in raw.items()}
    split["AAA"]["2026-05-06"] = 10.0                                                # history put on the new basis
    daily = h.Daily(raw, split)
    assert daily.moves("AAA", "2026-05-06", 100.0, 1)["1"] == pytest.approx(10.0)
    assert daily.moves("AAA", "2026-05-06", 100.0, 1)["0"] == pytest.approx(0.0)


def test_missing_closes_and_the_end_of_the_data_are_unscored():
    raw = closes(["AAA", "SPY"])
    daily = h.Daily(raw, {s: dict(v) for s, v in raw.items()})
    last = daily.sessions[-1]
    assert daily.moves("AAA", last, 100.0, 1) == {"0": pytest.approx(0.0), "1": None, "3": None, "5": None}
    assert daily.moves("ZZZ", "2026-05-06", 100.0, 1) == {"0": None, "1": None, "3": None, "5": None}
    assert daily.moves("AAA", "2026-05-06", None, 1)["0"] is None


# ---------------------------------------------------------------- one trade


def test_a_stock_that_rises_the_next_day_beats_both_controls():
    bars, daily = everything({"AAA": {AFTER[0]: 103.0}})
    row, reason = h.score_trade(trade(), fills(), bars, daily)
    assert reason is None and row["move"] == {"0": pytest.approx(0.0), "1": pytest.approx(3.0), "3": pytest.approx(0.0),
                                              "5": pytest.approx(0.0)}
    assert row["edge"]["stock"]["1"] == pytest.approx(3.0)        # the other names stayed flat
    # Day controls at +1: no neighbour's window ends on May 7 (May 5 ends on May 6; May 7 ends on May 8), so all are flat.
    assert row["edge"]["day"]["1"] == pytest.approx(3.0)
    # At +0 the May 7 neighbour enters at 100 and closes at 103: one control in 20 gains 3%, and the entry gained nothing.
    assert row["edge"]["day"]["0"] == pytest.approx(-3.0 / 20)
    assert row["held"] is False and row["overnight"] == pytest.approx(3.0) and row["week"] == "2026-W19"


def test_a_put_turns_the_sign_and_a_later_close_marks_the_trade_held():
    bars, daily = everything({"AAA": {AFTER[0]: 103.0}})
    row, _ = h.score_trade(trade(option_type="put", closed="2026-05-08T10:00:00"), fills(), bars, daily)
    assert row["side"] == "put" and row["move"]["1"] == pytest.approx(-3.0) and row["held"] is True
    assert row["overnight"] == pytest.approx(-3.0)


def test_exclusions_match_the_entry_skill_study():
    bars, daily = everything()
    assert h.score_trade(trade(), [], bars, daily)[1] == "no buy_to_open fill"
    assert h.score_trade(trade(ticker="QQQQ"), fills(), bars, daily)[1] == "no minute bars for the underlying on the entry session"


# ---------------------------------------------------------------- summary


def rows_with(edge_by_week, period="exploration", side="call", held=False, overnight=0.0):
    return [{"id": f"{w}-{i}", "week": w, "day": w, "period": period, "side": side, "held": held, "overnight": overnight,
             "move": {k: v for k in ("0", "1", "3", "5")}, "edge": {n: {k: v for k in ("0", "1", "3", "5")} for n in h.BASELINES}}
            for w, values in edge_by_week.items() for i, v in enumerate(values)]


def test_decisions_need_both_periods_and_the_neighbouring_horizons():
    good = rows_with({f"2026-W{w:02d}": [0.5, 0.7] for w in range(1, 13)}) + \
        rows_with({f"2026-W{w:02d}": [0.4, 0.6] for w in range(20, 32)}, period="check")
    b = h.summarize_baseline(good, "day", random.Random(h.SEED))
    assert b["decision"] == "beats chance" and b["large_enough_to_matter"] is True and b["n"] == 48 and b["weeks"] == 24
    one_period = rows_with({f"2026-W{w:02d}": [0.5, 0.7] for w in range(1, 13)})
    assert h.summarize_baseline(one_period, "day", random.Random(h.SEED))["decision"] == "no evidence either way"
    fades = [dict(r, edge={n: {**v, "3": -0.1} for n, v in r["edge"].items()}) for r in good]
    assert h.summarize_baseline(fades, "day", random.Random(h.SEED))["decision"] == "no evidence either way"
    small = rows_with({f"2026-W{w:02d}": [0.1, 0.2] for w in range(1, 13)}) + \
        rows_with({f"2026-W{w:02d}": [0.1, 0.2] for w in range(20, 32)}, period="check")
    b = h.summarize_baseline(small, "day", random.Random(h.SEED))
    assert b["decision"] == "beats chance" and b["large_enough_to_matter"] is False
    bad = [dict(r, edge={n: {k: -v for k, v in ev.items()} for n, ev in r["edge"].items()}) for r in good]
    assert h.summarize_baseline(bad, "day", random.Random(h.SEED))["decision"] == "worse than chance"


def test_whole_weeks_are_resampled():
    one_week = rows_with({"2026-W01": [1.0, 2.0, 3.0]}) + rows_with({"2026-W01": [2.0]}, period="check")
    b = h.summarize_baseline(one_week, "day", random.Random(1))
    assert b["interval"] == [2.0, 2.0] and b["standard_error"] == 0.0


def test_hold_choice_is_held_minus_closed():
    rows = rows_with({f"2026-W{w:02d}": [0.0, 0.0] for w in range(1, 11)}, held=True, overnight=1.5) + \
        rows_with({f"2026-W{w:02d}": [0.0] for w in range(1, 11)}, held=False, overnight=0.5)
    out = h.hold_choice(rows, random.Random(1))
    assert out["held"] == {"n": 20, "mean": 1.5} and out["closed_same_session"] == {"n": 10, "mean": 0.5}
    assert out["difference"] == pytest.approx(1.0) and out["interval"] == [1.0, 1.0]
    assert h.hold_choice(rows_with({"2026-W01": [0.0]}, held=True), random.Random(1)) is None


# ---------------------------------------------------------------- end to end


def test_run_reads_closes_and_minute_bars_and_writes_private_results(tmp_path):
    cache, data, out = tmp_path / "cache", tmp_path / "daily", tmp_path / "out"
    for d in [DAY, *e.neighbor_sessions(DAY)]:
        folder = cache / "stocks" / "1Min" / e.FEED / "AAA"
        folder.mkdir(parents=True, exist_ok=True)
        raw = [{"t": f"{d.isoformat()}T{(m + 240) // 60:02d}:{(m + 240) % 60:02d}:00Z", "o": 100.0, "c": 100.0}
               for m in range(e.OPEN, e.CLOSE)]
        (folder / f"{d.isoformat()}.json").write_text(json.dumps(raw))
    table = closes(["AAA", "SPY"], {"AAA": {AFTER[0]: 103.0}})
    data.mkdir()
    (data / "daily.json").write_text(json.dumps({"raw": table, "split": table}))
    extract = tmp_path / "trades.json"
    extract.write_text(json.dumps({"protocol_id": x.PROTOCOL_ID, "trades": [trade(), trade(tid="t2", ticker="ZZZ")],
                                   "fills": fills() + fills(tid="t2")}))
    results = h.run(extract, cache, data, out)
    assert results["protocol_id"] == h.PROTOCOL_ID and results["provenance"]["extract_is_registered"] is False
    assert results["scored"] == 1 and results["excluded"] == {"no minute bars for the underlying on the entry session": 1}
    assert results["baselines"]["day"]["horizons"]["1"]["n"] == 1 and results["baselines"]["stock"]["n"] == 0
    assert results["baselines"]["stock"]["decision"] == "no evidence either way" and results["hold_choice"] is None
    assert (out / "entry-horizon" / "results.json").exists()
