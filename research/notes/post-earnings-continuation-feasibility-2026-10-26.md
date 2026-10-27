# Post-earnings continuation: feasibility and go/no-go decision

October 26, 2026, America/New_York. Read-only research; documentation only.

## Decision

**NO-GO for a Factory attempt, a strategy adapter, or paid historical acquisition
on the present evidence. Park the generic liquid-stock earnings-drift idea.**

The fuller review weakens the earlier recommendation to investigate this path.
Published work supports an information-diffusion mechanism, but the evidence for
an executable, delayed-entry strategy in liquid US stocks is disputed. Our
existing earnings feeds also cannot reconstruct the information available at a
historical entry. Neither issue is solved by adding another signal family.

This is a feasibility decision, not a measured failure of a local PEAD strategy
or proof that every earnings-based strategy is unprofitable. No executable
candidate, threshold, holding period or new statistical gate is adopted here.
The failed ORB and ETF candidates remain closed; neither was tuned or rerun.

| Evidence class | What this review establishes |
|---|---|
| Historical external evidence | Mechanism evidence, conflicting persistence findings and material cost concerns; sources below. |
| Exploratory local findings | Source-code inspection finds missing historical event information and a mismatch with the current comparator. No local returns were computed. |
| Validated results | None for post-earnings continuation. |
| Forward hypothesis | A fully specified delayed-entry rule might add net return; its eligibility and profitability remain unestablished. |

## What the primary evidence says

Publication dates and sample dates are different. These findings are the
authors' results, not Factory results or independent replications performed here.

| Primary source | Evidence read | Implication for this proposal |
|---|---|---|
| Luo, Ravina, Sammon and Viceira, Chicago Fed working paper (2023) | Abstract and data section: brokerage observations cover 2010 Q1–2014 Q2. Retail contrarian trading around earnings is associated with PEAD; the reported relation depends on retail trading intensity. [Paper][retail] | Supports a possible mechanism. It does not establish present-day net profitability for a simple positive-surprise rule, and the proprietary flow data cannot be assumed available to us. |
| Chordia and coauthors, *Liquidity and the Post-Earnings-Announcement Drift* (2009) | Author-hosted abstract reports 0.04% monthly gross long-short return in the most liquid stocks versus 2.43% in the most illiquid, with estimated costs absorbing 70–100% of the strategy's paper profits. [Author summary][liquidity] | Historic drift and retail-accessible net return are different claims. These are old estimates, not our current spread assumptions. |
| Martineau, *Rest in Peace Post-Earnings Announcement Drift* (published 2022) | Author abstract reports disappearance for large stocks since 2006. Full publisher text was not accessible in this review. [Author abstract][martineau] | Direct contrary evidence to a generic liquid-stock rule. Do not treat this conclusion alone as proof that every implementation fails. |
| Hirshleifer, Peng and Wang, *News Diffusion in Social Networks and Stock Market Reactions*, RFS (2025) | Published paper, data section p. 891: 238,195 firm-quarter observations, 1996–2017. Social connectedness is associated with stronger immediate response and weaker subsequent drift. [Paper][social] | Positive mechanism evidence from a different author group, but the sample includes microcaps and the study does not establish our proposed long-only, delayed-entry, costed portfolio. Publication in 2025 is not a post-2025 trading test. |
| Subrahmanyam, *Keeping It Simple* (2026) | Section 2/Table 1 reconstructs an earnings-announcement-return factor for February 2001–December 2024. Its reported t falls from 2.18 including microcaps to 1.43 excluding them. [Paper][simple] | A recent challenge to apparent persistence. It studies a price-reaction-based long-short factor, not exactly an analyst-EPS-surprise long-only rule. Its statistics cannot be substituted for our gates; an insignificant estimate does not establish zero effect. |

**Synthesis:** this bounded review did not establish independent, recent,
after-cost evidence for the proposed liquid-US-stock implementation at an entry
available to this user. That is a search result, not a claim that no such study
exists. The opposing studies use different signals, populations and estimators;
counting favorable papers would not resolve the differences. No public factor
series, replication code or paper trade file was downloaded or evaluated.

## The proposed question is not yet an executable strategy

The question is whether a positive, genuinely known earnings surprise predicts
incremental net return after an achievable delayed entry, with shares held for
days or weeks. An EPS beat, an earnings-day price jump and management guidance
are different signals. Switching between them because a data field is missing
would change the hypothesis.

Before any evaluation could become eligible, one specification would need:

- A dated stock-eligibility rule including exits from the universe; a consistent
  EPS basis, currency and fiscal period; an estimate snapshot from before the
  release; the first usable actual value and its availability time.
- One selection rule and normalization, fixed without local returns. Dividing by
  a near-zero estimate can make surprise percentages extreme; vendor surprise
  fields are not automatically comparable to a paper's standardized surprise.
- One observation cutoff, practical processing delay, eligible execution session
  and quote/fill convention. No credit for a gap that occurred before entry.
- One holding/exit policy, treatment of new announcements, halts and delistings,
  and funded-account position, sector, cash and aggregate exposure limits.
  Stops cannot guarantee a maximum loss across an earnings gap.

These choices are deliberately unresolved, rather than filled with arbitrary
numbers to make a runnable candidate. No parameter grid, favorable subgroup,
social-network filter or microcap exception is selected.

## Existing data: concrete reasons it is not accepted

This inspection read source code, not earnings caches, production records or
market-price payloads.

| Existing component | Finding | Consequence |
|---|---|---|
| [Tradier events integration](../../backend/app/engine/symbol_info_tradier.py), `TIME_NOTE`; [normalizer](../../backend/app/engine/symbol_info_events.py), `parse_earnings` | Retained calendar rows have dates, quarter and status; release time is unavailable. | Cannot decide reliably whether information preceded an open, arrived intraday or followed the close. |
| [Analyst integration](../../backend/app/engine/symbol_info_analysts.py), `normalize_webull_eps` | Keeps the latest four reported quarters with actual/estimate/beat fields; no pre-release estimate-vintage timestamp in these rows. Yahoo is a separately labeled fallback, not historical-vintage proof. | Today's displayed estimate cannot be assumed to be the consensus known before an old announcement. A cache retrieval timestamp does not repair this. |
| [Historical reaction display](../../backend/app/engine/symbol_info_reactions.py), `calculate` | Examines the report-date session and next session and chooses the larger absolute completed daily move. | Appropriate only as its labeled retrospective inference. Using that choice as an entry-time event timestamp would introduce future information. |
| Factory bars and existing ETF bundle | Price history is not an earnings-information archive; the five ETF inputs are not a stock earnings universe. | No joined event roster, point-in-time surprise coverage or quote completeness is established. |

### Sources exist in principle; procurement has not passed

Public documentation checked October 26; no credential, account, subscription,
market-data API or sales contact was used.

| Source | Documented availability | Remaining acceptance / cost issue |
|---|---|---|
| [LSEG I/B/E/S Point-in-Time][ibes], brochure p. 7 | Daily historical snapshots with dates/timestamps, delivered weekly; US history advertised as far back as 1976 for 30 measures. This is distinct from its current/historical products. | Exact estimate/actual vintages, availability semantics, security mapping, coverage and retention rights need verification. No account entitlement or price quote established; no defensible all-in acquisition estimate. |
| [Massive/Benzinga earnings][earnings] | Posted individual price $99/month; advertised history from April 30, 2010. Fields include estimate, actual, EPS method, event date/time and `last_updated`. | The documentation inspected does not establish retrieval of every historical pre-release version. `last_updated` is not proof of the original known-at time. Scheduled/reported time semantics and timezone handling need acceptance. Price is not a purchase recommendation. |
| [Massive stock quotes][quotes] | Posted Stocks Advanced price $199/month; quote history advertised from September 10, 2003, with bid/ask, sizes and timestamps. | Coverage and license unverified. A displayed quote does not prove queue access or a fill. The two posted subscriptions sum to $298/month, not a complete PIT-data solution or all-in project quote. |
| [Massive dated ticker reference][tickers] | Dated queries and inactive/delisted securities are documented. | Need tested dated identity joins, ticker reuse/share-class handling, corporate actions and delisting proceeds. Current survivors alone cannot define the historical universe. |
| [SEC filings][sec] | Original disclosure documents can support provenance. SEC guidance distinguishes a press release from a subsequently furnished filing. | Filing acceptance, first public release and conference-call time are not interchangeable. SEC filings alone do not provide historical analyst consensus; no filing sample was acquired. |

The timestamp problem is not a demand for impossible perfect data. A documented
conservative delay and reliable as-of snapshot could support a deliberately
delayed strategy. It would have to demonstrate that useful return remains after
that delay, rather than assume access to the initial jump.

**Invented acceptance example, no prices or P&L:** an estimate version is available
at 15:00; the issuer releases results at 16:05; the vendor makes the actual value
available at 16:07; a correction arrives the next morning. A proposed 16:06 signal
cannot use the 16:07 value. A later eligible intent retains the version it used;
the correction cannot rewrite it. An unavailable execution quote leaves a
rejected/unfilled intent, not a midpoint fill or a deleted observation.

## Factory eligibility, comparator and statistical power

The authoritative checkout remains `/Users/user/TradeJournal-factory` on
`factory/ledger`, at `a954218f0e5c968c013d983064da79271cf68e03`.
Structural-only inspection found **84 distinct attempted IDs**:
8 unstructured, 23 recovery swing, 13 VWAP reclaim, 12 failed breakout,
15 ORB, 12 S1 research and 1 ETF exploratory. No earnings family or event-named
top-level spec key was found. This is **not exhaustive equivalence clearance**:
unstructured history was not opened for outcomes, and there is no exact proposed
spec to compare yet. A new name cannot establish novelty or reset the count.

Relevant source: [rules](../../backend/app/engine/factory_rules.py),
[features](../../backend/app/engine/factory_data.py),
[gates](../../backend/app/engine/factory_gates.py) and the
[research workflow on the audited research commit](https://github.com/imizik/TradeJournal/blob/a954218f0e5c968c013d983064da79271cf68e03/research/CONTINUOUS_SEARCH.md).

- `Family.on_bar`/`FeatureContext` provide price-series inputs, not an as-of
  earnings-event/estimate interface. Multi-session holding exists, but that does
  not supply missing event semantics or funded-portfolio accounting.
- `_random_entries`/`summarize` compare stop-normalized trade returns with a
  ticker/period/side matched entry average. This could test a specified timing
  rule; it is not an earnings-event-matched control or proof of incremental
  funded-account return. Same-event risk, market/sector exposures and overlapping
  positions would need a prespecified comparison. No comparator is replaced here.
- Default slippage is `max($0.01, price * 0.0001)` per applicable fill, not an
  observed earnings spread. The existing triple-cost check remains intact;
  calling it realistic earnings execution without evidence would be unjustified.
- Discovery spans July 2023–September 2024 and requires 100 trades. As planning
  arithmetic only, 18 names over about five quarterly reporting cycles yield
  about 90 events before positive-surprise, liquidity and missing-data filters.
  This is neither an observed count nor a hard upper bound; timing varies and
  coverage can reduce it. Repeated entries around one event do not create
  independent earnings observations.
- Confirmation requires at least 30 trades in each half, positive net return and
  excess over the existing comparator in each, plus the other unchanged gates.
  Counts alone would not establish power: earnings cluster by season/sector, and
  multi-week holds overlap across entry weeks. Adequate effective sample size
  and uncertainty have not been demonstrated. No local returns were inspected
  to estimate them.

**There is no eligible evaluation under the current inputs and implementation.**
Broadening the universe, adding an event comparator or introducing a portfolio
design is a separately reviewed research change, not permission to modify frozen
gates or expose protected dates. The manual ETF intake admits only its fixed case;
it is not a general bypass for this proposal.

## Costs, options and eventual paper use

Any eventual executable case must include spread, slippage, fees, missed orders,
available cash, share rounding, distributions and terminal liquidation. A
long-short paper's spread cannot be credited to a long-only account, and adding
shorts would introduce borrow availability/cost and separate authorization.
Stock execution should be established before options: earnings surprises alone
do not specify expiry, strike, premium risk or an executable contract. Historical
and prospective timestamped chains, bid/ask and sizes, selection/rejection rules
and actual-fill reconciliation remain unverified. No options archive was read.

The existing disabled paper adapter could eventually reuse closed-bar decision
and receipt concepts, but a new historical event signal must carry the same
availability semantics into prospective replay. Paper receipts would test
operation and fill assumptions, not retrospectively validate the economic edge.
No recorder, paper runner, alert, broker or live execution was activated.

## Stop conditions and the next independently testable milestone

**Do not build or buy for PEAD now.** Reopen only if evidence supplies all of:

1. A specified liquid-stock implementation with credible independent evidence
   in a recent sample after a realistic information/execution delay and costs;
   distinguish a positive long leg from a long-short factor and show the relevant
   comparator. A result confined to microcaps or instantaneous repricing does
   not meet the present objective.
2. Documented availability and affordable, approved access to historical
   pre-release estimates, original actuals, timestamps and security identities.
   Revised current history cannot silently substitute for unavailable vintages.
3. A complete, outcome-blind specification, equivalence review and statistical
   design compatible with official attempt accounting and protected data access.

If the owner elects to pursue this despite the no-go, the smallest next milestone
is a **documentation/sample-acceptance decision**, not a signal engine: verify
the required historical versions and timestamp semantics for one source, with
no prices or outcomes. A paid sample, acquisition or vendor contact requires its
own authorization. Do not start a recurring collector while historical readiness
is unresolved. If the requisite evidence/data cannot be established, retain this
no-go and move on without another adapter or speculative backtest.

## Audit and limits

Read: public research/provider documentation, local source/spec structure and
scheduler/Git metadata. No backtest, evaluator, candidate reservation, protected
outcome, production database, credential, provider data call or external message.
No new local performance result is claimed. This is a bounded review, not an
exhaustive systematic literature review or a provider acceptance test.

Before/after checks preserved the ledger SHA-256
`e7f5bda38f29993e6bd6c30903bf5d750ba850a45c503f03e647bb43558bb637`,
all existing search-budget receipts, `factory_gates.py` and `factory_rules.py`.
Both `com.tradejournal.factory-search` and `com.tradejournal.strategy-factory`
were absent from the user launchd domain. The attempted-ID count stayed **84**.
Only this memo changes; the research checkout stays untouched and live execution
remains off. Verification covers source/citation review, local link resolution,
diff whitespace and state comparisons; none is evidence of strategy performance.

[retail]: https://doi.org/10.21033/wp-2023-34
[liquidity]: https://business.columbia.edu/faculty/research/liquidity-and-post-earnings-announcement-drift
[martineau]: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3111607
[social]: https://bus.hkbu.edu.hk/content/dam/bus-assets/bite-sized-insights/qiguangwang-20230331.pdf
[simple]: https://sciencepg.com/article/10.11648/j.jim.20261501.11
[ibes]: https://www.lseg.com/content/dam/data-analytics/en_us/documents/brochures/lseg-data-for-quant-research-brochure.pdf
[earnings]: https://massive.com/docs/rest/partners/benzinga/earnings
[quotes]: https://massive.com/docs/rest/stocks/trades-quotes/quotes
[tickers]: https://massive.com/docs/rest/stocks/tickers/all-tickers
[sec]: https://www.sec.gov/rules-regulations/staff-guidance/corporation-finance-interpretations-cfis/exchange-act-form-8-k
