# Radar long-history study

**Neither live setup rule held up.** On 608 sessions that no Radar study had read (January 2, 2024 to June 12, 2026), dip turn (`radar-dip-v0`) was indistinguishable from random entries and is **retired as a trade idea** under the registered rule. Gap reversal (`radar-reversal-v0`) came out **inconclusive**: a small lead whose range runs from below zero to above the bar, and which disappears without the top 1% of cards. The lead the setup lab saw for reversal on 36 held-back sessions (+0.14 points) was +0.05 here.

The numbers that carry this, with the registered one-minute entry delay:

| Rule | Cards | Green | Random green | Mean % | Median % | Edge % (95% range) | Without top 1% | Verdict |
|---|---|---|---|---|---|---|---|---|
| Dip turn | 4,603 | 45% | 39% | −0.01 | −0.21 | −0.02 (−0.08 to +0.04) | −0.10 | retire as a trade idea |
| Gap reversal | 3,882 | 49% | 40% | +0.08 | −0.07 | +0.05 (−0.09 to +0.19) | −0.07 | inconclusive |

Edge is the card's result minus the average of 20 random roster stocks carded at the same minute and direction. All figures are the stock's own move in percent, with no costs. No option was scored.

## What was fixed first

The [protocol](../radar-long-history/protocol.json) was merged (#760) before any number was computed. It fixed:

- **The rules:** `radar_dip.replay` and `radar_reversal.replay`, unchanged, with the setup lab's card and exits.
- **The stock list:** each session's 150 most traded common stocks over the 20 sessions before it, from dated listings that include later-delisted names. The live roster was assembled after this period and was not used.
- **The entry:** the close of the minute after the flag, as a person acting on a ping could get.
- **The verdicts:** "holds up" needs a 95% range above zero, a mean edge of at least 0.10 points, every year positive and a positive mean without the top 1% of cards. "Retire as a trade idea" means the range's upper end is below 0.10.

One code change followed registration and before the run: the listing fetch was paged by cursor with the full page size, because the first attempt stalled. It changed no scoring rule.

## Results by year and direction

| Cell | Cards | Edge % (95% range) | Without top 1% |
|---|---|---|---|
| Dip · 2024 | 1,746 | −0.03 (−0.12 to +0.07) | −0.11 |
| Dip · 2025 | 1,831 | −0.05 (−0.15 to +0.05) | −0.13 |
| Dip · 2026 to June 12 | 1,026 | +0.05 (−0.10 to +0.21) | −0.02 |
| Reversal · 2024 | 1,047 | +0.17 (−0.09 to +0.43) | +0.02 |
| Reversal · 2025 | 1,706 | −0.04 (−0.23 to +0.13) | −0.14 |
| Reversal · 2026 to June 12 | 1,129 | +0.06 (−0.22 to +0.35) | −0.04 |
| Reversal · gap down reversing up | 1,744 | −0.03 (−0.26 to +0.20) | −0.15 |
| Reversal · gap up reversing down | 2,138 | +0.11 (−0.04 to +0.26) | −0.01 |

- **Dip turn** was below random in 2024 and 2025 and above it in the first half of 2026. No year's range clears zero.
- **Gap reversal** was positive in two of three years and negative in 2025, so it fails the every-year condition by itself. Its summed edge was positive in 46% of the sessions that had a card.
- **The long side of reversal**, a gap down reversing up, was at or below random. What lead there is sits on the short side.
- **The typical card lost a little.** The median result was −0.21% for dip and −0.07% for reversal. Both rules are green more often than random entries, yet the average lead is near zero: wins are small and the mean depends on a few large cards.

The lab's own zero-delay entry gave nearly the same picture: dip −0.02 (−0.08 to +0.05), reversal +0.07 (−0.08 to +0.20). The one-minute delay cost reversal about 0.02 points.

## The earnings split

The registered prediction was that reversal does better without an earnings report on the session or the one before. It did not: +0.05 without a report (3,327 cards) against +0.04 with one (542 cards), a difference of +0.01 points (90% range −0.23 to +0.23). On this label, news around a gap made no measurable difference to the rule. Dip was worse with a report (−0.14, range −0.34 to +0.07, 391 cards), which is a description and not a test.

## What to take from this

These items are listed, not built, and this study changes no live rule, switch or alert.

1. **Dip turn should not be presented as a trade idea.** Its best case on 600 sessions is +0.04 points a trade on the stock. It can stay as awareness.
2. **Gap reversal has not earned a phone ping.** It is not retired, because an edge of up to about 0.19 points cannot be ruled out. Nothing here supports it either: the estimate is half the bar, it is negative in 2025 and negative without the top 1% of cards.
3. **Do not rerun reversal on a few dozen new sessions.** This run had about 17 times the lab's held-back sessions and could not settle it. A short rerun cannot.
4. **Stock-level continuation and reversal are now both without support here.** The Factory's breakout families, the Radar v2 movers and the owner's own entries showed no follow-through. The one reversal rule shows no dependable lead.

## Limits

- **Less precise than registered.** The protocol expected a standard error near 0.03 points for reversal. It was 0.07, because reversal cards are few a day and heavy-tailed. That is why the result is inconclusive and not a retirement.
- **The stock, not the option.** No spread, decay or commission is modelled.
- **Minute closes only.** Intrabar stops are missed, equally for the cards and the random baseline.
- **A different stock list from live.** The 150 most traded common stocks each day, not the curated roster of optionable names with its ETFs and groups.
- **Earnings dates without a time of day,** from the vendor's history and not a point-in-time record. Both sessions around a report are marked, which blurs the split.
- **26 of 376 names had no earnings dates** and are left out of the split (57 cards).

## Reproduction

From `backend`, with a data folder outside the repository (about 400 MB):

```sh
ALPACA_DATA_FEED=sip python -m scripts.radar_long_history roster DATA --env-file .env
ALPACA_DATA_FEED=sip python -m scripts.radar_long_history minutes DATA --env-file .env
python -m scripts.radar_long_history earnings DATA --env-file .env
python -m scripts.radar_long_history run DATA --out RESULTS
```

The summary records the input hash. The card file holds every flag with its entry, level, exit, result, baseline and earnings label, one JSON line for each entry delay.

[Protocol](../radar-long-history/protocol.json) · [Summary and verdicts](../radar-long-history/summary.json) · [Cards](../radar-long-history/cards.jsonl.gz)
