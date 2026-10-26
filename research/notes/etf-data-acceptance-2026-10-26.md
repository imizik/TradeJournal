# ETF trend: bounded data acceptance result

October 26, 2026. The owner approved the next **no-return data-acceptance review**
for the [fixed proposed case](etf-trend-experiment-decision-2026-10-26.md).
This did not authorize an evaluation, candidate attempt, protocol change or
activation. The [machine-readable manifest](etf-data-acceptance-2026-10-26.json)
records the requests, counts, fingerprints, failures and unknowns.

## Decision: FAIL acceptance; park the case

Daily date coverage passed for all four ETFs. Overall acceptance failed because
the fixed cash archive is not accessible through a verified entitlement, dated
identity and corporate-action history remain unaccepted, and the execution-minute
probe failed. Original availability by 08:00 is also unproven. No result about
strategy profitability follows from this audit.

The useful new evidence is that the connected provider actually delivered the
entire requested daily date set. Another generic bar downloader is not the
missing prerequisite. The remaining requirements concern the particular cash
series, action/identity evidence, execution observations and knowledge timing.
Do not build an evaluator or purchase data on the strength of the daily pass.

## What was requested and measured

The only successful price request covered **SPY/EFA/EEM/IEF, January 1, 2016
through September 30, 2024**, daily bars, explicitly requesting SIP, USD,
ascending order and symbol mapping as of September 30, 2024. Its limit was
10,000 aggregate records. A separate provider-calendar request covered the same
dates. No request crossed into Factory confirmation or exam prices.

The connector returned OHLCV records. Orchestration extracted timestamps and
checked basic numeric consistency; prices were not displayed in the audit
output. No signal, adjusted total-return series, return, P&L, volatility, subgroup
performance or backtest was calculated. Hashing a source response and checking
OHLC bounds do not evaluate a strategy.

| Fund | Expected sessions | Received / distinct dates | Missing / duplicate / unexpected dates | Month-end dates present | Basic invalid records |
|---|---:|---:|---:|---:|---:|
| SPY | 2,200 | 2,200 / 2,200 | 0 / 0 / 0 | 105 | 0 |
| EFA | 2,200 | 2,200 / 2,200 | 0 / 0 / 0 | 105 | 0 |
| EEM | 2,200 | 2,200 / 2,200 | 0 / 0 / 0 | 105 | 0 |
| IEF | 2,200 | 2,200 / 2,200 | 0 / 0 / 0 | 105 | 0 |

First/last received sessions were January 4, 2016 and September 30, 2024.
Calendar counts were 252, 251, 251, 252, 253, 252, 251, 250 and 188 for
2016–2024 respectively; 2024 ends in September. The 105 month-end dates include
warm-up. They are not 105 measured signals. There are 92 potential decision
sessions from February 1, 2017 through September 3, 2024.

The basic check required finite OHLC, volume, trade count and VWAP; positive
low/VWAP; open and close inside low/high; and nonnegative volume/trade count.
It did not establish economically correct prices, independent vendor agreement,
official closes or adjustment correctness. Calendar agreement is with the **same
provider's calendar**, not an independent exchange-calendar certification.

[Alpaca documents][bars] raw as the REST adjustment default and warns that page
limits do not certify completion. This connector offers no explicit adjustment
or page-token argument. Matching all expected unique dates establishes this
specific date-set coverage; it does not supply a raw HTTP pagination receipt,
an adjustment reconciliation or a guarantee that a daily close has the required
regular-session meaning. Historical `asof` symbol mapping does not establish
when a data value was originally known.

## Requirements that did not pass

| Requirement | Actual evidence | Status |
|---|---|---|
| Current and dated identities | All four current-asset calls timed out; one repeat for SPY also timed out. Proposed CUSIPs remain expected identifiers, not fresh observations. No dated continuity audit completed. | Unaccepted |
| Complete distributions/splits and other actions | Two attempts for the same 2016-01-01–2024-09-30 processing-date request timed out. No records or completeness count obtained. | Unavailable; not zero events |
| Monthly 09:35 execution observations | One four-symbol probe for February 1, 2017, 09:35:00–09:35:59 New York timed out. The other 91 decision sessions were not queried. | Unavailable; not zero missing bars |
| Fixed bill total-return archive | Named official subscription services identified, but no authenticated archive retrieval, rights or exact historical series mapping accepted. | Unaccepted |
| Original publication by 08:00 | No historical publication/revision archive accepted for ETF/action/cash inputs. | Unverified |
| Historical settlement calendar | Not audited after mandatory data prerequisites failed. | Not accepted |

There were ten connected market-data calls: two successful responses and eight
connection timeouts. The recovery check repeated SPY identity and the action
request once after diagnosing `UNAVAILABLE / McpServerError: Connection timed
out`. Acquisition then stopped. This is a transport failure, not evidence that
Alpaca lacks these instruments, actions or minute history.

The existing standalone audit in [merged PR #509](https://github.com/imizik/TradeJournal/pull/509)
was not run: the required explicit credentials are absent from this process,
and this worktree has no backend environment file. No other checkout secrets or
connector credentials were searched. Its merge does not establish live REST
compatibility or authorize updating the authoritative research checkout.

Even a successful connector action response would not settle completeness:
[the endpoint][actions] filters by processing dates and the connector does not
expose explicit pagination or incomplete-record controls. Events effective by
September 2024 but processed later would require a separately bounded metadata
reconciliation. This audit made no later-period request and did not infer absence
from empty or failed responses.

## The cash-reference blocker is now specific

The fixed proposal names the USD total-return version of the
[S&P U.S. Treasury Bill 0–3 Month Index][cash]. Its official page links the
[Global Bill Index Series methodology][method], which describes end-of-day
calculation, a SIFMA fixed-income calendar, revisions and subscription delivery
of daily index levels. An end-of-day description is not a verified 08:00 delivery
SLA or a historical first-publication archive. The bill calendar also needs
explicit reconciliation with the ETF month-end endpoints; no forward filling or
calendar substitution was adopted here.

[S&P DJI's API documentation][api] describes historical index levels and tools
for discovering index history and subscribed packages. The [SPICE entry page][spice]
led to a login interface. These identify a plausible official archive, not
confirmed access for this account, a price quote or a reason to purchase it.

A search-indexed official directory suggested the total-return identifier
`SPBDUB3T`, but directly fetching that directory returned HTTP 404. The manifest
therefore retains it only as an **unverified candidate identifier**; the accepted
vendor-series ID, coverage and entitlement remain null/false. Neither the broader
Treasury Bill Index nor a yield series, research RF, ETF proxy or zero-interest
series was substituted for the specified signal reference.

The fixed cash reference was specified before archive access was established.
That is a concrete unresolved design dependency. Resolve existing lawful access
and availability evidence first. If that is impractical, park this case or obtain
approval for a transparent pre-outcome specification revision. Do not quietly
change the input or buy a subscription to preserve momentum on this proposal.

## Provenance, limits and disposition

The manifest includes SHA-256 fingerprints of the parsed daily response, parsed
calendar response and ordered session dates. These identify the observed payload
versions, not raw HTTP bytes or immutable provider history. No raw price archive
was committed, exact per-request retrieval timestamps were not captured, and no
locally replayable dataset is claimed. Original `known_at` remains null. The
compilation timestamp must never be substituted for historical availability.

This audit closes the bounded acceptance task with a failure decision. It does
not authorize automatic retries, a backtest, another candidate, alternative
cash inputs or more infrastructure. Resumption should address the named failed
requirements; previously passing date coverage can be retained with its explicit
provenance limits rather than treated as a completely accepted dataset.

The Factory ledger and all four existing budget files matched the prior receipt;
no budget file was added. Both launchd services were confirmed unloaded. No
Factory command, production database write, protected-outcome inspection, rule
change, broker order or live activation occurred. The only repository additions
are this audit and its metadata manifest, plus a link from the decision packet.

[bars]: https://docs.alpaca.markets/us/reference/stockbars
[actions]: https://docs.alpaca.markets/us/reference/corporateactions-1
[cash]: https://www.spglobal.com/spdji/en/indices/fixed-income/sp-us-treasury-bill-0-3-month-index/
[method]: https://www.spglobal.com/spdji/en/documents/methodologies/methodology-sp-global-bill-index-series.pdf
[api]: https://www.spglobal.com/spdji/en/landing/topic/api-data-solutions/
[spice]: https://www.spice-indices.com/
