# Dormant advisor-only MCP fixture slice

Selected 2026-10-11. This extends the [manual advisor handoff](advisor-shadow-contract.md#phase-2-local-manual-jo-handoff) with an offline-tested transport and a [disabled activation bundle](../../deploy/cloud-mcp-advisor/README.md). It is not activated or connected to Jo. Journal connectors, identities, grants, exports and services remain unchanged.

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

The existing `deploy/build.py` archives tracked backend/deploy source and copies it into normal release artifacts, so advisor modules and disabled templates ship through that path. The normal release installer does not install advisor units, mount advisor sockets or include the proposed proxy; normal merge/archive/install does not start this advisor entrance. The repository's normal release deployment still applies. Offline staging creates only new private disabled invented verification data. Retained fixture/grant creation, installation, ingress/network publication and retained startup require the owner's separate concrete approval; actual invented-packet transmission and signed-in Jo acceptance remain later approval gates.

`deploy/advisor_mcp_stage.py` inventories private source, disabled configuration/public-key placeholders, a fresh migrated invented SQLite and the original owner handoff. It refuses collisions, symlinks, mode/byte/inventory changes and removes only its newly created directory on staging failure. It never installs services or reads a journal database. The manual capability is discarded. Optional already verified release wheels are hashed; no dependency download occurs during staging/install. A disabled/expired staged assignment is not silently extended into a retained trial.

`deploy/advisor_mcp_control.py` is a separate manual controller, absent from the normal installer. Installation requires the reviewed root-owned bundle manifest SHA256 and leaves four units inactive, with no Install section or timer. Before invoking any installed interpreter, preflight verifies the complete recorded runtime, including virtual-environment dependencies/import hooks/bytecode, modes/owners and resolved interpreter targets. No generated-cache exclusions apply; post-install interpreters use `-B`, preserved by the backend clean re-exec. Added/changed/deleted executable inputs refuse before execution. Separate activation approval binds that runtime inventory and the current installation/config/public-keys/fixture hashes, independently verifies fresh keys and the active pinned invented assignment, and starts only both advisor socket/process pairs. It does not create OAuth grants, edit the proxy or contact the issuer. Startup failure attempts stopping both pairs. Stop attempts sockets first and processes next even after drift or one failed command. Rollback stops first, removes only unchanged recorded units, and preserves users/source/config/original export/SQLite receipts for owner recovery; it never rewrites a receipt or journal permission.

Two separate nologin UIDs (`tj-advisor`, `tj-advisor-backend`) serve inherited Unix sockets. Private network namespaces and AF_UNIX-only families deny IP creation. Empty read-only `/etc`, `/var`, `/opt`, `/run` mounts expose only the specific read-only source/config and adapter bridge socket; only the bridge mounts its private SQLite directory writable. Socket owners/modes, exact MCP/discovery proxy paths, limits and approval-gated commands are documented in the [bundle runbook](../../deploy/cloud-mcp-advisor/README.md). Manual public-only key freshness is at most one hour; no key refresh timer, recurring schedule or paid/provider API path is added. Source-only staging does not prove native controls or installed acceptance.

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

Before any later retained installation/start, review exact source/dependencies/artifact, current fixture/export/expiry and separate OAuth consent, private files/socket permissions and native process/network isolation. Keep root-private recovery copies. The adapter command is `.venv/bin/python cloud_mcp_advisor.py --config <private-advisor-config>`; the backend command is `.venv/bin/python cloud_mcp_advisor_bridge.py --config <private-advisor-config> --database <private-invented-fixture.db>`. Both require a separately supplied systemd-style listening Unix FD and refuse ordinary direct launch. These commands do not create sockets, grants or services. The disabled templates enforce no IP access and the private mounts above; publication of a concretely replaced/validated proxy remains separate. Do not reuse owner/journal identities or expand the journal bridge.

Stop and disable socket activation before replacing either process; disable the advisor profile/config and persisted assignment when retiring the trial. Start only the approved standalone backend and adapter together after verifying their bindings/keys. They have no dependency on the journal or existing demo namespace/service group. For rollback, stop both optional sockets/processes, restore the verified prior source/config or leave this entrance absent, and keep the fixture ledger so the owner can recover original receipts. Do not rotate journal credentials, alter journal permissions or rewrite receipts. Revocation at the OAuth issuer is a separate owner action.

## Verification and remaining acceptance

`backend/tests/test_cloud_mcp_advisor.py` uses generated signed tokens, invented fixture data and offline public keys. It covers exact catalog/schema, packet/request identity, valid/invalid citations, singleton selectors, direct-route/identity/scope denials, immutable sequential/concurrent/manual retries, grant/key/assignment expiry/revocation, before-commit rollback, lost-response recovery, stored-content tampering and real disposable Unix-process replacement equality. `frontend/e2e/advisor-shadow.spec.ts` covers existing manual receipt recovery plus a real SDK/generated-token MCP save into the browser fixture database, cited answer/transport rendering and exact receipt equality after reload/reopen at 390px.

`backend/tests/test_advisor_mcp_bundle.py` covers disabled migrated preparation, inventory/path/mode tampering, collisions, inactive install, partial failure, startup failure and receipt-preserving both-pair stop/rollback with fake host commands. Deployment CI adds `deploy/cloud-mcp-advisor/smoke.py`, guarded before mutation to the disposable Ubuntu runner, to exercise actual separate service UIDs/mounts/Unix activation/IP denial and exact TLS routes with generated tokens/invented data. It verifies independent bridge auth, cited save, uncertain-response read/retry/conflict, owner GET equality, process replacement, token/key expiry and config/assignment revocation, followed by both-pair shutdown and receipt-preserving rollback/cleanup. It does not contact an issuer, provider or Jo and is not a retained installer.

Run scoped causal/static/docs checks followed by full verification or the [CI-backed path](verification.md#ci-backed-verification); exact revision/job/step results belong to the PR record. Native proof remains pending until the applicable actual CI step passes. Actual retained installation, separate OAuth consent, Jo catalog/read/save, exact receipt/UI/reopen/restart equality and observations of Jo's account/tool/data isolation remain later acceptance gates. Generated-token, local browser and disposable native fixtures establish neither actual Jo acceptance nor VPS/laptop-off operation. No real journal data, provider capture, order, arm, recurring schedule or production activation is authorized here.

## Direct owner review in TradeJournal (dormant)

`/advisor-review` retrieves the single isolated advisor request and exact saved
receipt through `GET /api/advisor-owner`. It does not repoint the application
database, import a snapshot, accept a file or expose another advisor MCP tool.
The existing manual Practice receipt still uses the same pure receipt/citation
component and retains its write/recovery flow and original receipt bytes.

The Node BFF requires an explicitly configured `TJ_ACCESS_PROFILE=owner` and an
uncached enabled owner session from the existing access backend before opening
an operator-pinned Unix socket. Default `private_legacy` access is insufficient;
assistant and anonymous access cannot retrieve the record. It revalidates that
owner session after the bounded reader response, refusing revocation during the
read. No browser cookie, owner token, gateway secret or advisor OAuth credential
is forwarded to the reader. The BFF has no TCP, redirect, retry, alternate
ledger or backend-proxy fallback. The explicit socket path/owner UID, private
parent directories, file mode and inode are checked before and after the read.

`cloud_advisor_owner.py` is a separate owner-only process, absent from the main
backend and advisor OAuth bridge. Its only route is `GET /owner/advisor` without
selectors, body or credentials. An inherited AF_UNIX listener supplies the
kernel peer UID; only the reviewed frontend UID is accepted, including on each
new connection. Configuration and socket drift fail closed before and after
reads. No journal/practice/browser identity is accepted by that private route.
The reader uses an existing private migrated invented SQLite through `mode=ro`,
`query_only=ON` and one read transaction. It returns only the pinned immutable
handoff, exact receipt, assignment recovery status and read time. Packet/request
identity, receipt digest and original fact citations are checked against the
ledger; no shadow choices, capability, human decisions or other assignments
leave. Limits are 64 KiB per response, 16 KiB request headers, four concurrent
reads, five seconds per BFF/read and two seconds of SQLite work/lock waiting.

Owner recovery deliberately survives advisor assignment expiry/revocation and
OAuth/key expiry. Owner-session authority is still required. An absent receipt
is not proof a pending save failed; reload/reopen reads again and never submits
an advisor retry. The view retains invented-demo, missing-input, advisor-first
assisted-disclosure, provenance and independence-unverified labels. Model,
usage, cost, factual interpretation and usefulness remain unverified.

The optional owner units and disabled invalid-placeholder configuration live
beside the advisor templates but are excluded from the existing four-unit
stager/controller. Normal release packaging ships source; normal install and
merge do not install, start, enable or mount the optional reader. The frontend
route remains unavailable unless separately approved owner/socket settings are
installed. See the [owner reader runbook](../../deploy/cloud-mcp-advisor/README.md#optional-direct-owner-reader)
for the distinct runtime/UID approval and stop/rollback boundary. Disposable
browser and Ubuntu native CI proof establish fixture behavior, not installed
host activation or actual Jo acceptance.
