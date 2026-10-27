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

The next bounded milestone, if separately approved, is to inspect the provider
contract and entitlement for the required event fields and capture health **before
authorizing collection**. No performance cohort, statistical decision plan,
candidate attempt, feed subscription or collection is authorized by these tests.
Factory's protected gates and data splits remain unchanged. Both Factory launch
agents stay paused, and no live execution has been enabled.
