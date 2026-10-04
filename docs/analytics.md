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
