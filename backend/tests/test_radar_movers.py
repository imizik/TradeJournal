"""Radar "Movers now": the plain ranking over recorded passes, with no thresholds or provider calls."""
from datetime import UTC, datetime

from fastapi.testclient import TestClient
import pytest

from app.engine.chart_math import ET
from app.engine.radar_movers import build_movers
from app.engine.radar_store import RadarStore, load_universe
from app.main import app
from app.routers import radar
from tests.test_browser_access import boundary  # noqa: F401  (the shared access fixture)

SESSION = "2026-10-22"


def _at(hh_mm: str) -> float:
    return datetime.fromisoformat(f"{SESSION}T{hh_mm}:00").replace(tzinfo=ET).timestamp()


def _stamp(hh_mm: str) -> str:
    return datetime.fromtimestamp(_at(hh_mm), UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _pass(minute: str, status="ok"):
    return {"session_date": SESSION, "started_at": _stamp(minute), "finished_at": _stamp(minute), "universe_version": "radar-universe-v2",
            "status": status, "symbols_requested": 5, "symbols_returned": 5, "unmatched": [], "requests_used": 1,
            "error": None, "skip_reason": None}


def _q(symbol, last, prev=100.0, open_=None, minute="14:34"):
    return {"symbol": symbol, "last": last, "prev_close": prev, "open": prev if open_ is None else open_, "high": None, "low": None,
            "volume": 1, "bid": None, "ask": None, "trade_time_ms": None, "retrieved_at": _stamp(minute)}


def _etf(symbol):
    return {"symbol": symbol, "kind": "etf", "benchmark": True, "sources": []}


def _stock(symbol, sector=None):
    return {"symbol": symbol, "kind": "stock", "benchmark": False, "sector": sector, "sources": []}


UNIVERSE = {"version": "t", "symbols": [_etf("SPY"), _etf("QQQ"), _etf("SMH"), _stock("AAA", "SMH"), _stock("BBB", "SMH"),
                                        _stock("CCC"), _stock("DDD", "SMH")],
            "groups": [{"name": "Chips", "members": ["AAA", "BBB", "DDD", "ZZZ"]}, {"name": "Lone", "members": ["CCC"]},
                       {"name": "Empty", "members": ["ZZZ"]}]}


def _quotes():
    return [_q("SPY", 99.0), _q("QQQ", 98.0), _q("SMH", 96.0),               # SPY -1%, QQQ -2%, SMH -4%
            _q("AAA", 90.0, open_=91.0),                                      # -10%; from open -1.1%
            _q("BBB", 95.0, open_=100.0),                                     # -5%
            _q("CCC", 110.0, open_=100.0),                                    # +10%
            _q("DDD", 0.0)]                                                   # zero price: missing


def test_math_ranking_and_missing():
    out = build_movers(UNIVERSE, _quotes(), [_q("AAA", 100.0), _q("CCC", 100.0)])
    assert out["header"] == {"spy_day_pct": -1.0, "qqq_day_pct": -2.0, "symbols_with_data": 6, "symbols_tracked": 7, "has_earlier_pass": True}
    assert out["missing"] == ["DDD"]
    assert [r["symbol"] for r in out["leaders"]] == ["CCC", "BBB", "AAA"]
    assert [r["symbol"] for r in out["laggards"]] == []  # fewer than 10 stocks all sit in the leaders list
    aaa = next(r for r in out["leaders"] if r["symbol"] == "AAA")
    assert aaa["day_pct"] == -10.0 and aaa["vs_spy"] == -9.0
    assert aaa["from_open_pct"] == pytest.approx(-1.099, abs=0.001)
    assert aaa["sector"] == "SMH" and aaa["vs_sector"] == -6.0
    assert aaa["last_15m_pct"] == -10.0
    ccc = next(r for r in out["leaders"] if r["symbol"] == "CCC")
    assert ccc["sector"] is None and ccc["vs_sector"] is None and ccc["from_open_pct"] == 10.0 and ccc["last_15m_pct"] == 10.0
    bbb = next(r for r in out["leaders"] if r["symbol"] == "BBB")
    assert bbb["last_15m_pct"] is None  # not in the earlier pass: no invented 0%


def test_laggards_are_the_bottom_ten_without_overlap():
    symbols = [_etf("SPY")] + [_stock(f"S{i:02d}") for i in range(25)]
    quotes = [_q("SPY", 100.0)] + [_q(f"S{i:02d}", 100.0 + i) for i in range(25)]
    out = build_movers({"version": "t", "symbols": symbols, "groups": []}, quotes, None)
    assert [r["symbol"] for r in out["leaders"]] == [f"S{i:02d}" for i in range(24, 14, -1)]
    assert [r["symbol"] for r in out["laggards"]] == [f"S{i:02d}" for i in range(10)]
    assert out["header"]["has_earlier_pass"] is False and out["leaders"][0]["last_15m_pct"] is None


def test_groups_counts_median_and_order():
    out = build_movers(UNIVERSE, _quotes(), None)
    # Sorted by absolute median: Lone (+11.0) before Chips (-6.5); a group without data goes last.
    assert [g["name"] for g in out["groups"]] == ["Lone", "Chips", "Empty"]
    lone, chips, empty = out["groups"]
    assert (chips["members_with_data"], chips["members_total"]) == (2, 4)
    assert (chips["ahead"], chips["behind"]) == (0, 2) and chips["median_vs_spy"] == -6.5
    assert chips["most"] == {"symbol": "AAA", "vs_spy": -9.0}
    assert lone["median_vs_spy"] == 11.0 and lone["ahead"] == 1 and lone["behind"] == 0
    assert empty["members_with_data"] == 0 and empty["median_vs_spy"] is None and empty["most"] is None


def test_no_usable_spy_means_nothing_is_ranked():
    quotes = [q for q in _quotes() if q["symbol"] != "SPY"]
    out = build_movers(UNIVERSE, quotes, None)
    assert out["header"] is None and out["leaders"] == [] and "SPY" in out["missing"]


@pytest.fixture
def api(tmp_path, monkeypatch):
    path = tmp_path / "radar.sqlite"
    monkeypatch.setenv("RADAR_ENABLED", "true")
    monkeypatch.setenv("RADAR_STORE", str(path))
    monkeypatch.setattr(radar, "_regular_window", lambda day: (570, 960))
    clock = {"now": _at("14:34")}
    monkeypatch.setattr(radar, "_now", lambda: clock["now"])
    monkeypatch.setattr(radar, "load_universe", lambda: UNIVERSE)
    store = RadarStore(path)
    with TestClient(app) as client:
        yield type("Api", (), {"client": client, "store": store, "clock": clock})


def test_states(api, monkeypatch):
    assert api.client.get("/radar/movers").json()["state"] == "no_data"
    api.store.append_pass(_pass("14:19"), _quotes())
    api.store.append_pass(_pass("14:34", "failed"))  # a failed pass is never the latest
    body = api.client.get("/radar/movers").json()
    assert body["state"] == "stale" and body["pass_at"] == _stamp("14:19")  # live and 15 minutes behind
    api.store.append_pass(_pass("14:34"), _quotes())
    body = api.client.get(f"/radar/movers?session={SESSION}").json()
    assert body["state"] == "ok" and body["pass_at"] == _stamp("14:34") and body["earlier_pass_at"] == _stamp("14:19")
    assert body["reason"] is None and body["leaders"][0]["symbol"] == "CCC"
    api.clock["now"] = _at("17:00")  # after the close nothing is expected, so the last pass is simply the last pass
    assert api.client.get("/radar/movers").json()["state"] == "ok"
    assert api.client.get("/radar/movers?session=2026-10-21").json()["state"] == "no_data"
    assert api.client.get("/radar/movers?session=nope").status_code == 422
    assert api.client.get("/radar/movers?session=2026-13-45").status_code == 422
    monkeypatch.delenv("RADAR_ENABLED")
    assert api.client.get("/radar/movers").json()["state"] == "off"


def test_earlier_pass_needs_to_be_near_fifteen_minutes(api):
    api.store.append_pass(_pass("14:30"), _quotes())  # only 4 minutes back: not close to 15
    api.store.append_pass(_pass("14:34"), _quotes())
    body = api.client.get("/radar/movers").json()
    assert body["earlier_pass_at"] is None and body["header"]["has_earlier_pass"] is False
    assert all(r["last_15m_pct"] is None for r in body["leaders"])


def test_owner_only(boundary, tmp_path):  # noqa: F811
    RadarStore(tmp_path / "radar.sqlite")
    boundary.patch.setenv("RADAR_ENABLED", "true")
    boundary.patch.setenv("RADAR_STORE", str(tmp_path / "radar.sqlite"))
    assert boundary.owner.get("/radar/movers").status_code == 200
    assert boundary.public.get("/radar/movers").status_code == 401
