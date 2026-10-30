# Company Research

Company Research is an owner-only fundamental-research workspace at
`/research/companies`. The followed list starts empty, supports 10 companies,
and is independent of holdings and the existing AI Buildout workspace.

## Results and evidence

Add a ticker, open its page, and choose Refresh sources. A finite durable job
reads existing SEC, analyst and calendar adapters. Reload saved data to inspect
the result. Page reads do not fetch providers or call a model. Stop following
archives the company and preserves observations, research and thesis revisions.
Re-add its ticker to restore it.

The SEC research adapter saves eight available fiscal-quarter slots with
per-metric accession, filing date, tag and units. It preserves explicit Q4 gaps;
annual/YTD figures are not substituted. Historical data imported today is not
a record of what the app knew before an earnings release. Restated facts create
new observations. Failed attempts keep prior evidence available.

Current Yahoo estimates are displayed with their source and coverage warning:
the existing adapter does not supply an absolute target quarter or known EPS
basis. That data cannot support trusted estimate revisions or GAAP beat/miss
calculations. Provider-reported earnings history is labelled retrospective.
Price targets remain analyst opinions. No new paid provider is included.

The owner can compare 2–3 companies' latest fiscal results, with each reporting
date visible. This is a factual comparison, not a ranking. What changed compares
the most recent successful financial observations; the initial import is a
baseline, not a new corporate development. Source evidence is linked from the
reported metrics.

## Thesis and research

Save a thesis and up to five explicit assumptions. A stale save from another
tab is rejected and the local draft remains available. Revisions are retained.

Prepare a finite research question, copy its frozen context to a researcher,
and paste the structured response for preview and confirmation. Saved questions
can be reopened. The assignment expires after 24 hours. Manual imports are
labelled owner-supplied, even when the text claims to come from Duet or Dots.

A response separates factual claims, interpretation and questions, and includes
short source passages and public links. Accepted numeric extractions can fill
guidance or other financial-data gaps. Their origin remains “owner accepted
extraction”; acceptance does not verify a source automatically. The researcher
cannot change the thesis. Conflicting or corrected evidence is retained as new
records rather than overwriting earlier observations.

Calculations require compatible issuer, fiscal period, currency, units,
accounting basis and share basis. Missing/unknown inputs disable the comparison.
An earnings comparison additionally requires an estimate observed before the
actual release. A range midpoint is explicitly calculated. A zero or near-zero
EPS denominator suppresses percentage surprise. Source-backed numbers and
comparison limitations appear beside analyst observations.

## Implementation and verification

The implementation uses isolated company, snapshot, assignment and finding
tables, separate from journal records. Refreshes reuse the existing `JobRun`
executor; numeric comparisons use Decimal. Owner routes are explicitly listed
in the access manifest and denied through the assistant frontend proxy.

Focused checks live in `backend/tests/test_company_research.py` and
`frontend/e2e/company-research.spec.ts`. Browser coverage exercises desktop and
phone, persistence, explicit source gaps and citation links with invented data.
Fixture checks do not establish live provider coverage or trading usefulness.
The [implementation plan](company-research-plan.md) records the broader
acceptance criteria and the remaining gated connector/scheduling work.
