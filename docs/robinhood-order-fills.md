# Fills from Robinhood's order history

The journal learns of a trade from Robinhood's order history within about a minute, instead of only when the fill
email arrives, without ever counting a fill twice. This note says what it does, why it is built this way, how to run it
in shadow first, how to read the reconciliation, and how to switch it on and off. The read connection it uses (and its
guard) is in [Robinhood read-only feed](robinhood-read-feed.md); the binding rules are in
[Domain rules § Fills from Robinhood's order history](agent/domain-rules.md#fills-from-robinhoods-order-history).

## What it does

About once a minute in market hours (every 15 minutes otherwise), one read at a time and at most 40 calls, the app
reads every account's option and stock orders created in the last four days (`get_option_orders`,
`get_equity_orders`: two read tools added to the read-only allowlist for this). Each execution Robinhood reports (its
own id, price, quantity, time, and for options strike, call or put and expiry) is recorded once in
`robinhood_execution`. Then each order is paired with the journal's fills and the outcome recorded in
`robinhood_reconciliation`:

| Outcome | Meaning |
|---|---|
| **Matched** | The journal has this order's fill (from its email, a manual entry or a `csvfix` backfill). |
| **Waiting for email** (`pending`) | Seen on Robinhood; its email is not due yet (30 minutes), or the order is still working (partly filled). |
| **Robinhood only** (`order_only`) | No fill in the journal: no email came within 30 minutes, a recurring buy (which never emails), or a two-leg order (a roll, left to its email). |
| **Email only** (`email_only`) | An email fill no order in the read window explains. An order placed before the window (a good-till-cancelled order) can show here. |
| **Mismatch** | The journal's fill and the order differ in quantity or price beyond the email's rounding, or a fill written from Robinhood also arrived from another source. Both versions are listed. Never fixed by itself. |

## The design, and why

The fill email stays the journal's record. An order-history execution is a **provisional** fact: it is recorded and
paired, and it never becomes a fill, never reaches FIFO, trades, P&L, alerts or the companion, **except where no email
will ever come**. Today that is one case: a recurring stock buy (`placed_agent: "recurring"`), which Robinhood never
emails. Switched on, such an order, once filled and with no fill already in the journal for it, is written as one fill
(source **Robinhood** on the Fills page; `raw_email_id` `robinhood:<order id>`, a fixed id from the order) and the
trades are rebuilt in the same transaction.

Why not write every execution at once and let the email confirm it? Because the only way to recognise the email
afterwards is a match on account, contract, side, quantity, price and time (the email carries no execution id). If
that match ever failed (a time off by more than the window, a rounding beyond tolerance, an account's last four digits
that differ between the two), the email would become a second fill and FIFO would carry a phantom position. With
provisional rows a failed match costs nothing: it is listed, and the journal is exactly as the emails make it.
Shadow mode measures that match rate on Isaac's real trading before anything wider is trusted.

How the two are recognised as the same fill (one email is one order; an order may have several executions):

- **Same order:** same account (last four digits), stock or option, ticker, buy or sell, and for options the same
  strike, call or put and expiry.
- **Quantity:** the email's quantity equals the sum of the order's executions exactly.
- **Price:** the email's average (shown to the cent) within half a cent a share of the executions' volume-weighted
  average ($0.60 a contract for options). Beyond that it is a mismatch.
- **Time:** the email's minute within five minutes of the order's first and last executions. A manual fill (the July
  backfill's `csvfix` convention has rough times) only needs the same New York day.
- **Several executions of one order** (a fractional-share sale fills as whole and fractional parts): summed into one
  order, paired with its one email.
- **A partial fill:** a working order (`partially_filled`) is only "waiting"; it is paired once Robinhood says it is
  done. Partial-fill emails are skipped by the email import (they report running totals), so the final email pairs
  with the whole order.
- **Two identical trades seconds apart:** two orders, two emails; each order takes the closest unpaired email, one to
  one. They are interchangeable, so the journal is the same whichever pairs with which. A pair, once made, is kept.
- **A slight difference** within the email's rounding pairs (the journal keeps the email's numbers); a larger one, or
  a different quantity, is a mismatch with both versions; the journal keeps the email's fill.

Which wins: the email, always, for anything that emails. For a recurring buy written from the order history, an email
that arrives anyway is not imported as a second fill: it is recorded on the order's row (agreeing: noted; differing: a
mismatch for Isaac to correct by hand). A manual entry added later for an order already written is listed as a
possible duplicate. Nothing is ever deleted or rewritten by this feature.

Expirations, assignments, exercises and rolls are untouched: they are not orders (or, for a roll, a two-leg order this
feature does not pair), so the journal keeps closing expired options and resolving rolls from their email exactly as
before. Index options such as SPXW also never email, but their order shape has not been observed, so they are listed as
Robinhood only and not written; the `csvfix` backfill route stays the way to add them for now.

## Switches

`ROBINHOOD_FILLS_ENABLED` in `/etc/tradejournal/backend.env`, read at startup (restart the API after changing it):

- `false` or absent (default): nothing runs, no call is made.
- `shadow`: reads, records and reconciles; writes no fill. A recurring buy shows **Would be written (shadow)**.
- `true`: the same, and writes recurring buys.

Either needs the read feed on (`ROBINHOOD_READ_ENABLED=true` and a usable sign-in); while the feed is off or signed out
each pass does nothing. The desk's "New · not in the journal yet" marker reads **New · fill seen on Robinhood, email not
in yet** while a bought position's order is waiting for its email, and goes away, as before, once its fill is in the
journal by either route.

## Shadow first: what to look at

Run `shadow` for a week of normal trading, then open **Fills** and read the **Robinhood order history** section (or
`GET /fills/robinhood/reconciliation?days=7`, owner only):

1. **Matched should be nearly everything.** Every option and stock trade that emailed should be Matched within about
   30 minutes. Each Robinhood only (not a recurring buy) or Email only is a pairing that failed: note which.
2. **Mismatch should be empty.** Any row shows both versions; it means the email parser and Robinhood disagree, or the
   pairing rules are wrong for that case.
3. **Recurring buys** should appear once each as **Would be written (shadow)**, with the right shares and price, and
   none of them should already be a manual fill (if one is, it shows as Matched against it instead).
4. **The account labels** should read Roth IRA ••8267 (and Individual ••1113): if Robinhood's last four digits for an
   account differ from the journal's, nothing in that account will match. That is the first thing a real read proves.

Switch to `true` only when 1 to 4 hold. Off and shadow leave fills, trades and P&L byte-for-byte as they were.

## Switch it off

Set `ROBINHOOD_FILLS_ENABLED=false` (or remove it) and restart the API. Fills already written from the order history
stay (a resync keeps them, as it keeps manual fills: no email will re-import them); the two tables stay as a record.

## What has not been proven

Built against the fake connection with the shapes observed on 2026-11-12. Not yet seen live: how far Robinhood
paginates the order history and whether `created_at_gte` is honoured as sent (each kind reads at most five pages; a
kind that runs out of pages is not judged for Email only), the exact minute an email quotes relative to the
executions (the five-minute window), whether a partly filled then cancelled order sends an email, multi-leg orders,
corrections and busts, and that Robinhood's account last four digits equal the journal's. Shadow mode is how each of
these is proven on the real account.
