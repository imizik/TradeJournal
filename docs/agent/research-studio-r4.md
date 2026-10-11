# Research Studio R4: variants, conclusions and usefulness

R4 was selected after R3 was merged and manually activated. It completes the
bounded comparison/conclusion workflow and improves its explanation and layout.
[The roadmap](../strategy-workbench-roadmap.md), [R1](research-studio-r1.md),
[R2](research-studio-r2.md) and [R3](research-studio-r3.md) retain source,
observation, outcome, baseline, exposure and lifecycle contracts. Human usefulness
acceptance remains pending; automated completion does not declare V1 accepted.

## Connected workflow

The owner page starts with a readable question, ET window and outcome-free
population preview. **Edit conditions** opens the complete bounded editor;
scientific units remain visible beside its plain labels. Revealed results
collapse the editor, prioritize mean/baseline/difference and horizon-specific N,
and keep uncertainty, exclusions, previous-result and outcome-informed labels.
Immutable hashes move to details. No palette, chart gesture, price basis,
feature/outcome math, source cutoff, Factory or saved chart setting is changed.

After revealing a completed run, **Duplicate as variant** retains that exact
parent dataset. This R4 slice changes predicates only: targets, discovery dates,
decision window, event rule, horizons, normalization and analysis specification
stay fixed. A new question uses the existing fresh-source R3 submission path. Variant submission drops the warmed preview grid and copies verified immutable prepared parent bytes through R2 shared admission, avoiding another decode/serialization or redundant feature population.
A parent from an incompatible analysis engine refuses new variants; its saved
result remains readable. A no-op or lineage cycle refuses. Each logical variant
has one immutable parent; conflicting reparenting refuses without rewriting it.

**Compare with parent** explicitly exposes both complete saved analyses. Exact
ticker/UTC decision-close identity defines retained, removed and added sets.
A later first qualifier on the same ticker/session is added while the original
is removed, not retained. Retained outcomes are checked identical. Selections
inspect the appropriate parent's or variant's frozen chart; they do not filter
the full-population statistics or endpoint N.

Comparison recomputes ordinary eligible outcomes from the parent's supplied
frozen snapshot, using each definition's eligibility masks and own event/clock
weights. It checks full-population point estimates against both original saved
results. Joint uncertainty uses R2's 2,000 PCG64 seed0 calendar-week draws,
all symbols together, with a shared union-of-eligible-weeks draw multiplicity
for both populations. Each population's weights and means are recomputed in
each draw; reported changes are variant minus parent for event mean, baseline
mean and their difference. Both populations need at least20 eligible weeks and
at least1,900 jointly valid draws. Missing events/matches invalidate a draw.
Unavailable intervals stay unavailable. Shared weeks are approximate dependence
blocks; adaptive comparisons remain descriptive, never independent validation.

A finite comparison child receives bounded supplied snapshot/results only,
without source/store/database paths. Preparation admission excludes other
snapshot work, drops warmed parent objects before fork, and R2's execution
lock is inherited by the child. It checks parent death and is killed/reaped by
the parent on the60-second subprocess timeout. Status access remains separate.
No extra daemon, queue, timer, provider or automatic execution is introduced.

## Saved reasoning and integrity

Conclusions are **Promising**, **Rejected** or **Unclear**, with a required reason
of1–2,000 characters. They bind one exact completed run or the revealed
parent/variant comparison, horizon, units, original data/code/specification/NumPy
references and recorded exposure state. Each new conclusion appends with a
persisted sequence; earlier text/verdicts are never replaced. Reload/reopen
restores exact linked notes. A verdict is a research note, not a candidate,
strategy, order or proof of profitability. Arbitrary human exposure is not
claimed perfectly measurable.

R4 artifacts live only in the existing research root. Parent links, operation
receipts, comparisons and conclusions use R2 no-follow bounded immutable opens.
Their SHA256 digests are appended in the existing research ledger's event
table; reads refuse changed/uncommitted files. The R2 schema, analytical semantics, existing immutable requests/results and worker code remain unchanged. The storage admission refactor advances the normal R2 execution code fingerprint: queued/retried older-version work refuses, and new variants need a parent run on the updated execution version. Earlier completed results remain readable. No app/Postgres migration
or journal/Factory write is required. Operation UUID retries preserve the same
request; conflicting reuse refuses. A cached comparison preserves its own
comparison code/method identity and records fresh parent and variant result
exposures for a fresh reveal UUID before returning bytes. Repeating the same
reveal UUID does not duplicate either exposure.

History is bounded to1,000 conclusion records; parent ancestry to100 links.
Saved-run listing remains bounded to100, while an explicit metadata-only
describe can reopen a variant's older parent outside that list. All commands
inherit the existing owner-only app proxy, bearer sidecar and CSRF boundaries;
paths, providers, hosts and protected dates remain operator-only or refused.

## Manual worker compatibility and rollback

The sidecar is still manually started with the [R3 connection procedure](research-studio-r3.md#manual-local-connection).
R4 config advertises variants/conclusions capabilities. With an earlier R3
manual worker, the upgraded UI explains that a worker restart is needed,
retains preview/run/reopen, and does not offer unsupported R4 actions. No
autostart or production restart is performed by this implementation.

After deploying a merged R4 release, let active research work finish, stop the
old manual sidecar and explicitly start it from the updated release with the
same private token and original cache/store roots. Check config capabilities,
preview, a saved run and its notes. Do not start another calculation process
while the old child still holds its inherited lock. Manual activation does not
survive a host reboot unless a later operational slice explicitly adds autostart.

Rollback restores the prior application/sidecar release. R3 can still read the
unchanged R2 run schema/results; R4 artifacts stay intact but are not shown by
the old UI. Do not delete locks, rewrite lineage/notes or relabel an archived
comparison as a new engine result. Unsupported/corrupt records require operator
inspection, not silent repair.

## Acceptance and evidence limits

Backend fixtures independently pin later same-session replacement, exact
retained outcomes, frozen-parent preview without source access, paired shared
week shocks and deterministic difference intervals, operation idempotence,
cycles/scope/unfinished-parent refusals, worker-lock exclusion, corruption
refusal and append-only reload. Browser fixtures use invented raw minutes and
the real sidecar/kernel/app proxy: question/chart start, explicit reveals,
variant membership, parent chart selection, comparison/conclusion reload,
previous/late-response handling, errors and legacy-worker compatibility.
Desktop1280×900, intermediate957×720 and phone390×844 pictures/DOM checks cover
reading order and document overflow. The PR records final receipts and limits.

The actual first R3 activation was an agent-operated MU preview and saved run,
not independent user acceptance. The user's first reaction showed confusion
about technical labels/IDs, and a later question asked why the dates ended in
2024. R4 addresses those observed explanations without claiming that an
automated workflow establishes genuine research usefulness.

Before accepting V1, the user independently completes one sharp-decline
question, changes volume as a variant, inspects one retained/removed/added
example, and saves a reason. They should explain endpoint N, ordinary baseline,
previous-result state, unavailable uncertainty, outcome exposure and why a
descriptive result is not validation. Record unanswered questions, fallbacks
and actual use before expanding dates/symbols/features. No positive-profit or
statistical-significance requirement is imposed.

The final bounded all-core1.5×→2× RVOL probe preserved the original R1 data
identity and selected269 parent /130 variant events:121 retained,148 removed,
9 added. Cold frozen-variant preview was3.98s, verified-byte submission66ms,
and paired comparison9.71s. Parent peak RSS was527,581,184bytes (503.1MiB),
comparison child485,883,904bytes (463.4MiB). Earlier overlap-heavy implementations
exceeded512MiB; those failed receipts are retained. The memory repair reuses
parent bytes and streams weekly totals; it does not change predicate/outcome
semantics. These are bounded local receipts, not a universal workload,
concurrent-load, VPS, real-phone or trading-edge guarantee.
