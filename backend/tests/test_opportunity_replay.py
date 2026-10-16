"""Frozen opportunity import, explicit grants and real sequential MCP routes."""

import copy
from datetime import datetime, timedelta
import json
from types import SimpleNamespace
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.engine import (
    opportunity_replay as op,
    scanner_replay as replay,
    access,
    cloud_practice_access,
)
from app.main import app
from app.models import DecisionContext, PracticeRun
from tests.test_scanner_replay import read, path
from tests.test_browser_access import boundary as boundary  # noqa: F401
from tests.test_cloud_mcp_d1 import _write_config
from tests.test_cloud_mcp_d0 import (
    _jwks,
    _token,
    ISSUER,
    JWKS_URL,
    PROFILE_ID,
    signing_key as signing_key,
)  # noqa: F401


def bundle():
    cards = []
    for i in range(2):
        at = datetime.fromisoformat("2024-02-05T09:45:00-05:00") + timedelta(hours=i)
        identity = {
            "spec_id": "op-0000000000",
            "ticker": "NVDA",
            "signal_time": (at - timedelta(minutes=5)).isoformat(),
            "side": 1,
        }
        cards.append(
            {
                "id": op.digest(identity)[:20],
                "schema": "opportunity-pilot-v1",
                "candidate": identity,
                "family": "opening_range_breakout",
                "setup": "opening_range_breakout",
                "timeframe_minutes": 5,
                "simulated_as_of": at.isoformat(),
                "entry_reference": 100,
                "stop": 99,
                "target_reference": 102,
                "target_r": 2,
                "max_minutes": 60,
                "features": {"trend": 1, "day_move": 1},
                "estimated_round_trip_cost_r": 0.02,
                "option_eligibility": {
                    "available": False,
                    "reason": "No historical option quotes, spreads or contract evidence",
                },
                "candles": [
                    {
                        "start": identity["signal_time"],
                        "end": at.isoformat(),
                        "open": 100,
                        "high": 101,
                        "low": 99.5,
                        "close": 100,
                        "volume": 100,
                    }
                ],
                "source": "cached Alpaca SIP; retrospective data, may contain corrections",
                "labels": [
                    "offline-research",
                    "underlying-only",
                    "independence-unverified",
                    "options-liquidity-unverified",
                    "split-adjusted-to-decision-basis",
                ],
            }
        )
    private = {
        "nonce": "a" * 64,
        "outcomes": {
            c["id"]: {"resolved": True, "r": r} for c, r in zip(cards, [-1, 2])
        },
    }
    source = {
        "schema": "opportunity-pilot-v1",
        "frozen_at": "2024-02-10T00:00:00Z",
        "sessions": ["2024-02-05"],
        "seed": 10415,
        "spec_ids": ["op-0000000000"],
        "quality_policy": {
            "min_target_r": 1.25,
            "max_estimated_cost_r": 0.25,
            "max_cards_per_day": 18,
            "max_ticker_per_day": 3,
        },
        "cards": cards,
        "scoring_policy": op.SOURCE_POLICY,
        "sealed_outcomes_sha256": op.digest(private),
    }
    return {
        "format": "opportunity-replay-import-v1",
        "manifest": source,
        "outcomes": private,
    }


@pytest.fixture
def opportunity_link(boundary, signing_key, tmp_path):
    b = boundary
    for flag in (
        "TJ_ACCESS_SAMPLE_DATA",
        "TJ_DOT_TRIAL_ENABLED",
        "TJ_MARKET_DECISION_WRITES",
        "TJ_HISTORICAL_REPLAY_ENABLED",
        "TJ_CLOUD_MCP_ENABLED",
        "TJ_CLOUD_MCP_HISTORICAL_ENABLED",
        "TJ_CLOUD_MCP_DECISION_WRITES",
    ):
        b.patch.setenv(flag, "true")
    for flag in (
        "market_decisions_isolated",
        "historical_replay_isolated",
        "cloud_mcp_sample_only",
    ):
        b.patch.setattr(app.state, flag, True, raising=False)
    with Session(b.engine) as db:
        runs = op.prepare(db, bundle(), "jo-opportunity-fixture")
        ids = [str(r.id) for r in runs]
    grants = {
        "symbols": ["NVDA"],
        "run_ids": ids,
        "journal_read": False,
        "market_decision_write": True,
        "historical_replay": True,
        "scanner_replay": True,
        "opportunity_feed": True,
    }
    made = b.owner.post(
        "/access/assistants",
        json={"identifier": "jo-opportunity-fixture", "grants": grants},
    )
    assert made.status_code == 201, made.text
    config, keys = tmp_path / "opportunity.json", tmp_path / "keys.json"
    _write_config(
        config,
        sample_only=True,
        exercise_kind="scanner_replay",
        decision_writes=True,
        jwks_file=str(keys),
        backend_socket=str(tmp_path / "reads.sock"),
        profiles=[
            {
                "subject": "owner-subject",
                "id": PROFILE_ID,
                "enabled": True,
                "principal_id": "jo-opportunity-fixture",
                "principal_version": 1,
            }
        ],
    )
    now = int(time.time())
    keys.write_text(
        json.dumps(
            {
                "issuer_url": ISSUER,
                "jwks_url": JWKS_URL,
                "fetched_at": now,
                "expires_at": now + 3600,
                "keys": _jwks(signing_key.public_key())["keys"],
            }
        )
    )
    b.patch.setenv("TJ_CLOUD_MCP_CONFIG", str(config))
    cloud_practice_access.verifier.cache_clear()
    token = _token(signing_key, scope="d0:profile practice:read practice:write")
    with TestClient(app) as client:
        client.headers["authorization"] = "Bearer " + token
        yield SimpleNamespace(
            b=b, backend=client, ids=ids, grants=grants, config=config, token=token
        )
    cloud_practice_access.verifier.cache_clear()


def test_opportunity_sequential_receipts_hidden_future_and_complete_report(
    opportunity_link,
):
    h = opportunity_link
    first = read(h)
    assert first["read_only"] is False and first["report"] is None
    assert "10:45:00" not in json.dumps(first) and "nonce" not in json.dumps(first)
    with Session(h.b.engine) as db:
        run = db.get(PracticeRun, uuid.UUID(h.ids[0]))
        entries = replay.entries(run)
    assert (
        h.backend.post(
            path(entries[1]["opportunity_id"]),
            json={"decision": "take", "rationale": "future"},
        ).status_code
        == 404
    )
    args = {"decision": "skip", "rationale": "Cutoff geometry only"}
    saved = h.backend.post(path(first["next_setup"]["opportunity_id"]), json=args)
    assert saved.status_code == 201, saved.text
    assert (
        h.backend.post(path(first["next_setup"]["opportunity_id"]), json=args).json()[
            "choice"
        ]
        == saved.json()["choice"]
    )
    second = read(h)
    assert second["report"] is None
    assert second["next_setup"]["opportunity"]["simulated_as_of"].startswith(
        "2024-02-05T10:45"
    )
    assert read(h)["next_setup"] == second["next_setup"]
    result = h.backend.post(
        path(second["next_setup"]["opportunity_id"]),
        json={"decision": "take", "rationale": "Frozen context fits"},
    )
    assert result.status_code == 201, result.text
    final = read(h)
    assert final["report"]["scorecard"]["take_all"]["total_r"] == 1
    assert final["report"]["scorecard"]["jo_take"]["total_r"] == 2
    assert final["report"]["scorecard"]["fixed_context_filter"]["total_r"] == 1
    assert final["report"]["scorecard"]["delayed_entry"].startswith("not modeled")


def test_legacy_grant_cannot_get_opportunity_symbols_and_subtype_cannot_repoint(
    opportunity_link,
):
    h = opportunity_link
    for grants in (
        {**h.grants, "opportunity_feed": False},
        {**h.grants, "symbols": ["NVDA", "MSFT"]},
    ):
        with Session(h.b.engine) as db:
            with pytest.raises(Exception):
                access.grant_valid(grants)
                access.grant_targets_valid(db, "jo-opportunity-fixture", grants)
    with Session(h.b.engine) as db:
        with pytest.raises(ValueError, match="Actor"):
            altered = bundle()
            altered["manifest"]["seed"] = 42
            op.prepare(db, altered, "jo-opportunity-fixture")


def test_import_retry_no_duplicate_contexts_and_seal_failure_no_partial_rows(
    opportunity_link,
):
    h = opportunity_link
    with Session(h.b.engine) as db:
        before = len(db.exec(select(DecisionContext)).all())
        assert [
            str(r.id) for r in op.prepare(db, bundle(), "jo-opportunity-fixture")
        ] == h.ids
        assert len(db.exec(select(DecisionContext)).all()) == before
        bad = bundle()
        bad["outcomes"]["outcomes"][next(iter(bad["outcomes"]["outcomes"]))]["r"] = 999
        with pytest.raises(ValueError, match="seal"):
            op.prepare(db, bad, "jo-corrupt-fixture")
        assert len(db.exec(select(DecisionContext)).all()) == before


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b["manifest"]["cards"][0].update(extra_future_outcome=99),
        lambda b: b["manifest"]["cards"][0]["candles"][0].update(
            end="2024-02-05T10:45:00-05:00"
        ),
        lambda b: b["manifest"]["cards"][0].update(
            option_eligibility={"available": True}
        ),
        lambda b: b["manifest"].update(sessions=["2026-10-01"]),
        lambda b: b["manifest"]["cards"].reverse(),
        lambda b: b["manifest"]["scoring_policy"].update(exam="unsafe"),
    ],
)
def test_invalid_unbounded_or_lookahead_handoffs_refused(mutate):
    value = copy.deepcopy(bundle())
    mutate(value)
    with pytest.raises((ValueError, KeyError)):
        op.validate(value)


def test_actual_mcp_tools_use_same_next_card_and_immutable_receipt(opportunity_link):
    import httpx
    from cloud_mcp_d1 import create_server
    from tests.test_cloud_mcp_d0 import _request

    h = opportunity_link
    server = create_server(h.config, backend_transport=httpx.ASGITransport(app=app))
    with TestClient(server.streamable_http_app()) as client:
        response = _request(
            client,
            "tools/call",
            {"name": "get_practice_run", "arguments": {"run_id": h.ids[0]}},
            h.token,
        )["result"]
        assert not response.get("isError"), response
        card = response["structuredContent"]["run"]["next_setup"]
        args = {
            "opportunity_id": card["opportunity_id"],
            "decision": "skip",
            "rationale": "Native protocol fixture only",
        }
        saved = _request(
            client,
            "tools/call",
            {"name": "record_practice_choice", "arguments": args},
            h.token,
        )["result"]
        assert not saved.get("isError"), saved
        retry = _request(
            client,
            "tools/call",
            {"name": "record_practice_choice", "arguments": args},
            h.token,
        )["result"]
        assert (
            retry["structuredContent"]["choice"] == saved["structuredContent"]["choice"]
        )
    # New adapter/verifier instance, same frozen batch and receipt after restart.
    server = create_server(h.config, backend_transport=httpx.ASGITransport(app=app))
    with TestClient(server.streamable_http_app()) as client:
        response = _request(
            client,
            "tools/call",
            {
                "name": "get_practice_run",
                "arguments": {"run_id": h.ids[0], "resume": True},
            },
            h.token,
        )["result"]
        assert not response.get("isError"), response
        run = response["structuredContent"]["run"]
        assert (
            run["committed"] == 1
            and run["next_setup"]["opportunity_id"] != card["opportunity_id"]
        )
        assert run["report"] is None


def test_opportunity_abandonment_never_reveals_partial_batch(opportunity_link):
    h = opportunity_link
    with Session(h.b.engine) as db:
        run = db.get(PracticeRun, uuid.UUID(h.ids[0]))
        replay.abandon(db, run)
        assert not replay.reveal_allowed(db, run)
        with pytest.raises(Exception, match="sealed"):
            replay.report(db, run)
    assert read(h)["report"] is None


def test_export_private_handoff_is_exclusive_and_cannot_follow_symlinks(tmp_path):
    from scripts import opportunity_replay_export as exporter

    pilot = tmp_path / "pilot"
    private = pilot / "operator-private"
    private.mkdir(parents=True)
    value = bundle()
    for name, key in [("manifest", "manifest"), ("outcomes", "outcomes")]:
        p = private / f"{name}.json"
        p.write_text(json.dumps(value[key]))
        p.chmod(0o600)
    target = tmp_path / "handoff.json"
    assert exporter.export(pilot, target)["cards"] == 2
    assert target.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        exporter.export(pilot, target)
    (private / "manifest.json").chmod(0o644)
    with pytest.raises(ValueError):
        exporter.export(pilot, tmp_path / "unsafe.json")
