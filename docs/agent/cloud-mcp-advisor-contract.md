# Dormant advisor-only MCP fixture slice

Selected 2026-10-11. This extends the [manual advisor handoff](advisor-shadow-contract.md#phase-2-local-manual-jo-handoff) with an offline-tested transport. It is not activated or connected to Jo. Journal connectors, identities, grants, exports and services remain unchanged.

## Boundary and catalog

The standalone `backend/cloud_mcp_advisor.py` adapter exposes exactly:

- `get_profile()` returns an opaque separate `advisor_<UUID>` profile.
- `get_advisor_request()` returns one assigned frozen invented packet, explicit question/user plan and only that request's own saved advisor receipt, or null before a save. It has no selector.
- `save_advisor_answer(packet_sha256, request_sha256, answer)` saves one cited answer. Assignment/run/version come from the server binding. No caller identity, retry key or other fields are accepted.

There are no lists, search, journal, live-data, human/shadow-choice, continuation, reveal, provider/model, order, paper-arm or scheduling tools. The adapter imports no application/database module. It forwards the same bearer only over an operator-owned Unix socket to fixed GET `/cloud-mcp/advisor/request` or POST `/cloud-mcp/advisor/answer`. Redirects, proxy environment, automatic retries and fallback credentials are disabled. Five-second I/O and ten-second total deadlines, 64 KiB input/output bounds and serving concurrency limits fail closed instead of truncating evidence.

`backend/cloud_mcp_advisor_bridge.py` is a separate minimal backend app, never imported or mounted by `app.main`, the journal bridge or the shadow gateway. It exposes only those two routes, without docs/OpenAPI. Every request independently verifies the signed bearer, current offline keys, exact issuer/client/subject/audience and required scopes. Browser cookies, service/gateway/bootstrap headers, query selectors and duplicate Authorization headers refuse access. Four concurrent requests, ten-second bounded body reception and two-second SQLite writer waits are bounded independently. The supported executables accept only inherited listening Unix sockets; no TCP-serving CLI fallback exists.

A separate strict `advisor_only=true` configuration binds exactly one advisor subject/profile/version to assignment UUID, run UUID, packet SHA-256 and request SHA-256. The resource path must be `/advisor/mcp`, distinct from the existing `/mcp` journal/practice audiences. Scopes are `advisor:profile`, `advisor:read` and `advisor:write`; no journal, practice or D0 scope is borrowed. Reads need profile/read; writes need all three. Tokens live at most 300 seconds. Public-key snapshots expire and never trigger issuer network access during serving.

Configuration `enabled` and profile `enabled` are read on every token verification. Identity, binding version, assignment/run/digests, resource and socket changes require a deliberate restart and refuse the current process. The persisted assignment's enabled state and original expiry independently apply to every request read, receipt read and save, including exact retries. Profile-only discovery returns no assigned content. Revoking write scope alone preserves authorized active request reads; revoking the profile or assignment refuses both. Existing owner GET recovery after assignment expiry/revocation remains available.

The backend database filename is a separate startup argument, absent from the adapter's OAuth configuration. Startup requires an existing private isolated SQLite file with the .db suffix, current migration head and invented fixture assignment. The backend executable re-execs before importing application engines with dotenv disabled and no ambient provider/model/database credentials. Both serving factories reject those credentials; the adapter has no database role. Socket file permissions, process mounts/UIDs and native namespace restrictions must be reviewed before any later activation. Source-only isolation does not establish those operating-system controls.

## Ledger, provenance and recovery

The owner first creates the existing immutable versioned handoff through the private UI. That durably records assisted disclosure unless all human choices were already frozen. The connector cannot create or change the question, plan, request, packet or assignment. It rechecks the invented fact projection, stored context/packet integrity, pinned request identity and receipt digest. Only original opportunity/fact citation pairs are valid; answer prose is caller-unverified interpretation.

The save reuses `advisor_import`, its shared SQLite writer lock and immutable ledger. OAuth/config permission and assignment binding are checked under that lock after bounded body reception and again immediately before the first commit. Assignment revocation uses that same writer lock. Concurrent identical saves and identical manual/MCP retries return the original receipt; changed content conflicts. No decision record, paper event, provider request or scheduled job follows an advisor save.

The preserved owner export retains its original `transport=manual-paste` bytes. The MCP wrapper separately labels `request_origin_transport=manual-paste` and `delivery_transport=oauth-mcp`. A fresh MCP answer receipt records `transport=oauth-mcp` within its receipt SHA-256; existing manual receipts retain their original transport and digest, including when recovered by an MCP retry. The private UI displays the saved receipt transport and cited answer on reload/reopen. Independence remains unverified, and actual model/usage/cost remain unavailable.

After any uncertain save, read `get_advisor_request`, compare the complete receipt `submitted_output` with the intended server-derived envelope, and only then explicitly retry if no receipt exists and the grant remains active. A different saved answer is an immutable conflict. No automatic retry, journal fallback or browser permission bypass is supported. Hashes prove content equality, not model identity, factual interpretation, independence, usefulness or trading edge.

## Dormant setup, replacement and rollback gates

This slice adds dormant source and offline tests. The existing `deploy/build.py` archives tracked backend source and copies it into normal release artifacts, so the three advisor modules ship through that path. No advisor units, socket mounts, reverse-proxy routes, public listener, grants, key refresh, credentials or connector registration are added; normal releases do not start or activate this advisor entrance. The repository's normal release deployment still applies. New fixture preparation, actual invented-packet transmission and signed-in Jo acceptance need the owner's separate approval.

For later review, a disabled configuration has this shape (placeholders are not working grants):

```json
{
  "enabled": false,
  "advisor_only": true,
  "issuer_url": "https://advisor-identity.example.test/",
  "resource_url": "https://advisor.example.test/advisor/mcp",
  "jwks_url": "https://advisor-identity.example.test/.well-known/jwks.json",
  "jwks_file": "/etc/tradejournal-advisor/public-keys.json",
  "client_id": "separately-approved-advisor-client",
  "client_claim": "client_id",
  "backend_socket": "/run/tradejournal-advisor/backend.sock",
  "profiles": [{
    "subject": "separately-approved-advisor-subject",
    "id": "advisor_00000000-0000-0000-0000-000000000001",
    "enabled": false,
    "binding_version": 1,
    "assignment_id": "00000000-0000-0000-0000-000000000002",
    "run_id": "00000000-0000-0000-0000-000000000003",
    "packet_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
    "request_sha256": "0000000000000000000000000000000000000000000000000000000000000000"
  }]
}
```

Before starting later: review exact source/dependencies, current fixture/export/expiry and separate OAuth consent, private files/socket permissions and native process/network isolation. Keep root-private recovery copies. The adapter command is `.venv/bin/python cloud_mcp_advisor.py --config <private-advisor-config>`; the backend command is `.venv/bin/python cloud_mcp_advisor_bridge.py --config <private-advisor-config> --database <private-invented-fixture.db>`. Both require a separately supplied systemd-style listening Unix FD and refuse ordinary direct launch. These commands do not create sockets, grants or services. A future unit/ingress proposal must enforce no IP access for the adapter and mount only its config/public keys/Unix bridge, with the backend mounted only to this isolated fixture database and public binding. Do not reuse owner/journal identities or expand the journal bridge.

Stop and disable socket activation before replacing either process; disable the advisor profile/config and persisted assignment when retiring the trial. Start only the approved standalone backend and adapter together after verifying their bindings/keys. They have no dependency on the journal or existing demo namespace/service group. For rollback, stop both optional sockets/processes, restore the verified prior source/config or leave this entrance absent, and keep the fixture ledger so the owner can recover original receipts. Do not rotate journal credentials, alter journal permissions or rewrite receipts. Revocation at the OAuth issuer is a separate owner action.

## Verification and remaining acceptance

`backend/tests/test_cloud_mcp_advisor.py` uses generated signed tokens, invented fixture data and offline public keys. It covers exact catalog/schema, packet/request identity, valid/invalid citations, singleton selectors, direct-route/identity/scope denials, immutable sequential/concurrent/manual retries, grant/key/assignment expiry/revocation, before-commit rollback, lost-response recovery, stored-content tampering and real disposable Unix-process replacement equality. `frontend/e2e/advisor-shadow.spec.ts` covers existing manual receipt recovery plus a real SDK/generated-token MCP save into the browser fixture database, cited answer/transport rendering and exact receipt equality after reload/reopen at 390px.

Run focused checks and repository fast/full verification; completion results and revision belong to the PR record. Native Linux service/mount/namespace setup is not tested by this source-only slice. Actual separate OAuth consent, Jo catalog/read/save, exact receipt/UI/reopen/restart equality and observations of Jo's account/tool/data isolation remain later acceptance gates. Generated-token, local browser and Unix IPC fixtures establish neither actual Jo acceptance nor VPS/laptop-off operation. No real journal data, provider capture, order, arm, recurring schedule or production activation is authorized here.
