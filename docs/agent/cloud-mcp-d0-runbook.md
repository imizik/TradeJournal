# D0 synthetic cloud MCP trial

**2026-10-08 — local implementation, cloud acceptance pending.** The
[connector scope](cloud-mcp-integration-scope.md) defines D0–D3. This chunk
implements the synthetic resource server and configuration checks, not the
live TradeJournal read adapter. No app database, market providers, account
credentials or application router are imported by the D0 process.

## Implemented contract

[cloud_mcp_d0.py](../../backend/cloud_mcp_d0.py) uses the pinned Python MCP
SDK 1.28.1 and PyJWT 2.13.0. It serves stateless Streamable HTTP at `/mcp`,
with the SDK's protected-resource metadata at
`/.well-known/oauth-protected-resource/mcp`. Its only tool is `get_profile`,
which takes an empty object and returns a fixed synthetic name and a stable
configured `d0_` UUID. It advertises read-only annotations, the profile marker
and the `d0:profile` OAuth scope. It advertises no events or subscriptions.

The selected authentication approach is an external OAuth authorization server
with a predefined client, authorization code + PKCE S256, refresh tokens and
RS256 access tokens. The actual issuer/account is an outstanding cloud-trial
configuration choice; this process does not implement a login or consent page.
Use a maintained issuer rather than repurposing Gmail OAuth or creating a
TradeJournal authorization server in this chunk.

The resource server verifies the signature against the fixed issuer JWKS URL,
exact issuer and singleton resource audience, configured client claim,
subject, expiry and issued time. Token lifetime is capped at five minutes.
The configured subject maps to a synthetic profile; token claims or tool
arguments cannot select an owner or another profile. The current configuration
is reread on every request and tool call, so disabling the probe/profile denies
even otherwise valid tokens. Authentication and scope checks protect both
discovery and tool invocation.

JWKS requests have a five-second timeout, a 64 KiB response cap and no redirects
or environment proxy inheritance. Successful and failed lookups cache for
60 seconds; new signing keys may be unavailable for that period. Tokens never
choose a key URL. Input bodies are bounded at 64 KiB, headers at 16 KiB, and
the CLI limits HTTP concurrency to 16. Requests do not log bearer tokens or
issuer responses. The listener always binds to `127.0.0.1`.

Application-profile revocation is immediate for subsequent requests, including
fresh tokens. Issuer-only JWT revocation can take until token expiry; disconnect
acceptance must therefore include disabling the local profile/connection and
revoking the issuer refresh grant. Restarting the probe preserves profile IDs
only when its stored subject-to-ID mapping is preserved. Never reuse an ID for
a different subject. Changed issuer/client/resource configuration or an in-run
ID remap fails closed until restart.

## Prepare a separate synthetic installation

The user authorized implementation here. Deploying or connecting a trial is
a separate concrete action to select after review. Prepare an isolated
always-on host/install directory for D0, without copying production `.env`,
database, provider keys or broad MCP configuration. A separate VPS directory
under an isolated OS user is an option; a disposable host is preferable when
available. Neither requires Isaac's laptop to remain online.

Use [config.example.json](../../deploy/cloud-mcp-d0/config.example.json) as
the shape. Keep the real file outside Git. Select:

- `issuer_url`: the exact issuer advertised by the external OAuth server.
- `jwks_url`: its published JWKS URL on that same HTTPS origin.
- `resource_url`: one canonical HTTPS resource identifier ending `/mcp` that
  the tunnel-backed discovery and issuer agree on. It is an OAuth audience,
  not a direction to publish the private API. Verify the actual tunnel's
  resource handling during the trial.
- `client_id`: the predefined client registered for the ChatGPT plugin.
  Use the exact callback URI shown by that plugin's configuration; do not
  guess or wildcard it. Configure consent, PKCE S256, refresh and `d0:profile`.
- `client_claim`: `client_id`, or `azp` when the selected issuer uses that claim
  in its access tokens. Set the resource audience to the exact configured URL;
  this probe rejects multi-audience tokens and ID tokens for the OAuth client.
- `profiles`: the approved issuer subject and a newly generated stable
  synthetic UUID, with no real TradeJournal grants. Preserve the mapping
  across reconnects. Keep `synthetic_only` true and `enabled` false until the
  selected trial is ready.

URLs must already match the SDK's canonical HTTPS representation. In particular,
a root issuer without a trailing slash is rejected by this probe rather than
silently normalized. Never change an advertised issuer just to satisfy that
check; select a compatible issuer URL/provider or review support for that exact
issuer before the trial.

Create a dedicated unprivileged OS user/group if using the included
[service template](../../deploy/cloud-mcp-d0/tradejournal-d0.service). Give
it read-only access to the separate D0 source/environment and to a root-owned
configuration file (0640, group `tradejournal-d0`). Only the operator can
replace configuration. Install this template manually on the selected trial
host; it is outside the normal deployment unit directory and is not installed
or started by the release controller. Native systemd sandbox behavior still
needs to be observed on that host.

## Check the issuer and start the selected trial

From the separate probe's backend directory, after installing its pinned
dependencies, validate issuer metadata. The probe needs only the MCP SDK and
PyJWT crypto dependency tree; installing the full application's provider/model
dependencies is unnecessary on this isolated trial host:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install 'mcp==1.28.1' 'PyJWT[crypto]==2.13.0'
```

Then check the selected issuer:

```bash
.venv/bin/python cloud_mcp_d0.py --config /etc/tradejournal-d0/config.json --check-issuer
```

This checks issuer/JWKS identity, endpoint origin, code/refresh support, S256,
the synthetic scope and a supported predefined-client auth method. A 404 on
OAuth metadata permits an OIDC discovery fallback. Other failures and redirects
fail closed. Successful output explicitly says `login_observed: false`.
This check does not prove that the provider issues the required access-token
claims, that the callback works, or that a Dot can sign in.

Set `enabled` true only in the approved synthetic configuration, then start the
service manually or run its CLI on loopback:

```bash
.venv/bin/python cloud_mcp_d0.py --config /etc/tradejournal-d0/config.json --port 8788
```

The process refuses missing/invalid/disabled configuration and refuses the
owner/frontend/private-API ports. No public listen address is an option.

## Connect through Secure MCP Tunnel

Use the [official tunnel setup](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
for the selected account. Confirm account/organization/workspace permissions,
association, current charges/limits and a runtime key restricted as supported
by the Platform. Use the official client release and its actual current CLI;
keep its version and binary provenance in the trial record.

Run the tunnel client beside D0, targeting only `http://127.0.0.1:8788/mcp`.
Keep its own runtime key in protected configuration, separate from both the
probe and TradeJournal. Its admin UI stays on loopback. Do not target the
existing stdio adapter, ports 8080/8000, an owner frontend or arbitrary HTTP
callouts. The OAuth authorization server must still be reachable for login
and token exchange; the tunnel does not supply that reachability.

In ChatGPT Plugins, add a custom MCP server using the tunnel connection,
configure OAuth with the registered client, and install the resulting private
plugin. Verify resource metadata/challenges, the consent scope and the returned
profile in the actual Dot. Do not publicly submit the plugin or enable live
TradeJournal operations as part of D0. If the account cannot use this path,
record the failure and select the scope's authenticated HTTPS fallback before
making any ingress change.

## Acceptance record and stop path

Record exact deployed source and SDK/protocol/client versions, host isolation,
issuer/client choice, granted synthetic scope, account/workspace support and
confirmed costs/limits. Keep all credentials and access-bearing addresses out
of chat, repository evidence and screenshots. Observe:

1. Actual Dot OAuth login, one discovered `get_profile`, and one valid result.
2. The same profile after token refresh, reconnect and service restart.
3. A tool call while Isaac's laptop is offline, executed on the always-on host.
4. Rejection of an unrelated identity, wrong scope and a disabled local profile.
5. Disconnection and issuer refresh-grant revocation; subsequent valid-token
   calls must still be denied by the disabled local profile.
6. Stop both probe and tunnel services, unlink the plugin, and confirm no trial
   listener or subscription remains. D0 creates no subscription to begin with.

For local revocation, atomically replace the root-owned configuration with
`enabled: false` for the relevant profile or entire probe, preserving IDs and
file permissions. Existing process requests recheck that file; do not require
a restart merely to revoke. Stop the probe/tunnel afterward as appropriate.
The synthetic process never controls existing paper monitoring or owner access.

## Verification evidence

[Resource-server tests](../../backend/tests/test_cloud_mcp_d0.py) exercise
generated RSA tokens and mocked issuer keys, the actual SDK HTTP app, profile
continuity, authorization denial and request limits. An in-memory OAuth issuer
and the maintained SDK OAuth client exercise protected-resource discovery,
predefined-client authorization code + PKCE, exact resource indicators, MCP
initialization/tool discovery/call, refresh and rejection after local disable.
The negotiated fixture protocol is `2025-11-25`; no MCP 2.0 Events support is
claimed. The
[issuer-check tests](../../backend/tests/test_cloud_mcp_d0_issuer.py) check
discovery compatibility and origin/error handling. These are isolated fixtures;
external issuer login, the Secure MCP Tunnel, a real Dot, laptop-off use and
native Ubuntu isolation remain unobserved until the trial above.

Final local verification on 2026-10-08: the complete isolated
`scripts/verify.sh` run passed backend/deployment lint, import boundaries,
**1,713 backend tests (33 skipped)**, frontend typecheck/lint/build,
**193 ordinary browser tests** and **three authenticated browser scenarios**.
The backend total includes **42 D0 resource/issuer checks**. Documentation
navigation/freshness checks passed **54 tests (one skipped)**. These results
establish the local implementation and existing-app regressions; they do not
close the actual cloud acceptance gates above.
