# D0: read-only journal data audit

D0 is selected preparatory research: a script and local report, with no chart,
provider, ingestion, FIFO, model, migration, API or UI changes. This contract
implements its read-only research acceptance criteria. J1 and later analytics
remain separate decisions.

The audit also motivated a separately authorized calculator correction included
in this change. See [metric-calculation-fixes.md](metric-calculation-fixes.md)
for its numerical contract, verification and production recalculation steps.
Running D0 itself remains read-only.

## Run and preserve the evidence

From the repository root, after `bash scripts/setup.sh`:

```bash
backend/.venv/bin/python backend/scripts/audit_journal_data.py \
  --sqlite /absolute/path/to/journal.db \
  --output-dir backend/data/d0/initial

# Explicitly name a variable containing the PostgreSQL URL. Configure that
# variable privately; no dotenv file or default DATABASE_URL is loaded.
backend/.venv/bin/python backend/scripts/audit_journal_data.py \
  --postgres-url-env D0_DATABASE_URL \
  --output-dir backend/data/d0/production-snapshot

# Reproduce the report without a database connection.
backend/.venv/bin/python backend/scripts/audit_journal_data.py \
  --snapshot backend/data/d0/initial/snapshot.json \
  --output-dir backend/data/d0/replay
```

Output must be a new directory. The script writes `snapshot.json`,
`report.json`, `report.md` and `records.md`, never the source. Reports contain
private account/trade information; keep them in gitignored `backend/data/`.
Email bodies, subjects, AI reviews, account suffixes and broker account IDs
are omitted. Source references and fill IDs remain for traceability.

For a connection URL, supply the URL alone rather than an `export` command or
quoted shell assignment. Invalid URI/driver parameters are rejected before
connecting. Failure messages identify the stage and SQLSTATE when available;
they omit raw driver text because it can contain connection credentials.

SQLite opens an existing file with `mode=ro`, enables `query_only`, and reads
every journal table inside one transaction. PostgreSQL uses one explicit
`REPEATABLE READ READ ONLY` transaction and rolls back. No application startup,
schema checks that mutate data, rebuild, enrichment, job, or provider runs.
Capture timestamp is the end of reading the pinned database view, not a promise
that every broker execution up to that instant has been imported. Missing
optional context/path tables remain missing; missing source tables fail.

Supplied JSON must contain `snapshot_at`, `fills`, `trades` and `links`;
`accounts`, `contexts` and `paths` follow the existing metric-validation
snapshot format. An externally supplied snapshot without capture metadata has
**unverified consistency**. Preserve the original snapshot with its canonical
SHA256. Record whether it came from fixtures or the actual personal journal;
fixture output never establishes personal findings.

## What is measured

The report inventories every current model enrichment/context/path field,
with explicit missing and obsolete-version counts. Coverage denominators are
stored rows, so total fills/trades versus context/path row counts also matter.
The raw inventory can include fields inapplicable to an instrument; it is not
an instrument-adjusted completeness percentage. Entry/path lead denominators
use eligible options only for option metrics.
Fields without an interpreted unit are inventory only. Context timing checks
compare the completed-minute `entry_context_as_of` to execution time; a proxy
older than five minutes is an audit flag, not a new product freshness policy.
Historical fields do not become stale merely because computation is old.

Internal accounting uses the existing independent Decimal position ledger over
the linked fills. Source/account/instrument/role/time conflicts, shared fill
allocations, duplicate source references, same-timestamp same-side contract
ordering ambiguity and accounting mismatches exclude the affected trades.
Only dated closed/expired trades with finite recorded PnL enter outcome
comparisons. Missing recorded return stays unavailable. Open trades, including
partial realized PnL, are excluded from outcomes. All exclusions and source
fill IDs remain inspectable; exclusion reasons overlap.

This establishes internal consistency, not broker completeness, verified
execution timestamps, fees, lot selection or the quality of provider bars.
Naive execution clocks use America/New_York by the repository convention;
historically misnormalized clocks require comparison with original messages.
Unlinked fills need reconciliation, not an automatic rebuild by this script.

Predefined personal questions:

- Entry time: premarket before 09:30, open 09:30–10:29, mid 10:30–14:59,
  close 15:00–15:59, afterhours from 16:00, using entry New York wall time.
- First/repeat: same account/ticker/entry day, from the full trade history,
  including open/excluded trades. Simultaneous first entries are first;
  scale-in fills inside a trade are not separate entries.
- Activity after losses: most recent strictly earlier same-account same-day
  **final-close batch**, summing simultaneous closes. An unknown batch stays
  unknown. Any close exactly at entry makes the state unknown. This describes
  recorded outcomes, not when the trader became aware of them. Partial exits,
  prior-day losses, open entries and missing trades limit this analysis.

Each cohort is compared with its complementary known categories within the
same account, instrument, option type and opening side. The baseline excludes
unknown dimension values. Gross mean PnL, win rate (breakevens included), mean
and median entry-cost return, dollar and percentage-point effects, trade IDs
and trading-day counts accompany each comparison. Option entry-cost return
is not account return or planned risk; short premium is not capital at risk.
Activity counts and median time after close have no exposure-time denominator
and cannot establish that losses change the entry rate.

The earliest 70% of observed eligible entry dates form discovery; the later
dates form a separate retrospective check. Dates are never split between
periods. Trades entered before the split but closed on/after it are excluded
from discovery so their later outcome does not leak across the boundary.
Use `--holdout-start YYYY-MM-DD` to fix a previously chosen boundary across
new snapshots. This is not a prospective holdout after inspecting earlier
results, and the script does not choose favorable categories to report.

Approximate simultaneous 95% intervals use a deterministic bootstrap of whole
New York entry dates, keeping records across accounts together. A joint
maximum standardized deviation accounts for the displayed supported contrast
family within each period. All attempted comparisons are counted, including
unsupported ones. At least 20 recorded returns and 10 entry days are required
in both cohort and complement; these are display policies, not proof of an
edge. Degenerate/unstable resampling stays insufficient evidence. Intervals
do not handle serial day dependence, hidden previous trials or confounding by
size, holding period, instrument choice and market regime. Seed is fixed;
`--bootstrap-draws` defaults to 1000 (minimum 200).

## Questions still requiring better evidence

Entry extension versus VWAP, trend alignment, and underlying/option path
capture or giveback are inventoried as **unvalidated stored estimates**. Their
version, presence and median are reported, but they do not become trustworthy
or enter inferential cohorts from version alone. Current input fingerprints,
timing, frozen historical caches, feed provenance and independent values must
be checked first. The existing `backend/scripts/validate_trade_metrics.py`
can check many fields against supplied frozen caches; its documented coverage
excludes trend flags, hourly context, RVOL, Greeks and several path fields.
Do not pass a changing provider cache off as a consistent snapshot.

Underlying excursion percent differs from option-premium percent and dollar
capture. Hindsight minute-bar extrema are estimates, not executable quotes or
an exit rule available at the time. Planned risk, rationale, discretionary
setup and reflection remain absent unless actually recorded.

A later-period direction agreement may motivate a precisely scoped prospective
J5 question after the remaining data checks. D0 may find that no pattern is
ready to productize. It does not authorize J1, overlays or ingestion repairs.

## Verification boundary

`backend/tests/test_d0_data_audit.py` exercises capture under a concurrent SQLite
writer, read-only refusal, payload omission, PostgreSQL transaction commands,
source conflicts, incomplete accounting, zero/null values, strict sequence
timing, date splits and deterministic day-cluster uncertainty. The PostgreSQL
command test is a fixture; it does not prove a live server connection. Run
`bash scripts/verify.sh` before reporting repository verification as passing.
Separate that result from actual snapshot provenance and personal findings.
