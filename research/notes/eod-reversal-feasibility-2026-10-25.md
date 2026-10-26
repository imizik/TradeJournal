# End-of-day reversal: feasibility and next-step decision

October 25, 2026, America/New_York. Research-only review; no strategy evaluation.

## Decision

**NO-GO for another Factory attempt or the proposed clock-entry implementation.
GO for a bounded data/execution feasibility specification.**

No tradable strategy is validated here. The proposed rule does not faithfully
test the cited effect, executable net returns are unestablished, and adequate
statistical power has not been demonstrated. Searching more thresholds would
not resolve those issues. The failed frozen ORB proxy remains closed: no variant,
favorable subgroup, revised stop or replacement filter was selected.

## Evidence and boundaries

| Category | Status |
|---|---|
| Historical evidence | Primary studies below report historical effects, not Factory passes or current execution proof. |
| Exploratory findings | Source inspection identifies hypothesis/baseline mismatches; filename inventory establishes presence only. |
| Validated results | None for end-of-day reversal. No returns, candidate trades or protected outcomes were inspected. |
| Forward hypotheses | Faithful selection might survive realistic costs; profitability and detectability remain unestablished. |

Read: public papers, existing evidence/readiness notes, Factory source, discovery
cache filenames and repository/scheduler metadata. The authoritative research
checkout was `9a175be5aa71f3da3c4ae403d095f0752ad898a6`. Ledger/budget files were
hashed for change detection, not inspected for outcomes. The prior count of 83
comes from the already-authorized inspection reported in this chat. No backtest,
evaluator, provider market-data request, purchase, gate edit, schedule activation,
broker action or production write was performed. No new candidate was registered.

## Primary-paper check

Baltussen, Da and Soebhag's April 2025 working paper uses 1993–2019 US stock data.
Its principal sorts rank previous-close-to-15:00 returns cross-sectionally, then
hold portfolios during 15:30–16:00. The largest size quintile has a reported
six-factor long-short alpha of 3.41 bp/day; that is not an executable long-only
return. The authors warn that rebalancing costs may prevent exploitation. They
also test midpoint returns and exclusion of the final five minutes. See Sections
3.2–3.4, printed pages 11–15, and Table 3 of the [primary paper][eod].

The bounded search found versions and descriptions of the same work, not a
verified independent post-2019 replication demonstrating retail net profitability.
That is a search limitation, not proof none exists. Publication date is not the
end date of the evidence.

## Proposed rule versus the experiment it would actually test

These are source-based conclusions, not measured returns:

| Proposed shortcut | Unresolved issue |
|---|---|
| `day_move <= -1.0` on core names | `FeatureContext.at` measures session-open-to-signal change in daily ATR. It supplies neither a cross-sectional rank nor the paper's return definition. |
| Add a clock-entry family and call it replication | Each `Family` receives one ticker's Series, without a point-in-time all-stock ranking interface. A per-ticker threshold is a different hypothesis. |
| Use the current random baseline as the paper's comparator | `_random_entries` and `summarize` match ticker, period and side and use a period-average random-entry return. They do not construct a same-day ranked portfolio/comparator. A pass could support conditional timing, not automatically the published portfolio effect. |
| Use `AtrStop(1)` for a daily-ATR stop on five-minute bars | `baseline_signals` computes ATR from the supplied intraday Series. A daily-ATR family needs explicitly matched risk units, not silent reuse of that class. |
| Treat `[1530,1544]` as identical fill timing | Windows constrain signal bar-close time; `run_candidate` fills at the next bar open. The rotating baseline can select different closes in that window. Freeze information cutoff, observation time and execution convention first. |
| Assume the last OHLC close is an executable fill | Closing-auction deadlines, late signals, early closes and unfilled orders need a feasible convention. A close price alone proves none of these. |

Code anchors: `backend/app/engine/factory_data.py` (`FeatureContext.at`),
`backend/app/engine/factory_rules.py` (`Costs`, `AtrStop`, `baseline_signals`,
`run_candidate`) and `backend/app/engine/factory_gates.py` (`_random_entries`,
`summarize`, `confirm_gate`). No code or gates changed.

These are not instructions to repair the frozen protocol in place. Any new
portfolio interface, baseline or cost convention requires a separately reviewed
design before outcomes are examined. All prior research must remain accounted
for; a new name or protocol cannot reset the attempt history.

## Data and execution costs

A filename-only inventory of the official SIP minute cache found 314 date-named
files within July 3, 2023–September 30, 2024 for each of the 17 covered core stocks
and SPY; NBIS had zero. No payload was opened. File counts do not prove session
completeness, usable closing observations, corporate-action accuracy,
point-in-time membership or executable quotes. Confirmation/exam payloads remain
untouched. The journal-selected universe is not a broad survivorship-controlled
universe.

Factory charges `max($0.01, price * 0.0001)` per fill. Holding illustrative entry
and exit prices constant gives this arithmetic, not a backtest or spread estimate:

| Stock price | Default round-trip modeled cost | Triple-cost stress |
|---|---:|---:|
| $50 | 4 bp | 12 bp |
| $100 | 2 bp | 6 bp |
| $200 | 2 bp | 6 bp |

This does not establish commissions, impact, queue position, short availability or
auction access. Do not subtract these figures mechanically from a published
long-short factor alpha: notional, turnover, benchmark and return units must
agree first. A small statistical effect does not itself provide execution margin.

If this path becomes eligible, validate stock execution first. Options introduce
contract selection, bid/ask, expiry, volatility and fill uncertainty. Journal
option fills and current chains cannot reconstruct an unbiased historical
opportunity set. No option entitlement or archive completeness was verified.
Options are not a way to rescue an unvalidated underlying rule.

## Power: analytic illustration, not empirical evidence

For a possible candidate at K=84, the unchanged formula is
`NormalDist().inv_cdf(1 - 0.05/84) = 3.24115`. Discovery still requires t>=2,
positive after-cost mean and 100 trades. Confirmation still requires both halves
positive and better than random, minimum counts, triple-cost profitability,
ticker breadth and positive results without the best ticker.

Under independent, equally weighted weekly excess returns,
`t ≈ weekly mean / weekly SD * sqrt(weeks)`. For approximate one-sided 80% power,
add `Phi^-1(0.8)=0.84162` to the critical value:

| Illustrative stage | Approximate weeks | Weekly mean/SD at threshold | Weekly mean/SD for 80% power |
|---|---:|---:|---:|
| Discovery | 65 | 0.248 | 0.352 |
| Confirmation | 78 | 0.367 | 0.462 |

At the confirmation threshold, assumed weekly ratios 0.10, 0.20 and 0.30 require
approximately 1,667, 417 and 186 independent weeks for 80% power. Calculations use
constants only, with no market observations or simulated trades.

Actual Factory statistics cluster uneven trade counts and use an estimated
per-ticker baseline. These approximations are not calibrated power estimates;
serial dependence and joint gates can require more evidence. Portfolio Sharpe,
panel-regression t and Factory excess-R t are not interchangeable. The older
note's claim that a published Sharpe near one is simply "not detectable" was too
categorical: low power is not zero power, and the estimators/units differ. Do not
translate a headline Sharpe into eligibility or lower a gate to make it fit.

## Bounded follow-up after the no-go

Two alternatives were checked without computing local performance:

| Path | Primary evidence and limitation | Decision |
|---|---|---|
| Broad-universe stocks-in-play ORB | The paper studies over 7,000 stocks during 2016–2023 and ranks a top-20 opportunity set. Its described cost assumption is $0.0035/share commission; the retrieved text supplied no explicit spread/slippage model. [Sections 3–4][orb]. | Defer. Point-in-time universe, delistings and realistic execution require separate preparation. This is not a rescue variant of the failed proxy; no rule changes were selected. |
| Diversified longer-horizon trend following | Hurst, Ooi and Pedersen study 67 markets during 1880–2016 with modeled fees/costs. They acknowledge cost uncertainty and omitted futures-roll costs. [Pages 1–2 and Appendix B][trend]. | Worth separate feasibility work if the owner accepts broader instruments/holding periods. Outside this intraday equity protocol; no ETF/options substitute is assumed equivalent. |

My judgment: resolving research-design and execution feasibility is more useful
than generating further intraday candidates for this short, preselected universe.
Broader historical evidence elsewhere does not authorize changing Factory's
universe, gates, budget or objective. There is no ready next candidate established
by these three literature checks.

## Next independently testable milestone

Prepare a **data and execution feasibility specification**, not a signal engine:

1. Specify point-in-time identifiers, delistings, corporate actions, completed
   session calendars and timestamp conventions. Separate required fields from
   what the filename inventory actually proves.
2. Map historical sources for those fields, timestamped bid/ask sizes and closing
   execution. Verify coverage, licensing and acquisition-cost estimates using
   provider documentation. Do not purchase or download data yet.
3. Write a synthetic worked example of same-day selection and an outcome-blind
   comparator, including ties, missing quotes, halts and early closes. Show
   exactly what effect the experiment would measure; do not use real returns.
4. State break-even costs and portfolio controls in consistent units: cash,
   notional, position/aggregate risk, correlated exposure, shortability and
   rejection of late/unfillable signals. Account permissions and risk budget
   remain owner inputs, not assumed authorizations.
5. Return a decision before strategy coding. Go requires a faithful estimand,
   feasible data/execution and defensible power. Otherwise stop this path and
   present the broader-scope choice to the owner.

This recommendation does not authorize a new protocol, live quote capture, paper
service or candidate evaluation. The replay adapter stays disabled. Both Factory
schedules remain unloaded.

## Initial data/execution specification completed in this review

To move beyond a recommendation, the first procurement and fixture requirements
were checked without buying data or starting collection:

| Required input | Documentary evidence / unresolved acceptance |
|---|---|
| Historical universe | Massive documents dated ticker lists including subsequently delisted stocks, but warns about missing fields and lack of an identifier surviving every security change. Require explicit rename/share-class handling; never silently drop missing identifiers. [Reference guide][master]. |
| Historical stock NBBO | Its quote endpoint exposes bid/ask, sizes, exchanges and timestamps. The displayed individual Advanced plan is $199/month with all quote history; the archive date shown is September 10, 2003. This is a posted price, not a purchase recommendation, verified entitlement or all-in project quote. [Quote documentation][quotes]. |
| Bars versus quotes | History and quote access are separately gated, so possessing minute bars does not establish quote access. [Coverage guide][coverage]. |
| Licensing and total acquisition cost | Unresolved: account classification, permitted use/retention, full-universe volume, storage and source-version retention. No subscription or paid endpoint was used. |
| Execution proof | NBBO availability is not a fill guarantee. Auction participation, order deadlines, broker eligibility, queue/size effects and short locates remain unresolved. |

A minimal proposed record would contain source/version/hash, stable security
identity plus dated symbol, effective and known-at timestamps, session close,
signal cutoff, quote event/receipt times, bid/ask and sizes, eligibility status,
and a specific missing/rejection reason. This is a design sketch, not a new
schema installed in Factory.

**Invented acceptance example, no continuation or P&L:** at a fixed information
cutoff, four invented eligible symbols have ordering A, B, C, D; B and C tie.
A hypothetical bottom-two selection uses a stable-ID tie break and selects A/B.
B then has no usable execution quote. Preserve B's rejected intent; do not replace
it after seeing later prices. Preserve the full four-symbol comparison roster
and its quote eligibility too. Neither an absent quote nor a halt becomes a
zero-return completed trade. An early-close session uses calendar-relative
cutoffs or is explicitly excluded by a preregistered rule. No later-session
observation may revise the original membership, ordering or rejection.

This example detects leakage and selection/accounting errors without claiming
that bottom-two selection is an approved strategy or that the comparator is
already statistically valid. Statistical design must still settle the estimand,
weights, risk units, same-day controls and missing-execution treatment before
any real return is computed. The concrete blocker is now clear: data products
exist in principle, but identity quality, execution access, licensing/cost and
protocol compatibility have not passed acceptance. Do not build a trading
engine to work around these unresolved inputs.

## Verification and stopping point

Only this memo is added. Checks cover documentation links/freshness, diff review,
state hashes and scheduler status. No strategy tests/evaluator, public replication
code or protected outcomes were used. Public studies may overlap historical
dates; that does not grant access to Factory's protected local data.

The research stop is intentional: evidence has not established an eligible next
attempt. "Keep iterating" was applied to two bounded literature alternatives,
not optimization or repeated trials. Account-level usage percentage is unavailable;
no claim of consuming exactly 25% is made.

[eod]: https://academicweb.nd.edu/~zda/EOD.pdf
[orb]: https://alexandria.unisg.ch/server/api/core/bitstreams/3c2989c4-688d-4d78-8a71-f02690990d51/content
[trend]: https://www.aqr.com/-/media/AQR/Documents/Insights/Journal-Article/AQR-JPM-Fall-2017.pdf

[master]: https://massive.com/knowledge-base/article/does-massive-have-a-downloadable-security-master
[quotes]: https://massive.com/docs/rest/stocks/trades-quotes/quotes
[coverage]: https://massive.com/knowledge-base/article/how-much-historical-stock-data-does-massive-have
