import math

import pytest

from research.opening_lab import baselines
from research.opening_lab.baselines import BASELINES
from research.opening_lab.contract import (BAR_COLUMNS, CHECKPOINTS_ET, PACKET_FIELDS,
                                           validate_forecast)


def _minutes_since_open(hhmm):
    hh, mm = (int(x) for x in hhmm.split(":"))
    return (hh - 9) * 60 + mm - 30


def _et(i):
    return f"{9 + (30 + i) // 60:02d}:{(30 + i) % 60:02d}"


def flat_rows(n, price=100.0):
    return [[_et(i), price, price, price, price, 1000] for i in range(n)]


def packet(checkpoint="09:50", spy_rows=None, qqq_rows=None, spy=None, qqq=None,
           variant="market", last=None):
    """A contract-shaped packet; features null unless given, whole block null for bars."""
    def sym(rows, feats, sym_last):
        rows = rows or []
        if variant == "bars":
            features = None
        else:
            features = {k: None for k in PACKET_FIELDS["features"]}
            features.update(feats or {})
        if sym_last is None and rows:
            sym_last = rows[-1][4]
        return {"bars": {"columns": list(BAR_COLUMNS), "rows": rows},
                "last": sym_last, "features": features}
    last = last or {}
    return {"version": 1, "variant": variant, "checkpoint_et": checkpoint, "weekday": "Wed",
            "minutes_since_open": _minutes_since_open(checkpoint), "early_close": False,
            "symbols": {"SPY": sym(spy_rows, spy, last.get("SPY")),
                        "QQQ": sym(qqq_rows, qqq, last.get("QQQ"))},
            "news": [], "macro": [], "prior_decisions": []}


def is_flat(f):
    return f["action"] == "WAIT" and f["symbol"] is None and f["spy_p_up"] == f["qqq_p_up"] == 0.5


def test_registry_names():
    assert set(BASELINES) == {"coin", "always_long", "momentum", "fade_open", "orb",
                              "vwap_side", "gap_fill"}


@pytest.mark.parametrize("name", sorted(BASELINES))
@pytest.mark.parametrize("pk", [
    {},
    {"symbols": None},
    packet("09:30"),                                     # no bars, all-null features
    packet("09:50", flat_rows(20), flat_rows(20), variant="bars"),
    packet("09:50", flat_rows(20), flat_rows(20)),       # flat tape, null features
    packet("09:50", flat_rows(20), flat_rows(20), spy={"atr20_pct": 0.0, "session_vwap": 0,
                                                       "gap_pct": 5.0, "prior_close": None}),
])
def test_every_baseline_degrades_to_valid_flat_output(name, pk):
    f = BASELINES[name](pk)
    assert validate_forecast(f) == f
    if name == "always_long":
        assert f["action"] == "LONG" and f["symbol"] == "SPY"
        assert f["spy_p_up"] == f["qqq_p_up"] == baselines.ALWAYS_LONG_P
    else:
        assert is_flat(f)


def test_probabilities_stay_in_bounds():
    huge = {"return_since_open_pct": 50.0, "atr20_pct": 0.5, "session_vwap": 50.0,
            "gap_pct": -40.0, "prior_close": 1000.0}
    pk = packet("09:55", flat_rows(25), flat_rows(25), spy=huge, qqq=huge)
    for name, rule in BASELINES.items():
        f = rule(pk)
        for key in ("spy_p_up", "qqq_p_up"):
            assert baselines.P_MIN <= f[key] <= baselines.P_MAX, name


def test_momentum_hand_computed():
    # SPY +0.5 % since open, ATR 1 %, 15 minutes: scale = sqrt(15/390), z = 0.5 / scale.
    pk = packet("09:45", flat_rows(15), flat_rows(15),
                spy={"return_since_open_pct": 0.5, "atr20_pct": 1.0},
                qqq={"return_since_open_pct": 0.05, "atr20_pct": 1.0})
    f = baselines.momentum(pk)
    z = 0.5 / math.sqrt(15 / 390)
    assert f["spy_p_up"] == pytest.approx(0.5 + 0.05 * z)
    assert f["action"] == "LONG" and f["symbol"] == "SPY"
    # QQQ: |z| = 0.38 < 1 -> leans but would not trade.
    assert 0.5 < f["qqq_p_up"] < 0.52


def test_momentum_takes_strongest_symbol_and_shorts():
    pk = packet("09:45", flat_rows(15), flat_rows(15),
                spy={"return_since_open_pct": 0.3, "atr20_pct": 1.0},
                qqq={"return_since_open_pct": -0.6, "atr20_pct": 1.0})
    f = baselines.momentum(pk)
    assert (f["action"], f["symbol"]) == ("SHORT", "QQQ")
    assert f["qqq_p_up"] < 0.5 < f["spy_p_up"]


def test_fade_open_bets_against_first_five_minutes():
    rows = flat_rows(10)
    rows[0][1] = 100.0          # 09:30 open
    rows[4][4] = 100.2          # 09:34 close: +0.2 %
    pk = packet("09:40", rows, flat_rows(10), spy={"atr20_pct": 1.0}, qqq={"atr20_pct": 1.0})
    f = baselines.fade_open(pk)
    z = -0.2 / math.sqrt(5 / 390)
    assert f["spy_p_up"] == pytest.approx(0.5 + 0.05 * z)
    assert (f["action"], f["symbol"]) == ("SHORT", "SPY")
    assert f["qqq_p_up"] == 0.5


def test_fade_open_needs_all_five_opening_bars():
    rows = flat_rows(10)
    rows[4][4] = 100.5
    del rows[2]                 # 09:32 missing: no fade, no substitute bar
    pk = packet("09:40", rows, flat_rows(10), spy={"atr20_pct": 1.0})
    assert is_flat(baselines.fade_open(pk))
    assert is_flat(baselines.fade_open(packet("09:30", spy={"atr20_pct": 1.0})))


def test_orb_breakout_inside_and_too_early():
    rows = flat_rows(20)
    rows[3][2], rows[7][3] = 101.0, 99.0      # range 99..101 inside the first 15 bars
    up = packet("09:50", rows, flat_rows(20), last={"SPY": 101.5}, variant="bars")
    f = baselines.orb(up)
    assert (f["action"], f["symbol"]) == ("LONG", "SPY")
    assert f["spy_p_up"] == pytest.approx(0.5 + 0.05 * baselines.ORB_Z)
    down = baselines.orb(packet("09:50", rows, flat_rows(20), last={"SPY": 98.0}))
    assert (down["action"], down["symbol"]) == ("SHORT", "SPY")
    inside = baselines.orb(packet("09:50", rows, flat_rows(20), last={"SPY": 100.5}))
    assert inside["action"] == "WAIT" and inside["spy_p_up"] == 0.5
    assert is_flat(baselines.orb(packet("09:40", rows[:10], flat_rows(10))))


def test_vwap_side_hand_computed():
    pk = packet("09:50", flat_rows(20), flat_rows(20), last={"SPY": 100.3, "QQQ": 99.98},
                spy={"session_vwap": 100.0, "atr20_pct": 1.0},
                qqq={"session_vwap": 100.0, "atr20_pct": 1.0})
    f = baselines.vwap_side(pk)
    z = 0.3 / math.sqrt(20 / 390)
    assert f["spy_p_up"] == pytest.approx(0.5 + 0.05 * z)
    assert (f["action"], f["symbol"]) == ("LONG", "SPY")
    assert f["qqq_p_up"] < 0.5


def test_gap_fill_toward_prior_close_until_filled():
    feats = {"gap_pct": 0.5, "atr20_pct": 1.0, "prior_close": 100.0}
    f = baselines.gap_fill(packet("09:40", flat_rows(10), flat_rows(10),
                                  last={"SPY": 100.3}, spy=feats))
    assert (f["action"], f["symbol"]) == ("SHORT", "SPY")
    assert f["spy_p_up"] == pytest.approx(0.5 - 0.05 * 4 * 0.5)
    filled = baselines.gap_fill(packet("09:40", flat_rows(10), flat_rows(10),
                                       last={"SPY": 99.9}, spy=feats))
    assert is_flat(filled)
    small = baselines.gap_fill(packet("09:40", flat_rows(10), flat_rows(10), last={"SPY": 100.1},
                                      spy={**feats, "gap_pct": 0.2}))
    assert is_flat(small)
    down = baselines.gap_fill(packet("09:30", last={"QQQ": 99.0},
                                     qqq={"gap_pct": -1.0, "atr20_pct": 1.0, "prior_close": 100.0}))
    assert (down["action"], down["symbol"]) == ("LONG", "QQQ")


def test_last_may_be_a_dict_or_missing():
    rows = flat_rows(20)
    rows[3][2] = 101.0
    as_dict = packet("09:50", rows, flat_rows(20), last={"SPY": {"price": 102.0}})
    assert baselines.orb(as_dict)["action"] == "LONG"
    rows[-1][4] = 102.0
    no_last = packet("09:50", rows, flat_rows(20))
    no_last["symbols"]["SPY"]["last"] = None
    assert baselines.orb(no_last)["action"] == "LONG"


@pytest.mark.parametrize("checkpoint", CHECKPOINTS_ET)
def test_every_checkpoint_on_a_flat_tape_is_valid(checkpoint):
    n = _minutes_since_open(checkpoint)
    feats = {"atr20_pct": 1.0, "return_since_open_pct": 0.0, "session_vwap": 100.0,
             "gap_pct": 0.0, "prior_close": 100.0}
    pk = packet(checkpoint, flat_rows(n), flat_rows(n), spy=feats, qqq=feats)
    for name, rule in BASELINES.items():
        f = rule(pk)
        assert validate_forecast(f) == f
        if name != "always_long":
            assert f["action"] == "WAIT", name
