# Architecture

The shape of the system. For where a specific feature lives, see
[feature-map.md](feature-map.md); for the rules you must not break, see
[domain-rules.md](domain-rules.md).

## Processes

Three processes run locally, and they are deliberately not one:

| Process | Port | Entry point | Exposure |
|---|---|---|---|
| Private API | 8080 from `startdev.sh`; 8000 from a bare `uvicorn` command and `mcp_server.py`'s default | `backend/app/main.py` | localhost only, **no auth** |
| TradingView ingress | 8090 | `backend/app/tradingview_ingress.py` | the only tunnelable port; **opt-in** |
| Frontend | 3000 | `frontend/` (Next 16 App Router) | localhost |

The ingress is a separate FastAPI application with its own route allowlist and
its own environment file (`backend/.env.tradingview`). It exists so a public
webhook can reach the database without exposing the private API. Private API
keys and unrestricted database credentials must never appear in its
environment.

On Ubuntu, `tradejournal-ingress.service` is opt-in and runs as its own OS
user, with `/etc/tradejournal/tradingview.env` instead of the local dotenv.
Deployment checks its database target and effective role privileges before
activation. The dedicated Caddy template forwards only the webhook path to
8090; the private Tailscale/frontend/API routes stay private. See
[production setup](../../deploy/README.md#tradingview-webhooks).

That separation is enforced on the import graph, not only described here.
`backend/tests/test_import_boundaries.py` fails if anything the ingress
imports, through any chain, lies outside a six-module allowlist
(`app.tradingview_ingress`, `app.tradingview_database`,
`app.routers.tradingview_webhook`, `app.engine.tradingview`,
`app.engine.tradingview_alerts`, `app.models`); if a private module imports
the ingress side; or if a pure engine module — the reconstructor, the parsers,
Strategy Lab metrics — starts reaching the network or the database engine.
The allowlists at the top of that file are the policy. Changing them is an
architecture change: make it deliberately, in the same commit as the import
that needs it, and say why.

A module leaves the impure set by taking what it needs as an argument rather
than reaching for it. `app.engine.indicators` was held out by one lazy
`fetch_minute_bars_for_date` import for a cache-only read; it now accepts a
`MinuteBarLoader` and its caller decides where bars come from and who pays for
them. `trade_path` and `auditor` are the same shape and are the remaining
targets, listed in the test.
`app.engine.market_map` was written that way from the start:
`scripts/backtest_market_map.py` fetches the bars and hands them in.

`startdev.sh` / `startdev.ps1` launch the private backend and frontend by
default. The ingress is opt-in:

```bash
TRADINGVIEW_INGRESS_ENABLED=true bash startdev.sh
```

When it is enabled, the launchers require a webhook token and refuse to start
when the private `DATABASE_URL` is set but `TRADINGVIEW_DATABASE_URL` is blank
— that split would silently point the two processes at different databases.

The [Ubuntu deployment package](../../deploy/README.md) instead supervises
six services: frontend, API and the four worker lanes. It keeps the frontend
and API on loopback; private Tailscale Serve reaches the frontend, whose
same-origin `/api/backend` proxy carries browser requests. Server components
use `API_INTERNAL_URL`; the packaged build fixes browser requests to the proxy.
Because that frontend grants access to the private API, it must never be made
public. Local development retains the existing direct API URL default.
Release code lives under `/opt/tradejournal`, persistent data/OAuth/locks under
`/var/lib/tradejournal`. Production PostgreSQL now runs on the same VPS, bound
to loopback; Neon remains a pre-cutover recovery source. The cutover and
recovery checks are recorded in [the deployment guide](../../deploy/README.md).
The package also enables a daily verified application backup, an encrypted
offsite backup timer when R2 credentials are configured, a five-minute
Gmail-import timer and an 08:00/17:00 New York Sync Everything timer. The
Gmail timer rebuilds trades only when it imported new fills and never starts
market-data enrichment; with real-time import enabled it is the safety net. Backup retention, prerequisites
and the off-host boundary are documented in `deploy/README.md`.

## Data flow

```
Gmail execution emails ─┐
Webull gRPC events     ─┼──> fill (source of truth) ──FIFO──> trade + tradefill
Manual entry           ─┘         │
                                  ├──> fill_market_context   (Alpaca, per fill)
                                  └──> Polygon greeks/indicators (columns on fill)
                                              │
                                              └──> trade_path_metrics (per trade)
```

Real-time Gmail import is outbound only: Gmail publishes a change notice to a
Pub/Sub topic, the `gmail` lane holds a pull subscription, and each notice
queues one coalesced `gmail_push` job. The sync lane reads Gmail history from
a stored cursor, imports only new Robinhood execution emails, rebuilds trades,
then enriches. `GET /gmail/health` reports whether that chain is live.

`fill` rows are the source records. `trade` and `tradefill` are **derived** and
safe to wipe and rebuild — rebuilding is normal, not a repair of last resort.
Corrections happen by editing bad fills and rebuilding, not by appending
compensating rows.

## Three isolated domains

They share a database and nothing else. Do not route data between them.

1. **Journal** — `account`, `fill`, `trade`, `tradefill`, `fill_market_context`,
   `trade_path_metrics`, `job_run`, `dailyreview`.
2. **Strategy Lab** — `strategy_definition` → `strategy_version` →
   `strategy_run` → `strategy_run_trade`, plus `strategy_run_metrics` and
   `strategy_experiment`. Simulated trades never enter `fill`/`trade`/
   `tradefill`.
3. **TradingView live alerts** — `tradingview_alert` only. Wire contract `v=1`
   is frozen in `docs/tradingview-webhook-contract-v1.md`.

## Persistence

- SQLModel models in `backend/app/models.py`; Alembic revisions in
  `backend/alembic/versions/`.
- SQLite by default (`backend/data/trade_journal.db`), PostgreSQL via
  `DATABASE_URL` using the `postgresql+psycopg://` driver form.
- **Alembic is the only thing that builds the schema.** Startup checks that the
  database is at head (`backend/app/schema.py`) and refuses to start otherwise,
  naming the command to run. It does not create or repair anything.
- Startup used to call `create_all()`. Two authorities meant a database could
  be stamped at one revision with later tables added by `create_all` — a state
  no migration produces, where `upgrade` and `stamp` are both plausible and
  only one is right. It also forced every migration from `f1a2b3c4d5e6` on to
  guard each object with `if not _table_exists(...)`.
- Models can still drift from migrations, which is what
  `backend/tests/test_schema_migrations.py` catches; the difference is that
  drift no longer gets papered over at runtime.
- Databases predating this change have tables and no `alembic_version`. Startup
  sends them to `backend/scripts/check_database.py`, which compares the live
  schema against the models — constraints included — and names `stamp` or
  `upgrade` accordingly.

## Background work

`job_run` rows are the durable record of enrichment, path-metric and sync
work. API status endpoints read `job_run`, never process-local state.

`JOB_EXECUTION_MODE=embedded` (default) dispatches API-owned threads through
the shared ownership runtime. `external` leaves committed requests for
`python -m app.jobs.worker --lane sync`, plus separate `polygon` and `webull`
workers. This is a single-host design with shared local process locks, not a
distributed or Cloud Run queue. API restarts do not invalidate live owners;
dead owners become failed and require an explicit new run. See
[background-jobs.md](background-jobs.md) for configuration, recovery and the
remaining API-owned tasks.

## Cost and latency constraints

Hosted Postgres meters egress and charges a network round trip per statement.
Two rules follow, and both have already been paid for once:

- Every multi-row `select(Fill)` passes `.options(*FILL_LIGHT)`, and
  fill-returning endpoints respond with `FillOut`, never a raw `Fill` — FastAPI
  dumps all model fields, which would lazy-load one legacy email body per row.
- Enrichers and path metrics commit in batches and throttle `job_run` progress
  writes (`_throttled_progress`). Per-item commits were a SQLite-era pattern.

Polygon enrichment is bounded by the API call budget, not the database. The
rate is discovered rather than configured: calls run unpaced until Polygon
answers 429, and the number that succeeded in the preceding minute is the
budget — so a Basic key settles near its 5/min after one refusal and a paid
key (no per-minute limit) never paces at all. Per ticker the work is one
daily-bars call, one hourly-bars page per ~50 sessions needed, and one
minute-bars call per 60-day window of fill dates; every indicator is derived
locally from those bars. Adding a per-fill or per-indicator call reintroduces
the hours-long backfills this replaced: on a free key every extra call per
ticker costs about eight minutes across a 38-ticker week.

Frontend polling follows the same instinct: status/summary polls skip hidden
tabs and idle at 30–60s. Keep new polling loops on that pattern, and avoid N+1
fetches — batch, or extend a shared API response.

## Historical data and live quotes are different problems

Enrichment is historical and cached: Polygon bars for the fill minute and the
indicator series, Alpaca bars for market context and the option path. Both are
bounded by an API budget and both write to disk caches, because the same fill
is enriched once and read forever.

Live quotes are not that. `app/engine/quotes.py` prices open positions on
demand, holds results for 60 seconds in memory, and caches nothing to disk. It
dispatches on `QUOTES_PROVIDER`: `yfinance` (the default, unofficial, one
option-chain download per contract) or `tradier` (licensed, consolidated, every
position in one request), falling back to yfinance whenever Tradier errors.

Keep the two apart. A live quote must never be written into a fill's
`*_at_fill` columns — those describe the fill minute, which a quote taken now
is not — and a vendor's greeks carry their own `updated_at` because they are
refreshed hourly, not live. `docs/tradier-integration-plan.md` has the whole
assessment, including why Tradier is not a candidate for the historical side.

## Frontend

Next 16 App Router, React 19, Tailwind. `frontend/lib/api.ts` holds the typed
API client and defaults to `http://localhost:8080` when
`NEXT_PUBLIC_API_URL` is unset. Table logic is shared through
`components/DashboardTables.tsx` and `components/TradesTable.tsx` — reuse them
rather than writing a fourth table.
