"""Context attachment tests: no network."""

import json
from datetime import datetime, timezone

from research.opening_lab import context

UTC = timezone.utc


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
    assert start == "2026-07-14T20:00:00Z" and end == "2026-07-15T14:00:00Z"


def test_prior_date_prefers_daily_else_weekday():
    assert context._prior_date(_session(prior="2026-07-13")) == "2026-07-13"
    assert context._prior_date({"date": "2026-07-13", "symbols": {}}) == "2026-07-10"


def test_attach_uses_cache_only_without_fetch(tmp_path, monkeypatch):
    monkeypatch.setattr(context, "CACHE_DIR", tmp_path)
    (tmp_path / "2026-07-15.json").write_text(json.dumps(
        {"window": ["a", "b"], "fetched_at": "t", "incomplete": False,
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


class _Resp:
    status_code = 200

    def __init__(self, d):
        self.d = d

    def raise_for_status(self):
        pass

    def json(self):
        return self.d


class _Client:
    """Fake Alpaca: serves `articles` honoring start/end, 2 per page."""

    def close(self):
        pass

    def __init__(self, articles):
        self.articles, self.calls = articles, []

    def get(self, url, params):
        self.calls.append(params)
        rows = [a for a in self.articles if params["start"] <= a["created_at"] <= params["end"]]
        if params.get("symbols"):
            rows = [a for a in rows if set(a.get("symbols", [])) & {"SPY", "QQQ"}]
        pos = int(params.get("page_token") or 0)
        nxt = pos + 2 if pos + 2 < len(rows) else None
        return _Resp({"news": rows[pos:pos + 2], "next_page_token": str(nxt) if nxt else None})


def _art(i, ts, symbols=()):
    return {"id": i, "headline": f"h{i}", "created_at": ts, "symbols": list(symbols), "updated_at": ts}


EARLY = [_art(1, "2026-07-15T12:00:00Z"), _art(2, "2026-07-15T13:00:00Z"), _art(3, "2026-07-15T13:29:00Z")]
BURST = [_art(100 + k, "2026-07-15T13:31:00Z") for k in range(30)]
AFTER_1000 = datetime(2026, 7, 15, 15, 0, tzinfo=UTC)  # 11:00 ET


def test_paginates_oldest_first_and_keeps_updated_at(monkeypatch):
    monkeypatch.setattr(context, "_throttle", lambda: None)
    c = _Client(EARLY)
    items, ok = context._fetch_query(c, "2026-07-14T20:00:00Z", "2026-07-15T14:00:00Z", None)
    assert ok and [i["id"] for i in items] == ["1", "2", "3"]
    assert c.calls[0]["sort"] == "asc" and items[0]["updated_at"] == "2026-07-15T12:00:00Z"


def test_later_burst_does_not_change_early_items(tmp_path, monkeypatch):
    monkeypatch.setattr(context, "_throttle", lambda: None)
    monkeypatch.setattr(context, "CACHE_DIR", tmp_path)
    a = context.fetch_news_day("2026-07-15", "2026-07-14", _Client(EARLY), now=AFTER_1000, cache=False)
    b = context.fetch_news_day("2026-07-15", "2026-07-14", _Client(EARLY + BURST), now=AFTER_1000, cache=False)
    early = lambda p: [i["id"] for i in p["items"] if i["created_at"] <= "2026-07-15T13:30:00Z"]
    assert early(a) == early(b) == ["1", "2", "3"]


def test_refresh_never_writes_or_reads_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(context, "_throttle", lambda: None)
    monkeypatch.setattr(context, "CACHE_DIR", tmp_path)
    (tmp_path / "2026-07-15.json").write_text(json.dumps({"window": [], "items": [{"id": "stale"}]}))
    before = (tmp_path / "2026-07-15.json").read_text()
    monkeypatch.setattr(context, "_headers", lambda: {})
    monkeypatch.setattr(context.httpx, "Client", lambda **k: _Client(EARLY))
    out = context.attach_context(_session(), refresh=True)
    assert [n["id"] for n in out["news"]] == ["1", "2", "3"]
    assert out["provenance"]["context"]["news"]["status"] == "refreshed"
    assert (tmp_path / "2026-07-15.json").read_text() == before


def test_partial_window_not_cached_full_window_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(context, "_throttle", lambda: None)
    monkeypatch.setattr(context, "CACHE_DIR", tmp_path)
    early_now = datetime(2026, 7, 15, 13, 30, 5, tzinfo=UTC)  # 09:30:05 ET
    p = context.fetch_news_day("2026-07-15", "2026-07-14", _Client(EARLY), now=early_now)
    assert p["full_window"] is False and not list(tmp_path.glob("*.json"))
    p = context.fetch_news_day("2026-07-15", "2026-07-14", _Client(EARLY), now=AFTER_1000)
    assert p["full_window"] is True and (tmp_path / "2026-07-15.json").exists()


def test_safety_cap_marks_incomplete_and_skips_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(context, "_throttle", lambda: None)
    monkeypatch.setattr(context, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(context, "SAFETY_CAP", 4)
    p = context.fetch_news_day("2026-07-15", "2026-07-14", _Client(EARLY + BURST), now=AFTER_1000)
    assert p["incomplete"] is True and not list(tmp_path.glob("*.json"))
