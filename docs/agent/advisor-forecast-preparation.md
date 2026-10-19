# Prospective advisor forecast: development activation pending

Owner selection: October 17, 2026. The owner approved the synthetic dry run,
a new separate forecast-study connection with no production grants, and exactly
two live development sessions after connection verification. Subscription only;
no inference API or CLI fallback. Production Jo, Shadow, scanner, pre-trade
checks and factory remain unchanged. Evaluation activation is not authorized.

The owner replaced the task-scoped web/tool restriction on October 17 before
any real forecast. The v2 protocol uses deadline-time price baselines and reports
unrestricted browsing as a limitation. No v1 forecast or score was used to make
this revision. The isolated v2 connection was installed and its real subscription get_profile
verified. Collection remains disabled. Before any live forecast, the owner selected
existing Tradier access on October 18; v3 changes only the data adapter and its
provenance. No purchase, new brokerage login or inference API is involved.

## Frozen research rules

The machine-readable [spec](../../research/advisor-forecast/spec.json) and
[task prompt](../../research/advisor-forecast/prompt.txt) own the exact definitions.
The manifest records their bytes and all executable bundle sources. Preparation
is not evidence that hosted Jo can run this protocol reliably.

- Universe: MU, NBIS, NVDA, AAPL, QQQ, SPY, JPM. Seven symbols; 14 development
  cases and 140 evaluation cases across two then twenty consecutive sessions.
  Earnings days and sessions closing at or after 11:00 ET are included. The
  indices overlap the stocks; 140 cases are not 140 independent observations.
- Tradier production consolidated one-minute OHLCV from `/v1/markets/timesales`,
  `interval=1min`, `session_filter=open`, no fallback or client adjustment. Bars are start-labelled: the
  09:58 bar is the last one completed by 09:59. Snapshot collection starts at
  10:00, must finish by 10:00:30, and hashes the stored packet. No later bar can
  enter it. Historical inputs are fetched before 09:55 and saved with provenance.
- Primary window: 10:00 open to 10:59 close (11:00 endpoint); save by 10:02.
  A server save timestamp follows durable submission storage; caller timestamps
  are not accepted. This permits up to two elapsed outcome minutes at submission,
  so the result is not an executable signal at the window's start.
- Sideways includes ±25% of median absolute historical return over the matching
  window in the prior twenty eligible sessions. Missing minutes/history refuse
  the snapshot rather than interpolate or substitute an older session.
- Direction baselines: always sideways, always up, always down, and the
  opening move through the last minute completed by the submission deadline.
  Compare their accuracy on exactly the answered subset, and also
  report all cases with available inputs/outcomes. Report confusion and per-class
  recall, not just aggregate accuracy.
- Historical range: nearest-rank Q20 downside and Q80 upside of the entire
  forecast window relative to each historical deadline-minute close. Recenter
  on today's last minute completed by the submission deadline (10:01 close at
  the 10:02 deadline). The original snapshot-time historical width remains
  Jo's per-case cap; do not replace it with the later comparator width.
  Score whole-window low/high containment, width as a fraction
  of reference price, and terminal/low/high absolute errors in those same units.
- Answer at least 60%; beat the best baseline by 10 percentage points in
  direction and the historical range by 10 points in containment, with no
  greater average width. All gates and integrity must pass for replication only.
  A failure stops this version's directional development; no promotion or trades.
- Missing, invalid and late forecasts are not abstentions. Any affected ticker
  makes that session missing for the session-limit rule. More than three missing
  evaluation sessions invalidates the run: no extension or automatic restart.
  Missing outcomes or a missing deadline baseline for an existing snapshot
  invalidate the final judgment. All 140 cases remain in the
  participation denominator. No interim scoring or outcome inspection.

## Development timing choice

Both development sessions use 10:00/10:02. Inspect only operational timing.
If a complete platform record shows either task started after 10:00:30, select
the preregistered alternative **10:05 snapshot / 10:07 deadline / 11:00 end**.
The last visible minute then starts at 10:03; the forecast is 55 minutes and
all historical thresholds/range baselines use 10:05–11:00. Otherwise retain the
primary window. Missing start or delivery evidence blocks evaluation for review.
Write one immutable timing-selection record after development and before the
first evaluation day; never change it during evaluation. This is an operational
choice, not a choice based on forecast performance. It does not prove two
sessions establish long-run scheduler reliability. No extra development runs or
CLI fallback are automatic.

## Hosted Jo and external information

Use a separate hosted Dots task on the owner's ChatGPT subscription. No model
API client or key exists in the non-model runtime. The model is **not pinned**.
Record platform model metadata when available; otherwise say unavailable.
Record observed changes. Jo naming her own model is not platform evidence.

Report exactly: **web access not restricted; bounded by deadline**. The server
classifies any save after 10:02 (10:07 under the predeclared shift) as late,
never answered or abstained. Jo cannot supply/backdate the save timestamp.
An exact retry returns the original immutable receipt, including its status.
No web-disable or tool-trace gate remains. Do not use Jo's claims as evidence
of browsing absence, tool use or model identity; metadata is operator-imported
from the platform when available, and unavailable otherwise.

The deadline bounds save time, not information equality. Baselines receive
completed price bars through that deadline; they do not receive Jo's news,
web, memory or concurrent-task information. A pass is not a leakage-controlled
forecast or an executable signal at 10:00. The fixed directional baselines
remain fixed. Opening continuation and historical range use the independently
captured deadline price data, not Jo's reported inputs or later outcome data.

Capture deadline baselines once, starting at 10:02 and finishing by 10:02:30,
using only start-labelled bars 09:30–10:01. Under the shift, use 10:07–10:07:30
and bars 09:30–10:06. Hash and store immutable files separately, unavailable
through forecast tools. Historical whole-window extrema use the corresponding
historical deadline close; the target window, threshold and original forecast
width cap stay unchanged. Event-time filtering cannot guarantee an exact
historical as-of revision; report that limitation. A missing comparator is an
integrity failure, never replaced with the earlier baseline or an outcome.

## What is built and what remains

The standalone collector/scorer and forecast exchange have no application
database imports. Forecast tools use a **separate OAuth audience and scopes**
(`/forecast/mcp`, `forecast:profile/read/write`), immutable subject/spec binding,
offline public-key verification, no data-provider credentials and no result
reveal. The separate adapter is installed on the VPS and its actual scoped
subscription connector profile has been verified. Existing practice credentials do
not silently receive new tools. Actual connection/identity and deadline
enforcement must be reviewed before activation; no production connection is
repointed by this build.

The separate [installer](../../deploy/advisor_forecast_prepare.py) copies a
hashed v2 bundle to `/opt/tj-forecast/v2`, creates dedicated non-login accounts and
isolated state, and installs four **disabled/inactive** timers: history at
09:45, snapshot at the two predeclared slots (only the selected one runs),
deadline baseline at 10:02/10:07, and outcome capture at 11:05. Timezone is
America/New_York; missed boot-time runs are not replayed. Outcome and
deadline-baseline storage are unavailable to the forecast-serving user.
CPU is capped at 20%, memory at 128 MiB per job. The separate MCP socket, public route and public-key timer are installed.
Production grants remain excluded. Hosted Jo scheduling is a separate activation gate.

Installation refuses the wrong host, market hours, existing paths/accounts,
unsynchronized clock, low disk/memory and source digest mismatch. It never
touches the app release, DB, production units, credentials or scanner settings.
The only credential file is an empty private market-data placeholder. There is
no approval file, calendar registration or evaluation timing selection yet.
This fresh installer deliberately refuses the existing v1 installation.
The separate [upgrade](../../deploy/advisor_forecast_upgrade.py) recognizes only
the exact disabled v1 manifest and six unit hashes. It preserves v1 sources,
receipts and original units, copies v2 beside it, and installs the deadline
collector plus disabled MCP socket/service and public-key refresh timer. It
refuses existing activation records, unexpected paths, units or identities.
Never remove v1 evidence or bypass its collision checks to run the fresh installer.

The upgrade uses a separate venv from an explicitly fingerprinted offline
wheelhouse in an existing reviewed Ubuntu release. It installs only MCP/JWT/HTTP
dependencies, not the application package or inference SDKs. The serving unit
has no IP network, credentials or production mounts: it can read only its code,
binding, public keys and frozen snapshots, and write only its receipt directory.
An independent non-login identity publishes public verification keys every fifteen
minutes; expired keys deny access. The installer leaves both units inactive; the approved connection activation
subsequently enabled only the socket and public-key timer.
No proxy, credential, approval, registration, binding or hosted task is created
by the upgrade. On unit-validation failure it restores only the old study units;
partial new files are retained for inspection, never automatically adopted.

Activation still requires fresh installed-identity read/write/network refusal
proof, frozen source hashes, current public keys, and a binding restricted to the
separate client/subject and exact two development dates. Install only the rendered
forecast hostname stanza, validate the complete Caddy configuration, and reload
using its existing supported mechanism while preserving all other routes. Compare
production unit hashes and long-running PIDs before/after; distinguish independent
production deployments from study changes. Verify public metadata, unauthenticated
401, unknown-route 404, and real subscription connector profile access before
enabling the four development collection timers. No evaluation approval or timing
selection is written at this stage. Keep the task schedule and platform settings
in the private activation record, separate from Jo's self-reported metadata.

Before activation, verify the real scoped connector and server deadline, record
actual Dots task settings, provision only the existing Tradier token into the private study credential file, and register the
exact future calendar from Alpaca. Development-only approval blocks evaluation
collection, and the MCP binding permits only the two named development dates.
The base spec is bound by hash; the adapter derives the same zero-offset
effective spec as the collector. Later evaluation requires separate activation. No inference
API purchase or CLI installation is part of that handoff. The disabled setup
does not establish live feed entitlement, OAuth acceptance, scheduler timing,
model provenance or forecast accuracy.

Rollback affects only `tj-forecast-*` units and `/opt/tj-forecast`,
`/etc/tj-forecast`, `/var/lib/tj-forecast*`: disable/stop these study units,
preserve all evidence, then remove only the introduced unit files if uninstalling.
Do not remove production services or data. No DB rollback is needed because
this installation has no DB connection or migrations.

## Tradier revision before the first development session

All historical scale/range inputs, 10:00 snapshots, 10:02 deadline baselines and
11:05 outcome captures use the same Tradier production endpoint. Alpaca supplies
only the already-defined market calendar. Tradier `time` labels are interpreted
in America/New_York, including DST; explicit offsets are converted. Returned
OHLCV is used as reported, without a claim of historical revision or adjustment
control. No alternative provider or filled-in minute is accepted.

A read-only access check found every required minute in all seven tickers across
the prior twenty sessions (September 21–October 16): 140 complete windows. This
is history coverage, not evidence of publication latency at 10:00 or 10:02.
The two development sessions must establish operational timing; no forecast
performance is inspected. Tradier and hosted Jo latency may still block the study.

History uses seven date-range requests, filters to the exact registered prior
sessions and 09:30–10:59 window, and fails on any missing minute. Each current
capture uses seven requests with at most four in flight and a ten-second socket
timeout. That is 28 requests per session, sharing the existing account budget;
429, transport errors and malformed responses fail without retries. The unchanged
30-second capture deadline is enforced after all responses arrive. The serving
process cannot access the token, and no orders/account endpoint is called.

`advisor_forecast_upgrade.py --revise-v2-provider` recognizes only the exact
reviewed unstarted v2 bundle and unit contents, refuses collection activation or
real study evidence, and preserves old source and binding in `before-tradier`.
It briefly stops only the isolated MCP/key units, atomically replaces checked
bundle files and the spec hash in the same binding, and restores the connection.
Failure during replacement restores the old bundle/binding. Data timers remain
disabled; credential provisioning, future-date registration and hosted task
creation are separate activation steps. All performance/missing-data gates stay
unchanged. No evaluation approval is created.

## Verification

Use `backend/tests/test_advisor_forecast.py` and
`backend/tests/test_cloud_mcp_forecast.py` for hand-calculated scoring, shifted
windows, malformed/future bars, missing/late accounting, deadline-baseline integrity,
immutable timestamps/retries and OAuth audience/identity/scope refusal.
Run `scripts/advisor_forecast.py dry-run --output <fresh-private-directory>`
for an invented-data report. It runs zero provider/model calls. A synthetic
pass or failure checks the implementation, never Jo's skill. Tier-2 review and
applicable CI are required before calling the preparation merge-ready.
