# Chart refresh, cold chart opens and click feedback — October 24, 2026

A follow-up to the [navigation comparison](../navigation-2026-10-24/README.md).
Local only: a production Next.js build, Chromium 1440×1000, the seeded disposable
SQLite backend and invented candles. No real records, settings, provider
credentials or production services were used. Baseline: `25f6cfcc` (main after
#426) with this change's benchmark additions; candidate: this change. Raw samples
are alongside this report.

## Browser results

Milliseconds, median. The same fixed delays as the earlier report: settings GETs
400ms, workspace reads 600ms. `slow` delays journal trades by 2,000ms and the new
`slow_stats` fixture state delays journal statistics by 2,000ms.

| Scenario | Samples per layout | One chart before → after | Five charts before → after |
| --- | ---: | ---: | ---: |
| Reload Charts (this browser has saved settings) | 4 | 1,508 → 1,121 | 1,575 → 1,034 |
| First Charts visit, nothing saved in this browser | 1 | 1,850 → 1,714 | 1,659 → 1,589 |
| First feedback after clicking a page with slow data | 3 | 2,421 → 82 | 2,484 → 51 |
| Dashboard Attention while statistics are slow | 3 | 2,465 → 513 | 2,560 → 400 |
| Dashboard → previously visited Charts | 5 | 251 → 291 | 223 → 190 |
| Return to a recent symbol | 5 | 155 → 101 | 182 → 150 |

- **Reload** saves the settings round trip: candles are requested from this
  browser's saved copy while the server's copy loads. With nothing saved
  locally the chart still waits for the server's copy (the first-visit row is a
  single sample and within noise).
- **Click feedback** is the sidebar/tab link's pending mark (`nav-pending`), or the
  destination heading if that comes first. Before, nothing changed on screen until
  the slow page had rendered.
- **Attention** no longer waits for journal statistics; the journal section
  still does.
- Return visits are unchanged within this machine's noise (before samples ranged
  167–686ms). Workspace HTTP reads per script are unchanged (28).

A first candidate used a root `app/loading.tsx` page placeholder for click
feedback. It also answered in ~70–90ms, but made fast pages slower: React
holds a revealed Suspense fallback for about 300ms, so returning to Charts went
from ~250 to ~480–600ms and the Dashboard's market section from ~100 to
~400–900ms. It was replaced with the link pending mark; a run without the
placeholder restored return visits to 255/344ms.

## Event-loop stall from chart responses

`scripts/benchmark_chart_json.py`: the real `/charts/workspace` route on one
local uvicorn worker, a stubbed feed producing today's 960 minutes resampled to
1m/5m/15m/1h plus 1,200 daily candles (the shapes the route returns), and a file
SQLite database. One client reads the workspace back to back while a tiny async
route is probed every 10ms; the probe delay is what streams and Dashboard
requests wait. Three interleaved trials each (`chart-json.json`).

| Layout (response size) | Workspace read before → after | Probe p95 before → after | Probe max before → after |
| --- | ---: | ---: | ---: |
| One symbol (0.74 MB) | 47–55 → 18–21ms | 32–37 → 7–9ms | 116–177 → 14–23ms |
| Plus two held symbols (0.88 MB) | 64–73 → 29–34ms | 28–31 → 16–24ms | 39–189 → 30–57ms |

Before, FastAPI ran `jsonable_encoder` over every candle on the event loop after
the handler returned. The route now writes the same JSON in its worker thread.
Building the candles still holds Python's interpreter lock, so other requests
are not entirely unaffected; the stall is shorter, not gone. Absolute numbers
are from an Apple-silicon laptop; the VPS CPU is likely slower, which makes the
removed work larger there, not smaller.

## Not measured

Live provider latency, the production machine, phone networks and the Tradier
quote connection reuse (no provider is called offline; `test_market_http.py`
covers that the POST reuses the pool without sharing credentials or cookies).

## Reproduce

From `frontend/`, sequentially, one variant at a time:

```sh
TJ_NAV_BENCHMARK=/tmp/navigation-results npx playwright test e2e/navigation-performance.spec.ts
```

From the repository root:

```sh
backend/.venv/bin/python scripts/benchmark_chart_json.py
```

`BENCH_READERS=2` runs two back-to-back readers instead of one.
