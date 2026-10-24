# Navigation and first-useful-content comparison — October 24, 2026

Local production Next.js build (webpack), Chromium, 1440×1000, seeded disposable
SQLite, invented realistic candles. Baseline application: `31acf806`; candidate:
this PR's application code including restored-history recovery and midnight fixes.
Both variants ran the same `frontend/e2e/navigation-performance.spec.ts` sequentially
on the same machine. No real records, settings, provider credentials or production
services were used. Raw samples are alongside this report.

## Results

Milliseconds, median where repeated. A usable chart means the requested symbol's
chart with nonempty candles and no pending overlay, followed by two animation
frames. This measures a paint opportunity, not pixel presentation or trackpad feel.

| Scenario | Samples per layout | One chart before → after | Five charts before → after |
| --- | ---: | ---: | ---: |
| Initial chart / hard reload, no in-memory snapshot | 5 | 1,483 → 1,516 | 1,517 → 1,521 |
| Dashboard → previously visited Charts | 5 | 1,425 → 159 | 1,429 → 159 |
| Symbol B → previously visited A | 5 | 909 → 101 | 901 → 103 |
| Dashboard filter change | 4 | 916 → 100 | 438 → 101 |
| New symbol, slow supporting context | 1 | 2,385 → 908 | 2,413 → 880 |
| Dashboard market section, slow journal | 1 | 2,409 → 129 | 2,389 → 95 |

The repeat-visit improvement is restoration of a visibly labeled snapshot, **not**
faster fresh provider data. The app still refreshes timestamps and values from
the server. Initial loads with equal service latency did not improve; the
progressive path helps when supporting context is slower than candles. The two
slow-component cases have only one observation per layout; these are neither
production estimates nor p95s. Across each complete script, full document reads
fell from 10 to 6: five deliberate initial loads and the deliberate slow-journal
load remain, while four filter reloads disappear. Workspace HTTP reads increased
from 21 to 28 per script because cold requests now split candles and context.
The shared provider cache coalesces their overlapping minute read; this is an
explicit application-request tradeoff, not a claim of fewer total requests.

## Controlled workload and limitations

Settings GETs have a fixed 400ms delay; workspace requests have a fixed 600ms
delay. For the new AMD symbol, full supporting-context responses take 2,000ms,
while the new prices-only response remains at 600ms. The existing isolated
backend's `slow` fixture delays journal trades by 2,000ms. Requests for full
context still run: the benchmark waits for normal background refresh before
moving to the next measured step. One/five layouts share candles and settings;
the first-chart metric concerns the selected chart, not all-study readiness.

The timing includes Playwright actions/readiness assertions and thus some polling
and automation overhead. The charts already contain 240 bars per interval; this
benchmark does **not** remeasure cold historical provider downloads, deep-history
warmup, broker entitlement, auth-network latency, production hardware, or real
trackpad gestures. Existing October 23 history measurements remain separate.
All final benchmark samples completed without browser page errors. An earlier
experimental sequential candle/context path was discarded because it added a
round trip; the final path runs the two requests together and refuses late
primary overwrites. Full-data polling remains at its existing 15s cadence and
server TTLs/budgets remain unchanged.

## Integration transport

`http-pool.json` records five trials of 12 sequential reads against a disposable
local HTTP/1.1 server. Top-level HTTPX used 12 connections per trial; the pooled
transport used one. Median elapsed time was 74.332ms → 17.426ms. This verifies
connection reuse and local overhead only: there is no TLS or real provider,
so these numbers must not be presented as live integration speed gains.
Per-request headers/timeouts remain explicit; cookies and authorization are not
inherited across requests. Existing chart request locking/cache coalescing,
rate budgets, cooldowns and history indicator prefix are unchanged.

## Reproduce

Use a clean worktree without environment files and the existing Playwright seeded
backend/production frontend configuration. From `frontend/`:

```sh
TJ_NAV_BENCHMARK=/tmp/navigation-results npx playwright test e2e/navigation-performance.spec.ts
```

The benchmark is skipped unless the output directory is explicitly provided.
For a linked external `node_modules` installation, use webpack in the existing
config's build command; the recorded run used a temporary config importing the
normal config and changing only that command, absolute test/output paths, and
unused localhost ports. Do not run the before/after benchmarks concurrently.
The same test file must be copied into the baseline checkout.

From the repository root, the offline transport comparison is:

```sh
backend/.venv/bin/python scripts/benchmark_market_http.py
```

Correctness regressions cover exact restored candle/viewport equality, history
paging and failure disclosure during a failed workspace refresh, midnight across
a restored snapshot's first fresh response, expiration/bounds, settings conflict
reconciliation, and refusal to mix split bases. Desktop/phone realistic-chart
pictures and Dashboard loading/error/filter checks use the existing browser suite.
