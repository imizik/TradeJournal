# Trade Journal Context

## Product

Personal localhost trade journal and reconciliation tool for Robinhood trading history.

Current scope is broader than the original MVP notes:

- Stocks and options are both supported.
- Multiple account types exist in the data model.
- The current dataset is centered on Roth IRA `8267` and Individual `1113`.
- There is no auth and no multi-user model.
- The repo is optimized for local analysis, repair, and rebuild workflows.

## Stack

- Frontend: Next.js 16, React 19, App Router, Tailwind
- Backend: FastAPI, SQLModel, Alembic, SQLite
- Market data: `yfinance`, Polygon.io (free tier, API key in `backend/.env`)
- Email ingest: Gmail API
- Tests: `pytest`

Database file:

- `backend/data/trade_journal.db`

Manual fill backup file:

- `backend/data/manual_fills.json`

Generated reports:

- `backend/reports/`

## Core Data Model

The important mental model is:

- `fill` rows are the source records that came from Gmail or manual entry.
- `trade` and `tradefill` rows are derived from the full fill history through FIFO reconstruction.
- Rebuilding trades is normal and expected.

Important field semantics:

- `contracts` is the quantity field for both options and stocks.
- Stock quantities may be fractional.
- Option `price` is premium per contract in dollars.
- Stock `price` is per share.
- `raw_email_id` is the dedupe key for imported fills and uses `manual:` prefixes for manual fills.

The app currently allows editing fills to correct history, then rebuilding derived trades from scratch. So the conceptual rule is still "fills drive truth", but correction currently happens by updating bad fills rather than only appending compensating rows.

## What Already Exists

### Backend

- SQLModel schema for accounts, fills, trades, tags, and trade-fill junctions
- Alembic migrations through `b7e3a9f2c841`
- FIFO reconstructor that handles:
  - options and stocks
  - scale-ins
  - partial exits
  - expired worthless options
  - separate account isolation
  - fractional stock shares
  - anomaly reporting for orphaned and over-closed exits
- Gmail poller using the Gmail API
- Robinhood email parser for:
  - option execution emails
  - stock execution emails
- FastAPI routes for:
  - `/health`
  - `/accounts`
  - `/fills`
  - `/trades`
  - `/stats`
  - `/rebuild`
- Manual fill create and edit flows
- Manual fill backup and restore logic
- Full resync flow that clears imported fills, restores manual fills, re-imports Gmail, and rebuilds trades
- Reconciliation and CSV comparison scripts under `backend/scripts/`

### Frontend

- Dashboard with summary cards
- Dashboard action bar for:
  - email sync
  - rebuild all
  - resync all
  - jump to manual fills
- Open positions view built from trade data plus fill timelines
- Recent closed trades table
- Trades page with filters and sortable table
- Trade detail page with:
  - trade summary
  - fill timeline
  - edit-fill links
  - placeholder AI review rendering
- Fills page with:
  - fill history
  - manual fill form
  - edit-fill links
- Fill edit page
- Analytics page with ticker, time-bucket, tag, and behavioral-flag breakdowns

## Active Working Tree Changes

These are present in the repo right now but are not all committed yet:

- Quote support is being added:
  - `backend/app/engine/quotes.py`
  - `backend/app/routers/quotes.py`
  - dashboard pricing of open positions
- Open positions and closed trades table logic has been extracted into reusable components:
  - `frontend/components/DashboardTables.tsx`
  - `frontend/components/TradesTable.tsx`
- Roth account normalization is being tightened so blank-last4 Roth fills are merged into canonical Roth `8267` on startup
- Partial-fill Robinhood option emails are being intentionally skipped to avoid cumulative duplicate fills
- Expired options with partial exits now preserve realized FIFO PnL on the exited portion and only write off the remaining open lots
- AI trade review is wired: `POST /trades/{id}/review` calls `backend/app/ai/reviewer.py` (Claude claude-sonnet-4-6), writes structured JSON to `trade.ai_review`, rendered in trade detail page with Generate/Regenerate button
- Fill enrichment pipeline is live: `backend/app/engine/enricher.py` fetches Polygon data and computes Black-Scholes greeks. New fill columns: `underlying_price_at_fill`, `vwap_at_fill`, `iv_at_fill`, `delta_at_fill`, `gamma_at_fill`, `theta_at_fill`, `vega_at_fill`, `sma_20_at_fill`, `sma_50_at_fill`, `ema_9_at_fill`, `ema_20_at_fill`, `ema_9h_at_fill`, `rsi_14_at_fill`, `macd_at_fill`, `macd_signal_at_fill`. Polygon responses cached to `backend/data/polygon_cache/`. Backfill script: `backend/scripts/backfill_greeks.py`. Auto-enrichment runs after each Gmail import. API key in `backend/.env` as `POLYGON_API_KEY`.
- **Frontend UI for enriched fill data is NOT YET BUILT.** The backend returns all fields; the frontend needs to display them in: trade detail fill timeline, fill detail/edit page, and fills list table.

If behavior looks inconsistent between tests and code, check whether the file is part of this active working tree set before assuming the committed history is wrong.

## Key Files

Highest-leverage backend files:

- `backend/app/engine/reconstructor.py`
- `backend/app/engine/email_parser.py`
- `backend/app/engine/gmail_poller.py`
- `backend/app/engine/enricher.py`
- `backend/app/ai/reviewer.py`
- `backend/app/routers/fills.py`
- `backend/app/routers/trades.py`
- `backend/app/routers/stats.py`
- `backend/app/main.py`
- `backend/app/models.py`

Highest-leverage frontend files:

- `frontend/app/page.tsx`
- `frontend/app/trades/page.tsx`
- `frontend/app/trades/[id]/page.tsx`
- `frontend/app/fills/page.tsx`
- `frontend/app/fills/[id]/page.tsx`
- `frontend/components/ManualFillForm.tsx`
- `frontend/lib/api.ts`

Important analysis scripts:

- `backend/scripts/generate_reconciliation_report.py`
- `backend/scripts/csv_reconstruct.py`
- `backend/scripts/find_phantoms.py`
- `backend/scripts/rebuild_trades.py`

Scratch comparison scripts also exist in `backend/compare_fills*.py`. Treat them as ad hoc analysis utilities, not stable app code.

## API Summary

Stable current routes:

- `GET /health`
- `GET /accounts`
- `GET /fills`
- `POST /fills`
- `POST /fills/import`
- `POST /fills/resync-all`
- `GET /fills/{id}`
- `PUT /fills/{id}`
- `GET /trades`
- `GET /trades/{id}`
- `GET /trades/{id}/fills`
- `POST /trades/{id}/tags`
- `POST /trades/{id}/review`
- `GET /stats`
- `POST /rebuild`

Working-tree routes being added:

- `GET /quotes`
- `POST /quotes/positions`

## Run Locally

Backend:

```bash
cd backend
pip install -e .
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

## Testing

Backend tests:

```bash
cd backend
pytest
```

Current note:

- `fastapi.testclient` requires `httpx`, and local test collection currently fails if `httpx` is not installed in the Python environment.

## Reconciliation Workflow

This repo now includes a real reconciliation workflow, not just journaling UI.

- Use `backend/scripts/generate_reconciliation_report.py` to produce markdown reports in `backend/reports/`
- Use `backend/scripts/csv_reconstruct.py` to compare DB-derived FIFO results against Robinhood CSV ground truth
- Use `backend/scripts/find_phantoms.py` when investigating duplicate cumulative partial-fill emails

The report work is centered on understanding:

- differences between dashboard realized PnL and broker-level reality
- missing basis from orphaned stock sells
- Roth account consolidation issues
- CSV-vs-DB mismatch families such as symbol drift, date drift, quantity mismatch, and rounding

## Guardrails For Future Work

- Start with the reconstructor and fill history whenever PnL looks wrong.
- Do not assume the app is options-only or Roth-only anymore.
- Treat quotes and reconciliation tooling as first-class parts of the project now.
- Be careful with account identity; Roth fills with blank `last4` are part of the active cleanup story.
- If a change touches fill import or email parsing, check the downstream impact on rebuilds and reconciliation scripts.
- If a change touches the UI tables, prefer reusing the extracted table components instead of duplicating table logic.
- Fill enrichment fields are all nullable — always guard with null checks before displaying or passing to AI.
- Option `price` in the DB is total premium per contract (dollars). Divide by 100 for per-share price before passing to Black-Scholes.
- Backend port is 8080 (Windows zombie socket on 8000).
- Polygon cache lives at `backend/data/polygon_cache/`. Delete a cache file to force a re-fetch for that ticker/date.
- Update `CLAUDE.md` and `AGENTS.md` together when project scope changes materially.
