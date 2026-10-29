"""Context attachment tests: no network."""

import json

from research.opening_lab import context


def _session(day="2026-07-15", prior="2026-07-14"):
    return {"date": day, "symbols": {"SPY": {"daily": [{"date": prior}]}}, "news": [], "macro": [], "provenance": {}}


def test_normalize_news_strips_html_truncates_and_utc():
    item = {"id": 7, "headline": "A &amp; B", "summary": "<p>" + "x" * 500 + "</p>",
            "symbols": ["SPY"], "source": "benzinga", "created_at": "2026-07-15T09:31:02-04:00"}
    out = context.normalize_news(item)
    assert out["id"] == "7" and out["headline"] == "A & B"
    assert len(out["summary"]) == 400 and "<" not in out["summary"]
    assert out["created_at"] == "2026-07-15T13:31:02Z"


def test_merge_dedupes_and_sorts():
    a = {"id": "1", "created_at": "2026-07-15T12:00:00Z"}
    b = {"id": "2", "created_at": "2026-07-15T11:00:00Z"}
    assert [i["id"] for i in context._merge([a, b, dict(a)])] == ["2", "1"]


def test_window_uses_prior_session_and_et():
    start, end = context._window("2026-07-15", "2026-07-14")
    assert start == "2026-07-14T20:00:00Z" and end == "2026-07-15T14:30:00Z"


def test_prior_date_prefers_daily_else_weekday():
    assert context._prior_date(_session(prior="2026-07-13")) == "2026-07-13"
    assert context._prior_date({"date": "2026-07-13", "symbols": {}}) == "2026-07-10"


def test_attach_uses_cache_only_without_fetch(tmp_path, monkeypatch):
    monkeypatch.setattr(context, "CACHE_DIR", tmp_path)
    (tmp_path / "2026-07-15.json").write_text(json.dumps(
        {"window": ["a", "b"], "fetched_at": "t", "capped": False,
         "items": [{"id": "1", "headline": "h", "summary": "", "symbols": [], "source": "s",
                    "created_at": "2026-07-15T12:00:00Z"}]}))
    monkeypatch.setattr(context, "fetch_news_day", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    s = _session()
    out = context.attach_context(s)
    assert len(out["news"]) == 1 and s["news"] == []
    assert out["provenance"]["context"]["news"]["status"] == "cache"


def test_attach_missing_cache_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(context, "CACHE_DIR", tmp_path)
    out = context.attach_context(_session())
    assert out["news"] == [] and out["provenance"]["context"]["news"]["status"] == "missing"


def test_attach_fetch_error_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(context, "CACHE_DIR", tmp_path)

    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(context, "fetch_news_day", boom)
    out = context.attach_context(_session(), fetch=True)
    ctx = out["provenance"]["context"]
    assert ctx["news"]["status"] == "error" and ctx["errors"]


def test_macro_events_utc_and_coverage(tmp_path):
    cal = {"covers_from": "2026-01-01", "covers_through": "2026-12-31",
           "events": [{"date": "2026-07-15", "time": "08:30", "kind": "cpi", "name": "CPI (Jun)"}]}
    p = tmp_path / "m.json"
    p.write_text(json.dumps(cal))
    events, cov = context.load_macro("2026-07-15", p)
    assert events == [{"kind": "cpi", "name": "CPI (Jun)", "scheduled_at": "2026-07-15T12:30:00Z"}]
    assert cov["status"] == "ok"
    events, cov = context.load_macro("2027-02-01", p)
    assert events == [] and cov["status"] == "outside_coverage"


def test_fetch_query_paginates_with_fake_client(monkeypatch):
    monkeypatch.setattr(context, "_throttle", lambda: None)
    pages = [{"news": [{"id": 1, "headline": "a", "created_at": "2026-07-15T12:00:00Z"}], "next_page_token": "t"},
             {"news": [{"id": 2, "headline": "b", "created_at": "2026-07-15T12:01:00Z"}], "next_page_token": None}]
    seen = []

    class Resp:
        status_code = 200
        def __init__(self, d): self.d = d
        def raise_for_status(self): pass
        def json(self): return self.d

    class Client:
        def get(self, url, params):
            seen.append(params)
            return Resp(pages[len(seen) - 1])

    items = context._fetch_query(Client(), "s", "e", "SPY,QQQ")
    assert [i["id"] for i in items] == ["1", "2"]
    assert seen[1]["page_token"] == "t" and seen[0]["sort"] == "desc" and seen[0]["symbols"] == "SPY,QQQ"
