# Entry/context and option-path numerical corrections

The production audit found two zero-dollar option peaks with enormous capture
ratios and six entry-context rounding discrepancies. The corrections use
Decimal arithmetic for option exposure/PnL, cumulative completed-minute VWAP
and day-range position. Ratios and positive-peak timing stay unavailable when
the peak rounds to zero at the persisted six-place dollar precision. Genuine
representable positive peaks remain usable. VWAP and range position use
half-even rounding to four and two places, respectively.

Calculation identities are `entry-context-v3`, `position-path-v3` and
`decimal-reference-v2`. These labels identify code behavior; they are not
proof that a saved row has been recomputed or independently source-verified.

## Verification

The regression cases reproduce the audited RDDT/NFLX premium arithmetic, the
SPY/BULL/MSFT rounding boundaries and FMST's five completed cache bars. They
failed against the previous calculators. Additional cases cover short options,
sub-precision positive peaks, representable positive peaks and reselecting an
older path version despite otherwise matching input fingerprints.

```bash
cd backend
.venv/bin/python -m pytest tests/test_trustworthy_metrics.py tests/test_metric_reference.py tests/test_seed_snapshot.py -q
cd ..
bash scripts/verify.sh
```

Run a separate read-only rehearsal on a consistent journal snapshot and frozen
historical cache. Compare the changed production calculations with independent
reference values, keep unavailable cases explicit and retain both the original
report and candidate differences. The frozen database records are never
rewritten to make a validation report pass.

## Applying this release

Merging to `main` follows the normal automatic deployment process. Deployment
updates code; it does not by itself establish a complete all-history backfill.
Existing enrichment jobs select obsolete versions within their requested
range. Do not identify an old row as current merely by editing its version.

For a separately authorized production recalculation:

1. Verify the deployed release and production database identity; preserve a
   recoverable backup and a fresh read-only snapshot.
2. Re-enrich entry context for the explicitly selected history. Record changes
   and data gaps. Missing historical inputs remain unavailable.
3. Recompute dependent path metrics after context finishes, because their
   market-input fingerprints include context values and its version.
4. Capture a new snapshot, freeze the resulting cache and run the independent
   validator. Resolve unexpected differences before treating the recalculation
   as complete. Verify units, missing-data counts and input fingerprints.

No fill import or FIFO rebuild is required solely for these numerical fixes.
No schema migration is added. Provider feed/cache behavior and chart workflows
are unchanged.

## Separate source-history work

Correct arithmetic does not repair missing executions or opening inventory.
Confirm candidate missing partial fills against broker execution/order IDs and
replacement relationships; cumulative partial-email counts cannot simply be
added to complete-email counts. Obtain account-specific opening cost bases for
orphan sales, including transfers and corporate actions when applicable.

Any confirmed fill correction needs its own explicit evidence, dry-run changes
and rebuild impact review. Its order is source correction, preserved-annotation
rebuild, context enrichment, then dependent paths and a fresh audit. Unsupported
cost bases stay unavailable. This numerical fix does not authorize importing
unverified fills, changing FIFO ordering or inferring broker completeness.

Minute-bar extremes remain estimates, not executable bid/ask prices. Matching
frozen provider inputs does not independently verify provider accuracy or
historical coverage. Heuristic scores and metrics outside the independent
validator retain their existing verification limits.
