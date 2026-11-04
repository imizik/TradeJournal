# Position alert baseline — November 3, 2026

A historical ledger of the first frozen alert **condition** per trade and
what actually happened afterward. This is a descriptive pre-alert baseline
for `/proof`, not evidence that alerts caused a change or improved returns.
No alert was sent by this work. No P&L comparison is reported.

## Population and privacy

Reused the unchanged [exit study](../../backend/scripts/exit_counterfactual_study.py)
and [frozen protocol](../exit-counterfactual/protocol.json),
`exit-counterfactual-20261024-v1`. The original private extract/run files were
no longer present; the committed October 24 aggregates cannot supply a
per-trade ledger. A fresh extract used the script's existing `BEGIN READ ONLY`
SQL over SSH, followed by `run` against the existing local option-minute cache,
without `--fetch`. No provider calls, new charges, production writes or
prospective evaluation occurred.

The fresh extract contains **1,531** closed/expired option trades opened
July 10, 2025 through October 19, 2026. The frozen eligibility checks exclude
**25** with holding windows over ten calendar days. **1,506** are analyzed;
none lack cached bars or fail FIFO allocation. Recorded outcomes match the
fill replay for all analyzed trades. All 1,506 closed before the October 21,
2026 alert launch; the additional close-date filter removes zero trades.
The original October 24 extract had 1,528 trades and excluded 22, so this is
a refreshed historical snapshot, not a claim of byte-for-byte reproduction.

This is the **frozen cohort subset** of `/proof`'s baseline, not its full
population: `/proof` selects long-option trades by close date without this
study's entry-date and ten-day restrictions. In particular, October 20 entries
and longer holds are outside this report. These exclusions are not zero events.

Only aggregate counts and timing enter git. The per-trade ledger, timestamps,
identifiers, fills, entry context and analysis helper stay in the ignored,
owner-only local directory `backend/data/position-alert-baseline-20261103/`.
`ledger.jsonl` has one row per analyzed baseline trade, its entry/close times,
opened-green flag, and each observed first condition's timestamp, elapsed
minutes, FIFO response and study-execution availability. Trades without an
event remain in the ledger with an empty event map.

## First conditions and actual follow-up

Counts are distinct trades **within each row**; the same trade can appear in
several rows. Medians use elapsed wall-clock minutes from first entry to first
condition, including overnight time. Each response column counts trades and
sums to its row's condition count.

| Kind | Trades with condition | Median minutes from entry | Closed ≤15m | Trimmed ≤15m | Closed later same day | Held overnight | Expired |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Give-back | 247 | 35 | 49 | 6 | 115 | 67 | 10 |
| Held past an hour | 485 | 60 | 39 | 15 | 177 | 224 | 30 |
| Last-day / expiry (first warning) | 53 | 228 | 7 | 0 | 13 | 0 | 33 |
| Opened while green (habit, not an alert) | 632 | 0 | 238 | 29 | 217 | 135 | 13 |

There are zero unmatched, rolled or still-open responses in these rows. Stored
entry context is available for all 1,506 trades: zero opened-green exclusions.
The 25 duration exclusions apply before every row, including opened-green, to
keep one common frozen analysis cohort.

## Definitions and interpretation

The three trigger kinds call the study's existing `trigger_time`, `Position`
and `judged_bars` functions, with **no constant changes**. Count a condition
only while contracts remain open and strictly before the actual final sale
(or session close at expiration for expired trades). Give-back uses regular
session minute-bar closes, skipping bars containing fills, arms at +10% and
$50, and first triggers at or below +3%. The hour clock is first entry plus
60 minutes, anchored no earlier than 09:30 ET on entry day and suppressed
when due at/after that day's close. The expiry clock is 90 minutes before
the expiration-day close, using the frozen early-close calendar.

These are modeled condition opportunities, not reconstructed phone deliveries.
The frozen study's `trigger_time` returns exact clock times for hour/expiry;
give-back returns a judged bar's close. The ledger preserves those code
semantics. For the hour/expiry clocks it does not require a bar at the clock
instant. Prices are historical trade-bar closes, not the live midpoint.
Today's live suppression, grace periods, repeats, delivery caps, additional
expiry alerts and later rule changes are not retrofitted. “Last-day / expiry”
here means only the protocol's first expiry-day warning, not its final or
day-before warnings.

The study's original executable-exit counts are **206 give-back, 337 hour,
38 expiry**. They are smaller because `execute` additionally needs a cached
bar opening within five minutes, before final exit, with contracts still open.
The condition counts above include **41, 148 and 15** additional opportunities,
respectively, without that execution evidence. A missing execution opportunity
does not erase a clock/condition, and neither count establishes deliverability.

“Opened while green” is **not a fourth frozen alert rule**. It calls
[`exit_habits.habit_flags`](../../backend/app/engine/exit_habits.py): the
first entry fill's stored `realized_pnl_today_before > 0` for its account.
A supplemental read-only query retrieves that context for only the frozen
cohort, selecting the first entry by timestamp and fill ID exactly as
`long_rows` does. No missing context is inferred from subsequent outcomes.
Its comparison moment is entry itself (zero minutes); FIFO follow-up covers
the contracts open including fills at that timestamp.

Every event's response calls the existing `exit_habits.follow_up` directly,
with the actual fill history, contracts open at that moment, and no reference
mark. A scoped read also checks derived roll-close markers. No price-relative
result is used. Under its FIFO definitions, later purchases sit behind the
contracts open at the event:

- `closed_15m`: all those contracts sold within 15 minutes, inclusive.
- `trimmed_15m`: some, not all, sold within 15 minutes; this takes precedence
  even when the rest expired or sold on another day.
- `expired`: some remained at expiration, with no qualifying early trim.
- `closed_later`: all sold later the same ET day, with no qualifying early trim.
- `held_overnight`: all sold on a later ET date, with no qualifying early trim.

These responses describe actual behavior after a hypothetical condition. They
are not responses to notifications received. The `/proof` habits
`green_to_red`, `held_hour_lost` and `expired_worthless` are outcome-based flags,
not the three trigger counts above. This report does not recompute their rates
or change `/proof`'s verdict, sample threshold or production behavior.

## Reproduction and checks

Source before this report: `9ff70b2a38a23e9ba924b0c9b90db0e7984b3a43`.
Protocol, study constants and engine definitions are unchanged.

- Extract SHA-256: `4ada80b1977230773bd0d919cd3ea42f766b8fcc651d5484fee8253de7c33a47`.
- Private ledger SHA-256: `890bd5596a6163e53e7963d02446ea87d8cf67c1e8219952728fba183026487f`.
- Private `run/results.json`, `run/trades.jsonl`, `supplement.sql`,
  `supplement.json`, `build.py` and `summary.json` retain the input/run receipt
  and aggregation method alongside the ledger. The helper uses the private
  temporary working directory named in its source; it is not a product script.
- Checked row totals against response totals; execution counts agree with
  the unchanged study output. Cache fetch count is zero.
- Existing focused study and exit-habit tests pass (37 tests).

Report-only PR; owner review and merge. No activation, deployment, schedules,
rule changes or changes to the registered study are included.
