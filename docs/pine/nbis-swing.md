# NBIS recovery swing, v0.1 (research)

A follow-on module of the Pine research framework written from the 2026
journal on 2026-09-24, implemented as a Python backtest (no Pine yet).
Every number is the framework's proposed default and none was fitted; two
gaps the framework leaves open are filled as stated below and not tuned.

## Rules

- 15-minute regular-session candles, long only.
- **Arm** once price has traded below the prior completed day's daily EMA 20.
  An arm lasts for the session of the most recent trade below it and the
  next session (`arm_sessions=2`, a choice made here), and triggers once.
- **Trigger** on a 15-minute close back above the 15-minute EMA 20 (the
  previous bar closed at or below it) that is also above the preceding three
  completed bars' highs. The arming bar never triggers. "EMA 20 on that
  timeframe" is read as the 15-minute EMA; `reclaim_level=daily_ema` is the
  other reading (a 15-minute close back above the daily EMA 20).
- **Enter** at the next bar's open. The stop is 0.1 ATR(14) below the lowest
  low of the last four completed bars, frozen.
- **Exit** at 2R, or at the end of the second session (the entry session is
  the first). Holding overnight is allowed for this module only. Every trade
  also carries the intraday-only exit on the same entry (same stop and
  target, flat at the entry session's close), the comparison the framework
  asks for.

Execution is the same as `docs/pine/vwap-reclaim.md`: next-open market
entries, resting stop and target, fills at the open when a bar (including an
overnight gap) opens through either, stop first when one bar reaches both,
slippage of the larger of one tick and 1 basis point.

## Running it

```bash
cd backend
python scripts/backtest_nbis_swing.py NBIS --start 2025-10-14 --end 2026-09-24 --feed sip
python scripts/backtest_nbis_swing.py NBIS MU META --start 2024-10-14 --end 2025-10-13 --feed sip
python scripts/backtest_nbis_swing.py NBIS --feed sip --set reclaim_level=daily_ema
```

The report has the framework's measures in R (the same as the VWAP module's),
then the same measures for the intraday-only exits on the same entries, then
the setup events. Runs land in `backend/data/nbis_swing/<run>/` with a
Strategy Lab CSV per ticker (`sl1`: setup, version, risk in ATR, distance
above the daily EMA, exit reason, R, sessions held, intraday R).

## Results

Run on 2026-09-27 on SIP bars.

| NBIS | Oct 2025 – Sep 2026 | Oct 2024 – Oct 2025 |
|---|---|---|
| **As specified** | 79 trades, +6.7R, PF 1.13 | 58 trades, +25.6R, PF 2.02 |
| Without the best trade | +1.5R | +21.6R |
| Intraday-only exits, same entries | −5.2R, PF 0.83 | +17.0R, PF 2.34 |
| Costs stressed to 3 bp | +5.5R, PF 1.10 | +25.4R, PF 2.02 |
| Daily-EMA reading | 33 trades, +4.3R, PF 1.23 | 21 trades, +4.1R, PF 1.51 |
| Every-bar baseline, same exits (avg R) | −0.056 against the strategy's +0.084 | +0.090 against +0.441 |

The same rules, unchanged, on MU, META, AAPL, AMD, LLY, TSLA and GOOG:
−4.9R (PF 0.99) over 494 trades in the recent year, +84.1R (PF 1.28) over
468 in the prior one, where every ticker was positive.

- **It is the first framework idea to survive costs.** Stops sit below four
  15-minute bars, so 1 bp a side is a small share of R: tripling costs moves
  NBIS from +6.7R to +5.5R and from +25.6R to +25.4R.
- **Holding overnight added value in both years**, for NBIS and for the other
  seven names, against exiting the same entries at the close. The price is
  gap risk: the worst NBIS trade is −4.0R, and META's worst −6.7R.
- **The setup beats buying at random.** With the same exits, an entry on
  every possible bar averages −0.056R on NBIS in the recent year; the
  strategy's entries average +0.084R. Across the eight names and two years it
  beats that baseline in 12 of 16 cases, but none by more than 1.4 standard
  errors on its own.
- **It is thin where it matters most.** The recent NBIS year is +1.5R without
  its best trade, and the recent year is breakeven on the other names. The
  strong prior year includes the April 2025 selloff and recovery, the regime
  a buy-the-reclaim rule suits best.

So v0.1 is a lead worth forward-testing, not a proven edge. The framework's
next step is to freeze this specification and collect new signals (its
suggested first checkpoint is 30–50 signals across at least 20 sessions)
before building on it.

## What is verified

`backend/tests/test_nbis_swing.py`, on synthetic 15-minute bars with ATR
exactly 1.0 and a daily EMA 20 pinned at 100: arming below the daily EMA and
the reclaim-and-breakout trigger; the four-bar stop and three-bar breakout
windows; no arm without a dip; the prior completed day's EMA, not today's;
the arming bar never triggering; an arm lasting two sessions; one trigger per
arm; the daily-EMA reading; the target, the stop, the two-session exit, an
overnight gap through the stop, and the intraday-only exit on the same entry;
the Strategy Lab CSV through the real importer; and the script end to end
with a stub loader. Planted defects (the arming bar triggering, no disarm, no
stop buffer, a three-bar stop window, a two-bar breakout, today's daily EMA,
one session too long, a 1.5R target, gaps filling at the stop, arms that
never expire) each fail it.
