"""Trader-state sequence metrics at fill time, from the journal's own history.

No external data: everything is derived from existing Trade/Fill/TradeFill
rows. Scope is same-account and (except open_positions_count) same ET day,
since tilt/revenge patterns are intraday phenomena. All datetimes in the DB
are naive America/New_York, so naive comparisons are consistent.

Note these fields describe the state *as of the fill* given today's trade
history; like all enrichment they are recomputed on a forced re-run if fills
are edited and trades rebuilt.
"""

from collections import defaultdict
from datetime import datetime

from sqlmodel import Session, select

from app.models import Fill, Trade, TradeFill

ENTRY_SIDES = ("buy_to_open", "sell_to_open", "buy")
REENTRY_LOOKBACK_SECONDS = 3600  # same-ticker loss within the prior hour


class SequenceState:
    """Preloads trade/fill history once; ``compute(fill)`` is then in-memory."""

    def __init__(self, session: Session):
        trades = session.exec(select(Trade)).all()
        self._trades_by_account: dict = defaultdict(list)
        self._closed_by_account: dict = defaultdict(list)
        for t in trades:
            self._trades_by_account[t.account_id].append(t)
            if t.closed_at is not None:
                self._closed_by_account[t.account_id].append(t)
        for lst in self._closed_by_account.values():
            lst.sort(key=lambda t: t.closed_at)

        entry_rows = session.exec(
            select(Fill.account_id, Fill.executed_at).where(Fill.side.in_(ENTRY_SIDES))
        ).all()
        self._entries_by_account: dict = defaultdict(list)
        for acct, ts in entry_rows:
            if ts is not None:
                self._entries_by_account[acct].append(ts)

        tf_rows = session.exec(select(TradeFill.fill_id, TradeFill.trade_id)).all()
        self._trade_of_fill = {fid: tid for fid, tid in tf_rows}

    def compute(self, fill: Fill) -> dict:
        ts: datetime = fill.executed_at
        day = ts.date()
        acct = fill.account_id

        entries_today_before = sum(
            1
            for e in self._entries_by_account.get(acct, [])
            if e.date() == day and e < ts
        )

        closed_today = [
            t
            for t in self._closed_by_account.get(acct, [])
            if t.closed_at.date() == day and t.closed_at < ts
        ]
        realized_before = sum(float(t.realized_pnl or 0) for t in closed_today)

        loss_streak = 0
        for t in reversed(closed_today):
            if float(t.realized_pnl or 0) < 0:
                loss_streak += 1
            else:
                break

        minutes_since_last_exit = (
            int((ts - closed_today[-1].closed_at).total_seconds() // 60)
            if closed_today
            else None
        )

        own_trade_id = self._trade_of_fill.get(fill.id)
        open_positions = sum(
            1
            for t in self._trades_by_account.get(acct, [])
            if t.id != own_trade_id
            and t.opened_at is not None
            and t.opened_at <= ts
            and (t.closed_at is None or t.closed_at > ts)
        )

        is_reentry_after_loss = 0
        same_ticker = [t for t in closed_today if t.ticker == fill.ticker]
        if same_ticker:
            last = same_ticker[-1]
            if (
                float(last.realized_pnl or 0) < 0
                and (ts - last.closed_at).total_seconds() <= REENTRY_LOOKBACK_SECONDS
            ):
                is_reentry_after_loss = 1

        return {
            "entries_today_before": entries_today_before,
            "trades_closed_today_before": len(closed_today),
            "realized_pnl_today_before": round(realized_before, 2),
            "loss_streak_today_before": loss_streak,
            "minutes_since_last_exit": minutes_since_last_exit,
            "open_positions_count": open_positions,
            "is_reentry_after_loss": is_reentry_after_loss,
        }
