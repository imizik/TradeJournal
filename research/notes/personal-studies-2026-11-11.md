# Stop after green, size cap and long holds: registered run

**Run once on 2026-11-11. Two rules were rejected as demonstrated savings. Exiting long holds by the close of session 1 or 3 passed its registered test, but that pass does not yet support a rule (see [what the long-holds pass means](#what-the-long-holds-pass-means)).**

Protocols, registered on 2026-10-24 before any outcome was computed: [stop after green](../stop-after-green/protocol.json), [size cap](../size-cap/protocol.json), [long holds](../long-holds/protocol.json). Code: `backend/scripts/personal_trading_studies.py`, unchanged since registration. Every result is exploratory, as the protocols state: the October 21 audit had already read both periods.

## Results

Dollar difference is the rule minus what actually happened, over all 1,531 trades. The range is the registered Bonferroni interval (98.3% for three rules, 97.5% for two) from 2,000 resamples by trading day.

| Study | Rule | Trades touched | Difference (range) | Verdict |
|---|---|---|---|---|
| Stop after green | stop once the day is above $0 | 775 skipped | +$6,566 (−$8,920 to +$25,219) | reject |
| | above $250 | 382 skipped | +$4,269 (−$6,678 to +$18,309) | reject |
| | above $500 | 195 skipped | +$4,150 (−$4,848 to +$16,919) | reject |
| Size cap | 1.5 × trailing 20-trade median premium | 414 capped | −$1,270 (−$12,175 to +$12,103) | reject |
| | 2 × | 245 capped | −$1,580 (−$11,315 to +$8,593) | reject |
| Long holds (25 trades, −$6,525) | exit at the close of session 1 | 25 | +$5,402 (+$2,326 to +$9,672) | eligible for a forward test |
| | session 3 | 25 | +$2,141 (+$14 to +$4,238) | eligible for a forward test |
| | session 5 | 25 | +$1,590 (−$93 to +$3,544) | reject |

- **Stop after green.** Every threshold pointed the same way in both periods, and the skipped trades returned less per dollar than the kept ones (−5.3 and −12.0 points at $0). Each also beat trading less by the same premium (+$12,661 at $0, range −$1,479 to +$27,379). No range clears zero, so nothing is demonstrated. The largest loss (−$4,350) and the worst day (−$3,608) would not have changed.
- **Size cap.** Larger trades were not worse per dollar than smaller ones (+0.4 points at 1.5 ×, −1.6 at 2 ×). The cap would have cost money in the first period (−$2,953 at 1.5 ×) and saved it in the second (+$1,683). It does shrink the tail: the largest loss goes from −$4,350 to −$1,690 and the worst day from −$3,608 to −$1,723 at 1.5 ×. A cap limits bad days; this history does not show it makes money.
- **Long holds.** Exiting at the close of session 1 saved money on 22 of the 25 trades and cost money on 3. It held at the 9% stress cost (+$4,846) and in both periods (+$2,217 on 16 trades, +$3,186 on 9).

## What the long-holds pass means

The 25 trades are the ones that ended up held longer than 10 days, a group known to have lost money. The protocol says so itself: "a saving on it is expected unless the losses came late, so only a decision against the rule is strong evidence."

There is a second limit. Nobody knows on day 1 which trades will become long holds. A real hold limit closes every trade still open at the close of session N, and that includes the roughly 320 other overnight trades, which the October 21 audit put at about +$700 together. This study did not test them. The usable question is "every trade still open at the close of session N", on the same data. That needs its own registered protocol before anything is computed.

## What differs from the registration

- **The trade file is not the registered one.** The October 24 extract was no longer on the Mac. A fresh read-only extract was taken the registered way, with the owner's approval. It has 1,531 trades and +$12,722, against 1,528 and +$14,038, because three more long holds have expired since. Its hash is `4ada80b1…`, not the registered `023e0e11…`, and each results file records `extract_is_registered: false`.
- **Long holds ran twice mechanically.** A first pass against cached bars only analyzed no trades and computed no outcome. The recorded run fetched 25 option daily-bar windows from Alpaca.
- **Code.** Run from `5ae35afa8` with a clean checkout. The 34 tests for this script and the exit study pass.

## Next, listed and not built

1. No forward test of stop-after-green or a size cap is supported as a money-saving rule. A cap as a limit on the worst day is a separate choice that this study does not decide.
2. Register and run the "still open at the close of session N" study before any hold limit is tested forward.
3. One historical run per protocol id: these three are spent. A changed constant is a new protocol id.

[Stop-after-green results](../stop-after-green/results-2026-11-11.json) · [Size-cap results](../size-cap/results-2026-11-11.json) · [Long-holds results](../long-holds/results-2026-11-11.json)
