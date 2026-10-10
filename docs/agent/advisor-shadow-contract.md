# Advisor/shadow Phase 1: manual fixture session

Selected 2026-10-10. This chat owns these modules and the small A3 integration;
the journal chat confirmed it is only handling refresh/coaching. Journal source,
exports, identities, OAuth, gateways and deployment files are outside this change.

## Settled boundary

Use existing `PracticeRun`, five `PracticeOpportunity` rows, frozen
`DecisionContext`, `PracticeAgentCall` and immutable `DecisionRecord` storage.
The manual runner exclusively occupies A3's existing `agent:a3` slot in a
separate invented demo database; it cannot coexist with a paid adapter for that
run/day. Preserve the complete five-symbol batch, three-TAKE maximum, stable
`a3:{opportunity}:agent:a3` operations and existing reveal/receipt rules. No schema
or alternate accounting store is needed. P0 policy, universe, benchmark and A2
costs remain unchanged. Invented fixture prices cannot validate a P0 TAKE.

An operator-only CLI creates a fresh SQLite demo file, migrates it, freezes
invented market facts for all five P0 symbols and reserves a manual assignment.
It does not invoke preparation jobs, providers or model adapters. Its calendar
is explicitly unavailable. The run retains P0's 09:00 ET cutoff and honest late
status; an assignment separately expires after thirty minutes. Fixture WAIT/SKIP
is useful proof; no paper plan is armed. One assignment per database/day retains
the existing daily reservation constraint.

The separate loopback-only demo gateway exposes only authenticated `GET /packet`,
`POST /choices`, `GET /receipt`. A private capability file identifies exactly one
persisted assignment; the database holds its digest, expiry and enabled state.
Actor/context/policy IDs and operation keys are server-derived. Every request
checks current grant state; writes check again after bounded body reception,
under SQLite's writer lock shared with revocation. Invalid batches roll back in
full. Exact retries recover the entire original receipt before expiry validation
of choices; expired/revoked authentication still refuses access. Lost-response
recovery reads the receipt first. Packet/output bounds, a ten-second body
deadline, two-second SQLite lock timeout and four-request concurrency bound
fail closed. No wildcard routes,
HTTP proxy, shell, provider, paid job, journal, advisor or human read exists.

The exact frozen allowlist projection includes timestamps, source/units/basis,
coverage, IDs and context hashes, with its own canonical SHA-256. It excludes
raw packet notes, human choices, advisor content and continuation. Validate
stored context integrity and assignment equality on reads/writes. Receipts
contain only this assignment's records and neutral evidence, never raw packets.

## Advisor and disclosure

The private owner UI exports the same neutral packet plus one explicit question
and user plan. Before exposing this advisor packet, the backend makes a run
assisted unless all five human choices are already frozen. One immutable advisor
request and manually supplied structured answer are retained with receipt times.
The answer distinguishes interpretation, risks, proposed conditions and missing
inputs; factual citations resolve only to original packet fact IDs. Caller prose
is untrusted interpretation, not verified source facts. No backend inference or
fallback occurs. A fixture answer proves this interface, not actual plan inference.

Paired review reuses the existing Practice board/reveal and paper projections,
opens the exact packet/choices, and shows agreement/disagreement, nonresponse,
late/assisted labels and `independence-unverified` provenance. Manual transport,
unknown actual model/usage/cost, and fixture evidence are explicit. UI fixture
timings do not establish attention time or usefulness on real sessions.

## Proof and activation

Check exact retries/conflicts, malformed/full-batch rollback, forged identity or
assignment/context/policy, tampered evidence, missing/future/stale TAKE refusal,
direct-route and catalog denials, receipt-before-retry, expiry/revocation during
body reception, concurrent writes, restart/reopen, advisor-first disclosure and
generic A3 reveal routes. Run focused tests, fast/full verification, a real-backend
browser walkthrough and tier-2 native general/focused review, then exact-head CI.

The gateway is manual-only and absent from normal service packaging. Stop it to
roll back; disable its persisted grant before restart. Prior demo records remain
in the isolated file. The private API remains private. This adds no OAuth grants,
production activation, live captures, real journal changes or schedules.

The supported gateway executable re-execs before importing engines with only
PATH and its clean-process/dotenv-disable markers, then reads the private local
binding. The factory rejects ambient provider/model/database credentials and
enabled dotenv loading. No source .env or model key is part of runner input.

Actual signed-in-plan reasoning and runner memory/tool isolation, current product
capabilities, separate scoped cloud identity/transport, fresh cloud receipt/UI
equality and grouped restart are Phase 2 approval gates. An approved forward
capture, eligible common cutoff, explicit paper-arm authorization and three
human-timed applicable A3 sessions precede any recurring routine proposal. No
fixture, historical profit or endpoint success establishes independence or edge.

## Operator fixture walkthrough

From `backend`, choose a new private configuration path (never an existing
journal database):

```bash
.venv/bin/python scripts/advisor_shadow_demo.py create /private/tmp/tj-advisor-demo.json
.venv/bin/python advisor_shadow_demo.py /private/tmp/tj-advisor-demo.json --port 8138
```

The creation command reports the demo run ID and stores the capability privately;
never copy that file into chat or a runner packet. The gateway binds only loopback.
A local operator supplies the file's bearer capability to `GET /packet`, submits
`assignment_id`, `packet_sha256` and exactly five `choices` to `POST /choices`,
and reads `GET /receipt` after any uncertain response. Each choice supplies only
its opportunity UUID and A1 decision fields. The capability stays outside the
reasoning packet. The gateway has no human/advisor/journal route.

For owner review, run a disposable owner app against that specific demo SQLite
file with provider/model credentials empty, paid/schedule/listener/level-alert
startup disabled, and `TJ_MANUAL_FILLS_BACKUP` pointing at a separate nonexistent
fixture file. Use a frontend whose proxy points only at that loopback app. Open
`/?practice_run=<reported UUID>`; export the explicit advisor question and plan,
paste its structured answer, save human choices and use the existing paired review.
The ordinary app never imports the shadow gateway or discovers its capability file.
The automated browser configuration provides a representative seeded instance
with these isolation controls; it is the repeatable UI proof for this slice.

Revoke with `.venv/bin/python scripts/advisor_shadow_demo.py revoke
/private/tmp/tj-advisor-demo.json`, then stop the gateway. Restart refuses a
revoked/expired binding. Keep the SQLite file to preserve original receipts;
rollback does not migrate or delete any journal/paper data.

## Observed Phase-1 evidence (2026-10-10)

- Focused storage, denial, atomic rollback, exact retry, expiry/revocation,
  concurrency, owner auth, A3 regression and CLI/restart checks passed locally.
- A real-backend 390px browser scenario saved/reopened the neutral packet,
  advisor request and cited answer, durably labeled advice-first use assisted,
  submitted five shadow choices and displayed an exact human WAIT/agent SKIP
  disagreement. Existing A3 browser scenarios separately passed. This is fixture
  interaction evidence, not measured real-user attention/usefulness.
- A separate fresh migrated SQLite fixture was served over actual loopback HTTP.
  A Sol plan-based subagent received only the exported neutral packet in its
  task brief and returned five reasoned SKIPs. Manual submission, exact receipt
  read/retry equality, a real gateway process replacement and live local grant
  revocation passed. The advisor answered the sample SPY question with the
  original invented close citation and missing trigger/risk/calendar evidence;
  one subsequent human WAIT stayed assisted and four human nonresponses stayed
  unobserved. No paper event, provider capture or backend inference occurred.
- The subagent brief/file and gateway payload were observed. Its wider tools,
  memory and process isolation were not independently established; provenance
  remains `independence-unverified`, with actual model usage/cost unavailable.
  This is a local manually scoped plan demonstration, not actual cloud OAuth,
  ChatGPT Work runner isolation, deployment, laptop-off or forward acceptance.
- Broad verification, native review rounds and exact-head CI belong to the PR's
  completion record. No production service/grant/export/schedule was changed.
