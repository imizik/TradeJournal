# Research Studio R1: discovery event observations

**Selected by the user on 2026-10-10.** Implements the bounded
[R0 contract](research-studio-r0.md#bounded-r1-contract--selected) and
[roadmap R1](../strategy-workbench-roadmap.md#small-delivery-phases).
R2–R4 remain unselected. There is no Studio UI/API route, outcome calculation,
strategy execution, provider fetch, persistent research store or worker.

## Owning code and entry point

- `backend/app/engine/research_studio.py`: versioned definition, immutable source
  snapshot, quality masks, decision features and first-match population preview.
- `backend/app/engine/research_studio_data.py`: explicit-root read-only source
  adapter and code/content fingerprints.
- `backend/scripts/research_studio.py`: local cache-only JSON preview.
- `backend/app/engine/factory_data.py`: `FeatureContext.decision_at` separates
  shared decision features from execution risk. Factory's existing `at` still
  requires the stop, returns all original keys in their original order and
  keeps its existing values, side convention, defaults and IDs.
- `backend/tests/test_research_studio.py`: hand-calculated and refusal fixtures.

Run from the repository root with an operator-approved SIP minute root and a
version-1 definition file. Output goes to stdout; redirect only into temporary
storage when investigating. No root is chosen through credentials or `.env`.

```bash
backend/.venv/bin/python backend/scripts/research_studio.py \
  --cache-root /Users/user/TradeJournal/backend/data/alpaca_cache/stocks/1Min/sip \
  --definition /tmp/research-studio-r1/question.json
```

An illustrative sharp-decline definition, not an executable trading rule:

```json
{
  "version": 1,
  "predicates": [
    {"feature": "move_15m_atr", "maximum": -0.25},
    {"feature": "rvol", "minimum": 1.5}
  ],
  "window_start": 600,
  "window_end": 690
}
```

`universe` defaults to the Factory core targets, with SPY context loaded
separately. `start`/`end` default to discovery. Bounds are inclusive; window
values are completed-bar close minutes in Eastern time. One to three AND
predicates, finite numeric bounds, distinct approved targets and version 1
are required. Unknown fields, execution risk/stops, other rules, timeframes,
unaligned windows and out-of-discovery event dates fail. The returned canonical
definition can be parsed again; supplied canonical metadata must match V1.

## Read and identity boundaries

Discovery events are fixed to 2023-07-03 through 2024-09-30; indicator warm-up
begins 2023-06-01. Source dates and cursors validate **before payload opens**.
The adapter opens only named roster dates through its cutoff. It never
consults Factory pickles, evidence, run artifacts, ledger records, live feeds,
provider clients or a database. Wrong-day and timezone-naive payload timestamps
are rejected, including extended-hours rows. An unapproved filename cannot be
selected by a symbol/date/cursor request.

The operator approves the root. The existing factory checkout's root symlink
can resolve to that approved Mac directory. Below that root, POSIX directory
file descriptors and `O_NOFOLLOW` reject both symbol-directory and file symlink
escapes, including replacement during traversal. The opened root must also
retain its approved device/inode identity, rejecting an ancestor-directory
replacement before any payload read. The CLI constructs and pins one reader
before opening configuration, then retains that reader through snapshot loading.
Non-regular files and files
over 8 MiB fail closed. No file or directory in the source is written.

Definition JSON must be outside the approved source cache; the CLI rejects a
cache payload supplied as configuration before reading it. Resolved configuration
paths are opened through no-follow directory descriptors, so an ancestor or file
replaced by a cache symlink cannot bypass that check. Configuration must be a
regular file of at most 1 MiB; descriptors close on success and refusal.

Snapshot preparation is temporary **in memory**: the exact selected bytes are
hashed and parsed in the same read, then kept as frozen five-minute bars and
compact minute-coverage masks. Every new snapshot rereads/hashes selected files;
there is no date-only derived cache to reuse. Missing files are manifest entries
and remain gaps. Same-date corrections create a new data/population identity;
previous snapshots retain their original inputs. Threshold-only changes reuse
one bounded in-memory eligible-feature grid, keyed by universe, dates, window
and feature names on that immutable snapshot. New windows/features rebuild it;
new snapshots never share it. No outcomes or persistent cache are involved.
Prepared bars/coverage are
also fingerprinted, so supplied-snapshot changes cannot retain the same ID.

Identity binds definition/version/units, raw content hashes and missing states,
prepared content, source cutoff, code fingerprints, feed/adjustment provenance,
roster and hours. Occurrence keys are symbol + completed decision timestamp;
they remain comparable across predicate variants within the same dataset.
Population identity binds both definition and data IDs. No Factory ID or
validation budget is changed.

## Calendar and availability policy

The fixed `r0-spy-roster-335-v1` contains 335 warm-up/discovery sessions, generated
from weekdays and the 13 weekday closures absent in the R0 SPY audit. This is
versioned offline source evidence, not independently reconciled exchange data.
The roster is not rebuilt from whichever files happen to exist: deleting SPY
or target files cannot turn a missing session into a holiday. Hours retain the
Factory's early-close table, clipped to the approved interval.

Five-minute bars require all five valid scheduled minute opens. OHLC must be
finite, positive and consistent; volume must be present, finite and nonnegative.
Zero volume is valid. Invalid rows and duplicate minutes are unavailable; gaps
are never filled or replaced by nearby bars. Available-minute aggregates remain
in shared indicator calculations, with strict Studio availability masks.

- Daily-dependent features require the preceding nominal 14/20/25 sessions, or
  five sessions for relative strength, to have complete RTH minutes. A missing
  09:30 minute also excludes opening-dependent features. This can exclude a
  feature even though the symbol has every session file.
- RVOL retains the Factory's up-to-ten prior observations at each clock bucket,
  minimum five. Missing whole buckets do not count as observations. Every
  retained observation must have complete cumulative minutes through that
  clock, and so must the current observation. Reject a bad denominator instead
  of dropping its bad members and silently changing the shared calculation.
- `move_15m_atr` is `(ending close - starting close) / prior daily ATR14`. It
  requires four consecutive complete five-minute buckets in the same session:
  a known starting close and the three intervening buckets. Declines are
  negative; the first possible close interval starts after 09:30.
- VWAP distance requires complete cumulative session data and 14 consecutive
  complete chart bars in the same session. Its denominator is chart ATR, not
  volume-weighted standard deviation. Indicator state retains Factory seeding
  and carries older observations; a nominal completeness mask does not establish
  full-history EMA/Wilder accuracy.
- Market-dependent features require the **exact** complete SPY bucket at the
  decision timestamp and SPY's own prior-history mask. A stale previous bucket
  is unavailable, never contemporaneous context.

Every complete decision bucket in the requested window is evaluated. The first
qualifying one per target/session is selected, including already-true at the
window opening. Warm-up bars never become events. Editing the definition creates
new analytical identity; there is no highlighting input that changes counts.

Preview reports examined, eligible, excluded and qualifying moments separately
from first-match event N; actual eligible/unavailable names; coverage and feature
exclusion reasons; distinct dates/calendar weeks and largest-day concentration.
Reason counts can overlap and must not be summed as mutually exclusive buckets.
Each selected observation includes known-at-decision features, actual units and
unavailable reasons. Nothing computes a next open, future return or outcome N.

## Approved-cache acceptance evidence

The illustrative definition above was exercised on the existing approved Mac
SIP cache, using all core targets and discovery only. It examined 107,388 clock
buckets, retained 71,896 feature-eligible moments and 677 qualifying moments,
and selected **269 target/session events**, including **25 MU events**.
Fourteen targets had eligible moments; NBIS had no approved-period source data.
LLY, GS and CAT were excluded by the conservative history policy. There were
161 event dates and 64 calendar weeks; the largest day contributed 2.97% of
selected events. These are exploratory population counts, not independent
samples, outcome results, profitability or proof of an edge.

An instrumented pass under concurrent host load observed 28.82 s for immutable source preparation,
5.14 s for shared features/quality preparation, and 2.22 s for the first feature
grid/query. Twenty warm queries had median 100.9 ms and maximum 523.9 ms;
peak RSS was 341,344,256 bytes (325.5 MiB). Earlier lighter-load passes measured
about 24 s total preparation and warm queries near 30–50 ms. Concurrent host
work materially affected wall time. The <=30 s cold-preparation and <=100 ms
warm-preview budgets are **not proved met** by this pass; preserve this as an
R2/R3 performance gate, not a delivered latency promise. Completed analysis and
API/UI feedback remain unmeasured. Full correctness/verification evidence is
recorded in the PR.

A retest on the final source observed 19.47 s for the snapshot, 3.11 s for
feature/quality preparation and 1.62 s for the first grid/query (24.20 s total).
Twenty warm queries had median 31.3 ms, interpolated sample p95 about 63.0 ms
and maximum 149.0 ms, with 355,991,552 bytes (339.5 MiB) peak RSS. This quieter
pass supports feasibility; it does not erase the load-sensitive budget miss or
prove API/UI response times.
No paid request, protected-period read or journal/Factory record write was used.

## Frozen R2 specification — implementation not selected

Carry the existing roadmap/R0 choices into R2:

- Reference is the next complete five-minute bucket's open in the same session;
  exact closes at reference +15/+30/+60 minutes and scheduled session close.
  Missing reference excludes outcomes; missing endpoint excludes that horizon
  only. Report N/reasons per horizon. No next-session or nearest-bar substitution.
- Percent-of-reference and decision-frozen prior ATR14 returns; 30m primary
  descriptive horizon. No stops, costs, R, P&L or execution inference.
- Ordinary eligible moments at the same symbol, completed decision clock bucket
  and horizon, including qualifying moments. Weight controls to the selected
  event population's symbol/clock composition; report missing matches.
- Joint calendar-week block resampling with all symbols together; recompute
  event/control composition and weights per draw. Exactly 2,000 draws, NumPy
  PCG64 seed 0, 95% percentile descriptive intervals. Percentile convention is
  linear interpolation. Use the chronologically ordered distinct calendar weeks
  in the eligible event/control universe, resampling the same number of weeks
  with replacement. A zero-event draw or required missing control is invalid;
  report invalid draws. Fewer than 20 distinct eligible weeks or fewer than
  1,900 valid draws makes intervals unavailable. Calendar weeks are approximate
  dependence blocks, never asserted independent samples.

R2 must prove reference/endpoint semantics, matching weights, correlated-symbol
uncertainty and null calibration on independent synthetic fixtures before
showing results. These frozen parameters are not implemented or calibrated here.
Persistence, append-only exposure records, jobs, cancellation and cached reopens
remain R2; connected charts/editor/analysis remain R3. There is no permission
to weaken quality rules, fetch more history or enable Factory promotion.
