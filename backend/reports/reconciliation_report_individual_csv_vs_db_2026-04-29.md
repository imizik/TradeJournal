# Reconciliation Report

Generated: `2026-04-29 02:27:33`
Database: `backend\data\trade_journal.db`

## Headline

| Metric | Amount | Notes |
| --- | --- | --- |
| Dashboard total_pnl | $2,016.04 | Closed + expired realized P&L only, matching /stats |
| All realized P&L including open trades | $2,137.43 | Adds realized P&L already locked in on still-open positions |
| Realized P&L hidden inside open trades | $121.39 | Currently excluded from dashboard because those trades are still open |
| Open trade basis | $3,826.57 | Current open positions are all stocks; mark-to-market is not in the DB |

## Coverage By Account

| Account | Non-manual fills | Non-manual range | Manual fills | Closed/expired P&L | All realized | Open realized | Open trades | Open basis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Individual 1113 | 50 | 2025-12-12 to 2026-04-17 | 0 | $-821.50 | $-821.50 | $0.00 | 0 | $0.00 |
| Roth IRA 8267 | 3368 | 2025-07-10 to 2026-04-28 | 3 | $2,837.54 | $2,958.93 | $121.39 | 10 | $3,826.57 |

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
| Orphaned or over-closed stock sells | 13 | $8,036.87 | These sales have no matching opening buy in the DB, so their true realized P&L cannot be computed |
| Option close anomalies | 2 | $538.00 | These option closes are orphaned or over-sized, so the realized P&L is only partially represented |
| Total anomalies | 15 | - | Any anomaly weakens broker-vs-app reconciliation until the missing source fills are backfilled |

### Anomaly Breakdown

| Instrument | Side | Kind | Count | Gross notional |
| --- | --- | --- | --- | --- |
| option | sell_to_close | orphaned | 2 | $538.00 |
| stock | sell | orphaned | 13 | $8,036.87 |

### Unmatched Stock Sales

| Date | Account | Ticker | Shares | Price | Gross proceeds |
| --- | --- | --- | --- | --- | --- |
| 2025-07-29 | Roth IRA 8267 | FMET | 3.000000 | $35.24 | $105.72 |
| 2025-07-30 | Roth IRA 8267 | HIMS | 1.000000 | $64.99 | $64.99 |
| 2025-07-30 | Roth IRA 8267 | SPLG | 4.011760 | $74.77 | $299.96 |
| 2025-07-30 | Roth IRA 8267 | VTI | 0.319550 | $312.93 | $100.00 |
| 2025-08-12 | Roth IRA 8267 | VUZI | 44.000000 | $2.14 | $94.16 |
| 2025-08-20 | Roth IRA 8267 | VTI | 1.913570 | $313.54 | $599.98 |
| 2025-08-20 | Roth IRA 8267 | SPLG | 2.665240 | $75.03 | $199.97 |
| 2025-08-21 | Roth IRA 8267 | SPLG | 2.671110 | $74.88 | $200.01 |
| 2025-10-31 | Roth IRA 8267 | SPYM | 14.651890 | $80.46 | $1,178.89 |
| 2025-11-05 | Roth IRA 8267 | VTI | 12.000000 | $331.89 | $3,982.68 |
| 2025-11-05 | Roth IRA 8267 | VTI | 0.766880 | $331.83 | $254.47 |
| 2025-12-23 | Roth IRA 8267 | PANW | 2.000000 | $187.90 | $375.80 |
| 2026-02-03 | Roth IRA 8267 | FBTC | 9.000000 | $64.47 | $580.23 |

### Option Close Anomalies

| Date | Account | Ticker | Contracts | Price | Contract | Issue |
| --- | --- | --- | --- | --- | --- | --- |
| 2025-07-16 | Roth IRA 8267 | SOUN | 3.000000 | $26.00 | call 14.00 exp 2025-08-01 | Orphaned close |
| 2026-04-17 | Roth IRA 8267 | SPY | 4.000000 | $115.00 | put 710.00 exp 2026-04-17 | Orphaned close |

## Monthly Closed/Expired Realized P&L

| Month | Individual 1113 | Roth IRA 8267 | Total |
| --- | --- | --- | --- |
| 2025-07 | $0.00 | $-1,426.28 | $-1,426.28 |
| 2025-08 | $0.00 | $-312.00 | $-312.00 |
| 2025-09 | $0.00 | $3,162.00 | $3,162.00 |
| 2025-10 | $0.00 | $633.06 | $633.06 |
| 2025-11 | $0.00 | $1,133.61 | $1,133.61 |
| 2025-12 | $86.00 | $-200.63 | $-114.63 |
| 2026-01 | $-118.00 | $-1,051.18 | $-1,169.18 |
| 2026-02 | $-234.00 | $1,074.24 | $840.24 |
| 2026-03 | $-478.50 | $-295.00 | $-773.50 |
| 2026-04 | $-77.00 | $119.72 | $42.72 |

## Monthly Net Trade Cash Flow

| Month | Individual 1113 | Roth IRA 8267 | Total |
| --- | --- | --- | --- |
| 2025-07 | $0.00 | $-1,282.65 | $-1,282.65 |
| 2025-08 | $0.00 | $165.13 | $165.13 |
| 2025-09 | $0.00 | $2,220.95 | $2,220.95 |
| 2025-10 | $0.00 | $148.57 | $148.57 |
| 2025-11 | $0.00 | $5,359.32 | $5,359.32 |
| 2025-12 | $86.00 | $334.51 | $420.51 |
| 2026-01 | $-118.00 | $203.74 | $85.74 |
| 2026-02 | $-234.00 | $-75.53 | $-309.53 |
| 2026-03 | $-478.50 | $526.75 | $48.25 |
| 2026-04 | $-77.00 | $2,118.15 | $2,041.15 |

Net trade cash flow is not the same thing as realized P&L. It is useful here because it shows months with large cash exits or entries even when the reconstructor cannot fully match basis.

## Largest Contributors

### Biggest Winners

| Account | Ticker | Type | Closed/expired P&L | Trades |
| --- | --- | --- | --- | --- |
| Roth IRA 8267 | LLY | option | $5,625.00 | 41 |
| Roth IRA 8267 | SPY | option | $3,769.01 | 164 |
| Roth IRA 8267 | CAT | option | $1,396.00 | 23 |
| Roth IRA 8267 | GS | option | $1,323.00 | 13 |
| Roth IRA 8267 | GLD | option | $1,009.00 | 21 |
| Roth IRA 8267 | AMD | option | $959.00 | 49 |
| Roth IRA 8267 | BIDU | option | $883.00 | 3 |
| Roth IRA 8267 | AAPL | option | $865.00 | 24 |
| Individual 1113 | GLD | option | $788.00 | 3 |
| Roth IRA 8267 | META | option | $783.00 | 26 |

### Biggest Losers

| Account | Ticker | Type | Closed/expired P&L | Trades |
| --- | --- | --- | --- | --- |
| Roth IRA 8267 | SLV | option | $-1,972.00 | 16 |
| Roth IRA 8267 | CVNA | option | $-1,957.00 | 68 |
| Roth IRA 8267 | COST | option | $-1,194.00 | 4 |
| Roth IRA 8267 | SNDK | option | $-1,187.99 | 29 |
| Roth IRA 8267 | NVDA | option | $-1,042.04 | 35 |
| Roth IRA 8267 | MSFT | option | $-973.00 | 40 |
| Roth IRA 8267 | TSLA | option | $-932.00 | 28 |
| Individual 1113 | SPY | option | $-865.00 | 10 |
| Roth IRA 8267 | MSTR | option | $-674.00 | 16 |
| Roth IRA 8267 | ADBE | option | $-638.00 | 3 |

## Takeaways

- The dashboard number is not a broker-equity number. It is realized P&L on trades that the reconstructor considers closed or expired.
- Unrealized stock P&L is definitely missing, but the larger reconciliation blocker is missing basis on orphaned stock sells.
- The Roth CSV compares materially better when both `roth_ira` accounts are treated as one logical account.
- Combined Roth still has residual discrepancy buckets: quantity mismatches, symbol drift, date drift, and small rounding deltas.

## Suggested Next Steps

1. Backfill or normalize the remaining Roth mismatch families before treating the CSV as a broker-perfect reconciliation source.
2. Decide whether the blank-last4 Roth account should be merged or relabeled now that the Roth CSV clearly spans both DB accounts.
3. Keep using the fill-level comparison rather than dashboard P&L when validating broker CSV imports.
