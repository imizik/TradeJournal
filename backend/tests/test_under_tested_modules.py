"""Focused unit tests for under-tested, non-money backend modules."""

from __future__ import annotations

from datetime import date, datetime
import json
import sys
from types import ModuleType, SimpleNamespace
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pandas as pd
import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.engine import analyzer, company_research_bridge as bridge, packets, research
from app.engine.alpaca import ET
from app.models import ResearchAssignment
from app.routers import packets as packets_router_mod


@pytest.fixture
def isolated_db(tmp_path):
    """Yield an isolated SQLite Session for workspace and assignment tests."""
    engine = create_engine(f"sqlite:///{tmp_path / 'unit.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


# ---------------------------------------------------------------------------
# app.engine.company_research_bridge
# ---------------------------------------------------------------------------


def test_bridge_configuration_and_researchers(monkeypatch):
    monkeypatch.delenv("COMPANY_RESEARCH_CHECK_CONFIG", raising=False)
    assert bridge.configuration() is None
    assert bridge.researchers() == []

    monkeypatch.setenv("COMPANY_RESEARCH_CHECK_CONFIG", "/tmp/unused-config.json")
    import company_research_owner

    disabled_cfg = SimpleNamespace(company_research_enabled=False, profiles=[])
    monkeypatch.setattr(company_research_owner, "read_binding", lambda _p: disabled_cfg)
    assert bridge.configuration() is None

    enabled_cfg = SimpleNamespace(
        company_research_enabled=True,
        profiles=[
            SimpleNamespace(id="jo", enabled=True),
            SimpleNamespace(id="disabled", enabled=False),
            SimpleNamespace(id="duet", enabled=True),
        ],
    )
    monkeypatch.setattr(company_research_owner, "read_binding", lambda _p: enabled_cfg)
    assert bridge.configuration() is enabled_cfg
    assert bridge.researchers() == [
        {"id": "jo", "label": "Dots / Jo"},
        {"id": "duet", "label": "Duet"},
    ]


def test_bridge_revoke_company_unlinks_only_non_manual_matching_rows(isolated_db, tmp_path, monkeypatch):
    from company_research_exchange import context_name

    target_company = uuid.uuid4()
    other_company = uuid.uuid4()
    jo_actor = f"check_{uuid.uuid4()}"
    duet_actor = f"check_{uuid.uuid4()}"
    expires = datetime(2026, 12, 1, 0, 0, 0)

    def add_assignment(company_id: uuid.UUID, actor: str, *, create_file: bool = True) -> uuid.UUID:
        row_id = uuid.uuid4()
        isolated_db.add(
            ResearchAssignment(
                id=row_id,
                company_id=company_id,
                question="Check thesis",
                actor=actor,
                context_json="{}",
                context_hash="h",
                expires_at=expires,
            )
        )
        if create_file:
            (tmp_path / context_name(actor, row_id)).write_text("{}", encoding="utf-8")
        return row_id

    non_manual_target = add_assignment(target_company, jo_actor)
    add_assignment(target_company, "manual", create_file=False)
    other_company_row = add_assignment(other_company, jo_actor)
    missing_file_target = add_assignment(target_company, duet_actor, create_file=False)
    isolated_db.commit()

    monkeypatch.setattr(bridge, "configuration", lambda: None)
    bridge.revoke_company(isolated_db, target_company)
    assert (tmp_path / context_name(jo_actor, non_manual_target)).exists()

    cfg = SimpleNamespace(market_watch_snapshots_dir=str(tmp_path))
    monkeypatch.setattr(bridge, "configuration", lambda: cfg)
    bridge.revoke_company(isolated_db, target_company)

    assert not (tmp_path / context_name(jo_actor, non_manual_target)).exists()
    assert not (tmp_path / context_name(duet_actor, missing_file_target)).exists()
    assert (tmp_path / context_name(jo_actor, other_company_row)).exists()


# ---------------------------------------------------------------------------
# app.engine.analyzer
# ---------------------------------------------------------------------------


def test_analyzer_scalar_helpers():
    assert analyzer._pct(None, 100.0) is None
    assert analyzer._pct(105.0, None) is None
    assert analyzer._pct(105.0, 0) is None
    assert analyzer._pct(110.0, 100.0) == 10.0

    assert analyzer._bar_date_str({}) is None
    assert analyzer._bar_date_str({"t": 12345}) is None
    assert analyzer._bar_date_str({"t": "2026-11-17T15:00:00Z"}) == "2026-11-17"

    assert analyzer._snapshot_block({}) == {}
    snap_block = analyzer._snapshot_block(
        {
            "latestTrade": {"p": 110.0, "t": "2026-11-17T20:00:00Z"},
            "dailyBar": {"o": 102.0, "h": 112.0, "l": 101.0, "v": 1_000_000},
            "prevDailyBar": {"c": 100.0},
        }
    )
    assert snap_block["price"] == 110.0
    assert snap_block["change_pct_from_prev_close"] == 10.0
    assert snap_block["today_volume"] == 1_000_000

    assert analyzer._missing([], {}, {}) == ["daily_bars", "snapshot", "intraday"]
    assert analyzer._missing([{"c": 1.0}], {"latestTrade": {"p": 1.0}}, {"vwap": 1.0}) == []


def test_analyzer_long_term_block_edges_and_returns():
    latest = date(2026, 11, 17)
    assert analyzer._long_term_block([], {}, latest) == {}
    assert analyzer._long_term_block([{"o": 1, "h": 2, "l": 1, "c": None}], {}, latest) == {}

    short_bars = [{"o": 10.0, "h": 11.0, "l": 9.0, "c": 10.0 + i * 0.1} for i in range(10)]
    short_indic = {
        latest.isoformat(): {
            "sma_20": 10.0,
            "sma_50": 9.5,
            "ema_9": 10.5,
            "ema_20": 10.2,
            "rsi_14": 55.0,
            "atr_14": 0.4,
            "macd": 0.2,
            "macd_signal": 0.1,
            "macd_histogram": 0.1,
        }
    }
    short_out = analyzer._long_term_block(short_bars, short_indic, latest)
    assert short_out["sma_200"] is None
    assert short_out["return_1m_pct"] is None
    assert short_out["rsi_14"] == 55.0

    long_bars = [
        {"o": float(100 + i), "h": float(102 + i), "l": float(99 + i), "c": float(100 + i)}
        for i in range(260)
    ]
    fallback_indic = {"2026-11-16": {"sma_20": 340.0, "sma_50": 320.0}}
    long_out = analyzer._long_term_block(long_bars, fallback_indic, latest)
    assert long_out["trading_days_available"] == 260
    assert long_out["sma_200"] is not None
    assert long_out["sma_20"] == 340.0
    assert long_out["high_52w"] == float(102 + 259)
    assert long_out["low_52w"] == float(99 + 8)
    assert long_out["return_1m_pct"] is not None
    assert long_out["return_3m_pct"] is not None
    assert long_out["return_6m_pct"] is not None


def test_analyzer_build_ticker_analysis_live_and_fallback(monkeypatch):
    monkeypatch.setattr(analyzer, "alpaca_configured", lambda: False)
    with pytest.raises(RuntimeError, match="Alpaca keys not configured"):
        analyzer.build_ticker_analysis("NVDA")

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 18, 10, 30, tzinfo=tz)

    monkeypatch.setattr(analyzer, "datetime", FixedDateTime)
    monkeypatch.setattr(analyzer, "alpaca_configured", lambda: True)
    monkeypatch.setattr(analyzer, "_latest_completed_daily_bar_date", lambda: date(2026, 11, 17))
    monkeypatch.setattr(
        analyzer,
        "fetch_daily_bars",
        lambda _syms, _s, _e: {
            "NVDA": [
                {"t": "2026-11-17T00:00:00Z", "o": 100.0, "h": 105.0, "l": 99.0, "c": 104.0, "v": 1000},
                {"t": "2026-11-18T00:00:00Z", "o": 105.0, "h": 106.0, "l": 104.0, "c": 105.5, "v": 200},
            ]
        },
    )
    monkeypatch.setattr(analyzer, "compute_daily_indicators", lambda _bars: {"2026-11-17": {"sma_20": 101.0}})
    monkeypatch.setattr(
        analyzer,
        "fetch_snapshots",
        lambda _syms: {
            "NVDA": {"latestTrade": {"p": 106.0, "t": "2026-11-18T15:30:00Z"}, "prevDailyBar": {"c": 104.0}}
        },
    )
    live_bar = [{"t": "2026-11-18T15:29:00Z", "o": 105.0, "h": 106.0, "l": 104.8, "c": 106.0, "v": 500, "vw": 105.4}]
    monkeypatch.setattr(analyzer, "fetch_minute_bars_live", lambda _syms, _d: {"NVDA": live_bar})
    monkeypatch.setattr(analyzer, "fetch_minute_bars_for_date", lambda _s, _d: {})
    monkeypatch.setattr(analyzer, "analyze_minute_bars", lambda bars, _ref: {"vwap": 105.4, "count": len(bars)})

    live_res = analyzer.build_ticker_analysis(" nvda ")
    assert live_res["symbol"] == "NVDA"
    assert live_res["short_term"]["is_live_today"] is True
    assert live_res["short_term"]["as_of_session"] == "2026-11-18"
    assert [b["date"] for b in live_res["recent_daily_bars"]] == ["2026-11-17"]
    assert live_res["missing"] == []

    # Fallback to last completed session when no live prints exist yet
    fallback_calls: list[date] = []
    monkeypatch.setattr(analyzer, "fetch_minute_bars_live", lambda _syms, _d: {})

    def fake_hist(_syms, d):
        fallback_calls.append(d)
        return {}

    monkeypatch.setattr(analyzer, "fetch_minute_bars_for_date", fake_hist)
    fallback_res = analyzer.build_ticker_analysis("NVDA")
    assert fallback_calls == [date(2026, 11, 17)]
    assert fallback_res["short_term"]["as_of_session"] == "2026-11-17"
    assert fallback_res["short_term"]["is_live_today"] is False
    assert "intraday" in fallback_res["missing"]


# ---------------------------------------------------------------------------
# app.engine.research
# ---------------------------------------------------------------------------


def test_research_seed_merge_and_reconcile(monkeypatch):
    assert research.load_seed("unknown-slug") is None
    shipped = research.load_seed("ai-buildout")
    assert isinstance(shipped, dict)

    synthetic_seed = {"schema_version": 1, "companies": [{"ticker": "NVDA", "note": "base"}]}
    monkeypatch.setattr(research, "_load_seed_file", lambda _name: synthetic_seed)
    copy_a = research.load_seed("ai-buildout")
    assert copy_a is not None
    copy_a["companies"][0]["note"] = "mutated"
    assert research.load_seed("ai-buildout")["companies"][0]["note"] == "base"

    assert research._array_key([{"ticker": "AVGO"}]) == "ticker"
    assert research._array_key([{"id": "compute"}]) == "id"
    assert research._array_key([{"name": "plain"}]) is None
    assert research._array_key(["scalar"]) is None

    merged = research.deep_merge(
        {
            "companies": [{"ticker": "NVDA", "note": "default", "tag": "gpu"}],
            "tags": ["a", "b"],
            "meta": {"owner": "sys", "ver": 1},
            "keep": "default-scalar",
        },
        {
            "companies": [
                {"ticker": "NVDA", "note": "custom"},
                {"ticker": "AVGO", "note": "user-added"},
                {"note": "missing-key-ignored"},
            ],
            "tags": ["user-only"],
            "meta": {"ver": 2, "extra": True},
            "keep": None,
        },
    )
    assert merged["companies"] == [
        {"ticker": "NVDA", "note": "custom", "tag": "gpu"},
        {"ticker": "AVGO", "note": "user-added"},
    ]
    assert merged["tags"] == ["user-only"]
    assert merged["meta"] == {"owner": "sys", "ver": 2, "extra": True}
    assert merged["keep"] == "default-scalar"

    # Non-matching container types fall back to defaults
    assert research.deep_merge([1, 2], "not-a-list") == [1, 2]
    assert research.deep_merge({"a": 1}, ["not-a-dict"]) == {"a": 1}

    reconciled = research._reconcile({"layers": {"l1": {}, "l2": {}}, "order": ["l1"]})
    assert reconciled["order"] == ["l1", "l2"]


def test_research_workspace_lifecycle_and_schema_upgrade(isolated_db, monkeypatch):
    assert research.get_or_create_workspace(isolated_db, "nope") is None

    seed_v1 = {
        "schema_version": 1,
        "layers": {"compute": {"title": "Compute"}},
        "order": ["compute"],
        "companies": [{"ticker": "NVDA", "thesis": "base"}],
    }
    monkeypatch.setattr(research, "_load_seed_file", lambda _name: seed_v1)

    created = research.get_or_create_workspace(isolated_db, "ai-buildout")
    assert created is not None
    assert created.schema_version == 1
    assert created.revision == 0

    same = research.get_or_create_workspace(isolated_db, "ai-buildout")
    assert same.id == created.id
    assert same.revision == 0

    saved_row = research.save_workspace(
        isolated_db,
        created,
        {
            "layers": {"compute": {"title": "My Compute"}},
            "order": ["compute"],
            "companies": [{"ticker": "NVDA", "thesis": "edited"}],
        },
    )
    assert saved_row.revision == 1

    seed_v2 = {
        "schema_version": 2,
        "layers": {"compute": {"title": "Compute"}, "networking": {"title": "Net"}},
        "order": ["compute", "networking"],
        "companies": [
            {"ticker": "NVDA", "thesis": "base", "tier": 1},
            {"ticker": "MRVL", "thesis": "new", "tier": 2},
        ],
    }
    monkeypatch.setattr(research, "_load_seed_file", lambda _name: seed_v2)

    upgraded = research.get_or_create_workspace(isolated_db, "ai-buildout")
    assert upgraded.schema_version == 2
    payload = json.loads(upgraded.data_json)
    assert payload["layers"]["compute"]["title"] == "My Compute"
    assert payload["order"] == ["compute", "networking"]
    assert payload["companies"][0] == {"ticker": "NVDA", "thesis": "edited", "tier": 1}
    assert payload["companies"][1]["ticker"] == "MRVL"

    # Corrupt data_json falls back safely during another schema upgrade
    upgraded.data_json = "{not-valid-json"
    isolated_db.add(upgraded)
    isolated_db.commit()
    monkeypatch.setattr(research, "_load_seed_file", lambda _name: {**seed_v2, "schema_version": 3})
    recovered = research.get_or_create_workspace(isolated_db, "ai-buildout")
    assert recovered.schema_version == 3
    assert json.loads(recovered.data_json)["companies"][0]["thesis"] == "base"


# ---------------------------------------------------------------------------
# app.engine.packets
# ---------------------------------------------------------------------------


def test_packets_dates_state_and_metrics_helpers():
    assert packets._previous_weekday(date(2026, 11, 16)) == date(2026, 11, 13)  # Mon -> Fri
    assert packets._previous_weekday(date(2026, 11, 15)) == date(2026, 11, 13)  # Sun -> Fri

    sat = datetime(2026, 11, 14, 12, 0, tzinfo=ET)
    assert packets._resolve_session_dates("premarket", sat) == (date(2026, 11, 13), date(2026, 11, 12))
    wed_early = datetime(2026, 11, 18, 9, 15, tzinfo=ET)
    assert packets._resolve_session_dates("premarket", wed_early) == (date(2026, 11, 18), date(2026, 11, 17))
    assert packets._resolve_session_dates("postmarket", wed_early) == (date(2026, 11, 17), date(2026, 11, 16))

    assert packets._market_state(sat) == "closed"
    assert packets._market_state(datetime(2026, 11, 18, 3, 59, tzinfo=ET)) == "closed"
    assert packets._market_state(datetime(2026, 11, 18, 8, 30, tzinfo=ET)) == "premarket"
    assert packets._market_state(datetime(2026, 11, 18, 12, 0, tzinfo=ET)) == "rth"
    assert packets._market_state(datetime(2026, 11, 18, 17, 30, tzinfo=ET)) == "afterhours"
    assert packets._market_state(datetime(2026, 11, 18, 20, 5, tzinfo=ET)) == "closed"

    assert packets._bar_et_dt({}) is None
    assert packets._bar_et_dt({"t": "bad-ts"}) is None
    assert packets._bar_et_dt({"t": "2026-11-18T14:30:00Z"}).hour == 9

    session_d = date(2026, 11, 18)
    assert packets._symbol_metrics("SPY", None, [], session_d)["last_price"] is None

    daily_hist = [{"t": "2026-11-17T00:00:00Z", "v": 1_000_000}]
    m_curr = packets._symbol_metrics(
        "SPY",
        {
            "latestTrade": {"p": 111.0, "t": "2026-11-18T21:30:00Z"},
            "dailyBar": {"t": "2026-11-18T05:00:00Z", "o": 102.0, "h": 112.0, "l": 101.0, "c": 110.0, "v": 1_500_000},
            "prevDailyBar": {"c": 100.0},
        },
        daily_hist,
        session_d,
    )
    assert m_curr["prev_close"] == 100.0
    assert m_curr["gap_pct"] == 2.0
    assert m_curr["ah_move_pct"] == 0.91
    assert m_curr["rvol"] == 1.5

    m_prior = packets._symbol_metrics(
        "QQQ",
        {"latestTrade": {"p": 50.0}, "dailyBar": {"t": "2026-11-17T05:00:00Z", "c": 48.0}},
        [],
        session_d,
    )
    assert m_prior["prev_close"] == 48.0

    m_nodate = packets._symbol_metrics(
        "IWM",
        {"latestTrade": {"p": 21.0}, "dailyBar": {"c": 19.0}, "prevDailyBar": {"c": 20.0}},
        [],
        session_d,
    )
    assert m_nodate["prev_close"] == 20.0

    assert packets._bucket_aggregate([{"pct_change": None}], 1.0) == {"symbols_with_data": 0}
    agg = packets._bucket_aggregate([{"pct_change": 2.0, "rvol": 1.2}, {"pct_change": -1.0, "rvol": 0.8}], 0.5)
    assert agg["symbols_with_data"] == 2
    assert agg["pct_green"] == 50.0
    assert agg["rs_vs_spy"] == 0.0

    minute_bars = [
        {"t": "not-iso"},
        {"t": "2026-11-18T08:00:00-05:00", "o": 99.0, "h": 100.0, "l": 98.5, "c": 99.5, "v": 100},
        {"t": "2026-11-18T09:30:00-05:00", "o": 100.0, "h": 104.0, "l": 99.0, "c": 103.0, "v": 500, "vw": 102.0},
        {"t": "2026-11-18T10:00:00-05:00", "o": 103.0, "h": 106.0, "l": 102.0, "c": 105.0, "v": 500, "vw": 104.0},
        {"t": "2026-11-18T16:15:00-05:00", "o": 105.0, "h": 107.0, "l": 104.5, "c": 106.05, "v": 200},
    ]
    detail = packets._detail_metrics(minute_bars, m_curr)
    assert detail["premarket_high"] == 100.0
    assert detail["or5_high"] == 104.0
    assert detail["rth_vwap"] == 103.0
    assert detail["ah_last_price"] == 106.05
    assert detail["ah_move_pct"] == 1.0


def test_packets_yf_gauge_archive_and_build_report(tmp_path, monkeypatch):
    # Test _yf_gauge branches via stubbed yfinance module
    class FakeTicker:
        def __init__(self, symbol: str):
            self.symbol = symbol

        def history(self, **_kwargs):
            if self.symbol == "^EMPTY":
                return pd.DataFrame({"Close": pd.Series([], dtype=float)})
            if self.symbol == "^BOOM":
                raise RuntimeError("yf error")
            return pd.DataFrame({"Close": [20.0, 22.0]})

    fake_yf = ModuleType("yfinance")
    fake_yf.Ticker = FakeTicker
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    assert packets._yf_gauge("^EMPTY") is None
    assert packets._yf_gauge("^BOOM") is None
    assert packets._yf_gauge("^VIX") == {"last": 22.0, "prev_close": 20.0, "change_pct": 10.0}

    # Universe and archive paths stay inside tmp_path
    universe_file = tmp_path / "universe.json"
    universe_file.write_text(
        json.dumps(
            {
                "indexes": ["SPY", "QQQ", "IWM", "DIA", "SMH"],
                "sectors": ["XLK"],
                "macro_gauges": ["TLT"],
                "semis_ai": ["NVDA", "AVGO"],
            }
        ),
        encoding="utf-8",
    )
    archive_dir = tmp_path / "archive"
    monkeypatch.setattr(packets, "UNIVERSE_PATH", universe_file)
    monkeypatch.setattr(packets, "ARCHIVE_DIR", archive_dir)

    with pytest.raises(ValueError, match="Unknown report_type"):
        packets.build_market_report("midday")

    monkeypatch.setattr(packets, "alpaca_configured", lambda: False)
    with pytest.raises(RuntimeError, match="Alpaca API keys"):
        packets.build_market_report("premarket")

    class RthDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 18, 11, 0, tzinfo=tz)

    monkeypatch.setattr(packets, "datetime", RthDateTime)
    monkeypatch.setattr(packets, "alpaca_configured", lambda: True)
    monkeypatch.setattr(
        packets,
        "fetch_snapshots",
        lambda _syms: {
            "SPY": {
                "latestTrade": {"p": 505.0},
                "dailyBar": {"t": "2026-11-18T05:00:00Z", "o": 500.0, "h": 506.0, "l": 499.0, "c": 505.0, "v": 100},
                "prevDailyBar": {"c": 500.0},
            },
            "NVDA": {
                "latestTrade": {"p": 140.0},
                "dailyBar": {"t": "2026-11-18T05:00:00Z", "o": 135.0, "h": 141.0, "l": 134.0, "c": 140.0, "v": 200},
                "prevDailyBar": {"c": 135.0},
            },
            "XLK": {
                "latestTrade": {"p": 210.0},
                "dailyBar": {"t": "2026-11-18T05:00:00Z", "o": 208.0, "h": 211.0, "l": 207.0, "c": 210.0, "v": 50},
                "prevDailyBar": {"c": 208.0},
            },
        },
    )
    monkeypatch.setattr(packets, "fetch_daily_bars", lambda _s, _a, _b: {})
    monkeypatch.setattr(packets, "fetch_minute_bars_live", lambda _s, _d: {})
    monkeypatch.setattr(packets, "_yf_gauge", lambda sym: {"last": 15.0, "change_pct": 1.0} if sym == "^VIX" else None)

    def fake_news(symbols=None, **_kwargs):
        if symbols is not None:
            raise RuntimeError("news timeout")
        return []

    monkeypatch.setattr(packets, "fetch_news", fake_news)
    pre_report = packets.build_market_report("premarket")
    assert pre_report["confidence"] == "low"
    assert (archive_dir / "2026-11-18_premarket.json").exists()
    md = (archive_dir / "2026-11-18_premarket.md").read_text(encoding="utf-8")
    assert "# premarket packet — 2026-11-18" in md
    assert "macro_gauges: NO DATA" in md

    # Postmarket during RTH includes intraday caveat and archives article headlines
    monkeypatch.setattr(
        packets,
        "fetch_news",
        lambda symbols=None, **_kwargs: [{"created_at": "t", "headline": "News", "symbols": ["NVDA"]}],
    )
    post_report = packets.build_market_report("postmarket")
    assert any("market still open" in msg for msg in post_report["missing"])
    post_md = (archive_dir / "2026-11-18_postmarket.md").read_text(encoding="utf-8")
    assert "News (NVDA)" in post_md
    assert "Headlines (broad tape, 1)" in post_md

    # OSError during archive logs rather than raising
    archive_file_blocker = tmp_path / "file-not-dir"
    archive_file_blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(packets, "ARCHIVE_DIR", archive_file_blocker)
    packets._archive_report(post_report)


# ---------------------------------------------------------------------------
# app.routers.packets
# ---------------------------------------------------------------------------


def test_packets_router_endpoints_and_error_mapping(monkeypatch):
    router_mod = packets_router_mod

    app = FastAPI()
    app.include_router(router_mod.router, prefix="/packets")
    client = TestClient(app)

    monkeypatch.setattr(router_mod, "build_market_report", lambda kind: {"report_type": kind})
    assert client.get("/packets/report?type=premarket").json() == {"report_type": "premarket"}

    def raise_runtime(*_args, **_kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(router_mod, "build_market_report", raise_runtime)
    assert client.get("/packets/report?type=postmarket").status_code == 503

    monkeypatch.setattr(router_mod, "build_ticker_analysis", lambda sym: {"symbol": sym})
    assert client.get("/packets/analyze?symbol=NVDA").json() == {"symbol": "NVDA"}

    monkeypatch.setattr(router_mod, "build_ticker_analysis", raise_runtime)
    assert client.get("/packets/analyze?symbol=NVDA").status_code == 503

    captured_scalp = {}

    def fake_scalp(symbol, **kwargs):
        captured_scalp["symbol"] = symbol
        captured_scalp["kwargs"] = kwargs
        return {"symbol": symbol, "verdict": "wait"}

    monkeypatch.setattr(router_mod, "build_scalp_analysis", fake_scalp)
    res_scalp = client.get("/packets/scalp?symbol=NVDA&direction=long&instrument=stock&style=open")
    assert res_scalp.status_code == 200
    assert captured_scalp["kwargs"]["style"] == "open"

    def raise_value(*_args, **_kwargs):
        raise ValueError("bad option")

    monkeypatch.setattr(router_mod, "build_scalp_analysis", raise_value)
    assert client.get("/packets/scalp?symbol=NVDA").status_code == 422

    monkeypatch.setattr(router_mod, "build_scalp_analysis", raise_runtime)
    assert client.get("/packets/scalp?symbol=NVDA").status_code == 503

    captured_news = []

    def fake_fetch_news(**kwargs):
        captured_news.append(kwargs)
        return [{"headline": "H1"}]

    monkeypatch.setattr(router_mod, "fetch_news", fake_fetch_news)
    res_news = client.get("/packets/news?symbols=nvda, aapl &hours=6&limit=50&include_content=true")
    assert res_news.status_code == 200
    assert res_news.json()["articles"] == [{"headline": "H1"}]
    assert captured_news[0]["symbols"] == ["NVDA", "AAPL"]
    assert captured_news[0]["limit"] == 10
    assert captured_news[0]["include_content"] is True

    res_broad = client.get("/packets/news?limit=25")
    assert res_broad.status_code == 200
    assert captured_news[1]["symbols"] is None
    assert captured_news[1]["limit"] == 25
    assert captured_news[1]["include_content"] is False
