# Feature map

Where to start for a given subsystem. The code is the source of truth; this
just shortens the search.

## Backend by subsystem

Paths are relative to `backend/`.

| Working on | Start at |
|---|---|
| PnL, FIFO, trade shape | `app/engine/reconstructor.py` |
| Robinhood email parsing | `app/engine/email_parser.py` |
| Gmail fetch/import | `app/engine/gmail_poller.py`, `app/routers/fills.py` |
| Gmail OAuth | `app/routers/auth.py` |
| Gmail Pub/Sub push | `app/routers/gmail_push.py` |
| Polygon enrichment, greeks | `app/engine/enricher.py`, `app/engine/indicators.py` |
| Alpaca fill context | `app/engine/alpaca.py`, `app/engine/alpaca_enricher.py` |
| Trader-state sequence metrics | `app/engine/behavior.py` |
| Trade path metrics, attribution | `app/engine/trade_path.py` |
| Durable jobs | `app/engine/jobs.py`, `app/jobs/run.py`, `app/routers/sync.py` |
| Live quotes | `app/engine/quotes.py`, `app/routers/quotes.py` |
| Market packets / reports | `app/engine/packets.py`, `app/engine/news.py`, `backend/prompts/market_report.md` |
| Scalp analysis | `app/engine/scalper.py` (`score_scalp()` is pure) |
| AI review | `app/ai/reviewer.py`, `app/ai/daily_reviewer.py` |
| Webull | `app/engine/webull*.py`, `app/routers/webull.py` |
| Strategy Lab | `app/engine/strategy_lab.py`, `strategy_csv.py`, `strategy_metrics.py`, `app/routers/strategy_lab.py` |
| TradingView alerts | `app/engine/tradingview*.py`, `app/tradingview_ingress.py`, `app/routers/tradingview_*.py` |
| Schema | `app/models.py`, `alembic/versions/` |
| App startup / wiring | `app/main.py` |
| MCP tools for Claude Desktop | `backend/mcp_server.py` |

## Frontend by page

| Page | File |
|---|---|
| Dashboard | `app/page.tsx`, `components/DashboardActions.tsx`, `components/DashboardTables.tsx` |
| Trades list / detail | `app/trades/page.tsx`, `app/trades/[id]/page.tsx`, `components/TradesTable.tsx` |
| Fills list / edit | `app/fills/page.tsx`, `app/fills/[id]/page.tsx`, `components/ManualFillForm.tsx` |
| Analytics | `app/analytics/page.tsx` |
| Daily review | `app/daily/page.tsx`, `app/daily/[day]/page.tsx` |
| Strategy Lab | `app/strategy-lab/`, `components/strategy-lab/`, `lib/strategy-lab/` |
| Research workspace | `app/research/ai-buildout/`, `components/research/` |
| API client & types | `lib/api.ts` |

## Analysis and repair scripts

`backend/scripts/` — stable utilities:

- `generate_reconciliation_report.py` — markdown reports into `backend/reports/`
- `analyze_tiebreak_impact.py` — read-only same-timestamp FIFO impact analysis
- `csv_reconstruct.py` — DB-derived FIFO vs Robinhood CSV ground truth
- `find_phantoms.py` — duplicate cumulative partial-fill investigation
- `rebuild_trades.py`, `backfill_greeks.py`, `inspect_enrichment.py`
- `migrate_sqlite_to_postgres.py` — SQLite → Neon copy

`backend/compare_fills*.py` are ad hoc scratch scripts, not stable app code.

Note: scripts in `backend/scripts/` may do real work (open databases, call
APIs) at **import** time. Pytest collection is scoped to `backend/tests` for
this reason.

## Reference documents

- `docs/tradingview-webhook-contract-v1.md` — frozen wire contract
- `docs/tradingview-signal-loop-plan.md` — staged plan for the signal loop
- `docs/strategy-lab-metrics.md` — metric definitions
- `docs/strategy-lab-pine-metadata.md` — the `sl1|key=value|...` convention

## Where things are NOT

- No auth, no multi-user model, no roles anywhere.
- No live trading. Webull has read/listen/import only; the scalper is
  decision support and never places orders.
- No frontend test framework.
- Pine indicator source and the Signals page are not implemented.

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
  `backend/data/alpaca_cache/`. Deleting a file forces a re-fetch.

## API surface

Grouped by area; see `backend/app/routers/` for the definitions.

- Health/auth: `GET /health`, `GET /auth/gmail/start`,
  `GET /auth/gmail/start/browser`, `GET /auth/gmail/callback`
- Accounts: `GET /accounts`
- Fills: `GET|POST /fills`, `GET|PUT /fills/{id}`, `POST /fills/import`,
  `POST /fills/resync-all`, `POST /fills/enrich`, `GET /fills/enrich/status`
- Trades: `GET /trades`, `GET /trades/{id}`, `GET /trades/{id}/fills`,
  `GET /trades/fills/bulk`, `POST /trades/{id}/tags`, `POST /trades/{id}/review`
- Stats/rebuild: `GET /stats`, `POST /rebuild`
- Quotes: `GET /quotes`, `POST /quotes/positions`
- Packets: `GET /packets/report`, `/packets/analyze`, `/packets/scalp`,
  `/packets/news`
- Market context: `POST /market-context/enrich`,
  `GET /market-context/enrich/status`, `/coverage`, `/fill/{id}`, `/fills/bulk`,
  `/trade/{id}`, `/trade-path/bulk`, `POST /market-context/trade-path/compute`,
  `GET /market-context/trade-path/status`, `/audit/{trade_id}`
- Daily review: `GET /daily-review`, `GET /daily-review/{day}`,
  `POST /daily-review`
- Sync Center: `GET /sync/summary`, `/sync/jobs`, `/sync/runs`,
  `POST /sync/pipeline/run`, `POST /sync/jobs/{job_type}/run`,
  `POST /sync/advanced/rebuild-all`, `POST /sync/advanced/resync-all`
- Gmail push: `POST /gmail/watch`, `GET /gmail/watch/status`, `POST /gmail/push`
- Webull: `GET /webull/health`, `/accounts`, `/orders/recent`,
  `/orders/{order_id}`, `POST /webull/events/{test-ingest,start,stop}`,
  `GET /webull/events/status`
- Strategy Lab: `GET|POST /strategy-lab/strategies`,
  `GET|PATCH /strategy-lab/strategies/{id}`,
  `POST /strategy-lab/strategies/{id}/versions`,
  `GET|PATCH /strategy-lab/versions/{id}`,
  `POST /strategy-lab/versions/{id}/fork`,
  `POST /strategy-lab/imports/preview`, `POST /strategy-lab/runs/import`,
  `GET /strategy-lab/runs`, `/runs/{id}`, `/runs/{id}/trades`,
  `POST /strategy-lab/runs/{id}/metrics/recalculate`,
  `GET /strategy-lab/runs/{id}/metrics`
- TradingView: private `GET /tradingview/alerts`, `/alerts/{alert_id}`;
  public ingress `:8090` `POST /tradingview/webhook`
