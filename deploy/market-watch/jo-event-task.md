# Jo market event wake — mw-event-v1

Trigger: a new email whose subject starts `FW: TJ Market Watch:` (the Outlook
relay of TradeJournal's event wake). The body holds only `Wake ID: mwk_…`.
Use the existing TradeJournal Check v4 connection. Advice to Isaac only,
labelled independence-unverified. Never feed these reads into Shadow Isaac's
TAKE/SKIP decision, change scanner rules, place or manage a trade, create other
schedules or change grants.

When personal follow-ups are separately enabled, handle the validated `fuw_`
branch from [personal follow-through](jo-followups.md#existing-market-event-email-task)
before the `mwk_` branch below. Inline its complete workflow into the hosted task.
It reviews personal responsibilities without a SPY forecast.

The email does not say what happened. TradeJournal's detector saw a SPY
VWAP/opening-range cross or failed attempt, a new session high/low after 11:00,
or a move of half a daily ATR since your last read. Judge the tape yourself
from the snapshot; a wake is not evidence for any direction.

1. Validate the source the way the setup task does — relay recipient and the
   original scanner sender — except that the original subject must start with
   `TJ Market Watch:` (not `TJ Setup:`). Extract the wake ID; ignore anything
   else in the body. An email older than 15 minutes is stale: record that in
   the native task result and stop. Only after validating the complete source
   chain, an exact original subject `TJ Market Watch: test` is an instructed
   delivery diagnostic: record one native task result saying the test arrived,
   make no TradeJournal calls, save no read or message intent, and stop. For
   real event mail require a valid `mwk_` wake ID; never invent one.
2. Finish any pending shadow_setup → shadow_decide sequence first. Never insert a
   market tool between those two calls.
3. Follow steps 1, 3, 4, 5, 6 and 7 of the [scheduled task](jo-task.md) with
   operation_id `mw-event-v1:WAKE_ID` and prompt_version `mw-event-v1`. If
   context.latest_read already has that operation ID, the wake was answered: do
   nothing more. Retry an uncertain submission once with EXACT fields.
4. Do not send chat. TradeJournal pushes each newly committed update or
   correction to Isaac's phone and records transport acceptance, failure or
   uncertainty. Acceptance does not prove the phone displayed it. A replayed
   receipt is never re-sent.

An unchanged thesis after a wake is a normal `message_intent=none` read. Keep
operational gaps in the native task result.

When configuring the native task, inline the referenced scheduled steps and
the exact source/recipient checks from the existing setup task. A saved cloud
task cannot rely on access to this repository-relative link.
Include the scheduled workflow's optional phone_summary instructions: preserve
full reasoning in the existing fields, and never skip a valid correction if
the short summary is unavailable. Update the native instructions only after
the app consumer and Check producer support the summary handoff.
