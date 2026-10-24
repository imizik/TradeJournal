# Radar

Radar is a persistent feed of meaningful intraday market changes outside
Isaac's watchlist: stocks running ahead of or behind SPY and their sector, and
curated groups moving together, each saved with its evidence, how complete the
recording was, and a chart link. Isaac selected it on October 21, 2026
([priorities](product-roadmap.md#selected-priorities--october-11-2026)).

It is not a leaderboard. It sends no phone alerts, never trades, and does not
involve Jo.

## Build sequence

1. **Symbol list and quote recorder (built, off).** The tracked list
   `backend/app/data/radar_universe.json` (versioned; symbols, their source
   buckets/groups, benchmarks and the curated groups) and a once-a-minute
   Tradier quote pass, `backend/app/engine/radar_runner.py`, writing to its own
   append-only SQLite file, `backend/app/engine/radar_store.py`.
2. **Detection rules (built, provisional `radar-rules-v0`):**
   `backend/app/engine/radar_rules.py`, run by the recorder after each pass.
   They write the event and revision rows whose shape PR 1 defines
   (`RadarEvent`, `RadarEventRevision`; sample in
   `backend/tests/fixtures/radar/sample_event.json`). See
   [Alert rules](#alert-rules-radar-rules-v0-provisional).
3. **Owner-only API (built):** `backend/app/routers/radar.py` — feed, event
   detail, coverage, since-last-visit, visits and feedback. See
   [Feed API](#feed-api-and-screen).
4. **`/radar` screen (built),** `frontend/app/radar/page.tsx`. Step 2 now
   writes real events; the browser test still checks it against the sample
   event (`frontend/e2e/radar.spec.ts`).
5. **News enrichment (built):** "news nearby" or "cause unknown" on each
   event, `backend/app/engine/radar_news.py`. See [News nearby](#news-nearby).
6. **Premarket pilot (built, off, record-only):**
   `backend/app/engine/radar_premarket.py`. See
   [Premarket pilot](#premarket-pilot-record-only).

## Recorder

With `RADAR_ENABLED=true` and an absolute `RADAR_STORE`, the API process runs
one pass every 60 seconds inside the regular session of the market calendar
(holidays and early closes included). It is off when Tradier is not configured
and in the isolated Dot trial. Each pass quotes the list in requests of at most
50 symbols (169 symbols is 4 requests; hard cap 6) through the no-retry Tradier
call, sharing the 120-a-minute market-data allowance with charts, position
alerts and the scanner. A rate limit or transport error ends the pass as
failed or partial; the next minute tries again.

The file holds one row per pass (times, universe version, symbols requested,
returned and unmatched, requests used, error or skip reason) and one row per
symbol per pass (last, previous close, open, high, low, cumulative volume,
bid, ask, Tradier's trade time and our retrieval time). Quote rows older than
the newest 20 recorded sessions are pruned (disk); passes and events are kept. When
the calendar is unavailable during clock hours the pass is recorded as skipped
rather than guessed.

## Feed API and screen

All four routes are owner-only (assistant sessions are denied) and read-only
apart from two append-only tables, `visit` and `feedback`, in the same Radar
file (older files gain them when opened).

- `GET /radar/feed?session=YYYY-MM-DD` returns the session's events with their
  latest revision status and rating, `since_last_visit` (events first seen
  after the last recorded visit, or after `?since=` when the page pins it),
  coverage (passes recorded against regular-session minutes so far, last ok
  pass, symbols missing from the latest pass, universe version) and a `state`:
  `off` (not enabled, no absolute `RADAR_STORE`, or the file cannot be opened;
  never a 500), `no_data`, `recording`, or `stale` (during regular hours, no ok
  pass for over 3 minutes). The default session is today's New York date when
  it has data, else the latest session recorded.
- `GET /radar/events/{event_id}` returns the event exactly as saved and every
  revision in order. Nothing is recomputed or priced again.
- `POST /radar/visits` records Isaac opening the screen; the page posts it once
  per load, after reading the feed.
- `POST /radar/events/{event_id}/feedback` takes `useful`, `already_knew`,
  `too_late` or `irrelevant`; the latest rating wins on read.

The screen shows one coverage line, then "New since your last visit" and the
earlier events as cards that expand into the original evidence, the later
readings, an Open chart link and the four rating buttons. No detection runs
here; with no events it shows the empty state with coverage. Events whose
`rule_version` is `radar-rules-v0` carry a small "v0 · provisional rules" tag.

## Alert rules (radar-rules-v0, provisional)

`backend/app/engine/radar_rules.py` is pure arithmetic over recorded passes. After
each ok or partial pass the recorder runs it, appends any new events and
revisions, then runs the news check, so a new event gets news the same minute.
It reads the session's pass list, the quotes of only the passes its windows need
(at most six) and the session's saved `radar-rules-v0` events. A detection error
is logged and never affects the pass. Event ids are derived from the session,
kind, symbol or group, direction and a per-key count
(`rv0-2026-10-22-group-ai-networking-and-connectivity-down-1`), and rows already
saved are skipped, so replaying the same passes, or a restart, writes the same
rows once.

Each rule compares a 30-minute window: the pass nearest 30 minutes earlier
(within 90 seconds, same session and universe version) to the current pass. The
window never starts at the previous close or the open, so an opening gap alone
never qualifies. A quote counts only with a positive last and prev close and a
trade no more than 120 seconds older than its retrieval; otherwise that symbol
has no reading (no event, nothing filled in).

- **Stock vs SPY (`relative_to_spy`):** the stock's window return minus SPY's is
  at least **4.5 points** and the stock itself moved at least **2.0%**.
- **Stock vs sector (`relative_to_sector`):** the same against the stock's
  `sector` ETF (4.5 points, 2.0% floor), skipped while the stock has an active
  same-direction SPY event or its SPY reading also qualifies. It therefore only
  fires when the sector ETF itself moved, e.g. a stock holding up while its
  sector falls; on the calibration sessions it never fired.
- **Group (`group_move`):** a curated group with at least **4** members with data,
  a median member-vs-SPY of at least **2.0 points**, and at least **60%** of
  members on the median's side. The event lists the members moving that way
  (largest first), the member and median measures, members missing in
  `coverage.symbols_missing`, "mostly X" when one member is over half the
  same-direction move, and "Own alerts: …" for members that have their own SPY
  event. Members' own events still fire.
- **Persistence:** a reading must hold on **3** consecutive passes (no gap over
  150 seconds) on the same window.

One event per (session, kind, symbol or group, direction) is active at a time.
Later passes measure the move since the event's own window start and append a
revision: `extended` when it grows by **1.5 points** past the highest reported
reading (**1.0** for groups), `faded` when it falls below half of that, and
`reversed` when it is past the threshold the other way. A faded or reversed
event is closed; the same key can start a new event (`…-2`) only **30 minutes**
after it closed. The opposite direction is a separate key.

The numbers are module constants in `radar_rules.V0`; changing them means a new
`RULE_VERSION`. They change at most every few days, never mid-session.

### Calibration and replay

`backend/scripts/radar_replay.py /abs/path/radar.sqlite [--session D] [--set name=value] [--quiet]`
opens a store read-only, replays each session's passes through the rules (using
the current tracked list for kinds, sectors and groups) and prints counts by
kind/direction and each event's first-seen time, summary and later revisions.
`--set` overrides one threshold for that run only. The live recorder path and
the replay produce identical events and revisions on the same passes.

v0 was set on **two recorded sessions** (October 22, full; October 23, to
13:27 ET) from a read-only copy of the VPS file. It is provisional: two
sessions say nothing about usefulness, and v1 is due after the October 26 close
with three sessions and Isaac's ratings.

| Session | Passes | Events | vs SPY up/down | vs sector | Group up/down | Revisions |
| --- | --- | --- | --- | --- | --- | --- |
| Oct 22 (SPY −1.4%) | 390 | 7 | 1 / 1 | 0 | 1 / 4 | 14 |
| Oct 23 (to 13:27 ET) | 238 | 9 | 3 / 2 | 0 | 1 / 3 | 10 |

Checked against October 22's known moves: SPOT (+10.6% on the day) and most of
COHR's, AAOI's and ALAB's declines came at or before the open or ground lower
over hours, so none qualifies on its own under v0 (Movers still ranks them);
the AI-networking selloff surfaces as a group event at 10:33 ET (6 of 6 behind
SPY, biggest COHR), extended at 10:51, 11:31 and 14:02. Dropped during
calibration: a 15-minute window (two extra events a session, about 15 minutes
earlier, one of which faded within 8 minutes) and a lower sector threshold
(3.0–4.0 added 1–13 sector events a session that mostly repeated the SPY story
against a flat sector ETF).

### Outcome scoring

`backend/scripts/radar_outcomes.py /abs/path/radar.sqlite --out /abs/path/outcomes.jsonl` opens the store
read-only and scores each recorded event of a completed session at its first-seen pass: the return
against SPY at +30 min, +60 min and the close, signed in the event's direction, beside the plain Movers
leaders (or laggards) and five random tracked stocks at the same pass. It appends one line per newly
scored event, so results outlive the 20-session quote pruning; run it at least every 20 sessions. The
read-out is per rule version and decides only after 20 sessions of one version. No provider or model
call. Question, comparisons and decision: [spec](../research/radar-outcomes/spec.md).
`backend/scripts/radar_outcomes_review.py` optionally asks one Copilot Lab research job, on the Claude
plan only (never an API key), what set the furthest continuations apart from the furthest reversals;
it is hindsight input for a later rule version.

## Movers now

`GET /radar/movers?session=YYYY-MM-DD` (owner-only, read-only) supplies the
ranking below saved developments on the screen. It is a plain ranking of the latest ok or partial pass of the
session. It is not an alert and has no threshold, event or provider call; it is
also the "plain movers list" the pilot compares alerts against. Per stock it
gives `open_gap_pct` (open versus previous close), `day_pct` (versus prev close), `from_open_pct` (versus today's open, so a
gap shows apart from an intraday move), `vs_spy`, `vs_sector` (against the stock's
`sector` ETF, a field added in `radar-universe-v2`) and `last_15m_pct` (versus the
pass closest to 15 minutes earlier, within 2 minutes of that target, else null).
Leaders and laggards are the top and bottom 10 stocks by `vs_spy`; each curated
group reports members with data, how many are ahead of or behind SPY, the median
`vs_spy` and the member with the largest move, sorted by absolute median. A symbol
with a missing or non-positive last or prev close is counted as missing, never
shown as 0%. `state` is `off`, `no_data` (also when SPY has no usable quote),
`ok`, or `stale` (during regular hours, no ok pass for over 3 minutes). The screen shows opening gap and since-open returns separately from day and 15-minute returns;
these returns are not additive. Each latest and earlier quote must pass the existing
peer-comparison endpoint checks: finite positive last, retrieval inside its own
pass, and trade time 0–120 seconds before retrieval. Historical sessions use
recorded time, not today's clock. Ineligible latest quotes are omitted from
rankings, benchmarks and group counts; an ineligible earlier quote leaves 15 min
blank. Saved developments appear first, including their existing revisions,
news and feedback. Movers refresh every 60 seconds while the tab is visible.

## Charts group movement

The owner approved a read-only peer comparison on October 22, 2026. Charts
Overview → Peers adds **Group movement**, with **15 min**, **Session** and **From low** views. It uses recorded observations,
independently of the still-unbuilt event detector. This implementation does not
activate recording or establish live usefulness.

`GET /radar/groups/compare?symbol=NVDA&group=GPUs%20and%20AI%20compute%20chips`
is owner-only, including when a market-only assistant can read stock Charts.
It returns all current curated groups containing the symbol, the selected group,
source/version, session, shared window/pass IDs, selected-stock/peer/QQQ/SPY
rows and coverage. With no group parameter it selects the first valid group;
an explicit unrelated group is rejected. An ungrouped symbol is disclosed.

The 15-minute comparison uses the latest completed usable pass and the pass at or before
15 minutes earlier (at most 90 seconds earlier). Both endpoints use the same
pass IDs for every row, in one session and a compatible universe version. Older
membership is not archived. The sole historical compatibility exception is
v1/v2 when the complete group-membership fingerprint matches the pinned equal
definitions; v2 added sector annotations only. Other version mismatches are
refused rather than reinterpreted. Passes taking over 90 seconds are refused. Each price must be
finite and positive; its retrieval must fall within its pass, and its provider
trade timestamp must be present, no later than retrieval and at most 120 seconds
old. These are initial observation eligibility limits, not calibrated trading
thresholds. Return is `100 * (end / start - 1)`; missing observations stay null.
There is no interpolation, per-symbol substitution, shortened lookback, overnight
carry, synthesized candle or probability score. Actual trade/retrieval times
are available per row because batches and trades do not occur simultaneously.

The same response includes `session_context`, independently evaluated from the
first usable (`ok` or `partial`) pass in that session to the same latest pass.
It requires at least one minute between endpoints. The baseline never advances
to replace a missing member or an incompatible universe version. All endpoint
eligibility rules above apply. A late recording start is shown by its actual
time: this is **since first recorded sample**, not market-open return, previous
close return, recovery from the low or evidence of a sustained trend. There is
no 600-pass truncation that could silently advance this baseline. Failed passes
remain gaps. Either window can be unavailable while the other is available.
The Session toggle uses the same response, without another request.

The response also includes `recovery_context` for **From low**. It finds the
selected stock's lowest eligible sampled `last` in that recorded session, then
compares every peer and QQQ/SPY from that exact pass to the latest usable pass.
It does not compare each peer from its own low. Equal minima use the earliest
pass (pass ID breaks equal-time ties). Selecting another stock recalculates the
anchor. This is not the true tick/candle/session low or the provider's day-low
field: recording can start late and miss lower prices between samples.

The low search uses the same positive-price, trade-age, retrieval and pass-duration
eligibility rules. An incompatible universe version anywhere among usable session passes
refuses recovery context. `low_anchor` carries price, pass ID/time and actual
trade/retrieval times. `low_search` carries the search interval, eligible samples,
omitted samples and eligible/expected minute buckets, including gaps before the
anchor. Missing or ineligible search observations make a comparison partial.
The latest pass must have an eligible selected-stock price; no earlier latest
price is substituted. At least two eligible samples and one minute after the
anchor are required. A newly recorded low has no rebound window yet; a return
to an earlier equal low displays zero and **no net rebound**. Missing peer
endpoints stay null. This describes endpoint participation, not a sustained
recovery, bottom confirmation or future profit probability. The toggle uses the
same response and refresh as the other two views.

Coverage counts eligible peers (excluding the selected stock and benchmarks),
up/down peers, missing symbols and recorded minute buckets in the window.
Two endpoint returns do not demonstrate a continuous or sustained recovery.
Missing intermediate minutes or rows make the response partial. An end pass
older than three minutes during regular hours is stale. During the regular
session, no observations today means insufficient, not yesterday's comparison.
Outside regular hours the latest recorded session is labeled explicitly.
An unavailable calendar prevents a claim about the current session.

The API opens only an existing, app-ID-checked Radar file in SQLite read-only
mode: no schema initialization, visits, feedback or event writes. It reads
pass metadata from one session, the endpoint passes' quote rows, and an indexed
selected-symbol/session quote read for the sampled-low search. It makes no
quote/history/news requests; the shared market calendar may refresh its existing
monthly cache. Charts adds the read to its existing visible Overview peer refresh
cycle (60 seconds), aborts obsolete symbol/group requests, and hides old values
on refresh failure. There is no new timer, collector, subscription or AI call.
Group choice survives peer navigation when membership permits. The older day
change chips and valuation data remain separate and explicitly labeled.

Tests: `backend/tests/test_radar_comparison.py`, the owner boundary in
`backend/tests/test_radar_api.py`, and desktop/390px interaction and failure
coverage in `frontend/e2e/symbol-info-peers.spec.ts`. Historical event-to-chart
context and alternate lookbacks remain later slices; this is a current recorded
comparison, not a replay of an event or the chart crosshair time.

## News nearby

After each regular-hours pass the recorder checks headlines for events under
two hours old: once when an event has no check yet, and once more 15 minutes
after that first check. At most 3 news requests go out per pass; the rest wait
for the next minute. Each request asks `app.engine.news` (Alpaca/Benzinga, one
fast page, no retry) for the event's own symbols only, over the 24 hours before
`first_seen_at` up to the check time. It reuses the morning brief's
`eligible_headlines` filter and `catalyst_first` ordering and keeps at most 5
headlines, each marked as published before or after the event was first seen.

Every check is a new row in the append-only `event_news` table (older files gain
it when opened), with status `found`, `none_found` or `unavailable` (the
provider failed). The event itself is never rewritten. A news failure never
affects the quote pass.

The feed and the event detail carry a `news` block with the latest check;
the detail also lists every check in order. Each card shows one line — "News
nearby: headline · source · time (before/after the move)", "No news found —
cause unknown" or "News unavailable — cause unknown" — and the detail lists the
headlines with links and when they were checked. Nothing says a headline
caused the move.

## Premarket pilot (record-only)

Radar's passes start at 09:30, but in an October 12–23 back-test (144 stocks,
Alpaca SIP minutes) 41% of the moves that reached 5 points against SPY had
started overnight or premarket. Unusual volume, options volume and headlines
found almost none of the intraday moves earlier than price did. The pilot
checks whether a pre-open list is worth having; it alerts no one and is not on
the screen.

With `RADAR_PREMARKET_ENABLED=true` inside an enabled recorder, each open
session day gets one scan at 08:50 and one at 09:20 New York. A scan makes one
batched quote read (previous closes, 4 requests), then one 1-minute timesales
read per tracked symbol through the shared chart feed (uncached), at 40 a minute (about
4.3 minutes for 169 symbols), stopping 7½ minutes after the checkpoint so the
09:20 scan ends before the open. Only minutes completed by the checkpoint
count. Tradier quotes' `last` stays at the regular close outside the session,
so prices come from the minutes; on October 22–23 their 09:25 closes matched
SIP on all 46 checked symbol-days, with 80–90% of SIP's dollar volume.

Rule `radar-premarket-v0` (frozen for the pilot) flags a stock whose premarket
change differs from SPY's by at least 3 points, with at least $250k traded
premarket and a last minute at most 10 minutes before the checkpoint. Each
scan and every symbol's reading (previous close, last, bar count, volume,
dollar volume, change, change against SPY, flag, read error) are written once
to `<RADAR_STORE stem>-premarket.sqlite`, a separate append-only file; the
Radar store, its rules and its screen are unchanged. A failed scan is recorded
and not retried, and a setup error in the pilot file leaves the recorder
running without it. Deploys hold from 09:25, so one at 08:50–09:25 can cut a
scan short. The same back-test, at these two times, gave median lists of
15 and 23 stocks with 74–75% becoming 5-point moves.

Scoring after 10 sessions (read-only):

```bash
cd backend && PYTHONPATH=. .venv/bin/python scripts/radar_premarket_eval.py /abs/radar.sqlite
```

The 09:20 list passes when all four hold (every Radar session from the first
scan counts; a morning with no scan is a failed one): scans recorded on at least 9 of 10
sessions with at least 95% of reads succeeding; a median of 8–35 names a
session; at least 50% of names become moves of 5 points or more against SPY
after the open (from Radar's own passes); and at least 60% of the important
moves already 3 points away at 09:20 are on the list. The pilot stops early
on precision under 40%, more than 40 names a session, or failed scans on 3 or
more sessions. Passing earns a screen section next; phone alerts remain a
separate decision.

## Activation boundary

The recorder is off unless both variables are set in the VPS `backend.env`
(set since October 22 with Isaac's OK). The v0 rules have no flag of their own:
wherever the recorder runs, detection runs with it and writes events to the
screen. Nothing here sends phone alerts; those wait for a pilot. The premarket
pilot has its own `RADAR_PREMARKET_ENABLED`, off by default; turning it on is
Isaac's call.


### Movers to Charts navigation

Movers stock links carry their originating symbol, recorded session and pass
time. Group rows add **Compare in Charts**, passing the actual selected group
and its `most` stock; generic leader/laggard links do not invent membership.
Charts labels this dated navigation origin separately from current candles and
freshly read peer comparisons. A group link opens Overview → Peers on Session;
the existing comparison API validates current group membership. Unavailable or
changed groups do not silently fall back to a different group. No timestamp
replay, historical peer lookup, event detector or new market read is implied.

**Back to Radar** restores the selected session, expanded group list and group
location using an internal link. Origin parameters are validated, displayed as
plain text, and can be dismissed without affecting chart ranges or trade links.
The origin remains explicitly tied to its original ticker when another chart
symbol is selected. Existing event-detail links remain unchanged; historical
event-context handoff is deferred.

### Selected holding since entry

The same owner-only comparison endpoint accepts an optional `trade_id` and
returns one independently evaluated same-session entry window. It resolves the
original entry from the journal and reads only recorded Radar observations.
The selected holding disclosure refreshes while open; it does not add alerts
or a background recorder. See [the Charts contract](charts-workspace.md#same-session-since-entry-holding-context)
for timing, eligibility, missing-data behavior and tests.

### Since-entry context on existing holding alerts

Already-qualified holding alerts can append the same recorded entry comparison.
`backend/app/engine/radar_entry.py` shares the original-entry resolver with Charts;
`backend/app/engine/position_alert_context.py` reads at the alert detection cutoff,
using the alert monitor's already-read regular hours and the existing first curated
group for the symbol. The group is named; it is not an inferred owner preference.
No new trigger, flag, quote/news/model call, recorder or notification is added.

After duplicate/supersession checks, a new `PositionAlert.context_snapshot_json`
freezes the versioned result, entry and baseline times, group/version, Radar pass
IDs, returns and coverage. Account and first-entry source identity must match.
A rebuilt/missing trade that cannot be verified gets unavailable context. Adds
and partial exits retain the original entry. Later observations are excluded;
pending delivery retries never refresh the snapshot. Legacy rows remain null.
The additive nullable text column is migration `7c3e0a5b2d84`; no backfill occurs.

The phone keeps its existing reason/details first, then at most four context
lines: underlying window/returns, QQQ/SPY, named peer participation and sampling
limits. Missing rows stay unavailable, partial coverage is explicit, stale
numbers are withheld, and overnight entries stay unavailable. These are sampled
underlying endpoint movements, not option P&L, continuous trend or a sell signal.
This slice retains the trade-detail click target and adds no app screen.

Optional reads use their own journal session and a read-only Radar store with a
100 ms shared SQLite deadline (lock waits plus query progress checks). There are
no extra calendar reads. Missing, foreign, locked or unreadable storage produces
an unavailable snapshot; the original alert still proceeds. Alert thresholds,
dedupe, expiry, priorities and pending/sent/unknown behavior remain unchanged.
`sent` proves ntfy acceptance, not actual phone display. Tests cover recorded
fixtures and delivery mocks; production/phone usefulness is separate.
