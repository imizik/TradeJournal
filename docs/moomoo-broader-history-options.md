# Moomoo broader historical/options comparisons

Observed **2026-10-11, 01:08–01:13 America/New_York**, with markets closed.
This follows the [initial options comparison](moomoo-history-options-diagnostic.md)
and [timestamp/auction investigation](moomoo-auction-time-semantics.md).
The [endpoint-to-metric map](moomoo-endpoint-metric-map.md) separates measured
access from documentation-only candidates. Current feeds, metrics and stored
journal data remain unchanged; market-hours testing is deferred.

## Scope and method

There were **31 market-data/time requests**, below the declared 32-request
ceiling, in foreground stages totaling **27.002 seconds of active execution**.
Public documentation reads are separate from that API count. All API reads
returned HTTP 200; 29 were successful and two older-chain reads returned
`ret_code=-5`. Seventeen requests were signed Moomoo reads, of which 15 returned
`ret_code=0`; five were unsigned clock reads and nine were Alpaca histories.
No refusal was retried, no pages/cursors were followed, and no permission or
subscription was activated. No Polygon tick-history request was repeated.

A temporary driver reused the existing standalone diagnostic's secured
credentials, destination checks, exact-wire Ed25519 signer and bounded reader.
Process-local additions allowed only fixed market-data paths and validated
contract identities. Each stage retained the 18-request cap, one-second request
start spacing, 15-second hard deadlines and 2 MiB response limit. The shared
investigation ceiling was 32. Redirects, inherited proxies and network logging
were disabled. Only sanitized summaries and a few numeric samples persisted;
complete history responses remained in memory. No app provider module, account
endpoint, database, cache, trading operation, live collector or WebSocket ran.

Moomoo minute requests used the selected date through the next date, `ktype=1`,
`autype=0`, `num=370`, `extended_time=0`. Comparisons retained both raw labels
and the empirical minus-one-minute interpretation; no production normalization
was added. Invalid bars, duplicates and times outside the selected window were
excluded and counted. Volumes were unscaled using returned precision, which was
0 throughout these samples. The physical options-volume unit remains unverified.

Alpaca option histories used the endpoint default, matching the current
[option client](../backend/app/engine/alpaca.py). Stock baselines used the
existing local **IEX** selection with raw intraday prices. This comparison feed
is not an audit of deployed settings. Daily stock reads separately selected raw,
split and all adjustments without changing configuration. The diagnostic read
provider APIs directly to avoid the existing clients' cache writes.

The [published no-additional-API-charge evidence](moomoo-timestamp-comparison.md#cost-evidence)
continues to apply to the existing Moomoo access. Existing Alpaca histories
succeeded. This was not a billing/account audit and did not acquire any quote
entitlement. Numeric Moomoo rate/quota allowances remained absent; Alpaca
returned a rate-limit value of 200. No quota ceiling was tested or exhausted.

## Contracts and older archive results

| Cohort | Identity and selected session | Actual result |
| --- | --- | --- |
| Older NVDA expiry | September 18 $220 call; September 17 session; `US.NVDA260918C220000` / `NVDA260918C00220000` | Chain lookup failed; exact-code static metadata resolved the derivative, NVDA owner and 100-share sizes. History and baseline succeeded. |
| Deeper NVDA expiry candidate | December 19, 2025 $175 call; December 18 session; `US.NVDA251219C175000` | Chain lookup failed. The one exact candidate was absent from a successful metadata batch, so no option history or IV request was made. This does not establish a universal archive cutoff. |
| Second underlying | SPY October 9 $774 call; October 8 session; `US.SPY261009C774000` / `SPY261009C00774000` | 366 chain rows; selected standard call closest to the sampled $773.93 underlying close; 100-share metadata; both histories succeeded. |
| Nonstandard/sparse example | UVXY1 January 15, 2027 $1 call; October 8 session; `US.UVXY1270115C1000` / `UVXY1270115C00001000` | Filtered chain returned 134 rows, including 67 validated nonstandard calls. Lowest listed call selected without assuming liquidity. API lot/contract size were 20. Moomoo returned zero-volume candles; Alpaca returned no bars. |

The older NVDA chain requests used the documented `STANDARD` filter, one exact
expiration each. Their sanitized results were `api_error`, HTTP 200,
`ret_code=-5`, which the [chain reference](https://open.moomoo.com/api/quote/derivatives/option-chain)
describes as an internal/backend failure. Cause and retention policy were not
established; these were not explicit permission or no-data responses.

The bounded follow-up used one known-format candidate per older expiry, with
strike nearest $5 to the already observed underlying close ($219.34/$174.14).
There was no symbol search loop or alternate chain request. Exact returned code,
derivative type, underlying owner and 100-share sizes were required before
history comparison. The September profile did not report a standard-specification
flag, so that classification remains unverified. A successful basic-info response
can silently omit unresolved codes, as the [static metadata reference](https://open.moomoo.com/api/quote/basic-data/stock-basicinfo)
documents. The December omission therefore cannot be labeled a history-access
failure, a nonexistent contract or a proven provider limitation.

## Minute-path comparisons

| Option and window | Shared minutes after diagnostic shift | Equal O/H/L/C/volume counts | Largest remaining difference |
| --- | --- | --- | --- |
| September NVDA, 09:30–16:00 | 390 | 390 / 390 / 390 / 390 / 389 | Reported volume 7; all shared OHLC exact |
| SPY, full 09:30–16:15 | 405 | 405 / 405 / 404 / 404 / 404 | Low $0.06, close $0.05, reported volume 41; one differing minute |
| Adjusted UVXY1, initial 09:30–16:00 comparison window | 0 | Not comparable | 390 Moomoo zero-volume rows, no Alpaca rows |

Equality tolerance was 0.000001 in each compared field. No baseline pagination
token was present. These are historical paths, not executed-price or journal
metric comparisons. September NVDA shared extrema were $1.77/$0.93; SPY's were
$4.21/$1.10 in both sources. Matching session extrema does not prove matching
trade-window MFE/MAE, especially within entry/exit minutes.

SPY returned **405 Moomoo rows labeled 09:31–16:15 ET** despite `num=370` and
`extended_time=0`. The original stock-session filter excluded 15 rows after
the diagnostic shift. A separate three-read follow-up compared the full
half-open 09:30–16:15 window and found 405 valid rows in each source.
[Nasdaq's current options-hours reference](https://www.nasdaqtrader.com/Trader.aspx?id=optionshours)
lists SPY and UVXY among products trading until 16:15. Thus the extra SPY rows
are not evidence of extended-session leakage or a coverage advantage over Alpaca.
The UVXY response also had 405 total rows, but only its initial 390-row window
was summarized; its final 15 rows were not separately validated.

The isolated SPY difference was at diagnostic interval start **12:18 ET**,
Moomoo raw label **12:19 ET**:

| Source | Open | High | Low | Close | Reported volume |
| --- | --- | --- | --- | --- | --- |
| Moomoo | 3.63 | 3.71 | 3.28 | 3.33 | 222 |
| Alpaca | 3.63 | 3.71 | 3.34 | 3.38 | 181 |

Trade-condition/aggregation or revision differences could explain this, but
tick-level reconciliation was not attempted. Neither source was ranked as correct.

All 390 sampled UVXY1 rows had zero volume and OHLC $2.2511. Among its 390
Moomoo-only rows, 389 equaled the prior returned candle's close; the first had
no predecessor in the retained window. No actual traded-price coverage or new
liquidity was established. Missing Alpaca bars do not identify a permission
failure: its request succeeded without a next-page token.

## Adjusted-contract and split semantics

[OCC memo 57601](https://infomemo.theocc.com/infomemos?number=57601) describes
UVXY's November 20, 2025 reverse split: UVXY1 delivers **20 shares**, while its
premium/strike dollar-extension multiplier remains **100**. Moomoo's reported
20-share fields are consistent with that share component, but the complete
current deliverable/event history was not reconciled. Contract shares cannot
be substituted for the premium multiplier. The root remained UVXY1 throughout
the comparison; it was not collapsed into standard UVXY.

The current [option model](../backend/app/engine/options_models.py) and
[trade-path code](../backend/app/engine/trade_path.py) use explicit option
identity and a 100 premium conversion for the existing paths. A future adjusted
contract study would distinguish underlying root, premium multiplier, deliverable
shares/cash and effective dates before interpreting Greeks or payoff metrics.
No adjusted payoff, journal metric or local Black-Scholes result was recomputed.

NVIDIA's [official split reference](https://investor.nvidia.com/files/doc_downloads/2024/05/NVIDIA-2024-Stock-Split-FAQ.pdf)
identifies June 10, 2024 as the first split-adjusted trading day. Four daily rows
for June 6, 7, 10 and 11 were compared:

| Basis/source | June 7 close | June 10 close | June 7 reported volume |
| --- | --- | --- | --- |
| Moomoo raw, `autype=0` | 1,208.88 | 121.79 | 41,238,580 |
| Moomoo forward, `autype=1` | 120.544279149 | 121.443715589 | 412,385,800 |
| Alpaca IEX raw | 1,208.42 | 121.93 | 264,492 |
| Alpaca IEX split | 120.84 | 121.93 | 2,644,920 |
| Alpaca IEX all | 120.50 | 121.58 | 2,644,920 |

Moomoo raw prices preserve the approximate 10:1 split discontinuity; its forward
series scales pre-split volume by ten. Its forward prices are not simply raw/10
before the split or raw prices afterward. They were closer to Alpaca's all-
adjustment values than to split-only values in this sample; different venue
coverage, dividend treatment, rounding and adjustment algorithms remain confounds.
There was no exact daily-price match or verified equivalence of adjustment modes.

The US-compatible [rehabilitation endpoint](https://open.moomoo.com/api/quote/basic-data/rehab)
returned 62 events. Its June 10 split row reported `split_ratio=0.1`, forward
factor A/B of 0.1/0 and backward factor A/B of 10/0 with `divi_mode=exclude_divi`.
These returned floating factors were not rescaled or applied to any production
series. The separate [split-list endpoint](https://open.moomoo.com/api/quote/corporate-actions/splits)
documents HK-only support, so it was not used as a US split validator.

## Other observations and conclusion

SPY's one-year IV/HV query returned **31 points**, August 27–October 9, at daily
midnight ET labels with weekend/holiday spacing. A one-year request is not proof
of a year of data. IV minus HV matched reported premium to floating-point
tolerance. October 8/9 IV was 11.822%/211.872%, respectively. The expiry-day
jump is an observed model value, not independently validated volatility or proof
of a historical fill-time IV. Publication time, model conventions and intraday
as-of coverage remain unknown; no comparable historical vendor-IV series was read.

Three underlying sessions also matched 390 timestamps after the diagnostic
shift. Against the IEX baseline, median absolute OHLC differences were generally
$0.01–$0.02; volume differed substantially. The December stock low had a $1.93
maximum minute difference. Venue coverage and aggregation prevent superiority
claims from those comparisons. Successful signed Moomoo request RTTs ranged
94.015–426.185 ms; these are one-shot request times, not market freshness.

The broader sample establishes usable September-expired NVDA history, another
underlying's full option session and adjusted-contract metadata. It does **not**
demonstrate a better replacement for existing metric inputs. The zero-volume
example, SPY disagreement, differing stock bases and unresolved older identity
are reasons to keep missing data and provenance explicit in further research.
Current sources remain in place. Market-hours delivery, candle publication/
revision rules, quotas, depth product rights and recording rights remain deferred
or unresolved. No adapter, metric backfill, paid entitlement or Workbench collector
was created.

## Verification and bounded evidence

Existing offline signing/parsing/failure tests passed: **93 in 5.31 seconds**.
Temporary helper fixtures passed **31 cases** (19 broad-study, six metadata and
six ETF-session cases) before their corresponding live reads. They cover exact
identity and strike matching, adjusted-root separation, unsafe destination and
budget refusal, sparse/zero-volume interpretation, daily precision and units,
DST/epoch handling, duplicate refusal and the half-open 405-minute window.
Saved-summary, secret-content and documentation checks are recorded in the PR.
No runnable repository code, fixtures, dependencies or configuration changed.

| Temporary artifact | SHA-256 |
| --- | --- |
| `moomoo-broader-history-study.py` | `7942c27ff94ed8f2c7b3c6654f14289d216e5c26e53efc088bcaa1f306a8c489` |
| `moomoo-broader-history-summary.json` | `b63d0fa0dd9b69aadba43290988a5a87be7c0ace4ba9bc10b2896bf68758ed68` |
| `moomoo-older-options-followup.py` | `a341ddb79d6852d167433c00f0bb55ee4ffc473e162488d0467e0078c84643fa` |
| `moomoo-older-options-followup-summary.json` | `bd8ed8137ee70fd225fee28e9c8e3e3a54735df38a3af14d9824c8dd7c053e7d` |
| `moomoo-spy-session-followup.py` | `5c44e958785929f5c20a4a2862ce9def01b750b110a5517f85e2c67ffb211542` |
| `moomoo-spy-session-followup-summary.json` | `53e2b4a63a62a81ea8ec29cd4f95656bb70e8f34de8d0c57f434eed3259b6540` |
| `test_moomoo_broader_history_study.py` | `8efce1d0d20c63e7fae3fe649df934320174f97ed13cbfd45db79414bb2088ae` |
| `test_moomoo_older_options_followup.py` | `bef9c6bea91556c461448b8a0c0120af1d0bbafbd69cdc23d022655e5905a2cb` |
| `test_moomoo_spy_session_followup.py` | `d761569fa8166c0d9bc55c1352b51eed69edf625af1d6d3c06c825920908289d` |

All artifacts above are under `/private/tmp/`. They contain bounded diagnostic
code/summaries, not a historical dataset; no credentials or raw-depth history are
included in the reports. Local temporary evidence can expire independently of
the checked-in conclusions.
