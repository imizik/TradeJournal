# Add after the existing setup task's completed shadow/co-pilot sequence

Preserve all existing shadow-first instructions and independence labels.
After saving the shadow decision and co-pilot verdict, consider a market note
when this review and at least one other DISTINCT current-session call/long
review you actually observed were Pass/Wait because the market stayed below
VWAP and bounces failed. Do not count repeated tool retries as distinct setups,
use stale reviews from another date, or reinterpret the scanner's rule result.
This is a market-context note even without a Go; it creates no new paper trade.

Use the same mw-scheduled-v1 market-read workflow and shared three-intent budget
as the scheduled task, with operation_id
`mw-setup-context-v1:SESSION_DATE:CANDIDATE_ID` and
prompt_version=mw-setup-context-v1. Fetch the fresh market snapshot, recover the
parent and last message from its actor-scoped context, save the three fixed
SPY forecast slots (or explicit abstentions), and save any allowed update or
correction intent exactly as before. Do not send chat for market reads or
market notes; TradeJournal pushes newly committed intents to Isaac's phone. Two opposite-way setup reviews are a reason to reassess, not
sufficient evidence to assert a directional day or a specific put opportunity.
Apply the same material-change thresholds, quiet unchanged-read behavior and
linked-correction exception. Preserve Go alerts already required by the setup
task; this market-note budget covers market-watch notes, not those existing Go
alerts. Never add market calls before the shadow commit.

Include the scheduled workflow's optional phone_summary instructions in the
native setup task after consumer/producer rollout. Keep the full reasoning in
the existing fields; summary failure must never suppress a valid correction.
