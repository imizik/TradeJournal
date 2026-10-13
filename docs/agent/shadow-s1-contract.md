# Shadow Isaac S1 — Jo decides on scanner setups for its own paper book

Selected by Isaac on October 12, 2026, when he moved the Dots priority from
the advisor to the shadow trader. Build step 4 of the
[shadow trader design](shadow-trader-design.md#build-order-after-dots-steps-35),
narrowed to the smallest version that produces a comparable record.
**Contract only; nothing here is built, granted or activated.**

## What happens

1. The [scanner](setup-scanner-contract.md) saves a setup and emails it
   (`TJ Setup:` subject).
2. Jo's Gmail task wakes. **First**, as Shadow Isaac, it reads the setup through
   `shadow_setup` and commits **TAKE** or **SKIP** with a reason through
   `shadow_decide`. Only then does it run the co-pilot `pre_trade_check`.
3. TradeJournal prices a TAKE as Shadow Isaac's own one-contract paper trade:
   the setup's contract, stop, target, 60-minute time stop and flat-by time,
   entered at the ask of the first fresh quote after the commit. A commit after
   the setup's 10-minute expiry is recorded as **no response**, never entered.
4. The Scanner page shows, per setup: the rules-only result, Shadow Isaac's
   decision and result, and later Isaac's own trade if he took one.

S1 measures one thing: **does Shadow Isaac's choice of which setups to take
beat taking them all?** Same contract and same exits isolate selection skill.
Choosing its own contract, size or exits is a later version.

## What Shadow Isaac may see

`shadow_setup(candidate_id)` returns, and nothing else:

- the frozen setup exactly as saved (market facts, rule stop/target, contract,
  expiry);
- the live market packet the pre-trade check already builds for that ticker
  (price, VWAP, opening range, relative volume, levels, option quote), with
  source times;
- Isaac's closed-trade aggregates from the existing approved feature rows,
  **cut off at the previous session's close**: nothing from the setup's own
  day.

It never returns open positions, today's trades or fills, pre-trade checks, Jo's
co-pilot verdicts or Isaac's notes. Backend authorization enforces this, not
the prompt.

**Independence is unverified in S1, and every result says so.** Jo's Gmail
access also reaches broker fill emails, and Jo's memory may hold today's
conversation. S1 accepts that for speed. Results carry
`informed-by-history` and `independence-unverified`. Removing the second label
needs a wake-up path that is not Gmail (MCP Events) and a Dot or identity
without same-day memory; that is a later slice.

## Where it runs

- **Tools:** two new tools on the existing check service (`/check/mcp`) under
  a new scope `shadow:decide`, granted only to the existing check connection.
  `shadow_setup` reads; `shadow_decide(candidate_id, decision, reason)` writes
  one immutable row per setup in the check service's own ledger. A second
  commit with different content conflicts; an identical retry returns the
  original.
- **Setups in:** a finite publisher writes today's frozen setups (the
  `scanner_candidate` rows only) to a file the check service reads, following
  the feature publisher pattern. The check service still holds no database
  credential and the private API stays private.
- **Decisions out:** the scanner watcher in the private backend reads Shadow
  Isaac's decisions read-only from the check ledger, the way the owner page
  already does, and records the paper trade as `ScannerEvent` rows with
  `shadow_` keys. No new table or migration.

## Records and scorecard

Each setup gets: rules-only result (already built), Shadow Isaac decision
(TAKE / SKIP / no response, reason, commit time, latency from the email),
Shadow Isaac paper result for a TAKE, and the same two labels. The page
totals: rules-only P&L over all setups versus Shadow Isaac P&L over its TAKEs,
with counts. Groups under 30 decisions say "not enough evidence".

## Acceptance

- One live session where every emailed setup has a shadow decision or a
  recorded no response, and every TAKE has a priced entry after its commit or
  is unresolved.
- A forged or wrong-scope token cannot read a setup or commit; a commit for
  another day's setup, or after expiry, is refused or recorded as no response.
- `shadow_setup` for a setup on day D contains no trade closed on day D
  (fixture test plus one live spot check).
- Restart of either service leaves exactly one decision and at most one
  entry and exit per setup.

## Out of scope

Shadow-chosen contracts, sizes or exits; WAIT; Isaac-versus-shadow reveal
rules beyond showing both after the fact; MCP Events; a separate Dot; any
change to the pre-trade check's own outputs or the journal export.
