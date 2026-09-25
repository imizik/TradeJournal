import json
import uuid
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.engine.email_parser import ParsedFill
from app.engine.reconstructor import reconstruct
from app.models import Account, DailyReviewRecord, Fill, FillMarketContext, Trade, TradeFill, TradePathMetrics
from app.routers.fills import _normalize_executed_at
from app.routers.fills import _import_fills_from_gmail
from scripts import repair_gmail_fill_times as repair

ET = ZoneInfo("America/New_York")


def _source_fill(raw_id, side, price, minute):
    return ParsedFill(
        ticker="AAPL", side=side, contracts=Decimal("1"), price=Decimal(price),
        executed_at=datetime(2026, 7, 14, 9, minute, tzinfo=ET),
        instrument_type="stock", raw_email_id=raw_id,
        account_last4="8267", account_type="roth_ira",
    )


def _database():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    return engine


def test_import_boundary_keeps_new_york_wall_clock_before_database_write():
    aware = datetime(2026, 7, 14, 9, 30, tzinfo=ET)
    assert _normalize_executed_at(aware) == datetime(2026, 7, 14, 9, 30)
    assert _normalize_executed_at(datetime(2026, 1, 15, 9, 30)) == datetime(2026, 1, 15, 9, 30)


def test_gmail_import_persists_new_york_clock(monkeypatch):
    engine = _database()
    parsed = _source_fill("gmail:new", "buy", "100", 30)
    monkeypatch.setattr("app.engine.gmail_poller.poll_new_fills", lambda **_kw: [parsed])
    with Session(engine) as session:
        result = _import_fills_from_gmail(session, start_enrichment=False)
        stored = session.exec(select(Fill)).one()
    assert result["saved"] == 1
    assert stored.executed_at == datetime(2026, 7, 14, 9, 30)
    assert stored.executed_at.tzinfo is None


def test_plan_classifies_mixed_correct_and_utc_clock_rows(monkeypatch, tmp_path):
    engine = _database()
    account = Account(id=uuid.uuid4(), name="Roth IRA", type="roth_ira", last4="8267")
    source = {
        "gmail:correct": _source_fill("gmail:correct", "buy", "100", 30),
        "gmail:shifted": _source_fill("gmail:shifted", "sell", "101", 35),
    }
    with Session(engine) as session:
        session.add(account)
        session.add(Fill(
            account_id=account.id, ticker="AAPL", instrument_type="stock",
            side="buy", contracts=1, price=100,
            executed_at=datetime(2026, 7, 14, 9, 30),
            raw_email_id="gmail:correct",
        ))
        session.add(Fill(
            account_id=account.id, ticker="AAPL", instrument_type="stock",
            side="sell", contracts=1, price=101,
            executed_at=datetime(2026, 7, 14, 13, 35),
            raw_email_id="gmail:shifted",
        ))
        session.commit()

    monkeypatch.setattr(repair, "engine", engine)
    monkeypatch.setattr(repair, "_get_service", lambda: object())
    monkeypatch.setattr(repair, "_source", lambda _service, mid: (source[mid], "hash-" + mid))
    plan = repair.make_plan(tmp_path / "plan.json")

    assert plan["counts"] == {"correct": 1, "utc_clock": 1}
    assert (tmp_path / "plan.json").stat().st_mode & 0o777 == 0o600


def test_apply_repairs_time_and_invalidates_derived_context_without_losing_notes(monkeypatch, tmp_path):
    engine = _database()
    account = Account(id=uuid.uuid4(), name="Roth IRA", type="roth_ira", last4="8267")
    source = {
        "gmail:buy": _source_fill("gmail:buy", "buy", "100", 30),
        "gmail:sell": _source_fill("gmail:sell", "sell", "101", 35),
    }
    with Session(engine) as session:
        session.add(account)
        fills = []
        for mid, side, price, minute in (
            ("gmail:buy", "buy", 100, 30), ("gmail:sell", "sell", 101, 35)
        ):
            fill = Fill(
                account_id=account.id, ticker="AAPL", instrument_type="stock",
                side=side, contracts=1, price=price,
                executed_at=datetime(2026, 7, 14, 13, minute),
                raw_email_id=mid, underlying_price_at_fill=999,
            )
            session.add(fill)
            fills.append(fill)
        session.flush()
        result = reconstruct([repair._fill_input(f) for f in fills], today=datetime(2026, 7, 15).date())
        trade = Trade(**vars(result.trades[0]), ai_review='{"note":"keep"}')
        session.add(trade)
        for link in result.trade_fills:
            session.add(TradeFill(trade_id=link.trade_id, fill_id=link.fill_id, role=link.role))
        session.add(FillMarketContext(
            fill_id=fills[0].id, data_source="alpaca_iex", fetched_at=datetime.now(),
            entry_underlying_price=999,
        ))
        session.add(TradePathMetrics(
            trade_id=trade.id, data_source="alpaca_iex", fetched_at=datetime.now(),
            inputs_fingerprint="stale",
        ))
        session.add(DailyReviewRecord(
            day=datetime(2026, 7, 14).date(),
            review_json='{"summary":"keep this saved analysis"}', trade_count=1,
        ))
        session.commit()
        fill_ids = [f.id for f in fills]
        trade_id = trade.id

    monkeypatch.setattr(repair, "engine", engine)
    monkeypatch.setattr(repair, "_get_service", lambda: object())
    monkeypatch.setattr(repair, "_source", lambda _service, mid: (source[mid], "hash-" + mid))
    plan = {
        "format": 1, "database": engine.url.render_as_string(hide_password=True),
        "rows": [],
    }
    for mid, fill_id, minute in zip(("gmail:buy", "gmail:sell"), fill_ids, (30, 35)):
        plan["rows"].append({
            "id": str(fill_id), "raw_email_id": mid, "ticker": "AAPL",
            "stored_at": datetime(2026, 7, 14, 13, minute).isoformat(),
            "source_at_et": datetime(2026, 7, 14, 9, minute).isoformat(),
            "source_sha256": "hash-" + mid, "status": "utc_clock",
        })
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))

    preflight = repair.check_plan(path)
    assert preflight["candidate_fills"] == 2
    assert preflight["economic_signature_unchanged"] is True
    assert repair.apply_plan(path) == {"changed_fills": 2, "changed_trades": 1}
    with Session(engine) as session:
        repaired = session.exec(select(Fill).order_by(Fill.executed_at)).all()
        assert [f.executed_at.hour for f in repaired] == [9, 9]
        assert all(f.underlying_price_at_fill is None for f in repaired)
        assert session.exec(select(FillMarketContext)).all() == []
        assert session.exec(select(TradePathMetrics)).all() == []
        saved = session.get(Trade, trade_id)
        assert saved.opened_at == datetime(2026, 7, 14, 9, 30)
        assert saved.entry_time_bucket == "open"
        assert json.loads(saved.ai_review) == {"note": "keep", "source_data_stale": True}
        daily = session.exec(select(DailyReviewRecord)).one()
        assert json.loads(daily.review_json) == {
            "summary": "keep this saved analysis", "source_data_stale": True,
        }


def test_apply_rejects_changed_source_before_writing(monkeypatch, tmp_path):
    engine = _database()
    monkeypatch.setattr(repair, "engine", engine)
    monkeypatch.setattr(repair, "_get_service", lambda: object())
    monkeypatch.setattr(
        repair, "_source",
        lambda _service, mid: (_source_fill(mid, "buy", "100", 30), "different"),
    )
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({
        "format": 1, "database": engine.url.render_as_string(hide_password=True),
        "rows": [{
            "id": str(uuid.uuid4()), "raw_email_id": "gmail:buy",
            "stored_at": "2026-07-14T13:30:00", "source_at_et": "2026-07-14T09:30:00",
            "source_sha256": "original", "status": "utc_clock",
        }],
    }))
    with pytest.raises(ValueError, match="Source changed"):
        repair.apply_plan(path)
