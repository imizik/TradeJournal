"""Owner-entry replay: selection, blind causal packets, moves and the agree/pass split."""

import copy

from research.opening_lab import mytrades
from research.opening_lab.contract import checkpoint_ts
from research.opening_lab.tests.test_packet import DAY, make_session
from research.opening_lab.tests.test_trades import with_cross


def journal_row(**kw):
    row = {"id": "t1", "ticker": "NBIS", "instrument_type": "option", "option_type": "call",
           "opened_at": f"{DAY}T09:42:00", "strike": 180.0, "expiration": DAY, "realized_pnl": 230.0,
           "pnl_pct": 0.41, "hold_duration_mins": 113, "status": "closed"}
    return {**row, **kw}


def test_select_keeps_opening_options_after_cutoff():
    rows = [journal_row(), journal_row(id="late", opened_at=f"{DAY}T10:31:00"),
            journal_row(id="old", opened_at="2026-06-30T09:45:00"),
            journal_row(id="stock", instrument_type="stock", option_type=None),
            journal_row(id="spx", ticker="SPXW", option_type="put")]
    picks = mytrades.select_trades(rows)
    assert [p["id"] for p in picks] == ["spx", "t1"]   # same minute: by id
    assert picks[0]["underlying"] == "SPY" and picks[0]["side"] == "put"


def _session_with_stock():
    session = with_cross(make_session())
    stock = {**copy.deepcopy(session["symbols"]["QQQ"]), "volume_profile": {}}
    session["news"] = session["news"] + [
        {"id": "s1", "headline": "Nebius signs capacity deal", "summary": "", "symbols": ["NBIS"],
         "source": "benzinga", "created_at": "2026-07-15T13:30:00Z"},
        {"id": "s2", "headline": "Nebius shares halted", "summary": "", "symbols": ["NBIS"],
         "source": "benzinga", "created_at": "2026-07-15T13:50:00Z"}]   # 09:50 ET, after entry
    return session, stock


def test_packet_is_blind_and_causal():
    session, stock = _session_with_stock()
    pick = mytrades.select_trades([journal_row()])[0]
    packet = mytrades.build_mytrade_packet(session, pick, stock)
    text = str(packet)
    assert "call" not in text.lower().replace("calls", "") and "230" not in text   # nothing about the owner's trade
    assert [n["headline"] for n in packet["stock_news"]] == ["Nebius signs capacity deal"]

    c_ts = checkpoint_ts(DAY, "09:42")
    later = copy.deepcopy(stock)
    for b in later["minutes"]:
        if b["t"] + 60 > c_ts:
            b.update(o=b["o"] * 2, h=b["h"] * 2, l=b["l"] * 2, c=b["c"] * 2)
    assert mytrades.build_mytrade_packet(session, pick, later) == packet
    assert packet["stock"]["features"]["rvol"] is None


def test_moves_and_score_split():
    session, stock = _session_with_stock()
    pick = mytrades.select_trades([journal_row()])[0]
    m = mytrades.moves(stock, DAY, "09:42")
    by_t = {b["t"]: b for b in stock["minutes"]}
    start = checkpoint_ts(DAY, "09:43")
    assert m[15] == round((by_t[start + 900]["o"] / by_t[start]["o"] - 1) * 1e4, 2)

    loser = {**pick, "id": "t2", "realized_pnl": -100.0, "pnl_pct": -0.5}
    results = [{"pick": pick, "call": "CALLS", "moves": {15: 10.0, 30: -5.0}},
               {"pick": loser, "call": "PASS", "moves": {15: -8.0, 30: -12.0}},
               {"pick": loser, "call": None, "moves": {15: None, 30: None}}]
    s = mytrades.score(results)
    assert s["answered"] == 2 and s["unanswered"] == 1
    assert s["agree"]["total_pnl"] == 230.0 and s["pass"]["total_pnl"] == -100.0
    assert s["direction"]["15m"]["yours_right"] == "1/2" and s["direction"]["15m"]["claude_right"] == "1/1"
    assert "Claude would pass" in mytrades.render(s, results)
