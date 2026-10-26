# ETF trend: data and accounting acceptance packet

October 25, 2026. Preparation only. The owner accepts multi-week holds and
requested this packet; no evaluation, attempt or activation is authorized.
This refines the [proposed design](strategy-research-path-2026-10-25.md), not the
Factory protocol. No market price payloads or protected outcomes were opened.

**October 26 decision update:** the [experiment decision packet](etf-trend-experiment-decision-2026-10-26.md)
supersedes the proposed oldest-eligible selection and unspecified cash reference
below. Its fixed roster and modeled-account assumptions are for review, not
adopted rules. The fixture milestone is complete; more infrastructure is parked.

## Acceptance decision

**GO for specification and synthetic accounting preparation; NO-GO for historical
evaluation or paper activation.** The packet's invented arithmetic reconciles.
Actual identity, corporate-action, quote, cash-series and as-of coverage have not
passed acceptance. Provider capabilities are documentation evidence, not account
entitlement or verified data delivery. There is no measured strategy performance.

Multi-week holding is accepted. Capital, personal drawdown tolerance and a final
universe are still not owner-approved. Proposed values below make review concrete;
they do not set the user's financial risk limits.

## Proposed research charter

Primary question: does one monthly 12-month total-return-versus-cash signal add
net account return over a passive portfolio with the same underlying sleeves?
This is incremental return, not automatically factor alpha. Risk, turnover,
drawdown, exposure and cash-relative return are secondary descriptions, never
alternative pass criteria selected after seeing results.

Propose four fixed 25% sleeves: broad US equities, broad developed ex-US equities,
broad emerging-market equities, and intermediate nominal US Treasury exposure.
This is an accessible adaptation, not the diversified long-short futures study.
Equity overlap and shared macro risks mean four sleeves are not four independent
experiments. Commodity, leveraged/inverse, synthetic leverage, single-sector,
active, currency-hedged, ETN and fund-of-funds implementations are excluded from
this proposed first design. These are scope choices, not optimized exclusions.

Proposed deterministic selection at a single future registration cutoff: among
US-listed, USD-traded, unleveraged passive ETFs in each specified category, select
the earliest-inception fund with at least 13 complete month-end observations and
verified identity/action/execution coverage; break equal inception dates by
stable fund/share-class identifier. Classification must be supported by dated
issuer mandate documents, including a declared intermediate Treasury maturity
range of 3–10 years; ambiguous coverage is a review failure, not discretion to
pick a better performer. Freeze the complete eligible/rejected roster and reasons
before any returns. No AUM, recent performance or optimized spread ranking.

**Important selection limit:** this selects a prospective universe. Using the
resulting surviving funds backward is exploratory survivor-selected history,
not an unbiased historical universe. A credible historical design needs dated
selection rosters and mandate/closure histories at its original cutoff. Do not
quietly use today's roster or change universes after returns. No actual ETF has
been selected in this packet; no provider reference payload was fetched.

Proposed accounting denomination is USD and invented starting capital is $10,000.
No leverage or shorting; whole shares only; fees must fit inside each sleeve's
budget. Unused sleeve cash stays in that sleeve. At monthly rebalance, target
each sleeve at 25% of pre-trade NAV, subject to settled buying power; positive
signals buy/retain the largest affordable whole-share position, nonpositive
signals target zero. Record rounding, costs and unfilled residuals. Do not scale
other sleeves up when one is inactive. Drift between monthly decisions is
reported, not automatically traded. No intramonth price stop or target is added.

Signal cutoff proposal: 08:00 America/New_York on the first regular session after
month-end, using only data effective by the completed month-end and demonstrably
available by cutoff. Record UTC and exchange session identifier. Execution
proposal: one intent per sleeve, eligible at 09:35 that session, expires at 09:40;
no late catch-up or optimization of these operational times. Execution requires
an explicit latency, quote-age, size and partial-fill specification before use;
these values have not been frozen. A quote is evidence, not a guaranteed fill.

Missing signal input means unavailable, not bearish: do not open/increase a
position, preserve existing holdings and flag the decision for review. Missing
execution quote means unfilled intent with cash/holdings unchanged. No automatic
replacement. A halt preserves the position and explicit valuation uncertainty;
closure/liquidation requires documented entitlement and proceeds. It cannot be
assigned a zero return or removed. These are proposed failure semantics, not a
live unattended policy.

## Coverage and identity manifest

All rows below are **UNVERIFIED for the proposed universe**. No market-data API
was called and no purchase was made. An empty coverage field must remain unknown,
not become zero missing observations. The existing stock minute-cache inventory
in the EOD memo does not establish any of these ETF requirements.

| Dataset | Documentation evidence | Acceptance evidence still required |
|---|---|---|
| Dated security roster | [Massive reference guidance][master] describes dated lists, delisted names and incomplete older fields; no universal permanent ID. | Dated eligible/rejected rosters, ETF share-class identity, renames, inception, closure and mandate versions. CIK alone cannot distinguish multiple funds/share classes. |
| Raw prices and signal adjustments | [Alpaca bars][bars] distinguishes raw, split, dividend and all adjustments. Its `asof` parameter maps symbols. | Complete session coverage, pagination, adjustment convention, version hashes and distribution reconciliation. Symbol `asof` is not a historical knowledge-time guarantee. |
| Distributions and splits | [Massive action documentation][actions] provides event fields and factors; aggregate `adjusted=true` supports split adjustment. | ETF event coverage, ex/pay dates, special distributions, capital gains, split factors, closures and revision history. Do not equate split adjustment with total return. |
| Execution observations | [Massive quotes][quotes] documents NBBO prices, sizes and exchange/SIP timestamps. | Account rights, exact period, eligibility conditions, missing-session audit and quote freshness. Top-of-book size is not guaranteed queue access or impact capacity. |
| Feed provenance | [Alpaca feed documentation][feeds] distinguishes single-exchange IEX from consolidated SIP. | Freeze one feed; no silent IEX substitution when SIP is unavailable. |
| Cash signal and account yield | No cash archive or broker credit policy verified here. | Fixed total-return cash benchmark plus publication lag, and separate actually achievable account cash yield, settlement and eligibility rules. A quoted annual yield is not a realized monthly return. |
| Licenses and retention | Public documentation only; no account inspected. | Entitlements for each endpoint/date, permitted storage/replay and retention, cost approval if needed. |

For each accepted instrument/dataset, the eventual manifest must record:
`stable_id`, dated symbol, category/evidence, effective interval, listing/closure,
requested interval, expected/received sessions, missing/duplicate sessions,
source/feed/endpoint, pagination completion, raw-object hash, retrieval time,
source publication time (or explicitly unavailable), adjustment version,
corporate-action joins, license evidence, acceptance status and rejection reason.
Coverage counts and dates may be audited without calculating strategy returns.
No data retrieval command is supplied here that could accidentally evaluate it.

If a vendor supplies only today's revised history, record `known_at=unknown`.
Do not substitute retrieval time for historical availability. Either a separately
reviewed delayed-information assumption is necessary for exploratory history,
or that history fails strict as-of acceptance. Prospective receipts can establish
availability going forward but do not repair historical knowledge gaps.

## Keep signal, portfolio and execution accounting separate

The signal uses a total-return growth factor including reinvestment under a
specified convention. The account holds raw shares, receives distributions as
cash/receivables and executes at raw prices. Never apply an adjusted price to
held shares and also credit the same dividend. Expense ratios already reflected
in observed fund prices must not be subtracted a second time.

Trade-date NAV = trade-date cash + raw marked holdings + distribution receivables
minus other liabilities. Settled buying power is a separate constraint: a sale's
unsettled proceeds are not immediately available buying power in this proposed
cash-account model. Settlement dates must follow the applicable calendar/rule;
no fixed delay is assumed for every historical period. Track unsettled purchases
and sales without subtracting the same obligation twice from NAV.

The passive comparator uses identical base sleeves, whole-share and fee handling,
monthly rebalancing, calendars, cash yield and mark conventions, but always targets
exposure in eligible sleeves. The all-cash reference uses the declared cash
benchmark. Missing evidence must be reported for each lane; never drop only the
active strategy's rejected trades or silently intersect on successful fills.

## Reconciled invented receipt

The companion [fixture](etf-trend-accounting-example-2026-10-25.json) contains no
real symbols, prices or outcomes. Logical event times are ordered; they are not
market timestamps. All fees are invented 10 bp of notional, rounded half-up to
cents per fill. A modeled fill is explicitly not a broker fill. No interest,
tax, external cash flow or other liability is assumed in this example.

At cutoff A and B have total-return indices 100→108 versus cash 1.04; C has
100→102, D has 100→104. Thus A/B are positive, C/D target cash (equality is cash).
Each sleeve budget is $2,500. B has no eligible quote and remains unfilled. A's
invented ask is $100: 24 shares plus $2.40 fee fit its sleeve; 25 plus fee do not.

| Event | Trade-date cash | A shares × raw mark | Distribution receivable | NAV |
|---|---:|---:|---:|---:|
| Initial | 10,000.00 | 0 | 0.00 | 10,000.00 |
| Buy A; B rejected | 7,597.60 | 24 × 100 | 0.00 | 9,997.60 |
| Ex-date: $2 distribution, mark falls $2 | 7,597.60 | 24 × 98 | 48.00 | 9,997.60 |
| Pay date: receivable becomes cash | 7,645.60 | 24 × 98 | 0.00 | 9,997.60 |
| 2-for-1 split | 7,645.60 | 48 × 49 | 0.00 | 9,997.60 |
| Later invented negative signal; sell at bid 49, fee 2.35 | 9,995.25 | 0 | 0.00 | 9,995.25 |

All earlier settlements are assumed completed before the sale. Immediately after
that sale, $2,349.65 of the displayed cash is unsettled proceeds, so settled cash
is $7,645.60. On settlement, cash total is unchanged, settled cash becomes
$9,995.25. This explicitly prevents both premature reuse and double deduction.
Ending equity differs from starting equity by exactly the two fees, $4.75.
The ex-date drop and split generate no artificial gain/loss. This is an accounting
identity, not strategy performance. A one-off Decimal check verified the table.

## Acceptance cases and refusal conditions

| Case | Required behavior | Evidence now |
|---|---|---|
| Positive/equal/negative signal | Strict growth-factor comparison; no equality trade | Invented inputs checked |
| Sleeve sizing | Whole shares plus rounded fee fit $2,500; next share fails | Invented arithmetic checked |
| Missing quote | Preserve B's intent and rejection, no fill or reallocation | Explicit fixture record; no production handler tested |
| Dividend | Ex-date receivable; pay date transfer; no double credit | Invented arithmetic checked |
| Split | Quantity doubles, raw mark halves, NAV unchanged | Invented arithmetic checked |
| Settlement | Sale raises trade-date cash; settled buying power waits | Invented arithmetic checked |
| Late correction | Append correction with known-at time; retain original intent/hash | Requirement only; implementation not tested |
| Closure/rename | Preserve identity and original eligibility; require entitlement/proceeds | Requirement only; real coverage unverified |
| Missing mark/halt | Surface valuation uncertainty; do not fabricate zero return | Requirement only; implementation not tested |
| Duplicate event/restart | Stable event ID must prevent duplicate cash/share posting | Requirement only; implementation not tested |

The committed fixture's SHA-256 is recorded in PR validation evidence. This is a
versioned illustrative receipt, not tamper-proof production persistence. No
application engine, real provider client or Factory evaluator was invoked.

## Statistical readiness and next bounded work

The proposed primary observation is the synchronized monthly funded-portfolio
return difference, not each ETF trade counted as an independent sample. Joint
calendar resampling would need to preserve cross-asset dependence; serial
correlation and overlapping signals require a reviewed block/horizon choice.
No resampling or returns were computed. A reviewer must set minimum meaningful
net effect, power/precision targets, multiplicity treatment and chronological
splits before evaluation. Owner capital and tolerable losses remain inputs, not
parameters to optimize. No new statistical threshold is adopted here.

The frozen Factory intraday gates are not authorized to judge this different
portfolio design by substituting a new benchmark or bypassing minimum counts.
All prior attempts remain accounted for. A distinct future protocol requires
explicit review and authorization; no attempt-counter reset is proposed. Protected
Factory outcomes stay closed even if the same dates occur in a vendor archive.

The next useful bounded engineering task is a **fixture-only cash/share event
reconciler** satisfying the cases above, with no data loader, strategy evaluator,
broker client or scheduler integration. The next data task is a separately scoped
reference/coverage acquisition after provider permissions and exact universe
selection are settled. Neither task constitutes permission to run a backtest.
The acceptance packet is complete as preparation; data/statistical acceptance and
strategy validation are not complete.

[master]: https://massive.com/knowledge-base/article/does-massive-have-a-downloadable-security-master
[bars]: https://docs.alpaca.markets/us/reference/stockbars
[actions]: https://massive.com/blog/new-splits-and-dividends-endpoints
[quotes]: https://massive.com/docs/rest/stocks/trades-quotes/quotes
[feeds]: https://docs.alpaca.markets/us/docs/historical-stock-data-1

## Follow-on fixture implementation

The [fixture-only reconciler](etf-fixture-reconciler-2026-10-25.md) now checks the
invented receipt independently, including duplicate/restart behavior. Its fixed
eight-stage scope is explicit; unsupported corrections, closures and halts are
refused. This closes the example-accounting milestone only. Real data acceptance,
portfolio implementation and authorization for evaluation remain outstanding.
