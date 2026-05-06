# Reconciliation Report

Generated: `2026-04-17 19:47:26`
Database: `backend\data\trade_journal.db`

## Headline

| Metric | Amount | Notes |
| --- | --- | --- |
| Dashboard total_pnl | $-1,999.08 | Closed + expired realized P&L only, matching /stats |
| All realized P&L including open trades | $-1,896.17 | Adds realized P&L already locked in on still-open positions |
| Realized P&L hidden inside open trades | $102.91 | Currently excluded from dashboard because those trades are still open |
| Open trade basis | $3,561.85 | Current open positions are all stocks; mark-to-market is not in the DB |

## Coverage By Account

| Account | Non-manual fills | Non-manual range | Manual fills | Closed/expired P&L | All realized | Open realized | Open trades | Open basis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Individual 1113 | 50 | 2025-12-12 to 2026-04-17 | 0 | $-821.50 | $-821.50 | $0.00 | 0 | $0.00 |
| Roth IRA 8267 | 3335 | 2025-07-10 to 2026-04-17 | 3 | $-1,177.58 | $-1,074.67 | $102.91 | 9 | $3,561.85 |

## Current Robinhood CSV

| Field | Value |
| --- | --- |
| Path | backend\Robinhood\Jul2023 to April2026.csv |
| CSV date range | 2025-12-09 to 2026-04-02 |
| Rows with dates | 59 |
| Executable trade rows | 55 |
| Expiration rows | 3 |
| ACH rows | 1 |
| DB realized P&L through CSV max date (Individual 1113) | $-803.50 |
| Trades after CSV max date (Individual 1113) | 1 trade(s), $-18.00 |
| CSV vs DB overlap check | No fill-level economic mismatches found in the overlapping window. |

## Discrepancy Buckets

| Bucket | Count | Amount | Why it matters |
| --- | --- | --- | --- |
| Orphaned or over-closed stock sells | 13 | $8,036.87 | These sales have no matching opening buy in the DB, so their true realized P&L cannot be computed |
| Option close anomalies | 4 | $758.00 | These option closes are orphaned or over-sized, so the realized P&L is only partially represented |
| Total anomalies | 17 | - | Any anomaly weakens broker-vs-app reconciliation until the missing source fills are backfilled |

### Anomaly Breakdown

| Instrument | Side | Kind | Count | Gross notional |
| --- | --- | --- | --- | --- |
| option | sell_to_close | orphaned | 1 | $78.00 |
| option | sell_to_close | over_close | 3 | $680.00 |
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
| 2025-07-25 | Roth IRA 8267 | COIN | 3.000000 | $15.00 | put 375.00 exp 2025-07-25 | Over-close |
| 2025-11-07 | Roth IRA 8267 | LMND | 3.000000 | $20.00 | put 68.00 exp 2025-11-07 | Over-close |
| 2026-04-17 | Roth IRA 8267 | SPY | 5.000000 | $115.00 | put 710.00 exp 2026-04-17 | Over-close |

## Monthly Closed/Expired Realized P&L

| Month | Individual 1113 | Roth IRA 8267 | Total |
| --- | --- | --- | --- |
| 2025-07 | $0.00 | $-1,426.28 | $-1,426.28 |
| 2025-08 | $0.00 | $-312.00 | $-312.00 |
| 2025-09 | $0.00 | $3,030.00 | $3,030.00 |
| 2025-10 | $0.00 | $244.06 | $244.06 |
| 2025-11 | $0.00 | $1,138.61 | $1,138.61 |
| 2025-12 | $86.00 | $-200.63 | $-114.63 |
| 2026-01 | $-118.00 | $-1,051.18 | $-1,169.18 |
| 2026-02 | $-234.00 | $-2,177.76 | $-2,411.76 |
| 2026-03 | $-478.50 | $-295.00 | $-773.50 |
| 2026-04 | $-77.00 | $-127.40 | $-204.40 |

## Monthly Net Trade Cash Flow

| Month | Individual 1113 | Roth IRA 8267 | Total |
| --- | --- | --- | --- |
| 2025-07 | $0.00 | $-1,252.65 | $-1,252.65 |
| 2025-08 | $0.00 | $165.13 | $165.13 |
| 2025-09 | $0.00 | $2,145.95 | $2,145.95 |
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
| Roth IRA 8267 | LLY | option | $5,625.00 | 41 |
| Roth IRA 8267 | SPY | option | $3,699.01 | 162 |
| Roth IRA 8267 | CAT | option | $1,396.00 | 23 |
| Roth IRA 8267 | GS | option | $1,323.00 | 13 |
| Roth IRA 8267 | GLD | option | $1,009.00 | 21 |
| Roth IRA 8267 | BIDU | option | $883.00 | 3 |
| Roth IRA 8267 | AAPL | option | $865.00 | 24 |
| Roth IRA 8267 | META | option | $855.00 | 24 |
| Individual 1113 | GLD | option | $788.00 | 3 |
| Roth IRA 8267 | NFLX | option | $630.00 | 20 |

### Biggest Losers

| Account | Ticker | Type | Closed/expired P&L | Trades |
| --- | --- | --- | --- | --- |
| Roth IRA 8267 | AMD | option | $-2,343.00 | 48 |
| Roth IRA 8267 | SLV | option | $-1,972.00 | 16 |
| Roth IRA 8267 | CVNA | option | $-1,957.00 | 68 |
| Roth IRA 8267 | COST | option | $-1,194.00 | 4 |
| Roth IRA 8267 | SNDK | option | $-1,187.99 | 29 |
| Roth IRA 8267 | MSFT | option | $-1,121.00 | 38 |
| Roth IRA 8267 | NVDA | option | $-1,042.04 | 35 |
| Roth IRA 8267 | TSLA | option | $-932.00 | 28 |
| Individual 1113 | SPY | option | $-865.00 | 10 |
| Roth IRA 8267 | PLTR | option | $-715.00 | 28 |

## Takeaways

- The dashboard number is not a broker-equity number. It is realized P&L on trades that the reconstructor considers closed or expired.
- Unrealized stock P&L is definitely missing, but the larger reconciliation blocker is missing basis on orphaned stock sells.
- The current Robinhood CSV is only an Individual-account slice from 2025-12-09 through 2026-04-02. It cannot explain your full real-life result on its own.
- The Roth IRA account has only three manual seed buys in the DB: NVDA, ASTS, and AMZN. The unmatched sells suggest there are still more starting stock positions to backfill.

## Suggested Next Steps

1. Seed the missing stock opening positions for FMET, HIMS, SPLG, VTI, VUZI, SPYM, PANW, and FBTC before their first sale dates.
2. Decide whether the dashboard should expose a second metric for `realized_any_status`, so partial stock exits are visible even while a position remains open.
3. Reconcile one account at a time. The current Individual CSV overlaps cleanly with the DB, but your headline discrepancy is dominated by Roth IRA history.
4. If you want a true broker-comparable figure, we still need either complete pre-sale basis history or a CSV export that includes opening stock positions and transfers.
