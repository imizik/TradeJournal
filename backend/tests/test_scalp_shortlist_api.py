"""The owner records a single server-timed decision against a frozen displayed slate."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import scalp_shortlist as api
from tests.test_browser_access import boundary as boundary, signin


DAY = "2026-11-04"
PATH = "/scalp-shortlist"
CHOICES = f"{PATH}/{DAY}/decisions"


@pytest.fixture
def paper(tmp_path, monkeypatch):
    monkeypatch.setenv("SCALP_SHORTLIST_DIR", str(tmp_path))
    store = tmp_path / DAY
    store.mkdir()
    live = {"day": DAY, "captured_at": DAY + "T09:40:05-05:00", "feed": "iex", "eligible": 129,
            "picks": [{"symbol": "NVDA", "direction": "down"}], "movers": []}
    (store / "live.json").write_text(json.dumps(live))
    (store / "recap.json").write_text(json.dumps({"official": [{"symbol": "AMD"}], "shown": [{"symbol": "NVDA"}]}))
    app = FastAPI()
    app.include_router(api.router, prefix=PATH)
    client = TestClient(app)
    def at(t):
        monkeypatch.setattr(api, "_now", lambda: datetime.fromisoformat(DAY + "T" + t + "-05:00"))
    return client, at


def test_only_shown_choices_and_no_future_recap(paper):
    client, at = paper
    at("09:39:59")
    assert client.get(PATH).json()["live"] is None
    at("09:40:09")
    view = client.get(PATH).json()
    assert view["live"]["feed"] == "iex" and view["recap"] is None and not view["decisions"]
    assert len(view["sessions"]) == 20
    assert client.post(CHOICES, json={"symbol": "AMD", "choice": "take"}).status_code == 404
    chosen = {"symbol": "NVDA", "choice": "pass"}
    first = client.post(CHOICES, json=chosen).json()
    assert first["timely"] and first["direction"] == "down"
    assert client.post(CHOICES, json={**chosen, "choice": "take"}).status_code == 409
    at("10:20:00")
    assert client.post(CHOICES, json=chosen).json() == first
    assert client.get(PATH).json()["decisions"] == [first]
    assert client.get(PATH).json()["recap"]["shown"][0]["symbol"] == "NVDA"
    assert client.get(PATH + "?day=2026-11-05").json()["live"] is None


@pytest.mark.parametrize(("time", "status", "timely"), [("09:40:03",409,None), ("09:40:59",200,True),
                          ("09:41:00",200,False), ("09:50:59",200,False), ("09:51:00",409,None)])
def test_server_clock_controls_paper_window(paper, time, status, timely):
    client, at = paper
    at(time)
    response = client.post(CHOICES, json={"symbol": "NVDA", "choice": "take"})
    assert response.status_code == status
    if status == 200:
        assert response.json()["timely"] is timely


def test_simultaneous_conflicting_choices_publish_once(paper):
    client, at = paper
    at("09:40:20")
    gate = threading.Barrier(2)
    def save(choice):
        gate.wait()
        return client.post(CHOICES, json={"symbol": "NVDA", "choice": choice}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(save, ["take", "pass"])) == [200, 409]
    assert len(client.get(PATH).json()["decisions"]) == 1


def test_assistant_blocked_before_accessing_shortlist(boundary):
    assert signin(boundary).status_code == 200
    assert boundary.public.get(PATH).status_code == 403
    assert boundary.public.post(CHOICES, json={"symbol": "NVDA", "choice": "pass"}).status_code == 403


def test_collector_choice_and_recap_use_the_same_session(tmp_path, monkeypatch):
    from datetime import date
    from app.engine import scalp_shortlist as collector

    day = date.fromisoformat(DAY)
    stocks = {"TEST": "FUND"}
    monkeypatch.setenv("SCALP_SHORTLIST_DIR", str(tmp_path))
    monkeypatch.setattr(collector, "load_universe", lambda: stocks)
    now = datetime.fromisoformat(DAY + "T09:40:08-05:00")
    monkeypatch.setattr(api, "_now", lambda: now)

    def bars(session, *, feed, symbols, start_minute, end_minute):
        ticker = {i: {"o": 10, "c": 10, "v": 10, "h": 10, "l": 10} for i in range(end_minute + 1)}
        sector = {i: v.copy() for i, v in ticker.items()}
        if session == day:
            for i in range(10):
                ticker[i]["v"] = 30
            ticker[9].update(c=9, l=9)
            if 21 in ticker:
                ticker[21].update(o=8, l=8)
        return {"TEST": ticker, "FUND": sector}

    app = FastAPI()
    app.include_router(api.router, prefix=PATH)
    client = TestClient(app)
    collector.warmup(day, root=tmp_path, fetch=bars, stocks=stocks, now=lambda: now)
    collector.capture_live(day, root=tmp_path, now=lambda: now, fetch=bars, stocks=stocks)
    assert client.get(PATH).json()["live"]["picks"][0]["direction"] == "down"
    assert client.post(CHOICES, json={"symbol": "TEST", "choice": "take"}).json()["timely"]
    now = datetime.fromisoformat(DAY + "T10:20:00-05:00")
    collector.make_recap(day, root=tmp_path, fetch=bars, now=lambda: now)
    view = client.get(PATH).json()
    assert view["recap"]["shown"][0]["return_pct"] == pytest.approx(20)
    assert view["decisions"][0]["symbol"] == view["recap"]["shown"][0]["symbol"] == "TEST"
