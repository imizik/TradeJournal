"""At risk now (``app/engine/exposure.py``, ``GET /copilot/exposure``): the open long options' premium still paid, first
in first out, against the usual day's premium bought; Webull and stocks left out; the rendered line; unavailable on a
failing read; the route's gates. In-memory journal, no network."""
from datetime import date, datetime, timedelta
import itertools
from uuid import UUID

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.engine import exposure
from app.engine.chart_math import ET
from app.models import Account, Fill
from app.routers.fills import _rebuild_trades
from tests.test_browser_access import boundary, signin  # noqa: F401  (the shared access fixture)

ROTH, WEBULL = UUID(int=1), UUID(int=2)
AT = datetime(2026, 11, 6, 9, 0, tzinfo=ET)
_ids = itertools.count(100)


def fill(account, ticker, side, contracts, price, when, instrument="option", option_type="call"):
    n = next(_ids)
    extra = {"option_type": option_type, "strike": 100, "expiration": date(2026, 12, 18)} if instrument == "option" else {}
    return Fill(id=UUID(int=n), account_id=account, ticker=ticker, instrument_type=instrument, side=side, contracts=contracts,
                price=price, executed_at=when, raw_email_id=f"gmail:{n}", **extra)


@pytest.fixture
def journal():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Account(id=ROTH, name="Robinhood Roth 8267", type="roth_ira", last4="8267", broker="robinhood"))
        db.add(Account(id=WEBULL, name="Webull 4242", type="individual", last4="4242", broker="webull"))
        db.commit()
    yield engine
    engine.dispose()


def add(engine, *fills, rebuild=True):
    with Session(engine) as db:
        db.add_all(fills)
        db.commit()
        if rebuild:
            _rebuild_trades(db, "test")
            db.commit()


def test_open_long_options_cost_first_in_first_out_without_webull_stocks_or_closed_positions(journal):
    mon = datetime(2026, 11, 2, 10, 0)
    add(journal,
        # 2 @ $300, add 2 @ $200, sell 3: one contract of the add is still open, $200
        fill(ROTH, "NBIS", "buy_to_open", 2, 300, mon), fill(ROTH, "NBIS", "buy_to_open", 2, 200, mon + timedelta(minutes=5)),
        fill(ROTH, "NBIS", "sell_to_close", 3, 400, mon + timedelta(minutes=10)),
        fill(ROTH, "AMD", "buy_to_open", 1, 500, mon, option_type="put"),  # still open, $500
        fill(ROTH, "APLD", "buy_to_open", 3, 100, mon), fill(ROTH, "APLD", "sell_to_close", 3, 150, mon + timedelta(hours=1)),  # closed
        fill(ROTH, "CRWV", "buy", 10, 120, mon, instrument="stock"),  # a long hold, not premium
        fill(ROTH, "SPY", "sell_to_open", 1, 250, mon),  # a short receives premium
        fill(WEBULL, "TSLA", "buy_to_open", 5, 1000, mon))  # dormant
    with Session(journal) as db:
        out = exposure.now(db, AT)
    assert out["state"] == "ok" and out["at_risk_usd"] == 700.0 and out["positions"] == 2
    assert out["usual_day_usd"] is None and out["sample_days"] == 1
    assert out["as_of"] == "2026-11-06T09:00:00-05:00"
    assert exposure.line(out) == "At risk now: $700 in 2 options"


def test_the_usual_day_is_the_median_of_the_last_60_entry_days_before_today(journal):
    start = datetime(2026, 6, 1, 10, 0)
    days = [start + timedelta(days=i) for i in range(70)]  # 70 entry days; the oldest 10 fall outside the window
    rows = [fill(ROTH, "NBIS", "buy_to_open", 1, 10_000 if i < 10 else 100 * i, day) for i, day in enumerate(days)]
    rows += [fill(ROTH, "NBIS", "buy_to_open", 1, 50, days[-1] + timedelta(hours=1)),  # same day: summed
             fill(WEBULL, "TSLA", "buy_to_open", 1, 99_999, days[-1]),  # dormant
             fill(ROTH, "CRWV", "buy", 100, 120, days[-1], instrument="stock"),
             fill(ROTH, "SPY", "sell_to_open", 1, 99_999, days[-1]),
             fill(ROTH, "NBIS", "buy_to_open", 1, 99_999, datetime(2026, 11, 6, 9, 31))]  # today: not yet a whole day
    add(journal, *rows, rebuild=False)
    with Session(journal) as db:
        out = exposure.now(db, datetime(2026, 11, 6, 15, 0, tzinfo=ET))
    # days 10..69 at 100*i, the last day +50: the median of 1000..6900 by 100 (the 6900 day is 6950) is 3950
    assert out["sample_days"] == 60 and out["usual_day_usd"] == 3950.0
    assert out["positions"] == 0 and exposure.line(out) is None  # nothing open: no line


def test_under_ten_entry_days_the_line_leaves_the_usual_day_off():
    base = {"state": "ok", "at_risk_usd": 6400.4, "positions": 3, "usual_day_usd": 2100.0, "sample_days": 60}
    assert exposure.line(base) == "At risk now: $6,400 in 3 options · usual day $2,100"
    assert exposure.line({**base, "usual_day_usd": None, "sample_days": 9}) == "At risk now: $6,400 in 3 options"
    assert exposure.line({**base, "positions": 1, "at_risk_usd": 250}) == "At risk now: $250 in 1 option · usual day $2,100"


def test_nine_entry_days_are_too_few(journal):
    add(journal, *[fill(ROTH, "NBIS", "buy_to_open", 1, 100, datetime(2026, 10, 1 + i, 10, 0)) for i in range(9)], rebuild=False)
    with Session(journal) as db:
        out = exposure.now(db, AT)
    assert out["sample_days"] == 9 and out["usual_day_usd"] is None


def test_a_failing_read_is_unavailable_and_draws_no_line(journal, monkeypatch):
    monkeypatch.setattr(exposure, "_at_risk", lambda db: 1 / 0)
    with Session(journal) as db:
        out = exposure.now(db, AT)
    assert out["state"] == "unavailable" and out["at_risk_usd"] is None and exposure.line(out) is None


def test_the_route_is_owner_only_and_refused_while_the_lab_is_off(boundary):  # noqa: F811
    boundary.patch.delenv("COPILOT_ENABLED", raising=False)
    assert boundary.owner.get("/copilot/exposure").status_code == 503
    boundary.patch.setenv("COPILOT_ENABLED", "true")
    response = boundary.owner.get("/copilot/exposure")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"state", "at_risk_usd", "positions", "usual_day_usd", "sample_days", "as_of", "line"}
    assert body["state"] == "ok"
    assert signin(boundary).status_code == 200
    assert boundary.public.get("/copilot/exposure").status_code == 403
