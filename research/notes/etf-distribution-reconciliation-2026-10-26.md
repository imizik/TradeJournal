# ETF/BIL distribution reconciliation and frozen input candidate

October 26, 2026, following merged PR #521. **The apparent distribution gaps
are resolved against the saved issuer histories. A reproducible input candidate
is frozen for review; no historical strategy calculation has been run.** This
does not approve an evaluation, reserve a candidate or change Factory gates.

The [fixed exploratory proposal](etf-bil-exploratory-screen-proposal-2026-10-26.md)
still owns the universe, signal, period, execution approximation, costs and
primary passive comparator. None was changed in response to these data checks.
The [metadata receipt](etf-distribution-reconciliation-2026-10-26.json) pins the
sources, normalized artifacts and reconciliation counts. No prices or full
issuer archives are committed to Git.

## Observed data findings

Compare every issuer cash-distribution row with every acquired provider cash
event whose ex-date falls in January 2016–September 2024. Match on fund and
ex-date; check amount and nonempty identifiers/record/pay dates. Sources are
State Street's [historical distribution workbook][ssga] for SPY/BIL and the
embedded distribution histories on the issuer's [EFA][efa], [EEM][eem] and
[IEF][ief] pages. Public issuer files were retrieved on October 26, 2026 without
credentials. The earlier Alpaca archive was read without new provider requests.

| Fund | Provider cash rows | Issuer cash rows | Missing positive rows | Explicit zero rows absent from provider | Amount differences |
|---|---:|---:|---:|---:|---:|
| SPY | 33 | 35 | 2 | 0 | 1 |
| EFA | 18 | 18 | 0 | 0 | 0 |
| EEM | 18 | 18 | 0 | 0 | 1 |
| IEF | 103 | 104 | 1 | 0 | 5 |
| BIL | 71 | 104 | 0 | 33 | 0 |
| **Total** | **243** | **279** | **3** | **33** | **7** |

The three missing positive distributions are:

| Fund | Ex-date | Dollars per share | Saved issuer locator |
|---|---|---:|---|
| SPY | 2016-03-18 | 1.049604 | Workbook `dividend!A9172:J9172`, amount G9172 |
| IEF | 2016-08-01 | 0.158313 | `distributionTableData`, zero-based index 122, `totalDistribution.value` |
| SPY | 2018-06-15 | 1.245568 | Workbook `dividend!A9163:J9163`, amount G9163 |

BIL's 2021 gap is **12 explicit zero dividends**, not twelve unknown positive
payments. They occupy workbook rows 60–71, with amounts in G60:G71. Across the
full window, 33 explicit zero records are absent from the provider response;
all 71 overlapping positive BIL amounts agree. There are no provider-only dates,
duplicate issuer fund/ex-date keys or conflicting nonempty record/pay dates.

Seven overlapping amounts differ. Six differ by $0.0000001 per share (SPY once,
EEM once, IEF four times); IEF on November 1, 2017 is $0.164305 at the issuer
versus $0.1643 at the provider. The receipt lists all seven. These are source
precision differences, not evidence about their effect on a strategy.

## Normalization fixed before outcomes

Use **issuer amounts for all 279 cash rows**, not just the rows where a patch
looks favorable. Keep original provider bytes, IDs and source locators. There
are 246 positive and 33 explicit zero rows. Keep the provider's processing
metadata in the raw archive; an ex-date is not a publication timestamp.

For iShares, use the reported total distribution, not the separate income/tax
components. For State Street, use the dividend column. All selected short/long
capital-gain cells are blank or explicit zero; no nonzero separate gain is
declared. This exploratory normalization interprets a blank gain component as
not separately declared, while retaining the original blank in provenance. It
does not interpret a blank dividend amount as zero. An undeclared component
cannot be certified from this archive alone; this convention is part of the
input review, not proof that every historical source was complete.

Resolve spreadsheet shared strings before interpreting cells. The initial
artifact reader displayed the shared-string index `51` for empty gain cells.
The raw workbook XML resolves it to an empty string; a separate read-only
openpyxl pass agrees for all 139 selected SPY/BIL rows. No such index was used as
a dollar amount. Independently extracted iShares totals and dates also agree
with all 140 selected normalized rows.

The sole in-window split is BIL's 1-for-2 reverse split on November 30, 2017:
post-event shares per prior share = 0.5. Its date/ratio agree with the
[issuer announcement syndicated by Business Wire][split]. There is no same-day
BIL cash event, avoiding a combined-event unit ambiguity. This is unchanged
from the earlier archive review. The normalized input has no other action type.
The 65 later-effective provider events remain excluded.

Join the supplied issuer histories to the common price calendar. A session
without an issuer event gets zero cash entitlement under this revised-history
convention; a provider omission alone never establishes zero. Preserve raw
daily closes without adjustment or rescaling. No total-return index, signal,
portfolio NAV, performance comparison or economic screen was computed.

## Identity and evidence limits

The 114 provider cash rows with blank CUSIPs can be associated with the current
issuer fund histories: SPY 78462F103, EFA 464287465, EEM 464287234, IEF 464287440,
BIL 78468R663. All nonempty provider identifiers agree. The issuer records also
supply 228 record/pay fields absent from corresponding provider rows.

This corroborates fund association in the **current revised history**. It does
not independently establish every original dated identifier, the blank old/new
CUSIPs on BIL's split, publication-time availability, or absence of later
corrections. `known_at` remains null. Current issuer histories are not an
untouched validation set. The survivor-selected universe, fractional holdings,
ex-date reinvestment and next-session-close approximation retain the proposal's
limits. This work supplies data evidence only; strategy profitability and
historical executability remain unknown.

## Frozen snapshot and verification

The candidate is preserved outside the disposable worktree at:

`/Users/user/Documents/TradeJournalResearch/etf-bil-inputs-2026-10-26-v1`

It contains the original three provider pages and receipt, four issuer source
files and download receipts, a data-only reproduction script, normalized actions,
2,200 session rows, reconciliation detail and a hash manifest. Files are
read-only local copies, not tamper-proof or remotely backed-up storage. The
original acquisition directory remains unchanged.

| Artifact | SHA-256 |
|---|---|
| `manifest.json` | `d2f07d938cc66ee7d8fb1fbc155a82823dd5a9574e3fb0e3bd5ecae66c736c43` |
| `normalized-actions.json` | `2ec6d74624bb6ee283ef10975cd0aa68761cf3b4664ff3a0f35fb88a972e982e` |
| `sessions.jsonl` | `f21b65c4fbda449825972732aa4a3ed5b6d70dc03f79d3b0fefa162b090385da` |

The snapshot has 11,000 raw daily closes: 2,200 common sessions per fund, from
January 4, 2016 through September 30, 2024. The calendar hash remains
`e146c2a83fc72017fdde4f6f4fcb4b9862e5def917e435fbe72f642a1bbed9e7`.
Each session uses symbol order SPY, EFA, EEM, IEF, BIL and decimal strings for
close, cash distribution and post/prior split factor.

Verification checked all 17 saved files, independently compared all 279 cash
rows to issuer values/dates, and matched all 11,000 normalized closes back to
the unchanged provider records. Every action falls on its fund's price calendar.
Running only the saved data-reconciliation script from the relocated sources
into a fresh temporary directory reproduced every file and the manifest hash
exactly. The script has no application, Factory, portfolio or network imports;
its job ends at input construction. It is retained with the evidence bundle,
not installed as an evaluation command. A preliminary local snapshot was
superseded only to make source verification portable; normalized actions and
session bytes did not change.

Reproduction requires Python 3 with America/New_York timezone data. Invoke the
saved `freeze_inputs.py` with three absolute paths: the bundle's `issuer/`, its
`provider/`, and a **new** destination directory. It refuses an existing output.
Receipts retain original download locations as provenance; reproduction resolves
their file basenames within the supplied issuer directory. Do not call the
portfolio calculator as part of this check.

## Decision and next independently testable milestone

**Go for reviewing this frozen exploratory input candidate and preparing the
counted intake. No-go for evaluation or a tradability claim today.** This review
closes the observed distribution-gap investigation within the proposal's revised
history assumptions. It does not certify original publication-time identity or
adopt a new protocol. Further acquisition is not needed to explain these gaps.

The next useful engineering slice is a fixture-tested, disabled portfolio child
and intake through the **existing** Factory writer lock, reservation, budget,
exposure accounting and deadline. Pin this input manifest and canonical proposal
identity; reject wrong hashes, protected dates, missing inputs and authorization
absent; retain charges after a reserved failure. Keep confirmation/exam paths
unavailable and produce an exploratory artifact only. No scratch ledger,
unmetered invocation or retry path is acceptable.

After that preparation is reviewed, a separate explicit approval must authorize
one bounded official run. Its fixed practical follow-up criterion is still at
least 2 percentage points/year active-minus-passive at base costs and positive
increment under 30 bp stress; it is not a validation gate. No favorable subgroup
can replace the primary comparison. Both Factory schedules remain unloaded;
live execution remains off. Ledger/budget hashes were unchanged during this work.

[ssga]: https://www.ssga.com/library-content/products/fund-data/etfs/us/spdr-etf-historical-distributions.xlsx
[efa]: https://www.ishares.com/us/products/239623/ishares-msci-eafe-etf
[eem]: https://www.ishares.com/us/products/239637/ishares-msci-emerging-markets-etf
[ief]: https://www.ishares.com/us/products/239456/ishares-710-year-treasury-bond-etf
[split]: https://www.streetinsider.com/Press%2BReleases/State%2BStreet%2BGlobal%2BAdvisors%2BAnnounces%2BETF%2BShare%2BSplits/13511071.html
