# Edge Audit — 1,477 Closed Trades (Feb 2020 → Jul 6, 2026)

Generated 2026-07-07 from the enriched journal: greeks PnL attribution, trader-state
sequence metrics, ATR-normalized path metrics, and behavioral flags. Coverage:
1,477 trades with entry context, 1,406 with path metrics, 1,369 options with full
four-greek attribution.

**Baseline: net +$6,307 over ~6.5 years. Win rate 45.5%, profit factor 1.06.**
Barely above breakeven — but the decomposition shows that is not one mediocre
edge; it is a real edge minus a few large, specific leaks.

---

## The headline: your direction-picking makes money; costs eat it

Greeks attribution across 1,369 option trades:

| Component | Total | Meaning |
|---|---|---|
| Delta | **+$20,594** | direction |
| Gamma | **+$53,124** | direction, convexity |
| Theta | **−$72,444** | time decay paid |
| Vega | +$23,016 | IV changes |
| Residual | −$10,542 | spread/slippage + path effects |
| **Realized** | **+$13,749** | |

Directional edge (delta+gamma) earned **~+$74k**. Theta gave **−$72k** of it back.
You do not have an idea problem — you have a **holding-cost problem**. Every leak
below is a version of "paying too much time or giving back too much move."

---

## Leak 1 — Multi-day option holds (≈ −$10k direct, −$35k theta drag)

| Hold bucket | n | Total | Win% | PF |
|---|---|---|---|---|
| Scalp (<15m) | 495 | +$7,295 | 47.3 | 1.39 |
| Intraday | 604 | +$5,104 | 45.5 | 1.11 |
| Swing (6–24h) | 134 | **+$7,109** | 51.5 | **1.86** |
| **Multi-day** | 226 | **−$9,867** | 38.5 | **0.66** |

Holds >1 day paid **−$35,345 in theta** against −$5,239 realized. The 39
expired-worthless positions alone are **−$9,476** (avg −$243). Your overnight-to-
one-day swing is your *best* trade; the same trade held for days is your worst.
DTE tells the same story: 0dte PF 1.17 and 4–7dte PF 1.34, but 1–3dte PF 0.86 and
22+dte PF 0.86 — the toxic pattern is short-dated contracts held across days.

**Rule:** any option still open after the next session's close needs an explicit
re-decision (add thesis or exit). Never let short-dated longs ride to expiry —
"expired worthless" should be a rare event, not 39 of them.

## Leak 2 — Giving winners back (−$60k realized on once-green trades)

**308 trades were up at least +$50 unrealized and closed red.** Their combined
peak unrealized was **+$74,956**; they realized **−$60,256** — a $135k swing.
Option exit efficiency: median 0%, mean −42% (you often exit below entry on
trades that traded above it). Post-exit continuation is modest (+0.55% in 30m vs
1.20% in-trade MFE), so you are **not** selling winners too early — the leak is
specifically riding green trades back through breakeven into red.

**Rule:** once a trade shows meaningful gain (≈ +$50–100 or ~25% of premium),
ratchet the stop to breakeven. This one rule attacks the single largest dollar
leak in the journal.

## Leak 3 — Mid-session entries (−$5.7k in your biggest bucket)

| Entry window | n | Total | Win% | PF |
|---|---|---|---|---|
| Open (9:30–10) | 276 | +$4,982 | 51.8 | 1.25 |
| **Mid (10–14)** | **938** | **−$5,747** | 43.4 | **0.92** |
| Close (14–16) | 250 | +$8,212 | 47.6 | 1.63 |

**63% of your volume trades in the only window where you lose.** Open and close
entries earned +$13.2k combined; mid-day gave −$5.7k of it back.

**Rule:** half size (or paper-only) between 10:00 and 14:00. Full size at the
open drive and the closing move, where your edge actually lives.

## Leak 4 — Instant re-entry after an exit (−$4.1k, PF 0.73)

| Time since last exit | n | Total | PF |
|---|---|---|---|
| **< 5 min** | 161 | **−$4,132** | **0.73** |
| 5–30 min | 478 | +$270 | 1.01 |
| > 30 min | 511 | +$4,713 | 1.15 |

The classic "revenge trade" (same ticker after a loss) turned out roughly flat
(n=78, PF 0.98) — but **jumping into anything within 5 minutes of closing the
last trade** is reliably toxic. And the tilt direction is inverted from the
cliché: entries taken while **down >$200 on the day are your best cohort**
(PF 1.31, n=245) while entries taken while **up >$200 are breakeven with a 39%
win rate** (PF 1.00, n=358). You trade carefully when hurt and sloppily when
ahead.

**Rule:** 15-minute cooldown after every exit. Extra caution when the day's PnL
is green, not red.

## Leak 5 — No stop line (losers' tails are −$25k to −$40k)

ATR-normalized heat (MAE ÷ entry-day ATR) separates winners from losers cleanly:

- Winners: median heat **0.06 ATR**, p90 0.38
- Losers: median 0.17, p90 **1.06 ATR**

A hard "underlying moved 0.75 ATR against me → out" line would have left **96%
of winners untouched** while capping 123 losers that ultimately lost **−$32,068**
(a 1.0 ATR line: 98% of winners kept, 84 losers capped, −$25,196). A stop can't
recover all of that (it caps, not erases), but winners almost never take that
much heat — beyond ~0.5 ATR against you, history says the trade is dead.

---

## Secondary observations

- **"Right direction, lost anyway":** 135 trades, −$8,137 — killed by IV crush
  (−$12.3k vega) plus theta. Check IV/earnings proximity before buying premium;
  this is the cohort a spread (instead of a long option) would have saved.
- **Residual −$10.5k ≈ spread/slippage proxy** — 1.7× your total net PnL went to
  transaction friction. Supports adding bid/ask capture at fill (future work).
- **Setup quality score validates mildly:** score <50 → PF 0.96; score ≥50 →
  PF 1.12. Trend-aligned (PF 1.13) beats counter-trend (1.02). Chase flag is
  noise (1.07 vs 1.05).
- **Tickers:** LLY +$5,150, MU +$4,441, AMD +$2,132 are your franchises; SLV
  (−$1,972 in 16 trades) and CVNA (−$1,657 in 68) deserve a personal ban list.
  (COST −$1,194 is only 4 trades — variance, not signal.)
- Small-n cohorts (premarket n=3, afterhours n=10) excluded from conclusions.

## The five rules, one line each

1. Options don't sleep over twice: re-decide or exit after the next session.
2. Green trade +$50 → stop moves to breakeven, no exceptions.
3. Half size between 10:00 and 14:00.
4. 15-minute cooldown after every exit; extra care when up on the day.
5. Underlying 0.75 ATR against you = the trade is over.

*Method note: cohorts are historical associations, not guarantees; all five rules
rest on n ≥ 120 cohorts with consistent direction across PF, win rate, and total
dollars. MAE stop savings are caps-at-stop-line, not full loss recovery.*
