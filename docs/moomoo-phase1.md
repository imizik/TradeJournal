# moomoo Phase 1: isolated market-data diagnostic

## Scope and status

Observed on **2026-10-10, 16:32–16:33 America/New_York**, with US markets
closed. This is a manually invoked diagnostic, not a provider adapter. It has
no FastAPI registration, database access, background task, trading call or
brokerage-account query. Tradier/Alpaca feeds and deployment are unchanged.
There were two bounded trials, each with one server-time call, one signed
US.NVDA quote request and one signed US.NVDA order-book request. No streaming,
continuous collection, subscription purchase or quota-exhaustion test occurred.
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
| WebSocket | Not attempted: official AppKey signing payload unresolved |
| Quota/rate-limit response headers | No numeric allowance headers observed |

These are snapshot counts, not a measured entitlement ceiling. The two-book
shape is consistent with US LV3 in the [direct order-book reference], but no
explicit tier metadata was returned. ARCA multi-level access is established;
NASDAQ TotalView depth is not established by an empty NASDAQ book. Neither
the book identifiers nor the quote proves consolidated depth or SIP/NBBO.
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

## Commands

From the repository's `backend` directory, using a Python environment with the
existing backend dependencies (`httpx`, `cryptography` via `PyJWT[crypto]`):

```bash
python -m scripts.moomoo_diagnostic --configure
python -m scripts.moomoo_diagnostic
python -m pytest tests/test_moomoo_diagnostic.py -q
```

`--configure` prompts through `getpass`, writes exclusively outside Git, and
refuses overwrites. The probe rejects insecure/symlinked credential files,
does not inherit proxies or follow redirects, sends no retries, and closes
its HTTP client. It prints only allowlisted fields and at most two samples
per book side; it never prints provider error messages, credentials or signed
headers. HTTP 401/403/429 and timestamp refusal stop subsequent requests.
Exit 0 means both REST schemas succeeded, not that streaming or permissions
were fully established.

For a future market-hours **snapshot** test, invoke the same manual command.
To track the requested streaming proof, this command currently exits 2 and
reports the signing blocker without reading credentials or opening a socket:

```bash
python -m scripts.moomoo_diagnostic --stream-seconds 30
```

There is deliberately no executable streaming implementation to bypass that
blocker. Once official signing rules are supplied, implement a bounded 30s
trial with auth acknowledgment, quote/order_book/ticker subscription results,
message counts, exchange timestamps, quota metadata if exposed, unsubscribe
acknowledgment and connection close. That is a Phase 1 follow-up, not permission
to build an adapter. A market-open trial is needed to verify NASDAQ levels and
data freshness; Saturday silence would not prove a subscription failure.

## Permissions and restrictions

| Question | Verified or unresolved |
| --- | --- |
| Actual accessible depth | ARCA 6 bid / 20 ask in both trials; NASDAQ empty. No `num` supplied, so the gateway was asked for the permission-based default maximum. Available liquidity can be less than the limit. |
| Nasdaq TotalView / ArcaBook | Exchange labels establish venue books, not named-product licensing. The [legacy quota reference] links US LV3 to Nasdaq Basic + TotalView + NYSE ArcaBook, including a promotion and Arca non-professional evaluation. It does not prove this direct-AppKey account's current rights. |
| Consolidated vs top-of-book | Multi-level ARCA observed; no consolidated-depth evidence. Quote completeness and NBBO unverified. |
| Concurrent subscriptions/connections | Unknown. The [direct push quotas] explicitly avoid fixed numbers and count at account level, generally by symbol + type. Other devices may consume quota. No load/exhaustion probe performed. |
| REST and control-message limits | Unknown numeric limits. [Direct REST limits] explain batching/backoff, not fixed rates; no numeric rate headers returned here. Legacy OpenD quotas must not be transferred to this API. |
| Available book fields | Observed exchange, flags, price, volume, order_count, precision and server-dispatch timestamps. Sampled order_count=0 does not prove zero resting orders; the docs say unavailable counts may be 0. Volumes are raw; physical size is volume / 10^precision. |
| Extra streaming fields | [Push schema] documents optional mpid and batched ticker sequence/time fields. No actual availability established without streaming. |
| Historical Level 2 | No historical-depth endpoint found in the current direct reference. Historical K-lines are not historical books. Vendor confirmation is still needed. |
| Recording live depth for private ML | **Permission not established.** [Moomoo terms] limit market-data use and redistribution, incorporate provider conditions, and allow additional broker agreements. They do not explicitly authorize this proposed retention/non-display ML workflow. Obtain written clarification for the applicable account/API/exchange terms before enabling recording. |

Useful questions for moomoo support or the developer dashboard:

1. What exact method, path, query, body hash, nonce inclusion and byte encoding
   form the AppKey quote-WebSocket signing payload? Ask for an official Python
   example/test vector for initial auth and refresh at
   `wss://webapi-quote.moomoo.com/ws`.
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
chart feeds, after completing the streaming and licensing proof. A future
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

[getting-started reference]: https://open.moomoo.com/api/overview/getting-started
[direct order-book reference]: https://open.moomoo.com/api/quote/realtime/order-book
[direct push quotas]: https://open.moomoo.com/api/quote/push/rate-limit
[Direct REST limits]: https://open.moomoo.com/api/overview/rate-limit
[Push schema]: https://open.moomoo.com/api/quote/push/data-format
[legacy quota reference]: https://openapi.moomoo.com/moomoo-api-doc/en/intro/authority.html
[Moomoo terms]: https://www.moomoo.com/terms
