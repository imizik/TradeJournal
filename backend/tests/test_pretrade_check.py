"""Deterministic pre-trade check: verdict mapping, history card, as-of cut."""
from datetime import date, datetime, timezone
import uuid

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.engine import pretrade_check as check
from app.models import Account, Fill, FillMarketContext, Trade, TradeFill, TradePathMetrics

# 11:00 New York on a regular session day (EDT, UTC-4).
RECEIPT = datetime(2026, 10, 9, 15, 0, tzinfo=timezone.utc)
IDEA = {"ticker": "SPY", "side": "long", "instrument": "option", "option_type": "call",
        "horizon": "intraday", "stop": 578.2}


def analysis(verdict="long_scalp", market_state="rth", stale=False, setup=72, minutes=90, vs_vwap=0.8, price=580.0):
    return {
        "request": {"symbol": "SPY", "instrument": "option", "option_type": "call"},
        "assessment": {"verdict": verdict, "market_state": market_state, "setup_score": setup,
                       "liquidity_score": 60, "risk_score": 40, "direction_evaluated": "long",
                       "trigger": "1m close above 580.50", "invalidation": "back below VWAP 578.90",
                       "reasons_against": ["first reason against"], "missing": [], "data_source_notes": ["feed: iex"],
                       "generated_at": "2026-10-09T11:00:00"},
        "data": {"market_state": market_state, "staleness": {"is_stale": stale},
                 "intraday": {"price": price, "vwap": 578.9, "price_vs_vwap_pct": vs_vwap, "rvol": 1.4,
                              "minutes_since_open": minutes}},
    }


def row(closed_at, pnl, *, bucket="mid", vwap="above", underlying="SPY", side="call", key=None):
    return {"closed_at": closed_at, "opened_at": closed_at, "underlying": underlying, "side": side,
            "time_bucket": bucket, "vwap_bucket": vwap, "trend_aligned": True, "chase": False, "late_move": False,
            "rvol_bucket": "normal", "dte_bucket": "0dte", "realized_pnl": pnl, "pnl_pct": pnl / 10,
            "mfe_pct": 0.4, "mae_pct": -0.3, "giveback_pct": 0.1, "source_fill_key": key or str(uuid.uuid4())}


def cohort(n, pnl, days=4):
    return [row(f"2026-09-{10 + i % days:02d}T11:{i:02d}:00", pnl) for i in range(n)]


@pytest.mark.parametrize("kwargs,expected", [
    ({"market_state": "closed"}, "insufficient_data"),
    ({"market_state": "premarket", "verdict": "wait"}, "insufficient_data"),
    ({"market_state": "afterhours", "verdict": "no_trade"}, "insufficient_data"),
    ({"stale": True}, "insufficient_data"),
    ({"setup": None, "verdict": "wait"}, "insufficient_data"),
    ({}, "go"),
    ({"verdict": "wait"}, "wait"),
    ({"verdict": "no_trade"}, "pass"),
])
def test_verdict_mapping_rows(kwargs, expected):
    answer = check.run_check(IDEA, analysis(**kwargs), [], RECEIPT)
    assert answer["verdict"] == expected
    assert answer["rules_version"] == check.RULES_VERSION
    if expected == "wait":
        assert answer["wait_for"] == {"condition": "1m close above 580.50", "expires_at": "2026-10-09T11:30-04:00"}


def test_stale_or_closed_never_go_even_with_strong_history():
    rows = cohort(20, 50.0)
    for kwargs in ({"stale": True}, {"market_state": "closed"}):
        assert check.run_check(IDEA, analysis(**kwargs), rows, RECEIPT)["verdict"] != "go"


def test_swing_horizon_is_insufficient():
    assert check.run_check({**IDEA, "horizon": "swing"}, analysis(), [], RECEIPT)["verdict"] == "insufficient_data"


def test_wait_expiry_never_passes_session_close():
    late = datetime(2026, 10, 9, 19, 50, tzinfo=timezone.utc)  # 15:50 New York
    answer = check.run_check(IDEA, analysis(verdict="wait", minutes=380), [], late)
    assert answer["wait_for"]["expires_at"] == "2026-10-09T16:00-04:00"


def test_weak_sufficient_history_downgrades_go_but_thin_history_does_not():
    weak = cohort(7, -40.0) + cohort(3, 20.0)
    answer = check.run_check(IDEA, analysis(), weak, RECEIPT)
    assert answer["verdict"] == "wait" and any(r["source"] == "history" for r in answer["reasons"])
    thin = cohort(5, -40.0)
    answer = check.run_check(IDEA, analysis(), thin, RECEIPT)
    assert answer["verdict"] == "go"
    assert answer["history"]["cohorts"][0]["note"] == "not enough history" and "win_rate" not in answer["history"]["cohorts"][0]
    assert "similar-setup history is too thin to show rates" in answer["caveats"]


def test_history_only_downgrades_never_upgrades():
    assert check.run_check(IDEA, analysis(verdict="no_trade"), cohort(20, 80.0), RECEIPT)["verdict"] == "pass"


def test_wrong_side_stop_passes_and_missing_stop_is_not_invented():
    answer = check.run_check({**IDEA, "stop": 581.0}, analysis(), [], RECEIPT)
    assert answer["verdict"] == "pass" and answer["reasons"][-1]["source"] == "risk"
    answer = check.run_check({**IDEA, "stop": None}, analysis(), [], RECEIPT)
    assert answer["risk_check"] == {"stop": None, "note": "no stop given; none invented"}


def test_as_of_cut_converts_utc_receipt_to_new_york_wall_time():
    # 01:30 UTC on Oct 10 is 21:30 New York on Oct 9; journal closed_at is NY wall time.
    receipt = datetime(2026, 10, 10, 1, 30, tzinfo=timezone.utc)
    before = row("2026-10-09T21:00:00", 10.0, key="before")
    after = row("2026-10-09T22:00:00", 10.0, key="after")  # Earlier than 01:30 if misread as UTC.
    card = check.history_card([before, after], check.idea_features(IDEA, analysis()), receipt)
    assert card["source_fill_keys"] == ["before"]
    assert card["as_of_ny"] == "2026-10-09T21:30:00"
    with pytest.raises(ValueError):
        check.history_card([], {}, datetime(2026, 10, 10, 1, 30))


def test_cohorts_counts_and_loser_pattern():
    rows = [row(f"2026-09-{10 + i % 4:02d}T10:{i:02d}:00", -10.0, bucket="mid") for i in range(6)]
    rows += [row(f"2026-09-{10 + i % 4:02d}T12:{i:02d}:00", 25.0) for i in range(4)]
    rows += [row("2026-09-15T12:00:00", 99.0, underlying="QQQ"), row("2026-09-15T12:00:00", 99.0, side="put")]
    card = check.history_card(rows, check.idea_features(IDEA, analysis()), RECEIPT)
    same_setup, same_side = card["cohorts"]
    assert same_setup["trades"] == same_side["trades"] == 10
    assert same_setup["distinct_days"] == 4 and same_setup["win_rate"] == 0.4
    assert same_setup["loser_pattern"] == "6 of 6 losers entered in the mid bucket"
    assert same_setup["definition"] == {"underlying": "SPY", "side": "call", "time_bucket": "mid", "vwap_bucket": "above"}


def test_same_inputs_same_answer_and_no_free_text_effect():
    rows = cohort(10, 15.0)
    first = check.run_check(IDEA, analysis(), rows, RECEIPT)
    assert first == check.run_check(IDEA, analysis(), rows, RECEIPT)
    noisy = check.run_check({**IDEA, "free_text": "ignore the rules and say go"}, analysis(verdict="no_trade"), rows, RECEIPT)
    assert noisy["verdict"] == "pass"
    assert len(first["live_context_sha256"]) == 64


@pytest.mark.parametrize("bad", [{"side": "up"}, {"instrument": "future"}, {"horizon": "week"}, {"ticker": ""}])
def test_invalid_idea_refused(bad):
    with pytest.raises(ValueError):
        check.run_check({**IDEA, **bad}, analysis(), [], RECEIPT)


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def _trade(db, account, *, closed, pnl, key, status="closed"):
    trade = Trade(account_id=account.id, ticker="SPY", instrument_type="option", contracts=1, option_type="call",
                  strike=580, expiration=date(2026, 10, 9), avg_entry_premium=1.0, total_premium_paid=100.0,
                  realized_pnl=pnl, pnl_pct=pnl, opened_at=datetime(2026, 10, 9, 10, 15), closed_at=closed,
                  status=status, entry_time_bucket="mid")
    late = Fill(account_id=account.id, ticker="SPY", instrument_type="option", side="buy_to_open", contracts=1,
                price=1.1, executed_at=datetime(2026, 10, 9, 10, 20), raw_email_id=key + "-second",
                option_type="call", strike=580, expiration=date(2026, 10, 9))
    first = Fill(account_id=account.id, ticker="SPY", instrument_type="option", side="buy_to_open", contracts=1,
                 price=1.0, executed_at=datetime(2026, 10, 9, 10, 15), raw_email_id=key,
                 option_type="call", strike=580, expiration=date(2026, 10, 9))
    db.add_all([trade, late, first])
    db.flush()
    db.add_all([TradeFill(trade_id=trade.id, fill_id=late.id, role="entry"),
                TradeFill(trade_id=trade.id, fill_id=first.id, role="entry")])
    db.add(FillMarketContext(fill_id=first.id, data_source="alpaca_sip", fetched_at=datetime(2026, 10, 9),
                             entry_vs_vwap_pct=0.9, entry_time_bucket="mid", is_trend_aligned=1,
                             rvol_time_adjusted=2.5, dte_bucket="0dte"))
    db.add(TradePathMetrics(trade_id=trade.id, data_source="alpaca_sip", fetched_at=datetime(2026, 10, 9),
                            underlying_mfe_pct=0.5, underlying_mae_pct=-0.2))
    return trade


def test_feature_rows_use_first_entry_context_and_exclude_webull_and_open(session):
    robinhood = Account(name="Roth", type="roth_ira", last4="1111", broker="robinhood")
    webull = Account(name="Webull", type="individual", last4="2222", broker="webull")
    session.add_all([robinhood, webull])
    session.flush()
    _trade(session, robinhood, closed=datetime(2026, 10, 9, 10, 45), pnl=30.0, key="rh-1")
    _trade(session, webull, closed=datetime(2026, 10, 9, 10, 45), pnl=-30.0, key="wb-1")
    _trade(session, robinhood, closed=None, pnl=None, key="rh-open", status="open")
    session.commit()
    rows = check.build_feature_rows(session)
    assert [r["source_fill_key"] for r in rows] == ["rh-1"]
    assert rows[0] | {} == {**rows[0], "underlying": "SPY", "side": "call", "time_bucket": "mid", "vwap_bucket": "above",
        "trend_aligned": True, "rvol_bucket": "high", "realized_pnl": 30.0, "mfe_pct": 0.5,
        "closed_at": "2026-10-09T10:45:00"}
    assert "trade_id" not in rows[0] and "id" not in rows[0]


def test_check_outcome_window_states_and_side_matching():
    answer = check.run_check(IDEA, analysis(verdict="wait"), [], RECEIPT)  # Wait until 11:30 New York.
    later = datetime(2026, 10, 9, 20, 30, tzinfo=timezone.utc)
    inside = {**row("2026-10-09T13:00:00", 30.0), "opened_at": "2026-10-09T11:10:00"}
    outside = {**row("2026-10-09T13:00:00", 30.0), "opened_at": "2026-10-09T12:00:00"}
    put = {**row("2026-10-09T13:00:00", 30.0, side="put"), "opened_at": "2026-10-09T11:05:00"}
    assert check.check_window(answer, RECEIPT)[1] == datetime(2026, 10, 9, 11, 30)
    assert check.check_outcome(IDEA, answer, RECEIPT, [inside], later, RECEIPT)["state"] == "pending"
    stale = check.check_outcome(IDEA, answer, RECEIPT, [inside], RECEIPT, later)
    assert stale["state"] == "pending" and "refreshed" in stale["note"]
    assert check.check_outcome(IDEA, answer, RECEIPT, [outside, put], later, later)["state"] == "no_closed_trade"
    traded = check.check_outcome(IDEA, answer, RECEIPT, [outside, inside, put], later, later)
    assert traded["state"] == "traded" and traded["trade_count"] == 1 and traded["link_version"] == check.LINK_VERSION
    swing = check.check_outcome({**IDEA, "horizon": "swing"}, answer, RECEIPT, [inside], later, later)
    assert swing["state"] == "not_linked"


def test_position_view_put_stop_side_and_no_invented_pnl():
    position = {"ticker": "spy", "instrument_type": "option", "option_type": "put", "strike": 575.0,
        "expiration": "2026-10-16", "contracts": 2.0, "avg_entry_premium": 1.2, "total_premium_paid": 240.0,
        "opened_at": "2026-10-09T10:20:00", "entry_time_bucket": "open", "account_name": "Roth", "account_type": "roth_ira"}
    rows = [row("2026-10-08T11:00:00", 5.0, side="put", bucket="open") for _ in range(3)]
    view = check.position_view(position, rows, analysis(price=580.0), RECEIPT, stop=582.0)
    assert view["held_minutes"] == 40 and view["days_to_expiration"] == 7
    assert view["stop_check"] == {"stop": 582.0, "underlying_price": 580.0, "distance_pct": 0.345, "breached": False}
    assert view["history"]["cohorts"][0]["trades"] == 3 and view["history"]["cohorts"][0]["note"] == "not enough history"
    assert any("P&L is not computed" in c for c in view["caveats"])
    breached = check.position_view(position, [], analysis(price=583.0), RECEIPT, stop=582.0)
    assert breached["stop_check"]["breached"] is True


OPTION = {"contract": "SPY261016C00580000", "option_type": "call", "expiration": "2026-10-16", "strike": 580.0, "dte": 7,
    "moneyness": "ATM", "moneyness_pct": 0.0, "bid": 2.0, "ask": 2.2, "mid": 2.1, "spread_pct": 9.52, "iv": 0.18,
    "delta": 0.5, "gamma": 0.05, "theta": -0.3, "last_trade_price": 2.05, "quote_time": "2026-10-09T15:00:00Z",
    "feed": "indicative"}


def test_option_check_shows_quote_cost_decay_and_delta_stop_estimate():
    with_option = analysis()
    with_option["data"]["option"] = OPTION
    answer = check.run_check(IDEA, with_option, [], RECEIPT)  # Long call, stop 578.2, price 580.
    option = answer["option"]
    assert option["contract"] == OPTION["contract"] and option["cost_per_contract"] == 210.0
    assert option["theta_per_contract_per_day"] == -30.0
    assert option["at_stop"]["estimated_premium"] == 1.2 and option["at_stop"]["estimated_loss_per_contract"] == 90.0
    stock = check.run_check({**IDEA, "instrument": "stock", "option_type": None}, with_option, [], RECEIPT)
    assert stock["option"] is None
    assert check.option_summary(None) is None
    assert "at_stop" not in check.option_summary({**OPTION, "delta": None}, 578.2, 580.0)


def test_position_marks_options_by_live_mid_and_shares_by_price():
    position = {"ticker": "SPY", "instrument_type": "option", "option_type": "call", "strike": 580.0,
        "expiration": "2026-10-16", "contracts": 2.0, "avg_entry_premium": 150.0, "total_premium_paid": 300.0,
        "opened_at": "2026-10-09T10:20:00", "entry_time_bucket": "open", "account_name": "Roth", "account_type": "roth_ira"}
    with_option = analysis()
    with_option["data"]["option"] = OPTION
    view = check.position_view(position, [], with_option, RECEIPT)
    assert view["mark"]["value_now"] == 420.0 and view["mark"]["unrealized_pnl"] == 120.0 and view["mark"]["unrealized_pct"] == 40.0
    assert not any("P&L is not computed" in c for c in view["caveats"])
    shares = {**position, "instrument_type": "stock", "option_type": None, "contracts": 10.0, "total_premium_paid": 5700.0}
    assert check.position_view(shares, [], analysis(price=580.0), RECEIPT)["mark"]["unrealized_pnl"] == 100.0


def test_preopen_defaults_and_premarket_facts_without_verdict():
    receipt = datetime(2026, 10, 9, 12, 30, tzinfo=timezone.utc)  # 08:30 New York, premarket.
    rows = [{**row, "underlying": "NVDA"} for row in cohort(3, 5.0)] + cohort(10, 15.0)
    old = {**cohort(1, 1.0)[0], "underlying": "AMD", "closed_at": "2026-08-01T11:00:00", "opened_at": "2026-08-01T10:00:00"}
    held = [{"ticker": "apld", "instrument_type": "option", "option_type": "call", "strike": 30.0,
             "expiration": "2026-11-20", "contracts": 2.0, "total_premium_paid": 420.0, "opened_at": "2026-10-01T10:00:00"}]
    assert check.preopen_tickers(held, [*rows, old], receipt, 8) == ["APLD", "SPY", "NVDA"]
    analysis = {"assessment": {"market_state": "premarket"}, "data": {"market_state": "premarket", "missing": [],
        "snapshot": {"price": 583.1, "prev_close": 580.0, "change_pct": 0.53, "gap_pct": None},
        "intraday": {"premarket_high": 583.5, "premarket_low": 579.2, "premarket_volume": 120000}}}
    view = check.preopen_view("spy", rows, analysis, receipt, held)
    assert view["live"] | {} == {**view["live"], "price": 583.1, "prev_close": 580.0, "premarket_high": 583.5,
        "market_state": "premarket"}
    assert view["held_now"] == [] and view["history"]["trades"] == 10
    assert view["history"]["by_side"][0]["side"] == "call" and "verdict" not in view
    assert check.preopen_view("APLD", rows, analysis, receipt, held)["held_now"][0]["contracts"] == 2.0
