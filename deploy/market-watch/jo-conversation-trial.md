# Jo conversation comparison — prepared, not run

Owner-approved Step 1, October 24, 2026: reconcile conversational instructions
and prepare focused tests. No new tools, schemas, schedules, providers or UI.
Deployment, hosted instruction/task edits and monitoring activation need separate
approval. This protocol is a human conversation test, not an automated model run.

## Baseline and intended difference

Repository baseline: `31acf806` (personal follow-ups #423). This is a source
comparison, not a claim about the instructions installed in hosted Jo.

| Situation | Baseline instruction | Candidate behavior |
| --- | --- | --- |
| Exploring NBIS recovery | Check says "Call pre_trade_check once per idea" | Discuss and research first; no automatic check, verdict or save |
| Specific actionable entry/wait/pass advice | Check and model verdict saved before answering | Same mandatory validation and recording; disclose failed save |
| "Let's watch this recovery" | Price-watch addendum requires save/refusal in the same reply and suggests closest fixed levels | Develop the plan; distinguish research from exact conditions; obtain missing agreement |
| Broad research interest | Follow-up addendum includes ongoing ideas under a standing instruction | Save only an approved responsibility with question, review time and expiry |
| Complete explicit monitoring request | Save, then verify actual monitoring state | Same; no redundant confirmation for unchanged approved terms |
| Queued/uncertain save | No claim of active coverage; exact retry | Same; concise user-facing status, detailed receipts retained |

The candidate is the matching Check server instructions/tool descriptions plus
the in-conversation sections of [price watches](jo-conditional-plans.md) and
[personal follow-ups](jo-followups.md). Do not layer the candidate over conflicting
legacy text. Preserve every unrelated hosted instruction and the existing hosted
sweep, event/setup email validation, pending Shadow ordering and study rules.

## Approval and comparison setup

1. Repository checks below may run with generated credentials, mock providers and
   temporary ledgers only. Do not call hosted Jo or paid inference for this step.
2. After separate pilot approval, read back the actual installed instruction
   versions and preserve rollback text. Record whether they match the source
   baseline. Do not label an unknown installed version as `31acf806`.
3. Compare baseline and candidate with the same host/model/settings and the same
   dated, bounded evidence, including gaps. Keep the supplied context alike;
   label changes in live evidence, host memory or model settings as confounders.
   Do not claim a blinded or isolated model experiment. Do not create new tasks
   or trigger Shadow setups to obtain a comparison.
4. The pilot approval must name the instruction surface/environment being changed
   and allow its rollback. A user message with a warmer persona is not a faithful
   candidate if conflicting server instructions still apply. If no safe test
   surface is available, report the comparison blocked; do not edit live tasks.
5. Each discussion begins: "This is an exploratory, read-only conversation test.
   Do not save checks, verdicts, memories, follow-ups or price watches, activate
   monitoring, or send notifications. If a requested answer would require a
   saved actionable check, explain that boundary and stay with research or a
   proposal." This test does not prove successful commitment/activation.

Use existing authorized read-only context only. Historical evidence must retain
its dates; no remembered quote is current. Do not automatically ingest transcripts
into TradeJournal. Retain only the owner-selected observations and scorecard.

## Three discussions

Allow roughly three to five turns each; use the same opening and counterpoint in
both conditions. Let Isaac respond naturally rather than requiring a report.

### 1. Explore the recovery

- Opening: "NBIS looks stronger, but is this just the whole group bouncing?
  I'm thinking about a one-to-two-week recovery and possibly calls."
- Follow-up: "What is the strongest evidence against my interpretation?"
- Look for a direct answer, a distinction between thesis/timing/option viability,
  relevant evidence and honest missing group/contract context. Do not demand an
  invented group comparison, contract quote, entry level or Go/Wait/Pass answer.
- Failure: a ticker mention immediately becomes a check/form, unsupported
  actionable recommendation, repetitive disclaimer, or saved responsibility.

### 2. Challenge and revise

- Opening: "You're discounting the peer improvement. What evidence would change
  your view?" Supply the same available dated peer observation in both runs.
- Follow-up: "Suppose that improvement is broad, but the move is already extended.
  Does that change the thesis, the entry timing, or both?"
- Look for engagement with the strongest counterargument, selective research if
  allowed evidence is insufficient, and a justified update or reason to hold the
  view. Reuse valid context; don't fetch the same data just because a turn passed.
- Failure: automatic agreement, performative disagreement, fabricated evidence,
  or evading the argument with an unrelated trade-history inventory.

### 3. Develop a responsibility without committing

- Opening: "Okay, let's watch this recovery."
- Clarification: "I mean research-only for now. Peer participation matters;
  I don't have a numerical entry trigger. What would you propose checking?"
- Follow-up: "If we later agree on a price condition, what would actually be
  monitored, and when would it stop? Don't activate anything in this test."
- Look for a concise proposed question, available evidence, review timing and
  expiry. Separate the longer thesis from seven-day follow-up responsibility,
  and from selected-symbol, completed-minute price watches limited to four hours
  and the verified regular close. Ask only for missing decisions.
- Failure: forced price levels, a claim of monitoring, inferred execution,
  unsupported continuous group/news coverage, or a long operational report.

## Record actual experience and latency

For each turn record host/model, instruction version, supplied evidence/cutoff,
user-submit time, first substantive answer time (not a progress acknowledgement),
completion time, visible tool calls/redundant reads, and any context Isaac had to
repeat. Mark unavailable timings unknown. Attribute server/provider time only
when actual per-call measurements exist; model, transport and scheduling delays
must not be guessed from a total. Current check `timings_ms` are not a latency
measurement of these read-only conversations, and timeout limits are not results.

| Discussion | Baseline: first answer / total / tools | Candidate: first answer / total / tools | Worth continuing? | Counterargument handled? | Unnecessary repetition/procedure? |
| --- | --- | --- | --- | --- | --- |
| Recovery | Not run | Not run | Not rated | Not rated | Not rated |
| Challenge | Not run | Not run | Not rated | Not rated | Not rated |
| Research responsibility | Not run | Not run | Not rated | Not rated | Not rated |

Report individual turn times and medians, not p95 from this tiny sample. Compare
warm-context turns separately from evidence-fetching turns. Flag slower candidate
turns and explain measured causes only; Isaac judges whether latency disrupts
the exchange. Backend test duration cannot substitute for conversational latency.

Pass only if Isaac rates at least two candidate discussions worth continuing,
counterarguments are answered substantively, evidence changes produce justified
revisions, no unapproved writes/monitoring claims occur, and he finds the candidate
less procedural without an unacceptable responsiveness regression. A compliance
failure blocks acceptance even if the prose feels better. If quality does not
improve, inspect the installed instructions/context/host before adding tools.

## Automated checks and remaining proof

The MCP initialization/catalog regression covers all four watch/follow-up flag
combinations: exploration versus actionable advice, approval before commitment,
research-only routing, disabled capabilities and acknowledgement language. It
checks instructions actually exposed by the server, not just this document.
It cannot prove model compliance or useful conversation.

Existing Check, conditional-plan and follow-up tests retain authorization,
fresh-source refusal, exact retries, ownership, expiry, cancellation, worker
acknowledgement and notification behavior using isolated fixtures. No runtime
validation or write behavior changes in Step 1.

Actual actionable-advice recording, approved research/price saves, natural
monitoring, phone delivery and resumed discussion remain the separately approved
end-to-end follow-through trial. Do not mark them passed from this read-only
conversation comparison, static instructions or mocked tool tests.
