"""Contract checks for docs/pine/isaac_market_map.pine.

Pine cannot run here, so these tests read the script and rebuild what it
would emit from its own source: the alert JSON's keys and value helpers, the
alert_id template, the number format, and the Strategy Lab sl1 comments. Each
rebuilt payload then goes through the real v1 parser or CSV importer. Keys,
setups and templates are extracted from the script, never listed here, so a
new key or setup is checked the first time it is added.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.engine.strategy_csv import parse_tradingview_csv
from app.engine.tradingview import canonical_alert_id, parse_alert_bytes

PINE_PATH = Path(__file__).resolve().parents[2] / "docs" / "pine" / "isaac_market_map.pine"
SOURCE = PINE_PATH.read_text(encoding="utf-8")

SAMPLE_BAR_TIME_MS = 1_789_392_900_000
SAMPLE_SYMBOL = "NBIS"
SAMPLE_TIMEFRAME = "5"
SAMPLE_NUMBERS = [214.32, 1.8234567, -0.3125, 0.0000004, 12345.678901234, 3.0]


def _function_body(name: str) -> str:
    lines = SOURCE.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{name}("))
    body = []
    for line in lines[start + 1 :]:
        if line and not line.startswith(" "):
            break
        body.append(line)
    return "\n".join(body)


def _kv_fields(function: str) -> list[tuple[str, str]]:
    return re.findall(r'f_kv\("([^"]+)", ("?\w+)', _function_body(function))


def _sl1_fields(function: str) -> list[tuple[str, str]]:
    return re.findall(r'f_sl1\("([^"]+)", (\w+)', _function_body(function))


def _setups() -> set[str]:
    return set(
        re.findall(
            r'(?:longSetup|shortSetup|retestLongName|retestShortName) := "([^"]+)"',
            SOURCE,
        )
    )


def _default_indicator_version() -> str:
    match = re.search(r'indicatorVersion = input\.string\("([^"]+)"', SOURCE)
    assert match, "indicatorVersion input not found"
    return match.group(1)


def _pine_number(value: float | None) -> str:
    if value is None:
        return "null"
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _render(helper: str, index: int) -> str:
    if helper == "f_num":
        values = [*SAMPLE_NUMBERS, None]
        return _pine_number(values[index % len(values)])
    if helper == "f_bool":
        return "true" if index % 2 else "false"
    if helper == "f_text":
        return json.dumps("sample")
    raise AssertionError(f"unknown JSON helper {helper}")


def _snapshot_json(function: str) -> str:
    fields = _kv_fields(function)
    assert fields, f"{function} emits no fields"
    return "{" + ",".join(f'"{key}":{_render(helper, i)}' for i, (key, helper) in enumerate(fields)) + "}"


def _alert_id(setup: str, side: str) -> str:
    match = re.search(r"string alertId = (.+)", _function_body("f_alertJson"))
    assert match, "alertId template not found"
    values = {
        "indicatorVersion": _default_indicator_version(),
        "tickerSymbol": SAMPLE_SYMBOL,
        "timeframeText": SAMPLE_TIMEFRAME,
        "barTimeText": str(SAMPLE_BAR_TIME_MS),
        "setup": setup,
        "side": side,
    }
    parts = []
    for token in (part.strip() for part in match.group(1).split("+")):
        if token.startswith('"'):
            parts.append(json.loads(token))
        else:
            parts.append(values[token])
    return "".join(parts)


def _alert_body(setup: str, side: str) -> bytes:
    top_level = {
        "v": "1",
        "indicator_version": json.dumps(_default_indicator_version()),
        "alert_id": json.dumps(_alert_id(setup, side)),
        "symbol": json.dumps(SAMPLE_SYMBOL),
        "timeframe": json.dumps(SAMPLE_TIMEFRAME),
        "setup": json.dumps(setup),
        "side": json.dumps(side),
        "price": _pine_number(214.32),
        "bar_time_ms": str(SAMPLE_BAR_TIME_MS),
        "levels": _snapshot_json("f_levelsJson"),
        "context": _snapshot_json("f_contextJson"),
    }
    emitted = [key for key, _ in _kv_fields("f_alertJson")]
    assert emitted == list(top_level), "f_alertJson top-level fields changed; update this rebuild"
    return ("{" + ",".join(f'"{k}":{v}' for k, v in top_level.items()) + "}").encode()


def test_number_format_is_the_one_emulated_here() -> None:
    assert re.search(r'str\.tostring\(value, "#\.######"\)', _function_body("f_num"))
    assert 'na(value) ? "null"' in _function_body("f_num")


def test_setups_are_extracted() -> None:
    assert {"orb_break", "orb_retest", "pdh_break", "vwap_reclaim", "orb_fail"} <= _setups()


@pytest.mark.parametrize("side", ["long", "short"])
@pytest.mark.parametrize("setup", sorted(_setups()))
def test_every_setup_emits_a_payload_the_v1_parser_accepts(setup: str, side: str) -> None:
    parsed = parse_alert_bytes(_alert_body(setup, side))

    assert parsed.setup == setup
    assert parsed.side == side
    assert parsed.bar_time_ms == SAMPLE_BAR_TIME_MS
    assert parsed.alert_id == canonical_alert_id(
        indicator_version=_default_indicator_version(),
        symbol=SAMPLE_SYMBOL,
        timeframe=SAMPLE_TIMEFRAME,
        bar_time_ms=SAMPLE_BAR_TIME_MS,
        setup=setup,
        side=side,
    )
    assert set(parsed.levels) == {key for key, _ in _kv_fields("f_levelsJson")}
    assert set(parsed.context) == {key for key, _ in _kv_fields("f_contextJson")}


def test_sl1_comments_import_cleanly_into_strategy_lab() -> None:
    entry_fields = _sl1_fields("f_entryComment")
    exit_fields = re.findall(r'f_sl1\("([^"]+)", (\w+)', _function_body("f_exitComment"))
    entry_keys = [key for key, _ in entry_fields]
    exit_keys = [key for key, _ in exit_fields]
    assert len(entry_keys) == len(set(entry_keys))
    assert not set(entry_keys) & set(exit_keys), "a shared key would raise a merge conflict"

    def comment(fields: list[tuple[str, str]]) -> str:
        values = []
        for i, (key, expr) in enumerate(fields):
            value = _render("f_num", i) if expr == "f_num" else "orb_break"
            values.append(f"{key}={value}")
        return "sl1|" + "|".join(values)

    header = "Trade #,Type,Signal,Date/Time,Price USD,Contracts,Profit USD"
    rows = [
        header,
        f"1,Exit long,{comment(exit_fields)},2026-09-14 09:50,210.10,5,12.50",
        f"1,Entry long,{comment(entry_fields)},2026-09-14 09:40,207.60,5,12.50",
    ]
    result = parse_tradingview_csv(("\n".join(rows) + "\n").encode(), "America/New_York")

    assert result.accepted_count == 1
    assert result.rejected_count == 0
    assert not result.warnings, [issue.message for issue in result.warnings]
    assert set(result.trades[0].feature_snapshot) == set(entry_keys) | set(exit_keys)
