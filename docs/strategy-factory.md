# Strategy factory

A pipeline that judges trading ideas automatically and records every one it
judges. Searching many variations always turns up a few that look good by
luck, so the factory's main job is to throw those out before anyone trades
them. This is step 1 of 3: the rules engine, the gates and the ledger. Step 2
is a weekly agent that proposes the next ideas from the ledger; step 3 paper
trades whatever passes.

The code: `backend/app/engine/factory_data.py` (bars, splits, indicators,
features), `factory_rules.py` (entry families, the execution model, specs),
`factory_model.py` (the learned filter), `factory_gates.py` (statistics,
gates, ledger records), and `backend/scripts/strategy_factory.py` (the bar
cache, the ledger file, the commands). Specs live in `research/specs/`, the
ledger in `research/ledger.jsonl`.

## How a candidate is judged

| Stage | Data it may see | What must hold |
|---|---|---|
| Screen | 2023-07-03 to 2024-09-30 | at least 100 trades; average R above 0 after costs; beats random entries with t ≥ 2 |
| Confirm | 2024-10-01 to 2025-06-30, and 2025-07-01 to 2026-03-31 | in each half, at least 30 trades, average R above 0 and better than random; across both halves, t against random above the bar; still above 0 with costs tripled; money made on at least half the tickers with five or more trades; still above 0 without its best ticker |
| Exam | 2026-04-01 onward, once | at least 30 trades; average R above 0; better than random |

- **Each stage loads only its own data.** The screen never loads a bar after
  September 2024, and the holdout is loaded only for a candidate that passed
  confirmation. A candidate that fails early leaves the later data unseen for
  the next idea.
- **Random entries** are the yardstick: an entry every 15 minutes of market
  time (the offset turns each session, so every time of day is sampled), with
  the candidate's exits, costs, entry window and sides, per ticker, period and
  side. Their stop is the family's own rule where it can be applied at any
  bar (the recovery swing's four-bar stop). For families whose stop depends
  on the setup it is the candidate's median risk in ATR for that period.
  "Edge" is a trade's R minus random entries' average for its ticker, period
  and side.
- **t is clustered by week.** Trades in the same week share the market's
  moves (a selloff arms every name at once), so treating them as independent
  overstates the evidence.
- **The bar rises with every try:** t ≥ Φ⁻¹(1 − 0.05/K), where K counts the
  candidates that have reached confirmation, this one included (Bonferroni,
  one-sided 5%). K = 10 needs 2.58, 20 needs 2.81, 50 needs 3.09, 100 needs
  3.29. Ideas tested by hand before the factory count too.
- **Learned filters** (meta-labeling) take the family's signals and learn
  which to keep: a logistic regression on the entry features, trained on the
  discovery-period trades of the same spec without the model, then frozen.
  It takes a trade when its chance of ending positive is at least the
  training base rate. Its screen is in-sample, so it goes straight to
  confirmation and counts toward the bar there. There it must also beat the
  same rules without it in each half. The rules without the model are judged
  and recorded first.
- **The ledger** gets one line per run: the spec, the code commit, the
  numbers per period, every check with its result, and the verdict. Its
  first nine lines are the ideas tested by hand before the factory existed
  (the Market Map versions, four VWAP reclaim variants, three NBIS swing
  readings). A spec whose id matches a hand-research line still runs once,
  and is counted once.

## Running it

```bash
cd backend
python scripts/strategy_factory.py prepare    # fetch missing SIP minute bars; needs the Alpaca key
python scripts/strategy_factory.py run ../research/specs/failed_breakout_v0.1.json
python scripts/strategy_factory.py ledger     # every candidate, its verdict, and the current bar
```

`run` never touches the network. It builds regular-session bars per ticker
and timeframe from the local SIP minute cache once, into
`backend/data/factory/bars/`. A spec already in the ledger is not run again
(`--rerun` forces it, and it is still counted once). `--no-exam` stops before
the holdout. Each run writes `report.txt` and `trades.csv` (every trade with
its entry features) to `backend/data/factory/runs/<time>-<id>/`, and a line
to the ledger.

## Writing a spec

```json
{
  "name": "Failed breakout short v0.1",
  "family": "failed_breakout",
  "params": {"confirm_bars": 3},
  "exits": {"target_r": 1.5, "max_sessions": 1, "max_minutes": 20},
  "window": [935, 1500],
  "limits": {"max_entries": 2, "max_losses": 2, "max_loss_r": 2.0},
  "costs": {"slippage_ticks": 1, "slippage_bps": 1.0},
  "filters": [{"feature": "trend", "max": 0}],
  "model": null,
  "tickers": "core",
  "notes": "where the idea came from"
}
```

Only `family` is required; everything else defaults to the family's research
framework values. `window` is the fill time (HHMM, inclusive); `max_sessions`
above 1 holds overnight; `tickers: "core"` is the 18 names below. A `model`
of `{"kind": "logistic"}` uses all ten features; `features` and `l2` narrow
it. The id is a hash of everything except the name and notes, so renaming a
spec does not make it a new idea.

Features, read at the signal bar from completed data only, signed so that a
positive value is "with the trade" for longs and shorts alike:

| Feature | Meaning |
|---|---|
| `minutes` | minutes from 09:30 to the signal bar's close |
| `rvol` | session volume so far over its average at the same time of day across the prior 10 sessions |
| `gap` | the session's opening gap from the prior close, in daily ATR(14) |
| `day_move` | the signal close against the session open, in daily ATR |
| `trend` | the signal close against the prior day's daily EMA 20, in daily ATR |
| `trend_slope` | the daily EMA 20's change over the prior five sessions, in daily ATR |
| `rel_strength` | percent return since the close five sessions ago, minus SPY's |
| `spy_trend` | SPY against its prior daily EMA 20, in SPY's daily ATR |
| `spy_day` | SPY against its session open, in SPY's daily ATR |
| `risk` | the signal close to the stop, in ATR(14) of the chart bars |

## Families

All share one execution model, the one the Market Map port and the research
backtests use. A signal is decided at a bar's close and entered at the next
open, slipped by the larger of the tick count and the basis points. The stop
is frozen at the signal; if the open is already through it there is no
trade. The stop and a target in R rest from the fill, and a bar that opens
through either fills at the open (overnight gaps included). When one bar
reaches both, the stop fills first. Stops and closing exits slip; targets do
not. The trade leaves at a bar's close once it has held `max_minutes`, or at
the last bar of its `max_sessions`-th session. One position per ticker, and
the session limits block new entries for the rest of a session.

- `recovery_swing`: the NBIS recovery swing, 15-minute bars, long. Arm
  under the prior day's daily EMA 20 for two sessions; trigger once on a
  close back over the 15-minute EMA 20 (or the daily EMA with
  `reclaim_level="daily_ema"`) that clears the prior three highs; stop 0.1
  ATR under the last four lows; 2R or two sessions.
- `vwap_reclaim`: the framework's first build, one-minute bars, both sides.
  A reclaim (rejection) of session VWAP over (under) EMA 9 arms; a close
  beyond the arming bar within three bars confirms; a close back through VWAP
  cancels; no entry more than 1 ATR from VWAP; stop 0.1 ATR beyond the
  setup's extreme; 1.5R, 20 minutes, 09:35-15:00 fills, two entries a session
  and none after two losses or −2R.
- `failed_breakout`: the framework's META module, built here first.
  One-minute bars, short by default (`sides` adds the long mirror at the
  prior day's low). A bar that trades over the prior session's high and closes
  back under it arms. A close under that bar's low within three bars
  confirms, and a close back over the prior high cancels; the window and the
  cancel rule are this module's reading, since the framework leaves both
  open. Stop 0.1 ATR over the rejection bar's high, with the VWAP module's
  exits and limits.

The first two reproduce the engines they came from (`nbis_swing` and
`vwap_reclaim` on branch `claude/nbis-recovery-swing`) trade for trade on the
18 tickers from June 2023 to September 2026: 4,134 and 20,600 identical
trades.

## Data

- Alpaca SIP minute bars from the local cache, June 2023 onward, for the core
  universe (NBIS, MU, META, AAPL, AMD, LLY, TSLA, GOOG, AMZN, NFLX, NVDA,
  MSFT, AVGO, COIN, GS, CAT, MRVL, PLTR; the journal's names and its
  comparison list), with SPY as the market. NBIS starts at its October 2024
  relisting.
- Regular session only. The 13:00 closes (2023-07-03, 2023-11-24,
  2024-07-03, 2024-11-29, 2024-12-24, 2025-07-03, 2025-11-28, 2025-12-24)
  are confirmed in SIP volume: the closing cross prints at 13:00 and 15:59 is
  nearly empty.
- Share splits are taken out: an overnight jump within 4% of a whole ratio is
  a split, and earlier prices are put on the new scale. That finds NVDA
  2024-06-10, AVGO 2024-07-15 and NFLX 2025-11-17, all 10-for-1. Daily bars
  are built from the same bars; dividends are not adjusted.

## First results (2026-09-28)

| Candidate | Reached | Result |
|---|---|---|
| NBIS recovery swing v0.1 | screen | failed: +0.040R a trade over 1,471 trades, +0.051R better than random, t = 0.73 |
| the same with a learned filter | confirmation | failed: +0.068R a trade, +0.119R better than random at t = 1.51 against a bar of 2.58; below the plain rules in Oct 2024 - Jun 2025 (+0.093R against +0.107R) |
| VWAP reclaim/rejection v0.1 | screen | failed: −0.090R a trade after costs, no ticker positive; the entries do beat random ones (+0.046R, t = 3.06) |
| Failed breakout short v0.1 | screen | failed: −0.095R a trade, 3 of 17 tickers positive, t = 1.48 |

- The recovery swing's "2.7 standard errors" from the hand test treated its
  trades as independent. Clustered by week on the discovery period it is
  t = 0.73, because the names dip and reclaim together.
- The learned filter's weights are all under 0.1 per standard deviation: the
  ten features say little about which recovery-swing entries work.
- Both one-minute families time their entries better than random, and costs
  sink both. That is the lead for the next ideas: fewer trades with more
  room per trade, so costs are a smaller share of R.

The ledger counts 10 candidates at confirmation, so the next one there needs
t ≥ 2.61.

## What is verified

`backend/tests/test_factory.py`, on synthetic bars:

- The data: sessions ending at 13:00, splits and reverse splits (and a crash
  that is not one), EMA and ATR seeding, VWAP resets, and features that do
  not change when later bars do.
- The execution model: every exit path (resting stop and target, gaps
  through either, both on one bar, the session count, the time limit), orders
  across the close, one position at a time, the session limits, and the
  entry window.
- Each family's arming, triggering, cancelling and expiry, with exact stops
  and fills.
- Specs and their ids, the logistic fit recovering a known effect, the
  statistics and each gate.
- The evaluation end to end: a synthetic edge passes every gate, one that
  stops in the holdout fails the exam, and a failed screen or a failed
  confirmation never loads later data. A learned filter trains on the
  discovery period only and must beat its parent.

`backend/tests/test_strategy_factory.py` runs the script with a stub minute
source: the bar cache, the ledger, reruns, a model spec judging its parent
first, and the committed specs and ledger. Thirty-nine planted defects (a
fill at the signal close, no stop slippage, the target first, today's daily
EMA, no chase limit, the holdout loaded early, t not clustered, a bar that
never rises, the model trained on everything, and more) each fail the tests.

## Limits

- The holdout months were seen by hand research before the factory existed
  (the Market Map, VWAP and NBIS runs covered 2025-26). From here on nothing
  reads them outside an exam.
- The bar counts named ideas, not cohort scans: the Market Map's 14-setup
  scan behind the `orb_retest` lead is not in it, and an idea drawn from that
  scan should add those looks.
- Results are on the underlying. Options add spread and theta.
- The universe was picked from the journal, names already traded, not a
  random sample.
- Weekly clustering approximates how the names move together; a two-session
  hold can cross into the next week.
