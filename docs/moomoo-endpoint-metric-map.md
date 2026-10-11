# Moomoo endpoint-to-metric evidence map

Checked 2026-10-11 against the current official direct-API catalog, the
[broader historical/options reads](moomoo-broader-history-options.md),
[Phase 1 connectivity](moomoo-phase1.md), and the current backend source.
This is an explanatory research inventory. No feed, calculation, configuration,
metric value or provider adapter changes follow from this table.

The catalog snapshot contains **73 quote-reference pages**: 60 data pages,
seven push/protocol pages, three general guides and three user-watchlist pages.
Watchlist and all trading/account APIs are excluded from the authorized research.
Catalog presence is not proof of this account's access, US-category support,
free entitlement, history coverage or recording rights. Only the selected
bounded histories and metadata were called in this investigation.

Evidence labels: **N** = provider reads in the broader study; **P** = earlier
bounded diagnostic evidence; **D** = selected current schema inspected, no
new API read; **C** = catalog-only candidate, schema/access not established;
**E** = deliberately excluded. N/P always refer to the named samples, not an
endpoint-wide entitlement. Potential uses below are research hypotheses.

## Decisions for trade metrics

| Endpoint/data | Potential metric or feature | Current comparison/source | Evidence and decision |
| --- | --- | --- | --- |
| [Historical candles](https://open.moomoo.com/api/quote/basic-data/history-kline): options | Option MFE/MAE, giveback, exit efficiency, peak-time and post-exit paths | `trade_path.py` calls Alpaca option history; fill minutes excluded, actual FIFO exposure and Decimal math retained | **N/P.** September NVDA OHLC matched on 390 shared minutes; SPY had one differing minute in 405. Adjusted UVXY zero-volume candles add no verified traded coverage. Keep Alpaca; no recomputation. |
| Same endpoint: underlying minutes | Underlying MFE/MAE, move timing, ATR context and entry-price context | Alpaca minute paths; Polygon underlying price/context and independently computed indicators | **N/P.** Three additional sessions showed different OHLC/volume against IEX. Shared timestamps do not establish venue equivalence, fill-time availability or a better input. Keep current sources. |
| Same endpoint: daily/other intervals | Indicators, RVOL and swing/event-study histories | Alpaca daily `all` adjustment; Polygon split-adjusted daily/hourly context; chart history has its own explicit basis | **N/P.** Native minute/five-minute volumes differ; raw/forward daily split sample compared. Adjustment modes are not interchangeable; no indicator or backtest was rerun. |
| [Static profiles](https://open.moomoo.com/api/quote/basic-data/stock-basicinfo), [chains](https://open.moomoo.com/api/quote/derivatives/option-chain), [expirations](https://open.moomoo.com/api/quote/derivatives/option-expiration) | Contract resolution, expired-contract coverage, adjusted-root identity | Existing OCC mapping and Tradier chain contract model | **N** profiles/chains; **C** separate expiration endpoint. September history resolved despite chain failure; December candidate omitted. UVXY1 share size 20 is not its premium multiplier 100. Identity/deliverable semantics remain a gate. |
| [Option screen](https://open.moomoo.com/api/quote/screening/option-screen) | Spread/liquidity context, current Greeks/IV, OI or contract filtering | Tradier quotes/ORATS Greeks; Alpaca indicative snapshots; local fill-premium-based Black-Scholes | **P/D.** Earlier bid/ask and Greeks were observed; bid/ask sizes and OI were absent in sampled rows. No per-contract quote/Greek time was established. Current snapshots cannot replace historical `*_at_fill` values. |
| [Option volatility](https://open.moomoo.com/api/quote/derivatives/option-volatility) | Daily IV/HV context, IV premium and later IV-crush research | Existing local IV/Greeks; no historical vendor-IV comparison completed | **N/P.** SPY returned 31 daily points, not a year of coverage despite a one-year query. Documented percentages; publication/model/as-of rules unknown. An expiry-day IV spike is not independently validated. No historical overwrite. |
| [Exercise probability](https://open.moomoo.com/api/quote/derivatives/option-exercise-probability) | Potential model-context feature for option research | Local pricing/calculation models; no direct benchmark in this study | **D.** Documented percentage series supports US option categories and bounded limit; no model/calibration or API access test. This evidence does not equate it with realized assignment probability or historical fill-time delta. |
| [Strategy lists](https://open.moomoo.com/api/quote/derivatives/option-strategy), [spread definitions](https://open.moomoo.com/api/quote/derivatives/option-strategy-spread), [package quotes](https://open.moomoo.com/api/quote/derivatives/combo-option-quote) | Potential spread valuation and scenario comparison | Existing per-contract quotes and user-defined research semantics | **C** lists/spreads, **D** quote schema. Package quote is documented market data, not execution evidence. Read-only quote access, quote times, leg identity and pricing conventions remain untested. No order endpoint is included. |
| [Rehabilitation factors](https://open.moomoo.com/api/quote/basic-data/rehab) | Split/dividend basis reconciliation and corporate-action guards | Existing provider-adjusted histories and chart raw/split contracts | **N.** NVDA June 10 factor 0.1 agrees with the known split; mode-equivalence remains unproved. Separate split-list API documents HK-only support. Raw fill premiums/prices remain authoritative. |
| [Books](https://open.moomoo.com/api/quote/realtime/order-book), [pushes](https://open.moomoo.com/api/quote/push/subscribe), [ticks](https://open.moomoo.com/api/quote/realtime/rt-ticker) | Later liquidity overlays, imbalance and execution-context research | Existing Tradier price feeds; no existing depth source was replaced | **P** REST books and closed-market push trial; **C** separate REST tick read. ARCA multi-level observations do not establish TotalView, consolidated coverage, historical depth or recording rights. Market-hours test remains deferred. |
| [Earnings reactions](https://open.moomoo.com/api/quote/financials/earnings-price-move), [earnings-day paths](https://open.moomoo.com/api/quote/financials/earnings-price-history), calendar/context pages | Event windows and stratified outcome research | Research Studio source audit and current journal context | **D** earnings schemas; other context pages mostly **C**. Publication times, revisions, event identity, actual US access and history completeness need proof before historical research use. No retrospective value becomes a pre-entry fact. |

The current [trade-path implementation](../backend/app/engine/trade_path.py),
[Alpaca client](../backend/app/engine/alpaca.py),
[fill-context/Black-Scholes calculations](../backend/app/engine/enricher.py),
[Alpaca context enricher](../backend/app/engine/alpaca_enricher.py),
[Tradier quotes](../backend/app/engine/tradier.py), and
[option contract model](../backend/app/engine/options_models.py) were inspected
as source text only. No application provider module or journal was loaded.
These implementations identify comparison baselines; they were not exercised
on real fills by this study. Current metrics and their source provenance remain
unchanged.

## Whole quote catalog: potential use and evidence

This table covers all 73 distinct reference paths in the captured catalog.
A row labeled C is only a candidate inferred from its catalog name; it is not
an assertion about fields, supported markets, permissions or useful as-of history.
D rows have selective schema evidence described above or below. Protocol guides
are included for completeness and do not represent additional data products.

| Reference page | Potential journal/research use | Evidence |
| --- | --- | --- |
| [Overview](https://open.moomoo.com/api/quote/overview) | Catalog/naming/pagination support, not a metric endpoint | C — catalog guide only |
| [Naming Dictionary](https://open.moomoo.com/api/quote/naming-dictionary) | Catalog/naming/pagination support, not a metric endpoint | D — reference support only |
| [Pagination](https://open.moomoo.com/api/quote/pagination) | Catalog/naming/pagination support, not a metric endpoint | C — catalog guide only |
| [Market Snapshot](https://open.moomoo.com/api/quote/realtime/market-snapshot) | Price/quote context; live quality and coverage research | D — schema lists US equity/ETF/index, not US options |
| [Stock Quote](https://open.moomoo.com/api/quote/realtime/stock-quote) | Price/quote context; live quality and coverage research | P — NVDA quote only; market-hours freshness unproved |
| [Order Book](https://open.moomoo.com/api/quote/realtime/order-book) | Price/quote context; live quality and coverage research | P — venue-specific closed-market books; live proof deferred |
| [Current K-Line](https://open.moomoo.com/api/quote/realtime/cur-kline) | Price/quote context; live quality and coverage research | C — catalog only; schema and account access untested |
| [Real-time Data](https://open.moomoo.com/api/quote/realtime/rt-data) | Price/quote context; live quality and coverage research | C — catalog only; schema and account access untested |
| [Real-time Ticker](https://open.moomoo.com/api/quote/realtime/rt-ticker) | Price/quote context; live quality and coverage research | C — catalog only; schema and account access untested |
| [Stock Basic Info](https://open.moomoo.com/api/quote/basic-data/stock-basicinfo) | Identity, sessions, adjustment or event/context validation | N — exact profile resolution, including a 20-share adjusted contract |
| [Trading Days](https://open.moomoo.com/api/quote/basic-data/trading-days) | Identity, sessions, adjustment or event/context validation | C — catalog only; schema and account access untested |
| [Rehabilitation Factor](https://open.moomoo.com/api/quote/basic-data/rehab) | Identity, sessions, adjustment or event/context validation | N — NVDA split-event fields; no production factor application |
| [Owner Plate](https://open.moomoo.com/api/quote/basic-data/owner-plate) | Identity, sessions, adjustment or event/context validation | C — catalog only; schema and account access untested |
| [History K-Line](https://open.moomoo.com/api/quote/basic-data/history-kline) | Identity, sessions, adjustment or event/context validation | N/P — selected options and stock histories; no universal archive proof |
| [Market State](https://open.moomoo.com/api/quote/basic-data/market-state) | Identity, sessions, adjustment or event/context validation | C — catalog only; schema and account access untested |
| [Search](https://open.moomoo.com/api/quote/basic-data/search) | Identity, sessions, adjustment or event/context validation | C — catalog only; schema and account access untested |
| [Economic Calendar Hot](https://open.moomoo.com/api/quote/basic-data/economic-calendar-hot) | Identity, sessions, adjustment or event/context validation | C — catalog only; schema and account access untested |
| [Economic Calendar Search](https://open.moomoo.com/api/quote/basic-data/economic-calendar-search) | Identity, sessions, adjustment or event/context validation | C — catalog only; schema and account access untested |
| [Capital Flow (Intraday)](https://open.moomoo.com/api/quote/capital-flow/capital-flow) | Candidate aggregate-flow context; classification/as-of validation needed | D — intraday stock/ETF schema; no option history |
| [Capital Flow (History)](https://open.moomoo.com/api/quote/capital-flow/capital-flow-history) | Candidate aggregate-flow context; classification/as-of validation needed | D — daily/weekly/monthly stock/ETF schema; access/as-of untested |
| [Capital Distribution](https://open.moomoo.com/api/quote/capital-flow/capital-distribution) | Candidate aggregate-flow context; classification/as-of validation needed | D — cumulative intraday stock/ETF snapshot, no time series |
| [Plate List](https://open.moomoo.com/api/quote/plate/plate-list) | Candidate sector/peer conditioning for outcome research | C — catalog only; schema and account access untested |
| [Plate Stock](https://open.moomoo.com/api/quote/plate/plate-stock) | Candidate sector/peer conditioning for outcome research | C — catalog only; schema and account access untested |
| [Reference Future](https://open.moomoo.com/api/quote/derivatives/reference-future) | Futures reference candidate; outside the selected US stock/options cohort | C — catalog only; schema and account access untested |
| [Option Expiration Date](https://open.moomoo.com/api/quote/derivatives/option-expiration) | Contract/model/strategy context; payoff and timestamp validation needed | C — catalog only; schema and account access untested |
| [Option Chain](https://open.moomoo.com/api/quote/derivatives/option-chain) | Contract/model/strategy context; payoff and timestamp validation needed | N/P — SPY/UVXY success, two older NVDA backend errors |
| [Future Info](https://open.moomoo.com/api/quote/derivatives/future-info) | Futures reference candidate; outside the selected US stock/options cohort | C — catalog only; schema and account access untested |
| [Option Volatility](https://open.moomoo.com/api/quote/derivatives/option-volatility) | Contract/model/strategy context; payoff and timestamp validation needed | N/P — sampled daily series; intraday as-of unknown |
| [Option Exercise Probability](https://open.moomoo.com/api/quote/derivatives/option-exercise-probability) | Contract/model/strategy context; payoff and timestamp validation needed | D — percentage series; account/model untested |
| [Combo Option Strategy](https://open.moomoo.com/api/quote/derivatives/option-strategy) | Contract/model/strategy context; payoff and timestamp validation needed | C — catalog only; schema and account access untested |
| [Combo Option Spread](https://open.moomoo.com/api/quote/derivatives/option-strategy-spread) | Contract/model/strategy context; payoff and timestamp validation needed | C — catalog only; schema and account access untested |
| [Combo Option Quote](https://open.moomoo.com/api/quote/derivatives/combo-option-quote) | Contract/model/strategy context; payoff and timestamp validation needed | D — market-data package quote; untested access/times |
| [Stock Screen](https://open.moomoo.com/api/quote/screening/stock-screen) | Candidate discovery or bounded contract selection | C — catalog only; schema and account access untested |
| [Warrant Screen](https://open.moomoo.com/api/quote/screening/warrant-screen) | Warrant candidate; outside the selected US stock/options cohort | C — catalog only; schema and account access untested |
| [Option Screen](https://open.moomoo.com/api/quote/screening/option-screen) | Candidate discovery or bounded contract selection | P/D — selected closed-market fields; size/OI/time gaps |
| [IPO List](https://open.moomoo.com/api/quote/ipo/ipo-list) | Candidate listing-age/event cohort context | C — catalog only; schema and account access untested |
| [Get User Security](https://open.moomoo.com/api/quote/watchlist/user-security) | User-specific watchlist state, outside market-data-only scope | E — not called or requested |
| [Get User Security Group](https://open.moomoo.com/api/quote/watchlist/user-security-group) | User-specific watchlist state, outside market-data-only scope | E — not called or requested |
| [Modify User Security](https://open.moomoo.com/api/quote/watchlist/modify-user-security) | User-specific watchlist state, outside market-data-only scope | E — not called or requested |
| [Earnings Price Move](https://open.moomoo.com/api/quote/financials/earnings-price-move) | Candidate earnings/fundamental event conditioning | D — equity schema, including US; access/as-of untested |
| [Earnings Price History](https://open.moomoo.com/api/quote/financials/earnings-price-history) | Candidate earnings/fundamental event conditioning | D — equity-only US/HK/SH/SZ schema; access/as-of untested |
| [Financial Statements](https://open.moomoo.com/api/quote/financials/statements) | Candidate earnings/fundamental event conditioning | C — catalog only; schema and account access untested |
| [Revenue Breakdown](https://open.moomoo.com/api/quote/financials/revenue-breakdown) | Candidate earnings/fundamental event conditioning | C — catalog only; schema and account access untested |
| [Analyst Consensus](https://open.moomoo.com/api/quote/research/analyst-consensus) | Candidate vendor research context; no historical as-of proof | C — catalog only; schema and account access untested |
| [Rating Summary](https://open.moomoo.com/api/quote/research/rating-summary) | Candidate vendor research context; no historical as-of proof | C — catalog only; schema and account access untested |
| [Morningstar Report](https://open.moomoo.com/api/quote/research/morningstar) | Candidate vendor research context; no historical as-of proof | C — catalog only; schema and account access untested |
| [Valuation Detail](https://open.moomoo.com/api/quote/valuation/detail) | Candidate valuation/peer/index context; no proven metric replacement | C — catalog only; schema and account access untested |
| [Valuation Plate Stocks](https://open.moomoo.com/api/quote/valuation/plate-stocks) | Candidate valuation/peer/index context; no proven metric replacement | C — catalog only; schema and account access untested |
| [Index Component Valuation](https://open.moomoo.com/api/quote/valuation/index-stocks) | Candidate valuation/peer/index context; no proven metric replacement | C — catalog only; schema and account access untested |
| [Index Related Plates](https://open.moomoo.com/api/quote/valuation/index-stock-plates) | Candidate valuation/peer/index context; no proven metric replacement | C — catalog only; schema and account access untested |
| [Dividends](https://open.moomoo.com/api/quote/corporate-actions/dividends) | Corporate-action dates and price/quantity basis checks | C — catalog only; schema and account access untested |
| [Buybacks](https://open.moomoo.com/api/quote/corporate-actions/buybacks) | Corporate-action dates and price/quantity basis checks | C — catalog only; schema and account access untested |
| [Stock Splits](https://open.moomoo.com/api/quote/corporate-actions/splits) | Corporate-action dates and price/quantity basis checks | D — documents HK-only split list; no US API request |
| [Shareholders Overview](https://open.moomoo.com/api/quote/shareholders/overview) | Candidate ownership/change context; publication lag and revision checks | C — catalog only; schema and account access untested |
| [Holding Changes](https://open.moomoo.com/api/quote/shareholders/holding-changes) | Candidate ownership/change context; publication lag and revision checks | C — catalog only; schema and account access untested |
| [Holder Detail](https://open.moomoo.com/api/quote/shareholders/holder-detail) | Candidate ownership/change context; publication lag and revision checks | C — catalog only; schema and account access untested |
| [Institutional Shareholders](https://open.moomoo.com/api/quote/shareholders/institutional) | Candidate ownership/change context; publication lag and revision checks | C — catalog only; schema and account access untested |
| [Insider Holders](https://open.moomoo.com/api/quote/shareholders/insider-holders) | Candidate ownership/change context; publication lag and revision checks | C — catalog only; schema and account access untested |
| [Insider Trades](https://open.moomoo.com/api/quote/shareholders/insider-trades) | Candidate ownership/change context; publication lag and revision checks | C — catalog only; schema and account access untested |
| [Company Profile](https://open.moomoo.com/api/quote/company/profile) | Candidate company/classification/operating context | C — catalog only; schema and account access untested |
| [Company Executives](https://open.moomoo.com/api/quote/company/executives) | Candidate company/classification/operating context | C — catalog only; schema and account access untested |
| [Executive Background](https://open.moomoo.com/api/quote/company/executive-background) | Candidate company/classification/operating context | C — catalog only; schema and account access untested |
| [Operational Efficiency](https://open.moomoo.com/api/quote/company/operational-efficiency) | Candidate company/classification/operating context | C — catalog only; schema and account access untested |
| [Top Buy/Sell Brokers](https://open.moomoo.com/api/quote/top-brokers/top-brokers) | Candidate broker-participation context; US scope unverified | C — catalog only; schema and account access untested |
| [Daily Short Volume](https://open.moomoo.com/api/quote/short/daily-volume) | Candidate short-position context; reporting cadence and field meaning checks | D — US schema describes position-level fields; not interchangeable with HK trade flow |
| [Short Interest](https://open.moomoo.com/api/quote/short/interest) | Candidate short-position context; reporting cadence and field meaning checks | D — stock/ETF schema; access/publication history untested |
| [Overview](https://open.moomoo.com/api/quote/push/overview) | Connection/auth/subscription/error handling, not a new metric | C — protocol reference; prior connection evidence, no new push test |
| [Authentication](https://open.moomoo.com/api/quote/push/auth) | Connection/auth/subscription/error handling, not a new metric | C — protocol reference; prior connection evidence, no new push test |
| [Subscribe and Unsubscribe](https://open.moomoo.com/api/quote/push/subscribe) | Connection/auth/subscription/error handling, not a new metric | C — protocol reference; prior connection evidence, no new push test |
| [Keep-Alive](https://open.moomoo.com/api/quote/push/heartbeat) | Connection/auth/subscription/error handling, not a new metric | C — protocol reference; prior connection evidence, no new push test |
| [Data Format](https://open.moomoo.com/api/quote/push/data-format) | Connection/auth/subscription/error handling, not a new metric | C — protocol reference; prior connection evidence, no new push test |
| [Error Codes](https://open.moomoo.com/api/quote/push/error-codes) | Connection/auth/subscription/error handling, not a new metric | C — protocol reference; prior connection evidence, no new push test |
| [Rate Limit and Quota](https://open.moomoo.com/api/quote/push/rate-limit) | Connection/auth/subscription/error handling, not a new metric | C — protocol reference; prior connection evidence, no new push test |

## Remaining evidence gaps and recommendation

The highest-value finding is usable older option history despite a failing
chain lookup, followed by correct instrument-session and adjusted-deliverable
handling. None justifies replacing current sources. Sparse zero-volume bars
are not proof of additional traded-price history, and more vendor model fields
are not proof of more accurate fill-time Greeks.

Further bounded research could resolve older contract identities from independent
reference data, compare common trade windows without touching saved metrics,
clarify publication/revision and adjustment conventions, and verify missing
bid/ask sizes, OI and quote/Greek timestamps. Any potential replacement remains
metric-specific and would need demonstrated coverage/correctness benefit,
provenance, fallback and rollback; this inventory authorizes none of those changes.

Maximum concurrent subscriptions, actual named depth licenses and private
non-display/ML recording rights remain unresolved in the Phase 1 evidence.
Historical Level 2 was not established by the catalog or these candle reads.
A later historical Workbench dataset cannot be reconstructed from candlesticks.
No vendor messages were sent. Market-hours verification remains separately deferred.

The captured public catalog at `/private/tmp/moomoo-broader-catalog.json` has
SHA-256 `aad3cd3581dfdc5a8f0329c58f4d3407a61d51f14aa492c4b42a9f91bf7b402f`.
Only explanatory documentation is saved in Git; temporary provider summaries
are bounded local evidence rather than a retained raw market-data archive.
