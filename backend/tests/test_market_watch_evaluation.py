from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.engine.market_watch_evaluation import (
    MarketWatchEvaluationError, MarketWatchOutcomeStore, evaluate_forecast as _evaluate_forecast,
    session_diagnostic as _session_diagnostic,
)
from market_watch_common import digest


ET = timezone(timedelta(hours=-4))
SOURCE = {"provider": "Alpaca", "feed": "iex", "adjustment": "split",
          "price_basis": "split-consistent_non-dividend-adjusted", "retrieved_at": "2026-10-14T14:05:00Z"}


def evaluate_forecast(*args, **kwargs):
    kwargs.setdefault("bar_source", SOURCE)
    return _evaluate_forecast(*args, **kwargs)


def session_diagnostic(*args, **kwargs):
    kwargs.setdefault("bar_source", SOURCE)
    return _session_diagnostic(*args, **kwargs)


def minute(at, close, *, high=None, low=None, open_=None):
    return {"start": at.isoformat(), "open": close if open_ is None else open_,
            "high": close if high is None else high, "low": close if low is None else low,
            "close": close, "volume": 100}


def test_frozen_forecast_scores_exact_endpoints_tie_and_directional_path():
    opening = datetime(2026, 10, 14, 9, 30, tzinfo=ET)
    received = datetime(2026, 10, 14, 9, 30, 10, tzinfo=ET)
    bars = [minute(opening + timedelta(minutes=i), 100 if i != 30 else 99,
                   high=102 if i == 2 else (100 if i == 30 else 101),
                   low=99 if i == 2 else (99 if i == 30 else 100)) for i in range(33)]
    read = {"read_id": "r1", "received_at": received.isoformat(), "protocol_id": "mw-v1", "view": "up"}
    forecast = {"forecast_id": "f1", "horizon": "30m", "probability": 0.8}
    result = evaluate_forecast(read, forecast, bars, session_open_at=opening,
                               session_close_at=opening + timedelta(hours=6, minutes=30),
                               evaluated_at=opening + timedelta(minutes=48), comparator_probability=0.65)
    assert result["status"] == "scored"
    assert result["anchor_price"] == 100
    assert result["target_price"] == 99
    assert result["return"] == pytest.approx(-0.01)
    assert result["outcome_y"] == 1
    assert result["brier"] == pytest.approx(0.04)
    assert result["comparator_brier"] == pytest.approx(0.1225)
    assert result["favorable_excursion"] == pytest.approx(2 / 100)
    assert result["adverse_excursion"] == pytest.approx(1 / 100)


def test_tie_scores_zero_and_missing_interior_only_removes_path():
    opening = datetime(2026, 10, 14, 9, 30, tzinfo=ET)
    received = opening + timedelta(seconds=10)
    bars = [minute(opening + timedelta(minutes=i), 100) for i in range(32) if i != 8]
    read = {"read_id": "r", "received_at": received.isoformat(), "protocol_id": "mw-v1", "view": "down"}
    result = evaluate_forecast(read, {"forecast_id": "f", "horizon": "30m", "probability": 0.7}, bars,
                               session_open_at=opening, session_close_at=opening + timedelta(hours=6, minutes=30),
                               evaluated_at=opening + timedelta(minutes=48))
    assert result["status"] == "scored"
    assert result["outcome_y"] == 0 and result["brier"] == pytest.approx(0.49)
    assert result["path_status"] == "missing_intermediate_bars"
    assert result["adverse_excursion"] is None


def test_pending_then_abstention_and_late_session_ineligibility():
    opening = datetime(2026, 10, 14, 9, 30, tzinfo=ET)
    bars = [minute(opening + timedelta(minutes=i), 100) for i in range(390)]
    base = {"read_id": "r", "received_at": (opening + timedelta(seconds=1)).isoformat(),
            "protocol_id": "mw-v1", "view": "no_view"}
    f = {"forecast_id": "f", "horizon": "close", "probability": None, "abstention_reason": "no_view"}
    common = dict(bars=bars, session_open_at=opening, session_close_at=opening + timedelta(hours=6, minutes=30))
    pending = evaluate_forecast(base, f, evaluated_at=opening + timedelta(hours=6, minutes=30, seconds=1), **common)
    assert pending["status"] == "pending"
    done = evaluate_forecast(base, f, evaluated_at=opening + timedelta(hours=6, minutes=45), **common)
    assert done["status"] == "abstained"
    late = {**base, "received_at": (opening + timedelta(hours=6, minutes=5)).isoformat()}
    ineligible = evaluate_forecast(late, {"forecast_id": "g", "horizon": "60m", "probability": .5},
                                   evaluated_at=opening + timedelta(hours=6, minutes=30), **common)
    assert ineligible["status"] == "not_eligible"


def test_evaluation_store_is_immutable_idempotent_and_rejects_tamper(tmp_path):
    store = MarketWatchOutcomeStore(tmp_path / "outcomes.sqlite3")
    opening = datetime(2026, 10, 14, 9, 30, tzinfo=ET)
    bars = [minute(opening + timedelta(minutes=i), 100) for i in range(32)]
    result = evaluate_forecast({"read_id": "r", "received_at": (opening + timedelta(seconds=1)).isoformat(),
                                "protocol_id": "mw-v1", "view": "mixed"},
                               {"forecast_id": "f", "horizon": "30m", "probability": .5}, bars,
                               session_open_at=opening, session_close_at=opening + timedelta(hours=6, minutes=30),
                               evaluated_at=opening + timedelta(minutes=48))
    assert store.append_evaluations([result]) == 1
    assert store.append_evaluations([result]) == 0
    damaged = {**result, "brier": 7}
    with pytest.raises(MarketWatchEvaluationError):
        store.append_evaluations([damaged])
    with store._db() as db, pytest.raises(Exception, match="immutable"):
        db.execute("DELETE FROM evaluation")
    with store._db() as db, pytest.raises(Exception, match="immutable"):
        db.execute("INSERT OR REPLACE INTO evaluation VALUES(?,?,?,?,?,?)",
                   (result["outcome_id"], "r", "f", "30m", 1, "{}"))


def test_session_diagnostic_uses_fourteen_prior_complete_sessions_and_manual_coverage():
    opening = datetime(2026, 10, 14, 9, 30, tzinfo=ET)
    close = opening + timedelta(hours=6, minutes=30)
    today = [minute(opening + timedelta(minutes=i), 100 + i * .1,
                    high=max(100 + i * .1, 100 if i == 0 else 100 + (i - 1) * .1) + .05,
                    low=min(100 + i * .1, 100 if i == 0 else 100 + (i - 1) * .1) - .05,
                    open_=100 if i == 0 else 100 + (i - 1) * .1) for i in range(390)]
    prior = []
    roster = []
    session_source = {**SOURCE, "retrieved_at": "2026-10-14T20:05:00Z"}
    day_date = datetime(2026, 9, 23, tzinfo=ET).date()
    session_date = datetime(2026, 10, 14, tzinfo=ET).date()
    while day_date <= session_date:
        opened = day_date.weekday() < 5 and day_date.isoformat() != "2026-10-12"
        day_open = datetime.combine(day_date, datetime.min.time(), ET).replace(hour=9, minute=30) if opened else None
        day_close = day_open + timedelta(hours=6, minutes=30) if day_open else None
        roster.append({"session_date": day_date.isoformat(), "status": "open" if opened else "closed",
                       "open_at": day_open.isoformat() if day_open else None,
                       "close_at": day_close.isoformat() if day_close else None})
        if opened and day_date < session_date:
            prior.append({"session_date": day_date.isoformat(), "session_open_at": day_open.isoformat(),
                              "session_close_at": day_close.isoformat(), "previous_close": 100.0, "bar_source": session_source,
                          "bars": [minute(day_open + timedelta(minutes=i), 100, high=101, low=99) for i in range(390)]})
        day_date += timedelta(days=1)
    prior = prior[-14:]
    out = session_diagnostic(session_date="2026-10-14", read_rows=[], today_bars=today,
                             prior_sessions=prior, session_open_at=opening, session_close_at=close,
                             calendar_roster=roster, bar_source=session_source,
                             evaluated_at=close + timedelta(minutes=15))
    assert out["prior_atr14"] == 2
    assert out["day_label"] == "up_trend"
    assert out["coverage_status"] == "manual_partial"
    assert out["missed_before_noon"] is True
    diagnostics = session_diagnostic(session_date="2026-10-14", read_rows=[
        {"received_at": datetime(2026, 10, 14, 8, 0, tzinfo=ET).isoformat(), "view": "down"},
        {"received_at": datetime(2026, 10, 14, 12, 5, tzinfo=ET).isoformat(), "view": "up"},
        {"received_at": datetime(2026, 10, 14, 12, 10, tzinfo=ET).isoformat(), "view": "down"}],
        today_bars=today, prior_sessions=prior, session_open_at=opening, session_close_at=close,
        calendar_roster=roster, bar_source=session_source, evaluated_at=close + timedelta(minutes=15))
    assert diagnostics["first_directional_read_at"].startswith("2026-10-14T16:05")
    assert diagnostics["missed_before_noon"] is True and diagnostics["late_only"] is True
    assert diagnostics["opposite_direction"] is True


def test_session_coverage_does_not_claim_whole_day_when_history_missing():
    opening = datetime(2026, 10, 14, 9, 30, tzinfo=ET)
    out = session_diagnostic(session_date="2026-10-14", read_rows=[], today_bars=[], prior_sessions=[],
                             session_open_at=opening, session_close_at=opening + timedelta(hours=6, minutes=30))
    assert out["day_label"] == "unavailable"
    assert out["coverage_status"] == "manual_partial"


def test_known_market_closed_holiday_is_ineligible_not_calendar_unavailable():
    read = {"read_id": "holiday-read", "received_at": "2026-10-12T14:00:00Z",
            "protocol_id": "mw-v1", "view": "no_view"}
    forecast = {"forecast_id": "holiday-f", "horizon": "30m", "probability": 0.5}
    result = evaluate_forecast(read, forecast, [], session_open_at=None, session_close_at=None,
                               market_phase="market_closed", evaluated_at="2026-10-12T14:01:00Z")
    assert result["status"] == "not_eligible" and result["reason"] == "exchange_closed"
    session = session_diagnostic(session_date="2026-10-12", read_rows=[], today_bars=[], prior_sessions=[],
                                 session_open_at=None, session_close_at=None, market_phase="market_closed",
                                 evaluated_at="2026-10-12T20:00:00Z")
    assert session["day_label"] == "unavailable" and session["reason"] == "exchange_closed"


def test_corrected_revision_is_append_only_idempotent_and_keeps_quality_cohort(tmp_path):
    store = MarketWatchOutcomeStore(tmp_path / "revision-outcomes.sqlite")
    opening = datetime(2026, 10, 14, 9, 30, tzinfo=ET)
    bars = [minute(opening + timedelta(minutes=i), 100 if i < 31 else 101) for i in range(32)]
    read = {"read_id": "revision-read", "received_at": (opening + timedelta(seconds=5)).isoformat(),
            "protocol_id": "mw-v1", "view": "up", "model_id": "model-a", "prompt_version": "p1",
            "quality_flags": ["snapshot-stale", "SPY:stale", "QQQ:stale"], "forecasts": []}
    forecast = {"forecast_id": "revision-forecast", "horizon": "30m", "probability": 0.8}
    read["forecasts"] = [forecast]
    common = dict(session_open_at=opening, session_close_at=opening + timedelta(hours=6, minutes=30),
                  evaluated_at=opening + timedelta(minutes=48), bar_source=SOURCE)
    original = _evaluate_forecast(read, forecast, bars, **common)
    assert store.append_evaluations([original]) == 1
    corrected = _evaluate_forecast(read, forecast, bars, revision=2,
                                   supersedes_outcome_id=original["outcome_id"], **common)
    assert store.append_evaluations([corrected]) == 1
    assert store.append_evaluations([corrected]) == 0
    conflicting = {**corrected, "reason": "changed after append"}
    conflicting["content_sha256"] = digest({k: v for k, v in conflicting.items() if k != "content_sha256"})
    with pytest.raises(MarketWatchEvaluationError, match="revision already exists"):
        store.append_evaluations([conflicting])
    rows = store.outcomes()
    assert len(rows) == 2 and {row["evaluation_revision"] for row in rows} == {1, 2}
    report = store.report([read])
    cohorts = {group["evaluation_revision"]: group for group in report["groups"]}
    assert report["total_submitted_slots"] == 1
    for cohort in cohorts.values():
        assert cohort["submitted"] == 1
        assert cohort["stale_input_count"] == 1  # three stale flags, one affected slot
        assert cohort["quality_flags"] == read["quality_flags"]
        assert cohort["quality_flag_counts"] == {flag: 1 for flag in read["quality_flags"]}


def test_sealed_ledger_export_import_evaluate_and_report_end_to_end(tmp_path):
    from cloud_mcp_check_ledger import Ledger
    from market_watch_ledger import MarketWatchLedger
    from tests.test_market_watch_ledger import ACTOR, request
    from tests.test_market_watch_snapshot import fixture_snapshot, NOW

    ledger = MarketWatchLedger(Ledger(tmp_path / "check.sqlite"))
    supplied = ledger.serve(ACTOR, fixture_snapshot(), lambda: NOW)
    receipt = ledger.submit(ACTOR, request(supplied["input_id"], message_intent="none"), lambda: NOW)
    exported = ledger.export(ledger.ledger.path, ACTOR)
    store = MarketWatchOutcomeStore(tmp_path / "owner-outcomes.sqlite3")
    assert store.import_export(exported) is False
    assert store.import_export(exported) is True
    assert store.imported_exports() == [exported]
    pending_report = store.report(exported["reads"])
    assert pending_report["total_submitted_slots"] == 3
    assert all(group["submitted"] == 1 and group["pending"] == 1 for group in pending_report["groups"])
    opening = datetime(2026, 10, 14, 9, 30, tzinfo=ET)
    closing = datetime(2026, 10, 14, 16, 0, tzinfo=ET)
    session_source = {**SOURCE, "retrieved_at": "2026-10-14T20:05:00Z"}
    bars = [minute(opening + timedelta(minutes=i), 100 if i < 389 else 99) for i in range(390)]
    evaluated = store.evaluate_export(exported, bars_by_session={"2026-10-14": bars},
                                      evaluated_at=closing + timedelta(minutes=16),
                                      bar_source_by_date={"2026-10-14": session_source})
    assert evaluated["inserted_outcomes"] == 3
    assert store.evaluate_export(exported, bars_by_session={"2026-10-14": bars},
                                 evaluated_at=closing + timedelta(minutes=16),
                                     bar_source_by_date={"2026-10-14": session_source})["inserted_outcomes"] == 0
    report = store.report(exported["reads"])
    assert report["total_submitted_slots"] == 3
    assert len(report["groups"]) == 3
    assert all(group["scored"] == 1 and group["comparator_brier"] is not None and
               group["paired_jo_brier"] is not None for group in report["groups"])
    assert receipt["read_id"] == exported["reads"][0]["read_id"]


def test_missing_exact_anchor_is_unavailable_and_not_reanchored():
    opening = datetime(2026, 10, 14, 9, 30, tzinfo=ET)
    bars = [minute(opening + timedelta(minutes=i), 100) for i in range(32) if i != 0]
    result = evaluate_forecast({"read_id": "r", "received_at": (opening + timedelta(seconds=5)).isoformat(),
                                "protocol_id": "mw-v1", "view": "down"},
                               {"forecast_id": "f", "horizon": "30m", "probability": .5}, bars,
                               session_open_at=opening, session_close_at=opening + timedelta(hours=6, minutes=30),
                               evaluated_at=opening + timedelta(minutes=60))
    assert result["status"] == "unavailable"
    assert result["reason"] == "exact_anchor_or_target_bar_missing"
    assert result["anchor_at"] == (opening + timedelta(minutes=1)).astimezone(timezone.utc).isoformat()


def test_missing_anchor_waits_through_forecast_grace_and_late_target_is_ineligible():
    opening = datetime(2026, 10, 14, 9, 30, tzinfo=ET)
    bars = [minute(opening + timedelta(minutes=i), 100) for i in range(390) if i != 0]
    read = {"read_id": "r", "received_at": (opening + timedelta(seconds=5)).isoformat(),
            "protocol_id": "mw-v1", "view": "down"}
    args = {"bars": bars, "session_open_at": opening,
            "session_close_at": opening + timedelta(hours=6, minutes=30)}
    pending = evaluate_forecast(read, {"forecast_id": "f", "horizon": "30m", "probability": .5},
                                evaluated_at=opening + timedelta(minutes=45), **args)
    assert pending["status"] == "pending" and pending["anchor_at"] is not None
    late_read = {**read, "received_at": (opening + timedelta(hours=6, minutes=5)).isoformat()}
    late = evaluate_forecast(late_read, {"forecast_id": "late", "horizon": "60m", "probability": .5},
                             evaluated_at=opening + timedelta(hours=6, minutes=6), **args)
    assert late["status"] == "not_eligible"


def test_half_day_target_and_dst_local_noon_are_calendar_bound(tmp_path):
    et = ZoneInfo("America/New_York")
    opening = datetime(2026, 11, 27, 9, 30, tzinfo=et)
    closing = datetime(2026, 11, 27, 13, 0, tzinfo=et)  # exchange half-day
    bars = [minute(opening + timedelta(minutes=i), 100) for i in range(210)]
    read = {"read_id": "r", "received_at": datetime(2026, 11, 27, 12, 30, tzinfo=et).isoformat(),
            "protocol_id": "mw-v1", "view": "down"}
    out = evaluate_forecast(read, {"forecast_id": "f", "horizon": "60m", "probability": .5}, bars,
                            session_open_at=opening, session_close_at=closing,
                            evaluated_at=closing + timedelta(minutes=15))
    assert out["status"] == "not_eligible"
    assert out["reason"] == "outside_regular_session_or_target"
    assert opening.utcoffset() == timedelta(hours=-5)  # after the DST transition


def test_calendar_unavailable_is_explicit_unavailable_not_invented_session():
    opening = datetime(2026, 10, 14, 9, 30, tzinfo=ET)
    bar = minute(opening, 100)
    outcome = evaluate_forecast({"read_id": "r", "received_at": opening.isoformat(), "protocol_id": "mw-v1", "view": "no_view"},
                                {"forecast_id": "f", "horizon": "close", "probability": .5}, [bar],
                                session_open_at=None, session_close_at=None, evaluated_at=opening)
    session = session_diagnostic(session_date="2026-10-14", read_rows=[], today_bars=[bar], prior_sessions=[],
                                 session_open_at=None, session_close_at=None)
    assert outcome["status"] == "unavailable" and outcome["reason"] == "session_calendar_unavailable"
    assert session["day_label"] == "unavailable" and session["reason"] == "session_calendar_unavailable"


def test_import_rejects_cross_actor_tamper_and_store_actor_mixing(tmp_path):
    from market_watch_common import seal, digest
    from cloud_mcp_check_ledger import Ledger
    from market_watch_ledger import MarketWatchLedger
    from tests.test_market_watch_ledger import ACTOR, OTHER, request
    from tests.test_market_watch_snapshot import fixture_snapshot, NOW

    ledger = MarketWatchLedger(Ledger(tmp_path / "check.sqlite"))
    supplied = ledger.serve(ACTOR, fixture_snapshot(), lambda: NOW)
    ledger.submit(ACTOR, request(supplied["input_id"], message_intent="none"), lambda: NOW)
    exported = ledger.export(ledger.ledger.path, ACTOR)
    store = MarketWatchOutcomeStore(tmp_path / "owner.sqlite")
    bad_read = seal({**exported["reads"][0], "actor": OTHER})
    rows = {k: exported[k] for k in ("inputs", "comparators", "messages")}
    rows["reads"] = [bad_read]
    bad = seal({"export_id": "mwx_" + digest(rows), "actor": ACTOR, "protocol_id": "mw-v1", **rows})
    with pytest.raises(MarketWatchEvaluationError, match="cross-actor"):
        store.import_export(bad)
    store.import_export(exported)
    other_ledger = MarketWatchLedger(Ledger(tmp_path / "check-other.sqlite"))
    other_input = other_ledger.serve(OTHER, fixture_snapshot(), lambda: NOW)
    other_ledger.submit(OTHER, request(other_input["input_id"], message_intent="none"), lambda: NOW)
    with pytest.raises(MarketWatchEvaluationError, match="different owner actor"):
        store.import_export(other_ledger.export(other_ledger.ledger.path, OTHER))
