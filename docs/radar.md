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
2. **Detection rules,** calibrated on recorded sessions, then frozen and
   versioned. They write the event and revision rows whose shape PR 1 defines
   (`RadarEvent`, `RadarEventRevision`; sample in
   `backend/tests/fixtures/radar/sample_event.json`).
3. **Owner-only API (built):** `backend/app/routers/radar.py` — feed, event
   detail, coverage, since-last-visit, visits and feedback. See
   [Feed API](#feed-api-and-screen).
4. **`/radar` screen (built),** `frontend/app/radar/page.tsx`, checked against
   the sample event until step 2 writes real ones.
5. **News enrichment (built):** "news nearby" or "cause unknown" on each
   event, `backend/app/engine/radar_news.py`. See [News nearby](#news-nearby).

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
the newest 60 recorded sessions are pruned; passes and events are kept. When
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
here; until step 2 writes events it shows the empty state with coverage.

## Movers now

`GET /radar/movers?session=YYYY-MM-DD` (owner-only, read-only) and the first
section of the screen are a plain ranking of the latest ok or partial pass of the
session. It is not an alert and has no threshold, event or provider call; it is
also the "plain movers list" the pilot compares alerts against. Per stock it
gives `day_pct` (versus prev close), `from_open_pct` (versus today's open, so a
gap shows apart from an intraday move), `vs_spy`, `vs_sector` (against the stock's
`sector` ETF, a field added in `radar-universe-v2`) and `last_15m_pct` (versus the
pass closest to 15 minutes earlier, within 2 minutes of that target, else null).
Leaders and laggards are the top and bottom 10 stocks by `vs_spy`; each curated
group reports members with data, how many are ahead of or behind SPY, the median
`vs_spy` and the member with the largest move, sorted by absolute median. A symbol
with a missing or non-positive last or prev close is counted as missing, never
shown as 0%. `state` is `off`, `no_data` (also when SPY has no usable quote),
`ok`, or `stale` (during regular hours, no ok pass for over 3 minutes). The screen
tags a "gap" when `|from_open_pct| < |day_pct| / 3`, a plain label and not a rule,
and refreshes every 60 seconds while the tab is visible.

## Charts group movement

The owner approved a read-only peer comparison on October 22, 2026. Charts
Overview → Peers adds **Group movement · 15 min**. It uses recorded observations,
independently of the still-unbuilt event detector. This implementation does not
activate recording or establish live usefulness.

`GET /radar/groups/compare?symbol=NVDA&group=GPUs%20and%20AI%20compute%20chips`
is owner-only, including when a market-only assistant can read stock Charts.
It returns all current curated groups containing the symbol, the selected group,
source/version, session, shared window/pass IDs, selected-stock/peer/QQQ/SPY
rows and coverage. With no group parameter it selects the first valid group;
an explicit unrelated group is rejected. An ungrouped symbol is disclosed.

The comparison uses the latest completed usable pass and the pass at or before
15 minutes earlier (at most 90 seconds earlier). Both endpoints use the same
pass IDs for every row, in one session and the current universe version. Older
membership is not archived, so a version mismatch is refused rather than
reinterpreted. Passes taking over 90 seconds are refused. Each price must be
finite and positive; its retrieval must fall within its pass, and its provider
trade timestamp must be present, no later than retrieval and at most 120 seconds
old. These are initial observation eligibility limits, not calibrated trading
thresholds. Return is `100 * (end / start - 1)`; missing observations stay null.
There is no interpolation, per-symbol substitution, shortened lookback, overnight
carry, synthesized candle or probability score. Actual trade/retrieval times
are available per row because batches and trades do not occur simultaneously.

Coverage counts eligible peers (excluding the selected stock and benchmarks),
up/down peers, missing symbols and recorded minute buckets in the window.
Two endpoint returns do not demonstrate a continuous or sustained recovery.
Missing intermediate minutes or rows make the response partial. An end pass
older than three minutes during regular hours is stale. During the regular
session, no observations today means insufficient, not yesterday's comparison.
Outside regular hours the latest recorded session is labeled explicitly.
An unavailable calendar prevents a claim about the current session.

The API opens only an existing, app-ID-checked Radar file in SQLite read-only
mode: no schema initialization, visits, feedback or event writes. It reads at
most 600 pass records from one session and two passes' quote rows. It makes no
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

## Activation boundary

Merging builds the recorder; it stays off. Recording 3–5 sessions for step 2
starts only after Isaac's separate OK, by setting both variables in the VPS
`backend.env`. Nothing here sends alerts.
