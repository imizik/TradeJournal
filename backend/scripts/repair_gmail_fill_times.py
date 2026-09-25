"""Verify Gmail fill times against source emails, then repair proven UTC-clock rows.

Run from backend/:
  .venv/bin/python scripts/repair_gmail_fill_times.py --plan /secure/path/fill-times.json
  .venv/bin/python scripts/repair_gmail_fill_times.py --check /secure/path/fill-times.json
  .venv/bin/python scripts/repair_gmail_fill_times.py --apply /secure/path/fill-times.json --backup /secure/path/pre-repair.dump

Planning reads the configured database and original Gmail messages. Applying
rechecks each source message and current DB value, then changes only rows whose
stored naive time equals the source instant expressed as a UTC clock. Rows
already matching the source's New York clock, missing messages, and ambiguous
rows are never changed. Keep a database backup before applying. A successful
apply invalidates affected enrichment; run forced Polygon, Alpaca, and trade
path jobs afterward, in that order. Pause API/import/background workers while
applying so no concurrent fill can invalidate the reconstruction check.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import delete
from sqlmodel import Session, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import engine  # noqa: E402
from app.engine.email_parser import parse_option_email  # noqa: E402
from app.engine.gmail_poller import _get_service, _message_body  # noqa: E402
from app.engine.reconstructor import FillInput, reconstruct  # noqa: E402
from app.models import (  # noqa: E402
    Account, FILL_LIGHT, Fill, FillMarketContext, Trade, TradeFill, TradePathMetrics,
)

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def _wall_time(value: datetime) -> datetime:
    return value.astimezone(ET).replace(tzinfo=None) if value.tzinfo else value


def _source(service, raw_email_id: str):
    msg = service.users().messages().get(
        userId="me", id=raw_email_id, format="full"
    ).execute()
    headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
    if "noreply@robinhood.com" not in headers.get("from", "").lower():
        raise ValueError("sender mismatch")
    subject = headers.get("subject", "")
    body = _message_body(msg)
    parsed = parse_option_email(subject, body, raw_email_id)
    if parsed is None:
        raise ValueError("source message is not a complete execution")
    digest = hashlib.sha256((subject + "\n" + body).encode()).hexdigest()
    return parsed, digest


def _same_execution(fill: Fill, account: Account, parsed) -> bool:
    return (
        fill.ticker == parsed.ticker
        and fill.instrument_type == parsed.instrument_type
        and fill.side == parsed.side
        and Decimal(str(fill.contracts)) == parsed.contracts
        and Decimal(str(fill.price)) == parsed.price
        and fill.option_type == parsed.option_type
        and (Decimal(str(fill.strike)) if fill.strike is not None else None) == parsed.strike
        and fill.expiration == parsed.expiration
        and (account.last4 == parsed.account_last4 or
             (account.last4 == "8267" and parsed.account_type == "roth_ira" and not parsed.account_last4))
    )


def _gmail_rows(session: Session) -> list[Fill]:
    return session.exec(
        select(Fill).options(*FILL_LIGHT)
        .where(~Fill.raw_email_id.like("manual:%"))
        .where(~Fill.raw_email_id.like("webull:%"))
        .order_by(Fill.executed_at, Fill.id)
    ).all()


def make_plan(path: Path) -> dict:
    with Session(engine) as session:
        fills = _gmail_rows(session)
        accounts = {a.id: a for a in session.exec(select(Account)).all()}
    service = _get_service()
    rows = []
    counts: dict[str, int] = {}
    for index, fill in enumerate(fills, 1):
        row = {
            "id": str(fill.id), "raw_email_id": fill.raw_email_id,
            "stored_at": fill.executed_at.isoformat(), "ticker": fill.ticker,
        }
        try:
            parsed, digest = _source(service, fill.raw_email_id)
            row["source_sha256"] = digest
            if not _same_execution(fill, accounts[fill.account_id], parsed):
                status = "identity_mismatch"
            else:
                target = _wall_time(parsed.executed_at)
                utc_clock = parsed.executed_at.astimezone(UTC).replace(tzinfo=None)
                row["source_at_et"] = target.isoformat()
                if fill.executed_at == target:
                    status = "correct"
                elif fill.executed_at == utc_clock:
                    status = "utc_clock"
                else:
                    status = "ambiguous"
        except Exception as exc:
            status = "source_unavailable"
            row["error_type"] = type(exc).__name__
        row["status"] = status
        counts[status] = counts.get(status, 0) + 1
        rows.append(row)
        if index % 100 == 0:
            print(f"Verified {index}/{len(fills)} source messages", file=sys.stderr)

    plan = {
        "format": 1,
        "database": engine.url.render_as_string(hide_password=True),
        "created_at_utc": datetime.now(UTC).isoformat(),
        "counts": counts,
        "rows": rows,
    }
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w")
    try:
        json.dump(plan, fd, indent=2)
        fd.write("\n")
    finally:
        fd.close()
    return plan


def _fill_input(fill: Fill) -> FillInput:
    return FillInput(
        id=fill.id, account_id=fill.account_id, ticker=fill.ticker,
        instrument_type=fill.instrument_type, side=fill.side,
        contracts=Decimal(str(fill.contracts)), price=Decimal(str(fill.price)),
        executed_at=fill.executed_at, option_type=fill.option_type,
        strike=Decimal(str(fill.strike)) if fill.strike is not None else None,
        expiration=fill.expiration,
    )


def _economic_signature(result) -> tuple:
    trades = {
        (t.id, t.account_id, t.ticker, t.instrument_type, t.option_type,
         t.strike, t.expiration, t.status, t.contracts, t.avg_entry_premium,
         t.avg_exit_premium, t.total_premium_paid, t.realized_pnl, t.pnl_pct,
         t.expired_worthless)
        for t in result.trades
    }
    links = {(tf.trade_id, tf.fill_id, tf.role) for tf in result.trade_fills}
    return trades, links, tuple(sorted(result.anomalies))


def check_plan(path: Path) -> dict:
    """Read-only FIFO/P&L preflight using source-verified timestamps in a plan."""
    plan = json.loads(path.read_text())
    if plan.get("format") != 1 or plan.get("database") != engine.url.render_as_string(hide_password=True):
        raise ValueError("Plan format or database identity does not match")
    changes = [row for row in plan["rows"] if row["status"] == "utc_clock"]
    with Session(engine) as session:
        fills = session.exec(select(Fill).options(*FILL_LIGHT)).all()
        by_id = {str(fill.id): fill for fill in fills}
        targets = {}
        for row in changes:
            fill = by_id.get(row["id"])
            if (fill is None or fill.raw_email_id != row["raw_email_id"]
                    or fill.executed_at.isoformat() != row["stored_at"]):
                raise ValueError(f"Database changed since plan for {row['raw_email_id']}")
            targets[fill.id] = datetime.fromisoformat(row["source_at_et"])
        today = datetime.now(ET).date()
        before = reconstruct([_fill_input(fill) for fill in fills], today=today)
        after = reconstruct([
            replace(_fill_input(fill), executed_at=targets[fill.id])
            if fill.id in targets else _fill_input(fill)
            for fill in fills
        ], today=today)
    before_by_id = {trade.id: trade for trade in before.trades}
    moved_trades = sum(
        trade.id not in before_by_id
        or (trade.opened_at, trade.closed_at, trade.hold_duration_mins, trade.entry_time_bucket)
        != (before_by_id[trade.id].opened_at, before_by_id[trade.id].closed_at,
            before_by_id[trade.id].hold_duration_mins, before_by_id[trade.id].entry_time_bucket)
        for trade in after.trades
    )
    return {
        "candidate_fills": len(changes),
        "affected_trade_times": moved_trades,
        "economic_signature_unchanged": _economic_signature(before) == _economic_signature(after),
        "before_trades": len(before.trades),
        "after_trades": len(after.trades),
        "before_anomalies": len(before.anomalies),
        "after_anomalies": len(after.anomalies),
    }


def apply_plan(path: Path) -> dict:
    plan = json.loads(path.read_text())
    if plan.get("format") != 1:
        raise ValueError("Unsupported plan format")
    if plan.get("database") != engine.url.render_as_string(hide_password=True):
        raise ValueError("Plan was made for another database")
    changes = [r for r in plan["rows"] if r["status"] == "utc_clock"]
    if not changes:
        return {"changed_fills": 0, "changed_trades": 0}

    # Gmail requests happen before the write transaction. Recheck every
    # candidate's source identity and body hash, not only the saved plan.
    service = _get_service()
    source_by_id = {}
    for index, row in enumerate(changes, 1):
        parsed, digest = _source(service, row["raw_email_id"])
        if digest != row["source_sha256"] or _wall_time(parsed.executed_at).isoformat() != row["source_at_et"]:
            raise ValueError(f"Source changed for {row['raw_email_id']}")
        source_by_id[row["id"]] = parsed
        if index % 100 == 0:
            print(f"Reverified {index}/{len(changes)} repair candidates", file=sys.stderr)

    with Session(engine) as session:
        fills = _gmail_rows(session)
        all_fills = session.exec(select(Fill).options(*FILL_LIGHT)).all()
        by_id = {str(f.id): f for f in fills}
        accounts = {a.id: a for a in session.exec(select(Account)).all()}
        for row in changes:
            fill = by_id.get(row["id"])
            if (fill is None or fill.raw_email_id != row["raw_email_id"]
                    or fill.executed_at.isoformat() != row["stored_at"]
                    or not _same_execution(fill, accounts[fill.account_id], source_by_id[row["id"]])):
                raise ValueError(f"Database changed since plan for {row['raw_email_id']}")

        today = datetime.now(ET).date()
        before = reconstruct([_fill_input(f) for f in all_fills], today=today)
        stored_trades = {t.id: t for t in session.exec(select(Trade)).all()}
        expected_trades = {t.id: t for t in before.trades}
        stored_links = {
            (tf.trade_id, tf.fill_id, tf.role)
            for tf in session.exec(select(TradeFill)).all()
        }
        expected_links = {
            (tf.trade_id, tf.fill_id, tf.role) for tf in before.trade_fills
        }
        if set(stored_trades) != set(expected_trades) or stored_links != expected_links:
            raise ValueError("Stored trades do not match a fresh reconstruction; no rows committed")
        for trade_id, expected in expected_trades.items():
            stored = stored_trades[trade_id]
            if (stored.status != expected.status or
                    (Decimal(str(stored.realized_pnl)) if stored.realized_pnl is not None else None)
                    != expected.realized_pnl):
                raise ValueError(f"Stored P&L differs from reconstruction for trade {trade_id}")
        for row in changes:
            by_id[row["id"]].executed_at = datetime.fromisoformat(row["source_at_et"])
        after = reconstruct([_fill_input(f) for f in all_fills], today=today)
        if _economic_signature(before) != _economic_signature(after):
            raise ValueError("Repair changes FIFO, trade links, P&L, or anomalies; no rows committed")

        before_trades = {t.id: t for t in before.trades}
        changed_trade_ids = set()
        for item in after.trades:
            old = before_trades[item.id]
            if (item.opened_at, item.closed_at, item.hold_duration_mins, item.entry_time_bucket) != (
                old.opened_at, old.closed_at, old.hold_duration_mins, old.entry_time_bucket
            ):
                trade = session.get(Trade, item.id)
                if trade is None:
                    raise ValueError(f"Missing persisted trade {item.id}")
                trade.opened_at = _wall_time(item.opened_at)
                trade.closed_at = _wall_time(item.closed_at) if item.closed_at else None
                trade.hold_duration_mins = item.hold_duration_mins
                trade.entry_time_bucket = item.entry_time_bucket
                changed_trade_ids.add(item.id)

        changed_fill_ids = [by_id[r["id"]].id for r in changes]
        changed_trade_ids.update(session.exec(
            select(TradeFill.trade_id).where(TradeFill.fill_id.in_(changed_fill_ids))
        ).all())
        for row in changes:
            fill = by_id[row["id"]]
            for column in Fill.__table__.columns:
                if column.name.endswith("_at_fill"):
                    setattr(fill, column.name, None)
        session.exec(delete(FillMarketContext).where(FillMarketContext.fill_id.in_(changed_fill_ids)))
        if changed_trade_ids:
            session.exec(delete(TradePathMetrics).where(TradePathMetrics.trade_id.in_(changed_trade_ids)))
        session.commit()
    return {"changed_fills": len(changes), "changed_trades": len(changed_trade_ids)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--plan", type=Path, metavar="FILE")
    action.add_argument("--check", type=Path, metavar="FILE")
    action.add_argument("--apply", type=Path, metavar="FILE")
    parser.add_argument("--backup", type=Path, help="Existing nonempty database backup; required for --apply")
    args = parser.parse_args()
    if args.apply and (not args.backup or not args.backup.is_file() or args.backup.stat().st_size == 0):
        parser.error("--apply requires --backup pointing to an existing nonempty database backup")
    result = make_plan(args.plan) if args.plan else check_plan(args.check) if args.check else apply_plan(args.apply)
    print(json.dumps(result["counts"] if args.plan else result, sort_keys=True))


if __name__ == "__main__":
    main()
