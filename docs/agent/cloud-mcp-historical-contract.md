# Historical demo MCP choices

2026-10-09 — extend the existing connector to one assigned prepared historical
MU/NBIS demo exercise. This uses the merged historical browser engine; the
separate date-input fix is outside this change.

## Explicit mode and permissions

`exercise_kind` defaults to `synthetic` in the existing offline connector
configuration. Set it explicitly to `historical` only for the separately linked
historical assistant. Changing the mode or subject/principal binding requires
restarting both verifiers; live configuration cannot switch their identity or
evidence contract. Keep `sample_only=true`: this means the isolated demo
installation, while returned `sample_data=false` identifies real provider bars.

Historical reads and receipts require existing OAuth `d0:profile practice:read`,
one current assigned run, MU/NBIS symbol bounds, `journal_read=false`,
`market_decision_write=true`, `historical_replay=true`, and no ordinary sample
writer/replay permissions. The frozen run's assigned actor must match the linked
principal. Require the existing isolated historical factory/flags plus explicit
`TJ_CLOUD_MCP_HISTORICAL_ENABLED=true`. Production's ordinary factory refuses
this mode even with environment flags set. No new permission or ingress is
activated by merging.

Writes additionally require OAuth `practice:write`, strict
`decision_writes=true` and `TJ_CLOUD_MCP_DECISION_WRITES=true`. Recheck current
principal version, expiry, enabled state, grants and configuration after body
reception under the browser writer/revocation serialization boundary.

## Tools and evidence

Reuse `list_practice_runs`, `get_practice_run`, `get_practice_choice` and
`record_practice_choice`, with the existing profile tool and bounded Unix bridge.
The envelopes are `historical-demo-practice-v1` and
`historical-demo-choice-v1`, with `demo_only=true`, `historical_replay=true`,
`sample_data=false`, UTC read time and America/New_York display zone.

Return only frozen pre-cutoff evidence and own immutable choices. Keep original
bar timestamps, provider retrieval time, simulated information cutoff, real
exercise deadline and real receipt time distinct. Missing bars/partial intervals
and source provenance remain in the packet. Preserve existing historical TAKE
source-link, cost, freshness and expiry validation; WAIT expiry uses the same
historical validator as the browser. The server derives identity, context,
symbol and the browser's `history:` operation key. Identical retries recover the
same record, changed content conflicts and expired exercises retain receipts.

MCP neither starts nor reads historical replay results, even after a browser
replay has started. It never accesses sealed continuation, creates contexts,
reveals agent choices, arms paper/live orders, schedules work, calls a provider
or pays for model inference. Replay remains in the separately authorized browser.
An uncertain save directs receipt retrieval before retry or another entrance.

## Verification and activation

Signed OAuth fixtures must cover TAKE/WAIT/SKIP, browser/MCP identity, concurrent
retries, expired receipts, changed-content conflicts, lost response recovery,
current revocation during body reception, integrity and frozen-actor mismatch,
wrong mode/flags/assignment/scope and hidden replay. Existing synthetic D1/D2
coverage must remain green. Run full repository verification, disposable Unix
bridge smoke, and tier-two general/focused native reviews before ready status.

Manual demo activation is a separate operational step: use a reviewed source
bundle, private recovery materials and an explicitly linked historical account;
never widen the existing synthetic account's assignment or replace old receipts.
Preserve the other worktree's date fix. Actual Jo save/read/UI receipt comparison
and grouped demo-service restart are pending until that setup is performed; local
fixtures and CI do not satisfy those live acceptance checks.
