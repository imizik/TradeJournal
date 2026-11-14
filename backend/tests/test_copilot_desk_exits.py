"""The copilot's desk actions on a position he holds and on a Feed idea (docs/copilot-lab.md § Desk actions): close and
trim cards open the copy-only closing ticket, a note card saves his one-line note through the book row's own route, a
plan card opens a Radar setup card's own Plan it. The tool writes nothing; the money a card shows (contracts sold and
left, the P&L, what the sale brings in at the mark) comes from the desk's position data. Offline: no quote, no Robinhood
read, an in-memory database. Every number is invented."""
import asyncio
from datetime import date

import pytest

from app.ai import copilot, copilot_actions, copilot_tools
from app.ai.copilot_fixture import desk_requests
from app.engine import copilot_investigations
from app.models import RadarSetup
from app.routers.fills import _rebuild_trades
from tests.test_capture_links import CALL, PUT, db, fill, trade_of  # noqa: F401  (fixtures and helpers)
from tests.test_copilot import NOW, _cfg

T1 = "11111111-1111-4111-8111-111111111111"
T2 = "22222222-2222-4222-8222-222222222222"
T3 = "33333333-3333-4333-8333-333333333333"


def leg(trade_id=T1, *, side="call", strike=100.0, expiry="2026-11-20", direction="long", quantity=3, usd=420.0, mark=410.0,
        instrument="option", account="8267"):
    """A held position as ``_held`` reads it: ``mark`` is a contract's (the premium x 100), ``usd`` the open P&L."""
    return {"trade_id": trade_id, "instrument": instrument, "direction": direction, "side": side if instrument == "option" else None,
            "strike": strike if instrument == "option" else None, "expiry": expiry if instrument == "option" else None,
            "quantity": quantity, "usd": usd, "mark": mark, "account": account}


class Desk:
    """Evidence with a fixed desk: positions, ideas and whether he follows the ticker. No quote is ever read."""
    label = "fixture"

    def __init__(self, held=(), ideas=(), hidden=False):
        self.held, self.ideas, self.hidden, self.asked = list(held), list(ideas), hidden, []

    def desk_state(self, symbol, need=frozenset()):
        self.asked.append(set(need))
        state = {"hidden": self.hidden, "watching": [], "plans": [], "tickets": []}
        if not self.hidden:  # read_state reads no position or idea for a ticker he does not follow
            state |= {"held": self.held} if "held" in need else {}
            state |= {"ideas": self.ideas} if "ideas" in need else {}
        return state

    def get_quotes(self, symbols):
        raise AssertionError("a position or idea card reads no quote")


def card(evidence, **args):
    return copilot_actions.act(evidence, copilot_actions.validate({"symbol": "NBIS", **args}), now=1_794_600_000)["action"]


def refused(evidence, **args):
    with pytest.raises(copilot_tools.ToolInputError) as exc:
        card(evidence, **args)
    return str(exc.value)


# --------------------------------------------------------------------------- the money

@pytest.mark.parametrize("held,half,sold", [(1, True, 1), (2, True, 1), (3, True, 1), (4, True, 2), (5, True, 2), (11, True, 5)])
def test_half_rounds_down_and_is_at_least_one(held, half, sold):
    assert copilot_actions.trim_count(held, half=half) == sold


def test_a_count_is_never_more_than_he_holds():
    assert copilot_actions.trim_count(3, 2) == 2 and copilot_actions.trim_count(3, 3) == 3
    with pytest.raises(copilot_tools.ToolInputError, match="fewer than 4"):
        copilot_actions.trim_count(3, 4)
    for bad in (0, -1):
        with pytest.raises(copilot_tools.ToolInputError):
            copilot_actions.trim_count(3, bad)
    with pytest.raises(copilot_tools.ToolInputError, match="no whole contracts"):
        copilot_actions.trim_count(0, half=True)


def test_proceeds_are_the_mark_a_contract_times_the_contracts_and_negative_when_closing_costs():
    assert copilot_actions.proceeds(410.0, 3) == 1230.0  # 4.10 premium x 100 x 3
    assert copilot_actions.proceeds(4.0, 1) == 4.0  # a 0.04 premium is $4 a contract
    assert copilot_actions.proceeds(-135.0, 2) == -270.0  # a held credit spread costs $1.35 a spread to close
    assert copilot_actions.proceeds(None, 2) is None


# --------------------------------------------------------------------------- close and trim

def test_close_is_the_whole_long_call_at_the_mark_with_its_pnl():
    made = card(Desk([leg()]), action="close")
    assert made["legs"] == [{"trade_id": T1, "instrument": "option", "direction": "long", "side": "call", "strike": 100.0,
                             "expiry": "2026-11-20"}]
    assert (made["held"], made["contracts"], made["remains"]) == (3, 3, 0)
    assert made["mark"] == 410.0 and made["proceeds"] == 1230.0 and made["usd"] == 420.0
    assert copilot_actions.line(made) == "Close NBIS 100 call Nov 20 · all 3"
    assert "account" not in str(made) and "8267" not in str(made)  # the account never reaches the card


def test_trim_sells_part_and_says_what_is_left():
    half = card(Desk([leg(quantity=5)]), action="trim", half=True)
    assert (half["held"], half["contracts"], half["remains"]) == (5, 2, 3) and half["proceeds"] == 820.0
    assert copilot_actions.line(half) == "Trim NBIS 100 call Nov 20 · sell 2 of 5, 3 left"
    two = card(Desk([leg(quantity=5)]), action="trim", quantity=2)
    assert (two["contracts"], two["remains"]) == (2, 3)
    one = card(Desk([leg(quantity=1)]), action="trim", half=True)  # half of one is still one
    assert (one["contracts"], one["remains"]) == (1, 0)
    assert "fewer than 6" in refused(Desk([leg(quantity=5)]), action="trim", quantity=6)


def test_journal_only_numbers_stay_null_never_zero():
    made = card(Desk([leg(usd=None, mark=None)]), action="trim", quantity=1)
    assert made["mark"] is None and made["proceeds"] is None and made["usd"] is None


def test_a_put_closes_the_same_way_with_its_own_mark():
    made = card(Desk([leg(side="put", strike=30, mark=148.0, usd=-63.0, quantity=3)]), action="close")
    assert made["proceeds"] == 444.0 and made["usd"] == -63.0  # a loss keeps its sign
    assert copilot_actions.line(made) == "Close NBIS 30 put Nov 20 · all 3"


def test_a_held_vertical_closes_as_its_closing_spread():
    long_, short = leg(T1, strike=100, mark=410.0, usd=300.0, quantity=2), leg(T2, strike=110, direction="short", mark=150.0, usd=-90.0, quantity=2)
    made = card(Desk([short, long_]), action="close")
    assert [p["trade_id"] for p in made["legs"]] == [T1, T2]  # the bought leg first
    assert made["mark"] == 260.0 and made["proceeds"] == 520.0 and made["usd"] == 210.0  # (4.10 − 1.50) x 100 x 2; +300 − 90
    assert copilot_actions.line(made) == "Close NBIS 100/110 call spread Nov 20 · all 2"
    half = card(Desk([short, long_]), action="trim", half=True)
    assert (half["contracts"], half["remains"], half["proceeds"]) == (1, 1, 260.0)
    # Naming either leg's strike means the spread, never one leg of it.
    assert len(card(Desk([short, long_]), action="close", strike=110)["legs"]) == 2


def test_a_held_credit_spread_costs_money_to_close():
    long_, short = leg(T1, side="put", strike=90, mark=60.0), leg(T2, side="put", strike=95, direction="short", mark=195.0)
    made = card(Desk([long_, short]), action="close")
    assert made["mark"] == -135.0 and made["proceeds"] == -405.0  # (0.60 − 1.95) x 100 x 3: a debit to close


def test_more_than_one_fitting_position_asks_which_and_the_contract_picks_it():
    held = [leg(T1, strike=100), leg(T2, strike=105, expiry="2026-12-18")]
    why = refused(Desk(held), action="close")
    assert "ask the owner which one" in why and "100 call Nov 20" in why and "105 call Dec 18" in why
    assert card(Desk(held), action="close", strike=105)["legs"][0]["trade_id"] == T2
    assert card(Desk(held), action="close", expiry="2026-11-20")["legs"][0]["trade_id"] == T1
    assert "fits that contract" in refused(Desk(held), action="close", option_type="put")
    # The same contract in two accounts is two positions, never one spread.
    assert "ask the owner which one" in refused(Desk([leg(T1), leg(T2, account="1111")]), action="close")


def test_what_has_no_closing_ticket_is_refused():
    assert "holds no open NBIS position" in refused(Desk(), action="close")
    assert "is shares" in refused(Desk([leg(instrument="stock", quantity=100)]), action="trim", half=True)
    assert "short leg" in refused(Desk([leg(direction="short", side="put", strike=30)]), action="close")
    assert "whole number" in refused(Desk([leg(quantity=2.5)]), action="close")
    # Unequal legs are not one spread: two positions, so it asks.
    uneven = [leg(T1, strike=100, quantity=2), leg(T2, strike=110, direction="short", quantity=1)]
    assert "ask the owner which one" in refused(Desk(uneven), action="close")


@pytest.mark.parametrize("args,why", [
    ({"action": "trim"}, "either quantity or half"),
    ({"action": "trim", "quantity": 2, "half": True}, "either quantity or half"),
    ({"action": "trim", "quantity": 0}, "at least 1"),
    ({"action": "trim", "quantity": 1.5}, "whole number"),
    ({"action": "trim", "half": "yes"}, "true or false"),
    ({"action": "close", "quantity": 2}, "unexpected arguments"),
    ({"action": "close", "expiry": "Nov 20"}, "YYYY-MM-DD"),
    ({"action": "note"}, "1 to 300"),
    ({"action": "note", "text": "x" * 301}, "1 to 300"),
    ({"action": "plan_idea", "direction": "up"}, "long or short"),
])
def test_each_request_takes_only_its_own_arguments(args, why):
    with pytest.raises(copilot_tools.ToolInputError, match=why):
        copilot_tools.validate("desk_action", {"symbol": "NBIS", **args})


# --------------------------------------------------------------------------- notes

def test_a_note_names_the_position_and_its_journal_trade():
    made = card(Desk([leg()]), action="note", text="  took profit\n into the wall ")
    assert made["text"] == "took profit into the wall" and made["legs"][0]["trade_id"] == T1
    assert copilot_actions.line(made) == "Note on NBIS 100 call Nov 20: took profit into the wall"
    assert "held" not in made and "proceeds" not in made  # a note carries no money
    shares = card(Desk([leg(instrument="stock", quantity=100)]), action="note", text="added on the dip")
    assert copilot_actions.line(shares) == "Note on NBIS shares: added on the dip"
    # A spread's note goes on its bought leg.
    spread = card(Desk([leg(T1), leg(T2, strike=110, direction="short")]), action="note", text="rolled up")
    assert [p["trade_id"] for p in spread["legs"]] == [T1] and spread["contract"] == "100/110 call spread Nov 20"
    assert "fill email is not in" in refused(Desk([leg(None)]), action="note", text="x")


# --------------------------------------------------------------------------- a Feed idea

IDEA = {"event_id": "rd0-2026-11-13-dip-iren-up-1", "direction": "long", "words": "dip turn up", "levels_line": "In near 41.20 · out below 39.80 (-3.4%)",
        "plan_state": "none"}


def test_plan_it_opens_todays_setup_card_and_asks_when_there_are_two():
    made = card(Desk(ideas=[IDEA]), action="plan_idea", symbol="IREN")
    assert made["event_id"] == IDEA["event_id"] and made["direction"] == "long"
    assert copilot_actions.line(made) == "Plan it: IREN dip turn up"
    short = {**IDEA, "event_id": "rd0-2026-11-13-gap-iren-down-1", "direction": "short", "words": "gap reversal down"}
    assert "a long and a short" in refused(Desk(ideas=[IDEA, short]), action="plan_idea", symbol="IREN")
    assert card(Desk(ideas=[IDEA, short]), action="plan_idea", symbol="IREN", direction="short")["event_id"] == short["event_id"]
    assert "no Radar setup card in IREN today" in refused(Desk(), action="plan_idea", symbol="IREN")
    assert "already planned" in refused(Desk(ideas=[{**IDEA, "plan_state": "planned"}]), action="plan_idea", symbol="IREN")


def test_a_ticker_he_stopped_following_gets_no_card_and_no_position_read():
    desk = Desk([leg()], [IDEA], hidden=True)
    for args in ({"action": "close"}, {"action": "trim", "half": True}, {"action": "note", "text": "x"}, {"action": "plan_idea"}):
        assert "Not following" in refused(desk, **args)


# --------------------------------------------------------------------------- the desk as it stands

def test_held_reads_the_journals_open_positions_without_a_quote_or_robinhood(db, monkeypatch):  # noqa: F811
    from app.ai import copilot_book
    from app.engine import robinhood_book
    monkeypatch.setattr(robinhood_book.feed, "snapshot", lambda kick=True: ({"state": "off"}, None))
    monkeypatch.setattr(copilot_book, "_mark", lambda *a: (_ for _ in ()).throw(AssertionError("no quote read")))
    entry = fill(db, "NVDA", "buy_to_open", 3, 310, "2026-09-15T09:44", **CALL)
    fill(db, "NVDA", "sell_to_close", 1, 400, "2026-09-16T10:00", **CALL)
    put = fill(db, "NVDA", "buy_to_open", 2, 120, "2026-09-15T09:50", **PUT)
    fill(db, "NVDA", "sell_to_close", 2, 140, "2026-09-16T10:00", **PUT)  # closed: not held
    fill(db, "AMD", "buy_to_open", 1, 200, "2026-09-15T09:44", **CALL)
    _rebuild_trades(db, "test")
    held = copilot_actions._held(db, "NVDA")
    assert held == [{"trade_id": str(trade_of(db, entry).id), "instrument": "option", "direction": "long", "side": "call",
                     "strike": 900.0, "expiry": "2099-01-15", "quantity": 2, "usd": None, "mark": None, "account": "8267"}]
    assert trade_of(db, put).status != "open"


def test_held_takes_the_snapshots_numbers_and_its_new_rows(db, monkeypatch):  # noqa: F811
    from app.ai import copilot_book
    entry = fill(db, "NVDA", "buy_to_open", 3, 310, "2026-09-15T09:44", **CALL)
    _rebuild_trades(db, "test")
    trade = str(trade_of(db, entry).id)
    new = {"symbol": "NVDA", "instrument": "option", "direction": "short", "option": {"side": "call", "strike": 950.0, "expiry": "2099-01-15"},
           "quantity": 3.0, "unrealized_usd": -40.0, "mark": 120.0, "account": "Roth"}
    monkeypatch.setattr(copilot_book, "live_or_unavailable", lambda db: {"state": "ok", "as_of": None, "new": [new, {**new, "symbol": "AMD"}],
                        "matched": {trade: {"quantity": 3.0, "unrealized_usd": 270.0, "mark": 400.0}}})
    held = copilot_actions._held(db, "NVDA")
    assert [(p["trade_id"], p["quantity"], p["usd"], p["mark"]) for p in held] == [(trade, 3.0, 270.0, 400.0), (None, 3.0, -40.0, 120.0)]


def test_ideas_read_todays_setup_cards_only(db):  # noqa: F811
    for event, day, direction, state in (("e1", "2026-11-13", "up", "none"), ("e0", "2026-11-12", "up", "none"), ("e2", "2026-11-13", "down", "planned")):
        db.add(RadarSetup(event_id=event, session_date=day, rule_version="v0", kind="dip_turn", symbol="IREN", direction=direction,
                          entry=41.2, invalidation=39.8 if direction == "up" else 42.5, plan_state=state))
    db.commit()
    ideas = copilot_actions._ideas(db, "IREN", date(2026, 11, 13))
    assert {(i["event_id"], i["direction"], i["plan_state"]) for i in ideas} == {("e1", "long", "none"), ("e2", "short", "planned")}
    assert all(i["words"] and i["levels_line"].startswith("In near 41.20") for i in ideas)


# --------------------------------------------------------------------------- the scripted model's turns

def run(question, evidence):
    async def collect():
        return [e async for e in copilot.run_turn([{"role": "user", "content": question}], "NBIS", _cfg(), copilot.FakeAdapter(delay_s=0),
                                                  evidence, NOW, job="desk")]
    return asyncio.run(collect())


@pytest.mark.parametrize("question,line", [
    ("Close my NBIS calls", "Close NBIS 100 call Nov 20 · all 4"),
    ("Sell half my NBIS", "Trim NBIS 100 call Nov 20 · sell 2 of 4, 2 left"),
    ("Take 3 off NBIS", "Trim NBIS 100 call Nov 20 · sell 3 of 4, 1 left"),
    ("Note on NBIS: took profit into the wall", "Note on NBIS 100 call Nov 20: took profit into the wall"),
    ("Plan the IREN Radar setup", "Plan it: IREN dip turn up"),
])
def test_the_scripted_model_makes_each_card(question, line):
    events = run(question, Desk([leg(quantity=4)], [IDEA]))
    [proposal] = [e for e in events if e["type"] == "proposal"]
    assert proposal["kind"] == "desk_action" and copilot_actions.line(proposal) == line
    text = "".join(e["delta"] for e in events if e["type"] == "text")
    assert "Tap the card" in text and "Verdict:" not in text


def test_a_refusal_is_said_and_no_card_is_made():
    events = run("Take 6 off NBIS", Desk([leg(quantity=4)]))
    assert not [e for e in events if e["type"] == "proposal"]
    assert "fewer than 6" in "".join(e["delta"] for e in events if e["type"] == "text")
    events = run("Close my NBIS calls", Desk([leg(), leg(T2, strike=105)]))
    assert not [e for e in events if e["type"] == "proposal"]
    assert "which one" in "".join(e["delta"] for e in events if e["type"] == "text")


def test_the_fixture_reads_each_request_and_keeps_a_notes_words_whole():
    today = date(2026, 11, 13)
    assert desk_requests("Close my NBIS 100c Nov 20", "APLD", today) == [{"action": "close", "symbol": "NBIS", "strike": 100.0,
                                                                         "option_type": "call", "expiry": "2026-11-20"}]
    assert desk_requests("take 2 off IREN", "NBIS", today) == [{"action": "trim", "symbol": "IREN", "quantity": 2}]
    assert desk_requests("Trim NBIS", "NBIS", today) == "How many NBIS contracts: a number, or half?"
    # The words after the colon are the note, even ones that read like another request.
    assert desk_requests("Note on NBIS: move my stop to 90, watch IREN", "NBIS", today) == [
        {"action": "note", "symbol": "NBIS", "text": "move my stop to 90, watch IREN"}]
    assert desk_requests("Plan that scanner pick", "IREN", today) == [{"action": "plan_idea", "symbol": "IREN"}]
    assert desk_requests("What would you close today?", "NBIS", today) is None


# --------------------------------------------------------------------------- the card as saved

@pytest.mark.parametrize("question,bad", [
    ("Sell half my NBIS", {"remains": 3}),  # sold + left must be held
    ("Sell half my NBIS", {"contracts": 0, "remains": 4}),
    ("Close my NBIS calls", {"contracts": 2, "remains": 2}),  # a close sells all of it
    ("Close my NBIS calls", {"mark": None}),  # proceeds without a mark
    ("Close my NBIS calls", {"legs": [{"trade_id": "x"}]}),
    ("Close my NBIS calls", {"proceeds": "1230"}),
    ("Note on NBIS: took profit", {"held": 4}),  # a note keeps no money
    ("Note on NBIS: took profit", {"legs": [{**leg(None), "account": None}]}),
    ("Plan the IREN Radar setup", {"event_id": "../x"}),
    ("Plan the IREN Radar setup", {"words": None}),
])
def test_a_card_saves_with_its_outcome_and_a_tampered_one_does_not(question, bad):
    proposal = next(e for e in run(question, Desk([leg(quantity=4)], [IDEA])) if e["type"] == "proposal")
    stored = {k: v for k, v in proposal.items() if k != "type"} | {"client_id": "card-abc123", "outcome": {"state": "confirmed", "note": "done"}}
    assert copilot_investigations._saved_proposal(stored) == stored
    with pytest.raises(ValueError):
        copilot_investigations._saved_proposal({**stored, **bad})
