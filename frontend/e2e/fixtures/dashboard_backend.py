"""Offline quotes for the existing seeded browser harness, never the real app."""
from pathlib import Path
from datetime import datetime
import asyncio
import os

# A mistaken app target must fail closed rather than put fixture prices on a
# real journal. The Playwright config recreates this database every invocation.
expected = Path(__file__).resolve().parents[3] / "backend/data/e2e_seed.db"
if os.environ.get("DATABASE_URL") != f"sqlite:///{expected}":
    raise RuntimeError("Browser quote fixture requires the disposable e2e database")

from fastapi import HTTPException
from starlette.responses import JSONResponse
from app.engine.quotes import OptionQuoteResult
from app.main import app as core_app
from app.routers import quotes

state = "ready"


@core_app.post("/__test/scanner-amzn", include_in_schema=False)
def scanner_amzn():
    """Monday's AMZN rules paper trade: 10:10 bar close, 10:11:10 entry, 10:55:54 target exit."""
    import json
    from datetime import date, datetime
    from sqlmodel import Session, select
    from app.database import engine
    from app.models import ScannerCandidate, ScannerEvent

    with Session(engine) as db:
        if db.exec(select(ScannerCandidate).where(ScannerCandidate.symbol == "AMZN", ScannerCandidate.session_date == date(2026, 10, 19))).first():
            return {"seeded": False}
        contract = {"symbol": "AMZN261023C00220000", "expiration": "2026-10-23", "option_type": "call", "strike": 220.0,
                    "delta": 0.35, "bid": 1.75, "ask": 1.80, "multiplier": 100}
        c = ScannerCandidate(scanner_version="s1-v1", params_hash="0" * 64, session_date=date(2026, 10, 19), symbol="AMZN", setup="orb",
                             direction="long", bar_start=datetime(2026, 10, 19, 14, 5), bar_end=datetime(2026, 10, 19, 14, 10),
                             detected_at=datetime(2026, 10, 19, 14, 10, 31), expires_at=datetime(2026, 10, 19, 14, 20), stop=219.10,
                             target=222.40, facts_json="{}", contract_json=json.dumps(contract), source="e2e")
        db.add(c)
        db.flush()
        for kind, at, data in (("entry", datetime(2026, 10, 19, 14, 11, 10), {"ask": 1.80, "bid": 1.75}),
                               ("exit_intent", datetime(2026, 10, 19, 14, 55, 30), {"reason": "target"}),
                               ("exit", datetime(2026, 10, 19, 14, 55, 54), {"bid": 4.70, "ask": 4.80, "reason": "target", "pnl": 288.70,
                                                                             "pnl_2x_spread": 268.70, "return_on_premium": 1.6})):
            db.add(ScannerEvent(candidate_id=c.id, key=kind, event_type=kind, effective_at=at, recorded_at=at, data_json=json.dumps(data)))
        db.commit()
    return {"seeded": True}


@core_app.post("/__test/radar-seed", include_in_schema=False)
def radar_seed(news: str = "found"):
    """A fresh Radar file: three passes on 2026-10-20, the sample event with its one revision, and its news checks."""
    import json
    from app.engine.radar_store import RadarStore

    path = Path(os.environ["RADAR_STORE"])
    path.unlink(missing_ok=True)
    store = RadarStore(path)
    sample = json.loads((Path(__file__).resolve().parents[3] / "backend/tests/fixtures/radar/sample_event.json").read_text())
    from app.engine.radar_store import load_universe

    # Quotes for every tracked symbol but one (so one is missing); the 14:57 pass is the "15 minutes earlier" reading.
    symbols = [row["symbol"] for row in load_universe()["symbols"] if row["symbol"] != "WULF"]
    day = {"SPY": -1.4, "QQQ": -1.9, "SMH": -4.0, "COHR": -13.3, "AAOI": -13.1, "ALAB": -11.3, "SPOT": 10.6, "LCID": 7.3}
    for minute in ("14:57", "15:10", "15:11", "15:12"):
        stamp = f"2026-10-20T{minute}:00.000Z"
        pass_id = store.append_pass(
            {"session_date": "2026-10-20", "started_at": stamp, "finished_at": stamp, "universe_version": "radar-universe-v2",
             "status": "ok", "symbols_requested": 169, "symbols_returned": 168, "unmatched": ["ZZZ"], "requests_used": 4,
             "error": None, "skip_reason": None},
            [{"symbol": s, "last": round(100 * (1 + (day.get(s, ((i * 7) % 21 - 10) / 10)) / 100) * (1.002 if minute == "14:57" else 1), 4),
              "prev_close": 100.0, "open": 110.0 if s == "SPOT" else 100.0, "high": None, "low": None, "volume": 1000, "bid": None,
              "ask": None, "trade_time_ms": datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp() * 1000, "retrieved_at": stamp} for i, s in enumerate(symbols)] if minute == "15:12" or minute == "14:57" else [])
    store.append_event(sample["event"])
    store.append_revision(sample["revisions"][0])
    checks = sample["news_checks"] if news == "found" else [
        {"event_id": sample["event"]["event_id"], "checked_at": "2026-10-20T15:13:05.000Z", "status": news, "headlines": []}]
    for check in checks:
        store.append_news(check)
    return {"seeded": True}


@core_app.post("/__test/exit-habits-seed", include_in_schema=False)
def exit_habits_seed():
    """Phone alerts on the seeded Roth trades: NVDA closed within 15 minutes, TSLA left to expire (under a later
    alert kind), AAPL trimmed with no mark. Each is anchored like the live alerts, in its first entry fill."""
    from datetime import UTC, timedelta
    from sqlmodel import Session, select
    from app.database import engine
    from app.engine.chart_journal import contract_label
    from app.engine.chart_math import ET
    from app.models import Account, Fill, PositionAlert, Trade

    with Session(engine) as db:
        if db.exec(select(PositionAlert)).first():
            return {"seeded": False}
        roth = db.exec(select(Account.id).where(Account.type == "roth_ira")).one()
        for ticker, kind, minutes, mark, delivery in (("NVDA", "giveback", -5, 650.0, "sent"), ("TSLA", "hold_hour", 5, 120.0, "unknown"),
                                                      ("AAPL", "expiry_first", -10, None, "sent")):
            fills = db.exec(select(Fill).where(Fill.ticker == ticker, Fill.account_id == roth).order_by(Fill.executed_at)).all()
            entries = [f for f in fills if f.side == "buy_to_open"]
            exits = [f for f in fills if f.side == "sell_to_close"]
            at = (exits[0].executed_at if exits else entries[-1].executed_at) + timedelta(minutes=minutes)
            trade = db.exec(select(Trade).where(Trade.ticker == ticker, Trade.account_id == roth)).one()
            db.add(PositionAlert(account_id=roth, source_key=entries[0].raw_email_id, kind=kind, generation=0, trade_id=trade.id,
                                 contract=contract_label(ticker, "option", trade.option_type, trade.strike, trade.expiration),
                                 contracts=sum(float(f.contracts) for f in entries), avg_cost=float(trade.avg_entry_premium), mark=mark,
                                 detected_at=at.replace(tzinfo=ET).astimezone(UTC).replace(tzinfo=None), delivery=delivery))
        db.commit()
    return {"seeded": True}


@core_app.post("/__test/dashboard-state", include_in_schema=False)
def dashboard_state(value: str):
    global state
    if value not in {"ready", "quotes_unavailable", "quotes_error", "journal_error", "slow", "slow_stats"}:
        raise HTTPException(400, "Invalid fixture state")
    state = value
    return {"state": state}


async def app(scope, receive, send):
    # Forward untouched ASGI messages for every other route, including chart
    # streams and lifespan. Fault injection must not alter their transport.
    if scope["type"] == "http" and scope["path"] == "/trades" and scope["method"] == "GET":
        if state == "journal_error":
            await JSONResponse({"detail": "Fixture journal unavailable"}, status_code=503)(scope, receive, send)
            return
        if state == "slow":
            await asyncio.sleep(2)
    if scope["type"] == "http" and scope["path"] == "/stats" and scope["method"] == "GET" and state == "slow_stats":
        await asyncio.sleep(2)
    await core_app(scope, receive, send)


def stock_quotes(tickers):
    if state == "quotes_error":
        raise HTTPException(503, "Fixture quotes unavailable")
    prices = {"RNXT": 1.20, "AAPL": 240.00}
    return {ticker: prices.get(ticker) if state != "quotes_unavailable" else None for ticker in tickers}


def option_quotes(requests):
    if state == "quotes_error":
        raise HTTPException(503, "Fixture quotes unavailable")
    if state == "quotes_unavailable":
        return [OptionQuoteResult() for _ in requests]
    return [OptionQuoteResult(last_price=3.0, bid=2.9, ask=3.1, mid=3.0) for _ in requests]


quotes.get_stock_quotes = stock_quotes
quotes.get_option_quotes = option_quotes

# Loaded only behind the disposable database guard above, never by app.main.
from e2e.fixtures.day_journal_review import install as install_day_journal_fixture
install_day_journal_fixture(core_app)
