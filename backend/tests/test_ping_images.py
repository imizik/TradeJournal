"""Pings with pictures (engine/chart_render.py, engine/ping_images.py): the renderer's size, determinism, annotations
and speed; the attachment sent to ntfy and the text-alone fallbacks; and each sender attaching its picture or
sending text when the picture fails, with the image state on the ping's policy record."""

import base64
from datetime import UTC, date, datetime
import hashlib
import json
import struct
import threading
import time
from uuid import UUID, uuid4
import zlib

import httpx
import numpy as np
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.engine import chart_render, ntfy, ping_images, plan_time_stops, reconstructor
from app.engine.chart_math import ET
from app.engine.chart_render import Chart, Level, Mark, Row, Series, Time
from app.engine.level_alert_monitor import LevelAlertMonitor, create_alert
from app.engine.plan_nudges import PlanNudges
from app.engine.plan_time_stops import PlanTimeStops
from app.engine.position_alerts import PositionAlerts
from app.engine.premarket_prep import PremarketPreps
from app.engine.radar_alerts import RadarAlerts
from app.engine.thesis_watch import Candidate, ThesisWatch, Watched
from app.models import (Account, Fill, LevelAlert, LevelAlertEvent, PhonePing, PlanNudge, PlanTimeStop, PositionAlert, PositionWatch,
                        PremarketPrep, RadarAlert, ThesisWatchTrigger, Trade, TradeFill)
from app.routers.fills import _rebuild_trades

ROTH = UUID(int=1)
WED = date(2026, 10, 21)
FRI = date(2026, 10, 23)
INV = "44444444-4444-4444-8444-444444444444"


def at(hhmm: str, day: date = WED) -> float:
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=ET).timestamp()


def utc(stamp: float) -> datetime:
    return datetime.fromtimestamp(stamp, UTC).replace(tzinfo=None)


def minute_bars(start: str = "09:30", count: int = 120, price: float = 100.0) -> list[dict]:
    """A deterministic wavy session: up, down, up."""
    out, first = [], int(at(start))
    for i in range(count):
        o = price + 2 * np.sin(i / 15)
        c = price + 2 * np.sin((i + 1) / 15)
        out.append({"time": first + 60 * i, "open": o, "high": max(o, c) + 0.2, "low": min(o, c) - 0.2, "close": c, "volume": 1000})
    return out


def pixels(png: bytes) -> np.ndarray:
    """The palette indexes of a PNG written by chart_render (8-bit palette, filter 0 on every row)."""
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, size = 8, b"", None
    while pos < len(png):
        length = struct.unpack(">I", png[pos:pos + 4])[0]
        kind, data = png[pos + 4:pos + 8], png[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            size = struct.unpack(">II", data[:8])
        elif kind == b"IDAT":
            idat += data
        pos += 12 + length
    width, height = size
    rows = np.frombuffer(zlib.decompress(idat), dtype=np.uint8).reshape(height, width + 1)
    assert not rows[:, 0].any()
    return rows[:, 1:]


def plan_chart(**changes) -> Chart:
    bars = minute_bars(count=90)
    return Chart(**{"title": "NBIS invalidation broke", "note": "NOW 99.12", "bars": tuple(bars),
                    "levels": (Level(98.5, "INV 98.50", "down"), Level(101.5, "TRIG 101.50", "up")),
                    "marks": (Mark(bars[30]["time"], bars[30]["close"], "FILL", "amber"),),
                    "times": (Time(bars[60]["time"], "PEAK", "violet"),), **changes})


class _Wednesday(date):
    @classmethod
    def today(cls):
        return WED


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(reconstructor, "date", _Wednesday)  # the test positions are open on WED
    chart_render._cache.clear()
    monkeypatch.setenv("PING_IMAGES_ENABLED", "true")
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")
    monkeypatch.setenv("ALERT_APP_URL", "https://app.example")
    monkeypatch.setenv("RADAR_ENABLED", "false")
    for name in ("ALERT_POLICY_ENABLED", "PING_DAILY_CAP", "PING_QUIET_MINUTES", "NTFY_TOKEN", "NTFY_IPV4_ONLY"):
        monkeypatch.delenv(name, raising=False)


# ------------------------------------------------------------------ the renderer

def test_a_chart_is_a_720_by_360_png_and_the_same_chart_is_the_same_bytes():
    png = chart_render.render(plan_chart())
    assert struct.unpack(">II", png[16:24]) == (720, 360)
    assert pixels(png).shape == (360, 720)
    chart_render._cache.clear()
    again = chart_render.render(plan_chart())
    assert hashlib.sha256(again).hexdigest() == hashlib.sha256(png).hexdigest()
    assert chart_render.render(plan_chart(title="NBIS entry trigger hit")) != png
    assert b"tEXt" not in png and b"tIME" not in png  # nothing but the pixels decides the bytes


def test_the_layout_places_every_annotation_and_the_pixels_show_them():
    chart = plan_chart()
    placed = chart_render.layout(chart)
    texts = {(label["kind"], label["text"]) for label in placed["labels"]}
    assert {("title", "NBIS INVALIDATION BROKE"), ("note", "NOW 99.12"), ("level", "INV 98.50"), ("level", "TRIG 101.50"),
            ("mark", "FILL"), ("time", "PEAK"), ("axis", "09:30"), ("axis", "10:59")} <= texts
    assert placed["mode"] == "candles"
    for label in placed["labels"]:  # nothing drawn off the picture
        x0, y0, x1, y1 = label["box"]
        assert 0 <= x0 <= x1 <= 720 and 0 <= y0 <= y1 <= 360
    image = pixels(chart_render.render(chart))
    index = chart_render.INDEX
    x0, _, x1, _ = placed["plot"]
    for tone in ("up", "down", "amber", "violet", "text", "muted"):
        assert (image == index[tone]).any(), tone
    # Each level label sits in the gutter, drawn in its level's colour.
    inv = next(label for label in placed["labels"] if label["text"] == "INV 98.50")
    lx0, ly0, lx1, ly1 = inv["box"]
    assert lx0 >= x1 and (image[ly0:ly1, lx0:lx1] == index["down"]).any()


def test_long_titles_shrink_then_cut_and_never_leave_the_picture():
    placed = chart_render.layout(plan_chart(title="SNDK 10/23/26 230C · expires today and gave back most of it", note="PEAK +45% NOW -3%"))
    title = next(label for label in placed["labels"] if label["kind"] == "title")
    note = next(label for label in placed["labels"] if label["kind"] == "note")
    assert title["text"].endswith("..") and title["box"][2] < note["box"][0]


def test_120_bars_render_in_under_100_ms():
    chart = Chart(title="SNDK 10/23/26 230C · gave back", note="PEAK +20% NOW +3%", bars=tuple(minute_bars(count=120)),
                  levels=(Level(99, "INV 99.00", "down"),), marks=(Mark(int(at("10:00")), 101, "ENTRY", "amber"),),
                  times=(Time(int(at("10:30")), "PEAK", "violet"),))
    best = float("inf")
    for i in range(3):
        chart_render._cache.clear()
        started = time.perf_counter()
        chart_render.render(chart)
        best = min(best, time.perf_counter() - started)
    assert best < 0.1
    started = time.perf_counter()
    chart_render.render(chart)  # cached
    assert time.perf_counter() - started < 0.01


def test_a_long_day_is_a_close_line_and_series_rows_and_empty_pictures_draw():
    assert chart_render.layout(Chart(title="day", bars=tuple(minute_bars(count=390))))["mode"] == "line"
    series = Chart(title="Radar: LAD +5.3% vs SPY +0.1%", series=(
        Series("LAD", tuple((int(at("09:35")) + 300 * i, 0.3 * i) for i in range(12)), "blue"),
        Series("SPY", tuple((int(at("09:35")) + 300 * i, 0.01 * i) for i in range(12)), "muted")))
    placed = chart_render.layout(series)
    assert placed["mode"] == "series" and {"LAD +3.3%", "SPY +0.1%"} <= {label["text"] for label in placed["labels"]}
    rows = chart_render.layout(Chart(title="Pre-market", rows=tuple(Row(f"NBIS {i}C", f"{i}D", i / 8) for i in range(8))))
    assert rows["mode"] == "rows" and "+2 MORE" in {label["text"] for label in rows["labels"]}
    assert chart_render.layout(Chart(title="nothing"))["mode"] == "empty"


# ------------------------------------------------------------------ delivery

def _decode(word: str) -> str:
    assert word.startswith("=?UTF-8?B?") and word.endswith("?=")
    return base64.b64decode(word[10:-2]).decode()


def test_the_picture_is_put_to_ntfy_with_the_text_in_encoded_headers(monkeypatch):
    seen = {}

    def put(url, *, content, headers, timeout):
        seen.update(url=url, content=content, headers=headers)
        return httpx.Response(200, json={"id": "abc"})

    monkeypatch.setattr(httpx, "put", put)
    monkeypatch.setenv("NTFY_TOKEN", "tk")
    png = chart_render.render(plan_chart())
    receipt, state = ping_images.publish("SNDK 10/23/26 230C: give-back − 3%", "Line one\nLine two ✓", png, priority=5, tags=("warning",),
                                         path="/trades/t?alert=a", direct_click=True, more=(("Ask copilot", "/copilot-lab"),))
    assert (receipt, state) == ("abc", "attached")
    assert seen["url"] == "https://ntfy.example/topic" and seen["content"] == png
    headers = seen["headers"]
    assert _decode(headers["Title"]) == "SNDK 10/23/26 230C: give-back − 3%" and _decode(headers["Message"]) == "Line one\nLine two ✓"
    assert headers["Filename"] == "chart.png" and headers["Priority"] == "5" and headers["Tags"] == "warning"
    assert headers["Click"] == "https://app.example/trades/t?alert=a" and headers["Authorization"] == "Bearer tk"
    assert json.loads(headers["Actions"]) == [{"action": "view", "label": "Open app", "url": "https://app.example/trades/t?alert=a"},
                                              {"action": "view", "label": "Ask copilot", "url": "https://app.example/copilot-lab"}]
    assert all(value.isascii() for value in headers.values())


def test_a_refused_picture_sends_the_text_alone_and_an_unreachable_server_does_not(monkeypatch):
    sent = []
    monkeypatch.setattr(ntfy, "publish", lambda title, body, **kw: sent.append((title, body, kw)) or "txt")
    monkeypatch.setattr(httpx, "put", lambda *a, **k: httpx.Response(400, json={"code": 40014, "error": "attachments not allowed"}))
    assert ping_images.publish("t", "b", b"png", path="/x") == ("txt", "none")
    assert sent == [("t", "b", {"path": "/x"})]

    def down(*a, **k):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(httpx, "put", down)
    with pytest.raises(ntfy.NtfyError) as caught:
        ping_images.publish("t", "b", b"png")
    assert not isinstance(caught.value, ntfy.ImageRefused) and isinstance(caught.value.__cause__, httpx.ReadTimeout)
    assert len(sent) == 1  # may have reached the phone: the sender's at-most-once rule decides, never a second send here
    monkeypatch.setattr(httpx, "put", lambda *a, **k: httpx.Response(503))
    with pytest.raises(ntfy.NtfyError) as caught:
        ping_images.publish("t", "b", b"png")
    assert not isinstance(caught.value, ntfy.ImageRefused)
    assert ping_images.publish("t", "b", None) == ("txt", "none")
    monkeypatch.setenv("PING_IMAGES_ENABLED", "false")
    assert ping_images.publish("t", "b", None) == ("txt", "off")


def test_a_slow_failing_or_switched_off_picture_never_holds_the_ping(monkeypatch):
    release, finished = threading.Event(), threading.Event()

    def slow():
        release.wait(30)  # a builder that cannot finish until the test lets it
        finished.set()
        return plan_chart()

    try:
        assert ping_images.picture(slow, budget=0.2) is None
        assert not finished.is_set()  # the budget gave up on the picture; it did not wait for it
    finally:
        release.set()
    assert finished.wait(5)
    assert ping_images.picture(lambda: 1 / 0) is None
    assert ping_images.picture(lambda: None) is None
    assert ping_images.picture(None) is None
    assert ping_images.picture(plan_chart)[:8] == b"\x89PNG\r\n\x1a\n"
    monkeypatch.setenv("PING_IMAGES_ENABLED", "false")
    called = []
    assert ping_images.picture(lambda: called.append(1)) is None and called == []
    assert ping_images.prepare(None, lambda db: called.append(1)) is None and called == []


def test_failed_picture_reads_are_rolled_back_and_cost_only_the_picture():
    class Db:
        rolled = False

        def rollback(self):
            self.rolled = True

    db = Db()
    assert ping_images.prepare(db, lambda db: 1 / 0) is None and db.rolled


# ------------------------------------------------------------------ the senders

@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Account(id=ROTH, name="Roth", type="roth_ira", last4="8267", broker="robinhood"))
        db.commit()
    yield engine
    engine.dispose()


class Phone:
    """ntfy as the senders see it: pictures and text, each recorded."""

    def __init__(self, monkeypatch, refuse: bool = False):
        self.sent: list[dict] = []
        self.refuse = refuse
        monkeypatch.setattr(ntfy, "publish", self.text)
        monkeypatch.setattr(ntfy, "publish_image", self.picture)

    def text(self, title, body, **kw):
        self.sent.append({"title": title, "body": body, "image": None})
        return "id"

    def picture(self, title, body, image, **kw):
        if self.refuse:
            raise ntfy.ImageRefused("ntfy refused the picture (400).")
        self.sent.append({"title": title, "body": body, "image": image})
        return "id"


@pytest.fixture
def bars(monkeypatch):
    seen = []

    def today(symbol):
        seen.append(symbol)
        return minute_bars("09:30", 300, 230.0 if symbol == "SNDK" else 100.0)

    monkeypatch.setattr(ping_images, "today_bars", today)
    return seen


class Calendar:
    def hours(self, day):
        return {"status": "open", "open": 570, "close": 960}


def buy(engine, when="10:00", ticker="SNDK"):
    i = int(uuid4().int % 10**9)
    with Session(engine) as db:
        db.add(Fill(id=UUID(int=i), account_id=ROTH, ticker=ticker, instrument_type="option", side="buy_to_open", contracts=2, price=310,
                    executed_at=datetime.combine(WED, datetime.strptime(when, "%H:%M").time()), raw_email_id=f"gmail:{i}",
                    option_type="call", strike=230, expiration=FRI))
        db.commit()
        _rebuild_trades(db, "test")
        db.commit()
        trade = db.exec(select(Trade).join(TradeFill, TradeFill.trade_id == Trade.id).where(TradeFill.fill_id == UUID(int=i))).one()
        return trade.id, f"gmail:{i}"


def image_states(engine) -> dict[str, str | None]:
    with Session(engine) as db:
        return {p.sender: p.image for p in db.exec(select(PhonePing)).all()}


def position_alert(engine, trade_id, key, kind="giveback", when="11:00"):
    with Session(engine) as db:
        db.add(PositionWatch(account_id=ROTH, source_key=key, generation=1, contracts=2, avg_cost=310, peak_mark=372,
                             peak_at=utc(at("10:40")), armed_at=utc(at("10:30"))))
        row = PositionAlert(account_id=ROTH, source_key=key, kind=kind, generation=1, trade_id=trade_id, contract="SNDK 10/23/26 230C",
                            contracts=2, avg_cost=310, mark=320, bid=318, gain=20, gain_pct=0.0323, peak_gain=124, peak_gain_pct=0.2,
                            detected_at=utc(at(when)))
        db.add(row)
        db.commit()
        return row.id


def test_a_give_back_carries_entry_peak_and_now_and_names_no_account_or_id(engine, bars, monkeypatch):
    phone = Phone(monkeypatch)
    trade_id, key = buy(engine, "10:00")
    alert_id = position_alert(engine, trade_id, key)
    built = []
    real = ping_images.position
    monkeypatch.setattr(ping_images, "position", lambda *a, **k: built.append(real(*a, **k)) or built[-1])
    PositionAlerts(engine, Calendar(), clock=lambda: at("11:01"), quotes=lambda s: {}).deliver()
    assert phone.sent[0]["title"] == "SNDK 10/23/26 230C: give-back triggered" and phone.sent[0]["image"][:4] == b"\x89PNG"
    assert bars == ["SNDK"] and image_states(engine) == {"position_alerts": "attached"}
    with Session(engine) as db:
        assert db.get(PositionAlert, alert_id).delivery == "sent"
    chart = built[0]()
    shown = {label["text"] for label in chart_render.layout(chart)["labels"]}
    assert {"ENTRY", "PEAK", "NOW", "PEAK +20% NOW +3%"} <= shown
    assert chart.title == "SNDK 10/23/26 230C · gave back"
    secrets = ("8267", str(ROTH), str(trade_id), str(alert_id), key.upper())
    assert not any(secret in text for text in shown for secret in secrets)


def test_a_failed_picture_sends_the_position_alert_as_text_and_records_none(engine, monkeypatch):
    phone = Phone(monkeypatch)
    monkeypatch.setattr(ping_images, "today_bars", lambda symbol: (_ for _ in ()).throw(RuntimeError("feed down")))
    trade_id, key = buy(engine, "10:00")
    position_alert(engine, trade_id, key)
    PositionAlerts(engine, Calendar(), clock=lambda: at("11:01"), quotes=lambda s: {}).deliver()
    assert [s["image"] for s in phone.sent] == [None] and image_states(engine) == {"position_alerts": "none"}


def test_a_refused_picture_still_sends_the_text_once(engine, bars, monkeypatch):
    phone = Phone(monkeypatch, refuse=True)
    trade_id, key = buy(engine, "10:00")
    position_alert(engine, trade_id, key)
    PositionAlerts(engine, Calendar(), clock=lambda: at("11:01"), quotes=lambda s: {}).deliver()
    assert len(phone.sent) == 1 and phone.sent[0]["image"] is None and image_states(engine) == {"position_alerts": "none"}


def test_a_picture_send_that_may_have_arrived_is_unknown_and_never_resent_as_text(engine, bars, monkeypatch):
    texts = []
    monkeypatch.setattr(ntfy, "publish", lambda *a, **k: texts.append(a))

    def put(*a, **k):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(httpx, "put", put)
    trade_id, key = buy(engine, "10:00")
    alert_id = position_alert(engine, trade_id, key)
    watcher = PositionAlerts(engine, Calendar(), clock=lambda: at("11:01"), quotes=lambda s: {})
    watcher.deliver()
    watcher.deliver()
    with Session(engine) as db:
        alert = db.get(PositionAlert, alert_id)
        assert alert.delivery == "unknown" and alert.attempts == 1
    assert texts == []


def test_a_slow_picture_costs_at_most_the_budget_and_the_ping_goes_as_text(engine, monkeypatch):
    phone = Phone(monkeypatch)
    release, finished = threading.Event(), threading.Event()

    def slow_bars(symbol):
        release.wait(30)  # the bar read cannot finish until the ping has gone out
        finished.set()
        return minute_bars()

    monkeypatch.setattr(ping_images, "BUDGET_SECONDS", 0.3)
    monkeypatch.setattr(ping_images, "today_bars", slow_bars)
    trade_id, key = buy(engine, "10:00")
    position_alert(engine, trade_id, key)
    try:
        PositionAlerts(engine, Calendar(), clock=lambda: at("11:01"), quotes=lambda s: {}).deliver()
        # The ping was handed to ntfy as text while the picture was still being read: the budget, not the read, decided.
        assert not finished.is_set()
        assert [s["image"] for s in phone.sent] == [None] and image_states(engine) == {"position_alerts": "none"}
    finally:
        release.set()
    assert finished.wait(5)


def test_a_picture_that_failed_with_a_5xx_is_retried_as_text(engine, bars, monkeypatch):
    texts = []
    monkeypatch.setattr(ntfy, "publish", lambda title, body, **kw: texts.append(title) or "id")
    monkeypatch.setattr(httpx, "put", lambda *a, **k: httpx.Response(500))
    trade_id, key = buy(engine, "10:00")
    alert_id = position_alert(engine, trade_id, key)
    clock = [at("11:01")]
    watcher = PositionAlerts(engine, Calendar(), clock=lambda: clock[0], quotes=lambda s: {})
    watcher.deliver()
    with Session(engine) as db:
        assert db.get(PositionAlert, alert_id).delivery == "pending" and texts == []
    clock[0] = at("11:02")
    watcher.deliver()
    with Session(engine) as db:
        assert db.get(PositionAlert, alert_id).delivery == "sent"
    assert texts == ["SNDK 10/23/26 230C: give-back triggered"] and image_states(engine) == {"position_alerts": "none"}


def test_pictures_off_sends_text_and_never_reads_bars(engine, bars, monkeypatch):
    monkeypatch.setenv("PING_IMAGES_ENABLED", "false")
    phone = Phone(monkeypatch)
    trade_id, key = buy(engine, "10:00")
    position_alert(engine, trade_id, key)
    PositionAlerts(engine, Calendar(), clock=lambda: at("11:01"), quotes=lambda s: {}).deliver()
    assert phone.sent[0]["image"] is None and bars == [] and image_states(engine) == {"position_alerts": "off"}


def test_a_plan_invalidation_carries_the_plan_levels_and_the_fill(engine, bars, monkeypatch):
    phone = Phone(monkeypatch)
    buy(engine, "10:05")
    with Session(engine) as db:
        for role, price in (("entry", 233.0), ("invalidation", 228.3)):
            create_alert(db, symbol="SNDK", price=price, reference=230.0, condition="crosses", interval=None, session="regular",
                         source_kind="copilot", source_id=INV, label=f"SNDK {role}", now=at("10:00"), plan_role=role)
        alert_id = db.exec(select(LevelAlert.id).where(LevelAlert.plan_role == "invalidation")).one()
    built = []
    real = ping_images.plan_level
    monkeypatch.setattr(ping_images, "plan_level", lambda *a, **k: built.append(real(*a, **k)) or built[-1])
    monitor = LevelAlertMonitor(engine, None, clock=lambda: at("11:32"))
    monitor.reload()
    monitor.record([monitor._event(monitor._watched[alert_id], 228.27, at("11:32") - 30, "stream", None)])
    monitor.deliver()
    assert phone.sent[0]["title"] == "SNDK invalidation broke" and phone.sent[0]["image"] is not None
    assert image_states(engine) == {"level_alerts": "attached"}
    with Session(engine) as db:
        assert db.exec(select(LevelAlertEvent)).one().delivery == "sent"
    shown = {label["text"] for label in chart_render.layout(built[0]())["labels"]}
    assert {"INV 228.30", "TRIG 233.00", "FILL"} <= shown


def test_a_plain_level_alert_stays_text(engine, bars, monkeypatch):
    phone = Phone(monkeypatch)
    with Session(engine) as db:
        alert_id = create_alert(db, symbol="NBIS", price=95.9, reference=94.0, condition="crosses", interval=None, session="regular",
                                source_kind="level", source_id=None, label="NBIS", now=at("10:00")).id
    monitor = LevelAlertMonitor(engine, None, clock=lambda: at("10:42"))
    monitor.reload()
    monitor.record([monitor._event(monitor._watched[alert_id], 95.93, at("10:41"), "stream", None)])
    monitor.deliver()
    assert phone.sent[0]["image"] is None and bars == [] and image_states(engine) == {}


def test_a_time_stop_carries_the_day_with_the_stop_time(engine, bars, monkeypatch):
    phone = Phone(monkeypatch)
    buy(engine, "10:05")
    stops = PlanTimeStops(engine, Calendar(), clock=lambda: at("15:30"))
    with Session(engine) as db:
        plan_time_stops.create(db, client_id="card-1", investigation_id=INV, symbol="SNDK", text="out by 15:30", now=at("10:00"),
                               calendar=Calendar())
    built = []
    real = ping_images.day_with_stop
    monkeypatch.setattr(ping_images, "day_with_stop", lambda *a, **k: built.append(real(*a, **k)) or built[-1])
    stops.run()
    stops.deliver()
    assert phone.sent[0]["title"] == "SNDK time stop" and phone.sent[0]["image"] is not None
    assert image_states(engine) == {"plan_time_stops": "attached"}
    with Session(engine) as db:
        assert db.exec(select(PlanTimeStop)).one().delivery == "sent"
    assert {"OUT 15:30", "ENTRY"} <= {label["text"] for label in chart_render.layout(built[0]())["labels"]}


def test_a_no_plan_nudge_carries_the_fill(engine, bars, monkeypatch):
    phone = Phone(monkeypatch)
    trade_id, key = buy(engine, "09:50")
    with Session(engine) as db:
        db.add(PlanNudge(account_id=ROTH, source_key=key, trade_id=trade_id, ticker="SNDK", contract="SNDK 10/23/26 230C",
                         side="buy_to_open", contracts=2, price=310, opened_at=datetime.combine(WED, datetime.strptime("09:50", "%H:%M").time()),
                         detected_at=utc(at("09:53"))))
        db.commit()
    built = []
    real = ping_images.fill_window
    monkeypatch.setattr(ping_images, "fill_window", lambda *a, **k: built.append(real(*a, **k)) or built[-1])
    PlanNudges(engine, Calendar(), clock=lambda: at("09:54")).deliver()
    assert phone.sent[0]["title"] == "SNDK 10/23 230C: no plan yet" and phone.sent[0]["image"] is not None
    assert image_states(engine) == {"plan_nudges": "attached"}
    chart = built[0]()
    assert chart.title == "SNDK 10/23 230C · no plan" and "FILL" in {label["text"] for label in chart_render.layout(chart)["labels"]}


def test_pre_market_prep_shows_the_open_options_by_days_to_expiry(engine, bars, monkeypatch):
    phone = Phone(monkeypatch)
    buy(engine, "09:50")
    with Session(engine) as db:
        db.add(PremarketPrep(day=WED, detected_at=utc(at("08:30")), body="Line one\nLine two", delivery="pending"))
        db.commit()
    built = []
    real = ping_images.positions_strip
    monkeypatch.setattr(ping_images, "positions_strip", lambda *a, **k: built.append(real(*a, **k)) or built[-1])
    PremarketPreps(engine, Calendar(), clock=lambda: at("08:31"), spawn=lambda work: None).deliver()
    assert phone.sent[0]["image"] is not None and image_states(engine) == {"premarket_prep": "attached"}
    labels = {label["text"] for label in chart_render.layout(built[0]())["labels"]}
    assert {"SNDK 10/23/26 230C", "2D"} <= labels and bars == []


def test_pre_market_prep_without_options_shows_the_first_armed_plan(engine, bars, monkeypatch):
    phone = Phone(monkeypatch)
    with Session(engine) as db:
        create_alert(db, symbol="NBIS", price=95.9, reference=94.0, condition="crosses", interval=None, session="regular",
                     source_kind="copilot", source_id=INV, label="NBIS entry", now=at("10:00", date(2026, 10, 20)), plan_role="entry")
        db.add(PremarketPrep(day=WED, detected_at=utc(at("08:30")), body="Line one", delivery="pending"))
        db.commit()
    PremarketPreps(engine, Calendar(), clock=lambda: at("08:31"), spawn=lambda work: None).deliver()
    assert phone.sent[0]["image"] is not None and bars == ["NBIS"]


class Store:
    """The Radar store's reads a picture uses."""

    def event(self, event_id):
        return {"event_id": event_id, "kind": "relative_to_spy", "symbols": ["LAD"], "benchmark": "SPY", "group": None}

    def passes(self, session_date):
        return [{"id": i, "status": "ok", "finished_at": datetime.fromtimestamp(at("09:35") + 300 * i, UTC).isoformat()} for i in range(10)]

    def pass_quotes(self, ids):
        return {i: {"LAD": {"last": 100 + 0.6 * i, "prev_close": 100}, "SPY": {"last": 500 + 0.1 * i, "prev_close": 500}} for i in ids}


def radar_alert(engine):
    with Session(engine) as db:
        db.add(RadarAlert(event_id="rv0-2026-10-21-spy-lad-up-1", session_date="2026-10-21", rule_version="v0", kind="relative_to_spy",
                          subject="LAD", title="Radar: LAD +5.4% vs SPY +0.2%", body="LAD up · 10:20 AM ET",
                          first_seen_at=utc(at("10:20")), detected_at=utc(at("10:20"))))
        db.commit()


def test_a_radar_alert_carries_the_stock_against_its_benchmark(engine, monkeypatch):
    phone = Phone(monkeypatch)
    radar_alert(engine)
    built = []
    real = ping_images.radar
    monkeypatch.setattr(ping_images, "radar", lambda *a, **k: built.append(real(*a, **k)) or built[-1])
    RadarAlerts(engine, clock=lambda: at("10:21"), store=Store()).deliver()
    assert phone.sent[0]["title"] == "Radar: LAD +5.4% vs SPY +0.2%" and phone.sent[0]["image"] is not None
    assert image_states(engine) == {"radar_alerts": "attached"}
    placed = chart_render.layout(built[0]())
    assert placed["mode"] == "series" and {"LAD +5.4%", "SPY +0.2%"} <= {label["text"] for label in placed["labels"]}


def test_a_radar_alert_without_the_store_is_text(engine, monkeypatch):
    phone = Phone(monkeypatch)
    radar_alert(engine)
    RadarAlerts(engine, clock=lambda: at("10:21")).deliver()
    assert phone.sent[0]["image"] is None and image_states(engine) == {"radar_alerts": "none"}


def test_thesis_watch_carries_the_move_from_its_reference(engine, bars, monkeypatch):
    phone = Phone(monkeypatch)
    built = []
    real = ping_images.thesis
    monkeypatch.setattr(ping_images, "thesis", lambda *a, **k: built.append(real(*a, **k)) or built[-1])
    watch = ThesisWatch(engine, Calendar(), clock=lambda: at("10:30"))
    row = Watched(symbol="NBIS", held=False)
    candidate = Candidate(row, "move", "move:NBIS:close:2026-10-21", "NBIS +4.5% since the prior close: 96 → 100.3",
                          {"pct": 4.5, "last": 100.3, "reference": 96.0, "basis": "close:2026-10-21"})
    with Session(engine) as db:
        view = watch._record(db, candidate, WED, datetime.fromtimestamp(at("10:30"), UTC))
    assert view["delivery"] == "sent" and phone.sent[0]["image"] is not None
    assert image_states(engine) == {"thesis_watch": "attached"}
    with Session(engine) as db:
        assert db.exec(select(ThesisWatchTrigger)).one().message_id == "id"
    chart = built[0]()
    assert "REF 96.00" in {label["text"] for label in chart_render.layout(chart)["labels"]} and chart.note.endswith("since close")


def test_the_picture_never_changes_the_policy_decision(engine, bars, monkeypatch):
    """The same pings with pictures on and off reach the same decisions; only ``image`` differs."""
    decisions = {}
    for flag in ("true", "false"):
        monkeypatch.setenv("PING_IMAGES_ENABLED", flag)
        monkeypatch.setenv("PING_DAILY_CAP", "1")
        Phone(monkeypatch)
        local = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(local)
        with Session(local) as db:
            db.add(Account(id=ROTH, name="Roth", type="roth_ira", last4="8267", broker="robinhood"))
            db.commit()
        trade_id, key = buy(local, "10:00")
        position_alert(local, trade_id, key, kind="hold_hour")
        radar_alert(local)
        PositionAlerts(local, Calendar(), clock=lambda: at("11:01"), quotes=lambda s: {}).deliver()
        RadarAlerts(local, clock=lambda: at("10:21"), store=Store()).deliver()
        with Session(local) as db:
            decisions[flag] = sorted((p.sender, p.decision) for p in db.exec(select(PhonePing)).all())
        local.dispose()
    assert decisions["true"] == decisions["false"]
