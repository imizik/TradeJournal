"""
Golden snapshot over the seed fixture: PnL, FIFO assignment, and the audit.

`test_seed_dev_data.py` already asserts six trades' ticker, account, status and
realized PnL. That is a floor, not a net. A regression that preserves those six
numbers while corrupting cost basis, premium totals, which fill landed on which
trade, or the reconciliation output passes it unchanged.

This snapshots everything the reconstructor and the auditor produce from the
fixture, so moving any number requires a deliberate edit to a checked-in file.
It covers `auditor.py`, which had no test at all, and the FIFO fill-to-trade
assignment, which is the thing most likely to shift silently.

Regenerate on purpose, never to make a red test green without reading the diff:

    UPDATE_SNAPSHOTS=1 pytest tests/test_seed_snapshot.py

Why this can be a stable snapshot at all: the fixture's fill ids are
deterministic (`uuid.UUID(int=0x5EEDF111_0000 + index)`), so the reconstructor's
same-timestamp tie-break on `str(fill.id)` -- documented as arbitrary in
domain-rules.md -- lands the same way every run. Trade ids are *not*
deterministic (`default_factory=uuid.uuid4`) and are excluded. The fixture dates
are relative to `date.today()`, so absolute datetimes are recorded as offsets in
days rather than dropped, which keeps the date-derived fields covered without
the snapshot going stale overnight.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlmodel import Session, select

BACKEND_DIR = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = Path(__file__).parent / "snapshots" / "seed_reconstruction.json"
UPDATING = os.environ.get("UPDATE_SNAPSHOTS", "").strip().lower() in {"1", "true", "yes"}

# The audit embeds filesystem paths, and one of them is absolute: the
# "Daily bar cache not found" branch of _audit_indicators returns str(path)
# while its success branch and _audit_fill both return a path relative to the
# cache root. A snapshot recording the absolute form passes only on the machine
# that wrote it -- this failed CI on the first run with /home/runner/... against
# /home/user/... . Rewritten to a placeholder so the useful part of the path,
# stocks/1Day/iex/NVDA.json, stays under test.
REPO_ROOT = str(BACKEND_DIR.parent)

# A fixed path that does not exist, rather than a temporary directory. The
# auditor prints the cache path it failed to find, so a real temp directory
# would put a fresh random string into the snapshot on every run -- trading one
# kind of non-determinism for another. This name is constant on every machine.
EMPTY_CACHE_DIR = Path("/nonexistent/snapshot-empty-alpaca-cache")


def _load_seed_module():
    path = BACKEND_DIR / "scripts" / "seed_dev_data.py"
    spec = importlib.util.spec_from_file_location("seed_snapshot_seed_data", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["seed_snapshot_seed_data"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    seed_module = _load_seed_module()
    database_path = tmp_path_factory.mktemp("seed_snapshot") / "seed.db"
    url = f"sqlite:///{database_path}"
    seed_module.seed(url)
    return url


def _days_from_today(value) -> int | None:
    """
    Dates as an offset, not an absolute.

    The fixture builds itself relative to `date.today()`, so a snapshot holding
    absolute dates would pass on the day it was written and fail the next
    morning. An offset keeps `opened_at`, `closed_at` and `expiration` under
    test without that.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, str):
        value = datetime.fromisoformat(value).date()
    return (value - date.today()).days


def _jsonable(value):
    """
    Everything as JSON-native types, recursively.

    Applied before comparison, not just before writing: the snapshot is read
    back as parsed JSON, so a Decimal left in the captured side would never
    equal the string in the file and the test would fail on every run for a
    reason that has nothing to do with the numbers.
    """
    from decimal import Decimal

    if isinstance(value, Decimal):
        return f"{value:.6f}"
    if isinstance(value, float):
        return f"{value:.6f}"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, str):
        return value.replace(REPO_ROOT, "<repo>")
    return value


def _decimal(value) -> str | None:
    """Compare decimals as text. 1300.0 and 1300.00 are the same number and
    should not be the same snapshot, because a float creeping into a money
    column is exactly the regression worth catching."""
    return None if value is None else f"{value:.6f}"


def _capture(database_url: str) -> dict:
    """
    Capture the reconstruction with market data stubbed out.

    `compute_audit` -> `_audit_path` calls `fetch_minute_bars_for_date` without
    its `cache_only` flag, so auditing a closed trade makes a live Alpaca
    request. That is why this function had no test: it cannot run offline, and
    in CI it would be slow at best and flaky at worst.

    Stubbing it to return no bars pins the branch that matters here -- the
    "Not enough data to compute path" path, which is what a cold cache produces
    anyway -- and keeps the snapshot a property of the fixture rather than of
    whatever the market did while the suite ran.

    CACHE_DIR is redirected to an empty directory for the same reason, and it
    is the less obvious half. `_audit_fill` and `_audit_indicators` read the
    cache straight off disk rather than through the stubbed function, so on a
    machine that has run the real app against AAPL, NVDA or TSLA -- any normal
    developer clone -- those files would populate bars, indicator fields and
    formulas that this cold-cache snapshot expects to be absent. The suite
    would then pass or fail on untracked user data.

    This was missed on the first pass because the container that wrote the
    snapshot had an empty cache, so the defect was invisible exactly where it
    was created. Verified by planting sixty days of NVDA bars: without the
    redirect the snapshot flips to "No daily bars up to fill date"; with it,
    the planted file is ignored.
    """
    from unittest.mock import patch

    from sqlmodel import create_engine

    from app.models import Account, Fill, Trade, TradeFill, TradePathMetrics

    engine = create_engine(database_url)
    with (
        patch("app.engine.auditor.fetch_minute_bars_for_date", return_value={}),
        patch("app.engine.auditor.CACHE_DIR", EMPTY_CACHE_DIR),
    ):
        return _capture_with(engine)


def _capture_with(engine) -> dict:
    from sqlmodel import select as _select  # noqa: F401  -- keep the import local

    from app.engine.auditor import compute_audit
    from app.models import Account, Fill, Trade, TradeFill, TradePathMetrics

    with Session(engine) as session:
        accounts = {a.id: a.last4 for a in session.exec(select(Account)).all()}
        fills = {f.id: f for f in session.exec(select(Fill)).all()}
        paths = {p.trade_id: p for p in session.exec(select(TradePathMetrics)).all()}

        captured = []
        for trade in session.exec(select(Trade)).all():
            links = session.exec(
                select(TradeFill).where(TradeFill.trade_id == trade.id)
            ).all()
            trade_fills = [fills[link.fill_id] for link in links if link.fill_id in fills]
            # raw_email_id, not the uuid: `seed:007` says which seeded fill this
            # is, and survives a change to how ids are minted.
            assigned = sorted(f.raw_email_id for f in trade_fills)

            audit = compute_audit(trade, trade_fills, {}, paths.get(trade.id))
            captured.append({
                "ticker": trade.ticker,
                "account": accounts.get(trade.account_id),
                "instrument_type": trade.instrument_type,
                "option_type": trade.option_type,
                "strike": _decimal(trade.strike),
                "status": trade.status,
                "contracts": _decimal(trade.contracts),
                "avg_entry_premium": _decimal(trade.avg_entry_premium),
                "avg_exit_premium": _decimal(trade.avg_exit_premium),
                "total_premium_paid": _decimal(trade.total_premium_paid),
                "realized_pnl": _decimal(trade.realized_pnl),
                "pnl_pct": _decimal(trade.pnl_pct),
                "hold_duration_mins": trade.hold_duration_mins,
                "entry_time_bucket": trade.entry_time_bucket,
                "expired_worthless": trade.expired_worthless,
                "opened_days_from_today": _days_from_today(trade.opened_at),
                "closed_days_from_today": _days_from_today(trade.closed_at),
                "expiration_days_from_today": _days_from_today(trade.expiration),
                "fills": assigned,
                "audit": _normalize_audit(audit),
            })

    # Trade ids are random per rebuild, so sort by something stable.
    captured.sort(key=lambda t: (t["ticker"], t["account"] or "", t["status"],
                                 t["fills"][0] if t["fills"] else ""))
    return {"trades": captured, "trade_count": len(captured)}


def _normalize_audit(audit: dict) -> dict:
    """
    The audit minus what cannot be stable: the random trade id, and absolute
    dates. Everything else is kept, including the nulls -- enrichment fields
    are nullable by design and `CLAUDE.md` lists them as needing extra care, so
    a null quietly becoming a zero is a regression this should catch.
    """
    normalized = {
        key: value for key, value in audit.items()
        if key not in {"trade_id", "opened_at_et", "closed_at_et", "expiration"}
    }
    normalized["opened_days_from_today"] = _days_from_today(audit.get("opened_at_et"))
    normalized["closed_days_from_today"] = _days_from_today(audit.get("closed_at_et"))
    for fill_audit in normalized.get("fills") or []:
        fill_audit.pop("fill_id", None)
        for date_key in ("executed_at", "executed_at_et"):
            if date_key in fill_audit:
                fill_audit[f"{date_key}_days_from_today"] = _days_from_today(
                    fill_audit.pop(date_key))
    return _jsonable(normalized)


def test_the_seed_fixture_reconstructs_to_its_recorded_snapshot(seeded):
    """
    The whole reconstruction, not six headline numbers.

    If this fails, read the diff before regenerating: it is reporting that the
    reconstructor, the FIFO assignment or the auditor now produces different
    output from the same twelve fills.
    """
    actual = _capture(seeded)

    if UPDATING:
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(json.dumps(actual, indent=2, sort_keys=True) + "\n")
        pytest.skip(f"snapshot rewritten: {SNAPSHOT_PATH}")

    assert SNAPSHOT_PATH.exists(), (
        f"no snapshot at {SNAPSHOT_PATH}. Create it with "
        "UPDATE_SNAPSHOTS=1 pytest tests/test_seed_snapshot.py"
    )
    expected = json.loads(SNAPSHOT_PATH.read_text())

    if actual != expected:
        actual_text = json.dumps(actual, indent=2, sort_keys=True)
        expected_text = json.dumps(expected, indent=2, sort_keys=True)
        import difflib
        diff = "\n".join(difflib.unified_diff(
            expected_text.splitlines(), actual_text.splitlines(),
            fromfile="snapshot", tofile="actual", lineterm=""))
        pytest.fail(
            "The seed fixture no longer reconstructs to its recorded snapshot.\n"
            "Every line below is a number or field that changed:\n\n"
            f"{diff}\n\n"
            "If the change is intended, regenerate with "
            "UPDATE_SNAPSHOTS=1 pytest tests/test_seed_snapshot.py"
        )


def test_the_snapshot_covers_the_auditor(seeded):
    """
    The reason this file exists. auditor.py is 378 lines producing the
    reconciliation output CLAUDE.md lists under extra care, and had no test
    before this one.
    """
    captured = _capture(seeded)
    audits = [trade["audit"] for trade in captured["trades"]]
    assert audits, "no trades captured"
    assert all(audit.get("fills") for audit in audits), (
        "every trade should have per-fill audit records"
    )
    assert any(audit.get("direction") for audit in audits), (
        "the auditor should classify direction for at least one trade"
    )


def test_every_seeded_fill_is_assigned_to_exactly_one_trade(seeded):
    """
    FIFO reconstruction must not drop or double-count a fill. Realized PnL can
    look right while a fill is orphaned, so this is checked separately rather
    than inferred from the totals.
    """
    captured = _capture(seeded)
    assigned = [raw_id for trade in captured["trades"] for raw_id in trade["fills"]]
    assert len(assigned) == len(set(assigned)), (
        f"a fill is attached to more than one trade: {sorted(assigned)}"
    )

    seed_module = _load_seed_module()
    expected_total = seed_module.EXPECTED["total_fills"]
    assert len(assigned) == expected_total, (
        f"{len(assigned)} of {expected_total} seeded fills are attached to a trade"
    )


def test_the_snapshot_holds_no_machine_specific_paths():
    """
    A snapshot that records an absolute path passes only on the machine that
    generated it. This is not hypothetical: the first CI run of this file
    failed on nothing but /home/runner/... against /home/user/... .

    Guarding the file rather than the normalizer, because the leak can arrive
    from any new field the auditor starts returning, not only the one known
    today.
    """
    assert SNAPSHOT_PATH.exists(), "snapshot has not been generated"
    raw = SNAPSHOT_PATH.read_text()
    for prefix in ('"/home/', '"/Users/', '"/root/', '"C:\\\\'):
        assert prefix not in raw, (
            f"the snapshot contains an absolute path starting {prefix}, so it "
            "will fail on any other machine. Normalize it in _jsonable and "
            "regenerate."
        )
