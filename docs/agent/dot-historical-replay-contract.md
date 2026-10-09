# Jo's weekend historical market replay

Selected after Jo saved/reopened real-data MU/NBIS SKIPs. This isolated-demo
increment uses retrospectively retrieved raw Alpaca bars for a past regular
session and its next verified session. Jo chooses source-linked TAKE/WAIT/SKIP
before any continuation is exposed. It is an assisted historical exercise,
not contemporaneous source observation, a blind comparison or a live watcher.

## Two clocks and sealed evidence

Retain original minute timestamps, the actual provider retrieval time and the
actual decision receipt time. `simulated_as_of` is the historical information
cutoff; it is never substituted for actual retrieval/receipt metadata. Only
completed minutes at/before that cutoff enter the public packet and source
facts. The chart uses that cutoff. The real exercise deadline is twenty hours
after import. Plan/WAIT expiry is on the historical clock, at/before the end
of the second verified session. Freshness is checked at the fixed simulated
cutoff only in the separate historical policy. Live-market freshness rules
remain unchanged. Provider history may contain subsequent corrections; this
does not prove what the provider actually published at the historical cutoff.

The new schema is `practice-historical-replay-long-15m-v1`; the execution
contract is `historical-paper-replay-v1`. It supports MU/NBIS long shares,
source-linked trigger/stop/target, regular-session complete 15-minute close
confirmation, an entry guard, two-session maximum and `p0-cost-v1`. The public
packet has at most sixty pre-cutoff minutes. Coverage reports minutes without
supplied bars and partial intervals, separately from provider/input failures.
Never assume a missing IEX bar means a broken provider or fill it forward.

The operator seals the later original bars with a random nonce before publishing
the public context. Neither run/list/decision/card nor cloud read tools expose
the continuation before the actor's own saved TAKE starts its replay. WAIT/SKIP
produce no replay or paper entry. This is a bounded sample-account replay action;
the generic arm/paper routes and live watcher refuse the historical schema.

Replay reuses the pure existing paper reducer with original epoch times.
Each complete post-cutoff fifteen-minute bucket is detected two seconds after
its close. Entry uses the first full minute beginning after that detection.
Missing confirmation intervals are never considered complete. Missing required
entry/hold minutes are unresolved, and insufficient continuation for a complete
two-session hold is unresolved rather than a fabricated exit. Stop-first,
reference entry guard, costs, planned-R denominator and three-times costs keep
the existing reducer semantics. Save the entire receipt atomically once; exact
retries/read/restart return it without recomputation or changing the decision.

## Isolation and operations

Use a new own-run identity with `market_decision_write=true` and
`historical_replay=true`; no journal, ordinary sample writer/replay or other
session access. Require authentication, marked trial, existing market writer
flag and explicit `TJ_HISTORICAL_REPLAY_ENABLED=true`, with the isolated factory
state. Grant create/reset and every restricted read match the frozen assigned
actor. Serialize saves/replay against current sessions, grants and revocation.
Strict bodies/CSRF/budgets remain. Ordinary market-role accounts cannot start
historical replay and historical accounts cannot start the old sample replay.

The private VPS host capture uses only the existing provider credentials and
finite fixed calendar/minute GETs. No app/database imports, paid model calls,
feed upgrades, proxies, redirects or unbounded pagination. Import only a
root-owned private bounded file with verified consecutive session calendars,
strict symbols/source/OHLC/timestamps and original retrieval metadata. Retain
identical files/runs/keys; refuse replacement or implicit login rotation. No
provider/model secrets enter the isolated runtime. Production/network rules,
prior sample/market rows/credentials and D1 activation remain unchanged.

Native proof uses a separate run/account, never Jo's decisions, then revokes
that account. Verify source/cutoff/chart/coverage, a conditional TAKE with replay,
WAIT/SKIP refusal, hidden continuation, ownership/integrity/clock denials, exact
numeric outcomes, atomic concurrent retries, service restart and prior-record
preservation. Full verification, Postgres/Ubuntu CI and tier-two native reviews
are required. Actual Jo use and laptop-off observation remain separate gates.

Operator commands are `deploy/dot_historical_capture.py --day YYYY-MM-DD
--cutoff HH:MM` on the host, then `deploy/dot_historical_import.py` with the same
day/cutoff in the pinned trial virtualenv. The capture requests a calendar range
of at most eight dates, retains its first two verified past sessions and makes
four stock-bar GETs (two symbols by two sessions), each bounded to one response
and ten seconds. Root-owned 0600 handoffs stay under
`/etc/tradejournal-dot-trial/historical-handoff-YYYY-MM-DDTHHMM.json`.
The explicit updater option is `--enable-historical-replay`; its selected
twenty-three source files include the three new historical modules, with no
test fixture, dependency, market data or credential in the archive.
