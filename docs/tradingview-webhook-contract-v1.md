# TradingView Live Alert Contract v1

Status: frozen on 2026-07-23 and implemented by
`backend/app/engine/tradingview.py`. The golden contract tests live in
`backend/tests/test_tradingview.py`.

This is the wire contract between the Pine indicator and the webhook-only
TradingView ingress. It is deliberately independent from Strategy Lab CSV
metadata and from journal fills/trades.

Step 1 implements bounded raw JSON decoding, parsing, normalization, canonical
identity, raw and semantic fingerprints, and duplicate-key protection. Steps
2–3 add the isolated `tradingview_alert` model, guarded Alembic revision
`2e6f9a1b4c7d`, and `backend/app/engine/tradingview_alerts.py` for atomic
insert-first persistence and light/full reads. Step 4 adds the authenticated
webhook-only ingress, private read routes, and fenced database-backed analysis
worker. There is still no Pine script or Signals UI.

## Payload

Every alert is a JSON object:

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
  "levels": {
    "pdh": 214.45,
    "pdl": 204.51,
    "vwap": 211.10,
    "or_high": 213.9,
    "or_low": 210.2
  },
  "context": {
    "rvol": 1.82,
    "ema9_over_ema20": true,
    "above_vwap": true,
    "rs_vs_spy": 0.31
  }
}
```

Required fields:

- `v`: strict integer `1`. This identifies the wire schema.
- `indicator_version`: Pine logic/configuration revision, separate from `v`.
- `alert_id`: the exact server-derived canonical identity described below.
- `symbol`: normalized to uppercase.
- `timeframe`: normalized to uppercase.
- `setup`: an extensible lowercase slug, not a closed enum.
- `side`: `long` or `short`.
- `price`: a positive, finite JSON number.
- `bar_time_ms`: strict integer UTC epoch milliseconds from Pine
  `time_close`, not the bar-open `time`.

Optional fields:

- `levels`: flat scalar snapshot self-reported by Pine.
- `context`: flat scalar snapshot self-reported by Pine.

Unknown top-level fields are rejected. `levels` and `context` are diagnostic
evidence only; the deterministic verdict will come from current Alpaca data.

## Canonical identity

The only valid v1 idempotency key is:

```text
v1:{indicator_version}:{symbol}:{timeframe}:{bar_time_ms}:{setup}:{side}
```

The server normalizes the identity fields, derives this value, and rejects the
payload unless its supplied `alert_id` matches exactly. Indicator version and
side are included so Pine revisions and opposite-side signals cannot collide.
The wire-version prefix makes the natural key globally unique when v2 exists.

The persistence layer uses `alert_id` as its natural primary key and compares
`content_sha256` when a duplicate arrives:

- same ID and same semantic fingerprint: duplicate delivery;
- same ID and different semantic fingerprint: contract collision, never a
  silent no-op.

## Frozen v1 bounds

- Raw request body: at most 16 KiB, enforced before JSON decoding by the
  webhook receiver.
- `indicator_version` and `symbol`: at most 32 characters.
- `timeframe`: at most 16 characters.
- `setup`: at most 64 characters.
- `alert_id`: at most 200 characters.
- `levels` and `context`: at most 32 entries each.
- Snapshot keys: at most 64 characters and identifier-shaped.
- Snapshot string values: at most 256 characters.
- Numeric values: finite, at most 24 significant digits, at most 12 meaningful
  decimal places after insignificant trailing zeros are removed, and absolute
  magnitude no greater than `10^15`.
- `bar_time_ms`: from 2000-01-01 UTC through, but not including,
  2100-01-01 UTC.
- Snapshot values may be JSON null, boolean, string, or number. Arrays and
  nested objects are rejected.
- Control characters and non-finite values are rejected.

Frozen string formats:

- `indicator_version`: starts alphanumeric, followed only by letters, digits,
  `.`, `_`, or `-`.
- `symbol`: uppercase letters/digits plus `.`, `_`, or `-`; exchange prefixes
  such as `NASDAQ:AAPL` are not accepted.
- `timeframe`: uppercase letters and digits.
- `setup`: lowercase letter followed by lowercase letters, digits, or `_`.
- Snapshot keys: letter followed by letters, digits, or `_`; keys are not
  silently trimmed.

Numeric normalization is Decimal-based. Semantically equivalent JSON numbers
such as `1`, `1.0`, and `1e0` produce the same fingerprint, while the JSON
string `"1"` remains distinct from the number `1`.

## Versioning and future migrations

`v` is an immutable wire-contract version. `indicator_version` identifies the
Pine implementation/configuration that emitted the signal. Every
signal-affecting Pine code or input change must receive a new immutable
`indicator_version`. Such a change does not change `v` when the wire meaning
remains identical.

The following require a new parser and `v: 2`:

- adding or removing a top-level field;
- changing required/optional status, normalization, bounds, or defaults;
- changing field meaning or timestamp semantics;
- changing canonical ID construction;
- changing which values are accepted.

Adding new keys inside the already-extensible `levels` or `context` snapshots
does not require v2 when the existing scalar and size rules still hold.

Future database work must follow these rules:

1. Persist `contract_version`, `parser_revision`, `indicator_version`, exact
   raw payload and raw hash, semantic `content_sha256`, and normalized columns
   including `bar_time_ms`, `bar_time`, `levels`, and `context`.
2. Analyze and read normalized columns. Raw payload is immutable audit
   evidence and is never automatically reparsed with the newest parser.
3. Keep `parse_alert_v1()` and its golden fixtures unchanged while any v1 rows
   exist.
4. Add schema changes with expand → version-pinned/idempotent backfill →
   constraint/contract migrations. Never repurpose an old column.
5. Do not invent v2 values for v1 rows. New version-specific columns start
   nullable unless their value can be derived without changing old meaning.
6. If a corrective backfill is unavoidable, use the original pinned parser,
   preserve previous values, and record the migration revision/time.
7. Persist scorer version separately from webhook and indicator versions.
   Re-analysis must remain auditable and must not reinterpret the incoming
   signal.

Unsupported contract versions are rejected and persist nothing.

## Contract and persistence verification

Run:

```bash
cd backend
.venv/bin/python -m pytest -q tests/test_tradingview.py
.venv/bin/python -m pytest -q \
  tests/test_tradingview_alert_model.py \
  tests/test_tradingview_alert_migration.py \
  tests/test_tradingview_alert_persistence.py \
  tests/test_tradingview_analysis.py \
  tests/test_tradingview_routes.py
.venv/bin/python -m compileall -q app/engine/tradingview.py
```

The tests pin accepted and rejected inputs, UTC conversion, canonical ID,
strict raw decoding, duplicate-key rejection, context-independent Decimal
normalization, immutability, the exact v1 golden fingerprint, schema
upgrade/downgrade and create-all guards, exact Decimal storage, concurrent
idempotency, collision preservation, and egress-safe reads.
The Step 4 suites also pin fail-closed authentication, raw stream bounds,
readiness, public/private route isolation, exact typed detail snapshots, worker
claim races, attempt fencing, retry limits, abandoned-claim cleanup, and
transaction-free market-data execution.
