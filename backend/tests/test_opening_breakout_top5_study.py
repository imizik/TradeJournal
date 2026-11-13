"""Top-5 opening breakout with tape fills, on invented trades and quotes with hand-calculated R."""

import json
from pathlib import Path

import pytest

from scripts import opening_breakout_study as v1
from scripts import opening_breakout_top5_study as s

DAY = "2018-03-05"
S = 10**9


def at(minute, second=0.0):
    return s.minute_ns(DAY, minute) + int(second * S)


class Tape:
    """Invented tape: trades [(ns, price)] (already at least 100 shares) and quotes [(ns, bid, ask)]."""

    def __init__(self, trades, quotes):
        self.trades, self.quotes = sorted(trades), sorted(quotes)
        self.asked = []

    def through(self, symbol, lo, hi, threshold, side):
        self.asked.append(("T", lo, hi, threshold, side))
        return [[t, p] for t, p in self.trades if lo <= t < hi and (p >= threshold if side > 0 else p <= threshold)]

    def quote_at(self, symbol, t):
        self.asked.append(("Q", t))
        return s._in_effect([list(q) for q in self.quotes], t)


PICK = {"symbol": "AAA", "side": 1, "rank": 1, "high": 10.0, "low": 9.5, "atr": 2.0}  # risk 0.20


def bars(spec):
    return {m: [o, h, low, c, 100] for m, o, h, low, c in spec}


def test_time_helpers_keep_nanoseconds():
    assert s.ns_of("2024-03-04T14:35:00.020942355Z") == s.ns_of("2024-03-04T14:35:00Z") + 20942355
    assert s.ns_of("2016-01-04T14:35:00.136Z") % S == 136_000_000
    assert s.ns_of(s.stamp_of(1_457_190_900_123_456_789)) == 1_457_190_900_123_456_789
    assert s.minute_at(DAY, at(576, 59.9)) == 576 and s.minute_at(DAY, at(577)) == 577


def test_a_trade_counts_only_inside_the_quote_in_effect():
    q = [0, 9.98, 10.00]
    assert s.confirmed(10.01, q) and s.confirmed(9.97, q)
    assert not s.confirmed(10.05, q)  # tolerance is max(1 cent, 0.2% of 9.99) = 2 cents
    assert s.confirmed(10.019, q) and not s.confirmed(10.021, q)
    assert not s.confirmed(10.0, None) and not s.confirmed(10.0, [0, 10.1, 10.0])  # crossed
    rows = [[at(570), 9.9, 10.0], [at(571), 0, 10.0], [at(572), 10.2, 10.1]]
    assert s._in_effect(rows, at(570, 59)) == [at(570), 9.9, 10.0]
    assert s._in_effect(rows, at(572, 30)) is None  # the zero bid and the crossed quote are skipped; 570's is too old
    assert s._in_effect(rows, at(569)) is None


def test_entry_at_the_ask_a_second_after_the_first_confirmed_trade_and_exit_at_the_bid():
    tape = Tape(
        trades=[(at(576, 10), 10.30),  # a bad print far above the quote: ignored
                (at(576, 20), 10.00),  # the trigger
                (at(578, 5), 9.85)],   # above the 9.82 stop: not a stop
        quotes=[(at(576, 0), 9.98, 9.99), (at(576, 20.5), 10.00, 10.02), (at(959, 0.5), 10.40, 10.42)])
    b = bars([(576, 9.95, 10.3, 9.9, 10.0), (578, 10, 10, 9.85, 9.9), (959, 10.4, 10.45, 10.35, 10.4)])
    t = s.tape_trade(PICK, b, tape, DAY)
    assert t["fill"] == 10.02 and t["exit"] == 10.40 and t["how"] == "close"
    assert t["r"] == pytest.approx((10.40 - 10.02) / 0.2)
    assert t["r_extra_cent"] == pytest.approx((10.40 - 10.02 - 0.02) / 0.2)
    assert t["spread_r"] == pytest.approx(0.02 / 0.2) and t["entered"] == 576
    # minute 578's bar low 9.85 does not reach the 9.82 stop (fill 10.02 - 0.20), so it is never read
    assert not any(a[0] == "T" and a[1] == at(578) for a in tape.asked)


def test_a_stop_inside_the_fill_minute_is_seen_on_the_tape():
    tape = Tape(trades=[(at(575, 1), 10.0), (at(575, 30), 9.79)],
                quotes=[(at(575, 0), 9.99, 10.0), (at(575, 29), 9.78, 9.80), (at(575, 31), 9.77, 9.79),
                        (at(959, 0.5), 11, 11.01)])
    b = bars([(575, 9.9, 10.1, 9.7, 10.05), (959, 11, 11, 11, 11)])  # the bar closes above: v1 would hold
    assert v1.trade({**PICK}, b)["how"] == "close"
    t = s.tape_trade(PICK, b, tape, DAY)
    assert t["fill"] == 10.0 and t["how"] == "stop" and t["exit"] == 9.77
    assert t["r"] == pytest.approx((9.77 - 10.0) / 0.2)


def test_a_short_mirrors_bid_in_ask_out_and_late_or_missing_quotes():
    short = dict(PICK, side=-1)  # level 9.50, stop 0.20 above the fill
    tape = Tape(trades=[(at(580, 3), 9.50), (at(600, 0.5), 9.71)],
                quotes=[(at(580, 0), 9.50, 9.51), (at(580, 3.5), 9.49, 9.50), (at(600, 0.2), 9.70, 9.72)])
    b = bars([(580, 9.6, 9.6, 9.45, 9.5), (600, 9.5, 9.75, 9.4, 9.7), (959, 9, 9, 9, 9)])
    t = s.tape_trade(short, b, tape, DAY)
    assert t["fill"] == 9.49 and t["how"] == "stop" and t["exit"] == 9.72  # stop 9.69, bought back at the ask
    assert t["r"] == pytest.approx((9.49 - 9.72) / 0.2)
    no_quote = Tape(trades=[(at(580, 3), 9.50)], quotes=[(at(580, 0), 9.50, 9.51)])
    later = s.tape_trade(short, bars([(580, 9.6, 9.6, 9.45, 9.5), (959, 9, 9, 9, 9)]), no_quote, DAY)
    assert later["how"] == "close from bar" and later["exit"] == 9  # no quote at 15:59:01 within a minute
    assert s.tape_trade(PICK, bars([(956, 9.9, 10.5, 9.9, 10.4), (959, 10, 10, 10, 10)]), Tape([], []), DAY) is None
    lost = s.tape_trade(PICK, bars([(576, 9.9, 10.1, 9.9, 10)]), Tape([(at(576, 1), 10.0)], [(at(575), 9.99, 10.0)]), DAY)
    assert lost is None  # the only quote is over a minute old, so the trade is not confirmed


def test_the_recorder_saves_every_answer_and_the_replay_gives_the_same_trade():
    trades = {at(576): [{"t": s.stamp_of(at(576, 20)), "p": 10.0, "s": 300}, {"t": s.stamp_of(at(576, 21)), "p": 10.05, "s": 50}]}
    quotes = [(at(576, 0), 9.98, 9.99), (at(576, 20.5), 10.00, 10.02), (at(959, 0.5), 10.40, 10.42)]
    calls = []

    def get(path, params):
        calls.append((path, params.get("page_token")))
        lo, hi = s.ns_of(params["start"]), s.ns_of(params["end"])
        if path.endswith("/trades"):
            return {"trades": [r for r in trades.get(lo, [])], "next_page_token": None}
        rows = [q for q in reversed(quotes) if lo <= q[0] <= hi]
        return {"quotes": [{"t": s.stamp_of(t), "bp": b, "ap": a} for t, b, a in rows], "next_page_token": None}

    log = {}
    b = bars([(576, 9.95, 10.3, 9.9, 10.0), (959, 10.4, 10.45, 10.35, 10.4)])
    live = s.tape_trade(PICK, b, s.Recorder(get, log), DAY)
    assert live["fill"] == 10.02 and live["exit"] == 10.40
    assert sum(1 for p, _ in calls if p.endswith("/quotes")) == 2  # the trigger check and its fill share one read
    replayed = s.tape_trade(PICK, b, s.Replay(json.loads(json.dumps(log))), DAY)
    assert replayed == live
    with pytest.raises(KeyError):
        s.Replay({}).quote_at("AAA", at(576))


def test_selection_keeps_v1_rules_and_the_top_five():
    order = [f"2018-02-{d:02d}" for d in range(1, 16)]
    day = order[-1]
    opening, candidates = {}, {day: []}
    for i in range(8):
        sym = f"S{i}"
        candidates[day].append([sym, 1.0, 20.0])
        for d in order[:-1]:
            opening.setdefault(d, {})[sym] = [[570, 10, 10, 10, 10, 100], [571, 10, 10, 10, 10, 100], [572, 10, 10, 10, 10, 100]]
        opening.setdefault(day, {})[sym] = [[570, 10, 10.5, 9.9, 10.2, 100 * (i + 2)], [571, 10.2, 10.6, 10.1, 10.5, 100],
                                            [572, 10.5, 10.7, 10.4, 10.6, 100]]
    chosen = s.select(opening, day, order, candidates)
    assert [c["symbol"] for c in chosen] == ["S7", "S6", "S5", "S4", "S3"] and [c["rank"] for c in chosen] == [1, 2, 3, 4, 5]
    assert chosen[0]["high"] == 10.7 and chosen[0]["side"] == 1


def made(day, r, side=1, rank=1):
    return {"day": day, "symbol": f"X{rank}", "side": side, "rank": rank, "status": "traded", "how": "close",
            "r": r, "r_extra_cent": r - 0.05, "spread_r": 0.1}


def test_decisions_need_the_interval_both_halves_and_the_extra_cent():
    good = [made(f"201{y}-0{m}-1{d}", 0.4) for y in (6, 7, 8, 9) for m in range(1, 4) for d in range(3)] + \
           [made(f"202{y}-0{m}-1{d}", 0.3) for y in (0, 1, 2, 3) for m in range(1, 4) for d in range(3)]
    out = s.summarize(good, [{**t, "r": 0.2} for t in good], [], selected=len(good), triggered=len(good))
    assert out["both_sides"]["decision"] == "worth a paper test" and out["long_side"]["decision"] == "worth a paper test"
    assert out["descriptive"]["tape_minus_bar_r"]["mean"] == pytest.approx(0.15, abs=1e-3)
    thin = [{**t, "r_extra_cent": -0.01} for t in good]
    assert s.summarize(thin, [], [], len(thin), len(thin))["both_sides"]["decision"] == "no evidence either way"
    one_half = [t if t["day"] < "2020" else {**t, "r": -0.1} for t in good]
    assert s.summarize(one_half, [], [], len(good), len(good))["both_sides"]["decision"] == "no evidence either way"
    bad = [{**t, "r": -0.3} for t in good]
    assert s.summarize(bad, [], [], len(bad), len(bad))["both_sides"]["decision"] == "loses money"
    shorts = good + [made("2017-02-11", -9.0, side=-1)]
    out = s.summarize(shorts, [], [], len(shorts), len(shorts))
    assert out["descriptive"]["short_side"]["trades"] == 1 and out["long_side"]["trades"] == len(good)


def test_run_replays_saved_sessions(tmp_path):
    days = [f"2017-12-{d:02d}" for d in range(1, 29)] + ["2018-03-05"]
    v1.save(tmp_path / "candidates.json.gz", {"days": days, "by_day": {}})
    log = {}
    tape = Tape(trades=[(at(576, 20), 10.0)], quotes=[(at(576, 0), 9.99, 10.0), (at(959, 0.5), 10.4, 10.41)])
    b = {576: [9.95, 10.1, 9.9, 10.05, 1], 959: [10.4, 10.5, 10.3, 10.4, 1]}

    class Logging(Tape):
        def through(self, *a):
            log[s.through_key(*a)] = super().through(*a)
            return log[s.through_key(*a)]

        def quote_at(self, sym, t):
            log[s.quote_key(sym, t)] = super().quote_at(sym, t)
            return log[s.quote_key(sym, t)]

    s.tape_trade(PICK, b, Logging(tape.trades, tape.quotes), DAY)
    v1.save(tmp_path / "session" / f"{DAY}.json.gz",
            {"picks": [PICK], "bars": {"AAA": [[m, *v] for m, v in b.items()]}, "ticks": log})
    for d in s.sessions(days):
        if d != DAY:
            v1.save(tmp_path / "session" / f"{d}.json.gz", {"picks": [], "bars": {}, "ticks": {}})
    out = s.run(tmp_path, tmp_path / "copy.json")
    assert out["both_sides"]["trades"] == 1 and out["descriptive"]["bar_replay_v1_rules"]["trades"] == 1
    assert json.loads((tmp_path / "copy.json").read_text())["protocol_id"] == s.PROTOCOL_ID


def test_the_protocol_names_the_constants_in_code():
    protocol = json.loads((Path(__file__).resolve().parents[2] / "research" / "opening-breakout-top5" / "protocol.json").read_text())
    assert protocol["protocol_id"] == s.PROTOCOL_ID and protocol["tests"]["count"] == 2
    assert str(s.SEED) in protocol["tests"]["uncertainty"] and "97.5%" in protocol["tests"]["uncertainty"]
    assert "the top 5" in protocol["selection"]["stocks_in_play"] and s.TOP == 5
    assert all(d in protocol["data"]["names"] for d in s.LISTING_DATES)
    assert all(d.isoformat() in protocol["sessions"] for d in s.HALF_DAYS)
    assert "at least 100 shares" in protocol["trade"]["tape_trade"] and s.MIN_TRADE_SHARES == 100
    assert "0.2%" in protocol["trade"]["tape_trade"] and s.TOLERANCE_SHARE == 0.002
    assert "one second after the trigger" in protocol["trade"]["entry"] and s.DELAY == 10**9
    assert "15:58:59" in protocol["trade"]["stop"] and s.LAST_STOP_MINUTE == 958
