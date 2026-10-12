# Dots integration: delivery status and direction

**Owner priority: Dots functionality first, selected October 11, 2026.**
TradeJournal should be the place Isaac requests help, controls what Jo sees,
and reviews her saved work. The [product priorities](../product-roadmap.md#selected-priorities--october-11-2026)
own cross-roadmap order. This board owns the Dots sequence; linked contracts
own permissions, implementation and acceptance. Planning is not activation.

Dot owns bounded preparation, explanation and follow-through. TradeJournal
owns durable evidence, calculations and deterministic monitoring. Codex builds
selected changes; Isaac owns priorities and consequential approvals. The
personal coach/advisor is not the independent Shadow Isaac comparator.

## Current delivery board

Checkpoint: October 11, 2026 (evening ET), against merged source through PR #260 and the
operational evidence below. PR and host state can change; verify them before
acting. Built means merged implementation, activated means enabled in the
named environment, observed means the actual path ran, and accepted means the
slice's stated exit criteria were met. None implies trading edge.

| Capability | Delivered evidence | Remaining boundary |
|---|---|---|
| D0/D1 connection and sample reads | Actual synthetic OAuth call and assigned sample tool/UI comparison recorded in the [connector scope](cloud-mcp-integration-scope.md); Mac-asleep synthetic result was owner-reported | This does not prove laptop-off acceptance for every later role or write path |
| D2/historical sample choices | Scoped own-choice/receipt implementation exists; [D2](cloud-mcp-d2-contract.md) and [historical contract](cloud-mcp-historical-contract.md) retain their evidence requirements | Do not infer every live save/UI/restart gate passed from code or an earlier sample; reconcile actual receipts for a selected exercise |
| Journal coach | **Initial integration accepted.** Continuous scoped read-only publication and actual Jo reads passed October 10 ET; one actual coaching review followed. [Durable acceptance summary](cloud-mcp-journal-contract.md#observed-continuous-journal-acceptance) | Eight approved fields over closed/expired Roth trades; no open positions, intentions or automatic coaching. Repeated usefulness and current health are separate questions |
| Advisor handoff | **Connected trial observed October 11, 2026 ET** on the retained #251 v2 install: actual Jo (ChatGPT plugin, dedicated Auth0 advisor user) read the replacement invented request and saved one cited answer over OAuth MCP (received 7:11:24 PM ET, receipt `e98582d6…79939`, request `a4b178f7…`); the server read back the identical receipt after one bounded three-service restart, and the owner `/advisor-review` page showed the same saved answer after that restart. Discovery first needed `client_claim` `azp` (Auth0 JWT profile), a fresh login as the bound advisor user, and ChatGPT **Refresh tools**; the first save was refused because `answer` carried the whole contract wrapper | The owner screenshot did not expand the exact receipt panel; owner-deferred revoke/recover check remains. Public keys still expire hourly without upkeep (step 3). Invented data only; not trading advice or AV0 |
| Repeatable advisor questions | [PR #257](https://github.com/imizik/TradeJournal/pull/257) (merged) implements the [bounded assignment contract](advisor-assignment-contract.md): owner create/assign/list/reopen/revoke, one selected invented request and preserved cited receipts | Local generated-token two-question proof and desktop/390px authenticated UI create/reopen/revoke/restart passed; Not retained-activated or actual Jo accepted. `advisor_trial_control.py upgrade`/`downgrade` plus a separate additive `migrate-ledger` (the #251 ledger is one revision behind main) can carry it to the v2 install; fake-host and CI-smoke tested, not run on the VPS |
| Shadow and A3 | Manual fixture assignments/choices and disclosure records implemented; A1/A2 infrastructure exists and A2 has one observed live operational lifecycle | Actual cloud-runner isolation, forward comparison and A3 human-timed acceptance remain unproven; latest A3 record is 0/3 sessions, not a current production-data audit |
| D3 follow-through | Bounded design exists | No accepted user-facing subscription/scheduled follow-through. Journal export/key maintenance timers do not establish D3 |

### Functionality sequence

These are product outcomes, not authorization to implement every row at once.
Reuse existing OAuth, receipts, host and UI where their contracts permit.
Resolve an actual blocked user action before adding another infrastructure slice.

| Order | Outcome | Completion evidence |
|---|---|---|
| **1 — Observed: connected advisor trial** | Finish the existing advisor chat's one invented-data end-to-end trial | Actual Jo reads the frozen request, saves a cited answer, and the owner sees the identical receipt in TradeJournal after reload and service restart; existing isolation/activation gates remain applicable |
| **2 — Next: repeatable advisor questions** | Owner creates, assigns, revokes and reopens questions through the app | A second distinct assignment works without OAuth edits or service restart; answers bind to the correct immutable request, and prior answers remain recoverable. Write a bounded assignment-management contract first |
| **3 — Current: dependable connection** | Routine use survives normal credential/key lifecycle and service maintenance | Supported refresh/reconnect, health/failure visibility and recovery are observed; connection maintenance stays separate from agent schedules and trading automation. Scoped in the [connection upkeep contract](advisor-connection-upkeep-contract.md). Optional key upkeep for the v2 install is built (`deploy/advisor_keys_control.py`); not installed, activated or observed. The owner status view on `/advisor-review` is built as dormant source (keys, advisor enabled, selected question, last Jo save); it reaches the VPS only through the v2 upgrade command |
| **4 — Useful approved real-data advisor** | Move beyond invented packets to a narrowly selected real question and data scope | Separately approved fields/sources, frozen provenance, stale/missing-input handling and actual useful answer; do not call the fixture advisor the live AV0 Go/Wait/Pass product. Slice 1 (pre-trade check, live data and own-trade aggregates approved October 11) is planned in the [pre-trade check contract](advisor-pretrade-check-contract.md); engine, the disabled check service/installer (step 2) and the dormant owner view (step 3) are built, not installed or activated |
| **5 — Coach in the same workspace** | Request/review coaching without extra setup or copy/paste | Preserve the completed read-only journal connector and link displayed work to its approved snapshot. Define saved-result scope explicitly; UI unification is not broader data access |
| **6 — Bounded independent shadow** | Obtain a separately formed decision for comparison | Separate role/context, observed input isolation and commitment/reveal rules, then applicable forward/paper and A3 gates. Reuse the working advisor operations without sharing human/advisor inputs |

After these bounded outcomes, select one follow-through capability only when a
real recurring need justifies it. Do not build a general agent platform, widen
journaling obligations, or require profitable research as an integration gate.
Independent shadow acceptance does not block the already accepted coach.

### Coordination and acceptance

The existing advisor/shadow chat (“Implement advisor shadow handoff”) owns the
current connected trial and its prepared grouped activation packet. The owner
assigned the repeatable-question contract/implementation to “Build repeatable
advisor assignments”; the journal chat owns journal refresh/coaching. Research
retains its already-selected comparison/prospective slice and user acceptance,
then yields new feature priority to Dots. Other chats should consult this board
and the product priorities before starting adjacent work.

Each handoff should identify the user action being enabled, current status,
linked evidence, exact remaining exit gate and next eligible slice. Carry
unchanged evidence as the repository workflow permits; do not repeat a completed
integration trial merely to satisfy a new roadmap label. A conversational success
claim is not a durable receipt, and recorded past acceptance is not current health.

## Existing architecture and later scope

The [cloud MCP scope](cloud-mcp-integration-scope.md) owns structured access;
the [browser contract](cloud-browser-auth-contract.md) owns the separate assistant
UI entrance. Browser login and connector OAuth are distinct. The synthetic,
practice, journal and advisor roles have different grants and acceptance; no
broad local stdio adapter is suitable for an independent runner.

The selected connector route uses ChatGPT plan reasoning with no API-credit
model path. Keep the production private API private. Existing role contracts,
backend authorization and separate activation gates remain authoritative.
The sections below retain the A1 and proposed shadow/follow-through design;
they are not statements that the accepted journal connector is absent.

## Current A1 interface

The current adapter is [`backend/mcp_server.py`](../../backend/mcp_server.py),
a local stdio FastMCP server. It calls the private FastAPI service; the backend
owns validation and persistence. A1 tools are:

| Tool | Inputs | Result |
|---|---|---|
| `get_decision_context(symbol, operation_id)` | Symbol and retry key | Fetches a ticker packet and durably freezes it. Returns `context_id`, server capture time, provider, context digest, packet and completed-minute price facts. Repeating the operation key returns that same snapshot. |
| `record_decision(operation_id, opportunity_id, actor, decision, symbol, context_id, rationale, wait_condition, wait_expiry, plan)` | Decision metadata plus the saved context ID. `plan` is used only for TAKE; WAIT needs a condition and expiry; SKIP needs a reason. | Creates an immutable record bound to the server-owned context. Identical retries return the existing row; changed content with the same key conflicts. |
| `get_decision(record_id)` | Record UUID | Returns the saved decision, exact evidence, hashes and receipt/cutoff times. |
| `list_decisions(limit)` | Optional bounded page size | Returns recent records. |

Every A1 response is labeled `practice_draft_unarmed`. A TAKE must reference
completed raw Alpaca minute facts by their saved fact names. Source, formation
and observation times, USD/share unit, and raw split basis are retained. The
validator rejects missing, stale, future, mismatched or non-finite facts, and
requires an explicit freshness limit, entry guard and versioned nonnegative
slippage parameters. The [selected P0 operating policy](practice-policy.md) now
fixes the universe and worked example. Its complete `shadow-isaac-p0-v1`
version/hash and eligibility checks must be stored at a future A2 arm; the
current A1 schema hash alone does not make a draft prospectively eligible.

## Requirements before connecting another agent

The requirements below govern an independent shadow runner. The personal Dot's
initial reviewer/inspector catalog is scoped separately in the
[cloud connector plan](cloud-mcp-integration-scope.md); the backend, identity
and transport boundaries apply to both roles.

1. Confirm Dots' actual supported transport and authentication contract. Do
   not assume it can launch a local stdio process or call this API.
2. Create a separate shadow-agent tool profile that includes only market
   context and the agent's own decision records. Exclude fills, journal trades,
   account data, Isaac's decisions and all journal-analysis tools.
3. Enforce the same capability policy in backend services. Hiding tools from an
   MCP catalog is not access control. Legacy private mode has no authentication
   and accepts a caller-supplied actor. Optional authenticated mode has browser
   principals and named service capabilities; decision writes derive the actor
   for owner/manual MCP identities. The scoped cloud services have their own
   OAuth and ownership contracts;
   the broad local adapter is not a substitute for those services or proof of
   independent shadow isolation.
4. If Dots is remote, design a separately scoped gateway/identity on the private
   host. The cloud scope selects direct HTTPS/OAuth to a
   restricted MCP service with named operations. Do not expose or tunnel ports
   8080/8000, do not give
   the agent raw HTTP or shell access, and do not add a proxy that forwards
   arbitrary API routes. Public access requires a new reviewed security design.
5. Test allowlisted tool discovery, denied journal reads/writes at the service
   layer, idempotent decision submission, identity attribution, timeouts and
   failure behavior before enabling a Dots connection.

Until those gates are met, use the existing local MCP adapter for manual
preparation only. The current adapter advertises the existing all-journal
profile as well as A1 tools; do not give it to an independent shadow agent.

## Proposed restricted shadow-agent profile (design only)

Keep the existing MCP adapter as a local manual toolset. Build a **separate** `shadow_agent_v1` catalog whose only capabilities are `get_decision_context` for a P0 universe symbol, `record_decision` for the authenticated shadow actor, `get_decision` for that actor's own record ID, and `list_decisions` filtered to that actor with a strict page limit. A future read-only status tool may expose only the agent's own plan/paper events after A2 exists. No journal fills, trades, accounts, human decisions, raw database access, arbitrary URL fetch, shell, factory writer, alert administration, or generic HTTP proxy belongs in this profile. Tool names are a convenience; backend authorization is authoritative.

At the service boundary, authenticate a per-client capability on **every** request before route logic, map it server-side to an immutable principal such as `shadow-isaac`, and derive `actor=agent:shadow-isaac` there rather than trusting the submitted field. Authorize operation plus resource owner: context create/read only for allowlisted symbols and bounded rate; record create only with the caller's own saved context, P0 policy version and daily cap; record get/list only for that principal; no access to `/trades`, `/fills`, `/accounts`, journal analytics, human rows or unrelated contexts. Give the capability no paper-arm or alert-write right in A1. Scope any later A2 arm right separately to an explicit reviewed policy and the agent's own TAKE records. Deny by default in the service even if an endpoint is reached outside MCP. Keep an audit trail of principal, operation, record ID, outcome and request time without secrets or unrestricted payloads. Expire and rotate credentials; bound request size, rate and deadline. Test forged actor/context/record IDs, catalog omissions versus direct-route calls, idempotent retry, timeout and revocation.

A remote Dots integration first needs its actual transport/auth contract and a separately reviewed narrow gateway on the private host. The gateway would expose only named operations above and forward an authenticated principal, never the private API port or arbitrary route paths. Until that design and negative authorization tests exist, no independent Dot receives a connector or the current broad adapter.

## Ownership boundary

Put business rules in `backend/app/engine/decisions.py` and typed HTTP routes in
`backend/app/routers/decisions.py`. MCP or a future Dots connector should only
translate tool inputs and outputs. Do not add Dots-specific columns, callback
formats, schedulers, credentials or a public tunnel to the decision schema.
The implementation sequence and A1/A2/A3 boundaries are in the
[agentic trading roadmap](../agentic-trading-roadmap.md).

## Roles and independent decisions

The personal Dot may know Isaac's decisions from prior conversation or memory.
A prompt asking it to disregard them cannot make its choice independent. Use
a separate restricted runner for Shadow Isaac, with an explicit recorded input
packet containing only permitted market/context/policy facts. Do not pass Dot
memory, human choices, journal activity or a summary that leaks those choices.
Verify the actual delegated payload and service authorization; a new thread
alone is not proof of isolation. Reveal paired decisions only after both are
committed, or label late/assisted/independence-unverified cases explicitly.

| Proposed role | Allowed scope | Boundary |
|---|---|---|
| Independent practice runner | Approved context and its own frozen decisions; later own paper events if separately granted | No human choices, coaching memory, accounts or journal tools before commitment |
| Personal review/coach | Explicitly granted reflections, commitments, opportunity outcomes and journal summaries | Human context is allowed; its decisions are not represented as blind comparisons |
| Research | Approved questions, sourced evidence and thesis-update proposals | No automatic policy changes, paper arming or journal mutation |
| Operational diagnosis | Sanitized freshness, coverage and delivery evidence | No credentials, raw database access, production repair or automatic deployment |

These roles are permission scopes, not a requirement to create four agents.
Enforce each at the service boundary; do not broaden the shadow catalog to
support coaching. Scope changes need explicit selection and authorization.

## Proposed follow-through capabilities

Build only the capability needed for a selected slice. The following are
design requirements, not existing tools, routes, tables or verified Dot APIs.

| Capability | Contract |
|---|---|
| Durable questions and commitments | Store owner, linked evidence/decision, original wording, version, due time or explicit condition, budget/expiry and open/resolved/expired/canceled state. Reference existing WAIT conditions; do not duplicate executable plans. |
| Changes since a saved cursor | Return authorized bounded events with stable IDs, source/observation times, versions, pagination and a resumable cursor. Surface retention gaps and stale sources; consumers deduplicate and recover after restart. No human-choice metadata may leak into the shadow scope. |
| Evidence-linked proposals | Separate suggested reflections, structured reasons and thesis amendments from accepted records. Retain original words and before/after-outcome timing; unresolved identity stays unresolved. Saving authority is explicit and corrections append history. |
| Action receipts | Return operation ID, accepted/rejected/pending status and resulting record/version. Same-key retries are idempotent; changed content conflicts. After an uncertain timeout, retrieve status before retrying. A conversational claim is not a persistence receipt. |
| Availability and interruption preferences | Version user-selected availability, timezone, quiet windows, channel and budget. Optional calendar access requires its own permission. Preferences cannot rewrite cohorts, execution policy or required exit/failure notices. |
| Usefulness and operational evidence | Link feedback and source/detection/delivery status to exact artifacts/events. Preserve unrated/unobserved states; expose bounded sanitized reports for diagnosis and weekly service review. |

A connection does not establish an active responsibility. For each selected
follow-up, retain its confirmed schedule or supported event subscription,
timezone, destination, next due/check state, last success/failure and cancellation
status. Verify one actual run and a stop/cancel path. Bound calls, cost, retries
and notification volume. Polling may be an initial fallback only after the
transport is verified. Deterministic monitoring of existing positions must
continue if Dot, its model, a schedule or the connected computer is unavailable.

Before claiming a capability works, test ownership denial and identity spoofing,
proposal/acceptance separation, duplicate and out-of-order events, cursor gaps,
restart recovery, uncertain writes, cancellation and revocation. Observe a real
connection and resulting persisted record; test fixtures do not establish live
delivery. Existing A1 tools do not satisfy these proposed contracts by name.

Prioritize conversational reasons, follow-ups and feedback through their
[product owners](../product-roadmap.md#dots-assisted-learning-extensions-proposed).
Thesis evidence monitoring and operational diagnosis follow the
[agentic expansion](../agentic-trading-roadmap.md#17-dots-follow-through-expansion-proposed).
Preserve A1–A3 scope; do not build a general workflow engine or publish the
private API to make the integration convenient.

## Selected sample replay increment (2026-10-09)

Isaac selected [Jo’s own sample paper replay](dot-sample-replay-contract.md) after
reporting the original MU/NBIS WAIT save/reload/reopen acceptance. A new scoped
login may start its own TAKE replay on a separate frozen exercise. This adds no
live exposure, P0 universe change, active WAIT monitor, model calls or schedule.
