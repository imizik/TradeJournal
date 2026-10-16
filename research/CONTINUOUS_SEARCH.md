# Mac continuous setup search

Runs only in `/Users/user/TradeJournal-factory`, branch `factory/ledger`.
This branch is never merged and no unproven strategy PR is created.

`backend/scripts/factory_search.py --tick` runs at most one new candidate.
launchd calls it every five minutes with `--force`, enabled by Isaac on
October 15 to continue searching during the day as well as at night. The same
24-candidate / two-hour budget remains in force; its existing window rolls
over at 22:00 New York. Already consumed attempts and time are retained.
A tick acquires the same exclusive writer lock, so evaluations do not overlap.
Without `--force`, new work remains restricted to 22:00–06:00 New York.
Daily summary files/ntfy receipts are snapshots; tomorrow's verifier must
compare them against the latest ledger while continuous work is active.
The Mac must be awake. SIP cache only; no VPS computation or database access.

Nightly limits: 24 reserved candidates, two hours of reserved process time,
one Claude-plan call capped at $2 / 300 seconds, each evaluation at most
15 minutes. Completed evaluation time is charged; a supervisor interruption
consumes the entire reserved timeout. Process-time bounds are conservative,
not a promise that 24 candidates finish. Failed Claude calls use random
proposals and appear in logs. No API-key fallback. `--force` permits one
acceptance tick outside the nightly window and uses the same budgets.

Every candidate is durably reserved in `research/ledger.jsonl` BEFORE
its worker starts. All distinct IDs, including historical screen failures and
interrupted reservations, count toward Bonferroni. Reservations never retry.
An atomic finished result is imported after a supervisor restart; otherwise
the reservation is marked interrupted. The worker inherits the supervisor's
flock so a second launch cannot overlap an orphan worker. The weekly wrapper's
`week.lock` excludes weekly writes. Direct manual CLI writers must not run
concurrently. The ledger checkout's CLI also recognizes reserved IDs.

The existing April 2026 onward exam holdout is retained (it includes the most
recent four weeks). Discovery/confirmation periods are unchanged. Later
periods are loaded only by the existing gates; all candidates face the same
random-entry baseline and cost-stress checks. Claude sees only a whitelisted
spec + discovery/confirm ledger digest, no notes, exam outcome or holdout
numbers. Its tools are disabled and it has no session persistence. Random
proposals cover every factory family, the two S1 setup types, day/week filters,
past levels and exits. The model does not edit code, costs or the universe.

`s1_research` reuses scanner_rules' pure signal functions on SIP minute bars,
including scanner ATR/VWAP/EMA computation; it is an underlying-signal research
proxy with factory exits and costs. It does not model option premiums/spreads,
scanner cooldown/admission or Jo decisions. A passing exam produces only an
`s1-v3-proposal-<id>.json` evidence file, requiring forward paper evaluation and
Isaac approval. It changes no live S1 settings, exchange, task or pre-trade check.

Jobs/results/briefs and budget receipts: `backend/data/factory/search/`.
Daily summary: `research/reports/<night>-continuous.json`, plus ntfy using
`FACTORY_ALERTS_ENV` (default `~/.config/tradejournal/alerts.env`), falling back
to the existing `FACTORY_NTFY_URL` / token in the linked backend environment.
Never print these settings. Commits/pushes retain research evidence on the
ledger branch. Logs: `~/Library/Logs/tradejournal-factory-search.log`.

Pause: `launchctl bootout gui/$(id -u)/com.tradejournal.factory-search`.
Resume: `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.tradejournal.factory-search.plist`.
The actual unattended-night and real restart receipts must be recorded after
observation; installation, fixture tests and a daytime run do not satisfy them.


October 15 proposal intake repair: the first 16 completed trials were all random.
Claude had produced four proposals, but canonical ledger-style `low`/`high`
filter bounds were rejected by the CLI-style `min`/`max` parser. The search now
translates those equivalent spellings (and `note` to `notes`) before strict
validation, rejecting conflicting bounds. No numeric bound, gate, cost or
budget is changed. The original answer is retained. Three saved proposals
now validate; the fourth remains refused for an invalid window and is not
silently altered. Claude validation refusals are logged to the main log and
`backend/data/factory/search/<window>-proposal-rejections.jsonl`. Rejected
proposals are not evaluated candidates and are not ledger trials.

Claude feedback now includes origin and recorded discovery screen failures in
the whitelisted ledger digest. Each next scheduled call must explain which
failure its hypothesis addresses. A preview and three-candidate feedback
receipt were prepared October 15 without making an extra model call.
The one-call-per-window limit, candidate/time caps and every gate are unchanged.

The separately authorized opportunity-feed pilot is documented in
`research/OPPORTUNITY_FEED.md`. Its two discovery-only builds reused already
counted IDs and consumed 32 + 63 seconds from the existing time budget. They
added no factory candidates, changed no gates and made no model calls. The
v2 pilot has 90 outcome-blind cards awaiting real Jo choices; it is not a
passed strategy and is not connected to the live scanner or Jo task.

October 16 Codex preference: the search prefers the signed-in ChatGPT Codex
plan for ideas. Isaac explicitly approved sanitized candidate specs and
discovery/confirmation feedback on October 16. Codex receives the same
whitelisted digest as Claude, excluding free-text names/notes, holdout/exam
evidence, real trades and credentials. Duplicate checking stays local.

Request up to four ideas per batch, with another batch only when no valid
untried Codex idea remains. At most six batches per 22:00 ET budget window;
each conservatively reserves 330 seconds before launch. Candidate cap 24 and
process-time cap 7200 seconds are unchanged. Started batches are never retried.
The CLI forces ChatGPT login with no API fallback and uses the configured user
model. It runs in an empty temporary directory, read-only, with shell, web,
MCP, plugins, hooks, memories and delegation disabled. Keep schema/answer,
usage/events and generation receipts under the private search directory.
Existing single-call Claude fallback and random sampling remain available.
No gate, holdout, Bonferroni count, scanner setting or production task changes.

Unattended-night acceptance October 16: 20 candidates completed in the October
15 22:00–October 16 06:00 ET window, four after midnight. None passed the screen.
The accepted ntfy receipt at 09:52 ET is a 20-candidate snapshot; the next result
at 10:56 ET raised the active-window count to 21. The Mac slept on battery,
so wall-clock gaps do not represent uninterrupted awake execution. It was on
AC at audit. Existing restart-receipt.json proves unchanged distinct trial
count after the actual supervisor restart; the complete ledger has no duplicate
reservations, and every stored prior-candidate K matches all distinct earlier IDs.
