"""Correct expiration closes saved as UTC clocks instead of New York wall time.

Run from backend/ after a verified backup and with import writers paused:
  .venv/bin/python scripts/repair_expired_trade_times.py --check
  .venv/bin/python scripts/repair_expired_trade_times.py --apply --backup /secure/path/database.dump

Only expired trades whose stored close is exactly the UTC-clock rendering of
16:00 on their expiration date are changed. Other timestamps are left alone.
Saved reviews are retained and marked stale; affected same-day fill sequence
fields are recomputed in place, and path metrics are removed for recomputation.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import delete
from sqlmodel import Session, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import engine  # noqa: E402
from app.engine.behavior import SequenceState  # noqa: E402
from app.engine.reconstructor import FillInput, reconstruct  # noqa: E402
from app.models import (  # noqa: E402
    DailyReviewRecord, FILL_LIGHT, Fill, FillMarketContext, Trade, TradeFill, TradePathMetrics,
)

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def _fill_input(fill: Fill) -> FillInput:
    return FillInput(
        id=fill.id, account_id=fill.account_id, ticker=fill.ticker,
        instrument_type=fill.instrument_type, side=fill.side,
        contracts=Decimal(str(fill.contracts)), price=Decimal(str(fill.price)),
        executed_at=fill.executed_at, option_type=fill.option_type,
        strike=Decimal(str(fill.strike)) if fill.strike is not None else None,
        expiration=fill.expiration,
    )


def repair(*, apply: bool = False) -> dict[str, int]:
    with Session(engine) as session:
        trades = session.exec(select(Trade).where(Trade.status == "expired")).all()
        candidates: list[tuple[Trade, datetime]] = []
        correct = ambiguous = 0
        for trade in trades:
            if trade.expiration is None or trade.closed_at is None:
                ambiguous += 1
                continue
            target = datetime.combine(trade.expiration, time(16))
            utc_clock = target.replace(tzinfo=ET).astimezone(UTC).replace(tzinfo=None)
            if trade.closed_at == target:
                correct += 1
            elif trade.closed_at == utc_clock:
                candidates.append((trade, target))
            else:
                ambiguous += 1

        # A stored timestamp is not enough evidence by itself: confirm the
        # candidate still belongs to the current FIFO reconstruction.
        fills: list[Fill] = []
        if candidates:
            fills = session.exec(select(Fill).options(*FILL_LIGHT)).all()
            rebuilt = {
                trade.id: trade for trade in reconstruct(
                    [_fill_input(fill) for fill in fills], today=datetime.now(ET).date()
                ).trades
            }
            for stored, target in candidates:
                expected = rebuilt.get(stored.id)
                pnl = Decimal(str(stored.realized_pnl)) if stored.realized_pnl is not None else None
                if (expected is None or expected.status != "expired"
                        or expected.closed_at != target
                        or expected.opened_at != stored.opened_at
                        or expected.realized_pnl != pnl
                        or expected.hold_duration_mins != stored.hold_duration_mins):
                    raise ValueError(f"Trade {stored.id} no longer matches a fresh reconstruction")

        result = {
            "candidate_trades": len(candidates),
            "already_correct": correct,
            "unresolved": ambiguous,
        }
        if not apply or not candidates:
            return result

        ids = [trade.id for trade, _ in candidates]
        boundaries = {(trade.account_id, trade.expiration): target for trade, target in candidates}
        sequence_fills = [
            fill for fill in fills
            if (boundary := boundaries.get((fill.account_id, fill.executed_at.date()))) is not None
            and fill.executed_at >= boundary
        ]
        sequence_fill_ids = [fill.id for fill in sequence_fills]
        linked_ids = set(session.exec(
            select(TradeFill.trade_id).where(TradeFill.fill_id.in_(sequence_fill_ids))
        ).all()) if sequence_fill_ids else set()
        analysis_ids = set(ids) | linked_ids
        analysis_trades = session.exec(select(Trade).where(Trade.id.in_(analysis_ids))).all()
        days = {
            day
            for trade in analysis_trades
            for day in (trade.opened_at.date(), trade.closed_at.date() if trade.closed_at else None)
            if day is not None
        }
        for trade, target in candidates:
            trade.closed_at = target
            days.add(target.date())
        session.flush()
        sequence = SequenceState(session)
        for fill in sequence_fills:
            context = session.get(FillMarketContext, fill.id)
            if context is not None:
                for key, value in sequence.compute(fill).items():
                    setattr(context, key, value)
        for trade in analysis_trades:
            if trade.ai_review:
                review = json.loads(trade.ai_review)
                if isinstance(review, dict):
                    review["source_data_stale"] = True
                    trade.ai_review = json.dumps(review)
        for saved in session.exec(select(DailyReviewRecord).where(DailyReviewRecord.day.in_(days))).all():
            review = json.loads(saved.review_json)
            if isinstance(review, dict):
                review["source_data_stale"] = True
                saved.review_json = json.dumps(review)
        session.exec(delete(TradePathMetrics).where(TradePathMetrics.trade_id.in_(ids)))
        session.commit()
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path, help="Existing nonempty database backup; required for --apply")
    args = parser.parse_args()
    if args.apply and (not args.backup or not args.backup.is_file() or args.backup.stat().st_size == 0):
        parser.error("--apply requires --backup pointing to an existing nonempty database backup")
    print(json.dumps(repair(apply=args.apply), sort_keys=True))


if __name__ == "__main__":
    main()
