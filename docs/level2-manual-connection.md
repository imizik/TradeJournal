# Level 2 manual connection lab

The owner `/level2-lab` page has two separate sections: a manually started
US.NVDA moomoo session that runs until stopped, and the original synthetic
replay. Charts adds the same session in its dock and a memory-only liquidity
heatmap behind the candles, for any US stock or ETF ticker, one at a time.
Tradier/Alpaca feeds and saved metrics are
unchanged. The provider book is an inspection display, not a validated live
trading feed.

## Isolation and lifecycle

`backend/scripts/moomoo_lab_server.py` is a standalone FastAPI service on
127.0.0.1:8196. It is not imported by the journal app and has no database,
startup subscription, timer, recording or ML pipeline. An explicitly enabled
production systemd unit can host the same passive bridge.
Only an authenticated POST starts provider work. GET status never reads
credentials or contacts moomoo. One process permits one active session.

The server reuses the secured AppKey and Ed25519 private key and the
existing diagnostic signature implementation. Credentials remain outside Git
and the browser. A separate ephemeral bearer token protects the loopback bridge.
The Next route is disabled by default and refuses assistant profiles. Local
development accepts only its loopback HTTP origin. Explicit production setup
pins one private HTTPS Tailscale origin and Host; it accepts only a same-origin
POST with no arguments or body. Authenticated owner profiles also require an
owner session. The private legacy entrance retains owner-restricted Tailscale
access without an additional login; Host/Origin checks are not identity proof.
It forwards to a fixed loopback endpoint without browser cookies or credentials.
No provider URL or duration can be supplied by the browser. Its only argument
is one `symbol` query parameter on the POST, a plain US ticker matching
`^[A-Z]{1,5}(\.[A-Z])?$` (BRK.B style classes included). The Next route and the
bridge each refuse anything else (other or repeated parameters, lowercase,
options, `US.` prefixes) before forwarding or reading credentials. The bridge
subscribes to `US.<ticker>` and accepts only pushes for that code. Without the
parameter it streams NVDA, which the lab page uses.

Each connection authenticates before subscribing separately to quote,
order_book and ticker. It returns each acknowledgment and a final sanitized
summary. The session runs until the browser stops it. Every four minutes it
sends the documented in-session AppKey `refresh` (a fresh signature, timestamp
and nonce over the auth layout); subscriptions continue without being resent.
A refused refresh, or none acknowledged within 30 seconds, ends the session
(`refresh_failed`), well inside the provider's ten-minute disconnect limit.
The bridge's own eight-hour ceiling ends a forgotten session; the client and
proxy backstop sits a minute above it. There are no automatic retries or
reconnects; Connect starts a new session after one ends.

Stop, leaving the page and the backstop abort the request. On the lab page,
hiding the tab also stops it. On Charts the session belongs to the page so the
heatmap keeps collecting while the dock is closed, another dock tab or symbol is
shown, or the page is in the background; the status strip's **Stop** (or the
dock) ends it. The provider cleanup attempts unsubscribe and closes its socket.
An unconfirmed unsubscribe or close remains distinct in the final diagnostic
report. A cancelled session's report is not returned to the browser, so after
Stop only the socket closure is observable, not the unsubscribe acknowledgment.

The service retains one latest book per book kind (ARCA-labelled or other
market-maker IDs), replacing it rather than storing a series, so the frequent
book cannot starve the other. Book delivery is coalesced to at most four
updates per second per kind. A quiet stream sends a `keepalive` line every 30
seconds so the Next proxy's default five-minute body timeout never ends a live
session; the browser ignores it. After Stop, the bridge holds the session until
its unsubscribe finishes, so an immediate Connect is refused with "still
closing" for a few seconds. The final summary
contains bounded first/last diagnostic samples, total received counts and
refresh counts. Reload starts without an active provider session. The lab's
own heatmap uses invented replay data only.

## Charts dock panel and heatmap

The owner's Charts dock has an optional **Level 2** tab (a phone reaches it from
the More menu as a sheet). It follows the main chart's symbol: a US stock or ETF
ticker shows the session (`LiveDepthSession`, compact layout) and the heatmap
controls; anything else (an option, an index) says so and makes no request.
One ticker streams at a time: while one runs, another ticker's panel only
offers to stop it, and Connect then starts the ticker on screen. Whether the
account's depth access covers a ticker shows in its subscription result.
Assistants get no tab, and a saved Level 2 tab restores as the watchlist for
them. The service status is checked only once the tab has been shown; nothing
reaches the provider before Connect. Only the dock's open/tab choice is stored
on the device; no depth data is. Browser checks use synthetic responses only.

The heatmap (`frontend/lib/depthHeatmap.ts`) draws behind the main chart's
candles for the ticker shown while **Heatmap behind the … candles** is on. Each
ticker connected on this visit keeps its own heatmap, so checking another
symbol does not discard an earlier one. It keeps 2-second columns for at most
four hours per ticker, in the page's memory only; leaving Charts or
reloading starts empty. Each update is placed at its own provider source time.
An update without a source time, or with an estimated age at receipt outside
0–2 seconds, is left out and counted. A side missing from an update adds
nothing, so older levels are never carried forward. A column averages the
updates that fell in it, and a gap with no updates stays blank, which is not
zero. The provider alternates two books on this subscription, one with ARCA
MPIDs (one row per price) and one with other market-maker IDs (NSDQ, NASD,
ETMM; sometimes several rows per price). They are never merged; the dock picks
which one is drawn, ARCA-labelled by default. Brightness is relative to the
95th-percentile size in view (square root). It shows where displayed size sat,
not consolidated or executable liquidity, and no spread/imbalance signal is
derived from it.

## Depth recorder

`backend/scripts/moomoo_depth_recorder.py` is an opt-in always-on service
(`tradejournal-depth-recorder.service`) for a short watchlist, by default SPY, MU,
NBIS, SNDK and NVDA (`TJ_DEPTH_TICKERS` in `/etc/tradejournal/depth-recorder.env`,
at most 20 plain tickers). From 04:00 to 20:00 New York on weekdays it holds one
provider connection with the same service account, credentials and in-session
auth refresh as the bridge, and subscribes order_book and ticker for every
watched ticker. Holidays are not known to it; such a session receives nothing.

It writes one gzip JSON-lines file per ticker per day under
`/var/lib/tradejournal-depth/YYYY-MM-DD/`:

- `{"t":"b"}` book lines: every 2 seconds, the latest update of each book kind
  (`arca` or `mpid`) that changed in that window, with its source time and
  estimated age at receipt. Books are never merged; a missing side stays empty
  and nothing is carried forward. A window without an update writes nothing.
- `{"t":"x"}` trade lines: every print with price, volume, provider direction
  (`BUY`, `SELL`, `NEUTRAL`, else null), sequence and type. The provider does not
  document whether direction is the aggressor side.

It never reads the journal, its database or any R2 credential. Each flush
appends one complete gzip member in a single write, and a file is cut back to
its last complete member before the first append after a restart, so a crash
loses at most that flush. SIGTERM flushes and unsubscribes before exit. Below
2 GB of free disk it stops writing and says so in `status.json`. Until an
uploader has run it keeps 14 local days; after that it never deletes a day,
and only the uploader removes days R2 confirmed. A failed connection reconnects
with a back-off from 15 seconds to 5 minutes, starting over after a connection
that recorded; provider and credential text is never logged. The phone alerts
report a failed recorder or upload, and a disabled upload timer.

`backend/scripts/depth_upload.py` (`tradejournal-depth-upload.timer`, 20:30 New
York) PUTs each finished day to `depth/v1/<TICKER>/<YYYY>/<YYYY-MM-DD>.jsonl.gz`
in a private R2 bucket of its own, signs with SigV4, confirms the stored size,
marks the day uploaded and deletes uploaded local days older than three days.
It uses a bucket-scoped token in `/etc/tradejournal/depth-r2.env`, never the
offsite backup's. The recorder never loads that token, but the uploader runs as
the same `tradejournal-moomoo` user, so a compromised provider-facing process of
that user could read it during the nightly run. The token reaches only the depth
bucket, never the backups.

Recording is the owner's decision (2026-10-12): private recording for personal
use, with the rights questions in the
[permissions audit](moomoo-depth-permissions-rights-audit.md) left unasked.

A live minute on 2026-10-12 after hours (18:03 ET, five tickers) wrote 14–17 KB
per ticker: 60/60-entry books in both kinds (SPY asks 31–34 after hours) and
56–246 trades, about three quarters marked NEUTRAL. Expect roughly 25 MB per
ticker per trading day until a full regular session is measured. Nothing here
draws the recorded data yet; reading it into Charts is the next step.

## Order flow on Charts: liquidity levels, depth profile, heatmap

For a ticker the recorder watches, the owner's main chart reads the recorder's
data with no Connect, about five seconds behind live (the recorder appends every
five seconds), through `GET /api/level2-lab/depth` and the bridge's loopback
`/depth`. The bridge reads only today's local day files
(`backend/scripts/depth_history.py`, one complete gzip member at a time, so a
poll costs only what was appended) and never credentials or the provider. The
browser polls every 10 seconds (`frontend/components/level2/useRecordedDepth.ts`).

Three layers, chosen in the Level 2 dock and remembered on the device
(`tradejournal.charts.orderflow.v1`); the book kind is ARCA-labelled by default:

- **Liquidity levels** (on by default): at most three per side. Over the last
  15 minutes of 10-second buckets, a price is a wall when its mean displayed size
  is at least 8% of that side's mean total depth and 4x its median level, it
  showed in 60% of the buckets whose displayed range covered it, and it lies
  inside the latest book (a level price has traded through is history, not a
  wall). Each draws as a dotted segment from when it began resting to now, with a
  size and age tag ("9.0k · 11m") at the segment's start, away from the newest
  candles, and a colored price-axis tag. A wall whose size dropped below half the
  bar is shown grey as pulled for three minutes. Overlapping tags are left out.
  When the recorder is not receiving (after 20:00, or a dropped feed), walls
  stay faint, end at the last update and are tagged "not live".
- **Depth profile** (on by default): the latest book as faint bars in the
  price-axis gutter, never over candles; dimmed when the recorder is not
  receiving.
- **Heatmap** (opt-in): recorded 10-second columns from the last four hours,
  then everything since the newest column held (at least two minutes), so a
  sleep or outage is backfilled; drawn only on 1m–5m candles. The bridge
  serializes reads and queries of a day file, so overlapping requests never
  double-count its read position.

A ticker the recorder does not watch says so; its Connect session still drives
the heatmap and profile, but liquidity levels need the recorder. Walls are
provider-displayed size in one book kind, not consolidated or executable
liquidity, and not predictions. On 2026-10-12 after hours the rules found, for
example, NVDA bid walls at 224.00 and 224.25 and SNDK at 1450.00, all inside the
book; the "other market-maker" SNDK book was crossed at times, one reason ARCA
is the default.

## Fields and clocks

- Price and volume retain provider numeric precision. Volume is labeled provider
  units until actual US size scaling has been verified. Order counts are optional;
  unavailable counts remain unavailable, and a returned zero remains zero.
- Exchange labels are allowlisted. Missing venue remains unavailable. MPID is a
  separate maker/broker identifier and does not establish exchange coverage.
- Each update is displayed independently. Missing sides stay empty; there is no
  undocumented delta merging or borrowing levels from an older update.
- Source time is separate from local receive time. Zero/missing source time means
  unknown freshness. Estimated age is a midpoint clock estimate **at receipt**,
  not current freshness, one-way measured latency or guaranteed provider latency.
- The display remains inspection-only. No live spread, imbalance or trading
  signal calculations are added before unit/clock validation.
- Returned depth, successful authentication and subscriptions do not establish
  TotalView/ArcaBook rights, consolidated depth, raw order identity or ML rights.
  A session with zero messages does not prove market-hours delivery.

## Local use, when a manual provider test is approved

The following manual command runs the bridge locally. Run from this checkout's root in
an otherwise unused terminal. Keep the ephemeral token in that shell; do not
print it or put it in `.env`, a command argument, screenshots or a report.

```bash
export TJ_MOOMOO_LAB_ENABLED=true
export TJ_MOOMOO_LAB_TOKEN="$(backend/.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
(cd backend && exec .venv/bin/python -m scripts.moomoo_lab_server) &
TJ_LAB_BRIDGE_PID=$!
trap 'kill "$TJ_LAB_BRIDGE_PID" 2>/dev/null; unset TJ_MOOMOO_LAB_TOKEN TJ_MOOMOO_LAB_ENABLED' EXIT INT TERM
(cd frontend && npm run dev -- --hostname 127.0.0.1)
```

Open the frontend on its local HTTP origin (`http://127.0.0.1:3000` by default),
then **Level 2 lab → Connect**. The command starts a passive
bridge; it subscribes only after that click. Stop the frontend with Ctrl+C and
exit that terminal to stop the bridge. Use one bridge process; port 8196 is
fixed. Both services must bind exclusively to loopback. Do not omit the frontend
hostname argument: a local URL or Origin header alone cannot authenticate the
network peer. Production uses the separately provisioned private configuration below.
If credentials/whitelist are unavailable, inspect the sanitized status; no
alternative signing formats or entitlement upgrades are attempted.

## Production connection

The owner authorized a VPS-hosted passive bridge. Provider credentials remain
outside the release, under `/etc/tradejournal/moomoo/`, mode 0700, root owned; the two
credential files are root-private mode 0600. systemd `LoadCredential` supplies
read-only private runtime copies to the dedicated `tradejournal-moomoo` user.
The bridge reads `CREDENTIALS_DIRECTORY`, preserving root-only traversal of
`/etc/tradejournal`; local tools may use `TJ_MOOMOO_CREDENTIAL_DIR` without
altering the original standalone diagnostic's local credential path. The bridge does not load the
journal environment or database. A shared token stays in root-private systemd
environment files, never in browser configuration.

`tradejournal-moomoo.service` binds only 127.0.0.1:8196. It is opt-in: ordinary
releases do not enable it. Once explicitly enabled, deployment stops it before
switching releases, restarts it against the new release, and stops/removes it
when rolling back to code without the unit. Restart never resumes a session.
The owner frontend reads optional `moomoo-frontend.env`; the assistant frontend
does not. Production requires an exact configured HTTPS `.ts.net` origin, the
matching Host and POST Origin. Client forwarded headers confer no authority.
The existing owner-only Tailscale restriction and loopback frontend binding
remain essential. No Funnel, public route or private-API exposure is added.

Provision and activation instructions are in
[the deployment runbook](../deploy/README.md#manual-moomoo-level-2-connection).
Activation and provider authentication are separate evidence from fixture tests.
Changing the source IP may require adding the VPS public egress IP to the
AppKey whitelist. Do not disable the whitelist or buy access to resolve a refusal.

## Market-hours observation — October 12, 2026

One production dock session (release `f577105`, which includes the VPS
connection and the null-side fix), 12:36–12:46 ET, NVDA, then three short
lifecycle sessions. This was the 30-second build, before the refresh and
heatmap changes above.

The same day, the refreshed `stream_probe` ran once on the VPS under the bridge's
service account for 540 seconds with a 240-second refresh: both refreshes were
acknowledged (correlated by id), delivery continued throughout (3,720 order_book,
2,133 quote and 512 ticker messages), and unsubscribe succeeded with the socket
closed. A multi-hour session through the deployed proxy is not yet observed.

Also that day, 20-second checks of the ticker-parameter build: US.AAPL and
US.SPY each authenticated and had all three subscriptions acknowledged, then
delivered depth (AAPL 20 order_book messages, 60 bid/60 ask entries, MPIDs ARCA,
NASD, NSDQ; SPY 42 messages, books of 35–60 entries per side, MPIDs ARCA, IMCC,
NSDQ). Unsubscribe succeeded and both sockets closed. This shows these two
tickers stream, not coverage for every symbol or any named depth product.

- Opening, restoring and reloading the dock made only GET status checks; the
  bridge held no provider socket until Connect.
- Authentication and the quote, order_book and ticker subscriptions each
  succeeded separately (code 0). Two 30-second sessions then delivered 114/110
  quote, 212/214 order_book and 30/32 ticker messages; the book visibly changed.
- All 114 displayed (coalesced) updates in one session had 60 bid and 60 ask
  entries. The exchange field was never supplied. 105 updates carried ARCA
  MPIDs with one row per price; 9 carried NSDQ/NASD/ETMM with some repeated
  prices. Source time was present on every update; estimated age at receipt
  ranged 10–272 ms (median 101, 90th percentile 190). That is a clock estimate
  at receipt, not exchange freshness, and none of this establishes TotalView,
  ArcaBook or consolidated coverage.
- No null-sided update occurred, so the null-side handling was not exercised live.
- Natural completion returned the summary (unsubscribe success, closed) and the
  provider socket closed at the end. Stop and closing the dock each closed the
  socket within about half a second; reopening was idle. A cancelled session's
  unsubscribe acknowledgment is not observable (see above).
- The bridge wrote no files. Only connection-state timing was kept.

## Verification

`backend/tests/test_moomoo_lab.py` exercises bounded parsing, precision,
credential/error redaction, token/body boundaries, coalescing, single-session
exclusion and cancellation cleanup with invented sockets. Existing diagnostic
signature vectors and authentication/refusal tests remain in
`backend/tests/test_moomoo_diagnostic.py`.

The frontend's `level2-live.spec.ts` uses invented HTTP stream fixtures for the
manual flow, status/failure paths and cleanup on desktop and phone;
`level2-route.spec.ts` exercises the actual proxy function with a mocked local
service. The original replay browser tests remain. These checks do not establish
live delivery, real entitlements or market-hours latency. No real provider or
account calls are required for these tests.

Official references consulted:
[Chinese AppKey authentication and refresh](https://open.moomoo.com/zh-cn/api/quote/push/auth),
[English authentication](https://open.moomoo.com/api/quote/push/auth),
[subscription protocol](https://open.moomoo.com/zh-cn/api/quote/push/subscribe),
[push field format](https://open.moomoo.com/zh-cn/api/quote/push/data-format).
The English subscription/format pages timed out during this implementation;
the Chinese official pages supplied the same action/acknowledgment structure.
Refresh follows the official AppKey refresh frame and its five-minute
recommendation and ten-minute limit. The optional five-minute re-subscription
is not sent, because the auth page states that a successful refresh keeps
subscriptions. Keepalive uses the WebSocket library's protocol pings, as the
[keepalive page](https://open.moomoo.com/zh-cn/api/quote/push/heartbeat) requires.
