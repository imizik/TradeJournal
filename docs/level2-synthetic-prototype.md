# Level 2 synthetic prototype

Open **Level 2 lab** in the owner navigation (phone: **More**) or `/level2-lab`.
The synthetic section contains an invented US.NVDA ARCA price-level book.
The separate [manual connection section](level2-manual-connection.md) is disabled
by default and connects only through an explicitly started local bridge.
The synthetic section does not mount the Charts workspace, call a market-data endpoint, use moomoo
credentials, create WebSockets, write storage or update journal metrics. Existing
shell health/status reads remain unchanged. The existing access proxy keeps the
new page outside restricted assistant access; no access policy was changed.

## Acceptance and behavior

- Desktop and 390×844 phone views show **SYNTHETIC REPLAY**, US.NVDA and the ARCA
  fixture scope. No label presents the feed as live or consolidated.
- The ladder displays eight prices per side, synthetic shares, optional order
  counts and relative size bars. An unavailable order count is a dash, not zero.
- Spread and imbalance use the displayed fixture only. Imbalance sums the nearest
  five prices per side and divides the difference by their combined size.
- Replay starts paused. Play/pause, step, speed, reset, keyboard scrubbing and
  scenario shortcuts work. It stops after 20 seconds, pauses on hidden tabs and
  clears its timer/listener on unmount. Reload starts from the first frame.
- Stale (>2 seconds), disconnected, empty and unknown-source-time states disable
  summary calculations. Retained ladder snapshots carry an inspection-only note.
- The heatmap shows synthetic price-level size over replay time, never future
  columns. Invalid/stale/disconnected/empty columns are blank; blank is not zero
  liquidity. It uses a fixed, disclosed synthetic size scale.
- Source times use a declared invented October 9, 2026 session in New York time;
  age uses the replay clock. It is not measured provider latency.

The 20-second fixture includes shifting displayed liquidity, a stall, disconnect,
an empty book, a missing source timestamp and recovery. It is not a captured or
licensed market dataset. It makes no claims about named TotalView/ArcaBook rights,
Nasdaq availability, queue position or executable liquidity.

## Verification and later work

`frontend/e2e/level2-lab.spec.ts` checks the fixture math, controls, stale/empty
handling, history gaps, cleanup and isolation; it saves desktop/phone pictures.
Typecheck/lint and exact-head CI are recorded in the PR. The baseline route was
404; baseline pictures were captured in the disposable seeded browser environment.

Market-hours testing is deferred. The manual connection section still requires
actual source-field, unit, venue, clock and recovery validation before presenting
its display as usable market data. Recording, historical
depth storage, ML training and changes to current feed/metric sources remain
outside this prototype.
