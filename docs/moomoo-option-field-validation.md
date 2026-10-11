# Moomoo option fields versus existing sources and local formulas

Observed **2026-10-11, 02:04–02:07 America/New_York**, with markets closed.
This continues the [endpoint inventory](moomoo-endpoint-metric-map.md) and
[broader history comparison](moomoo-broader-history-options.md). Current feeds,
metric calculations, journal records and production configuration are unchanged.
Market-hours testing remains deferred.

## Scope and method

The study made **15 bounded market-data/time requests**: an initial 11-read
sample and a four-read field-type follow-up, totaling 13.433 seconds of active
execution. All returned HTTP 200; all 11 signed Moomoo reads returned
`ret_code=0`. Two reads were unsigned clocks, one was an Alpaca option-snapshot
batch and one a Tradier market-quote batch. There were no retries, pagination,
account/trading reads, paid activations or WebSocket connections.

The existing secure AppKey/Ed25519 files and baseline credentials were reused.
Each foreground probe retained the audited reader's HTTPS/path allowlist,
18-request ceiling, one-second request-start pacing, 15-second hard deadlines
and 2 MiB response bound. Total calls also remained below 18. Redirects,
inherited proxies and network logging were disabled. Only selected numeric
summaries and counts persisted; complete screens and history responses stayed
in memory. No app module, database, cache, job or real fill was loaded by the
diagnostic.

For each NVDA/SPY underlying, the first probe read static metadata, October 9
regular raw candles, an October 16 standard option chain and one 50-row option
screen. The screen explicitly requested price, midpoint, spread, sizes, volume,
OI, IV, Greeks, multiplier/share size and underlying fields. It selected the
closest available positive, uncrossed call and put to the sampled underlying
close among chain-validated October 16 contracts. SPY's selected put was $772:
this is a bounded screen selection, not an assertion that every nearer strike
was unavailable. Both pages reported more data; no next page was requested.

All four selected profiles independently returned lot/contract size 100. They
were standard roots, not adjusted contracts. Baseline requests reused the
configured Tradier production **market-data** host and Alpaca **indicative**
option feed. A successful quote request is not an account-state audit or proof
of a named Moomoo exchange license.

## Prices, sizes and open interest

| October 16 contract | Moomoo and Tradier bid / ask | Matched reported bid / ask size | Matched reported OI | Alpaca indicative bid / ask |
| --- | --- | --- | --- | --- |
| NVDA $230 call | 3.40 / 3.45 | 100 / 30 | 54,673 | 3.46 / 3.47 |
| NVDA $230 put | 3.90 / 3.95 | 1 / 5 | 21,207 | 3.95 / 3.98 |
| SPY $780 call | 3.59 / 3.61 | 41 / 42 | 20,909 | 3.62 / 3.65 |
| SPY $772 put | 1.79 / 1.80 | 40 / 88 | 15,109 | 1.81 / 1.82 |

**Moomoo sizes and OI were available.** They were decimal integer strings,
for example `"bid_volume":"100"`, `"open_interest":"54673"`. The initial
numeric-only parser rejected them even though its presence flags were true.
Thirty-six offline cases passed before the four-read follow-up, which safely
decoded all four contracts' bid/ask sizes, volume and OI. Prices and model fields
were unchanged across the two captures. OI and raw sizes matched Tradier exactly.
This is sampled field agreement, not an independent audit of true open interest.

The standalone history/options diagnostic now handles these quantity strings
with a bounded nonnegative int64 decoder. It rejects booleans, fractional or
exponent strings, arbitrary text, overflow and imprecise floating integers.
It retains missing values as unavailable and zero as zero. Price/IV/Greek
parsing, authentication, destinations and production providers are unchanged.
An invented offline fixture covers the returned field shape; no live quote
response is committed as a fixture.

The older diagnostic summaries' unavailable size/OI values cannot establish a
permission restriction. Their full raw responses were not retained, so this
study does not reconstruct the earlier wire shapes. It establishes current
sampled access and corrects the numeric-only interpretation.

Quantity fields remain **reported units**. The [Tradier quote guide](https://docs.tradier.com/docs/quotes)
uses generic size wording in hundreds, whereas the Moomoo screen describes best
bid/ask volume. This study did not independently reconcile physical size units;
it applied no shares/lots/contracts conversion. The [Alpaca snapshot reference](https://docs.alpaca.markets/us/reference/optionsnapshots)
describes indicative quotes as modified and trades as delayed. Its differing
prices and sizes therefore are not a reliable execution-price benchmark.
No OI value was established through the sampled Alpaca snapshot field mapping;
no separate OI endpoint was queried.

Moomoo returned underlying price/IV/HV under **`underlying`**, while the request
and one documentation example use **`underlying_info`**. The returned prices
matched the sampled October 9 closing anchors: NVDA **229.28**, SPY **778.57**.
The request/response parent names are not interchangeable in a response parser.
This correction affected the temporary research helper only; the existing
diagnostic does not consume those underlying fields.

## Units and timestamps

The current [option-screen schema](https://open.moomoo.com/api/quote/screening/option-screen)
describes divisions by 1e9 for prices/multipliers and 1e5 for Greeks/volatility,
but its examples contain already normalized numbers. The observed 3.40/3.45
prices and 100 multipliers matched existing sources directly. Applying another
1e9 division would break this agreement. Likewise, reported delta/gamma/theta/
vega were ordinary decimal values, not raw 1e5-scaled integers. No extra wire
division was applied. These observations are sample-specific, not a universal
normalization contract for every field/endpoint.

Moomoo IV was interpreted as a **percentage** and divided by 100 for the local
decimal-IV model input. Tradier/Alpaca IV values were used as reported decimals.
Absolute provider/model accuracy remains unestablished despite plausible scaling.

| Timing field | Actual result |
| --- | --- |
| Moomoo per-contract quote/Greek time | None of the diagnostic's known timestamp fields returned; no documented per-contract stamp established |
| Tradier quote/trade clocks | Epoch-millisecond fields returned; NVDA quotes near Friday 16:00 ET, SPY near 16:15 ET |
| Tradier Greek time | A stamp was present for all four, but had no explicit timezone offset; absolute age was not inferred |
| Alpaca quote/trade clocks | RFC3339 timestamps returned; no separate known Greek timestamp in the sampled object |
| Observed baseline quote/trade age | About 33.82–34.08 hours using the local receive clock, consistent with weekend snapshots |

Moomoo's missing quote/Greek clock prevents freshness or contemporaneity proof.
[Tradier's market-data guide](https://docs.tradier.com/docs/market-data) says
ORATS Greeks update hourly, separately from quotes. Source-event age is not
exchange-to-client latency, and close prices matching cannot establish that
the vendors' Greeks share the same as-of time.

## Local formula checks and common-input scenarios

The probe extracted only pure `_bs_price`, `implied_volatility`, `compute_greeks`
and `bs_gamma` function definitions from the current source using AST. It did
not import the [fill enricher](../backend/app/engine/enricher.py), whose module
initialization loads configuration and creates a cache directory, or the
[positioning module](../backend/app/engine/options_positioning.py). The CLI
explicitly refused unexpected `app` imports.

The local formula's units are delta/gamma per underlying-price change, theta
per day divided by 365, and vega per one percentage-point change in IV.
Independent central differences of price matched all four rounded Greeks
within **0.000001** for synthetic calls and puts. At S=K=100, T=1, r=0.05,
sigma=0.20, call/put prices were 10.450583572/5.573526022. Put-call parity
residual was zero and IV inversion recovered 0.20 within 0.000001. These checks
establish internal mathematical consistency, not a market valuation benchmark.

The provider comparison used one declared retrospective scenario: Friday
October 9 **16:00 ET**, each Moomoo underlying close, expiration October 16
**16:00 ET**, T=7/365.25, r=0.0372 from the selected local baseline/default,
zero dividend yield and European Black-Scholes. This matches the fill formula's
time convention. The four contracts report American exercise; early exercise,
dividends, actual settlement rules, quote times and vendor volatility surfaces
are outside this scenario. SPY quotes after 16:00 are another temporal confound.
No current or historical fill metric was recomputed.

| Contract | Moomoo IV % | Tradier IV % | Alpaca IV % | Local IV fitting Moomoo/Tradier mid % |
| --- | --- | --- | --- | --- |
| NVDA $230 call | 32.601 | 29.080 | 34.820 | 29.157519 |
| NVDA $230 put | 31.929 | 28.640 | 34.370 | 28.714261 |
| SPY $780 call | 10.458 | 9.370 | 11.330 | 9.348328 |
| SPY $772 put | 11.624 | 10.420 | 12.330 | 10.476978 |

Identical Moomoo/Tradier mids necessarily yielded identical fitted IV under
the same local assumptions. Maximum reprice residual across all 12 vendor-mid
fits was **0.000003588**. This does not make the fit a true historical IV.

For example, NVDA-call Moomoo delta/gamma/theta/vega were
0.48354/0.04298/−0.35742/0.11336. At its reported IV, the local seven-day
scenario returned 0.487592/0.038534/−0.305931/0.126567. The difference was not
removed by inventing an undocumented scaling factor or vendor input.
The current positioning gamma uses a separate r=0/q=0/365-day convention;
its scenario value was also retained, without changing either engine.
Rho was returned by vendors but is not produced by the selected local Greek
routine, so it was not locally validated.

A conditional consistency calculation supplied another diagnostic:
under BSM gamma/vega identities, decimal IV and vega per percentage point,
effective T in years equals `100 * vega / (S² * IV * gamma)`. Converting that
to 365.25-day years gave **5.599–5.632 days for Moomoo**, **6.937–7.117 for
Tradier**, and **5.000–5.007 for Alpaca** across the four rows. These differ
from a shared seven-day input, making maturity/model/clock conventions plausible
contributors to the differences. This is an inferred consistency diagnostic,
not a verified vendor clock, model formula, or market-accuracy ranking.

## Conclusion and verification

Moomoo provides usable prices, raw sizes, OI and model fields for these standard
contracts. Its quote fields matched Tradier numerically, but incomplete clocks,
unverified size conventions and differing model inputs prevent a superiority
claim. Current feeds, saved Greeks, MFE/MAE and pricing calculations remain in
place. The decoder repair affects only the manual standalone diagnostic, which
is not registered with FastAPI or used as an application provider.

There were 25 temporary offline cases before the initial probe, 36 before the
quantity follow-up and **38** after the final container/conditional-time checks.
The existing plus new committed diagnostic fixtures passed **121 tests**.
The first probe's numeric-only output is superseded for quantities and underlying
container interpretation; its prices and model values were reproduced unchanged.
The final helper hash below identifies the repaired research helper, not the
initial execution bytes. No full probe was rerun. Provider outputs are bounded
temporary evidence, not a historical archive or an as-of research dataset.

The official screen-page HTML SHA-256 was
`318d8a7704c8b87176d71aa747829d38f03adcc72feacd5969faffd12eec24ac`.
Formula-source hashes were `e34b1b4c7f7afd53f68e93d12928b561f5b8a7a792663b174b8e225271e568e1`
for `enricher.py` and `21633f729312679aa5a10971c152213b9c2d4545b9783753b2d7d2043ab7edf7`
for `options_positioning.py`.

| Temporary artifact under `/private/tmp/` | SHA-256 |
| --- | --- |
| Repaired `moomoo-option-fields-study.py` | `a1bc1bf2b0bc9d11af3a93c2cc71d3d79914ba3b7bfb09e3814eec116870c6a0` |
| `test_moomoo_option_fields_study.py` | `7947297d9a162c0ab03c383392b0044deb05bafc50c8e0377b3297c5b98a7ef9` |
| Initial `moomoo-option-fields-summary.json` | `0a0d67ba0dbc3d6d3ac7274a02b11237973c201fa6ffbabe533b7eb73d76f015` |
| `moomoo-option-quantity-followup.py` | `f854dbd9ecdb29d3a0f7272e60d80db3add2f628c5c60f9eae94d3135673f59a` |
| `moomoo-option-quantity-followup-summary.json` | `f8ac1b2c333c63dcaab7a0100918fbffe0aa5ec296ebcfe6029d0819b14a362a` |
| `moomoo-option-fields-analysis.json` | `935314415f94b7cf56a9976f09f576d523a211c6d6579afb9bde2299e9dcfdef` |

Review, full verification and exact-head CI evidence are recorded in the PR.
No production deployment, provider adapter or market-hours test was performed.
