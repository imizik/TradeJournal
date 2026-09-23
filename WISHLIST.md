# Wish list

What Isaac wants from the journal, in plain language. **This file is the
owner's, not the agents'.** It says what should be true and why it matters, not
how to build it — the how belongs in `docs/agent/` and in the pull request.

`docs/agent/roadmap.md` is a different thing: the engineering foundation
(verification, environments). This file is the trading-side queue.

## How this works

- Items live under **Now**, **Next** or **Someday**. Anyone may reorder them.
- **Before starting anything sizeable, read this file and check what the other
  agent merged recently.** Claude and Codex both work in this repository, and
  have already built two different answers to the same problem on the same day.
- An item is **done when it is deployed and checked on the real thing**, not
  when it is merged. Move it to Done with the date and the PR.
- Small annoyances do not need to be written down first. Say them, fix them,
  ship them.

---

## Now

### Phone polish on the remaining screens
Analytics, Daily Review, Signals, Strategy Lab and Research have not been
looked at on a phone. The dashboard, trades, fills and trade detail have.
**Why:** the phone is now a main way to check the journal during the day.
**Done when:** each reads without sideways scrolling or overlapping text at
iPhone width, and `frontend/e2e/phone.spec.ts` covers them.

### Tell me on my phone when Gmail disconnects
Today a disconnect shows as a banner inside the app, so it is only seen by
opening the journal. **Why:** while Gmail is disconnected no fills import, and
silence looks identical to "no trades yet".
**Done when:** the phone gets a notification within a few minutes of the
listener or Gmail auth failing, and another when it recovers. Needs a decision
on which notification service to use; no trade details in the message.

### Faster refresh while actively trading
An open page notices new fills within about 30 seconds.
**Why:** watching a fill land should feel immediate.
**Done when:** a new fill appears within about 10 seconds while the page is
open, without adding constant database traffic when nothing is happening.

## Next

### Decide what the 5-minute Gmail timer is for
Now that real-time import works, `tradejournal-gmail-sync.timer` still runs 288
times a day and fills the job history.
**Why:** it is a genuine safety net, but at that rate the Sync Center history
is hard to read.
**Done when:** either the interval is longer, or runs that import nothing stop
being recorded — decided deliberately, not left at 5 minutes by accident.

## Someday

### Older Roth cost basis
From earlier notes: fills before October 2025 have a cost-basis gap that needs
an older brokerage export. **Confirm this is still wanted** before acting on it.

---

## Done

- **Real-time Robinhood import** — a fill reaches the journal seconds after the
  email instead of up to five minutes. 2026-09-22, PRs #53, #54.
- **Gmail stays signed in** — the Google app was in Testing, which expired the
  sign-in every 7 days; it is published now and Reconnect works from the phone.
  2026-09-22, PR #55.
- **Phone layout** — the sidebar no longer eats the screen; tables show the
  columns worth reading; home-screen icon. 2026-09-23, PRs #58, #60.
- **Sync Everything on the server** — 08:00 and 17:00 New York, replacing the
  job that only ran when the laptop was awake. 2026-09-22, PR #53.
