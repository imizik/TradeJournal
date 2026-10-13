# Shadow trader + setup co-pilot — Dots step 6 design

Selected by Isaac on October 12, 2026 as the direction for Dots step 6
(bounded independent shadow) on the [delivery board](dots-integration.md#functionality-sequence).
**Design only.** Nothing here is built, installed, granted or activated, and it
does not reorder the board: steps 3–5 come first. It replaces the narrow
four-tool `shadow_agent_v1` idea in the
[Dots integration notes](dots-integration.md#proposed-restricted-shadow-agent-profile-design-only)
as the target. The P0 premarket form in the [practice policy](practice-policy.md)
stays as a cheap clean baseline; it is not removed.

## What Isaac wants

A Dot that **uses TradeJournal like a real trader**: reads charts, levels,
volume and news, decides on setups during the session, has its own paper book
and journal, and can be compared with Isaac trade by trade. It may learn from
how Isaac has traded. The goal is a "better version of me": where it does
something different, who did better and why.

Two products share one scanner:

| | B — Shadow trader | C — Setup co-pilot |
|---|---|---|
| Question it answers | Would a model that knows my style do better than me? | Is this live setup worth taking right now? |
| Who decides | The Dot, for its own paper book | Isaac, with the Dot's rating as advice |
| Records | Shadow decisions, its own paper fills/outcomes | Assisted ratings linked to Isaac's choice |
| Builds on | Decision records, A2 paper watcher | [Pre-trade check](advisor-pretrade-check-contract.md) (live) |

## Information rule: learn from the past, decide blind on the present

The shadow **may** see Isaac's closed-trade history up to a frozen cutoff date
(the approved coach fields and pre-trade aggregates are the starting point;
anything wider needs Isaac's explicit approval). This is what makes it
"informed". Every shadow result is labeled `informed-by-history`.

The shadow **may not** see, before it commits its own decision on a candidate:
Isaac's open positions, his decision on that candidate, a co-pilot rating he
received for it, or any outcome after the cutoff. TradeJournal enforces this by
what each tool returns and by commit-then-reveal; prompt instructions are not
the control.

One Dot does both jobs, so order matters per candidate:

1. Scanner creates the candidate and freezes its packet.
2. The shadow decides and commits (TAKE / WAIT / SKIP, or times out).
3. Only then is the co-pilot alert sent to Isaac, and it may include the
   shadow's committed call.
4. Isaac's choice on that candidate is labeled assisted.

Isaac's own trades on symbols or times the scanner never surfaced remain
unassisted and are compared separately.

## Scanner (shared)

- Deterministic rules in TradeJournal, versioned; no model in the loop.
- Each candidate gets an ID, frozen packet (bars, levels, volume, proposed
  trigger/stop/target, source times), creation time and hard expiry.
- Duplicate suppression and a per-symbol cooldown bound the wake-up count.
- **Every candidate is logged with a rules-only paper outcome.** That baseline
  is how the shadow's filtering is judged; without it, AI value is unknowable.

## Shadow trader toolset (B)

Scoped to one restricted principal, enforced in the backend:

- Market reads: bars by timeframe, levels, volume, news, the frozen candidate.
- Its own history: decisions, paper fills, outcomes, its own journal notes.
- Isaac's approved closed-trade history up to the cutoff.
- Write: record its decision (with plan and reasons), write its own journal note.
- Optional later: the assistant web frontend in the Dot's cloud browser, limited
  to the same data.

No broker, real order, account, raw fill, other-actor decision, admin or
generic HTTP access. A TAKE can only become a paper plan under an approved
policy version.

## Execution: the Dot decides, the app executes

The existing A2 watcher pattern owns triggers, fills, slippage, stops, exits
and restart recovery. A Dot reply never sits in the trade path after commit.
A candidate whose decision arrives after expiry is recorded as **no response**,
never a late entry. WAIT must name a mechanical condition plus expiry, or it
scores as SKIP.

Intraday, candidate-driven paper trading needs a **new policy version** next
to `shadow-isaac-p0-v1` (instrument, universe, hours, risk caps, hold, costs).
P0 is not edited to fit it.

## Scorecard

Per candidate and per setup type: rules-only vs shadow vs Isaac. The useful
rows are disagreements — trades it took that Isaac skipped, trades Isaac took
that it skipped — with paper/real results and the shadow's stated reason.
Fix the minimum trade count and any holdout before looking at results; never
tune rules on the evaluation period.

## Choices Isaac still makes

- Instruments: shares/ETFs only, or options too.
- Style: intraday (15-minute bars and slower), swing, or both. Seconds-level
  scalps are out of reach for a Dot; that would need a server-side model (API
  credits), which is not selected.
- Universe, trading hours, per-trade and per-day paper risk caps.
- History cutoff and which history fields the shadow receives.

## Dots feasibility checks

Started October 12, 2026. "Docs" means OpenAI documentation read that day, not
an observation of Isaac's account.

| Check | Status |
|---|---|
| **1. Can TradeJournal wake the Dot?** | Docs: MCP Events are supported in Dots, webhook delivery only, and need MCP protocol `2026-07-28`; the server implements `events/list`, `events/subscribe`, `events/unsubscribe`, keeps subscriptions, verifies the callback, and signs deliveries (Standard Webhooks, ≤256 KiB, one event per request). Event-triggered tasks are subject to workspace controls, and the docs do not explicitly confirm unattended runs. Code: every connector pins `mcp==1.28.1` (protocol `2025-11-25`). `mcp` 2.3.0 serves `2026-07-28` but has no built-in events helpers, so the methods would be custom. Jo's answer (October 12, relayed by Isaac, not yet observed): for supported event sources Jo can start an automated task while Isaac is away; its current sources are Gmail and GitHub, and the TradeJournal plugin exposes none. **Two routes:** (a) a TradeJournal alert email as the trigger — available now, fine for the co-pilot; (b) MCP Events on a TradeJournal connector — the build above. For the shadow, route (a) is a leak path: Jo's Gmail access also reaches Isaac's broker fill emails, so same-day blindness could not be enforced by the app and results would carry `independence-unverified`. **Next:** co-pilot may use the email trigger (email carries only a candidate ID; Jo fetches details through tools); the shadow waits for route (b), proved first by a disposable events probe on the sample trial host. |
| **2. How many wake-ups fit the plan?** | Docs: talking to the Dot does not count toward ChatGPT limits; tasks it starts or manages in Work/Codex do, against an unpublished plan allowance. No schedule minimum or per-event cost is documented. **Next:** Isaac checks the plan's usage page before and after a fixed number of probe events. |
| **3. Separate shadow identity** | Docs describe one Dot per account with persistent notes. Under this design that is acceptable: memory of the past is allowed, and same-day blindness is enforced by the app. **Next:** confirm the Dot can hold two connector identities (co-pilot and shadow) or one connector with both scopes, without Isaac's same-day decisions reachable from the shadow tools. |

Sources: [MCP Events](https://developers.openai.com/plugins/build/mcp-events),
[Dots](https://learn.chatgpt.com/docs/dots),
[Dots tasks and memory](https://learn.chatgpt.com/codex/dots/tasks-and-memory).

If check 1 fails, the fallback is a scheduled Dot check (cadence set by the
plan), which suits swing setups but not intraday ones.

## Build order (after Dots steps 3–5)

The package-level plan, with models and lanes for Codex, is the
[shadow build plan](shadow-build-plan.md).

1. Feasibility checks 1–3 above, with a disposable probe only.
2. Scanner + candidate log + rules-only paper baseline (no model) —
   [setup scanner S1 contract](setup-scanner-contract.md).
3. Co-pilot: scanner candidates feed the pre-trade check and alert Isaac.
4. Shadow principal, toolset and commit-then-reveal; new intraday policy
   version; A2 watcher runs its paper book — first slice:
   [shadow S1](shadow-s1-contract.md) (selection only, scanner paper engine).
5. Scorecard and comparison view.

Each slice needs its own contract, approval and acceptance before activation.
