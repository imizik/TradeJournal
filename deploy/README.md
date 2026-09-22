# Ubuntu 24.04 deployment

This package runs one private, single-user TradeJournal installation. It uses
native systemd services for Next.js, the API, the sync, Polygon, Webull and
Gmail worker lanes, plus backup, Gmail-import and Sync Everything timers. **The initial database remains Neon.** Moving that database to
the VPS is a separate cutover, gated on an off-host backup and a successful
restore rehearsal with data checks. Nothing here exports or deletes Neon data.

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

The frontend proxy has the same authority as the unauthenticated private API.
Keep **both** services behind private access. Restrict the Tailscale access
policy to the journal owner's devices/identity. Do not use Funnel, a public
reverse proxy, public port forwarding, or expose 3000/8080 in the firewall.
The only application designed for public webhooks is the separate TradingView
ingress on 8090; deploying that ingress is outside this package.

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

Download its artifact from Actions. It contains:

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

Set `DATABASE_URL` to the existing Neon application-role URL. Set
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

The release installs three timers:

- `tradejournal-backup.timer` runs daily at 05:15 UTC with up to 15 minutes of
  jitter. It creates a custom-format PostgreSQL dump plus a compressed archive
  of `/var/lib/tradejournal/data` and `oauth`, verifies both, and retains seven
  dated restore points under `/var/backups/tradejournal/`.
- `tradejournal-gmail-sync.timer` checks Gmail five minutes after boot and five
  minutes after each prior check finishes. It treats an already-active sync as
  a safe skip. When Gmail imports new fills, it waits for that durable job and
  then queues a trade rebuild; it does not start market-data enrichment.
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
themselves. Ensure the provider's daily VPS backup is active so they leave the
host, and retain a second-provider copy before moving Postgres off Neon. A
successful `verify` checks archive structure and checksums; the local-Postgres
cutover still requires restoring a dump into a disposable database and
querying it before changing `DATABASE_URL`.

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

## Updates, restarts and rollback

Install the next verified archive using its checksum. The installer creates
an offline venv and preserves state/config. Release IDs cannot be overwritten.
When the controller changes, update `/usr/local/sbin/tradejournal-deploy` from
that verified artifact too. Before switching, wait for long-running jobs to
finish; deployment stops all six services and the timers. Workers get 90 seconds to finish,
after which systemd can kill them. Queued jobs survive. Interrupted jobs fail
visibly and need an explicit new run; destructive or paid work is never
automatically replayed.

```bash
sudo tradejournal-deploy migrate NEW_RELEASE_ID --confirm-database 'HOST/DATABASE'
sudo tradejournal-deploy activate NEW_RELEASE_ID --confirm-database 'HOST/DATABASE'
sudo tradejournal-deploy status
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

All six units are enabled for boot and restart on process failure. A provider
error that is caught inside a still-running worker is not a process crash;
inspect job failures/logs. Webull's reconnect cap remains unchanged. On the
first real VPS, verify a reboot, browser access, OAuth, and the desired live
integrations. No real VPS or Tailscale enrollment is created by this PR.

## Verification boundaries

`backend/tests/test_deployment.py` covers rollback ordering, incompatible
schemas, checksums, unsafe extraction and forced runtime bindings. Browser
smoke tests exercise the same-origin proxy with seeded data. The Ubuntu
workflow additionally installs the built artifact, migrates fresh Postgres,
executes queued work, restarts the API without restarting its worker, checks
crash recovery, upgrades/rolls back releases, preserves state, and stops and
starts the entire service set. It checks boot enablement; it does not reboot
a VPS, enroll Tailscale, exercise Neon networking, or contact live providers;
the Gmail listener runs there disabled, and its Pub/Sub path is covered by
`backend/tests/test_gmail_listener.py` with a fake subscriber.

The frontend packaging follows Next's
[standalone output documentation](https://nextjs.org/docs/app/api-reference/config/next-config-js/output)
and [rewrite proxy documentation](https://nextjs.org/docs/app/api-reference/config/next-config-js/rewrites).
