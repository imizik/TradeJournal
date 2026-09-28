"""The strategy factory script end to end, with a stub minute source.

The stub serves a random walk (one bar every 15 minutes, in Alpaca's bar
format) for two tickers and SPY from June 2023 to September 2024, the
discovery period only. It also checks that the committed specs and ledger
parse, and that the NBIS spec keeps the id its hand-research ledger line uses.
"""

from __future__ import annotations

import importlib.util
import json
import random
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.engine.factory_data import NYSE_EARLY_CLOSES
from app.engine.factory_gates import required_t
from app.engine.factory_rules import parse_spec, spec_id
from app.engine.market_map import ET

BACKEND = Path(__file__).resolve().parents[1]
RESEARCH = BACKEND.parent / "research"
FIRST, LAST = date(2023, 6, 1), date(2024, 9, 30)


def _load_script():
    path = BACKEND / "scripts" / "strategy_factory.py"
    spec = importlib.util.spec_from_file_location("strategy_factory_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def walk(seed: int, first: date, last: date) -> dict[date, list[dict]]:
    rng = random.Random(seed)
    price, days, day = 100.0, {}, first
    while day <= last:
        if day.weekday() < 5:
            rows = []
            for k in range(26):
                minute = 570 + 15 * k
                moment = datetime(day.year, day.month, day.day, minute // 60, minute % 60, tzinfo=ET)
                close = price * (1 + rng.gauss(0, 0.004))
                rows.append({
                    "t": moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "o": price, "h": max(price, close) * (1 + abs(rng.gauss(0, 0.001))),
                    "l": min(price, close) * (1 - abs(rng.gauss(0, 0.001))), "c": close, "v": 1000 + 500 * rng.random(),
                })
                price = close
            days[day] = rows
        day += timedelta(days=1)
    return days


class StubSource:
    feed = "sip"

    def __init__(self, last: date = LAST):
        self.data = {ticker: walk(seed, FIRST, last) for seed, ticker in enumerate(("AAA", "BBB", "SPY"))}
        self.calls = 0

    def days(self, ticker: str) -> list[date]:
        return sorted(self.data.get(ticker, {}))

    def minute_bars(self, ticker: str, day: date) -> list[dict]:
        self.calls += 1
        return self.data.get(ticker, {}).get(day, [])


def write_spec(path: Path, **extra) -> Path:
    path.write_text(json.dumps({"name": "test swing", "family": "recovery_swing", "tickers": ["AAA", "BBB"], **extra}))
    return path


def read_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.fixture
def script(monkeypatch):
    monkeypatch.setenv("ALPACA_DATA_FEED", "sip")  # main() sets it; this restores it afterwards
    return _load_script()


def test_the_bar_store_builds_once_and_rebuilds_when_new_days_arrive(script, tmp_path):
    source = StubSource()
    series = script.BarStore(source, tmp_path).load("AAA", 15, None)
    days = source.days("AAA")
    half_days = [day for day in days if day in NYSE_EARLY_CLOSES]  # 2023-07-03, 2023-11-24, 2024-07-03
    assert len(half_days) == 3 and len(series) == 26 * len(days) - 12 * len(half_days)
    assert source.calls == len(days)
    assert (tmp_path / "bars" / "sip" / "AAA_15m.pkl").exists()
    again = script.BarStore(source, tmp_path)
    assert again.load("AAA", 15, date(2024, 1, 31)).days[-1] == date(2024, 1, 31)
    assert source.calls == len(source.days("AAA"))  # read from the pickle
    newer = StubSource(last=date(2024, 10, 4))
    assert script.BarStore(newer, tmp_path).load("AAA", 15, None).days[-1] == date(2024, 10, 4)
    assert newer.calls == len(newer.days("AAA"))


def test_run_judges_a_spec_records_it_and_skips_a_repeat(script, tmp_path, capsys):
    ledger, out = tmp_path / "ledger.jsonl", tmp_path / "out"
    spec_path = write_spec(tmp_path / "spec.json")
    args = ["--ledger", str(ledger), "--out", str(out), "run", str(spec_path)]
    assert script.main(args, source_factory=StubSource) == 0
    (record,) = read_lines(ledger)
    assert record["id"] == spec_id(parse_spec(json.loads(spec_path.read_text())))
    assert (record["source"], record["name"], record["verdict"]) == ("factory", "test swing", "failed_screen")
    assert record["cache_through"] == LAST.isoformat() and set(record["periods"]) == {"discovery"}
    assert record["reached_confirmation"] is False and record["bar_t"] is None
    (run_dir,) = (out / "runs").iterdir()
    assert "Verdict: failed the screen" in (run_dir / "report.txt").read_text()
    rows = (run_dir / "trades.csv").read_text().splitlines()
    assert rows[0].startswith("ticker,period,side,signal_time") and len(rows) - 1 == record["periods"]["discovery"]["n"]
    assert "Verdict: failed the screen" in capsys.readouterr().out

    assert script.main(args, source_factory=StubSource) == 0
    assert "already in the ledger: failed_screen" in capsys.readouterr().out
    assert len(read_lines(ledger)) == 1
    assert script.main([*args, "--rerun"], source_factory=StubSource) == 0
    assert [r["id"] for r in read_lines(ledger)] == [record["id"]] * 2


def test_a_hand_research_line_does_not_block_its_spec(script, tmp_path):
    ledger, out = tmp_path / "ledger.jsonl", tmp_path / "out"
    spec_path = write_spec(tmp_path / "spec.json")
    identifier = spec_id(parse_spec(json.loads(spec_path.read_text())))
    ledger.write_text(json.dumps({"id": identifier, "source": "hand research", "reached_confirmation": True,
                                  "verdict": "failed_confirmation", "name": "by hand"}) + "\n")
    assert script.main(["--ledger", str(ledger), "--out", str(out), "run", str(spec_path)], source_factory=StubSource) == 0
    assert [r["source"] for r in read_lines(ledger)] == ["hand research", "factory"]


def test_a_model_spec_has_its_parent_judged_first(script, tmp_path):
    ledger, out = tmp_path / "ledger.jsonl", tmp_path / "out"
    spec_path = write_spec(tmp_path / "learned.json", model={"kind": "logistic"}, name="test swing, learned")
    assert script.main(["--ledger", str(ledger), "--out", str(out), "run", str(spec_path)], source_factory=StubSource) == 0
    parent, learned = read_lines(ledger)
    assert parent["model"] is None and learned["parent"] == parent["id"]
    assert learned["model"]["trained_on"] == parent["periods"]["discovery"]["n"]
    # The screen is in-sample for a trained model, so it goes to confirmation and counts toward the bar;
    # the stub has no bars after September 2024, so confirmation has nothing to go on.
    assert (learned["verdict"], learned["reached_confirmation"]) == ("failed_confirmation", True)
    assert learned["bar_t"] == pytest.approx(required_t(1))


def test_the_ledger_command_prints_the_count_and_the_bar(script, capsys):
    assert script.main(["ledger"]) == 0
    text = capsys.readouterr().out
    count = sum(1 for r in read_lines(RESEARCH / "ledger.jsonl") if r["reached_confirmation"])
    assert f"the next one there needs t >= {required_t(count + 1):.2f}" in text


def test_the_committed_specs_parse_and_keep_their_ids():
    specs = {path.stem: parse_spec(json.loads(path.read_text())) for path in sorted((RESEARCH / "specs").glob("*.json"))}
    assert {"recovery_swing_v0.1", "recovery_swing_v0.1_logistic", "vwap_reclaim_v0.1", "failed_breakout_v0.1"} <= set(specs)
    # The ledger's hand-research line for the NBIS swing shares this id, so it is counted once.
    assert spec_id(specs["recovery_swing_v0.1"]) == "re-d5194badb1"
    assert spec_id(specs["recovery_swing_v0.1_logistic"].parent()) == "re-d5194badb1"


def test_the_committed_ledger_is_well_formed():
    records = read_lines(RESEARCH / "ledger.jsonl")
    for record in records:
        assert {"id", "name", "source", "verdict", "reached_confirmation"} <= set(record), record
        assert record["source"] in ("factory", "hand research")
    assert sum(r["source"] == "hand research" for r in records) == 9
