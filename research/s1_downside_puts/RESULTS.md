# Downside put setups for S1 — research result (October 14, 2026)

Research only. Nothing here changes the live scanner, the s1-v1/s1-v2 rules
or the 10-session acceptance that began October 14. No PR (unproven strategy).

## Question

S1 has no trend-following puts, so on a trend-down day such as October 14 it
offers nothing on the downside. Would an opening-range **breakdown put**
(mirror of S1's break call), or a **trend-continuation put** (failed pullback
to EMA9 below VWAP), be worth adding as `s1-v3`?

## Method

- Same window as the s1-v1 adoption check: 135 sessions, March 2 – September 11,
  2026. September 14 onward stays held out and was not touched.
- Same universe (`AAPL AMZN GOOGL META SPY QQQ NBIS MU CRDO MRVL LLY AMD`),
  Alpaca SIP 1-minute bars, S1's own code for 5-minute bars, VWAP, EMA9, ATR,
  the `orb` call rule and the exit rule (`backend/app/engine/scanner_rules.py`).
- Contract rule from the contract doc: same-day expiry if listed, else nearest
  3–7 days; delta 0.25–0.45 closest to 0.35; option volume ≥ 100 before the
  setup. Delta is backed out of the last option trade (Black-Scholes, 4% rate).
  Open interest and the 10% spread limit cannot be checked historically.
- Paper trade as S1: stop/target on the underlying, 60-minute time stop, flat
  15:45 (0DTE) / 15:50; $0.65 per side. Priced from historical option trade
  bars (no historical quotes), so each side pays a haircut: 0%, **3% (main
  view)** and 6% of premium. The fill window is 5 minutes instead of 2 because
  trade bars are sparser than quotes.
- S1's own break **call** was re-run under the same pricing as a yardstick.
- Day types use the whole day's result, so they are hindsight labels, not
  something the scanner could know at signal time. Trend-down = closed ≥ 0.5
  daily ATR below the open and in the bottom 30% of the day's range.

Scripts: `backtest.py` (data and trades), `summarize.py` (tables). Raw output:
`out/trades.json`, `out/daytypes.json`; every table in `out/summary.md`.

## Headline (3% cost each side)

| Setup | Setups / session | Priced trades | Win rate | Profit factor | $ per contract | Return on premium |
|---|---|---|---|---|---|---|
| S1 break call (yardstick) | 0.8 | 79 | 43% | 0.97 | −$2 | +8.7% |
| **Breakdown put** | 0.7 | 60 | 28% | 0.91 | −$6 | −8.1% |
| Trend-continuation put | 8.8 | 727 | 30% | 0.83 | −$10 | −10.0% |

About a third of setups had no qualifying contract: 58% because Wednesday/
Thursday single stocks have no same-day or 3–7 day expiry (the rule skips 1–2
DTE), the rest because no strike was in the delta band with enough volume
(mostly CRDO, LLY, NBIS, MRVL).

## By day type (3% cost)

| Setup | SPY trend-down days | SPY choppy days | SPY trend-up days |
|---|---|---|---|
| Breakdown put | 14 trades, PF 0.16, −$99 avg | 36 trades, PF 2.09, +$54 avg | 10 trades, 0 wins |
| Trend-continuation put | 161 trades, PF 1.24, +$12 avg | 530 trades, PF 0.79, −$12 avg | 36 trades, PF 0.19 |

The breakdown put did *worst* on the market's trend-down days: by the time a
symbol closes below its opening range on those days the first leg is usually
done, and the stop at the opening-range midpoint is far enough away that the
60-minute time stop takes most trades out at a loss on premium decay.

The trend-continuation put makes money only on days that, in hindsight,
were the symbol's own trend-down days (PF 2.27). On everything else it bleeds
(PF 0.49 on choppy days), and it fires ~6 times a session on choppy days.

## Days that reverse

- Breakdown put: the day closed back above the entry on 51% of setups and
  above the stop on 20%; those reversal setups lost $50 per contract on average
  (2 wins in 15).
- Trend-continuation put: closed above the entry on 55%, above the stop on 26%;
  reversal setups lost $81 per contract (PF 0.08).

## Verdict

**Not worth adding as `s1-v3` now.**

- The breakdown put is roughly a coin-flip-minus-costs (PF 0.91 at realistic
  costs, 60 trades) and, against intuition, fails on exactly the trend-down
  days it is meant for. It is also only slightly worse than S1's own break call
  under this harsher pricing, so it is not clearly broken, just unproven.
- The trend-continuation put would more than double the scanner's alert count
  (8.8 extra per session) and loses money overall; its good results depend on
  knowing in advance that the day will trend down, which the rule cannot.
- Isaac's own history (puts chasing extended moves were a leak) agrees with
  this: no put rule here produced a reliable edge.

What could change it later: a real-time trend-day filter (for example SPY
already below its opening range and VWAP with breadth weak) tested as a new,
separate idea on fresh sessions — not tuned on these numbers or on the
holdout. Revisit after S1 has its 50 resolved paper trades.
