"""Insider buying and selling (T3.3), on rows recorded from Yahoo on 2026-10-08."""

from datetime import date
import json
from pathlib import Path

import pandas as pd

from app.engine.symbol_info_insiders import ProviderError, SymbolInsiders, classify, normalize, summarize

RECORDED = json.loads((Path(__file__).parent / "fixtures" / "yahoo" / "insider_transactions_2026-10-08.json").read_text())["symbols"]
TODAY = date(2026, 10, 8)
SINCE = "2026-07-10"  # 90 days before TODAY


def frame(symbol: str) -> pd.DataFrame:
    """The recorded rows as yfinance returns them: a DataFrame with a datetime Start Date."""
    out = pd.DataFrame(RECORDED[symbol])
    out["Start Date"] = pd.to_datetime(out["Start Date"])
    return out


def inside(symbol: str, kind: str) -> list[dict]:
    return [r for r in RECORDED[symbol] if r["Start Date"][:10] >= SINCE and r["Text"].startswith(kind)]


def test_classification_counts_only_open_market_purchases_and_sales():
    assert classify("Sale at price 222.19 - 223.75 per share.") == "sell"
    assert classify("Purchase at price 256.31 per share.") == "buy"
    for text in ("Stock Award(Grant) at price 0.00 per share.", "Stock Gift at price 0.00 per share.",
                 "Conversion of Exercise of derivative security at price 23.34 per share.", "", None):
        assert classify(text) == "other"


def test_nvda_window_counts_sales_and_excludes_awards_and_gifts():
    summary = summarize(normalize(frame("NVDA"), TODAY), TODAY)
    sales = inside("NVDA", "Sale")
    assert summary["since"] == SINCE and summary["buys"]["count"] == 0
    assert summary["sells"]["count"] == len(sales) > 0 and summary["sells"]["shares"] == sum(r["Shares"] for r in sales)
    assert summary["net_shares"] == -summary["sells"]["shares"]
    assert summary["net_value"] == -sum(r["Value"] for r in sales)
    others = [r for r in RECORDED["NVDA"] if r["Start Date"][:10] >= SINCE and not r["Text"].startswith("Sale")]
    assert summary["excluded"] == len(others) > 0  # the 500,000-share gifts and the director awards
    assert summary["latest"][0] == {"date": "2026-09-21", "insider": "TETER TIMOTHY S", "position": "General Counsel",
                                    "kind": "sell", "shares": 30460.0, "value": 6786533.0}
    assert len(summary["latest"]) == 5 and all(r["kind"] == "sell" for r in summary["latest"])
    assert [r["date"] for r in summary["latest"]] == sorted((r["date"] for r in summary["latest"]), reverse=True)


def test_nbis_blank_text_row_is_not_a_sale():
    rows = normalize(frame("NBIS"), TODAY)
    blank = [r for r in rows if r["value"] is None and r["insider"] == "BORODITSKY MARC"]
    assert len(blank) == 1 and blank[0]["kind"] == "other"
    summary = summarize(rows, TODAY)
    sales = inside("NBIS", "Sale")
    assert summary["sells"]["count"] == len(sales) > 0 and summary["sells"]["shares"] == sum(r["Shares"] for r in sales)
    assert summary["net_value"] == -sum(r["Value"] for r in sales)  # every counted row has a value


def test_net_value_is_blank_when_a_counted_row_has_no_value():
    rows = normalize([{"Start Date": "2026-10-01", "Shares": 10, "Value": 100, "Text": "Purchase at price 10.00 per share."},
                      {"Start Date": "2026-10-02", "Shares": 5, "Value": 0, "Text": "Sale at price 10.00 per share."}], TODAY)
    summary = summarize(rows, TODAY)
    assert summary["net_shares"] == 5 and summary["net_value"] is None


def test_a_recorded_purchase_is_a_buy_and_the_window_is_by_transaction_date():
    now = date(2025, 10, 1)
    rows = normalize(frame("TSLA"), now)
    summary = summarize(rows, now)
    assert summary["buys"] == {"count": 1, "shares": 2568732.0} and summary["sells"]["count"] == 0
    assert summary["net_shares"] == 2568732.0 and summary["net_value"] == 999959042.0
    assert summarize(rows, date(2025, 10, 31))["buys"]["count"] == 1  # 49 days old, still inside
    assert summarize(rows, date(2026, 1, 1))["buys"]["count"] == 0  # 111 days old, outside


def test_normalize_accepts_plain_records_and_drops_bad_rows():
    rows = normalize([{"Start Date": "2026-10-01", "Shares": 10, "Value": float("nan"), "Text": "Sale at price 1.00 per share.", "Insider": "A"},
                      {"Start Date": "", "Shares": 10, "Text": "Sale"}, {"Start Date": "2026-10-02", "Shares": None, "Text": "Sale"},
                      {"Start Date": "2020-01-01", "Shares": 5, "Text": "Sale"}], TODAY)
    assert rows == [{"date": "2026-10-01", "insider": "A", "position": None, "kind": "sell", "shares": 10.0, "value": None}]


def make(tmp_path, fetcher, clock):
    return SymbolInsiders(root=tmp_path, clock=lambda: clock[0], fetcher=fetcher, today=lambda: TODAY)


def test_view_caches_a_day_and_serves_the_old_copy_with_a_message_on_failure(tmp_path):
    clock, calls, fail = [1000.0], [], []

    def fetcher(symbol, today):
        calls.append(symbol)
        if fail:
            raise ProviderError("Yahoo could not be read.")
        return normalize(frame("NVDA"), today)

    first = make(tmp_path, fetcher, clock).view("NVDA")
    assert first["state"] == "ready" and first["source"] == "Yahoo, unofficial" and first["message"] is None
    again = make(tmp_path, fetcher, clock)  # a new process reads the file, not Yahoo
    assert again.view("NVDA")["sells"] == first["sells"] and calls == ["NVDA"]
    fail.append(1)
    clock[0] += 25 * 3600
    stale = again.view("NVDA")
    assert stale["state"] == "ready" and stale["fetched_at"] == 1000 and stale["message"] == "Yahoo could not be read."
    assert stale["sells"] == first["sells"]
    again.view("NVDA")
    assert calls == ["NVDA", "NVDA"]  # not retried for five minutes


def test_view_without_a_cache_is_unavailable_and_empty_yahoo_is_none(tmp_path):
    def boom(symbol, today):
        raise RuntimeError("yfinance exploded")

    out = make(tmp_path, boom, [5.0]).view("NVDA")
    assert out["state"] == "unavailable" and out["message"] == "Yahoo could not be read." and out["fetched_at"] is None
    empty = make(tmp_path / "e", lambda s, t: normalize(None, t), [5.0]).view("SPY")
    assert empty["state"] == "none" and "no insider transactions" in empty["message"]


def test_a_quiet_quarter_is_ready_with_zero_counts(tmp_path):
    late = date(2026, 12, 31)  # TSLA's September rows are still cached, but 90 days back starts in October
    out = SymbolInsiders(root=tmp_path, clock=lambda: 5.0, fetcher=lambda s, t: normalize(frame("TSLA"), t), today=lambda: late).view("TSLA")
    assert out["state"] == "ready" and out["buys"]["count"] == 0 and out["sells"]["count"] == 0 and out["latest"] == []
