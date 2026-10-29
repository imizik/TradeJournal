"""What the server runs and what automatic deployment decided recently.

Read-only. On the VPS the controller keeps releases under /opt/tradejournal and
deploy/autodeploy.py writes a readable copy of its state next to the app's
data; on a laptop neither exists and the page says so.
"""

from datetime import datetime, timezone
import json
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()

ROOT = Path("/opt/tradejournal")
STATUS = Path("/var/lib/tradejournal/autodeploy.json")
RELEASES = 10


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _when(path: Path) -> str:
    """When a symlink was switched or a release directory was installed."""
    return datetime.fromtimestamp(path.lstat().st_mtime, timezone.utc).isoformat(timespec="seconds")


@router.get("")
def deploys():
    running = _read(ROOT / "current/release.json")
    if running is None:
        return {"server": False, "running": None, "previous": None, "releases": [], "autodeploy": None}
    previous = _read(ROOT / "previous/release.json")
    releases = []
    directory = ROOT / "releases"
    for release in directory.iterdir() if directory.is_dir() else []:
        metadata = _read(release / "release.json")
        if metadata:
            releases.append({"release_id": release.name, "commit": metadata.get("commit"), "installed_at": _when(release)})
    releases.sort(key=lambda release: release["installed_at"], reverse=True)
    return {
        "server": True,
        "running": {"release_id": running.get("release_id"), "commit": running.get("commit"), "live_since": _when(ROOT / "current")},
        "previous": previous and {"release_id": previous.get("release_id"), "commit": previous.get("commit")},
        "releases": releases[:RELEASES],
        "autodeploy": _read(STATUS),
    }
