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

from app.engine.factory_brief import SYSTEM_PROMPT
from app.engine.factory_data import NYSE_EARLY_CLOSES
from app.engine.factory_gates import required_t
from app.engine.factory_rules import canonical, parse_spec, spec_id
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
    """A random walk for any ticker asked for, one bar every 15 minutes."""

    feed = "sip"
    seeds = {"AAA": 0, "BBB": 1, "SPY": 2}

    def __init__(self, last: date = LAST):
        self.last = last
        self.data: dict[str, dict[date, list[dict]]] = {}
        self.calls = 0

    def _walk(self, ticker: str) -> dict[date, list[dict]]:
        if ticker not in self.data:
            self.data[ticker] = walk(self.seeds.get(ticker, sum(map(ord, ticker))), FIRST, self.last)
        return self.data[ticker]

    def days(self, ticker: str) -> list[date]:
        return sorted(self._walk(ticker))

    def minute_bars(self, ticker: str, day: date) -> list[dict]:
        self.calls += 1
        return self._walk(ticker).get(day, [])


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
    assert not (run_dir / "trades_confirm.csv").exists()
    rows = (run_dir / "trades_discovery.csv").read_text().splitlines()
    assert rows[0].startswith("ticker,period,side,signal_time") and len(rows) - 1 == record["periods"]["discovery"]["n"]
    printed = capsys.readouterr().out
    assert "Verdict: failed the screen" in printed
    assert f"The ledger counts 0 candidates at confirmation; the next one there needs t >= {required_t(1):.2f}." in printed

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
    # The ledger's hand-research line for the NBIS swing shares this id, so it is counted once, and
    # every judged spec keeps the id the ledger recorded for it.
    assert spec_id(specs["recovery_swing_v0.1"]) == "re-d5194badb1"
    assert spec_id(specs["recovery_swing_v0.1_logistic"].parent()) == "re-d5194badb1"
    assert [spec_id(specs[name]) for name in ("recovery_swing_v0.1_logistic", "vwap_reclaim_v0.1", "failed_breakout_v0.1")] == [
        "re-5c58b4e869", "vw-3d24a7243d", "fa-72fca93262"]


def test_the_committed_ledger_is_well_formed():
    records = read_lines(RESEARCH / "ledger.jsonl")
    for record in records:
        assert {"id", "name", "source", "verdict", "reached_confirmation"} <= set(record), record
        assert record["source"] in ("factory", "hand research")
    assert sum(r["source"] == "hand research" for r in records) == 9


# --- the weekly loop -------------------------------------------------------------------


def weekly_paths(tmp_path: Path) -> tuple[dict[str, Path], list[str]]:
    paths = {name: tmp_path / name for name in ("ledger.jsonl", "out", "reports", "specs")}
    args = ["--ledger", str(paths["ledger.jsonl"]), "--out", str(paths["out"]), "--reports", str(paths["reports"]),
            "--specs", str(paths["specs"])]
    return paths, args


def weekly_idea(title: str, spec: dict) -> dict:
    return {"title": title, "hypothesis": f"{title}: a reason.", "builds_on": "re-d5194badb1", "change": "one thing",
            "from_evidence": False, "spec_json": json.dumps(spec)}


ANSWER = {
    "ideas": [weekly_idea("Daily EMA reclaim", {"family": "recovery_swing", "params": {"reclaim_level": "daily_ema"}}),
              weekly_idea("Cheap", {"family": "recovery_swing", "costs": {"slippage_bps": 0}})],
    "lessons": "Nothing has passed yet.",
    "wanted": ["an opening-range family"],
}


def test_week_asks_for_ideas_judges_them_and_reports(script, tmp_path):
    paths, args = weekly_paths(tmp_path)
    asked: list[tuple[str, str]] = []

    def proposer(system: str, text: str):
        asked.append((system, text))
        return ANSWER, "a stub model, 10 tokens in and 5 out"

    assert script.main([*args, "week"], source_factory=StubSource, proposer=proposer) == 0
    ((system, text),) = asked
    assert system == SYSTEM_PROMPT and "Propose up to 3 new candidates this week." in text
    assert '"recovery_swing"' in text and "## Discovery evidence" in text
    today = datetime.now(ET).date()
    (record,) = read_lines(paths["ledger.jsonl"])
    batch = script.week_start(today).isoformat()
    assert (record["name"], record["batch"], record["source"]) == ("Daily EMA reclaim", batch, "factory")
    saved = json.loads((paths["specs"] / today.isoformat() / "daily-ema-reclaim.json").read_text())
    assert spec_id(parse_spec(saved)) == record["id"] and "tickers" not in saved
    markdown = (paths["reports"] / f"{today}.md").read_text()
    assert "### 1. Daily EMA reclaim" in markdown and "- Cheap: it changes the costs." in markdown
    assert "Nothing has passed yet." in markdown and "- an opening-range family" in markdown
    assert "Idea model: a stub model, 10 tokens in and 5 out." in markdown
    week = json.loads((paths["reports"] / f"{today}.json").read_text())
    assert week["answer"] == ANSWER and week["passed"] is False and week["summary"].startswith("1 idea judged")
    assert (paths["out"] / "evidence").is_dir()  # cached for next week

    # The same week again: one of three used, and the same idea is now in the ledger.
    asked.clear()
    assert script.main([*args, "week"], source_factory=StubSource, proposer=proposer) == 0
    assert "Propose up to 2 new candidates this week." in asked[0][1]
    assert len(read_lines(paths["ledger.jsonl"])) == 1
    # A second report the same day gets its own name; the first is kept.
    assert "- Daily EMA reclaim: the same rules are already in the ledger." in (paths["reports"] / f"{today}b.md").read_text()
    assert "### 1. Daily EMA reclaim" in (paths["reports"] / f"{today}.md").read_text()


def test_week_stops_when_the_budget_is_used_and_dry_run_only_prints(script, tmp_path, capsys):
    paths, args = weekly_paths(tmp_path)

    def proposer(system: str, text: str):
        raise AssertionError("the idea model should not be asked")

    assert script.main([*args, "week", "--dry-run"], source_factory=StubSource, proposer=proposer) == 0
    printed = capsys.readouterr().out
    assert printed.startswith(SYSTEM_PROMPT) and "Propose up to 3 new candidates" in printed
    assert not paths["reports"].exists() and not paths["ledger.jsonl"].exists()
    paths["ledger.jsonl"].write_text(used_week(script))
    assert script.main([*args, "week"], source_factory=StubSource, proposer=proposer) == 0
    assert "budget of 3 candidates is already used" in capsys.readouterr().out


def used_week(script) -> str:
    """Three ledger lines from this week's weekly run, as the factory writes them."""
    batch = script.week_start(datetime.now(ET).date()).isoformat()
    lines = []
    for k in range(3):
        spec = parse_spec({"family": "recovery_swing", "tickers": ["AAA", "BBB"], "params": {"arm_sessions": 3 + k}})
        lines.append(json.dumps({"id": spec_id(spec), "name": f"used {k}", "source": "factory", "spec": canonical(spec),
                                 "verdict": "failed_screen", "reached_confirmation": False, "batch": batch}) + "\n")
    return "".join(lines)


def test_the_week_runs_sunday_to_saturday(script):
    tuesday, sunday = date(2026, 9, 29), date(2026, 10, 4)
    assert script.week_start(tuesday) == date(2026, 9, 27) and script.week_start(sunday) == sunday
    # The first weekly run, on a Tuesday, tagged its lines with that week's Monday.
    first_run = [{"batch": "2026-09-28"}] * 3 + [{"batch": None}, {"name": "by hand"}]
    assert script.used_this_week(first_run, tuesday) == 3
    assert script.used_this_week(first_run, date(2026, 10, 3)) == 3
    assert script.used_this_week(first_run, sunday) == 0  # the scheduled Sunday run starts a new week


def test_a_claude_code_session_can_answer_the_brief_instead_of_the_api(script, tmp_path, capsys):
    paths, args = weekly_paths(tmp_path)
    paths["ledger.jsonl"].write_text(used_week(script))
    today = datetime.now(ET).date()
    # The week's three are used; a run the user asks for can go past them.
    brief = tmp_path / "brief.md"
    assert script.main([*args, "week", "--dry-run", "--brief-out", str(brief), "--budget", "2"],
                       source_factory=StubSource) == 0
    assert brief.read_text().startswith(SYSTEM_PROMPT) and "Propose up to 2 new candidates this week." in brief.read_text()
    answer = tmp_path / "answer.json"
    answer.write_text(json.dumps(ANSWER))
    assert script.main([*args, "week", "--answer", str(answer), "--answer-by", "Claude Opus 5.5", "--budget", "2"],
                       source_factory=StubSource) == 0
    record = read_lines(paths["ledger.jsonl"])[-1]
    assert (record["name"], record["batch"]) == ("Daily EMA reclaim", script.week_start(today).isoformat())
    assert "Idea model: Claude Opus 5.5 in a Claude Code session, no API call." in (
        paths["reports"] / f"{today}.md").read_text()
    answer.write_text(json.dumps({"ideas": [], "lessons": "none"}))
    with pytest.raises(SystemExit, match="does not fit the format: answer lacks wanted"):
        script.main([*args, "week", "--answer", str(answer), "--budget", "1"], source_factory=StubSource)
    with pytest.raises(SystemExit):
        script.main([*args, "week", "--budget", "0"], source_factory=StubSource)


def test_the_live_ledger_is_written_only_on_the_factory_branch(script, tmp_path, monkeypatch):
    spec_path = write_spec(tmp_path / "spec.json")
    out = ["--out", str(tmp_path / "out")]
    # The default ledger points at a scratch file, so a broken guard cannot write the committed one.
    live = tmp_path / "live.jsonl"
    monkeypatch.setattr(script, "LEDGER", live)
    monkeypatch.setattr(script, "_git", lambda *args: "claude/elsewhere")
    with pytest.raises(SystemExit, match="The live ledger is on branch factory/ledger"):
        script.main([*out, "run", str(spec_path)], source_factory=StubSource)
    with pytest.raises(SystemExit, match="The live ledger is on branch factory/ledger"):
        script.main([*out, "week"], source_factory=StubSource, proposer=lambda s, t: (ANSWER, ""))
    assert not live.exists()
    monkeypatch.setattr(script, "_git", lambda *args: "factory/ledger" if "--abbrev-ref" in args else "abc1234")
    assert script.main([*out, "run", str(spec_path)], source_factory=StubSource) == 0
    assert len(read_lines(live)) == 1


def test_notify_sends_the_latest_summary_or_a_failure(script, tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    for day, summary, passed in (("2026-09-27", "an older week", True), ("2026-10-04", "3 ideas judged, none passed.", False)):
        (reports / f"{day}.json").write_text(json.dumps({"day": day, "summary": summary, "passed": passed, "answer": {}}))
    sent: list[tuple] = []

    def sender(*args):
        sent.append(args)

    monkeypatch.delenv("FACTORY_NTFY_URL", raising=False)
    with pytest.raises(SystemExit, match="FACTORY_NTFY_URL is not set"):
        script.main(["--reports", str(reports), "notify"], sender=sender)
    monkeypatch.setenv("FACTORY_NTFY_URL", "https://ntfy.example/topic-x")
    monkeypatch.setenv("FACTORY_NTFY_TOKEN", "a-token")
    assert script.main(["--reports", str(reports), "notify"], sender=sender) == 0
    assert sent[-1] == ("https://ntfy.example/topic-x", "a-token", "Strategy factory, week of 2026-10-04",
                        "3 ideas judged, none passed.", None, 3, ["chart_with_upwards_trend"])
    (reports / "2026-10-11.json").write_text(json.dumps({"day": "2026-10-11", "summary": "1 of 3 ideas passed.",
                                                         "passed": True, "answer": {}}))
    assert script.main(["--reports", str(reports), "notify"], sender=sender) == 0
    assert (sent[-1][2], sent[-1][5], sent[-1][6]) == ("Strategy factory, week of 2026-10-11", 5, ["tada"])
    assert script.main(["--reports", str(reports), "notify", "--failure", "fetching bars failed"], sender=sender) == 0
    assert sent[-1][2:4] == ("Strategy factory: the weekly run failed", "fetching bars failed") and sent[-1][5] == 4


def test_publish_posts_ntfy_json_and_links_to_github(script, monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout):
        captured["request"] = request
        return Response()

    monkeypatch.setattr(script, "urlopen", fake_urlopen)
    script.publish("https://ntfy.sh/topic-x", "a-token", "Title", "Body", "https://github.com/x", 3, ["tag"])
    request = captured["request"]
    assert request.full_url == "https://ntfy.sh/" and request.get_header("Authorization") == "Bearer a-token"
    assert json.loads(request.data) == {"topic": "topic-x", "title": "Title", "message": "Body", "priority": 3,
                                        "tags": ["tag"], "click": "https://github.com/x"}
    monkeypatch.setattr(script, "_git", lambda *args: "git@github.com:someone/TradeJournal.git")
    assert script.github_url(script.RESEARCH / "reports" / "2026-10-04.md") == (
        "https://github.com/someone/TradeJournal/blob/factory/ledger/research/reports/2026-10-04.md")
    assert script.github_url(Path("/somewhere/else.md")) is None


def test_prepare_asks_for_each_missing_day_once_and_skips_market_holidays(script):
    fri, mon, tue, wed, fri2, mon2 = (date(2025, 1, 3), date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8),
                                      date(2025, 1, 10), date(2025, 1, 13))
    cached = {
        "SPY": [fri, mon, tue, wed, fri2],  # closed on Thursday 2025-01-09, a national day of mourning
        "AAA": [fri, mon, wed, fri2],  # missing Tuesday, and the holiday
        "NEW": [wed],  # listed on Wednesday
    }
    assert script.days_to_fetch(cached, mon2) == {tue: ["AAA"], fri2: ["NEW"], mon2: ["SPY", "AAA", "NEW"]}
    assert script.days_to_fetch({"SPY": [], "AAA": []}, date(2023, 6, 2)) == {
        date(2023, 6, 1): ["SPY", "AAA"], date(2023, 6, 2): ["SPY", "AAA"]}


def test_evidence_is_recomputed_when_the_engine_code_changes(script, tmp_path, monkeypatch):
    paths, args = weekly_paths(tmp_path)
    computed: list[str] = []
    real = script.discovery_trades

    def counting(spec, load):
        computed.append(spec.family)
        return real(spec, load)

    monkeypatch.setattr(script, "discovery_trades", counting)
    dry = [*args, "week", "--dry-run"]

    def unused(system: str, text: str):
        raise AssertionError("a dry run asks no one")

    assert script.main(dry, source_factory=StubSource, proposer=unused) == 0
    assert sorted(computed) == ["failed_breakout", "opening_range_breakout", "recovery_swing", "vwap_reclaim"]
    assert script.main(dry, source_factory=StubSource, proposer=unused) == 0
    assert len(computed) == 4  # cached
    fingerprint = script.engine_fingerprint()
    assert {path.name.rsplit("-", 1)[1] for path in (paths["out"] / "evidence").glob("*.json")} == {f"{fingerprint}.json"}
    monkeypatch.setattr(script, "engine_fingerprint", lambda: "changed000")
    assert script.main(dry, source_factory=StubSource, proposer=unused) == 0
    assert len(computed) == 8
    assert {path.name.rsplit("-", 1)[1] for path in (paths["out"] / "evidence").glob("*.json")} == {"changed000.json"}
