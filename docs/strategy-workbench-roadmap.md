# Strategy Workbench: Research Studio roadmap

**Status: R0/R1 complete; R2 reproducible analysis implemented; verification/review gates recorded in its PR.**
R3 selected: connected workspace implementation and acceptance are recorded in the [R3 contract](agent/research-studio-r3.md). R4 remains unselected. The [R2 contract](agent/research-studio-r2.md) records current work; the [R1 contract](agent/research-studio-r1.md) records
implementation and acceptance; R3 connects the owner app workspace; R2 provides outcomes and a manual local lifecycle; its contract records acceptance limits. The existing filename is retained so links remain stable.
The product-aware review at `4c42018` supersedes the strategy-form-first
proposal of 2026-10-07 as recorded below. Implementation requires selection
of one bounded phase; this update authorizes no data purchase, protocol
migration, deployment or Factory run.

## Product direction

One visual market research studio, with three connected ways to explore the
**same experiment**:

- **Chart:** notice something, select a completed decision bar, inspect occurrences.
- **Experiment:** describe observable conditions and adjust variables.
- **Analysis:** explore distributions, relationships, outliers and variants,
  with observations linked back to their historical charts.

The promise is to investigate a useful, expanding range of market questions
without asking a coding agent to write each analysis. An event study does not
require entries, stops, exits, sizing or a full strategy. Ordinary use needs
no AI. A chart, a question or a saved result can be the starting point; there
is no mandatory chart-first sequence and no separate experiment per view.

The first release is an event lab. Strategy simulation is a later handoff to
the [Factory](strategy-factory.md), whose validation remains authoritative
for strategies. Richer composition, formulas, pattern research, ML, suitable
order-book datasets and contextual AI are possible extensions, not promises
or first-release requirements. The Studio does not establish profitability.

## Sequencing and ownership

The user selected **R0, then R1** on 2026-10-10 ahead of further S1–S2 work.
[R0 evidence](agent/research-studio-r0.md) and the
[R1 contract](agent/research-studio-r1.md) record the results.
S1–S2 otherwise retain their priority; this does not select R2 or change another
board's active item. That order is a product
priority, **not a technical dependency**: an independent event lab needs
neither a swing family nor the practice loop. If repeated one-off research
questions justify earlier Studio work, explicitly select R0 and record the
priority change before starting it.

The old Workbench W0 is not a prerequisite for S1–S2 or the event lab. Its
store extraction may be useful, but its strategy catalog/normalize/explore
package is superseded. R0 must measure what is needed before choosing a
minimal extraction. The [product roadmap](product-roadmap.md) continues to
own the journal learning loop; [Charts](charts-roadmap.md) owns live chart
replacement. Studio neither extends Pine Strategy Lab nor replaces those plans.

## Superseded decisions

This table records changes in meaning, rather than leaving contradictory
requirements elsewhere in this document. W0–W10 refer to the retired
2026-10-07 plan and must not be used as implementation assignments. Its full
text remains in Git history at `4c42018`.

| Previous decision | Replacement and reason |
|---|---|
| Every experiment is a Factory spec; one spec, one ID | Independent, versioned event definitions and IDs. A strategy spec is a later output requiring execution rules. Existing strategy IDs remain unchanged. |
| Every number comes from `run_candidate`, `_Stage`, `summarize` or `discovery_forward` | Share authoritative feature calculations and suitable statistical primitives. Use a small stop-free event-analysis path; these existing functions assume executed trades, stops or R. |
| W0–W3 deliver a family form, breakdowns, trades and candidate freeze | R0–R4 below deliver evidence, event analysis, one connected workspace, variants and acceptance. Factory promotion is later. |
| Two filters; proposed review's three conditions as a hard product boundary | Up to three AND predicates in the V1 UI is a simplification, not a permanent language limit or statistical guarantee. |
| Mac-only, separate destination as necessities | Compute beside an approved cache. A separate route is the V1 recommendation; browser location and navigation are not dictated by host placement. |
| A slider never runs anything | Editing may query outcome-free population counts. Outcome analysis is explicit and logged; previews do not prove freedom from overfitting. |
| A frozen event can be sent straight to Factory validation | V1 saves an event hypothesis. A later adapter must supply and validate stops, exits and execution semantics before a Factory command is offered. |
| Discovery look counts provide a numerical “luck line” | Keep exposure/accounting records, but do not present a look counter as a calibrated correction for adaptive selection. |
| New features excluded from V1 | One narrowly defined 15-minute move feature is needed to distinguish a sharp decline from a slow day move. Preserve existing feature behavior. |
| Permanent dataset-toggle exclusion and a larger scheduled W4–W10 queue | Protected data never becomes a runtime escape hatch. New approved datasets/protocols require an explicit decision; advanced capabilities are conditional, not scheduled commitments. |

## Repository baseline and evidence limits

Static inspection at `4c42018` verified these implementation boundaries.
No tests or performance measurements ran in the review; its worktree had no
Python virtual environment or market-data caches. Neither live Mac/VPS
placement nor actual coverage was verified. Recheck these facts in R0.

| Existing source | Reuse and limit |
|---|---|
| `backend/app/engine/factory_data.py`: `Series`, `FeatureContext`, `prior`, EMA/ATR/VWAP | Shared calculations; stop-free interface needed. Preserve existing Factory values, defaults and model feature lists. |
| `backend/app/engine/factory_gates.py`: `clustered_mean`, `_session_paths` | Clustered SE primitive and future-path helper. Future paths belong only in outcome calculation. |
| Same module: `Stats`, `summarize`, `_after_fill`, `discovery_forward` | Strategy-specific reference behavior, not a drop-in event engine: R, stops, executed family trades and strategy baselines affect results/populations. |
| `backend/scripts/strategy_factory.py`: `BarStore`, `AlpacaCache`, `engine_fingerprint` | Cache-only loading and cache patterns. `_bars` reads/builds all dates before `load` truncates; Studio needs a source-level date boundary. |
| `backend/app/engine/market_map.py`: `resample` | Aggregates available minutes but does not establish bucket completeness. Exact research endpoints need coverage rules. |
| `frontend/components/charts/PriceChart.tsx`, `frontend/lib/chartStore.ts` | Lightweight Charts foundation, panel data, markers and interaction patterns; isolate live-store/clock behavior for static research. |
| `frontend/components/FrozenSampleChart.tsx` | Useful cutoff/missing-data presentation; packet-specific SVG and fixed intervals make it a weaker interactive foundation. |
| `backend/app/engine/job_runtime.py`, `jobs.py` | Durable job patterns exist. No research lane/dispatch exists; embedded jobs use threads. A job name alone is not CPU isolation. |
| `backend/tests/test_factory.py`, `test_strategy_factory.py` | Existing synthetic causality, execution, gate and ID tests to preserve and extend; not proof of unbuilt Studio behavior. |

## Enduring integrity rules

1. Decision-time features use only completed information available at the
   decision. Future returns, paths and outcome-based selections cannot become
   condition inputs. A chart chosen after seeing its recovery remains an
   outcome-informed idea even when its feature calculation is causal.
2. Keep Factory confirmation/exam boundaries, IDs, defaults, behavior,
   validation semantics and historical records unchanged. No incidental UI
   change can migrate them. The live ledger remains owned by the Factory;
   Studio's exploration log is not a second validation ledger.
3. Under the existing protocol, Studio exploration and occurrence charts use
   discovery only: 2023-07-03 through 2024-09-30. Prior warm-up data may feed
   indicators but cannot become research events. The boundary applies to
   source reads, workers, charts, exports and caches, not only UI controls.
   A submitted date or cursor must not bypass it. Confirmation/exam bars and
   breakdowns are never available through this exploration surface.
4. Preserve actual exposure history. Older data does not make an already
   inspected period unseen again. Existing hand-research exposure remains a
   limitation, including the Factory's documented prior holdout exposure.
5. Distinguish unavailable from zero. Report coverage, warm-up exclusions,
   per-horizon eligibility and adjustment provenance; never fill absent bars
   with invented prices or silently use a nearby endpoint.
6. Highlighting never changes the population, N or statistics. A decision-time
   brush may explicitly create a predicate and a changed draft, marked as
   chosen after viewing outcomes. Outcome-axis brushes cannot do so.
7. Results belong to immutable analytical inputs and data/engine versions.
   Editing any analytical input marks the old result as previous; a late
   response cannot replace a newer draft's result. Reopened cached results
   retain identity and record exposure.
8. Runs, failures and abandoned variants remain in an append-only exploration
   history. Notes/verdict revisions append rather than overwrite prior runs.
   Neither explicit Run nor a look counter eliminates adaptive overfitting.

### Relationship to the Factory protocol

Exploring discovery makes its results exploratory. Keep the existing screen's
behavior, but do not present it as independent evidence for Studio-derived
candidates. `prior_candidates` counts distinct ledger IDs that reached
confirmation, including applicable hand-research records; Studio previews and
runs do not silently change K or the weekly candidate budget. Any later
promotion carries its lineage and outcome exposure into the candidate notes.
The promotion slice must decide budget handling explicitly before enabling it.

Repeated confirmation-informed revisions remain adaptive: counting candidates
does not repair hypotheses chosen using confirmation results. If a later
read-only candidate view is selected, expose confirmation only as the ledger
allows and the exam as passed/failed, never discovery-style drilldowns. Do not
load the ledger's restricted detail into a browser and merely hide it.

## First release: one connected session

You notice a sharp decline on a discovery chart, select a completed bar and
inspect what was known then. Or start with “sharp decline on high volume” in
the condition editor. Both create the same experiment draft.

Use 15-minute move, relative volume and a morning decision window to describe
it. Editing immediately validates inputs; a separate population query shows
counts, dates, weeks, tickers, concentration and exclusions without aggregate
outcomes. No latency promise is made before R0 measurements.

Press Run to see forward returns against a stated baseline. The chart,
distribution, one feature-versus-outcome scatter and occurrence table share
stable occurrence IDs and a common inspector. Select an outlier and step
through its historical charts. Keep “known at decision” and “what happened
next” visibly separate. Chart outcome reveals count as exposure even without
an aggregate run; dimming a future region is not proof it was unseen.

Duplicate as a variant and change the volume threshold. Compare retained,
removed and added occurrences and both complete populations' outcomes. Save a
conclusion such as “Higher volume did not clearly separate recoveries,” linked
to both runs. Saving does not claim an edge or emit an executable strategy.

### V1 scope and explicit non-goals

| Limit | Classification and reason |
|---|---|
| Up to three AND predicates; no formula/OR editor | V1 simplification. Keep time-window controls explicit and saved. |
| First qualifying bar per ticker-session within the decision window | V1 simplification, not an assertion of independent samples. |
| Five-minute RTH bars, core symbol set, SPY market context | V1 simplification/current data constraint. SPY is context, not an extra target in aggregate event counts. Report eligible names rather than promising all 18 have data. |
| Fixed discovery dates | Integrity under the current protocol, not a permanent ban on separately approved datasets. |
| A separate research route, compute near approved cache | Layout/operational simplification. No Mac-only browser rule; no VPS provisioning or public access in V1. |
| Percent and named ATR returns; no strategy P&L | Event semantics. No stops, sizing, fills, execution, auto-promotion, live/paper signals or profitability verdict. |
| No formulas, similarity, ML, Level 2, sweeps, heatmaps or AI | V1 deferral; reopening criteria below, not long-term exclusions. |
| No news/macro/options/swing horizons or new research periods | V1 scope. No paid fetch, protocol change or retrospective claim about unseen data. |

### Features and units

Use a fixed price-direction convention: a decline is negative. Changing an
outcome-side view must not reverse predicates or change the event population.
Provide a stop-free interface over shared calculations; never fabricate a stop
just to produce `risk`. Missing/invalid values reject that predicate and have
explicit exclusion counts. Select only completed, aligned SPY observations;
missing/stale market context cannot silently masquerade as contemporaneous.

| Existing feature | Unit and required history |
|---|---|
| `minutes` | Minutes from 09:30 to the decision bar's close. |
| `rvol` | Cumulative volume / up-to-10 prior observations at that clock bucket; at least five. Missing buckets mean these are not necessarily the immediately preceding ten sessions. |
| `gap`, `day_move` | Prior completed daily ATR(14) units; 14 completed daily observations plus valid open/prior close. |
| `trend`, `open_trend` | Prior daily EMA(20) distance / prior daily ATR(14); 20 completed sessions. |
| `trend_slope` | Five-session EMA change in daily ATR units; 25 completed sessions. |
| `rel_strength` | Percentage-point return difference versus SPY using closes five sessions back. |
| `spy_trend`, `spy_day` | SPY daily ATR units; respective EMA/ATR history and completed market observation. |
| `vol_ratio` | Prior daily ATR(5)/ATR(20); 20 completed sessions. |
| `spy_vol` | Prior SPY daily ATR(14) as percent of prior close. |
| `vwap_distance` | Distance from Factory session VWAP / chart-bar ATR(14); 14 chart bars and positive session volume. |
| `risk` | Excluded: requires a strategy stop. |

The one new V1 feature is the close-to-close move over three complete
five-minute bars in the same session, divided by prior daily ATR(14).
It needs the starting close and all intervening complete buckets; it must not
reach across the overnight gap. Name the 15-minute interval and denominator
in the UI. Add causality and missing-data fixtures without changing existing
feature definitions or unnamed model defaults.

ATR-scaled VWAP distance is **not** a VWAP standard-deviation band. Charts
compute volume-weighted sigma from minute HLC3; Factory VWAP uses resampled
HLC3. V1 labels its actual calculation. A sigma condition needs a separately
specified feature, not a renamed ATR feature.

### Events, outcomes and comparisons

- **Event rule:** first qualifying completed bar inside the decision window,
  per ticker/session. Already true at the window opening qualifies. A
  threshold crossing is a different rule requiring a known prior false state,
  missing-bar behavior and reset semantics; defer it until requested.
- **Reference/outcomes:** next complete five-minute bar's open in the same
  session, then exact closes 15/30/60 minutes later and the scheduled session
  close. No next-session substitution. Missing next open excludes the event
  from outcomes; a missing endpoint excludes that horizon only. Report counts
  and reasons. Use percent of reference price and prior daily ATR(14) frozen
  at decision time; no R or strategy cost/profitability inference.
- **Baseline:** ordinary eligible moments on the same ticker, decision clock
  bucket and horizon, weighted to the event population's composition. Include
  qualifying moments in the ordinary population and disclose that choice.
  This asks how events differ from ordinary moments at similar times, not a
  causal question or a regime-controlled trading claim. Record missing matches.
- **Dependence:** first-per-session still leaves correlated symbols and
  overlapping baseline windows. Display distinct dates/weeks, largest-day
  concentration and per-horizon N. Never label weeks “independent.”
- **Uncertainty:** estimate event/baseline uncertainty jointly, for example
  calendar-week block resampling with all symbols together and the baseline
  recomputed each time. Fix and record method, seed, interval level and
  insufficient-cluster behavior in R1. Verify it on synthetic fixtures before
  showing intervals. Week independence is an approximation, not a remedy for
  adaptive research. Mark 30 minutes as the default primary descriptive
  horizon; the others remain visible exploratory outcomes, not extra gates.
- **Variants:** identity is ticker plus decision timestamp within a fixed
  dataset. Tightening a condition may select a later event in the same
  session, so removed-versus-retained alone is insufficient. Show retained,
  removed and added sets, and compare full populations with joint resampling.
  Retained events have identical outcomes under the same analysis definition;
  changed definitions are labeled and not misrepresented as predicate-only
  comparisons. Comparisons are descriptive, not independent validation.

### Run identity and persistence

Save canonical event definition/version, decision window, event rule, feature
units, horizons, normalization, baseline, universe, period, engine fingerprint,
data manifest/content identity, exclusions, results and uncertainty method/seed.
Record parent, changes, distinct specifications, execution attempts and outcome
exposures separately. Viewing an occurrence's future or reopening a cached run
is exposure, not a new independent experiment. Arbitrary visual inspection is
not perfectly measurable; do not claim the log captures every researcher choice.

Persist immutable runs and append-only notes/verdicts: Promising, Rejected or
Unclear with a reason. A manifest must detect corrected same-date data; “latest
cache date” alone is insufficient. No Factory ledger mutation is part of V1.
Storage choice is bounded in R0; reuse local file/cache or existing job patterns
where adequate, without promising that persistence requires no design work.

## Data and rendering boundaries

[Charts workspace](charts-workspace.md) describes a distinct data pipeline:
current Tradier bars, historical SIP raw sessions with calendar hours,
recorded corporate-action splits, Tradier daily history, first-close EMA
seeding, minute-derived VWAP/sigma and a 20-session RVOL baseline. Factory
uses its own cached minutes, regular sessions with a fixed early-close table,
inferred splits, daily bars derived from intraday data, SMA-seeded EMA and
its own VWAP/RVOL definitions. Neither adjusts dividends.

These differences prevent silently treating live-chart values as Studio
predicates. They do not prevent shared rendering or a symbol/time navigation
link: Studio can check discovery coverage and recompute its own values. Full
indicator parity is not required merely to navigate. The research chart must
use the exact versioned bars that produced its observations, disclose price
basis and avoid live-stream contamination. No unreviewed correction to the
Factory's split policy is folded into this UI project.

Current store/evidence caches are useful patterns, not sufficient integrity
boundaries. Restrict source reads before loading protected dates, fingerprint
actual data and verify complete minutes, session opens and horizon endpoints.
Use cached feature columns for repeated predicates only after these boundaries
are established. Fetch occurrence chart windows lazily from the same manifest.

## Small delivery phases

R0 probes and bounded R1 observations are complete with documented evidence
limits; R2 is implemented with documented acceptance limits; R3 is selected for the connected workspace; R4 is **planned, not started**. V1 is complete only after R4.
Each phase is separately selected and reviewed, with one bounded result; the
plan does not authorize implementing the entire sequence at once.

| Phase | Deliverable | Acceptance criteria |
|---|---|---|
| **R0 — Evidence and feasibility** | Read-only approved-cache audit; temporary static-chart and timing probes; bounded implementation contract | Record actual feed, symbols, dates, minute/bucket completeness, warm-up and adjustment basis. Do not read confirmation/exam bars for probes. Measure cold load/preparation, warm population query, completed run estimate and peak memory separately. Exercise fixture chart selection/markers/zoom without live updates. Decide source cutoff, content manifest, minimal extraction, persistence and worker isolation; state measured latency targets and unresolved blockers. No paid fetch, protected-record writes or shipped feature. |
| **R1 — Event observations** | Versioned definition, stop-free feature access, first-match selection and bounded loader; no UI | Synthetic tests pin exact values/units, same-session 15-minute move, missing/zero behavior, warm-up exclusions, SPY alignment and future perturbation invariance. Requests/cursors cannot read beyond discovery, including cold source/cache paths. Existing Factory IDs, trades and validation remain unchanged. Freeze baseline/uncertainty specifications for R2. |
| **R2 — Reproducible analysis** | Explicit run, baseline/outcomes, immutable results and job execution | Hand-calculated fixtures verify next-open reference, all horizons, early closes, absent endpoints and matching weights. Deterministic joint-resampling fixtures cover event/control uncertainty, correlated symbols and insufficient clusters; null simulations assess calibration rather than requiring every null trial to look insignificant. Manifest correction invalidates cache. Failed/interrupted/retried work has honest durable status and no duplicate logical run or ledger write; research work does not queue behind sync. |
| **R3 — Connected workspace** | Chart, conditions, population preview, analysis and common inspector | Browser fixtures complete both chart-start and question-start paths. Counts agree with engine observations; every view selects identical occurrence IDs/bars. Highlighting leaves N/statistics unchanged. Editing inputs and out-of-order responses cannot mislabel old results. Outcome reveals and cached reopens are recorded. Measured feedback/loading/cancellation behavior meets R0 targets. No live feed or protected data leaks through research navigation. |
| **R4 — Variants, conclusions and usefulness** | Parent comparison, saved conclusions, user acceptance | Fixtures cover later replacement events in the same session, all three event sets and identical retained outcomes. Reload restores exact runs and append-only note history. User independently completes the sharp-decline journey and explains N, baseline, stale state and uncertainty. Record real unanswered questions/fallbacks and actual usage before approving expansion. No requirement that exploratory results be profitable. |

### First slice

When implementation is selected, start with **R0**, not the retired W0. The
smallest useful evidence is a read-only inventory and timings on the existing
approved discovery cache, plus a temporary static fixture in the chart
foundation. Keep generated probe output in temporary storage, not the research
ledger or protected datasets. Missing local data is a finding, not permission
to fetch more history or provision the VPS. Return a bounded R1 contract with
pass/fail criteria and measured bottlenecks; do not build a general quant platform.

The standard repository verification and review requirements still apply to
each implementation change. Fixture correctness, browser behavior, actual
cache coverage, performance and human usefulness are separate evidence layers.
The R0/R1 reports distinguish observed acceptance from remaining later-phase
proof; the complete connected Studio remains unbuilt.

## Later capabilities and reopening criteria

| Capability | Why deferred; what would justify revisiting |
|---|---|
| Factory handoff, possibly `condition_event` | V1 events lack stops/exits. Revisit after saved useful hypotheses need simulation; require canonical predicate parity, execution/stop semantics, stable old IDs/trades, lineage, budget decision and unchanged gates before offering validation. Do not assume every event is an executable trade. |
| Formulas, OR and richer composition | Repeated useful questions blocked by the bounded feature menu; specify a causal, unit-aware expression subset before adding it. No speculative expression framework now. |
| Pattern similarity | Repeated shape questions plus a past-only window representation, distance definition, overlap controls and adequate reference data. Conditions do not exhaust all legitimate pattern research. |
| Small ML playground | A concrete predictive question, adequate dataset, fixed training protocol and untouched or prospective evaluation. Weak weights in one existing logistic model do not rule out ML generally. |
| Level 2/order-book research | A specific question plus licensed timestamped, venue-aware history and explicit reconstruction semantics. Current absence and the Charts epic's exclusion are not a permanent Studio ban. |
| Sweeps and heatmaps | Repeated sensitivity questions, bounded grids, recorded adaptive accounting and a validation plan; no unattended optimizer by default. |
| More symbols, timeframes or horizons | Demonstrated demand and measured coverage/dependence. Longer holds may need a separate protocol; never silently reset K or reuse exposed periods as unseen. |
| Older history/new datasets | Explicit availability, cost, survivorship and protocol decision. New history does not rehabilitate prior exposure. No runtime toggle around protected periods. |
| Macro, earnings, news, sector and options context | A repeated question and historically available, versioned, as-of data. Current snapshots/prospective labels cannot stand in for missing discovery history. Existing recorders remain owned by their plans. |
| Contextual AI | A useful log and a repeated interpretation task; ordinary research remains usable without AI. No direct protected-data or autonomous validation bypass. |
| VPS/phone access and live-chart handoff | Measured demand and an explicit operational slice. Preserve private access and source identity; do not equate a separate route with a separate permanent product. |

## Decisions still open

- R0 and R1 were selected before further S1–S2 work; R2 was subsequently selected in this chat; R3 was selected after R2 merged; R4 requires separate selection.
- Approved cache host and component measurements are recorded in the
  [R0 report](agent/research-studio-r0.md); end-to-end performance is still unproved.
- Data-quality masks and concrete uncertainty parameters are fixed in the
  [R1 contract](agent/research-studio-r1.md). R2 must prove analysis/calibration
  before displaying results.
- Whether a saved event merits Factory promotion and how that promotion uses
  the weekly budget: decide only when the later handoff slice is selected.

R2 was selected after inspecting R1 coverage and correctness evidence; its
[current contract](agent/research-studio-r2.md) owns acceptance. This selection
did not authorize later phases; the subsequent user selection authorizes R3 only.
