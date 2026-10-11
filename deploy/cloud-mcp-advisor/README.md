# Disabled advisor activation bundle

This is a proposal and an offline preparation path for **one invented advisor
request**. It creates no OAuth client/grant, publishes no ingress, starts no
retained process, and does not change journal/practice connectors. Source and
templates ship in normal release archives; the normal installer does not
install these units or include this proxy. Nothing here is enabled at boot.

The [advisor contract](../../docs/agent/cloud-mcp-advisor-contract.md) defines
the exact three tools, separate identity/audience/scopes and immutable receipt.
The [manual ledger contract](../../docs/agent/advisor-shadow-contract.md) remains
unchanged. Actual Jo access is a later, separately approved acceptance layer.

## Offline preparation

From the reviewed checkout, using its existing backend environment:

```bash
backend/.venv/bin/python deploy/advisor_mcp_stage.py stage /private/tmp/advisor-disabled-bundle
backend/.venv/bin/python deploy/advisor_mcp_stage.py preflight /private/tmp/advisor-disabled-bundle
```

Choose a new absolute directory without symlink ancestors. The helper refuses
collisions, builds only a fresh private migrated SQLite, freezes an invented
question/plan with the existing owner handoff, disables that assignment, and
discards the manual capability. Config and profile are disabled. Public keys
are an empty expired placeholder. No network, provider, model or issuer call
occurs. Existing receipts are never copied, replaced or deleted. Source is an
allowlist of tracked application/migration files and the standalone modules;
dotenv, runtime databases, tests and caches are excluded.

`manifest.json` inventories every directory/file, modes and SHA256 plus the
source commit. Its SHA256 is the installation approval input; actual source
bytes are also hashed, including uncommitted preparation changes. Directories
are0700, files0600. Missing/extra files, symlinks, modified bytes/modes or an
enabled config refuse preflight. Partial staging failure removes only the new
staging directory created by that attempt. Preserve this private record.

Installation additionally needs `--wheels /absolute/verified-release/wheels`
at staging time, taken from the exact verified Ubuntu release artifact after
checking its archive SHA256. Wheel bytes join the manifest. The installer uses
only `pip --no-index --find-links`; it does not resolve/download dependencies
on the retained host. Adapter dependencies are MCP1.28.1/PyJWT2.13.0; backend
uses the release's existing wheel set. Linux installation is Python3.12 and
the verified artifact's architecture, matching the normal package environment.

## Concrete resources and permissions

| Resource | Owner/mode | Access |
| --- | --- | --- |
| `/opt/tradejournal-advisor/adapter` | root, directories0755/files0644 | Standalone adapter source/dependencies; no application/database mount |
| `/opt/tradejournal-advisor/backend` | root, directories0755/files0644 | Standalone bridge and application engines/dependencies |
| `/opt/tradejournal-advisor/recovery` | root0700/files0600 | Original frozen manual-origin export; private recovery |
| `/opt/tradejournal-advisor/installation.json` | root0600 | Reviewed manifest/source/unit hashes; original fixture hash |
| `/etc/tradejournal-advisor` | root:tj-advisor0750/files0640 | Dedicated public binding and public-only key snapshot; read-only in both processes |
| `/var/lib/tradejournal-advisor` | tj-advisor-backend:tj-advisor0700 | Only the bridge sees this writable isolated SQLite directory |
| `fixture.db` | tj-advisor-backend:tj-advisor0600 | Current migration head; invented assignment only |
| `/run/tradejournal-advisor/mcp.sock` | root:caddy0660 | Exact approved proxy to adapter; parent0755 |
| `/run/tradejournal-advisor/backend.sock` | tj-advisor-backend:tj-advisor0660 | Adapter to independently authenticated bridge; parent0755 |
| Four `tradejournal-advisor-{mcp,backend}.{socket,service}` units | root0644 | No Install section, enablement, timer or restart schedule |

`tj-advisor` and `tj-advisor-backend` are new static system users with nologin;
neither reuses an owner/journal/practice UID. Both serving processes have a
private network namespace, AF_UNIX-only address families, no capabilities,
no ambient environment files, private temporary files, strict read-only host
filesystem, hidden home/processes and bounded CPU/memory/tasks. Empty read-only
mounts cover `/etc`, `/var`, `/opt` and `/run`; only the named runtime/config and
adapter bridge socket are rebound read-only. The bridge alone rebinds its state
directory writable. Neither process sees existing journal/owner/sample paths.

The adapter does not import application storage. The bridge independently
verifies the same bearer and live config/assignment for its two fixed routes;
no service credential substitutes. Serving inherits one listening Unix FD,
never TCP. Original 64KiB body/output, concurrency and deadline limits remain.

## Installation and activation are separate approval gates

**Stop here until the owner approves the concrete installation.** Inspect the
reviewed commit/artifact/bundle digests, file modes/owners, exact users/paths/
units and intended isolated host. Take a root-private copy of the reviewed
bundle and recheck its manifest digest; root must own every entry and its
ancestors must be root-owned/immutable (a root-owned sticky temporary parent
is allowed). The operator command is:

```bash
sudo python3.12 deploy/advisor_mcp_control.py install --bundle /absolute/root-private/bundle --approve-install REVIEWED_MANIFEST_SHA256
```

This refuses existing paths, users/groups and loaded units from any search
path, installs only the reviewed resources, and leaves them inactive. It does
not install/reload the proxy or enable/start sockets/processes. On partial
failure it removes only unit files it created, attempts socket/process stop,
and keeps copied fixture/recovery/runtime/config for explicit private recovery.
Collisions on a later attempt remain a refusal; there is no overwrite retry.

**Separate owner approval is required before creating any retained assignment
or OAuth grants, publishing ingress/network settings, or starting retained
services.** The staged disabled assignment is verification data, not a live
trial. For a later approved trial, prepare a fresh invented assignment/handoff
through the existing owner path in this isolated SQLite; never extend or
rewrite an old export/receipt. Preserve old ledgers and use a new reviewed
bundle/path if prior evidence exists. Assignment duration remains30 minutes;
tokens at most300 seconds. Do not share the manual capability with Jo.

Review the actual issuer/client/subject/profile, exact setup-form callback
(no guessing/wildcards), `/advisor/mcp` resource origin, exactly
`advisor:profile advisor:read advisor:write`, assignment/run/digests/version,
expiry and current manual public-key snapshot (at most one hour). Profile and
config must be deliberately enabled; persisted assignment must also be active.
Only public RSA verification keys belong in the snapshot; no client secret,
signing key, cookie or database/provider credential belongs in the bundle.
Serving never fetches keys. Manual refresh, OAuth issuer consent/revocation and
updating the dedicated binding are separate approved operator actions. No key
timer/schedule is supplied. Placeholders are explicitly nonworking.

Review a concrete hostname replacement of `Caddyfile.example` before publishing.
It forwards only `/advisor/mcp` GET/POST/DELETE/OPTIONS and its exact protected
resource metadata GET/HEAD; everything else is404. POST input is bounded,
upstream connect/headers are bounded and stream flushing is explicit. Validate
with the installed Caddy before a separately approved reload; preserve every
existing route. Neither staging nor control edits Caddy, TLS, firewall or DNS.

After separate activation approval, the controller's read-only preflight checks
the entire recorded runtime/units, public keys, active migrated invented assignment and
pinned hashes **before invoking the installed interpreter**. Runtime inventory
includes both virtual environments, all dependencies/import hooks/bytecode,
directory/file modes and owners, every symlink and its resolved interpreter
target digest. Added/deleted/modified inputs refuse before execution. No cache
files are ignored: install-generated bytecode is recorded, and every post-install
preflight/probe/service interpreter uses `-B` (also preserved by the bridge's
clean re-exec), so validation does not generate new cache drift. Serving mounts
are read-only. Interpreter targets are pinned; the matching Ubuntu host's OS
libraries remain the trusted system base. Runtime replacement needs new review.
The approval SHA256 binds the runtime inventory as well as installation/config/keys/current
fixture bytes; any changed input requires new review/approval. It refuses
disabled/placeholding inputs before startup:

```bash
sudo python3.12 deploy/advisor_mcp_control.py activation-preflight
sudo python3.12 deploy/advisor_mcp_control.py activate --approve-activation REVIEWED_PREFLIGHT_SHA256
```

These commands do not create grants or transmit to Jo. Activation starts only
the two optional socket/process pairs and verifies active state; any startup
failure attempts stopping both groups. No boot enablement follows. Current
implementation work must leave this step paused.

## Stop, replacement and receipt-preserving rollback

```bash
sudo python3.12 deploy/advisor_mcp_control.py stop
sudo python3.12 deploy/advisor_mcp_control.py rollback
```

Stop always attempts both sockets first and both processes next, and refuses
to claim shutdown if any are active, socket files remain, or a stop command
failed. Runtime/unit drift does not prevent the stop action. Rollback stops
first, then removes only unchanged units recorded by this installation; altered
resources require explicit review before removal. It keeps both users, source,
config, original export and SQLite/receipt bytes for owner recovery. It leaves
the optional entrance absent; it never rolls journal source/permissions back.
Owner recovery reads the isolated ledger through the existing private owner
route using an explicitly targeted disposable owner UI, not production. Revoke
the advisor binding/assignment and remove the exact introduced proxy handler
under the corresponding later approval. OAuth issuer revocation is separate.
Never delete the ledger to make a reinstall pass or reuse an answered binding.

Replacement requires stop first, verified source/config and new bounded review;
there is no automatic update, mutable runtime symlink or unattended relink in
this bundle. Reopening original receipts after revocation remains owner-only.

## Evidence boundaries

`backend/tests/test_advisor_mcp_bundle.py` exercises disabled migrated staging,
inventory/path/mode tampering, collisions, partial failure, inactive installation,
startup failure, runtime/dependency/import-hook/bytecode/interpreter-target drift
refusal before execution, both-pair stop and receipt-preserving rollback with fake host
commands. Existing advisor signed-token/Unix/browser checks retain immutable
catalog, citations, denials and owner receipt equality.

`smoke.py` requires root **and** the explicitly disposable GitHub runner before
any host mutation; it cannot serve as a retained installer. Deployment CI builds
the committed artifact, stages an invented disabled fixture, exercises actual
manual control/service/Unix/TLS boundaries with generated keys, verifies mount/
UID/IP denials, saved receipt/retry/restart/revocation/expiry/recovery, and stops
both pairs. Cleanup removes only its exclusive temporary resources even on
failure. It neither contacts an issuer nor Jo. Actual installed isolation,
real OAuth consent, public HTTPS and Jo catalog/read/save/owner UI/reopen equality
remain pending until separately approved and observed. CI green is not activation.

The root disposable smoke uses a fixed administrative PATH with `/usr/sbin`
and an otherwise credential-free environment. Staging scopes Git trust to its
own exact reviewed checkout per read command, without global/wildcard Git
configuration. These are preparation portability controls, not runtime grants.
