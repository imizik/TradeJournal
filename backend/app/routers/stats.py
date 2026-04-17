from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.database import get_session
from app.models import Account, Tag, Trade, TradeFill, TradeTag

router = APIRouter()


@router.get("")
async def get_stats(
    account: str | None = None,
    type: str | None = None,
    session: Session = Depends(get_session),
):
    trades = session.exec(select(Trade)).all()
    if account and account != "all":
        accounts = session.exec(select(Account)).all()
        allowed_account_ids = {a.id for a in accounts if a.type == account}
        trades = [t for t in trades if t.account_id in allowed_account_ids]
    if type and type != "all":
        trades = [t for t in trades if t.instrument_type == type]

    closed = [t for t in trades if t.status in ("closed", "expired")]
    open_trades = [t for t in trades if t.status == "open"]

    winners = [t for t in closed if t.realized_pnl is not None and t.realized_pnl > 0]
    losers = [t for t in closed if t.realized_pnl is not None and t.realized_pnl <= 0]

    total_pnl = sum((float(t.realized_pnl) for t in closed if t.realized_pnl is not None), start=0.0)
    total_premium_risked = sum((float(t.total_premium_paid) for t in trades), start=0.0)

    win_rate = len(winners) / len(closed) if closed else 0.0
    avg_win_pct  = _avg([t.pnl_pct for t in winners if t.pnl_pct is not None])
    avg_loss_pct = _avg([t.pnl_pct for t in losers  if t.pnl_pct is not None])
    avg_hold_mins = _avg([t.hold_duration_mins for t in closed if t.hold_duration_mins])

    expired_worthless = [t for t in closed if t.expired_worthless]
    expired_worthless_rate = len(expired_worthless) / len(closed) if closed else 0.0

    # --- breakdowns ---
    by_ticker = _breakdown_by(closed, key=lambda t: t.ticker)
    by_time_bucket = _breakdown_by(
        [t for t in closed if t.entry_time_bucket],
        key=lambda t: t.entry_time_bucket,
    )

    # Tag breakdowns — load tags for each trade
    tag_map: dict[str, list[Trade]] = defaultdict(list)
    trade_tags = session.exec(select(TradeTag)).all()
    tag_ids = {tt.tag_id for tt in trade_tags}
    tags_by_id = {t.id: t.name for t in session.exec(select(Tag)).all()}
    trade_id_to_tags: dict = defaultdict(list)
    for tt in trade_tags:
        trade_id_to_tags[tt.trade_id].append(tags_by_id.get(tt.tag_id, ""))
    for trade in closed:
        for tag_name in trade_id_to_tags.get(trade.id, []):
            if tag_name:
                tag_map[tag_name].append(trade)
    by_tag = {name: _trade_summary(ts) for name, ts in tag_map.items()}

    # --- behavioral flag counts (from ai_review JSON) ---
    import json
    flag_counts: dict[str, int] = defaultdict(int)
    for t in closed:
        if t.ai_review:
            try:
                review = json.loads(t.ai_review)
                for flag in review.get("flags", []):
                    flag_counts[flag] += 1
            except (json.JSONDecodeError, AttributeError):
                pass

    # Today's PnL
    today = date.today()
    today_pnl = sum(
        (
            float(t.realized_pnl)
            for t in closed
            if t.realized_pnl is not None and t.closed_at and t.closed_at.date() == today
        ),
        start=0.0,
    )

    return {
        "total_trades": len(trades),
        "open_trades": len(open_trades),
        "closed_trades": len(closed),
        "win_rate": round(win_rate, 4),
        "total_pnl": round(total_pnl, 2),
        "total_premium_risked": round(total_premium_risked, 2),
        "today_pnl": round(today_pnl, 2),
        "avg_win_pct": round(avg_win_pct, 4) if avg_win_pct is not None else None,
        "avg_loss_pct": round(avg_loss_pct, 4) if avg_loss_pct is not None else None,
        "avg_hold_mins": round(avg_hold_mins, 1) if avg_hold_mins is not None else None,
        "expired_worthless_rate": round(expired_worthless_rate, 4),
        "by_ticker": by_ticker,
        "by_tag": by_tag,
        "by_time_bucket": by_time_bucket,
        "behavioral_flags": dict(flag_counts),
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _avg(values: list) -> float | None:
    filtered = [float(v) for v in values if v is not None]
    return sum(filtered) / len(filtered) if filtered else None


def _trade_summary(trades: list[Trade]) -> dict:
    closed = [t for t in trades if t.realized_pnl is not None]
    winners = [t for t in closed if t.realized_pnl > 0]
    pnl = sum((float(t.realized_pnl) for t in closed), start=0.0)
    return {
        "count": len(trades),
        "win_rate": round(len(winners) / len(closed), 4) if closed else 0.0,
        "total_pnl": round(pnl, 2),
        "avg_pnl_pct": round(
            _avg([t.pnl_pct for t in closed if t.pnl_pct is not None]) or 0, 4
        ),
    }


def _breakdown_by(trades: list[Trade], key) -> dict:
    groups: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        groups[key(t)].append(t)
    return {k: _trade_summary(v) for k, v in sorted(groups.items())}
