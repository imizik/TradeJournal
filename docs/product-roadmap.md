# TradeJournal: future product roadmap

**Goal:** make TradeJournal the place to prepare a trade, see what actually
happened, review the decision, and choose one concrete improvement to practice.
Success means a useful routine with trustworthy evidence and little manual
work. Shipping a feature does not establish a trading edge or improved returns.

**Planning date:** 2026-10-04. This document records future direction from the
product discussion. No new feature is implemented by this document, and no
production data was audited to write it.

## Ownership and priority

This is the product direction for the journal's learning workflow. Existing
plans retain their implementation scope and execution order:

| Document | Owns |
|---|---|
| [Charts roadmap](charts-roadmap.md) | Chart replacement, alerts, historical trade navigation, pre-trade capture, options layers and replay |
| [Symbol info roadmap](symbol-info-roadmap.md) | News, events, company information and options-implied context beside the chart |
| [Engineering roadmap](agent/roadmap.md) | Verification, environment isolation and operational foundations |
| [Swing strategy roadmap](swing-strategy-roadmap.md) | Swing research in the strategy factory, the after-close practice loop, the setups board and confluence scan |
| [Strategy Workbench roadmap](strategy-workbench-roadmap.md) | A later interactive page over the factory's discovery data |
| This document | Structured reflection, weekly improvement, personal playbooks, planned risk and prospective experiments |

This plan does not interrupt the active `next` rows in those boards. The
milestones below are **future** or **conditional**, not a second active queue.
When the user selects one, write a bounded implementation contract and deliver
one slice. Advance status only with implementation and verification evidence.

Pre-trade capture already belongs to Charts C3.4–C3.6. Reuse its durable
records and surfaces; do not create a competing plan store. The earlier
discussion recommended a smaller text/template version with manual linking,
with voice and adherence added when useful. The user resolved this on
2026-10-04 by asking for C3.4 and C3.5 together under the existing Charts
contract. C3.6 is now implemented: source-fill links, timing and capture coverage
are described in [the workspace](charts-workspace.md#plans-linked-to-trades-c36).
Those counts measure capture coverage, not adherence to the substance of a plan.

## Starting point

The checked-in application already has reconstructed fills/trades, P&L
analytics and drill-down, tags, AI trade and daily reviews, market-context
enrichment, trade-path metrics, and charts with fill markers. See the
[feature map](agent/feature-map.md) and [analytics definitions](analytics.md).

Those are foundations to extend. AI reviews are not the user's own recorded
intent or reflection. Analytics groups are not proof of a repeatable setup.
The connected workflow below combines built capture/linking with future
structured reflection and prospective experiments:

1. Before entry, save a short plan and, optionally, a playbook template.
2. After execution, connect the plan to the recorded trade.
3. After the trade, record a short reflection or bookmark it for review.
4. Once a week, revisit selected trades and choose one behavior to practice.
5. Evaluate that behavior on subsequent trades before treating it as a rule.

## Future milestones

Order is a recommendation for when this track is activated, not a deadline.
D0 is preparatory research and can be selected independently; it is not a
prerequisite for basic reflection. C3.4/C3.5 capture is built, with its human
walkthrough gates still recorded on the Charts board. The
[agentic trading proposal](agentic-trading-roadmap.md) recommends a separate
bounded paper-practice experiment using these foundations; it does not change
the milestone statuses here.

| ID | Deliverable | Depends on | Status |
|---|---|---|---|
| D0 | Read-only data audit and broad personal-pattern analysis | Existing journal data; explicit selection of the analysis task | future research |
| J1 | Short post-trade reflection and review bookmarks | Existing trade detail; durable user-record design | future; recommended first product slice |
| J2 | Weekly review with one commitment and a follow-up | J1; existing Daily Review and Analytics | future |
| J3 | Personal setup playbook with winning and losing examples | J1; C3.4 for pre-trade template selection | future |
| J4 | Optional planned-risk fields and a session agreement | C3.4; reliable timing and links for comparisons | future |
| J5 | Prospective personal experiment log | J2; a precisely defined question supported by D0 or recorded observations | conditional |

### D0 — Establish which questions the data can answer

Start with a read-only report, not an Analytics V2 build. Audit fill/source
traceability, execution times, reconstruction, enrichment coverage and metric
freshness. Existing validation machinery is a starting point; matching
accounting calculations does not prove broker completeness or market-data
quality.

Then investigate a small set of broad questions: entry time, repeat entries,
activity after losses, entry extension, trend alignment and exit outcomes.
Only include a dimension when its definition and historical data support it.
Do not infer a discretionary setup or motivation from P&L alone.

**Done when:** the report identifies dataset date range and accounts, available
and excluded observations, metric units and limitations; links findings to
their contributing records; compares with an explicit baseline; and reports
effect sizes and uncertainty. Account for trades clustered within days and
multiple comparisons. Separate exploratory findings from checks on a later
period. Small or unsupported cohorts say insufficient evidence. Sample-count
thresholds are display policies, not proof of an edge.

The result may be that no pattern is ready to productize. Save promising
questions for J5; a research result does not authorize a smart overlay.

### J1 — Record a reflection in under 30 seconds

Extend trade detail and existing review entry points with optional structured
input: followed plan (yes, partly, no, no plan), exit reason (invalidation,
target, time, discretionary, other), one thing to repeat/change, and a review
bookmark. Keep input skippable; avoid requiring a journal essay for every
trade. These are the user's assessments, visibly separate from AI output.

When capture is available, show the original intent beside the reflection.
An absent plan remains absent; a later note cannot become pre-entry intent.

**Done when:** reflection and bookmark survive reload and reconstruction;
missing or ambiguous source links remain visibly unresolved; reviewed trades
are reachable from a simple review list; and phone/desktop entry, correction
and retrieval have browser evidence. Saving and failure states are explicit.
No automatic psychology labels or score based on whether the trade won.

### J2 — Turn weekly review into one action

Extend existing Daily Review and Analytics into a weekly view with selected
bookmarks, self-reported recurring issues, available outcome summaries, the
previous commitment, and one optional commitment for the coming week.
Distinguish outcomes from recorded process adherence. Let the user choose the
lesson; automatic summaries may organize evidence, not invent a diagnosis.

**Done when:** a saved weekly review and commitment survive reload; the next
review brings the prior commitment back; every numerical summary drills into
its records and reports missing reflection/data coverage. Define New York
week boundaries and distinguish execution dates from analytics' final-close
date selection. Completing a review must not require an AI call.

Use repeated review sessions to judge whether this helps. If the view becomes
an unread report, shorten the workflow before adding more metrics.

### J3 — Build a small playbook from real examples

Save a few user-defined setups with entry conditions, invalidation, reasons
to pass, and selected winning and losing examples. Include good decisions
with losing outcomes where the user identifies them. Reuse existing tags
where they fit, but distinguish user-confirmed membership from suggestions.

If C3.4 templates already exist, extend/reference them rather than maintaining
a second template library. Selecting a playbook for a plan copies the relevant
version into the immutable capture; later edits do not rewrite old intent.

**Done when:** a setup and its examples survive reconstruction, revisions are
clear, both outcome types can be saved, and the setup is selectable through
the existing capture workflow once that dependency ships. Aggregate stats
reuse analytics definitions and disclose overlapping cohorts and coverage.
No automatic setup classifier is required for this slice.

### J4 — Compare intended risk with recorded behavior

Add optional intended size, invalidation and planned dollar loss to capture,
plus a simple daily agreement: user-selected limits and conditions for a break.
Show intended versus recorded size and outcomes after import. Do not prescribe
limits on the user's behalf.

For options, underlying-price invalidation, planned option-dollar loss and
premium committed are separate quantities. An underlying stop cannot be
converted to an exact option loss. Planned risk is an assumption and does not
guarantee an execution price or maximum loss. R-multiples require a valid,
explicitly recorded pre-entry initial-risk denominator; historical trades
without one remain unavailable in R.

**Done when:** definitions, units, account/date scope and timing are explicit;
only reliably linked records receive plan/outcome comparisons; and session
summaries show import freshness and missing data. A delayed journal is not a
live risk monitor. Broker enforcement, order routing, account-equity returns
and buying-power claims are outside this slice.

### J5 — Evaluate one change on future trades

Store a question, behavior, eligible trades, measures and evaluation period
before collecting its results. Example: does requiring a written entry trigger
reduce trades the user later labels unplanned? Capture process adherence and
outcomes separately. Amendments are dated rather than silently changing the
original question after results arrive.

**Done when:** the original definition survives reload, later eligible trades
can be reviewed against it, missing/unreviewed observations are visible, and
the result can be inconclusive. The report distinguishes an observational
comparison from a causal claim. A favorable historical subgroup is a
hypothesis, not validation on future trades.

Build only after weekly review is useful and there is a question worth
tracking repeatedly. One prospective experiment is enough for the first slice.

## Evidence and persistence rules

- Fills are authoritative; trades are rebuilt. User reflections, bookmarks,
  examples, captures and their links must survive rebuilds. Resolve links from
  stable account/source-fill identity; a trade UUID alone is insufficient.
  Missing sources or changed membership must not silently attach a record to
  a different trade. Follow the [domain rules](agent/domain-rules.md).
- Submitted pre-entry intent is immutable. Later reflections, corrections and
  template revisions remain visibly distinct and cannot backdate a decision.
- Preserve unavailable and stale values. Show metric source, timing, units and
  relevant coverage. Underlying path metrics and option-premium results must
  remain distinguishable. Hindsight MFE is an investigation lead, not a price
  that was necessarily executable or an exit rule the trader could know.
- Journal P&L is not account-equity return. Historical outcome comparisons do
  not imply a future edge. No fabricated planned risk, rationale or missing
  market context.
- Keep the first versions in existing trade/review/analytics surfaces, with
  bulk data loading. Use AI explicitly where it adds useful synthesis; basic
  saving, reviewing and calculation must work without a model call.
- Each implementation needs targeted calculation/persistence checks and
  browser verification for interactions, with reconstruction, missing data
  and phone behavior covered as relevant. Follow [verification](agent/verification.md)
  and separate fixture, provider, deployment and actual usage evidence.

## Features that must earn their next slice

After Charts G0 passes, the product recommendation is to pause automatic
chart-parity expansion and review actual usage. Additional chart features
should solve a workflow still requiring TradingView or make useful use of the
journal's own history. Reconcile this policy with the Charts board before
selecting a post-G0 item; already implemented layout work is not a rewrite
target.

| Candidate | Evidence needed before expansion |
|---|---|
| Voice capture | Built at the user's request (Charts C3.5, 2026-10-04) before this evidence existed; review its actual use before extending it |
| Screenshots and richer capture media | Stored candles/context cannot reproduce information needed in review, such as the drawings actually visible at decision time |
| Capture adherence summaries | Linking and execution timing are trustworthy, and counting captures answers a real review question |
| Context analytics and smart badges | D0 identifies a supported question worth monitoring; evidence remains visible and uncertain findings stay uncertain |
| Signed GEX, gamma flip and strike ladder | A specific repeated workflow needs them, with provider coverage and model assumptions disclosed |
| Replay drills or exit-rule comparisons | Repeated use of basic replay establishes a concrete practice need; historical information and simulated execution limitations are handled |

These are future gates, not implementation instructions or cancellations of
existing milestones. Keep the existing options recorder collecting its bounded
history; analytical UI can wait for a demonstrated use.

## How to know the product is helping

Evaluate use across multiple real sessions: can the user retrieve an original
plan and a later reflection, finish a short weekly review, and revisit one
chosen behavior? Does the workflow reduce manual work and produce a decision
the user can explain from actual records?

Track capture/review coverage only over known eligible journal records, with
missing data disclosed. If a feature is repeatedly skipped or yields no useful
action, simplify it or pause its expansion. Usage establishes usefulness;
profitability and a repeatable trading edge require separate evidence.
