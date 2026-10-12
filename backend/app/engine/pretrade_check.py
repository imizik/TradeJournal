"""Deterministic pre-trade check: rules verdict + own similar-trades card.

Pure functions over a scalp analysis (``scalper.build_scalp_analysis``) and
per-trade feature rows. No network, no database writes, no model call, never
places or sizes orders. See docs/agent/advisor-pretrade-check-contract.md.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from statistics import median
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app.models import Account, Fill, FillMarketContext, Trade, TradeFill, TradePathMetrics

RULES_VERSION = "pretrade-rules-v1"
NY = ZoneInfo("America/New_York")
# Display policy, not proof: below these the card says "not enough history".
MIN_TRADES = 8
MIN_DAYS = 3
# History downgrade (v1): a sufficient matching cohort that mostly loses.
WEAK_WIN_RATE = 0.40
WAIT_EXPIRY_MINUTES = 30
SESSION_CLOSE = (16, 0)
EXCLUDED_BROKERS = {"webull"}  # Dormant by owner choice; never in the card.
SIDES = {"call": "long", "put": "short"}


def _ny_wall(moment_utc: datetime) -> datetime:
    """UTC receipt time -> naive New York wall time, the journal's convention."""
    if moment_utc.tzinfo is None:
        raise ValueError("Check receipt time must be timezone-aware UTC")
    return moment_utc.astimezone(NY).replace(tzinfo=None)


def _vwap_bucket(pct: Optional[float]) -> Optional[str]:
    if pct is None:
        return None
    if pct < -0.5:
        return "below"
    if pct > 0.5:
        return "above"
    return "at"


def _rvol_bucket(rvol: Optional[float]) -> Optional[str]:
    if rvol is None:
        return None
    return "low" if rvol < 1.0 else "normal" if rvol < 2.0 else "high"


def _flag(value) -> Optional[bool]:
    return None if value is None else bool(value)


def _side(instrument: str, option_type: Optional[str]) -> Optional[str]:
    if instrument == "option":
        return option_type if option_type in SIDES else None
    return "stock" if instrument == "stock" else None


def feature_row(trade: Trade, entry_fill: Fill, context: Optional[FillMarketContext],
                path: Optional[TradePathMetrics]) -> dict:
    """One closed trade's cohort dimensions and outcome measures.

    Stores source fill keys, never bare trade IDs: FIFO rebuilds recreate trades.
    """
    return {
        "closed_at": trade.closed_at.isoformat(),  # naive New York wall time
        "opened_at": trade.opened_at.isoformat(),
        "underlying": trade.ticker.upper(),
        "side": _side(trade.instrument_type, trade.option_type),
        "time_bucket": (context.entry_time_bucket if context else None) or trade.entry_time_bucket,
        "vwap_bucket": _vwap_bucket(context.entry_vs_vwap_pct) if context else None,
        "trend_aligned": _flag(context.is_trend_aligned) if context else None,
        "chase": _flag(context.is_chase_entry) if context else None,
        "late_move": _flag(context.is_late_move) if context else None,
        "rvol_bucket": _rvol_bucket(context.rvol_time_adjusted) if context else None,
        "dte_bucket": context.dte_bucket if context else None,
        "realized_pnl": float(trade.realized_pnl) if trade.realized_pnl is not None else None,
        "pnl_pct": float(trade.pnl_pct) if trade.pnl_pct is not None else None,
        "mfe_pct": path.underlying_mfe_pct if path else None,
        "mae_pct": path.underlying_mae_pct if path else None,
        "giveback_pct": path.underlying_giveback_pct if path else None,
        "source_fill_key": entry_fill.raw_email_id,
    }


def build_feature_rows(session: Session) -> list[dict]:
    """Read-only: one row per closed/expired trade outside excluded brokers."""
    trades = session.exec(
        select(Trade, Account).join(Account, Trade.account_id == Account.id)
        .where(Trade.status.in_(("closed", "expired")), Trade.closed_at.is_not(None))
    ).all()
    rows = []
    for trade, account in trades:
        if (account.broker or "").lower() in EXCLUDED_BROKERS:
            continue
        entries = session.exec(
            select(Fill).join(TradeFill, TradeFill.fill_id == Fill.id)
            .where(TradeFill.trade_id == trade.id, TradeFill.role == "entry")
            .order_by(Fill.executed_at, Fill.raw_email_id)
        ).all()
        if not entries:
            continue
        first = entries[0]
        rows.append(feature_row(trade, first, session.get(FillMarketContext, first.id),
            session.get(TradePathMetrics, trade.id)))
    return rows


def idea_features(idea: dict, analysis: dict) -> dict:
    """The same cohort dimensions for the idea being checked, from live data."""
    request = analysis.get("request") or {}
    intraday = (analysis.get("data") or {}).get("intraday") or {}
    minutes = intraday.get("minutes_since_open")
    bucket = None
    if minutes is not None and 0 <= minutes < 390:
        # Same boundaries as fill contexts: open 9:30-10:00, mid to 15:00, close to 16:00.
        bucket = "open" if minutes < 30 else "mid" if minutes < 330 else "close"
    return {
        "underlying": idea["ticker"].upper(),
        "side": _side(request.get("instrument") or idea["instrument"], request.get("option_type") or idea.get("option_type")),
        "time_bucket": bucket,
        "vwap_bucket": _vwap_bucket(intraday.get("price_vs_vwap_pct")),
        "rvol_bucket": _rvol_bucket(intraday.get("rvol")),
    }


def _summary(rows: list[dict]) -> dict:
    days = {row["closed_at"][:10] for row in rows}
    weeks = {datetime.fromisoformat(row["closed_at"]).isocalendar()[:2] for row in rows}
    pnl = [row["realized_pnl"] for row in rows if row["realized_pnl"] is not None]
    returns = [row["pnl_pct"] for row in rows if row["pnl_pct"] is not None]
    mfe = [row["mfe_pct"] for row in rows if row["mfe_pct"] is not None]
    mae = [row["mae_pct"] for row in rows if row["mae_pct"] is not None]
    enough = len(rows) >= MIN_TRADES and len(days) >= MIN_DAYS
    result = {"trades": len(rows), "distinct_days": len(days), "distinct_weeks": len(weeks), "enough": enough}
    if not enough:
        result["note"] = "not enough history"
        return result
    wins = sum(1 for value in pnl if value > 0)
    result.update({
        "win_rate": round(wins / len(pnl), 3) if pnl else None,
        "total_pnl": round(sum(pnl), 2) if pnl else None,
        "avg_pnl": round(sum(pnl) / len(pnl), 2) if pnl else None,
        "median_return_pct": round(median(returns), 2) if returns else None,
        "median_mfe_pct": round(median(mfe), 3) if mfe else None,
        "median_mae_pct": round(median(mae), 3) if mae else None,
        "coverage": {"pnl": len(pnl), "path": len(mfe)},
    })
    losers = [row for row in rows if (row["realized_pnl"] or 0) < 0]
    if len(losers) >= 3:
        bucket, count = Counter(row["time_bucket"] for row in losers).most_common(1)[0]
        if bucket and count / len(losers) >= 0.6:
            result["loser_pattern"] = f"{count} of {len(losers)} losers entered in the {bucket} bucket"
    return result


def history_card(rows: Iterable[dict], features: dict, receipt_utc: datetime) -> dict:
    """Similar closed trades before the check's receipt, by two cohorts."""
    cutoff = _ny_wall(receipt_utc)
    prior = [row for row in rows if datetime.fromisoformat(row["closed_at"]) < cutoff]
    same_side = [row for row in prior if row["underlying"] == features["underlying"] and row["side"] == features["side"]]
    setup_keys = ("time_bucket", "vwap_bucket")
    setup = [row for row in same_side
             if all(features[key] is not None and row[key] == features[key] for key in setup_keys)]
    return {
        "as_of_ny": cutoff.isoformat(timespec="seconds"),
        "cohorts": [
            {"name": "same_setup", "definition": {key: features[key] for key in ("underlying", "side", *setup_keys)},
             **_summary(setup)},
            {"name": "same_ticker_side", "definition": {key: features[key] for key in ("underlying", "side")},
             **_summary(same_side)},
        ],
        "source_fill_keys": sorted(row["source_fill_key"] for row in setup),
    }


def _wait_expiry(receipt_utc: datetime) -> str:
    ny = receipt_utc.astimezone(NY)
    close = ny.replace(hour=SESSION_CLOSE[0], minute=SESSION_CLOSE[1], second=0, microsecond=0)
    return min(ny + timedelta(minutes=WAIT_EXPIRY_MINUTES), close).isoformat(timespec="minutes")


def _risk_check(idea: dict, assessment: dict, analysis: dict) -> tuple[dict, Optional[str]]:
    stop, entry = idea.get("stop"), idea.get("entry")
    intraday = (analysis.get("data") or {}).get("intraday") or {}
    price = entry if entry is not None else intraday.get("price")
    if stop is None:
        return {"stop": None, "note": "no stop given; none invented"}, None
    if price is None:
        return {"stop": stop, "note": "no live or entry price to measure the stop against"}, None
    long_side = (assessment.get("direction_evaluated") or "long") == "long"
    distance = (price - stop) if long_side else (stop - price)
    result = {"stop": stop, "reference_price": price,
              "distance_pct": round(distance / price * 100, 3), "scorer_invalidation": assessment.get("invalidation")}
    if distance <= 0:
        return result, "stop is on the wrong side of the price for this direction"
    return result, None


def rules_verdict(analysis: dict, history: dict, idea: dict, receipt_utc: datetime) -> dict:
    """Roadmap mapping (docs/advisor-roadmap.md#rules-verdict-mapping), versioned."""
    assessment = analysis.get("assessment") or {}
    data = analysis.get("data") or {}
    market_state = assessment.get("market_state") or data.get("market_state") or "closed"
    stale = bool((data.get("staleness") or {}).get("is_stale"))
    risk, risk_problem = _risk_check(idea, assessment, analysis)
    reasons, wait_for = [], None
    if idea.get("horizon") != "intraday":
        verdict = "insufficient_data"
        reasons.append({"source": "rules", "text": "only regular-session intraday ideas are scored"})
    elif market_state != "rth":
        verdict = "insufficient_data"
        reasons.append({"source": "live", "text": "outside the regular session — not a judgment on the idea"})
    elif stale or assessment.get("setup_score") is None:
        verdict = "insufficient_data"
        reasons.append({"source": "live", "text": "live data is stale or the setup could not be scored"})
    elif assessment.get("verdict") in ("long_scalp", "short_scalp"):
        verdict = "go"
        reasons.append({"source": "live", "text": f"setup {assessment.get('setup_score')}, "
                        f"liquidity {assessment.get('liquidity_score')}, risk {assessment.get('risk_score')}"})
    elif assessment.get("verdict") == "wait":
        verdict = "wait"
        wait_for = {"condition": assessment.get("trigger"), "expires_at": _wait_expiry(receipt_utc)}
        reasons.extend({"source": "live", "text": text} for text in (assessment.get("reasons_against") or [])[:1])
    else:
        verdict = "pass"
        reasons.extend({"source": "live", "text": text} for text in (assessment.get("reasons_against") or [])[:1])

    same_setup = history["cohorts"][0]
    if verdict == "go" and same_setup.get("enough") and (same_setup.get("win_rate") or 0) < WEAK_WIN_RATE \
            and (same_setup.get("avg_pnl") or 0) < 0:
        verdict = "wait"
        wait_for = {"condition": assessment.get("trigger"), "expires_at": _wait_expiry(receipt_utc)}
        reasons.append({"source": "history", "text": f"your {same_setup['trades']} similar trades won "
                        f"{same_setup['win_rate']:.0%} with average P&L {same_setup['avg_pnl']}"})
    if risk_problem and verdict in ("go", "wait"):
        verdict = "pass"
        wait_for = None
        reasons.append({"source": "risk", "text": risk_problem})
    return {"verdict": verdict, "wait_for": wait_for, "reasons": reasons[:3], "risk_check": risk}


def _caveats(analysis: dict, history: dict) -> list[str]:
    data = analysis.get("data") or {}
    assessment = analysis.get("assessment") or {}
    caveats = []
    if (data.get("staleness") or {}).get("is_stale"):
        caveats.append("live quotes/bars are stale")
    caveats.extend(f"missing: {item}" for item in (assessment.get("missing") or []))
    caveats.extend(note for note in (assessment.get("data_source_notes") or []) if "iex" in note.lower())
    if not history["cohorts"][0].get("enough"):
        caveats.append("similar-setup history is too thin to show rates")
    return caveats


def run_check(idea: dict, analysis: dict, rows: Iterable[dict], receipt_utc: datetime) -> dict:
    """The answer contract for one idea. Same inputs, same answer."""
    for key in ("ticker", "side", "instrument", "horizon"):
        if not idea.get(key):
            raise ValueError(f"{key} is required")
    if idea["side"] not in ("long", "short") or idea["instrument"] not in ("stock", "option") \
            or idea["horizon"] not in ("intraday", "swing"):
        raise ValueError("side long|short, instrument stock|option, horizon intraday|swing")
    rows = list(rows)
    history = history_card(rows, idea_features(idea, analysis), receipt_utc)
    rules = rules_verdict(analysis, history, idea, receipt_utc)
    assessment = analysis.get("assessment") or {}
    data = analysis.get("data") or {}
    intraday = data.get("intraday") or {}
    live = {"price": intraday.get("price"), "vwap": intraday.get("vwap"), "rvol": intraday.get("rvol"),
            "market_state": assessment.get("market_state"), "scalp_verdict": assessment.get("verdict"),
            "setup_score": assessment.get("setup_score"), "trigger": assessment.get("trigger"),
            "invalidation": assessment.get("invalidation"), "generated_at": assessment.get("generated_at"),
            "staleness": data.get("staleness")}
    would_change = assessment.get("trigger") if rules["verdict"] in ("wait", "pass") else assessment.get("invalidation")
    answer = {"rules_version": RULES_VERSION, "receipt_utc": receipt_utc.astimezone(timezone.utc).isoformat(),
              "idea": idea, **rules, "would_change": would_change, "history": history, "live": live,
              "caveats": _caveats(analysis, history)}
    answer["live_context_sha256"] = hashlib.sha256(
        json.dumps({"request": analysis.get("request"), "data": data}, sort_keys=True, default=str).encode()).hexdigest()
    return answer


LINK_VERSION = "pretrade-link-v1"


def check_window(answer: dict, receipt_utc: datetime) -> tuple[datetime, datetime]:
    """Fixed before the outcome is known: receipt to the wait expiry, else to that session's close (NY wall time)."""
    start = _ny_wall(receipt_utc)
    close = start.replace(hour=SESSION_CLOSE[0], minute=SESSION_CLOSE[1], second=0, microsecond=0)
    end = close
    if answer.get("verdict") == "wait" and answer.get("wait_for"):
        end = min(datetime.fromisoformat(answer["wait_for"]["expires_at"]).astimezone(NY).replace(tzinfo=None), close)
    return start, max(start, end)


def check_outcome(idea: dict, answer: dict, receipt_utc: datetime, rows: Optional[Iterable[dict]],
                  features_generated_at: Optional[datetime], now_utc: datetime) -> dict:
    """What happened after a check, from closed trades only (docs/advisor-roadmap.md#checks-and-captures).

    "traded" means a trade on the same underlying and side opened inside the window; it is not proof the
    check was followed. "no_closed_trade" never claims no position: an open one appears after it closes.
    """
    if idea.get("horizon") != "intraday":
        return {"state": "not_linked", "link_version": LINK_VERSION, "note": "swing checks are not linked yet"}
    start, end = check_window(answer, receipt_utc)
    window = {"from_ny": start.isoformat(timespec="minutes"), "to_ny": end.isoformat(timespec="minutes")}
    base = {"link_version": LINK_VERSION, "window": window}
    if _ny_wall(now_utc) < end:
        return {**base, "state": "pending", "note": "the check's window is still open"}
    if rows is None or features_generated_at is None or _ny_wall(features_generated_at) < end:
        return {**base, "state": "pending", "note": "trade history has not been refreshed since the window closed"}
    side = _side(idea["instrument"], idea.get("option_type"))
    trades = sorted((row for row in rows if row["underlying"] == idea["ticker"].upper() and row["side"] == side
                     and start <= datetime.fromisoformat(row["opened_at"]) <= end), key=lambda row: row["opened_at"])
    if not trades:
        return {**base, "state": "no_closed_trade",
                "note": "no closed trade on this ticker and side opened in the window; an open one would appear after it closes"}
    pnl = [row["realized_pnl"] for row in trades if row["realized_pnl"] is not None]
    # Aggregates only: the approved scope shares own-trade summaries, not individual trades.
    return {**base, "state": "traded", "trade_count": len(trades), "wins": sum(1 for value in pnl if value > 0),
        "total_pnl": round(sum(pnl), 2) if pnl else None, "first_opened_at": trades[0]["opened_at"],
        "note": "a trade on this ticker and side opened in the window; not proof the check was followed"}
