# Feature map

How to get from a feature to its screen, its endpoints, its code and its
proof. The code is the source of truth; this shortens the search and says
where the evidence for a change comes from.

Backend paths are relative to `backend/`, frontend paths to `frontend/`.

## The screens

The sidebar (`components/Nav.tsx`) has seven entries plus a **Sync** button
at its foot that opens a drawer on any page. Everything else is reached from
one of these by a row link or a button.

| Sidebar | Route | Page | Loads | Then, from the browser |
|---|---|---|---|---|
| Dashboard | `/` | `app/page.tsx` | `GET /stats`, `/trades`, `/accounts`, `/trades/fills/bulk`, `/quotes?tickers=`, `POST /quotes/positions` | `DashboardActions`: `GET /sync/summary`, `/sync/jobs`, `/sync/runs`, `/health`, `/auth/gmail/start`; `POST /sync/pipeline/run`, `/sync/jobs/{job_type}/run`, `/sync/advanced/rebuild-all`, `/sync/advanced/resync-all` |
| Daily Review | `/daily` → `/daily/{YYYY-MM-DD}` | `app/daily/page.tsx`, `app/daily/[day]/page.tsx` | `GET /daily-review`; per day `/daily-review/{day}`, `/trades`, `/trades/{id}/fills`, `/market-context/fills/bulk`, `/accounts`, quotes | `DailyAiPanel`: `POST /daily-review` |
| Trades | `/trades` → `/trades/{id}` | `app/trades/page.tsx`, `app/trades/[id]/page.tsx`, `components/TradesTable.tsx` | list: `GET /trades?status=&ticker=&account=&type=`, `/accounts`. Detail (client page): `/trades/{id}`, `/trades/{id}/fills`, `/market-context/fills/bulk`, `/market-context/trade/{id}` | `AuditPanel`: `GET /market-context/audit/{id}`; review button: `POST /trades/{id}/review` |
| Analytics | `/analytics` | `app/analytics/page.tsx` | `GET /stats` | — |
| Fills | `/fills` → `/fills/{id}` | `app/fills/page.tsx`, `app/fills/[id]/page.tsx` | `GET /fills`, `/accounts`; edit: `/fills/{id}` | `ManualFillForm`: `POST /fills`, `PUT /fills/{id}` |
| Strategy Lab | `/strategy-lab` → `/strategies/{id}`, `/strategies/{id}/versions/new`, `/versions/{id}`, `/versions/{id}/import`, `/runs/{id}` | `app/strategy-lab/**`, `components/strategy-lab/`, `lib/strategy-lab/api.ts` | `GET /strategy-lab/strategies`, `/strategies/{id}`, `/versions/{id}`, `/runs`, `/runs/{id}`, `/runs/{id}/trades`, `/runs/{id}/metrics` | forms and wizard: `POST /strategy-lab/strategies`, `/strategies/{id}/versions`, `/versions/{id}/fork`, `/imports/preview`, `/runs/import`, `/runs/{id}/metrics/recalculate`; `PATCH /strategies/{id}`, `/versions/{id}` |
| Research | `/research/ai-buildout` | `app/research/ai-buildout/page.tsx`, `components/research/`, `lib/research/` | — | `GET`/`PUT /research/workspaces/{slug}` |
| Sync (drawer) | any page | `components/StatusPanel.tsx` | — | polls `GET /fills/enrich/status`, `/market-context/enrich/status`, `/market-context/trade-path/status`, `/market-context/coverage` |

Things worth knowing before you touch a page:

- Pages under `app/` are server components that call the API from the Next
  server through `lib/api.ts` (`NEXT_PUBLIC_API_URL`, default
  `http://localhost:8080`), except `/trades/{id}`, which is a client page.
  Every component marked `"use client"` fetches from the browser instead,
  which is why the backend's CORS allowlist must include the frontend origin
  (`verification.md`, browser tests).
- Row links go to `/trades/{id}` from the dashboard tables, the trades table
  and the daily review; the daily review also links each fill to
  `/fills/{id}?returnTo=`. The trade detail page links nowhere.
- The Sync Center's job types (`JOB_CONFIG` in `app/routers/sync.py`) are
  `gmail_sync`, `fill_import_check`, `trade_rebuild`, `polygon_enrich`,
  `alpaca_enrich`, `trade_path`, `daily_review` and `gmail_push`;
  `full_pipeline` and `resync_all` (`_EXTRA_JOB_CONFIG`) are the run types
  behind the pipeline button and the advanced resync, and
  `gmail_watch_renew` and `gmail_listener` are the run types the Gmail
  listener creates. `POST
  /sync/pipeline/run` (`_run_pipeline`) runs six
  stages: Gmail sync, fill check, trade rebuild (only when new fills arrived),
  then Polygon, Alpaca and trade-path enrichment over everything missing.
  Daily review is deliberately not one of them. Status endpoints read
  `job_run` rows, never process memory (`architecture.md`).
- `/accounts` (`app/accounts/page.tsx`) is a static placeholder: not in the
  sidebar, calls nothing, renders "No accounts yet."
- `/privacy` (`app/privacy/page.tsx`) is static and not in the sidebar. The
  Google OAuth consent screen links to it; keep it true to what the Gmail
  integration does.
- Phone layout: below `md` the sidebar in `components/Nav.tsx` is replaced by a
  bar plus a slide-out menu (same `navItems`), and below `sm` tables mark
  secondary columns `wide` so only a few show -- `TradesTable`,
  `DashboardTables`, `app/fills/page.tsx`. A row still opens the full record.
  `app/manifest.ts` plus `public/icon-*.png` (regenerate with
  `frontend/scripts/generate-icons.py`) make the home-screen shortcut open like
  an app. Proof: `e2e/phone.spec.ts`.

## Backend by feature

Each row names where the logic lives, the routes that reach it, and the test
that is the first place to look for evidence. "—" under proof means the path
is only covered where its network call is stubbed, or not at all; say so when
you change it (`verification.md`, "What is NOT covered yet").

| Working on | Start at | Routes | Proof |
|---|---|---|---|
| Background job ownership and recovery | `app/engine/job_runtime.py`, `app/jobs/worker.py`; commands in [background-jobs.md](background-jobs.md) | Sync Center, Gmail push, enrichment and Webull start routes | `tests/test_job_runtime.py` (competing processes, API restarts, worker death, queue consumption and fill dedupe/FIFO); external providers stubbed |
| PnL, FIFO, trade shape | `app/engine/reconstructor.py` | `POST /rebuild`; runs after every fill write and in `trade_rebuild` | `tests/test_reconstructor.py`; `test_seed_dev_data.py` (`EXPECTED`); `test_seed_snapshot.py` (golden snapshot over the seed) |
| Robinhood email parsing | `app/engine/email_parser.py` | — | `test_email_parser.py` |
| Gmail fetch and import | `app/engine/gmail_poller.py`, `app/routers/fills.py` | `POST /fills/import`, `POST /fills/resync-all` (destructive, needs `confirm`) | `test_gmail_poller.py`, `test_fill_import.py`, `test_environment_guard.py` |
| Gmail OAuth | `app/routers/auth.py` | `GET /auth/gmail/start`, `/auth/gmail/start/browser`, `/auth/gmail/callback` | `test_gmail_auth.py`, `test_cors.py` |
| Real-time Gmail import (Pub/Sub pull) | `app/engine/gmail_listener.py` (lane `gmail`), history cursor in `app/engine/gmail_poller.py`, `_import_gmail_changes` and `queue_gmail_push_pipeline` in `app/routers/sync.py`; setup in [deploy/README.md](../../deploy/README.md#real-time-gmail-import) | jobs `gmail_listener`, `gmail_push`, `gmail_watch_renew`; `POST /gmail/watch`, `GET /gmail/watch/status`, `POST /gmail/push` (same coalesced queue; nothing public calls it) | `test_gmail_listener.py` (fake subscriber), `test_gmail_realtime.py` (cursor, targeted fetch, coalescing) |
| Gmail status banner and live refresh | `app/engine/gmail_health.py`; `components/GmailStatusBanner.tsx`, `lib/useGmailHealth.ts`, status line in `components/Nav.tsx` | `GET /gmail/health` (polled every 30s while visible; `data_version` drives `router.refresh()`) | `test_gmail_realtime.py` (health states); rendering is not in the browser suite |
| Polygon enrichment, greeks, indicators | `app/engine/enricher.py`, `app/engine/indicators.py` | `POST /fills/enrich?range=`, `GET /fills/enrich/status`; job `polygon_enrich` | `test_enricher.py` (incl. the discovered rate limit), `test_indicators_rvol.py` |
| Alpaca fill context | `app/engine/alpaca.py`, `app/engine/alpaca_enricher.py`, `app/engine/behavior.py` (sequence metrics) | `POST /market-context/enrich?range=&force=`, `GET /market-context/enrich/status`, `/market-context/fill/{id}`, `/market-context/fills/bulk?ids=`, `/market-context/coverage`; job `alpaca_enrich` | `test_alpaca_context_repair.py`, `test_indicators_rvol.py` (the injected cache-only bar loader) |
| Trade path metrics (MFE, MAE, exit efficiency) | `app/engine/trade_path.py` | `POST /market-context/trade-path/compute`, `GET /market-context/trade-path/status`, `/market-context/trade/{id}`, `/market-context/trade-path/bulk?ids=`; job `trade_path` | — (live Alpaca fetch; `test_seed_snapshot.py` stubs it) |
| Trade audit | `app/engine/auditor.py` | `GET /market-context/audit/{trade_id}` | `test_seed_snapshot.py` (Alpaca stubbed, cache emptied) |
| Durable jobs, Sync Center | `app/engine/jobs.py`, `app/jobs/run.py`, `app/routers/sync.py`; `app/engine/api_wait.py` (per-job pacing and backoff telemetry) | `GET /sync/summary`, `/sync/jobs`, `/sync/runs`; `POST /sync/pipeline/run`, `/sync/jobs/{job_type}/run?range=&force=`, `/sync/advanced/rebuild-all`, `/sync/advanced/resync-all` | `test_sync_progress.py`, `test_environment_guard.py` (the destructive guard) |
| Trades, tags | `app/routers/trades.py` | `GET /trades`, `/trades/{id}`, `/trades/{id}/fills`, `/trades/fills/bulk?ids=`; `POST /trades/{id}/tags` | browser tests; `test_seed_dev_data.py` |
| Fills CRUD | `app/routers/fills.py` | `GET`/`POST /fills`, `GET`/`PUT /fills/{id}` | browser tests |
| Stats, accounts | `app/routers/stats.py`, `app/routers/accounts.py` | `GET /stats`, `GET /accounts` | the browser fixture test asserts `/stats` totals |
| Live quotes | `app/engine/quotes.py` (provider seam), `app/engine/tradier.py`, `app/engine/occ.py`, `app/routers/quotes.py` | `GET /quotes?tickers=`, `POST /quotes/positions` | `test_quotes_provider.py` (dispatch, batching, fallback), `test_tradier.py`, `test_occ.py` — the live call itself is uncovered; `scripts/compare_quote_providers.py` is how it gets checked |
| Market packets, reports, ticker analysis | `app/engine/packets.py`, `app/engine/analyzer.py`, `app/engine/news.py`, `prompts/market_report.md` | `GET /packets/report`, `/packets/analyze`, `/packets/news` | — (live Alpaca and yfinance) |
| Scalp analysis | `app/engine/scalper.py` (`score_scalp()` is pure) | `GET /packets/scalp` | `test_scalper.py` |
| AI review | `app/ai/reviewer.py`, `app/ai/daily_reviewer.py`, `app/routers/daily_review.py` | `POST /trades/{id}/review`; `GET /daily-review`, `/daily-review/{day}`, `POST /daily-review`; job `daily_review` | — (Anthropic) |
| Webull | `app/engine/webull*.py`, `app/routers/webull.py` | `GET /webull/health`, `/webull/accounts`, `/webull/orders/recent`, `/webull/orders/{order_id}`, `/webull/events/status`; `POST /webull/events/test-ingest`, `/webull/events/start`, `/webull/events/stop`; job `webull_listener` | `test_webull_ingest.py`, `test_webull_events.py`, `test_webull_signer.py` |
| Strategy Lab | `app/engine/strategy_lab.py`, `strategy_csv.py`, `strategy_metrics.py`, `app/routers/strategy_lab.py` | listed under the screen above | `test_strategy_lab_routes.py`, `test_strategy_import_routes.py`, `test_strategy_run_reads.py`, `test_strategy_csv.py`, `test_strategy_metrics.py` |
| Research workspace | `app/engine/research.py`, `app/routers/research.py` | `GET`/`PUT /research/workspaces/{slug}` | — |
| TradingView Signals page | `frontend/app/signals/page.tsx`, `frontend/app/signals/[alertId]/page.tsx`, `frontend/lib/tradingview.ts` | `/signals` in the nav, then any row's **Detail** | no automated coverage — verified by hand against a live alert |
| TradingView alerts | `app/engine/tradingview.py`, `tradingview_alerts.py`, `tradingview_analysis.py`; `app/routers/tradingview_*.py`; `app/tradingview_ingress.py`, `app/tradingview_database.py` | private `GET /tradingview/alerts`, `/tradingview/alerts/{alert_id}`; public ingress on `:8090` `POST /tradingview/webhook`, `GET /health` | `test_tradingview.py`, `_routes`, `_alert_model`, `_alert_persistence`, `_alert_migration`, `_analysis`; `test_import_boundaries.py` (what the ingress may import) |
| Schema | `app/models.py`, `alembic/versions/`, `app/schema.py` | — | `test_schema_migrations.py`, `test_schema_authority.py`, `test_postgres_parity.py`, `test_postgres_migration_paths.py` |
| Which database am I on | `app/environment.py`, `app/database.py`, `app/routers/health.py` | `GET /health` | `test_environment_guard.py`, `test_check_database.py` |
| Database roles | `scripts/setup_roles.py` | — | `test_setup_roles.py` (Postgres job only) |
| App startup and wiring | `app/main.py` | — | every `TestClient(app)` test boots the real lifespan |
| Import boundaries | `tests/test_import_boundaries.py` (the policy lists are at the top) | — | itself; see `architecture.md` |
| MCP tools for Claude Desktop | `mcp_server.py` | — | — |

## Getting evidence for a change

- **Engine or router change:** the test module in the table, or drive the
  route through `TestClient(app)` the way `test_fill_import.py` does.
- **Anything a page shows:** `bash scripts/verify.sh --e2e`. The smoke tests
  (`frontend/e2e/smoke.spec.ts`) open `/`, `/trades`, `/trades/{id}`,
  `/fills`, `/analytics`, `/daily`, `/strategy-lab` against a seeded backend
  and assert the values from `EXPECTED` in `scripts/seed_dev_data.py`. Then
  open the route on the dev server (`bash startdev.sh`, port 3000) and say
  what you saw.
- **A route with no test:** call it and paste the response.
  `curl -s localhost:8080/health` tells you which database you are on first.

## Analysis and repair scripts

`backend/scripts/` — stable utilities:

- `generate_reconciliation_report.py` — markdown reports into `backend/reports/`
- `analyze_tiebreak_impact.py` — read-only same-timestamp FIFO impact analysis
- `csv_reconstruct.py` — DB-derived FIFO vs Robinhood CSV ground truth
- `find_phantoms.py` — duplicate cumulative partial-fill investigation
- `rebuild_trades.py`, `backfill_greeks.py`, `inspect_enrichment.py`
- `seed_dev_data.py` — the fixed fills behind the browser tests and the snapshot
- `migrate_sqlite_to_postgres.py` — SQLite → PostgreSQL copy
- `check_database.py` — read-only preflight: which database, schema ready?
- `setup_roles.py` — create the app and ingress roles, then prove they are
  limited by connecting as each one (`environments.md`)

`backend/compare_fills*.py` are ad hoc scratch scripts, not stable app code.

Scripts in `backend/scripts/` may do real work (open databases, call APIs) at
**import** time. Pytest collection is scoped to `backend/tests` for this
reason, and ruff lints them without importing them.

## Reference documents

- `docs/tradingview-webhook-contract-v1.md` — frozen wire contract
- `docs/tradingview-signal-loop-plan.md` — staged plan for the signal loop
- `docs/strategy-lab-metrics.md` — metric definitions
- `docs/strategy-lab-pine-metadata.md` — the `sl1|key=value|...` convention

## Where things are NOT

- No auth, no multi-user model, no roles in the application (database roles
  exist; see `environments.md`).
- No live trading. Webull has read/listen/import only; the scalper is
  decision support and never places orders.
- No component-level frontend tests; the Playwright smoke tests are the only
  frontend coverage, and they are smoke depth.
- Pine indicator source is not implemented (Step 5); the Signals page is.
- `/accounts` is a placeholder page (above).

## Subsystem notes worth knowing before you dig

- **Market packets** (`app/engine/packets.py`) build deterministic
  premarket/postmarket reports: index detail with VWAP/ORB/premarket/AH, sector
  rotation, macro gauges (`^VIX`/`^TNX` via yfinance), a bucketed high-beta
  universe with `rs_vs_spy`, leaders/laggards, and raw Alpaca news. The symbol
  universe is hand-edited in `backend/data/universe.json` — it is an execution
  watchlist, not the market. No relevance filtering happens in Python; Claude
  triages headlines. Judgment lives in `backend/prompts/market_report.md`, not
  in backend code.
- **Scalper** (`app/engine/scalper.py`) is read-only decision support and never
  places trades. `score_scalp()` is a pure function over a packet and is tested
  without network in `tests/test_scalper.py`; `build_scalp_analysis()` is the
  gathering layer. Hard rules: closed market or stale data ⇒ wait/no_trade;
  option spread >10% of mid ⇒ reject; inside the VWAP/OR band on weak RVOL ⇒
  chop; extra strict in the first 5–15 minutes.
- **MCP server** (`backend/mcp_server.py`) is a stdio FastMCP adapter for Claude
  Desktop. It is a thin httpx client over the private API, holds no API keys,
  and logs calls to `backend/data/mcp_log/*.jsonl`. It defaults to
  `http://localhost:8000`; set `TRADE_JOURNAL_API` when the backend is on 8080.
  Read-only tools: `get_market_report`, `get_news`, `analyze_ticker`,
  `analyze_scalp`, `get_trades`, `get_stats`, `get_trade_detail`,
  `get_coverage`, `get_trade_audit`, `get_trade_path_metrics`,
  `get_fill_contexts`.
- **Caches** live at `backend/data/polygon_cache/` and
  `backend/data/alpaca_cache/`. Deleting a file forces a re-fetch. The audit
  and the golden snapshot read the Alpaca cache; `test_seed_snapshot.py` points
  it at an empty directory so a developer's cache cannot leak into the result.
