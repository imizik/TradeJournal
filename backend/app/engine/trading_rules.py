"""His own trading rules (docs/copilot-lab.md § My rules): written once, checked at each entry, scored by whether
following them paid.

- **The rules.** Up to ``MAX_RULES``, each in his own words. A rule may pick one automatic check from ``CHECKS`` (the
  only ones the app can verify honestly); a rule without one is a tick-box he answers at the entry. Each save is a new
  ``trading_rule_record`` row (``kind`` ``rules``); the newest is the list. A rule keeps its id across edits.
- **At an entry.** ``evaluate`` checks every rule against the order: an automatic check passes, fails (``broken``,
  with the reason), does not apply (``na``: a share trade has no expiry) or cannot be checked (``unknown``, with why;
  never a pass). A tick-box passes when he ticked it and is broken when he left it unticked; before he answers it is
  ``ask``. Breaking a rule never blocks an order.
- **Where answers are kept.** A paper entry keeps its checklist in its own paper event (``paper_book``: the open fill's
  ``rules``; a limit order keeps his answers and the rules as they stood, and is checked at its fill). A real order he
  copies from the Ticket keeps its checklist in a ``ticket`` record keyed to the saved plan; it is matched to a real
  trade only through that plan's own capture link (``copilot_plans``), else it stays unmatched and is counted as such.
- **Followed versus broken.** ``split`` groups closed trades: followed (every rule passed or did not apply), broken
  (any rule broken), unclear (none broken, but one could not be checked or was not answered). Trades entered before he
  had rules are left out and counted.

Reads the paper book, the journal's open trades and the desk's account line (``desk_account_value``) only; never a quote,
never Robinhood, never an order.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.engine.chart_math import ET
from app.models import TradingRuleRecord

MAX_RULES = 8
TEXT_CHARS = 140
_ID = re.compile(r"^r_[a-z0-9]{6,16}$")
_KEY = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_PLAN = re.compile(r"^[A-Za-z0-9:._-]{1,80}$")
EPS = 1e-9

# The automatic checks: (words with {n}, whether n is needed, smallest n, largest n, whole numbers only).
CHECKS: dict[str, dict] = {
    "max_size_pct": {"words": "Size at most {n}% of the account", "min": 0.1, "max": 100, "whole": False},
    "stop_set": {"words": "Stop set before entry"},
    "no_open_minutes": {"words": "No entry in the first {n} minutes after the open", "min": 1, "max": 390, "whole": True},
    "max_open": {"words": "At most {n} open positions", "min": 1, "max": 50, "whole": True},
    "min_dte": {"words": "Option at least {n} days to expiry", "min": 0, "max": 3650, "whole": True},
}
STATUSES = ("pass", "fail", "na", "unknown", "ask")


class RulesError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _usd(value: float) -> str:
    return f"${value:,.2f}"


def _pct(pct: float, n: float, status: str) -> str:
    """One decimal, half up; two when one would read as the limit itself on a broken rule (5.04% of a 5% rule)."""
    shown = Decimal(str(round(pct, 6))).quantize(Decimal("0.1"), ROUND_HALF_UP)
    if status == "fail" and float(shown) <= n:
        shown = Decimal(str(round(pct, 6))).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return str(shown)


def _clock(stamp: float) -> str:
    return datetime.fromtimestamp(stamp, ET).strftime("%-I:%M %p ET")


# --- the list ---------------------------------------------------------------------------------------------------------

def current(db: Session) -> list[dict]:
    """His rules now: the newest saved list, or none."""
    row = db.exec(select(TradingRuleRecord).where(TradingRuleRecord.kind == "rules")
                  .order_by(col(TradingRuleRecord.recorded_at).desc(), col(TradingRuleRecord.id).desc())).first()
    return json.loads(row.data_json)["rules"] if row else []


def _check(raw) -> dict | None:
    if raw in (None, "", {}):
        return None
    if not isinstance(raw, dict) or raw.get("kind") not in CHECKS:
        raise RulesError(f"An automatic check is one of: {', '.join(CHECKS)}.")
    spec = CHECKS[raw["kind"]]
    if "min" not in spec:
        return {"kind": raw["kind"]}
    n = raw.get("n")
    if isinstance(n, bool) or not isinstance(n, (int, float)) or not spec["min"] <= n <= spec["max"]:
        raise RulesError(f"\"{spec['words'].format(n='N')}\" needs N from {spec['min']:g} to {spec['max']:g}.")
    if spec["whole"]:
        if n != int(n):
            raise RulesError(f"\"{spec['words'].format(n='N')}\" needs a whole number.")
        n = int(n)
    return {"kind": raw["kind"], "n": n}


def clean(raw) -> list[dict]:
    """His list as it can be kept: at most ``MAX_RULES``, each with its words (an automatic rule may leave them empty and
    reads its check's words), its id (kept when it has one, else a new one) and its check or none."""
    if not isinstance(raw, list):
        raise RulesError("Send the rules as a list.")
    if len(raw) > MAX_RULES:
        raise RulesError(f"Keep it to {MAX_RULES} rules.")
    out, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            raise RulesError("Each rule is its words and, if you like, one automatic check.")
        check = _check(item.get("check"))
        text = " ".join(str(item.get("text") or "").split())[:TEXT_CHARS]
        if not text and check is None:
            continue  # an empty line
        if not text:
            text = words(check)
        rule_id = item.get("id")
        if not (isinstance(rule_id, str) and _ID.match(rule_id)) or rule_id in seen:
            rule_id = f"r_{uuid.uuid4().hex[:10]}"
        seen.add(rule_id)
        out.append({"id": rule_id, "text": text, "check": check})
    return out


def words(check: dict | None) -> str:
    if check is None:
        return "Tick-box"
    n = check.get("n")
    return CHECKS[check["kind"]]["words"].format(n=f"{n:g}" if isinstance(n, (int, float)) else "N")


def save(db: Session, raw, now: float) -> list[dict]:
    rules = clean(raw)
    db.add(TradingRuleRecord(kind="rules", record_key=f"rules:{uuid.uuid4().hex}", recorded_at=_naive(now),
                             data_json=json.dumps({"rules": rules}, sort_keys=True)))
    db.commit()
    return rules


def _naive(now: float) -> datetime:
    return datetime.fromtimestamp(now, UTC).replace(tzinfo=None)


def answers_of(raw) -> dict[str, bool]:
    """His tick-box answers as kept: rule id to ticked (True) or left unticked (False)."""
    if not isinstance(raw, dict):
        return {}
    return {k: v is True for k, v in list(raw.items())[:MAX_RULES * 2] if isinstance(k, str) and _ID.match(k)}


# --- the checks -------------------------------------------------------------------------------------------------------

def _result(rule: dict, status: str, reason: str) -> dict:
    check = rule.get("check")
    return {"id": rule["id"], "text": rule["text"], "kind": check["kind"] if check else "tick", "n": (check or {}).get("n"),
            "status": status, "reason": reason}


def _minutes(rule: dict, at: float, n: int) -> dict:
    from app.engine import desk_sparks
    try:
        _day, phase, _hours, regular = desk_sparks._session(at)
    except Exception:  # noqa: BLE001 -- the calendar could not be read: say so, never a pass
        return _result(rule, "unknown", "The market calendar could not be read.")
    if regular is None:
        return _result(rule, "unknown", "Not a trading day, so there is no open to count from.")
    opens, closes = regular
    if at < opens:
        return _result(rule, "unknown", f"Before the open ({_clock(at)}): when it fills is not known here.")
    if at >= closes:
        return _result(rule, "unknown", f"After the close ({_clock(at)}): when it fills is not known here.")
    after = int((at - opens) // 60)
    if after >= n:
        return _result(rule, "pass", f"{_clock(at)}, {after} minutes after the open.")
    return _result(rule, "fail", f"{_clock(at)}, {after} minute{'' if after == 1 else 's'} after the open.")


def evaluate(rules: list[dict], order: dict, context: dict, answers: dict[str, bool] | None) -> list[dict]:
    """Each rule against one entry. ``order``: ``instrument`` (stock, option or spread), ``expiry`` (ISO date or None),
    ``size`` (the most it can lose at entry, dollars, or None), ``stop`` (stock price or None) and ``at`` (epoch seconds:
    the fill, or the moment he copies a real order). ``context``: ``account_value`` and ``account_words`` (what it is,
    or why it is unknown), ``open_count`` (positions already open, not this one) and ``open_words``. ``answers`` None:
    tick-boxes not answered yet (``ask``)."""
    out = []
    at = order["at"]
    for rule in rules:
        check = rule.get("check")
        if check is None:
            if answers is None:
                out.append(_result(rule, "ask", "Tick it if this trade follows it."))
            elif answers.get(rule["id"]):
                out.append(_result(rule, "pass", "You ticked it."))
            else:
                out.append(_result(rule, "fail", "Not ticked."))
            continue
        kind, n = check["kind"], check.get("n")
        if kind == "stop_set":
            stop = order.get("stop")
            out.append(_result(rule, "pass", f"Stop at {stop:g}.") if isinstance(stop, (int, float)) and stop > 0
                       else _result(rule, "fail", "No stop set."))
        elif kind == "max_size_pct":
            size, value = order.get("size"), context.get("account_value")
            if not isinstance(size, (int, float)) or size <= 0:
                out.append(_result(rule, "unknown", "No size yet: set the quantity and price."))
            elif not isinstance(value, (int, float)) or value <= 0:
                out.append(_result(rule, "unknown", context.get("account_words") or "The account's value is not known."))
            else:
                pct = size / value * 100
                status = "pass" if pct <= n + EPS else "fail"
                out.append(_result(rule, status, f"{_usd(size)} is {_pct(pct, n, status)}% of {context.get('account_words')}."))
        elif kind == "max_open":
            count = context.get("open_count")
            if not isinstance(count, int):
                out.append(_result(rule, "unknown", context.get("open_words") or "Open positions are not known."))
            else:
                after = count + 1
                status = "pass" if after <= n else "fail"
                out.append(_result(rule, status, f"This makes {after} open ({context.get('open_words')})."))
        elif kind == "min_dte":
            if order.get("instrument") == "stock":
                out.append(_result(rule, "na", "Shares: no expiry."))
                continue
            try:
                expiry = date.fromisoformat(str(order.get("expiry")))
            except ValueError:
                out.append(_result(rule, "unknown", "No expiry named."))
                continue
            dte = (expiry - datetime.fromtimestamp(at, ET).date()).days
            status = "pass" if dte >= n else "fail"
            out.append(_result(rule, status, f"{dte} day{'' if dte == 1 else 's'} to expiry."))
        elif kind == "no_open_minutes":
            out.append(_minutes(rule, at, n))
    return out


def outcome(results: list[dict] | None) -> str | None:
    """followed | broken | unclear; None when there were no rules to check."""
    if not results:
        return None
    statuses = {r.get("status") for r in results}
    if "fail" in statuses:
        return "broken"
    if statuses & {"unknown", "ask"}:
        return "unclear"
    return "followed"


def paper_context(cash: float, open_count: int) -> dict:
    return {"account_value": cash, "account_words": f"paper cash {_usd(cash)}", "open_count": open_count,
            "open_words": "paper positions and working paper buys"}


def real_context(db: Session, last4: str | None, now: float) -> dict:
    """The real side: the account's value from the desk's account line (today's newest reading of that account, the
    readings the desk already keeps), and the journal's open trades (Webull left out)."""
    from app.engine.desk_value_line import session_day
    from app.models import Account, DeskAccountValue, Trade
    out: dict = {"account_value": None, "open_count": None}
    if not last4 or not re.fullmatch(r"\d{4}", str(last4)):
        out["account_words"] = "Can't check: this account has no number to find on the desk's account line."
    else:
        row = db.exec(select(DeskAccountValue).where(DeskAccountValue.masked == f"••{last4}",
                                                     DeskAccountValue.day == session_day(now).isoformat(),
                                                     DeskAccountValue.total_value.is_not(None))
                      .order_by(col(DeskAccountValue.at).desc())).first()
        if row is None:
            out["account_words"] = "Can't check: the desk's account line has no value for this account today."
        else:
            out["account_value"] = row.total_value
            out["account_words"] = f"{row.label} ••{last4} at {_usd(row.total_value)} ({_clock(row.at)})"
    webull = select(Account.id).where(Account.broker == "webull")
    count = db.exec(select(Trade.id).where(Trade.status == "open").where(col(Trade.account_id).not_in(webull))).all()
    out["open_count"] = len(count)
    out["open_words"] = "open trades in your journal; a fill not yet emailed is not counted"
    return out


def check_entry(db: Session, body: dict, now: float) -> dict:
    """The checklist for an entry he is about to make (``side`` paper or real), before he answers its tick-boxes."""
    rules = current(db)
    if not rules:
        return {"rules": [], "results": []}
    order = {"instrument": body.get("instrument"), "expiry": body.get("expiry"), "size": body.get("size"),
             "stop": body.get("stop"), "at": now}
    if body.get("side") == "real":
        context = real_context(db, body.get("last4"), now)
    else:
        from app.engine import paper_book
        context = paper_book.rules_context(db)
        if context is None:
            context = {"account_words": "Can't check: no paper account yet.", "open_words": "Can't check: no paper account yet."}
    return {"rules": rules, "results": evaluate(rules, order, context, None)}


def record_ticket(db: Session, body: dict, now: float) -> dict:
    """A real order's checklist, kept when he copies it from the Ticket (the copy is the only moment the app sees)."""
    plan = str(body.get("investigation_id") or "")
    key = str(body.get("order_key") or "")
    if not _PLAN.match(plan):
        raise RulesError("Name the saved plan.")
    if not _KEY.match(key):
        raise RulesError("The checklist has no key.")
    rules = current(db)
    if not rules:
        return {"recorded": False, "results": []}
    order = {"instrument": body.get("instrument"), "expiry": body.get("expiry"), "size": body.get("size"),
             "stop": body.get("stop"), "at": now}
    results = evaluate(rules, order, real_context(db, body.get("last4"), now), answers_of(body.get("answers")))
    data = {"symbol": str(body.get("symbol") or "")[:12], "instrument": order["instrument"], "results": results}
    db.add(TradingRuleRecord(kind="ticket", record_key=f"ticket:{key}", investigation_id=plan, recorded_at=_naive(now),
                             data_json=json.dumps(data, sort_keys=True)))
    try:
        db.commit()
    except IntegrityError:  # this copy is already kept
        db.rollback()
        return {"recorded": False, "duplicate": True, "results": results}
    return {"recorded": True, "results": results, "outcome": outcome(results)}


# --- followed versus broken -------------------------------------------------------------------------------------------

def _stats(pnls: list[float]) -> dict:
    wins = sum(1 for p in pnls if p > 0)
    return {"trades": len(pnls), "pnl": round(sum(pnls), 2), "win_rate": round(wins / len(pnls) * 100, 1) if pnls else None}


def split(items: list[tuple[list[dict] | None, float]], rules: list[dict]) -> dict:
    """Closed trades by whether his rules were followed: ``items`` are (the entry's checklist or None, realized P&L).
    ``by_rule``: for each rule a checklist named (his current words when he still has it), the trades that followed it
    and those that broke it (``na`` and can't-check results count in neither)."""
    groups: dict[str, list[float]] = {"followed": [], "broken": [], "unclear": []}
    unrecorded = 0
    per: dict[str, dict] = {}
    names = {r["id"]: r["text"] for r in rules}
    for results, pnl in items:
        found = outcome(results)
        if found is None:
            unrecorded += 1
            continue
        groups[found].append(pnl)
        for r in results:
            row = per.setdefault(r["id"], {"id": r["id"], "text": names.get(r["id"], r["text"]), "current": r["id"] in names,
                                           "followed": [], "broken": [], "unchecked": 0})
            if r["status"] == "pass":
                row["followed"].append(pnl)
            elif r["status"] == "fail":
                row["broken"].append(pnl)
            elif r["status"] in ("unknown", "ask"):
                row["unchecked"] += 1
    order = {r["id"]: i for i, r in enumerate(rules)}
    by_rule = [{**row, "followed": _stats(row["followed"]), "broken": _stats(row["broken"])}
               for row in sorted(per.values(), key=lambda r: (order.get(r["id"], len(order)), r["text"]))]
    return {**{k: _stats(v) for k, v in groups.items()}, "unrecorded": unrecorded, "by_rule": by_rule}


def real_split(db: Session, rules: list[dict]) -> dict | None:
    """Real orders he copied with a checklist, matched to a closed real trade only through the saved plan's own link
    (the plan's capture linked to its fill, or the position companion's adopted trade). The newest checklist per plan
    counts. Unmatched ones (no linked trade yet, or never placed) and still-open ones are counted, never guessed."""
    rows = db.exec(select(TradingRuleRecord).where(TradingRuleRecord.kind == "ticket")
                   .order_by(col(TradingRuleRecord.recorded_at), col(TradingRuleRecord.id))).all()
    if not rows:
        return None
    newest = {r.investigation_id: json.loads(r.data_json)["results"] for r in rows}
    from app.engine import copilot_plans
    from app.models import Trade
    plans, links = copilot_plans._plans(db)
    trade_ids: dict[str, uuid.UUID] = {}
    for plan in plans:
        if plan["investigation_id"] not in newest:
            continue
        trade = plan.get("trade")
        if trade is not None:
            trade_ids[plan["investigation_id"]] = trade.id
            continue
        capture = plan.get("capture")
        link = (links.get(capture.id) or {}).get("link") if capture is not None else None
        if link and link.get("trade_id"):
            trade_ids[plan["investigation_id"]] = uuid.UUID(link["trade_id"])
    trades = {t.id: t for t in db.exec(select(Trade).where(col(Trade.id).in_(set(trade_ids.values())))).all()} if trade_ids else {}
    items, still_open = [], 0
    for plan_id, results in newest.items():
        trade = trades.get(trade_ids.get(plan_id))
        if trade is None:
            continue
        if trade.status not in ("closed", "expired") or trade.realized_pnl is None:
            still_open += 1
            continue
        items.append((results, float(trade.realized_pnl)))
    unmatched = len(newest) - len(items) - still_open
    return {**split(items, rules), "checklists": len(newest), "matched": len(items), "open": still_open, "unmatched": unmatched}
