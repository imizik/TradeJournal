"""Contract checks for docs/pine/intraday_reclaim.pine.

Pine cannot run here, so these tests read the script and rebuild what it
emits from its own source: the baseline preset, the Strategy Lab sl1
comments, the research alert JSON and the setup id. The rebuilt output then
goes through the real Strategy Lab importer, the research report
(scripts/pine_research_report.py) and the v1 webhook parser, which must reject
it. Keys and event names are extracted from the script, so a new one is
checked the first time it is added.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

from app.engine.strategy_csv import parse_tradingview_csv
from app.engine.tradingview import TradingViewContractError, parse_alert_bytes

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = (REPO_ROOT / "docs" / "pine" / "intraday_reclaim.pine").read_text(encoding="utf-8")
REPORT_PATH = REPO_ROOT / "backend" / "scripts" / "pine_research_report.py"

# The v0.1 defaults proposed in docs/pine/research-framework.md ("First
# build"). The script's preset must match them; changing one is a new version.
FRAMEWORK_BASELINE = {
    "BASE_EMA_LENGTH": 9,
    "BASE_ATR_LENGTH": 14,
    "BASE_STOP_BUFFER_ATR": 0.1,
    "BASE_CHASE_LIMIT_ATR": 1.0,
    "BASE_CONFIRM_BARS": 3,
    "BASE_TARGET_R": 1.5,
    "BASE_MAX_HOLD_MIN": 20,
    "BASE_ENTRY_START": 935,
    "BASE_ENTRY_END": 1500,
    "BASE_MAX_ENTRIES": 2,
    "BASE_MAX_LOSSES": 2,
    "BASE_MAX_SESSION_LOSS_R": 2.0,
}
SPEC_ALERT_FIELDS = {"ticker", "exchange", "bar_close_ms", "version", "setup_id"}
EXPORT_HEADER = (
    "Trade number,Type,Date and time,Signal,Price USD,Size (qty),Size (value),Net PnL USD,"
    "Return %,Commission USD,Favorable excursion USD,Favorable excursion %,"
    "Adverse excursion USD,Adverse excursion %,Cumulative PnL USD,Cumulative PnL %,Duration (bars)"
)
ARM_MS = 1_789_392_840_000


def _function_body(name: str) -> str:
    lines = SOURCE.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{name}("))
    body = []
    for line in lines[start + 1 :]:
        if line and not line.startswith(" "):
            break
        body.append(line)
    return "\n".join(body)


def _const(name: str) -> str:
    match = re.search(rf'^const \w+ {name} = "?([^"\n]+)"?$', SOURCE, re.MULTILINE)
    assert match, f"{name} not found"
    return match.group(1)


VERSION = _const("VERSION")


def _setup_id(side: str, ticker: str = "MU") -> str:
    tokens = [part.strip() for part in _function_body("f_setupId").strip().split(" + ")]
    values = {
        "VERSION": VERSION,
        "exchangeName": "NASDAQ",
        "tickerSymbol": ticker,
        "timeframeText": "1",
        'str.tostring(armCloseMs, "#")': str(ARM_MS),
        '(dir == 1 ? "long" : "short")': side,
    }
    parts = []
    for token in tokens:
        if token.startswith('"'):
            parts.append(json.loads(token))
        else:
            assert token in values, f"f_setupId changed ({token!r}); update this rebuild and the report"
            parts.append(values[token])
    return "".join(parts)


def _sl1_fields(function: str) -> list[tuple[str, str]]:
    return re.findall(r'f_sl1\("([^"]+)", (\w+)', _function_body(function))


def _entry_comment(values: dict[str, str]) -> str:
    rendered = []
    for key, helper in _sl1_fields("f_entryComment"):
        default = "0.5" if helper == "f_num" else "1" if helper == "f_int" else "sample"
        rendered.append(f"{key}={values.get(key, default)}")
    return "sl1|" + "|".join(rendered)


def _exit_comment(reason: str) -> str:
    fields = _sl1_fields("f_exitComment")
    assert fields == [("exit_reason", "reason")], "f_exitComment changed; update this rebuild"
    return f"sl1|exit_reason={reason}"


# (side, signal close, stop, fill, qty, exit price, exit reason, expected R)
SAMPLE_TRADES = [
    ("long", 100.00, 99.50, 100.00, 200, 100.75, "target", 1.5),
    ("long", 100.00, 99.50, 100.02, 200, 99.49, "stop", (99.49 - 100.02) / 0.52),
    ("short", 50.00, 50.30, 50.00, 333, 49.90, "time", 0.10 / 0.30),
    ("short", 50.00, 50.30, 50.00, 333, 50.12, "session", -0.12 / 0.30),
]


def _export_csv() -> bytes:
    rows = [EXPORT_HEADER]
    for number, (side, signal_close, stop, fill, qty, exit_price, reason, _) in enumerate(SAMPLE_TRADES, 1):
        direction = 1 if side == "long" else -1
        pnl = round(direction * (exit_price - fill) * qty, 2)
        entry = _entry_comment(
            {
                "ver": VERSION,
                "variant": "baseline",
                "cfg": "ema9_atr14_buf0.1_chase1_win3_tgt1.5_hold20_t935-1500_ent2_loss2_dd2_dirboth_risk100",
                "setup_id": _setup_id(side),
                "signal_close": str(signal_close),
                "stop": str(stop),
                "target_r": "1.5",
                "risk_ps": f"{direction * (signal_close - stop):.2f}",
                "tick": "0.01",
            }
        )
        day = f"2026-09-{number + 13:02d}"
        tail = f"{qty},{fill * qty:.2f},{pnl},0.1,0,1,0.01,-1,-0.01,{pnl},0.01,5"
        rows.append(f"{number},Exit {side},{day} 10:05,{_exit_comment(reason)},{exit_price},{tail}")
        rows.append(f"{number},Entry {side},{day} 09:50,{entry},{fill},{tail}")
    return ("\n".join(rows) + "\n").encode()


def _load_report():
    spec = importlib.util.spec_from_file_location("pine_research_report", REPORT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    keys = [key for key, _ in pairs]
    assert len(keys) == len(set(keys)), f"duplicate keys in {keys}"
    return dict(pairs)


def _event_json(event: str) -> str:
    fields = re.findall(r'f_kv\("([^"]+)", (\w+)\(', _function_body("f_event"))
    samples = {"f_text": '"sample"', "f_textOrNull": "null", "f_int": str(ARM_MS), "f_num": "214.32"}
    rendered = []
    for key, helper in fields:
        assert helper in samples, f"f_event uses an unknown helper {helper}"
        rendered.append(f'"{key}":{json.dumps(event) if key == "event" else samples[helper]}')
    return "{" + ",".join(rendered) + "}"


def test_baseline_preset_is_the_framework_default() -> None:
    declared = {
        name: float(value)
        for name, value in re.findall(r"^const (?:int|float) (BASE_\w+) = ([\d.]+)$", SOURCE, re.MULTILINE)
    }
    assert declared == {name: float(value) for name, value in FRAMEWORK_BASELINE.items()}
    for name in FRAMEWORK_BASELINE:
        assert re.search(rf"usePreset \? {name} : \w+Input$", SOURCE, re.MULTILINE), f"{name} is not applied"
        assert re.search(rf"input\.(?:int|float)\({name},", SOURCE), f"{name}'s input does not start at it"


def test_title_carries_the_version() -> None:
    major_minor = ".".join(VERSION.split(".")[:2])
    assert re.match(rf'strategy\("Intraday Reclaim v{re.escape(major_minor)}"', SOURCE.splitlines()[1])


def test_variant_label_cannot_break_metadata_or_json() -> None:
    match = re.search(r'str\.match\(variantInput, "([^"]+)"\)', SOURCE)
    assert match, "the variant label is no longer validated"
    pattern = re.compile(match.group(1))
    assert pattern.fullmatch("tight-stop_v2.1")
    for unsafe in ("a|b", "a=b", 'a"b', "a b", ""):
        assert not pattern.fullmatch(unsafe)


def test_setup_id_is_what_the_report_parses() -> None:
    report = _load_report()
    parsed = report.parse_setup_id(_setup_id("short", ticker="META"))
    assert parsed == {
        "prefix": "ir",
        "version": VERSION,
        "exchange": "NASDAQ",
        "ticker": "META",
        "timeframe": "1",
        "arm_ms": str(ARM_MS),
        "side": "short",
    }


def test_metadata_imports_cleanly_into_strategy_lab() -> None:
    entry_keys = [key for key, _ in _sl1_fields("f_entryComment")]
    assert len(entry_keys) == len(set(entry_keys))
    assert "exit_reason" not in entry_keys, "a shared key would raise a merge conflict"

    result = parse_tradingview_csv(_export_csv(), "America/New_York")

    assert result.accepted_count == len(SAMPLE_TRADES)
    assert result.rejected_count == 0
    assert not result.warnings, [issue.message for issue in result.warnings]
    for trade in result.trades:
        assert set(trade.feature_snapshot) == set(entry_keys) | {"exit_reason"}


def test_report_computes_r_from_the_actual_fill(tmp_path: Path) -> None:
    report = _load_report()
    assert set(report.REQUIRED_KEYS) - {"exit_reason"} <= {key for key, _ in _sl1_fields("f_entryComment")}
    export = tmp_path / "IR_NASDAQ_MU.csv"
    export.write_bytes(_export_csv())

    trades, problems = report.load_trades([str(export)], "America/New_York")

    assert problems == []
    assert [t.exit_reason for t in trades] == [sample[6] for sample in SAMPLE_TRADES]
    for trade, sample in zip(trades, SAMPLE_TRADES):
        assert trade.r == pytest.approx(sample[7], abs=1e-3)
        assert trade.ticker == "MU"
        assert f"v{VERSION} baseline tf=1" in trade.config
    slipped_stop = trades[1]
    assert slipped_stop.entry_slip_r == pytest.approx(0.04)
    assert slipped_stop.overshoot_r == pytest.approx(0.01 / 0.52)
    assert trades[0].target == pytest.approx(100.75)

    totals = report.metrics(trades)
    expected_total = sum(sample[7] for sample in SAMPLE_TRADES)
    assert totals["total"] == pytest.approx(expected_total, abs=1e-3)
    assert totals["without_best_trade"] == pytest.approx(expected_total - 1.5, abs=1e-3)
    assert totals["stress_1"] < totals["total"]


def test_report_runs_end_to_end(tmp_path: Path, monkeypatch, capsys) -> None:
    report = _load_report()
    (tmp_path / "IR_NASDAQ_MU.csv").write_bytes(_export_csv())
    monkeypatch.setattr(sys, "argv", ["report", str(tmp_path / "IR_*.csv"), "--replay", "2"])

    report.main()

    output = capsys.readouterr().out
    assert "trades 4 over 4 sessions" in output
    assert "replay checklist: 2 winners, 2 losers" in output


def test_every_event_is_research_json_that_the_v1_ingress_rejects() -> None:
    events = set(re.findall(r'f_event\("([a-z_]+)"', SOURCE))
    assert {"armed", "cancelled", "triggered", "filled", "exit_signal", "closed"} <= events
    keys = [key for key, _ in re.findall(r'f_kv\("([^"]+)", (\w+)\(', _function_body("f_event"))]
    assert SPEC_ALERT_FIELDS <= set(keys)
    assert "v" not in keys, "a v key would put research alerts on the live contract"

    for event in sorted(events):
        payload = _event_json(event)
        body = json.loads(payload, object_pairs_hook=_unique_keys)
        assert body["event"] == event
        with pytest.raises(TradingViewContractError):
            parse_alert_bytes(payload.encode())
