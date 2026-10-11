# Dependable advisor connection upkeep

Selected October 11, 2026 as Dots sequence step 3 on the
[delivery board](dots-integration.md#functionality-sequence). Contract only:
nothing here is built, installed or activated. The connected trial (step 1)
stays owned by the existing advisor chat, and its approved digest-bound package
is not changed by this document. Implementation targets a successor bundle
revision after that trial records its result.

## Problem

Routine use currently breaks within an hour without an operator. The advisor
bundle verifies tokens against a manual public-key snapshot that expires after
at most one hour; [the bundle runbook](../../deploy/cloud-mcp-advisor/README.md)
supplies no key timer. The activation approval also binds the key file's SHA-256,
so any refreshed snapshot drifts from the approved identity. Isaac has no
in-app view of whether the connection is healthy, stale or revoked, and no
written recovery path when Claude's connector sign-in lapses.

## Outcome

Isaac can use the advisor across days without operator key handling, can see in
`/advisor-review` whether the connection is usable and why not, and can recover
from each normal failure with a documented action. Connection upkeep stays
separate from agent schedules, assignments and trading automation.

## Scope

1. **Public-key upkeep.** Reuse `backend/cloud_mcp_d0_refresh.py` and the
   journal's proven publisher pattern (`tradejournal-journal-real-keys` and its
   network unit under `deploy/cloud-mcp-journal/`). A dedicated advisor key UID
   runs a oneshot every 15 minutes, writing only the advisor snapshot under
   `/var/lib/tradejournal-advisor/public-keys/`. Its UID-specific nftables table
   allows DNS and public HTTPS to the configured issuer origin only, with
   private/loopback/Tailscale/host addresses denied; it cannot read the advisor
   config, fixture SQLite, sockets or any journal/production path. The serving
   processes keep `PrivateNetwork`, AF_UNIX only, and read the snapshot
   read-only; `JWKSVerifier.signing_keys` already checks expiry on every call.
   A failed refresh leaves the previous snapshot, which still expires normally.
   Expiry is never lengthened to mask a stopped publisher.
2. **Approval identity.** Activation keeps binding runtime inventory, units,
   config, issuer/JWKS URLs and fixture, but replaces the key-file digest with a
   start-time check that the snapshot is fresh, parses, and matches the pinned
   issuer and JWKS URL. Key rotation then never invalidates an approval, while
   a changed issuer or key URL still does. This is the only change to activation
   semantics and requires the focused risk review.
3. **Health visibility.** A read-only status on the existing owner path (owner
   Unix socket and BFF, owner session required) reports: key snapshot age and
   expiry (fresh / expiring within 15 minutes / expired), config and profile
   enabled, adapter and bridge sockets reachable, selected assignment state and
   expiry, and the time of the last successful Jo read and save. It returns
   states and timestamps only: no keys, tokens, subjects, config bodies or
   receipt contents. `/advisor-review` shows one plain-language line per item
   and the matching recovery step. No new public MCP tool or main-API route.
4. **Recovery runbook.** Document in the bundle README, for each failure the
   status can show: stale keys (check timer/journal, run the oneshot once),
   connector sign-in expired or revoked at the issuer (reconnect from Claude's
   connector settings; Auth0 refresh-token policy is not changed here),
   disabled profile/config, stopped sockets after host reboot or deploy, and
   expired assignment (create a new one; old receipts stay recoverable).
   Ordinary app deployment does not start, stop or replace advisor units.

## Out of scope

Auth0 tenant, client or refresh-token lifetime changes; phone alerts; D3
follow-through or any recurring Jo task; real journal data; new tools or
scopes; journal coach units, grants or keys; host firewall tables other than
the new UID-specific one.

## Acceptance

- **Local:** refresher writes only the advisor path; serving accepts a fresh
  snapshot, refuses an expired one and recovers after refresh without restart;
  activation accepts a rotated snapshot and refuses a changed issuer/JWKS URL;
  status reports each state without secrets; owner session and CSRF rules hold;
  desktop and 390px status rendering.
- **Disposable Ubuntu (deployment CI):** timer advances the snapshot; network
  policy denies private API/frontend and non-issuer hosts for the key UID;
  stopping the timer leads to refusal after expiry and status shows it;
  restarting recovers; host reboot of the units preserves receipts.
- **Observed on the VPS, after step 1 is accepted:** an actual Jo read and save
  succeed more than two hours after the last manual operator action; one
  reconnect after issuer-side revocation is observed; status matched reality at
  each point. Record dates as built, activated, observed and accepted separately.

Activation needs the owner's separate approval of the exact units, network
policy and bundle digest, a fresh restore point and retained rollback files,
as for the existing advisor bundle. Rollback stops and removes only the new
key timer, oneshot and UID table; receipts and the fixture ledger are preserved.
