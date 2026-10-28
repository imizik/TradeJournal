"""Automatic packet → tool → import → owner view, all against disposable data."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.engine import jo_briefing as store
from app.engine.jo_morning import MorningConfig, MorningRunner, collect, morning_view, load_config
from app.models import Account, ChartSettingsRecord, Fill, Trade, TradeFill, MorningBriefingPacket, MorningBriefingRecord
from cloud_mcp_check_common import read_config
from jo_briefing_common import BriefingSave
import jo_briefing_exchange as exchange
from tests.test_cloud_mcp_check import harness, signing_key, call  # noqa: F401
from tests.test_jo_briefing import client, engine, packet, briefing  # noqa: F401

NOW = datetime(2026, 10, 19, 12, 45, tzinfo=timezone.utc)  # 08:45 ET


def test_runner_logs_failure_class_without_private_exception_text(monkeypatch, caplog):
    from types import SimpleNamespace
    from app import main
    from app.engine import jo_morning

    def fail():
        raise PermissionError('private-sentinel /private/config.json')
    runner = SimpleNamespace(run_once=fail, last_error=None)
    app = SimpleNamespace(state=SimpleNamespace())
    monkeypatch.setenv('JO_MORNING_CONFIG', '/unused-fixture')
    monkeypatch.delenv('TJ_DOT_TRIAL_ENABLED', raising=False)
    monkeypatch.setattr(jo_morning, 'MorningRunner', lambda db_engine: runner)

    async def invoke(function):
        function()

    async def stop_after_pass(seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(main.asyncio, 'to_thread', invoke)
    monkeypatch.setattr(main.asyncio, 'sleep', stop_after_pass)

    async def run():
        task = await main._maybe_start_jo_morning(app)
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert runner.last_error == 'Morning briefing pass unavailable (PermissionError)'
    assert runner.last_error in caplog.text
    assert 'private-sentinel' not in caplog.text and '/private/' not in caplog.text


@pytest.fixture
def morning(harness, tmp_path, monkeypatch):  # noqa: F811
    from app.engine import alpaca
    monkeypatch.setattr(alpaca, "ALPACA_API_KEY", "")
    monkeypatch.setattr(alpaca, "ALPACA_API_SECRET", "")
    snapshots, outbox = tmp_path / "snapshots", tmp_path / "outbox"
    snapshots.mkdir()
    outbox.mkdir()
    harness.configure(jo_briefing_enabled=True, market_watch_snapshots_dir=str(snapshots), market_watch_outbox_dir=str(outbox))
    db = create_engine("sqlite:///" + str(tmp_path / "morning.sqlite"))
    SQLModel.metadata.create_all(db)
    with Session(db) as session:
        account = Account(name="Private name", type="roth_ira", last4="5511")
        other = Account(name="Unapproved", type="individual", last4="8822")
        session.add_all([account, other])
        session.commit()
        config = MorningConfig(enabled=True, check_config=str(harness.config_path), account_ids=[account.id])
        trade = Trade(account_id=account.id, ticker="SPY", instrument_type="stock", contracts=10,
            avg_entry_premium=100, total_premium_paid=1000, opened_at=NOW.replace(tzinfo=None) - timedelta(days=1))
        excluded = Trade(account_id=other.id, ticker="SECRET", instrument_type="stock", contracts=500,
            avg_entry_premium=100, total_premium_paid=50000, opened_at=trade.opened_at)
        session.add_all([trade, excluded])
        session.commit()
        for n, side, qty, price in [(1, "buy", 4, 90), (2, "buy", 6, 110), (3, "sell", 5, 120)]:
            fill = Fill(account_id=account.id, ticker="SPY", instrument_type="stock", side=side,
                contracts=qty, price=price, executed_at=trade.opened_at + timedelta(minutes=n), raw_email_id=f"secret-email-{n}")
            session.add(fill)
            session.commit()
            session.add(TradeFill(trade_id=trade.id, fill_id=fill.id, role="entry" if side == "buy" else "exit"))
        session.add(ChartSettingsRecord(name="default", data_json=json.dumps({"watchlist": ["SPY", "MU"],
            "levels": {"SPY": [{"price": 99, "label": "My level"}]}}), updated_at=(NOW-timedelta(days=1)).replace(tzinfo=None)))
        session.commit()
    yield harness, db, config
    db.dispose()


def test_automatic_once_per_session_restart_tool_import_and_disabled(morning):
    h, db, config = morning
    check = read_config(h.config_path)
    def hours(day):
        return {"status": "open", "open": 570, "close": 960}
    reads = []
    def market(symbols, cutoff, **kwargs):
        reads.append((symbols, cutoff))
        return [dict(id="market-SPY", kind="fact", text="SPY: invented recent trade $100", source="Fixture",
            observed_at=NOW-timedelta(seconds=10), retrieved_at=NOW+timedelta(seconds=2))], ["Fixture market coverage"]
    runner = MorningRunner(db, lambda: config, hours, market)
    assert runner.run_once(NOW - timedelta(minutes=1))["status"] == "outside_publication_window"
    assert runner.run_once(NOW)["status"] == "published"
    first_files = {p.name: p.read_bytes() for p in Path(check.market_watch_snapshots_dir).iterdir()}
    restarted = MorningRunner(db, lambda: config, hours, market)
    assert restarted.run_once(NOW + timedelta(minutes=10))["status"] == "published"
    assert first_files == {p.name: p.read_bytes() for p in Path(check.market_watch_snapshots_dir).iterdir()}
    assert len(reads) == 1 and reads[0][0] == ["SPY", "SPY", "MU"]
    assert "SECRET" not in str(reads)
    with Session(db) as session:
        packets = session.exec(select(MorningBriefingPacket)).all()
        assert len(packets) == 1
        saved = store.get_packet(session, packets[0].id)
        encoded = json.dumps(saved)
        for secret in ("SECRET", "5511", "8822", "secret-email", "Private name", str(config.account_ids[0])):
            assert secret not in encoded
        evidence = {e["id"]: e for e in saved["body"]["evidence"]}
        assert evidence["market-SPY"]["observed_at"] != evidence["market-SPY"]["retrieved_at"]
        assert datetime.fromisoformat(saved["body"]["as_of"]) == NOW+timedelta(seconds=2)
        position = json.loads(evidence["position-1"]["text"])
        assert position["remaining_quantity"] == 5 and position["remaining_average_cost"] == 110
        assert "SPY, MU" in evidence["watchlist"]["text"]
        assert evidence["levels-1"]["kind"] == "belief"
    with TestClient(h.server(now=NOW + timedelta(minutes=11)).streamable_http_app()) as browser:
        token = h.token(scope="check:read jo:read jo:submit")
        response = call(browser, "jo_morning_context", {}, token)
        assert not response.get("isError"), response
        published = response["structuredContent"]
        assert published["packet"]["id"] == saved["id"]
        body = BriefingSave(operation_id="auto-brief", packet_id=saved["id"], author="Jo", prompt_version="test",
            summary="Saved watchlist only", summary_evidence_ids=["watchlist"], items=[], limitations=["No quotes"])
        response = call(browser, "jo_briefing_submit", {"briefing": body.model_dump(mode="json")}, token)
        assert response["structuredContent"]["status"] == "pending_import"
        assert restarted.run_once(NOW + timedelta(minutes=12))["imported"] == 1
        assert call(browser, "jo_receipt", {"operation_id": "auto-brief"}, token)["structuredContent"]["status"] == "saved"
    assert restarted.run_once(NOW + timedelta(minutes=13))["imported"] == 0
    with Session(db) as session:
        assert len(session.exec(select(MorningBriefingRecord)).all()) == 1
        view = morning_view(session, NOW.date(), NOW + timedelta(hours=5), config=config)
        assert view["state"] == "ready" and view["stale"]
        assert morning_view(session, NOW.date()+timedelta(days=1), NOW + timedelta(days=1), config=config)["briefing"] is None
    config.enabled = False
    assert MorningRunner(db, lambda: None, hours).run_once(NOW)["status"] == "disabled"


def test_closed_missing_calendar_invalid_scope_and_actual_watchlist(morning):
    h, db, config = morning
    for hours, expected in [(None, "calendar_unavailable"), ({"status": "closed"}, "closed")]:
        assert MorningRunner(db, lambda: config, lambda day: hours).run_once(NOW)["status"] == expected
    with Session(db) as session:
        config.account_ids = [uuid4()]
        with pytest.raises(ValueError, match="scope"):
            collect(session, config, read_config(h.config_path).profiles[0].id, NOW)
    assert not list(Path(read_config(h.config_path).market_watch_snapshots_dir).iterdir())


def test_import_after_publication_window_and_bad_file_does_not_stop_publish(morning):
    h, db, config = morning
    check = read_config(h.config_path)
    (Path(check.market_watch_outbox_dir) / ("jo-request-" + "0"*64 + ".json")).write_text("invalid")
    runner = MorningRunner(db, lambda: config, lambda day: {"status": "open", "open": 570}, market_reader=None)
    outcome = runner.run_once(NOW)
    assert outcome["status"] == "published" and outcome["errors"] == 1
    with Session(db) as session:
        p = session.exec(select(MorningBriefingPacket)).one()
        body = BriefingSave(operation_id="late", packet_id=p.id, author="Jo", prompt_version="test", summary="No evidence",
            summary_evidence_ids=[], items=[], limitations=["Unavailable"])
        exchange.submit(check.market_watch_snapshots_dir, check.market_watch_outbox_dir, check.profiles[0].id,
            p.id, "briefing", body.model_dump(mode="json"), NOW + timedelta(minutes=35))
    assert runner.run_once(NOW + timedelta(hours=2))["imported"] == 1
    with Session(db) as session:
        view = morning_view(session, NOW.date(), NOW + timedelta(hours=2), config=config)
        assert view["late"] and view["state"] == "ready"


def test_owner_feedback_read_view_redaction_and_date_mismatch(client):  # noqa: F811
    p = client.post("/jo/packets", json=packet()).json()
    b = client.post("/jo/briefings", json=briefing(p["id"])).json()
    url = f"/jo/briefings/{b['id']}/feedback"
    first = client.post(url, json={"opened": True}).json()
    assert first["first_opened_at"]
    assert client.post(url, json={"opened": True, "rating": "useful"}).json()["first_opened_at"] == first["first_opened_at"]
    assert client.post(url, json={"rating": "meh"}).json()["rating"] == "meh"
    assert client.post(url, json={"rating": "other"}).status_code == 422
    view = client.get("/jo/morning?day=2026-10-01").json()
    assert view["briefing"]["id"] == b["id"] and view["feedback"]["rating"] == "meh"
    assert client.get(f"/jo/morning?day=2026-10-02&briefing_id={b['id']}").status_code == 404
    client.post(f"/jo/briefings/{b['id']}/redact")
    assert client.get("/jo/morning?day=2026-10-01").json()["state"] == "redacted"


def test_config_off_by_default_and_trial_refusal(monkeypatch):
    monkeypatch.delenv("JO_MORNING_CONFIG", raising=False)
    assert load_config() is None
    monkeypatch.setenv("JO_MORNING_CONFIG", "/nonexistent")
    monkeypatch.setenv("TJ_DOT_TRIAL_ENABLED", "true")
    assert load_config() is None


def test_empty_view_distinguishes_closed_unknown_and_missed_session(morning):
    _, db, config = morning
    with Session(db) as session:
        now = NOW + timedelta(hours=2)
        assert morning_view(session, NOW.date(), now, config=config, calendar=lambda day: None)["state"] == "unavailable"
        assert morning_view(session, NOW.date(), now, config=config, calendar=lambda day: {"status": "closed"})["state"] == "closed"
        assert morning_view(session, NOW.date(), now, config=config, calendar=lambda day: {"status": "open"})["state"] == "missing"


def test_feedback_migration_roundtrip_preserves_briefing_tables(tmp_path):
    from sqlalchemy import inspect
    from tests.test_schema_migrations import _alembic
    path = tmp_path / "feedback-migration.sqlite"
    _alembic(path, "upgrade", "head")
    db = create_engine(f"sqlite:///{path}")
    assert "morning_briefing_feedback" in inspect(db).get_table_names()
    _alembic(path, "downgrade", "c9e5a1b3d7f2")
    tables = inspect(db).get_table_names()
    assert "morning_briefing_feedback" not in tables
    assert "morning_briefing_record" in tables and "morning_briefing_packet" in tables
    _alembic(path, "upgrade", "head")
    assert "morning_briefing_feedback" in inspect(db).get_table_names()
    db.dispose()


def test_prior_brief_requires_same_accounts_and_check_profile(morning):
    from app.engine.jo_morning import operation
    from jo_briefing_common import PacketSave
    h, db, config = morning
    actor = read_config(h.config_path).profiles[0].id
    prior_day = NOW.date() - timedelta(days=1)
    with Session(db) as session:
        old = store.save_packet(session, PacketSave(operation_id=operation(config, actor, prior_day),
            day=prior_day, as_of=NOW-timedelta(days=1), scope="original approved scope", evidence=[], gaps=["Fixture"]))
        store.save_briefing(session, BriefingSave(operation_id="prior", packet_id=old["id"], author="Jo",
            prompt_version="test", summary="Prior private position", summary_evidence_ids=[], items=[], limitations=["Fixture"]))
        now = datetime.now(timezone.utc)
        assert any(e.id == "prior-brief" for e in collect(session, config, actor, now).evidence)
        changed_actor = "check_" + str(uuid4())
        assert all(e.id != "prior-brief" for e in collect(session, config, changed_actor, now).evidence)
        other = session.exec(select(Account).where(Account.id != config.account_ids[0])).one()
        config.account_ids = [other.id]
        result = collect(session, config, actor, now)
        assert all(e.id != "prior-brief" for e in result.evidence)
        assert any("No matching account-scope/profile" in gap for gap in result.gaps)


def test_large_unicode_memories_fit_packet_and_published_context(morning):
    from jo_briefing_common import MemorySave
    from jo_briefing_owner import publish
    h, db, config = morning
    check = read_config(h.config_path)
    with Session(db) as session:
        for n in range(30):
            store.save_memory(session, MemorySave(operation_id=f"large-{n}", kind="preference", original_text="界"*4000,
                interpretation="界"*4000, source_reference="界"*4000, source="owner_statement", status="active", owner_confirmed=True))
        now = datetime.now(timezone.utc)
        body = collect(session, config, check.profiles[0].id, now)
        assert len(body.memory_revision_ids) < 30
        assert len([e for e in body.evidence if e.id.startswith("memory-")]) == len(body.memory_revision_ids)
        assert any("byte limit" in gap for gap in body.gaps)
        assert len(exchange.canonical(body.model_dump(mode="json")).encode()) < 128 * 1024
        saved = store.save_packet(session, body)
        publish(session, check, UUID(saved["id"]), now)
        context = exchange.context(check.market_watch_snapshots_dir, check.profiles[0].id, saved["id"], now)
        assert len(exchange.canonical(context).encode()) < exchange.LIMIT
        assert len(context["packet"]["memories"]) == len(body.memory_revision_ids)


def _imported_at(db, at):
    """Records take the importer's wall-clock time; pin it to the simulated import moment."""
    with Session(db) as session:
        for row in session.exec(select(MorningBriefingRecord)).all():
            row.created_at = at.replace(tzinfo=None)
            session.add(row)
        session.commit()


def _submit(check, packet_id, operation_id, at, summary="Saved watchlist only"):
    body = BriefingSave(operation_id=operation_id, packet_id=packet_id, author="Jo", prompt_version="test",
        summary=summary, summary_evidence_ids=["watchlist"], items=[], limitations=["Fixture"])
    exchange.submit(check.market_watch_snapshots_dir, check.market_watch_outbox_dir, check.profiles[0].id,
        packet_id, "briefing", body.model_dump(mode="json"), at)


def test_delivery_is_judged_on_journal_availability_and_keeps_the_miss(morning):
    """Submitted 09:05 but imported 09:16: late, with the receipt time and import lag kept."""
    h, db, config = morning
    check = read_config(h.config_path)
    actor = check.profiles[0].id
    open_day = lambda day: {"status": "open", "open": 570, "close": 960}  # noqa: E731
    runner = MorningRunner(db, lambda: config, open_day, lambda symbols, cutoff, **kwargs: ([], []))
    with Session(db) as session:
        before = morning_view(session, NOW.date(), NOW - timedelta(minutes=5), config=config, calendar=open_day, actor=actor)["delivery"]
        assert before["publication"] == "pending" and before["fulfilment"] == "pending" and before["origin"] == "unknown"
        unpublished = morning_view(session, NOW.date(), NOW + timedelta(minutes=31), config=config, calendar=open_day, actor=actor)["delivery"]
        assert unpublished["publication"] == "missing" and unpublished["fulfilment"] == "missing"
    assert runner.run_once(NOW)["status"] == "published"
    with Session(db) as session:
        packet_id = session.exec(select(MorningBriefingPacket)).one().id
    _submit(check, packet_id, "scheduled", NOW + timedelta(minutes=20))
    with Session(db) as session:
        waiting = morning_view(session, NOW.date(), NOW + timedelta(minutes=29), config=config, calendar=open_day, actor=actor)["delivery"]
        assert waiting["publication"] == "published" and waiting["fulfilment"] == "pending"
        missed = morning_view(session, NOW.date(), NOW + timedelta(minutes=30), config=config, calendar=open_day, actor=actor)["delivery"]
        assert missed["fulfilment"] == "missing" and missed["deadline"] == "2026-10-19T13:15:00+00:00"
    assert runner.run_once(NOW + timedelta(minutes=31))["imported"] == 1
    _imported_at(db, NOW + timedelta(minutes=31))
    with Session(db) as session:
        late = morning_view(session, NOW.date(), NOW + timedelta(hours=1), config=config, calendar=open_day, actor=actor)["delivery"]
        assert late["fulfilment"] == "late" and late["late_by_seconds"] == 60
        assert late["submitted_at"] == (NOW + timedelta(minutes=20)).isoformat()
        assert late["import_lag_seconds"] == 11 * 60
        # A same-day manual packet's brief never counts as the scheduled delivery.
        from jo_briefing_common import PacketSave
        manual = store.save_packet(session, PacketSave(operation_id="manual-afternoon", day=NOW.date(), as_of=NOW + timedelta(hours=6),
            scope="manual", evidence=[{"id": "x", "kind": "fact", "text": "x", "source": "Fixture", "retrieved_at": (NOW + timedelta(hours=6)).isoformat()}], gaps=[]))
        store.save_briefing(session, BriefingSave(operation_id="manual-brief", packet_id=manual["id"], author="Jo", prompt_version="test",
            summary="Manual", summary_evidence_ids=["x"], items=[], limitations=[]))
        view = morning_view(session, NOW.date(), NOW + timedelta(hours=7), config=config, calendar=open_day, actor=actor)
        assert view["briefing"]["operation_id"] == "manual-brief" and view["delivery"]["briefing_id"] == late["briefing_id"]
        assert view["delivery"]["fulfilment"] == "late" and view["delivery"]["other_briefings"] == 1


def test_delivery_on_time_closed_unknown_and_owner_saves_have_no_submission_time(morning):
    h, db, config = morning
    check = read_config(h.config_path)
    actor = check.profiles[0].id
    open_day = lambda day: {"status": "open", "open": 570, "close": 960}  # noqa: E731
    runner = MorningRunner(db, lambda: config, open_day, lambda symbols, cutoff, **kwargs: ([], []))
    runner.run_once(NOW)
    with Session(db) as session:
        packet_id = session.exec(select(MorningBriefingPacket)).one().id
    _submit(check, packet_id, "early", NOW + timedelta(minutes=10))
    runner.run_once(NOW + timedelta(minutes=11))
    _imported_at(db, NOW + timedelta(minutes=11))
    with Session(db) as session:
        on_time = morning_view(session, NOW.date(), NOW + timedelta(hours=1), config=config, calendar=open_day, actor=actor)["delivery"]
        assert on_time["fulfilment"] == "on_time" and on_time["late_by_seconds"] == 0
        for calendar, expected in [(lambda d: {"status": "closed"}, "not_expected"), (lambda d: None, "unknown")]:
            assert morning_view(session, NOW.date(), NOW, config=config, calendar=calendar, actor=actor)["delivery"]["fulfilment"] == expected
        assert morning_view(session, NOW.date(), NOW, config=config, calendar=open_day, actor=None)["delivery"]["fulfilment"] == "unknown"
        assert morning_view(session, NOW.date(), NOW, config=None, calendar=open_day, actor=actor)["delivery"]["fulfilment"] == "not_expected"
        owner = store.save_briefing(session, BriefingSave(operation_id="owner", packet_id=packet_id, author="Jo", prompt_version="test",
            summary="Owner save", summary_evidence_ids=["watchlist"], items=[], limitations=[]))
        from app.models import MorningBriefingSubmission
        assert session.get(MorningBriefingSubmission, UUID(owner["id"])) is None
        assert session.get(MorningBriefingSubmission, UUID(on_time["briefing_id"])) is not None


def test_first_morning_read_leaves_one_content_free_marker_and_the_view_reports_it(morning, monkeypatch):
    """A read tells "never ran" apart from "ran but nothing arrived"; it proves neither origin nor use."""
    h, db, config = morning
    check = read_config(h.config_path)
    actor = check.profiles[0].id
    open_day = lambda day: {"status": "open", "open": 570, "close": 960}  # noqa: E731
    outbox = Path(check.market_watch_outbox_dir)
    marker = outbox / f"jo-read-{actor}-{NOW.date().isoformat()}.json"
    token = h.token(scope="check:read jo:read jo:submit")

    def read_at(now):
        with TestClient(h.server(now=now).streamable_http_app()) as browser:
            return call(browser, "jo_morning_context", {}, token)

    assert read_at(NOW - timedelta(minutes=1))["isError"]  # No pointer published yet.
    assert not list(outbox.iterdir())
    MorningRunner(db, lambda: config, open_day, lambda symbols, cutoff, **kwargs: ([], [])).run_once(NOW)
    with Session(db) as session:
        packet_id = str(session.exec(select(MorningBriefingPacket)).one().id)
        view = lambda: morning_view(session, NOW.date(), NOW + timedelta(minutes=31), config=config, calendar=open_day, actor=actor)["delivery"]  # noqa: E731
        # No earlier marker: an old Check runtime or a day before the trace existed, so absence is unknown.
        assert view()["fulfilment"] == "missing" and view()["context_read"] == "unknown"
        exchange.record_read(str(outbox), actor, (NOW.date() - timedelta(days=1)).isoformat(), uuid4(), NOW - timedelta(days=1))
        unread = view()
        assert unread["context_read"] == "not_recorded" and unread["context_read_at"] is None

    # A marker that can't be written never fails the read.
    def broken(*args):
        raise OSError("fixture outbox unavailable")
    with monkeypatch.context() as patch:
        patch.setattr(exchange, "record_read", broken)
        assert not read_at(NOW + timedelta(minutes=5)).get("isError")
    assert not marker.exists()

    first = read_at(NOW + timedelta(minutes=17))
    assert not first.get("isError") and first["structuredContent"]["packet"]["id"] == packet_id
    recorded = json.loads(marker.read_text())
    assert recorded == {"schema_version": "jo-read-v1", "profile_id": actor, "day": NOW.date().isoformat(),
        "packet_id": packet_id, "read_at": (NOW + timedelta(minutes=17)).isoformat()}
    original = marker.read_bytes()
    assert not read_at(NOW + timedelta(minutes=25)).get("isError")
    assert marker.read_bytes() == original  # Later reads keep the first.
    assert read_at(NOW + timedelta(hours=5))["isError"]  # Expired publication: refused, marker untouched.
    assert marker.read_bytes() == original and len(list(outbox.glob("jo-read-*.json"))) == 2
    # A concurrent first read that loses the race to a different clock keeps the winner without failing.
    later = (NOW.date() + timedelta(days=1)).isoformat()
    real_write = exchange.write
    def race(directory, name, value):
        real_write(directory, name, {**value, "read_at": "winner"})
        real_write(directory, name, value)
    with monkeypatch.context() as patch:
        patch.setattr(exchange, "write", race)
        exchange.record_read(str(outbox), actor, later, packet_id, NOW + timedelta(days=1))
    assert json.loads((outbox / f"jo-read-{actor}-{later}.json").read_text())["read_at"] == "winner"
    (outbox / f"jo-read-{actor}-{later}.json").unlink()
    with Session(db) as session:
        view = morning_view(session, NOW.date(), NOW + timedelta(minutes=31), config=config, calendar=open_day, actor=actor)["delivery"]
        assert view["context_read"] == "recorded" and view["context_read_at"] == (NOW + timedelta(minutes=17)).isoformat()
        assert view["fulfilment"] == "missing" and view["origin"] == "unknown"
    # A marker for another packet, or one the app can't read, stays unknown, never "not read".
    with pytest.raises(ValueError, match="does not match"):
        exchange.read_marker(str(outbox), actor, NOW.date().isoformat(), uuid4())
    marker.chmod(0)
    try:
        with Session(db) as session:
            assert morning_view(session, NOW.date(), NOW + timedelta(minutes=31), config=config, calendar=open_day, actor=actor)["delivery"]["context_read"] == "unknown"
    finally:
        marker.chmod(0o640)
    # The importer's scan never treats the marker as a submission.
    runner = MorningRunner(db, lambda: config, open_day, lambda symbols, cutoff, **kwargs: ([], []))
    assert runner.run_once(NOW + timedelta(minutes=32))["errors"] == 0 and runner.pending["unreadable"] == 0


def test_runner_reports_waiting_and_unreadable_submissions_for_its_own_profile(morning):
    h, db, config = morning
    check = read_config(h.config_path)
    runner = MorningRunner(db, lambda: config, lambda day: {"status": "open", "open": 570}, lambda s, c, **kwargs: ([], []))
    runner.run_once(NOW)
    with Session(db) as session:
        packet_id = session.exec(select(MorningBriefingPacket)).one().id
    _submit(check, packet_id, "queued", NOW + timedelta(minutes=1))
    outbox = Path(check.market_watch_outbox_dir)
    (outbox / ("jo-request-" + "1" * 64 + ".json")).write_text("not json")
    candidates = sorted(outbox.glob("jo-request-*.json"))
    waiting = MorningRunner.waiting(check, check.profiles[0].id, candidates)
    assert waiting == {"count": 1, "oldest_submitted_at": (NOW + timedelta(minutes=1)).isoformat(), "unreadable": 1}
    assert MorningRunner.waiting(check, "check_" + str(uuid4()), candidates)["count"] == 0
    # A file named for another operation can never import; it is not a waiting brief.
    real = next(p for p in candidates if "1" * 64 not in p.name)
    renamed = outbox / ("jo-request-" + "2" * 64 + ".json")
    renamed.write_bytes(real.read_bytes())
    assert MorningRunner.waiting(check, check.profiles[0].id, [real, renamed])["unreadable"] == 1
    renamed.unlink()
    runner.run_once(NOW + timedelta(minutes=2))
    assert runner.pending == {"count": 0, "oldest_submitted_at": None, "unreadable": 1}
    assert runner.last_status == "published"


def test_watchdog_status_is_unknown_without_its_record(tmp_path):
    from app.engine.jo_morning import watchdog_status
    day = NOW.date()
    path = tmp_path / "state.json"
    assert watchdog_status(day, path)["state"] == "unknown"
    path.write_text("not json")
    assert watchdog_status(day, path)["state"] == "unknown"
    notice = {"kind": "brief", "title": "Jo's morning brief is missing", "recovered": False, "outcome": "unknown", "at": NOW.isoformat()}
    path.write_text(json.dumps({"jo_morning": {"enabled": True, "checked_at": NOW.isoformat(), "notices": {day.isoformat(): [notice]}}}))
    assert watchdog_status(day, path) == {"state": "on", "checked_at": NOW.isoformat(), "notices": [notice]}
    assert watchdog_status(day + timedelta(days=1), path)["notices"] == []
    path.write_text(json.dumps({"jo_morning": {"enabled": False}}))
    assert watchdog_status(day, path)["state"] == "off"


def test_morning_route_reports_delivery_and_never_claims_chatgpt_delivery(client, monkeypatch, tmp_path):  # noqa: F811
    from app.engine import jo_morning
    monkeypatch.setattr(jo_morning, "ALERTS_STATE", tmp_path / "absent.json")
    view = client.get("/jo/morning?day=2026-10-01").json()
    assert view["delivery"]["fulfilment"] == "not_expected" and view["delivery"]["origin"] == "unknown"
    assert view["delivery"]["notifications"] == {"chatgpt": "not_observable", "watchdog": {"state": "unknown", "checked_at": None, "notices": []}}
    assert set(view["automation"]) >= {"enabled", "last_pass", "unavailable", "last_status", "pending"}


def test_submitted_at_migration_roundtrip_keeps_records(tmp_path):
    from sqlalchemy import inspect
    from tests.test_schema_migrations import _alembic
    path = tmp_path / "submitted-at.sqlite"
    _alembic(path, "upgrade", "head")
    db = create_engine(f"sqlite:///{path}")
    tables = lambda: set(inspect(db).get_table_names())  # noqa: E731
    record_sql = lambda: [c["name"] for c in inspect(db).get_columns("morning_briefing_record")]  # noqa: E731
    assert "morning_briefing_submission" in tables()
    before = record_sql()
    _alembic(path, "downgrade", "d0f6b2c4e8a3")
    assert "morning_briefing_submission" not in tables() and "morning_briefing_feedback" in tables()
    assert record_sql() == before  # Additive: the record table itself never changes.
    _alembic(path, "upgrade", "head")
    assert "morning_briefing_submission" in tables()
    db.dispose()


def test_backdrop_evidence_leads_market_rows_passes_check_citation_rules_and_never_blocks(morning):
    from app.models import MarketContextItem
    h, db, config = morning
    actor = read_config(h.config_path).profiles[0].id
    with Session(db) as session:
        session.add(MarketContextItem(kind="vix", symbol="VIX", value=17.5, fetched_at=NOW.replace(tzinfo=None) - timedelta(minutes=3),
                                      source="Tradier"))
        session.add(MarketContextItem(kind="earnings", symbol="MU", event_date=NOW.date() + timedelta(days=2), status="confirmed",
                                      fetched_at=NOW.replace(tzinfo=None) - timedelta(hours=1), source="Tradier"))
        session.commit()
        def market(symbols, cutoff, **kwargs):
            return [dict(id="market-SPY", kind="fact", text="SPY fixture", source="Fixture", observed_at=NOW, retrieved_at=NOW)], []
        packet = collect(session, config, actor, NOW, market)
        ids = [e.id for e in packet.evidence]
        assert ids.index("macro-calendar") < ids.index("vix") < ids.index("earnings-MU") < ids.index("market-SPY")
        published = {"id": str(uuid4()), "body": packet.model_dump(mode="json")}
        body = BriefingSave(operation_id="backdrop", packet_id=published["id"], author="Jo", prompt_version="jo-morning-v3",
            summary="Calm backdrop; MU reports Wednesday.", summary_evidence_ids=["vix", "macro-calendar", "earnings-MU"],
            items=[], limitations=["No futures, yields, dollar or oil."])
        exchange.validate_body("briefing", body.model_dump(mode="json"), published)
        def broken(*_):
            raise RuntimeError("database gone")
        packet = collect(session, config, actor, NOW, market, broken)
        assert "vix" not in [e.id for e in packet.evidence] and "market-SPY" in [e.id for e in packet.evidence]
        assert "Macro calendar, VIX and earnings backdrop unavailable." in packet.gaps


def test_discovery_excludes_all_saved_symbols_beyond_packet_caps(morning):
    h, db, config = morning
    from app.engine.jo_morning import collect
    watchlist = ["W"+chr(65+i//26)+chr(65+i%26) for i in range(35)]
    tickers = ["H"+chr(65+i) for i in range(22)]
    with Session(db) as session:
        settings = session.get(ChartSettingsRecord, "default")
        settings.data_json = json.dumps({"watchlist": watchlist})
        session.add(settings)
        session.add_all([Trade(account_id=config.account_ids[0], ticker=ticker, instrument_type="stock", contracts=1,
            avg_entry_premium=10, total_premium_paid=10, opened_at=NOW.replace(tzinfo=None)-timedelta(days=1)) for ticker in tickers])
        session.commit()
        captured = []
        def market(symbols, cutoff, *, excluded_symbols):
            captured.append((symbols, excluded_symbols))
            return [], []
        collect(session, config, read_config(h.config_path).profiles[0].id, NOW, market_reader=market, backdrop_reader=None)
    _, excluded = captured[0]
    assert set(watchlist + tickers + ["SPY"]) == excluded
    assert "SECRET" not in excluded  # No additional account grant.


def test_month_lists_each_weekday_delivery_without_guessing(morning):
    from datetime import date
    from app.engine.jo_morning import month_delivery, weekdays_in_month
    _, db, config = morning
    assert weekdays_in_month("2026-10", date(2026, 10, 6)) == [date(2026, 10, 6), date(2026, 10, 5), date(2026, 10, 2), date(2026, 10, 1)]
    assert weekdays_in_month("2026-11", date(2026, 10, 6)) == []
    days = [date(2026, 10, 19), date(2026, 10, 16)]
    with Session(db) as session:
        assert month_delivery(session, days, NOW, config, "actor", lambda day: {"status": "open"}) == []  # nothing published yet
    assert MorningRunner(db, lambda: config, lambda day: {"status": "open", "open": 570}).run_once(NOW)["status"] == "published"
    later = NOW + timedelta(hours=2)
    with Session(db) as session:
        from jo_briefing_owner import binding, load_binding
        actor = binding(load_binding(config.check_config))
        rows = month_delivery(session, days, later, config, actor, lambda day: {"status": "open"})
        # Before the first packet there is no record, so the 16th is left out instead of read as missed.
        assert [(r["day"], r["publication"], r["fulfilment"]) for r in rows] == [("2026-10-19", "published", "missing")]
        assert month_delivery(session, days, later, config, actor, lambda day: None)[0]["fulfilment"] == "unknown"


def test_month_route_shape_and_validation(client):  # noqa: F811
    assert client.get("/jo/morning").status_code == 422
    assert client.get("/jo/morning?month=2026-13").status_code == 422
    assert client.get("/jo/morning?month=2026-10").json()["days"] == []  # no packet yet: no record, not "missed"
    client.post("/jo/packets", json=packet())  # for 2026-10-01
    view = client.get("/jo/morning?month=2026-10").json()
    assert view["month"] == "2026-10" and view["days"][-1]["day"] == "2026-10-01"
    assert set(view["days"][0]) == {"day", "publication", "fulfilment", "deadline", "available_at", "late_by_seconds", "watchdog_notices"}
