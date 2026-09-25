import json
import uuid
from datetime import date, datetime

from sqlmodel import Session, SQLModel, create_engine

from app.engine import alpaca
from app.engine.jobs import _alpaca_fill_ids
from app.models import Account, Fill, FillMarketContext


def _bar(day: str) -> dict:
    return {"t": f"{day}T04:00:00Z", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}


def test_daily_cache_must_cover_latest_completed_bar(tmp_path, monkeypatch):
    cache_file = tmp_path / "NVDA.json"
    cache_file.write_text(json.dumps([_bar("2026-05-07")]))
    monkeypatch.setattr(alpaca, "_latest_completed_daily_bar_date", lambda: date(2026, 5, 15))

    assert alpaca._daily_cache_covers(cache_file, date(2026, 5, 17)) is False

    cache_file.write_text(json.dumps([_bar("2026-05-15")]))

    assert alpaca._daily_cache_covers(cache_file, date(2026, 5, 17)) is True



def test_daily_cache_written_for_a_shorter_window_does_not_answer_a_longer_one(tmp_path, monkeypatch):
    # A 90-day cache from market packets must not satisfy a year-long
    # backtest's request; a front gap of a long weekend still counts as covered.
    cache_file = tmp_path / "MU.json"
    cache_file.write_text(json.dumps([_bar("2026-02-17"), _bar("2026-05-15")]))
    monkeypatch.setattr(alpaca, "_latest_completed_daily_bar_date", lambda: date(2026, 5, 15))

    assert alpaca._daily_cache_covers(cache_file, date(2026, 5, 15), date(2025, 5, 15)) is False
    assert alpaca._daily_cache_covers(cache_file, date(2026, 5, 15), date(2026, 2, 14)) is True
    assert alpaca._daily_cache_covers(cache_file, date(2026, 5, 15)) is True



def test_fetch_daily_bars_refetches_when_the_cache_starts_too_late(tmp_path, monkeypatch):
    cache_file = tmp_path / "MU.json"
    cache_file.write_text(json.dumps([_bar("2026-02-17"), _bar("2026-05-15")]))
    monkeypatch.setattr(alpaca, "_latest_completed_daily_bar_date", lambda: date(2026, 5, 15))
    monkeypatch.setattr(alpaca, "_daily_cache_path", lambda ticker: cache_file)
    requests = []

    def fake_fetch(path, params):
        requests.append(params["start"])
        return {"MU": [_bar("2025-05-15"), _bar("2026-05-15")]}

    monkeypatch.setattr(alpaca, "_fetch_all_pages", fake_fetch)

    assert len(alpaca.fetch_daily_bars(["MU"], date(2026, 2, 16), date(2026, 5, 15))["MU"]) == 2
    assert requests == []
    alpaca.fetch_daily_bars(["MU"], date(2025, 5, 15), date(2026, 5, 15))
    assert requests == ["2025-05-15"]


def test_alpaca_fill_selection_retries_partial_context_rows():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        account = Account(id=uuid.uuid4(), name="Roth IRA", type="roth_ira", last4="8267")
        complete_fill = Fill(
            id=uuid.uuid4(),
            account_id=account.id,
            ticker="AMD",
            instrument_type="option",
            side="buy_to_open",
            contracts=1,
            price=1,
            executed_at=datetime(2026, 5, 15, 10, 0),
            raw_email_id="complete",
        )
        partial_fill = Fill(
            id=uuid.uuid4(),
            account_id=account.id,
            ticker="NVDA",
            instrument_type="option",
            side="buy_to_open",
            contracts=1,
            price=1,
            executed_at=datetime(2026, 5, 15, 11, 0),
            raw_email_id="partial",
        )
        session.add(account)
        session.add(complete_fill)
        session.add(partial_fill)
        session.add(
            FillMarketContext(
                fill_id=complete_fill.id,
                data_source="alpaca_iex",
                fetched_at=datetime.utcnow(),
                entry_underlying_price=150,
                entry_vwap=149,
                entry_rsi_14=50,
                entry_ema_9=100,
                entry_ema_20=95,
            )
        )
        session.add(
            FillMarketContext(
                fill_id=partial_fill.id,
                data_source="alpaca_iex",
                fetched_at=datetime.utcnow(),
                entry_underlying_price=228,
                entry_rsi_14=None,
                entry_ema_9=None,
                entry_ema_20=None,
            )
        )
        session.commit()

        partial_fill_id = partial_fill.id
        complete_fill_id = complete_fill.id
        selected = set(_alpaca_fill_ids(session, "all", force=False))

    assert partial_fill_id in selected
    assert complete_fill_id not in selected
