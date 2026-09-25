# Ubuntu 24.04 deployment

This package runs one private, single-user TradeJournal installation. It uses
native systemd services for Next.js, the API, the sync, Polygon, Webull and
Gmail worker lanes, plus local/offsite backup, Gmail-import and Sync Everything
timers. Production now uses PostgreSQL on the VPS. The original Neon primary is
retained as a pre-cutover recovery source; it is no longer the live database.
An optional, separately credentialed service accepts TradingView webhooks.

## Access and layout

| Component | Address / location |
|---|---|
| Frontend | `127.0.0.1:3000`, reached through private Tailscale Serve |
| API | `127.0.0.1:8080`, never published directly |
| Browser API requests | same-origin `/api/backend/…`, proxied by Next to loopback |
| Server component API requests | loopback API directly |
| Releases | `/opt/tradejournal/releases/<release-id>`; root owned |
| Active / prior release | `/opt/tradejournal/current`, `/opt/tradejournal/previous` |
| Runtime state | `/var/lib/tradejournal/data`, `oauth`, `job-locks`, `frontend-cache` |
| Private application config | `/etc/tradejournal/backend.env`; root owned, mode 0600 |
| Migration credentials | `/etc/tradejournal/migration.env`; root owned, mode 0600 |
| TradingView ingress | `127.0.0.1:8090`; dedicated `tradejournal-ingress` OS user |
| Ingress configuration | `/etc/tradejournal/tradingview.env`; root owned, mode 0600 |
| Offsite backup credentials | `/etc/tradejournal/offsite.env` and `restic-password`; root owned, mode 0600 |

The frontend proxy has the same authority as the unauthenticated private API.
Keep **both** services behind private access. Restrict the Tailscale access
policy to the journal owner's devices/identity. Do not use Funnel, a public
reverse proxy, public port forwarding, or expose 3000/8080 in the firewall.
The only application designed for public webhooks is the separate TradingView
ingress on 8090. Its opt-in service is included; the dedicated public HTTPS
proxy is configured separately under [TradingView webhooks](#tradingview-webhooks).

All API/worker processes share the same hostname, database URL and local lock
directory. This is not a multi-host worker deployment. Stop the old laptop's
API and workers before enabling the VPS against the same database. Let active
jobs finish first. Previously running rows owned by another host need explicit
operator recovery; see [background jobs](../docs/agent/background-jobs.md).

## Build and obtain the release

The `Deployment package` GitHub Actions workflow builds on Ubuntu 24.04 x86_64,
then installs the artifact on a disposable runner and exercises real systemd
services against disposable Postgres. Only a successful smoke test uploads
`tradejournal-ubuntu-24.04-x86_64` (retained for 14 days). Choose a successful
run for the exact reviewed commit; after merging, prefer the `main` run.

For every `main` commit on which both that workflow and CI pass, the Release
workflow (`.github/workflows/release.yml`) republishes the same files as a
`build-<commit>` GitHub pre-release and keeps the newest ten. Those downloads
need no sign-in, and they are what [automatic deployment](#automatic-deployment)
installs. A red commit is never published, even though `main` has no branch
protection and can merge one.

Download its artifact from Actions, or from that release. It contains:

- `<release-id>.tar.gz`: standalone frontend, bundled Node 22, backend source
  and migrations, and a resolved Python 3.12 wheelhouse.
- `tradejournal-deploy.py`: bootstrap/operation command.
- `SHA256SUMS`: checksums for those files.

Build manually on a separate Ubuntu 24.04 machine of the same architecture,
with Python 3.12 and Node 22 installed, from a clean committed checkout:

```bash
python3.12 deploy/build.py --release-id "$(git rev-parse --short=12 HEAD)-$(date -u +%Y%m%d%H%M%S)"
```

The build uses `git archive HEAD`, installs npm's lockfile, and resolves Python
runtime wheels once into the artifact. Reuse the same artifact for rollback;
a later rebuild can resolve newer Python dependencies. Generated caches,
local configuration, OAuth tokens and databases are excluded. The VPS never
runs npm, a Next build, or an online pip install. ARM hosts need an ARM build;
the supplied workflow produces x86_64 only.

## First installation

Provision Ubuntu 24.04 x86_64. Allow administrative SSH only as needed for
bootstrap and use the provider's firewall plus the host firewall. Install the
Python runtime/venv support and Tailscale using its
[official Linux installation guide](https://tailscale.com/download/linux).
Join the server and your browser's device to the same restricted tailnet.

```bash
sudo apt-get update
sudo apt-get install -y python3.12-venv
```

Copy the downloaded artifact files to the server. From that directory:

```bash
sha256sum --check SHA256SUMS
sudo install -m 0755 tradejournal-deploy.py /usr/local/sbin/tradejournal-deploy
# Substitute the release ID and its archive digest from SHA256SUMS.
sudo tradejournal-deploy install RELEASE_ID.tar.gz --sha256 ARCHIVE_SHA256
sudoedit /etc/tradejournal/backend.env
sudoedit /etc/tradejournal/migration.env
```

For an initial Neon-backed installation, set `DATABASE_URL` to its existing
application-role URL. Set
`MIGRATION_DATABASE_URL` in **migration.env only**, using the owner role for
the same endpoint, database and URL query settings. Use the same hostname
spelling (do not mix pooled and direct endpoints); prefer the direct endpoint
for this long-running host. Retain the existing database roles; new role setup
is documented in [environments](../docs/agent/environments.md).

Use simple `KEY=value` entries or single-quoted values, without shell commands,
variable interpolation, `export`, multiline values or inline comments. These
files are read by both systemd and Python dotenv. URL-encode reserved password
characters. Keep them root owned with permissions 0600. The frontend service
does not receive these files; only the short-lived migration helper receives
owner credentials, and it drops root before accessing the database.

Set `FRONTEND_PUBLIC_URL` to the private HTTPS Tailscale origin and
`BACKEND_PUBLIC_URL` to that origin plus `/api/backend`. Configure only the
integration keys needed. Autostarts default to false; turn on Webull listening
only after installing its credentials and stopping the old executor.
TradingView analysis, when enabled, remains API-owned. Real-time Gmail import
is opt-in and needs no public endpoint; see
[Real-time Gmail import](#real-time-gmail-import).

Copy needed state from the old host **before activation**, with all writers
stopped. Market caches, manual-fill backups and Gmail sidecars go under
`/var/lib/tradejournal/data/`. Gmail `credentials.json` and `token.json` go
under `/var/lib/tradejournal/oauth/`. Preserve their contents and restrict
ownership to `tradejournal:tradejournal`; files should be 0600 and directories
0700. Do not copy old process lock files. Include this state directory in
off-host backups: a database backup alone does not contain OAuth or caches.

The VPS needs a **Web application** OAuth client; a Desktop client only
allows loopback redirects, so its Reconnect flow can never finish on the VPS.
Create one in the same Google Cloud project with this exact redirect URI and
install its downloaded JSON as `/var/lib/tradejournal/oauth/credentials.json`:
`https://YOUR_SERVER.YOUR_TAILNET.ts.net/api/backend/auth/gmail/callback`.
The browser opening that callback must be connected to the tailnet. Google
accepts the tailnet domain (`YOUR_TAILNET.ts.net`) as an authorized domain.

Publish the OAuth app (*Audience → Publish app*): in *Testing*, Google expires
Gmail sign-ins after seven days. Publishing first needs a home page, a privacy
policy link and an authorized domain on the *Branding* page; the app serves
`/privacy` for this, and the private Serve origin works for all three.
Personal use under 100 users needs no verification; the consent screen shows
an "unverified app" warning (*Advanced → Go to Trade Journal*). Reconnect Gmail
once afterwards so the stored token no longer carries the seven-day limit.
The live Google flow is not tested by the automated suite.

Check the target identity, then copy that exact redacted value into the next
two commands. Take a backup/restore point before applying schema changes.

```bash
sudo tradejournal-deploy identity RELEASE_ID
sudo tradejournal-deploy migrate RELEASE_ID --confirm-database 'HOST/DATABASE'
sudo tradejournal-deploy activate RELEASE_ID --confirm-database 'HOST/DATABASE'
sudo tailscale serve --bg http://127.0.0.1:3000
sudo tailscale serve status
```

Use the HTTPS address reported by Serve. Per the
[Tailscale Serve documentation](https://tailscale.com/docs/features/tailscale-serve),
this shares with the tailnet; Funnel would expose it publicly. No public
database port, frontend port or API port is needed.

## Backups and scheduled Robinhood import

The release installs four timers:

- `tradejournal-backup.timer` runs daily at 05:15 UTC with up to 15 minutes of
  jitter. It creates a custom-format PostgreSQL dump plus a compressed archive
  of `/var/lib/tradejournal/data`, `oauth`, and the active
  `/etc/tradejournal/backend.env` and `migration.env` files. It verifies both
  files and retains seven dated restore points under
  `/var/backups/tradejournal/`. Backups created before format version 2 do not
  contain the deployment configuration.
- `tradejournal-offsite-backup.timer` runs daily at 06:15 UTC with up to 15
  minutes of jitter. Once configured, it verifies the newest local backup,
  uploads it through restic's encryption to a private R2 bucket, keeps 30 daily
  snapshots, and checks the repository. Without the two root-only offsite
  credential files, the service is skipped.
- `tradejournal-gmail-sync.timer` checks Gmail five minutes after timer
  activation and five minutes after each prior check finishes. It treats an
  already-active sync as a safe skip. When Gmail imports new fills, it waits
  for that durable job and then queues a trade rebuild; it does not start
  market-data enrichment.
  With real-time import enabled this is the safety net for a dropped
  notification.
- `tradejournal-sync-pipeline.timer` queues Sync Everything (import, rebuild,
  Polygon, Alpaca, path metrics) at 08:00 and 17:00 New York time. It waits
  up to ten minutes for a running sync to finish instead of skipping, and
  `Persistent=true` runs a missed slot after downtime.

Install a `pg_dump`/`pg_restore` client at least as new as the hosted PostgreSQL
server before enabling the backup timer. The service keeps the database
password out of its arguments and metadata, reads the root-only migration URL,
and runs the database client as `tradejournal`. Backup directories and files
use the root-only `0700`/`0600` defaults.

```bash
sudo systemctl start tradejournal-backup.service
sudo journalctl --no-pager -u tradejournal-backup.service
sudo /opt/tradejournal/current/backend/.venv/bin/python \
  /opt/tradejournal/current/deploy/backup.py verify \
  /var/backups/tradejournal/latest
sudo systemctl list-timers 'tradejournal-*'
```

The dated directories are local restore artifacts, not independent storage by
themselves. Keep the provider's daily VPS backup active and retain the
**encrypted** second-provider R2 copy. The state archive contains OAuth tokens
and API/database credentials; never upload it unencrypted. A successful
`verify` checks archive structure and checksums. Confirm scheduled local and
offsite backup runs; periodically restore an R2 snapshot into a disposable
database, since a successful upload alone does not prove recoverability.

### Production database cutover (2026-09-23)

The Ubuntu 24.04 VPS runs PostgreSQL 18 on `127.0.0.1:5432/tradejournal`.
The app uses `tj_app`; Alembic uses `tj_owner`; the optional TradingView ingress
role is `tj_ingress`. PostgreSQL, the API and the frontend listen on loopback;
private Tailscale Serve reaches only the frontend. No database port is public.

For the cutover, all application writers and timers were stopped. A final Neon
dump was verified, uploaded encrypted to R2, and restored in a disposable
database. Every table count and the Alembic revision matched the restored VPS
database. Schema and role checks passed before switching `DATABASE_URL`. The
live API, frontend proxy, workers, Gmail sync and a fresh VPS-database
backup/restore drill passed afterwards.
The root-only `backend.env.neon-before-local` and
`migration.env.neon-before-local` files preserve the previous connection
settings. Neon was not modified or deleted during the cutover. Once the VPS
database accepts writes, switching back to the old Neon snapshot requires
reconciling any newer VPS data first; copying those old settings back alone
would lose writes.

### Encrypted offsite backup in Cloudflare R2

Create a private R2 bucket using **Standard** storage. Make a bucket-scoped
Object Read & Write token; Cloudflare shows its Access Key ID and Secret Access
Key only at creation. Use the **account endpoint**, not the bucket URL, in the
restic repository string. For example, if the bucket URL ends in
`/trade-journal`, set the repository to
`s3:https://ACCOUNT_ID.r2.cloudflarestorage.com/trade-journal/tradejournal-v1`.
The extra path is a dedicated restic repository prefix. Never make the bucket
public and never put its S3 credentials in a Git checkout or chat.

Install the Ubuntu restic package and create two root-owned `0600` files:

- `/etc/tradejournal/offsite.env`, based on `deploy/offsite.env.example`, with
  that repository string and the bucket-scoped S3 access key and secret.
- `/etc/tradejournal/restic-password`, containing one generated random password
  for restic encryption. Save a copy of this password in a password manager
  **outside the VPS**. Losing it makes the offsite backup unreadable; possession
  of the R2 token alone cannot decrypt it.

Keep the password out of shell history, process arguments, and logs. Generate
the file on the VPS with `sudo openssl rand -base64 48` redirected to the
root-only file under a `077` umask, then copy its contents to the password
manager through a private channel. The token may be rotated; the restic
password must remain available for recovery.

After the files exist, initialize and exercise the dedicated repository:

```bash
sudo apt-get install -y restic
sudo /opt/tradejournal/current/backend/.venv/bin/python /opt/tradejournal/current/deploy/offsite.py init
sudo /opt/tradejournal/current/backend/.venv/bin/python /opt/tradejournal/current/deploy/offsite.py backup
sudo /opt/tradejournal/current/backend/.venv/bin/python /opt/tradejournal/current/deploy/offsite.py restore-drill
sudo systemctl enable --now tradejournal-offsite-backup.timer
```

The drill downloads the encrypted snapshot to a temporary root-only directory,
verifies both archive checksums, restores the database dump into a disposable
local PostgreSQL database, queries its tables and Alembic revision, then removes
both the restored files and disposable database. Check the timer and service
logs after scheduled runs. Retire Neon only after deciding how long to keep the
pre-cutover source and confirming continued recoverability from R2.

## Real-time Gmail import

Gmail can announce each new execution email through Google Pub/Sub. The
`tradejournal-worker@gmail` service holds a **pull** subscription open, an
outbound HTTPS connection, so nothing on the VPS accepts inbound traffic and
Funnel is never involved. Each notification queues one coalesced
`gmail_push` job. The sync lane reads Gmail history from a saved cursor,
imports only new Robinhood execution emails through the ordinary parser and
dedupe, and rebuilds trades, typically within about 15 seconds of the email.
Only one machine may listen and register the watch: keep
`GMAIL_LISTENER_ENABLED=false` anywhere else that shares this database.

It stays off until configured. One-time setup, in Cloud Shell for the Google
Cloud project that owns the Gmail OAuth client:

```bash
PROJECT_ID="$(gcloud config get-value project)"
gcloud services enable pubsub.googleapis.com
gcloud pubsub topics create tradejournal-gmail
gcloud pubsub topics add-iam-policy-binding tradejournal-gmail \
  --member="serviceAccount:gmail-api-push@system.gserviceaccount.com" --role="roles/pubsub.publisher"
gcloud pubsub subscriptions create tradejournal-gmail-vps --topic=tradejournal-gmail \
  --ack-deadline=60 --message-retention-duration=7d --expiration-period=never
gcloud iam service-accounts create tradejournal-gmail-listener --display-name="TradeJournal Gmail listener (pull only)"
gcloud pubsub subscriptions add-iam-policy-binding tradejournal-gmail-vps \
  --member="serviceAccount:tradejournal-gmail-listener@${PROJECT_ID}.iam.gserviceaccount.com" --role="roles/pubsub.subscriber"
gcloud iam service-accounts keys create pubsub-subscriber.json \
  --iam-account="tradejournal-gmail-listener@${PROJECT_ID}.iam.gserviceaccount.com"
```

The key can only read that one subscription. Install it as
`/var/lib/tradejournal/oauth/pubsub-subscriber.json` (owner
`tradejournal:tradejournal`, mode 0600) and delete the Cloud Shell copy. The
state backup already includes it.

In Gmail, create a filter from `noreply@robinhood.com` with subject
`"Option order executed" OR "Option order partially executed" OR "Your order has been executed"`
that applies a new label `TradeJournal/Fills` and is never sent to spam.
Watching that label keeps unrelated mail from waking the listener; the importer
reads only the From/Subject headers of anything else.

Set in `/etc/tradejournal/backend.env`:

```
GMAIL_LISTENER_ENABLED=true
GMAIL_PUBSUB_TOPIC=projects/PROJECT_ID/topics/tradejournal-gmail
GMAIL_PUBSUB_SUBSCRIPTION=projects/PROJECT_ID/subscriptions/tradejournal-gmail-vps
GMAIL_PUBSUB_CREDENTIALS_FILE=/var/lib/tradejournal/oauth/pubsub-subscriber.json
GMAIL_WATCH_LABELS=TradeJournal/Fills
GMAIL_WATCH_AUTOSTART=false
```

Then `sudo systemctl restart tradejournal-worker@gmail tradejournal-worker@sync tradejournal-api`
and check `curl -s http://127.0.0.1:8080/gmail/health`; `status` should reach
`live` within a minute. The sync worker must restart too: it runs the watch
registration, and a stale environment fails it with "GMAIL_PUBSUB_TOPIC is
required" (the listener then retries every 15 minutes, or run
`curl -s -X POST http://127.0.0.1:8080/gmail/watch` once). The listener registers the Gmail watch itself and
renews it daily through a `gmail_watch_renew` sync job; Gmail stops
notifications after seven days without renewal. A plumbing test that needs no
trade:

```bash
gcloud pubsub topics publish tradejournal-gmail --message='{"emailAddress":"you@gmail.com","historyId":"1"}'
```

A `gmail_push` run should appear within seconds and finish with no new fills.

A Google Cloud OAuth app left in *Testing* issues Gmail sign-ins that expire
after seven days. Publish it to *In production* (personal use under 100 users
does not need verification) and reconnect Gmail once. When Gmail does need
reconnecting, every page shows a banner with a Reconnect button.

## TradingView webhooks

The deployment includes `tradejournal-ingress.service`, disabled by default.
It runs on loopback port 8090 as a separate `tradejournal-ingress` OS user,
with only `/etc/tradejournal/tradingview.env` injected by systemd. The unit
cannot read the journal's runtime data, OAuth files, backups or private
configuration. The launcher removes inherited private credentials, forces
the PostgreSQL URL to be explicit, and disables Uvicorn access logging.
Analysis remains in the private API, using its existing durable claim/retry
worker and private Alpaca credentials.

### Enable the receiver and analysis

1. Install a release containing the ingress service. The installer creates
   its OS user and a root-only `tradingview.env` with ingress disabled.
2. In `/etc/tradejournal/backend.env`, configure `ALPACA_API_KEY` and
   `ALPACA_API_SECRET`, then set `TRADINGVIEW_ANALYSIS_AUTOSTART=true`.
3. In `/etc/tradejournal/tradingview.env`, set:

   ```dotenv
   TRADINGVIEW_INGRESS_ENABLED=true
   TRADINGVIEW_DATABASE_URL=postgresql+psycopg://tj_ingress:URL_ENCODED_PASSWORD@127.0.0.1:5432/tradejournal
   TRADINGVIEW_WEBHOOK_TOKEN=DEDICATED_RANDOM_TOKEN_AT_LEAST_32_BYTES
   ```

   Generate the token with `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`.
   Use the existing restricted ingress role, never `tj_app` or `tj_owner`.
   It needs SELECT/INSERT/UPDATE on `tradingview_alert`, USAGE on `public`,
   no other table privileges, no CREATE on `public`, and no role memberships
   or administrative flags. See [database roles](../docs/agent/environments.md#database-roles).
   Match the private URL's host, port, database and routing parameters exactly.
4. Run the read-only check before activation:

   ```bash
   sudo /opt/tradejournal/releases/RELEASE_ID/backend/.venv/bin/python /opt/tradejournal/releases/RELEASE_ID/deploy/ingress.py
   sudo tradejournal-deploy activate RELEASE_ID --confirm-database '127.0.0.1:5432/tradejournal'
   curl --fail http://127.0.0.1:8090/health
   ```

   Preflight checks the configured worker, matching database endpoint, real
   schema access and effective role privileges before stopping a healthy
   release. It prints only whether ingress is enabled. Activation starts and
   checks ingress after the private API is healthy; a failed ingress startup
   follows the same rollback path as an API/frontend failure. The health check
   proves DB/token readiness, not Alpaca connectivity or a live verdict.

### Public HTTPS with a free hostname

[DuckDNS](https://www.duckdns.org/about.jsp) provides a free hostname such as
`your-alerts.duckdns.org`. Point its IPv4 record at the VPS public IPv4 address.
[Caddy](https://caddyserver.com/docs/automatic-https) obtains and renews HTTPS
certificates automatically. This uses the existing VPS; no additional hosted
relay or purchased domain is required.

Install Caddy following its [official package instructions](https://caddyserver.com/docs/install#debian-ubuntu-raspbian).
Use `deploy/Caddyfile.tradingview.example` as the dedicated `/etc/caddy/Caddyfile`,
replacing both `alerts.example.com` and `203.0.113.10` with the actual hostname
and the public IPv4 address assigned to the VPS interface. Review existing
Caddy configuration before replacing it if the host already uses Caddy.
The explicit bind keeps Caddy off the private Tailscale Serve address.
If the VPS uses NAT, choose its assigned interface address for the bind and
its public address for DNS. Allow inbound TCP 80/443 to that interface in
both the VPS and provider firewalls; keep 3000/8080/8090/5432 closed publicly.

```bash
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl enable caddy
sudo systemctl restart caddy
```

The template disables the Caddy admin API, so use a service restart rather
than `caddy reload`. Only HTTPS POST `/tradingview/webhook` is forwarded to
8090; other application paths return 404. HTTP is used only for certificate
validation and otherwise returns 404. No journal/frontend route is proxied.
Access logs are disabled, and request fields are removed from Caddy runtime
error logs, since upstream failures would otherwise record the query token.
Do not enable debug/request logging at another proxy hop.

TradingView's URL is:

```text
https://YOUR_HOSTNAME/tradingview/webhook?token=YOUR_DEDICATED_TOKEN
```

The public endpoint uses 443; 8090 remains internal. TradingView accepts ports
80/443, requires 2FA for webhooks, and cancels a request taking more than three
seconds ([official webhook requirements](https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/)).
The receiver acknowledges persistence without waiting for market analysis.
Check readiness locally, then use a current contract-valid alert to confirm
the public response and the private `/signals` record. Resending it must
return `dup:true`; unauthenticated requests must return 401. A synthetic old
alert proves receipt/deduplication but will be skipped by analysis.

The controller preserves the ingress config across releases, includes it in
local/encrypted offsite backups when present, and stops ingress during
migration or release switching. Rolling back to a release without ingress
support removes/disables its unit; the public proxy then returns an upstream
error until a supporting release is activated. Set ingress to `false` and
activate the current release to disable it deliberately.

## Updates, restarts and rollback

Install the next verified archive using its checksum. The installer creates
an offline venv and preserves state/config. Release IDs cannot be overwritten.
When the controller changes, update `/usr/local/sbin/tradejournal-deploy` from
that verified artifact too. Before switching, wait for long-running jobs to
finish; deployment stops the six private services, optional ingress, and the timers. Workers get 90 seconds to finish,
after which systemd can kill them. Queued jobs survive. Interrupted jobs fail
visibly and need an explicit new run; destructive or paid work is never
automatically replayed.

```bash
sudo tradejournal-deploy migrate NEW_RELEASE_ID --confirm-database 'HOST/DATABASE'
sudo tradejournal-deploy activate NEW_RELEASE_ID --confirm-database 'HOST/DATABASE'
sudo tradejournal-deploy status
# Keep the newest three installed releases plus current and previous:
sudo tradejournal-deploy prune --keep 3
# API-only restart leaves the four worker services running:
sudo systemctl restart tradejournal-api
sudo journalctl -u tradejournal-api -u tradejournal-worker@sync -u tradejournal-worker@polygon -u tradejournal-worker@webull -u tradejournal-worker@gmail -f
# Roll back code only, when its required schema still matches:
sudo tradejournal-deploy rollback --confirm-database 'HOST/DATABASE'
```

`migrate` validates the target and owner connection, stops services and runs
Alembic; it leaves services stopped until activation. If migration fails,
inspect the error and actual schema before retrying. `activate` checks schema
compatibility before stopping an existing release, switches the symlink,
checks API/frontend identity plus a database-backed proxy request, and starts
workers. A failed activation restores the prior release only if its schema
check passes. The deployment lock serializes controller operations.

Rollback is **not** a database restore. This package never runs `alembic
downgrade`. If a migration advanced the schema, the old release refuses to
start; use a forward fix or an explicitly planned database restore. Shared
runtime state and configuration do not roll back with code. Retain known-good
artifacts off the VPS. Do not delete the shared job-lock directory or files.

Each release is about 1 GB on the disk PostgreSQL shares, and nothing but
`prune` removes one. Automatic deployment prunes after every successful
switch; `prune` never removes the current or previous release, and an older
build can be reinstalled from its GitHub release or Actions artifact. A
controller command that finds another one holding the deployment lock exits
with status 75 instead of waiting.

All six units are enabled for boot and restart on process failure. A provider
error that is caught inside a still-running worker is not a process crash;
inspect job failures/logs. Webull's reconnect cap remains unchanged. On the
first real VPS, verify a reboot, browser access, OAuth, and the desired live
integrations. No real VPS or Tailscale enrollment is created by this PR.

## Automatic deployment

The server installs green `main` builds by itself, so a merge goes live
without anyone connecting to it. GitHub cannot reach the server, which is
private to the tailnet, so `tradejournal-autodeploy.timer` pulls instead:
every five minutes `deploy/autodeploy.py` asks GitHub's public API for the
newest `build-*` release (published only after CI and the Ubuntu smoke test
passed on that commit), checks the download against its `SHA256SUMS`, installs
the bundled controller and the release, then activates it with the usual
health checks and rollback. It needs no GitHub credential. A merge normally
goes live 10–15 minutes after it lands.

A newer build waits, and is installed later or by a person, while:

- it is 09:25–16:15 New York time on a weekday. An activation restarts
  everything for about a minute, and a TradingView alert arriving then is
  lost. Adding the `deploy-now` label to the pull request, before or after
  merging, releases it on the next check;
- a sync or enrichment job is running, or the API is not answering;
- it adds or removes an Alembic revision. The release is installed but not
  activated, and the phone is told. `run --allow-migration` (below) takes and
  verifies a backup, migrates and activates;
- it is not ahead of the running commit on `main`. The deployer never moves
  the server backwards, and never replaces a build deployed by hand from a
  branch;
- it is the build an operator rolled back from, or its install or activation
  failed. A later merge deploys normally.

Turn it on by creating `/etc/tradejournal/autodeploy.env` from
`deploy/autodeploy.env.example`, root owned with mode 0600. Its
`AUTODEPLOY_CONFIRM_DATABASE` is the exact identity that `sudo
tradejournal-deploy identity` prints, the same confirmation an operator would
type. Set `NTFY_URL` to an ntfy topic to hear about each deploy, hold and
failure on a phone; each is sent once per build. The timer is enabled by every
activation; without that file its service is skipped.

```bash
sudo install -m 0600 /opt/tradejournal/current/deploy/autodeploy.env.example /etc/tradejournal/autodeploy.env
sudoedit /etc/tradejournal/autodeploy.env
AUTODEPLOY=/opt/tradejournal/current/deploy/autodeploy.py
PY=/opt/tradejournal/current/backend/.venv/bin/python
sudo $PY $AUTODEPLOY status
# Skip the market-hours wait for the newest build:
sudo $PY $AUTODEPLOY run --now
# Apply a held schema change: verified backup, migrate, activate:
sudo $PY $AUTODEPLOY run --now --allow-migration
sudo journalctl -u tradejournal-autodeploy --since today
```

To pause it, set `AUTODEPLOY_ENABLED=false`. Manual `migrate`, `activate` and
`rollback` stop the timer while they run, and a rollback stays rolled back.
The deployer runs as root because the controller it calls needs root; its
unit uses `KillMode=process`, so a controller it started always finishes a
release switch. Its decisions are kept in
`/var/lib/tradejournal/autodeploy/state.json`.

## Verification boundaries

`backend/tests/test_deployment.py` covers rollback ordering, incompatible
schemas, checksums, unsafe extraction, ingress configuration isolation,
preflight failure, opt-in service lifecycle and forced runtime bindings. Browser
smoke tests exercise the same-origin proxy with seeded data. The Ubuntu
workflow additionally installs the built artifact, migrates fresh Postgres,
executes queued work, restarts the API without restarting its worker, checks
crash recovery, upgrades through the real autodeploy unit, rolls back, checks
that the deployer then leaves the rollback alone, prunes, preserves state, and
stops and starts the entire service set. The upgrade polls a local stand-in
for GitHub's releases API; the live Release workflow and the VPS polling
GitHub are exercised only after a merge. `backend/tests/test_autodeploy.py`
covers the decisions: market hours and `deploy-now`, ancestry, busy jobs,
schema holds, checksums, and notifications sent once per build. It also runs a restricted PostgreSQL ingress
role, real webhook duplicate/auth checks, stale-alert analysis, a separate OS
user, and the shipped Caddy routing/error-log filter over local HTTP fixtures.
It checks boot enablement; it does not verify public DNS/ACME certificates, reboot
a VPS, enroll Tailscale, exercise Neon networking, or contact live providers;
the Gmail listener runs there disabled, and its Pub/Sub path is covered by
`backend/tests/test_gmail_listener.py` with a fake subscriber.

The frontend packaging follows Next's
[standalone output documentation](https://nextjs.org/docs/app/api-reference/config/next-config-js/output)
and [rewrite proxy documentation](https://nextjs.org/docs/app/api-reference/config/next-config-js/rewrites).
