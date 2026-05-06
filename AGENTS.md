# AGENTS.md

Read this first before making changes in this repo.

## Project In One Paragraph

Trade Journal is a local-only Robinhood trade history system built around fill ingestion, FIFO trade reconstruction, analytics, and reconciliation. The live repo already supports stocks and options, multiple account records, Gmail execution-email import, manual fill entry/edit, full trade rebuilds, and markdown reconciliation reporting.

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
- `backend/app/routers/fills.py`
- `backend/app/routers/stats.py`
- `backend/app/main.py`
- `backend/app/models.py`

Frontend:

- `frontend/lib/api.ts`
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

## Core Invariants

- `fill` is the source layer.
- `trade` and `tradefill` are derived layers.
- Quantity lives in `contracts` for both stocks and options.
- Stock quantities can be fractional.
- Option `price` is dollars per contract.
- Stock `price` is dollars per share.
- `raw_email_id` is the dedupe key for imported fills.
- Manual fills use `manual:` source IDs and are backed up to `backend/data/manual_fills.json`.

## Main User Flows

- Gmail import: `POST /fills/import`
- Manual fill create: `POST /fills`
- Manual fill edit: `PUT /fills/{id}`
- Rebuild everything from fills: `POST /rebuild`
- Full resync from Gmail plus manual-fill restore: `POST /fills/resync-all`
- View analytics and breakdowns: `GET /stats`
- Review per-trade history via trade detail and fill timeline pages

## Active Working Tree Features

These exist in the repo right now and may still be in flux:

- Quote endpoints and dashboard mark pricing via `yfinance`
- Reusable dashboard/trades table components
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

## What To Check First When Something Looks Wrong

- PnL mismatch: inspect `reconstructor.py`, then fill ordering, then account identity
- Import mismatch: inspect `email_parser.py`, `gmail_poller.py`, and `fills.py`
- Manual fill issue: inspect `ManualFillForm.tsx`, `frontend/lib/api.ts`, and `backend/app/routers/fills.py`
- Dashboard numbers vs broker numbers: inspect reconciliation scripts and generated reports, not just `/stats`

## Reconciliation Notes

- Reports are written to `backend/reports/`
- The repo already contains date-stamped reconciliation reports
- CSV comparison work is a core part of the project now, not side analysis
- Scratch files in `backend/compare_fills*.py` are investigative utilities, not durable product code

## Editing Guidance

- Prefer changing the shared table components instead of duplicating UI table logic
- Treat account normalization carefully; blank Roth `last4` values are part of an active cleanup path
- Any change to fill import or parsing can affect rebuilds, analytics, and reconciliation outputs
- When scope changes materially, update both `AGENTS.md` and `CLAUDE.md`
