# Level 2 manual connection lab

The owner `/level2-lab` page now has two separate sections: a manually started,
30-second US.NVDA moomoo session and the original synthetic replay. Charts,
Tradier/Alpaca feeds and saved metrics are unchanged. The provider book is an
inspection display, not a validated live trading feed.

## Isolation and lifecycle

`backend/scripts/moomoo_lab_server.py` is a standalone FastAPI service on
127.0.0.1:8196. It is not imported by the journal app and has no database,
startup subscription, deployment unit, timer, recording or ML pipeline.
Only an authenticated POST starts provider work. GET status never reads
credentials or contacts moomoo. One process permits one active session.

The server reuses the secured local AppKey and Ed25519 private key and the
existing diagnostic signature implementation. Credentials remain outside Git
and the browser. A separate ephemeral bearer token protects the loopback bridge.
The Next route is disabled by default, refuses assistant profiles and remote
origins, and accepts only a same-origin local POST with no arguments or body.
It forwards to a fixed loopback endpoint without browser cookies or credentials.
No provider URL, symbol or duration can be supplied by the browser.

Each connection authenticates before subscribing separately to quote,
order_book and ticker. It returns each acknowledgment and a final sanitized
summary. There are no automatic retries or reconnects. Stop, hiding the tab,
leaving the page and the 40-second client/proxy timeout abort the request.
The provider cleanup attempts unsubscribe and closes its socket. An unconfirmed
unsubscribe or close remains distinct in the final diagnostic report. The
provider's own 30-second cap applies even if browser cancellation is delayed.

The service retains one latest book, replacing it rather than storing a series.
Book delivery is coalesced to at most four updates per second; the final summary
contains bounded first/last diagnostic samples and total received counts.
The live section does not create a heatmap/history. The existing heatmap uses
invented replay data only. Reload starts without an active provider session.

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

Market-hours testing remains deferred. The following is a future manual command,
not a test run as part of this implementation. Run from this checkout's root in
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
then **Level 2 lab → Connect for 30 seconds**. The command starts a passive
bridge; it subscribes only after that click. Stop the frontend with Ctrl+C and
exit that terminal to stop the bridge. Use one bridge process; port 8196 is
fixed. Both services must bind exclusively to loopback. Do not omit the frontend
hostname argument: a local URL or Origin header alone cannot authenticate the
network peer. Do not configure these flags in production or deployment files.
If credentials/whitelist are unavailable, inspect the sanitized status; no
alternative signing formats or entitlement upgrades are attempted.

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
The session hard cap is below the recommended five-minute refresh and
re-subscription cycle and ten-minute refresh limit. Extending connection lifetime
requires verified refresh handling; this code deliberately does not expose a
long-lived mode.
