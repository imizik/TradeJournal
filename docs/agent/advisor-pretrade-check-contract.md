# Jo pre-trade check — Dots step 4, slice 1

Selected by Isaac on October 11, 2026 (evening ET) as the first real-data
advisor slice: the moment he would use most during a session. **Built and
activated on the VPS October 12, 2026**; current per-step status is in
[Next steps](#next-steps). It reconciles Dots step 4 on the
[delivery board](dots-integration.md#functionality-sequence) with the
[pre-trade advisor roadmap](../advisor-roadmap.md) (AV0 rules, AV2 records and
AV5 phone access, narrowed to one call). Later slices (after-close review,
pre-open plan, while holding) reuse this gateway and are not authorized here.

## What Isaac does

Mid-session, from ChatGPT on phone or desktop: "Thinking SPY 0DTE calls here,
stop 578.20." Jo calls one tool and answers within seconds with **Go / Wait /
Pass** (or insufficient data), the reasons, what would change it, and how his
own similar past trades went. Later he reopens every check in TradeJournal.

Jo advises only. No tool places, sizes, amends or arms an order, and nothing
writes fills, trades, captures, P&L or the paper ledger.

## Approved data

Isaac approved on October 11, 2026 that Jo (ChatGPT/OpenAI) may receive, for
this slice only:

- **Live market data** for the ticker asked about: the existing scalp packet
  (price, VWAP, opening range, day structure, relative volume, scores, trigger,
  invalidation), with source and observation timestamps.
- **Aggregates of his own closed trades** forming the similar-trades card:
  counts, distinct days/weeks, win rate, realized P&L and return summaries,
  MFE/MAE and giveback, by cohort. No account numbers, order IDs or raw fill
  rows; Webull stays excluded while dormant.

Open positions and trade notes/plans are **not** sent in this slice (they
belong to the while-holding and later slices and need their own approval).

## The one tool

`pre_trade_check(ticker, side, instrument, horizon, entry?, stop?, option_type?,
expiration?, strike?, free_text?)` returns the
[answer contract](../advisor-roadmap.md#the-answer-contract) in one round trip:
`verdict`, `wait_for` (with `wait`), up to three sourced `reasons`,
`would_change`, `risk_check`, `history`, `live`, `caveats`, plus the saved
check's ID and receipt. `horizon=swing` returns `insufficient_data`.

- **Rules verdict only** from the server, using the roadmap's
  [verdict mapping](../advisor-roadmap.md#rules-verdict-mapping). Stale or
  missing live data, a closed/premarket/after-hours session or a missing setup
  can never yield `go`. History and risk may only downgrade.
- **Similar trades** follow the roadmap's cohort, honest-count, display
  threshold and as-of rules: only trades closed before the check's receipt
  time, converting UTC receipt to New York wall time before comparing.
- **Jo's narration** is optional on top. A second tool,
  `attach_model_verdict(check_id, verdict, summary)`, saves it once per check;
  identical retries return the original, different content conflicts.
- No `free_text` instruction changes the computation; it is stored as data.

## Where it runs

The private production API stays private (hard constraint). A new isolated
**check service** on the VPS, following the advisor/journal isolation pattern:

- Its own system UID, service units and Unix socket behind a new OAuth
  resource (`/check/mcp`) with its own scopes (`check:run`, `check:read`,
  `check:note`). Existing journal and advisor resources, scopes and tokens are
  not reused. Issuer keys are maintained the way
  [connection upkeep](advisor-connection-upkeep-contract.md) does.
- **Live data:** the service calls the market-data provider directly using the
  existing scalp packet code with a dedicated read-only provider credential,
  delivered as a systemd credential. A UID-only network policy permits only
  DNS and public HTTPS (the provider has no fixed addresses); loopback,
  private and host addresses stay denied, with a systemd `IPAddressDeny`
  backstop if the table is ever flushed.
- **History:** a separate finite publisher (like the journal export) writes a
  per-trade feature row file after fill import/rebuild, through a read-only
  database role on a narrow view. The check service never holds a database
  credential. Rows carry close time, cohort dimensions and outcome measures
  only; a stale or missing feature file is a caveat, never fabricated history.
- **Records:** each check is an immutable row in the service's own SQLite ledger
  (the roadmap's [record fields](../advisor-roadmap.md#records), including stage
  timings and a live-context hash). The owner reads the ledger read-only in
  `/advisor-review` through the existing private owner frontend.

Rejected: letting the gateway call the private API over loopback (widens the
unauthenticated API's blast radius) and reusing the invented-fixture advisor
install (its ledger, binding and grants are fixture-only).

## Speed

Server-side p50 under 1.5 s and p95 under 4 s for the deterministic answer:
concurrent provider calls with a short cache, history from feature rows. Each
record stores its stage timings. Provider latency is observed, not assumed.

## Out of scope

Orders or sizing; open positions; notes/plans; push alerts or schedules;
swing scoring; the in-app Check button (AV3); grading views (AV4); linking
checks to captures; repeatable fixture questions; any change to the journal
coach export or the fixture advisor.

## Build order

1. **Engine (local, no network exposure):** per-trade feature rows, cohort card
   with the as-of cut, verdict mapper and immutable check record, against
   fixtures and the existing scalp packet. Tests cover every mapping row,
   stale data, closed session, thin cohorts and the UTC/New York cut.
2. **Check service and installer:** isolated units, ledger, OAuth resource and
   scopes, provider credential and network policy, key upkeep, feature-row
   publisher; disposable Ubuntu proof with generated tokens and recorded
   provider fixtures.
3. **Owner view:** list and reopen checks in `/advisor-review`, desktop and
   390px.
4. **Activation** (separate approval): Auth0 API/scopes, provider credential,
   database role/view, restore point and rollback files.

## Build status

Step 2 was built October 11, 2026 and activated with step 3 on October 12 (below):

- Service: [cloud_mcp_check.py](../../backend/cloud_mcp_check.py) with
  [identity/config](../../backend/cloud_mcp_check_common.py) and the
  [immutable ledger](../../backend/cloud_mcp_check_ledger.py). Scopes:
  `check:read` on every call, plus `check:run` for `pre_trade_check` and
  `check:note` for `attach_model_verdict`. `pre_trade_check` also takes an
  optional `operation_id`; reusing it with the same idea returns the saved
  check. Jo's view omits the hashed fill keys; the ledger keeps them.
- Live data: the scalp packet's four provider reads now run concurrently, and
  the service swaps the engine's patient getter for one bounded attempt
  (3 s timeout, 10 s shared cache). A provider failure is a caveat and
  `insufficient_data`, never a guessed price.
- History: [pretrade_feature_publish.py](../../backend/pretrade_feature_publish.py)
  selects the narrow view from [check_scope.py](../../deploy/check_scope.py)
  (raw fill keys hashed in Postgres) and writes a content-addressed file via
  [pretrade_features.py](../../backend/pretrade_features.py). Missing →
  `history.available=false` plus a caveat; older than 36 h → used with a caveat.
- Install: [check_control.py](../../deploy/check_control.py) `stage`/`install`
  (exact manifest approval, `--dns`, `--host-ip`), `check`, `stop`, `remove`,
  and `upgrade` (all units stopped; replaces runtime and individually hash-approved units,
  keeps backups; SQL additions require their own approval);
  units in [cloud-mcp-check](../../deploy/cloud-mcp-check/); UID-only policy in
  [check_network.py](../../deploy/check_network.py). Install writes no
  credential and starts, enables and loads nothing. Activation (step 4) adds
  `alpaca-key-id`, `alpaca-secret-key`, `tradier-api-key` and `features-database-url` under
  `/etc/tradejournal-check/` (root 0600), creates role `tj_check_features`
  and applies `feature-view.sql`, runs the key unit before the service, and
  publishes the Caddy route.
- Proof: `backend/tests/test_cloud_mcp_check.py` (generated tokens, recorded
  Alpaca responses for SPY/QQQ on October 9, 2026),
  `backend/tests/test_check_deployment.py`, and the disposable Ubuntu
  [smoke](../../deploy/cloud-mcp-check/smoke.py) in the deployment workflow.
  Speed against the live provider is not yet observed.

Step 3 (owner view) was built October 11, 2026:

- Reader: [cloud_check_owner.py](../../backend/cloud_check_owner.py) serves
  `GET /owner/checks` (newest 50: idea, rules verdict, Jo's verdict, timing)
  and `GET /owner/checks/{check_id}` (the saved answer after its record hash
  is verified; fill keys become a count, the raw provider packet stays behind
  its hash). It runs as `tj-check` with no network, opens the ledger
  `mode=ro` with `query_only`, and admits only the kernel-identified
  `tj-advisor-web-owner` peer (the trial's private owner frontend) on
  `/run/tradejournal-check-owner/owner.sock`. `install` now also writes the
  two owner units and a disabled config in its own bound directory, and
  refuses when that frontend identity is missing.
- Page: `/advisor-review` lists and reopens checks through
  `/api/check-owner/checks[/{id}]`, behind the same owner session as the
  advisor review. It stays dormant until `TJ_CHECK_OWNER_ENABLED=true`,
  `TJ_CHECK_OWNER_SOCKET` and `TJ_CHECK_OWNER_SOCKET_UID=0` are set for the
  owner frontend, which runs the v2 trial's runtime: activation upgrades that
  runtime first, then enables the owner reader config and starts the owner socket.
- Proof: `backend/tests/test_cloud_check_owner.py`, the check BFF cases in
  `frontend/scripts/advisor-owner.test.js`, and an owner read as the real
  frontend UID (another UID refused) in the disposable Ubuntu smoke.

Activated and first used **October 12, 2026** (10:16 ET: SPY intraday
pass in 0.75 s with 33 similar trades; NBIS swing insufficient_data). Auth0
API token lifetime must be 300 s to match the verifier.

After-close review (advisor step 4, outcome linking): `review_checks(day?)`
(`check:read`) lists one New York day's checks with the rules verdict, Jo's
saved verdict and an outcome from closed trades
([`check_outcome`](../../backend/app/engine/pretrade_check.py),
`pretrade-link-v1`). The window is fixed by the check itself: receipt to the
`wait_for` expiry, otherwise to that session's close. `traded` means a trade on
the same underlying and side opened inside it, reported as count, wins and
total P&L only (on its own not proof the check was followed; grading counts a
go that was traded as followed); `no_closed_trade` never claims no position, since open trades
appear only after they close; `pending` until the window has passed and the
history file was refreshed after it; swing checks are `not_linked`.

While holding and notes (slice 2, owner decision October 12, 2026: Jo may see
all of Isaac's trade data; still never credentials, account numbers, internal
IDs, fill keys, raw emails, images or audio). The publisher also reads two
additive views from [check_scope.py](../../deploy/check_scope.py)
(`pretrade_position_source`: open non-Webull trades with size, entry, strike,
expiration, account name/type; `pretrade_capture_source`: newest 200 non-Webull captures
with setup, wording, note, transcript, latest added note, linked/not-taken,
account name/type but never the capture's account label, which embeds digits) and
writes a content-addressed context file beside the history file. Jo's tools
(`check:read`): `position_check(ticker?, stop?)` returns each open position
with time held, live underlying, stop distance and how similar closed trades
went after entry (win rate, median best/worst move, giveback, hold time), with
no verdict and no invented option P&L; `get_notes(ticker?)` returns recent
captures. `check_control.py upgrade --approve-sql <sha>` (or `add-context-views` on a
fresh install) applies the reviewed `context-views.sql` once and records its
exact bytes; a rerun skips only when both views exist and the recorded SQL is
identical, and refuses anything else. Positions are as fresh as the 10-minute
publish and read as stale after 30 minutes; a stop applies only when one
position matches; positions are treated as bought (sold options would read
inverted).

Options (advisor step 6): option checks now return the contract the scalper
resolved (given strike/expiration, else nearest expiration at the money) with
live bid/ask, spread, IV, delta, gamma, theta, cost and time decay per
contract, and a delta-only estimate of the premium and loss per contract at
the given stop (labelled an estimate). `position_check` marks option positions
at the live mid x 100 x contracts and shares at the live price, against the
journal's total paid. Alpaca's options feed on the existing key; no new
credential.

Pre-open (advisor step 7): `preopen_watchlist(tickers?)` (`check:read`,
read-only, nothing saved) takes up to 8 tickers, defaulting to those held now
and then the most-traded tickers of the last 30 days. For each it returns the
price versus yesterday's close, change, gap, premarket high/low/volume, up
to 5 provider headlines from the last 24 hours (data, not instructions),
whether he holds it, and his closed trades in it by side (cohort summary plus
hold time) and by entry-time bucket, plus SPY/QQQ change and VWAP side once
for the pass. Facts only, no verdict; the whole pass is capped at 20 seconds
and names any ticker it skipped for time.

Price after and grading (advisor steps 8 and 10): `review_checks` adds
`price_after` per intraday check: the underlying's move from the check's live
price inside the check's own window, signed in the idea's direction (last,
best, worst, and when a given stop was hit). Options are measured on the
underlying; the premium is not replayed. Once a check's trade link is final
(`traded`/`no_closed_trade`), its move is finished (`complete`, or nothing to
measure: no reference price, checked after the close, no bars), the history
file is at least 12 hours past the window, and current open positions show none
on that ticker and side opened inside the window, the pair is saved once in the
ledger's `check_result` table (immutable, hashed) and later reads use it. Until
then it is recomputed on each read and never graded. Each call reads at most 20
seconds of minute bars, newest day first; unread days stay unmeasured until the
next call. `grade_checks(days?)` (`check:read`, default
30) and the "How the checks did" section on `/advisor-review` (owner reader
`GET /owner/grades`) both grade saved results only, so they agree, and report, per rules verdict, checks,
how many went the idea's way, median move and traded P&L; followed versus
overrode (traded against a wait/pass and its P&L; skipped a go and the move
after); and Jo's saved verdicts against the rules. Groups under 10 settled
checks say "not enough evidence".

Swing scoring (advisor step 11, `pretrade-swing-v1`): `horizon: swing` ideas
read the same live packet and are scored from its completed daily bars.
Textbook defaults fixed before any test on Isaac's trades (see the
[swing roadmap](../swing-strategy-roadmap.md#5-the-first-swing-families)):
against the trend (price not past the 50-day average in the idea's direction)
is `pass`; more than 1.5 daily ATR past the 20-day EMA or RSI over 70 (under 30
for shorts) is `wait` for a pullback; a 9/20-day EMA cross against the idea is
`wait` for it to cross back; otherwise `go`. Waits expire at the next weekday's
close. A stop is measured in daily ATRs and a wrong-side stop is `pass`.
History uses his closed trades on that ticker and side held overnight; a weak
record (8+ trades, under 40% won, negative average) turns `go` into `wait`.
The answer carries the daily inputs and caveats that the rules are untested
and that no earnings date was checked. Swing checks are not yet linked to
outcomes or graded.

Macro calendar (advisor step 9, first part): every check and the pre-open pass
carry `macro`, the scheduled FOMC, CPI and jobs releases today and next trading
day from the Daily Review's official calendar
([macro_calendar.json](../../backend/app/data/macro_calendar.json), NYSE
holidays skipped). A release still to come today is a caveat ("expect a
volatility spike"); one already out today is noted; for swing ideas, next
trading day's releases are flagged as inside the hold. A day the calendar does
not cover is a caveat, never "no events". The verdict itself is unchanged.

Earnings and VIX (advisor step 9, second part): the private backend's 15-minute
job writes the next earnings date per tracked symbol and a live VIX quote to
`market_context_item` (Tradier, [market_context.py](../../backend/app/engine/market_context.py)).
The publisher reads it through the additive view `pretrade_market_source`
([check_scope.py](../../deploy/check_scope.py), no row IDs, applied with its own
`--approve-sql` like the context views) into a content-addressed
market file. Checks carry `market` (earnings date/status/days away and VIX
with their read times); `position_check` and each pre-open ticker carry it too,
and the pre-open pass carries `vix`. Caveats: a report today or next day (gap
and IV-crush risk), inside a swing hold (14 days), before an option's
expiration, VIX 25 or higher, an earnings read older than 48 hours, VIX older
than an hour (by the quote's own trade time when known). A ticker outside the
tracked calendar (only held, recently traded and watched names are read), an
unreadable row, a snapshot older than an hour or none at all is "not checked",
never "no earnings"; funds and indices simply have none.

## Next steps

The advisor plan agreed with Isaac on October 12, 2026, in order. The end goal:
Jo is a trading partner used during sessions. Before an entry, Jo gives a fast
Go/Wait/Pass from live data and Isaac's own record. Every check is saved before
the outcome is known, so later it can be graded: when Jo was right, when Isaac
was, and what overriding cost.

| # | Step | Done when | Status |
|---|---|---|---|
| 1 | Stay signed in: Auth0 Allow Offline Access on the check API, and the server advertises `offline_access` so ChatGPT requests a refresh token | A check more than an hour after connecting works without reconnecting | Done: plugin v4 passed the 6- and 60-minute checks Oct 13 ([shadow S1 evidence](shadow-s1-contract.md#activation-evidence--october-13-2026)) |
| 2 | Jo saves its own verdict on every check (`next_step`) | At least 9 of 10 saved checks carry Jo's verdict and summary | Live; confirm on real days |
| 3 | Checks visible on `/advisor-review` | Every saved check reopens identical to the server copy, including after a restart | Live |
| 4 | Link each check to what happened (`review_checks`) | One day's links agree with a hand check of that day's fills | Live |
| 5 | While-holding check (`position_check`) | Stop distance, live mark and similar-trade behaviour match the trade page | Live |
| 6 | Options-aware checks | Quote, IV, greeks, cost, decay and the at-stop estimate appear with timestamps on a live check | Live |
| 7 | Pre-open watchlist pass (`preopen_watchlist`) | One real morning's pass matches the journal and the provider | Live (deployed Oct 12) |
| 8 | **Price after the check** in `review_checks`: for every check (above all skip/wait), the underlying's move from the check price to the window end, with the best and worst move in between | A skipped idea shows what it would have done; numbers match recorded bars | Built (`price_after`; final results saved once) |
| 9 | **Macro and external context**: economic calendar (CPI, FOMC, jobs), VIX/rates, earnings dates, sector moves. Headlines are passed to Jo in `pre_trade_check` too, not only used for the event-risk flag | Each item names its source and timestamp; a missing feed is a caveat, never a guess; tested on recorded data | Built: calendar live; earnings + VIX via `market_context_item` → `pretrade_market_source` → market file. Sector moves not covered |
| 10 | Grading view: results by verdict, followed versus overrode | Counts reconcile with saved checks and trades; small groups say "not enough evidence" | Built (`grade_checks`, `/advisor-review`); needs weeks of checks to mean much |
| 11 | Swing scoring | Swing ideas get a real verdict, tested on recorded data | Built (`pretrade-swing-v1`); outcome linking for swings still open |

Shadow Isaac ([design](shadow-trader-design.md)) follows the advisor.

## Manual advice recording and candle evidence (October 13, 2026)

The owner approved a prompt-first improvement after the October 13 session:
specific actionable advice in Jo's conversation should use the existing
`pre_trade_check` → `attach_model_verdict` sequence before the final verdict.
The returned check ID identifies the saved record. Broad market discussion
and pre-open watchlists do not become invented trade ideas. Missing required
idea details need clarification; missing data is not a deliberate bearish
`pass`. Failed saves must be disclosed as unrecorded advice.

The short saved narrative should include the evidence/candle cutoff, trigger,
invalidation, expiry or recheck condition and material gaps when known. These
are narrative contents, not new structured fields. A materially changed idea
or fresh reassessment uses a new `operation_id`; only an uncertain retry of
the same request reuses its ID. Do not backfill old conversations as decisions
made before the outcome. Measure actual check/verdict completeness on future
sessions; acknowledging instructions is not evidence of adherence.

### Full-market requirement — October 20 code change

Jo's live checks use Tradier full-market quotes, completed daily history and
completed intraday candles through the bounded `tradier_stock_data.py` reader.
Pre-trade, position and preopen analysis share this source; RVOL uses Tradier
history and never the old Alpaca minute cache. Post-check price measurements
also use Tradier. Daily OHLC is provider-reported, without a guarantee of dividend
adjustment. Saved checks and immutable retries retain their original evidence.

The manual candle tool first reads fresh scanner files, then directly refreshes
Tradier if those files are absent, invalid or stale. Same-key requests coalesce;
short caches, a 30-request/minute per-process budget, five-second error backoff
and a 60-second 429 cooldown bound provider load. Independent symbol failures do
not discard healthy symbols. Provider failure or genuinely stale data still
returns explicit missing evidence; neither IEX nor delayed SIP is a live backup.
This code change does not establish live acceptance or activate a service.

Rollout requires a separately authorized isolated Check upgrade as well as the
app release. Provision `/etc/tradejournal-check/tradier-api-key` as root-owned
0600 from the existing production Tradier credential using a private transfer
that never prints the token or places it in command arguments. Do not grant the
Check UID access to `backend.env`. Stage the reviewed bundle, stop all Check
units, and pass its exact manifest hash plus `--approve-unit <sha256>` for each
changed service unit to `check_control.py upgrade`. The main unit receives the
key through `LoadCredential`; key-refresh and feature units cannot read it.
A failed upgrade restores the previous runtime and unit files; nothing starts
automatically. Verify credentials, restart only with rollout authorization, and
check actual pre-trade/candle responses and the next scheduled Market Watch
publication. Keep old runtime/unit backups for rollback. The existing publisher
already receives the production Tradier key; it now publishes `mw-tradier-v2`.

The isolated provider also refuses stock requests without explicit `feed=sip`.
This is scoped to Jo's Check process; unrelated journal/research adapters are
unchanged. Deployment and updating external Jo task instructions are not proven
by the PR or local fixture tests.

Read-only diagnosis on October 13: an explicit IEX NVDA one-minute request
from 10:00 through 10:13 Eastern returned 14 bars including the 10:13 bar;
only bars through 10:12 would have been complete at a 10:13 cutoff. A second
request with the same start, ascending sort, limit 20 and no end returned the
first 20 bars through 10:19. Both succeeded after hours. This confirms boundary
and truncation handling, **not** the cause or resolution of the earlier live
timeouts. Intraday reliability still needs a natural market-hours observation.
Alpaca documents an [inclusive end and a total response limit](https://docs.alpaca.markets/us/reference/stockbars);
the provider's default end also depends on feed access.

These instructions apply to manual advice, not pre-commit shadow evidence.
The existing Gmail task retains `shadow_setup` → `shadow_decide` before its
co-pilot calls, both independence labels and its source/freshness guards.
No extra candle reads may be inserted before that shadow commit. Scanner
rules, universe and task schedule are unchanged. Natural SH-6 acceptance
remains governed by the [S1 contract](shadow-s1-contract.md#acceptance).

## Acceptance

During a regular session, Isaac asks Jo for at least three real checks from his
phone. Each answer arrives within the speed budget, cites live timestamps and a
history card consistent with `get_fill_contexts`/`get_trade_path_metrics` for
the same filters, and reopens unchanged in TradeJournal after reload and service
restart. A stale-data or out-of-session check returns `insufficient_data`.
Isaac records whether the answer was useful. Built, activated, observed and
accepted are recorded separately with dates; none implies a trading edge.
