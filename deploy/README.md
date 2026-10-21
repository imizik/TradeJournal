# Ubuntu 24.04 deployment

This package runs one private, single-user TradeJournal installation. It uses
native systemd services for Next.js, the API, the sync, Polygon, Webull,
Gmail and capture (voice-plan transcription) worker lanes, plus local/offsite backup, Gmail-import, Sync Everything
and phone-alert timers. Production now uses PostgreSQL on the VPS. The original Neon primary is
retained as a pre-cutover recovery source; it is no longer the live database.

## Access and layout

The [disabled advisor bundle](cloud-mcp-advisor/README.md) is a separate manual
proposal for one invented request. Its source/templates ship in this archive,
but this installer does not install or start advisor units, publish its proxy,
create grants or change existing journal/practice permissions. Retained
installation, grants, ingress and startup require separate owner approval.

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
| Legacy TradingView configuration | Existing `/etc/tradejournal/tradingview.env` is preserved but unused |
| Offsite backup credentials | `/etc/tradejournal/offsite.env` and `restic-password`; root owned, mode 0600 |
| Phone alert settings | `/etc/tradejournal/alerts.env`; root owned, mode 0600 |

The frontend proxy has the same authority as the unauthenticated private API.
Keep **both** services behind private access. Restrict the Tailscale access
policy to the journal owner's devices/identity. Do not use Funnel, a public
reverse proxy, public port forwarding, or expose 3000/8080 in the firewall.
C5.2 retires the public TradingView webhook receiver. The frontend and API
remain private; the release controller removes the old ingress unit during an
upgrade and does not bind port 8090.

All API/worker processes share the same hostname, database URL and local lock
directory. This is not a multi-host worker deployment. Stop the old laptop's
API and workers before enabling the VPS against the same database. Let active
jobs finish first. Previously running rows owned by another host need explicit
operator recovery; see [background jobs](../docs/agent/background-jobs.md).

## Build and obtain the release

The `Deployment package` GitHub Actions workflow builds once on Ubuntu 24.04
x86_64, then installs those exact bytes on two disposable runners in parallel
(the package and MCP smokes, and the slower advisor smoke) and exercises real
systemd services against disposable Postgres. Only when both pass does it upload
`tradejournal-ubuntu-24.04-x86_64` (retained for 14 days). Pull requests run the
advisor smoke only when `scripts/ci_scope.sh` marks them advisor-relevant
(deployment code, migrations, dependencies, access, shared backend modules the
advisor imports, or advisor files); every
`main` push always runs it, so a release has always passed it. Choose a successful
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
Real-time Gmail import is opt-in and needs no public endpoint; see
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

## Voice plans

Voice plans on the chart (Charts C3.5) are saved under
`/var/lib/tradejournal/data/captures`, so the daily backup includes the
recordings and frozen chart images with the database rows that point to them.
`tradejournal-worker@capture` transcribes them with Whisper on this server.
The launcher points `CAPTURE_MODEL_DIR` at `/var/lib/tradejournal/models`,
outside the backed-up data. The first transcription downloads the model
(about 150 MB) from Hugging Face; only the model is downloaded, and recordings
never leave the server. `CAPTURE_TRANSCRIBER=off` in `backend.env` keeps
recordings and skips transcription.

## Manual moomoo Level 2 connection

The optional market-depth lab uses a dedicated `tradejournal-moomoo` systemd
service. It binds only to `127.0.0.1:8196`, has no database or journal-state
access, and makes no provider request at startup. The browser can request one
stream for one validated US ticker, which refreshes its auth in place and runs until stopped
(eight hours at most), after the operator starts the lab. There is no
timer or scheduled work.

Provision it explicitly with the reviewed appkey and Ed25519 PEM stored as
mode-0600 files. The helper validates the private HTTPS Tailscale origin,
creates the dedicated service account, copies the credentials into
root-owned mode-0600 files under `/etc/tradejournal/moomoo`, and writes the
shared token to root-owned mode-0600 environment files. It refuses to overwrite
existing credentials or configuration and never prints the generated token:

```bash
sudo /opt/tradejournal/current/backend/.venv/bin/python \
  /opt/tradejournal/current/deploy/moomoo_config.py \
  --appkey-file /secure/source/appkey \
  --private-key-file /secure/source/phase1-ed25519.pem \
  --web-origin https://YOUR_SERVER.YOUR_TAILNET.ts.net
```

Provisioning does not start or enable the service. For a separately approved
manual activation, enable the bridge and restart the frontend so systemd loads
its optional environment file:

```bash
sudo systemctl enable --now tradejournal-moomoo.service
sudo systemctl restart tradejournal-frontend.service
```

Deployments stop the bridge before replacing the frontend or release, then
restart it only when the unit is explicitly enabled and
`TJ_MOOMOO_LAB_ENABLED=true` is present in
`/etc/tradejournal/moomoo-frontend.env`. A rollback to a release without the
unit stops, disables and removes it while preserving operator credentials and
configuration. Disable the bridge with `sudo systemctl disable --now
tradejournal-moomoo.service`; the frontend lab route is unavailable until the
operator explicitly enables the bridge again.

### Depth recorder and its R2 upload

The [depth recorder](../docs/level2-manual-connection.md#depth-recorder) reuses the
provisioned `tradejournal-moomoo` account and credentials. Releases install its
units but never enable them. To change the default watchlist, write
`TJ_DEPTH_TICKERS=SPY,MU,NBIS,SNDK,NVDA` (plain tickers, at most 20) to a
root-owned 0600 `/etc/tradejournal/depth-recorder.env`, then:

```bash
sudo systemctl enable --now tradejournal-depth-recorder.service
sudo cat /var/lib/tradejournal-depth/status.json
```

For the upload, create a separate private R2 bucket and an Object Read & Write
token scoped to that bucket only (not the offsite backup's). Put its account
endpoint, bucket and keys in a root-owned 0600 `/etc/tradejournal/depth-r2.env`:

```
TJ_DEPTH_R2_ENDPOINT=https://ACCOUNT_ID.r2.cloudflarestorage.com
TJ_DEPTH_R2_BUCKET=trade-journal-depth
TJ_DEPTH_R2_ACCESS_KEY_ID=...
TJ_DEPTH_R2_SECRET_ACCESS_KEY=...
```

then `sudo systemctl enable --now tradejournal-depth-upload.timer`. Deployments
stop both before switching releases and start them again only when enabled; a
recorder that fails to start is reported, not a reason to roll back. A rollback
to a release without these units disables and removes them, so enable them
again after returning to a release that has them.
`sudo systemctl disable --now tradejournal-depth-recorder.service` stops recording;
recorded files stay until removed.

## Backups and scheduled Robinhood import

The release installs five timers:

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
- `tradejournal-options-snapshot.timer` queues the options positioning snapshot
  at 16:20 New York on weekdays, with a 19:20 catch-up that costs no Tradier
  request once the session is recorded; holidays record nothing. A session's
  open interest cannot be captured after 20:00, so if the job cannot be queued
  within ten minutes the unit fails and the phone alert says so.
- `tradejournal-rvol-history.timer` queues the relative-volume history at
  06:00 New York on weekdays, with an 08:40 catch-up: it stores the 20 SIP
  sessions before today for each chart watchlist name, so chart RVol is ready
  at the open. A stored session is never fetched again. If the job cannot be
  queued within ten minutes the run is skipped, not failed: RVol waits for the
  next slot.
- `tradejournal-market-context.timer` queues the earnings and VIX refresh for
  Jo's pre-trade check every 15 minutes, 06:00–16:45 New York on weekdays
  ([market_context.py](../backend/app/engine/market_context.py), Tradier). A
  busy lane skips that slot; the check shows older rows with their age.
- `tradejournal-alerts.timer` checks every two minutes whether anything above,
  the API or real-time Gmail has stopped working, and sends a phone alert.
  Without `/etc/tradejournal/alerts.env` the check is skipped; see
  [Phone alerts](#phone-alerts).

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
The app uses `tj_app`; Alembic uses `tj_owner`; a legacy `tj_ingress` role may
remain in existing databases and is not used by current releases. Removing that
role is a separate operator decision. PostgreSQL, the API and the frontend listen on loopback;
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

## Phone alerts

`tradejournal-alerts.timer` runs `deploy/alerts.py check` every two minutes as
`tradejournal`. It reads the loopback API and `systemctl show`, remembers what
it saw in `/var/lib/tradejournal/alerts/state.json`, and sends one
[ntfy](https://ntfy.sh) notification when a problem starts and one when it
clears. It never repeats an alert.

| Alert | Fires when | Waits |
|---|---|---|
| TradeJournal isn't responding | any of its API requests fails | 5 min |
| Gmail needs reconnecting / Robinhood import stopped | `GET /gmail/health` is `down` or `degraded` | 10 min |
| *Job* failed | the newest finished run of a job type failed; listeners are excluded, and Gmail jobs wait 10 min and stay quiet while the Gmail alert is active | — |
| Nightly backup, Offsite backup, Scheduled Sync Everything, Options snapshot or Relative volume history failed | its systemd service is `failed` | — |
| *Schedule* is switched off | the backup, offsite, Sync Everything, Gmail-check, options-snapshot or relative-volume-history timer is not active | 15 min |
| Server disk is *N*% full | the disk holding `/`, PostgreSQL or the backups is at least 80% used (as `df` reports) | 30 min |
| Server disk is *N*% full (critical) | that disk is at least 90% used; the 80% warning keeps its state meanwhile | — |
| Jo's morning brief is missing / arrived late | opt-in (`JO_MORNING_ALERTS=true`): no brief on the scheduled packet was in the journal by the deadline; one recovery when it arrives | — |
| Jo's morning packet wasn't published | opt-in: no scheduled packet after publication time on an open session | 5 min |
| Morning brief automation stopped / can't load its settings | opt-in: the API's morning runner hasn't completed a pass for three minutes, or its configuration fails to load | 5 min |
| A Jo submission is waiting to be imported / can't be read | opt-in: a submission has no receipt after two minutes, or an outbox file can never import | — |
| Market calendar unavailable for the morning brief | opt-in: the runner can't confirm a weekday session, so it publishes nothing | 15 min |
| Morning brief status unreadable | opt-in: `GET /jo/morning` fails while the rest of the API answers | 10 min |
| Jo's *11:00 AM* market read is missing / arrived late | opt-in (`JO_MARKET_READ_ALERTS=true`): no read for a scheduled 09:50/11:00/12:30/14:00 slot was received 15 minutes after it, once the app has imported reads past that deadline; one recovery when a read arrives inside the 30-minute window | — |
| Jo's market reads aren't being checked | opt-in: market watch is on but the API's read import hasn't run for three minutes (or has no outbox), so missing reads can't be judged | 5 min |
| Market read status unreadable | opt-in: `GET /jo/market-reads` fails while the rest of the API answers | 10 min |

The morning rows read `GET /jo/morning`; see [delivery honesty and the morning
watchdog](../docs/agent/dots-integration.md#delivery-honesty-and-the-morning-watchdog).
The market-read rows read `GET /jo/market-reads`; see [scheduled-read
reliability](../docs/agent/market-watch-design.md#mw-2-implementation-and-activation-boundary).
They are off while `MARKET_WATCH_ENABLED` is off, and closed days and slots after an
early close are not expected.
A morning or market-read send whose outcome is unknown (a timeout while waiting for ntfy's
reply) is recorded and not resent; a connect timeout is a failure and is retried.

Failures that finished before the first check are history and never alerted.
A reboot clears systemd's failed state; only a later successful run counts as
recovery.
A pipeline and its failed step arrive as one message, and an interrupted
import says to run *Rebuild trades*. Messages pass through ntfy.sh, so they
carry only a title and the first line of an error, never fills or P&L.
[Automatic deployment](#automatic-deployment) reports each deploy, hold and
failure to the same topic.

Level alerts set on the charts (Charts C5.1) go to the same topic: the API
service reads `alerts.env` too (optional, as above) and sends each firing
itself, with the symbol, the level, the price and the time.

Create `/etc/tradejournal/alerts.env` from `deploy/alerts.env.example` (root
owned, mode 0600). Anyone who knows a topic on ntfy.sh can read it, so use a
long random topic such as `tradejournal-` followed by `openssl rand -hex 16`.
Subscribe to that topic in the ntfy phone app, then:

```bash
sudo /opt/tradejournal/current/backend/.venv/bin/python /opt/tradejournal/current/deploy/alerts.py test
sudo systemctl start tradejournal-alerts.service
sudo journalctl --no-pager -u tradejournal-alerts.service -n 20
```

If ntfy's anonymous quota is exhausted on a shared hosting IPv6 `/64`, set
`NTFY_IPV4_ONLY=true` in `alerts.env` and restart `tradejournal-api.service`.
This binds API, health and deployment notifications to the server's fixed IPv4
address; it does not change the topic, TLS verification or provider limits.
There is no retry through another address after a refusal. ntfy acceptance is
separate from confirming the notification appeared on the subscribed phone.

The server cannot report its own death. Set `HEALTHCHECK_PING_URL` to an
outside dead-man's switch, such as a free healthchecks.io check with a
five-minute period and ten-minute grace that notifies the same ntfy topic.
Every check pings it, or pings `/fail` when a notification could not be
delivered, and the outside service alerts when the pings stop.

## Retired TradingView webhook ingress

C5.2 removes the public webhook application, its 8090 listener, deployment
unit and Pine alert source. Existing `tradingview_alert` rows remain available
through the private read-only Signals API and pages. The release controller
stops and removes an old `tradejournal-ingress.service` during activation.

The deployment does not delete `/etc/tradejournal/tradingview.env`, remove the
`tradejournal-ingress` OS account, drop the `tj_ingress` database role, or
delete stored alert rows. Those are preserved for recovery and require a
separate operator decision. Existing Caddy or firewall configuration is outside
the release artifact; remove the old webhook route and public 80/443 allowance
when retiring that endpoint.

## Updates, restarts and rollback

Install the next verified archive using its checksum. The installer creates
an offline venv and preserves state/config. Release IDs cannot be overwritten.
When the controller changes, update `/usr/local/sbin/tradejournal-deploy` from
that verified artifact too. Before switching, wait for long-running jobs to
finish; deployment stops the six private services, any installed retired ingress unit,
and every timer except the phone-alert check, which keeps watching so a release that
fails to start is still reported. Workers get 90 seconds to finish, after
which systemd can kill them. Queued jobs survive. Interrupted jobs fail
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
sudo journalctl -u tradejournal-api -u tradejournal-worker@sync -u tradejournal-worker@polygon -u tradejournal-worker@webull -u tradejournal-worker@gmail -u tradejournal-worker@capture -f
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

Each release is about 1.7 GB on the disk PostgreSQL shares, and nothing but
`prune` removes one. Automatic deployment prunes after every successful
switch; after a manual install and activation, run
`sudo /usr/local/sbin/tradejournal-deploy prune --keep 2` yourself. `prune`
never removes the current or previous release, and an older
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
every three minutes `deploy/autodeploy.py` asks GitHub's public API for the
newest `build-*` release (published only after CI and the Ubuntu smoke test
passed on that commit), checks the download against its `SHA256SUMS`, installs
the bundled controller and the release, then activates it with the usual
health checks and rollback. It needs no GitHub credential. A merge normally
goes live about 10 minutes after it lands.

A newer build waits, and is installed later or by a person, while:

- it is 09:25–16:15 New York time on a weekday. An activation restarts
  the private app for about a minute. Adding the `deploy-now` label to the pull request, before or after
  merging, releases it on the next check;
- a sync or enrichment job is running, or the API is not answering;
- it adds or removes an Alembic revision and `AUTODEPLOY_AUTO_MIGRATE` is not
  `true`. With that setting enabled, the deployer creates and verifies a fresh
  backup for the confirmed database and running commit, migrates, and activates.
  A backup or migration failure stops the release and alerts the phone. After
  a migration failure, the controller attempts to restart the prior release
  only when the database is still compatible;
- it is not ahead of the running commit on `main`. The deployer never moves
  the server backwards, and never replaces a build deployed by hand from a
  branch;
- it is the build an operator rolled back from, or its install or activation
  failed. A later merge deploys normally.

Turn it on by creating `/etc/tradejournal/autodeploy.env` from
`deploy/autodeploy.env.example`, root owned with mode 0600. Its
`AUTODEPLOY_CONFIRM_DATABASE` is the exact identity that `sudo
tradejournal-deploy identity` prints, the same confirmation an operator would
type. Each deploy, hold and failure is sent once per build to the
[phone alerts](#phone-alerts) topic in `alerts.env`, through the same sender;
an `NTFY_URL` in `autodeploy.env` sends them to a different topic instead. The
timer is enabled by every activation; without that file its service is
skipped.

Set `AUTODEPLOY_AUTO_MIGRATE=true` in the root-only configuration to let green
`main` builds with schema changes deploy after the market-hours hold. This does
not make an old release schema-compatible: a failed migration may require a
forward fix or a deliberate database restore. Keep the offsite backup and
restore drill healthy; the deployer's immediate pre-migration check verifies
the new local restore point, not an offsite restore.

```bash
sudo install -m 0600 /opt/tradejournal/current/deploy/autodeploy.env.example /etc/tradejournal/autodeploy.env
sudoedit /etc/tradejournal/autodeploy.env
AUTODEPLOY=/opt/tradejournal/current/deploy/autodeploy.py
PY=/opt/tradejournal/current/backend/.venv/bin/python
sudo $PY $AUTODEPLOY status
# Skip the market-hours wait for the newest build:
sudo $PY $AUTODEPLOY run --now
# Apply a held schema change once when automatic migrations are disabled:
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
schemas, checksums, unsafe extraction, and removal of an installed retired
ingress unit. Browser smoke tests exercise the same-origin proxy with seeded data. The Ubuntu
workflow additionally installs the built artifact, migrates fresh Postgres,
executes queued work, restarts the API without restarting its worker, checks
crash recovery, upgrades through the real autodeploy unit, rolls back, checks
that the deployer then leaves the rollback alone, prunes, preserves state, and
stops and starts the entire service set. The upgrade polls a local stand-in
for GitHub's releases API; the live Release workflow and the VPS polling
GitHub are exercised only after a merge. `backend/tests/test_autodeploy.py`
covers the decisions: market hours and `deploy-now`, ancestry, busy jobs,
optional schema migrations, fresh backups, checksums, and notifications sent
once per build. It checks boot enablement; it does not verify public DNS/ACME certificates, reboot
a VPS, enroll Tailscale, exercise Neon networking, or contact live providers;
the Gmail listener runs there disabled, and its Pub/Sub path is covered by
`backend/tests/test_gmail_listener.py` with a fake subscriber. The workflow
runs the sandboxed phone-alert unit against the real API and systemd and
checks that it delivers to a loopback stand-in for ntfy; delivery through
ntfy.sh itself is proved only by `alerts.py test` on the server.

The frontend packaging follows Next's
[standalone output documentation](https://nextjs.org/docs/app/api-reference/config/next-config-js/output)
and [rewrite proxy documentation](https://nextjs.org/docs/app/api-reference/config/next-config-js/rewrites).

### Nightly reviews on the Claude plan (opt-in)

`tradejournal-plan-reviews.timer` writes the Daily Review for the latest
trading day at 20:10 New York (after Sync Everything, enrichment, the options
catch-up and the day's final minute bars), with Claude Code on the owner's Claude plan, never API
credits. It reviews that day when it has no review, gained trades since its
review, or went stale; it never backfills older days, which get a review from
their own Daily Review button. On its first run of a new month it also writes
last month's monthly review. The buttons use the same plan. The release
carries Claude Code at the version `deploy/claude-code/package.json` pins, as
`bin/claude`; its state is under `/var/lib/tradejournal/claude` and the last
run's status in `/var/lib/tradejournal/plan-reviews/status.json`, which the
Daily Review calendar shows. A failed run, or the enabled timer being off,
reaches the phone through the alert check.

Turn it on once, after a release that contains it:

1. On a computer signed in to the Claude plan, run `claude setup-token` and
   copy the token it prints.
2. On the VPS, create the token file. `read -rs` waits for the token without
   showing it; paste it and press Enter:

   ```bash
   sudo install -m 600 -o root -g root /dev/null /etc/tradejournal/claude-plan.env
   read -rs TOKEN && printf 'CLAUDE_CODE_OAUTH_TOKEN=%s\n' "$TOKEN" | sudo tee /etc/tradejournal/claude-plan.env > /dev/null; unset TOKEN
   sudo systemctl restart tradejournal-api
   ```

3. Try one run by hand, then enable the schedule:

   ```bash
   sudo systemctl start tradejournal-plan-reviews.service
   sudo journalctl -u tradejournal-plan-reviews.service -n 40
   sudo systemctl enable --now tradejournal-plan-reviews.timer
   ```

An enabled timer survives releases; a release never enables it. A rollback to
a release from before this feature removes the units, so after rolling forward
again, enable the timer once more. To stop the
nightly reviews, `sudo systemctl disable --now tradejournal-plan-reviews.timer`.
The run uses the plan's usage like any Claude Code session, about one review a
trading day; a failed call (for example the plan's limit) is recorded and the
next run tries again. `claude-plan.env.example` lists the optional model,
timeout and budget.

### A3 Practice preparation (opt-in, disabled)

The package includes a dedicated `practice` worker lane and
`tradejournal-practice.service` / `tradejournal-practice.timer`. The release
controller installs the timer but does not enable it. It runs at 08:50
America/New_York only after a separate operator enablement decision. The finite
job uses the same persistent `JOB_LOCK_DIR`; manual requests do not wait behind
broker imports or voice transcription. Calendar failures/closures and missed
09:00 deadlines produce explicit records. Preparation never arms a plan.

Both `PRACTICE_SCHEDULE_ENABLED` and `PRACTICE_AGENT_ENABLED` default off.
Enabling an agent requires explicit approval of the exact Anthropic model,
`PRACTICE_AGENT_TIMEOUT_SECONDS` (≤120), `PRACTICE_AGENT_INPUT_TOKENS` (≤20000),
`PRACTICE_AGENT_OUTPUT_TOKENS` (≤4000), `PRACTICE_AGENT_DAILY_USD`,
`PRACTICE_AGENT_INPUT_USD_PER_MILLION` and
`PRACTICE_AGENT_OUTPUT_USD_PER_MILLION`, with operator-verified rate provenance.
There is at most one reserved attempt per ET day, including revisions; failed
or uncertain calls never retry automatically. Missing usage/cost remains unknown.
Do not enable the timer or paid runtime merely because these units are packaged.
A3 deployment requires separate approval and migration/Ubuntu CI verification.
Three real sessions with actual morning-plus-review timings are still required
for [live acceptance](../docs/agent/a3-implementation-contract.md).

## Optional browser authentication (disabled by default)

The existing installation stays private through Tailscale. Chunk 2 adds an
opt-in authenticated mode and a separately configured assistant frontend;
there is no bundled public TLS ingress and the assistant unit is never enabled
by the release controller. The
[access contract](../docs/agent/cloud-browser-auth-contract.md) defines the
sample-data browser trial and the separate live-exposure gate.

The owner frontend remains on loopback port 3000 and establishes owner sessions
through its private server credential. The assistant frontend is a separate
process on loopback port 3001 with a separate credential and OS identity. Its
credential can transport browser sessions but cannot bootstrap an owner. API
port 8080 and PostgreSQL remain loopback-only. Do not publish the private owner
frontend or the legacy unauthenticated API.

Auth configuration is generated explicitly, after selecting origins, with
`deploy/access-config.py`. It writes six mode-0600 files into a named directory
without printing secrets or replacing existing credentials:

- `access-backend.env`: backend auth settings and distinct ingress/service keys.
- `access-owner.env`: the private frontend's ingress credential and origin.
- `access-assistant.env`: the assistant credential/origin, with
  `TJ_ASSISTANT_ENABLED=false`.
- `access-monitor.env`: health-monitor capability.
- `access-automation.env`: only the existing scheduled job operations.
- `access-mcp.env`: a private manual MCP capability, not a Dot credential.

The API and owner units load their optional files on restart. The monitor and
job units load only their named capabilities. The assistant unit uses a dynamic
OS user, cannot read private state/configuration, and has no database or owner
credentials. Backup archives include any installed auth configuration files.
The existing private profile remains the default when no auth files exist;
an assistant profile cannot fall back to it.

On a configured private owner frontend, `/access` creates/revokes/resets
assistant logins and shows new access keys once. Public signup is unavailable.
The inspector gets explicit market symbols and selected practice-run IDs,
never write, paid-model, import or arm rights. Optional journal inspection is
available only when the operator has explicitly configured a sample-data
installation and grants it. That configuration flag is an operator assertion,
not proof that a database contains no real data; verify the actual isolated
fixture installation before issuing the grant. Market-only chart responses
omit journal markers, positions and alert data. Assistant chart preferences
stay in its browser.

Only an approved sample/live trial may turn on `TJ_ASSISTANT_ENABLED` and start
`tradejournal-assistant.service`. No Tailscale Funnel, firewall change, DNS/TLS
service or public reverse proxy is installed by this package. In authenticated
mode, the production browser origin must use HTTPS; insecure cookies are
accepted only with the explicit loopback-fixture switch. Session revocation is
checked on every request and at most every 15 seconds on active SSE streams.

Deployment and rollback stop the assistant unit before switching code and do
not restart it automatically. Keep it stopped when rolling back to a release
without auth. Re-enablement requires checking the exact code/configuration and
approved ingress. Owner access, API/worker health and deterministic paper
monitoring are checked independently.

Verification: `scripts/verify.sh` now includes the ordinary browser suite and
`frontend/playwright.auth.config.ts`, using a separate sample database and two
loopback frontend instances. Browser fixtures prove login, private owner
bootstrap, denied writes/reads, session audience separation, logout and
revocation; they do not establish a live Dot connection, HTTPS deployment or
actual Tailscale ACL behavior. Auth Postgres round-trip/revocation and schema
checks are included in parity CI; native process sandbox behavior is exercised by the disposable Ubuntu
`deploy/auth-smoke.py` trial and must pass CI before live exposure. No local
Mac run establishes that native result.

### Approved isolated Dot sample trial

The separately approved temporary trial and its actual observations are in the
[access contract](../docs/agent/cloud-browser-auth-contract.md#approved-sample-installation-and-handoff).
It is a pinned copied runtime, not the production assistant unit. Production
authentication configuration and private access are unchanged.

The [preparation script](dot_trial_install.py) requires root, an explicit verified
release and a portable frontend archive. It refuses to overwrite trial state or
credentials or pre-existing trial units. Failed preparation stops/removes only
units, identities and directories created by that invocation before allowing a
retry. If cleanup cannot stop a process, it retains state and reports incomplete
rollback for inspection. Keep the verified release's Linux dependencies: a local
archive contains compiled JS/assets, never native macOS `node_modules`. The
[fixture entry point](dot_trial_app.py) checks both configuration and actual
sample-fill provenance before importing the application. HTTP fixture responses
sit inside authorization, not in front of it. The running trial rejects all
non-authentication domain writes for owners as well as assistants; the sole
POST exception returns fixture position quotes without writing journal data.

The trial's services share a private network namespace. Only frontend bridges
3101/3102 bind host loopback; the API does not bind the host namespace. The public
proxy points only to 3101; private sample administration uses Tailscale Serve
8443. Original public Caddy routes and private Serve 443 remain unchanged.
The temporary DNS service is [sslip.io](https://sslip.io/), with HTTPS managed
by the existing [Caddy proxy](https://caddyserver.com/docs/automatic-https).

Keys are root-owned mode-0600 files under `/etc/tradejournal-dot-trial`. Do not
print them, include them in chat, commit them or reuse production credentials.
The owner can reset/revoke the dedicated inspector from the private sample
`/access` page. Operator controls on the pinned copied runtime are:

```bash
sudo /opt/tradejournal-dot-trial/runtime/backend/.venv/bin/python /opt/tradejournal-dot-trial/runtime/deploy/dot_trial_control.py revoke trader-jo
sudo /opt/tradejournal-dot-trial/runtime/backend/.venv/bin/python /opt/tradejournal-dot-trial/runtime/deploy/dot_trial_control.py disable
```

`disable` removes the public Caddy import before revoking every non-owner
principal and version-bumping each to invalidate existing sessions,
disabling the assistant profile and stopping trial sockets/processes. It retains
sample data and revoked credential records for explicit recovery; every
assistant needs a new key before re-enabling. It preserves unrelated Caddy
configuration. The private sample Serve mapping may remain stopped/unavailable;
do not reset the full Tailscale configuration to remove it. Native revocation
was observed; the full shutdown/re-enable recovery drill remains unobserved.
Production deployment does not update or restart this pinned sample runtime.


### Selected sample decision-writing increment

Isaac selected [Trader Jo's first saved sample decision](../docs/agent/dot-decision-trial-contract.md)
on 2026-10-09. The original inspector remains read-only. A separate writer is
bound to one MU/NBIS sample run, has no journal access, and may only save its own
simulated choices. `TJ_SAMPLE_DECISION_WRITES` is disabled unless explicitly set
on the guarded sample runtime. No production profile is enabled by this change.

Use [dot_trial_update.py](dot_trial_update.py) with the exact reviewed commit,
the selected-source backend archive and portable standalone frontend archive.
It validates archives before stopping trial processes, preserves Linux
dependencies and old code/assets/permission flags, and rolls back on startup
failure. Root-private recovery files remain under the isolated trial root.
The selected backend bundle includes the Research Studio forwarding router
required by app startup on older trials. It does not install or start the
research sidecar; no research token or new permission is enabled.
Then [dot_trial_seed.py](dot_trial_seed.py) prepares today's immutable simulated
MU/NBIS packets and privately saves the separate login. Existing credentials
require explicit `--rotate`; resets invalidate prior sessions. Never print the
access key or put it in a chat prompt.

```bash
sudo python3 /path/to/dot_trial_update.py --backend-archive /path/to/backend.tar.gz --frontend-archive /path/to/frontend.tar.gz --commit <reviewed-40-character-commit>
sudo /opt/tradejournal-dot-trial/runtime/backend/.venv/bin/python /opt/tradejournal-dot-trial/runtime/deploy/dot_trial_seed.py
```

Both commands refuse other runtime/database targets. Production configuration,
Tailscale/Caddy routes and journal data are outside this update. Saving a
simulated TAKE never arms a paper plan; its distinct sample policy cannot pass
A2's schema check. Native update and actual Dot write/reopen observations must
be reported separately from local browser/fixture checks.


### Manual synthetic MCP HTTPS trial

The [D0 runbook](../docs/agent/cloud-mcp-d0-runbook.md) prepares a standalone
synthetic `get_profile` service for a private ChatGPT Server URL + OAuth plugin.
Use the manual-only templates under `deploy/cloud-mcp-d0/`; normal releases
neither install nor activate them. A dedicated HTTPS hostname forwards only
MCP/metadata to a mode-0660 Unix socket. The service verifies expiring local
public keys under a network-disabled systemd sandbox, with no model keys, app
imports, paid jobs, OpenAI tunnel or Platform runtime key. Operator key refresh
is a separate bounded HTTPS fetch of issuer metadata/public keys; its optional
15-minute timer publishes only public keys. No model/job scheduler is added.
Stop both socket and service to prevent reactivation.

The deployment CI adds a separate disposable TLS/Caddy/socket smoke after the
ordinary package smoke. It checks real IPv4/IPv6 socket denial and offline
verification, authentication refusal, exact route allowlisting, revocation,
restart and teardown. This fixture evidence does not prove an actual Dot, live
issuer, laptop-off use or account-level usage controls. Those remain trial
acceptance steps; no public route is created by merging the implementation.

### Manual assigned sample MCP reads

The [D1 contract](../docs/agent/cloud-mcp-d1-contract.md) selects two read tools
for one existing MU/NBIS sample assistant. Templates under `deploy/cloud-mcp-d1/`
add only a private Unix socket bridge into the isolated sample API namespace;
the offline adapter and backend both validate the same approved OAuth token.
They do not expose the raw backend publicly or reuse an owner/service key.
Normal deployment does not install these units/drop-ins or enable the new scope.
The runbook covers staged pinned dependencies, exact principal/version binding,
separate `practice:read` consent, manual activation and D0 rollback. CI exercises
the actual namespace/Unix boundary; actual Dot tool/UI acceptance remains separate.

The [first D2 increment](../docs/agent/cloud-mcp-d2-contract.md) adds own sample
choice save/receipt tools through that same private bridge. Its catalog remains
off with `decision_writes=false` (the default). Writes also require
`TJ_CLOUD_MCP_DECISION_WRITES=true`, existing sample-write flags, current
`decision_write=true` and separate `practice:write` OAuth consent. Include
`cloud_mcp_d2_common.py` when staging the standalone adapter; update API/MCP
sources together with rollback retained. Receipt reads require only the existing
read scope; withdrawing writes preserves existing D1 choice reads. This remains
a manual demo increment, with no production activation or context creation.

### Selected sample paper replay increment

Isaac selected [Jo’s own sample paper replay](../docs/agent/dot-sample-replay-contract.md)
on 2026-10-09. Keep prior inspector/writer keys and decisions. The updater’s
explicit selected source set includes the replay engine and P0 schema refusal.
Enable the new capability only on the already-approved guarded sample runtime:

```bash
sudo python3 /path/to/dot_trial_update.py --backend-archive /path/to/backend.tar.gz --frontend-archive /path/to/frontend.tar.gz --commit <reviewed-40-character-commit> --enable-sample-replay
sudo /opt/tradejournal-dot-trial/runtime/backend/.venv/bin/python /opt/tradejournal-dot-trial/runtime/deploy/dot_trial_seed.py --replay
```

The new default ID is `trader-jo-replay`, with one fresh sample run, MU/NBIS, no
journal access and explicit replay permission. The key remains in a mode-0600
private file and is entered only in the sign-in flow. The original WAIT records
cannot become replay plans. No live provider, watcher, model, timer, broker or
notification is enabled. New flags/code/assets roll back together if the isolated
runtime fails readiness. Future continuations are hidden until each actor starts
its own TAKE; stored sample outcomes never write journal fills or P0 events.


### Historical demo connector mode

The existing D1/D2 standalone source set also supports one explicitly linked
historical assistant; see [the contract](../docs/agent/cloud-mcp-historical-contract.md).
Keep `sample_only=true`, set `exercise_kind="historical"` in the private config,
and opt in with `TJ_CLOUD_MCP_HISTORICAL_ENABLED=true` in the isolated API only.
The existing historical factory/writer flags and current own-run grants remain
required. Restart the verifiers together after any mode or identity change.
Do not repoint the synthetic account, change production configuration or copy
provider/model credentials. Historical replay is available only in the browser.
Activation and real Jo/restart acceptance remain a separate manual demo step.
