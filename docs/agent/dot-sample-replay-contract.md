# Jo's own sample paper replay

Isaac selected this next increment on 2026-10-09: Jo may start and review a
bounded paper replay for its own assigned sample TAKE. The first cloud-browser
save/reload/reopen test was reported successful for MU/NBIS WAIT, and separately
corroborated through their deployed receipts. Those records and credentials are
retained. This replay uses a fresh exercise and separate `trader-jo-replay` login.

## Scope and clocks

A root-only preparation creates one MU/NBIS run under the distinct
`practice-sample-replay-long-15m-v1` schema. It freezes completed invented price
facts using actual capture timestamps, a fixed conditional long plan and a real
20-hour decision/start deadline. TAKE commits that conditional plan before its
future trigger; WAIT/SKIP remain valid and create no replay entry.

The continuation is a short, invented regular-session sequence, sealed before
any decision. It uses seconds from a simulated session open: arm at minute 15,
a completed 15-minute close at minute 30, detect two seconds later, then use the
first full eligible minute. Replay expiry is minute 60. This relative clock is
separate from real capture/receipt timestamps and the real start deadline. No
historical or future live market observation is claimed. Event `effective_at`
is mapped to the frozen capture anchor; UI event times are labelled replay
minutes. `recorded_at` is the actual server commit time.

The private continuation lives in `PracticeOpportunity.benchmark_json`; only its
salted SHA-256 commitment and rules are published in frozen context. A random
private nonce prevents guessing the stop/target variant from its commitment.
Preparation persists the sealed continuation before committing its context, so
recovery cannot replace a published commitment. Assistant views, including a
read-only inspector or partially prepared run, never reveal the private tape
before that actor starts its own committed TAKE.

## Permission and execution boundary

Enablement requires all existing four sample/auth flags plus the explicit
`TJ_SAMPLE_REPLAY_ENABLED=true`. The actual request must also originate in the
sample factory that validated the marked seeded SQLite installation; flags
alone on normal `app.main` do not admit replay requests. The separate login
requires `decision_write=true`, `sample_replay=true`, one assigned run, up to two
symbols and no journal access. All flags/capabilities default off.

Only `POST /practice/opportunities/{opp_id}/sample-replay` is added. Its body is
empty/strict: actor, decision, context, plan, tape, clock and retry identity are
server-owned. The service serializes against access revocation/grant changes,
rechecks the current session/principal/grants, resolves only its own TAKE, checks
schema, context/decision hashes, sealed commitment, fixed plan and freshness,
and rejects new starts past the real deadline. An identical completed retry
returns the original result after expiry; disabled/revoked permission still
refuses execution requests. Own committed results remain readable through the
existing sanitized run view.

The pure `paper_execution` reducer supplies next-minute fills, entry guard,
stop-first exits, fixed sample costs and 3x costs. Its normal P0 policy/universe,
raw-provider source guard, watcher and schedule are unchanged. The replay's
complete execution policy/hash declares its separate clock/expiry. It never
arms a P0 plan, contacts providers, starts a timer/model, sends notifications,
creates broker orders, or writes account fills/FIFO/trades.

Sample events use `sample_replay_` event types, `sample-replay:` keys, the
`sample_replay_fixture` source and `delivery=none`. The normal watcher selects
only `armed` events, so sample results consume no live P0 slots or outbox work.
P0 arming checks schema before existing-event retries, and its generic paper
view refuses sample schemas. The sample view owns its event timeline/result.

## Persistence and acceptance

All replay events and the base/stressed outcome snapshot commit in one bounded
transaction. An interruption leaves either no events or the complete replay;
retries cannot create another entry/exit. The view reads stored outcome snapshots
rather than recalculating history through a future reducer. The saved decision
and evidence never change. The receipt hash binds the committed event data.

Required checks: refusal of WAIT/SKIP, old sample/live records, other actors,
unassigned runs/symbols, forged fields, missing factory/flags/grants, bad CSRF,
expired starts, revoked sessions, changed plans and corrupt commitments; exact
numerical base/stress outcomes; simultaneous retries and pre-commit interruption;
preparation recovery preserving its nonce; real UI start/reload/reopen, phone
layout and delayed pre-start response; native namespace/key/receipt preservation
and a restart proving the outcome persists. Tier-2 native reviews and exact-head
CI are required. Jo reported saving/reopening WAIT for both symbols in the first
replay exercise; read-only deployed checks corroborated the hashes and no events.
The owner separately observed a TAKE replay over public HTTPS, including restart.
Jo subsequently reported MU TAKE and NBIS WAIT saved before revealing the v2
continuation, followed by MU replay/reload/reopen. Read-only deployed checks
corroborated the original choices, hashes and sealed commitment, one MU entry/exit,
no NBIS events, and MU base/3x net -$1.24192/-$1.32576 per share. This closes
Jo sample workflow acceptance; it is not a live market or independent human test.

This is a sample workflow exercise, not a blind human/agent comparison, live
forward cohort, automatic WAIT monitor or evidence of trading edge.

## Operations

Use the existing guarded updater with the exact reviewed source commit and
`--enable-sample-replay`. Its selected source archive now has eleven files;
Linux dependencies, credentials and data remain outside the archive. Rollback
restores the prior code/assets and all permission flags. Then run the guarded
seed command with `--replay`, which defaults to a new `trader-jo-replay` identity
and saves its key privately. Existing identities require explicit `--rotate`;
the selected path does not rotate old logins. Revoke the disposable proof login
after native acceptance. No production route or Tailscale change is selected.


## Distinct frozen scenarios (v2)

The user selected a fresh scenario exercise after Jo identified the first
packet's repeated bars. `sample-scenarios-v2` uses a new daily run key below the
same sample-only prefix. Original v1 runs, sealed continuations, decisions,
receipts and credentials remain unchanged. Repeated preparation returns the
same frozen v2 run; it does not refresh timestamps, deadlines or hashes.

Each symbol has 60 contiguous completed invented minute bars, newest first
in the frozen packet, with valid OHLC and positive volume. MU depicts a
pullback and recovery toward $110, with recent rising volume and price above
its window VWAP. Its frozen stop is the earlier $109 pivot, target the earlier
$113 high, and entry guard $110–$110.20. NBIS depicts a rebound followed by
choppy closes around $60 and declining volume; its earlier $58 pivot and $64
high supply the fixed stop/target, with guard $60–$60.50. Fact references name
those actual bars rather than assigning every extreme to the newest bar.
These are illustrative scenarios, not recommended choices or real market data.

VWAP is explicitly the cumulative volume-weighted OHLC typical price within
this invented 60-minute window, not an exchange VWAP. No historical daily/news
data or regular-session calendar evidence is added. The separate Charts page
still uses its other simulated window. The hidden replay clock, continuation
commitment, execution rules and permission boundary are unchanged; TAKE stays
conditional and both stop/target continuations remain possible. Scenario
version/id and the entire example plan are bound into the frozen evidence.

Use the guarded seed command with `--replay --scenarios`, which defaults to
the new `trader-jo-scenarios` identity. `--scenarios` without `--replay` refuses.
Do not rotate or repoint either prior Jo identity. Revoke only the separate
disposable scenario proof identity after acceptance. Replay and ordinary v1
preparation remain available without the new explicit option.


## Frozen evidence chart

The sample decision form and saved review show the exact context's completed
minute candles, supplied VWAP, volume and fixed trigger/stop/target. This
component receives only `DecisionContext`; it never uses the replay continuation
or requests Charts/provider/stream data. Context ID, cutoff and evidence hash
remain visible; displaying the hash does not claim automatic hash verification.

One-minute and 15-minute views use Eastern labels and actual timestamp spacing.
15-minute groups align to UTC clock quarters (also New York clock quarters),
with first open, maximum high, minimum low, last close and summed share volume.
A group is complete only with all 15 contiguous completed minutes. First/last
partial groups and missing minutes remain partial; they are not regular-session
trigger confirmation evidence. No calendar/session status is inferred. The
15-minute VWAP point is the last supplied value, not a recalculated interval
VWAP. Missing VWAP stays unavailable and is never bridged. Invalid, duplicate,
unaligned, unfinished or unsupported bars show an explicit unavailable chart;
the original packet and choice workflow remain accessible.

The page places this view beside the decision or original saved result on wide
screens and stacks it on phones. Reload and replay do not alter its evidence.
The separate Charts page continues using its other sample window. Numeric
aggregation/refusal and real browser save/replay/reload/phone checks are
required, together with native preservation of Jo's existing choices/receipt.
