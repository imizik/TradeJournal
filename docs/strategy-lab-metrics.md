# Strategy Lab Metrics

Strategy Lab metrics are deterministic, recalculable summaries of imported
`strategy_run_trade` rows. Calculation version `strategy_metrics_v1` uses
`Decimal` arithmetic and stores persisted numbers as `NUMERIC(18,6)`.

## Calculation Rules

`trade_count` always means every imported trade in the run. Outcome metrics
use only trades with a non-null `net_pnl`; the response `coverage` object makes
that denominator and every missing-field count explicit. Missing values are
never replaced with zero.

| Metric | Definition |
| --- | --- |
| Winning / losing | `net_pnl > 0` / `net_pnl < 0`; zero is breakeven |
| Win rate | winners divided by trades with P&L, as a `0..1` ratio |
| Average winner / loser | arithmetic mean of positive / negative P&L; average loser stays negative |
| Payoff ratio | average winner divided by the absolute average loser |
| Expectancy | mean `net_pnl` across P&L-covered trades, including breakevens |
| Profit factor | gross profit divided by absolute gross loss; null when there is no gross loss |
| Total net P&L | sum of all trade P&L, only when every trade has P&L |
| Net return % | complete total P&L divided by positive initial capital; otherwise the latest source cumulative return when available |
| MFE / MAE | average and median of the imported dollar excursion values, preserving source sign |
| Average holding time | mean of non-null `duration_minutes` |
| Top 1 / 3 / 5 contribution % | largest positive trades divided by positive total net P&L, only with complete P&L coverage; it can exceed 100% |

Fields ending in `_pct` are percentage points, such as `4.25` for 4.25%.
`win_rate` follows the rest of TradeJournal and is a ratio, such as `0.625`
for 62.5%.

## Equity And Drawdown

Accounting curves require complete P&L coverage and an exit timestamp for
every trade. Trades are ordered by exit timestamp and then trade number. Both
curves include an explicit sequence-zero baseline before the first trade.
Cumulative P&L starts at zero. Dollar maximum drawdown is the largest positive
peak-to-trough decline on that realized-P&L curve, including a loss before the
first winning trade.

When positive initial capital is available, account equity starts at that
capital and drawdown percentage is `drawdown / peak account equity * 100`.
Without positive initial capital, dollar drawdown remains available but
drawdown percentage is null. If any trade lacks P&L or an exit timestamp, both
curves and drawdown metrics remain unavailable rather than showing a partial
or ambiguously ordered history.

## Breakdowns

Long, short, and entry-time summaries repeat the covered count, outcome
counts, win rate, expectancy, profit factor, and average source return. A
cohort total is included only when every trade in that cohort has P&L, so a
partial total is never presented as complete. Entry timestamps are converted
from stored UTC into the run's explicit source timezone before bucketing:

- `premarket`: before 09:30
- `open`: 09:30 through 09:59
- `mid`: 10:00 through 13:59
- `close`: 14:00 through 15:59
- `afterhours`: 16:00 or later
- `unknown`: missing entry timestamp

Every trade enters exactly one time bucket; missing entry timestamps use the
explicit `unknown` bucket.

## API

- `GET /strategy-lab/runs` returns paginated run summaries and accepts optional
  `strategy_id` and `version_id` filters.
- `GET /strategy-lab/runs/{run_id}` returns the run, version, source, and
  result-affecting assumptions without loading the stored source CSV.
- `GET /strategy-lab/runs/{run_id}/trades` returns lightweight paginated trades
  and accepts `direction`, `outcome`, `entry_date_from`, and `entry_date_to`
  filters. Raw CSV rows and large feature/comment payloads stay off this list.
- `POST /strategy-lab/runs/{run_id}/metrics/recalculate` calculates or replaces
  the run's one metrics row.
- `GET /strategy-lab/runs/{run_id}/metrics` returns the stored metrics and
  decoded breakdown, coverage, equity, and drawdown JSON.

Recalculation safely replaces the same one-to-one metrics row and never changes
imported trades; `calculated_at` records each refresh. Metrics are not
automatically recalculated when the calculation version changes, so call the
recalculation endpoint explicitly.

## Stage 4 Frontend

The `/strategy-lab/runs/{run_id}` page presents run assumptions, coverage-aware
metric cards, long/short and time-bucket summaries, equity and drawdown curves,
and the filterable simulated-trade endpoint above. Missing metrics remain
visibly unavailable with their coverage reason; the UI does not substitute
zero or draw a partial accounting curve. Naive stored UTC timestamps are
formatted back into the run's explicit source timezone.

Stage 4 reused the existing `strategy_run`, `strategy_run_trade`, and
`strategy_run_metrics` schema from Alembic revision `f1a2b3c4d5e6`; it added no
schema migration. Two-run comparison, deterministic findings, experiment
workflows/advice, and Pine diffs remain Stage 5 work.
