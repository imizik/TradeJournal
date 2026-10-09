# D2 first increment: own sample choices

2026-10-09 — selected after D1 live OAuth and actual Dot read/UI comparison.
This increment proves demo writes before considering real journal access.
It does not implement the whole proposed D2 context-creation catalog.

## Selected interface

- Reuse the one ordinary linked sample principal, one explicitly granted
  prepared MU/NBIS run, immutable frozen contexts and existing sample validators.
  Prepare a fresh operator-owned exercise for live acceptance; never overwrite
  existing choices or silently broaden grants. No assistant context creation.
- Add `record_practice_choice(opportunity_id, decision, rationale,
  wait_condition=null, wait_expiry=null, plan=null)` and
  `get_practice_choice(opportunity_id)`. Only canonical opportunity UUIDs from
  the assigned run are accepted. Unknown fields, actor, symbol, context ID and
  caller-selected retry keys are refused.
- The fixed private bridge forwards the same bearer only to GET/POST
  `/cloud-mcp/practice/opportunities/{opportunity_id}/choice`. Preserve D1
  limits, independent backend token verification, namespace isolation and the
  denial of cookies/service keys, owner routes and paid model paths.
- Reads require `d0:profile practice:read`. Writes additionally require
  `practice:write`, current `decision_write=true`, existing sample-write flags,
  new `TJ_CLOUD_MCP_DECISION_WRITES=true`, and strict config
  `decision_writes=true` (default false). Existing D1 catalog stays read-only
  unless the operator explicitly starts the opt-in writer catalog.
- The server derives actor/context/symbol and the existing
  `sample:{opportunity_id}:{principal_id}` operation identity. Both UI and MCP
  use the same choice service, preventing duplicate cross-entrance saves.
- Return `d2-sample-choice-v1`, `sample_data=true`, UTC `read_at`, New York
  time zone, relative UI path, run/opportunity IDs, `status` (`recorded` or
  `not_recorded`) and own `choice` (the existing immutable decision projection
  or null). POST also reports `created`. A GET does not create/recover anything.
  An inaccessible opportunity is refused, never described as not yet saved.
- Identical retries return the original receipt, even after the exercise
  deadline; changed content conflicts. New expired choices and invalid WAIT
  limits are refused. Concurrent identical saves leave exactly one record.
- Transport errors after a write can mean the record committed. The tool
  explicitly instructs receipt retrieval before a retry or UI fallback. A
  retrieved receipt is persisted evidence, not a claim that a replay ran.

## Acceptance criteria

1. Real signed OAuth fixtures save TAKE, WAIT and SKIP through MCP to the real
   restricted backend; exact IDs, evidence/record hashes and frozen cutoffs
   match existing UI/API projections. Status remains practice_draft_unarmed.
2. Same-content sequential, concurrent and cross-UI/MCP retries produce one
   immutable record. Changed content conflicts without changing saved bytes.
   A deliberately lost committed response is recovered by own receipt GET.
3. Refuse wrong/expired tokens, missing write scope, revoked/expired/versioned
   principals, disabled flags/config, read-only grants, mixed credentials,
   unassigned runs/symbols, guessed IDs and actor/context/key spoofing.
4. Preserve frozen contexts and other actors' choices. No new job, fill,
   paper arm, reveal or replay event follows from any write/read. Hidden
   continuation remains hidden. Oversize inputs/responses and unavailable
   backend results fail without truncating evidence or leaking private errors.
5. D1 reads/profile and browser saves remain compatible. No schema migration,
   production configuration/data, provider/model request, scheduler, new
   public ingress or boot enablement is part of this increment.
6. Run required local verification and disposable native Unix/namespace smoke;
   record the candidate SHA. Tier 2 fresh general Astra/high and focused
   Sol/medium reviews must cover the final diff, followed by current-head CI.
7. After merge and approved demo setup, obtain concrete new-scope consent,
   test real Dot save/read/UI reload, and restart demo services as the existing
   namespace group before retrieving the same receipt. Fixture/CI evidence
   does not satisfy actual OAuth/Dot acceptance or prove laptop-off operation.

## Operations and remaining evidence

Extend the existing bounded updater and isolated MCP source set only as needed.
Retain root-private recovery materials and existing credentials, receipt data,
OAuth profile ID and refresh lifecycle. Writer permission and demo activation
remain separately reviewable setup; this contract alone does not activate them.
Normal releases keep the sample connector manual-only. On disable/rollback,
stop the reader bridge before replacing API/MCP source, restore verified D1
source/config, and restart API/frontends/bridges together. Previously saved
choices remain readable through the existing D1 projection after write
permission is revoked. No production enablement is selected here.

Implementation and all D2 acceptance evidence are pending.
