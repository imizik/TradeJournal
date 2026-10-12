# Setup scanner S1 — candidates and a rules-only options baseline

Selected by Isaac on October 12, 2026 as build step 2 of the
[shadow trader design](shadow-trader-design.md#build-order-after-dots-steps-35).
**Contract only; nothing is built or activated.** S1 has no model, no Dot, no
connector, no alert and no real order. It produces the setup feed that the
co-pilot and the shadow trader will later consume, plus the rules-only paper
baseline they are judged against.

## Why these rules

From Isaac's 1,525 closed option trades (July 2025 – October 9, 2026, both
accounts, entry context saved at each first fill; analysis run October 12 and
not stored in the repo):

- Entries against the move toward VWAP (call below VWAP, put above it) earned
  about +$11.1k, profit factor 1.68 — his strongest setup.
- 15-minute opening-range breaks earned about +$2.4k; calls did better than puts.
- Trades closed within 60 minutes earned about +$35k; trades held 1–6 hours
  lost about −$17.6k and overnight holds about −$4.6k.
- 0DTE earned about +$17.4k; 1–2 DTE lost about −$9.5k.
- Leaks: puts in the first 15 minutes (−$5.3k), puts chasing an extended move
  (−$5.2k), and a sixth-or-later entry in a day (slightly negative).

Setup tags were approximate rules over saved context, so these figures choose
starting rules; they are not evidence that the rules have an edge.

## Universe and session

`AAPL AMZN GOOGL META SPY QQQ NBIS MU CRDO MRVL LLY AMD`. MSFT, NVDA and TSLA
are left out of version 1 at Isaac's choice (they lost money for him); adding
them back is a new scanner version. Regular session only, scanning completed
5-minute underlying bars from 09:45 ET. No new candidate after 15:00 ET.

## Setups (scanner `s1-v1`)

Prices are underlying prices from completed bars. Daily ATR is the 14-day ATR
as of the prior close. Parameters are versioned; changing one creates `s1-v2`.

**VWAP fade (calls and puts).** Long version (call): price has been at least
0.35 daily ATR below session VWAP, then a completed 5-minute bar closes above
the previous 5-minute bar's high while still below VWAP. Stop: the session low
reached during the stretch, minus 0.05 daily ATR. Target: session VWAP at
detection. Require target distance ≥ stop distance. The put version mirrors it
above VWAP. At most two fade candidates per symbol per day.

**Opening-range break (calls only).** The first completed 5-minute bar of the
day to close above the 09:30–09:45 high, closing by 10:45 ET, above VWAP, with
volume at least the average of the three opening-range bars. Stop: the
opening-range midpoint. Target: entry plus twice the stop distance. One per
symbol per day.

**Cooldown and duplicates.** No new candidate on a symbol while one of its
paper trades is open, and none within 30 minutes of that symbol's last
candidate. A repeated detection of the same bar is the same candidate.

**Flags (recorded, not filtered).** `put_extended` (more than
1.5% beyond VWAP or 0.8% beyond EMA9 in the trade direction), and `sixth_plus_entry`
(Isaac's sixth or later entry that day, filled in at review, never visible to
the scanner or a later shadow before commit). Puts in the first 15 minutes
cannot occur because scanning starts with the 09:45 bar, so that leak is
measured on Isaac's own trades, not flagged here.

## Contract choice

A fixed rule picks the contract at detection from the Tradier chain already
used by [`options_chain.py`](../../backend/app/engine/options_chain.py):

- Expiration: same day if listed; otherwise the nearest with 3–7 days to
  expiry. Never 1–2 days to expiry.
- Delta 0.25–0.45, closest to 0.35; call for long setups, put for short.
- Open interest ≥ 500, day volume ≥ 100, bid > 0, spread ≤ 10% of mid.
- No qualifying contract: the candidate is saved as `no_contract` and has no
  paper trade.

## Candidate record

Append-only, one row per candidate: ID, scanner version and parameter hash,
symbol, setup, direction, flags, detection time, source bar start/close times,
frozen facts (last bar OHLCV, VWAP, opening range, daily ATR, EMA9),
underlying stop and target, chosen contract with its quote time, bid, ask,
delta, open interest and volume, and a hard expiry 10 minutes after detection.
The later co-pilot and shadow read this frozen record; nothing edits it.

## Rules-only paper trade

Every candidate with a contract gets one simulated contract, priced from
option quotes and never backdated:

- **Entry:** the ask of the first quote taken after the candidate is saved.
- **Exits, all judged on the underlying and priced at the bid of the first
  option quote after detection:** stop, target, a 60-minute time stop, and a
  flat-by time of 15:45 ET for same-day contracts or 15:50 ET otherwise.
  Nothing is held overnight.
- **Missing quotes:** if no quote arrives within 2 minutes of an entry or exit
  decision, the trade is `unresolved` rather than filled at a guessed price.
- Commission $0.65 per contract per side, disclosed.

Results report per-contract dollars and return on premium, by setup, symbol,
direction, flag and expiry bucket. A second view applies 2× the observed
spread as a pessimistic cost check.

## Storage, service and safety

New tables for candidates and paper events, added by an Alembic migration.
That makes S1 consequential under the [review policy](pr-review.md): full
verification, an independent review, and the deployment backup and
market-hours rules in the [deploy guide](../../deploy/README.md#automatic-deployment).
The scanner runs inside the existing backend job system, off by default
behind one environment flag, uses existing Alpaca and Tradier credentials,
and sends no alert in S1. Restart recovery resumes open paper trades from
saved events; a monitoring gap longer than 2 minutes on an open trade marks it
`unresolved`.

## Before switching it on

1. **Historical fire-rate check** (done, results above). Replay the rules over completed sessions
   to confirm a manageable candidate count (target 3–15 a day in total) and
   to catch rule bugs. Use stock minute bars only, with no option prices and
   no profit tuning. Keep the most recent four weeks untouched as a holdout.
2. **Owner approval to enable on the VPS**, then 10 live sessions forward.
   Forward results decide whether the rules stay; nothing is tuned on them
   until 50 resolved paper trades exist.

## Historical fire-rate check (October 12, 2026)

Replayed over 135 sessions (March 2 – September 11, 2026) of Alpaca SIP
split-adjusted 5-minute bars; September 14 onward is held out and was not
examined. Counts and exit types only; no option prices and no profit figures.
The script lives outside the repo.

| Rule set | Setups per session | Note |
|---|---|---|
| Fade 0.25 ATR, opening-range break any time, no volume check | 18.1 | Above the 3–15 target; the break fired on 58% of symbol-days |
| Break by 10:45 + volume ≥ opening-range average | 12.9 | Break cut from 691 to 108 |
| **Above + fade 0.35 ATR (adopted as `s1-v1`)** | **8.8** | 1,193 setups: 601 fade puts, 484 fade calls, 108 break calls; 1 session had none, busiest had 24 |
| Above + fade 0.5 ATR | 4.3 | 11 sessions with none |

Every symbol produced setups and no session had missing data. In the adopted
set, 57% of underlying exits were the 60-minute time stop, 32% stops, 9% targets
and 2% the flat-by time: the VWAP target is usually farther than an hour away.
This is a property of the rules to watch forward, not a reason to tune them.

## Build status (October 12, 2026)

Built, not activated. `app/engine/scanner_rules.py` holds the rules and
`app/engine/setup_scanner.py` runs them inside the level alert monitor's
pass when `SETUP_SCANNER_ENABLED=true` (default off, and level alerts must
also be running). Migration `a7c3e9f1b2d4` adds `scanner_candidate` and
`scanner_event`. The owner page is `/scanner` (`GET /scanner/day`).

Implementation choices within this contract: session VWAP uses each
minute's typical price; daily ATR is the simple mean of 14 true ranges from
Tradier daily bars; the scanner judges only the newest completed 5-minute
bar and skips one noticed more than two minutes late; stop and target are
judged on completed 1-minute bars that start after the entry minute, the stop
winning a bar that touches both. Same-day contracts are flat by 15:45 and
others by 15:50 (or 10 minutes before an early close).

An entry or exit is priced only from a quote read within two minutes of its
decision whose bid and ask were both updated at or after the decision;
otherwise the trade is `unresolved`, even if a usable quote arrives later.
A gap in watching an open trade ends it `unresolved` only when an exit
condition fell inside the gap: the minute bars cover the rest of the gap, so
nothing is backdated. The review-time `sixth_plus_entry` flag counts trades
opened that day, not fills.

Budget when enabled: each 5-minute bar reads 12 one-minute series from the
chart feed's shared 60-per-minute allowance (plus 12 daily series once a
day), and each open trade re-reads its symbol about three times a minute. A
symbol whose read is refused is retried on later passes while the bar is
still within two minutes. Option quotes use Tradier's quote endpoint, which
waits out a rate limit inside the monitor pass. Watch for `rate_limited`
chart reads during the first live sessions.

Fixture tests cover the rules, duplicate suppression across a restarted
process, entry and exit pricing, missing quotes, late exits and the
review-time flag. A seeded local page was checked at desktop and 375px
widths. No live session has run.

## Acceptance

- Candidates appear with correct frozen facts and source times on a live
  session, and duplicates are suppressed across a restart.
- Every paper trade has an entry and exit quote time after its decision time,
  or is `unresolved`.
- One API restart with an open paper trade leaves exactly one entry and one exit.
- The owner can see the day's candidates and paper results in the app.

## Out of scope

Co-pilot alerts, Dot wake-ups, shadow decisions, real orders, intraday
re-entry rules and any change to Isaac's own trade records.
