"""Packet tests: field contract, strict causality, feature arithmetic and size. No network."""

import copy
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import random

import pytest

from research.opening_lab import packet as pk
from research.opening_lab.contract import (BAR_COLUMNS, CHECKPOINTS_ET, PACKET_FIELDS, SYMBOLS,
                                           UTC, VARIANTS, checkpoint_ts, et_datetime)

DAY = "2026-07-15"  # a Wednesday, EDT


def _iso(epoch):
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _minutes(rng, day, start_price, base_volume):
    """04:00-10:59 one-minute bars: thin premarket (vw sometimes None), busy open."""
    bars, price = [], start_price
    t0, open_ts, end = checkpoint_ts(day, "04:00"), checkpoint_ts(day, "09:30"), checkpoint_ts(day, "11:00")
    for t in range(t0, end, 60):
        rth = t >= open_ts
        if not rth and rng.random() < 0.3:
            continue  # premarket minutes without trades
        step = rng.gauss(0, 0.0006 if rth else 0.0002)
        o = price
        c = price * (1 + step)
        h = max(o, c) * (1 + abs(rng.gauss(0, 0.0002)))
        l = min(o, c) * (1 - abs(rng.gauss(0, 0.0002)))
        v = int(base_volume * (rng.uniform(0.6, 1.6) if rth else rng.uniform(0.005, 0.03)))
        vw = None if (not rth and rng.random() < 0.5) else round((h + l + c) / 3 + rng.gauss(0, 0.01), 4)
        bars.append({"t": t, "o": round(o, 4), "h": round(h, 4), "l": round(l, 4), "c": round(c, 4),
                     "v": v, "vw": vw, "n": v // 100})
        price = c
    return bars


def _daily(rng, day, n, price):
    out, d = [], date.fromisoformat(day)
    days = []
    while len(days) < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            days.append(d)
    for d in reversed(days):
        o = price
        c = price * (1 + rng.gauss(0, 0.008))
        out.append({"date": d.isoformat(), "o": round(o, 2), "h": round(max(o, c) * 1.004, 2),
                    "l": round(min(o, c) * 0.996, 2), "c": round(c, 2), "v": int(rng.uniform(4e7, 9e7))})
        price = c
    return out


def _profile(rng, base_volume):
    out, t = {}, et_datetime(DAY, "09:30")
    for _ in range(90):
        out[t.strftime("%H:%M")] = round(base_volume * rng.uniform(0.8, 1.2), 1)
        t += timedelta(minutes=1)
    return out


def make_session(seed=7, news_count=60):
    rng = random.Random(seed)
    symbols = {}
    for sym, price, vol in (("SPY", 625.0, 400_000), ("QQQ", 560.0, 300_000)):
        daily = _daily(rng, DAY, 30, price)
        start = daily[-1]["c"] * (1 + rng.gauss(0, 0.003))
        symbols[sym] = {"daily": daily, "minutes": _minutes(rng, DAY, start, vol),
                        "volume_profile": _profile(rng, vol)}
    news = []
    first, last = checkpoint_ts(DAY, "04:00") - 6 * 3600, checkpoint_ts(DAY, "10:30")
    pool = [
        (["SPY", "QQQ"], "Stock futures edge higher ahead of inflation data"),
        ([], "Fed's Waller says policy is well positioned; markets watch rate path"),
        (["NVDA"], "Nvidia supplier reports record quarterly revenue on AI demand"),
        (["AAPL"], "Apple shares slip in premarket after analyst downgrade"),
        (["TSLA", "F", "GM", "RIVN", "LCID", "NIO"], "EV makers mixed as tariff headlines swirl"),
        (["JPM"], "JPMorgan beats second-quarter profit estimates, trading revenue jumps"),
        ([], "Treasury yields dip after CPI comes in line with forecasts"),
        (["XOM"], "Exxon to expand Permian output"),
    ]
    for i in range(news_count):
        syms, headline = pool[i % len(pool)]
        created = rng.randint(first, last)
        news.append({"id": str(1000 + i), "headline": f"{headline} ({i})",
                     "summary": ("Long-form summary text describing the story in detail. " * 8).strip(),
                     "symbols": list(syms), "source": "benzinga", "created_at": _iso(created)})
    macro = [
        {"kind": "cpi", "name": "CPI (Jun)", "scheduled_at": _iso(checkpoint_ts(DAY, "08:30"))},
        {"kind": "sentiment", "name": "UMich sentiment (prelim)",
         "scheduled_at": _iso(checkpoint_ts(DAY, "10:00"))},
        {"kind": "fomc", "name": "FOMC minutes (next day)",
         "scheduled_at": _iso(checkpoint_ts("2026-07-16", "14:00"))},
    ]
    return {"date": DAY, "schedule": {"open": "09:30", "close": "16:00", "early_close": False},
            "symbols": symbols, "news": news, "macro": macro, "provenance": {"source": "synthetic"}}


@pytest.fixture(scope="module")
def session():
    return make_session()


# ---------------------------------------------------------------- field contract
@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("checkpoint", CHECKPOINTS_ET)
def test_fields_match_contract(session, checkpoint, variant):
    p = pk.build_packet(session, checkpoint, variant)
    assert tuple(p) == PACKET_FIELDS["top"]
    assert p["version"] == "opening-lab-packet-v1" and p["variant"] == variant
    assert p["checkpoint_et"] == checkpoint and p["weekday"] == "Wednesday"
    assert p["minutes_since_open"] == CHECKPOINTS_ET.index(checkpoint) * 5
    assert p["early_close"] is False
    assert set(p["symbols"]) == set(SYMBOLS)
    for block in p["symbols"].values():
        assert tuple(block) == PACKET_FIELDS["symbol"]
        assert tuple(block["bars"]["columns"]) == BAR_COLUMNS
        assert all(len(row) == len(BAR_COLUMNS) for row in block["bars"]["rows"])
        if variant == "bars":
            assert block["features"] is None
        else:
            assert tuple(block["features"]) == PACKET_FIELDS["features"]
    if variant == "full":
        assert p["news"] and p["macro"]
        for item in p["news"]:
            assert set(item) == {"id", "age_min", "headline", "summary", "symbols"}
        for event in p["macro"]:
            assert set(event) == {"time_et", "kind", "name", "status"}
    else:
        assert p["news"] == [] and p["macro"] == []
    text = pk.render_user_message(p)
    assert DAY not in text and "2026-" not in text  # the calendar date never leaks
    assert json.loads(text) == p


def test_render_is_compact_and_sorted(session):
    p = pk.build_packet(session, "09:40", "market")
    text = pk.render_user_message(p)
    assert text == json.dumps(p, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def test_rejects_unknown_checkpoint_and_variant(session):
    with pytest.raises(ValueError):
        pk.build_packet(session, "10:05", "bars")
    with pytest.raises(ValueError):
        pk.build_packet(session, "09:30", "everything")


# ---------------------------------------------------------------- causality
def _poison_future(session, c_ts):
    """Rewrite everything that must not be visible at checkpoint C."""
    s = copy.deepcopy(session)
    for data in s["symbols"].values():
        for bar in data["minutes"]:
            if bar["t"] + 60 > c_ts:
                bar.update(o=bar["o"] * 1.5, h=bar["h"] * 2, l=bar["l"] * 0.1, c=bar["c"] * 0.5,
                           v=bar["v"] * 50 + 7, vw=123.45, n=1)
        # an extra future bar and later daily data (the session itself and after)
        data["minutes"].append({"t": c_ts, "o": 1, "h": 999, "l": 0.5, "c": 2, "v": 10**9,
                                "vw": None, "n": 1})
        data["minutes"].sort(key=lambda b: b["t"])
        data["daily"] += [{"date": DAY, "o": 1, "h": 9999, "l": 0.01, "c": 5, "v": 1},
                          {"date": "2026-07-16", "o": 1, "h": 9999, "l": 0.01, "c": 7, "v": 1}]
    cutoff = c_ts - pk.NEWS_LAG_SECONDS
    for item in s["news"]:
        created = int(datetime.fromisoformat(item["created_at"]).timestamp())
        if created > cutoff:
            item.update(headline="FUTURE: Fed emergency cut, stocks soar", summary="future",
                        symbols=["SPY", "QQQ"])
    s["news"] += [{"id": f"late{k}", "headline": f"LATE market headline {k}", "summary": "late",
                   "symbols": ["SPY"], "source": "x", "created_at": _iso(cutoff + 1 + k * 30)}
                  for k in range(20)]
    return s


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("checkpoint", CHECKPOINTS_ET)
def test_future_data_cannot_reach_packet(session, checkpoint, variant):
    c_ts = checkpoint_ts(DAY, checkpoint)
    before = pk.build_packet(session, checkpoint, variant)
    after = pk.build_packet(_poison_future(session, c_ts), checkpoint, variant)
    assert pk.render_user_message(after) == pk.render_user_message(before)


@pytest.mark.parametrize("checkpoint", CHECKPOINTS_ET)
def test_bar_boundary_last_visible_bar_matters(session, checkpoint):
    """Non-vacuous check: the bar ending exactly at C is visible, the one starting at C is not."""
    c_ts = checkpoint_ts(DAY, checkpoint)
    base = pk.build_packet(session, checkpoint, "market")
    for start, should_change in ((c_ts - 60, True), (c_ts, False)):
        s = copy.deepcopy(session)
        bar = next(b for b in s["symbols"]["SPY"]["minutes"] if b["t"] == start)
        bar["c"] += 1.0
        changed = pk.build_packet(s, checkpoint, "market") != base
        assert changed is should_change, (checkpoint, start)


def test_0930_has_no_rth_bars_and_uses_premarket(session):
    p = pk.build_packet(session, "09:30", "market")
    for sym in SYMBOLS:
        block, data = p["symbols"][sym], session["symbols"][sym]
        pre = [b for b in data["minutes"] if b["t"] < checkpoint_ts(DAY, "09:30")]
        f = block["features"]
        assert block["bars"]["rows"] == []
        assert block["last"] == round(pre[-1]["c"], 2) == f["premarket_last"]
        assert f["gap_pct"] == round(100 * (pre[-1]["c"] / data["daily"][-1]["c"] - 1), 3)
        for key in ("session_vwap", "session_high", "session_low", "return_since_open_pct", "rvol"):
            assert f[key] is None


def test_news_lag_boundary(session):
    c_ts = checkpoint_ts(DAY, "09:45")
    s = copy.deepcopy(session)
    s["news"] = [
        {"id": "a", "headline": "Stocks at the boundary", "summary": "", "symbols": ["SPY"],
         "source": "x", "created_at": _iso(c_ts - 60)},
        {"id": "b", "headline": "Stocks one second late", "summary": "", "symbols": ["SPY"],
         "source": "x", "created_at": _iso(c_ts - 59)},
    ]
    news = pk.build_packet(s, "09:45", "full")["news"]
    assert [n["headline"] for n in news] == ["Stocks at the boundary"]
    assert news[0]["id"] == "n1" and news[0]["age_min"] == 1


def test_news_selection_caps_prefers_market_and_orders_newest_first(session):
    p = pk.build_packet(session, "10:00", "full")
    news = p["news"]
    assert len(news) == pk.NEWS_LIMIT
    assert [n["id"] for n in news] == [f"n{i}" for i in range(1, len(news) + 1)]
    assert [n["age_min"] for n in news] == sorted(n["age_min"] for n in news)
    assert all(len(n["headline"]) <= 200 and len(n["summary"]) <= 240 and len(n["symbols"]) <= 5
               for n in news)
    # with plenty of market-wide items visible, single-name stories are not chosen
    assert not any(n["headline"].startswith(("Nvidia", "Apple", "Exxon", "JPMorgan")) for n in news)


def test_macro_status_flips_at_scheduled_time(session):
    status = {cp: {e["time_et"]: e["status"] for e in pk.build_packet(session, cp, "full")["macro"]}
              for cp in CHECKPOINTS_ET}
    for cp in CHECKPOINTS_ET:
        assert status[cp]["08:30"] == "released"
        assert "14:00" not in status[cp]  # another day's event is not listed
    assert status["09:55"]["10:00"] == "upcoming"
    assert status["10:00"]["10:00"] == "released"


def test_prior_decisions_compacted_and_validated(session):
    rows = [
        {"checkpoint_et": "09:30", "action": "WAIT", "symbol": None, "spy_p_up": 0.5123,
         "qqq_p_up": 0.49, "reason": "dropped"},
        {"checkpoint_et": "09:40", "action": "LONG", "symbol": "QQQ", "spy_p_up": 0.55,
         "qqq_p_up": 0.58},
    ]
    p = pk.build_packet(session, "09:45", "bars", rows)
    assert p["prior_decisions"] == [
        {"checkpoint_et": "09:30", "action": "WAIT", "symbol": None, "spy_p_up": 0.512, "qqq_p_up": 0.49},
        {"checkpoint_et": "09:40", "action": "LONG", "symbol": "QQQ", "spy_p_up": 0.55, "qqq_p_up": 0.58},
    ]
    assert pk.build_packet(session, "09:30", "bars")["prior_decisions"] == []
    with pytest.raises(ValueError):  # same checkpoint is not earlier
        pk.build_packet(session, "09:40", "bars", rows)
    with pytest.raises(ValueError):  # later than the checkpoint
        pk.build_packet(session, "09:35", "bars", rows)
    with pytest.raises(ValueError):  # out of order
        pk.build_packet(session, "09:50", "bars", list(reversed(rows)))
    with pytest.raises(ValueError):  # not a checkpoint
        pk.build_packet(session, "09:50", "bars", [dict(rows[0], checkpoint_et="9:31")])


# ---------------------------------------------------------------- feature arithmetic
def _hand_session():
    """Tiny session with numbers checkable by hand."""
    daily = [{"date": f"2026-06-{d:02d}", "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.0, "v": 1}
             for d in range(1, 21)]  # 20 bars, TR = 2 each
    daily.append({"date": "2026-07-14", "o": 100.0, "h": 104.0, "l": 100.0, "c": 103.0, "v": 1})
    # last 20 TRs: 19 x 2 + max(4, |104-100|, |100-100|) = 4  -> mean 2.1, 2.1/103*100
    t = lambda hhmm: checkpoint_ts(DAY, hhmm)
    minutes = [
        {"t": t("04:00"), "o": 103.5, "h": 104.0, "l": 103.0, "c": 103.8, "v": 100, "vw": None, "n": 1},
        {"t": t("09:29"), "o": 103.8, "h": 104.5, "l": 103.6, "c": 104.0, "v": 300, "vw": None, "n": 1},
        {"t": t("09:30"), "o": 104.2, "h": 105.0, "l": 104.0, "c": 104.6, "v": 1000, "vw": 104.5, "n": 1},
        {"t": t("09:31"), "o": 104.6, "h": 104.9, "l": 103.9, "c": 104.2, "v": 3000, "vw": None, "n": 1},
        {"t": t("09:32"), "o": 104.2, "h": 104.4, "l": 104.1, "c": 104.3, "v": 1000, "vw": 104.3, "n": 1},
        {"t": t("09:35"), "o": 1, "h": 999, "l": 0.1, "c": 1, "v": 10**9, "vw": None, "n": 1},
    ]
    profile = {"09:30": 2000, "09:31": 2000, "09:32": 2000, "09:33": 1000, "09:34": 1000}
    data = {"daily": daily, "minutes": minutes, "volume_profile": profile}
    return {"date": DAY, "schedule": {"open": "09:30", "close": "16:00", "early_close": False},
            "symbols": {"SPY": data, "QQQ": copy.deepcopy(data)}, "news": [], "macro": [],
            "provenance": {}}


def test_feature_arithmetic_by_hand():
    p = pk.build_packet(_hand_session(), "09:35", "market")
    block = p["symbols"]["SPY"]
    f = block["features"]
    assert [r[0] for r in block["bars"]["rows"]] == ["09:30", "09:31", "09:32"]
    assert block["last"] == 104.3
    assert f["prior_close"] == f["prior_day_close"] == 103.0
    assert (f["prior_day_high"], f["prior_day_low"]) == (104.0, 100.0)
    assert f["gap_pct"] == round(100 * (104.2 / 103 - 1), 3) == 1.165
    assert (f["premarket_high"], f["premarket_low"], f["premarket_last"]) == (104.5, 103.0, 104.0)
    assert f["premarket_volume"] == 400
    assert f["atr20_pct"] == round(100 * 2.1 / 103, 3) == 2.039
    # vwap: 104.5*1000 + typical(104.9,103.9,104.2)=104.3333*3000 + 104.3*1000, / 5000
    vwap = (104.5 * 1000 + (104.9 + 103.9 + 104.2) / 3 * 3000 + 104.3 * 1000) / 5000
    assert f["session_vwap"] == round(vwap, 2) == 104.36
    assert (f["session_high"], f["session_low"]) == (105.0, 103.9)
    assert f["return_since_open_pct"] == round(100 * (104.3 / 104.2 - 1), 3) == 0.096
    # five RTH minutes ended by 09:35 (09:30-09:34): 5000 / (2000*3 + 1000*2); 09:33-34 bars missing
    assert f["rvol"] == round(5000 / 8000, 3) == 0.625


def test_features_null_when_inputs_missing():
    s = _hand_session()
    s["symbols"]["SPY"]["daily"] = s["symbols"]["SPY"]["daily"][-5:]
    s["symbols"]["SPY"]["volume_profile"] = {"09:30": 2000}
    f = pk.build_packet(s, "09:35", "market")["symbols"]["SPY"]["features"]
    assert f["atr20_pct"] is None and f["rvol"] is None and f["prior_close"] == 103.0
    del s["symbols"]["QQQ"]
    q = pk.build_packet(s, "09:35", "full")["symbols"]["QQQ"]
    assert q["last"] is None and q["bars"]["rows"] == []
    assert tuple(q["features"]) == PACKET_FIELDS["features"]
    assert all(v is None for v in q["features"].values())


# ---------------------------------------------------------------- size
def packet_sizes(session):
    out = {}
    for cp in ("09:30", "10:00"):
        for variant in VARIANTS:
            text = pk.render_user_message(pk.build_packet(session, cp, variant))
            out[(cp, variant)] = (len(text), pk.estimate_tokens(text))
    return out


def test_size_bound(session):
    heavy = make_session(news_count=200)
    for s in (session, heavy):
        sizes = packet_sizes(s)
        assert sizes[("10:00", "full")][1] < 6000, sizes
        assert sizes[("09:30", "bars")][1] < sizes[("10:00", "bars")][1]


def test_prompt_file_present_and_bounded():
    text = (Path(pk.__file__).with_name("prompt.txt")).read_text()
    assert len(text.split()) < 600
    for phrase in ("OPEN of the bar", "CLOSE ten minutes after entry", "untrusted", "WAIT",
                   "calendar date", "300 characters"):
        assert phrase in text


def test_forced_prompt_differs_only_in_the_trade_decision():
    here = Path(pk.__file__).parent
    standard, forced = (here / "prompt.txt").read_text(), (here / "prompt_forced.txt").read_text()
    assert len(forced.split()) < 600
    assert "WAIT is not allowed" in forced and "never WAIT" in forced
    changed = [line for line in forced.splitlines() if line not in standard.splitlines()]
    assert len(changed) == 3   # trade decision, release risk, output
    for phrase in ("OPEN of the bar", "CLOSE ten minutes after entry", "untrusted", "calendar date"):
        assert phrase in forced
