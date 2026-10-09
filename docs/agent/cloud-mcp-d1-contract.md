# D1 assigned sample Practice reads

2026-10-09 — first useful D1 slice activated after PR #182 merged. Actual Jo
list/detail calls succeeded through OAuth; Jo reported exact frozen packet,
own-choice and existing replay agreement with its separately signed-in cloud UI.
Backend successful requests and persisted decision hashes were independently
corroborated. D0 remains the connected synthetic profile probe. D1 adds
only `list_practice_runs(day)` and `get_practice_run(run_id)` to that profile
catalog. Market, journal, standalone decision/paper tools and writes remain
later scope. See the [cloud scope](cloud-mcp-integration-scope.md) and
[D0 runbook](cloud-mcp-d0-runbook.md).

## Contract

- Link the one previously approved OAuth subject/client/resource/profile to
  **one existing ordinary sample assistant principal and its current version**.
  Select Jo's current MU/NBIS exercise; linking never creates owner access.
  OAuth identifies the approved account connection, not a particular chat/Dot.
- Domain reads require both `d0:profile` and `practice:read`. Discovery advertises
  both; profile-only tokens still call `get_profile`. The added scope requires
  separate consent before activation. Reuse the stable D0 profile ID/name.
- Every request independently checks issuer, exact audience, approved client,
  subject, signature, maximum 300-second token lifetime and unexpired offline
  public keys in both adapter and backend. No issuer request happens in serving.
- The backend also checks the principal's enabled state, version, credential
  expiry and current grants. Require exactly one canonical run UUID, one or
  two MU/NBIS symbols and `journal_read=false`. Current grant changes take effect
  immediately. Disabling a profile or changing its startup binding refuses
  still-valid tokens; changing a binding requires an explicit service restart.
- Two distinct GET paths under `/cloud-mcp/practice/runs` use ordinary identities.
  Browser cookies, gateway/bootstrap headers and service keys cannot substitute
  for this Bearer token. Existing browser ingress, session and CSRF checks stay
  in place; a connector Bearer grants no existing domain routes or writes.
- Require all four opt-in flags plus the validated isolated sample factory.
  Flags alone cannot enable a production/legacy app. Fixture provenance,
  disabled model/jobs and the sample network namespace remain required.
- Reuse `sample_practice.view` directly. Return only the assigned prepared
  simulated run, allowed symbols and this principal's own saved choices.
  Preserve immutable evidence/record hashes, source/capture times, units,
  missing states, policy hashes and simulated labels. Reads do not prepare,
  recover, reveal, start or recompute replay. Hidden continuation stays hidden
  until that assistant has already started its own TAKE replay through the
  separately authorized UI; thereafter return the existing committed receipt.
- Responses carry `d1-sample-practice-v1`, `sample_data=true`, UTC `read_at`,
  New York date/time-zone and a relative `/daily/YYYY-MM-DD` path. That path
  conveys no login or access. Keep full frozen evidence within a 1 MiB response
  limit; oversize/unavailable responses fail instead of truncating evidence.
- Adapter forwards the same token only through an operator-owned Unix socket
  to a fixed HTTP origin/path. No redirects, proxy environment, retries or
  fallback credential. Five-second I/O timeout and ten-second total deadline;
  16 concurrent serving/bridge requests. Backend shares the existing persisted
  240 requests/minute principal budget with browser access. Security budget
  and denial audit metadata may change; domain records must not change.
- Tools handle precise records; the separately signed-in assistant UI handles
  charts, visual behavior and review flow. A tool denial cannot be bypassed in
  the UI. Rationale/news/notes remain untrusted text. There is no model API,
  sampling tool, scheduler or provider read in this slice.

## Manual installation and rollback

The [templates](../../deploy/cloud-mcp-d1/config.example.json) are manual-only;
normal releases do not install/start D1. Preserve a root-private snapshot of
the current source, units/drop-ins, environment, D0 config and dependencies
before changes. Record exact reviewed source and archive hashes. Do not print
subject, keys, tokens, gateway secrets or private credential files.

1. Wait for reviewed-head local checks and native Ubuntu CI. Read only current
   sample principal ID/version/expiry, run/date and MU/NBIS grants. Reuse that
   existing identity; do not rotate its UI credential or grant more runs.
2. Check isolated API dependencies: this adapter/backend is tested with
   `mcp==1.28.1` and `PyJWT[crypto]==2.13.0`. The existing trial was observed
   with other versions on 2026-10-09. Stage a separate pinned Linux virtualenv
   and verify imports/startup before switching; retain the old environment for
   rollback. Do not silently reuse an incompatible SDK or pip-mutate a live venv.
3. Use the [bounded updater](../../deploy/dot_trial_update.py) with its exact
   `SOURCE_FILES` set, including the new middleware/router/shared verifier.
   Keep the installed Linux frontend dependencies and existing data/credentials.
   Supply a portable copy of the existing compiled frontend if no UI change is
   needed. Verify the selected source set against the installed runtime before
   changing it; new dependencies/files must exist before importing `app.main`.
   The updater pauses installed D1 socket/bridge activation before replacing
   files or rolling back. It restores only a previously active socket after
   readiness succeeds; an absent/inactive entrance stays off, and failed recovery
   leaves it stopped. It never boot-enables D1.
4. Stage `cloud_mcp_d0.py`, `cloud_mcp_d1_common.py`, `cloud_mcp_d2_common.py`
   and `cloud_mcp_d1.py` in the separate D0 runtime. The D2 shared module is
   required even when choice writes are disabled. Its pinned standalone
   environment already provides the SDK. Keep D0 source/config snapshots and
   profile ID for rollback.
5. Prepare `/etc/tradejournal-d1/config.json`, root:tradejournal-d0, directory
   0750/file 0640, from the disabled example. Use the same issuer/resource/
   client claim/key snapshot as D0, and the selected principal ID/version.
   Keep it disabled until approval. Backend and adapter read the same link;
   neither can edit it or the public-key snapshot.
6. Install the updated D0 public-key publisher unit: it masks the entire D1
   config directory so the networked publisher cannot read OAuth/profile grants.
   Reload systemd; verify that restriction before enabling the new link.
7. Obtain approval for the concrete `practice:read` grant on the existing
   public OAuth client/API, then register that permission and reconnect/consent.
   Do not add model/API credentials or increase the approved refresh lifecycle.
8. Install [sample API drop-in](../../deploy/cloud-mcp-d1/sample-api.conf),
   [Unix socket](../../deploy/cloud-mcp-d1/tradejournal-d1-reads.socket),
   [namespace bridge](../../deploy/cloud-mcp-d1/tradejournal-d1-reads.service)
   and [MCP selection drop-in](../../deploy/cloud-mcp-d1/mcp.conf). API reads the
   public snapshot through a supplementary group and cannot read D0 config.
   MCP remains AF_UNIX-only and cannot read sample DB/owner configuration.
   The bridge joins only the sample API namespace and follows its restart.
9. Enable the approved link and reload. Stop the read socket/bridge, then stop
   the sample frontend bridge sockets/services and all three sample services.
   Start the sample API, both sample frontends and their bridge sockets together
   using the updater's service sets/readiness check; confirm all three share the
   same new namespace. Restart the isolated MCP and start the read socket
   manually. Restarting just the API can strand existing frontends in its old
   namespace. No new hostname, Caddy route, public backend port,
   production configuration, service credential or boot enablement is added.
   Confirm service UID/mount permissions, fixed 8091 namespace target, distinct
   host namespace, immediate revocation and restoration, and fresh keys.
10. Refresh the plugin catalog, consent to the new scope and test with the actual
    Dot: list the assigned date, retrieve the listed UUID, compare frozen record
    hashes/own replay receipt with its assistant UI, and record visible UI proof.
    A generated-token fixture does not establish OAuth or actual Dot acceptance.

Rollback: stop `tradejournal-d1-reads.socket` and its bridge first; remove the
API/MCP D1 drop-ins, restore the previous API source/environment and D0 source/
config, reload systemd and restart the isolated API/frontends/bridges as one
namespace group plus MCP. Verify the
synthetic profile still works and browser permissions are unchanged. Keep the
publisher's D1 mask; disabling/stopping D1 cannot widen D0. Disable/revoke the
OAuth permission/refresh grant separately at the issuer when disconnecting.
The existing sample shutdown revokes principals and stops the optional D1
socket/bridge before the API, preventing socket-driven reactivation.

## Evidence and remaining acceptance

Local signed-token tests exercise the real restricted projections, principal
and link revocation, mixed identities, flags, unassigned resources, shared
budget, own-only choices, preserved sealed/committed replay and read invariance.
SDK fixtures check catalog, metadata and same-token forwarding without redirects.
The [native smoke](../../deploy/cloud-mcp-d1/smoke.py) runs only on disposable CI,
with actual socket activation, namespace bridge, independent backend auth,
restart, expired keys and MCP IP denial. D0 native smoke additionally proves
the separate publisher cannot read D1 bindings.

Native CI passed on the merged D1 candidate; live setup, new-scope OAuth consent
and fresh actual Dot tool/UI comparison were observed on 2026-10-09. The assigned
sample records stayed unchanged; later unrelated market-demo additions were
separately identified. Physical laptop-off D1 operation and VPS reboot persistence
remain unobserved. Purchased-credit account settings were checked separately
at acceptance and can change; this code has no API inference billing path.
The selected [D2 increment](cloud-mcp-d2-contract.md) adds opt-in own sample
choices; its implementation/live evidence is separate from this completed read
acceptance.
