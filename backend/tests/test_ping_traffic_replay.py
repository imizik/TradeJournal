"""Synthetic gap-day acceptance replay; no market, outbox or transport access.

The requested non-starvation guarantees deliberately fail if the shared ceiling
holds an otherwise eligible alert. Do not raise the cap or xfail that evidence.
"""

from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session, select

from app.database import engine
from app.engine import notification_policy as policy
from app.engine.chart_math import ET
from app.models import PhonePing


def at(hhmm):
    return datetime.fromisoformat(f"2026-10-29T{hhmm}:00").replace(tzinfo=ET).timestamp()


def utc(stamp):
    return datetime.fromtimestamp(stamp, UTC).replace(tzinfo=None)


def traffic():
    """Headlines first, busy open, then Radar/position decisions into the close."""
    events = []

    def add(hhmm, kind, source, anchor=None):
        events.append(dict(now=at(hhmm), kind=kind, source_id=source,
                           anchor=anchor or f"symbol:SYNTH-{source}"))

    add("08:40", "thesis_watch", "early-headline")
    add("09:00", "prep", "morning-brief")
    for i in range(15):
        add(f"09:{i + 1:02d}", ("thesis_watch", "research", "nudge")[i % 3], f"preopen-{i}")
    # Companion traffic must not consume another kind's ceiling allowance.
    for i in range(13):
        add("09:30", "companion_update", f"companion-{i}")
    for kind, count in (("thesis_watch", 3), ("research", 2), ("nudge", 3), ("interrupt", 5)):
        for i in range(count):
            add("09:32", kind, f"open-{kind}-{i}")
    # Exercise every alias too, including shared prep/nudge budgets.
    for kind in ("link", "no_plan", "companion_adopt", "week_review", "day_replay"):
        add("09:40", kind, f"alias-{kind}")
    # Distinct positions: quiet-window suppression cannot explain starvation.
    for i, kind in enumerate(("hold_hour", "wrong_way", "time_stop", "expiry_first", "expiry_eve", "entry")):
        add(f"09:{41 + i:02d}", kind, f"position-{kind}")
    for i in range(5):
        add(f"{10 + i:02d}:05", "radar_event", f"radar-single-{i}")
    for i, hhmm in enumerate(("10:00", "14:00", "15:00")):
        add(hhmm, "radar_digest", f"radar-digest-{i}")
    for kind in ("giveback", "invalidation", "expiry_final"):
        add("15:30", kind, f"late-{kind}")
    # One duplicate give-back on the same anchor inside the quiet window.
    add("15:31", "giveback", "duplicate-giveback", "symbol:SYNTH-late-giveback")
    add("16:30", "evening_review", "evening-review")
    return sorted(events, key=lambda event: event["now"])


@pytest.fixture
def replay(monkeypatch):
    # conftest.py owns the database pin and migration chain. Use that engine,
    # with a rollback around policy.decide()'s internal commits.
    assert engine.url.get_backend_name() == "sqlite"
    assert "trade-journal-tests-" in engine.url.database
    for name in ("PING_DAILY_CAP", "PING_QUIET_MINUTES", "PING_PREOPEN_ALLOWANCE", "PREMARKET_PREP_AT",
                 *(f"PING_BUDGET_{kind.upper()}" for kind in policy.BUDGETS)):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ALERT_POLICY_ENABLED", "true")
    monkeypatch.setenv("PREMARKET_PREP_ENABLED", "true")
    assert policy.daily_cap() == 12
    with engine.connect() as connection:
        connection.exec_driver_sql("BEGIN")
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            events = traffic()
            start, end = policy.day_bounds(events[0]["now"])
            assert not db.exec(select(PhonePing).where(PhonePing.decided_at >= start, PhonePing.decided_at < end)).all()
            retries = []
            for event in events:
                args = dict(event, sender="synthetic-gap-day", title=f"Synthetic {event['kind']}", body="Invented replay traffic.")
                ticket = policy.decide(db, **args)
                # Fail-open must never masquerade as successful replay evidence.
                assert ticket.id is not None, ticket.reason
                if ticket.action == "send":
                    policy.delivered(db, ticket, event["now"])
                    db.commit()
                retried = policy.decide(db, **dict(args, now=event["now"] + 1))
                retries.append((ticket, retried))
            rows = db.exec(select(PhonePing).where(PhonePing.sender == "synthetic-gap-day").order_by(PhonePing.decided_at)).all()
            yield rows, retries, events
        connection.rollback()


@pytest.mark.parametrize("kind", ("radar_event", "radar_digest"))
def test_gap_day_radar_gets_its_budget_without_waiting(replay, kind):
    rows, _, _ = replay
    candidates = [row for row in rows if row.kind == kind]
    eligible = candidates[:policy.budget(kind)]
    assert [(row.source_id, row.decision, row.reason) for row in eligible if row.decision != "sent"] == []
    assert all(row.delivered_at == row.decided_at for row in eligible)
    assert candidates[-1].decision == "over_cap"
    assert candidates[-1].reason == policy.budget_reason(kind, policy.budget(kind))


def test_gap_day_position_alerts_are_not_starved_by_other_kinds(replay):
    rows, _, _ = replay
    positions = [row for row in rows if row.source_id.startswith(("position-", "late-"))]
    assert len(positions) == 9
    assert all(policy.budget(row.kind) is None for row in positions)
    assert [(row.kind, row.reason) for row in positions if row.decision != "sent"] == []
    assert all(row.delivered_at == row.decided_at for row in positions)


def test_gap_day_evening_review_is_immediate_even_after_the_cap(replay):
    rows, _, _ = replay
    evening = next(row for row in rows if row.kind == "evening_review")
    assert sum(row.decision == "sent" and row.decided_at < evening.decided_at for row in rows) > policy.daily_cap()
    assert evening.decision == "sent"
    assert evening.decided_at == evening.delivered_at == utc(at("16:30"))


def test_gap_day_budgets_quiet_window_and_retry_ledger(replay):
    rows, retries, events = replay
    assert {row.kind for row in rows} == set(policy.PRIORITY) | set(policy.ALIASES)
    assert len(rows) == len(events)
    assert len({(row.sender, row.source_id) for row in rows}) == len(events)
    for first, retried in retries:
        assert (first.id, first.action, first.reason, first.append) == (retried.id, retried.action, retried.reason, retried.append)
    spent = Counter(policy.canonical(row.kind) for row in rows if row.decision == "sent")
    # Companion updates are themselves subject to the ceiling; earlier prep
    # and thesis traffic can legitimately leave fewer than their own 12 slots.
    assert spent["companion_update"] > 0
    for kind in policy.BUDGETS:
        assert spent[kind] <= policy.budget(kind)
    preopen = [row for row in rows if row.decided_at < utc(at("09:30")) and row.decision == "sent"]
    assert [row.kind for row in preopen] == ["thesis_watch", "prep"]
    duplicate = next(row for row in rows if row.source_id == "duplicate-giveback")
    assert duplicate.decision == "suppressed"
    assert duplicate.delivered_at is None
    # Same anchor/kind inside the quiet window has one sent ledger row.
    assert sum(row.anchor == duplicate.anchor and row.kind == duplicate.kind and row.decision == "sent"
               and abs(row.decided_at - duplicate.decided_at) <= timedelta(minutes=10) for row in rows) == 1
