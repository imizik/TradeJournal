# Prospective MU study

Selected after the owner reviewed the historical MU comparison. This separate
study freezes the existing question before collecting future observations;
it does not change Factory validation or make a trading recommendation.

## Frozen question

Protocol `mu-prospective-20261012-v1` runs October 12, 2026–April 9, 2027:
26 calendar weeks and 124 scheduled sessions under the published
[NYSE calendar](https://ir.theice.com/press/news-details/2024/NYSE-Group-Announces-2025-2026-and-2027-Holiday-and-Early-Closings-Calendar/default.aspx).
November 27 and December 24, 2026 close at 13:00 ET. Unscheduled closures and
missing minutes remain disclosed coverage gaps; files never define the calendar.

MU, first qualifying completed five-minute decision per session within
10:00–11:30 ET, 15-minute close decline at most -0.25 prior daily ATR(14),
cumulative RVOL at least 1.5×. Primary: 30-minute percent return from next
complete five-minute open, compared with the existing symbol/clock-weighted
ordinary baseline and joint calendar-week uncertainty. The 2× rule, other
existing horizons and ATR units are secondary. All current causal features,
endpoint masks, resampling method/seed and insufficient-cluster behavior stay
fixed. These are price returns, not P&L, stops or execution simulation.

The first formal performance review occurs after the final session's
collection. There is no early performance review, threshold tuning, automatic
extension, selection of the best secondary horizon or promotion to Factory.
The six-month window is an operational bound, not a statistical power claim;
rare events may leave the result inconclusive. Operational coverage is available
throughout. Prospective means subsequent to this registration; it cannot prove
that no one inspected the same dates elsewhere.

## Registration, collection and storage

Registration must occur before the first session opens and before any forward
cache payload exists. Immutable registration includes canonical definitions,
the analysis specification, planned source-file hashes and a frozen warm-up
snapshot through October 9, 2026. Later corrections to the historical cache
cannot change this warm-up. Runtime sealing refuses source changes since
registration and records the actual Python/NumPy/calculation identities.

Source version 3 is separately bounded to this fixed MU study. Defaults retain
version-1 discovery and version-2 historical cutoffs. An operator-supplied
prospective cutoff is required before any version-3 cache path opens; forward
raw storage never supplies historical warm-up. The normal Studio sidecar has
no forward-source flag and cannot load this cohort through its HTTP commands.

The collector requests only MU/SPY completed regular sessions from the
[Alpaca historical stock-bars endpoint](https://docs.alpaca.markets/us/reference/stockbars),
with SIP, raw adjustment, fixed symbols/date range and no symbol mapping.
Only existing credentials are used. There is no IEX fallback, plan purchase,
account read, order endpoint or model/API billing. Entitlement failure stops
collection; fixture tests do not prove live SIP entitlement.

The timer runs at 20:30 ET, persists across reboot, and considers at most the
last five completed scheduled sessions. A failed date is attempted at most
once per ET date; a later date may retry it within that window. Older gaps stay
in the study. Each request permits at most four pages of at most 2 MiB each,
so at most 20 requests per run, ordinarily one for a new session pair.
Both symbols must have every scheduled minute, with no duplicate, invalid or
off-grid rows, before a session is committed. Incomplete attempts record
quality counts without committing deficient payloads. A crash after one symbol
was committed resumes with the same immutable bytes and fetches the missing
symbol. No committed source file is overwritten.
The final collection attempt closes collection permanently, including when
the provider fails. Formal review then uses committed receipts only; interrupted
or uncommitted files remain retained but excluded. A reboot resumes partial
pre-deadline captures, not indefinite fetches after the study ends.

Future cache plus records are capped at 250 MiB with a 2 GiB free-space reserve.
Each session is stored once; daily full-history snapshots are avoided. The
historical transfer averaged about 200 KiB per MU/SPY session pair, roughly
50 MB/year; network traffic may differ. The frozen Python runtime is a separate
one-time installation, not part of that data estimate. Formal review verifies
receipt hashes, combines frozen warm-up with committed future bytes, preserves
one review snapshot and two complete immutable result JSONs, and records
review/source exposure. It does not write the ordinary Studio or Factory ledger.

## Operator activation after merge

Normal application deployment does not install or enable the collector.
The explicit installer copies a closed set of reviewed source files and the
installed Python environment into a root-owned runtime outside release pruning.
It copies only the installed NumPy/HTTPX distribution dependency closure into
an offline Python environment; it does not copy the full application environment
or download packages. It walks actual project imports to refuse dependencies outside that set. App
upgrades cannot silently change this runtime; OS/runtime drift refuses collection.
Only two Alpaca secrets are copied from the root-private backend configuration
into a separate root-private environment file. Never print either file.

```bash
sudo /opt/tradejournal/current/backend/.venv/bin/python \
  /opt/tradejournal/current/deploy/research_studio_prospective.py install
sudo systemctl status tradejournal-research-prospective.timer --no-pager
sudo systemctl start tradejournal-research-prospective.service
```

The installer adopts an existing matching pre-registration, or creates one
only before the frozen start. It seals the runtime and enables the timer.
Missing credentials, conflicting source/runtime/units or late registration
refuse activation. The service is unprivileged with a read-only system and
write access only to the separate study cache and records; the original cache
is read-only. The installed runtime is intentionally fixed to its first release.

Inspect coverage without reviewing outcomes:

```bash
sudo -u tradejournal \
  /usr/local/lib/tradejournal-research-prospective/backend/.venv/bin/python \
  /usr/local/lib/tradejournal-research-prospective/backend/scripts/research_studio_prospective.py status \
  --records /var/lib/tradejournal/data/research-studio/prospective/records \
  --cache /var/lib/tradejournal/data/research-studio/prospective/cache/sip \
  --warmup /var/lib/tradejournal/data/research-studio/cache/stocks/1Min/sip
```

After April 9's final collection, `review.json`, `review.snapshot.gz` and the
two `result.<run_id>.json` files live in the records directory. The `review`
CLI action returns the saved report; before that deadline it refuses. These
prospective results are separate from the historical comparison UI and can be
reviewed from their receipts. Automatic generation is not a claim of owner
acceptance, unseen validation or a trading edge.

Stop safely without deleting evidence:

```bash
sudo /opt/tradejournal/current/backend/.venv/bin/python \
  /opt/tradejournal/current/deploy/research_studio_prospective.py disable
```

## Evidence

Fixtures pin the 124-session roster, fixed definitions, pre-open registration,
pre-close network refusal, duplicate/daily retry bounds, masks, hand-calculated
next-open return, frozen warm-up despite outside corrections, corrected-payload
refusal, clock/runtime/budget/ownership/link boundaries, market-data-only URL,
SIP refusal and bounded pagination. Operator tests check actual project-import
closure and unit scope. Actual VPS installation, reboot/first provider session
and source entitlement remain distinct from these fixtures and release CI.
