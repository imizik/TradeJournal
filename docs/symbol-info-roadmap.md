# Symbol info panel: roadmap

**The goal.** Switch the chart to a ticker and see what TradingView's symbol
page would tell you (latest news, upcoming earnings, key stats, what the
street and the options market expect) beside the chart, without opening
another tab. It serves the [Charts epic](charts-roadmap.md) goal of never
opening TradingView for normal chart work.

**What this is.** The working plan for that panel: priorities, data sources,
acceptance criteria. Every source below was probed with the production
credentials on 2026-10-02 (after the 2026-10-01 close). Rows marked
*unverified* are not established capability. Re-probe before shipping an item;
providers change entitlements without notice.

**The angle.** 1,519 of 1,589 journal trades are options, mostly 0-7 DTE
([charts roadmap ground truth](charts-roadmap.md#how-the-user-trades-reported-journal-snapshot-2026-09-30)).
TradingView's Forecast tab (analyst 12-month price targets) is close to
useless for that. What matters is what the options market prices for the next
few days, how the name actually moved on past earnings, and what is moving it
today. The plan builds those first and adds the TradingView-style analyst data
after them, clearly labelled.

## How to work from this file

1. Take the first `next` row on the [status board](#status-board). Board order
   is execution order. One pull request per item ID, scoped to its **Done
   when**.
2. This is a separate track from the Charts board. It touches the chart page's
   side column, not the chart canvas, so it can run beside a Charts item. Keep
   new UI in `frontend/components/charts/SymbolInfo*.tsx` and new backend code
   in `backend/app/engine/symbol_info*.py`, so the two tracks do not collide in
   `ChartWorkspace.tsx` beyond one mount point.
3. Every pure normalizer gets a backend test from a recorded, trimmed provider
   fixture. Every tab gets a browser test in `frontend/e2e/` against seeded or
   stubbed data. Live provider data is a known gap; say so in the PR, as
   `docs/agent/verification.md` requires.
4. In the same PR, update the item's row (`done`, PR link) and mark the next
   row `next`. When behavior ships, document it in `docs/charts-workspace.md`
   and add the feature to `docs/agent/feature-map.md`.

## Status board

| ID | Item | Phase | Status |
|---|---|---|---|
| T1.1 | Panel shell and the **You** tab: your own trades on this underlying | 1 Core | done ([PR #115](https://github.com/imizik/TradeJournal/pull/115)) |
| T1.2 | **News** tab: latest headlines for the symbol (Alpaca / Benzinga) | 1 Core | next |
| T1.3 | **Overview** tab: key stats and company profile (Tradier) | 1 Core | todo |
| T1.4 | **Events** tab and header badge: next earnings, ex-dividend, splits (Tradier) | 1 Core | done ([PR #125](https://github.com/imizik/TradeJournal/pull/125), with Charts C2.5) |
| T2.1 | Implied move: what the options market prices for this week and for earnings | 2 Forecast | done ([PR #128](https://github.com/imizik/TradeJournal/pull/128), with Charts C4.2–C4.5, ahead of T1.2 at the user's request) |
| T2.2 | Earnings reactions: how far the stock actually moved on past reports | 2 Forecast | todo |
| T2.3 | Analyst consensus: price targets, ratings, estimates, beat/miss (Yahoo, unofficial) | 2 Forecast | todo (needs [decision 1](#open-decisions)) |
| T3.1 | Short interest, short volume and hard-to-borrow flag | 3 Depth | todo |
| T3.2 | Financials: last eight quarters of revenue, margins and EPS | 3 Depth | todo |
| T3.3 | Ownership and insider activity | 3 Depth | todo |
| T3.4 | Peers strip: related tickers with today's move, one click to switch | 3 Depth | todo |
| T3.5 | News markers on the chart | 3 Depth | todo (needs Charts C1.3) |

Why this order: **You** costs zero external calls, is the one tab TradingView
cannot have, and proves the shell. News is the most-asked-for tab and the
cheapest feed. Overview and Events share one Tradier call each. The options
forecast (T2.1, T2.2) is built from data the app already fetches. Analyst data
is unofficial and waits on a decision. Phase 3 is depth that matters less for
short-dated options.

## What the APIs actually return

Probed 2026-10-02 with NVDA, CVNA, AMD, LLY and SPY.

| TradingView tab | Source we have | What it returned | Verdict |
|---|---|---|---|
| Overview: key stats | Tradier `/v1/markets/quotes` + `/beta/markets/fundamentals/company`, `/ratios`, `/statistics` (Morningstar) | Last, change, day range, 52-week high/low; market cap, enterprise value, shares outstanding, employees, sector code, IPO date, long description; P/E, P/S, P/B, EV/EBITDA, dividend yield, payout, 36/48/60-month beta; 30/60/90-day average volume; 13F holders and % institutional. One call each, 0.3-1.3 s, comma-separated symbols batch | **Feasible now** |
| News | Alpaca `/v1beta1/news` (Benzinga), already in `backend/app/engine/news.py` | Headline, summary, tagged symbols, source, URL, images; full text on request. Last 7 days: NVDA 115, SPY 240, LLY 28, CVNA 4 articles | **Feasible now** |
| News, with sentiment | Polygon `/v2/reference/news` | Publisher, description, keywords, and per-ticker `insights` (positive/negative/neutral plus a reasoning sentence) | Feasible but costs the Polygon budget (below); later |
| Events / earnings | Tradier `/beta/markets/fundamentals/calendars` | Earnings results and calls by quarter, AGM, conferences, annual report, each `Confirmed` or `Estimated`. History back to 2010 (AMD) / 2017 (CVNA). NVDA next: 2026-11-19 *Estimated*; CVNA next: 2026-10-28 *Confirmed* | **Feasible now**, with the caveats below |
| Dividends, splits | Tradier `/dividends`, `/corporate_actions`; Alpaca `/v1/corporate-actions`; Polygon `/v3/reference/dividends` | Ex, record and pay dates, amounts; split history with ratios | **Feasible now** (Tradier; Alpaca as fallback) |
| Forecast: analyst targets, ratings, estimates | Polygon/Massive Benzinga endpoints (`/benzinga/v1/ratings`, `/consensus-ratings`, `/earnings`) | **HTTP 403**, "not entitled", needs a paid plan | Not available on current plans |
| Forecast: same data | Yahoo via `yfinance` (already a dependency for quotes) | Price targets (NVDA mean 327.7, median 315, high 515, low 180), rating counts (NVDA 10/48/2/1/0), 984 upgrade/downgrade rows with target changes, next-quarter EPS and revenue estimates with analyst counts, EPS trend over 90 days, last four quarters beat/miss, 150 insider transactions | **Works**, unofficial and unlicensed: [decision 1](#open-decisions) |
| Forecast, trader edition | Tradier option chains (Charts C4.1 adapter) + Tradier daily bars | ATM straddle per expiration; daily bars back to the 1990s | **Feasible now**, calculated locally (T2.1, T2.2) |
| Financials | Polygon `/vX/reference/financials` | Quarterly income statement, balance sheet, cash flow from SEC XBRL (NVDA Q2 FY27: revenue 96.2B, diluted EPS 2.46), with filing date | Feasible; `vX` is Polygon's experimental route and the newer `/stocks/financials/v1` is 403, so it may be retired |
| Short interest | Polygon `/stocks/v1/short-interest`, `/stocks/v1/short-volume`; Tradier `/v1/markets/etb` | FINRA short interest twice a month with days to cover (NVDA 294M, 2.55 days, settled 2026-09-15); daily short-volume ratio (NVDA 54.1% on 2026-10-01); the easy-to-borrow list | Feasible |
| Ownership, insiders | Tradier `/company` (13F summary); Yahoo insider transactions; SEC EDGAR Form 4 | 13F: 6,065 holders, 69.5% held. Yahoo: Form 4 rows with insider, role, shares, value. EDGAR: *unverified*, blocked by this sandbox's network, not by SEC | 13F feasible; insiders via Yahoo or a later EDGAR probe from the VPS |
| Peers | Polygon `/v1/related-companies` | Ten tickers (NVDA: GOOGL, AMD, MSFT, META, AMZN, TSLA, AAPL, AVGO, INTC) | Feasible |
| Logo | Polygon ticker `branding`; Alpaca `/v1beta1/logos` | Polygon returns image URLs that need the API key to fetch; Alpaca is 403 on this plan | Not building (below) |
| Technicals (buy/sell gauge) | — | — | Not building: no buy/sell signals ([charts roadmap](charts-roadmap.md#not-building)) |
| Ideas, Minds (social) | — | — | Not available, not wanted |
| ETF holdings (SPY, QQQ components) | — | Tradier fundamentals return nothing for SPY | Not available |
| Economic calendar (CPI, FOMC) | — | — | None; a hand-kept yearly file if ever wanted (charts roadmap decision) |

### Data traps the probes found

Each one would put a wrong number on screen. The normalizers must handle them,
and the item that consumes the data owns the test.

- **Tradier's quote `average_volume` is not the volume average you expect.**
  NVDA read 9.57M in the quote; the fundamentals 30-day average read 112.7M
  and Polygon's short-interest average daily volume 115.3M. Use the
  fundamentals `price_statistics` averages (or compute from daily bars), never
  the quote field. (T1.3)
- **Tradier fundamentals return more than one share class per symbol.** NVDA
  came back as the primary class (`0P000003RE`, IPO 1999, all ratios) plus a
  second class (`0PDXF29G25`, IPO 1970, nearly empty) that carries its own
  beta and averages. Pick the share class matching the request's primary
  listing and ignore the rest. Do not merge fields across classes. (T1.3)
- **Calendars can hold two "next earnings" rows.** CVNA had Q3 results on
  2026-10-28 *Confirmed* and 2026-10-29 *Estimated*. A confirmed row wins for
  the same fiscal quarter. (T1.4) By 2026-10-04 the estimated row was gone;
  the recorded fixture keeps it.
- **Estimates lag announcements.** On 2026-10-04 Tradier still had TSLA's Q3
  report as 2026-10-22 *Estimated*, a day after the 2026-10-21 Tesla announced
  that day; CVNA's *Confirmed* 2026-10-28 matched Carvana's release. Show the
  status every time a date is shown. (T1.4, C2.5)
- **Sources disagree on dates.** NVDA's next report: Tradier 2026-11-19
  *Estimated*, Yahoo 2026-11-17. Show the source and status, prefer a
  confirmed date from either, and never present an estimate as a date. (T1.4,
  T2.3)
- **No time of day for earnings.** Tradier's calendar has dates only (its
  `time_zone` field holds a placeholder date), so before-open versus
  after-close is unknown. Yahoo's `earnings_dates` carries a time but could not
  be reached from this sandbox (*unverified*). Until a source is verified the
  panel says "time not published". (T1.4, T2.2)
- **No float.** Tradier's `float` read 0 and Polygon has no float endpoint on
  this plan. Short interest is shown against shares outstanding and labelled
  that way, never as "% of float". (T3.1)
- **ETFs and indices have no fundamentals.** SPY, the most-traded underlying,
  returns no company profile, ratios or calendar. Every tab must render an
  explicit "not available for ETFs" state, and the panel must still be useful
  on SPY through **You**, **News** and the implied move.

## Rate and cost budget

The panel must not starve the chart feed or the enrichment jobs that share
these keys.

| Provider | Shared with | Budget for this panel | How |
|---|---|---|---|
| Tradier (120/min per token) | Chart feed (60/min cap), options positioning (30/min), position quotes (under 10/min) | **At most 10/min** | Fundamentals cached 24 h per symbol, calendar 12 h, batched by `symbols=`. A cold symbol costs three calls (company, ratios, calendar); a warm one costs none |
| Alpaca (free data plan) | Enrichment, reports, scalp packets | At most 2/min | News cached 60 s per symbol on the server; the browser polls once a minute only while the News tab is open and the page is visible |
| Polygon Basic (5/min) | Fill enrichment, which paces itself from Polygon's first 429 | **At most one call per symbol per dataset per day**, never on the hot path | Disk cache; on a 429, serve the cached copy with its age and do not retry. No Polygon call in Phase 1 |
| Yahoo (`yfinance`) | Quote fallback, report gauges | One fetch per symbol per day | Disk cache; any failure shows "Yahoo unavailable" and the cached copy if one exists |
| Anthropic | AI reviews | Zero by default | Nothing in this plan calls a model automatically |

## Rules every item follows

- **Normalize in the backend.** Providers are adapters; the frontend sees one
  shape per tab and never a provider response. Normalizers are pure functions
  (no network, no database) so they can join the pure-module allowlist in
  `backend/tests/test_import_boundaries.py`; fetching and caching live in a
  separate module.
- **One request per open tab.** `GET /charts/symbol/{symbol}/{tab}` returns
  everything that tab shows. The browser fetches only the open tab, after the
  symbol has settled for about 300 ms (stepping the watchlist with hotkeys
  must not fire a request per step), and never per row. That is the N+1 rule
  in `CLAUDE.md`.
- **Source and age on every block.** Each block names its provider and as-of
  time. Numbers carry the charts-roadmap labels: *observed* (a provider field),
  *calculated* (our formula over observed data), *inferred* (a heuristic),
  *estimated* (the provider says so). Yahoo data is always tagged
  "Yahoo, unofficial".
- **Missing is shown as missing.** A field the provider did not return renders
  as "—", not zero and not a stale value without its age. A failed provider
  degrades only its own block.
- **No new tables and no migrations** for Phases 1-3. Caches live under
  `backend/data/symbol_info/v1/<provider>/` (gitignored), like the chart
  calendar cache. That keeps this track out of Alembic, where parallel
  branches collide.
- **No API key leaves the backend.** No provider URL that embeds a key is
  ever sent to the browser.
- **External links open in a new tab** and are the article's own URL. No
  article text is republished beyond the provider's summary.

## Phases

### Phase 1 — Core panel

**T1.1 Panel shell and the You tab.** A tabbed section in the chart page's
side column, under the watchlist: **Overview · News · Events · Forecast ·
You**. It follows the main chart's symbol, remembers the open tab per device,
collapses on the phone layout, and hides in immersive mode the way the
watchlist does. The **You** tab is built from journal data only, by
underlying: open position (if any), closed trades, realized P&L, win rate,
average hold time, best and worst trade, last traded date, and the five most
recent trades linking to their records. It counts closed trades only, uses
the reconstructor's realized P&L as stored, and does not recompute P&L.
*Done when:* the shell renders every tab as a placeholder except **You**;
**You** shows seeded values in a browser test using
`backend/scripts/seed_dev_data.py`; switching symbol re-fetches once; a
symbol with no trades shows "No trades on this symbol"; the 390 px layout
test passes.

**T1.2 News.** The latest 20 Benzinga headlines for the symbol, newest first:
time (relative, with New York time on hover), headline, source, a "+N
tickers" chip when the article tags several symbols, summary on expand, and
the link out. A **Focused** toggle (default on) hides articles tagging more
than three symbols, which removes most mega-cap roundups (NVDA appears in
many). New articles since the tab was opened show as "N new" at the top
instead of shifting the list. Reuse `fetch_news`; add the server-side 60 s
cache. *Done when:* a fixture with mixed tagging proves the Focused filter;
an empty feed says "No news in the last 7 days"; polling stops when the tab
or page is hidden (browser test with a stubbed route).

**T1.3 Overview.** Price and change, day range, a 52-week range bar, average
volume (30-day, from fundamentals; [trap](#data-traps-the-probes-found)),
market cap, enterprise value, P/E, P/S, P/B, EV/EBITDA, dividend yield, beta
(60-month), shares outstanding, % held by institutions, sector, employees,
IPO date, and the description collapsed to two lines. The quote fields come
from the chart's existing quote where one is already loaded; do not fetch a
second quote. *Done when:* the normalizer test covers NVDA's two share
classes and picks the primary one, an ETF fixture (SPY) renders the "not
available for ETFs" state, and every value has its as-of date on hover.

**T1.4 Events and the earnings badge.** Next earnings date with
*Confirmed*/*Estimated* status and days away, the time of day if a verified
source has one (otherwise "time not published"), the next ex-dividend date
and amount, splits in the last two years, and the last eight report dates.
The chart header shows a badge when earnings fall within 14 days
("Earnings in 5 d · est."). This adapter **is** the data half of Charts
**C2.5**; C2.5 then only draws the markers on the chart from it. *Done when:*
the CVNA duplicate-row fixture resolves to the confirmed date, a symbol with
only estimated rows shows the *Estimated* label, an unknown date shows
nothing rather than a guess, and the badge appears and disappears around the
14-day line in a test with a fixed clock.
As built ([Events tab](charts-workspace.md#symbol-info-panel), [chart
earnings](charts-workspace.md#earnings-c25)): `GET /charts/symbol/{symbol}/events`
answers from `backend/app/engine/symbol_info_tradier.py`, which reads the
three Tradier datasets with its own budget of 10 a minute and keeps the
normalized rows (pure normalizers in `symbol_info_events.py`) in memory and on
disk for 12 or 24 hours. Earnings are quarterly *result* rows only (Tradier
event types 7-10), one date per fiscal quarter. Past reports are confirmed
dates only: an estimate whose day passed was never a report. Each symbol's
rows come from one share class, the one with the most rows. No upcoming row
means "Not announced"; nothing is projected from earlier quarters. Ex-dividend
dates show the next announced one and the last; splits the last two years.

### Phase 2 — Forecast, for an options trader

The **Forecast** tab, in this order from top to bottom: implied move, past
reactions, then analyst consensus.

**T2.1 Implied move.** From the Tradier chain adapter
(`backend/app/engine/options_chain.py`): the at-the-money straddle mid for
the nearest expiration, the nearest Friday, and the first expiration after
the next earnings date, shown as ±$ and ±% with the expiry and the IV.
Labelled *calculated*, with the quote time of the options used. One chain
call per expiration, inside the 30/min positioning budget, cached 60 s. Wide
or one-sided markets (no bid) show "market too wide" instead of a number.
*Done when:* a fixture chain test proves the straddle choice (nearest strike
to spot, both legs quoted), the earnings expiry is chosen from T1.4's date,
and a no-bid fixture renders the refusal.

As built ([Forecast tab](charts-workspace.md#symbol-info-panel)):
`GET /charts/symbol/{symbol}/forecast?spot=` with the chart's latest price.
`backend/app/engine/options_implied.py` (pure) takes the strike nearest the
price that lists both a call and a put (a tie takes the lower); a leg with no
bid or no ask, a crossed quote, or a spread wider than its own mid shows
"Market too wide" with the reason. The earnings row is the first expiration
strictly after the next report, since the report's time of day is unknown.
Chains come through the chart's option feed, 60 seconds fresh, inside its
share of the 30-a-minute budget; the tab reads again each minute while open.

**T2.2 Earnings reactions.** For the last eight reports (dates from T1.4's
history), the gap (open versus prior close) and the full-day move (close
versus prior close), from Tradier daily bars. Because the time of day is
unknown, compute both the report day and the next session and show the
larger absolute move as the reaction, labelled *inferred*, until a verified
timing source exists. Summary line: average absolute reaction versus the
current implied move from T2.1 ("Priced ±8.1 %, moved ±6.4 % on average").
*Done when:* a fixture test covers a before-open and an after-close report,
and the summary refuses to render with fewer than four past reports.

**T2.3 Analyst consensus (Yahoo, unofficial).** Price target mean, median,
high and low against the current price; rating distribution; the last ten
upgrades and downgrades with target changes; next-quarter EPS and revenue
estimates with the analyst count; the last four quarters' beat or miss;
EPS-estimate trend over 90 days. Fetched once per symbol per day through
`yfinance`, cached on disk, and tagged "Yahoo, unofficial" on every block.
**Blocked on [decision 1](#open-decisions).** Before shipping, probe from the
VPS itself (Yahoo rate-limits datacenter addresses and this sandbox could not
reach `earnings_dates`). *Done when:* a recorded fixture renders, a Yahoo
failure leaves the rest of the Forecast tab intact, and the probe result is
in the PR.

### Phase 3 — Depth

**T3.1 Short and borrow.** Short interest and days to cover from the latest
FINRA settlement (with the settlement date, which lags by about two weeks),
short interest as % of shares outstanding (labelled; [no float](#data-traps-the-probes-found)),
the daily short-volume ratio for the last ten sessions (labelled as a share
of FINRA-reported volume, which is not all volume: NVDA's 2026-10-01 row
covered 41.6M shares on a roughly 100M-share day), and a hard-to-borrow
flag when the symbol is missing from Tradier's easy-to-borrow list. Polygon
calls cached one day. *Done when:* fixtures render, and a Polygon 429 serves
the cached copy with its age.

**T3.2 Financials.** The last eight quarters of revenue, gross margin,
operating margin, net income and diluted EPS from Polygon's XBRL financials,
as small bars with year-over-year growth. Cached until the next filing date.
Isolate the `vX` route behind the adapter: if Polygon retires it, this tab
degrades and nothing else breaks. *Done when:* the NVDA fixture renders and
the margins are calculated, not read.

**T3.3 Ownership and insiders.** The 13F summary from the Tradier company
call T1.3 already makes (holders, % held, buyers versus sellers, new and
sold-out holders), and net insider buying and selling over 90 days. Insider
rows come from Yahoo if decision 1 allows it; otherwise from SEC EDGAR Form 4
after a probe from the VPS (EDGAR needs a descriptive `User-Agent` and is
free). *Done when:* the 13F block renders from the T1.3 payload with no extra
call.

**T3.4 Peers strip.** Polygon's related companies (cached seven days) as a
row of chips with today's change from one batched Tradier quote call; click
switches the chart. This is the first step of the charts roadmap's
"cross-market strip". *Done when:* one quote call serves all peers, and a
peer click behaves exactly like a watchlist click.

**T3.5 News markers on the chart.** Small markers on the candle where each
Focused article was published, for the main symbol; hover shows the headline,
click opens it in the News tab. Built on the Charts drawing primitives and
context menu, so it waits for **C1.3**. This replaces the "News markers"
bullet in the charts roadmap's Later list. *Done when:* markers align to the
right candle on 1m and 1D in a browser test, and a layer toggle hides them.

## Later

- **AI news digest**: a "what's the story today" button that summarizes the
  last 24 h of headlines and the price move with the Anthropic API, on demand
  only, cached per symbol per hour. Belongs with the charts roadmap's "Why did
  this move?", which owns the evidence-labelling rules.
- **Headline sentiment** from Polygon's per-ticker `insights`. It is a model's
  opinion and costs the scarce Polygon budget; add only if headlines prove
  hard to triage.
- **Seasonals**: average return by month and weekday from Tradier daily
  history. Cheap to calculate, of little use for 0-7 DTE options.
- **SEC filings list** (10-K, 10-Q, 8-K links) from EDGAR, after the VPS
  probe.
- **IV rank**: needs about a year of the C4.3 daily option snapshots before it
  means anything.

## Not building

- Logos. Polygon's branding images need the API key to fetch, so they would
  need a caching proxy; Alpaca logos are not on this plan. Cosmetic.
- TradingView's Technicals buy/sell gauge, or any buy/sell rating of our own.
- Ideas, Minds or any social feed.
- ETF holdings for SPY and QQQ: no source.
- A paid data upgrade (Massive/Benzinga analyst endpoints, Polygon paid
  financials) unless the user decides to pay for one; Yahoo covers the same
  ground for free, with the caveats in decision 1.
- Market movers lists from Alpaca's screener: the raw lists are dominated by
  warrants and rights priced under a cent.

## Open decisions

Only the user can settle these.

1. **Use Yahoo (`yfinance`) for analyst data?** It is free, it already
   powers the default quote provider, and the probe returned everything the
   Forecast tab needs. It is unofficial and unlicensed, Yahoo rate-limits
   datacenter IPs, and it can break without notice. The alternative is a paid
   analyst feed. **Recommendation: yes**, as T2.3, labelled "unofficial",
   cached daily, after T2.1 and T2.2 so the tab is useful without it.
2. **When does Phase 1 start relative to the Charts board?** This track
   touches the side column and new files only, so it can run beside the
   Charts items. **Recommendation:** run T1.1-T1.4 now, alongside C1.2; hold
   Phase 2 until T1.4 ships, because T2.1 and T2.2 need its earnings dates.
