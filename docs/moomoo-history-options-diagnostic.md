# moomoo historical/options diagnostic

This is a separately selected, read-only follow-up to the
[Phase 1 connectivity diagnostic](moomoo-phase1.md) and the
[M0 research milestone](product-roadmap.md#m0--evaluate-moomoo-data-for-better-trade-metrics).
It adds no provider adapter, journal recalculation, app registration, chart-feed
change, database/cache writes, paid entitlement or collector. Market-hours
streaming remains deferred. No account/trading endpoints were called.

The [broader comparison](moomoo-broader-history-options.md) adds September-expired
NVDA history, SPY's full option session, a nonstandard UVXY example and a stock
split check. The [endpoint-to-metric map](moomoo-endpoint-metric-map.md) distinguishes
those results from documentation-only candidates. The observations below remain
the original two-call NVDA cohort.

The later [option-field study](moomoo-option-field-validation.md) found sizes
and OI returned as integer strings for four standard contracts. Its typed
decoder recovered values that matched Tradier. Earlier numeric-only summaries
cannot establish absence or a permission restriction; their complete raw wire
shapes were not retained. The standalone quantity decoder is now repaired.

## Scope and command

The frozen comparison cohort is NVDA, its 2026-10-16 $230 call (active at the
2026-10-10 observation), and its 2026-10-09 $230 call (expired at observation).
The historical regular session is 2026-10-09. A five-row NVDA option screen
also supplies at most two contracts for current snapshot comparison.

```bash
cd backend
python -m scripts.moomoo_history_options_diagnostic
python -m pytest tests/test_moomoo_history_options_diagnostic.py tests/test_moomoo_diagnostic.py -q
```

Use the existing backend Python environment. The probe reuses the Phase 1
owner-only AppKey/private-key files outside Git. Baseline credentials are read
from the existing local `~/TradeJournal/backend/.env` by default; an explicit
`--baseline-env` can select another existing file. Environment variables take
precedence, as in the current clients. It neither prints credentials nor
loads unrelated configuration into the environment. No new setup is required
when the existing provider credentials remain available.

The run allows at most 18 requests, starts at most one request per second, has
15-second hard request deadlines spanning headers/body parsing, and refuses
responses above 2 MiB or beyond the elapsed response budget. This Unix
main-thread CLI refuses unsupported environments or an existing process alarm;
it restores the signal handler/timer after each request. It requests identity
encoding and refuses unexpected compression. It never follows redirects, uses inherited proxies,
retries, follows provider-supplied URLs/cursors, or paginates indefinitely.
Only fixed market-data hosts/methods/paths can receive credentials. Python
logging is disabled for network operations and restored afterward, including
descendant HTTP loggers and inherited DEBUG handlers. Signature
construction reuses the verified five-field REST payload, signing the final
wire query/body. Raw responses stay in memory; stdout contains aggregate
comparisons and small numeric samples. Exit 1 reports configuration/request
failures; exit 0 means the bounded requests completed, not that coverage or
data quality has been established.

History takes one response per symbol. The request declares `num=370`, raw
prices and no explicit extended-hours inclusion. Baselines use the existing
Alpaca stock feed and option-history request semantics, plus Polygon's
split-adjusted stock aggregates. Regular-session filtering uses
America/New_York. Invalid OHLC, duplicate timestamps, non-minute stamps and
outside-session bars are excluded and counted. Missing precision remains
unknown; volume comparison is omitted rather than fabricated. Comparisons
retain two interpretations: timestamps as reported, and a clearly labeled
minus-one-minute moomoo end-label hypothesis. Neither alters production data.

## Observed results

The final historical comparison ran at **2026-10-10 18:12:40 ET**. All 15
requests returned HTTP 200; all signed moomoo requests returned `ret_code=0`.
It finished in 14.227 seconds. Two later baseline reads compared the screener
contracts, and one final moomoo read explicitly requested documented bid/ask,
size, OI and multiplier fields. Across the bounded investigation there were
65 market-data/time requests, including the initial unsuccessful symbol/date
trial and two chain-resolution requests. No streaming or ongoing collection
was started. Private temporary files contain only bounded sanitized reports,
not raw bar or depth histories; live responses are not committed as fixtures.

After security-review repairs, a final bounded guard verification at
**18:23:23 ET** completed all 15 requests successfully in 14.413 seconds with
hard deadlines, identity encoding and logging suppression. It reproduced the
386/390 option-history matches and 390 stock/Polygon matches under the same
unverified timestamp hypothesis. This was a single foreground run, not a
background collector.

| Test | Actual result |
|---|---|
| Security metadata | Stock and both option codes resolved; both options reported contract size/lot size 100. |
| Active and expired chains | 224 and 176 contracts respectively; both requested calls were present. This establishes recently expired chain access for this example, not a long-term archive. |
| Stock and both option histories | Each returned 390 minute rows despite `num=370`; no next-page indication. Labels ran from 09:31 through 16:00 ET. |
| Option IV/HV history | Five timestamped points for each contract, spaced one day apart in this sample. Intraday cadence, publication time and older archive coverage remain unverified. |
| Option screen | Five NVDA contracts returned with numeric last price, IV and Greeks. A documented-field follow-up also returned bid/ask and multiplier/share size 100. The then numeric-only parser did not produce usable bid/ask sizes or OI despite explicit requests. This does not prove wire-field absence or a permission restriction; see the later typed field study. |
| Existing sources | Alpaca IEX stock bars, default-endpoint option history and indicative option snapshots succeeded. Tradier quotes/Greeks and Polygon stock aggregates succeeded. These are the local configured sources, not a new assertion about production settings. |

Two protocol details mattered:

- Moomoo's chain returned `US.NVDA261016C230000` and
  `US.NVDA261009C230000`, while the baseline OCC codes are
  `NVDA261016C00230000` and `NVDA261009C00230000`. The earlier padded moomoo
  request returned `ret_code=-7`; it was a symbol-resolution problem, not
  an established entitlement failure. Mapping was checked against chain
  expiry, call side, strike 230 and underlying NVDA before the corrected run.
- `start=end=2026-10-09` returned HTTP 200/`ret_code=0` with empty stock bars.
  Spanning `2026-10-09` to `2026-10-10` returned the session. Endpoint date
  boundaries therefore need explicit validation; empty success is not proof
  that no historical data exists.

## Comparison and implications for metrics

The unshifted labels produced large apparent price differences. Under the
**unverified end-label hypothesis**, the results were:

| Comparison | Matched minutes | OHLCV observations |
|---|---:|---|
| Active call versus Alpaca | 386 | All five fields matched exactly. Moomoo's four additional rows had zero volume; more rows did not establish additional traded-price information. |
| Expired call versus Alpaca | 390 | All five fields matched exactly. |
| NVDA versus Polygon | 390 | All highs/lows matched; 389 opens and 388 closes matched within $0.000001. Maximum open/close discrepancies were $0.01/$0.07. Volume still differed materially. |
| NVDA versus Alpaca IEX | 389 | Median absolute OHLC differences were $0.01. Volume differed, as expected for different venue coverage, but this does not independently establish moomoo's consolidated-feed status. |

This is strong empirical evidence for end-of-minute labels, **not official
confirmation of their semantics**. The source report keeps the unshifted
comparison too. Timestamp conversion, auction/trade-condition handling,
zero-volume bar construction and volume semantics need resolution before any
metric-source replacement. Matching one session is not proof of general
correctness, and Polygon's split-adjusted basis differs from moomoo's raw
basis even though this recent session's highs/lows agreed.

Current-option comparison used two screener-returned puts, separate from the
two historical calls. Their bid/ask values matched Tradier's closed-market
values in the bounded follow-up. Moomoo's reported IV percentages were close
to the baseline decimal IVs after a diagnostic percent interpretation, and
Greeks differed across vendors. No screener quote/Greek timestamp was available
to establish contemporaneity. Wire scaling and Greek model/unit conventions
remain unresolved; no provider is ranked as more accurate on these snapshots.
Current vendor Greeks do not replace historical `*_at_fill` values or the
fill-premium-based local Black-Scholes calculations. No actual journal fill
or derived money metric was read or recalculated.

Historical-request RTTs in the final run were 233.810 ms (moomoo stock),
190.180/193.346 ms (moomoo options), 136.784 ms (Alpaca stock), 179.850 ms
(batched Alpaca options), and 169.596 ms (Polygon stock). These are single
request round trips, not exchange latency, provider freshness or sustained
performance measurements. Snapshot source times remained Friday observations
while the trial ran Saturday; no live-market acceptance is claimed.

**Recommendation:** keep current metric sources. This sample establishes
useful recently expired option history and daily IV/HV access, but does not
demonstrate better option MFE/MAE inputs than Alpaca. The next historical slice
would test older expiries, another underlying, illiquid/adjusted contracts and
corporate actions, with timestamp and field semantics resolved first. The
separate market-hours depth/ticker test is still deferred. Historical Level 2
availability and private live-depth recording rights remain unresolved.

## Verification

Offline tests use invented bars, mocked HTTP and the public RFC 8032 key.
Coverage includes frozen GET signatures, destination and redirect refusal,
authentication/permission/rate failures, hard header/body deadlines and slow
trickles, inherited DEBUG logging, byte/request budgets, precision,
missing/duplicate/malformed bars, session boundaries, the separate timestamp
hypothesis, bounded OCC mapping, configured comparisons and secret-reflection
refusal. Repository verification and native review evidence are recorded in
the pull request when publication is complete.

Official references used for request schemas and their limits:

- [AppKey authentication](https://open.moomoo.com/api/overview/getting-started)
- [Historical candles](https://open.moomoo.com/api/quote/basic-data/history-kline)
- [Contract metadata](https://open.moomoo.com/api/quote/basic-data/stock-basicinfo)
- [Option chain](https://open.moomoo.com/api/quote/derivatives/option-chain)
- [Option screen](https://open.moomoo.com/api/quote/screening/option-screen)
- [Option volatility](https://open.moomoo.com/api/quote/derivatives/option-volatility)
- [Moomoo pagination](https://open.moomoo.com/api/quote/pagination)
- [Alpaca stock bars](https://docs.alpaca.markets/us/reference/stockbars)
- [Alpaca option bars](https://docs.alpaca.markets/us/reference/optionbars)
- [Tradier quotes](https://docs.tradier.com/reference/brokerage-api-markets-get-quotes)
- [Polygon/Massive stock aggregates](https://massive.com/docs/rest/stocks/aggregates/custom-bars)
