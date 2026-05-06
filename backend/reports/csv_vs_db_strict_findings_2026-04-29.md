# CSV vs DB Strict Findings

Generated: `2026-04-29 02:29:23`
CSV source of truth: `backend\Robinhood\Jul2023 to April2026.csv`
Database: `backend\data\trade_journal.db`
Compared DB account: `Individual 1113` (`9e3371be8bf94c879d5b500d07f12c8d`)

## Summary

| Metric | Value |
| --- | --- |
| CSV dated rows | 59 |
| CSV executable rows | 55 |
| CSV ignored non-trade rows | ACH: 1, OEXP: 3 |
| CSV date range | 2025-12-09 to 2026-04-02 |
| CSV normalized fill keys | 45 |
| DB Individual fill rows | 50 |
| DB normalized fill keys across all dates | 47 |
| DB normalized fill keys inside CSV date range | 45 |
| Exact normalized keys inside CSV date range | 45 |
| Strict mismatched normalized keys across all DB dates | 2 |
| CSV net trade cash flow | $-803.50 |
| DB net trade cash flow inside CSV range | $-803.50 |
| DB net trade cash flow across all Individual fills | $-821.50 |
| DB cash-flow delta vs CSV | $-18.00 |

## Findings

- Inside the CSV date range, normalized fills match exactly: quantity and notional agree for every key within a $0.02 tolerance.
- Strict source-of-truth comparison found 2 DB-only normalized fill keys, both after the CSV ends on 2026-04-02.
- Those DB-only fills create one DB-only trade with realized P&L `$-18.00`.
- CSV row count and DB fill row count differ inside the overlap, but only because multiple Robinhood rows collapse to the same normalized economic key; aggregate quantity and notional match.

## Mismatch Buckets

| Bucket | Count |
| --- | --- |
| missing side / key | 2 |

## Fill Mismatches

| Key | Bucket | CSV qty | DB qty | CSV notional | DB notional | DB minus CSV | Note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-04-17 SPY option buy_to_open put 708.00 exp 2026-04-17 | missing side / key | 0 | 3 | $0.00 | $168.00 | $168.00 | The normalized key appears in only one source. |
| 2026-04-17 SPY option sell_to_close put 708.00 exp 2026-04-17 | missing side / key | 0 | 3 | $0.00 | $150.00 | $150.00 | The normalized key appears in only one source. |

## DB-Only Fill Rows

| Executed at | Ticker | Side | Qty | Price | Type | Strike | Expiration | raw_email_id |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-04-17 10:53:00.000000 | SPY | buy_to_open | 3 | $56.00 | put | 708.00 | 2026-04-17 | 19d9beed6b9b4a8c |
| 2026-04-17 11:08:00.000000 | SPY | sell_to_close | 3 | $50.00 | put | 708.00 | 2026-04-17 | 19d9bfcf34021b20 |

## Trade Comparison

| Metric | Value |
| --- | --- |
| DB Individual trades total | 25 |
| DB trades opened/closed inside CSV range | 24 |
| DB trades after CSV max date | 1 |
| DB realized P&L inside CSV range | $-803.50 |
| DB realized P&L after CSV max date | $-18.00 |

### DB-Only Trades After CSV Max Date

| Opened | Closed | Ticker | Type | Contract | Qty | Entry cost | Avg exit | Realized P&L | Status | Trade id |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-04-17 10:53:00.000000 | 2026-04-17 11:08:00.000000 | SPY | option | put 708.00 exp 2026-04-17 | 3 | $168.00 | $50.00 | $-18.00 | closed | e0e5570d722b4414b52a62bc6e6ea943 |

## Conclusion

The CSV matches the DB for Individual `1113` through `2026-04-02`. Treating the CSV as the complete source of truth, the DB currently has one extra Individual trade dated `2026-04-17`, represented by two extra SPY option fills.
