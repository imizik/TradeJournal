"""A scripted Jo day for the UX sandbox: the real API on a fake clock, fed through Jo's real save paths.

Run only through ``bash scripts/ux_sandbox.sh --jo-day``, which seeds the sandbox database and starts
the frontend. This replaces the sandbox backend with the same app plus a simulation clock and a
``/__sim`` control route. Scripted Jo writes through the same ledgers and outboxes the Check service
uses after sign-in (briefing submission, market-read notice, conditional-plan export and refusal receipt); the app's own
importers, plan monitor and API judge them. The MCP sign-in layer, ChatGPT and real prices are not
involved: prices are invented and phone pushes are recorded, never sent.

    curl -s 127.0.0.1:8098/__sim            # where the day is and what comes next
    curl -s -X POST 127.0.0.1:8098/__sim/next
"""
import argparse
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import sys
import uuid
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
ET = ZoneInfo("America/New_York")


class Clock:
    now = datetime.now(UTC)


class SimDatetime(datetime):
    """``datetime`` whose ``now()`` is the simulation's; patched only into the modules that read the day."""

    @classmethod
    def now(cls, tz=None):
        return Clock.now.astimezone(tz) if tz else Clock.now.astimezone().replace(tzinfo=None)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8098)
    parser.add_argument("--day", default=datetime.now(ET).date().isoformat(), help="ET weekday to simulate (default today)")
    parser.add_argument("--dir", required=True, help="empty sandbox folder for the Check and market-watch files")
    args = parser.parse_args()
    day = datetime.fromisoformat(args.day).date()
    if day.weekday() >= 5:
        raise SystemExit("--day must be a weekday")
    if "ux_sandbox.db" not in os.environ.get("DATABASE_URL", ""):
        raise SystemExit("refusing: this only runs against the UX sandbox database")

    base = Path(args.dir).resolve()
    public, outbox, receipts = base / "public", base / "outbox", base / "receipts"
    for folder in (public, outbox, receipts):
        folder.mkdir(parents=True, exist_ok=False)
    os.environ.update(MARKET_WATCH_STORE=str(base / "wakes.sqlite"), MARKET_WATCH_SNAPSHOTS_DIR=str(public),
                      MARKET_WATCH_OUTBOX_DIR=str(outbox), CONDITIONAL_PLAN_ENABLED="true", STOCK_WATCH_ENABLED="true",
                      MARKET_WATCH_ENABLED="true", LEVEL_ALERTS_AUTOSTART="false")
    profile = "check_" + str(uuid.uuid4())
    (base / "jwks.json").write_text("{}")
    check_path = base / "check.json"
    check_path.write_text(json.dumps({
        "enabled": True, "check_only": True, "provider_feed": "sip", "issuer_url": "https://issuer.invalid/",
        "resource_url": "https://check.invalid/check/mcp", "jwks_url": "https://issuer.invalid/jwks", "jwks_file": str(base / "jwks.json"),
        "client_id": "ux-sandbox", "profiles": [{"subject": "ux-sandbox", "id": profile, "enabled": True}],
        "ledger_file": str(base / "check-ledger.sqlite"), "features_pointer": str(base / "features.json"),
        "jo_briefing_enabled": True, "conditional_plan_enabled": True,
        "market_watch_snapshots_dir": str(public), "market_watch_outbox_dir": str(outbox)}))

    import uvicorn
    from fastapi import APIRouter, HTTPException
    from sqlmodel import Session, select

    import app.main as app_main
    from app import models
    from app.database import engine
    from app.engine import conditional_plans as plans_engine, jo_briefing as briefing_engine, jo_morning
    from app.engine.chart_calendar import chart_calendar
    from app.engine.conditional_plans import PlanMonitor
    from app.engine.market_watch_snapshot import build_snapshot, publish_snapshot
    from app.engine.market_watch_wakes import MarketWatchRunner, MarketWatchWakeStore
    from app.engine.stock_watch import packet
    from app.models import Account, MorningBriefingPacket
    from app.routers import conditional_plans as plans_route, jo_briefing as briefing_route, market_reads as reads_route
    from cloud_mcp_check_ledger import Ledger
    from conditional_plan_common import publish
    from conditional_plan_ledger import PlanLedger, export
    import jo_briefing_exchange as exchange
    from jo_briefing_common import BriefingSave
    from market_watch_common import PROTOCOL, digest, seal
    from market_watch_ledger import MarketWatchLedger, write_read_notice
    import market_watch_schedule as schedule
    from stock_watch_common import stamp, write_once
    from stock_watch_ledger import StockWatchLedger

    def at(clock):
        hour, minute = map(int, clock.split(":"))
        return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ET).astimezone(UTC)

    open_at, close_at = at("09:30"), at("16:00")
    hours = lambda d: {"status": "open", "open": 570, "close": 960} if d == day else None  # noqa: E731

    # The views read "now" and the exchange calendar here; everything else takes the clock explicitly.
    for module in (briefing_route, briefing_engine, jo_morning, models):  # models: records' created_at
        module.datetime = SimDatetime
    reads_route._now = plans_route._now = lambda: Clock.now
    reads_route._hours = hours
    reads_route._receipts = lambda: receipts
    # The phone watchdog (deploy/alerts.py) isn't running here; the 12:50 step writes the notice it would record.
    jo_morning.ALERTS_STATE = base / "alerts-state.json"
    chart_calendar.hours = chart_calendar.cached = hours
    plans_engine.datetime = SimDatetime

    with Session(engine) as session:
        account = next((a for a in session.exec(select(Account)).all() if (a.broker or "").lower() != "webull"), None)
    if account is None:
        raise SystemExit("the sandbox has no non-Webull account to brief")
    config = jo_morning.MorningConfig(enabled=True, check_config=str(check_path), account_ids=[account.id])
    jo_morning.load_config = lambda: config
    briefing_route.load_config = lambda: config

    def market(symbols, cutoff):
        rows = [dict(id=f"market-{s}", kind="fact", text=f"{s}: invented premarket trade", source="Simulation",
                     observed_at=cutoff - timedelta(minutes=2), retrieved_at=cutoff) for s in ("SPY", "MU")]
        return rows, ["Simulated prices, not market data"]

    morning = jo_morning.MorningRunner(engine, lambda: config, hours, market, lambda *a, **k: ([], ["Simulation: no backdrop"]))
    pushes = []
    store = MarketWatchWakeStore(base / "wakes.sqlite")
    reads = MarketWatchRunner(store, public, outbox_dir=outbox, clock=lambda: Clock.now, bounds=lambda d: (open_at, close_at),
                              push=lambda title, body: pushes.append({"at": stamp(Clock.now), "title": title, "body": body}) or "sim")
    ledger = Ledger(base / "check-ledger.sqlite")
    watch_ledger, plan_ledger, stock_ledger = MarketWatchLedger(ledger), PlanLedger(ledger), StockWatchLedger(ledger)
    monitor = PlanMonitor(store, public, outbox, clock=lambda: Clock.now,
                          push=lambda title, body: pushes.append({"at": stamp(Clock.now), "title": title, "body": body}) or "sim")
    state = {"step": -1, "last_read": None, "plan": None}

    def snapshot():
        minutes = max(0, int((min(Clock.now, close_at) - open_at).total_seconds() // 60))
        closes = [770 + (i % 7) * 0.1 for i in range(minutes)]
        rows = lambda scale: [{"t": (open_at + timedelta(minutes=i)).isoformat().replace("+00:00", "Z"), "o": c * scale,  # noqa: E731
                               "h": c * scale + .05, "l": c * scale - .05, "c": c * scale, "v": 1000} for i, c in enumerate(closes)]
        when = stamp(Clock.now)
        return build_snapshot(Clock.now, protocol=PROTOCOL, bars_reader=lambda *_: {"SPY": rows(1), "QQQ": rows(.94)}, daily_reader=lambda *_: {},
            vix_reader=lambda: {"observed_at": Clock.now - timedelta(minutes=5), "value": 17.0, "change_pct": 1.0},
            calendar_reader=lambda d, a: {"status": "fresh", "reason": None, "source": "official_calendar", "observed_at": when, "retrieved_at": when,
                "age_seconds": 0, "coverage_start": "2026-01-01", "coverage_end": "2027-12-31", "calendar_version": "simulation", "events": [],
                "source_sha256": digest({"coverage_start": "2026-01-01", "coverage_end": "2027-12-31", "calendar_version": "simulation", "events": []})},
            news_reader=lambda start, end: {"status": "missing", "reason": "no_published_headline_cache", "source": "Alpaca Benzinga",
                "observed_at": None, "retrieved_at": end.isoformat().replace("+00:00", "Z"), "age_seconds": None, "source_sha256": digest([]),
                "query_symbols": ["SPY", "QQQ"], "window_start": start.isoformat().replace("+00:00", "Z"),
                "window_end": end.isoformat().replace("+00:00", "Z"), "coverage": "unpublished", "errors": [], "items": []},
            bounds_reader=lambda d: (open_at, close_at))

    def packet_receipt(slot, snap):
        prep = f"{int(slot[:2]):02d}-{int(slot[3:]) - 1:02d}"
        for phase, status in (("started", "started"), ("published", "published")):
            schedule._write_immutable(receipts / day.isoformat() / prep / f"attempt-01-{phase}.json", {
                "schema_version": 1, "session_date": day.isoformat(), "slot": prep, "purpose": "planned_jo_wake_packet",
                "scheduled_read_slot": None, "attempt": 1, "recorded_at": stamp(Clock.now), "phase": phase, "status": status,
                **({"snapshot_id": snap["snapshot_id"], "quality_flags": []} if phase == "published" else {})})

    def read(operation, view, main, alternative, invalidation, change, intent="none"):
        snap = snapshot()
        publish_snapshot(public, snap)
        served = watch_ledger.serve(profile, snap, lambda: Clock.now)
        receipt = watch_ledger.submit(profile, {"operation_id": operation, "input_id": served["input_id"], "view": view,
            "main": {"text": main, "supporting_refs": ["/indices/SPY/bar_1m/close"], "contradicting_refs": []},
            "alternative": {"text": alternative, "supporting_refs": [], "contradicting_refs": []},
            "invalidation": {"text": invalidation, "evidence_refs": ["/indices/SPY/vwap"]}, "change_summary": change,
            "forecasts": [{"horizon": h, "predicate": "spy_return_lt_zero", "probability": None,
                           "abstention_reason": "No defensible directional forecast."} for h in ("30m", "60m", "close")],
            "message_intent": intent, "prompt_version": "ux-simulation", "previous_read_id": state["last_read"]}, lambda: Clock.now)
        state["last_read"] = receipt["read_id"]
        write_read_notice(outbox, watch_ledger.read_notice(profile, receipt["read_id"]))
        return snap

    def ready():
        publish(public, "conditional-plan-readiness.json", seal({"format": "conditional-plan-readiness-v1", "enabled": True,
            "session_date": day.isoformat(), "symbols": ["SPY", "QQQ", "MU", "NBIS", "AMD"], "selection_revision": 1,
            "session_open_at": stamp(open_at), "session_close_at": stamp(close_at), "created_at": stamp(Clock.now)}))

    def mu_price(minute):
        """Invented MU closes: under 140 until 10:52, two closes above it, then holding."""
        et = minute.astimezone(ET).strftime("%H:%M")
        return 139.4 + (minute - open_at).total_seconds() / 60 * .003 if et < "10:52" else 140.3 if et == "10:52" else 140.6 if et == "10:53" else 141.0

    def mu_minutes():
        """Every completed minute so far: the monitor stops on a missing minute, as it should."""
        end = Clock.now.replace(second=0, microsecond=0)
        bars, minute = [], open_at
        while minute + timedelta(minutes=1) <= end:
            close = round(mu_price(minute), 2)
            bars.append({"time": minute.timestamp(), "end_time": minute.timestamp() + 60, "open": close, "high": close + .1,
                         "low": close - .1, "close": close, "volume": 5000.0})
            minute += timedelta(minutes=1)
        return bars

    def watch_pass():
        ready()
        if state["plan"] is None:
            return
        scanner = type("Scanner", (), {"_pass_minutes": {"MU": (mu_minutes(), Clock.now.timestamp())}})()
        session_hours = type("Hours", (), {"open_at": open_at.timestamp(), "close_at": close_at.timestamp()})()
        # The monitor imports Jo's exported plan itself (validation, store, cancellations), as in production.
        for plan in monitor.ingest():
            monitor.observe(plan, scanner, ("SPY", "QQQ", "MU", "NBIS", "AMD"), session_hours, True)
            monitor.deliver(plan, True)
            monitor.project(plan, True)

    def publish_packet():
        assert morning.run_once(Clock.now)["status"] == "published"

    def save_briefing():
        with Session(engine) as session:
            p = session.exec(select(MorningBriefingPacket)).first()
            ids = {e["id"] for e in briefing_engine.get_packet(session, p.id)["body"]["evidence"]}
        cite = lambda *want: [i for i in want if i in ids] or sorted(ids)[:1]  # noqa: E731
        body = BriefingSave(operation_id="sim-brief", packet_id=p.id, author="Jo", prompt_version="ux-simulation",
            summary="Two things before new risk: MU is pressing 140 into earnings week, and SPY is flat premarket.",
            summary_evidence_ids=cite("market-MU", "market-SPY"),
            items=[{"symbol": "MU", "what_matters": "MU is pressing 140; a clean break with volume is the setup you asked about yesterday.",
                    "why_personal": "It is on your watchlist and you traded it last week.", "what_changed": "Up 2% premarket.",
                    "contrary_evidence": "Premarket volume is thin.", "watch_out": "Don't chase the open; let 140 hold first.",
                    "evidence_ids": cite("market-MU")},
                   {"symbol": "SPY", "what_matters": "Flat premarket; the opening range will set the tone.", "why_personal": "Your index read.",
                    "what_changed": "Nothing material overnight.", "contrary_evidence": "VIX slightly higher.", "watch_out": "No macro event today.",
                    "evidence_ids": cite("market-SPY")}],
            limitations=["Simulated prices"])
        exchange.submit(str(public), str(outbox), profile, p.id, "briefing", body.model_dump(mode="json"), Clock.now)
        morning.run_once(Clock.now + timedelta(seconds=9))

    def save_watch():
        alert = stock_alert("MU", 139.6)
        ready()
        plan = plan_ledger.create(profile, {"operation_id": "sim-mu-watch", "source_kind": "stock_alert", "source_id": alert["alert_id"],
            "direction": "long", "trigger_price": 140.0, "invalidation_price": 137.5, "confirm_bars": 2,
            "expires_at": stamp(Clock.now + timedelta(hours=4)),
            "rationale": "You asked me to track MU for a breakout: two 1-minute closes above 140 alert you; one close below 137.50 cancels."},
            public, lambda: Clock.now)
        export(outbox, plan)
        state["plan"] = plan
        watch_pass()

    def stock_alert(symbol, last):
        minutes = [{"time": (Clock.now - timedelta(minutes=30 - i)).timestamp(), "end_time": (Clock.now - timedelta(minutes=29 - i)).timestamp(),
                    "open": last - .9 + i * .03, "high": last - .7 + i * .03, "low": last - 1.1 + i * .03, "close": last - .8 + i * .03,
                    "volume": 5000.0} for i in range(30)]
        alert = packet(symbol, "move", "up", minutes, Clock.now, Clock.now, {"symbols": [symbol], "revision": 1}, {"kind": "session_rebound"},
                       alert_id="sta_" + str(uuid.uuid4()))
        alert = seal({k: v for k, v in alert.items() if k != "content_sha256"})
        stock_ledger.serve(profile, alert, Clock.now)
        write_once(public, f"stock-{alert['alert_id']}.json", alert)
        return alert

    def refused_watch():
        try:
            plan_ledger.create(profile, {"operation_id": "sim-tsla", "source_kind": "stock_alert", "source_id": stock_alert("TSLA", 250)["alert_id"],
                "direction": "long", "trigger_price": 252.0, "invalidation_price": 245.0, "confirm_bars": 2,
                "expires_at": stamp(Clock.now + timedelta(hours=2)), "rationale": "TSLA breakout"}, public, lambda: Clock.now)
        except Exception as error:  # Jo relays this in chat; the receipt goes to the app as the Check tool does
            if getattr(error, "refusal", None):
                export(outbox, error.refusal)
            return f"refused: {error}"
        return "unexpectedly accepted"

    def tick():
        Clock.now += timedelta(minutes=1)

    def ingest():
        reads.ingest_notices(Clock.now)

    def scheduled(slot, view, main, alt, inval, change, intent="none"):
        def run():
            snap = read(f"mw-scheduled-v1:{day.isoformat()}:{slot}", view, main, alt, inval, change, intent)
            packet_receipt(slot, snap)
            ingest()
            reads.deliver_messages(Clock.now)  # Jo's "update" reads go to the phone (recorded here, never sent)
        return run

    def watchdog(notices=()):
        jo_morning.ALERTS_STATE.write_text(json.dumps({section: {"enabled": True, "checked_at": stamp(Clock.now),
            "notices": {day.isoformat(): list(notices) if section == "jo_market_reads" else []}} for section in ("jo_morning", "jo_market_reads")}))

    def watchdog_missing(slot, label):
        watchdog([{"kind": slot.replace(":", ""), "title": f"Jo's {label} market read is missing", "recovered": False,
                   "outcome": "sent", "at": stamp(Clock.now), "attempts": 1}])

    steps = [
        ("08:30", "Before the briefing: nothing from Jo yet; the briefing is due by 9:15.", lambda: None),
        ("08:46", "8:45 morning packet published for Jo.", publish_packet),
        ("08:56", "Jo saves the morning briefing (MU and SPY).", save_briefing),
        ("09:52", "Jo's 9:50 scheduled market read arrives on time.", scheduled("09:50", "mixed",
            "SPY is holding its opening range around 770; no clean break yet.", "A drop under 769.5 would turn the tape weak.",
            "Wrong if SPY loses 769.5 with volume.", "First read of the day.")),
        ("10:20", "You ask Jo to watch MU; Jo saves a price watch above 140. Jo's attempt to watch TSLA is refused (not a scanner ticker).",
            lambda: (save_watch(), state.update(refusal=refused_watch()))),
        ("10:45", "Jo sends an extra unscheduled read correcting its 9:50 view.", lambda: (read("sim-extra-1045", "up",
            "Correction: SPY reclaimed VWAP and its opening high; the weak-tape worry no longer holds.", "This could still stall at 771.",
            "Weakens if SPY loses VWAP again.", "Corrects the 9:50 read."), ingest(), watch_pass())),
        ("10:55", "MU closed above 140 at 10:52 and 10:53: the watch triggered and a phone alert went out.", watch_pass),
        ("11:03", "Jo's 11:00 read arrives on time and Jo flags it for your phone (a market-read message).", scheduled("11:00", "up", "Breadth improving; MU and semis leading.",
            "A fade back under VWAP would undo it.", "Wrong if SPY closes back under 770.", "Upgraded from mixed.", "update")),
        ("12:50", "Jo's 12:30 read never arrived: it shows as missing and the phone watchdog's notice is recorded.",
            lambda: (watch_pass(), ingest(), watchdog_missing("12:30", "12:30 PM"))),
        ("14:22", "Jo's 2:00 read arrives 22 minutes late.", scheduled("14:00", "mixed", "Afternoon chop; MU holding above 140.",
            "A late-day flush is possible into the close.", "Wrong if SPY breaks 769.", "Momentum faded since 11:00.")),
        ("16:05", "After the close: the day is a record; nothing is upcoming.", lambda: (watch_pass(), ingest())),
    ]

    def where():
        current = steps[state["step"]] if state["step"] >= 0 else None
        nxt = steps[state["step"] + 1] if state["step"] + 1 < len(steps) else None
        return {"day": day.isoformat(), "sim_time_et": Clock.now.astimezone(ET).strftime("%H:%M"), "step": state["step"],
                "did": current[1] if current else None, "next": f"{nxt[0]} ET: {nxt[1]}" if nxt else None,
                "phone_pushes": pushes, "jo_refusal": state.get("refusal"), "steps": len(steps)}

    control = APIRouter()

    @control.get("")
    def sim_status():
        return where()

    @control.post("/next")
    def sim_next():
        if state["step"] + 1 >= len(steps):
            raise HTTPException(409, "The simulated day is over")
        state["step"] += 1
        clock, _, run = steps[state["step"]]
        # The real monitor checks every minute; a saved watch is passed through each minute between steps.
        while state["plan"] is not None and Clock.now + timedelta(minutes=1) < at(clock):
            tick()
            watch_pass()
        Clock.now = at(clock)
        run()
        return where()

    Clock.now = at("08:00")
    watchdog()
    # The simulation's own runners replace the API's background loops, which would use the real clock.
    async def runner_off(app_):
        app_.state.market_watch = reads
        return None

    async def morning_off(app_):
        app_.state.jo_morning = morning
        return None

    app_main._maybe_start_market_watch = runner_off
    app_main._maybe_start_jo_morning = morning_off
    app_main.app.include_router(control, prefix="/__sim")
    uvicorn.run(app_main.app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
