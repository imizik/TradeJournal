"""get_catalysts: SEC filings, halts and headlines since the close, each with the tape's reaction. Pure; no network."""
from datetime import date, datetime

import pytest

from app.ai import copilot_catalysts as cat
from app.ai import copilot_tools
from app.ai.copilot_fixture import FixtureEvidence
from app.ai.copilot_tool_summary import summarize
from app.engine.chart_math import ET

ATOM = """<?xml version="1.0" encoding="ISO-8859-1" ?>
<feed xmlns="http://www.w3.org/2005/Atom">
<title>NEBIUS GROUP N.V.</title>
<entry>
  <category label="form type" scheme="https://www.sec.gov/" term="6-K" />
  <link href="https://www.sec.gov/Archives/edgar/data/1513845/000110465926000001-index.htm" rel="alternate" type="text/html" />
  <summary type="html"> &lt;b&gt;Filed:&lt;/b&gt; 2026-11-27 &lt;b&gt;AccNo:&lt;/b&gt; 0001104659-26-000001 &lt;b&gt;Size:&lt;/b&gt; 1 MB</summary>
  <title>6-K  - Report of foreign issuer [Rules 13a-16 and 15d-16]</title>
  <updated>2026-11-27T07:05:12-05:00</updated>
</entry>
<entry>
  <category label="form type" scheme="https://www.sec.gov/" term="8-K/A" />
  <link href="https://www.sec.gov/a" rel="alternate" type="text/html" />
  <summary type="html">Item 2.02: Results Item 9.01: Exhibits Item 2.02</summary>
  <title>8-K/A - Current report, amended</title>
  <updated>2026-11-26T16:31:00-05:00</updated>
</entry>
<entry>
  <category label="form type" scheme="https://www.sec.gov/" term="424B5" />
  <link href="https://www.sec.gov/b" rel="alternate" type="text/html" />
  <summary type="html">Prospectus</summary>
  <title>424B5 - Prospectus</title>
  <updated>2026-11-26T18:00:00-05:00</updated>
</entry>
<entry>
  <category label="form type" scheme="https://www.sec.gov/" term="SD" />
  <link href="https://www.sec.gov/c" rel="alternate" type="text/html" />
  <summary type="html">Specialized disclosure</summary>
  <title>SD - Specialized disclosure</title>
  <updated>2026-11-26T12:00:00-05:00</updated>
</entry>
<entry>
  <category label="form type" scheme="https://www.sec.gov/" term="4" />
  <link href="https://www.sec.gov/d" rel="alternate" type="text/html" />
  <summary type="html">Insider</summary>
  <title>4 - Statement of changes</title>
  <updated>not a time</updated>
</entry>
</feed>"""

HALTS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:ndaq="http://www.nasdaqtrader.com/">
<channel><title>NASDAQTrader.com</title>
<item>
  <title>NBIS</title>
  <ndaq:HaltDate>11/27/2026</ndaq:HaltDate><ndaq:HaltTime>10:02:15</ndaq:HaltTime>
  <ndaq:IssueSymbol>NBIS</ndaq:IssueSymbol><ndaq:ReasonCode>LUDP</ndaq:ReasonCode>
  <ndaq:ResumptionDate>11/27/2026</ndaq:ResumptionDate><ndaq:ResumptionTradeTime>10:07:15</ndaq:ResumptionTradeTime>
</item>
<item>
  <title>CRWV</title>
  <ndaq:HaltDate>11/27/2026</ndaq:HaltDate><ndaq:HaltTime>11:00:00</ndaq:HaltTime>
  <ndaq:IssueSymbol>CRWV</ndaq:IssueSymbol><ndaq:ReasonCode>T1</ndaq:ReasonCode>
  <ndaq:ResumptionDate></ndaq:ResumptionDate><ndaq:ResumptionTradeTime></ndaq:ResumptionTradeTime>
</item>
</channel></rss>"""


def _at(text: str) -> float:
    return datetime.fromisoformat(text).replace(tzinfo=ET).timestamp()


def _bars(start: float, n: int, *, spike_at: int | None = None, jump: float = 0.0) -> list[dict]:
    """Flat minute bars at 100 with volume 100; one 10x minute at ``spike_at`` after which price sits ``jump`` higher."""
    out = []
    for i in range(n):
        after = spike_at is not None and i >= spike_at
        out.append({"time": start + 60 * i, "close": 100 + (jump if after else 0), "volume": 1000 if i == spike_at else 100})
    return out


def test_form_families_drop_amendments_and_ignore_the_rest():
    assert cat.form_kind("8-K/A") == "current_report" and cat.form_kind(" 424b5 ") == "offering"
    assert cat.form_kind("4") == "insider" and cat.form_kind("SC 13G/A") == "ownership"
    assert cat.form_kind("SD") is None and cat.form_kind(None) is None


def test_parse_filings_keeps_trade_moving_forms_with_their_acceptance_time():
    rows = cat.parse_filings(ATOM)
    assert [r["form"] for r in rows] == ["6-K", "8-K/A", "424B5"]  # SD is not kept; a bad timestamp is skipped
    six, eight, _ = rows
    assert six["at"] == _at("2026-11-27T07:05:12") and six["kind"] == "current_report"
    assert six["url"].endswith("-index.htm") and "<b>" not in six["title"] and six["detail"] is None
    assert eight["detail"] == "Item 2.02, Item 9.01"  # items deduplicated, in order


def test_feeds_with_entity_declarations_are_refused():
    with pytest.raises(ValueError):
        cat.parse_filings('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><feed/>')


def test_parse_halts_reads_only_the_symbol_in_new_york_time():
    rows = cat.parse_halts(HALTS, "nbis")
    assert rows == [{"at": _at("2026-11-27T10:02:15"), "reason": "LUDP", "resumed_at": _at("2026-11-27T10:07:15")}]
    assert cat.parse_halts(HALTS, "CRWV")[0]["resumed_at"] is None


def test_reaction_measures_the_move_and_the_burst_against_the_hour_before():
    start = _at("2026-11-27T09:00:00")
    bars = _bars(start, 120, spike_at=60, jump=2.0)
    r = cat.reaction(bars, start + 60 * 60)
    assert r == {"move_15m_pct": 2.0, "volume_x": 2.8}  # (1000 + 4*100) / (5*100)
    assert cat.reaction(bars, start - 60) is None  # nothing before the item
    assert cat.reaction(_bars(start, 70), start + 10 * 60)["volume_x"] is None  # too little baseline


def test_a_sharp_minute_without_an_item_is_listed_and_an_explained_one_is_not():
    start = _at("2026-11-27T09:00:00")
    bars = _bars(start, 120, spike_at=60, jump=-1.5)
    found = cat.unexplained(bars, [])
    assert found == [{"at": start + 3600, "move_5m_pct": -1.5, "volume_x": 10.0}]
    assert cat.unexplained(bars, [start + 3600 - 120]) == []  # a filing two minutes earlier explains it
    assert cat.unexplained(_bars(start, 120, spike_at=60, jump=0.2), []) == []  # volume without a move is not sharp


def _ok(items):
    return {"state": "ok", "items": items}


def test_timeline_orders_items_newest_first_with_reactions_and_clock_times():
    since, now = _at("2026-11-26T16:00:00"), _at("2026-11-27T10:30:00")
    bars = _bars(_at("2026-11-27T08:00:00"), 150, spike_at=60, jump=1.0)
    out = cat.timeline("NBIS", since, now, filings=_ok(cat.parse_filings(ATOM)), halts=_ok(cat.parse_halts(HALTS, "NBIS")),
                       headlines=_ok([{"at": _at("2026-11-27T09:00:30"), "headline": "NBIS signs deal", "source": "benzinga",
                                       "url": None}, {"at": _at("2026-11-20T09:00:00"), "headline": "old", "source": "x"}]),
                       bars=bars)
    assert [i["type"] for i in out["items"]] == ["halt", "headline", "filing", "filing", "filing"]  # the old headline is cut
    assert out["items"][0]["at"] == "11-27 10:02 ET" and out["items"][0]["resumed"] == "11-27 10:07 ET"
    assert out["items"][1]["reaction"]["move_15m_pct"] == 1.0
    assert out["since"] == "11-26 16:00 ET" and out["sources"] == {"sec_filings": "ok", "halts": "ok", "headlines": "ok"}
    assert out["unexplained_moves"] == [] and "note" not in out


def test_no_item_from_working_sources_says_the_move_is_not_news_driven():
    since, now = _at("2026-11-26T16:00:00"), _at("2026-11-27T10:30:00")
    out = cat.timeline("NBIS", since, now, filings=_ok([]), halts=_ok([]), headlines=_ok([]), bars=None)
    assert "not news-driven" in out["note"] and out["minute_bars"] == "unavailable" and out["items"] == []


def test_a_failed_source_is_named_and_never_reads_as_no_news():
    since, now = _at("2026-11-26T16:00:00"), _at("2026-11-27T10:30:00")
    out = cat.timeline("NBIS", since, now, filings={"state": "unavailable", "reason": "SEC EDGAR could not be read"},
                       halts=_ok([]), headlines=_ok([]), bars=None)
    assert out["sources"]["sec_filings"] == "unavailable: SEC EDGAR could not be read"
    assert "note" not in out


def test_headlines_only_are_called_out():
    since, now = _at("2026-11-26T16:00:00"), _at("2026-11-27T10:30:00")
    out = cat.timeline("NBIS", since, now, filings=_ok([]), halts=_ok([]),
                       headlines=_ok([{"at": _at("2026-11-27T09:00:00"), "headline": "x", "source": "benzinga"}]), bars=None)
    assert out["note"] == "No SEC filing or halt since 11-26 16:00 ET; headlines only."


def test_last_close_walks_back_over_closed_days():
    days = {date(2026, 11, 26): {"status": "closed"}, date(2026, 11, 25): {"status": "open", "close": 16 * 60}}
    now = _at("2026-11-27T09:00:00")
    assert cat.last_close(now, days.get) == _at("2026-11-25T16:00:00")
    assert cat.last_close(now, lambda d: None) == now - cat.FALLBACK_SINCE


def test_fixture_is_marked_simulated_and_replay_refuses():
    data = FixtureEvidence().get_catalysts("NBIS")
    assert data["simulated"] is True and data["note"] == cat.FIXTURE_NOTE and data["items"]
    assert summarize("get_catalysts", data) == "Since 10-22 19:12 ET: 1 filing, 0 halts, 1 headline"


def test_the_tool_is_listed_with_its_provenance_and_validates_a_symbol():
    assert "get_catalysts" in {t["name"] for t in copilot_tools.TOOLS}
    assert "SEC EDGAR" in copilot_tools.PROVENANCE["get_catalysts"][0]
    assert copilot_tools.validate("get_catalysts", {"symbol": "nbis"}) == {"symbol": "NBIS"}


def test_a_window_the_bars_have_not_reached_is_not_called_a_15_minute_reaction():
    start = _at("2026-11-27T09:00:00")
    bars = _bars(start, 62, spike_at=60, jump=1.0)  # the item lands at minute 60; the bars end two minutes later
    r = cat.reaction(bars, start + 60 * 60)
    assert r["move_15m_pct"] is None and r["volume_x"] is None
    assert (r["move_so_far_pct"], r["minutes_so_far"]) == (1.0, 2)


def test_the_reaction_is_measured_by_the_clock_across_an_overnight_gap():
    evening = _at("2026-11-26T19:00:00")
    bars = _bars(evening, 60)  # 19:00-19:59 at 100, volume 100
    morning = _at("2026-11-27T04:00:00")
    bars += [{"time": morning + 60 * i, "close": 110.0, "volume": 5000} for i in range(30)]
    r = cat.reaction(bars, _at("2026-11-26T19:58:00"))
    # Only 19:58 and 19:59 fall inside the next 15 (and 5) minutes; the morning's bars are not part of the reaction.
    assert r["move_15m_pct"] == 0.0 and r["volume_x"] == 0.4  # 200 over 5 minutes of a 100 typical minute


def test_an_item_past_the_display_cap_still_explains_its_spike():
    since, now = _at("2026-11-27T08:00:00"), _at("2026-11-27T10:30:00")
    spike = _at("2026-11-27T09:00:00")
    bars = _bars(_at("2026-11-27T08:00:00"), 150, spike_at=60, jump=2.0)
    heads = [{"at": spike, "headline": "cause", "source": "benzinga"}]
    heads += [{"at": spike + 300 * (k + 1), "headline": f"later {k}", "source": "benzinga"} for k in range(cat.MAX_ITEMS)]
    out = cat.timeline("NBIS", since, now, filings=_ok([]), halts=_ok([]), headlines=_ok(heads), bars=bars)
    assert len(out["items"]) == cat.MAX_ITEMS and all(i["title"] != "cause" for i in out["items"])
    assert out["unexplained_moves"] == []


def test_headlines_only_needs_the_filings_and_halts_read_and_a_headline():
    since, now = _at("2026-11-26T16:00:00"), _at("2026-11-27T10:30:00")
    head = _ok([{"at": _at("2026-11-27T09:00:00"), "headline": "x", "source": "benzinga"}])
    halts_down = cat.timeline("NBIS", since, now, filings=_ok([]), halts={"state": "unavailable", "reason": "r"},
                              headlines=head, bars=None)
    nothing_read = cat.timeline("NBIS", since, now, filings=_ok([]), halts=_ok([]),
                                headlines={"state": "unavailable", "reason": "r"}, bars=None)
    assert "note" not in halts_down and "note" not in nothing_read


def test_a_spike_still_forming_is_not_called_a_five_minute_move():
    start = _at("2026-11-27T09:00:00")
    bars = _bars(start, 61, spike_at=60, jump=2.0)  # the spike is the last bar the feed holds
    assert cat.unexplained(bars, []) == [{"at": start + 3600, "volume_x": 10.0, "move_so_far_pct": 2.0, "minutes_so_far": 1}]


def test_the_fact_line_names_a_failed_source_and_says_nothing_when_none_was_read():
    since, now = _at("2026-11-26T16:00:00"), _at("2026-11-27T10:30:00")
    down = {"state": "unavailable", "reason": "r"}
    one_down = cat.timeline("NBIS", since, now, filings=_ok([]), halts=down, headlines=_ok([]), bars=None)
    assert summarize("get_catalysts", one_down) == "Since 11-26 16:00 ET: 0 filings, halts unavailable, 0 headlines"
    all_down = cat.timeline("NBIS", since, now, filings=down, halts=down, headlines=down, bars=None)
    assert summarize("get_catalysts", all_down) is None


def test_counts_cover_the_whole_window_not_only_the_items_shown():
    since, now = _at("2026-11-27T08:00:00"), _at("2026-11-27T10:30:00")
    filing = {"at": _at("2026-11-27T08:30:00"), "form": "8-K", "kind": "current_report", "title": "8-K", "url": None}
    heads = [{"at": _at("2026-11-27T09:00:00") + 60 * k, "headline": f"h{k}", "source": "benzinga"} for k in range(cat.MAX_ITEMS)]
    out = cat.timeline("NBIS", since, now, filings=_ok([filing]), halts=_ok([]), headlines=_ok(heads), bars=None)
    assert all(i["type"] == "headline" for i in out["items"]) and out["counts"] == {"filing": 1, "halt": 0, "headline": 15}
    assert summarize("get_catalysts", out) == "Since 11-27 08:00 ET: 1 filing, 0 halts, 15 headlines"
    assert "note" not in out  # a filing in the window, shown or not, is not "headlines only"


def test_a_slow_source_reads_as_unavailable_and_the_rest_still_stand(monkeypatch):
    import threading
    from app.engine import chart_calendar as cal
    release = threading.Event()
    monkeypatch.setattr(cat, "READ_DEADLINE", 0.2)
    monkeypatch.setattr(cal.chart_calendar, "hours", lambda d: None)
    monkeypatch.setattr(cat, "live_filings", lambda s: (release.wait(5), _ok([]))[1])  # a cold SEC ticker list
    monkeypatch.setattr(cat, "live_halts", lambda s: _ok([]))
    monkeypatch.setattr(cat, "live_headlines", lambda s, since: _ok([]))
    monkeypatch.setattr(cat, "_bars", lambda s, since, at: None)
    try:
        out = cat.live_catalysts("NBIS", datetime(2026, 11, 27, 15, 0, tzinfo=ET))
    finally:
        release.set()
    assert out["sources"] == {"sec_filings": "unavailable: did not answer in time", "halts": "ok", "headlines": "ok"}


def test_a_slow_calendar_falls_back_to_memory_inside_the_deadline(monkeypatch):
    import threading
    from app.engine import chart_calendar as cal
    release = threading.Event()
    monkeypatch.setattr(cat, "CALENDAR_WAIT", 0.1)
    monkeypatch.setattr(cal.chart_calendar, "hours", lambda d: (release.wait(5), None)[1])  # a calendar refresh hangs
    monkeypatch.setattr(cal.chart_calendar, "cached", lambda d: None)
    for name in ("live_filings", "live_halts"):
        monkeypatch.setattr(cat, name, lambda s: _ok([]))
    monkeypatch.setattr(cat, "live_headlines", lambda s, since: _ok([]))
    monkeypatch.setattr(cat, "_bars", lambda s, since, at: None)
    now = datetime(2026, 11, 27, 15, 0, tzinfo=ET)
    try:
        out = cat.live_catalysts("NBIS", now)
    finally:
        release.set()
    assert out["since"] == "11-26 21:00 ET" and set(out["sources"].values()) == {"ok"}  # the 18-hour fallback


def test_concurrent_misses_share_one_halts_read(monkeypatch):
    import threading
    cat._cache.clear()
    calls, gate = [], threading.Event()

    def get(url, headers):
        calls.append(url)
        gate.wait(2)
        return HALTS
    monkeypatch.setattr(cat, "_get_text", get)
    out = {}
    threads = [threading.Thread(target=lambda s=s: out.__setitem__(s, cat.live_halts(s))) for s in ("NBIS", "CRWV")]
    for t in threads:
        t.start()
    gate.set()
    for t in threads:
        t.join()
    assert len(calls) == 1 and out["NBIS"]["items"][0]["reason"] == "LUDP" and out["CRWV"]["items"][0]["reason"] == "T1"
    cat._cache.clear()


def test_a_failed_last_session_read_keeps_todays_bars(monkeypatch):
    from app.engine import chart_feed as feed
    today = [{"time": _at("2026-11-27T09:30:00"), "close": 100.0, "volume": 10}]

    def boom(*a, **k):
        raise RuntimeError("provider down")
    monkeypatch.setattr(feed.chart_feed, "read", boom)
    monkeypatch.setattr(feed.chart_feed, "today_minutes", lambda symbol, now: today)
    assert cat._bars("NBIS", _at("2026-11-26T16:00:00"), _at("2026-11-27T10:00:00")) == today


def test_after_the_bell_the_window_still_holds_todays_session():
    days = {date(2026, 11, 27): {"status": "open", "close": 13 * 60}, date(2026, 11, 26): {"status": "open", "close": 16 * 60}}
    # 17:00 after a 13:00 early close: the window opens at the session before, so today's session is in it.
    assert cat.last_close(_at("2026-11-27T17:00:00"), days.get) == _at("2026-11-26T16:00:00")
