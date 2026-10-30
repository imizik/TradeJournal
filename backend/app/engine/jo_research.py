"""Jo's research role, app side (docs/agent/dots-integration.md § Jo research role).

Jo (OpenAI, through the Check connector) does slow, independent research outside market hours: nightly dossiers on
held names, armed plans and the day's Radar groups; a Friday audit of the copilot's week; and, on the owner's request,
the case against one confirmed plan. This module:

- builds the three read-only contexts Jo reads (``dossier``, ``audit``, ``red_team``) and publishes them as immutable
  files in the Check snapshot directory: the dossier after 18:30 New York on trading days, the audit after 17:00 on
  Fridays, the red-team list whenever its pending requests change;
- imports each sealed ``jo_research_submit`` as one saved research record (``source="jo"``), which the copilot reads
  through ``get_saved_research`` and the desk lists; a red-team answer is linked to its request, shown on the plan card;
- records the owner's red-team requests.

It runs inside the existing Jo publication/import pass and behind its switch (``JO_MORNING_CONFIG`` ``enabled``). No
model call, no notification, no trade, no monitoring.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
import logging
from pathlib import Path
import re
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.engine import copilot_investigations as inv
from app.models import CopilotInvestigation, JoRedTeamRequest, JoResearchImport, Trade, utc_now_naive
import jo_briefing_exchange as briefing_exchange
import jo_research_exchange as exchange

ET = ZoneInfo("America/New_York")
LOG = logging.getLogger(__name__)
DOSSIER_AFTER = time(18, 30)
AUDIT_AFTER = time(17, 0)
REPUBLISH = timedelta(hours=12)  # an unchanged red-team list is republished before its 24-hour publication expires
KEEP = timedelta(days=7)
LABEL = {"dossier": "Jo dossier", "audit": "Jo audit", "narrative": "Jo narrative", "red_team": "Jo red team"}
MAX_PLANS = 40
MAX_VERDICTS = 80
DAILY_IMPORTS = 40  # Jo research records saved per New York day; more are rejected so they cannot crowd out the rest
STAMP = re.compile(r"-(\d{8}T\d{12}Z)\.json$")


class RedTeamError(ValueError):
    """``code``: ``not_found`` (no such plan card) or ``not_confirmed``."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------- red-team requests

def _level(level: dict | None, typed: str | None) -> str:
    """The plan's level as text: the owner's confirmed price when the card kept it, with the card's condition."""
    level = level or {}
    price = (typed or "").strip() or str(level.get("price", ""))
    condition = " ".join(str(level[k]) for k in ("condition", "interval") if level.get(k))
    return f"{price} ({condition})" if condition else price


def request_red_team(db: Session, investigation_id: str, proposal_id: str) -> tuple[dict, bool]:
    """Ask Jo to argue against a confirmed plan card. Returns (request, created); a second ask returns the first."""
    try:
        record = inv.get(investigation_id, session=db)
    except inv.InvestigationError:
        raise RedTeamError("not_found", "No such investigation.") from None
    card = next((p for m in record["transcript"] for p in m.get("proposals") or () if p.get("id") == proposal_id), None)
    if card is None or card.get("kind") != "trade_plan":
        raise RedTeamError("not_found", "That plan card is not saved with this investigation yet; try again in a moment.")
    outcome = card.get("outcome") or {}
    if outcome.get("state") != "confirmed":
        raise RedTeamError("not_confirmed", "This plan is not saved as confirmed yet (a Confirm may still be saving); "
                                            "try again in a moment.")
    existing = _request_for(db, record["id"], proposal_id)
    if existing is not None:
        return view(db, existing), False
    fields = outcome.get("fields") or {}
    row = JoRedTeamRequest(
        investigation_id=record["id"], proposal_id=proposal_id, symbol=card["symbol"], direction=card["direction"],
        instrument=card["instrument"], contract=(fields.get("contract") or card.get("contract") or None),
        thesis=(fields.get("thesis") or card["thesis"])[:300], entry=_level(card.get("entry_trigger"), fields.get("entry")),
        invalidation=_level(card.get("invalidation"), fields.get("invalidation")),
        time_stop=(fields.get("time_stop") or card.get("time_stop") or None))
    db.add(row)
    try:
        db.commit()
    except IntegrityError:  # a second window asked at the same moment
        db.rollback()
        return view(db, _request_for(db, record["id"], proposal_id)), False
    db.refresh(row)
    return view(db, row), True


def _request_for(db: Session, investigation_id: str, proposal_id: str) -> JoRedTeamRequest | None:
    return db.exec(select(JoRedTeamRequest).where(JoRedTeamRequest.investigation_id == investigation_id,
                                                  JoRedTeamRequest.proposal_id == proposal_id)).first()


def _utc(value: datetime | None) -> str | None:
    return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z") if value else None


def view(db: Session, row: JoRedTeamRequest) -> dict:
    out = {"request_id": str(row.id), "proposal_id": row.proposal_id, "symbol": row.symbol, "status": row.status,
           "requested_at": _utc(row.created_at), "answered_at": _utc(row.answered_at), "answer": None}
    if row.answer_investigation_id is not None:
        answer = inv.get(row.answer_investigation_id, session=db)
        findings = answer["findings"] or {}
        out["answer"] = {"investigation_id": answer["id"], "title": answer["conclusion"] or answer["title"],
                         "body": findings.get("report") or findings.get("summary", ""),
                         "citations": (answer["findings"] or {}).get("citations", [])}
    return out


def red_team_for(db: Session, investigation_id: str) -> list[dict]:
    rows = db.exec(select(JoRedTeamRequest).where(JoRedTeamRequest.investigation_id == investigation_id)
                   .order_by(JoRedTeamRequest.created_at)).all()
    return [view(db, r) for r in rows]


# --------------------------------------------------------------------------- contexts

def _iso(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _held(db: Session, accounts: list[UUID]) -> list[dict]:
    """Open positions by symbol in the approved accounts: held, the instrument and each option's expiry week. No
    accounts, sizes or prices."""
    query = select(Trade).where(Trade.status == "open", Trade.account_id.in_(list(accounts) or [None]))
    by_symbol: dict[str, dict] = {}
    for trade in db.exec(query).all():
        row = by_symbol.setdefault(trade.ticker, {"symbol": trade.ticker, "held": True, "instruments": set(), "option_expiry_weeks": set()})
        if trade.instrument_type == "option":
            row["instruments"].add("puts" if trade.option_type == "put" else "calls")
            if trade.expiration:
                row["option_expiry_weeks"].add((trade.expiration - timedelta(days=trade.expiration.weekday())).isoformat())
        else:
            row["instruments"].add("stock")
    return [{**r, "instruments": sorted(r["instruments"]), "option_expiry_weeks": sorted(r["option_expiry_weeks"])}
            for r in sorted(by_symbol.values(), key=lambda r: r["symbol"])]


def _armed(db: Session) -> list[dict]:
    from app.engine import copilot_plans
    rows = copilot_plans.board(db, quotes=lambda symbols: ({}, None, None))["plans"]
    return [{"plan_id": r["investigation_id"], "symbol": r["symbol"], "direction": r["direction"],
             "instrument": r["instrument"], "thesis": r["thesis"],
             "entry": (r["entry"] or {}).get("price"), "invalidation": (r["invalidation"] or {}).get("price"),
             "position": r["position"]} for r in rows[:MAX_PLANS]]


def _radar(day: date, now: datetime) -> dict:
    from app.routers import radar
    store, reason = radar._store(read_only=True)
    if store is None:
        return {"state": "off", "reason": reason}
    try:
        feed = radar._read_feed(store, day.isoformat(), None, now.timestamp())
    except Exception as exc:  # a busy or damaged file leaves the dossier without Radar, never without the rest
        LOG.warning("Jo research: Radar unreadable (%s)", type(exc).__name__)
        return {"state": "unavailable", "reason": "The Radar file could not be read."}
    groups, stocks = [], []
    for e in feed["events"]:
        row = {"direction": e["direction"], "summary": e["summary"], "first_seen_at": e["first_seen_at"],
               "latest_status": e["latest_status"]}
        if e["kind"] == "group_move":
            groups.append({"group": e["group"], "symbols": e["symbols"], **row})
        else:
            stocks.append({"symbol": e["symbols"][0], "kind": e["kind"], "benchmark": e["benchmark"], **row})
    return {"state": feed["state"], "session": feed["session"], "groups": groups[:30], "stock_events": stocks[:60]}


def dossier_context(db: Session, now: datetime, accounts: list[UUID]) -> dict:
    day = now.astimezone(ET).date()
    return {"day": day.isoformat(), "held": _held(db, accounts), "armed_plans": _armed(db), "radar": _radar(day, now),
            "provenance": {"held": "journal open positions in the accounts approved for Jo; no accounts, quantities or prices",
                           "armed_plans": "confirmed copilot plans still armed or in a position; thesis as confirmed",
                           "radar": "the day's saved Radar events as the Radar feed shows them"}}


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _scrub(value, keep=("plan_id",)):
    """Drop identifiers (``id``, ``*_id``, ``thread``) except plan ids, account names and dollar amounts (``*_usd``),
    everywhere: counts and percentages stay, so no position's size can be read back."""
    if isinstance(value, dict):
        return {k: _scrub(v, keep) for k, v in value.items()
                if k in keep or not (k == "id" or k.endswith("_id") or k.endswith("_usd")
                                     or k in ("thread", "threads", "account", "accounts"))}
    if isinstance(value, list):
        return [_scrub(v, keep) for v in value]
    return value


def _lines(text: str) -> dict:
    """The copilot's Verdict and Read lines from an answer; never the rest of its reasoning."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        for key, prefix in (("verdict", "Verdict:"), ("read", "Read:")):
            if key not in out and line.startswith(prefix):
                out[key] = line[:240]
    return out


def _plan_outcomes(db: Session) -> dict[str, dict]:
    from app.engine import copilot_plans
    plans, links = copilot_plans._plans(db)
    trades = {}
    out = {}
    for plan in plans:
        link = (links.get(plan["capture"].id, {}) if plan["capture"] else {}).get("link") or {}
        row = {"position": plan["position"],
               "entry_alert": None if plan["entry"] is None else ("armed" if plan["entry"].state == "active" else "hit"),
               "invalidation_alert": None if plan["invalidation"] is None else ("armed" if plan["invalidation"].state == "active" else "hit"),
               "time_stop": plan["stop"].delivery if plan["stop"] else None}
        if link.get("trade_id"):
            trade = trades.get(link["trade_id"]) or db.get(Trade, UUID(link["trade_id"]))
            trades[link["trade_id"]] = trade
            if trade is not None:
                row.update(trade_status=trade.status, pnl_pct=None if trade.pnl_pct is None else round(float(trade.pnl_pct), 1),
                           entry_timing=link.get("timing"))
        out[plan["investigation_id"]] = row
    return out


def audit_context(db: Session, now: datetime) -> dict:
    """The copilot's week (Monday to Friday, New York): every plan card it drafted with its answer's Verdict and Read
    lines and what happened to it, every other answer's Verdict line, and the week review's totals, alerts and pings."""
    from app.ai import copilot_review
    monday = _week_start(now.astimezone(ET).date())
    start = datetime.combine(monday, time(), ET).astimezone(timezone.utc).replace(tzinfo=None)
    end = start + timedelta(days=7)
    rows = db.exec(select(CopilotInvestigation).where(CopilotInvestigation.source == "copilot",
                                                      CopilotInvestigation.updated_at >= start,
                                                      CopilotInvestigation.created_at < end)
                   .order_by(CopilotInvestigation.created_at)).all()
    outcomes = _plan_outcomes(db)
    plans, verdicts, words = [], [], Counter()
    for row in rows:
        record = inv.full(row)
        for message in record["transcript"]:
            if message["role"] != "assistant":
                continue
            lines = _lines(message["content"])
            if "verdict" in lines:
                words[lines["verdict"].removeprefix("Verdict:").strip().split(" ", 1)[0].strip("—-:")] += 1
            cards = [p for p in message.get("proposals") or () if p.get("kind") == "trade_plan"]
            for card in cards:
                outcome = card.get("outcome") or {}
                fields = outcome.get("fields") or {}
                plans.append({"plan_id": record["id"], "symbol": card["symbol"], "direction": card["direction"],
                              "instrument": card["instrument"], "thesis": fields.get("thesis") or card["thesis"],
                              "entry": _level(card.get("entry_trigger"), fields.get("entry")),
                              "invalidation": _level(card.get("invalidation"), fields.get("invalidation")),
                              **lines, "card": outcome.get("state", "not_acted_on"),
                              "outcome": outcomes.get(record["id"]) if outcome.get("state") == "confirmed" else None})
            if not cards and "verdict" in lines:
                verdicts.append({"symbol": record["symbol"], "day": row.created_at.replace(tzinfo=timezone.utc).astimezone(ET).date().isoformat(),
                                 **lines})
    try:
        week = copilot_review.week_review(monday.isoformat(), session=db)
    except Exception as exc:
        LOG.warning("Jo research: week review unavailable (%s)", type(exc).__name__)
        week = {"state": "unavailable"}
    review = {k: week[k] for k in ("state", "reason", "week", "sample", "totals", "planned", "follow_through", "alerts",
                                   "pings", "units") if k in week}
    return {"week": {"start": monday.isoformat(), "end": (monday + timedelta(days=4)).isoformat()},
            "plans": plans[:MAX_PLANS], "other_verdicts": verdicts[-MAX_VERDICTS:], "verdict_counts": dict(words),
            "week_review": _scrub(review),
            "provenance": {"plans": "trade plan cards the copilot drafted this week, the Verdict and Read lines of the "
                                    "answer that drafted each, what the owner did with the card and, once confirmed, "
                                    "its alerts, position and linked trade",
                           "other_verdicts": "the Verdict and Read lines of the week's other copilot answers",
                           "week_review": "the copilot's own week review: measured totals, plans' follow-through, "
                                          "phone alerts by kind and what followed, pings; counts and percentages "
                                          "only, no dollar amounts or account names"}}


def red_team_context(db: Session) -> dict:
    rows = db.exec(select(JoRedTeamRequest).where(JoRedTeamRequest.status == "pending")
                   .order_by(JoRedTeamRequest.created_at).limit(20)).all()
    return {"requests": [{"request_id": str(r.id), "symbol": r.symbol, "direction": r.direction, "instrument": r.instrument,
                          "contract": r.contract, "thesis": r.thesis, "entry": r.entry, "invalidation": r.invalidation,
                          "time_stop": r.time_stop, "requested_at": _utc(r.created_at)} for r in rows],
            "provenance": "confirmed copilot plans the owner asked Jo to argue against: the plan's own fields only"}


BUILDERS = {"dossier": dossier_context, "audit": lambda db, now, accounts: audit_context(db, now),
            "red_team": lambda db, now, accounts: red_team_context(db)}


# --------------------------------------------------------------------------- publication

def publish(check, actor: str, kind: str, data: dict, now: datetime) -> str:
    value = exchange.Context(profile_id=actor, kind=kind, as_of=now, published_at=now, expires_at=now + exchange.LIFETIME,
                             data=data).model_dump(mode="json")
    name = exchange.context_name(actor, kind, now)
    briefing_exchange.write(check.market_watch_snapshots_dir, name, value)
    return name


def _published(check, actor: str, kind: str) -> list[tuple[datetime, Path]]:
    out = []
    for path in Path(check.market_watch_snapshots_dir).glob(exchange.context_prefix(actor, kind) + "*.json"):
        if found := STAMP.search(path.name):
            out.append((datetime.strptime(found.group(1), "%Y%m%dT%H%M%S%fZ").replace(tzinfo=timezone.utc), path))
    return sorted(out)


# --------------------------------------------------------------------------- import

def _title(kind: str, symbols: list[str], as_of: datetime) -> str:
    day = as_of.astimezone(ET)
    return " · ".join(p for p in (LABEL[kind], " ".join(symbols[:4]), f"{day:%b} {day.day}") if p)[:120]


def _summary(body: str) -> str:
    first = body.strip().split("\n\n", 1)[0].strip()
    return first[:1999] + "…" if len(first) > 2000 else first


def save(db: Session, key: str, data: dict, received_at: datetime) -> str:
    """One sealed submission → one saved research record (source ``jo``), committed with its import row and, for a
    red team, the answered request. Returns the record's id."""
    request = None
    symbols = list(data["symbols"])
    if data["kind"] == "red_team":
        request = db.get(JoRedTeamRequest, UUID(data["request_id"]))
        if request is None or request.status != "pending":
            raise LookupError("No pending red-team request")
        symbols = [request.symbol] + [s for s in symbols if s != request.symbol]
    as_of = datetime.fromisoformat(data["as_of"])
    findings = {"summary": _summary(data["body"]),
                "citations": [{"url": s["url"], "publisher": s["publisher"], "published_at": s["published_at"]}
                              for s in data["sources"]],
                "evidence_at": as_of.isoformat(), "report": data["body"]}
    ask = (f"{LABEL[data['kind']]} from Jo's research run" + (f" on {', '.join(symbols)}" if symbols else "")
           + f". Received {received_at.astimezone(ET):%b %d %H:%M} ET; evidence as of {as_of.astimezone(ET):%b %d %H:%M} ET."
           + (f" The case against the {request.direction} {request.symbol} plan." if request else ""))
    investigation_id = uuid4()
    rows = [JoResearchImport(submission_key=key, kind=data["kind"], investigation_id=investigation_id,
                             request_id=request.id if request else None)]
    if request is not None:
        request.status, request.answered_at, request.answer_investigation_id = "answered", utc_now_naive(), investigation_id
        rows.append(request)
    inv.save_jo_result(investigation_id=investigation_id, title=_title(data["kind"], symbols, as_of),
                       symbol=symbols[0] if symbols else None, conclusion=data["title"][:280], findings=findings,
                       # Jo's text stays in the findings, a tool result for the copilot (get_saved_research), never a
                       # transcript answer a follow-up would replay to the copilot as its own words.
                       transcript=[{"role": "user", "content": ask}],
                       also=rows, session=db)
    return str(investigation_id)


class Capped(ValueError):
    pass


class Foreign(ValueError):
    """A request file this profile cannot import (another profile's, or named for another operation)."""


def _imported_today(db: Session, now: datetime) -> int:
    midnight = datetime.combine(now.astimezone(ET).date(), time(), ET).astimezone(timezone.utc).replace(tzinfo=None)
    return len(db.exec(select(JoResearchImport.submission_key).where(JoResearchImport.imported_at >= midnight)).all())


def import_submission(db: Session, check, actor: str, key: str, now: datetime) -> dict:
    snapshots, outbox = check.market_watch_snapshots_dir, check.market_watch_outbox_dir
    request = exchange.Submission.model_validate(briefing_exchange.read(outbox, exchange.request_name(key)))
    if request.profile_id != actor or briefing_exchange.operation_key(actor, request.operation_id) != key:
        raise Foreign("Submission identity mismatch")
    current = exchange.status(snapshots, outbox, actor, request.operation_id)
    if current["status"] != "pending_import":
        return current
    ack = {"profile_id": actor, "submission_sha256": briefing_exchange.digest(request.model_dump(mode="json")),
           "imported_at": now.isoformat()}
    try:
        if request.received_at > now:
            raise ValueError("Future submission")
        if briefing_exchange.digest(request.body) != request.body_sha256:
            raise ValueError("Submission body changed")
        data = exchange.validate_body(request.body, request.received_at)
        done = db.get(JoResearchImport, key)
        if done is None and _imported_today(db, now) >= DAILY_IMPORTS:
            raise Capped(f"Daily cap of {DAILY_IMPORTS} Jo research records reached; resubmit tomorrow under a new operation_id")
        record_id = str(done.investigation_id) if done else save(db, key, data, request.received_at)
        ack.update(status="saved", record_id=record_id)
    except Capped as exc:
        db.rollback()
        ack.update(status="rejected", reason=str(exc))
    except (ValueError, LookupError, ValidationError, inv.InvestigationError):
        db.rollback()
        ack.update(status="rejected", reason="Invalid research, or no pending red-team request with that ID")
    try:
        briefing_exchange.write(snapshots, exchange.receipt_name(key), ack)
    except ValueError:
        # Concurrent importers can have distinct imported_at times, but must agree on the result.
        other = briefing_exchange.read(snapshots, exchange.receipt_name(key))
        if {k: v for k, v in other.items() if k != "imported_at"} != {k: v for k, v in ack.items() if k != "imported_at"}:
            raise
    return exchange.status(snapshots, outbox, actor, request.operation_id)


# --------------------------------------------------------------------------- the pass

class ResearchRunner:
    """One pass: import waiting submissions, publish whichever contexts are due, prune week-old contexts."""

    def __init__(self, engine, config_loader=None, calendar=None):
        from app.engine import jo_morning
        self.engine, self.config_loader = engine, config_loader or jo_morning.load_config
        if calendar is None:
            from app.engine.chart_calendar import chart_calendar
            calendar = chart_calendar.hours
        self.calendar = calendar
        self.red_team_digest = None
        self.last_error = None
        self.scan_cursor = ""

    def due(self, check, actor: str, kind: str, now: datetime, data_digest: str | None = None) -> bool:
        local = now.astimezone(ET)
        published = _published(check, actor, kind)
        last = published[-1][0] if published else None
        if kind == "red_team":
            return last is None or data_digest != self.red_team_digest or now - last >= REPUBLISH
        if last is not None and last.astimezone(ET).date() == local.date():
            return False
        if kind == "audit":
            return local.weekday() == 4 and local.time() >= AUDIT_AFTER
        hours = self.calendar(local.date())
        return bool(hours) and hours.get("status") == "open" and local.time() >= DOSSIER_AFTER

    def run_once(self, now: datetime | None = None) -> dict:
        from jo_briefing_owner import binding, load_binding
        now = now or datetime.now(timezone.utc)
        config = self.config_loader()
        if config is None or not config.enabled:
            return {"status": "disabled"}
        check = load_binding(config.check_config)
        actor = binding(check)
        imported, errors, published = 0, 0, []
        with Session(self.engine) as db:
            # Completed receipts are skipped before the per-pass bound, so old saves never starve new ones.
            keys = [key for path in Path(check.market_watch_outbox_dir).glob("jo-research-request-*.json")
                    if re.fullmatch(r"[0-9a-f]{64}", key := path.name.removeprefix("jo-research-request-").removesuffix(".json"))
                    and not (Path(check.market_watch_snapshots_dir) / exchange.receipt_name(key)).exists()]
            # Rotate: files that never import (another profile's, unreadable) cannot hold the first 100 places.
            for key in sorted(keys, key=lambda k: (k <= self.scan_cursor, k))[:100]:
                self.scan_cursor = key
                try:
                    import_submission(db, check, actor, key, now)
                    imported += 1
                except Foreign:
                    continue  # never this profile's to import; the rotation keeps it from holding a place
                except Exception:
                    db.rollback()
                    errors += 1
            for kind in ("red_team", "dossier", "audit"):
                try:
                    due = kind == "red_team" or self.due(check, actor, kind, now)
                    data = BUILDERS[kind](db, now, config.account_ids) if due else None
                    digest = briefing_exchange.digest(data) if kind == "red_team" else None
                    if data is not None and self.due(check, actor, kind, now, digest):
                        publish(check, actor, kind, data, now)
                        if kind == "red_team":
                            self.red_team_digest = digest
                        published.append(kind)
                except Exception as exc:
                    db.rollback()
                    errors += 1
                    LOG.warning("Jo research: %s context not published (%s)", kind, type(exc).__name__)
            for kind in exchange.CONTEXT_KINDS:
                for when, path in _published(check, actor, kind)[:-1]:
                    if now - when > KEEP:
                        path.unlink(missing_ok=True)
        self.last_error = "Some Jo research could not be imported or published" if errors else None
        return {"status": "ok", "imported": imported, "published": published, "errors": errors}
