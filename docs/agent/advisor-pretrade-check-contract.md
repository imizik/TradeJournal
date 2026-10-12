# Jo pre-trade check — Dots step 4, slice 1

Selected by Isaac on October 11, 2026 (evening ET) as the first real-data
advisor slice: the moment he would use most during a session. Plan only;
nothing here is built, installed or activated. It reconciles Dots step 4 on the
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

Step 2 is **built, not installed or activated** (October 11, 2026):

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
  and `upgrade` (all units stopped; replaces only the runtime code, keeps the
  previous one, refuses a bundle with changed units or feature view);
  units in [cloud-mcp-check](../../deploy/cloud-mcp-check/); UID-only policy in
  [check_network.py](../../deploy/check_network.py). Install writes no
  credential and starts, enables and loads nothing. Activation (step 4) adds
  `alpaca-key-id`, `alpaca-secret-key` and `features-database-url` under
  `/etc/tradejournal-check/` (root 0600), creates role `tj_check_features`
  and applies `feature-view.sql`, runs the key unit before the service, and
  publishes the Caddy route.
- Proof: `backend/tests/test_cloud_mcp_check.py` (generated tokens, recorded
  Alpaca responses for SPY/QQQ on October 9, 2026),
  `backend/tests/test_check_deployment.py`, and the disposable Ubuntu
  [smoke](../../deploy/cloud-mcp-check/smoke.py) in the deployment workflow.
  Speed against the live provider is not yet observed.

Step 3 (owner view) is **built, not installed or activated** (October 11, 2026):

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
total P&L only (never counted as followed); `no_closed_trade` never claims no position, since open trades
appear only after they close; `pending` until the window has passed and the
history file was refreshed after it; swing checks are `not_linked`.

While holding and notes (slice 2, owner decision October 12, 2026: Jo may see
all of Isaac's trade data; still never credentials, account numbers, internal
IDs, fill keys, raw emails, images or audio). The publisher also reads two
additive views from [check_scope.py](../../deploy/check_scope.py)
(`pretrade_position_source`: open non-Webull trades with size, entry, strike,
expiration, account name/type; `pretrade_capture_source`: newest 200 captures
with setup, wording, note, transcript, latest added note, linked/not-taken) and
writes a content-addressed context file beside the history file. Jo's tools
(`check:read`): `position_check(ticker?, stop?)` returns each open position
with time held, live underlying, stop distance and how similar closed trades
went after entry (win rate, median best/worst move, giveback, hold time), with
no verdict and no invented option P&L; `get_notes(ticker?)` returns recent
captures. `check_control.py upgrade --approve-sql <sha>` applies the reviewed
`context-views.sql` once (skips when both views exist, refuses a half state)
before swapping the runtime. Positions are as fresh as the 10-minute publish.

## Acceptance

During a regular session, Isaac asks Jo for at least three real checks from his
phone. Each answer arrives within the speed budget, cites live timestamps and a
history card consistent with `get_fill_contexts`/`get_trade_path_metrics` for
the same filters, and reopens unchanged in TradeJournal after reload and service
restart. A stale-data or out-of-session check returns `insufficient_data`.
Isaac records whether the answer was useful. Built, activated, observed and
accepted are recorded separately with dates; none implies a trading edge.
