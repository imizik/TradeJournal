"""The market's backdrop from one recorded Radar pass: the benchmark ETFs' day, computed the way "Movers now" does.

``build_movers`` ranks stocks and drops the benchmark rows it measured them against; this keeps those rows (SPY, QQQ,
IWM, RSP and the sector ETFs) so the copilot can say whether a move is the stock, its sector or the whole market.
Arithmetic over recorded quotes only: no thresholds, no provider calls.
"""
from app.engine.radar_comparison import _endpoint
from app.engine.radar_movers import _pct, _price

INDICES = ("SPY", "QQQ", "IWM", "RSP")


def sector_of(universe: dict, symbol: str) -> str | None:
    """The sector ETF a tracked stock is measured against, or None (an ETF, or a symbol Radar does not track)."""
    return next((row.get("sector") for row in universe["symbols"] if row["symbol"] == symbol), None)


def day_moves(universe: dict, quotes: list[dict], earlier_quotes: list[dict] | None, *, latest: dict,
              earlier: dict | None = None, symbols: list[str] | None = None) -> dict[str, dict]:
    """``{symbol: {last, day_pct, from_open_pct, open_gap_pct, last_15m_pct}}`` for every tracked symbol with a usable
    quote in ``latest`` (or just ``symbols``). ``last_15m_pct`` needs the earlier pass; it is None without one."""
    by_symbol = {q["symbol"]: q for q in quotes if _endpoint(q, latest)[0] is not None}
    before = {q["symbol"]: q["last"] for q in earlier_quotes or []
              if earlier is not None and _endpoint(q, earlier)[0] is not None}
    out: dict[str, dict] = {}
    wanted = set(symbols) if symbols is not None else None
    for row in universe["symbols"]:
        sym = row["symbol"]
        if wanted is not None and sym not in wanted:
            continue
        q = by_symbol.get(sym)
        last, prev = (_price(q["last"]), _price(q["prev_close"])) if q else (None, None)
        if not (last and prev):
            continue
        open_ = _price(q["open"])
        was = _price(before.get(sym))
        out[sym] = {"last": last, "day_pct": _pct(last, prev),
                    "from_open_pct": _pct(last, open_) if open_ else None,
                    "open_gap_pct": _pct(open_, prev) if open_ else None,
                    "last_15m_pct": _pct(last, was) if was else None}
    return out


def benchmark_day(universe: dict, quotes: list[dict], earlier_quotes: list[dict] | None, *, latest: dict,
                  earlier: dict | None = None) -> dict[str, dict]:
    """The benchmark rows only (``benchmark: true`` in the universe): the four indices and the sector ETFs."""
    marks = [row["symbol"] for row in universe["symbols"] if row["benchmark"]]
    return day_moves(universe, quotes, earlier_quotes, latest=latest, earlier=earlier, symbols=marks)
