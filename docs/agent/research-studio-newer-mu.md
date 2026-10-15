# Research Studio: fixed MU newer-data comparison

Selected by the owner on October 11, 2026: add newer cached data, including
2026, and run the same MU rules for comparison. This is an explicit new
exploratory protocol, `mu-fixed-rules-20261011-v1`, not a change to Factory
validation, a new unseen test, or a universal Studio date-cutoff toggle.

## Approved question and periods

Definition version 1 retains its discovery bounds, canonical metadata and
calendar. Definition version 2 permits only MU, 10:00–11:30 ET completed
five-minute decisions, a 15-minute close decline at most -0.25 prior daily
ATR(14), and RVOL at least 1.5 or 2. The first qualifying decision per session,
quality masks, next-complete-open reference, exact endpoints, ordinary baseline
and weekly uncertainty calculation are unchanged. The 30-minute percent return
is the primary descriptive comparison. No stops, costs or trading profits are
inferred.

Version 2 accepts only these separate periods, chosen before revealing their
results:

- October 1–December 31, 2024;
- January 1–December 31, 2025;
- January 1–October 9, 2026 (the latest available session when selected).

Each question loads its own source cutoff with warm-up from June 1, 2023. Later
period files never feed earlier-period features or outcomes. The older raw
history retains existing Wilder/EMA seeding and inferred-split/no-dividend
provenance; this is cache evidence, not a supplier adjustment receipt. Missing
files/minutes remain exclusions, and endpoint N is separate from preview N.
Calendar closures follow the published
[NYSE 2025–2027 schedule](https://ir.theice.com/press/news-details/2024/NYSE-Group-Announces-2025-2026-and-2027-Holiday-and-Early-Closings-Calendar/default.aspx)
and the [January 9, 2025 mourning closure](https://ir.theice.com/press/news-details/2024/The-New-York-Stock-Exchange-Will-Close-Markets-on-January-9-to-Honor-the-Passing-of-Former-President-Jimmy-Carter-on-National-Day-of-Mourning/default.aspx).
The original discovery calendar is preserved. No session is inferred from
missing cache files.

## Source approval and exposure

The local operator must pass `--allow-newer-mu` to the research sidecar. Without
it the source adapter refuses version-2 source reads before opening paths.
Even with it, default/version-1 reads retain the discovery cutoff; version 2
refuses any source symbol except MU/SPY and dates after October 9, 2026.
The default production launcher remains unchanged until an explicit activation
on the merged release. The private loopback/token boundary is unchanged.

Before a session loads version-2 bytes, it commits an immutable research-owned
`source-exposure.<cutoff>.json` declaration naming protocol, MU/SPY and the
entire warm-up/source range. This conservatively records all loaded dates as
exposed, including warm-up. Actual aggregate results, cached reopens, chart
inspections and variants keep their existing append-only exposure records.
Source-version metadata survives immutable snapshot serialization and is bound
into the dataset identity. A version-1 definition cannot use a version-2
snapshot.

These intervals overlap Factory confirmation (October 2024–March 2026) and
exam data (April 2026 onward). Their inspection removes any claim that this
researcher's later work on the exposed source ranges is unseen. Factory code,
IDs, gates, defaults, ledger and prior evidence stay unchanged; the Studio
record does not revise old Factory verdicts or grant future validation status.
Any future Factory handoff must account for this external exposure explicitly.
There is no automatic fetching, cutoff advancement, new provider call or
reset of prior exposure. Future unobserved sessions can supply fresh evidence
under a separately frozen question.

## App behavior and verification

An approved sidecar advertises the fixed periods. The Study period control
starts a separate question and clears the active comparison and chart; saved
runs remain. Newer questions display the frozen rule and a 1.5×/2× volume
selector. Arbitrary condition/target/window editing is disabled and also
refused by the backend. The header and saved history identify the dates.
Switching back to discovery restores its original date boundary.

Predicate comparisons apply only within a period. A cross-period difference
is descriptive; disjoint dates are not paired event observations and the
within-period paired interval must not be presented as a cross-year test.

Backend fixtures verify the 335-session discovery roster remains unchanged,
64 late-2024 / 250 2025 / 194 2026 sessions, fixed-rule refusal before source
opens, missing-session masks, hand-calculated causal features, exposure before
source reads and snapshot round trips. Browser fixtures walk the newer 2026
parent/variant/reveal/comparison, return to discovery refusal, and desktop /
390px phone layout. Approved-cache results and operator transfer receipts are
separate from synthetic fixture proof and deployment status.
