# Future Dots integration

This is a handoff for connecting a future Dots client to TradeJournal. Official
documentation now describes Dots plugins and ChatGPT custom MCP connections;
the [cloud MCP scope](cloud-mcp-integration-scope.md) records those sources,
the selected direct HTTPS/OAuth transport and unverified account/runtime gates.
No MCP connection to this installation is established. Keep TradeJournal as the
owner of decision records, frozen market context and paper outcomes.

**Direction updated 2026-10-08; design only.** Dot owns bounded preparation,
explanation and follow-through. TradeJournal owns durable evidence, objective
monitoring, validation and calculations. Codex implements selected changes;
Isaac owns priorities and consequential approvals. No integration, schedule,
new permission or implementation is activated by this document.

**Cloud browser direction selected 2026-10-08; isolated sample sign-in reported 2026-10-09.** Isaac wants the
Dot to use the actual UI with his laptop closed, while keeping his own
Tailscale entrance without another login. The
[cloud-browser access contract](cloud-browser-auth-contract.md) defines the opt-in
separate authenticated assistant entrance, backend-enforced permissions and
a sample-data browser trial before any live exposure. Isaac subsequently reported Trader Jo using the isolated sample UI. The
[first saved sample decision contract](dot-decision-trial-contract.md) owns the
next selected browser permission increment. Production remains private; this
sample observation does not establish a connector or independent runner. The
personal Dot's app inspection remains separate from independent Shadow Isaac.

**Combined access direction scoped 2026-10-08.** Use a connected app for exact
records and supported operations, and browser access for visual inspection and
workflow feedback. The [cloud connector scope](cloud-mcp-integration-scope.md)
defines the initial read catalog, OAuth boundary, routing guidance and D0–D3
sequence. It adds no active connection or permission.

**Connector spending constraint selected 2026-10-09.** Use ChatGPT plan usage
with no API credits. The selected D0 package uses Server URL + OAuth, local
public keys and a network-disabled Unix-socket service with no model keys or
model-call tools. The [runbook](cloud-mcp-d0-runbook.md) distinguishes that
enforced service boundary from account-level allowances/extra-credit settings
and pending actual Dot acceptance. Later UI/MCP grants must also deny paid
model-job triggers; connecting a plugin does not change the current browser grant.

OpenAI documents ongoing responsibilities, selective memory, delegation and
event monitoring where a connected service supports it in
[Tasks and memory](https://learn.chatgpt.com/docs/dots/tasks-and-memory).
These product capabilities do not establish this installation's transport,
authentication, event support or availability. Verify those at connection time.
Agent memory is not a complete transcript or the authority for saved state.

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
   for owner/manual MCP identities. Neither mode implements the proposed cloud
   OAuth and per-agent ownership boundary yet.
4. If Dots is remote, design a separately scoped gateway/identity on the private
   host. The cloud scope proposes testing Secure MCP Tunnel only to a new
   restricted MCP service. Do not expose or tunnel ports 8080/8000, do not give
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
