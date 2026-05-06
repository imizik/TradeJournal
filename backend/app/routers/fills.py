import json
import logging
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import not_
from sqlmodel import Session, delete, select

from app.database import get_session
from app.engine.reconstructor import FillInput, reconstruct
from app.models import Account, Fill, Trade, TradeFill, TradeTag

MANUAL_FILLS_BACKUP = Path(__file__).parent.parent.parent / "data" / "manual_fills.json"

log = logging.getLogger(__name__)

router = APIRouter()
ET = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# Background enrichment state
# ---------------------------------------------------------------------------

_enrich_state: dict = {
    "running": False,
    "done": 0,
    "total": 0,
    "current": "",
    "enriched": 0,
    "error": None,
}
_enrich_lock = threading.Lock()

_ACCOUNT_NAMES = {
    "roth_ira": "Roth IRA",
    "individual": "Individual",
    "traditional_ira": "Traditional IRA",
}
_OPTION_SIDES = {"buy_to_open", "sell_to_open", "buy_to_close", "sell_to_close"}
_STOCK_SIDES = {"buy", "sell"}


def _get_or_create_account(session: Session, last4: str, account_type: str) -> Account:
    """Look up account by last4, creating it if it doesn't exist yet."""
    normalized_last4 = last4.strip()
    if account_type == "roth_ira" and not normalized_last4:
        normalized_last4 = "8267"

    account = session.exec(select(Account).where(Account.last4 == normalized_last4)).first()
    if not account:
        account = Account(
            id=uuid.uuid4(),
            name=_ACCOUNT_NAMES.get(account_type, account_type.replace("_", " ").title()),
            type=account_type,
            last4=normalized_last4,
        )
        session.add(account)
        session.flush()
    return account


def _clear_derived_trade_data(session: Session) -> None:
    session.exec(delete(TradeTag))
    session.exec(delete(TradeFill))
    session.exec(delete(Trade))
    session.flush()


def backup_manual_fills(session: Session) -> None:
    """Serialize all manual fills to data/manual_fills.json for crash/delete recovery."""
    fills = session.exec(select(Fill).where(Fill.raw_email_id.like("manual:%"))).all()
    data = [
        {
            "id": str(f.id),
            "account_id": str(f.account_id),
            "ticker": f.ticker,
            "instrument_type": f.instrument_type,
            "side": f.side,
            "contracts": str(f.contracts),
            "price": str(f.price),
            "executed_at": f.executed_at.isoformat(),
            "raw_email_id": f.raw_email_id,
            "option_type": f.option_type,
            "strike": str(f.strike) if f.strike is not None else None,
            "expiration": f.expiration.isoformat() if f.expiration else None,
            "iv_at_fill": f.iv_at_fill,
            "delta_at_fill": f.delta_at_fill,
            "iv_rank_at_fill": f.iv_rank_at_fill,
            "underlying_price_at_fill": f.underlying_price_at_fill,
        }
        for f in fills
    ]
    MANUAL_FILLS_BACKUP.parent.mkdir(parents=True, exist_ok=True)
    MANUAL_FILLS_BACKUP.write_text(json.dumps(data, indent=2))
    log.info("Backed up %d manual fill(s) to %s", len(data), MANUAL_FILLS_BACKUP)


def restore_manual_fills_from_backup(session: Session) -> int:
    """Re-insert manual fills from backup file that are missing from the DB.

    Called on startup (covers deleted-DB scenario) and after resync-all as a
    safety net. Returns the number of fills restored.
    """
    if not MANUAL_FILLS_BACKUP.exists():
        return 0
    try:
        data = json.loads(MANUAL_FILLS_BACKUP.read_text())
    except Exception:
        log.warning("Could not read manual fills backup at %s", MANUAL_FILLS_BACKUP)
        return 0

    existing_ids = set(
        session.exec(select(Fill.raw_email_id).where(Fill.raw_email_id.like("manual:%"))).all()
    )

    restored = 0
    for item in data:
        if item["raw_email_id"] in existing_ids:
            continue
        # Ensure the account still exists (re-seeded by lifespan hook on startup)
        account_id = uuid.UUID(item["account_id"])
        if not session.get(Account, account_id):
            log.warning("Skipping manual fill %s — account %s not found", item["raw_email_id"], account_id)
            continue
        session.add(Fill(
            id=uuid.UUID(item["id"]),
            account_id=account_id,
            ticker=item["ticker"],
            instrument_type=item["instrument_type"],
            side=item["side"],
            contracts=Decimal(item["contracts"]),
            price=Decimal(item["price"]),
            executed_at=datetime.fromisoformat(item["executed_at"]),
            raw_email_id=item["raw_email_id"],
            option_type=item.get("option_type"),
            strike=Decimal(item["strike"]) if item.get("strike") else None,
            expiration=date.fromisoformat(item["expiration"]) if item.get("expiration") else None,
            iv_at_fill=item.get("iv_at_fill"),
            delta_at_fill=item.get("delta_at_fill"),
            iv_rank_at_fill=item.get("iv_rank_at_fill"),
            underlying_price_at_fill=item.get("underlying_price_at_fill"),
        ))
        restored += 1

    if restored:
        session.flush()
        log.info("Restored %d manual fill(s) from backup", restored)
    return restored


def _normalize_executed_at(executed_at: datetime) -> datetime:
    if executed_at.tzinfo is None:
        return executed_at
    return executed_at.astimezone(ET).replace(tzinfo=None)


def _import_fills_from_gmail(session: Session) -> dict[str, int]:
    from app.engine.gmail_poller import GmailPollingError, poll_new_fills

    t0 = time.monotonic()
    log.info("BEGIN /fills/import")

    known_ids: set[str] = {raw_id for raw_id in session.exec(select(Fill.raw_email_id)).all() if raw_id}
    log.info("Loaded %d known email IDs", len(known_ids))

    latest_fill = session.exec(select(Fill).order_by(Fill.executed_at.desc())).first()
    since_date: str | None = None
    if latest_fill and latest_fill.executed_at:
        d = latest_fill.executed_at.date() - timedelta(days=1)
        since_date = d.strftime("%Y/%m/%d")
    log.info("Polling Gmail since_date=%s", since_date)

    try:
        log.info("Calling Gmail poller for /fills/import")
        parsed_fills = poll_new_fills(known_ids=known_ids, since_date=since_date)
    except GmailPollingError as exc:
        log.warning("FAIL /fills/import: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    log.info("Gmail poll returned %d new fills in %.1fs", len(parsed_fills), time.monotonic() - t0)

    account_cache: dict[str, Account] = {}
    saved = 0

    for parsed_fill in parsed_fills:
        if parsed_fill.raw_email_id in known_ids:
            continue

        if parsed_fill.account_last4 not in account_cache:
            account_cache[parsed_fill.account_last4] = _get_or_create_account(
                session,
                parsed_fill.account_last4,
                parsed_fill.account_type,
            )
        account = account_cache[parsed_fill.account_last4]

        session.add(Fill(
            id=uuid.uuid4(),
            account_id=account.id,
            ticker=parsed_fill.ticker,
            instrument_type=parsed_fill.instrument_type,
            side=parsed_fill.side,
            contracts=parsed_fill.contracts,
            price=parsed_fill.price,
            executed_at=parsed_fill.executed_at,
            option_type=parsed_fill.option_type,
            strike=parsed_fill.strike,
            expiration=parsed_fill.expiration,
            raw_email_id=parsed_fill.raw_email_id,
        ))
        known_ids.add(parsed_fill.raw_email_id)
        saved += 1

    session.commit()
    log.info("Import complete: saved=%d elapsed=%.1fs", saved, time.monotonic() - t0)

    # Enrich new fills with underlying price, greeks, and indicators
    if saved > 0:
        try:
            from app.engine.enricher import enrich_fills
            new_fills = session.exec(
                select(Fill).where(Fill.underlying_price_at_fill == None)  # noqa: E711
            ).all()
            enrich_fills(list(new_fills), session)
        except Exception as exc:
            log.warning("Enrichment failed (non-fatal): %s", exc)

    log.info("END /fills/import")
    return {"saved": saved, "skipped": len(parsed_fills) - saved}


def _persist_rebuild(session: Session, anomalies_label: str) -> tuple[int, list[str]]:
    fills = session.exec(select(Fill).order_by(Fill.executed_at)).all()
    if not fills:
        return 0, []

    fill_inputs = [
        FillInput(
            id=fill.id,
            account_id=fill.account_id,
            ticker=fill.ticker,
            instrument_type=fill.instrument_type,
            side=fill.side,
            contracts=fill.contracts,
            price=fill.price,
            executed_at=fill.executed_at,
            option_type=fill.option_type,
            strike=fill.strike,
            expiration=fill.expiration,
        )
        for fill in fills
    ]
    result = reconstruct(fill_inputs)

    for trade in result.trades:
        session.add(Trade(
            id=trade.id,
            account_id=trade.account_id,
            ticker=trade.ticker,
            instrument_type=trade.instrument_type,
            option_type=trade.option_type,
            strike=trade.strike,
            expiration=trade.expiration,
            contracts=trade.contracts,
            avg_entry_premium=trade.avg_entry_premium,
            avg_exit_premium=trade.avg_exit_premium,
            total_premium_paid=trade.total_premium_paid,
            realized_pnl=trade.realized_pnl,
            pnl_pct=trade.pnl_pct,
            hold_duration_mins=trade.hold_duration_mins,
            entry_time_bucket=trade.entry_time_bucket,
            expired_worthless=trade.expired_worthless,
            opened_at=trade.opened_at,
            closed_at=trade.closed_at,
            status=trade.status,
        ))

    for trade_fill in result.trade_fills:
        session.add(TradeFill(
            trade_id=trade_fill.trade_id,
            fill_id=trade_fill.fill_id,
            role=trade_fill.role,
        ))

    if result.anomalies:
        log.warning("%s anomalies: %s", anomalies_label, result.anomalies)

    return len(result.trades), result.anomalies


class FillCreate(BaseModel):
    account_id: uuid.UUID
    ticker: str
    instrument_type: str
    side: str
    contracts: Decimal
    price: Decimal
    executed_at: datetime
    option_type: str | None = None
    strike: Decimal | None = None
    expiration: date | None = None
    raw_email_id: str | None = None


class FillCreateResponse(BaseModel):
    fill: Fill
    trades_rebuilt: int
    anomalies: list[str]


def _validated_fill_values(body: FillCreate, session: Session) -> dict[str, object]:
    account = session.get(Account, body.account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    ticker = body.ticker.strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="Ticker is required")
    if body.contracts <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than zero")
    if body.price <= 0:
        raise HTTPException(status_code=400, detail="Price must be greater than zero")

    if body.instrument_type not in {"stock", "option"}:
        raise HTTPException(status_code=400, detail="Instrument type must be stock or option")

    if body.instrument_type == "option":
        if body.side not in _OPTION_SIDES:
            raise HTTPException(status_code=400, detail="Option fills must use an options side")
        if body.option_type not in {"call", "put"}:
            raise HTTPException(status_code=400, detail="Option type must be call or put")
        if body.strike is None or body.strike <= 0:
            raise HTTPException(status_code=400, detail="Option strike must be greater than zero")
        if body.expiration is None:
            raise HTTPException(status_code=400, detail="Option expiration is required")
    else:
        if body.side not in _STOCK_SIDES:
            raise HTTPException(status_code=400, detail="Stock fills must use buy or sell")

    return {
        "account_id": account.id,
        "ticker": ticker,
        "instrument_type": body.instrument_type,
        "side": body.side,
        "contracts": body.contracts,
        "price": body.price,
        "executed_at": _normalize_executed_at(body.executed_at),
        "option_type": body.option_type if body.instrument_type == "option" else None,
        "strike": body.strike if body.instrument_type == "option" else None,
        "expiration": body.expiration if body.instrument_type == "option" else None,
    }


@router.get("", response_model=list[Fill])
async def get_fills(session: Session = Depends(get_session)):
    return session.exec(select(Fill).order_by(Fill.executed_at.desc())).all()


@router.post("", response_model=FillCreateResponse)
async def create_fill(body: FillCreate, session: Session = Depends(get_session)):
    fill_values = _validated_fill_values(body, session)
    raw_email_id = (body.raw_email_id or "").strip() or f"manual:{uuid.uuid4().hex}"
    existing = session.exec(select(Fill).where(Fill.raw_email_id == raw_email_id)).first()
    if existing:
        raise HTTPException(status_code=400, detail="A fill with that source ID already exists")

    fill = Fill(
        id=uuid.uuid4(),
        raw_email_id=raw_email_id,
        **fill_values,
    )
    session.add(fill)
    session.flush()

    _clear_derived_trade_data(session)
    trades_rebuilt, anomalies = _persist_rebuild(session, anomalies_label="/fills manual")

    session.commit()
    session.refresh(fill)
    backup_manual_fills(session)

    try:
        from app.engine.enricher import enrich_fills
        enrich_fills([fill], session)
    except Exception as exc:
        log.warning("Enrichment failed (non-fatal): %s", exc)

    return {
        "fill": fill,
        "trades_rebuilt": trades_rebuilt,
        "anomalies": anomalies,
    }


def _run_enrich_background(fill_ids: list) -> None:
    """Run enrichment in a background thread with progress tracking."""
    from app.database import engine
    from app.engine.enricher import enrich_fills

    with _enrich_lock:
        _enrich_state["running"] = True
        _enrich_state["done"] = 0
        _enrich_state["total"] = len(fill_ids)
        _enrich_state["current"] = ""
        _enrich_state["enriched"] = 0
        _enrich_state["error"] = None

    def on_progress(done: int, ticker: str) -> None:
        with _enrich_lock:
            _enrich_state["done"] = done
            _enrich_state["current"] = ticker

    try:
        with Session(engine) as bg_session:
            fills = bg_session.exec(select(Fill).where(Fill.id.in_(fill_ids))).all()
            enriched = enrich_fills(list(fills), bg_session, on_progress=on_progress)
            with _enrich_lock:
                _enrich_state["enriched"] = enriched
    except Exception as exc:
        log.exception("Background enrichment failed")
        with _enrich_lock:
            _enrich_state["error"] = str(exc)
    finally:
        with _enrich_lock:
            _enrich_state["running"] = False


@router.get("/enrich/status")
async def enrich_status():
    """Return the current enrichment job progress."""
    with _enrich_lock:
        return dict(_enrich_state)


@router.post("/enrich")
async def enrich_missing(range: str = "week", session: Session = Depends(get_session)):
    """Start background enrichment for fills missing underlying price data. range: day|week|month|all"""
    with _enrich_lock:
        if _enrich_state["running"]:
            raise HTTPException(status_code=409, detail="Enrichment already running")

    cutoff: datetime | None = None
    if range == "day":
        cutoff = datetime.utcnow() - timedelta(days=1)
    elif range == "week":
        cutoff = datetime.utcnow() - timedelta(weeks=1)
    elif range == "month":
        cutoff = datetime.utcnow() - timedelta(days=30)

    query = select(Fill.id).where(Fill.underlying_price_at_fill == None)  # noqa: E711
    if cutoff is not None:
        query = query.where(Fill.executed_at >= cutoff)

    fill_ids = session.exec(query).all()
    if not fill_ids:
        return {"started": False, "total_missing": 0}

    t = threading.Thread(target=_run_enrich_background, args=(fill_ids,), daemon=True)
    t.start()
    return {"started": True, "total_missing": len(fill_ids)}


@router.post("/import")
async def import_fills(session: Session = Depends(get_session)):
    """Poll Gmail for new fill emails and save any new fills to the DB."""
    return _import_fills_from_gmail(session)


@router.post("/resync-all")
async def resync_all(session: Session = Depends(get_session)):
    """Delete fills and derived trade data, then import from Gmail and rebuild from scratch."""
    t0 = time.monotonic()
    log.warning("BEGIN /fills/resync-all")

    _clear_derived_trade_data(session)
    session.exec(delete(Fill).where(not_(Fill.raw_email_id.like("manual:%"))))
    session.commit()
    log.warning("Cleared non-manual fills and derived trade data for /fills/resync-all")

    # Safety net: restore any manual fills missing from the DB (e.g. if DB was recreated)
    restore_manual_fills_from_backup(session)
    session.commit()

    import_result = _import_fills_from_gmail(session)
    trades_rebuilt, anomalies = _persist_rebuild(session, anomalies_label="/fills/resync-all")
    session.commit()

    log.warning(
        "END /fills/resync-all saved=%d rebuilt=%d elapsed=%.1fs",
        import_result["saved"],
        trades_rebuilt,
        time.monotonic() - t0,
    )
    return {
        "status": "ok",
        "saved": import_result["saved"],
        "skipped": import_result["skipped"],
        "trades_rebuilt": trades_rebuilt,
        "anomalies": anomalies,
    }


@router.get("/{fill_id}", response_model=Fill)
async def get_fill(fill_id: uuid.UUID, session: Session = Depends(get_session)):
    fill = session.get(Fill, fill_id)
    if not fill:
        raise HTTPException(status_code=404, detail="Fill not found")
    return fill


@router.put("/{fill_id}", response_model=FillCreateResponse)
async def update_fill(fill_id: uuid.UUID, body: FillCreate, session: Session = Depends(get_session)):
    fill = session.get(Fill, fill_id)
    if not fill:
        raise HTTPException(status_code=404, detail="Fill not found")

    fill_values = _validated_fill_values(body, session)
    for key, value in fill_values.items():
        setattr(fill, key, value)

    session.add(fill)
    session.flush()

    _clear_derived_trade_data(session)
    trades_rebuilt, anomalies = _persist_rebuild(session, anomalies_label="/fills update")

    session.commit()
    session.refresh(fill)

    try:
        from app.engine.enricher import enrich_fills
        enrich_fills([fill], session)
    except Exception as exc:
        log.warning("Enrichment failed (non-fatal): %s", exc)

    return {
        "fill": fill,
        "trades_rebuilt": trades_rebuilt,
        "anomalies": anomalies,
    }
