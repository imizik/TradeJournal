from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlmodel import Session, create_engine, select

from app.engine import first_pullback as pb
from app.engine.chart_math import ET, normalize_bars
from app.models import PhonePing

OPEN = int(datetime(2026, 11, 4, 9, 30, tzinfo=ET).timestamp())
END = OPEN + 17 * 60


def candles(side):
    bars = []
    for index, close in enumerate([100 + (i + 1) / 5 for i in range(15)] + [102.8, 103.1]):
        high, low = round(close + .1, 2), round(close - .1, 2)
        if index == 15:
            low = 102.5
        if index == 16:
            low = 102.6
        if side < 0:
            high, low, close = (round(200 - n, 2) for n in (low, high, close))
        bars.append(dict(timestamp=OPEN + 60 * index, open=close, high=high, low=low, close=close, volume=100))
    return bars


@pytest.mark.parametrize("side", [1, -1])
def test_signal_levels_and_retirement(side):
    rows = candles(side)
    bars = normalize_bars(rows)
    t = pb.first_trigger(bars, OPEN, END)
    assert (t.side, t.end, float(t.stop), float(t.target)) == (
        side, END, 102.5 if side == 1 else 97.5, 104 if side == 1 else 96)
    assert pb.first_trigger(bars, OPEN, END - 60) is None
    assert pb.first_trigger(bars[1:], OPEN, END) is None
    rows[-1]["low" if side == 1 else "high"] = float(t.stop)
    assert pb.first_trigger(normalize_bars(rows), OPEN, END) is None


def test_watcher_records_and_sends_each_side_once_on_fresh_data(monkeypatch):
    engine = create_engine("sqlite://")
    PhonePing.__table__.create(engine)
    now = [END + 31]
    fetched = [END - 1]
    sent = []
    calendar = SimpleNamespace(hours=lambda day: {"status": "open", "open": 570, "close": 960})

    def read(path, params, ttl):
        rows = candles(1 if params["symbol"] == "SPY" else -1)
        return {"series": {"data": rows}}, fetched[0], None

    def run():
        pb.FirstPullbackAlerts(engine, SimpleNamespace(read=read), calendar, lambda: now[0]).run()

    monkeypatch.setattr(pb.phone, "configured", lambda: True)
    monkeypatch.setattr(pb.phone, "send", lambda title, body, **kw: sent.append((title, body, kw["path"])))
    run()
    assert not sent
    fetched[0] = now[0]
    run()
    run()  # fresh monitor instance, same durable claim
    assert [s[0] for s in sent] == ["SPY first pullback · CALL", "QQQ first pullback · PUT"]
    assert "ETF stop $102.50 · 1.5R target $104.00" in sent[0][1]
    assert "09:47 ET" in sent[1][1] and sent[1][2] == "/charts?symbol=QQQ"
    with Session(engine) as db:
        assert all(p.delivered_at for p in db.exec(select(PhonePing)).all())
    engine.dispose()


def test_disabled_by_default_and_in_trial_or_sandbox(monkeypatch):
    monkeypatch.delenv("FIRST_PULLBACK_ALERTS_ENABLED", raising=False)
    monkeypatch.delenv("TJ_DOT_TRIAL_ENABLED", raising=False)
    monkeypatch.setattr(pb.tradier, "TRADIER_BASE_URL", "https://api.tradier.com")
    assert not pb.enabled()
    monkeypatch.setenv("FIRST_PULLBACK_ALERTS_ENABLED", "true")
    assert pb.enabled()
    monkeypatch.setenv("TJ_DOT_TRIAL_ENABLED", "true")
    assert not pb.enabled()
    monkeypatch.delenv("TJ_DOT_TRIAL_ENABLED")
    monkeypatch.setattr(pb.tradier, "TRADIER_BASE_URL", "https://sandbox.tradier.com")
    assert not pb.enabled()


@pytest.mark.parametrize("case", ["old_signal", "stop_touched", "target_touched", "closed", "unconfigured"])
def test_no_late_or_already_crossed_level_ping(monkeypatch, case):
    cutoff = END + (60 if case == "old_signal" else 0)
    now = cutoff + 31
    calendar = SimpleNamespace(hours=lambda day: {"status": "closed" if case == "closed" else "open",
                                                 "open": 570, "close": 960})

    def read(path, params, ttl):
        assert case not in ("closed", "unconfigured")
        rows = candles(1)
        rows.append(dict(timestamp=END, open=103.1, close=103.1, volume=10,
                         high=104.01 if case == "target_touched" else 103.2,
                         low=102.49 if case == "stop_touched" else 103.0))
        return {"series": {"data": rows}}, now, None

    monkeypatch.setattr(pb.phone, "configured", lambda: case != "unconfigured")
    job = pb.FirstPullbackAlerts(None, SimpleNamespace(read=read), calendar, lambda: now)
    monkeypatch.setattr(job, "notify", lambda *args: pytest.fail("ineligible alert"))
    job.run()
