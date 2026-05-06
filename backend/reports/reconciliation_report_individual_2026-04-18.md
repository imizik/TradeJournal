# Reconciliation Report

Generated: `2026-04-18 00:40:32`
Database: `backend\data\trade_journal.db`

## Headline

| Metric | Amount | Notes |
| --- | --- | --- |
| Dashboard total_pnl | $-2,127.21 | Closed + expired realized P&L only, matching /stats |
| All realized P&L including open trades | $-2,070.69 | Adds realized P&L already locked in on still-open positions |
| Realized P&L hidden inside open trades | $56.52 | Currently excluded from dashboard because those trades are still open |
| Open trade basis | $4,261.85 | Current open positions are all stocks; mark-to-market is not in the DB |

## Coverage By Account

| Account | Non-manual fills | Non-manual range | Manual fills | Closed/expired P&L | All realized | Open realized | Open trades | Open basis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Individual 1113 | 50 | 2025-12-12 to 2026-04-17 | 0 | $-821.50 | $-821.50 | $0.00 | 0 | $0.00 |
| Roth IRA | 303 | 2025-07-10 to 2025-09-03 | 0 | $-1,746.28 | $-1,746.28 | $0.00 | 2 | $700.00 |
| Roth IRA 8267 | 3032 | 2025-09-04 to 2026-04-17 | 3 | $440.57 | $497.09 | $56.52 | 9 | $3,561.85 |

## Requested Robinhood CSV Comparison

| Field | Value |
| --- | --- |
| Path | backend\Robinhood\Jul2023 to April2026.csv |
| Account scope | Individual 1113 |
| DB accounts combined | Individual 1113 |
| CSV date range | 2025-12-09 to 2026-04-02 |
| Rows with dates | 59 |
| Executable trade rows | 55 |
| Ignored non-trade rows | ACH: 1, OEXP: 3 |
| DB fill rows in overlap | 48 |
| CSV normalized fill keys | 45 |
| DB normalized fill keys | 45 |
| Exact-match keys | 45 |
| Mismatch keys | 0 |
| Closed/expired P&L through CSV max date | $-803.50 |
| Closed/expired trades after CSV max date | 1 trade(s), $-18.00 |
| Verdict | Exact match across the overlap window. |

## Discrepancy Buckets

| Bucket | Count | Amount | Why it matters |
| --- | --- | --- | --- |
| Orphaned or over-closed stock sells | 16 | $9,096.82 | These sales have no matching opening buy in the DB, so their true realized P&L cannot be computed |
| Option close anomalies | 4 | $758.00 | These option closes are orphaned or over-sized, so the realized P&L is only partially represented |
| Total anomalies | 20 | - | Any anomaly weakens broker-vs-app reconciliation until the missing source fills are backfilled |

### Anomaly Breakdown

| Instrument | Side | Kind | Count | Gross notional |
| --- | --- | --- | --- | --- |
| option | sell_to_close | orphaned | 1 | $78.00 |
| option | sell_to_close | over_close | 3 | $680.00 |
| stock | sell | orphaned | 15 | $8,677.44 |
| stock | sell | over_close | 1 | $419.38 |

### Unmatched Stock Sales

| Date | Account | Ticker | Shares | Price | Gross proceeds |
| --- | --- | --- | --- | --- | --- |
| 2025-07-29 | Roth IRA | FMET | 3.000000 | $35.24 | $105.72 |
| 2025-07-30 | Roth IRA | HIMS | 1.000000 | $64.99 | $64.99 |
| 2025-07-30 | Roth IRA | SPLG | 4.011760 | $74.77 | $299.96 |
| 2025-07-30 | Roth IRA | ASTS | 1.820490 | $54.91 | $99.96 |
| 2025-07-30 | Roth IRA | VTI | 0.319550 | $312.93 | $100.00 |
| 2025-08-12 | Roth IRA | VUZI | 44.000000 | $2.14 | $94.16 |
| 2025-08-20 | Roth IRA | VTI | 1.913570 | $313.54 | $599.98 |
| 2025-08-20 | Roth IRA | SPLG | 2.665240 | $75.03 | $199.97 |
| 2025-08-21 | Roth IRA | SPLG | 2.671110 | $74.88 | $200.01 |
| 2025-10-31 | Roth IRA 8267 | SPYM | 14.651890 | $80.46 | $1,178.89 |
| 2025-11-05 | Roth IRA 8267 | VTI | 12.000000 | $331.89 | $3,982.68 |
| 2025-11-05 | Roth IRA 8267 | VTI | 0.766880 | $331.83 | $254.47 |
| 2025-12-23 | Roth IRA 8267 | PANW | 2.000000 | $187.90 | $375.80 |
| 2026-01-27 | Roth IRA 8267 | UNH | 1.908390 | $283.28 | $540.61 |
| 2026-01-27 | Roth IRA 8267 | CNC | 10.139738 | $41.36 | $419.38 |
| 2026-02-03 | Roth IRA 8267 | FBTC | 9.000000 | $64.47 | $580.23 |

### Option Close Anomalies

| Date | Account | Ticker | Contracts | Price | Contract | Issue |
| --- | --- | --- | --- | --- | --- | --- |
| 2025-07-16 | Roth IRA | SOUN | 3.000000 | $26.00 | call 14.00 exp 2025-08-01 | Orphaned close |
| 2025-07-25 | Roth IRA | COIN | 3.000000 | $15.00 | put 375.00 exp 2025-07-25 | Over-close |
| 2025-11-07 | Roth IRA 8267 | LMND | 3.000000 | $20.00 | put 68.00 exp 2025-11-07 | Over-close |
| 2026-04-17 | Roth IRA 8267 | SPY | 5.000000 | $115.00 | put 710.00 exp 2026-04-17 | Over-close |

## Monthly Closed/Expired Realized P&L

| Month | Individual 1113 | Roth IRA 8267 | Total |
| --- | --- | --- | --- |
| 2025-07 | $0.00 | $0.00 | $0.00 |
| 2025-08 | $0.00 | $0.00 | $0.00 |
| 2025-09 | $0.00 | $3,038.00 | $3,038.00 |
| 2025-10 | $0.00 | $244.06 | $244.06 |
| 2025-11 | $0.00 | $1,138.61 | $1,138.61 |
| 2025-12 | $86.00 | $-200.63 | $-114.63 |
| 2026-01 | $-118.00 | $-1,179.31 | $-1,297.31 |
| 2026-02 | $-234.00 | $-2,177.76 | $-2,411.76 |
| 2026-03 | $-478.50 | $-295.00 | $-773.50 |
| 2026-04 | $-77.00 | $-127.40 | $-204.40 |

## Monthly Net Trade Cash Flow

| Month | Individual 1113 | Roth IRA 8267 | Total |
| --- | --- | --- | --- |
| 2025-07 | $0.00 | $0.00 | $0.00 |
| 2025-08 | $0.00 | $0.00 | $0.00 |
| 2025-09 | $0.00 | $1,631.95 | $1,631.95 |
| 2025-10 | $0.00 | $23.57 | $23.57 |
| 2025-11 | $0.00 | $5,384.32 | $5,384.32 |
| 2025-12 | $86.00 | $334.51 | $420.51 |
| 2026-01 | $-118.00 | $203.74 | $85.74 |
| 2026-02 | $-234.00 | $-376.53 | $-610.53 |
| 2026-03 | $-478.50 | $526.75 | $48.25 |
| 2026-04 | $-77.00 | $2,199.83 | $2,122.83 |

Net trade cash flow is not the same thing as realized P&L. It is useful here because it shows months with large cash exits or entries even when the reconstructor cannot fully match basis.

## Largest Contributors

### Biggest Winners

| Account | Ticker | Type | Closed/expired P&L | Trades |
| --- | --- | --- | --- | --- |
| Roth IRA 8267 | LLY | option | $5,422.00 | 40 |
| Roth IRA 8267 | SPY | option | $3,746.01 | 161 |
| Roth IRA 8267 | CAT | option | $1,440.00 | 21 |
| Roth IRA 8267 | GS | option | $1,159.00 | 12 |
| Roth IRA 8267 | COIN | option | $1,150.00 | 38 |
| Roth IRA 8267 | GLD | option | $1,009.00 | 21 |
| Roth IRA 8267 | META | option | $962.00 | 19 |
| Roth IRA 8267 | BIDU | option | $883.00 | 3 |
| Roth IRA 8267 | AAPL | option | $865.00 | 24 |
| Roth IRA 8267 | NFLX | option | $850.00 | 18 |

### Biggest Losers

| Account | Ticker | Type | Closed/expired P&L | Trades |
| --- | --- | --- | --- | --- |
| Roth IRA 8267 | SLV | option | $-1,972.00 | 16 |
| Roth IRA 8267 | CVNA | option | $-1,682.00 | 61 |
| Roth IRA 8267 | AMD | option | $-1,500.00 | 38 |
| Roth IRA 8267 | MSFT | option | $-1,310.00 | 34 |
| Roth IRA 8267 | COST | option | $-1,194.00 | 4 |
| Roth IRA 8267 | SNDK | option | $-1,187.99 | 29 |
| Roth IRA | COIN | option | $-1,014.00 | 7 |
| Roth IRA 8267 | TSLA | option | $-932.00 | 28 |
| Individual 1113 | SPY | option | $-865.00 | 10 |
| Roth IRA | AMD | option | $-843.00 | 10 |

## Takeaways

- The dashboard number is not a broker-equity number. It is realized P&L on trades that the reconstructor considers closed or expired.
- Unrealized stock P&L is definitely missing, but the larger reconciliation blocker is missing basis on orphaned stock sells.
- The Roth CSV compares materially better when both `roth_ira` accounts are treated as one logical account.
- Combined Roth still has residual discrepancy buckets: quantity mismatches, symbol drift, date drift, and small rounding deltas.

## Suggested Next Steps

1. Backfill or normalize the remaining Roth mismatch families before treating the CSV as a broker-perfect reconciliation source.
2. Decide whether the blank-last4 Roth account should be merged or relabeled now that the Roth CSV clearly spans both DB accounts.
3. Keep using the fill-level comparison rather than dashboard P&L when validating broker CSV imports.
