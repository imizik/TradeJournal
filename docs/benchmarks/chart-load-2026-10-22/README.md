# Chart opening-load baseline — October 22, 2026

Measured locally on a production Next.js build (webpack), Chromium headless,
1440×1000, real Tradier candles and Alpaca historical SIP. Base code:
`025a739135d9bb8c15873b7430c39b7c5174871d`, plus this PR's timing instrumentation.
No loading algorithm, history size, study calculation, provider limit or lock
lifetime changed. Sandbox SQLite held only seeded records; settings were
intercepted in the browser. No production settings or history cache was changed.

## Results

All times are seconds since navigation, through a React commit and two animation
frames. This is a paint opportunity, not pixel-level paint timing. Each run used
a new browser context. Symbol SPY, extended session; one panel = 5m; five panels
= 5m, 15m, 1h, 1D, 1m. Default studies (including the existing compact-panel
reductions), one-symbol watchlist, news markers and live SSE off in all cells.
The regular-session live clock and 15-second REST refresh remained active.

| Panels / history | Runs | First candles | All studies ready |
| --- | ---: | ---: | ---: |
| One / initially cold | 1 | 2.810 | 2.810 |
| One / subsequent visits | 2 | 0.205–0.864 | 0.205–0.864 |
| Five / cold completed history | 1 | 0.405 | 303.620 |
| Five / saved completed history | 2 | 0.313–1.143 | 1.262–2.129 |

**Caveat:** the 5m-only view needed no completed-session history in this afternoon
session. Its cold/warm difference therefore measures workspace/provider-cache
startup, not historical paging. The initial one-panel visit also warmed daily,
calendar and split metadata; five-panel cold means an empty **completed-minute
history** cache, not an empty cache for every provider. The five-panel first-paint
advantage is not evidence that five panels render faster. This is one cold
sample and two warm samples per layout, not a p95 or a production/VPS benchmark.

On the cold five-panel run, all five panels showed their first candles at
0.405s. The 15m panel's studies became ready at 65.571s; 1h finished at 303.620s.
The fresh completed-history cache ended with **153 session files**. There were
33 history HTTP responses (including continuation/cooldown responses), 21 of
which reported the existing `rate_limited` state. Warm visits each needed two
history responses and **zero historical provider-download time**.

The 1h critical path from first history request through last response:

| Component | Seconds | Interpretation |
| --- | ---: | --- |
| Browser gaps between history attempts | 260.602 | 257.242s after rate-limit responses; 3.360s after pending responses |
| Historical provider GETs | 31.650 | Network reads inside the history handler |
| Waiting for the shared history lock | 6.748 | Actual contention, but much smaller than cooldown time |
| History resampling | 0.689 | Building timeframe bars from minutes |
| History cache reads/validation | 0.111 | Completed-session cache access on this cold path |
| Final indicator calculation | 0.006 | Final history warmup calculation; resampling also computes studies |

These nested measurements are not independent wall-clock buckets: the history
responses also included calendar reads, parsing, normalization, cache writes,
SQL marker reads, serialization and transport. The 1h request sequence lasted
303.216s, of which 42.614s was in active HTTP requests and 260.602s was between
requests. Across all panels, summed history-lock wait was 11.279s; that sum is
not additional time on top of the 1h critical path.

**Conclusion:** the evidence supports reducing unnecessary opening-history work
before changing concurrency. Preserving the 30-requests/minute budget means a
lock-only change cannot eliminate the roughly five-minute cold warmup. Warm
five-panel history work took roughly one additional second after first candles.
The initial 1,200 + 1,400 target and study-aware warmup deserve a separate,
correctness-checked proposal. This experiment does not establish the benefit of
any unimplemented optimization.

## Evidence and measurement limits

The six JSON files beside this report contain per-panel samples, request timings,
Server-Timing values, history issues and completion state. All six runs completed
without browser page errors. Provider payloads, credentials and real journal
records are not included. The experiment ran at approximately 14:54–15:03 ET.
Screenshots were inspected locally; sandbox banners are expected fixture state.

The real-data runs preceded two diagnostic-only review refinements: treating
extended-hours VWAP as intentionally absent and adding a separate
`initial_panel_history` metric. These regular-session samples are unaffected;
the retained JSON therefore has no history-ready metric. The final browser
regression covers the extended-hours case. Neither refinement changes loading.
Current tail-study calculations can leave some enabled studies unavailable even
when history is ready; absence of a study-ready sample must remain visible,
not be reclassified as success.

## Reproduce safely

Use a clean worktree, existing installed dependencies and an explicit market-data
key file. The backend runner imports only allowlisted market-data credentials,
clears other inherited environment settings, disables background jobs and binds
localhost. It refuses a checkout containing environment/credential files and
requires its history directory inside the sandbox. Never delete the real cache.

From the worktree, start the backend using the project virtualenv Python:

```sh
/path/to/python scripts/chart_load_benchmark_backend.py \
  --keys-from /path/to/main-checkout/backend/.env \
  --history-dir "$PWD/backend/data/ux_sandbox/history-trial-1"
```

In `frontend/`, build and serve the production frontend:

```sh
NEXT_PUBLIC_API_URL=/api/backend API_PROXY_TARGET=http://127.0.0.1:8198 API_INTERNAL_URL=http://127.0.0.1:8198 npx next build --webpack
PORT=3198 NEXT_PUBLIC_API_URL=/api/backend API_PROXY_TARGET=http://127.0.0.1:8198 API_INTERNAL_URL=http://127.0.0.1:8198 npm run start
```

Then, in another terminal from `frontend/`:

```sh
node scripts/chart-load-benchmark.mjs http://127.0.0.1:3198 single /tmp/one-cold.json
node scripts/chart-load-benchmark.mjs http://127.0.0.1:3198 single /tmp/one-warm.json
node scripts/chart-load-benchmark.mjs http://127.0.0.1:3198 multi /tmp/five-cold.json
node scripts/chart-load-benchmark.mjs http://127.0.0.1:3198 multi /tmp/five-warm.json
```

Check whether the one-panel run itself downloaded history before calling the
five-panel cache cold (the afternoon baseline did not). To isolate another cold
trial, stop the backend and restart with a **new** sandbox history directory.
Keep existing completed files for warm trials. Do not reset provider budgets
while downloads are active. The optional arguments after the output path are
timeout seconds (default 1,200) and main interval (`5m` or `1h`). A timeout is an
incomplete measurement; the JSON retains `completed:false` and any issues.
