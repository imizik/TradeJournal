"""Remote aggregation privacy, cutoff and packet binding; no real trade inputs."""
import copy
from datetime import datetime, timezone
import json

import pytest

from app.engine import scanner_replay_market as market
from scripts import scanner_replay_history as history
from tests.test_scanner_replay_market import bundle


def aggregate_fixture():
    packet = market.generate_session(bundle())["setups"][0]["packet"]
    features = packet["history"]["cohorts"][0]["definition"]
    request = {"format": "scanner-replay-history-requests-v1", "requests": [{
        "candidate_id": packet["candidate"]["candidate_id"], "session_date": "2026-08-25",
        "history_cutoff": packet["history_cutoff"], "features": features}]}
    row = {**features, "closed_at": "2026-08-24T16:01:00", "opened_at": "2026-08-24T14:00:00",
           "realized_pnl": 10, "pnl_pct": 0.1, "mfe_pct": 0.2, "mae_pct": -0.1,
           "source_fill_key": "a" * 64}
    source = {"state": "fresh", "features_sha256": "f" * 64,
              "generated_at": datetime(2026, 10, 13, tzinfo=timezone.utc).isoformat(),
              "rows": [row, {**row, "closed_at": "2026-08-25T04:00:00+00:00", "source_fill_key": "b" * 64},
                       {**row, "closed_at": "2026-08-25T03:59:00+00:00", "source_fill_key": "c" * 64}]}
    return request, source


def test_cutoff_aggregates_exclude_midnight_and_return_no_trade_rows_or_keys():
    request, source = aggregate_fixture()
    cards = history.aggregate(request, source)
    card = next(iter(cards["cards"].values()))["history"]
    assert card["available"] and card["source_state"] == "fresh"
    assert [c["trades"] for c in card["cohorts"]] == [2, 2]
    serialized = json.dumps(cards)
    assert "closed_at" not in serialized and "source_fill_key" not in serialized and "opened_at" not in serialized
    result = market.generate_session(bundle(), history_cards=cards)
    packet = result["setups"][0]["packet"]
    assert packet["history"] == card
    assert "informed-by-history" in packet["labels"]


def test_missing_and_zero_matching_history_are_distinct_labels():
    request, source = aggregate_fixture()
    missing = market.generate_session(bundle())["setups"][0]["packet"]
    assert not missing["history"]["available"]
    assert "informed-by-history" not in missing["labels"]
    assert "prior-trade-history-unavailable" in missing["labels"]
    source["rows"] = []
    packet = market.generate_session(bundle(), history_cards=history.aggregate(request, source))["setups"][0]["packet"]
    assert packet["history"]["available"] and packet["history"]["cohorts"][0]["trades"] == 0
    assert "history-available-no-matching-trades" in packet["labels"]
    assert "informed-by-history" not in packet["labels"]


@pytest.mark.parametrize("mutation", ["cutoff", "symbol", "raw_keys", "missing_card", "nonfinite", "nested_raw_keys"])
def test_precomputed_card_cannot_cross_cutoff_features_or_leak_keys(mutation):
    request, source = aggregate_fixture()
    cards = history.aggregate(request, source)
    card = next(iter(cards["cards"].values()))
    if mutation == "cutoff":
        card["history_cutoff"] = "2026-08-26T00:00:00-04:00"
    elif mutation == "symbol":
        card["features"]["underlying"] = "MU"
    elif mutation == "raw_keys":
        card["history"]["source_fill_keys"] = ["private"]
    elif mutation == "missing_card":
        cards["cards"] = {}
    elif mutation == "nested_raw_keys":
        card["history"]["cohorts"][0]["coverage"] = {"pnl": 0, "path": 0, "source_fill_keys": ["private"]}
    else:
        card["history"]["cohorts"][0]["total_pnl"] = float("nan")
    with pytest.raises(ValueError):
        market.generate_session(bundle(), history_cards=cards)


def test_aggregate_requests_refuse_wrong_cutoff_and_missing_source():
    request, source = aggregate_fixture()
    wrong = copy.deepcopy(request)
    wrong["requests"][0]["history_cutoff"] = "2026-08-25T00:00:00+00:00"
    with pytest.raises(ValueError, match="cutoff"):
        history.aggregate(wrong, source)
    with pytest.raises(ValueError, match="unavailable"):
        history.aggregate(request, {**source, "state": "missing", "rows": None})
