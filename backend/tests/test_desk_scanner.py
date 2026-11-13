"""Today's setup-scanner candidates on the desk (GET /copilot/scanner): today's rows only, hidden names left out (and
nothing when that setting cannot be read), new-to-him marking, one row with a matching Radar setup card, the paper
result as the Scanner page shows it, the scanner switched off, the owner-only route and its simulated fixture, and that
the read touches no provider, no Robinhood and writes nothing. No network."""

from datetime import UTC, datetime, timedelta
import inspect
import json
from types import SimpleNamespace

from sqlmodel import Session, select

from app.engine import desk_scanner, scanner_rules as rules, setup_scanner
from app.models import RadarSetup, ScannerCandidate, ScannerEvent
from tests.test_desk_ticket import NOW, REPO, T0, WED, engine, lab  # noqa: F401  (shared fixtures)
from tests.test_desk_unusual import hide, hold, watch


def candidate(engine, symbol="NBIS", setup="orb", direction="long", minutes=0, day=WED, events=(), contract=True):  # noqa: F811
    bar_end = T0 + timedelta(minutes=minutes)
    row = ScannerCandidate(
        session_date=day, symbol=symbol, setup=setup, direction=direction, scanner_version=rules.VERSION,
        params_hash=rules.PARAMS_HASH, bar_start=bar_end - timedelta(minutes=5), bar_end=bar_end, source=setup_scanner.SOURCE,
        detected_at=bar_end, expires_at=bar_end + timedelta(minutes=10), stop=93.18, target=96.0, flags_json="[]",
        facts_json=json.dumps({"close": 94.12, "vwap": 93.6, "opening_range_high": 94.05, "opening_range_low": 92.9}),
        contract_json=json.dumps({"symbol": "NBIS261023C00095000", "option_type": "call", "strike": 95.0,
                                  "expiration": "2026-10-23", "delta": 0.4567, "bid": 1.0, "ask": 1.05}) if contract else None)
    with Session(engine) as db:
        db.add(row)
        for kind, data in events:
            db.add(ScannerEvent(candidate_id=row.id, key=kind, event_type=kind, effective_at=bar_end + timedelta(minutes=2),
                                recorded_at=bar_end + timedelta(minutes=2), data_json=json.dumps(data)))
        db.commit()
        return str(row.id)


def radar(engine, symbol="NBIS", direction="up", plan_state="none"):  # noqa: F811
    with Session(engine) as db:
        db.add(RadarSetup(event_id=f"rd0-{symbol}-{direction}", session_date=WED.isoformat(), rule_version="v0", kind="dip_turn",
                          symbol=symbol, direction=direction, entry=94.0, invalidation=92.5, created_at=T0, plan_state=plan_state))
        db.commit()


def read(engine, monkeypatch, on=True):  # noqa: F811
    monkeypatch.setenv("SETUP_SCANNER_ENABLED", "true" if on else "false")
    with Session(engine) as db:
        return desk_scanner.view(db, {"state": "fresh"}, NOW)


def test_today_rows_newest_first_with_levels_and_paper_result(engine, monkeypatch):  # noqa: F811
    candidate(engine, "NBIS", minutes=0, events=[("entry", {"ask": 1.05}), ("exit", {"bid": 1.5, "pnl": 44.0, "reason": "target"})])
    candidate(engine, "AMD", "fade", "short", minutes=30)
    candidate(engine, "SPY", day=WED - timedelta(days=1))  # yesterday: not today's
    body = read(engine, monkeypatch)
    assert body["state"] == "ok" and body["day"] == "2026-10-21" and body["monitoring"] == {"state": "fresh"}
    assert [r["symbol"] for r in body["rows"]] == ["AMD", "NBIS"]
    amd, nbis = body["rows"]
    assert amd["words"] == "VWAP fade (short)" and amd["status"] == "pending_entry" and amd["pnl"] is None
    assert nbis["words"] == "Opening-range break (long)"
    assert (nbis["trigger"], nbis["stop"], nbis["target"], nbis["vwap"], nbis["range_high"], nbis["range_low"]) == (94.12, 93.18, 96.0, 93.6, 94.05, 92.9)
    assert nbis["contract_line"] == "10-23 95C · Δ0.46"
    assert (nbis["status"], nbis["pnl"], nbis["exit_reason"]) == ("exit", 44.0, "target")
    assert nbis["bar_end"] == "2026-10-21T14:00:00Z"


def test_no_contract_is_said_and_levels_still_shown(engine, monkeypatch):  # noqa: F811
    candidate(engine, contract=False)
    row = read(engine, monkeypatch)["rows"][0]
    assert row["status"] == "no_contract" and row["contract_line"] is None and row["trigger"] == 94.12


def test_hidden_names_stay_out_and_an_unreadable_setting_shows_nothing(engine, monkeypatch):  # noqa: F811
    candidate(engine, "NBIS")
    candidate(engine, "AMD", minutes=5)
    hide(engine, "AMD")
    assert [r["symbol"] for r in read(engine, monkeypatch)["rows"]] == ["NBIS"]
    from app.engine import day_journal

    def broken(db):
        raise RuntimeError("no table")
    monkeypatch.setattr(day_journal, "not_following", broken)
    body = read(engine, monkeypatch)
    assert body["state"] == "unavailable" and body["rows"] == [] and "could not be read" in body["message"]


def test_a_name_he_does_not_hold_watch_or_plan_is_new_to_him(engine, monkeypatch):  # noqa: F811
    for minutes, symbol in enumerate(["NBIS", "AMD", "CRWV"]):
        candidate(engine, symbol, minutes=minutes)
    hold(engine, "NBIS")
    watch(engine, "AMD")
    assert {r["symbol"]: r["new"] for r in read(engine, monkeypatch)["rows"]} == {"NBIS": False, "AMD": False, "CRWV": True}
    # His book unreadable: nothing is marked new rather than guessing.
    from app.engine import desk_feed

    def broken(db):
        raise RuntimeError("no table")
    monkeypatch.setattr(desk_feed, "_book", broken)
    assert {r["new"] for r in read(engine, monkeypatch)["rows"]} == {False}


def test_a_candidate_that_is_also_a_radar_setup_carries_the_card_once(engine, monkeypatch):  # noqa: F811
    candidate(engine, "NBIS", direction="long")
    candidate(engine, "AMD", direction="long", minutes=5)
    radar(engine, "NBIS", "up")
    radar(engine, "AMD", "down")  # the other direction: a different setup
    rows = {r["symbol"]: r for r in read(engine, monkeypatch)["rows"]}
    assert len(rows) == 2 and rows["AMD"]["radar"] is None
    card = rows["NBIS"]["radar"]
    assert card["event_id"] == "rd0-NBIS-up" and card["plan_state"] == "none"
    assert card["href"] == "/copilot-lab?symbol=NBIS&radar=rd0-NBIS-up" and card["levels_line"].startswith("In near 94.00")


def test_switched_off_is_off(engine, monkeypatch):  # noqa: F811
    candidate(engine)
    body = read(engine, monkeypatch, on=False)
    assert body["state"] == "off" and body["rows"] == []


def test_the_read_writes_nothing_and_calls_no_provider(engine, monkeypatch):  # noqa: F811
    candidate(engine, events=[("entry", {"ask": 1.05})])
    with Session(engine) as db:
        before = (len(db.exec(select(ScannerCandidate)).all()), len(db.exec(select(ScannerEvent)).all()))
    read(engine, monkeypatch)
    with Session(engine) as db:
        assert (len(db.exec(select(ScannerCandidate)).all()), len(db.exec(select(ScannerEvent)).all())) == before
    source = inspect.getsource(desk_scanner)
    imports = " ".join(line for line in source.lower().splitlines() if "import" in line)
    for word in ("robinhood", "tradier", "options_feed", "chart_feed", "notification", "telegram", "quote"):
        assert word not in imports, word
    assert "db.add" not in source and "commit(" not in source


def test_the_route_is_owner_only_and_the_fixture_is_simulated(engine, lab, monkeypatch):  # noqa: F811
    from app.access_manifest import DOMAIN_ROUTES
    from app.routers import copilot_ticket as routes
    assert "GET /copilot/scanner" in DOMAIN_ROUTES
    monkeypatch.setenv("SETUP_SCANNER_ENABLED", "true")
    candidate(engine, "NBIS")
    monkeypatch.setattr(routes, "time", SimpleNamespace(time=lambda: NOW))
    body = lab.get("/copilot/scanner").json()
    assert [r["symbol"] for r in body["rows"]] == ["NBIS"] and body["monitoring"]["state"] == "not_running"
    monkeypatch.setattr(routes.copilot, "settings", lambda: SimpleNamespace(enabled=True, evidence="fixture"))
    body = lab.get("/copilot/scanner").json()
    assert body["simulated"] is True and [(r["symbol"], r["new"]) for r in body["rows"]] == [("NBIS", False), ("CRWV", True)]
    hide(engine, "CRWV")
    assert [r["symbol"] for r in lab.get("/copilot/scanner").json()["rows"]] == ["NBIS"]
    monkeypatch.setattr(routes.copilot, "settings", lambda: SimpleNamespace(enabled=False))
    assert lab.get("/copilot/scanner").status_code == 503


def test_the_docs_name_the_route():
    assert "GET /copilot/scanner" in (REPO / "docs" / "copilot-lab.md").read_text()
    assert datetime.fromtimestamp(NOW, UTC).date() == WED
