"""Opt-in morning publication/import inside the existing API process; no inference.

Read approved local records and bounded existing-provider market evidence.
Existing Check OAuth/file boundaries remain. No inference or Shadow mutation.
"""
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import re
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator
from sqlmodel import Session, select

from app.engine import jo_briefing as store
from app.engine.chart_journal import open_lots
from app.engine.jo_morning_market import collect_backdrop, collect_market
from app.models import FILL_LIGHT, Account, ChartSettingsRecord, Fill, Trade, TradeFill, TradeCapture, MorningBriefingPacket, MorningBriefingRecord
from jo_briefing_common import PacketSave, Strict
import jo_briefing_exchange as exchange
from jo_briefing_owner import binding, load_binding, publish, import_submission

ET = ZoneInfo("America/New_York")
LOG = logging.getLogger(__name__)
# Written by deploy/alerts.py (same service user); read only to show what the watchdog sent.
ALERTS_STATE = Path("/var/lib/tradejournal/alerts/state.json")


class MorningConfig(Strict):
    enabled: bool = False
    check_config: str
    account_ids: list[UUID] = Field(min_length=1, max_length=20)
    publish_time: str = Field(default="08:45", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    deadline: str = Field(default="09:15", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")

    @model_validator(mode="after")
    def ordered(self):
        if self.publish_time >= self.deadline:
            raise ValueError("Publication must precede the deadline")
        if len(set(self.account_ids)) != len(self.account_ids):
            raise ValueError("Account scope must be unique")
        if not Path(self.check_config).is_absolute():
            raise ValueError("Check configuration must be absolute")
        return self


def load_config():
    path = os.environ.get("JO_MORNING_CONFIG")
    if not path or os.environ.get("TJ_DOT_TRIAL_ENABLED") == "true":
        return None
    value = MorningConfig.model_validate(exchange.read(str(Path(path).parent), Path(path).name))
    return value if value.enabled else None


def at(day, clock):
    hour, minute = map(int, clock.split(":"))
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ET).astimezone(timezone.utc)


def operation(config, actor, day):
    return "morning-" + exchange.digest({"version": 1, "actor": actor, "day": day.isoformat(),
        "scope": sorted(str(i) for i in config.account_ids), "publish": config.publish_time, "deadline": config.deadline})


def collect(session, config, actor, now, market_reader=None, backdrop_reader=collect_backdrop):
    day = now.astimezone(ET).date()
    accounts = session.exec(select(Account).where(Account.id.in_(config.account_ids))).all()
    if len(accounts) != len(config.account_ids) or any((a.broker or "").lower() == "webull" for a in accounts):
        raise ValueError("Approved account scope missing or excluded")
    evidence, gaps = [], ["Journal import freshness is not verified by this packet; positions reflect saved fills.",
        "No option risk metrics or verified live broker holdings. Saved levels may need split/basis review."]

    evidence_bytes = 0
    symbols = []
    # Exclude every saved holding/watchlist name from discovery, even outside packet display caps.
    discovery_excluded = set(session.exec(select(Trade.ticker).where(
        Trade.account_id.in_(config.account_ids), Trade.status == "open",
        Trade.opened_at <= now.astimezone(ET).replace(tzinfo=None))).all())
    packet_time = now

    def add(key, kind, text, source, observed=None, retrieved=None):
        nonlocal evidence_bytes
        if len(evidence) >= 80:
            if "Evidence limited to 80 items." not in gaps:
                gaps.append("Evidence limited to 80 items.")
            return
        if len(text) > 4000:
            gaps.append(f"{key}: text truncated to 4000 characters.")
        # Leave ample room for JSON keys, timestamps, references and gap text.
        size = len(exchange.canonical(text[:4000]).encode()) + len(source.encode()) + 512
        if evidence_bytes + size > 96 * 1024:
            if "Evidence omitted to fit the packet byte limit." not in gaps:
                gaps.append("Evidence omitted to fit the packet byte limit.")
            return False
        evidence_bytes += size
        evidence.append(dict(id=key, kind=kind, text=text[:4000], source=source,
            observed_at=observed, retrieved_at=retrieved or now))
        return True

    add("schedule", "fact", exchange.canonical({"deadline": at(day, config.deadline).isoformat()}), "Morning publication schedule")
    trades = session.exec(select(Trade).where(Trade.account_id.in_(config.account_ids), Trade.status == "open",
        Trade.opened_at <= now.astimezone(ET).replace(tzinfo=None))
        .order_by(Trade.opened_at.desc(), Trade.id).limit(21)).all()
    if len(trades) > 20:
        gaps.append("Open positions limited to the 20 most recently opened trades.")
    for index, trade in enumerate(trades[:20]):
        fills = session.exec(select(Fill).options(*FILL_LIGHT).join(TradeFill, TradeFill.fill_id == Fill.id).where(
            TradeFill.trade_id == trade.id, Fill.account_id == trade.account_id, Fill.executed_at <= now.astimezone(ET).replace(tzinfo=None))).all()
        lots = open_lots([dict(id=f.id, side=f.side, contracts=f.contracts, price=f.price, executed_at=f.executed_at) for f in fills])
        if not fills or lots["open"] <= 0:
            gaps.append(f"{trade.ticker}: open-trade record has no reconcilable remaining fills.")
            continue
        # An allowlist avoids account identifiers, raw emails and fill keys.
        detail = {"symbol": trade.ticker, "instrument": trade.instrument_type, "direction": lots["direction"],
            "remaining_quantity": lots["open"], "unit": "contracts" if trade.instrument_type == "option" else "shares",
            "remaining_average_cost": lots["avg_cost"], "cost_unit": "USD per contract" if trade.instrument_type == "option" else "USD per share", "option_type": trade.option_type,
            "strike": float(trade.strike) if trade.strike is not None else None,
            "expiration": trade.expiration.isoformat() if trade.expiration else None}
        symbols.append(trade.ticker)
        add(f"position-{index + 1}", "fact", exchange.canonical(detail), "Saved journal fills; FIFO remaining lots")
    if not trades:
        add("positions", "fact", "No open journal trades in the approved account scope.", "Saved journal query")
    settings = session.get(ChartSettingsRecord, "default")
    try:
        data = json.loads(settings.data_json) if settings else {}
        watched = data.get("watchlist")
        if not isinstance(watched, list) or any(not isinstance(s, str) or not re.fullmatch(r"[A-Z][A-Z0-9./-]{0,14}", s) for s in watched):
            raise ValueError("No valid saved watchlist")
        discovery_excluded.update(watched)
        add("watchlist", "fact", "Saved Charts watchlist: " + (", ".join(watched[:30]) or "empty"), "Charts saved workspace",
            settings.updated_at.replace(tzinfo=timezone.utc))
        if len(watched) > 30:
            gaps.append("Watchlist limited to 30 saved symbols.")
        symbols.extend(watched[:30])
        levels = data.get("levels", {})
        for i, symbol in enumerate(watched[:10]):
            rows = levels.get(symbol, []) if isinstance(levels, dict) else []
            clean = [{"price": r["price"], "label": str(r.get("label", ""))[:120]} for r in rows[:10]
                     if isinstance(r, dict) and type(r.get("price")) in (int, float) and 0 < r["price"] < 1e9]
            if clean:
                add(f"levels-{i + 1}", "belief", f"{symbol}: {exchange.canonical(clean)}", "Owner saved chart levels; not current market prices",
                    settings.updated_at.replace(tzinfo=timezone.utc))
        if len(watched) > 10:
            gaps.append("Saved levels limited to the first 10 watchlist symbols and 10 levels each.")
    except (ValueError, TypeError, AttributeError):
        gaps.append("Saved Charts watchlist/levels unavailable; no default tickers substituted.")
    # Saved local backdrop (calendar, VIX, earnings) first, so the evidence cap never drops it.
    if backdrop_reader is not None:
        try:
            backdrop_evidence, backdrop_gaps = backdrop_reader(session, symbols, now)
        except Exception:
            LOG.warning("Jo morning backdrop unavailable", exc_info=True)
            backdrop_evidence, backdrop_gaps = [], ["Macro calendar, VIX and earnings backdrop unavailable."]
        gaps.extend(backdrop_gaps)
        for row in backdrop_evidence:
            add(row["id"], row["kind"], row["text"], row["source"], row["observed_at"], row["retrieved_at"])
    if market_reader is not None:
        market_evidence, market_gaps = market_reader(symbols, now, excluded_symbols=discovery_excluded)
        gaps.extend(market_gaps)
        for row in market_evidence:
            if add(row["id"], row["kind"], row["text"], row["source"], row["observed_at"], row["retrieved_at"]):
                packet_time = max(packet_time, row["retrieved_at"])
    else:
        gaps.append("No price or headline source was requested for this packet.")
    captures = session.exec(select(TradeCapture).where(TradeCapture.account_id.in_(config.account_ids),
        TradeCapture.received_at >= (now - timedelta(days=30)).replace(tzinfo=None), TradeCapture.received_at <= now.replace(tzinfo=None))
        .order_by(TradeCapture.received_at.desc(), TradeCapture.id).limit(11)).all()
    for i, row in enumerate(captures[:10]):
        text = " | ".join(str(x) for x in (row.underlying, row.side, row.setup_label, row.wording, row.note) if x)
        add(f"capture-{i + 1}", "belief", text, "Owner capture; not an activated plan", row.received_at.replace(tzinfo=timezone.utc))
    if len(captures) > 10:
        gaps.append("Captures limited to the latest 10 in 30 days; images/audio/transcripts are excluded.")
    memories = store.memories(session, "active", None, 31)
    selected_memories, memory_bytes = [], 0
    for i, memory in enumerate(memories[:30]):
        size = len(exchange.canonical(memory).encode())
        if memory_bytes + size > 256 * 1024:
            if "Memory revisions omitted to fit the published context byte limit." not in gaps:
                gaps.append("Memory revisions omitted to fit the published context byte limit.")
            continue
        if add(f"memory-{i + 1}", "belief", memory["body"]["original_text"], "Explicit owner memory; not a market fact",
               datetime.fromisoformat(memory["received_at"])):
            selected_memories.append(memory["id"])
            memory_bytes += size
    if len(memories) > 30:
        gaps.append("Active memories limited to the latest 30; packet retains exact revision IDs.")
    candidates = session.exec(select(MorningBriefingRecord, MorningBriefingPacket).join(MorningBriefingPacket).where(
        MorningBriefingPacket.day < day, MorningBriefingRecord.redacted_at.is_(None), MorningBriefingPacket.redacted_at.is_(None))
        .order_by(MorningBriefingPacket.day.desc(), MorningBriefingRecord.created_at.desc()).limit(30)).all()
    previous = next((brief for brief, packet in candidates if packet.operation_id == operation(config, actor, packet.day)), None)
    if previous:
        add("prior-brief", "belief", json.loads(previous.body_json)["summary"], "Prior saved briefing in matching account scope/profile; not current facts",
            previous.created_at.replace(tzinfo=timezone.utc))
    else:
        gaps.append("No matching account-scope/profile briefing among the latest 30 prior records.")
    return PacketSave(operation_id=operation(config, actor, day), day=day, as_of=packet_time,
        scope=f"{len(accounts)} explicitly approved accounts; saved journal, Charts workspace and personal memories. Deadline {at(day, config.deadline).isoformat()}",
        evidence=evidence, gaps=gaps[:30], memory_revision_ids=selected_memories)


class MorningRunner:
    def __init__(self, engine, config_loader=load_config, calendar=None, market_reader=collect_market, backdrop_reader=collect_backdrop):
        self.engine, self.config_loader = engine, config_loader
        self.market_reader, self.backdrop_reader = market_reader, backdrop_reader
        if calendar is None:
            from app.engine.chart_calendar import chart_calendar
            calendar = chart_calendar.hours
        self.calendar = calendar
        self.last_pass = None
        self.last_error = None
        self.last_status = None
        # Submissions still waiting for a receipt after this pass, for the watchdog.
        self.pending = {"count": 0, "oldest_submitted_at": None, "unreadable": 0}
        self.scan_cursor = ""

    def run_once(self, now=None):
        now = now or datetime.now(timezone.utc)
        config = self.config_loader()
        if config is None or not config.enabled:
            return {"status": "disabled"}
        check = load_binding(config.check_config)
        actor = binding(check)
        imported, errors = 0, 0
        with Session(self.engine) as session:
            # Stable file keys make every pass and restart recoverable. Completed receipts
            # are skipped before the per-pass work bound; no starvation from old saves.
            pending = []
            for path in Path(check.market_watch_outbox_dir).glob("jo-request-*.json"):
                key = path.name.removeprefix("jo-request-").removesuffix(".json")
                if not re.fullmatch(r"[0-9a-f]{64}", key):
                    continue
                if not (Path(check.market_watch_snapshots_dir) / f"jo-receipt-{key}.json").exists():
                    pending.append(path)
            ordered = sorted(pending, key=lambda p: (p.name <= self.scan_cursor, p.name))
            for path in ordered[:100]:
                self.scan_cursor = path.name
                try:
                    request = exchange.Submission.model_validate(exchange.read(check.market_watch_outbox_dir, path.name))
                    if request.profile_id != actor or exchange.operation_key(actor, request.operation_id) not in path.name:
                        continue
                    import_submission(session, check, request.operation_id, now)
                    imported += 1
                except Exception:
                    session.rollback()
                    errors += 1
            self.pending = self.waiting(check, actor, pending)
            day = now.astimezone(ET).date()
            hours = self.calendar(day)
            if not hours or hours.get("status") != "open":
                state = "calendar_unavailable" if not hours else "closed"
            elif not at(day, config.publish_time) <= now < at(day, f"{hours['open']//60:02d}:{hours['open']%60:02d}"):
                state = "outside_publication_window"
            else:
                key = operation(config, actor, day)
                row = session.exec(select(MorningBriefingPacket).where(MorningBriefingPacket.operation_id == key)).first()
                if row is None:
                    saved = store.save_packet(session, collect(session, config, actor, now, self.market_reader, self.backdrop_reader))
                    row = session.get(MorningBriefingPacket, UUID(saved["id"]))
                # Use the frozen cutoff for repeat publication, never extend expiry on restart.
                published = datetime.fromisoformat(json.loads(row.body_json)["as_of"])
                publish(session, check, row.id, published)
                exchange.write(check.market_watch_snapshots_dir, f"jo-morning-{actor}-{day.isoformat()}.json",
                    {"packet_id": str(row.id), "profile_id": actor, "day": day.isoformat()})
                state = "published"
        self.last_pass, self.last_error = now.isoformat(), "Some submissions could not be imported" if errors else None
        self.last_status = state
        return {"status": state, "imported": imported, "errors": errors}

    @staticmethod
    def waiting(check, actor, candidates, limit=200):
        """This profile's importable submissions with no receipt yet (briefings or memories).

        Files that can never import (unreadable, or named for another operation) are counted
        as unreadable; other profiles' files are ignored. At most ``limit`` files are read.
        """
        count, oldest, unreadable = 0, None, 0
        for path in sorted(candidates, key=lambda p: p.name)[:limit]:
            key = path.name.removeprefix("jo-request-").removesuffix(".json")
            if (Path(check.market_watch_snapshots_dir) / f"jo-receipt-{key}.json").exists():
                continue
            try:
                request = exchange.Submission.model_validate(exchange.read(check.market_watch_outbox_dir, path.name))
            except Exception:
                unreadable += 1
                continue
            if request.profile_id != actor:
                continue
            if exchange.operation_key(actor, request.operation_id) not in path.name:
                unreadable += 1
                continue
            count += 1
            oldest = request.received_at if oldest is None else min(oldest, request.received_at)
        return {"count": count, "oldest_submitted_at": oldest.isoformat() if oldest else None, "unreadable": unreadable}


def _frozen_deadline(packet_row):
    """The deadline frozen in a scheduled packet's own schedule evidence, if readable."""
    try:
        for item in json.loads(packet_row.body_json)["evidence"]:
            if item["id"] == "schedule":
                value = datetime.fromisoformat(json.loads(item["text"])["deadline"])
                return value if value.tzinfo is not None else None
    except (ValueError, TypeError, KeyError):
        pass
    return None


def delivery(session, day, now, config, actor, hours):
    """Did the scheduled obligation for this day reach the journal in time?

    Fulfilment is judged on journal availability (``created_at``): a brief Check received
    at 09:14 but imported at 09:40 still missed a 09:15 deadline. Only a record citing the
    day's own scheduled packet fulfils it; manual or recovery packets for the same day are
    counted separately. Who started the run (the scheduled task or a manual chat) is not
    visible to the app, so origin stays unknown. ``context_read_at`` is Check's first
    jo_morning_context read of the scheduled packet: it separates "never ran" (no read)
    from "ran but nothing arrived", without proving who started the run. Past days are judged with today's
    configuration, so a day before automation was on can read as "not published".
    """
    calendar = "unavailable" if not hours else hours.get("status") or "unavailable"
    result = {"calendar": calendar, "publication": "unknown", "fulfilment": "unknown", "deadline": None,
        "publish_at": None, "packet_id": None, "published_at": None, "briefing_id": None, "available_at": None,
        "submitted_at": None, "import_lag_seconds": None, "late_by_seconds": None, "origin": "unknown",
        "other_briefings": 0, "context_read": "unknown", "context_read_at": None, "notifications": {"chatgpt": "not_observable", "watchdog": None}}
    if config is None:
        result.update(publication="not_expected", fulfilment="not_expected")
        return result
    if calendar == "closed":
        result.update(publication="not_expected", fulfilment="not_expected")
        return result
    if calendar != "open" or actor is None:
        return result
    publish_at, deadline = at(day, config.publish_time), at(day, config.deadline)
    key = operation(config, actor, day)
    packet = session.exec(select(MorningBriefingPacket).where(MorningBriefingPacket.operation_id == key)).first()
    if packet is not None:
        deadline = _frozen_deadline(packet) or deadline
    result.update(deadline=deadline.isoformat(), publish_at=publish_at.isoformat())
    records = session.exec(select(MorningBriefingRecord).join(MorningBriefingPacket).where(MorningBriefingPacket.day == day)
        .order_by(MorningBriefingRecord.created_at, MorningBriefingRecord.id)).all()
    mine = [r for r in records if packet is not None and r.packet_id == packet.id]
    result["other_briefings"] = len(records) - len(mine)
    if packet is None:
        result["publication"] = "pending" if now < publish_at else "missing"
        result["fulfilment"] = "pending" if now < deadline else "missing"
        return result
    result.update(publication="published", packet_id=str(packet.id), published_at=store.timestamp(packet.created_at))
    try:
        read_at = exchange.read_marker(load_binding(config.check_config).market_watch_outbox_dir, actor, day.isoformat(), packet.id)
        result.update(context_read="recorded" if read_at else "not_recorded", context_read_at=read_at)
    except LookupError:
        pass  # No earlier marker: the trace isn't proven live, so absence stays unknown.
    except Exception:
        LOG.warning("Jo morning read marker unreadable")  # Stays unknown, never "not read".
    if not mine:
        result["fulfilment"] = "pending" if now < deadline else "missing"
        return result
    # The first saved record is the delivery; later ones are corrections or retries.
    first = mine[0]
    available = first.created_at.replace(tzinfo=timezone.utc)
    result.update(briefing_id=str(first.id), available_at=available.isoformat(),
        fulfilment="on_time" if available <= deadline else "late",
        late_by_seconds=max(0, int((available - deadline).total_seconds())))
    from app.models import MorningBriefingSubmission
    receipt = session.get(MorningBriefingSubmission, first.id)
    if receipt is not None:
        submitted = receipt.submitted_at.replace(tzinfo=timezone.utc)
        result.update(submitted_at=submitted.isoformat(), import_lag_seconds=max(0, int((available - submitted).total_seconds())))
    return result


def morning_view(session, day, now, briefing_id=None, config=None, calendar=None, actor=None):
    """Saved content only. Dates never fall back to a prior morning's output."""
    records = session.exec(select(MorningBriefingRecord).join(MorningBriefingPacket)
        .where(MorningBriefingPacket.day == day).order_by(MorningBriefingRecord.created_at.desc(), MorningBriefingRecord.id.desc()).limit(100)).all()
    row = session.get(MorningBriefingRecord, briefing_id) if briefing_id else (records[0] if records else None)
    if briefing_id and (row is None or session.get(MorningBriefingPacket, row.packet_id).day != day):
        raise LookupError("Briefing not found for this date")
    packet_row = (session.get(MorningBriefingPacket, row.packet_id) if row else session.exec(select(MorningBriefingPacket)
        .where(MorningBriefingPacket.day == day).order_by(MorningBriefingPacket.created_at.desc(), MorningBriefingPacket.id.desc()).limit(1)).first())
    packet = store.get_packet(session, packet_row.id) if packet_row else None
    if calendar is None:
        from app.engine.chart_calendar import chart_calendar
        calendar = chart_calendar.cached
    hours = calendar(day) if config else None
    deadline = at(day, config.deadline) if config and hours and hours.get("status") == "open" else None
    if packet and not packet["redacted_at"]:
        for item in packet["body"]["evidence"]:
            if item["id"] == "schedule" and packet_row.operation_id.startswith("morning-"):
                try:
                    candidate = datetime.fromisoformat(json.loads(item["text"])["deadline"])
                    if candidate.tzinfo is not None:
                        deadline = candidate
                except (ValueError, TypeError, KeyError):
                    pass
    late = bool(row and deadline and row.created_at.replace(tzinfo=timezone.utc) > deadline)
    stale = bool(packet and not packet["redacted_at"] and now - datetime.fromisoformat(packet["body"]["as_of"]) >= timedelta(hours=4))
    if row and (row.redacted_at or packet_row.redacted_at):
        state = "redacted"
    elif row:
        state = "ready"
    elif not packet and hours and hours.get("status") == "closed":
        state = "closed"
    elif deadline and now >= deadline:
        state = "missing"
    elif packet:
        state = "waiting"
    else:
        state = "unavailable"
    from app.models import MorningBriefingFeedback
    feedback = session.get(MorningBriefingFeedback, row.id) if row else None
    return {"day": day.isoformat(), "state": state, "late": late, "stale": stale,
        "delivery": delivery(session, day, now, config, actor, hours),
        "archived": day != now.astimezone(ET).date(), "deadline": deadline.isoformat() if deadline else None,
        "checked_at": now.isoformat(), "packet": packet, "briefing": store.receipt(row) if row else None,
        "versions": [{"id": str(r.id), "received_at": store.timestamp(r.created_at), "redacted": bool(r.redacted_at)} for r in records],
        "feedback": {"rating": feedback.rating if feedback else None,
            "first_opened_at": store.timestamp(feedback.first_opened_at) if feedback and feedback.first_opened_at else None}}


def watchdog_status(day, path=None, section="jo_morning"):
    """The phone watchdog's record for one day (morning brief, or ``jo_market_reads``), or unknown when unreadable.

    Only the watchdog's own ntfy attempts are known here; any notification ChatGPT sends
    about a Jo task is outside TradeJournal and is never reported as delivered or missing.
    """
    try:
        state = json.loads((path or ALERTS_STATE).read_text()).get(section)
    except (OSError, ValueError, AttributeError):
        return {"state": "unknown", "checked_at": None, "notices": []}
    if not isinstance(state, dict):
        return {"state": "unknown", "checked_at": None, "notices": []}
    notices = state.get("notices")
    notices = notices.get(day.isoformat(), []) if isinstance(notices, dict) else []
    return {"state": "on" if state.get("enabled") else "off", "checked_at": state.get("checked_at"),
        "notices": notices if isinstance(notices, list) else []}
