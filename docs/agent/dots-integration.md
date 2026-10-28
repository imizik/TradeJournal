# Dots integration: delivery status and direction

**Owner priority: Dots functionality first, selected October 11, 2026.**
TradeJournal should be the place Isaac requests help, controls what Jo sees,
and reviews her saved work. The [product priorities](../product-roadmap.md#selected-priorities--october-11-2026)
own cross-roadmap order. This board owns the Dots sequence; linked contracts
own permissions, implementation and acceptance. Planning is not activation.

Dot owns bounded preparation, explanation and follow-through. TradeJournal
owns durable evidence, calculations and deterministic monitoring. Codex builds
selected changes; Isaac owns priorities and consequential approvals. The
personal coach/advisor is not the independent Shadow Isaac comparator.

## Current delivery board

**October 17 bounded addition:** [Advisor forecast preparation](advisor-forecast-preparation.md)
has passed its synthetic dry run. The owner authorized a new isolated connection
and two development sessions after connection verification. Hosted Jo stays
subscription-only; evaluation remains inactive. Web access is unrestricted,
bounded by the server save deadline, with deadline-time price baselines.
Production Jo and Shadow are unchanged.

Checkpoint: October 24, 2026 (documentation reconciliation only): added the personal follow-ups row from merged #423/#425; no host state was checked. October 21, 2026: conditional price-plan follow-through was activated at about 01:52 ET with owner authorization (`CONDITIONAL_PLAN_ENABLED=true` in the VPS `backend.env`, `conditional_plan_enabled=true` in the Check configuration); its live proof is still pending. The Check runtime was upgraded to `141a015f`, which includes #368's packet-read marker; a read-only check at 10:16 ET still found `141a015f`, so #377's Check upgrade (scheduled after 16:15 ET) was pending then. The first scored morning brief was on time, with the morning watchdog and `HEALTHCHECK_PING_URL` configured in `alerts.env`. The same check found reads linked to every expected scheduled market-read slot since October 15 on the reliability screen; per-slot on-time/late/missing states and an opt-in missed-read alert merged in #378; missed-read alert activation remains unverified. Earlier checkpoint, October 20, 2026: the normal private journal's separate read-only Check reader was activated and verified (list/detail/grades, peer/write refusals and reader recovery); the detail-page rendering repair has since merged in #365, and real link/unlink acceptance remains open. Earlier that day, a read-only VPS check found `STOCK_WATCH_ENABLED=true` and `MARKET_WATCH_ENABLED=true` in `backend.env` (whether every running service has loaded them was not separately verified), conditional plans unset (off) in both the app and Check configurations, the morning runner enabled with publish 08:45 / deadline 09:15, and the phone-alert timer running every two minutes. Earlier checkpoint, October 19, 2026: owner approved starting the morning-briefing implementation below, accepting shared-context Shadow as independence-unverified. Shadow S1 retains its October 17 owner acceptance on October 16 live-session evidence. Other rows retain their individually stated evidence dates; this update is not a production-state audit.
**Claude Duet trial, October 26, 2026 (server side ready, connectors not yet
added):** the owner was admitted to Anthropic's Claude Duet preview and
selected one trial beside Jo: a researched morning brief and an evening
debrief, through the existing Check and journal-coach MCP servers added to his
Claude account as custom connectors under a second, client-bound profile
([recipe and instructions](../../deploy/duet/README.md)). On October 27, 2026
the Check runtime was upgraded to `889a2870`, the live journal coach
(`tradejournal-journal-real`) was refreshed by hand, the Auth0 application
Claude Duet was created, and a second profile bound to it was added to both
configurations with both services restarted at 12:00 ET (Jo's profile
unchanged). The Claude connector sign-ins and the Duet standing instructions
are still owner steps; nothing about Jo, Shadow or the app's alerts changes,
and no usefulness is claimed before five rated mornings.

This board is the one place that answers "what is built, switched on, seen
working and accepted" for Dots; the linked contracts hold the evidence. Open owner
checks are in the [owner acceptance runbook](owner-acceptance-runbook.md). Move
the checkpoint whenever a row changes, and verify host state before acting.
Built means merged implementation, activated means enabled in the named
environment, observed means the actual path ran, and accepted means the
slice's stated exit criteria were met. None implies trading edge.

| Capability | Built | Activated | Observed | Accepted | Remaining boundary |
|---|---|---|---|---|---|
| Journal coach ([contract](cloud-mcp-journal-contract.md#observed-continuous-journal-acceptance)) | Yes | Yes | Oct 10 | **Initial integration, Oct 10** | Eight approved fields over closed/expired Roth trades; no open positions, intentions or automatic coaching. Repeated usefulness and current health are separate questions |
| Invented-data advisor: connected trial, repeatable questions, owner status ([assignment](advisor-assignment-contract.md), [upkeep](advisor-connection-upkeep-contract.md)) | Yes | v2 trial upgraded Oct 12 per the operator record (owner page lists checks); not recorded in the repo's evidence | Connected trial Oct 11 | **Closed by the owner Oct 12**, not against every contract gate | Repeatable-question and key-upkeep acceptance with actual Jo were not recorded; owner-deferred revoke/recover check remains. Invented data only |
| Pre-trade check, real data ([contract](advisor-pretrade-check-contract.md#next-steps)) | Yes | Oct 12 | First checks Oct 12; sign-in survived a 60-minute gap Oct 13 | Per step in its next-steps table | Grading (followed vs overrode) needs weeks of saved checks; swing outcome linking and sector moves open |
| Setup scanner S1 ([contract](setup-scanner-contract.md#daily-health-acceptance-notes)) | Yes | Oct 12 (`SETUP_SCANNER_ENABLED`) | Oct 13 baseline session | No — ten full sessions from Oct 14 | Restart and pricing gates per the contract; no tuning before 50 paper trades |
| Selected-stock awareness ([contract](setup-scanner-contract.md#selected-stock-awareness-separate-from-option-eligibility)) | Yes (#327) | `STOCK_WATCH_ENABLED=true` in the VPS `backend.env` (read-only check Oct 20; activation date not recorded) | Detector replay/fixtures only | No | Native email → actual Jo → saved stock review → phone; stock advice remains separate from trade eligibility |
| Market watch MW-1 and scheduled reads ([design](market-watch-design.md#mw-1-implementation-and-activation-boundary)) | MW-1 (#312, #313); four scheduled reads (#315); MW-2 event wakes and push (#316), off by default. Per-slot on-time/late/missing and the opt-in missed-read phone alert (`JO_MARKET_READ_ALERTS`) merged in #378 | MW-1 and the 09:50/11:00/12:30/14:00 reads with the snapshot publisher, Oct 14. `MARKET_WATCH_ENABLED=true` with store and outbox paths set in `backend.env` (read-only check Oct 20); MW-2 live wake/push behavior not verified. Missed-read alert not activated | Instructed Jo tool proof Oct 14. First scheduled read Oct 15 refused (13 references over the limit of 10); task workflow fixed in #323. Read-only check Oct 21 10:16 ET: the [reliability screen](market-watch-design.md#mw-2-implementation-and-activation-boundary) linked a read by time to every expected slot Oct 15–20 and to Oct 21 09:50, 18 s to 12.4 min after the slot. Time-window links can't show whether a read came from the scheduled task or a manual or setup request | No | Owner confirms the proposed 15-minute on-time tolerance; an on-time read shown to be the scheduled run (operation-ID export); after separately verified activation, one missed-read alert and recovery observed on the phone; eligible intraday scoring; MW-2 needs Isaac's separate approval |
| Jo historical replay ([contract](dot-historical-replay-contract.md)) | Yes, isolated demo (#305, #308, #329, #331) | No; merging does not activate or rebind the isolated demo | Generation-only replays (135 sessions, no Jo choices) | No | Actual Jo completing the five-session batch and its scorecard; exam count is zero |
| Shadow Isaac S1 ([contract](shadow-s1-contract.md#acceptance)) | SH-1 through SH-6 pipeline | VPS file exchange and Jo task, Oct 13 | Oct 16 full session: **8 published setups, 8 on-time SKIPs**, 7 clean-order receipts and 1 conservatively false; refusal/restart/lifecycle fixtures passed | **Pipeline accepted on Oct 16 evidence; owner closeout Oct 17** | Natural TAKE lifecycle unproven live because no setup has qualified for Jo to take; covered by fixtures and not an acceptance blocker. No selection edge claimed. At 50 resolved S1 paper trades, report per-family underlying and option results for an owner keep/turn-off decision; no tuning |
| Shadow S2: Isaac's trades in the scorecard ([plan](shadow-build-plan.md#s2--built-isaac-in-the-scorecard)) | Yes, display-only (#304) | Pending: merged after the last recorded deploy (`23b7c6c`) | No | No | Comparisons say "not enough evidence" under 30 decisions |
| Shadow S3 (independence) / S4 (shadow picks contract and exits) | No | No | No | No | S3 research-gated; S4 needs S2 evidence. S1 is accepted; later slices retain their own authorization gates |
| Manual A1/A2/A3 fixtures ([contract](advisor-shadow-contract.md)) | Yes | — | A2 one lifecycle | No | Cloud-runner isolation, forward comparison and A3 human-timed acceptance unproven; latest A3 record is 0/3 sessions. Separate from Shadow Isaac S1 |
| D0–D2 sample reads and choices ([scope](cloud-mcp-integration-scope.md)) | Yes | Sample trial | Synthetic OAuth call and sample reads | Sample only | Do not infer later write/UI/restart gates from an earlier sample |
| D3 follow-through | Design only | No | No | No | No accepted subscription or scheduled follow-through; maintenance timers do not count |
| Conditional price-plan follow-through ([contract](setup-scanner-contract.md#conditional-price-plan-follow-through)) | Yes (#335; owner price-watches screen #359). Refused-request receipts shown on Jo's day and the watches screen merged in #384; Check runtime/tool deployment remains a separate verification | Oct 21 ~01:52 ET with owner authorization: `CONDITIONAL_PLAN_ENABLED=true` in the VPS `backend.env` and `conditional_plan_enabled=true` in the Check configuration; monitor heartbeat fresh with 11 eligible scanner tickers. The owner refreshed the Check tools in ChatGPT at ~09:14 ET and added the Jo instructions from [`jo-conditional-plans.md`](../../deploy/market-watch/jo-conditional-plans.md) | Local lifecycle, scope, restart and delivery-burst regressions passed; live proof (save → trigger → phone → cancel → restart) pending | No | Actual Jo save, monitored future transition, phone confirmation, cancellation and restart; separate from S1 and the pilot study |
| Personal follow-ups, followup-v1 ([section](#personal-follow-through--october-23-2026)) | Yes (#423); explore-first conversation instructions #425 | Not recorded here: app `JO_FOLLOWUPS_ENABLED` and Check `followup_enabled` default off | No | No | App/Check deployment, Jo instruction rollout ([instructions](../../deploy/market-watch/jo-followups.md)) and a natural owner question → review → phone observation are separate gates |
| Saved advice → journal links ([contract](advisor-pretrade-check-contract.md#saved-advice-links-to-later-journal-activity--october-20-2026)) | Built (#363, #364) | Read-only journal reader enabled Oct 20 with owner authorization | Live list/detail/grades and peer/write refusals passed; existing units/configs preserved; UI list visible; structured-condition detail crash fix merged in #365; fixture link/unlink only | No | Explicit owner link/unlink plus "Later activity — review needed" possible matches; no grading, notifications, assumed links, reassessment or new Jo access |
| Personalized morning briefing and explicit memory ([roadmap](#personalized-morning-briefing-and-memory)) | #342–#344 merged; briefing layout, memory-revision display, saved-memories screen and delivery watchdog through #356 | Roth-only publisher/importer and existing Jo task, Oct 19. `JO_MORNING_ALERTS=true` and `HEALTHCHECK_PING_URL` in the VPS `alerts.env` (read-only check Oct 21) | Packet/UI observed; instructed afternoon Jo save receipt-confirmed Oct 19 15:31 ET; first natural scheduled run Oct 20 failed connector validation, manual recovery saved 09:26:56 (late). **Oct 21, first scored morning on time:** packet 08:45:18, Jo read recorded 08:55:45, Check receipt 08:56:43, in the journal 08:56:52 (9 s import lag); watchdog on, no notices (correct) | No | Five-morning acceptance so far: delivery 1/5, watchdog 1/5; no phone push exercised yet. The owner judged Oct 21's content weak (no macro context); the [market backdrop](#market-backdrop--october-21) (#377) is merged, and its Check upgrade (scheduled after 16:15 ET Oct 21) was pending at the last check. Existing Jo/auth reused; shared-context limitation accepted; [delivery honesty and the morning watchdog](#delivery-honesty-and-the-morning-watchdog); ten-morning owner ratings tracked below |

### Personal follow-through — October 23, 2026

The owner selected conversational follow-through: keep the original question,
personal relevance, next review and expiry; bring useful developments back without
repeated requests. The implementation uses the existing Check ledger, market-watch
worker/exchange, selected-stock evidence, conditional plans and phone delivery.
It adds five actor-owned `followup_*` tools and a separate personal review workflow;
SPY forecast predicates and its three-message budget do not govern these updates.

Up to five active responsibilities (25 new saves/day) last at most seven days.
Reviews run during verified regular exchange sessions, with at least 30 minutes
between planned reviews; existing stock events and linked price-plan transitions
can make work due earlier. Public news research is performed by hosted Jo when
needed and is stored as Jo-reported source findings. No continuous news/pattern
monitor, account access, new provider calls or paid model worker is introduced.
Missing evidence is explicit, unchanged reviews stay quiet, and cancellation,
expiry, late/missing reviews and delivery outcomes remain visible in the ledger.

The [conversation, sweep, event-task and rollout instructions](../../deploy/market-watch/jo-followups.md)
are prepared. The app flag and separate Check flag default off. Merge, app/Check
deployment, live task installation and a natural owner-question → review → phone
observation are separate gates; this implementation does not establish activation
or live usefulness. Conditional price watches keep their separate lifecycle.

### Functionality sequence

**October 24 selected preparation:** conversational instructions now distinguish
exploration, proposed responsibilities and approved monitoring. Research-only
follow-ups need no price watch; actual actionable advice retains Check validation
and saved verdicts. The [three-conversation comparison](../../deploy/market-watch/jo-conversation-trial.md)
holds the baseline, scripts and latency/usefulness scorecard. This is bounded
repository preparation only: no hosted instruction/task edit, Check deployment,
activation or natural conversation-quality result is implied. Peer publication,
new context/history tools and UI changes remain outside this step.

These are product outcomes, not authorization to implement every row at once.
Reuse existing OAuth, receipts, host and UI where their contracts permit.
Resolve an actual blocked user action before adding another infrastructure slice.

| Order | Outcome | Completion evidence |
|---|---|---|
| **1 — Observed Oct 11: connected advisor trial** | Finish the existing advisor chat's one invented-data end-to-end trial | Actual Jo reads the frozen request, saves a cited answer, and the owner sees the identical receipt in TradeJournal after reload and service restart; existing isolation/activation gates remain applicable |
| **2 — Closed by owner Oct 12: repeatable advisor questions** | Owner creates, assigns, revokes and reopens questions through the app | A second distinct assignment works without OAuth edits or service restart; answers bind to the correct immutable request, and prior answers remain recoverable. Write a bounded assignment-management contract first |
| **3 — Closed by owner Oct 12: dependable connection** | Routine use survives normal credential/key lifecycle and service maintenance | Supported refresh/reconnect, health/failure visibility and recovery are observed; connection maintenance stays separate from agent schedules and trading automation. Scoped in the [connection upkeep contract](advisor-connection-upkeep-contract.md). Key upkeep (`deploy/advisor_keys_control.py`) and the owner status view were installed with the v2 trial upgrade on October 12 per the operator record; the refresh/reconnect lifecycle was not observed before the owner closed this step |
| **4 — Live Oct 12: useful approved real-data advisor** | Move beyond invented packets to a narrowly selected real question and data scope | Separately approved fields/sources, frozen provenance, stale/missing-input handling and actual useful answer; do not call the fixture advisor the live AV0 Go/Wait/Pass product. Slice 1 (pre-trade check, live data and own-trade aggregates approved October 11) is in the [pre-trade check contract](advisor-pretrade-check-contract.md); activated October 12, 2026 and tracked in its next-steps table |
| **5 — Coach in the same workspace** | Request/review coaching without extra setup or copy/paste | Preserve the completed read-only journal connector and link displayed work to its approved snapshot. Define saved-result scope explicitly; UI unification is not broader data access |
| **6 — Current (selected October 12, 2026; S1 activated Oct 13): bounded shadow** | Obtain a separately formed decision for comparison. Direction selected October 12, 2026: an informed shadow trader with its own paper book plus a setup co-pilot sharing one scanner ([design](shadow-trader-design.md)) | Learns from closed history up to a cutoff; blind to Isaac's same-day decisions until it commits (commit-then-reveal), then applicable forward/paper gates. First slice [shadow S1](shadow-s1-contract.md) uses an email-triggered Jo task (observed waking Oct 13), so independence stays unverified until S3 |

After these bounded outcomes, select one follow-through capability only when a
real recurring need justifies it. Do not build a general agent platform, widen
journaling obligations, or require profitable research as an integration gate.
Independent shadow acceptance does not block the already accepted coach.

### Coordination and acceptance

The lead Codex chat owns shadow S1 activation and the weekday scanner health
check ([acceptance notes](setup-scanner-contract.md#daily-health-acceptance-notes));
the journal chat owns journal refresh/coaching. The advisor chats closed when
the owner declared the advisor done on October 12, 2026. Research
retains its already-selected comparison/prospective slice and user acceptance,
then yields new feature priority to Dots. Other chats should consult this board
and the product priorities before starting adjacent work.

Each handoff should identify the user action being enabled, current status,
linked evidence, exact remaining exit gate and next eligible slice. Carry
unchanged evidence as the repository workflow permits; do not repeat a completed
integration trial merely to satisfy a new roadmap label. A conversational success
claim is not a durable receipt, and recorded past acceptance is not current health.

## Personalized morning briefing and memory

**October 19, 2026 — implementation authorized.** The owner approved starting
the small release using existing Jo/auth, with Shadow left unchanged and its
shared-context limitation accepted. Grants, task changes, deployment and
activation retain their separate approvals. This is not a current VPS audit.

**Outcome:** open TradeJournal to an already-generated, phone-friendly briefing,
understand what matters in about five minutes, open the relevant chart, and
continue with Jo using the same saved evidence and personal context.

### Smallest release and non-goals

- Reuse **Trader Jo's existing TradeJournal Check connection, Auth0 setup and
  services**. Extend bounded tool authorization and receipt/storage patterns;
  do not create another Auth0 application, login flow or inference worker.
- Freeze a dated packet of approved holdings, the actual saved Charts watchlist,
  relevant levels/captures, active personal memories and the prior briefing.
  Jo retrieves it, researches material developments and submits a cited brief
  with a stable operation ID. Dashboard reads the saved result without inference.
- Show what matters, why it matters personally, what changed, contrary evidence
  and reasons to wait; prioritize at most three items. Reuse Attention for factual
  warnings, Charts for investigation and captures for owner-confirmed plans.
  Add a compact context reference, not automatic chart overlays. Reopen by date/ID;
  offer a copyable Jo context reference until a direct handoff is verified.
- Store explicit memories in existing relational storage: original wording,
  separate interpretation, source, symbol/topic, timestamp, revision and status.
  Inferred memories remain proposals pending owner review. Corrections/retirement
  preserve history and each briefing's referenced revisions; sensitive material
  needs an explicit deletion/redaction path. Retrieve by symbol/topic/status and
  recency, with a few pinned preferences. Bootstrap only owner-selected records
  or supplied conversation excerpts, not an assumed export of all Jo history.
- Current positions come from the journal, not remembered holdings. Distinguish
  preferences and beliefs from facts and statistically supported lessons; retain
  sample size, period and limitations. Reuse validated position calculations and
  source times; unsupported basis, exposure or option metrics stay unavailable.

**Non-goals:** a new auth system, VPS Codex worker, paid-model fallback, vector
database, full Session framework, wholesale conversation ingestion, broad
discovery scans, continuous AI thesis monitoring, dashboard rewrite, autonomous
trading or automatic plan monitoring. No changes to Shadow's live workflow or
experiment, and no new forecasting study. Saving a plan does not activate it.

### Owner daily thoughts and review — October 21 implementation

The owner authorized a daily thinking workflow after the isolated UX audit.
The private owner UI records morning outlooks, later thoughts, ideas (including
explicitly untraded ones) and end-of-day reflections in `DayJournalEntry`.
The Morning page and Daily Review share the selected day's timeline; Jo's
briefing remains separately attributed. Entries need no trade or account and
retain original text and server receipt time. A later update adds a new entry;
selecting a historical day does not backdate it. Retry operations are
idempotent and conflicting payloads are refused.

`GET /day-journal/{day}` and `POST /day-journal/{day}/entries` are owner-only.
No journal-reader, assistant or MCP role gains access. Ordinary reads do not
fetch market data or launch inference. Saving a thought marks an existing
review stale without moving its original generation time. Thoughts and
unlinked-capture days appear in the review calendar even with no trades.

Explicit daily analysis can review thoughts/captures without trades, retaining
the existing configured review backend. Owner entries and later capture notes
retain timestamps and provenance in its input. Review context discloses its
entry/text limits and retrospective notes. Optional expectation checks refer
to saved thought IDs and sourced market observations; missing evidence remains
unresolved. They are separate from trade-plan adherence and do not establish
trading edge or returns. Symbol links open the selected day's chart for
inspection. The existing no-trade empty state remains meaningful when there
are neither trades nor saved thoughts/captures.

The isolated browser test uses the real owner routes, context builder and
review persistence with labeled synthetic market and inference boundaries.
It verifies UI integration, not model accuracy, a naturally elapsed trading
day, natural Jo delivery or production activation. The UX journey lives in
`.claude/skills/trade-chart-ux/references/day-review-journey.md`; its recurring
follow-up preserves pass/fail/blocked evidence and revisits findings after fixes.

### Shadow separation decision — accepted limitation

Personal memories/briefings must remain separate from Shadow records and be
excluded from its explicit frozen input packet. Reuse existing storage and
packet construction; separate tables or scopes alone do not isolate reasoning.
Do not automatically copy app memory into Dot-wide memory, but recognize that
retrieving it still exposes it to the receiving model context.

Personal Jo and Shadow currently share a Dot context. A new chat, prompt to
ignore memory, or shadow-first call ordering does not prove independence. The
same authenticated identity with the same permissions cannot enforce different
access merely because a task calls itself Shadow.

**Owner decision, October 19:** proceed with personal briefing/memory and leave
Shadow's workflow unchanged. Isolation is not an activation prerequisite.
Preserve `independence-unverified` and all existing execution guards; richer
personal context may influence Shadow, and results are not blind comparisons.
Record the actual personal-memory activation time in the activation evidence so
later reviews can distinguish before/after periods. Revisit isolation only if
the owner selects it later; earlier results cannot become independent retroactively.
No separate runner, new identity or Auth0 application is selected.

### Delivery checkpoints and acceptance

| Step | Work | Acceptance / dependency |
|---|---|---|
| 1. Settle scope | Small release and shared-context Shadow accepted; deadline/timezone, exchange-session schedule, accounts/fields and initial memories remain activation choices | Implementation authorized; no live data publication or task creation before those choices and approvals |
| 2. Save and reopen | Versioned memory, frozen packets and immutable briefing revisions in existing storage; private owner reads | Fixture save → reload → reopen returns identical evidence and revision IDs; correction/retirement and duplicate/conflicting writes behave explicitly |
| 3. Connect existing Jo | Bounded context, memory and briefing operations over the current connection; reuse receipt/recovery patterns | Ownership/scope refusals, proposed versus accepted memory, payload limits and uncertain-save recovery pass; no broad private API access or paid fallback |
| 4. Morning experience | Scheduled-task instructions, Dashboard brief, Charts/context links and Useful / Meh / Missed something feedback | Phone/desktop walkthrough covers fresh, partial, stale, late, missing and duplicate results; evidence is accessible and chart settings preserved |
| 5. Activate and observe | After merge and separately approved grants/deployment/task activation, verify actual Jo delivery | Scheduled packet → Jo → saved receipt → app visibility → reopen observed; cancellation verified; distinguish receipt, app availability and any notification delivery |
| 6. Decide whether to keep | Ten scheduled mornings of delivery and owner feedback | Report every expected morning, lateness/gaps, opens and ratings; owner judges five-minute usefulness and omissions, including no-trade days; keep, simplify or stop before expanding |

**First implementation slice (merged PR #342):** private owner save/read APIs under
`/jo` use `backend/app/engine/jo_briefing.py` and
`backend/app/routers/jo_briefing.py`. Memory amendments append revisions with
explicit owner acceptance; stale amendments conflict. Packets reference exact
active memory revisions and contain supplied evidence, not an automatically
collected portfolio. Briefings cite that packet and corrections append new
records. Both packet/output provenance and reported author/model remain
owner-supplied, not proof of an actual Jo call. Redaction removes the selected
record's text (all revisions for a memory), retaining ID/hash tombstones;
copies in other artifacts, conversations, exports or backups are not erased.
Packet and briefing text can be redacted separately. No assistant/service grants,
MCP tools, model calls, publisher, UI or schedule are added in this slice.
This slice alone did not activate Jo; see the October 19 activation evidence below.

**Second slice — existing-connection tools (merged PR #343):** `jo_context(packet_id)`,
`jo_memory_propose(packet_id, memory)`, `jo_briefing_submit(briefing)` and
`jo_receipt(operation_id)` extend the same Check MCP resource, identity and
Auth0 application. The default-off `jo_briefing_enabled` configuration requires
the existing market-watch snapshot/outbox directories; no new service, socket,
database or login is introduced. It advertises `jo:read` and `jo:submit` only
when enabled, with `check:read` still required. Existing grants alone do not
permit personal tools. Config/profile revocation is checked on every call.

The private owner command `backend/jo_briefing_owner.py --config <approved-check-config>`
provides `publish --packet-id <id> [--lifetime-hours 4]` and
`import --operation-id <id>`. Publication exposes only that saved packet and
its exact memory revisions to the configured Check profile, for at most
24 hours. It does not collect holdings, the watchlist or conversation history.
Manual publication requires the packet ID. The third slice below adds automatic
collection/publication/import and a current-day pointer without new infrastructure.
Run these commands only against separately approved data/bindings; no live
commands or new grants are included in this implementation.

Jo submissions use the existing outbox, with bounded immutable actor/operation
keys. `pending_import` means queued, **not app-saved**. The explicit owner import
validates context/citations again, commits through the existing storage engine,
and publishes a text-free receipt with saved IDs; `saved` means committed,
`rejected` means no accepted write for that operation. An exact retry or receipt
read recovers an uncertain call, including DB-commit/export-failure recovery.
Jo can only propose new memories; owner acceptance/amendment/retirement/redaction
remain private. Briefing corrections append and must reference this actor's
imported record. No notification or monitoring is implied by a save.

Published files are copies: app redaction does not erase an already published
packet or model context. Future imports refuse changed/redacted context;
revocation/expiry prevents new tool reads, and export cleanup is an activation
procedure. Receipts intentionally omit saved text. Authenticated submission
receipts establish which Check profile submitted content; author/model fields
remain self-report, and original packet evidence remains owner-supplied.
Shadow's explicit packet, decision code and workflow are unchanged; shared
reasoning remains `independence-unverified`.

### Automatic publication/import and morning UI

The existing private API lifespan runs `backend/app/engine/jo_morning.py` every
30 seconds only when `JO_MORNING_CONFIG` names an enabled local JSON configuration.
There is no new service or inference worker. The configuration must supply the
absolute existing Check configuration path and explicit account UUIDs:

```json
{
  "enabled": true,
  "check_config": "/absolute/path/to/approved-check-config.json",
  "account_ids": ["approved-account-uuid"],
  "publish_time": "08:45",
  "deadline": "09:15"
}
```

The owner selected these times in America/New_York on October 19, with Roth IRA only.
Before activation, approve accounts/fields, times, the Check profile/grants and
file permissions, then set the environment path on the existing API. The API
must be able to read that configuration and use the existing snapshot/outbox
directories. Synthetic trial mode refuses this runner. Do not change the bound
profile, scope or times mid-session: the dated pointer is immutable; a conflicting
replacement refuses publication rather than silently switching context.

On a confirmed open exchange session, publication starts at the configured time
and stops at the exchange open. The existing Charts calendar supplies holidays
and early-open information; unavailable calendars fail closed. Imports continue
outside that window while enabled. One deterministic packet per scope/day survives
restarts and retries without refreshing its cutoff or four-hour expiry. The
collector exports only allowlisted saved fields: approved-account remaining FIFO
positions, actual saved watchlist/levels, latest ten captures within 30 days,
up to thirty active memory revisions, and a prior saved brief summary matching
the current account scope and Check profile among the latest thirty records. Account
names/IDs, fill source keys, images/audio/transcripts and Webull accounts are
excluded. Counts/text and UTF-8 byte totals are bounded and omissions/truncation are disclosed. The morning publisher adds bounded stock-trade observations and headlines through
the existing Alpaca adapters; option-risk data and journal freshness remain unverified. Prior
briefs, memories, captures and saved levels are interpretations, not market facts.

`jo_morning_context()` retrieves only today's published pointer through the same
Check connection and `check:read jo:read` authorization. The first successful read per
profile and New York day leaves one immutable `jo-read-<profile>-<day>.json`
marker in the existing outbox (profile, day, packet ID and Check's receipt time;
no content). Later reads keep it, and a failed marker write never fails the read.
`/jo/morning` reports it as `delivery.context_read` / `context_read_at`, so a
missed brief separates "no read" from "read but nothing arrived". A missing marker
reads as `not_recorded` only once an earlier day's marker proves the trace is live;
before that (an un-upgraded Check runtime, or days before the trace) it stays
`unknown`. The API autodeploys, but the Check runtime upgrade is a separate owner
step, as is refreshing the connector's tool metadata. A read shows the
tool was called; it does not prove who started the run or how Jo used the packet. Submissions keep the
existing `jo:submit` grant, validation, expiry and receipt protocol. The importer
skips completed receipts, rotates bounded pending batches, and tolerates malformed
files without blocking publication. Disable the configuration to stop both
publication and import; stop/cancel the Jo task separately. Existing exported
copies remain subject to their expiry and the explicit cleanup procedure.

Morning-context failures distinguish a missing packet (`morning_packet_missing`),
unreadable files (`morning_packet_unreadable`), invalid/expired context
(`morning_packet_invalid`) and other exchange I/O failures
(`morning_exchange_unavailable`). These are read failures before generation or
submission, not failed briefing saves. Details never include paths, packet text
or exception messages. The API's morning-loop status/log includes the exception
class, without its message, so an owner can distinguish a permission failure
from a validation failure. Check runtime and connector metadata updates remain
separate from app deployment.

When investigating a missing morning packet, test the configured Check binding
under the API service's Unix identity, not just root. The API needs its already
approved read access to that exact configuration and traversal of its parent.
Replacing a configuration file can discard a named-user ACL even when its
owner/group/mode look unchanged. Preserve the approved ACL across replacements;
do not solve this by adding the API user to the Check service group or making
the configuration public. Restoring production access requires owner approval.

The Daily Review's Jo timeline labels publication **Morning data ready** and
shows **Morning data read** separately only when both a recorded marker and its
timestamp exist. Publication does not wake Jo; the read does not establish the
task's start time or origin. Missing/unknown markers and older responses without
these fields never manufacture a read from the publication or briefing time.
The external task schedule is not measured by the gap between these two rows.

**Installed Jo task instructions (October 19):** On approved exchange mornings
after publication, call `jo_morning_context`. If unavailable, report the gap; never
substitute yesterday's brief or invent positions. Use the returned frozen packet
and exact memory revisions. Keep beliefs separate from facts, disclose missing
quotes/news and source times, and do not present research absent from the packet
as cited evidence. Submit at most three priorities with personal relevance,
changes, contrary evidence and reasons to wait using `jo_briefing_submit` and a
stable operation ID. Read `jo_receipt` until saved or rejected; `pending_import`
is not success, and an uncertain call must reuse the same operation ID. Do not
trade, activate plans, alter Shadow or promote memory proposals to accepted memory.
The existing schema accepts packet citations only; external research enrichment
requires a separately approved packet update and is not added by this slice.

The owner Dashboard card links to `/morning` with date/version reopening, explicit
late/stale/missing/closed/unavailable states, evidence/source timestamps, Charts
links, a copyable Jo reference and persisted Useful / Meh / Missed something
feedback. First full-view opens are recorded best-effort; a failed telemetry write
does not block reading. Feedback errors are shown and can be retried. The private
browser proxy permits owner routes and refuses assistant-profile access. Neither
viewing nor saving feedback triggers inference, notifications or chart changes.
No result silently falls back to another date. Reads use saved content only.

Fixture acceptance covers once-per-session publication, restart/retry, partial
fills and account exclusions, actual MCP read/submit/import receipts, off/closed/
unknown-calendar states, late imports, redaction, version/date selection, feedback
persistence/errors and desktop/390px phone interactions. Actual Jo scheduling,
production permissions and natural delivery require separate step-5 evidence below.

### Briefing readability

The morning page opens with a compact header: the briefing date, an honest
status (Ready, Late, Missing, Waiting, …), saved/context/due times, date/version
controls and the saved scope. Late arrival, evidence at least four hours old and
unknown delivery status are separate visible warnings. **Today’s focus** follows
directly; summaries longer than 360 characters are clamped, with the verbatim
text one tap away under **Read Jo’s full summary**. Old saved records are not
rewritten or rounded by the UI.

Each ranked priority shows the review task, **Why you**, **Before acting**,
**What changed** and **Counterpoint** in the reading flow, with Open chart and
**Ask Jo about …** beside it. Citations read as saved source labels with observed
times (for example "Alpaca IEX latest trade · observed 8:44 AM ET"), grouped by
source; exact evidence IDs stay in the evidence list. Ask Jo builds a copyable
reference with the briefing and packet IDs, the selected priority and its
evidence IDs, plus an optional question. It copies text only (with a fallback
for non-secure pages and an honest failure message); it does not open Jo, start
a task or guarantee an expired packet is still readable. Feedback sits after the
priorities; coverage gaps, evidence and briefing IDs stay in details below it.
Charts links still carry only the symbol. No supported priorities is an explicit
state, not a reason to manufacture an extra item.

A priority that cites a saved memory shows it under **Your saved view** with its
kind, symbol, revision number and save time, linked to **Your saved memories in
this packet**: the exact revisions the packet referenced, with interpretation,
source and revision/memory IDs. A citation is paired with a revision only when its
saved wording and save time match exactly one referenced revision; otherwise it
stays a plain source label. Later corrections or retirements do not change an old
brief. A packet with no memories says so under the focus. Ask Jo includes the
selected priority's memory revision IDs.

**Saved memories** (`/morning/memories`, owner-only, linked from the brief) lists
Jo's proposals, active and retired memories through the existing owner
`/jo/memories` routes. The owner can accept a proposal (as-is or edited), decline
it, correct an active memory, retire one with a confirming click, or add a new
belief. Every action appends an owner-confirmed revision and keeps the original
source and reference; nothing in the screen redacts or deletes. An uncertain save
keeps its operation ID only for an identical retry and reloads the list first;
a changed request gets a new ID; revision conflicts close the editor on the newer
version. Active memories reach Jo only through the next morning packet (latest 30).

Not yet built for this roadmap: returning from Charts with the brief/symbol/
evidence still selected.
Usefulness still rests on the ten scheduled mornings and owner ratings.

The `jo_briefing_submit` tool description carries the writing guidance for future
briefs: a 1–2 sentence summary (45 words maximum), at most three useful priorities,
short task-led `what_matters`, one sentence of personal relevance and a concrete
`watch_out` check. Material counterpoints/risks must appear in that always-visible
check too. Shared caveats appear once in limitations; diagnostics stay out of the
main prose. Citation IDs belong in the citation fields. Display costs to cents
and fractional quantities approximately, retaining exact evidence and strike/level
precision. These are generation instructions, not new validation limits.

After this change is merged and released, refresh the existing Check v4 tool
metadata so Jo receives the revised writing instructions. This source change does
not update the live task, regenerate historical briefs, fetch fresh market context
or establish that an actual Jo-generated brief meets the new writing targets.

**October 20 validation recovery:** the scheduled submission failed before reaching
Check because the connector full-matched the exported nonblank `\S` pattern,
rejecting ordinary strings including author `Jo`. Whole-string nonblank patterns
retain blank rejection and length bounds. A regression against exported MCP
schemas reproduces the failure; focused submission/import/recovery tests pass.
The owner-authorized one-file Check runtime repair preserves the original runtime
commit with explicit hotfix provenance, verifies the full installation inventory,
retains rollback copies and restarts only Check. Refreshing Check v4 tools then
allowed a manually recovered two-priority briefing against the original October 20
packet. Its receipt confirmed an app save at **09:26:56 ET**; the owner UI showed
APLD before NBIS and the correct packet/briefing IDs. The **09:15 target was missed**.
This proves the recovered connector save, not natural scheduled delivery or useful
current market coverage. The frozen stale-price, missing-option-mark and
independence-unverified limitations remain; no schedule, grants or Shadow workflow
were changed.

`backend/tests/test_check_tool_schemas.py` now covers every tool the Check
connector can register (Jo briefing, pre-trade, review, position, market-watch,
stock-alert, Shadow and conditional-plan tools): realistic arguments are validated
against each exported input schema with formats checked and patterns full-matched,
and a newly registered tool fails CI until it has sample arguments there.

### Delivery honesty and the morning watchdog

`GET /jo/morning` adds a `delivery` block for the day's **scheduled obligation**.
Only a record citing the day's own scheduled packet (its exact `morning-` operation
key for the configured scope, times and Check profile) fulfils it. Briefs on other
same-day packets (manual or recovery requests) are counted as `other_briefings`;
they are never the scheduled delivery. Fulfilment is judged on **journal
availability**, the record's `created_at` (when the importer committed it): a brief
Check received at 09:14 but imported at 09:40 missed a 09:15 deadline. `late`
keeps `late_by_seconds`, so a later recovery never erases the miss. A separate
`morning_briefing_submission` table (committed with the record, which stays
unchanged) records when Check received an imported submission as `submitted_at`;
the gap is `import_lag_seconds`. It is unknown (null) for owner saves and for every
record imported before this change. The deadline is the one frozen in the scheduled packet.
Past days are judged with today's configuration, so a day before automation was on
can read as "not published". Who started a run (the scheduled task or a manual
chat request) is not visible to TradeJournal: `origin` is always `unknown`.

`automation` also reports the runner's `last_status` and `pending` (this profile's
submissions still lacking a receipt, the oldest Check receipt time, and unreadable
outbox files). `delivery.notifications.chatgpt` is always `not_observable`;
`watchdog` reports what the phone watchdog recorded for that date.
`GET /jo/morning?month=YYYY-MM` (instead of `day`) returns just each weekday's
`publication`, `fulfilment`, `deadline`, `available_at`, `late_by_seconds` and
`watchdog_notices` for the Daily Review calendar, skipping days before the first
morning packet ever published (no record, not a miss).

The watchdog is the existing `deploy/alerts.py` timer (a separate process from the
API), opt-in with `JO_MORNING_ALERTS=true` in `alerts.env`; it is off until set.
It reads `/jo/morning` each pass and alerts once per condition:
brief missing at the deadline (no grace; a late save sends one "arrived late"
recovery), packet not published five minutes after publication time (replacing the
missing-brief alert, since the packet explains it), runner pass older than three
minutes or morning settings that fail to load (five-minute grace, like the API
alert), a submission waiting more than two minutes for import, an outbox file that
can never import, an unavailable market calendar on a weekday (15-minute grace;
weekends leave it unchanged), and `/jo/morning` itself unreadable while the rest of
the API answers (10-minute grace). Pending, unreadable and calendar facts count
only while the runner is fresh. When the API is down, the existing "isn't
responding" alert covers it and morning conditions keep their state. Settings that
fail to load leave the brief and packet conditions unknown, never "resolved";
deliberately disabling the morning automation or the watchdog ends them silently.
Day conditions end silently at the next New York date; notices are kept for seven
days in `/var/lib/tradejournal/alerts/state.json`, which the API reads to show
them, with retries of one failed notice collapsed into a single line. A morning
send that times out while waiting for ntfy's reply is recorded `unknown` and **not
resent**; a send that clearly failed, including a connect timeout, is retried on
the next pass. ntfy accepting a message does not prove the phone displayed it.

Failure domains this can and cannot see: a stopped runner, stalled import,
unreadable file, unpublished packet, unavailable calendar and a brief absent at the
deadline are visible. A hosted task that never ran, ran late or failed ChatGPT-side
schema validation (October 20) is visible only as absence at the deadline. A stopped
alerts timer is visible only to the dead-man's switch (`HEALTHCHECK_PING_URL`),
configured in the VPS `alerts.env` as of October 21.

Initial operational acceptance, after separately approved deployment and
activation: five consecutive exchange mornings, reported as two numbers. Watchdog
correctness (target 5/5): each morning classified correctly, every miss alerted
within its grace, and at least one push confirmed on the owner's phone. Delivery
(reported as x/5): on time by journal availability, each miss explained by failure
domain. This is separate from the ten-morning usefulness decision in step 6.

### Fresh market context — activated October 19

The morning publisher originally made at most two existing-provider reads when creating a
new packet: one Tradier full-market quote request and one fast Alpaca news request
(extended by the [market backdrop](#market-backdrop--october-21) below). Both use
the existing bounded, single-attempt adapters. Tradier must use its production
endpoint; missing credentials, errors or missing observations do not fall back to IEX. Only symbol names leave the app;
account identifiers, quantities, costs and memories are never sent to providers.
The scope is at most 20 unique stock symbols, approved holdings first and then
the saved watchlist. Unsupported/omitted symbols are disclosed. No replacement
watchlist, new service, credentials, paid inference or alternate provider is added.

Each accepted last trade retains its provider observation time separately from
actual retrieval time, feed name and stock-only/unadjusted basis. Observations
after actual retrieval, invalid prices and missing timestamps are omitted.
Trades older than ten minutes are labelled stale, including prior-session trades
returned by newly fetched quotes. Full-market coverage does not make a stale trade current. No return,
P&L, split-adjusted daily change, option quote or executable bid/ask is inferred.

Headlines are at most eight relevant, deduplicated HTTPS articles from the prior
36 hours, retaining publication time and source URL. Future/undated/out-of-window
articles are excluded; article claims are not independent verification. Empty or
failed results never mean no catalysts. Earnings and macro-calendar completeness
remain gaps. Price and news failures degrade independently and do not prevent a
saved-context briefing. No network call occurs on page reads or when republishing
an existing packet after a restart; the saved packet and expiry remain immutable.

Deploying this slice with the existing enabled morning configuration automatically
adds these reads to the next new packet; there is no extra activation flag.
Before deploying it, replace the live task's old “No live quote/news
fetch is included” sentence with: “Use only the returned frozen market evidence,
when present. Report source times/feed and stale or missing observations. A recent
retrieval is not a current price, and missing headlines do not mean no catalysts.”
Keep account scope, schedule, authentication and Shadow instructions unchanged.
Verify actual provider coverage and a natural Jo brief after release; fixture
coverage alone does not establish useful premarket prices or news availability.

Merged #349 is active in release `53879202d0a5-39309047280-1`, after successful
main CI, package smoke gates, checksum verification and guarded deployment.
The existing task now uses `jo-morning-v2`, retaining Roth IRA-only scope and
the weekday 09:00 ET schedule. Authentication, Check runtime and Shadow settings
were unchanged. A separately keyed manual afternoon packet collected at 15:30 ET
contained 20 IEX stock observations aged 0–66 seconds and eight headlines.
Actual Jo submitted a two-priority briefing, receipt-confirmed saved at 15:31 ET;
the private API and reloaded UI matched its packet, record and evidence citations.
The earlier briefing and scheduled day pointer were preserved. This establishes
the instructed fresh-data path, not natural morning delivery or usefulness of
premarket coverage; those remain unobserved.

### Market backdrop — October 21

The first scored brief (October 21) had no macro context: every price was the
prior 16:00 trade and nothing described the market. New packets now add, each
failing alone into a gap line and never blocking publication:

- **Extended-hours prices.** After the one batched quote read, each priced
  symbol gets one cached Tradier 1-minute `timesales` read (`session_filter=all`,
  the request level alerts already make), bounded by a 45-second budget. Today's
  last minute becomes `market-<SYMBOL>` with its bar time and the change against
  the quote's prior regular-session last trade (not an official close). With no
  minute today, the quote's regular-session trade stays, labelled stale. SPY, QQQ
  and SMH are always priced as backdrop proxies, outside the 20 owner symbols.
- **`macro-calendar`**: FOMC, CPI and jobs releases from today through the next
  seven days, from the Daily Review's `macro_events` reader.
- **`vix`** and **`earnings-<SYMBOL>`**: the pre-trade check's `market_context_item`
  snapshot (no new provider read), with its read time; earnings within seven days
  for held, recently traded and watched symbols.
- **`macro-headline-<n>`**: at most four broad-tape Benzinga headlines from the
  prior 18 hours whose title names a market-wide theme (Fed, rates, inflation,
  tariffs, war, oil, dollar and similar), with the ticker headlines' labelling.

Index futures, Treasury yields, the dollar and oil remain unavailable without new
provider access; the packet says so. The Check tool descriptions ask Jo to open
with a cited market backdrop (summary up to 60 words), then position items, and to
compress shared caveats into one or two limitations lines. Deploying this requires
a Check runtime upgrade for the new tool descriptions and a ChatGPT connector refresh.

### October 19 activation evidence

The owner approved Roth IRA only, 08:45 ET publication and a 09:15 ET deadline,
then explicitly approved an immediate market-hours restart. Merged #344 release
`3d50d64fdbcd` passed main CI and the Ubuntu deployment package gates. Its archive
checksums and commit metadata were verified. Installation first stopped for disk
exhaustion before migration or activation; the old app stayed healthy. With owner
approval, five obsolete Check runtime copies were removed, retaining the running
runtime and newest rollback copy. The retry completed after a fresh verified
backup and the existing guarded migration/activation procedure.

The existing Check runtime and API are enabled; no new service, database, OAuth
client or connector was created. Only `jo:read` and `jo:submit` were added to the
existing interactive grant; existing machine-to-machine grants were preserved.
The Check configuration differs only by personal-Jo enablement. Shadow settings,
identities and execution rules remain unchanged. Effective service-user checks
confirmed the exact configuration/exchange grants and denial of private API
credentials and the Check ledger. Configuration-directory traversal is required
in addition to read permission on the two exact configuration files; it grants
neither directory listing nor reads of sibling credentials.

The existing **TJ Premarket Brief** task now runs weekdays at **09:00 ET**, using
the frozen Roth packet, at most three cited priorities, stable operation IDs and
receipt checks. Its first scheduled run is October 20. The UI time picker uses
15-minute increments; 09:00 leaves time after publication and before the deadline.
No separate email/push or paid inference fallback was enabled.

A manual activation packet was collected and published at **13:33:18 ET on
October 19** with its actual time and a four-hour expiry. It explicitly identifies
itself as a late activation test. This marks the personal-context activation
boundary for subsequent Shadow reviews; independence remains unverified.
The live owner UI showed the actual packet and explicit missing-brief state.
Actual Jo attempted the new context read, but ChatGPT reported an expired
connection after automated reconnect attempts; owner reconnect/consent is the
current handoff. No Jo-generated briefing has been claimed saved. Natural scheduled delivery,
cancellation and owner usefulness remain separate acceptance items; this manual
packet must not be counted as a successful scheduled morning.

Every factual claim needs traceable evidence and source times; interpretation,
uncertainty and missing/stale data remain visible. "What changed" compares frozen
records, not reconstructed recollections. No result by the deadline means an
explicit unavailable/late state with available factual context, never yesterday's
brief labelled current. A tool attempt is not a save; a valid citation is not
proof of correct interpretation. The October 15 reference-limit refusal and its
task fix motivate schema checks and receipt-based completion, not a claim that
scheduling is either reliable or broken.

Use small PRs under the existing [review policy](pr-review.md): migrations,
financial semantics, sensitive-data authorization and activation/deployment are
tier 2; a cross-surface UI integration is tier 1 unless it changes those boundaries.
Complete applicable review/CI and UI checks; merging follows the
[PR completion rules](pr-review.md#automatic-repair-and-merge). Fixture proof,
installed state, natural scheduled execution and usefulness are separate evidence.
Later evaluation keeps market forecasts, plan adherence and long-term thesis
changes distinct; clicks/ratings alone establish neither trading edge nor returns.

## Existing architecture and later scope

The [cloud MCP scope](cloud-mcp-integration-scope.md) owns structured access;
the [browser contract](cloud-browser-auth-contract.md) owns the separate assistant
UI entrance. Browser login and connector OAuth are distinct. The synthetic,
practice, journal and advisor roles have different grants and acceptance; no
broad local stdio adapter is suitable for an independent runner.

The selected connector route uses ChatGPT plan reasoning with no API-credit
model path. Keep the production private API private. Existing role contracts,
backend authorization and separate activation gates remain authoritative.
The sections below retain the A1 and proposed shadow/follow-through design;
they are not statements that the accepted journal connector is absent.

## Current A1 interface

The current adapter is [`backend/mcp_server.py`](../../backend/mcp_server.py),
a local stdio FastMCP server. It calls the private FastAPI service; the backend
owns validation and persistence. A1 tools are:

| Tool | Inputs | Result |
|---|---|---|
| `get_decision_context(symbol, operation_id)` | Symbol and retry key | Fetches a ticker packet and durably freezes it. Returns `context_id`, server capture time, provider, context digest, packet and completed-minute price facts. Repeating the operation key returns that same snapshot. |
| `record_decision(operation_id, opportunity_id, actor, decision, symbol, context_id, rationale, wait_condition, wait_expiry, plan)` | Decision metadata plus the saved context ID. `plan` is used only for TAKE; WAIT needs a condition and expiry; SKIP needs a reason. | Creates an immutable record bound to the server-owned context. Identical retries return the existing row; changed content with the same key conflicts. |
| `get_decision(record_id)` | Record UUID | Returns the saved decision, exact evidence, hashes and receipt/cutoff times. |
| `list_decisions(limit)` | Optional bounded page size | Returns recent records. |

Every A1 response is labeled `practice_draft_unarmed`. A TAKE must reference
completed raw Alpaca minute facts by their saved fact names. Source, formation
and observation times, USD/share unit, and raw split basis are retained. The
validator rejects missing, stale, future, mismatched or non-finite facts, and
requires an explicit freshness limit, entry guard and versioned nonnegative
slippage parameters. The [selected P0 operating policy](practice-policy.md) now
fixes the universe and worked example. Its complete `shadow-isaac-p0-v1`
version/hash and eligibility checks must be stored at a future A2 arm; the
current A1 schema hash alone does not make a draft prospectively eligible.

## Requirements before connecting another agent

The requirements below govern an independent shadow runner. The personal Dot's
initial reviewer/inspector catalog is scoped separately in the
[cloud connector plan](cloud-mcp-integration-scope.md); the backend, identity
and transport boundaries apply to both roles.

1. Confirm Dots' actual supported transport and authentication contract. Do
   not assume it can launch a local stdio process or call this API.
2. Create a separate shadow-agent tool profile that includes only market
   context and the agent's own decision records. Exclude fills, journal trades,
   account data, Isaac's decisions and all journal-analysis tools.
3. Enforce the same capability policy in backend services. Hiding tools from an
   MCP catalog is not access control. Legacy private mode has no authentication
   and accepts a caller-supplied actor. Optional authenticated mode has browser
   principals and named service capabilities; decision writes derive the actor
   for owner/manual MCP identities. The scoped cloud services have their own
   OAuth and ownership contracts;
   the broad local adapter is not a substitute for those services or proof of
   independent shadow isolation.
4. If Dots is remote, design a separately scoped gateway/identity on the private
   host. The cloud scope selects direct HTTPS/OAuth to a
   restricted MCP service with named operations. Do not expose or tunnel ports
   8080/8000, do not give
   the agent raw HTTP or shell access, and do not add a proxy that forwards
   arbitrary API routes. Public access requires a new reviewed security design.
5. Test allowlisted tool discovery, denied journal reads/writes at the service
   layer, idempotent decision submission, identity attribution, timeouts and
   failure behavior before enabling a Dots connection.

Until those gates are met, use the existing local MCP adapter for manual
preparation only. The current adapter advertises the existing all-journal
profile as well as A1 tools; do not give it to an independent shadow agent.

## Proposed restricted shadow-agent profile (design only)

Superseded as the target by the [shadow trader design](shadow-trader-design.md), which allows closed-history reads and a fuller trader toolset; the backend authorization rules below still apply.


Keep the existing MCP adapter as a local manual toolset. Build a **separate** `shadow_agent_v1` catalog whose only capabilities are `get_decision_context` for a P0 universe symbol, `record_decision` for the authenticated shadow actor, `get_decision` for that actor's own record ID, and `list_decisions` filtered to that actor with a strict page limit. A future read-only status tool may expose only the agent's own plan/paper events after A2 exists. No journal fills, trades, accounts, human decisions, raw database access, arbitrary URL fetch, shell, factory writer, alert administration, or generic HTTP proxy belongs in this profile. Tool names are a convenience; backend authorization is authoritative.

At the service boundary, authenticate a per-client capability on **every** request before route logic, map it server-side to an immutable principal such as `shadow-isaac`, and derive `actor=agent:shadow-isaac` there rather than trusting the submitted field. Authorize operation plus resource owner: context create/read only for allowlisted symbols and bounded rate; record create only with the caller's own saved context, P0 policy version and daily cap; record get/list only for that principal; no access to `/trades`, `/fills`, `/accounts`, journal analytics, human rows or unrelated contexts. Give the capability no paper-arm or alert-write right in A1. Scope any later A2 arm right separately to an explicit reviewed policy and the agent's own TAKE records. Deny by default in the service even if an endpoint is reached outside MCP. Keep an audit trail of principal, operation, record ID, outcome and request time without secrets or unrestricted payloads. Expire and rotate credentials; bound request size, rate and deadline. Test forged actor/context/record IDs, catalog omissions versus direct-route calls, idempotent retry, timeout and revocation.

A remote Dots integration first needs its actual transport/auth contract and a separately reviewed narrow gateway on the private host. The gateway would expose only named operations above and forward an authenticated principal, never the private API port or arbitrary route paths. Until that design and negative authorization tests exist, no independent Dot receives a connector or the current broad adapter.

## Ownership boundary

Put business rules in `backend/app/engine/decisions.py` and typed HTTP routes in
`backend/app/routers/decisions.py`. MCP or a future Dots connector should only
translate tool inputs and outputs. Do not add Dots-specific columns, callback
formats, schedulers, credentials or a public tunnel to the decision schema.
The implementation sequence and A1/A2/A3 boundaries are in the
[agentic trading roadmap](../agentic-trading-roadmap.md).

## Roles and independent decisions

The personal Dot may know Isaac's decisions from prior conversation or memory.
A prompt asking it to disregard them cannot make its choice independent. Use
a separate restricted runner for Shadow Isaac, with an explicit recorded input
packet containing only permitted market/context/policy facts. Do not pass Dot
memory, human choices, journal activity or a summary that leaks those choices.
Verify the actual delegated payload and service authorization; a new thread
alone is not proof of isolation. Reveal paired decisions only after both are
committed, or label late/assisted/independence-unverified cases explicitly.

| Proposed role | Allowed scope | Boundary |
|---|---|---|
| Independent practice runner | Approved context and its own frozen decisions; later own paper events if separately granted | No human choices, coaching memory, accounts or journal tools before commitment |
| Personal review/coach | Explicitly granted reflections, commitments, opportunity outcomes and journal summaries | Human context is allowed; its decisions are not represented as blind comparisons |
| Research | Approved questions, sourced evidence and thesis-update proposals | No automatic policy changes, paper arming or journal mutation |
| Operational diagnosis | Sanitized freshness, coverage and delivery evidence | No credentials, raw database access, production repair or automatic deployment |

These roles are permission scopes, not a requirement to create four agents.
Enforce each at the service boundary; do not broaden the shadow catalog to
support coaching. Scope changes need explicit selection and authorization.

## Proposed follow-through capabilities

Build only the capability needed for a selected slice. The following are
design requirements, not existing tools, routes, tables or verified Dot APIs.

| Capability | Contract |
|---|---|
| Durable questions and commitments | Store owner, linked evidence/decision, original wording, version, due time or explicit condition, budget/expiry and open/resolved/expired/canceled state. Reference existing WAIT conditions; do not duplicate executable plans. |
| Changes since a saved cursor | Return authorized bounded events with stable IDs, source/observation times, versions, pagination and a resumable cursor. Surface retention gaps and stale sources; consumers deduplicate and recover after restart. No human-choice metadata may leak into the shadow scope. |
| Evidence-linked proposals | Separate suggested reflections, structured reasons and thesis amendments from accepted records. Retain original words and before/after-outcome timing; unresolved identity stays unresolved. Saving authority is explicit and corrections append history. |
| Action receipts | Return operation ID, accepted/rejected/pending status and resulting record/version. Same-key retries are idempotent; changed content conflicts. After an uncertain timeout, retrieve status before retrying. A conversational claim is not a persistence receipt. |
| Availability and interruption preferences | Version user-selected availability, timezone, quiet windows, channel and budget. Optional calendar access requires its own permission. Preferences cannot rewrite cohorts, execution policy or required exit/failure notices. |
| Usefulness and operational evidence | Link feedback and source/detection/delivery status to exact artifacts/events. Preserve unrated/unobserved states; expose bounded sanitized reports for diagnosis and weekly service review. |

A connection does not establish an active responsibility. For each selected
follow-up, retain its confirmed schedule or supported event subscription,
timezone, destination, next due/check state, last success/failure and cancellation
status. Verify one actual run and a stop/cancel path. Bound calls, cost, retries
and notification volume. Polling may be an initial fallback only after the
transport is verified. Deterministic monitoring of existing positions must
continue if Dot, its model, a schedule or the connected computer is unavailable.

Before claiming a capability works, test ownership denial and identity spoofing,
proposal/acceptance separation, duplicate and out-of-order events, cursor gaps,
restart recovery, uncertain writes, cancellation and revocation. Observe a real
connection and resulting persisted record; test fixtures do not establish live
delivery. Existing A1 tools do not satisfy these proposed contracts by name.

Prioritize conversational reasons, follow-ups and feedback through their
[product owners](../product-roadmap.md#dots-assisted-learning-extensions-proposed).
Thesis evidence monitoring and operational diagnosis follow the
[agentic expansion](../agentic-trading-roadmap.md#17-dots-follow-through-expansion-proposed).
Preserve A1–A3 scope; do not build a general workflow engine or publish the
private API to make the integration convenient.

## Selected sample replay increment (2026-10-09)

Isaac selected [Jo’s own sample paper replay](dot-sample-replay-contract.md) after
reporting the original MU/NBIS WAIT save/reload/reopen acceptance. A new scoped
login may start its own TAKE replay on a separate frozen exercise. This adds no
live exposure, P0 universe change, active WAIT monitor, model calls or schedule.

### Opportunity-first morning brief — October 21

New generation uses `jo-morning-v4`: market context first, up to three new
opportunities outside the approved account holdings **and** saved Charts
watchlist, then at most two short urgent position reviews. Urgent reviews cover
imminent expiry, material new position events or time-sensitive risk; they do not
become a portfolio inventory. Historical `items` briefs retain their original
labels/content. Daily Review’s Jo timeline includes both new sections and the
setup’s conditions, status and timeframe. Existing packet/briefing records are
not rewritten.

The publisher reads one broad-tape news page (at most 50 stories, past 36 hours)
independent of saved symbols. Valid HTTPS stories with observation times in that
window introduce at most six new US ticker candidates, material-catalyst keywords
first and recency second. All approved open holding tickers and the entire valid
saved watchlist are excluded, including names beyond the existing display/quote
caps. `discovery-scope` discloses coverage; `discovery-<SYMBOL>` records the reported
catalyst and source URL. This is bounded news-led discovery, **not** a whole-market
mover, liquidity or relative-volume screen. No new provider or model service is
added. Broad-news failure is disclosed; it never becomes “no opportunities.”

SPY/QQQ/SMH are priced first, then discovery candidates, then the existing bounded
saved symbols. The same single Tradier quote request and 45-second minute-read
budget apply. Completed same-day premarket minutes add `setup-<SYMBOL>` range
high/low, reported volume and returned-minute count (minimum two minutes and
positive volume). The range retains its own last-minute timestamp; a later stock
trade cannot refresh it. Missing, sparse or stale minutes require research-only
ideas. Source observations/retrievals, partial coverage and unadjusted price-basis
caveats remain visible. The separate saved-symbol news page also samples up to 50
stories, prioritizes catalyst stories and keeps at most eight, with a two-story
per-symbol quota, so generic watchlist headlines do not take every slot.

The JSON briefing keeps legacy `items=[]` for new generation, adding bounded
`opportunities` and `urgent_positions` arrays. Opportunities require an entry
condition, invalidation, timeframe and `conditional` or `research_only` status.
Both owner saves and Check submissions validate citations; every opportunity
must cite its discovery evidence. Conditional setups additionally require cited
Tradier price **and** range evidence from the packet's ET date, each at most ten
minutes old at collection. A conditional setup still waits for its stated
trigger and a fresh spread/liquidity check; it is not an executed or activated
plan. Jo must not invent numeric levels, relative volume, sizing, targets or
option selections. Shared gaps belong in limitations; specific risks stay on
cards. Empty discovery is an explicit state, never filled with owned tickers.
Empty new arrays are omitted in serialized legacy requests to preserve existing
idempotency hashes. No migration is needed for the existing JSON bodies.

Release source changes alone do not update the live ChatGPT task or isolated
Check catalog. After merge/release, refresh Check's tool metadata and change the
existing morning task's writing instruction to: “Use jo-morning-v4. Read today's
jo_morning_context only. Lead with market context, then opportunities beyond my
holdings and watchlist using discovery evidence, with entry condition,
invalidation, timeframe and honest research-only status when confirmation is
missing. Keep urgent positions to a short final section. Submit items=[],
opportunities and urgent_positions; recover jo_receipt until saved or rejected.”
Retain the current account grant, weekday schedule, expiry, authentication and
Shadow ordering. Production activation and a natural morning's provider/Jo
acceptance are separate from fixture checks; neither is claimed by this change.

### SPY/QQQ morning prep — October 22 owner-selected slice

The Morning page has a collapsible SPY/QQQ prep block. It reuses the Charts
workspace's automatic levels (including developing and missing-source labels),
with selected-day chart links for setting existing price alerts. Opening today's
block fetches one bounded SPY/QQQ workspace request; historical days do not fetch
live levels. Refresh is explicit, and the map's own session date must match.

The owner records one macro sentence, a contract/size convention, 1–2 selected
higher-timeframe levels, and 2–3 scenarios total across both symbols. Each has
family, level, trigger, invalidation and time stop. Saving appends an owner outlook
to the existing day journal; it does not activate monitoring, change a chart
setting, publish new Jo evidence or place an order. Original receipt times remain
visible. Editable prep is recovered from a date-keyed local draft after chart
navigation or reload; it is not journal-saved until the server confirms. An
uncertain save retains its operation ID and payload for safe retry.
A freeze records the saved plan ID, scenario number and owner-reported trigger
time as an untraded idea, separately from a deliberate pass or invalidated setup.
Daily Review reads these existing journal entries. No new schema or grants.

This is the owner's bounded exception to new-feature ordering, supporting Dots
morning usefulness. Production activation and the owner's under-ten-minute
morning acceptance remain pending; browser fixtures prove the mechanics only.
