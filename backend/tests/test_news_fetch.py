"""The Alpaca news fetcher (app/engine/news.py): machine-written summaries never reach a consumer."""
from app.engine import news


def test_fiscal_ai_summaries_are_dropped_and_benzinga_kept(monkeypatch):
    page = {"news": [
        {"id": 1, "headline": "Nebius Shares Decline Following HPE Financing Warning", "source": "fiscal.ai", "symbols": ["NBIS"]},
        {"id": 2, "headline": "Nebius signs GPU deal", "source": "benzinga", "symbols": ["NBIS"]},
        {"id": 3, "headline": "Upper-case source", "source": " Fiscal.AI ", "symbols": ["NBIS"]},
    ]}
    monkeypatch.setattr(news, "_alpaca_get_fast", lambda path, params: page)
    found = news.fetch_news(symbols=["NBIS"], fast=True)
    assert [a["id"] for a in found] == [2] and found[0]["source"] == "benzinga"
