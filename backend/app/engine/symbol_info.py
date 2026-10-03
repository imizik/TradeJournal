"""Pure journal summaries for the symbol panel; never reconstruct P&L."""

from decimal import Decimal


def journal_summary(symbol: str, trades: list[dict], last_traded_at: str | None) -> dict:
    """Summarize stored results across accounts for one underlying.

    Expired trades are completed losses/profits, just as in journal stats.
    Missing results must not turn into zero or a misleading complete total.
    Trade times and last_traded_at are New York wall clocks.
    """
    closed = [t for t in trades if t["status"] in ("closed", "expired")]
    known = [t for t in closed if t["realized_pnl"] is not None]
    holds = [t["hold_duration_mins"] for t in closed if t["hold_duration_mins"] is not None]
    complete = bool(closed) and len(known) == len(closed)

    def record(t):
        return {key: float(value) if isinstance(value, Decimal) else value for key, value in t.items()}

    recent = sorted(trades, key=lambda t: (t["closed_at"] or t["opened_at"], t["id"]), reverse=True)
    return {
        "symbol": symbol,
        "total_trades": len(trades),
        "closed_trades": len(closed),
        "missing_pnl": len(closed) - len(known),
        "realized_pnl": float(sum((Decimal(str(t["realized_pnl"])) for t in known), Decimal(0))) if complete else None,
        "win_rate": sum(t["realized_pnl"] > 0 for t in known) / len(closed) if complete else None,
        "average_hold_mins": sum(holds) / len(holds) if holds else None,
        "hold_samples": len(holds),
        "best_trade": record(max(known, key=lambda t: (t["realized_pnl"], t["id"]))) if known else None,
        "worst_trade": record(min(known, key=lambda t: (t["realized_pnl"], t["id"]))) if known else None,
        "last_traded_at": last_traded_at,
        "open_positions": [record(t) for t in recent if t["status"] == "open"],
        "recent_trades": [record(t) for t in recent[:5]],
    }
