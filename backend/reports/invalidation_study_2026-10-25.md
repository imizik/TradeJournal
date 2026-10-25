# Where should my invalidation be? — historical study, October 25, 2026

**No universal invalidation level or mechanical time stop earns a default from this sample.** Every overall primary-sample 95% interval for mean return improvement includes zero. Session extremes, entry VWAP, a 2% adverse underlying move and the 120-minute mark have positive mean counterfactual differences in both halves, but the first three are sensitive to coverage and the last would have reduced total dollars. These are minute-bar counterfactuals, not executable strategies.

Read-only research on the same **1,528 closed/expired long option trades**, July 10, 2025–October 19, 2026, as the [October 21 behavior audit](behavior_audit_2026-10-21.md). One report only; no production database writes, market/provider fetches, model calls, alerts, copilot changes or policy activation.

## Cohort and method

- Read the production PostgreSQL journal with the existing [`exit_counterfactual_study.py`](../scripts/exit_counterfactual_study.py) extraction SQL: one `BEGIN READ ONLY` transaction, `trade`, `account`, `tradefill` and `fill`; entry date through October 19 and closed/expired options. Unlike that script's separate exit study, **do not apply its 10-day holding-window exclusion**. All extracted fills are buy-to-open/sell-to-close.
- Reconciled exactly: **1,528 trades, 287 New York entry days, 1,501 Roth IRA / 27 Individual, +$14,037.98 actual realized P&L**. FIFO reconstruction of all 1,528 trades agrees with recorded realized P&L and premium to within $0.51 per trade. No replacement or recalculation was written to the journal.
- Fixed split: **1,178 before April 1, 2026; 350 on/after April 1**. No later trades enter this study. Each measurable crossing/time mark is paired with that same trade's actual exit. The target is mean **percentage-point change in return on total premium paid**, not a comparison of unrelated trade groups. Dollar changes and medians are shown separately.
- **2,000 bootstrap resamples of New York entry days**, retaining all measured trades on a selected day together, seed `20261025`; percentile 95% intervals. Recompute separately within each displayed subgroup and half. A positive/negative pattern counts only if its mean points the same way in both halves. This is a necessary screen, not proof: many overlapping comparisons, no multiplicity adjustment, and no genuinely untouched prospective holdout. Full-period intervals are printed; half sample sizes/means are printed alongside them.
- Primary stock source: cached **Alpaca IEX raw minute bars**, matching the production journal cache feed. Merge existing local and server files, server precedence for duplicate timestamps; no conflicting duplicate values were found. Option source: existing Alpaca option **trade** minute bars, not bid/ask quotations. A separate SIP-stock replay is a sensitivity check, not a replacement or a merged feed. Time marks use the same option observations in both runs.

### Levels frozen at entry

Reference underlying price is the last completed minute close available at entry, at most five minutes old; it is a proxy for the underlying price at the option fill. No entry-minute high, low or close is used to set a level. All entries in this cohort were within regular clock hours.

| Candidate | Exact definition |
|---|---|
| Session extreme | Regular-session low so far for a call; high so far for a put, from completed bars. Freeze it; never use the eventual full-session extreme. |
| OR5 / OR15 | Low for calls / high for puts of 09:30–09:34 / 09:30–09:44 New York. Available only after 09:35 / 09:45 respectively. Missing prints are not synthesized. |
| Entry VWAP | Freeze regular-session cumulative volume-weighted typical price `(high + low + close) / 3`, using completed bars, matching the journal's formula rather than a streaming/recomputed VWAP. |
| Prior-session extreme | Immediately preceding exchange session's regular-hours low for calls / high for puts, aggregated from cached raw minute bars. Never skip a missing prior session and substitute an older one. |
| Nearest available automatic | Call [`chart_levels.compute_levels`](../app/engine/chart_levels.py) at entry, then choose the nearest returned price strictly below the reference for calls / above it for puts. Includes round numbers and prior closes; this is **not** restricted to swing support/resistance or confluence zones. |
| Adverse 1%, 2%, 3% | Reference × `(1 − p)` for calls and × `(1 + p)` for puts. For puts an adverse underlying move is **up**, not down. |

Only levels strictly on the adverse side qualify. Levels already beyond entry, missing levels and paths with no observed in-trade underlying bars are excluded from the crossing denominator, not counted as non-crosses. Raw minute aggregates supply daily inputs to automatic levels; the adjusted daily cache is deliberately unused because its price basis differs. Exchange holidays and early closes are explicit in the replay. An automatic level is the nearest **available** level; missing history can change which level is selected.

### Crossing, recovery and valuation

1. Monitor regular-session bars starting at/after entry and **ending strictly before actual exit**. The entry's partial minute and exit's partial/final minute are excluded. A cross is the first observed bar with low **strictly below** the frozen level for a call, or high **strictly above** it for a put. Touches alone do not count. Gap-through bars count. No claim is made about the precise intra-minute crossing time, overnight crossings or crossings missed by the feed.
2. Recovery is a later completed option minute close with whole-trade marked P&L **≥ $0**, strictly after the crossing minute and before exit. Include realized partial-sale P&L plus mark-to-market P&L on remaining FIFO lots. Also tabulate the more permissive later option-bar-high observation. Excluding the crossing bar avoids inventing intra-bar event order. “Later BE” includes trades already green at the crossing; a separate red-at-cross recovery table prevents mistaking continued profitability for a recovery.
3. Recovery does **not** require a cross-minute option print. Its denominator is all crossed trades with at least one usable later mark and no subsequent add. No later print means unknown, not no recovery. An observed failure to recover is not proof it never recovered between prints. Trades with later adds are omitted from recovery and exit valuation to avoid attributing added capital to the stop.
4. Exit counterfactual: mark the remaining contracts at the option **close in the same underlying-cross minute**, retain actual earlier partial sales, and compare with actual final P&L. Require that exact option minute, an open lot, no actual fill anywhere in that minute or at its close, and no later buy-to-open. Do not carry forward quotes or borrow a later print. No simultaneous fill, slippage, spread, fee or liquidity model is asserted.
5. `stop Δ$ = marked total P&L − actual total P&L`; `stop Δpp = 100 × stop Δ$ / actual total premium paid`. Positive means the minute counterfactual improved the outcome. `hold-after = actual − marked`: its medians measure what happened by continuing to the actual exit. Total dollars are sums over **valued trades only**, not estimates for missing marks or all 1,528 trades. The same trade can appear in several candidate rows; never sum rows together.
6. Time stops use trades **still open strictly after N elapsed wall-clock minutes** (15/30/60/120). Use the option bar starting at the first whole minute at/after that threshold, ending strictly before exit; its close is up to just under two minutes after an exact-second threshold. Never roll an overnight threshold to next open. The later-BE recovery window and fill/add exclusions are the same. These are survivor risk sets, not all entries.
7. Hold groups are actual elapsed hold `<15`, `15–60` inclusive, and `>60` minutes (including overnight holds). They are **post-entry outcomes**, not setup labels available when entering. Calls/puts are known at entry. No breakout/reversal/retest setup label was inferred from these bars.

## Primary results: levels and time marks

“Cross/eligible” is the observed crossing frequency; time rows show the still-open risk-set count instead. “Valued n” requires the exact-minute option mark. “Later BE” has its own denominator, often larger. “Median hold-after” is dollars and percentage points earned/lost **after** the mark; negative means continuing lost money. Half columns are **valued n; mean stop Δpp**.

| Candidate | Cross/eligible (%) or still open | Valued n | Later BE / observed n (%) | Median hold-after $; pp | Stop Δ$ | Mean stop Δpp | Day-bootstrap 95% CI, pp | Before n; Δpp | After n; Δpp |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| Session extreme | 263/1462 (18.0%) | 115 | 81/192 (42.2%) | -23; -6.01 | -1,114 | +1.74 | [-6.10, +8.88] | 88; +1.55 | 27; +2.34 |
| OR5 | 193/1059 (18.2%) | 70 | 64/145 (44.1%) | -19; -5.21 | -1,400 | +0.04 | [-9.47, +8.79] | 55; +1.13 | 15; -3.95 |
| OR15 | 179/1026 (17.4%) | 64 | 54/132 (40.9%) | -18; -6.21 | -2,086 | +1.86 | [-8.28, +11.07] | 47; +3.58 | 17; -2.89 |
| Entry VWAP | 321/1049 (30.6%) | 144 | 128/256 (50.0%) | -22; -6.53 | +1,436 | +1.51 | [-7.48, +9.48] | 111; +1.32 | 33; +2.14 |
| Prior-session extreme | 95/1030 (9.2%) | 45 | 20/68 (29.4%) | -14; -4.29 | -2,786 | +1.07 | [-6.81, +9.00] | 32; +4.31 | 13; -6.88 |
| Nearest available automatic | 759/1470 (51.6%) | 285 | 398/611 (65.1%) | -18; -6.35 | -2,296 | +1.90 | [-3.64, +7.24] | 220; +3.74 | 65; -4.31 |
| Adverse 1% | 362/1470 (24.6%) | 155 | 127/283 (44.9%) | -19; -4.59 | -2,973 | +0.29 | [-6.07, +6.06] | 117; -1.54 | 38; +5.93 |
| Adverse 2% | 210/1470 (14.3%) | 85 | 50/152 (32.9%) | -16; -4.12 | -3,301 | +4.88 | [-0.76, +10.71] | 56; +3.75 | 29; +7.07 |
| Adverse 3% | 130/1470 (8.8%) | 41 | 24/88 (27.3%) | -24; -3.71 | -2,477 | +1.19 | [-6.47, +10.24] | 25; -0.89 | 16; +4.43 |
| 15 minutes | 962 | 448 | 606/789 (76.8%) | -16; -4.26 | -14,500 | -4.99 | [-12.21, +1.83] | 354; -4.09 | 94; -8.37 |
| 30 minutes | 750 | 285 | 461/613 (75.2%) | -14; -4.18 | -10,611 | -2.89 | [-12.14, +5.27] | 212; -0.43 | 73; -10.03 |
| 60 minutes | 581 | 179 | 343/490 (70.0%) | -12; -4.40 | -3,793 | -2.71 | [-15.86, +8.00] | 130; +1.53 | 49; -13.98 |
| 120 minutes | 465 | 120 | 262/391 (67.0%) | -16; -6.25 | -2,048 | +9.68 | [-8.30, +31.74] | 89; +8.97 | 31; +11.70 |

### Actual versus counterfactual on the same valued trades

Returns are unweighted means of per-trade return on premium; dollar totals are size-weighted. A positive mean return improvement can coexist with a negative dollar result. Dollar intervals also resample entry days.

| Candidate | Actual total $ | Counterfactual total $ | Actual mean return % | Counterfactual mean return % | Stop Δ$ 95% day-bootstrap interval |
|---|---:|---:|---:|---:|---|
| Session extreme | -19,854 | -20,968 | -31.22 | -29.48 | [-6,860, +5,279] |
| OR5 | -9,039 | -10,439 | -31.91 | -31.87 | [-4,776, +1,848] |
| OR15 | -10,306 | -12,392 | -32.47 | -30.60 | [-5,923, +1,741] |
| Entry VWAP | -18,498 | -17,062 | -24.11 | -22.60 | [-2,922, +6,069] |
| Prior-session extreme | -10,390 | -13,176 | -40.27 | -39.20 | [-8,428, +1,671] |
| Nearest available automatic | -20,400 | -22,696 | -18.38 | -16.48 | [-10,437, +6,028] |
| Adverse 1% | -20,265 | -23,238 | -25.11 | -24.82 | [-9,824, +3,704] |
| Adverse 2% | -15,974 | -19,275 | -40.27 | -35.38 | [-10,276, +2,344] |
| Adverse 3% | -9,112 | -11,589 | -42.49 | -41.30 | [-7,073, +635] |
| 15 minutes | +11,605 | -2,895 | +5.09 | +0.10 | [-28,022, -1,084] |
| 30 minutes | +4,044 | -6,567 | +1.23 | -1.66 | [-21,999, -559] |
| 60 minutes | -6,041 | -9,834 | -4.40 | -7.11 | [-13,419, +5,936] |
| 120 minutes | -8,289 | -10,337 | -13.35 | -3.67 | [-10,701, +5,655] |

### Recovery detail

The unknown column counts crossed/still-open trades lacking a usable later path or having a later add. A same-minute mark is unnecessary for the first two recovery columns. “Red at cross” is the narrower set with a valid negative crossing mark and a usable later path. High-based recovery is an observed traded high, still not an executable option sale.

| Candidate | Later close ≥ BE / observed | Later high ≥ BE / observed | Later path unknown | Red-at-cross → later close ≥ BE |
|---|---:|---:|---:|---:|
| Session extreme | 81/192 | 82/192 | 71 | 44/107 |
| OR5 | 64/145 | 66/145 | 48 | 29/68 |
| OR15 | 54/132 | 57/132 | 47 | 25/60 |
| Entry VWAP | 128/256 | 130/256 | 65 | 49/123 |
| Prior-session extreme | 20/68 | 21/68 | 27 | 11/40 |
| Nearest available automatic | 398/611 | 413/611 | 148 | 140/251 |
| Adverse 1% | 127/283 | 128/283 | 79 | 55/145 |
| Adverse 2% | 50/152 | 50/152 | 58 | 21/77 |
| Adverse 3% | 24/88 | 24/88 | 42 | 9/37 |
| 15 minutes | 606/789 | 615/789 | 173 | 131/231 |
| 30 minutes | 461/613 | 467/613 | 137 | 88/158 |
| 60 minutes | 343/490 | 346/490 | 91 | 45/101 |
| 120 minutes | 262/391 | 266/391 | 74 | 31/72 |

## What holds up, and what does not

- **Only weak overall directional replication:** session extreme +1.55/+2.34 pp, VWAP +1.32/+2.14 pp, adverse 2% +3.75/+7.07 pp, and 120 minutes +8.97/+11.70 pp (before/after). Every full-period mean-return interval includes zero. Session, adverse 2%, and 120-minute stops **lose total dollars** on their valued samples. None supports “this would have saved money” across the cohort.
- **OR5, OR15, prior-session extreme, nearest automatic, 1%, 3% and 60 minutes fail the two-half sign screen.** Do not promote their pooled positive values, where present. The automatic-level mean moves from +3.74 to −4.31 pp; its high crossing frequency is not evidence of usefulness.
- **15- and 30-minute automatic exits are directionally harmful in both halves:** −4.09/−8.37 pp and −0.43/−10.03 pp. Their intervals still include zero. This argues against inventing an early universal time stop from the old hold-time association.
- **The 60-minute audit association is not a 60-minute exit result.** In this survivor sample, the 60-minute mean changes from +1.53 pp (130 valued trades) to −13.98 pp (49). For calls alone it is negative in both halves, −4.65/−4.03 pp (54/30). The median continuation is a loss, but larger recoveries can make stopping worse in the mean or total dollars.
- **Rebounds are material:** after a VWAP cross, 128/256 trades with later observations show a later breakeven close; among those known red at the cross, 49/123 do. For the nearest automatic level, those counts are 398/611 and 140/251. Neither a cross nor a later recovery establishes a tradable fill or the best exit.
- **A small, retrospective VWAP pocket survives both halves and feeds:** for trades actually held under 15 minutes, IEX has 21 valued crosses (16/5), +7.61 pp mean, interval [+2.40, +12.06], +$1,550; SIP has 13 (10/3), +9.75 pp and +$1,326. The actual hold category is unknowable at entry; five/three later-half observations and multiple comparisons are too little to call it a scalp setup rule.
- **The strongest-looking fixed-stop subgroup does not travel:** IEX puts at an adverse 2% rise have 51 valued crosses (37/14), +8.04 pp, interval [+0.68, +16.09], +$980. SIP puts have 24 (17/7), −0.80 pp and −$431. On the **same 23 trades valued in both feeds**, IEX/SIP means are −2.07/−1.96 pp; both halves are negative. This mainly reveals sample/coverage selection, not proof that one feed caused a reversal.

## Defaults the copilot could suggest — approval only

**No measured setup-specific invalidation or automatic time-exit default is established.** This study has direction and actual hold length, not a trustworthy entry-time setup taxonomy. In particular, do not treat an eventual short hold as an intended scalp.

| Possible copilot wording for approval | Evidence and appropriate status |
|---|---|
| “For a trade you explicitly intend as a short scalp, do you want to use the entry VWAP as a level to reassess?” | Research candidate only: the retrospective `<15` group has 21 IEX marks (16 before / 5 after), favorable means in both halves; SIP has 13 (10/3), also favorable. This does **not** validate the prospective intended-scalp setup or a mechanical sell. Needs your chosen setup and approval. |
| “You are still in this option after two hours; do you want to reassess the original thesis?” | Review prompt only: 465 survivors, 120 usable threshold marks (89/31); mean mark-versus-actual return +9.68 pp, but interval [−8.30, +31.74] and dollar change **−$2,048**, negative in both halves. No evidence that such a prompt improves behavior; no default exit time justified. |
| “Should I propose a fixed 1%/2%/3%, OR5/OR15, prior-day or nearest-automatic stop?” | No evidence-backed default from this run. Several flip between halves; the nominal 2%-put subgroup fails the SIP-covered sensitivity. Choosing one would be a new user-approved hypothesis, not a learned rule. |

These are wording candidates for your decision, not changes to copilot instructions, position alerts or trading rules. No setting was saved and no suggestion was activated.

## Coverage and limits

- **43 trades have no observed in-trade IEX underlying bar; 20 have no entry reference within five minutes.** The nine level rows retain all 1,528 trades for eligibility accounting, but their statistical samples differ. Among the 1,470 eligible fixed/automatic paths, median expected regular-minute coverage is 100%; the 10th percentile is 71.4%, and only 1,048/1,470 reach 95%. A full minute count still does not make IEX consolidated market coverage.
- IEX automatic-level history is incomplete: among 1,508 computable entry references, the chart function flags missing swings/ATR on **1,032**, prior day on **222**, prior week on **395**, overnight on **769**, and premarket on **724**. It selects round numbers for **888** entries. This is the code's nearest available output, not proof of the level a fully populated historical chart would have shown. No complete daily or overnight history was manufactured.
- The raw prior-session aggregate is the extreme observed in that feed's cached regular minutes, not an official daily high/low. Adjusted daily bars are excluded. Raw data avoids adjustment mismatch but does not remove real corporate-action discontinuities across multi-session holds; no complete corporate-action screen was available, so those paths are not evidence for a fixed cross-event stop.
- Option prints are sparse. Example: **321 VWAP crossings, 144 exact-minute valuations, 256 later paths**. Do not turn 144 valued marks into an estimate for all 321 crossings or all 1,528 trades. Missingness is not random and its composition differs between halves. Breakeven observations are lower-bound evidence of recovery; no-print periods, gaps, outside-regular-hours moves and the excluded entry/exit minutes can hide additional crossings or recoveries.
- A threshold bar's option close may be after the underlying hit and can already include a rebound. Underlying and option OHLC timestamps do not establish synchronized executable quotes. No spread, slippage, fees, latency, market impact, fill guarantees or stop-order behavior are modeled. Partial exits are retained; future adds are excluded from valuation. Results are counterfactual **at a minute bar**, not a strategy backtest.
- The reference can be up to five minutes stale, VWAP is frozen rather than dynamic, and opening ranges can have missing minutes. Longer holds include overnight/corporate-action exposure; the clock stops are elapsed wall time, not accumulated trading minutes. These choices are explicit limitations, not interchangeable stop definitions.
- Small half/subgroup samples, overlapping tests, exposure to this period in previous research, and winner/position-size concentration prevent a causal or prospective claim. Do not optimize the threshold against these results and call the same half a fresh test.

### Eligibility exclusions (primary stock replay)

Counts are mutually exclusive within a row; “no path” is applied after level availability/adverse-side checks.

| Candidate | Missing reference/level | Not strictly adverse | No observed path | Eligible |
|---|---:|---:|---:|---:|
| Session extreme | 22 | 6 | 38 | 1462 |
| OR5 | 75 | 366 | 28 | 1059 |
| OR15 | 185 | 288 | 29 | 1026 |
| Entry VWAP | 22 | 431 | 26 | 1049 |
| Prior-session extreme | 242 | 227 | 29 | 1030 |
| Nearest available automatic | 20 | 0 | 38 | 1470 |
| Adverse 1% | 20 | 0 | 38 | 1470 |
| Adverse 2% | 20 | 0 | 38 | 1470 |
| Adverse 3% | 20 | 0 | 38 | 1470 |

## SIP-stock sensitivity

Same frozen journal and option cache, separate stock feed. This is a different coverage subset: 691 trades have no observed SIP path and 672 lack a fresh SIP entry reference. It cannot serve as an independent replication sample. These overall rows show how the answer changes with available consolidated stock history. Time rows are omitted because their point estimates are identical.

| Candidate | Cross/eligible (%) or still open | Valued n | Later BE / observed n (%) | Median hold-after $; pp | Stop Δ$ | Mean stop Δpp | Day-bootstrap 95% CI, pp | Before n; Δpp | After n; Δpp |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| Session extreme | 147/827 (17.8%) | 79 | 54/110 (49.1%) | -12; -3.85 | -3,375 | -3.01 | [-13.89, +5.78] | 60; -2.92 | 19; -3.30 |
| OR5 | 101/574 (17.6%) | 50 | 39/78 (50.0%) | -12; -3.15 | -2,638 | -6.72 | [-18.66, +4.71] | 38; -5.13 | 12; -11.73 |
| OR15 | 94/553 (17.0%) | 43 | 33/73 (45.2%) | -16; -3.71 | -2,281 | -3.78 | [-17.56, +8.29] | 33; -1.42 | 10; -11.56 |
| Entry VWAP | 162/544 (29.8%) | 81 | 66/132 (50.0%) | -18; -6.80 | -799 | +2.09 | [-7.56, +10.89] | 62; +3.92 | 19; -3.92 |
| Prior-session extreme | 62/654 (9.5%) | 37 | 20/47 (42.6%) | -3; -0.43 | -4,362 | -22.96 | [-73.06, +5.41] | 27; +2.51 | 10; -91.74 |
| Nearest available automatic | 451/835 (54.0%) | 183 | 246/368 (66.8%) | -18; -6.92 | -2,506 | -0.11 | [-7.01, +6.36] | 135; +2.27 | 48; -6.79 |
| Adverse 1% | 152/835 (18.2%) | 77 | 48/116 (41.4%) | -11; -3.27 | -2,540 | -0.78 | [-8.17, +6.28] | 55; -3.01 | 22; +4.80 |
| Adverse 2% | 74/835 (8.9%) | 36 | 12/46 (26.1%) | -8; -3.68 | -3,727 | -1.31 | [-9.13, +6.70] | 22; +1.58 | 14; -5.85 |
| Adverse 3% | 48/835 (5.7%) | 17 | 8/28 (28.6%) | +30; +6.57 | -2,807 | -19.23 | [-44.35, -2.75] | 9; -9.35 | 8; -30.35 |

Matched-valued comparisons separate coverage selection from differences in the observed bar. Each row below uses only identical trade IDs with both marks available; means remain conditional on this overlap.

| Candidate | Matched n (before/after) | IEX / SIP mean Δpp | Before IEX / SIP | After IEX / SIP |
|---|---:|---:|---:|---:|
| Session extreme | 74 (57/17) | −2.20 / −2.29 | −2.20 / −2.46 | −2.21 / −1.71 |
| Entry VWAP | 74 (57/17) | +1.94 / +2.98 | +4.70 / +6.04 | −7.29 / −7.29 |
| Adverse 2%, all | 33 (20/13) | −2.17 / −2.10 | +0.13 / +0.25 | −5.71 / −5.71 |
| Adverse 2%, puts | 23 (16/7) | −2.07 / −1.96 | −1.88 / −1.72 | −2.51 / −2.51 |
| Nearest automatic | 139 (100/39) | +2.36 / +3.08 | +5.84 / +6.90 | −6.57 / −6.70 |

## Requested splits

Same definitions and columns as the primary table. Empty time-stop risk sets are omitted: a trade closed within 15 minutes cannot still be open after 15 minutes. The 15–60-minute group includes exactly 60 minutes, whereas the 60-minute risk set requires **strictly more** than 60. Both margins and joint hold-by-direction groups are provided. All hold-based groups are retrospective, not suggested setups.

### Under 15 minutes

| Candidate | Cross/eligible (%) or still open | Valued n | Later BE / observed n (%) | Median hold-after $; pp | Stop Δ$ | Mean stop Δpp | Day-bootstrap 95% CI, pp | Before n; Δpp | After n; Δpp |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| Session extreme | 11/493 (2.2%) | 6 | 3/8 (37.5%) | -30; -6.09 | +418 | +14.60 | [+3.15, +26.96] | 5; +17.52 | 1; +0.00 |
| OR5 | 8/337 (2.4%) | 3 | 2/6 (33.3%) | -12; -4.48 | +12 | +3.20 | [-1.68, +6.80] | 2; +5.64 | 1; -1.68 |
| OR15 | 11/320 (3.4%) | 3 | 4/6 (66.7%) | +30; +1.68 | -233 | -3.14 | [-14.44, +6.72] | 1; +6.72 | 2; -8.06 |
| Entry VWAP | 25/342 (7.3%) | 21 | 5/15 (33.3%) | -30; -7.24 | +1,550 | +7.61 | [+2.40, +12.06] | 16; +6.92 | 5; +9.83 |
| Prior-session extreme | 1/349 (0.3%) | 0 | 0/1 (0.0%) | — | — | — | — | 0; — | 0; — |
| Nearest available automatic | 115/494 (23.3%) | 44 | 46/90 (51.1%) | -24; -7.07 | +1,197 | +4.89 | [-0.55, +9.63] | 32; +4.62 | 12; +5.61 |
| Adverse 1% | 13/494 (2.6%) | 10 | 3/10 (30.0%) | -22; -7.13 | -321 | +2.74 | [-6.44, +11.46] | 7; +1.29 | 3; +6.12 |
| Adverse 2% | 2/494 (0.4%) | 2 | 0/1 (0.0%) | +4; -1.00 | -7 | +1.00 | [-2.00, +4.00] | 0; — | 2; +1.00 |
| Adverse 3% | 0/494 (0.0%) | 0 | 0/0 (—) | — | — | — | — | 0; — | 0; — |

### 15–60 minutes

| Candidate | Cross/eligible (%) or still open | Valued n | Later BE / observed n (%) | Median hold-after $; pp | Stop Δ$ | Mean stop Δpp | Day-bootstrap 95% CI, pp | Before n; Δpp | After n; Δpp |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| Session extreme | 39/401 (9.7%) | 25 | 20/36 (55.6%) | +0; +0.00 | -1,964 | -8.68 | [-24.08, +3.80] | 19; -8.44 | 6; -9.43 |
| OR5 | 26/291 (8.9%) | 16 | 12/24 (50.0%) | -21; -7.12 | -494 | -0.25 | [-15.53, +14.65] | 11; +7.73 | 5; -17.80 |
| OR15 | 27/290 (9.3%) | 16 | 11/26 (42.3%) | -18; -6.38 | -1,238 | +0.60 | [-16.47, +14.47] | 11; +11.09 | 5; -22.49 |
| Entry VWAP | 58/294 (19.7%) | 36 | 27/53 (50.9%) | -10; -2.91 | -315 | -6.39 | [-20.95, +4.69] | 28; -9.09 | 8; +3.03 |
| Prior-session extreme | 12/273 (4.4%) | 9 | 4/10 (40.0%) | -30; -4.29 | -165 | +6.64 | [-7.27, +21.53] | 7; +13.13 | 2; -16.07 |
| Nearest available automatic | 192/403 (47.6%) | 94 | 108/168 (64.3%) | -10; -2.95 | -4,517 | -4.71 | [-12.91, +2.45] | 77; -0.55 | 17; -23.57 |
| Adverse 1% | 42/403 (10.4%) | 29 | 10/39 (25.6%) | -21; -4.09 | -1,422 | -3.10 | [-20.40, +8.62] | 23; -0.10 | 6; -14.63 |
| Adverse 2% | 11/403 (2.7%) | 10 | 3/10 (30.0%) | -6; -2.09 | -1,760 | -2.41 | [-12.57, +5.76] | 6; +5.92 | 4; -14.91 |
| Adverse 3% | 3/403 (0.7%) | 3 | 1/3 (33.3%) | +12; +3.66 | -1,467 | -11.57 | [-37.31, +6.25] | 1; +6.25 | 2; -20.49 |
| 15 minutes | 381 | 237 | 222/307 (72.3%) | -12; -3.14 | -10,420 | -8.13 | [-15.68, -1.79] | 193; -6.25 | 44; -16.35 |
| 30 minutes | 169 | 92 | 89/125 (71.2%) | -8; -2.12 | -6,470 | -10.41 | [-21.22, -1.06] | 75; -6.94 | 17; -25.75 |

### Over 60 minutes

| Candidate | Cross/eligible (%) or still open | Valued n | Later BE / observed n (%) | Median hold-after $; pp | Stop Δ$ | Mean stop Δpp | Day-bootstrap 95% CI, pp | Before n; Δpp | After n; Δpp |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| Session extreme | 213/568 (37.5%) | 84 | 58/148 (39.2%) | -28; -8.09 | +432 | +3.92 | [-4.84, +11.79] | 64; +3.27 | 20; +5.99 |
| OR5 | 159/431 (36.9%) | 51 | 50/115 (43.5%) | -18; -4.67 | -918 | -0.05 | [-11.76, +10.68] | 42; -0.81 | 9; +3.48 |
| OR15 | 141/416 (33.9%) | 45 | 39/100 (39.0%) | -22; -6.67 | -615 | +2.65 | [-10.87, +13.82] | 35; +1.13 | 10; +7.95 |
| Entry VWAP | 238/413 (57.6%) | 87 | 96/188 (51.1%) | -28; -7.06 | +201 | +3.31 | [-9.62, +15.12] | 67; +4.34 | 20; -0.14 |
| Prior-session extreme | 82/408 (20.1%) | 36 | 16/57 (28.1%) | -12; -4.37 | -2,621 | -0.32 | [-9.82, +8.16] | 25; +1.83 | 11; -5.21 |
| Nearest available automatic | 452/573 (78.9%) | 147 | 244/353 (69.1%) | -20; -7.55 | +1,024 | +5.24 | [-4.33, +13.40] | 111; +6.46 | 36; +1.48 |
| Adverse 1% | 307/573 (53.6%) | 116 | 114/234 (48.7%) | -18; -4.66 | -1,230 | +0.93 | [-6.83, +7.61] | 87; -2.15 | 29; +10.16 |
| Adverse 2% | 197/573 (34.4%) | 73 | 47/141 (33.3%) | -21; -5.30 | -1,534 | +5.99 | [-0.40, +12.89] | 50; +3.49 | 23; +11.42 |
| Adverse 3% | 127/573 (22.2%) | 38 | 23/85 (27.1%) | -27; -4.29 | -1,010 | +2.20 | [-5.72, +10.91] | 24; -1.18 | 14; +7.99 |
| 15 minutes | 581 | 211 | 384/482 (79.7%) | -20; -5.52 | -4,080 | -1.47 | [-13.90, +9.29] | 161; -1.50 | 50; -1.35 |
| 30 minutes | 581 | 193 | 372/488 (76.2%) | -15; -6.29 | -4,141 | +0.70 | [-11.94, +11.64] | 137; +3.13 | 56; -5.26 |
| 60 minutes | 581 | 179 | 343/490 (70.0%) | -12; -4.40 | -3,793 | -2.71 | [-15.72, +7.64] | 130; +1.53 | 49; -13.98 |
| 120 minutes | 465 | 120 | 262/391 (67.0%) | -16; -6.25 | -2,048 | +9.68 | [-9.37, +31.75] | 89; +8.97 | 31; +11.70 |

### call

| Candidate | Cross/eligible (%) or still open | Valued n | Later BE / observed n (%) | Median hold-after $; pp | Stop Δ$ | Mean stop Δpp | Day-bootstrap 95% CI, pp | Before n; Δpp | After n; Δpp |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| Session extreme | 88/660 (13.3%) | 42 | 27/60 (45.0%) | -19; -7.64 | -141 | +4.91 | [-6.68, +14.96] | 31; +7.64 | 11; -2.76 |
| OR5 | 65/498 (13.1%) | 24 | 21/44 (47.7%) | -9; -5.26 | -961 | -2.28 | [-20.66, +12.71] | 17; -2.63 | 7; -1.44 |
| OR15 | 58/476 (12.2%) | 22 | 20/40 (50.0%) | -12; -3.41 | -1,074 | -5.61 | [-26.47, +12.05] | 12; -6.12 | 10; -5.01 |
| Entry VWAP | 136/499 (27.3%) | 66 | 60/110 (54.5%) | -20; -6.23 | -1,114 | +0.56 | [-8.37, +9.11] | 47; +3.77 | 19; -7.38 |
| Prior-session extreme | 32/495 (6.5%) | 10 | 3/19 (15.8%) | -14; -12.41 | -25 | +5.81 | [-10.65, +21.19] | 7; +9.34 | 3; -2.44 |
| Nearest available automatic | 307/665 (46.2%) | 129 | 166/247 (67.2%) | -12; -3.14 | -1,882 | +1.07 | [-5.65, +6.65] | 91; +5.12 | 38; -8.62 |
| Adverse 1% | 145/665 (21.8%) | 66 | 52/113 (46.0%) | -20; -4.33 | -2,491 | +0.37 | [-6.36, +6.03] | 43; +1.76 | 23; -2.22 |
| Adverse 2% | 83/665 (12.5%) | 34 | 22/59 (37.3%) | -12; -3.61 | -4,281 | +0.15 | [-8.85, +8.60] | 19; +4.59 | 15; -5.46 |
| Adverse 3% | 52/665 (7.8%) | 17 | 15/37 (40.5%) | -2; -0.63 | -2,401 | -1.77 | [-11.68, +10.51] | 8; +4.43 | 9; -7.27 |
| 15 minutes | 412 | 205 | 277/344 (80.5%) | -12; -2.89 | -10,659 | -4.54 | [-13.91, +3.86] | 145; -5.16 | 60; -3.05 |
| 30 minutes | 326 | 137 | 213/274 (77.7%) | -15; -4.83 | -8,587 | -2.72 | [-13.55, +6.60] | 90; -1.10 | 47; -5.81 |
| 60 minutes | 254 | 84 | 158/219 (72.1%) | -9; -5.34 | -4,909 | -4.43 | [-19.87, +7.69] | 54; -4.65 | 30; -4.03 |
| 120 minutes | 204 | 57 | 123/172 (71.5%) | -24; -6.67 | -2,417 | -1.40 | [-22.07, +18.52] | 37; -7.51 | 20; +9.91 |

### put

| Candidate | Cross/eligible (%) or still open | Valued n | Later BE / observed n (%) | Median hold-after $; pp | Stop Δ$ | Mean stop Δpp | Day-bootstrap 95% CI, pp | Before n; Δpp | After n; Δpp |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| Session extreme | 175/802 (21.8%) | 73 | 54/132 (40.9%) | -30; -5.08 | -973 | -0.09 | [-10.77, +9.14] | 57; -1.75 | 16; +5.85 |
| OR5 | 128/561 (22.8%) | 46 | 43/101 (42.6%) | -20; -5.21 | -439 | +1.26 | [-9.77, +11.77] | 38; +2.82 | 8; -6.15 |
| OR15 | 121/550 (22.0%) | 42 | 34/92 (37.0%) | -19; -6.69 | -1,012 | +5.78 | [-4.68, +15.14] | 35; +6.91 | 7; +0.15 |
| Entry VWAP | 185/550 (33.6%) | 78 | 68/146 (46.6%) | -26; -6.78 | +2,550 | +2.32 | [-12.63, +14.99] | 64; -0.47 | 14; +15.06 |
| Prior-session extreme | 63/535 (11.8%) | 35 | 17/49 (34.7%) | -14; -3.43 | -2,761 | -0.28 | [-9.57, +8.60] | 25; +2.90 | 10; -8.21 |
| Nearest available automatic | 452/805 (56.1%) | 156 | 232/364 (63.7%) | -20; -7.23 | -414 | +2.59 | [-5.98, +10.20] | 129; +2.76 | 27; +1.75 |
| Adverse 1% | 217/805 (27.0%) | 89 | 75/170 (44.1%) | -18; -5.38 | -482 | +0.23 | [-9.49, +9.69] | 74; -3.46 | 15; +18.42 |
| Adverse 2% | 127/805 (15.8%) | 51 | 28/93 (30.1%) | -20; -4.29 | +980 | +8.04 | [+0.68, +16.09] | 37; +3.33 | 14; +20.50 |
| Adverse 3% | 78/805 (9.7%) | 24 | 9/51 (17.6%) | -32; -4.51 | -76 | +3.28 | [-7.69, +15.24] | 17; -3.39 | 7; +19.48 |
| 15 minutes | 550 | 243 | 329/445 (73.9%) | -20; -4.86 | -3,841 | -5.37 | [-15.57, +3.65] | 209; -3.35 | 34; -17.77 |
| 30 minutes | 424 | 148 | 248/339 (73.2%) | -5; -1.79 | -2,024 | -3.04 | [-18.62, +9.63] | 122; +0.07 | 26; -17.65 |
| 60 minutes | 327 | 95 | 185/271 (68.3%) | -12; -4.17 | +1,116 | -1.19 | [-21.55, +14.79] | 76; +5.93 | 19; -29.67 |
| 120 minutes | 261 | 63 | 139/219 (63.5%) | -16; -4.88 | +369 | +19.70 | [-6.94, +60.50] | 52; +20.70 | 11; +14.97 |

### Under 15 minutes call

| Candidate | Cross/eligible (%) or still open | Valued n | Later BE / observed n (%) | Median hold-after $; pp | Stop Δ$ | Mean stop Δpp | Day-bootstrap 95% CI, pp | Before n; Δpp | After n; Δpp |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| Session extreme | 6/246 (2.4%) | 5 | 1/3 (33.3%) | -20; -3.85 | +378 | +15.86 | [+1.93, +31.20] | 4; +19.82 | 1; +0.00 |
| OR5 | 2/169 (1.2%) | 1 | 1/2 (50.0%) | -30; -6.80 | +30 | +6.80 | [+6.80, +6.80] | 1; +6.80 | 0; — |
| OR15 | 3/161 (1.9%) | 1 | 2/2 (100.0%) | +221; +14.44 | -221 | -14.44 | [-14.44, -14.44] | 0; — | 1; -14.44 |
| Entry VWAP | 14/183 (7.7%) | 13 | 4/9 (44.4%) | -30; -7.24 | +1,266 | +6.84 | [+0.46, +12.80] | 11; +6.98 | 2; +6.07 |
| Prior-session extreme | 1/181 (0.6%) | 0 | 0/1 (0.0%) | — | — | — | — | 0; — | 0; — |
| Nearest available automatic | 51/247 (20.6%) | 24 | 23/40 (57.5%) | -24; -6.83 | +726 | +2.73 | [-2.69, +7.31] | 18; +2.99 | 6; +1.94 |
| Adverse 1% | 5/247 (2.0%) | 4 | 1/5 (20.0%) | -105; -8.18 | +362 | +8.49 | [+7.13, +9.86] | 3; +7.79 | 1; +10.59 |
| Adverse 2% | 0/247 (0.0%) | 0 | 0/0 (—) | — | — | — | — | 0; — | 0; — |
| Adverse 3% | 0/247 (0.0%) | 0 | 0/0 (—) | — | — | — | — | 0; — | 0; — |

### Under 15 minutes put

| Candidate | Cross/eligible (%) or still open | Valued n | Later BE / observed n (%) | Median hold-after $; pp | Stop Δ$ | Mean stop Δpp | Day-bootstrap 95% CI, pp | Before n; Δpp | After n; Δpp |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| Session extreme | 5/247 (2.0%) | 1 | 2/5 (40.0%) | -40; -8.33 | +40 | +8.33 | [+8.33, +8.33] | 1; +8.33 | 0; — |
| OR5 | 6/168 (3.6%) | 2 | 1/4 (25.0%) | +9; -1.40 | -18 | +1.40 | [-1.68, +4.48] | 1; +4.48 | 1; -1.68 |
| OR15 | 8/159 (5.0%) | 2 | 2/4 (50.0%) | +6; -2.52 | -12 | +2.52 | [-1.68, +6.72] | 1; +6.72 | 1; -1.68 |
| Entry VWAP | 11/159 (6.9%) | 8 | 1/6 (16.7%) | -18; -8.05 | +284 | +8.86 | [+1.06, +17.54] | 5; +6.77 | 3; +12.33 |
| Prior-session extreme | 0/168 (0.0%) | 0 | 0/0 (—) | — | — | — | — | 0; — | 0; — |
| Nearest available automatic | 64/247 (25.9%) | 20 | 23/50 (46.0%) | -24; -10.68 | +471 | +7.48 | [-3.16, +16.18] | 14; +6.71 | 6; +9.28 |
| Adverse 1% | 8/247 (3.2%) | 6 | 2/5 (40.0%) | -3; +2.76 | -683 | -1.10 | [-14.86, +13.84] | 4; -3.59 | 2; +3.88 |
| Adverse 2% | 2/247 (0.8%) | 2 | 0/1 (0.0%) | +4; -1.00 | -7 | +1.00 | [-2.00, +4.00] | 0; — | 2; +1.00 |
| Adverse 3% | 0/247 (0.0%) | 0 | 0/0 (—) | — | — | — | — | 0; — | 0; — |

### 15–60 minutes call

| Candidate | Cross/eligible (%) or still open | Valued n | Later BE / observed n (%) | Median hold-after $; pp | Stop Δ$ | Mean stop Δpp | Day-bootstrap 95% CI, pp | Before n; Δpp | After n; Δpp |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| Session extreme | 14/167 (8.4%) | 9 | 7/14 (50.0%) | +0; +0.00 | -1,086 | -5.35 | [-23.58, +12.49] | 5; +6.48 | 4; -20.13 |
| OR5 | 10/128 (7.8%) | 8 | 5/10 (50.0%) | +10; +3.10 | -853 | -7.41 | [-27.51, +8.13] | 4; +2.37 | 4; -17.19 |
| OR15 | 11/126 (8.7%) | 8 | 4/11 (36.4%) | -12; -3.41 | -1,070 | -8.87 | [-35.89, +10.77] | 3; +13.82 | 5; -22.49 |
| Entry VWAP | 19/123 (15.4%) | 15 | 6/17 (35.3%) | -10; -4.09 | -226 | +1.26 | [-5.99, +7.57] | 11; +0.66 | 4; +2.92 |
| Prior-session extreme | 3/118 (2.5%) | 3 | 1/3 (33.3%) | -3; -0.43 | -557 | -4.97 | [-32.14, +16.79] | 2; +8.61 | 1; -32.14 |
| Nearest available automatic | 73/168 (43.5%) | 38 | 41/62 (66.1%) | -6; -1.11 | -2,261 | -1.97 | [-11.07, +6.24] | 27; +7.43 | 11; -25.06 |
| Adverse 1% | 17/168 (10.1%) | 13 | 4/16 (25.0%) | -10; -2.61 | -1,683 | +1.22 | [-8.30, +11.43] | 8; +11.12 | 5; -14.61 |
| Adverse 2% | 4/168 (2.4%) | 4 | 2/4 (50.0%) | +256; +11.44 | -1,994 | -13.21 | [-31.08, +4.66] | 1; +7.50 | 3; -20.11 |
| Adverse 3% | 2/168 (1.2%) | 2 | 1/2 (50.0%) | +748; +20.49 | -1,497 | -20.49 | [-37.31, -3.66] | 0; — | 2; -20.49 |
| 15 minutes | 158 | 105 | 98/130 (75.4%) | -3; -1.22 | -8,937 | -10.90 | [-20.73, -2.07] | 75; -6.70 | 30; -21.38 |
| 30 minutes | 72 | 46 | 41/57 (71.9%) | -14; -4.07 | -5,162 | -11.23 | [-27.98, +1.53] | 35; -3.11 | 11; -37.07 |

### 15–60 minutes put

| Candidate | Cross/eligible (%) or still open | Valued n | Later BE / observed n (%) | Median hold-after $; pp | Stop Δ$ | Mean stop Δpp | Day-bootstrap 95% CI, pp | Before n; Δpp | After n; Δpp |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| Session extreme | 25/234 (10.7%) | 16 | 13/22 (59.1%) | -10; -1.22 | -878 | -10.55 | [-32.92, +5.96] | 14; -13.76 | 2; +11.96 |
| OR5 | 16/163 (9.8%) | 8 | 7/14 (50.0%) | -46; -8.88 | +359 | +6.92 | [-16.84, +30.62] | 7; +10.80 | 1; -20.24 |
| OR15 | 16/164 (9.8%) | 8 | 7/15 (46.7%) | -18; -11.38 | -168 | +10.07 | [-5.60, +26.43] | 8; +10.07 | 0; — |
| Entry VWAP | 39/171 (22.8%) | 21 | 21/36 (58.3%) | -6; -1.54 | -89 | -11.86 | [-36.43, +6.18] | 17; -15.39 | 4; +3.15 |
| Prior-session extreme | 9/155 (5.8%) | 6 | 3/7 (42.9%) | -35; -5.32 | +392 | +12.45 | [-0.71, +30.38] | 5; +14.94 | 1; +0.00 |
| Nearest available automatic | 119/235 (50.6%) | 56 | 67/106 (63.2%) | -13; -5.54 | -2,256 | -6.57 | [-16.96, +4.41] | 50; -4.86 | 6; -20.85 |
| Adverse 1% | 25/235 (10.6%) | 16 | 6/23 (26.1%) | -28; -6.60 | +261 | -6.62 | [-37.41, +12.63] | 15; -6.08 | 1; -14.74 |
| Adverse 2% | 7/235 (3.0%) | 6 | 1/6 (16.7%) | -13; -3.03 | +234 | +4.79 | [+1.76, +8.78] | 5; +5.61 | 1; +0.69 |
| Adverse 3% | 1/235 (0.4%) | 1 | 0/1 (0.0%) | -30; -6.25 | +30 | +6.25 | [+6.25, +6.25] | 1; +6.25 | 0; — |
| 15 minutes | 223 | 132 | 124/177 (70.1%) | -19; -4.93 | -1,483 | -5.92 | [-15.60, +2.88] | 118; -5.96 | 14; -5.57 |
| 30 minutes | 97 | 46 | 48/68 (70.6%) | -2; -0.78 | -1,308 | -9.59 | [-23.71, +2.63] | 40; -10.28 | 6; -5.00 |

### Over 60 minutes call

| Candidate | Cross/eligible (%) or still open | Valued n | Later BE / observed n (%) | Median hold-after $; pp | Stop Δ$ | Mean stop Δpp | Day-bootstrap 95% CI, pp | Before n; Δpp | After n; Δpp |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| Session extreme | 68/247 (27.5%) | 28 | 19/43 (44.2%) | -20; -9.07 | +567 | +6.26 | [-10.21, +19.13] | 22; +5.68 | 6; +8.35 |
| OR5 | 53/201 (26.4%) | 15 | 15/32 (46.9%) | -6; -4.05 | -138 | -0.16 | [-27.71, +20.60] | 12; -5.08 | 3; +19.54 |
| OR15 | 44/189 (23.3%) | 13 | 14/27 (51.9%) | -21; -8.24 | +217 | -2.93 | [-35.19, +22.11] | 9; -12.76 | 4; +19.20 |
| Entry VWAP | 103/193 (53.4%) | 38 | 50/84 (59.5%) | -18; -6.14 | -2,154 | -1.87 | [-17.80, +13.08] | 25; +3.72 | 13; -12.61 |
| Prior-session extreme | 28/196 (14.3%) | 7 | 2/15 (13.3%) | -21; -16.58 | +532 | +10.43 | [-10.68, +29.55] | 5; +9.63 | 2; +12.41 |
| Nearest available automatic | 183/250 (73.2%) | 67 | 102/145 (70.3%) | -6; -3.49 | -347 | +2.20 | [-8.45, +12.81] | 46; +4.59 | 21; -3.03 |
| Adverse 1% | 123/250 (49.2%) | 49 | 47/92 (51.1%) | -20; -4.32 | -1,170 | -0.52 | [-8.80, +6.73] | 32; -1.15 | 17; +0.67 |
| Adverse 2% | 79/250 (31.6%) | 30 | 20/55 (36.4%) | -20; -4.56 | -2,287 | +1.93 | [-8.20, +11.35] | 18; +4.42 | 12; -1.80 |
| Adverse 3% | 50/250 (20.0%) | 15 | 14/35 (40.0%) | -21; -4.86 | -904 | +0.73 | [-8.57, +12.57] | 8; +4.43 | 7; -3.50 |
| 15 minutes | 254 | 100 | 179/214 (83.6%) | -22; -7.71 | -1,722 | +2.13 | [-11.62, +15.13] | 70; -3.50 | 30; +15.28 |
| 30 minutes | 254 | 91 | 172/217 (79.3%) | -18; -8.51 | -3,425 | +1.58 | [-13.00, +14.15] | 55; +0.17 | 36; +3.74 |
| 60 minutes | 254 | 84 | 158/219 (72.1%) | -9; -5.34 | -4,909 | -4.43 | [-20.48, +7.73] | 54; -4.65 | 30; -4.03 |
| 120 minutes | 204 | 57 | 123/172 (71.5%) | -24; -6.67 | -2,417 | -1.40 | [-24.59, +18.53] | 37; -7.51 | 20; +9.91 |

### Over 60 minutes put

| Candidate | Cross/eligible (%) or still open | Valued n | Later BE / observed n (%) | Median hold-after $; pp | Stop Δ$ | Mean stop Δpp | Day-bootstrap 95% CI, pp | Before n; Δpp | After n; Δpp |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| Session extreme | 145/321 (45.2%) | 56 | 39/105 (37.1%) | -34; -7.74 | -135 | +2.75 | [-7.21, +11.62] | 42; +2.01 | 14; +4.98 |
| OR5 | 106/230 (46.1%) | 36 | 35/83 (42.2%) | -22; -5.21 | -780 | -0.01 | [-13.84, +12.24] | 30; +0.90 | 6; -4.55 |
| OR15 | 97/227 (42.7%) | 32 | 25/73 (34.2%) | -25; -6.21 | -832 | +4.91 | [-8.25, +17.41] | 26; +5.94 | 6; +0.45 |
| Entry VWAP | 135/220 (61.4%) | 49 | 46/104 (44.2%) | -33; -8.04 | +2,355 | +7.32 | [-14.67, +22.98] | 42; +4.70 | 7; +23.03 |
| Prior-session extreme | 54/212 (25.5%) | 29 | 14/42 (33.3%) | -10; -2.95 | -3,153 | -2.91 | [-13.95, +6.51] | 20; -0.12 | 9; -9.12 |
| Nearest available automatic | 269/323 (83.3%) | 80 | 142/208 (68.3%) | -26; -8.89 | +1,371 | +7.78 | [-6.54, +19.43] | 65; +7.78 | 15; +7.78 |
| Adverse 1% | 184/323 (57.0%) | 67 | 67/142 (47.2%) | -16; -5.41 | -60 | +1.99 | [-9.43, +14.13] | 55; -2.73 | 12; +23.61 |
| Adverse 2% | 118/323 (36.5%) | 43 | 27/86 (31.4%) | -21; -5.30 | +753 | +8.82 | [+0.11, +18.49] | 32; +2.97 | 11; +25.84 |
| Adverse 3% | 77/323 (23.8%) | 23 | 9/50 (18.0%) | -35; -3.71 | -106 | +3.16 | [-8.16, +16.04] | 16; -3.99 | 7; +19.48 |
| 15 minutes | 327 | 111 | 205/268 (76.5%) | -20; -4.76 | -2,358 | -4.71 | [-26.93, +11.16] | 91; +0.04 | 20; -26.31 |
| 30 minutes | 327 | 102 | 200/271 (73.8%) | -12; -4.96 | -716 | -0.09 | [-21.62, +16.90] | 82; +5.12 | 20; -21.45 |
| 60 minutes | 327 | 95 | 185/271 (68.3%) | -12; -4.17 | +1,116 | -1.19 | [-24.53, +14.38] | 76; +5.93 | 19; -29.67 |
| 120 minutes | 261 | 63 | 139/219 (63.5%) | -16; -4.88 | +369 | +19.70 | [-6.97, +57.67] | 52; +20.70 | 11; +14.97 |

## Reproduction and verification receipt

- Owning code read at commit `df6a5eead67bf5cc009a42957162465e94db702f`; pure chart-level implementation, journal timestamp convention (naive New York wall clock), option multiplier 100, actual FIFO fill ledger.
- The original audit's aggregate counts, account split, trading-day count, half split and realized dollars match. Per-trade premium/P&L reconciliation passed for the entire extract. Additional independent assertions passed for candidate denominators, adverse-side selection, strict survivor risk sets, close/high recovery bounds, paired dollar/return arithmetic and aggregate sums.
- Frozen input/output receipts and analysis scripts remain in private local scratch directory `/private/tmp/invalidation-20261025`; no raw journal rows, fill IDs, option-path files or server archive are committed. Read-only server cache archive plus local cache inputs are hashed in per-feed receipts. Hashes identify this run; they do not guarantee scratch-file retention.

| Artifact | SHA-256 |
|---|---|
| `journal.json` | `023e0e11302cdc685f789dfd452d103feeb36d87385232c819fc8eedb1878eda` |
| `server-cache.tgz` | `1518056d7347bece56d926d9d07c61d07ac387aa7ab3787f61b3364b87091fe3` |
| `receipt-iex.json` | `83bf5093c61fb667327b9ec6ca6c1c8fb396c1b6b6c7e27ca261cc8ddad13f2b` |
| `receipt-sip.json` | `9c0bbd436ea728a4db965bd140420116d6cbb4166fe9f343d85dbc9c60cf42c5` |
| `rows-iex.json` | `fd4a5a904902d7260339f0d72327cb78ce1ae6becf65cc9b69aed5056a054bab` |
| `rows-sip.json` | `f4d3b059c2ab738d2cf2b74ab35258bb84c65f16353a71604a02dc2f7cf81f4c` |
| `summary-iex.json` | `6a1501e5726edde80172cd1353a49c0ff56110e9a2e4efd43f8b41d5b5a93cfe` |
| `summary-sip.json` | `212b39098a03084541d4bde3cc83aa3b2b034da2e9a32737fdf36a39b6b6cdd5` |
| `study.py` | `55fb1b45d21af244f9ae3d7f234e831eaad5b31f60adebab131b4b566ac35dc4` |
| `recovery.py` | `da918831390b9b91d6cfd17ea90ffdec1940b0bda5e9d668d76fd2fa6c4f0599` |
| `summarize.py` | `cd23ca1ab95d2111771321435daa468a6fc2f01b8f9d2d49fe9799e0d7d292de` |
| `check.py` | `5419aba0847b8cdcaa4384a89a8717bd48a406915ee796c5dfefc48e522902d7` |

### Archived analysis recipe

The following source is documentation of the offline research, not installed application code. For another machine, change the repository/cache/scratch path constants; preserve the definitions and frozen input hashes for an exact rerun. The private `journal.json` is the read-only extractor output; `cache/` is the unpacked read-only server archive. Run the primary script once with default IEX and once with `STUDY_FEED=sip`, then run the recovery pass, summary pass and verification pass in that order. The recovery pass deliberately measures later recovery even when no crossing-minute mark exists. Requires the backend's existing Python environment (NumPy/pandas); it makes no network calls.

<details>
<summary>Offline replay, recovery, day bootstrap and consistency checks</summary>

**study.py**

```python
"""Offline research only. Reads frozen JSON/cache; writes scratch aggregate receipts."""
import os, sys, json, hashlib, math
from pathlib import Path
from datetime import datetime,date,time,timedelta,timezone
from collections import defaultdict,Counter
from functools import lru_cache
from bisect import bisect_left,bisect_right
import numpy as np
sys.path.insert(0, '/Users/user/.codex/worktrees/609f/TradeJournal/backend')
from app.engine.chart_levels import compute_levels
from scripts.exit_counterfactual_study import Position, et, occ, actual_outcome
from decimal import Decimal
from zoneinfo import ZoneInfo
ET=ZoneInfo('America/New_York'); UTC=timezone.utc
ROOT=Path('/private/tmp/invalidation-20261025')
LOCAL=Path('/Users/user/TradeJournal/backend/data/alpaca_cache'); SERVER=ROOT/'cache'
# Primary: original journal's IEX stock cache. SIP is a separate sensitivity run.
FEED=os.environ.get('STUDY_FEED','iex')
HOLIDAYS=set('2025-01-01 2025-01-09 2025-01-20 2025-02-17 2025-04-18 2025-05-26 2025-06-19 2025-07-04 2025-09-01 2025-11-27 2025-12-25 2026-01-01 2026-01-19 2026-02-16 2026-04-03 2026-05-25 2026-06-19 2026-07-03 2026-09-07 2026-11-26 2026-12-25'.split())
EARLY=set('2025-07-03 2025-11-28 2025-12-24 2026-11-27 2026-12-24'.split())
def session(d): return d.weekday()<5 and d.isoformat() not in HOLIDAYS
def stamp(d,m): return int(datetime.combine(d,time(m//60,m%60),ET).timestamp())
def close(d): return stamp(d,780 if d.isoformat() in EARLY else 960)
def days(a,b):
 while a<=b:
  yield a; a+=timedelta(days=1)
CAL={d:dict(status='open' if session(d) else 'closed',open=570,close=780 if d.isoformat() in EARLY else 960) for d in days(date(2025,1,1),date(2026,12,31))}
def prev(d):
 d-=timedelta(days=1)
 while not session(d): d-=timedelta(days=1)
 return d
files={}; conflicts=Counter()
def read(p):
 raw=p.read_bytes(); files[str(p)]=hashlib.sha256(raw).hexdigest(); return json.loads(raw)
def parse(b,source):
 t=int(datetime.fromisoformat(b['t'].replace('Z','+00:00')).timestamp())
 return dict(time=t,open=float(b['o']),high=float(b['h']),low=float(b['l']),close=float(b['c']),volume=float(b['v']),source=source)
@lru_cache(maxsize=25000)
def minutes(ticker,d):
 # Server wins duplicate timestamps: same feed only; local fills missing days/minutes.
 out={}
 for root in (LOCAL,SERVER):
  p=root/f'stocks/1Min/{FEED}'/ticker/f'{d}.json'
  if p.exists():
   for b in read(p):
    q=parse(b,FEED)
    if q['time'] in out and q!=out[q['time']]: conflicts['stock_duplicate_difference']+=1
    out[q['time']]=q
 return sorted(out.values(),key=lambda b:b['time'])
@lru_cache(maxsize=10000)
def raw_daily(ticker,d):
 bars=[b for b in minutes(ticker,d) if stamp(d,570)<=b['time']<close(d)]
 if not bars:return None
 # Same raw price basis as minute paths, never adjusted daily-cache prices.
 return dict(time=stamp(d,570),open=bars[0]['open'],high=max(b['high'] for b in bars),low=min(b['low'] for b in bars),close=bars[-1]['close'],volume=sum(b['volume'] for b in bars),source=f'{FEED} minute aggregate')
@lru_cache(maxsize=3000)
def option_bars(symbol):
 out={}
 for root in (LOCAL,SERVER):
  for p in sorted((root/'options/1Min'/symbol).glob('*.json')):
   for b in read(p):
    q=parse(b,'option trade')
    if q['time'] in out and q!=out[q['time']]: conflicts['option_duplicate_difference']+=1
    out[q['time']]=q
 return out
names=['session','OR5','OR15','VWAP','prior_day','auto','fixed1','fixed2','fixed3']
rows=[]; audit=Counter(); auto_kinds=Counter(); auto_missing=Counter(); fillgroups=defaultdict(list)
data=read(ROOT/'journal.json')
for f in data['fills']:
 fillgroups[f['trade_id']].append(dict(side=f['side'],contracts=Decimal(str(f['contracts'])),price=Decimal(str(f['price'])),at=et(f['executed_at']),role=f['role']))
for index,t in enumerate(data['trades']):
 fills=fillgroups[t['id']]; pos=Position(fills)
 actual,premium=actual_outcome(pos)
 if abs(float(actual)-float(t['realized_pnl']))>.51: audit['pnl_mismatch']+=1
 if abs(float(premium)-float(t['total_premium_paid']))>.51: audit['premium_mismatch']+=1
 entry=int(et(t['opened_at']).timestamp()); end=int(et(t['closed_at']).timestamp()); d=datetime.fromtimestamp(entry,ET).date()
 dur=(end-entry)/60
 base=dict(id=t['id'],day=d.isoformat(),period='before' if d<date(2026,4,1) else 'after',side=t['option_type'],hold='<15' if dur<15 else '15-60' if dur<=60 else '>60',duration=dur,actual=float(actual),premium=float(premium))
 symbol=occ(t['ticker'],date.fromisoformat(t['expiration']),t['option_type'],t['strike']); opts=option_bars(symbol)
 optkeys=sorted(opts)
 filltimes=[int(f['at'].timestamp()) for f in fills]
 adds=[int(f['at'].timestamp()) for f in fills if f['side']=='buy_to_open']
 def mark(s):
  # A completed full minute with no actual fill inside or at its close.
  b=opts.get(s)
  if not b or s<entry or s+60>=end or any(s<=f<=s+60 for f in filltimes):return None
  if any(a>s for a in adds):return None  # canceling a later purchase changes capital: not comparable
  realized,lots,cost=pos.state(datetime.fromtimestamp(s,UTC))
  if not lots or cost<=0:return None
  value=float(realized)+sum(float(q)*(b['close']*100-float(p)) for q,p in lots)
  return value
 def outcome(s):
  value=mark(s)
  if value is None:return dict(mark=None)
  later=[]
  for k in optkeys[bisect_right(optkeys,s):bisect_left(optkeys,end-60)]:
   val=mark(k)
   if val is not None:later.append(val)
  # 'Recovered' is later observed minute-close >= full-trade breakeven, strictly before exit.
  recovery=any(x>=0 for x in later) if later else None
  return dict(mark=value,delta=value-float(actual),pp=100*(value-float(actual))/float(premium),recovered=recovery,red=value<0,post_marks=len(later),at=s)
 # All still-open risk sets, elapsed wall-clock minutes, no overnight deferral.
 for n in [15,30,60,120]:
  at=entry+n*60
  if end>at:
   s=math.ceil(at/60)*60
   rows.append(dict(base,candidate=f'time{n}',eligible=True,cross=True,**outcome(s)))
 today=minutes(t['ticker'],d)
 before=[b for b in today if b['time']+60<=entry]
 ref=before[-1]['close'] if before and entry-(before[-1]['time']+60)<=300 else None
 rth=[b for b in before if stamp(d,570)<=b['time']<close(d)]
 prior=prev(d); daily=[b for day in days(d-timedelta(days=120),d-timedelta(days=1)) if session(day) and (b:=raw_daily(t['ticker'],day))]
 levels={n:None for n in names}; direction=-1 if t['option_type']=='call' else 1
 side='low' if direction==-1 else 'high'; extreme=min if direction==-1 else max
 if ref:
  levels.update({f'fixed{p}':ref*(1+direction*p/100) for p in [1,2,3]})
  if rth:
   levels['session']=extreme(b[side] for b in rth)
   volume=sum(b['volume'] for b in rth)
   levels['VWAP']=sum((b['high']+b['low']+b['close'])/3*b['volume'] for b in rth)/volume if volume else None
  for n in [5,15]:
   span=[b for b in rth if b['time']<stamp(d,570+n)]
   if entry>=stamp(d,570+n) and span:levels[f'OR{n}']=extreme(b[side] for b in span)
  p=raw_daily(t['ticker'],prior)
  if p:levels['prior_day']=p[side]
  computed=compute_levels(d,minutes(t['ticker'],prior)+today,daily,entry,calendar=CAL,reference=ref)
  auto_missing.update(computed.missing.keys())
  eligible=[lv for lv in computed.levels if (lv.price-ref)*direction>0]
  if eligible:
   lv=min(eligible,key=lambda lv:abs(lv.price-ref)); levels['auto']=lv.price; auto_kinds[lv.kind]+=1
 else:audit['no_fresh_entry_reference']+=1
 endday=datetime.fromtimestamp(end,ET).date()
 path=[b for day in days(d,endday) for b in minutes(t['ticker'],day) if b['time']>=entry and b['time']+60<end and stamp(day,570)<=b['time']<close(day)]
 expected=sum(max(0,(min(end-1,close(day))-max(math.ceil(entry/60)*60,stamp(day,570)))//60) for day in days(d,endday) if session(day))
 audit['trades_no_path']+=not bool(path)
 for name in names:
  level=levels[name]
  reason='missing entry reference/level' if level is None else 'not on adverse side' if (level-ref)*direction<=0 else 'no observed in-trade underlying bars' if not path else None
  if reason:
   rows.append(dict(base,candidate=name,eligible=False,reason=reason));continue
  hit=next((b for b in path if (b['low']<level if direction==-1 else b['high']>level)),None)
  rows.append(dict(base,candidate=name,eligible=True,cross=hit is not None,coverage=len(path)/expected if expected else None,level=level,ref=ref,**(outcome(hit['time']) if hit else {})))
 if index%250==0:print('processed',index,flush=True)
assert len(data['trades'])==1528
assert audit['pnl_mismatch']==0 and audit['premium_mismatch']==0, audit
(ROOT/f'rows-{FEED}.json').write_text(json.dumps(rows))
receipt=dict(feed=FEED,audit=dict(audit),auto_kinds=dict(auto_kinds),auto_missing=dict(auto_missing),conflicts=dict(conflicts),files=files)
(ROOT/f'receipt-{FEED}.json').write_text(json.dumps(receipt,indent=2))
print('DONE',json.dumps({k:v for k,v in receipt.items() if k!='files'}),flush=True)
```

**recovery.py**

```python
"""Add observed later recovery for ALL crossings, even without a cross-minute option mark."""
import sys,json,math
from pathlib import Path
from datetime import datetime,date,timedelta,timezone
from zoneinfo import ZoneInfo
from decimal import Decimal
from functools import lru_cache
from collections import defaultdict
sys.path.insert(0,'/Users/user/.codex/worktrees/609f/TradeJournal/backend')
from scripts.exit_counterfactual_study import Position,et,occ
R=Path('/private/tmp/invalidation-20261025'); L=Path('/Users/user/TradeJournal/backend/data/alpaca_cache');ET=ZoneInfo('America/New_York')
data=json.loads((R/'journal.json').read_text());trades={t['id']:t for t in data['trades']};fills=defaultdict(list)
for f in data['fills']:fills[f['trade_id']].append(dict(side=f['side'],contracts=Decimal(str(f['contracts'])),price=Decimal(str(f['price'])),at=et(f['executed_at'])))
@lru_cache(maxsize=4000)
def options(symbol):
 out={}
 for root in (L,R/'cache'):
  for p in sorted((root/'options/1Min'/symbol).glob('*.json')):
   for b in json.loads(p.read_text()):out[int(datetime.fromisoformat(b['t'].replace('Z','+00:00')).timestamp())]=b
 return out
@lru_cache(maxsize=10000)
def underlying(feed,ticker,day):
 out={}
 for root in (L,R/'cache'):
  p=root/f'stocks/1Min/{feed}'/ticker/f'{day}.json'
  if p.exists():
   for b in json.loads(p.read_text()):out[int(datetime.fromisoformat(b['t'].replace('Z','+00:00')).timestamp())]=b
 return sorted(out.items())
for feed in ['iex','sip']:
 rows=json.loads((R/f'rows-{feed}.json').read_text());byid=defaultdict(list)
 for r in rows:byid[r['id']].append(r)
 for tid,rr in byid.items():
  t=trades[tid];fs=fills[tid];pos=Position(fs);entry=int(et(t['opened_at']).timestamp());end=int(et(t['closed_at']).timestamp());ft=[int(f['at'].timestamp()) for f in fs];adds=[int(f['at'].timestamp()) for f in fs if f['side']=='buy_to_open']
  opts=options(occ(t['ticker'],date.fromisoformat(t['expiration']),t['option_type'],t['strike']))
  marks=[]
  for k,b in sorted(opts.items()):
   if k<entry or k+60>=end or any(k<=f<=k+60 for f in ft) or any(a>k for a in adds):continue
   realized,lots,cost=pos.state(datetime.fromtimestamp(k,timezone.utc))
   if not lots or cost<=0:continue
   gain=lambda field:float(realized)+sum(float(q)*(float(b[field])*100-float(p)) for q,p in lots)
   marks.append((k,gain('c'),gain('h')))
  for r in rr:
   if not r.get('cross'):continue
   at=r.get('at')
   if at is None:
    if r['candidate'].startswith('time'):at=math.ceil((entry+int(r['candidate'][4:])*60)/60)*60
    else:
     d=datetime.fromtimestamp(entry,ET).date();last=datetime.fromtimestamp(end,ET).date();hits=[]
     while d<=last:
      for k,b in underlying(feed,t['ticker'],d):
       local=datetime.fromtimestamp(k,ET);cm=780 if str(d) in ['2025-07-03','2025-11-28','2025-12-24','2026-11-27','2026-12-24'] else 960
       if k>=entry and k+60<end and 570<=local.hour*60+local.minute<cm and (float(b['l'])<r['level'] if r['side']=='call' else float(b['h'])>r['level']):hits.append(k)
      d+=timedelta(days=1)
     assert hits
     at=min(hits)
   r['at']=at
   later=[(c,h) for k,c,h in marks if k>at] if not any(a>at for a in adds) else []
   r['recovered']=any(c>=0 for c,h in later) if later else None
   r['recovered_high']=any(h>=0 for c,h in later) if later else None
   r['post_marks']=len(later)
   r['red']=r.get('mark') is not None and r['mark']<0

 (R/f'rows-{feed}.json').write_text(json.dumps(rows))
 print('recovery updated',feed,flush=True)
```

**summarize.py**

```python
import json
from pathlib import Path
from collections import Counter
import numpy as np
R=Path('/private/tmp/invalidation-20261025')
rng=np.random.default_rng(20261025)
def summarize(rows):
 el=[r for r in rows if r['eligible']]; hit=[r for r in el if r.get('cross')]; valued=[r for r in hit if r.get('mark') is not None]; recovery=[r for r in hit if r.get('recovered') is not None]; red=[r for r in recovery if r['red']]
 out=dict(n=len(rows),eligible=len(el),cross=len(hit),valued=len(valued),days=len(set(r['day'] for r in valued)),recovery_n=len(recovery),recoveries=sum(r['recovered'] for r in recovery),high_recoveries=sum(r['recovered_high'] for r in recovery),red_n=len(red),red_recoveries=sum(r['recovered'] for r in red),missing_reasons=dict(Counter(r['reason'] for r in rows if not r['eligible'])))
 if not valued:return out
 pp=np.array([r['pp'] for r in valued]); delta=np.array([r['delta'] for r in valued]); ds=sorted(set(r['day'] for r in valued)); index={d:i for i,d in enumerate(ds)}
 counts=np.zeros(len(ds)); sums=np.zeros(len(ds)); dollars=np.zeros(len(ds))
 for r in valued:
  i=index[r['day']];counts[i]+=1;sums[i]+=r['pp'];dollars[i]+=r['delta']
 weights=rng.multinomial(len(ds),np.full(len(ds),1/len(ds)),size=2000)
 ci=np.quantile((weights@sums)/(weights@counts),[.025,.975]);dci=np.quantile(weights@dollars,[.025,.975])
 out.update(actual_dollars=sum(r['actual'] for r in valued),counterfactual_dollars=sum(r['mark'] for r in valued),actual_mean_return=float(np.mean([100*r['actual']/r['premium'] for r in valued])),counterfactual_mean_return=float(np.mean([100*r['mark']/r['premium'] for r in valued])),mean_pp=float(np.mean(pp)),median_pp=float(np.median(pp)),delta=float(sum(delta)),median_post_dollar=float(np.median(-delta)),median_post_pp=float(np.median(-pp)),post_positive=int(sum(d<0 for d in delta)),ci=list(ci),dollar_ci=list(dci))
 return out
def split(rows):return {p:summarize([r for r in rows if p=='all' or r['period']==p]) for p in ['all','before','after']}
for feed in ['iex','sip']:
 if not (R/f'rows-{feed}.json').exists(): continue
 rows=json.loads((R/f'rows-{feed}.json').read_text());result={}
 for name in dict.fromkeys(r['candidate'] for r in rows):
  rr=[r for r in rows if r['candidate']==name]; groups={'all':rr}
  for h in ['<15','15-60','>60']:groups[h]=[r for r in rr if r['hold']==h]
  for s in ['call','put']:groups[s]=[r for r in rr if r['side']==s]
  for h in ['<15','15-60','>60']:
   for s in ['call','put']:groups[h+' '+s]=[r for r in rr if r['hold']==h and r['side']==s]
  result[name]={g:split(rs) for g,rs in groups.items()}
 (R/f'summary-{feed}.json').write_text(json.dumps(result,indent=2))
 print(feed)
 for name,g in result.items():
  a,b,c=[g['all'][p] for p in ['all','before','after']]
  print(name, 'E/X/V',a['eligible'],a['cross'],a['valued'],'delta',round(a.get('delta',0)), 'pp',round(a.get('mean_pp',0),2),'CI',a.get('ci'), 'halves',b['valued'],round(b.get('mean_pp',0),2),c['valued'],round(c.get('mean_pp',0),2))
```

**check.py**

```python
import json,hashlib
from pathlib import Path
from collections import Counter
import numpy as np
P=Path('/private/tmp/invalidation-20261025');d=json.loads((P/'journal.json').read_text());ts=d['trades']
assert len(ts)==1528 and len(set(t['opened_at'][:10] for t in ts))==287
assert sum(t['opened_at']<'2026-04-01' for t in ts)==1178
assert abs(sum(float(t['realized_pnl']) for t in ts)-14037.98)<1e-6
for feed in ['iex','sip']:
 rows=json.loads((P/f'rows-{feed}.json').read_text());counts=Counter(r['candidate'] for r in rows)
 for n in ['session','OR5','OR15','VWAP','prior_day','auto','fixed1','fixed2','fixed3']:assert counts[n]==1528
 for r in rows:
  if r.get('level') is not None:assert (r['level']-r['ref'])*(-1 if r['side']=='call' else 1)>0
  if r.get('mark') is not None:
   assert r['cross'] and r['eligible']
   assert abs(r['delta']-(r['mark']-r['actual']))<1e-7
   assert abs(r['pp']-r['delta']/r['premium']*100)<1e-7
  if r.get('recovered'):assert r['recovered_high']
  if r['candidate'].startswith('time'):assert r['duration']>int(r['candidate'][4:])
 # Independently reconstruct paired point estimates, rather than trusting summary formatting.
 s=json.loads((P/f'summary-{feed}.json').read_text())
 for n,g in s.items():
  rr=[r for r in rows if r['candidate']==n and r.get('mark') is not None]
  assert len(rr)==g['all']['all']['valued']
  assert abs(sum(r['delta'] for r in rr)-g['all']['all']['delta'])<1e-7
  assert abs(np.mean([r['pp'] for r in rr])-g['all']['all']['mean_pp'])<1e-7
print('PASS: cohort, half split, all level denominators, adverse directions, time risk sets, recovery bounds, paired dollar/return arithmetic, aggregate reconciliation')
```

</details>
