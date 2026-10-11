# Moomoo historical timestamp validation: original blocked report

**Follow-up on 2026-10-11:** the [October 8 comparison](moomoo-timestamp-comparison.md)
resolved the API usage-cost blocker using the official direct-channel pricing
statement and completed eight bounded reads. This report preserves the original
October 10 findings; its cost/data blockers are superseded, while official
timestamp publication/finality and auction semantics remain unresolved.

Observed 2026-10-10, approximately 22:59 UTC. This follow-up concerns historical
minute labels only. **The additional-session comparison is incomplete. Current
data sources remain in place.** There were no new authenticated market-data
reads, source integrations, journal recalculations, account changes or streaming.

## Verified base and preserved work

[PR209](https://github.com/imizik/TradeJournal/pull/209) merged at 22:50:47 UTC
on 2026-10-10 as `e8a9c98197ae9742a95910d7b2c3ffe9c63ad788`.
The fetched `origin/main` was that merge commit. Its tree is identical to the
previous reviewed head, `5bf466ee963b8421eb1c39f5ac5f03750927578c`.
The separate branch is `codex/moomoo-timestamp-validation`; the prior owner's
checkout and branch were preserved.

The [prior report](moomoo-history-options-diagnostic.md) remains the observed
October 9 evidence, including both timestamp interpretations. The owner confirmed
that raw bar responses stayed in memory and no additional session was tested.
The surviving sanitized guard report identifies session 2026-10-09 and capture
2026-10-10T22:23:23.888297+00:00; it contains summaries, not replayable raw bars.
The repository's historical-comparison fixture is invented test data.

A stored Alpaca SIP NVDA cache exists for October 8, with 941 rows including
extended hours. This is a possible baseline input, not a new Moomoo comparison.
It differs from the prior diagnostic's configured IEX stock feed. Its existence
does not supply the missing Moomoo or option histories or authorize a feed change.

## Official documentation findings

The public [English REST history reference](https://open.moomoo.com/api/quote/basic-data/history-kline)
and [Chinese REST history reference](https://open.moomoo.com/zh-cn/api/quote/basic-data/history-kline)
were retrieved directly over HTTPS on October 10. Both describe `time_key` as
“K-line time, millisecond timestamp” (English wording). Neither identifies interval
start, interval end, publication time, revision finality or lookahead-safe
availability. The prior one-minute-shift matches therefore remain empirical
evidence for a hypothesis, not an officially confirmed convention.

Both documents describe a trading-date field for minute candles and a timezone
offset in minutes relative to UTC. Their example labels -300 as US daylight
saving time; America/New_York on October 8–9, 2026 has offset -240. That example
is inconsistent with the session's timezone, so it cannot justify applying a
fixed offset or adding an offset to an epoch timestamp. No newly observed wire
`date` or `time_zone` values are available in this follow-up.

The Chinese reference describes start and end dates as inclusive. That conflicts
with the previous successful-but-empty same-day request versus the successful
next-day-end request. The docs also retain a maximum of 370 requested rows,
while the prior session returned 390. These discrepancies remain unresolved;
neither proves a timestamp convention or missing history.

The listed candle response fields carry no auction identifier or trade-condition
classification. Opening/closing OHLCV agreement alone would not establish which
auction prints were included. A zero-volume candle also does not establish a
new traded price, an executable quote, or when its OHLC became available.

The public [REST rate-limit reference](https://open.moomoo.com/api/overview/rate-limit)
describes quotas and pacing but supplies no numeric quota or per-request charge
for this account. OpenD documentation uses a different interface and timestamp
representation; it cannot confirm the direct AppKey REST convention by itself.

For source identification, SHA-256 digests of the retrieved HTML were:

| Reference | SHA-256 |
| --- | --- |
| English history | `ad9b9d8c1ba3715d9e94c6e3e2d0b71d4322111309d212aedb2bb01f33ea2efe` |
| Chinese history | `f65e4330f22011af91214a3231486f90660b4d4801d910217cad6dfaaf1e0f1b` |
| REST rate limit | `743e94a572617d07fe36db5a9c534be1dd9fdb432dca30cf5e26e33defcaa984` |

These identify this retrieval, not stable future page contents. Private temporary
HTML copies contain public documentation only; no credentials were included.

## Exact blocker and evidence still missing

The prior owner confirmed existing authorized credentials and successful bounded
access, but **per-request charges were not independently established**. No
approved stored raw Moomoo bars exist for the additional session. Consequently
new reads are necessary, and their cost is uncertain. The selected task explicitly
requires reporting that uncertainty before proceeding. No permission expansion,
purchase, alternate provider or wider invocation was attempted.

The missing evidence is confirmation that the bounded historical reads can use
the existing access without a new charge or entitlement, followed by an actual
additional-session dataset. October 8 is within the existing diagnostic's fixed
contract/date window. Its broad normal invocation also reads chains, volatility
and current snapshots, so it is not a timestamp-only observation.

No new opening, closing, auction-adjacent or zero-volume observations can be
reported. Raw timestamp preservation and both interval interpretations for that
additional session remain untested. Existing parser tests exercise the synthetic
boundaries and shift hypothesis; they cannot substitute for source observations.
Even a second exact OHLCV match would leave publication/finality and auction
semantics unverified. Quote freshness, OI/size, market-hours streaming, depth
entitlements and recording rights remain deferred.

## Verification observed

On the unchanged merged code, the existing historical-options and Phase 1
diagnostic test files passed: **93 tests, 5.48 seconds**. They use invented bars
and mocked HTTP, without authenticated requests. This report adds no executable
diagnostic changes and no live fixtures. Full runtime evidence from PR209 applies
to the identical implementation tree; this follow-up does not claim a new full
local application run. Documentation checks and publication CI are recorded in
the associated pull request, when available. The historical acceptance remains
blocked regardless of documentation CI status.
