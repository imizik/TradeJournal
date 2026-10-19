# Moomoo historical timestamp comparison: October 8

Observed 2026-10-11 at 00:25:56–00:26:04 America/New_York
(04:25:56–04:26:04 UTC), for Thursday October 8. The API usage-cost
blocker from the earlier October 10 report is resolved.
Eight bounded read-only requests succeeded. Current metric sources remain in
place: interval publication/finality, auction handling and field semantics
remain unresolved.

A [subsequent read-only investigation](moomoo-auction-time-semantics.md) sampled
the DST transition and five-minute labels and identified condition-coded closing
trades. It strengthens the interval-end interpretation and explains nearly all
of the closing-volume discrepancy; official publication/finality and some
aggregation differences remain unresolved. Results below describe this earlier
run.

## Cost evidence

The current [official developer platform](https://open.moomoo.com/) describes
OpenD and direct REST under “Two Channels to Moomoo Markets” and states
**“No additional API charges.”** This supplies a direct-channel pricing basis
missing from the earlier rate-limit-only investigation. The
[REST rate-limit reference](https://open.moomoo.com/api/overview/rate-limit)
separately describes quotas and pacing, without a per-request monetary fee.

Historical calls using the existing authorized access incur no additional API
usage charge under this published policy. This is not an account-billing audit
or proof that every market-data entitlement is free. No brokerage, account or
billing reads occurred; no subscription, quotation card, payment or permission
was activated. Previously accessible histories succeeded with the existing
secured credentials. Quota consumption remains an access constraint.

The retrieved developer homepage SHA-256 was
`6f76f826e1dfffa8f023d0c2ed8c301cc4b60cf53286fd79947bb86e7b35fbee`.
English/Chinese history-page hashes matched the earlier report. They still do
not explicitly define interval-start/end labels, publication time or finality.

## Method and observed bounds

A temporary foreground driver reused the merged
[diagnostic](../backend/scripts/moomoo_history_options_diagnostic.py)'s secure
credential reader, signing, `Reader`, `parse_bars` and `compare_interpretations`.
No production provider clients, routes, database or caches were imported/called.

| Read | Parameters/basis used |
| --- | --- |
| Moomoo server time | One unsigned clock request |
| Three Moomoo histories | NVDA stock; October 16 and October 9 expiry strike-230 calls; start October 8/end October 9; `ktype=1`, `autype=0`, `num=370`, `extended_time=0` |
| Moomoo date-boundary check | NVDA stock; start/end both October 8; same history parameters |
| Alpaca stock history | Existing local IEX, raw, 1-minute, 09:30–16:00 ET |
| Alpaca option history | Both previously validated OCC codes; endpoint default, matching the existing client which omits a feed parameter |
| Polygon stock history | NVDA October 8, 1-minute, split-adjusted; 941 rows including 390 regular-session rows |

All eight requests returned HTTP 200; all four signed Moomoo requests returned
`ret_code=0`. Elapsed time was 7.230 seconds. No retries, redirects, pagination,
current quote/Greek calls, new symbols or streaming occurred. The unchanged
reader's bounds were 18 requests, at most one request start per second, hard
15-second request deadlines and 2 MiB responses. No numerical Moomoo quota/rate
headers were returned; Alpaca reported a limit of 200. Maximum historical quota
was neither established nor exhausted.

Full responses/bar series stayed in memory. Retained output contains counts,
comparisons, source timestamps and four boundary samples per source/symbol,
without credentials, arbitrary response text or depth history. These temporary
files identify the run, not a durable historical dataset:

| Local evidence | SHA-256 |
| --- | --- |
| `/private/tmp/moomoo-timestamp-study.py` | `c5c141f33dd67b31710e358dbb020adc1f736e0788227523e2f957dc5d4ed436` |
| `/private/tmp/moomoo-timestamp-oct8-summary.json` | `9fd3328339d3ea793802fbf77dddbbcee35fae085764c3eaa75b794d2883eac3` |

## Timestamp and date observations

Each Moomoo history returned 390 valid rows despite `num=370`, with no duplicates
or malformed OHLCV. Raw labels ran **09:31–16:00 ET**. The hypothetical minus-one-
minute shift placed them at **09:30–15:59 ET**, matching the baseline labels.
Without the shift, only 389 rows fit the half-open regular-session window.
Both interpretations remained separate; no production timestamps were changed.

All three histories reported `date=20261008` and **`time_zone=-4`**. The
[English reference](https://open.moomoo.com/api/quote/basic-data/history-kline)
and [Chinese reference](https://open.moomoo.com/zh-cn/api/quote/basic-data/history-kline)
describe this field in minutes and give -300 as US daylight saving. The observed
-4 is consistent numerically with New York's UTC−4 hours, not the documented
minute unit. Epoch conversion used `America/New_York`, without applying the
wire offset. One sample does not establish units across markets or DST.

The same-day stock request succeeded with **zero rows**; next-day-end returned
exactly October 8. This reproduces October 9's discrepancy with the Chinese
inclusive-date wording. End-exclusive behavior in these samples remains an
empirical observation, not a general endpoint guarantee. No next-time marker
appeared in Moomoo histories; no pagination was followed.

## Side-by-side results

Equality below means absolute difference at most 0.000001. Shared option OHLCV
had exactly zero differences under the shift.

| Comparison | As-reported shared minutes / equal OHLC counts | Minus-one-minute hypothesis |
| --- | --- | --- |
| October 16 call vs Alpaca | 326 / O 32, H 26, L 30, C 24 | 327 shared; every OHLCV field exact |
| October 9 call vs Alpaca | 353 / O 21, H 26, L 17, C 22 | 354 shared; every OHLCV field exact |
| NVDA vs Polygon | 389 / O 3, H 6, L 6, C 4 | 390 shared; O 388, H 389, L 389, C 388 equal |
| NVDA vs Alpaca IEX | 389 / O 8, H 5, L 7, C 7 | 390 shared; median OHLC differences about $0.01–$0.015 |

Shifted Polygon maximum stock differences were $0.015 open, $0.000034 high,
$0.005 low and $0.09 close. Volume differed, especially at the close. Raw Moomoo
and split-adjusted Polygon bases were preserved; this session does not establish
interchangeability on corporate-action days. IEX differences do not prove
Moomoo consolidated coverage, licensing or superiority.

Both options' first/last regular-session OHLCV matched Alpaca exactly under the
shift. Moomoo's extra rows were **63** for the October 16 call (390 vs 327) and
**36** for the October 9 call (390 vs 354). All 99 had zero volume and
O=H=L=C equal to the previous minute's close; all were absent from Alpaca under
the shift. This indicates carry-forward candles in this sample, not additional
executed trades, executable quotes or better MFE/MAE coverage. Neither stock
source had zero-volume regular-session rows.

A small stock boundary sample preserves raw timestamps:

| Source/interpretation | Source timestamp | OHLC | Reported volume |
| --- | --- | --- | --- |
| Moomoo opening, hypothetical 09:30 | `1791466260000` = 09:31 ET | 234.92 / 235.20 / 233.87 / 234.24 | 2,386,594 |
| Polygon 09:30 | `1791466200000` | 234.92 / 235.20 / 233.87 / 234.24 | 2,385,714.069923 |
| Moomoo closing, hypothetical 15:59 | `1791489600000` = 16:00 ET | 230.58 / 230.615 / 230.32 / 230.48 | 13,137,322 |
| Polygon 15:59 | `1791489540000` | 230.58 / 230.615 / 230.32 / 230.57 | 1,809,253.658906 |

Moomoo volume precision was 0 for all histories. These are reported fields,
not a newly established option-volume unit or trading-price basis. Stock opening
OHLC matched Polygon; closing O/H/L matched, but close differed by $0.09 and
volume by about 11.33 million. Polygon separately returned a 16:00 extended-hours
row. No candle auction/trade-condition classification was available, so auction
inclusion remains **unresolved**; volume size alone cannot identify included prints.

Single historical RTTs: Moomoo stock 444.847 ms, options 422.508/439.411 ms;
Alpaca stock 150.528 ms, batched options 73.753 ms; Polygon 196.484 ms.
These are request round trips, not exchange freshness or sustained performance.

## Conclusion and verification

The usage-cost blocker is resolved and the additional-session comparison is
complete. It reproduces strong empirical evidence for end-of-minute labels and
exact shared option OHLCV. **Official labeling, publication/finality, auction
handling and timezone-field units remain unconfirmed.** A historical match does
not establish when a bar became available for a decision or justify lookahead-
safe normalization.

No journal fills, MFE/MAE or money metrics were read/recalculated. Extra zero-volume
option candles do not demonstrate improvement over Alpaca. Current sources remain
in place; market-hours streaming, depth entitlements/recording rights, historical
depth and broader options archive exploration remain deferred.

Unchanged offline signing/parsing/failure tests passed: **93 tests in 5.46 s**.
Offline saved-summary assertions checked eight successes, the empty same-day
result, exact option OHLCV, first/last matches and extra zero-volume counts.
Those assertions check report consistency, not vendor semantics. No executable
repository code, fixture, dependency or production configuration changed.
Documentation validation and exact-head CI are recorded in the PR.
