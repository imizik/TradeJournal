"""Create invented R3 browser cache only in a new disposable temporary root."""
import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.engine.market_map import ET  # noqa: E402
from app.engine.research_studio import session_dates, session_close  # noqa: E402


def seed(root, *, include_newer_mu=False):
    # This standalone fixture never selects an application or real cache path.
    if not root.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()) or root.exists():
        raise ValueError("fixture needs a new directory under the system temporary root")
    root.mkdir(mode=0o700)
    days = list(session_dates(date(2023, 7, 12)))
    if include_newer_mu:
        days += [d for d in session_dates(date(2026, 1, 12), version=2) if d >= date(2025, 12, 1)]
    for symbol in ("MU", "SPY"):
        folder = root / "sip" / symbol
        folder.mkdir(parents=True)
        for day in days:
            rows = []
            for minute in range(570, session_close(day)):
                # A complete, known decline then recovery on discovery days.
                base = 100 + (minute - 570) * .002
                if symbol == "MU" and (date(2023, 7, 3) <= day <= date(2023, 7, 12) or day >= date(2026, 1, 1)):
                    base += -2 if 590 <= minute < 605 else 1 if minute >= 615 else 0
                stamp = datetime(day.year, day.month, day.day, minute // 60, minute % 60, tzinfo=ET)
                rows.append({"t": stamp.astimezone(timezone.utc).isoformat(), "o": base, "h": base+.1,
                             "l": base-.1, "c": base, "v": 1000 if date(2023,7,3) <= day <= date(2023,7,12) or day >= date(2026,1,1) else 100})
            (folder / f"{day}.json").write_text(json.dumps(rows))
    (root / "store").mkdir(mode=0o700)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    p.add_argument("--include-newer-mu", action="store_true")
    args = p.parse_args()
    seed(args.root, include_newer_mu=args.include_newer_mu)
