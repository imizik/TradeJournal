# Strategy Workbench: roadmap

An interactive page over the [strategy factory](strategy-factory.md): pick a
family, set its building blocks, run it against discovery data, compare it
with its parent, read the trades behind every number, and freeze a candidate
for the factory to judge. The factory stays the only engine and the only
judge. The Workbench adds a faster way to explore discovery data and a
record of every look. It adds no backtester, no gate and no second ledger.

**Status:** proposal, 2026-10-07. Nothing here is built. Sequenced after
the [swing strategy roadmap](swing-strategy-roadmap.md)'s S1–S2, which take
priority. Milestones are
listed in order with what proves each; the [first slice](#first-slice) is at
the end.

## Is it worth building

Yes, if it stays a thin shell over the factory. No, if it grows into a
platform before the factory has found anything.

- **What it buys:** speed of understanding. Today a question like "are the
  ORB losers the late-morning ones?" means writing a spec, running the CLI and
  reading a CSV. The Workbench answers it in a click, with the trades behind
  the answer.
- **What it will not buy by itself:** an edge. Every family so far beats
  random entries by 0.01 to 0.05R on 18 heavily traded names, and costs eat
  that. Turning the same four families' knobs faster is unlikely to change
  this. The factory's own leads ([what comes next](strategy-factory.md#what-comes-next):
  a stocks-in-play universe, fewer trades with more room) are new building
  blocks. The Workbench makes them quicker to study once they exist; it does
  not stand in for building them.
- **The real risk:** an interactive tool is a discovery-overfitting machine
  by design. That is acceptable only because confirmation and the exam stay
  locked and every frozen candidate pays the rising bar. The design below
  keeps confirmation results as stingy in the UI as they are in the ledger,
  and makes the number of looks impossible to miss.
- **Most of the requested data cannot be backtested here.** The factory's
  periods are fixed: discovery is 2023-07-03 to 2024-09-30. A dataset that
  starts later (option positioning since 2026-10-02, LLM labels written
  from today on) has no discovery data. It cannot be explored or screened
  at all, only tested forward. That is a property of the protocol and the
  roadmap treats it as one.

## Ground truth this plan rests on

Read from the code on 2026-10-07:

- **One engine.** `factory_rules.py` holds four families
  (`recovery_swing`, `vwap_reclaim`, `failed_breakout`,
  `opening_range_breakout`), one execution model (`run_candidate`) and the
  spec: `parse_spec` validates every field and fills defaults, `canonical`
  is everything that decides the trades, and `spec_id` hashes it (name and
  notes excluded). A setting added later stays out of the hash while unset.
- **Fourteen features**, read at the signal bar from completed data
  (`factory_data.FEATURES`, `FeatureContext.at`). Filters are
  `{feature, min, max}`; a filter on a missing (NaN) value rejects the
  signal.
- **Judging.** `factory_gates.evaluate` runs screen, confirm, exam; each
  `_Stage` loads bars only through its own end date. Edge is R minus matched
  random entries' average per ticker, period and side; t is clustered by week;
  the confirmation bar is Φ⁻¹(1 − 0.05/K) with K the distinct candidates that
  have reached confirmation (10 today, so the next needs t ≥ 2.61).
- **Discovery-only helpers already exist.** `discovery_trades` and
  `discovery_forward` (price 5, 15, 30, 60 minutes, the close and the next
  close after each fill, against random entries) load discovery data only.
  `factory_brief.evidence` buckets trades by side, time of day, exit and
  fifths of each feature. `factory_brief.catalog` lists families, settings
  and features. `factory_brief.spec_changes` shows a spec as its changes from
  the family defaults. `factory_brief.review` refuses proposals that pick
  tickers, change costs, carry more than two filters or repeat the ledger.
- **Where it runs.** The bar cache (`backend/data/alpaca_cache`, SIP minute
  bars from June 2023 for the 18 names and SPY) and the live ledger
  (`research/ledger.jsonl` on branch `factory/ledger`, in the factory
  checkout) are on the development Mac. The VPS runs the app and has no
  factory cache. `BarStore`, `AlpacaCache` and `engine_fingerprint` live in
  `backend/scripts/strategy_factory.py`, not in `app/`.
- **Strategy Lab** (`/strategy-lab`) is Pine-only and frozen since
  2026-10-02. The Workbench does not extend it.

## Rules every item follows

1. **One engine.** Every number the Workbench shows comes from
   `run_candidate`, `summarize`, `_Stage` and `discovery_forward`. A
   Workbench function that re-implements an entry, an exit, a statistic or a
   feature is a defect.
2. **One spec, one id.** The browser holds a draft spec in the factory's JSON
   form. `parse_spec` is the only validator; the browser shows its error text
   verbatim. The id shown is `spec_id`.
3. **Explore loads discovery data only**, by construction: the explore
   function takes no date argument, and a test asserts every bar request ends
   on 2024-09-30.
4. **Confirmation and exam results reach the Workbench only as the ledger
   records them.** Confirmation shows the gate checks and the per-half
   headline numbers; the exam shows passed or failed. No breakdowns, no
   trade lists, no charts for any period after discovery.
5. **One ledger.** Only `scripts/strategy_factory.py` writes it, in the
   factory checkout. The Workbench reads it.
6. **Every look is recorded**, including Claude's proposals and repeats of
   a cached run.
7. **Coverage is computed, never asserted.** A dataset's history and status
   come from what is on disk. Nothing is backfilled by guessing.
8. **New building blocks keep every earlier spec's id and trades**, as the
   factory already requires.

## Where it runs

The Workbench needs the bar cache and the live ledger, and both are on the
Mac. **V1 runs on the Mac**: `startdev.sh` in the main checkout, with
`FACTORY_LEDGER_PATH` pointing at the factory checkout's
`research/ledger.jsonl` (read-only). It needs no database table, so the
worktree's SQLite is enough. On any host without the cache (the VPS), the page
says so and shows only the catalog and the ledger.

Moving it to the VPS means fetching the factory cache there and syncing the
ledger from `factory/ledger`. Do it only if the Mac-only page gets real use.

## 1. What is reused

| Need | Reused as is | Change needed |
|---|---|---|
| Spec validation, defaults, id | `parse_spec`, `canonical`, `spec_id`, `spec_changes` | none |
| Running a spec on discovery | `_Stage` (screen settings), `summarize`, `_by_ticker`, `_random_entries` | a public `explore` in `factory_gates.py` that runs one discovery `_Stage` with the cost stress on; see [first slice](#first-slice) |
| Forward evidence | `discovery_forward` | none |
| Breakdowns | `factory_brief.evidence` (side, hour, exit, feature fifths) | add year/quarter, ticker, holding sessions, SPY and volatility regime buckets beside it |
| Catalog | `factory_brief.catalog`, `FEATURES` descriptions | per-setting metadata (label, units, kind, choices, suggested range), in `factory_rules.py` field metadata so it sits next to the setting |
| Bars | `BarStore`, `AlpacaCache` | move from the script into `app/engine/factory_store.py`; the script imports them back |
| Result cache | the evidence cache pattern (`<id>-<engine fingerprint>.json`) | same pattern under `backend/data/factory/workbench/` |
| Ledger reading, K, the bar | `read_ledger`, `prior_candidates`, `required_t`, `ledger_digest` | read from a configured path |
| AI proposals | `factory_brief.brief`, `review`, `answer_problem`, the JSON answer shape | a Workbench brief (below) |
| Durable job status | `job_run` with a new `job_type` | a `research` lane, so an explore never waits behind a sync |
| Price path chart | the charts workspace's Lightweight Charts wrapper | fed with the factory's own bars, not chart history |
| Breakdown tables | `components/AnalyticsExplorer.tsx` patterns | none planned; copy layout, not data code |

## 2. Routes and layout

One route, `/workbench`, linked from the nav beside Strategy Lab. Four tabs:

| Tab | What it holds |
|---|---|
| **Build** | Left: the spec form, generated from the catalog. Right: the latest explore result for the current draft and its parent. Header: draft id, "explored before?" and "in the ledger?" badges, the run button. |
| **Explorations** | The log, newest first: id, family, parent, what changed (`spec_changes` against the parent), author (you or Claude), headline numbers. Grouped by lineage, with the count of looks per family and lineage. |
| **Candidates** | Frozen candidates and every factory ledger line: verdict, gate checks, K, the bar. Confirmation as the ledger records it; the exam as passed or failed. |
| **Data** | The [data catalog](#9-data-catalog). |

A result opens at `/workbench/runs/{run}` with **Summary · Breakdowns ·
Trades**, and a trade at `/workbench/runs/{run}/trades/{n}`.

The spec form, top to bottom: family (with its docstring) · signal settings
· timeframe (values that divide 30 minutes) · universe (`core` only in V1) ·
entry window · filters (at most two, matching the weekly review) · exits
(target, sessions, minutes, breakeven, trail, stall) · session limits · costs
(shown, locked at the defaults). Later blocks (context, events, news,
expression) appear only when their features exist.

A slider never runs anything. Runs are explicit button presses, so every look
is a decision and lands in the log.

## 3. The catalog and the spec

### Spec

The draft is the factory's spec JSON. No new format. The browser holds
it, posts it to `normalize` after each change, and renders what comes back:
the id, the canonical form, the changes from the family defaults and the
parent, and `parse_spec`'s error if there is one.

### Catalog

`GET /factory/catalog` is generated from code, so the UI cannot drift from
`factory_rules.py`:

```json
{
  "engine": "a1b2c3d4e5",
  "families": {
    "opening_range_breakout": {
      "about": "The opening range breakout, both sides. ...",
      "sides": ["long", "short"],
      "defaults": {"timeframe": 5, "exits": {"target_r": null, "max_sessions": 1}},
      "settings": [
        {"id": "range_minutes", "label": "Opening range", "kind": "int", "default": 5,
         "units": "minutes", "suggested": [5, 30], "step": 5},
        {"id": "stop_at", "label": "Stop at", "kind": "enum", "default": "range",
         "choices": ["range", "mid"]},
        {"id": "sides", "label": "Sides", "kind": "enum", "default": "both",
         "choices": ["long", "short", "both"]}
      ]
    }
  },
  "exits": [{"id": "target_r", "kind": "float", "units": "R", "nullable": true, "min": 0.01}],
  "limits": ["..."],
  "timeframes": [1, 2, 3, 5, 10, 15, 30],
  "universes": [{"id": "core", "tickers": ["NBIS", "..."]}],
  "costs": {"slippage_ticks": 1.0, "slippage_bps": 1.0, "locked": true},
  "max_filters": 2,
  "features": [
    {"id": "rel_strength", "label": "Relative strength vs SPY", "units": "%",
     "description": "percent return since the close five sessions ago, minus SPY's",
     "signed": true, "datasets": ["sip_minute", "sip_minute_spy"],
     "frequency": "daily, prior sessions",
     "status": "backtest", "coverage": {"discovery": 0.97}, "in_default_model": true}
  ]
}
```

Per building block, as asked: id, label, description, kind, choices or
suggested range, default, units, applicable families (exits and filters apply
to all; settings to their family), source datasets, frequency, coverage over
discovery (share of signal bars where the value is not NaN, computed from the
cache), status (backtest / live / prospective / unavailable), and the engine
fingerprint as the version.

- **Hard limits stay in `parse_spec`.** The catalog's `suggested` range only
  sizes a slider. A typed value outside it is allowed if `parse_spec`
  accepts it.
- **Choices come from one place.** Field metadata in `factory_rules.py`
  carries the enum choices, and each family's `validate` reads them.
- **Drift tests.** A family field without metadata fails a test. So does a
  catalog choice that `parse_spec` refuses, or a value outside the choices
  that it accepts. Field metadata is invisible to `asdict`, so ids and
  trades do not change.

## 4. Backend API

New router `backend/app/routers/factory.py`. Everything reads the bar cache
and the ledger; nothing writes the ledger.

| Method | Path | Does |
|---|---|---|
| GET | `/factory/status` | Bar cache present and through what day, ledger path, line count and last line, K, the next bar, engine fingerprint, code commit |
| GET | `/factory/catalog` | The catalog above |
| POST | `/factory/specs/normalize` | Raw spec → `{id, canonical, changes, parent_changes, error, explored: [run ids], ledger: verdict or null}`. Pure, fast, no bars |
| POST | `/factory/explore` | `{spec, parent_id, note, author}` → a run: from the cache when `(id, engine)` was computed before, else a `factory_explore` job. Appends to the log either way |
| GET | `/factory/explore/{run}` | Status, then the result: discovery stats, stats with costs tripled, by ticker, forward evidence, random stop rule, parent comparison |
| GET | `/factory/explore/{run}/breakdowns` | Buckets, each with a key the trade list accepts |
| GET | `/factory/explore/{run}/trades` | Discovery trades with features; `?bucket=` filters by the same key |
| GET | `/factory/explore/{run}/trades/{n}` | One trade: [why it fired](#8-a-simulated-trade) and the bars around it (discovery bars only) |
| GET | `/factory/explorations` | The log; `?family=`, `?lineage=` |
| POST | `/factory/candidates` | Freeze: `{run, hypothesis}` → an immutable frozen spec; 409 if that id is frozen or in the ledger |
| GET | `/factory/candidates` | Frozen candidates joined to ledger lines by id, exam reduced to passed or failed |

Explore refuses a spec with a `model`: a learned filter's discovery numbers
are in-sample by construction, and the factory already sends such specs
straight to confirmation.

## 5. The exploration log

An append-only JSONL file, `backend/data/factory/workbench/explorations.jsonl`
(gitignored, with the factory's other local state), one line per look:

```json
{"run": "2026-10-08T14:02:11-or-3f9a1c2b7e", "id": "or-3f9a1c2b7e", "parent": "or-0d41e9a2c3",
 "lineage": "or-0d41e9a2c3", "author": "you", "note": "drop late-morning breaks",
 "engine": "a1b2c3d4e5", "code": "8b1088f", "cached": false,
 "headline": {"n": 412, "mean_r": 0.031, "edge": 0.022, "edge_t": 1.41}}
```

Results sit beside it as `<id>-<engine>.json` plus a trades CSV in the
factory's format. Discovery bars never change, so a result is valid until the
engine changes, the same rule as the evidence cache.

Why a file and not a table: the factory deliberately touches no database,
the Workbench runs where the factory runs, and a table would add a
migration that waits for a person on deploy. Losing the file loses
visibility, never validity: the safeguards live in the data lock and the
ledger, not in this log. Revisit when the Workbench moves to the VPS.

## 6. Explore → Freeze → Confirm → Exam

| Step | Where | Data | Writes |
|---|---|---|---|
| **Explore** | Workbench | discovery only | a log line and a cached result |
| **Freeze** | Workbench | none | `backend/data/factory/workbench/frozen/<id>.json`: the canonical spec, the hypothesis, the lineage and the looks behind it; never overwritten |
| **Confirm** | factory checkout: `python scripts/strategy_factory.py run <frozen file>` | discovery, then confirmation if the screen passes | one ledger line, exactly as today |
| **Exam** | the same run, for a candidate that passed confirmation | the holdout, once | the same ledger line |

- **A frozen candidate never changes.** Editing it in Build makes a new
  draft whose parent is the frozen id. A variant of a candidate whose
  confirmation results were seen is labelled "designed after confirmation"
  in the log and in its notes. The factory already treats it as a new
  candidate that pays the higher bar.
- **The Freeze dialog shows the price** before you commit: "If this passes
  the screen it becomes candidate 11, and every later candidate needs
  t ≥ 2.64 instead of 2.61." It also asks for a written hypothesis, as the
  weekly review does.
- **Validation stays a command in V1.** The Candidates tab shows the exact
  command with a copy button, and the verdict once the ledger has the line.
  A Validate button that runs it from the UI (the factory checkout, a lock
  shared with the weekly run, commit and push as `factory_week.sh` does) is
  [W4](#w4--validate-from-the-ui-conditional), and only after the command has
  been used a few times.
- The frozen file's `notes` carry `source: workbench`, the number of looks
  in its lineage and whether any filter came from a breakdown, so the
  ledger line says how it was found. That is the field the factory already
  writes; no ledger format change.

### What repeated exploration does to the safeguards

- **Confirmation stays valid.** Bonferroni over K is valid when the confirmation data
  played no part in choosing the candidates and every candidate tested on it
  is counted. Explore never loads confirmation data, and every frozen
  candidate that passes the screen is counted. Searching discovery a
  thousand times does not weaken the confirmation test of what comes out.
- **The screen stops being a test.** t ≥ 2 on discovery is a filter for an
  idea written blind. After forty looks at the same family, something clears
  it by luck. The weekly loop already admits this for evidence-drawn ideas
  ("the screen is not an independent test of it"), and learned filters skip
  the screen for the same reason. For Workbench candidates the screen is a
  formality and the UI says so.
- **The cost moves to K.** Overfitted candidates pass the screen, fail
  confirmation and raise the bar for every later idea, the weekly loop's
  included. That is the honest price, and the Freeze dialog shows it. K = 20
  needs 2.81; K = 30 needs 2.94; K = 50 needs 3.09.
- **Confirmation leaks when its results steer the next idea.** Bonferroni
  counts tests; it does not repair a test whose hypothesis was picked after
  seeing that data. Every "failed confirmation, tweak, resubmit" cycle makes
  the confirmation periods a little more in-sample. The exam is the one
  clean test left. Hence rule 4: the Workbench never shows confirmation
  breakdowns or trades, so it adds no leak beyond the headline numbers the
  ledger already exposes.
- **Looks are shown as a luck line.** Beside discovery t, the result shows
  the t that chance alone would top across this lineage's looks,
  Φ⁻¹(1 − 0.05/N). Variants are correlated, so this overstates the luck; it
  is labelled as an upper bound and gates nothing.

## 7. Results and comparison

### Summary, for every run

| Number | Source |
|---|---|
| Trades, trading days | `Stats.n`, `days` |
| Mean R, total R, profit factor, win rate, max drawdown | `Stats` |
| Edge against matched random entries, its clustered SE and t | `Stats.edge`, `edge_se`, `edge_t`, `random_r`, and the random stop rule used |
| Cost sensitivity | mean R at default costs and tripled; `cost_r` (round-trip slippage in R) from the forward evidence |
| Breadth | tickers positive / tickers with five or more trades; mean R without the best ticker |
| Concentration | total R without the best trade and without the best day; the top ticker's share of total R |
| Forward returns | `discovery_forward`: edge at 5, 15, 30, 60 minutes, close, next close; MFE/MAE to the close; share stopped by the close |
| Screen preview | the screen gate's checks on these numbers, labelled "preview, not a test" |
| Luck line | above |

Each number has a hover that names the factory function behind it.

### Variant against parent

The parent is the draft's parent in the log, or the family defaults. Side by
side: every summary number for both, and the difference. Since both runs
share most trades, the useful split is by trade, matched on ticker, side and
signal time:

- **Kept**: in both. **Removed**: only in the parent. **Added**: only in the
  variant.
- For a filter, the honest question is whether the removed trades were worse
  than the kept ones. That gets its own row: removed trades' mean R and edge,
  with clustered t.

### Breakdowns

All from trade fields and features already recorded. No new data:

| Breakdown | Buckets |
|---|---|
| Time | quarter (2023Q3–2024Q3) and the two discovery halves |
| Ticker | each name; sector from a static map once the catalog has one |
| Side | long, short |
| Market regime | `spy_trend` above or below 0; `spy_day` sign |
| Volatility regime | `spy_vol` terciles; `vol_ratio` above or below 1 |
| Entry context | hour of entry (`factory_brief.HOURS`); fifths of each feature (`factory_brief.evidence`); gap direction |
| Holding | exit reason; sessions held; minutes held in fifths |
| Catalyst | once [news features](#11-news-and-catalysts-later) exist |

Each row: trades, mean R, edge, and t only when the bucket has at least 30
trades across at least 10 weeks; below that the cell says "too few". Clicking
any cell opens the trade list filtered to it. Adding a filter from a bucket is
one click, and that filter is marked "from a breakdown" in the log.

## 8. A simulated trade

`/workbench/runs/{run}/trades/{n}`:

- **The decision:** signal bar time, side, family, entry fill and slip, stop,
  target, risk in ATR.
- **Why it fired (V1):** every feature's value at the signal bar, each filter
  with its bounds and pass, the entry window, and the session's entries and
  losses so far. These are the values `FeatureContext.at` returned, read off
  the trade's `features`. Nothing is recomputed.
- **Why it fired (W5):** the family's own conditions. The arming bar, the
  level reclaimed, the bars cleared, the confirmation bar. Families add them
  to the `Signal` they already emit, in a field excluded from equality, and a
  test asserts every committed spec's trades are unchanged.
- **What happened next:** a chart of the factory's own bars for that ticker
  and timeframe, from a session before the signal to a session after the
  exit (discovery only). Markers at signal, fill and exit; lines at stop,
  target and any moved stop; the bar the stall check read. The R path under
  it, with MFE and MAE. The random-entry average for that ticker, side and
  period, so one trade's R reads against its yardstick.

The factory's bars are used on purpose: chart history is a different cache
with its own adjustment layer, and a trade must be shown on the bars that
produced it.

## 9. Data catalog

A registry in code, `app/engine/factory_datasets.py`, one entry per dataset:
id, label, source, frequency, symbols, point-in-time (yes / approximate /
no, with the reason), live source, and the features that read it. History,
coverage and freshness are **computed** from the cache on each request
(cheaply, from file listings), never typed in.

| Status | Means | Rule |
|---|---|---|
| **backtest** | usable in Explore and by the factory | covers 2023-07-03 to 2026-03-31 for the symbols, missing sessions under 2%, point-in-time yes or approximate |
| **live** | also available on live bars for paper trading | a live source exists and its parity check (see the factory's step 3) has run |
| **prospective** | collected from a date after discovery began | first day after 2023-07-03; can be tested only forward |
| **stale / incomplete** | was backtest, now behind or gappy | last day older than its cadence allows, or gaps over the threshold |
| **unavailable** | no access on current plans | e.g. Benzinga analyst endpoints (HTTP 403) |

Initial rows: SIP minute bars, 18 names (backtest); SPY (backtest); QQQ,
sector ETFs, TLT, UUP, USO, GLD (unavailable until fetched, then backtest:
the same SIP history); VIX close, Treasury yields (FRED, not fetched);
economic calendar (static file, not written); earnings (Tradier calendar,
approximate: dates only, no time of day); Alpaca/Benzinga news (to probe);
company filings and press releases (not fetched); option open interest by
strike (prospective since 2026-10-02).

- **No on/off toggles.** A feature reading a dataset either exists in the
  engine or does not. Switching datasets at runtime would change what a spec
  id means. "Enabling" a dataset means a person decides to build its
  features, with tests, as the factory already requires for new building
  blocks. The tab shows what would become possible.
- **A prospective dataset never becomes historical by waiting** inside these
  periods. It becomes testable when its own forward record is long enough
  for a separate, forward-only protocol (product roadmap
  [J5](product-roadmap.md#j5--evaluate-one-change-on-future-trades)).

## 10. Macro and market context, later

Cheapest first: **ETFs on the same SIP pipeline.** QQQ, the sector SPDRs and
SMH, TLT and IEF for rates, UUP for the dollar, USO for oil, GLD for gold,
VIXY for volatility. Same history from June 2023, the same session rules,
split handling and timestamps, intraday values. Adding them is a longer
`prepare` list and new features. No new data source.

- **New features follow the existing pattern.** Market-relative values read
  from a context series the way `spy_trend` reads SPY. Daily values come from
  prior sessions only (`prior`). The names are new (`qqq_trend`,
  `sector_rs`, `tlt_day`, `uup_trend`), so old ids stand. Each must be named
  in a model's feature list.
- **Sector relative strength** needs a static, dated map of the 18 names to
  sector ETFs in the catalog.
- **True index and rate levels (VIX, 10-year yield) come from FRED, daily.**
  Use them only at the prior session's close; FRED posts the 10-year with a
  lag, so the safe reading is two sessions back. Where values are revised,
  use ALFRED vintages or mark the dataset approximate.
- **Economic calendar:** FOMC, CPI, payrolls and PCE dates and times are
  published in advance, so a hand-kept, dated file in the repository is
  point-in-time safe. Features: `minutes_to_macro_event`,
  `macro_event_day`. Event restrictions are ordinary filters (0/1 or minutes
  with min/max), so no new filter type is needed. Release values and
  consensus surprises have no free point-in-time source: unavailable.
- **Earnings:** Tradier's calendar back to 2010, frozen as a dated snapshot
  file so a refetch cannot change history. Dates have no time of day, so
  `sessions_to_earnings` treats the report date and the session after as the
  event window. Historical rows are the dates that happened, not the dates
  announced beforehand; status approximate.

## 11. News and catalysts, later

### Layers

1. **Raw articles, as source evidence.** Append-only:
   `(source, article_id, revision, created_at, updated_at, fetched_at,
   symbols, headline, summary, url, content_hash)`. A changed article is a
   new revision, never an overwrite.
2. **Classifications, frozen.** Keyed by
   `(article_id, revision, classifier, taxonomy_version)`. `classifier` is
   either a rules version or a model id plus prompt hash, and `input_hash`
   is stored. A stored key is never recomputed. A new model or taxonomy is a
   new classifier with its own rows. The output is a bounded object:
   - scope: ticker / sector / market
   - categories (multi-label): earnings_guidance, analyst_action, mna,
     contract_customer, product, regulatory, legal, geopolitical,
     ai_semis, crypto, energy, defense
   - tone: positive / negative / neutral / unclear, **prospective only**
     (below)
   - story cluster id for independent-story counting
3. **Features, versioned in their names.** For example `news_count_24h_v1`,
   `cat_defense_72h_v1`, `stories_24h_v1`, `news_age_min_v1`. The version
   names the classifier and taxonomy, so a reclassification is a new feature
   and every earlier spec id keeps its meaning.

### Timing and lookahead

- **An article counts for a decision at a bar's close only if
  `created_at` plus a latency allowance (two minutes to start) is before that
  close.** Live, the time it was received replaces `created_at`.
- **Revisions.** For history, the API returns the latest text, so a backfill
  may have read an edit made later. Those rows are marked approximate.
  Prospectively, the first revision seen is kept and used.
- **Missing coverage is NaN, not zero.** A day the source has no articles
  for the whole tape is a gap. A ticker with no articles on a covered day is
  a real zero. A filter on a NaN feature rejects the signal, as today.
- **Model knowledge is lookahead.** A language model trained after 2024
  has read about what followed a 2023 headline. Its tone label for that
  headline is contaminated, and so, more weakly, is any judgment of
  importance. So:
  - historical backfill uses a **deterministic, versioned rules
    classifier** for categories and scope (keywords and symbol tags, audited
    on a labelled sample);
  - LLM classification runs **prospectively only**, at ingestion, frozen;
  - LLM-derived features are **prospective** datasets. They feed forward
    tests and, once enough record exists, a comparison against the rules
    classifier on the same articles.
- **Story counting** clusters by headline similarity within a time window,
  with a versioned algorithm, so ten reposts of one wire story count once.

### Before any of it

Probe what Alpaca's news API returns for the 18 names across the discovery
period: articles per name per month, gaps, revision behaviour. Record it
the way the [symbol info roadmap](symbol-info-roadmap.md#what-the-apis-actually-return)
records its probes. If discovery coverage is thin, historical news features
are not worth building and the whole news layer is prospective.

## 12. AI researcher boundaries

A side panel in Build. You ask; Claude proposes up to three drafts; you
decide what to run.

- **What it sees:** a Workbench brief built like the weekly one
  (`factory_brief.brief`). It holds the catalog with each feature's status
  and coverage, the ledger digest with exams as passed or failed,
  discovery evidence for the current lineage, the exploration log's digest
  for the family (including the look count), and your question.
- **What it returns:** the weekly loop's JSON answer shape (title,
  hypothesis, what it builds on and changes, whether it came from evidence,
  a spec), checked by `answer_problem` and `review`: no ticker picking, no
  cost changes, at most two filters, no repeat of a ledger id. Accepted
  specs fill the form as drafts, marked as Claude's.
- **What it cannot do:** run Explore, freeze, read trade files, read
  confirmation or holdout anything, or name a feature the catalog lacks
  (`parse_spec` refuses it). There is no tool loop. One call returns
  proposals, so it cannot search until something wins.
- **When the question cannot be tested, it says so.** "Do recent geopolitical
  defense catalysts improve 5–10 day momentum continuation?" needs a
  backtest-status defense-category feature and a swing family. If either is
  missing or prospective, the answer names the missing building block and
  proposes a forward test or the build, not a proxy dressed up as the
  question.
- Every proposal is logged with `author: claude`, whether or not it is run.

## 13. Anti-overfitting protections

| Protection | Mechanism | Proved by |
|---|---|---|
| Explore never sees later data | `explore` takes no date; loads through 2024-09-30 | test on `BarStore.requests` |
| One engine | Explore calls `_Stage`; no re-implementation | parity test: explore's stats equal `evaluate`'s screen stats for each family on synthetic bars |
| Confirmation stays thin | only ledger fields served; no breakdown or trade route accepts a later period | route tests |
| Exam stays a verdict | candidates route reduces exam to passed/failed | route test |
| Every look recorded | log append on every explore request, cached or not | test |
| Search depth visible | look counts per family and lineage; luck line | UI |
| Freezing has a visible price | K and the next bar in the Freeze dialog | UI |
| Frozen means frozen | 409 on re-freeze; edits make a new id with a parent | test |
| No hidden building blocks | catalog generated from code; `parse_spec` the only validator | drift tests |
| No ticker or cost tuning | universe `core`, costs locked, at most two filters | `normalize` refuses; same rules as `review` |
| Learned filters not explored | explore refuses `model` | test |
| Breakdown-born filters flagged | "from a breakdown" in log and notes | test |
| Prospective data stays out of history | dataset status computed from coverage | test with a fixture cache |

## 14. Milestones

Each is one delivery with its own proof. V1 is W0–W3.

### W0 — Catalog, normalize and explore, no UI

See [first slice](#first-slice).

### W1 — Build tab and the log

The spec form generated from the catalog; normalize on change; Explore as a
`factory_explore` job in a `research` lane, cached by `(id, engine)`; the
Summary view; parent comparison with kept/removed/added; the Explorations
tab. *Done when:* a draft built in the form gets the same id as the same spec
written by hand; a run's numbers match `strategy_factory.py explore` for the
same spec; a repeat run is served from the cache and still logged; the
frontend build passes, and rendering is checked by hand on the Mac, since the
suite does not cover it.

### W2 — Breakdowns and trades

Breakdown tables, trade list by bucket, trade page with V1 "why it fired" and
the price path. *Done when:* every bucket's trades sum to its row; the trade
page's feature values equal the trades CSV's; no route serves a bar after
2024-09-30.

### W3 — Freeze and Candidates

Freeze dialog with hypothesis, K and the next bar; frozen files; the
Candidates tab reading `FACTORY_LEDGER_PATH`; the copyable validate command.
*Done when:* a frozen file run by the CLI yields a ledger line whose id equals
the frozen id; re-freezing is refused; the exam shows as passed/failed only.

### W4 — Validate from the UI (conditional)

Only after the command has been used a few times. A job that runs
`strategy_factory.py run` in the factory checkout under a lock shared with
`factory_week.sh`, then commits and pushes `research/` the same way.
*Done when:* a weekly run and a UI validation cannot interleave (test with
both holding the lock), and a validation leaves the checkout clean.

### W5 — Family traces and the Data tab

`Signal` reasons per family; the dataset registry with computed coverage and
status. *Done when:* every committed spec's trades are identical with traces
on; the Data tab's coverage for SIP bars matches the cache's days.

### W6 — Context ETFs

Fetch the ETF list in `prepare`; context series in `FeatureContext`; new,
named features; sector map. *Done when:* every earlier spec's id and trades
are unchanged; new features use only prior sessions (the existing
"features do not change when later bars do" test, extended).

### W7 — Event calendars

Macro schedule file, earnings snapshot, event features. *Done when:* a
synthetic calendar proves the event window, and a refetch of the earnings
snapshot cannot change a past run.

### W8 — Slower swing families (needs a decision)

Daily-bar families holding 5–10 sessions. Fifteen months of discovery holds
about 65 weeks, which is thin evidence for a weekly-clustered t with trades
that overlap weeks. A swing family likely needs its own periods on longer
daily history, and its own count toward the bar. That is a protocol change
and a person's decision before any code.

### W9 — News

The probe first; then raw store, rules classifier, versioned features; then
prospective LLM classification. Each a separate slice.

### W10 — AI researcher panel

After W3, when there is a log worth reasoning over.

### Later — expression and universe

Options expression as a stated cost overlay on underlying R (spread and
theta assumptions shown, not gated). Option history exists only since
2026-10-02, so real option backtests are prospective. Stocks-in-play
universes are the factory's own lead and its own decision.

## 15. Not in V1

- Macro, news, events, sector or option data of any kind.
- New families, new features, new filter types, swing families.
- Ticker subsets, custom universes, cost changes.
- Learned filters in Explore.
- Parameter sweeps, grids, optimisers, "run all neighbours".
- Validate button (W4), AI panel (W10), live or paper signals.
- Any confirmation or holdout breakdown, trade list or chart. Not later
  either.
- A database table, a VPS deployment, auth.
- Extending Strategy Lab or Pine.
- Dataset toggles. Not later either, as runtime switches.

## Decisions for a person

1. **Where V1 runs:** Mac only (recommended) or provision the factory cache
   on the VPS first.
2. **Do Workbench freezes share the weekly budget?** Recommended no, as with
   hand runs, but the Candidates tab shows how many came from each source.
3. **Swing families' periods** (W8).
4. **Whether historical news is worth it**, after the probe (W9).

## First slice

**W0: the catalog, `normalize` and `explore`, as engine functions, two
routes and a CLI command. No UI and no change to any family, the execution
model, a feature, a gate, the ledger format or any spec id.**

1. Move `BarStore`, `AlpacaCache`, `MinuteSource` and `engine_fingerprint`
   from `backend/scripts/strategy_factory.py` to
   `app/engine/factory_store.py`; the script imports them. Mechanical.
2. Add field metadata (label, units, kind, choices, suggested range) to each
   family's settings in `factory_rules.py`. `validate` reads enum choices
   from it. Feature labels and units go beside `FEATURES` in
   `factory_data.py`.
3. `factory_gates.explore(spec, load)`: refuses a `model`; runs one `_Stage`
   on discovery with the cost stress on; returns discovery stats, stats with
   costs tripled, by-ticker stats, trades, the random stop rule, and the
   forward evidence from `discovery_forward`. It takes no date.
4. `GET /factory/catalog` and `POST /factory/specs/normalize` in a new
   router, built from the above. Normalize also returns the spec's ledger
   verdict when `FACTORY_LEDGER_PATH` is set.
5. `python scripts/strategy_factory.py explore <spec>`: prints the summary
   and the screen preview, writes the result and trades CSV under
   `backend/data/factory/workbench/`, appends to the exploration log, and
   never touches the ledger. This gives the Mac a working explore loop
   before any UI exists.

**Done when** (all in the existing suites, on synthetic bars and the stub
minute source):

- for each family at its defaults and for each committed spec, `explore`'s
  discovery stats equal `evaluate`'s screen stats, field by field;
- every bar request `explore` makes ends on 2024-09-30;
- the committed specs' ids in `test_strategy_factory.py` are unchanged, and
  their trades on synthetic bars are identical before and after;
- a family setting without metadata fails a test; every catalog choice
  parses, and a value outside the choices does not;
- `normalize` returns `spec_id(parse_spec(x))` and `parse_spec`'s error
  text unchanged;
- `explore` refuses a model spec, and the CLI leaves the ledger file
  byte-identical;
- `bash scripts/verify.sh` passes.

The CLI and routes are checked by tests; the CLI against real bars needs the
Mac and is the user's first run.
