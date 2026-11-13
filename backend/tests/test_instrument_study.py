"""Instrument study on invented fills, with hand-calculated dollars."""

from datetime import date, datetime
import json
import random

import pytest

from scripts import exit_counterfactual_study as x
from scripts import instrument_study as s


def fill(fid, side, at, contracts, price, delta=None, underlying=None):
    return {"fill_id": fid, "side": side, "at": datetime.fromisoformat(at), "contracts": contracts, "price": price,
            "delta": delta, "underlying": underlying}


def cost(shares, price):
    return abs(shares) * price * s.STOCK_COST


def test_a_call_that_wins_more_than_its_stock_replay():
    # 2 contracts at $300 (delta 0.5 = 100 shares) with the stock at 100; sold at $500 with the stock at 103.
    fills = [fill("a", x.ENTRY, "2026-05-06T10:00", 2, 300, 0.5, 100.0), fill("b", x.EXIT, "2026-05-06T11:00", 2, 500, 0.6, 103.0)]
    out, reason = s.replay({}, fills, None)
    assert reason is None and out["option_pnl"] == pytest.approx(400) and out["premium"] == pytest.approx(600)
    assert out["stock_pnl"] == pytest.approx(100 * 3 - cost(100, 100) - cost(100, 103))
    assert out["difference"] == pytest.approx(400 - out["stock_pnl"])


def test_a_put_replays_as_a_short_stock_position():
    fills = [fill("a", x.ENTRY, "2026-05-06T10:00", 1, 200, -0.4, 50.0), fill("b", x.EXIT, "2026-05-06T12:00", 1, 150, -0.3, 49.0)]
    out, _ = s.replay({}, fills, None)
    assert out["option_pnl"] == pytest.approx(-50)
    assert out["stock_pnl"] == pytest.approx(-40 * (49 - 50) - cost(40, 50) - cost(40, 49))   # short 40 shares gains $40


def test_partial_exits_close_the_oldest_lot_first_with_its_own_delta():
    fills = [fill("a", x.ENTRY, "2026-05-06T10:00", 1, 100, 0.5, 10.0), fill("b", x.ENTRY, "2026-05-06T10:30", 1, 200, 0.8, 11.0),
             fill("c", x.EXIT, "2026-05-06T11:00", 1, 150, 0.6, 12.0), fill("d", x.EXIT, "2026-05-06T12:00", 1, 250, 0.9, 13.0)]
    out, _ = s.replay({}, fills, None)
    assert out["option_pnl"] == pytest.approx(50 + 50)
    gross = 50 * (12 - 10) + 80 * (13 - 11)
    assert out["stock_pnl"] == pytest.approx(gross - cost(50, 10) - cost(80, 11) - cost(50, 12) - cost(80, 13))


def test_an_expired_remainder_is_worth_nothing_and_the_stock_closes_at_the_expiry_close():
    fills = [fill("a", x.ENTRY, "2026-05-06T10:00", 3, 100, 0.3, 20.0), fill("b", x.EXIT, "2026-05-07T10:00", 1, 50, 0.2, 19.5)]
    out, _ = s.replay({}, fills, 19.0)
    assert out["option_pnl"] == pytest.approx(-50 - 200)
    gross = 30 * (19.5 - 20) + 60 * (19.0 - 20)
    assert out["stock_pnl"] == pytest.approx(gross - cost(90, 20) - cost(30, 19.5) - cost(60, 19.0))
    assert s.replay({}, fills, None)[1] == "an expired trade without the underlying's close on the expiration date"


def test_missing_inputs_and_other_sides_are_excluded_with_a_reason():
    good_exit = fill("b", x.EXIT, "2026-05-06T11:00", 1, 1, 0.5, 10.0)
    assert s.replay({}, [fill("a", x.ENTRY, "2026-05-06T10:00", 1, 1, None, 10.0), good_exit], None)[1].startswith("an entry fill")
    assert s.replay({}, [fill("a", x.ENTRY, "2026-05-06T10:00", 1, 1, 0.5, 10.0),
                         fill("b", x.EXIT, "2026-05-06T11:00", 1, 1, 0.5, None)], None)[1].startswith("an exit fill")
    assert s.replay({}, [fill("a", "sell_to_open", "2026-05-06T10:00", 1, 1, 0.5, 10.0)], None)[1].startswith("not a long")
    assert s.replay({}, [good_exit], None)[1].startswith("not a long")


def test_splits_and_expiry_buckets():
    assert s.spans_split("NFLX", date(2025, 11, 14), date(2025, 11, 17)) is True
    assert s.spans_split("NFLX", date(2025, 11, 17), date(2025, 11, 20)) is False
    assert s.spans_split("AAPL", date(2025, 1, 1), date(2026, 1, 1)) is False
    assert [s.dte_bucket(date(2026, 5, 6), date(2026, 5, d)) for d in (6, 7, 8, 13, 14)] == ["0-1", "0-1", "2-7", "2-7", "8+"]


def rows(diffs, period="exploration"):
    return [{"day": f"2026-05-{i % 20 + 1:02d}", "period": period, "side": "call", "dte": "0-1", "held": "same session",
             "option_pnl": d, "stock_pnl": 0.0, "difference": d, "premium": 100.0} for i, d in enumerate(diffs)]


def test_decisions():
    up = s.summarize(rows([50.0] * 40) + rows([30.0] * 40, period="check"))
    assert up["decision"] == "options added value" and up["all"]["difference"] == 3200 and up["all"]["option_beat_stock"] == 80
    down = s.summarize(rows([-50.0] * 40) + rows([-30.0] * 40, period="check"))
    assert down["decision"] == "options cost money"
    one = s.summarize(rows([50.0] * 40) + rows([-1.0] * 40, period="check"))
    assert one["decision"] == "no evidence either way"
    noisy = s.summarize(rows([(-1) ** i * 100.0 for i in range(80)]) + rows([1.0], period="check"))
    assert noisy["decision"] == "no evidence either way"


def test_the_interval_resamples_days():
    single = [{"day": "2026-05-06", "difference": v} for v in (1.0, 2.0, 3.0)]
    assert s.interval(single, random.Random(1)) == [6.0, 6.0]


def test_run_joins_fills_by_id_and_records_hashes(tmp_path):
    trade = {"id": "t1", "ticker": "AAA", "option_type": "call", "strike": 10, "expiration": "2026-05-08", "status": "expired",
             "opened_at": "2026-05-06T10:00:00", "closed_at": "2026-05-08T16:00:00", "realized_pnl": -100,
             "total_premium_paid": 100, "account_type": "roth_ira"}
    split = dict(trade, id="t2", ticker="NFLX", expiration="2025-11-21", opened_at="2025-11-14T10:00:00")
    extract = {"protocol_id": x.PROTOCOL_ID, "trades": [trade, split],
               "fills": [{"trade_id": "t1", "fill_id": "f1", "role": "entry", "side": x.ENTRY, "contracts": 1, "price": 100,
                          "executed_at": "2026-05-06T10:00:00"},
                         {"trade_id": "t2", "fill_id": "f2", "role": "entry", "side": x.ENTRY, "contracts": 1, "price": 100,
                          "executed_at": "2025-11-14T10:00:00"}]}
    (tmp_path / "trades.json").write_text(json.dumps(extract))
    (tmp_path / "fills.json").write_text(json.dumps([{"fill_id": "f1", "delta": 0.5, "underlying": 10.0},
                                                    {"fill_id": "f2", "delta": 0.5, "underlying": 1000.0}]))
    (tmp_path / "daily.json").write_text(json.dumps({"raw": {"AAA": {"2026-05-08": 9.0}}, "split": {}}))
    out = s.run(tmp_path / "trades.json", tmp_path / "fills.json", tmp_path / "daily.json", tmp_path / "out")
    assert out["scored"] == 1 and out["excluded"] == {"a hold that spans a share split of the underlying": 1}
    assert out["all"]["option_pnl"] == -100 and out["all"]["stock_pnl"] == pytest.approx(-50 - 0.05 - 0.045, abs=0.01)
    assert out["provenance"]["extract_is_registered"] is False and len(out["provenance"]["fills_sha256"]) == 64
    assert (tmp_path / "out" / "instrument" / "trades.jsonl").exists()
