"""Watch your day (engine/day_replay.py, routers/replay.py): the frames (fixed axes, fills, pings and plan lines at the
right frames, deterministic), the animated PNG (valid chunks, every frame whole), the size cap, the owner-only routes
with their 14-day expiry, and the 16:20 job (once a day, off by default, a no-fill day builds nothing, one ping
through the notification policy that opens /replay/<date>). No network."""

from datetime import UTC, date, datetime, timedelta
import hashlib
import json
import re
import struct
from uuid import UUID
import zlib

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.engine import chart_render, day_replay, notification_policy, ntfy
from app.engine.chart_math import ET
from app.engine.day_replay import DayReplays, SymbolDay
from app.models import Account, DayReplay, Fill, LevelAlert, PhonePing
from app.routers import replay as replay_routes
from tests.test_browser_access import boundary, signin  # noqa: F401  (the shared access fixture)

ROTH, WEBULL = UUID(int=1), UUID(int=2)
FRI, SAT = date(2026, 10, 23), date(2026, 10, 24)
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def at(hhmm: str, day: date = FRI) -> int:
    h, m = map(int, hhmm.split(":"))
    return int(datetime(day.year, day.month, day.day, h, m, tzinfo=ET).timestamp())


def utc(stamp: float) -> datetime:
    return datetime.fromtimestamp(stamp, UTC).replace(tzinfo=None)


def session_bars(day: date = FRI, price: float = 100.0) -> list[dict]:
    first = at("09:30", day)
    out = []
    for i in range(390):
        o, c = price + 2 * np.sin(i / 25), price + 2 * np.sin((i + 1) / 25)
        out.append({"time": first + 60 * i, "open": o, "high": max(o, c) + 0.1, "low": min(o, c) - 0.1, "close": c, "volume": 100})
    return out


class Calendar:
    """Every weekday open 9:30-16:00."""

    def hours(self, day):
        return {"status": "closed"} if day.weekday() >= 5 else {"status": "open", "open": 570, "close": 960}


def nbis_day() -> SymbolDay:
    return SymbolDay("NBIS", FRI, tuple(session_bars()),
                     (day_replay.Fill(at("10:07") + 23, True, None), day_replay.Fill(at("13:40"), False, 100.5)),
                     (at("11:15"),), (day_replay.PlanLine(at("09:00"), "entry", 101.0), day_replay.PlanLine(at("12:00"), "invalidation", 98.5)))


def chunks(png: bytes) -> list[tuple[bytes, bytes]]:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    out, pos = [], 8
    while pos < len(png):
        length = struct.unpack(">I", png[pos:pos + 4])[0]
        kind, data = png[pos + 4:pos + 8], png[pos + 8:pos + 8 + length]
        assert struct.unpack(">I", png[pos + 8 + length:pos + 12 + length])[0] == zlib.crc32(kind + data) & 0xFFFFFFFF
        out.append((kind, data))
        pos += 12 + length
    return out


def frames_of(png: bytes) -> list[np.ndarray]:
    found = chunks(png)
    width, height = struct.unpack(">II", found[0][1][:8])
    out = []
    for kind, data in found:
        if kind in (b"IDAT", b"fdAT"):
            raw = zlib.decompress(data if kind == b"IDAT" else data[4:])
            rows = np.frombuffer(raw, dtype=np.uint8).reshape(height, width + 1)
            assert not rows[:, 0].any()
            out.append(rows[:, 1:])
    return out


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPTURE_STORAGE_DIR", str(tmp_path / "captures"))
    monkeypatch.setattr(day_replay, "_today", lambda: FRI)
    for name in ("DAY_REPLAY_ENABLED", "ALERT_POLICY_ENABLED", "PING_DAILY_CAP", "PING_QUIET_MINUTES"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path / "captures" / "day-replay"


# ------------------------------------------------------------------ frames


def test_frames_fill_a_fixed_axis_with_each_marker_from_its_own_minute():
    day = nbis_day()
    (start, end, low, high), frames = day_replay.charts(day, Calendar())
    times = [t for t, _ in frames]
    assert (start, end) == (at("09:30"), at("16:00")) and len(frames) == day_replay.FRAMES
    assert times[-1] == end and all(a < b for a, b in zip(times, times[1:]))
    assert low <= 98.5 and high >= 101.0  # the plan's lines are inside the fixed range
    buy, sell = day.fills
    first_buy, first_sell = day_replay.first_frame(times, buy.time), day_replay.first_frame(times, sell.time)
    first_ping = day_replay.first_frame(times, at("11:15"))
    first_inv = day_replay.first_frame(times, at("12:00"))
    for i, (t, chart) in enumerate(frames):
        labels = [m.label for m in chart.marks]
        assert ("BUY" in labels) == (i >= first_buy) and ("SELL" in labels) == (i >= first_sell)
        assert bool(chart.times) == (i >= first_ping) and all(x.label == "PING" for x in chart.times)
        assert [lv.label.split()[0] for lv in chart.levels] == (["TRIG", "INV"] if i >= first_inv else ["TRIG"])
        assert all(b["time"] < t for b in chart.bars) and chart.note == datetime.fromtimestamp(t, ET).strftime("%H:%M")
    # The option fill sits on the underlying's close at its minute; the stock fill at its price.
    mark = next(m for m in frames[-1][1].marks if m.label == "BUY")
    assert mark.price == next(b["close"] for b in day.bars if b["time"] == at("10:07"))
    assert next(m for m in frames[-1][1].marks if m.label == "SELL").price == 100.5


def test_a_fill_outside_the_session_widens_the_clip():
    day = SymbolDay("NBIS", FRI, tuple(session_bars()), (day_replay.Fill(at("08:47"), True, 100.0),))
    start, end = day_replay.window(day, Calendar())
    assert start <= at("08:47") and start % day_replay.SLOT == 0 and end == at("16:00")


def test_the_clip_is_deterministic_and_each_frame_is_the_drawn_frame():
    day = nbis_day()
    first, again = day_replay.clip(day, Calendar()), day_replay.clip(day, Calendar())
    assert hashlib.sha256(first.png).hexdigest() == hashlib.sha256(again.png).hexdigest()
    assert (first.width, first.height, first.fps, len(first.times)) == (720, 360, 10.0, 300)
    decoded = frames_of(first.png)
    (start, end, low, high), frames = day_replay.charts(day, Calendar())
    for i in (0, 120, 299):
        drawn = chart_render.frame(frames[i][1], start=start, end=end, low=low, high=high, slot=day_replay.SLOT)
        assert np.array_equal(decoded[i], drawn)
    assert not np.array_equal(decoded[0], decoded[-1])
    assert np.array_equal(frames_of(first.poster)[0], decoded[-1])
    assert len(first.png) < day_replay.MAX_BYTES


def test_a_frame_draws_only_what_happened_by_its_minute():
    day = SymbolDay("NBIS", FRI, tuple(session_bars()), nbis_day().fills)  # no plan lines: they span the whole plot
    (start, end, low, high), frames = day_replay.charts(day, Calendar())
    before = chart_render.frame(frames[50][1], start=start, end=end, low=low, high=high, slot=day_replay.SLOT)
    after = chart_render.frame(frames[51][1], start=start, end=end, low=low, high=high, slot=day_replay.SLOT)
    plot_x1 = chart_render.PLOT[2]
    # The right part of the plot (later in the day) is still empty early on.
    late = before[chart_render.PLOT[1] + 10:chart_render.PLOT[3] - 10, plot_x1 - 60:plot_x1 - 10]
    assert not np.isin(late, [chart_render.INDEX["up"], chart_render.INDEX["down"]]).any()
    assert not np.array_equal(before, after)


def test_a_clip_over_the_cap_halves_its_rate_then_its_size():
    day = nbis_day()
    full = day_replay.clip(day, Calendar())
    rate = day_replay.clip(day, Calendar(), max_bytes=len(full.png) // 2 + 1000)
    assert len(rate.png) <= len(full.png) // 2 + 1000 and len(rate.times) == 150 and rate.fps == 5.0
    assert rate.times[-1] == full.times[-1] and (rate.width, rate.height) == (720, 360)
    assert len(frames_of(rate.png)) == 150
    small = day_replay.clip(day, Calendar(), max_bytes=40_000)
    assert len(small.png) <= 40_000 and small.width < 720 and len(small.times) >= day_replay.MIN_FRAMES
    assert frames_of(small.png)[0].shape == (small.height, small.width)


def test_a_stale_plan_far_from_the_day_is_left_out():
    far = day_replay.PlanLine(at("09:00", FRI - timedelta(days=20)), "invalidation", 40.0)
    day = SymbolDay("NBIS", FRI, tuple(session_bars()), (), (), (nbis_day().plan[0], far))
    (_, _, low, _), frames = day_replay.charts(day, Calendar())
    assert low > 90 and [lv.label for lv in frames[-1][1].levels] == ["TRIG 101.00"]


def test_no_bars_no_clip():
    assert day_replay.clip(SymbolDay("NBIS", FRI, (), (day_replay.Fill(at("10:00"), True, 100.0),)), Calendar()) is None


# ------------------------------------------------------------------ the encoder


def test_the_apng_is_a_valid_looping_file_with_every_frame_whole():
    frames = [np.full((8, 12), i % len(chart_render.NAMES), dtype=np.uint8) for i in range(5)]
    data = chart_render.apng(frames, 10)
    found = chunks(data)
    kinds = [k for k, _ in found]
    assert kinds[:4] == [b"IHDR", b"acTL", b"PLTE", b"fcTL"] and kinds[-1] == b"IEND"
    assert struct.unpack(">II", found[1][1]) == (5, 0)  # five frames, looping
    assert kinds.count(b"fcTL") == 5 and kinds.count(b"IDAT") == 1 and kinds.count(b"fdAT") == 4
    sequence = [struct.unpack(">I", d[:4])[0] for k, d in found if k in (b"fcTL", b"fdAT")]
    assert sequence == list(range(9))
    controls = [struct.unpack(">IIIIIHHBB", d) for k, d in found if k == b"fcTL"]
    assert all(c[1:5] == (12, 8, 0, 0) and c[5:7] == (100, 1000) for c in controls)  # whole frames, 1/10 s each
    assert all(np.array_equal(a, b) for a, b in zip(frames_of(data), frames))


# ------------------------------------------------------------------ the day's facts and storage


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Account(id=ROTH, name="Roth", type="roth_ira", last4="8267", broker="robinhood"))
        db.add(Account(id=WEBULL, name="Webull", type="individual", last4="1111", broker="webull"))
        db.commit()
    yield engine
    engine.dispose()


def fill(engine, when: str, ticker: str = "NBIS", side: str = "buy_to_open", account: UUID = ROTH, day: date = FRI, n: list = [0]):
    n[0] += 1
    with Session(engine) as db:
        db.add(Fill(account_id=account, ticker=ticker, instrument_type="option", side=side, contracts=1, price=3.1,
                    executed_at=datetime.combine(day, datetime.strptime(when, "%H:%M").time()), raw_email_id=f"gmail:{n[0]}",
                    option_type="call", strike=100, expiration=FRI, underlying_price_at_fill=100.2))
        db.commit()


def ping(engine, when: str, symbol: str = "NBIS", decision: str = "sent"):
    with Session(engine) as db:
        db.add(PhonePing(sender="position_alerts", source_id=f"{symbol}-{when}-{decision}", kind="giveback", rank=2, symbol=symbol,
                         decision=decision, title="t", body="b", decided_at=utc(at(when))))
        db.commit()


def seed_day(engine):
    fill(engine, "10:07")
    fill(engine, "13:40", side="sell_to_close")
    fill(engine, "11:00", ticker="SPY", side="buy")
    fill(engine, "11:30", ticker="APLD", account=WEBULL)  # Webull is dormant: no clip
    fill(engine, "10:00", day=FRI - timedelta(days=1))  # yesterday
    ping(engine, "11:15")
    ping(engine, "12:15", symbol="SPY")
    ping(engine, "12:30", decision="suppressed")  # held: never shown
    with Session(engine) as db:
        db.add(LevelAlert(symbol="NBIS", price=101.0, created_on=FRI, condition="crosses", session="regular", direction="up",
                          source_kind="copilot", source_id="inv", plan_role="entry", created_at=utc(at("09:00"))))
        db.add(LevelAlert(symbol="NBIS", price=90.0, created_on=FRI, condition="crosses", session="regular", direction="down",
                          source_kind="copilot", source_id="old", plan_role="invalidation", state="fired",
                          created_at=utc(at("09:00", FRI - timedelta(days=9))), fired_at=utc(at("10:00", FRI - timedelta(days=8)))))
        db.commit()


def read_bars(symbol, day):
    return session_bars(day, 450.0 if symbol == "SPY" else 100.0)


def test_build_reads_the_day_and_saves_each_symbols_clip(engine, storage):
    seed_day(engine)
    with Session(engine) as db:
        assert {s: len(f) for s, f in day_replay.traded(db, FRI).items()} == {"NBIS": 2, "SPY": 1}
        assert day_replay.pings(db, FRI, "NBIS") == (at("11:15"),)
        assert [(p.role, p.price) for p in day_replay.plan_lines(db, FRI, "NBIS")] == [("entry", 101.0)]  # the old fired one is not
        saved = day_replay.build(db, FRI, Calendar(), read_bars)
    assert [c["symbol"] for c in saved["clips"]] == ["NBIS", "SPY"] and (saved["fills"], saved["pings"]) == (3, 2)
    assert sorted(p.name for p in (storage / "2026-10-23").iterdir()) == ["NBIS.png", "SPY.png", "index.json", "poster.png"]
    assert day_replay.ping_title(saved) == "Watch your day: NBIS, SPY · 3 fills, 2 pings"
    assert day_replay.ping_body(saved).startswith("A 30-second replay")


def test_a_day_with_no_fills_builds_nothing(engine, storage):
    fill(engine, "11:30", ticker="APLD", account=WEBULL)
    with Session(engine) as db:
        assert day_replay.build(db, FRI, Calendar(), read_bars) is None
    assert not storage.exists()


# ------------------------------------------------------------------ routes


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(replay_routes.router, prefix="/replay")
    return TestClient(app)


def test_routes_list_serve_and_expire_the_days_clips(engine, client, storage, monkeypatch):
    seed_day(engine)
    with Session(engine) as db:
        day_replay.build(db, FRI, Calendar(), read_bars)
    assert client.get("/replay").json() == {"days": [{"date": "2026-10-23", "symbols": ["NBIS", "SPY"]}]}
    body = client.get("/replay/2026-10-23").json()
    assert [(c["symbol"], c["frames"], c["fps"], c["path"]) for c in body["clips"]] == [
        ("NBIS", 300, 10.0, "/replay/2026-10-23/NBIS"), ("SPY", 300, 10.0, "/replay/2026-10-23/SPY")]
    assert len(body["clips"][0]["times"]) == 300 and not UUID_RE.search(json.dumps(body))
    clip = client.get("/replay/2026-10-23/nbis")
    assert clip.status_code == 200 and clip.headers["content-type"] == "image/png" and clip.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert clip.headers["cache-control"] == "private, no-store"
    assert client.get("/replay/2026-10-23/AAPL").status_code == 404
    assert client.get("/replay/2026-10-22").status_code == 404
    assert client.get("/replay/not-a-date").status_code == 400
    assert client.get("/replay/2026-10-23/..%2Findex.json").status_code == 404
    # Fourteen days later it is still kept; fifteen days later it is gone, and the next build deletes it.
    monkeypatch.setattr(day_replay, "_today", lambda: FRI + timedelta(days=14))
    assert client.get("/replay/2026-10-23/NBIS").status_code == 200
    monkeypatch.setattr(day_replay, "_today", lambda: FRI + timedelta(days=15))
    assert client.get("/replay/2026-10-23").status_code == 404 and client.get("/replay/2026-10-23/NBIS").status_code == 404
    assert client.get("/replay").json() == {"days": []}
    assert day_replay.purge() == 1 and not (storage / "2026-10-23").exists()


def test_assistant_sessions_cannot_reach_the_replay(boundary):  # noqa: F811
    assert boundary.owner.get("/replay").status_code == 200
    assert signin(boundary).status_code == 200
    for path in ("/replay", "/replay/2026-10-23", "/replay/2026-10-23/NBIS"):
        assert boundary.public.get(path).status_code == 403, path


# ------------------------------------------------------------------ the job


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class Phone:
    def __init__(self, monkeypatch):
        self.sent: list[dict] = []
        monkeypatch.setattr(ntfy, "configured", lambda: True)
        monkeypatch.setattr(ntfy, "publish", lambda title, body, **kw: self.sent.append({"title": title, "body": body, "image": None, **kw}) or "id")
        monkeypatch.setattr(ntfy, "publish_image", lambda title, body, image, **kw: self.sent.append({"title": title, "body": body, "image": image, **kw}) or "id")


def job(engine, clock):
    return DayReplays(engine, Calendar(), clock=clock, spawn=lambda work: work(), read_bars=read_bars)


def rows(engine):
    with Session(engine) as db:
        return db.exec(select(DayReplay)).all()


def test_at_1620_the_day_is_built_once_and_one_ping_opens_it(engine, storage, monkeypatch):
    monkeypatch.setenv("DAY_REPLAY_ENABLED", "true")
    monkeypatch.setenv("PING_IMAGES_ENABLED", "true")
    phone = Phone(monkeypatch)
    decided = []
    real = notification_policy.decide
    monkeypatch.setattr(notification_policy, "decide", lambda db, **kw: decided.append(kw) or real(db, **kw))
    seed_day(engine)
    clock = Clock(at("16:19"))
    replays = job(engine, clock)
    replays.run()
    assert rows(engine) == [] and phone.sent == []
    clock.now = at("18:20")  # past its window: waits for the next day
    replays.run()
    assert rows(engine) == []
    clock.now = at("16:20")
    replays._last_run = 0
    replays.run()
    (row,) = rows(engine)
    assert (row.day, row.delivery, row.symbols, row.fills, row.pings) == (FRI, "sent", "NBIS,SPY", 3, 2)
    (sent,) = phone.sent
    assert sent["title"] == "Watch your day: NBIS, SPY · 3 fills, 2 pings" and sent["path"] == "/replay/2026-10-23"
    assert sent["direct_click"] is True and sent["image"] == (storage / "2026-10-23" / "poster.png").read_bytes()
    assert [(d["sender"], d["kind"]) for d in decided] == [("day_replay", "day_replay")]
    with Session(engine) as db:
        record = db.exec(select(PhonePing).where(PhonePing.sender == "day_replay")).one()
        assert (record.decision, record.image, record.rank) == ("sent", "attached", notification_policy.rank("prep"))
    # Later passes, and a second process, never build or ping the day again.
    for later in ("16:21", "17:30", "23:59"):
        clock.now = at(later)
        replays._last_run = 0
        replays.run()
        replays.deliver()
        job(engine, Clock(at(later))).run()
    assert len(rows(engine)) == 1 and len(phone.sent) == 1


def test_off_by_default_on_a_closed_day_and_a_no_fill_day_sends_nothing(engine, storage, monkeypatch):
    phone = Phone(monkeypatch)
    seed_day(engine)
    job(engine, Clock(at("16:30"))).run()
    assert rows(engine) == []  # DAY_REPLAY_ENABLED unset
    monkeypatch.setenv("DAY_REPLAY_ENABLED", "true")
    job(engine, Clock(at("16:30", SAT))).run()
    assert rows(engine) == []  # not a trading day
    monday = date(2026, 10, 26)
    job(engine, Clock(at("16:30", monday))).run()
    (row,) = rows(engine)
    assert (row.day, row.delivery, row.title) == (monday, "skipped", None) and phone.sent == []
    assert not (storage / monday.isoformat()).exists()


def test_a_held_ping_is_recorded_and_not_sent(engine, storage, monkeypatch):
    monkeypatch.setenv("DAY_REPLAY_ENABLED", "true")
    monkeypatch.setenv("PING_DAILY_CAP", "0")
    phone = Phone(monkeypatch)
    seed_day(engine)
    job(engine, Clock(at("16:20"))).run()
    (row,) = rows(engine)
    assert row.delivery == "held" and "cap" in row.last_error and phone.sent == []
    assert (storage / "2026-10-23" / "NBIS.png").exists()  # the clips are kept: the page still opens them
