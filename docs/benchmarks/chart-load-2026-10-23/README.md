# Chart opening history — October 23, 2026

A local production-build comparison using real Tradier candles and Alpaca SIP
history, Chromium headless, 1440×1000, SPY, extended hours and five panels (5m,
15m, 1h, 1D, 1m). Baseline: `0e71e11cf20843af4df0431fba11941d0234dba5`.
Both variants use seeded sandbox records, intercepted browser-local chart
settings and independent empty completed-history directories. Live SSE and news
markers are off; ordinary workspace refreshes remain on. No production records,
settings or caches were changed.

## Results

Seconds from navigation, through a React commit and two animation frames (a
paint opportunity, not pixel-level timing):

| Variant | First candles | All five history-ready | History HTTP responses | Cooldown responses | Cached sessions |
| --- | ---: | ---: | ---: | ---: | ---: |
| Before, cold | 2.383 | 306.171 | 30 | 15 | 153 |
| Before, warm | 0.753 | 1.891 | 3 | 0 | 153 |
| After, cold, preliminary | 1.929 | 7.820 | 4 | 0 | 93 |
| After, warm, preliminary | 0.905 | 1.577 | 3 | 0 | 93 |
| After, cold, final implementation | 1.622 | 8.829 | 5 | 0 | 93 |
| After, warm, final implementation | 0.721 | 1.380 | 3 | 0 | 93 |

The final cold run finished history about **97% sooner** than this baseline,
without reducing the 1,400-candle indicator prefix or increasing the 30-attempt
provider budget. Opening pages return 210/165 candles instead of 1,200; the
backend groups up to five missing sessions per provider range and still stores
validated sessions individually. Scrolling continues to request 1,200 candles.

The preliminary run preceded the final guard preserving a session another panel
completed during a paused batch. The final cold run starts with another empty
cache and includes that guard. Raw JSON files next to this report retain timing,
response and completion data; every run had zero browser page errors.

## Interpretation and limits

These are premarket runs, 08:45–08:57 ET. We compare **history readiness**, not
all enabled studies: the current hourly Tradier tail has fewer than nine bars,
so its enabled EMA-9 remains unavailable even after completed-history warmup is
ready. Both variants exhibit that existing behavior. Four of five panels record
study readiness. No missing study was counted as ready.

One baseline cold run, one final cold run, and an earlier implementation trial
are not a p95, VPS benchmark or guarantee for every symbol. Provider latency,
sparse symbols, regular-only sessions and concurrent users can differ. Warm
measurements reuse the corresponding cold cache. First candles were already
fast; the improvement is in the completed-history path.

## Reproduction and correctness

Use the existing [isolated benchmark instructions](../chart-load-2026-10-22/README.md#reproduce-safely)
with fresh sandbox history directories. For these premarket measurements, a
local copy of `frontend/scripts/chart-load-benchmark.mjs` changed only its exit
condition from five `initial_panel_studies` samples to five
`initial_panel_history` samples, and added
`completionMetric: "initial_panel_history"` to the output. The original study
samples remain present and were not relabeled.

Focused checks cover smaller-page OHLC/VWAP equality and EMA/RSI agreement with
the original warmup tolerance; exact batched-versus-single-session output;
fixed provider pagination bounds, failures and 429 recovery; cache reuse after
restart; DST session windows; missing sessions; and completed-file preservation
between continuations. Browser checks cover opening ranges, partial failures and
retries, six-month scroll-back, retained viewports, symbol changes, midnight
replacement, split-basis refusal and desktop/phone rendering.
