# Trade Journal Context

## Product

Personal local-first trade journal and reconciliation tool for Robinhood trading history.

Current scope is broader than the original MVP notes:

- Stocks and options are both supported.
- Multiple account types exist in the data model.
- The current dataset is centered on Roth IRA `8267` and Individual `1113`.
- There is no auth and no multi-user model.
- The repo is optimized for local analysis, repair, rebuild workflows, and eventual low-cost deployment.
- Current scope also includes Webull read/listen/import plumbing, Gmail Pub/Sub push ingest, a Sync Center, AI trade/day review, market packets for Claude Desktop, live quotes, Alpaca fill context, and trade path metrics.
- Strategy Lab has an end-to-end Stage 4 workflow for version-controlled Pine research: strategy/version creation and history, stored Pine source and assumptions, hash-bound TradingView CSV preview/import, deterministic persisted metrics, and run pages with curves and filterable simulated trades. It is separate from journal fills/trades, and every import requires an explicit source timezone. Run comparison, deterministic findings, experiment workflows, and Pine diffs remain Stage 5 work.
- The TradingView live-signal loop has its local backend path through Step 4:
  a frozen network/DB-free v1 parser, isolated `tradingview_alert` table,
  guarded migration, token-protected webhook-only ingress, private light/full
  reads, and one database-backed fenced Alpaca/scalper worker. Pine code and
  the Signals page remain future work.

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

Strategy Lab is a separate normalized domain: `strategy_definition` -> `strategy_version` -> `strategy_run` -> `strategy_run_trade`, with one-to-one `strategy_run_metrics` and lightweight `strategy_experiment` records. Simulated rows never enter `fill`, `trade`, or `tradefill`. Result-producing fields on a version become immutable after its first run; fork the version to test a change. TradingView import is a non-persistent preview followed by a commit that re-uploads the same bytes and verifies the returned source, version, and preview fingerprints. Source timestamps require an explicit IANA timezone and are normalized to UTC. Run metrics use a versioned pure-Decimal calculator and persist explicit source-field coverage; accounting curves remain unavailable when P&L or exit chronology is incomplete.

TradingView live alerts are a third isolated domain. Wire `v` is immutable and
separate from Pine `indicator_version`. `parse_alert_v1()` and its golden
fixtures remain frozen while v1 data exists; changed fields, meaning,
canonical identity, timestamp semantics, or acceptance rules require a new
wire version. Future database changes use expand → version-pinned/idempotent
backfill → constraint migrations and never reinterpret raw payloads with a
generic current parser. Canonical `alert_id` is the only idempotency key:
same semantic hash means duplicate even when raw bytes differ; a different
semantic hash is a collision that preserves the first evidence.

The public ingress (`app.tradingview_ingress`) and private API (`app.main`) are
separate applications. Expose only ingress port `8090`. Analysis claims commit
before market calls and use `analysis_attempts` as a fencing token. The
database is a durable local queue, not a Cloud scale-to-zero task dispatcher.

Durable background work:

- `job_run` records durable state for enrichment/path jobs.
- API status endpoints should read `job_run`, not process-local dictionaries.
- Local routes may still start convenience background threads, but the execution path must also work through `python -m app.jobs.run`.
- Cloud Run Jobs can use the same container/image and call the CLI entrypoint later.

## What Already Exists

### Backend

- SQLModel schema for accounts, fills, trades, tags, and trade-fill junctions
- Alembic migrations through `c7d8e9f0a1b2`
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
  - `GET /auth/gmail/start/browser` redirects straight to Google from the backend
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
- Sync Center routes for job summaries, history, pipeline runs, and advanced rebuild/resync:
  - `backend/app/routers/sync.py`
- Gmail Pub/Sub push watch/webhook:
  - `backend/app/routers/gmail_push.py`
- Webull read/listen/import plumbing:
  - `backend/app/engine/webull.py`
  - `backend/app/engine/webull_client.py`
  - `backend/app/engine/webull_events.py`
  - `backend/app/engine/webull_listener.py`
  - `backend/app/routers/webull.py`
- AI review:
  - `backend/app/ai/reviewer.py`
  - `backend/app/ai/daily_reviewer.py`
- SQLite-to-Postgres copy script:
  - `backend/scripts/migrate_sqlite_to_postgres.py`
- Reconciliation and CSV comparison scripts under `backend/scripts/`
- TradingView live-alert backend through Step 4:
  - `backend/app/engine/tradingview.py`
  - `backend/app/engine/tradingview_alerts.py`
  - `backend/app/engine/tradingview_analysis.py`
  - `backend/app/tradingview_ingress.py`
  - `backend/app/tradingview_database.py`
  - `backend/app/routers/tradingview_webhook.py`
  - `backend/app/routers/tradingview_alerts.py`
  - `TradingViewAlert` in `backend/app/models.py`
  - Alembic revision `2e6f9a1b4c7d`
  - `backend/tests/test_tradingview.py`
  - `backend/tests/test_tradingview_alert_model.py`
  - `backend/tests/test_tradingview_alert_migration.py`
  - `backend/tests/test_tradingview_alert_persistence.py`
  - `backend/tests/test_tradingview_analysis.py`
  - `backend/tests/test_tradingview_routes.py`
  - `docs/tradingview-webhook-contract-v1.md`
  - Pine indicator and frontend Signals page are not implemented yet
- Strategy Lab definition/version lifecycle and API:
  - `backend/app/engine/strategy_lab.py`
  - `backend/app/routers/strategy_lab.py`
  - normalized `strategy_*` tables added by Alembic revision `f1a2b3c4d5e6`
  - stable source fingerprints across database Decimal round-trips
  - transactional one-champion transitions and run-backed version locking
  - TradingView CSV preview at `POST /strategy-lab/imports/preview`
  - hash-verified run commit at `POST /strategy-lab/runs/import`
  - paginated/filterable run reads at `GET /strategy-lab/runs`, `GET /strategy-lab/runs/{run_id}`, and `GET /strategy-lab/runs/{run_id}/trades`
  - deterministic metrics recalc at `POST /strategy-lab/runs/{run_id}/metrics/recalculate`
  - stored metrics read at `GET /strategy-lab/runs/{run_id}/metrics`
  - optional flat Pine metadata using the export-visible `sl1|key=value|...` convention documented in `docs/strategy-lab-pine-metadata.md`
  - imported simulations remain isolated from journal fills and FIFO-derived trades
  - Stage 4 reused Alembic revision `f1a2b3c4d5e6` and added no schema migration; comparison, findings, experiment workflows, and Pine diffs remain Stage 5 work

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
  - Generate/Regenerate AI review
  - Alpaca context, path metrics, and audit panels
- Fills page with:
  - fill history
  - manual fill form
  - edit-fill links
- Fill edit page
- Analytics page with ticker, time-bucket, tag, and behavioral-flag breakdowns
- Daily review index/detail pages
- Strategy Lab pages for strategy/version creation and history, exact Pine source and assumptions, two-step TradingView CSV preview/commit, and run detail with coverage-aware metrics, equity/drawdown curves, and paginated/filterable simulated trades

## Current Capabilities And In-Flux Areas

These are present in the repo right now and may still be in flux:

- Market report ("packet") + MCP layer for Claude chat:
  - `backend/app/engine/packets.py` builds deterministic premarket/postmarket market reports (indexes detail with VWAP/ORB/premarket/AH, sector rotation, macro gauges incl. ^VIX/^TNX via yfinance, bucketed high-beta universe with `rs_vs_spy`, leaders/laggards, raw Alpaca news).
  - Symbol universe is hand-editable in `backend/data/universe.json` (bucketed execution watchlist, not the market).
  - `backend/app/engine/news.py` wraps Alpaca `/v1beta1/news`; no relevance filtering in Python, so Claude triages headlines.
  - `backend/mcp_server.py` is a stdio FastMCP server for Claude Desktop with read-only tools for market packets plus journal analysis (`get_market_report`, `get_news`, `analyze_ticker`, `analyze_scalp`, `get_trades`, `get_stats`, `get_trade_detail`, `get_coverage`, `get_trade_audit`, `get_trade_path_metrics`, `get_fill_contexts`); thin httpx adapter over `localhost:8000`, holds no API keys, logs calls to `backend/data/mcp_log/*.jsonl`.
  - `backend/prompts/market_report.md` is the Claude-side analysis prompt (regime rules, 13-section output); judgment lives there, not in backend code.
  - Live "today" market data must use `fetch_snapshots`/`fetch_minute_bars_live` (never cached); the persistent minute cache never expires and must not be written with partial intraday data.
- Scalper Analyzer (read-only decision support, never places trades):
  - `backend/app/engine/scalper.py` gathers a live packet (snapshot, live minute bars, intraday VWAP/OR/EMA/RVOL, daily indicators, SPY/QQQ context, news, optional Alpaca option snapshot with greeks/spread) and scores it deterministically — verdict (`no_trade`/`wait`/`long_scalp`/`short_scalp`), confidence, bias, setup/liquidity/risk scores, level-based trigger/invalidation/targets, reasons, missing-data caveats.
  - `score_scalp()` is a pure function over the packet (tested in `backend/tests/test_scalper.py` without network); `build_scalp_analysis()` is the gathering layer. Hard rules: closed market or stale data ⇒ wait/no_trade; option spread >10% of mid ⇒ reject; inside VWAP/OR band on weak RVOL ⇒ chop; extra strict in the first 5–15 minutes.
  - Exposed at `GET /packets/scalp` and via the `analyze_scalp` MCP tool; option snapshots come from `fetch_option_snapshots`/`fetch_option_chain_snapshots` in `alpaca.py` (`ALPACA_OPTIONS_FEED`, default `indicative`, never cached).
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
- AI trade review is wired: `POST /trades/{id}/review` calls `backend/app/ai/reviewer.py`, defaults to `ANTHROPIC_MODEL` or `claude-opus-4-7`, writes structured JSON to `trade.ai_review`, and renders in trade detail with a Generate/Regenerate button.
- Daily AI review is wired through `/daily-review`, `backend/app/ai/daily_reviewer.py`, and the `dailyreview` table.
- Sync Center is wired through `/sync/*` and dashboard controls. It queues finite `job_run` rows for Gmail sync, fill check, trade rebuild, enrichment, path metrics, daily review, full pipeline, and advanced rebuild/resync.
- The full Sync Everything pipeline stops after Gmail sync, fill check, rebuild, Polygon, Alpaca, and trade-path work. Daily review remains a standalone explicit action from the daily page or the `daily_review` Sync Center job.
- Gmail Pub/Sub push ingest is wired through `/gmail/watch`, `/gmail/watch/status`, and `/gmail/push`; push events queue `gmail_push` pipeline work.
- Webull support is wired for signed read endpoints, gRPC event listening, raw event persistence, and normalized fill ingest. No live trading endpoints are implemented.
- App startup may also auto-renew Gmail Pub/Sub watches (`GMAIL_WATCH_AUTOSTART`) and auto-start Webull listeners (`WEBULL_LISTENER_AUTOSTART` or `WEBULL_LISTENER_ACCOUNTS`) after orphaned jobs are cleaned up.
- Fill enrichment pipeline is live:
  - `backend/app/engine/enricher.py` fetches Polygon data and computes Black-Scholes greeks.
  - `backend/app/engine/alpaca_enricher.py` computes Alpaca-derived fill market context in `fill_market_context`.
  - `backend/app/engine/behavior.py` computes trader-state sequence metrics (entries/PnL/loss streak so far today, minutes since last exit, open-position count, re-entry-after-loss) from the journal's own history; written onto `fill_market_context` during Alpaca enrichment.
  - `backend/app/engine/trade_path.py` computes trade-level path metrics in `trade_path_metrics`, including ATR-normalized MFE/MAE multiples and first-order greeks PnL attribution for options (`attr_delta/gamma/theta/vega/residual_pnl`, `entry_iv`/`exit_iv`).
  - "At fill" daily indicators (both the Polygon fields on `fill` and the Alpaca fields on `fill_market_context`) intentionally use the last completed daily bar strictly BEFORE the fill date; the fill day's own daily value is computed on that day's close and would leak the future. Same for hourly EMA-9 (prior completed hour). Do not "fix" this back.
  - Polygon minute/hour bar keys use real America/New_York conversion (zoneinfo). Fills enriched before this fix during EST months have underlying/VWAP/greeks from one hour early; a forced re-enrich corrects them from cache.
  - `backend/app/engine/jobs.py` wraps long enrichment/path work in durable `job_run` rows.
  - Polygon responses cache to `backend/data/polygon_cache/`.
  - Alpaca bars cache to `backend/data/alpaca_cache/`.
  - Alpaca daily cache validity must cover the requested date range, not just be young by file age.
  - Enrichers/path metrics commit in batches (~10 groups / 25 trades) and `job_run` progress writes are throttled to ~2s via `_throttled_progress` in `jobs.py` — per-item commits/updates were a SQLite-era pattern that costs a network round trip each on hosted Postgres. SQLite stays safe because its write lock is only taken at commit.
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
- `backend/app/engine/quotes.py`
- `backend/app/engine/trade_path.py`
- `backend/app/engine/webull.py`
- `backend/app/engine/webull_client.py`
- `backend/app/engine/webull_events.py`
- `backend/app/engine/webull_listener.py`
- `backend/app/engine/packets.py`
- `backend/app/engine/scalper.py`
- `backend/app/engine/tradingview.py`
- `backend/app/engine/tradingview_alerts.py`
- `backend/app/engine/tradingview_analysis.py`
- `backend/app/tradingview_ingress.py`
- `backend/app/tradingview_database.py`
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
- `backend/app/routers/tradingview_webhook.py`
- `backend/app/routers/tradingview_alerts.py`
- `backend/app/main.py`
- `backend/app/models.py`

Highest-leverage frontend files:

- `frontend/app/page.tsx`
- `frontend/app/strategy-lab/`
- `frontend/components/strategy-lab/`
- `frontend/lib/strategy-lab/`
- `frontend/app/trades/page.tsx`
- `frontend/app/trades/[id]/page.tsx`
- `frontend/app/daily/page.tsx`
- `frontend/app/daily/[day]/page.tsx`
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
- `GET /auth/gmail/start/browser`
- `GET /auth/gmail/callback`
- `GET /accounts`
- `GET /fills`
- `POST /fills`
- `POST /fills/import`
- `POST /fills/resync-all`
- `GET /fills/{id}`
- `PUT /fills/{id}`
- `GET /trades`
- `GET /trades/fills/bulk`
- `GET /trades/{id}`
- `GET /trades/{id}/fills`
- `POST /trades/{id}/tags`
- `POST /trades/{id}/review`
- `GET /stats`
- `POST /rebuild`
- `GET /quotes`
- `POST /quotes/positions`
- `GET /packets/report?type=premarket|postmarket`
- `GET /packets/analyze?symbol=...`
- `GET /packets/scalp?symbol=...&direction=&instrument=&option_type=&expiration=&strike=&style=`
- `GET /packets/news`
- `POST /fills/enrich`
- `GET /fills/enrich/status`
- `POST /market-context/enrich`
- `GET /market-context/enrich/status`
- `GET /market-context/coverage`
- `GET /market-context/fill/{fill_id}`
- `GET /market-context/fills/bulk`
- `GET /market-context/trade/{trade_id}`
- `GET /market-context/trade-path/bulk`
- `POST /market-context/trade-path/compute`
- `GET /market-context/trade-path/status`
- `GET /market-context/audit/{trade_id}`
- `GET /daily-review`
- `GET /daily-review/{day}`
- `POST /daily-review`
- `GET /sync/summary`
- `GET /sync/jobs`
- `GET /sync/runs`
- `POST /sync/pipeline/run`
- `POST /sync/jobs/{job_type}/run`
- `POST /sync/advanced/rebuild-all`
- `POST /sync/advanced/resync-all`
- `POST /gmail/watch`
- `GET /gmail/watch/status`
- `POST /gmail/push`
- `GET /webull/health`
- `GET /webull/accounts`
- `GET /webull/orders/recent`
- `GET /webull/orders/{order_id}`
- `POST /webull/events/test-ingest`
- `POST /webull/events/start`
- `POST /webull/events/stop`
- `GET /webull/events/status`
- `GET /strategy-lab/strategies`
- `POST /strategy-lab/strategies`
- `GET /strategy-lab/strategies/{strategy_id}`
- `PATCH /strategy-lab/strategies/{strategy_id}`
- `POST /strategy-lab/strategies/{strategy_id}/versions`
- `GET /strategy-lab/versions/{version_id}`
- `PATCH /strategy-lab/versions/{version_id}`
- `POST /strategy-lab/versions/{version_id}/fork`
- `POST /strategy-lab/imports/preview`
- `POST /strategy-lab/runs/import`
- `GET /strategy-lab/runs`
- `GET /strategy-lab/runs/{run_id}`
- `GET /strategy-lab/runs/{run_id}/trades`
- `POST /strategy-lab/runs/{run_id}/metrics/recalculate`
- `GET /strategy-lab/runs/{run_id}/metrics`
- Private: `GET /tradingview/alerts`
- Private: `GET /tradingview/alerts/{alert_id}`
- Public ingress `:8090`: `POST /tradingview/webhook`

## Run Locally

Backend:

```bash
cd backend
pip install -e .
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Use port `8080` only when `8000` is occupied. If you do, keep `NEXT_PUBLIC_API_URL`, `BACKEND_PUBLIC_URL`, and `FRONTEND_PUBLIC_URL` consistent with the actual frontend/backend ports and public callback URLs.

Restricted TradingView ingress:

```bash
cd backend
uvicorn app.tradingview_ingress:app --reload --no-access-log \
  --host 127.0.0.1 --port 8090
```

Repo-specific local dev note:

- The private backend loads `backend/.env` then repo-root `.env`; the public
  ingress loads only `backend/.env.tradingview`. Never place private API keys
  or unrestricted database credentials in the ingress environment.
- `frontend/lib/api.ts` defaults to `http://localhost:8080` when `NEXT_PUBLIC_API_URL` is unset.
- `startdev.ps1` and `startdev.sh` launch the private backend on `8080` and
  frontend on `3000` by default. The restricted TradingView ingress on `8090`
  is opt-in with `TRADINGVIEW_INGRESS_ENABLED=true`.
- When ingress is enabled, both local backend processes bind to `127.0.0.1`;
  tunnel only `8090`.
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

Durable local enrichment/path jobs:

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
- Fill enrichment fields are all nullable; always guard with null checks before displaying or passing to AI.
- `fill.email_subject`/`email_body_text` are legacy write-only payloads. Every multi-row `select(Fill)` must pass `.options(*FILL_LIGHT)` (from `app.models`), and fill-returning endpoints must respond with `FillOut`, never raw `Fill` — FastAPI dumps all model fields, which would lazy-load one email body per row (metered egress on Neon). `GET /fills` takes `limit` (default 2000) and `offset`.
- Frontend status/summary polls skip hidden tabs and idle at 30–60s; keep new polling loops on that pattern.
- Alpaca context is fill-level. Trade path metrics are separate and require the Path Metrics job.
- Greeks PnL attribution lives on `trade_path_metrics` and depends on Polygon-enriched entry/exit fill greeks; when backfilling, run Polygon enrichment before the path job. Attribution fields are options-only and all nullable.
- Sequence metrics on `fill_market_context` are derived from `trade` rows, so trades must be rebuilt before Alpaca enrichment runs (the sync pipeline already orders it this way).
- Trade path metrics now prefetch minute bars batched by day, then fall back to cache-only per-day reads; preserve that shape and avoid reintroducing per-trade/day network fetch loops.
- Normal rebuilds reuse trade path metrics instead of recomputing all of them. `_rebuild_trades()` in `backend/app/routers/fills.py` snapshots `trade_path_metrics`, does the full clear+rebuild, then re-inserts only rows whose `inputs_fingerprint` (status + fills hash; see `trade_inputs_fingerprint` in `trade_path.py`) still matches the rebuilt trade. Dirty/orphaned rows are dropped so the path job recomputes just those. Use `_rebuild_trades(..., preserve_path_metrics=True)` for incremental rebuilds; only the destructive resync paths (which re-import fills with new ids) should call `_clear_derived_trade_data` + `_persist_rebuild` directly.
- The dashboard Alpaca "All history" control should send `range=all&force=true`; `force` alone only reprocesses the currently selected range.
- If recent trades have underlying/VWAP but missing RSI/EMA/MACD/ATR, inspect stale Alpaca daily cache coverage before changing indicator math.
- Option `price` in the DB is total premium per contract (dollars). Divide by 100 for per-share price before passing to Black-Scholes.
- Backend port is usually 8000. Use 8080 only when 8000 is occupied, and keep OAuth/API URLs in sync.
- The public TradingView ingress is a separate `8090` process. Keep its exact
  route allowlist, disable/redact access logging at Uvicorn and every
  proxy/tunnel because TradingView requires a query token, and never expose
  the private API.
- Keep TradingView analysis network calls outside DB transactions. Preserve
  atomic claims, attempt fencing, finite/bounded configuration, terminal
  generic failures, and lease recovery. An always-on worker or durable task
  dispatcher is still required for Cloud scale-to-zero deployment.
- Polygon cache lives at `backend/data/polygon_cache/`. Delete a cache file to force a re-fetch for that ticker/date. Empty responses are also cached as `{"_empty_cached_at": ts}` markers (1 year for finalized history, 7 days for indicator series) so dead tickers/days stop burning the rate limit every sync; deleting the marker file forces a retry.
- Alpaca cache lives at `backend/data/alpaca_cache/`. Daily cache files must be refreshed when they do not cover the requested date range.
- For SQLite, avoid long write transactions in historical jobs; progress updates to `job_run` can otherwise hit `database is locked`.
- Update `CLAUDE.md` and `AGENTS.md` together when project scope changes materially.
- Webull raw events are persisted before normalization. Preserve idempotency on `webull_raw_event.event_id` and `Fill.raw_email_id = webull:{event_id}`.
- Sync Center should treat `webull_listener` as a persistent listener, not a blocking finite sync job.
- Sync pipeline success does not imply Polygon enrichment finished; full pipeline and Gmail push intentionally launch Polygon in the background and only wait for Alpaca/path work.
- The full pipeline skips the trade rebuild step when Gmail sync saves 0 new fills (fill edits rebuild inline in their endpoint; manual rebuild stays available in the Sync Center). Enrichment steps still run and self-select missing work.
- Daily review is intentionally NOT part of "Sync Everything" (`_run_pipeline`) or the Gmail push pipeline. It is generated only on explicit request: from the daily page, or by running the standalone `daily_review` job in the Sync Center. Do not re-add it to the pipelines.
