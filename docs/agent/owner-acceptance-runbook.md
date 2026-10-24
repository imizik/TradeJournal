# Owner acceptance runbook

Prepared October 24, 2026 from the [Dots delivery board](dots-integration.md#current-delivery-board)
and the code behind each row. These are the checks only Isaac can do: watching a
phone, judging usefulness, approving an activation. Each item takes a few minutes of
owner time; some then wait for the market. Running a step is evidence, not
acceptance: an agent updates the board from what you record, against the linked
contract gate.

Items are ordered by value per minute of your effort, putting first what feeds the
[October 22 end-goal proofs](../product-roadmap.md#end-goal--october-22-2026)
(position follow-through and discovery). The position-alert and Radar proofs
themselves are measured passively (the exit-habits card on the dashboard and the
[Radar](../radar.md) pilot ratings) and need no runbook step.

**Before any item.** Open the app on your phone over Tailscale, as usual. The board's
host state was last checked October 21; if a step's "you should see" doesn't match,
record that and stop. Don't fix it on the spot.

**Recording.** Each item ends with a record line. Paste it into any Claude Code or
Codex session with "record this runbook result"; the agent adds it to the contract's
evidence and moves the board. The app already keeps IDs, times and push outcomes,
so the line only needs what the app can't see: what your phone showed and your
judgment. "ntfy accepted" in the app never proves your phone displayed a push; only
you can confirm that.

**Owner-gated** below means: needs your approval at the VPS. An agent doesn't flip
it on its own, and you shouldn't either without reading the linked activation steps.

| # | Item | Your time | Where | Gate it feeds |
|---|---|---|---|---|
| 1 | Price-watch follow-through, live | ~15 min in one session + wait | Phone; one restart needs the VPS shell | [Conditional plans: activation and acceptance](setup-scanner-contract.md#activation-and-acceptance) |
| 2 | Morning brief, five mornings | ~1 min/morning × 5 | Phone | [Delivery honesty and the morning watchdog](dots-integration.md#delivery-honesty-and-the-morning-watchdog) |
| 3 | Saved advice → journal link/unlink | ~5 min, any time | Phone | [Saved advice links](advisor-pretrade-check-contract.md#saved-advice-links-to-later-journal-activity--october-20-2026) |
| 4 | Missed-read alert + 15-min tolerance | ~2 min decision; the rest waits | Phone; activation is owner-gated (VPS) | [MW-2 scheduled-read reliability](market-watch-design.md#mw-2-implementation-and-activation-boundary) |
| 5 | Selected-stock awareness | ~10 min diagnostic + 1 min later | VPS shell + phone | [Selected-stock awareness](setup-scanner-contract.md#selected-stock-awareness-separate-from-option-eligibility) |
| 6 | Personal follow-ups | ~10 min after activation + wait | Phone; activation is owner-gated (VPS + ChatGPT tasks) | [Personal follow-through](dots-integration.md#personal-follow-through--october-23-2026) |

## 1. Price-watch follow-through, live

**Proves:** Jo can save an exact price watch you agree on, the app monitors it, a
real market move reaches your phone, cancellation sticks, and an API restart doesn't
duplicate anything. This is the "Execute and monitor" leg of the end goal.
**Closes:** the board's conditional price-plan row, Observed and Accepted
(save → trigger → phone → cancel → restart).

**Preconditions**

- Already on since October 21: the conditional-plan switch in the app and in Check
  (VPS state, per the board). Nothing to flip.
- A regular session, at least 30 minutes before close. Jo refuses watches when the
  market is closed, and every watch expires within four hours and by that day's close.
- The ticker is on your scanner list (`/scanner`, the tickers editor). Watches only
  cover those tickers.

**Steps**

1. Open **Morning → Jo's price watches** (`/morning/watches`). The top banner should
   read **Monitor running** with a recent heartbeat and your eligible tickers. If it
   says *Price watches are off* or *Monitor not reporting*, record that and stop.
2. In ChatGPT, ask Jo for an exact long or short watch on one eligible ticker. Give
   the trigger, invalidation, number of confirming one-minute closes (1–3) and an
   expiry. Choose levels the market could plausibly reach before expiry, so you'll
   probably get a trigger, invalidation or expiry push. Jo should first take a fresh
   pre-trade check or use a real stock alert, then save.
3. Jo should say it's saved and pending acknowledgement, not that it's watching yet.
   Within about a minute, refresh the watches screen. The card should go from
   **Saved · not monitored yet** to **Watching**, with a last evaluated bar.
4. Ask Jo for a second, separate watch on any eligible ticker, then ask Jo to cancel
   it. The card should show *Cancellation requested* and then **Cancelled** ("Cancelled
   on request"). Cancellation sends no push.
5. **VPS shell, your call:** while the first watch reads **Watching**, run
   `sudo systemctl restart tradejournal-api.service`. This interrupts level and
   position alerts too while the API restarts. Afterwards, refresh the screen. It
   should either still read **Watching**, or honestly show **Monitoring failed · not
   watched** with "a gap of more than three minutes" if the restart took too long.
   Either is honest. A repeated event or push is a fail.
6. Leave it alone. When the trigger, invalidation or expiry happens, a push titled
   `Jo plan: SYMBOL — triggered` (or `invalidated`, `expired`, `unavailable`) should
   reach your phone. Open the card: **History** shows each state once, and **Phone
   alerts** shows one *Sent to ntfy* per event.
7. Optional: ask Jo something it can't watch, such as a ticker not on your scanner
   list. The refusal should appear under **Refused requests**. If Jo refuses but
   nothing is listed there, record it: the Check side of #384 may not be deployed.

**Pass:** steps 3–6 all happened; your phone showed each push the card lists as
sent; History has no duplicate state; the cancelled watch never pushed.
**Fail:** the card never reaches Watching, a push arrived twice, a listed push
never showed on your phone, or Jo claimed it was watching before the card said so.

**Record:** `price-watch: date, ticker, plan state path (e.g. watching → triggered),
push seen on phone yes/no + time, cancel ok yes/no, restart outcome (still watching /
gap → failed / duplicate), refusal listed yes/no/not tried`.

## 2. Morning brief, five mornings

**Proves:** the scheduled brief reaches the journal on time, the watchdog classifies
each morning correctly, and the brief is worth reading. The Radar pilot compares
against the morning brief, so honest ratings here feed that proof.
**Closes:** the five-morning operational acceptance (delivery x/5, watchdog x/5),
and starts the ten-morning usefulness decision
([delivery checkpoints](dots-integration.md#delivery-checkpoints-and-acceptance)).
October 21 counted as 1/5; later mornings aren't recorded on the board.

**Preconditions**

- Already on as of October 21: `JO_MORNING_ALERTS=true` and the dead-man's switch
  (`HEALTHCHECK_PING_URL`) in `/etc/tradejournal/alerts.env`. Confirm on the phone:
  the **Scheduled brief** line on `/morning` should say *Phone watchdog: on*.

**Steps (each exchange morning, after the 09:15 deadline)**

1. Open `/morning`. Tap **Scheduled brief:** to expand it. Note **On time**, **Late**
   or **Missing**, and the *Phone watchdog* line.
2. Read the brief for about five minutes, as you would anyway. Tap **Useful**, **Meh**
   or **Missed something**. The rating is saved in the app. If it missed something,
   say what in the record line.
3. If a morning push arrives (*Jo's morning brief is missing*, *arrived late*,
   *packet wasn't published*…), note the time your phone showed it.

Past mornings: open `/morning?day=YYYY-MM-DD`, or the Daily Review calendar (`/daily`).

**Pass (operational):** the five consecutive exchange mornings each show a state that
matches what happened, and every late or missing morning produced its watchdog notice
within the grace. **Fail:** a missing or late morning with no notice, or *Phone
watchdog: off* or *status unavailable*.

Note: the gate also asks for at least one watchdog push confirmed on your phone. The
watchdog only pushes on a problem, so five clean mornings can't meet that part. Wait
for a real miss rather than forcing one.

**Record:** `morning: date, on time/late/missing, watchdog notice + phone time (or
none), rating, what it missed (if anything)`. Five lines close the operational part.

## 3. Saved advice → journal link/unlink

**Proves:** you can tie Jo's saved advice to what you actually traded afterwards, and
take it back. Nothing is graded or linked automatically.
**Closes:** "real link/unlink acceptance" on the saved-advice row.

**Preconditions**

- Already on since October 20: the journal's read-only check reader. Nothing to flip.
- At least one saved pre-trade check followed by a real trade in the same underlying
  within five days (NBIS from October 19–23 is the motivating case).

**Steps**

1. Open `/advisor-review`. **Pre-trade checks** should list Jo's checks, not *Saved
   advice isn't connected to the journal yet*.
2. Tap a check to expand it. If it has a structured trigger or invalidation, it should
   render without a crash; that's the #365 fix running in production.
3. Under **Journal afterwards → Later activity — review needed**, find the trade you
   actually made. Tap **Link trade**, or **Link fill** for a single fill. It should move
   to **Linked by you**.
4. Tap the contract name to open the trade. The **Saved advice** card should show that
   check with *you linked this trade* (or *one fill*).
5. Go back to the check and tap **Unlink**. It should leave **Linked by you**, and the
   trade page should read *No saved advice linked*. Re-link it if you want to keep the
   link; unlinking keeps the history either way.

**Pass:** steps 1–5 behave as described, and the possible matches make sense: same
symbol, entered after the check, nothing pre-linked. **Fail:** a crash, a link that
doesn't show on the trade page, an unlink that doesn't stick, or an obviously wrong
match (for example, one entered before the check).

**Record:** `advice-links: date, check ticker/date, trade linked, trade page showed it
yes/no, unlink ok yes/no, kept linked yes/no, any odd match`.

## 4. Missed-read alert and the 15-minute tolerance

**Proves:** when Jo misses a scheduled 09:50/11:00/12:30/14:00 market read, your phone
says so, and the "on time" rule reflects your intent.
**Closes:** two items in the market-watch row's remaining boundary: owner confirms the
tolerance, and one missed-read alert plus recovery is observed on the phone.

**Preconditions**

- The opt-in alert merged in #378. The board says it isn't activated, but that was
  never verified on the host. Check on the phone: `/morning/market-reads` shows
  *Phone watchdog: off, so no phone alert is sent for a missing read* while it's off.
- Activation is **owner-gated; needs your approval at the VPS**: set
  `JO_MARKET_READ_ALERTS=true` in `/etc/tradejournal/alerts.env`. It takes effect on
  the alerts timer's next two-minute pass.

**Steps**

1. Decide the tolerance (1 min, phone). Currently a read counts as on time if the Check
   service saved it within 15 minutes of the slot. A read up to 30 minutes after still
   links to the slot, as late. Answer: keep 15, or name another number.
2. Approve or decline activation. If approved, an agent or you sets the flag on the VPS.
   Then `/morning/market-reads` should show *Phone watchdog: on; …* for today.
3. Passive: when a slot is missed, a push titled `Jo's 11:00 AM market read is missing`
   (or the slot's time) should arrive. If a read lands inside the 30-minute window,
   an `…arrived` recovery follows. The session on `/morning/market-reads` lists both
   notices.

**Pass:** a real miss produced exactly one missing push your phone showed, and the
screen's notice matches it. **Fail:** a slot reads **Missing** on the screen with no
push, or a slot that arrived on time was alerted.

Note: the gate asks for a recovery too. A recovery only fires if the late read arrives
within 30 minutes; a read that never comes produces no recovery. Record what happened.

**Record:** `market-read: tolerance decision (keep 15 / N), activation approved yes/no
+ date; later: date, slot, missing push phone time, recovery push yes/no`.

## 5. Selected-stock awareness

**Proves:** a big move in one of your scanner tickers wakes the real Jo task by email,
Jo saves a stock review, and the review reaches your phone. This is the NBIS rebound
coverage gap from October 15, and the closest Dots row to Radar's "noticed early enough".
**Closes:** the stock-awareness row: native email → actual Jo → saved stock review →
phone. The diagnostic proves delivery; a natural alert proves real use. These are
separate pieces of evidence.

**Preconditions**

- On per a read-only check October 20: `STOCK_WATCH_ENABLED=true` in
  `/etc/tradejournal/backend.env`. Its activation date isn't recorded.
- The saved ChatGPT task that matches `FW: TJ Setup:` contains the stock branch
  (`TJ Setup: STOCK`, `stock_alert`, `stock_alert_submit`;
  [branch text](../../deploy/market-watch/jo-stock-task.md)). You can check this on your
  phone by opening the task in ChatGPT. If it's missing, stop. Adding it is a hosted
  task edit that needs your approval.
- There's no app screen for stock reviews. Evidence is the push, Jo's task history and
  the Check ledger.

**Steps: diagnostic (VPS shell, regular hours)**

1. Pick a ticker on your scanner list and a new code, e.g. `STK-1024A`. Codes are
   one-time per day.
2. The contract makes this an explicit owner command that creates one labelled
   invented-data alert and no trade. The contract gives no exact invocation; this one
   mirrors the API unit's user, directory and environment:
   `sudo systemd-run --pipe --wait --uid=tradejournal -p WorkingDirectory=/opt/tradejournal/current/backend -p EnvironmentFile=/etc/tradejournal/backend.env /opt/tradejournal/current/backend/.venv/bin/python stock_watch_owner.py delivery-diagnostic --symbol NBIS --code STK-1024A`.
   It prints the `alert_id` and its expiry (ten minutes).
3. Within the ten minutes: the scanner relay emails `TJ Setup: STOCK NBIS sta_…`, the
   Jo task runs, and a push titled `TJ stock delivery diagnostic: STK-1024A` should
   reach your phone. Don't message Jo to help it along; a typed nudge doesn't count.

**Steps: natural (passive)**

4. During normal sessions, a push titled `Jo stock review: SYMBOL — watch` (or `avoid`)
   may arrive after a real move. When one does, note the time, and whether it was
   useful and early enough to act on.

**Pass (diagnostic):** the labelled push arrived within the ten minutes without any
typed nudge. **Pass (natural):** at least one real review reached your phone and you
can say whether it helped. **Fail:** the command errors, or no push arrives before the
expiry. Record which, and don't retry with the same code.

**Record:** `stock-diagnostic: date, ticker, code, alert_id, push phone time or none`
and later `stock-natural: date, ticker, stance, phone time, useful yes/no, early
enough yes/no`.

## 6. Personal follow-ups (followup-v1)

**Proves:** Jo can hold a research question you agree on, come back with a cited
reassessment at the agreed time, and push it to your phone without being asked again.
**Closes:** the follow-ups row, step by step: activation, then a natural question →
review → phone.

**Preconditions (none are done yet)**

- **Owner-gated; needs your approval at the VPS.** The Check upgrade through
  `check_control.py`, `followup_enabled=true` in Check, `JO_FOLLOWUPS_ENABLED=true` in
  `/etc/tradejournal/backend.env`, and the restarts. All of it follows the
  [rollout](../../deploy/market-watch/jo-followups.md#rollout-and-acceptance).
- **Owner-gated: hosted ChatGPT changes.** These are the conversation instructions,
  one 30-minute weekday sweep task and the event-task branch. The
  [conversation comparison](../../deploy/market-watch/jo-conversation-trial.md) was
  prepared as the test before that rollout; whether to run it first is your call.

**Steps (after activation, regular hours)**

1. Ask Jo a real question you'd want revisited, e.g. "is this NBIS recovery holding —
   check back in 45 minutes, until today's close". Jo should confirm the question,
   next review and expiry in one sentence, and not claim it's scheduled until the
   worker acknowledges it.
2. Wait. Around the review time, a push titled `Jo follow-up: …` should arrive if
   something useful changed. Nothing arriving is correct if nothing changed.
3. Ask Jo "what are you following?" Jo answers from its saved list, including that
   review. Then ask Jo to cancel it; later reviews should stop.

**Pass:** the review happened near the agreed time without a nudge, cited what it
used, and its push (if any) showed on your phone; cancellation stopped it. **Fail:**
no review by the time, a review with no sources, repeated identical pushes, or a
claim of monitoring that the list doesn't back up.

**Record:** `followup: date, question, agreed review time, review seen yes/no +
time, push phone time or none, useful yes/no, cancel ok yes/no`.

## Gaps found while preparing this

These come from reading the code against the contracts. None of them is fixed here.

- Item 2's gate wants a watchdog push confirmed on the phone, and item 4's wants a
  recovery push. Both need a real failure, or a late read inside the window, so a
  clean run can't close them.
- The [saved-advice contract](advisor-pretrade-check-contract.md#saved-advice-links-to-later-journal-activity--october-20-2026)
  still says the #365 repairs "require merge/deployment". #365 has merged; whether
  production runs it is unverified, and item 3 step 2 checks it.
- The stock-awareness diagnostic command has no documented host invocation. Item 5
  uses the API unit's user and environment.
