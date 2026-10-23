"""The plain "Movers now" ranking: arithmetic over one recorded pass and the pass about 15 minutes before it.

No thresholds, no events and no provider calls. A symbol without a usable last and prev_close is counted
as missing, never shown as 0%.
"""
from datetime import datetime
from statistics import median

LOOKBACK_SECONDS = 15 * 60
LOOKBACK_TOLERANCE_SECONDS = 120
TOP = 10


def _epoch(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _price(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and value > 0 else None


def _pct(now: float, base: float) -> float:
    return round((now / base - 1) * 100, 3)


def earlier_pass(recorded: list[dict], latest: dict) -> dict | None:
    """The recorded pass closest to 15 minutes before ``latest``, if one is within the tolerance."""
    target = _epoch(latest["started_at"]) - LOOKBACK_SECONDS
    near = [p for p in recorded if p["id"] != latest["id"] and abs(_epoch(p["started_at"]) - target) <= LOOKBACK_TOLERANCE_SECONDS]
    return min(near, key=lambda p: abs(_epoch(p["started_at"]) - target)) if near else None


def build_movers(universe: dict, quotes: list[dict], earlier_quotes: list[dict] | None) -> dict:
    """Header numbers, leaders, laggards, group summaries and missing symbols; ``None`` when SPY has no usable quote."""
    by_symbol = {q["symbol"]: q for q in quotes}
    before = {q["symbol"]: _price(q["last"]) for q in earlier_quotes or []}
    day: dict[str, float] = {}
    for row in universe["symbols"]:
        q = by_symbol.get(row["symbol"])
        last, prev = (_price(q["last"]), _price(q["prev_close"])) if q else (None, None)
        if last and prev:
            day[row["symbol"]] = _pct(last, prev)
    tracked = [row["symbol"] for row in universe["symbols"]]
    missing = [s for s in tracked if s not in day]
    if "SPY" not in day:
        return {"header": None, "leaders": [], "laggards": [], "groups": [], "missing": missing}

    rows: dict[str, dict] = {}
    for row in universe["symbols"]:
        sym = row["symbol"]
        if row["benchmark"] or sym not in day:
            continue
        q = by_symbol[sym]
        open_ = _price(q["open"])
        sector = row.get("sector")
        earlier = before.get(sym)
        rows[sym] = {
            "symbol": sym, "kind": row["kind"], "last": q["last"], "day_pct": day[sym],
            "from_open_pct": _pct(q["last"], open_) if open_ else None,
            "vs_spy": round(day[sym] - day["SPY"], 3),
            "sector": sector if sector in day else None,
            "vs_sector": round(day[sym] - day[sector], 3) if sector in day else None,
            "last_15m_pct": _pct(q["last"], earlier) if earlier else None,
        }
    ranked = sorted((r for r in rows.values() if r["kind"] == "stock"), key=lambda r: (-r["vs_spy"], r["symbol"]))
    laggards = ranked[max(TOP, len(ranked) - TOP):][::-1]

    groups = []
    for group in universe["groups"]:
        members = [rows[m] for m in group["members"] if m in rows]
        if members:
            mid = round(median(r["vs_spy"] for r in members), 3)
            top = max(members, key=lambda r: (abs(r["vs_spy"]), r["symbol"]))
            most = {"symbol": top["symbol"], "vs_spy": top["vs_spy"]}
        else:
            mid, most = None, None
        groups.append({"name": group["name"], "members_total": len(group["members"]), "members_with_data": len(members),
                       "ahead": sum(1 for r in members if r["vs_spy"] > 0), "behind": sum(1 for r in members if r["vs_spy"] < 0),
                       "median_vs_spy": mid, "most": most})
    groups.sort(key=lambda g: (g["median_vs_spy"] is None, -abs(g["median_vs_spy"] or 0), g["name"]))
    return {
        "header": {"spy_day_pct": day["SPY"], "qqq_day_pct": day.get("QQQ"), "symbols_with_data": len(day),
                   "symbols_tracked": len(tracked), "has_earlier_pass": earlier_quotes is not None},
        "leaders": ranked[:TOP], "laggards": laggards, "groups": groups, "missing": missing,
    }
