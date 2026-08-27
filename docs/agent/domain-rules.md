# Domain rules

Invariants that must survive any change. These are the canonical copy — this
is the file to update when a rule changes.

Highest-risk areas, where extra care is warranted: PnL math, FIFO
reconstruction, Gmail/email parsing, fill dedupe, account identity,
reconciliation outputs, nullable enrichment fields, and frontend data-fetch
patterns that can create N+1 calls.

## Fills and trades

- `fill` is the source layer. `trade` and `tradefill` are derived and are safe
  to wipe and rebuild.
- `contracts` is the quantity field for **both** stocks and options.
- Stock quantities may be fractional.
- Option `price` is total premium **per contract in dollars** — divide by 100
  for a per-share price before passing it to Black-Scholes.
- Stock `price` is per share.
- `raw_email_id` is the dedupe key for imported fills. Manual fills use
  `manual:` prefixes, Webull fills use `webull:{event_id}`.
- Manual fills are backed up to `backend/data/manual_fills.json` and restored
  on startup and after a destructive resync.
- The FIFO sort key is
  `(executed_at, opens-before-closes, str(fill.id))`. Opens must sort before
  closes at equal timestamps, or a close is orphaned and its entry lots get
  written off as expired worthless.

### Known: same-timestamp ordering is arbitrary

When two fills share an `executed_at` **and** are both opens (or both closes),
FIFO order is decided by `str(fill.id)`, a random UUID. It is stable for a
given set of fill rows, so ordinary rebuilds reproduce the same PnL. It is not
stable across a destructive resync, which re-imports fills with new ids — so
realized PnL attribution for same-second fills can change after
`POST /fills/resync-all`. Multiple prints of one order at the same second are
common. Changing the tie-break is a PnL-semantics decision, not a cleanup.

## Accounts

- Roth IRA `8267` and Individual `1113` are the live accounts.
- Roth fills with a blank `last4` are merged into canonical `8267` at startup.
- `account.last4` is unique; account identity bugs are a known live issue class.

## Email import

- Partial-fill Robinhood option emails are **deliberately skipped**. They
  report cumulative filled counts, so a 3-of-13 email followed by the final
  13-of-13 email would import 16 contracts. Only `"Option order executed"` is
  in `OPTION_SUBJECTS`. See `backend/scripts/find_phantoms.py`.
- The poller still lists partial-subject message ids; they are dropped at parse
  time. Their ids are not recorded as seen, so each sync re-fetches them.

## Enrichment

- Every enrichment field is nullable. Guard before display, calculation, or
  putting it in an AI prompt.
- "At fill" daily indicators — both the Polygon columns on `fill` and the
  Alpaca fields on `fill_market_context` — intentionally use the last completed
  daily bar **strictly before** the fill date. The fill day's own daily value is
  computed on that day's close and would leak the future. Same for hourly EMA-9
  (prior completed hour). **Do not "fix" this back.**
- Polygon minute/hour bar keys use real America/New_York conversion via
  zoneinfo. Fills enriched before that fix during EST months are one hour early;
  a forced re-enrich corrects them from cache.
- Alpaca daily cache validity must cover the requested date **range**, not
  merely be young by file age. Stale coverage is the usual cause of missing
  RSI/EMA/MACD/ATR on recent trades — check it before touching indicator math.
- Sequence metrics on `fill_market_context` derive from `trade` rows, so trades
  must be rebuilt **before** Alpaca enrichment runs.
- Greeks PnL attribution on `trade_path_metrics`
  (`attr_delta/gamma/theta/vega/residual_pnl`, plus `entry_iv`/`exit_iv`)
  depends on Polygon-enriched entry/exit greeks: run Polygon enrichment before
  the path job. Attribution fields are options-only and all nullable.
- The dashboard's Alpaca "All history" control must send
  `range=all&force=true`. `force` alone only reprocesses the selected range.
- Cache markers: empty Polygon responses are cached as
  `{"_empty_cached_at": ts}` (1 year for finalized history, 7 days for
  indicator series). Delete the file to force a retry.
- Live "today" data must use `fetch_snapshots` / `fetch_minute_bars_live`,
  never the cache. The persistent minute cache never expires and must not be
  written with partial intraday data.

## Rebuilds

- Normal rebuilds **reuse** trade path metrics. `_rebuild_trades()` snapshots
  `trade_path_metrics`, rebuilds, then re-inserts only rows whose
  `inputs_fingerprint` still matches. Use
  `_rebuild_trades(..., preserve_path_metrics=True)` for incremental rebuilds.
- Only destructive resync paths, which re-import fills with new ids, may call
  `_clear_derived_trade_data` + `_persist_rebuild` directly.

## Sync pipeline

- The full pipeline runs Gmail sync, fill check, rebuild, Polygon, Alpaca and
  trade-path work. It skips the rebuild step when Gmail saves 0 new fills.
- Polygon enrichment is launched in the background: pipeline success does
  **not** mean Polygon finished. Check `GET /fills/enrich/status` separately.
- Daily review is intentionally **not** part of "Sync Everything" or the Gmail
  push pipeline. It runs only on explicit request. Do not re-add it.
- `webull_listener` is a persistent listener, not a finite sync job.

## Strategy Lab

- A `strategy_version` with any `strategy_run` is locked for Pine source,
  parameters, and result-affecting assumptions. Fork it to test a change;
  status and research annotations may still change.
- Import is a non-persistent preview followed by a commit that re-uploads the
  same bytes and verifies source, version and preview fingerprints.
- Source timestamps require an explicit IANA timezone and are normalized to UTC.
- Simulated rows never enter `fill`, `trade`, or `tradefill`.

## TradingView live alerts

- Wire `v` is the immutable wire-schema version and is distinct from Pine
  `indicator_version`.
- `parse_alert_v1()` and its golden fixtures are **frozen** while v1 data
  exists. Changed fields, meaning, canonical identity, timestamp semantics or
  acceptance rules require a new wire version. Never reparse stored v1 payloads
  with a future "current" parser.
- `alert_id` is the sole idempotency key. Equal semantic hashes are retries even
  when raw bytes differ; the same id with a different semantic hash is a
  collision and must never overwrite first evidence.
- `persist_alert()` commits or rolls back the session it is given — pass a clean
  request-scoped session with no unrelated pending writes.
- Analysis claims commit **before** market-data calls, and `analysis_attempts`
  is a fencing token: a stale worker must never overwrite a newer attempt.
  Generic scorer/code failures are terminal, not retried.
- Keep analysis network calls outside database transactions.
- Query-token auth is required by TradingView but leaks through access logs.
  Keep ingress/proxy/tunnel request-target logging disabled or redacted, and
  rotate the token if exposed.
- Future schema work uses expand → version-pinned idempotent backfill →
  constraint migration.

## Database access patterns

- Every multi-row `select(Fill)` must pass `.options(*FILL_LIGHT)` (from
  `app.models`), and fill-returning endpoints must respond with `FillOut`, never
  a raw `Fill`. `fill.email_subject` / `email_body_text` are legacy write-only
  payloads; FastAPI dumping all model fields lazy-loads one email body per row,
  and egress is metered on Neon.
- `GET /fills` takes `limit` (default 2000) and `offset`.
- On SQLite, avoid long write transactions in historical jobs, or `job_run`
  progress updates hit "database is locked".
