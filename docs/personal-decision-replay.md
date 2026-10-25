# Personal Decision Replay Lab

The owner opens **Daily Practice → Open a replay** (`/practice/replay`) to work
through two moments in one invented options trade. V1 is a fixture exercise,
not an import of the owner's history, a strategy test or an AI assessment.

## Workflow

1. Start the scenario. The backend creates a durable frozen attempt; the URL
   retains its ID for reloads and return visits.
2. Read only the completed underlying candles, option-position reference marks
   and original plan available at the checkpoint. Choose hold, reduce or exit;
   a short reason is optional.
3. Save the choice. The decision and evidence fingerprint are fixed before
   **Reveal what happened next** becomes available.
4. Reveal the first segment. Compare the choice with the scenario's historical
   action, then decide at the next checkpoint. This is a fresh decision about
   the original position: an earlier practice exit does not change its history.
5. Reveal the close and compare both decisions. Synthetic recorded fills are
   distinct from reference marks. No hypothetical execution or counterfactual
   profit is assigned. Repeating the scenario is labeled as repeated practice.

The chart uses the existing `FrozenSampleChart` and its completed-minute and
partial-15-minute rendering. It has no live feed. The feature calls no model,
creates no paper orders, and writes no fills, journal trades or Copilot memory.

## Reuse audit and boundaries

| Existing capability | Reuse or reason to keep separate |
| --- | --- |
| Historical Charts and trade navigation | The full Charts workspace reads journal, quote and symbol context. Embedding it would risk exposing current or completed-trade facts. Replay reuses the existing frozen chart instead. |
| Journal, FIFO and canonical identity | Real trade IDs and `capture_links` already provide rebuild-stable source anchors via account plus entry `raw_email_id`. V1 creates no second journal and does not invent real trade IDs. An approved importer should resolve those anchors and freeze only eligible source facts. |
| `TradePathMetrics` and option history | Path summaries include final results and whole-trade extrema. They are unsuitable for a checkpoint packet. Historical minute marks can support labeled estimates when coverage is adequate; they cannot supply missing bid/ask or executable fills. |
| Chart captures and captured plans | Existing immutable capture receipt times and linked-entry timing are the right source for original plans. Later edits, voice transcripts received later and retrospective notes must not be backdated into a replay. V1's plan is explicitly invented and timestamped. |
| Practice decisions and paper plans | Reuses the Practice entry point, immutable-choice vocabulary and canonical JSON hashing. A1 supports stock-entry TAKE/WAIT/SKIP; A2 executes its own paper policy. Option-position HOLD/REDUCE/EXIT needs a small separate Practice receipt table, not changes to those financial engines. |
| Jo sample/historical replay | Reuses the pattern of frozen evidence, precommitted continuation, idempotent writes and explicit reveals. Those services are scoped to Jo identities/grants and TAKE-trigger paper outcomes, so their routes and grants remain separate. |
| Research Studio | Its frozen parents, explicit exposures and append-only conclusions motivate snapshot persistence and repeated-attempt disclosure. No sidecar, Factory candidate search, protected-period data or research ledger is read. |
| Copilot Lab | Its current owner context and closed-trade review intentionally expose today's holdings and retrospective data. Replay has an internal neutral-packet projection only, with no model adapter or tool registration. A future comparison must receive exactly that packet and a matching hash, never the ordinary context pack. |
| Browser fixtures and caches | The existing Playwright seeded SQLite backend and frozen chart run this complete workflow without provider keys. No production cache or private snapshot is read. |

The audited Copilot changes include [the original Lab/replay PR](https://github.com/imizik/TradeJournal/pull/431),
[owner context](https://github.com/imizik/TradeJournal/pull/470),
[completed-trade review](https://github.com/imizik/TradeJournal/pull/472) and
[captured plans](https://github.com/imizik/TradeJournal/pull/477). The owning code,
not those descriptions, determines what is safe to reuse.

## Historical integrity and persistence

`backend/app/engine/personal_replay.py` owns the synthetic source, checkpoint
projection and state transitions. `backend/app/routers/personal_replay.py`
exposes `/practice/replay/scenarios` and `/practice/replay/attempts` with
read, choice and reveal operations. The existing access middleware permits
only the private owner; no assistant or service grant is expanded.

The additive `practice_replay_attempt` table stores the frozen snapshot and
choices separately from existing journal and paper tables. A unique operation
ID makes creation retryable. Revision checks prevent competing writes from
replacing a choice or losing a reveal. Reloads use saved evidence, not a newly
computed scenario. A reveal is persisted before its response is returned.

The server filters completed intervals and observation/publication times at
the evidence cutoff; retrieval and actual decision receipt times are recorded
separately. The first continuation must pass the next checkpoint's cutoff.
Unknown timestamps or missing observations cannot be treated as known facts.
The public response is an explicit projection, never the stored sealed snapshot.
The future neutral comparison projection excludes human choices, notes and
all continuation, even after the human has revealed it.

## Local demonstration and checks

Use the existing isolated fixture runner, with no keys:

```bash
bash scripts/ux_sandbox.sh --no-keys
# Open http://127.0.0.1:3098/practice/replay
```

In a fresh checkout, run `bash scripts/setup.sh` first. The runner seeds its own
local database, disables integrations and refuses to use a real environment.

Focused checks are `backend/tests/test_personal_replay.py` and
`frontend/e2e/personal-replay.spec.ts`. Browser coverage exercises the real API
and database through the same-origin proxy: two checkpoints, reveal refusal,
reloads, lost-response recovery, pre-reveal payload inspection, and desktop
and 390×844 phone layouts. Schema, access, existing Practice and frozen-chart
regressions remain relevant. The PR records actual test and review results;
this document does not claim live acceptance or physical-device testing.

## What is needed for personal history

An owner-approved bounded export needs canonical entry source anchors and
ordered fills; explicit exchange timezone and contract units; historical
underlying bars with interval completion and provenance; historical option
observations with missing coverage retained; and original capture/plan receipt
times. News needs original publication and observation times, not a current
summary. Whole-trade metrics and later notes belong in sealed outcomes only.

Preparation should choose checkpoints by a rule fixed before examining their
future returns, document prior exposure, and respect the Factory's protected
periods. Deliberately skipped opportunities need contemporaneous records.
Nothing in V1 authorizes retrieving those records or importing them.

One fixture cannot show improved trading judgment. This slice is worth testing
for whether making a choice before seeing history produces a useful discussion
about plan adherence, sizing and horizon. Continue to a small approved set of
personal scenarios only if the owner wants to repeat the exercise; do not infer
an edge from agreement with the historical action or a profitable outcome.
