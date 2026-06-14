# Trade Journal Context

## Product

Personal local-first trade journal and reconciliation tool for Robinhood trading history.

Current scope is broader than the original MVP notes:

- Stocks and options are both supported.
- Multiple account types exist in the data model.
- The current dataset is centered on Roth IRA `8267` and Individual `1113`.
- There is no auth and no multi-user model.
- The repo is optimized for local analysis, repair, rebuild workflows, and eventual low-cost deployment.

## Agent Operating Style

Default behavior for coding agents in this repo:

- Read only what matters for the task; use `CLAUDE.md`/`AGENTS.md` to orient quickly.
- Batch searches, file reads, and cheap checks instead of issuing many tiny commands.
- Avoid repeated `git status`, broad tree walks, or unrelated spelunking.
- Find root cause first, then make the smallest safe fix directly.
- Do not ask obvious follow-ups when the requested fix is local and low-risk.
- Keep progress narration minimal; do not explain routine shell/file operations.
- Prefer cheap targeted validation over full test suites unless the blast radius requires more.
- Avoid unrelated refactors, formatting churn, and duplicated UI/table logic.
- Final summaries should be brief: changed files/behavior, validation run, remaining risk.

Highest-risk areas require extra care: PnL math, FIFO reconstruction, Gmail/email parsing, fill dedupe, account identity, reconciliation outputs, nullable enrichment fields, and frontend data-fetch patterns that can create N+1 calls.

## Stack

- Frontend: Next.js 16, React 19, App Router, Tailwind
- Backend: FastAPI, SQLModel, Alembic, SQLite by default, Postgres via `DATABASE_URL`
- Market data: `yfinance`, Polygon.io, Alpaca
- Email ingest: Gmail API
- Tests: `pytest`

Database file:

- `backend/data/trade_journal.db`

Cloud/deploy-ready DB config:

- `DATABASE_URL` overrides the local SQLite default.
- Neon/Postgres URLs should use the `postgresql+psycopg://...` SQLAlchemy driver form.

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

Durable background work:

- `job_run` records durable state for enrichment/path jobs.
- API status endpoints should read `job_run`, not process-local dictionaries.
- Local routes may still start convenience background threads, but the execution path must also work through `python -m app.jobs.run`.
- Cloud Run Jobs can use the same container/image and call the CLI entrypoint later.

## What Already Exists

### Backend

- SQLModel schema for accounts, fills, trades, tags, and trade-fill junctions
- Alembic migrations through `9d1e2f3a4b5c`
- FIFO reconstructor that handles:
  - options and stocks
  - scale-ins
  - partial exits
  - expired worthless options
  - separate account isolation
  - fractional stock shares
  - anomaly reporting for orphaned and over-closed exits
- Gmail poller using the Gmail API
- In-app Gmail OAuth flow:
  - `GET /auth/gmail/start` returns a Google auth URL
  - `GET /auth/gmail/callback` saves `backend/token.json`
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
- Durable job runner for Polygon enrichment, Alpaca fill context, and trade path metrics:
  - `backend/app/engine/jobs.py`
  - `backend/app/jobs/run.py`
- SQLite-to-Postgres copy script:
  - `backend/scripts/migrate_sqlite_to_postgres.py`
- Reconciliation and CSV comparison scripts under `backend/scripts/`

### Frontend

- Dashboard with summary cards
- Dashboard action bar for:
  - email sync
  - in-browser Gmail authorization when needed
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

- Market report ("packet") + MCP layer for Claude chat:
  - `backend/app/engine/packets.py` builds deterministic premarket/postmarket market reports (indexes detail with VWAP/ORB/premarket/AH, sector rotation, macro gauges incl. ^VIX/^TNX via yfinance, bucketed high-beta universe with `rs_vs_spy`, leaders/laggards, raw Alpaca news).
  - Symbol universe is hand-editable in `backend/data/universe.json` (bucketed execution watchlist — not the market).
  - `backend/app/engine/news.py` wraps Alpaca `/v1beta1/news`; no relevance filtering in Python — Claude triages headlines.
  - `backend/mcp_server.py` is a stdio FastMCP server for Claude Desktop with read-only tools (`get_market_report`, `get_news`, `get_trades`, `get_stats`); thin httpx adapter over `localhost:8000`, holds no API keys, logs calls to `backend/data/mcp_log/*.jsonl`.
  - `backend/prompts/market_report.md` is the Claude-side analysis prompt (regime rules, 13-section output) — judgment lives there, not in backend code.
  - Live "today" market data must use `fetch_snapshots`/`fetch_minute_bars_live` (never cached); the persistent minute cache never expires and must not be written with partial intraday data.
- Quote support is being added:
  - `backend/app/engine/quotes.py`
  - `backend/app/routers/quotes.py`
  - dashboard pricing of open positions
- Gmail OAuth no longer depends on copying a terminal URL. The frontend can call `/auth/gmail/start`, redirect to Google, and return through `/auth/gmail/callback`.
- Open positions and closed trades table logic has been extracted into reusable components:
  - `frontend/components/DashboardTables.tsx`
  - `frontend/components/TradesTable.tsx`
- Roth account normalization is being tightened so blank-last4 Roth fills are merged into canonical Roth `8267` on startup
- Partial-fill Robinhood option emails are being intentionally skipped to avoid cumulative duplicate fills
- Expired options with partial exits now preserve realized FIFO PnL on the exited portion and only write off the remaining open lots
- AI trade review is wired: `POST /trades/{id}/review` calls `backend/app/ai/reviewer.py` (Claude claude-sonnet-4-6), writes structured JSON to `trade.ai_review`, rendered in trade detail page with Generate/Regenerate button
- Fill enrichment pipeline is live:
  - `backend/app/engine/enricher.py` fetches Polygon data and computes Black-Scholes greeks.
  - `backend/app/engine/alpaca_enricher.py` computes Alpaca-derived fill market context in `fill_market_context`.
  - `backend/app/engine/trade_path.py` computes trade-level path metrics in `trade_path_metrics`.
  - `backend/app/engine/jobs.py` wraps long enrichment/path work in durable `job_run` rows.
  - Polygon responses cache to `backend/data/polygon_cache/`.
  - Alpaca bars cache to `backend/data/alpaca_cache/`.
  - Alpaca daily cache validity must cover the requested date range, not just be young by file age.
  - Local SQLite enrichers commit incrementally to avoid locking `job_run` progress updates.
- Trade detail UI displays Alpaca context and audit/path panels. Enrichment fields remain nullable and should display as missing when unavailable.

If behavior looks inconsistent between tests and code, check whether the file is part of this active working tree set before assuming the committed history is wrong.

## Key Files

Highest-leverage backend files:

- `backend/app/engine/reconstructor.py`
- `backend/app/engine/email_parser.py`
- `backend/app/engine/gmail_poller.py`
- `backend/app/engine/enricher.py`
- `backend/app/engine/alpaca.py`
- `backend/app/engine/alpaca_enricher.py`
- `backend/app/engine/jobs.py`
- `backend/app/engine/trade_path.py`
- `backend/app/ai/reviewer.py`
- `backend/app/routers/auth.py`
- `backend/app/routers/fills.py`
- `backend/app/routers/trades.py`
- `backend/app/routers/stats.py`
- `backend/app/routers/market_context.py`
- `backend/app/main.py`
- `backend/app/models.py`

Highest-leverage frontend files:

- `frontend/app/page.tsx`
- `frontend/app/trades/page.tsx`
- `frontend/app/trades/[id]/page.tsx`
- `frontend/app/fills/page.tsx`
- `frontend/app/fills/[id]/page.tsx`
- `frontend/components/DashboardActions.tsx`
- `frontend/components/DashboardTables.tsx`
- `frontend/components/TradesTable.tsx`
- `frontend/components/ManualFillForm.tsx`
- `frontend/lib/api.ts`

Important analysis scripts:

- `backend/scripts/generate_reconciliation_report.py`
- `backend/scripts/csv_reconstruct.py`
- `backend/scripts/find_phantoms.py`
- `backend/scripts/rebuild_trades.py`
- `backend/scripts/migrate_sqlite_to_postgres.py`

Scratch comparison scripts also exist in `backend/compare_fills*.py`. Treat them as ad hoc analysis utilities, not stable app code.

## API Summary

Stable current routes:

- `GET /health`
- `GET /auth/gmail/start`
- `GET /auth/gmail/callback`
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
- `GET /quotes`
- `POST /quotes/positions`
- `GET /packets/report?type=premarket|postmarket`
- `GET /packets/news`
- `POST /fills/enrich`
- `GET /fills/enrich/status`
- `POST /market-context/enrich`
- `GET /market-context/enrich/status`
- `GET /market-context/coverage`
- `GET /market-context/fill/{fill_id}`
- `GET /market-context/fills/bulk`
- `GET /market-context/trade/{trade_id}`
- `POST /market-context/trade-path/compute`
- `GET /market-context/trade-path/status`
- `GET /market-context/audit/{trade_id}`

## Run Locally

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

Durable local enrichment/path jobs:

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

## Testing

Backend tests:

```bash
cd backend
pytest
```

Current note:

- `fastapi.testclient` requires `httpx`, and local test collection currently fails if `httpx` is not installed in the Python environment.
- The checked-in backend venv may not have `pytest`; when it is unavailable, run `python -m compileall app scripts` plus targeted `TestClient` smoke checks.
- Next 16 no longer supports `next lint` the same way; `npm run lint` may fail until the script is updated.
- `npm run build` may fail in a network-restricted environment because `next/font` tries to fetch Google Fonts.

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
- Avoid frontend N+1 calls; batch data loading or extend shared API responses when practical.
- Fill enrichment fields are all nullable — always guard with null checks before displaying or passing to AI.
- Alpaca context is fill-level. Trade path metrics are separate and require the Path Metrics job.
- The dashboard Alpaca "All history" control should send `range=all&force=true`; `force` alone only reprocesses the currently selected range.
- If recent trades have underlying/VWAP but missing RSI/EMA/MACD/ATR, inspect stale Alpaca daily cache coverage before changing indicator math.
- Option `price` in the DB is total premium per contract (dollars). Divide by 100 for per-share price before passing to Black-Scholes.
- Backend port is usually 8000. Use 8080 only when 8000 is occupied, and keep OAuth/API URLs in sync.
- Polygon cache lives at `backend/data/polygon_cache/`. Delete a cache file to force a re-fetch for that ticker/date.
- Alpaca cache lives at `backend/data/alpaca_cache/`. Daily cache files must be refreshed when they do not cover the requested date range.
- For SQLite, avoid long write transactions in historical jobs; progress updates to `job_run` can otherwise hit `database is locked`.
- Update `CLAUDE.md` and `AGENTS.md` together when project scope changes materially.
