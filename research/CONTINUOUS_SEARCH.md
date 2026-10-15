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
