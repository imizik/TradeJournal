# Research Studio R3: connected workspace

R3 was selected by the user after R2 merged. R4 variants/conclusions, Factory
promotion, provider fetching, new datasets and VPS provisioning remain unselected.
The [roadmap](../strategy-workbench-roadmap.md), [R1](research-studio-r1.md) and
[R2](research-studio-r2.md) own observation and analysis semantics.

## App workflow

Open **Research Studio** in the owner navigation (`/research-studio`). Start with
one to three AND conditions or an approved historical decision bar. The initial
question is a negative 15-minute move in prior daily ATR14 units, elevated
cumulative RVOL and completed decision closes from 10:00–11:30 ET. Target one
core ticker or the core universe; SPY remains context. All dates stay discovery.
Editing shows population preparation and obtains an outcome-free preview with
coverage/exclusions, dates/weeks, concentration and available names. There is no
paid or live feed and no hidden provider fallback.

Run records a separate immutable submission provenance artifact (including the
client-declared outcome-informed flag) and explicitly freezes fresh source contents; it never assumes a warm preview
is still current. Snapshot corrections can therefore change the submitted data
identity. The run's eventual population is authoritative. A finite research
worker executes separately from import/sync. Polling exposes status only. Reveal
analysis explicitly records an aggregate exposure. Distribution, decision-feature
scatter and occurrence table share ticker/UTC decision-close IDs and one
inspector. Histogram bins inspect their first occurrence; scatter points and
rows inspect that exact occurrence. Selections do not filter statistics or N.
The default primary horizon is30m; all exact R2 horizons and both units remain
available. Missing values/intervals remain unavailable, with reasons.

The inspector separates known features from continuation. Static SVG candles
show complete five-minute buckets on the frozen Factory basis, with a decision
marker and bounded candle zoom/pan; no live chart store, indicator pipeline, stream, split provider or price
basis substitution is used. It intentionally has no live chart controls. A
candle click selects its completed close. Use decision features creates move
and RVOL predicates only; an outcome-axis selection cannot become a condition.
Every chart inspection is recorded before bytes return, including decision-only
history: moving a cutoff must not silently reset prior exposure. Explicit future
reveal returns only that discovery session's complete bars. Missing chart buckets
remain absent. Chart inspections are immutable research artifacts named by a
canonical operation UUID and containing the data identity, optional saved run,
ticker, decision and future-revealed flag. Reusing that UUID with another reveal
refuses. They do not increment the separate R2 aggregate-result exposure count.
Arbitrary human inspection outside Studio is not claimed perfectly measurable.

Editing any analytical input immediately labels a retained result previous.
A busy preparation retries only the current preview/chart with visible loading;
obsolete requests are aborted or ignored. Abort/generation guards prevent old previews, results and charts replacing a
newer draft/run/selection. Saved runs reopen their original snapshot/results;
reopening completed analysis records another exposure. If the feature engine
changes, original saved analysis remains readable but chart feature recalculation
refuses rather than relabeling current calculations as the original run. Cancel/retry preserve
logical identity and append-only attempt history. Pending jobs after restart
need explicit **Start queued worker**; interrupted attempts follow R2 recovery,
with explicit retry. No outcome reveal occurs merely from status polling.

## Manual local connection

Computation stays beside the approved SIP cache in a separate manually started
loopback process. The app API imports only a forwarding router, not the research
engine; numerical preparation never runs on the API event loop or sync worker.
The sidecar admits one preparation/chart/submission at a time, refuses excess
requests promptly, caches one warm observation population, releases its feature grid before
calculation startup to bound fork memory, and uses R2's finite
parent/child calculation lane. No autostart, service, daemon or timer is installed.
Only an operator chooses cache/store roots; HTTP commands cannot choose paths,
providers, hosts or protected dates.

Use one random private token of at least32 characters in both processes. Set
`TJ_RESEARCH_TOKEN` and `TJ_RESEARCH_PORT=8097` in the **backend's** environment
before starting the app. They are server settings, never `NEXT_PUBLIC_*`. In a
second terminal with the same token, from `backend`:

```bash
python scripts/research_studio_server.py \
  --cache-root /operator/approved/stocks/1Min/sip \
  --store-root /operator/research-studio --port 8097
```

Both directories must already exist and be owner-controlled; the store must be
separate from the source. Use an isolated scratch store for trying the UI.
The sidecar binds127.0.0.1 only and requires its bearer token for all routes;
it has no CORS/public gateway. The app forwards only to a configured integer
loopback port, ignores environment HTTP proxies, and never follows redirects.
Its two registered routes inherit owner-only authorization and authenticated
CSRF rules; assistant/service grants cannot reach them. The page also requires
owner access. Existing private-legacy access remains private. The token is not
returned to the browser. With no token/service, the app shows a connection error.

Stop with Ctrl-C after cancelling active work (or allow its finite work to
finish). Replacing/crashing the sidecar does not auto-replay queued work; the
inherited R2 kernel lock protects a still-live calculation child. Restart with
the same roots/token; inspect saved status, explicitly recover/start and retry.
Rollback stops the sidecar and removes the two backend settings; R2 immutable
results and inspection records remain. No production deployment is performed.

## Verification and evidence limits

Backend tests cover exact preview/chart identity, cutoff bars, durable reveal
and idempotency conflicts, timezone/date/symbol/data refusal before inspection
writes, original-snapshot reopen with source reads disabled, finite dispatch,
preparation admission, sidecar token checks and assistant denial before forwarding.
Browser fixtures use a new invented minute cache and the real sidecar, research
loader/engine/store/child, app forwarding, same-origin frontend proxy and rendered
page. They complete question-start/chart-start, inspect shared IDs, leave N
unchanged on selections, reopen exposures, reject late previews/invalid windows,
and cancel/retry without changing logical identity. Desktop/phone pictures are
manually inspected, not pixel assertions. Timings and final verification/review
receipts are recorded in the PR. Fixture proof is not production, provider,
real-phone usefulness or trading-edge acceptance. R4 retains human usefulness.
