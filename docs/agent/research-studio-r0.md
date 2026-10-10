# Research Studio R0: evidence and bounded R1 contract

**Selected by the user on 2026-10-10; probes completed on the Mac.** This
selection advances R0 ahead of additional S1–S2 work only. R1 was subsequently selected; see the [current R1 contract](research-studio-r1.md).
R2–R4 remain unselected. R0 introduced no Studio route, event engine, worker,
schema or Factory adapter. This is the evidence slice of the
[revised roadmap](../strategy-workbench-roadmap.md#small-delivery-phases).

## Finding

A discovery-only event lab is feasible on the existing Mac cache. It cannot
promise the nominal 18-symbol universe, full daily-history quality or measured
end-to-end analysis latency. NBIS has no approved-period files; six other
names have minute gaps. A conservative daily-history rule leaves LLY, GS and
CAT with no eligible ATR windows. Start with available names and honest
feature-specific exclusions, without a provider fetch or a protocol change.

The existing `BarStore.load` is unsuitable: `_bars` opens/builds all source
dates and only then truncates. Its pickle may contain protected dates and
its invalidation checks the latest date rather than content. Neither those
pickles nor Factory evidence/run caches were opened in this audit.

## Source and boundary evidence

Source checkout inspected: `48fd47c`. Approved cache host: the existing Mac,
`/Users/user/TradeJournal/backend/data/alpaca_cache/stocks/1Min/sip`.
The documented factory checkout links to this same cache; this worktree had
no local cache. IEX also exists as a directory but its payloads were not read.
No VPS data, journal database, ledger, confirmation/exam payloads, provider
API or model API was used.

The audit enumerated filenames and selected **2023-06-01 through 2024-09-30
before opening any file**. June is warm-up only; events start 2023-07-03.
It opened 6,030 JSON files across 17 targets plus SPY. All payload timestamps
were checked against their filename day; no wrong-day timestamps occurred.
Outside-window filenames were not treated as permission to open payloads.
The pure Factory modules were imported directly; `AlpacaCache`, the Alpaca
module with its import-time cache-directory creation, and `BarStore` were
not instantiated.

Feed provenance is **directory label SIP and current writer code**, not a
supplier-certified receipt: minute files have no embedded feed/adjustment
metadata. `fetch_minute_bars_for_date` requests `adjustment=raw`. The pure
Factory preparation inferred NVDA 10:1 on 2024-06-10 and AVGO 10:1 on
2024-07-15 from approved bars. No other split was inferred. Dividends are
not adjusted. These inferences do not independently verify corporate actions;
no split-policy change or later-date split information is introduced.

Source content manifest identity:
`e7476745147a47d5ba251403dab50a1219a9c6b8891bf5154d153123fabdd350`.
Each entry is `[symbol, filename, byte_length, SHA256(payload_bytes)]`, ordered
SPY then `CORE_UNIVERSE`, ascending filenames within each name; identity is
SHA256 of compact JSON with separators comma/colon. This covers warm-up too.
Generated manifests and probe output remain in temporary storage.

## Observed coverage

SPY has 314 discovery sessions. Those dates supply the audit's expected-session
set; this is a cached-SPY cross-check, **not an independent exchange-calendar
reconciliation**. Session hours use the current Factory early-close table:
2023-07-03, 2023-11-24 and 2024-07-03 close at 13:00 ET; otherwise 16:00 ET.
Each covered symbol has 335 files, 21 June warm-up sessions and all 314
SPY discovery dates, spanning 2023-06-01 to 2024-09-30. NBIS has zero files
in the approved interval and is unavailable, not a zero-event result.

Completeness checks require one timestamp at each scheduled minute open,
finite positive OHLC, consistent high/low and finite nonnegative volume.
Zero volume is valid. Five-minute buckets require all five minute opens.
No discovery duplicates, off-grid timestamps or invalid OHLCV were found.
A missing minute is an observation gap; the audit cannot distinguish a
no-trade minute from a provider omission. It never synthesizes a price.

| Name(s) | Missing discovery minutes per name | Complete 5m buckets per name | Partial 5m buckets per name | Sessions lacking exact 09:30 open |
|---|---:|---:|---:|---:|
| SPY; MU, META, AAPL, AMD, TSLA, GOOG, AMZN, NVDA, MSFT, MRVL, PLTR | 0 | 24,384 | 0 | 0 |
| LLY | 1,272 | 23,225 | 1,159 | 17 |
| NFLX | 511 | 23,906 | 478 | 0 |
| AVGO | 1,997 | 22,669 | 1,715 | 0 |
| COIN | 8 | 24,376 | 8 | 0 |
| GS | 2,518 | 22,249 | 2,135 | 0 |
| CAT | 1,318 | 23,185 | 1,199 | 0 |
| NBIS | unavailable | unavailable | unavailable | unavailable |

Covered names have no wholly absent discovery buckets and no missing scheduled
last-minute close. Complete five-minute bars can still be ineligible for a
horizon or a feature. The following is an **all-complete-decision-bar endpoint
probe**, not event N: require the next complete bucket open and the exact
bucket close at reference +15/+30/+60 minutes, or scheduled session close.
No first-match rule, condition, daily warm-up or SPY feature gate is applied.

| Name(s) | 15m | 30m | 60m | Session close |
|---|---:|---:|---:|---:|
| Every fully complete name above, including SPY | 23,442 | 22,500 | 20,616 | 24,070 |
| LLY | 20,497 | 19,541 | 17,748 | 21,961 |
| NFLX | 22,171 | 21,223 | 19,372 | 23,176 |
| AVGO | 19,437 | 18,496 | 16,733 | 21,111 |
| COIN | 23,418 | 22,476 | 20,592 | 24,054 |
| GS | 18,636 | 17,708 | 15,913 | 20,432 |
| CAT | 20,420 | 19,462 | 17,665 | 21,896 |

### Warm-up sensitivity

Twenty-one prior observations suffice for nominal ATR14/EMA20 seeding, but
not the roadmap's 25-session trend-slope history. On otherwise complete
names the first nominal slope day is July 10; July 3/5/6/7 are excluded.
SPY and PLTR also have four missing June 5 minutes. June sessions with any
missing minute: SPY/PLTR 1 each, LLY 19, AVGO 14, GS 18, CAT 9; others 0.

A separate strict-quality probe required every minute in each of the preceding
14/20/25 scheduled cached sessions. It did not reset or recalculate indicators.
These counts are quality-mask sensitivity evidence, not verified feature values
or joint event eligibility:

| Name(s) | Prior 14 complete sessions | Prior 20 | Prior 25 |
|---|---:|---:|---:|
| MU, META, AAPL, AMD, TSLA, GOOG, AMZN, NVDA, MSFT, MRVL | 314 | 314 | 310 |
| PLTR; SPY | 314 | 312 | 307 |
| COIN | 255 | 243 | 229 |
| NFLX | 25 | 10 | 4 |
| AVGO | 50 | 44 | 39 |
| LLY, GS, CAT | 0 | 0 | 0 |

This exposes a material tradeoff: accepting observed daily extrema preserves
more observations but cannot claim a complete daily range. The bounded R1
contract below chooses conservative availability masks while preserving shared
calculations. EMA/Wilder state also carries older history beyond its nominal
lookback; the mask is not proof of full-history indicator accuracy. Disclose
this limitation rather than describing every retained value as pristine.

## Bounded feasibility measurements

All times are single-host observations, with the Mac's existing filesystem
cache state. “Cold” means a fresh process without prepared research columns;
OS cache was not flushed. No concurrency/load or VPS performance claim follows.

| Probe | Observed |
|---|---|
| File read, SHA256, completeness audit, resample and `Series.build` | 17.834 s |
| `FeatureContext` preparation and three timing columns over 414,528 target bars | 0.389 s |
| Warm minute/RVOL/ATR population scan, 20 repeats | Median 9.27 ms; max 10.80 ms |
| Peak Python RSS for that audit/preparation process | 249,839,616 bytes (238.3 MiB) |
| Synthetic joint weekly weighted-comparison proxy, 2,000 draws, 3 repeats | 0.289–0.295 s |
| Separate proxy process peak RSS | 53,755,904 bytes (51.3 MiB) |
| Static 78-candle chart setup in Chromium | 14.1 ms |

The population timing counts 11,535 raw qualifying bar rows in a
10:00–11:30 ET close window at RVOL >=1.5 and positive prior ATR. This is a
workload size, not a research result or first-per-session population. It uses
existing Factory calculations on available buckets and omits Studio quality
masks. The stop-requiring `FeatureContext.at` was never called.

The comparison proxy uses seeded synthetic arrays of 66 weeks ×17 names ×78
clock buckets, 100 draws per batch, 20 batches, one BLAS thread. Each draw
resamples weeks jointly and recomputes event/control clock-composition weights.
It benchmarks one numerical workload, not uncertainty correctness or a
completed Studio run. A provisional cold-run engineering estimate is about
19–30 seconds on this host; source work dominates the measured components.
Actual outcomes, baseline construction, hashing/cache reopen, serialization,
job lifecycle and cancellation are still unmeasured. R2 must measure the
completed run independently; summing these probes is not acceptance evidence.

Temporary Chromium fixture uses the installed Lightweight Charts 5 foundation,
synthetic July 5 candles and a separate static adapter, not the live component.
Actual mouse click selected the marker's timestamp, one occurrence marker
rendered, wheel zoom narrowed the logical span from 77 to 69.91 bars, and data
remained unchanged over a one-second observation. No page network requests
occurred. Screenshot inspected. This proves static foundation feasibility,
not React integration, live-store isolation or human usefulness. `PriceChart`
imports `useClock`/`useLivePanel`; reusing it intact is not proposed.

## Bounded R1 contract — selected

1. **Read boundary and manifest.** Extract a small pure source adapter, not
   `BarStore` or a general quant store. Fixed discovery and June warm-up bounds
   apply before every payload/cache read, including supplied dates/cursors,
   cold paths and worker paths. Verify resolved paths remain in the approved
   root; reject symlink escapes and wrong-day/out-of-window row timestamps.
   Never deserialize old all-date pickles. Snapshot/hash selected bytes into
   temporary research-owned preparation before calculation; identity includes
   content, dates, hours, feed/provenance, adjustment policy and engine version.
   Same-date corrections must invalidate derived columns and chart windows.
2. **Minimal shared extraction.** Separate existing decision-time feature
   computation from the strategy `risk`/stop parameter without changing Factory
   outputs, feature defaults, IDs or trades. Studio direction is price direction
   (+1), decline negative. Add only the roadmap's three-complete-bucket move /
   prior daily ATR14; never carry it overnight. Use exact completed SPY bucket
   alignment; no stale fallback. Do not introduce R, stops or strategy simulation.
3. **Quality masks.** Require all five valid minutes for a usable five-minute
   bucket. Missing scheduled session open makes open-dependent features
   unavailable. Require the nominal preceding daily-history window to have
   complete RTH minutes for daily-dependent predicates (14, 20, 25 or the
   feature's specified lookback). Keep Factory's numerical state/calculations;
   masks apply only to Studio availability. RVOL history needs complete
   cumulative minutes through that clock, at least five qualified prior
   observations among its up-to-ten retained bucket observations. Chart ATR
   and three-bucket move reject holes in their required same-session inputs.
   Count exclusions by reason and actual eligible names; NBIS is unavailable.
   R1 must pin exact RVOL history handling against the existing computation;
   if stricter availability would alter its denominator, reject the value
   rather than silently redefine RVOL. Do not reset EMA/Wilder state at holes.
4. **Event selection.** Up to three AND predicates and explicit close-time
   decision window, first qualifying completed bar per ticker/session,
   including already-true at window start. Stable occurrence key is symbol +
   decision timestamp within a manifest. Highlighting is never a predicate.
   Warm-up cannot produce events; population previews contain no outcomes.
5. **R1 acceptance.** Hand-calculated synthetic fixtures for feature values,
   units, zeros versus missing, three-bucket gaps, overnight boundaries,
   incomplete opens/daily windows and exact SPY alignment. Spy source-open
   calls to prove date/cursor/derived-cache rejection before protected reads;
   add future perturbation invariance and same-date correction invalidation.
   Run existing Factory regression/ID tests unchanged. R1 has no UI, outcome
   engine, database schema, ledger writes or provider calls.

Later R2 planning decisions are bounded here, not implemented: use
research-owned local SQLite for immutable run identities, execution attempts
and append-only exposure/notes, with atomic content-addressed file artifacts
for prepared columns/charts. Keep it separate from the journal and Factory
ledger. Crash/retry semantics need tests before enabling writes. Use one
separate local research child process with bounded queue, cooperative
cancellation and parent-owned durable status; do not dispatch CPU work through
sync's embedded thread lane. No service installation/provisioning in R0/R1.

Freeze the proposed R2 comparison as 2,000 seeded calendar-week block draws
with all symbols together, recomputing clock/ticker composition matches in
each draw; 95% percentile descriptive intervals, 30m primary horizon. Include
qualifying moments in ordinary controls. Fewer than 20 distinct eligible
weeks yields descriptive point estimates and unavailable intervals; a draw
with zero events or a required missing control is invalid, report its count,
and suppress intervals if fewer than 1,900 valid draws remain. Baseline and
all horizons need independent synthetic proofs/calibration in R2. Twenty
weeks is an explicit engineering floor, not a claim of independence or
protection against adaptive selection. No confirmation/exam gate is added.

Provisional budgets for subsequent acceptance on this Mac: warm preview p95
<=100 ms backend, visible edit feedback <=250 ms, cold preparation <=30 s,
completed analysis <=30 s warm / <=60 s cold, <=512 MiB research-process RSS.
Only the warm scan/cold preparation and component proxy support these targets;
API/browser p95 and completed analysis remain proof pending. Show loading
within 250 ms, retain previous-result identity, and require cancellation
acknowledgment <=1 s, testing interruption/recovery before R2 acceptance.
These are future pass conditions, not shipped promises.

## Reproduction and remaining evidence

Temporary evidence directory: `/tmp/research-studio-r0/`. `/tmp/research-studio-r0/audit.py` and
`/tmp/research-studio-r0/audit.json`/`/tmp/research-studio-r0/manifest.json` hold source coverage/preparation/query timings;
`/tmp/research-studio-r0/extra.py`/`/tmp/research-studio-r0/extra.json` hold exact endpoint coverage and synthetic numerical
proxy; `/tmp/research-studio-r0/quality.py`/`/tmp/research-studio-r0/quality.json` hold strict daily-window sensitivity;
`/tmp/research-studio-r0/chart.cjs`/`/tmp/research-studio-r0/chart.json`/`/tmp/research-studio-r0/chart.png` hold the browser fixture. Python probes
used the existing Mac venv with bytecode writes disabled; the proxy used
`OPENBLAS_NUM_THREADS=1`. Chart fixture used installed Playwright/Chromium.
Artifacts are temporary and are not a permanent research dataset or ledger.
The tables above retain the evidence if temporary files are removed.

Remaining limits: independent calendar reconciliation, cache origin receipts,
full causal/quality/adjustment proofs, completed-run timings and process
cancellation, persisted reopen/crash semantics, React integration and actual
user usefulness. No paid fetch is authorized to close these limits. The
missing NBIS history and conservative daily coverage are known exclusions,
not permission to remap tickers or dilute the quality policy automatically.
