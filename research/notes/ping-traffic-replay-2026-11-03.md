# Phone-ping traffic replay — 2026-11-03

`backend/tests/test_ping_traffic_replay.py` replays 67 invented candidate pings
on October 29, 2026, from 08:40 through 16:30 New York. This is a synthetic
gap-day workload, not a reconstruction of personal trades or production rows.

Coverage:

- Every canonical policy kind and every alias, using real `decide()` and
  `budget()` with default budgets, the 12/day ceiling and the morning brief on.
- Pre-open headline pressure and the reserved morning-brief slot; excess
  thesis, research, nudge, interrupt, companion and Radar traffic.
- Distinct anchors for otherwise eligible position and Radar alerts, so their
  starvation cannot be attributed to the per-position quiet window.
- Immediate simulated delivery of accepted decisions; retries of every source
  reuse its decision and ledger ID. A second give-back on the same anchor within
  the quiet window is suppressed. Per-kind sent counts stay within budgets.
- An evening review after the ceiling is exhausted.
- The migrated SQLite engine pinned by `backend/tests/conftest.py`, with an outer
  transaction rolled back after each replay. The pin is unchanged. No production
  reads, external calls, real transport sends or provider charges are needed.

## Finding: shared ceiling still starves eligible alerts

The requested non-starvation acceptance assertions fail under the current policy:
the first four Radar singles and first two digests are held with unused budgets.
The busy open spends 10 non-companion slots; hold-hour and wrong-way use the last
two by 09:42. The subsequent time stop, expiry-first, expiry-eve and entry alerts
are held with reason `Not sent: 12 pings already went out today (cap 12).`
Retries retain the original hold, so there is no later release of those sources.

The evening review, give-back, invalidation and expiry-final pass. Companion
updates do not consume other kinds' ceiling slots; they are themselves capped
after 10 updates because two pre-open pings already counted toward their ceiling.

This is consistent with the current documented ceiling, but it fails the stronger
requested guarantee that Radar and position alerts survive unrelated traffic.
Policy changes require a separate owner decision. Replay-only PR #661 deliberately leaves
the acceptance failures visible, without skips, xfails, cap increases or changes
to `notification_policy.py`.

The delivery timestamps are simulated bookkeeping only. Ledger retry identity
does not prove transport at-most-once delivery: `decide()` intentionally returns
`send` again for a previously sent source, and actual senders own their outboxes.
This test does not prove phone receipt, scheduling latency, concurrent sender
behavior or live usefulness. Different alert kinds on the same position can be
legitimate sends; the duplicate assertion targets the same kind in its quiet window.

Run from `backend/`:

```sh
python -m pytest -q tests/test_ping_traffic_replay.py tests/test_notification_policy.py
```

## Follow-up: owner requested shared-cap removal

The separate `codex/remove-shared-ping-cap` branch removes the shared ceiling,
retains category budgets, pre-open allowance, quiet windows and retry semantics,
and runs the same non-starvation acceptance assertions. The replay explicitly
sets the obsolete `PING_DAILY_CAP=0` to prove it cannot re-enable starvation.
The original findings above describe the unchanged policy in replay-only PR #661.
