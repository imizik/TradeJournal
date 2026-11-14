# QQQ intraday momentum (noise area): search on 2016-2021, exam on 2022-2026, result (2026-11-14)

Protocol: [`research/qqq-intraday-momentum/protocol.json`](../qqq-intraday-momentum/protocol.json) (`qqq-intraday-momentum-20261114-v1`), registered in #822 before any result of this rule on QQQ was computed. It ran once on 2026-11-14 with the script as merged in #822. Aggregates, including every searched combination, are in [`results.json`](../qqq-intraday-momentum/results.json).

The rule comes from Zarattini, Aziz and Barbon (2024). Each session, QQQ's "noise area" at each time of day is the open (or the previous close, if further out) plus or minus VM times the average absolute move from the open over the previous LOOKBACK sessions. At each check from 10:00 the rule goes long above the band and short below it, exits on a trailing stop, and is flat at the close. Decisions use the price at the check. Fills are at the next minute bar's open plus $0.01 a share each side.

## Search (2016-05-12 to 2021-12-31, 1,409 sessions, 180 combinations)

- **Chosen by the highest Sharpe at 1x:** lookback 60 sessions, VM 1.25, a check every 60 minutes, and the band-and-VWAP stop. On the search years it scored Sharpe 1.59 and +4.47 bp a day.
- **Every one of the 180 combinations had a positive search Sharpe.** All of the top ten checked once an hour. The paper's own settings (14, 1.0, every 30, band and VWAP) scored Sharpe 1.06 and +3.48 bp.

## Exam (2022-01-03 to 2026-11-13, 1,213 sessions, run once): worth a paper test

| Days | Mean net a day at 1x | 95% interval | 2022-2023 / 2024-2026 | At $0.02 a side | Sharpe |
|---|---|---|---|---|---|
| 1,213 | +4.40 bp | +2.10 to +6.85 bp | +4.46 / +4.36 bp | +4.16 bp | 1.32 |

All three conditions held:
- the interval is above zero;
- both exam periods are positive;
- the double-cost mean is positive.

This allows a QQQ intraday momentum paper book on the desk with the chosen settings, at 1x first.

## What else the exam shows (descriptive, not tested)

- **Steady, not lumpy:** every exam year was positive: 2022 +7.2 bp, 2023 +1.7, 2024 +3.3, 2025 +6.8, 2026 +2.8 a day. The second period, which starts after the paper's first version (May 2024), held at +4.36 bp.
- **What a year looks like:** it traded on 521 of 1,213 days (43%), with 625 trades. 361 ended at a stop and 264 at the close. Long and short trades were about even (322 / 303). Only about one day in five made money. Most trading days are small stop-outs, and the gains come from days that trend into the close.
- **At 1x:** $1 grew to $1.68 with a worst drawdown of 5.1%. QQQ buy-and-hold grew to $1.70 with a 35.3% drawdown (Sharpe 0.59). The rule matched the index's growth while flat every night and mostly out of the market.
- **With the paper's sizing (up to 4x, 2% daily volatility target):** $1 grew to $2.15, +6.57 bp a day, Sharpe 1.39, worst drawdown 7.1%.
- **The paper's own settings on the exam:** +5.26 bp a day at 1x (Sharpe 1.46, $1 to $1.86, drawdown 7.8%). With its sizing, $1 grew to $2.72 with a 15.6% drawdown. They did as well as the searched choice: the effect does not depend on fine-tuning.
- **Costs are small:** doubling the cost to $0.02 a side lowered the mean by only 0.25 bp a day, because it trades about half a time a day.

## Limits

- Fills are minute-bar opens plus a stated cost, not quotes. A cent a side covers QQQ's usual spread but not every fast market.
- The 15:59 bar's close stands in for the 16:00 close.
- The paper's sample (SPY, to April 2024) overlaps the first part of the exam on a different symbol. Its preferred longer lookback and wider band were in the grid.
- Margin interest and short borrow are left out. They matter for the levered version.
- The searched choice was one of 180 combinations. The exam is the honest check of that choice, and it held.
