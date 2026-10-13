"""Setup scanner S1: the pure rules, and the watcher's candidates, paper trades and restarts."""

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.database import get_session
from app.engine import scanner_rules as rules
from app.engine import shadow_exchange
from app.engine import setup_scanner
from app.engine.options_models import OptionContract
from app.models import Account, Fill, Trade, ScannerCandidate, ScannerEvent
from app.routers import scanner as routes

ET = ZoneInfo("America/New_York")
DAY = date(2026, 10, 7)  # a Wednesday


def at(hour, minute, second=0, day=DAY):
    return int(datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=ET).timestamp())


OPEN, CLOSE = at(9, 30), at(16, 0)


def bar(start_minute, o, h, lo, c, v=100, vwap=100.0, ema9=100.0):
    start = OPEN + start_minute * 60
    return {"start": start, "end": start + 300, "open": o, "high": h, "low": lo, "close": c, "volume": v, "vwap": vwap, "ema9": ema9}


def contract(side="call", delta=0.35, bid=1.0, ask=1.05, oi=1000, volume=500, strike=101.0, expiration=DAY, multiplier=100):
    letter = "C" if side == "call" else "P"
    return OptionContract(f"SPY{expiration:%y%m%d}{letter}{int(strike * 1000):08d}", "SPY", "SPY", expiration, side, strike,
                          multiplier, bid, ask, None, None, None, volume, oi, None, None, None, None, None,
                          delta if side == "call" else -delta, None, None, None, None)


# ------------------------------------------------------------------ rules


def test_five_minute_bars_build_session_vwap_and_skip_extended_hours():
    minutes = [{"time": OPEN - 60, "end_time": OPEN, "open": 50, "high": 50, "low": 50, "close": 50, "volume": 1000}]
    minutes += [{"time": OPEN + i * 60, "end_time": OPEN + i * 60 + 60, "open": 100 + i, "high": 100 + i, "low": 100 + i,
                 "close": 100 + i, "volume": 100} for i in range(10)]
    bars = rules.five_minute_bars(minutes, OPEN, CLOSE)
    assert [b["start"] for b in bars] == [OPEN, OPEN + 300]
    assert bars[0]["open"] == 100 and bars[0]["close"] == 104 and bars[0]["high"] == 104 and bars[0]["volume"] == 500
    assert bars[0]["vwap"] == pytest.approx(102)  # the premarket print is excluded
    assert bars[1]["vwap"] == pytest.approx(104.5)


def opening(price=100.0, v=100):
    return [bar(m, price, price + 0.5, price - 0.5, price, v) for m in (0, 5, 10)]


def test_opening_range_break_needs_vwap_volume_and_the_1045_cutoff():
    last = at(15, 0)
    good = opening() + [bar(15, 100.2, 100.9, 100.1, 100.8, v=150)]
    [signal] = rules.scan(good, 2.0, OPEN, last, set())
    assert (signal["setup"], signal["direction"], signal["bar_end"]) == ("orb", "long", at(9, 50))
    assert signal["stop"] == pytest.approx(100.0) and signal["target"] == pytest.approx(102.4)
    assert rules.scan(opening() + [bar(15, 100.2, 100.9, 100.1, 100.8, v=50)], 2.0, OPEN, last, set()) == []
    late = opening() + [bar(m, 100, 100.4, 99.9, 100.2) for m in range(15, 75, 5)] + [bar(75, 100.2, 100.9, 100.1, 100.8, v=150)]
    assert rules.scan(late, 2.0, OPEN, last, set()) == []  # the first break closed at 10:50
    # Only the first close above the range counts, even when it failed a filter.
    again = opening() + [bar(15, 100.2, 100.9, 100.1, 100.8, v=50), bar(20, 100.8, 101.0, 100.7, 100.9, v=150)]
    assert rules.scan(again, 2.0, OPEN, last, set()) == []


def fade_day():
    # ATR 2: stretched means a low at or below VWAP - 0.7.
    return opening() + [bar(15, 99.8, 99.9, 99.6, 99.7), bar(20, 99.6, 99.3, 99.2, 99.25),
                        bar(25, 99.3, 99.5, 99.3, 99.45)]


def test_fade_turns_back_toward_vwap_with_reward_at_least_risk():
    [signal] = rules.scan(fade_day(), 2.0, OPEN, at(15, 0), set())
    assert (signal["setup"], signal["direction"], signal["bar_end"]) == ("fade", "long", at(10, 0))
    assert signal["stop"] == pytest.approx(99.1) and signal["target"] == pytest.approx(100.0)
    assert signal["facts"]["daily_atr14"] == 2.0 and signal["flags"] == []


def test_a_saved_fade_resets_the_stretch_and_two_saved_fades_end_the_day():
    day = fade_day() + [bar(30, 99.45, 99.6, 99.45, 99.55)]
    saved = {("fade", at(10, 0))}
    assert [s["bar_end"] for s in rules.scan(day, 2.0, OPEN, at(15, 0), saved)] == [at(10, 0)]
    unsaved = rules.scan(day, 2.0, OPEN, at(15, 0), set())
    assert [s["bar_end"] for s in unsaved] == [at(10, 0), at(10, 5)]


def test_short_fade_flags_an_extended_put():
    day = opening() + [bar(15, 100.2, 101.0, 100.2, 100.9, v=50), bar(20, 100.9, 101.0, 100.85, 100.9, ema9=100.0),
                       bar(25, 100.85, 100.85, 100.6, 100.7, ema9=101.6)]
    [signal] = rules.scan(day, 1.0, OPEN, at(15, 0), set())
    assert (signal["setup"], signal["direction"]) == ("fade", "short")
    assert signal["flags"] == ["put_extended"]  # already 0.9% below its EMA9


def test_nothing_after_the_last_bar_end():
    assert rules.scan(fade_day(), 2.0, OPEN, at(9, 55), set()) == []


def test_contract_choice_and_expiration_rule():
    assert rules.pick_expiration([date(2026, 10, 8), date(2026, 10, 9), date(2026, 10, 16)], DAY) is None  # only 1-2 or 9 days
    assert rules.pick_expiration([date(2026, 10, 9), date(2026, 10, 12)], DAY) == date(2026, 10, 12)
    assert rules.pick_expiration([DAY, date(2026, 10, 12)], DAY) == DAY
    chosen = rules.choose_contract([
        contract(delta=0.30, strike=102), contract(delta=0.36, strike=101), contract(delta=0.35, oi=100, strike=100),
        contract(delta=0.35, bid=1.0, ask=1.3, strike=99), contract(side="put", delta=0.35, strike=98),
    ], "long")
    assert chosen["strike"] == 101 and chosen["delta"] == 0.36
    assert rules.choose_contract([contract(delta=0.5), contract(multiplier=None)], "long") is None
    assert rules.choose_contract([contract(side="put", delta=0.3)], "short")["option_type"] == "put"


def minute(t, low, high):
    return {"time": t, "end_time": t + 60, "open": low, "high": high, "low": low, "close": low, "volume": 1}


def test_exit_condition_stop_first_and_clock_exits():
    entry = at(10, 0, 20)
    bars = [minute(at(10, 0), 90, 110), minute(at(10, 1), 99.0, 103.0)]  # the entry minute itself is not judged
    found = rules.exit_condition("long", 99.0, 103.0, bars, entry, entry + 3600, at(15, 45), at(10, 3), 30)
    assert found["reason"] == "stop" and found["condition_at"] == at(10, 2)
    assert rules.exit_condition("long", 99.0, 103.0, bars[:1], entry, entry + 3600, at(15, 45), at(10, 3), 30) is None
    assert rules.exit_condition("long", 99.0, 103.0, [], entry, entry + 3600, at(15, 45), entry + 3600, 30)["reason"] == "time_stop"
    found = rules.exit_condition("short", 101.0, 99.0, [minute(at(10, 1), 98.5, 100)], entry, entry + 3600, at(15, 45), at(10, 3), 30)
    assert found["reason"] == "target"


def test_result_is_ask_in_bid_out_with_commission():
    out = rules.result({"ask": 1.05, "bid": 1.0}, {"bid": 1.5, "ask": 1.6}, 100)
    assert out["pnl"] == pytest.approx(43.7)
    assert out["pnl_2x_spread"] == pytest.approx((1.45 - 1.075) * 100 - 1.3)
    assert out["return_on_premium"] == pytest.approx(43.7 / 105.65, abs=1e-4)


def test_params_hash_is_stable():
    assert rules.PARAMS["fade"]["stretch_atr"] == 0.35 and len(rules.PARAMS_HASH) == 64


# ------------------------------------------------------------------ the watcher


class Calendar:
    def hours(self, day):
        return {"date": day.isoformat(), "status": "open", "open": 570, "close": 960}


class Feed:
    def __init__(self):
        self.minutes = []

    def add(self, first, last, low, high, volume=100):
        self.minutes += [(t, low, high, volume) for t in range(first, last, 60)]

    def read(self, path, params, ttl):
        if path == "/v1/markets/history":
            days = [{"date": f"2026-09-{d:02d}", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1} for d in range(10, 30)]
            return {"history": {"day": days}}, 0, None
        rows = [{"timestamp": t, "open": low, "high": high, "low": low, "close": high, "volume": v} for t, low, high, v in self.minutes]
        return {"series": {"data": rows}}, 0, None


class Options:
    def __init__(self):
        self.chains = 0

    def expirations(self, symbol):
        return [DAY]

    def chain(self, symbol, expiration):
        self.chains += 1
        return SimpleNamespace(contracts=(contract(),))


class Quotes:
    def __init__(self):
        self.next = (1.0, 1.05)
        self.updated_ms = 10**15  # both sides updated after any decision in these tests

    def __call__(self, occ):
        if self.next is None:
            return None
        bid, ask = self.next
        return SimpleNamespace(bid=bid, ask=ask, bid_date=self.updated_ms, ask_date=self.updated_ms)


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(rules, "UNIVERSE", ("SPY",))
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


def breakout_day(feed):
    feed.add(OPEN, at(9, 45), 99.5, 100.5)  # opening range 99.5 - 100.5, ATR 2
    feed.add(at(9, 45), at(9, 50), 100.4, 100.9, volume=150)  # closes 100.9 above the range and VWAP


def scanner(engine, now, quotes=None, options=None):
    clock = Clock(now)
    return setup_scanner.SetupScanner(engine, Feed(), Calendar(), options or Options(), clock, quote=quotes or Quotes()), clock


def rows(engine):
    with Session(engine) as db:
        cands = db.exec(select(ScannerCandidate)).all()
        events = db.exec(select(ScannerEvent)).all()
        return cands, {e.event_type: json.loads(e.data_json) for e in events}


def test_breakout_is_saved_entered_and_exits_at_target(engine):
    watch, clock = scanner(engine, at(9, 50, 35))
    breakout_day(watch.feed)
    watch.run()
    cands, events = rows(engine)
    assert len(cands) == 1 and cands[0].setup == "orb" and cands[0].stop == pytest.approx(100.0)
    assert json.loads(cands[0].contract_json)["strike"] == 101.0 and events["entry"]["ask"] == 1.05

    watch.run()  # the same bar again
    again, _ = scanner(engine, at(9, 50, 50))  # and a restarted process
    again.feed = watch.feed
    again.run()
    assert len(rows(engine)[0]) == 1

    target = cands[0].target
    watch.feed.add(at(9, 51), at(9, 52), 100.9, target + 0.1)
    watch.quote.next = (1.5, 1.6)
    clock.now = at(9, 52, 40)
    watch.run()
    _, events = rows(engine)
    assert events["exit_intent"]["reason"] == "target" and events["exit"]["pnl"] == pytest.approx(43.7)

    with Session(engine) as db:
        view = setup_scanner.day_view(db, DAY, [])
    assert view["totals"]["resolved"] == 1 and view["candidates"][0]["status"] == "exit"


def test_no_quote_for_two_minutes_is_unresolved(engine):
    quotes = Quotes()
    quotes.next = None
    watch, clock = scanner(engine, at(9, 50, 35), quotes=quotes)
    breakout_day(watch.feed)
    watch.run()
    assert "entry" not in rows(engine)[1]
    clock.now = at(9, 52, 40)
    watch.run()
    assert rows(engine)[1]["unresolved"]["reason"] == "no entry quote within two minutes"


@pytest.mark.parametrize("failure", ["rate_limit", "transport"])
def test_default_quote_does_not_sleep_and_recovers_on_next_pass(engine, monkeypatch, failure):
    calls = []

    def post(_url, *, data, headers, timeout):
        calls.append(data["symbols"])
        assert timeout == setup_scanner.tradier.REQUEST_TIMEOUT_SECONDS
        if len(calls) == 1:
            if failure == "transport":
                raise httpx.ReadTimeout("quote timed out")
            return httpx.Response(429, headers={"Retry-After": "120"})
        return httpx.Response(200, json={"quotes": {"quote": {
            "symbol": data["symbols"], "bid": 1.0, "ask": 1.05,
            "bid_date": at(9, 51) * 1000, "ask_date": at(9, 51) * 1000,
        }}})

    def refuse_sleep(_seconds):
        pytest.fail("Scanner quote reads must not sleep between attempts")

    monkeypatch.setattr(setup_scanner.tradier, "TRADIER_API_KEY", "test-token")
    monkeypatch.setattr(setup_scanner.tradier.httpx, "post", post)
    monkeypatch.setattr(setup_scanner.tradier.time, "sleep", refuse_sleep)
    clock = Clock(at(9, 50, 35))
    watch = setup_scanner.SetupScanner(engine, Feed(), Calendar(), Options(), clock)
    breakout_day(watch.feed)

    watch.run()
    assert len(calls) == 1
    assert len(rows(engine)[0]) == 1
    assert "entry" not in rows(engine)[1] and "unresolved" not in rows(engine)[1]

    clock.now = at(9, 51, 5)
    watch.run()
    assert len(calls) == 2
    entry = rows(engine)[1]["entry"]
    assert entry["ask"] == 1.05 and entry["bid"] == 1.0
    assert entry["ask_time"] == at(9, 51) * 1000


def test_a_quote_that_arrives_after_the_window_is_never_used(engine):
    quotes = Quotes()
    quotes.next = None
    watch, clock = scanner(engine, at(9, 50, 35), quotes=quotes)
    breakout_day(watch.feed)
    watch.run()
    quotes.next = (1.0, 1.05)  # the provider recovers half an hour later
    clock.now = at(10, 20)
    watch.run()
    events = rows(engine)[1]
    assert "entry" not in events and events["unresolved"]["reason"] == "no entry quote within two minutes"


def test_a_quote_not_updated_since_the_decision_is_not_a_fill(engine):
    quotes = Quotes()
    quotes.updated_ms = (at(9, 50, 0)) * 1000  # last changed before the setup was saved
    watch, clock = scanner(engine, at(9, 50, 35), quotes=quotes)
    breakout_day(watch.feed)
    watch.run()
    assert "entry" not in rows(engine)[1]
    quotes.updated_ms = at(9, 51) * 1000
    clock.now = at(9, 51, 5)
    watch.run()
    assert rows(engine)[1]["entry"]["ask"] == 1.05


def test_an_exit_quote_after_the_window_is_unresolved(engine):
    quotes = Quotes()
    watch, clock = scanner(engine, at(9, 50, 35), quotes=quotes)
    breakout_day(watch.feed)
    watch.run()
    watch.feed.add(at(9, 51), at(9, 52), 100.9, rows(engine)[0][0].target + 0.1)
    quotes.next = None
    clock.now = at(9, 52, 40)
    watch.run()
    assert "exit_intent" in rows(engine)[1]
    quotes.next = (1.5, 1.6)
    clock.now = at(10, 30)
    watch.run()
    events = rows(engine)[1]
    assert "exit" not in events and events["unresolved"]["reason"] == "no exit quote within two minutes"


def test_an_exit_noticed_late_is_unresolved_never_priced(engine):
    watch, clock = scanner(engine, at(9, 50, 35))
    breakout_day(watch.feed)
    watch.run()
    clock.now = at(11, 0)  # the 60-minute time stop passed at 10:50:35 while nothing was watching
    watch.run()
    events = rows(engine)[1]
    assert "exit" not in events and events["unresolved"]["reason"].startswith("monitoring gap")


def test_no_contract_is_saved_without_a_trade(engine):
    options = Options()
    options.expirations = lambda symbol: [date(2026, 10, 8)]
    watch, _ = scanner(engine, at(9, 50, 35), options=options)
    breakout_day(watch.feed)
    watch.run()
    cands, events = rows(engine)
    assert cands[0].contract_json is None and events == {}
    assert json.loads(cands[0].facts_json)["contract_note"].startswith("no expiration")


def test_a_bar_noticed_late_is_skipped(engine):
    watch, _ = scanner(engine, at(9, 53, 0))
    breakout_day(watch.feed)
    watch.run()
    assert rows(engine)[0] == []


def test_day_route_marks_a_sixth_entry(engine):
    watch, _ = scanner(engine, at(9, 50, 35))
    breakout_day(watch.feed)
    watch.run()
    with Session(engine) as db:
        account = Account(name="Roth", type="roth_ira", last4="0000")
        db.add(account)
        for i in range(5):
            db.add(Trade(account_id=account.id, ticker="SPY", instrument_type="option", contracts=1, avg_entry_premium=1.0,
                         total_premium_paid=100.0, opened_at=datetime(2026, 10, 7, 9, 31 + i)))
        # A sixth fill of an already-open trade is not another entry.
        db.add(Fill(account_id=account.id, ticker="SPY", instrument_type="option", side="buy_to_open", contracts=1, price=1.0,
                    executed_at=datetime(2026, 10, 7, 9, 40), raw_email_id="scale-in"))
        db.commit()
    app = FastAPI()
    app.include_router(routes.router, prefix="/scanner")
    app.dependency_overrides[get_session] = lambda: Session(engine)
    body = TestClient(app).get("/scanner/day", params={"day": "2026-10-07"}).json()
    assert body["candidates"][0]["flags"] == ["sixth_plus_entry"] and body["scanner_version"] == "s1-v1"
    assert TestClient(app).get("/scanner/day", params={"day": "nope"}).status_code == 422


# ------------------------------------------------------------------ setup emails


def mail_env(monkeypatch):
    monkeypatch.setenv("SCANNER_EMAIL_TO", "owner+tjsetups@example.com")
    monkeypatch.setenv("SCANNER_SMTP_USER", "owner@example.com")
    monkeypatch.setenv("SCANNER_SMTP_PASSWORD", "test-only")


def test_each_setup_is_emailed_once_with_the_pre_trade_check_inputs(engine, monkeypatch):
    sent = []
    mail_env(monkeypatch)
    monkeypatch.setattr(setup_scanner.scanner_mail, "send", lambda title, body: sent.append((title, body)))
    watch, clock = scanner(engine, at(9, 50, 35))
    breakout_day(watch.feed)
    watch.run()
    watch.run()
    assert len(sent) == 1
    title, body = sent[0]
    assert title == "TJ Setup: SPY CALL opening-range break 09:50 ET"
    inputs = json.loads(next(line for line in body.splitlines() if line.startswith("{")))
    candidate = rows(engine)[0][0]
    assert inputs == {"ticker": "SPY", "side": "long", "instrument": "option", "horizon": "intraday", "entry": 100.9,
                      "stop": candidate.stop, "option_type": "call", "expiration": "2026-10-07", "strike": 101.0,
                      "free_text": f"scanner s1-v1 orb setup {candidate.id}", "operation_id": str(candidate.id)}
    assert rows(engine)[1]["email"]["status"] == "sent"


def test_emails_are_off_without_an_address_and_never_sent_stale(engine, monkeypatch):
    sent = []
    mail_env(monkeypatch)
    monkeypatch.delenv("SCANNER_EMAIL_TO")
    monkeypatch.setattr(setup_scanner.scanner_mail, "send", lambda title, body: sent.append(title))
    watch, clock = scanner(engine, at(9, 50, 35))
    breakout_day(watch.feed)
    watch.run()
    assert sent == [] and "email" not in rows(engine)[1]

    monkeypatch.setenv("SCANNER_EMAIL_TO", "owner@example.com")
    clock.now = at(10, 5)  # after the setup's ten-minute expiry
    watch.run()
    assert sent == [] and rows(engine)[1]["email"]["status"] == "expired"


def test_a_failed_send_is_retried_while_fresh(engine, monkeypatch):
    calls = []

    def flaky(title, body):
        calls.append(title)
        if len(calls) == 1:
            raise setup_scanner.scanner_mail.MailError("down")

    mail_env(monkeypatch)
    monkeypatch.setattr(setup_scanner.scanner_mail, "send", flaky)
    watch, clock = scanner(engine, at(9, 50, 35))
    breakout_day(watch.feed)
    watch.run()
    assert "email" not in rows(engine)[1]
    clock.now = at(9, 51)
    watch.run()
    assert len(calls) == 2 and rows(engine)[1]["email"]["status"] == "sent"


def _decision_file(path, candidate, decision="take", timing="on_time", committed_at=None, **changes):
    path.mkdir(parents=True, exist_ok=True)
    setup_hash = shadow_exchange.setup_payload(candidate)["content_sha256"]
    payload = {"format": "shadow-decision-v1", "decision_id": "shd_test", "candidate_id": str(candidate.id),
               "actor": "fixture", "decision": decision, "reason": "fixture reason",
               "committed_at": committed_at or shadow_exchange.utc_z(candidate.detected_at), "timing": timing,
               "clean_order": True, "labels": ["informed-by-history", "independence-unverified"],
               "setup_sha256": setup_hash}
    payload.update(changes)
    payload["content_sha256"] = shadow_exchange.digest(payload)
    (path / f"decision-{candidate.id}.json").write_bytes(shadow_exchange.canonical(payload))
    return payload


def _candidate(engine):
    return rows(engine)[0][0]


def test_shadow_setup_round_trip_is_content_addressed(engine, tmp_path):
    watch, _ = scanner(engine, at(9, 50, 35))
    breakout_day(watch.feed)
    watch.run()
    candidate = _candidate(engine)
    payload = shadow_exchange.write_setup(tmp_path, candidate)
    path = tmp_path / f"setup-{candidate.id}.json"
    written = json.loads(path.read_text())
    assert written == payload and written["content_sha256"] == shadow_exchange.digest({k: v for k, v in written.items() if k != "content_sha256"})
    assert path.stat().st_mode & 0o777 == 0o640


def test_expired_candidate_is_not_handed_off(engine, monkeypatch, tmp_path):
    watch, clock = scanner(engine, at(9, 50, 35))
    breakout_day(watch.feed)
    watch.run()
    candidate = _candidate(engine)
    setups = tmp_path / "setups"
    monkeypatch.setenv("SHADOW_SETUPS_DIR", str(setups))
    clock.now = int(candidate.expires_at.replace(tzinfo=ZoneInfo("UTC")).timestamp())
    watch.shadow_exchange_pass(clock.now, DAY, None)
    assert rows(engine)[1]["shadow_handoff"]["status"] == "expired"
    assert not (setups / f"setup-{candidate.id}.json").exists()


def test_open_shadow_trade_becomes_unresolved_after_next_session(engine):
    watch, clock = scanner(engine, at(9, 50, 35))
    breakout_day(watch.feed)
    watch.run()
    candidate = _candidate(engine)
    watch._store(candidate, "shadow_decision", clock.now, {"decision": "take", "timing": "on_time"})
    watch._store(candidate, "shadow_entry", clock.now, {"ask": 1.05, "bid": 1.0})

    watch.shadow_exchange_pass(clock.now, DAY + timedelta(days=1), None)

    assert rows(engine)[1]["shadow_unresolved"]["reason"] == "session ended before the trade finished"


def test_no_response_starts_at_the_exact_expiry_time(engine):
    watch, _ = scanner(engine, at(9, 50, 35))
    breakout_day(watch.feed)
    watch.run()
    candidate = _candidate(engine)
    expiry = setup_scanner._epoch(candidate.expires_at)
    assert setup_scanner.shadow_status_of(candidate, {"shadow_handoff": {"status": "written"}}, now=expiry - 1) == "awaiting_decision"
    assert setup_scanner.shadow_status_of(candidate, {"shadow_handoff": {"status": "written"}}, now=expiry) == "no_response"


def test_shadow_view_separates_decision_rationale_from_unresolved_reason():
    labels = ["informed-by-history", "independence-unverified"]
    mixed = setup_scanner._shadow_view({
        "shadow_decision": {"decision": "take", "reason": "setup rationale", "labels": labels},
        "shadow_unresolved": {"reason": "decision export failed"},
    }, "unresolved")
    assert mixed["reason"] == "setup rationale"
    assert mixed["unresolved_reason"] == "decision export failed"
    assert mixed["labels"] == labels

    no_response = setup_scanner._shadow_view({}, "no_response")
    assert no_response["reason"] is None and no_response["unresolved_reason"] is None
    assert no_response["labels"] == labels

    rejected = setup_scanner._shadow_view({"shadow_unresolved": {"reason": "invalid decision export"}}, "unresolved")
    assert rejected["reason"] is None and rejected["unresolved_reason"] == "invalid decision export"
    assert rejected["labels"] == labels


def test_scorecard_counts_mixed_unresolved_and_uses_setup_baseline(engine):
    watch, _ = scanner(engine, at(9, 50, 35))
    breakout_day(watch.feed)
    watch.run()
    candidate = _candidate(engine)
    candidate.expires_at = datetime(2020, 1, 1, tzinfo=ZoneInfo("UTC"))
    take = {"shadow_handoff": {"status": "written"}, "shadow_decision": {"decision": "take", "timing": "on_time"}}
    mixed = {**take, "shadow_unresolved": {"reason": "entry was not priced"}, "exit": {"pnl": 10.0}}

    score = setup_scanner._shadow_scorecard([(candidate, mixed), *((candidate, take) for _ in range(28)), (candidate, {"shadow_handoff": {"status": "written"}})])

    assert score["setups"] == 30 and score["decisions"] == 29 and score["take"] == 29
    assert score["unresolved"] == 1 and score["no_response"] == 1
    assert score["rules_priced"] == 1 and score["rules_pnl"] == 10.0
    assert score["group_evidence"] == {"rules": "sufficient count", "takes": "not enough", "skipped": "not enough"}


def test_tampered_shadow_decision_is_unresolved(engine, monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_SETUPS_DIR", str(tmp_path / "setups"))
    monkeypatch.setenv("SHADOW_OUTBOX_DIR", str(tmp_path / "outbox"))
    watch, clock = scanner(engine, at(9, 50, 35))
    breakout_day(watch.feed)
    watch.run()
    candidate = _candidate(engine)
    value = _decision_file(tmp_path / "outbox", candidate)
    value["reason"] = "tampered after hashing"
    (tmp_path / "outbox" / f"decision-{candidate.id}.json").write_bytes(shadow_exchange.canonical(value))
    clock.now += 10
    watch.run()
    events = rows(engine)[1]
    assert events["shadow_unresolved"]["reason"] == "decision content hash is invalid"
    assert "shadow_entry" not in events


def test_decision_with_another_setup_hash_is_unresolved(engine, monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_SETUPS_DIR", str(tmp_path / "setups"))
    monkeypatch.setenv("SHADOW_OUTBOX_DIR", str(tmp_path / "outbox"))
    watch, clock = scanner(engine, at(9, 50, 35))
    breakout_day(watch.feed)
    watch.run()
    candidate = _candidate(engine)
    _decision_file(tmp_path / "outbox", candidate, setup_sha256="0" * 64)
    clock.now += 10
    watch.run()
    assert rows(engine)[1]["shadow_unresolved"]["reason"] == "decision setup hash does not match the saved candidate"


@pytest.mark.parametrize("decision,timing,expected", [("skip", "on_time", "skipped"), ("take", "late", "late")])
def test_skip_and_late_take_never_price_shadow_trade(engine, monkeypatch, tmp_path, decision, timing, expected):
    monkeypatch.setenv("SHADOW_SETUPS_DIR", str(tmp_path / "setups"))
    monkeypatch.setenv("SHADOW_OUTBOX_DIR", str(tmp_path / "outbox"))
    watch, clock = scanner(engine, at(9, 50, 35))
    breakout_day(watch.feed)
    watch.run()
    candidate = _candidate(engine)
    _decision_file(tmp_path / "outbox", candidate, decision=decision, timing=timing)
    clock.now += 10
    watch.run()
    events = rows(engine)[1]
    assert "shadow_entry" not in events
    with Session(engine) as db:
        view = setup_scanner.day_view(db, DAY)
    assert view["candidates"][0]["shadow"]["status"] == expected


def test_shadow_take_uses_backend_decision_time_and_exits_independently(engine, monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_SETUPS_DIR", str(tmp_path / "setups"))
    monkeypatch.setenv("SHADOW_OUTBOX_DIR", str(tmp_path / "outbox"))
    quotes = Quotes()
    watch, clock = scanner(engine, at(9, 50, 35), quotes=quotes)
    breakout_day(watch.feed)
    watch.run()
    candidate = _candidate(engine)
    _decision_file(tmp_path / "outbox", candidate, committed_at=shadow_exchange.utc_z(candidate.detected_at))
    clock.now += 10
    quotes.updated_ms = clock.now * 1000 - 1
    watch.run()  # the quote predates backend storage, so it cannot price the shadow entry
    assert "shadow_entry" not in rows(engine)[1]
    quotes.updated_ms = (clock.now + 1) * 1000
    clock.now += 1
    watch.run()
    events = rows(engine)[1]
    assert events["entry"] and events["shadow_entry"]
    stored_ms = int(datetime.fromisoformat(events["shadow_decision"]["stored_at"].replace("Z", "+00:00")).timestamp() * 1000)
    assert events["shadow_entry"]["ask_time"] >= stored_ms
    watch.run()  # a new monitor pass over the same rows must not create another entry
    with Session(engine) as db:
        entries = db.exec(select(ScannerEvent).where(ScannerEvent.candidate_id == candidate.id)
                          .where(ScannerEvent.event_type == "shadow_entry")).all()
    assert len(entries) == 1

    watch.feed.add(at(9, 51), at(9, 52), 100.9, candidate.target + 0.1)
    clock.now = at(9, 52, 40)
    quotes.next = (1.5, 1.6)
    quotes.updated_ms = 10**15
    watch.run()
    events = rows(engine)[1]
    assert events.get("exit") and events.get("shadow_exit"), events
    with Session(engine) as db:
        view = setup_scanner.day_view(db, DAY)
    score = view["scorecard"]["day"]
    assert view["candidates"][0]["shadow"]["result"]["pnl"] == pytest.approx(43.7)
    assert score["take"] == 1 and score["shadow_pnl"] == pytest.approx(43.7)
    assert score["rules_priced"] == score["shadow_priced"] == 1
    assert score["group_evidence"] == {"rules": "not enough", "takes": "not enough", "skipped": "not enough"}


def test_shadow_no_response_and_cumulative_scorecard(engine, monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_SETUPS_DIR", str(tmp_path / "setups"))
    watch, clock = scanner(engine, at(9, 50, 35))
    breakout_day(watch.feed)
    watch.run()
    clock.now = at(10, 1)
    watch.shadow_exchange_pass(clock.now, DAY, Calendar().hours(DAY))
    with Session(engine) as db:
        view = setup_scanner.day_view(db, DAY)
    assert view["scorecard"]["day"]["no_response"] == 1
    assert "shadow_entry" not in rows(engine)[1]
    assert view["scorecard"]["cumulative"] == view["scorecard"]["day"]


def test_shadow_status_remains_separate_from_rules_trade(engine):
    watch, _ = scanner(engine, at(9, 50, 35))
    breakout_day(watch.feed)
    watch.run()
    with Session(engine) as db:
        view = setup_scanner.day_view(db, DAY)
    item = view["candidates"][0]
    assert item["status"] == "open" and item["shadow"]["status"] == "not_published"


def test_mail_send_logs_in_with_the_app_password_and_addresses_the_owner(monkeypatch):
    from app.engine import scanner_mail

    seen = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout, context):
            seen["server"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def login(self, user, password):
            seen["login"] = (user, password)

        def send_message(self, message):
            seen["message"] = message

    mail_env(monkeypatch)
    monkeypatch.setenv("SCANNER_SMTP_PASSWORD", "abcd efgh ijkl mnop")
    monkeypatch.setattr(scanner_mail.smtplib, "SMTP_SSL", FakeSMTP)
    assert scanner_mail.configured()
    scanner_mail.send("TJ Setup: test", "body")
    assert seen["server"] == ("smtp.gmail.com", 465) and seen["login"] == ("owner@example.com", "abcdefghijklmnop")
    assert seen["message"]["To"] == "owner+tjsetups@example.com" and seen["message"]["Subject"] == "TJ Setup: test"

# ------------------------------------------------------------------ S2 display-only trade links


def s2_candidate(day=DAY, hour=9, minute=50, **changes):
    detected = datetime(day.year, day.month, day.day, hour, minute, tzinfo=ET).astimezone(UTC).replace(tzinfo=None)
    return ScannerCandidate(**{ "session_date": day, "symbol": "SPY", "setup": "orb", "direction": "long",
        "scanner_version": rules.VERSION, "params_hash": rules.PARAMS_HASH, "bar_end": detected,
        "bar_start": detected - timedelta(minutes=5), "source": setup_scanner.SOURCE,
        "detected_at": detected, "expires_at": detected + timedelta(minutes=10), "stop": 100, "target": 102,
        "flags_json": "[]", "facts_json": "{}", "contract_json": json.dumps({"symbol": "SPY261007C00101000", "option_type": "call", "strike": 101, "expiration": day.isoformat(), "delta": 0.35, "bid": 1, "ask": 1.05}),
        **changes})


def s2_trade(day=DAY, hour=9, minute=55, **changes):
    return Trade(**{"account_id": uuid.uuid4(), "ticker": "SPY", "instrument_type": "option", "option_type": "call",
        "strike": 101, "expiration": day, "contracts": 2, "avg_entry_premium": 1, "total_premium_paid": 200,
        "opened_at": datetime(day.year, day.month, day.day, hour, minute), "status": "closed", "realized_pnl": 40,
        **changes})


@pytest.mark.parametrize("offset,expected", [(-1, False), (0, True), (1, True), (900, True), (901, False)])
def test_isaac_link_window_includes_both_edges(offset, expected):
    c = s2_candidate()
    trade = s2_trade(opened_at=datetime(2026, 10, 7, 9, 50) + timedelta(seconds=offset))
    assert bool(setup_scanner.link_isaac_trades([c], [trade])[c.id]) is expected


@pytest.mark.parametrize("changes", [{"option_type": "put"}, {"ticker": "QQQ"}, {"instrument_type": "stock"}])
def test_isaac_link_ignores_wrong_side_symbol_and_stock(changes):
    c = s2_candidate()
    assert setup_scanner.link_isaac_trades([c], [s2_trade(**changes)])[c.id] == []


def test_isaac_link_put_matches_short():
    c = s2_candidate(direction="short")
    t = s2_trade(option_type="put")
    assert setup_scanner.link_isaac_trades([c], [t])[c.id] == [t]


def test_isaac_link_latest_candidate_wins_and_ties_use_lowest_id():
    earlier = s2_candidate(minute=45)
    c = s2_candidate(id=uuid.UUID(int=1))
    tied = s2_candidate(id=uuid.UUID(int=2))
    trade, later = s2_trade(), s2_trade(minute=56)
    linked = setup_scanner.link_isaac_trades([tied, earlier, c], [later, trade])
    assert linked[c.id] == [trade, later]
    assert linked[earlier.id] == linked[tied.id] == []
    view = setup_scanner._isaac_view(c, {}, linked[c.id])
    assert view["trade_id"] == str(trade.id) and view["extra_trade_ids"] == [str(later.id)]


@pytest.mark.parametrize("day,utc_hour", [(DAY, 13), (date(2026, 11, 1), 14), (date(2026, 10, 31), 13), (date(2026, 3, 8), 13)])
def test_isaac_link_uses_ny_trade_clock_across_dst(day, utc_hour):
    c, t = s2_candidate(day), s2_trade(day)
    assert c.detected_at.hour == utc_hour
    assert setup_scanner.link_isaac_trades([c], [t])[c.id] == [t]
    assert setup_scanner._isaac_view(c, {}, [t])["opened_at"].endswith("-05:00" if utc_hour == 14 else "-04:00")


@pytest.mark.parametrize("status,seconds,assisted", [("sent", -1, True), ("sent", 0, False), ("sent", 1, False),
    ("expired", -1, False), ("skipped_daily_cap", -1, False), (None, -1, False)])
def test_isaac_assisted_requires_sent_email_strictly_before_open(status, seconds, assisted):
    c, t = s2_candidate(), s2_trade(strike=103, expiration=DAY + timedelta(days=7))
    state = {"email": {"status": status, "at": t.opened_at.replace(tzinfo=ET).timestamp() + seconds}} if status else {}
    view = setup_scanner._isaac_view(c, state, [t])
    assert view["assisted"] is assisted and view["contract_differs"] is True
    assert view["realized_pnl"] == 40 and view["pnl_per_contract"] == 20
    assert not setup_scanner._isaac_view(c, {}, [s2_trade()])["contract_differs"]


def s2_state(decision="take", rules_pnl=10, shadow_pnl=5):
    state = {"shadow_handoff": {"status": "written"}, "shadow_decision": {"decision": decision, "timing": "on_time"},
             "exit": {"pnl": rules_pnl, "pnl_2x_spread": rules_pnl - 5, "bid": 1.2, "reason": "target"}}
    if decision == "take":
        state["shadow_exit"] = {"pnl": shadow_pnl}
    return state


def test_isaac_scorecard_all_buckets_open_trades_and_independent_subset():
    candidates = [s2_candidate() for _ in range(6)]
    states = [s2_state("take"), s2_state("skip"), s2_state("take"), s2_state("skip"), s2_state("skip"), s2_state("take")]
    assisted = s2_trade()
    states[2]["email"] = {"status": "sent", "at": assisted.opened_at.replace(tzinfo=ET).timestamp() - 1}
    trades = [[], [s2_trade()], [assisted, s2_trade(minute=56, status="expired", realized_pnl=-20)], [],
              [s2_trade(status="open", realized_pnl=999)], [s2_trade(status="expired", realized_pnl=-10)]]
    views = {c.id: setup_scanner._isaac_view(c, state, ts) for c, state, ts in zip(candidates, states, trades)}
    score = setup_scanner._shadow_scorecard(list(zip(candidates, states)), views)
    isaac = score["isaac"]
    assert (isaac["traded"], isaac["assisted"], isaac["independent"], isaac["closed"]) == (4, 1, 3, 4)
    assert isaac["pnl_per_contract"] == 25 and isaac["pnl_dollars"] == 50
    groups = isaac["disagreements"]
    assert {k: g["count"] for k, g in groups.items()} == {"shadow_only": 1, "isaac_only": 2, "both_took": 2, "both_passed": 1}
    assert groups["shadow_only"]["shadow_pnl"] == 5 and groups["shadow_only"]["isaac_priced"] == 0
    assert groups["isaac_only"]["isaac_pnl_per_contract"] == 20 and groups["isaac_only"]["shadow_priced"] == 0
    assert groups["both_took"]["isaac_pnl_per_contract"] == 5 and groups["both_took"]["shadow_pnl"] == 10
    assert groups["both_passed"]["rules_pnl"] == 10 and groups["both_passed"]["isaac_priced"] == groups["both_passed"]["shadow_priced"] == 0
    subset = score["independent"]
    assert subset["setups"] == 5 and subset["traded"] == 3 and subset["assisted"] == 0
    assert subset["pnl_per_contract"] == 15 and subset["pnl_dollars"] == 30
    assert subset["disagreements"]["both_took"]["count"] == 1
    assert views[candidates[4].id]["pnl_per_contract"] is None
    assert all(g["evidence"] == "not enough" for g in groups.values())


def test_isaac_scorecard_evidence_boundary_and_missing_decisions():
    c, t = s2_candidate(), s2_trade()
    views = {c.id: setup_scanner._isaac_view(c, {}, [t])}
    for count in (29, 30):
        score = setup_scanner._shadow_scorecard([(c, s2_state())] * count, views)
        expected = "not enough" if count == 29 else "sufficient count"
        assert score["isaac"]["evidence"] == score["isaac"]["disagreements"]["both_took"]["evidence"] == expected
    score = setup_scanner._shadow_scorecard([(c, {}), (c, {"shadow_handoff": {"status": "written"}}),
                (c, {**s2_state(), "shadow_decision": {"decision": "take", "timing": "late"}})], views)
    assert sum(g["count"] for g in score["isaac"]["disagreements"].values()) == 0


def test_isaac_route_cumulative_multiple_days_and_dormant_account_scope(engine):
    prior = s2_candidate(DAY - timedelta(days=1))
    current = s2_candidate()
    future = s2_candidate(DAY + timedelta(days=1))
    roth = Account(name="Roth", type="roth_ira", last4="0001")
    webull = Account(name="Webull", type="brokerage", last4="0002", broker="webull")
    with Session(engine) as db:
        db.add_all([roth, webull, prior, current, future])
        db.add_all([s2_trade(DAY - timedelta(days=1), account_id=roth.id), s2_trade(account_id=roth.id),
                    s2_trade(account_id=webull.id, realized_pnl=900), s2_trade(DAY + timedelta(days=1), account_id=roth.id)])
        # Preserve six-entry scope: dormant account entries still count in the original S1 flag.
        for i in range(5):
            db.add(s2_trade(minute=31+i, account_id=webull.id))
        for c in (prior, current, future):
            for kind, data in s2_state().items():
                db.add(ScannerEvent(candidate_id=c.id, key=kind, event_type=kind, effective_at=c.detected_at,
                                    recorded_at=c.detected_at, data_json=json.dumps(data)))
        db.commit()
    app = FastAPI()
    app.include_router(routes.router, prefix="/scanner")
    app.dependency_overrides[get_session] = lambda: Session(engine)
    body = TestClient(app).get("/scanner/day", params={"day": DAY.isoformat()}).json()
    assert len(body["candidates"]) == 1 and body["candidates"][0]["flags"] == ["sixth_plus_entry"]
    assert body["scorecard"]["day"]["isaac"]["traded"] == 1
    assert body["scorecard"]["cumulative"]["isaac"]["traded"] == 2
    assert body["scorecard"]["cumulative"]["isaac"]["pnl_dollars"] == 80
    assert body["candidates"][0]["isaac"]["extra_trade_ids"] == []


def test_unpublished_and_published_expired_shadow_candidates_are_distinct():
    c = s2_candidate(day=date(2020, 1, 1))
    unpublished, missed = {}, {"shadow_handoff": {"status": "written"}}
    expired_handoff = {"shadow_handoff": {"status": "expired"}}
    assert setup_scanner.shadow_status_of(c, unpublished) == "not_published"
    assert setup_scanner.shadow_status_of(c, expired_handoff) == "not_published"
    assert setup_scanner.shadow_status_of(c, missed) == "no_response"
    view = setup_scanner._shadow_view(unpublished, setup_scanner.shadow_status_of(c, unpublished))
    assert view["status"] == "not_published" and view["result"] is None
    score = setup_scanner._shadow_scorecard([(c, unpublished), (c, missed), (c, expired_handoff)])
    assert score["not_published"] == 2 and score["no_response"] == score["shadow_setups"] == 1
    assert score["decisions"] == score["take"] == score["skip"] == 0


def test_isaac_same_fractional_strike_is_not_a_contract_difference():
    from decimal import Decimal
    c = s2_candidate()
    contract_ = json.loads(c.contract_json)
    contract_["strike"] = 101.1
    c.contract_json = json.dumps(contract_)
    assert not setup_scanner._isaac_view(c, {}, [s2_trade(strike=Decimal("101.100000"))])["contract_differs"]


def test_assisted_extra_trade_excludes_the_whole_setup_from_independent_comparison():
    c, first, extra = s2_candidate(), s2_trade(), s2_trade(minute=56)
    state = s2_state()
    state["email"] = {"status": "sent", "at": first.opened_at.replace(tzinfo=ET).timestamp() + 30}
    view = setup_scanner._isaac_view(c, state, [first, extra])
    assert not view["assisted"] and view["trades"][1]["assisted"]
    score = setup_scanner._shadow_scorecard([(c, state)], {c.id: view})
    assert score["isaac"]["assisted"] == 1 and score["isaac"]["pnl_dollars"] == 80
    assert score["independent"]["setups"] == score["independent"]["traded"] == 0


@pytest.mark.parametrize("state,expected", [
    ({"shadow_decision": {"decision": "take", "timing": "on_time"}}, "pending_entry"),
    ({"shadow_entry": {"ask": 1}}, "open"),
    ({"shadow_exit_intent": {"reason": "target"}}, "exiting"),
    ({"shadow_exit": {"pnl": 5}}, "exit"),
    ({"shadow_unresolved": {"reason": "entry was not priced"}}, "unresolved"),
])
def test_shadow_evaluation_survives_missing_or_expired_handoff_marker(state, expected):
    c = s2_candidate()
    for provenance in ({}, {"shadow_handoff": {"status": "expired"}}):
        assert setup_scanner.shadow_status_of(c, {**provenance, **state}) == expected


def test_shadow_scorecard_keeps_evaluated_trades_with_missing_marker():
    c = s2_candidate()
    state = s2_state()
    del state["shadow_handoff"]
    state["shadow_exit"]["at"] = setup_scanner._epoch(c.detected_at)
    view = setup_scanner._shadow_view(state, setup_scanner.shadow_status_of(c, state))
    assert view["decision"] == "take" and view["publication"] is None
    score = setup_scanner._shadow_scorecard([(c, state)])
    assert score["decisions"] == score["take"] == score["shadow_setups"] == 1
    assert score["shadow_pnl"] == 5 and score["not_published"] == 0
    assert score["isaac"]["disagreements"]["shadow_only"]["count"] == 1


def test_shadow_recovery_after_file_write_without_handoff_event(engine, monkeypatch, tmp_path):
    watch, clock = scanner(engine, at(9, 50, 35))
    breakout_day(watch.feed)
    watch.run()
    candidate = _candidate(engine)
    # File published and committed to, then backend crashed before recording the handoff.
    shadow_exchange.write_setup(tmp_path / "setups", candidate)
    _decision_file(tmp_path / "outbox", candidate)
    monkeypatch.setenv("SHADOW_SETUPS_DIR", str(tmp_path / "setups"))
    monkeypatch.setenv("SHADOW_OUTBOX_DIR", str(tmp_path / "outbox"))
    clock.now = setup_scanner._epoch(candidate.expires_at)
    watch.shadow_exchange_pass(clock.now, DAY, Calendar().hours(DAY))
    events = rows(engine)[1]
    assert events["shadow_handoff"]["status"] == "expired" and events["shadow_decision"]["decision"] == "take"
    assert "shadow_entry" in events and setup_scanner.shadow_status_of(candidate, events) == "open"
    with Session(engine) as db:
        score = setup_scanner.day_view(db, DAY)["scorecard"]["day"]
    assert score["take"] == 1 and score["not_published"] == score["no_response"] == 0
