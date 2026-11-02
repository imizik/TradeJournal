"""The copilot's symbol profile and proof reads (docs/copilot-lab.md § What runs).

``get_symbol_profile`` composes what the Symbol page's Overview, Events, Short interest and Analysts tabs already
cache: company and valuation, 13F ownership, the next earnings, dividend and splits, FINRA short interest and the
borrow flag, analyst targets, ratings and estimates. Each block is read on its own, so a cold or failed one says
``unavailable`` and the rest stands; every figure carries its source and fetch time, since the caches are a day old.
``get_proof`` is the product's own proof read-out (exit habits, plan proof, outcomes, the alert scorecard) as counts
and verdicts the owner can ask about; it never turns a count into a judgement of them. Nothing here writes.
"""
from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Callable

log = logging.getLogger(__name__)

DESCRIPTION_CHARS = 240
MAX_ACTIONS = 3
MAX_SPLITS = 3
SCORECARD_DAYS = 30
PROFILE_NOTE = ("Fundamentals and ownership are Tradier's, cached a day; short interest is FINRA's twice-monthly settlement "
                "(about two weeks behind); analyst figures are unofficial (Yahoo / Webull). Name the source and age of any "
                "figure you quote.")
PROOF_NOTE = ("Counts and verdicts from the product's own proof pages. 'not_enough_data' is the honest state until the rules' "
              "samples are met; never turn a count into a judgement of the owner. The Radar proof is not here: the Proof "
              "page's Radar tile shows it.")


def _iso(epoch: float | int | None) -> str | None:
    return None if epoch is None else datetime.fromtimestamp(float(epoch), UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _block(name: str, build: Callable[[], dict]) -> dict:
    """One part of the answer; a failure marks that part unavailable and leaves the others."""
    try:
        return build()
    except Exception as exc:  # noqa: BLE001 - one cold or failing source must not take the whole profile down
        log.warning("copilot %s unavailable: %s", name, type(exc).__name__)
        return {"state": "unavailable", "reason": f"{name} could not be read right now."}


# --------------------------------------------------------------------------- the symbol profile

def _overview(symbol: str) -> dict:
    from app.engine import symbol_info_tradier
    raw = symbol_info_tradier.symbol_events.overview(symbol)
    sets = raw["datasets"]
    company, ratios, stats = sets["company"], sets["ratios"], sets["statistics"]
    ownership = company.get("ownership") or {}
    return {
        "state": raw["state"],
        "company": {"state": company["state"], "fetched_at": _iso(company.get("fetched_at")), "message": company.get("message"),
                    "name": company.get("name"), "sector": company.get("sector"), "employees": company.get("employees"),
                    "ipo_date": company.get("ipo_date"), "description": (company.get("description") or "")[:DESCRIPTION_CHARS] or None},
        "valuation": {"state": ratios["state"], "fetched_at": _iso(ratios.get("fetched_at")), "message": ratios.get("message"),
                      "market_cap": stats.get("market_cap"), "enterprise_value": stats.get("enterprise_value"),
                      "shares_outstanding": stats.get("shares_outstanding"), "pe": ratios.get("pe"),
                      "price_to_sales": ratios.get("price_to_sales"), "price_to_book": ratios.get("price_to_book"),
                      "ev_to_ebitda": ratios.get("ev_to_ebitda"), "beta_60_month": ratios.get("beta_60_month"),
                      "average_volume_30_day": stats.get("average_volume_30_day")},
        "ownership": {"state": "ready" if ownership.get("percent_held") is not None else company["state"],
                      "institutional_pct": stats.get("institutional_ownership"), "holders_13f": ownership.get("holders"),
                      "as_of": ownership.get("as_of")},
    }


def _events(symbol: str, today: date) -> dict:
    from app.engine import symbol_info_tradier
    raw = symbol_info_tradier.symbol_events.events(symbol, today)
    earnings, dividends, splits = raw["earnings"], raw["dividends"], raw["splits"]
    return {"state": earnings.get("state"), "fetched_at": _iso(earnings.get("fetched_at")), "message": earnings.get("message"),
            "next_earnings": earnings.get("next"), "last_report": (earnings.get("reports") or [None])[0],
            "dividends": {"state": dividends.get("state"), "next": dividends.get("next"), "last": dividends.get("last")},
            "splits": [{"ex_date": s["ex_date"], "label": s["label"]} for s in (splits.get("rows") or [])[:MAX_SPLITS]]}


def _short(symbol: str) -> dict:
    from app.engine import symbol_info_short_feed
    raw = symbol_info_short_feed.short_feed.view(symbol)
    interest, volume, borrow = raw["interest"], raw["volume"], raw["borrow"]
    out = {"state": raw["state"], "as_of": raw.get("as_of"),
           "interest": {"state": interest.get("state"), "source": interest.get("source"), "message": interest.get("message"),
                        "settlement_date": interest.get("settlement_date"), "short_interest": interest.get("short_interest"),
                        "days_to_cover": interest.get("days_to_cover"), "pct_of_shares_outstanding": interest.get("pct_of_shares_outstanding"),
                        "change_pct_from_previous": (interest.get("previous") or {}).get("change_pct"), "lag_note": interest.get("settlement_note")},
           "short_volume": {"state": volume.get("state"), "average_pct": volume.get("average_pct"), "note": volume.get("note")},
           "borrow": {"state": borrow.get("state"), "hard_to_borrow": borrow.get("hard_to_borrow"), "note": borrow.get("note") or borrow.get("message")}}
    return out


def _analysts(symbol: str) -> dict:
    from app.engine import symbol_info_analysts
    raw = symbol_info_analysts.symbol_analysts.view(symbol)
    blocks = raw["blocks"]

    def pick(name: str, shape: Callable[[dict | list], dict | list]) -> dict:
        b = blocks.get(name) or {}
        if b.get("state") != "ready":
            return {"state": b.get("state", "none"), "message": b.get("message")}
        return {"state": "ready", "source": b.get("source"), "fetched_at": _iso(b.get("fetched_at")), **({"note": b["note"]} if b.get("note") else {}),
                "value": shape(b["value"])}

    return {"state": raw["state"], "source_note": "unofficial, from Yahoo / Webull",
            "targets": pick("targets", lambda v: {k: v.get(k) for k in ("mean", "median", "high", "low")}),
            "ratings": pick("ratings", lambda v: dict(v)),
            "estimates": pick("estimates", lambda v: [{"period": e.get("period"), "eps": e.get("eps"), "revenue": e.get("revenue")} for e in v][:2]),
            "recent_actions": pick("actions", lambda v: [{k: a.get(k) for k in ("date", "firm", "action", "to_grade", "target")} for a in v[:MAX_ACTIONS]]),
            "last_reports": pick("history", lambda v: [{k: h.get(k) for k in ("quarter", "result", "surprise")} for h in v[:4]])}


def live_profile(symbol: str, now: datetime) -> dict:
    from app.engine.chart_math import ET
    today = now.astimezone(ET).date()
    out = {"symbol": symbol, "as_of": _iso(now.timestamp()), "note": PROFILE_NOTE}
    overview = _block("overview", lambda: _overview(symbol))
    out.update({k: overview.get(k, {"state": "unavailable", "reason": overview.get("reason")}) for k in ("company", "valuation", "ownership")})
    out["events"] = _block("events", lambda: _events(symbol, today))
    out["short"] = _block("short interest", lambda: _short(symbol))
    out["analysts"] = _block("analysts", lambda: _analysts(symbol))
    states = [out[k].get("state") for k in ("company", "valuation", "events", "short", "analysts")]
    out["state"] = "ok" if any(s in ("ready", "ok") for s in states) else "unavailable"
    if out["state"] == "unavailable":
        out["reason"] = f"No part of {symbol}'s profile could be read right now."
    return out


# --------------------------------------------------------------------------- the proof read-out

def _habits_card(db) -> dict:
    from app.engine import exit_habits
    card = exit_habits.build(db)
    v = card.get("verdict") or {}
    return {"state": "ok", "since": card.get("go_live"), "recent_trades": card.get("recent_trades"), "baseline_trades": card.get("baseline_trades"),
            "window": card.get("window"), "verdict": v.get("verdict"), "reason": v.get("reason"), "changes": v.get("changes") or {},
            "habits": [{"habit": h["label"], "recent": f"{h['recent']['n']} of {h['recent']['trades']}",
                        "recent_pct": None if h["recent"].get("pct") is None else round(100 * h["recent"]["pct"], 1),
                        "baseline_pct": None if h["baseline"].get("pct") is None else round(100 * h["baseline"]["pct"], 1)}
                       for h in card.get("habits") or []],
            "alerts": {"sent": card.get("alerts_total"), "responses": card.get("responses"),
                       "feedback": {k: (card.get("feedback") or {}).get(k) for k in ("total", "responded", "unanswered", "counts")}}}


def _plans_card(db) -> dict:
    from app.engine import plan_proof
    card = plan_proof.build(db)
    v = card.get("verdict") or {}
    return {"state": "ok", "since": card.get("go_live"), "trades": card.get("trades"), "caveat": card.get("caveat"),
            "verdict": v.get("verdict"), "reason": v.get("reason"), "difference_pct": v.get("difference_pct"), "days": v.get("days"),
            "groups": [{"group": g["key"], "trades": g["trades"], "pnl": g["pnl"], "mean_return_pct": g["mean_return_pct"],
                        "win_rate": g["win_rate"], "counted_in_verdict": g["in_verdict"]} for g in card.get("groups") or []]}


def _outcomes_card(db, scope: str, symbol: str | None, now: datetime) -> dict:
    from app.engine import outcomes
    if scope == "week":
        from app.engine import capture_links
        from app.engine.chart_math import ET
        today = now.astimezone(ET).date()
        monday = datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time())  # New York wall clock, as the journal keeps it
        rows = outcomes.week(db, capture_links.entry_utc(monday), capture_links.entry_utc(monday + timedelta(days=7)))
        start = monday.date()
        return {"scope": f"week of {start.isoformat()}", **rows}
    full = outcomes.build(db, symbol=symbol)
    return {"scope": f"{symbol} since {full.get('since')}", "state": "ok" if full.get("summary") else "not_applicable",
            "by_kind": full.get("summary") or {}, "note": full.get("note")}


def _scorecard_card(db, now: datetime) -> dict:
    from app.engine import alert_scorecard
    card = alert_scorecard.scorecard(db, now.timestamp(), SCORECARD_DAYS)
    return {"state": "ok", "window_days": card["window_days"], "alerts": card["alerts"],
            "by_decision": {k: {f: v[f] for f in ("alerts", "closed", "better", "worse", "even", "open", "vs_alert_usd")}
                            for k, v in (card.get("summary") or {}).items()}}


def live_proof(scope: str, symbol: str | None, now: datetime) -> dict:
    from sqlmodel import Session
    from app.database import engine
    out = {"scope": scope, "symbol": symbol, "as_of": _iso(now.timestamp()), "note": PROOF_NOTE}
    with Session(engine) as db:
        def guarded(name: str, build: Callable[[], dict]) -> dict:
            try:
                return build()
            except Exception as exc:  # noqa: BLE001 - one failing proof must not take the read-out down
                db.rollback()
                log.warning("copilot proof %s unavailable: %s", name, type(exc).__name__)
                return {"state": "unavailable", "reason": f"{name} could not be read right now."}

        out["alerts"] = guarded("exit habits", lambda: _habits_card(db))
        out["plans"] = guarded("plan proof", lambda: _plans_card(db))
        out["outcomes"] = guarded("outcomes", lambda: _outcomes_card(db, scope, symbol, now))
        out["scorecard"] = guarded("alert scorecard", lambda: _scorecard_card(db, now))
    out["state"] = "ok" if any(out[k].get("state") == "ok" for k in ("alerts", "plans", "outcomes", "scorecard")) else "unavailable"
    return out


# --------------------------------------------------------------------------- the fixture's NBIS scenario

FIXTURE_AT = "2026-10-23T15:12:00Z"


def fixture_profile(symbol: str, next_earnings: dict | None) -> dict:
    known = symbol in ("NBIS", "CRWV", "APLD")
    gone = {"state": "none", "message": f"Nothing simulated for {symbol}."}
    if not known:
        return {"symbol": symbol, "as_of": FIXTURE_AT, "state": "unavailable", "note": PROFILE_NOTE,
                **{k: dict(gone) for k in ("company", "valuation", "ownership", "events", "short", "analysts")}}
    return {
        "symbol": symbol, "as_of": FIXTURE_AT, "state": "ok", "note": PROFILE_NOTE,
        "company": {"state": "ready", "fetched_at": "2026-10-23T06:00:00Z", "message": None, "name": f"{symbol} (simulated)", "sector": "Technology",
                    "employees": 1200, "ipo_date": "2025-10-21",
                    "description": "Simulated: an AI infrastructure company renting GPU capacity to model builders and enterprises."},
        "valuation": {"state": "ready", "fetched_at": "2026-10-23T06:00:00Z", "message": None, "market_cap": 22_400_000_000, "enterprise_value": 21_100_000_000,
                      "shares_outstanding": 237_000_000, "pe": None, "price_to_sales": 38.2, "price_to_book": 6.1, "ev_to_ebitda": None,
                      "beta_60_month": 2.4, "average_volume_30_day": 18_500_000},
        "ownership": {"state": "ready", "institutional_pct": 41.3, "holders_13f": 412, "as_of": "2026-06-30"},
        "events": {"state": "ready", "fetched_at": FIXTURE_AT, "message": None, "next_earnings": next_earnings,
                   "last_report": {"date": "2026-08-07", "label": "Q2 2026"}, "dividends": {"state": "none", "next": None, "last": None}, "splits": []},
        "short": {"state": "ready", "as_of": FIXTURE_AT,
                  "interest": {"state": "ready", "source": "FINRA short interest (simulated)", "message": None, "settlement_date": "2026-10-15",
                               "short_interest": 31_200_000, "days_to_cover": 1.7, "pct_of_shares_outstanding": 13.2, "change_pct_from_previous": 8.4,
                               "lag_note": "Settlement dates are twice a month and published about two weeks later."},
                  "short_volume": {"state": "ready", "average_pct": 44.1, "note": "Share of daily volume FINRA marked short; not a position."},
                  "borrow": {"state": "ready", "hard_to_borrow": False, "note": "On Tradier's easy-to-borrow list."}},
        "analysts": {"state": "ready", "source_note": "unofficial, from Yahoo / Webull (simulated)",
                     "targets": {"state": "ready", "source": "Yahoo (simulated)", "fetched_at": "2026-10-23T06:00:00Z",
                                 "value": {"mean": 118.0, "median": 120.0, "high": 150.0, "low": 85.0}},
                     "ratings": {"state": "ready", "source": "Webull (simulated)", "fetched_at": "2026-10-23T06:00:00Z",
                                 "value": {"strong_buy": 6, "buy": 9, "hold": 3, "sell": 0, "strong_sell": 0}},
                     "estimates": {"state": "ready", "source": "Yahoo (simulated)", "fetched_at": "2026-10-23T06:00:00Z",
                                   "value": [{"period": "current quarter", "eps": {"avg": -0.31, "low": -0.45, "high": -0.2, "analysts": 9, "growth": None},
                                              "revenue": {"avg": 185_000_000, "low": 170_000_000, "high": 205_000_000, "analysts": 9, "growth": 2.1}}]},
                     "recent_actions": {"state": "ready", "source": "Yahoo (simulated)", "fetched_at": "2026-10-23T06:00:00Z",
                                        "value": [{"date": "2026-10-20", "firm": "Simulated Securities", "action": "raise", "to_grade": "Buy", "target": 130.0}]},
                     "last_reports": {"state": "ready", "source": "Yahoo (simulated)", "fetched_at": "2026-10-23T06:00:00Z",
                                      "value": [{"quarter": "2026-06-30", "result": "beat", "surprise": 12.5}]}},
    }


def fixture_proof(scope: str, symbol: str | None) -> dict:
    return {
        "scope": scope, "symbol": symbol, "as_of": FIXTURE_AT, "state": "ok", "note": PROOF_NOTE,
        "alerts": {"state": "ok", "since": "2026-10-21", "recent_trades": 9, "baseline_trades": 1528, "window": 30, "verdict": "not_enough_data",
                   "reason": "9 of 30 trades closed since the alerts went live.", "changes": {},
                   "habits": [{"habit": "Was up 10% and $50, then closed red", "recent": "1 of 9", "recent_pct": 11.1, "baseline_pct": 14.9},
                              {"habit": "Held an hour or more, closed red the same day", "recent": "2 of 9", "recent_pct": 22.2, "baseline_pct": 31.4},
                              {"habit": "Expired worthless", "recent": "0 of 9", "recent_pct": 0.0, "baseline_pct": 6.2},
                              {"habit": "Opened while the day was already green", "recent": "4 of 9", "recent_pct": 44.4, "baseline_pct": 52.0}],
                   "alerts": {"sent": 7, "responses": {"held": 4, "exited_within_15m": 2, "unmatched": 1},
                              "feedback": {"total": 7, "responded": 3, "unanswered": 4, "counts": {"helped": 2, "didnt": 1}}}},
        "plans": {"state": "ok", "since": "2026-10-13", "trades": 14, "verdict": "not_enough_data",
                  "reason": "6 planned and 8 unplanned of 10 each needed.", "difference_pct": None, "days": None,
                  "caveat": "Selection-biased: you plan the trades you are more careful about, so this can show that planned trades do "
                            "better, not that planning causes it.",
                  "groups": [{"group": "planned", "trades": 6, "pnl": 412.0, "mean_return_pct": 9.8, "win_rate": 0.67, "counted_in_verdict": True},
                             {"group": "unplanned", "trades": 8, "pnl": -230.0, "mean_return_pct": -4.1, "win_rate": 0.38, "counted_in_verdict": True}]},
        "outcomes": {"scope": "week of 2026-10-19" if scope == "week" else f"{symbol} since 2026-10-13", "state": "ok",
                     "by_kind": {"position_alert": {"count": 5, "complete": 4, "held": 3, "median_d1_pct": -1.2, "actions": {"held": 3, "exited": 2},
                                                    "alt_usd_total": -84.0}},
                     "note": "Counts and price paths, not causation."},
        "scorecard": {"state": "ok", "window_days": 30, "alerts": 7,
                      "by_decision": {"holding": {"alerts": 4, "closed": 3, "better": 1, "worse": 2, "even": 0, "open": 1, "vs_alert_usd": -140.0},
                                      "exiting": {"alerts": 2, "closed": 2, "better": 2, "worse": 0, "even": 0, "open": 0, "vs_alert_usd": 0.0},
                                      "none": {"alerts": 1, "closed": 1, "better": 0, "worse": 1, "even": 0, "open": 0, "vs_alert_usd": -35.0}}},
    }
