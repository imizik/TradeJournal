# Top-5 opening breakout on 2016-2023 with tape fills: result (2026-11-13)

Protocol: [`research/opening-breakout-top5/protocol.json`](../opening-breakout-top5/protocol.json) (`opening-breakout-top5-20261113-v1`), registered in #796 before any 2016-2023 data was read. It ran once on 2026-11-13 with the script as merged in #796. Aggregates are in [`results.json`](../opening-breakout-top5/results.json).

The data covered 1,982 sessions from 2016 to 2023. On 1,971 of them the rules picked 5 stocks in play. The 11 without picks are the first ten sessions with enough history (late January to early February 2016) and 2020-03-16, when a market-wide halt at the open left no opening range. Of the 9,855 picks, 7,812 triggered (79%). Every triggered entry and stop found a quote. Only one exit fell back to the bar close.

## Decision: loses money (both tests)

| Test | Trades | Mean R a trade | 97.5% interval | 2016-2019 / 2020-2023 | Extra cent a side |
|---|---|---|---|---|---|
| Both sides | 7,812 | -0.41 | -0.51 to -0.31 | -0.31 / -0.51 | -0.59 |
| Long side | 3,778 | -0.49 | -0.61 to -0.35 | -0.36 / -0.61 | -0.67 |

Under the protocol, opening range breakouts on stocks in play are closed for this account. That includes the top-5 slice. No further variants are tried on any history, and no live paper recorder is built.

## What else the run shows (descriptive, not tested)

- **On one-minute bars the same picks look profitable:** v1's bar rules with its costs give +0.12R a trade on these 7,820 trades. That is the same direction as the +0.24R slice on 2024-2026 that prompted this test. Filled from the tape, the same trades average 0.53R worse. The bar result was produced by how the bars fill entries and stops, and the tape removes it.
- **The spread alone is most of a stop:** the quoted spread at entry averaged 0.60R (median 0.43R). With a stop 0.10 × ATR away, a fill at the ask (long) or bid (short) one second after the breakout starts the trade most of the way to its stop.
- **90% of trades stopped out:** 7,019 of 7,812, with 9.7% winners averaging +8.6R and losses averaging -1.38R. Stops sometimes filled well past their level in fast names.
- **Every year and every rank lost:** 2016 was about even (-0.03R). Every year from 2017 to 2023 was between -0.21R and -0.60R. Ranks 1 to 5 were all between -0.25R and -0.55R, with rank 1 worst.
- **Short side alone:** -0.34R (4,034 trades).
- **Without the best 1% of sessions:** -0.51R.
- **The bar method's fill-bar worst case** (any touch of the stop inside the fill's minute counts as stopped) gives -0.68R. The tape result lies between the bar result and that worst case, much closer to the worst case.

## Limits

- The one-second delay, the tape-trade rule and fills at the displayed best quote are stated assumptions. A real retail stop order could trigger and route differently. Displayed size could make large fills worse, which would only deepen the loss.
- Polygon's listing snapshots are thinner in 2016 (about 3,000 names against 4,500 or more later). Early-2016 picks come from a smaller pool. Both halves lost, so this does not change the decision.
