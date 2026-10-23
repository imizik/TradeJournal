# Jo's market watch — design (proposed October 14, 2026)

**Status: MW-1 implemented; owner-authorized activation and instructed Jo tool proof completed October 14, 2026. Eligible intraday scoring and later session trials remain unproven.** Written at Isaac's request
after the October 14 CPI session. It extends the
[shadow trader design](shadow-trader-design.md) and reuses rules already
written in the [agentic trading roadmap](../agentic-trading-roadmap.md)
(macro and catalysts, thesis versions, morning pipeline, anti-hindsight).
[Setup scanner S1](setup-scanner-contract.md),
its ten-session acceptance and [shadow S1](shadow-s1-contract.md) keep their
rules, records and gates. Codex owns the shadow and check-service backend;
selecting any slice below goes through the
[Dots delivery board](dots-integration.md#current-delivery-board).

## Full-market requirement — October 20 code change

The default publisher now builds `mw-tradier-v2` from Tradier full-market
SPY/QQQ minute candles and daily history. Jo Check serves and accepts this
protocol, restoring live reads without IEX. VWAP, opening range and completed
five-minute bars retain strict coverage requirements; unavailable or stale
sources remain explicit gaps. Daily prices are provider-reported, with no
promise of dividend adjustment. Stock-watch ATR history uses Tradier too.

The frozen `mw-v1` IEX protocol and historical records remain reproducible.
New reads start a separate per-protocol parent chain; the daily notification
budget still spans both protocols. Owner exports default to the latest served
protocol, with `--protocol mw-v1` available for historical exports. Evaluation
keeps source bases separate and requires a new session revision when changing
protocols. The older implementation/acceptance notes below describe MW-1 unless
explicitly marked otherwise. Existing committed retries remain recoverable.

These changes have fixture proof only, not deployment or live acceptance.
The app publisher release and isolated Check credential/unit upgrade must both
complete; see the [Check rollout](advisor-pretrade-check-contract.md#full-market-requirement--october-20-code-change).

## What Isaac wants

Jo should pay attention to the market on its own, form a view of the day from
macro events, news and the tape, and tell Isaac without being asked when
something meaningful develops — a directional day building, a view that
failed, or a strong opportunity. Not an alert every 20 minutes, and not
invented trades. Isaac reports no market-level alert on October 14 (CPI morning, persistent
selling, repeated failed bounces). MW-0 below separates what the server
records establish from the still-unobserved task and notification history.

## The reframe

Today the system is **setup-driven**: a scanner rule fires, Jo rates or shadows
that setup, a paper trade runs. This design adds an **observation-driven**
path beside it:

| | Setup path (live, unchanged) | Market watch (proposed) |
|---|---|---|
| Trigger | S1 candidate email | Schedule plus deterministic market events |
| Jo's output | TAKE/SKIP, Go/Wait/Pass on one setup | A timestamped market read; optionally a message to Isaac |
| Baseline | S1 rules-only paper trade | Simple frozen price checks scored on the same outcomes |
| Trades | S1 contract and exits | None in the first version; a separate idea book later |

S1 observations may become inputs to Jo's read, but Jo's read never changes
S1's candidates or paper trades. That keeps S1 a clean baseline.

## What the research says (exploratory, research branch only)

Research lives on branch `claude/research-s1-orb-breakdown-put` (no PR;
branch-relative location `claude/research-s1-orb-breakdown-put:research/s1_downside_puts/`). In-sample, March 2 – October 13, 2026, SPY
trend day = at least 0.5 daily ATR open-to-close with the close in the outer
30% of the day's range (a hindsight label).

- Downside setups added to S1 (opening-range breakdown put, trend-continuation
  put) did not beat realistic option costs (profit factor 0.91 and 0.83).
- Trades on days that, in hindsight, trended made money with a VWAP trailing
  exit (about +35% return on premium); chop days lost it back. Identifying the
  day early is the problem.
- No price, breadth, volume or VIXY check called down-trend days well by late
  morning (best about one in three). Afternoon checks caught most down days,
  but little move remained after them.
- Macro days are small samples: CPI and jobs mornings mostly ended choppy;
  FOMC days leaned down (3 of 5); a gap down after an 08:30 release followed
  through more often than an ordinary gap down (2 of 5 vs 2 of 29).

These are leads, not design assumptions. They justify testing whether a
judgment-based read does better than simple checks, scored prospectively.
They do not show that it will.

## Diagnose October 14 first (MW-0)

**Read-only diagnosis, October 14, 2026, through 15:11:37 ET.** This is a
partial-session audit, not an end-of-day or ten-session acceptance receipt.
The application and installed check-service metadata name release
`e89a22813e5091b4aa4fc630a848849fad98a8fe`; it was the active release at
inspection, not necessarily for the whole morning. Sources: scanner day GET,
check ledger located from the configuration used by `deploy/check_control.py`
and opened with SQLite `mode=ro` plus `query_only`, saved check/model records,
deployed tool code and systemd/cron inventory. No production writes, tool
invocations, restarts or deployments were performed.

| Possible cause | Finding and evidence (all times ET) |
|---|---|
| 1. Jo never woke | **Refuted for the observed session.** Authenticated `tool_call` IDs 11–80 contain 70 calls by one actor. All 12 emailed candidates received on-time SKIP commits. `preopen_watchlist` calls 11–13 occurred at 09:13:13, 09:13:22 and 09:16:24, before the first candidate; their wake source is unknown. |
| 2. Needed data missing/stale | **Partial context/output gap, not absence of CPI awareness.** Every saved check contains `CPI (Sep 2026), 08:30, today`; `chk_e462a8f2…` at 09:52:02 already returned that calendar fact and VIX 15.83. Stored internal analyses have SPY/QQQ price/VWAP and 1–10 news headlines. However, `jo_view` returns the compact single-ticker answer, calendar and VIX/earnings, not the full index/news packet. `preopen_watchlist` can return index tape and news, but its six responses were not retained. No structured actual/consensus surprise, IWM/breadth or persistent market-state record was present in these saved answers. |
| 3. Retrieved data but formed no directional view | **Refuted for local weakness recognition; market-level synthesis unknown.** SPY decision `shd_bb39f951…` at 11:02:00 calls the entry countertrend below VWAP/EMA9. SPY `shd_d8530ccc…` at 11:58:47 says recovery is not holding; QQQ `shd_58aa2f2b…` at 11:59:10 describes a surrendered bounce near the low. These are setup rejections, not a saved day thesis or a timestamped bearish forecast. |
| 4. Formed a view but no path/permission to message | **Strongly supported as a setup-output/policy mismatch; external permission unknown.** The deployed catalog has no market-read submit or notification tool. The documented Gmail task allows fresh co-pilot Go alerts; saved verdict `chk_ddfa8f22…` at 11:03:17 explicitly says “noGo notification,” and `chk_f99b1143…` at 11:59:42 says “no Go alert.” There were no Go verdicts. This explains silence under that policy, but does not prove what Jo actually sent or its current task permissions. |

**Wake evidence and limits.** The documented route is scanner email → relay →
Jo Gmail task. No additional Jo market-watch wake was found in the host's
systemd timers, `/etc/cron.d`, or root/ubuntu/application-user crontabs.
The market-context timer refreshes earnings/VIX; Gmail sync imports journal
mail; operational alerts are not Jo market-watch wakes. ChatGPT schedules,
other Gmail triggers, task run history, manual prompts and messages to Isaac
are **unknown from the server**. The call log stores name/actor/time, not
arguments, success, response or wake origin. An authenticated call is not proof
of a successful response. No matching scanner/shadow failure was found in the
bounded journal filter; that does not establish external delivery.

**Conclusion:** the hypothesis is supported for setup-local interpretation and
missing market-level recording/message criteria. Its claim that Jo only woke
on setups is unproved; broader tools were called. CPI calendar awareness
already existed. MW-1 should expose and freeze a reusable market packet and
record market reads, rather than start by adding a new macro data vendor.
Ask Isaac for screenshots of Jo's enabled schedules/Gmail triggers and their
prompts, October 14 run history, and messages/manual prompts around 09:13–09:16,
10:40–11:03, 12:37 and 13:12–13:16 to resolve the remaining causes.

<details>
<summary>October 14 candidate and check timeline (ET; IDs shown as unique prefixes)</summary>

20 candidates: 19 long VWAP fades and one long ORB; no shorts. Twelve emails
were `sent`; none were `expired` or `skipped_daily_cap`. Eight `no_contract`
candidates have no email event and no shadow commit. The ledger and scanner
agree on all 12 commits, each `skip`, `on_time` (9 clean, 3 unclean).

| Candidate ID | Symbol/setup | Detected | Email sent | Shadow commit / decision ID |
|---|---|---|---|---|
| `b75fd4c5` | GOOGL orb | 09:50:33 | 09:50:44 | 09:51:51 / `shd_85d617d4` |
| `4c1acb94` | SPY fade | 11:00:42 | 11:00:50 | 11:02:00 / `shd_bb39f951` |
| `1a62f477` | AMZN fade | 11:20:47 | 11:20:54 | 11:24:58 / `shd_a9eb3da0` (unclean) |
| `e025363a` | QQQ fade | 11:20:49 | 11:20:59 | 11:23:53 / `shd_63e99ae2` |
| `20652164` | MRVL fade | 11:50:34 | no_contract; no event | — |
| `a684732c` | GOOGL fade | 11:55:39 | 11:55:42 | 11:56:42 / `shd_aec7bb37` |
| `1474c12c` | SPY fade | 11:55:39 | 11:55:43 | 11:58:47 / `shd_d8530ccc` (unclean) |
| `628766a8` | QQQ fade | 11:55:40 | 11:55:45 | 11:59:10 / `shd_58aa2f2b` (unclean) |
| `557c51b2` | META fade | 12:30:47 | 12:30:51 | 12:32:39 / `shd_fea9924d` |
| `563920a6` | MU fade | 12:35:36 | 12:35:37 | 12:36:48 / `shd_c9462e1e` |
| `06cd9247` | CRDO fade | 12:35:36 | no_contract; no event | — |
| `eff7db18` | MRVL fade | 12:35:36 | no_contract; no event | — |
| `3279227c` | AMD fade | 12:40:49 | no_contract; no event | — |
| `fe9f2db5` | AMZN fade | 12:45:37 | no_contract; no event | — |
| `0b2232ae` | GOOGL fade | 12:45:37 | 12:45:39 | 12:46:39 / `shd_21ca359a` |
| `634dd695` | AAPL fade | 13:50:48 | no_contract; no event | — |
| `90d85159` | META fade | 13:50:48 | 13:50:50 | 13:52:19 / `shd_08700289` |
| `a1178cc6` | CRDO fade | 14:05:38 | no_contract; no event | — |
| `35992f71` | AMD fade | 14:05:39 | no_contract; no event | — |
| `ced853fb` | AAPL fade | 14:30:40 | 14:30:42 | 14:32:14 / `shd_1c449726` |

`clean_order=false` is explained by interleaved co-pilot calls for other
candidates: AMZN `1a62f477` spans calls 28–29 at 11:24:02/11:24:14 (QQQ check
and verdict); SPY `1474c12c` and QQQ `628766a8` span calls 36–37 at
11:56:54/11:57:04 (GOOGL check and verdict). No `position_check` or `get_notes`
call appears in the observed log. This does not establish independence from
Gmail, memory or other connectors; S1's flags and labels remain unchanged.

Thirteen pre-trade checks and thirteen saved model verdicts: twelve match the
emailed candidates; the additional NBIS check's origin is unknown. Every idea
was long/call. Rules: 11 Pass, 2 Wait. Model: 11 Pass, 1 Wait, 1 Insufficient
Data; zero Go. No new check or verdict was submitted by this audit.

| Check ID | Symbol | Check received | Model saved | Rules / model |
|---|---|---|---|---|
| `chk_e462a8f2` | GOOGL | 09:52:02 | 09:52:18 | wait / wait |
| `chk_b8fda934` | NBIS | 11:02:24 | 11:02:38 | wait / insufficient_data |
| `chk_ddfa8f22` | SPY | 11:03:04 | 11:03:17 | pass / pass |
| `chk_d9852487` | QQQ | 11:24:02 | 11:24:14 | pass / pass |
| `chk_a7197d22` | AMZN | 11:25:09 | 11:25:20 | pass / pass |
| `chk_3738bfbd` | GOOGL | 11:56:54 | 11:57:04 | pass / pass |
| `chk_f99b1143` | SPY | 11:59:23 | 11:59:42 | pass / pass |
| `chk_5c234c10` | QQQ | 11:59:26 | 11:59:44 | pass / pass |
| `chk_cd797931` | META | 12:32:48 | 12:33:00 | pass / pass |
| `chk_b6b7a956` | MU | 12:37:07 | 12:37:19 | pass / pass |
| `chk_69c41246` | GOOGL | 12:46:44 | 12:46:54 | pass / pass |
| `chk_f0567d1d` | META | 13:52:28 | 13:52:35 | pass / pass |
| `chk_9fd34a6c` | AAPL | 14:32:25 | 14:32:33 | pass / pass |

Tool-call inventory: 12 `shadow_setup`, 12 `shadow_decide`, 13
`pre_trade_check`, 13 `attach_model_verdict`, 6 `preopen_watchlist`, 11
`candles`, 3 `review_checks`. Market-context-capable watchlist calls were
11/12/13 at 09:13:13/09:13:22/09:16:24, 18 at 10:40:31, 19 at 11:00:13,
and 54 at 12:37:20. Candle calls 59–69 span 13:12:42–13:16:06; their symbols
and responses are not logged. Review calls 78–80 were at
14:51:07/14:52:39/14:52:49. The private audit timeline retains every call's
exact timestamp and complete candidate/check/decision IDs; no credentials,
private addresses or account identifiers are copied into this design.

</details>

## Records and outcomes come first (MW-1)

**Bounded MW-1 contract; implementation authorized October 14, 2026. Activation
requires separate authorization.** Build a snapshot/read/score foundation beside S1,
with no trades, autonomous wake-ups, delivery, UI or paid model calls. MW-0
found existing calendar, index and news inputs but no retained market read;
reuse those sources and make the exact returned evidence durable. MW-2 owns
scheduling, event detectors and delivery. Preserve S1 rules, the ten-session
acceptance, shadow-first ordering and all independence labels.

### Storage and immutable records

The records below define the MW-1 storage and tool boundary.
Every record carries `schema_version`, a server-generated ID, UTC server
`created_at`, and `content_sha256` over canonical JSON excluding that hash.
Numbers must be finite; timestamps must include an offset and are stored in
UTC; `session_date` uses the exchange calendar in America/New_York. Updates,
deletes and conflicting overwrites are refused by storage constraints/triggers,
not merely by the tool description. Corrections append linked versions.

| Record / owner | Required fields beyond the common envelope |
|---|---|
| `market_watch_protocol` / app | `protocol_id`, `effective_from`, `universe`, `source_policy`, `feature_version`, `freshness_limits`, `horizons`, `anchor_rule`, `price_basis`, `missing_policy`, `comparator_version`, `day_label_version`; complete frozen values defined below |
| `market_watch_snapshot` / app | `snapshot_id`, `protocol_id`, `session_date`, `collection_started_at`, `collection_finished_at`, `session_open_at`, `session_close_at`, `market_phase`, `indices`, `volatility`, `calendar`, `headlines`, `gaps`, `input_manifest` |
| `market_watch_input` / check SQLite ledger | `input_id`, authenticated `actor`, `snapshot_id`, `snapshot_sha256`, exact returned `snapshot_json`, `served_at`; records what the tool offered, not proof the model understood it |
| `market_watch_read` / check ledger | `read_id`, `actor`, client `operation_id`, `request_sha256`, server `received_at`, `session_date`, `protocol_id`, `input_id`, `snapshot_id`, `snapshot_sha256`, `previous_read_id` (nullable), `view` (`up`, `down`, `mixed`, `no_view`), `main`, `alternative`, `invalidation`, `change_summary`, `forecasts`, `message_intent` (`none`, `update`, `correction`), `correction_of_read_id` (nullable), `prompt_version`, declared `model_id` (nullable/unknown), `quality_flags` |
| `market_watch_comparator` / check ledger | `comparator_id`, `read_id`, `protocol_id`, `snapshot_sha256`, `computed_at`, `signal` (`up`, `down`, `neutral`, `unavailable`), exact input values, three horizon probabilities or missing reasons; written atomically with the read |
| `market_watch_message_event` / check ledger | `message_id`, `event_id`, `read_id`, `actor`, `kind` (`intent`, `attempt`, `accepted`, `delivered`, `failed`, `unknown`, `rated`), `channel` (`none`, `email`, `push`), `is_correction`, `corrects_message_id` (nullable), `text_sha256`, bounded `text`, `occurred_at`, `recorded_at`, `source` (`system`, `transport`, `owner_report`), `transport_receipt_id` (nullable), `error_code` (nullable), `rating` (`useful`, `not_useful`, nullable) |
| `market_watch_outcome` / app | `outcome_id`, `evaluation_revision`, `supersedes_outcome_id` (nullable), `read_id`, `forecast_id`, `protocol_id`, `evaluated_at`, `status`, `reason`, `anchor_at`, `anchor_price`, `target_at`, `target_price`, `return`, `outcome_y`, `brier`, `comparator_brier`, `adverse_excursion`, `favorable_excursion`, `path_status`, `bar_manifest_sha256`; nullable measurements remain explicit |
| `market_watch_session_outcome` / app | `evaluation_revision`, `supersedes_outcome_id` (nullable), `session_date`, `protocol_id`, `open`, `close`, `high`, `low`, `prior_atr14`, `day_label`, `first_directional_read_at`, `false_alarm`, `opposite_direction`, `missed_before_noon`, `late_only`, `coverage_status`, `bar_manifest_sha256` |

App snapshots are saved before publication as content-addressed files through
a narrow read-only handoff, following the existing shadow exchange pattern.
The check service gets only those public-market files, no database credential
or new access to the private API. It retains the complete served snapshot in
its ledger so later publication changes cannot alter a read's evidence.
A narrow owner export supplies reads/comparators to the app evaluator; it
excludes checks, history, positions, notes and other actors. Export is read-only
and idempotent, and the app verifies IDs/hashes before insertion. The check process
cannot fetch outcome continuations through either new Jo tool. Protocol/hash
mismatches, forged IDs and cross-actor references fail closed. Any new path,
reader/export permission or migration needs MW-1's tier-2 review and separately
authorized activation; no existing grant is silently widened.

### Snapshot v1: the smallest useful packet

- **Universe:** SPY and QQQ only. No personalized watchlist, holdings or trade
  history. IWM, watchlist breadth, sectors, rates/dollar, flow labels and S1
  candidate/outcome feeds are deferred; they are not prerequisites to record
  the weakness MW-0 already found. No full-market breadth claim.
- **Prices:** reuse the bounded Alpaca adapter with explicitly labelled IEX
  stock bars/quotes in v1; no silent fallback or consolidated-feed claim. Per index: `price`, `price_at`, `prior_close`,
  `prior_close_at`, `session_open`, latest completed `bar_1m`, `vwap`,
  `or15_high`, `or15_low`, `return_vs_prior_close`, `distance_to_vwap`, and
  up to 12 completed regular-session `bars_5m` (start/end/OHLCV). No unclosed
  bars or forward filling. Regular-session VWAP is cumulative
  `sum(((high+low+close)/3)*volume)/sum(volume)` from the same completed 1-minute
  bars; OR15 is the high/low of all 15 bars from the exchange open. Missing
  required bars with an unknown cause makes the affected aggregate unavailable.
  The publisher may reconcile at most eight interior minutes after OR15 through
  complete, bounded IEX trade responses. A minute with no trades or only odd-lot
  (`I`) trades has no provider price bar; its exact query window, retrieval time
  and trade timestamps/conditions are retained as `omitted_minutes` in the bar
  manifest (Alpaca's [bar-generation rules](https://docs.alpaca.markets/us/docs/market-data-faq)
  explain these non-price-forming intervals). Those verified intervals contribute no invented OHLCV to the same
  VWAP formula; the metric discloses `verified_iex_non_price_forming_minutes`.
  Truncation, source errors, other trade conditions, unverified gaps and opening
  range holes still withhold the affected metric. Five-minute buckets and
  outcome/detector path-continuity rules stay strict. Before OR completion
  it is `not_ready`; regular-session metrics are not invented premarket.
  `input_manifest` retains the exact source bars needed to reproduce each
  aggregate, provider/feed, request window, retrieval time and payload hash.
- **Volatility:** reuse the existing timestamped VIX publication; fields
  `instrument`, `instrument_type=spot_index`, `value`, `change_pct`. Do not add
  VIXY as a substitute; any later futures ETF must use a distinct instrument
  type and protocol version.
- **Calendar:** reuse the official-source CPI/FOMC/jobs calendar, with
  `event_id`, `kind`, `name`, `scheduled_at`, `source`, `calendar_version`,
  `coverage_start`, `coverage_end`. `actual`, `consensus`, `surprise` are null
  with `not_supported` in v1. A scheduled time passing is not verification of
  release contents or of a “hot” surprise. Out-of-coverage is missing, not
  “no events.” Adding BEA or release values is a separate scope decision.
- **News:** retain at most 10 already-fetched SPY/QQQ headlines from the last
  24 hours; no new collector or historical backfill. Preserve `article_id`
  (nullable), `provider`, public `url`, `headline`, `published_at`,
  `provider_updated_at` (nullable), `first_observed_at`, `retrieved_at`,
  `payload_sha256`, `truncated`, query symbols/window and coverage/errors.
  Unknown first-observation/update times stay unknown. Apply
  [Catalyst V1](../agentic-trading-roadmap.md#catalyst-v1): retain the exact
  evidence used, and do not claim empty results prove no catalyst existed.
- **Every input group** includes `source`, `observed_at`, `retrieved_at`,
  `age_seconds`, `status` (`fresh`, `stale`, `missing`, `not_ready`,
  `not_supported`), `reason`, `source_sha256`. Use finer timestamps when fields
  differ. In RTH, price/completed-bar age over 180 seconds is stale; published
  VIX observation age over 60 minutes is stale. News retrieval age over
  30 minutes is stale, distinct from article age. An unknown observation time
  uses `status=missing, reason=observation_time_unknown`, never fresh. No replacement with zero. Source times
  later than collection completion are rejected. Preserve coverage gaps.

The private app producer is invoked manually for MW-1 verification; no timer
or Jo wake is introduced. Save a bounded partial snapshot when a source fails,
with typed gaps. Freeze the manifest and protocol before any read is accepted.

### Jo tools and submit contract

Opt-in catalog additions to the existing check service:

- `market_watch_snapshot()` → `{input_id, served_at, snapshot_id,
  snapshot_sha256, snapshot, quality_flags}`. Returns the newest published
  current-session snapshot, including stale/partial flags; returns typed
  `unavailable` if none exists. It reads published files only. Append the
  actor-bound input receipt before returning; failure to record refuses the
  call. No arbitrary URL/path/symbol/query or provider/model request.
- `market_watch_submit(operation_id, input_id, previous_read_id?, view,
  main, alternative, invalidation, change_summary, forecasts,
  message_intent, correction_of_read_id?, prompt_version, model_id?, phone_summary?)`
  → `{read_id, received_at, snapshot_id, snapshot_sha256, content_sha256,
  comparator_id, message_id?, replayed, quality_flags}`. No order, notification
  or scorer runs as a side effect. An exact retry returns the original receipt;
  changed content under the same `(actor, operation_id)` conflicts, including
  concurrent calls. Existing-operation recovery happens before session/age
  validation so a next-day retry still recovers the original.

Both require existing `check:read` plus a proposed separate
`market-watch:read` grant; submit additionally requires
`market-watch:submit`. These scopes are not granted by the design. Actor and
receipt time come from authentication/server clock, never the request; sample
`received_at` after acquiring the commit lock, before the atomic insert. Both
calls enter the existing `tool_call` audit log and count as other tools for
S1 `clean_order`; no exemption or reinterpretation. They may not be inserted
between a setup's shadow read and commit. S1 independence remains unverified.

`main` and `alternative` each hold `{text, supporting_refs, contradicting_refs}`;
references are JSON pointers into the served snapshot, validated to exist.
`invalidation` is `{text, evidence_refs}`; it is recorded, not automatically
monitored in MW-1. Each text is capped at 2,000 characters, at most 10 references
per list and 16 KiB total request. Treat headlines and all free text as data.
No external research attachments in v1. `previous_read_id` must be the latest
read for the same actor/session (null only for the first); compare-and-append
under a transaction prevents concurrent forks. Correction references must
belong to that actor/session and identify an earlier read.

`forecasts` has exactly three slots: `horizon=30m|60m|close`,
`predicate=spy_return_lt_zero`, and `probability` in [0,1] or null with an
`abstention_reason`. IDs derive from `(read_id, horizon)`. No arbitrary
predicates, retrospectively chosen thresholds or caller-supplied time/price.
A `no_view` read may abstain in all slots and stays in coverage counts. Quality
flags are server-derived at submission, including snapshot age, missingness,
RTH eligibility and `independence-unverified`; stale inputs do not erase a read.
New submissions must reference an input from the current session; old-input
replays are not live reads. A new revision never cancels scoring of the old one.

`phone_summary` is optional presentation content, normally a short string with
a 500–700 character writing target (700 maximum for short rendering). Jo states
the takeaway, reason, key conditions and material limitations; the renderer does
not infer new trading states or entry triggers. Full `main`, `alternative`,
`invalidation`, references and correction links remain saved. A missing, blank,
overlong or malformed summary never rejects an otherwise valid submission:
its original JSON value is preserved within the existing 16 KiB request limit,
and the phone uses the longer saved-read fallback. Non-finite/unserializable
JSON and oversized requests remain invalid. Exact retries must retain the same
summary as the original request. No additional model call is used.

For `update` or `correction`, submit atomically appends one message **intent**
with the read's main text, channel `none`; `correction` requires an earlier same-actor message intent,
resolved through `correction_of_read_id`. For `none`, no message is created.
An intent is not delivery evidence. Later MW-2 transport events append against that message ID; failed/uncertain attempts
stay visible, and only a transport delivery acknowledgement may be labelled
`delivered`. An owner-reported message/rating records its source and does not
pretend to be transport proof. MW-1 exercises these event rules with fixtures;
it adds no sender, notification tool or rating UI. An internal
`append_market_watch_message_event(message_id, operation_id, event)` method
validates event/source fields and returns an immutable event receipt; identical
retries recover it, conflicting retries fail. Jo cannot assert delivery or
submit a usefulness rating on Isaac's behalf.

### Frozen evaluation protocol `mw-v1`

Use SPY regular-session, split-consistent, non-dividend-adjusted 1-minute OHLC
bars from Alpaca IEX, matching the snapshot feed, with timestamps interpreted
as minute starts and evaluation at their ends. Persist the exact bar
manifest used. No future bar may enter the snapshot or comparator.

- **Anchor:** first regular-session minute close strictly after server
  `received_at`; the decision precedes its reference price. This adds at most
  one minute to receipt, explicitly reported. Forecast ends are anchor +30
  minutes, anchor +60 minutes, and the calendar's actual session close. Never
  truncate 30/60 minutes to fit the close or carry into another session.
  A target after the session close or at/before the anchor is `not_eligible`.
  Premarket/after-hours reads are descriptive, `not_eligible`; an unavailable
  or out-of-session anchor/target has no invented score. Half-days and DST use
  the exchange calendar, not fixed UTC/16:00 assumptions.
- **Outcome:** `return = target_price / anchor_price - 1`;
  `y = 1` iff return < 0, otherwise 0 (an exact tie is 0).
  `Brier = (probability - y)^2`. The close-horizon return measures move
  remaining after the read, not the day's open-to-close move.
- **Path:** use only full bars strictly after the anchor through the target.
  With directional sign `s=+1` for up and `s=-1` for down, favorable excursion
  is `max(0, max(s*(price/anchor_price-1)))` and adverse excursion is
  `max(0, -min(s*(price/anchor_price-1)))` over bar highs/lows. For mixed/no_view,
  directional excursions are null. Missing intermediate bars make path
  metrics unavailable even if endpoint return is scoreable. No options P&L.
- **Missingness:** evaluation is pending until target +15 minutes; retain that
  pending state as a query-derived state, not a mutable terminal row. A local
  finite evaluator then saves one initial terminal result per `(read_id, horizon,
  protocol_id, evaluation_revision=1)`: `scored`, `abstained`, `not_eligible`,
  or `unavailable` with reasons. Status precedence is not-eligible, then
  abstained, then missing endpoints, then scored; retained reasons may overlap. Missing exact anchor/target bars are unavailable; no nearest-bar
  substitution. Later data corrections append a superseding evaluation with
  its own manifest/version; the original remains visible and is never silently
  replaced. Superseding results increment `evaluation_revision` and name
  `supersedes_outcome_id`; reports retain original-versus-corrected cohorts.
  No automatic rescoring on provider revisions. Identical retries do not
  duplicate results. The same revision rules apply to session outcomes.
- **Simple comparator:** `price-check-v1`, computed at submission using the
  same frozen snapshot. Down when both SPY and QQQ completed-minute closes are
  below their session VWAP **and** SPY is below OR15 low; up for the symmetric
  above-VWAP/above-OR15-high condition; otherwise neutral. Freeze down-probability
  at 0.65/0.35/0.50 respectively for each horizon. These are uncalibrated design
  constants, not the unverified research win rates. Missing/stale required
  inputs yield `unavailable`, not neutral. Also report a constant p=0.50
  no-information baseline. All share each read's anchor, horizon and outcome.
- **Session diagnostic:** prior ATR14 is the arithmetic mean of true range
  over the preceding 14 complete regular sessions (exclude today), with
  `TR=max(high-low, abs(high-previous_close), abs(low-previous_close))`. Up/down
  trend requires signed open-to-close move >=0.5 ATR14 and close in the upper/
  lower 30% of today's high-low range (inclusive boundaries); otherwise chop. Missing history/session
  bars or zero range yields unavailable. A directional `view` on chop is a
  false alarm; a view opposite a trend is separately counted. A trend with no
  matching directional read before 12:00 ET is missed-before-noon; a first
  matching read afterward is late-only, never an early hit. For half-days use
  the earlier of noon and session close. MW-1's manually sampled sessions have
  `coverage_status=manual_partial`; whole-day miss rates stay unknown until
  MW-2 supplies a declared observation roster with wake failures included.

Report Brier and fixed probability calibration bins [0,.1), [.1,.2), …,
[.9,1] by horizon and protocol/model/prompt version, with counts of all submitted, scored, abstained, ineligible and unavailable
slots; preserve stale-input flags. Paired comparison uses the intersection
with a scoreable comparator and discloses exclusions plus total coverage.
Keep revisions and correlated horizons visible; do not present them as
independent sessions or claim statistical advantage from a small sample.

### Verification, acceptance and review

MW-1 is accepted as a foundation when fixture-based end-to-end proof covers:

1. Snapshot → published hash → actor-bound input → read/comparator/message
   intent → owner export → terminal outcomes, with exact input reproduction.
   Partial sources, stale data, absent calendar coverage and unpublished news
   remain flagged. No future observations or unclosed bars pass the cutoff.
2. Direct database UPDATE/DELETE refusal; exact and conflicting retries;
   concurrent submissions; latest-parent enforcement; cross-actor/forged
   references; hash tampering; lost-response recovery after restart/next day;
   duplicate export/evaluator execution. One immutable logical record survives.
3. Deterministic 30m/60m/close fixtures with known returns, ties, up/down path
   excursions and Brier values, matched comparator inputs, missing endpoints
   and interior bars, abstentions, late-session reads, holidays, half-days and
   DST. A corrected dataset cannot overwrite the original result. A later
   revision cannot remove an earlier forecast from the denominator.
4. Missing scopes/invalid actor and credential/path injection are refused;
   snapshot/export readers cannot access private account data or other ledger
   tables. New calls preserve existing S1 `clean_order` behavior. No live
   provider/model call, message, paper trade or S1 mutation occurs in tests.
5. Message intent/attempt/accepted/delivered/unknown remain distinct; retries
   and owner ratings append without manufacturing delivery. The acceptance
   report reproduces scores and unavailable counts from frozen fixtures.

**Review:** implementing the records, storage initialization, scorer and check-service tools is
**tier 2** under [review policy](pr-review.md): fresh `risk-reviewer` (Astra,
high) plus focused `reviewer` (Sol, medium), focusing on append-only provenance,
auth boundaries and no-lookahead scoring; focused failure/recovery tests and
full applicable final-head CI via the CI-backed path. A separate authorized
activation proves the installed paths/grants and real Jo tool access. MW-1
fixture acceptance does not complete MW-2's 20-session trial or either S1 gate.

## MW-1 implementation and activation boundary

The implementation adds the manual snapshot producer in
`backend/app/engine/market_watch_snapshot.py`, frozen protocol helpers in
`backend/market_watch_common.py`, the opt-in check ledger in
`backend/market_watch_ledger.py`, and the offline evaluator in
`backend/app/engine/market_watch_evaluation.py`. `backend/market_watch_owner.py`
provides explicit owner snapshot/export commands. No scheduler, detector,
notification sender, rating UI or autonomous Jo run is included.

Storage adjustment: app-owned evaluation/import records use an explicitly
selected, single-actor local SQLite sidecar, not an automatically migrated journal table.
The check records use additive tables in the existing isolated check ledger,
initialized only when `market_watch_snapshots_dir` is explicitly configured.
This keeps installation and schema activation separate from merging code and
preserves the private journal database boundary. Neither default configuration
nor issuer grants are changed. Snapshot publication is public-market-only;
owner export selects only one actor's market-watch tables through read-only
SQLite access. Continuations never pass through the Jo tools.

Existing-source limits are explicit: the current macro-calendar file has no
publication/observation timestamp, so its covered events remain visible with
`observation_time_unknown`; it is not labelled fresh. There is no durable
publication of the existing fetched headlines with the required provenance.
The default producer therefore records `no_published_headline_cache` and does
not call the news collector. Supplied published-headline fixtures exercise the
retention boundary; adding a durable publication later is a separate decision.
Unknown exchange-calendar bounds also remain unavailable instead of inventing
regular hours.

Fixture acceptance is exercised by `backend/tests/test_market_watch_snapshot.py`,
`backend/tests/test_market_watch_ledger.py`, and
`backend/tests/test_market_watch_evaluation.py`: publication/receipt/export/score
reproduction, source failures, postmarket/closed-session handling, missing opening
and interior bars, exact endpoints, correction cohorts, immutable retries,
concurrency, actor/scope refusals, and message provenance. Native review and
final-head CI status are recorded in the implementation PR, not inferred from
these fixtures.

The implementation retains `manual_partial` session coverage and
`independence-unverified`. Fixture acceptance is evidence about records and
math, not live access, delivery, performance, or completion of the later
20-session trial or either S1 acceptance gate. MW-0's unresolved external wake
origins and actual messages remain unresolved; screenshots are not a build gate.

Separately authorized activation must name the release, actor and paths, then:

1. Install the reviewed app/check code and explicitly create the app-owned
   outcome sidecar and a dedicated public snapshot publication directory.
   Confirm backups and rollback before opt-in check-ledger schema initialization;
   existing tables and rows must remain unchanged.
2. Give the check-service identity read-only access to that publication
   directory only. Set `market_watch_snapshots_dir` to that exact absolute path;
   keep it disjoint from keys, ledger, feature files and shadow exchanges.
   Approve any service sandbox/path allowance and the required restart explicitly.
3. Grant the selected check actor `check:read` plus `market-watch:read`, and
   `market-watch:submit` only for submission. Verify issuer consent, refreshed
   tokens, scope refusal and the installed catalog with that actor. Do not widen
   other actors' grants or expose the private API.
4. In the private app environment, manually invoke
   `python market_watch_owner.py snapshot --directory ABSOLUTE_PUBLIC_DIRECTORY`
   from `backend/`, using existing permitted sources. Inspect timestamps, gaps,
   feed, manifest and protocol hash before a manually authorized Jo read/submit.
   A missing source remains missing; activation does not authorize a new collector.
5. As the owner, run `python market_watch_owner.py export --ledger ABSOLUTE_LEDGER
   --actor CHECK_PROFILE_ID` and transfer only that narrow export to the app-side
   evaluator. Supply explicitly frozen IEX continuation/history bars and the
   exchange-calendar roster there (missing prior sessions/roster leave ATR and
   session diagnostics unavailable),
   verify/import the export, run the finite evaluator, and retain the report and
   original-versus-corrected cohorts. No outcome continuation is mounted into
   the check process.

None of these activation actions was performed by the initial implementation task.
MW-2 scheduling, event detection and message transport need their own scope and
review; merging this foundation does not authorize them.

Subsequent owner-authorized activation on October 14 installed the merged code,
initialized the isolated stores after a verified ledger backup, added only the
two delegated market-watch scopes, and refreshed the existing Check v4 catalog.
A manual post-close snapshot passed validation inside the check service's mount
namespace; publication writes and private configuration/outcome reads remained
denied. It exposed an incorrect default macro-calendar file path, now corrected
to the bundled `app/data/macro_calendar.json` with a default-reader regression.
The first immutable snapshot retains its explicit calendar source-error gap;
the repaired producer was installed from merged PR #313 (`a00ad678cd4c`) after
main CI and deployment-package checks passed. A new immutable post-close
snapshot retained the CPI entry with `observation_time_unknown`, stale prices
and VIX, and the explicit unpublished-news gap. Check-namespace read-only and
private-path denial checks passed again.

An instructed **Codex connector** proof then used the existing authenticated
Check v4 actor to fetch that snapshot, submit one explicitly labelled `no_view`
read with three abstentions and `message_intent=none`, and retry the identical
submission. The same immutable read/hash was returned, with no duplicate or
message event. This proves the connector's scoped read/submit access, not actual
Jo use or independent market reasoning. The narrow owner export was identical
on retry. The app-side evaluator used only the snapshot's frozen IEX bars and
recorded three `not_eligible` outcomes, zero scores and an unavailable session
label because required history/roster were absent. Repeating import/evaluation
inserted no extra outcomes.

The owner then explicitly authorized one manual Jo test. Jo fetched the same
snapshot, saved one separately labelled post-close `no_view` read linked to the
Codex proof, and repeated the exact submission. Jo's displayed input/read IDs
and hashes matched the server's immutable records; the audit showed one
snapshot call and two submit calls, with one new read and no message event.
The narrow owner export/evaluator added three ineligible horizons for Jo and
zero scores; exact export/import/evaluation retries added no duplicate records.
This establishes actual Jo access for the instructed test only. Eligible
intraday scoring, independent reasoning and later session trials remain
unproven; no trial, schedule or market-message delivery was activated.

## Wake-ups and messages (MW-2)

### Selected first slice: four scheduled reads

On October 14 the owner requested a scheduled market read at 09:50, 11:00,
12:30 and 14:00 ET and a market-context exception to setup Go-only messages.
This selects the fixed-schedule/chat-advice slice below; deterministic event
detectors, other instruments/predicates, an app message sender, automated
continuation acquisition and the twenty-session acceptance run remain deferred.
PR #315 implemented this slice. Its final head passed CI and the Ubuntu
deployment checks, both required native reviews, and 179 focused market-watch
and documentation tests. Owner-authorized activation completed October 14:
the merged code is deployed, the isolated Check runtime preserves its config
and ledger records, and the publisher timer is enabled with its first
publication due October 15 at 09:49 ET. The publisher's database connection
was verified read-only; the Check namespace can read public snapshots but
cannot write them or read the private app environment/outcomes. A live
connector call recovered Jo's existing latest read and the unused three-intent
budget without submitting a new market read.

The four enabled native tasks were verified under Trader Jo with the complete
saved workflow, explicit SLOT and weekday ET times, first due October 15. The
existing setup task's bounded exception was saved and verified after reload;
its original source/expiry guards and shadow-first sequence remain intact.

October 15 first-session diagnosis: the 09:49 publisher packet was available
and the 09:50 native task reached both market tools, but its submission listed
13 supporting references against the existing maximum of 10 per list. The
ledger correctly refused it without saving a read. The shared task workflow
now states that limit, recommends existing parent pointers, and requires a
successful `read_id`/`received_at` receipt before reporting completion. An
instructed late recovery is distinct from on-time scheduled execution; task
activation and attempted calls alone do not close that acceptance gap.

The optional MW-2 event/email wakes, read-notice outboxes and market-watch
phone-push delivery remain disabled and unconfigured. A later push activation
must reconcile the chat route to avoid duplicate messages. No live scheduled
publication, Jo wake, eligible forecast or delivered market note was claimed
by this configuration proof.
Frozen outcome collection/evaluation and later session trials remain separate.

The proposed task needed two concrete additions to MW-1: an opt-in app-side
publisher before each wake, and server-owned recovery of the latest parent.
The publisher refreshes the same bounded SPY/QQQ IEX packet every two minutes
from 09:49 through 15:59 America/New_York, including the four pre-wake times
09:49, 10:59, 12:29 and 13:59, with read-only database access. Four daily
publications alone cannot support fresh setup-triggered reassessments between
wakes. This source cadence adds no Jo/model wakes or event detector. The
exchange calendar suppresses holiday and out-of-session half-day refreshes. Its app-owned immutable
publication success/failure receipts establish producer attempts, not Jo wakes.
No missed refresh is silently backfilled or labelled an on-time Jo read.
A provider failure before publication is explicitly retryable within its slot;
a crash or uncertain error after publication begins stays unknown and
nonretryable until owner reconciliation.

`market_watch_snapshot` additionally returns `context`: the authenticated
actor's current-session `latest_read`, `latest_message_intent` (including its
read), discretionary intent count/remaining budget, and
`delivery_status=unverified`. This is mutable recovery metadata alongside the
immutable input packet, never part of snapshot evidence. It contains no other
actor's records, setup/check history or private account data. The same context
is available with a typed unavailable snapshot response so task memory need
not invent a parent. Existing scope requirements and audit/clean-order rules
are unchanged.

Ordinary update intents share a hard limit of three per actor/session across
scheduled and setup-context reads, checked inside the append transaction.
Linked corrections to an earlier same-session message intent are exempt;
an unmessaged read cannot manufacture an exemption. Exact operation retries
recover before budget/age checks. A quota rejection commits nothing; Jo can
still save that observation with `message_intent=none`. This counts reservations
conservatively, including an intent whose chat delivery is uncertain. It does
not establish a hard transport-delivery count or delivery proof.

The [scheduled task prompt](../../deploy/market-watch/jo-task.md) retains all
three `mw-v1` SPY predicate/horizon slots. QQQ supplies context. A stale core
packet becomes a saved `no_view` with abstentions; an unavailable packet leaves
its audit call and a one-line native task failure. Missing calendar observation
and release values are preserved, rather than gating every otherwise usable
read. Unchanged reads stay quiet. A discretionary chat update requires a
material directional change (named-horizon down probability >= .65 or <= .35),
a strengthening of >= .10 on the same horizon with new evidence, or a specific
conditional opportunity. These are notification-policy constants, not a
calibration/edge claim. Invalidation of previously messaged advice is a linked
correction even over budget. Chat is sent only after a new committed intent;
replayed receipts never send another chat message.

The [setup task addendum](../../deploy/market-watch/setup-task-addendum.md)
runs only after the existing shadow commit and co-pilot verdict. Two distinct
same-session call/long Pass/Wait reviews due to below-VWAP/failed-bounce evidence
prompt a fresh market reassessment; they do not automatically assert a bearish
forecast. Existing fresh Go alerts remain, while market notes share the same
three-intent budget and correction policy. S1 decisions and independence
labels remain unchanged. Native Jo task history, producer receipts and input/
read records must be reconciled before claiming wake coverage; neither an
installed timer nor fixture tests complete the live-session acceptance gate.
Owner export and frozen evaluation remain explicitly operated as in MW-1.


**Observe often, message rarely.** TradeJournal runs the event detector; Jo
is called on:

- a schedule: about 08:50 (after 08:30 releases), 09:50, 11:00, 12:30, 14:00;
- deterministic events: a scheduled release time passed, SPY crossing or
  failing at VWAP or the opening range, a new session high/low after 11:00,
  a move of N daily ATR since Jo's last read. Thresholds are set once and
  versioned.

Each wake produces a read (possibly "no change"). A **message** goes to
Isaac only when the read changes what he should consider: a directional
view forms or strengthens past a stated probability, a view is invalidated,
or a specific opportunity appears. Another red candle is not a reason.
Budget: about three discretionary messages a day; a **correction** to an
earlier message is always sent, even over budget. (As implemented in MW-2: when
the corrected message reached Isaac, once per corrected message and at most
three a session; see below and "Choices for Isaac".)

Message format: the read in one line, confidence as a probability on a named
forecast, the evidence, what would prove it wrong, and which trades fit or
should be avoided, with Isaac's recorded cautions (puts in the first 15
minutes, chasing extended moves, late-day holds) as flags rather than rules.

**Wake route.** The documented automatic setup route uses Gmail; MW-0 could
not establish the origin of the other observed calls. Proposed options,
to be chosen with the shadow independence work: (a) a TradeJournal email per
scheduled or event wake — available now, inherits the same
`independence-unverified` limits; (b) MCP Events on the connector
([shadow S3](shadow-build-plan.md#s3--independence-later-research-gated));
(c) a scheduled Jo task, subject to plan usage limits. The market watch is
advice to Isaac, so route (a) is acceptable for it; its reads must not feed
Shadow Isaac decisions until independence is settled.

## MW-2 implementation and activation boundary

**Event wakes and phone push, complementing the selected first slice (#315).
Off by default; activation needs Isaac's separate approval.** On October 14
Isaac chose to keep #315's scheduled Jo reads (09:50, 11:00, 12:30, 14:00), its
snapshot publisher and its ledger-side limit of three ordinary intents, and to
add from this slice only the deterministic event detector, event wakes and
ntfy delivery. This module therefore publishes no snapshots and sends no
scheduled wakes.

`backend/app/engine/market_watch_wakes.py` holds the frozen `DETECTOR`
(`mw-detect-v1`), `WAKE_POLICY` (`mw-wake-v1`) and `MESSAGE_POLICY`
(`mw-message-v2` for short-summary presentation; eligibility/budgets unchanged);
their joint hash is stamped on every record. The API process
runs one pass about every 30 seconds during the regular session, only when
`MARKET_WATCH_ENABLED` is true and `MARKET_WATCH_SNAPSHOTS_DIR` (#315's
publication directory) and `MARKET_WATCH_STORE` are absolute paths; a bad
setting logs and leaves MW-2 off without blocking API startup. Nothing places,
sizes or arms an order, and nothing writes S1, its acceptance or shadow S1
(the setup guard below only reads S1's email and shadow events); market-watch
reads never reach Shadow Isaac.

- **Detector.** Runs on the latest current-session snapshot from #315's
  two-minute publisher and replays its frozen SPY minutes from the open, so the
  same snapshot yields the same events: a SPY close crossing VWAP, OR15 high or
  OR15 low by more than 0.05%, or a failed attempt (wick through, close back),
  from 09:45, 30-minute cooldown per level; a new session high or low on a bar
  ending at or after 11:00, 30-minute cooldown; a SPY move of each 0.5 × prior
  ATR14 (14 complete prior sessions, Alpaca IEX daily bars) since Jo's last
  read, priced from that read's served snapshot; a scheduled CPI/FOMC/jobs time
  passed (time only; with publication starting 09:49, an 08:30 release is
  recorded late and does not wake Jo). A missing minute is recorded once as a
  `minute_gap` event (never a wake) and ends VWAP events for the session;
  OR levels need all 15 opening bars; extremes and ATR moves keep using the
  real bars. Events detected more than 10 minutes after their bar are `late`
  and never wake Jo.
- **Event wakes (route a).** An event wakes Jo unless a wake went out in the
  last 15 minutes or one of Jo's scheduled reads is 5 minutes ahead or up to
  15 minutes behind (`coalesced`), or 6 event wakes were already sent that
  session (`rate_limited`). It is also withheld (`setup_guard`) while an S1
  setup emailed in the last 10 minutes has no shadow decision yet: a market
  call in that window would make the shadow commit `clean_order=false`. The
  app reads the scanner's events for this and never writes them; unknown state
  withholds the wake. A setup email arriving after a wake can still overlap;
  that residual risk to shadow S1's clean-order count is Isaac's to accept. Each wake is one email through the scanner's
  existing mail path, subject `TJ Market Watch: <wake ID>`, body only the wake
  ID; the [event task prompt](../../deploy/market-watch/jo-event-task.md) uses
  operation ID `mw-event-v1:<wake ID>`. Each attempt is recorded `sending`
  before the send; Gmail acceptance is `accepted`; a refusal or unreachable
  server is `failed` and retried at most 3 times, 60 seconds apart, within
  5 minutes, then `expired`. A timeout or dropped connection after the request
  went out, or a `sending` row with no result (crash mid-send), is `unknown`
  and never resent, so a wake may be lost rather than sent twice. Wake IDs are
  deterministic per event, so a restart never plans a wake twice.
- **Read notices.** With `market_watch_outbox_dir` set in the check
  configuration, `market_watch_submit` writes a sealed, deterministic notice of
  each committed read (public read fields, message ID and links) as a write-once
  outbox file — the shadow-outbox pattern. A failed handoff refuses the call and
  an identical retry recovers it. The seal is an integrity hash, not a
  signature: the boundary is that only the check service can write the outbox.
  The app checks the hash, field types and that the snapshot exists in the
  publication directory, then stores the notice; a refused file is recorded
  once as a `notice_refusal` and never stalls other notices. The app gets no
  check-ledger access. On Linux the bounded reader uses `O_PATH` directory
  descriptors to traverse the private Check parent without permission to list
  it; every component still refuses symlinks and the final file still requires
  read permission and a bounded regular-file check. Other platforms retain the
  existing read-only directory-open fallback. No private-parent ACL widening
  is required. Notices cover every read: scheduled, setup-context,
  event and manual.
  Existing reads keep byte-identical `mw-read-notice-v1` notices for handoff
  recovery. Reads submitted with `phone_summary` use `mw-read-notice-v2`, whose
  exact field set adds that field. The consumer accepts both versions, validates
  the seal/snapshot normally and treats summary usability only as a rendering
  concern. Deploy the compatible app consumer before enabling summaries in
  Check/native tasks; an old consumer cannot import v2 notices.
- **Messages.** Channel: **phone push through the server's existing ntfy alerts**
  (`NTFY_URL`). Every committed `update` or `correction` intent gets one
  decision: `send`, `suppressed_budget` or `expired_before_send`. The check
  ledger already refuses a fourth ordinary `update` per session (#315); the
  app's own budget of three is a second guard that refunds a send that expires
  undelivered. A correction skips the app budget when the message it corrects
  reached Isaac (`accepted` or `unknown`), once per corrected message and at
  most 3 times a session; any other correction is budgeted like an update. A
  budget decision is final. The push title carries the existing direction and
  correction label plus the server's save time in Eastern time (not a quote
  timestamp). The body uses Jo's usable `phone_summary`, populated forecasts
  only, and source limitations/observation times from the referenced snapshot.
  Forecasts remain probabilities of negative SPY return from the post-receipt
  anchor, regardless of the view; they are not confidence or entry signals.
  Generic cautions, internal IDs and the repeated alternative are omitted from
  phone prose. Full reasoning, references, forecasts and links remain saved.
  The renderer never derives "setup invalidated" or "conditions met" states.
  If the summary is unusable, the fallback identifies itself and prioritizes
  the full invalidation and main text, then change summary and available
  forecasts. A 3,500 UTF-8-byte budget reserves data limitations; whole sections
  that cannot fit get an explicit omission notice rather than a cut-off
  sentence. This fallback may be longer than the short summary. Losing an
  archived snapshot after import does not block sending: source flags remain
  visible and observation times are labelled unavailable. Summary failure
  does not bypass or alter any correction, budget, age or retry guard.
  No full-read page/link is provided by this change: `/morning/market-reads`
  remains a reliability view. Native scheduled/event/setup task instructions
  must be updated separately after compatible consumer/producer rollout;
  repository prompt edits alone are not live task proof. ntfy's reply ID is
  recorded as `accepted` — evidence ntfy took it, not that the phone showed it.
  Failures are retried at most 3 times within 10 minutes of the read, then
  `expired`; timeouts and interrupted sends are `unknown`.
- **Records.** Events, wakes, wake attempts, read notices, notice refusals,
  message decisions and message attempts are immutable rows in an explicitly
  selected SQLite file (application ID `MWD1`), separate from the journal
  database, the MW-1 outcome store, #315's publisher receipts and the check
  ledger. Transport events stay in that app-side file because the app cannot
  write the check ledger; the report joins them by message ID. Owner ratings
  remain the check ledger's `rated` events.
- **Report.** `python market_watch_owner.py report --store ABS --outcomes ABS`
  prints, per session, event wakes and Jo's scheduled slots → reads → messages
  → outcomes, plus the MW-1 evaluator's score groups over imported exports. A
  read whose exported `operation_id` names its trigger (`mw-event-v1:<wake ID>`
  or `mw-scheduled-v1:<date>:<HH:MM>`) is linked exactly; otherwise the first
  unclaimed read within 30 minutes (and before the next trigger) is linked by
  time, and only for reads known from notices alone: an exported read whose
  operation ID names another workflow is never credited to a slot by time.
  Reads with neither are `unprompted`. MW-2 cannot see a scheduled run
  that saved nothing; that stays in Jo's native task history and #315's receipts.
- **Scheduled-read reliability (owner screen).** `GET /jo/market-reads`
  (owner-only; `/morning/market-reads`, linked from Morning) shows the last ten
  weekdays back to the first recorded evidence; `?day=YYYY-MM-DD` returns that
  one weekday for the Daily Review's Jo's day timeline, and `?month=YYYY-MM`
  that month's weekdays up to today (never before the first evidence) for the
  Daily Review calendar's Jo marks. Each session lists `messages`: Jo's reads
  flagged for the phone, with decision, delivery (`accepted` is ntfy taking the
  push, not the phone showing it), `decided_at` and `settled_at`. Each credited slot and
  each read not credited to a slot carries `read`: Jo's saved `view`,
  `main_text`, `alternative_text`, `invalidation_text`, `change_summary` and
  `is_correction` (null when only an export without the text is known). For each 09:50, 11:00, 12:30
  and 14:00 slot it joins the prep slot's latest #315 publisher receipt
  (status, attempts, error code; `started` alone is an unknown outcome) with
  the read `session_report` links to it, and reports the Check receipt time and
  its delay from the slot in seconds. Each slot also has a `deadline` and a
  `delivery` state: `on_time` when the Check receipt is within 15 minutes of
  the slot, `late` after that (with `late_by_seconds`), `missing` once an
  import of read notices that ran at least a minute after the deadline found
  none, `pending` before the deadline, `not_expected` or `unknown`. The
  15 minutes (`SCHEDULED_READ_DEADLINE_MINUTES`, outside the hashed policies)
  is a **proposal of October 21, 2026, not yet confirmed by Isaac**; the reads
  observed October 15–21 arrived 18 seconds to 12.4 minutes after their slot.
  Delivery is judged on Check's receipt time, not on when the app imported the
  notice; the route reports the API runner's last import (`importer`), and
  while that is older than the deadline plus a minute a slot without a read is
  `unknown`, never `missing`. The
  exchange calendar marks slots on closed days or after an early close as not
  expected; an unavailable calendar, store or receipt directory reads as
  unknown, never as missing. The route has no outcome store, so it links by the
  time window only: a read more than 30 minutes after its slot (or after the
  next wake) is listed as not credited to a slot, and the slot shows no read
  seen. Equally, a manual or setup-context read inside the window is
  credited to the slot, since the route cannot see its operation ID. `reliability_report(..., outcome_store=...)` links exactly by operation
  ID when an export is imported. A receipt time is not when Jo started, and a
  slot with no read has no cause the app can see. The Daily Review shows
  `Matched by time`, `Schedule reference matched` or `Match unknown` before
  opening a read; both owner views explain that a time match does not verify
  the scheduled run. Even a matching schedule reference does not establish
  who started it. An extra read's market-alert link stays unverified because
  this response does not expose its attribution method. Tests:
  `backend/tests/test_market_watch_reliability.py`.
- **Missed-read phone alert (opt-in).** `deploy/alerts.py` reads
  `GET /jo/market-reads` every two minutes when `JO_MARKET_READ_ALERTS=true` in
  `alerts.env` and `MARKET_WATCH_ENABLED` is on, following the [morning
  watchdog](dots-integration.md#delivery-honesty-and-the-morning-watchdog)
  rules: one "Jo's 11:00 AM market read is missing" push per slot and day when
  the slot turns `missing` (no grace), naming a failed or absent packet, and one
  "arrived" recovery if a read lands inside the 30-minute window (usually late;
  the screen says which); "Jo's
  market reads aren't being checked" when the import is three minutes stale or
  has no outbox (five-minute grace, slots then stay unknown); and the status
  read itself failing (ten-minute grace). An uncertain send is logged `unknown`
  and never resent; notices are kept seven days in the alerts state file and
  shown per session on the reliability screen. Limits: a manual or
  setup-context read, or a late reply to an event wake sent before the slot,
  inside a slot's window still counts for that slot, so it can hide a missed
  scheduled run; a read whose notice the app refused counts as missing (the
  refusal is in the store's `notice_refusal` records); an unavailable exchange calendar leaves slots
  unknown without an alert of its own; and ntfy accepting a push does not prove
  the phone showed it. Tests: the market-read cases in
  `backend/tests/test_deployment.py`.

Fixture tests: `backend/tests/test_market_watch_wakes.py`. They are not live
proof of mail, push, Jo's triggers or the 20-session acceptance.

**Activation (separate, needs Isaac's approval).** Requires #315's publisher to
be active. Name the release first, then:

1. Create the app-side store under `/var/lib/tradejournal/market-watch/`. Give
   the API service read access to `/var/lib/tradejournal-market-watch-public`
   (MW-2 only reads it).
2. Create a check-owned outbox (for example beside `shadow-outbox`) with the same
   read-only ACL for the API user, set `market_watch_outbox_dir`, and restart the
   check service. Set `MARKET_WATCH_OUTBOX_DIR` for the API to the same path.
3. Confirm the scanner SMTP settings and `NTFY_URL` are present in the API
   environment. `SCANNER_EMAIL_TO` is the owner's Outlook relay inbox, whose
   rule forwards only scanner mail with `TJ Setup:` (see the
   [shadow S1 route](shadow-s1-contract.md)); self-sent Gmail did not wake Jo.
   With Isaac's approval, widen that rule to also forward `TJ Market Watch:`
   from the scanner sender, and add a Jo task triggered on
   `^FW: TJ Market Watch:` with the [event task prompt](../../deploy/market-watch/jo-event-task.md).
   Keep the shadow S1 `^FW: TJ Setup:` filter unchanged.
4. Push replaces chat for market messages: at the same time, change step 8 of
   the [scheduled task](../../deploy/market-watch/jo-task.md) and the
   [setup addendum](../../deploy/market-watch/setup-task-addendum.md) in Jo's
   live tasks to "do not send chat; TradeJournal pushes committed intents".
   Otherwise each message reaches Isaac twice.
5. Set `MARKET_WATCH_ENABLED=true`, `MARKET_WATCH_SNAPSHOTS_DIR` and
   `MARKET_WATCH_STORE` in `backend.env`, restart the API under the usual
   market-hours safeguards, and watch one event wake, one read notice and one
   push end to end. Disable by unsetting the flag; records stay.

## Replay as evidence, with limits (MW-3)

Use replay to find failures and test the workflow, not to establish
performance:

- price history replays cleanly with sealed continuation (the
  [historical replay](dot-historical-replay-contract.md) pattern, extended
  from 15-minute shares to SPY/QQQ/IWM 5-minute bars — needs a focused check
  of those interfaces before calling it an extension);
- calendar times are reliable; consensus/actual values need publication-time
  sources;
- historical news needs original publication and revision times, which the
  current fetcher does not keep;
- the model may already know famous outcomes, so replay results are labelled
  `replay-hindsight-risk` and never pooled with live reads.

Candidate set: the 2026 macro days in the research table plus a matched
number of ordinary days, so false alarms are measured too.

## Later, gated on evidence

- **Idea book**: Jo's own paper trade ideas in either direction, recorded
  before the trigger with trigger, invalidation, contract and execution
  assumptions, priced like S1, kept separate from S1 and Shadow Isaac.
  Only after reads beat the comparator on false alarms and calibration.
- **Analog days and playbooks** (CPI, FOMC, jobs, expiration, earnings):
  only when enough recorded days of each type exist to say something.
- **Scorecard screen**: after the records and outcomes above exist.

## Smallest version and acceptance

MW-0 to MW-2 with no trades. It is accepted when, over at least 20 live
sessions including at least three scheduled macro days:

1. every scheduled wake and triggered event produced a read or a recorded
   failure, with input freshness visible;
2. every read's forecasts were scored at their horizons;
3. messages stayed within budget, every correction was sent, and Isaac rated
   each message;
4. the read-versus-comparator table (calibration, false alarms, missed days,
   move remaining after the read) is reported honestly, including "no
   advantage shown".

Twenty sessions may hold only a few trend days; the first result is
descriptive. Only a measured advantage justifies the idea book.

## Choices for Isaac

- Whether to authorize the MW-1 activation steps above, then select an MW-2 slice.
- Whether to authorize the MW-2 activation steps above (event wakes and ntfy
  push on top of #315's schedule; push replaces chat).
- Whether the MW-2 correction rule is right: a correction skips the budget only
  when the message it corrects reached Isaac, once per corrected message and at
  most three a session; a correction of a message he never got is budgeted.
- Whether Jo's market reads may see his open positions (useful advice, but
  reads then cannot feed an independent shadow).
