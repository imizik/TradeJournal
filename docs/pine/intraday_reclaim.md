# Intraday Reclaim v0.1

`intraday_reclaim.pine` is the first build in the
[research framework](research-framework.md): the MU intraday
reclaim/rejection strategy, version 0.1.0. It is a Pine v6 `strategy()` for
1-minute regular-hours candles.

**Status:**
- It has never been compiled; there is no Pine compiler in this repository.
- It has never been backtested.
- The framework's numbers are research defaults, not fitted values.

## How each rule was read

The framework leaves some calls open. These are the ones the script makes. A
different reading is a new version, not an edit.

| Rule | What the script does |
|---|---|
| 1. Session | VWAP resets on the exchange's first regular bar (`session.isfirstbar_regular`). The entry window is checked at the **fill time**: the confirmation bar must close between 09:35 and 15:00 ET inclusive, which on 1m means confirmation bars 09:34–14:59. The session exit uses the exchange's last-regular-bar flag, so early closes need no clock time. That exit fills at the last bar's close, the only same-bar fill in the script. |
| 2. Arm | Needs the previous bar in the same session, so it never arms on the first regular bar. It also never arms on the last bar, after the entry window, or while a position or entry is open. One armed setup at a time. |
| 3. Confirm | Checked on the 1st–3rd bar after arming. A close back through VWAP cancels the setup, and cancelling wins when one bar would do both. A confirmation outside the entry window or past the chase limit cancels it too; there is no second trigger. |
| 4. Entry | Market order at the confirmation close, filled at the next bar's open. **Chase limit:** reject when the confirmation close is more than 1.0 × ATR(14) of the chart timeframe away from VWAP on the trade's side. Slippage is 1 tick in the strategy properties. The fill-vs-signal gap is recorded as `entry_slip_r`. |
| 5. Stop and size | **Stop:** the lowest low (long) or highest high (short) from the arming bar through the confirmation bar, plus 0.1 ATR, rounded to the tick. It is sent with the entry and never moves. **Size:** $100 ÷ (signal close − stop), capped at equity ÷ price. Margin simulation is off. **R** is measured from the actual fill to the stop. |
| 6. Exit | **Target:** while the entry fills, it sits at 1.5R from the planned entry. At the fill bar's close it moves to 1.5R from the actual fill. **Max hold:** the first bar close 20+ minutes after the fill sends a market close, which fills at the next open (exactly 20 minutes on 1m). Ambiguous bars: see below. |
| 7. Limits | Per chart only. A losing trade is net PnL < 0. The −2R session limit uses actual R. |
| 8. Output | Chart marks: armed ▲▼, cancelled ×, trigger and exit labels, frozen stop/target lines, and a status table. Every event goes to Pine Logs as JSON. Alerts go out on `triggered`, `exit_signal` and `closed`; `armed`, `cancelled` and `filled` alert only if you turn them on. |

**Ambiguous bars.** A target fill can land on a bar whose range also reached
the stop. TradingView's intrabar guess (or Bar Magnifier, if your plan has it)
decides which filled first. These trades can't be found from the export:
TradingView's per-trade excursions stop at the exit fill. That held for all
509 stop exits in the Isaac Market Map exports, where adverse excursion
equalled the loss every time. So the script counts them itself. The table's
**Fill check** row shows the count and the run's total R if every one had
been a stop.

**Quirks to measure, not fix in 0.1:**
- On gap days, ATR(14) runs wide for about the first 15 minutes, because the
  first bar's true range includes the overnight gap. That loosens the chase
  limit and the stop buffer early.
- On early-close days, entries are allowed until the last bar but one, and
  anything still open is closed at the close.

## Run it

1. **Chart:** NASDAQ:MU, 1 minute, extended hours **off**, timezone
   **Exchange**. The report reads export times as New York.
2. **Load it:** Pine Editor → paste the whole file → **Add to chart**. The
   first job is getting it to compile. Paste any error back and it gets fixed.
3. **Properties:** leave capital at 100,000, slippage at 1 and commission at
   0. Turn **Bar Magnifier** on if your plan has it, and write down whether it
   was on.
4. **Check the table:** the first row should read `0.1.0 · baseline`.
   Leave **Use the v0.1 baseline preset** on; with it on, the other inputs
   are ignored.
5. **Export:** Strategy Tester → List of trades → export. Save it as
   `backend/TradingView/IR_v0.1.0_NASDAQ_MU_<date>.csv`.
6. **Transfer check:** repeat on NASDAQ:META with nothing changed.

Then, from `backend/`:

```bash
.venv/bin/python scripts/pine_research_report.py "TradingView/IR_*.csv" --replay 10
```

## What the report prints

The report prints the framework's measures in R:
- trades and independent sessions
- expectancy, profit factor and max drawdown
- average win and loss, worst trade and worst day, and holding time
- totals without the best trade and without the best day
- the same split by side, ticker, month and exit reason
- totals at +1 and +2 ticks of extra slippage per side

It also prints mechanics checks:
- holds past the limit
- sessions over the entry limit
- entry slippage
- stop fills past the stop

**Replay checklist.** With `--replay 10` it lists ten winners and ten
losers, spread across the run. Check each one on the chart before trusting
any total:
- the armed bar
- the confirmation close
- the fill at the next open
- the stop, the target and the exit

That is the framework's v0.1 exit criterion. It proves mechanics, not
profitability.

Runs with a different version, variant, timeframe or settings are never
pooled. Every order carries `ver`, `variant` and `cfg`, the exact settings,
so an export can't be misattributed.

## Record every run

**Strategy Lab.** Create three separate strategies: "Intraday reclaim",
"NBIS recovery swing" and "META failed breakout". Add version 0.1.0 with this
file's source, and import each export with source timezone
`America/New_York`. Fork a new version for any change; never edit a version
that already has runs.

**Record per run:**
- symbol and timeframe
- first and last trade date
- slippage, commission and Bar Magnifier on/off
- the commit
- the table's Config row

## What is and isn't proven

**Proven here** by `backend/tests/test_pine_intraday_reclaim.py`, which
rebuilds the output from the Pine source:
- The preset equals the framework's numbers.
- The trade metadata imports into Strategy Lab with no warnings.
- The report computes R from the actual fill.
- Every alert event is JSON carrying ticker, exchange, bar-close time,
  version and setup id, and the live v1 ingress rejects every one of them.

Ten planted defects each failed the suite.

**Not proven:**
- that it compiles
- that the chart matches the rules (the replay checklist is that test)
- anything about profitability

The options boundary in the framework applies in full. A short signal is a
bearish underlying simulation, not a put. If a result only survives at 1 tick
of slippage, it won't survive option spreads.

## Round 1 (v0.1.0 baseline, MU)

The runs are BATS:MU and BATS:META (the transfer check, nothing changed) on
1m, September 24, 2025 – September 24, 2026. The exports are
`backend/TradingView/IR_v0.1.0_BATS_*_2026-09-24.csv`.

**Mechanics are clean:**
- 0 holds past 20 minutes; every time exit is at exactly 20.
- 0 sessions over 2 entries.
- Entries fall between 09:35 and 14:56.
- The worst stop fill landed 0.06R past the stop.

**Overall:** 374 trades over 216 sessions, **+20.2R, +0.054R a trade, PF
1.10**, max drawdown 24.1R. That becomes +14.6R at +1 tick a side and +9.1R
at +2.

**It decayed:**

| Half | Trades | R | PF |
|---|---|---|---|
| Sep 24 – Mar 23 | 187 | +32.8 | 1.37 |
| Mar 24 – Sep 24 | 187 | −12.6 | 0.88 |

Both sides went negative in the second half: longs +14.6R → −11.2R, shorts
+18.3R → −1.4R.

**META transfer check:** 351 trades, **+23.3R, +0.067R a trade, PF 1.13**,
max drawdown 14.2R, and +17.0R at +1 tick a side. It held up across both
halves: +12.6R, then +10.7R. So the MU decay is MU, not the rules, but both
edges are thin.

**Hold off on:**
- Time-of-day slices: 09:35–10:00 made +16.6R, 10–11 lost 4.4R. They are
  in-sample and noisy, not a filter.
- Any conclusion before the ambiguous-bar counts from the table's Fill check
  row, and the replay checks.

### Rerun on NASDAQ data (supersedes the BATS numbers)

The BATS runs above used one exchange's volume, and VWAP is the setup. The
same settings on NASDAQ:MU and NASDAQ:META are in
`backend/TradingView/IR_v0.1.0_NASDAQ_*_2026-09-25.csv`.

| | Trades | R | Per trade | PF | Max DD | +1 tick/side | 1st half | 2nd half |
|---|---|---|---|---|---|---|---|---|
| MU | 359 | +24.5 | +0.068 | 1.14 | 17.3 | +19.8 | +30.5 | −6.0 |
| META | 349 | +28.4 | +0.081 | 1.16 | 10.3 | +22.1 | +6.0 | +22.4 |
| Both | 708 | +52.9 | +0.075 | 1.15 | 19.3 | +41.9 | | |

**The feed changed most of the trades.** Only 171 of MU's and 102 of META's
entries match their BATS runs (same minute and side). Every number from here
on uses NASDAQ data only.

**Mechanics are still clean.** One stop fill landed 0.28R past the stop on a
gap; everything else was within 0.1R.

**MU's second half is still negative, just less so.**

**Fill check (ambiguous bars):** 0 ambiguous target bars on MU and on META.
That count covers only the trades on the 1-minute bars the chart had loaded
(34 on MU, 39 on META), not the deep-backtest year. Over the year, 27 of the
240 target exits came within a minute of the fill. If every one of those had
really been a stop, the NASDAQ total would fall from +52.9R to −14.1R. That
is a bound, not an estimate: the loaded sample had none.

**Next:** v0.2 changes only the exit, and only after the replay checks pass.
