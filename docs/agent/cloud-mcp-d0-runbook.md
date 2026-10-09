# D0 synthetic cloud MCP trial

**2026-10-09 — direct HTTPS implementation, actual Dot acceptance pending.**
The [connector scope](cloud-mcp-integration-scope.md) defines D0–D3. Isaac
selected ChatGPT-plan usage with no API credits. The selected connection is
now a private ChatGPT plugin using **Server URL + OAuth**, backed by a dedicated
HTTPS entrance and the offline synthetic service. No OpenAI tunnel or Platform
runtime key is required. This builds D0's transport and spending boundary;
it does not enable real journal reads, domain writes or production ingress.

## Implemented contract

[cloud_mcp_d0.py](../../backend/cloud_mcp_d0.py) uses MCP SDK 1.28.1 and PyJWT
2.13.0. It serves stateless Streamable HTTP at `/mcp` with protected-resource
metadata at `/.well-known/oauth-protected-resource/mcp`. The only tool is
`get_profile`, with empty arguments, fixed synthetic name, stable configured
`d0_` UUID, read-only annotations, the profile marker and `d0:profile` scope.
It advertises no events, subscriptions, sampling or model tools. The service
imports neither the application/database nor any model SDK.

An external maintained OAuth issuer owns login, consent, authorization code +
PKCE S256 and refresh. The predefined client and actual issuer remain trial
configuration choices. The resource server verifies RS256 signatures, exact
issuer, singleton resource audience, configured client claim, subject, issue
and expiry times, and the five-minute maximum token lifetime. The subject maps
to an operator-granted synthetic profile. Token claims cannot select an owner.
Every request/tool call rereads configuration: disabling a profile or probe
immediately denies subsequent calls. Changing issuer/client/resource/key-file
path or an existing subject's profile ID requires restart.

The HTTPS deployment reads a local **public-key snapshot** instead of fetching
JWKS during requests. A snapshot records the configured issuer/JWKS URLs,
`fetched_at`, `expires_at` and 1–16 public RSA verification keys. It is bounded
at 64 KiB, lasts at most one hour, rejects private/weak key material, and is
reread for every verification. Missing, corrupt, future or expired snapshots
fail closed. Removed signing keys take effect immediately. There is no network
fallback. Issuer-only token revocation can otherwise last until token expiry;
always pair disconnect with local profile disable and issuer refresh revocation.

[The HTTPS service](../../deploy/cloud-mcp-d0/tradejournal-d0-https.service)
uses `PrivateNetwork=true`, `RestrictAddressFamilies=AF_UNIX`, native syscall
architecture and no capabilities. It has no environment-file imports; startup
rejects known inherited model/tunnel credentials without printing values.
Production data/configuration, home directories and common privileged IPC
sockets are inaccessible. The process can accept only one inherited listening
Unix stream socket. This deployment targets Ubuntu/systemd; platforms unable
to inspect the listener fail closed.

[The socket unit](../../deploy/cloud-mcp-d0/tradejournal-d0-https.socket)
creates `/run/tradejournal-d0/mcp.sock` with mode 0660 for the probe user and
Caddy group. [The proxy template](../../deploy/cloud-mcp-d0/Caddyfile.example)
terminates HTTPS on a dedicated hostname and forwards only `/mcp` and its exact
protected-resource metadata path to that socket. Other paths return 404.
Authorization headers and the public Host are preserved; D0 ignores forwarded
identity/IP headers. Complete POST uploads have a ten-second deadline, bodies
are capped at 64 KiB, headers at 16 KiB and concurrency at 16. Access logging is
disabled; tokens and issuer responses are not logged.

The original loopback/network-JWKS mode remains available for compatibility and
fixture work, but is **not the selected no-API-credit deployment**. Do not start
its older `tradejournal-d0.service` or a tunnel client for this trial.

## Spending boundary and limits

Dot performs the reasoning through the signed-in ChatGPT product. MCP returns
synthetic data and never invokes a model. The selected deployment has no model
credentials, no model/API fallback, no app/job routes and no outgoing IP
network capability. It cannot use TradeJournal's paid model preparation or
other existing jobs. These are service boundaries rather than prompt promises.

Dot conversations and delegated Work/Codex tasks follow their documented plan
allowances. A connector cannot set or guarantee OpenAI account-level allowance,
purchased-credit or overage behavior. Before a real trial, check the account's
usage controls and keep paid top-ups/overages disabled where available; use
ChatGPT sign-in for delegated tasks, never API-key authentication. If included
usage is unavailable, wait for reset rather than authorizing another billing
path. Hosting/OAuth costs are separate and are not authorized by implementation.

Official sources checked 2026-10-09:
[custom MCP connection](https://developers.openai.com/plugins/deploy/connect-chatgpt),
[Dot access and allowances](https://learn.chatgpt.com/docs/dots#access), and
[Work/Codex pricing](https://learn.chatgpt.com/docs/pricing).

## Prepare a separate synthetic installation

Use a separate host/install directory and OS user, without copying production
`.env`, database, model/provider keys or broad MCP configuration. The included
units are manual-only and outside the normal deployment unit directory; merging
this code does not start or publish the probe. No hostname, issuer account,
credential or public route has been created by this implementation.

Copy [config.https.example.json](../../deploy/cloud-mcp-d0/config.https.example.json)
to a protected file outside Git. Keep `enabled` false while preparing. Select:

- `issuer_url` and same-origin `jwks_url`: exact canonical HTTPS URLs advertised
  by the issuer. A root issuer needs its advertised trailing slash.
- `resource_url`: the dedicated HTTPS hostname followed by `/mcp`; use this
  exact resource audience in the issuer and plugin configuration.
- `jwks_file`: the absolute operator-managed snapshot path, normally
  `/etc/tradejournal-d0/jwks.json`.
- `client_id` and `client_claim`: the predefined ChatGPT client and `client_id`
  or `azp`, matching actual access tokens. Register the exact callback displayed
  by ChatGPT; no wildcard or guessed callbacks. Require S256, refresh and
  `d0:profile`. ID tokens/multiple audiences are rejected.
- `profiles`: one approved issuer subject and stable newly generated synthetic
  UUID. Preserve IDs across reconnects; keep `synthetic_only` true.

Create an unprivileged `tradejournal-d0` user/group and a root-owned separate
runtime under `/opt/tradejournal-d0/backend`. Install only the probe and its
SDK/crypto dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install 'mcp==1.28.1' 'PyJWT[crypto]==2.13.0'
```

The root-owned `/etc/tradejournal-d0` directory should be mode 0750, group
`tradejournal-d0`; configuration and snapshot should be mode 0640 with that
group. No model or application credentials belong in this directory.

## Refresh public keys and start the selected trial

Run the operator preflight outside the network-disabled service:

```bash
sudo /opt/tradejournal-d0/backend/.venv/bin/python /opt/tradejournal-d0/backend/cloud_mcp_d0.py --config /etc/tradejournal-d0/config.json --refresh-keys
sudo chown root:tradejournal-d0 /etc/tradejournal-d0/jwks.json
```

The command verifies issuer discovery, code/refresh/S256/client-method
metadata and origin, fetches only the fixed public JWKS URL, then atomically
replaces the snapshot at mode 0640, preserving existing ownership/group.
Redirects, oversized bodies and invalid keys fail without replacing the old
snapshot. Its output says `login_observed: false`: no login, consent or actual
token-exchange acceptance is implied. `synthetic_scope_advertised` reports
whether provider-wide discovery lists `d0:profile`; resource-specific API scopes
may be absent there. `scope_enforcement: access_token` records that every
authenticated MCP request still requires that scope in its verified token.
Missing/other token scopes fail even after successful issuer preflight.
Refresh manually before its one-hour
expiry during the short trial. Missed refresh stops authenticated calls; it
never enables network access or another billing mode. No scheduler is added.

Install the HTTPS socket/service templates manually in `/etc/systemd/system`
on the selected host. Confirm the proxy runs under the `caddy` group (adapt
`SocketGroup` to its actual group if needed). Prepare a dedicated hostname/DNS
and a Caddy stanza matching the resource origin, validate the complete Caddy
configuration, and review its exact diff before publishing ingress. Forward
only the supplied Unix socket. Never forward production ports 8000/8080, an
owner frontend, the broad stdio MCP adapter, or arbitrary paths.

Set the synthetic configuration `enabled` true once the selected trial is
ready, then:

```bash
sudo systemctl daemon-reload
sudo systemctl start tradejournal-d0-https.socket
```

Do not enable boot startup in the first temporary trial. The first permitted
proxy request activates the service. Check native sandbox/socket behavior on
the actual host; template reading alone cannot prove enforcement.

In [ChatGPT Plugins](https://chatgpt.com/plugins), select **+ → Add custom MCP
server**, choose **Server URL**, enter the dedicated `/mcp` URL and configure
OAuth with the registered client. Create and install the private plugin, then
connect it in the actual Dot. No public directory submission, OpenAI API key,
Responses API request or API Playground test is part of this route.

## Acceptance record and stop path

Record exact source/SDK/protocol versions, isolation, issuer/client choice,
synthetic grants, account/workspace eligibility and usage settings. Keep
credentials and access-bearing addresses out of chat, Git and screenshots.
Observe:

1. Actual Dot OAuth login, only `get_profile` discovery and a valid result.
2. Same profile after token refresh/reconnect/service restart and with the
   laptop offline.
3. Anonymous/wrong identity/scope/audience rejection and immediate profile
   disable, expired snapshot and removed-key refusal with no network fallback.
4. Native IPv4/IPv6 socket-creation denial while Unix ingress still works,
   no model credentials and 404 for app/job/private-API paths.
5. Local profile disable, plugin disconnect and issuer refresh-grant revoke.
   Demonstrate subsequent valid-token calls fail.
6. Remove the dedicated public proxy stanza, validate/reload Caddy, stop both
   socket and service, unlink the plugin and confirm no listener remains.

For local revocation, atomically replace root-owned configuration with the
profile or probe disabled, preserving IDs/permissions. Do not require restart
to revoke. Stop **both** activation and service:

```bash
sudo systemctl stop tradejournal-d0-https.socket tradejournal-d0-https.service
```

Stopping the service alone allows socket activation to restart it. Remove the
public stanza before teardown, and preserve unrelated Caddy routes. D0 has no
subscription and never controls paper monitoring or owner access.

## Verification evidence

[Resource tests](../../backend/tests/test_cloud_mcp_d0.py) and
[issuer tests](../../backend/tests/test_cloud_mcp_d0_issuer.py) cover generated
RSA tokens, mocked JWKS/discovery and maintained-SDK OAuth interoperability:
predefined client, resource indicators, code + S256, discovery/call, refresh and
local disable. Fixture protocol is `2025-11-25`; no MCP 2.0 Events support is
claimed. [Offline tests](../../backend/tests/test_cloud_mcp_d0_offline.py) prove
successful and denied requests use no network, snapshot refusal/rotation,
atomic refresh failure preservation, model-credential rejection and actual
Unix/TCP descriptor checks. macOS safely refuses unavailable listener
inspection; successful activation requires native Ubuntu evidence.

[The disposable smoke](../../deploy/cloud-mcp-d0/smoke.py) is wired into
[Ubuntu CI](../../.github/workflows/deployment.yml). It installs only D0 on a
root-owned GitHub runner, uses generated public-key/token fixtures and a local
verified TLS certificate, runs the shipped Caddy routing and systemd units,
checks actual IPv4/IPv6 denial in the service sandbox, and exercises discovery,
call/refusal, route denial, key expiry, profile revoke, restart and full stop.
It uses no live issuer, model or production data and does not prove an actual
Dot connection.

Observed 2026-10-09: full local verification passed **1,804 backend tests
(33 skipped), 196 ordinary browser tests, five authenticated browser tests and
four sample-decision browser tests**, plus lint/typecheck/build/import checks.
The focused D0 resource/issuer/offline checks passed **71 tests**. The native
Ubuntu job on implementation commit `a3dee5c` passed real TLS/Unix ingress,
OAuth refusal, offline key expiry, revocation, restart, stop and IPv4/IPv6
socket-creation denial. Its fixtures do not establish provider or Dot evidence.
Two test-only socket paths were subsequently made portable from macOS to
Ubuntu; the corrected offline suite passed 27 tests locally. PR readiness still
requires current-head CI and native review.

External issuer login/refresh, actual Dot invocation, laptop-off use, account
usage controls and real-host ingress/isolation remain pending until the trial.


## Auth0 discovery observation

On 2026-10-09 the selected free Auth0 tenant's public OAuth discovery supported
authorization code, refresh, S256 and predefined public clients, but listed
standard OIDC scopes rather than resource-specific API permissions. The
[tenant-redacted captured contract](../../backend/tests/fixtures/auth0-d0-discovery-2026-10-09.json)
records that response shape, date, original response digest and redaction.
Requiring `d0:profile` in provider-wide metadata prevented the operator key
refresh before any login. Preflight now reports that advertisement separately;
signed-token scope enforcement, issuer/JWKS binding, singleton audience,
client/subject/lifetime checks and network isolation remain required.

Configure the dedicated API's `d0:profile` permission and the public client's
code + S256/refresh flow explicitly. Request `d0:profile offline_access`; avoid
adding OIDC profile/email permissions when the trial only needs its synthetic
profile. Use the exact ChatGPT callback from its configuration. Verify actual
token claims and consent before granting the observed issuer subject locally.
Do not reuse unrelated applications or change their grants. Auth0's
[API scopes](https://auth0.com/docs/get-started/apis/scopes/api-scopes) are
resource permissions, and its
[PKCE authorize reference](https://auth0.com/docs/api/authentication/authorization-code-flow-with-pkce/authorize-with-pkce)
documents API scopes, `offline_access` and the resource/audience behavior.
This metadata observation does not establish OAuth login or an actual Dot call.

VPS preparation was separately observed on 2026-10-09: reviewed D0 source
`7b47aeb` copied into its own root-owned runtime/configuration and unprivileged
identity; manual units and the pending dedicated HTTPS stanza validated. A
transient process under the service's sandbox denied actual IPv4/IPv6 socket
creation and imported no application/model SDKs. Existing Caddy configuration,
production release and browser trial remained unchanged/active. The D0 units
remained inactive and its configuration disabled pending issuer/client setup.
