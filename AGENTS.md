# AGENTS.md

Read this first before making changes in this repo.

## Project In One Paragraph

Trade Journal is a local-first Robinhood trade history system built around fill ingestion, FIFO trade reconstruction, analytics, enrichment, and reconciliation. The live repo already supports stocks and options, multiple account records, Gmail execution-email import, manual fill entry/edit, full trade rebuilds, durable enrichment jobs, and markdown reconciliation reporting.

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

## Highest-Leverage Files

Backend:

- `backend/app/engine/reconstructor.py`
- `backend/app/engine/email_parser.py`
- `backend/app/engine/gmail_poller.py`
- `backend/app/engine/enricher.py`
- `backend/app/engine/alpaca.py`
- `backend/app/engine/alpaca_enricher.py`
- `backend/app/engine/jobs.py`
- `backend/app/routers/auth.py`
- `backend/app/routers/fills.py`
- `backend/app/routers/trades.py`
- `backend/app/routers/stats.py`
- `backend/app/routers/market_context.py`
- `backend/app/main.py`
- `backend/app/models.py`

Frontend:

- `frontend/lib/api.ts`
- `frontend/components/DashboardActions.tsx`
- `frontend/components/DashboardTables.tsx`
- `frontend/components/TradesTable.tsx`
- `frontend/components/ManualFillForm.tsx`
- `frontend/app/page.tsx`
- `frontend/app/trades/page.tsx`
- `frontend/app/trades/[id]/page.tsx`
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
- `job_run` rows are durable status records for import/enrichment/path jobs; do not rely on process-local progress state.
- Alpaca context is fill-level context in `fill_market_context`; trade-level path metrics are separate rows in `trade_path_metrics`.

## Main User Flows

- Gmail import: `POST /fills/import`
- Gmail OAuth start/callback: `GET /auth/gmail/start`, `GET /auth/gmail/callback`
- Manual fill create: `POST /fills`
- Manual fill edit: `PUT /fills/{id}`
- Rebuild everything from fills: `POST /rebuild`
- Full resync from Gmail plus manual-fill restore: `POST /fills/resync-all`
- View analytics and breakdowns: `GET /stats`
- Review per-trade history via trade detail and fill timeline pages
- Polygon enrichment: `POST /fills/enrich`
- Alpaca fill context enrichment: `POST /market-context/enrich`
- Trade path metrics: `POST /market-context/trade-path/compute`
- Enrichment coverage: `GET /market-context/coverage`

## Active Working Tree Features

These exist in the repo right now and may still be in flux:

- Quote endpoints and dashboard mark pricing via `yfinance`
- Reusable dashboard/trades table components
- Gmail OAuth can be started from the app instead of copying a terminal URL
- Fill enrichment fields and durable job-backed enrichment status/actions
- Configurable `DATABASE_URL`; SQLite remains the local default, Postgres/Neon is supported for migration/deploy
- Durable job runner CLI for historical enrichment and future Cloud Run Jobs
- Alpaca context and trade-path metrics with cache-aware daily/minute bar handling
- Startup merge of blank-last4 Roth data into canonical `8267`
- New fill columns for source email subject and body
- Skipping cumulative partial-fill option emails to avoid phantom duplicates
- Correct expired-option accounting when some contracts were already exited

If tests or older docs disagree with one of the above, trust the working tree and inspect the diff before changing behavior.

## Commands

Backend:

```bash
cd backend
pip install -e .
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Use port `8080` only when `8000` is occupied, and set `NEXT_PUBLIC_API_URL`/`BACKEND_PUBLIC_URL` consistently if changing ports.

Frontend:

```bash
cd frontend
npm install
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

Durable local jobs:

```bash
cd backend
python -m app.jobs.run --type polygon_enrich --range all
python -m app.jobs.run --type alpaca_enrich --range all --force
python -m app.jobs.run --type trade_path --range all
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
- Gmail OAuth mismatch: inspect `auth.py`, `gmail_poller.py`, Google redirect URIs, and `BACKEND_PUBLIC_URL`
- Manual fill issue: inspect `ManualFillForm.tsx`, `frontend/lib/api.ts`, and `backend/app/routers/fills.py`
- Dashboard numbers vs broker numbers: inspect reconciliation scripts and generated reports, not just `/stats`
- Enrichment job issue: inspect `backend/app/engine/jobs.py`, `job_run`, and the relevant enricher before changing UI polling
- Missing Alpaca daily indicators on recent trades: inspect `backend/app/engine/alpaca.py` daily cache coverage and the ticker's `backend/data/alpaca_cache/stocks/1Day/<feed>/` file

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
- When scope changes materially, update both `AGENTS.md` and `CLAUDE.md`
