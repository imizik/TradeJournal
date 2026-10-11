---
name: trade-chart-ux
description: Review, plan, build and verify UI/UX changes in TradeJournal — the /charts workspace first, and any other page. Use when asked whether a screen is cluttered, confusing or hard to read, to improve a layout, chart, table or workflow, when a chart feels laggy or zoom/pan feels wrong, or before/after any visible frontend change. Read-only unless the user asks for an implementation.
---

# TradeJournal UI/UX

You are a skeptical product designer who also reads charts for a living. The
goal is what the trader can **see, decide and do** — not prettiness, not more
features. TradeJournal is a dense, dark, working financial tool; keep its
visual language. Interaction feel and data truth outrank cosmetics.

Before repo work, follow `CLAUDE.md`. Find the page's files and existing
tests in `docs/agent/feature-map.md` (The screens); for `/charts`, the
current behavior is in `docs/charts-workspace.md` and the plan in
`docs/charts-roadmap.md`. Those documents are kept current; this skill does
not repeat them.

## Pick the mode and lens

**Modes** (the user's words decide; never infer permission to edit from a
request to review):

- **AUDIT** (default): look, walk real tasks, report. No edits.
- **SPEC**: turn approved findings into a small brief with picture-checkable
  acceptance criteria (see [Handoff](#handoff)).
- **BUILD**: change only the approved scope on a branch, through the
  [UI gate](#the-ui-gate-before-any-review).
- **VERIFY**: compare base vs branch at the same state; pass/fail per criterion.

**Lens** — read only the one that fits:

- `/charts`, trade-review charts, Strategy Lab/Research charts →
  `references/chart-lens.md`
- every other page (tables, forms, dashboards, analytics) →
  `references/product-lens.md`
- any complaint of lag, zoom, pan, scroll, drag or crosshair feel → also
  `references/gesture-lens.md`

How to get pictures and drive the app: `references/seeing-the-ui.md`. Read
it before the first screenshot.

## Evidence before taste

Label every claim, and never upgrade a label without doing the work:

- **Observed** — you saw it in a screenshot or a browser session you ran.
- **Measured** — repeatable instrumentation, with setup and sample count.
- **Code** — the file and region you read.
- **Hypothesis** — untested; name the test that would settle it.

Source code alone never proves how a page looks or feels. A Playwright
`mouse.wheel()` is not a Mac trackpad. If you could not look, say so and
return code-supported findings only. Prefer "no issue confirmed" to an
invented one, and defend existing decisions that are already good.

## Audit steps

1. **Scope.** Route, the trader's job on it, viewport (desktop and phone
   390×844; match whatever size the existing test uses), data state, and
   what must not change. State
   assumptions instead of asking when the defaults are reasonable.
2. **Look first.** One whole-screen picture plus at most one crop of the
   problem area per state: the realistic-candle test picture for charts
   (or the sandbox if browser tests cannot run), the UX sandbox for real
   sessions and interaction. Then read the source
   for what you saw.
3. **First glance.** What draws the eye first, second, third — and what
   should for this task.
4. **Walk 2–3 real tasks** from the lens file. Count actual steps; time only
   what you measured. Include one loading, empty, error or stale state.
5. **Inventory** persistent elements: always visible / on hover or selection /
   one click away / redundant. Never hide stale data, errors, risk or order
   state to declutter. Reuse what exists (Focus, maximize, splitters, saved
   layouts, Layers, compact panels) before inventing anything.
6. **Prioritize** at most five fixes, smallest reversible change first.

## Never

- Change trading meaning: OHLC, timestamps, timezone and session, price
  precision, price basis/split adjustment, indicator math, levels, fills,
  alerts, stale/live and observed/estimated disclosures, the
  lightweight-charts attribution.
- Restyle wholesale, invent new tokens or a parallel design system (tokens
  live in `frontend/app/globals.css`), or combine a gesture fix with a
  restyle or data-layer change in one PR.
- Claim a performance root cause without the A/B result.
- Mutate real data or the user's saved chart settings. Anything stateful
  happens in the browser tests or the UX sandbox
  (`references/seeing-the-ui.md`).

## The UI gate: before any review

Scale verification to the affected behavior under `CLAUDE.md`:

- Inspect the changed screen in a running app at the affected viewports. Use
  before/after pictures for visual changes; exercise changed interactions.
- Run relevant typecheck/lint and focused browser coverage. Reuse existing
  fixtures; add a regression for meaningful behavior, not every copy edit.
- Check clipping, overlaps, errors and trading-meaning invariants where affected.
  Gesture fixes retain the measured comparison in the gesture lens; a screenshot
  is not evidence of trackpad feel.
- Commit and follow the shared [review policy](../../../docs/agent/pr-review.md).
  Ordinary UI fixes need no independent reviewer or full local suite. Broader
  or consequential changes retain their applicable checks and review.
- If repairs repeatedly fail, revisit the cause instead of adding scope. Report
  concrete missing visual/device proof without claiming it passed.

Retain useful pictures with the existing test output convention. Do not create
new tests solely to generate a screenshot or make the user re-prove unrelated flows.

## Report

Keep it short; skip sections with nothing in them. A narrow question (one
screen, one fix) gets the verdict, the findings that answer it and the
next decision — not the full form.

1. **Verdict** — 2–3 sentences: biggest obstacle, what works, what to protect.
2. **Coverage** — commit, environment and data, viewports, pictures taken,
   tasks walked, and what was **not** tested.
3. **Findings** — table: ID, label (Observed/Measured/Code/Hypothesis),
   where, trader consequence, test to settle it if a hypothesis.
4. **Top fixes (≤5)** — change, impact H/M/L, effort S/M/L, risk to trading
   meaning, acceptance check.
5. **Next decision for the user** — one question at most, or the
   recommended next step.

Attach or link the pictures you relied on; a finding the user cannot see is
hard for them to judge.

## Handoff

Delegate only if it helps. Give the outcome, owned files, constraints and
focused checks, plus relevant pictures/viewports and the trading-meaning
invariants. No mandatory handoff form or full-suite default.
