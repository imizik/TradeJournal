# Moomoo timestamp, timezone and closing-auction investigation

Observed 2026-10-11 at 00:43:47–00:44:01 America/New_York
(04:43:47–04:44:01 UTC). This bounded follow-up to the
[October 8 comparison](moomoo-timestamp-comparison.md) strengthens the evidence
for interval-end labels, resolves the sampled DST conversion, and identifies
a closing print that explains nearly all of the final-minute volume difference.
It does **not** establish publication time, a universal aggregation rule, or
permission to replace current metric sources.

## Scope and access

Fifteen foreground market-data requests took 14.077 seconds. Fourteen succeeded;
Polygon tick history returned HTTP 403. All six signed Moomoo histories returned
HTTP 200 and `ret_code=0`. The other request was Moomoo server time. Existing
secured credentials were reused without changes to account permissions or plans.

| Reads | Bounded selection |
| --- | --- |
| Moomoo | NVDA October 8 regular 1-minute, extended 1-minute, regular 5-minute and daily; March 6 and March 9 regular 1-minute |
| Alpaca | NVDA historical SIP raw bars: October 8 1-minute and 5-minute, March 6 and March 9 1-minute; one page of SIP trades at October 8 16:00:00–16:00:01 ET |
| Polygon | NVDA October 8 unadjusted 1-minute aggregates; stock trade-condition reference; one attempted page of trades for the same closing second |

Moomoo used each selected day through the following day, `autype=0`, `num=370`,
and `extended_time=0` except the extended read (`1`). The existing reader capped
the run at 18 requests, paced request starts at least one second apart, bounded
responses to 2 MiB and requests to 15 seconds, and disabled redirects and proxy
environment inheritance. No retries or pagination occurred. Alpaca bar reads
covered 09:30–16:03 ET; comparisons filtered the regular session. Trade parsing
used the strict half-open SIP window [16:00:00, 16:00:01), preserving nanoseconds.
Alpaca returned 112 trades and no next-page token.

The [earlier cost evidence](moomoo-timestamp-comparison.md#cost-evidence) applies
to Moomoo. Alpaca's [official FAQ](https://docs.alpaca.markets/us/v1.1/docs/market-data-faq)
allows historical SIP queries without a subscription when their end time is at
least 15 minutes old. These historical requests succeeded with the existing key;
SIP was selected only for this diagnostic, leaving the configured feeds alone.
No subscription, payment, account/billing read or automatic upgrade occurred.

Full responses stayed in memory. Retained output consists of sanitized counts,
comparison statistics and a few boundary/condition samples. No journal, database,
cache, chart feed or metric calculation was read or modified. No depth recording,
stream, trading operation or background process ran.

## Timestamp and timezone evidence

The direct [history reference](https://open.moomoo.com/api/quote/basic-data/history-kline)
describes `time_key` as a millisecond timestamp without specifying an interval
boundary or publication/finality rule. Its `time_zone` description says minutes;
the sampled wire values were **hours**, including the correct DST transition:

| NVDA session | Moomoo raw minute labels | Wire `time_zone` | Epoch-derived ET offset | Shared rows after the diagnostic −1 minute shift |
| --- | --- | --- | --- | --- |
| March 6, before DST | 09:31–16:00 ET | −5 | −05:00 | 390/390 Alpaca SIP |
| March 9, after DST | 09:31–16:00 ET | −4 | −04:00 | 390/390 Alpaca SIP |
| October 8 | 09:31–16:00 ET | −4 | −04:00 | 390/390 Alpaca SIP and Polygon |

Conversion used the epoch and `America/New_York`, independently of the disputed
timezone field. All three Moomoo minute reads returned 390 valid rows, with
`volume_precision=0`. Their wire dates matched the requested trading dates.
The March first labels were `1772807460000` and `1773063060000`; conversion
produced 09:31 with the corresponding winter/summer offsets.

October 8 five-minute candles ran **09:35–16:00**, with 78 rows. A separate
−5 minute comparison aligned all 78 with Alpaca's 09:30–15:55 labels. High and
low matched in all 78; open matched in 76 and close in 77. The maximum open/close
differences were $0.04/$0.09. The extended Moomoo minute series ran
**04:01–20:00** with 960 rows. Both strengthen the interval-end interpretation;
no normalization was added to application code.

After the −1 minute comparison, equal O/H/L/C counts against Alpaca SIP were
387/389/389/388 for October 8, 386/389/390/386 for March 6, and
385/390/389/386 for March 9. Equality tolerance was $0.000001. Maximum close
differences were $0.09/$0.13/$0.01, respectively. Shared-session high/low extrema
matched on all three days, but this is not a journal MFE/MAE validation.

The October 8 daily row was labeled **00:00 ET**, not 16:00. The read returned
two dates; only the requested date was summarized. Its close was $230.48 and
volume 118,697,435. Daily labels therefore require separate interpretation:
neither an intraday interval shift nor availability at midnight follows from
this value.

## Closing print and boundary allocation

Alpaca historical SIP reported these sanitized NVDA messages within the selected
closing second. Exchange `Q` is Nasdaq and `P` is NYSE Arca in the
[official SDK exchange reference](https://alpaca.markets/sdks/python/api_reference/data/enums.html).

| SIP epoch nanoseconds | Exchange | Conditions | Price | Reported size |
| --- | --- | --- | --- | --- |
| `1791489600555311820` | Q | `@`, `6`, `X` | 230.48 | 11,326,428 |
| `1791489600555347455` | Q | `@`, `M` | 230.48 | 11,326,428 |
| `1791489600097881621` | P | `@`, `M` | 230.58 | 200 |

The first message has a SIP time of 16:00:00.555311820 ET. Alpaca documents
`6` as a market-center closing trade, `X` as a cross trade and `M` as an official
close message. Its aggregation uses SIP time and start-labeled minute windows;
`M` does not update consolidated OHLCV, whereas `6` and `X` can. Counting the
Nasdaq `M` message as another execution would double the closing size.
([Aggregation and condition rules](https://docs.alpaca.markets/us/v1.1/docs/market-data-faq))
Nasdaq's [cross reference](https://www.nasdaqtrader.com/content/productsservices/trading/crosses/openclose_faqs.pdf)
describes the closing cross initiated at 16:00 ET and setting its official
closing price. The observed conditions, exchange, time and matching price
provide strong evidence of the closing cross, rather than volume size alone.

| Source/raw label | Close | Volume |
| --- | --- | --- |
| Moomoo regular 16:00, compared with 15:59 | 230.48 | 13,137,322 |
| Alpaca SIP 15:59 | 230.57 | 1,809,438 |
| Polygon 15:59 | 230.57 | 1,809,253.658906 |
| Moomoo extended 16:01, compared with 16:00 | 230.60 | 4,810,040 |
| Alpaca SIP 16:00 | 230.60 | 16,138,139 |
| Polygon 16:00 | 230.60 | 1,454,326.545208 |

Moomoo regular 16:00 exceeds Alpaca SIP 15:59 volume by **11,327,884**.
Subtracting the observed closing trade leaves **1,456 shares** unexplained.
Against Polygon the residual is **1,640.341094 shares**. The cross price also
matches Moomoo's final regular and daily close, explaining the apparent $0.09
close discrepancy.

Alpaca's next minute includes the cross. Subtracting its 11,326,428 shares from
Alpaca 16:00 leaves 4,811,711, only 1,671 above Moomoo extended 16:01. Across
both boundary candles the Moomoo/Alpaca volume difference is just **−215 shares**.
This strongly supports different allocation of the cross between the final
regular candle and the next minute. It does not prove every included trade or
Moomoo's undocumented interval-edge/auction policy.

Polygon 16:00 volume remains substantially different from both sources, even
after considering the cross. The [condition-reference response](https://massive.com/docs/rest/stocks/market-operations/condition-codes)
mapped official-close ID 15 to `M`, closing-trade ID 19 to CTA `6`, and corrected
close ID 38 to `9`. ID 19 supplied **no UTP mapping**. These reference rows do
not establish which trades Polygon actually aggregated. Its tick-history
request failed with sanitized status `http_error`, HTTP **403**; empty parsed
rows mean unavailable access, not no trades. No alternative endpoint, plan
change or retry was attempted. Exact Polygon trade-level reconciliation remains
blocked under existing access.

Other discrepancies remain: October 8 Moomoo minute volume totaled 106,190,121
versus 106,180,003 for five-minute candles; extended minutes totaled 118,707,239
versus daily 118,697,435. Thus native five-minute/daily volume is not the exact
sum of the returned minute series. Eligibility, revisions and aggregation
rules remain possible explanations, not verified causes.

## Limits and implications

The sampled epochs/DST offsets are internally consistent. Interval-end labels
have stronger empirical support, while official field units, half-days, other
intervals, symbols and option DST behavior remain unconfirmed. Event time,
candle label, exchange/SIP time and arrival time are distinct; a finalized
historical candle does not establish when its values became available.

Moomoo historical request RTTs were 201.707–498.211 ms; Alpaca 37.140–183.932 ms;
successful Polygon reads 190.845–196.940 ms. These few request round trips are
not exchange freshness, publication lag or sustained performance measurements.

Current metric sources remain unchanged. A later replacement study could retain
source provenance and compare identical trade windows, adjustment/session rules,
boundary inclusion and candle availability before considering MFE/MAE or option
metrics. Minute high/low cannot resolve extrema before entry or after exit within
the same minute; matching full-session extrema is insufficient. The observed
auction relocation particularly matters for trades exited near 16:00.

Remaining vendor questions are the official direct-API interval-start/end rule;
`time_zone` units; closing/official/corrected-close inclusion; native interval
volume differences; and publication/revision timing. None were sent externally.
Market-hours publication testing remains deferred. No provider adapter or
production rollout is part of this investigation.

## Verification and local evidence

Seventeen offline temporary-helper cases passed, covering exact nanosecond
boundaries, distinct closing/official messages, decimal-string sizes, invalid
numeric inputs, DST conversion and a separate five-minute shift hypothesis.
A fixture initially caught rejected Polygon decimal strings; the temporary
helper was repaired. The live run had already executed, but Polygon returned
403 without a usable trade payload. Alpaca numeric sizes and candle results
were unaffected. No live rerun was needed or performed. The final helper hash
below identifies the repaired helper, not its pre-repair execution bytes.

| Temporary evidence | SHA-256 |
| --- | --- |
| `/private/tmp/moomoo-auction-time-study.py`, repaired | `bf82d7c2621250912db03da90dbaf47af03ac8c8134e2f7202dacf88a4554b38` |
| `/private/tmp/test_moomoo_auction_time_study.py` | `b9fb55a2d69f506108aac23302ac5916fb4777cc0e4720cdc1e5727e1a7a341e` |
| `/private/tmp/moomoo-auction-time-summary.json` | `848c2eff632cc9d9e93193d456fa02a9fdd7485b54481be2cca15b5ced639961` |

These are bounded local diagnostic artifacts, not a raw historical archive.
Only explanatory documentation changed in the repository. Documentation checks
and exact-head CI results are recorded in the PR; fixture passes do not establish
vendor semantics or market-hours delivery.
