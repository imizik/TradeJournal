"""Isolated operator guards, sealed reports and S2 snapshot matching."""

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import uuid

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.engine import scanner_replay, scanner_replay_market
from app.engine import scanner_replay_report as report
from app.models import Account, Fill, PracticeRun
from scripts import scanner_replay_operator as operator
from tests.test_scanner_replay_market import bundle


def private_file(path: Path, value) -> Path:
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return path


@pytest.fixture
def trial(tmp_path, monkeypatch):
    root = tmp_path / "trial"
    (root / "data").mkdir(parents=True)
    (root / ".sample-installation").write_text("sample")
    target = root / "data/trial.db"
    url = f"sqlite:///{target}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        account = Account(name="Seed", type="roth_ira", last4="0001")
        db.add(account)
        db.flush()
        db.add(Fill(account_id=account.id, ticker="SPY", instrument_type="stock", side="buy", contracts=1,
                    price=100, executed_at=datetime(2026, 8, 25, 9, 30), raw_email_id="seed:scanner-test"))
        db.commit()
    values = {"DATABASE_URL": url, "MIGRATION_DATABASE_URL": url, "TJ_DOT_TRIAL_ENABLED": "true",
              "TJ_ACCESS_ENABLED": "true", "TJ_ACCESS_SAMPLE_DATA": "true", "JOB_EXECUTION_MODE": "external"}
    for name in ("GMAIL_WATCH_AUTOSTART", "GMAIL_LISTENER_ENABLED", "WEBULL_LISTENER_AUTOSTART",
                 "LEVEL_ALERTS_AUTOSTART", "PRACTICE_AGENT_ENABLED", "PRACTICE_SCHEDULE_ENABLED"):
        values[name] = "false"
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    for name in ("TRADIER_API_KEY", "ALPACA_API_KEY", "ALPACA_API_SECRET", "POLYGON_API_KEY", "OPENAI_API_KEY",
                 "ANTHROPIC_API_KEY", "WEBULL_USERNAME", "WEBULL_PASSWORD", "NTFY_URL"):
        monkeypatch.delenv(name, raising=False)
    yield root, engine
    engine.dispose()


def resolved_bundle():
    source = bundle()
    source["symbols"]["SPY"]["minutes"][22]["high"] = 101
    source["symbols"]["SPY"]["minutes"][23]["high"] = 101
    return source


def prepare(trial, tmp_path, capsys, *, exam_count=0, identifier="scanner-operator"):
    root, _engine = trial
    source = private_file(tmp_path / f"{identifier}.json", resolved_bundle())
    operator.main(["--trial-root", str(root), "prepare", "--bundle", str(source), "--identifier", identifier,
                   "--seed", "17", "--exam-count", str(exam_count)])
    return json.loads(capsys.readouterr().out)["run_ids"][0]


def test_wrong_database_refused_before_input_or_app_work(tmp_path, monkeypatch):
    root = tmp_path / "not-marked"
    root.mkdir()
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/forbidden")
    monkeypatch.setattr(operator, "private_json", lambda *_: pytest.fail("private input read before trial validation"))
    with pytest.raises(RuntimeError, match="non-isolated"):
        operator.main(["--trial-root", str(root), "prepare", "--bundle", str(tmp_path / "missing.json"),
                       "--identifier", "scanner-isolated", "--seed", "2", "--exam-count", "0"])
    output = tmp_path / "never-written.md"
    with pytest.raises(RuntimeError, match="non-isolated"):
        operator.main(["--trial-root", str(root), "report", "--run-id", str(uuid.uuid4()),
                       "--output", str(output)])
    assert not output.exists()


def test_private_input_mode_symlink_bound_and_exclusive_output(tmp_path):
    source = private_file(tmp_path / "capture.json", {"a": 1})
    assert operator.private_json(source, 100) == {"a": 1}
    source.chmod(0o644)
    with pytest.raises(ValueError, match="0600"):
        operator.private_json(source, 100)
    source.chmod(0o600)
    with pytest.raises(ValueError, match="size bound"):
        operator.private_json(source, 2)
    link = tmp_path / "linked.json"
    link.symlink_to(source)
    with pytest.raises(ValueError, match="private regular"):
        operator.private_json(link, 100)
    output = tmp_path / "report.md"
    operator.write_private_report(output, "first")
    assert output.read_text() == "first" and (output.stat().st_mode & 0o777) == 0o600
    with pytest.raises(FileExistsError):
        operator.write_private_report(output, "second")
    assert output.read_text() == "first"


def test_prepare_records_split_and_report_after_commit(trial, tmp_path, capsys):
    root, engine = trial
    run_id = prepare(trial, tmp_path, capsys)
    with Session(engine) as db:
        run = db.get(PracticeRun, uuid.UUID(run_id))
        manifest = scanner_replay.metadata(run)["manifest"]
        assert manifest["seed"] == 17 and manifest["phases"][run.day.isoformat()] == "practice"
        assert len(scanner_replay.entries(run)) == 1
        with pytest.raises(Exception, match="sealed"):
            scanner_replay.report(db, run)
        scanner_replay.view(db, run, manifest["actor"], scanner_replay_market.rules.UNIVERSE)
        scanner_replay.view(db, run, manifest["actor"], scanner_replay_market.rules.UNIVERSE, resume=True)
        scanner_replay.choose(db, run, scanner_replay.entries(run)[0], manifest["actor"],
                              scanner_replay_market.rules.UNIVERSE,
                              {"decision": "take", "rationale": "<script>|`line\nnext"})
        saved = scanner_replay.report(db, run)
        assert saved["scorecard"]["rules_take_all"]["resolved"] == 1
        assert saved["scorecard"]["jo_baseline_entry"]["total_r"] == 2.2
        assert saved["scorecard"]["jo_delayed_entry"]["total_r"] == 2.2
        assert saved["scorecard"]["jo_baseline_entry"]["pnl_100_cost_sensitivity"] == pytest.approx(
            saved["scorecard"]["jo_baseline_entry"]["pnl_100"] - 4)
        assert scanner_replay.report(db, run)["scorecard"] == saved["scorecard"]
    output = tmp_path / "private-report.md"
    operator.main(["--trial-root", str(root), "report", "--run-id", run_id, "--output", str(output)])
    capsys.readouterr()
    markdown = output.read_text()
    assert "## Cumulative practice and exam" in markdown and "## By setup" in markdown
    assert "2.20" in markdown and "&lt;script&gt;\\|&#96;line / next" in markdown
    assert "No optional Isaac snapshot was supplied" in markdown
    assert "all unknown" in markdown and "30 decisions" in markdown
    assert "model-memory-unverified" in markdown and "Alpaca SIP" in markdown
    assert "source_fill_key" not in markdown
    assert "TAKE 1; SKIP 0; INSUFFICIENT_DATA 0" in markdown
    assert "&#x27;take&#x27;" not in markdown
    assert "Wall seconds" in markdown and "Resumed setup" in markdown
    assert "| yes |" in markdown
    assert "P&L / 100 shares at $0.02/share/side" in markdown
    assert "entry-minute stop not checked (optimistic)" in markdown.lower()
    assert "Daily ATR coverage" in markdown and "Missing-minute impact" in markdown
    assert "Lost setup count is unknowable" in markdown


def test_exam_abandon_does_not_publish_report(trial, tmp_path, capsys):
    root, engine = trial
    run_id = prepare(trial, tmp_path, capsys, exam_count=1, identifier="scanner-exam")
    output = tmp_path / "sealed.md"
    with pytest.raises(Exception, match="sealed"):
        operator.main(["--trial-root", str(root), "report", "--run-id", run_id, "--output", str(output)])
    assert not output.exists()
    operator.main(["--trial-root", str(root), "abandon", "--run-id", run_id])
    capsys.readouterr()
    with Session(engine) as db:
        assert db.get(PracticeRun, uuid.UUID(run_id)).status == "abandoned"
    with pytest.raises(Exception, match="sealed"):
        operator.main(["--trial-root", str(root), "report", "--run-id", run_id, "--output", str(output)])
    assert not output.exists()


def test_s2_latest_candidate_exact_15m_and_snapshot_filters():
    at = datetime(2026, 8, 25, 14, 0, tzinfo=UTC)
    first_id, second_id = uuid.uuid4(), uuid.uuid4()
    setups = [{"candidate": {"candidate_id": str(identity), "symbol": "SPY", "direction": "long",
                              "detected_at": moment.isoformat()}}
              for identity, moment in ((first_id, at), (second_id, at + timedelta(minutes=5)))]
    def row(moment, *, active=True, broker="robinhood", option_type="call"):
        return {"id": str(uuid.uuid4()), "ticker": "SPY", "instrument_type": "option", "option_type": option_type,
                "opened_at": moment.isoformat(), "active_account": active, "broker": broker,
                "status": "closed", "contracts": 1, "realized_pnl": 25}
    trades = [row(at + timedelta(minutes=15)), row(at + timedelta(minutes=20)),
              row(at + timedelta(minutes=20, seconds=1)), row(at + timedelta(minutes=10), active=False),
              row(at + timedelta(minutes=10), broker="webull"), row(at + timedelta(minutes=10), option_type="put")]
    linked = report.link_snapshot(setups, trades)
    assert len(linked[str(first_id)]) == 0
    assert len(linked[str(second_id)]) == 2
    assert all(trade.realized_pnl == 25 for trade in linked[str(second_id)])


def test_report_uses_snapshot_only_and_keeps_option_pnl_separate(trial, tmp_path, capsys):
    root, engine = trial
    run_id = prepare(trial, tmp_path, capsys, identifier="scanner-isaac")
    with Session(engine) as db:
        run = db.get(PracticeRun, uuid.UUID(run_id))
        scanner_replay.view(db, run, "scanner-isaac", scanner_replay_market.rules.UNIVERSE)
        scanner_replay.choose(db, run, scanner_replay.entries(run)[0], "scanner-isaac",
            scanner_replay_market.rules.UNIVERSE, {"decision": "skip", "rationale": "No historical spread"})
        candidate = scanner_replay.report(db, run)["setups"][0]["candidate"]
    trade = {"id": str(uuid.uuid4()), "ticker": "SPY", "instrument_type": "option", "option_type": "call",
             "opened_at": (report._ny(candidate["detected_at"]) + timedelta(minutes=4)).replace(tzinfo=None).isoformat(),
             "active_account": True, "broker": "robinhood", "status": "closed", "contracts": 2,
             "realized_pnl": 125}
    snapshot = private_file(tmp_path / "isaac.json", [trade])
    output = tmp_path / "isaac-report.md"
    operator.main(["--trial-root", str(root), "report", "--run-id", run_id,
                   "--output", str(output), "--isaac-trades", str(snapshot)])
    markdown = output.read_text()
    assert "1 matched option trade(s)" in markdown
    assert "actual option P&L: 125.00" in markdown
    assert "Jo at baseline entry | 0" in markdown
    assert "125.00" not in markdown.split("## Isaac's actual option trades")[0]
