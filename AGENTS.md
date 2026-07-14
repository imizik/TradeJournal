# AGENTS.md

Read this first before making changes in this repo.

## Project In One Paragraph

Trade Journal is a local-first Robinhood trade history system built around fill ingestion, FIFO trade reconstruction, analytics, enrichment, and reconciliation. The live repo already supports stocks and options, multiple account records, Gmail execution-email import, manual fill entry/edit, full trade rebuilds, durable enrichment jobs, and markdown reconciliation reporting.

Current scope also includes Webull read/listen/import plumbing, a Sync Center, Gmail Pub/Sub push ingest, AI trade/day review, market packets for Claude Desktop, quotes, fill-level Alpaca context, and trade-level path metrics.

Strategy Lab now has an end-to-end local workflow for version-controlled Pine research: normalized strategy definitions, immutable-after-use Pine versions, run/trade/metrics/experiment tables, strategy/version creation and history, Pine source pages, a preview-then-commit TradingView CSV importer, and deterministic persisted run metrics. The frontend exposes run metadata, coverage-aware metrics, equity/drawdown curves, and filterable simulated trades. Imports require an explicit source timezone and remain isolated from journal fills/trades. Run comparison, deterministic findings, experiment workflows, and Pine diffs remain Stage 5 work.

## Agent Operating Style

Work like a fast, practical senior dev helper:

- Read only the files that matter for the reported issue.
- Batch file reads, searches, and cheap status checks.
- Do not repeatedly inspect repo state unless something changed.
- Find the root cause, make the smallest safe fix, and avoid broad refactors.
- Do not ask "want me to fix this?" when the fix is obvious and local.
- Keep narration short while working and final summaries shorter: what changed, validation, risks.
- Run the cheapest useful validation for the touched surface.
- Avoid duplicated UI/table logic and slow frontend N+1 data fetching.
- Be extra careful around PnL, FIFO reconstruction, fill import/parsing, account identity, nullable enrichment fields, and reconciliation.

## Current Reality

- This is not just the original scaffold anymore.
- This is not options-only anymore.
- This is not Roth-only anymore.
- The important live accounts are Roth IRA `8267` and Individual `1113`.
- `trade` rows are derived from `fill` rows and are safe to wipe and rebuild.
- Manual data repair currently happens by editing fills and rebuilding.
- Strategy Lab simulations stay in `strategy_run*` tables and never enter `fill`, `trade`, or `tradefill`.

## Highest-Leverage Files

Backend:

- `backend/app/engine/reconstructor.py`
- `backend/app/engine/email_parser.py`
- `backend/app/engine/gmail_poller.py`
- `backend/app/engine/enricher.py`
- `backend/app/engine/alpaca.py`
- `backend/app/engine/alpaca_enricher.py`
- `backend/app/engine/jobs.py`
- `backend/app/engine/quotes.py`
- `backend/app/engine/trade_path.py`
- `backend/app/engine/webull.py`
- `backend/app/engine/webull_client.py`
- `backend/app/engine/webull_events.py`
- `backend/app/engine/webull_listener.py`
- `backend/app/engine/packets.py` (premarket/postmarket market reports; universe in `backend/data/universe.json`)
- `backend/app/engine/scalper.py` (read-only scalp setup assessment: live data gathering + pure deterministic scoring; never trades)
- `backend/app/engine/strategy_lab.py` (Strategy Lab definition/version lifecycle, fingerprints, locking, champion transitions)
- `backend/app/engine/strategy_metrics.py` (pure Decimal Strategy Lab run metrics, coverage, breakdowns, equity, and drawdown)
- `backend/mcp_server.py` (read-only MCP stdio server for Claude Desktop; market packet + trade-analysis tools over localhost:8000)
- `backend/app/ai/reviewer.py`
- `backend/app/ai/daily_reviewer.py`
- `backend/app/routers/auth.py`
- `backend/app/routers/fills.py`
- `backend/app/routers/trades.py`
- `backend/app/routers/stats.py`
- `backend/app/routers/quotes.py`
- `backend/app/routers/market_context.py`
- `backend/app/routers/sync.py`
- `backend/app/routers/daily_review.py`
- `backend/app/routers/gmail_push.py`
- `backend/app/routers/packets.py`
- `backend/app/routers/webull.py`
- `backend/app/routers/strategy_lab.py`
- `backend/app/main.py`
- `backend/app/models.py`

Frontend:

- `frontend/lib/api.ts`
- `frontend/lib/strategy-lab/` (typed Strategy Lab API client, Decimal-safe response types, and UTC/source-timezone formatting)
- `frontend/app/strategy-lab/` (strategy/version creation and history, Pine source, CSV import, and run analysis pages)
- `frontend/components/strategy-lab/` (import wizard, metrics/curves, and filterable simulated-trade table)
- `frontend/components/DashboardActions.tsx`
- `frontend/components/DashboardTables.tsx`
- `frontend/components/TradesTable.tsx`
- `frontend/components/ManualFillForm.tsx`
- `frontend/app/page.tsx`
- `frontend/app/trades/page.tsx`
- `frontend/app/trades/[id]/page.tsx`
- `frontend/app/daily/page.tsx`
- `frontend/app/daily/[day]/page.tsx`
- `frontend/app/fills/page.tsx`
- `frontend/app/fills/[id]/page.tsx`

Analysis scripts:

- `backend/scripts/generate_reconciliation_report.py`
- `backend/scripts/csv_reconstruct.py`
- `backend/scripts/find_phantoms.py`
- `backend/scripts/migrate_sqlite_to_postgres.py`

## Core Invariants

- `fill` is the source layer.
- `trade` and `tradefill` are derived layers.
- Quantity lives in `contracts` for both stocks and options.
- Stock quantities can be fractional.
- Option `price` is dollars per contract.
- Stock `price` is dollars per share.
- `raw_email_id` is the dedupe key for imported fills.
- Manual fills use `manual:` source IDs and are backed up to `backend/data/manual_fills.json`.
- Enrichment fields are nullable and must be guarded before display, calculations, or AI prompts.
- Bulk `select(Fill)` queries must pass `.options(*FILL_LIGHT)` and fill-returning endpoints must respond with `FillOut` (not raw `Fill`) so legacy email-body columns stay off the wire — DB egress is metered on hosted Postgres.
- `job_run` rows are durable status records for import/enrichment/path jobs; do not rely on process-local progress state.
- Alpaca context is fill-level context in `fill_market_context`; trade-level path metrics are separate rows in `trade_path_metrics`.
- `fill_market_context` also carries journal-derived trader-state sequence metrics (see `backend/app/engine/behavior.py`); `trade_path_metrics` carries ATR-normalized MFE/MAE and options greeks PnL attribution.
- "At fill" daily indicators use the last completed daily bar strictly before the fill date (no look-ahead); Polygon bar keys use real ET tz conversion. Preserve both behaviors.
- Webull raw events are stored first in `webull_raw_event`; normalized fills use `webull:` source IDs.
- AI review output is stored as JSON on `trade.ai_review` or in `dailyreview.review_json`.
- A `strategy_version` with any `strategy_run` is locked for Pine source, parameters, and result-affecting assumptions. Fork it to make a challenger; status and research annotations may still change.

## Main User Flows

- Gmail import: `POST /fills/import`
- Gmail OAuth start/callback: `GET /auth/gmail/start`, `GET /auth/gmail/start/browser`, `GET /auth/gmail/callback`
- Manual fill create: `POST /fills`
- Manual fill edit: `PUT /fills/{id}`
- Rebuild everything from fills: `POST /rebuild`
- Full resync from Gmail plus manual-fill restore: `POST /fills/resync-all`
- Sync Center: `GET /sync/summary`, `GET /sync/jobs`, `GET /sync/runs`, `POST /sync/pipeline/run`, `POST /sync/jobs/{job_type}/run`
- Sync Center advanced rebuild/resync: `POST /sync/advanced/rebuild-all`, `POST /sync/advanced/resync-all`
- Gmail Pub/Sub watch/push: `POST /gmail/watch`, `GET /gmail/watch/status`, `POST /gmail/push`
- Webull listener/test ingest/status: `POST /webull/events/start`, `POST /webull/events/stop`, `POST /webull/events/test-ingest`, `GET /webull/events/status`
- Strategy Lab definitions/versions: `GET/POST /strategy-lab/strategies`, `GET/PATCH /strategy-lab/strategies/{id}`, `POST /strategy-lab/strategies/{id}/versions`, `GET/PATCH /strategy-lab/versions/{id}`, `POST /strategy-lab/versions/{id}/fork`
- Strategy Lab TradingView import: `POST /strategy-lab/imports/preview`, then `POST /strategy-lab/runs/import` with the same file bytes and returned hash/version/preview bindings; an explicit IANA source timezone is required
- Strategy Lab run browsing: `GET /strategy-lab/runs`, `GET /strategy-lab/runs/{run_id}`, and paginated/filterable `GET /strategy-lab/runs/{run_id}/trades`
- Strategy Lab run metrics: `POST /strategy-lab/runs/{run_id}/metrics/recalculate`, then `GET /strategy-lab/runs/{run_id}/metrics`; incomplete source fields stay explicit in metric coverage
- Strategy Lab frontend: open `/strategy-lab`, create a strategy/version, review its Pine source and assumptions, preview/commit a TradingView CSV, then inspect the resulting run, curves, metrics, and simulated trades
- View analytics and breakdowns: `GET /stats`
- Review per-trade history via trade detail and fill timeline pages
- AI trade review: `POST /trades/{id}/review`
- Daily review: `GET /daily-review`, `POST /daily-review`
- Quotes: `GET /quotes`, `POST /quotes/positions`
- Market packets: `GET /packets/report`, `GET /packets/news`, `GET /packets/analyze`, `GET /packets/scalp`
- Polygon enrichment: `POST /fills/enrich`
- Alpaca fill context enrichment: `POST /market-context/enrich`
- Trade path metrics: `POST /market-context/trade-path/compute`
- Enrichment coverage: `GET /market-context/coverage`

## Active Working Tree Features

These exist in the repo right now and may still be in flux:

- Quote endpoints and dashboard mark pricing via `yfinance`
- Webull OpenAPI read/listen/import endpoints and durable listener job
- Sync Center routes and dashboard controls for pipeline/job history
- Daily AI review pages and trade-level AI review actions
- Reusable dashboard/trades table components
- Gmail OAuth can be started from the app instead of copying a terminal URL
- Fill enrichment fields and durable job-backed enrichment status/actions
- Configurable `DATABASE_URL`; SQLite remains the local default, Postgres/Neon is supported for migration/deploy
- Durable job runner CLI for historical enrichment and future Cloud Run Jobs
- Alpaca context and trade-path metrics with cache-aware daily/minute bar handling
- Backend startup may auto-renew Gmail watches and auto-start Webull listeners when the relevant env flags are enabled
- Trade-path computation now batch-prefetches minute bars by day and falls back to cache-only reads for uncovered days to avoid per-trade API fetch loops
- Startup merge of blank-last4 Roth data into canonical `8267`
- New fill columns for source email subject and body
- Skipping cumulative partial-fill option emails to avoid phantom duplicates
- Correct expired-option accounting when some contracts were already exited
- Strategy Lab schema plus strategy/version API, stable source fingerprints, one-champion enforcement, run-backed version locking, hash-bound TradingView CSV preview/import, versioned deterministic run metrics, lightweight run/trade read endpoints, and the Stage 4 frontend workflow
- Stage 4 reused the existing `strategy_*` schema and Alembic revision `f1a2b3c4d5e6`; it introduced no schema migration

If tests or older docs disagree with one of the above, trust the working tree and inspect the diff before changing behavior.

## Commands

Backend:

```bash
cd backend
pip install -e .
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Use port `8080` only when `8000` is occupied. If you do, keep `NEXT_PUBLIC_API_URL`, `BACKEND_PUBLIC_URL`, and `FRONTEND_PUBLIC_URL` consistent with the actual frontend/backend ports and public callback URLs.

Repo-specific local dev note:

- Backend config now loads `.env` before DB init from `backend/.env` first, then repo-root `.env`; exported env vars still win. This matters for `DATABASE_URL`, autostart flags, API keys, and OAuth/public URL config.
- `frontend/lib/api.ts` defaults to `http://localhost:8080` when `NEXT_PUBLIC_API_URL` is unset.
- `startdev.ps1` intentionally launches the backend on `8080` and points the frontend there.
- `startdev.sh` is the macOS/Linux equivalent; it also assumes backend config comes from `.env` instead of exporting `DATABASE_URL` inline.
- `backend/mcp_server.py` defaults to `http://localhost:8000`; set `TRADE_JOURNAL_API` if you want Claude Desktop/MCP tools to hit a backend running on `8080`.

Frontend:

```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

PowerShell:

```powershell
$env:NEXT_PUBLIC_API_URL="http://localhost:8000"
npm run dev
```

Tests:

```bash
cd backend
pytest
```

Known environment note:

- Backend test collection currently needs `httpx` available because `fastapi.testclient` depends on it.
- The checked-in backend venv may not have `pytest`; use `python -m compileall app scripts` and targeted `TestClient` smoke checks when pytest is unavailable.
- `npm run lint` may still fail because the frontend is on Next 16 while `frontend/package.json` still uses `next lint`.
- `npm run build` may fail in network-restricted environments because `next/font` fetches Google Fonts.

Durable local jobs:

```bash
cd backend
python -m app.jobs.run --type polygon_enrich --range all
python -m app.jobs.run --type alpaca_enrich --range all --force
python -m app.jobs.run --type trade_path --range all
python -m app.jobs.run --type webull_listener --accounts WEBULL_ACCOUNT_ID
```

SQLite-to-Postgres/Neon migration:

```bash
cd backend
DATABASE_URL="postgresql+psycopg://USER:PASSWORD@HOST/dbname?sslmode=require" alembic upgrade head
python scripts/migrate_sqlite_to_postgres.py --target "$DATABASE_URL"
```

## What To Check First When Something Looks Wrong

- PnL mismatch: inspect `reconstructor.py`, then fill ordering, then account identity
- Import mismatch: inspect `email_parser.py`, `gmail_poller.py`, and `fills.py`
- Gmail OAuth mismatch: inspect `auth.py`, `gmail_poller.py`, Google redirect URIs, `BACKEND_PUBLIC_URL`, and `FRONTEND_PUBLIC_URL`
- Manual fill issue: inspect `ManualFillForm.tsx`, `frontend/lib/api.ts`, and `backend/app/routers/fills.py`
- Dashboard numbers vs broker numbers: inspect reconciliation scripts and generated reports, not just `/stats`
- Quote/dashboard mark issue: inspect `backend/app/engine/quotes.py`, `backend/app/routers/quotes.py`, and dashboard consumers before changing table math
- Enrichment job issue: inspect `backend/app/engine/jobs.py`, `job_run`, and the relevant enricher before changing UI polling
- Missing Alpaca daily indicators on recent trades: inspect `backend/app/engine/alpaca.py` daily cache coverage and the ticker's `backend/data/alpaca_cache/stocks/1Day/<feed>/` file
- Sync Center issue: inspect `backend/app/routers/sync.py`, `job_run`, and `frontend/components/DashboardActions.tsx`
- Webull issue: inspect `backend/app/engine/webull*.py`, `backend/app/routers/webull.py`, and `backend/app/engine/webull_proto/NOTICE`
- AI review issue: inspect `backend/app/ai/reviewer.py`, `backend/app/ai/daily_reviewer.py`, and nullable enrichment/path fields before changing prompts
- MCP/Claude Desktop issue: inspect `backend/mcp_server.py`, the bulk `/trades/*` and `/market-context/*` routes, `backend/data/mcp_log/*.jsonl`, and whether the backend is reachable on `localhost:8000`
- Strategy Lab definition/version issue: inspect `backend/app/engine/strategy_lab.py`, `backend/app/routers/strategy_lab.py`, and the `strategy_*` tables; do not route simulated data through FIFO reconstruction
- Strategy Lab CSV import issue: inspect the TradingView parser, `backend/app/routers/strategy_lab.py`, the preview warnings/header mapping, and the explicit source timezone before changing imported values
- Strategy Lab metrics issue: inspect `backend/app/engine/strategy_metrics.py`, the persisted coverage JSON, and the run's source timezone; never present partial P&L as a complete accounting curve or total

## Reconciliation Notes

- Reports are written to `backend/reports/`
- The repo already contains date-stamped reconciliation reports
- CSV comparison work is a core part of the project now, not side analysis
- Scratch files in `backend/compare_fills*.py` are investigative utilities, not durable product code

## Editing Guidance

- Prefer changing the shared table components instead of duplicating UI table logic
- Treat account normalization carefully; blank Roth `last4` values are part of an active cleanup path
- Any change to fill import or parsing can affect rebuilds, analytics, and reconciliation outputs
- Any change to enrichment affects local historical backfills, Cloud Run job readiness, and nullable UI fields
- For SQLite, keep long enrichment transactions short enough that `job_run` progress updates do not lock the DB
- For trade-path work, preserve the batched minute-bar prefetch and cache-only fallback; do not reintroduce one-network-call-per-trade/day behavior
- Incremental rebuilds go through `_rebuild_trades()` (fills.py), which reuses `trade_path_metrics` whose `inputs_fingerprint` still matches the rebuilt trade and drops dirty/orphaned rows for the path job to recompute; do not revert incremental rebuilds to a blanket `delete(TradePathMetrics)`. Only destructive resync (re-imports fills with new ids) clears all metrics.
- Daily review is not part of "Sync Everything" or Gmail push; it is generated only from the daily page or the standalone `daily_review` Sync Center job. Do not re-add it to the pipelines.
- Sync Center treats `webull_listener` as a persistent listener, not a blocking finite sync job or "sync running" banner source
- Sync pipeline and Gmail push intentionally do not wait for slow Polygon completion; check `/fills/enrich/status` separately before assuming market enrichment is fully done
- Preserve Strategy Lab version traceability: once a run exists, create a child version instead of editing its Pine source or assumptions in place
- When scope changes materially, update both `AGENTS.md` and `CLAUDE.md`
