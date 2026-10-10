# Trade Journal

Local-first trade journal and reconciliation system for Robinhood/Webull trade history. It ingests fills, rebuilds FIFO trades, tracks open positions, enriches fills/trades with market context, supports AI review, and produces reconciliation/market-report artifacts.

## Structure

- `frontend/` - Next.js 16, React 19, App Router, Tailwind
- `backend/` - FastAPI, SQLModel, Alembic, SQLite by default, Postgres via `DATABASE_URL`
- `docs/agent/` - architecture, domain rules, verification, environments, feature map, roadmap
- `research/` - strategy factory specs, weekly reports and the ledger of every idea it has judged; the live copy is on branch `factory/ledger` (`docs/strategy-factory.md`)
- `scripts/` - `setup.sh`, `verify.sh`, and `factory_week.sh` (the strategy factory's weekly run)

## Quick Start

```bash
bash scripts/setup.sh    # clean clone -> runnable (venv, deps, migrations)
bash scripts/verify.sh   # backend lint + tests, import boundaries, frontend typecheck/lint/build, browser tests
bash startdev.sh         # backend 8080, frontend 3000
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
- `startdev.ps1` and `startdev.sh` start the private backend on `8080` and
  frontend on `3000` by default.
- `backend/mcp_server.py` defaults to `http://localhost:8000`; set
  `TRADE_JOURNAL_API=http://localhost:8080` if you want the MCP tools to talk
  to a backend started by `startdev.ps1`.

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

C5.2 retired the TradingView webhook ingress. The retained TradingView alert
API routes are private GET-only reads of historical rows.

## Strategy Lab TradingView Import

TradingView strategy CSVs use a preview-then-commit workflow. `POST /strategy-lab/imports/preview` is multipart with `strategy_version_id`, `source_timezone`, and `file`; it returns `source_sha256`, `version.source_fingerprint`, and `preview_fingerprint` plus the parsed trades and warnings. `POST /strategy-lab/runs/import` re-uploads the same file with a multipart `metadata` JSON field containing those expected fingerprints, the same version/timezone, required `symbol` and `timeframe`, and any optional run fields. Together the fingerprints bind the exact bytes, timezone, and result-producing strategy version.

Both steps require an explicit IANA source timezone such as `America/New_York`; source timestamps are normalized to UTC instead of being inferred from the symbol or filename. Commit is all-or-nothing when preview reports rejected trade groups, and optional backtest bounds must contain every entry and exit date in the source timezone. A compact curl verification is in [Strategy Lab Pine Export Metadata](docs/strategy-lab-pine-metadata.md#curl-verification).

Pine strategies can attach flat, export-visible feature metadata with `sl1|key=value|...`. See [Strategy Lab Pine Export Metadata](docs/strategy-lab-pine-metadata.md) for safe values, merge rules, examples, and current importer limitations.

Imported simulations remain in `strategy_run*` tables and never enter journal fills or FIFO-derived trades. Run metrics are calculated explicitly after import, stored with a calculation version, and expose missing-field coverage instead of silently treating missing values as zero. Formula and curve semantics are documented in [Strategy Lab Metrics](docs/strategy-lab-metrics.md).

## Strategy Lab Frontend

Open `/strategy-lab` to create strategies and immutable-after-use Pine versions, browse version history, and review each version's source, hypothesis, parameters, execution assumptions, and risk notes. The version import page implements the same two-step preview/commit binding as the API and keeps the selected version and hypothesis visible while reviewing mappings, warnings, rejected groups, and normalized trades.

After commit, the run page shows source/run assumptions, coverage-aware deterministic metrics, long/short and time-bucket summaries, equity and drawdown curves, and a paginated simulated-trade table filterable by direction, outcome, and entry date. `GET /strategy-lab/runs` supports strategy/version filters for run history, while the run-detail and trade endpoints omit stored CSV text and raw source-row payloads.

Stage 4 reused the existing normalized `strategy_*` schema and Alembic revision `f1a2b3c4d5e6`; it added no schema migration. Two-run comparison, deterministic findings, experiment workflows, and Pine source diffs remain Stage 5 work.

## Retired TradingView alert records

C5.2 retired the public webhook, its Pine alert source and the analysis worker
after an in-house chart alert was observed on the phone. Existing `tradingview_alert`
rows and the `/signals` pages remain read-only. The old `v=1` contract and
implementation plan are retained as historical documentation; the legacy ingress
configuration and database role are preserved, but current releases do not use
them. See [the retired contract](docs/charts-roadmap.md#phase-5--alerts-on-the-chart).

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
BACKEND_PUBLIC_URL=http://localhost:8000
FRONTEND_PUBLIC_URL=http://localhost:3000
```

`BACKEND_PUBLIC_URL` names where *this* process is reachable, for OAuth
redirects. Keep it local. It is not an instruction to expose the backend.

Register or renew the watch:

```bash
curl -X POST http://localhost:8000/gmail/watch
```

Pub/Sub would push to `POST /gmail/push`, and **that path is not supported
today.** Two things stand in the way, both worth knowing before you wire it up:

- Pub/Sub push needs a public HTTPS endpoint, and `/gmail/push` lives on the
  private API, which has no authentication and must never be internet-reachable
  (see the hard constraints in `CLAUDE.md`). No application ingress is
  currently available.
- `_verify_push_token` returns early when `GMAIL_PUBSUB_VERIFICATION_TOKEN` is
  unset, so an unconfigured token accepts **any** caller. Exposing the route
  with the token blank would let anyone trigger the ingest pipeline.

Use the OAuth pull path instead — `POST /sync/pipeline/run`, or the Sync
Center in the UI — which needs no public endpoint. Reintroducing push requires
a separately reviewed authenticated service design.

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
bash scripts/verify.sh          # local checks; CI also tests Postgres and systemd
bash scripts/verify.sh --fast   # lint, import boundaries, tests, typecheck
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

For private Ubuntu 24.04 hosting, see the [deployment guide](deploy/README.md).
It packages independent systemd services and preserves runtime state across
releases. Production now uses PostgreSQL on the VPS after a verified Neon
backup, row-count comparison and encrypted offsite restore drill.

Durable context for coding agents lives in `docs/agent/`. `CLAUDE.md` is the
working agreement and points there; `AGENTS.md` points at `CLAUDE.md`, so
there is only one copy. Assorted current notes:


- `backend/mcp_server.py` is a read-only FastMCP adapter over the local API. It now exposes market packet tools plus journal-analysis tools such as trade detail, coverage, audit, path-metrics, and fill-context fetches.
- `backend/app/engine/trade_path.py` now prefetches minute bars batched by day and uses cache-only fallback reads for misses. Preserve that pattern if you touch path-metric performance.
- Normal rebuilds now preserve reusable `trade_path_metrics` rows. `_rebuild_trades()` snapshots existing metrics, rebuilds derived trades, and restores only rows whose `inputs_fingerprint` still matches the rebuilt trade; destructive resync paths should still clear everything.
- Sync Center treats `webull_listener` as a persistent background listener, not a blocking finite sync job.
- Sync Center pipelines intentionally do not wait for slow Polygon enrich completion. A succeeded pipeline may still have Polygon work running; check `GET /fills/enrich/status` separately.
- Daily review is intentionally separate from "Sync Everything" and Gmail push. Generate it from the daily page or the standalone `daily_review` Sync Center job.

## SQLite to PostgreSQL migration (development databases)

This is for a new PostgreSQL target, not the live VPS database. See the
[deployment guide](deploy/README.md) for production operations.

```bash
cd backend
export DATABASE_URL="postgresql+psycopg://USER:PASSWORD@HOST/dbname?sslmode=require"
export MIGRATION_DATABASE_URL="$DATABASE_URL"
.venv/bin/python -m alembic upgrade head
.venv/bin/python scripts/migrate_sqlite_to_postgres.py --target "$DATABASE_URL"
```
