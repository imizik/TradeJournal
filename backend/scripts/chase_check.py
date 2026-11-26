"""Do extended entries really do worse? A read-only check of the "chasing" tag against prices.

The pre-trade check says "Price is X% past VWAP, the shape of a chase" and quotes the record of trades a model tagged
as chases after the fact (``trade_ai_tags.pretrade_setup_record``). That record is hindsight: a losing trade is easier
to call a chase. This measures the same thing from prices instead. For each closed long option trade (entries all
``buy_to_open``, Webull left out), the first entry fill's ``FillMarketContext`` (from minute bars at the fill) gives how
far the stock was past VWAP in the trade's direction (calls above, puts below) and where it sat in the day's range so
far. Trades are grouped by that distance; each group's count, win rate, dollars and median return are printed, plus the
gap between extended (``EXTENDED_PCT`` or more, the pre-trade check's own line) and the rest with a bootstrap interval,
overall and within short-dated (0-3 days) and longer options, and against the model's chase tag.

Aggregates only, printed as JSON; no trade, ticker or fill is printed. Nothing is written.

    cd backend && python -m scripts.chase_check
"""
from __future__ import annotations

import json
import random
from statistics import mean, median

from sqlmodel import Session, select

from app.database import engine
from app.engine.trade_ai_tags import EXTENDED_PCT, _is_chase
from app.models import FILL_LIGHT, Account, Fill, FillMarketContext, Trade, TradeAiTag, TradeFill

BUCKETS = ((None, 0.0, "against VWAP"), (0.0, 1.0, "0-1% past"), (1.0, EXTENDED_PCT, f"1-{EXTENDED_PCT:g}% past"),
           (EXTENDED_PCT, None, f"{EXTENDED_PCT:g}%+ past"))
SEED, DRAWS = 20261126, 5000


def rows(db: Session) -> list[dict]:
    tags = {(t.account_id, t.source_key): t for t in db.exec(select(TradeAiTag)).all()}
    out = []
    for trade, account in db.exec(select(Trade, Account).join(Account, Account.id == Trade.account_id).where(
            Trade.instrument_type == "option", Trade.status.in_(("closed", "expired")), Trade.realized_pnl.is_not(None))).all():
        if (account.broker or "").lower() == "webull" or trade.option_type not in ("call", "put"):
            continue
        entries = db.exec(select(Fill).options(*FILL_LIGHT).join(TradeFill, TradeFill.fill_id == Fill.id).where(
            TradeFill.trade_id == trade.id, TradeFill.role == "entry").order_by(Fill.executed_at, Fill.raw_email_id)).all()
        if not entries or any(f.side != "buy_to_open" for f in entries):
            continue
        context = db.get(FillMarketContext, entries[0].id)
        tag = tags.get((trade.account_id, entries[0].raw_email_id))
        sign = 1 if trade.option_type == "call" else -1
        days = (trade.expiration - entries[0].executed_at.date()).days if trade.expiration else None
        range_used = context.entry_day_range_used_pct if context else None
        out.append({
            "pnl": float(trade.realized_pnl), "pct": float(trade.pnl_pct) * 100 if trade.pnl_pct is not None else None,  # stored as a ratio
            "past": sign * context.entry_vs_vwap_pct if context and context.entry_vs_vwap_pct is not None else None,
            # Where in the day's range so far, toward the trade's side: 100 is buying a call at the high of day.
            "range": None if range_used is None else (range_used if sign > 0 else 100 - range_used),
            "short": days is not None and 0 <= days <= 3,
            "tag_chase": None if tag is None else _is_chase({"setup": tag.setup, "primary_mistake": tag.primary_mistake,
                                                             "mistakes": json.loads(tag.mistakes_json or "[]")}),
        })
    return out


def record(group: list[dict]) -> dict:
    pct = [r["pct"] for r in group if r["pct"] is not None]
    return {"trades": len(group), "win_rate": round(sum(r["pnl"] > 0 for r in group) / len(group), 3) if group else None,
            "total_pnl": round(sum(r["pnl"] for r in group)), "mean_pnl": round(mean(r["pnl"] for r in group)) if group else None,
            "median_return_pct": round(median(pct), 1) if pct else None}


def gap(a: list[dict], b: list[dict]) -> dict | None:
    """Mean return (percent of premium) of ``a`` minus ``b``, with a 95% bootstrap interval."""
    x, y = [r["pct"] for r in a if r["pct"] is not None], [r["pct"] for r in b if r["pct"] is not None]
    if len(x) < 10 or len(y) < 10:
        return None
    rng = random.Random(SEED)
    draws = sorted(mean(rng.choices(x, k=len(x))) - mean(rng.choices(y, k=len(y))) for _ in range(DRAWS))
    return {"extended_minus_rest_mean_return_pts": round(mean(x) - mean(y), 1),
            "interval_95": [round(draws[int(DRAWS * 0.025)], 1), round(draws[int(DRAWS * 0.975)], 1)]}


def report(found: list[dict]) -> dict:
    measured = [r for r in found if r["past"] is not None]
    out = {"long_option_trades": len(found), "with_vwap_at_entry": len(measured), "by_distance_past_vwap": {}}
    for low, high, label in BUCKETS:
        out["by_distance_past_vwap"][label] = record([r for r in measured if (low is None or r["past"] >= low)
                                                      and (high is None or r["past"] < high)])
    ext = [r for r in measured if r["past"] >= EXTENDED_PCT]
    rest = [r for r in measured if r["past"] < EXTENDED_PCT]
    out["extended_vs_rest"] = {"all": gap(ext, rest),
                               "short_dated_0_3d": gap([r for r in ext if r["short"]], [r for r in rest if r["short"]]),
                               "longer": gap([r for r in ext if not r["short"]], [r for r in rest if not r["short"]])}
    ranged = [r for r in found if r["range"] is not None]
    out["by_day_range_toward_trade"] = {label: record([r for r in ranged if low <= r["range"] < high])
                                        for low, high, label in ((0, 50, "bottom half"), (50, 80, "50-80%"), (80, 101, "top 20%"))}
    tagged = [r for r in measured if r["tag_chase"] is not None]
    out["model_chase_tag_vs_prices"] = {
        f"tagged chase, {name}": record([r for r in tagged if r["tag_chase"] and (r["past"] >= EXTENDED_PCT) == is_ext])
        for name, is_ext in (("extended", True), ("not extended", False))} | {
        f"not tagged, {name}": record([r for r in tagged if not r["tag_chase"] and (r["past"] >= EXTENDED_PCT) == is_ext])
        for name, is_ext in (("extended", True), ("not extended", False))}
    return out


if __name__ == "__main__":
    with Session(engine) as db:
        print(json.dumps(report(rows(db)), indent=2))
