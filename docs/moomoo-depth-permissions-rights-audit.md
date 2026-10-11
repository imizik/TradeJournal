# Moomoo depth permissions and usage-rights audit

Audited **2026-10-11** using public official documentation, the owner's quoted
developer-dashboard label and the existing bounded Phase 1 evidence. There were
**no new market-data, account, billing or trading API requests**, WebSocket
connections, entitlement activations or vendor messages. Current feeds, saved
metrics, production configuration and recording behavior remain unchanged.
Market-hours testing is deferred.

## Outcome

| Question | Evidence established | Still unresolved |
| --- | --- | --- |
| Exchange coverage | Earlier NVDA REST response identified NASDAQ and ARCA books; ARCA had 6 bid/20 ask levels. Earlier stream had 60 distinct prices per side with ARCA MPIDs. | Populated Nasdaq depth, named TotalView/ArcaBook licenses, other symbols/venues, live completeness and freshness. |
| Quote tier | Direct documentation associates multi-exchange NASDAQ/ARCA book structure with US LV3 and supports a 1–60 `num` parameter. The previous response is compatible with that representation. | No explicit account-tier/product entitlement was returned; response shape is not a license confirmation. |
| Concurrent quotas | One connection and quote/order_book/ticker subscriptions for NVDA were previously acknowledged. Public direct documentation describes account-level counting. | Numeric connection/subscription ceilings, exact counting for this account, REST/control rates and quota used by other devices. |
| Private depth retention and ML | Public broker/exchange terms make usage scope contractual; a personal or nonprofessional designation does not establish the proposed workflow's rights. | Applicable accepted API/exchange agreement, raw retention period, private model-training permission, derived/model retention, third-party/cloud processing and any fees. |

**Private ML recording permission is not established.** This is an evidence
gap, not a finding that all personal recording is prohibited or necessarily
requires paid subscriptions. Successful reads demonstrate technical access;
they do not supply a separate storage/training license.

## Account-specific evidence

The owner reported that the developer dashboard shows only **Market Quote**,
with a description of real-time quotes, historical candlesticks and core market
data. That identifies a broad AppKey capability category. The supplied text
does not name depth products, expiry dates, numeric quotas or data-use terms.
No additional entitlement screen, signed agreement or subscriber classification
was inspected. No account balance or brokerage-account endpoint was queried.

The [existing Phase 1 report](moomoo-phase1.md) supplies the earlier observed
depth and acknowledgment evidence. This audit did not refresh those snapshots;
continued availability or changed promotions cannot be inferred from them.
Funded-account status is not a substitute for API entitlement evidence.

## Exchange coverage and depth meaning

The current [direct book reference](https://open.moomoo.com/api/quote/realtime/order-book)
describes separate NASDAQ/ARCA books for US LV3. Omitting `num` requests the
permission-dependent maximum; fewer occupied price levels may be returned.
It reports price, aggregate volume, order count, volume precision and timestamps,
with counts potentially unavailable. These are price-level summaries; no raw
order-event identifier or complete exchange order-event stream was established.
Moomoo's LV3 tier name is not proof of market-by-order or queue-position data.

| Product/interpretation | Official product scope | This account's evidence |
| --- | --- | --- |
| [Nasdaq TotalView](https://www.nasdaq.com/products/data/equities/nasdaq-totalview) | Displayed Nasdaq book for securities trading on Nasdaq, including securities listed elsewhere. | NASDAQ label was present but its sampled lists were empty; no populated TotalView depth or product license proved. |
| [NYSE ArcaBook](https://www.nyse.com/data-products/catalog/arcabook) | NYSE Arca's limit order book for securities traded there. | Nonempty REST ARCA-labelled depth observed; actual named license/expiry unconfirmed. |
| Consolidated depth / NBBO | Venue books and cross-venue consolidated quotations are different data products. | No complete cross-venue depth or verified consolidated NBBO established. Combining two venue books would not establish all-market coverage. |
| Top of book | Best displayed prices of a particular book. | Multiple ARCA price levels were observed, so that sample exceeded top of book. Full coverage was not established. |

Listing venue and execution venue differ: an NYSE-listed security in TotalView
does not imply that TotalView contains the NYSE execution book. Stream `mpid`
values are not substitutes for an explicit book-level exchange identifier or a
product entitlement. Exchange timestamps were zero in the earlier REST sample;
exchange freshness remains unknown.

The [legacy OpenD authority guide](https://openapi.moomoo.com/moomoo-api-doc/en/intro/authority.html)
describes a promotional US LV3 bundle of Nasdaq Basic, TotalView and ArcaBook,
with a nonprofessional evaluation for ArcaBook. That is useful product context,
not proof of this direct-AppKey account's current promotion or agreements. Its
numeric quotas and endpoint rates were not transferred to the direct API.
No OpenD session, quote card, questionnaire or subscription was activated.

## Subscription and rate quotas

The [direct push quota reference](https://open.moomoo.com/api/quote/push/rate-limit)
explicitly omits fixed numeric ceilings. Subscription items are usually
symbol + data type; K-lines may also include period/adjustment. Connections and
devices can share account allowances. The internal `uid_total_quota` is not a
client-provided field. Code 4 can indicate exhausted subscription quota, with
gateway wrappers/translations possible. Successful unsubscribe releases its
item, while another connection may still hold it. These rules do not establish
this account's exact counting or numerical allowance.

The observed one-symbol/three-type success is an accepted configuration, not
an exhaustion test or a measurement of three billable quota units. The direct
[REST limit page](https://open.moomoo.com/api/overview/rate-limit) describes
batching/backoff but supplies no fixed endpoint rate. Its example batch size is
not a subscription ceiling. No numeric limit was obtained from prior Moomoo
rate headers. No quota getter was established in the reviewed direct quote
reference, and no account/trading endpoint or guessed API path was tried.

## Storage, non-display and ML rights

The retrieved [public moomoo terms](https://www.moomoo.com/terms) include personal
use limited to authorized activities, provider-specific conditions and
redistribution restrictions; broker agreements can add controlling terms.
They do not explicitly grant this proposed recording/training workflow. The
page includes regional/contractual content, so it is not evidence of which
version or agreement this account accepted.

The [US agreement index](https://www.moomoo.com/us/support/categories/2427?from_platform=1)
links the June 22, 2026 Moomoo Financial Inc. customer agreement. Its section
14.7 discusses informational/educational market data and accuracy/timeliness
limitations, not an explicit depth-storage or ML-training license. The relevant
broker entity and accepted account/API agreements remain unverified. Marketing
references to quantitative/API use cannot settle exchange usage rights.

NYSE's currently linked
[comprehensive policy package](https://www.nyse.com/publicdocs/nyse/data/NYSE_Proprietary_Market_Data_Comprehensive_Policy_Package.pdf)
is version 2.3, March 21, 2022. Sections 2.1–2.3 define non-display processing
and include investment analysis; declaration/licensing conditions are described
separately. Private offline ML analysis may implicate those rules, but this
account's classification, exemptions and pass-through terms were not established.
The separately retrieved older
[historical-use policy](https://www.nyse.com/publicdocs/nyse/data/NYSE_Market_Data_Complete_Policy_Package.pdf),
page 8, allows internal later storage/use by vendors and separately restricts
external historical redistribution. It is not a retail subscriber grant and
does not settle private ML rights. The current policies index's historical-use
link resolves to `/publicdocs/nyse/data/.pdf`; the older package was therefore
treated as context, not a confirmed current replacement.

### Nasdaq policy version gap

The readily available [Nasdaq AI PDF](https://www.nasdaqtrader.com/content/AdministrationSupport/AgreementsData/Data_AI_Policy.pdf)
reports version 1.0, February 5, 2025. It ties AI training, third-party tools,
storage/model retention and derived-data use to licensed scope, with possible
additional licensing. However, Nasdaq's
[June 2, 2026 notice](https://nasdaqtrader.com/TraderNews.aspx?id=DN2026-4)
announces an AI-policy clarification effective on publication, alongside GDA
5.1 effective September 1, 2026. Its current-policy hub link returned 404; an
alternate official policy listing could not be retrieved. The 2025 PDF is
**not treated as the authoritative current grant or prohibition**. The effective
revised policy and its applicability need confirmation. This version gap is a
material audit limitation.

No blanket prohibition or personal ML exemption was inferred. Open-source
software libraries, privately trained models, publicly distributed models and
third-party AI services are different uses whose exact treatment needs the
applicable license. Waiting until data is old, retaining derived features only,
or keeping everything on a personal computer does not itself establish rights.
No raw depth dataset was uploaded and no model training occurred in this audit;
only public policies and existing bounded diagnostic summaries were reviewed.

## Prepared clarification request — not sent

This can be supplied to [moomoo support](https://www.moomoo.com/us/support).
It contains no credentials or account identifiers:

> I use the direct REST + quote WebSocket AppKey API with Market Quote only.
> Please confirm the US equity depth products active for this access, their
> venue coverage, depth caps, expiry dates and required subscriber classification.
> Please provide my numeric concurrent connection/subscription limits, exact
> symbol/type/K-line counting rules, cross-device sharing, REST endpoint rates
> and WebSocket control-message limits, with the applicable documentation.
>
> Is private local recording of live depth for later personal non-display
> research/backtesting and model training permitted under my existing access,
> without a new paid entitlement? Please identify the controlling API, broker
> and exchange agreements and effective AI-policy versions. Please specify raw
> and derived-data retention, model/weight retention, use after subscription
> expiry, backups/deletion, cloud processing and third-party AI conditions.
> Also distinguish local personal display/heatmaps from offline analysis and
> training. I am not requesting paid activation, trading access or redistribution.

Until those answers are available, named licenses, numerical quota ceilings and
private ML recording rights remain unresolved. This audit adds no authorization
for recording, ingestion, provider integration or feed/metric replacement.
Market-hours delivery and freshness verification remain a separate later test.

## Evidence and verification

Official public pages/PDFs were read on October 11. Original bytes and extracted
text are bounded temporary documentation artifacts, not market-data archives.
No credentials were needed or read for this audit. Documentation checks,
independent review and exact-head CI are recorded in the PR. No new offline
signing/response fixtures are warranted because executable behavior did not change.

| Public artifact under `/private/tmp/moomoo-depth-audit-…` | Original-byte SHA-256 |
| --- | --- |
| `rest-limit.html` | `743e94a572617d07fe36db5a9c534be1dd9fdb432dca30cf5e26e33defcaa984` |
| `push-limit.html` | `b604d2b114e64fc33a932be4411f1988be83169549f648e284b2cf9a706a43ab` |
| `book.html` | `afe059fcb5a710e88d6689c9f22eaa27ab59152bbd5d02009b0df880e08110a7` |
| `push-schema.html` | `f29b4a05947c44d88999efe4630dc1cb230d22d9cee320742a21799908d0fb44` |
| `quote-rights.html` | `c2642d940e476060beb007163042620e9cb347709bbeee491584f2c2f3dc7a39` |
| `terms.html` | `f6c085d4cdaa647e9072721cb9812970e282312f4057e717c6eba4363d9aa514` |
| `nasdaq-ai.pdf` (2025 version) | `18ef5190b4cb5b9bb519d04e0da326515c6aa8f7716ce82b61e580430854ab5c` |
| `nyse-comprehensive.pdf` | `17257854bf128b72f8c8b3f36f0f91bcb1a808ef39ae6a82bb2b67718c71bb48` |
| `nyse-historical-package.pdf` (older context) | `7e89f954b7ec5daadaf37feb45088f441cf92ee1c7a369df92190c30144f7a9a` |
| `mfi-agreement.pdf` | `114f7718f4d50b9df9f1970ca1a7f9d8da917bb33e2deb435a38fc5259d4fedf` |
