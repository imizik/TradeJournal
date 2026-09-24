# Background jobs on one server

The API commits requests to `job_run`. With `JOB_EXECUTION_MODE=external`,
separate workers execute them. This supports a single Linux or macOS host with
SQLite or a hosted PostgreSQL, including the VPS database production now uses.
It does not change database credentials or move the database.

## Ownership and recovery

`backend/app/engine/job_runtime.py` claims a queued row atomically and records
its executor, hostname and lock directory. A kernel file lock covers the entire
execution, including network calls. Another process cannot run the same job or
declare its owner dead while that lock is held. There is no heartbeat timeout
that could mistake a slow provider request for a crashed worker.

Every process for one database must run on the **same host**, with the **same
absolute `JOB_LOCK_DIR` on local disk** and the same database endpoint spelling.
The directory must survive releases and be writable by the service account.
Containers would need the same bind mount and hostname. Multiple hosts and
network filesystems are unsupported. Never delete lock files while executors
are running; unlinking them defeats mutual exclusion. A job from a different
host or lock directory is left untouched for operator investigation.

Four execution lanes have separate locks:

| Lane | Work |
|---|---|
| `sync` | Gmail import/push, Gmail watch renewal, fill check, rebuild, pipelines, Alpaca, path metrics, requested daily review and confirmed resync |
| `polygon` | Polygon enrichment, which can continue after a pipeline completes |
| `webull` | The persistent Webull listener |
| `gmail` | The persistent Gmail Pub/Sub listener, which only queues `gmail_push` and `gmail_watch_renew` work for `sync` |

Pipeline children execute inside the parent's sync lane. Polygon is queued
independently, so provider pacing cannot block pipeline completion. Additional
workers in the same lane provide no extra concurrency. This serializes queued
job execution; direct synchronous API mutations are outside this mechanism.

On worker startup and each idle poll:

- Queued requests remain eligible, including requests committed just before an
  API crash. Gmail push notifications are queued even while another sync runs.
- A running request whose local owner has died becomes **failed**, with an
  explanation that partial work may already be committed. It is never replayed
  automatically. This also applies to destructive resyncs and paid reviews.
- Live owners are left alone. API restarts in external mode do not recover or
  execute jobs at all. Embedded mode uses the same ownership locks.
- Legacy running rows without ownership require the explicit migration step
  below. A stop request for an unclaimed Webull listener cancels it.

After an interrupted import or pipeline, inspect the failed run. Import again
if needed, then explicitly **Rebuild trades / FIFO matching** before enrichment:
fills may have committed before the interrupted pipeline reached its rebuild.
An ordinary pipeline skips rebuilding when its own import saves no new fills.
Existing fill dedupe keys and FIFO rules are unchanged. A destructive resync
requires a new confirmed request; it is not a generic retry operation. Daily
reviews may already have incurred provider charges before an interruption.

## Rollout and commands

1. Stop all old API and job processes before upgrading from code without
   ownership. Old executors cannot participate in the new locks.
2. From `backend/`, run `.venv/bin/python scripts/check_database.py` and verify
   the target. Apply `.venv/bin/python -m alembic upgrade head` using the
   existing migration credentials. The new revision adds nullable ownership
   fields; neither the API nor workers migrate automatically.
3. Configure these values for the API and **every** worker. Provision the lock
   directory for the service account before launching:

   ```bash
   export JOB_EXECUTION_MODE=external
   export JOB_LOCK_DIR=/var/lib/tradejournal/job-locks
   ```

4. Only for the first upgrade, after all old executors have stopped, mark old
   running rows as interrupted, without executing queued work:

   ```bash
   .venv/bin/python -m app.jobs.worker --lane sync --recover-unowned --recover-only
   .venv/bin/python -m app.jobs.worker --lane polygon --recover-unowned --recover-only
   .venv/bin/python -m app.jobs.worker --lane webull --recover-unowned --recover-only
   .venv/bin/python -m app.jobs.worker --lane gmail --recover-unowned --recover-only
   ```

5. Run each command as a separate supervised process, from `backend/`, with
   the same application database configuration and integration credentials:

   ```bash
   .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
   .venv/bin/python -m app.jobs.worker --lane sync
   .venv/bin/python -m app.jobs.worker --lane polygon
   .venv/bin/python -m app.jobs.worker --lane webull
   .venv/bin/python -m app.jobs.worker --lane gmail
   ```

The Webull worker consumes a listener request made by the existing Start route
or `WEBULL_LISTENER_AUTOSTART=true` on API startup. It does not invent a
subscription or restart a failed listener automatically. Existing bounded
transport reconnects and credential failures remain visible as failed runs.

The Gmail worker differs on purpose. With `GMAIL_LISTENER_ENABLED=true` and a
subscription and key configured, it queues its own `gmail_listener` request
before each poll whenever none is queued or running, backing off 10 s, 30 s,
2 min, 10 min, then 30 min after consecutive failures. Pub/Sub has no
connection cap to protect, and an API-side autostart would race deploys: the
API starts before the workers and would still see the dead run as running.
SIGTERM sets `job_runtime.shutdown_requested`, so the listener ends as
succeeded ("Stopped for shutdown") within seconds instead of waiting out the
kill timeout. Stream errors resubscribe in place; credential and subscription
errors fail the run with the setting to check. The listener never calls Gmail.
It queues `gmail_watch_renew` in the sync lane daily and whenever the watch
is within 48 hours of Gmail's seven-day expiry, and then `GMAIL_WATCH_AUTOSTART`
is ignored. Push requests coalesce: at most one `gmail_push` waits at a time,
and one is re-queued behind a running push because that run may already have
read the history cursor.

Workers poll every five seconds (`--poll-seconds` adjusts this). This keeps a
hosted database awake: it is not a scale-to-zero design. SIGTERM stops claiming
new work and allows current work to finish. Configure a supervisor shutdown
timeout appropriate to provider waits; a forced kill releases the locks and
the next worker records the interruption. A Webull stream may need that timeout
because its existing subscriber checks cancellation between messages.

For development, the default `JOB_EXECUTION_MODE=embedded` keeps API-owned
background threads. On startup it recovers interrupted owned runs and dispatches
queued work. Its default lock directory is under `backend/data/`; set a common
explicit directory when multiple checkouts target the same database.

`python -m app.jobs.run --job-id <uuid>` remains available for one queued job.
It cannot replay a completed or failed row or steal a running job. Its existing
`--type` options create new enrichment or listener requests.

## Remaining work and evidence

Optional TradingView analysis, and Gmail watch renewal when the Gmail listener
is disabled (`GMAIL_WATCH_AUTOSTART`, development only), are still API-owned
background threads. TradingView already has its own database claim/recovery
mechanism, separate from `job_run`. Direct request-time review/import endpoints
also remain request-time operations. The [Ubuntu deployment package](../../deploy/README.md)
now provides systemd services for the four lanes and the private API/frontend.
It does not alter Webull reconnection policy or move the remaining API threads
to supervised worker lanes.

`backend/tests/test_job_runtime.py` exercises competing real processes, API
lifespan restarts during execution, forced process death, persisted queue
consumption, nested pipelines, and import retry/dedupe with FIFO reconstruction.
Provider traffic is stubbed. The suite does not exercise live Gmail, Webull,
Alpaca, or Polygon. The separate Ubuntu deployment workflow exercises systemd
with a packaged application and disposable Postgres; real-VPS reboot and live
provider checks remain operator work. Those checks and Postgres-specific tests
are separate from the local verification script.
