"""A labeled offline market/reviewer boundary for the existing browser server.

The production routes, context builder, persistence and UI remain real. Only
external market reads and inference are replaced; this never loads in the app.
"""
from datetime import datetime, time, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException


def install(app):
    expected = Path(__file__).resolve().parents[3] / "backend/data/e2e_seed.db"
    if os.environ.get("DATABASE_URL") != f"sqlite:///{expected}":
        raise RuntimeError("Day journal review fixture requires the disposable e2e database")

    from app.ai import plan_runner, review_context

    names = ("daily_moves", "intraday_shape", "gauges", "company_facts", "_headlines", "open_interest_walls")
    originals = {name: getattr(review_context, name) for name in names}
    original_ask = plan_runner.ask
    state = {"mode": "off"}

    def stamp(day):
        return datetime.combine(day, time(20), timezone.utc).isoformat()

    def daily_moves(day, symbols):
        if state["mode"] == "missing":
            return {}
        return {symbol: {"source": "synthetic-browser-fixture", "source_bar_at": stamp(day),
                         "change_pct": -0.52, "gap_pct": 0, "open_to_close_pct": -0.52,
                         "close_in_range": 0.1, "range_vs_20d": 1.2, "close": 577.0}
                for symbol in symbols}

    def intraday_shape(day):
        if state["mode"] == "missing":
            return {}
        return {"SPY": {"source": "synthetic-browser-fixture", "source_bar_at": stamp(day),
                        "trend_efficiency": 0.6, "close_vs_vwap_pct": -0.3,
                        "high_at": "10:00", "low_at": "15:50", "first_hour_share_of_range": 0.4}}

    def ask(system, message, schema):
        context = json.loads(message.split("\n\n", 1)[1])
        day = context["day"]
        thoughts = context["day_context"].get("owner_timeline", [])
        checks = []
        for entry in thoughts:
            if entry["kind"] not in {"outlook", "idea"}:
                continue
            retrospective = entry.get("retrospective", False)
            missing = state["mode"] == "missing"
            checks.append({
                "entry_id": entry["id"], "expected": entry["text"],
                "observed": "Market observations unavailable." if missing else "Synthetic SPY fixture closed at 577; this is invented market data.",
                "assessment": "unresolved" if retrospective or missing else "invalidated",
                "evidence": ("No timestamped market observations are available." if missing else
                             f"synthetic-browser-fixture, {day}T20:00:00+00:00; thought recorded {entry['created_at']}.")
                            + (" Recorded after the selected session; not a prospective forecast." if retrospective else ""),
            })
        data = {
            "summary": "Synthetic review fixture: owner thoughts and saved revisions reached the real review route.",
            "day_grade": "Not graded — synthetic review",
            "key_takeaways": ["A changed view stays separate from the original expectation."],
            "best_trade": {"trade_id": None, "ticker": None, "reason": "No trade ranking in this synthetic review."},
            "worst_trade": {"trade_id": None, "ticker": None, "reason": "No trade ranking in this synthetic review."},
            "patterns": [], "next_session_rules": [], "rules_check": [], "vs_baseline": [],
            "data_gaps": ["Synthetic market and reviewer boundary; no external model was called."] + context["day_context"].get("gaps", []),
            "market_read": "Market observations unavailable." if state["mode"] == "missing" else
                           "Synthetic market fixture: SPY closed at 577. Invented data for UI integration; not a live market result.",
            "plan_vs_execution": [], "expectation_checks": checks,
        }
        return SimpleNamespace(data=data, author="Synthetic browser fixture (no model call)", input_tokens=0,
                               output_tokens=0, api_equivalent_usd=0, seconds=0)

    @app.post("/__test/day-journal-review", include_in_schema=False)
    def configure(mode: str):
        if mode not in {"ready", "missing", "off"}:
            raise HTTPException(400, "Invalid day journal fixture mode")
        state["mode"] = mode
        if mode == "off":
            for name, value in originals.items():
                setattr(review_context, name, value)
            plan_runner.ask = original_ask
        else:
            review_context.daily_moves = daily_moves
            review_context.intraday_shape = intraday_shape
            review_context.gauges = lambda day: None
            review_context.company_facts = lambda symbols, day: {symbol: {"sector_state": "none", "earnings": {"state": "none"}} for symbol in symbols}
            review_context._headlines = lambda day, symbols, gaps: {}
            review_context.open_interest_walls = lambda *args, **kwargs: None
            plan_runner.ask = ask
        return {"mode": mode, "provenance": "synthetic-browser-fixture"}
