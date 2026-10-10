# moomoo Phase 1: isolated market-data diagnostic

## Scope and status

Observed on **2026-10-10, 16:32–16:53 America/New_York**, with US markets
closed. This is a manually invoked diagnostic, not a provider adapter. It has
no FastAPI registration, database access, background task, trading call or
brokerage-account query. Tradier/Alpaca feeds and deployment are unchanged.
There were two bounded trials, each with one server-time call, one signed
US.NVDA quote request and one signed US.NVDA order-book request. Four bounded
WebSocket trials followed: two stopped on acknowledgment-envelope mismatch,
then two completed 30-second probes with exact wrapped-ID correlation.
After review found the library's default redirect behavior, a final 5-second
probe confirmed the redirect-refusing connection factory still authenticated,
acknowledged all subscriptions/unsubscribe and closed (5.147s elapsed).
No continuous collection, subscription purchase or quota-exhaustion test occurred.
Live prices are not stored in this repository; test fixtures are invented.

| Test | Observed result |
| --- | --- |
| Ed25519 AppKey REST authentication | Both market endpoints returned HTTP 200, `ret_code=0` |
| Stock quote | US.NVDA returned; `data_time=1791576000000`, Friday 2026-10-09 16:00 ET |
| NASDAQ book | Exchange identifier present, zero bid and ask levels, both valid flags 1 |
| ARCA book | 6 valid bid levels and 20 valid ask levels; precision 0; sampled order counts 0 |
| Book freshness | Both `exchange_data_time_ms=0`; exchange age and provider processing delay cannot be measured |
| REST quote round trip | 348.907 ms first trial; 341.138 ms second trial |
| REST book round trip | 319.375 ms first trial; 330.896 ms second trial |
| WebSocket authentication | Succeeded with the official Chinese four-field signature |
| Separate stream subscriptions | quote, order_book and ticker each acknowledged `code=0` |
| Final 30s delivery | 1 QUOTE, 4 ORDER_BOOK, 0 TICKER messages; some book messages omitted both lists |
| Streaming depth | One complete observed book had 60 valid entries and 60 distinct prices per side; sampled MPIDs and collected MPID set were ARCA, with no book-level exchange identifier |
| Unsubscribe and close | Exact-ID unsubscribe acknowledged `code=0`; closed; final elapsed 30.075s |
| Quota/rate-limit response headers | No numeric allowance headers observed |

These are snapshot counts, not a measured entitlement ceiling. The two-book
shape is consistent with US LV3 in the [direct order-book reference], but no
explicit tier metadata was returned. ARCA multi-level access is established;
NASDAQ TotalView depth is not established by an empty NASDAQ book. Neither
the book identifiers nor the quote proves consolidated depth or SIP/NBBO.
Streaming establishes 60 distinct prices per side in one observed ARCA-MPID
book; its shape differs from the REST snapshot. The REST book's 6/20 counts
must not be treated as a streaming limit. MPIDs identify reported participants;
do not infer coverage of other venues or a named license from them alone.
Moomoo's LV3 naming does not establish an order-by-order Level 3 event feed:
the documented response aggregates price levels.

## Authentication and local storage

The [getting-started reference] supports Ed25519 and RSA-SHA256 for AppKeys.
This diagnostic uses Ed25519 only. The private key is PKCS#8 PEM and the
uploaded public key is SubjectPublicKeyInfo PEM. Key material and the AppKey
are outside Git in `~/.config/tradejournal/moomoo/`: directory mode 0700,
private key and AppKey mode 0600. The dashboard is configured manually for
Market Quote only. The diagnostic cannot sign trading or account paths.
Successful quote calls do not independently prove that other dashboard
permissions are disabled. Whitelist configuration remains dashboard-managed;
restrict it to the diagnostic machine's outbound public IP if available.

REST signs five newline-separated fields:

```text
timestamp_ms
UPPERCASE_HTTP_METHOD
request_path_without_host_or_query
raw_final_query_string
lowercase_sha256_of_exact_body_bytes_or_empty
```

Ed25519 signs those UTF-8 bytes directly, then Base64 encodes the signature.
Headers are `X-Api-Key`, `X-Timestamp`, `X-Nonce`, and `Authorization` with
the signature alone. The nonce is not an extra signing field in the current
REST documentation. Query ordering, percent encoding and body whitespace
must match the sent request exactly. The diagnostic builds the HTTP request
before signing its bytes. It does not send the internal `X-Futu-Client-Nnid`
header shown in some endpoint examples. Those examples are not the public
AppKey authentication contract.

The unauthenticated server-time endpoint provides one midpoint clock estimate
for signing and freshness calculations. First trial estimated server minus
local clock was +206.402 ms with 421.950 ms RTT; second was +81.017 ms with
190.456 ms RTT. Asymmetric network delay and server clock behavior are unknown.
Second-trial estimated server-dispatch-to-receive was 86.017 ms NASDAQ and
84.017 ms ARCA, with roughly 95 ms half-RTT uncertainty from clock sampling
alone. This is not an exchange-to-client latency measurement. Freshness at
the exchange remains unavailable. Quote age was about 24 hours 33 minutes,
consistent with Friday's closing timestamp during Saturday testing.

The final streaming quote had `data_time_ms=1791579600046`, Friday 17:00 ET,
about 23h48m old. The first complete streaming book had
`data_time_ms=1791665244414`, received locally at `1791665264351`, estimated
timestamp age 19,955.821 ms. A later book message with no bid/ask lists had
timestamp age 202.821 ms. This measures provider-reported message timestamp
age, not verified exchange freshness or liquidity change. The prior successful
30s trial observed two complete books with timestamp ages 4,273.290 and
174.290 ms. Market-hours delivery and clock/freshness behavior still need proof.

## Commands

From the repository's `backend` directory, using a Python environment with the
existing backend dependencies (`httpx`, `cryptography` via `PyJWT[crypto]`):

```bash
python -m scripts.moomoo_diagnostic --configure
python -m scripts.moomoo_diagnostic
python -m pytest tests/test_moomoo_diagnostic.py -q
```

`--configure` prompts through `getpass`, refuses echo fallback, writes exclusively outside Git, and
refuses overwrites. The probe rejects insecure/symlinked credential files,
does not inherit proxies or follow redirects, sends no retries, and closes
its HTTP client. It prints only allowlisted fields and at most two samples
per book side; it never prints provider error messages, credentials or signed
headers. HTTP 401/403/429 and timestamp refusal stop subsequent requests.
Exit 0 means both REST schemas succeeded, not that streaming or permissions
were fully established.

For a future market-hours snapshot test, invoke the same manual command.
For a bounded streaming test:

```bash
python -m scripts.moomoo_diagnostic --stream-seconds 30
```

The [official Chinese auth reference] and traditional-Chinese version supply
the detail omitted by the current [English auth reference]:

```text
{timestamp_ms}\n{nonce}\nWEBSOCKET\nws/auth
```

These are four UTF-8 fields, no trailing newline, signed directly with Ed25519
and Base64 encoded. The REST body hash and method/path format are not reused.
The English auth frame and [subscription reference] are otherwise followed.
The actual gateway wraps control acknowledgments as
`{"ret_code":0,"data":{"id":"sub-quote","code":0,"message":""}}`.
The diagnostic checks the exact ID inside that envelope, not merely outer
success. It subscribes to each type separately, preserving distinct results.
Failed/unknown auth never subscribes, and no retries or alternate signatures
are attempted. Unknown controls are summarized without copying arbitrary
provider strings or session identifiers.

The probe uses protocol ping/pong, no custom JSON heartbeat, and a capture
duration of 1–60 seconds with bounded cleanup. It cannot be used as a
long-lived collector. This is below the documented ten-minute auth-refresh
limit; the recommended five-minute refresh cycle is unnecessary here. A
future long-lived implementation must generate a fresh timestamp/nonce and
signature for refresh on that cycle; extending this diagnostic is not
authorization for background collection.

A market-open trial is still needed to verify NASDAQ levels, ticker delivery
and freshness. Saturday ticker silence is not a subscription failure. A book
message omitting lists is recorded as unavailable, not interpreted as an empty
book deletion or blindly merged as a delta. Full-snapshot/delta semantics
remain a vendor clarification before production integration.

## Permissions and restrictions

| Question | Verified or unresolved |
| --- | --- |
| Actual accessible depth | REST ARCA 6 bid / 20 ask, NASDAQ empty; streaming book 60 distinct valid prices per side with ARCA MPIDs. REST `num` omitted to request the permission-based default maximum. Available liquidity can be less than the limit. |
| Nasdaq TotalView / ArcaBook | Exchange labels establish venue books, not named-product licensing. The [legacy quota reference] links US LV3 to Nasdaq Basic + TotalView + NYSE ArcaBook, including a promotion and Arca non-professional evaluation. It does not prove this direct-AppKey account's current rights. |
| Consolidated vs top-of-book | Multi-level ARCA observed; no consolidated-depth evidence. Quote completeness and NBBO unverified. |
| Concurrent subscriptions/connections | One connection and all three US.NVDA types accepted concurrently. Maximum unknown. The [direct push quotas] avoid fixed numbers and count at account level, generally by symbol + type. Other devices may consume quota. No load/exhaustion probe performed. |
| REST and control-message limits | Unknown numeric limits. [Direct REST limits] explain batching/backoff, not fixed rates; no numeric rate headers returned here. Legacy OpenD quotas must not be transferred to this API. |
| Available book fields | Observed exchange, flags, price, volume, order_count, precision and server-dispatch timestamps. Sampled order_count=0 does not prove zero resting orders; the docs say unavailable counts may be 0. Volumes are raw; physical size is volume / 10^precision. |
| Extra streaming fields | Stream books actually returned price, volume, nonzero order_count and ARCA mpid. Precision/book-level exchange omitted. Ticker sequence/time availability remains unobserved because no ticker messages arrived. |
| Historical Level 2 | No historical-depth endpoint found in the current direct reference. Historical K-lines are not historical books. Vendor confirmation is still needed. |
| Recording live depth for private ML | **Permission not established.** [Moomoo terms] limit market-data use and redistribution, incorporate provider conditions, and allow additional broker agreements. They do not explicitly authorize this proposed retention/non-display ML workflow. Obtain written clarification for the applicable account/API/exchange terms before enabling recording. |

Useful questions for moomoo support or the developer dashboard:

1. Can the English auth docs include the Chinese four-field signature? Confirm
   the gateway acknowledgment envelope and whether ORDER_BOOK messages that
   omit lists are partial updates; clarify timestamp/venue/volume semantics.
2. What US **direct API** quote tier and named products are active for this
   AppKey? Does that include TotalView and ArcaBook, and what is the maximum
   price-level count per venue? Is an evaluation/activation still required?
3. What are this account's concurrent connections/subscriptions, counting
   rules, REST endpoint rates and WebSocket control-message limits?
4. Is private, local retention of live depth for later personal non-display
   ML/backtesting allowed? What retention, derived-data, cloud processing,
   display, redistribution and deletion conditions apply? Is historical
   depth available through any approved API or licensed product?

No messages were sent to moomoo. No paid services were enabled.

## Future integration recommendation (approval required)

Use moomoo initially as an optional depth source alongside the established
chart feeds, after completing market-hours freshness and licensing proof. A future
low-level client would follow `backend/app/engine/tradier.py` and
`backend/app/engine/alpaca.py` conventions: bounded reads, provider errors,
explicit timestamps and provenance. Keep credentials local to the backend.
Depth normalization should retain the venue, precision, source/receive
timestamps, quality flags and observed coverage rather than flattening it into
an apparent consolidated book.

The current chart integration is split between `chart_feed.py` (bounded
Tradier REST), `chart_history.py` (Alpaca SIP/raw historical sessions), and
`chart_stream.py` (one demand-driven Tradier connection with fan-out). A
separate, demand-driven depth stream should use the same fan-out pattern,
subscribe to the visible symbol only, coalesce UI updates and release quota
when unused. It should not change these chart price or history sources merely
because depth is available.

Potential approved follow-ups:

1. **Overlays and heatmaps:** display venue-specific ladders and sampled
   liquidity over time. Clearly label depth coverage and stale/unavailable
   timestamps. A two-venue book is not the entire US market. Keep raw depth on
   its as-of price basis; convert copies to the chart's split-adjusted basis
   where needed, preserving the source records.
2. **Imbalance/liquidity research:** derive equal-depth or fixed-price-band
   bid/ask size imbalance separately per venue, with consistent units and
   missing-side handling. Record spread, concentration and trade-flow context.
   Snapshot changes cannot uniquely identify cancellations or order-level
   behavior; zero order counts do not establish queue position.
3. **Historical Workbench pipeline:** after explicit recording rights and new
   collection approval, retain bounded/session-scoped books and ticks in a
   separate versioned dataset, with receive/source clocks, gaps, precision,
   session/calendar metadata and reconnect provenance. Confirm whether pushes
   are full snapshots or deltas before designing replay. Historical bar APIs
   cannot reconstruct Level 2. Newly collected depth starts a new forward
   research dataset; it cannot populate the factory's 2023–2024 discovery
   period. Preserve Workbench discovery/confirmation boundaries and keep
   research data separate from journal fills and paper activity.

No adapter, chart UI or collection pipeline is included in Phase 1.

## Validation and review limits

The final diagnostic has 50 passing offline tests, including frozen WebSocket
signature bytes, authentication failures/timeouts, wrapped and per-type
acknowledgments, unsubscribe failures, absent lists and redirect refusal.
Together with documentation links, 119 tests pass. Changed-file lint passes.
Independent reviews identified and the owner fixed unsafe getpass fallback,
continuation after server-time refusals, and WebSocket handshake redirects.
The redirect guard's live 5-second trial succeeded without changing the
signing format. Final independent re-review of that guard remains pending:
three review rounds have been used, and additional rounds require explicit
authorization under `docs/agent/pr-review.md`.

The first full verification attempts encountered sandbox socket-bind failures
and an external dependency-symlink build restriction. All 27 offline socket
tests passed outside the sandbox, and locked frontend dependencies were
installed locally for the final full verification. `bash scripts/verify.sh`
then passed every local check: 2,171 backend tests (35 skipped), lint, import
boundaries, frontend type/lint/build, and 225 browser tests (200 general,
5 authenticated, 20 sample-decision). That run began on `0ea7ece`; the later
redirect correction was separately validated by the 50 diagnostic tests and
5-second live trial, reusing the unaffected application checks. No CI ran.
No ready-to-publish or
production-acceptance claim is made. The branch is local; automatic approval
review rejected publishing it to the remote. No PR was created.

[getting-started reference]: https://open.moomoo.com/api/overview/getting-started
[direct order-book reference]: https://open.moomoo.com/api/quote/realtime/order-book
[direct push quotas]: https://open.moomoo.com/api/quote/push/rate-limit
[Direct REST limits]: https://open.moomoo.com/api/overview/rate-limit
[Push schema]: https://open.moomoo.com/api/quote/push/data-format
[legacy quota reference]: https://openapi.moomoo.com/moomoo-api-doc/en/intro/authority.html
[Moomoo terms]: https://www.moomoo.com/terms
[official Chinese auth reference]: https://open.moomoo.com/zh-cn/api/quote/push/auth
[English auth reference]: https://open.moomoo.com/api/quote/push/auth
[subscription reference]: https://open.moomoo.com/api/quote/push/subscribe
