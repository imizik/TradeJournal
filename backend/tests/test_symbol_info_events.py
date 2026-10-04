"""Events tab (T1.4) and chart earnings (C2.5): normalizers on recorded Tradier
responses, the cache and budget around them, and both routes.

`fixtures/tradier/fundamentals_2026-10-04.json` holds production responses,
trimmed; its `_note` says how.
"""

from datetime import date
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from app.engine import symbol_info_tradier as module
from app.engine.symbol_info_events import (dividends_view, earnings_view, parse_dividends, parse_earnings, parse_splits,
                                           report_dates, splits_view)
from app.engine.symbol_info_tradier import SymbolEvents
from app.routers import symbol_info

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "tradier" / "fundamentals_2026-10-04.json").read_text())
TODAY = date(2026, 10, 4)


def test_a_confirmed_row_wins_over_an_estimate_for_the_same_quarter():
    rows = parse_earnings(FIXTURE["calendars"])["CVNA"]
    assert {(r["date"], r["status"]) for r in rows if (r["fiscal_year"], r["fiscal_quarter"]) == (2026, 3)} == {
        ("2026-10-28", "confirmed"), ("2026-10-29", "estimated")}
    assert earnings_view(rows, TODAY)["next"] == {"date": "2026-10-28", "status": "confirmed", "label": "Q3 FY2026"}
    # The day after, the leftover estimate is not a second Q3 report; the next one is Q4's estimate.
    view = earnings_view(rows, date(2026, 10, 29))
    assert view["next"] == {"date": "2027-02-18", "status": "estimated", "label": "Q4 FY2026"}
    assert view["reports"][0] == {"date": "2026-10-28", "label": "Q3 FY2026"}


def test_estimated_dates_stay_labelled_and_reports_are_confirmed_results_only():
    rows = parse_earnings(FIXTURE["calendars"])["NVDA"]
    view = earnings_view(rows, TODAY)
    # NVDA's fiscal year runs ahead of the calendar year; the label is Tradier's own.
    assert view["next"] == {"date": "2026-11-19", "status": "estimated", "label": "Q3 FY2027"}
    assert [r["date"] for r in view["reports"]] == ["2026-08-26", "2026-05-20", "2026-02-25", "2025-11-19",
                                                   "2025-08-27", "2025-05-28", "2025-02-26", "2024-11-20"]
    # Conference calls, meetings and conferences share the calendar but are not reports.
    raw = [r for item in FIXTURE["calendars"] if item["request"] == "NVDA" for result in item["results"]
           for r in result["tables"]["corporate_calendars"] or []]
    assert len(rows) == sum(r["event_type"] in (7, 8, 9, 10) for r in raw) < len(raw)
    assert len(earnings_view(rows, TODAY, reports=None)["reports"]) > 8


def test_an_unknown_date_is_none_and_an_etf_has_no_calendar():
    calendars = parse_earnings(FIXTURE["calendars"])
    assert calendars["SPY"] == []
    assert earnings_view(calendars["SPY"], TODAY) == {"next": None, "reports": []}
    # Past the last row Tradier lists: nothing is projected from earlier quarters.
    assert earnings_view(calendars["CVNA"], date(2028, 1, 1))["next"] is None
    # An estimate whose day passed without confirmation was never a report.
    stale = [{"date": "2026-07-01", "status": "estimated", "fiscal_year": 2026, "fiscal_quarter": 2, "event": ""}]
    assert earnings_view(stale, TODAY) == {"next": None, "reports": []}


def test_rows_come_from_one_share_class_and_are_never_merged():
    row = {"begin_date_time": "2026-11-05", "event_type": 9, "event_status": "Confirmed", "event_fiscal_year": 2026, "event": "Q3"}
    other = {**row, "begin_date_time": "2026-11-06"}
    payload = [{"request": "abc", "results": [
        {"id": "secondary", "tables": {"corporate_calendars": other}},
        {"id": "primary", "tables": {"corporate_calendars": [row, {**row, "event_type": 14}, {**row, "event_type": 8, "begin_date_time": "2026-08-05"}]}},
    ]}]
    rows = parse_earnings(payload)["ABC"]
    assert [r["date"] for r in rows] == ["2026-08-05", "2026-11-05"]
    # A 1970 placeholder, a missing status or an unknown type is dropped, not guessed.
    junk = [{**row, "begin_date_time": "1970-01-01"}, {**row, "event_status": None}, {**row, "event_type": "x"}]
    assert parse_earnings([{"request": "ABC", "results": [{"tables": {"corporate_calendars": junk}}]}])["ABC"] == []
    with pytest.raises(ValueError):
        parse_earnings({"fault": "denied"})


def test_ties_inside_a_quarter_take_the_earliest_date():
    rows = [{"date": d, "status": s, "fiscal_year": 2026, "fiscal_quarter": 3, "event": ""}
            for d, s in [("2026-10-30", "estimated"), ("2026-10-29", "estimated")]]
    assert [r["date"] for r in report_dates(rows)] == ["2026-10-29"]


def test_dividends_next_and_last_from_every_table_shape():
    dividends = parse_dividends(FIXTURE["dividends"])
    nvda = dividends_view(dividends["NVDA"], TODAY)
    assert nvda["next"] is None  # none declared after September's
    assert (nvda["last"]["ex_date"], nvda["last"]["amount"], nvda["last"]["pay_date"]) == ("2026-09-10", 0.25, "2026-10-01")
    assert dividends_view(dividends["NVDA"], date(2026, 9, 1))["next"]["ex_date"] == "2026-09-10"
    assert dividends["SPY"][0]["ex_date"] == "2026-09-18"  # an ETF still pays
    assert dividends["CVNA"] == []
    # AMD's only row comes back as a bare object, not a list.
    assert [(r["ex_date"], r["type"]) for r in dividends["AMD"]] == [("1995-04-27", "SC")]


def test_splits_in_the_last_two_years():
    splits = parse_splits(FIXTURE["corporate_actions"])
    assert splits_view(splits["CVNA"], TODAY) == [{"ex_date": "2026-05-08", "from": 1.0, "to": 5.0, "label": "5-for-1"}]
    assert splits_view(splits["NVDA"], TODAY) == []  # June 2024 is more than two years back
    assert [r["label"] for r in splits_view(splits["NVDA"], date(2026, 6, 1))] == ["10-for-1"]
    assert splits["SPY"] == []


# --------------------------------------------------------------------- store

@pytest.fixture
def tradier(monkeypatch):
    """Answers each batched request with the fixture's rows for the symbols asked."""
    calls: list[tuple[str, str]] = []
    status = [200]

    def get(url, params=None, **_):
        dataset = url.rsplit("/", 1)[-1]
        calls.append((dataset, params["symbols"]))
        asked = params["symbols"].split(",")
        body = [item for item in FIXTURE[dataset] if item["request"] in asked]
        return httpx.Response(status[0], json=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(module.tradier, "TRADIER_API_KEY", "test-secret")
    monkeypatch.setattr(module.httpx, "get", get)
    return calls, status


def store(tmp_path, clock):
    queued = []
    events = SymbolEvents(root=tmp_path, clock=lambda: clock[0], spawn=queued.append)
    return events, queued


def test_the_chart_never_waits_and_one_batched_call_covers_the_watchlist(tmp_path, tradier):
    calls, _ = tradier
    clock = [1_000_000.0]
    events, queued = store(tmp_path, clock)
    first = events.chart_earnings(["CVNA"], ["NVDA", "CVNA", "SPY"], TODAY)
    assert first["CVNA"]["state"] == "loading" and first["CVNA"]["next"] is None and not calls
    assert len(queued) == 1
    events.chart_earnings(["NVDA"], ["CVNA"], TODAY)
    assert len(queued) == 1  # one refresh at a time
    queued.pop()()
    assert calls == [("calendars", "CVNA,NVDA,SPY")]
    ready = events.chart_earnings(["CVNA", "SPY"], ["NVDA"], TODAY)
    assert ready["CVNA"]["state"] == "ready" and ready["CVNA"]["next"]["date"] == "2026-10-28"
    assert len(ready["CVNA"]["reports"]) > 8  # every past report, for markers on older candles
    assert ready["SPY"]["state"] == "none" and ready["SPY"]["source"] == "Tradier corporate calendar"
    assert not queued
    # Half a day later the calendar is read again; a restart reads the disk copy instead.
    clock[0] += 12 * 3600
    events.chart_earnings(["CVNA"], [], TODAY)
    assert len(queued) == 1
    restarted, queued_again = store(tmp_path, [1_000_000.0 + 3600])
    assert restarted.chart_earnings(["NVDA"], ["CVNA"], TODAY)["NVDA"]["next"]["status"] == "estimated"
    assert not queued_again and len(calls) == 1


def test_a_failed_read_cools_down_and_keeps_the_older_copy(tmp_path, tradier):
    calls, status = tradier
    clock = [1_000_000.0]
    events, _ = store(tmp_path, clock)
    status[0] = 500
    assert events.refresh("calendars", ["CVNA"]) == "Tradier could not read the corporate calendar (500)."
    blocked = events.chart_earnings(["CVNA"], [], TODAY)["CVNA"]
    assert blocked["state"] == "unavailable" and "500" in blocked["message"]
    assert events.refresh("calendars", ["CVNA"]) and len(calls) == 1  # cooling down: no second call
    status[0] = 200
    clock[0] += 61
    assert events.refresh("calendars", ["CVNA"]) is None
    clock[0] += 12 * 3600
    status[0] = 403
    assert "refused" in events.refresh("calendars", ["CVNA"])
    older = events.chart_earnings(["CVNA"], [], TODAY)["CVNA"]
    assert older["state"] == "ready" and older["fetched_at"] == 1_000_061 and "refused" in older["message"]


def test_reads_stay_within_ten_a_minute(tmp_path, tradier):
    calls, _ = tradier
    clock = [1_000_000.0]
    events, _ = store(tmp_path, clock)
    for index in range(10):
        assert events.refresh("dividends", [f"X{index}"]) is None
    assert "pacing" in events.refresh("dividends", ["X10"])
    assert len(calls) == 10


def test_missing_key_reads_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(module.tradier, "TRADIER_API_KEY", "")
    monkeypatch.setattr(module.httpx, "get", lambda *a, **k: pytest.fail("no key, no request"))
    events, queued = store(tmp_path, [1_000_000.0])
    result = events.chart_earnings(["CVNA"], ["NVDA"], TODAY)["CVNA"]
    assert result["state"] == "unavailable" and "TRADIER_API_KEY" in result["message"] and not queued


def test_events_route_reads_each_dataset_once_and_degrades_by_block(tmp_path, tradier, monkeypatch):
    calls, status = tradier
    monkeypatch.setattr(module, "symbol_events", SymbolEvents(root=tmp_path, spawn=lambda work: None))
    app = FastAPI()
    app.include_router(symbol_info.router, prefix="/charts")
    with TestClient(app) as client:
        data = client.get("/charts/symbol/cvna/events").json()
        assert [c[0] for c in calls] == ["calendars", "dividends", "corporate_actions"]
        assert data["symbol"] == "CVNA" and data["time_zone"] == "America/New_York"
        earnings = data["earnings"]
        assert earnings["state"] == "ready" and earnings["time_note"].startswith("Time of day not published")
        assert len(earnings["reports"]) <= 8 and all(r["date"] < data["today"] for r in earnings["reports"])
        assert data["dividends"]["state"] == "none" and data["dividends"]["last"] is None
        assert data["splits"]["state"] == "ready" and data["splits"]["source"] == "Tradier corporate actions"
        client.get("/charts/symbol/CVNA/events")
        assert len(calls) == 3  # cached
        # SPY: no calendar, but dividends; a failing dataset degrades only its own block.
        status[0] = 503
        spy = client.get("/charts/symbol/SPY/events").json()
        assert spy["earnings"]["state"] == "unavailable" and "503" in spy["earnings"]["message"]
        assert spy["dividends"]["state"] == "unavailable" and spy["splits"]["state"] == "unavailable"
        assert client.get("/charts/symbol/CVNA/events").json()["earnings"]["state"] == "ready"
        assert client.get("/charts/symbol/..%2Fx/events").status_code in (404, 422)
