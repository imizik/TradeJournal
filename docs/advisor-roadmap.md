# Pre-trade advisor roadmap

**Goal:** before an entry, the user describes what they are thinking — ticker,
direction, instrument, rough entry and stop, a sentence of reasoning — and gets
a fast, grounded verdict: **Go**, **Wait for X**, or **Pass**, with the two or
three reasons that decided it. Every check is frozen before the outcome is
known, so after a few weeks the journal can show when the advisor was right,
when the user was, and what overriding it cost.

**Planning date:** 2026-10-09. **Status:** future. Activate after the current
shadow work ([agentic practice](agentic-trading-roadmap.md) A2/A3 and the Dot
D-series contracts) settles; this document does not interrupt those boards.
No feature is implemented by this document. When the user selects a
milestone, write a bounded implementation contract and deliver one slice.

The advisor is decision support over the user's own records and market data.
It never places, sizes or amends orders, and its verdict is a check on the
user's thinking, not evidence of an edge until its saved verdicts carry
outcomes.

## Where the advisor sits among the agent roles

The Dots integration defines proposed agent roles as permission scopes —
independent practice runner, personal review/coach, research and operational
diagnosis ([roles](agent/dots-integration.md#roles-and-independent-decisions)).
Two matter here:

- **Shadow Isaac**, the independent practice runner — a separate restricted
  runner that decides under the `shadow-isaac-p0-v1` practice policy from an
  explicit input packet, without Isaac's decisions, fills or memory, so the
  two can be compared.
- **The personal Dot (Jo)** — a coach/inspector, not a blind comparator. It
  saves its own simulated sample choices through the cloud connector (D2);
  its replay and market-decision sessions run in the browser.

The advisor is closest to the personal review/coach scope but reads more than
that scope lists today: live context and per-check history summaries. It is
therefore a new scope that needs explicit selection and authorization, as
that document requires. It is the opposite of the shadow: it starts from the
user's idea and reads the user's history.

- The advisor is never the Shadow Isaac runner, and advisor tools never appear
  in its profile. Backend authorization, not tool omission, enforces this.
- On the cloud connector, advisor scopes are a separate grant. A principal
  holding a practice decision-write scope does not also receive advisor
  scopes in the same grant; otherwise its "own" simulated choices could be
  made with the user's history in view.
- Advisor checks never enter a shadow cohort, a P0 denominator or paper
  outcomes.
- A human decision made after consulting the advisor is **advised**. Any later
  human-versus-shadow comparison reports advised and unadvised decisions
  separately; otherwise the advisor quietly contaminates the human baseline.

## What already exists

Most of the advisor is assembly. Reuse these; do not build parallel versions.

| Need | Existing piece | Gap |
|---|---|---|
| Live context and a level-based plan | `analyze_scalp` → `/packets/scalp` ([scalper.py](../backend/app/engine/scalper.py)): deterministic `no_trade`/`wait`/`long_scalp`/`short_scalp`, setup/liquidity/risk scores, trigger/invalidation/targets, the option-spread rejection and stale-data rules | Live provider calls are made one after another and take a few seconds; no frozen snapshot ID; regular-session intraday only |
| Daily trend and levels | `analyze_ticker` ([analyzer.py](../backend/app/engine/analyzer.py)) | Same snapshot gap |
| How the user's entries looked | `get_fill_contexts`: VWAP distance, RSI/EMA, relative volume, chase / late-move / trend-aligned flags | Row-level only; no cohort summary |
| How the user's trades played out | `get_trade_path_metrics`: MFE/MAE, exit efficiency, giveback, post-exit continuation | Row-level only |
| The user's committed intent | Pre-trade capture ([captures.py](../backend/app/engine/captures.py), Charts C3.4–C3.5): immutable intent, side, optional contract and quantity, frozen chart context, receipt time, retry identity | No entry or stop price (J4 plans invalidation, size and planned loss); no advice attached |
| Intent → actual trade | Capture links (C3.6, [plans linked to trades](charts-workspace.md#plans-linked-to-trades-c36)), anchored to survive rebuilds | — |
| Agent access | Local stdio MCP adapter ([mcp_server.py](../backend/mcp_server.py)); cloud OAuth pattern from the [cloud connector scope](agent/cloud-mcp-integration-scope.md) | Cloud path is sample-only with no real journal reads |

## Checks and captures

Product direction forbids a competing plan store
([product roadmap](product-roadmap.md#ownership-and-priority)). The advisor
respects that by keeping two things apart:

- A **capture** remains the user's committed intent and the only thing C3.6
  links to a trade.
- An **advice check** stores the question it was asked — the idea's inputs,
  including any entry, stop or target — the same way a capture stores its
  frozen chart context. It is a record of a consultation, not a plan.

The usual order is check first, capture second, so a check cannot carry its
capture at creation. Linking a check to a capture is a separate append-only
link record made when the capture is saved (or later by the user); the check
itself never changes. Re-checking after "Wait for X" creates a new check, so
one capture can be linked from several checks.

Checks with no linked capture do not appear in C3.6's needs-linking view or
capture-coverage counts. Their outcome is resolved deterministically from
fills: **no trade** only when no trade on that underlying and side opened
within the check's window; otherwise **unattributed** — a trade happened but
was not tied to the check. The window is fixed in the AV2 contract and
recorded with the rules version — for an intraday check, from receipt to the
`wait_for` expiry or the session close, never a window chosen after the
outcome is known. Unattributed is shown, never silently counted as
followed or ignored. When J4 adds planned-risk fields to captures, a check
linked to a capture reads them instead of asking again.

## The answer contract

One response shape, whatever the surface:

| Field | Meaning |
|---|---|
| `verdict` | `go` · `wait` · `pass` · `insufficient_data` |
| `wait_for` | Required with `wait`: one observable condition and an expiry ("15-minute close above 98.40 before 11:00 ET") |
| `reasons` | At most three, each tagged with its source: `history`, `live`, `playbook` or `risk` |
| `would_change` | What would flip the verdict |
| `risk_check` | Stop distance against the nearest level and recent range; planned loss against the user's own limit when J4 exists. Absent stop → says so, never invents one |
| `history` | The similar-trades card below, with its cohort definition and coverage |
| `live` | Price, levels and scalp assessment with source and observation timestamps |
| `caveats` | Stale or missing data, thin cohorts, IEX-only quotes, wide option spreads |

Two verdicts are stored, not one:

- **`rules_verdict`** — deterministic, from the scalp assessment, the history
  card and playbook checks. Same inputs, same answer.
- **`model_verdict`** — the narrated answer. It may disagree with the rules
  but must say why.

Keeping both is what makes the advisor gradeable: it shows whether the model
adds anything over the rules, and the rules still work when the model is slow
or unavailable.

### Rules verdict mapping

The first version covers **regular-session intraday ideas**, the range the
scalp scorer was built for. Every request states a required `horizon`:
`intraday` (exit the same session) or `swing`. Swing ideas return
`insufficient_data` until a scorer exists for them.

The check always passes the idea's direction, so the scorer evaluates only
that side. `score_scalp` reports closed and after-hours sessions as
`no_trade`, and premarket, stale data and a missing setup as `wait`; none of
these is a judgment on the idea, so the mapper reads the packet before the
verdict, in this order:

| Condition, checked in order | Rules verdict |
|---|---|
| `market_state` is closed, premarket or after hours | `insufficient_data`, reason "outside the regular session" — not a judgment on the idea |
| `data.staleness.is_stale`, or no setup score | `insufficient_data`, never `go` |
| Assessment `long_scalp` / `short_scalp` | `go`, unless history or risk downgrades it |
| Assessment `wait` | `wait`: the scorer's trigger as the condition, with an expiry set by the rules version (the scorer returns none) |
| Assessment `no_trade` | `pass` |

History and risk can only downgrade (`go` → `wait` or `pass`), never upgrade.
The exact downgrade and expiry rules are fixed in the AV0 contract and
versioned; a change makes a new rules version recorded on each check.

## Similar trades: the part only this journal can give

"You have taken 23 trades like this; the losers were mostly entries after
10:30" is the advisor's distinctive value — and the easiest part to get wrong.

- **Cohort dimensions** come only from fields with stored coverage: underlying
  (same / any), instrument and side (calls, puts, stock), New York time-of-day
  bucket, entry-versus-VWAP bucket, trend-aligned, chase and late-move flags,
  relative-volume bucket. No dimension is inferred from P&L.
- **Outcome measures** reuse existing definitions: realized P&L, return and
  win rate from [analytics](analytics.md); MFE/MAE and giveback from
  [trade metric correctness](trade-metric-correctness.md). Journal trades
  carry no planned stop, so the history card shows no R multiple.
- **Honest counts:** trades, distinct days, distinct weeks; trades clustered
  in one day are not independent. Below a display threshold the card says
  "not enough history" rather than showing a rate. The threshold is a display
  policy, not proof.
- **As-of discipline:** the card frozen into a check uses only trades closed
  before the check's receipt time. A check's receipt time is UTC while
  `trade.closed_at` is timezone-free New York wall time
  ([domain rules](agent/domain-rules.md)); convert before comparing, as C3.6
  does, or later trades leak into the card and grading rewards hindsight.
- **Rebuild-safe:** FIFO rebuilds recreate derived trades, so the frozen card
  stores aggregate values, the cohort definition and source fill dedupe keys —
  never bare trade IDs.
- **Precomputed per trade:** after fills import and reconstruction, write one
  feature row per closed trade (cohort dimensions, close time, outcome
  measures). A check filters and aggregates those rows at request time with
  the as-of cut. A table of pre-aggregated totals cannot apply that cut or ad
  hoc filters.

## Speed

"On the spot" means the answer arrives while the idea is still live.

- **One call.** `pre_trade_check` returns everything above in one round trip.
  The Dot sample connector's flow is several sequential tools — profile, list
  runs, read run, save choice ([cloud_mcp_d1.py](../backend/cloud_mcp_d1.py))
  — each with model thinking between calls. The advisor must not repeat that
  shape.
- **Server budget:** p50 under 1.5 s, p95 under 4 s for the deterministic
  part. That needs the scalp packet's provider calls made concurrently with a
  short cache, and history read from the per-trade feature rows.
- **Instant path without a model.** The in-app check renders the rules
  verdict and cards with no AI call. The narrated answer is optional on top.
- **Model mode.** For the advisor, a fast model mode is acceptable; the model
  and mode are recorded on each check. (The shadow is different: its model and
  mode are part of what is being tested and stay fixed per version.)
- **Measure it.** Each check stores its stage timings (context, history,
  total), so slowness is diagnosed from records, not impressions.

## Records

An advice check is an immutable row:

- operation ID (retries return the original), server receipt time, actor;
- the structured idea (including `horizon`) and free text as submitted;
- live-context snapshot with source timestamps and a content hash;
- the frozen history card and its cohort definition;
- playbook version, if one was selected; rules version;
- `rules_verdict`, stage timings and errors.

The **model verdict** is written separately by the client that produced it,
through one `attach_model_verdict` call: once per check, with server-derived
actor, model and mode as reported, and receipt time. A retry with identical
content returns the original; different content conflicts.

What the user did afterwards — **followed**, **overrode**, **no trade** — is
an append-only note, never an edit. Outcome comes from the check → capture
link and C3.6's capture → trade link, or from the no-trade/unattributed rule
above. Advice rows stay outside fills, FIFO, P&L and the paper ledger.

## Milestones

IDs use `AV` to avoid colliding with the Charts (C), journal (J), agentic
practice (A), Dot (D) and swing (S) boards.

| ID | Deliverable | Depends on | Status |
|---|---|---|---|
| AV0 | Per-trade feature rows and a `pre_trade_check` endpoint returning the answer contract with `rules_verdict` only | Fill contexts, path metrics, scalp packet | future |
| AV1 | Local advisor: `pre_trade_check` on the local MCP adapter plus a skill that adds the narrated verdict in the fixed format | AV0 | future |
| AV2 | Immutable check record, append-only check → capture link, `attach_model_verdict`, followed/overrode/no-trade note | AV0; C3.4–C3.6 (built) | future |
| AV3 | In-app **Check** beside the capture sheet: cards and rules verdict, no AI call | AV2 | future |
| AV4 | Grading view: outcomes by verdict, overrides, rules-versus-model agreement | AV2 and enough linked outcomes | conditional |
| AV5 | Phone through Dot: advisor grant on the cloud connector with summary-only real-data reads | AV1–AV2; a new authentication contract | conditional |
| AV6 | Playbook-aware checks: the selected setup's entry, invalidation and pass reasons become rules | J3 playbooks | conditional |

### AV0 — The deterministic check

**Done when:** a request with underlying, side, instrument, horizon and
optional entry/stop/strike/expiration returns the answer contract; the
verdict mapping above is covered for every scalp verdict, session state,
stale packet, missing setup and swing horizon; cohort summaries
match row-level `get_fill_contexts`/`get_trade_path_metrics` for the same
filters; a test with a trade closed after the check time (including across
the UTC/New York conversion) proves the as-of cut; stale live data can never
yield `go`. Fixture timings show server-side overhead only — live provider
latency is not proven here. No model call.

### AV1 — Use it today, locally

The cheapest useful version: the user asks in Claude or another local client,
the skill calls one tool and answers in the fixed format. Checks are not yet
saved, so AV1 is useful but ungraded. **Done when:** the skill always shows
reasons with sources and caveats and distinguishes the rules verdict from its
own, and live market-hours checks are observed end to end with stage timings
measured against the latency budget.

### AV2 — Freeze it

**Done when:** a check survives reload, FIFO rebuild and resync; a retried
operation returns the original; a second `attach_model_verdict` with
different content conflicts; a capture saved after the check links to it
without altering the check and shows the trade that followed; an unlinked
check resolves to no trade or unattributed from fills;
the follow/override note cannot alter the check; and a test proves advice
rows are excluded from shadow cohorts.

### AV3 — Check without leaving the chart

A **Check** button beside the existing capture flow. Saving a capture still
makes no market-data provider request, as the Charts contract requires;
**Check** is a separate, explicit action and the only one that calls
providers. **Done when:** phone and desktop browser evidence shows the cards
render from a saved check within the budget, failure states are explicit, a
capture saved without checking makes no provider request, and no AI call is
required.

### AV4 — Grade the advisor and the user

**Done when:** outcomes are shown by verdict and by followed/overrode with
counts, distinct days and coverage; unlinked checks remain visible as
"no trade" or "unattributed", never folded into followed or overrode; small groups say insufficient evidence; and advised
human decisions are separable in any shadow comparison. No automatic rule
tuning from these results.

### AV5 — From the phone

Reading real-journal data from a cloud model is a new exposure. It needs its
own contract under the
[cloud browser and authentication rules](agent/cloud-browser-auth-contract.md):
owner-only identity; an advisor grant separate from every shadow and
practice-write scope; reads limited to the check endpoint's summaries and
live context, not raw fills or accounts; and the production private API never
tunnelled. Until that contract exists, the advisor is local and in-app only.

## Not in scope

Order placement or broker connections; position sizing on the user's behalf;
push alerts that volunteer advice; options pricing beyond the existing spread
and liquidity rules; swing or overnight scoring; automatic tuning of rules
from outcomes; a setup classifier; reading the shadow's undecided
opportunities; treating any verdict or hit rate as a validated strategy.

## Risks to design against

- **Anchoring and over-reliance:** the advisor can make the user's own
  judgment worse. AV4's override view is the check on this.
- **Small cohorts read as edges:** show counts, days and uncertainty; hide
  rates below the threshold.
- **Stale or thin data:** every live fact carries its timestamp; IEX quotes
  for thin names and option spreads are flagged, not smoothed over.
- **Look-ahead in grading:** the as-of cut with correct time-zone conversion
  and frozen snapshots.
- **Shadow contamination:** separate roles, grants and records, and the
  advised flag.

## Decisions for the user at activation

1. Which verdict the user sees first: rules or narrated.
2. Whether AV5 (phone) is needed before AV3 (in-app), given its authentication
   cost.
3. Which accounts the history cohorts include by default.
4. Whether a capture created from a check uses a new capture mode or the
   existing `discretionary` mode.
