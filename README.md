# Trade Journal

Local-first trade journal and reconciliation system for Robinhood/Webull trade history. It ingests fills, rebuilds FIFO trades, tracks open positions, enriches fills/trades with market context, supports AI review, and produces reconciliation/market-report artifacts.

## Structure

- `frontend/` - Next.js 16, React 19, App Router, Tailwind
- `backend/` - FastAPI, SQLModel, Alembic, SQLite by default, Postgres via `DATABASE_URL`

## Run Locally

Backend:

```bash
cd backend
pip install -e .
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
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

- Backend config now loads `.env` before DB init from `backend/.env` first, then repo-root `.env`; exported env vars still win. This is where `DATABASE_URL`, API keys, autostart flags, and public callback URLs should usually live.
- `startdev.ps1` intentionally starts the backend on `8080` and points the frontend there.
- `startdev.sh` is the macOS/Linux equivalent and relies on the same `.env` loading behavior instead of exporting `DATABASE_URL` inline.
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

Current SQLite tables include `account`, `fill`, `trade`, `tradefill`, `tag`, `tradetag`, `job_run`, `fill_market_context`, `trade_path_metrics`, `dailyreview`, `webull_raw_event`, and the normalized `strategy_*` Strategy Lab tables.

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

## Strategy Lab TradingView Import

TradingView strategy CSVs use a preview-then-commit workflow. `POST /strategy-lab/imports/preview` is multipart with `strategy_version_id`, `source_timezone`, and `file`; it returns `source_sha256`, `version.source_fingerprint`, and `preview_fingerprint` plus the parsed trades and warnings. `POST /strategy-lab/runs/import` re-uploads the same file with a multipart `metadata` JSON field containing those expected fingerprints, the same version/timezone, required `symbol` and `timeframe`, and any optional run fields. Together the fingerprints bind the exact bytes, timezone, and result-producing strategy version.

Both steps require an explicit IANA source timezone such as `America/New_York`; source timestamps are normalized to UTC instead of being inferred from the symbol or filename. Commit is all-or-nothing when preview reports rejected trade groups, and optional backtest bounds must contain every entry and exit date in the source timezone. A compact curl verification is in [Strategy Lab Pine Export Metadata](docs/strategy-lab-pine-metadata.md#curl-verification).

Pine strategies can attach flat, export-visible feature metadata with `sl1|key=value|...`. See [Strategy Lab Pine Export Metadata](docs/strategy-lab-pine-metadata.md) for safe values, merge rules, examples, and current importer limitations.

Imported simulations remain in `strategy_run*` tables and never enter journal fills or FIFO-derived trades. Run metrics are calculated explicitly after import, stored with a calculation version, and expose missing-field coverage instead of silently treating missing values as zero. Formula and curve semantics are documented in [Strategy Lab Metrics](docs/strategy-lab-metrics.md).

## Strategy Lab Frontend

Open `/strategy-lab` to create strategies and immutable-after-use Pine versions, browse version history, and review each version's source, hypothesis, parameters, execution assumptions, and risk notes. The version import page implements the same two-step preview/commit binding as the API and keeps the selected version and hypothesis visible while reviewing mappings, warnings, rejected groups, and normalized trades.

After commit, the run page shows source/run assumptions, coverage-aware deterministic metrics, long/short and time-bucket summaries, equity and drawdown curves, and a paginated simulated-trade table filterable by direction, outcome, and entry date. `GET /strategy-lab/runs` supports strategy/version filters for run history, while the run-detail and trade endpoints omit stored CSV text and raw source-row payloads.

Stage 4 reused the existing normalized `strategy_*` schema and Alembic revision `f1a2b3c4d5e6`; it added no schema migration. Two-run comparison, deterministic findings, experiment workflows, and Pine source diffs remain Stage 5 work.

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
cd backend
pytest
```

If `pytest` is unavailable in the local environment, use:

```bash
cd backend
python -m compileall app scripts
```

Frontend validation notes:

- `npm run lint` may still fail because `frontend/package.json` still uses `next lint` on Next 16.
- `npm run build` may fail in network-restricted environments because `next/font` fetches Google Fonts.

## Agent Notes

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
