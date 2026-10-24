# Overnight engineering foundation

## Handoff to Claude

Codex owns branch `codex/overnight-foundation` in
`/Users/user/.codex/worktrees/5baf/TradeJournal`.
Reserved files: `backend/scripts/overnight_trial.py`,
`backend/tests/test_overnight_trial.py`, this document, and one entry in
`docs/agent/feature-map.md`. Please keep hypothesis generation, interpretation,
research protocols and Factory proposals in your separate workstream. Codex
will not edit Factory gates, its ledger, Research Studio internals, Radar rules,
or Jo/Dots/copilot files. This foundation uses only invented discovery data.

Integration boundary: a future approved coordinator can pass a frozen assignment
to the existing deterministic evaluator and collect a receipt. It must never
send the owner morning report, protected outcomes, or raw evaluation artifacts
back to the hypothesis generator. No shared runtime is being activated here.

Ownership was checked against `claude/autonomous-trading-research-0a764a` at
`25f6cfcc`; the user is relaying this handoff. Acknowledgment is not assumed.

## Reuse and the smallest architecture

Inspected against `25f6cfcc` on October 24, 2026. These are source-code findings,
not a claim that any service is currently running or collecting complete data.

| Existing infrastructure | Reuse | Boundary / missing proof |
| --- | --- | --- |
| [Strategy Factory](strategy-factory.md), `scripts/factory_week.sh` | Existing strategy engine, random baselines, costs, stages, candidate review and protected `factory/ledger` accounting | Weekly launchd depends on the Mac. Its directory lock can remain after a crash; direct CLI writers do not share it. `--rerun` can reopen an exam. Do not automate more writers or reset counts. |
| `backend/scripts/strategy_factory.py` prepare/cache | Fetches missing ticker-days and reuses SIP minutes; deterministic `run` is offline | Derived pickle cache writes are not an immutable dataset release; its latest-date key does not detect all same-date corrections. Do not share a writable live cache with research. |
| [Research Studio R2](agent/research-studio-r2.md) | Explicit source roots, content-addressed inputs/results, append-only attempts/exposures, UUID idempotency, kernel locks, isolated calculation child, explicit retry | Single local host; no multi-host queue. Failed/interrupted work does not replay automatically. Studio is a descriptive event lab, not Factory strategy validation. |
| [Prospective MU study](agent/research-studio-prospective-mu.md) | Existing finite collection, immutable intents and receipts, bounded requests, restart-safe partial collection, frozen final-review protocol | Specific registered study, not permission to collect other periods or symbols. Keep its outcome and exposure records separate. |
| [Radar](radar.md#calibration-and-replay) | Read-only `backend/scripts/radar_replay.py`, recorder coverage/pass records, versioned rules and universe | Later use only an approved frozen export; record both universe/rule versions and missing passes. No live recorder or thresholds changed here. |
| [Application jobs](agent/background-jobs.md) | Proven kernel-lock ownership, failure recovery and separate worker-lane patterns | Runs against the app database; a research lane there would not provide CPU/memory isolation. Reuse ResearchStore instead. |
| [Deployment](../deploy/README.md) and existing GitHub workflows | Finite systemd jobs, opt-in timers, CI, release checks, status/notification patterns | No new unit, workflow, notification or timer is installed. Merging can auto-deploy the app; this PR remains for the owner to merge. |

Use a small finite command as the coordinator, existing ResearchStore as the
deterministic executor, and files as the handoff and report. A dedicated Linux
research host with local persistent storage is the preferred eventual compute
location; GitHub Actions is suitable for bounded engineering assignments and
fixture rehearsals. A job should pin an existing repository SHA and an approved
immutable dataset version. Do not merge latest main mid-experiment. An ephemeral
runner must retain its authoritative store before it can resume anything.

The three logical lanes remain separate:

1. **Engineering / Codex:** one explicit issue, owned paths, a branch, focused
   tests, required review and CI, and a PR receipt. No automatic consequential
   merge. No engineering agent is launched by this increment.
2. **Research / Claude:** frozen hypothesis/protocol proposal and interpretation
   supplied by the existing research workstream. The proposal process gets only
   an approved discovery brief, never the consolidated owner report or protected
   evaluation artifacts. A result-reporting directory is not a model context.
3. **Deterministic evaluation / Python:** existing Studio for discovery events;
   Factory remains the sole strategy validator. Future Factory automation needs
   an exclusive ledger writer, stable experiment/variant accounting and an
   audited proposal boundary first. None of its gates, periods, costs, baselines,
   Bonferroni counts, frozen rules or protocols change here.

Factory's existing brief includes prior confirmation information (exam numbers
are reduced to verdicts). That is not sufficient to promise the stricter
"hypothesis agent never sees protected outcomes" requirement. Claude and the
owner must resolve the permitted brief before connecting that lane; do not
silently reuse the full ledger digest. This foundation never opens the ledger.

No second backtester, agent framework, broker integration or research database
is needed. The new receipt adds assignment/SHA/budget/report metadata around the
existing research ledger, which stays authoritative for attempts and results.

## Codex scheduling capabilities

The desktop automation tool exposed in this session creates local cron jobs or
chat heartbeats; it is not evidence of a Mac-independent execution host. Current
official [Agents API documentation](https://developers.openai.com/api/docs/guides/agents-api/overview)
describes managed Codex sessions and hosted environments; its
[scheduled automations](https://developers.openai.com/api/docs/guides/agents-api/sessions/automations)
can dispatch new or existing sessions. Those calls and hosted compute are billed
API resources, require separate authorization, and have not been configured or
tested for this account. Scheduled invocation accepted is not job completion.

Existing systemd or GitHub scheduling is enough for deterministic jobs once the
host, persistent artifact retention and supervised acceptance are approved.
Cloud engineering availability, subscription eligibility and enforceable agent
tool/spend limits must be verified in the chosen environment before unattended
agent work. No API fallback or new automation is installed in this change.

## Implemented fixture rehearsal

`backend/scripts/overnight_trial.py` supports `init`, `run`, `report` and explicit
`retry`. It only seeds the existing invented MU/SPY discovery fixture into a new
private directory under the OS temporary root. There is no external dataset,
arbitrary shell-command, agent, provider, credential, Factory or application-DB
selector. It does not read `.env`. Python 3.11+ and existing backend dependencies
are required; Linux/macOS POSIX locks and signals are required.

- One fixed assignment, one worker per trial root, at most two research attempts.
  Separate manually created roots are independent; host-level concurrency is a
  future activation responsibility, not a cross-host lease implemented here.
- Initialization and each evaluation have a 120-second wall-time limit. At most
  360 seconds of bounded initialization/evaluation across the two attempts,
  excluding short control/report commands and scheduler downtime. Zero agent
  tool calls, model calls, provider calls, API spend and Factory candidates.
- `receipt.json` records the coordinator UUID, assignment, source SHA/dirty flag,
  script and engine hashes, dataset ID, artifacts, state transitions, timestamps,
  coverage, research attempts, worker metrics, failure, retry state, usage and
  approval requirement. `research/ledger.sqlite3` owns durable research history;
  snapshots/results stay in the existing content-addressed run directory.
- `run` consumes only the trial's dedicated queue. Completed runs are reused;
  repeating `run` or `report` does not add an attempt or repeat result exposure.
  A dead worker becomes failed. A surviving child or live worker prevents
  recovery. Retry is explicit and retains the same run ID and prior attempts.
- `report` reconciles state and regenerates the owner report. It never executes
  queued work. It may mark a dead attempt failed and records the single
  idempotent result exposure after completion. It is not a read-only operation.
- Initialization interruption before a saved research reference is reported as
  incomplete; inspect and retain that root, then use a new root. No evaluation
  was dispatched by initialization. Storage corruption is refused, not repaired.
  CLI exits 0 for queued/completed operations, 1 for failed/cancelled work, 2 for
  refused requests. A hard kill needs the next explicit `report` to reconcile;
  if disk is unwritable, retain stderr rather than assume a report was saved.
- Reports contain all six requested sections. They label engineering/Radar as
  unassigned and synthetic research as non-evidence. No PR, hypothesis rejection
  or success is invented. Owner report output must never feed proposal context.

Example local fixture run from the repository root (no activation):

```bash
PYTHON=/path/to/backend/.venv/bin/python
TRIAL_ROOT="$($PYTHON -c 'import tempfile,uuid; from pathlib import Path; print(Path(tempfile.gettempdir()) / ("tj-overnight-" + str(uuid.uuid4())))')"
"$PYTHON" backend/scripts/overnight_trial.py init --root "$TRIAL_ROOT"
"$PYTHON" backend/scripts/overnight_trial.py run --root "$TRIAL_ROOT"
"$PYTHON" backend/scripts/overnight_trial.py report --root "$TRIAL_ROOT"
```

After an inspected failure only, use `retry --root "$TRIAL_ROOT" --operation-id
YOUR_CANONICAL_UUID`, then `run`. Reuse that UUID only for the identical retry.
Keep the entire root, including ledger and immutable snapshots/results; a
Markdown report alone is insufficient for recovery. Temporary storage can be
cleaned by the OS, so it is explicitly not the unattended retention solution.

## Activation, rollback and first supervised overnight

**Not activated.** First review/merge this PR, then approve a single manually
started fixture trial on a named dedicated nonproduction Linux host, pinned to
the approved commit, without production mounts, secrets or outbound network.
Cap the container/service at one CPU, 1 GiB memory, 1 GiB writable disk, one
process group per trial and a 10-minute outer timeout. Set BLAS thread counts to
one. Those host caps are proposed acceptance controls, not installed features.
Preserve the trial root and stderr in an owner-only retained artifact directory
before runner teardown. No timer, provider or model call is needed for that trial.

The first supervised overnight should be the same finite rehearsal started at
night, with its artifacts inspected in the morning; do not make it run for hours
merely to call it overnight. Check normal completion, a duplicate invocation,
a killed worker followed by `report`, one explicit retry with the same research
identity, and no second automatic retry. Confirm the report describes failure
when interrupted and does not claim a trading finding. A synthetic seven-event
result proves plumbing only, not strategy quality or Radar usefulness.

After that, approval is needed for (1) a named discovery-only dataset export and
its immutable manifest, (2) durable non-temporary host storage and resource/
retention limits, and (3) a recurring schedule with a failure-only notification
destination. Enabling real-data assignments needs a separately reviewed adapter;
this fixture-only command intentionally has no switch for them. Agent dispatch
needs its own scoped tools, spend authorization and hard limits. Factory
concurrency/brief/attempt issues must be resolved before it joins the coordinator.

Rollback: stop the trial's process group/container, retain receipts and artifacts,
then run `report` using the pinned code after all workers have stopped. Do not
delete lock files or reset ledgers. With no schedule there is nothing to disable.
For a later separately approved timer, disable it before stopping the worker;
revert the runner code without rewriting prior stores. Production app rollback
is unnecessary for this isolated command; no service or production data changed.
