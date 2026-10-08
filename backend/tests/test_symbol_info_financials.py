"""SEC EDGAR financials (T3.2): the normalizer on recorded NVDA and NBIS payloads, and the cached feed."""

import json
from pathlib import Path

import pytest

from app.engine import symbol_info_financials as module
from app.engine.symbol_info_financials import normalize
from app.engine.symbol_info_financials_feed import FILING_DUE_DAYS, NotFound, ProviderError, SymbolFinancials, expires_at

FIXTURES = Path(__file__).parent / "fixtures" / "sec"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


NVDA = load("nvda_companyfacts_2026-10-08.json")
NBIS = load("nbis_companyfacts_2026-10-08.json")
TICKERS = load("company_tickers_2026-10-08.json")


def raw(tag: str, start: str, end: str, form: str = "10-Q", unit: str = "USD") -> list[dict]:
    return [r for r in NVDA["facts"]["us-gaap"][tag]["units"][unit] if r["start"] == start and r["end"] == end and r["form"] == form]


def test_nvda_selects_the_last_eight_quarter_slots_with_q4_gaps():
    out = normalize(NVDA)
    rows = out["quarters"]
    assert len(rows) == 8 and out["latest_end"] == "2026-07-26"
    assert [r["end"] for r in rows if not r["gap"]] == ["2024-10-27", "2025-04-27", "2025-07-27", "2025-10-26", "2026-04-26", "2026-07-26"]
    gaps = [r for r in rows if r["gap"]]
    assert [(g["fiscal_year"], g["fiscal_period"]) for g in gaps] == [(2025, "Q4"), (2026, "Q4")]
    for gap in gaps:  # never derived from the annual figure: every value is null, not 0
        assert all(gap[k] is None for k in ("revenue", "gross_profit", "operating_income", "net_income", "eps_diluted", "gross_margin", "operating_margin", "revenue_yoy"))
    assert [r["end"] for r in rows] == sorted(r["end"] for r in rows)


def test_year_to_date_spans_are_never_a_quarter():
    out = normalize(NVDA)
    assert 177837000000 not in {r["revenue"] for r in out["quarters"]}  # the 6-month fact ending 2026-07-26
    assert 91166000000 not in {r["revenue"] for r in out["quarters"]}  # the 9-month fact ending 2024-10-27
    latest = out["quarters"][-1]
    assert latest["start"] == "2026-04-27" and latest["revenue"] == 96221000000


def test_margins_are_calculated_from_revenue_and_profit_not_read():
    latest = normalize(NVDA)["quarters"][-1]
    revenue = raw("Revenues", "2026-04-27", "2026-07-26")[-1]["val"]
    gross = raw("GrossProfit", "2026-04-27", "2026-07-26")[-1]["val"]
    operating = raw("OperatingIncomeLoss", "2026-04-27", "2026-07-26")[-1]["val"]
    assert latest["gross_margin"] == gross / revenue and latest["operating_margin"] == operating / revenue
    assert "GrossMargin" not in NVDA["facts"]["us-gaap"]  # nothing in the payload to read
    assert 0.4 < latest["operating_margin"] < latest["gross_margin"] < 1


def test_comparatives_take_the_latest_value_and_the_earliest_label():
    rows = {r["end"]: r for r in normalize(NVDA)["quarters"] if not r["gap"]}
    # Q2 FY26 (ended 2025-07-27) was first filed 2025-08-27 as FY2026 Q2, and repeated in the next year's 10-Q as FY2027 Q2.
    q2 = rows["2025-07-27"]
    assert (q2["fiscal_year"], q2["fiscal_period"], q2["filed"]) == (2026, "Q2", "2025-08-27")
    # The 2024 EPS was restated for the 10-for-1 split in a later 10-Q: the latest filing's value wins.
    q3 = rows["2024-10-27"]
    expected = max(raw("EarningsPerShareDiluted", "2024-07-29", "2024-10-27", unit="USD/shares"), key=lambda r: r["filed"])["val"]
    assert q3["eps_diluted"] == expected


def test_year_over_year_is_the_same_quarter_a_year_earlier_or_null():
    rows = {r["end"]: r for r in normalize(NVDA)["quarters"] if not r["gap"]}
    assert rows["2026-07-26"]["revenue_yoy"] == pytest.approx((96221000000 - 46743000000) / 46743000000)
    assert rows["2025-07-27"]["revenue_yoy"] == pytest.approx((46743000000 - 30040000000) / 30040000000)
    assert rows["2025-10-26"]["revenue_yoy"] == pytest.approx((57006000000 - 35082000000) / 35082000000)
    # Q1 FY26 (2025-04-27) compares with Q1 FY25, which is in the payload; the 2026-04-26 quarter likewise.
    assert rows["2026-04-26"]["revenue_yoy"] == pytest.approx((81615000000 - 44062000000) / 44062000000)
    # No quarter ended a year before 2024-10-27 is shown or needed; its comparison comes from the full history.
    assert rows["2024-10-27"]["revenue_yoy"] is not None


def test_missing_prior_year_leaves_growth_null_and_missing_fields_stay_null():
    doc = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
        {"start": "2025-01-01", "end": "2025-03-31", "val": 100, "accn": "a", "fy": 2025, "fp": "Q1", "form": "10-Q", "filed": "2025-05-01"}]}}}}}
    (row,) = normalize(doc)["quarters"]
    assert row["revenue"] == 100 and row["revenue_yoy"] is None
    assert row["gross_profit"] is None and row["gross_margin"] is None and row["operating_margin"] is None and row["net_income"] is None


def test_other_revenue_tags_are_used_and_annual_only_filers_have_no_quarters():
    doc = {"facts": {"us-gaap": {"RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
        {"start": "2025-01-01", "end": "2025-03-31", "val": 7, "accn": "a", "fy": 2025, "fp": "Q1", "form": "10-Q", "filed": "2025-05-01"}]}}}}}
    assert normalize(doc)["quarters"][0]["revenue"] == 7
    assert not module.has_quarterly_facts(NBIS) and module.has_quarterly_facts(NVDA)


# ---- the feed ----

class Clock:
    def __init__(self, now: float = 1_791_000_000.0):  # 2026-10-03
        self.now = now

    def __call__(self):
        return self.now


class Sec:
    def __init__(self, facts: dict[int, object] | None = None):
        self.calls: list[str] = []
        self.facts = facts if facts is not None else {1045810: NVDA, 1513845: NBIS}
        self.fail: str | None = None
        self.tickers_fail: str | None = None

    def facts_calls(self) -> int:
        return sum("companyfacts" in url for url in self.calls)

    def __call__(self, url: str):
        self.calls.append(url)
        if url.endswith("company_tickers.json"):
            if self.tickers_fail:
                raise ProviderError(self.tickers_fail)
            return TICKERS
        if self.fail:
            raise ProviderError(self.fail)
        cik = int(url.rsplit("CIK", 1)[1].split(".")[0])
        if cik not in self.facts:
            raise NotFound(url)
        return self.facts[cik]


def feed(tmp_path, sec=None, clock=None):
    return SymbolFinancials(tmp_path, clock or Clock(), sec or Sec())


def test_nvda_renders_through_the_feed_and_the_cache_holds_only_the_normalized_quarters(tmp_path):
    sec = Sec()
    view = feed(tmp_path, sec).view("NVDA")
    assert view["state"] == "ready" and view["source"] == "SEC EDGAR" and view["stale"] is False and len(view["quarters"]) == 8
    cached = (tmp_path / "NVDA.json").read_text()
    assert len(cached) < 20_000 and "facts" not in cached  # never the raw payload
    again = feed(tmp_path, sec, Clock(1_791_000_000.0 + 3600)).view("NVDA")  # a new process reads the disk copy
    assert again["quarters"] == view["quarters"]
    assert sum(url.endswith("company_tickers.json") for url in sec.calls) == 1 and sec.facts_calls() == 1


def test_nbis_files_only_20f_and_says_so(tmp_path):
    view = feed(tmp_path).view("NBIS")
    assert view["state"] == "none" and view["message"] == "No quarterly SEC financials for this issuer." and view["quarters"] == []


def test_unknown_ticker_and_missing_facts_are_not_available_for_funds(tmp_path):
    sec = Sec()
    assert feed(tmp_path, sec).view("SPY")["message"] == "Not available for ETFs or funds."
    assert not any("companyfacts" in url for url in sec.calls)  # not in the ticker map: no facts call
    only_tickers = Sec(facts={})
    view = feed(tmp_path / "b", only_tickers).view("AAPL")  # in the map, 404 on companyfacts
    assert view["state"] == "none" and view["message"] == "Not available for ETFs or funds."


def test_share_class_symbols_map_to_sec_dashes(tmp_path):
    sec = Sec(facts={1067983: NBIS})
    assert feed(tmp_path, sec).view("BRK.B")["state"] == "none"
    assert any("CIK0001067983" in url for url in sec.calls)


def test_freshness_waits_for_the_next_filing_then_checks_daily(tmp_path):
    clock, sec = Clock(1_791_000_000.0), Sec()
    f = feed(tmp_path, sec, clock)
    f.view("NVDA")
    latest = 1_785_024_000.0  # 2026-07-26T00:00Z
    due = latest + FILING_DUE_DAYS * 86400
    entry = {"latest_end": "2026-07-26"}
    assert expires_at(entry, clock.now) == due
    clock.now += 86400 * 20  # before the next filing is due: no new request
    f.view("NVDA")
    assert sec.facts_calls() == 1
    clock.now = due + 10
    f.view("NVDA")
    assert sec.facts_calls() == 2  # due: reads again
    f.view("NVDA")
    assert sec.facts_calls() == 2
    clock.now += 86400 + 10  # past due, so daily
    f.view("NVDA")
    assert sec.facts_calls() == 3


def test_failure_serves_the_cache_with_its_age_and_stays_quiet_for_five_minutes(tmp_path):
    clock, sec = Clock(1_791_000_000.0), Sec()
    f = feed(tmp_path, sec, clock)
    first = f.view("NVDA")
    clock.now = 1_785_024_000.0 + 117 * 86400  # due
    sec.fail = "SEC EDGAR answered 503."
    calls = sec.facts_calls()
    view = f.view("NVDA")
    assert view["stale"] is True and view["quarters"] == first["quarters"]
    assert "SEC EDGAR answered 503." in view["message"] and "Showing the cached copy from" in view["message"] and "days ago" in view["message"]
    assert sec.facts_calls() == calls + 1
    clock.now += 120
    assert f.view("NVDA")["stale"] is True and sec.facts_calls() == calls + 1  # quiet
    clock.now += 400
    sec.fail = None
    recovered = f.view("NVDA")
    assert recovered["stale"] is False and sec.facts_calls() == calls + 2


def test_no_cache_and_a_failure_is_unavailable_and_a_403_names_the_user_agent(tmp_path):
    sec = Sec()
    sec.tickers_fail = "SEC refused the request. Set SEC_USER_AGENT on the server to a name and contact email."
    view = feed(tmp_path, sec).view("NVDA")
    assert view["state"] == "unavailable" and "SEC_USER_AGENT" in view["message"] and view["quarters"] == []
