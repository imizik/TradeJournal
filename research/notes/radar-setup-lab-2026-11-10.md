# Radar setup lab

**No setup type or filter passed.** Six setup types and 72 setup-plus-filter combinations were scored as trades with the live setup card's exits. Five combinations, all of them gap reversal, made the shortlist from June 15 to August 31. None held up on the 36 held-back sessions from September 1 to October 21. Each was still ahead of random entries on average, but no 90% range stayed above zero. For the two live rules the answer is "no evidence either way." Neither should be demoted, and neither has earned a phone ping on this history.

The numbers that carry this:

- **Gap reversal** (`radar-reversal-v0`, live) was ahead of random stocks at the same minute in both halves. It led by +0.46 points a trade on the design half (90% range +0.15 to +0.75) and by **+0.14 on the held-back half (−0.07 to +0.34)** across 413 cards. Its strongest design slice, a gap up reversing down, fell from +0.63 to +0.03.
- **Dip turn** (`radar-dip-v0`, live) was also slightly ahead in both halves. It led by +0.06 on design and by **+0.11 on the held-back half (−0.04 to +0.26)** across 326 cards. That is too small and too uncertain to rank on.
- **Gap hold** was the only setup clearly worse than random on the held-back half: **−0.20 points a trade (−0.35 to −0.04)** across 649 cards, with 56% stopped out. It was not shortlisted, so this result is descriptive.

Opening drive (the frozen `radar-rules-v2` champion), the per-stock first pullback and the group laggard were all within ±0.05 points of random on the held-back half. Calls versus puts showed no stable pattern. The direction that led on the design half did not lead on the held-back half, for any setup.

All figures are the stock's own move in percent, with no costs. An option's spread and decay would come on top. Historical option quotes for these names are not saved, so no contract was scored.

## What was fixed first

The [protocol](../radar-setup-lab/protocol.json) was committed (`3cd434b31`) before any number was computed. It fixed:

- the setups, filters and exits;
- the random baseline;
- the shortlist rule: on the design half alone, up to five combinations with at least 40 cards, ranked by the low end of their 90% edge range, keeping only those whose range sat above zero;
- the pass rule: on the held-back half, at least 25 cards, mean edge above zero with the 90% range's low end above zero, and mean R above zero.

The design results and the [shortlist](../radar-setup-lab/design-picks.json) were committed (`605a6663d`) before the held-back half was opened. That half was then run once, with all 72 combinations together. Nothing was retuned.

**Setups.** Every setup reads only minute bars that have closed by the flag minute.

- **dip** and **reversal** are the live rules' own code (`radar_dip.replay`, `radar_reversal.replay`), run over passes rebuilt from the minute snapshot.
- **pullback** is the live `first_pullback.first_trigger` run on each tracked stock from 09:47 to 10:59.
- **laggard** flags a group of at least five stocks where 75% of the other members have moved at least 1 point against SPY since the open while this member has moved at most 0.25.
- **drive** and **hold** are the registered v2 clauses.

**Card and exit, as live.** Entry is the flag minute's close. The idea is wrong at the session low so far for an up setup, or the high for a down setup; reversal also counts the open, as its live card does. If that level is not beyond the price, there is no card. The trade exits at the first minute close at or through the level, otherwise at +60 minutes, otherwise at 15:55.

**Baseline.** Each card is compared with up to 20 other tracked stocks, drawn at random (seeded) and carded at the same minute in the same direction with the same exits. Edge is the card's result minus their average, so a market that simply rose that hour earns nothing. The ranges come from 2,000 resamples of whole sessions.

## Held-back half · 36 sessions (September 1 – October 21)

Results are percent on the stock. R is that result divided by the distance to the invalidation level. Edge is the card minus its random baseline, with the 90% session-resampled range. The verdict column applies only to shortlisted rows; all other rows are descriptive.

| Combination | Cards | /day | Green | Random green | Mean % | Median % | Mean R | Stopped | Edge % (90% range) | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| reversal · gap up reversing down | 205 | 5.7 | 53% | 39% | −0.05 | +0.06 | −0.01 | 11% | +0.03 (−0.19 to +0.26) | fail |
| reversal · first 30 min | 307 | 8.5 | 52% | 39% | +0.13 | +0.07 | +0.07 | 11% | +0.13 (−0.06 to +0.32) | fail |
| reversal · normal volume | 352 | 9.8 | 53% | 42% | +0.19 | +0.09 | +0.07 | 9% | +0.14 (−0.09 to +0.36) | fail |
| reversal · all | 413 | 11.5 | 52% | 41% | +0.17 | +0.07 | +0.07 | 9% | +0.14 (−0.07 to +0.34) | fail |
| reversal · gap ≥ 2% | 396 | 11.0 | 53% | 41% | +0.17 | +0.08 | +0.07 | 9% | +0.14 (−0.07 to +0.33) | fail |
| dip · all | 326 | 9.1 | 47% | 33% | +0.07 | −0.06 | +0.01 | 29% | +0.11 (−0.04 to +0.26) | live: no evidence either way |
| pullback · all | 993 | 27.6 | 48% | 42% | +0.04 | −0.04 | +0.01 | 9% | +0.01 (−0.07 to +0.09) | — |
| laggard · all | 575 | 16.0 | 38% | 41% | −0.03 | −0.20 | −0.18 | 41% | −0.03 (−0.08 to +0.02) | — |
| drive · all | 2,545 | 70.7 | 47% | 40% | −0.00 | −0.08 | −0.00 | 14% | −0.00 (−0.07 to +0.06) | — |
| hold · all | 649 | 18.0 | 33% | 31% | −0.24 | −0.54 | −0.56 | 56% | −0.20 (−0.35 to −0.04) | — |

Filters on the held-back half, as edge in points (each level's card count is in the summary file):

| Setup | Up / down | First 30 / 31–60 / later | With / against SPY | Heavy / normal volume | Gap ≥2% / smaller |
|---|---|---|---|---|---|
| dip | +0.11 / — | +0.12 / +0.03 / — | +0.19 / +0.04 | +0.01 / +0.12 | +0.18 / +0.06 |
| reversal | +0.24 / +0.03 | +0.13 / +0.26 / +0.04 | +0.12 / +0.15 | +0.11 / +0.14 | +0.14 / +0.17 |
| pullback | +0.07 / −0.05 | −0.00 / −0.01 / +0.13 | +0.01 / +0.01 | −0.02 / +0.01 | −0.02 / +0.02 |
| laggard | +0.02 / −0.07 | −0.04 / −0.06 / +0.02 | −0.04 / −0.02 | −0.08 / −0.03 | −0.10 / −0.01 |
| drive | +0.04 / −0.04 | −0.01 / −0.07 / +0.04 | −0.02 / +0.01 | −0.16 / +0.02 | +0.00 / −0.01 |
| hold | −0.06 / −0.30 | −0.20 / −0.28 / — | −0.25 / −0.09 | −0.25 / −0.19 | −0.22 / +0.01 |

Most dip and reversal filter levels were positive in both halves, but that mostly repeats the setup's own small lead. No filter level's range cleared zero on the held-back half. The levels that added the most to their setup in both halves were dip with the SPY backdrop (+0.09, then +0.19, against +0.06 and +0.11 for all dip cards), dip after a gap of at least 2% (+0.33, then +0.18) and reversal in the first 30 minutes (+0.60, then +0.13, against +0.46 and +0.14).

## Design half · 54 sessions (June 15 – August 31)

| Combination | Cards | /day | Green | Random green | Mean % | Mean R | Stopped | Edge % (90% range) |
|---|---|---|---|---|---|---|---|---|
| reversal · gap up reversing down | 390 | 7.2 | 59% | 38% | +0.73 | +0.26 | 10% | +0.63 (+0.27 to +0.98) |
| reversal · first 30 min | 639 | 11.8 | 58% | 40% | +0.81 | +0.27 | 15% | +0.60 (+0.24 to +0.95) |
| reversal · normal volume | 680 | 12.6 | 54% | 40% | +0.64 | +0.23 | 12% | +0.50 (+0.16 to +0.83) |
| reversal · all | 785 | 14.5 | 54% | 40% | +0.61 | +0.20 | 13% | +0.46 (+0.15 to +0.75) |
| reversal · gap ≥ 2% | 729 | 13.5 | 54% | 40% | +0.61 | +0.21 | 13% | +0.46 (+0.15 to +0.76) |
| dip · all | 511 | 9.5 | 46% | 37% | +0.08 | −0.02 | 33% | +0.06 (−0.13 to +0.25) |
| pullback · all | 1,443 | 26.7 | 47% | 41% | −0.06 | −0.02 | 11% | −0.02 (−0.09 to +0.04) |
| laggard · all | 1,135 | 21.0 | 41% | 40% | +0.07 | −0.01 | 43% | +0.08 (+0.01 to +0.16) |
| drive · all | 4,647 | 86.1 | 49% | 40% | +0.14 | +0.08 | 16% | +0.10 (+0.01 to +0.20) |
| hold · all | 1,216 | 22.5 | 38% | 34% | +0.11 | +1.71 | 52% | +0.03 (−0.20 to +0.28) |

Laggard, drive and several drive and laggard filter levels also had design ranges above zero. They ranked below the five reversal rows, so they were not shortlisted. Their held-back results above show they would have failed too. Every combination for both halves, with medians and R, is in the summary files.

## What to build from this

These items are listed, not built.

1. **No new setup type deserves a live rule on this history.** The per-stock first pullback, the group laggard and the opening drive were indistinguishable from random entries on the held-back half. Gap hold was worse than random.
2. **Keep both live rules recording, and demote neither.** Reversal and dip turn each led random entries by roughly 0.1 point a trade on the held-back half, but not reliably. Let the live paper book decide, and if they are ranked against each other, rank reversal first.
3. **No filter should gate the phone ping yet.** If anything ranks pings, the levels that added most to their setup in both halves are dip with the SPY backdrop, dip after a gap of at least 2%, and reversal in its first 30 minutes. Each needs live confirmation before it gates anything.
4. **Judge the live paper book the way this lab does.** Score each card against random tracked stocks carded at the same minute, in the same direction, with the same exits (`radar_setup_lab.Session.baseline`). A green paper record in a rising hour otherwise looks like edge.
5. **Save the card's option quote at entry and exit.** That makes it possible to score the contract, spread included, later. History cannot.
6. **Rerun this lab once on sessions after October 21.** About 40 new sessions would form a fresh held-back sample for reversal and dip. That needs a new registered protocol, and the existing reversal and dip rules must stay unchanged.

## Limits

- **The stock, not the option.** Results are the underlying's move, with no commission, spread or slippage. The median card's risk distance was 0.7–2.9% on the stock, depending on the setup. A held-back edge of about 0.1 point on the stock is small next to an option's spread and decay over an hour.
- **Minute closes only.** The snapshot has minute opens and closes, not intrabar highs or lows. Stops are checked on closes, so some stops that live would hit inside a minute are missed, and exits are at the minute's close. This applies equally to the setups and to the random baseline.
- **No headlines.** Catalysts are not available historically and were left out.
- **Small and not independent.** The study covers 36 held-back sessions, and confirmation was pooled over all flags, so the many cards on the same day are not independent. The session-resampled ranges account for that. The reversal rule was selected in the v2 search on these same sessions, so its numbers here are not a fresh test. The roster was assembled on October 21, after the period.
- **R is heavy-tailed.** When the invalidation level is a few cents away, R explodes. Gap hold's design mean R of +1.71 against a median of −1.00 is that effect. Edge is judged in percent for this reason.
- **Refetched inputs.** The minute price snapshot was not on this machine and was refetched the documented way (`ALPACA_DATA_FEED=sip`). Its hash differs from the v2 study's (`d7c21e0d…` against `d0dd5bd1…` for the design half). The refetched snapshot reproduces the v2 study's flag counts exactly: reversal 785 and 413, drive 4,664 and 2,549, hold 1,323 and 687. The volume snapshot's hash matches the v2 study's. One input is new: Alpaca SIP daily bars (adjustment `all`, April 1 – October 21), used only for the dip rule's 20-day test.

## Reproduction

From `backend`, with the v2 price and volume snapshots (see [the v2 note](radar-v2-search-2026-11-04.md#interpretation-and-reproduction)) and an empty results directory:

```sh
ALPACA_DATA_FEED=sip python -m scripts.radar_setup_lab fetch-daily DAILY
python -m scripts.radar_setup_lab design PRICES VOLUME DAILY --out RESULTS
python -m scripts.radar_setup_lab confirm PRICES VOLUME DAILY --out RESULTS
```

The summaries record input hashes. The card files hold every flag with its entry, level, exit, result, baseline and filters, one JSON line each.

[Protocol](../radar-setup-lab/protocol.json) · [Design shortlist](../radar-setup-lab/design-picks.json) · [Design summary](../radar-setup-lab/design-summary.json) · [Held-back summary and verdicts](../radar-setup-lab/confirm-summary.json) · [Design cards](../radar-setup-lab/design-cards.jsonl.gz) · [Held-back cards](../radar-setup-lab/confirm-cards.jsonl.gz)
