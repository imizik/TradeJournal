# Future Dots integration

This is a handoff for connecting a future Dots client to TradeJournal. It does
not establish that Dots supports MCP, that a connection exists, or that a cloud
agent can reach this installation. Keep TradeJournal as the owner of decision
records, frozen market context and any later paper outcomes.

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
slippage parameters. P0 still needs a selected universe and a frozen operating
example before any plan can be considered prospectively eligible.

## Requirements before connecting another agent

1. Confirm Dots' actual supported transport and authentication contract. Do
   not assume it can launch a local stdio process or call this API.
2. Create a separate shadow-agent tool profile that includes only market
   context and the agent's own decision records. Exclude fills, journal trades,
   account data, Isaac's decisions and all journal-analysis tools.
3. Enforce the same capability policy in backend services. Hiding tools from an
   MCP catalog is not access control. Current private API routes have no
   authentication, and `actor` is caller supplied; neither is a cloud boundary.
4. If Dots is remote, design a separately scoped gateway/token on the private
   host. Do not expose or tunnel ports 8080/8000, do not give the agent raw
   HTTP or shell access, and do not add a proxy that forwards arbitrary API
   routes. Public access requires a new reviewed security design.
5. Test allowlisted tool discovery, denied journal reads/writes at the service
   layer, idempotent decision submission, identity attribution, timeouts and
   failure behavior before enabling a Dots connection.

Until those gates are met, use the existing local MCP adapter for manual
preparation only. The current adapter advertises the existing all-journal
profile as well as A1 tools; do not give it to an independent shadow agent.

## Ownership boundary

Put business rules in `backend/app/engine/decisions.py` and typed HTTP routes in
`backend/app/routers/decisions.py`. MCP or a future Dots connector should only
translate tool inputs and outputs. Do not add Dots-specific columns, callback
formats, schedulers, credentials or a public tunnel to the decision schema.
The implementation sequence and A1/A2/A3 boundaries are in the
[agentic trading roadmap](../agentic-trading-roadmap.md).
