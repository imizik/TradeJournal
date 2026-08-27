# Architecture

The shape of the system. For where a specific feature lives, see
[feature-map.md](feature-map.md); for the rules you must not break, see
[domain-rules.md](domain-rules.md).

## Processes

Three processes run locally, and they are deliberately not one:

| Process | Port | Entry point | Exposure |
|---|---|---|---|
| Private API | 8080 (8000 also used) | `backend/app/main.py` | localhost only, **no auth** |
| TradingView ingress | 8090 | `backend/app/tradingview_ingress.py` | the only tunnelable port; **opt-in** |
| Frontend | 3000 | `frontend/` (Next 16 App Router) | localhost |

The ingress is a separate FastAPI application with its own route allowlist and
its own environment file (`backend/.env.tradingview`). It exists so a public
webhook can reach the database without exposing the private API. Private API
keys and unrestricted database credentials must never appear in its
environment.

`startdev.sh` / `startdev.ps1` launch the private backend and frontend by
default. The ingress is opt-in:

```bash
TRADINGVIEW_INGRESS_ENABLED=true bash startdev.sh
```

When it is enabled, the launchers require a webhook token and refuse to start
when the private `DATABASE_URL` is set but `TRADINGVIEW_DATABASE_URL` is blank
— that split would silently point the two processes at different databases.

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
- SQLite by default (`backend/data/trade_journal.db`), Postgres/Neon via
  `DATABASE_URL` using the `postgresql+psycopg://` driver form.
- **Startup calls `create_all()`**, so a fresh local database is built from the
  models, not from migrations. That is why models and migrations can drift
  without anyone noticing locally, and why
  `backend/tests/test_schema_migrations.py` exists.
- A database created by `create_all()` carries no Alembic stamp, so a later
  `alembic upgrade head` fails on "table already exists". `scripts/setup.sh`
  detects and stamps that case for the local SQLite file only.

## Background work

`job_run` rows are the durable record of enrichment, path-metric and sync
work. API status endpoints read `job_run`, never process-local state.

Local routes may start convenience background threads, but the same work must
run through `python -m app.jobs.run`, so a scheduler or Cloud Run Job can
invoke it later with the same container.

## Cost and latency constraints

Hosted Postgres meters egress and charges a network round trip per statement.
Two rules follow, and both have already been paid for once:

- Every multi-row `select(Fill)` passes `.options(*FILL_LIGHT)`, and
  fill-returning endpoints respond with `FillOut`, never a raw `Fill` — FastAPI
  dumps all model fields, which would lazy-load one legacy email body per row.
- Enrichers and path metrics commit in batches and throttle `job_run` progress
  writes (`_throttled_progress`). Per-item commits were a SQLite-era pattern.

Frontend polling follows the same instinct: status/summary polls skip hidden
tabs and idle at 30–60s. Keep new polling loops on that pattern, and avoid N+1
fetches — batch, or extend a shared API response.

## Frontend

Next 16 App Router, React 19, Tailwind. `frontend/lib/api.ts` holds the typed
API client and defaults to `http://localhost:8080` when
`NEXT_PUBLIC_API_URL` is unset. Table logic is shared through
`components/DashboardTables.tsx` and `components/TradesTable.tsx` — reuse them
rather than writing a fourth table.
