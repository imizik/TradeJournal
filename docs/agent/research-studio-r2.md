# Research Studio R2: reproducible discovery analysis

**R2 selected and implemented in this chat after R1. Review and final verification gates are recorded in the PR.**
R3/R4, app screens, Factory promotion, provider fetching and deployment/activation
are not selected. [R1](research-studio-r1.md) remains the observation/source
contract; [the roadmap](../strategy-workbench-roadmap.md) owns later phases.

## Computation

`app.engine.research_studio_analysis` consumes a supplied immutable R1 snapshot.
The ordinary population uses exactly R1's predicate eligibility masks, universe,
window and dates, includes qualifying moments, and retains the first qualifying
moment per target/session as the event population. Declines remain negative;
there is no outcome-side inversion, stop, cost, R, P&L or execution inference.

The reference is the immediate next five-minute bucket's open at the decision
close, provided that entire bucket is complete and in the same session. No
skipping a missing/partial next bucket or using the next session. Exact endpoint
closes are reference+15/30/60 minutes and scheduled session close. An endpoint
requires its complete five-minute bucket; holes elsewhere do not invent prices
or become a different endpoint. Missing reference excludes every horizon;
missing endpoint excludes only that horizon. Percent returns use reference
price; ATR returns use prior daily ATR14 frozen at decision, with R1's complete
prior-14-session mask. Missing ATR does not erase otherwise available percent
returns. Result N and reasons are separate for each horizon and normalization.

Baseline means use ordinary eligible outcomes at the same symbol and decision
clock. Group weights are the available event population's symbol/clock shares
for that horizon/unit. Qualifying moments are included in controls. Missing
required matches makes the baseline/difference unavailable. Raw ordinary N,
matched ordinary N, event N, weights and exclusions are stored separately.
These are descriptive comparisons, not causal or regime-controlled inference.

The primary descriptive horizon is 30 minutes. Uncertainty uses the frozen R1
specification: chronologically ordered distinct calendar weeks from the complete
eligible event/control universe, 2,000 joint replacement draws of that number
of weeks, NumPy PCG64 seed0, all symbols together, event/control composition and
weights recomputed every draw, 95% linear percentile intervals. Zero-event or
missing-required-control draws are invalid and counted. Fewer than20 eligible
weeks or fewer than1,900 valid draws makes intervals unavailable. Weeks are
approximate dependence blocks, not asserted independent samples. Adaptive
research and previously revealed outcomes remain exposure, not validation.

## Research-owned persistence and process lifecycle

`app.engine.research_studio_store` requires an explicit existing owner-controlled
local directory outside, and not an ancestor of, the approved source root.
Root binding and every artifact/lock open use no-follow descriptors and pinned
root identity. No source directory, journal database, Factory ledger, credential
file or old pickle is written/read by the store. Source requests still use R1's
approved loader and validate all dates before source opens.

The authoritative index is `ledger.sqlite3`, containing immutable run requests,
separate attempts, append-only transitions, operation IDs and outcome exposures.
SQLite opens only `:memory:`: Python3.11+ serialization loads/saves its image
through bounded, no-follow files. A ledger kernel lock serializes short write
transactions; atomic replacement and directory fsync publish the image. This
avoids a path-following SQLite/WAL open or coupling to the app database. Explicit
local single-host storage only; network filesystems and multi-host workers are
unsupported. Prepared snapshots and results are bounded content-addressed files
created with no-overwrite links, fsync and recorded SHA256. There is no automatic
pruning or rewriting of prior results. Corruption is refused and requires owner
inspection; the worker does not repair modified metadata silently.

One parent holds the research worker lock throughout a finite `work-once` call,
claims one queued attempt, and runs a separate computation child. The child
receives a bounded immutable envelope, opens no source/store files and never
writes durable status. The parent validates result identity and commits artifacts
and completion. The child inherits the execution lock so a dead parent's still
live child cannot be mistaken for completed recovery; it detects parent death at
calculation checkpoints. This lane has no `job_run`, sync dependency, daemon,
service/timer installation or automatic startup. At most four queued/running
runs are admitted. Extra submissions/retries refuse when capacity is occupied.

Cancel queued work immediately. For running work the parent observes the durable
request, terminates the child cooperatively, then kills it after400ms if needed;
only after the child stops does it commit cancellation. No partial results are
exposed. Keyboard interruption also stops the child. A later worker holding the
execution lock marks dead running attempts failed/cancelled and does not replay
them. Retry is explicit, increments the attempt, preserves the logical run and
prior history, and cannot run changed engine code against an old snapshot.

Run identity binds canonical definition, raw/prepared data identity, R1 and R2
code fingerprints, analysis specification and NumPy version. Submission saves
the actual specification and NumPy version; cached results retain those labels
and remain reopenable after an upgrade. Queued/retried work refuses changed
code/version before prepared-data access. Every new enqueue
rereads/hashes approved source data; same-date corrections create a new run.
A repeat operation UUID with the identical action/run is idempotent; conflicting
reuse refuses. Reopening completed results appends one exposure for a new UUID;
repeating the same UUID does not duplicate it. Status does not reveal outcomes.
There is no claim that this captures arbitrary manual inspection outside Studio.
Parent variants, notes/verdicts and richer per-occurrence browser exposure belong
to later phases; they are not implemented here.

## Manual use

Create a separate private research directory once. Every command supplies both
roots; no root is discovered from `.env`, provider credentials or an HTTP input.
Use a fresh canonical UUID for each new enqueue/result/control operation, and
reuse it only when retrying the identical request. Definitions must be outside
both source and research roots. Run from `backend`:

```bash
python scripts/research_studio_run.py \
  --cache-root /operator/approved/stocks/1Min/sip \
  --store-root /operator/research-studio \
  enqueue --definition /tmp/question.json --operation-id YOUR_UUID
```

With the same root options, `work-once` executes one queued run; `status --run-id
RUN_ID` inspects state; `result --run-id RUN_ID --operation-id NEW_UUID` records
and returns an outcome exposure; `cancel` and `retry` accept the same run/operation
arguments. Submission and worker output contain status only. Definitions and
source snapshots are frozen at submission; retries use those exact inputs.
No app page exists until R3. No production service or private API is exposed.

## Acceptance evidence and remaining limits

Synthetic tests independently pin next-open/endpoint values, early closes,
missing/partial reference, horizon-only gaps, frozen ATR and percent availability,
weighted matching including qualifiers, joint-symbol shocks, recomputed draw
composition against closed-form calculations, deterministic seed, insufficient
weeks/draws, cancellation, real subprocess death and explicit recovery/retry,
operation conflicts, immutable reopen/exposure, corrections and protected opens.
A fixed-design null simulation with seed9841,40 joint weeks and30 independent
trials found28/30 nominal95% intervals covering zero. This is a bounded Monte
Carlo diagnostic; it is neither universal calibration nor a requirement that
every null trial look insignificant. It does not rehabilitate adaptive choices.

The approved-cache sharp-decline example selected269 events and71,896 ordinary
moments. The30m percent horizon retained all269 events, had no missing matches,
used66 eligible calendar weeks and2,000 valid draws with zero invalid draws.
The one explicit result retrieval was recorded as an exposure; it is not new
independent validation.

An end-to-end pass measured15.61s source snapshot,5.21s submission/serialization,
7.40s worker execution including child startup and re-preparation, and28.27s
total including result retrieval. Cached retrieval was5.8ms. Parent peak RSS was
341,049,344 bytes (325.2MiB); calculation child peak was467,566,592 bytes
(445.9MiB). This question met the completed-run time and per-process RSS targets
on this host. It does not establish all windows/workloads or concurrent-load
latency. Tests measured <=1s parent cancellation of an uncooperative child.

Full verification, native tier2 review and final-head CI are pending. The R0 targets remain <=30s warm/
<=60s cold completed analysis, <=512MiB research-process RSS, and <=1s cancellation
acknowledgment. R3 browser/API feedback is unmeasured; no latency promise is made.
