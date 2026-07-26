# Plan: TradingView → Webhook → Scalp-Verdict Loop ("Isaac Market Map")

**Audience:** a coding agent (Codex) implementing this cold. Everything needed is in this doc plus the referenced files. Read the referenced files before writing code; do not guess signatures.

> **Implementation status (2026-07-23):** Step 1 is complete. The frozen v1
> wire contract, migration policy, and exact bounds are canonical in
> `docs/tradingview-webhook-contract-v1.md`; the pure implementation and
> golden tests are `backend/app/engine/tradingview.py` and
> `backend/tests/test_tradingview.py`. No model, migration, route, worker,
> Pine script, or frontend signal page exists yet.

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
  └─ on trigger: alert() sends JSON  ──HTTPS POST──►  FastAPI  POST /tradingview/webhook?token=SECRET
                                                        1. verify shared-secret token
                                                        2. persist raw alert (idempotent)
                                                        3. return 200 fast
                                                        4. background: build_scalp_analysis(symbol, side)
                                                           → store verdict/confidence/assessment on the row
Frontend "Signals" page  ◄──GET /tradingview/alerts──  (poll, hidden-tab-skip, 30–60s)
```

The webhook-only ingress must be **publicly reachable** (TradingView cannot hit
`localhost`). The existing TradeJournal API has no general authentication and
must remain private:

- **Local/dev:** tunnel a dedicated ingress port, not the full backend on
  `8000`/`8080`.
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

**1. Model** — add to `backend/app/models.py`, mirroring `WebullRawEvent` (natural-key PK idempotency):

```python
class TradingViewAlert(SQLModel, table=True):
    __tablename__ = "tradingview_alert"
    alert_id: str = Field(primary_key=True)          # canonical v1 identity
    contract_version: int
    parser_revision: str
    indicator_version: str
    content_sha256: str
    raw_payload_sha256: str
    symbol: str = Field(index=True)
    timeframe: str
    setup: str = Field(index=True)
    side: str                                         # "long" | "short"
    price: Decimal
    bar_time_ms: int
    bar_time: datetime = Field(index=True)
    received_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    payload_json: str = Field(sa_column=Column(Text, nullable=False))   # raw body
    levels_json: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    context_json: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    # analysis result (best-effort, filled in by background pass)
    analysis_status: str = Field(default="pending", index=True)  # pending|running|done|skipped|error
    analysis_attempts: int = 0
    analysis_started_at: Optional[datetime] = None
    analysis_completed_at: Optional[datetime] = None
    verdict: Optional[str] = None                     # no_trade|wait|long_scalp|short_scalp
    confidence: Optional[str] = None                  # low|medium|high
    assessment_json: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    analysis_error_code: Optional[str] = None
    analysis_error: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
```

Add an Alembic migration (new revision off current head `f1a2b3c4d5e6`, or whatever `alembic heads` reports) that creates `tradingview_alert`. Do not reuse an existing revision.

**2. Engine** — `backend/app/engine/tradingview.py`. Keep the network-free logic **pure and testable** (same split as `score_scalp` vs `build_scalp_analysis`):

- `parse_alert_bytes(raw_body)` performs the frozen bounded UTF-8/JSON
  decoding, preserves decimals, rejects duplicate keys, and dispatches to
  `parse_alert()` / `parse_alert_v1()`. The future router must use it instead
  of `request.json()`.
- `persist_alert(session, parsed, raw_body) -> tuple[TradingViewAlert, bool]`
  must insert atomically, catch an `IntegrityError`, compare the stored
  semantic fingerprint, and distinguish duplicate from collision.
- `run_analysis(alert_id) -> None` owns its sessions. It claims work in one
  short transaction, closes the session during `build_scalp_analysis()`, then
  opens another short transaction to persist only the assessment. Missing
  Alpaca configuration is `skipped`; network/retry exhaustion is a retryable
  `error`; a closed market is a normal completed `no_trade`/`wait` result.

**3. Router** — `backend/app/routers/tradingview.py`, thin, copying `gmail_push.py` almost verbatim for token verification:

- `_verify_webhook_token(token, authorization)` reads
  `TRADINGVIEW_WEBHOOK_TOKEN` and fails closed when it is unset. Compare in
  constant time. Accept token via `?token=` or `Authorization: Bearer`.
- `POST /tradingview/webhook` — verify token → bound/read body → parse →
  persist → dispatch only newly created or recoverable work. Use a bounded
  one-worker local queue with startup recovery, not one thread per alert.
  Return 200 on a true duplicate so TradingView stops retrying.
- `GET /tradingview/alerts?limit=50&offset=0&symbol=` — light list DTO: everything **except** `payload_json`/`assessment_json`/`levels_json`/`context_json`. Newest first.
- `GET /tradingview/alerts/{alert_id}` — full detail incl. raw payload + parsed assessment.

Return Pydantic DTOs, never the raw SQLModel row in the list (egress discipline).

**4. Register** — in `backend/app/main.py`, add to the import line and:
```python
app.include_router(tradingview.router, prefix="/tradingview", tags=["tradingview"])
```

**5. Config** — `TRADINGVIEW_WEBHOOK_TOKEN` in `.env` (loaded via the existing `.env` precedence). Document it.

**6. Tests** — `backend/tests/test_tradingview.py`, network-free (mirror `test_scalper.py`):
- `parse_alert` happy path + malformed (missing `alert_id`, bad `v`, bad `bar_time_ms`).
- Idempotency: two posts with same `alert_id` → one row, second returns `dup=true` (use `TestClient`; monkeypatch `run_analysis` to a no-op so no Alpaca call).
- Token: wrong/missing request token → 401; no server token configured →
  endpoint disabled with 503 and nothing persisted.

**Cloud note:** `job_run` stores status but is not a task delivery system.
Cloud production needs an actual durable dispatcher such as Cloud Tasks or
Pub/Sub. Do not claim Cloud Run readiness until that exists, and never block
the webhook response on analysis.

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

**Phase 1:**
1. `curl -X POST 'http://localhost:8080/tradingview/webhook?token=T' -d '<sample JSON>'` → 200 `{accepted:true, dup:false}`; row exists in `tradingview_alert`.
2. Same POST again → 200 `{dup:true}`; still one row.
3. Wrong/missing token (when configured) → 401.
4. Within a few seconds the row's `analysis_status` becomes `done` (including
   closed-market `no_trade`/`wait`), `skipped` (for example Alpaca is not
   configured or the signal is stale), or retryable `error`.
5. `GET /tradingview/alerts` returns the row **without** `payload_json`; `GET /tradingview/alerts/{id}` returns it **with** raw payload + assessment.
6. `pytest backend/tests/test_tradingview.py` passes (no network).
7. `python -m compileall app` clean; `alembic upgrade head` applies the new migration.

**Phase 2:** `/signals` lists alerts with color-coded verdicts, polls on the hidden-tab/30–60s convention, detail view shows scorer reasons.

## Handoff / housekeeping

- Update `CLAUDE.md` **and** `AGENTS.md` together when this lands (new router, model, migration, env var, `/tradingview/*` routes) — repo rule.
- Add `TRADINGVIEW_WEBHOOK_TOKEN` to `.env.example` if one exists.
- Keep the MCP surface read-only; if exposing signals to Claude Desktop later, add a read-only `get_signals` tool in `backend/mcp_server.py` (separate task, not this plan).

## Suggested commit slices

1. frozen contract/parser + golden tests + contract docs (complete)
2. model + guarded Alembic migration
3. persistence/read engine + tests
4. restricted ingress, private read router, bounded worker, and configuration
5. Pine v6 indicator (`docs/pine/isaac_market_map.pine`)
6. frontend `/signals`
7. docs (`CLAUDE.md`/`AGENTS.md`) update
