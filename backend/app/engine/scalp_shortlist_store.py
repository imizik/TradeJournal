"""Private, per-session paper records shared by the recorder and the owner UI."""
import json
import os
import tempfile
from pathlib import Path


def study_dir() -> Path:
    return Path(os.environ.get("SCALP_SHORTLIST_DIR") or Path(__file__).resolve().parents[2] / "data" / "scalp_shortlist")


def read_record(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def publish_once(path: Path, value: dict) -> dict:
    """Publish a complete file exactly once. A concurrent loser gets the winning record."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent)
    pending = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(pending, path)
        except FileExistsError:
            return json.loads(path.read_text(encoding="utf-8"))
        if os.name == "posix":
            dir_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        return value
    finally:
        pending.unlink(missing_ok=True)
