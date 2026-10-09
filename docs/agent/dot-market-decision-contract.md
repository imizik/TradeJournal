# Jo's frozen real-market decision pilot

Selected by Isaac on 2026-10-09 after Jo completed the authenticated sample
save/replay/chart workflow. This increment prepares one manual MU/NBIS session
from actual market evidence, permits Jo's own immutable TAKE/WAIT/SKIP, and lets
the private owner review those records. It does not enable paper monitoring,
real orders, scheduling, model calls, an independent comparison, or change P0.

## Data handoff and isolation

The existing isolated trial retains its seeded journal, marked SQLite database,
private network namespace, disabled integrations and absence of provider/model
keys. Only its authenticated assistant frontend remains public. The private
production API, journal, credentials and network routes remain private.

`deploy/dot_market_capture.py` runs explicitly as root on the VPS host. It reads
only the existing Alpaca key/secret/feed fields from the private provider env;
it imports neither the app nor a database. It makes at most two fixed calendar
GETs (paper then live authentication realm), followed by at most one fixed stock
bars GET per symbol, with ten-second timeouts and bounded response sizes. No
redirect, environment proxy, retries, feed upgrade or historical fallback is
used. The existing configured IEX/SIP feed must be available; missing evidence
is explicit and never replaced with fixtures.

Requests specify raw USD 1-minute bars for the verified current regular session.
Early closes/holidays come from the calendar, never a weekday assumption. Keep
at most sixty newest completed minutes for each symbol, with provider OHLC,
share volume and nullable supplied VWAP. Missing minutes remain missing. Freeze
request end before retrieval and capture time after retrieval. News, daily
history and options are outside this packet. The importer preserves capture
and observation times; import does not make old bars fresh.

Capture publishes a root-owned 0600 `market-handoff-YYYY-MM-DD.json` atomically,
without credentials. Repeating capture retains the original file/cutoff without
provider calls. `deploy/dot_market_import.py` checks its location/permissions,
size, strict field whitelist, symbols, timestamps, calendar, source, ordering,
OHLC/volume/VWAP and completed regular-session membership. Both contexts,
opportunities and the run commit together. Identical import returns the original
run; changing a frozen day's evidence or assigned agent refuses. Bundle and
context hashes identify frozen data, not cryptographic provider authenticity.
The trusted host capture is the provenance boundary.

The [Alpaca bars](https://docs.alpaca.markets/us/reference/stockbars) and
[calendar](https://docs.alpaca.markets/us/reference/legacycalendar) contracts were
checked on 2026-10-09. Provider-shaped unit/browser fixtures test parsing and
application behavior; actual provider retrieval is a separate native gate.

## Own decisions only

Use a new `trader-jo-market` identity and exactly one assigned run with
`market_decision_write=true`, MU/NBIS symbols and no journal/sample-write/replay
grant. Do not rotate/repoint prior Jo credentials. A later session requires a new date-stamped identifier; reusing an existing identity for a different day refuses before creating a run. A failed credential publication disables that new identity; recovery requires an explicit private-owner key reset, never implicit rotation. The runtime requires explicit
`TJ_MARKET_DECISION_WRITES=true` plus authentication, marked-trial flags and the
isolated factory state. Normal production `app.main` refuses this writer even
with flags set. The browser can only read that run and its own records and POST
to its opportunity's `agent-choice`; ordinary market routes, journal, human or
other-agent records, context preparation, generic writes, reveal, jobs, arming
and replay are denied. CSRF, budgets, expiry and revocation remain enforced.
Submission serializes and rechecks the current session/grants against resets
and revocation, before saving. Actor, context, opportunity and retry IDs are
server-owned. One choice per opportunity is immutable; exact retry retrieves
its original receipt after expiry, changed retries conflict.

`practice-market-decision-only-v1` has a separate policy/hash, an hour-long
capture-to-decision window, and `execution=disabled`. All records remain
`practice_draft_unarmed`; P0 arm and generic paper views refuse this schema.
TAKE requires the same actual raw Alpaca fact validation as A1, a verified open
regular session on the capture date, and a latest frozen minute no older than
five minutes at save. Plan levels are selected by Jo from frozen facts rather
than assigned by the app. Retain source-linked stop/trigger/target, an ordered
entry guard, expiry at/before the decision deadline, two-session maximum,
two-hour fact freshness and declared `p0-cost-v1` assumptions. These costs do not
start execution or make this policy eligible for P0. WAIT/SKIP remain possible
when source/calendar/freshness is unavailable until the decision window ends.
Late/postmarket captures are explicitly decision-only observations; none count
as A3's eligible live sessions or blind comparisons.

## UI and acceptance

The landing page/Daily Review distinguish real frozen evidence from invented
samples. The frozen chart reuses the packet-only reducer, never Charts or a live
provider route. TAKE has source-fact selectors, maximum reference entry and an
expiry preview. Missing/stale/closed-session TAKE refusal is readable. Saved
cards reopen exact evidence/record hashes. The private isolated owner review
shows the assigned Jo choice without enabling owner edits or paper controls.
Jo's actual browser acceptance, laptop-off observation and native hover-popup
rendering remain separate observations.

An explicitly labelled operational proof uses a separate run/identity via
`--proof`; it never pre-fills Jo's session. Its credentials are revoked after
native acceptance. Test fixtures are not shipped in the updater archive.

Required evidence: raw-source and policy identity, integrity/freshness/calendar
refusals, ownership/CSRF/revocation/flag/factory denials, immutable concurrent
retry behavior, atomic failed-import rollback, original-context/decision/key
preservation, private owner review, browser save/reopen/phone checks, native
provider/HTTPS/process-isolation/restart checks, full local verification,
Postgres/Ubuntu CI and tier-2 native general plus focused security review.

Operations use the existing guarded updater with the exact reviewed commit and
`--enable-market-decisions`. Its twenty-file selected source archive includes
only reviewed code, never dependencies, data or credentials. Rollback restores
assets, source, permission flags and any already-active D1 socket; it never
activates an absent cloud reader. Existing D1 tools remain sample-only and do
not gain real-market reads from this browser increment. Do not change production
service settings or network rules. Capture/import are manual, finite commands;
merging code enables neither scheduling nor a live model call.
