"""Movement richness study on invented bars, prices and outcomes, with hand-calculated values."""

from datetime import date, datetime, timedelta
import json
import math
from pathlib import Path

import pytest

from scripts import exit_counterfactual_study as x
from scripts import movement_price_study as mp
from scripts import movement_richness_study as s

FLAT = {"overnight": 0.2, "buckets": [0.8 / 78] * 78}
TRADE = {"option_type": "call", "strike": 100, "expiration": "2026-05-08"}


def full(price: float, moves: dict | None = None) -> dict:
    session = {m: (price, price) for m in range(mp.OPEN, mp.CLOSE)}
    for minute, value in (moves or {}).items():
        for m in range(minute, mp.CLOSE):
            session[m] = (value, value)
    return session


def test_daily_variance_is_the_average_whole_day():
    pair = (full(100), full(101, {574: 102}))
    assert s.daily_variance([pair] * 10) == pytest.approx(math.log(1.01) ** 2 + math.log(102 / 101) ** 2)
    assert s.daily_variance([pair] * 9) is None


def test_richness_is_priced_variance_per_typical_day_over_recent_variance():
    at = datetime(2026, 5, 6, 10)
    expiry = mp.close_at(date(2026, 5, 8))
    price = mp.bs(100, 100, 0.05, mp.RATE * mp.years(at, expiry), "call") * 100
    value, reason = s.richness({"at": at, "price": price, "underlying": 100.0}, TRADE, FLAT, 0.0004)
    assert reason is None
    assert value == pytest.approx(0.05 ** 2 / mp.units(FLAT, at, expiry) / 0.0004, rel=1e-5)
    entry = {"at": at, "price": price, "underlying": 100.0}
    assert s.richness(entry, TRADE, None, 0.0004)[1].startswith("fewer than 10")
    assert s.richness(dict(entry, underlying=None), TRADE, FLAT, 0.0004)[1].startswith("an entry fill without")
    assert s.richness(dict(entry, price=0.0), TRADE, FLAT, 0.0004)[1].startswith("an entry price")
    assert s.richness(entry, TRADE, FLAT, 0.0)[1].startswith("a stock that did not move")


def row(i, richness, movement, period="exploration", held="same session"):
    return {"id": f"t{i:03d}", "day": f"2026-05-{i % 20 + 1:02d}", "period": period, "held": held, "dte": "0-1", "side": "call",
            "movement": movement, "option_pnl": movement, "premium": 100.0, "moved": 1.0, "priced": 2.0, "richness": richness}


def test_thirds_put_any_remainder_in_the_middle():
    rows = [row(i, float(i), 0.0) for i in range(7)]
    s.assign(rows)
    assert [r["group"] for r in rows] == ["lower"] * 2 + ["middle"] * 3 + ["upper"] * 2


def test_decisions_compare_the_upper_third_with_the_lower():
    rows = []
    for period, offset in (("exploration", 0), ("check", 100)):
        rows += [row(offset + i, 0.5, -2.0, period) for i in range(30)]
        rows += [row(offset + 30 + i, 1.0, -5.0, period) for i in range(30)]
        rows += [row(offset + 60 + i, 2.0, -10.0, period) for i in range(30)]
    out = s.summarize(rows)
    assert out["gap_pct"] == pytest.approx(-8.0) and out["decision"] == "richer options lost more to movement"
    assert out["interval_pct"] == [pytest.approx(-8.0), pytest.approx(-8.0)]
    assert out["groups"]["upper"]["movement_per_premium_pct"] == -10.0 and out["groups"]["upper"]["median_richness"] == 2.0
    assert out["descriptive"]["share_richer_than_recent_pct"] == pytest.approx(33.3)
    flipped = s.summarize([dict(r, movement=-r["movement"]) for r in rows])
    assert flipped["decision"] == "richer options lost less to movement"
    one_period = [dict(r, movement=-1.0) if r["period"] == "check" else r for r in rows]
    assert s.summarize(one_period)["decision"] == "no evidence either way"
    assert s.decide(None, {}) == "no evidence either way"


def write_bars(cache, ticker, day, price):
    folder = cache / "stocks" / "1Min" / "sip" / ticker
    folder.mkdir(parents=True, exist_ok=True)
    bars = []
    for m in range(mp.OPEN, mp.CLOSE):
        stamp = datetime(day.year, day.month, day.day, m // 60, m % 60) + timedelta(hours=4)  # EDT to UTC
        bars.append({"t": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"), "o": price, "c": price})
    (folder / f"{day.isoformat()}.json").write_text(json.dumps(bars))


def test_run_joins_entries_to_outcomes_and_records_hashes(tmp_path):
    cache = tmp_path / "cache"
    for i, day in enumerate(mp.sessions_before(date(2026, 5, 6), mp.PROFILE_SESSIONS + 1)):
        write_bars(cache, "AAA", day, 100.0 + i % 2)
    base = {"option_type": "call", "strike": 100, "expiration": "2026-05-08", "status": "closed"}
    trades = [dict(base, id=t, ticker=k) for t, k in (("t1", "AAA"), ("t2", "BBB"), ("t3", "AAA"))]
    fills = [{"trade_id": t, "fill_id": f"{t}e", "side": x.ENTRY, "contracts": 1, "price": 120,
              "executed_at": "2026-05-06T10:00:00"} for t in ("t1", "t2", "t3")]
    (tmp_path / "trades.json").write_text(json.dumps({"protocol_id": x.PROTOCOL_ID, "trades": trades, "fills": fills}))
    (tmp_path / "fills.json").write_text(json.dumps([{"fill_id": f["fill_id"], "underlying": 100.0} for f in fills]))
    outcome = [dict(row(n, 0, -1.0), id=t, day="2026-05-06", earnings=t == "t3") for n, t in enumerate(("t1", "t2", "t3"))]
    (tmp_path / "movement.jsonl").write_text("".join(json.dumps(r) + "\n" for r in outcome))
    out = s.run(tmp_path / "trades.json", tmp_path / "fills.json", tmp_path / "movement.jsonl", cache, tmp_path / "out")
    assert out["outcome_trades"] == 2 and out["scored"] == 1
    assert out["excluded"] == {"fewer than 10 usable sessions of minute bars in the 20 before entry": 1}
    assert out["provenance"]["inputs_are_registered"] is False and len(out["provenance"]["movement_sha256"]) == 64
    assert (tmp_path / "out" / "movement-richness" / "trades.jsonl").exists()


def test_the_protocol_names_the_constants_in_code():
    protocol = json.loads((Path(__file__).resolve().parents[2] / "research" / "movement-richness" / "protocol.json").read_text())
    assert protocol["protocol_id"] == s.PROTOCOL_ID and protocol["tests"] == 1
    assert s.REGISTERED_MOVEMENT_SHA256 in protocol["population"]["inputs"]["outcome"]
    assert str(s.SEED) in protocol["uncertainty"]
    assert set(protocol["decisions"]) >= {"richer options lost more to movement", "richer options lost less to movement",
                                          "no evidence either way"}
