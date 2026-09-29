# Historical metric correctness

This change corrects historical entry context and trade excursions before using
them to compare setups. It preserves source fills and FIFO ordering. Expired short options now credit
remaining premium instead of subtracting it; long-option expiration accounting
is unchanged. Broker reconciliation is still required to prove the source
history is complete.

## What changes

| Calculation | Corrected behavior |
| --- | --- |
| Short expiration | Remaining short premium is profit at worthless expiration; prior buybacks retain their realized result |
| Entry context | Only bars completed by the fill timestamp; records `entry_context_as_of` in New York wall time |
| Opening ranges | Five/fifteen-minute ranges remain unknown until 09:35/09:45 |
| Opening gap | Actual 09:30 open versus previous close; missing open stays null |
| Direction | Bought puts and sold calls use bearish underlying exposure |
| Session buckets | Context and path close bucket starts at 15:00, matching FIFO |
| Outside hours | The legacy `is_overnight` field is displayed as outside regular hours |
| Option excursions | FIFO quantity and basis change after each entry/exit; minute bars for multi-day holds |
| Peak total PnL | Realized partial exits plus remaining open PnL; final realized PnL is also an observed endpoint |
| Capture/giveback | Uses peak total PnL, with a separate peak open PnL field |
| Unsupported analysis | Long windows, missing bars and ambiguous fill allocation stay unavailable; simplistic underlying efficiency/greeks attribution stays null for scale-ins/outs |
| Rebuilds | Preserve reviews, roll groups and tags for surviving trade ids; changed summaries mark trade/daily reviews stale |
| Reprocessing | Versions and source/context fingerprints select changed calculations and prevent mixing legacy values into new results |

For example, buy 10 contracts at $100 per contract, sell 9 at $110, then sell
the remaining 1 at $200. If observed bars reach $110 before the partial exit
and $200 afterward, the position's peak total PnL is $190: $90 already realized
plus $100 on the remaining contract. Applying the later price to all 10
contracts incorrectly produces a $1,000 peak and $810 giveback.

## Limits

Historical minute bars provide observed estimates, not executable quotes.
Fill-minute bars are excluded because minute-granular execution timestamps
cannot locate a fill within the bar. Missing minutes may hide larger excursions.
Option windows exceeding the ten-calendar-day cap have no new path estimate.
Option paths wait for the final closing session; pre-final cache files are
refetched. Existing source feed limitations remain, including IEX volume and
unsupported option/underlying history.

The strongest-setup ranking, statistical confidence/sample counts, fill pagination, broker
source reconciliation and historical backfill progress are subsequent work.
Setup scores remain heuristics, not validated trading edges.

## Release and historical recomputation

Revision `8d4f2a6b9c10` adds nullable provenance fields. Legacy rows retain null
versions; applying the migration does not claim their numbers were corrected.
The UI labels old context/path calculations for recomputation.

Before production activation, finish CI's Postgres migration/role and Ubuntu
checks and use the schema-change deployment procedure in
[deploy/README.md](../deploy/README.md). Verify the production target and backup
before migrating. This local implementation has not migrated production or
contacted live market providers.

After deployment, run the Alpaca context job for all history and wait for it to
finish, then run the trade-path job for all history. Unforced runs now select
old versions and changed dependencies. These are enrichment/recomputation jobs;
resyncing or deleting source fills is unnecessary. Confirm versions, as-of
timestamps and unavailable reasons afterward; row counts alone are insufficient.
New calculations can legitimately become null where older formulas produced
unsupported numbers.

## Verification

`backend/tests/test_trustworthy_metrics.py` covers temporal leakage, direction,
actual gaps, changing exposure/basis, multi-day minute paths, short-option signs,
fingerprint invalidation, rebuild annotations and provisional cache behavior.
`frontend/e2e/trade-metric-quality.spec.ts` uses controlled market responses to
verify timing/quality notices and separate total/open PnL labels. Other browser
smoke tests exercise the real seeded backend. Neither proves live-provider
history correctness.

## Independent validation and review

The trade detail **Show Audit** panel reads existing cache files only. It uses
`metric_reference.py`, a separate Decimal FIFO event ledger and scalar indicator
recurrences, instead of reusing the production calculators. Malformed market
cache evidence is an error without hiding valid fill accounting. Missing
values cannot produce a passing badge. Matching results show reproducibility
on supplied inputs; they do not prove broker completeness or provider accuracy.
Legacy versions stay stale even when numbers agree.

For an explicit saved snapshot (arrays `fills`, `trades`, `links`, optional
`contexts` and `paths`), run from `backend/`:

```bash
.venv/bin/python scripts/validate_trade_metrics.py \
  --snapshot /absolute/path/snapshot.json \
  --cache-dir /absolute/path/alpaca_cache --feed iex \
  --output /absolute/path/metric-validation.json
```

This performs no database or network operations and writes JSON, Markdown and a
self-contained HTML report outside the cache. The default 30-trade sample
prioritizes diverse hard cases; it is not a statistical accuracy estimate.
Review source fills, changing quantity, observed price/PnL points, stored versus
reference values, and unavailable reasons together. Points do not interpolate
across missing minutes. Option caches lack reliable feed identity, so their
provenance remains unverified. A successful CLI exit only means no mismatch or
input error was detected; stale or unavailable checks still need attention.

Coverage includes gross FIFO accounting, completed-minute entry structure,
completed-day EMA/SMA/RSI/ATR/MACD and directional labels, underlying MFE/MAE
and timing, and position-aware option peak/capture/giveback. It excludes hourly
context, RVOL, Greeks, chase/sequence scores, underlying exit efficiency and
post-exit metrics. Setup scores are explicitly unvalidated heuristics. Entry
anchors are supplied evidence, not independently verified execution quotes.

`backend/tests/test_metric_reference.py` covers hand calculations, seeded random
long/short scale-ins and exits, production-versus-reference comparisons,
temporal invariance, rounding, corrupt/missing cache evidence and report source
preservation. The frontend browser tests also cover stale/missing statuses and
changed accounting values. Broker exports and a separate market-data source
are still needed for source verification.
