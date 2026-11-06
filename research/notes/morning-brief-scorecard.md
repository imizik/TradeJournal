# Morning brief scorecard

Retrospective research of every saved morning-brief version from October 19,
2026. The initial census was read on November 3 ET: 12 versions across 11
session dates. No brief was saved for October 28. Three versions arrived after
09:30; their returns are descriptive, excluded from morning-available totals.

The copilot's own 09:00 brief (not Jo's briefing scored here) gets an automatic
line on the Desk's This week tab with the same excess and hit definitions, but a
weaker symbol match: uppercase tokens against known symbols, not this manual
audit ([the brief scorecard](../../docs/copilot-lab.md#the-brief-scorecard)).

The original November 3 scorecard had no archived 09:00 ranking. Its weekly
tables remain the record of that first run. The dated supplement below uses
historical SIP minutes and a date-effective listing universe. Catalyst coverage
still requires a separate audit of pre-09:00 source reports.

Scoring definitions:

- Every explicit ticker in visible summary, items, opportunities, urgent
  positions and limitations is manually audited, including incidental mentions,
  cautions, holdings and ETFs. Each version deduplicates ticker names. Mere
  evidence IDs do not count as mentions. This measures attention to movers,
  not directional prediction, trade suitability, or tradable profit.
- `excess_pp = 100 × [(ticker_end / ticker_open − 1) − (SPY_end / SPY_open − 1)]`.
  A hit is `abs(excess_pp) >= 3`, including negative excess. This is a difference
  in percentage points, not a ticker/SPY price ratio. SPY itself, if named,
  remains in the denominator and has zero excess.
- First hour uses the 09:30 minute's open and the 10:29 minute's close. Full
  session uses that open and the last minute's close before the exchange's
  regular close. These are endpoint returns, not maximum excursions during a
  window. Missing exact endpoints stay unknown; no fill-forward. Denominators
  count only tickers with both their own and SPY endpoints. The Named column
  includes missing endpoints, so coverage loss remains visible.
- Source is Alpaca SIP, one-minute, raw/unadjusted, using the existing access.
  Symbols are mapped as of the session date. No IEX/Tradier price fallback,
  paid upgrade, model call or trading API mutation. Session close times came
  from read-only Tradier October/November 2026 exchange calendars. New York
  time handles the November DST change. Missing calendars withhold session
  scores. Raw intraday returns do not cross overnight corporate actions.
- All saved versions are retained; later corrections never replace a prior
  version or erase late delivery. Weekly totals pool morning-available ticker
  mentions, so repeated names and multiple timely versions can count again.
  They are not independent statistical observations.
- Public output contains only per-brief aggregate counts. Individual returns
  can fingerprint private tickers, so those also stay private alongside raw
  briefs, ticker identities, account context, trade details and keyed results.
  No raw brief prose is copied into this report.

Rerun from the repository root with the existing backend Python environment:

```sh
python backend/scripts/morning_brief_scorecard.py \
  --ssh-host tradejournal-isolated --start YYYY-MM-DD --end YYYY-MM-DD \
  --private-dir /tmp/morning-brief-scorecard-private --export-only
```

Review **all visible text** in the private `briefs-START-END.jsonl` export.
Create a private `mentions.json` mapping `brief_key(brief)` (SHA256 of the whole
exported record, canonicalized with `json.dumps(..., sort_keys=True)`) to its
complete ticker list. `mentions()` supplies conservative candidates, but manual
review is required to resolve all-caps prose such as AI, CPI, EDT and GW and
catch uncited tickers. Changed briefs invalidate the audit key. Prepare private
`sessions.json` as `{ "YYYY-MM-DD": "16:00" }` from the existing read-only
exchange calendar, using `13:00` on early closes and omitting closed days.

```sh
python backend/scripts/morning_brief_scorecard.py \
  --briefs /tmp/morning-brief-scorecard-private/briefs-START-END.jsonl \
  --start YYYY-MM-DD --end YYYY-MM-DD \
  --mentions /tmp/morning-brief-scorecard-private/mentions.json \
  --sessions /tmp/morning-brief-scorecard-private/sessions.json \
  --private-dir /tmp/morning-brief-scorecard-private \
  --sip-cache /existing/checkout/backend/data/alpaca_cache/stocks/1Min/sip \
  --credentials /existing/checkout/backend/.env \
  --output research/notes/morning-brief-scorecard.md
```

Without `--credentials`, only existing caches are read. Supplying it enables
bounded historical market-data GETs with only the existing Alpaca keys; the app
is never imported and no database connection string is loaded. The SSH mode
runs a fixed SELECT in `BEGIN READ ONLY` without starting the app. It does not
write any VPS file. Private bars and results are cached locally outside git.
Raw inputs have a private SHA256 receipt. Provider errors fail the run before
any report append; they cannot become silently frozen missing-data scores.

### 09:00 ET market archive

The private backend job prepares the day's roster from 08:45 ET, confirms the
session and preceding trading date against Alpaca's exchange calendar, and
preloads prior closes, split factors and minutes through 08:44. At 09:00 it
starts one batched SIP snapshot pass alongside the 08:45–08:59 minute reads.
Both passes must finish before 09:01. Enablement requires the API process running with
`PREMARKET_ARCHIVE_ENABLED=true` (default off), existing Polygon reference
access, Alpaca paper-calendar access and **real-time SIP snapshot and bar
entitlement**. A denied or missed capture leaves the day open for explicitly
labelled reconstruction. The isolated assistant trial does not run this job.

The universe is the paginated US stocks market's CS and ETF types marked
active **on that session date** by Polygon/Massive. It includes listings since
delisted and excludes the provider's separate OTC market. These are
effective-dated records, which the provider can correct retrospectively.
[Point-in-time listing reference](https://massive.com/docs/rest/stocks/tickers/all-tickers)

Both modes use raw SIP minutes from 04:00 through 08:59 ET inclusive. Price is
the last completed minute close. Before filtering, the live job cross-checks
every pre-market snapshot minute against the last historical minute by time,
close, volume and VWAP. Every listing meeting the dollar floor needs a matching
snapshot. A snapshot-only minute or conflicting input withholds the whole day.
Both modes use the preceding exchange session’s raw SIP daily close, which is
converted to current share units for splits effective that morning. A listing
without a previous-session close is excluded and counted. Dollar volume is
the sum of each minute's VWAP times its reported share volume. Price **≥ $2**
and pre-market dollar volume **≥ $1 million** are inclusive. The archive saves
up to 25 positive and 25 negative percentage changes, descending and ascending
respectively, with alphabetical ticker ties. A flat name belongs to neither
side. [SIP snapshots](https://docs.alpaca.markets/us/reference/stocksnapshots-1)
and [historical bars](https://docs.alpaca.markets/us/reference/stockbars).

The API reads `GET /premarket/archive/{date}` from the ignored local
`backend/data/premarket_archive` directory. Each complete daily JSON file is
published once, including across competing live/backfill runs. An absent date
returns 404. The endpoint never collects data. Live receipts retain their
actual snapshot and publication timestamps. Backfills always use
`reconstructed-sip`. No archived day or per-symbol score belongs in git.

From the backend directory, use the existing market-data credentials and a
private destination outside the repository:

```sh
python -m scripts.premarket_archive --start 2026-10-19 --end 2026-11-03 \
  --credentials /existing/checkout/backend/.env \
  --baselines /tmp/morning-brief-scorecard-private/r6-baselines.json
```

Add `--baselines /tmp/morning-brief-scorecard-private/r6-baselines.json` to
the scorecard command above. Add `--append-baselines` for the supplementary
columns on previously published weeks. The export is keyed by session date.
Each entry contains `feed: "sip"`, `whole_market: true`, `as_of` at exactly
09:00 ET, `source`, `ranking_basis: "pct_vs_prior_regular_close"`, and ten
distinct ticker strings on each side in `gainers` and `losers`. Both sides
use the same absolute excess-return score as the briefs. Gapper coverage
counts how many of those 20 names appeared in that saved brief version.

Weeks are append-only snapshots. Repeating identical evidence is a no-op;
changed evidence for the same week/cutoff is refused. The current partial week
can receive a later cutoff section without changing earlier sections. Do not
pool overlapping snapshots or silently revise earlier weeks. Each Friday run
uses that Monday through Friday and opens a report-only PR for the owner to
merge; it never merges, deploys, changes the brief, Jo, prompts, publisher,
rules, thresholds, CI or agent files. No production writes or data purchases.

## Week of 2026-10-19 (through 2026-10-23)

6 saved versions; 4 available before 09:30. Late versions are descriptive only.
Morning-available ticker mentions: ≥3pp first hour 6/29; session 9/30. Repeated mentions across days count separately.

| Day / version | Saved ET | Morning eligible | Named | ≥3pp first hour | ≥3pp session | Baseline hour / session | Gappers mentioned / catalyst assessment |
|---|---|---|---:|---|---|---|---|
| 2026-10-19 / 1 | 13:45:04 | late | 14 | 3/14 | 4/14 | unavailable | unavailable |
| 2026-10-19 / 2 | 15:31:41 | late | 2 | 1/2 | 1/2 | unavailable | unavailable |
| 2026-10-20 / 1 | 09:26:56 | yes | 2 | 2/2 | 2/2 | unavailable | unavailable |
| 2026-10-21 / 1 | 08:56:52 | yes | 4 | 1/4 | 2/4 | unavailable | unavailable |
| 2026-10-22 / 1 | 09:05:11 | yes | 11 | 2/11 | 2/11 | unavailable | unavailable |
| 2026-10-23 / 1 | 09:06:52 | yes | 13 | 1/12 | 3/13 | unavailable | unavailable |

No saved brief on confirmed sessions: none.

- Gap: Archived whole-market 09:00 SIP top-10 gainers AND top-10 losers unavailable: baseline, gapper coverage and catalyst coverage unscored.

## Week of 2026-10-26 (through 2026-10-30)

4 saved versions; 4 available before 09:30. Late versions are descriptive only.
Morning-available ticker mentions: ≥3pp first hour 5/35; session 8/37. Repeated mentions across days count separately.

| Day / version | Saved ET | Morning eligible | Named | ≥3pp first hour | ≥3pp session | Baseline hour / session | Gappers mentioned / catalyst assessment |
|---|---|---|---:|---|---|---|---|
| 2026-10-26 / 1 | 09:06:19 | yes | 10 | 1/8 | 2/9 | unavailable | unavailable |
| 2026-10-27 / 1 | 09:00:52 | yes | 11 | 3/10 | 5/10 | unavailable | unavailable |
| 2026-10-29 / 1 | 09:06:55 | yes | 14 | 1/13 | 1/14 | unavailable | unavailable |
| 2026-10-30 / 1 | 09:01:50 | yes | 4 | 0/4 | 0/4 | unavailable | unavailable |

No saved brief on confirmed sessions: 2026-10-28.

- Gap: Archived whole-market 09:00 SIP top-10 gainers AND top-10 losers unavailable: baseline, gapper coverage and catalyst coverage unscored.

## Week of 2026-11-02 (through 2026-11-03)

2 saved versions; 1 available before 09:30. Late versions are descriptive only.
Morning-available ticker mentions: ≥3pp first hour 3/4; session 4/4. Repeated mentions across days count separately.

| Day / version | Saved ET | Morning eligible | Named | ≥3pp first hour | ≥3pp session | Baseline hour / session | Gappers mentioned / catalyst assessment |
|---|---|---|---:|---|---|---|---|
| 2026-11-02 / 1 | 09:54:29 | late | 5 | 0/5 | 5/5 | unavailable | unavailable |
| 2026-11-03 / 1 | 09:03:23 | yes | 4 | 3/4 | 4/4 | unavailable | unavailable |

No saved brief on confirmed sessions: none.

- Gap: Archived whole-market 09:00 SIP top-10 gainers AND top-10 losers unavailable: baseline, gapper coverage and catalyst coverage unscored.

## Baseline supplement 2026-10-19 through 2026-11-03

Morning-available versions with a baseline, pooled on the same dates and versions.
Each cell counts hits over tickers with both endpoints. Repeated mentions count again.

| Week of | Timely versions compared | Brief first hour | Baseline first hour | Brief session | Baseline session |
|---|---:|---:|---:|---:|---:|
| 2026-10-19 | 4 | 6/29 | 46/78 | 9/30 | 58/80 |
| 2026-10-26 | 4 | 5/35 | 49/77 | 8/37 | 55/78 |
| 2026-11-02 | 1 | 3/4 | 12/20 | 4/4 | 17/20 |

| Day / version | Source | Baseline ≥3pp first hour | Baseline ≥3pp session | Gappers mentioned |
|---|---|---:|---:|---:|
| 2026-10-19 / 1 | reconstructed-sip | 14/18 | 16/20 | 0/20 |
| 2026-10-19 / 2 | reconstructed-sip | 14/18 | 16/20 | 0/20 |
| 2026-10-20 / 1 | reconstructed-sip | 14/20 | 16/20 | 0/20 |
| 2026-10-21 / 1 | reconstructed-sip | 7/20 | 11/20 | 0/20 |
| 2026-10-22 / 1 | reconstructed-sip | 14/18 | 16/20 | 0/20 |
| 2026-10-23 / 1 | reconstructed-sip | 11/20 | 15/20 | 0/20 |
| 2026-10-26 / 1 | reconstructed-sip | 12/19 | 16/19 | 0/20 |
| 2026-10-27 / 1 | reconstructed-sip | 11/20 | 10/19 | 0/20 |
| 2026-10-29 / 1 | reconstructed-sip | 13/19 | 14/20 | 0/20 |
| 2026-10-30 / 1 | reconstructed-sip | 13/19 | 15/20 | 0/20 |
| 2026-11-02 / 1 | reconstructed-sip | 10/18 | 16/20 | 0/20 |
| 2026-11-03 / 1 | reconstructed-sip | 12/20 | 17/20 | 0/20 |
