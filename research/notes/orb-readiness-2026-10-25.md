# ORB readiness — October 25, 2026

**No validated strategy or new backtest result is delivered here.** The requested
candidate, `op-998d19a73d`, is absent from the authoritative ledger. Evaluating it
would spend a new candidate attempt. Fourteen other ORB candidates have already
failed discovery. The useful bounded change is a stage-isolation repair and a
frozen specification; live execution remains disabled.

This review follows the [Factory protocol](../../docs/strategy-factory.md), the
[October evidence review](evidence-review-2026-10.md), and the authoritative
`factory/ledger` checkout's `research/CONTINUOUS_SEARCH.md`. It does not optimize
the October 25 option-invalidation results. No Factory evaluation, reservation,
prepare/download, exam inspection, broker order, production write, activation,
or deployment was performed. Synthetic tests write only temporary fixtures.

## 1. Existing research and eligibility

Audit identity:

- Application base: `26913c429e440ef2b7545bb9afcaf8e8541d14d9`.
- Authoritative local and fetched remote `factory/ledger`:
  `a285a8340525e0c37421f80b9642baabf0bf0d41`.
- Ledger: `/Users/user/TradeJournal-factory/research/ledger.jsonl`, SHA-256
  `0e1a959e540a25597b38a55dca8f453641aa2359fd312397a69b2ccb7fb3e47e`.
- 142 lines, 82 distinct IDs. Latest outcome per ID: 68 failed screen, 14 failed
  confirmation. The 59 reservation records are not 59 additional unique ideas.
  Records span September 28–October 16, 2026. No successful confirmation is
  present. Only candidate specifications, statuses, and discovery metrics were
  reported; protected-period results were not inspected.

Canonical comparison includes family, parameters, bar size, exits, costs,
window, limits, filters, model and ticker universe. Names and notes do not create
new identities. The exact default-five-minute/both-sides/range-stop spec with
only `rvol >= 2.0` is neither reserved nor completed. All 14 existing ORB IDs
have materially different canonical specifications; none is a renamed equivalent.

These are **existing discovery results**, not reruns or evidence for the exact
candidate. Negative mean R means losing after the Factory's modeled costs.

| Existing candidate | Material difference from requested spec | Trades / trading days | Mean R | Total R | Profit factor | Mean R minus random | Weekly-cluster t |
|---|---|---:|---:|---:|---:|---:|---:|
| `op-599834809b` | 15-minute range, RVOL ≥1.5 | 652 / 240 | -0.0361 | -23.5450 | 0.8837 | -0.0139 | -0.4254 |
| `op-72f0fc136f` | No RVOL filter; 09:45–16:00 window | 5,091 / 314 | -0.0119 | -60.7654 | 0.9726 | +0.0166 | 0.7646 |
| `op-63dc1c56a3` | 15-minute range, no RVOL filter | 6,325 / 314 | -0.0086 | -54.5985 | 0.9753 | +0.0134 | 0.7481 |

All three failed screen. The other 11 ORB IDs also failed screen:
`op-a3e4e69a6a`, `op-2a811caf9b`, `op-3e18b7a299`, `op-7f71884194`,
`op-a879437c70`, `op-febb969e20`, `op-8676dbe66f`, `op-30d48ea079`,
`op-2dbca51a67`, `op-1e7fdc3455`, `op-45ea65a5cd`.
A losing nearby variant does not prove the requested threshold loses; it does
remove any basis for calling this family an established edge.

**No eligible free evaluation exists.** Under the live continuous-search
accounting, all distinct IDs, including failed screens and reservations, count.
The next reservation would be candidate 83 if the ledger is unchanged; its
confirmation threshold would be `required_t(83) = 3.2377367481`. Main's older
standalone CLI accounting is not a substitute for the live wrapper. Neither a
scratch discovery backtest, `--rerun`, a new name nor a paper label avoids the
attempt cost. The last search record does not authorize restarting the paused
search or spending a fresh attempt. This request conditions evaluation on not
spending one; therefore no new performance run was made.

The official wrapper retains the 288-attempt / 86,400-second window budgets,
900-second evaluation timeout, reservation-before-evaluation, duplicate refusal,
writer lock and week lock. These are unchanged. Before any future authorized run,
re-read the live ledger and budget, carry the reviewed loader fix into that
checkout without dropping its custom loader integration, and use its official
single-candidate path. Do not merge the research-ledger branch wholesale into
application main.

## 2. Data and validation boundaries

Source: local Alpaca SIP stock-minute cache,
`/Users/user/TradeJournal/backend/data/alpaca_cache/stocks/1Min/sip`.
The audit read discovery JSON only (July 3, 2023–September 30, 2024), checked
regular-session minute timestamps against weekdays/NYSE holidays and early
closes, and counted missing minutes, duplicates, off-date records and invalid
OHLCV. Later-period **filenames only** were counted, not opened. This is a
coverage check, not a strategy evaluation. It did not compute signals or returns.

| Coverage group | Discovery day files / expected | Days with all first five minutes | Days with every RTH minute | Missing RTH minutes |
|---|---:|---:|---:|---:|
| NBIS | 0 / 314 | 0 | 0 | Not available |
| LLY | 314 / 314 | 291 | 75 | 1,272 |
| NFLX | 314 / 314 | 314 | 178 | 511 |
| AVGO | 314 / 314 | 312 | 106 | 1,997 |
| COIN | 314 / 314 | 314 | 308 | 8 |
| GS | 314 / 314 | 304 | 75 | 2,518 |
| CAT | 314 / 314 | 311 | 78 | 1,318 |
| MU, META, AAPL, AMD, TSLA, GOOG, AMZN, NVDA, MSFT, MRVL, PLTR; SPY context | Each 314 / 314 | Each 314 | Each 314 | 0 |

No duplicate RTH minute, off-date row or invalid OHLCV was detected by these
checks. Each available discovery ticker has 21 June 2023 warmup filenames;
warmup content was not re-audited. NBIS starts October 21, 2024. All other core
tickers have 186 confirm-A and 189 confirm-B filenames; NBIS has 172 and 189.
Filename availability does not establish protected-data quality. No NBIS backfill
or replacement was invented. Missing minutes can reflect no qualifying trades,
feed gaps or halts; this audit cannot distinguish them. The current resampler can
form partial five-minute bars. Changing that policy now would change the frozen
strategy and is outside this repair.

Discovery file hashes and the audit script were retained in local scratch
`/private/tmp/orb-readiness-20261025/coverage.{py,json,log}`; this path is not a
portable dataset or a committed performance artifact. Report counts describe
that local snapshot, not an immutable vendor release. Corporate actions, inferred
split adjustments and survivor selection remain limitations; shape checks do not
certify economic correctness.

**Loader defect found and repaired:** `BarStore` previously read all source days
and/or deserialized an unbounded pickle before trimming the series to a stage's
cutoff. The same pattern exists in the live Factory checkout. The evaluator
received a trimmed series, so this finding is not proof that later prices entered
its statistics. It nevertheless violated the physical data-access boundary.
The patch filters filenames before minute reads and keys memory and disk caches
by cutoff. Bounded requests cannot consume a legacy unbounded cache. No protected
bar content was opened to reproduce this defect; the regression uses synthetic
three-stage data and a poisoned unbounded pickle.

Frozen gates remain:

| Stage | Dates | Acceptance |
|---|---|---|
| Screen | 2023-07-03–2024-09-30 | ≥100 trades, mean R >0 after costs, weekly-cluster edge t ≥2 |
| Confirm A/B | 2024-10-01–2025-06-30 / 2025-07-01–2026-03-31 | ≥30 each; positive mean R and edge each; pooled multiplicity-adjusted t; positive with costs ×3; at least half qualifying tickers positive; positive without best ticker |
| Exam | 2026-04-01 onward | Once, after confirmation; ≥30 trades, positive mean R and edge |

The Factory uses weekly clustering, not the invalidation study's day bootstrap.
No gate, split or statistical test was replaced. Earlier hand research had seen
some later history; fixing the loader cannot make historically seen data pristine.

## 3. Frozen executable research specification

Machine-readable [spec](../specs/opening_range_breakout_rvol2_v1.json):
**`op-998d19a73d`**. A regression pins its canonical equality to existing defaults
plus exactly one filter, and verifies that renaming cannot create another ID.

- **Universe:** NBIS, MU, META, AAPL, AMD, LLY, TSLA, GOOG, AMZN, NFLX, NVDA,
  MSFT, AVGO, COIN, GS, CAT, MRVL, PLTR. SPY supplies context, not an added entry
  ticker. This is the existing core, not a point-in-time all-stock universe.
- **Bars and entry:** five-minute regular-session bars, America/New_York. The
  first 09:30–09:35 bar defines the opening high and low; it cannot signal.
  First subsequent close strictly above the high signals long; strictly below
  the low signals short. Each direction is consumed once per session, including
  a rejected/filtered signal. Earliest possible signal closes at 09:40, with
  entry at the next bar's open. Missing opening bar means no opening range.
- **Only extra filter:** RVOL ≥2.0 at the signal close. Factory RVOL is cumulative
  session volume divided by same-time average volume over ten prior observed
  sessions, requiring five valid histories. Nonfinite values fail the filter.
  It is not an opening-five-minute top-20 rank, news catalyst or earnings label.
- **Fill:** next bar open, adversely slipped by `max($0.01, price × 0.0001)`.
  A gap through the intended stop prevents entry. No other entry window.
- **Invalidation:** opposite opening-range boundary, fixed at signal. Stop exits
  include adverse slippage; gaps can lose more than 1R. No profit target,
  trailing stop, breakeven move, maximum-minute exit or stall exit. Exit at the
  last available session bar close if not stopped; maximum one session.
- **Limits:** one position per ticker; at most two entries and two losses per
  ticker/session. No default maximum-loss-R limit. These are not portfolio caps.
- **Accounting:** R is entry-fill-to-stop risk. There are no shares, cash account,
  portfolio equity curve, financing, borrow costs or option contracts in this
  specification. No dollar profitability, CAGR or account drawdown is available.

Implementation anchors: `factory_rules.py` (defaults, canonical identity,
`run_candidate`, signals and fills), `factory_data.py` (session features),
`factory_gates.py` (baseline and acceptance), under `backend/app/engine/`.
The current live-bar `on_bar` strategy path is the intended future reuse point;
a new paper service must demonstrate prefix-by-prefix parity with this research
engine, not reinterpret its prose.

## 4. Baseline, costs and generalization

The frozen random reference samples entries approximately every 15 minutes with
rotating offsets, the same sides/window/exits/costs and an ORB stop-distance
calibration from the candidate's period-wide median risk/ATR. It does **not** apply
the candidate RVOL filter or reproduce its session entry caps, opportunity times,
capital competition and non-overlapping positions. It is a research timing
reference, not a matched investable portfolio. Its period-derived stop calibration
is not an ex-ante paper sizing rule. This construction cannot establish an
unbiased, capital-matched dollar advantage by itself. Preserve it for the frozen
gates; do not quietly replace it after seeing outcomes. Any later stronger
benchmark needs a separately preregistered scope.

The default one-tick-or-one-basis-point slippage is not measured bid/ask execution.
It omits commissions/fees, short borrow availability and financing, latency,
market impact, halt handling and account constraints. Costs ×3 is a stress test,
not proof that those omissions are covered. Full-period and baseline R averages
cannot be interpreted as actual position-sized P&L.

The literature motivates a hypothesis, not a transferable result. The cited
[primary paper abstract](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284)
studies a broad US-stock universe over 2016–2023. Its full text was not accessible
in this audit; rule differences summarized in the October evidence note are not
independently revalidated here. This core-18, cumulative-RVOL, close-confirmed,
range-stop implementation is a proxy, not a replication of that paper.

Reasons an apparent edge might fail to generalize include hand-selected surviving
large names, NBIS absent from discovery, correlated technology exposure, short-side
eligibility, volume-regime shifts, gap/partial-bar handling, split inference and
cost underestimation. Thousands of trades share only roughly 65 discovery weeks
and 78 confirmation weeks; minimum trade counts do not guarantee statistical
power. With attempt-83's threshold near 3.24, a rough equal-week heuristic requires
weekly mean edge / weekly standard deviation around `3.24 / sqrt(78) ≈ 0.37`.
This is a scale illustration, not a formal power calculation for the Factory's
clustered estimator. Failure to validate can mean a weak effect, no effect or
insufficient independent information. It never licenses lowering the gates.

## 5. Stocks versus a realistic options version

Stocks are closest to the existing evidence: entry and invalidation directly use
the underlying. Even stock paper execution needs a dollar-risk budget, gross/net
and correlated exposure caps, portfolio daily-loss cap, deterministic simultaneous
signal priority, shortability/account eligibility, price freshness and halt rules.
A sizing design can cap shares by both `risk_budget / abs(entry-stop)` and available
notional; gaps remain unbounded by that nominal risk. These operational inputs are
not frozen or authorized here. Turning both-sides research into long-only trading
would also change the candidate.

Long calls/puts add spread, volatility, theta, expiry, liquidity and contract
selection. An underlying stop does not imply a fixed option loss. The historical
journal selects trades the owner actually took; it is not the opportunity set for
this ORB and cannot supply missing contracts or unbiased option execution returns.

| Source / existing facility | Evidence and limitation |
|---|---|
| Alpaca historical options | Documentation starts February 2024, leaving the first seven months of discovery uncovered. Actual OPRA quotes require the appropriate subscription; indicative quotes are not consolidated executable bid/ask. [Official historical guide](https://docs.alpaca.markets/us/docs/historical-option-data) |
| Alpaca prospective stream | OPRA or indicative feed by entitlement; quote messages include timestamp, bid/ask, sizes and exchanges. Options quote wildcard subscriptions are unavailable. Capture selected contracts and feed identity explicitly. [Official stream guide](https://docs.alpaca.markets/us/docs/real-time-option-data) |
| Current option chain | Latest quote/trade/Greeks snapshots do not reconstruct a point-in-time historical chain. [Official chain endpoint](https://docs.alpaca.markets/us/v1.1/reference/optionchain) |
| Tradier | Current brokerage quotes can support prospective capture; sandbox data is delayed. Intraday timesales retention is short, and expired-option daily history is unavailable. This is not a 2023–2026 bid/ask archive. [Official market-data guide](https://docs.tradier.com/docs/market-data) |
| Potential paid archives | Massive documents OPRA quote files from March 7, 2022; Databento documents OPRA history from March 28, 2023 and instrument definitions. These could cover the dates in principle, subject to entitlement, completeness, cost and licensing verification. No subscription was bought or historical paid request made. [Massive quotes](https://massive.com/docs/flat-files/options/quotes), [Databento OPRA](https://databento.com/blog/opra-data) |
| Repository caches | `alpaca.py` option bars are trade OHLC, not quote paths. `options_recorder.py` records end-of-day strike/type/OI/volume, not historical bid/ask. Existing chain display does not prove durable prospective quote retention. |

A defensible options project needs a separately frozen contract policy before
looking at performance: permitted expiries/DTE, strike or delta selection,
standard versus adjusted deliverables, deterministic ties, maximum spread,
minimum displayed size, quote age and missing-data refusal. Historical selection
must use only contracts and information available then; no future volume/OI or
surviving-contract selection. A selector cannot depend on historical Greeks that
are unavailable. Do not sweep these inputs until something wins.

The quote archive must retain contract identity/multiplier/deliverable, underlying
signal, exchange event and local receive timestamps, bid/ask and sizes, conditions,
feed/entitlement, entry eligibility and exit reason. Simulate entry at ask and exit
at bid with explicit delay, size limits and per-contract fees, plus adverse
sensitivity; midpoint and option-minute highs are not executable fills. Stale,
crossed, one-sided or absent quotes must produce an unresolved/skipped event with
its reason, not an invented fill. Full-premium-at-risk sizing gives a conservative
contract cap; an underlying stop cannot guarantee its smaller planned loss.

**Forward hypothesis only:** the first options study could map each underlying
long/short signal to one long call/put under one owner-approved deterministic
selector. No option edge, selector, numeric risk allocation or options activation
is approved by this report. Underlying validation is a prerequisite, not evidence
that this mapping will survive spreads and volatility decay.

## 6. Smallest next milestone and acceptance

This PR supplies preparation only: cutoff-scoped cache I/O, synthetic regressions,
and the immutable candidate JSON. The focused Factory suites pass **162 tests**.
The regression checks later-first memory, poisoned legacy disk cache, reuse of an
earlier bounded cache, new protected filenames, and canonical ID stability.
It does not prove a live paper feed or real fills.

The next independently testable engineering milestone is a **disabled replay-to-
paper parity adapter** around Factory's existing live-bar strategy code, using
synthetic or already-permitted discovery fixtures. Acceptance should cover:

1. Identical signals, filter decisions, frozen stops, session limits and exit
   reasons for completed-bar prefixes versus `run_candidate`, including warmup,
   early close, gaps, incomplete bars and restart.
2. Durable idempotent event IDs and explicit signal-close, observed-at,
   order-eligible and simulated-fill timestamps. A signal received after the next
   bar opens cannot claim a retroactive open fill.
3. Separate append-only paper events, missing/late quote refusal and restart
   replay without duplicate entries. No broker-order path, production scheduler,
   real-journal writes or automatic enablement.
4. Paired reporting against Factory ideal fills and, only where owner-executed
   fills exist, read-only actual-fill matching by contract, side, quantity and
   timestamps. Report latency, spread/slippage, skipped and unfilled signals,
   and unmatched fills; never compare only conveniently filled winners.

The existing Practice P0 is not that adapter: its universe, 15-minute plan,
entry timing, stop-risk convention and additive slippage differ. Reuse its durable
ledger patterns where appropriate, not its strategy semantics under this ID.

Before prospective observation, freeze portfolio controls and a feasible
feed/latency convention, then obtain paper activation approval. Before a new
historical evaluation, obtain explicit authorization for the next counted attempt
and adopt the reviewed boundary fix in the official checkout. An authorized run
must stop at whichever existing gate fails; no favorable subgroup or revised
threshold becomes a replacement candidate. Until then, the honest state is
**prepared, untested exact hypothesis; no validated tradable strategy**.
