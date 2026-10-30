# Company research workspace — implementation handoff

Status: proposed implementation, not built or activated. Prepared October 30,
2026 against local main commit `05a3049f`. The owner requested a plan to execute
in this same chat after switching to GPT-6.1 Sol, high. This document preserves
the scope and decisions; it does not switch models or authorize activation.

## 1. Product and decisions

Build a personal fundamental-research workspace for selected companies. It
connects financial results, analyst expectations, management guidance, source
documents and the owner's thesis across reporting periods. Think a narrowly
scoped AlphaSense-like workflow, not a trading-signal generator.

The owner explicitly chose:

- Existing subscriptions and free sources first. Ask before any purchase or
  additional paid data/model use; do not assume an existing key includes a new
  endpoint or unlimited usage.
- Start with an empty company list. The owner adds companies in the app. No
  automatic holdings import, preselected portfolio or seeded real companies.
- Plan now, implementation after the model switch and execution instruction.

Default product decisions (no further questionnaire needed):

- Owner-only `/research/companies` and `/research/companies/[symbol]`, named
  **Company Research**. Keep AI Buildout, Research Studio and chart panels.
- Limit initial active coverage to 10 companies; compare at most 3. Document
  the limit in the UI and API rather than adding a configuration subsystem.
- Primary research questions: Is the business improving? What was expected?
  Did it deliver? What changed in the outlook? Does that change my thesis?
- Duet and Dots/Jo are interchangeable research contributors. Store the actual
  actor/provider. No mandatory dual-agent run or model voting. Both may be
  connected later, with separate assignments and receipts.
- APIs supply structured observations; agents supply sourced interpretations
  and proposed extractions. Missing data stays missing.
- No social sentiment, orders, sizing, price predictions, automatic thesis
  acceptance, market-wide scanning, vector database, new chat engine, or
  generic agent framework in this build.
- The v1 comparison is a factual table, not a ranking or investment score.
- AI interpretation arrives through the assignment workflow; there is no new
  in-app paid model call or generic chat interface in this scope.
- A record can be useful without any agent connected. Agent research is a
  supported end-to-end workflow, not a dependency for viewing financials.

## 2. Existing code and constraints that matter

Read these affected sources, not the entire repository:

| Existing area | Reuse and limitation |
| --- | --- |
| `backend/app/engine/symbol_info_financials.py` | Pure SEC quarterly normalization. Uses explicit 80–105-day spans and leaves Q4 gaps. Current selection uses latest comparative filings; it is not a point-in-time archive. |
| `backend/app/engine/symbol_info_financials_feed.py` | SEC ticker/CIK map, descriptive User-Agent, pacing and error handling. Current cache holds normalized data, not per-fact original sources; refresh can wait until the next filing is due. Do not call that cache a current earnings monitor. |
| `backend/app/engine/symbol_info_analysts.py` | Webull targets/ratings/history and unofficial Yahoo estimates/actions. Cache overwritten per symbol/provider. `normalize_yahoo` drops the estimate's absolute period, leaving current/next quarter; accounting basis may be unknown. |
| `backend/app/engine/symbol_info_tradier.py`, `symbol_info_events.py` | Existing earnings-calendar and company-overview readers/cache. Reuse budgeted reads; do not create a second quote/chain service. |
| `backend/app/routers/symbol_info.py`, `frontend/lib/symbolInfo.ts` | Existing chart contracts; preserve response compatibility. |
| `frontend/components/charts/SymbolInfoFinancials.tsx`, `SymbolInfoForecast.tsx` | Existing financial labels, units and source displays; reuse formatters where suitable without enlarging chart panels. |
| `backend/app/routers/research.py`, `frontend/lib/research/store.tsx` | AI Buildout uses one editable JSON workspace. Do not put immutable observations in it or copy its stale-save retry that reapplies a local blob. |
| `backend/jo_research_common.py`, `jo_research_exchange.py`, `jo_research_tools.py`, `backend/app/engine/jo_research.py` | Existing bounded schemas, actor-bound snapshot/outbox exchange, idempotent submissions and app receipts. Reuse patterns; do not disguise Duet as Jo or change existing research jobs. |
| `deploy/duet/README.md` | Current Duet recipe deliberately blocks `jo_*` tools and grants no Jo research submit access. New research access needs an explicit reviewed grant, not reuse of Jo's identity. |
| `backend/app/access_manifest.py`, `access_middleware.py` | Explicit route classification; enforce owner-only access through the real policy, not just hidden navigation. |
| `backend/app/engine/jobs.py`, `job_runtime.py`, `backend/app/jobs/worker.py` | Durable jobs, ownership, interruption handling. Do not build an untracked thread pool. |

Existing tests: `backend/tests/test_symbol_info_financials.py`,
`test_symbol_info_analysts.py`, `test_symbol_info_events.py`,
`test_jo_research.py`, `test_browser_access.py`, and
`frontend/e2e/symbol-info.spec.ts`.

Contracts: [working agreement](../CLAUDE.md),
[domain rules](agent/domain-rules.md), [background jobs](agent/background-jobs.md),
[verification](agent/verification.md), [review policy](agent/pr-review.md),
[Dots integration](agent/dots-integration.md), and the `trade-chart-ux` skill in
SPEC/BUILD mode as appropriate. This plan is based on code inspection, not a
visual audit of an existing Company Research screen.

### Concurrent Claude work

At planning time Claude is implementing position companion, fill interrupts,
and outcome attribution. PR #620 handles typed Telegram questions and is open.
Recheck live branches/PRs before implementation; status here is not a lock.

Keep this feature out of `position_companion`, `plan_nudges`,
`telegram_replies`, `level_alert_monitor`, `exit_habits`, `radar_scorecard`,
`plan_proof`, `copilot_review` and the sync pipeline. Shared `models.py`,
`main.py`, job registration, migrations and navigation will need small additive
edits. Reconcile those edits without reverting siblings. Select the actual
Alembic head at implementation time; never guess a revision or overwrite one.

## 3. User journeys and screen specification

### First use

The list says “Follow a company to track its results and expectations” and has
one Add company action. Adding a supported ticker resolves issuer identity and
queues a bounded initial refresh. Duplicate add returns the existing company.
Unsupported issuers can still have a sourced research record; explicitly show
which automatic datasets are unavailable. ETFs are unsupported in v1.

Removal means **Stop following**: archive the company, stop future scheduled
reads/assignments, preserve history. Re-adding restores the same issuer record.
An explicit permanent-delete feature is outside scope.

### Daily use

List columns: company, next earnings (confirmed/estimated/unknown), latest
material change, last successful refresh, coverage/problems. Sort changes
newest first; do not treat first import or fetch failure as business change.
One refresh action per company and a bounded Refresh all. GETs are stored-data
reads; page navigation does not silently issue provider/model requests.

Company page:

1. Header: identity, last checked, next report, Refresh, Research question.
2. “What changed”: concise observed numeric changes and sourced findings.
   Separate first baseline, revisions, and agent interpretation. Mark reviewed
   without deleting; reading the page does not automatically mark everything.
3. **Results & expectations**: last 8 fiscal quarters available, plus explicit
   gaps; expectations/revisions for identifiable upcoming periods; earnings
   actual-vs-estimate and guidance comparisons when compatible.
4. **Thesis & research**: current owner-authored thesis and up to 5 specific
   assumptions, supporting/contradicting findings, open questions, assignments.
5. Source drawer from every metric/finding: source, URL/accession, relevant
   passage when available, period/basis/unit, publication and retrieval times.

Use two main tabs (Results & expectations / Thesis & research); keep What
changed above them. Tables are the primary view. Add small trend lines only
where they improve reading; no dashboard of decorative scores.

Compare page/state: choose 2–3 followed companies and metric rows; show each
company's fiscal period/end date. Do not silently align different fiscal
quarters or currencies. Comparison selection can live in URL parameters;
there is no new comparison persistence engine.

Desktop 1440px and phone 390×844: on phone show one selected quarter with
previous/next controls and full metric labels. Source drawer and controls
remain reachable; no page-wide horizontal overflow. Preserve tab, company and
period in deep links/back navigation. Loading, empty, partial, stale and error
are distinct states. Keep existing dark theme, typography and tokens.

### Research interaction

“Research question” creates a finite assignment such as “Why did gross margin
fall, and did management change the outlook?” with selected assumptions and
saved evidence. It exports a bounded packet/prompt before a connector exists.
Owner can paste/import a structured response with a preview. Once connected,
the selected agent reads that same assignment and submits its response.

Agent results appear as sourced research, labelled Duet, Dots/Jo, or manual.
They can propose “supports / weakens / mixed / unresolved” for an assumption;
only the owner changes the saved thesis/assumption status. A bare source link
is not evidence that the cited page was retrieved or the claim verified.

## 4. Data semantics — implement before polished UI

### Identity and time

- Resolve a supported security to a stable company ID; store canonical ticker,
  provider symbols, issuer name and CIK if available. A ticker is not an issuer
  identity across renames/reuse; don't silently merge uncertain identities.
- Store UTC timestamps; display New York time. Keep `observed_at` (our fetch),
  `published_at` (source release, nullable/precision-tagged), and `period_end`
  distinct. Preserve fiscal year/quarter AND start/end dates.
- Record `available_at` conservatively for historical/as-of claims. A document
  first retrieved now is not proof the app knew it earlier. Historic backfill
  is labelled “historical, imported on …”.
- “Current quarter” and “next quarter” cannot be durable identifiers. Preserve
  exact provider period metadata before normalization. Only resolve a period
  from explicit supported evidence. If absent, store the relative label as
  unresolved and disable revision/surprise arithmetic for it; never infer it
  solely from today's date or the next earnings date.
- Preserve snapshots when a provider restates a past result. Latest view may
  select the new value, with revision evidence; old snapshots remain intact.
- Provenance is per metric, not merely per row: a later filing can restate EPS
  without being the source of the revenue beside it. Fiscal labels from an
  earlier filing do not determine a metric's publication time.

### Financials, estimates and guidance

V1 automatic actuals: revenue, gross profit, operating income, net income,
diluted EPS; calculated gross/operating margins and comparable YoY changes.
Retain the SEC reader's conservative quarter boundaries. Do not derive Q4 as
annual minus nine months or subtract annual EPS. Show unavailable Q4 unless an
explicit, compatible quarterly source is supplied. Cash flow, debt, cash,
share dilution and sector-specific KPIs can be sourced research facts in v1;
automatic additional statements/annual-YTD conversion are a later slice.

Each metric/estimate has a value (finite decimal), unit/scale, currency when
applicable, basis (`gaap`, `adjusted`, `ifrs`, `unknown`), period, provider and
source reference. Use decimal strings in stored JSON/API for financial values;
do calculations with Decimal and round only for display. Missing is null, not
zero; booleans/NaN/infinity are rejected. Separate weighted-average diluted
shares from end-of-period shares if a sourced fact uses either.

Estimates: EPS and revenue mean/low/high, analyst count where available; preserve
source coverage. A changed mean with changed contributor count is a change in
published consensus, not proof that individual analysts revised their calls.
Keep targets, ratings and firm actions secondary and separate from earnings
estimates. No “target upside” recommendation or analyst accuracy leaderboard.

Comparisons require compatible issuer, metric, explicit period, currency,
units and accounting basis. Unknown EPS basis must not match GAAP by default.
Show provider-reported beat/miss history separately from independently computed
comparisons. Vendor history retrieved after the event is not our pre-event
snapshot. Do not combine Webull history and Yahoo estimates by label alone.

- Growth/surprise: `(actual - reference) / abs(reference)` only for compatible
  nonzero denominators. Show absolute difference when zero/near-zero makes a
  percentage misleading; near-zero EPS under 0.01 in its stated currency has
  percentage suppressed. Margin changes use percentage points.
- A verified pre-release snapshot must have been observed before the earliest
  known release bound. For date-only reports, require before the beginning of
  that reporting date in the issuer's supported timezone (New York default
  only for confirmed US reporting); otherwise label timing unresolved.
- Show estimate revisions over 7/30 days only when comparable snapshots exist
  within a disclosed tolerance (up to 3 calendar days earlier than the target
  date). Otherwise show the actual observed interval or “history collecting”.
- Matching Q1 labels are insufficient: fiscal year/end date, split/per-share
  basis and reporting scope must agree. Retain the reason for an incompatible
  comparison instead of forcing a join.
- Guidance stores issuer-stated range/point, metric, explicit period, basis,
  announcement date, source passage and prior comparable guidance. Do not
  equate management guidance with analyst consensus. Range midpoint is labelled
  calculated; retain both endpoints.
- Do not claim “beat lowered expectations” without at least two identifiable
  pre-release observations for the same period. Do not infer why price moved.

### Evidence and agent claims

Every finding has a claim, kind (fact/interpretation/question), source refs,
publication/retrieval times and affected assumption IDs. Numeric extractions
include the quoted supporting passage, period, unit and basis. Provider/SEC
observations and agent-extracted proposals are separate origins.

Agent facts start as proposals. Owner acceptance can promote a sourced number
to an observation labelled “owner accepted extraction”; it never becomes an
API-verified fact. This provides a usable free-source route for missing guidance
or explicit Q4 numbers without trusting model arithmetic. Corrections append
superseding records. Conflicting sources remain visible.

Store URLs and short supporting excerpts, not an indiscriminate article mirror.
No unrestricted backend URL fetcher or browser scraper. No HTML execution.
Citation links accept ordinary http(s) URLs only, strip access-bearing query
parameters/reject credentials and unsafe schemes. Imported text is data, never
instructions. Excerpts have a per-document cap and respect source permissions.

## 5. Minimal persistence and API shape

Use additive SQLModel tables in the existing database, with migrations and
SQLite/Postgres coverage. Do not use browser localStorage as the source of truth
or the mutable AI Buildout workspace blob as an observation ledger.

Proposed tables (names may follow current repository conventions):

| Table | Minimum responsibility |
| --- | --- |
| `company_research_company` | Stable ID, ticker/provider map/CIK/name, followed/archive state, current thesis and assumptions with a revision counter, created/updated times. |
| `company_research_snapshot` | Append-only versioned normalized payload for one issuer/component/source; observation/publication metadata, source refs, digest, job/refresh ID, supersedes ID where appropriate. Components: actuals, estimates, guidance, analyst actions, calendar, thesis revision. |
| `company_research_finding` | Immutable submitted claim/content and citations; provider/actor, assignment and operation ID; proposed/accepted/rejected/reviewed metadata; links to snapshots/assumptions. Numeric acceptance appends a snapshot. |
| `company_research_assignment` | Owner question, selected company IDs, immutable context/assumption revision, intended actor, creation/expiry, queued/submitted/imported/expired/cancelled state, receipt hash and result links. |

Keep strict Pydantic payload schemas versioned in code, even if snapshots use
JSON columns. Reuse `JobRun` for refresh execution; don't add a parallel queue.
Store each component's last attempt/error separately from its last good data
(JobRun details may supply attempt history). Atomic compare-and-set for thesis
edits; stale revisions return 409 without automatic overwrite. Preserve old
thesis versions through snapshot rows.

Deduplication: retrying the same operation/refresh ID is idempotent. Repeated
observation of an unchanged payload at a later legitimate refresh may be saved
as a dated observation, but must not create another change notification. Key
agent operations by authenticated actor plus operation ID; changed payload with
the same key is a conflict, not an overwrite. Enforce uniqueness in the DB, not
only an in-memory set. No cascading deletion of history on unfollow.

Owner routes under `/company-research`:

- `GET/POST /companies`; `PATCH /companies/{id}` for revision-checked thesis,
  assumptions and follow state; `GET /companies/{id}` for stored summary.
- `GET /companies/{id}/history` with component/period and bounded pagination.
- `POST /companies/{id}/refresh` and bounded `POST /refresh` -> job ID/status.
- `GET/POST /assignments`; `GET /assignments/{id}` including export packet.
- `POST /assignments/{id}/import` -> preview/validation or committed receipt,
  with an explicit confirm step; manual import is labelled owner-supplied,
  never cryptographically authenticated Duet/Jo output.
- `GET /companies/{id}/findings`; `PATCH /findings/{id}` for owner disposition.
- Compare can compose stored company reads; no new query language.

Resolve ticker to company ID on navigation. Keep queries bounded; no provider
calls during DB write transactions. All browser/API routes classified owner-only.
External agents use scoped frozen assignments, not these private routes.

Import preview returns a digest of the strictly validated payload. Confirmation
must carry that exact payload/digest and assignment version and revalidate
expiry/status. Acceptance of a finding or numeric extraction is likewise
version-checked and idempotent. A preview is never permission for changed text.

## 6. Provider refresh and acquisition

Stage 0 of execution is a bounded coverage check using fixtures and, if existing
access permits, read-only requests through current adapters for a few explicit
test issuers. Use NVDA, NBIS and an unsupported/ETF fixture as development cases,
not a seed watchlist. No journal holdings read is required. Never expose keys.

Check these before claiming the live data path works:

1. SEC coverage and source-level accession/tag/unit/period provenance.
2. Whether Yahoo actually supplies target-period metadata and EPS basis.
3. Webull earnings-history semantics (reported vs adjusted; date vs quarter).
4. Calendar date confirmation/timezone and available release-time precision.
5. Existing provider entitlement, pacing, stale/failure behavior.

Record coverage/gaps in this document during implementation. A missing provider
does not block the whole app: retain other components, offer sourced import, and
show the exact gap. If the core estimate comparison has no compatible data,
say that capability is unavailable; do not claim completed live comparisons.
Propose any paid alternative with an exact capability/price separately, never
purchase or change provider configuration in order to complete the feature.

Reuse existing fetch/normalization functions where truthful. Add a research
normalizer that retains SEC per-fact accession/tag/filed/start/end data before
the existing chart cache discards it; don't reinterpret cached chart rows as
raw evidence. Keep the chart's existing behavior and cache contract stable.
For Yahoo preserve any absolute period and basis actually supplied; extending
the adapter with optional metadata must retain existing clients/tests.

Refresh uses a finite durable `company_research_refresh` job. One company at a
time, provider deadlines/pacing, at most 10 companies per request. Concurrent
button presses coalesce. Failed components record their error and retain last
good data. A crash preserves committed components; explicit retry is safe.
No model calls in the refresh job and no refresh loop from a frontend timer.

Use the existing sync lane for bounded jobs initially; do not attach to the
morning sync pipeline. Process one issuer per job so a 10-company pass does not
hold the lane for one long execution. Before dispatch, verify a company remains
followed. Job registration touches shared files only as a small additive edit.

Scheduled tracking is a separate delivery slice: after approval, queue one daily
refresh for followed companies, reusing the same jobs. Default off. No promise
of real-time earnings delivery; user can refresh after a release. Weekend
research is valid; date-based scheduling must not pretend business disclosures
only happen during regular market hours. Do not silently start model research
or phone alerts when a dataset changes.

## 7. Duet / Dots integration

Deliver the owner export/import workflow first. Then implement a scoped MCP
bridge on the existing Check transport, using the snapshot/outbox/receipt
pattern. This is a new capability with its own scopes, not an expansion of
`jo_research_submit` to impersonate another agent.

Suggested tools: `company_research_assignments`,
`company_research_context(assignment_id)`,
`company_research_submit(assignment_id, operation_id, context_hash, findings)`,
and `company_research_receipt(operation_id)`.

Scopes: `company-research:read` and `company-research:submit`, plus the transport's
existing base requirement if necessary. Disabled by default; profile/client
binding is authoritative. Publishing gives an actor only assignments explicitly
addressed to it. Context contains selected company data and owner-selected
thesis assumptions; no account IDs, quantities, cost basis, fills or unrelated
chat. Context expires after 24 hours; create a new assignment to refresh it.
Closed/archived assignments and wrong actors cannot receive or submit context.

Submission is bounded (reuse 64-KiB total/12,000-character body limits; at most
20 findings and 30 source references), schema-validated and sealed with a digest.
Require source evidence for factual assertions; questions may have no citation.
Receipts distinguish `pending_import`, `saved`, `rejected`. Import atomically
creates findings once and stores actual actor provenance. It sends nothing,
changes no thesis, refreshes no provider and starts no follow-up work.

Both agents can receive separate assignments over the same context. Neither
sees the other's answer before submission unless the owner explicitly assigns
a critique. Keep disagreement visible; no consensus score.

Provide exact standing/manual prompts with the implementation: read assignment,
inspect available original sources, cite passages and periods, separate facts
from interpretation, report unavailable sources, submit, check receipt, stop.
No X/Reddit requirement and no financial orders. Agent browsing/scheduling uses
its subscription but still consumes usage; do not create standing tasks here.

The server code and deployment instructions can be prepared and tested with
synthetic profiles. Actual grants, remote runtime upgrades, connector setup,
scheduled tasks and activation remain explicit owner steps. Do not claim live
integration until a real authorized assignment round-trip has a saved receipt.

## 8. Delivery sequence and ownership

Use a `codex/` implementation branch from a freshly inspected base. Keep this
planning document, do not restart discovery. Each slice must be a usable,
reviewable result. Do not build all slices in a single unreviewable PR.

1. **Persistent company research and provider observations.** Empty watchlist,
   additive tables/migration, owner routes, finite refresh jobs, core actuals,
   analyst/calendar snapshots, provenance and partial-state UI. Preserve chart
   contracts. Outcome: add company, refresh, reopen and inspect dated facts.
2. **Comparisons and thesis tracking.** Validated estimate revisions,
   actual/estimate and guidance comparisons, thesis revision history, What
   changed, 2–3-company comparison, source-backed manual extraction/import.
   Outcome: a complete earnings walkthrough with correct temporal/basis rules.
3. **Research assignments and agent submissions.** Export/import usability plus
   provider-neutral, actor-scoped MCP exchange and receipts. Implement synthetic
   end-to-end proof; prepare concrete connector/grant instructions for approval.
4. **Daily refresh and live acceptance.** Disabled scheduling package, explicit
   activation controls/runbook and visible last-success/last-attempt status.
   Activate only after owner approval. One approved real-company refresh and
   one approved real-agent round-trip establish operation, not trading value.

Suggested new owning files: `backend/app/engine/company_research.py` (storage,
services), `company_research_math.py` (pure comparisons),
`company_research_sources.py` (adapters),
`backend/app/routers/company_research.py`,
`backend/app/jobs/company_research.py`,
`frontend/lib/companyResearch.ts`,
`frontend/components/company-research/`, and the two Next.js routes above.
Split a module only when its actual size/responsibility warrants it. For the
bridge use `backend/company_research_common.py`,
`company_research_exchange.py`, `company_research_tools.py` mirroring the
existing exchange's responsibilities; avoid duplicating auth infrastructure.

Shared touchpoints: `models.py`, `main.py`, `access_manifest.py`, necessary
frontend access/proxy inventories, job dispatch, `Nav.tsx`, additive migration,
Check tool registration/scopes/config for slice 3, and `deploy/` for slice 4.
The executor must find the actual current registration points; do not create
nonexistent router names from an assumption. Update owning feature docs/index
only for behavior actually delivered.

Migrations, financial comparisons and access changes require tier-2 reviews per
the current repository policy. New access scopes/routes, deployment and
activation changes are user-gated; prepare them fully, leave auto-merge off and
the merge to the owner. Don't split a gated change to evade that gate. Follow
the current policy for any genuinely non-gated slice. Never treat this plan as
authorization to activate, buy services or change production data.

Complete the implementation sequence rather than stopping after slice 1 with
an offer to continue. If an earlier gated PR is awaiting the owner's merge,
dependent slices may use clearly identified stacked branches with the correct
base; don't merge the parent yourself. Recheck affected integration and CI when
the parent lands. Real activation is the eventual owner decision, not a reason
to leave the code, fixtures or runbook unfinished.

## 9. Acceptance and focused verification

Use deterministic recorded/synthetic inputs; never run tests on production.
Protect `backend/tests/conftest.py` database pin. New focused suites should cover:

- Empty list, add/dedup/archive/restore, issuer ambiguity, persistence after
  restart, concurrent thesis edits returning 409, no destructive archive.
- Mixed provider success, stale cached copy vs fresh observation, timeout/429,
  no zero substitution, retries and concurrent refresh idempotency.
- SEC comparative restatement and accession provenance; Q4 gap; annual/YTD
  rejected as quarter; different currencies, negative/zero EPS, percentage
  points, missing data and unknown basis.
- Calendar/fiscal mismatch; current-quarter rollover; unresolved periods;
  report-time/date-only bounds; retrospective vendor history vs pre-release
  snapshot; no fabricated 7/30-day history; changing analyst contributor counts.
- Guidance ranges, compatible prior guidance, contradictory sources, numeric
  extraction acceptance, revisions and unchanged fetches producing no changes.
- Unauthorized browser/assistant reads and writes, private API not exposed;
  stored HTML/unsafe URLs rendered safely; no credentials in citations.
- MCP wrong actor/scope/assignment/hash/expiry, oversized/invalid payload,
  identical retry and conflicting retry, duplicate import and restart between
  sealing/import/receipt. Old Jo and Duet grants remain unchanged.
- No calls, jobs or messages from disabled scheduler, empty watchlist,
  unconfigured agent bridge, GET navigation or an agent submission.
- Migration upgrade/downgrade on disposable SQLite/Postgres, indexes and
  uniqueness under concurrent writes; existing source tables untouched.

Browser walkthrough fixtures at 1440px and 390×844:

1. Empty list -> add issuer -> partial refresh -> source details -> reload.
2. Two pre-release estimate snapshots -> earnings -> compare expected/actual;
   show an incompatible EPS basis and prevent a false beat/miss.
3. Write thesis -> create/export question -> import sourced answer -> accept
   one extracted guidance number -> inspect old/new evidence and thesis history.
4. Two tabs edit the thesis -> visible conflict without losing either draft.
5. Compare three issuers with different fiscal dates; back navigation retains
   selection; no mobile clipping, inaccessible sources or page-wide overflow.

Suggested new test modules: `test_company_research.py`,
`test_company_research_sources.py`, `test_company_research_math.py`,
`test_company_research_exchange.py`, and `frontend/e2e/company-research.spec.ts`.
Extend existing access/migration suites where behavior belongs. Run relevant
existing financial/analyst/Jo/job tests only for affected dependencies. Use the
repository's current lint/typecheck commands, focused Playwright execution and
disposable Postgres parity instructions. Full applicable CI must pass on the
final head; don't duplicate all CI locally without cause.

Capture changed-flow screenshots, perform the UX gate, and get the required
strong general plus focused financial-temporal/access review for each tier-2
slice. Repair actual findings; retain one concise completion checkpoint per PR.

## 10. What completion means

Report separately:

- **Built:** supported fields, persistence, comparisons, source drill-down and
  synthetic/manual agent workflow pass the checks.
- **Available from current sources:** identify exact live field/issuer gaps;
  especially estimate period/basis, Q4 and transcripts. Unavailable is not done.
- **Connected/activated:** only after an actual authorized refresh, connector
  receipt and schedule observation. Do not claim from configuration alone.
- **Useful:** owner finds new relevant facts, saves research time, or revises a
  thesis based on evidence. No claim of return improvement from engineering QA.

The core first release is done when the owner can follow a company, see saved
financial/expectation history, investigate a change with source evidence, and
bring a research response back without losing earlier reasoning. Don't finish
with a static mockup, empty placeholder tabs, or merely another current quote
screen. Conversely, don't buy data or fabricate coverage to force completeness.

## 11. Resume instruction for this chat

After the owner switches models and says to execute:

> Implement `docs/company-research-plan.md` in its delivery order. My decisions
> are existing/free sources first and an initially empty company list. Reuse the
> inspected sources, preserve temporal/basis correctness and coordinate shared
> files with current Claude work. Start with the bounded data-coverage check,
> then deliver the first usable slice through focused checks, required review
> and final-head CI. Prepare gated changes completely for my merge; do not
> activate services, broaden grants, buy data or run paid model calls. Continue
> through independent work while a gated slice waits. Report actual data gaps
> honestly. Do not restart the product brainstorming or ask me routine design
> questions already answered here.

## Source references checked during planning

- [SEC company submissions and Company Facts APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
  provide public filing metadata/standardized financial facts; this is not an
  analyst-consensus or complete transcript service.
- [Benzinga earnings through Massive](https://massive.com/docs/rest/partners/benzinga/earnings)
  and [Benzinga corporate guidance](https://www.benzinga.com/apis/cloud-product/corporate-guidance/)
  illustrate optional structured feeds, not purchased or presumed available.
- [Duet capabilities and limitations](https://support.claude.com/en/articles/17631495-get-started-with-claude-duet)
  support connector/browser research but don't guarantee source access, exact
  timing or successful private connector configuration in this account.

Recheck provider specifications/entitlements when implementing an adapter;
preserve the free/existing-source decision.
