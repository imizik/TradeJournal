# Morning plan through end-of-day review

Use this scenario when auditing the owner's daily thinking workflow. Follow
the parent UX skill and its sandbox instructions. This is an audit and fix
backlog, not permission to implement every finding or activate production.

## Outcome

The owner can record a morning market outlook and plans, add timestamped
thoughts during the day, and compare what was expected with the day's actual
market path and their actions. Preserve the original words and distinguish
the owner's thoughts from Jo's advice. Include ideas never traded and days
with no trades. A saved per-trade plan does not prove this whole journey works.

## Replay

Run in the isolated seeded sandbox with `--no-keys`; no real journal records,
provider calls, notifications, broker connections or model calls. Read the
frontend-proxied health response and confirm `ux_sandbox.db` before writes.
Use desktop 1440×900 and phone 390×844. Start from the app's navigation, not
hidden API endpoints. Never create missing features with browser mocks and
count those as product success.

Use invented entries with a unique run label:

1. Before open: "I expect SPY to hold 580 and test 585 by the close. Below
   578 invalidates that view. Wait for a reclaim before considering calls."
   Save the owner's outlook and plan; inspect Jo's briefing separately if
   available. Missing briefing must be visible and must not erase the plan.
2. During day: "SPY lost 578; my morning view is invalidated. I am standing
   aside until it reclaims 580." Save as a new update with its time and
   reason. Add a second idea and explicitly mark it untraded where supported.
3. Navigate away, reload, and reopen in a new browser context. Confirm the
   same original words, updates, timestamps and actor attribution. The update
   must not overwrite the original or silently become a new morning thesis.
4. Open the day's review through navigation. Locate the original expectation,
   intraday changes, actual market path, actual journal trades and untraded
   ideas. Assess whether the owner can tell what was right, what invalidated
   the view and whether actions followed the plan. Repeat on a no-trade day.
5. Exercise an empty/missing-data state and one failed save using a browser
   request failure on the sandbox. Confirm the draft survives, failure is
   visible, and retry saves once without duplicate entries. Restore normal
   requests and prove the record survives reload.

Do not alter server timestamps to pretend one real-time session spanned a
trading day. Use existing dated fixtures if available and report simulated
timing. Provider or AI fixtures prove integration/rendering only; label their
origin. Do not launch external inference. Missing actual-path or generated
review evidence stays blocked/unverified. If a fixture is necessary, keep it
isolated to test data and preserve the distinction in every result.

When an entry point is absent, record that step as blocked and inspect the
other existing stages independently. Do not end the entire audit at the first
missing field, substitute a per-trade note without disclosing it, or claim
later stages passed because their components render.

## Evidence and reruns

Keep run evidence under `backend/data/ux_sandbox/journey-runs/<run-id>/` (local
ignored sandbox data): a short report and screenshots of relevant states.
Record commit and dirty diff, run time, environment/health, viewport, exact
click path and test text, fixture provenance, and pass/fail/blocked/unverified
for each step. Inspect the screenshots. Label Observed, Code and Hypothesis
claims; link evidence and retain earlier runs when comparing fixes.

Keep at most five actionable findings, with stable IDs, owner consequence,
smallest suggested fix and a browser-visible acceptance check. On rerun,
mark which findings are new, unchanged or verified fixed. An unchanged build
and unchanged blockers need no duplicate full replay or notification. When
relevant code or test conditions change, rerun affected steps plus the
whole journey before declaring completion. Never reset the sandbox to hide
failed persistence; preserve evidence before any documented reset.

The recurring UX follow-up audits and suggests fixes. It may maintain its
local evidence/backlog and perform already authorized test-app repairs;
new product features, migrations and production activation remain separate
implementation decisions. Never merge or deploy as part of an audit run.

## Finish

Complete only after all five steps work through the real UI on desktop and
phone, including new-context persistence, untraded and no-trade cases, honest
market-data provenance and recoverable failed saves. Report remaining limits
of fixture timing and real scheduled Jo delivery separately. Notify once on
completion, then disable the recurring follow-up using the automation tool.
If an external permission or missing product feature prevents progress,
report the concrete action needed once and remain quiet until it changes.
