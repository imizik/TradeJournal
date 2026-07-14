# Roth Reconciliation Report — 2026-07-14

Source: Robinhood activity export `backend/reports/1f4613d0-7593-50f0-a265-8171ec59973d.csv`
(Roth IRA 8267, activity 2025-10-01 → 2026-07-13, 4,059 records, 3,929 trade fills).

Method: CSV parsed with `scripts/csv_reconstruct.py` logic (export is newest-first, so
fills were reversed to chronological order before FIFO — without this, same-day exits
sort before entries and the comparison is garbage). CSV FIFO result compared per
contract key against the live `trade` table (Neon), non-open trades opened ≥ 2025-10-01.

## Bottom line

| | Realized PnL (window) |
|---|---|
| Broker CSV ground truth | **+$7,059.62** |
| Live journal (trade table) | **+$988.51** |
| Journal understates by | **$6,071.60** |

1,082 of 1,102 contract keys match to the penny. 20 differ, in five root-cause families.

## Family 1 — Same-minute fill ordering breaks FIFO (-$3,732, 6 contracts)

Robinhood email timestamps are minute-granular. When an entry and a partial exit land in
the same minute, the rebuild can process the sell first: the sell is orphaned, and the
still-"open" lots are later written off as expired worthless.

| Contract | Broker | Journal | Diff |
|---|---|---|---|
| SPY 682p 2025-12-01 | +260 | -1,040 (expired) | -1,300 |
| SPY 690p 2025-12-26 | +118 | -944 (expired) | -1,062 |
| SPY 694c 2026-01-13 | +210 | -385 | -595 |
| NVDA 185p 2025-11-07 | +24 | -292 (expired) | -316 |
| MU 230p 2025-11-21 | +79 | -194 (expired) | -273 |
| SPY 670p 2025-11-17 | +17 | -169 | -186 |

Verified: each has buy_to_open and sell_to_close fills at the identical minute.

**This is nondeterministic per rebuild.** `reconstruct()` sorts by `executed_at` only
(stable sort), so ties resolve to whatever row order Postgres returns. Re-running the
reconstruction over the same fills produced the *correct* result for these six but broke
NBIS 230c 2026-07-10 and SPY 669p 2025-11-17 instead (which the live table currently has
right). Any future rebuild can reshuffle these. Fix: deterministic tie-break in the
reconstructor sort — opens before closes at equal timestamps, then a stable key (fill id).

## Family 2 — SPXW index options never imported (-$2,440, 3 contracts)

July 9–10 SPXW scalps (7535p ×2 expirations, 7540c) realized +$2,440 at the broker.
Zero SPX* fills exist anywhere in the DB — the executions never produced parseable
Robinhood execution emails (the parser regex itself handles the SPXW symbol and
comma strikes fine). Needs Gmail verification, then manual fills or CSV import.

## Family 3 — Missing fills on June 11 SPY 730 puts (net +255)

- SPY 730p exp 2026-06-12: journal is missing the BTO 3 @ $206, so its orphaned sell
  produced no trade — a real **-$327 loss is absent** from the journal.
- SPY 730p exp 2026-06-11: journal is missing the STC 3 @ $24, so it shows expired
  -$201 instead of the true -$129 (-$72 off).

## Family 4 — CAR 100p phantom contract (-$20)

Journal has 3 contracts (BTO 1 + BTO 2, same minute) vs 2 at the broker — the known
cumulative-partial-fill duplicate family. All expired, overstating the loss by $20.

## Family 5 — Recurring fractional buys never imported (≈ -$134 + missing basis)

Weekly recurring buys (VOO, QQQM, SOXX, SMH, GOOGL, ASTS, NVDA, ALAB fractional adds;
RKLB, AUR still accumulating) have no fills in the journal. When positions were sold
on 2026-06-05/06-18/06-25 the sells arrived as orphaned/over-closed exits:

ASTS -74.08, NVDA -22.52, SOXX -22.23, SMH -17.77, QQQM -4.99, VOO -1.55,
GOOGL +5.03, ALAB +3.51 (fractional basis drift).

Open recurring positions (RKLB, AUR, …) also carry no basis in the journal.

## Fixes applied (2026-07-14, same day)

All five families were fixed and the trades rebuilt:

1. **Family 1 (code fix):** `reconstruct()` in `backend/app/engine/reconstructor.py` now
   sorts fills by `(executed_at, opens-before-closes, fill id)` — same-minute entry/exit
   pairs order correctly and rebuilds are deterministic. Covered by
   `test_same_minute_open_and_close_orders_deterministically` in
   `backend/tests/test_reconstructor.py` (13/13 passing).
2. **Families 2, 3, 5 (backfill):** 103 fills inserted as manual fills
   (`raw_email_id` prefix `manual:csvfix-`, included in `manual_fills.json`, so
   resync-all preserves them): 38 SPXW option fills (Jul 9–10), the SPY 730p
   BTO/STC pair (Jun 11), and 63 recurring fractional stock buys
   (AUR/GOOGL/QQQM/RKLB/SMH/SOXX/VOO/NBIS/ALAB/APLD, May 6 – Jul 13).
   Synthetic execution times preserve the CSV's intra-day order (dates are real,
   clock times are not).
3. **Family 4 + one more phantom:** CAR 100p BTO qty 2 → 1, and a previously
   unknown duplicate found during fill-level matching — SPY 710p 2026-04-17
   STC 4 @ 115 (`raw 19d9c02f55e349f3`, a cumulative "4 of 5 filled" partial
   alongside the final 5-lot fill) — deleted. NOTE: a destructive Gmail
   resync-all would re-import both phantoms from the original emails; re-apply
   these two corrections if that ever runs.

**Post-fix verification:** per-contract comparison of the live trade table vs the
CSV ground truth: 1,102 contract keys, zero real differences. (Two apparent
diffs — ASTS +74.08, NVDA +22.52 — are window artifacts: those sells close
against lots bought in 2020/2021 that the CSV export cannot see; the journal is
correct.) Window totals: broker +7,059.62, journal +6,963.50, the $96.12 gap
being exactly those two boundary trades booked on pre-window open dates.

## Remaining known gap

14 orphaned stock sells (SOUN, FMET, HIMS, SPLG ×3, VTI ×3, VUZI, SPYM, PANW,
FBTC) from Jul 2025 – Feb 2026 still lack purchase basis: their recurring buys
happened before 2025-10-01, outside this export, and recurring buys never
generate parseable execution emails. Fix requires an older Robinhood activity
export (anything covering back to when those recurring plans started); the
backfill process used here can then be repeated. This gap predates today and
does not affect the reconciled window above.
