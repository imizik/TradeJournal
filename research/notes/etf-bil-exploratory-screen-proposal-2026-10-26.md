# ETF/BIL: one bounded exploratory screen, proposed before outcomes

October 26, 2026. The owner accepted preparing the simpler ETF/BIL direction
and explicitly approved three read-only BIL requests using the documented
Alpaca credential source. **No evaluation, attempt or live execution is approved
by this document or its merge.** This is a reviewable amendment and run contract;
it does not modify the frozen Factory protocol or register a candidate.

## What changed, and why

The [earlier proposal](etf-trend-experiment-decision-2026-10-26.md) required an
unverified proprietary cash archive, original 08:00 publication evidence and
09:35 minute observations before an economic screen. Those requirements combined
exploration with execution proof too early. The [bounded audit in PR #515](https://github.com/imizik/TradeJournal/pull/515)
found daily date coverage, not a profitable or unprofitable strategy.

This proposal replaces the signal cash reference with BIL and invests inactive
sleeves in BIL, uses next-session daily-close proxies, and models fractional
total-return units instead of a cash/share settlement ledger. These are visible
changes to an **untested proposal**, made for accessible inputs and a smaller
economic question. They are not equivalent to the original case and must never
inherit its identity or become a free rerun after results. The failed ORB stays
closed. No lookback, sleeve or execution-time variants are proposed.

Keep the primary question: **does timing add net return over the same passive
four-ETF portfolio?** Drawdown, volatility and cash-alternative exposure are
secondary descriptions. A risk-reduction objective would require an explicit
change before outcomes, not promotion of the most favorable result afterward.

## Access result: a concrete blocker resolved

The connected BIL daily-bar request timed out once. No connector retry was made.
Following the owner's explicit approval, the prepared standalone probe read only
the two Alpaca key entries from the documented factory environment link. It made
exactly three fixed GET requests to the market-data host, with no application,
database, account, order or Factory imports/endpoints. It disabled redirects and
environment proxies and bounded response size/time. No credentials were printed
or copied to this repository. No further credentialed requests are authorized by
the three-request approval.

| Request | Observed result |
|---|---|
| BIL SIP daily, raw, January 2016–September 2024 | HTTP 200; terminal page; 2,200 distinct dates; zero basic-invalid records |
| Same request, adjustment=all | HTTP 200; terminal page; same 2,200 dates; zero basic-invalid records |
| BIL actions, processing dates October 1–November 15, 2023, data_quality=all | HTTP 200; terminal page; two cash-dividend records |

The two action records identify BIL CUSIP 78468R663, with ex-dates October 2 and
November 1, and payable/processing dates October 6 and November 7, 2023. They
establish a successful spot check, not complete action history or historical
known-at timestamps. The date-list hash matches the previously observed 2,200
dates for SPY/EFA/EEM/IEF. [State Street][bil] describes BIL's 1–3-month Treasury
bill exposure, inception on May 25, 2007 and monthly distributions.

The [access receipt](etf-bil-access-receipt-2026-10-26.json) records request/response
times and response-body SHA-256 values. Saved responses are read-only local
temporary files, not a durable five-fund research dataset. Only metadata is
committed. Prices were checked for basic consistency; no signal, strategy return
or historical total-return index was computed.

The practical conclusion is **direct data access works for the approved probe**.
It is not established for every future request. Full action coverage, all five
input versions and a counted portfolio-evaluation path remain prerequisites.

## Proposed fixed economic case

| Component | One choice for review |
|---|---|
| Risk sleeves | SPY, EFA, EEM, IEF, each targeting 25% when active; no replacements |
| Alternative asset | BIL is both the signal comparator and the asset held for inactive sleeves; it is a traded ETF, not a risk-free broker cash balance |
| Signal | At completed month-end m, compare each sleeve's 12-month reinvested total-return growth with BIL's over the same endpoints. Strictly greater selects the risk ETF; equality or less selects BIL. Require 13 month-end observations. |
| Portfolio weights | Risk ETF i gets 0.25 or zero; BIL gets one minus the sum of the four risk weights. Long only, no leverage, no redistribution among active risk ETFs. Weights drift between monthly rebalances. |
| Timing | Form targets after the completed month-end. Apply them **after marking existing positions at the first following session's provider daily close**, charging trading costs then. New positions earn subsequent returns. This is a delayed daily-bar approximation, not an achievable closing-auction fill claim. |
| Management | Monthly recomputation only; no intramonth stop, target, filter or optimized timing. No options. |
| Modeled holdings | Fractional total-return units; normalized starting NAV 1. Ex-date reinvestment is an idealized economic convention. No claim about share rounding, dividend-payment financing, settlement or broker buying power. |
| Costs | 10 bp of absolute bought/sold notional at each rebalance; mandatory 30 bp stress of the same case. Include BIL transactions. Embedded ETF expenses stay inside observed fund prices and are not deducted twice. Taxes are outside this screen. |
| Primary comparator | Always target 25% in each risk ETF, zero BIL; same dates, total-return convention, fractional approximation, cost model and initial/terminal treatment. |
| Descriptive reference | Always BIL, under the same conventions. It cannot replace the primary passive comparator when outcomes disappoint. |
| Candidate history | One prospective identity for this revised case, after duplicate/equivalence review and explicit approval. Preserve all prior attempts and disclosures; no separate scratch ledger or counter reset. |

Define daily total-return growth from raw daily closes and normalized actions:
g_i,t = s_i,t (P_i,t + D_i,t) / P_i,t−1, where s is post-event shares per prior
share and D is the distribution entitlement per post-event share. Reinvestment
is at the ex-date closing proxy. Multiple/same-date events require an unambiguous
share-unit convention; unsupported corporate actions refuse the run. An adjusted
bar label alone does not prove this convention. [Alpaca][bars] offers separate
raw/split/dividend/all settings; the BIL adjusted response is access evidence,
not automatic certification of a reinvested total-return series.

Hold constant units between decisions, including the first session of each
month. At a rebalance, let H_i be each marked pre-trade holding value and V− the
total NAV. With target weights w_i and cost rate c, solve the self-financing
identity V+ = V− − c sum_i |w_i V+ − H_i|, then hold value w_i V+ in each asset.
This charges actual modeled turnover and funds costs before investment. It does
not invest 100% of pre-cost NAV and borrow the fees. Initial cash has no asset
holdings, so V+ = V−/(1+c). A full switch between two assets gives
V+ = V−(1−c)/(1+c). These are mathematical identities, not market results.

The proposed price window is January 1, 2016–September 30, 2024, with January
2016–January 2017 month-ends supplying initial warm-up. Start with NAV 1 on
January 31, 2017, uninvested until the first allocation after the February 1
close. End after the September 30, 2024 mark and a modeled full liquidation
charging c times remaining asset value. Do not use an October price. Apply the
same startup/termination convention to all lanes. This gives 92 calendar-month
portfolio observations, not 92 independent samples. Earlier pre-discovery prices
are proposed exploration inputs; using them is not an authorized Factory run.

## What exploration may assume, and what it still must prove

The proposed screen may use a fixed, revised historical archive with unknown
original publication times, this explicit next-session-close approximation and
fractional total-return units. Report those assumptions prominently. This
history is also selected from today's surviving funds. It cannot establish an
untouched validation result or historical executability.

It still needs all expected dates, consistent raw prices and actions, no
duplicate/conflicting unhandled events, source/version hashes and a reproducible
input bundle. Retain late-processed events with separate effective and process
dates; do not truncate effective distributions merely at a processing cutoff.
Missing marks or action fields needed by the formula refuse the run. Never
substitute price-only returns, zero distributions, IEX, a different fund or
another window after a data failure. Provider history and a bounded issuer-event
reconciliation support exploration; complete original publication receipts are
deferred to a stronger prospective/executable claim.

This is a proposed staged evidence standard for this new exploratory case. It
does not loosen the frozen Factory's existing statistical gates or authorize
protected-date inputs. The prior assumed-volatility power table limits what a
future positive result could establish; it is not a blanket prohibition on a
useful, explicitly inconclusive exploration.

## One-run contract to approve after preparation

Before any strategy arithmetic, review and freeze the input bundle, canonical
case identity, code commit and this analysis contract. The existing Factory
runner handles per-trade R and cannot execute this monthly portfolio unchanged.
The smallest missing implementation would be a bounded portfolio child plus an
explicit intake through the **existing** writer lock, reservation, budget and
exposure accounting. It must produce an exploratory artifact only, never a
Factory confirmation/exam pass. No implementation or direct ledger write is
performed by this proposal.

Proposed bound: **one newly reserved candidate, one evaluation child, at most
15 minutes, no automatic retry, no hidden-stage data load**. Acquisition remains
a distinct read-only preflight; a future authorization must name its endpoints,
date ranges (including any later-processing metadata reconciliation) and caps.
The three BIL requests already approved do not authorize that larger acquisition.
Abort incomplete preparation before launching the evaluator. Once reserved,
interruptions/failures retain their charge under the existing budget rules.
Inspect fresh counts/hash/budget before reservation; do not assume attempt 84 or
reuse the earlier ORB authorization. No schedule is resumed.

Freeze one primary estimand: 12 times the mean paired monthly simple net return,
active minus passive. Report both NAV paths, monthly pairs, CAGRs, maximum
drawdowns, turnover, BIL exposure and both cost cases. The mean-difference units
are annualized arithmetic percentage points, not CAGR difference or alpha.
Use the full fixed window; no sleeve/era/filter selection or optimized rerun.

Proposed practical follow-up criterion: base-case primary increment at least
2 percentage points/year and a positive primary increment under the 30 bp cost
stress. This retains the earlier planning effect size; it is a research-spending
decision for owner approval, not a statistical validation gate or a promised
return. Failure means stop this case; a negative estimate alone does not prove
the true effect is nonpositive. Meeting it earns consideration of a separate
uncertainty/replication and execution study, with prior attempts retained. No
significance claim, independent-sample assumption, Bonferroni reset or trading
permission follows. All measured performance fields are currently unavailable.

Whole-share/settlement reconciliation, time-stamped live input availability,
quotes/fills, owner capital/loss limits and options remain later evidence tasks.
They should be built only if an authorized economic screen justifies the work.
This proposal and its access receipt complete preparation for review; they do
not claim that an eligible one-click evaluation exists today.

## Subsequent preparation implementation — October 26

After PR #516 merged, the owner approved continuing preparation. The
[pure portfolio calculator](../../backend/app/engine/etf_portfolio.py) now makes
the proposed arithmetic independently testable: fixed 12-month comparisons,
strict ties to BIL, delayed monthly rebalancing, funded turnover costs, initial
cash, final liquidation, paired monthly returns, NAV, CAGR and drawdown for all
three lanes at both cost levels. BIL weights and traded notional are recorded
along the daily paths. Its tests use **invented prices and an invented calendar
only**; their outputs are software checks, not strategy performance evidence.
Signal comparisons use exact rational ratios so an exact tie cannot become a
risk allocation through rounding; portfolio accounting uses Decimal arithmetic.

The calculator accepts already-normalized per-post-event-share distributions
and splits. It has no market loader, CLI, candidate reservation or broker path.
The caller must establish full calendar coverage, completed month boundaries,
identity and complete action normalization first. In particular, unhandled
capital distributions, conflicting corrections or ambiguous same-day units
cannot become zeros. A pure callable is not an authorization boundary: it must
not be invoked on market data outside a separately approved counted run.

The [input acquirer](../../backend/scripts/etf_input_acquire.py) defaults to
printing this fixed request plan, without reading keys or accessing the network:

| Request | Fixed scope | Page cap |
|---|---|---|
| `GET https://data.alpaca.markets/v2/stocks/bars` | SPY/EFA/EEM/IEF/BIL; raw SIP daily; January 1, 2016–September 30, 2024; USD; asof September 30, 2024; 10,000 records/page | 4 |
| `GET https://data.alpaca.markets/v1/corporate-actions` | Same five symbols; processing dates January 1, 2016–October 26, 2026; all action types; data_quality=all; 1,000 records/page | 8 |

The later action cutoff is solely for reconciling late-processed events whose
effective dates fall inside the proposed price interval. The source archive
retains responses, including out-of-window action records; future normalization
must exclude post-September-2024 effective events. No later prices are requested.
[Alpaca's action endpoint][actions] uses process dates and does not guarantee
original availability time. An empty or terminal response does not prove a
complete historical action ledger.

For a separately authorized acquisition, the tool selects only
`ALPACA_API_KEY` and `ALPACA_API_SECRET` from
`/Users/user/TradeJournal-factory/backend/.env`, the documented link to the main
checkout environment file. It does not load app settings or interpolate other
entries. The maximum is **12 GETs, no retries, 120 seconds per CLI invocation,
3 MB per response**, with redirects and environment proxies disabled. No account,
order, database or evaluation endpoints exist in the tool. It requires a new
absolute local directory, keeps partial archives on failure, refuses overwrite,
and records retrieval times and raw-body hashes without logging secrets.

Even successful acquisition is marked `acquired_unaccepted` and
`eligible_for_evaluation=false`. Daily dates must match the previously audited
2,200-session calendar hash for every fund; this is date coverage, not issuer
reconciliation. The request plan and refusal paths are covered by mock-transport
tests. The earlier three-request approval did not cover this expanded plan;
the owner separately approved this exact acquisition during implementation.

The approved acquisition completed once in **three GETs**: two bar pages and one
action page, all HTTP 200 with terminal pagination reached. All five funds have
2,200 dates matching the audited calendar, for 11,000 daily bars. The
[metadata-only receipt](etf-bil-input-archive-2026-10-26.json) records the exact
code version, request metadata, response hashes and local archive location.
Raw pages are retained in the ignored worktree data directory with read-only
permissions; they are not committed or guaranteed to survive worktree deletion.
Original source bytes must be retained before retiring this worktree.

| Symbol | In-window cash-dividend records | Those with blank CUSIP |
|---|---:|---:|
| SPY | 33 | 14 |
| EFA | 18 | 8 |
| EEM | 18 | 7 |
| IEF | 103 | 47 |
| BIL | 71 | 38 |

All nonempty dividend CUSIPs matched the expected current identifiers. There
were no repeated/conflicting in-window action IDs. These checks do not establish
historical identity or distribution completeness. For example, SPY has three
records in each of 2016 and 2018, and BIL has none in 2021; those counts require
issuer reconciliation, not a presumption of zero distributions or an automatic
decision that every apparent gap is missing data.

The BIL archive also contains a 1-for-2 reverse split effective November 30,
2017, with blank old/new CUSIPs. The ratio and date agree with the
[issuer's November 15, 2017 announcement, syndicated by Business Wire][bil-split].
A synthetic reverse-split regression checks that the calculator does not turn
the price discontinuity into a gain. This one-event check is not full archive
acceptance. Sixty-five action records have effective dates beyond the price
window and remain outside any future normalized evaluator input.

Remaining before any historical screen: reconcile and freeze the acquired
archive's action normalization/input receipt; then connect the
calculator to the **existing** Factory reservation, locks, budget and bounded
child, with an explicit one-run authorization. The current ORB-only intake and
all frozen gates remain unchanged. There is no enabled ETF evaluation command,
new ledger, schedule, live execution or consumed candidate attempt in this slice.

[bil]: https://www.ssga.com/us/en/intermediary/etfs/state-street-spdr-bloomberg-1-3-month-t-bill-etf-bil
[bars]: https://docs.alpaca.markets/us/reference/stockbars
[actions]: https://docs.alpaca.markets/us/reference/corporateactions-1
[bil-split]: https://www.streetinsider.com/Press%2BReleases/State%2BStreet%2BGlobal%2BAdvisors%2BAnnounces%2BETF%2BShare%2BSplits/13511071.html
