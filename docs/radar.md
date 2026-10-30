# Radar

Radar is a persistent feed of meaningful intraday market changes outside
Isaac's watchlist: stocks running ahead of or behind SPY and their sector, and
curated groups moving together, each saved with its evidence, how complete the
recording was, and a chart link. Isaac selected it on October 21, 2026
([priorities](product-roadmap.md#selected-priorities--october-11-2026)).

It is not a leaderboard. Phone pings are off unless `RADAR_ALERTS_ENABLED=true`,
which is on on the VPS since October 25, 2026
([Phone alerts](#phone-alerts-off-by-default)); it never trades and does not
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
7. **Phone alerts (built, on on the VPS since October 25, 2026):** `backend/app/engine/radar_alerts.py`, one
   ntfy ping per new event when `RADAR_ALERTS_ENABLED=true`. See
   [Phone alerts](#phone-alerts-off-by-default).
8. **Dip-buy candidates (built, off):** `backend/app/engine/radar_dip.py`, a
   separate first-hour rule `radar-dip-v0` with its own version, receipt and
   scoring. See [Dip-buy candidates](#dip-buy-candidates-radar-dip-v0-off-by-default).

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

## Proof read-out

`GET /radar/proof` (owner-only, read-only) feeds the `/proof` page: for the
newest rule version, the latest rating per event; for each stock event, whether
the plain Movers top 10 (rebuilt at every recorded pass of its session) listed
the stock before Radar's first sighting, only later, or never; and whether a
saved morning brief within 5 days named it first. Helping needs 20+ rated
events with 40%+ useful and, over 10+ timed stock events, 50%+ where Movers did
not already have it; otherwise not helping, and below either sample, not enough
data. Rules and samples are shown on the page. See `backend/app/engine/radar_proof.py`.

Beside alerted events, the read-out counts events that **led to a plan** (a
pre-trade plan names the event as its origin) and **to a trade** (that plan is
linked to a trade), shown on `/proof` and not part of the verdict. The event
detail (`GET /radar/events/{id}`, field `plans`) carries the same as
**Planned** and **Traded** marks. See [Origin](copilot-lab.md#origin).

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
`rule_version` is `radar-rules-v0` carry a small "v0 · provisional rules" tag,
and dip-rule events (`radar-dip-v0`) a "dip · discovery rule" tag.

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
rule version. They change at most every few days, never mid-session. A
candidate `radar-rules-v1` sits beside v0, unused until Isaac picks it
([Rules v1 candidate](#rules-v1-candidate-october-26-2026)).

### Calibration and replay

`backend/scripts/radar_replay.py /abs/path/radar.sqlite [--rules v1] [--session D] [--set name=value] [--quiet]`
opens a store read-only, replays each session's passes through the rules (v0
unless `--rules` names another version; using the current tracked list for
kinds, sectors and groups) and prints counts by kind/direction and each event's
first-seen time, summary and later revisions. `--set` overrides one threshold
for that run only. `backend/scripts/radar_rules_report.py` compares versions
in a Markdown report ([below](#rules-v1-candidate-october-26-2026)). The live recorder path and
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

### Why the live store had zero events (October 25, 2026)

On October 25 the feed showed two recorded sessions (October 22 and 23, 390
and 391 passes, 168 of 169 symbols quoted) and no events, and `/radar/proof`
said "No Radar events recorded yet". A fresh read-only snapshot of the VPS
file (SQLite backup API over a `mode=ro` connection) replayed through the
deployed v0 rules writes the 7 and 9 events in the table above, so the rules,
the store and the feed are fine and the thresholds were reached. The cause is
timing: the v0 rules merged at 14:15 ET on October 23 (#422) and the VPS
installed them at 14:40 ET, mid-session (`Deployed 8161f5fc` in the
autodeploy journal). Detection then ran for the last 80 minutes of October 23
and found nothing new in that stretch: all nine of the day's events had
started by 10:44 ET, a detector switched on mid-session reads only the
current pass and never backfills (by design), and a replay started at 14:40 ET
also writes 0 events. October 24–25 are a weekend. The first session recorded
with detection live from the open is Monday October 26; on sessions like the
two recorded, v0 writes 7–9 events a day.

What the two sessions actually contained, every 30-minute reading with the
2% own-move floor held (stock × pass; groups need 4 members with data and 60%
agreement):

| Reading | Oct 22 | Oct 23 |
| --- | --- | --- |
| stock vs SPY ≥ 2 points | 790 readings, 67 symbols | 642, 60 |
| ≥ 3 | 165, 25 | 178, 27 |
| ≥ 4 | 33, 10 | 55, 10 |
| **≥ 4.5 (v0)** | 14, 5 | 28, 8 |
| ≥ 5 | 6, 2 | 11, 7 |
| ≥ 6 | 2, 1 | 0 |
| group median vs SPY ≥ 1.5 points | 148 readings, 17 groups | 130, 11 |
| **≥ 2.0 (v0)** | 35, 9 | 47, 7 |
| ≥ 2.5 | 5, 3 | 23, 3 |
| ≥ 3 | 0 | 16, 3 |
| stock vs sector ≥ 4.5 without the same ≥ 4.5 vs SPY | 1 | 8 |

Largest per symbol: LAD +7.8, MRK −5.5, LCID +4.8, CIFR −4.7, DDOG −4.5 on
October 22; DECK +5.6, CRDO +5.4, ASTS +5.4, WULF −5.3, CRWD +5.1, CIFR −5.1,
NET +5.0, APLD −4.6 on October 23. No v0 threshold went unreached: the stock
and group rules fired in the replay, and the sector rule's 4.5 points were
crossed on 1 and 8 single readings but never on three consecutive passes
(hence 0 sector events). Nothing reached 8 points vs SPY or a group median of
4. Coverage: 144 of 146 stocks were usable on at least 90% of passes (AN
82–84%, HUM 92–95%); WBD never returned a quote on either day and is the one
symbol always missing. No rules change was made: v0 stays, and v1 is still
due after the October 26 close with three live sessions and Isaac's ratings.

### Rules v1 candidate (October 26, 2026)

`radar-rules-v1` (`radar_rules.V1`) is a candidate, not active: the VPS keeps
v0 until Isaac picks. It changes two numbers and nothing else, both chosen
from replays of the recorded sessions:

- **Two consecutive passes instead of three** (`persist_passes` 3 → 2). Alone,
  +15 events over the three full sessions (October 22, 23 and 26), none
  dropped, three of the added events quick fades (DECK on October 23, gone 11
  minutes later; the Quantum computing and Social and ads groups on October
  26, gone within 14 and 8 minutes); the shared events fire a median 1 minute
  earlier.
- **4.0 points vs SPY instead of 4.5** (`spy_relative_pct` 4.5 → 4.0). Alone,
  +12 events (CIFR and LCID on October 22, CRWD and CIFR on October 23, ASTS,
  SNAP, S, DDOG, ALAB, CRDO, CIFR and WULF on October 26), none dropped, no
  quick fade, three extended. Readings of 4.0+ held 3 passes in a row for 4, 7
  and 12 symbol-directions a session, against 2, 5 and 4 at 4.5.

Together, rerun after the October 26 close: 52 events against v0's 28
(12/13/27 against 7/9/12), 5 quick fades against 1, 19 extended against 13.
Of the 24 events v1 adds, 3 are quick fades and 7 extended, against 1 and 13
of v0's 28; the persistence change supplies all three quick fades. The store
held no ratings at the rerun, so the usefulness read-out is still empty.
Event ids start `rv1-`, so both versions' events can sit in one store. Considered and not chosen: a 3.5-point sector
threshold (+13, mostly the SPY story again against a flat XLK, firing a few
minutes before the SPY event; 2 quick fades), groups at 3 members (+1:
Telehealth, "mostly HIMS") and a 1.75 group median (+5, three overlapping
crypto/quantum groups on one quiet morning, 2 quick fades). With no ratings
yet, a quick fade (faded or reversed within 15 minutes) is the noise proxy.

The evidence is [the v1 report](../backend/reports/radar_rules_v1_2026-10-26.md),
written by `backend/scripts/radar_rules_report.py`: read-only and offline over
a store snapshot, it replays every session under each version (default all
of `radar_rules.VERSIONS`, plus `--try field=value` variants of v0) and lists
events per session by rule, each changed threshold's effect alone, the
30-minute readings near each threshold and how long they held, the events a
version adds or drops against v0, and, once the store has ratings, how events
rated useful and not useful survive each version (same kind, subject and
direction within 30 minutes). Rerun it after the October 26 close (from the
repository root; the snapshot uses the SQLite backup API over a `mode=ro`
connection and never writes the live file):

```bash
ssh ubuntu@100.121.251.15 "sudo python3 -c 'import sqlite3; s = sqlite3.connect(\"file:/var/lib/tradejournal/radar/radar.sqlite?mode=ro\", uri=True); d = sqlite3.connect(\"/tmp/radar-snapshot.sqlite\"); s.backup(d); d.close()' && sudo chown ubuntu /tmp/radar-snapshot.sqlite" && scp ubuntu@100.121.251.15:/tmp/radar-snapshot.sqlite /tmp/radar-snapshot.sqlite && ssh ubuntu@100.121.251.15 rm /tmp/radar-snapshot.sqlite && cd backend && .venv/bin/python scripts/radar_rules_report.py /tmp/radar-snapshot.sqlite --try sector_relative_pct=3.5 --try group_min_members=3 --try group_relative_pct=1.75 --title "Radar rules v1 candidate — October 26, 2026" --out reports/radar_rules_v1_2026-10-26.md
```

**Setting:** `RADAR_RULES_VERSION` in the VPS `backend.env` (`v0` by default,
or `v1`; an unknown name keeps v0 and logs an error) selects the version the
recorder runs, read at startup. Each event records its `rule_version` (the
store's existing column and payload field), so `/radar/proof`, which scores
only the newest version, starts over at v1 and never pools the two. Switch
between sessions, never mid-session: a version switched on mid-session never
backfills the morning.

### Outcome scoring

The October 28 evidence repair adds per-pass detector receipts and frozen
rule/universe snapshots. Only complete, verified live sessions count, including
zero-event sessions; legacy/replay and incomplete sessions stay explicitly
unverified. `--census-only` reports metadata without prices or output writes.
The first 20 qualifying sessions form one review window. This does not switch
v0 to v1, change alerts, or authorize deployment. See the
[evidence and rollback boundary](../research/radar-outcomes/spec.md#october-28-evidence-accounting-repair).

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

On the VPS, either step can be run by hand as the API's user with its settings:

```bash
sudo systemd-run --wait --pipe --collect --quiet --uid=tradejournal --gid=tradejournal \
  -p WorkingDirectory=/opt/tradejournal/current/backend -p EnvironmentFile=/etc/tradejournal/backend.env \
  /opt/tradejournal/current/backend/.venv/bin/python -m scripts.radar_outcomes \
  /var/lib/tradejournal/radar/radar.sqlite --out /var/lib/tradejournal/radar/outcomes.jsonl
sudo systemd-run --wait --pipe --collect --quiet --uid=tradejournal --gid=tradejournal \
  -p WorkingDirectory=/opt/tradejournal/current/backend -p EnvironmentFile=/etc/tradejournal/backend.env \
  -p EnvironmentFile=/etc/tradejournal/claude-plan.env -E TJ_CLAUDE_BIN=/opt/tradejournal/current/bin/claude \
  -E TJ_CLAUDE_CONFIG_DIR=/var/lib/tradejournal/claude /opt/tradejournal/current/backend/.venv/bin/python \
  scripts/radar_outcomes_review.py /var/lib/tradejournal/radar/outcomes.jsonl --since <first session> \
  --out /var/lib/tradejournal/radar/review-<date>.json
```

The review calls the research job directly, so `RESEARCH_BUDGET_USD` caps it but the queue's
`RESEARCH_DAILY_BUDGET_USD` does not count it; run it at most once a week. First run, October 24:
the scorer opened the live store read-only and scored 0 (no rule-written events yet); the review,
on that day's replayed in-sample events, ran on the plan in 56 s ($0.14 API-equivalent, 13 citations,
server checks clean).

**Weekly timer (owner-approved October 24, 2026).** `tradejournal-radar-outcomes.timer` runs both every
Friday at 18:30 New York: the scorer, then the review of that week's sessions (Saturday on), skipped
when nothing was scored. Reviews land in `/var/lib/tradejournal/radar/review-<date>.json`. The units
were installed by hand in `/etc/systemd/system/` and are not part of `deploy/systemd`, so a deploy
neither changes nor removes them. Its first run, on install, scored 0 and skipped the review.

```bash
systemctl list-timers tradejournal-radar-outcomes.timer          # next run
sudo journalctl -u tradejournal-radar-outcomes.service -n 20      # last run
sudo systemctl disable --now tradejournal-radar-outcomes.timer   # stop it
```

The installed units, verbatim:

```ini
[Unit]
Description=Weekly Radar outcome scoring, then the plan-only research review (docs/radar.md, Outcome scoring)
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=tradejournal
Group=tradejournal
WorkingDirectory=/opt/tradejournal/current/backend
EnvironmentFile=/etc/tradejournal/backend.env
EnvironmentFile=/etc/tradejournal/claude-plan.env
Environment=TJ_CLAUDE_BIN=/opt/tradejournal/current/bin/claude
Environment=TJ_CLAUDE_CONFIG_DIR=/var/lib/tradejournal/claude
Environment=HOME=/var/lib/tradejournal/claude
Environment=PYTHONUNBUFFERED=1
# Read-only on the Radar store; appends newly scored events. No model call.
ExecStart=/opt/tradejournal/current/backend/.venv/bin/python -m scripts.radar_outcomes /var/lib/tradejournal/radar/radar.sqlite --out /var/lib/tradejournal/radar/outcomes.jsonl
# The week's sessions (Saturday on), reviewed on the Claude plan only; skipped when nothing was scored.
ExecStart=/bin/sh -c 'f=/var/lib/tradejournal/radar/outcomes.jsonl; since=$$(date -d "6 days ago" +%%F); out=/var/lib/tradejournal/radar/review-$$(date +%%F).json; py=/opt/tradejournal/current/backend/.venv/bin/python; if "$$py" scripts/radar_outcomes_review.py "$$f" --since "$$since" --dry-run >/dev/null 2>&1; then "$$py" scripts/radar_outcomes_review.py "$$f" --since "$$since" --out "$$out" >/dev/null && echo "Review written to $$out"; else echo "No scored events since $$since: no review this week."; fi'
TimeoutStartSec=20min
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/tradejournal
```

```ini
[Unit]
Description=Weekly Radar outcome scoring and review, Fridays 18:30 New York

[Timer]
# After the close and the recorder's last pass; quotes are kept 20 sessions, so weekly is well inside that.
OnCalendar=Fri *-*-* 18:30:00 America/New_York
RandomizedDelaySec=120
Persistent=true
Unit=tradejournal-radar-outcomes.service

[Install]
WantedBy=timers.target
```

## Dip-buy candidates (radar-dip-v0, off by default)

A discovery rule beside the trial rules, built October 29, 2026. In the first
hour it flags a tracked stock that came into the day weak, dropped further, and
now shows the first sign of turning up on the recorded passes: a buy-the-dip
candidate. It is advice only (it flags a name, never an order), deterministic
and model-free, and it reads nothing after the pass it fires on. Its numbers
were fixed before any trial, not fitted to trades; changing one is a new
version.

Every condition holds on **2** consecutive passes (no gap over 150 seconds),
each read as of that pass, for a tracked stock (not an ETF or benchmark):

| Test | `radar_dip.V0` |
| --- | --- |
| Window | the pass started before **10:30 ET**; the session's first usable pass started before **09:33 ET** with a usable quote for the stock |
| Liquid | last at least **$5**; the day's dollar volume so far (last × cumulative volume) at least **$10M**. The tracked list is curated optionable names; optionability is not re-checked |
| Weak coming in | the open at least **1.0%** below the previous close (gap down), **or** the latest completed daily close below the mean of the last **20** completed daily closes |
| Dropped | the lowest recorded last so far at least **1.5%** below the previous close |
| Turning up | no new or equal low for **5 minutes**; the last at least **0.5%** off that low; the low was under its sampled VWAP and the last is now above it |

The sampled VWAP weights each recorded last by the cumulative volume added
since the stock's previous usable quote, so it is an estimate from minute
samples, not the exchange VWAP. Quotes follow the trial rules' freshness test.
The 20-day test uses Alpaca daily bars (`ALPACA_DATA_FEED`), only closes dated
before the session, read once a session from 09:00 ET so the first pass does not
wait, through the no-retry fast read (2.5 s a request): a rate limit or outage
fails that pass's dip result at once (receipt `failed`, retried the next
minute) and never holds up the recorder or the trial rules. A symbol with fewer than 20 closes or none in the last
5 days can only qualify on its gap.

One event per stock a session, at most **10** a session (earliest first, ties
by symbol), no revisions: kind `dip_turn`, direction `up`, ids
`rd0-<session>-dip-<symbol>-up-1`. The summary names the low and its time, the
change now and why the stock counted as weak; measures include the day change,
the low, the distance off the low and from the sampled VWAP, the gap, the prior
close against its 20-day average and SPY's day.

**Kept apart from the trial.** The trial rules' events, receipts and frozen
configuration are unchanged with the dip rule on: its result is a `dip` entry in
the same pass's detection receipt, with its own frozen configuration, and its
event ids are never in the trial's `event_ids`. `/radar/proof`, the desk's
"to rate" list and the trial's session census leave dip events out; the
outcome scorer gives the dip rule its own census and read-out
(`radar_evidence.census(..., side="dip")`). In `alert` mode a dip event is
always a single ping (never held for the digest: the first-hour window is
over by 10:00), and the one-per-stock-an-hour rule counts one rule version's
singles at a time. The app-wide [ping policy](copilot-lab.md#phone-ping-policy)
applies to both, and dip singles share Radar's single-ping budget
(`PING_BUDGET_RADAR_EVENT`, 4 a day) with the trial's strong events. Dip events do get news checks (the same 3 a pass),
appear in the feed, where they can be rated, and reach the shadow book when
that is on.

**Switching on (Isaac's call).** `RADAR_DIP_RULES` in the VPS `backend.env`:
`off` (default), `record` (events in the feed and scored; no phone) or `alert`
(also a ping per event, `Radar dip: XYZ turning up, −1.2% (low −3.1%)`, which
still needs `RADAR_ALERTS_ENABLED=true`). Read at startup: add the line and
restart `tradejournal-api.service` before the open (between sessions, never
mid-session: a session the rule did not see from the first pass is unverified).
Undo: remove the line and restart; saved events stay.

**How it is judged.** `scripts/radar_outcomes.py` scores each dip event at its
first-seen pass, signed up, against SPY at +30 min, +60 min and the close,
beside the Movers leaders and five random tracked stocks at the same pass, and
reports `radar-dip-v0` separately. Decide after **20** verified sessions of
this version, never on fewer: it earns its keep when its +60 min return against
SPY is positive more often than not and its confidence interval against the
leaders sits above zero, and when Isaac rates its events useful; otherwise drop
it or keep it as a record-only list. No tuning before that read-out.

Tests: `backend/tests/test_radar_dip.py` (triggers, no-triggers, the window,
liquidity, the cap, no future pass read, the daily closes before the session,
the recorder's separate receipt, census and scoring, alert mode).

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
coverage in `frontend/e2e/symbol-info-peers.spec.ts`. Historical event replay
and alternate lookbacks remain later slices; this is a current recorded
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

## Phone alerts (off by default)

Off unless `RADAR_ALERTS_ENABLED=true` in the VPS `backend.env`; switching it
on is Isaac's call (a new phone alert is an activation). It has been on on the
VPS since October 25, 2026 (undo copy `backend.env.before-four-pings`). With it on, the
recorder (`backend/app/engine/radar_runner.py`) hands each pass's newly
written events to `backend/app/engine/radar_alerts.py`, on the `NTFY_URL` topic
and `ALERT_APP_URL` position alerts use. Since October 29, 2026 (the day the
shared ping cap held all twelve Radar pings) most events reach the phone in two
digests a session, and only a strong one is pinged on its own:

- **Digests:** at each `RADAR_DIGEST_AT` time (default `10:00,14:00` New York)
  one ping (policy kind `radar_digest`), `Radar digest: 5 events since the
  open`, lists every event waiting since the previous digest or the session's
  start, newest first, one line each (`LAD up 5.2% vs SPY · 10:07 AM`,
  `Semis down 3.1% vs SPY (5 of 6) · 10:12 AM`), at most 12 lines then
  `+N more`; the tap opens `/radar`. A digest more than 15 minutes past its time
  is not written; one with nothing waiting is recorded `skipped`. When the
  digest is sent, held or dropped its events take the same delivery, so
  `/radar/proof` counts an event a digest reached as alerted. Events after the
  last digest stay in the feed only.
- **Single pings, strong events only** (`radar_alerts.strong`, one pure test
  the Shadow book can reuse): a stock at least `RADAR_SINGLE_MIN_RELATIVE_PCT`
  (default 7.0) against SPY (a sector event reads its SPY-relative move), or a
  group whose every member moved the same way with a median at least
  `RADAR_SINGLE_MIN_GROUP_PCT` (default 3.0) against SPY. Policy kind
  `radar_event`. What follows describes a single ping.
- **Title:** the event's own numbers, `Radar: LAD +5.3% vs SPY +0.1%` for a
  stock (its 30-minute change and the benchmark's), `Radar: Neoclouds and AI
  hosting −2.4% vs SPY (6 of 7 down)` for a group (median member vs SPY).
  **Body:** the feed's one-line summary and the time first seen
  (`… · 10:09 AM ET`).
- **Tap:** opens `/radar?event=<id>`, the saved event expanded, with its Open
  chart, Ask copilot and Plan a trade buttons and the four rating buttons; the
  page switches to the event's session when it is not the default one.
- **Actions Useful and Not useful:** open `/radar?event=<id>&rate=useful` or
  `&rate=irrelevant`; the page saves that rating once through the existing
  `POST /radar/events/{event_id}/feedback` (the tap is the rating, as the plan
  link ping works), then drops `rate` from the address so a reload cannot
  repeat it. No new server route, token or public ingress. "Not useful" is
  saved as `irrelevant`; the card is open, so "Already knew" or "Too late" is
  one more tap and the latest rating wins. ntfy shows three actions: Open app,
  Useful, Not useful. With Telegram set up ([deploy/README.md](../deploy/README.md#telegram))
  the ping goes there instead, and Useful and Not useful are reply buttons that
  save the rating in place without opening the app.
- **Only a new event pings.** Revisions (extended, faded, reversed) never do.
  Regular hours only: the recorder detects only inside the session and sends
  pending pings only on a pass.
- **Caps:** one single ping per stock or group an hour; a strong event inside
  that hour waits for the digest instead. A held single (below) does not count
  toward the hour. The old `RADAR_ALERTS_DAILY_CAP` is gone: the policy's
  budgets (4 singles and 2 digests a day by default) replace it.
- **Notification policy:** right before every send, the app's
  [phone ping policy](copilot-lab.md#phone-ping-policy) may hold it: its
  kind's budget (`PING_BUDGET_RADAR_EVENT`, `PING_BUDGET_RADAR_DIGEST`), the
  daily ceiling, or, for a single (anchored to the stock's open position, else
  the stock, or to the group), the quiet window after a ping for the same
  position. A held ping is recorded `held` with the reason and never sent
  later.
- **Outbox:** table `radar_alert` in the journal database (`RadarAlert` in
  `backend/app/models.py`, additive migration
  `backend/alembic/versions/b9e4d2a7c1f3_add_radar_alerts.py`), not the Radar
  file, which stays append-only and alert-free. One row per event (unique
  event id) and one per digest (kind `digest`, event id
  `digest-<session>-<HHMM>`); delivery `pending`, `sending`, `digest` (waiting
  for the next digest), `sent`, `expired` (not sent within 15 minutes: a late
  Radar ping is a stale read), `unknown` (a send that may have reached ntfy is
  never resent), `skipped` or `held`. `sent` means ntfy accepted
  it, not that the phone showed it. A failing ping never affects the recorded
  pass or its events.
- **Proof:** `GET /radar/proof` adds `alerted` (events with a `sent` or
  `unknown` ping, with their ratings) so alerted events can be read apart
  from events only seen in the feed; `/proof` shows the line, not part of the
  verdict.

Switching on: add `RADAR_ALERTS_ENABLED=true` (and `RADAR_DIGEST_AT` or the
`RADAR_SINGLE_MIN_*` thresholds if not the defaults) to
`/etc/tradejournal/backend.env` and restart `tradejournal-api.service`; ntfy
must already be set up (`alerts.env`). Tests:
`backend/tests/test_radar_alerts.py` (trigger, digests, strong events, delivery states),
`backend/tests/test_radar_proof.py` (alerted counts) and the tap in
`frontend/e2e/radar.spec.ts`.

## Shadow book (off by default)

Shadow book v1 is the copilot's own paper book, deciding by itself from Radar
events: Isaac's "Shadow Isaac" using the app like a trader with its own book,
on the Claude copilot instead of Dots. It is off unless
`SHADOW_BOOK_ENABLED=true` (and `RADAR_STORE` is set); switching it on is
Isaac's call, because it runs unattended plan turns in a new worker.

- **Trigger:** `backend/app/engine/shadow_book.py` runs in the API process
  (`_maybe_start_shadow_book` in `app/main.py`, a pass every 15 seconds). During
  the regular session it reads today's events from the Radar store (read only)
  and gives each new event at most one decision, one at a time, at most
  `SHADOW_BOOK_MAX_TURNS` turns a session (default 12). An event it reaches more
  than ten minutes after Radar first saw it, one in the session's last half
  hour, and one past the cap is recorded `not_decided` with the reason and no
  turn. Between sessions it is quiet. Phone pings are not built.
- **Filter:** before any of that, `eligible(event)` keeps the turns for events
  worth one, so the cap lasts the session (on October 29 the 12 turns were gone
  by 10:05 ET on 17 events). An event is eligible when it clears the same bar as
  a Radar single ping, `radar_alerts.strong` (a stock at least
  `RADAR_SINGLE_MIN_RELATIVE_PCT`, default 7%, against SPY, or a group with
  every member the same way and a median at least
  `RADAR_SINGLE_MIN_GROUP_PCT`, default 3%), or is a dip-buy candidate (kind
  `dip_turn`). Any other event is recorded once as `filtered` with a short
  reason ("Below the strong-event bar: NBIS +2.1% vs SPY") and costs no turn;
  the cap counts eligible events only. The week summary's `filtered` is that
  count, and the screen folds those rows into one line ("9 events below the
  bar, no turn spent") that opens to the list.
- **Decision:** one turn through `backend/app/ai/shadow_turn.py` on Isaac's
  Claude plan only, never an API key (`research_job.prepare("plan")`, whatever
  `RESEARCH_AUTH` says). It refuses on a hosted database unless
  `COPILOT_PLAN_REMOTE_OK=true`, as the plan chat does. Tools are an allowlist:
  the research job's read-only lab tools plus `get_option_candidates`, no
  built-in tools and no web; a PreToolUse hook denies everything else. The
  prompt carries the event, the 5-minute chart context and the shadow book's own
  open positions and last ten results, never Isaac's book. The answer is SKIP
  with a one-line reason, or one plan in the `trade_plan` shape `propose_plan`
  uses (checked by the same validator) plus a target and an `HH:MM` New York time
  stop; the thesis states the copilot's own rules. A plan that fails the checks
  is recorded `error`, never traded. Each turn is a `copilot_turn` row with
  `billing=claude_plan`.
- **Unit:** one position is one unit: one option contract for calls or puts, or
  whole shares worth $1,000 for stock (at least one). No scaling, adding or
  spreads.
- **Paper execution:** the setup scanner's pricing. The entry is the first
  quote whose bid and ask both moved after the decision (ask to buy; bid to
  sell stock short), within two minutes or the position is `unresolved`. The
  invalidation and target are touches on completed 1-minute bars of the
  underlying (a bar touching both is the invalidation); the time stop and the
  session's last regular minute are clock exits; the exit is the first fresh
  quote after the condition (bid to sell; ask to cover). Options score as the
  scanner does (per contract, commissions); stock on its shares. A position
  still open after its session is `unresolved`.
- **Record:** `shadow_book_decision` (one per Radar event, unique; claimed as
  `deciding` before the turn, so a restart records an interrupted turn as an
  error and never decides the event again) and append-only `shadow_book_event`
  (entry, exit_intent, exit, unresolved); a position is the fold of its events,
  so a restart rebuilds the book. Additive migration
  `backend/alembic/versions/9ff22204d1d2_add_shadow_book.py`. Nothing touches
  fills, trades, accounts, alerts, Radar rules or the strategy factory.
- **Screen:** the Shadow book section under the feed on `/radar` (`GET
  /radar/shadow-book?week=`): each decision with its event, the plan or the
  reason, the fill, the exit and the result (filtered events folded into one
  line), and a week line with the shadow P&L and counts beside Isaac's own week from the week review, side by side and
  not compared.

Switching on: add `SHADOW_BOOK_ENABLED=true` (and `SHADOW_BOOK_MAX_TURNS` if not
12) to `/etc/tradejournal/backend.env` and restart `tradejournal-api.service`;
the plan token and `COPILOT_PLAN_REMOTE_OK=true` are already there. Undo: remove
the line (or set it to false) and restart; the stored decisions stay and the
section keeps showing them. Tests: `backend/tests/test_shadow_book.py`.

## Social buzz (studied, not built)

An October 24 desk study looked at adding a Reddit/X/Stocktwits attention signal
and recommends against building one now; at most a free, record-only forward
test after the premarket pilot is scored. See
[the feasibility study](radar-social-buzz-feasibility.md).

## Activation boundary

The recorder is off unless both variables are set in the VPS `backend.env`
(set since October 22 with Isaac's OK). The rules have no on/off flag of their
own: wherever the recorder runs, detection runs with it and writes events to the
screen, under v0 unless `RADAR_RULES_VERSION` names v1
([Rules v1 candidate](#rules-v1-candidate-october-26-2026)); switching is Isaac's call. Phone alerts have their own `RADAR_ALERTS_ENABLED`, off by default
([Phone alerts](#phone-alerts-off-by-default)), and the premarket pilot its
own `RADAR_PREMARKET_ENABLED`, also off, and the shadow book its own
`SHADOW_BOOK_ENABLED`, also off ([Shadow book](#shadow-book-off-by-default)),
and the dip-buy rule its own `RADAR_DIP_RULES`, also off
([Dip-buy candidates](#dip-buy-candidates-radar-dip-v0-off-by-default));
turning any of them on is Isaac's call.


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
symbol is selected. Event-detail **Open chart** links carry the event's first-seen
time, original ticker, recorded session and event id through the same origin note;
**Back to Radar** reopens the original event in that session. This is navigation
continuity only: historical event replay remains deferred.

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
