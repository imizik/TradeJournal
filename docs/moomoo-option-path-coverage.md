# Historical option coverage and hypothetical metric inputs

Observed **2026-10-11, 02:45–02:48 America/New_York**, with markets closed.
This follows the [field validation](moomoo-option-field-validation.md) and
[broader history comparison](moomoo-broader-history-options.md). Current feeds,
saved metrics, journal records and production configuration remain unchanged.
Market-hours streaming remains deferred.

## Result

Four recent standard-root NVDA/SPY contracts supplied comparable minute paths.
Across **18 hypothetical position windows**, the diagnostic minus-one-minute
Moomoo interpretation matched all **150 available metric fields** calculated
from Alpaca. Another **12 fields were unavailable in both sources** because
their observed total peak rounded to zero; these were not counted as matches.
The fields covered MFE/MAE, peak/worst open PnL, peak total PnL, giveback,
exit efficiency, giveback percentage and elapsed minutes to a positive peak.

Four older candidates had Alpaca history but no Moomoo profile. The remaining
four exact-code reads returned HTTP 200 / `ret_code=-7` from Moomoo. This is
an observed resolution failure, not proof of an archive cutoff or entitlement
restriction. The NVDA put's three additional recent Moomoo minutes had zero
volume; they did not establish extra traded-price coverage or alter the
sampled eligible-window metrics. **Keep Alpaca as the option-path source.**

## Bounded method and account scope

There were **18 foreground market-data/time reads**, totaling **16.376 seconds
of active execution**: an initial 14-read probe and four exact older-code reads.
All returned HTTP 200. Fourteen succeeded at the API level; four histories
returned the sanitized `-7` error. The breakdown was one unsigned clock,
one signed Moomoo profile batch, eight Alpaca histories, four successful recent
Moomoo histories and four unsuccessful older Moomoo histories.

The [manual study](../backend/scripts/moomoo_option_path_study.py) reuses the
existing secure AppKey/Ed25519 files and Alpaca credentials. It retains the
audited reader's HTTPS/path checks, 18-request ceiling, one-second request-start
spacing, 15-second hard deadlines, 2 MiB response bound, redirect refusal and
disabled inherited proxies/network logging. The follow-up used the remaining
four requests within the same aggregate ceiling. It used the established signer
with the local epoch clock; no extra clock, baseline request, retries, symbol
permutations or chain requests were made.

No paid subscription, account/billing/trading read, order, cache, database,
provider adapter, job or WebSocket ran. Raw bars stayed in memory; only bounded
numeric summaries and hypothetical fills persisted under `/private/tmp/`.
No real fills or journal records were loaded. Published
[no-additional-API-charge evidence](moomoo-timestamp-comparison.md#cost-evidence)
applies to the existing access; this was not a billing or entitlement audit.

The fixed candidates were chosen before the reads. Moomoo exact profiles had
to match code, `stock_owner`, `stock_type=DRVT`, and 100-share lot/contract
sizes before ordinary comparisons. The four older profiles were omitted from
the successful batch. Independently returned Alpaca bars then supported four
exact historical-code probes; they did not supply missing Moomoo metadata.
No adjusted root was tested and no premium multiplier was inferred from share
size. All hypothetical calculations use the existing code's **100 premium
conversion**, whose application to an unresolved or adjusted contract would
remain conditional. No older Moomoo result qualified for a metric comparison.

## Coverage

| Candidate/session | Moomoo shifted valid minutes | Alpaca valid minutes | Resolution/comparison result |
| --- | --- | --- | --- |
| NVDA Dec 19, 2025 $175 call; Dec 18 | unavailable | 390 | Profile omitted; exact history `-7`; no comparison |
| NVDA Dec 19, 2025 $175 put; Dec 18 | unavailable | 387 | Profile omitted; exact history `-7`; no comparison |
| NVDA Mar 20, 2026 $180 call; Mar 19 | unavailable | 390 | Profile omitted; exact history `-7`; no comparison |
| NVDA Mar 20, 2026 $180 put; Mar 19 | unavailable | 389 | Profile omitted; exact history `-7`; no comparison |
| NVDA Sep 18 $220 call; Sep 17 | 390 | 390 | 390 shared minutes; four hypothetical windows |
| NVDA Sep 18 $220 put; Sep 17 | 390 | 387 | 387 shared; three Moomoo-only zero-volume rows; four windows |
| SPY Oct 9 $774 call; Oct 8 | 405 | 405 | 405 shared minutes; five hypothetical windows |
| SPY Oct 9 $774 put; Oct 8 | 405 | 405 | 405 shared minutes; five hypothetical windows |

Moomoo requests used the session date through the following date, `ktype=1`,
`autype=0`, `num=370`, `extended_time=0`. Returned recent sessions nevertheless
contained 390/405 valid shifted rows, as in the earlier study. Alpaca requests
used `1Min`, 09:30 through 16:00 ET for NVDA and through 16:15 for SPY,
`limit=1000`, ascending sort and the endpoint default option feed, matching the
[current client](../backend/app/engine/alpaca.py). No feed selection changed.
The Alpaca [bar reference](https://docs.alpaca.markets/us/reference/optionbars)
documents inclusive end times and limits across symbols. This study requested
one symbol per read and applied a half-open session filter after parsing.

No next-page token or Moomoo `next_time` cursor was present in the sampled
histories; no page was followed. The parser counts and excludes invalid OHLC,
non-minute timestamps, duplicates and out-of-session rows. A missing clock
minute can mean no qualifying trade; it is not automatically data loss. Zero-
volume rows remain explicitly counted and have a separate positive-volume
sensitivity calculation. Moomoo reported volume precision zero. Physical volume
units were not independently reconciled and volume is not an input to these
path calculations.

The current [Moomoo history reference](https://open.moomoo.com/api/quote/basic-data/history-kline)
describes `-7` as `invalid_symbol`: the format is valid but the security is not
found in cache. The four sanitized protocol observations were:

| Requested Moomoo code | HTTP | `ret_code` | Result |
| --- | --- | --- | --- |
| `US.NVDA251219C175000` | 200 | -7 | API error; no bars or metrics |
| `US.NVDA251219P175000` | 200 | -7 | API error; no bars or metrics |
| `US.NVDA260320C180000` | 200 | -7 | API error; no bars or metrics |
| `US.NVDA260320P180000` | 200 | -7 | API error; no bars or metrics |

The corresponding Alpaca symbols use eight-digit strikes, e.g.
`NVDA251219C00175000`. Their returned bars establish sampled Alpaca availability;
they do not prove a Moomoo naming/retention contract. There was no alternate-code
search. September success and March/December resolution failures do not establish
the exact historical boundary or universal access for either provider.

## Hypothetical positions and metric agreement

The probe extracted only trusted pure `option_position_path`, `bars_to_df`
and `_f` definitions using AST, without importing application modules. It did
not invoke the [trade-path job](../backend/app/engine/trade_path.py), its cache
fetcher, model constructors or persistence. The entry/exit records were plain
in-memory objects and every provider calculation received the same records.

Each recent contract had these declared windows:

- Long morning: one contract, 09:45:20–10:45:40 ET.
- Short morning: one contract over the same window.
- Long afternoon: one contract, 14:00:20–15:45:40 ET.
- Scale-in/out: buy two at 09:45:20, buy one at 10:00:20, sell one at
  10:15:20, sell the remaining two at 10:45:40 ET.
- SPY only: one long contract, 16:00:20–16:10:40 ET.

Hypothetical premiums came from the **previous completed Alpaca minute's
close**, multiplied by 100. This is a declared reference-price scenario, not
an actual fill, executable quote or claim that the close was available at that
historical moment. Missing anchors were not filled forward or replaced with
Moomoo prices. Final hypothetical PnL used independent Decimal FIFO arithmetic.
No original trade metric was calculated or overwritten.

The existing pure function excludes all fill minutes and incomplete/outside-
hold bars, uses changing FIFO open quantity/basis, and includes partial realized
exits and final realized PnL in the total peak. MFE/MAE percentages use the open
cost basis at each sampled minute. Giveback is `max(0, peak total - final PnL)`;
exit efficiency is `final PnL / peak total * 100` only for a positive stored
peak. It may be negative and is not constrained to 0–100%. A peak rounding to
zero at six decimal dollars leaves ratios and positive-peak timing unavailable.

The recent windows had no missing eligible clock minutes in either source.
Ordinary morning, afternoon, scale and late-SPY windows respectively had
59, 104, 57 and nine eligible minutes. The NVDA put's three zero-volume extras
were outside these eligible windows. Agreement is specific to these scenarios;
it cannot prove agreement for every trade or every timestamp.

Selected **long-morning** results were identical after the diagnostic shift:

| Contract | Hypothetical entry / exit dollars per contract | MFE % | MAE % | Peak total / giveback $ | Exit efficiency % |
| --- | --- | --- | --- | --- | --- |
| NVDA Sep $220 call | 105 / 147 | 68.571429 | 9.523810 | 72 / 30 | 58.333333 |
| NVDA Sep $220 put | 315 / 204 | 1.587302 | 41.587302 | 5 / 116 | -2220 |
| SPY Oct $774 call | 275 / 339 | 40 | 0 | 110 / 46 | 58.181818 |
| SPY Oct $774 put | 174 / 117 | 0 | 41.954023 | 0 / 57 | unavailable |

The 18 recent windows yielded 162 field comparisons: 150 equal finite fields
at the existing six-decimal output precision and 12 jointly unavailable fields.
Unavailable fields were three ratios/timing fields in four zero-peak scenarios.
Older Moomoo API failures did not become zero excursions or successful matches.

## Timestamp sensitivity and interpretation limits

Unshifted Moomoo labels changed at least one metric/timing field in **all 18
recent scenarios**, including changes caused by fill-minute exclusion. For
example, the SPY-call short-morning scenario had a zero total peak and unavailable
ratios under Alpaca and shifted Moomoo. Unshifted Moomoo gave a $5 positive peak
and an exit efficiency of -1280%. The NVDA-call afternoon MAE changed from
3.448276% to 6.896552% without the shift. This shows a concrete metric impact
from label interpretation rather than a demonstrated price-feed advantage.

The empirical shift was investigated in the
[timestamp/auction study](moomoo-auction-time-semantics.md). It remains a
diagnostic sensitivity, not a production normalization or a verified vendor
publication/finality contract. Candle extremes are observed traded-price
estimates and do not prove bid/ask availability, fillability, historical Greek
accuracy or data that was available before a decision. This retrospective study
does not supply an as-of Workbench dataset or historical Level 2.

Successful signed Moomoo requests took **191.070–431.191 ms** in this run.
These are one-shot HTTP round trips, not exchange-to-client latency or live
freshness measurements. Market-hours streaming was not tested.

## Verification and recommendation

The committed offline diagnostic suites passed **147 cases** before the live
probe, with the corrected identity enum separately covered by all 26 study
tests. Three temporary saved-summary/provenance tests passed before the older
follow-up. Invented fixture tests check hand-calculated long/short and FIFO
scale cases, fill-boundary exclusion, zero/missing peaks, invalid allocation,
malformed/duplicate bars, SPY session limits, missing anchors, incomplete pages,
identity refusal and stopping after a permission/quota refusal. Existing signing
and credential/failure tests are retained. No vendor response is committed as
a fixture. Final diagnostic/documentation checks passed 231 tests with one
documentation skip. Full backend verification passed 2,606 tests with 35 skips,
plus lint and import-boundary checks. Independent review and exact-head CI are
recorded in the PR.

The only post-probe script change before review renamed its profile-output flag
from `identity_and_100_multiplier_verified` to
`identity_and_100_share_profile_verified`, clarifying that the API profile reports
shares rather than proving the premium conversion. No request or metric formula
changed and no live probe was rerun for this output-name correction. The original
executed source is preserved only as temporary provenance. The reusable manual
study retains its profile gate; the four older exact-code reads were a separate
temporary bounded follow-up, not automatic retries in the saved script.

Keep current feeds and saved metrics unchanged. This sample demonstrates useful
recent agreement, no additional verified traded-price coverage, and older
resolution failures where Alpaca still has bars. The next research decision is
whether independent expired-contract reference data can resolve the older
Moomoo cache limitation; separately, publication/finality and adjustment rules
need authoritative clarification. Any source replacement still needs a measured
metric-specific coverage/correctness benefit, provenance, fallback and rollback.
Market-hours testing, Level 2 recording rights and provider integration remain
separate approvals.

| Evidence | SHA-256 |
| --- | --- |
| Initial executed study source, temporary copy | `108b94e0cb074003149721ff22512f64e1f76435ef05aa84333094e966addd4f` |
| Initial numeric summary | `5e966e61eccae2d18e6254b5391a115f4b486de2c99f4f7db05fdddadf460c4e` |
| Four-read follow-up source | `79f2e3b96f9335c18b5630efa6dd68127d77266871da899904835f11925fe244` |
| Follow-up fixture tests | `06af4a4c4fe6cf44cf93b39f34b748939a28511aa360b13c62dc8af83ca7766b` |
| Follow-up numeric summary | `e6d094cb19fdb66d8c92650e5c360f6edf1b6b77fbb0fb74496c48ef0c10d8f6` |
| `trade_path.py` source | `bd720db961eb3375c4d5941a0934d993626b54c755fa7b1b08303524dd6bd1f3` |
| `indicators.py` source | `c08ec7e287a2a806f70b05a0f77457022cff3d6cb63dad194826c80b679076ca` |
| Retrieved official Moomoo history page | `ad9b9d8c1ba3715d9e94c6e3e2d0b71d4322111309d212aedb2bb01f33ea2efe` |

Summary paths are `/private/tmp/moomoo-option-path-coverage-summary.json` and
`/private/tmp/moomoo-option-path-older-followup-summary.json`. These bounded
temporary summaries are diagnostic evidence, not a retained raw history archive.
