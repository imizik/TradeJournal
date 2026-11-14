# Momentum pullback on 2016-2026 daily bars: result (2026-11-14)

Protocol: [`research/momentum-pullback/protocol.json`](../momentum-pullback/protocol.json) (`momentum-pullback-20261113-v1`), registered in #805 before any multi-day return was computed. It ran once on 2026-11-14 with the script as merged in #805. Aggregates are in [`results.json`](../momentum-pullback/results.json).

The rule: buy a six-month leader (top fifth of liquid US stocks, ahead of QQQ, above its 50-day average) at the open after three quiet lower closes that reach its 20-day average. Exit on a close below the pullback low, on no progress by the third session, or after ten sessions. From July 2016 to October 2026 it gave 17,519 signals. 4,983 were skipped because the name already had an open trade, which left 12,534 trades.

## Decision: no evidence either way (both tests)

| Test | Trades | Mean a trade | 97.5% interval | 2016-2019 / 2020-2022 / 2023-2026 | Doubled costs |
|---|---|---|---|---|---|
| Beats the market (net minus SPY over the same hold) | 12,534 | -0.06% | -0.39% to +0.30% | -0.15% / +0.20% / -0.20% | -0.21% |
| Pullback adds (net minus random same-day leaders) | 12,534 | +0.04% | -0.18% to +0.27% | -0.01% / +0.14% / -0.02% | — |

"Worth a paper test" needed the interval above zero, every period above zero and doubled costs above zero. None of the three held, so under the protocol this pullback rule is closed. No variants (other lookbacks, averages, pullback lengths or exits) are to be tried on any history. Plain momentum without the pullback was not decided here.

## What else the run shows (descriptive, not tested)

- **It roughly matches SPY, with far more risk:** a trade averaged +0.24% after costs over 4.7 sessions. SPY averaged +0.30% over the same holds. The median trade lost 1.25%, and only a third of trades made money.
- **One year carries all of the result:** 2020 averaged +1.46% over SPY a trade. Nine of the other ten years were below SPY, and 2023 was worst at -0.55%. Without the best 1% of months the mean is -0.12% over SPY.
- **Most trades stop out:** 7,825 stops, 1,238 no-progress exits, 3,462 time exits and 9 end-of-data exits.
- **The stop is often already hit at the open:** 2,073 trades (17%) opened at or below the pullback low. The pullback low is usually close to the entry, so many stops are tight.
- **The mean R is misleading:** the mean is +0.73R, but 467 trades had stops so close that a normal move counted as more than 20R. The median trade is -1.09R, and the mean without those trades is -0.57R.
- **Buying the leaders on a random day did no better:** the random same-day leaders averaged -0.09% a trade against SPY (+0.21% net). So the pullback timing neither helped nor hurt measurably. Leadership alone did not beat SPY over these short holds either.

## Limits

- Fills are at the daily open. A real open order in a fast name can fill worse; the cost line only approximates that.
- Dividends are left out on both sides. This slightly flatters SPY.
- Six-monthly listing snapshots can miss short-lived names. 2016 snapshots are thinner.
- Split-only adjustment does not handle spin-offs or reused tickers. Such days can create false stops or distort momentum.
