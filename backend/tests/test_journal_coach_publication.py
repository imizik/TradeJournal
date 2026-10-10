from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timezone

import pytest

from journal_coach_publication import (
    publication_digest,
    publish_snapshot,
    read_publication,
    rolling_window,
)
from journal_coach_snapshot import Snapshot


def _snapshot(*, generated_at: datetime | None = None) -> Snapshot:
    return Snapshot.model_validate({
        "schema_version": "journal-coach-snapshot-v1",
        "generated_at": generated_at or datetime.now(timezone.utc),
        "start_day": date(2026, 1, 1),
        "end_day": date(2026, 1, 1),
        "source": "approved_journal_export",
        "sample_data": True,
        "trades": [],
    })


def test_rolling_window_uses_eastern_calendar_and_dst():
    start, end = rolling_window(datetime(2026, 3, 8, 4, 30, tzinfo=timezone.utc), 3)
    assert (start, end) == (date(2026, 3, 5), date(2026, 3, 7))
    start, end = rolling_window(datetime(2026, 3, 8, 8, 30, tzinfo=timezone.utc), 1)
    assert (start, end) == (date(2026, 3, 8), date(2026, 3, 8))


@pytest.mark.parametrize("days", [True, 0, 32, 1.0, "2"])
def test_rolling_window_rejects_invalid_days(days):
    with pytest.raises(ValueError):
        rolling_window(datetime.now(timezone.utc), days)


def test_publication_round_trip_permissions_and_content_address_reuse(tmp_path):
    pointer = tmp_path / "published.json"
    snap = _snapshot()
    first = publish_snapshot(snap, pointer)
    again = publish_snapshot(snap, pointer)
    loaded, digest = read_publication(pointer)
    assert loaded == snap
    assert digest == first["snapshot_sha256"] == again["snapshot_sha256"]
    assert first["created"] is True and again["created"] is False
    assert stat_mode(pointer) == stat_mode(tmp_path / first["snapshot_file"]) == 0o640
    assert publication_digest(pointer) == digest


def stat_mode(path):
    return os.stat(path, follow_symlinks=False).st_mode & 0o777


def test_pointer_rejects_unknown_fields_bad_json_and_oversize(tmp_path):
    pointer = tmp_path / "published.json"
    for data in (
        b'{"snapshot_sha256":"' + b"a" * 64 + b'","extra":1}',
        b'{"snapshot_sha256":"' + b"a" * 64 + b'","snapshot_sha256":"' + b"b" * 64 + b'"}',
        b"{",
        b" " * 257,
        json.dumps({"snapshot_sha256": "A" * 64}).encode(),
    ):
        pointer.write_bytes(data)
        with pytest.raises(ValueError):
            publication_digest(pointer)


def test_relative_and_parent_traversal_paths_are_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for candidate in ("published.json", str(tmp_path / ".." / "published.json")):
        with pytest.raises(ValueError, match="canonical"):
            publication_digest(candidate)


def test_symlink_pointer_parent_and_snapshot_are_refused(tmp_path):
    pointer = tmp_path / "published.json"
    target = tmp_path / "target.json"
    target.write_text("{}")
    pointer.symlink_to(target)
    with pytest.raises(ValueError):
        publication_digest(pointer)
    pointer.unlink()

    linkdir = tmp_path / "linkdir"
    linkdir.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        publication_digest(linkdir / "published.json")

    digest = hashlib.sha256(b"x").hexdigest()
    (tmp_path / f"snapshot-{digest}.json").symlink_to(target)
    pointer.write_text(json.dumps({"snapshot_sha256": digest}))
    with pytest.raises(ValueError):
        read_publication(pointer)


def test_fifo_snapshot_is_refused_without_blocking(tmp_path):
    digest = "a" * 64
    pointer = tmp_path / "published.json"
    pointer.write_text(json.dumps({"snapshot_sha256": digest}))
    os.mkfifo(tmp_path / f"snapshot-{digest}.json")
    with pytest.raises(ValueError, match="not regular"):
        read_publication(pointer)


def test_bad_or_stale_candidate_keeps_prior_pointer_and_snapshot(tmp_path):
    pointer = tmp_path / "published.json"
    old = publish_snapshot(_snapshot(), pointer)
    old_pointer = pointer.read_bytes()
    stale = _snapshot(generated_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
    with pytest.raises(ValueError, match="stale"):
        publish_snapshot(stale, pointer)
    assert pointer.read_bytes() == old_pointer
    assert (tmp_path / old["snapshot_file"]).exists()
    assert len(list(tmp_path.glob("snapshot-*.json"))) == 1


def test_retention_keeps_current_and_two_previous_owned_files(tmp_path):
    pointer = tmp_path / "published.json"
    results = []
    for index in range(4):
        snap = _snapshot(generated_at=datetime.now(timezone.utc).replace(microsecond=index))
        # Ensure distinct serialized content and digest.
        result = publish_snapshot(snap, pointer)
        results.append(result)
    current = publication_digest(pointer)
    remaining = list(tmp_path.glob("snapshot-*.json"))
    assert len(remaining) <= 3
    assert (tmp_path / f"snapshot-{current}.json").exists()
    assert (tmp_path / "snapshot-not-owned.json").exists() is False

