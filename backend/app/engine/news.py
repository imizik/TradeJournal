"""
Alpaca news (Benzinga feed) fetcher.

Returns cleaned headline dicts — HTML content stripped, deduped by article id.
Relevance filtering and market-moving/noise classification are deliberately
NOT done here; the consumer (Claude via the market report) triages headlines.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from app.engine.alpaca import _alpaca_get

log = logging.getLogger(__name__)

MAX_PAGE_LIMIT = 50
MAX_CONTENT_CHARS = 8000


def fetch_news(
    symbols: Optional[list[str]] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    limit: int = 50,
    include_content: bool = False,
) -> list[dict]:
    """
    Fetch news articles, newest first. `symbols=None` returns the broad tape.
    Returns a list of {id, headline, summary, symbols, source, created_at, url}.

    `include_content=True` adds full article text (HTML stripped, capped at
    MAX_CONTENT_CHARS). Meant for targeted drill-down on a few articles, not
    bulk packet assembly — keep `limit` small when using it.
    """
    params: dict = {
        "sort": "desc",
        "limit": min(limit, MAX_PAGE_LIMIT),
        "exclude_contentless": False,
        "include_content": include_content,
    }
    if symbols:
        params["symbols"] = ",".join(sorted({s.strip().upper() for s in symbols if s.strip()}))
    if start:
        params["start"] = start.isoformat()
    if end:
        params["end"] = end.isoformat()

    articles: list[dict] = []
    seen_ids: set[int] = set()
    page_token: Optional[str] = None

    while len(articles) < limit:
        page_params = dict(params)
        if page_token:
            page_params["page_token"] = page_token
        data = _alpaca_get("/v1beta1/news", page_params)
        for item in data.get("news", []):
            article_id = item.get("id")
            if article_id in seen_ids:
                continue
            seen_ids.add(article_id)
            article = {
                "id": article_id,
                "headline": item.get("headline"),
                "summary": item.get("summary"),
                "symbols": item.get("symbols", []),
                "source": item.get("source"),
                "created_at": item.get("created_at"),
                "url": item.get("url"),
            }
            if include_content:
                article["content"] = _strip_html(item.get("content") or "")[:MAX_CONTENT_CHARS]
            articles.append(article)
            if len(articles) >= limit:
                break
        page_token = data.get("next_page_token")
        if not page_token:
            break

    return articles


def _strip_html(html: str) -> str:
    import html as html_mod

    html = html_mod.unescape(html)
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()
