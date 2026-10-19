"""Automatic packet → tool → import → owner view, all against disposable data."""
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
    def market(symbols, cutoff):
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
    runner = MorningRunner(db, lambda: config, lambda day: {"status": "open", "open": 570})
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
