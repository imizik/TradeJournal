# Prospective advisor forecast: preparation only

Owner selection: October 17, 2026. This reopens one bounded advisor research
preparation task. It does not change production Jo, Shadow, the scanner,
pre-trade checks or factory status. No inference API, CLI runtime, account login,
real forecast, new active schedule or connector grant is authorized by this
preparation. Only an additive **disabled** non-model VPS installation is selected.

## Frozen research rules

The machine-readable [spec](../../research/advisor-forecast/spec.json) and
[task prompt](../../research/advisor-forecast/prompt.txt) own the exact definitions.
The manifest records their bytes and all executable bundle sources. Preparation
is not evidence that hosted Jo can run this protocol reliably.

- Universe: MU, NBIS, NVDA, AAPL, QQQ, SPY, JPM. Seven symbols; 14 development
  cases and 140 evaluation cases across two then twenty consecutive sessions.
  Earnings days and sessions closing at or after 11:00 ET are included. The
  indices overlap the stocks; 140 cases are not 140 independent observations.
- Alpaca SIP raw one-minute bars, no fallback. Bars are start-labelled: the
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
- Direction baselines: always sideways, always up, always down, and the visible
  opening move. Compare their accuracy on exactly the answered subset, and also
  report all cases with available inputs/outcomes. Report confusion and per-class
  recall, not just aggregate accuracy.
- Historical range: nearest-rank Q20 downside and Q80 upside relative to each
  historical pre-cutoff reference. Jo's per-case width cannot exceed that
  baseline's width. Score whole-window low/high containment, width as a fraction
  of reference price, and terminal/low/high absolute errors in those same units.
- Answer at least 60%; beat the best baseline by 10 percentage points in
  direction and the historical range by 10 points in containment, with no
  greater average width. All gates and integrity must pass for replication only.
  A failure stops this version's directional development; no promotion or trades.
- Missing, invalid and late forecasts are not abstentions. Any affected ticker
  makes that session missing for the session-limit rule. More than three missing
  evaluation sessions invalidates the run: no extension or automatic restart.
  Missing outcomes invalidate the final judgment. All 140 cases remain in the
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

Prepare the task to permit only this study's read/save/recovery tools. Disable
web/browsing/other data tools at task scope if a supported control exists. Do
not change Jo-wide permissions, production tasks or plugin grants to pretend
the study is isolated. Official [Dots controls](https://learn.chatgpt.com/codex/dots/controls)
describe custom rules as instructions, not guaranteed enforcement; no per-task
technical web-disable control has been verified in this preparation.

Each session needs either complete platform tool-trace evidence or verified
task-scoped tool isolation, kept as an owner-controlled audit with its evidence
digest. Record `verified_no_external_access`, `external_access_detected`, or
`unverified`. Server logs see only this server; Jo self-report cannot establish
absence of browsing. Any detected or unverified external access prevents a
leakage-controlled pass; retain every case instead of removing contaminated
ones. Shared memory and information encountered in concurrent Jo work remain
limitations. Post-cutoff access is not confined to the web.

## What is built and what remains

The standalone collector/scorer and forecast exchange have no application
database imports. Forecast tools use a **separate OAuth audience and scopes**
(`/forecast/mcp`, `forecast:profile/read/write`), immutable subject/spec binding,
offline public-key verification, no data-provider credentials and no result
reveal. This adapter is prepared and fixture-tested; it is **not bound to an
existing connector or exposed on the VPS**. Existing practice credentials do
not silently receive new tools. Actual connection/identity and task-level
isolation must be reviewed before activation; no production connection is
repointed by this build.

The separate [installer](../../deploy/advisor_forecast_prepare.py) copies a
hashed bundle to `/opt/tj-forecast/v1`, creates dedicated non-login accounts and
isolated state, and installs three **disabled/inactive** timers: history at
09:45, snapshot at the two predeclared slots (only the selected one runs), and
outcome capture at 11:05. Timezone is America/New_York; missed boot-time runs
are not replayed. Outcome storage is unavailable to the forecast-serving user.
CPU is capped at 20%, memory at 128 MiB per job. The adapter source is staged
but no MCP service/socket, public route, issuer grant or Jo schedule is installed.

Installation refuses the wrong host, market hours, existing paths/accounts,
unsynchronized clock, low disk/memory and source digest mismatch. It never
touches the app release, DB, production units, credentials or scanner settings.
The only credential file is an empty private market-data placeholder. There is
no approval file, calendar registration or evaluation timing selection yet.

Before activation, confirm the dry run, verify the real scoped connector and
tool-access evidence, record actual Dots task settings, provision existing SIP
credentials, and register the exact future calendar from Alpaca. No inference
API purchase or CLI installation is part of that handoff. The disabled setup
does not establish live feed entitlement, OAuth acceptance, scheduler timing,
model provenance or forecast accuracy.

Rollback affects only `tj-forecast-*` units and `/opt/tj-forecast`,
`/etc/tj-forecast`, `/var/lib/tj-forecast*`: disable/stop these study units,
preserve all evidence, then remove only the introduced unit files if uninstalling.
Do not remove production services or data. No DB rollback is needed because
this installation has no DB connection or migrations.

## Verification

Use `backend/tests/test_advisor_forecast.py` and
`backend/tests/test_cloud_mcp_forecast.py` for hand-calculated scoring, shifted
windows, malformed/future bars, missing/late accounting, web-evidence refusal,
immutable timestamps/retries and OAuth audience/identity/scope refusal.
Run `scripts/advisor_forecast.py dry-run --output <fresh-private-directory>`
for an invented-data report. It runs zero provider/model calls. A synthetic
pass or failure checks the implementation, never Jo's skill. Tier-2 review and
applicable CI are required before calling the preparation merge-ready.
