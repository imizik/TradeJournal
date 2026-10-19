"""Opt-in morning publication/import inside the existing API process; no inference.

Read approved local records only. Existing Check OAuth and file permissions
remain the boundary. No provider research, notifications or Shadow mutation.
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
from app.models import Account, ChartSettingsRecord, Fill, Trade, TradeFill, TradeCapture, MorningBriefingPacket, MorningBriefingRecord
from cloud_mcp_check_common import read_config
from jo_briefing_common import PacketSave, Strict
import jo_briefing_exchange as exchange
from jo_briefing_owner import binding, publish, import_submission

ET = ZoneInfo("America/New_York")
LOG = logging.getLogger(__name__)


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


def collect(session, config, actor, now):
    day = now.astimezone(ET).date()
    accounts = session.exec(select(Account).where(Account.id.in_(config.account_ids))).all()
    if len(accounts) != len(config.account_ids) or any((a.broker or "").lower() == "webull" for a in accounts):
        raise ValueError("Approved account scope missing or excluded")
    evidence, gaps = [], ["Journal import freshness is not verified by this packet; positions reflect saved fills.",
        "No live quotes, news or option risk metrics were fetched. Saved levels may need split/basis review."]

    def add(key, kind, text, source, observed=None):
        if len(evidence) >= 80:
            if "Evidence limited to 80 items." not in gaps:
                gaps.append("Evidence limited to 80 items.")
            return
        if len(text) > 4000:
            gaps.append(f"{key}: text truncated to 4000 characters.")
        evidence.append(dict(id=key, kind=kind, text=text[:4000], source=source,
            observed_at=observed, retrieved_at=now))

    add("schedule", "fact", exchange.canonical({"deadline": at(day, config.deadline).isoformat()}), "Morning publication schedule")
    trades = session.exec(select(Trade).where(Trade.account_id.in_(config.account_ids), Trade.status == "open",
        Trade.opened_at <= now.astimezone(ET).replace(tzinfo=None))
        .order_by(Trade.opened_at.desc(), Trade.id).limit(21)).all()
    if len(trades) > 20:
        gaps.append("Open positions limited to the 20 most recently opened trades.")
    for index, trade in enumerate(trades[:20]):
        fills = session.exec(select(Fill).join(TradeFill, TradeFill.fill_id == Fill.id).where(
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
        add(f"position-{index + 1}", "fact", exchange.canonical(detail), "Saved journal fills; FIFO remaining lots")
    if not trades:
        add("positions", "fact", "No open journal trades in the approved account scope.", "Saved journal query")
    settings = session.get(ChartSettingsRecord, "default")
    try:
        data = json.loads(settings.data_json) if settings else {}
        watched = data.get("watchlist")
        if not isinstance(watched, list) or any(not isinstance(s, str) or not re.fullmatch(r"[A-Z][A-Z0-9./-]{0,14}", s) for s in watched):
            raise ValueError("No valid saved watchlist")
        add("watchlist", "fact", "Saved Charts watchlist: " + (", ".join(watched[:30]) or "empty"), "Charts saved workspace",
            settings.updated_at.replace(tzinfo=timezone.utc))
        if len(watched) > 30:
            gaps.append("Watchlist limited to 30 saved symbols.")
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
    captures = session.exec(select(TradeCapture).where(TradeCapture.account_id.in_(config.account_ids),
        TradeCapture.received_at >= (now - timedelta(days=30)).replace(tzinfo=None), TradeCapture.received_at <= now.replace(tzinfo=None))
        .order_by(TradeCapture.received_at.desc(), TradeCapture.id).limit(11)).all()
    for i, row in enumerate(captures[:10]):
        text = " | ".join(str(x) for x in (row.underlying, row.side, row.setup_label, row.wording, row.note) if x)
        add(f"capture-{i + 1}", "belief", text, "Owner capture; not an activated plan", row.received_at.replace(tzinfo=timezone.utc))
    if len(captures) > 10:
        gaps.append("Captures limited to the latest 10 in 30 days; images/audio/transcripts are excluded.")
    memories = store.memories(session, "active", None, 31)
    for i, memory in enumerate(memories[:30]):
        add(f"memory-{i + 1}", "belief", memory["body"]["original_text"], "Explicit owner memory; not a market fact",
            datetime.fromisoformat(memory["received_at"]))
    if len(memories) > 30:
        gaps.append("Active memories limited to the latest 30; packet retains exact revision IDs.")
    previous = session.exec(select(MorningBriefingRecord).join(MorningBriefingPacket).where(
        MorningBriefingPacket.day < day, MorningBriefingRecord.redacted_at.is_(None), MorningBriefingPacket.redacted_at.is_(None))
        .order_by(MorningBriefingPacket.day.desc(), MorningBriefingRecord.created_at.desc()).limit(1)).first()
    if previous:
        add("prior-brief", "belief", json.loads(previous.body_json)["summary"], "Prior saved briefing; compare dates, not current facts",
            previous.created_at.replace(tzinfo=timezone.utc))
    else:
        gaps.append("No prior saved briefing available for comparison.")
    return PacketSave(operation_id=operation(config, actor, day), day=day, as_of=now,
        scope=f"{len(accounts)} explicitly approved accounts; saved journal, Charts workspace and personal memories. Deadline {at(day, config.deadline).isoformat()}",
        evidence=evidence, gaps=gaps[:30], memory_revision_ids=[m["id"] for m in memories[:30]])


class MorningRunner:
    def __init__(self, engine, config_loader=load_config, calendar=None):
        self.engine, self.config_loader = engine, config_loader
        if calendar is None:
            from app.engine.chart_calendar import chart_calendar
            calendar = chart_calendar.hours
        self.calendar = calendar
        self.last_pass = None
        self.last_error = None
        self.scan_cursor = ""

    def run_once(self, now=None):
        now = now or datetime.now(timezone.utc)
        config = self.config_loader()
        if config is None or not config.enabled:
            return {"status": "disabled"}
        check = read_config(config.check_config)
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
                    saved = store.save_packet(session, collect(session, config, actor, now))
                    row = session.get(MorningBriefingPacket, UUID(saved["id"]))
                # Use the frozen cutoff for repeat publication, never extend expiry on restart.
                published = datetime.fromisoformat(json.loads(row.body_json)["as_of"])
                publish(session, check, row.id, published)
                exchange.write(check.market_watch_snapshots_dir, f"jo-morning-{actor}-{day.isoformat()}.json",
                    {"packet_id": str(row.id), "profile_id": actor, "day": day.isoformat()})
                state = "published"
        self.last_pass, self.last_error = now.isoformat(), "Some submissions could not be imported" if errors else None
        return {"status": state, "imported": imported, "errors": errors}


def morning_view(session, day, now, briefing_id=None, config=None, calendar=None):
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
        "archived": day != now.astimezone(ET).date(), "deadline": deadline.isoformat() if deadline else None,
        "checked_at": now.isoformat(), "packet": packet, "briefing": store.receipt(row) if row else None,
        "versions": [{"id": str(r.id), "received_at": store.timestamp(r.created_at), "redacted": bool(r.redacted_at)} for r in records],
        "feedback": {"rating": feedback.rating if feedback else None,
            "first_opened_at": store.timestamp(feedback.first_opened_at) if feedback and feedback.first_opened_at else None}}
