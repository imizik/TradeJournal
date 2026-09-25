# Isaac Market Map

`isaac_market_map.pine` is Step 5 of the
[TradingView signal loop](../tradingview-signal-loop-plan.md): one Pine v6
`strategy()` that both backtests in TradingView's Strategy Tester and sends
[v1 contract](../tradingview-webhook-contract-v1.md) JSON alerts to the ingress.
**The alerts are exactly the strategy's entries**, so the rules that produce the
backtest also produce the alerts.

It is built around how this account actually trades rather than around generic
setups. Every rule below cites the evidence it comes from.

## Evidence

Two sources, both in the repository:

- `backend/scripts/playbook_cohorts.py`: FIFO reconstruction of the Robinhood
  export in `backend/reports/` (1,088 option trades, Oct 2025 – Jul 2026, net
  +$6.4k, PF 1.07). It has dates only, no times.
- `backend/reports/edge_audit_2026-07-07.md`: the enriched journal
  (1,477 trades with times, greeks attribution and ATR-normalized path metrics).

| Finding | Number | Rule in the script |
|---|---|---|
| Open (9:30–10) and close (14–16) make money; midday loses on 63% of volume | PF 1.25 / 1.63 vs 0.92 | Signals in the open window and the power window only. Midday is off by default (`Midday entries`) |
| Winners barely go against you; losers do | Winner heat p90 0.38 ATR, loser p90 1.06 ATR | Stop is the structure level, capped at **0.4 × daily ATR** (`Max stop distance`) |
| Green trades ridden back to red | 308 trades, peak +$75k, realized −$60k | Stop moves to **breakeven at +0.75R**, and a trail starts at +1.5R |
| Theta ate the directional edge | Delta+gamma +$74k, theta −$72k | **Time stop**: out after 30 min unless the trade reached +0.5R |
| Re-entering right after an exit | <5 min: PF 0.73 | **15-minute cooldown** after every exit |
| 0DTE and 4–7 DTE work; 1–3 DTE and 22+ don't | PF 1.49, 1.52 vs 0.77, 0.56 | `dte_hint` in every alert: `0dte` by default, `4_7dte` only for overnight candidates |
| Next-day holds work; 2+ day holds don't | PF 1.63 vs 0.46 / 0.27 | Flat by 15:55. The optional overnight experiment exits by 10:00 the next session. Nothing is held 2+ days |
| Averaging down | 85 trades, −$13.1k, PF 0.39 | `pyramiding = 0`, so there is never a second entry. The script can't stop you doing it manually, so don't |
| Adding to winners | PF 1.44 | Not modelled: Strategy Lab rejects multi-leg trades. Do it manually, only above entry and only after breakeven |
| Bigger conviction pays | Premium 1,500+: PF 1.40 | Grade A = full size, B = half |
| Ticker cohorts | LLY, MU, AMD, META, SPY: PF 1.3–3.0. SNDK −$5.6k, NVDA PF 0.19, SLV, CVNA, MSFT | `Core` / `Avoid` ticker inputs. Avoid-list tickers get no signals unless you allow them |

**The ticker lists are in-sample.** They were picked from the same trades they
are scored on, so of course they look good. Treat them as a starting point
and re-score them on trades made after this commit. SNDK is still in your
September fills and is your single worst ticker.

## Setups

Everything is evaluated on bar close during regular trading hours (RTH), after
the opening range (OR) is complete. Trend setups also need close on the trade's
side of VWAP and EMA 9/20 stacked the same way.

| Setup | Long | Short | Stop level |
|---|---|---|---|
| `orb_break` | first close above the 5m OR high | first close below the OR low | the OR level |
| `orb_retest` | pullback within 0.1 ATR of a broken OR high that closes back above it, within 12 bars | mirror | the level |
| `pdh_break` / `pdl_break` | close crosses the prior-day high | close crosses the prior-day low | the level |
| `pdh_retest` / `pdl_retest` | retest of a broken prior-day level | mirror | the level |
| `hod_break` / `lod_break` | power window only: close above the session high | close below the session low | nearer of VWAP and EMA 20 |
| `vwap_reclaim` / `vwap_loss` | close back above VWAP after 2 closes below it, with EMA 9 > 20 | mirror | VWAP |
| `orb_fail` | break of the OR low that closes back inside and above VWAP within 3 bars | mirror | recent swing extreme |

Priority when several fire on one bar: retest, ORB, prior-day level, HOD/LOD,
VWAP, failed ORB. If a long and a short fire on the same bar, both are skipped.

**Grade (v1.1).** Every signal needs relative strength vs the benchmark of at
least **1.5% on the trade's side** since the 9:30 open (`Min relative strength`).
With it, A = RVOL ≥ 1.5 at the same time of day (full size), B = RVOL below
that (half size). Without it the signal is C, and C never trades. A failed ORB
is counter-trend, so it is never graded A. v1.0.0 needed only RS above 0; see
the round 1 results below for why that changed.

**Defaults (v1.1).** Longs only (`Allow shorts` off), no midday entries,
opening-range retests off, prior-day retests on.

**Limits.** At most 3 entries a day. No more entries after 2 full-stop losses.
No entries after 15:45.

## What each alert carries

`levels`: `entry_ref`, `stop`, `be_trigger`, `trail_start`, prior-day
high/low/close, premarket high/low, OR high/low, HOD/LOD, VWAP, EMA 9/20, and
daily ATR.

`context`: `grade`, `size` (`full`/`half`), `score` (0–5 confluence),
`window`, `tier`, `dte_hint`, RVOL, RS vs SPY, VWAP and EMA state, gap in ATR,
extension from VWAP in ATR, risk in ATR, time stop, and entries today.

The backend's scalp scorer still gives its own verdict from live Alpaca data.
The Pine fields are the reasoning at the moment of the signal.

## Backtest round 1 (v1.0.0)

Strategy Tester exports for MU, META, AAPL, NBIS and SPY on 5m, over the last
365 days (Oct 2025 – Sep 2026), are in `backend/TradingView/IMM_v1.0.0_*.csv`.
`backend/scripts/imm_export_cohorts.py` reproduces every number here.

**Overall: 1,432 trades, −32.8R, PF 0.94.** Roughly breakeven. What the
cohorts showed:

| Cohort | n | R | PF | Every quarter? |
|---|---|---|---|---|
| All shorts | 737 | −61.1 | 0.81 | No: negative even when filtered by RS |
| All longs | 695 | +28.3 | 1.10 | No: Q4 2025 negative |
| RS on the trade's side ≥ 1.5% | 549 | +55.4 | 1.29 | No: shorts drag it |
| **Longs with RS ≥ 1.5%** | **270** | **+64.4** | **1.85** | **Yes: PF 1.16 / 1.43 / 2.94 / 1.89, and every ticker positive** |
| RS 0–1.5% (the old grade allowed these) | 856 | −91.6 | 0.77 | — |
| Longs with RS ≥ 1.5%, midday | 18 | −2.9 | 0.64 | small n, but agrees with the journal audit |
| `orb_retest` long, all | 44 | −8.2 | 0.64 | — |
| SPY (RS against itself is always 0) | 35 | −8.0 | 0.54 | — |

v1.1.0 changes the defaults to match: RS ≥ 1.5% gate, longs only, midday off,
opening-range retest off. In the longs-with-RS cohort, RVOL added little (every
bucket below 2.0 was positive), so it now decides size rather than whether
to trade.

**These results are in-sample.** The filter was found by slicing this
same year, which was a bull tape (SPY 658 → 760) in which shorts were always
going to struggle. Treat "longs only" as a regime setting, not a law.
The honest tests still to come:

1. Re-export v1.1.0 on the same tickers and confirm it reproduces the
   cohort. The trade sequence changes when cooldowns and daily limits apply
   to different trades, so the result won't match exactly.
2. Run it on tickers that weren't in this round (for example AMD, LLY, TSLA,
   GOOG) and on the prior year, using the
   [Python backtester](#backtesting-in-python).
3. Forward: paper-trade the alerts before trading them live.

SPY cannot produce signals under the RS gate, because its strength against
itself is 0. Trade SPX/SPXW from a separate strategy, not this one.

## Set it up in TradingView

1. Pine Editor → paste the file → **Add to chart** on a 2m or 5m chart.
   Extended hours changes the signals, not just the premarket levels: EMA 9
   and 20 run through every bar on the chart, so premarket bars move them at
   the open. The round 1 exports were made with extended hours on. Pick one
   setting and keep it, and give the Python backtester the same one
   (`--extended-hours`).
2. **Check compile first.** This file has never been compiled; there is no
   Pine compiler in this repository's CI. Fix whatever the editor flags.
3. Open **Pine Logs**. Each entry logs its exact JSON. Check that one line
   has `bar_time_ms` as a plain integer and the `alert_id` ends in
   `:<setup>:<long|short>`.
4. Strategy Tester: run it on each core ticker over the history your plan
   gives (5m usually reaches ~60 sessions). Compare against the table above;
   R-multiples matter more than dollars here.
5. Alert: condition **Isaac Market Map → alert() function calls only**, webhook
   URL `https://<ingress-host>/tradingview/webhook?token=<token>`, message
   left blank. "Order fills" alerts are not JSON and the ingress will reject
   them. You need one alert per chart/ticker, and webhooks need a paid plan.
6. **Bump `Indicator version`** whenever you change a signal-affecting input.
   Alert ids include it, and the contract requires it.

## Validate it in Strategy Lab

Export Strategy Tester → **List of trades** as CSV and import it on
`/strategy-lab` with source timezone `America/New_York`. Every entry and exit
already carries `sl1` metadata, so runs can be split by setup, grade, window,
tier, RVOL and exit reason (`stop`, `be`, `trail`, `time`, `eod`, `target`,
`overnight_exit`). `backend/tests/test_pine_market_map.py` imports a
reconstructed export through the real importer.

## Backtesting in Python

`backend/scripts/backtest_market_map.py` runs the same rules over Alpaca bars
for many tickers in one command, so nobody has to export Strategy Tester
results chart by chart:

```bash
cd backend
python scripts/backtest_market_map.py MU META AAPL NBIS SPY --days 365
python scripts/backtest_market_map.py AMD LLY TSLA GOOG --days 365 --set allow_shorts=true
```

Add `--extended-hours` when the TradingView chart has extended hours on, as
the round 1 charts did: the EMAs, and so the signals, depend on it.

It prints a cohort report grouped by ticker, setup, side, grade, window, exit
reason and tier (n, total R, average R, win %, PF, max drawdown in R, then
dollars) and writes it, plus one TradingView-shaped "List of trades" CSV per
ticker, to `backend/data/market_map/<run>/`. The CSVs carry the same `sl1`
entry and exit comments as the Pine, so they import on `/strategy-lab` with
source timezone `America/New_York`. R is net PnL over the risk budget for the
trade's size, the same definition `imm_export_cohorts.py` uses, so Python and
Strategy Tester numbers are on one scale.

**The port.** `backend/app/engine/market_map.py` is the Pine, bar for bar,
with every input as a `MarketMapConfig` field. `--profile v1.0.0` selects the
v1.0.0 inputs and grading that produced the round 1 exports; `--set
field=value` overrides any field. It is pure (no network, no database); the
script fetches bars with the cached clients in `app/engine/alpaca.py` and
resamples 1-minute bars to `--timeframe` (default 5). Execution matches the
`strategy()` settings: signals and entries on bar close, stop orders checked
intrabar from the next bar (a bar that opens through the stop fills at the
open), a stop moved on a bar takes effect on the next unless that bar's own
close is already through it (`process_orders_on_close` gives the order one
attempt there, so it fills at that close), 2 ticks of slippage on market and
stop fills.

**Data differences to expect.** The default IEX feed prints a small share of
volume, so RVOL (A vs B, full vs half) will not match TradingView; the script
warns, and `--feed sip` fixes it where the key allows. Daily ATR comes from
Alpaca daily bars, which are split- and dividend-adjusted while minute bars
are raw; the script warns when their closes disagree, and `--atr-source
minutes` builds ATR from regular-session minute bars instead. It asks for
daily bars only through the day before `--end`, since ATR is the prior day's
and SIP refuses a same-day daily request. Bars are regular hours only unless
`--extended-hours` is given; match the chart, because the EMAs depend on it
(the round 1 exports need it, see parity below).

**What is verified.**

- `backend/tests/test_market_map.py`, on synthetic bars: every setup on both
  sides, every exit reason (`stop`, a gap through the stop, `be`, `trail`,
  `time`, `eod`, `target`, `overnight_exit`), the stop moving a bar late, a
  moved stop filling at the close it is already through (and that exit being
  noticed a bar later), the cooldown boundary, both daily limits, grades,
  midday modes, tiers, and the stop cap and floor. Every Pine input is
  checked against its `MarketMapConfig` default by reading the Pine source. Planted defects
  (breakeven at 0.5R, as a default and in the logic; a 10-minute cooldown;
  counting breakeven exits as losses; no slippage on stops; a network import)
  each fail it.
- `backend/tests/test_market_map_exports.py` checks the execution model
  against every one of the 1,432 trades in the round 1 exports: breakeven
  exits fill exactly 4 ticks under the entry fill, or worse when the stop was
  already through the price it filled at (a gap open, or the close of the bar
  that moved it), never better (254 exact, 51 worse); every time stop lasts
  30 minutes; every `eod` is the 15:50 bar; grade, size and window follow the
  v1.0.0 rules on all 1,432; the next entry comes at least 15 minutes after a
  stop-type exit and 20 after a market close (the script only notices those
  on the next bar, and TradingView shows both boundaries); no day has more
  than 3 entries or an entry after 2 full-stop losses.
- `backend/tests/test_market_map_report.py`: the CSVs import through the real
  Strategy Lab importer with no warnings, the report's R and drawdown math,
  the parity comparison, and the script end to end with a stub loader.

**Parity on real bars (run 2026-09-24 on SIP bars).** Given the bars
TradingView had, the port reproduces 1,229 of the 1,397 single-stock entries
in the round 1 exports (88.0%) on the same bar, side and setup, and 1,241 of
1,432 with SPY:

```bash
python scripts/backtest_market_map.py --profile v1.0.0 --feed sip --extended-hours \
    --start 2025-10-14 --end 2026-09-24 \
    --parity "TradingView/IMM_v1.0.0_*.csv"
```

| Ticker | TradingView entries matched | Port entries that match | Grade / size agree | Exit reason / time agree | Median \|difference\|: RVOL, RS %, gap ATR, risk ATR |
|---|---|---|---|---|---|
| AAPL | 280 / 326 (85.9%) | 87.0% | 92% / 92% | 94% / 92% | 0.097, 0.019, 0.013, 0.001 |
| META | 291 / 334 (87.1%) | 88.2% | 96% / 96% | 95% / 89% | 0.087, 0.030, 0.009, 0.002 |
| MU | 338 / 368 (91.8%) | 92.1% | 96% / 96% | 96% / 93% | 0.063, 0.031, 0.007, 0.001 |
| NBIS | 320 / 369 (86.7%) | 84.9% | 97% / 97% | 95% / 88% | 0.081, 0.071, 0.007, 0.003 |
| SPY | 12 / 35 (34.3%) | 57.1% | 100% / 100% | 92% / 83% | 0.132, 0, 0.007, 0.002 |

- **The exports were made with extended hours on.** The command as first
  written here (regular hours, `--warmup-days 1`) matched 68.4%. Its misses
  were mostly ORB and VWAP setups in the opening window where EMA 9 and 20
  sat the other way round: premarket bars move them at the open, and with
  `--extended-hours` those entries match. The one-day warm-up was wrong too.
  In the first two weeks the exports' RVOL fits a full 10-session history
  (median gap 9% with the default 20-day warm-up, as for the rest of the
  year, against 17% with one day), so the charts had history before
  2025-10-14.
- **One porting bug, fixed.** A stop moved to breakeven or trailed to a level
  that bar's close is already through fills at that close minus 2 ticks. The
  port used to wait for the next bar. 80 matched trades show it, and fixing
  it raised exit-time agreement from 82–88% to 88–93% on the four stocks.
- **What is left is the feed.** Of the 110 entries TradingView took where the
  port had no signal or a different setup, 80 hinge on a condition missed by
  under 0.01 ATR (a close against a level, VWAP or the other EMA) and 14 more
  by under 0.03 ATR. The other 16 trace to a VWAP 0.04–0.08 ATR apart, or to
  an earlier bar where the feeds disagreed: a 9:30 close 2 cents above the
  prior-day high, so the level broke later, or an opening-range high set by
  a sub-penny print. SIP and TradingView bars differ in three ways:
  - Closes: TradingView's fill equals the SIP close plus 2 ticks within a
    cent only a third of the time.
  - Extremes: SIP includes sub-penny and odd-lot prints. On matched trades
    its bar reaches past TradingView's in 58% of run-ups and 81% of drawdowns,
    so the port's stops and breakeven triggers trip a little sooner.
  - Opening volume: SIP's 9:30 minute carries derivatively priced prints at
    the opening price (1.77M AAPL shares on 2026-01-16), which pulls the
    first hour's VWAP toward the open.

  Port-only entries are the same near-misses the other way round, plus bars
  where TradingView was cooling down or at a daily limit after a trade the
  port did not take. The report calls those "no tradingview entry" because it
  cannot see TradingView's cooldown.
- **SPY trades on RVOL alone.** Its relative strength against itself is 0, so
  B needs RVOL ≥ 1.5. The feed's RVOL gap (median 0.13) decides most entries:
  19 of the 23 misses are grades.
- **The ATR source barely matters.** `--atr-source minutes` changes one entry
  in 1,432 and barely moves risk ATR. It narrows the gap ATR difference only
  on SPY (0.007 to 0.002), which pays the largest dividend of the five;
  Alpaca's daily bars are dividend-adjusted, which may be why. The ATR implied
  by the exports' stop exits is within about 0.1–0.8% of either source.

The comparison matches entries on timestamp, side and setup, prints the match
rate and every mismatch with a cause: a knock-on (one side was in a trade,
cooling down or at a limit because of an earlier difference), a grade that
came out differently (RVOL and relative strength depend on the feed), a
different setup on the same bar, or no signal at all (levels, VWAP or EMAs
saw different prices). Matched trades also report grade, size, exit-reason
and exit-time agreement and the median difference in RVOL, RS, gap and risk
in ATR; a gap difference points at ATR. Do not tune the port to raise the
match rate; explain the difference.

**Findings from the port.** A long and a short can never fire on the same
bar: every long setup needs the close above VWAP and every short below it, so
the "skip the bar when both fire" rule is kept but never triggers. Options
pricing (`--options`) is not built; parity, which it was waiting for, is
above.

## What is and isn't proven

- **Proven here:** every setup, on both sides, produces a payload that the real
  v1 parser accepts, with the canonical `alert_id`. The `sl1` comments import
  into Strategy Lab with no warnings or key conflicts. The test rebuilds all of
  this from the Pine source itself, and planted defects (a bad key, a changed
  id template, colliding `sl1` keys, a new number format, an invalid setup
  slug) all fail it.
- **Not proven:** that it compiles, that the setups make money, or that
  backtesting on the underlying says much about options (no theta, IV or
  spread; slippage is a flat 2 ticks). Exits are single-leg, but you scale
  out in practice. None of the rules above has been tested out-of-sample yet.
  The Strategy Tester runs are that test.
- **Not enforceable from a chart:** averaging down, caution when the day is
  green (audit: PF 1.00 when up more than $200 vs 1.31 when down), and holding
  1–3 DTE overnight. Those stay journal rules.
