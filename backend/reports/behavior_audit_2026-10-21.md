# Behavior audit (D0) — 1,528 closed option trades, Jul 2025 → Oct 19, 2026

Generated 2026-10-21, read-only, from the production journal (`/health`:
`127.0.0.1:5432/tradejournal`, release `f95559e7aab1`). Follows the D0 brief in
[the product roadmap](../../docs/product-roadmap.md#d0--establish-which-questions-the-data-can-answer)
and checks the July [edge audit](edge_audit_2026-07-07.md) against the trades since.

## Dataset

- **Included:** every closed or expired long option trade (all 1,528 are
  buy-to-open): 1,501 Roth IRA, 27 Individual, 287 trading days,
  2025-07-10 → 2026-10-19. Total realized **+$14,038**, win rate 46.5%,
  mean return on premium +0.3%, median −1.0%.
- **Excluded:** 60 closed stock trades (mostly recurring fractional buys with the
  known pre-Oct-2025 basis gap) and 15 open positions.
- **Coverage:** entry context missing for ≤19 trades on any one field (trend
  flag 13, VWAP 19); option path metrics missing for 104; exit efficiency and
  give-back missing for 280. Missing values are left out of a group, never
  counted as zero.
- **Outcome measured:** return on premium paid (`pnl_pct`), plus dollars and win
  rate. Dollars are dominated by position size, so a group is judged mainly on
  return on premium and its median.

## Method

Each question compares a group with all other trades. The 95% interval on the
difference in mean return comes from 2,000 bootstrap resamples **by trading
day**, because trades on the same day are not independent. About 45 groups were
tested, so 2–3 intervals per pass will exclude zero by chance. A finding is
reported as a pattern only if it points the same way in **both halves**:
exploration (before Apr 1, 2026: 1,178 trades) and check (Apr 1 → Oct 19:
350 trades). These are associations in past trades, not causes or a trading edge.

## What holds up

### 1. The money is lost after the first hour, not at entry

| Hold time | n | Win % | Mean return | Median | Total $ |
|---|---|---|---|---|---|
| < 5 min | 192 | 47 | −2.2% | 0.0% | +4,974 |
| 5–15 min | 350 | 51 | +2.6% | +0.5% | +9,620 |
| **15–60 min** | 403 | 50 | **+9.8%** | +0.2% | **+21,516** |
| **1 h → same-day close** | 240 | 39 | **−9.5%** | −8.1% | **−17,558** |
| Overnight or longer | 343 | 43 | −5.1% | −6.8% | −4,514 |

15–60 minutes is better than the rest in both halves (+13.5 and +11.5 points).
1 hour to the close is worse in both (−11.0 and −13.4; the full-period interval
is −18.9 to −3.8). Hold time is decided after entry, so this measures **exits**:
losers are being held. The median loser costs −13% of premium when closed within
an hour, −24% when held to the close, and −42% when held overnight.

**Of 146 losers held between 1 hour and the close, 53 had been up at least 10%
within their first hour.** Those 53 trades lost **$15,304**. Only 32 of the 146
were never green.

### 2. The July rules didn't change the leak

The July 7 audit named the same leaks: riding green trades back into losses,
letting short-dated options expire, and multi-day holds. Since then:

| | Before Jul 7 | After Jul 7 |
|---|---|---|
| Trades / days | 1,430 / 233 | 98 / 54 |
| Total realized | +$9,307 | +$4,731 |
| Win rate | 46% | **59%** |
| Up ≥ $50, then closed red | 233 (16%), −$44,345 | 15 (15%), **−$10,406** |
| Expired worthless | 32, −$5,972 | **11, −$7,525** |
| Held 1 h → close | −$11,399 | −$6,159 |

You trade much less and win more often, but the same mistakes now cost more per
trade because sizes are larger. The five largest losses since July:
- SNDK Jul 9, −$4,350 (had been up $1,109)
- SNDK Sep 1, −$2,690 (had been up $380)
- TSLA Sep 10, −$2,534
- DRAM Sep 22, −$1,472 (held 17 days)
- META Sep 10, −$1,074

The rules exist in a report, but nothing in the app reminds you of them while a
trade is open.

### 3. Trading on after you're already green on the day

Trades entered while the day was already profitable: 642 trades, mean −3.2%,
**−$8,942** in total. That's 6.0 points worse than the rest (interval −11.5 to
−0.9), and worse in both halves (−3.8, −13.2). The first trade of the day was
the best in both halves (+5.9% mean overall; the interval includes zero).
Trading after a loss was **not** worse: entries while red on the day averaged +1.1%.

### 4. Weaker: the 9:45–10:00 window

Entries from 9:45 to 10:00 did best in both halves: 137 trades, +17.5% mean,
+$9,389. But n is small, the check-half interval is very wide (+6.6 to +91.5),
and 9:30–9:45 showed nothing. Treat this as a question to watch, not a rule.

## What showed nothing reliable

These differences were small, had intervals spanning zero, or flipped sign
between halves:

- **Trend alignment:** the app's daily trend flag and alignment with the day's move.
  - Day-move alignment helped in the first half and hurt in the second.
  - The day-move/trend filter that looked positive in the Jo scanner pilots does
    **not** separate your own discretionary winners from losers.
- **Extension at entry:** chase score, late move, distance past VWAP.
- **Repeat entries:** in the same ticker on the same day.
- **Quick re-entry after a loss:** the July audit's leak 4 didn't replicate here
  (within 5 minutes after a loss: −4.4 points, interval spans zero).
- **Calls vs puts:** calls better in both halves, but not reliably.
- **DTE:** 1–3 DTE was bad in the first half and not in the second.
- **Mid-session entries (10:00–14:00):** slightly worse; the intervals span zero.

The AI reviews coach heavily on the chase and trend flags. On this evidence
those flags don't predict your outcomes.

## Concentration and limits

- Without the top five winners (LLY, MU, AAPL, AMD, SPY), the 1,528 trades total
  +$2,644. The overall result is close to breakeven.
- By ticker, SNDK is the worst (−$5,410 over 48 trades) and MU the best (+$9,562).
- Peak-unrealized and give-back figures come from minute bars and option prices
  where available (`observed_1min` for 1,424 trades). They are not tick-level and
  don't model what a different exit would have filled at.
- No counterfactual exit was simulated. "Would have been green if closed" doesn't
  mean a rule would have captured that money.

## What this suggests

1. **Exits are the lever.** Entries, by every measure here, are not reliably
   good or bad.
2. **The candidate behavior to practice:** once an option is up about 10% or
   more, don't let it go back through entry. Re-decide any position still open
   after an hour.
3. **Something in the app needs to say this while the trade is open.** A rule in
   a report has not changed behavior. A report can't do that job, and neither can
   a weekly review on its own.
4. **Recheck on later trades:** whether the give-back count and the cost of
   expired options fall over the next 30 trades.
