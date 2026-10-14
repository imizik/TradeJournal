"""Generation-only replay frequency denominators and gap-policy comparison."""

import copy
from datetime import datetime, timedelta

import pytest

from app.engine import scanner_replay_market as market
from scripts import scanner_replay_frequency as frequency
from tests.test_scanner_replay_market import bundle


def next_day_zero_bundle():
    source = copy.deepcopy(bundle())
    source["session_date"] = "2026-08-26"
    source["retrieved_at"] = (datetime.fromisoformat(source["retrieved_at"]) + timedelta(days=1)).isoformat()
    source["open_at"] += 86400
    source["close_at"] += 86400
    for values in source["symbols"].values():
        values["minutes"] = []
    return source


def test_frequency_includes_zero_setup_sessions_and_sums_all_symbols_types():
    sparse = bundle()
    sparse["symbols"]["SPY"]["minutes"].pop(2)  # v1 stops; live buckets still select one ORB
    result = frequency.analyze([next_day_zero_bundle(), sparse])
    assert [row["session_date"] for row in result["sessions"]] == ["2026-08-25", "2026-08-26"]
    assert result["parity"]["sessions"] == result["strict"]["sessions"] == 2
    assert result["parity"]["total"] == 1 and result["parity"]["mean"] == 0.5
    assert result["strict"]["total"] == 0 and result["strict"]["mean"] == 0
    assert result["sessions"][0]["setups"] - result["sessions"][0]["strict_v1_setups"] == 1
    assert result["sessions"][1]["setups"] == result["sessions"][1]["strict_v1_setups"] == 0
    assert sum(row["total"] for row in result["by_symbol"].values()) == result["parity"]["total"]
    assert sum(row["total"] for row in result["by_setup"].values()) == result["parity"]["total"]
    assert all(row["sessions"] == 2 for row in (*result["by_symbol"].values(), *result["by_setup"].values()))
    assert result["by_symbol"]["SPY"]["total"] == 1
    assert result["by_setup"]["orb:long"]["total"] == 1
    assert result["by_setup"]["fade:long"]["total"] == result["by_setup"]["fade:short"]["total"] == 0
    assert result["policy"]["version"] == market.VERSION and result["no_jo"] is True


def test_frequency_zero_observed_live_denominator_is_explicit_and_safe():
    result = frequency.analyze([next_day_zero_bundle()])
    assert result["parity"] == {"sessions": 1, "total": 0, "mean": 0, "median": 0, "min": 0, "max": 0}
    report = frequency.render(result, {"enablement_date_ny": "2026-10-12", "rows": []})
    assert "2026-08-26" in report and "| 2026-10-12 | 0 |" in report
    assert "Replay mean versus observed live mean" not in report
    assert "No Jo decisions or profit results were used" in report


def test_frequency_rejects_holdout_and_duplicate_sessions():
    holdout = bundle()
    holdout["session_date"] = "2026-09-14"
    with pytest.raises(ValueError, match="Holdout"):
        frequency.analyze([holdout])
    source = bundle()
    with pytest.raises(ValueError, match="distinct"):
        frequency.analyze([source, copy.deepcopy(source)])
