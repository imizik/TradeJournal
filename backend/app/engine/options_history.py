"""Open-interest changes from the immutable option snapshots (Charts C4.6)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
import json

from sqlmodel import Session, select

from app.models import OptionChainSnapshot, OptionSnapshotDay


def _contract_rows(snapshot: OptionChainSnapshot) -> list[list]:
    try:
        payload = json.loads(snapshot.data_json)
        columns = payload["columns"]
        indexes = [columns.index(name) for name in ("root", "type", "strike", "open_interest")]
        return [[row[index] for index in indexes] for row in payload["rows"]]
    except (KeyError, TypeError, ValueError, IndexError, json.JSONDecodeError):
        return []


def _snapshot_oi(rows: list[OptionChainSnapshot], expirations: set[date], root: str) -> dict[tuple, int | None]:
    values: dict[tuple, list[int | None]] = defaultdict(list)
    for snapshot in rows:
        if snapshot.expiration not in expirations:
            continue
        for contract_root, side, strike, oi in _contract_rows(snapshot):
            if contract_root == root:
                values[(snapshot.expiration.isoformat(), contract_root, side, float(strike))].append(oi)
    return {key: sum(value for value in contracts if value is not None) if all(value is not None for value in contracts) else None
            for key, contracts in values.items()}


def attach_open_interest_changes(db: Session, symbol: str, root: str, rows: list[dict], expirations: list[str]) -> None:
    """Attach stored-session changes in place; this function has no provider dependency."""
    days = db.exec(select(OptionSnapshotDay).where(OptionSnapshotDay.underlying == symbol.upper())
                   .order_by(OptionSnapshotDay.session_date.desc()).limit(2)).all()
    if len(days) < 2:
        current_day = days[0].session_date if days else None
        previous_day = None
        current_status = days[0].status if days else None
    else:
        current_day, previous_day = days[0].session_date, days[1].session_date
        current_status = days[0].status

    base = {"session": current_day.isoformat() if current_day else None,
            "previous_session": previous_day.isoformat() if previous_day else None,
            "status": "unavailable"}
    if current_status != "recorded" or len(days) < 2 or days[1].status != "recorded":
        for row in rows:
            row["oi_change"] = base
        return

    wanted = {date.fromisoformat(value) for value in expirations}
    current = _snapshot_oi(db.exec(select(OptionChainSnapshot).where(
        OptionChainSnapshot.underlying == symbol.upper(), OptionChainSnapshot.session_date == current_day)).all(), wanted, root)
    previous = _snapshot_oi(db.exec(select(OptionChainSnapshot).where(
        OptionChainSnapshot.underlying == symbol.upper(), OptionChainSnapshot.session_date == previous_day)).all(), wanted, root)

    for row in rows:
        strike = float(row["strike"])
        deltas = {}
        for name, side in (("calls", "C"), ("puts", "P")):
            current_keys = {key for key in current if key[2] == side and key[3] == strike}
            previous_keys = {key for key in previous if key[2] == side and key[3] == strike}
            # Both snapshots must contain the same contracts: either an added or a
            # disappeared contract has an unknown baseline/current OI, not a zero.
            if not current_keys or current_keys != previous_keys or any(
                current[key] is None or previous[key] is None for key in current_keys
            ):
                deltas[name] = None
            else:
                deltas[name] = sum(current[key] - previous[key] for key in current_keys)
        row["oi_change"] = {**base, "status": "ready" if any(v is not None for v in deltas.values()) else "unavailable", **deltas}
