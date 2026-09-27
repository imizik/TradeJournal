# VWAP reclaim/rejection, v0.1 (research)

The "first build" of the Pine research framework written from the 2026
journal on 2026-09-24: an intraday VWAP reclaim (long) and rejection (short)
on MU, one-minute candles, run unchanged on META as a transfer check. It is
implemented here as a Python backtest before any Pine exists, because the
framework's own rule is to prove the baseline before building on it.

Every number below is the framework's proposed research default. None was
fitted to bars, and none has been changed to improve a result.

## Rules

- Regular-session one-minute bars. VWAP resets at 09:30 America/New_York.
- **Arm** a long when the previous bar closed at or below its session VWAP
  and this bar closes above VWAP and above EMA 9. A short is the mirror. No
  trend filter.
- **Confirm** within the next three bars: a close above the arming bar's high
  (long) or below its low (short). The arming bar never enters. A close back
  through VWAP cancels the setup, and each setup triggers at most once.
- **Reject** a confirmation more than 1.0 ATR(14, one-minute) from VWAP, or one
  whose fill would fall outside 09:35–15:00.
- **Enter** at the next bar's open. The stop is the setup's extreme from
  arming through confirmation, 0.1 ATR beyond it, and never moves.
- **Exit** at 1.5R, where R is the price risk from the fill to the stop; after
  20 minutes regardless; and at the session close, early closes included.
- **Limits:** two entries a session, and none after two losing trades or a
  realized −2R.

## Execution model

Signals are evaluated on bar close. Entries are market orders at the next
bar's open; the stop and target rest from the fill. A bar that opens through
either fills at its open. When one bar reaches both, the stop is assumed first
(the framework's conservative assumption; `both_hit=target` reverses it).
Market and stop fills slip by the larger of one tick and 1 basis point of
price; `--set slippage_bps=3` is the cost stress test. Positions are sized
from a $100 risk budget with no leverage on $25,000, but everything is
reported in R, so sizing does not change a result.

Bars outside a session's regular hours never reach VWAP, EMA 9 or ATR. That
includes the after-hours part of early-close days, which the regular-hours
filter would otherwise keep: `NYSE_EARLY_CLOSES` lists them, and the ones in
the test window are confirmed in SIP volume.

## Running it

```bash
cd backend
python scripts/backtest_vwap_reclaim.py MU META --start 2025-10-14 --end 2026-09-24 --feed sip
python scripts/backtest_vwap_reclaim.py MU --start 2025-10-14 --end 2026-09-24 --feed sip --set target_r=2
python scripts/backtest_vwap_reclaim.py MU --start 2025-10-14 --end 2026-09-24 --feed sip --timeframe 3
```

The report gives the framework's acceptance measures in R: trade count,
independent days, expectancy, profit factor, win rate, average win and loss,
the worst trade, maximum drawdown, holding time, and the result without the
best trade and without the best day, overall and by ticker, side, month and
exit reason. It also counts setup events (armed, cancelled, expired,
rejected and why). Each run writes the report and a TradingView-shaped CSV
per ticker to `backend/data/vwap_reclaim/<run>/`; the CSVs import on
`/strategy-lab` (source timezone America/New_York) with `sl1` metadata:
setup, side, version, risk and extension from VWAP in ATR, bars to confirm,
exit reason, R.

`app/engine/vwap_reclaim.py` holds the rules and statistics and is pure (no
network, no database); `scripts/backtest_vwap_reclaim.py` fetches bars through
the Market Map backtester's loader. `--set field=value` overrides any
`ReclaimConfig` field.

## Results

**v0.1 does not pass the framework's acceptance bar.** Run on 2026-09-27 on
SIP bars for MU, META and six more of the cached names (AAPL, NBIS, AMD, LLY,
TSLA, GOOG), over the year the journal covers and the year before it:

| Eight tickers | Oct 2025 – Sep 2026 | Oct 2024 – Oct 2025 |
|---|---|---|
| **As specified** (1 bp slippage) | 2,687 trades, −185.4R, PF 0.88 | 2,830 trades, −120.6R, PF 0.92 |
| MU, the primary | 349, −0.6R, PF 1.00 | 350, −4.3R, PF 0.98 |
| META, the transfer check | 334, +1.9R, PF 1.01 | 355, −57.7R, PF 0.74 |
| Costs stressed to 3 bp | −523.3R, PF 0.69 | −475.5R, PF 0.73 |
| No costs at all | −18.4R, PF 0.99 | +116.1R, PF 1.08 |
| Three-minute bars | 2,141 trades, −128.2R, PF 0.86 | 2,339 trades, −151.9R, PF 0.85 |
| v0.2 exit: 2R target | −179.6R, PF 0.89 | −103.2R, PF 0.94 |
| v0.2 exit: 40-minute hold | −209.2R, PF 0.87 | −141.5R, PF 0.92 |

- As specified it loses in both years, on longs and on shorts, and no ticker
  is positive in both years (TSLA +15.9R then −3.5R; GOOG −17.4R then +8.1R).
- Costs decide it. Realistic slippage costs 0.06–0.08R a trade, while the
  signal itself is worth −0.01 to +0.04R a trade before costs. One-minute
  stops are tight, so every basis point of cost is a large share of R. MU is
  the one name slightly positive before costs in both years (PF 1.07 and
  1.08), and that margin is about what 1 bp a side takes away. Options, with
  wider spreads, would start further behind.
- No one-minute bar reached both the stop and the target, so the
  conservative fill assumption never came into play.
- The framework's v0.2 exits (a 2R target, a 40-minute hold) leave it where it
  was. Trades that last the full 20 minutes average +0.21R, but that is
  selection: they are the ones that were not stopped out.
- Setup events for the recent year: 11,824 armed; 4,861 cancelled back
  through VWAP; 2,556 rejected by the chase limit; 964 expired; 724 outside
  the entry window; 2,687 entered.

By the framework's own rule (a challenger must stay viable when costs are
stressed and not rely on one ticker or one parameter), v0.1 as specified
should not get a Pine version or forward-test time. If the idea is revisited,
the question to test is whether fewer trades with more room per trade make
costs a smaller share of R. That is a new hypothesis, to be chosen on one
year and confirmed on the other.

## What is verified

`backend/tests/test_vwap_reclaim.py`, on synthetic one-minute bars built so
that ATR is exactly 2.0 and VWAP is the running mean of the closes: arming,
confirmation and the next-open fill (including a gap between the signal close
and the fill); the chase limit; cancellation through VWAP; expiry after three
bars; both edges of the 09:35–15:00 window; a bar that opens through the stop
before the fill; every exit (target, stop, a gap through the stop, the time
stop, both stop-first and target-first when one bar reaches both, and an early
close with after-hours bars ignored); each session limit on its own; the
summary measures; the CSV through the real Strategy Lab importer; and the
script end to end with a stub loader. Every scenario runs long and, reflected
through 100, short. Planted defects (no chase limit, no stop buffer, the
target filling first, no VWAP cancel, a four-bar window, filling at the signal
close, the time stop a bar late, no −2R limit, 15:00 excluded) each fail it.

Not verified: that a Pine version would match. There is no Pine yet; if one is
written, the Market Map parity method (`docs/pine/README.md`) is how to check
it against this engine.
