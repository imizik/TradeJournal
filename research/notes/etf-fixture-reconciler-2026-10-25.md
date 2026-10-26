# Fixture-only ETF cash/share reconciler

October 25, 2026. Implements the invented accounting example from the
[acceptance packet](etf-trend-acceptance-2026-10-25.md). This is accounting
preparation, not a strategy, historical evaluation or paper activation.

Run from the repository root, with Python 3.11 or newer:

```sh
python3 backend/scripts/etf_fixture_reconcile.py
```

The command accepts no input path or live/evaluation switches. It reads only the
committed invented JSON receipt and checks its pinned SHA-256 before processing.
It writes a JSON summary to stdout, with no file, database or network writes.
There are no application, provider, broker or Factory imports. Nothing registers
with a scheduler. Live execution remains absent.

The pure `reconcile` function recomputes cash, whole shares, dividend receivable,
unsettled sale proceeds, settled cash and NAV using Decimal and half-up cent fees.
Expected balances in the receipt are assertions, not state inputs. It returns
immutable snapshots and does not mutate input. Replaying the complete receipt
reconstructs the same result. Exact duplicate IDs with identical payloads are
ignored; conflicting payloads fail. The fixed event sequence also refuses a
second payment or split under a fresh ID.

Scope is deliberately narrow: one invented held asset, one rejected intent,
one distribution, one whole-share split, one full liquidation and one sale
settlement. The fixture assumes purchase settlement is completed before the
later sale. It does not model unsettled purchase obligations, partial fills,
multiple concurrent positions or arbitrary corporate actions. The sequence is
fixed; this is not a general ledger API. Corrections, closures, halts, missing
marks and unsupported events fail rather than silently updating the example.
Reconciliation failure returns no partial result or persisted state.

No signal, ETF selection or performance statistic is computed. The fixture's
signal metadata is narrative context, not an evaluated trading rule. Quote
provenance and availability are invented, not verified. The CLI's pin prevents
accidental replacement by market data; the pure checker is exposed for altered
invented regression cases, not an authorization boundary for hostile Python code.
No durable restart journal or tamper-proof storage is claimed.

Focused tests cover reconstructed balances, nonmutation/restart, duplicate
handling, finite decimal/whole-share bounds, fees, budget refusal, dividend/split
accounting, sale settlement, rejected intents, unsupported cases, expected-value
mismatches and CLI input/hash refusals. A passing result proves only this fixture
contract. Data acceptance, statistical design and strategy validation remain
blocked as described in the acceptance packet. Neither Factory schedule nor its
ledger, budgets, gates or protected data is changed.
