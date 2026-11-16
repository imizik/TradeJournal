"""The copilot's paper order card (``app/ai/copilot_paper_draft.py``): ``draft_paper_order`` matches the contract he
named to what is listed (saying each substitution), prices it with the paper book's own preview (the ask to buy, the
bid to sell, the cash and the buying power left) and never fills or stores anything. A stale quote or a closed market
leaves the card without a price and says why. No network: the paper book's quote read and the options feed are faked."""
import asyncio
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from sqlmodel import select

from app.ai import copilot, copilot_fixture, copilot_paper_draft as draft, copilot_prompt, copilot_tools
from app.ai.copilot_fixture import FixtureEvidence
from app.engine import copilot_investigations, paper_book
from app.models import PaperEvent
from tests.test_paper_book import CALL, NOW, buy_call, db, key, market, q  # noqa: F401  (fixtures)

FRI = date(2026, 11, 20)


def chain_of(expiries, strikes, root="NBIS", multiplier=100):
    """A fake ``options_feed.chains``: the listed expiries, and each one's chain with these call and put strikes."""
    calls = []

    def chains(symbol, pick, ttl):
        calls.append((symbol, ttl))
        chosen = pick(sorted(expiries))
        reads = [SimpleNamespace(value=SimpleNamespace(expiration=d, contracts=tuple(
            SimpleNamespace(option_type=t, strike=s, root=root, multiplier=multiplier) for s in strikes for t in ("call", "put"))))
            for d in chosen]
        return reads, None
    chains.calls = calls
    return chains


def ask(**args):
    return copilot_tools.validate("draft_paper_order", {"symbol": "NBIS", **args})


def opened(db, chains=None, **args):
    return draft._open(db, ask(action="open", **args), NOW, chains or chain_of([FRI], [95, 100, 105]))


def events(db):
    return len(db.exec(select(PaperEvent)).all())


# --------------------------------------------------------------------------- the request

@pytest.mark.parametrize("args,why", [
    ({"action": "buy"}, "open, close or trim"),
    ({"action": "open", "instrument": "option", "quantity": 2, "option_type": "call", "strike": 100}, "expiry and strike"),
    ({"action": "open", "instrument": "spread", "quantity": 1}, "from the Ticket"),
    ({"action": "open", "instrument": "stock", "quantity": 0}, "whole number"),
    ({"action": "open", "instrument": "stock", "quantity": 5, "strike": 100}, "no option_type"),
    ({"action": "open", "instrument": "stock", "quantity": 5, "idea": "radar"}, "idea is mine"),
    ({"action": "close", "quantity": 2}, "unexpected arguments"),
    ({"action": "trim"}, "quantity or half"),
    ({"action": "trim", "quantity": 1, "half": True}, "quantity or half"),
])
def test_a_request_takes_only_its_own_arguments(args, why):
    with pytest.raises(copilot_tools.ToolInputError, match=why):
        ask(**args)


def test_only_a_desk_turn_is_offered_the_card():
    assert "draft_paper_order" in {t["name"] for t in copilot_prompt.tools(copilot_prompt.DESK)}
    for job in (copilot_prompt.TELEGRAM, copilot_prompt.PREP, copilot_prompt.COMPANION, copilot_prompt.WEEK_REVIEW):
        assert "draft_paper_order" not in {t["name"] for t in copilot_prompt.tools(job)}
    assert "draft_paper_order" in copilot_tools.CARD_TOOLS


# --------------------------------------------------------------------------- the contract against what is listed

def test_the_nearest_listed_expiry_and_strike_are_said_never_picked_silently():
    exact = draft.resolve("NBIS", "call", "2026-11-20", 100, chain_of([FRI, date(2026, 11, 27)], [95, 100, 105]))
    assert exact == ("2026-11-20", 100, [])
    expiry, strike, picked = draft.resolve("NBIS", "call", "2026-11-19", 101, chain_of([FRI, date(2026, 11, 27)], [95, 100, 105]))
    assert (expiry, strike) == ("2026-11-20", 100)
    assert picked == ["Thu Nov 19 is not a listed NBIS expiry; the nearest is Fri Nov 20.", "$101 is not a listed strike; the nearest is $100."]
    # A tie goes to the earlier expiry and the lower strike, and is still said.
    assert draft.resolve("NBIS", "put", "2026-11-23", 97.5, chain_of([FRI, date(2026, 11, 26)], [95, 100]))[:2] == ("2026-11-20", 95)


def test_a_list_that_cannot_be_read_drafts_his_contract_and_says_it_was_not_checked():
    def down(symbol, pick, ttl):
        return [], "Options data is pacing: try again in a minute."
    expiry, strike, picked = draft.resolve("NBIS", "call", "2026-11-20", 100, down)
    assert (expiry, strike) == ("2026-11-20", 100) and "Could not check the listed NBIS contracts" in picked[0]


def test_no_listed_options_or_an_adjusted_contract_is_refused():
    with pytest.raises(copilot_tools.ToolInputError, match="no listed options"):
        draft.resolve("NBIS", "call", "2026-11-20", 100, lambda s, pick, ttl: ([], None))
    with pytest.raises(copilot_tools.ToolInputError, match="adjusted contract"):
        draft.resolve("NBIS", "call", "2026-11-20", 100, chain_of([FRI], [100], multiplier=150))


# --------------------------------------------------------------------------- the price, and nothing stored

def test_an_open_card_shows_the_ask_the_cost_and_the_buying_power_left_and_stores_nothing(db, market):  # noqa: F811
    paper_book.start_run(db, 10_000, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 97.9, 98.1, last=98.0)}
    before = events(db)
    card = opened(db, instrument="option", option_type="call", expiry="2026-11-20", strike=100, quantity=2, stop=96, target=108)
    assert events(db) == before  # a draft never fills
    assert card["label"] == "NBIS $100 Call 11/20/26" and card["multiplier"] == 100 and card["idea"] == "mine"
    assert (card["stop"], card["target"], card["issue"], card["picked"]) == (96, 108, None, [])
    p = card["preview"]
    assert (p["price"], p["side"], p["per_share"]) == (3.40, "ask", -3.40)
    assert p["cash"] == -680.0 and p["buying_power"] == 10_000.0 and p["buying_power_after"] == 9_320.0
    assert p["quoted_at"] == pytest.approx(NOW - 5)
    assert draft.line(card) == "Paper: buy 2 × NBIS $100 Call 11/20/26"


def test_shares_have_no_multiplier_and_no_chain_read(db, market):  # noqa: F811
    paper_book.start_run(db, 10_000, False, NOW)
    market.quotes = {"NBIS": q("NBIS", 97.9, 98.1, last=98.0)}
    chains = chain_of([FRI], [100])
    card = opened(db, chains, instrument="stock", quantity=50, idea="copilot")
    assert chains.calls == [] and card["label"] == "NBIS shares" and card["multiplier"] == 1
    assert card["preview"]["cash"] == -4_905.0 and card["preview"]["buying_power_after"] == 5_095.0
    assert draft.line(card) == "Paper: buy 50 NBIS shares"


def test_a_stale_quote_a_closed_market_or_no_account_greys_the_card_with_why(db, market):  # noqa: F811
    args = dict(instrument="option", option_type="call", expiry="2026-11-20", strike=100, quantity=1)
    assert opened(db, **args)["issue"] == "Start a paper account first."
    paper_book.start_run(db, 10_000, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40, age=600), "NBIS": q("NBIS", 97.9, 98.1)}
    stale = opened(db, **args)
    assert stale["preview"] is None and "not live: no paper fill on a stale price" in stale["issue"]
    market.open = False
    assert "market is closed" in opened(db, **args)["issue"]
    market.open = True
    market.quotes = {CALL: q(CALL, 30.0, 31.0), "NBIS": q("NBIS", 97.9, 98.1)}
    assert "Not enough paper buying power" in opened(db, **{**args, "quantity": 5})["issue"]


def test_a_stop_on_the_wrong_side_is_the_models_to_ask_about(db, market):  # noqa: F811
    paper_book.start_run(db, 10_000, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 97.9, 98.1, last=98.0)}
    with pytest.raises(copilot_tools.ToolInputError, match="stop is a stock price below 98"):
        opened(db, instrument="option", option_type="call", expiry="2026-11-20", strike=100, quantity=1, stop=99)


def test_close_and_trim_name_his_open_paper_position_at_the_bid(db, market):  # noqa: F811
    paper_book.start_run(db, 10_000, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 97.9, 98.1, last=98.0)}
    position = buy_call(db, qty=5)["filled"]["position_id"]
    market.quotes = {CALL: q(CALL, 4.10, 4.20), "NBIS": q("NBIS", 99.9, 100.1, last=100.0)}
    before = events(db)
    close = draft._close(db, ask(action="close"), NOW)
    assert (close["position_id"], close["quantity"], close["remains"], close["held"]) == (position, 5, 0, 5)
    assert (close["preview"]["price"], close["preview"]["side"]) == (4.10, "bid")
    assert close["preview"]["cash"] == 2_050.0 and close["preview"]["pnl"] == 350.0  # 5 × (4.10 − 3.40) × 100
    half = draft._close(db, ask(action="trim", half=True), NOW)
    assert (half["quantity"], half["remains"]) == (2, 3) and half["preview"]["pnl"] == 140.0
    assert draft.line(half) == "Paper: trim NBIS $100 Call 11/20/26 · sell 2 of 5"
    assert events(db) == before
    with pytest.raises(copilot_tools.ToolInputError, match="fewer than 6"):
        draft._close(db, ask(action="trim", quantity=6), NOW)
    with pytest.raises(copilot_tools.ToolInputError, match="no open paper AMD"):
        draft._close(db, {**ask(action="close"), "symbol": "AMD"}, NOW)
    with pytest.raises(copilot_tools.ToolInputError, match="fits that contract"):
        draft._close(db, ask(action="close", option_type="put"), NOW)


def test_two_positions_in_the_ticker_ask_which(db, market):  # noqa: F811
    paper_book.start_run(db, 10_000, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 97.9, 98.1, last=98.0)}
    buy_call(db, qty=1)
    paper_book.open_order(db, {"symbol": "NBIS", "instrument": "stock", "quantity": 10, "order_key": key()}, NOW)
    with pytest.raises(copilot_tools.ToolInputError, match="2 open paper NBIS positions"):
        draft._close(db, ask(action="close"), NOW)
    assert draft._close(db, ask(action="close", strike=100), NOW)["label"] == "NBIS $100 Call 11/20/26"


def test_a_ticker_he_does_not_follow_is_left_alone(monkeypatch):
    from app.engine import day_journal
    monkeypatch.setattr(day_journal, "quiet", lambda db: {"NBIS"})
    with pytest.raises(copilot_tools.ToolInputError, match="Not following"):
        draft.live_draft(ask(action="close"))


# --------------------------------------------------------------------------- the turn, the card and its save

def test_the_tool_needs_a_desk_evidence_and_the_fixture_card_is_simulated():
    class Replay:
        label = "replay"
    with pytest.raises(copilot_tools.ToolInputError, match="not available here"):
        copilot_tools.call(Replay(), "draft_paper_order", ask(action="close"))
    out = copilot_tools.call(FixtureEvidence(), "draft_paper_order",
                             ask(action="open", instrument="option", option_type="call", expiry="2026-11-20", strike=100, quantity=2))
    assert out["order"]["preview"]["cash"] == -680.0 and out["order"]["label"] == "NBIS $100 Call 11/20/26"


def test_a_stored_card_round_trips_and_a_tampered_one_is_refused():
    card = draft.fixture_draft(ask(action="open", instrument="option", option_type="call", expiry="2026-11-20", strike=100,
                                   quantity=2, stop=96), now=1_792_857_000)["order"]
    stored = {"id": "toolu_1", "kind": "paper_order", **card, "outcome": {"state": "confirmed", "note": "Paper: Buy 2 × …"}}
    assert copilot_investigations._saved_proposal(stored) == {**stored, "made_at": 1_792_857_000}
    trim = draft.fixture_draft(ask(action="trim", half=True), now=1_792_857_000)["order"]
    assert copilot_investigations._saved_proposal({"id": "t2", "kind": "paper_order", **trim})["quantity"] == 1
    for bad in ({**stored, "quantity": 0}, {**stored, "preview": {**card["preview"], "side": "mid"}},
                {**stored, "fill_now": True}, {"id": "t3", "kind": "paper_order", **trim, "remains": 5}):
        with pytest.raises(ValueError):
            copilot_investigations._saved_proposal(bad)


def test_the_scripted_model_reads_a_paper_request_and_asks_when_a_part_is_missing():
    today = date(2026, 11, 16)  # a Monday
    assert copilot_fixture.paper_request("paper 2 NBIS 100c Friday, stop 96", "AMD", today) == [
        {"action": "open", "symbol": "NBIS", "quantity": 2, "idea": "mine", "stop": 96.0, "instrument": "option",
         "option_type": "call", "expiry": "2026-11-20", "strike": 100.0}]
    assert copilot_fixture.paper_request("paper 50 shares of PLTR", "AMD", today)[0]["instrument"] == "stock"
    assert copilot_fixture.paper_request("close my paper NBIS", "AMD", today) == [{"action": "close", "symbol": "NBIS"}]
    assert copilot_fixture.paper_request("sell half of my paper NBIS", "AMD", today) == [{"action": "trim", "symbol": "NBIS", "half": True}]
    assert "How many" in copilot_fixture.paper_request("paper NBIS calls", "NBIS", today)
    assert "Which NBIS contract" in copilot_fixture.paper_request("paper 2 NBIS calls", "NBIS", today)
    assert copilot_fixture.paper_request("how is my paper book doing?", "NBIS", today) is None


def test_a_scripted_desk_turn_carries_the_card_as_a_proposal_event():
    from app.engine.chart_math import ET

    async def turn():
        return [e async for e in copilot.run_turn([{"role": "user", "content": "paper 2 NBIS 100c Nov 20, stop 96"}], "NBIS",
                                                  copilot.settings(), copilot.FakeAdapter(0), FixtureEvidence(),
                                                  datetime.fromtimestamp(NOW, ET))]
    found = asyncio.run(turn())
    tool = next(e for e in found if e["type"] == "tool" and e["name"] == "draft_paper_order" and e["status"] == "ok")
    card = copilot.proposal_event(tool)
    assert card["kind"] == "paper_order" and card["action"] == "open" and card["stop"] == 96.0
    assert card["label"].startswith("NBIS $100 Call 11/20/") and card["preview"]["side"] == "ask"
    assert "Fill on paper" in "".join(e["delta"] for e in found if e["type"] == "text")


def test_a_close_says_what_a_working_limit_keeps_open(db, market):  # noqa: F811
    paper_book.start_run(db, 10_000, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 97.9, 98.1, last=98.0)}
    position = buy_call(db, qty=5)["filled"]["position_id"]
    paper_book.place_limit(db, {"action": "close", "order_type": "limit", "limit_price": 9.0, "position_id": position, "quantity": 2,
                                "order_key": key()}, NOW)
    close = draft._close(db, ask(action="close"), NOW)
    assert (close["quantity"], close["held"]) == (3, 3)
    assert close["picked"] == ["2 of the 5 are held for a working limit order and stay open; this sells the other 3."]


def test_a_long_picked_line_is_cut_so_the_card_still_saves():
    def down(symbol, pick, ttl):
        return [], "x" * 200
    picked = draft._said(draft.resolve("BRK.B", "call", "2026-11-20", 100, down)[2])
    assert len(picked[0]) == draft.PICKED_CHARS and draft._words_list(picked) == picked


def test_paper_book_questions_are_not_read_as_paper_orders():
    for words in ("paper book for NBIS?", "paper trading went how?", "paper mode please"):
        assert copilot_fixture.paper_request(words, "NBIS", date(2026, 11, 16)) is None
