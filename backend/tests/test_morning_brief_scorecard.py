"""Invented briefs and bars only; no production, credentials or network."""
from datetime import timedelta
from decimal import Decimal
import json
import shlex
from types import SimpleNamespace

import pytest

from scripts import morning_brief_scorecard as scorer

DAY = "2026-11-02"  # standard time; the week before uses daylight time


def bar(clock, opening=100, close=100, day=DAY):
    return dict(t=scorer.at(day, clock).isoformat(), o=opening, c=close)


@pytest.fixture
def brief():
    return dict(day=DAY, saved_at="2026-11-02T14:00:00Z", redacted=False,
                body=dict(summary="Watch MU and $ABCD. QQQ is backdrop.", items=[dict(symbol="MU", what_changed="Revenue guidance raised",
                          evidence_ids=["headline-1"])], opportunities=[], urgent_positions=[], limitations=[]),
                evidence=[dict(id="market-QQQ", text="QQQ", observed_at=None),
                          dict(id="headline-1", text="MU — Revenue guidance raised", observed_at="2026-11-02T13:30:00Z")])


def test_exact_threshold_signed_spy_subtraction_and_missing():
    spy = [bar("09:30"), bar("10:29", close=102), bar("15:59", close=99)]
    stock = [bar("09:30"), bar("10:29", close=105), bar("15:59", close=96)]
    assert scorer.excess(stock, spy, DAY, "10:30") == Decimal("3")
    assert scorer.excess(stock, spy, DAY, "16:00") == Decimal("-3")
    assert scorer.ratio({"MU": [Decimal(3), Decimal(-3)], "NO": [None, None]}, 0) == "1/1"
    assert scorer.excess(stock[:-1], spy, DAY, "16:00") is None
    assert scorer.excess(stock, [], DAY, "10:30") is None
    # A 10:30 bar belongs to the next hour; never substitute it for 10:29.
    assert scorer.excess([bar("09:30"), bar("10:30", close=110)], spy, DAY, "10:30") is None


def test_dst_and_early_close():
    assert scorer.at("2026-10-30", "09:30").utcoffset() == timedelta(hours=-4)
    assert scorer.at(DAY, "09:30").utcoffset() == timedelta(hours=-5)
    rows = [bar("09:30"), bar("12:59", close=104)]
    assert scorer.excess(rows, [bar("09:30"), bar("12:59")], DAY, "13:00") == 4


def test_duplicate_and_invalid_prices_refused():
    with pytest.raises(ValueError, match="Duplicate"):
        scorer.excess([bar("09:30"), bar("09:30")], [], DAY, "10:30")
    with pytest.raises(ValueError, match="Invalid price"):
        scorer.excess([bar("09:30", opening=0), bar("10:29")], [], DAY, "10:30")


def test_mentions(brief):
    assert scorer.mentions(brief) == ["ABCD", "MU", "QQQ"]


@pytest.mark.parametrize("stock_open,stock_close,spy_open,spy_close", [(75, 76, 300, 295), (34, 34.02, 680, 660)])
def test_exact_repeating_division_threshold(stock_open, stock_close, spy_open, spy_close):
    stock = [bar("09:30", opening=stock_open), bar("10:29", close=stock_close)]
    spy = [bar("09:30", opening=spy_open), bar("10:29", close=spy_close)]
    positive = scorer.excess(stock, spy, DAY, "10:30")
    negative = scorer.excess(spy, stock, DAY, "10:30")
    assert positive == 3 and negative == -3
    assert scorer.ratio({"UP": [positive], "DOWN": [negative]}, 0) == "2/2"
    stock[1]["c"] = Decimal(str(stock_close)) - Decimal("0.00000001")
    below = scorer.excess(stock, spy, DAY, "10:30")
    assert scorer.ratio({"BELOW": [below], "NEG": [-below]}, 0) == "0/2"


def test_all_versions_late_excluded_and_report_private(brief, tmp_path):
    class FixtureMinutes:
        errors = {}
        def load(self, day, symbols):
            return {s: [bar("09:30"), bar("10:29", close=104 if s == "MU" else 100), bar("15:59")]
                    for s in symbols}
    late = dict(brief, saved_at="2026-11-02T15:00:00Z")
    results = scorer.score([brief, late], FixtureMinutes(), {DAY: "16:00"}, {})
    assert [r["eligible"] for r in results] == [True, False]
    text = scorer.render_week(DAY, results, {DAY: "16:00", "2026-11-03": "16:00"}, DAY, "2026-11-03")
    assert "2 saved versions; 1 available" in text
    assert "first hour 1/3" in text
    assert "2026-11-03" in text and "Archived whole-market" in text
    assert "MU" not in text and "Revenue" not in text and "ABCD" not in text
    assert "+4.00" not in text and "ticker slots" not in text
    output = tmp_path / "report.md"
    scorer.append_weeks(output, results, {DAY: "16:00"}, DAY, "2026-11-03")
    first = output.read_text()
    scorer.append_weeks(output, results, {DAY: "16:00"}, DAY, "2026-11-03")
    assert output.read_text() == first
    scorer.append_weeks(output, results, {DAY: "16:00"}, DAY, "2026-11-06")
    assert output.read_text().startswith(first.rstrip())
    with pytest.raises(ValueError, match="already exists"):
        scorer.append_weeks(output, [], {DAY: "16:00"}, DAY, "2026-11-03")


def test_paginated_sip_only_private_writes(tmp_path, monkeypatch):
    import httpx
    calls = []
    responses = [dict(bars={"MU": [bar("09:30")]}, next_page_token="next"),
                 dict(bars={"MU": [bar("10:29", close=103)]}, next_page_token=None)]
    def get(url, *, headers, params, timeout):
        calls.append((url, dict(params)))
        return SimpleNamespace(status_code=200, json=lambda: responses.pop(0))
    monkeypatch.setattr(httpx, "get", get)
    credentials = tmp_path / "fixture.env"
    credentials.write_text("ALPACA_API_KEY=invented\nALPACA_API_SECRET=invented\n")
    reader = scorer.Minutes(tmp_path / "private", credentials=credentials)
    assert len(reader.load(DAY, ["MU"])["MU"]) == 2
    assert all(p["feed"] == "sip" and p["adjustment"] == "raw" for _, p in calls)
    assert calls[1][1]["page_token"] == "next"
    assert reader.load(DAY, ["MU"]) and len(calls) == 2
    assert not (tmp_path / "private" / "database").exists()


def test_403_no_fallback_and_no_empty_cache(tmp_path, monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "get", lambda *a, **k: SimpleNamespace(status_code=403))
    credentials = tmp_path / "fixture.env"
    credentials.write_text("ALPACA_API_KEY=invented\nALPACA_API_SECRET=invented\n")
    reader = scorer.Minutes(tmp_path / "private", credentials=credentials)
    report = tmp_path / "report.md"
    report.write_text("Earlier week remains exactly intact.\n")
    prior = report.read_bytes()
    with pytest.raises(RuntimeError, match="SIP HTTP 403"):
        scorer.score([dict(day=DAY, saved_at=scorer.at(DAY, "09:00").isoformat(), body={"summary": "$MU"})],
                     reader, {DAY: "16:00"}, {})
        scorer.append_weeks(report, [], {DAY: "16:00"}, DAY, DAY)
    assert report.read_bytes() == prior
    assert "403" in reader.errors[DAY]
    assert list(reader.root.iterdir()) == []


def test_read_only_sql_and_hash_bound_manual_review(monkeypatch, brief):
    def run(command, **kwargs):
        remote = shlex.split(command[-1])
        query = remote[-1]
        assert "BEGIN READ ONLY;" in query and "SELECT" in query and "COMMIT;" in query
        assert all(word not in query for word in ("UPDATE ", "DELETE ", "INSERT ", "CREATE "))
        return SimpleNamespace(stdout=json.dumps(brief))
    monkeypatch.setattr(scorer.subprocess, "run", run)
    assert scorer.read_briefs("existing-host", DAY, DAY) == [brief]
    old = scorer.brief_key(brief)
    brief["body"]["summary"] += " updated"
    assert scorer.brief_key(brief) != old


def test_untrusted_baseline_refused(brief, tmp_path):
    baseline = dict(feed="iex", whole_market=True, as_of=scorer.at(DAY, "09:00").isoformat(), gainers=[], losers=[])
    with pytest.raises(ValueError, match="baseline"):
        scorer.score([brief], scorer.Minutes(tmp_path), {DAY: "16:00"}, {DAY: baseline})


def test_reconstructed_baseline_supplement_is_private_append_only(brief, tmp_path):
    baseline = dict(feed="sip", whole_market=True, as_of=scorer.at(DAY, "09:00").isoformat(),
                    source="reconstructed-sip", ranking_basis="pct_vs_prior_regular_close",
                    gainers=["G" + chr(65+i) for i in range(10)], losers=["L" + chr(65+i) for i in range(10)])
    results = scorer.score([brief], scorer.Minutes(tmp_path), {DAY: "16:00"}, {DAY: baseline})
    output = tmp_path / "report.md"
    output.write_text("Original weekly evidence.\n")
    scorer.append_baselines(output, results, DAY, DAY)
    first = output.read_text()
    assert first.startswith("Original weekly evidence.\n") and "| reconstructed-sip |" in first
    assert baseline["gainers"][0] not in first and "Revenue" not in first
    assert "(reconstructed-sip)" in scorer.render_week(DAY, results, {DAY: "16:00"}, DAY, DAY)
    scorer.append_baselines(output, results, DAY, DAY)
    assert output.read_text() == first
    results[0]["overlap"] = 1
    with pytest.raises(ValueError, match="different evidence"):
        scorer.append_baselines(output, results, DAY, DAY)
