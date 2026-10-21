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
3. **Owner-only API:** feed, event detail, coverage, since-last-visit and
   feedback.
4. **`/radar` screen,** built against sample events alongside step 2.
5. **News enrichment:** "news nearby" or "cause unknown" on each event.

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

## Activation boundary

Merging builds the recorder; it stays off. Recording 3–5 sessions for step 2
starts only after Isaac's separate OK, by setting both variables in the VPS
`backend.env`. Nothing here sends alerts.
