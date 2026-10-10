---
name: tradejournal-dots-integration
description: Set up, verify, or troubleshoot TradeJournal's scoped Dots/Jo browser and MCP connections, including isolated demo and journal-fixture environments. Use for connector OAuth, environment activation, receipt comparison, and restart proof; not general trading analysis or unrelated deployment work.
---

# TradeJournal Dots integration

Use this repository-managed skill from a TradeJournal checkout. Read
[CLAUDE.md](../../../CLAUDE.md) first. Existing contracts and current code define
permissions and payloads; this skill supplies the operator sequence learned
from the browser/MCP trials. It does not authorize activation or transmission.

## Select the contract before operating

Read only the contracts for the requested mode:

| Work | Source of truth |
| --- | --- |
| Transport, UI versus tools, model-call boundary | [Integration scope](../../../docs/agent/cloud-mcp-integration-scope.md) |
| OAuth, offline public keys, proxy and isolated service | [D0 runbook](../../../docs/agent/cloud-mcp-d0-runbook.md) |
| Assigned demo reads / immutable saves and retries | [D1](../../../docs/agent/cloud-mcp-d1-contract.md), [D2](../../../docs/agent/cloud-mcp-d2-contract.md) |
| Historical MCP and sealed continuation | [Historical MCP](../../../docs/agent/cloud-mcp-historical-contract.md), [historical replay](../../../docs/agent/dot-historical-replay-contract.md) |
| Cloud-browser identity and sign-in | [Browser contract](../../../docs/agent/cloud-browser-auth-contract.md) |
| Invented journal fixture or separately approved journal export | [Journal contract](../../../docs/agent/cloud-mcp-journal-contract.md) |
| Synthetic browser replay | [Sample replay](../../../docs/agent/dot-sample-replay-contract.md) |

Keep independent practice, instructed operational proofs, and journal coaching
distinct. Identify the requested mode, actor/assignment, data class, allowed
actions and current authorization from fresh evidence. Historical provider bars
can be demo-only while `sample_data=false`; do not relabel them as invented.
Past receipts establish past observations, not current service health or grants.

## Prepare and activate within the requested scope

1. Inspect the current source revision, existing connector binding and relevant
   service/configuration state without exposing secrets. Preserve existing demo
   identities, assignments and receipts. Do not repoint a connector unless that
   specific switch is authorized; journal setup uses its separate connection.
2. Prepare the contract's reviewed bundle/configuration and a concrete change
   list before any required approval. Use the repository staging helper for a
   journal fixture. Check exact file inventory, digests and permissions; refuse
   unexpected existing destinations. Do not turn disposable CI smoke installers
   or prior temporary shell scripts into a retained-server deployment procedure.
3. Apply the contract's activation gates. Existing explicit user authorization
   persists; ask only for missing scope or confirmation required by the active
   tool policy. If automatic approval rejects an action, explain its reason and
   continue only independent permitted work. Never route around the rejection.
4. For OAuth, read the actual issuer and the exact callback displayed by the
   connector setup form. Apply the current contract's client, audience, scopes,
   code/PKCE and refresh settings. Do not guess callbacks, add wildcard access,
   reuse an unrelated subject, or widen grants to resolve a login failure.
   Hand private login/consent steps to the user when required by the tool.
5. Install only the authorized isolated resources. Follow the runbook/templates
   for separate identities, files, Unix sockets and public proxy routing. Keep
   incomplete bindings disabled. Validate proxy configuration before reload and
   preserve existing routes. Verify fresh public keys and fixture/export age;
   refresh through the approved mechanism rather than extending expiry limits.
6. Verify startup, refusal cases and bounded restart using the relevant contract.
   A socket can reactivate its service: stop both when shutdown is intended.
   Rollback targets only resources introduced by this activation and preserves
   prior receipts/exports. Do not expose the broad local MCP or private API.

This path must not silently start provider/model API calls or add paid inference
fallbacks. Connector setup, successful OAuth and tool availability are separate
from evidence of actual Jo access. Journal fixture acceptance does not authorize
real journal export, production database access or scheduled refresh.

## Use the browser and MCP for their respective proof

Use available purpose-built tools for exact reads, saves and receipt retrieval.
Use supported browser control for login, visible UI comparison, reload/reopen,
and an explicitly authorized replay. Follow the current browser tool's entry
point and returned documentation; do not depend on remembered API method names,
tab IDs, accessibility indices or private browser endpoints.

Refresh page state after navigation or mutation. Prefer semantic locators for
repeated forms; inspect a screenshot when controls lack labels. Read the relevant
section instead of dumping whole conversations, account pages or credentials.
The user's local browser and Jo's cloud browser are separate acceptance surfaces.

For a practice proof:

- Confirm the fresh profile/run matches the assigned actor, mode and evidence.
  Check the allowed catalog before writing. Retrieve existing receipts first.
- Save only the authorized choice. After an uncertain save, read its receipt
  before retrying; an exact retry must return the same entire choice without a
  duplicate. Never bypass refusal through the UI or a different account.
- Compare immutable IDs, rationale, plan, evidence and hashes with the visible
  UI. State precision limits: whole-second UI timestamps do not verify receipt
  microseconds or fields absent from the page. Keep historical cutoff, provider
  retrieval, real deadline and receipt time separate.
- Start an authorized own TAKE replay once. WAIT/SKIP create no entry. Report
  guard rejection, no fill or unresolved outcomes as observed; report outcome
  fields only when present. Known continuation makes this an operational proof,
  not an independent recommendation or evidence of trading edge.
- Reload/reopen, then perform only the approved service restart. Compare fresh
  receipts before/after. Confirm MCP still withholds continuation and replay
  results after the browser replay, as required by the historical contract.

For journal acceptance, follow the journal contract's exact catalog, exclusions,
pagination, expiry and revocation tests. Preserve unknown P&L as missing. If the
export digest changes between pages, restart the read against one fresh export.

## Troubleshoot and report

Read [troubleshooting](references/troubleshooting.md) when a step fails. Separate
local fixture, native CI, installed service, public HTTPS, actual Jo and user-
observed evidence. Report completed observations, remaining gates and any paused
handoff; do not call setup complete on staging or OAuth success alone.

For repository changes, use [verification](../../../docs/agent/verification.md)
and [normal review](../../../docs/agent/pr-review.md). Skill instructions are
behavioral changes, not prose-only exemptions. Keep credentials, tenant/client
bindings, live hostnames, receipt IDs and temporary session state out of this
skill; store operational evidence only in the appropriate private task record.
