# "Trend mode" — playing the day's trend either way (October 14, 2026)

Research only; nothing is wired into the scanner. Follows `RESULTS.md`,
which found the trend-continuation put only paid on days that turned out to
be down days. Question: can rules spot a trend day early enough, and do
trailing exits capture it? `trend_mode.py` has the rules (SPY gate, symbol
failed-pullback entry both directions, three exits); `trend_summary.py`
prints the tables in `out/trend_design_h3.md` and `out/trend_recent_h3.md`;
`out/late_morning_gate.md` holds the last check. Same pricing, contract
rules and 3% cost per side as `RESULTS.md`.

Windows: the s1-v1 design sessions (March 2 – September 11, 135 sessions) and,
at Isaac's request, the most recent 22 sessions (September 14 – October 13)
to check the current market. That uses the S1 fire-rate holdout once; it does
not affect the live 10-session acceptance.

## What we found

1. **Trend days pay when you hold.** With the SPY gate on, trades on days
   that really trended (hindsight label) made money both ways: VWAP-trail exit
   +34% return on premium on trend-down days and +36% on trend-up days,
   holding about 2.5 hours. The 60-minute time stop cuts most of that off.
2. **The early "trend day" read is the whole problem.** The 10:00 SPY gate
   (below opening range and VWAP, VWAP falling) turned down on 83 of 135
   design sessions — it caught all 17 real trend-down days but also 63 choppy
   ones — and on 18 of the last 22 sessions, of which only 2 trended down.
   On choppy days every variant bled (PF 0.5–0.8). Overall at 3% cost:
   best variant PF 0.99 (design) and 0.34–0.73 (recent).
3. **Down days do not announce themselves; up days partly do.** Checked on
   SPY alone over 157 sessions (no pricing): an 11:00 read "SPY ≥ 0.3 ATR from
   the open and on the same side of VWAP since 10:00" was right 63% of the time
   for up-trend days but only 25% for down-trend days; stricter versions never
   beat about one in three for down days. In this period, early morning
   selling was usually bought back.
4. **Late-morning up gate + calls with an EMA9 trail** was the only variant
   positive in both windows (design PF 1.22, +$7 per contract over 111 trades
   on 17 days; recent 13 trades on 2 days, PF 8.6). Too few days, and chosen
   after looking at the data — a lead, not a result. Puts under the mirror
   gate were +PF 2.0 with S1 exits in design but lost in every recent cut.

## Verdict

No rules-only trend strategy here beats costs reliably; don't add trend
mode as s1-v3. The edge is in knowing it's a trend day, and simple morning
rules can't tell a real down day from the many fake-outs in this market.
If anything goes forward, it is the late-morning up-trend call with an
EMA9 trail, as a paper-only idea re-tested on fresh sessions after S1
reaches 50 paper trades. In a market where morning pushes mostly fade, the
regime matches S1's existing VWAP fade more than trend-chasing.
