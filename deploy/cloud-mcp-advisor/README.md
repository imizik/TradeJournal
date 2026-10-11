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
Both services use `Type=exec`: startup waits for executable and credential setup
before activation checks the running process. Native CI records the expected
and observed process UIDs and requires all four to match the dedicated account.
The public MCP middleware returns401 for invalid identity/audience/expired
tokens and403 `insufficient_scope` for a valid token lacking `advisor:profile`;
the independent backend still refuses missing read/write scopes with401.

## Installation and activation are separate approval gates

### Side-by-side upgrade for the private owner trial

The optional `deploy/advisor_trial_stage.py` and `advisor_trial_control.py`
support the already installed, inactive v1 advisor without overwriting its
runtime, installation record, isolated ledger or recovery export. They are
not called by normal release installation or auto-deployment. Installation
creates disabled v2 resources; it does **not** restart the owner frontend,
start/enable units, apply a ledger ACL, allocate a live assignment, refresh
keys, create grants or publish a proxy. Native CI's `trial_smoke.py` is only a
disposable test harness and must never be used as an operator installer.

The owner entrance is the existing authenticated **private demo app** at
`https://vps-c6302cfc.tail978c2e.ts.net:8443/advisor-review`. This is a regular
TradeJournal page, not the production entrance. Production's legacy access
mode, journal connector, shared database and all existing grants remain
unchanged. The existing `tradejournal-dot-trial-owner.service` alone receives
a guarded drop-in: static `tj-advisor-web-owner` user/private group, new Node
and frontend runtime paths, and a public-only advisor environment file. Its
existing EnvironmentFile, API8091, private session gateway and backend unit
dependencies remain in place. No credential file is copied or printed.

New resources are `/opt/tradejournal-advisor-v2` (root-owned adapter/backend,
compiled frontend/Node, inventory, previous-unit backups and recovery),
`/etc/tradejournal-advisor-v2/{advisor,owner}` (separately readable public
configuration), `/var/lib/tradejournal-advisor-v2/fixture.db` (new invented
ledger), and `/run/tradejournal-advisor{,-owner}-v2` (private sockets). The
six existing-name advisor units are the backend, MCP and owner socket/service
pairs. The new reader account `tj-advisor-owner` differs from the writer and
frontend; its later approved named-UID ACL applies only to the **new** ledger.
The owner socket's group is only `tj-advisor-web-owner`, never the general
production `tradejournal` group. Actual UID and GID are recorded independently.

Prepare a private JSON guard file containing exactly `old_record_sha256`,
`frontend_unit_sha256`, `owner_env_sha256`, and `api_env_sha256`, obtained from
the bounded read-only inventory. Include the full source/artifact provenance,
intended host, existing owner URL, new paths/accounts and unit/drop-in diff in
the human approval. Stage with verified offline wheels and the exact reviewed
Ubuntu24.04/x86_64/Node22 archive (no downloads/build on the retained host):

```bash
backend/.venv/bin/python deploy/advisor_trial_stage.py /absolute/private/trial-bundle \
  --archive /absolute/verified-release.tar.gz --archive-sha256 REVIEWED_TAR_SHA256 \
  --wheels /absolute/verified-wheels --guards /absolute/private/host-guards.json
```

Staging rejects archive digest/platform/source mismatch, duplicate/traversing
paths, links and special files. A previous compiled frontend is accepted only
when the complete tracked frontend source equals the current checkout. Every
staged file/mode, including the v2 proxy socket target, joins the manifest.
The installer requires the exact approved manifest SHA, root-private staging,
unchanged old runtime/unit/owner-auth guards, stopped old advisor units, absent
v2 destinations and absent new identities/owner units/drop-ins:

```bash
sudo /usr/bin/python3.12 -B deploy/advisor_trial_control.py install \
  --bundle /root/approved-trial-bundle --approve-install REVIEWED_MANIFEST_SHA256
sudo /usr/bin/python3.12 -B deploy/advisor_trial_control.py preflight
```

There is no activation action in this install-only controller. A later grouped
approval must separately cover the fresh invented freeze/question/plan,
dedicated bindings, public keys valid for at most one hour, exact reader ACL,
proxy fragment/Caddy append, the six unit starts and the one private frontend
restart. Compute the final startup guard from those **actual** approved inputs
at execution time; preparation cannot honestly supply that digest yet. Do not
use the v1 activation controller for v2: it correctly refuses replaced units.
Use the existing fixture CLI/JWKS preparation procedures only after approval,
allocate the30-minute request late, and preserve any existing v2 receipt before
considering a new request. Manual receipt capability files remain private.

```bash
sudo /usr/bin/python3.12 -B deploy/advisor_trial_control.py stop
sudo /usr/bin/python3.12 -B deploy/advisor_trial_control.py rollback
```

Stop attempts all three sockets first, then all three processes, even after
runtime drift. Rollback stops those six units, refuses changed inventories,
units, account/group authority, auth guards or backups, restores the exact old
four units, and removes only the owned owner pair/drop-in. Old and new ledgers,
receipts, recovery, accounts, runtimes and records remain. It never implicitly
stops/restarts the private owner frontend. **If that frontend was restarted
onto v2, rollback is incomplete until the separately approved explicit restart
and verification restores its original runtime/DynamicUser identity/session
behavior.** A failed partial install retains inert destinations for deliberate
recovery and refuses overwrite/retry; it restores only unit files still equal
to this attempt's exact new bytes. Preserve diagnostics and receipts.

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

Before recording the newly constructed runtime, the installer normalizes only
its root-owned adapter/backend directories to0755 and regular files to0644
(0755 for executable files). Wheel/venv group-write modes must not reach serving
identities. Non-root ownership and special files refuse. Symlinks are skipped;
OS interpreter targets/outside paths are never chmodded. There is no
post-install normalization: an existing installation record makes that helper
refuse, and later mode/ownership drift still blocks preflight. Refusal diagnostics
name the relative runtime entry and UID/mode without exposing binding contents.

The backend also has two empty, root-owned0755 compatibility directories,
`data` and `data/alpaca_cache`, created before normalization/inventory because
the shared engines construct that path during import. They remain fully
inventoried/read-only, contain no provider/cache files or database, and add no
writable mount. The adapter has no corresponding data directory. Preflight
rechecks the full runtime after the factory child and refuses unexpected import
side effects before returning an approval hash.

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

## Optional direct owner reader

The direct `/advisor-review` page solves the separate-ledger owner view without
changing the journal database or advisor catalog. The existing four-unit bundle
installer/stager does **not** install these additional units. The currently
installed immutable source32/artifact1d8 runtime predates this reader; it must
not be edited or used to launch an unrecorded newer module. Normal production
release automation ships frontend/source changes but leaves this reader dormant.
Existing journal/demo/production units, permissions and database paths stay
unchanged. Default private-legacy frontend access cannot read this ledger.

A later concrete approval must name the reviewed new owner runtime and complete
source/dependency/interpreter inventory, exact existing invented ledger and
assignment/run/packet/request identity, root-owned config and two unit hashes,
actual owner frontend UID/group and its explicitly authenticated owner entrance.
Do not infer that UID or profile from this template. New reader files belong in
separate `/opt/tradejournal-advisor-owner/backend` and
`/etc/tradejournal-advisor-owner`; refuse any pre-existing destination/unit/socket
or symlink and preserve partial failure evidence instead of overwriting it.
A separate runtime copy may use already verified matching offline wheels and
must include its empty read-only import directories. Do not rewrite the
existing advisor installation record or receipt ledger to accommodate it.
The disabled `owner-config.example.json` has a deliberately invalid UID marker
and placeholder binding; it is not a working config or grant. Reader binding
pins the same frozen request; advisor binding enablement is not required for
owner recovery. Only the top-level owner reader enable flag authorizes reads.

Before the optional owner grant, upgrade the advisor bridge/common runtime to
this separately reviewed candidate and record the new complete runtime inventory.
The old installed source32 rejects the new ACL mask/mode and must not receive
that permission change or launch a newer unrecorded module. The four-unit default
installation still keeps its original private fixture mode and no owner UID.
Only a later approval may add `owner_reader_uid=<exact new UID>` to advisor config
and matching `reader_uid=<exact new UID>` to owner config, create the new nologin
identity and grant that named UID fixture directory traverse and SQLite read.
This is an explicit isolated-advisor permission change, not a journal grant.
The Linux POSIX ACL must exactly contain owner rw (directory rwx), one named
owner-reader UID r (directory x), original group zero, mask r (directory x) and
other zero. Modes become0640/0710 because of the ACL mask; they do not grant
existing group members access. No other named entry, write bit or group/other
permission is accepted. Absence of the configured grant, changed UID/ACL/mode,
unsupported ACL metadata or directory drift refuses; normal unconfigured
owner-only fixtures retain their old permission behavior. Both services verify
these live xattrs without mounting passwd/group/NSS metadata. The bridge's UID
pin cannot change in a running grant. Root must inventory/review these exact
numeric identities and ACL bytes before any retained application of them.

The new service requires a separately approved nologin `tj-advisor-owner` UID
and private primary group, distinct from the writer and frontend UIDs, with
an independent read-only mount namespace, exposing only its reviewed runtime,
owner config, isolated advisor state directory and inherited owner socket. All
four mounts are read-only; there is no writable database directory, journal
mount, IP family, OAuth/grant/key dependency or startup dependency on the MCP
services. `tradejournal-advisor-owner.socket` grants its filesystem access to
the reviewed owner frontend group (template `tradejournal`), while the process
checks the exact configured frontend **UID** from the connected Unix socket.
Root or another socket-group member is denied by that UID check. The distinct
reader UID also prevents writer `/proc/<pid>/root`/fd access and signal authority;
read-only mounts alone were insufficient when both processes shared a UID.
No forwarded token,
header, browser/assistant session or claimed UID substitutes for kernel identity.
The retained platform is Linux/systemd; macOS `getpeereid` is supported only for
disposable local acceptance. The app transport requires a Node frontend server
on the same host with Unix-socket support; Edge/serverless/remote deployment
cannot activate this route without a separately reviewed architecture change.

Before a later approved start, validate the complete owner runtime inventory
before invoking its interpreter, pin configuration/unit/runtime/state hashes,
verify the exact named-UID file/directory ACL and existing migrated fixture with
unchanged exported identity,
and confirm frontend profile/session, Unix directory/mode/group and exact UID.
Frontend configuration requires `TJ_ACCESS_PROFILE=owner`, existing valid owner
access settings, and these additional separately approved settings:

```text
TJ_ADVISOR_OWNER_ENABLED=true
TJ_ADVISOR_OWNER_SOCKET=/run/tradejournal-advisor-owner/owner.sock
TJ_ADVISOR_OWNER_SOCKET_UID=0
```

Do not set them during preparation. Installation, frontend configuration change
and start remain separate approval gates; installing disabled config/units alone
must leave both units inactive/static with the socket absent. No public proxy
route, grant, timer or schedule is needed for this private owner reader. Once
explicitly approved, start only the optional pair:

```bash
sudo systemctl start tradejournal-advisor-owner.socket tradejournal-advisor-owner.service
```

Stop the socket first, then the process, verifying both inactive and
`/run/tradejournal-advisor-owner/owner.sock` absent, even when config has drifted:

```bash
sudo systemctl stop tradejournal-advisor-owner.socket
sudo systemctl stop tradejournal-advisor-owner.service
```

Do not enable either unit at boot. Replacement requires stopping both before
installing a newly reviewed, inventoried runtime/config/unit set; fail on
collision or unreviewed drift and retain the old version for rollback. Rollback
stops both, disables the frontend owner-read flag, and removes only unchanged
recorded optional unit files followed by daemon-reload. Preserve owner runtime,
config, existing advisor users, frozen request and SQLite receipts; never delete
or rewrite the ledger. The four-unit advisor controller does not stop this
separate owner pair, so an operator shutdown of all advisor access must stop
both optional units as well. A failed/absent reader produces an unavailable view
rather than a journal fallback or write. Actual host installation, owner browser
acceptance and actual Jo/OAuth transmission remain unperformed until separately
approved.

The existing disposable Ubuntu advisor smoke additionally constructs only a
fresh optional owner runtime/config/pair, proves native read-only mounts and
SQLite/IP denial, distinct exact peer/owner/writer UIDs, writer proc-root/fd/signal
denial, exact named-UID-only ACL and live grant removal refusal, legitimate
advisor read/save after the grant, receipt recovery/restart, disabled config,
stop of both optional units and receipt-preserving unit rollback. It
cleans its own temporary resources and is not an operator installer.
