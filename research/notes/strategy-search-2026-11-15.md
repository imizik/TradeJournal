# Four-family strategy search: search 2016-2021, exam 2022-2026, result (2026-11-15)

Protocol: [`research/strategy-search/protocol.json`](../strategy-search/protocol.json) (`strategy-search-20261115-v1`), registered in #831 before any result of these rules on these ETFs was computed. It ran once on 2026-11-15 with the scripts as merged in #831. Aggregates, including every searched setting, are in [`results.json`](../strategy-search/results.json).

Each family's settings were searched on 2016-2021 and scored by Sharpe ratio. Only its best setting ran on 2022-2026, once, with a 99% month-bootstrap interval because there were four exams. Costs are $0.01 a share a side intraday, or 0.02% a side on daily closes.

## Decisions: no evidence either way, all four (closed, no variants)

| Family | Chosen setting (search) | Exam statistic | 99% interval | 2022-23 / 2024-26 | Stress |
|---|---|---|---|---|---|
| ETF intraday momentum (13 ETFs) | lookback 90, VM 2.0, every 60, opposite stop (search Sharpe -0.07) | -0.86 bp a day | -3.15 to +0.97 | -1.71 / -0.27 | -1.34 |
| Dip buy (14 ETFs), timing only | RSI(2) < 20, no trend filter, exit above 3-day average or 10 days (Sharpe 0.70) | +1.49 bp a day over exposure | -0.23 to +3.36 | +1.08 / +1.77 | +0.92 |
| Trend switch (QQQ) | 100-day average, 1% buffer, weekly (Sharpe 1.30) | Sharpe -0.01 vs holding QQQ | -0.92 to +0.86 | +0.28 / -0.29 | -0.02 |
| Opening gap (13 ETFs) | fade gaps of at least 1 range, in 09:31, out 11:00 (Sharpe 1.00) | +0.36 bp a day | -0.45 to +1.17 | -0.20 / +0.76 | +0.27 |

Under the protocol, each family is closed: no new grid, settings, symbols or filters on any history.

## What the run shows (descriptive, not tested)

- **The intraday momentum rule did not travel beyond QQQ.** On the 13 other ETFs, every one of the 180 settings had a negative search Sharpe on 2016-2021. In the exam only the tech-heavy funds and SPY were positive: SMH +4.1 bp, XLK +2.8, SPY +1.1. The other ten were negative, from XLU -3.6 to XLY 0.0. Without SPY, XLK and SMH the book lost 1.9 bp a day, and the paper's own settings lost 1.5 bp on the 13. The QQQ pass (#825) stands on its own exam, but the effect looks specific to QQQ and tech rather than general to index ETFs. Read the QQQ paper book with that in mind.
- **Dip buying came closest.** Its timing earned +1.49 bp a day above the same exposure held passively, and was positive in both exam periods and at the higher cost. The interval's low end was -0.23 bp, so it missed by a small margin. As a plain book it averaged +2.73 bp a day (Sharpe 0.82) with an 8.2% worst drawdown, invested about a quarter of the days. Equal-weight buy-and-hold of the 14 ETFs earned +5.16 bp a day (Sharpe 0.79) with a 20.5% drawdown. 178 of the 180 search settings had a positive search Sharpe. 2024 was the one losing exam year on timing (-0.86 bp).
- **The trend switch matched holding QQQ on a risk basis.** It cut the worst drop from 34.7% to 19.7% but gave up return: $1 grew to $1.47 against $1.76, with Sharpe 0.60 against 0.62. It was invested 69% of the days. At 3x daily leverage it grew $1 to $2.28 with a 49.7% drawdown; 3x buy-and-hold grew to $2.46 with a 79.6% drawdown, ignoring financing and decay.
- **Gap fading barely moved.** Only 23% of the 48 search settings were positive. The chosen fade traded on 21% of days for +0.36 bp a day.

## Limits

- Intraday fills are minute-bar opens plus a stated cost. Daily fills are adjusted closes plus a stated cost.
- Minute bars are split-adjusted only, so ex-dividend opens look like small gap downs.
- Leverage figures ignore financing, borrow and the decay of daily-reset funds.
- The trend switch's cash earns nothing.
