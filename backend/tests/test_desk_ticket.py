"""The desk's Ticket (GET /copilot/tickets, GET /copilot/tickets/{investigation_id}): copy-to-Robinhood fields for one
saved plan. Only a saved, armed, not-entered plan has a ticket; the figures are arithmetic on the quote; a stale or
missing quote carries no number; nothing here places or sends anything. No network."""

import dataclasses
from datetime import UTC, date, datetime, timedelta
import inspect
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.engine import desk_ticket, reconstructor
from app.engine.chart_feed import chart_feed
from app.engine.options_models import OptionChain, OptionContract
from app.models import Account, LevelAlert, PlanTimeStop, TradeCapture
from app.routers import copilot_ticket as ticket_routes
from tests.test_browser_access import boundary, signin  # noqa: F401  (the shared access fixture)
from tests.test_copilot_plans import buy_and_link

ROTH, MCP = UUID(int=1), UUID(int=2)
NBIS, CRWV = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
WED = date(2026, 10, 21)
T0 = datetime(2026, 10, 21, 14, 0)  # 10:00 ET, naive UTC as stored
NOW = T0.replace(tzinfo=UTC).timestamp() + 600  # 10:10 ET
EXPIRY = date(2026, 11, 13)
REPO = Path(__file__).resolve().parents[2]


class _Wednesday(date):
    @classmethod
    def today(cls):
        return WED


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(reconstructor, "date", _Wednesday)
    monkeypatch.setattr(chart_feed, "quote_rows", lambda symbols: ([], None, None))
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Account(id=ROTH, name="Roth IRA", type="roth_ira", last4="12348267", broker="robinhood"))
        db.add(Account(id=MCP, name="MCP", type="individual", last4="7884", broker="robinhood"))
        db.add(Account(id=UUID(int=3), name="Webull", type="individual", last4="w001", broker="webull"))
        db.commit()
    yield engine
    engine.dispose()


def plan(engine, inv=NBIS, symbol="NBIS", *, side="buy_calls", contract="NBIS 11/13 100C", size=None, quantity=None,
         strike=None, expiration=None, instrument="option", entry_state="active", minute=0, client_id="card-1"):
    """A confirmed plan as a plan card's Confirm leaves it: an entry and invalidation alert, a time stop, the capture."""
    with Session(engine) as db:
        for role, price in (("entry", 95.9), ("invalidation", 90.0)):
            db.add(LevelAlert(symbol=symbol, price=price, created_on=WED, condition="crosses", session="regular", direction="up",
                              source_kind="copilot", source_id=inv, label=f"{symbol} {role}", plan_role=role,
                              state=entry_state if role == "entry" else "active", created_at=T0 + timedelta(minutes=minute)))
        db.add(PlanTimeStop(client_id=client_id, investigation_id=inv, symbol=symbol, text="out by Friday", delivery="scheduled",
                            due_at=T0 + timedelta(days=2), created_at=T0 + timedelta(minutes=minute)))
        wording = "Entry: crosses 95.9. Invalidation: crosses 90." + (f" Size: {size}." if size else "")
        note = "Thesis: Reclaims VWAP with the group." + (f" Contract: {contract}." if contract else "") + " From a Copilot Lab plan card."
        row = TradeCapture(client_id=client_id, received_at=T0 + timedelta(minutes=minute) - timedelta(seconds=5), account_id=ROTH,
                           account_label="Roth IRA", underlying=symbol, side=side, instrument=instrument, mode="discretionary",
                           setup_label="Copilot plan", wording=wording, note=note, strike=strike, expiration=expiration,
                           quantity=quantity, context_state="unavailable", image_state="unavailable")
        db.add(row)
        db.commit()
        return row.id


def contract(strike=100.0, kind="call", bid=3.10, ask=3.30, quoted=NOW - 30, multiplier=100):
    at = datetime.fromtimestamp(quoted, UTC) if quoted else None
    return OptionContract(symbol=f"NBIS261113C{int(strike * 1000):08d}", underlying="NBIS", root="NBIS", expiration=EXPIRY,
                          option_type=kind, strike=strike, multiplier=multiplier, bid=bid, ask=ask, last=None, bid_size=None,
                          ask_size=None, volume=None, open_interest=None, bid_time=at, ask_time=at, trade_time=None, iv=None,
                          iv_smoothed=None, delta=None, gamma=None, theta=None, vega=None, greeks_updated_at=None)


def chain_read(*contracts, spot=95.0, fetched=NOW - 20, spot_at=NOW - 10):
    def read(symbol, expiry):
        chain = OptionChain(underlying=symbol, expiration=expiry, provider="tradier", fetched_at=datetime.fromtimestamp(fetched, UTC),
                            contracts=tuple(contracts)) if contracts else None
        return {"chain": chain, "fetched": fetched, "spot": spot, "spot_at": spot_at, "simulated": False,
                "issue": None if contracts else "No chain."}
    return read


def ticket(engine, inv=NBIS, **kw):
    kw.setdefault("now", NOW)
    with Session(engine) as db:
        return desk_ticket.build(db, inv, **kw)


# --- only a saved plan -----------------------------------------------------------------------------------------------

def test_no_ticket_without_a_saved_plan(engine):
    with pytest.raises(desk_ticket.TicketError) as nothing:
        ticket(engine, chain_read=chain_read(contract()))
    assert nothing.value.code == "no_plan"
    # Armed alerts with no saved pre-trade plan (the capture) are not a saved plan either.
    with Session(engine) as db:
        db.add(LevelAlert(symbol="CRWV", price=100, created_on=WED, condition="crosses", session="regular", direction="up",
                          source_kind="copilot", source_id=CRWV, label="CRWV entry", plan_role="entry", state="active", created_at=T0))
        db.commit()
    with pytest.raises(desk_ticket.TicketError):
        ticket(engine, CRWV, chain_read=chain_read(contract()))
    # A plain watch (not a plan) and a random id: no ticket.
    with pytest.raises(desk_ticket.TicketError):
        ticket(engine, "not-a-plan", chain_read=chain_read(contract()))


def test_an_entered_plan_has_no_ticket_and_leaves_the_list(engine):
    capture_id = plan(engine)
    with Session(engine) as db:
        assert [r["investigation_id"] for r in desk_ticket.armed(db)] == [NBIS]
    buy_and_link(engine, capture_id)
    with pytest.raises(desk_ticket.TicketError) as entered:
        ticket(engine, chain_read=chain_read(contract()))
    assert entered.value.code == "entered"
    with Session(engine) as db:
        assert desk_ticket.armed(db) == []


def test_an_unlinked_fill_after_the_plan_counts_as_entered(engine):
    from app.models import Fill
    from app.routers.fills import _rebuild_trades
    plan(engine)
    with Session(engine) as db:  # bought 45 minutes after the plan, never linked to it
        db.add(Fill(id=UUID(int=600), account_id=ROTH, ticker="NBIS", instrument_type="option", side="buy_to_open", contracts=1,
                    price=320, executed_at=datetime(2026, 10, 21, 10, 45), raw_email_id="gmail:600", option_type="call", strike=100,
                    expiration=EXPIRY))
        db.commit()
        _rebuild_trades(db, "test")
        db.commit()
        assert desk_ticket.armed(db) == []
    with pytest.raises(desk_ticket.TicketError) as entered:
        ticket(engine, chain_read=chain_read(contract()))
    assert entered.value.code == "entered"


def test_the_list_is_newest_first_and_needs_the_capture(engine):
    plan(engine, NBIS, "NBIS", minute=0, client_id="a")
    plan(engine, CRWV, "CRWV", minute=30, client_id="b")
    with Session(engine) as db:
        assert [r["symbol"] for r in desk_ticket.armed(db)] == ["CRWV", "NBIS"]


# --- the figures -----------------------------------------------------------------------------------------------------

def test_figures_for_a_call_and_a_put_against_known_quotes():
    call = desk_ticket.figures("call", 100, 3.20, 2, 100, 95.0, expected_move_pct=6.0)
    assert call == {"cost": 640.0, "max_loss": 640.0, "breakeven": 103.2, "move_pct": 8.63, "vs_expected": 1.4}
    put = desk_ticket.figures("put", 90, 1.50, 3, 100, 95.0)
    assert put == {"cost": 450.0, "max_loss": 450.0, "breakeven": 88.5, "move_pct": -6.84, "vs_expected": None}
    # No quantity: no cost, but break-even still stands; no limit: nothing.
    assert desk_ticket.figures("call", 100, 3.20, None, 100, 95.0)["cost"] is None
    assert desk_ticket.figures("call", 100, None, 2, 100, 95.0) == {"cost": None, "max_loss": None, "breakeven": None,
                                                                     "move_pct": None, "vs_expected": None}


def test_a_ticket_for_a_named_contract_prices_it_at_the_mid(engine):
    plan(engine, size="2 contracts of Nov 13 '26 100C at 3.30, $660 max loss, risk $700")
    found = ticket(engine, chain_read=chain_read(contract(100, bid=3.10, ask=3.30), contract(105, bid=1.0, ask=1.2)))
    assert found["state"] == "ok"
    assert found["contract"] == {"strike": 100.0, "expiry": "2026-11-13", "type": "call", "label": "NBIS $100 Call 11/13/26",
                                 "source": "plan", "multiplier": 100}
    assert found["quote"]["state"] == "ok"
    assert (found["quote"]["bid"], found["quote"]["ask"], found["quote"]["mid"], found["quote"]["spread"]) == (3.1, 3.3, 3.2, 0.2)
    assert found["quote"]["as_of"] == pytest.approx(NOW - 30)
    assert found["limit"] == 3.2 and found["contracts"] == 2
    assert found["figures"]["cost"] == 640.0 and found["figures"]["max_loss"] == 640.0
    assert found["figures"]["breakeven"] == 103.2 and found["figures"]["move_pct"] == 8.63
    assert found["underlying"] == {"state": "ok", "last": 95.0, "as_of": NOW - 10}


def test_the_size_comes_from_a_risk_note_when_it_gives_no_count(engine):
    plan(engine, size="risk $1,000")
    found = ticket(engine, chain_read=chain_read(contract(100, bid=3.10, ask=3.30)))
    assert found["size"]["risk_usd"] == 1000.0
    assert found["contracts"] == 3  # 1000 / 320 a contract, rounded down
    assert found["figures"]["cost"] == 960.0


def test_no_size_leaves_the_quantity_blank(engine):
    plan(engine)
    found = ticket(engine, chain_read=chain_read(contract()))
    assert found["contracts"] is None and found["figures"]["cost"] is None and found["figures"]["breakeven"] == 103.2


def test_the_captures_own_contract_and_quantity_win_over_the_words(engine):
    plan(engine, contract="something vague", strike=105, expiration=EXPIRY, quantity=4)
    found = ticket(engine, chain_read=chain_read(contract(105, bid=1.0, ask=1.2)))
    assert found["contract"]["label"] == "NBIS $105 Call 11/13/26" and found["contracts"] == 4
    assert found["figures"]["cost"] == 440.0


@pytest.mark.parametrize("words,expected", [
    ("NBIS 11/13 100C", (100.0, date(2026, 11, 13), "call")),
    ("Nov 13 '26 100C", (100.0, date(2026, 11, 13), "call")),
    ("100C Nov 13", (100.0, date(2026, 11, 13), "call")),
    ("NBIS 11/13/26 92.5 put", (92.5, date(2026, 11, 13), "put")),
    ("Jan 15 2027 $120 calls", (120.0, date(2027, 1, 15), "call")),
    ("Nov 14 '26 102.5C", (102.5, date(2026, 11, 14), "call")),
    ("Nov 14 95 calls", (95.0, date(2026, 11, 14), "call")),  # a two-digit strike after the day is not a year
    ("SOFI Nov 21 30 calls", (30.0, date(2026, 11, 21), "call")),
    ("Nov 21 105-110 call spread", None),  # a spread is not one long call
    ("Nov 21 105/110C call spread", None),
    ("Nov 21 105/110C", None),
    ("105C, a decent 2 week hold", None),  # "decent 2" is not a date
    ("a 100 strike next week", None),  # no type, no date: not stated plainly
    ("100C or 105C Nov 13", None),  # two strikes: not one contract
    ("calls", None),
    (None, None),
])
def test_contract_words_are_read_only_when_stated_plainly(words, expected):
    assert desk_ticket.read_contract(words, WED) == expected


def test_a_plan_with_no_contract_offers_candidates_and_picks_none(engine):
    plan(engine, contract=None)
    asked = {}

    def candidates(symbol, days, direction):
        asked.update(symbol=symbol, days=days, direction=direction)
        rows = [{"expiry": "2026-11-13", "days": 23, "type": "call", "strike": s, "bid": b, "ask": b + 0.2, "mid": b + 0.1,
                 "per_contract": {"ask": (b + 0.2) * 100}, "spread_pct": 6.0, "breakeven_move_pct": 5.0,
                 "move_needed_vs_expected": 0.8} for s, b in ((90, 7.0), (95, 4.0), (100, 2.0), (105, 1.0), (110, 0.5))]
        return {"state": "ok", "as_of": datetime.fromtimestamp(NOW - 20, UTC).isoformat(), "spot": 98.0, "candidates": rows,
                "expiries": [{"expiry": "2026-11-13", "role": "first_at_or_after", "expected_move": {"move_pct": 6.2}}]}
    found = ticket(engine, candidates_read=candidates)
    assert found["contract"] is None and found["quote"] is None and found["figures"] is None
    assert asked == {"symbol": "NBIS", "days": 2, "direction": "long"}  # the time stop's day sets the horizon
    rows = found["candidates"]["rows"]
    assert [r["strike"] for r in rows] == [95, 100, 105]  # the three nearest the price, by strike; none chosen
    assert rows[0]["expected_move_pct"] == 6.2 and rows[0]["ask_contract"] == pytest.approx(420)
    # His pick becomes the ticket's contract.
    picked = ticket(engine, pick=(EXPIRY, 100.0), chain_read=chain_read(contract(100)))
    assert picked["contract"]["source"] == "picked" and picked["limit"] == 3.2


# --- stale and missing quotes ----------------------------------------------------------------------------------------

def test_a_stale_contract_quote_says_so_and_shows_no_number(engine):
    plan(engine, size="2 contracts")
    found = ticket(engine, chain_read=chain_read(contract(quoted=NOW - 3600)))
    assert found["quote"]["state"] == "stale" and found["quote"]["as_of"] == pytest.approx(NOW - 3600)
    assert not {"bid", "ask", "mid", "spread"} & set(found["quote"])
    assert found["limit"] is None and found["figures"]["cost"] is None and found["figures"]["breakeven"] is None
    # An old chain read is stale too, however fresh the quote times inside it.
    old = ticket(engine, chain_read=chain_read(contract(), fetched=NOW - 3600))
    assert old["quote"]["state"] == "stale" and "mid" not in old["quote"]


def test_a_stale_bid_is_stale_however_fresh_the_ask(engine):
    plan(engine)
    old_bid = dataclasses.replace(contract(), bid_time=datetime.fromtimestamp(NOW - 3 * 3600, UTC))
    found = ticket(engine, chain_read=chain_read(old_bid))
    assert found["quote"]["state"] == "stale" and "mid" not in found["quote"] and found["limit"] is None
    no_time = dataclasses.replace(contract(), ask_time=None)  # a side with no time is not fresh either
    assert ticket(engine, chain_read=chain_read(no_time))["quote"]["state"] == "stale"


def test_a_size_range_is_not_one_count():
    assert desk_ticket.read_size("Size: 1-2 contracts; risk $500.", None) == {"contracts": None, "risk_usd": 500.0, "text": "1-2 contracts; risk $500"}


def test_a_missing_quote_says_so(engine):
    plan(engine)
    no_bid = ticket(engine, chain_read=chain_read(contract(bid=None)))
    assert no_bid["quote"]["state"] == "missing" and "mid" not in no_bid["quote"] and no_bid["limit"] is None
    not_listed = ticket(engine, chain_read=chain_read(contract(105)))  # the chain has no 100 strike
    assert not_listed["quote"]["state"] == "missing"
    no_chain = ticket(engine, chain_read=chain_read())
    assert no_chain["quote"] == {"state": "missing", "reason": "No chain."}


def test_a_stale_stock_price_leaves_out_the_move_needed(engine):
    plan(engine)
    found = ticket(engine, chain_read=chain_read(contract(), spot_at=NOW - 3600))
    assert found["underlying"]["state"] == "stale" and "last" not in found["underlying"]
    assert found["figures"]["breakeven"] == 103.2 and found["figures"]["move_pct"] is None


def test_stock_and_short_option_plans_get_no_ticket_figures(engine):
    plan(engine, side="sell_puts")
    assert ticket(engine, chain_read=chain_read(contract()))["state"] == "not_option"


def test_replay_reads_no_quotes(engine):
    plan(engine)
    assert ticket(engine, mode="replay")["state"] == "no_quotes"


# --- accounts --------------------------------------------------------------------------------------------------------

def test_accounts_show_the_label_and_last_four_only_with_the_plans_selected(engine):
    plan(engine)
    found = ticket(engine, chain_read=chain_read(contract()))
    assert found["account"] == str(ROTH)
    assert [(a["label"], a["last4"], a["kind"]) for a in found["accounts"]] == [("Roth IRA", "8267", "roth"), ("MCP", "7884", "mcp")]
    assert "1234" not in str(found["accounts"]) and "Webull" not in str(found["accounts"])


def test_an_mcp_account_not_in_the_journal_still_shows_without_a_number(engine):
    with Session(engine) as db:
        db.delete(db.get(Account, MCP))
        db.commit()
    plan(engine)
    found = ticket(engine, chain_read=chain_read(contract()))
    assert found["accounts"][-1] == {"id": "mcp", "label": "MCP", "last4": None, "kind": "mcp"}


# --- routes, and nothing sends ---------------------------------------------------------------------------------------

@pytest.fixture
def lab(engine, monkeypatch):
    monkeypatch.setattr(ticket_routes.copilot, "settings", lambda: SimpleNamespace(enabled=True, evidence="live"))
    app = FastAPI()
    app.include_router(ticket_routes.router, prefix="/copilot")

    def session():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_session] = session
    with TestClient(app) as client:
        yield client


def test_routes_refuse_without_a_saved_plan_and_while_the_lab_is_off(engine, lab, monkeypatch):
    assert lab.get("/copilot/tickets").json() == {"plans": []}
    assert lab.get(f"/copilot/tickets/{NBIS}").status_code == 404
    plan(engine)
    assert [r["symbol"] for r in lab.get("/copilot/tickets").json()["plans"]] == ["NBIS"]
    monkeypatch.setattr(ticket_routes.copilot, "settings", lambda: SimpleNamespace(enabled=False))
    assert lab.get("/copilot/tickets").status_code == 503
    assert lab.get(f"/copilot/tickets/{NBIS}").status_code == 503


def test_assistant_sessions_cannot_reach_tickets(boundary):  # noqa: F811
    boundary.patch.setenv("COPILOT_ENABLED", "true")
    assert boundary.owner.get("/copilot/tickets").status_code == 200
    assert signin(boundary).status_code == 200
    assert boundary.public.get("/copilot/tickets").status_code == 403


def test_nothing_in_the_ticket_places_or_sends_anything():
    # Every ticket route only reads.
    methods = {m for route in ticket_routes.router.routes for m in route.methods}
    assert methods <= {"GET", "HEAD"}
    # No broker, order or send path is reachable from the ticket's code.
    sources = [inspect.getsource(desk_ticket), inspect.getsource(ticket_routes)]
    screen = REPO / "frontend/components/copilot/DeskTicket.tsx"
    sources.append(screen.read_text())
    # The closing ticket ("Close at target" / "Close at stop") is filled in the browser from the book row: its math and
    # its buttons are in these files, and none of them reads or sends anything either.
    closing = REPO / "frontend/lib/closingTicket.ts"
    sources += [closing.read_text(), (REPO / "frontend/components/copilot/OptionStanding.tsx").read_text()]
    assert "fetch(" not in closing.read_text() and "apiUrl" not in closing.read_text()
    forbidden = ("robinhood_trading", "place_option_order", "place_equity_order", "review_option_order", "order_tool",
                 "requests.post", "httpx", "urllib", "method: \"POST\"", "method: 'POST'", "ntfy", "telegram")
    for text in sources:
        lowered = text.lower()
        assert not [word for word in forbidden if word.lower() in lowered]
    # The screen's Send button is drawn disabled and has no handler.
    send = next(line for line in screen.read_text().splitlines() if "Send to Robinhood for your approval" in line)
    assert "disabled" in send and "onClick" not in send
    assert screen.read_text().count("Send to Robinhood") == 1
    # The closing view has no Send button at all, disabled or not, and reads no route.
    view = screen.read_text()[screen.read_text().index("function ClosingView("):]
    assert "Send" not in view and "read<" not in view and "fetch(" not in view
