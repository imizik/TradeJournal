"""Movement price study on invented bars, prices and fills, with hand-calculated values."""

from datetime import date, datetime, timedelta
import json
import math
from pathlib import Path
import random

import pytest

from scripts import exit_counterfactual_study as x
from scripts import movement_price_study as s

FLAT = {"overnight": 0.2, "buckets": [0.8 / 78] * 78}
BUCKET = 0.8 / 78


def at(text: str) -> datetime:
    return datetime.fromisoformat(text)


def test_black_scholes_round_trip_and_parity():
    price = s.bs(100, 100, 0.2, 0.01, "call")
    assert s.solve_stdev(price, 100, 100, 0.01, "call") == pytest.approx(0.2, abs=1e-6)
    put = s.bs(100, 100, 0.2, 0.01, "put")
    assert price - put == pytest.approx(100 - 100 * math.exp(-0.01))
    assert s.bs(100, 90, 0, 0, "call") == 10 and s.bs(100, 90, 0, 0, "put") == 0
    assert s.solve_stdev(5.0, 100, 90, 0, "call") is None  # below intrinsic value
    assert s.bs_delta(100, 90, 0, 0, "call") == 1.0 and s.bs_delta(100, 110, 0, 0, "put") == -1.0


def test_the_variance_clock_counts_buckets_and_one_night_per_open():
    assert s.units(FLAT, at("2026-05-06T09:30"), at("2026-05-06T16:00")) == pytest.approx(0.8)
    assert s.units(FLAT, at("2026-05-06T09:30"), at("2026-05-06T09:40")) == pytest.approx(2 * BUCKET)
    assert s.units(FLAT, at("2026-05-06T09:30"), at("2026-05-06T09:32:30")) == pytest.approx(0.5 * BUCKET)
    overnight = 18 * BUCKET + 0.2
    assert s.units(FLAT, at("2026-05-06T15:00"), at("2026-05-07T10:00")) == pytest.approx(overnight)
    assert s.units(FLAT, at("2026-05-08T15:00"), at("2026-05-11T10:00")) == pytest.approx(overnight)  # a weekend is one night
    assert s.units(FLAT, at("2026-05-22T15:00"), at("2026-05-26T10:00")) == pytest.approx(overnight)  # Memorial Day
    assert s.units(FLAT, at("2026-11-27T09:30"), at("2026-11-27T16:00")) == pytest.approx(42 * BUCKET)  # closes at 13:00
    assert s.units(FLAT, at("2026-05-06T17:00"), at("2026-05-07T09:30")) == pytest.approx(0.2)
    assert s.units(FLAT, at("2026-05-06T12:00"), at("2026-05-06T11:00")) == 0


def full(price: float, moves: dict | None = None) -> dict:
    session = {m: (price, price) for m in range(s.OPEN, s.CLOSE)}
    for minute, value in (moves or {}).items():
        for m in range(minute, s.CLOSE):
            session[m] = (value, value)
    return session


def test_the_profile_shares_a_typical_day_between_the_night_and_each_bucket():
    previous, session = full(100), full(101, {574: 102})
    night, buckets = s.session_variance(previous, session)
    assert night == pytest.approx(math.log(1.01) ** 2)
    assert buckets[0] == pytest.approx(math.log(102 / 101) ** 2) and sum(buckets[1:]) == 0
    assert s.session_variance(previous, {m: v for m, v in session.items() if m < 950}) is None  # ends early
    assert s.session_variance(None, session) is None
    shape = s.profile([(previous, session)] * 10)
    a, b = math.log(1.01) ** 2, math.log(102 / 101) ** 2
    assert shape["overnight"] == pytest.approx(a / (a + b)) and shape["buckets"][0] == pytest.approx(b / (a + b))
    assert shape["sessions"] == 10 and s.profile([(previous, session)] * 9) is None


EXPIRY = s.close_at(date(2026, 5, 8))


def test_a_worthless_expiry_without_a_move_is_all_movement_cost():
    one, _ = s.piece("call", 105, EXPIRY, FLAT, (at("2026-05-06T10:00"), 50.0, 100.0), (EXPIRY, 0.0, 100.0), 2)
    assert one["direction"] == 0 and one["movement"] == pytest.approx(-100, abs=1e-6)
    assert one["iv_and_spread"] == pytest.approx(0, abs=1e-6) and one["option_pnl"] == -100
    assert one["moved"] == 0 and one["moved_more"] == 0 and one["contracts"] == 2


def test_pieces_add_up_and_a_big_move_beats_its_price():
    entry = (at("2026-05-06T10:00"), 120.0, 100.0)
    big, _ = s.piece("call", 100, EXPIRY, FLAT, entry, (at("2026-05-07T10:00"), 900.0, 110.0), 1)
    assert big["movement"] > 0 and big["moved_more"] == 1
    assert big["direction"] + big["movement"] + big["iv_and_spread"] == pytest.approx(big["option_pnl"])
    assert big["movement_calendar"] + big["iv_and_spread_calendar"] == pytest.approx(big["movement"] + big["iv_and_spread"])
    still, _ = s.piece("call", 100, EXPIRY, FLAT, entry, (at("2026-05-06T12:00"), 110.0, 100.0), 1)
    assert still["direction"] == 0 and still["movement"] < 0 and still["moved"] == 0
    sd0 = s.solve_stdev(1.2, 100, 100, s.RATE * s.years(entry[0], EXPIRY), "call")
    share = s.units(FLAT, entry[0], at("2026-05-06T12:00")) / s.units(FLAT, entry[0], EXPIRY)
    assert still["priced"] == pytest.approx(sd0 ** 2 * share)


def test_pieces_that_cannot_be_scored_say_why():
    assert s.piece("call", 90, EXPIRY, FLAT, (at("2026-05-06T10:00"), 500.0, 100.0), (EXPIRY, 0.0, 100.0), 1)[1] == \
        "an entry price no Black-Scholes volatility reproduces"
    late = at("2026-05-08T16:05")
    assert s.piece("call", 90, EXPIRY, FLAT, (late, 1000.0, 100.0), (late, 1000.0, 100.0), 1)[1] == \
        "an entry with no trading time left before expiry"


def fill(fid, side, when, contracts, price, underlying):
    return {"fill_id": fid, "side": side, "at": at(when), "contracts": contracts, "price": price, "underlying": underlying}


TRADE = {"option_type": "call", "strike": 100, "expiration": "2026-05-08"}


def test_replay_closes_lots_first_in_first_out_and_expires_the_rest():
    fills = [fill("a", x.ENTRY, "2026-05-06T10:00", 1, 120, 100.0), fill("b", x.ENTRY, "2026-05-06T11:00", 2, 150, 101.0),
             fill("c", x.EXIT, "2026-05-07T10:00", 2, 200, 102.0)]
    out, reason = s.replay(TRADE, fills, 99.0, FLAT)
    assert reason is None and out["option_pnl"] == pytest.approx((200 - 120) + (200 - 150) - 150) and out["premium"] == 420
    assert out["contracts"] == 3
    assert out["direction"] + out["movement"] + out["iv_and_spread"] == pytest.approx(out["option_pnl"])
    assert s.replay(TRADE, fills, None, FLAT)[1] == "an expired trade without the underlying's close on the expiration date"
    assert s.replay(TRADE, [fill("a", x.ENTRY, "2026-05-06T10:00", 1, 120, None)], 99.0, FLAT)[1].startswith("an entry fill")
    assert s.replay(TRADE, [fill("a", x.ENTRY, "2026-05-06T10:00", 1, 120, 100.0),
                            fill("c", x.EXIT, "2026-05-07T10:00", 1, 200, None)], 99.0, FLAT)[1].startswith("an exit fill")
    assert s.replay(TRADE, [fill("c", x.EXIT, "2026-05-07T10:00", 1, 200, 100.0)], 99.0, FLAT)[1].startswith("not a long")


def rows(movements, period="exploration", earnings=False):
    return [{"day": f"2026-05-{i % 20 + 1:02d}", "period": period, "side": "call", "dte": "0-1", "held": "same session",
             "earnings": earnings, "direction": 0.0, "movement": m, "iv_and_spread": 0.0, "option_pnl": m, "premium": 100.0,
             "moved": 1.0, "priced": 2.0, "contracts": 1.0, "moved_more": 0.0, "movement_calendar": m,
             "iv_and_spread_calendar": 0.0} for i, m in enumerate(movements)]


def test_decisions_use_trades_without_earnings_in_the_window():
    down = s.summarize(rows([-50.0] * 40) + rows([-30.0] * 40, period="check") + rows([999.0] * 40, earnings=True))
    assert down["decision"] == "paid for more movement than he got" and down["primary"]["trades"] == 80
    assert down["primary"]["movement_ratio"] == 0.5 and down["descriptive"]["earnings_in_window"]["trades"] == 40
    up = s.summarize(rows([50.0] * 40) + rows([30.0] * 40, period="check"))
    assert up["decision"] == "got more movement than he paid for"
    one = s.summarize(rows([50.0] * 40) + rows([-1.0] * 40, period="check"))
    assert one["decision"] == "no evidence either way"
    assert s.summarize([])["decision"] == "no evidence either way"


def test_the_interval_resamples_days():
    single = [{"day": "2026-05-06", "movement": v} for v in (1.0, 2.0, 3.0)]
    assert s.interval(single, random.Random(1)) == [6.0, 6.0]


def test_the_protocol_names_the_constants_in_code():
    protocol = json.loads((Path(__file__).resolve().parents[2] / "research" / "movement-price" / "protocol.json").read_text())
    inputs = protocol["population"]["inputs"]
    assert protocol["protocol_id"] == s.PROTOCOL_ID and protocol["tests"] == 1
    assert s.REGISTERED_EXTRACT_SHA256 in inputs["extract"] and s.REGISTERED_FILLS_SHA256 in inputs["fill_join"]
    assert s.REGISTERED_DAILY_SHA256 in inputs["daily_closes"]
    assert str(s.SEED) in protocol["uncertainty"] and f"{s.RATE:.2%}" in protocol["method"]["priced_variance"]
    assert set(protocol["decisions"]) >= {"paid for more movement than he got", "got more movement than he paid for",
                                          "no evidence either way"}


def write_bars(cache, ticker, day, price):
    folder = cache / "stocks" / "1Min" / "sip" / ticker
    folder.mkdir(parents=True, exist_ok=True)
    bars = []
    for m in range(s.OPEN, s.CLOSE):
        stamp = datetime(day.year, day.month, day.day, m // 60, m % 60) + timedelta(hours=4)  # EDT to UTC
        bars.append({"t": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"), "o": price, "c": price})
    (folder / f"{day.isoformat()}.json").write_text(json.dumps(bars))


def test_run_scores_flags_earnings_and_records_hashes(tmp_path):
    cache = tmp_path / "cache"
    for i, day in enumerate(s.sessions_before(date(2026, 5, 6), s.PROFILE_SESSIONS + 1)):
        write_bars(cache, "AAA", day, 100.0 + i % 2)
    base = {"option_type": "call", "strike": 100, "expiration": "2026-05-08", "status": "closed",
            "opened_at": "2026-05-06T10:00:00", "closed_at": "2026-05-06T12:00:00", "realized_pnl": 0,
            "total_premium_paid": 120, "account_type": "roth_ira"}
    trades = [dict(base, id="t1", ticker="AAA"), dict(base, id="t2", ticker="BBB")]
    fills = []
    for t in ("t1", "t2"):
        fills += [{"trade_id": t, "fill_id": f"{t}e", "role": "entry", "side": x.ENTRY, "contracts": 1, "price": 120,
                   "executed_at": "2026-05-06T10:00:00"},
                  {"trade_id": t, "fill_id": f"{t}x", "role": "exit", "side": x.EXIT, "contracts": 1, "price": 110,
                   "executed_at": "2026-05-06T12:00:00"}]
    (tmp_path / "trades.json").write_text(json.dumps({"protocol_id": x.PROTOCOL_ID, "trades": trades, "fills": fills}))
    (tmp_path / "fills.json").write_text(json.dumps([{"fill_id": f["fill_id"], "delta": 0.5, "underlying": 100.0} for f in fills]))
    (tmp_path / "daily.json").write_text(json.dumps({"raw": {}, "split": {}}))
    (tmp_path / "earnings.json").write_text(json.dumps({"requested": ["AAA", "BBB"], "dates": {"AAA": ["2026-05-07"]}}))
    out = s.run(tmp_path / "trades.json", tmp_path / "fills.json", tmp_path / "daily.json", tmp_path / "earnings.json",
                cache, tmp_path / "out")
    assert out["scored"] == 1 and out["excluded"] == {"fewer than 10 usable sessions of minute bars in the 20 before entry": 1}
    assert out["primary"]["trades"] == 0 and out["descriptive"]["earnings_in_window"]["trades"] == 1
    assert out["descriptive"]["earnings_in_window"]["option_pnl"] == -10
    assert out["symbols_without_report_dates"] == ["BBB"] and out["provenance"]["inputs_are_registered"] is False
    assert len(out["provenance"]["earnings_sha256"]) == 64
    assert (tmp_path / "out" / "movement-price" / "trades.jsonl").exists()
