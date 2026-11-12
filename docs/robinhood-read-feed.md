# Robinhood read-only feed

The desk's book and account chips can come live from Robinhood instead of waiting for each fill email. This note says
what the feed reads, what it can never do and why, where the sign-in lives, how Isaac signs in and switches it on, and
how to switch it off and revoke it. What the desk shows is in [Copilot Lab § The desk](copilot-lab.md#the-desk).

## What it reads

Robinhood's official agent connection (an MCP server over streamable HTTP), through seven read tools only:
`get_accounts`, `get_portfolio`, `get_option_positions`, `get_option_instruments`, `get_option_quotes`,
`get_equity_positions` and `get_equity_quotes`. From them the desk gets, for each account shown: its label and number
masked to the last four (`••8267`), total value, cash and buying power; and each open position: options with strike,
call or put, expiry, quantity, Robinhood's average price, mark, bid, ask, the day's change and the Greeks; stocks with
quantity, average cost and quote; each with unrealized P&L in dollars and percent from Robinhood's own average price and
mark. A missing or odd field shows as unavailable, never as zero.

Accounts shown: those named in `ROBINHOOD_ACCOUNTS` (default `Roth IRA,MCP`; a label, a type such as `ira_roth`, or the
last four digits), plus any other account only while it holds something.

Refresh: about once a minute in market hours (9:25 to 16:15 New York on weekdays), every 15 minutes otherwise, only
when the desk's thread read asks (an open desk, or the evening review's one read of it), one read at a time and at most 40 calls each; the **live from Robinhood · as of** line on the book
reads again on a tap (no more than once every 15 seconds). If a read fails the last snapshot stays; after three missed
refreshes it is **stale** and the book shows the journal again.

## What it can never do, and why

Robinhood's connection has one sign-in scope and no read-only version: the same sign-in can place, cancel and exercise
orders (29 of its 95 tools change or trade something), and the MCP account can be traded through it. Robinhood's trade
approvals setting is off and not yet available on this account, so nothing on Robinhood's side would stop an order.
The app's own code is the only guard:

- `backend/app/engine/robinhood_read.py` is the one module that talks to Robinhood. It has a hard-coded allowlist of the
  seven read tools. The one function that builds a tool call refuses any other name before any network I/O, and every
  message on its way out is checked again: only the session handshake and an allowlisted read reach the connection,
  and only a sign-in renewal reaches the token endpoint.
- There is no "call any tool" entry point. No tool name comes from a request, the environment, configuration or a
  model. The copilot has no Robinhood tool.
- The only new route, `POST /copilot/desk/robinhood/refresh`, takes no input.
- Tests (`backend/tests/test_robinhood_read.py`) fail if a write-looking name is added to the allowlist, if any
  changing or trading tool is not refused, or if anything else in the repository names the endpoint or builds a tool call.
- Display only: nothing from the feed is written to the journal (fills, trades, P&L, FIFO stay as the emails make them).
  Account numbers leave the server masked to the last four (to the desk; never to the copilot). Robinhood's `guide`
  text (its instructions to an AI) and every other string from Robinhood are treated as data: dropped or shown as data,
  never sent to a model. Only numbers, tickers and fixed words reach the copilot (below).

Adding a tool to the allowlist is a consequential, user-gated change.

## What the copilot sees

The copilot answers from the same numbers the book shows, and nothing else from Robinhood. Exactly what its owner
context carries is in [Copilot Lab § Owner context](copilot-lab.md#owner-context); in short:

- **Only the cached snapshot.** `backend/app/ai/copilot_book.py` (`live_book`) reads the snapshot the desk's last
  refresh left (`feed.snapshot(kick=False)`) and joins it with the desk's own `match`. A copilot turn, `get_positions`
  or a trade review never starts a Robinhood read, and the copilot still has no Robinhood tool. A test fails if
  `copilot_book` uses anything of the feed but `feed.snapshot`, `match` and `contract_key`.
- **Fresh:** each journal position Robinhood shows takes its quantity, mark, bid, ask, day change, unrealized P&L in
  dollars and percent, IV and Greeks, marked `live: "Robinhood"` under one `as_of` (the snapshot's); the journal keeps
  its plan, alerts, decisions, hold time and history. A position only Robinhood shows is added with no plan and the
  note that its fill has not reached the journal. A journal position Robinhood does not show stays as the journal has
  it. `get_positions` and the trade review's current mark say the same and name their source.
- **Off:** the copilot's context is exactly what it was without the feed. **Signed out, expired, loading, unavailable
  or stale:** the rows are the journal's own and one line says the live numbers are unavailable and why.
- **What passes:** numbers, tickers (letters, digits and a dot) and the fixed words call, put, long and short. The
  account is the journal's own label for the account with those last four digits (else "Robinhood account"); no digit
  of an account number, masked or not, no Robinhood account name, id or text. A position with an odd ticker, side or
  expiry is left out. Account totals (value, cash, buying power) are not given to the copilot.
- Tests: `backend/tests/test_copilot_robinhood.py`.

## Where the sign-in lives

One file, never in the database, never in a log line, an API response, an error or the browser:
`/var/lib/tradejournal/robinhood/robinhood-token.json` on the VPS (outside the backed-up `data` and `oauth` folders:
it is re-made by signing in again). It must be owned by `tradejournal` with mode 0600; the app refuses a file anyone
else can read. It holds the access token, the renewal token, its expiry and Robinhood's public client id.

The sign-in lasts about five days. The app renews it on its last day and writes the new one back in place
atomically. If renewal fails, or Robinhood refuses the sign-in, the feed shows **Robinhood sign-in expired** and makes
no further call until a new file is put in place; nothing retries in a loop.

## Isaac: sign in and switch it on

These steps are yours to run. Nobody else needs to see the sign-in.

1. On your Mac, from the TradeJournal folder (Python 3, nothing to install):

   ```bash
   python3 backend/scripts/robinhood_signin.py ~/robinhood-token.json
   ```

   Robinhood's sign-in opens in your browser. When it says Done, the terminal says how long the sign-in lasts. It prints
   no token and calls no Robinhood tool.

2. Put it on the server (one command; it asks for your sudo password), then delete the Mac copy:

   ```bash
   scp ~/robinhood-token.json ubuntu@100.121.251.15:/tmp/rh-token.json && ssh -t ubuntu@100.121.251.15 'sudo install -d -o tradejournal -g tradejournal -m 700 /var/lib/tradejournal/robinhood && sudo install -o tradejournal -g tradejournal -m 600 /tmp/rh-token.json /var/lib/tradejournal/robinhood/robinhood-token.json && rm /tmp/rh-token.json'
   ```

   ```bash
   rm ~/robinhood-token.json
   ```

3. Switch it on: add these lines to `/etc/tradejournal/backend.env` and restart the API.

   ```
   ROBINHOOD_READ_ENABLED=true
   ROBINHOOD_TOKEN_FILE=/var/lib/tradejournal/robinhood/robinhood-token.json
   ROBINHOOD_ACCOUNTS=Roth IRA,MCP
   ```

   Within a minute the desk shows the account chips and **live from Robinhood · as of HH:MM**.

Every five days or so, or whenever the desk says **sign-in expired**, repeat steps 1 and 2. No restart is needed: the
app picks up the new file.

## Switch it off and revoke

- **Off:** set `ROBINHOOD_READ_ENABLED=false` (or remove it) and restart the API. The desk is back to the journal only
  and makes no Robinhood call.
- **Remove the sign-in:** delete `/var/lib/tradejournal/robinhood/robinhood-token.json`.
- **Revoke it at Robinhood:** in the Robinhood app, go to the security settings, find the connected agent app (it
  registers as "Robinhood Trading") and remove its access. That ends both the sign-in and its renewal at once, whatever
  copies exist. (The exact menu was not observed when this was written; it sits with Robinhood's other connected-app
  and security settings.)

## What has not been proven

Built and tested against a fake connection that returns the shapes Isaac's own test observed on 2026-11-11. Not yet
seen live: the exact shape of `get_equity_quotes` (read defensively), how pagination looks on a long position list,
whether `account_number` is all digits (either works; the last four come from `rhs_account_number` when it is), the
sign of a short option's average price (read either way), and whether Robinhood rotates the renewal token (handled).
The first real sign-in proves them, and with them the copilot's live numbers: that Isaac's journal accounts carry the
same last four digits as Robinhood's (else a position matches by contract in any account, and an unmatched account
reads as "Robinhood account"), and that the snapshot's marks agree with what the Robinhood app shows. A single failed renewal (a network blip on the last day) also ends the sign-in by
design: sign in again.
