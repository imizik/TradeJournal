# Trade Journal

Local-first trade journal and reconciliation system for Robinhood/Webull trade history. It ingests fills, rebuilds FIFO trades, tracks open positions, enriches fills/trades with market context, supports AI review, and produces reconciliation/market-report artifacts.

## Structure

- `frontend/` - Next.js 16, React 19, App Router, Tailwind
- `backend/` - FastAPI, SQLModel, Alembic, SQLite by default, Postgres via `DATABASE_URL`
- `docs/agent/` - architecture, domain rules, verification, feature map
- `scripts/` - `setup.sh` and `verify.sh`

## Quick Start

```bash
bash scripts/setup.sh    # clean clone -> runnable (venv, deps, migrations)
bash scripts/verify.sh   # backend tests, frontend typecheck, lint, build
bash startdev.sh         # backend 8080, TradingView ingress 8090, frontend 3000
```

No credentials are needed to install, test, or run against local SQLite. Every
external integration is opt-in; see `backend/.env.example`.

## Run Locally

Backend:

```bash
cd backend
pip install -e .
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Restricted TradingView ingress (only when using live alerts):

```bash
cd backend
uvicorn app.tradingview_ingress:app --reload --no-access-log \
  --host 127.0.0.1 --port 8090
```

Frontend:

```powershell
cd frontend
npm install
$env:NEXT_PUBLIC_API_URL="http://localhost:8000"
npm run dev
```

The frontend dev server runs on `http://localhost:3000` by default. The frontend API base defaults to `http://localhost:8080` when `NEXT_PUBLIC_API_URL` is not set, so set `NEXT_PUBLIC_API_URL=http://localhost:8000` for the normal local backend. If you do move the backend to `8080`, keep `NEXT_PUBLIC_API_URL`, `BACKEND_PUBLIC_URL`, and `FRONTEND_PUBLIC_URL` consistent.

Repo helper note:

- Private backend config loads `.env` before DB init from `backend/.env` first,
  then repo-root `.env`; exported env vars still win.
- The public TradingView process loads only `backend/.env.tradingview`, never
  the private app's shared `.env`.
- `startdev.ps1` starts the private backend on `8080`, restricted TradingView ingress on `8090`, and frontend on `3000`.
- `startdev.sh` is the macOS/Linux equivalent. Both backend processes bind to `127.0.0.1`; tunnel only `8090`, never the private API.
- Both startdev launchers refuse a hosted/private `DATABASE_URL` setup unless
  `TRADINGVIEW_DATABASE_URL` is also set, preventing alerts and the worker
  from silently using different databases.
- `backend/mcp_server.py` defaults to `http://localhost:8000`; set `TRADE_JOURNAL_API=http://localhost:8080` if you want the MCP tools to talk to a backend started by `startdev.ps1`.

## Core Model

- `fill` is the source layer.
- `trade` and `tradefill` are derived from fills by FIFO reconstruction.
- Strategy Lab simulations are stored separately in `strategy_definition`, `strategy_version`, and `strategy_run*` tables; they never enter journal fills or FIFO-derived trades.
- Quantity is stored in `contracts` for stocks and options.
- Stock quantities can be fractional.
- Option `price` is dollars per contract; stock `price` is dollars per share.
- `raw_email_id` dedupes imported fills; manual fills use `manual:` IDs and are backed up to `backend/data/manual_fills.json`.
- Long-running work is tracked in `job_run`.

Current SQLite tables include `account`, `fill`, `trade`, `tradefill`, `tag`, `tradetag`, `job_run`, `fill_market_context`, `trade_path_metrics`, `dailyreview`, `webull_raw_event`, the normalized `strategy_*` Strategy Lab tables, and isolated `tradingview_alert` rows.

## Main API Surfaces

- Health/accounts/stats: `GET /health`, `GET /accounts`, `GET /stats`
- Fills: `GET /fills`, `POST /fills`, `GET /fills/{id}`, `PUT /fills/{id}`, `POST /fills/import`, `POST /fills/resync-all`
- Trades: `GET /trades`, `GET /trades/{id}`, `GET /trades/{id}/fills`, `GET /trades/fills/bulk`, `POST /trades/{id}/tags`, `POST /trades/{id}/review`
- Rebuild: `POST /rebuild`
- Quotes: `GET /quotes`, `POST /quotes/positions`
- Enrichment: `POST /fills/enrich`, `GET /fills/enrich/status`, `POST /market-context/enrich`, `GET /market-context/enrich/status`, `GET /market-context/coverage`
- Trade path/audit: `GET /market-context/trade/{trade_id}`, `GET /market-context/trade-path/bulk`, `POST /market-context/trade-path/compute`, `GET /market-context/trade-path/status`, `GET /market-context/audit/{trade_id}`
- Daily review: `GET /daily-review`, `GET /daily-review/{day}`, `POST /daily-review`
- Sync Center: `GET /sync/summary`, `GET /sync/jobs`, `GET /sync/runs`, `POST /sync/pipeline/run`, `POST /sync/jobs/{job_type}/run`, `POST /sync/advanced/rebuild-all`, `POST /sync/advanced/resync-all`
- Gmail OAuth/push: `GET /auth/gmail/start`, `GET /auth/gmail/start/browser`, `GET /auth/gmail/callback`, `POST /gmail/watch`, `GET /gmail/watch/status`, `POST /gmail/push`
- Webull: `GET /webull/health`, `GET /webull/accounts`, `GET /webull/orders/recent`, `GET /webull/orders/{order_id}`, `POST /webull/events/test-ingest`, `POST /webull/events/start`, `POST /webull/events/stop`, `GET /webull/events/status`
- Market packets: `GET /packets/report?type=premarket|postmarket`, `GET /packets/news`
- Strategy Lab: `GET/POST /strategy-lab/strategies`, `GET/PATCH /strategy-lab/strategies/{id}`, `POST /strategy-lab/strategies/{id}/versions`, `GET/PATCH /strategy-lab/versions/{id}`, `POST /strategy-lab/versions/{id}/fork`, `POST /strategy-lab/imports/preview`, `POST /strategy-lab/runs/import`, `GET /strategy-lab/runs`, `GET /strategy-lab/runs/{run_id}`, `GET /strategy-lab/runs/{run_id}/trades`, `POST /strategy-lab/runs/{run_id}/metrics/recalculate`, `GET /strategy-lab/runs/{run_id}/metrics`
- TradingView private reads: `GET /tradingview/alerts`, `GET /tradingview/alerts/{alert_id}`

The separate port `8090` ingress exposes only `POST /tradingview/webhook` and
`GET /health`; it does not expose any of the private API surfaces above.

## Strategy Lab TradingView Import

TradingView strategy CSVs use a preview-then-commit workflow. `POST /strategy-lab/imports/preview` is multipart with `strategy_version_id`, `source_timezone`, and `file`; it returns `source_sha256`, `version.source_fingerprint`, and `preview_fingerprint` plus the parsed trades and warnings. `POST /strategy-lab/runs/import` re-uploads the same file with a multipart `metadata` JSON field containing those expected fingerprints, the same version/timezone, required `symbol` and `timeframe`, and any optional run fields. Together the fingerprints bind the exact bytes, timezone, and result-producing strategy version.

Both steps require an explicit IANA source timezone such as `America/New_York`; source timestamps are normalized to UTC instead of being inferred from the symbol or filename. Commit is all-or-nothing when preview reports rejected trade groups, and optional backtest bounds must contain every entry and exit date in the source timezone. A compact curl verification is in [Strategy Lab Pine Export Metadata](docs/strategy-lab-pine-metadata.md#curl-verification).

Pine strategies can attach flat, export-visible feature metadata with `sl1|key=value|...`. See [Strategy Lab Pine Export Metadata](docs/strategy-lab-pine-metadata.md) for safe values, merge rules, examples, and current importer limitations.

Imported simulations remain in `strategy_run*` tables and never enter journal fills or FIFO-derived trades. Run metrics are calculated explicitly after import, stored with a calculation version, and expose missing-field coverage instead of silently treating missing values as zero. Formula and curve semantics are documented in [Strategy Lab Metrics](docs/strategy-lab-metrics.md).

## Strategy Lab Frontend

Open `/strategy-lab` to create strategies and immutable-after-use Pine versions, browse version history, and review each version's source, hypothesis, parameters, execution assumptions, and risk notes. The version import page implements the same two-step preview/commit binding as the API and keeps the selected version and hypothesis visible while reviewing mappings, warnings, rejected groups, and normalized trades.

After commit, the run page shows source/run assumptions, coverage-aware deterministic metrics, long/short and time-bucket summaries, equity and drawdown curves, and a paginated simulated-trade table filterable by direction, outcome, and entry date. `GET /strategy-lab/runs` supports strategy/version filters for run history, while the run-detail and trade endpoints omit stored CSV text and raw source-row payloads.

Stage 4 reused the existing normalized `strategy_*` schema and Alembic revision `f1a2b3c4d5e6`; it added no schema migration. Two-run comparison, deterministic findings, experiment workflows, and Pine source diffs remain Stage 5 work.

## TradingView Live Signal Loop

Steps 1–4 are implemented. The frozen v1 parser validates TradingView JSON,
the isolated table preserves immutable first-delivery evidence, and a
token-protected webhook-only process accepts alerts without exposing the
journal API. The private backend runs one database-backed worker that claims
alerts atomically, calls the existing read-only scalp analyzer outside any
transaction, and stores a fenced verdict/confidence/assessment result.

Local setup:

1. Run `alembic upgrade head`.
2. Generate a token:

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

3. Copy `backend/.env.tradingview.example` to
   `backend/.env.tradingview` and put the token there as
   `TRADINGVIEW_WEBHOOK_TOKEN=...`. If the private app uses `DATABASE_URL`,
   set `TRADINGVIEW_DATABASE_URL` to the same database (preferably through a
   restricted ingress role); leave it blank only for default local SQLite.
4. In the private `backend/.env`, set
   `TRADINGVIEW_ANALYSIS_AUTOSTART=true`.
5. Run `bash startdev.sh`, or start `app.main:app` and
   `app.tradingview_ingress:app` separately using the commands above.
6. Test with the sample payload from
   [TradingView Live Alert Contract v1](docs/tradingview-webhook-contract-v1.md):

   ```bash
   curl -X POST http://localhost:8090/tradingview/webhook \
     -H "Authorization: Bearer <TOKEN>" \
     -H "Content-Type: application/json" \
     --data-binary @sample-alert.json
   ```

The TradingView UI cannot attach a Bearer header, so its webhook URL uses
`https://<tunnel-host>/tradingview/webhook?token=<TOKEN>`. Query tokens can
appear in proxy/access logs: the local ingress command disables Uvicorn access
logs, and every tunnel/proxy/cloud hop must also disable or redact the request
target. The token should be dedicated and rotated if exposed. Tunnel only port
`8090`; `/health` returns `200` only when the token and isolated table are
ready.

The private reads are `GET /tradingview/alerts` and
`GET /tradingview/alerts/{alert_id}`. The list omits raw payload, snapshots,
assessment JSON, and full error text; detail returns them explicitly.
Snapshot scalars in detail are tagged (`number`, `string`, `boolean`, `null`)
so exact decimal text and original scalar types remain distinguishable.

`backend/.env.example` documents private worker retry/lease/freshness settings.
`backend/.env.tradingview.example` documents the public token and optional
`TRADINGVIEW_DATABASE_URL`; production must use a service-specific environment
and an ingress database role restricted to `tradingview_alert`. The ingress
never runs migrations. Cloud scale-to-zero still needs an always-on worker or
durable task dispatcher.

The exact payload, bounds, identity format, and future migration policy are in
[TradingView Live Alert Contract v1](docs/tradingview-webhook-contract-v1.md).
The Pine indicator and frontend Signals page remain future Steps 5–6.

## Durable Jobs

```bash
cd backend
python -m app.jobs.run --type polygon_enrich --range all
python -m app.jobs.run --type alpaca_enrich --range all --force
python -m app.jobs.run --type trade_path --range all
python -m app.jobs.run --type webull_listener --accounts WEBULL_ACCOUNT_ID
```

## Gmail Push Ingest

The backend can receive Gmail Pub/Sub notifications and queue a `gmail_push` pipeline that imports new Robinhood fills, rebuilds trades when new fills are saved, then runs enrichment/path work.

Environment:

```bash
GMAIL_PUBSUB_TOPIC=projects/YOUR_PROJECT_ID/topics/YOUR_TOPIC
GMAIL_WATCH_LABEL_IDS=INBOX
GMAIL_PUBSUB_VERIFICATION_TOKEN=choose-a-long-random-token
GMAIL_WATCH_AUTOSTART=true
BACKEND_PUBLIC_URL=https://YOUR_PUBLIC_BACKEND
FRONTEND_PUBLIC_URL=http://localhost:3000
```

Register or renew the watch:

```bash
curl -X POST http://localhost:8000/gmail/watch
```

Pub/Sub should push to:

```text
https://YOUR_PUBLIC_BACKEND/gmail/push?token=choose-a-long-random-token
```

If you keep the backend running continuously, `GMAIL_WATCH_AUTOSTART=true` lets it renew the watch in-process. On startup the backend can also auto-start Webull listeners when `WEBULL_LISTENER_AUTOSTART=true` or `WEBULL_LISTENER_ACCOUNTS` is set. The `gmail_push` pipeline does not wait for slow Polygon enrichment to finish, so check `GET /fills/enrich/status` separately if coverage still looks incomplete right after a successful push or full pipeline run.

## Reconciliation

Reports are generated under `backend/reports/`. Useful scripts:

```bash
cd backend
python scripts/generate_reconciliation_report.py
python scripts/csv_reconstruct.py
python scripts/find_phantoms.py
```

## Tests

```bash
bash scripts/verify.sh          # everything CI runs
bash scripts/verify.sh --fast   # tests + typecheck only
```

Or directly:

```bash
cd backend && pytest -q
cd frontend && npm run typecheck && npm run lint && npm run build
```

The backend suite pins itself to a throwaway SQLite database, so an exported
`DATABASE_URL` (including a hosted Neon one) is ignored and tests never touch
real data. `docs/agent/verification.md` describes what the checks cover and,
just as importantly, what they do not.

Note: `next/font` fetches Google Fonts during `npm run build`, so the build
step needs outbound network access.

## Agent Notes

Durable context for coding agents lives in `docs/agent/`; `CLAUDE.md` and
`AGENTS.md` are thin working agreements that point there. Assorted current
notes:


- `backend/mcp_server.py` is a read-only FastMCP adapter over the local API. It now exposes market packet tools plus journal-analysis tools such as trade detail, coverage, audit, path-metrics, and fill-context fetches.
- `backend/app/engine/trade_path.py` now prefetches minute bars batched by day and uses cache-only fallback reads for misses. Preserve that pattern if you touch path-metric performance.
- Normal rebuilds now preserve reusable `trade_path_metrics` rows. `_rebuild_trades()` snapshots existing metrics, rebuilds derived trades, and restores only rows whose `inputs_fingerprint` still matches the rebuilt trade; destructive resync paths should still clear everything.
- Sync Center treats `webull_listener` as a persistent background listener, not a blocking finite sync job.
- Sync Center pipelines intentionally do not wait for slow Polygon enrich completion. A succeeded pipeline may still have Polygon work running; check `GET /fills/enrich/status` separately.
- Daily review is intentionally separate from "Sync Everything" and Gmail push. Generate it from the daily page or the standalone `daily_review` Sync Center job.

## Postgres/Neon Migration

```bash
cd backend
DATABASE_URL="postgresql+psycopg://USER:PASSWORD@HOST/dbname?sslmode=require" alembic upgrade head
python scripts/migrate_sqlite_to_postgres.py --target "$DATABASE_URL"
```
