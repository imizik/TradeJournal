"""The Peers strip (T3.4): Polygon's related-companies response and Tradier quote rows, normalized.

Pure functions over supplied responses (no network, no database). Fetching, caching and the
rate limiter live in ``symbol_info_peers_feed``.

Two traps from the recorded responses: Polygon omits ``results`` entirely when a symbol has no
related companies (SPY), and Tradier returns ``quotes.quote`` as an object for one symbol and an
array for several, listing unknown symbols under ``unmatched_symbols`` instead of in the rows.
The quote's ``average_volume`` is deliberately not read (it is not the volume average you expect).
"""

import json
import math
from pathlib import Path
import re
from statistics import median

MAX_PEERS = 10
GROUPS_FILE = Path(__file__).resolve().parent.parent / "data" / "peer_groups.json"
# The Valuation block's comparisons. A loss-maker's P/E or EV/EBITDA is not a multiple, so only positive values count.
COMPARED = ("pe", "price_to_sales", "price_to_book", "ev_to_ebitda")
MIN_PEERS = 3  # a median of one or two companies is a quote, not a norm
_TICKER = re.compile(r"[A-Z][A-Z0-9.-]{0,9}")


def normalize_related(body: object, symbol: str) -> list[str]:
    """Related tickers in Polygon's order, deduplicated, without the symbol itself."""
    results = body.get("results") if isinstance(body, dict) else None
    out: list[str] = []
    for row in results if isinstance(results, list) else []:
        ticker = str(row.get("ticker") or "").strip().upper() if isinstance(row, dict) else ""
        if _TICKER.fullmatch(ticker) and ticker != symbol and ticker not in out:
            out.append(ticker)
    return out[:MAX_PEERS]


def load_groups(path: Path = GROUPS_FILE) -> dict[str, tuple[str, list[str]]]:
    """Symbol -> (group name, its peers in order). A symbol in several groups keeps its first.
    No file (bundles that leave out ``data`` folders) means no groups: every symbol uses Polygon."""
    out: dict[str, tuple[str, list[str]]] = {}
    if not path.is_file():
        return out
    for group in json.loads(path.read_text())["groups"]:
        members = [str(m).upper() for m in group["members"]]
        for symbol in members:
            out.setdefault(symbol, (str(group["name"]), [m for m in members if m != symbol][:MAX_PEERS]))
    return out


def valuation(rows: dict[str, dict], peers: list[str]) -> dict:
    """The peers' median of each compared ratio, from the peers whose value is positive, and how many counted."""
    out: dict = {"median": {}, "counted": {}}
    for field in COMPARED:
        values = [v for v in (_number(rows.get(peer, {}).get(field)) for peer in peers) if v is not None and v > 0]
        out["counted"][field] = len(values)
        out["median"][field] = round(median(values), 2) if len(values) >= MIN_PEERS else None
    return out


def _number(value: object) -> float | None:
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def quote_rows(data: object) -> list[dict]:
    quotes = data.get("quotes") if isinstance(data, dict) else None
    quote = quotes.get("quote") if isinstance(quotes, dict) else None
    if isinstance(quote, dict):
        return [quote]
    return [row for row in quote if isinstance(row, dict)] if isinstance(quote, list) else []


def chips(tickers: list[str], data: object) -> list[dict]:
    """One chip per peer, in order. A peer Tradier did not quote keeps its chip with nulls."""
    by_symbol = {str(row.get("symbol") or "").upper(): row for row in quote_rows(data)}
    out = []
    for ticker in tickers:
        row = by_symbol.get(ticker, {})
        out.append({"symbol": ticker, "name": str(row["description"]) if row.get("description") else None,
                    "last": _number(row.get("last")), "change_percentage": _number(row.get("change_percentage"))})
    return out
