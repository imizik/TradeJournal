# Can a check spot a SPY trend day early? (October 14, 2026)

Research only, no option prices. `detect.py` scores 12 intraday checks over 157
sessions (March 2 – October 13, 2026: 19 SPY trend-down days, 24 trend-up).
Each check fires at most once a day, at the first of 10:30 / 11:00 / 12:00 /
13:00 / 14:00 where it holds. Full table: `out/detect.md`.

## Findings

- **Nothing reliably spots a down-trend day early.** The best down checks were right
  about one time in three: SPY 0.3 ATR below the open and below VWAP since 10:00
  was right 33% (6 of 18), SPY+QQQ+IWM aligned 27%, VIXY confirmation 22%, volume
  1.3× 0 of 4. "Prior day coiled + base" was 4 of 7, too few to trust.
- **Late checks catch down days but the move is mostly spent.** "New session low
  after 12:00" caught 14 of 19 down days at a 48% hit rate, but SPY moved only
  +0.04 ATR further on average from the 13:00 check to the close.
- **Breadth at 11:00 does not separate.** Across 50 large caps, the median share
  below VWAP was 56% on trend-down days vs 50% on choppy days; the 70% threshold
  never fired.
- **Up days are easier**: SPY volume 1.3× (4 of 5 right) and VIXY falling (5 of 7)
  looked useful, but samples are tiny.

## Meaning

Price, breadth, volume and VIX on their own cannot tell a real down day from a
fake-out by late morning in this period. The input not tested here is the macro
context (calendar events such as CPI and the reaction to them), which needs an
economic-calendar source. That supports a judgment-based market read for Jo,
recorded with a timestamp and scored against these simple checks, rather
than another fixed rule.
