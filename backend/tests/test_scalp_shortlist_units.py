"""The release packages a finite, opt-in study without enabling it."""
import importlib.util
from datetime import date, timedelta
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"


def test_shortlist_timers_match_study_and_are_opt_in():
    spec = importlib.util.spec_from_file_location("release_control", DEPLOY / "control.py")
    control = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(control)
    expected = {date(2026, 11, 4) + timedelta(days=i) for i in range(29)}
    expected = {d for d in expected if d.weekday() < 5 and d != date(2026, 11, 26)}
    for phase, when in (("warmup", "08:50:00"), ("live", "09:40:03"), ("recap", "10:20:00")):
        name = f"tradejournal-scalp-shortlist-{phase}.timer"
        assert name in control.OPT_IN_TIMERS and name in control.OPTIONAL_UNITS and name not in control.TIMERS
        timer = (DEPLOY / "systemd" / name).read_text()
        dates = set()
        for line in timer.splitlines():
            if line.startswith("OnCalendar="):
                month, clock, tz = line.removeprefix("OnCalendar=").split()
                assert (clock, tz) == (when, "America/New_York")
                prefix, days = month.rsplit("-", 1)
                dates.update(date.fromisoformat(f"{prefix}-{d}") for d in days.split(","))
        assert dates == expected
        assert f"Unit=tradejournal-scalp-shortlist@{phase}.service" in timer
    assert "Persistent=false" in (DEPLOY / "systemd/tradejournal-scalp-shortlist-live.timer").read_text()
