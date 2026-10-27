# SPY/QQQ v1 fixture conformance

October 27, 2026. Implements the separately authorized fixture milestone for
the [sealed paper specification](spec.md). The historical status in that sealed
document is unchanged; this companion records the subsequent engineering work.

**This is executable specification evidence, not strategy evidence.** All prices,
contracts, sessions, quotes and trade events are invented. No market data was
collected, no historical bars were replayed, no candidate was reserved or evaluated,
and no returns were measured from real observations. The paper strategy remains
inactive. There is no collector, broker client, runtime adapter or live switch.

## What is implemented

- [Signal examples](../../../backend/tests/scalp_fixtures/signal.py) implement the
  bar-based VWAP, aligned five-minute trend, first-pullback state machine and
  strict stop/trigger rules in a test-only package.
- [Execution examples](../../../backend/tests/scalp_fixtures/execution.py) cover
  chain selection, timestamped quote eligibility, the reservation lifecycle,
  crossing order, timeouts, unresolved exposure and one-contract arithmetic.
- [Conformance tests](../../../backend/tests/test_scalp_conformance.py) supply
  hand-authored inputs and expected outcomes. Two complete synthetic traces join
  signal, admission, selection, entry, exit and cash accounting for SPY calls and
  QQQ puts. Additional cases mirror both directions and both ETFs.

The reference model lives entirely under `backend/tests/`; it is not part of the
`app` package or registered with Factory, scanners, alerts or schedulers. The
model imports only an explicit small standard-library allowlist and its sibling
signal module. A test enumerates every support Python file and rejects forbidden
imports and direct I/O/evaluation builtins; planted violations verify the guard.
Network calls are denied during these tests. This is a regression boundary, not
a general-purpose security sandbox or proof against malicious Python code.

## Coverage against the frozen contract

| Contract | Fixture evidence |
|---|---|
| Freeze integrity | Exact spec/audit SHA-256 values and manifest contents |
| Causal bars | Contiguous minute sequence; end+5s deadline; missing, late, duplicate, malformed and nonfinite input; prior bars never revised |
| Signal | Earliest 09:45 arm/09:47 trigger; own-end VWAP; zero volume; one-to-three adverse bars; strict equality refusals; trigger excluded from stop; failed five-minute trend checked first; 11:00 signal cutoff |
| Session eligibility | Known calendar, 09:30 open, close after 11:15, 13:00 early close; 100ms clock bound; feed identity, health and halt refusals |
| Selection | First complete response; ten-second deadline; Friday-to-Monday calendar DTE; 2/5 inclusive and 0/1/6 excluded; nearest strictly ITM; no ATM or later-expiry fallback; standard deliverables; uncertain nearer metadata and duplicate identities |
| Entry | Locked contract; two-second latency on both quote sides; source/receipt freshness; first valid quote; both spread caps; no wait for tightening; observed stop touch despite recovery; no future reference; entry before 11:00 |
| Exit | Mirrored inclusive crossings; delayed pre-entry prints ignored; stale/unknown prints unresolved; same-receipt source ordering; unknown order unresolved; receipt-time intent; 15-minute timer and 11:15 cap; known crossings precede tied timer |
| Liquidation | Bid pricing without entry spread cap; fixed deadline; zero bid/size and pre-latency quote sides; immutable primary exit; later prices cannot resolve a timed-out position |
| Portfolio | SPY simultaneous priority; no QQQ fallback; reserved/open/unresolved blocking; rejected opportunities consumed; at most two entries; day reset never clears unresolved exposure |
| Accounting | Decimal dollar and premium-denominator examples; $1/side; additional spread per side; stress bid floored at zero; unresolved debit and full-loss sensitivity |

## Verification and limitations

Focused command, run from `backend/` with the existing development environment:

```sh
python -m pytest tests/test_scalp_conformance.py -q
ruff check tests/scalp_fixtures tests/test_scalp_conformance.py
```

The normal repository `conftest.py` remains intact: pytest creates/migrates its
disposable, pinned local test database. These conformance cases do not query it.
The tests do not open `.env`, Factory state, price caches, option history or account
records. Source ledger, gates, rules and budget files are checked separately by
read-only hashes; the tests themselves never need those files.

The fixture caller supplies complete, ordered receipt batches, verified session
facts and explicit health observations. A missed timer is unresolved, not rebuilt
from a later quote. Unknown quote order is refused. The helpers are not a transport
parser, scheduler, persistence journal or robust adapter for arbitrary payloads.
They do not establish feed entitlement, provider timestamp/condition semantics,
actual quote size execution, continuous health capture, restart recovery, complete
audit persistence or natural runtime conformance. A future adapter must run these
same expectations through its own interface; passing this reference model alone
cannot certify that adapter. No claim of exhaustive formal verification is made.

## Subsequent milestone: offline event adapter

The owner subsequently authorized building what can be isolated from the regular
journal. [The offline adapter](../../../backend/scripts/scalp_event_adapter.py)
now converts caller-supplied, newline-delimited quote/timesale JSON bytes into
immutable observations. It has no CLI, network client, credential/configuration
reader, database, file writer, timer, application import or runtime registration.
There is no enable flag. Importing it performs no collection. Existing Charts,
quotes, journal records, alerts and the shared Tradier connection are untouched.

This is reusable parsing code, built and tested once for later integration. A
future observation experiment would run for its approved window; it is not a new
permanent journal job. No such experiment is started or authorized here.

The adapter preserves original frame/line bytes, receipt UTC and monotonic clocks,
separate bid/ask times, size, exchange, sequence, opaque condition, cancellation,
correction and session fields. Events stay in transport order; transport ordinal
is never used as an exchange sequence. Missing fields remain missing. Zero bids,
stale/future prints and crossed quotes remain visible for the strategy's refusal
rules; they are not repaired or silently discarded. Malformed/unsupported events
and oversized frames produce explicit issues while retaining their source bytes.
It expects a complete caller-framed message and does not implement HTTP chunk
assembly, reconnection, subscription ownership or durable capture.

[Adapter tests](../../../backend/tests/test_scalp_event_adapter.py) use invented
Tradier-shaped messages and explicitly invented feed/condition semantics to bind
normalized events to the existing frozen reference examples. They exercise
two-sided latency, spread rejection, source-clock preservation, crossing order
and unresolved exposure during pending exits. No app strategy is imported, no
new evaluator is created and no performance is measured. Dependency and importer
guards enforce that the adapter stays separate from app and other script callers;
their planted failures cover I/O and journal imports. These are regression checks,
not a security sandbox. Existing conformance cases and freeze hashes are unchanged.

Run from `backend/`:

```sh
python -m pytest tests/test_scalp_event_adapter.py tests/test_scalp_conformance.py -q
ruff check scripts/scalp_event_adapter.py tests/test_scalp_event_adapter.py
```

The wire format is based on Tradier's public
[stream examples](https://docs.tradier.com/reference/websocket-market-data-streaming).
Timestamp units are pinned to epoch milliseconds in this offline stream parser;
REST timestamps and other formats are not guessed into that interpretation.
Parsing does not establish NBBO entitlement, quote-size units, sequence scope,
trade-condition eligibility, standard contract deliverables, halt detection,
clock synchronization or continuous connection health. No live semantics are
silently inferred from the fixture binding. Unknown production semantics still
block compliant paper execution. The existing chart stream coalesces events and
does not expose all of these fields, so it cannot be treated as this input.

Before an authorized capture: verify provider semantics and access, choose one
explicit stream owner, provide the frozen calendar/clock/health evidence, and
prove that raw events reach a separate paper consumer without affecting journal
consumers. Tradier's documented single-market-stream constraint remains relevant;
this offline module opens zero connections. No performance cohort, statistical
decision plan, candidate attempt, feed subscription or collection is authorized.
Factory's protected gates and data splits remain unchanged. Both Factory launch
agents stay paused, and live execution remains off.
