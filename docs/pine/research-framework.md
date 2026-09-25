# Pine research framework from the 2026 journal

> Research spec from September 24, 2026. It replaces the Isaac Market Map work
> ([README.md](README.md)) and is stored here unchanged as the source for the
> scripts in this folder. First build: [intraday_reclaim.md](intraday_reclaim.md).

Prepared September 24, 2026 (New York). Live production snapshot: September 25, 02:32 UTC. Latest fill: September 24. Research watchlist and test specification; no entry recommendation based on current market prices.

## Evidence and selection

Analyzed 795 closed/expired journal trades closing in 2026 across accounts, excluding open positions. Recent means August 1–September 24; July onward is a cross-check. Dollar figures are stored realized journal P&L across wins and losses, without an additional commission adjustment. They are not account returns, risk-adjusted returns, or verified strategy backtests. Win rate includes flat trades in the denominator. Profit factor is gross winning P&L divided by absolute losing P&L. Candidates below are all options trades.

| Ticker | Full-year record | Recent record, Aug 1 onward | Research role |
|---|---|---|---|
| MU | 31 trades; +$6,125; 21 wins; PF 3.37 | 4 trades; -$224 | Best larger-sample foundation for intraday reclaim/rejection; recent weakness requires forward validation |
| NBIS | 28 trades; +$1,209; 12 wins; PF 1.57 | 6 trades; +$1,904; 5 wins | Strongest recent candidate; separate recovery swing from opening momentum |
| META | 26 trades; +$1,586; 15 wins; PF 1.71 | 3 trades; -$292 | Intraday reversal/continuation research with strict invalidation; recent wins do not erase the larger loss |
| SNDK | 43 trades; -$4,640.99; 24 wins; PF 0.62 | 7 trades; -$270 | Secondary long-side experiment only; do not promote based on isolated big wins |

MU remains +$4,565 after removing its best trade; NBIS remains +$959 since August after removing its best recent trade. Those are concentration checks, not forecasts. MU had 30 same-day trades totaling +$5,578, versus one overnight trade +$547; median full-year hold was 14 minutes. Its calls totaled +$4,009 and puts +$2,116.

NBIS had five overnight trades totaling +$1,506 and 23 same-day trades totaling -$297 for the year. This is a retrospective grouping by realized holding period, not evidence that deliberately holding a losing scalp overnight improves it. Recent winners include August 10–12 (+$945), September 8 (+$280 in five minutes), and September 17–18 (+$458). These are different trade types; do not combine their exit rules.

META had 21 same-day trades totaling +$2,819 and five overnight trades totaling -$1,233. September 22 and 23 put trades made +$126 and +$656 in 16 and two minutes, respectively; the September 10–11 put lost $1,074. Treat the day/overnight split as a hypothesis to test prospectively, not a counterfactual backtest of closing those trades earlier.

SNDK's September 1 put winner (+$930) and September 14 call winner (+$900) coexist with a September 1 put loss of $2,690. Full-year calls: 15 trades, +$1,582. Full-year puts: 28 trades, -$6,222.99. This suggests a long-side research branch, not a proven long-only strategy.

AMD (+$2,191/24 trades), MRVL (+$811/8), and LLY (+$4,090/19) are secondary comparison names. AMD's best trade contributed $1,661; LLY's contributed $3,440. SKHY's +$1,220 recent winner is only one observation. These are weaker foundations for a repeatable first script than MU. TSLA and NVDA are negative YTD in this journal.

September overall: 21 closed trades, 16 winners, four losers and one flat; -$2,105.99. A high win rate has not controlled the size of losses. Risk and exit design belong in version 0.1.

## Data limits to resolve before labeling historical setups

The snapshot contains inconsistent entry-time bucket labels: for example, a September 1 SNDK entry stored at 16:35 has an `afterhours` label, while recent stored times are consistent with UTC trading-session times. Older stored timestamps also appear to use a different convention. The indicator code assigns New York timezone directly to naive timestamps. Source-time confirmation was unavailable for the two inspected source-email fields. Do not infer a best time of day or train a filter from these saved labels yet.

Saved VWAP/setup flags are not sufficient to establish what price did immediately before entry. Use original minute bars, verified timestamp provenance and only information available before each signal. No historical bar replay was performed for this report. The setups below are deliberately testable hypotheses, not recovered descriptions of the user's exact signals. Daily indicator snapshots are suggestive only. Multiple entries, scaling and discretionary exits also separate journal outcomes from a mechanical strategy.

## First build: MU intraday reclaim/rejection, version 0.1

Use Pine v6 `strategy()` on the underlying's standard one-minute candles. One-minute is a starting resolution consistent with short holds, not an optimized timeframe. Add a three-minute comparison only as a separately recorded experiment. Start on MU; run META unchanged as a transfer check before tuning META-specific rules.

All numeric settings below are proposed research defaults, not values fitted or validated from the journal.

1. Session: regular-hours VWAP resetting at 09:30 America/New_York. Permit entries 09:35–15:00. No pyramiding, no averaging down, one open position. Flatten before the regular session ends, including early-close sessions; do not assume every session closes at 16:00.
2. Long setup: previous completed bar closed at or below its session VWAP; current completed bar closes above current VWAP and above EMA9. This creates an armed setup. Short setup is the exact directional mirror. No daily trend filter initially, because the observed winners span different daily regimes.
3. Confirmation: within the following three bars, a completed bar must close above the reclaim bar's high for a long, or below its low for a short. Cancel an armed long if a completed bar closes below VWAP, and mirror for shorts. Never enter on the arming bar. Allow only one trigger per setup.
4. Entry: submit at the confirmation close for the next available tick, normally next bar open. Use a limit on how far price can chase: reject confirmation if more than 1.0 ATR(14, one-minute) from VWAP. Model gap and slippage effects explicitly; the fill is not guaranteed to equal signal close.
5. Invalidation: the extreme of the setup from arming through confirmation, plus a 0.1 ATR buffer. Freeze the initial stop; never widen it. Set a protective stop with the entry order. Risk quantity is based on the expected entry-to-stop distance and a fixed simulated risk budget, capped at available capital with no leverage. Reconcile actual R with the actual fill and record overshoots from gaps.
6. Exit: initial target 1.5R; full exit rather than partials in version 0.1. Add a 20-minute maximum hold and mandatory session exit. R means initial price risk from fill to stop, not percent option premium. If stop and target can both hit in one candle, use lower-timeframe evidence where available and compare conservative fill assumptions.
7. Loss controls: at most two entries per symbol per session; stop opening new positions after two losing trades or a realized -2R session, whichever happens first. Portfolio-wide exposure across separate chart scripts requires an external coordinator; a per-chart limiter is not an account-wide limit.
8. Output: show armed/triggered/cancelled states, direction, frozen invalidation, target, R, entry time and exit reason. Alerts include ticker, exchange, bar-close timestamp, version and setup id. Keep research alerts separate from the application's frozen live-webhook v1 contract until an explicit integration step.

The baseline uses a common event sequence: flat -> armed -> confirmed -> position open -> exit -> cooldown/flat. EMA length, ATR buffer, confirmation window, maximum hold, target R and trade limits should be inputs, with a saved baseline preset. Default unsupported/missing-data conditions to no trade.

## Separate follow-on modules

**NBIS recovery swing:** research on 15-minute candles, long only initially. Arm after price has traded below the prior completed daily EMA20; require a completed 15-minute reclaim of EMA20 on that timeframe and a close above the preceding three completed bars' highs. Set invalidation below the preceding four completed bars' lows with an ATR buffer. Start with a fixed 2R target and a maximum of two trading sessions. Overnight holding is permitted only for this named module, selected before entry. This is a proposed confirmation rule; the journal does not establish that the observed winners used it. Compare against an intraday-only exit using identical entries to test whether overnight exposure actually adds value.

**META failed-breakout short:** on one-minute candles, select a pre-existing level (prior-day high initially). Arm only after a bar trades above that level and closes back below it. Require a subsequent completed close below the rejection bar's low before entry; stop above the rejection high plus an ATR buffer. Begin with the same 1.5R/20-minute exit and session controls as the baseline. A separate prior-day RSI or daily-extension filter can be tested later; RSI >70 alone is not a short trigger. The September losing put also entered an extended market.

**SNDK:** only after the baseline is stable, run the long version unchanged as a separate experiment. Compare its losses and cost sensitivity before expanding its role. Keep bearish experiments separate and visible rather than pooling them with long results.

## Iteration and acceptance framework

- Version 0.1 establishes the baseline entries, exits, fixed risk and traceable signals. Replay at least ten winners and ten losers where available; ensure the minute bars and order timestamps agree. These manual checks prove mechanics, not profitability.
- Version 0.2 changes only the exit: compare fixed 1.5R versus a 2R target, then a time-exit variation. Do not change entries simultaneously.
- Version 0.3 tests one filter at a time: prior completed higher-timeframe trend, time-of-day, or time-of-day-adjusted relative volume. A simple volume/SMA ratio is not equivalent to time-adjusted RVOL. Drop filters that merely remove a few inconvenient losses.
- Measure trade count, independent trading days, expectancy in R, profit factor, maximum drawdown in R, average win/loss, tail loss, holding time, and results after removing the best trade and best day. Show long/short, ticker and month separately. Use equal planned risk; actual journal dollar results are affected by position sizing.
- Use standard candles, realistic fees and slippage, next-tick fills, and confirmed higher-timeframe data. For higher-timeframe `request.security`, use the documented prior-bar offset pattern; never use unoffset lookahead. Record the exact settings with every run.
- Treat all 2026 results inspected here as exploratory. Historical chronological splits can test stability, but September is no longer an untouched holdout. Freeze the specification before collecting new forward/paper observations. A suggested preliminary checkpoint is 30–50 new signals across at least 20 sessions, followed by more evidence if sparse or unstable; those counts are not proof of an edge.
- A challenger should improve cost-adjusted expectancy without materially worsening drawdown, remain viable when costs are stressed, and not rely on one trade/day or one narrow parameter value. Do not force profitability by optimizing each ticker separately.
- Strategy Lab is currently empty. When implementation begins, create separate definitions for intraday reclaim, NBIS swing and META failed breakout. Save source, settings, symbol, timeframe, date range, costs and exports for each run. Fork a used version for each change; never mix simulated results into real fills/trades.

## Options execution boundary

The first script tests direction and exits on the underlying. A short signal is a bearish underlying simulation, not a put-option P&L simulation. Contract selection, expiry, delta, volatility changes, spreads and fees need separate validation. Do not translate a 1.5R stock move into a promised option return. In particular, several journal winners used 0DTE options; that does not establish 0DTE as the best execution choice. Keep 0DTE separate from longer expirations when testing an options layer and record contemporaneous bid/ask and fills.

Sources: [TradingView strategies](https://www.tradingview.com/pine-script-docs/concepts/strategies/), [TradingView repainting and confirmed data](https://www.tradingview.com/pine-script-docs/concepts/repainting/), [OIC on option pricing and Greeks](https://www.optionseducation.org/advancedconcepts/putting-it-all-together).

No production records or application code were changed. Ticker totals were independently checked with SQL. No Pine script has been compiled or backtested in this task.
