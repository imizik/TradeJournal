# ETF trend: decide the experiment before building more

October 26, 2026. **Owner-review proposal; no evaluation authorized.** This fixes
one research case for review, not a registered Factory candidate or a tradable
strategy. Merging this document does not adopt a protocol, consume an attempt,
authorize data acquisition or activate anything.

**Subsequent authorized data review:** the [bounded acceptance audit](etf-data-acceptance-2026-10-26.md)
passed daily date coverage but failed overall acceptance. The fixed cash archive,
dated identity/actions, execution observations and historical availability remain
unaccepted. The proposed rules below are unchanged; no evaluation was authorized.

## Decision

**NO-GO for a validating run under the current Factory protocol. Park further
ETF infrastructure work.** There is no measured ETF strategy performance, no
accepted real-data manifest and no approved monthly-portfolio validation design.
The present history cannot be declared adequately powered from the evidence we
have. This is a readiness decision, not a finding that trend cannot work.

If the owner wants to continue, the useful next commitment is a bounded,
explicitly exploratory historical falsification exercise, conditional on the
data and protocol prerequisites below. It could reject an unattractive economic
case; a favorable result would not establish a tradable edge. Do not spend an
attempt, build a general simulator or acquire extensive quote history merely
because such an exercise is technically possible.

The primary question stays: **does this one signal add net account return over
the same passive portfolio?** A profitable account, incremental return and a
useful risk-reduction policy are different claims. Do not switch the primary
claim to drawdown, Sharpe or a favorable sleeve after seeing results. An owner
preference for risk reduction would require a new, explicit charter before data
inspection, not rescue this hypothesis after a disappointing return comparison.

## What the evidence actually supports

| Evidence class | Current conclusion |
|---|---|
| Historical local result | The separately authorized default ORB plus RVOL >= 2 candidate failed its screen. Its prior result remains closed; it was not reread or retested for this memo. |
| External research | [Time-series momentum research][tsmom] motivates investigating a 12-month signal. Its 58 futures/forwards, long/short positions and asset-class breadth do not validate four long/cash ETFs. [Trends Everywhere][everywhere] expands instruments but reports gross results and has overlapping authors; it is not independent retail net validation. |
| Preparation | The [pinned accounting fixture](etf-fixture-reconciler-2026-10-25.md) reconciles invented events. The separate [metadata PR #509](https://github.com/imizik/TradeJournal/pull/509) was open at this review; its transport tests do not establish historical coverage. |
| Forward hypothesis | The fixed ETF adaptation below might add value. No returns, subgroup results or live fills support that claim yet. |
| Validated result | None for this ETF proposal. Paper receipts could prove operation, not quickly supply missing decades of independent economic evidence. |

## One fixed research case for approval

This proposal supersedes the discretionary universe and unspecified cash
reference in the [October 25 design](strategy-research-path-2026-10-25.md) and
[acceptance packet](etf-trend-acceptance-2026-10-25.md). Those were proposals, not
registered rules. The choices below were made without calculating candidate
returns. They are not a parameter grid. Any material revision before a future
run must be visible in the spec history; revisions after outcomes cannot inherit
the same untouched-evidence claim or evade attempt accounting.

| Item | Fixed proposed choice |
|---|---|
| Instruments | SPY, EFA, EEM, IEF; USD, unleveraged ETF shares. Reference CUSIPs respectively 78462F103, 464287465, 464287234, 464287440, still requiring dated identity acceptance. |
| Selection meaning | A prospective practical roster covering S&P 500, MSCI EAFE, MSCI emerging markets and US 7–10-year Treasuries. No claim of an oldest-eligible census, optimal allocation or unbiased backward selection. No replacements. |
| Signal | For each ETF, compare its total-return index ratio at month-end m versus m−12 with the cash-reference ratio over exactly those endpoints. Strictly greater means long; equality or less means cash. Require all 13 month-end observations. |
| Cash reference for the signal | USD total-return version of the [S&P U.S. Treasury Bill 0–3 Month Index][cash-index], with source/version and publication timestamps in the manifest. This is a specified bill-return reference, not a quoted annual yield or assumed broker credit. No zero-yield or other-index fallback. Archive access and timely publication are unverified. |
| Total-return convention | Reinvest distributions at the raw ex-date close for signal-index construction, with splits reconciled on consistent share units. This is a signal convention; the funded account instead books receivables on ex-date and cash on payable date. No adjusted-price-plus-dividend double counting. |
| Decision clock | 08:00 America/New_York on the first regular session after month-end, using events effective by month-end and available by that cutoff. Preserve the observed version; later corrections cannot rewrite an intent. |
| Management | Monthly only. Long signals target their sleeve; nonpositive signals target zero shares. No intramonth stop, profit target, re-entry rule, volatility scaling, shorting or leverage. Holds may last multiple months. |
| Capital | A $10,000 research account, no contributions/withdrawals, whole shares. This specifies a small-account case, not the owner's capital or acceptable loss. |
| Allocation | Four 25% targets based on common pre-trade NAV; inactive allocations remain cash. No redistribution to active sleeves. Changes between decisions drift without rebalancing. |
| Account cash yield | Zero in this one modeled account, for both active and passive portfolios. This is an explicit non-interest-bearing research case, not a statement about the owner's broker. Signal cash reference and account interest are intentionally different. An interest-bearing account would require a separately approved case, not a favorable post-result substitution. |
| Historical execution model | On the decision session, the raw opening observation of the SIP minute starting 09:35 New York is the reference for one rebalance. No same-close fill and no next-available-bar substitution. This is a minute-bar counterfactual, not a tradable fill claim. |
| Modeled trading cost | Deduct 10 bp of absolute traded notional on each side, covering modeled spread/slippage/explicit charges in aggregate. Also report a mandatory 30 bp stress with the same signal and allocation procedure. These are prespecified assumptions, not measured costs or Factory's existing cost model. No cost sweep or selection of the better case. Fund expenses embedded in prices are not deducted again. |
| Comparator | Same initial capital, four ETFs, 25% targets, monthly rebalance, clock, whole-share/cash/settlement handling, prices and costs; always target long. The cash-reference index is a separate descriptive comparison, never an invested broker balance. |

The roster narrows earlier broad category descriptions: EFA is not all developed
ex-US equities, and IEF is specifically 7–10-year Treasuries. Three equity sleeves
share risk; four funds do not yield four independent economic histories. Looking
backward at these present-day surviving funds is exploratory. A dated identity
audit is still necessary, but an exhaustive market-wide ETF selection census is
not necessary to answer this explicitly roster-specific question.

For deterministic historical sizing, let N be NAV just before the rebalance and
p_i the specified raw execution reference. For an active sleeve the desired
whole-share holding is floor(0.25 N / (p_i (1+c))), with c = 0.001 (0.003 in the
mandatory stress). An inactive sleeve targets zero. Sell excess shares first;
fees reduce trade-date cash, and sale proceeds cannot fund purchases until
settlement. Buy deficits only from previously settled cash. If cash cannot fund
all deficits, scale requested purchase quantities by the common cash/required-
cost ratio and round down; allocate remaining affordable shares by largest
fractional remainder, ties in SPY/EFA/EEM/IEF order, without exceeding a target.
Use the applicable historical settlement calendar, not today's delay throughout.
Cash is pooled; target budgets constrain positions, not four separate accounts.

Missing signal data mean no increase and retention of existing shares, with an
unavailable decision recorded. Missing 09:35 observations mean unfilled intents.
Do not invent a fill or silently remove the affected month. Missing valuation,
unreconciled corporate actions, closure proceeds or cash-reference history fail
data acceptance: no scored aggregate may be emitted. Halts and closures retain
positions/claims until documented disposition. All failures remain in the report.

These rules make the proposed **modeled economic case** concrete. They do not
freeze an executable order strategy: verified information latency, live quotes,
order behavior, fees, liquidity and owner risk limits remain separate blockers.

## Available time and statistical resolution

[Alpaca documents stock/ETF history since 2016][coverage]. This is documentation,
not proof that the account can retrieve every required observation. The current
Factory discovery ends September 30, 2024; confirmation begins October 1, 2024,
and exam begins April 1, 2026. Those restrictions remain in force for the same
dates obtained through another provider. Earlier pre-discovery data are also
**not authorized for evaluation** by this memo.

Assuming complete January 2016 onward data, the first 13 month-ends run from
January 2016 through January 2017. The first holding month is February 2017.
February 2017–September 2024 contains **92 complete monthly observations**, or
7.67 years, before any missing-data exclusions. This is a calendar ceiling for a
potential earlier-history exploration, not an approved window or 92 independent
samples. Within the current July 2023–September 2024 discovery alone there are
at most 15 complete portfolio months if warm-up is available. Do not inspect
confirmation/exam to make the sample longer.

The primary estimand is 12 times the mean of paired monthly simple net returns:
active minus passive. This annualized arithmetic difference is not a CAGR
difference or factor alpha. Terminal dollars, both CAGRs, drawdowns, turnover,
cash exposure, unavailable decisions and cost stress must also be reported.

Propose **2 percentage points/year** as a minimum economically useful increment
for planning, subject to owner approval. It is a research hurdle, not a promised
return or a personal risk limit. The table below asks how hard detecting that
increment would be against zero, not how to prove the effect exceeds 2 points.

For independent, stationary normal return differences with assumed annualized
tracking standard deviation s, an approximate 80%-power planning relationship is
Y = ((z_(1−a) + z_0.80) s / 0.02)^2. Conversely the detectable annual increment
at Y years is (z_(1−a) + z_0.80) s / sqrt(Y). All inputs below are assumptions;
no return sample, volatility estimate, bootstrap or backtest was used.

| Assumed annual tracking SD | One-sided alpha used only for illustration | Years to detect 2 points/year | Detectable increment with 92 months |
|---|---|---:|---:|
| 5% | 5%, one prespecified test | 38.64 | 4.49 points/year |
| 10% | 5%, one prespecified test | 154.56 | 8.98 points/year |
| 5% | 5% / 84 | 104.18 | 7.37 points/year |
| 10% | 5% / 84 | 416.73 | 14.75 points/year |

Reproduction constants: z_0.80 = 0.841621; z_0.95 = 1.644854;
z_(1−0.05/84) = 3.241152; Y = 92/12. The last two rows illustrate retaining the
previously reported 83 counted attempts plus a hypothetical next candidate;
they neither reserve attempt 84 nor establish its eligibility or future count.
The first two rows are an optimistic single-test comparison, **not permission to
reset multiplicity**. No new significance gate is adopted.

This calculation does not establish actual power: tracking variance is unknown,
serial dependence can materially change it, regimes are not stationary, and a
positive result can occur by chance. Much lower tracking variance could improve
precision. The conclusion is that adequate power has not been demonstrated,
not that 38 years is a universal minimum or this hypothesis is disproven.
Buying more historical data might help but does not create an independent,
untouched validation set or justify its cost automatically.

Any future inferential design needs synchronized calendar sampling of the whole
portfolio difference, dependence treatment with a justified horizon, uncertainty
for the passive comparison, multiplicity accounting and a predeclared reporting
date. Do not multiply N by four ETFs or by daily/minute marks. A 12-month block
would leave only about eight block lengths in 92 months; naming a bootstrap is
not proof that its tail estimates are reliable. No block length, interval or
replacement acceptance gate is silently registered here.

## Data and authorization conditions

Before proposing any run, resolve these as a single bounded acceptance decision:

1. **Exact data contract:** dated identity for the four named funds; complete raw
   marks and required execution observations; reconciled distributions, splits,
   closures and settlement calendars; exact bill total-return series, rights and
   publication times. Record coverage, pagination, versions/hashes and missing
   values without computing strategy results. Missing credentials are an access
   task, not evidence that a provider lacks data. No subscription is authorized.
2. **As-of feasibility:** verify that each signal input can exist by 08:00.
   [Alpaca warns that corporate-action availability may be delayed][actions].
   Fetch time is not original known-at time. A final revised archive cannot prove
   historical executability. The French research-factor library is not a silent
   substitute: its [RF definition][rf] identifies a research series with source
   changes, not a verified first-session publication SLA. Missing evidence means
   refusal or a separately approved exploratory assumption, not invented timing.
3. **One registered analysis design:** obtain explicit approval for the dated
   input window, estimand, meaningful effect, dependence/uncertainty procedure,
   exposure record, budget and all-distinct-attempt treatment. Preserve existing
   Factory history, protected splits and single-writer discipline. A new portfolio
   protocol needs its own reviewed approval; this is not permission to modify
   the frozen intraday protocol or run a scratch-ledger workaround.
4. **Implementation scope justified by that decision:** the intraday Factory
   judges per-trade R against random entries, not funded monthly portfolio
   returns. Its current runner cannot perform this case unchanged. Only after
   data/design acceptance should a bounded accounting/evaluation extension be
   proposed through the official controlled workflow. Fixture correctness alone
   does not close that gap. No evaluator implementation is authorized here.

For a separately approved exploratory exercise, report one result for the whole
fixed roster and window, with its mandated cost stress and all missingness. A
nonpositive primary estimate is a practical reason to stop this case, not a
statistical proof of no effect. A positive estimate below the proposed useful
effect, uncertainty spanning zero, failed cost stress or inadequate precision
is insufficient to advance. Even an estimate above the useful effect with a
properly adjusted lower bound above zero remains **promising exploration** in
this survivor-selected/revised history, not validated live edge. Do not tune,
drop a sleeve, change cash yield or choose a favorable era to rescue it.

If any prerequisite fails, record the specific failure and **park the case**.
An inconclusive answer is an allowed terminal outcome; it does not automatically
authorize a longer sample, another strategy, an options variant or another tool.

## Next milestone and the path to actual use

The next independently testable milestone is an owner decision on this research
case and whether a bounded exploration is worth the effort despite its limits.
If accepted, first return a **no-return pass/fail manifest** using existing data
and metadata facilities, with a named, accessible cash archive and explicit
historical-knowledge limitations. Keep that task bounded to the four instruments
and proposed pre-confirmation interval. Do not build a new universe selector or
paper executor to avoid making the decision. A manifest pass still does not
authorize evaluation; the reviewed design and official intake must exist first.

For prospective paper work, require frozen input receipts, decision-time intents,
contemporaneous eligible bid/ask and sizes, partial/unfilled/rejected outcomes,
actual fees, settled cash and end-to-end reconciliation. Reuse the disabled
Factory paper adapter's observation/receipt boundaries where compatible; its
synthetic single-ticker examples are not a monthly multi-asset account engine.
Compare paper outcomes to separately recorded actual user fills without feeding
those discrepancies back into signal optimization. A short trial tests operation
and cost assumptions; it cannot validate the economic hypothesis.

Options stay deferred. Contract selection, expiry, rolling, bid/ask history,
liquidity, exercise/assignment, premium-at-risk and portfolio exposure would all
change the experiment. An ETF-share result cannot be relabeled an options result.
Personal capital, tolerated drawdown and concentration limits must be approved
before prospective trading; a monthly exit offers no maximum-loss guarantee.

This session changed documentation only. No price archive or Factory outcome
file was analyzed; external paper/documentation pages were consulted, with no
factor-series download or candidate-return calculation. The ledger and all four
existing budget files matched their prior hashes, and no budget file was added.
Both launchd jobs were confirmed unloaded. No production/database/app changes,
broker orders, schedule changes, live activation or evaluation occurred.

## Subsequent proposal for review

The [ETF/BIL exploratory amendment](etf-bil-exploratory-screen-proposal-2026-10-26.md)
documents an accessible alternative asset and simpler modeled execution. It is
an explicit revision to this untested case, not an evaluated result, adopted
protocol or permission to run. This earlier proposal remains as design history.

[tsmom]: https://www.aqr.com/Insights/Datasets/Time-Series-Momentum-Factors-Monthly
[everywhere]: https://images.aqr.com/-/media/AQR/Documents/Insights/Journal-Article/AQR-Trends-Everywhere_JOIM.pdf
[cash-index]: https://www.spglobal.com/spdji/en/indices/fixed-income/sp-us-treasury-bill-0-3-month-index/
[coverage]: https://docs.alpaca.markets/us/docs/about-market-data-api
[actions]: https://docs.alpaca.markets/us/reference/corporateactions-1
[rf]: https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/f-f_factors.html
