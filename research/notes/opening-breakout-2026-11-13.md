# Opening breakout on stocks in play: result (2026-11-13)

Protocol: [`research/opening-breakout/protocol.json`](../opening-breakout/protocol.json) (`opening-breakout-20261113-v1`), registered in #788 before any data was read. It ran once on 2026-11-13 from main at 7baff6cdd plus #788 (the script matched the registered commit). Aggregates are in [`results.json`](../opening-breakout/results.json).

The data covered 714 sessions from 2024-01-02 to 2026-11-12, picking 20 stocks in play from about 1,000–1,600 candidates each morning. Of the 14,280 picks, 11,239 triggered (79%), and 103 had no bars after 09:35.

## Decision: no evidence either way (both tests)

| Test | Mean R a trade | 97.5% interval | Exploration / check | Costs tripled |
|---|---|---|---|---|
| Both sides | +0.073 | -0.037 to +0.184 | +0.040 / +0.110 | -0.478 |
| Long side | +0.073 | -0.080 to +0.238 | +0.045 / +0.104 | -0.488 |

Under the protocol, opening range breakouts are closed for this account, and no variant is tried on this history.

## What else the run shows (descriptive, not tested)

- **Before costs there is a signal:** +0.35R a trade, with half the sessions positive. One cent plus 2 bp a side, against a stop only 0.10 ATR away, costs about 0.28R a trade and takes most of it.
- **The profit is concentrated:** a 13% win rate, wins averaging +9R and losses -1.3R. Without the best 1% of sessions (7 days), the mean is +0.011R.
- **It depends on an unknowable detail:** whether the stop was touched inside the fill's own one-minute bar. Counting every touch in that bar as a stop gives -0.63R a trade. With a stop this tight, sub-minute order and real slippage decide the outcome, and one-minute history cannot show either.
- **By year:** 2024 -0.02R, 2025 +0.14R, 2026 +0.11R.
- **By relative-volume rank:** 1-5 +0.24R (2,757 trades), 6-10 +0.04R, 11-20 +0.01R. This is a slice chosen after seeing results. It can only be tested forward, on sessions not yet traded, under a new protocol id.
