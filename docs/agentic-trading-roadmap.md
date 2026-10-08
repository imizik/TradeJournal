# TradeJournal: a trading process that runs while Isaac works

**Proposed product track, 2026-10-07. Documentation only; no implementation is authorized by this document.**

This proposed track would prove one small loop: **freeze a decision, watch its
objective trigger, send a useful alert, paper-track the outcome, and review the
original decision.** Start with underlying shares, at most three candidate
plans a day and five watched symbols. Use an agent for bounded preparation and
critique; let deterministic code monitor conditions and account for outcomes.

Within this track, do this before building an interactive strategy optimizer
or acquiring a large news archive. The first month should produce
forward records and reveal whether this fits a working day. It cannot establish
a trading edge or justify real-money automation.

For the immediate assignment queue, jump to the
[first three slices](#15-recommended-first-three-implementation-slices) and
[30-day sequence](#16-proposed-first-30-days). The preceding sections explain
the reuse decisions, evidence limits and contracts those slices depend on.

## How to work from this roadmap

This is the proposed **Agentic Practice** track, alongside the existing
[Charts](charts-roadmap.md), [journal learning](product-roadmap.md),
[swing strategy and practice](swing-strategy-roadmap.md), and
[Strategy Workbench](strategy-workbench-roadmap.md) plans. The swing plan's
S1–S2 is a separate, after-close factory-signal proposal; this track tests
morning human/agent decisions and intraday paper plans. They share the same
phone, practice and decision concepts. Choose which loop to run first before
implementation, and reuse one decision record and paper outcome service if
both are eventually built. Do not create competing Take/Skip stores or two
practice pages. This document does not change the other plans' priorities.
If this track is selected, start with A1, then A2, then A3. Assign and review
**one slice at a time**; finishing a slice does not authorize starting the next.

1. Read the selected slice's scope, exclusions, acceptance criteria and
   verification. Use the domain, data and permission contracts above it for
   implementation decisions. Recheck current code, migrations and concurrent
   chart work before starting; the inspection snapshot in section 2 will age.
2. Keep the implementation inside that slice. Put newly discovered work in a
   later row or document a concrete blocker instead of silently expanding the
   current pull request. Preserve the existing private API and production
   deployment rules in [CLAUDE.md](../CLAUDE.md).
3. In the same implementation change, update the row below with its evidence
   and PR, update the owning feature docs, and identify the next eligible row.
   `built` means code landed; `done` requires that row's stated verification,
   including human/provider evidence where specified. Mark unknown evidence
   explicitly rather than treating a fixture as a live result.
4. After A3, run the observation period before selecting one Phase C topic.
   Phase C and D rows are **decision gates**, not ready-made implementation
   contracts. Write a bounded contract only for the selected follow-up.

| ID | Deliverable | Depends on | Status / exit evidence |
|---|---|---|---|
| P0 | Set the first practice policy, universe and schedule | Selection of this track | selected in [P0 v1](agent/practice-policy.md); synthetic plan/outcome and real read-only source-time check recorded; forward use awaits A1/A2 operational gates |
| A1 | Freeze and retrieve a human or agent decision | P0 | [PR #143](https://github.com/imizik/TradeJournal/pull/143) merged; merged CI including Postgres parity passed; read-only provider time/unit check and 390px automated WAIT save/reopen observed; human timing and provider-backed TAKE remain unobserved; records remain practice drafts and unarmed |
| A2 | Watch, alert and paper-track a fixed-rule plan | A1 | proposed second build; exit: one observed phone alert and restart-safe paper lifecycle, with any operational probe labeled and excluded from strategy results |
| A3 | Run the short daily routine and compare independent choices | A2 | proposed third build; exit: three observed sessions with honest run status, paired choices and review timing |
| B | Use the same policy for forward observation | A3, or manual preparation using A1/A2 | proposed observation; exit: at least ten eligible sessions with coverage and attention results |
| C | Select one research or thesis improvement | B review and a named recurring obstacle | conditional decision gate; write one new scoped contract after choosing the obstacle |
| D | Evaluate a frozen policy prospectively | Specific C contract and parity/evidence gates | conditional decision gate; inconclusive is an acceptable result |

The [phase gates](#14-phases-and-explicit-gates) define when to stop or defer;
the [first-month scorecard](#first-month-scorecard) measures whether the loop
is worth continuing. A1–A3 are the only implementation-ready slices in this
document. No row is marked `next` until this track is chosen over competing
work on the existing boards.

## 1. The product decision

The proposed long chain mixes three different questions:

| Question | Evidence that answers it | Product home |
|---|---|---|
| Is my account of the world predictive? | Frozen thesis predictions and their later measurements | Theses, within Research |
| Does an objective setup generalize? | Factory specs, discovery, confirmation, exam, subsequent forward evidence | The separately planned Strategy Workbench |
| Can I make and follow useful decisions while working? | Timestamped opportunities, plans, alerts, paper events and review | Today and Daily Review |

Connect them with explicit references, but allow each to work independently.
A technical setup need not have a geopolitical thesis. A thesis need not produce
a trade. An agent can SKIP, and a good decision can lose. A correct narrative,
a valid entry, and an acceptable entry price are separate judgments.

The central unit is a **decision opportunity**: a named symbol or theme, an
information cutoff, an eligible time window, and independently recorded actor
decisions. A TAKE decision may attach an executable plan. WAIT specifies what
would change the decision and when waiting ends. SKIP records why. No response
is **unobserved**, never an inferred rejection.

Recommended initial attention contract: one brief before 09:00 New York, up to
three actionable setup notifications a day, a five-minute after-work review,
and one 20-minute weekly review. Stops and paper management run without an
open browser. Measure whether this contract is realistic rather than assuming
that a strategy with an attractive backtest fits the user's life.

If the morning agent workflow is selected over the after-close S1–S2 path,
this proposal recommends A1–A3 as its first experiment. It does not mark other
roadmaps done, reorder their boards, or grant deployment permission. A live
phone alert satisfied Charts C5.1 on 2026-10-06; C5.2 is merged, with the
Charts board still recording fresh-deployment verification as pending. The
factory's validated-strategy paper path remains gated; the proposed
**Practice** path is a separate, explicitly unvalidated experiment.

## 2. Excavation: what exists and what it proves

### Inspection boundary

The implementation inspected is `/Users/user/TradeJournal` at
`2dac72447e8e19bc904c2a844a960d99feed8780`. Existing unrelated local changes
were left alone. The local `origin/main` ref was three commits ahead, including
`8b1088f` (C4.6 stored OI changes); it was not fetched or pulled. Thus C4.6 is
absent from the inspected checkout, but is already present in that local remote
ref and should not be proposed as new work.

Before opening this documentation PR, `origin/main` was fetched at `ff4a9f2`.
It has since added C4.6, the News tab, C5.1's observed phone check, C5.2's
merged code, and the two linked swing/Workbench proposals. The detailed
implementation inventory below remains labeled as the earlier inspection;
recheck current code before implementing any slice. This document adds the
morning agent, immutable decision and review proposal; it is not a replacement
for the newer swing or Workbench contracts.

The active research checkout is `/Users/user/TradeJournal-factory`, branch
`factory/ledger`, at `47f58aa2f80a69e1f78c7edf937b0c986e8dbc36`, dated
2026-10-04. It was clean when inspected. That branch's ledger and reports,
rather than main's historical copy, support the research findings below.
No factory evaluation, provider request with account credentials, database
audit, live alert, browser walkthrough, or deployment was performed for this
proposal. Existing reports are inspected evidence, not independently rerun
results. Public provider documentation was checked for the source contracts
cited in section 8.

### Reuse map

Paths below refer to the inspected checkout unless explicitly linked to a
factory-branch artifact. Functions are useful entry points, not new APIs.

| Existing capability | Implementation inspected | Reuse and limitation |
|---|---|---|
| Market packets | [packets.py](../backend/app/engine/packets.py), `build_market_report`, `/packets/report` | Index detail, sectors, watchlist buckets, relative strength, ETF macro proxies, VIX/10Y and headlines already exist. Add an immutable decision snapshot around this; do not rebuild the report engine. |
| Archived packets | `backend/data/packet_archive/` | Three local JSON packets: 2026-07-08 postmarket, July 9 and 10 premarket, with 13 sector rows and 44–50 symbol headlines plus 25 broad headlines. These are old snapshots, not evidence of an operating daily service. |
| News | [news.py](../backend/app/engine/news.py), `fetch_news`, `/packets/news` | Paginated Alpaca/Benzinga fetch, ID dedupe, summaries and capped article text. No durable article-version or catalyst store; `updated_at` is discarded. |
| Ticker and scalp analysis | [analyzer.py](../backend/app/engine/analyzer.py), [scalper.py](../backend/app/engine/scalper.py), `/packets/analyze`, `/packets/scalp` | Daily indicators, fresh intraday context, pure `score_scalp`, deterministic level-based suggestions. Read-only, heuristic and intraday-oriented; its score is not a calibrated success probability or factory validation. |
| Chart facts and levels | [chart_feed.py](../backend/app/engine/chart_feed.py), [chart_levels.py](../backend/app/engine/chart_levels.py), [chart_calendar.py](../backend/app/engine/chart_calendar.py), [chart_adjust.py](../backend/app/engine/chart_adjust.py) | Shared live feed, session calendar, split basis, pure `compute_levels(as_of=...)`, confirmed structure and confluence. Reuse for plan evidence; preserve level source, formation time and measured/calculated/inferred labels. |
| Phone level alerts | [level_alert_monitor.py](../backend/app/engine/level_alert_monitor.py), [level_alerts.py](../backend/app/engine/level_alerts.py), [ntfy.py](../backend/app/engine/ntfy.py) | Browser-independent monitor, stream plus minute-bar fallback, one firing per alert generation, retrying outbox. Existing cap: 20 active alerts across five symbols. No plan or position lifecycle. |
| Human pre-trade capture | [captures.py](../backend/app/engine/captures.py), [captures router](../backend/app/routers/captures.py), [PlanSheet](../frontend/components/charts/PlanSheet.tsx) | Immutable submitted intent, frozen browser context, receipt time, retry identity, raw audio, image and separate later notes. Keep this as the human capture surface. It requires a real journal account and is not an executable agent plan. |
| Voice | [transcribe.py](../backend/app/engine/transcribe.py), capture worker lane | Local Whisper transcription, raw-file hashes, explicit retry, original preserved. Current clips are 30 seconds and trade-scoped; a long market-thesis ramble is not supported by simply reusing the current form. |
| Plan-to-journal links | [capture_links.py](../backend/app/engine/capture_links.py), [LinkReview](../frontend/components/charts/LinkReview.tsx), [PlanSummary](../frontend/components/charts/PlanSummary.tsx) | C3.6 is implemented. Links anchor to account/source-fill identity and survive FIFO rebuilds; pre-entry, retrospective and uncertain timing are distinct. Coverage is capture coverage, not discipline or alpha. |
| Strategy factory | [factory_rules.py](../backend/app/engine/factory_rules.py), [factory_data.py](../backend/app/engine/factory_data.py), [factory_gates.py](../backend/app/engine/factory_gates.py), [factory_brief.py](../backend/app/engine/factory_brief.py), [CLI](../backend/scripts/strategy_factory.py) | Canonical specs/IDs, four families, causal entry features, one execution model, clustered comparisons, staged data access, ledger and reports. `factory_brief.catalog()` already builds a backend catalog. |
| Strategy Lab | [router](../backend/app/routers/strategy_lab.py), [metrics](../backend/app/engine/strategy_metrics.py), [UI](../frontend/app/strategy-lab/page.tsx) | Imported Pine versions/runs, fingerprinted preview/commit, immutable-after-use versions, coverage-aware metrics and trade drill-down. Reuse presentation patterns; do not make CSV import the factory's storage protocol. |
| Thematic research workspace | [research.py](../backend/app/engine/research.py), [Cockpit](../frontend/components/research/Cockpit.tsx), [store](../frontend/lib/research/store.tsx) | AI Buildout research, watchlists, thesis/bear notes and signposts exist. One editable JSON document with optimistic revision checks; a revision number is not retained belief history. Use for discovery and navigation, not prospective scoring. |
| Jobs and deployment | [job_runtime.py](../backend/app/engine/job_runtime.py), [jobs.py](../backend/app/engine/jobs.py), [worker](../backend/app/jobs/worker.py), [deployment](../deploy/README.md) | Durable `JobRun`, single-host locks, five lanes, systemd timers, operational ntfy. Reuse; no broker or distributed queue is needed. Running jobs interrupted by dead owners fail visibly rather than silently replaying. |
| Agent tools | [mcp_server.py](../backend/mcp_server.py) | Eleven read-only tools, thin stdio/httpx adapter, request metadata logs. It has market report/news/ticker/scalp and journal tools; it has no plan, thesis, strategy signal or paper-write tools. |
| Options context | [options_feed.py](../backend/app/engine/options_feed.py), [options_implied.py](../backend/app/engine/options_implied.py), [options_recorder.py](../backend/app/engine/options_recorder.py) | Shared live chains, straddle-implied move, OI/volume snapshots with missing-session status. Useful current evidence; not years of historical options inputs. |
| Review and data quality | [analytics.py](../backend/app/engine/analytics.py), [daily review](../backend/app/routers/daily_review.py), [audit script](../backend/scripts/audit_journal_data.py) | Reuse review entry points, coverage conventions and source traceability. Closed journal P&L is not account return; historical R is unavailable without recorded initial risk. |

### Gaps that change the design

1. **A packet is not yet an immutable information set.** `_archive_report`
   overwrites `(session_date, report_type)` and logs rather than propagating
   archival failure. `generated_at` is taken before gathering finishes; it is
   not a cutoff for every constituent. `_breadth_row` drops source timestamps,
   and `_yf_gauge` does not return an observation time. The `confidence` label
   counts missing fields. It measures coverage, not predictive confidence.
2. **There are multiple calendar/feed conventions.** Packet market-state
   helpers use weekdays and clock hours, whereas charts have a holiday/early
   close calendar. Alpaca packet feed is configurable, defaulting to IEX,
   while the packet caveat always says IEX. Chart history explicitly uses
   SIP/raw; live charts use Tradier. Do not call these interchangeable.
3. **Alerts do not freeze trade plans or simulate fills.** Current close alerts
   support 1m–4h, not 1D. Their sweep reads today's minutes, so a multi-day
   outage is not a guaranteed historical replay. Deleting an alert explicitly
   deletes its event rows. A durable paper record cannot depend on that row
   remaining forever.
4. **Captured chart context is browser evidence.** Server receipt proves when
   it was saved, not that every submitted price is independently verified.
   Machine-executable plans need validated, server-owned facts and structured
   conditions. Screenshots and free text cannot execute a trigger.
5. **No paper position ledger, prospective thesis evaluator, or independent
   agent-versus-human opportunity denominator exists.** The `StrategyExperiment`
   model is a schema starting point; no functioning experiment service/UI was
   found. Do not label it a ready-made evaluation system.
6. **The factory is a local research workflow, not an API service.** Its sole
   ledger owner is a Mac checkout. A VPS web worker must not write a second
   authoritative ledger or pull the research branch into the production
   release checkout.

## 3. What the factory currently says

The [latest weekly report](https://github.com/imizik/TradeJournal/blob/47f58aa2f80a69e1f78c7edf937b0c986e8dbc36/research/reports/2026-10-04.md)
contains two new candidates, neither passing. The
[inspected ledger](https://github.com/imizik/TradeJournal/blob/47f58aa2f80a69e1f78c7edf937b0c986e8dbc36/research/ledger.jsonl) contains
22 records, 21 distinct IDs, nine hand-research records and 13 factory records.
One hand-research ID occurs twice. Twelve distinct candidates have reached
confirmation; none has passed it. The next new confirmation candidate needs
approximately **t ≥ 2.67** under the current counting rule.

| Recovery-swing candidate | Discovery | Confirmation | Conclusion permitted |
|---|---|---|---|
| `re-f700e5e41e`: daily-EMA recovery with SPY above its session open | 292 trades; +0.282R average; +0.290R versus matched random; t=2.59 | 319 trades; −0.009R average; +0.041R versus random; t=0.33. Second half −0.059R; triple-cost −0.028R | Failed confirmation. A plausible regime story did not generalize. |
| `re-3d2a12fb74`: hold the recovery a third session | 394 trades; +0.194R average; +0.191R versus random; t=1.96 | Not opened | Failed screen; increasing the hold did not clear the current gate. |

The report's discovery forward-path discussion quotes +0.03R versus random at
30 minutes, +0.05R at one hour, +0.11R at session close and +0.21R at next
session close. This motivates investigating a slower response. These are
entry-path diagnostics before the candidate's exits and costs, not realizable
net returns or proof of monotonic improvement through 16 days. The earlier
one-hour-stall version also failed confirmation.

The report's **“What the ledger says now” is model-authored prose** inserted by
`factory_brief.weekly_report` from `answer['lessons']`. Claims that a family is
“finished” or that a regime explains a failure are interpretations. Preserve
the underlying measured results, and do not promote that prose to a gate.

The current safeguards are valuable but not absolute statistical protection:

- `evaluate` loads screen, confirmation and exam conditionally. `--no-exam`
  still permits confirmation; it is **not Explore mode**.
- Weekly proposal review limits three candidates, core tickers, default costs
  and two filters. Direct `run` candidates do not consume the weekly budget.
- `--rerun` can evaluate the same ID again, including exam unless disabled.
  The ledger count deduplicates IDs and the brief uses the latest record.
  Thus “exam once” is partly workflow policy, not an irreversible access lock.
- The weekly shell wrapper has a lock; direct CLI ledger read/evaluate/append
  does not share an enforced transaction. Concurrent UI/CLI runs could use a
  stale candidate count. Fix this before adding a writer surface.
- The docs disclose prior manual exposure to 2025–26 data, a journal-selected
  18-name universe, and uncounted cohort scans. Counting named candidates
  cannot undo that exposure. A rising normal-quantile threshold with adaptive
  reuse is a useful screen; it is not a complete familywise-error guarantee.

Use the existing verdict names, show the limitations, and require genuinely
future evidence for claims beyond the factory's historical tests.

## 4. Information architecture: small additions to existing surfaces

| Surface | First use | Later addition |
|---|---|---|
| **Today**, a section on the existing dashboard | 0–3 frozen plans, paper status, data/watch health and a link to the original evidence | Morning brief and independent choice controls |
| **Charts** | Deep-link to a plan's symbol and time; reuse PlanSummary styling and current levels | “Watch as paper plan” from a human capture, using the same plan service |
| **Daily Review** | A separate Paper/Decisions section alongside actual journal review | Weekly process and thesis outcomes |
| **Strategy Workbench** | Follow its separate roadmap and factory access gates | Cross-link any later frozen candidates and signals from Today |
| **Research** | Keep AI Buildout intact | A Theses tab with versions and due predictions |

Do not add separate top-level pages for a Morning Agent, Shadow Isaac,
Referee, Macro Terminal, Catalyst Lab and Paper Broker. These are roles and
views of the same small record set. Do not silently repurpose `/signals`;
check its current ownership after C5.2 deployment verification.

A phone alert should open one card showing: **PAPER / PRACTICE**, decision time,
ticker, why it was considered, exact trigger and whether it fired, price and
data age, invalidation, target source, expiry, and paper state. Secondary detail
contains evidence, alternatives and the event timeline. The user should be able
to explain it within 60 seconds. A link that opens only the current chart is
insufficient because current facts differ from the original decision.

## 5. Smallest backend/domain model

Keep FastAPI, SQLModel/Alembic, the existing providers, the single-host runtime
and private file storage. Preserve journal fills/FIFO, imported Strategy Lab
runs, historical signal records and paper practice as separate accounting domains.
Do not create a fake brokerage account to hold simulated trades.

### First-loop records

Start with **two explicit models**, introduced across A1 and A2. Names here are
proposed, not existing files or tables.

| Record | Required contents | Ownership |
|---|---|---|
| `DecisionRecord` | UUID, opportunity ID, actor (`human`/agent identity), record kind, version/parent ID, server receipt time, policy/spec/schema hashes, typed decision/plan, exact evidence envelope, optional `TradeCapture` reference | Original decision is immutable. A replacement is another row. Session abstention and human choice use explicit schemas, not arbitrary JSON. |
| `DecisionEvent` | Record ID, sequence, unique operation key, type, effective time and recorded time, evidence, engine version; narrowly typed arm/trigger/entry/exit/expiry/cancel/review events | Append-only economic/history content. Delivery attempts and execution checkpoints are operational metadata, not amended decisions. |

Store the small frozen packet inside the decision envelope initially. Repeating
a compact packet across three plans is cheaper than a generalized artifact
platform. Content hashes can deduplicate larger private files later. A packet
run with zero setups still has a session record, so missing runs and abstention
are distinguishable. Persist the exact compact input and structured response
used by the agent; request-length logs are not a record of its information set.

Paper position state is a projection of the events, not a new source of truth.
A cache of the projection is optional. Create no independent accounting engine
in React, no universal event bus, and no generic workflow designer.

`TradeCapture` remains the human's raw pre-trade record. An executable
`DecisionRecord` is its optional typed extension/reference, or an agent-owned
decision with no human capture. It does not rewrite captured wording, require
a real account for a shadow decision, or duplicate the human template library.
The same plan validator serves agent writes and a future chart action.

### Executable plan contract

A TAKE plan freezes symbol, underlying direction, information cutoff, actor
and policy version; entry condition with operator/interval/session; activation
and expiry; entry price guard; stop/invalidation; objective target reference;
maximum holding sessions; initial-risk calculation; cost/fill model; position
and notification limits; and reasons for/against. Link an optional factory spec
or thesis version without requiring either. WAIT and SKIP need no invented stop
or target, but WAIT needs a condition and expiry.

Each price reference carries value, currency/unit, source, source time,
formation time, observed time and split basis. A 2R target is a calculation
from the frozen risk policy, not market structure. Unsupported conditions are
rejected by the backend, even if the agent describes them persuasively.

Use server timestamps as UTC, display New York time, and convert the existing
journal's naive New York fill times through its current adapters. Never treat
all naive historical timestamps as UTC. Keep original risk as the denominator
through exits and revisions. For the proposed long-share simulator, retain
planned reference risk and separately fix initial fill risk as the slipped
entry price minus the original stop. Net per-share P&L divided by that positive
initial fill risk is realized R; subsequent stop changes never shrink the
denominator. If risk is absent, report price return and missing R.

### Later records, only when their gate is met

- `ThesisVersion` and typed `ThesisPrediction`/evaluation records: once users
  repeatedly record beliefs they actually want scored.
- `ArticleVersion` and versioned catalyst classification: once the initial
  captured news is useful enough to warrant a reusable prospective collection.
- Factory exploration/attempt artifacts: owned by the authoritative factory
  ledger service, not duplicated in the journal database as another trial count.

### Runtime and scheduling

Use the existing level monitor for fixed-price trigger observations, and a
small deterministic paper evaluator beside it in the API process. Reuse the
same feed, calendar, budgets and persisted checkpoints. No model call belongs
in a tick handler. The current supported deployment is one API process;
uniqueness and conditional state transitions still defend against retries.

Use `JobRun` for finite morning preparation and after-close evaluation, and
systemd timers for scheduling on the existing always-on host. A local Mac-only
agent run cannot satisfy “watches while I work” if that Mac sleeps. The sync
lane can be occupied by enrichment/options snapshots; deadline-sensitive model
preparation should get one small dedicated lane using the same runtime when
scheduled in A3. Do not put it behind broker import or voice transcription.
The packet/agent job has a time budget and visibly misses its deadline if it
cannot finish. It must not return a late result labeled 08:50.

## 6. Generic agent/MCP/API contract

Business rules live in backend services. MCP remains an adapter, and a local
scheduled runner can use the same typed API. No Dots-specific storage,
callback format, scheduler, or model feature is required.

| Agent need | Reuse now | Proposed thin addition |
|---|---|---|
| Market state / premarket packet | `get_market_report` → `/packets/report` | A versioned response and a frozen snapshot ID/envelope; explicit live versus historical request semantics |
| News | `get_news` → `/packets/news` | Source/observation timestamps, saved article version references and completeness status |
| Ticker / watchlist / levels | `analyze_ticker`, chart workspace/settings and `compute_levels` | Bounded batch `get_watchlist_context` and `get_ticker_context`; `get_chart_levels` delegates to the chart service, without journal payloads |
| Active theses | No prospective thesis API exists | `get_active_theses` after the thesis slice; return explicit unavailable before then |
| Strategy signals | Factory generates historical trade artifacts | `get_strategy_signals` only after the live-family parity gate; distinguish historical result, practice signal and validated-forward signal |
| Plans / paper positions | No current equivalent | `get_open_plans`, `get_shadow_positions`, filtered to this actor/policy |
| Freeze a decision | Capture service provides receipt/idempotency patterns | `record_decision` / `create_trade_plan` through one validator; return stored ID/hash/time |
| Revise / cancel / review | Capture later-note pattern | `revise_trade_plan(expected_version=...)`, `cancel_plan`, `record_postmortem`; append, never PATCH the original |
| Paper entry / reduction / exit | No current equivalent | Internal deterministic transition services first. Agent-facing requests may request an action but cannot choose a historical fill price/time. Partial reduction deferred. |

Write commands require an operation ID, expected version where relevant and a
validated schema. A repeated ID with identical content returns the original;
the same ID with different content is a conflict. Retries cannot arm twice,
create two positions, or revise a past decision. Store actor/model identifier,
returned model version where available, prompt/policy hash, tool result IDs,
input cutoff, start/end times, usage and errors. A vendor model alias is not
proof of identical model weights; retain the exact output for reproducibility.

Keep the existing all-journal MCP profile for human-assisted review. Give the
independent shadow role a separate allowlisted tool profile with market facts,
shared thesis versions and its own plans only. It must not read Isaac's current
decisions, fills or open positions before committing its independent choice.
MCP tool omission must be accompanied by service-side access restrictions for
that runner, not just a prompt. Start the runner on the private host with a
restricted capability token and no raw HTTP/shell tool that bypasses its
allowlist; do not expose the unauthenticated private API to
the public internet. Cloud agents require a separately scoped gateway design
later; tunneling port 8080 is not a shortcut.

Retrieved articles and web pages are evidence, never instructions. External
content cannot change the tool allowlist, risk policy or execution rules.
One bounded planner call and an optional bounded critique replace an always-on
conversation. If the model or web search fails, deterministic monitoring of
existing plans continues and new plans remain absent.

## 7. Strategy Workbench and slower swing research

The newer [Workbench roadmap](strategy-workbench-roadmap.md) owns its
implementation order and UI, and the [swing roadmap](swing-strategy-roadmap.md)
owns S1–S2. The analysis here records constraints for a later shared design;
it is not a second Workbench or swing implementation queue. Reconcile any
different protocol choices with those owning roadmaps before coding them.

### Workbench: extend the existing catalog

`factory_brief.catalog()` already derives families, parameter defaults and
feature descriptions from `FAMILIES` and `FEATURES`. Extend it with typed
parameters, units, coarse allowed values, null semantics, dependencies,
dataset coverage, temporal availability, family compatibility and policy
version. `parse_spec`, `canonical` and `spec_id` remain authoritative.

Frontend controls are rendered from this catalog. Backend validates every
submission and returns normalized spec plus ID; the browser never hashes a
different semantic representation or evaluates trading rules. Distinguish
**allowed research family** from **validated profitable strategy**. Earnings,
macro, sector and catalyst controls remain disabled/unavailable until the
backend actually supplies a causal feature and a coverage contract.

### Explore

- Discovery data only: 2023-07-03 through 2024-09-30 under the current factory
  protocol. Build an explicit discovery-only entry point; never map Explore
  to `run --no-exam`. The loader must reject later prices, including outcome
  horizons crossing the cutoff, rather than merely hiding them in the UI.
- Record every evaluated canonical configuration, its parent, hypothesis,
  author/source, data manifest and engine version, including failures and
  cancelled attempts that accessed results. No grid-search slider running a
  hidden experiment on every drag. A Run button and visible trial history suffice.
- Candidate ID remains the existing spec ID. A run/attempt identity additionally
  binds engine, data, evaluation protocol and stage. Preserve legacy IDs. A
  semantics-changing engine/data/protocol revision is a new evaluation epoch
  and counted hypothesis when promoted, never a cheap rerun of the same ID.
- Compare one baseline and one stated change. Show removed, retained and new
  signals; changed outcome paths; unavailable-feature exclusions; and total
  population counts. An exit change can free a position earlier and change
  subsequent entries, so “only a filter changed” cannot be inferred from a
  difference in average R. Align signal IDs and report interaction effects.

The initial result page needs trade count, distinct days/weeks/tickers,
average net R, matched-random difference and uncertainty, cost sensitivity,
concentration and missing coverage. Reuse factory summaries and existing
Strategy Lab table/chart presentation. Add profit factor, drawdown and
year/regime breakdowns with their actual definitions. Current factory
drawdown is the cumulative trade-R sequence ordered by entry time; it is not
simultaneous portfolio equity. Do not relabel it as account drawdown.

Every number drills into contributing signals. CSV entry features are a useful
start but do not fully explain arming/cancellation and failed filters. Add an
on-demand deterministic trace for a selected signal using the saved data and
engine identity: preceding family state, each operand/value/operator/result,
source bar close/availability, filter result, fill rule and subsequent path.
Keep later outcome data visually separate from “known then.” Default to
on-demand replay rather than storing a trace for every bar of every experiment.

### Freeze / Validate and honest trial accounting

Freeze exact rules, hypothesis, one primary endpoint, expected direction,
comparison, universe, horizons, costs, dataset manifest, code and evaluation
policy. Amendments become new candidates. A frozen spec is not validated.

Maintain two counts: all distinct discovery experiments/inspected cohorts,
and all distinct hypotheses that accessed confirmation. UI-origin candidates
join the same latter count as weekly and manual candidates; no separate
“manual allowance.” Discovery-only exploration does not automatically consume
the current confirmation K, but its search breadth is disclosed and never
erased. Testing a learned parent and child remains two evaluated hypotheses.
New post-hoc cohort views are exploratory looks, not additional confirmatory
successes. A renamed copy or unchanged cached replay adds no new hypothesis.

Before any Workbench-triggered validation is allowed, implement one shared serialization lock
around reserve-count/evaluate/append for CLI, weekly and future UI requests;
durable attempts must count confirmation access even if the process fails
after opening data but before completing a report. Disable unrestricted
`--rerun` in the product path. Cache completed exam decisions; diagnostic
reruns are explicitly non-gating. For `awaiting_exam`, predeclare the next
eligible information date/sample rule, suppress interim numeric feedback and
record every look. Do not keep peeking until a result passes.

V1 integration can be **catalog + discovery result viewer + frozen spec export**
for the existing factory owner to run. The next step is one private inbox
consumed by that owner with the shared lock, and immutable result exports back
to the UI. If it is offline, validation waits. Do not deploy Git branch
switching or a second ledger writer inside the production API. Moving factory
ownership from Mac to VPS is a separate migration, only if usage warrants it.

The historical exam has acknowledged prior exposure. It must be labeled as
such. After selecting a protocol, freeze a genuinely future evaluation window
and analyze it at its prespecified end. No tool or UI can manufacture an
untouched historical holdout from already inspected data.

### Swing direction: one family first

Prioritize **the existing daily-EMA recovery-swing family** as a testable lead,
because it already has an execution engine, comparable failures and evidence
suggesting slower response. Do not assume profitability, and do not start eight
new families. Its current trigger still uses 15-minute bars; a daily setup name
does not make entry timing end-of-day or low-attention.

| Potential family | Recommendation |
|---|---|
| Daily-EMA recovery / failed breakdown recovery | First bounded research protocol; reuse `RecoverySwing` and compare a fixed baseline with one slower exit hypothesis |
| Pullback in established relative strength | Next candidate only if the first protocol suggests trend context matters; existing `rel_strength`, `trend` and `trend_slope` are reusable |
| Consolidation continuation | Defer a new family until the existing family cannot express the question; define consolidation without future pivots |
| Post-catalyst continuation / post-earnings drift | Prospective context first; historical event time, revisions, earnings timing and surprise baselines are prerequisites |
| Sector/theme momentum / regime-dependent swings | Add one price-derived feature after measuring missing value and incremental value; freeze theme membership as of time |
| Intraday VWAP / opening-range refinements | Lower life-fit priority; current inspected evidence does not justify more indiscriminate tuning |

`max_sessions` already accepts any positive integer; the 1–3-session range is
in the weekly prompt, not a parser maximum. Thus 16-day holds do not require a
new duration engine. The missing work is **valid evaluation and an appropriate
entry/exit/risk contract**, not changing one integer or presenting 16 as tested.

Before evaluating longer holds:

1. Freeze one coarse primary horizon, for example five trading sessions, with
   1/2/4/8/16-session forward returns as explicitly exploratory diagnostics.
   If a diagnostic selects another horizon, it is a new hypothesis. Expand
   discovery-path calculations beyond the currently implemented next-session
   close; horizons without enough in-window data stay censored/unavailable.
2. Reserve sufficient **in-period outcome room** at every boundary for the
   longest hold. Use a predeclared entry cutoff/embargo and report excluded and
   open trades for candidate and random baseline. Never load October prices
   to complete a September discovery trade. Warmup comes only from earlier
   bars. Isolate the two confirmation halves' outcome windows: current code
   assigns by signal date and can score a first-half signal using a second-half
   exit, while still-open trades at the overall cutoff are omitted.
3. Version a dependence-aware uncertainty protocol for holds overlapping
   weeks, such as shared-calendar blocks at least as long as the maximum hold
   with sensitivity to longer blocks. Weekly entry clustering alone is weak
   for 16-session positions. Report effective clusters, not just trade count;
   low counts may remain inconclusive under the current sample gates.
4. Use identical horizon, side, universe, entry window, risk and cost rules for
   matched-random comparisons. Report overlapping exposure; a random-entry
   diagnostic is not a capital-constrained portfolio. Measure price returns
   versus SPY as well as R so very tight intraday stops do not make a slow
   effect look large solely through the denominator.
5. Preserve old engine/spec results. Adding daily-ATR risk or a daily-close
   exit is a versioned optional rule with next-observation execution, not a
   silent change to old recovery trades. Actual daily-bar families need a new
   supported timeframe path; current `timeframe` must divide 30 minutes.
6. Reconcile factory inferred whole-ratio splits with charts' corporate-action
   basis before live parity; freeze the adjustment policy. Handle holidays,
   early closes, missing bars, delistings, overnight gaps and dividends
   explicitly. The journal-selected universe limits generalization.

Attach life-fit metadata to each candidate: decision cadence, required response
window, expected holding sessions, overnight exposure, monitoring dependency,
number of simultaneous names and whether missing a notification matters.
Backtest viability and practical availability get separate verdicts.

## 8. Macro and catalysts: record useful evidence before buying history

Every feature needs an availability class and a manifest: provider, identifier,
units, transformation/version, event time, publication/update time if supplied,
first observed time, applicable release vintage, missingness and coverage.
“Available now” is not “known historically.” A market packet assembled over
several seconds contains several source times; record the interval and each
input's age instead of pretending the whole packet is simultaneous.

| Input | Historically backtestable in this repository? | Live-capable / prospective status | Recommendation |
|---|---|---|---|
| SPY and core-stock price trends/RS | Yes within the factory's cached dates and causal definitions; inspect missing sessions | Current packet/chart paths exist | First research features; freeze dataset and universe |
| QQQ/IWM/RSP, sectors, GLD/USO/UUP/TLT | Price-derived history is feasible, but not all are factory-loaded or feature-exposed | Current packet universe includes these price proxies | One bounded daily-context adapter later; distinguish price proxies from spot commodities, dollar index or macro releases |
| Sector/theme membership | Current manually selected buckets are not a historical membership database | Freeze membership prospectively with each decision | No survivorship-free sector/theme backtest claim |
| VIX and 10Y | No verified point-in-time factory dataset | Packet uses yfinance daily gauges without returned source observation time | Descriptive until time, units and freshness are fixed; normalize yield changes in basis points |
| 2Y, yield curve, CPI/jobs values | No existing integrated feature source | New dataset needed | Defer; use released vintages and publication lags if justified |
| CPI/FOMC/jobs calendar | Not currently integrated into packets | A small sourced, versioned event calendar is sufficient | Start with dated official-source notes; no invented surprise series |
| Earnings | Current Tradier calendars contain dates/status, not reliable time-of-day or historical announcement vintages | Events tab and cache exist | Event-risk context now; historical PEAD needs richer evidence |
| News/catalysts | Vendor history exists; repository has no revision/coverage archive adequate for causal labels | Existing fetcher can supply prospective evidence | Save article versions used for decisions first |
| OI, option walls, expected move | Recorder history begins recently according to repo docs; actual DB coverage was not audited | Current chains and daily recorder exist | Record context; do not backfill old decisions from current chains |
| Full-market breadth / point-in-time constituents | Not supplied by a watchlist's green percentage | Watchlist breadth is available | Keep the label narrow; defer broad-universe data acquisition |
| Policy/geopolitics/theme labels | No causal historical taxonomy/dataset | Prospective human/agent coding is feasible | Freeze evidence and predictions; treat historical LLM labels as exploratory |

FRED's default real-time period answers what is known **today** about the past;
ALFRED-style queries can retrieve prior vintages. That is useful if macro
values become a research feature, but date-level vintage selection alone does
not prove a value was available before an intraday decision. Preserve the
release timestamp and a conservative availability lag too.
[Source: FRED real-time periods](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html).

Alpaca documents historical Benzinga news back to 2015, and its endpoint sorts
by updated date. Neither claim establishes complete ticker coverage, original
article revisions, or this account's historical entitlement. The present
fetcher exposes `created_at` and discards update time, so querying an old date
today is insufficient proof of the original article text.
[Sources: Alpaca historical news](https://docs.alpaca.markets/us/docs/historical-news-data),
[news endpoint](https://docs.alpaca.markets/us/reference/news-3).

### Catalyst V1

At A1, preserve exactly the returned headlines/summaries and retrieved evidence
used in each plan. Include URL, provider article ID, original publication time,
provider update time where available, observed time, payload hash and truncation
status. Do not claim a capped/HTML-stripped payload is the full raw article.
Preserve the available raw provider payload privately when permitted; a URL
alone cannot reproduce an article that later changes.

After recurring news use is demonstrated, add an incremental collector for the
small watchlist/broad tape with an overlapping update window. Deduplicate by
provider ID **and content hash**, append changed versions, and record queried
windows, page exhaustion, truncation, errors and missing content. “No articles
returned” is not equivalent to “no catalyst existed.”

The first taxonomy should be small: scope (ticker/sector/broad), affected
assets/themes, event type (earnings/guidance/analyst/M&A/contract/product/
regulatory/legal/macro/geopolitical/other), and evidence-backed facts. Themes
such as AI, semiconductors, defense, energy and crypto are tags, not separate
engines. Store source excerpts or field references for every factual label.

Sentiment is optional, nullable and target-specific. “Positive earnings” and
“positive expected price reaction” are different assertions. Catalyst age is
deterministic from a specified publication time. Novelty and independent-story
count require versioned grouping rules and a known comparison window; report
unknown when the corpus is incomplete. Ten syndicated copies are not ten
independent catalysts.

Each classification stores article-version hash, taxonomy/prompt version,
model identifier, output, confidence/abstention and classification time. A
new classifier writes a new classification; a historical run binds one frozen
classification set. **A classification generated tomorrow was not usable
today**, even when its article was published yesterday. LLM knowledge of
later outcomes can also contaminate historical labels despite a frozen prompt;
prospective classification is the clean first experiment.

Only buy/backfill historical news after a prospective question repeatedly
depends on it, a sample coverage/revision audit passes, and the expected
incremental value beats the data/maintenance cost. Do not build historical
sentiment first just because the endpoint accepts a start date.

## 9. Market theses and the Thesis Referee

### Thesis capture and versions

Reuse the local media-writing/transcription pattern and private storage from
captures. Keep broad beliefs out of account-specific `TradeCapture` rows and
out of the mutable AI Buildout JSON. Text-first is enough to prove the thesis
workflow; longer audio needs an explicit size/duration/job contract rather
than silently lifting the trade recorder's 30-second limit.

Preserve raw text/audio and its receipt time. AI produces a **draft structure**:
core claim, horizon, sourced facts, Isaac's interpretation, transmission
mechanism, beneficiaries/losers, assumptions, strongest counterargument,
expected price behavior, invalidation and confidence. The user confirms what
represents their belief. AI-added statements remain attributed to the AI.
An unclear claim remains a draft, with missing information shown.

Each accepted version points to its predecessor, identifies new evidence and
explains changes in claim/confidence. Do not edit v1 when v2 is created. Old
predictions still mature and remain scored; withdrawing or replacing them is
an additional event, not a way to erase a miss.

### Make predictions executable

A prediction freezes instrument and benchmark, statistic/operator/threshold,
start observation, trading-calendar convention, horizon, data source and
price/return basis, evaluation rule, confidence, expiry and missing-data policy.
Two typed predicates suffice initially: **relative close-to-close return** and
**close above/below a frozen level**. Sector rank, “remains above throughout”
and natural-language event outcomes wait for explicit evaluators.

Example: “Over the next five completed trading sessions, XLE's price return
exceeds SPY's by at least 0.5 percentage points, measured from the first common
regular-session close after this prediction is accepted; 60% confidence.”
The threshold and confidence are illustrative, not a recommendation. Record
both starting closes when they become available and evaluate at the fifth
subsequent common close. Use split-consistent price returns, or a separately
supported total-return definition; never mix them. Missing final observations
produce pending/unavailable, not an automatic failure or success.

Ten-day sector rank requires a universe and ties/rank definition frozen at
creation. A 20-day thesis expiry requires a terminal review even when no trade
was taken. Multiple horizons from one thesis are related observations, not
three independent successful theses.

| Desired lesson | Evidence required before saying it |
|---|---|
| Direction was right but duration overestimated | Original signed forecasts at predeclared horizons; terminal and intermediate outcomes across several thesis episodes |
| Entered too early despite a useful thesis | Thesis timestamp, frozen objective confirmation and actual/paper entry timing; matched subsequent paths, not hindsight optimum |
| Exited after one adverse day while the thesis remained valid | Dated exit reason, contemporaneous predicate state and price path; label “exit before recorded invalidation,” not “panic,” unless the user says so |
| Kept rationalizing invalidated theses | Original invalidation observed, subsequent held/revised decisions and timestamps; count revisions after invalidation, retaining counterevidence |

Use accuracy, return/rank errors and Brier score for genuinely probabilistic
binary predictions, with a frozen simple base-rate comparator. Show counts of
matured, pending, cancelled-but-still-scored and unavailable predictions. Do not
derive personality labels from a handful of winning/losing trades.

### Referee: a mode of review, not a second autonomous platform

Input: original thesis and plan versions, explicit assumptions/invalidation,
new source evidence and current market facts. Output: what still supports the
thesis, what weakens it, each predicate's state, whether the narrative remains
plausible, whether this particular trade still meets its frozen rules, and
whether a confidence change is supported. Cite evidence and identify unknowns.

The backend decides numeric predicate states; the agent explains and challenges
the interpretation. “Oil down today” is neither automatically thesis-fatal nor
irrelevant. Compare it with the actual horizon and criterion. If the thesis
survives but the trade's stop fired, the trade is invalid under its original
plan. A compelling new story cannot revive that trade retrospectively.

The referee initially cannot move stops or alter positions. A proposed change
requires a new timestamped decision with a reason. Keep original-rule paper
outcome and amended-management outcome separate when later supporting
discretionary management comparisons. No silent confidence inflation.

## 10. Morning intelligence and Shadow Isaac

### Morning pipeline

1. At approximately **08:50 America/New_York**, a calendar-aware finite job
   assembles the deterministic packet, bounded watchlist context and any
   already-supported events/levels. Record start/end times and the actual
   freshest observation per source. On holidays, record no-session status.
2. Freeze that packet. Retain missing and stale sections. A premarket gap is
   current premarket price versus prior close; the current packet's `gap_pct`
   derives from the session open and may be absent before it opens. Do not
   present regular-session RVOL or ORB as known at 08:50.
3. A bounded agent adds fresh public-source research where useful, retaining
   URLs, retrieved evidence, publication/update and retrieval times. This
   extends the information cutoff: freeze the full augmented input **before**
   accepting a decision. Web unavailability is an explicit gap, not a reason
   to invent a calendar or fail existing plan monitoring.
4. Generate the short human brief and zero to three candidate plans, validate
   them through the backend and save TAKE/WAIT/SKIP before any future trigger.
   Run once per session/policy; a later rerun is a labeled revision.
5. The deterministic monitor watches armed plans. The model is called again
   only for a scheduled review or a meaningful, specifically permitted event.

Reuse [market_report.md](../backend/prompts/market_report.md)'s source discipline
and broad-market-versus-watchlist distinction, but shorten its current 13-part
output. Human-facing output:

- **MARKET TAPE:** two to four sourced factual bullets, with freshness/gaps.
- **IMPORTANT NEWS:** headline, what happened, interpretation, affected assets
  and source link. Facts and implications are visibly different.
- **SETUP BOARD:** zero to three cards with bias, catalyst if present, objective
  trigger, invalidation/no-trade condition, reason and confidence label.

“No clean setup” is a successful run. Show active theses, active strategies and
near-trigger signals only when those services actually exist and are current.
Options context is optional and bounded; do not fetch every expiration for
every symbol to fill a morning report.

### Written shadow policy

Freeze one policy for the first observation window: a small named universe,
underlying long-only practice, liquid names, explicit evidence/catalyst when
claimed, relative strength measured by a stated formula, objective entry and
invalidation, price guard, bounded exposure, finite hold and low attention
requirements. These are experiment constraints, not assumed profitable rules.

Avoid forced daily entries, chasing beyond the frozen price guard, headline-only
TAKE without a trigger, unplanned averaging and unsupported options liquidity.
Default to WAIT/SKIP when required data or an executable rule is missing. Cap
three new plans/day, three concurrent paper positions and five watched symbols,
subject to the existing alert budget; count stop/target watchers against it.
One plan per symbol/actor at a time keeps the first accounting tractable.
The setup-notification cap does not suppress exits or operational failures for
positions already open; show those separately and measure total interruptions.

Before committing a choice, the agent can inspect the shared market packet,
approved context and thesis versions, but not Isaac's current choice. Record
the entire final decision and concise rationale, not a demand for hidden
chain-of-thought. Model/prompt/policy changes start labeled cohorts.

The agent makes a bounded preparation decision and may register an objectively
conditional plan. It never needs to stay conversationally awake to enter or
exit. Provider failure, malformed output, exceeded budget and no setup are
different recorded states.

### Independent comparison design

On a small set of **preselected opportunities**, present Isaac the same factual
card without the agent verdict. He can tap TAKE/WAIT/SKIP or ignore it. Record
his first choice, then reveal the agent's committed choice. Never require a
pre-trade essay. Define a deadline; late choices remain useful but are labeled
late, and seeing the agent first makes the comparison assisted rather than
independent. A journal fill alone does not prove a precommitted independent
decision.

The opportunity universe must include non-trades and rejected opportunities,
not just tickers eventually traded. Use a predeclared morning watchlist or
deterministic candidate rule; do not select only winners for review. Report:
Isaac TAKE only, agent TAKE only, both TAKE, both SKIP, WAIT combinations,
opposite/different-plan decisions and unobserved. “Agreement” needs a definition
of direction, trigger and time window; two bullish narratives are not identical
trade plans.

For both-rejected opportunities, use a predeclared forward-return diagnostic
or a frozen benchmark plan. Do not invent a hindsight entry/stop to fabricate
counterfactual R. Separate actual user option outcomes from common underlying
paper outcomes. Any apparent benefit of agreement is initially observational;
turn it into a frozen filter on later opportunities before claiming it helps.

## 11. Paper execution, targets and operational truth

### First executable policy

Support one simple plan: **regular-session 15-minute close beyond a frozen
level, a fixed protective stop, one target and a maximum of two trading
sessions in the position**. Entry expires at a specified session/time if it
never triggers. Use one normalized initial-risk unit and long underlying
shares. This tests the process with existing alert semantics; it does not claim
to reproduce the factory recovery family's entry logic.

The paper engine must distinguish these timestamps: decision received,
plan activated, market condition occurred, monitor detected it, simulated
order became eligible, simulated fill time, and notification delivered.
Current close alerts finalize after a 30-second lateness allowance. Therefore
filling at the already-past next 15-minute open would overstate execution.

For V1, use the **first full one-minute bar whose start is strictly after the
trigger was durably detected and accepted**, and simulate its open with adverse
slippage. Persist that eligible bar before waiting for it. The bar can be read
after it closes; the order rule must have existed before its open. Reject an
open through the stop, beyond the frozen entry guard or at/beyond the target.
Call it a simulated bar fill, not a real executable quote. Freeze a cost model
and show base/triple-cost outcomes. Do not allow an agent to submit a favorable
historical price to `paper_enter`.

For a long position, keep the original stop and target resting from entry,
including the entry minute after its opening fill. A subsequent bar opening
below the stop exits at that open with adverse
slippage, not the stop price; a bar touching both stop and target resolves
stop first and is flagged ambiguous. Target-only touches fill no better than
the target. A time exit uses a predeclared close/order convention, including
early closes; the entry session counts as session one of the two-session hold.
Missing required bars suspend exact accounting and disclose an
unresolved interval. No forward-filled prices or imaginary zero-volume fills.

Reuse pure execution primitives from `factory_rules` where the exact semantics
match (costs, gap/stop-first handling); add the explicit delayed-entry adapter
and its own execution version. Do not shoehorn discretionary plans through a
fake factory family or change historical family fills to match this experiment.
When a factory family later goes live, feed its own `on_bar` implementation and
prove replay parity with `run_candidate`; distinguish model execution from
actual delayed live fill assumptions.

### Restart and delivery behavior

An accepted plan arms its watch atomically or remains visibly unarmed with a
retryable operation. Plan-owned alerts must be distinguishable from manual
chart alerts. Freeze source level, direction, generation and event facts; a
dragged level or rearmed alert cannot silently change the plan.

Each trigger/entry/exit has a unique operation key and a conditional transition.
Restarts reconstruct state from durable events. If there was a monitoring gap,
record it. A trigger discovered after its allowable delay becomes a missed
opportunity, not a backdated live paper entry. For positions already open,
recovery may replay persisted orders over recovered bars, explicitly marked
reconstructed; if order/path sequence is unknowable, mark the outcome ambiguous
or unavailable. The current today-only alert sweep is not sufficient alone.

Reuse ntfy and its outbox conventions: economic events are recorded once;
delivery is at-least-once and may duplicate after a crash. Include the event ID
and deep link in the notification. “ntfy accepted” and “Isaac saw it” are
separate evidence. A delayed entry alert must say it is late and cannot imply
the old entry is still available. Preserve plan-event evidence even if the
associated chart alert is removed; retire referenced plan watches rather than
letting the current delete route erase their only record.

Show watcher health, feed freshness, last evaluation and disabled/paused state
on Today. A quiet day must be distinguishable from a stopped monitor. Reuse
existing operational alerts for meaningful failures. Do not send one phone
message per poll or per irrelevant headline.

### Objective targets and options separation

Use `compute_levels` for prior session/week extremes, confirmed swing levels,
premarket and opening-range levels; chart calculations for VWAP/ATR; and
`options_implied`/positioning for eligible current context. A pivot needs its
confirmation bars, and an opening range does not exist before its window ends.
Freeze the value and provenance, not a pointer that later resolves to today's
level. ATR fractions and R multiples are policy-derived candidates; options
walls and max pain retain their documented inference limitations. An implied
move prices magnitude, not a guaranteed boundary or direction.

The agent selects among valid candidates or abstains. A target with insufficient
remaining reward/risk after a gap or delayed alert fails the plan price guard.
Recompute reward/risk using the actual simulated entry while retaining original
risk and plan versions; do not move the target merely to make the ratio pass.

Defer option execution until underlying forward evidence and workflow quality
justify it. A future expression record binds the same underlying decision to
stock or a specific option, DTE, strike/delta, bid/ask times and spreads, IV,
premium, liquidity and exit rules. Evaluate selection/fill/decay separately
from underlying signal quality. Current chain context and daily OI are not an
intraday option execution history. Never infer an exact option loss from an
underlying stop or convert historical premium returns into R without risk.

## 12. Anti-hindsight and evaluation rules

The minimum invariant is:

**Inputs available → decision durably saved → order eligible → market outcome.**

An artifact violates prospective evaluation if any dependency was first made
available after the relevant cutoff, even if it carries an older event date.
Store event, publication/update, observation, decision and evaluation times.
Freeze code/protocol/data/price basis and the exact values actually shown.
Hashing a mutable URL or trusting the user's device clock is insufficient.

Corrections create versions and retain the original result. As-observed and
later-corrected market data can support separate reports; a provider correction
never rewrites what the agent saw. Model revisions, missing news, unobserved
human choices, late uploads, unfilled plans, stopped services, ambiguous fills
and pending horizons all stay in the denominator where applicable.

Use two independent state dimensions:

| Dimension | States and meaning |
|---|---|
| Research evidence | Exploratory → Frozen → screen/confirmation/exam verdicts → future evaluation. Preserve current factory verdicts; “factory passed” always names protocol, data and limits. |
| Operational permission | Read-only → **Practice paper** → forward trial of a specified policy → disabled/retired. Practice can precede factory validation and remains labeled unvalidated. |

Do not force “Research → Practice → Factory Validated → Live” into one ladder.
A discretionary thesis may have no backtestable factory specification. A
factory-pass strategy may be unusable during work. **Live eligible is a future
human governance decision**, requiring separate execution/risk/reliability and
prospective evidence; there is no automatic transition in this roadmap.

### Measure four things separately

| Layer | Measures | Interpretation |
|---|---|---|
| Operations | On-time runs / eligible sessions; frozen plans; trigger-to-detection and delivery delay; monitored-time coverage; duplicates; missed/stale signals; fill ambiguity; recovery failures | Whether the system did what it promised |
| Life fit | Useful alerts / rated alerts and rating coverage; fraction understood within 60 seconds; review minutes; missed response windows; weekly usage | Whether it earns attention while Isaac works |
| Decisions and theses | Plan adherence; TAKE/WAIT/SKIP counts; frozen versus amended management; matured prediction scores and base rates; independent versus assisted comparisons | Whether the process and beliefs are measurable |
| Underlying outcomes | Net R with frozen denominator, price return and excess over a specified benchmark; MFE/MAE; hold duration; loss tails; drawdown definition; costs; concentration; cohort and missing counts | Descriptive forward evidence first, not alpha after a few trades |

Keep profitable outcome and good process separate. “Useful alert” is a user
rating that it was relevant, understandable and actionable at receipt, whether
the trade won or lost. Preserve unrated alerts; do not report usefulness only
over an undisclosed hand-picked subset.

For research, retain matched random entries, uncertainty clustered on shared
calendar exposure, year/regime/ticker breadth and sensitivity to the best
ticker/day. All filters and comparisons are recorded. Regime definitions must
be causal and frozen; retrospective labels cannot enter earlier features.
For forward discretionary comparisons, match opportunity and information
window, and separate policy/model versions. Do not compare a cherry-picked
agent stock cohort against all of Isaac's historical options trades.

No first-month significance gate based on returns: small, correlated samples
remain descriptive. Pre-register a later test's endpoint, calendar end,
minimum information/coverage and decision rule; if insufficient observations
arrive, report inconclusive rather than keep changing the test. Keep both
execution-qualified samples and all-intended-opportunity coverage visible.

## 13. What should deliberately wait

| Component | Decision and reason | Gate for revisiting |
|---|---|---|
| Full interactive Workbench | After the forward loop; it can increase building and parameter mining | Repeated concrete research questions from use, plus trial/accounting protections |
| Eight swing families and broad scanner | One existing family first | Evidence that the family/universe cannot express the chosen hypothesis |
| Historical LLM sentiment and news purchase | Record prospectively first | Named valuable feature, verified historical revisions/coverage and justified cost |
| Rich macro terminal / causal knowledge graph | A few observable inputs and sourced notes suffice | Repeated decisions blocked by one specific missing variable |
| Long voice-thesis studio | Existing trade voice is already built; text tests the thesis need | Sustained thesis use plus real friction with text/short clips |
| Fully autonomous management / agent committees | Frozen deterministic management first | A predeclared forward comparison can test one management amendment policy |
| Live orders, broker paper account, autonomous options | Local underlying paper events are sufficient for first evidence | Separate explicit execution project after evidence and reliability gates |
| Redis/Celery/Kafka, vector DB, separate microservices | Existing host, SQL database, files and worker runtime cover the load | Measured bottleneck that the current runtime cannot solve |
| New journaling system, template library or chart engine | Existing captures/review/charts already own these | Extend the owning surface only for a demonstrated gap |
| General authentication/multi-user SaaS | Private single-user product | Only scoped agent capability enforcement is needed now; public access is another project |
| Psychology scores, AI confidence gauges and automatic “edge” badges | Easy to produce and difficult to justify | Operational definitions, sufficient prospective evidence and uncertainty |
| More unrelated chart polish / analytical tabs | Low expected value while nobody is using the decision loop | A recorded recurring obstacle to preparation, alert comprehension or review |

The existing options recorder may continue gathering its bounded history.
This proposal does not disable useful infrastructure or undo completed chart
work. It recommends spending new build time only on the next observed obstacle.

## 14. Phases and explicit gates

| Phase | Scope | Exit gate | Stop/defer rule |
|---|---|---|---|
| 0 — Evidence contract | Choose one practice policy, bounded universe and session schedule; identify missing operational acceptance | One unambiguous example plan and simulated outcome, with time/cost/source rules; confirm the intended private runtime | No new data vendor or framework |
| A — First forward loop | A1 frozen decisions, A2 alerts/paper outcomes, A3 short daily review and independent choices | One real forward trigger and paper lifecycle preserved across restart, phone receipt checked, review retrieves original evidence | If not working by day 10, cut UI/automation scope; do not start Workbench |
| B — Use it | Ten or more eligible market sessions with the same versioned policy; bounded manual morning preparation is acceptable | Measured attention/usefulness/coverage; a written list of actual shortcomings | Stop discretionary automation if data or notifications are unreliable; fix the narrow failure |
| C — One research or belief improvement | Choose either guarded discovery Workbench + one swing protocol, or thesis predictions/catalyst collection | A frozen question with supporting data and an evaluator; no new subsystem just for completeness | Do not start all three in parallel |
| D — Validated forward evaluation | Exact factory family parity or frozen discretionary policy evaluated prospectively | Prespecified horizon/sample/coverage criteria, honest cost and dependence accounting | Inconclusive is a valid end state; no automatic real-money eligibility |

Practical budget: aim for **no more than eight focused engineering days in the
first month**, with the rest used for observation. These are scope limits, not
estimates of guaranteed completion. If a slice expands, shorten it before adding
another agent or feature. After day 14, only reliability/data defects that block
the loop should interrupt the observation period. No automatic roadmap march.

### Source inventory and reconciliation

The proposal reads the working agreement, README and all `docs/agent/` topics
(architecture, domain, environments, jobs, feature map, verification, workflow
and engineering roadmap), plus the requested product, charts, workspace,
factory, Strategy Lab metrics, analytics and symbol-info documents. Relevant
router, engine, model, MCP and frontend implementations are linked above.
It also inspects factory specs/ledger, the October 4 and preceding September
29c/29d reports, generated latest run artifacts, and local archived packets.

Important planning reconciliations: C3.6 exists despite older product text;
News/Overview were placeholders in the inspected checkout, but the News tab
has since landed on main; the AI Buildout workspace is editable context, not an immutable
thesis system; the factory catalog exists; paper execution does not. Built
capture still has its documented human acceptance gates. The older
factory “paper only after confirmation” rule applies to validated-family
forward testing; adding Practice requires its own explicit label and permission
state and does not silently relax that rule.

## 15. Recommended first three implementation slices

These are **assignment-sized implementation contracts**, to select one at a
time after this proposal. New file/model names are suggestions. Each has one
owner; coordinate migrations against the current head and recheck concurrent
chart work before editing shared files. All runtime slices follow the repo's
verification agreement, including full local verification before completion,
appropriate Postgres/migration CI and browser checks. Report fixture, provider,
deployment and human-observed evidence separately.

### A1 — Save and retrieve one executable practice decision

**User outcome:** a human or agent can save TAKE/WAIT/SKIP; a TAKE yields a
readable, immutable paper plan card with exactly the facts used. Reopening it
tomorrow shows the original plan, even if the packet or levels changed.

**Scope:** one typed `DecisionRecord`, one additive migration, a compact server
evidence envelope, idempotent create/get/list, and a Today card/detail view.
Use existing packet/ticker/level adapters for at most three candidates. Freeze
required price facts and their source times; incomplete optional context stays
missing. Add only read/context and `record_decision` MCP exposure needed for a
manual bounded morning session. Do not schedule or run a model automatically.

**Likely files:** `backend/app/models.py`, one new Alembic revision;
`backend/app/engine/packets.py`, `news.py`, and `chart_levels.py` adapters;
proposed `backend/app/engine/decisions.py` and
`backend/app/routers/decisions.py`; `backend/app/main.py`;
`backend/mcp_server.py`; `frontend/app/page.tsx`, a small decision-card component
and typed client. Extend capture references, not the capture form itself.

**Reuse:** `captures` receipt/idempotency/media conventions, the existing
calendar, packet calculations and chart facts; existing card styling and
missing-data presentation. No separate packet ingestion framework.

**Do not include:** triggers, fills, options execution, long voice, a thesis
editor, a general article database, factory runs, web scraping, a new nav suite,
or a second human plan/template store.

**Acceptance criteria:**

1. Identical operation retries return one saved record; changed payload under
   the same key conflicts. Stored decisions cannot be PATCHed or backdated.
2. An accepted TAKE has the supported trigger, stop, target source, expiry,
   hold, entry guard and cost policy; unsupported/inconsistent plans fail
   with a specific reason. WAIT/SKIP can save without fictional prices.
3. Required source observations are no later than the decision cutoff;
   future/stale/missing price facts cannot produce an armed-capable plan.
   Regeneration cannot overwrite an earlier evidence envelope. Recording
   failure cannot return “saved.” Calendar/feed/basis metadata are explicit.
4. Desktop and 390px phone view display the same original evidence and link
   to Charts. A human walkthrough retrieves and explains a saved plan in
   about 60 seconds. This does not claim five-second trade capture acceptance.
5. No journal fills, trades, accounts or factory ledger are mutated by a plan.

**Verification:** isolated API/persistence tests for retries, concurrency,
timestamp ordering, later packet changes, split basis and malformed plans;
calendar holiday/early-close fixtures; Postgres constraint/migration checks;
browser save/reload/failure states. A real read-only provider snapshot checks
source time/units separately before plans are used prospectively.

**Dependencies:** existing private backend and chart providers; no factory
pass, new vendor, thesis system or scheduled agent. Use one manually prepared
example as the first end-to-end acceptance artifact.

**Why this first:** it starts collecting anti-hindsight evidence immediately
and creates the one contract all later automation needs. Another analytical
tab cannot answer what was actually decided before the outcome.

**Acceptance status (2026-10-07, [merged PR #143](https://github.com/imizik/TradeJournal/pull/143)):** A1 storage/API, durable server-owned market contexts, idempotency, Today decision entry/detail and local MCP adapter are on main. PR #143 reported successful Backend, Frontend, Browser, Postgres parity, Ubuntu package/systemd and Screenshots checks. TAKE validation binds prices to completed raw Alpaca minute-bar facts in the saved context, requires a declared freshness limit (capped at one day), explicit entry guard and versioned nonnegative cost parameters. The selected [P0 practice policy](agent/practice-policy.md) fixes the universe, manual schedule, cost assumptions and one synthetic plan/outcome; its real read-only Alpaca check found a completed SPY IEX minute bar with UTC source time before request time. A1 still does not enforce all P0 operating limits or arm a plan; its `practice-long-15m-v1` hash covers the A1 schema, while the complete `shadow-isaac-p0-v1` operating version/hash is an A2 arm gate. A disposable local 390px browser walkthrough saved and reopened one WAIT with explicit unavailable-provider context and no horizontal overflow; this did not validate TAKE or measure human comprehension time. Full local verification passed (1,406 backend tests, 177 browser tests); the human comprehension timing and provider-backed TAKE save remain unobserved.

### A2 — Watch that plan, alert once, and paper-track its outcome

**User outcome:** Isaac closes the browser and works. A saved plan's objective
condition fires; the phone opens its frozen card, and the app tracks one paper
entry and fixed-rule exit without requiring him to watch candles.

**Scope:** the one 15-minute-close, long-underlying policy in section 11; an
explicit arm action; typed `DecisionEvent` storage and a position projection;
fixed stop/target, two-session time exit and entry expiry. Shared level monitor
observations feed a pure paper state reducer with durable checkpoints. No LLM
is involved in evaluating or executing the rule.

**Likely files:** `backend/app/engine/level_alert_monitor.py`, `level_alerts.py`,
`ntfy.py`, `chart_feed.py` integration, `backend/app/routers/level_alerts.py`,
decision service/router, `backend/app/models.py`, one event-table migration;
proposed `backend/app/engine/paper_execution.py`; Today card/timeline;
`backend/tests/test_level_alerts.py` and new focused paper tests.

**Reuse:** existing stream/calendar/budgets, firing identity, delivery outbox
pattern, and compatible pure cost/gap/stop-first primitives from
`factory_rules.py`. Keep paper positions outside FIFO and imported backtests.

**Do not include:** new strategy families, daily triggers, model-managed stops,
averaging, partial exits, short selling, options, broker integration, portfolio
optimization or full historical replay UI.

**Acceptance criteria:**

1. With no browser open, a fixture trigger yields one durable trigger and one
   position. Replaying ticks/bars or restarting at each transition never
   duplicates economic events. Arm failure is visible and retryable.
2. Entry occurs only under the declared post-detection next-minute rule and
   price guard. Stop/target collision, gap through stop, entry beyond target,
   no trigger, expiry, missing bars, early close and split cases have expected
   outcomes. Report the frozen A1 trigger-minus-stop planned-risk denominator, simulated entry-to-stop exposure, and net planned R with the cost version.
3. Alert rearm/drag/delete cannot rewrite or erase original plan/event facts.
   A multi-day monitoring gap cannot create an unmarked backdated entry.
4. The phone message links to the exact plan/event. Delivery retry may resend
   the message but never repeats the simulated order; stale alerts say so.
5. One controlled live trigger is observed on the phone on the private origin,
   followed through its paper state and recovery after restart. Record actual
   receipt separately from ntfy acceptance. If markets provide no suitable
   organic setup, use a clearly segregated operational probe, excluded from
   strategy outcomes, then wait for an organic event.

**Verification:** pure adverse-path fixtures, seeded API/browser timeline,
cross-process/restart/idempotency tests, migration/decimal checks, no-journal-
write assertion and a live Tradier→monitor→ntfy→phone observation. Validate
underlying price/fill assumptions; do not describe a fixture or probe as alpha.

**Dependencies:** A1; private always-on API, fresh provider data and working
phone delivery. C5.1's phone observation already occurred; A2 needs its own
observed plan-to-paper lifecycle and does not change C5.2 deployment status.

**Smallest proposed A2 cut after A1 acceptance:** One explicit arm action checks a frozen TAKE against the complete versioned P0 policy (including universe, schedule, source, daily limits, execution and cost rules), stores its canonical policy hash, and atomically stores a plan-owned watch or a visible retryable arm failure. One deterministic worker consumes completed regular-session 15-minute observations, commits a single trigger/missed-trigger event and the next eligible one-minute order intent, then advances one paper position through fixed stop/target/two-session expiry. `DecisionEvent` rows and unique operation keys are the authority; projections rebuild from them after restart. A recovery cursor records the last evaluated provider interval. On restart, a recoverable pending order may be replayed against source bars with reconstruction marked; a detection gap past the allowable entry window records `missed_trigger` or unresolved coverage without backdating an entry. Persist the economic event before enqueueing one plan-event phone notification through the existing ntfy outbox. Delivery can retry, but the phone message deep-links to the frozen card/event and never mutates an event. Keep paper rows and R separate from journal fills, FIFO, actual P&L and factory ledger. One controlled live phone receipt and restart drill are acceptance gates, with any operational probe excluded from strategy outcomes. No scheduled agent, Dots connection or second rule family is part of A2.

**Why this second:** it is the shortest route to the user's actual objective:
the system watches while he works and retains an outcome worth reviewing.

### A3 — Run a daily routine and compare independent choices

**User outcome:** one short morning board and one after-work review make the
loop habitual. On selected opportunities Isaac records one tap before seeing
the agent choice; later he can compare decisions and paper outcomes.

**Scope:** bounded daily preparation using A1's contract, session-level
no-setup/failure records, a 08:50 New York timer, one agent adapter/profile,
and a deterministic Daily Review paper/decision table. Add TAKE/WAIT/SKIP and
reveal controls for common preselected opportunities, plus useful/not-useful
alert feedback. Keep the agent adapter replaceable; use the project's existing
structured model-call approach as the first implementation, with a timeout and
explicit daily budget. No recurring job is created by this roadmap itself.

**Likely files:** `backend/prompts/market_report.md`; decision service/router
and `backend/mcp_server.py`; `backend/app/engine/jobs.py`, `job_runtime.py` and
worker dispatch; proposed finite preparation runner and systemd timer/service;
`deploy/launch.py`/service packaging where required; Today cards and
`frontend/app/daily/[day]/page.tsx` or a separate paper subsection.

**Reuse:** existing packet, ntfy, `JobRun`, systemd conventions, model JSON
validation patterns from the factory, Daily Review layout, A1/A2 records and
the existing private API transport. Keep journal-review calculations separate.

**Do not include:** factory/Workbench writers, automatic policy tuning, a new
model orchestration framework, a web crawler, historical news purchase, thesis
prediction UI, reflection/playbook rewrite, or autonomous position amendments.
Fresh web evidence can be supplied through the bounded agent's existing search
capability; when that adapter has none, show the gap and allow attached sourced
notes. Do not block the daily routine on building search infrastructure.

**Acceptance criteria:**

1. One session/policy run is recorded as completed, no setup, failed or late;
   timer retries cannot quietly create another daily cohort. DST, holidays,
   deadline misses and provider/model failure are explicit. The model's failure
   cannot stop monitoring of existing positions.
2. The bounded agent commits no more than three plans through A1 validation;
   no clean setup is permitted. The brief contains the requested three sections
   and links back to frozen evidence. Its cost and runtime are recorded.
3. Independent mode denies the runner access to human decisions and journal
   activity before its choice, hides its verdict from Isaac until his choice,
   and records reveal/late/assisted status. Unobserved is not SKIP.
4. Review reconciles all opportunities, WAIT/SKIP, expired/unfilled plans,
   paper positions, missing observations, alert ratings and policy versions.
   All counts drill into records. Same-opportunity comparisons use common
   underlying outcomes, not option-versus-stock P&L.
5. Across three real sessions, Isaac can use the morning card and complete the
   review in five minutes or less per session; collect actual timings and
   reasons when he cannot. Returns are descriptive, with sample coverage.

**Verification:** stub-model schema/access-control tests, timer and lane
isolation tests using the existing deployment-test patterns, same-key retries,
missed deadline and zero-plan fixtures, browser choice/reveal/late/nonresponse
flows, reconciliation of report denominators and three observed daily runs.
Do not silently retry paid calls after uncertain completion.

**Dependencies:** A1 and A2 plus an explicitly enabled, budgeted agent runtime.
Until scheduled preparation is verified, a manual morning MCP session can
produce the same frozen records; manual versus automated sessions are labeled.

**Why this third:** repeated use and honest disagreement expose the next real
problem. More research controls before this point would optimize the building
process rather than produce decisions the user can evaluate.

## 16. Proposed first 30 days

Day 1 means the day implementation is selected, not an implied start date or
an instruction to deploy today. Calendar days and eligible market sessions
are distinct. Timeboxes may shift for review/deployment; cut optional scope
instead of compressing observation into a weekend.

| When | Action | Evidence to retain |
|---|---|---|
| Days 1–3 | Select policy/universe; deliver A1; use one existing packet/agent session manually | Immutable plan and abstention examples, source-time checks, phone card walkthrough |
| Days 4–8 | Deliver A2; verify private phone delivery, restart and one paper lifecycle | Technical probe clearly labeled; first organic plans and event timelines |
| Days 9–14 | Deliver A3; use manual preparation until the timer/runner is proven | Daily run status, independent/assisted choices, short reviews and attention timings |
| Days 15–21 | Freeze feature expansion; operate the same policy; resolve only blocking data/reliability issues | All intended opportunities, missed/late alerts, paper paths, no-setup days and user feedback |
| Days 22–30 | Continue collection; conduct two weekly reviews; choose one measured shortcoming for a next slice | Coverage-aware report and a KEEP / CHANGE / STOP decision for this workflow |

### First-month scorecard

The following are **collection goals**, not reasons to manufacture setups or
promises of available market opportunities:

| Measure | Target | Honest shortfall handling |
|---|---|---|
| Complete daily decision records | At least 10 eligible market sessions after A2, including no-setup days | List missed sessions and reason; a late run remains late |
| Frozen agent decisions | 20–30 TAKE/WAIT/SKIP opportunity decisions, with at most three executable plans/day | Lower count is acceptable when eligibility is rare; never lower policy quality to hit a number |
| Useful setup alerts | Aim for five rated useful; at least 80% of delivered setup alerts rated | Show useful/total/rated and latency; zero triggers can still be a valid observation |
| Paper executions | Aim for five organic triggered entries, retain every non-fill; closed and still-open counted separately | No trigger means no trade; probes excluded; extend collection, not a fabricated sample |
| Independent comparisons | At least 10 common opportunities with both timely blinded choices | Unobserved/assisted/late cases remain visible; no filling in Isaac's choice from later trades |
| Evidence integrity | Every accepted plan bound to original evidence; zero duplicated economic events; every outage/missing fill interval disclosed | Any unresolved integrity defect pauses outcome claims and becomes the next fix |
| Attention fit | Median setup comprehension ≤60 seconds; review ≤5 minutes on observed days; two weekly reviews | Report sample and unmeasured days; simplify if burdensome |
| Next build decision | One prioritized shortcoming supported by at least three recorded examples, or a decision to stop | No new feature solely because the roadmap contains it |

Do **not** require a full thesis product or matured 20-day predictions during
this month. If thesis recording is already natural, use dated, frozen sourced
notes as optional context and log predictions for a later evaluator; do not
pretend the first three slices automatically score them. The next thesis slice
can target five matured 5/10-session predictions after its own start date.

At day 30, continue only if the loop is usable, its evidence is trustworthy and
Isaac actually reads the alerts/reviews. If alerts are understandable but fills
are unrealistic, fix execution assumptions. If decisions repeatedly depend on
uncaptured catalysts, add prospective catalyst recording. If a recurring
objective pattern deserves testing, choose the guarded swing/Workbench slice.
If the whole routine is ignored or interrupts work too often, reduce cadence
or stop. **The intended deliverable is a usable body of forward evidence and
one justified next decision, not a finished trading platform.**
