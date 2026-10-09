# Trader Jo's first saved sample decision

Selected 2026-10-09 after Isaac reported Trader Jo's successful cloud-browser
sign-in and navigation of the VPS sample app. This is the next browser chunk:
inspect frozen MU/NBIS evidence, save a simulated TAKE/WAIT/SKIP, reload Daily
Review, and reopen the identical record. The Dot's original trial showed chart
loading/study problems, a symbol/URL mismatch and undiscoverable practice dates.
Physical laptop-off observation was not separately reported.

## Scope and permissions

Keep the original `trader-jo` inspector. Create a separate
`trader-jo-decisions` principal with exactly one selected sample run, at most two
market symbols, `decision_write=true` and `journal_read=false`. Its credentials
are entered through the private website sign-in flow and remain revocable.
Enablement requires all four flags: `TJ_ACCESS_ENABLED`,
`TJ_ACCESS_SAMPLE_DATA`, `TJ_DOT_TRIAL_ENABLED` and
`TJ_SAMPLE_DECISION_WRITES`. The final flag is absent/false by default.

The writer may use the selected market reads, list/read the assigned sample run
and its own immutable records, and submit only
`POST /practice/opportunities/{opp_id}/agent-choice`. It cannot create contexts,
prepare runs, read journal/accounts/human or other agents' choices, change
reveal state, edit records, arm plans, start jobs/models, or modify alerts.
Owner journal mutations remain blocked in the sample runtime. Authentication
management remains available through the private owner entrance.

The server derives actor, symbol, context, opportunity and retry key. One
principal has at most one immutable choice per opportunity. Same-content retries
return the original receipt; changed-content retries conflict. New choices
after the exercise deadline are refused; old records and identical retries
remain available. WAIT cannot extend beyond that deadline. Symbol/run/record
ownership, CSRF, feature disablement, expiry, rate budget and key revocation are
application boundaries. UI visibility and prompts do not establish permission.

## Evidence and policy

Preparation is a root-only operation on the existing guarded SQLite sample
installation. A separate sample run contains MU and NBIS, sixty invented
completed minute bars per symbol, derived timestamped USD/share facts, a bounded
scenario, a fixed sample plan example and an exercise deadline. No human or agent
choice is prefilled. Saved contexts and evidence hashes are immutable; preparing
again does not silently refresh a committed packet. Expired evidence needs an
explicitly prepared later sample run and credential rotation to its grant.

The `practice-sample-long-15m-v1` policy and hash differ from the normal A1 schema.
Its source is `sample_fixture` and price basis `simulated_raw`. The live TAKE
validator continues to require raw Alpaca facts; sample admission is an explicit
internal argument used only by the guarded sample choice service. All simulated
choices stay `practice_draft_unarmed`, with visible SIMULATED labels. A2 rejects
their different schema even through an owner/direct service path. This chunk
does not change the P0 universe, live strategy rules, costs or paper watcher.
MU/NBIS paper eligibility belongs to the separately selected next chunk.

Charts use a separate limited synthetic history window. Their responses include
all required nullable study fields and calculate EMA/RSI using the normal math.
VWAP and the 200-bar EMA remain explicitly unavailable. No live stream is
requested for a sample workspace. Plain chart links initialize the symbol and
subsequent selection updates the URL while preserving Next history state.
Practice-only sessions appear in the Daily Review calendar; the practice board
precedes journal AI review in the dated page.

This personal Dot has already inspected sample journal material. The exercise is
labelled independence-unverified; this permission increment does not establish
blind Shadow Isaac. An independent runner still needs a restricted fresh payload
and both choices committed before reveal.

## Acceptance

- A real authenticated browser saves simulated TAKE/WAIT/SKIP through the actual
  UI, reloads and retrieves original IDs, cutoffs and hashes. Phone layout has no
  horizontal overflow. Exact API reads confirm the receipt, not just chat text.
  A delayed pre-save reload or another choice response cannot hide an accepted
  immutable receipt.
- Refuse forged actor/context/symbol/key, other actors' records, unassigned runs
  and symbols, journal/account access, direct generic writes and paper arming.
  Sample records cannot pass the live source validator or A2 schema guard.
- Chart selection and URL agree after navigation/reload; enabling EMA/RSI does
  not throw; missing history is explained. Practice-only dates and evidence are
  reachable through the calendar.
- Root-only runtime updates validate narrowly scoped archives, retain Linux
  dependencies, preserve trial data and credentials, and restore prior code,
  assets and permission flag when startup fails. Production services/config,
  private API and network routes are unaffected.
- Required local checks, native tier-2 reviews and current-head CI complete
  before PR readiness. Actual Dot write/reopen acceptance remains a subsequent
  user-observed step; no paid model, timer, live provider or paper outcome follows
  from these fixture checks.

## Operations

The [updater](../../deploy/dot_trial_update.py) accepts only the nine selected
backend/control source files and portable compiled frontend files. Keep the
verified Linux `node_modules`; never include data, OAuth files or environment
secrets in either archive. The updater records the exact source commit and
archive hashes, preserves root-private recovery files and checks that restarted
trial services share a namespace distinct from the host.

The [sample preparation command](../../deploy/dot_trial_seed.py) runs with the
trial's exact marked SQLite environment and source-provenance check. It creates
today's sample run and writes a mode-0600 private credential file under
`/etc/tradejournal-dot-trial`. An existing identity/key requires explicit
`--rotate`; a credential-save failure disables the identity. All trial
assistants, including writers, are revoked by the existing shutdown control.
