# A3 implementation contract: daily preparation, choices and review

Scoped on 2026-10-08 for a Sol-led implementation. This refines A3 in the
[agentic trading roadmap](../agentic-trading-roadmap.md#a3--run-a-daily-routine-and-compare-independent-choices);
it does not select another roadmap track or authorize A3 deployment, paid
model calls, scheduling, or Phase B/C/D work.

## Starting evidence

A1 immutable, provider-backed decisions and A2's core live operational loop
are available. PR #152 merged and release `d00257286dd0` deployed on
2026-10-08. One late-session SPY operational observation completed phone
receipt/exact-card opening, accepted paper entry, API restart while open,
and a fixed-stop exit with unique events and independently verified base
and triple-cost R. The [acceptance evidence](practice-policy.md#a2-live-operational-observation-2026-10-08)
is currently an unpushed local documentation change. It is outside the
on-time strategy cohort. A1 human comprehension timing is still unobserved.
Check current code and deployment state; this dated evidence is not proof
of the next chat's environment.

## User outcome

A short morning board makes a frozen decision possible before work. An
after-work review reconciles what was decided, what the paper watcher did,
and what was missed. Selected human and agent choices can be compared
without revealing the agent verdict before the human commits. Dots is not
required.

## In scope

1. **Durable daily runs and shared opportunities.** One canonical market
   session/P0-policy run, immutable input contexts, stable opportunity IDs,
   explicit preparation mode, timing, coverage and terminal result. Reuse A1,
   A2 and JobRun instead of creating a second decision or paper engine.
2. **Manual-first Today workflow.** An explicit preparation action, calendar
   and freshness status, frozen-context links, human TAKE/WAIT/SKIP capture,
   separate explicit A2 arming, and visible failure/retry/no-setup states.
   A one-tap choice must not invent TAKE levels: a TAKE still needs validated
   frozen plan terms, while WAIT/SKIP retain their required fields.
3. **One bounded, replaceable agent adapter.** Use the existing structured
   model-call approach. Supply only approved frozen market/policy facts.
   Persist exact output, validation failures, prompt/policy/model identifiers,
   timing, usage and cost provenance. Enforce explicit runtime and daily
   spending/token limits. Missing usage/cost is unavailable, not zero.
4. **Independent choice and reveal.** Predeclare the common opportunities
   before either choice. Human-visible pre-choice content is neutral context;
   agent verdict, plan, rationale and confidence stay hidden until eligible
   reveal. Backend authorization and the actual runner payload enforce
   isolation. Do not give the independent runner the broad journal MCP
   profile, raw HTTP/shell tools, human decisions or journal activity.
5. **Deterministic practice review.** A separate practice section in Daily
   Review/Today shows all opportunities and decisions, paper lifecycle,
   source gaps, actual timing, versions, and useful/not-useful/unrated alert
   feedback. Operational probes and late/assisted cohorts remain distinct.
6. **Opt-in 08:50 ET scheduling.** Build one finite preparation job using
   JobRun and existing systemd patterns. Deadline-sensitive preparation
   must not queue behind broker imports or voice transcription. Preserve
   restart/ownership rules. Ship paid execution and scheduling disabled until
   the user approves the exact runtime/model, limits and enablement.

## Build order and decision ownership

Deliver and verify the daily-run model and manual UI first. Then integrate
choice isolation, the bounded adapter, and disabled scheduling into the same
A3 contract. Sol settles ownership, canonical run/retry semantics, cutoff,
budget enforcement, the restricted runner boundary, and comparison semantics
before delegating implementation. Do not create an unrelated orchestration
framework. Choose concrete schema and routes after inspecting owning code;
this document does not mandate hypothetical tables or endpoints.

## Acceptance criteria

- **AC1 — Session identity and honest outcomes.** Concurrent manual/scheduled
  starts and same-key retries cannot create a second canonical session/policy
  cohort. Completed, no-setup, failed, late and no-session cases are explicit;
  successful completion does not erase lateness or missing coverage. Revisions
  retain their original run and a visible relationship. DST, holidays, early
  closes, unavailable calendars and missed deadlines have deterministic tests.
- **AC2 — Manual capture works on desktop and phone.** Prepare, inspect
  timestamped facts, commit each valid choice, reload and reopen its exact
  evidence. Missing/stale required facts cannot support TAKE. A1 validation,
  immutable hashes, original risk and A2 explicit arming stay authoritative.
  Arming refusals are visible; no UI action silently creates a paper position.
- **AC3 — Bounded preparation.** At most five P0 symbols and three agent TAKE
  candidates per session. A2's global arm/active-symbol limits still apply;
  paired decisions do not authorize duplicate positions or reset arm caps.
  No clean setup is a valid result. The brief contains MARKET TAPE, IMPORTANT
  NEWS and SETUP BOARD with source times, links and honest unavailable sections.
  Premarket packets do not pretend regular-session RVOL/ORB is known.
- **AC4 — Model and failure isolation.** Hard runtime and daily limits are
  checked before calls. Timeout, malformed output, exhausted budget and
  uncertain completion are durable and visible. No silent paid retry after
  uncertain completion. Restart/retry cannot duplicate decisions. Model or
  preparation failure cannot pause A2 monitoring/delivery. Manual preparation
  remains usable with the adapter disabled.
- **AC5 — Enforced independence.** Negative tests deny human/journal reads,
  forged actor/context/record ownership and unapproved operations at the
  runner/service boundary. Inspect the exact submitted model payload. A hidden
  UI or prompt alone is insufficient. Agent choices cannot be retrieved via
  the intended human comparison API before eligible reveal. Preserve the
  application's existing private-owner access boundary; do not claim broader
  anonymity or expose its unauthenticated API. If a required isolation boundary
  cannot be enforced, disable independent mode and label the run assisted or
  independence-unverified rather than claiming a blind comparison.
- **AC6 — Reveal and nonresponse.** Both choices are durably committed before
  independent reveal. Late/early reveal, assisted decisions, unavailable agent
  output and human nonresponse remain explicit. Unobserved is never SKIP.
  Frozen human choices cannot change after seeing the agent result.
- **AC7 — Review reconciles.** Counts and filters drill into every saved
  opportunity, TAKE/WAIT/SKIP/nonresponse, expired/unfilled/rejected plan,
  open/closed/unresolved position, gap and alert rating. Distinguish ntfy
  acceptance from reported phone receipt. Keep paper outcomes separate from
  journal fills/FIFO/actual P&L. Preserve frozen planned R and base/3× costs.
  Define a shared underlying-outcome benchmark before either choice; do not
  substitute each actor's different fills or option-versus-stock P&L for it.
  Missing benchmark coverage remains unavailable. Sol freezes the smallest
  deterministic benchmark contract before implementation.
- **AC8 — Schedule/deployment readiness.** Test the dedicated job lane,
  calendar-aware 08:50 scheduling, actual receipt/deadline labels, ownership,
  restart and same-key retries with fixtures and native deployment patterns.
  Packaging is compatible with opt-in enablement. No live recurring job or
  paid call is enabled by merging documentation or by fixture tests.
- **AC9 — Engineering readiness.** Appropriate backend, browser and negative
  authorization tests pass. Run `scripts/verify.sh --fast` while working and
  full `scripts/verify.sh` before reporting code readiness. Verify Postgres
  migration/roles and Ubuntu package/systemd in CI when relevant. Report
  fixture, browser, provider, deployment and human observations separately.
- **AC10 — Live acceptance.** After separately approved deployment/enablement,
  observe three eligible market sessions, including honest no-setup/failure
  coverage. Retain actual human timings: morning use and after-work review
  together take five minutes or less per session, or record why they did not.
  Label manual versus scheduled sessions; manual use does not validate the
  timer, and assisted use does not validate independence. Report descriptive
  outcomes and coverage without profitability claims. A3 is not fully accepted
  until the applicable live gates are observed.

## Explicit exclusions

No Dots/cloud connection, public gateway/tunnel, broker orders, automatic
arming, changed P0 universe/execution/costs, discretionary position amendments,
new strategy families, factory/Workbench writers, policy optimization, thesis
prediction engine, purchased historical news, crawler/search infrastructure,
portfolio sizing, options/shorts/partial exits, or journal/reflection redesign.
No A3 implementation grants authority to start another roadmap slice.

## Completion and approvals

Keep one accountable Sol lead; use bounded Luna workers only when useful and
follow [the repository workflow](codex-workflow.md). Sol owns consequential
semantics, integration, security and final/live verification. One writer per
shared subsystem; avoid gratuitous delegation or nested workers.

Ask before pushing, opening a PR, merging/deploying, making paid calls or
turning on the scheduled runtime. Earlier VPS approval applied to the A2
release, not automatic A3 enablement. While an approval-dependent gate is
pending, finish independent implementation and deterministic verification.
Report code-ready, deployed and live-accepted states separately. Stop at A3.

## Implementation decisions and readiness (2026-10-08)

The owned `codex/a3-daily-routine` implementation preserves this contract.
`PracticeRun` uses a unique ET date/P0 hash/revision key; revision zero is the
canonical cohort regardless of manual/scheduled races. Explicit revisions link
to the original and are assisted. Job ownership is the existing single-host
`JobRun` lock, in a dedicated `practice` lane. An interrupted run becomes failed,
retains evidence and requires an explicit revision; it never replays a paid call.
Five symbol opportunities are committed before contexts or either actor choice.
Choices use stable A1 operation IDs and cannot be changed even after reveal.
A shared opportunity can be armed through only one actor, including after that
plan becomes terminal; paired choices never create a second paper plan.

The cutoff remains P0's 09:00 ET. Actual receipt and completion timestamps
preserve lateness independently of the terminal result. Calendar unavailable
fails closed; closed sessions are explicit no-session records. Scheduled startup
before 08:50 does not replay yesterday; after 09:00 it records a missed deadline
without a provider/model call. Manual late preparation remains visibly late.

The smallest shared benchmark is `underlying-open-close-v1`: regular-session
underlying open-to-close percentage return, without costs or actor fills. It is
predeclared on every opportunity, requires every regular-session minute from
Tradier and current verified no-split coverage, and respects early closes.
After-close collection is explicit; unavailable coverage is never a zero return.
A2's frozen planned R and base/3× paper costs remain separate in the review.

The bounded adapter is a tool-free Anthropic JSON call. Its sole input is an
allowlisted market/policy payload, with at most ten frozen facts per symbol.
The child receives no database credentials, private API origin, journal MCP,
human records, raw packet or application tools. A finite subprocess enforces
wall-clock runtime. Model outputs cannot assign actor, context or operations;
the orchestrator validates all five choices before writing through A1 and
accepts at most three TAKEs. All five agent records and completed-call status
commit atomically; a later receipt-time validation or storage failure rolls
back the entire choice batch while retaining the earlier durable call/output
reservation. New TAKE receipts and new arm events must match the run's ET
session date; same-key retries retrieve original evidence.
Generic decision/list/paper/arm routes also enforce
A3 visibility and context ownership. This preserves the private owner boundary;
it does not add public API authentication or protect against the owner directly
reading their database. No independent external runner endpoint is exposed.

One unique paid reservation per ET day includes revisions and uncertain calls.
Explicit model, timeout, input/output bounds, token rates and daily USD cap are
required before enablement. Conservative input byte bounds and maximum output
cost are checked before submission; exact submitted payload, raw result,
validation failures, config, timing and usage are retained. Missing usage/cost
stays unavailable. A failed or uncertain attempt cannot trigger an automatic
paid retry. Preparation failure does not change A2 monitoring or delivery.

Paid execution and the timer are disabled by default. The package installs the
optional timer unit without enabling it. Manual preparation, immutable choices,
review, explicit benchmark refresh and measured morning/review timers are usable
without the agent. Source-less news and premarket RVOL/ORB remain unavailable.
User-reported phone receipt remains separate from A2 delivery acceptance.

Code readiness is subject to local verification and separate Postgres/Ubuntu CI.
No A3 push, PR, deployment, paid call or live schedule is authorized by this
implementation. AC10 remains **unobserved (0/3 A3 sessions)**: fixture/browser
checks cannot satisfy human routine timing or scheduled/independent live gates.

### Local verification evidence

`bash scripts/verify.sh --fast` passed. The complete
`E2E_BACKEND_PORT=8107 E2E_FRONTEND_PORT=3107 bash scripts/verify.sh` passed:
1,552 backend tests (32 skipped), 187 browser tests, backend/deployment lint,
import boundaries, frontend typecheck/lint and production build. Disposable
ports avoided an existing test-port listener without stopping it. The paired
opportunity arm guard additionally passed the complete backend recheck.

A final focused browser check covers the attention timer staying on its
original run and surviving a failed write, alongside phone capture/reload and
independent commit/reveal. All browser and timing evidence is synthetic. No
paid API call, live provider observation, production change or recurring job
was made for A3. New Postgres constraints and disabled native units have CI
checks prepared, but no CI run for this unpushed source has been observed.

The final A3 browser recheck passed all three real-backend fixture scenarios
on disposable ports 8127/3127, including the timer correction. The subsequent
frontend typecheck and documentation link/freshness checks passed as well.


### Hosted review follow-up

Codex reviewed published head `7581d7f` in PR #156 and identified atomic agent
writes, cross-session TAKE/arm ownership, and revealed-agent filter coverage.
The follow-up addresses those cases with rollback fixtures, session-date
refusals that preserve idempotent retrieval, and a real-backend disagreement
filter test. Human and visible-agent counts are separately labeled. These
corrections do not enable paid calls, scheduling, or deployment; AC10 remains
0/3 observed sessions.

The review follow-up passed `scripts/verify.sh --fast` (1,560 backend tests,
32 skipped), 76 focused decision/paper/routine regression tests including an
actual-receipt midnight case, and all three real-backend A3 browser scenarios.
All required CI checks on original head `7581d7f` passed, including Postgres
parity/roles and native Ubuntu package/systemd. The correction head needs its
own CI and hosted re-review; no merge or deployment is authorized.
