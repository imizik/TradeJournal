# Plan: TradingView → Webhook → Scalp-Verdict Loop ("Isaac Market Map")

**Audience:** a coding agent (Codex) implementing this cold. Everything needed is in this doc plus the referenced files. Read the referenced files before writing code; do not guess signatures.

> **Implementation status (2026-07-26):** Steps 1–4 are complete. The frozen
> v1 contract/parser, isolated persistence, authenticated webhook-only ingress,
> private read API, and fenced one-at-a-time analysis worker are implemented
> and tested. No Pine script or frontend signal page exists yet.

## Goal

Close the loop the market-preview notes described:

> TradingView Pine indicator detects an objective setup (opening-range break, VWAP reclaim, PDH/PDL break, retest) → fires an **alert with a JSON body** to a dedicated public webhook-only FastAPI ingress → the backend persists the signal, runs the **existing deterministic scalp scorer** on that symbol, and stores a verdict (`no_trade` / `wait` / `long_scalp` / `short_scalp`) with reasons.

This is **read-only decision support**, exactly like the existing Scalper Analyzer. It never places a trade and never touches the journal.

## Non-goals / hard guardrails (do not violate)

- **Never** write TradingView signals into `fill`, `trade`, `tradefill`, or FIFO reconstruction. This is a separate, isolated domain (same principle as Strategy Lab simulated rows and the "webhook signals are not trades" rule).
- **Do not** re-use the `sl1|...` Pine metadata convention (`docs/strategy-lab-pine-metadata.md`) — that is for backtest CSV import, a different path. This is a live JSON webhook.
- Reuse `build_scalp_analysis()` for the verdict; **do not** reimplement scoring. The scorer already forces `wait`/`no_trade` when the market is closed or data is stale — that behavior is correct, keep it.
- Follow the repo egress discipline: list endpoints return light DTOs, never the raw payload column per row (same reasoning as `FILL_LIGHT`/`FillOut`).
- Keep DB write transactions short (SQLite write-lock caution from `CLAUDE.md`).

## Architecture

```
TradingView (Pine v6 "Isaac Market Map" indicator)
  ├─ draws objective levels on the chart (PDH/PDL/PDC, premarket/overnight/weekly H-L,
  │  5/15/30m opening ranges, VWAP, 9/20 EMA, gap/gap-fill, ATR zones, RVOL, RS vs SPY)
  └─ on trigger: alert() sends JSON ──HTTPS POST──► webhook-only FastAPI :8090
                                                       1. verify token before body/DB
                                                       2. bounded stream + frozen parser
                                                       3. persist idempotently
                                                       4. return 200 fast
Private TradeJournal API :8080
  ├─ one DB-backed worker claims pending alerts
  │    → build_scalp_analysis(symbol, side) outside a DB transaction
  │    → fenced verdict/confidence/assessment update
  └─ GET /tradingview/alerts + /alerts/{id}
Frontend "Signals" page (future) ◄── private reads ── (poll, hidden-tab-skip, 30–60s)
```

The webhook-only ingress must be **publicly reachable** (TradingView cannot hit
`localhost`). The existing TradeJournal API has no general authentication and
must remain private:

- **Local/dev:** run `app.tradingview_ingress:app` on `8090` and tunnel only
  that port, never the private backend on `8000`/`8080`.
- **Prod:** deploy a separate restricted ingress and durable dispatcher. Do
  not expose journal routes, read APIs, docs, or OpenAPI on its hostname.
- **TradingView webhooks require a paid TradingView plan** (free tier cannot POST webhooks). Note this to the user; it is a prerequisite, not a code task.

---

## The integration contract (the one hard boundary)

`docs/tradingview-webhook-contract-v1.md` is the canonical specification. Pine
builds this JSON string and sends it as the alert message. The token is not
stored in the body, but a query-string token can still appear in Uvicorn,
tunnel, proxy, or cloud access logs. Use a dedicated high-entropy token,
redaction, and rotation.

```json
{
  "v": 1,
  "indicator_version": "1.0.0",
  "alert_id": "v1:1.0.0:AAPL:5:1737561600000:orb_break:long",
  "symbol": "AAPL",
  "timeframe": "5",
  "setup": "orb_break",
  "side": "long",
  "price": 214.32,
  "bar_time_ms": 1737561600000,
  "levels": { "pdh": 214.45, "pdl": 204.51, "vwap": 211.10, "or_high": 213.9, "or_low": 210.2 },
  "context": { "rvol": 1.82, "ema9_over_ema20": true, "above_vwap": true, "rs_vs_spy": 0.31 }
}
```

Rules:
- `v` is the immutable wire schema; `indicator_version` independently tracks
  Pine logic/configuration.
- `alert_id` is the canonical **idempotency key**:
  `"v1:{indicator_version}:{symbol}:{timeframe}:{bar_time_ms}:{setup}:{side}"`.
  Same-ID/same-fingerprint deliveries are duplicates; same-ID/different
  payloads are collisions.
- `bar_time_ms` is Pine `time_close` in UTC epoch milliseconds.
- `side` ∈ `long | short`. Maps to `build_scalp_analysis(direction=side)`.
- `setup` is a short slug (`orb_break`, `orb_fail`, `vwap_reclaim`, `vwap_loss`, `pdh_break`, `pdl_break`, `retest`). Free-form string; do not hard-validate an enum (Pine authors will add setups).
- `levels`/`context` are optional, flat, stored for display/debugging. Backend does not trust them for the verdict — the verdict comes from live Alpaca data via the scorer. They are the Pine's *self-reported* snapshot.

---

## Backend work

### Phase 1 — Receiver + persistence + verdict (core)

**1. Model (complete)** — `TradingViewAlert` in `backend/app/models.py`
uses the canonical `alert_id` as its natural primary key and stores:

- contract/parser/indicator provenance and both semantic/raw SHA-256 hashes;
- normalized identity, UTC bar-close time, side, setup, and exact price;
- immutable raw payload plus deterministic flat `levels`/`context` snapshots;
- analysis lifecycle, scorer revision, verdict, confidence, assessment, and
  error fields.

The domain has no foreign keys to journal or Strategy Lab tables. Prices remain
exact through an SQLite text / PostgreSQL `NUMERIC(28,12)` type variant, and
`bar_time_ms` is a true `BIGINT`.

Alembic revision `2e6f9a1b4c7d` creates the table and indexes. It is guarded for
the repo's `create_all()`-before-Alembic startup path: a compatible existing
table has missing indexes repaired. Missing/unexpected columns, wrong
types/nullability/defaults, a wrong primary key or constraint set, and
same-name wrong-column indexes are rejected. SQLite check expressions are also
verified exactly; PostgreSQL rewrites reflected check SQL, so that dialect's
guard verifies the canonical constraint names rather than comparing text.

**2. Parser, persistence, and analysis services (complete)**

Keep the network-free parsing logic in `backend/app/engine/tradingview.py`
**pure and testable** (same split as `score_scalp` vs
`build_scalp_analysis`):

- `parse_alert_bytes(raw_body)` performs the frozen bounded UTF-8/JSON
  decoding, preserves decimals, rejects duplicate keys, and dispatches to
  `parse_alert()` / `parse_alert_v1()`. The receiver uses it instead of
  `request.json()`.
- `backend/app/engine/tradingview_alerts.py` now owns persistence and reads
  without adding DB imports to the frozen parser.
- `persist_alert(session, parsed, raw_body)` inserts first and commits
  atomically. After a uniqueness failure it rolls back before reading the
  winner, classifies same-ID/same-semantic-hash as a duplicate, and raises an
  explicit collision for same-ID/different-content. SQLite lock contention is
  surfaced separately instead of being misreported as a duplicate.
- `serialize_snapshot()` preserves JSON scalar types and exact decimals in
  sorted compact JSON. `list_alerts()` applies bounded filters/pagination and
  defers large evidence fields; `get_alert()` explicitly hydrates full detail,
  including after a same-session light-list query.
- `backend/app/engine/tradingview_analysis.py` uses the database as the durable
  queue. Conditional updates atomically claim recoverable rows and increment
  `analysis_attempts`; that attempt is the fencing token on every finalize.
- `run_alert_analysis()` closes the claim session before
  `build_scalp_analysis(symbol, direction=side)`, then opens a new short
  session for analysis fields only. Pine price/levels/context never feed the
  verdict.
- Missing Alpaca configuration and stale/future signals are `skipped`.
  Explicit Alpaca transport failures and retryable HTTP responses
  (`408`/`429`/`5xx`) use bounded attempts/backoff; generic code/output errors
  are terminal. Closed, after-hours, premarket, and stale-market-data scorer
  outputs are normal completed results.
- `TradingViewAnalysisWorker` is one cooperatively stoppable private-process
  poller. It periodically terminalizes exhausted abandoned claims, stale
  running leases are reclaimable, and an older attempt cannot overwrite a
  newer result. Its daemon thread permits bounded process shutdown; the
  durable lease recovers any interrupted in-flight claim.

**3. HTTP surfaces (complete)** — deliberately split by trust boundary:

- `backend/app/tradingview_ingress.py` is a separate FastAPI app exposing only
  `POST /tradingview/webhook` and `GET /health`. It has no docs/OpenAPI, CORS,
  slash redirects, journal routes, private reads, or market-data worker.
  `/health` is readiness: it returns `503` unless the token and isolated table
  are usable.
- `backend/app/routers/tradingview_webhook.py` fails closed unless a token of
  at least 32 bytes is configured, compares UTF-8 bytes with
  `secrets.compare_digest`, authenticates before body streaming or DB session
  creation, and accepts `?token=` or `Authorization: Bearer`.
- The receiver stream-caps the body at 16 KiB, calls
  `parse_alert_bytes()`, opens its DB session only after parsing succeeds,
  returns `200` for true duplicates, `409` for identity collisions, and
  retryable `503` for SQLite contention.
- `backend/app/routers/tradingview_alerts.py` is registered only on the private
  API. `GET /tradingview/alerts?limit=50&offset=0&symbol=` returns a light DTO:
  everything **except** `payload_json`/`assessment_json`/`levels_json`/
  `context_json`/`analysis_error`. Newest first.
- `GET /tradingview/alerts/{alert_id}` — full detail incl. raw payload,
  parsed assessment, and tagged snapshot scalars so exact numbers remain
  distinguishable from strings.

Return Pydantic DTOs, never the raw SQLModel row in the list (egress discipline).

**4. Runtime registration (complete)**

- `app.main` includes only the private read router and starts/stops one worker
  from its lifespan only when `TRADINGVIEW_ANALYSIS_AUTOSTART=true`.
- `app.tradingview_ingress` includes only the public webhook router.
- `startdev.sh`/`startdev.ps1` launch private API `:8080`, ingress `:8090`,
  and frontend `:3000`; both backend processes bind to `127.0.0.1`.
- Both startdev launchers fail preflight when the private API uses a configured
  `DATABASE_URL` but ingress has no `TRADINGVIEW_DATABASE_URL`, preventing a
  hosted-worker/local-ingress split.
- The ingress loads only `backend/.env.tradingview` locally, not the private
  app's `.env`. Its optional `TRADINGVIEW_DATABASE_URL` lets production use a
  role restricted to `tradingview_alert`. It never runs migrations or
  `create_all()`.

**5. Config (complete)** — private worker settings are documented in
`backend/.env.example`; public ingress settings are isolated in
`backend/.env.tradingview.example`.

**6. Tests**

Completed network/DB-independent foundations:

- `backend/tests/test_tradingview.py`: frozen parser, canonical identity,
  duplicate-key rejection, bounds, timestamps, and golden fixtures.
- `backend/tests/test_tradingview_alert_model.py`: exact numeric round trips,
  constraints, indexes, defaults, and domain isolation.
- `backend/tests/test_tradingview_alert_migration.py`: fresh
  upgrade/downgrade/re-upgrade, existing-table index repair, and malformed
  schema/index refusal.
- `backend/tests/test_tradingview_alert_persistence.py`: insert/duplicate/
  collision semantics, immutable first-delivery evidence, SQLite contention,
  concurrent duplicate delivery, deterministic snapshots, filters,
  pagination, and light-to-full hydration.

Completed HTTP/worker tests:

- `backend/tests/test_tradingview_routes.py` covers fail-closed authentication,
  auth-before-body/DB, Unicode tokens, hard stream bounds, idempotency,
  collision/busy mappings, readiness, public/private topology, and
  type-preserving light/detail DTOs.
- `backend/tests/test_tradingview_analysis.py` covers success/skip/error
  lifecycle, bounded transport/HTTP retries, two-worker claim races, attempt
  fencing, no open DB transaction during market calls, bounded shutdown,
  durable draining, and final-claim lease recovery.

**Cloud note:** `job_run` stores status but is not a task delivery system.
The database makes local pending work durable, but Cloud production still
needs an always-on worker or an actual dispatcher such as Cloud Tasks/Pub/Sub.
Do not claim scale-to-zero Cloud Run readiness until that exists, and never
block the webhook response on analysis.

### Phase 2 — Frontend "Signals" page

- New route `frontend/app/signals/page.tsx` + a `SignalsTable` component (reuse table styling from `TradesTable.tsx`; do not duplicate table logic wholesale).
- Columns: time, symbol, timeframe, setup, side, price, **verdict** (color-coded), confidence.
- Row → detail drawer/page showing the scorer's reasons/trigger/invalidation/targets + the Pine-reported `levels`/`context`.
- Data via `GET /tradingview/alerts`. Add helpers to `frontend/lib/api.ts`.
- Poll on the repo convention: **skip hidden tabs, idle at 30–60s** (match existing status polls). Add a dashboard link.

### Phase 3 — Notifications (optional, only if requested)

Push a verdict to the user when it is actionable (`long_scalp`/`short_scalp`
with an explicit categorical rule such as `confidence == "high"`). Reuse
whatever notification path the app already has; do not add a new external
dependency without asking. Keep it opt-in via env.

---

## Pine indicator spec — "Isaac Market Map"

One Pine **v6 indicator** (`indicator(..., overlay=true)`). Two responsibilities: draw objective structure, and fire JSON alerts. (Any competent Pine author or the pine-script skill can implement from this spec — the JSON contract above is the only thing that must match exactly.)

**Draw (objective, no discretion):**
- Prior-day High/Low/Close via `request.security(syminfo.tickerid, "D", ...)` (use `lookahead=barmerge.lookahead_off`, reference the *previous* daily value — no future leak; same principle as the journal's "prior completed bar" rule).
- Premarket H/L (session `0400-0930` ET) and overnight H/L (`1800-0930`).
- Weekly H/L (`"W"`).
- Opening ranges: first 5 / 15 / 30 min after 0930 ET.
- Session VWAP (`ta.vwap`), EMA 9 & 20 (`ta.ema`).
- Opening gap vs prior close + gap-fill target line.
- ATR zones (`ta.atr`) around a reference (e.g. PDC or OR midpoint).
- RVOL: current cumulative session volume vs N-day average at same time-of-day.
- RS vs SPY: `request.security("AMEX:SPY", timeframe.period, close)` ratio / rate-of-change comparison.
- A small `table` (top-right) showing trend (EMA stack), above/below VWAP, RVOL, RS sign.

**Alert (JSON):** define conditions and call `alert(msg, alert.freq_once_per_bar_close)` where `msg` is `str.tostring`-assembled JSON matching the contract. Conditions:
- `orb_break` / `orb_fail`: close breaks/reclaims the 5m (configurable) OR high/low.
- `vwap_reclaim` / `vwap_loss`: cross of VWAP with EMA-stack confirmation.
- `pdh_break` / `pdl_break`: break of prior-day high/low.
- `retest`: pullback to a broken level holding.

Build `alert_id` with the frozen canonical v1 format using `time_close`.
Version-pinned JSON helpers must emit valid `null` for unavailable values and
escape strings safely; Pine `na` must never produce invalid JSON. Use
`alert.freq_once_per_bar_close` to avoid intrabar spam.

**Alert setup in TradingView UI:** create an alert on the indicator, condition = "Any alert() function call", Webhook URL = `https://<public-host>/tradingview/webhook?token=<TRADINGVIEW_WEBHOOK_TOKEN>`, message = leave blank (Pine supplies the JSON). Requires a paid plan.

---

## Acceptance criteria

**Completed foundation (Steps 1–4):**

1. Frozen v1 parser and golden fixtures pass without network or DB access.
2. `tradingview_alert` is the sole new isolated domain table and the guarded
   migration remains the single Alembic head.
3. Same-ID/same-content persistence is idempotent; same-ID/different-content
   is a visible collision; raw first-delivery evidence is not overwritten.
4. Exact prices, deterministic snapshots, stable light-list pagination, and
   full detail hydration are covered by tests.

**Phase 1:**
1. Authenticated `POST http://localhost:8090/tradingview/webhook` with the
   sample JSON → 200 `{accepted:true, dup:false}`; row exists in
   `tradingview_alert`.
2. Same POST again → 200 `{dup:true}`; still one row.
3. Wrong/missing token (when configured) → 401.
4. Within a few seconds the row's `analysis_status` becomes `done` (including
   closed-market `no_trade`/`wait`), `skipped` (for example Alpaca is not
   configured or the signal is stale), or retryable `error`.
5. `GET /tradingview/alerts` returns the row **without** `payload_json`; `GET /tradingview/alerts/{id}` returns it **with** raw payload + assessment.
6. The `test_tradingview*` suites pass without external network calls.
7. `python -m compileall app` clean; `alembic upgrade head` applies the new migration.

**Phase 2:** `/signals` lists alerts with color-coded verdicts, polls on the hidden-tab/30–60s convention, detail view shows scorer reasons.

## Handoff / housekeeping

- `CLAUDE.md` and `AGENTS.md` describe the Steps 1–4 foundation. Update both
  together again when Pine or the Signals frontend lands.
- Keep the private backend and read APIs off the tunneled/public hostname.
- Keep the MCP surface read-only; if exposing signals to Claude Desktop later, add a read-only `get_signals` tool in `backend/mcp_server.py` (separate task, not this plan).

## Suggested commit slices

1. frozen contract/parser + golden tests + contract docs (complete)
2. model + guarded Alembic migration (complete)
3. persistence/read engine + tests (complete)
4. restricted ingress, private read router, bounded worker, and configuration (complete)
5. Pine v6 indicator (`docs/pine/isaac_market_map.pine`)
6. frontend `/signals`
7. docs (`CLAUDE.md`/`AGENTS.md`) update (ongoing per completed slice)
