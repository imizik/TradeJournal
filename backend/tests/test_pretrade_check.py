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


def daily(price=110.0, sma50=100.0, ema9=108.0, ema20=107.0, atr=3.0, rsi=58.0):
    base = analysis(market_state="closed")
    base["data"]["snapshot"] = {"price": price}
    base["data"]["daily"] = {"as_of_date": "2026-10-08", "last_close": price, "ema_9": ema9, "ema_20": ema20,
                             "sma_50": sma50, "sma_200": 90.0, "rsi_14": rsi, "atr_14": atr, "pct_vs_sma_50": 10.0,
                             "pct_vs_sma_200": 22.2}
    return base


@pytest.mark.parametrize("side,kwargs,expected", [
    ("long", {}, "go"),
    ("long", {"price": 95.0}, "pass"),                      # below the 50-day: against the trend
    ("long", {"rsi": 74.0}, "wait"),                       # RSI hot
    ("long", {"price": 110.0, "ema20": 104.0, "atr": 2.0}, "wait"),  # 3 ATR past the 20-day EMA
    ("long", {"ema9": 106.0}, "wait"),                      # pullback in progress
    ("short", {"price": 95.0, "sma50": 100.0, "ema9": 96.0, "ema20": 97.0, "rsi": 42.0}, "go"),
    ("short", {}, "pass"),
    ("long", {"sma50": None}, "insufficient_data"),
])
def test_swing_verdict_from_daily_bars(side, kwargs, expected):
    idea = {**IDEA, "horizon": "swing", "side": side, "option_type": "call" if side == "long" else "put", "stop": None}
    answer = check.run_check(idea, daily(**kwargs), [], RECEIPT)
    assert answer["verdict"] == expected and answer["rules_version"] == check.SWING_RULES_VERSION
    if expected == "wait":
        assert answer["wait_for"]["expires_at"] == "2026-10-12T16:00-04:00"  # Friday check: Monday's close.
    if expected != "insufficient_data":
        assert answer["live"]["daily"]["sma_50"] == kwargs.get("sma50", 100.0) and answer["would_change"]
        assert "earnings date and VIX not checked (market data unavailable)" in answer["caveats"]


def test_swing_stop_in_atr_and_overnight_history():
    idea = {**IDEA, "horizon": "swing", "stop": 104.0}
    answer = check.run_check(idea, daily(), [], RECEIPT)
    assert answer["risk_check"] | {} == {**answer["risk_check"], "distance_atr": 2.0, "distance_pct": 5.455}
    assert check.run_check({**idea, "stop": 112.0}, daily(), [], RECEIPT)["verdict"] == "pass"
    overnight = [{**r, "opened_at": r["closed_at"][:10] + "T10:00:00", "closed_at": "2026-09-2%dT11:00:00" % (i % 4)}
                 for i, r in enumerate(cohort(10, -20.0))]
    same_day = cohort(10, 50.0)
    weak = check.run_check({**idea, "stop": None}, daily(), overnight + same_day, RECEIPT)
    cohorts = {c["name"]: c for c in weak["history"]["cohorts"]}
    assert cohorts["same_ticker_side_overnight"]["trades"] == 10 and cohorts["same_ticker_side"]["trades"] == 20
    assert weak["verdict"] == "wait" and any(r["source"] == "history" for r in weak["reasons"])


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
        "staleness": {"is_stale": False, "last_trade_age_seconds": 40},
        "snapshot": {"price": 583.1, "prev_close": 580.0, "change_pct": 0.53, "gap_pct": None},
        "intraday": {"premarket_high": 583.5, "premarket_low": 579.2, "premarket_volume": 120000}}}
    view = check.preopen_view("spy", rows, analysis, receipt, held)
    assert view["live"] | {} == {**view["live"], "price": 583.1, "prev_close": 580.0, "premarket_high": 583.5,
        "market_state": "premarket"}
    assert view["held_now"] == [] and view["history"]["trades"] == 10 and view["news"] == []
    assert view["history"]["by_side"][0]["side"] == "call" and "verdict" not in view
    assert check.preopen_view("APLD", rows, analysis, receipt, held)["held_now"][0]["contracts"] == 2.0


def _bar(minute_utc, low, high, close):
    return {"t": f"2026-10-09T{minute_utc}:00Z", "o": close, "h": high, "l": low, "c": close}


def test_price_after_measures_the_window_in_the_ideas_direction():
    receipt = datetime(2026, 10, 9, 15, 0, tzinfo=timezone.utc)  # 11:00 New York.
    answer = {"verdict": "pass", "wait_for": None, "live": {"price": 100.0}}
    bars = [_bar("14:59", 99.0, 101.0, 100.0), _bar("15:10", 98.0, 101.5, 99.0), _bar("17:00", 97.0, 100.5, 98.0),
            _bar("20:00", 90.0, 110.0, 105.0)]  # Before the check and after the 16:00 close: ignored.
    after_close = datetime(2026, 10, 9, 21, 0, tzinfo=timezone.utc)
    long_idea = {"ticker": "SPY", "side": "long", "horizon": "intraday", "stop": 97.5}
    move = check.price_after(long_idea, answer, receipt, bars, after_close)
    assert move | {} == {**move, "state": "complete", "reference_price": 100.0, "last_price": 98.0,
        "move_pct": -2.0, "best_pct": 1.5, "worst_pct": -3.0, "stop_hit_ny": "2026-10-09T13:00"}
    short = check.price_after({**long_idea, "side": "short", "stop": None}, answer, receipt, bars, after_close)
    assert (short["move_pct"], short["best_pct"], short["worst_pct"]) == (2.0, 3.0, -1.5) and "stop_hit_ny" not in short
    during = check.price_after(long_idea, answer, receipt, bars[:2], datetime(2026, 10, 9, 15, 30, tzinfo=timezone.utc))
    assert during["state"] == "so_far"
    assert check.price_after(long_idea, answer, receipt, [], after_close)["state"] == "no_bars"
    assert check.price_after(long_idea, answer, receipt, None, after_close)["state"] == "unavailable"
    assert check.price_after(long_idea, {**answer, "live": {"price": None}}, receipt, bars, after_close)["state"] == "no_reference"
    assert check.price_after({**long_idea, "horizon": "swing"}, answer, receipt, bars, after_close)["state"] == "not_measured"


def test_grade_counts_followed_overrode_and_jo():
    def item(verdict, state, move, pnl=None, model=None):
        outcome = {"state": state, "total_pnl": pnl}
        return {"verdict": verdict, "model_verdict": model, "outcome": outcome,
                "move": {"state": "complete", "move_pct": move}}
    items = ([item("go", "traded", 0.5, 40.0, "go")] * 6 + [item("go", "no_closed_trade", 0.8)] * 2
             + [item("pass", "no_closed_trade", -0.4, model="pass")] * 9 + [item("pass", "traded", -0.6, -55.0, "go")] * 3
             + [item("insufficient_data", "no_closed_trade", 0.1)] + [item("go", "pending", 0.2)])
    grade = check.grade_results(items)
    assert grade["final_checks"] == 21 and grade["followed"] == 15 and grade["overrode"]["total"] == 5
    against = grade["overrode"]["traded_against_wait_or_pass"]
    assert against["checks"] == 3 and against["pnl"] == -165.0 and against["note"] == "not enough evidence"
    assert grade["overrode"]["skipped_a_go"]["median_move_pct"] == 0.8
    passes = grade["by_rules_verdict"]["pass"]
    assert passes["checks"] == 12 and passes["enough"] is True and passes["went_the_idea_way"] == 0
    assert passes["traded"] == 3 and passes["traded_pnl"] == -165.0
    assert grade["jo"] == {**grade["jo"], "with_verdict": 18, "agrees_with_rules": 15}


def test_result_final_waits_for_history_and_open_positions():
    receipt = datetime(2026, 10, 9, 15, 0, tzinfo=timezone.utc)  # 11:00 New York; window to 16:00.
    idea = {"ticker": "SPY", "side": "long", "instrument": "option", "option_type": "call", "horizon": "intraday"}
    answer = {"verdict": "pass", "wait_for": None, "live": {"price": 100.0}}
    result = {"outcome": {"state": "no_closed_trade"}, "move": {"state": "complete"}}
    morning = datetime(2026, 10, 10, 13, 0, tzinfo=timezone.utc)
    held = {"ticker": "spy", "instrument_type": "option", "option_type": "call", "opened_at": "2026-10-09T11:20:00"}
    assert check.result_final(idea, answer, receipt, result, morning, []) is True
    assert check.result_final(idea, answer, receipt, result, datetime(2026, 10, 9, 21, 0, tzinfo=timezone.utc), []) is False
    assert check.result_final(idea, answer, receipt, result, morning, None) is False
    assert check.result_final(idea, answer, receipt, result, morning, [held]) is False
    assert check.result_final(idea, answer, receipt, result, morning, [{**held, "option_type": "put"}]) is True
    assert check.result_final(idea, answer, receipt, result, morning, [{**held, "opened_at": "2026-10-08T11:00:00"}]) is True
    for state in ("pending", "not_linked"):
        assert check.result_final(idea, answer, receipt, {**result, "outcome": {"state": state}}, morning, []) is False
    assert check.result_final(idea, answer, receipt, {**result, "move": {"state": "unavailable"}}, morning, []) is False
    late = datetime(2026, 10, 9, 21, 0, tzinfo=timezone.utc)  # Checked at 17:00, after the close.
    assert check.price_after({**idea, "stop": None}, answer, late, [], morning)["state"] == "no_window"


def test_macro_calendar_flags_releases_today_and_inside_a_swing():
    cpi_morning = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)  # 08:00 New York; CPI (Sep 2026) at 08:30.
    answer = check.run_check(IDEA, analysis(market_state="premarket"), [], cpi_morning)
    assert [e["event"] for e in answer["macro"]["events"]] == ["CPI (Sep 2026)"]
    assert "CPI (Sep 2026) at 08:30 ET today: expect a volatility spike" in answer["caveats"]
    later = check.run_check(IDEA, analysis(), [], datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc))
    assert "CPI (Sep 2026) came out at 08:30 ET today" in later["caveats"]
    eve = datetime(2026, 10, 27, 20, 0, tzinfo=timezone.utc)  # FOMC decision next day at 14:00.
    assert not any("FOMC" in c for c in check.run_check(IDEA, analysis(), [], eve)["caveats"])
    swing = check.run_check({**IDEA, "horizon": "swing"}, daily(), [], eve)
    assert "FOMC decision at 14:00 ET next trading day: inside a swing hold" in swing["caveats"]
    uncovered = check.run_check(IDEA, analysis(), [], datetime(2030, 1, 2, 15, 0, tzinfo=timezone.utc))
    assert uncovered["macro"]["events"] is None and uncovered["caveats"][0].startswith("macro calendar unavailable")


def test_market_facts_flag_reports_near_the_trade_and_old_reads():
    receipt = datetime(2026, 10, 14, 13, 0, tzinfo=timezone.utc)  # Wednesday 09:00 New York.
    rows = [{"kind": "earnings", "symbol": "APLD", "event_date": "2026-10-15", "status": "confirmed", "label": "Q1 2027",
             "value": None, "change_pct": None, "observed_at": None, "fetched_at": "2026-10-10T12:00:00", "source": "Tradier"},
            {"kind": "vix", "symbol": "VIX", "event_date": None, "status": None, "label": None, "value": 15.2,
             "change_pct": -1.0, "observed_at": None, "fetched_at": "2026-10-14T12:55:00", "source": "Tradier"}]
    facts, notes = check.market_facts("apld", rows, receipt, "intraday", "2026-10-17")
    assert facts["earnings"]["days_away"] == 1 and facts["vix"]["value"] == 15.2
    assert notes == ["APLD reports earnings 2026-10-15 (confirmed): gap and IV-crush risk around the report",
                     "APLD reports earnings 2026-10-15 (confirmed): before this option expires",
                     "earnings date is from an older calendar read"]
    quiet, notes = check.market_facts("MU", rows, receipt, "intraday")
    assert quiet["earnings"]["date"] is None
    assert notes == ["earnings date not checked for MU (not in the tracked calendar)"]  # Absence is not "none".
    assert check.market_facts("SPY", rows, receipt, "swing")[1] == []  # Funds have no earnings.
    assert check.market_facts("SPY", [rows[0]], receipt, "intraday")[1] == ["VIX unavailable"]
    broken = [{**rows[0], "event_date": None}, rows[1]]
    facts, notes = check.market_facts("APLD", broken, receipt, "swing")  # A bad row never crashes the check.
    assert facts["earnings"]["date"] is None and notes == ["earnings date for APLD unreadable; not checked"]
    old_quote = [{**rows[1], "observed_at": "2026-10-13T20:15:00"}]  # Fetched just now, traded yesterday.
    assert "VIX is 17 h old" in check.market_facts("SPY", old_quote, receipt, "intraday")[1]


def test_preopen_flags_old_premarket_prints_and_withholds_last_sessions_change():
    receipt = datetime(2026, 10, 13, 13, 22, tzinfo=timezone.utc)  # 09:22 New York.

    def read(age):
        return {"assessment": {"market_state": "premarket"}, "data": {"market_state": "premarket", "missing": [],
            "staleness": {"is_stale": False, "last_trade_age_seconds": age},
            "snapshot": {"price": 210.83, "prev_close": 210.14, "change_pct": 0.33, "gap_pct": 0.1,
                         "last_trade_time": "2026-10-12T19:59:58Z"}, "intraday": {}}}
    fresh = check.preopen_view("QQQ", [], read(37), receipt)
    assert fresh["live"]["fresh"] is True and fresh["live"]["change_pct"] == 0.33 and fresh["caveats"] == []
    old = check.preopen_view("MU", [], read(17 * 60), receipt)
    assert old["live"]["fresh"] is False and old["live"]["change_pct"] == 0.33
    assert "last trade 17 min old; premarket is thin, confirm on your broker" in old["caveats"]
    overnight = check.preopen_view("NBIS", [], read(17 * 3600), receipt)
    assert overnight["live"]["change_pct"] is None and overnight["live"]["gap_pct"] is None
    assert overnight["caveats"][0].startswith("no trade since the last session (last 2026-10-12T19:59:58Z)")
    assert check.preopen_view("NBIS", [], read(None), receipt)["live"]["fresh"] is False
