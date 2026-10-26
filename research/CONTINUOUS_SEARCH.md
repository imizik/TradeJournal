# Mac continuous setup search

Runs only in `/Users/user/TradeJournal-factory`, branch `factory/ledger`.
This branch is never merged and no unproven strategy PR is created.

The schedule/activation statements below record October 15–16, not a current
service-health check or authorization to resume. This October 25 PR performs
preparation and synthetic tests only; no evaluation or attempt is authorized.

`backend/scripts/factory_search.py --tick` runs at most one new candidate.
launchd calls it every five minutes with `--force`, enabled by Isaac on
October 15 to continue searching during the day as well as at night. Isaac
increased the budget on October 16 to 288 candidates / 24 compute hours so
the search can continue throughout the day. Its existing window rolls
over at 22:00 New York. Already consumed attempts and time are retained.
A tick acquires the same exclusive writer lock, so evaluations do not overlap.
Without `--force`, new work remains restricted to 22:00–06:00 New York.
Daily summary files/ntfy receipts are snapshots; tomorrow's verifier must
compare them against the latest ledger while continuous work is active.
The Mac must be awake. SIP cache only; no VPS computation or database access.

Per-window limits: 288 reserved candidates, 24 hours of reserved process time,
one Claude-plan call capped at $2 / 300 seconds, each evaluation at most
15 minutes. Completed evaluation time is charged; a supervisor interruption
consumes the entire reserved timeout. Process-time bounds are conservative,
not a promise that 288 candidates finish. Failed Claude calls use random
proposals and appear in logs. No API-key fallback. `--force` permits one
acceptance tick outside the nightly window and uses the same budgets.

Every candidate is durably reserved in `research/ledger.jsonl` BEFORE
its worker starts. All distinct IDs, including historical screen failures and
interrupted reservations, count toward Bonferroni. Reservations never retry.
An atomic finished result is imported after a supervisor restart; otherwise
the reservation is marked interrupted. The worker inherits the supervisor's
flock so a second launch cannot overlap an orphan worker. The weekly wrapper's
`week.lock` excludes weekly writes. Direct manual CLI writers must not run
concurrently. The ledger checkout's CLI also recognizes reserved IDs.

The existing April 2026 onward exam holdout is retained (it includes the most
recent four weeks). Discovery/confirmation periods are unchanged. Later
periods are loaded only by the existing gates; all candidates face the same
random-entry baseline and cost-stress checks. Claude sees only a whitelisted
spec + discovery/confirm ledger digest, no notes, exam outcome or holdout
numbers. Its tools are disabled and it has no session persistence. Random
proposals cover every factory family, the two S1 setup types, day/week filters,
past levels and exits. The model does not edit code, costs or the universe.

`s1_research` reuses scanner_rules' pure signal functions on SIP minute bars,
including scanner ATR/VWAP/EMA computation; it is an underlying-signal research
proxy with factory exits and costs. It does not model option premiums/spreads,
scanner cooldown/admission or Jo decisions. A passing exam produces only an
`s1-v3-proposal-<id>.json` evidence file, requiring forward paper evaluation and
Isaac approval. It changes no live S1 settings, exchange, task or pre-trade check.

Jobs/results/briefs and budget receipts: `backend/data/factory/search/`.
Daily summary: `research/reports/<night>-continuous.json`, plus ntfy using
`FACTORY_ALERTS_ENV` (default `~/.config/tradejournal/alerts.env`), falling back
to the existing `FACTORY_NTFY_URL` / token in the linked backend environment.
Never print these settings. Commits/pushes retain research evidence on the
ledger branch. Logs: `~/Library/Logs/tradejournal-factory-search.log`.

Pause: `launchctl bootout gui/$(id -u)/com.tradejournal.factory-search`.
Resume: `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.tradejournal.factory-search.plist`.
The actual unattended-night and real restart receipts must be recorded after
observation; installation, fixture tests and a daytime run do not satisfy them.


October 15 proposal intake repair: the first 16 completed trials were all random.
Claude had produced four proposals, but canonical ledger-style `low`/`high`
filter bounds were rejected by the CLI-style `min`/`max` parser. The search now
translates those equivalent spellings (and `note` to `notes`) before strict
validation, rejecting conflicting bounds. No numeric bound, gate, cost or
budget is changed. The original answer is retained. Three saved proposals
now validate; the fourth remains refused for an invalid window and is not
silently altered. Claude validation refusals are logged to the main log and
`backend/data/factory/search/<window>-proposal-rejections.jsonl`. Rejected
proposals are not evaluated candidates and are not ledger trials.

Claude feedback now includes origin and recorded discovery screen failures in
the whitelisted ledger digest. Each next scheduled call must explain which
failure its hypothesis addresses. A preview and three-candidate feedback
receipt were prepared October 15 without making an extra model call.
The one-call-per-window limit, candidate/time caps and every gate are unchanged.

The separately authorized opportunity-feed pilot is documented in
`research/OPPORTUNITY_FEED.md`. Its two discovery-only builds reused already
counted IDs and consumed 32 + 63 seconds from the existing time budget. They
added no factory candidates, changed no gates and made no model calls. The
v2 pilot has 90 outcome-blind cards awaiting real Jo choices; it is not a
passed strategy and is not connected to the live scanner or Jo task.

October 16 Codex preference: the search prefers the signed-in ChatGPT Codex
plan for ideas. Isaac explicitly approved sanitized candidate specs and
discovery/confirmation feedback on October 16. Codex receives the same
whitelisted digest as Claude, excluding free-text names/notes, holdout/exam
evidence, real trades and credentials. Duplicate checking stays local.

Request up to four ideas per batch, with another batch only when no valid
untried Codex idea remains. At most 72 batches per 22:00 ET budget window;
each conservatively reserves 330 seconds before launch. Candidate cap 288 and
process-time cap 86400 seconds apply from the October 16 budget increase. Started batches are never retried.
The CLI forces ChatGPT login with no API fallback and uses the configured user
model. It runs in an empty temporary directory, read-only, with shell, web,
MCP, plugins, hooks and memories disabled. `agents.enabled=false` and
`multi_agent_v2=false` remove delegation tools. The installed CLI still
advertises an execution wrapper; its disabled host was verified to refuse
execution in a synthetic local test, without creating the requested test file. Keep schema/answer,
usage/events and generation receipts under the private search directory.
Existing single-call Claude fallback and random sampling remain available.
No gate, holdout, Bonferroni count, scanner setting or production task changes.

Unattended-night acceptance October 16: 20 candidates completed in the October
15 22:00–October 16 06:00 ET window, four after midnight. None passed the screen.
The accepted ntfy receipt at 09:52 ET is a 20-candidate snapshot; the next result
at 10:56 ET raised the active-window count to 21. The Mac slept on battery,
so wall-clock gaps do not represent uninterrupted awake execution. It was on
AC at audit. Existing restart-receipt.json proves unchanged distinct trial
count after the actual supervisor restart; the complete ledger has no duplicate
reservations, and every stored prior-candidate K matches all distinct earlier IDs.

October 16 runtime proof: inspect both top-level tools and input.additional_tools;
checking only the former misses advertised tools in the bundled CLI. Local
request capture with synthetic credentials shows delegation removed with the
explicit agents.enabled setting. A simulated functions.exec call returns
"code-mode host is disabled". The model process uses the separate guardian
so a lost parent cannot leave a running model or inherited writer lock beyond
its reservation. Both bare-array and {"specs": [...]} proposal envelopes are
accepted; their underlying specs still face unchanged strict validation.
The first native batch used the signed-in ChatGPT plan, generated four specs,
and made no tool calls; its initial envelope rejection consumed the full 330
seconds. Two strictly valid unseen specs were recovered locally without a new
model call or trial reservation; the two invalid specs remain refused.

October 16 budget increase: Isaac requested continued work immediately instead
of waiting for the 22:00 rollover. Caps increased from 24 to 288 candidates,
7200 to 86400 reserved seconds, and six to 72 Codex batches per window. All
already consumed candidate IDs, batch markers and seconds are retained. The
five-minute launchd cadence, single-writer exclusion, per-process deadlines,
ChatGPT-plan Codex preference, sanitized feedback and every statistical gate
are unchanged. The increased caps apply to the active and future windows.

## Frozen single-candidate intake (preparation, October 25)

The optional manual intake accepts only the canonical default
`opening_range_breakout` with `rvol >= 2.0`, ID `op-998d19a73d`, in
`research/specs/opening_range_breakout_rvol2_v1.json`. It does not change its
rules, core universe, costs, acceptance gates, protected dates or attempt budget.
This is infrastructure on the research branch, not an unproven strategy release
or a reason to merge `factory/ledger` into application `main`.

**No evaluation is authorized by this change, its merge, or an inspection.**
The authoritative Mac checkout is not updated or restarted by this PR. Before
adopting the code there, verify the search remains paused. Do not resume launchd,
run an acceptance tick, or spend a new attempt as part of code preparation.
The loader fix is included here because the old BarStore physically read later
source files before trimming the returned Series. Bounded requests now filter
source dates before reads and isolate both memory and disk caches by cutoff;
the research branch's scanner `MINUTE_LOADER` hook is preserved.

Once the reviewed code has been adopted in the authoritative checkout, this is
the read-only inspection command (run from that checkout):

```bash
backend/.venv/bin/python backend/scripts/factory_search.py \
  --inspect-spec research/specs/opening_range_breakout_rvol2_v1.json
```

It returns only candidate identity, whether that identity is already counted,
all-distinct-ID count, prospective next attempt number, ledger SHA-256, current
window/caps/time budget, search-hours status and whether a weekly lock exists.
The next attempt is null for an already-counted candidate. No outcomes, free-text
ledger notes or protected-period metrics are exposed. Inspection creates no
locks/directories, recovers no jobs, calls no model/provider/worker, publishes no
message, reserves no time/attempt and writes no ledger. It is a momentary snapshot,
not a lock acquisition or an eligibility/approval guarantee. A missing ledger,
malformed budget or absent budget for a window with recorded activity is refused.

A **separately owner-approved** future evaluation must use the same supervisor:
`--tick --spec <frozen-spec-path> --authorize-spec op-998d19a73d
--expect-ledger-sha256 <fresh-inspection-digest>`. These flags make the intent
explicit; they are not an external approval system and cannot grant owner
permission. The ordinary search-hours guard still applies; existing `--force`
can bypass only that clock guard, with all budgets and locks retained.

The requested path acquires the existing writer flock and weekly exclusion,
rechecks the inspected ledger digest, duplicate identity, current caps and
remaining time, then uses the existing reservation/job/worker/completion path.
It does not call Codex, Claude or random proposal fallback, and does not send
unrelated nightly notifications. Existing result recovery and proposal evidence
handling remain in the official workflow. Scheduled `--tick` behavior is retained.
Renames, retries of reserved/interrupted/failed IDs, variants, stale receipts,
busy locks and insufficient budgets cannot substitute another candidate.
Refusals before recovery/reservation do not invoke git persistence or alter the
ledger/time budget. Existing interrupted reservations still count. A launch or
evaluation failure does not make the candidate retryable.

One authorized requested tick can start at most one worker, with the same maximum
900-second timeout, inherited writer lock, durable ledger reservation before
launch and all-prior-distinct-ID multiplicity count. The worker and statistical
gates are unchanged: it cannot reach confirmation or the exam by a new path.
Do not use the standalone application CLI, a scratch backtest or the replay demo
to bypass this counted evaluation.

Preparation evidence: the authoritative checkout was clean at
`a285a8340525e0c37421f80b9642baabf0bf0d41`; its ledger still contained 82 distinct
IDs, with no `op-998d19a73d`, and SHA-256
`0e1a959e540a25597b38a55dca8f453641aa2359fd312397a69b2ccb7fb3e47e`.
This is a dated metadata observation, not a reusable approval receipt or proof
that attempt 83 will remain available. No real data evaluation was performed.

`backend/tests/test_factory_intake.py` runs the real supervisor with invented
ledgers, temporary budget/job files and fake workers. It checks read-only
inspection, exact-spec admission, duplicate/refusal states, stale digests,
missing history/budget, time and attempt caps, both locks, reservation-before-
launch, all-attempt counting, failure/restart behavior and unchanged scheduled
selection. It forbids real model, provider, evaluation, notification and git
operations. `test_strategy_factory.py` covers physical stage isolation and the
frozen spec identity with synthetic bars. The S1 research family is registered
by the research CLI, not the shared engine, preserving Studio's frozen runtime
dependency set. Test imports restore CLI environment changes and never load
the real backend environment file. These fixtures do not establish live
adoption, process recovery under every host failure, strategy performance or
paper/live execution readiness.

## Fixed ETF exploratory intake (preparation, October 26)

After the input reconciliation in PR #523, the owner approved the smallest
counted integration. **This implementation and its merge authorize no historical
screen, attempt, checkout adoption, schedule change or live execution.** Only
invented inputs were used for preparation tests. Both schedules stay paused.

`backend/scripts/factory_etf.py` pins the [ETF/BIL proposal](notes/etf-bil-exploratory-screen-proposal-2026-10-26.md)
as canonical case `etf-c4c308ecc58fc194`. It admits only the reviewed input
manifest `d2f07d938cc66ee7d8fb1fbc155a82823dd5a9574e3fb0e3bd5ecae66c736c43`:
SPY/EFA/EEM/IEF/BIL, January 2016–September 2024, 2,200 complete common sessions.
It has no CLI or alternate candidate/period/cost/input-pin switches. The saved
snapshot's revised-history assumptions and unknown original publication times
remain explicit; this is exploratory evidence, never a Factory gate pass.

Once reviewed code adoption in the authoritative checkout is separately
approved, the read-only inspection is:

```bash
backend/.venv/bin/python backend/scripts/factory_search.py \
  --inspect-etf-bundle /Users/user/Documents/TradeJournalResearch/etf-bil-inputs-2026-10-26-v1
```

Inspection hashes archived bytes and returns only the fixed candidate/input/code
identities, existing ledger digest/count, duplicate status, budget and lock
metadata. It does not parse prices into calculation inputs, compute returns,
recover jobs, reserve an attempt or publish anything. There is no provider call.
The four-file code fingerprint covers the supervisor, ETF adapter, shared CLI
and portfolio calculator. It supplements the recorded Git commit.

An explicitly owner-approved run uses `--tick --etf-bundle <same-bundle>` with
`--authorize-spec etf-c4c308ecc58fc194`, `--expect-ledger-sha256 <fresh-receipt>`
and `--expect-code-sha256 <fresh-receipt>`. Flags acknowledge a separate approval;
they do not grant it. The existing `--force` bypasses only the time-of-day guard.
The scheduled search cannot select this case, and ORB intake stays unchanged.

This manual path uses the existing writer flock, weekly exclusion, time budget,
candidate cap, fsynced ledger reservation and at-most-900-second child. All prior
distinct IDs count, including failed/interrupted attempts. The ETF ID excludes
bundle paths, labels, code and source versions. Any prior record of this fixed
case/family blocks it, including renamed IDs; unstructured historical notes
still require the owner's duplicate/equivalence review before authorization.
There is no model proposal or fallback case. Missing/changed inputs, stale
receipts, busy locks and exhausted budgets refuse before reservation.

The ETF child rechecks its exact live reservation, inherited writer descriptor,
owning supervisor, code/input hashes and one-start marker before loading sessions.
It validates the pinned calendar and explicit action vectors, then calls only
the existing pure portfolio calculator. No minute-bar store, provider, random
baseline, confirmation/exam evaluator or broker is called. A changed input after
reservation consumes the attempt as a failure. Existing failure/time accounting
is retained; an interrupted supervisor retains the full reserved timeout.

Output is `research/reports/etf-c4c308ecc58fc194-exploratory.json`, retained by the
existing research persistence path. It includes both fixed cost cases, all three
NAV paths, aligned monthly returns, CAGR, drawdown, traded notional, fees, BIL
weights and the fixed continuation criterion. The ledger records its hash and
summary with verdict `exploratory_only`, `reached_confirmation=false`, and no
gate/period fields. A favorable continuation criterion does not mean validation.
These records still increase the global attempted-ID count but are excluded
from scheduled model feedback and live-proposal generation.

Normal completion and restart recovery validate the same reservation/artifact
binding. Missing results become interrupted; malformed/mismatched results become
failed. Neither starts another ETF child. A direct worker call without its
supervisor and counted reservation is refused. No result or signal from actual
market inputs has been computed during this preparation.

`backend/tests/test_factory_etf.py` exercises the real supervisor/child logic
with invented input pins, temporary ledgers and fake process transport, plus one
native child-process check of inherited locking and supervisor identity. It covers
admission, stale hashes, protected-date refusal, budget/lock exclusion, durable
reservation, failure charges, duplicate/retry refusal, one-start behavior,
completion corruption and restart recovery. Existing ORB/scheduled-search tests
remain intact. These are software checks, not live process-adoption proof.

Next: review/merge the integration, approve clean checkout adoption and obtain a
fresh inspection, then separately authorize one bounded screen. The first
economic result must precede further execution/options infrastructure. No new
variants, statistical gates or protected-period access are introduced here.
