"""Independent references cross-check production math and evidence boundaries."""
import json
import random
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.engine import metric_reference as ref
from app.engine import trade_path
from app.engine.auditor import compute_audit
from app.engine.indicators import analyze_minute_bars, compute_daily_indicators
from app.engine.metric_validation import CachedBars, build_report, record
from app.engine.reconstructor import FillInput, reconstruct
from app.models import Fill, Trade


def fill(side="buy_to_open", qty=1, price=100, minute=0):
    return dict(id=str(uuid.uuid4()), account_id="00000000-0000-0000-0000-000000000001", raw_email_id=str(uuid.uuid4()),
                ticker="AMD", instrument_type="option", option_type="call", strike=100, expiration="2026-09-30",
                side=side, contracts=qty, price=price, executed_at=f"2026-09-24T10:{minute:02}:00")


def bar(minute, high=1.2, low=0.9):
    return dict(t=f"2026-09-24T14:{minute:02}:00Z", o=(high + low) / 2, h=high, l=low, c=(high + low) / 2, v=100)


def trade(fills, status="closed"):
    return dict(id=fills[0]["id"], account_id=fills[0]["account_id"], ticker="AMD", instrument_type="option",
                option_type="call", strike=100, expiration="2026-09-30", opened_at=fills[0]["executed_at"],
                closed_at=fills[-1]["executed_at"], status=status, contracts=10, avg_entry_premium=100, total_premium_paid=1000)


def test_reference_ledger_and_position_path_hand_calculation():
    fills = [fill(qty=10), fill("sell_to_close", 9, 110, 10), fill("sell_to_close", 1, 200, 30)]
    t = trade(fills)
    ledger = ref.position_ledger(t, fills)
    assert ledger["values"]["realized_pnl"] == 190
    result = ref.option_path(t, fills, [bar(1, 1.1, 1), bar(11, 2, 1.1), bar(29, 2, 1.1)])
    assert result["values"]["option_peak_total_pnl"] == 190
    assert result["values"]["option_peak_unrealized_pnl"] == 100
    assert result["values"]["option_giveback_from_peak"] == 0
    assert result["samples"][1]["quantity"] == 1
    assert result["samples"][1]["realized"] == 90


def test_reference_applies_documented_financial_rounding():
    fills = [fill(price=160), fill("sell_to_close", price=225, minute=20)]
    assert ref.position_ledger(trade(fills), fills)["values"]["pnl_pct"] == 0.4063


@pytest.mark.parametrize("high,expected", [(2.000000001,None), (2.0000001,-100000000)])
def test_reference_capture_needs_a_positive_peak_at_persisted_precision(high, expected):
    fills = [fill(price=200), fill("sell_to_close", price=190, minute=10)]
    result = ref.option_path(trade(fills), fills, [bar(1, high, 1.9)])["values"]
    assert result["option_exit_efficiency"] == expected
    assert result["time_to_option_mfe_minutes"] == (None if expected is None else 1)


@pytest.mark.parametrize("short", [False, True])
def test_random_position_paths_and_fifo_match_independent_decimal_reference(short):
    rng = random.Random(731)
    for _ in range(40):
        opening, closing = ("sell_to_open", "buy_to_close") if short else ("buy_to_open", "sell_to_close")
        q1, q2 = rng.randint(1, 10), rng.randint(1, 8)
        partial = rng.randint(1, q1 + q2 - 1)
        fills = [fill(opening, q1, rng.randint(40, 200)), fill(opening, q2, rng.randint(40, 200), 7),
                 fill(closing, partial, rng.randint(40, 200), 15), fill(closing, q1 + q2 - partial, rng.randint(40, 200), 25)]
        t = trade(fills)
        ledger = ref.position_ledger(t, fills)
        t.update(ledger["values"])
        bars = [bar(m, rng.uniform(1.2, 2.8), rng.uniform(0.2, 1)) for m in range(1, 25)]
        expected = ref.option_path(t, fills, bars)["values"]
        models = [Fill.model_validate(f) for f in fills]
        actual = trade_path.option_position_path(Trade.model_validate(t), models, bars)
        for key, value in expected.items():
            assert actual[key] == pytest.approx(value, abs=0.000001) if value is not None else actual[key] is None
        inputs = [FillInput(id=f.id, account_id=f.account_id, ticker=f.ticker, instrument_type=f.instrument_type,
                           side=f.side, contracts=Decimal(str(f.contracts)), price=Decimal(str(f.price)), executed_at=f.executed_at,
                           option_type=f.option_type, strike=Decimal(str(f.strike)), expiration=f.expiration) for f in models]
        reconstructed = reconstruct(inputs, today=date(2026, 9, 24)).trades[0]
        for key, value in ledger["values"].items():
            assert float(getattr(reconstructed, key)) == pytest.approx(value, abs=0.000001) if value is not None else getattr(reconstructed, key) is None


def test_entry_reference_excludes_unfinished_and_future_bars():
    f = fill()
    f["executed_at"] = "2026-09-24T09:31:00"
    bars = [dict(t="2026-09-24T13:30:00Z", o=100, h=105, l=99, c=101, v=100),
            dict(t="2026-09-24T13:31:00Z", o=101, h=900, l=1, c=500, v=100000)]
    expected = ref.entry_context(f, bars)["values"]
    assert expected == ref.entry_context(f, bars[:1])["values"]
    actual = analyze_minute_bars(bars, datetime(2026, 9, 24, 9, 31))
    for key, value in expected.items():
        assert actual[key].isoformat() == value if key == "entry_context_as_of" else actual[key] == value


def test_independent_daily_recurrences_match_production_and_ignore_fill_day():
    rng = random.Random(404)
    start = datetime(2026, 1, 1)
    bars = []
    for offset in range(120):
        close = rng.uniform(90, 110)
        bars.append(dict(t=(start + timedelta(days=offset)).strftime("%Y-%m-%dT05:00:00Z"),
                         o=close, h=close+2, l=close-1, c=close, v=100))
    fill_time = start + timedelta(days=100, hours=10)
    result = ref.daily_indicators(bars, fill_time)
    assert result["latest"] == "2026-04-10"
    production = compute_daily_indicators(bars)["2026-04-10"]
    for key, value in production.items():
        assert result["values"][f"entry_{key}"] == pytest.approx(value, abs=0.000001) if value is not None else result["values"][f"entry_{key}"] is None
    bars[100].update(h=99999, c=99998, o=99998)
    assert result == ref.daily_indicators(bars, fill_time)


def test_audit_missing_cache_never_fetches_or_claims_a_match(tmp_path, monkeypatch):
    from app.engine import auditor
    import httpx
    root = tmp_path / "not-created"
    monkeypatch.setattr(auditor, "CACHE_DIR", root)
    monkeypatch.setattr(httpx, "get", lambda *a, **k: pytest.fail("Audit made a network request"))
    fills = [fill(), fill("sell_to_close", price=110, minute=20)]
    t = trade(fills)
    t.update(ref.position_ledger(t, fills)["values"])
    report = compute_audit(Trade.model_validate(t), [Fill.model_validate(f) for f in fills], {}, None)
    assert not root.exists()
    checks = report["validation"]["checks"]
    assert all(c["status"] != "matched" for c in checks if c.get("kind") != "internal_accounting")
    assert report["indicators"]["error"]
    assert report["validation"]["broker_verification"] == "not_performed"


def test_snapshot_validation_detects_changed_pnl_and_retains_missing_status(tmp_path):
    fills = [fill(), fill("sell_to_close", price=110, minute=20)]
    t = trade(fills)
    t.update(ref.position_ledger(t, fills)["values"])
    t["realized_pnl"] = 999
    snapshot = dict(fills=fills, trades=[t], links=[dict(trade_id=t["id"], fill_id=f["id"]) for f in fills])
    report = build_report(snapshot, CachedBars(tmp_path, "iex"))
    check = next(c for c in report["trades"][0]["checks"] if c["field"] == "realized_pnl")
    assert check["status"] == "mismatch"
    assert check["reference"] == 10
    assert report["counts"]["unavailable"] > 0
    assert report["broker_verification"] == "not_performed"


def test_record_serialization_excludes_deferred_email_bodies():
    f = Fill.model_validate(fill())
    f.email_body_text = "private message"
    assert "email_body_text" not in record(f)


def test_invalid_and_duplicate_bars_are_rejected():
    with pytest.raises(ValueError, match="Invalid"):
        ref.normalized_bars([bar(1, high=0.5, low=1)])
    with pytest.raises(ValueError, match="Duplicate"):
        ref.normalized_bars([bar(1), bar(1)])


def test_report_cli_preserves_input_bytes_and_has_no_network(tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(dict(fills=[], trades=[], links=[])))
    before = snapshot.read_bytes()
    result = subprocess.run([sys.executable, "scripts/validate_trade_metrics.py", "--snapshot", str(snapshot),
        "--cache-dir", str(tmp_path / "missing"), "--feed", "iex", "--output", str(tmp_path / "report.json")],
        cwd=Path(__file__).resolve().parents[1], capture_output=True)
    assert result.returncode == 0, result.stderr.decode()
    assert snapshot.read_bytes() == before
    assert not (tmp_path / "missing").exists()
    assert json.loads((tmp_path / "report.json").read_text())["broker_verification"] == "not_performed"


def test_corrupt_cache_is_an_error_without_hiding_valid_accounting(tmp_path, monkeypatch):
    from app.engine import auditor
    monkeypatch.setattr(auditor, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(auditor, "ALPACA_DATA_FEED", "iex")
    cached = tmp_path / "stocks/1Min/iex/AMD/2026-09-24.json"
    cached.parent.mkdir(parents=True)
    cached.write_text("invalid JSON")
    fills = [fill(), fill("sell_to_close", price=110, minute=20)]
    t = trade(fills)
    t.update(ref.position_ledger(t, fills)["values"])
    before = cached.read_bytes()
    report = compute_audit(Trade.model_validate(t), [Fill.model_validate(f) for f in fills], {}, None)
    checks = report["validation"]["checks"]
    assert next(c for c in checks if c["field"] == "realized_pnl")["status"] == "matched"
    assert any(c["status"] == "error" for c in checks)
    assert report["fills"][0]["discrepancies"]
    assert cached.read_bytes() == before


@pytest.mark.parametrize("option_type,side", [("call", "buy_to_open"), ("put", "buy_to_open"), ("call", "sell_to_open"), ("put", "sell_to_open")])
def test_underlying_path_matches_independent_reference(option_type, side, monkeypatch):
    from app.models import FillMarketContext
    fills = [fill(side), fill("buy_to_close" if side == "sell_to_open" else "sell_to_close", price=110, minute=20)]
    for f in fills:
        f["option_type"] = option_type
    t = trade(fills)
    t["option_type"] = option_type
    t.update(ref.position_ledger(t, fills)["values"])
    bars = [bar(m, high=100 + m / 5, low=98 - m / 10) for m in range(21)]
    monkeypatch.setattr(trade_path, "_compute_option_path", lambda *args: None)
    models = [Fill.model_validate(f) for f in fills]
    ctx = FillMarketContext(fill_id=models[0].id, entry_underlying_price=100, data_source="alpaca_iex")
    result = trade_path._compute(Trade.model_validate(t), models, {str(ctx.fill_id): ctx}, {("AMD", "2026-09-24"): bars})
    expected = ref.underlying_path(t, fills[0], bars, 100)["values"]
    for key, value in expected.items():
        assert getattr(result, key) == pytest.approx(value, abs=0.000001) if value is not None else getattr(result, key) is None


def test_short_expiration_independent_ledger():
    fills = [fill("sell_to_open", qty=2, price=200), fill("buy_to_close", qty=1, price=50, minute=20)]
    assert ref.position_ledger(trade(fills, status="expired"), fills)["values"]["realized_pnl"] == 350


def test_stale_and_missing_comparisons_cannot_pass():
    assert ref.compare_values({"x": 1}, {"x": 1}, stale=True)[0]["status"] == "stale"
    assert ref.compare_values({"x": None}, {"x": None})[0]["status"] == "unavailable"
    assert ref.compare_values({"x": 1}, {"x": 1}, unavailable_reason="wrong feed")[0]["status"] == "unavailable"


def test_html_report_escapes_source_records_and_shows_observed_evidence(tmp_path):
    from app.engine.metric_report import html_report
    fills = [fill(), fill("sell_to_close", price=110, minute=20)]
    t = trade(fills)
    t.update(ref.position_ledger(t, fills)["values"])
    t["ticker"] = "<script>bad()</script>"
    snapshot = dict(fills=fills, trades=[t], links=[dict(trade_id=t["id"], fill_id=f["id"]) for f in fills])
    report = build_report(snapshot, CachedBars(tmp_path, "iex"))
    html = html_report(report)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "Broker verification has not been performed" in html
    assert fills[0]["id"] in html
