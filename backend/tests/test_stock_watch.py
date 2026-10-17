"""Stock awareness, option independence and actual transport boundaries with fixtures."""

from datetime import UTC, datetime, timedelta
import json
import sqlite3
import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from app.engine.stock_watch import StockWatcher, packet, detect_move
from app.engine.market_watch_wakes import MarketWatchWakeStore
from cloud_mcp_check_ledger import Ledger, Conflict
from market_watch_common import seal
from stock_watch_common import validate_alert, validate_review
from stock_watch_ledger import StockWatchLedger, write_review
from tests.test_cloud_mcp_check import (
    harness as harness,
    signing_key as signing_key,
    call,
    rpc,
    RECEIPT,
)
from tests.test_setup_scanner import engine as engine

NOW = RECEIPT
ACTOR = "check_00000000-0000-0000-0000-000000000001"
SCOPE = "check:read market-watch:read market-watch:submit"


def minutes(now=NOW, *, n=30, first=100, step=0.15):
    end = now.replace(second=0, microsecond=0).timestamp()
    return [
        {
            "time": end - (n - i) * 60,
            "end_time": end - (n - i - 1) * 60,
            "open": first + i * step,
            "high": first + i * step + 0.2,
            "low": first + i * step - 0.2,
            "close": first + i * step + 0.1,
            "volume": 1000.0,
        }
        for i in range(n)
    ]


def alert(now=NOW, **changes):
    value = packet(
        "NBIS",
        "move",
        "up",
        minutes(now),
        now,
        now,
        {"symbols": ["NBIS"], "revision": 1},
        {"kind": "session_rebound"},
        alert_id="sta_" + str(uuid.uuid4()),
    )
    return seal(
        {**{k: v for k, v in value.items() if k != "content_sha256"}, **changes}
    )


def watcher(tmp_path, clock=lambda: NOW, **kwargs):
    public, outbox = tmp_path / "public", tmp_path / "outbox"
    public.mkdir(exist_ok=True)
    outbox.mkdir(exist_ok=True)
    return StockWatcher(
        MarketWatchWakeStore(tmp_path / "wakes.db"),
        public,
        outbox,
        clock=clock,
        **kwargs,
    )


def test_contiguous_fresh_moves_rebounds_and_no_future_bars():
    bars = minutes()
    found = detect_move(bars, bars[0]["time"], NOW.timestamp(), 2.0)
    assert found[0] == "up"
    assert detect_move(bars[:-5], bars[0]["time"], NOW.timestamp(), 2.0) is None
    assert (
        detect_move(bars[:15] + bars[16:], bars[0]["time"], NOW.timestamp(), 2.0)
        is None
    )
    assert detect_move(bars, bars[0]["time"], NOW.timestamp(), None) is None
    future = {
        **bars[-1],
        "time": NOW.timestamp() + 60,
        "end_time": NOW.timestamp() + 120,
        "close": 1000.0,
        "high": 1000.0,
    }
    assert detect_move(bars + [future], bars[0]["time"], NOW.timestamp(), 2.0) == found
    previous = alert()
    assert detect_move(bars, bars[0]["time"], NOW.timestamp(), 2.0, previous) is None


@pytest.mark.parametrize(
    "change",
    ["future", "stale", "duplicate", "price", "eligibility", "selection", "extra"],
)
def test_frozen_alert_schema_refuses_unsafe_evidence(change):
    p = alert()
    if change == "future":
        p["evidence"]["bars"][-1]["end_time"] += 60
    elif change == "stale":
        p["observed_at"] = (NOW - timedelta(minutes=4)).isoformat()
    elif change == "duplicate":
        p["evidence"]["bars"][-1] = p["evidence"]["bars"][-2]
    elif change == "price":
        p["evidence"]["price"] += 1
    elif change == "eligibility":
        p["trade_eligibility"]["status"] = "take"
    elif change == "selection":
        p["selected_symbols"] = []
    else:
        p["private_position"] = "never"
    with pytest.raises(ValueError):
        validate_alert(seal({k: v for k, v in p.items() if k != "content_sha256"}))


def test_actor_bound_review_retry_conflict_expiry_and_immutability(tmp_path):
    ledger = StockWatchLedger(Ledger(tmp_path / "ledger.db"))
    p = alert()
    with pytest.raises(ValueError, match="Read this"):
        ledger.submit(ACTOR, p, "watch", "A rebound", "Below low", True, lambda: NOW)
    ledger.serve(ACTOR, p, NOW)
    result = ledger.submit(
        ACTOR, p, "watch", "A rebound", "Below low", True, lambda: NOW
    )
    assert (
        ledger.submit(
            ACTOR,
            p,
            "watch",
            "A rebound",
            "Below low",
            True,
            lambda: NOW + timedelta(days=1),
        )
        == result
    )
    with pytest.raises(Conflict):
        ledger.submit(ACTOR, p, "watch", "Different", "Below low", True, lambda: NOW)
    with pytest.raises(Conflict):
        ledger.submit("other", p, "watch", "A rebound", "Below low", True, lambda: NOW)
    with pytest.raises(ValueError):
        ledger.submit(
            ACTOR, alert(), "no_view", "No data", "Fresh data", True, lambda: NOW
        )
    with sqlite3.connect(tmp_path / "ledger.db") as db:
        assert db.execute("SELECT count(*) FROM shadow_decision").fetchone()[0] == 0
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT OR REPLACE INTO stock_watch_review VALUES(?,?,?)",
                ("other", p["alert_id"], "{}"),
            )
        for table in ["stock_watch_input", "stock_watch_review"]:
            for sql in [
                f"DELETE FROM {table}",
                f'UPDATE {table} SET actor="other"',
                f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}",
            ]:
                with pytest.raises(sqlite3.IntegrityError):
                    db.execute(sql)
    second = alert()
    ledger.serve(ACTOR, second, NOW)
    with pytest.raises(ValueError, match="expired"):
        ledger.submit(
            ACTOR,
            second,
            "watch",
            "A rebound",
            "Below low",
            True,
            lambda: NOW + timedelta(minutes=10),
        )


def test_export_recovery_one_push_and_no_paper_action(tmp_path):
    sent = []
    w = watcher(
        tmp_path, push=lambda title, body: sent.append((title, body)) or "ntfy-fixture"
    )
    p = w.capture(alert())
    ledger = StockWatchLedger(Ledger(tmp_path / "ledger.db"))
    ledger.serve(ACTOR, p, NOW)
    r = ledger.submit(
        ACTOR, p, "watch", "Large rebound", "Below the reference", True, lambda: NOW
    )
    write_review(w.outbox, r)
    write_review(w.outbox, r)
    w.ingest_and_deliver()
    w.ingest_and_deliver()
    assert len(sent) == 1 and "option/trade eligibility is separate" in sent[0][1]
    attempts = w.store.records("stock_push_attempt")
    assert [a["result"] for a in attempts] == ["sending", "accepted"]
    assert attempts[-1]["transport_receipt_id"] == "ntfy-fixture"
    # A restart recovers the same frozen input, expiry and sent receipt.
    w2 = StockWatcher(
        w.store, w.directory, w.outbox, push=lambda *_: pytest.fail("duplicate push")
    )
    assert w2.capture({**p}) == p
    w2.ingest_and_deliver()
    path = w.outbox / f"stock-review-{r['review_id']}.json"
    path.unlink()
    write_review(w.outbox, r)
    path.unlink()
    path.symlink_to(tmp_path / "ledger.db")
    with pytest.raises((ValueError, OSError)):
        write_review(w.outbox, r)


def test_expired_unknown_and_quiet_reviews_never_resend(tmp_path):
    p = alert()
    ledger = StockWatchLedger(Ledger(tmp_path / "ledger.db"))
    ledger.serve(ACTOR, p, NOW)
    r = ledger.submit(ACTOR, p, "watch", "Rebound", "Below low", True, lambda: NOW)
    w = watcher(
        tmp_path,
        clock=lambda: NOW + timedelta(minutes=10),
        push=lambda *_: pytest.fail("expired push"),
    )
    w.capture(p)
    write_review(w.outbox, r)
    w.ingest_and_deliver()
    assert w.store.records("stock_push_attempt")[0]["result"] == "expired"
    other = alert()
    w.capture(other)
    ledger.serve(ACTOR, other, NOW)
    quiet = ledger.submit(
        ACTOR,
        other,
        "no_view",
        "Insufficient evidence",
        "Need data",
        False,
        lambda: NOW,
    )
    write_review(w.outbox, quiet)
    w.ingest_and_deliver()
    assert len(w.store.records("stock_push_attempt")) == 1


def test_diagnostic_is_explicit_not_live_advice(tmp_path):
    p = alert(
        kind="diagnostic", source="delivery_diagnostic", diagnostic_code="STK-FLOW-01"
    )
    validate_alert(p)
    ledger = StockWatchLedger(Ledger(tmp_path / "ledger.db"))
    ledger.serve(ACTOR, p, NOW)
    with pytest.raises(ValueError, match="Diagnostic"):
        ledger.submit(ACTOR, p, "watch", "Buy NBIS", "Below low", True, lambda: NOW)
    r = ledger.submit(
        ACTOR,
        p,
        "watch",
        "Delivery diagnostic STK-FLOW-01; no market advice",
        "Not a trade",
        True,
        lambda: NOW,
    )
    validate_review(r, p)


def test_real_mcp_auth_source_boundary_saved_receipt_export_and_no_provider(
    harness, tmp_path
):
    public, outbox = tmp_path / "public", tmp_path / "outbox"
    public.mkdir()
    outbox.mkdir()
    p = alert()
    (public / f"stock-{p['alert_id']}.json").write_text(json.dumps(p))
    harness.configure(
        market_watch_snapshots_dir=str(public), market_watch_outbox_dir=str(outbox)
    )
    before = len(harness.requests)
    args = {"alert_id": p["alert_id"]}
    submit = {
        **args,
        "stance": "watch",
        "summary": "Observed rebound",
        "invalidation": "Below low",
        "notify": True,
    }
    with TestClient(harness.server(now=NOW).streamable_http_app()) as client:
        assert call(client, "stock_alert", args, harness.token())["isError"]
        assert call(client, "stock_alert_submit", submit, harness.token(scope=SCOPE))[
            "isError"
        ]
        assert call(
            client,
            "stock_alert",
            {"alert_id": "../../passwd"},
            harness.token(scope=SCOPE),
        )["isError"]
        assert (
            rpc(
                client, "stock_alert", args, harness.token(subject="other", scope=SCOPE)
            ).status_code
            == 401
        )
        assert (
            call(client, "stock_alert", args, harness.token(scope=SCOPE))[
                "structuredContent"
            ]["alert"]
            == p
        )
        assert call(
            client,
            "stock_alert_submit",
            submit,
            harness.token(scope="check:read market-watch:read"),
        )["isError"]
        r = call(client, "stock_alert_submit", submit, harness.token(scope=SCOPE))[
            "structuredContent"
        ]
        assert (
            call(client, "stock_alert_submit", submit, harness.token(scope=SCOPE))[
                "structuredContent"
            ]
            == r
        )
        assert call(
            client,
            "stock_alert_submit",
            {**submit, "decision": "take"},
            harness.token(scope=SCOPE),
        )["isError"]
    # Recover an interrupted export through the real tool after the session
    # changes, without allowing a late new assessment or historical input read.
    exported = outbox / f"stock-review-{r['review_id']}.json"
    exported.unlink()
    late = alert()
    (public / f"stock-{late['alert_id']}.json").write_text(json.dumps(late))
    with TestClient(
        harness.server(now=NOW + timedelta(days=1)).streamable_http_app()
    ) as client:
        assert call(client, "stock_alert", args, harness.token(scope=SCOPE))["isError"]
        assert call(
            client, "stock_alert_submit", submit, harness.token(scope=SCOPE)
        )["structuredContent"] == r
        assert call(
            client,
            "stock_alert_submit",
            {**submit, "alert_id": late["alert_id"]},
            harness.token(scope=SCOPE),
        )["isError"]
    assert len(harness.requests) == before
    assert json.loads((outbox / f"stock-review-{r['review_id']}.json").read_text()) == r
    with sqlite3.connect(
        json.loads(harness.config_path.read_text())["ledger_file"]
    ) as db:
        assert db.execute("SELECT count(*) FROM shadow_decision").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM stock_watch_review").fetchone()[0] == 1


def test_capture_precedes_failed_option_selection_and_remains_stock_only(
    engine, monkeypatch, tmp_path
):
    from tests.test_setup_scanner import scanner, breakout_day, at, DAY, rows
    from app.engine import stock_watch

    s, clock = scanner(engine, at(9, 50, 35))
    breakout_day(s.feed)
    now = datetime.fromtimestamp(clock(), UTC)
    w = watcher(tmp_path, clock=lambda: now)
    monkeypatch.setattr(stock_watch, "for_scanner", lambda _: w)

    def missing(*_):
        raise RuntimeError("Options down")

    s._contract = missing
    s.scan(DAY, SimpleNamespace(open_at=at(9, 30), close_at=at(16, 0)))
    assert len(w.store.records("stock_alert")) == 1
    assert rows(engine)[0] == []
    assert (
        w.store.records("stock_alert")[0]["trade_eligibility"]["status"]
        == "not_evaluated"
    )


def test_mail_checks_expiry_after_prior_slow_send(engine, monkeypatch, tmp_path):
    from app.engine import stock_watch

    monkeypatch.setattr(
        stock_watch.scanner_settings,
        "read_settings",
        lambda _: {"symbols": ["NBIS", "MU"], "revision": 1},
    )
    clock = [NOW + timedelta(minutes=9, seconds=59)]
    sent = []

    def mail(subject, body):
        sent.append(subject)
        clock[0] += timedelta(seconds=5)
        return "fixture"

    w = watcher(tmp_path, clock=lambda: clock[0], mail=mail)
    for symbol in ("NBIS", "MU"):
        w.capture(alert(symbol=symbol, selected_symbols=["NBIS", "MU"]))
    w.send(SimpleNamespace(engine=engine), NOW.date())
    assert len(sent) == 1
    assert "NBIS" in sent[0]


def test_email_to_scoped_jo_tools_to_phone_fixture_flow(
    harness, engine, tmp_path, monkeypatch
):
    from app.engine import stock_watch

    mail = []
    phone = []
    monkeypatch.setattr(
        stock_watch.scanner_settings,
        "read_settings",
        lambda _: {"symbols": ["NBIS"], "revision": 1},
    )
    w = watcher(
        tmp_path,
        mail=lambda subject, body: mail.append((subject, body)),
        push=lambda title, body: (
            phone.append((title, body)) or "accepted-phone-fixture"
        ),
    )
    p = w.capture(alert())
    w.send(SimpleNamespace(engine=engine), NOW.date())
    w.send(SimpleNamespace(engine=engine), NOW.date())
    assert len(mail) == 1 and mail[0][0].startswith("TJ Setup: STOCK NBIS ")
    assert mail[0][1] == f"Stock alert ID: {p['alert_id']}\n"
    harness.configure(
        market_watch_snapshots_dir=str(w.directory),
        market_watch_outbox_dir=str(w.outbox),
    )
    with TestClient(harness.server(now=NOW).streamable_http_app()) as client:
        inp = call(
            client,
            "stock_alert",
            {"alert_id": p["alert_id"]},
            harness.token(scope=SCOPE),
        )["structuredContent"]
        assert (
            inp["advisory_only"]
            and inp["alert"]["trade_eligibility"]["status"] == "not_evaluated"
        )
        r = call(
            client,
            "stock_alert_submit",
            {
                "alert_id": p["alert_id"],
                "stance": "watch",
                "summary": "A material rebound warrants attention",
                "invalidation": "Failure below the frozen reference",
                "notify": True,
            },
            harness.token(scope=SCOPE),
        )["structuredContent"]
    w.ingest_and_deliver(["NBIS"])
    w.ingest_and_deliver(["NBIS"])
    assert len(phone) == 1 and r["review_id"] in phone[0][1]
    assert (
        w.store.records("stock_push_attempt")[-1]["transport_receipt_id"]
        == "accepted-phone-fixture"
    )
    with sqlite3.connect(
        json.loads(harness.config_path.read_text())["ledger_file"]
    ) as db:
        assert db.execute("SELECT count(*) FROM shadow_decision").fetchone()[0] == 0


def test_selection_guard_cooldown_and_recovery_are_recorded(
    engine, tmp_path, monkeypatch
):
    from app.engine import stock_watch

    selection = {"symbols": ["NBIS"], "revision": 1}
    mail = []
    monkeypatch.setattr(
        stock_watch.scanner_settings, "read_settings", lambda _: selection
    )
    w = watcher(tmp_path, mail=lambda *args: mail.append(args))
    p = w.capture(alert())
    selection["symbols"] = []
    w.send(SimpleNamespace(engine=engine), NOW.date())
    assert mail == []
    selection["symbols"] = ["NBIS"]
    w.guard = lambda _: True
    w.send(SimpleNamespace(engine=engine), NOW.date())
    assert (
        mail == []
        and w.store.records("stock_status")[-1]["reason"] == "shadow_setup_guard"
    )
    w.guard = lambda _: False
    (w.directory / f"stock-{p['alert_id']}.json").unlink()
    w.send(SimpleNamespace(engine=engine), NOW.date())
    assert len(mail) == 1 and (w.directory / f"stock-{p['alert_id']}.json").exists()
    w.capture(alert())
    w.send(SimpleNamespace(engine=engine), NOW.date())
    assert (
        len(mail) == 1 and w.store.records("stock_status")[-1]["reason"] == "cooldown"
    )


def test_early_wakes_cannot_exhaust_late_selected_tickers(engine, tmp_path, monkeypatch):
    from app.engine import stock_watch

    symbols = ["NBIS", "AAPL", "AMD", "MRVL", "MU", "CRDO"]
    monkeypatch.setattr(stock_watch.scanner_settings, "read_settings",
                        lambda _: {"symbols": symbols, "revision": 2})
    now = NOW
    sent = []
    w = watcher(tmp_path, clock=lambda: now, mail=lambda subject, _: sent.append(subject))
    scanner = SimpleNamespace(engine=engine)
    # More than four wakes for each early ticker, and fifteen shared wakes.
    for slot in range(5):
        now = NOW + timedelta(minutes=31 * slot)
        for symbol in symbols[:3]:
            w.capture(alert(now, symbol=symbol, selected_symbols=symbols))
        w.send(scanner, now.date())
    assert len(sent) == 15
    now = NOW.replace(hour=19, minute=55)  # 15:55 ET, after the paper cutoff.
    for symbol in symbols[3:]:
        w.capture(alert(now, symbol=symbol, selected_symbols=symbols))
    w.send(scanner, now.date())
    assert len(sent) == 18
    assert all(any(f"STOCK {symbol} " in subject for subject in sent)
               for symbol in symbols[3:])
    # The same store after a restart must not resend these accepted inputs.
    restarted = StockWatcher(w.store, w.directory, w.outbox, clock=lambda: now,
                             mail=lambda *_: pytest.fail("duplicate wake"))
    restarted.send(scanner, now.date())
    assert not any(s["reason"] == "wake_budget" for s in w.store.records("stock_status"))


def test_observations_record_actual_selected_checks_gaps_and_close(engine, tmp_path, monkeypatch):
    from app.engine import stock_watch

    now = NOW.replace(hour=19, minute=58)
    symbols = ["MRVL", "MU", "CRDO"]
    monkeypatch.setattr(stock_watch.scanner_settings, "read_settings",
                        lambda _: {"symbols": symbols, "revision": 3})
    scanner = SimpleNamespace(engine=engine, _pass_minutes={}, _daily_atr=lambda *_: 2.0)

    def read(symbol, day):
        if symbol == "MU":
            raise OSError("source unavailable")
        bars = minutes(now)
        scanner._pass_minutes[symbol] = (bars, now.timestamp() - (300 if symbol == "CRDO" else 0))
        return bars

    scanner._minutes = read
    w = watcher(tmp_path, clock=lambda: now)
    session = SimpleNamespace(open_at=now.replace(hour=13, minute=30).timestamp(),
                              close_at=now.replace(hour=20, minute=0).timestamp())
    w.observe(scanner, now.date(), session)
    w.observe(scanner, now.date(), session)
    rows = w.store.records("stock_observation")
    assert {r["symbol"]: r["outcome"] for r in rows} == {
        "MRVL": "captured", "MU": "source_unavailable", "CRDO": "stale_source"}
    assert all(r["selection_revision"] == 3 and r["checked_at"] == r["started_at"] for r in rows)
    now += timedelta(minutes=1)
    scanner._pass_minutes.clear()
    w.observe(scanner, now.date(), session)
    assert len(w.store.records("stock_observation")) == 6
    now += timedelta(minutes=1)  # At the actual exchange close, no extra pass.
    scanner._pass_minutes.clear()
    w.observe(scanner, now.date(), session)
    assert len(w.store.records("stock_observation")) == 6


def test_monitor_runs_after_paper_cutoff_and_uses_only_selected_symbols(
    engine, tmp_path, monkeypatch
):
    from app.engine import stock_watch

    now = NOW.replace(hour=19, minute=15, second=30)  # 15:15 ET
    selection = {"symbols": ["NBIS"], "revision": 7}
    monkeypatch.setattr(
        stock_watch.scanner_settings, "read_settings", lambda _: selection
    )
    requested = []
    bars = minutes(now)
    s = SimpleNamespace(engine=engine, _pass_minutes={}, _daily_atr=lambda *_: 2.0)

    def read(symbol, day):
        requested.append(symbol)
        s._pass_minutes[symbol] = (bars, now.timestamp())
        return bars

    s._minutes = read
    w = watcher(tmp_path, clock=lambda: now)
    session = SimpleNamespace(
        open_at=now.replace(hour=13, minute=30).timestamp(),
        close_at=now.replace(hour=20, minute=0).timestamp(),
    )
    w.observe(s, now.date(), session)
    w.observe(s, now.date(), session)
    assert requested == ["NBIS"]
    assert (
        len(w.store.records("stock_alert")) == 1
        and w.store.records("stock_alert")[0]["selection_revision"] == 7
    )
    selection["symbols"] = []
    w.last_minute = None
    w.observe(s, now.date(), session)
    assert requested == ["NBIS"]


def test_unknown_transport_is_terminal_and_removed_ticker_cannot_push(tmp_path):
    w = watcher(tmp_path, push=lambda *_: pytest.fail("Must not resend"))
    p = w.capture(alert())
    ledger = StockWatchLedger(Ledger(tmp_path / "ledger.db"))
    ledger.serve(ACTOR, p, NOW)
    r = ledger.submit(ACTOR, p, "watch", "A rebound", "Below low", True, lambda: NOW)
    write_review(w.outbox, r)
    w.ingest_and_deliver([])
    assert w.store.records("stock_push_attempt") == []
    assert w.store.records("stock_status")[-1]["reason"] == "selection_removed"
    w.runner._attempt(
        "stock_push_attempt",
        NOW,
        p["session_date"],
        "review_id",
        r["review_id"],
        1,
        "sending",
        "push",
    )
    w.ingest_and_deliver(["NBIS"])
    w.ingest_and_deliver(["NBIS"])
    assert [a["result"] for a in w.store.records("stock_push_attempt")] == [
        "sending",
        "unknown",
    ]


def test_stock_only_enable_never_enables_option_selection_or_paper_management(
    engine, tmp_path, monkeypatch
):
    from tests.test_setup_scanner import scanner, breakout_day, at, rows
    from app.engine import stock_watch

    s, clock = scanner(engine, at(9, 50, 35))
    breakout_day(s.feed)
    s.paper_enabled = False
    w = watcher(
        tmp_path,
        clock=lambda: datetime.fromtimestamp(clock(), UTC),
        mail=lambda *_: None,
    )
    monkeypatch.setattr(stock_watch, "for_scanner", lambda _: w)
    s.manage = lambda *_: pytest.fail("Paper management enabled by stock watch")
    s._contract = lambda *_: pytest.fail("Option selection enabled by stock watch")
    s.shadow_exchange_pass = lambda *_: pytest.fail(
        "Paper shadow changed by stock watch"
    )
    s.run()
    assert rows(engine)[0] == []
    assert w.store.records("stock_alert")
