# Bounded ETF metadata audit tool

October 26, 2026. Metadata preparation only; no candidate registration,
backtest, protected-outcome inspection, trading or schedule activation.

The [acceptance packet](etf-trend-acceptance-2026-10-25.md) requires identity and
corporate-action coverage before strategy data. The connected Alpaca tool does
not expose REST pagination or `data_quality`, so its compact output cannot
certify exhaustive traversal. This standalone tool supplies that missing path
without importing the application's market-data cache or Factory evaluator.

## Use and boundary

Default invocation is offline and uses invented fixture pages:

```sh
python3 backend/scripts/etf_metadata_audit.py
```

An explicitly requested provider read uses credentials already present in
`ALPACA_API_KEY` and `ALPACA_API_SECRET`, never dotenv auto-discovery:

```sh
python3 backend/scripts/etf_metadata_audit.py --fetch-metadata --start 2023-10-01 --end 2023-11-15
```

The reader accepts only GET to four fixed current asset-reference paths at
`api.alpaca.markets` and the corporate-actions endpoint at
`data.alpaca.markets`. Credentials must be valid for those endpoints; no automatic
paper/live host fallback. No user-selected URL, price endpoint, order endpoint,
redirect, environment proxy, retry, database or persistent output writer exists.
Results print to stdout only after successful traversal. HTTP errors are reported
by status without response bodies, request headers or exception details.

Bounds: four asset reads, at most ten action pages with limit 1,000, at most 2 MB
per response, and a processing-date window of at most 367 inclusive calendar days.
A 90-second elapsed budget is checked before requests and while reading; each
request has a 10-second HTTP timeout, so an in-flight timeout can extend elapsed
runtime beyond 90 seconds. Hitting any bound aborts, never certifies a partial
manifest. A failed CLI run may leave an empty file if a caller used shell
redirection; empty output is not a valid manifest.

The shortlist SPY/EFA/EEM/IEF is for metadata investigation only, not a complete
universe census or a claim that these are the oldest eligible ETFs. Asset records
are current observations. Their provider IDs and names do not prove historical
identity continuity. Expected CUSIPs are reference anchors from issuer pages:
SPY 78462F103, EFA 464287465, EEM 464287234, IEF 464287440. A missing or different
CUSIP is flagged for reconciliation, not automatically discarded or corrected.

## Manifest semantics

Each asset and action retains its raw metadata, normalized date fields, a
SHA-256 of the JSON content, and an observation timestamp. Hashes are over parsed,
canonical JSON, not HTTP bytes. Ex/effective, record, payable and process dates
remain separate. `known_at` stays null: querying an old event today cannot prove
when it was originally available. No date is replaced by a pay/process date.
Missing fields and invalid dates remain visible as issues.

Corporate-action requests set `data_quality=all`, follow `next_page_token` and
refuse repeated/invalid tokens. Exact duplicates by ID and payload are deduplicated;
conflicting versions remain in the manifest and are flagged. A terminal page
sets `pagination_complete=true`, meaning only that this bounded request's pages
were traversed. Historical coverage/identity remain unverified and evaluation
eligibility stays false even when there are no issues. No automatic pass gate.

Known-event checks are deliberately limited. Requests enclosing July 1–August 15,
2008 check for EEM's July 24 forward-split record, based on the
[exchange notice](https://www.nasdaqtrader.com/content/phlxmemos/2008/Jul/1410-08.pdf).
An absent event is `expected_event_not_observed`, not proof of no split or proof
that every provider endpoint lacks it. Other windows explicitly show an empty
`expected_events_checked` list unless the pure audit function receives metadata
sentinels. There is no comprehensive corporate-action truth set yet.

[Alpaca's documentation](https://docs.alpaca.markets/us/reference/corporateactions-1)
warns that event creation times are not guaranteed, distinguishes incomplete
records, and documents processing-date queries and pagination. This matters for
SPY's observed September 15, 2023 ex-dividend event whose processing/payment date
was October 31: a September-only processing query would miss it. The fixture
models this date separation with an invented amount, plus a missing-date record,
a duplicate across pages and an absent expected event. It contains no prices.

## Verification and actual acquisition status

Focused tests cover pagination, terminal empty pages, caps/loops, malformed
responses, current identity mismatch, incomplete records, conflicting duplicates,
known-event absence, date separation, offline default, missing credentials,
fixed endpoint refusal, redirects, HTTP errors and response-size limits.
Tests use invented dictionaries and mock HTTP transport only.

No live REST audit was completed in this implementation session: neither the
process environment nor this worktree provides the required Alpaca credentials.
The tool does not search other checkouts or extract connector credentials.
Connected-tool spot checks from the preceding review remain spot checks; they
are not relabeled as a paginated audit. No provider entitlement, historical
coverage or real response-schema compatibility is claimed from fixture tests.

Next: explicitly supply an existing appropriately scoped credential to this
standalone process, run one approved metadata window, and reconcile the resulting
manifest to issuer/exchange evidence. A new subscription is not authorized or
assumed. Full universe history, closures, benchmark changes, cash data and
execution quotes remain separate acceptance items. Both schedules remain paused;
this tool contains no scheduler or execution activation path.
