# TradeJournal: future product roadmap

**Goal:** make TradeJournal the place to prepare a trade, see what actually
happened, review the decision, and choose one concrete improvement to practice.
Success means a useful routine with trustworthy evidence and little manual
work. Shipping a feature does not establish a trading edge or improved returns.

**Planning date:** 2026-10-04; Dots capability direction added 2026-10-08;
moomoo metric-source evaluation added 2026-10-10. This document records future direction from the
product discussion. No new feature is implemented by this document, and no
production data was audited to write it.

## End goal — October 22, 2026

Isaac's statement of where TradeJournal is going. It sits above the dated
priorities below: when they conflict, this wins.

Build a personalized AI-powered trading companion that helps Isaac discover
opportunities, make better decisions, manage positions, and continuously
improve as a trader, with minimal manual effort.

1. **Discover — Market Radar.** Proactively detect unusual activity, emerging
   momentum, sector rotations and potential opportunities, even in stocks he is
   not already watching. Send timely, factual alerts without waiting for AI
   analysis.
2. **Understand — AI research and Jo.** Help him understand what is happening,
   why it matters, what might happen next, and which opportunities deserve
   further investigation. Jo provides background monitoring and deeper analysis.
3. **Decide — interactive copilot.** Bounce ideas off AI, challenge theses,
   compare scenarios and develop a clear plan. Save the reasoning, entry
   conditions, invalidation and decisions.
4. **Execute and monitor — position follow-through.** Track plans and existing
   positions, alert him when meaningful conditions change, and help manage risk
   without constant screen time. He remains in control of trades.
5. **Review and improve — personal trading intelligence.** Automatically connect
   market observations, original plans, actual trades and outcomes. Identify
   recurring strengths, mistakes and behaviors worth practicing. Use historical
   research and prospective evidence to test what actually works.

What makes it different: it knows his trading history, strategies, beliefs,
positions and past decisions, and uses that context across one continuous loop,
**Discover → Investigate → Plan → Monitor → Review → Improve**, rather than five
disconnected tools. The goal is not more features, more AI activity or
automated trading.

**What comes next: prove two things first.**

- Position alerts help him notice and reconsider important changes while
  holding trades. Measured by the alert follow-up tracker and exit-habits
  scorecard (what he did after each alert; give-back, held-past-an-hour,
  expired and opened-while-green counts against the pre-alert baseline from the
  [October 21 behavior audit](../backend/reports/behavior_audit_2026-10-21.md)).
- [Radar](radar.md) identifies opportunities he otherwise might have missed,
  early enough to investigate. Measured by the Radar pilot: his ratings, and
  comparison with the Movers ranking and the morning brief.

The `/proof` page reads both every week: a verdict per question (`helping`,
`not helping`, or by default `not enough data`) with its rule and sample on
screen, from `GET /analytics/exit-habits` and `GET /radar/proof`
(`backend/app/engine/exit_habits.py`, `backend/app/engine/radar_proof.py`).
A third card, "Do planned trades do better?" (`GET /analytics/plan-proof`,
`backend/app/engine/plan_proof.py`), compares planned with unplanned trades
since the plan card went live; it is a secondary read, not a third proof, and
selection-biased (he plans the trades he is more careful about).

Then connect the successful workflows through a natural conversational
experience, reusing the infrastructure already built. The conversational
copilot (step 3) waits for both proofs. The owner-only, off-by-default
[Copilot Lab](copilot-lab.md) is an experiment toward it, not the activated step.

**Success measure:** TradeJournal becomes something he genuinely relies on
because it helps him notice better opportunities, make deliberate decisions,
avoid repeatable mistakes and learn what improves his trading, not simply
because he built it.

## October 23 selected work — personal Jo follow-through

Isaac explicitly selected implementation of conversational follow-ups using the
existing Jo infrastructure: discuss a real interest once, save the responsibility,
and have Jo return with relevant developments. This advances that part of the
conversational loop from the earlier deferred position. The [Dots delivery board](agent/dots-integration.md#personal-follow-through--october-23-2026)
records the implementation and remaining rollout/live-use gates. It does not
authorize broker actions or reopen unrelated roadmap work.

## October 21 workflow consolidation — planning only

The owner walkthrough established the daily routine: understand the market,
investigate charts, trade/manage in Robinhood, and return when TradeJournal has
useful information. The [workflow consolidation roadmap](workflow-consolidation-roadmap.md)
records the full findings, Claude critique assessment, proposed order, source
limitations and acceptance gates. It makes Dashboard orientation the next
proposed consolidation slice after the already-local VWAP clarity fix, and
peer confirmation the primary Charts benefit from Radar.

This is a requested specification, not implementation or activation approval.
Radar retains its separately selected ownership and contract; existing Dots
acceptance continues. Plans/reviews remain available without assuming a new
journaling habit. This plan replaces the old journal-first opening-screen
assumption for future consolidation proposals; it does not remove existing
capabilities or reopen frozen studies.

## Selected priorities — October 11, 2026

The owner selected **Dots functionality as the top product priority** after
reviewing delivered work and remaining acceptance. The outcome is that Isaac
can request help, understand its evidence, and reopen Jo's saved answer in
TradeJournal with little setup. Coaching, advice and independent shadow remain
distinct roles within that experience.

The [Dots delivery board](agent/dots-integration.md#current-delivery-board)
is the shared status and next-work sequence. Use it before selecting another
slice; the detailed contracts continue to own implementation and acceptance.

1. **Dots first:** finish the actual connected advisor trial, then repeatable
   assignments, dependable connection upkeep and approved real-data advice.
   Bring the existing coach into the same workspace and expand independent
   shadow only after the advisor foundation is useful and dependable.
   **Update October 12, 2026:** Isaac declared the advisor done and moved the
   priority to the shadow trader ([shadow S1](agent/shadow-s1-contract.md));
   coach-in-workspace waits behind it.
   **Bounded exception October 17, 2026:** Isaac selected
   [prospective advisor forecast preparation](agent/advisor-forecast-preparation.md):
   subscription-only hosted Jo, non-model infrastructure and synthetic dry run.
   Dry run approved; exactly two development sessions await the new isolated
   connection. Evaluation remains inactive. Shadow and production remain
   unchanged. This does not reopen unrelated advisor features.
   **Bounded exception October 21, 2026:** after the read-only
   [behavior audit](../backend/reports/behavior_audit_2026-10-21.md) found exits,
   not entries, losing the money, Isaac selected open-trade phone alerts: a long
   option that was up gives its gain back, or is still open on its last day.
   Alerts only, off until he enables `POSITION_ALERTS_ENABLED`. This does not
   reopen other non-Dots work.
   The one-hour re-decide alert followed (#411), behind its own
   `POSITION_HOLD_ALERTS` flag as well.
   **Selected October 21, 2026:** Isaac selected [Radar](radar.md), a feed of
   meaningful intraday market changes outside his watchlist, ahead of other new
   feature work. In-flight Dots acceptance work continues. Radar sends no alerts
   and records only after his separate OK.
2. **Close the selected Research Studio work:** finish the existing event/period
   comparison and prospective MU slice ([PR #252](https://github.com/imizik/TradeJournal/pull/252),
   now merged), close its remaining activation/operational gates, and observe one
   independent user research journey. Collect prospective evidence under its
   frozen protocol once activated; do not use the waiting period to justify
   more research features.
3. **Defer new adjacent expansion:** additional Level 2/provider work, chart
   polish, Dashboard expansion, broad research features and swing S1–S2 follow
   Dots unless a concrete defect blocks ordinary use or the selected Dots flow.
   Existing authorized bounded work may close; this is not a request to abandon
   another chat's changes or disable existing features/services.

This priority selection supersedes older cross-roadmap ordering below and on
other boards. It does not mark unobserved acceptance complete or authorize a
new implementation, data grant, service activation or trading capability.
Future Dots steps need bounded contracts under the existing review/activation
rules. Keep the current advisor and research chats as owners of their selected
work; avoid duplicate implementations. Record built, activated, observed and
accepted separately, with dated evidence; an open PR is not a delivered feature.

Journal coaching's completed integration does not depend on Isaac writing
trade notes or adopting a daily habit. Repeated usefulness is a separate product
question. A3's real-session acceptance remains required for claims about that
routine, not a gate on unrelated coaching completion.

## Ownership and priority

This is the product direction for the journal's learning workflow. The selected
priorities above own cross-roadmap order; existing plans retain their feature
scope and acceptance criteria:

| Document | Owns |
|---|---|
| [Charts roadmap](charts-roadmap.md) | Chart replacement, alerts, historical trade navigation, pre-trade capture, options layers and replay |
| [Symbol info roadmap](symbol-info-roadmap.md) | News, events, company information and options-implied context beside the chart |
| [Engineering roadmap](agent/roadmap.md) | Verification, environment isolation and operational foundations |
| [Swing strategy roadmap](swing-strategy-roadmap.md) | Swing research in the strategy factory, the after-close practice loop, the setups board and confluence scan |
| [Strategy Workbench roadmap](strategy-workbench-roadmap.md) | Event-first Research Studio: connected chart, conditions and analysis on discovery data; later Factory handoff |
| [Agentic practice proposal](agentic-trading-roadmap.md) | Alternative morning human/agent decision loop, immutable plans and intraday paper review; select against the swing practice loop before implementation |
| [Pre-trade advisor roadmap](advisor-roadmap.md) | Future on-the-spot Go/Wait/Pass check on the user's idea, attached to captures and graded; separate from the shadow |
| This document | Structured reflection, weekly improvement, personal playbooks, planned risk and prospective experiments |

The milestones below are **future** or **conditional**, not a second active
queue. Their former recommendations do not override the Dots-first selection.
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
D0 and M0 are preparatory research and can be selected independently; neither is a
prerequisite for basic reflection. C3.4/C3.5 capture is built, with its human
walkthrough gates still recorded on the Charts board. The
[agentic trading proposal](agentic-trading-roadmap.md) recommends a separate
bounded paper-practice experiment using these foundations; it does not change
the milestone statuses here.

| ID | Deliverable | Depends on | Status |
|---|---|---|---|
| D0 | Read-only data audit and broad personal-pattern analysis | Existing journal data; explicit selection of the analysis task | future research |
| M0 | Explore moomoo market-data endpoints and evaluate selective metric-source replacement | Phase 1 diagnostic; separately approved bounded comparisons with existing sources | Read-only diagnostics/comparisons delivered; manual Level 2 connection landed in PRs #241/#248 and was observed in market hours on 2026-10-12. On 2026-10-12 the owner chose to bring an until-stopped session and a memory-only liquidity heatmap behind the NVDA candles ahead of Dots ([contract](level2-manual-connection.md#charts-dock-panel-and-heatmap)). This is not metric-source replacement; other new expansion follows Dots |
| J1 | Short post-trade reflection and review bookmarks | Existing trade detail; durable user-record design | future; recommended first product slice |
| J2 | Weekly review with one commitment and a follow-up | J1; existing Daily Review and Analytics | First bounded slice merged #371; deployment and real-week acceptance unverified |
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

### M0 — Evaluate moomoo data for better trade metrics

The proposed research covers the direct API's market-data endpoint catalog,
including documented capabilities that this account cannot access. Its result
would be an endpoint-to-metric map with tested availability, entitlements,
history coverage, units, timestamps, rate/subscription limits and permitted
uses. The [Phase 1 diagnostic](moomoo-phase1.md) establishes stock connectivity;
it does not establish US options access, complete historical coverage or rights
to retain live depth. Trading and brokerage-account endpoints are outside this
research.

The separately selected [historical/options diagnostic](moomoo-history-options-diagnostic.md)
on 2026-10-10 established access to one recently expired NVDA option and found
matching option OHLCV inputs after a diagnostic timestamp shift. It recommended
keeping current metric sources. The subsequent
[broader historical/options comparison](moomoo-broader-history-options.md)
and [endpoint-to-metric inventory](moomoo-endpoint-metric-map.md) record additional
bounded research and unresolved access/semantics. They add no production adapter
or metric replacement; further endpoint evaluation remains future work.

| Candidate data | Potential journal or research use | Comparison question |
|---|---|---|
| Stock and option historical candles | MFE/MAE, giveback, exit efficiency and post-exit paths | Are minute paths more complete and accurate than the current sources, including expired US options? |
| Option chains, quotes and contract metadata | Contract matching, spread/liquidity context and option valuations | Are bid/ask timestamps, sizes, multipliers and adjusted contracts reliable for the intended calculation? |
| Option IV, Greeks, volatility history and open interest | IV crush, Greek attribution, volatility context and OI changes | Are units, model assumptions, historical as-of coverage and update cadence suitable, compared with existing data and local calculations? |
| Trades, order books and related reference/context endpoints | Execution context, liquidity/imbalance research and later Workbench datasets | What venue coverage, freshness, historical availability and recording rights are actually supported? |

Evaluation would use bounded, read-only samples across active and expired
contracts, liquid and illiquid symbols, regular and extended sessions, and
corporate-action cases. Side-by-side results would keep the existing inputs and
calculations as a baseline, with independent reference calculations and
explicit missing/stale-data cases. More fields or deeper books alone would not
establish a better metric. Bar highs/lows and quote-based liquidation estimates
would retain their different meanings and execution limitations.

Selective replacement of an existing metric's data source or calculation is a
possible outcome, after demonstrated improvements in correctness, relevant
coverage or freshness without unacceptable reliability, cost or licensing
trade-offs. A recommendation would name each affected metric, its before/after
results, unresolved discrepancies, fallback and rollback behavior. It could
also recommend keeping the current source or using moomoo only to fill verified
gaps.

Any later approved recomputation would be versioned and traceable to its inputs,
source times and calculation version, preserving prior results for comparison.
Current vendor Greeks would not overwrite historical `*_at_fill` values;
historical replacement would require matching as-of evidence. Authoritative
fills and realized P&L remain governed by the existing accounting rules.

This is a future research item, not an extension of Phase 1. It authorizes no
provider adapter, metric overwrite/backfill, chart-feed change, paid entitlement,
background collector or raw depth retention. Production replacement and a
historical Workbench pipeline remain separately selected implementation slices.

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

First slice merged in #371: fixed exit-leak evidence and one saved rule at
`/daily/week`. This does not complete the broader scope or human acceptance
below; see [the implemented boundary](agent/weekly-review-plan.md).

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

## Dots-assisted learning extensions (proposed)

The 2026-10-08 direction is to give Dot durable questions, commitments and
outcomes to follow through on. These are candidates extending the owning
milestones, not shipped functionality or a second implementation queue. Keep
the selected A1–A3 practice sequence intact; select a bounded extension
explicitly rather than adding these requirements to its current acceptance
gates. Integration and authorization belong to the
[Dots handoff](agent/dots-integration.md#proposed-follow-through-capabilities).

| Candidate | Owner and dependency | Smallest useful result and acceptance evidence |
|---|---|---|
| Conversational reason capture | J1; existing capture/decision links | Attach the user's own words to a confirmed trade or opportunity, with original text, capture time and before/after-outcome status. Suggested structured reasons remain distinct from confirmed reasons. Ambiguous links ask one question or remain unresolved; corrections preserve history and links survive reconstruction. |
| Durable questions and commitments | J2; J1 for journal-linked commitments | Save “revisit after earnings” or a weekly commitment with an owner, evidence links, a due date or explicit condition, and open/resolved/expired/canceled status. Demonstrate retrieval, one follow-up, resolution and cancellation without duplicate reminders. A WAIT decision references its existing condition; do not create a competing plan store. |
| Availability and interruption preferences | J4; A3 for practice presentation | Start with explicit daily availability and attention budget; calendar access is optional. Version the preference and record actual missed windows. Presentation may mark a setup unsuitable for the user's day but cannot remove it from the frozen practice cohort or suppress open-position/operational notices. |
| Personalized practice exercises | Conditional J3 extension; repeated review difficulty and usable replay | Select a few examples of one observed difficulty, hide later information, record a choice, then reveal and explain. Known examples are labeled; training records remain separate from evaluation/holdout data. Measure completion and usefulness before building a curriculum engine. |
| Dot usefulness review | J2; J5 only for a later prospective comparison | Link brief/alert feedback to the exact artifact: useful, too late, unclear, too long, already known, or not rated. Show rating coverage, attention time and commitments attempted; recommend one output to shorten, change or stop. Unread is not useless, delivery is not reading, and a few favorable outcomes do not establish financial benefit. |

Conversational reason capture should distinguish deliberate rule-based skip,
missed alert, unavailable user, unclear setup and entry beyond the plan. Do
not infer these reasons from silence, fills or price paths. Dot may propose a
reflection from conversation; whether it may save it directly must be explicit
in its granted authority. Original pre-entry intent remains immutable.

Useful follow-up means checking the evidence and closing or revising the
question, not repeatedly producing a report. Record why a commitment remains
unresolved and when its next review is warranted. Basic capture, retrieval and
resolution must remain usable without Dot or a paid model call.

Recommended first extensions, after explicit selection, are reason capture,
durable follow-ups and attention feedback. Thesis evidence monitoring belongs
to the [agentic roadmap](agentic-trading-roadmap.md#17-dots-follow-through-expansion-proposed).
Personalized drills wait for a demonstrated learning need. The action →
feedback → next exercise pattern may inform AbleTutor separately; this does
not authorize cross-product data sharing or create an AbleTutor dependency.

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

### October 22 SPY/QQQ routine — selected bounded implementation

Isaac selected a Morning prep block with 2–3 scenarios total across SPY and QQQ,
reusing Charts levels and the day journal for plans and freeze notes. It supports
the Dots morning-usefulness outcome without new scanner rules or data grants.
He also selected the Roth IRA SPY/QQQ-only give-back dollar-floor exception,
retaining +10% arming and +3% notification. That exception remains disabled until
separate owner activation approval. This selection does not change Radar's scope
or reopen other adjacent features. Implementation is not live acceptance.
