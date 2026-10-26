# A more useful next strategy experiment

October 25, 2026. Proposed research design, not a registered candidate, changed
protocol, executable strategy or authorization to trade. No backtest was run.

**October 26 decision update:** the [experiment decision packet](etf-trend-experiment-decision-2026-10-26.md)
replaces the open-ended preparation sequence below with one fixed proposed case
and a no-go for current validation. Further infrastructure work is parked pending
data/design acceptance and a decision on whether bounded exploration is useful.

The owner subsequently accepted multi-week holds. See the
[data-and-accounting acceptance packet](etf-trend-acceptance-2026-10-25.md) for
the next preparation milestone; no evaluation is authorized.

## Recommendation

Keep the failed ORB candidate closed. Do not spend an attempt on the current
end-of-day reversal shortcut. The [feasibility memo](eod-reversal-feasibility-2026-10-25.md)
explains the specific mismatches and data gaps.

**Investigate the feasibility of one slow, diversified trend strategy next, if
multi-week holdings and underlying instruments fit the owner's objective.** This
is a research-priority judgment from the bounded literature review, not a claim
that trend is the world's best strategy or profitable for this account. If the
objective requires intraday options, this recommendation does not satisfy it;
the next milestone instead remains point-in-time universe and execution-data
qualification, with no eligible new candidate established.

The useful change in approach is to choose the economic question before choosing
another signal. A profitable portfolio, a statistically credible timing edge,
and an executable personal trading process are three separate achievements.

## What the current Factory can and cannot establish

`backend/app/engine/factory_gates.py` (`summarize`, `_random_entries`) measures
trade returns in R and their difference from a ticker/period/side matched
random-entry average. Weekly clustering addresses dependence in that statistic.
`backend/app/engine/factory_rules.py` (`run_candidate`) runs one position at a
time within a ticker Series, using modeled next-bar entries and exits.

That is a useful test of conditional entry timing under specified exits and
costs. It is not a complete portfolio simulator: summing sequential trade R is
not the return on a funded account with overlapping trades, shared cash,
correlated exposures and position limits. Neither a pass nor a failure answers
every portfolio question. This observation does not invalidate the failed ORB
result, authorize an easier benchmark, or justify changing frozen gates.

| Economic question | Appropriate evidence before making the claim |
|---|---|
| Does owning risk make money? | Net funded-account returns versus cash; report market exposures. |
| Does this signal add value? | Incremental performance versus a prespecified comparable passive/exposure benchmark, with dependence and research multiplicity accounted for. |
| Is the portfolio useful to this owner? | Prespecified capital, drawdown tolerance, concentration, liquidity and holding constraints; report tradeoffs rather than choosing the nicest metric afterward. |
| Can it actually be executed? | Timestamped intents, quotes, attempted fills and reconciliation, including rejects and missed trades. |

An invented arithmetic example illustrates the distinction: a $10,000 account
returning 8% made $800. If the comparable passive account returned 10%, the
strategy lagged by $200 before any difference in risk is considered. Neither
number alone proves timing alpha or poor utility. These are assumed numbers,
not market observations or simulated historical results.

## Why trend deserves the next feasibility review

The [AQR description of the original time-series momentum data][tsmom] identifies
58 futures/forward instruments across equity indices, currencies, commodities
and government bonds. It describes a 12-month excess-return signal and one-month
holding period, with a monthly factor series beginning in 1985. Only the data
**description** was read; no factor file was downloaded or evaluated here.

[Babu et al., *Trends Everywhere* (2020)][everywhere] extend examination to 82
additional instruments and 16 equity factors. Their Section 5 compares trend
with a passive portfolio using the same volatility scaling, addressing whether
static exposure or sizing explains the result. Their reported returns are gross
of transaction costs; costs are outside the study's scope. Much of the instrument
set is unlike a retail stock/ETF portfolio. The authors' institutional overlap
with the earlier research limits independence of this supporting evidence.

The case for prioritizing feasibility is breadth of external evidence and a
simple source-derived horizon, not a selected recent return. The strongest
transfer risk is that an accessible long-only ETF implementation removes short
positions, changes instruments and weights, and loses much of the original
breadth. That implementation is a **new forward hypothesis**, not a replication.
Monthly decisions also do not manufacture independent observations: overlapping
lookbacks and common macro exposures remain. The Factory's short intraday
sample cannot settle a long-horizon portfolio question merely by generating
more trades.

No local strategy is validated by these papers. This review did not establish
independent post-publication retail net profitability, entitlement to the
necessary archives, or sufficient statistical power for a proposed ETF version.

## One concrete design card, pending feasibility and approval

This is a single proposed ETF adaptation for specification review. It is not
ready to register: exact universe, capital and statistical design remain explicit
blockers. Do not run it or substitute it into an existing Factory family.

| Component | Proposed choice and unresolved prerequisite |
|---|---|
| Economic hypothesis | Positive trailing excess return can identify useful periods of exposure across a diversified accessible universe, net of switching costs. |
| Source-derived horizon | One 12-month lookback, one calendar-month decision interval. No horizon sweep, ensemble, extra entry filter or optimized stop. |
| Universe | Select asset-class coverage and a dated eligibility rule before inspecting returns. Obtain stable identities, inception/closure histories and distributions. Freeze exact instruments or a deterministic selection rule; do not choose today's surviving winners. |
| Signal | At month-end, compare each eligible instrument's trailing 12-month total-return growth factor with the cash growth factor over exactly the same interval. Strictly greater means long; equality or less means cash. Require 13 month-end total-return index observations. |
| Observation time | A completed month-end close is input, never a fill assumed available to a signal computed from that close. Freeze provider publication latency and an as-of availability rule before evaluation. Later corrections must not silently overwrite the recorded signal. |
| Execution proposal | Submit the paper intent only after the information cutoff; model execution at the next eligible regular session under a separately frozen quote/fill convention. Next-open OHLC alone cannot establish an achievable fill. |
| Allocation | Proposed equal, fixed sleeves across the approved universe; each sleeve holds its instrument or cash. No leverage, shorts or redistribution of inactive sleeves. This deliberately differs from volatility-scaled futures evidence and needs its own test. |
| Management | Recompute monthly. A negative/equal signal moves that sleeve to cash at the next permitted execution. No optimized target or stop. A gap can exceed any desired loss limit; this is not a loss guarantee. |
| Missing inputs | Record an unavailable signal, not zero return or bearish evidence. Freeze separate handling for new entries, existing holdings, halts and closures before registration; no arbitrary substitute instrument. |
| Risk | Cap aggregate long exposure at 100% of funded capital. Exact sleeve/asset-class caps, minimum trade size, cash reserve and acceptable drawdown require the owner's constraints. They cannot be inferred from favorable history. |
| Costs | Include commissions, spread, slippage, fees and cash yield; distinguish embedded fund expenses from explicit trading charges to avoid double counting. Freeze costs and stress assumptions before returns. Tax treatment is a separate owner-specific comparison. |
| Options | Excluded from this first hypothesis. Options would change payoff, carry, selection, sizing and execution and require separate evidence. |

Equal sleeves are a proposed simplicity choice, not an evidence-supported optimum.
Do not silently convert this card into the original long-short, volatility-scaled
strategy when results disappoint. Do not add a second implementation merely to
pick the winner.

## Benchmarks and tests that prevent a misleading success

Propose one primary incremental-return estimand against a passive portfolio of
the **same instruments with the same base sleeve weights**, plus cash as a
separate economic reference. The passive comparator stays invested; the active
version moves sleeves to cash. Both need consistent dividends, calendars, fees,
corporate actions and valuation. Their difference includes changes in market
exposure; it is not automatically factor-adjusted alpha.

Report exposure and risk alongside that difference. If the owner instead wants
risk reduction, choose the primary risk/utility objective before evaluation.
Do not promote whichever of return, Sharpe or drawdown happens to look best.
A later volatility-scaled implementation would also need a comparator with the
same sizing mechanism; that would be another hypothesis, not a free sensitivity
check. A broad-market index alone is not an adequate control for changing the
asset mix.

Before registration, a statistical reviewer must freeze sampling units,
dependence handling, a meaningful minimum effect, precision/power requirements,
chronological splits, all comparisons and treatment of prior research. No
numerical new gate is set here. Existing Factory gates, attempts and protected
splits stay untouched. A new research design cannot erase past attempts or turn
previously viewed periods into unseen evidence. Public factor histories are not
an untouched personal holdout merely because we have not downloaded them.

### Invented acceptance cases for the smallest useful preparation

These specify future tests, not tests run against prices or a new application
implementation:

1. Total-return index 100 to 108 and cash growth 1.04 produce a long signal;
   100 to 104 with cash growth 1.04 produces cash. A price-only decline caused by
   a distribution must not be substituted for total return.
2. A corrected close received after the frozen cutoff cannot revise that intent.
   The correction remains a separately timestamped record.
3. Four equal sleeves with only two positive signals allocate 25% to each active
   sleeve and 50% to cash, not 50% to each active sleeve. This prevents implicit
   leverage/concentration when other assets turn off.
4. A missing quote preserves an unfilled intent and its reason. It does not become
   a midpoint fill or disappear from the opportunity denominator.
5. A closed or delisted fund retains its historical record and proceeds. It is
   not removed from the entire sample because it is absent today.
6. On assumed $10,000 capital, a $2,500 purchase at an assumed all-in 10 bp cost
   costs $2.50, or 2.5 bp of portfolio equity. Count a subsequent sale separately.
   The inputs are invented; this is units checking, not an estimate of costs.

## The next independently testable milestone

Deliver a **no-return data-and-accounting acceptance packet** for this one design,
conditional on the owner accepting the horizon/instruments. It should contain:

- An explicit objective, fixed eligible universe rule and capital/exposure constraints.
- Provider documentation and a coverage/identity manifest without strategy returns,
  including distributions, closures, cash series, known-at times and licensing.
- One immutable invented decision-to-intent-to-fill/rejection example, reconciled
  against cash and holdings, with the six cases above specified as acceptance tests.
- A reviewed statistical design and explicit decision whether a separately
  authorized evaluation is possible without violating Factory's existing history.

Only after those pass should there be an implementation/evaluation request.
Reuse the disabled paper adapter's prefix-only observation and receipt concepts
where compatible; do not force a monthly multi-asset funded portfolio through a
single-ticker intraday runner. Any missing portfolio accounting is useful bounded
engineering **after** the objective and inputs justify it, not a reason to build
a second Factory tonight.

For a future options version, first establish the underlying hypothesis, then
freeze contract selection using contemporaneous chains, expiries, strikes,
quotes and sizes. Preserve unavailable contracts and rejected fills, model both
sides of execution, and constrain premium and portfolio exposure. Option marks,
model prices and observed bid/ask fills must remain distinct. Prospective paper
receipts should eventually reconcile to actual user fills without fitting the
signal or contract rule to those fills. This review verified no options archive
or authorization for collection and did not invent a delta/expiry optimum.

## What changed tonight

The concrete output is a better specified next experiment and an explanation of
why a new intraday threshold is not the necessary next step. External historical
evidence supports prioritizing a feasibility question; source inspection exposes
scope limits; invented cases test the proposed semantics. There is **no new
measured performance or validated strategy**, and no new active protocol.

No strategy engine, ledger, budget, protected outcomes, schedules or application
code was modified. The proposal remains for owner review alongside the EOD
no-go memo. Work has narrowed the question and its falsification conditions
without consuming another candidate attempt.

[tsmom]: https://www.aqr.com/Insights/Datasets/Time-Series-Momentum-Factors-Monthly
[everywhere]: https://images.aqr.com/-/media/AQR/Documents/Insights/Journal-Article/AQR-Trends-Everywhere_JOIM.pdf
