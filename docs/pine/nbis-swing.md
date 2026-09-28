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

Run on 2026-09-28 on SIP bars. The daily EMA 20 is built from the same raw
regular-session minute bars as the 15-minute chart: Alpaca's daily bars are
dividend-adjusted (older prices sit below raw ones for any dividend payer)
and carry 51 stale bars at the halted price for NBIS before its October 2024
relisting, which moved its first weeks' results (58 trades, +25.6R, before
the fix).

| NBIS | Oct 2025 – Sep 2026 | Oct 2024 – Oct 2025 |
|---|---|---|
| **As specified** | 79 trades, +6.7R, PF 1.13 | 51 trades, +20.2R, PF 1.90 |
| Without the best trade | +1.5R | +16.2R |
| Intraday-only exits, same entries | −5.2R, PF 0.83 | +13.6R, PF 2.28 |
| Costs stressed to 3 bp | +5.5R, PF 1.10 | +20.1R, PF 1.90 |
| Daily-EMA reading | 33 trades, +4.3R, PF 1.23 | 16 trades, +3.5R, PF 1.66 |
| Every-bar baseline, same exits (avg R) | −0.056 against the strategy's +0.084 | +0.090 against +0.396 |

**The wider test decides it: v0.1 is not a strategy yet.** The same frozen
rules on 17 more liquid names (MU, META, AAPL, AMD, LLY, TSLA, GOOG, AMZN,
NFLX, NVDA, MSFT, AVGO, COIN, GS, CAT, MRVL, PLTR) over three years, the
first of which nobody had looked at. Ticker-years with a stock split are left
out (NVDA and AVGO before mid-2024, NFLX in 2025–26):

| Year | Ticker-years | Trades | R | PF | Positive | Beat the every-bar baseline | Edge over baseline | Intraday-only R |
|---|---|---|---|---|---|---|---|---|
| Oct 2023 – Oct 2024 | 15 | 960 | +67.1 | 1.10 | 7 | 10 | +0.072R | −30.3 |
| Oct 2024 – Oct 2025 | 16 | 1,058 | +130.4 | 1.19 | 12 | 12 | +0.119R | +49.9 |
| Oct 2025 – Sep 2026 | 17 | 1,325 | −22.2 | 0.98 | 8 | 11 | +0.066R | −41.3 |
| All | 48 | 3,343 | +175.3 | 1.08 | 27 | 33 | +0.084R | −21.7 |

- **The entry timing is the one consistent thing.** In every year the
  strategy's entries beat an entry on every possible bar with the same
  exits, by +0.07 to +0.12R a trade; pooled that is 2.7 standard errors,
  which overstates it because the names move together.
- **The strategy as a whole is thin.** +0.05R a trade and PF 1.08 across all
  48 ticker-years, a loss in the most recent year, and that is on the stock,
  before the theta and spread of an options version.
- **Holding up to two sessions beat the intraday-only exit on the same
  entries in all three years.**
- **Costs do not decide it.** The stops sit below four 15-minute bars, so
  tripling slippage moves NBIS by about 1R a year.
- NBIS is positive in both of its years, but it is one of several names that
  are (PLTR, MRVL, LLY and TSLA have comparable years), and choosing it
  because it did well would be choosing on the result.

By the framework's acceptance rule this does not pass: it relies on the
regime (the 2024–25 selloff and recovery suited a buy-the-reclaim rule) and is
flat to negative otherwise. What it does show is an entry signal that is
better than chance. The framework's next steps apply to that: change one
exit at a time (v0.2) or add one filter at a time (v0.3), choosing each
change on one year and keeping it only if it also holds on the other two.

## What is verified

`backend/tests/test_nbis_swing.py`, on synthetic 15-minute bars with ATR
exactly 1.0 and a daily EMA 20 pinned at 100: arming below the daily EMA and
the reclaim-and-breakout trigger; the four-bar stop and three-bar breakout
windows; no arm without a dip; the prior completed day's EMA, not today's;
the arming bar never triggering; an arm lasting two sessions; one trigger per
arm; the daily-EMA reading; the target, the stop, the two-session exit, an
overnight gap through the stop, and the intraday-only exit on the same entry;
the Strategy Lab CSV through the real importer; and the script end to end
with a stub loader, including that its daily EMA comes from the minute bars
and not from adjusted daily bars. Planted defects (the arming bar triggering, no disarm, no
stop buffer, a three-bar stop window, a two-bar breakout, today's daily EMA,
one session too long, a 1.5R target, gaps filling at the stop, arms that
never expire) each fail it.
