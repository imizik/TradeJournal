"""Same-session holding context: original entry, conservative timing, no writes."""

from copy import deepcopy
from datetime import datetime, date
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.engine.radar_comparison import (
    compare_entry,
    empty_comparison,
    iso,
    accepted_group_versions,
)
from app.engine.radar_store import RadarStore, load_universe
from app.models import Account, Fill, Trade, TradeFill
from app.routers import radar
from tests.test_radar_comparison import NOW, UNIVERSE, seed

ENTRY = NOW - 180  # 10:12 ET; first possible pass is 10:13.
BOUNDARY = ENTRY + 60
DAY = "2026-10-20"


@pytest.fixture
def store(tmp_path):
    return RadarStore(tmp_path / "radar.sqlite")


def read_entry(store, now=NOW, entry=ENTRY, live=True, universe=UNIVERSE, today=DAY):
    result = empty_comparison("NVDA", None, universe, now)
    result.update(
        window_minutes=None,
        entry={
            "trade_id": "recorded-trade",
            "recorded_at": iso(entry),
            "not_before": iso((int(entry) // 60 + 1) * 60),
            "baseline_at": None,
            "baseline_delay_seconds": None,
        },
    )
    return compare_entry(
        store,
        result,
        today=today,
        now=now,
        live=live,
        regular_start=NOW - 2700,
        regular_end=NOW + 20700,
    )


def test_entry_skips_ineligible_first_sample_within_fixed_deadline(store):
    seed(store, BOUNDARY, edits={"NVDA": {"trade_time_ms": (BOUNDARY - 0.184) * 1000}})
    anchor = seed(store, BOUNDARY + 60)
    seed(store, NOW, {"NVDA": 98, "AMD": 99, "MU": 101, "QQQ": 99.5, "SPY": 100})
    before = store.path.read_bytes()
    result = read_entry(store)
    assert result["window"]["start_pass_id"] == anchor
    assert result["entry"]["baseline_delay_seconds"] == 120
    assert [r["change_pct"] for r in result["rows"]] == pytest.approx(
        [-2, -1, 1, -0.5, 0]
    )
    assert result["coverage"]["peers_down"] == result["coverage"]["peers_up"] == 1
    assert (
        store.path.read_bytes() == before
        and not store.events()
        and not store.last_visit()
    )


def test_entry_never_moves_anchor_to_improve_peer_coverage_or_price(store):
    first = seed(
        store, BOUNDARY, {"NVDA": 100, "QQQ": 100, "SPY": 100}, status="partial"
    )
    seed(
        store,
        BOUNDARY + 60,
        {"NVDA": 90, "AMD": 100, "MU": 100, "QQQ": 100, "SPY": 100},
    )
    seed(store, NOW)
    result = read_entry(store)
    assert result["window"]["start_pass_id"] == first
    assert result["rows"][0]["change_pct"] == 0
    assert result["coverage"]["missing"] == ["AMD", "MU"]


def test_entry_does_not_use_before_boundary_or_after_deadline(store):
    seed(store, ENTRY)
    seed(store, BOUNDARY, edits={"NVDA": {"last": None}})
    seed(store, BOUNDARY + 91)
    seed(store, NOW)
    result = read_entry(store)
    assert result["window"] is None and "90-second" in result["reason"]


@pytest.mark.parametrize(
    "edits",
    [
        {"last": 0},
        {"last": None},
        {"trade_time_ms": None},
        {"trade_time_ms": (BOUNDARY - 121) * 1000},
        {"trade_time_ms": (BOUNDARY + 1) * 1000},
        {"retrieved_at": iso(BOUNDARY - 1)},
    ],
)
def test_entry_eligibility_rules_apply_to_search(store, edits):
    seed(store, BOUNDARY, edits={"NVDA": edits})
    anchor = seed(store, BOUNDARY + 60)
    seed(store, NOW)
    assert read_entry(store)["window"]["start_pass_id"] == anchor


def test_entry_peer_baseline_trade_before_boundary_is_missing(store):
    seed(store, BOUNDARY, edits={"AMD": {"trade_time_ms": (BOUNDARY - 0.01) * 1000}})
    seed(store, NOW)
    result = read_entry(store)
    assert result["coverage"]["missing"] == ["AMD"]
    assert result["rows"][1]["reason"] == "Trade precedes the post-entry boundary"


def test_entry_waits_one_minute_and_never_substitutes_latest_selected_price(store):
    seed(store, BOUNDARY)
    assert "one minute" in read_entry(store, BOUNDARY)["reason"]
    seed(store, NOW, {"AMD": 100})
    result = read_entry(store)
    assert (
        result["window"] is None and not result["rows"] and "latest" in result["reason"]
    )


def test_entry_stale_no_future_no_overnight_and_after_close_is_labeled(store):
    seed(store, BOUNDARY)
    seed(store, NOW)
    seed(store, NOW + 600)
    assert read_entry(store)["window"]["end"] == iso(NOW)
    assert read_entry(store, NOW + 181)["state"] == "stale"
    assert not read_entry(store, NOW + 20700, live=False)["live"]
    assert read_entry(store, NOW + 86400, today="2026-10-21")["window"] is None


def test_entry_unknown_version_even_between_endpoints_is_refused(store):
    seed(store, BOUNDARY)
    seed(store, BOUNDARY + 60, version="unknown")
    seed(store, NOW)
    result = read_entry(store)
    assert result["window"] is None and "version" in result["reason"]


def test_version_compatibility_is_pinned_to_exact_known_membership(store):
    universe = load_universe()
    assert accepted_group_versions(universe) == [
        "radar-universe-v2",
        "radar-universe-v1",
    ]
    changed = deepcopy(universe)
    changed["groups"][0]["members"].append("FAKE")
    assert accepted_group_versions(changed) == ["radar-universe-v2"]
    changed = deepcopy(universe)
    changed["version"] = "radar-universe-v3"
    assert accepted_group_versions(changed) == ["radar-universe-v3"]
    seed(store, BOUNDARY, version="radar-universe-v1")
    seed(store, NOW, version="radar-universe-v2")
    result = read_entry(store, universe=universe)
    assert result["window"] and result["recorded_versions"] == [
        "radar-universe-v1",
        "radar-universe-v2",
    ]
    assert not read_entry(store, universe=changed)["window"]


@pytest.fixture
def api(store, monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setenv("RADAR_ENABLED", "true")
    monkeypatch.setenv("RADAR_STORE", str(store.path))
    monkeypatch.setattr(radar, "load_universe", lambda: UNIVERSE)
    monkeypatch.setattr(radar, "_now", lambda: NOW)
    monkeypatch.setattr(
        radar.chart_calendar,
        "hours",
        lambda day: {"status": "open", "open": 570, "close": 960},
    )
    app = FastAPI()
    app.include_router(radar.router, prefix="/radar")
    with Session(engine) as db:
        app.dependency_overrides[get_session] = lambda: db
        with TestClient(app) as client:
            yield client, db
    engine.dispose()


def trade(db, n=1, at="2026-10-20T10:12", account=1, **changes):
    if not db.get(Account, UUID(int=account)):
        db.add(
            Account(
                id=UUID(int=account),
                name=f"Account {account}",
                type="individual",
                last4=f"{account:04}",
            )
        )
    opened = datetime.fromisoformat(at)
    fields = dict(
        id=UUID(int=n),
        account_id=UUID(int=account),
        ticker="NVDA",
        instrument_type="option",
        contracts=1,
        avg_entry_premium=200,
        total_premium_paid=200,
        option_type="call",
        strike=100,
        expiration=date(2026, 10, 23),
        opened_at=opened,
        status="open",
    )
    fields.update(changes)
    t = Trade(**fields)
    db.add(t)
    f = Fill(
        id=UUID(int=n),
        account_id=t.account_id,
        ticker=t.ticker,
        instrument_type=t.instrument_type,
        contracts=1,
        price=200,
        side="buy_to_open",
        executed_at=opened,
        raw_email_id=f"fixture:{n}",
    )
    db.add(f)
    db.add(TradeFill(trade_id=t.id, fill_id=f.id, role="entry"))
    db.commit()
    return t


def url(t, symbol="NVDA"):
    return f"/radar/groups/compare?symbol={symbol}&trade_id={t.id}"


def test_api_resolves_original_entry_account_and_rejects_other_symbol(api, store):
    client, db = api
    a = trade(db)
    b = trade(db, 2, at="2026-10-20T10:13", account=2)
    seed(store, BOUNDARY)
    seed(store, BOUNDARY + 60)
    seed(store, NOW)
    assert client.get(url(a)).json()["entry"]["baseline_delay_seconds"] == 60
    assert client.get(url(b)).json()["entry"]["recorded_at"] == iso(BOUNDARY)
    assert client.get(url(a, "AMD")).status_code == 422
    assert (
        client.get("/radar/groups/compare?symbol=NVDA&trade_id=bad").status_code == 422
    )
    assert (
        client.get(
            "/radar/groups/compare?symbol=NVDA&trade_id=" + str(UUID(int=999))
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "changes,at,reason",
    [
        ({"status": "closed"}, "2026-10-20T10:12", "open option"),
        ({"instrument_type": "stock"}, "2026-10-20T10:12", "open option"),
        ({}, "2026-10-19T10:12", "overnight"),
        ({}, "2026-10-20T08:00", "outside"),
        ({}, "2026-10-20T00:00", "outside"),
        ({}, "2026-10-20T10:16", "future"),
    ],
)
def test_api_refuses_unsupported_entries(api, store, changes, at, reason):
    client, db = api
    t = trade(db, at=at, **changes)
    seed(store, BOUNDARY)
    seed(store, NOW)
    result = client.get(url(t)).json()
    assert (
        reason in result["reason"] and not result["rows"] and result["window"] is None
    )


def test_api_adds_and_partial_exits_do_not_reset_entry(api, store):
    client, db = api
    t = trade(db)
    for n, role in ((2, "entry"), (3, "exit")):
        f = Fill(
            id=UUID(int=n),
            account_id=t.account_id,
            ticker="NVDA",
            instrument_type="option",
            contracts=1,
            price=100,
            side="buy_to_open" if role == "entry" else "sell_to_close",
            executed_at=datetime(2026, 10, 20, 10, 14),
            raw_email_id=f"fixture:{n}",
        )
        db.add(f)
        db.add(TradeFill(trade_id=t.id, fill_id=f.id, role=role))
    db.commit()
    seed(store, BOUNDARY)
    seed(store, NOW)
    result = client.get(url(t)).json()
    assert result["entry"]["recorded_at"] == iso(ENTRY)
    assert result["window"]["start"] == iso(BOUNDARY)
    t.status = "closed"
    db.add(t)
    db.commit()
    assert not client.get(url(t)).json()["rows"]


def test_api_calendar_unavailable_and_rebuilt_entry_mismatch(api, store, monkeypatch):
    client, db = api
    t = trade(db)
    seed(store, BOUNDARY)
    seed(store, NOW)
    monkeypatch.setattr(radar.chart_calendar, "hours", lambda day: None)
    assert "calendar" in client.get(url(t)).json()["reason"]
    t.opened_at = datetime(2026, 10, 20, 10, 13)
    db.add(t)
    db.commit()
    assert "verified" in client.get(url(t)).json()["reason"]
