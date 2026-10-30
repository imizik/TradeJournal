# Journal analytics

`/analytics` is a read-only explorer of reconstructed closed and expired
positions. `GET /stats/analytics` provides reusable calculations from
`backend/app/engine/analytics.py`; the React component only formats, sorts,
selects groups, and paginates the supplied trade rows. There are no external
provider calls, mutations, or AI calculations.

## Scope and filters

- `account_id`: an exact account UUID, independently of account type.
- `instrument_type`: `stock` or `option`; omitted means both.
- `start` and `end`: inclusive **final close dates** in America/New_York.
  Omitted dates mean all dated closed/expired positions in scope. Naive
  journal timestamps already represent New York wall time; aware timestamps
  are converted to it. A trade entered before the range but closed inside it
  belongs to the selection.
- Open positions, including their partial realized P&L, are excluded.
- Closed positions without a close timestamp are excluded. Coverage reports
  their count across the account/instrument scope because their date
  eligibility cannot be determined.

## Metric definitions

Dollar totals, expectancy (average dollar P&L), median, win rate, and win/loss
sizes use only selected trades with recorded P&L. Missing P&L is excluded
and its count is shown. Breakeven trades remain in the win-rate denominator
but are neither winners nor losers. No priced trades means unavailable,
including total P&L and drawdown, rather than a fabricated zero.
Dollar calculations retain Decimal precision; displayed results are rounded
to cents with half-up rounding after aggregation.

Profit factor is gross positive P&L divided by the absolute gross negative
P&L. A positive gross profit with no losses is shown as infinity. With only
breakevens or no priced trades it is unavailable.

The curve accumulates closed P&L by final close date. Drawdown is the largest
fall from a running peak starting at zero, measured at recorded close
timestamps. Simultaneous closes are summed before measuring the peak. Neither
the curve nor drawdown measures account equity, open-position losses, or
cash-flow-adjusted returns.

Profit concentration removes the largest one/five **positive** trade results,
keeps all losses, and shows the remaining closed P&L. The share uses gross
profits, never net P&L. Fewer available winners means fewer removals; no
winners means no share. This is a sensitivity comparison, not evidence that
concentrated returns are undesirable.

## Breakdowns and evidence

Breakdowns cover ticker, New York entry-time windows, tags, recorded hold
duration, instrument, and first/repeat entries. Tag groups overlap; untagged
trades have their own group. Missing hold duration is an Unavailable group.
The mean percentage return is unweighted and shows its own valid sample
count. It is not a portfolio return or an R-multiple.

Repeat entries are later reconstructed positions in the same account, ticker,
and New York entry day. Classification uses all trade history, including open
positions, **before** close-date or instrument filtering. Simultaneous first
entries all belong to First entry time; arbitrary UUID order cannot classify
one as a repeat. Additional fills in one position are not new trades.

Every group shows trade count, distinct entry days, and how many results are
available. Fewer than 20 priced trades receives a Small sample label. This is
a display cue, not a statistical-confidence threshold; larger groups may
still be dependent or inconclusive. Minimum-sample filtering only changes
visible groups; it does not change the selected baseline or overall summary.
Group buttons and concentration cards drill into the exact contributing
trades, with links to their detail pages.

Accounting and temporal edge cases are covered in
`backend/tests/test_analytics.py`; the interactive filters and drill-downs are
covered in `frontend/e2e/analytics.spec.ts`, using isolated seeded SQLite data.
These checks do not establish live broker completeness or historical data
freshness.

## Outcomes

Every output the app makes gets one `outcome` row (`app/engine/outcomes.py`):
what the underlying did after it, what the owner did in the fills, and the
dollars against the obvious alternative. Python fills it in at the end of the
sync pipeline the timer runs at 08:00 and 17:00 New York (`compute_outcomes`); no model call, and
prices come only from the minute sessions the charts already store on disk
(the only provider read is the market calendar's usual cached one, at most
once a New York day).
Rows start at `OUTCOMES_SINCE` (default 2026-10-21, when position alerts went
live). `GET /analytics/outcomes?kind=&since=&symbol=` (owner only) returns the
rows and a summary per kind; `/proof` shows the summary, the trade page shows
each ping's "+1h −4% · +1d −12%", and the week review reads it per kind.

| Subject (`subject_kind`) | Anchored at | Action window | Alternative (`alt_usd`) |
|---|---|---|---|
| `ping`: every phone ping; those the policy held are rows too, `held` true, as a control | delivered (else decided) | 15 min on the position's own fills for an exit-kind ping; 30 min on the symbol's fills otherwise | open-trade alerts sent or possibly sent (as `exit_habits` counts them): proceeds minus closing the alert's contracts at its midpoint mark (`follow_up`'s `vs_alert`) |
| `plan`: every pre-trade plan, the copilot's plan card included | saved | the trade's life: `entered` once linked, else `none` (final 14 days on with no link) | none |
| `radar_event`: stock events on the stock, group events on their top member (Radar's first listed) | first sighting | 30 min on the symbol's fills | one share at first sight in Radar's direction: the scorecard's move against SPY to the session's last pass times the price then |
| `research`: each Jo research record, on its symbol; d1 and d5 only | saved | to the next session's close | none |
| `shadow_decision`: each Shadow book plan or skip; d1 and d5 only | decided | its own paper book (`entered`, `closed`, `none`) | none: its paper fills are its result |

`companion_update` is reserved for the position companion's updates.

**Windows.** `h1` ends 60 minutes after the anchor; `d1` and `d5` at the
regular close of the 1st and 5th trading day after the anchor's New York date
(the market calendar, else weekdays). Each holds the last minute's close
before the end, its change from the reference price in percent, the highest
and lowest minute inside, and `complete`. The reference price is the source's
own recorded price of the underlying (Radar's evidence at first sight), else
the last stored minute at or before the anchor (up to five days back, for a
weekend or an anchor before 04:00). Stored minutes include extended hours.

**Action.** With a position in the symbol open at the anchor: `closed` (all of
it), `trimmed`, `added` or `held`; with none, `entered` or `none`. `unknown`
when it cannot be told (no symbol, or the position's trade is gone). Fills
carry the broker's minute, so a fill in the anchor's own minute counts as after.

**Incomplete rows.** A window still open, a session not stored yet, an open
position behind an alert or a plan, or a Radar session still trading leaves
the row incomplete; the next run recomputes it. New subjects are computed
before rows waiting on a window, at most 400 a run. A window still missing a
session ten days after it ended is closed with what there is, and says which
sessions were missing. Symbols the charts never stored have no prices.

**What it does not claim.** Counts and price paths, not causation. A price
move after a ping is not the ping's effect, the alternative is a reference
mark rather than an executable price, held pings are a convenience control
rather than a randomized one, and a symbol nobody charted has no stored
sessions to measure.

