"""Would Claude have said cut? A blinded replay of the owner's leak moments through the Message Batches API.

The November 24, 2026 edge audit found the money leaking where a short-dated long option sat deep red past the hour and
was held anyway. ``leak_bill.bill_trade`` already finds that minute for every long option trade (entries all
``buy_to_open``, Webull left out): the first regular-session minute at least ``HOLD_MINUTES`` after the first entry,
with at most ``SHORT_DATED_DAYS`` calendar days to expiry, where the open contracts are worth ``DEEP_RED_PCT`` or less
against their cost. Its ``saved["deep_red"]`` is what selling there would have kept against what those contracts later
fetched (negative when holding paid). Each such minute is a moment.

Each moment becomes one blinded question for Claude: no ticker, no date, nothing after that minute. It gets the option
side, days to expiry, minutes held, the position's cost, mark and drawdown, its best and worst point so far, how many
buys built it, the underlying's move since the first buy (Alpaca minute bars, when the cache or feed has them), the time
of day, and his own record before that minute: his closed short-dated long option trades and how his earlier moments
like this one ended. The trade's own model tag is not used, because it was written after the close. Claude answers
``cut``, ``hold`` or ``add`` with a confidence and one reason.

Scoring compares each call with what happened: a ``cut`` is worth that moment's ``saved``; ``hold`` and ``add`` are worth
nothing (``add`` is counted apart, since an add cannot be priced). A call is a hit when it is ``cut`` and cutting saved
money, or not ``cut`` and holding paid. The model is measured against the two plain rules: always cut (the leak rule
itself) and never cut. Moments on or after ``HOLDOUT`` (after the model's training data ends) are reported apart as the
honest set. Aggregates only: no ticker, trade or fill is printed.

Spending: ``--dry-run`` (the default) builds every prompt and prints the count, an estimate and two samples, with no
API call. ``--submit`` creates one batch (50% off; ``copilot.cost_usd`` halved) and refuses when the estimate is over
``--max-usd`` or over what is left of ``AI_MONTHLY_BUDGET_USD``. ``--collect BATCH_ID`` reads the results, records the
batch's cost as one ``copilot_turn`` row so the monthly cap counts it, and prints the score. The key is
``ANTHROPIC_API_KEY`` only. ``--retry BATCH_ID`` submits only the moments that collected batch left unanswered (an
answer cut off or errored); collecting the retry scores them together with the earlier batch's answers. The submit
manifest and the results are written under ``--out-dir`` (``backend/reports/leak_replay/`` by default, ignored by git;
it maps answers back to trades; on the server, a folder outside the release, which each deploy replaces). Read-only
against the journal.

    cd backend && python -m scripts.leak_replay                    # dry run
    cd backend && python -m scripts.leak_replay --submit --max-usd 20
    cd backend && python -m scripts.leak_replay --collect msgbatch_...
    cd backend && python -m scripts.leak_replay --retry msgbatch_... --max-usd 1
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from sqlalchemy import or_
from sqlmodel import Session, select

from app.ai import copilot
from app.engine import leak_bill
from app.engine.analytics import wall_time
from app.engine.chart_journal import OPEN_SIDES
from app.engine.position_alerts import DEEP_RED_PCT, HOLD_MINUTES, SHORT_DATED_DAYS

MODEL = "claude-sonnet-5-5"
HOLDOUT = date(2026, 6, 1)  # moments on or after this are past the model's training data
MAX_TOKENS = 1500  # 400 cut off 12 of 118 answers mid-JSON in the first run (Nov 27); the answer itself is ~100
OUTPUT_ESTIMATE = 150  # tokens per answer, for the estimate
CHARS_PER_TOKEN = 3.5
DEFAULT_MAX_USD = 20.0
OUT_DIR = Path(__file__).resolve().parents[1] / "reports" / "leak_replay"
EPS = 1e-9

SYSTEM = """You advise one retail options trader at a single moment inside a trade. You see only what was known at \
that minute: the ticker and date are hidden, and nothing after that minute is given. Decide what he should do with the \
whole position right now: "cut" (sell it all now), "hold" (keep it, no new buys) or "add" (buy more). Judge from the \
numbers, his own record and the time left to expiry. Give a confidence from 0 to 1 that your call beats the \
alternatives, and one short reason."""

SCHEMA = {"type": "object", "required": ["call", "confidence", "reason"],
          "properties": {"call": {"type": "string", "enum": ["cut", "hold", "add"]},
                         "confidence": {"type": "number"}, "reason": {"type": "string"}}}


# --------------------------------------------------------------------------- moments

def _position_at(fills: list[dict], at: datetime) -> tuple[float, float, int]:
    """Contracts open, their cost (first in, first out) and the number of buys, over the fills up to ``at``."""
    ordered = sorted(fills, key=lambda f: (f["executed_at"], 0 if f["side"] in OPEN_SIDES else 1, str(f["id"])))
    lots: list[list[float]] = []
    buys = 0
    for fill in ordered:
        if fill["executed_at"].replace(second=0, microsecond=0) > at:
            break
        qty, price = float(fill["contracts"]), float(fill["price"])
        if fill["role"] == "entry":
            lots.append([qty, price])
            buys += 1
            continue
        while qty > EPS and lots:
            used = min(qty, lots[0][0])
            lots[0][0] -= used
            qty -= used
            if lots[0][0] <= EPS:
                lots.pop(0)
    return sum(q for q, _ in lots), sum(q * p for q, p in lots), buys


def _underlying_move(ticker: str, option_type: str, first: datetime, at: datetime, stock_bars: Callable | None) -> float | None:
    """The stock's percent move from the first buy's minute to ``at``, signed toward the trade (calls up, puts down)."""
    if stock_bars is None:
        return None

    def close_at(moment: datetime) -> float | None:
        best = None
        for at_bar, price in _stock_marks(stock_bars(ticker, moment.date())):
            if at_bar > moment:
                break
            best = price
        return best

    try:
        start, now = close_at(first), close_at(at)
    except Exception:  # noqa: BLE001 - no stock bars: the fact is left out
        return None
    if not start or now is None:
        return None
    move = (now / start - 1) * 100
    return round(move if option_type == "call" else -move, 2)


def _stock_marks(bars: list[dict] | None) -> list[tuple[datetime, float]]:
    return [(at, price / 100) for at, price in leak_bill.marks(bars)]  # marks() scales by 100 for contracts


def _alpaca_stock_bars(ticker: str, day: date) -> list[dict] | None:
    from app.engine.alpaca import fetch_minute_bars_for_date
    return fetch_minute_bars_for_date([ticker], day).get(ticker)


def find_moments(db: Session, bars_for: Callable = leak_bill._bars, stock_bars: Callable | None = _alpaca_stock_bars) -> list[dict]:
    """Every long option trade's deep-red cut minute, oldest first, with the facts known then and what happened."""
    from app.models import Account, Fill, Trade, TradeFill
    trades = db.exec(select(Trade).join(Account, Account.id == Trade.account_id).where(
        Trade.instrument_type == "option", Trade.status.in_(("closed", "expired")), Trade.closed_at.is_not(None),
        Trade.expiration.is_not(None), or_(Account.broker.is_(None), Account.broker != "webull"))).all()
    fills_of: dict = defaultdict(list)
    if trades:
        for f in db.exec(select(TradeFill.trade_id, TradeFill.role, Fill.id, Fill.side, Fill.contracts, Fill.price,
                                Fill.executed_at).join(Fill, Fill.id == TradeFill.fill_id)
                         .where(TradeFill.trade_id.in_([t.id for t in trades]))).all():
            fills_of[f.trade_id].append({"id": f.id, "role": f.role, "side": f.side, "contracts": float(f.contracts),
                                         "price": float(f.price), "executed_at": wall_time(f.executed_at)})
    found, history = [], []
    for trade in trades:
        fills = fills_of[trade.id]
        entries = [f for f in fills if f["role"] == "entry"]
        if not entries or any(f["side"] != "buy_to_open" for f in entries) or trade.option_type not in ("call", "put"):
            continue
        first, closed = min(f["executed_at"] for f in entries), wall_time(trade.closed_at)
        short = 0 <= (trade.expiration - first.date()).days <= SHORT_DATED_DAYS
        history.append({"closed": closed, "pnl": float(trade.realized_pnl or 0), "short": short})
        if not (short and closed >= first + timedelta(minutes=HOLD_MINUTES)):
            continue
        bars = bars_for(trade)
        cut = leak_bill.bill_trade(trade.expiration, trade.status == "expired", fills, bars)
        if not cut["cut"] or cut["cut"]["rule"] != "deep_red":
            continue
        at, mark = cut["cut"]["at"], cut["cut"]["price"]
        held, cost, buys = _position_at(fills, at)
        if held <= EPS or cost <= EPS:
            continue
        path = [price for moment, price in leak_bill.marks(bars) if first <= moment <= at]
        avg = cost / held
        found.append({
            "trade_id": str(trade.id), "at": at, "closed": closed, "ticker": trade.ticker,
            "facts": {"side": trade.option_type, "days_to_expiry": (trade.expiration - at.date()).days,
                      "minutes_held": int((at - first).total_seconds() // 60), "contracts": held,
                      "avg_cost_per_contract": round(avg, 2), "mark_per_contract": round(mark, 2),
                      "position_pct": round((mark * held / cost - 1) * 100, 1),
                      "best_pct_so_far": round((max(path) / avg - 1) * 100, 1) if path else None,
                      "worst_pct_so_far": round((min(path) / avg - 1) * 100, 1) if path else None,
                      "buys_so_far": buys, "time_et": at.strftime("%H:%M"),
                      "underlying_move_pct": _underlying_move(trade.ticker, trade.option_type, first, at, stock_bars)},
            "saved": round(float(cut["saved"].get("deep_red", 0.0)), 2),
            "realized_pnl": float(trade.realized_pnl or 0),
        })
    found.sort(key=lambda m: m["at"])
    for m in found:  # his record as it stood at that minute, never anything that closed later
        prior = [h for h in history if h["short"] and h["closed"] < m["at"]]
        earlier = [e for e in found if e["closed"] < m["at"]]
        m["facts"]["record"] = {
            "short_dated_trades": len(prior), "short_dated_win_rate": round(sum(h["pnl"] > 0 for h in prior) / len(prior), 3) if prior else None,
            "short_dated_total_pnl": round(sum(h["pnl"] for h in prior)) if prior else 0,
            "earlier_moments_like_this": len(earlier),
            "earlier_moments_where_cutting_saved_money": sum(e["saved"] > 0 for e in earlier),
            "earlier_moments_net_dollars_cutting_would_have_kept": round(sum(e["saved"] for e in earlier)),
        }
    return found


# --------------------------------------------------------------------------- prompts and the batch

def prompt(m: dict) -> str:
    f, r = m["facts"], m["facts"]["record"]
    move = "unknown" if f["underlying_move_pct"] is None else f"{f['underlying_move_pct']:+.2f}% (toward the trade is positive)"
    best = "unknown" if f["best_pct_so_far"] is None else f"{f['best_pct_so_far']:+.1f}%"
    worst = "unknown" if f["worst_pct_so_far"] is None else f"{f['worst_pct_so_far']:+.1f}%"
    win = "none yet" if r["short_dated_win_rate"] is None else f"{r['short_dated_win_rate']:.0%} won, net ${r['short_dated_total_pnl']:+,}"
    return "\n".join([
        f"Position: long {f['contracts']:g} {f['side']} contract(s), {f['days_to_expiry']} calendar day(s) to expiry.",
        f"Bought in {f['buys_so_far']} buy(s); average cost ${f['avg_cost_per_contract']:,.2f} per contract.",
        f"Now {f['time_et']} New York, {f['minutes_held']} minutes after the first buy.",
        f"Mark ${f['mark_per_contract']:,.2f} per contract: the position is {f['position_pct']:+.1f}%.",
        f"Best point so far {best}, worst {worst}. Underlying since the first buy: {move}.",
        f"His record before now: {r['short_dated_trades']} closed short-dated long option trades ({win}).",
        f"Earlier moments like this one (short-dated, down {-DEEP_RED_PCT:.0%}+ past an hour): {r['earlier_moments_like_this']}; "
        f"cutting there would have saved money in {r['earlier_moments_where_cutting_saved_money']}, "
        f"net ${r['earlier_moments_net_dollars_cutting_would_have_kept']:+,} kept by cutting.",
        "What should he do now?",
    ])


def requests(found: list[dict], model: str = MODEL) -> list[dict]:
    from app.ai.api_runner import api_schema
    return [{"custom_id": f"m{i}", "params": {
        "model": model, "max_tokens": MAX_TOKENS, "system": SYSTEM,
        "messages": [{"role": "user", "content": prompt(m)}],
        "output_config": {"format": {"type": "json_schema", "schema": api_schema(SCHEMA)}}}}
        for i, m in enumerate(found)]


def estimate_usd(reqs: list[dict], model: str = MODEL) -> float:
    """Batch price (half of ``copilot.cost_usd``) from a characters-per-token guess plus a fixed answer length."""
    chars = sum(len(r["params"]["system"]) + len(r["params"]["messages"][0]["content"]) for r in reqs)
    usage = {"input_tokens": int(chars / CHARS_PER_TOKEN) + 400 * len(reqs),  # schema and framing overhead
             "output_tokens": OUTPUT_ESTIMATE * len(reqs), "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    return round(copilot.cost_usd(model, usage) / 2, 4)


class Refused(Exception):
    pass


def submit(client, found: list[dict], max_usd: float, *, budget_left: float | None = None, out_dir: Path = OUT_DIR,
           retry_of: str | None = None) -> dict:
    """Create the batch, or refuse (``Refused``) when the estimate is over ``max_usd`` or the month's remaining budget.
    ``retry_of``: an earlier batch whose unanswered moments these are; collecting this one scores them together."""
    reqs = requests(found)
    usd = estimate_usd(reqs)
    if not reqs:
        raise Refused("No leak moments found; nothing to submit.")
    if usd > max_usd:
        raise Refused(f"Estimated ${usd:.2f} is over --max-usd ${max_usd:.2f}.")
    if budget_left is not None and usd > budget_left:
        raise Refused(f"Estimated ${usd:.2f} is over what is left of this month's AI budget (${budget_left:.2f}).")
    batch = client.messages.batches.create(requests=reqs)
    manifest = {"batch_id": batch.id, "model": MODEL, "estimate_usd": usd, "submitted_at": datetime.now().isoformat(),
                "retry_of": retry_of,
                "moments": {f"m{i}": {k: m[k] for k in ("trade_id", "saved", "realized_pnl")}
                            | {"at": m["at"].isoformat(), "days_to_expiry": m["facts"]["days_to_expiry"]}
                            for i, m in enumerate(found)}}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{batch.id}.manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def _key(moment: dict) -> tuple[str, str]:
    at = moment["at"]
    return str(moment["trade_id"]), at if isinstance(at, str) else at.isoformat()


def unanswered(found: list[dict], batch_id: str, out_dir: Path = OUT_DIR) -> list[dict]:
    """The moments a collected batch (and the batches it retried) left without an answer, from ``found``."""
    rows = json.loads((out_dir / f"{batch_id}.results.json").read_text())["rows"]
    missing = {_key(r) for r in rows if r["call"] is None}
    return [m for m in found if _key(m) in missing]


# --------------------------------------------------------------------------- collect and score

def _answer(result) -> tuple[dict | None, dict]:
    usage = {k: 0 for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
    if getattr(result.result, "type", None) != "succeeded":
        return None, usage
    message = result.result.message
    usage.update({k: int(getattr(message.usage, k, 0) or 0) for k in usage})
    text = next((b.text for b in message.content if getattr(b, "type", None) == "text"), "")
    try:
        data = json.loads(text)
    except ValueError:
        return None, usage
    return (data if isinstance(data, dict) and data.get("call") in ("cut", "hold", "add") else None), usage


def _group(rows: list[dict]) -> dict:
    answered = [r for r in rows if r["call"] is not None]
    cuts = [r for r in answered if r["call"] == "cut"]
    hits = sum((r["call"] == "cut") == (r["saved"] > 0) for r in answered)
    return {"moments": len(rows), "answered": len(answered), "cut": len(cuts),
            "hold": sum(r["call"] == "hold" for r in answered), "add": sum(r["call"] == "add" for r in answered),
            "hit_rate": round(hits / len(answered), 3) if answered else None,
            "model_dollars_kept": round(sum(r["saved"] for r in cuts), 2),
            "always_cut_dollars_kept": round(sum(r["saved"] for r in answered), 2),
            "never_cut_dollars_kept": 0.0,
            "cutting_saved_money_in": sum(r["saved"] > 0 for r in answered)}


def score(rows: list[dict]) -> dict:
    """Rows carry ``call`` (or None), ``saved``, ``at`` (ISO) and ``days_to_expiry``."""
    def bucket(days: int) -> str:
        return "0dte" if days <= 0 else "1-3dte"

    out = {"all": _group(rows),
           "before_holdout": _group([r for r in rows if r["at"][:10] < HOLDOUT.isoformat()]),
           "holdout": _group([r for r in rows if r["at"][:10] >= HOLDOUT.isoformat()]),
           "by_dte": {}}
    for name in ("0dte", "1-3dte"):
        out["by_dte"][name] = _group([r for r in rows if bucket(r["days_to_expiry"]) == name])
    return out


def collect(client, batch_id: str, *, out_dir: Path = OUT_DIR, record: Callable | None = None) -> dict:
    batch = client.messages.batches.retrieve(batch_id)
    if batch.processing_status != "ended":
        return {"batch_id": batch_id, "status": batch.processing_status}
    manifest = json.loads((out_dir / f"{batch_id}.manifest.json").read_text())
    total = {k: 0 for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
    rows = []
    seen = set()
    for result in client.messages.batches.results(batch_id):
        moment = manifest["moments"].get(result.custom_id)
        if moment is None:
            continue
        seen.add(result.custom_id)
        data, usage = _answer(result)
        for k in total:
            total[k] += usage[k]
        rows.append({**moment, "call": data["call"] if data else None,
                     "confidence": data.get("confidence") if data else None, "reason": data.get("reason") if data else None})
    rows += [{**m, "call": None} for key, m in manifest["moments"].items() if key not in seen]
    if manifest.get("retry_of"):  # the earlier batch's rows, with this batch's answers in place of its gaps
        earlier = json.loads((out_dir / f"{manifest['retry_of']}.results.json").read_text())["rows"]
        mine = {_key(r): r for r in rows}
        rows = [mine.pop(_key(r), r) if r["call"] is None else r for r in earlier] + list(mine.values())
    usd = round(copilot.cost_usd(manifest["model"], total) / 2, 6)
    if record is not None:
        record({"backend": "api_background", "model": manifest["model"], "rounds": len(rows), "usage": total,
                "cost_usd": usd}, kind="research", source="api_runner")
    report = {"batch_id": batch_id, "retry_of": manifest.get("retry_of"), "cost_usd": usd,
              "unanswered": sum(r["call"] is None for r in rows), "score": score(rows)}
    (out_dir / f"{batch_id}.results.json").write_text(json.dumps({**report, "rows": rows}, indent=2, default=str))
    return report


# --------------------------------------------------------------------------- command line

def _client():
    import anthropic
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit("ANTHROPIC_API_KEY is not set.")
    return anthropic.Anthropic(api_key=key)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="the default: build prompts and estimate, no API call")
    mode.add_argument("--submit", action="store_true", help="create the batch")
    mode.add_argument("--collect", metavar="BATCH_ID", help="fetch a finished batch and score it")
    mode.add_argument("--retry", metavar="BATCH_ID", help="submit only the moments a collected batch left unanswered")
    parser.add_argument("--max-usd", type=float, default=DEFAULT_MAX_USD)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR, help="where manifests and results are kept")
    args = parser.parse_args(argv)
    from app.ai import copilot_spend
    if args.collect:
        print(json.dumps(collect(_client(), args.collect, out_dir=args.out_dir, record=copilot_spend.record), indent=2))
        return 0
    from app.database import engine
    with Session(engine) as db:
        found = find_moments(db)
    if args.retry:
        found = unanswered(found, args.retry, args.out_dir)
    if args.submit or args.retry:
        exceeded, spent, cap = copilot_spend.monthly_status()
        try:
            manifest = submit(_client(), found, args.max_usd, budget_left=0.0 if exceeded else cap - spent,
                              out_dir=args.out_dir, retry_of=args.retry)
        except Refused as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps({k: manifest[k] for k in ("batch_id", "estimate_usd")} | {"moments": len(found)}, indent=2))
        return 0
    reqs = requests(found)
    print(json.dumps({"moments": len(found), "holdout_moments": sum(m["at"].date() >= HOLDOUT for m in found),
                      "estimate_usd": estimate_usd(reqs), "always_cut_dollars_kept": round(sum(m["saved"] for m in found), 2),
                      "samples": [r["params"]["messages"][0]["content"] for r in reqs[:2]]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
