"""The journal on the chart (C3.1 trade card, C3.2 position lines): units, FIFO
open lots, labeled missing/stale metrics, and option premiums never offered as
underlying prices."""

from datetime import date, datetime
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.database import get_session
from app.engine import chart_journal
from app.engine.chart_journal import open_lots
from app.engine.metric_versions import CONTEXT_VERSION, PATH_VERSION
from app.engine.quotes import OptionQuoteResult
from app.engine.trade_path import market_inputs_fingerprint, trade_inputs_fingerprint
from app.models import Account, Fill, FillMarketContext, Trade, TradeFill, TradePathMetrics
from app.routers import charts
from app.routers.fills import _rebuild_trades

ACCOUNT = UUID(int=1)
OTHER = UUID(int=2)
LATER = date(2099, 1, 15)


def fill(n, ticker, side, qty, price, at, account=ACCOUNT, **option):
    kind = "option" if option else "stock"
    return Fill(id=UUID(int=n), account_id=account, ticker=ticker, instrument_type=kind, side=side, contracts=qty, price=price,
                executed_at=datetime.fromisoformat(at), raw_email_id=f"journal:{n}", **option)


CALL = {"option_type": "call", "strike": 900, "expiration": LATER}
PUT = {"option_type": "put", "strike": 880, "expiration": LATER}
CLOSED_CALL = {"option_type": "call", "strike": 905, "expiration": date(2026, 7, 17)}


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Account(id=ACCOUNT, name="Roth", type="roth_ira", last4="8267"))
        session.add(Account(id=OTHER, name="Individual", type="individual", last4="1111"))
        session.add_all([
            # Stock: scale in 10 @ 100, 10 @ 110; out 5 @ 120 (FIFO from the first lot); in 5 @ 90.
            fill(1, "NVDA", "buy", 10, 100, "2026-09-01T09:45"),
            fill(2, "NVDA", "buy", 10, 110, "2026-09-02T10:00"),
            fill(3, "NVDA", "sell", 5, 120, "2026-09-03T11:00"),
            fill(4, "NVDA", "buy", 5, 90, "2026-09-04T12:00"),
            # The same stock in another account is its own position.
            fill(5, "NVDA", "buy", 3, 105, "2026-09-02T10:05", account=OTHER),
            # An open call with enrichment, partly closed; an open put with none at all.
            fill(6, "NVDA", "buy_to_open", 2, 310, "2026-09-05T09:42", **CALL),
            fill(7, "NVDA", "sell_to_close", 1, 420, "2026-09-05T10:15", **CALL),
            fill(8, "NVDA", "buy_to_open", 1, 200, "2026-09-05T11:00", **PUT),
            # A closed call months ago, for the card.
            fill(9, "NVDA", "buy_to_open", 1, 500, "2026-07-14T09:40", **CLOSED_CALL),
            fill(10, "NVDA", "sell_to_close", 1, 650, "2026-07-14T10:20", **CLOSED_CALL),
            # A close with nothing to close: no trade.
            fill(11, "AMD", "sell", 1, 150, "2026-09-05T09:31"),
        ])
        session.commit()
        _rebuild_trades(session, "test")
        session.add(FillMarketContext(fill_id=UUID(int=6), data_source="alpaca_sip", fetched_at=datetime(2026, 9, 5, 14),
                                      calculation_version=CONTEXT_VERSION, entry_context_as_of=datetime(2026, 9, 5, 9, 42),
                                      entry_underlying_price=901.25, entry_vs_vwap_pct=0.42, rvol_time_adjusted=1.8,
                                      is_chase_entry=0, is_vwap_reclaim=1))
        session.add(FillMarketContext(fill_id=UUID(int=9), data_source="alpaca_iex", fetched_at=datetime(2026, 7, 14, 14),
                                      calculation_version="entry-context-v1", entry_underlying_price=880.5))
        session.commit()
        yield session
    engine.dispose()


@pytest.fixture
def client(db, monkeypatch):
    app = FastAPI()
    app.include_router(charts.router, prefix="/charts")
    app.dependency_overrides[get_session] = lambda: db
    with TestClient(app) as test_client:
        yield test_client


def trade_for(db, fill_id):
    return db.get(Trade, db.exec(select(TradeFill).where(TradeFill.fill_id == UUID(int=fill_id))).one().trade_id)


def test_open_lots_are_first_in_first_out_and_short_runs_the_other_way():
    rows = [{"id": 1, "side": "buy", "contracts": 10, "price": 100, "executed_at": datetime(2026, 9, 1)},
            {"id": 2, "side": "buy", "contracts": 10, "price": 110, "executed_at": datetime(2026, 9, 2)},
            {"id": 3, "side": "sell", "contracts": 15, "price": 120, "executed_at": datetime(2026, 9, 3)}]
    assert open_lots(rows) == {"open": 5.0, "avg_cost": 110.0, "realized": 250.0, "direction": "long"}
    short = [{"id": 1, "side": "sell_to_open", "contracts": 2, "price": 3, "executed_at": datetime(2026, 9, 1)},
             {"id": 2, "side": "buy_to_close", "contracts": 1, "price": 1, "executed_at": datetime(2026, 9, 1)}]
    assert open_lots(short) == {"open": 1.0, "avg_cost": 3.0, "realized": 2.0, "direction": "short"}
    # A close stamped the same minute as its open still closes it (opens sort first).
    tied = [{"id": 9, "side": "sell", "contracts": 1, "price": 5, "executed_at": datetime(2026, 9, 1)},
            {"id": 1, "side": "buy", "contracts": 1, "price": 4, "executed_at": datetime(2026, 9, 1)}]
    assert open_lots(tied)["open"] == 0


def test_stock_scale_ins_and_outs_draw_the_remaining_shares_share_weighted_average(db):
    lines = chart_journal.positions(db, "NVDA")
    stock = [p for p in lines if p["instrument"] == "stock"]
    assert [(p["account"], p["open"]) for p in stock] == [("Roth", 20.0), ("Individual", 3.0)]
    roth = stock[0]
    # Open lots: 5 @ 100 (the first lot after selling 5), 10 @ 110, 5 @ 90 -> 2,050 / 20.
    assert roth["avg_cost"] == pytest.approx(102.5) and roth["line"] == roth["avg_cost"]
    assert roth["realized"] == pytest.approx(100.0)  # 5 x (120 - 100)
    assert roth["unit"] == "share"
    assert len(roth["exits"]) == 1 and roth["exits"][0] == chart_journal.stamp(datetime(2026, 9, 3, 11))


def test_option_lines_use_the_observed_underlying_never_the_premium(db):
    lines = {p["contract"]: p for p in chart_journal.positions(db, "NVDA") if p["instrument"] == "option"}
    call = lines["NVDA 1/15/99 900C"]
    assert call["open"] == 1 and call["avg_cost"] == pytest.approx(310) and call["unit"] == "contract"
    assert call["line"] == 901.25 and call["underlying_at_entry"]["source"] == "alpaca_sip"
    assert call["line"] != call["avg_cost"]
    # No enrichment and no fill-time underlying: no line at all, not the premium.
    put = lines["NVDA 1/15/99 880P"]
    assert put["line"] is None and put["underlying_at_entry"] is None and put["avg_cost"] == 200.0
    # Closed trades are not positions.
    assert "NVDA 7/17/26 905C" not in lines


def test_fill_card_labels_units_context_and_missing_or_stale_metrics(client, db):
    card = client.get(f"/charts/journal/fills/{UUID(int=7)}").json()
    assert card["fill"]["side"] == "sell_to_close"
    trade = card["trade"]
    assert trade["contract"] == "NVDA 1/15/99 900C" and trade["status"] == "open" and trade["unit"] == "contract"
    assert "not underlying prices" in trade["price_note"] and "per contract" in trade["price_note"]
    assert [f["role"] for f in card["fills"]] == ["entry", "exit"]
    assert card["fills"][0]["underlying"]["price"] == 901.25
    assert card["fills"][1]["underlying"] is None  # never the premium in its place
    assert card["position"] == {"open": 1.0, "avg_cost": pytest.approx(310), "realized": pytest.approx(110.0)}
    assert card["path"]["state"] == "missing" and "closes" in card["path"]["note"]
    assert card["context"]["state"] == "current" and card["context"]["entry_vs_vwap_pct"] == 0.42
    assert card["context"]["flags"]["is_vwap_reclaim"] is True and card["context"]["flags"]["is_trend_aligned"] is None

    closed = trade_for(db, 9)
    fills = db.exec(select(Fill).where(Fill.id.in_([UUID(int=9), UUID(int=10)]))).all()
    contexts = {str(c.fill_id): c for c in db.exec(select(FillMarketContext))}
    db.add(TradePathMetrics(trade_id=closed.id, data_source="alpaca_sip", fetched_at=datetime(2026, 7, 15), calculation_version=PATH_VERSION,
                            inputs_fingerprint=trade_inputs_fingerprint(closed, fills), market_inputs_fingerprint=market_inputs_fingerprint(fills, contexts),
                            underlying_mfe_pct=1.2, underlying_mae_pct=0.4, option_exit_efficiency=61.0))
    db.commit()
    card = client.get(f"/charts/journal/trades/{closed.id}").json()
    assert card["fill"] is None and card["trade"]["realized_pnl"] == pytest.approx(150) and card["position"] is None
    assert card["trade"]["pnl_pct"] == pytest.approx(30.0)
    assert card["path"]["state"] == "current" and card["path"]["underlying_mfe_pct"] == 1.2
    # Old calculation and a single-venue source are both said, not hidden.
    assert card["context"]["state"] == "stale" and card["context"]["single_venue"] is True and "IEX" in card["context"]["note"]
    # An edited fill makes the stored path stale.
    db.get(Fill, UUID(int=10)).price = 660
    db.commit()
    assert client.get(f"/charts/journal/trades/{closed.id}").json()["path"]["state"] == "stale"


def test_orphan_fill_and_missing_rows(client):
    card = client.get(f"/charts/journal/fills/{UUID(int=11)}").json()
    assert card["trade"] is None and "not part of a reconstructed trade" in card["note"]
    assert client.get(f"/charts/journal/fills/{UUID(int=99)}").status_code == 404
    assert client.get(f"/charts/journal/trades/{UUID(int=99)}").status_code == 404


def test_option_mark_reports_its_age_and_open_pnl(client, db, monkeypatch):
    call = trade_for(db, 6)
    monkeypatch.setattr(charts, "option_mark", lambda req: (OptionQuoteResult(bid=3.9, ask=4.1, mid=4.0, last_price=4.05, provider="tradier"), 1789000000.0))
    mark = client.get(f"/charts/journal/trades/{call.id}/mark").json()
    assert mark["mark"] == 4.0 and mark["mark_per_contract"] == 400 and mark["basis"] == "mid" and mark["quoted_at"] == 1789000000
    assert mark["open_pnl"] == pytest.approx(400 - 310)  # per share x 100 vs per contract
    monkeypatch.setattr(charts, "option_mark", lambda req: (OptionQuoteResult(provider="tradier"), None))
    assert client.get(f"/charts/journal/trades/{call.id}/mark").json() == {
        "mark": None, "mark_per_contract": None, "basis": None, "bid": None, "ask": None, "last": None, "provider": "tradier", "quoted_at": None, "open_pnl": None}
    # A stock trade has no option mark; its open P&L comes from the chart's own price.
    stock = trade_for(db, 1)
    assert client.get(f"/charts/journal/trades/{stock.id}/mark").status_code == 422
