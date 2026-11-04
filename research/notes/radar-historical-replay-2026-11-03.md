# Historical Radar v0 and Movers replay

90 regular sessions, 2026-06-15 through 2026-10-21. All times are New York time.

| Method | Closing top-20 hits | Misses | Median minutes before close (hits) |
|---|---|---|---|
| Radar | 272/1800 (15.1%) | 1528 | 358 |
| Movers | 1681/1800 (93.4%) | 119 | 386 |

Among 266 stock-days both methods caught, median Movers time minus Radar time was -24 minutes (positive means Radar was earlier). Radar was earlier on 46, tied on 0, and later on 220.

| Method | Horizon | Continued in flag direction | Unscored | Mean directional vs SPY (pp) |
|---|---|---|---|---|
| Radar | +30 | 571/1161 (49.2%) | 30 | +0.04 |
| Radar | +60 | 530/1152 (46.0%) | 39 | -0.18 |
| Radar | +120 | 558/1129 (49.4%) | 62 | -0.03 |
| Movers | +30 | 2615/5305 (49.3%) | 102 | -0.04 |
| Movers | +60 | 2578/5248 (49.1%) | 159 | -0.04 |
| Movers | +120 | 2558/5136 (49.8%) | 271 | +0.01 |

## Reading the comparison

- Each day contributes the 20 tracked stocks with the largest absolute split-comparable daily close-to-close return minus SPY’s return. Ties at four decimal places go to the ticker first alphabetically. A hit requires a first sighting on the closing move’s side by 16:00. A miss means no such sighting in the available minutes. Lead time runs from that sighting to the close, including zero for a closing-minute hit.
- Radar uses frozen radar-rules-v0 on minute passes. Stock vs SPY and stock vs sector flags count as stock hits. Group events and their originally flagged members are listed separately. Revisions are excluded. Movers uses the unchanged top 10 leaders and 10 laggards each minute. Its flag is the first appearance per stock and side per day. This ranking includes opening gaps, while Radar needs a persistent intraday move.
- Individual flag rows show the raw subsequent stock return minus SPY in percentage points, including for down flags. The continuation summary signs those values by flag direction. Group returns equally weight the flagged members. A dash means the exact minute was outside regular hours or an endpoint for SPY or any member was missing. Each method’s continuation rate uses its own scored flags.
- Inputs are historical Alpaca SIP bars. A 09:30 bar first becomes a quote at 09:31. Each pass uses only the just-completed minute’s close and its start as the conservative trade-time proxy. Empty minutes stay empty. Previous close comes from the preceding scheduled session’s split-adjusted daily close, converted to that day’s raw share units using the current raw/split opening-price ratio. Daily closing prices are used only to label the top 20 after the session. This reconstructs minute-end sightings, with different print timing and coverage from Tradier’s live snapshots.
- The fixed radar-universe-v2 roster contains 169 symbols and was assembled after most of this period, which introduces selection bias. Coverage across all tracked names was 5,815,000/5,931,900 usable symbol-minutes. Each day lists exclusions. The pre-recorder sessions are separate from the live 20-session experiment.

Input SHA-256 (uncompressed daily then ordered minute snapshots): `3dbc7ff911be3d390cddbd782c9fc3d07450abc4f7fd3fc0e44ed54f2b81b6b3`. Roster SHA-256 (sorted-key JSON): `ddd112a46ffe90edfe71e379deb93fd682acf75bbbf1c14164fa79f394b18c3c`.

From `backend`, run `ALPACA_DATA_FEED=sip python -m scripts.radar_historical_replay fetch SNAPSHOT --cache-root /path/to/alpaca_cache`, then `python -m scripts.radar_historical_replay report SNAPSHOT --out REPORT.md`. The second step runs offline.

## 2026-06-15

Usable symbol-minutes 64,811/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | WDC | +14.33 | miss | 09:31 |
| 2 | AAOI | +11.55 | miss | 09:31 |
| 3 | HIMS | +10.73 | miss | 10:36 |
| 4 | QBTS | +10.60 | miss | 09:31 |
| 5 | RDDT | +10.44 | miss | 10:19 |
| 6 | NBIS | +10.16 | miss | 09:31 |
| 7 | QUBT | +10.02 | miss | 09:31 |
| 8 | DASH | +9.87 | miss | 10:08 |
| 9 | MU | +9.07 | miss | 09:31 |
| 10 | MRVL | +8.67 | miss | 09:31 |
| 11 | STX | +7.66 | miss | 09:31 |
| 12 | APLD | +7.07 | miss | 09:37 |
| 13 | SNAP | +6.79 | miss | miss |
| 14 | ARM | +6.57 | miss | miss |
| 15 | RGTI | +6.43 | miss | 09:31 |
| 16 | WULF | +6.33 | miss | miss |
| 17 | XOM | -5.91 | miss | 09:31 |
| 18 | IRDM | -5.84 | miss | 09:32 |
| 19 | COP | -5.80 | miss | 09:31 |
| 20 | CVNA | +5.72 | miss | 09:33 |

### Radar flags (6)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | AI networking and connectivity (COHR, MRVL, CRDO, AVGO, ANET) | group_move | down | +1.18 | +0.84 | +1.61 |
| 10:09 | ALAB | relative_to_spy | up | +0.26 | +2.25 | +1.58 |
| 10:17 | Space (PL, ASTS, LUNR, RKLB, IRDM) | group_move | down | -0.50 | -1.30 | +0.72 |
| 10:23 | Quantum computing (QBTS, RGTI, QUBT, IONQ) | group_move | down | +0.81 | +0.59 | +2.01 |
| 11:12 | Quantum computing (QUBT, RGTI, QBTS, IONQ) | group_move | down | +1.06 | +2.17 | +2.52 |
| 12:19 | Space (ASTS, RKLB, LUNR, PL, IRDM) | group_move | up | -0.96 | -0.74 | -0.63 |

### Movers flags (47)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | WDC | leaders | up | +1.96 | +3.95 | +4.23 |
| 09:31 | NBIS | leaders | up | -1.51 | -2.75 | -0.15 |
| 09:31 | AAOI | leaders | up | -0.64 | +2.11 | +1.48 |
| 09:31 | QUBT | leaders | up | +3.80 | +2.79 | +2.41 |
| 09:31 | QBTS | leaders | up | +4.54 | +3.35 | +2.43 |
| 09:31 | MU | leaders | up | -0.93 | +0.55 | +0.87 |
| 09:31 | STX | leaders | up | -1.14 | +1.05 | +0.52 |
| 09:31 | RGTI | leaders | up | +2.88 | +1.77 | +0.69 |
| 09:31 | MRVL | leaders | up | -3.70 | -1.74 | -1.86 |
| 09:31 | COHR | leaders | up | -4.42 | -2.75 | -2.05 |
| 09:31 | OXY | laggards | down | +0.93 | +1.38 | +1.80 |
| 09:31 | XOM | laggards | down | -0.37 | +0.79 | +0.95 |
| 09:31 | COP | laggards | down | -0.70 | -0.19 | +0.26 |
| 09:31 | SHEL | laggards | down | -0.18 | +0.11 | +0.43 |
| 09:31 | CVX | laggards | down | -0.42 | +0.23 | +0.11 |
| 09:31 | CNC | laggards | down | -1.20 | -1.18 | -0.99 |
| 09:31 | MRK | laggards | down | -1.55 | -1.41 | -1.23 |
| 09:31 | HUM | laggards | down | -1.36 | -1.04 | -1.27 |
| 09:31 | CVS | laggards | down | -0.83 | -0.94 | -0.75 |
| 09:31 | COST | laggards | down | -0.11 | +0.51 | -0.01 |
| 09:32 | MSTR | leaders | up | -2.37 | -1.85 | -0.57 |
| 09:32 | IRDM | laggards | down | -1.07 | -2.04 | -3.22 |
| 09:32 | CRWD | laggards | down | +2.41 | +2.19 | +2.63 |
| 09:32 | PANW | laggards | down | +2.61 | +2.90 | +2.35 |
| 09:33 | CVNA | leaders | up | +0.13 | -0.42 | -0.22 |
| 09:33 | IBM | laggards | down | +0.46 | +0.26 | +0.82 |
| 09:33 | ARM | laggards | down | +2.12 | +5.28 | +5.35 |
| 09:35 | CRCL | leaders | up | -0.36 | +1.13 | +0.21 |
| 09:35 | CIFR | leaders | up | -0.89 | -1.65 | -1.85 |
| 09:35 | ELV | laggards | down | +1.90 | +1.65 | +2.16 |
| 09:36 | IONQ | leaders | up | -1.67 | -1.93 | -2.44 |
| 09:37 | APLD | leaders | up | -1.44 | -2.11 | -2.17 |
| 09:45 | ROKU | laggards | down | +0.15 | +1.13 | +0.76 |
| 09:46 | AMD | leaders | up | -0.53 | -1.54 | -1.93 |
| 09:48 | RCAT | leaders | up | -0.82 | -0.05 | -1.48 |
| 09:48 | CRDO | laggards | down | +2.55 | +4.31 | +5.60 |
| 10:08 | DASH | leaders | up | +1.24 | +2.21 | +2.80 |
| 10:19 | RDDT | leaders | up | +0.73 | +2.29 | +2.07 |
| 10:23 | LUNR | laggards | down | -0.40 | -0.81 | +1.21 |
| 10:25 | PL | laggards | down | +0.72 | -0.04 | +1.94 |
| 10:36 | HIMS | leaders | up | +0.65 | +1.22 | +2.22 |
| 11:15 | FLNC | laggards | down | +0.70 | +2.06 | +5.36 |
| 12:12 | UAA | laggards | down | +0.13 | -0.35 | -0.36 |
| 12:28 | HPQ | laggards | down | -0.19 | +0.05 | -0.32 |
| 13:26 | CPRT | laggards | down | -0.08 | -0.11 | -0.44 |
| 13:27 | CI | laggards | down | -0.52 | -0.02 | +0.09 |
| 14:31 | LULU | laggards | down | -0.34 | -0.19 | — |

## 2026-06-16

Usable symbol-minutes 64,792/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | CRWV | +10.27 | 10:02 | 09:31 |
| 2 | AAOI | -10.23 | 10:11 | 10:05 |
| 3 | MRVL | -9.18 | miss | 12:44 |
| 4 | SNAP | -9.04 | 10:24 | 09:35 |
| 5 | LUNR | -8.72 | 10:02 | 09:31 |
| 6 | RBLX | +8.66 | miss | 09:34 |
| 7 | RGTI | -8.48 | miss | 09:32 |
| 8 | RCAT | -8.34 | 10:04 | 09:46 |
| 9 | QBTS | -8.24 | miss | 09:32 |
| 10 | QUBT | -8.23 | miss | 09:31 |
| 11 | HSAI | -8.09 | miss | 09:31 |
| 12 | INTC | -7.86 | miss | 10:52 |
| 13 | IONQ | -7.77 | miss | 09:31 |
| 14 | CRDO | -7.20 | miss | 09:32 |
| 15 | PL | -7.15 | 10:02 | 09:31 |
| 16 | TTWO | +6.95 | miss | 11:24 |
| 17 | COHR | -6.90 | miss | 11:12 |
| 18 | AMD | -6.71 | miss | miss |
| 19 | CIEN | -6.55 | miss | 10:13 |
| 20 | ALAB | -6.47 | miss | 11:51 |

### Radar flags (25)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | CRWV | relative_to_spy | up | -2.48 | -1.20 | +0.04 |
| 10:02 | FLNC | relative_to_spy | up | -7.16 | -7.88 | -4.90 |
| 10:02 | LUNR | relative_to_spy | down | -1.72 | -0.03 | +0.09 |
| 10:02 | NBIS | relative_to_spy | up | -4.66 | -3.80 | -1.65 |
| 10:02 | PL | relative_to_spy | down | -1.42 | +0.19 | +2.25 |
| 10:02 | Neoclouds and AI hosting (NBIS, CRWV, APLD, ORCL, CIFR, WULF, IREN) | group_move | up | -2.91 | -2.15 | -0.97 |
| 10:02 | Space (PL, LUNR, ASTS, RKLB, IRDM) | group_move | down | -1.48 | -0.64 | +0.75 |
| 10:04 | RCAT | relative_to_spy | down | -1.67 | -0.07 | -0.69 |
| 10:04 | Cloud software and data (DDOG, SNOW, ORCL, ADBE, NOW, MDB, CRM) | group_move | up | -1.60 | -1.29 | -1.02 |
| 10:11 | AAOI | relative_to_spy | down | -1.68 | -2.15 | -1.78 |
| 10:12 | Quantum computing (QUBT, QBTS, RGTI, IONQ) | group_move | down | -0.67 | -0.36 | -0.68 |
| 10:19 | FLNC | relative_to_spy | down | -1.55 | -1.79 | -0.65 |
| 10:22 | AI software and analytics (SNOW, NOW, AI, PLTR, DDOG, APP) | group_move | down | -0.33 | +0.85 | +0.21 |
| 10:22 | Cloud software and data (MDB, SNOW, NOW, ORCL, CRM, DDOG, ADBE) | group_move | down | +0.19 | +1.18 | +0.37 |
| 10:24 | SNAP | relative_to_spy | down | +0.64 | +3.86 | +7.10 |
| 10:25 | Memory and storage (STX, WDC, SNDK, MU) | group_move | down | -0.78 | -2.31 | -0.58 |
| 10:26 | MDB | relative_to_spy | down | +0.22 | +1.75 | +1.27 |
| 10:33 | AI networking and connectivity (COHR, ALAB, CRDO, MRVL, AVGO, ANET) | group_move | down | -0.37 | -0.58 | -1.01 |
| 10:33 | Neoclouds and AI hosting (NBIS, IREN, APLD, CIFR, ORCL, CRWV, WULF) | group_move | down | +0.87 | +1.29 | +2.15 |
| 10:34 | NBIS | relative_to_spy | down | +0.74 | +1.25 | +2.93 |
| 10:34 | Bitcoin treasuries and miners (IREN, MSTR, MARA, COIN, RIOT, CLSK) | group_move | down | +0.73 | +1.08 | +1.64 |
| 10:34 | Crypto and exchanges (MSTR, MARA, CRCL, COIN, HOOD, RIOT, BULL) | group_move | down | +0.03 | +0.47 | +1.06 |
| 11:49 | AI networking and connectivity (MRVL, ALAB, CRDO, COHR, AVGO, ANET) | group_move | down | +1.28 | +1.30 | +1.34 |
| 12:15 | Memory and storage (WDC, SNDK, MU, STX) | group_move | up | +0.41 | +0.03 | -0.03 |
| 13:28 | SNAP | relative_to_spy | down | -2.15 | -3.74 | -5.20 |

### Movers flags (67)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | WDC | leaders | up | +2.54 | +0.07 | -2.23 |
| 09:31 | STX | leaders | up | +1.66 | -0.23 | -1.59 |
| 09:31 | QCOM | leaders | up | +1.05 | -0.66 | -3.29 |
| 09:31 | CRWV | leaders | up | +7.12 | +4.68 | +5.71 |
| 09:31 | CVNA | leaders | up | -1.17 | -2.33 | -0.03 |
| 09:31 | ALAB | leaders | up | -3.01 | -5.69 | -6.17 |
| 09:31 | HOOD | leaders | up | -1.24 | -3.15 | -4.49 |
| 09:31 | JPM | leaders | up | +0.54 | +1.05 | +1.71 |
| 09:31 | CIFR | leaders | up | +3.09 | +0.89 | +0.96 |
| 09:31 | SNDK | leaders | up | -1.57 | -3.27 | -4.65 |
| 09:31 | HSAI | laggards | down | -1.20 | -2.10 | -2.56 |
| 09:31 | BIDU | laggards | down | +0.82 | +0.28 | -0.09 |
| 09:31 | PL | laggards | down | -6.08 | -7.93 | -5.19 |
| 09:31 | ZS | laggards | down | +1.11 | +0.12 | +0.49 |
| 09:31 | LUNR | laggards | down | -4.94 | -7.25 | -5.86 |
| 09:31 | BABA | laggards | down | +0.57 | +0.14 | +0.53 |
| 09:31 | QUBT | laggards | down | -1.95 | -4.54 | -3.47 |
| 09:31 | PANW | laggards | down | +1.52 | +1.27 | +1.28 |
| 09:31 | RIVN | laggards | down | -0.16 | -2.16 | -1.31 |
| 09:31 | IONQ | laggards | down | -0.65 | -4.07 | -2.44 |
| 09:32 | KMX | leaders | up | -1.16 | -0.47 | -1.02 |
| 09:32 | ARM | leaders | up | +0.06 | -2.61 | -2.65 |
| 09:32 | QBTS | laggards | down | +0.06 | -4.54 | -2.26 |
| 09:32 | RGTI | laggards | down | -0.77 | -4.80 | -3.25 |
| 09:32 | CRDO | laggards | down | +1.66 | -2.02 | -1.65 |
| 09:33 | RIOT | leaders | up | +0.98 | -0.76 | -0.18 |
| 09:33 | CAT | leaders | up | +0.24 | -0.33 | +0.64 |
| 09:33 | IRDM | laggards | down | -1.08 | -2.63 | -2.30 |
| 09:34 | RBLX | leaders | up | +0.19 | -1.53 | +1.43 |
| 09:35 | HD | leaders | up | -0.12 | +0.64 | +0.15 |
| 09:35 | CMI | leaders | up | +0.13 | +0.16 | +0.58 |
| 09:35 | SNAP | laggards | down | +0.53 | -1.78 | +1.91 |
| 09:36 | COIN | leaders | up | -0.48 | -2.51 | -1.12 |
| 09:36 | WFC | leaders | up | -0.47 | -0.18 | +0.02 |
| 09:36 | FTNT | laggards | down | +1.99 | +2.08 | +1.40 |
| 09:37 | PYPL | leaders | up | +0.15 | -0.19 | +0.03 |
| 09:37 | LOW | leaders | up | -0.80 | +0.23 | -0.34 |
| 09:38 | NBIS | leaders | up | +2.69 | +0.06 | +0.02 |
| 09:38 | APLD | leaders | up | +2.97 | +0.49 | -1.19 |
| 09:39 | APP | laggards | down | -0.19 | -0.55 | +0.25 |
| 09:39 | CRWD | laggards | down | +1.98 | +1.92 | +2.44 |
| 09:41 | FLNC | leaders | up | -0.34 | -4.06 | -5.81 |
| 09:42 | DDOG | laggards | down | +2.14 | +2.72 | +3.82 |
| 09:43 | WULF | leaders | up | -0.89 | -0.52 | -1.70 |
| 09:43 | RKLB | laggards | down | -1.62 | +0.06 | -0.09 |
| 09:46 | RCAT | laggards | down | -3.62 | -4.52 | -5.13 |
| 09:47 | CNC | laggards | down | +0.67 | -0.25 | +0.41 |
| 09:52 | MARA | leaders | up | -1.86 | -1.38 | -2.07 |
| 09:53 | ASTS | laggards | down | -2.09 | -1.24 | -1.78 |
| 09:57 | SOFI | leaders | up | -2.64 | -2.15 | -1.18 |
| 10:05 | AAOI | laggards | down | -4.22 | -4.24 | -3.40 |
| 10:06 | CLSK | leaders | up | -1.10 | +0.41 | +0.71 |
| 10:13 | HIMS | leaders | up | +0.65 | +1.87 | +2.51 |
| 10:13 | CIEN | laggards | down | -1.00 | -1.85 | -1.51 |
| 10:15 | LCID | laggards | down | -0.19 | +0.89 | +1.36 |
| 10:33 | DASH | leaders | up | +0.30 | +0.27 | -0.30 |
| 10:33 | WMT | leaders | up | -0.85 | -0.66 | -1.09 |
| 10:34 | DE | leaders | up | -0.26 | +0.22 | — |
| 10:52 | INTC | laggards | down | -0.23 | -1.57 | -0.60 |
| 10:59 | ADBE | leaders | up | -0.12 | -0.22 | -0.91 |
| 11:12 | COHR | laggards | down | -1.06 | -0.15 | +0.36 |
| 11:24 | TTWO | leaders | up | -0.15 | -0.14 | +1.12 |
| 11:42 | V | leaders | up | +0.05 | +0.31 | +0.45 |
| 11:51 | ALAB | laggards | down | +2.70 | +2.53 | +2.60 |
| 12:44 | MRVL | laggards | down | +0.55 | +0.18 | +0.18 |
| 12:56 | SNAP | leaders | up | -4.53 | -6.78 | -8.39 |
| 15:52 | SCHW | leaders | up | — | — | — |

## 2026-06-17

Usable symbol-minutes 64,776/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | HOOD | +10.03 | miss | 09:53 |
| 2 | CVNA | -9.00 | miss | 09:31 |
| 3 | KMX | -7.73 | miss | 09:31 |
| 4 | NBIS | +7.21 | miss | 09:33 |
| 5 | BULL | +7.20 | miss | 10:38 |
| 6 | ARM | +6.94 | miss | 09:31 |
| 7 | SNAP | -6.89 | miss | 09:31 |
| 8 | WDC | +5.81 | miss | 09:31 |
| 9 | APP | -5.68 | miss | 09:59 |
| 10 | AVGO | +5.55 | miss | 09:34 |
| 11 | CRDO | +5.49 | miss | 09:31 |
| 12 | MRVL | +5.15 | miss | 09:31 |
| 13 | ASTS | +5.12 | miss | 09:35 |
| 14 | DELL | +5.02 | miss | 14:34 |
| 15 | IRDM | +4.93 | miss | 12:16 |
| 16 | ALAB | +4.83 | miss | 09:31 |
| 17 | INTC | +4.71 | miss | 09:31 |
| 18 | STX | +4.62 | miss | 09:32 |
| 19 | AI | -4.61 | miss | 09:59 |
| 20 | NOW | -4.52 | miss | 09:37 |

### Radar flags (9)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:06 | AI software and analytics (PLTR, NOW, DDOG, SNOW) | group_move | up | -0.66 | -1.02 | -0.67 |
| 10:09 | Cloud software and data (MDB, NOW, DDOG, SNOW, ADBE, CRM, ORCL) | group_move | up | -0.46 | -0.74 | -0.23 |
| 10:10 | Bitcoin treasuries and miners (CLSK, MARA, RIOT, IREN, MSTR, COIN) | group_move | down | +0.80 | +0.79 | +0.94 |
| 11:20 | Memory and storage (SNDK, WDC, STX, MU) | group_move | up | +0.27 | +0.14 | +0.60 |
| 12:30 | Space (IRDM, ASTS, RKLB, PL, LUNR) | group_move | up | +0.02 | +0.79 | -0.32 |
| 15:35 | Neoclouds and AI hosting (CIFR, NBIS, IREN, CRWV, WULF, APLD, ORCL) | group_move | down | — | — | — |
| 15:45 | Bitcoin treasuries and miners (IREN, CLSK, MSTR, RIOT, COIN, MARA) | group_move | down | — | — | — |
| 15:45 | Quantum computing (RGTI, QUBT, IONQ, QBTS) | group_move | down | — | — | — |
| 15:58 | Memory and storage (MU, SNDK, WDC, STX) | group_move | down | — | — | — |

### Movers flags (69)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | ALAB | leaders | up | -1.29 | -1.39 | +1.27 |
| 09:31 | MRVL | leaders | up | -1.58 | +0.08 | +0.41 |
| 09:31 | WDC | leaders | up | -1.13 | +1.97 | +2.30 |
| 09:31 | CRDO | leaders | up | +1.46 | +1.85 | +3.60 |
| 09:31 | ARM | leaders | up | -1.09 | +1.87 | +2.61 |
| 09:31 | SNDK | leaders | up | -4.37 | -4.50 | -3.67 |
| 09:31 | INTC | leaders | up | -1.75 | +0.24 | +0.52 |
| 09:31 | AMD | leaders | up | -2.36 | -0.74 | -0.05 |
| 09:31 | MU | leaders | up | -2.64 | -1.61 | -0.43 |
| 09:31 | NVO | leaders | up | -0.29 | -0.64 | -0.77 |
| 09:31 | KMX | laggards | down | -1.08 | -1.59 | -2.00 |
| 09:31 | SNAP | laggards | down | -1.02 | -0.87 | -0.58 |
| 09:31 | ADBE | laggards | down | +1.38 | +0.53 | -0.09 |
| 09:31 | IBM | laggards | down | +1.04 | +0.18 | +0.23 |
| 09:31 | MDB | laggards | down | +0.76 | +0.19 | +0.25 |
| 09:31 | ZS | laggards | down | +2.10 | +1.40 | +1.30 |
| 09:31 | HUM | laggards | down | +0.66 | +0.18 | +0.75 |
| 09:31 | CVNA | laggards | down | -6.05 | -4.49 | -6.49 |
| 09:31 | FND | laggards | down | +4.39 | +4.00 | +3.09 |
| 09:31 | META | laggards | down | -0.94 | -1.08 | -1.64 |
| 09:32 | STX | leaders | up | -0.01 | +1.36 | +2.03 |
| 09:32 | QCOM | leaders | up | +0.04 | -0.88 | -1.18 |
| 09:32 | CRWV | leaders | up | -1.37 | -0.58 | -0.99 |
| 09:32 | PINS | laggards | down | +1.09 | +1.59 | +1.12 |
| 09:32 | RCAT | laggards | down | +2.76 | +3.87 | +5.37 |
| 09:32 | CRM | laggards | down | +1.09 | +1.06 | +0.24 |
| 09:33 | NBIS | leaders | up | -0.91 | +2.68 | +1.78 |
| 09:33 | RDDT | laggards | down | -1.37 | -0.69 | -0.21 |
| 09:34 | CMI | leaders | up | +1.41 | +0.86 | +1.16 |
| 09:34 | AVGO | leaders | up | +1.74 | +2.65 | +3.08 |
| 09:35 | ASTS | leaders | up | +0.14 | +1.23 | -0.88 |
| 09:35 | HPQ | laggards | down | -0.66 | -0.49 | -1.30 |
| 09:37 | CIFR | leaders | up | -1.00 | +0.74 | +0.08 |
| 09:37 | APLD | leaders | up | -2.35 | -2.48 | -3.33 |
| 09:37 | SNOW | laggards | down | +2.19 | +2.08 | +2.68 |
| 09:37 | NOW | laggards | down | +3.27 | +3.37 | +2.73 |
| 09:39 | CLSK | leaders | up | -3.33 | -2.71 | -2.46 |
| 09:39 | OKLO | leaders | up | -0.15 | +0.11 | +1.68 |
| 09:40 | RIVN | leaders | up | -1.31 | -1.17 | +0.72 |
| 09:40 | RKLB | leaders | up | +0.84 | +0.60 | +0.04 |
| 09:44 | ELV | laggards | down | +1.25 | +1.40 | +1.78 |
| 09:45 | LCID | leaders | up | -0.77 | -0.30 | -0.13 |
| 09:45 | CNC | laggards | down | +1.68 | +2.16 | +2.63 |
| 09:49 | UAA | leaders | up | -1.43 | -1.67 | -1.03 |
| 09:49 | SPOT | laggards | down | +0.12 | +0.45 | +0.19 |
| 09:51 | GOOGL | laggards | down | +0.09 | -0.51 | -0.63 |
| 09:52 | AMZN | laggards | down | +0.05 | -0.35 | -0.73 |
| 09:53 | HOOD | leaders | up | +1.22 | +4.13 | +7.21 |
| 09:53 | AN | laggards | down | +0.14 | — | — |
| 09:54 | FND | leaders | up | -1.09 | -1.74 | -1.29 |
| 09:54 | LAD | laggards | down | +0.13 | -0.20 | -0.19 |
| 09:55 | RBLX | laggards | down | +1.36 | +2.15 | +3.78 |
| 09:58 | ANET | laggards | down | +0.36 | +0.99 | +2.82 |
| 09:59 | SOFI | leaders | up | +0.80 | +0.44 | +1.37 |
| 09:59 | APP | laggards | down | -1.04 | -0.49 | -1.71 |
| 09:59 | AI | laggards | down | -1.16 | -2.79 | -1.64 |
| 10:00 | WULF | laggards | down | +1.05 | +2.61 | +0.57 |
| 10:38 | BULL | leaders | up | +1.43 | +2.97 | +1.83 |
| 10:38 | U | laggards | down | -0.45 | +0.08 | -0.17 |
| 11:26 | FTNT | laggards | down | +0.37 | +0.61 | +1.29 |
| 11:59 | RCAT | leaders | up | +1.32 | +1.51 | +1.20 |
| 12:16 | IRDM | leaders | up | +0.60 | +0.92 | +0.60 |
| 12:25 | MSFT | laggards | down | -0.19 | -0.01 | +0.05 |
| 13:28 | CPRT | laggards | down | -0.20 | +0.17 | -0.28 |
| 13:41 | TGT | laggards | down | -0.34 | -0.79 | -0.44 |
| 14:00 | WMT | laggards | down | +0.26 | -0.04 | +1.16 |
| 14:05 | GM | laggards | down | +0.92 | +0.75 | — |
| 14:34 | DELL | leaders | up | +0.05 | -0.28 | — |
| 15:45 | SMCI | laggards | down | — | — | — |

## 2026-06-18

Usable symbol-minutes 64,862/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | KMX | +12.36 | miss | 11:51 |
| 2 | SNDK | +10.76 | miss | 09:32 |
| 3 | ALAB | +10.53 | miss | 09:32 |
| 4 | HIMS | +10.45 | 10:04 | 09:39 |
| 5 | CIFR | +9.96 | 11:10 | 10:55 |
| 6 | INTC | +9.86 | miss | 09:31 |
| 7 | SMCI | +9.59 | miss | 09:45 |
| 8 | QUBT | +9.35 | miss | 09:31 |
| 9 | CRDO | +8.24 | 10:40 | 09:38 |
| 10 | MU | +7.92 | miss | 09:31 |
| 11 | QBTS | +6.94 | miss | miss |
| 12 | RBLX | +6.53 | 10:02 | 09:44 |
| 13 | MRVL | +6.49 | miss | 09:31 |
| 14 | ASTS | -6.36 | 10:02 | 09:31 |
| 15 | TSM | +6.16 | miss | miss |
| 16 | IBM | -5.83 | miss | 09:31 |
| 17 | TDOC | +5.54 | miss | miss |
| 18 | UAA | +5.54 | miss | miss |
| 19 | QCOM | +5.39 | miss | 09:55 |
| 20 | FLNC | +5.11 | 10:29 | 09:31 |

### Radar flags (19)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | AAOI | relative_to_spy | down | +4.99 | +7.85 | +3.34 |
| 10:02 | ASTS | relative_to_spy | down | +1.14 | +2.89 | +1.59 |
| 10:02 | FLNC | relative_to_spy | down | +2.46 | +10.09 | +7.68 |
| 10:02 | RBLX | relative_to_spy | up | +0.30 | +1.49 | +1.74 |
| 10:02 | RKLB | relative_to_spy | down | +0.94 | +3.13 | +2.98 |
| 10:02 | COHR | relative_to_sector | down | +4.57 | +6.44 | +4.71 |
| 10:02 | Quantum computing (IONQ, RGTI, QUBT, QBTS) | group_move | down | +0.58 | +4.03 | +2.41 |
| 10:02 | Space (ASTS, RKLB, LUNR, IRDM, PL) | group_move | down | +0.83 | +2.68 | +2.12 |
| 10:04 | HIMS | relative_to_spy | up | -1.71 | -1.69 | +0.00 |
| 10:09 | Gaming platforms (RBLX, U, TTWO) | group_move | up | +0.09 | +0.43 | +1.21 |
| 10:25 | AI networking and connectivity (CRDO, COHR, ALAB, MRVL, AVGO) | group_move | up | +0.20 | +0.36 | +0.56 |
| 10:29 | FLNC | relative_to_sector | up | +5.05 | +6.33 | +4.57 |
| 10:29 | Quantum computing (QBTS, RGTI, IONQ, QUBT) | group_move | up | +3.51 | +2.42 | +1.34 |
| 10:40 | CRDO | relative_to_spy | up | +0.25 | -1.28 | -1.67 |
| 10:49 | FLNC | relative_to_spy | up | +3.29 | +1.39 | +1.49 |
| 11:10 | CIFR | relative_to_spy | up | +1.30 | +2.45 | +2.16 |
| 11:45 | Crypto and exchanges (CRCL, HOOD, MSTR, COIN, BULL, RIOT, MARA) | group_move | down | +0.60 | +0.19 | -0.32 |
| 15:54 | Space (LUNR, PL, ASTS, IRDM, RKLB) | group_move | up | — | — | — |
| 15:58 | MRVL | relative_to_spy | down | — | — | — |

### Movers flags (56)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | WDC | leaders | up | +2.08 | +0.52 | +0.35 |
| 09:31 | INTC | leaders | up | -0.85 | -1.94 | +0.93 |
| 09:31 | STX | leaders | up | -1.68 | -3.23 | -4.13 |
| 09:31 | ARM | leaders | up | -0.67 | -0.53 | -0.00 |
| 09:31 | QUBT | leaders | up | -2.70 | -3.08 | +0.22 |
| 09:31 | NBIS | leaders | up | -3.88 | -4.68 | -2.77 |
| 09:31 | MRVL | leaders | up | +2.01 | +3.23 | +6.33 |
| 09:31 | IREN | leaders | up | -3.92 | -2.35 | -2.02 |
| 09:31 | MU | leaders | up | +0.85 | +1.47 | +2.77 |
| 09:31 | FLNC | leaders | up | -8.52 | -6.06 | +0.56 |
| 09:31 | IBM | laggards | down | -1.20 | -1.11 | -0.54 |
| 09:31 | SHEL | laggards | down | +0.23 | +0.46 | +0.43 |
| 09:31 | XOM | laggards | down | -0.11 | -0.31 | +0.01 |
| 09:31 | SNOW | laggards | down | -1.66 | -1.00 | -0.13 |
| 09:31 | OXY | laggards | down | -0.56 | -1.05 | -1.15 |
| 09:31 | CRM | laggards | down | -0.43 | +0.07 | -0.21 |
| 09:31 | COP | laggards | down | -0.36 | -0.85 | -1.11 |
| 09:31 | ASTS | laggards | down | -7.11 | -6.30 | -4.68 |
| 09:31 | NET | laggards | down | -1.37 | -0.88 | -0.30 |
| 09:31 | PL | laggards | down | -4.19 | -3.25 | -1.85 |
| 09:32 | ALAB | leaders | up | +0.49 | +3.00 | +5.12 |
| 09:32 | SNDK | leaders | up | +3.72 | +4.76 | +5.87 |
| 09:32 | MDB | laggards | down | -1.99 | -1.11 | -0.61 |
| 09:32 | DDOG | laggards | down | -0.88 | -0.96 | +0.37 |
| 09:32 | U | laggards | down | +1.66 | +2.92 | +3.06 |
| 09:32 | APP | laggards | down | -1.42 | -0.94 | -0.08 |
| 09:34 | AVGO | leaders | up | -1.16 | -1.10 | -0.67 |
| 09:34 | LUNR | laggards | down | -1.79 | -2.20 | +1.20 |
| 09:34 | ZS | laggards | down | +0.46 | +1.49 | +1.54 |
| 09:35 | ORCL | laggards | down | +1.80 | +2.36 | +3.21 |
| 09:38 | CRDO | leaders | up | -2.26 | +2.73 | +0.70 |
| 09:38 | CVNA | leaders | up | +1.30 | +2.75 | +2.25 |
| 09:38 | CRWD | laggards | down | +1.53 | +2.39 | +1.63 |
| 09:39 | HIMS | leaders | up | +3.24 | +2.03 | +2.02 |
| 09:39 | RKLB | laggards | down | -1.79 | -1.08 | +0.06 |
| 09:40 | AMD | leaders | up | -0.56 | -0.67 | -0.91 |
| 09:42 | RCAT | laggards | down | +0.19 | -0.15 | +2.02 |
| 09:44 | RBLX | leaders | up | +3.79 | +2.70 | +3.46 |
| 09:45 | SMCI | leaders | up | +3.32 | +3.73 | +3.80 |
| 09:51 | FLNC | laggards | down | +2.01 | +6.11 | +8.22 |
| 09:55 | QCOM | leaders | up | -1.02 | -0.16 | -1.95 |
| 09:56 | FND | leaders | up | -0.15 | +0.13 | +1.02 |
| 09:59 | PLTR | laggards | down | +1.23 | +1.44 | +1.48 |
| 10:01 | AAOI | laggards | down | +3.45 | +6.45 | +2.34 |
| 10:12 | MSTR | laggards | down | +1.10 | +0.72 | -0.26 |
| 10:19 | PFE | laggards | down | -0.48 | -0.57 | -0.03 |
| 10:48 | MRK | laggards | down | -0.35 | +0.67 | +0.97 |
| 10:55 | CIFR | leaders | up | +1.42 | +3.97 | +6.05 |
| 11:51 | KMX | leaders | up | +1.68 | +1.93 | +2.43 |
| 11:55 | HSAI | laggards | down | -0.23 | -0.02 | -0.10 |
| 12:34 | CRCL | laggards | down | -1.01 | -0.51 | -1.11 |
| 13:47 | SCHW | laggards | down | -0.50 | -0.25 | -0.40 |
| 15:22 | AI | laggards | down | +2.11 | — | — |
| 15:37 | CVX | laggards | down | — | — | — |
| 15:47 | JPM | laggards | down | — | — | — |
| 15:57 | DELL | laggards | down | — | — | — |

## 2026-06-22

Usable symbol-minutes 64,844/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | SMCI | +15.97 | 10:02 | 09:31 |
| 2 | CRDO | +11.60 | miss | 09:31 |
| 3 | COHR | +9.53 | 10:02 | 09:53 |
| 4 | ASTS | -8.95 | miss | 09:32 |
| 5 | RIVN | -8.28 | miss | 09:31 |
| 6 | RBLX | -7.95 | miss | 09:31 |
| 7 | CIEN | +7.81 | miss | 09:32 |
| 8 | MU | +7.14 | miss | 09:31 |
| 9 | ARM | -6.91 | miss | 09:39 |
| 10 | RCAT | -6.77 | 10:30 | 09:31 |
| 11 | PLTR | -6.67 | miss | 12:25 |
| 12 | ONON | -6.55 | miss | 09:34 |
| 13 | NVO | +6.54 | miss | 09:34 |
| 14 | RKLB | -6.17 | 10:25 | 09:36 |
| 15 | AAOI | +6.11 | 13:21 | 13:39 |
| 16 | TDOC | -5.76 | miss | 15:12 |
| 17 | ALAB | +5.73 | miss | 09:41 |
| 18 | AI | -5.51 | miss | 15:58 |
| 19 | INTC | +5.50 | miss | 09:31 |
| 20 | NFLX | -5.50 | miss | 12:16 |

### Radar flags (32)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | CLSK | relative_to_spy | up | -2.45 | -4.26 | -6.55 |
| 10:02 | COHR | relative_to_spy | up | -2.56 | -3.21 | -3.63 |
| 10:02 | IONQ | relative_to_spy | up | -3.64 | -2.57 | -1.76 |
| 10:02 | MARA | relative_to_spy | up | +0.47 | -2.24 | -4.18 |
| 10:02 | QUBT | relative_to_spy | up | -4.61 | -4.68 | -3.67 |
| 10:02 | RDDT | relative_to_spy | up | -2.83 | -4.11 | -3.05 |
| 10:02 | RGTI | relative_to_spy | up | -2.89 | -2.04 | -1.57 |
| 10:02 | SMCI | relative_to_spy | up | -2.90 | -1.28 | -0.10 |
| 10:02 | HIMS | relative_to_sector | up | -1.68 | -3.62 | -3.80 |
| 10:02 | Bitcoin treasuries and miners (MARA, CLSK, COIN, RIOT, IREN, MSTR) | group_move | up | -2.15 | -3.33 | -4.69 |
| 10:02 | Crypto and exchanges (MARA, COIN, BULL, CRCL, RIOT, MSTR, HOOD) | group_move | up | -2.40 | -3.06 | -3.86 |
| 10:02 | Quantum computing (RGTI, IONQ, QUBT, QBTS) | group_move | up | -3.74 | -3.16 | -2.01 |
| 10:02 | Retail brokers and fintech (COIN, BULL, SOFI, HOOD, PYPL) | group_move | up | -2.60 | -2.88 | -2.97 |
| 10:02 | Rideshare and delivery (DASH, LYFT, TSLA, UBER) | group_move | up | -0.73 | -0.44 | +0.06 |
| 10:03 | AI software and analytics (APP, DDOG, NOW, AI, PLTR, SNOW) | group_move | up | -1.37 | -2.05 | -2.51 |
| 10:04 | QCOM | relative_to_spy | up | -0.15 | +0.60 | -0.43 |
| 10:05 | Social and ads (RDDT, APP, SNAP, PINS, META) | group_move | up | -0.69 | -1.89 | -1.77 |
| 10:06 | APP | relative_to_spy | up | -0.68 | -2.33 | -2.63 |
| 10:15 | Space (RKLB, LUNR, ASTS, PL, IRDM) | group_move | down | -0.07 | +0.39 | +1.79 |
| 10:18 | Quantum computing (QBTS, QUBT, RGTI, IONQ) | group_move | down | +0.15 | -1.36 | +1.97 |
| 10:25 | RKLB | relative_to_spy | down | +1.32 | +2.57 | +1.95 |
| 10:25 | Retail brokers and fintech (HOOD, SOFI, COIN, BULL, PYPL) | group_move | down | -0.75 | -0.34 | -0.94 |
| 10:27 | Crypto and exchanges (HOOD, RIOT, COIN, BULL, CRCL, MSTR) | group_move | down | -0.97 | -0.80 | -2.27 |
| 10:27 | Neoclouds and AI hosting (CRWV, APLD, IREN, NBIS, WULF, CIFR, ORCL) | group_move | down | -0.88 | -1.17 | -2.69 |
| 10:30 | RCAT | relative_to_sector | down | +0.76 | +2.38 | +1.71 |
| 10:30 | Bitcoin treasuries and miners (RIOT, COIN, CLSK, IREN, MSTR, MARA) | group_move | down | -1.24 | -1.42 | -3.66 |
| 10:32 | LUNR | relative_to_sector | down | +1.59 | +3.55 | +3.04 |
| 10:34 | IRDM | relative_to_sector | down | +1.87 | +3.38 | +3.08 |
| 11:43 | Quantum computing (QBTS, IONQ, RGTI, QUBT) | group_move | up | +0.30 | +0.92 | +1.73 |
| 11:50 | Space (LUNR, PL, RKLB, ASTS, IRDM) | group_move | up | -0.63 | +0.02 | +0.01 |
| 13:21 | AAOI | relative_to_spy | up | +1.53 | +3.98 | +1.19 |
| 14:56 | Quantum computing (QBTS, RGTI, QUBT, IONQ) | group_move | down | -1.75 | -1.75 | — |

### Movers flags (55)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | CRDO | leaders | up | +1.49 | +1.40 | +4.01 |
| 09:31 | SMCI | leaders | up | +7.44 | +4.21 | +8.09 |
| 09:31 | FLNC | leaders | up | +0.04 | -3.92 | -3.41 |
| 09:31 | MU | leaders | up | -1.12 | +0.05 | -0.49 |
| 09:31 | SNDK | leaders | up | -1.09 | +1.05 | +1.32 |
| 09:31 | DELL | leaders | up | +1.38 | +0.30 | +0.30 |
| 09:31 | INTC | leaders | up | -2.01 | -0.86 | -0.52 |
| 09:31 | NBIS | leaders | up | -1.43 | -3.56 | -5.60 |
| 09:31 | RIOT | leaders | up | +3.02 | -0.12 | -0.77 |
| 09:31 | CLSK | leaders | up | +5.32 | +3.00 | +0.80 |
| 09:31 | RBLX | laggards | down | -0.33 | -1.74 | -3.92 |
| 09:31 | HIMS | laggards | down | +5.47 | +3.84 | +1.42 |
| 09:31 | OKLO | laggards | down | +2.28 | -0.84 | +0.42 |
| 09:31 | RGTI | laggards | down | +7.10 | +3.70 | +5.24 |
| 09:31 | LUNR | laggards | down | -1.32 | -5.39 | -1.90 |
| 09:31 | MDB | laggards | down | -0.86 | -2.96 | -1.67 |
| 09:31 | HSAI | laggards | down | +1.55 | +0.55 | +2.05 |
| 09:31 | PL | laggards | down | +3.30 | -0.71 | +1.81 |
| 09:31 | RCAT | laggards | down | +0.04 | -4.51 | -2.34 |
| 09:31 | RIVN | laggards | down | -0.36 | -2.30 | -1.72 |
| 09:32 | TTWO | leaders | up | -0.03 | -1.52 | -2.34 |
| 09:32 | MARA | leaders | up | +10.34 | +10.80 | +6.57 |
| 09:32 | CIEN | leaders | up | -0.58 | -0.68 | -0.39 |
| 09:32 | ASTS | laggards | down | -0.26 | -3.55 | -1.39 |
| 09:32 | RDDT | laggards | down | +8.38 | +5.27 | +4.76 |
| 09:32 | QCOM | laggards | down | +4.51 | +5.35 | +5.44 |
| 09:33 | WDC | leaders | up | -2.04 | -2.02 | -2.04 |
| 09:33 | GOOGL | laggards | down | -0.94 | -1.69 | -2.46 |
| 09:34 | MSTR | leaders | up | +1.27 | +0.05 | -1.79 |
| 09:34 | NVO | leaders | up | +1.62 | +2.36 | +3.80 |
| 09:34 | APP | laggards | down | +5.45 | +4.54 | +3.28 |
| 09:34 | U | laggards | down | +3.06 | +1.60 | +1.36 |
| 09:34 | ONON | laggards | down | -1.10 | -1.26 | -2.96 |
| 09:36 | RKLB | laggards | down | -2.47 | -4.91 | -3.07 |
| 09:37 | COIN | leaders | up | +1.75 | -0.39 | -1.84 |
| 09:39 | ARM | laggards | down | +0.05 | +0.19 | -1.78 |
| 09:40 | CRWV | laggards | down | +1.09 | -1.30 | -3.48 |
| 09:41 | ALAB | leaders | up | -2.15 | -1.67 | -3.11 |
| 09:43 | AAOI | laggards | down | +2.39 | +1.87 | +3.07 |
| 09:45 | CRCL | leaders | up | -2.12 | -2.66 | -3.20 |
| 09:47 | GM | leaders | up | -0.80 | -0.79 | -0.56 |
| 09:51 | SONY | laggards | down | -0.17 | +0.46 | +0.32 |
| 09:53 | COHR | leaders | up | -0.88 | -0.63 | -1.46 |
| 09:55 | IONQ | leaders | up | -2.92 | -3.06 | +0.57 |
| 10:16 | STX | leaders | up | -1.12 | -1.34 | -3.07 |
| 10:17 | IRDM | laggards | down | -0.69 | +1.44 | +2.22 |
| 10:55 | CVS | leaders | up | +0.06 | +0.25 | +0.63 |
| 11:25 | CNC | leaders | up | +0.11 | +0.27 | +0.50 |
| 12:16 | NFLX | laggards | down | -0.33 | -0.26 | +0.75 |
| 12:25 | PLTR | laggards | down | +0.35 | +0.42 | +0.37 |
| 12:56 | LULU | laggards | down | -0.28 | +0.11 | -0.11 |
| 13:39 | AAOI | leaders | up | +2.46 | +3.83 | +0.94 |
| 15:12 | TDOC | laggards | down | -0.00 | — | — |
| 15:53 | IREN | laggards | down | — | — | — |
| 15:58 | AI | laggards | down | — | — | — |

## 2026-06-23

Usable symbol-minutes 64,807/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | FLNC | -14.35 | miss | 09:31 |
| 2 | AAOI | -12.44 | miss | 09:34 |
| 3 | SNDK | -12.19 | miss | 09:31 |
| 4 | MU | -11.72 | miss | 09:31 |
| 5 | COHR | -8.95 | miss | 09:31 |
| 6 | ARM | -8.68 | miss | 09:31 |
| 7 | CRDO | -8.63 | miss | 09:32 |
| 8 | ALAB | -8.25 | miss | 09:31 |
| 9 | MRVL | -7.91 | miss | 09:31 |
| 10 | WDC | -6.99 | miss | 09:31 |
| 11 | QCOM | -6.56 | miss | 09:37 |
| 12 | IBM | +6.50 | miss | 09:31 |
| 13 | ANET | -5.63 | miss | 09:33 |
| 14 | TSM | -5.24 | miss | miss |
| 15 | MRK | +5.02 | miss | 09:31 |
| 16 | TGT | +4.83 | miss | 09:32 |
| 17 | NVO | +4.81 | miss | 09:31 |
| 18 | LULU | +4.76 | miss | 13:38 |
| 19 | INTC | -4.69 | miss | 09:31 |
| 20 | NOW | +4.60 | miss | 09:31 |

### Radar flags (24)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | APLD | relative_to_spy | up | -0.32 | -0.30 | +0.55 |
| 10:02 | ASTS | relative_to_spy | up | -1.18 | -1.30 | +0.75 |
| 10:02 | CIFR | relative_to_spy | up | +0.69 | -0.21 | -0.32 |
| 10:02 | CLSK | relative_to_spy | up | +0.47 | -1.31 | -1.58 |
| 10:02 | CRWV | relative_to_spy | up | +1.59 | -0.55 | -1.93 |
| 10:02 | IREN | relative_to_spy | up | -0.04 | -1.27 | -2.39 |
| 10:02 | MARA | relative_to_spy | up | +0.27 | -1.14 | -0.71 |
| 10:02 | NBIS | relative_to_spy | up | -1.19 | -3.52 | -3.94 |
| 10:02 | OKLO | relative_to_spy | up | -0.21 | +0.11 | -0.76 |
| 10:02 | RIOT | relative_to_spy | up | -0.11 | -1.47 | -1.36 |
| 10:02 | WULF | relative_to_spy | up | +0.10 | -0.94 | -1.05 |
| 10:02 | Bitcoin treasuries and miners (CLSK, RIOT, IREN, MARA, COIN) | group_move | up | +0.07 | -1.21 | -1.39 |
| 10:02 | Neoclouds and AI hosting (NBIS, CIFR, APLD, WULF, CRWV, IREN, ORCL) | group_move | up | -0.03 | -1.17 | -1.60 |
| 10:02 | Quantum computing (QBTS, IONQ, RGTI, QUBT) | group_move | up | -2.42 | -2.94 | -3.17 |
| 10:03 | CIEN | relative_to_spy | up | -1.83 | -1.28 | -1.98 |
| 10:05 | Space (ASTS, PL, RKLB, LUNR, IRDM) | group_move | up | -2.11 | -2.05 | -0.68 |
| 10:14 | Quantum computing (IONQ, QBTS, QUBT, RGTI) | group_move | down | -0.39 | -1.57 | -0.86 |
| 10:21 | Memory and storage (MU, SNDK, WDC, STX) | group_move | up | -2.51 | -2.48 | -1.44 |
| 10:49 | Bitcoin treasuries and miners (MARA, CLSK, RIOT, IREN, COIN, MSTR) | group_move | down | -0.70 | -0.11 | +0.19 |
| 10:49 | Memory and storage (MU, SNDK, WDC, STX) | group_move | down | +0.38 | +0.84 | +1.00 |
| 10:50 | NBIS | relative_to_spy | down | -1.37 | -1.69 | +0.19 |
| 11:09 | Neoclouds and AI hosting (CRWV, NBIS, CIFR, IREN, WULF, APLD, ORCL) | group_move | down | -0.16 | +1.11 | +0.09 |
| 14:09 | Quantum computing (QBTS, RGTI, QUBT, IONQ) | group_move | down | -0.29 | -0.67 | — |
| 15:41 | Quantum computing (RGTI, QUBT, IONQ, QBTS) | group_move | up | — | — | — |

### Movers flags (54)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | NOW | leaders | up | -0.96 | -0.11 | +0.55 |
| 09:31 | IBM | leaders | up | +1.39 | +0.94 | +1.78 |
| 09:31 | NVO | leaders | up | -0.86 | -0.60 | -1.10 |
| 09:31 | ADBE | leaders | up | -1.99 | -2.09 | -1.33 |
| 09:31 | LLY | leaders | up | -2.08 | -1.93 | -2.27 |
| 09:31 | MRK | leaders | up | +0.43 | +0.00 | +0.06 |
| 09:31 | CRM | leaders | up | -1.53 | -1.02 | -0.01 |
| 09:31 | WMT | leaders | up | -0.48 | -0.51 | +0.48 |
| 09:31 | TTWO | leaders | up | +0.27 | -1.13 | +0.49 |
| 09:31 | CPRT | leaders | up | -1.34 | -1.77 | -1.19 |
| 09:31 | MU | laggards | down | +2.11 | +2.55 | +0.47 |
| 09:31 | SNDK | laggards | down | -0.57 | -0.28 | -1.28 |
| 09:31 | FLNC | laggards | down | -1.69 | -1.93 | -3.34 |
| 09:31 | STX | laggards | down | +1.22 | +2.08 | +2.42 |
| 09:31 | WDC | laggards | down | -0.81 | -0.15 | -0.31 |
| 09:31 | MRVL | laggards | down | +2.03 | +0.73 | +0.09 |
| 09:31 | ALAB | laggards | down | +3.45 | +1.11 | -0.40 |
| 09:31 | INTC | laggards | down | +5.68 | +5.22 | +5.22 |
| 09:31 | COHR | laggards | down | +0.70 | +0.75 | -0.93 |
| 09:31 | ARM | laggards | down | +2.65 | +0.22 | -0.82 |
| 09:32 | QUBT | leaders | up | +0.54 | -2.05 | -2.57 |
| 09:32 | QBTS | leaders | up | +4.44 | +2.46 | +1.30 |
| 09:32 | RGTI | leaders | up | +2.47 | -0.00 | -1.52 |
| 09:32 | TGT | leaders | up | +0.51 | +1.11 | +1.67 |
| 09:32 | CRWV | laggards | down | +5.80 | +7.50 | +3.57 |
| 09:32 | CRDO | laggards | down | -1.48 | -3.68 | -4.39 |
| 09:33 | DASH | leaders | up | -2.48 | -1.49 | -1.57 |
| 09:33 | PINS | leaders | up | +1.92 | -0.48 | +0.17 |
| 09:33 | ANET | laggards | down | +0.92 | -0.20 | -0.38 |
| 09:34 | ZS | leaders | up | -1.67 | -1.32 | +0.09 |
| 09:34 | AAOI | laggards | down | -0.27 | -1.77 | -3.85 |
| 09:35 | IONQ | leaders | up | +0.52 | -1.09 | -1.64 |
| 09:36 | AI | leaders | up | -2.50 | -2.88 | -2.56 |
| 09:37 | QCOM | laggards | down | +1.10 | +0.53 | -1.35 |
| 09:39 | MSFT | leaders | up | -0.56 | -0.04 | -0.49 |
| 09:43 | RBLX | leaders | up | +0.05 | -1.21 | -0.31 |
| 09:43 | HIMS | leaders | up | -1.23 | -1.99 | -1.57 |
| 09:51 | ASTS | leaders | up | +1.28 | +1.10 | +0.58 |
| 09:56 | TDOC | leaders | up | -0.88 | -0.68 | -1.55 |
| 10:01 | CLSK | leaders | up | +1.38 | -1.77 | -1.37 |
| 10:10 | WULF | leaders | up | +0.00 | -1.53 | +0.09 |
| 10:13 | NBIS | leaders | up | -2.77 | -5.70 | -3.43 |
| 10:13 | OKLO | leaders | up | +0.19 | -0.52 | -0.08 |
| 10:16 | MARA | leaders | up | -3.45 | -4.66 | -2.48 |
| 10:21 | SOFI | leaders | up | -0.43 | -0.55 | -0.27 |
| 10:42 | NET | leaders | up | +0.85 | +1.89 | +2.32 |
| 11:01 | LCID | leaders | up | -0.84 | -1.22 | -1.71 |
| 11:07 | FND | leaders | up | -0.31 | +0.05 | -0.08 |
| 12:11 | APLD | leaders | up | -1.07 | -2.28 | -2.30 |
| 12:12 | DELL | leaders | up | +0.01 | -0.14 | -0.49 |
| 12:32 | S | leaders | up | +0.26 | +0.60 | +0.38 |
| 12:36 | IRDM | leaders | up | +0.01 | -0.75 | -0.58 |
| 12:42 | SNOW | leaders | up | -0.31 | -0.01 | -0.27 |
| 13:38 | LULU | leaders | up | +0.56 | +0.88 | +0.60 |

## 2026-06-24

Usable symbol-minutes 64,938/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | FND | +10.70 | miss | 09:31 |
| 2 | RKLB | -10.16 | miss | 09:32 |
| 3 | MSTR | -9.30 | miss | 09:53 |
| 4 | LUNR | -8.64 | miss | 09:31 |
| 5 | RCAT | -8.21 | miss | 12:06 |
| 6 | RGTI | -8.18 | miss | 09:31 |
| 7 | QBTS | -8.14 | miss | 09:31 |
| 8 | IREN | -8.03 | miss | 09:44 |
| 9 | PL | -7.77 | miss | 09:33 |
| 10 | QUBT | -7.48 | miss | 09:31 |
| 11 | IONQ | -7.30 | miss | 09:31 |
| 12 | APLD | -7.22 | miss | 09:41 |
| 13 | FLNC | -6.84 | miss | 10:20 |
| 14 | ASTS | -6.62 | miss | 09:31 |
| 15 | WULF | -6.24 | miss | 14:20 |
| 16 | CRCL | -6.16 | miss | miss |
| 17 | UBER | +6.05 | miss | 10:34 |
| 18 | HOOD | -5.82 | miss | 09:52 |
| 19 | MDB | -5.73 | miss | miss |
| 20 | HD | +5.72 | miss | 09:31 |

### Radar flags (10)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | Bitcoin treasuries and miners (CLSK, IREN, MSTR, MARA, COIN, RIOT) | group_move | down | +0.01 | +0.17 | -1.07 |
| 10:02 | Crypto and exchanges (HOOD, MSTR, MARA, COIN, CRCL, BULL, RIOT) | group_move | down | +0.31 | +0.25 | -0.69 |
| 10:02 | Neoclouds and AI hosting (IREN, CIFR, APLD, NBIS, CRWV, WULF, ORCL) | group_move | down | -0.08 | -0.22 | -0.86 |
| 10:03 | CLSK | relative_to_spy | down | -1.21 | -0.98 | -1.29 |
| 10:05 | AI networking and connectivity (ALAB, CRDO, MRVL, COHR, AVGO, ANET) | group_move | down | +1.02 | +1.42 | +0.92 |
| 10:06 | AAOI | relative_to_spy | down | +1.92 | +2.46 | +2.20 |
| 10:22 | Quantum computing (QBTS, RGTI, IONQ, QUBT) | group_move | down | +0.12 | +0.92 | +1.13 |
| 10:50 | Rideshare and delivery (UBER, DASH, LYFT, TSLA) | group_move | up | +1.66 | +0.78 | +1.12 |
| 15:39 | Memory and storage (MU, WDC, SNDK, STX) | group_move | up | — | — | — |
| 15:56 | Neoclouds and AI hosting (NBIS, WULF, CIFR, APLD, IREN, CRWV, ORCL) | group_move | up | — | — | — |

### Movers flags (59)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | FND | leaders | up | +3.82 | +4.86 | +5.66 |
| 09:31 | CLSK | leaders | up | -4.52 | -6.36 | -6.74 |
| 09:31 | SONY | leaders | up | -0.26 | -0.51 | -0.42 |
| 09:31 | MARA | leaders | up | -3.60 | -5.36 | -6.04 |
| 09:31 | LLY | leaders | up | -0.73 | -2.12 | -2.58 |
| 09:31 | CRDO | leaders | up | -3.21 | -2.02 | -1.99 |
| 09:31 | HD | leaders | up | +1.22 | +1.94 | +2.81 |
| 09:31 | ALAB | leaders | up | -0.72 | +0.47 | -0.47 |
| 09:31 | PINS | leaders | up | -0.88 | -0.12 | +1.80 |
| 09:31 | LULU | leaders | up | +1.02 | -0.08 | +0.83 |
| 09:31 | QBTS | laggards | down | -2.03 | -3.19 | -3.57 |
| 09:31 | ASTS | laggards | down | -2.18 | -1.58 | -1.02 |
| 09:31 | QUBT | laggards | down | -0.51 | -2.04 | -1.08 |
| 09:31 | RGTI | laggards | down | -2.37 | -3.06 | -3.34 |
| 09:31 | OKLO | laggards | down | -1.20 | -1.61 | -1.59 |
| 09:31 | WDC | laggards | down | -0.05 | -0.78 | -0.49 |
| 09:31 | OXY | laggards | down | +0.67 | +0.23 | -0.18 |
| 09:31 | LUNR | laggards | down | -3.41 | -3.49 | -2.80 |
| 09:31 | STX | laggards | down | +0.65 | -0.34 | +0.03 |
| 09:31 | IONQ | laggards | down | -2.52 | -3.80 | -4.42 |
| 09:32 | TDOC | leaders | up | -2.46 | -2.01 | -1.22 |
| 09:32 | BULL | leaders | up | -1.64 | -1.54 | -1.53 |
| 09:32 | ONON | leaders | up | -0.16 | +0.90 | +1.86 |
| 09:32 | RKLB | laggards | down | -2.86 | -2.53 | -3.32 |
| 09:33 | PL | laggards | down | -2.13 | -1.43 | -3.08 |
| 09:33 | COP | laggards | down | +1.12 | +0.13 | -0.61 |
| 09:34 | SOFI | leaders | up | +0.28 | +1.56 | +1.81 |
| 09:34 | AVGO | leaders | up | -1.29 | -1.39 | -1.04 |
| 09:34 | CVNA | leaders | up | +0.50 | +0.38 | +0.39 |
| 09:35 | LYFT | leaders | up | -0.95 | +2.32 | +3.18 |
| 09:35 | NBIS | laggards | down | -2.02 | -2.72 | -3.24 |
| 09:36 | SNDK | leaders | up | -2.83 | -2.92 | -4.58 |
| 09:37 | CIFR | laggards | down | -1.99 | -1.87 | -2.87 |
| 09:39 | CPRT | leaders | up | +0.14 | -0.42 | +0.20 |
| 09:40 | LOW | leaders | up | +0.34 | +0.16 | +1.02 |
| 09:41 | APLD | laggards | down | -0.08 | -0.92 | -1.49 |
| 09:42 | KMX | leaders | up | +0.12 | -0.03 | -2.16 |
| 09:43 | TGT | leaders | up | +0.36 | +0.57 | +0.90 |
| 09:44 | IREN | laggards | down | +0.20 | +1.07 | +0.27 |
| 09:45 | ADBE | leaders | up | -2.07 | -2.03 | -1.80 |
| 09:49 | UAA | leaders | up | -0.25 | -0.12 | +1.73 |
| 09:52 | HOOD | laggards | down | -0.49 | +0.99 | +1.00 |
| 09:53 | LCID | leaders | up | -1.57 | -3.29 | -3.68 |
| 09:53 | MSTR | laggards | down | -1.78 | -1.32 | -3.47 |
| 09:56 | QCOM | laggards | down | +0.11 | +0.55 | +0.33 |
| 10:14 | DE | leaders | up | +0.08 | +0.17 | +0.42 |
| 10:16 | PYPL | leaders | up | -0.01 | +1.00 | -0.05 |
| 10:18 | LAD | leaders | up | -0.55 | -0.88 | -0.56 |
| 10:20 | FLNC | laggards | down | +2.87 | +2.55 | +2.27 |
| 10:24 | DECK | leaders | up | -0.78 | +0.08 | -0.09 |
| 10:25 | ZS | leaders | up | -0.44 | -0.14 | -1.15 |
| 10:29 | DASH | leaders | up | +2.28 | +2.95 | +2.65 |
| 10:30 | DELL | leaders | up | -0.73 | -1.86 | -1.25 |
| 10:34 | UBER | leaders | up | +3.25 | +4.72 | +4.21 |
| 10:38 | CIEN | leaders | up | -0.28 | -0.24 | -0.26 |
| 10:45 | RBLX | leaders | up | +1.69 | -0.02 | +1.34 |
| 10:57 | COHR | leaders | up | -1.43 | -0.38 | -1.32 |
| 12:06 | RCAT | laggards | down | -0.02 | -0.81 | -1.50 |
| 14:20 | WULF | laggards | down | -1.75 | -1.25 | — |

## 2026-06-25

Usable symbol-minutes 64,936/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | SNDK | +21.82 | miss | 09:31 |
| 2 | MU | +15.60 | miss | 09:31 |
| 3 | MSTR | -9.49 | 10:02 | 09:40 |
| 4 | QUBT | -6.43 | 10:02 | 14:46 |
| 5 | AAPL | -6.26 | miss | 09:31 |
| 6 | AI | -6.26 | miss | 09:31 |
| 7 | CAT | +6.15 | miss | 09:42 |
| 8 | AAOI | -5.88 | 10:02 | 09:49 |
| 9 | RGTI | -5.88 | 10:02 | 14:48 |
| 10 | IONQ | -5.82 | 10:02 | 11:49 |
| 11 | DELL | -5.81 | miss | 09:31 |
| 12 | OKLO | -5.79 | 10:02 | 12:46 |
| 13 | RKLB | -5.67 | miss | 09:31 |
| 14 | PLTR | -5.63 | miss | 09:31 |
| 15 | IREN | -5.23 | 10:02 | 14:28 |
| 16 | COIN | -5.20 | miss | 14:44 |
| 17 | URI | +5.00 | miss | 09:51 |
| 18 | BABA | -4.88 | miss | 09:31 |
| 19 | DE | +4.85 | miss | 09:59 |
| 20 | QBTS | -4.80 | 10:08 | 14:51 |

### Radar flags (46)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | AAOI | relative_to_spy | down | +0.21 | +0.96 | -1.80 |
| 10:02 | ALAB | relative_to_spy | down | +2.37 | +2.98 | +3.42 |
| 10:02 | AMD | relative_to_spy | down | +0.68 | +1.28 | +1.71 |
| 10:02 | APLD | relative_to_spy | down | +0.77 | +0.18 | -0.92 |
| 10:02 | ARM | relative_to_spy | down | +0.54 | +1.57 | +2.59 |
| 10:02 | CIEN | relative_to_spy | down | +3.59 | +4.51 | +3.64 |
| 10:02 | CIFR | relative_to_spy | down | +0.58 | +0.13 | -0.20 |
| 10:02 | CLSK | relative_to_spy | down | -0.00 | -1.01 | +1.45 |
| 10:02 | COHR | relative_to_spy | down | +1.45 | +4.14 | +3.17 |
| 10:02 | CRDO | relative_to_spy | down | +2.51 | +3.21 | +1.31 |
| 10:02 | HIMS | relative_to_spy | down | +2.17 | +1.07 | +0.63 |
| 10:02 | INTC | relative_to_spy | down | +1.71 | +2.06 | +1.72 |
| 10:02 | IONQ | relative_to_spy | down | +1.79 | +0.75 | -0.76 |
| 10:02 | IREN | relative_to_spy | down | +1.42 | +1.08 | +0.97 |
| 10:02 | MARA | relative_to_spy | down | +1.35 | +2.06 | +3.09 |
| 10:02 | MRVL | relative_to_spy | down | +0.74 | +2.42 | +3.08 |
| 10:02 | MU | relative_to_spy | down | -0.14 | +1.99 | +4.16 |
| 10:02 | OKLO | relative_to_spy | down | +0.77 | +0.07 | -1.23 |
| 10:02 | QCOM | relative_to_spy | down | +0.35 | +0.16 | +2.29 |
| 10:02 | QUBT | relative_to_spy | down | +1.01 | +0.24 | -0.58 |
| 10:02 | RGTI | relative_to_spy | down | +1.92 | +0.83 | -0.60 |
| 10:02 | RIOT | relative_to_spy | down | +0.04 | +1.61 | +3.34 |
| 10:02 | STX | relative_to_spy | down | -1.34 | +0.16 | -0.01 |
| 10:02 | WULF | relative_to_spy | down | +1.16 | +1.34 | +0.47 |
| 10:02 | BULL | relative_to_sector | down | +0.31 | +0.26 | +0.92 |
| 10:02 | FLNC | relative_to_sector | down | +1.80 | +1.03 | +0.91 |
| 10:02 | MSTR | relative_to_sector | down | +1.07 | -0.30 | -0.98 |
| 10:02 | RCAT | relative_to_sector | down | +1.86 | +0.78 | -0.59 |
| 10:02 | AI networking and connectivity (ALAB, CRDO, COHR, MRVL, AVGO) | group_move | down | +1.50 | +2.86 | +2.57 |
| 10:02 | Bitcoin treasuries and miners (MARA, CLSK, IREN, RIOT, MSTR, COIN) | group_move | down | +0.85 | +0.62 | +1.26 |
| 10:02 | Crypto and exchanges (MARA, RIOT, BULL, MSTR, HOOD, COIN, CRCL) | group_move | down | +1.01 | +0.84 | +1.10 |
| 10:02 | GPUs and AI compute chips (INTC, MRVL, ARM, QCOM, AMD, TSM, NVDA, AVGO) | group_move | down | +0.60 | +1.28 | +1.84 |
| 10:02 | Heavy machinery (URI, PCAR, DE, CMI, CAT) | group_move | up | +0.55 | — | -0.10 |
| 10:02 | Memory and storage (STX, MU, SNDK, WDC) | group_move | down | -0.76 | +1.51 | +2.43 |
| 10:02 | Neoclouds and AI hosting (CIFR, WULF, IREN, APLD, CRWV, NBIS, ORCL) | group_move | down | +0.92 | +0.28 | -0.10 |
| 10:02 | Oil majors (XOM, COP, OXY, CVX, SHEL) | group_move | up | -0.51 | -0.88 | -0.44 |
| 10:02 | Quantum computing (QUBT, RGTI, IONQ, QBTS) | group_move | down | +1.41 | +0.56 | -0.70 |
| 10:05 | SNDK | relative_to_spy | down | +1.23 | +4.23 | +3.89 |
| 10:05 | APP | relative_to_sector | up | +1.56 | +0.53 | +0.73 |
| 10:06 | PL | relative_to_sector | up | -0.45 | -2.26 | -1.94 |
| 10:06 | SNOW | relative_to_sector | up | +0.96 | +0.61 | +0.66 |
| 10:08 | QBTS | relative_to_spy | down | +0.79 | -0.15 | -0.68 |
| 10:28 | Crypto and exchanges (MSTR, CRCL, COIN, HOOD, MARA, BULL, RIOT) | group_move | up | +0.11 | -0.22 | +0.55 |
| 10:35 | AI networking and connectivity (ANET, ALAB, COHR, CRDO, MRVL, AVGO) | group_move | up | +0.68 | -0.33 | +1.02 |
| 11:02 | Memory and storage (SNDK, WDC, MU, STX) | group_move | up | -0.07 | +0.90 | +2.19 |
| 15:53 | HIMS | relative_to_spy | up | — | — | — |

### Movers flags (64)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | MU | leaders | up | -5.22 | -5.40 | -3.46 |
| 09:31 | SNDK | leaders | up | -4.29 | -3.34 | -0.82 |
| 09:31 | STX | leaders | up | -6.16 | -7.19 | -6.65 |
| 09:31 | WDC | leaders | up | -4.77 | -6.38 | -3.66 |
| 09:31 | QCOM | leaders | up | -4.88 | -4.40 | -4.67 |
| 09:31 | CRDO | leaders | up | -6.53 | -4.24 | -5.01 |
| 09:31 | INTC | leaders | up | -8.07 | -6.42 | -6.75 |
| 09:31 | ALAB | leaders | up | -6.33 | -4.46 | -4.42 |
| 09:31 | CIFR | leaders | up | -9.23 | -8.54 | -9.24 |
| 09:31 | CRWV | leaders | up | -5.42 | -3.21 | -4.33 |
| 09:31 | APP | laggards | down | -0.50 | +1.00 | +1.02 |
| 09:31 | DELL | laggards | down | -3.56 | -2.60 | -2.10 |
| 09:31 | NOW | laggards | down | +0.64 | +1.02 | +0.03 |
| 09:31 | PLTR | laggards | down | -2.06 | -1.87 | -2.54 |
| 09:31 | AI | laggards | down | -4.17 | -2.20 | -2.23 |
| 09:31 | ADBE | laggards | down | +2.87 | +3.53 | +1.92 |
| 09:31 | GOOGL | laggards | down | +1.31 | +0.89 | +1.38 |
| 09:31 | RKLB | laggards | down | -2.98 | -2.50 | -2.87 |
| 09:31 | AAPL | laggards | down | -1.91 | -2.35 | -2.76 |
| 09:31 | BABA | laggards | down | -1.47 | -1.58 | -1.68 |
| 09:32 | CIEN | leaders | up | -5.57 | -2.25 | -2.09 |
| 09:32 | PL | laggards | down | +3.03 | +3.62 | +2.03 |
| 09:32 | LUNR | laggards | down | -1.87 | -0.11 | -1.84 |
| 09:32 | ASTS | laggards | down | -2.22 | -1.68 | -2.07 |
| 09:33 | COHR | leaders | up | -7.53 | -4.98 | -4.86 |
| 09:33 | AMD | leaders | up | -5.27 | -4.56 | -4.30 |
| 09:33 | RBLX | laggards | down | -0.82 | -1.05 | -0.63 |
| 09:34 | AMZN | laggards | down | +1.39 | +1.34 | +2.11 |
| 09:34 | RDDT | laggards | down | +0.21 | +2.24 | +1.07 |
| 09:35 | SNOW | laggards | down | +3.19 | +4.39 | +4.23 |
| 09:36 | HPQ | laggards | down | +1.63 | +2.85 | +3.08 |
| 09:38 | NBIS | leaders | up | -3.56 | -4.63 | -5.63 |
| 09:40 | MSTR | laggards | down | -0.91 | -1.45 | -3.85 |
| 09:42 | KMX | leaders | up | +0.48 | +0.80 | +0.38 |
| 09:42 | CAT | leaders | up | +0.58 | +1.05 | +0.39 |
| 09:44 | FND | leaders | up | +0.68 | +0.48 | -0.85 |
| 09:44 | UAA | leaders | up | +0.05 | -1.17 | -4.74 |
| 09:45 | MARA | laggards | down | -0.20 | +0.33 | +2.07 |
| 09:46 | CMI | leaders | up | +0.13 | +0.42 | -0.35 |
| 09:46 | BULL | laggards | down | +0.08 | -0.58 | +0.18 |
| 09:47 | HIMS | laggards | down | -0.44 | +0.15 | -0.23 |
| 09:47 | SNAP | laggards | down | +0.13 | -0.12 | -0.63 |
| 09:49 | AAOI | laggards | down | -2.84 | -1.00 | -3.46 |
| 09:51 | URI | leaders | up | +0.76 | +0.75 | +0.39 |
| 09:53 | PCAR | leaders | up | +0.63 | +0.87 | — |
| 09:54 | RIOT | laggards | down | +0.44 | +1.27 | +2.69 |
| 09:54 | CIFR | laggards | down | +0.94 | +1.89 | +0.05 |
| 09:56 | WULF | laggards | down | +2.29 | +3.89 | +1.80 |
| 09:59 | DE | leaders | up | +0.26 | +0.09 | -0.60 |
| 10:12 | FTNT | leaders | up | -0.23 | -0.60 | -0.42 |
| 10:15 | HUM | leaders | up | +0.15 | -0.01 | +1.18 |
| 10:21 | CLSK | laggards | down | -0.59 | -0.14 | +2.49 |
| 10:35 | ANET | leaders | up | +0.51 | +0.23 | +0.49 |
| 10:58 | TDOC | leaders | up | -2.81 | -2.32 | -1.23 |
| 11:14 | F | leaders | up | -0.46 | +0.17 | +0.19 |
| 11:17 | MRK | leaders | up | -0.56 | -0.71 | -0.49 |
| 11:49 | IONQ | laggards | down | +0.46 | -0.13 | -0.04 |
| 11:56 | CNC | leaders | up | +0.44 | -0.20 | -0.51 |
| 12:46 | OKLO | laggards | down | +0.80 | +0.57 | -0.13 |
| 14:28 | IREN | laggards | down | -1.00 | -1.28 | — |
| 14:44 | COIN | laggards | down | -0.65 | -0.61 | — |
| 14:46 | QUBT | laggards | down | +0.06 | -1.49 | — |
| 14:48 | RGTI | laggards | down | -0.35 | -0.47 | — |
| 14:51 | QBTS | laggards | down | -0.31 | -0.55 | — |

## 2026-06-26

Usable symbol-minutes 64,824/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | LCID | +16.35 | miss | 09:35 |
| 2 | WDC | -12.45 | miss | 09:31 |
| 3 | STX | -11.51 | miss | 09:31 |
| 4 | NOW | +10.58 | miss | 09:31 |
| 5 | CRDO | -10.48 | 15:53 | 09:33 |
| 6 | SNOW | +10.37 | miss | 14:59 |
| 7 | SNDK | -9.74 | miss | 09:31 |
| 8 | ASTS | +9.61 | 10:02 | 09:36 |
| 9 | DDOG | +9.25 | miss | 09:31 |
| 10 | LLY | +7.86 | 10:02 | 09:41 |
| 11 | APP | +7.71 | miss | 10:16 |
| 12 | CRCL | +7.64 | 10:02 | 09:43 |
| 13 | PINS | +7.60 | miss | 15:31 |
| 14 | ZS | +7.56 | miss | 09:31 |
| 15 | MDB | +7.49 | miss | 09:33 |
| 16 | S | +7.07 | miss | 09:46 |
| 17 | QCOM | -6.85 | miss | 15:19 |
| 18 | TDOC | +6.79 | miss | 09:50 |
| 19 | LUNR | +6.55 | 10:02 | 09:36 |
| 20 | MSFT | +6.43 | miss | 10:57 |

### Radar flags (14)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | ASTS | relative_to_spy | up | +0.74 | -0.13 | +1.00 |
| 10:02 | CRCL | relative_to_spy | up | -0.54 | -0.94 | -0.25 |
| 10:02 | HIMS | relative_to_spy | up | -2.12 | -2.49 | -1.54 |
| 10:02 | LLY | relative_to_spy | up | -0.76 | -0.69 | -0.05 |
| 10:02 | RIOT | relative_to_spy | up | +1.01 | -0.30 | -0.69 |
| 10:02 | LUNR | relative_to_sector | up | -0.74 | -0.15 | +0.76 |
| 10:02 | MSTR | relative_to_sector | up | -1.80 | -2.63 | -1.55 |
| 10:02 | Bitcoin treasuries and miners (RIOT, MSTR, COIN, CLSK, MARA, IREN) | group_move | up | +0.45 | -0.31 | +1.12 |
| 10:02 | Crypto and exchanges (CRCL, RIOT, MSTR, COIN, MARA, BULL, HOOD) | group_move | up | +0.03 | -0.51 | +0.57 |
| 10:02 | Space (ASTS, LUNR, RKLB, PL, IRDM) | group_move | up | +0.20 | -0.03 | +1.07 |
| 10:12 | MARA | relative_to_spy | up | +0.25 | -0.19 | +1.62 |
| 10:21 | Quantum computing (QBTS, IONQ, RGTI, QUBT) | group_move | up | +0.14 | -0.60 | -0.48 |
| 10:23 | Memory and storage (MU, SNDK, STX, WDC) | group_move | up | -1.82 | -3.10 | -3.41 |
| 15:53 | CRDO | relative_to_spy | down | — | — | — |

### Movers flags (52)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | NOW | leaders | up | +3.12 | +3.85 | +4.40 |
| 09:31 | RKLB | leaders | up | +2.87 | +2.09 | +2.43 |
| 09:31 | SONY | leaders | up | +0.35 | +0.06 | +0.12 |
| 09:31 | CRM | leaders | up | +1.24 | +1.55 | +1.30 |
| 09:31 | CRWD | leaders | up | -0.41 | +0.10 | -0.32 |
| 09:31 | ZS | leaders | up | +0.70 | +1.91 | +2.52 |
| 09:31 | ADBE | leaders | up | +0.60 | +0.87 | +1.09 |
| 09:31 | DDOG | leaders | up | +2.60 | +2.28 | +2.75 |
| 09:31 | PLTR | leaders | up | +1.57 | +2.61 | +3.07 |
| 09:31 | WMT | leaders | up | -0.48 | -0.87 | -0.91 |
| 09:31 | SNDK | laggards | down | +1.36 | +1.25 | -1.28 |
| 09:31 | AAOI | laggards | down | +1.06 | +0.81 | +0.81 |
| 09:31 | COHR | laggards | down | -0.98 | -1.20 | -2.57 |
| 09:31 | MU | laggards | down | +2.65 | +2.44 | +1.21 |
| 09:31 | NBIS | laggards | down | +0.84 | +1.49 | -2.00 |
| 09:31 | ALAB | laggards | down | +2.22 | +1.16 | -0.20 |
| 09:31 | APLD | laggards | down | -0.54 | +1.98 | -0.45 |
| 09:31 | WDC | laggards | down | -3.26 | -4.65 | -6.68 |
| 09:31 | STX | laggards | down | -1.27 | -2.11 | -4.21 |
| 09:31 | ARM | laggards | down | +0.38 | -0.36 | -0.20 |
| 09:32 | RCAT | leaders | up | +0.83 | +0.89 | +1.05 |
| 09:32 | NFLX | leaders | up | +1.11 | +2.12 | +2.46 |
| 09:32 | ANET | laggards | down | +1.07 | +0.85 | -0.61 |
| 09:33 | MDB | leaders | up | -0.10 | +0.35 | +1.07 |
| 09:33 | SPOT | leaders | up | -0.40 | +2.04 | +2.14 |
| 09:33 | CRDO | laggards | down | +1.84 | -0.40 | -1.02 |
| 09:34 | IBM | leaders | up | +0.30 | +0.89 | +2.10 |
| 09:34 | CIFR | laggards | down | +1.58 | +2.93 | +2.34 |
| 09:35 | LCID | leaders | up | +0.84 | +2.30 | +4.43 |
| 09:36 | ASTS | leaders | up | +3.83 | +4.77 | +6.02 |
| 09:36 | LUNR | leaders | up | +1.73 | +1.72 | +2.60 |
| 09:36 | MRVL | laggards | down | +0.88 | -0.24 | -1.52 |
| 09:37 | WULF | laggards | down | +1.33 | +1.93 | +2.29 |
| 09:41 | LLY | leaders | up | +2.45 | +1.98 | +2.18 |
| 09:43 | CRCL | leaders | up | +2.83 | +1.03 | +2.22 |
| 09:44 | HIMS | leaders | up | +2.44 | +0.45 | +0.94 |
| 09:46 | S | leaders | up | -0.65 | -0.72 | +0.26 |
| 09:50 | TDOC | leaders | up | -0.41 | -0.69 | +0.28 |
| 09:54 | DELL | laggards | down | +0.71 | +0.54 | -0.93 |
| 09:57 | PL | leaders | up | +1.39 | +1.19 | +2.57 |
| 09:57 | CMI | laggards | down | +0.05 | -0.54 | -1.52 |
| 10:01 | CAT | laggards | down | -0.02 | -0.72 | -0.53 |
| 10:07 | CRWV | laggards | down | -0.67 | -0.70 | -0.32 |
| 10:16 | APP | leaders | up | +1.98 | +2.16 | +3.30 |
| 10:36 | RDDT | leaders | up | +0.20 | +1.17 | +0.53 |
| 10:57 | MSFT | leaders | up | -0.32 | -0.39 | -0.16 |
| 11:27 | U | leaders | up | +0.43 | +0.66 | +0.05 |
| 13:10 | MARA | leaders | up | +0.40 | +1.33 | -1.19 |
| 14:59 | SNOW | leaders | up | +1.17 | +4.10 | — |
| 15:19 | QCOM | laggards | down | -1.39 | — | — |
| 15:31 | PINS | leaders | up | — | — | — |
| 15:35 | CVNA | laggards | down | — | — | — |

## 2026-06-29

Usable symbol-minutes 64,866/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | IRDM | +23.79 | miss | 09:31 |
| 2 | ASTS | +19.79 | miss | 09:31 |
| 3 | ALAB | +14.75 | 11:16 | 09:43 |
| 4 | RKLB | +14.29 | miss | 09:31 |
| 5 | PL | +13.90 | miss | 09:31 |
| 6 | RBLX | +12.61 | miss | 09:31 |
| 7 | MSTR | +10.95 | 13:18 | 09:31 |
| 8 | SMCI | -9.74 | 14:07 | 14:00 |
| 9 | CPRT | -9.67 | miss | 09:33 |
| 10 | RCAT | +9.56 | miss | 09:31 |
| 11 | WDC | +9.51 | miss | 11:09 |
| 12 | AAOI | +8.97 | 11:17 | 12:53 |
| 13 | LCID | +8.32 | miss | 10:26 |
| 14 | IONQ | +7.62 | miss | 09:31 |
| 15 | CLSK | -7.53 | 10:02 | 09:56 |
| 16 | PANW | +7.49 | 10:02 | 09:44 |
| 17 | NBIS | +7.03 | miss | 09:32 |
| 18 | TSLA | +6.81 | miss | miss |
| 19 | QUBT | +6.41 | miss | 09:41 |
| 20 | TGT | -6.26 | miss | 09:33 |

### Radar flags (46)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | CIFR | relative_to_spy | down | +0.09 | +1.20 | +1.55 |
| 10:02 | CLSK | relative_to_spy | down | -1.12 | -1.67 | -1.50 |
| 10:02 | COHR | relative_to_spy | down | +1.97 | +1.90 | +6.38 |
| 10:02 | CRDO | relative_to_spy | down | +0.52 | +3.12 | +3.60 |
| 10:02 | CRWD | relative_to_spy | up | -0.45 | -0.24 | -1.05 |
| 10:02 | FLNC | relative_to_spy | down | -0.47 | -0.60 | +1.03 |
| 10:02 | MARA | relative_to_spy | down | -0.25 | -0.14 | +1.24 |
| 10:02 | MRVL | relative_to_spy | down | +1.21 | +2.45 | +5.15 |
| 10:02 | PANW | relative_to_spy | up | +0.10 | +1.36 | +0.80 |
| 10:02 | RIOT | relative_to_spy | down | +1.28 | +1.05 | +0.89 |
| 10:02 | S | relative_to_spy | up | +0.64 | +0.71 | -0.73 |
| 10:02 | SNDK | relative_to_spy | down | +1.65 | +0.29 | +3.31 |
| 10:02 | AI networking and connectivity (COHR, MRVL, CRDO, AVGO) | group_move | down | +0.94 | +1.97 | +3.92 |
| 10:02 | Bitcoin treasuries and miners (CLSK, MARA, RIOT, IREN, COIN, MSTR) | group_move | down | -0.10 | -0.62 | +0.33 |
| 10:02 | Cybersecurity (PANW, CRWD, S, FTNT, NET, ZS) | group_move | up | +0.09 | +0.28 | -0.52 |
| 10:02 | Gaming platforms (APP, RBLX, TTWO, U) | group_move | up | -0.69 | -0.14 | -1.29 |
| 10:02 | Memory and storage (SNDK, MU, STX) | group_move | down | +1.99 | +1.65 | +4.44 |
| 10:02 | Neoclouds and AI hosting (CIFR, APLD, WULF, IREN, CRWV, ORCL, NBIS) | group_move | down | -1.41 | -1.20 | -0.15 |
| 10:03 | APLD | relative_to_spy | down | -1.55 | -2.45 | -1.08 |
| 10:04 | IREN | relative_to_spy | down | -0.80 | -2.28 | -1.03 |
| 10:04 | WULF | relative_to_spy | down | -0.49 | -1.25 | -1.09 |
| 10:05 | MU | relative_to_spy | down | -0.25 | +0.69 | +3.41 |
| 10:07 | CRWV | relative_to_spy | down | +0.95 | +0.84 | +3.61 |
| 10:07 | NBIS | relative_to_spy | down | -0.90 | -0.03 | +4.20 |
| 10:07 | GPUs and AI compute chips (MRVL, ARM, AMD, INTC, AVGO, QCOM, TSM, NVDA) | group_move | down | +0.36 | +1.48 | +3.04 |
| 10:08 | AAOI | relative_to_spy | down | +0.63 | +4.42 | +7.61 |
| 10:08 | Quantum computing (RGTI, QUBT, QBTS, IONQ) | group_move | down | +1.09 | +0.22 | +2.34 |
| 10:09 | Crypto and exchanges (MARA, RIOT, CRCL, BULL, COIN, MSTR) | group_move | down | +1.73 | +1.13 | +2.30 |
| 10:12 | HIMS | relative_to_spy | down | +1.17 | -0.86 | +1.10 |
| 10:13 | ALAB | relative_to_spy | down | +4.02 | +8.43 | +14.05 |
| 10:13 | ARM | relative_to_spy | down | +3.34 | +6.74 | +8.67 |
| 10:16 | AMD | relative_to_spy | down | +0.77 | +3.81 | +4.97 |
| 10:26 | CIEN | relative_to_sector | up | +2.78 | +3.40 | +6.22 |
| 10:33 | Memory and storage (STX, WDC, SNDK) | group_move | up | +0.40 | +0.85 | +3.99 |
| 10:43 | CIFR | relative_to_spy | up | -2.13 | -0.77 | -0.16 |
| 10:43 | RIOT | relative_to_spy | up | -2.71 | -0.94 | -1.76 |
| 10:43 | Bitcoin treasuries and miners (RIOT, MSTR, MARA, CLSK, IREN, COIN) | group_move | up | -2.00 | +0.09 | -0.19 |
| 10:56 | AI networking and connectivity (ALAB, CRDO, COHR, ANET, MRVL, AVGO) | group_move | up | +1.16 | +2.45 | +4.53 |
| 11:16 | ALAB | relative_to_spy | up | +0.87 | +4.58 | +4.76 |
| 11:17 | AAOI | relative_to_spy | up | -0.00 | +1.26 | +4.15 |
| 11:17 | Memory and storage (WDC, MU, STX, SNDK) | group_move | up | +0.82 | +3.46 | +3.97 |
| 11:18 | GPUs and AI compute chips (ARM, AMD, INTC, MRVL, QCOM, TSM, AVGO, NVDA) | group_move | up | +0.35 | +1.12 | +1.98 |
| 11:52 | Quantum computing (QUBT, QBTS, RGTI, IONQ) | group_move | up | +0.24 | +1.51 | +2.26 |
| 11:53 | Space (PL, RKLB, LUNR, ASTS, IRDM) | group_move | up | +0.98 | +1.57 | +2.76 |
| 13:18 | MSTR | relative_to_spy | up | +0.46 | -0.09 | -1.35 |
| 14:07 | SMCI | relative_to_spy | down | +1.63 | -0.67 | — |

### Movers flags (60)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | IRDM | leaders | up | +0.05 | +0.48 | +0.64 |
| 09:31 | RKLB | leaders | up | +0.09 | -0.40 | -0.90 |
| 09:31 | PL | leaders | up | +2.74 | +2.61 | +1.82 |
| 09:31 | ASTS | leaders | up | +1.16 | +2.73 | +3.64 |
| 09:31 | RBLX | leaders | up | +5.06 | +6.14 | +6.36 |
| 09:31 | LUNR | leaders | up | -3.33 | -2.97 | -5.68 |
| 09:31 | RCAT | leaders | up | -1.96 | -0.17 | -0.97 |
| 09:31 | MSTR | leaders | up | -0.79 | +1.07 | +1.41 |
| 09:31 | BIDU | leaders | up | +1.00 | +1.31 | +1.27 |
| 09:31 | IONQ | leaders | up | +0.21 | +0.58 | +0.06 |
| 09:31 | CIEN | laggards | down | -5.27 | -1.48 | +0.65 |
| 09:31 | COHR | laggards | down | -5.98 | -4.68 | -2.41 |
| 09:31 | UAA | laggards | down | -0.18 | +1.47 | -0.76 |
| 09:31 | MU | laggards | down | -4.69 | -4.93 | -2.65 |
| 09:31 | INTC | laggards | down | -3.20 | -4.18 | -0.86 |
| 09:31 | SNDK | laggards | down | -6.74 | -5.40 | -5.29 |
| 09:31 | ARM | laggards | down | -3.91 | -4.50 | -0.31 |
| 09:31 | PCAR | laggards | down | +0.37 | +0.00 | -0.79 |
| 09:31 | FND | laggards | down | -1.16 | +0.02 | -1.14 |
| 09:31 | DELL | laggards | down | -3.51 | -1.58 | -0.22 |
| 09:32 | NBIS | leaders | up | -1.60 | -5.23 | -2.56 |
| 09:32 | UNH | laggards | down | -0.22 | -0.35 | -0.91 |
| 09:32 | LULU | laggards | down | -1.51 | -0.83 | -2.54 |
| 09:33 | CPRT | laggards | down | -1.54 | -1.86 | -2.39 |
| 09:33 | TGT | laggards | down | -0.27 | +0.10 | -1.29 |
| 09:35 | CNC | laggards | down | -0.73 | -0.25 | +0.09 |
| 09:36 | RGTI | leaders | up | -2.88 | -2.30 | -3.43 |
| 09:36 | DASH | laggards | down | +2.65 | +3.53 | +3.04 |
| 09:38 | OKLO | leaders | up | -2.59 | -3.27 | -2.47 |
| 09:41 | QUBT | leaders | up | -3.99 | -3.03 | -1.48 |
| 09:41 | AN | laggards | down | — | — | — |
| 09:43 | ALAB | leaders | up | -6.27 | -2.56 | +3.30 |
| 09:44 | HSAI | leaders | up | -0.82 | -0.30 | +1.27 |
| 09:44 | PANW | leaders | up | +1.30 | +2.07 | +2.71 |
| 09:47 | CVNA | leaders | up | -0.75 | +0.13 | -3.11 |
| 09:47 | CRWD | leaders | up | +0.81 | +1.28 | +0.74 |
| 09:47 | MDB | leaders | up | +0.54 | +0.70 | -0.08 |
| 09:49 | APP | leaders | up | -0.98 | -0.33 | -1.18 |
| 09:50 | RIOT | laggards | down | -3.33 | +0.01 | -1.30 |
| 09:52 | MARA | laggards | down | -4.39 | -2.69 | -0.98 |
| 09:56 | S | leaders | up | +1.27 | +2.35 | +0.38 |
| 09:56 | CIFR | laggards | down | -2.43 | -0.49 | -0.39 |
| 09:56 | CLSK | laggards | down | -2.10 | -2.07 | -2.44 |
| 09:57 | CRDO | laggards | down | +0.69 | +3.57 | +4.29 |
| 09:59 | ZS | leaders | up | +0.11 | +0.10 | -1.59 |
| 10:00 | MRVL | laggards | down | +0.19 | +1.60 | +4.17 |
| 10:04 | CRWV | laggards | down | -0.35 | -0.46 | +1.32 |
| 10:05 | APLD | laggards | down | -0.14 | -1.59 | -0.15 |
| 10:17 | AMZN | leaders | up | -0.06 | -1.16 | -2.10 |
| 10:26 | LCID | leaders | up | +0.25 | -1.22 | -0.74 |
| 10:40 | FLNC | laggards | down | +0.18 | +0.75 | +3.19 |
| 10:49 | RIVN | leaders | up | -0.32 | -1.27 | -0.08 |
| 10:57 | IREN | laggards | down | -0.72 | +0.68 | +2.50 |
| 11:08 | WULF | laggards | down | +1.00 | +0.71 | +2.28 |
| 11:09 | WDC | leaders | up | +0.21 | +2.21 | +3.51 |
| 12:17 | STX | leaders | up | +0.79 | +1.03 | +1.99 |
| 12:27 | ONON | laggards | down | -0.20 | -0.18 | -0.83 |
| 12:53 | AAOI | leaders | up | -0.93 | -0.70 | -0.06 |
| 13:12 | DECK | laggards | down | +0.01 | -0.19 | -1.18 |
| 14:00 | SMCI | laggards | down | -1.42 | -3.71 | -4.32 |

## 2026-06-30

Usable symbol-minutes 64,763/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | CRCL | -18.33 | 10:56 | 09:31 |
| 2 | HSAI | +14.83 | 10:32 | 09:31 |
| 3 | SNDK | +10.11 | miss | 09:31 |
| 4 | CRDO | +9.91 | miss | 09:32 |
| 5 | MSTR | -6.98 | miss | 09:31 |
| 6 | AMD | +6.90 | miss | 09:31 |
| 7 | MRVL | +6.47 | miss | 09:34 |
| 8 | CLSK | -6.11 | miss | 09:31 |
| 9 | INTC | +5.23 | miss | 09:38 |
| 10 | UBER | -5.20 | miss | 10:18 |
| 11 | ALAB | +5.16 | 10:02 | 09:32 |
| 12 | PL | +5.14 | miss | 09:44 |
| 13 | LYFT | -4.98 | miss | 10:54 |
| 14 | NBIS | +4.97 | 10:02 | 09:36 |
| 15 | PINS | -4.66 | miss | 09:32 |
| 16 | COIN | -4.38 | miss | 09:31 |
| 17 | WULF | -4.22 | miss | 09:31 |
| 18 | BULL | -4.19 | miss | 15:36 |
| 19 | TSM | +4.16 | miss | 15:36 |
| 20 | NFLX | -4.00 | miss | 15:52 |

### Radar flags (14)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | ALAB | relative_to_spy | up | +1.47 | +1.46 | +0.64 |
| 10:02 | HIMS | relative_to_spy | up | +0.22 | -1.01 | -0.42 |
| 10:02 | NBIS | relative_to_spy | up | +4.25 | +2.95 | +1.54 |
| 10:02 | AI networking and connectivity (ALAB, CRDO, ANET, MRVL, COHR, AVGO) | group_move | up | +1.53 | +1.06 | +0.84 |
| 10:07 | Quantum computing (QBTS, RGTI, IONQ, QUBT) | group_move | up | -0.51 | -2.96 | -1.95 |
| 10:26 | Neoclouds and AI hosting (NBIS, WULF, IREN, CRWV, APLD, CIFR, ORCL) | group_move | up | -0.97 | -0.81 | -2.19 |
| 10:32 | HSAI | relative_to_spy | up | +0.08 | +1.57 | +1.04 |
| 10:49 | Quantum computing (QBTS, RGTI, IONQ, QUBT) | group_move | down | -0.46 | -0.49 | +0.52 |
| 10:56 | CRCL | relative_to_spy | down | -0.18 | -0.36 | -2.74 |
| 10:56 | RCAT | relative_to_spy | down | -0.33 | -2.10 | -0.64 |
| 10:56 | Space (ASTS, LUNR, RKLB, PL, IRDM) | group_move | down | +1.13 | +0.48 | +4.42 |
| 11:02 | Bitcoin treasuries and miners (MSTR, COIN, IREN, CLSK, RIOT) | group_move | down | +0.13 | +0.06 | +0.50 |
| 11:08 | FLNC | relative_to_sector | down | +0.99 | +1.41 | +1.14 |
| 12:16 | Space (RKLB, ASTS, PL, LUNR, IRDM) | group_move | up | +1.45 | +1.42 | +1.07 |

### Movers flags (60)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | HSAI | leaders | up | +0.69 | +6.41 | +7.74 |
| 09:31 | RCAT | leaders | up | +0.15 | +2.12 | -3.40 |
| 09:31 | FLNC | leaders | up | -0.61 | +2.33 | -0.53 |
| 09:31 | AMD | leaders | up | -0.33 | +0.15 | +1.34 |
| 09:31 | SNDK | leaders | up | +3.18 | +3.66 | +4.48 |
| 09:31 | QCOM | leaders | up | -0.91 | +0.12 | -3.38 |
| 09:31 | LUNR | leaders | up | -1.46 | +0.11 | -2.71 |
| 09:31 | CAT | leaders | up | +0.99 | +1.49 | +1.71 |
| 09:31 | RKLB | leaders | up | -1.26 | +0.86 | -0.49 |
| 09:31 | CMI | leaders | up | +0.47 | +0.74 | +1.16 |
| 09:31 | MSTR | laggards | down | -2.60 | +0.97 | -2.00 |
| 09:31 | CRCL | laggards | down | -4.75 | -3.79 | -8.58 |
| 09:31 | HIMS | laggards | down | +4.91 | +5.67 | +5.62 |
| 09:31 | WULF | laggards | down | -0.16 | +2.53 | +1.13 |
| 09:31 | CLSK | laggards | down | -1.18 | -0.07 | -2.75 |
| 09:31 | RGTI | laggards | down | +1.29 | +2.75 | +0.39 |
| 09:31 | AAOI | laggards | down | +1.89 | +3.50 | +0.22 |
| 09:31 | ASTS | laggards | down | +0.38 | +2.78 | +1.10 |
| 09:31 | COIN | laggards | down | -1.26 | -0.47 | -2.46 |
| 09:31 | QUBT | laggards | down | -0.58 | +1.05 | -1.89 |
| 09:32 | CRDO | leaders | up | +3.45 | +7.14 | +7.32 |
| 09:32 | ALAB | leaders | up | +4.97 | +6.52 | +6.03 |
| 09:32 | SCHW | leaders | up | +1.65 | +0.33 | -0.12 |
| 09:32 | MARA | laggards | down | +0.40 | +0.02 | +0.04 |
| 09:32 | PINS | laggards | down | +0.95 | +0.07 | -0.18 |
| 09:32 | RIOT | laggards | down | -0.19 | +1.66 | -0.18 |
| 09:33 | ARM | leaders | up | +0.94 | +2.03 | +0.30 |
| 09:33 | RBLX | leaders | up | -0.73 | -0.51 | -0.15 |
| 09:34 | MRVL | leaders | up | +2.58 | +4.45 | +4.70 |
| 09:34 | CIFR | laggards | down | +1.01 | +2.88 | +1.18 |
| 09:36 | NBIS | leaders | up | +3.99 | +7.11 | +5.69 |
| 09:38 | INTC | leaders | up | +1.46 | +1.11 | +3.18 |
| 09:40 | PANW | leaders | up | -0.71 | -0.18 | -0.32 |
| 09:43 | SMCI | leaders | up | +0.63 | +1.46 | +0.60 |
| 09:44 | PL | leaders | up | +0.51 | -0.88 | -0.43 |
| 09:44 | TGT | laggards | down | -0.61 | -0.47 | +0.02 |
| 09:45 | APLD | leaders | up | -1.08 | +1.50 | -2.50 |
| 09:47 | ZS | leaders | up | -1.25 | -0.98 | -1.15 |
| 09:50 | IREN | laggards | down | +2.95 | +1.76 | +0.77 |
| 10:00 | TDOC | laggards | down | +1.40 | +1.20 | +1.34 |
| 10:07 | NOW | laggards | down | +0.42 | -0.50 | -0.34 |
| 10:08 | FTNT | laggards | down | -0.28 | -0.33 | -0.29 |
| 10:09 | LCID | laggards | down | +3.21 | +0.93 | +2.43 |
| 10:16 | LLY | laggards | down | -0.07 | +0.80 | +0.42 |
| 10:18 | UBER | laggards | down | -0.24 | -0.14 | -0.97 |
| 10:19 | CRWV | leaders | up | -1.64 | -2.31 | -2.01 |
| 10:27 | LAD | laggards | down | +0.23 | -0.19 | — |
| 10:32 | PYPL | laggards | down | -2.24 | -2.06 | -1.26 |
| 10:39 | DELL | leaders | up | -0.38 | -2.12 | -2.36 |
| 10:54 | LYFT | laggards | down | +0.22 | -0.53 | +0.51 |
| 11:01 | OKLO | laggards | down | -0.00 | -1.13 | +0.29 |
| 11:12 | DIS | laggards | down | +0.52 | +0.46 | +0.18 |
| 11:13 | HPQ | laggards | down | +0.07 | -0.50 | -0.79 |
| 11:27 | DDOG | leaders | up | -0.52 | +0.12 | +0.80 |
| 11:33 | ANET | leaders | up | +0.05 | -0.33 | +0.67 |
| 12:56 | STX | laggards | down | +0.25 | +1.17 | +1.25 |
| 15:36 | TSM | leaders | up | — | — | — |
| 15:36 | BULL | laggards | down | — | — | — |
| 15:41 | LCID | leaders | up | — | — | — |
| 15:52 | NFLX | laggards | down | — | — | — |

## 2026-07-01

Usable symbol-minutes 64,779/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | NBIS | -16.88 | miss | 09:31 |
| 2 | RDDT | +14.07 | miss | 09:31 |
| 3 | CRWV | -13.78 | miss | 09:31 |
| 4 | RIOT | -12.36 | miss | 09:31 |
| 5 | ALAB | -10.66 | miss | 09:33 |
| 6 | SNDK | -10.49 | miss | 09:31 |
| 7 | MU | -10.43 | miss | 09:31 |
| 8 | BULL | +10.26 | miss | 15:31 |
| 9 | APP | +9.72 | miss | 09:32 |
| 10 | COIN | +9.06 | miss | 09:47 |
| 11 | META | +8.94 | miss | 09:31 |
| 12 | INTC | -8.90 | miss | 10:02 |
| 13 | MRVL | -8.54 | miss | 09:31 |
| 14 | HIMS | +8.50 | 10:06 | 09:31 |
| 15 | HOOD | +8.48 | miss | 11:04 |
| 16 | PDD | +8.32 | miss | 09:42 |
| 17 | PLTR | +7.90 | miss | 09:31 |
| 18 | ELV | +7.75 | miss | 16:00 |
| 19 | MSTR | +7.57 | 10:02 | 09:34 |
| 20 | FLNC | -7.51 | miss | 14:51 |

### Radar flags (21)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | MSTR | relative_to_spy | up | +1.22 | +1.58 | +3.86 |
| 10:02 | Crypto and exchanges (MSTR, CRCL, COIN, HOOD, BULL, MARA) | group_move | up | +0.14 | +0.39 | +2.64 |
| 10:06 | HIMS | relative_to_spy | up | -0.60 | +0.08 | +0.74 |
| 10:06 | RCAT | relative_to_spy | up | -2.77 | -3.52 | -1.53 |
| 10:06 | AI networking and connectivity (CRDO, COHR, ALAB, MRVL, ANET, AVGO) | group_move | up | -1.13 | -1.83 | -2.65 |
| 10:06 | Quantum computing (IONQ, QBTS, QUBT, RGTI) | group_move | up | -1.49 | -0.95 | -0.58 |
| 10:23 | Memory and storage (STX, WDC, SNDK, MU) | group_move | down | -1.75 | -1.25 | -0.66 |
| 10:42 | Space (ASTS, LUNR, RKLB, PL) | group_move | down | +1.67 | +4.45 | +5.27 |
| 10:43 | AI networking and connectivity (COHR, MRVL, ALAB, CRDO, AVGO) | group_move | down | -0.26 | -0.00 | -0.96 |
| 10:43 | Bitcoin treasuries and miners (RIOT, IREN, CLSK, MARA, MSTR, COIN) | group_move | down | +1.64 | +2.78 | +3.12 |
| 10:43 | Neoclouds and AI hosting (NBIS, IREN, CRWV, WULF, CIFR, APLD, ORCL) | group_move | down | +0.18 | +1.56 | +1.88 |
| 10:43 | Quantum computing (IONQ, QBTS, RGTI, QUBT) | group_move | down | +1.56 | +1.73 | +1.60 |
| 11:16 | Crypto and exchanges (COIN, HOOD, MSTR, MARA, BULL, CRCL) | group_move | up | +0.23 | +0.67 | +0.47 |
| 11:18 | Bitcoin treasuries and miners (COIN, MARA, MSTR, IREN, CLSK) | group_move | up | +0.55 | +1.07 | +1.20 |
| 11:18 | Space (RKLB, ASTS, PL, LUNR, IRDM) | group_move | up | +0.36 | +1.64 | +1.08 |
| 11:25 | ASTS | relative_to_spy | up | +0.52 | +2.40 | +3.33 |
| 11:25 | RKLB | relative_to_spy | up | +0.25 | +1.96 | +1.97 |
| 11:25 | Neoclouds and AI hosting (IREN, CIFR, WULF, NBIS, APLD, CRWV, ORCL) | group_move | up | -0.73 | +0.36 | +1.60 |
| 11:28 | LUNR | relative_to_spy | up | -1.01 | -0.03 | -1.17 |
| 11:28 | MARA | relative_to_spy | up | -2.07 | -0.86 | -0.56 |
| 11:28 | Quantum computing (QBTS, RGTI, IONQ, QUBT) | group_move | up | -0.54 | +0.05 | -0.01 |

### Movers flags (48)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | META | leaders | up | +2.00 | +2.70 | +4.63 |
| 09:31 | CNC | leaders | up | +0.67 | +0.14 | +0.06 |
| 09:31 | CRM | leaders | up | +0.41 | +0.74 | +0.88 |
| 09:31 | RDDT | leaders | up | +3.00 | +4.30 | +5.83 |
| 09:31 | NOW | leaders | up | +0.20 | +0.74 | +2.22 |
| 09:31 | MDB | leaders | up | +1.81 | +1.81 | +3.15 |
| 09:31 | AI | leaders | up | +1.63 | +1.57 | +2.26 |
| 09:31 | HIMS | leaders | up | +3.64 | +5.22 | +6.30 |
| 09:31 | TDOC | leaders | up | +0.90 | +2.45 | +2.47 |
| 09:31 | PLTR | leaders | up | +3.89 | +3.90 | +5.83 |
| 09:31 | NBIS | laggards | down | +1.97 | -0.74 | +0.96 |
| 09:31 | CRWV | laggards | down | +0.25 | -1.44 | -1.96 |
| 09:31 | SNDK | laggards | down | -0.96 | -1.86 | -2.59 |
| 09:31 | STX | laggards | down | +2.44 | +0.44 | +0.56 |
| 09:31 | MU | laggards | down | -0.62 | -1.20 | -2.67 |
| 09:31 | CIFR | laggards | down | -2.30 | -2.53 | -2.07 |
| 09:31 | RIOT | laggards | down | -2.31 | -5.15 | -4.36 |
| 09:31 | MRVL | laggards | down | +2.12 | +0.21 | -2.36 |
| 09:31 | WULF | laggards | down | -1.58 | -2.42 | -1.29 |
| 09:31 | COHR | laggards | down | +1.35 | +0.02 | -2.88 |
| 09:32 | APP | leaders | up | +3.09 | +3.16 | +5.53 |
| 09:32 | ZS | leaders | up | +0.44 | +0.46 | +0.92 |
| 09:32 | NVO | leaders | up | +0.07 | -0.28 | -0.74 |
| 09:32 | IREN | laggards | down | +0.50 | +0.51 | +1.62 |
| 09:32 | AAOI | laggards | down | +4.02 | +2.68 | +1.65 |
| 09:33 | RBLX | leaders | up | +0.48 | +2.09 | +2.81 |
| 09:33 | WDC | laggards | down | +1.08 | -0.92 | -0.24 |
| 09:33 | ALAB | laggards | down | +1.45 | +0.19 | +0.28 |
| 09:34 | MSTR | leaders | up | +4.56 | +4.60 | +7.94 |
| 09:35 | U | leaders | up | +2.11 | +3.37 | +4.34 |
| 09:35 | LUNR | leaders | up | -3.50 | -5.35 | -2.19 |
| 09:37 | CRDO | laggards | down | +4.75 | +3.77 | +3.57 |
| 09:41 | S | leaders | up | +0.74 | +0.98 | -0.02 |
| 09:42 | PDD | leaders | up | +1.13 | +2.42 | +2.90 |
| 09:47 | COIN | leaders | up | +2.47 | +1.80 | +6.00 |
| 09:47 | ARM | laggards | down | +0.07 | -1.90 | +0.49 |
| 09:47 | WMT | laggards | down | -0.98 | -0.72 | -1.10 |
| 10:02 | INTC | laggards | down | -1.16 | -3.23 | -3.82 |
| 10:07 | RCAT | leaders | up | -3.95 | -4.24 | -1.99 |
| 10:43 | SNAP | leaders | up | +2.38 | +1.83 | +0.93 |
| 11:04 | HOOD | leaders | up | +0.23 | +0.88 | +0.42 |
| 12:21 | TSM | laggards | down | -0.17 | -0.54 | -0.27 |
| 12:30 | CVNA | leaders | up | -0.37 | +0.10 | -2.45 |
| 14:08 | CAT | laggards | down | -0.46 | -0.12 | — |
| 14:51 | FLNC | laggards | down | +1.15 | -0.01 | — |
| 15:31 | BULL | leaders | up | — | — | — |
| 15:56 | AMD | laggards | down | — | — | — |
| 16:00 | ELV | leaders | up | — | — | — |

## 2026-07-02

Usable symbol-minutes 64,875/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | SNDK | -14.00 | 10:35 | 09:40 |
| 2 | AAOI | -12.85 | 10:30 | 09:31 |
| 3 | CIFR | -12.13 | 10:28 | 10:04 |
| 4 | IREN | -10.26 | miss | 09:44 |
| 5 | STX | -10.25 | 10:35 | 09:31 |
| 6 | WULF | -10.05 | miss | 09:31 |
| 7 | WDC | -9.79 | 10:35 | 10:50 |
| 8 | MRVL | -9.71 | miss | 09:38 |
| 9 | COHR | -9.44 | 10:31 | 09:31 |
| 10 | RIVN | +8.57 | 10:02 | 09:31 |
| 11 | CIEN | -8.51 | miss | 09:31 |
| 12 | LCID | -8.16 | 10:02 | 09:43 |
| 13 | MSTR | +8.03 | miss | 09:31 |
| 14 | RIOT | -7.59 | miss | 09:31 |
| 15 | TSLA | -7.36 | miss | 09:44 |
| 16 | FLNC | -7.28 | miss | 09:31 |
| 17 | CLSK | -7.21 | miss | 13:59 |
| 18 | DELL | -7.14 | miss | 09:31 |
| 19 | MARA | -7.12 | 11:09 | 14:52 |
| 20 | APLD | -6.79 | 10:30 | 10:26 |

### Radar flags (33)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | ALAB | relative_to_spy | up | -5.07 | -8.48 | -9.89 |
| 10:02 | ARM | relative_to_spy | up | -4.93 | -7.41 | -9.27 |
| 10:02 | CRDO | relative_to_spy | up | -7.21 | -9.16 | -10.90 |
| 10:02 | LCID | relative_to_spy | down | -2.09 | -5.04 | -3.91 |
| 10:02 | OKLO | relative_to_spy | up | -1.76 | -4.04 | -5.80 |
| 10:02 | PL | relative_to_spy | up | -1.97 | -4.68 | -4.21 |
| 10:02 | RIVN | relative_to_spy | up | +1.64 | -1.73 | -1.63 |
| 10:02 | AI networking and connectivity (CRDO, ALAB, COHR, ANET, AVGO, MRVL) | group_move | up | -3.82 | -5.39 | -6.81 |
| 10:02 | Quantum computing (IONQ, RGTI, QBTS, QUBT) | group_move | up | -2.24 | -4.07 | -6.37 |
| 10:02 | Space (PL, RKLB, LUNR, IRDM, ASTS) | group_move | up | -1.79 | -4.30 | -4.35 |
| 10:21 | Memory and storage (SNDK, WDC, STX, MU) | group_move | down | -3.38 | -4.54 | -5.28 |
| 10:24 | Neoclouds and AI hosting (CIFR, APLD, NBIS, WULF, CRWV, IREN, ORCL) | group_move | down | -3.66 | -4.61 | -5.85 |
| 10:28 | CIFR | relative_to_spy | down | -0.75 | -1.73 | -4.73 |
| 10:28 | AI networking and connectivity (COHR, CRDO, ALAB, MRVL, ANET, AVGO) | group_move | down | -2.07 | -2.70 | -4.09 |
| 10:29 | NBIS | relative_to_spy | down | -3.11 | -2.75 | -4.61 |
| 10:30 | AAOI | relative_to_spy | down | -3.54 | -5.38 | -10.73 |
| 10:30 | APLD | relative_to_spy | down | -1.71 | -2.97 | -4.67 |
| 10:30 | GPUs and AI compute chips (MRVL, ARM, INTC, AMD, QCOM, TSM, AVGO, NVDA) | group_move | down | -0.90 | -1.69 | -2.94 |
| 10:30 | Quantum computing (QBTS, IONQ, RGTI, QUBT) | group_move | down | -1.27 | -3.03 | -4.62 |
| 10:30 | Space (ASTS, RKLB, LUNR, PL, IRDM) | group_move | down | -2.10 | -1.87 | -2.48 |
| 10:31 | COHR | relative_to_spy | down | -1.25 | -1.82 | -3.92 |
| 10:31 | CRDO | relative_to_spy | down | -2.08 | -3.34 | -5.83 |
| 10:32 | ARM | relative_to_spy | down | -2.63 | -3.61 | -6.00 |
| 10:33 | ALAB | relative_to_spy | down | -3.27 | -4.22 | -5.42 |
| 10:35 | SNDK | relative_to_spy | down | -4.02 | -2.36 | -5.74 |
| 10:35 | STX | relative_to_spy | down | -2.00 | -1.17 | -4.07 |
| 10:35 | WDC | relative_to_spy | down | -2.30 | -1.67 | -4.12 |
| 10:44 | Crypto and exchanges (MARA, HOOD, BULL, CRCL, COIN, MSTR, RIOT) | group_move | down | -1.21 | -1.15 | -2.41 |
| 10:44 | Retail brokers and fintech (HOOD, BULL, SOFI, COIN, PYPL, SCHW) | group_move | down | -0.03 | +0.32 | -0.05 |
| 10:45 | Bitcoin treasuries and miners (IREN, MARA, MSTR, COIN, CLSK, RIOT) | group_move | down | -1.63 | -1.97 | -3.60 |
| 10:46 | IONQ | relative_to_spy | down | -2.05 | -1.59 | -3.45 |
| 11:09 | MARA | relative_to_spy | down | +0.30 | -1.19 | -2.54 |
| 11:37 | Space (ASTS, PL, RKLB, LUNR, IRDM) | group_move | up | -1.67 | -2.16 | -3.23 |

### Movers flags (66)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | MSTR | leaders | up | +2.30 | +1.90 | +0.99 |
| 09:31 | HOOD | leaders | up | +2.29 | +0.88 | -0.57 |
| 09:31 | RIVN | leaders | up | +7.43 | +8.96 | +6.26 |
| 09:31 | COIN | leaders | up | +1.67 | +1.14 | +0.44 |
| 09:31 | CRCL | leaders | up | +3.46 | +4.25 | +2.59 |
| 09:31 | RCAT | leaders | up | +3.83 | +2.02 | -2.37 |
| 09:31 | LCID | leaders | up | -5.74 | -7.64 | -9.56 |
| 09:31 | PLTR | leaders | up | +0.29 | +0.30 | -0.32 |
| 09:31 | ONON | leaders | up | -0.69 | -1.76 | +0.29 |
| 09:31 | NKE | leaders | up | +0.22 | -1.18 | -0.08 |
| 09:31 | RBLX | laggards | down | -0.43 | +0.62 | +1.00 |
| 09:31 | COHR | laggards | down | +4.37 | -0.89 | -2.69 |
| 09:31 | BIDU | laggards | down | +0.59 | -0.36 | -0.88 |
| 09:31 | WULF | laggards | down | +0.65 | -3.08 | -6.20 |
| 09:31 | AAOI | laggards | down | +1.98 | -3.19 | -8.34 |
| 09:31 | DELL | laggards | down | +0.70 | -1.78 | -3.74 |
| 09:31 | RIOT | laggards | down | +2.04 | +0.65 | -2.58 |
| 09:31 | CIEN | laggards | down | +0.25 | -2.36 | -3.60 |
| 09:31 | STX | laggards | down | +2.18 | -2.11 | -3.78 |
| 09:31 | FLNC | laggards | down | +3.04 | +0.03 | -4.09 |
| 09:32 | SMCI | leaders | up | +0.81 | -1.80 | -2.67 |
| 09:32 | SOFI | leaders | up | -3.53 | -4.50 | -5.13 |
| 09:32 | RDDT | laggards | down | +0.87 | -0.75 | -1.54 |
| 09:33 | ADBE | leaders | up | -0.19 | +0.31 | +0.92 |
| 09:33 | ALAB | laggards | down | +9.95 | +2.51 | -1.83 |
| 09:33 | MDB | laggards | down | +1.70 | +0.91 | +1.72 |
| 09:34 | MARA | leaders | up | -0.69 | -3.47 | -7.69 |
| 09:34 | CRDO | laggards | down | +9.16 | +0.28 | -1.59 |
| 09:34 | HSAI | laggards | down | -0.30 | -1.35 | -3.76 |
| 09:35 | RKLB | leaders | up | +2.27 | -1.05 | -2.43 |
| 09:35 | META | laggards | down | -1.75 | -1.63 | -1.72 |
| 09:36 | NET | laggards | down | +2.10 | +1.40 | +0.84 |
| 09:38 | AMD | laggards | down | +1.99 | -0.64 | -0.56 |
| 09:38 | MRVL | laggards | down | +1.06 | -2.45 | -3.96 |
| 09:40 | SNDK | laggards | down | +0.03 | -4.82 | -6.45 |
| 09:43 | LUNR | leaders | up | +0.11 | -2.77 | -3.59 |
| 09:43 | LCID | laggards | down | +1.79 | -4.61 | -3.37 |
| 09:44 | OKLO | leaders | up | +1.98 | -1.54 | -2.79 |
| 09:44 | TSLA | laggards | down | -0.68 | -4.05 | -3.27 |
| 09:44 | IREN | laggards | down | +0.15 | -4.18 | -7.07 |
| 09:51 | ASTS | leaders | up | -2.77 | -4.93 | -4.10 |
| 09:54 | ALAB | leaders | up | -1.81 | -7.87 | -9.01 |
| 09:59 | CRDO | leaders | up | -5.93 | -8.47 | -10.18 |
| 10:01 | ARM | leaders | up | -4.81 | -7.42 | -8.83 |
| 10:04 | CIFR | laggards | down | -4.53 | -6.44 | -10.41 |
| 10:05 | HIMS | laggards | down | -1.98 | -0.95 | +1.35 |
| 10:13 | BULL | leaders | up | -3.10 | -3.39 | -4.23 |
| 10:15 | IONQ | leaders | up | -4.55 | -6.27 | -6.57 |
| 10:15 | PL | leaders | up | -3.72 | -4.47 | -3.15 |
| 10:26 | NVO | leaders | up | +0.82 | +0.35 | +0.28 |
| 10:26 | AAPL | leaders | up | +0.92 | +1.23 | +2.00 |
| 10:26 | APLD | laggards | down | -3.00 | -3.63 | -5.54 |
| 10:39 | DECK | leaders | up | +0.34 | +1.56 | +1.37 |
| 10:44 | NBIS | laggards | down | -2.23 | -0.22 | -1.96 |
| 10:49 | AMGN | leaders | up | +0.43 | -0.26 | +0.12 |
| 10:50 | WDC | laggards | down | -1.52 | -0.83 | -3.64 |
| 10:58 | NFLX | leaders | up | +0.03 | +0.82 | +1.90 |
| 12:31 | WMT | leaders | up | +0.26 | -0.01 | -0.28 |
| 12:49 | LAD | leaders | up | +0.41 | +0.62 | +1.21 |
| 13:13 | CPRT | leaders | up | +0.11 | +0.11 | +0.26 |
| 13:59 | MA | leaders | up | -0.19 | -0.22 | -0.42 |
| 13:59 | CLSK | laggards | down | +1.09 | +0.76 | +1.86 |
| 14:21 | SPOT | leaders | up | +0.08 | +0.01 | — |
| 14:52 | MARA | laggards | down | -1.16 | +0.83 | — |
| 15:18 | DIS | leaders | up | +0.11 | — | — |
| 15:50 | CI | leaders | up | — | — | — |

## 2026-07-06

Usable symbol-minutes 64,772/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | IREN | +12.24 | miss | 09:31 |
| 2 | CRDO | +8.90 | 10:02 | 09:33 |
| 3 | LCID | +8.67 | miss | 11:34 |
| 4 | RKLB | -8.21 | miss | 09:36 |
| 5 | CIFR | +7.56 | miss | 09:31 |
| 6 | ANET | +7.43 | miss | 09:57 |
| 7 | RIVN | +7.23 | miss | 11:17 |
| 8 | WDC | +6.26 | miss | 09:31 |
| 9 | CLSK | +6.18 | miss | 09:31 |
| 10 | ASTS | -6.15 | miss | 09:38 |
| 11 | TSLA | +5.82 | miss | 14:28 |
| 12 | AMD | +5.74 | 10:02 | 09:46 |
| 13 | ALAB | +5.60 | 10:02 | 09:33 |
| 14 | CRCL | +5.36 | miss | 11:51 |
| 15 | STX | +4.99 | miss | 09:31 |
| 16 | QCOM | +4.93 | miss | miss |
| 17 | CRWV | +4.90 | miss | 13:38 |
| 18 | FND | -4.60 | miss | 09:32 |
| 19 | PCAR | +4.49 | miss | miss |
| 20 | LUNR | -4.40 | miss | 10:40 |

### Radar flags (17)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | AAOI | relative_to_spy | up | +2.61 | +1.96 | +2.17 |
| 10:02 | ALAB | relative_to_spy | up | -0.26 | -2.12 | -1.74 |
| 10:02 | AMD | relative_to_spy | up | +0.49 | +0.96 | +0.25 |
| 10:02 | CRDO | relative_to_spy | up | +2.59 | +1.58 | +0.59 |
| 10:02 | CRWD | relative_to_spy | up | +1.31 | -0.47 | -1.58 |
| 10:02 | DELL | relative_to_spy | up | +1.60 | +1.01 | -1.17 |
| 10:02 | RBLX | relative_to_sector | up | -1.84 | -0.16 | -0.49 |
| 10:02 | AI networking and connectivity (CRDO, ALAB, ANET, COHR, AVGO, MRVL) | group_move | up | +0.98 | +0.21 | -0.36 |
| 10:02 | AI software and analytics (NOW, AI, DDOG, SNOW, PLTR, APP) | group_move | up | -0.52 | -0.56 | +1.29 |
| 10:02 | Bitcoin treasuries and miners (MSTR, CLSK, MARA, RIOT, IREN, COIN) | group_move | up | +0.48 | -0.28 | +1.05 |
| 10:02 | Crypto and exchanges (CRCL, MSTR, MARA, RIOT, HOOD, COIN, BULL) | group_move | up | +0.30 | +0.10 | +1.80 |
| 10:02 | Cybersecurity (CRWD, PANW, NET, FTNT, ZS, S) | group_move | up | +0.03 | -0.76 | -0.60 |
| 10:02 | Quantum computing (RGTI, QUBT, QBTS, IONQ) | group_move | up | +0.10 | +0.36 | +0.78 |
| 10:05 | WULF | relative_to_sector | down | +2.55 | +2.07 | -0.18 |
| 10:09 | NBIS | relative_to_spy | up | +1.84 | +1.55 | +0.88 |
| 10:29 | Space (ASTS, RKLB, LUNR, PL, IRDM) | group_move | down | -0.42 | -0.61 | -1.10 |
| 11:15 | Memory and storage (WDC, SNDK, STX, MU) | group_move | down | +0.28 | +0.19 | -1.35 |

### Movers flags (65)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | WULF | leaders | up | -1.06 | +2.40 | -1.26 |
| 09:31 | IREN | leaders | up | +3.53 | +5.07 | +3.85 |
| 09:31 | CIFR | leaders | up | +1.48 | +2.35 | +2.38 |
| 09:31 | STX | leaders | up | -0.15 | +1.12 | -0.41 |
| 09:31 | WDC | leaders | up | +2.87 | +4.02 | +1.66 |
| 09:31 | APLD | leaders | up | +0.65 | +0.68 | -1.54 |
| 09:31 | RIOT | leaders | up | +2.86 | +3.31 | +1.56 |
| 09:31 | SNDK | leaders | up | -1.12 | -0.41 | -0.85 |
| 09:31 | CLSK | leaders | up | +4.34 | +3.77 | +3.12 |
| 09:31 | ARM | leaders | up | +1.90 | +1.06 | +0.59 |
| 09:31 | MSTR | laggards | down | +2.70 | +3.20 | +3.82 |
| 09:31 | DDOG | laggards | down | +2.40 | +3.77 | +3.01 |
| 09:31 | PYPL | laggards | down | +1.34 | +0.26 | +1.52 |
| 09:31 | NVO | laggards | down | -0.86 | -0.49 | -0.84 |
| 09:31 | SNOW | laggards | down | +2.97 | +2.13 | +3.71 |
| 09:31 | AAOI | laggards | down | +6.32 | +8.45 | +7.77 |
| 09:31 | ZS | laggards | down | +5.03 | +3.75 | +3.58 |
| 09:31 | AI | laggards | down | +2.75 | +0.76 | +4.07 |
| 09:31 | MDB | laggards | down | +1.60 | +1.64 | +2.31 |
| 09:31 | CRM | laggards | down | +1.22 | -0.14 | +1.61 |
| 09:32 | S | leaders | up | +0.67 | +1.05 | +1.32 |
| 09:32 | AVGO | leaders | up | +1.43 | +1.02 | -0.46 |
| 09:32 | COIN | laggards | down | +1.93 | +1.62 | +3.25 |
| 09:32 | CRCL | laggards | down | +4.84 | +4.62 | +7.81 |
| 09:32 | BULL | laggards | down | +1.01 | +1.58 | +1.89 |
| 09:32 | FND | laggards | down | -1.79 | -2.24 | -1.53 |
| 09:32 | ADBE | laggards | down | +0.43 | -1.14 | +0.64 |
| 09:33 | ALAB | leaders | up | +4.51 | +4.48 | +2.36 |
| 09:33 | CRDO | leaders | up | +6.08 | +9.41 | +7.48 |
| 09:33 | LULU | laggards | down | -1.69 | -2.21 | -1.95 |
| 09:33 | NKE | laggards | down | -1.54 | -3.22 | -2.05 |
| 09:34 | PFE | laggards | down | -0.06 | -0.63 | -0.59 |
| 09:35 | RCAT | laggards | down | +2.23 | +0.62 | +0.35 |
| 09:36 | RKLB | laggards | down | +1.01 | -0.19 | -1.69 |
| 09:36 | OKLO | laggards | down | +0.15 | +1.61 | +0.62 |
| 09:37 | NBIS | laggards | down | +4.55 | +7.22 | +5.22 |
| 09:38 | ASTS | laggards | down | +1.16 | -1.02 | -2.56 |
| 09:39 | V | laggards | down | -0.43 | -0.18 | +0.04 |
| 09:41 | MA | laggards | down | -0.02 | +0.32 | +0.53 |
| 09:42 | CI | laggards | down | -0.68 | -1.09 | -0.68 |
| 09:44 | MARA | leaders | up | -0.81 | -1.31 | -1.70 |
| 09:45 | AMGN | laggards | down | -1.14 | -0.87 | -0.50 |
| 09:46 | AMD | leaders | up | +2.36 | +2.42 | +1.69 |
| 09:48 | TGT | laggards | down | -0.69 | -0.99 | -1.33 |
| 09:48 | CNC | laggards | down | -0.96 | -1.16 | -1.42 |
| 09:57 | ANET | leaders | up | +0.99 | +1.65 | +0.75 |
| 09:57 | HD | laggards | down | -0.51 | -0.04 | +0.28 |
| 09:59 | FLNC | leaders | up | -2.53 | -1.82 | -0.93 |
| 09:59 | LOW | laggards | down | -0.68 | -0.45 | +0.15 |
| 10:02 | MRK | laggards | down | +0.08 | +0.02 | -0.33 |
| 10:10 | DELL | leaders | up | +0.49 | -0.40 | -2.45 |
| 10:32 | CPRT | laggards | down | -0.08 | +0.50 | +1.53 |
| 10:40 | LUNR | laggards | down | +0.85 | +0.45 | +1.52 |
| 10:56 | KMX | laggards | down | +1.02 | +1.22 | +1.39 |
| 11:17 | RIVN | leaders | up | -0.34 | -0.74 | -0.28 |
| 11:34 | LCID | leaders | up | -1.93 | -0.83 | +1.36 |
| 11:51 | CRCL | leaders | up | +0.00 | -0.67 | -1.46 |
| 12:11 | CVS | laggards | down | +0.42 | +0.44 | +0.42 |
| 13:31 | IRDM | laggards | down | +0.22 | +0.19 | +0.13 |
| 13:38 | CRWV | leaders | up | -1.44 | -0.53 | -1.03 |
| 14:00 | SNAP | laggards | down | +1.01 | +0.50 | +0.78 |
| 14:28 | TSLA | leaders | up | -0.14 | -0.10 | — |
| 15:10 | RDDT | leaders | up | -0.16 | — | — |
| 15:32 | UBER | laggards | down | — | — | — |
| 15:56 | ELV | laggards | down | — | — | — |

## 2026-07-07

Usable symbol-minutes 64,802/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | RIVN | -17.65 | miss | 09:31 |
| 2 | ALAB | -11.04 | 10:02 | 09:33 |
| 3 | RKLB | -9.92 | miss | 09:36 |
| 4 | LCID | -9.51 | miss | 09:35 |
| 5 | INTC | -9.19 | miss | 09:31 |
| 6 | NET | +9.07 | miss | 09:31 |
| 7 | IREN | -8.85 | 10:13 | 10:01 |
| 8 | FLNC | -8.62 | 10:13 | 10:23 |
| 9 | WULF | -8.39 | 10:02 | 09:56 |
| 10 | RCAT | -8.23 | 10:13 | 15:56 |
| 11 | NBIS | -7.89 | miss | 09:31 |
| 12 | APLD | -7.85 | 10:13 | 15:56 |
| 13 | ASTS | -7.50 | miss | miss |
| 14 | WDC | -7.38 | miss | 09:31 |
| 15 | RGTI | -7.38 | miss | 12:35 |
| 16 | CLSK | -7.15 | 10:10 | 10:09 |
| 17 | OKLO | -7.13 | 10:02 | miss |
| 18 | HSAI | -7.08 | miss | 12:22 |
| 19 | MRVL | -6.97 | miss | 09:31 |
| 20 | RIOT | -6.96 | miss | miss |

### Radar flags (23)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | ALAB | relative_to_spy | down | -1.82 | -3.54 | -2.92 |
| 10:02 | OKLO | relative_to_spy | down | -1.93 | -1.31 | -0.93 |
| 10:02 | WULF | relative_to_spy | down | -4.09 | -2.83 | -0.04 |
| 10:02 | Bitcoin treasuries and miners (IREN, CLSK, RIOT, COIN, MSTR, MARA) | group_move | down | -2.20 | -1.10 | -0.16 |
| 10:02 | Cybersecurity (S, PANW, FTNT, CRWD, ZS, NET) | group_move | down | +1.56 | +1.48 | +2.49 |
| 10:02 | Quantum computing (IONQ, QBTS, QUBT, RGTI) | group_move | down | -2.26 | -0.80 | -0.54 |
| 10:02 | Space (RKLB, LUNR, ASTS, PL, IRDM) | group_move | down | -0.17 | -0.38 | -0.39 |
| 10:04 | Crypto and exchanges (RIOT, BULL, COIN, MARA, MSTR, HOOD, CRCL) | group_move | down | -1.00 | -0.63 | +0.20 |
| 10:04 | Retail brokers and fintech (BULL, COIN, SOFI, HOOD, PYPL) | group_move | down | +0.17 | -0.08 | +0.31 |
| 10:05 | Neoclouds and AI hosting (WULF, CRWV, IREN, APLD, CIFR, NBIS, ORCL) | group_move | down | -2.53 | -1.10 | +0.04 |
| 10:10 | CLSK | relative_to_spy | down | -2.39 | +0.13 | -0.07 |
| 10:13 | AAOI | relative_to_spy | down | -2.78 | +0.00 | +0.42 |
| 10:13 | APLD | relative_to_spy | down | -2.05 | +0.49 | +1.18 |
| 10:13 | FLNC | relative_to_spy | down | -1.40 | -0.35 | -0.56 |
| 10:13 | IREN | relative_to_spy | down | -1.21 | +1.76 | +2.42 |
| 10:13 | RCAT | relative_to_spy | down | -1.47 | +0.18 | +1.16 |
| 10:13 | AI networking and connectivity (ALAB, CRDO, COHR, MRVL, ANET, AVGO) | group_move | down | -1.27 | -0.32 | +0.79 |
| 10:13 | Memory and storage (WDC, SNDK, STX, MU) | group_move | down | -1.97 | +1.84 | +1.82 |
| 11:10 | Bitcoin treasuries and miners (IREN, MARA, CLSK, RIOT, MSTR, COIN) | group_move | up | -0.28 | +0.46 | +2.12 |
| 11:10 | Memory and storage (SNDK, MU, STX, WDC) | group_move | up | -0.54 | +0.44 | +1.68 |
| 11:10 | Neoclouds and AI hosting (NBIS, WULF, IREN, CIFR, APLD, CRWV, ORCL) | group_move | up | -0.33 | +0.81 | +1.84 |
| 11:11 | Quantum computing (QUBT, QBTS, RGTI, IONQ) | group_move | up | -1.26 | -0.05 | +1.17 |
| 11:13 | SNDK | relative_to_spy | up | -1.33 | +0.42 | +1.76 |

### Movers flags (58)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | NET | leaders | up | -1.49 | +1.03 | +1.21 |
| 09:31 | DASH | leaders | up | +1.09 | +0.92 | +0.63 |
| 09:31 | SHEL | leaders | up | +0.77 | +1.28 | +1.26 |
| 09:31 | SPOT | leaders | up | -1.00 | -1.02 | -0.47 |
| 09:31 | MDB | leaders | up | -1.00 | -0.61 | +0.25 |
| 09:31 | TTWO | leaders | up | -2.21 | -1.84 | -1.85 |
| 09:31 | NOW | leaders | up | +0.20 | +0.92 | +1.28 |
| 09:31 | NVO | leaders | up | -0.44 | -0.15 | -0.62 |
| 09:31 | LLY | leaders | up | +0.63 | +1.28 | +1.19 |
| 09:31 | PINS | leaders | up | -1.10 | -0.96 | -1.14 |
| 09:31 | RIVN | laggards | down | -1.41 | -0.99 | -3.03 |
| 09:31 | MU | laggards | down | +0.64 | -0.64 | -0.33 |
| 09:31 | SNDK | laggards | down | -2.46 | -4.95 | -3.73 |
| 09:31 | INTC | laggards | down | -1.73 | -3.42 | -3.85 |
| 09:31 | AMD | laggards | down | -0.49 | -0.89 | -0.82 |
| 09:31 | MRVL | laggards | down | -1.31 | -3.40 | -3.73 |
| 09:31 | CRDO | laggards | down | -2.27 | -4.40 | -5.37 |
| 09:31 | WDC | laggards | down | -2.83 | -4.92 | -3.48 |
| 09:31 | AAOI | laggards | down | +2.40 | -1.22 | -1.52 |
| 09:31 | NBIS | laggards | down | -0.55 | -2.88 | -1.24 |
| 09:32 | U | leaders | up | -0.30 | -2.49 | -1.79 |
| 09:32 | IBM | leaders | up | -1.57 | -1.08 | +0.95 |
| 09:32 | CRM | leaders | up | -0.10 | +1.10 | +1.43 |
| 09:32 | CNC | leaders | up | -0.95 | -0.73 | -0.61 |
| 09:32 | CIFR | laggards | down | -0.12 | -2.99 | -1.04 |
| 09:32 | STX | laggards | down | -0.77 | -2.93 | -1.09 |
| 09:33 | OXY | leaders | up | -0.35 | +0.76 | +0.39 |
| 09:33 | ALAB | laggards | down | -3.48 | -5.63 | -7.84 |
| 09:34 | ADBE | leaders | up | -0.62 | +0.12 | +2.69 |
| 09:35 | XOM | leaders | up | +0.38 | +1.61 | +0.93 |
| 09:35 | LYFT | leaders | up | -1.11 | -0.76 | -1.59 |
| 09:35 | RDDT | leaders | up | -1.25 | -0.95 | -0.99 |
| 09:35 | LCID | laggards | down | +0.19 | -2.65 | -2.11 |
| 09:36 | HPQ | leaders | up | -0.79 | -1.27 | -0.76 |
| 09:36 | RKLB | laggards | down | -1.36 | -3.28 | -3.99 |
| 09:37 | TDOC | leaders | up | -1.30 | -0.98 | -1.34 |
| 09:40 | CVX | leaders | up | -0.24 | +0.84 | -0.28 |
| 09:48 | PFE | leaders | up | -0.46 | +0.05 | -0.46 |
| 09:50 | UBER | leaders | up | -0.34 | +0.16 | -0.39 |
| 09:52 | WMT | leaders | up | -0.06 | -0.22 | -0.63 |
| 09:56 | WULF | laggards | down | -4.74 | -4.55 | -1.44 |
| 10:01 | IONQ | laggards | down | -1.99 | -0.85 | -0.64 |
| 10:01 | IREN | laggards | down | -2.37 | -0.61 | -0.35 |
| 10:04 | META | leaders | up | -0.08 | -0.82 | -1.27 |
| 10:09 | CLSK | laggards | down | -2.35 | -0.10 | -0.18 |
| 10:15 | CI | leaders | up | +0.49 | +0.81 | -0.12 |
| 10:22 | COP | leaders | up | +0.41 | +0.71 | +0.13 |
| 10:23 | FLNC | laggards | down | +0.21 | +0.97 | +2.58 |
| 10:31 | SNOW | leaders | up | -0.43 | +0.71 | +0.60 |
| 10:42 | NFLX | leaders | up | -1.08 | -1.19 | -1.44 |
| 11:12 | KMX | leaders | up | -0.34 | -0.93 | +0.90 |
| 11:15 | ELV | leaders | up | +0.05 | -0.43 | -0.54 |
| 11:22 | DDOG | leaders | up | +0.51 | +0.67 | +1.63 |
| 12:22 | HSAI | laggards | down | +0.54 | +0.42 | +0.74 |
| 12:27 | PLTR | leaders | up | +0.69 | +1.02 | +1.76 |
| 12:35 | RGTI | laggards | down | +0.67 | +1.65 | +0.89 |
| 15:56 | RCAT | laggards | down | — | — | — |
| 15:56 | APLD | laggards | down | — | — | — |

## 2026-07-08

Usable symbol-minutes 64,763/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | WULF | +13.11 | 10:02 | 09:31 |
| 2 | BABA | +11.35 | miss | 09:31 |
| 3 | NBIS | +11.22 | miss | 09:35 |
| 4 | ANET | +9.07 | miss | 09:55 |
| 5 | IREN | +8.32 | miss | 09:31 |
| 6 | CRWV | +8.05 | miss | 09:47 |
| 7 | SMCI | +7.62 | miss | 09:47 |
| 8 | SNDK | +7.08 | miss | 09:36 |
| 9 | CIFR | +7.05 | miss | 09:32 |
| 10 | CIEN | +5.58 | miss | 12:12 |
| 11 | CRDO | +5.30 | 10:02 | 09:36 |
| 12 | BIDU | +5.24 | miss | 09:31 |
| 13 | AVGO | +5.14 | miss | 09:31 |
| 14 | FLNC | -5.00 | miss | 09:31 |
| 15 | JD | +4.61 | miss | 09:31 |
| 16 | PANW | -4.57 | miss | 10:01 |
| 17 | TDOC | -4.42 | miss | 10:04 |
| 18 | LUNR | -4.34 | miss | 12:37 |
| 19 | FND | -4.32 | miss | 09:31 |
| 20 | STX | +4.22 | miss | miss |

### Radar flags (9)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | CRDO | relative_to_spy | up | +0.10 | -2.14 | -4.68 |
| 10:02 | WULF | relative_to_spy | up | -0.00 | -1.52 | -3.68 |
| 10:02 | AI networking and connectivity (CRDO, ANET, ALAB, COHR, MRVL, AVGO) | group_move | up | -0.38 | -1.26 | -3.00 |
| 10:02 | Memory and storage (MU, WDC, SNDK, STX) | group_move | up | -0.48 | -2.00 | -3.82 |
| 10:04 | Cybersecurity (PANW, CRWD, NET, ZS, S, FTNT) | group_move | down | -0.14 | -0.51 | +0.02 |
| 10:14 | DELL | relative_to_spy | down | +0.74 | +1.78 | +2.69 |
| 11:26 | AI networking and connectivity (ALAB, MRVL, CRDO, COHR, ANET, AVGO) | group_move | down | -0.17 | +1.28 | +2.71 |
| 11:26 | Neoclouds and AI hosting (APLD, WULF, CIFR, IREN, CRWV, NBIS, ORCL) | group_move | down | -0.05 | +0.10 | +0.36 |
| 15:58 | Memory and storage (STX, WDC, SNDK) | group_move | up | — | — | — |

### Movers flags (56)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | BABA | leaders | up | +0.88 | +0.95 | +1.52 |
| 09:31 | BIDU | leaders | up | -0.39 | +0.30 | -0.51 |
| 09:31 | WULF | leaders | up | +6.34 | +5.75 | +3.35 |
| 09:31 | JD | leaders | up | -0.07 | +0.60 | +0.95 |
| 09:31 | OXY | leaders | up | -0.57 | +0.58 | +2.90 |
| 09:31 | DELL | leaders | up | +1.30 | -2.08 | -1.99 |
| 09:31 | AVGO | leaders | up | +0.93 | +1.42 | +1.56 |
| 09:31 | IREN | leaders | up | +4.36 | +2.82 | +0.17 |
| 09:31 | PDD | leaders | up | +0.07 | -0.08 | +0.44 |
| 09:31 | RKLB | leaders | up | -0.20 | -1.35 | -4.04 |
| 09:31 | RIVN | laggards | down | +1.80 | +2.82 | +4.32 |
| 09:31 | FLNC | laggards | down | +1.08 | +0.88 | -3.17 |
| 09:31 | HIMS | laggards | down | +2.78 | +0.79 | -0.28 |
| 09:31 | FND | laggards | down | -0.01 | -1.31 | -2.04 |
| 09:31 | NOW | laggards | down | -0.72 | -0.17 | +0.17 |
| 09:31 | CVNA | laggards | down | +1.17 | +0.73 | -1.40 |
| 09:31 | HD | laggards | down | -0.22 | -0.26 | +0.36 |
| 09:31 | MSTR | laggards | down | -0.62 | -0.94 | -1.46 |
| 09:31 | PLTR | laggards | down | -2.12 | -1.19 | -1.08 |
| 09:31 | COIN | laggards | down | +0.93 | +0.27 | -0.17 |
| 09:32 | CIFR | leaders | up | +1.50 | +1.18 | -1.41 |
| 09:32 | WDC | leaders | up | +2.28 | +0.96 | -2.18 |
| 09:32 | DASH | laggards | down | -0.22 | -1.88 | -2.24 |
| 09:32 | LOW | laggards | down | +0.17 | -0.05 | +0.40 |
| 09:32 | UAA | laggards | down | -1.35 | -2.62 | -2.17 |
| 09:34 | RCAT | leaders | up | -1.35 | -2.53 | -4.91 |
| 09:34 | APLD | leaders | up | -1.02 | -0.88 | -4.29 |
| 09:34 | ASTS | leaders | up | +0.32 | +0.88 | -2.85 |
| 09:35 | NBIS | leaders | up | +0.49 | +4.58 | +0.52 |
| 09:35 | DECK | laggards | down | -0.39 | -0.85 | -1.67 |
| 09:36 | CRDO | leaders | up | +0.07 | +2.06 | -1.72 |
| 09:36 | SNDK | leaders | up | -0.50 | +0.40 | -3.42 |
| 09:39 | RDDT | laggards | down | +1.56 | +0.16 | +0.16 |
| 09:42 | U | laggards | down | -0.13 | -0.49 | -0.40 |
| 09:47 | SMCI | leaders | up | -1.15 | -1.86 | -2.67 |
| 09:47 | CRWV | leaders | up | -0.87 | -0.32 | -1.97 |
| 09:47 | AXP | laggards | down | +0.90 | +0.04 | +0.52 |
| 09:48 | ALAB | leaders | up | -2.25 | -3.10 | -3.75 |
| 09:49 | CRCL | laggards | down | -0.33 | -0.95 | -0.43 |
| 09:50 | NET | laggards | down | -0.21 | +1.50 | +1.66 |
| 09:55 | ANET | leaders | up | +1.07 | +1.92 | +0.51 |
| 09:56 | COHR | leaders | up | -1.62 | -2.82 | -5.36 |
| 10:01 | PANW | laggards | down | -1.11 | -1.84 | -1.18 |
| 10:01 | RBLX | laggards | down | -0.46 | -0.24 | -1.54 |
| 10:04 | TDOC | laggards | down | -1.12 | -0.46 | -0.33 |
| 10:08 | CNC | leaders | up | -0.93 | -1.79 | — |
| 10:12 | TGT | leaders | up | +0.41 | +0.05 | +1.18 |
| 10:14 | ZS | laggards | down | +0.02 | -0.03 | +0.15 |
| 11:05 | CRWD | laggards | down | +0.26 | +1.03 | +1.35 |
| 11:18 | COP | leaders | up | -0.20 | -0.90 | -2.29 |
| 11:21 | INTC | laggards | down | -0.48 | +0.69 | +1.12 |
| 11:25 | CVX | leaders | up | +0.15 | -1.01 | -2.07 |
| 12:03 | PL | laggards | down | -0.08 | -1.01 | -1.60 |
| 12:12 | CIEN | leaders | up | +0.76 | +0.59 | +0.88 |
| 12:37 | LUNR | laggards | down | -1.63 | -1.58 | -1.67 |
| 13:02 | CLSK | laggards | down | +1.38 | +1.32 | +1.53 |

## 2026-07-09

Usable symbol-minutes 64,551/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | MARA | +9.14 | 10:39 | 09:31 |
| 2 | ARM | +8.36 | miss | 09:32 |
| 3 | FLNC | +8.28 | miss | 09:35 |
| 4 | RIVN | +7.92 | 10:02 | 10:07 |
| 5 | SNDK | +6.74 | miss | 09:37 |
| 6 | AAOI | +5.94 | miss | 09:31 |
| 7 | CIFR | +5.61 | miss | 09:31 |
| 8 | ALAB | +5.33 | miss | 09:31 |
| 9 | COST | -5.06 | miss | 09:33 |
| 10 | S | +5.05 | miss | 15:51 |
| 11 | AMD | +4.82 | miss | 09:34 |
| 12 | PANW | +4.68 | miss | 15:56 |
| 13 | WDC | +4.20 | miss | 09:31 |
| 14 | SOFI | +4.17 | miss | miss |
| 15 | MRVL | +4.14 | miss | 09:31 |
| 16 | CIEN | +4.00 | miss | 09:31 |
| 17 | META | +3.86 | miss | miss |
| 18 | IREN | -3.83 | miss | 15:42 |
| 19 | QUBT | +3.72 | miss | 15:02 |
| 20 | MU | +3.67 | miss | 09:31 |

### Radar flags (14)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | ORCL | relative_to_spy | up | -2.33 | -2.32 | -1.76 |
| 10:02 | RIVN | relative_to_spy | up | +1.31 | +2.31 | +1.64 |
| 10:02 | AI software and analytics (NOW, DDOG, APP, SNOW, AI, PLTR) | group_move | up | -0.72 | -0.26 | -0.68 |
| 10:02 | Cloud software and data (ORCL, NOW, DDOG, MDB, CRM, ADBE, SNOW) | group_move | up | -0.52 | -0.15 | -0.35 |
| 10:02 | Cybersecurity (ZS, FTNT, S, CRWD, PANW, NET) | group_move | up | +0.63 | +0.84 | +0.60 |
| 10:02 | Gaming platforms (APP, U, RBLX) | group_move | up | +0.01 | +0.25 | -0.87 |
| 10:02 | Social and ads (APP, SNAP, META, PINS, RDDT) | group_move | up | -1.15 | -0.88 | -1.07 |
| 10:07 | Crypto and exchanges (MARA, HOOD, RIOT, MSTR, BULL, CRCL, COIN) | group_move | up | +0.53 | +1.84 | +1.46 |
| 10:23 | AI networking and connectivity (COHR, ANET, ALAB, CRDO, MRVL, AVGO) | group_move | down | +1.11 | +2.34 | +2.13 |
| 10:23 | Neoclouds and AI hosting (NBIS, IREN, CRWV, APLD, WULF, ORCL, CIFR) | group_move | down | +1.41 | +1.67 | +1.48 |
| 10:27 | AAOI | relative_to_spy | down | +1.05 | +2.69 | +0.21 |
| 10:39 | MARA | relative_to_sector | up | +2.99 | -1.04 | -3.72 |
| 10:48 | MARA | relative_to_spy | up | -0.29 | -2.73 | -6.09 |
| 10:52 | Quantum computing (QUBT, QBTS, RGTI, IONQ) | group_move | up | -0.31 | +0.06 | -0.83 |

### Movers flags (52)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | MARA | leaders | up | +3.66 | +6.72 | +7.87 |
| 09:31 | MU | leaders | up | +1.10 | +0.03 | +0.16 |
| 09:31 | CRDO | leaders | up | -3.34 | -3.47 | -0.29 |
| 09:31 | CIFR | leaders | up | -1.53 | -2.64 | +0.47 |
| 09:31 | ALAB | leaders | up | +1.69 | +0.37 | +1.30 |
| 09:31 | STX | leaders | up | +1.67 | +0.63 | -0.43 |
| 09:31 | WDC | leaders | up | +1.95 | +0.49 | +0.73 |
| 09:31 | MRVL | leaders | up | +0.66 | -0.47 | -0.15 |
| 09:31 | AAOI | leaders | up | +3.20 | -0.62 | +2.19 |
| 09:31 | CIEN | leaders | up | +2.99 | +0.14 | +0.60 |
| 09:31 | CRM | laggards | down | +2.64 | +2.40 | +3.04 |
| 09:31 | IBM | laggards | down | +2.96 | +2.67 | +2.47 |
| 09:31 | NOW | laggards | down | +4.00 | +3.45 | +4.60 |
| 09:31 | META | laggards | down | +2.00 | +2.28 | +3.96 |
| 09:31 | PLTR | laggards | down | +0.59 | -1.44 | -0.76 |
| 09:31 | APP | laggards | down | +4.23 | +2.99 | +2.81 |
| 09:31 | SPOT | laggards | down | +2.03 | +2.16 | +2.52 |
| 09:31 | S | laggards | down | +3.86 | +4.75 | +5.83 |
| 09:31 | MDB | laggards | down | +3.33 | +2.93 | +3.22 |
| 09:31 | ADBE | laggards | down | +2.03 | +1.63 | +2.23 |
| 09:32 | ARM | leaders | up | +2.69 | +3.23 | +3.50 |
| 09:32 | COHR | leaders | up | -0.29 | -2.70 | -2.38 |
| 09:32 | CRCL | laggards | down | +1.68 | +0.26 | +3.33 |
| 09:33 | COST | laggards | down | -1.51 | -1.48 | -2.04 |
| 09:34 | AMD | leaders | up | +1.57 | +1.71 | +0.77 |
| 09:34 | HSAI | laggards | down | +0.16 | +0.90 | +2.89 |
| 09:35 | FLNC | leaders | up | +0.62 | +0.66 | +3.11 |
| 09:35 | LCID | laggards | down | +1.14 | +2.87 | +3.05 |
| 09:37 | SNDK | leaders | up | +1.25 | +0.35 | +2.17 |
| 09:42 | OXY | laggards | down | -0.67 | -0.14 | -0.92 |
| 09:45 | DIS | laggards | down | +0.34 | +0.56 | +0.76 |
| 09:47 | XOM | laggards | down | -0.37 | -0.34 | -1.00 |
| 09:55 | GOOGL | laggards | down | -1.18 | -0.89 | -1.35 |
| 09:56 | CPRT | laggards | down | +0.22 | -0.08 | -1.10 |
| 09:57 | MSFT | laggards | down | -0.12 | +0.10 | +0.56 |
| 09:58 | COP | laggards | down | +0.18 | -0.01 | -0.69 |
| 10:02 | ASTS | laggards | down | -0.72 | +0.13 | +0.18 |
| 10:06 | NVDA | laggards | down | -0.45 | +0.19 | +0.49 |
| 10:07 | RIVN | leaders | up | +0.14 | -0.22 | -0.38 |
| 10:51 | NFLX | laggards | down | +0.39 | +0.10 | -0.23 |
| 11:39 | AMGN | laggards | down | -0.11 | -0.17 | -0.18 |
| 11:59 | WULF | leaders | up | -2.58 | -2.29 | -2.72 |
| 13:19 | CVS | laggards | down | -0.05 | +0.51 | +0.52 |
| 14:13 | TTWO | laggards | down | -0.91 | -0.08 | — |
| 14:36 | HIMS | laggards | down | +0.25 | -0.10 | — |
| 15:02 | QUBT | leaders | up | -0.62 | — | — |
| 15:04 | CLSK | leaders | up | -0.48 | — | — |
| 15:28 | PL | laggards | down | -0.26 | — | — |
| 15:31 | OKLO | leaders | up | — | — | — |
| 15:42 | IREN | laggards | down | — | — | — |
| 15:51 | S | leaders | up | — | — | — |
| 15:56 | PANW | leaders | up | — | — | — |

## 2026-07-10

Usable symbol-minutes 64,464/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | MDB | -6.16 | 10:02 | 10:14 |
| 2 | CRWD | -6.09 | miss | 10:32 |
| 3 | QUBT | -5.79 | miss | 14:03 |
| 4 | ZS | -5.77 | miss | 10:28 |
| 5 | WULF | -5.73 | 10:03 | 09:57 |
| 6 | S | -5.63 | miss | 09:33 |
| 7 | META | +5.54 | miss | 09:31 |
| 8 | QBTS | -5.49 | 10:03 | 11:05 |
| 9 | CIFR | -5.38 | 10:03 | 09:50 |
| 10 | LCID | -5.23 | miss | 14:49 |
| 11 | MARA | -5.12 | 10:02 | 09:54 |
| 12 | LUNR | -4.93 | miss | 09:32 |
| 13 | IONQ | -4.70 | miss | 09:42 |
| 14 | DDOG | -4.69 | miss | 10:32 |
| 15 | PL | -4.66 | miss | 09:31 |
| 16 | CRCL | +4.54 | miss | 09:31 |
| 17 | KMX | +4.43 | miss | 09:40 |
| 18 | ONON | +4.38 | miss | 10:49 |
| 19 | RCAT | -4.35 | miss | 15:49 |
| 20 | FTNT | -4.23 | miss | 12:52 |

### Radar flags (19)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | FLNC | relative_to_spy | down | +1.69 | +0.82 | +1.10 |
| 10:02 | HOOD | relative_to_spy | down | +0.15 | +0.28 | +1.85 |
| 10:02 | MARA | relative_to_spy | down | -1.01 | -1.26 | -0.86 |
| 10:02 | MDB | relative_to_spy | down | -2.56 | -1.73 | -1.99 |
| 10:02 | AI software and analytics (APP, PLTR, DDOG, SNOW, NOW, AI) | group_move | down | -0.79 | -1.09 | -0.90 |
| 10:02 | Bitcoin treasuries and miners (MARA, RIOT, CLSK, COIN, IREN, MSTR) | group_move | down | -0.09 | -1.23 | -0.77 |
| 10:02 | Crypto and exchanges (MARA, HOOD, CRCL, RIOT, COIN, MSTR, BULL) | group_move | down | -0.15 | -0.88 | -0.57 |
| 10:02 | Gaming platforms (RBLX, APP, U, TTWO) | group_move | down | +0.38 | -0.58 | -0.21 |
| 10:02 | Neoclouds and AI hosting (WULF, CIFR, APLD, IREN, NBIS, CRWV, ORCL) | group_move | down | +1.03 | -0.31 | +0.74 |
| 10:02 | Quantum computing (QBTS, IONQ, RGTI, QUBT) | group_move | down | +1.42 | -0.26 | -0.13 |
| 10:02 | Space (PL, LUNR, ASTS, RKLB, IRDM) | group_move | down | +1.42 | +0.56 | +0.70 |
| 10:03 | AAOI | relative_to_spy | down | +0.14 | -1.07 | +0.68 |
| 10:03 | CIFR | relative_to_spy | down | -0.73 | -1.01 | -0.29 |
| 10:03 | WULF | relative_to_spy | down | +0.09 | -1.14 | -1.33 |
| 10:03 | QBTS | relative_to_sector | down | +0.64 | -0.93 | -1.30 |
| 10:06 | CRCL | relative_to_spy | down | -1.22 | -0.54 | -1.91 |
| 10:07 | Memory and storage (STX, SNDK, WDC, MU) | group_move | up | -0.27 | -0.83 | -0.21 |
| 10:27 | Cybersecurity (CRWD, S, NET, ZS, PANW, FTNT) | group_move | down | -0.64 | -0.96 | -1.38 |
| 12:54 | Neoclouds and AI hosting (IREN, WULF, NBIS, APLD, CIFR, CRWV, ORCL) | group_move | up | -0.63 | -0.45 | -1.18 |

### Movers flags (76)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | CRCL | leaders | up | -3.32 | -3.05 | -4.94 |
| 09:31 | U | leaders | up | -3.89 | -4.34 | -5.47 |
| 09:31 | META | leaders | up | +1.45 | +0.83 | +1.68 |
| 09:31 | COIN | leaders | up | -2.82 | -2.71 | -3.86 |
| 09:31 | MSTR | leaders | up | -0.98 | -1.65 | -3.28 |
| 09:31 | SOFI | leaders | up | -0.37 | -1.33 | -1.96 |
| 09:31 | MARA | leaders | up | -6.58 | -7.99 | -6.68 |
| 09:31 | JD | leaders | up | +0.12 | +0.18 | -0.37 |
| 09:31 | RDDT | leaders | up | -2.20 | -4.16 | -4.27 |
| 09:31 | BABA | leaders | up | +0.66 | +0.66 | -0.72 |
| 09:31 | SNDK | laggards | down | +2.75 | +4.52 | +6.06 |
| 09:31 | MU | laggards | down | +1.12 | +1.68 | +1.59 |
| 09:31 | INTC | laggards | down | -0.35 | +0.06 | +0.13 |
| 09:31 | CIEN | laggards | down | +0.07 | +1.08 | +1.51 |
| 09:31 | NBIS | laggards | down | -2.01 | +0.56 | +2.33 |
| 09:31 | QCOM | laggards | down | -0.21 | -0.12 | +0.41 |
| 09:31 | MRVL | laggards | down | -1.32 | -1.30 | -1.06 |
| 09:31 | WDC | laggards | down | +0.90 | +1.68 | +1.55 |
| 09:31 | PL | laggards | down | -4.84 | -4.30 | -4.32 |
| 09:31 | STX | laggards | down | +2.39 | +3.49 | +4.04 |
| 09:32 | BULL | leaders | up | -0.78 | -1.39 | -1.50 |
| 09:32 | SNOW | leaders | up | -2.25 | -4.77 | -5.10 |
| 09:32 | HOOD | leaders | up | -5.87 | -5.72 | -4.60 |
| 09:32 | LUNR | laggards | down | -3.24 | -1.43 | -2.81 |
| 09:32 | LLY | laggards | down | +0.07 | -0.37 | -0.75 |
| 09:33 | SNAP | leaders | up | -1.33 | -2.28 | -1.92 |
| 09:33 | APP | leaders | up | -4.28 | -4.02 | -4.24 |
| 09:33 | RKLB | laggards | down | -1.76 | -0.79 | -0.49 |
| 09:33 | S | laggards | down | -0.93 | -3.74 | -3.70 |
| 09:34 | CVNA | leaders | up | -1.13 | -1.93 | -2.85 |
| 09:34 | HIMS | laggards | down | -1.86 | -3.18 | -2.11 |
| 09:35 | HSAI | leaders | up | -0.25 | -0.73 | -1.54 |
| 09:35 | FLNC | laggards | down | -4.20 | -2.81 | -4.21 |
| 09:38 | LYFT | leaders | up | -0.72 | -1.43 | -1.02 |
| 09:38 | DELL | laggards | down | +2.47 | +1.09 | +0.39 |
| 09:39 | CLSK | leaders | up | -3.96 | -4.90 | -4.49 |
| 09:40 | KMX | leaders | up | +1.69 | +1.70 | +3.14 |
| 09:40 | CRDO | laggards | down | +1.99 | +1.02 | -0.33 |
| 09:41 | ADBE | leaders | up | -1.37 | -1.64 | -1.59 |
| 09:41 | AAOI | laggards | down | -2.81 | -2.67 | -1.83 |
| 09:42 | FND | leaders | up | +0.20 | +0.37 | -0.10 |
| 09:42 | IONQ | laggards | down | +0.16 | -0.90 | -1.06 |
| 09:42 | APLD | laggards | down | -0.30 | -1.24 | -1.24 |
| 09:43 | HOOD | laggards | down | -0.76 | -0.26 | -0.13 |
| 09:47 | NFLX | laggards | down | -0.26 | -0.59 | -0.61 |
| 09:49 | LAD | leaders | up | -0.19 | +0.18 | — |
| 09:50 | RIVN | leaders | up | +0.70 | +0.38 | -1.68 |
| 09:50 | CIFR | laggards | down | -1.67 | -2.25 | -1.98 |
| 09:51 | RIOT | laggards | down | -0.32 | -0.37 | +0.86 |
| 09:54 | MARA | laggards | down | -2.32 | -2.02 | -1.55 |
| 09:57 | HPQ | leaders | up | -0.66 | -0.34 | -0.09 |
| 09:57 | WULF | laggards | down | -0.27 | -1.55 | -1.52 |
| 10:08 | LULU | leaders | up | +0.62 | +1.16 | +0.69 |
| 10:14 | MDB | laggards | down | -1.87 | -0.98 | -2.26 |
| 10:15 | NVDA | leaders | up | -0.44 | -0.29 | +0.44 |
| 10:17 | AN | leaders | up | +1.51 | +1.41 | +0.81 |
| 10:22 | NKE | leaders | up | +0.94 | +1.46 | +0.96 |
| 10:28 | ZS | laggards | down | -0.43 | -0.83 | -1.05 |
| 10:32 | DDOG | laggards | down | +0.00 | -0.43 | +0.04 |
| 10:32 | CRWD | laggards | down | -0.67 | -1.07 | -1.75 |
| 10:33 | TGT | leaders | up | +0.14 | +0.07 | +0.05 |
| 10:38 | F | leaders | up | +0.29 | +0.35 | +0.13 |
| 10:49 | ONON | leaders | up | +1.13 | +1.82 | +1.23 |
| 10:55 | UAA | leaders | up | +0.52 | +0.69 | +0.10 |
| 11:05 | QBTS | laggards | down | +0.88 | +0.46 | +1.43 |
| 11:07 | GM | leaders | up | -0.50 | -0.28 | -0.21 |
| 11:15 | STX | leaders | up | -0.66 | +0.40 | +0.67 |
| 11:28 | SNDK | leaders | up | -2.07 | -0.50 | +1.17 |
| 11:41 | CVS | leaders | up | -0.92 | -1.03 | -1.19 |
| 12:35 | PANW | laggards | down | +0.26 | +0.62 | +0.04 |
| 12:39 | AI | leaders | up | -0.35 | -1.72 | -2.59 |
| 12:49 | NBIS | leaders | up | -0.97 | -0.53 | -0.52 |
| 12:52 | FTNT | laggards | down | -0.23 | +0.06 | -0.37 |
| 14:03 | QUBT | laggards | down | -0.26 | -1.09 | — |
| 14:49 | LCID | laggards | down | +1.19 | +0.55 | — |
| 15:49 | RCAT | laggards | down | — | — | — |

## 2026-07-13

Usable symbol-minutes 64,766/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | APP | -11.88 | 10:09 | 09:32 |
| 2 | SNDK | -11.86 | miss | 09:31 |
| 3 | ALAB | -11.56 | miss | 09:31 |
| 4 | IONQ | -8.52 | miss | 09:32 |
| 5 | CIFR | -8.39 | miss | 11:05 |
| 6 | CRDO | -7.35 | miss | 09:33 |
| 7 | ASTS | -7.06 | miss | 09:43 |
| 8 | MRVL | -6.99 | miss | 09:31 |
| 9 | QUBT | -6.86 | miss | 10:32 |
| 10 | ARM | -6.78 | miss | 09:31 |
| 11 | APLD | -6.65 | miss | 12:04 |
| 12 | RGTI | -6.37 | miss | 10:37 |
| 13 | QBTS | -6.35 | miss | 09:33 |
| 14 | AAOI | -5.94 | 10:04 | 09:39 |
| 15 | ORCL | -5.70 | miss | miss |
| 16 | HSAI | -5.61 | miss | 10:12 |
| 17 | CRM | +5.60 | miss | 09:31 |
| 18 | CRWV | -5.50 | miss | 09:31 |
| 19 | OKLO | -5.46 | miss | 11:33 |
| 20 | FLNC | -5.42 | miss | 10:06 |

### Radar flags (7)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | Quantum computing (QBTS, IONQ, RGTI, QUBT) | group_move | down | +0.89 | +0.76 | -0.62 |
| 10:04 | AAOI | relative_to_spy | down | +3.32 | +3.28 | +1.95 |
| 10:07 | Bitcoin treasuries and miners (MARA, RIOT, IREN, CLSK, MSTR, COIN) | group_move | down | +1.11 | +0.96 | -0.46 |
| 10:07 | Neoclouds and AI hosting (CIFR, IREN, WULF, APLD, ORCL, NBIS, CRWV) | group_move | down | +1.24 | +0.61 | -1.30 |
| 10:09 | APP | relative_to_spy | down | -0.21 | -0.77 | -3.15 |
| 10:27 | Memory and storage (SNDK, WDC, STX, MU) | group_move | up | -0.11 | +0.70 | -1.66 |
| 10:36 | Cybersecurity (NET, FTNT, PANW, S, CRWD, ZS) | group_move | up | +0.10 | +0.69 | +0.58 |

### Movers flags (59)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | DECK | leaders | up | +0.50 | +0.16 | -0.03 |
| 09:31 | NOW | leaders | up | -2.09 | -1.16 | +1.44 |
| 09:31 | IBM | leaders | up | -1.84 | -0.56 | -0.58 |
| 09:31 | OXY | leaders | up | -0.78 | -0.79 | -0.47 |
| 09:31 | NFLX | leaders | up | +0.08 | -0.18 | -0.31 |
| 09:31 | COP | leaders | up | +0.14 | +0.07 | +0.33 |
| 09:31 | LAD | leaders | up | +0.73 | +0.87 | +0.97 |
| 09:31 | CRM | leaders | up | +0.10 | +0.49 | +3.02 |
| 09:31 | ADBE | leaders | up | -0.66 | -0.69 | +1.00 |
| 09:31 | SPOT | leaders | up | -0.91 | -0.93 | -1.51 |
| 09:31 | SNDK | laggards | down | -2.28 | -0.51 | -1.72 |
| 09:31 | WDC | laggards | down | -0.70 | +1.09 | +1.76 |
| 09:31 | MU | laggards | down | +0.28 | +1.76 | +1.70 |
| 09:31 | STX | laggards | down | -0.41 | +1.26 | +1.51 |
| 09:31 | ARM | laggards | down | -3.15 | -1.18 | +0.08 |
| 09:31 | INTC | laggards | down | +0.61 | +1.08 | +0.33 |
| 09:31 | MRVL | laggards | down | -2.81 | -1.62 | -1.05 |
| 09:31 | ALAB | laggards | down | -4.32 | -4.16 | -4.61 |
| 09:31 | CRCL | laggards | down | -0.41 | +1.58 | +1.02 |
| 09:31 | CRWV | laggards | down | -0.60 | +2.74 | +1.12 |
| 09:32 | PL | leaders | up | -0.22 | -0.30 | -0.74 |
| 09:32 | JD | leaders | up | +0.84 | +0.58 | +0.71 |
| 09:32 | MDB | leaders | up | -3.16 | -1.48 | +0.15 |
| 09:32 | IONQ | laggards | down | -2.07 | -1.21 | -2.15 |
| 09:32 | APP | laggards | down | -4.14 | -4.81 | -5.21 |
| 09:33 | HUM | leaders | up | -0.16 | +1.17 | +1.89 |
| 09:33 | PYPL | leaders | up | -1.02 | -1.41 | -0.49 |
| 09:33 | QBTS | laggards | down | -1.06 | +0.01 | -0.66 |
| 09:33 | CRDO | laggards | down | -1.96 | +0.45 | +0.86 |
| 09:34 | KMX | leaders | up | -0.06 | +0.55 | +1.31 |
| 09:34 | HPQ | leaders | up | -1.88 | -1.83 | -1.24 |
| 09:34 | CI | leaders | up | +0.97 | +0.41 | +1.09 |
| 09:35 | XOM | leaders | up | +0.60 | +0.47 | +0.84 |
| 09:35 | CVX | leaders | up | -0.17 | -0.31 | -0.10 |
| 09:35 | LYFT | leaders | up | -0.67 | -0.52 | -1.11 |
| 09:36 | RBLX | leaders | up | -0.66 | -0.91 | +0.69 |
| 09:37 | AMD | laggards | down | -0.09 | +2.42 | +2.98 |
| 09:39 | RDDT | leaders | up | +0.64 | +1.56 | +1.45 |
| 09:39 | AAOI | laggards | down | -3.42 | -0.78 | -0.71 |
| 09:43 | ASTS | laggards | down | +1.59 | +2.76 | +0.85 |
| 09:44 | CVNA | leaders | up | -0.81 | -1.95 | -2.21 |
| 09:50 | AAPL | leaders | up | -0.77 | -1.04 | -1.71 |
| 09:54 | PFE | leaders | up | -0.58 | -0.50 | -0.66 |
| 09:59 | UAA | leaders | up | +0.21 | -0.16 | -0.88 |
| 10:02 | ELV | leaders | up | -0.28 | -0.25 | +0.02 |
| 10:06 | FLNC | laggards | down | +2.24 | +1.39 | +1.39 |
| 10:12 | HSAI | laggards | down | +1.03 | — | +0.26 |
| 10:25 | SNOW | leaders | up | +0.77 | +1.53 | +1.97 |
| 10:31 | S | leaders | up | +0.54 | +1.61 | +1.16 |
| 10:32 | QUBT | laggards | down | +0.54 | +0.18 | -1.67 |
| 10:37 | RGTI | laggards | down | +0.28 | +0.12 | -1.77 |
| 10:39 | NET | leaders | up | -0.35 | -0.60 | -1.22 |
| 11:01 | AI | leaders | up | +0.01 | -0.72 | -0.72 |
| 11:05 | CIFR | laggards | down | -0.67 | -1.94 | -4.07 |
| 11:26 | WULF | laggards | down | -0.37 | -1.54 | -1.33 |
| 11:33 | OKLO | laggards | down | -0.85 | -2.29 | -2.31 |
| 12:04 | APLD | laggards | down | -1.19 | -0.58 | -1.25 |
| 12:15 | WBD | leaders | up | -1.16 | -0.62 | -0.43 |
| 15:18 | TDOC | leaders | up | +0.41 | — | — |

## 2026-07-14

Usable symbol-minutes 64,555/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | IBM | -25.56 | miss | 09:31 |
| 2 | LCID | -16.51 | 12:51 | 12:49 |
| 3 | CRWD | +11.79 | 10:02 | 09:36 |
| 4 | AAOI | +11.77 | miss | 09:31 |
| 5 | GS | +8.64 | miss | 09:32 |
| 6 | CLSK | +8.46 | 10:39 | 09:31 |
| 7 | NBIS | -8.16 | 10:05 | 10:06 |
| 8 | CVNA | +7.94 | miss | 12:14 |
| 9 | WULF | -7.44 | 10:21 | 09:32 |
| 10 | S | +7.03 | miss | 10:10 |
| 11 | ZS | +6.89 | 10:02 | 09:47 |
| 12 | DELL | +6.77 | miss | 09:32 |
| 13 | PANW | +6.48 | miss | 09:45 |
| 14 | ARM | -6.32 | miss | 09:34 |
| 15 | NOW | -6.12 | miss | 09:31 |
| 16 | C | -5.64 | 11:35 | 11:33 |
| 17 | MSTR | +5.59 | miss | 10:15 |
| 18 | SNDK | +4.65 | miss | 09:31 |
| 19 | ADBE | -4.62 | miss | 09:31 |
| 20 | MU | +4.57 | miss | 09:31 |

### Radar flags (23)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | CLSK | relative_to_spy | down | -0.23 | +2.73 | +2.42 |
| 10:02 | CRWD | relative_to_spy | up | +0.22 | +1.41 | +0.80 |
| 10:02 | DDOG | relative_to_spy | up | -0.53 | -0.15 | -1.23 |
| 10:02 | MDB | relative_to_spy | up | +1.07 | +3.47 | +2.05 |
| 10:02 | PLTR | relative_to_spy | up | +1.04 | +2.12 | +0.76 |
| 10:02 | ZS | relative_to_spy | up | +1.99 | +3.79 | +3.10 |
| 10:02 | AI software and analytics (DDOG, PLTR, SNOW, AI, APP, NOW) | group_move | up | +0.23 | +0.63 | -0.27 |
| 10:02 | Big banks (WFC, JPM, GS, MS, C, BAC) | group_move | up | +0.25 | -0.20 | -1.53 |
| 10:02 | Cybersecurity (CRWD, ZS, NET, PANW, S, FTNT) | group_move | up | +0.63 | +1.55 | +1.58 |
| 10:02 | Neoclouds and AI hosting (NBIS, CIFR, WULF, APLD, IREN, CRWV, ORCL) | group_move | down | -2.53 | -1.28 | -1.61 |
| 10:05 | NBIS | relative_to_spy | down | -2.00 | -2.65 | -2.50 |
| 10:08 | Memory and storage (STX, SNDK, WDC, MU) | group_move | down | +0.24 | -0.12 | +0.36 |
| 10:09 | Bitcoin treasuries and miners (CLSK, RIOT, IREN, MARA) | group_move | down | +2.42 | +2.12 | +2.55 |
| 10:13 | Quantum computing (IONQ, RGTI, QBTS, QUBT) | group_move | down | +0.41 | +0.13 | +0.82 |
| 10:20 | AI networking and connectivity (ALAB, MRVL, COHR, CRDO) | group_move | down | -0.56 | +1.44 | -0.05 |
| 10:21 | WULF | relative_to_spy | down | +3.15 | +5.66 | +3.88 |
| 10:26 | CIFR | relative_to_spy | down | +3.46 | +5.04 | +4.20 |
| 10:31 | Space (LUNR, RKLB, PL, ASTS, IRDM) | group_move | down | +0.17 | +0.49 | +0.45 |
| 10:39 | CLSK | relative_to_spy | up | -0.47 | +0.36 | -2.97 |
| 11:35 | C | relative_to_spy | down | -0.08 | -0.10 | -1.61 |
| 12:51 | LCID | relative_to_spy | down | — | — | -12.33 |
| 13:57 | Bitcoin treasuries and miners (CLSK, IREN, MARA, RIOT, MSTR, COIN) | group_move | up | +0.42 | +0.18 | +0.33 |
| 15:12 | LCID | relative_to_spy | up | +0.05 | — | — |

### Movers flags (56)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | CLSK | leaders | up | -9.15 | -8.78 | -5.72 |
| 09:31 | AAOI | leaders | up | +0.60 | -0.85 | +3.52 |
| 09:31 | SNDK | leaders | up | -1.06 | -2.76 | -1.63 |
| 09:31 | AMD | leaders | up | -2.34 | -3.40 | -0.70 |
| 09:31 | ALAB | leaders | up | +0.03 | -4.15 | -2.29 |
| 09:31 | RIOT | leaders | up | -4.25 | -5.92 | -4.79 |
| 09:31 | CRDO | leaders | up | -2.07 | -4.49 | -2.21 |
| 09:31 | MU | leaders | up | -1.43 | -2.36 | -0.71 |
| 09:31 | MRVL | leaders | up | -1.62 | -3.15 | -1.21 |
| 09:31 | NBIS | leaders | up | -4.08 | -8.57 | -8.38 |
| 09:31 | IBM | laggards | down | -0.64 | -2.34 | -4.39 |
| 09:31 | NOW | laggards | down | +2.19 | +2.44 | +2.09 |
| 09:31 | MDB | laggards | down | +4.93 | +6.34 | +6.97 |
| 09:31 | CRM | laggards | down | +2.33 | +2.92 | +3.23 |
| 09:31 | PLTR | laggards | down | +5.21 | +6.24 | +6.12 |
| 09:31 | ADBE | laggards | down | +0.45 | +0.33 | -0.24 |
| 09:31 | WFC | laggards | down | +3.77 | +3.74 | +2.14 |
| 09:31 | AI | laggards | down | +2.98 | +2.14 | +2.09 |
| 09:31 | MSFT | laggards | down | +1.12 | +1.13 | +1.14 |
| 09:31 | U | laggards | down | +5.40 | +5.42 | +4.93 |
| 09:32 | DELL | leaders | up | -0.41 | -0.92 | +1.42 |
| 09:32 | GS | leaders | up | +2.33 | +3.07 | +2.21 |
| 09:32 | BIDU | laggards | down | -2.95 | -2.45 | -2.32 |
| 09:32 | WULF | laggards | down | -3.55 | -6.51 | -2.52 |
| 09:33 | WDC | leaders | up | -1.80 | -2.68 | -2.64 |
| 09:33 | STX | leaders | up | -1.56 | -2.66 | -1.98 |
| 09:34 | ARM | laggards | down | -0.45 | -0.30 | -0.22 |
| 09:35 | CRCL | laggards | down | -0.53 | +0.11 | +2.92 |
| 09:36 | CRWD | leaders | up | +2.99 | +3.82 | +4.83 |
| 09:37 | RKLB | leaders | up | +0.19 | -0.75 | -0.33 |
| 09:38 | FLNC | leaders | up | -3.06 | -2.41 | -1.77 |
| 09:40 | TDOC | laggards | down | -1.57 | -2.01 | -2.11 |
| 09:42 | RCAT | leaders | up | -1.70 | -1.26 | -1.59 |
| 09:42 | ASTS | leaders | up | -1.08 | -1.51 | -1.29 |
| 09:44 | LLY | laggards | down | +0.00 | -0.13 | +0.15 |
| 09:45 | PANW | leaders | up | +0.62 | +0.54 | +1.61 |
| 09:47 | ZS | leaders | up | +1.32 | +2.95 | +3.79 |
| 10:05 | APLD | laggards | down | +0.79 | +0.72 | +1.52 |
| 10:06 | MS | leaders | up | +0.06 | -0.61 | -1.17 |
| 10:06 | NBIS | laggards | down | +0.14 | -1.14 | -0.96 |
| 10:06 | CIFR | laggards | down | +1.61 | +2.89 | +4.85 |
| 10:10 | S | leaders | up | +1.32 | +1.88 | +3.14 |
| 10:15 | MSTR | leaders | up | +0.34 | -0.13 | +0.33 |
| 10:17 | LULU | laggards | down | -0.03 | -0.04 | +1.09 |
| 10:31 | NET | leaders | up | +0.33 | -0.54 | +1.09 |
| 10:55 | MRK | laggards | down | -0.07 | +0.45 | -0.30 |
| 11:02 | UAA | laggards | down | -0.22 | +0.23 | -0.07 |
| 11:33 | C | laggards | down | -0.56 | -0.64 | -2.25 |
| 11:44 | CRWV | laggards | down | -1.25 | -1.28 | -2.37 |
| 12:14 | CVNA | leaders | up | +0.29 | +0.47 | +1.30 |
| 12:24 | QCOM | laggards | down | -0.37 | -0.05 | +0.52 |
| 12:49 | LCID | laggards | down | — | -44.12 | -11.43 |
| 12:55 | IREN | laggards | down | -0.80 | +2.09 | +1.99 |
| 13:18 | MARA | laggards | down | +2.12 | +4.21 | +3.20 |
| 14:39 | RGTI | leaders | up | -0.02 | -0.48 | — |
| 14:53 | BULL | leaders | up | -1.11 | -2.47 | — |

## 2026-07-15

Usable symbol-minutes 64,805/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | LCID | +28.39 | 10:02 | 09:32 |
| 2 | PYPL | +16.81 | miss | 09:31 |
| 3 | AAOI | -13.44 | miss | 09:32 |
| 4 | DELL | -10.20 | 10:28 | 09:42 |
| 5 | WDC | -9.18 | miss | 09:36 |
| 6 | ELV | -8.94 | miss | 09:31 |
| 7 | SNDK | -8.52 | 10:25 | 09:31 |
| 8 | MU | -8.42 | miss | 09:31 |
| 9 | MRVL | -7.67 | miss | 09:31 |
| 10 | CIEN | -6.77 | miss | 09:33 |
| 11 | RCAT | -6.65 | miss | 15:18 |
| 12 | ANET | -6.23 | miss | 09:55 |
| 13 | STX | -6.09 | miss | 09:38 |
| 14 | RGTI | -5.73 | miss | 09:46 |
| 15 | KMX | +5.36 | miss | 09:37 |
| 16 | HIMS | +5.35 | miss | 09:32 |
| 17 | IONQ | -4.93 | miss | miss |
| 18 | INTC | -4.82 | miss | 14:03 |
| 19 | CLSK | +4.66 | 13:11 | 09:31 |
| 20 | TDOC | +4.46 | miss | 11:28 |

### Radar flags (23)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | LCID | relative_to_spy | up | +0.97 | +4.06 | +4.94 |
| 10:02 | RDDT | relative_to_spy | down | +0.93 | +1.25 | +3.97 |
| 10:02 | Crypto and exchanges (MSTR, COIN, BULL, HOOD, MARA, CRCL, RIOT) | group_move | down | -0.31 | +0.23 | -0.16 |
| 10:02 | Memory and storage (STX, WDC, SNDK, MU) | group_move | down | -4.12 | -4.35 | -5.27 |
| 10:02 | Retail brokers and fintech (SOFI, COIN, BULL, HOOD, SCHW) | group_move | down | +0.08 | +0.62 | +1.11 |
| 10:02 | Space (ASTS, PL, RKLB, LUNR, IRDM) | group_move | down | -0.26 | -0.46 | -1.54 |
| 10:04 | Bitcoin treasuries and miners (CLSK, MSTR, COIN, MARA, RIOT) | group_move | down | -0.11 | -0.86 | -2.16 |
| 10:04 | Quantum computing (RGTI, IONQ, QBTS, QUBT) | group_move | down | -1.06 | -1.79 | -3.45 |
| 10:05 | Managed care (ELV, CI, CNC, CVS, UNH) | group_move | up | -0.03 | +0.37 | +1.36 |
| 10:11 | CLSK | relative_to_spy | down | -1.34 | -1.13 | -3.86 |
| 10:25 | SNDK | relative_to_spy | down | -1.76 | -2.22 | -4.76 |
| 10:28 | DELL | relative_to_spy | down | -4.20 | -4.71 | -6.39 |
| 10:31 | ALAB | relative_to_spy | down | +1.49 | +1.94 | +0.01 |
| 10:31 | AI networking and connectivity (ALAB, CRDO, MRVL, ANET, AVGO, COHR) | group_move | down | -0.09 | -0.60 | -2.29 |
| 10:39 | CRDO | relative_to_spy | down | +1.61 | +1.12 | -0.59 |
| 10:39 | GPUs and AI compute chips (AMD, ARM, INTC, MRVL, AVGO, TSM, QCOM, NVDA) | group_move | down | +0.62 | +0.13 | -1.22 |
| 10:41 | AMD | relative_to_spy | down | +0.47 | +0.21 | -1.10 |
| 12:52 | Neoclouds and AI hosting (NBIS, CIFR, APLD, IREN, WULF, CRWV, ORCL) | group_move | up | +1.78 | +1.75 | +1.59 |
| 13:04 | Bitcoin treasuries and miners (CLSK, IREN, MARA, RIOT, COIN, MSTR) | group_move | up | +0.47 | +0.55 | -0.36 |
| 13:11 | CLSK | relative_to_spy | up | -1.14 | +0.32 | -0.73 |
| 13:11 | Crypto and exchanges (MARA, RIOT, COIN, CRCL, MSTR, HOOD, BULL) | group_move | up | +0.23 | +0.24 | -0.01 |
| 15:01 | Bitcoin treasuries and miners (IREN, CLSK, RIOT, MARA, MSTR, COIN) | group_move | down | +0.37 | — | — |
| 15:01 | Neoclouds and AI hosting (CIFR, IREN, WULF, APLD, CRWV, NBIS, ORCL) | group_move | down | +0.67 | — | — |

### Movers flags (60)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | PYPL | leaders | up | +0.37 | +1.53 | +0.89 |
| 09:31 | CLSK | leaders | up | -1.14 | -5.01 | -6.05 |
| 09:31 | BABA | leaders | up | +3.15 | +2.11 | +1.33 |
| 09:31 | RBLX | leaders | up | -0.92 | -0.06 | +0.06 |
| 09:31 | COIN | leaders | up | -2.70 | -2.15 | -1.60 |
| 09:31 | CRCL | leaders | up | +0.67 | +0.53 | -0.50 |
| 09:31 | MSTR | leaders | up | -2.53 | -1.83 | -2.24 |
| 09:31 | PL | leaders | up | -2.69 | -3.25 | -3.95 |
| 09:31 | NET | leaders | up | -2.19 | -3.06 | -5.36 |
| 09:31 | BULL | leaders | up | -2.73 | -3.56 | -1.64 |
| 09:31 | ELV | laggards | down | +1.85 | +0.16 | +1.77 |
| 09:31 | CNC | laggards | down | +0.22 | -0.28 | +1.44 |
| 09:31 | SNDK | laggards | down | -2.62 | -7.26 | -8.69 |
| 09:31 | MS | laggards | down | +3.11 | +4.18 | +2.39 |
| 09:31 | UNH | laggards | down | +1.18 | +1.11 | +2.06 |
| 09:31 | MU | laggards | down | -0.84 | -4.12 | -5.58 |
| 09:31 | CI | laggards | down | +0.33 | +1.19 | +1.85 |
| 09:31 | V | laggards | down | +0.78 | +1.66 | +1.86 |
| 09:31 | MRVL | laggards | down | -1.30 | -4.37 | -4.49 |
| 09:31 | HUM | laggards | down | — | +0.20 | +2.10 |
| 09:32 | LCID | leaders | up | +7.36 | +8.40 | +12.07 |
| 09:32 | HIMS | leaders | up | +2.19 | +0.80 | +1.94 |
| 09:32 | MRK | leaders | up | +0.11 | -0.48 | -0.33 |
| 09:32 | AAOI | laggards | down | -4.15 | -7.78 | -9.27 |
| 09:32 | CVS | laggards | down | +1.24 | +1.70 | +2.84 |
| 09:33 | FLNC | leaders | up | -2.44 | -6.07 | -5.97 |
| 09:33 | RIVN | leaders | up | +3.28 | +2.15 | +1.44 |
| 09:33 | CIEN | laggards | down | -2.17 | -3.32 | -4.51 |
| 09:34 | SNAP | leaders | up | -0.10 | -0.68 | -0.03 |
| 09:34 | NBIS | leaders | up | +0.21 | -1.06 | -3.00 |
| 09:36 | ORCL | leaders | up | -0.81 | +0.12 | -0.90 |
| 09:36 | WDC | laggards | down | -3.08 | -6.03 | -6.14 |
| 09:37 | KMX | leaders | up | +2.13 | +2.91 | +2.76 |
| 09:38 | S | leaders | up | -1.11 | -0.46 | -1.96 |
| 09:38 | STX | laggards | down | -1.64 | -6.17 | -5.29 |
| 09:40 | RDDT | laggards | down | -0.92 | +0.27 | +2.42 |
| 09:42 | JD | leaders | up | +0.27 | -0.10 | -0.34 |
| 09:42 | DELL | laggards | down | -0.59 | -9.74 | -9.16 |
| 09:46 | BIDU | leaders | up | +0.74 | +0.06 | -0.01 |
| 09:46 | RGTI | laggards | down | -0.67 | -1.54 | -2.77 |
| 09:47 | COHR | laggards | down | -0.57 | -1.57 | -3.74 |
| 09:51 | AI | leaders | up | +0.29 | +0.29 | -0.46 |
| 09:53 | UAA | leaders | up | +1.99 | +2.99 | +4.04 |
| 09:55 | PDD | leaders | up | -0.53 | -0.17 | +0.15 |
| 09:55 | ANET | laggards | down | -1.18 | -1.69 | -4.00 |
| 10:06 | ADBE | leaders | up | +0.05 | -0.73 | -1.01 |
| 10:14 | ALAB | laggards | down | -2.64 | -0.66 | -2.35 |
| 10:15 | TGT | leaders | up | +0.25 | +0.60 | +0.58 |
| 10:16 | CRDO | laggards | down | -2.10 | -2.25 | -3.16 |
| 10:20 | LAD | leaders | up | — | -0.05 | +0.60 |
| 10:24 | NOW | leaders | up | -2.04 | -1.82 | -2.61 |
| 11:17 | NVO | leaders | up | +0.05 | +0.16 | -0.67 |
| 11:28 | TDOC | leaders | up | +0.62 | +0.65 | +1.32 |
| 11:39 | AAPL | leaders | up | +0.23 | +0.73 | +0.27 |
| 11:45 | LYFT | leaders | up | +0.78 | +1.01 | -0.18 |
| 12:52 | AN | leaders | up | — | — | — |
| 13:19 | IREN | leaders | up | -1.62 | -1.09 | -4.22 |
| 14:03 | INTC | laggards | down | -0.20 | -0.33 | — |
| 15:02 | PINS | leaders | up | -0.24 | — | — |
| 15:18 | RCAT | laggards | down | +0.67 | — | — |

## 2026-07-16

Usable symbol-minutes 64,897/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | ASTS | -16.50 | 10:06 | 09:31 |
| 2 | NBIS | -13.36 | miss | 09:31 |
| 3 | SNDK | -12.08 | miss | 09:31 |
| 4 | RKLB | -11.07 | miss | 09:32 |
| 5 | PL | -10.74 | miss | 09:32 |
| 6 | CIFR | -10.28 | miss | 09:31 |
| 7 | STX | -9.46 | miss | 09:32 |
| 8 | LCID | +9.11 | 10:02 | 09:51 |
| 9 | LUNR | -8.95 | miss | 09:31 |
| 10 | HIMS | -8.85 | 10:02 | 15:58 |
| 11 | WDC | -8.61 | miss | 09:33 |
| 12 | IREN | -8.47 | miss | 10:16 |
| 13 | APLD | -8.38 | miss | 09:31 |
| 14 | ALAB | -8.27 | miss | 09:35 |
| 15 | OKLO | -8.19 | miss | 09:33 |
| 16 | MRVL | -8.17 | miss | 09:36 |
| 17 | CLSK | -8.16 | miss | miss |
| 18 | CRDO | -7.74 | miss | 10:31 |
| 19 | HOOD | -7.70 | miss | miss |
| 20 | SMCI | -7.68 | miss | miss |

### Radar flags (11)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | LCID | relative_to_spy | up | +3.14 | +8.39 | +6.98 |
| 10:02 | ELV | relative_to_sector | down | -1.20 | -0.09 | -0.09 |
| 10:02 | HIMS | relative_to_sector | down | +0.41 | -0.41 | -4.05 |
| 10:02 | HUM | relative_to_sector | down | -1.40 | -2.01 | -4.06 |
| 10:04 | Bitcoin treasuries and miners (MARA, CLSK, RIOT, IREN, COIN, MSTR) | group_move | down | +1.23 | +0.00 | -0.82 |
| 10:05 | Neoclouds and AI hosting (IREN, CIFR, NBIS, APLD, WULF, CRWV, ORCL) | group_move | down | +0.03 | -0.79 | -2.83 |
| 10:05 | Space (ASTS, RKLB, LUNR, IRDM, PL) | group_move | down | -0.35 | — | -3.22 |
| 10:06 | ASTS | relative_to_spy | down | -0.50 | -2.37 | -4.00 |
| 10:07 | Rideshare and delivery (LYFT, UBER, DASH) | group_move | down | +0.88 | +0.83 | +0.04 |
| 10:19 | Memory and storage (SNDK, STX, WDC, MU) | group_move | up | -0.71 | -2.78 | -4.29 |
| 13:15 | LCID | relative_to_spy | down | -1.41 | -2.20 | +2.95 |

### Movers flags (63)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | UNH | leaders | up | -0.20 | -3.79 | -4.53 |
| 09:31 | HUM | leaders | up | -3.88 | -5.06 | -6.94 |
| 09:31 | BIDU | leaders | up | -0.33 | -0.62 | -0.87 |
| 09:31 | JD | leaders | up | -0.10 | -0.39 | -0.22 |
| 09:31 | CNC | leaders | up | -1.49 | -2.46 | -3.23 |
| 09:31 | ZS | leaders | up | -3.10 | -2.55 | -3.01 |
| 09:31 | SONY | leaders | up | +0.55 | +0.59 | +0.66 |
| 09:31 | LYFT | leaders | up | -3.81 | -2.60 | -2.93 |
| 09:31 | PDD | leaders | up | +0.12 | +0.05 | -0.24 |
| 09:31 | UBER | leaders | up | -0.30 | -0.46 | -0.41 |
| 09:31 | ASTS | laggards | down | -3.90 | -4.18 | -6.09 |
| 09:31 | AAOI | laggards | down | +1.14 | -0.06 | -2.33 |
| 09:31 | ARM | laggards | down | -0.81 | -1.33 | -2.10 |
| 09:31 | CIFR | laggards | down | -1.55 | -1.68 | -3.18 |
| 09:31 | NBIS | laggards | down | -0.64 | -1.05 | -5.60 |
| 09:31 | SNDK | laggards | down | -1.33 | -2.68 | -4.79 |
| 09:31 | COHR | laggards | down | +0.82 | -0.60 | -2.54 |
| 09:31 | WULF | laggards | down | -0.66 | +0.18 | -0.97 |
| 09:31 | LUNR | laggards | down | -2.97 | -0.99 | -2.98 |
| 09:31 | APLD | laggards | down | -1.06 | -1.04 | -3.21 |
| 09:32 | CVS | leaders | up | -0.85 | -2.18 | -1.36 |
| 09:32 | BABA | leaders | up | -0.65 | -0.89 | -1.01 |
| 09:32 | PL | laggards | down | -0.42 | -1.90 | -3.46 |
| 09:32 | LCID | laggards | down | +11.74 | +15.27 | +19.35 |
| 09:32 | RKLB | laggards | down | -3.85 | -4.77 | -5.89 |
| 09:32 | STX | laggards | down | -1.97 | -1.06 | -2.89 |
| 09:32 | CRCL | laggards | down | +0.67 | +0.15 | -0.57 |
| 09:32 | RCAT | laggards | down | -0.38 | -1.16 | -0.71 |
| 09:33 | BULL | leaders | up | -2.41 | -2.91 | -2.28 |
| 09:33 | TGT | leaders | up | -0.33 | -0.67 | -0.08 |
| 09:33 | DASH | leaders | up | -2.24 | — | -2.93 |
| 09:33 | CPRT | leaders | up | +0.35 | -0.19 | +0.35 |
| 09:33 | WDC | laggards | down | -1.26 | -1.19 | -3.26 |
| 09:33 | OKLO | laggards | down | -1.90 | -2.28 | -3.49 |
| 09:34 | KMX | leaders | up | +0.73 | +0.42 | +0.14 |
| 09:35 | ALAB | laggards | down | -2.07 | -2.06 | -3.00 |
| 09:36 | FND | leaders | up | +0.52 | +0.98 | +1.20 |
| 09:36 | UAA | leaders | up | +0.58 | +1.77 | +3.36 |
| 09:36 | MRVL | laggards | down | -1.09 | -1.85 | -2.91 |
| 09:37 | LAD | leaders | up | — | — | +0.97 |
| 09:38 | DECK | leaders | up | +0.46 | +0.47 | +0.25 |
| 09:39 | COST | leaders | up | -0.57 | -1.02 | -0.45 |
| 09:39 | MRK | leaders | up | +0.35 | +0.26 | +0.94 |
| 09:40 | HD | leaders | up | -0.67 | -0.96 | -0.43 |
| 09:42 | LOW | leaders | up | -0.66 | -0.16 | +0.44 |
| 09:43 | WMT | leaders | up | -0.95 | -1.02 | -0.65 |
| 09:46 | AMGN | leaders | up | -0.41 | +0.02 | +0.52 |
| 09:51 | LCID | leaders | up | +4.62 | +8.50 | +8.88 |
| 09:53 | NKE | leaders | up | +0.69 | +0.52 | +0.86 |
| 10:01 | AN | leaders | up | +0.15 | +0.31 | +0.23 |
| 10:04 | RIOT | laggards | down | +2.00 | -0.12 | -1.52 |
| 10:10 | CI | laggards | down | -0.26 | +0.91 | +1.02 |
| 10:11 | NOW | laggards | down | +0.69 | +1.67 | +3.82 |
| 10:12 | CVNA | leaders | up | -0.11 | -2.14 | -2.86 |
| 10:16 | IREN | laggards | down | -1.47 | -2.04 | -3.31 |
| 10:18 | ONON | leaders | up | +0.48 | +0.50 | -0.14 |
| 10:31 | CRDO | laggards | down | -1.29 | -2.49 | -3.19 |
| 11:15 | PYPL | leaders | up | -0.07 | +0.11 | +0.89 |
| 12:00 | URI | leaders | up | -0.26 | — | — |
| 12:09 | CRM | leaders | up | +0.44 | +0.80 | +1.46 |
| 12:32 | ADBE | leaders | up | +0.74 | +1.19 | +2.15 |
| 12:52 | IBM | leaders | up | +0.64 | +0.30 | +1.25 |
| 15:58 | HIMS | laggards | down | — | — | — |

## 2026-07-17

Usable symbol-minutes 64,672/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | LCID | +14.92 | miss | 09:31 |
| 2 | STX | +6.65 | 10:16 | 10:46 |
| 3 | NFLX | -6.27 | miss | 09:31 |
| 4 | ASTS | +6.06 | 10:11 | 09:31 |
| 5 | MARA | -5.40 | miss | 09:34 |
| 6 | CNC | +4.98 | miss | 14:10 |
| 7 | HOOD | -4.73 | miss | 09:31 |
| 8 | HUM | +4.49 | miss | 09:36 |
| 9 | NBIS | +4.45 | 10:06 | 10:03 |
| 10 | ALAB | -4.05 | miss | 09:31 |
| 11 | MDB | -3.96 | miss | 12:11 |
| 12 | BIDU | -3.96 | miss | 10:07 |
| 13 | HPQ | +3.89 | miss | 10:17 |
| 14 | CVNA | -3.71 | miss | 14:24 |
| 15 | SHEL | +3.62 | miss | 09:31 |
| 16 | UAA | +3.47 | miss | 09:40 |
| 17 | ZS | +3.39 | miss | 09:32 |
| 18 | RBLX | -3.32 | miss | 12:03 |
| 19 | OXY | +3.25 | miss | 09:31 |
| 20 | WDC | +3.22 | 10:12 | 12:17 |

### Radar flags (36)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:05 | Memory and storage (SNDK, MU, STX, WDC) | group_move | up | +1.28 | +0.75 | +5.46 |
| 10:06 | NBIS | relative_to_spy | up | +1.55 | +0.44 | +3.35 |
| 10:07 | Neoclouds and AI hosting (NBIS, CIFR, WULF, IREN, APLD, CRWV, ORCL) | group_move | up | +0.38 | -0.70 | +1.54 |
| 10:07 | Space (PL, RKLB, ASTS, LUNR, IRDM) | group_move | up | +1.15 | +0.16 | +3.00 |
| 10:08 | LCID | relative_to_spy | down | +0.34 | +0.07 | +4.21 |
| 10:09 | AAOI | relative_to_spy | up | +1.27 | +0.05 | +3.60 |
| 10:09 | ARM | relative_to_spy | up | +0.60 | -0.60 | +2.22 |
| 10:09 | CIFR | relative_to_spy | up | -1.67 | -2.38 | +1.43 |
| 10:09 | SNDK | relative_to_spy | up | +0.48 | -1.80 | +3.60 |
| 10:09 | WULF | relative_to_spy | up | -1.04 | -0.82 | +0.90 |
| 10:09 | Bitcoin treasuries and miners (IREN, RIOT, CLSK, MSTR, COIN, MARA) | group_move | up | -0.35 | -0.79 | +0.37 |
| 10:09 | GPUs and AI compute chips (ARM, AMD, INTC, MRVL, TSM, AVGO, NVDA, QCOM) | group_move | up | +0.07 | -0.84 | +1.00 |
| 10:10 | PL | relative_to_spy | up | +0.12 | -0.87 | +1.96 |
| 10:10 | AI networking and connectivity (COHR, MRVL, ALAB, CRDO, ANET, AVGO) | group_move | up | +0.19 | -1.11 | +1.46 |
| 10:11 | AMD | relative_to_spy | up | -0.42 | -1.44 | +2.09 |
| 10:11 | ASTS | relative_to_spy | up | -0.32 | -2.54 | +3.09 |
| 10:11 | COHR | relative_to_spy | up | +0.15 | -1.29 | +2.14 |
| 10:11 | IREN | relative_to_spy | up | -2.11 | -3.03 | -0.07 |
| 10:11 | LUNR | relative_to_spy | up | -0.30 | -1.82 | +2.14 |
| 10:11 | MU | relative_to_spy | up | +0.51 | -1.93 | +2.05 |
| 10:11 | RKLB | relative_to_spy | up | +0.40 | -1.74 | +1.26 |
| 10:11 | Quantum computing (RGTI, IONQ, QBTS, QUBT) | group_move | up | -0.79 | -1.21 | +2.41 |
| 10:12 | DELL | relative_to_spy | up | +0.68 | -0.14 | +1.01 |
| 10:12 | INTC | relative_to_spy | up | -1.23 | -2.82 | +0.38 |
| 10:12 | WDC | relative_to_spy | up | +0.59 | -1.40 | +3.42 |
| 10:13 | CIEN | relative_to_spy | up | -0.62 | -1.31 | +0.72 |
| 10:13 | MRVL | relative_to_spy | up | -0.87 | -1.81 | +1.84 |
| 10:15 | ANET | relative_to_spy | up | -0.21 | -0.52 | +1.50 |
| 10:15 | Crypto and exchanges (RIOT, HOOD, COIN, MSTR, CRCL, MARA, BULL) | group_move | up | +0.05 | -0.74 | +0.98 |
| 10:16 | STX | relative_to_spy | up | +2.17 | +0.66 | +5.21 |
| 10:17 | FLNC | relative_to_spy | up | -1.12 | -2.53 | +0.31 |
| 10:19 | CRWV | relative_to_spy | up | +2.48 | +0.39 | +0.33 |
| 12:01 | SNDK | relative_to_spy | up | -1.35 | -0.97 | -3.58 |
| 12:03 | Quantum computing (RGTI, IONQ, QBTS, QUBT) | group_move | up | -0.34 | +1.36 | +0.98 |
| 12:12 | Neoclouds and AI hosting (CIFR, WULF, NBIS, APLD, IREN, CRWV, ORCL) | group_move | up | -1.51 | +0.60 | -0.02 |
| 13:10 | Neoclouds and AI hosting (NBIS, APLD, WULF, CIFR, CRWV, IREN, ORCL) | group_move | up | +0.05 | -0.76 | -1.53 |

### Movers flags (74)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | XOM | leaders | up | -1.11 | -1.19 | -1.49 |
| 09:31 | OXY | leaders | up | -0.92 | -1.14 | -1.84 |
| 09:31 | SHEL | leaders | up | -0.06 | -0.62 | -0.56 |
| 09:31 | COP | leaders | up | -0.45 | -1.10 | -1.78 |
| 09:31 | CVX | leaders | up | -0.58 | -0.97 | -1.18 |
| 09:31 | LCID | leaders | up | -0.67 | -1.16 | +3.48 |
| 09:31 | CI | leaders | up | -1.18 | -0.59 | +0.05 |
| 09:31 | COST | leaders | up | -0.77 | -1.65 | -1.84 |
| 09:31 | ASTS | leaders | up | +1.61 | +3.27 | +4.64 |
| 09:31 | WMT | leaders | up | +0.12 | -0.87 | -0.62 |
| 09:31 | NFLX | laggards | down | +1.52 | +2.79 | +3.18 |
| 09:31 | CRDO | laggards | down | +1.78 | +0.52 | +0.49 |
| 09:31 | CIFR | laggards | down | +1.18 | +1.37 | +0.61 |
| 09:31 | ALAB | laggards | down | +0.16 | -0.05 | -1.13 |
| 09:31 | HSAI | laggards | down | -0.30 | -0.55 | — |
| 09:31 | FLNC | laggards | down | +0.51 | +2.76 | +1.49 |
| 09:31 | WDC | laggards | down | +0.46 | +2.55 | +2.63 |
| 09:31 | HOOD | laggards | down | -0.94 | -0.93 | -1.18 |
| 09:31 | TSM | laggards | down | +1.09 | +1.64 | +1.29 |
| 09:31 | ARM | laggards | down | +2.45 | +4.20 | +3.28 |
| 09:32 | ZS | leaders | up | -0.30 | +0.19 | -1.83 |
| 09:32 | PANW | leaders | up | -0.40 | -0.05 | -0.04 |
| 09:32 | CRWD | leaders | up | -1.53 | -0.54 | -1.05 |
| 09:32 | UNH | leaders | up | -0.47 | -1.11 | -0.54 |
| 09:32 | MS | laggards | down | +2.86 | +3.54 | +3.76 |
| 09:32 | WULF | laggards | down | +1.44 | +1.26 | +1.62 |
| 09:33 | MRK | leaders | up | +0.70 | +0.41 | +0.87 |
| 09:33 | APLD | laggards | down | -0.33 | -0.77 | -1.67 |
| 09:33 | AMD | laggards | down | +1.02 | +1.12 | +2.00 |
| 09:34 | AAOI | laggards | down | +3.38 | +5.45 | +5.46 |
| 09:34 | RIOT | laggards | down | +1.13 | +1.64 | +2.86 |
| 09:34 | MARA | laggards | down | -0.18 | -1.77 | -1.53 |
| 09:35 | CPRT | leaders | up | -1.49 | -2.80 | -3.77 |
| 09:35 | NOW | leaders | up | -2.16 | -1.82 | -2.68 |
| 09:36 | HUM | leaders | up | — | -0.24 | +0.38 |
| 09:38 | TGT | leaders | up | -0.73 | -0.97 | -1.49 |
| 09:40 | UAA | leaders | up | +0.37 | +0.31 | -0.35 |
| 09:41 | BULL | laggards | down | +1.22 | +0.82 | -0.51 |
| 09:44 | INTC | laggards | down | +5.10 | +4.38 | +3.79 |
| 09:45 | COHR | laggards | down | +6.32 | +6.70 | +6.97 |
| 09:49 | DE | leaders | up | -1.84 | -2.26 | -2.33 |
| 10:03 | NBIS | leaders | up | +0.95 | +1.20 | +3.88 |
| 10:04 | META | laggards | down | -0.92 | -1.64 | -1.09 |
| 10:07 | BIDU | laggards | down | -0.81 | -1.47 | -1.14 |
| 10:08 | APP | laggards | down | -0.36 | -0.38 | +0.32 |
| 10:11 | SNDK | leaders | up | -1.04 | -3.46 | +2.02 |
| 10:11 | RKLB | leaders | up | +0.40 | -1.74 | +1.26 |
| 10:11 | PL | leaders | up | -0.46 | -1.62 | +1.71 |
| 10:11 | PDD | laggards | down | +0.18 | +0.41 | +0.23 |
| 10:17 | HPQ | leaders | up | -0.06 | -0.06 | +1.28 |
| 10:19 | MU | leaders | up | -0.56 | -1.52 | +1.73 |
| 10:33 | NET | leaders | up | -0.24 | -0.43 | +0.02 |
| 10:46 | STX | leaders | up | -1.48 | -0.31 | +3.19 |
| 10:54 | U | laggards | down | -0.68 | -0.46 | +0.55 |
| 11:00 | CVS | leaders | up | +0.21 | -0.16 | -0.93 |
| 11:38 | SNAP | laggards | down | -0.04 | +0.03 | +2.10 |
| 11:56 | AAOI | leaders | up | -1.04 | -0.15 | +1.08 |
| 11:57 | QUBT | leaders | up | +0.45 | +1.22 | +2.11 |
| 12:01 | LUNR | leaders | up | -1.73 | +0.87 | -0.06 |
| 12:03 | RBLX | laggards | down | +0.90 | +1.22 | +1.18 |
| 12:11 | MDB | laggards | down | -0.24 | +0.56 | +0.42 |
| 12:17 | WDC | leaders | up | -0.13 | +1.65 | +0.23 |
| 12:27 | IREN | laggards | down | +1.82 | +3.07 | +0.82 |
| 12:28 | LYFT | laggards | down | +0.20 | +0.63 | +0.58 |
| 13:02 | CPRT | laggards | down | +0.98 | +1.21 | +1.28 |
| 13:16 | LOW | laggards | down | +0.32 | +0.08 | +0.07 |
| 13:34 | GOOGL | laggards | down | +0.05 | +0.26 | +0.41 |
| 13:39 | IBM | laggards | down | -0.44 | -0.72 | -0.41 |
| 13:58 | ARM | leaders | up | -0.99 | -1.38 | -1.27 |
| 14:10 | CNC | leaders | up | -0.04 | +0.49 | — |
| 14:24 | CVNA | laggards | down | -0.36 | -0.01 | — |
| 14:49 | DELL | leaders | up | -0.70 | -0.33 | — |
| 15:57 | SNDK | laggards | down | — | — | — |
| 15:59 | CIEN | laggards | down | — | — | — |

## 2026-07-20

Usable symbol-minutes 64,597/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | IREN | +19.73 | 10:02 | 09:31 |
| 2 | CIFR | +17.13 | miss | 09:31 |
| 3 | CLSK | +10.83 | miss | 09:31 |
| 4 | MARA | +9.33 | miss | 09:31 |
| 5 | RIOT | +9.14 | miss | 09:38 |
| 6 | CRCL | +8.41 | miss | 10:58 |
| 7 | APLD | +8.15 | miss | 09:31 |
| 8 | BULL | +6.52 | miss | 13:29 |
| 9 | FND | -5.00 | miss | 09:33 |
| 10 | BABA | +4.83 | miss | 11:51 |
| 11 | CRDO | +4.79 | miss | 09:31 |
| 12 | CVNA | -4.59 | miss | 09:34 |
| 13 | WULF | +4.02 | miss | 09:31 |
| 14 | ORCL | -3.82 | miss | 09:31 |
| 15 | MDB | +3.69 | miss | 10:57 |
| 16 | AN | -3.63 | miss | 10:30 |
| 17 | WBD | -3.60 | miss | 13:31 |
| 18 | DELL | -3.49 | miss | 10:11 |
| 19 | MRVL | +3.48 | miss | 11:18 |
| 20 | JD | +3.47 | miss | miss |

### Radar flags (5)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | IREN | relative_to_spy | up | -0.36 | -2.29 | +1.40 |
| 10:02 | Bitcoin treasuries and miners (IREN, RIOT, CLSK, MARA, MSTR) | group_move | up | +0.44 | -0.00 | +2.55 |
| 10:22 | NBIS | relative_to_spy | down | +1.74 | +3.82 | +2.89 |
| 10:59 | LCID | relative_to_spy | down | +1.01 | +1.74 | +1.98 |
| 12:12 | Space (ASTS, LUNR, RKLB, PL, IRDM) | group_move | up | -0.56 | -0.91 | +0.28 |

### Movers flags (59)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | IREN | leaders | up | +6.92 | +6.98 | +7.84 |
| 09:31 | CIFR | leaders | up | +3.80 | +6.21 | +7.21 |
| 09:31 | CLSK | leaders | up | +3.70 | +4.43 | +5.58 |
| 09:31 | APLD | leaders | up | +3.09 | +3.89 | +3.21 |
| 09:31 | NBIS | leaders | up | +0.24 | -1.56 | +1.07 |
| 09:31 | WULF | leaders | up | +1.26 | +1.47 | +1.57 |
| 09:31 | COHR | leaders | up | +2.13 | +1.75 | +1.32 |
| 09:31 | CRDO | leaders | up | +1.89 | +2.56 | +2.66 |
| 09:31 | MARA | leaders | up | +2.43 | +4.89 | +6.45 |
| 09:31 | CRWV | leaders | up | +1.38 | +0.89 | -0.48 |
| 09:31 | RDDT | laggards | down | +3.14 | +3.57 | +6.09 |
| 09:31 | NOW | laggards | down | -1.37 | -0.69 | +1.96 |
| 09:31 | ADBE | laggards | down | -1.44 | -1.55 | -0.34 |
| 09:31 | CRM | laggards | down | +0.86 | +1.32 | +2.43 |
| 09:31 | ORCL | laggards | down | -1.48 | -1.41 | -1.09 |
| 09:31 | S | laggards | down | +2.89 | +1.69 | +2.78 |
| 09:31 | NFLX | laggards | down | -1.21 | -0.13 | +0.33 |
| 09:31 | IBM | laggards | down | +1.19 | +1.05 | +0.97 |
| 09:31 | SHEL | laggards | down | +0.45 | +0.65 | +0.92 |
| 09:31 | ONON | laggards | down | +1.62 | +1.19 | +1.75 |
| 09:32 | ALAB | leaders | up | -1.35 | -0.71 | +0.05 |
| 09:32 | HPQ | laggards | down | -0.25 | -1.21 | -0.68 |
| 09:32 | OXY | laggards | down | +1.51 | +1.68 | +2.05 |
| 09:33 | FND | laggards | down | -1.78 | -2.16 | -2.32 |
| 09:34 | SNDK | leaders | up | -0.48 | -0.86 | -0.20 |
| 09:34 | CVNA | laggards | down | -0.32 | -0.76 | -2.88 |
| 09:34 | NKE | laggards | down | -0.06 | -0.02 | -0.07 |
| 09:36 | LAD | laggards | down | — | +1.66 | +1.93 |
| 09:36 | DECK | laggards | down | +0.75 | +0.04 | -0.17 |
| 09:37 | LYFT | laggards | down | +0.26 | +0.63 | +2.00 |
| 09:38 | RIOT | leaders | up | +1.09 | -1.43 | +1.24 |
| 09:39 | LOW | laggards | down | -0.12 | -0.24 | -0.09 |
| 09:40 | PYPL | laggards | down | +0.80 | +0.55 | +2.46 |
| 09:44 | ASTS | laggards | down | +1.55 | +0.50 | +0.18 |
| 09:47 | DIS | laggards | down | +0.43 | +0.63 | +0.79 |
| 09:55 | AAPL | laggards | down | -0.46 | -0.40 | -0.70 |
| 09:57 | AI | laggards | down | +0.45 | -1.78 | -1.07 |
| 09:59 | RKLB | laggards | down | +0.87 | +0.17 | +0.69 |
| 10:00 | WDC | leaders | up | +0.33 | -1.29 | -0.51 |
| 10:11 | DELL | laggards | down | -0.72 | -0.89 | -0.02 |
| 10:30 | AN | laggards | down | — | — | — |
| 10:34 | UAA | laggards | down | -0.46 | +0.53 | -0.15 |
| 10:40 | LCID | laggards | down | -1.54 | -1.34 | -0.21 |
| 10:57 | MDB | leaders | up | -0.13 | +0.41 | +1.22 |
| 10:58 | CRCL | leaders | up | +2.48 | +3.50 | +4.32 |
| 11:08 | URI | laggards | down | +0.17 | +0.17 | -0.18 |
| 11:18 | MRVL | leaders | up | +0.06 | +1.06 | -0.49 |
| 11:29 | RBLX | leaders | up | -0.71 | +0.79 | +0.26 |
| 11:39 | TSLA | laggards | down | +0.49 | +0.43 | -0.15 |
| 11:51 | BABA | leaders | up | +0.03 | +0.15 | +0.37 |
| 12:17 | KMX | laggards | down | -0.07 | +0.18 | +0.17 |
| 12:30 | MS | laggards | down | -0.03 | +0.04 | -0.07 |
| 13:29 | BULL | leaders | up | +0.77 | +1.29 | +0.60 |
| 13:31 | U | leaders | up | -0.86 | -0.91 | -1.37 |
| 13:31 | WBD | laggards | down | -1.85 | -0.43 | -1.26 |
| 14:07 | MSTR | leaders | up | -1.07 | -2.33 | — |
| 14:54 | LLY | laggards | down | +0.21 | -0.17 | — |
| 15:46 | MRK | laggards | down | — | — | — |
| 15:56 | PANW | laggards | down | — | — | — |

## 2026-07-21

Usable symbol-minutes 64,474/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | NBIS | +17.95 | miss | 09:31 |
| 2 | AAOI | +14.93 | miss | 09:52 |
| 3 | SNDK | +13.43 | miss | 09:31 |
| 4 | WDC | +11.67 | miss | 09:31 |
| 5 | MU | +11.34 | miss | 09:31 |
| 6 | CIFR | +10.61 | 11:34 | 09:34 |
| 7 | COHR | +10.32 | miss | 09:31 |
| 8 | STX | +10.30 | miss | 09:31 |
| 9 | RCAT | +9.86 | miss | 11:59 |
| 10 | ASTS | +9.48 | 10:05 | 09:54 |
| 11 | COIN | +8.78 | miss | 09:32 |
| 12 | CRWV | +8.09 | miss | miss |
| 13 | INTC | +7.81 | miss | 09:31 |
| 14 | CRCL | +7.77 | miss | 09:31 |
| 15 | AMD | +7.28 | miss | miss |
| 16 | RIOT | +7.16 | miss | miss |
| 17 | CIEN | +7.08 | miss | miss |
| 18 | APLD | +7.07 | miss | 09:49 |
| 19 | ARM | +6.63 | miss | miss |
| 20 | RGTI | +6.39 | miss | miss |

### Radar flags (7)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:04 | Bitcoin treasuries and miners (COIN, IREN, MSTR, RIOT, CLSK, MARA) | group_move | up | -0.04 | -0.24 | +1.32 |
| 10:05 | ASTS | relative_to_spy | up | +2.27 | +1.36 | +3.70 |
| 10:09 | Cybersecurity (CRWD, PANW, FTNT, NET, S, ZS) | group_move | down | +0.38 | -0.57 | +0.13 |
| 10:12 | Crypto and exchanges (MSTR, COIN, MARA, BULL, RIOT, HOOD, CRCL) | group_move | up | -1.03 | -0.26 | +0.47 |
| 10:14 | Space (ASTS, LUNR, RKLB, IRDM, PL) | group_move | up | +1.19 | +1.38 | +1.04 |
| 10:57 | Memory and storage (MU, STX, SNDK, WDC) | group_move | up | +1.02 | +0.48 | +1.86 |
| 11:34 | CIFR | relative_to_spy | up | +1.38 | +2.01 | +2.07 |

### Movers flags (54)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | WDC | leaders | up | +1.79 | +1.41 | +2.84 |
| 09:31 | COHR | leaders | up | -1.12 | -0.44 | +0.60 |
| 09:31 | SNDK | leaders | up | +1.30 | +0.16 | +2.69 |
| 09:31 | NBIS | leaders | up | +0.97 | +3.82 | +4.57 |
| 09:31 | STX | leaders | up | +1.66 | +0.47 | +2.48 |
| 09:31 | MU | leaders | up | +0.59 | +0.04 | +2.42 |
| 09:31 | INTC | leaders | up | -1.09 | -1.27 | +0.12 |
| 09:31 | MRVL | leaders | up | -0.31 | -0.63 | +0.53 |
| 09:31 | CRCL | leaders | up | +0.79 | +1.35 | +0.59 |
| 09:31 | ALAB | leaders | up | -0.32 | -0.36 | -0.07 |
| 09:31 | ADBE | laggards | down | +1.75 | +2.42 | +1.41 |
| 09:31 | LULU | laggards | down | +1.74 | +0.90 | +0.82 |
| 09:31 | NOW | laggards | down | +0.99 | +1.80 | +0.20 |
| 09:31 | CRM | laggards | down | +0.34 | +0.72 | -0.35 |
| 09:31 | CPRT | laggards | down | +0.54 | +0.62 | +0.28 |
| 09:31 | PINS | laggards | down | +1.00 | +0.93 | +0.97 |
| 09:31 | DDOG | laggards | down | +0.75 | +0.80 | -0.96 |
| 09:31 | NKE | laggards | down | +1.41 | +0.57 | +0.22 |
| 09:31 | PLTR | laggards | down | +0.87 | +1.04 | +0.14 |
| 09:31 | BIDU | laggards | down | -0.05 | +0.07 | -0.14 |
| 09:32 | COIN | leaders | up | +3.06 | +5.33 | +4.59 |
| 09:32 | FND | laggards | down | -0.94 | -1.06 | -1.33 |
| 09:32 | RDDT | laggards | down | +2.87 | +3.02 | +3.10 |
| 09:33 | S | laggards | down | -0.17 | -1.15 | -2.59 |
| 09:34 | HOOD | leaders | up | +0.84 | +1.59 | +1.74 |
| 09:34 | CIFR | leaders | up | +2.27 | +3.51 | +8.31 |
| 09:34 | LCID | laggards | down | +1.83 | +0.29 | +1.03 |
| 09:34 | BABA | laggards | down | -0.98 | -0.74 | -1.08 |
| 09:35 | COST | laggards | down | -0.08 | +0.04 | +0.01 |
| 09:36 | SCHW | laggards | down | +0.87 | +1.37 | +0.59 |
| 09:36 | NVO | laggards | down | +1.15 | +0.96 | +0.53 |
| 09:37 | V | laggards | down | +0.01 | -0.26 | -0.02 |
| 09:38 | GOOGL | laggards | down | +0.23 | -0.02 | -0.13 |
| 09:38 | HD | laggards | down | -0.30 | -0.44 | -0.49 |
| 09:39 | FLNC | leaders | up | -1.89 | -0.89 | -2.50 |
| 09:39 | DASH | laggards | down | +0.49 | +0.26 | -0.53 |
| 09:40 | MA | laggards | down | +0.39 | +0.06 | -0.15 |
| 09:42 | PYPL | laggards | down | -0.17 | -0.43 | -0.64 |
| 09:48 | PANW | laggards | down | -1.59 | -1.70 | -1.60 |
| 09:48 | CVNA | laggards | down | +0.81 | +0.86 | +0.48 |
| 09:49 | APLD | leaders | up | +0.96 | +0.86 | +3.02 |
| 09:49 | CRWD | laggards | down | -2.25 | -2.09 | -2.20 |
| 09:51 | URI | laggards | down | +0.70 | +0.97 | +0.73 |
| 09:52 | AAOI | leaders | up | +0.23 | +2.31 | +4.01 |
| 09:54 | ASTS | leaders | up | +1.42 | +2.93 | +4.13 |
| 09:54 | FTNT | laggards | down | -0.39 | -0.47 | -0.09 |
| 09:55 | AAPL | laggards | down | +1.06 | +1.22 | +1.68 |
| 10:11 | ZS | laggards | down | +1.01 | +0.41 | +0.52 |
| 10:32 | LOW | laggards | down | +0.12 | +0.27 | +0.88 |
| 10:34 | ONON | laggards | down | -0.29 | +0.15 | +0.01 |
| 10:49 | WMT | laggards | down | +0.07 | -0.26 | -0.76 |
| 11:48 | MDB | laggards | down | -1.80 | -2.08 | -3.33 |
| 11:59 | RCAT | leaders | up | -0.78 | -0.73 | -0.35 |
| 15:48 | LYFT | laggards | down | — | — | — |

## 2026-07-22

Usable symbol-minutes 64,571/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | SMCI | +19.96 | 10:02 | 09:31 |
| 2 | DELL | +9.43 | miss | 09:31 |
| 3 | RIOT | +8.91 | 10:02 | 09:41 |
| 4 | RCAT | -8.73 | 11:04 | 09:31 |
| 5 | RDDT | -8.20 | miss | 09:31 |
| 6 | TDOC | -8.02 | miss | 09:47 |
| 7 | LCID | -7.26 | miss | 12:32 |
| 8 | AAOI | -7.21 | miss | 09:31 |
| 9 | CIFR | +6.98 | miss | 09:38 |
| 10 | CRCL | -6.81 | miss | 09:31 |
| 11 | NOW | -6.35 | miss | 09:33 |
| 12 | PLTR | -5.98 | miss | 09:32 |
| 13 | COIN | -5.42 | miss | 10:53 |
| 14 | DASH | -5.37 | miss | 09:34 |
| 15 | RBLX | -5.33 | miss | 09:33 |
| 16 | AI | -4.54 | miss | 10:40 |
| 17 | ZS | -4.23 | miss | 09:43 |
| 18 | CVNA | -4.20 | miss | 09:31 |
| 19 | CRM | -4.04 | miss | miss |
| 20 | PCAR | +3.97 | miss | 10:55 |

### Radar flags (8)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | CRWV | relative_to_spy | up | -0.51 | -1.93 | -1.46 |
| 10:02 | IREN | relative_to_spy | up | -0.39 | -2.29 | -2.01 |
| 10:02 | RIOT | relative_to_spy | up | +0.70 | -0.09 | +1.70 |
| 10:02 | SMCI | relative_to_spy | up | +0.52 | +1.12 | +1.27 |
| 10:02 | Bitcoin treasuries and miners (RIOT, IREN, MARA, CLSK, MSTR) | group_move | up | -0.41 | -1.38 | -0.72 |
| 10:02 | Memory and storage (WDC, SNDK, STX, MU) | group_move | up | +1.44 | +0.71 | +1.00 |
| 10:02 | Neoclouds and AI hosting (IREN, CRWV, NBIS, WULF, CIFR, APLD, ORCL) | group_move | up | -0.32 | -1.28 | -1.08 |
| 11:04 | RCAT | relative_to_spy | down | +1.30 | +2.09 | -0.61 |

### Movers flags (64)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | SMCI | leaders | up | +7.43 | +7.66 | +7.99 |
| 09:31 | DELL | leaders | up | +3.83 | +5.99 | +4.21 |
| 09:31 | OKLO | leaders | up | +2.74 | +1.10 | +0.14 |
| 09:31 | HIMS | leaders | up | -2.39 | -4.20 | -3.20 |
| 09:31 | FLNC | leaders | up | -2.17 | -2.79 | -3.47 |
| 09:31 | RKLB | leaders | up | +0.81 | +1.82 | +1.89 |
| 09:31 | AN | leaders | up | +1.04 | — | — |
| 09:31 | GM | leaders | up | +2.98 | +0.38 | +0.98 |
| 09:31 | HPQ | leaders | up | -0.36 | -0.62 | -0.88 |
| 09:31 | LAD | leaders | up | +1.32 | — | -1.00 |
| 09:31 | RDDT | laggards | down | -1.74 | -1.02 | -1.82 |
| 09:31 | SNDK | laggards | down | +3.14 | +4.89 | +4.32 |
| 09:31 | CVNA | laggards | down | +0.51 | +0.54 | +0.35 |
| 09:31 | CRCL | laggards | down | +1.53 | +0.48 | -0.25 |
| 09:31 | ARM | laggards | down | +1.61 | +1.69 | +1.81 |
| 09:31 | RCAT | laggards | down | -0.68 | +2.04 | -1.91 |
| 09:31 | DDOG | laggards | down | -1.00 | +0.02 | -0.25 |
| 09:31 | AAOI | laggards | down | -0.11 | -2.44 | -0.41 |
| 09:31 | WDC | laggards | down | +3.78 | +5.23 | +4.47 |
| 09:31 | MU | laggards | down | +2.29 | +2.94 | +2.49 |
| 09:32 | OXY | leaders | up | -0.45 | -0.19 | -0.71 |
| 09:32 | APP | laggards | down | -0.42 | +1.04 | +0.59 |
| 09:32 | U | laggards | down | +1.03 | +0.80 | +0.26 |
| 09:32 | INTC | laggards | down | +2.70 | +2.82 | +3.15 |
| 09:32 | PLTR | laggards | down | -1.27 | -1.78 | -2.53 |
| 09:33 | KMX | leaders | up | -0.11 | -1.75 | -2.62 |
| 09:33 | RBLX | laggards | down | +0.33 | +0.42 | -0.58 |
| 09:33 | NOW | laggards | down | -1.34 | -2.06 | -2.83 |
| 09:34 | CRWV | leaders | up | +3.92 | +3.19 | +1.97 |
| 09:34 | DASH | laggards | down | -1.35 | -1.79 | -1.87 |
| 09:34 | SNOW | laggards | down | -0.42 | +0.53 | +0.12 |
| 09:38 | CIFR | leaders | up | +0.12 | +1.44 | +1.67 |
| 09:39 | F | leaders | up | +0.07 | -0.94 | -1.44 |
| 09:39 | PL | laggards | down | +2.24 | +2.47 | +2.31 |
| 09:39 | LUNR | laggards | down | +1.42 | +0.44 | +2.16 |
| 09:41 | RIOT | leaders | up | +2.50 | +2.08 | +5.46 |
| 09:42 | IREN | leaders | up | +3.30 | +1.17 | +1.40 |
| 09:42 | PANW | laggards | down | +2.41 | +1.40 | +1.50 |
| 09:42 | S | laggards | down | +1.96 | +0.54 | +0.77 |
| 09:43 | NFLX | leaders | up | -0.26 | +0.47 | +0.04 |
| 09:43 | ZS | laggards | down | +1.10 | -0.40 | -0.69 |
| 09:45 | QCOM | leaders | up | -0.49 | -0.23 | -0.17 |
| 09:47 | TDOC | laggards | down | -1.91 | -4.19 | -4.90 |
| 09:51 | NBIS | leaders | up | +0.39 | -0.94 | +0.13 |
| 09:52 | LCID | leaders | up | -1.15 | -1.77 | -3.56 |
| 09:59 | MDB | laggards | down | +1.23 | +0.81 | +0.69 |
| 10:03 | MARA | leaders | up | -1.15 | -1.12 | -1.79 |
| 10:13 | LULU | laggards | down | -0.18 | -0.56 | -0.15 |
| 10:17 | SOFI | laggards | down | -0.29 | +0.70 | +0.33 |
| 10:22 | ALAB | leaders | up | -0.79 | +0.90 | +0.71 |
| 10:27 | STX | leaders | up | -1.14 | -1.64 | -0.69 |
| 10:31 | NKE | laggards | down | +0.25 | +0.62 | +0.62 |
| 10:36 | DE | leaders | up | -0.18 | -0.03 | +0.64 |
| 10:40 | AI | laggards | down | +0.13 | +0.03 | -1.67 |
| 10:53 | COIN | laggards | down | +0.68 | +0.05 | +0.73 |
| 10:55 | PCAR | leaders | up | +0.03 | +0.15 | +0.98 |
| 11:01 | MRVL | leaders | up | -0.13 | -0.21 | -0.25 |
| 11:06 | APLD | leaders | up | -0.60 | -1.05 | -2.56 |
| 11:24 | ONON | laggards | down | +1.20 | +1.79 | +1.99 |
| 12:03 | NVDA | leaders | up | +0.09 | +0.24 | +0.20 |
| 12:05 | SPOT | laggards | down | — | +0.89 | +0.25 |
| 12:32 | LCID | laggards | down | -1.49 | -1.76 | -1.48 |
| 15:25 | AVGO | leaders | up | -0.29 | — | — |
| 15:34 | AMD | leaders | up | — | — | — |

## 2026-07-23

Usable symbol-minutes 64,639/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | TSLA | -13.29 | miss | 09:31 |
| 2 | URI | +11.35 | miss | 09:31 |
| 3 | CIFR | +6.79 | 10:07 | 09:32 |
| 4 | UAA | -5.93 | miss | 09:31 |
| 5 | GOOGL | -5.90 | miss | 09:31 |
| 6 | MSTR | -5.14 | miss | 09:31 |
| 7 | DECK | -4.85 | miss | 13:19 |
| 8 | CRDO | +4.84 | 10:07 | 09:54 |
| 9 | CRCL | -4.78 | miss | 09:31 |
| 10 | HIMS | +4.58 | 12:45 | 12:40 |
| 11 | MU | +4.44 | miss | 09:37 |
| 12 | MARA | +4.14 | miss | 09:43 |
| 13 | WULF | +4.11 | miss | 09:34 |
| 14 | CIEN | +3.85 | miss | 09:38 |
| 15 | RCAT | +3.79 | miss | 11:56 |
| 16 | ONON | -3.70 | miss | 09:42 |
| 17 | LCID | -3.63 | miss | 09:56 |
| 18 | MRK | +3.60 | miss | 10:45 |
| 19 | S | -3.38 | miss | 12:16 |
| 20 | ORCL | -3.37 | miss | 09:34 |

### Radar flags (12)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | AAOI | relative_to_spy | up | -1.20 | -3.29 | -3.44 |
| 10:04 | Neoclouds and AI hosting (CIFR, NBIS, APLD, WULF, CRWV, IREN, ORCL) | group_move | up | -0.73 | -2.55 | -2.18 |
| 10:07 | CIFR | relative_to_spy | up | -1.39 | -3.72 | -4.19 |
| 10:07 | CRDO | relative_to_spy | up | -1.30 | -1.65 | -2.28 |
| 10:07 | NBIS | relative_to_spy | up | -1.99 | -3.19 | -3.08 |
| 10:07 | Bitcoin treasuries and miners (MARA, CLSK, IREN, RIOT, COIN) | group_move | up | -0.77 | -2.44 | -2.03 |
| 10:07 | Quantum computing (QBTS, QUBT, RGTI, IONQ) | group_move | up | -1.11 | -2.86 | -2.57 |
| 10:36 | Space (RKLB, ASTS, PL, LUNR, IRDM) | group_move | down | -0.73 | +0.17 | +1.29 |
| 11:00 | Neoclouds and AI hosting (CIFR, IREN, CRWV, NBIS, APLD, ORCL, WULF) | group_move | down | -0.65 | +0.28 | +0.24 |
| 11:10 | Quantum computing (IONQ, QBTS, RGTI, QUBT) | group_move | down | +0.17 | +0.84 | +1.05 |
| 12:45 | HIMS | relative_to_spy | up | +3.51 | +1.28 | -2.57 |
| 14:03 | HIMS | relative_to_spy | down | +0.32 | -4.63 | — |

### Movers flags (64)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | URI | leaders | up | +5.07 | +3.78 | +4.68 |
| 09:31 | SNOW | leaders | up | -2.07 | -3.22 | -5.36 |
| 09:31 | NOW | leaders | up | -1.36 | -2.20 | -3.63 |
| 09:31 | OXY | leaders | up | -0.92 | -0.28 | -0.07 |
| 09:31 | COP | leaders | up | -0.20 | +0.35 | +1.02 |
| 09:31 | NET | leaders | up | -3.03 | -3.30 | -4.38 |
| 09:31 | WDC | leaders | up | -1.77 | -1.24 | -0.50 |
| 09:31 | CVX | leaders | up | -0.33 | +0.34 | +0.79 |
| 09:31 | SHEL | leaders | up | -0.33 | -0.11 | +0.34 |
| 09:31 | XOM | leaders | up | -0.27 | +0.39 | +1.25 |
| 09:31 | TSLA | laggards | down | -3.17 | -3.90 | -4.55 |
| 09:31 | GOOGL | laggards | down | -0.55 | -1.44 | -1.38 |
| 09:31 | UAA | laggards | down | -1.53 | -2.30 | -2.31 |
| 09:31 | ASTS | laggards | down | +2.91 | +0.94 | -2.06 |
| 09:31 | AMZN | laggards | down | -0.41 | -0.90 | -1.36 |
| 09:31 | MSTR | laggards | down | -1.22 | -1.25 | -3.65 |
| 09:31 | CNC | laggards | down | +0.24 | -0.42 | +0.46 |
| 09:31 | META | laggards | down | +0.01 | -0.50 | -1.28 |
| 09:31 | CRCL | laggards | down | -0.77 | -1.11 | -3.62 |
| 09:31 | HIMS | laggards | down | +4.51 | +4.80 | +2.74 |
| 09:32 | SMCI | leaders | up | +1.89 | +1.96 | -0.42 |
| 09:32 | CIFR | leaders | up | +4.36 | +5.08 | +1.39 |
| 09:32 | STX | leaders | up | -0.40 | -0.39 | -0.31 |
| 09:32 | LUNR | laggards | down | +4.02 | +2.60 | +0.71 |
| 09:32 | IBM | laggards | down | +1.38 | +3.32 | +3.93 |
| 09:32 | HOOD | laggards | down | +1.21 | +0.54 | -1.33 |
| 09:33 | AAOI | leaders | up | +4.23 | +2.33 | -0.16 |
| 09:33 | RIOT | leaders | up | +3.12 | +2.54 | +3.16 |
| 09:33 | U | laggards | down | +2.29 | +0.65 | -0.79 |
| 09:33 | DASH | laggards | down | +0.15 | -0.79 | -2.33 |
| 09:33 | RBLX | laggards | down | +0.93 | +0.23 | -1.32 |
| 09:34 | WULF | leaders | up | +2.29 | +1.19 | -0.46 |
| 09:34 | ORCL | laggards | down | +0.94 | +1.44 | -1.24 |
| 09:35 | RDDT | leaders | up | +1.96 | -0.56 | -2.22 |
| 09:35 | TGT | laggards | down | -0.93 | +0.35 | +0.68 |
| 09:35 | CVNA | laggards | down | +0.28 | +0.40 | -1.28 |
| 09:37 | MU | leaders | up | +0.60 | +0.61 | +0.84 |
| 09:38 | CIEN | leaders | up | +1.76 | +2.27 | +0.77 |
| 09:39 | RIVN | laggards | down | +0.94 | +0.12 | -0.04 |
| 09:41 | CLSK | leaders | up | -0.44 | -0.11 | +0.94 |
| 09:42 | NBIS | leaders | up | +1.55 | -0.93 | -1.16 |
| 09:42 | IREN | leaders | up | +0.10 | -0.41 | -1.23 |
| 09:42 | ONON | laggards | down | -0.08 | +0.01 | +0.37 |
| 09:43 | MARA | leaders | up | -0.52 | -0.87 | -0.57 |
| 09:43 | PANW | laggards | down | -1.17 | -1.18 | -0.47 |
| 09:47 | APLD | leaders | up | -2.28 | -3.27 | -3.66 |
| 09:47 | GM | laggards | down | -0.57 | -0.20 | -0.12 |
| 09:49 | COHR | leaders | up | -0.66 | -1.13 | -2.64 |
| 09:51 | FND | laggards | down | +0.08 | -0.07 | -0.31 |
| 09:54 | CRDO | leaders | up | +0.53 | -0.35 | -1.00 |
| 09:56 | LCID | laggards | down | -1.07 | -3.89 | -3.34 |
| 10:01 | LULU | laggards | down | +1.25 | +1.17 | +0.85 |
| 10:22 | LYFT | laggards | down | -2.13 | -2.44 | +0.50 |
| 10:45 | MRK | leaders | up | +0.48 | +0.49 | -0.19 |
| 10:53 | SNDK | leaders | up | -0.84 | +0.06 | +1.89 |
| 11:12 | LLY | leaders | up | +0.06 | -0.16 | -0.39 |
| 11:12 | SCHW | leaders | up | -0.51 | -1.24 | -0.74 |
| 11:12 | PL | laggards | down | +1.31 | +1.71 | +2.69 |
| 11:56 | RCAT | leaders | up | +0.16 | -0.56 | -0.40 |
| 12:16 | S | laggards | down | +1.10 | +0.50 | +0.00 |
| 12:40 | HIMS | leaders | up | +3.38 | +1.24 | -1.48 |
| 12:55 | AMD | laggards | down | +0.92 | +1.32 | +1.09 |
| 13:12 | TDOC | laggards | down | +0.67 | +1.66 | +1.60 |
| 13:19 | DECK | laggards | down | -0.05 | -0.29 | -0.33 |

## 2026-07-24

Usable symbol-minutes 64,520/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | NBIS | -15.13 | 10:04 | 09:31 |
| 2 | HIMS | -14.30 | 10:02 | 10:04 |
| 3 | CRWV | -11.47 | miss | 09:34 |
| 4 | ALAB | -10.93 | miss | 09:31 |
| 5 | SNDK | -10.89 | miss | 09:31 |
| 6 | AAOI | -10.70 | 10:02 | 09:31 |
| 7 | CIFR | -10.44 | miss | 15:02 |
| 8 | CRDO | -9.97 | 10:05 | 09:32 |
| 9 | COHR | -9.94 | 10:06 | 09:31 |
| 10 | APLD | -9.13 | miss | 09:36 |
| 11 | RKLB | -8.79 | miss | 11:54 |
| 12 | IREN | -8.75 | miss | 09:34 |
| 13 | OKLO | -8.62 | miss | 11:53 |
| 14 | PL | -8.55 | miss | 09:53 |
| 15 | ARM | -8.24 | 10:05 | miss |
| 16 | WULF | -8.03 | miss | miss |
| 17 | INTC | -7.99 | miss | miss |
| 18 | NOW | +7.34 | miss | 09:31 |
| 19 | MRVL | -7.31 | miss | 09:31 |
| 20 | MU | -7.10 | miss | 09:31 |

### Radar flags (13)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | AAOI | relative_to_spy | down | -1.41 | -0.76 | +0.53 |
| 10:02 | HIMS | relative_to_spy | down | -4.30 | -4.90 | -6.43 |
| 10:02 | Neoclouds and AI hosting (NBIS, CRWV, ORCL, CIFR, APLD, IREN, WULF) | group_move | down | -1.10 | -1.03 | +0.71 |
| 10:02 | Quantum computing (RGTI, IONQ, QUBT, QBTS) | group_move | down | -0.40 | -0.60 | +0.45 |
| 10:02 | Space (PL, LUNR, RKLB, ASTS) | group_move | down | -1.00 | -1.43 | -1.15 |
| 10:04 | NBIS | relative_to_spy | down | -1.22 | -1.80 | +2.66 |
| 10:04 | AI networking and connectivity (CRDO, COHR, ALAB, MRVL, AVGO, ANET) | group_move | down | -0.80 | -0.88 | +0.42 |
| 10:05 | ARM | relative_to_spy | down | -1.00 | -1.57 | -0.57 |
| 10:05 | CRDO | relative_to_spy | down | -1.64 | -1.87 | +1.02 |
| 10:05 | GPUs and AI compute chips (ARM, INTC, MRVL, AMD, QCOM, AVGO, TSM, NVDA) | group_move | down | -0.41 | -0.29 | +0.36 |
| 10:05 | Memory and storage (SNDK, MU, WDC, STX) | group_move | down | -1.30 | -0.71 | +0.93 |
| 10:06 | COHR | relative_to_spy | down | -1.87 | -1.78 | -0.49 |
| 11:32 | Athletic apparel (ONON, LULU, DECK, UAA, NKE) | group_move | up | -0.86 | -0.43 | -0.30 |

### Movers flags (49)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | HIMS | leaders | up | -9.09 | -13.72 | -14.65 |
| 09:31 | NOW | leaders | up | -0.33 | +0.07 | +1.05 |
| 09:31 | ZS | leaders | up | -2.30 | -2.33 | -1.45 |
| 09:31 | CRM | leaders | up | -0.40 | -0.10 | +0.82 |
| 09:31 | ADBE | leaders | up | -0.08 | +0.80 | +2.20 |
| 09:31 | HPQ | leaders | up | +0.50 | +1.40 | +2.16 |
| 09:31 | ORCL | leaders | up | -3.87 | -4.84 | -3.62 |
| 09:31 | S | leaders | up | -0.06 | +0.85 | +1.43 |
| 09:31 | U | leaders | up | -3.06 | -3.77 | -2.04 |
| 09:31 | SNAP | leaders | up | -2.04 | -3.01 | -1.74 |
| 09:31 | AXP | laggards | down | -0.70 | -1.20 | -0.74 |
| 09:31 | SNDK | laggards | down | -2.76 | -4.27 | -3.39 |
| 09:31 | WDC | laggards | down | -0.13 | -1.34 | -1.81 |
| 09:31 | ALAB | laggards | down | -2.08 | -4.69 | -4.89 |
| 09:31 | NBIS | laggards | down | -4.41 | -6.65 | -6.30 |
| 09:31 | STX | laggards | down | +1.22 | -0.27 | -0.65 |
| 09:31 | MU | laggards | down | -1.94 | -2.56 | -2.68 |
| 09:31 | MRVL | laggards | down | -1.38 | -2.96 | -3.01 |
| 09:31 | COHR | laggards | down | -3.14 | -5.00 | -4.86 |
| 09:31 | AAOI | laggards | down | -5.01 | -6.25 | -5.08 |
| 09:32 | NVO | leaders | up | +0.21 | +0.58 | -0.65 |
| 09:32 | HOOD | laggards | down | -2.28 | -3.62 | -2.95 |
| 09:32 | CRDO | laggards | down | -4.28 | -5.81 | -5.74 |
| 09:33 | TDOC | leaders | up | +0.18 | +0.40 | +0.53 |
| 09:33 | ARM | leaders | up | -4.97 | -5.74 | -6.19 |
| 09:33 | DECK | laggards | down | -0.76 | +0.21 | +2.05 |
| 09:34 | IBM | leaders | up | +1.12 | +1.33 | +1.49 |
| 09:34 | CLSK | laggards | down | -0.61 | -1.64 | -0.24 |
| 09:34 | CRWV | laggards | down | -4.30 | -4.39 | -4.68 |
| 09:34 | IREN | laggards | down | -2.55 | -2.65 | +0.10 |
| 09:36 | APLD | laggards | down | -3.28 | -4.39 | -3.00 |
| 09:37 | SPOT | leaders | up | -0.31 | +0.11 | +1.37 |
| 09:37 | GM | leaders | up | +1.16 | +1.21 | +1.41 |
| 09:38 | PINS | leaders | up | -1.02 | -0.97 | -0.45 |
| 09:40 | ONON | leaders | up | -2.00 | -1.24 | +0.73 |
| 09:43 | UAA | leaders | up | -1.33 | -0.39 | +1.26 |
| 09:45 | DIS | leaders | up | +0.45 | +0.94 | +1.40 |
| 09:46 | LCID | leaders | up | -1.83 | -2.30 | -3.94 |
| 09:52 | CPRT | leaders | up | +0.12 | +0.71 | +0.40 |
| 09:53 | PL | laggards | down | -1.25 | -1.61 | -1.86 |
| 09:55 | AAPL | leaders | up | +0.35 | +0.55 | +1.19 |
| 09:58 | GOOGL | leaders | up | -1.06 | -1.63 | -1.75 |
| 10:04 | HIMS | laggards | down | -3.01 | -3.47 | -4.57 |
| 10:59 | LYFT | leaders | up | +1.28 | +0.43 | +0.99 |
| 11:21 | LULU | leaders | up | -0.34 | +0.68 | +0.75 |
| 11:22 | FND | leaders | up | -0.25 | -0.43 | -1.40 |
| 11:53 | OKLO | laggards | down | +0.40 | -0.68 | -0.63 |
| 11:54 | RKLB | laggards | down | +0.09 | -1.19 | -1.08 |
| 15:02 | CIFR | laggards | down | -0.94 | — | — |

## 2026-07-27

Usable symbol-minutes 64,921/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | QBTS | +20.34 | 10:02 | 09:31 |
| 2 | SNDK | -11.04 | 10:02 | 09:34 |
| 3 | RGTI | +10.51 | 10:02 | 09:31 |
| 4 | IONQ | +9.36 | 10:02 | 09:31 |
| 5 | AI | +8.20 | miss | 10:06 |
| 6 | HIMS | +7.63 | miss | 10:49 |
| 7 | MSTR | +7.59 | miss | 09:40 |
| 8 | QUBT | +7.11 | miss | 09:31 |
| 9 | PLTR | +6.98 | miss | 13:11 |
| 10 | NOW | +6.84 | miss | 11:21 |
| 11 | DASH | +6.61 | miss | 09:31 |
| 12 | CPRT | +6.60 | miss | 10:42 |
| 13 | CIFR | -6.50 | 10:14 | 10:09 |
| 14 | U | +6.34 | miss | 12:26 |
| 15 | LYFT | +6.25 | miss | 11:32 |
| 16 | SONY | +6.22 | miss | 09:31 |
| 17 | RDDT | +6.20 | miss | 09:48 |
| 18 | PINS | +6.17 | miss | 11:53 |
| 19 | CRM | +6.05 | miss | 09:31 |
| 20 | CVNA | +5.90 | miss | 09:31 |

### Radar flags (20)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | IONQ | relative_to_spy | up | -2.82 | -3.41 | -4.89 |
| 10:02 | QBTS | relative_to_spy | up | -1.61 | -1.58 | -1.92 |
| 10:02 | SNDK | relative_to_spy | down | -3.91 | -3.46 | -2.51 |
| 10:02 | RGTI | relative_to_sector | up | -3.58 | -4.00 | -4.21 |
| 10:02 | Memory and storage (SNDK, WDC, STX, MU) | group_move | down | -3.64 | -3.40 | -2.59 |
| 10:02 | Quantum computing (QBTS, IONQ, RGTI, QUBT) | group_move | up | -2.58 | -2.86 | -3.48 |
| 10:06 | AI networking and connectivity (CRDO, ALAB, COHR, MRVL, ANET, AVGO) | group_move | down | -2.06 | -1.70 | -1.79 |
| 10:06 | Cloud software and data (MDB, CRM, ADBE, NOW, DDOG, ORCL, SNOW) | group_move | up | -0.14 | -0.02 | +0.60 |
| 10:08 | AAOI | relative_to_spy | down | -3.78 | -1.67 | -1.64 |
| 10:08 | CRDO | relative_to_spy | down | -3.64 | -1.86 | -2.53 |
| 10:08 | WDC | relative_to_spy | down | -4.19 | -2.51 | -1.44 |
| 10:08 | Neoclouds and AI hosting (CIFR, IREN, WULF, NBIS, APLD, CRWV) | group_move | down | -2.86 | -2.10 | -2.52 |
| 10:14 | CIFR | relative_to_spy | down | -3.73 | -3.68 | -3.23 |
| 10:25 | MU | relative_to_spy | down | -0.02 | -0.47 | +0.68 |
| 10:25 | Quantum computing (RGTI, QBTS, IONQ, QUBT) | group_move | down | +0.01 | -0.30 | -0.83 |
| 10:39 | Bitcoin treasuries and miners (RIOT, COIN, CLSK, IREN, MARA, MSTR) | group_move | down | -0.24 | -0.40 | +1.13 |
| 10:39 | Crypto and exchanges (RIOT, HOOD, COIN, CRCL, MARA, MSTR, BULL) | group_move | down | -0.03 | -0.21 | +0.99 |
| 10:40 | GPUs and AI compute chips (AMD, MRVL, INTC, ARM, TSM, AVGO, QCOM, NVDA) | group_move | down | +1.09 | +0.09 | +1.53 |
| 15:10 | Neoclouds and AI hosting (NBIS, APLD, WULF, IREN, CIFR, CRWV, ORCL) | group_move | up | -0.41 | — | — |
| 15:10 | Quantum computing (QBTS, RGTI, IONQ, QUBT) | group_move | up | +0.21 | — | — |

### Movers flags (62)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | QBTS | leaders | up | +8.55 | +7.33 | +7.87 |
| 09:31 | RGTI | leaders | up | +6.75 | +3.95 | +2.53 |
| 09:31 | CVNA | leaders | up | +0.59 | -0.34 | -0.08 |
| 09:31 | DASH | leaders | up | +0.69 | +1.34 | +2.26 |
| 09:31 | QUBT | leaders | up | +3.90 | +2.41 | +2.44 |
| 09:31 | IONQ | leaders | up | +7.46 | +5.05 | +3.04 |
| 09:31 | SONY | leaders | up | +0.94 | +2.60 | +2.97 |
| 09:31 | HSAI | leaders | up | +1.79 | +0.84 | +1.65 |
| 09:31 | CRM | leaders | up | +1.20 | +2.32 | +3.64 |
| 09:31 | DECK | leaders | up | -0.48 | -0.55 | +0.93 |
| 09:31 | OXY | laggards | down | +1.58 | +1.82 | +1.15 |
| 09:31 | COP | laggards | down | +1.29 | +1.63 | +1.01 |
| 09:31 | CVX | laggards | down | +0.94 | +1.70 | +1.36 |
| 09:31 | XOM | laggards | down | +1.24 | +1.92 | +1.30 |
| 09:31 | RIOT | laggards | down | +1.70 | -1.39 | -2.59 |
| 09:31 | WBD | laggards | down | +1.12 | +2.27 | +2.04 |
| 09:31 | SHEL | laggards | down | +0.86 | +1.44 | +1.27 |
| 09:31 | CIEN | laggards | down | -1.96 | -3.93 | -4.04 |
| 09:31 | COHR | laggards | down | -1.58 | -4.81 | -6.46 |
| 09:31 | HUM | laggards | down | -1.26 | -0.11 | +0.14 |
| 09:32 | NBIS | leaders | up | -3.16 | -3.28 | -5.23 |
| 09:32 | SOFI | leaders | up | +0.86 | -0.63 | +0.42 |
| 09:32 | CVS | laggards | down | -0.44 | +0.46 | +0.94 |
| 09:32 | LLY | laggards | down | +1.49 | +2.37 | +1.94 |
| 09:33 | ONON | leaders | up | +0.25 | +0.17 | +1.13 |
| 09:33 | APP | leaders | up | +0.37 | -0.18 | +1.29 |
| 09:33 | CLSK | laggards | down | +1.38 | -1.21 | -0.63 |
| 09:33 | MARA | laggards | down | +0.11 | -1.21 | -2.08 |
| 09:34 | SNDK | laggards | down | -7.43 | -10.78 | -10.31 |
| 09:36 | RKLB | leaders | up | -1.26 | -2.08 | -3.12 |
| 09:36 | PYPL | laggards | down | +1.01 | +1.89 | +2.31 |
| 09:38 | ASTS | leaders | up | -1.62 | -3.26 | -3.43 |
| 09:38 | URI | laggards | down | -0.12 | +0.25 | +0.07 |
| 09:39 | AMD | laggards | down | -1.94 | -5.56 | -5.91 |
| 09:40 | MSTR | leaders | up | +2.45 | +1.11 | +1.25 |
| 09:41 | COIN | leaders | up | -0.76 | -3.02 | -2.34 |
| 09:42 | NVDA | laggards | down | -0.48 | -1.44 | -2.52 |
| 09:43 | ORCL | leaders | up | +0.17 | -0.41 | -0.34 |
| 09:44 | RBLX | laggards | down | -0.23 | -0.70 | +3.61 |
| 09:47 | ALAB | laggards | down | -1.66 | -3.58 | -4.98 |
| 09:48 | RDDT | leaders | up | +1.37 | +0.80 | +1.96 |
| 09:51 | CRCL | leaders | up | -1.01 | -2.38 | -3.76 |
| 09:53 | OKLO | leaders | up | -2.56 | -3.09 | -3.47 |
| 09:55 | RIVN | leaders | up | +0.01 | +0.20 | +0.17 |
| 09:57 | WDC | laggards | down | -3.81 | -3.65 | -3.01 |
| 10:02 | MU | laggards | down | -3.36 | -2.73 | -2.01 |
| 10:03 | ANET | laggards | down | +0.04 | -1.11 | -0.46 |
| 10:04 | CRDO | laggards | down | -2.95 | -2.51 | -2.43 |
| 10:06 | AI | leaders | up | +0.55 | +2.06 | +1.93 |
| 10:06 | AAOI | laggards | down | -3.19 | -1.89 | -1.75 |
| 10:07 | STX | laggards | down | -3.78 | -3.08 | -2.67 |
| 10:09 | CIFR | laggards | down | -4.39 | -5.02 | -5.09 |
| 10:30 | ADBE | leaders | up | -0.17 | +0.84 | +0.94 |
| 10:42 | CPRT | leaders | up | -0.03 | +0.66 | +0.62 |
| 10:49 | HIMS | leaders | up | -0.27 | -0.09 | -0.14 |
| 11:21 | NOW | leaders | up | -0.11 | +0.32 | +2.51 |
| 11:32 | LYFT | leaders | up | -0.00 | +0.46 | +0.48 |
| 11:53 | PINS | leaders | up | +0.28 | +0.38 | +0.72 |
| 12:26 | U | leaders | up | +0.43 | +1.02 | +0.23 |
| 13:11 | PLTR | leaders | up | +0.96 | +0.71 | +0.24 |
| 14:19 | WULF | laggards | down | -0.27 | +1.75 | — |
| 15:08 | DELL | laggards | down | +0.80 | — | — |

## 2026-07-28

Usable symbol-minutes 64,855/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | LCID | +21.30 | 10:11 | 10:10 |
| 2 | SNDK | -14.49 | 10:02 | 09:31 |
| 3 | COHR | -10.55 | 10:02 | 09:31 |
| 4 | AAOI | -10.14 | 10:02 | 09:31 |
| 5 | NBIS | -9.92 | 10:02 | 09:47 |
| 6 | QBTS | -9.85 | miss | 09:35 |
| 7 | MU | -9.09 | miss | 09:31 |
| 8 | STX | -8.77 | 10:02 | 09:31 |
| 9 | DELL | -8.39 | 10:02 | 09:32 |
| 10 | AMD | -8.39 | miss | 15:47 |
| 11 | ARM | -8.35 | miss | 12:01 |
| 12 | ALAB | -8.13 | miss | 09:31 |
| 13 | MRVL | -8.01 | miss | 10:21 |
| 14 | CRDO | -7.86 | miss | 09:41 |
| 15 | RGTI | -7.40 | miss | miss |
| 16 | CIEN | -7.33 | miss | 09:31 |
| 17 | LUNR | -7.30 | miss | 09:34 |
| 18 | WDC | -7.15 | 10:02 | 09:31 |
| 19 | FLNC | -6.83 | miss | 10:40 |
| 20 | IREN | -6.74 | miss | miss |

### Radar flags (30)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | AAOI | relative_to_spy | down | -0.39 | +3.62 | +5.07 |
| 10:02 | COHR | relative_to_spy | down | -2.31 | +0.56 | +1.88 |
| 10:02 | DELL | relative_to_spy | down | +1.83 | +4.29 | +6.24 |
| 10:02 | HIMS | relative_to_spy | down | -1.64 | -0.50 | +0.98 |
| 10:02 | NBIS | relative_to_spy | down | -1.36 | -0.54 | +2.84 |
| 10:02 | SNDK | relative_to_spy | down | -1.10 | -0.65 | +1.27 |
| 10:02 | STX | relative_to_spy | down | +0.10 | +1.39 | +4.28 |
| 10:02 | WDC | relative_to_spy | down | -0.75 | +1.03 | +4.74 |
| 10:02 | AI networking and connectivity (COHR, CRDO, MRVL, ALAB, ANET) | group_move | down | -1.15 | +0.51 | +3.38 |
| 10:02 | AI software and analytics (PLTR, DDOG, SNOW, APP) | group_move | down | -0.47 | +2.06 | +3.80 |
| 10:02 | Cybersecurity (NET, CRWD, FTNT, PANW, ZS, S) | group_move | down | +0.19 | +2.71 | +3.16 |
| 10:02 | Memory and storage (SNDK, STX, WDC, MU) | group_move | down | -0.64 | +0.47 | +2.97 |
| 10:02 | Neoclouds and AI hosting (NBIS, CIFR, IREN, WULF, CRWV, ORCL) | group_move | down | +0.03 | +1.41 | +3.44 |
| 10:02 | Quantum computing (QBTS, IONQ, RGTI, QUBT) | group_move | down | -0.38 | +2.38 | +3.48 |
| 10:02 | Space (RKLB, LUNR, ASTS, PL, IRDM) | group_move | down | -0.23 | +2.21 | +3.30 |
| 10:11 | LCID | relative_to_spy | up | -2.35 | -4.57 | -2.83 |
| 10:46 | Quantum computing (IONQ, QBTS, QUBT, RGTI) | group_move | up | +0.26 | +1.97 | +1.51 |
| 10:49 | Space (LUNR, ASTS, PL, RKLB, IRDM) | group_move | up | +0.08 | +1.37 | +1.73 |
| 10:50 | LUNR | relative_to_spy | up | -0.88 | -0.37 | +0.14 |
| 10:50 | Bitcoin treasuries and miners (IREN, RIOT, MARA, CLSK, MSTR, COIN) | group_move | up | -0.47 | +1.60 | +0.68 |
| 10:50 | Memory and storage (SNDK, MU, STX, WDC) | group_move | up | -1.02 | +1.50 | +1.49 |
| 10:51 | AAOI | relative_to_spy | up | -0.50 | +1.33 | +1.63 |
| 10:51 | CIFR | relative_to_spy | up | -1.15 | +1.20 | +0.61 |
| 10:55 | Cloud software and data (SNOW, MDB, ORCL, DDOG, NOW) | group_move | up | +2.08 | +1.11 | +1.89 |
| 10:55 | Neoclouds and AI hosting (IREN, CIFR, ORCL, NBIS, APLD, CRWV, WULF) | group_move | up | +1.01 | +1.55 | +1.64 |
| 11:11 | AI software and analytics (DDOG, SNOW, APP, PLTR, AI, NOW) | group_move | up | +0.98 | +0.37 | +0.57 |
| 11:11 | Cybersecurity (NET, ZS, CRWD, PANW, FTNT, S) | group_move | up | -0.15 | -0.01 | -0.11 |
| 11:49 | AI networking and connectivity (ALAB, COHR, CRDO, MRVL, ANET, AVGO) | group_move | up | -0.45 | -0.16 | -0.77 |
| 13:40 | LCID | relative_to_spy | up | +11.93 | +8.90 | +11.13 |
| 14:36 | LCID | relative_to_spy | down | -1.81 | +1.81 | — |

### Movers flags (53)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | CRM | leaders | up | +1.42 | +1.19 | +2.57 |
| 09:31 | HPQ | leaders | up | -0.71 | +1.28 | +1.83 |
| 09:31 | NOW | leaders | up | +0.14 | +1.21 | +2.71 |
| 09:31 | IBM | leaders | up | -2.05 | -1.99 | +1.31 |
| 09:31 | CPRT | leaders | up | +0.20 | +1.14 | +0.34 |
| 09:31 | ADBE | leaders | up | +1.84 | +2.65 | +3.45 |
| 09:31 | AMGN | leaders | up | +2.18 | +3.16 | +1.56 |
| 09:31 | HD | leaders | up | +1.42 | +0.88 | +0.23 |
| 09:31 | LLY | leaders | up | -0.19 | +0.31 | -0.90 |
| 09:31 | COST | leaders | up | +1.42 | +1.41 | +0.27 |
| 09:31 | CNC | laggards | down | +2.99 | +3.00 | +7.27 |
| 09:31 | AAOI | laggards | down | -5.77 | -6.90 | -2.59 |
| 09:31 | SNDK | laggards | down | -5.48 | -6.69 | -6.69 |
| 09:31 | WDC | laggards | down | -6.33 | -7.11 | -4.77 |
| 09:31 | STX | laggards | down | -5.66 | -5.90 | -4.54 |
| 09:31 | COHR | laggards | down | -5.93 | -8.46 | -6.37 |
| 09:31 | CIEN | laggards | down | -3.89 | -5.76 | -3.78 |
| 09:31 | MU | laggards | down | -3.02 | -4.15 | -3.03 |
| 09:31 | CIFR | laggards | down | -4.64 | -3.83 | -0.21 |
| 09:31 | ALAB | laggards | down | -3.07 | -4.29 | -1.77 |
| 09:32 | PYPL | leaders | up | +0.23 | +0.29 | +0.84 |
| 09:32 | DASH | leaders | up | -1.39 | -0.28 | +1.41 |
| 09:32 | NFLX | leaders | up | +1.70 | +1.77 | +0.74 |
| 09:32 | JD | leaders | up | +0.63 | +1.44 | -0.15 |
| 09:32 | DECK | leaders | up | +1.01 | +1.48 | +2.17 |
| 09:32 | DELL | laggards | down | -6.90 | -5.21 | -3.54 |
| 09:32 | MARA | laggards | down | +0.22 | -0.54 | +3.73 |
| 09:33 | LOW | leaders | up | +0.55 | +0.56 | -0.48 |
| 09:34 | LUNR | laggards | down | -0.85 | -0.50 | +2.91 |
| 09:35 | FND | leaders | up | +0.65 | +0.95 | +1.02 |
| 09:35 | QBTS | laggards | down | -1.75 | -2.31 | +1.00 |
| 09:41 | CRDO | laggards | down | +0.61 | -0.46 | +2.59 |
| 09:42 | HSAI | leaders | up | +0.08 | -0.08 | +0.61 |
| 09:43 | PFE | leaders | up | -0.49 | -0.62 | -1.25 |
| 09:47 | WMT | leaders | up | +0.09 | +0.19 | -1.95 |
| 09:47 | NBIS | laggards | down | -2.86 | -2.72 | +1.82 |
| 09:53 | TGT | leaders | up | +0.86 | +0.44 | -0.82 |
| 10:10 | LCID | leaders | up | -1.25 | -1.72 | -1.58 |
| 10:10 | IONQ | laggards | down | +1.71 | +3.63 | +4.32 |
| 10:21 | MRVL | laggards | down | +3.83 | +4.68 | +5.43 |
| 10:40 | FLNC | laggards | down | +0.32 | +1.80 | +2.65 |
| 10:52 | SNAP | leaders | up | +0.14 | -0.84 | +0.26 |
| 11:10 | ZS | leaders | up | +0.04 | -0.18 | -0.07 |
| 11:31 | RBLX | leaders | up | -1.65 | -1.92 | -1.76 |
| 11:40 | AI | leaders | up | -2.00 | -1.98 | -2.03 |
| 11:48 | GM | leaders | up | -0.24 | +0.14 | -0.67 |
| 11:56 | WULF | laggards | down | -0.42 | +0.56 | -0.50 |
| 12:01 | ARM | laggards | down | -0.80 | +0.43 | -0.80 |
| 15:01 | CI | leaders | up | +0.42 | — | — |
| 15:46 | TDOC | leaders | up | — | — | — |
| 15:47 | AMD | laggards | down | — | — | — |
| 15:52 | LAD | leaders | up | — | — | — |
| 15:57 | U | leaders | up | — | — | — |

## 2026-07-29

Usable symbol-minutes 65,071/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | LAD | +20.84 | miss | 09:33 |
| 2 | HIMS | -13.20 | 12:45 | 09:31 |
| 3 | RIOT | -12.59 | 15:46 | 09:45 |
| 4 | IREN | -12.08 | 15:48 | 09:46 |
| 5 | CIFR | -11.83 | 10:02 | 09:32 |
| 6 | AAOI | -11.64 | miss | 09:40 |
| 7 | APLD | -11.23 | miss | 09:40 |
| 8 | NBIS | -11.11 | 10:02 | 09:37 |
| 9 | WULF | -10.16 | miss | 09:34 |
| 10 | MARA | -10.15 | miss | 10:35 |
| 11 | CLSK | -9.37 | miss | 09:31 |
| 12 | MU | -8.40 | miss | miss |
| 13 | SMCI | -8.13 | miss | 09:31 |
| 14 | CRWV | -8.09 | miss | 09:38 |
| 15 | RCAT | -7.59 | miss | 09:32 |
| 16 | RGTI | -7.41 | miss | 13:40 |
| 17 | SOFI | -7.36 | miss | 09:31 |
| 18 | ADBE | +7.26 | 10:07 | 09:52 |
| 19 | COHR | -7.21 | miss | 12:31 |
| 20 | DDOG | +6.85 | miss | 09:31 |

### Radar flags (32)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | CIFR | relative_to_spy | down | -1.02 | -1.55 | -3.97 |
| 10:02 | HUM | relative_to_spy | down | -0.78 | +0.15 | +0.18 |
| 10:02 | LCID | relative_to_spy | up | -1.67 | -4.57 | -3.00 |
| 10:02 | NBIS | relative_to_spy | down | -2.03 | -1.66 | -4.26 |
| 10:02 | Neoclouds and AI hosting (NBIS, CIFR, APLD, IREN, WULF, CRWV) | group_move | down | -2.18 | -2.29 | -4.54 |
| 10:04 | Big banks (GS, MS, C, WFC, JPM, BAC) | group_move | down | +0.65 | +1.10 | +0.39 |
| 10:04 | Memory and storage (SNDK, MU, WDC, STX) | group_move | down | -1.14 | -1.33 | -2.51 |
| 10:05 | Bitcoin treasuries and miners (IREN, RIOT, CLSK, MARA) | group_move | down | -2.52 | -2.30 | -5.22 |
| 10:07 | ADBE | relative_to_sector | up | +0.27 | +1.35 | +2.18 |
| 10:33 | AI networking and connectivity (CRDO, ALAB, MRVL, COHR, AVGO, ANET) | group_move | down | +0.30 | -0.90 | -1.76 |
| 10:42 | Space (PL, LUNR, RKLB, ASTS) | group_move | down | +0.22 | -0.92 | -1.18 |
| 10:43 | Quantum computing (RGTI, QBTS, QUBT, IONQ) | group_move | down | +0.78 | +0.53 | +0.23 |
| 12:45 | HIMS | relative_to_spy | down | +0.26 | +1.04 | +0.15 |
| 12:49 | NBIS | relative_to_spy | up | +2.55 | +1.90 | +2.53 |
| 13:09 | Memory and storage (STX, WDC, SNDK, MU) | group_move | up | +0.10 | +1.53 | +2.56 |
| 14:38 | Neoclouds and AI hosting (NBIS, CIFR, IREN, WULF, CRWV, APLD, ORCL) | group_move | down | +1.61 | -1.52 | — |
| 14:53 | Quantum computing (IONQ, RGTI, QUBT, QBTS) | group_move | up | -1.05 | -3.90 | — |
| 14:55 | AI networking and connectivity (ALAB, CRDO, MRVL, COHR, ANET, AVGO) | group_move | up | -1.07 | -2.88 | — |
| 14:58 | ALAB | relative_to_spy | up | -2.20 | -5.82 | — |
| 14:58 | Neoclouds and AI hosting (APLD, CIFR, NBIS, IREN, CRWV, WULF, ORCL) | group_move | up | -3.11 | -4.49 | — |
| 14:58 | Space (RKLB, ASTS, LUNR, PL) | group_move | up | -2.63 | -4.39 | — |
| 15:00 | SNDK | relative_to_spy | up | -3.94 | -7.22 | — |
| 15:23 | Memory and storage (SNDK, MU, STX, WDC) | group_move | down | -1.89 | — | — |
| 15:23 | Neoclouds and AI hosting (NBIS, APLD, IREN, WULF, CIFR, CRWV, ORCL) | group_move | down | -2.64 | — | — |
| 15:28 | Space (ASTS, RKLB, LUNR, PL, IRDM) | group_move | down | -1.59 | — | — |
| 15:30 | Quantum computing (IONQ, RGTI, QBTS, QUBT) | group_move | down | -2.48 | — | — |
| 15:34 | SNDK | relative_to_spy | down | — | — | — |
| 15:34 | AI networking and connectivity (ALAB, MRVL, CRDO, COHR, ANET, AVGO) | group_move | down | — | — | — |
| 15:36 | NBIS | relative_to_spy | down | — | — | — |
| 15:46 | RIOT | relative_to_spy | down | — | — | — |
| 15:47 | Crypto and exchanges (RIOT, MARA, MSTR, CRCL, COIN, HOOD, BULL) | group_move | down | — | — | — |
| 15:48 | IREN | relative_to_spy | down | — | — | — |

### Movers flags (56)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | SNOW | leaders | up | -1.38 | -1.64 | -2.13 |
| 09:31 | HSAI | leaders | up | +1.17 | -0.08 | -3.08 |
| 09:31 | STX | leaders | up | -1.21 | -2.39 | -2.76 |
| 09:31 | OXY | leaders | up | -0.18 | +1.07 | +0.87 |
| 09:31 | XOM | leaders | up | -0.54 | +0.66 | +0.28 |
| 09:31 | MDB | leaders | up | +0.49 | -0.21 | +0.35 |
| 09:31 | COP | leaders | up | -0.01 | +0.98 | +0.74 |
| 09:31 | DDOG | leaders | up | -0.47 | -0.91 | -0.12 |
| 09:31 | F | leaders | up | +4.26 | +2.25 | +3.15 |
| 09:31 | U | leaders | up | -1.51 | -3.56 | -3.55 |
| 09:31 | SOFI | laggards | down | -2.35 | -3.05 | -1.05 |
| 09:31 | CAT | laggards | down | +0.41 | -0.05 | -1.91 |
| 09:31 | LCID | laggards | down | +6.66 | +4.54 | +2.35 |
| 09:31 | QBTS | laggards | down | -1.04 | -2.13 | -2.73 |
| 09:31 | UAA | laggards | down | +1.40 | -1.47 | -0.28 |
| 09:31 | CLSK | laggards | down | -1.58 | -5.87 | -6.76 |
| 09:31 | SMCI | laggards | down | -0.69 | -1.70 | -3.22 |
| 09:31 | DECK | laggards | down | +1.72 | +0.42 | +1.32 |
| 09:31 | HIMS | laggards | down | -0.36 | -3.22 | -2.31 |
| 09:31 | CRDO | laggards | down | -2.00 | -4.30 | -3.29 |
| 09:32 | RDDT | leaders | up | +0.23 | -2.12 | -1.18 |
| 09:32 | CIFR | laggards | down | -5.51 | -6.46 | -8.30 |
| 09:32 | ARM | laggards | down | -1.07 | -3.10 | -2.88 |
| 09:32 | RCAT | laggards | down | -1.54 | -3.55 | -4.51 |
| 09:33 | LAD | leaders | up | +9.02 | +8.66 | +10.76 |
| 09:33 | WDC | leaders | up | -2.83 | -2.52 | -2.87 |
| 09:33 | DE | laggards | down | +0.13 | -0.79 | — |
| 09:33 | CNC | laggards | down | +1.60 | +1.98 | +1.62 |
| 09:34 | FLNC | leaders | up | -1.41 | -3.91 | -4.16 |
| 09:34 | WULF | laggards | down | -2.22 | -4.34 | -4.69 |
| 09:35 | FND | laggards | down | — | +0.42 | +0.51 |
| 09:36 | HPQ | laggards | down | +3.83 | +4.23 | +3.68 |
| 09:37 | ASTS | leaders | up | -0.21 | -2.18 | -4.01 |
| 09:37 | NBIS | laggards | down | -3.97 | -5.33 | -6.83 |
| 09:38 | SNDK | laggards | down | -1.05 | -4.06 | -3.15 |
| 09:38 | CRWV | laggards | down | -0.87 | -2.39 | -4.65 |
| 09:40 | APLD | laggards | down | -2.35 | -5.27 | -5.98 |
| 09:40 | AAOI | laggards | down | -1.17 | -4.09 | -5.33 |
| 09:41 | HUM | laggards | down | -1.27 | -1.10 | — |
| 09:45 | RIOT | laggards | down | -2.02 | -2.71 | -4.93 |
| 09:46 | AN | leaders | up | +1.03 | +0.73 | +1.58 |
| 09:46 | IREN | laggards | down | -2.04 | -5.18 | -6.19 |
| 09:52 | ADBE | leaders | up | +0.68 | +2.30 | +3.15 |
| 09:53 | KMX | leaders | up | -0.16 | +0.43 | +1.24 |
| 09:54 | LCID | leaders | up | -1.63 | -4.81 | -4.79 |
| 10:02 | NOW | leaders | up | -0.19 | -0.33 | +2.03 |
| 10:06 | GS | laggards | down | -0.01 | +0.59 | -0.41 |
| 10:13 | SHEL | leaders | up | +0.53 | +0.30 | +0.59 |
| 10:21 | SONY | leaders | up | -0.28 | -0.03 | +0.13 |
| 10:35 | MARA | laggards | down | +0.93 | -1.17 | -1.20 |
| 10:41 | CVX | leaders | up | -0.57 | -0.28 | -0.19 |
| 11:21 | CRM | leaders | up | +0.74 | +0.96 | +0.13 |
| 12:31 | PDD | leaders | up | -0.29 | -0.43 | +0.35 |
| 12:31 | COHR | laggards | down | -0.26 | +0.15 | -0.17 |
| 13:40 | RGTI | laggards | down | +1.85 | +0.81 | -0.97 |
| 14:38 | NET | leaders | up | +0.18 | -0.37 | — |

## 2026-07-30

Usable symbol-minutes 64,960/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | TDOC | -30.00 | 10:02 | 09:31 |
| 2 | IREN | +28.86 | 10:02 | 09:31 |
| 3 | CIFR | +26.39 | 10:02 | 09:31 |
| 4 | NBIS | +25.45 | 10:02 | 09:31 |
| 5 | SNDK | +24.32 | 10:02 | 09:31 |
| 6 | CRWV | +19.83 | 10:02 | 09:31 |
| 7 | RIOT | +19.60 | 10:02 | 09:35 |
| 8 | CLSK | +19.39 | 10:02 | 09:45 |
| 9 | APLD | +18.78 | 10:02 | 09:31 |
| 10 | ALAB | +18.32 | miss | 09:31 |
| 11 | MU | +16.68 | 10:02 | 13:32 |
| 12 | WULF | +16.41 | 10:02 | 09:31 |
| 13 | AAOI | +16.08 | 10:02 | 10:36 |
| 14 | MARA | +15.94 | 10:02 | 09:53 |
| 15 | MSFT | +13.83 | miss | 09:33 |
| 16 | WDC | +13.69 | miss | 09:32 |
| 17 | CRDO | +11.64 | miss | miss |
| 18 | FLNC | +11.61 | 10:04 | miss |
| 19 | AMD | +11.32 | 10:05 | miss |
| 20 | CIEN | +10.95 | miss | miss |

### Radar flags (27)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | AAOI | relative_to_spy | up | +0.75 | -1.74 | +1.02 |
| 10:02 | APLD | relative_to_spy | up | -1.16 | -1.87 | -0.63 |
| 10:02 | ARM | relative_to_spy | down | +1.39 | +0.57 | -1.94 |
| 10:02 | CIFR | relative_to_spy | up | -0.19 | -1.43 | +0.03 |
| 10:02 | CLSK | relative_to_spy | up | -2.08 | -1.83 | -1.83 |
| 10:02 | CRWV | relative_to_spy | up | +1.75 | -0.50 | +2.41 |
| 10:02 | HIMS | relative_to_spy | up | +1.55 | +0.02 | +1.54 |
| 10:02 | IREN | relative_to_spy | up | +0.15 | -0.86 | +0.80 |
| 10:02 | MARA | relative_to_spy | up | -1.43 | -2.02 | -1.29 |
| 10:02 | MU | relative_to_spy | up | +2.59 | +0.39 | +2.01 |
| 10:02 | NBIS | relative_to_spy | up | +1.40 | -1.33 | -0.45 |
| 10:02 | OKLO | relative_to_spy | up | +1.27 | +0.11 | +0.59 |
| 10:02 | RIOT | relative_to_spy | up | -2.54 | -2.93 | -0.37 |
| 10:02 | SNDK | relative_to_spy | up | +1.43 | +0.50 | +1.71 |
| 10:02 | TDOC | relative_to_spy | down | -2.48 | -1.25 | +0.67 |
| 10:02 | WULF | relative_to_spy | up | +1.12 | +0.13 | +2.40 |
| 10:02 | NOW | relative_to_sector | down | -0.91 | +0.74 | +0.94 |
| 10:02 | Bitcoin treasuries and miners (MARA, CLSK, IREN, RIOT, MSTR, COIN) | group_move | up | -1.23 | -1.64 | -0.64 |
| 10:02 | Memory and storage (SNDK, MU, WDC) | group_move | up | +1.71 | +0.03 | +0.58 |
| 10:02 | Neoclouds and AI hosting (IREN, NBIS, APLD, CIFR, CRWV, WULF, ORCL) | group_move | up | +0.54 | -0.90 | +0.47 |
| 10:02 | Quantum computing (RGTI, IONQ, QBTS, QUBT) | group_move | up | +0.81 | -0.45 | +0.56 |
| 10:03 | Space (RKLB, ASTS, LUNR, IRDM, PL) | group_move | up | +0.21 | -0.92 | -1.08 |
| 10:04 | FLNC | relative_to_spy | up | -0.75 | -0.99 | -0.96 |
| 10:05 | AMD | relative_to_spy | up | +2.67 | +1.12 | +0.31 |
| 10:40 | AI networking and connectivity (ALAB, COHR, CRDO, MRVL, ANET, AVGO) | group_move | up | +0.21 | -0.44 | -0.86 |
| 11:02 | Memory and storage (STX, MU, WDC, SNDK) | group_move | down | +0.08 | -0.01 | -0.22 |
| 12:50 | Neoclouds and AI hosting (APLD, CRWV, IREN, NBIS, WULF, CIFR, ORCL) | group_move | down | +0.68 | +0.85 | -0.00 |

### Movers flags (39)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | CIFR | leaders | up | +6.31 | +5.72 | +6.22 |
| 09:31 | NBIS | leaders | up | +11.31 | +12.46 | +10.00 |
| 09:31 | ARM | leaders | up | -8.63 | -7.21 | -10.02 |
| 09:31 | IREN | leaders | up | +11.49 | +10.25 | +10.26 |
| 09:31 | STX | leaders | up | +1.14 | +0.85 | -3.02 |
| 09:31 | CRWV | leaders | up | +5.95 | +6.82 | +7.44 |
| 09:31 | ALAB | leaders | up | -0.36 | +1.06 | +1.85 |
| 09:31 | APLD | leaders | up | +7.07 | +6.04 | +6.08 |
| 09:31 | SNDK | leaders | up | +7.69 | +9.44 | +8.30 |
| 09:31 | WULF | leaders | up | +4.91 | +5.36 | +5.77 |
| 09:31 | TDOC | laggards | down | -10.72 | -13.32 | -11.46 |
| 09:31 | CVNA | laggards | down | +4.49 | +3.53 | +3.36 |
| 09:31 | META | laggards | down | -1.05 | -0.66 | +0.27 |
| 09:31 | CI | laggards | down | +0.65 | +1.08 | +1.85 |
| 09:31 | HPQ | laggards | down | -2.46 | -3.26 | -2.20 |
| 09:31 | QCOM | laggards | down | -0.67 | -0.60 | +0.63 |
| 09:31 | ADBE | laggards | down | -3.59 | -4.66 | -2.98 |
| 09:31 | AN | laggards | down | -2.90 | -3.37 | — |
| 09:31 | CRM | laggards | down | -2.71 | -3.55 | -1.77 |
| 09:31 | NFLX | laggards | down | -1.22 | -1.22 | +0.50 |
| 09:32 | WDC | leaders | up | +2.89 | +4.02 | +2.07 |
| 09:32 | DECK | laggards | down | -0.62 | -1.85 | -0.85 |
| 09:32 | DE | laggards | down | +1.65 | +1.57 | +1.39 |
| 09:33 | MSFT | leaders | up | +1.38 | +1.35 | +0.59 |
| 09:33 | NOW | laggards | down | -1.78 | -3.79 | -1.34 |
| 09:34 | HSAI | laggards | down | +3.58 | +3.56 | +2.89 |
| 09:35 | RIOT | leaders | up | +8.12 | +6.76 | +8.10 |
| 09:37 | NKE | laggards | down | -0.59 | -1.04 | -0.05 |
| 09:38 | LCID | laggards | down | +1.09 | -1.56 | -0.66 |
| 09:40 | LAD | laggards | down | -2.92 | -2.56 | -3.10 |
| 09:45 | CLSK | leaders | up | +3.03 | +3.26 | +3.97 |
| 09:53 | MARA | leaders | up | -0.76 | -0.06 | -0.10 |
| 09:53 | ZS | laggards | down | -1.85 | -1.51 | -1.18 |
| 09:54 | CPRT | laggards | down | -1.34 | -1.50 | -1.02 |
| 10:02 | UAA | laggards | down | -1.20 | -1.19 | -0.43 |
| 10:36 | AAOI | leaders | up | -0.67 | -0.49 | -1.68 |
| 13:32 | MU | leaders | up | +0.24 | -0.15 | +0.27 |
| 13:37 | RBLX | laggards | down | +0.42 | +0.02 | +0.47 |
| 15:25 | LLY | laggards | down | -0.36 | — | — |

## 2026-07-31

Usable symbol-minutes 65,118/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | RBLX | -27.57 | 10:02 | 09:31 |
| 2 | RDDT | -21.71 | 10:11 | 09:31 |
| 3 | AMZN | +14.60 | miss | 09:31 |
| 4 | COIN | -11.31 | miss | 09:31 |
| 5 | RIVN | -10.29 | miss | 09:33 |
| 6 | LCID | -9.83 | miss | 10:49 |
| 7 | RIOT | -9.54 | 10:02 | 12:05 |
| 8 | NVO | -9.50 | miss | 09:31 |
| 9 | AAPL | -8.07 | miss | 09:31 |
| 10 | MU | -6.62 | 10:02 | 14:13 |
| 11 | OKLO | -6.22 | miss | 15:55 |
| 12 | CLSK | -6.08 | 10:02 | 09:54 |
| 13 | GOOGL | +6.01 | miss | 10:03 |
| 14 | SNDK | -5.81 | 10:02 | 10:08 |
| 15 | U | -5.61 | miss | 09:31 |
| 16 | LAD | -5.56 | miss | 09:34 |
| 17 | MSTR | -5.28 | miss | 09:31 |
| 18 | SPOT | -5.06 | miss | 09:31 |
| 19 | MARA | -4.95 | 10:09 | miss |
| 20 | COHR | +4.83 | miss | 09:31 |

### Radar flags (36)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | AAOI | relative_to_spy | down | +0.77 | +1.49 | +0.89 |
| 10:02 | ALAB | relative_to_spy | down | +0.93 | +1.26 | -0.71 |
| 10:02 | APLD | relative_to_spy | down | -0.07 | +1.35 | -2.15 |
| 10:02 | CIFR | relative_to_spy | down | +1.37 | +1.22 | -1.35 |
| 10:02 | CLSK | relative_to_spy | down | +0.26 | +1.59 | -0.05 |
| 10:02 | CRWV | relative_to_spy | down | -1.01 | -0.25 | -2.05 |
| 10:02 | FLNC | relative_to_spy | down | +0.91 | +0.68 | -0.32 |
| 10:02 | IREN | relative_to_spy | down | -0.56 | -0.19 | -3.78 |
| 10:02 | MU | relative_to_spy | down | -0.63 | -1.48 | -3.60 |
| 10:02 | NBIS | relative_to_spy | down | +0.65 | +2.46 | -2.81 |
| 10:02 | RBLX | relative_to_spy | down | +0.53 | +0.22 | -1.28 |
| 10:02 | RIOT | relative_to_spy | down | +0.30 | -0.13 | -2.52 |
| 10:02 | SNDK | relative_to_spy | down | +0.27 | +1.11 | -0.96 |
| 10:02 | STX | relative_to_spy | down | +1.15 | +1.11 | +0.20 |
| 10:02 | WDC | relative_to_spy | down | +1.12 | +1.70 | +1.37 |
| 10:02 | AI networking and connectivity (ALAB, COHR, CRDO, MRVL, AVGO, ANET) | group_move | down | +0.06 | +0.61 | -0.25 |
| 10:02 | AI software and analytics (NOW, DDOG, AI, SNOW, PLTR) | group_move | up | -2.29 | -2.37 | -1.53 |
| 10:02 | Bitcoin treasuries and miners (CLSK, IREN, RIOT, COIN, MARA, MSTR) | group_move | down | -0.47 | -0.05 | -1.17 |
| 10:02 | Crypto and exchanges (RIOT, COIN, MARA, MSTR, CRCL, HOOD, BULL) | group_move | down | -0.71 | -0.81 | -0.99 |
| 10:02 | Memory and storage (SNDK, MU, STX, WDC) | group_move | down | +0.48 | +0.61 | -0.75 |
| 10:02 | Neoclouds and AI hosting (APLD, CIFR, IREN, NBIS, CRWV, WULF, ORCL) | group_move | down | -0.01 | +0.79 | -1.95 |
| 10:02 | Space (ASTS, LUNR, RKLB, PL, IRDM) | group_move | down | -0.96 | -0.40 | -0.92 |
| 10:03 | DDOG | relative_to_sector | up | -3.66 | -3.49 | -2.30 |
| 10:03 | GPUs and AI compute chips (AMD, MRVL, INTC, AVGO, TSM, QCOM, ARM) | group_move | down | -0.09 | -0.07 | -0.96 |
| 10:04 | NOW | relative_to_spy | up | -2.48 | -2.23 | -0.94 |
| 10:04 | Cloud software and data (NOW, CRM, MDB, DDOG, ADBE, SNOW) | group_move | up | -2.01 | -1.71 | -0.89 |
| 10:05 | ASTS | relative_to_spy | down | +0.46 | +1.26 | +0.22 |
| 10:07 | COHR | relative_to_spy | down | -0.02 | +0.46 | -1.07 |
| 10:07 | HIMS | relative_to_sector | down | +0.38 | +0.31 | -0.44 |
| 10:09 | MARA | relative_to_spy | down | +1.71 | +3.26 | +0.91 |
| 10:11 | RDDT | relative_to_spy | down | -0.12 | -0.27 | -1.07 |
| 10:16 | Gaming platforms (RBLX, APP, U, TTWO) | group_move | down | +0.62 | +0.19 | +0.50 |
| 10:27 | AI software and analytics (DDOG, APP, NOW, SNOW, PLTR, AI) | group_move | down | +0.34 | +0.37 | +0.96 |
| 10:27 | Cybersecurity (NET, ZS, PANW, S, CRWD, FTNT) | group_move | down | +0.74 | +1.04 | +1.20 |
| 10:40 | Memory and storage (STX, WDC, SNDK, MU) | group_move | up | +0.71 | -1.09 | -0.18 |
| 11:35 | NBIS | relative_to_spy | down | +0.20 | +1.01 | +2.57 |

### Movers flags (49)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | AAOI | leaders | up | -7.89 | -6.62 | -8.25 |
| 09:31 | COHR | leaders | up | -4.28 | -5.32 | -6.02 |
| 09:31 | AMZN | leaders | up | +3.07 | +3.20 | +1.95 |
| 09:31 | ALAB | leaders | up | -5.89 | -4.80 | -6.21 |
| 09:31 | FLNC | leaders | up | -5.63 | -4.95 | -6.06 |
| 09:31 | SNDK | leaders | up | -10.94 | -10.07 | -12.48 |
| 09:31 | MRVL | leaders | up | -3.16 | -2.20 | -3.61 |
| 09:31 | WDC | leaders | up | -6.00 | -4.49 | -4.60 |
| 09:31 | NBIS | leaders | up | -6.57 | -5.21 | -8.04 |
| 09:31 | APLD | leaders | up | -7.74 | -7.49 | -7.87 |
| 09:31 | RBLX | laggards | down | -11.71 | -11.00 | -13.24 |
| 09:31 | RDDT | laggards | down | -1.69 | -4.15 | -6.28 |
| 09:31 | AAPL | laggards | down | +0.13 | -0.00 | -0.08 |
| 09:31 | NVO | laggards | down | -0.66 | +0.21 | -0.00 |
| 09:31 | COIN | laggards | down | -4.16 | -5.87 | -5.97 |
| 09:31 | AN | laggards | down | -2.31 | -1.08 | +0.75 |
| 09:31 | U | laggards | down | +0.29 | -1.33 | -2.10 |
| 09:31 | MSTR | laggards | down | -2.31 | -3.38 | -2.89 |
| 09:31 | CRCL | laggards | down | -1.42 | -2.54 | -4.43 |
| 09:31 | SPOT | laggards | down | +0.17 | +0.10 | +0.45 |
| 09:32 | ARM | leaders | up | -0.52 | -2.96 | -4.32 |
| 09:32 | STX | leaders | up | -5.64 | -4.56 | -5.07 |
| 09:32 | APP | laggards | down | -0.68 | -2.00 | -1.74 |
| 09:33 | CIFR | leaders | up | -7.82 | -6.48 | -7.56 |
| 09:33 | RIVN | laggards | down | -1.77 | -4.21 | -4.46 |
| 09:34 | LAD | laggards | down | -0.07 | +0.97 | -0.24 |
| 09:35 | CRDO | leaders | up | -4.94 | -2.80 | -3.16 |
| 09:35 | CPRT | laggards | down | +1.38 | +1.24 | +1.26 |
| 09:38 | INTC | leaders | up | -3.50 | -3.28 | -4.39 |
| 09:39 | ANET | leaders | up | -1.67 | -1.46 | -1.48 |
| 09:41 | HIMS | leaders | up | -4.27 | -4.05 | -5.21 |
| 09:42 | CIEN | leaders | up | -4.00 | -3.43 | -3.83 |
| 09:49 | FND | leaders | up | -0.22 | -1.38 | -0.23 |
| 09:50 | DDOG | leaders | up | -2.56 | -4.12 | -2.77 |
| 09:52 | AI | leaders | up | -1.09 | -1.92 | -2.63 |
| 09:52 | HSAI | leaders | up | -1.13 | -1.23 | -2.83 |
| 09:54 | CLSK | laggards | down | +0.53 | +1.55 | -0.40 |
| 09:57 | BABA | leaders | up | +1.28 | +1.23 | +1.31 |
| 10:03 | GOOGL | leaders | up | +0.46 | +1.91 | +1.36 |
| 10:08 | SNDK | laggards | down | +2.19 | +4.59 | +1.10 |
| 10:09 | IREN | laggards | down | +1.99 | +2.69 | -2.07 |
| 10:37 | TDOC | leaders | up | -2.28 | -2.67 | -2.52 |
| 10:49 | LCID | laggards | down | -1.51 | -2.31 | -1.59 |
| 11:27 | FTNT | leaders | up | +0.47 | -0.42 | +0.82 |
| 12:05 | RIOT | laggards | down | -0.42 | -0.80 | +0.79 |
| 12:26 | BIDU | leaders | up | -0.57 | -0.56 | -0.64 |
| 14:13 | MU | laggards | down | +0.31 | +0.36 | — |
| 15:55 | OKLO | laggards | down | — | — | — |
| 15:58 | S | leaders | up | — | — | — |

## 2026-08-03

Usable symbol-minutes 64,928/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | CRWV | +18.07 | 10:02 | 09:45 |
| 2 | AAOI | +15.42 | 10:02 | 10:09 |
| 3 | NBIS | +10.22 | 10:02 | 09:59 |
| 4 | HIMS | +9.56 | 10:02 | 09:38 |
| 5 | SOFI | +9.12 | miss | 10:07 |
| 6 | QBTS | +9.08 | 10:02 | 09:38 |
| 7 | RDDT | +8.56 | miss | 11:08 |
| 8 | RCAT | +8.27 | miss | 15:13 |
| 9 | COHR | +8.18 | 10:02 | 10:31 |
| 10 | ORCL | +7.80 | miss | 09:37 |
| 11 | RKLB | +7.01 | 10:02 | 11:53 |
| 12 | CIFR | +6.82 | 10:02 | 10:01 |
| 13 | IREN | +6.59 | 10:02 | 10:19 |
| 14 | QUBT | +6.48 | miss | miss |
| 15 | ASTS | +6.27 | 10:02 | 10:26 |
| 16 | APLD | +6.24 | 10:02 | 10:16 |
| 17 | SNAP | +6.04 | miss | 09:31 |
| 18 | RGTI | +5.73 | miss | 10:18 |
| 19 | WULF | +5.20 | 10:02 | miss |
| 20 | IONQ | +5.19 | 10:02 | 09:52 |

### Radar flags (28)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | AAOI | relative_to_spy | up | +5.87 | +7.33 | +8.79 |
| 10:02 | APLD | relative_to_spy | up | +2.45 | +3.47 | +3.50 |
| 10:02 | ASTS | relative_to_spy | up | +1.70 | +2.58 | +4.98 |
| 10:02 | CIFR | relative_to_spy | up | +2.33 | +2.81 | +4.28 |
| 10:02 | CLSK | relative_to_spy | up | +1.39 | +3.78 | +3.13 |
| 10:02 | COHR | relative_to_spy | up | +4.93 | +6.78 | +7.34 |
| 10:02 | CRWV | relative_to_spy | up | -0.27 | +2.00 | +3.27 |
| 10:02 | HIMS | relative_to_spy | up | +1.37 | +2.03 | +3.71 |
| 10:02 | IONQ | relative_to_spy | up | +1.48 | +2.95 | +2.50 |
| 10:02 | IREN | relative_to_spy | up | +0.75 | +1.37 | +1.04 |
| 10:02 | LUNR | relative_to_spy | up | +0.54 | +1.91 | +2.83 |
| 10:02 | NBIS | relative_to_spy | up | +1.65 | +4.65 | +5.46 |
| 10:02 | QBTS | relative_to_spy | up | +2.34 | +3.29 | +3.18 |
| 10:02 | RIOT | relative_to_spy | up | +2.33 | +3.06 | +2.33 |
| 10:02 | RKLB | relative_to_spy | up | +0.94 | +2.63 | +4.18 |
| 10:02 | SNDK | relative_to_spy | up | +3.26 | +3.67 | +3.68 |
| 10:02 | WULF | relative_to_spy | up | +0.45 | +1.04 | +1.13 |
| 10:02 | Bitcoin treasuries and miners (IREN, RIOT, CLSK, MARA, MSTR, COIN) | group_move | up | +1.49 | +2.55 | +1.79 |
| 10:02 | Crypto and exchanges (RIOT, MARA, HOOD, MSTR, COIN, BULL, CRCL) | group_move | up | +1.24 | +1.87 | +1.43 |
| 10:02 | Neoclouds and AI hosting (NBIS, CRWV, CIFR, APLD, IREN, WULF, ORCL) | group_move | up | +0.82 | +2.03 | +2.59 |
| 10:02 | Quantum computing (IONQ, QBTS, RGTI, QUBT) | group_move | up | +1.77 | +3.26 | +3.05 |
| 10:02 | Space (ASTS, RKLB, LUNR, PL) | group_move | up | +1.35 | +2.64 | +3.99 |
| 10:14 | MARA | relative_to_spy | up | +0.52 | +0.12 | +0.45 |
| 10:19 | Cloud software and data (NOW, ADBE, MDB, DDOG, CRM, SNOW, ORCL) | group_move | down | -0.20 | +0.22 | +0.38 |
| 10:23 | GPUs and AI compute chips (MRVL, AMD, NVDA, ARM, QCOM, INTC, AVGO, TSM) | group_move | up | +1.75 | +1.29 | +1.44 |
| 10:24 | AI networking and connectivity (COHR, MRVL, CRDO, ALAB, ANET, AVGO) | group_move | up | +2.78 | +2.06 | +3.42 |
| 10:25 | Memory and storage (SNDK, MU, STX, WDC) | group_move | up | +2.12 | +0.27 | +1.66 |
| 11:03 | LCID | relative_to_sector | up | -3.39 | -3.74 | -4.33 |

### Movers flags (70)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | U | leaders | up | +0.61 | -0.60 | -1.67 |
| 09:31 | ONON | leaders | up | -0.71 | -0.61 | -0.96 |
| 09:31 | APP | leaders | up | -1.37 | -1.86 | -2.29 |
| 09:31 | LULU | leaders | up | -1.09 | -2.18 | -2.29 |
| 09:31 | NOW | leaders | up | +2.71 | +0.07 | -1.07 |
| 09:31 | UAA | leaders | up | -1.01 | -1.79 | -1.32 |
| 09:31 | BABA | leaders | up | +1.17 | +0.89 | +1.08 |
| 09:31 | SNAP | leaders | up | +1.48 | +0.61 | +1.43 |
| 09:31 | ADBE | leaders | up | -0.40 | -2.22 | -2.41 |
| 09:31 | CRM | leaders | up | +0.86 | -1.05 | -1.12 |
| 09:31 | ARM | laggards | down | +3.01 | +5.34 | +5.40 |
| 09:31 | NBIS | laggards | down | +15.49 | +16.30 | +19.90 |
| 09:31 | STX | laggards | down | +0.51 | +1.08 | +0.09 |
| 09:31 | ALAB | laggards | down | +3.96 | +4.66 | +6.43 |
| 09:31 | SNDK | laggards | down | +6.54 | +8.98 | +8.74 |
| 09:31 | AAOI | laggards | down | +12.34 | +17.14 | +19.05 |
| 09:31 | CRCL | laggards | down | +0.64 | +0.65 | +1.04 |
| 09:31 | MU | laggards | down | +2.18 | +4.06 | +3.37 |
| 09:31 | WDC | laggards | down | -0.05 | +0.53 | -0.42 |
| 09:31 | CRDO | laggards | down | +2.32 | +3.25 | +5.32 |
| 09:32 | MSFT | leaders | up | +1.06 | -0.34 | +0.07 |
| 09:32 | AMZN | leaders | up | +0.34 | +0.70 | +0.53 |
| 09:32 | TGT | leaders | up | -1.35 | -1.09 | -1.65 |
| 09:32 | FND | leaders | up | -2.86 | -5.29 | -6.36 |
| 09:32 | CIEN | laggards | down | +2.24 | +4.54 | +5.45 |
| 09:35 | DECK | leaders | up | -1.45 | -2.47 | -2.69 |
| 09:35 | MRVL | laggards | down | +1.45 | +5.48 | +5.02 |
| 09:36 | SNOW | leaders | up | +1.12 | +1.11 | +1.89 |
| 09:36 | INTC | laggards | down | +1.04 | +3.46 | +3.44 |
| 09:37 | ORCL | leaders | up | +1.14 | +0.13 | +0.68 |
| 09:37 | OXY | laggards | down | +0.46 | +0.86 | +0.94 |
| 09:37 | COIN | laggards | down | +1.95 | +3.33 | +4.36 |
| 09:38 | HIMS | leaders | up | +3.42 | +3.61 | +4.62 |
| 09:38 | QBTS | leaders | up | +2.26 | +4.59 | +4.61 |
| 09:39 | ANET | laggards | down | +0.70 | +2.17 | +2.62 |
| 09:40 | MDB | leaders | up | -1.04 | -1.04 | +0.71 |
| 09:42 | AMD | laggards | down | +2.43 | +4.13 | +3.90 |
| 09:44 | GOOGL | leaders | up | -1.11 | -1.41 | +0.09 |
| 09:45 | CRWV | leaders | up | +3.70 | +5.28 | +7.85 |
| 09:45 | S | leaders | up | -1.81 | -1.90 | -1.47 |
| 09:48 | META | leaders | up | +0.82 | +0.11 | +0.78 |
| 09:52 | IONQ | leaders | up | +1.36 | +3.48 | +2.73 |
| 09:57 | LLY | laggards | down | +0.92 | +0.51 | +0.37 |
| 09:59 | NBIS | leaders | up | +2.25 | +5.40 | +6.26 |
| 09:59 | AVGO | laggards | down | +0.33 | +2.16 | +2.07 |
| 10:01 | CIFR | leaders | up | +1.63 | +2.37 | +3.62 |
| 10:02 | QCOM | laggards | down | +2.23 | +3.64 | +3.61 |
| 10:07 | SOFI | leaders | up | +0.13 | -0.14 | +1.18 |
| 10:09 | AAOI | leaders | up | +4.96 | +5.02 | +6.30 |
| 10:16 | APLD | leaders | up | +0.91 | +1.78 | +2.67 |
| 10:18 | RGTI | leaders | up | +1.68 | +1.91 | +1.49 |
| 10:19 | IREN | leaders | up | +0.73 | -0.63 | +1.37 |
| 10:22 | SONY | laggards | down | -0.78 | -0.76 | -0.86 |
| 10:25 | COP | laggards | down | +0.12 | +0.44 | +0.36 |
| 10:26 | ASTS | leaders | up | +1.51 | +1.17 | +3.18 |
| 10:30 | MRK | laggards | down | -0.21 | -0.59 | -0.87 |
| 10:31 | COHR | leaders | up | +2.27 | +1.35 | +1.94 |
| 10:36 | FND | laggards | down | -0.94 | -0.34 | -0.48 |
| 10:48 | NVO | laggards | down | +0.67 | +0.75 | +0.54 |
| 10:49 | AMGN | laggards | down | +0.76 | +0.22 | -0.67 |
| 11:05 | AAPL | laggards | down | -0.45 | -0.31 | +0.52 |
| 11:07 | TDOC | laggards | down | -0.12 | +0.71 | +0.62 |
| 11:08 | RDDT | leaders | up | +0.40 | +0.50 | +1.53 |
| 11:53 | RKLB | leaders | up | -0.37 | -1.64 | -0.89 |
| 12:06 | SPOT | laggards | down | -0.26 | -0.60 | -1.06 |
| 12:30 | GM | laggards | down | -0.28 | -0.16 | +0.18 |
| 12:39 | F | laggards | down | +0.25 | +0.05 | +0.02 |
| 13:41 | CVX | laggards | down | -0.52 | -0.60 | -0.66 |
| 15:13 | RCAT | leaders | up | +0.66 | — | — |
| 15:51 | LAD | laggards | down | — | — | — |

## 2026-08-04

Usable symbol-minutes 64,908/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | PLTR | +27.65 | miss | 09:31 |
| 2 | AAOI | +17.63 | miss | 09:31 |
| 3 | CIFR | -17.45 | 15:39 | 09:31 |
| 4 | ARM | +15.56 | miss | 09:31 |
| 5 | SNAP | +13.08 | miss | 09:31 |
| 6 | MRVL | +11.00 | miss | 09:31 |
| 7 | ALAB | +10.85 | miss | 09:31 |
| 8 | COHR | +10.55 | miss | 09:31 |
| 9 | SNDK | +9.03 | miss | 09:43 |
| 10 | INTC | +9.03 | miss | 09:54 |
| 11 | ASTS | +8.89 | miss | 09:31 |
| 12 | SMCI | +8.85 | miss | 13:58 |
| 13 | NVO | -7.77 | 12:47 | 12:44 |
| 14 | QBTS | +7.46 | miss | miss |
| 15 | CRDO | +7.16 | miss | 09:31 |
| 16 | RGTI | +7.12 | miss | 14:34 |
| 17 | DELL | +7.11 | miss | 10:13 |
| 18 | FLNC | +5.82 | miss | miss |
| 19 | MU | +5.81 | miss | 11:34 |
| 20 | IONQ | +5.58 | miss | miss |

### Radar flags (10)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | CAT | relative_to_spy | down | -1.99 | -1.45 | -1.53 |
| 10:02 | CMI | relative_to_sector | up | -0.59 | +0.03 | +1.85 |
| 10:02 | Cybersecurity (PANW, NET, S, CRWD, FTNT, ZS) | group_move | up | +0.25 | -0.65 | -0.64 |
| 10:05 | Bitcoin treasuries and miners (MARA, CLSK, COIN, RIOT, IREN, MSTR) | group_move | down | +0.54 | +2.11 | +2.07 |
| 10:06 | Crypto and exchanges (HOOD, MARA, COIN, CRCL, RIOT, BULL, MSTR) | group_move | down | +0.11 | +1.38 | +1.87 |
| 10:06 | Quantum computing (IONQ, QUBT, QBTS, RGTI) | group_move | down | +0.09 | +0.89 | +1.82 |
| 10:06 | Space (PL, ASTS, LUNR, RKLB, IRDM) | group_move | down | — | +0.45 | +0.25 |
| 10:13 | CLSK | relative_to_spy | down | +0.63 | +2.24 | +2.71 |
| 12:47 | NVO | relative_to_spy | down | -0.94 | -1.57 | -1.15 |
| 15:39 | CIFR | relative_to_spy | down | — | — | — |

### Movers flags (44)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | PLTR | leaders | up | +3.41 | +5.77 | +6.59 |
| 09:31 | AAOI | leaders | up | +0.14 | -0.79 | +1.80 |
| 09:31 | CAT | leaders | up | -5.63 | -7.16 | -6.63 |
| 09:31 | COHR | leaders | up | -0.02 | -0.55 | +1.52 |
| 09:31 | MRVL | leaders | up | +0.31 | +0.50 | +1.57 |
| 09:31 | ALAB | leaders | up | -1.50 | -0.75 | -0.58 |
| 09:31 | SNAP | leaders | up | +3.87 | +4.79 | +5.91 |
| 09:31 | CRDO | leaders | up | -2.08 | -2.68 | -1.21 |
| 09:31 | ASTS | leaders | up | -1.32 | -0.60 | +0.10 |
| 09:31 | ARM | leaders | up | +2.36 | +5.43 | +4.80 |
| 09:31 | CMI | laggards | down | +4.06 | +3.62 | +4.98 |
| 09:31 | CIFR | laggards | down | -5.85 | -4.29 | -3.89 |
| 09:31 | SPOT | laggards | down | +4.37 | +5.82 | +4.81 |
| 09:31 | NKE | laggards | down | +1.46 | +0.90 | +0.30 |
| 09:31 | CI | laggards | down | -0.11 | -0.14 | -0.51 |
| 09:31 | XOM | laggards | down | -0.25 | +0.22 | +0.18 |
| 09:31 | AMZN | laggards | down | -0.60 | -0.50 | -0.70 |
| 09:31 | OXY | laggards | down | -0.18 | +0.49 | +0.43 |
| 09:31 | HPQ | laggards | down | +2.16 | +2.76 | +3.88 |
| 09:31 | ADBE | laggards | down | +2.10 | +1.81 | +1.58 |
| 09:32 | LUNR | leaders | up | -3.62 | -2.46 | -1.46 |
| 09:32 | LCID | laggards | down | +1.91 | +2.58 | +3.30 |
| 09:32 | CLSK | laggards | down | -2.43 | -0.65 | +0.36 |
| 09:32 | CVX | laggards | down | -0.52 | -0.10 | +0.23 |
| 09:33 | COP | laggards | down | -0.02 | -0.08 | +0.29 |
| 09:37 | SHEL | laggards | down | +0.03 | -0.02 | -0.46 |
| 09:41 | F | laggards | down | -0.69 | -1.08 | -0.49 |
| 09:43 | SNDK | leaders | up | -0.37 | -1.00 | +1.96 |
| 09:47 | HUM | laggards | down | -1.15 | -1.12 | — |
| 09:54 | INTC | leaders | up | +0.54 | +1.09 | +1.28 |
| 09:57 | MARA | laggards | down | +0.10 | +1.25 | +1.76 |
| 10:12 | AMD | leaders | up | -0.20 | +0.23 | +0.62 |
| 10:13 | DELL | leaders | up | -0.44 | +0.39 | +1.59 |
| 10:23 | TDOC | laggards | down | -1.02 | -1.68 | -1.52 |
| 10:31 | UNH | laggards | down | -0.11 | -0.17 | -0.32 |
| 10:51 | LAD | laggards | down | -1.00 | -0.90 | -1.03 |
| 11:03 | META | laggards | down | +0.22 | +0.01 | -0.22 |
| 11:34 | MU | leaders | up | -0.49 | -0.46 | -0.70 |
| 11:35 | TTWO | laggards | down | +0.10 | +0.02 | -0.63 |
| 12:44 | NVO | laggards | down | -3.55 | -4.44 | -4.10 |
| 13:05 | COST | laggards | down | +0.15 | +0.27 | +0.31 |
| 13:58 | SMCI | leaders | up | -0.29 | -0.58 | +0.41 |
| 14:34 | RGTI | leaders | up | -0.42 | -1.64 | — |
| 15:20 | WBD | laggards | down | +0.71 | — | — |

## 2026-08-05

Usable symbol-minutes 64,751/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | LCID | -13.68 | 10:10 | 09:31 |
| 2 | ALAB | -11.76 | miss | 09:31 |
| 3 | FLNC | -8.99 | miss | 09:32 |
| 4 | PINS | -8.48 | miss | 09:31 |
| 5 | CIFR | -7.99 | miss | 11:13 |
| 6 | SNAP | -7.75 | miss | 09:36 |
| 7 | AMD | -6.84 | miss | 09:31 |
| 8 | CRDO | -5.39 | 10:19 | 10:20 |
| 9 | SNDK | -5.20 | miss | 10:40 |
| 10 | WDC | -5.16 | miss | 15:35 |
| 11 | UBER | -5.09 | miss | 09:31 |
| 12 | LLY | +5.06 | miss | 09:31 |
| 13 | CVS | -4.88 | miss | 09:31 |
| 14 | AMGN | +4.77 | miss | 09:32 |
| 15 | CNC | +4.76 | miss | 09:37 |
| 16 | IREN | -4.60 | miss | 14:38 |
| 17 | CLSK | -4.53 | miss | miss |
| 18 | APLD | -4.28 | miss | miss |
| 19 | MARA | -4.14 | miss | miss |
| 20 | SMCI | -4.12 | miss | 09:33 |

### Radar flags (15)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | ANET | relative_to_spy | down | +1.17 | +3.17 | +3.78 |
| 10:02 | Managed care (CNC, CVS, ELV, CI, UNH, HUM) | group_move | up | +0.13 | +0.27 | +1.32 |
| 10:08 | AAOI | relative_to_spy | up | -2.79 | -3.19 | -2.46 |
| 10:08 | RIOT | relative_to_spy | up | -3.73 | -3.48 | -4.85 |
| 10:08 | Bitcoin treasuries and miners (RIOT, COIN, MARA, CLSK, MSTR, IREN) | group_move | up | -1.94 | -1.45 | -1.85 |
| 10:08 | Crypto and exchanges (RIOT, COIN, MARA, CRCL, HOOD, MSTR, BULL) | group_move | up | -1.22 | -0.90 | -1.22 |
| 10:08 | Space (RKLB, ASTS, PL, LUNR) | group_move | up | -1.52 | -1.58 | -0.89 |
| 10:10 | LCID | relative_to_sector | down | -0.76 | -2.57 | -3.54 |
| 10:10 | Memory and storage (MU, SNDK, STX, WDC) | group_move | up | -2.13 | +0.09 | +0.59 |
| 10:19 | CRDO | relative_to_spy | down | -0.64 | -1.08 | -0.41 |
| 10:22 | AI networking and connectivity (CRDO, ALAB, ANET, MRVL, COHR) | group_move | down | -0.04 | +0.77 | +1.27 |
| 11:12 | Memory and storage (SNDK, STX, MU, WDC) | group_move | up | +0.84 | +0.39 | +0.16 |
| 12:12 | GOOGL | relative_to_spy | down | +0.96 | +1.22 | +1.27 |
| 15:45 | Memory and storage (WDC, STX, SNDK, MU) | group_move | down | — | — | — |
| 16:00 | Neoclouds and AI hosting (NBIS, WULF, CIFR, CRWV, APLD, IREN) | group_move | down | — | — | — |

### Movers flags (59)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | ANET | leaders | up | -9.08 | -8.85 | -6.24 |
| 09:31 | LLY | leaders | up | +0.02 | -2.36 | -3.26 |
| 09:31 | RIOT | leaders | up | +4.43 | +0.86 | -0.35 |
| 09:31 | DIS | leaders | up | -1.42 | -1.25 | -1.28 |
| 09:31 | SPOT | leaders | up | -0.22 | +0.57 | +0.38 |
| 09:31 | APP | leaders | up | +0.87 | +0.79 | -0.36 |
| 09:31 | NVDA | leaders | up | +1.49 | +1.31 | +1.22 |
| 09:31 | U | leaders | up | -0.47 | +0.69 | +0.80 |
| 09:31 | CVNA | leaders | up | +0.09 | +0.01 | +0.59 |
| 09:31 | GS | leaders | up | -0.40 | -0.20 | +0.35 |
| 09:31 | CVS | laggards | down | +4.85 | +3.99 | +4.40 |
| 09:31 | LCID | laggards | down | -5.03 | -4.64 | -6.43 |
| 09:31 | PINS | laggards | down | +3.66 | +3.73 | +1.46 |
| 09:31 | AMD | laggards | down | +1.64 | +0.05 | +0.56 |
| 09:31 | CRCL | laggards | down | +1.24 | +2.28 | +3.89 |
| 09:31 | ALAB | laggards | down | -2.24 | -5.38 | -4.51 |
| 09:31 | UBER | laggards | down | -1.33 | -0.78 | -1.36 |
| 09:31 | CI | laggards | down | +2.73 | +2.31 | +2.38 |
| 09:31 | ASTS | laggards | down | +0.70 | +1.26 | +2.18 |
| 09:31 | HPQ | laggards | down | +0.56 | +0.48 | +0.13 |
| 09:32 | AMGN | leaders | up | +1.45 | +2.00 | +0.20 |
| 09:32 | KMX | leaders | up | -1.38 | -2.40 | -3.05 |
| 09:32 | FLNC | laggards | down | -2.21 | -2.24 | -1.60 |
| 09:32 | UNH | laggards | down | +2.52 | +3.06 | +3.77 |
| 09:33 | LAD | leaders | up | -0.69 | — | — |
| 09:33 | NVO | leaders | up | +0.00 | +0.62 | +0.06 |
| 09:33 | SMCI | laggards | down | +0.65 | +0.34 | +1.05 |
| 09:34 | DELL | leaders | up | +0.00 | +0.07 | -1.67 |
| 09:34 | LUNR | laggards | down | -0.33 | -0.36 | -0.13 |
| 09:35 | NBIS | laggards | down | +1.98 | +0.91 | +3.41 |
| 09:36 | SNAP | laggards | down | -2.20 | -2.20 | -3.13 |
| 09:37 | CNC | leaders | up | +0.48 | +1.07 | +2.84 |
| 09:37 | RGTI | laggards | down | +1.68 | +1.18 | +1.35 |
| 09:40 | IONQ | laggards | down | +1.60 | -0.26 | +1.11 |
| 09:41 | CRWD | leaders | up | -2.18 | -2.07 | -2.22 |
| 09:42 | PANW | leaders | up | -1.54 | -1.96 | -2.82 |
| 09:43 | COHR | leaders | up | +1.59 | -1.53 | +0.06 |
| 09:46 | CRDO | leaders | up | -4.47 | -5.96 | -4.89 |
| 09:48 | CMI | leaders | up | -0.11 | -0.24 | +0.55 |
| 09:50 | MU | leaders | up | -0.19 | -0.94 | +0.20 |
| 09:54 | AAOI | leaders | up | -0.82 | -4.09 | -2.11 |
| 09:58 | RKLB | leaders | up | -0.83 | -3.22 | -1.81 |
| 10:05 | TDOC | leaders | up | +0.44 | +0.87 | -0.52 |
| 10:09 | CPRT | laggards | down | +0.85 | +1.00 | +0.82 |
| 10:19 | QUBT | laggards | down | -0.74 | -0.48 | +0.71 |
| 10:20 | CRDO | laggards | down | -0.13 | -0.38 | +0.24 |
| 10:29 | ARM | laggards | down | +0.07 | +1.78 | +3.62 |
| 10:40 | SNDK | laggards | down | +2.83 | +3.68 | +3.89 |
| 11:07 | STX | leaders | up | +1.50 | +1.30 | +0.18 |
| 11:13 | CIFR | laggards | down | +0.26 | +0.11 | -0.28 |
| 11:26 | QCOM | laggards | down | +0.24 | +0.53 | +0.42 |
| 11:44 | ELV | leaders | up | +0.71 | +0.50 | +1.09 |
| 11:51 | RDDT | laggards | down | -0.22 | -0.53 | +0.05 |
| 12:07 | GOOGL | laggards | down | -0.23 | +0.29 | +0.40 |
| 12:23 | RBLX | laggards | down | -0.36 | +1.14 | +0.42 |
| 14:38 | IREN | laggards | down | +0.28 | +0.69 | — |
| 15:34 | FND | leaders | up | — | — | — |
| 15:35 | WDC | laggards | down | — | — | — |
| 16:00 | DASH | leaders | up | — | — | — |

## 2026-08-06

Usable symbol-minutes 64,640/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | APP | -19.50 | 10:04 | 09:31 |
| 2 | DDOG | -18.87 | miss | 09:31 |
| 3 | U | +15.21 | miss | 09:32 |
| 4 | NBIS | -13.13 | miss | 09:31 |
| 5 | WDC | -12.87 | miss | 09:31 |
| 6 | QBTS | -9.12 | miss | 09:31 |
| 7 | FLNC | -7.01 | 10:52 | 09:32 |
| 8 | LUNR | +6.88 | 10:11 | 09:56 |
| 9 | SNDK | -6.65 | miss | 09:31 |
| 10 | HIMS | -6.13 | miss | 09:49 |
| 11 | CLSK | -5.40 | miss | 09:54 |
| 12 | DELL | -5.25 | miss | 09:33 |
| 13 | UAA | -5.17 | miss | 10:10 |
| 14 | MARA | -5.09 | miss | miss |
| 15 | CRWV | -4.91 | miss | 10:04 |
| 16 | ARM | +4.57 | 10:11 | 09:50 |
| 17 | LCID | +4.34 | miss | 09:33 |
| 18 | OXY | +4.30 | miss | 09:31 |
| 19 | ALAB | +4.26 | 10:25 | 09:42 |
| 20 | FND | -4.15 | miss | 11:12 |

### Radar flags (26)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | COHR | relative_to_spy | up | +4.59 | +4.70 | +2.65 |
| 10:02 | CRDO | relative_to_spy | up | +4.00 | +5.09 | +3.56 |
| 10:02 | FLNC | relative_to_spy | up | -0.73 | -1.07 | -4.57 |
| 10:02 | SNDK | relative_to_spy | up | -0.64 | +1.36 | +1.19 |
| 10:02 | STX | relative_to_spy | up | +1.67 | +1.89 | +3.34 |
| 10:02 | WDC | relative_to_spy | up | +0.80 | +3.02 | +2.95 |
| 10:02 | AI networking and connectivity (COHR, CRDO, MRVL, ALAB, ANET, AVGO) | group_move | up | +2.82 | +3.08 | +1.82 |
| 10:02 | Memory and storage (WDC, STX, SNDK, MU) | group_move | up | +1.10 | +2.39 | +2.61 |
| 10:02 | Neoclouds and AI hosting (NBIS, IREN, WULF, CIFR, ORCL, APLD) | group_move | up | +1.67 | +2.01 | +1.08 |
| 10:02 | Space (RKLB, ASTS, LUNR, PL, IRDM) | group_move | up | +4.16 | +2.84 | +1.13 |
| 10:04 | APP | relative_to_sector | down | +1.20 | +0.89 | +0.81 |
| 10:11 | ARM | relative_to_spy | up | +0.24 | +0.95 | +0.22 |
| 10:11 | LUNR | relative_to_spy | up | +3.14 | +2.91 | +1.12 |
| 10:11 | Gaming platforms (TTWO, APP, RBLX) | group_move | down | +0.58 | +0.91 | +1.06 |
| 10:14 | GPUs and AI compute chips (ARM, MRVL, AVGO, INTC, AMD, QCOM, TSM) | group_move | up | -0.02 | +0.69 | -0.42 |
| 10:15 | ASTS | relative_to_spy | up | -0.50 | -1.82 | -4.17 |
| 10:15 | RKLB | relative_to_spy | up | -0.30 | -0.88 | -2.75 |
| 10:18 | AAOI | relative_to_spy | up | -1.82 | -0.25 | -1.37 |
| 10:18 | PL | relative_to_spy | up | -0.53 | -0.50 | -2.04 |
| 10:18 | Quantum computing (QBTS, RGTI, QUBT, IONQ) | group_move | up | -0.59 | +0.32 | -1.91 |
| 10:25 | ALAB | relative_to_spy | up | -0.40 | -0.41 | -1.91 |
| 10:25 | Bitcoin treasuries and miners (IREN, RIOT, CLSK, MARA, COIN) | group_move | up | -0.31 | +0.70 | -1.38 |
| 10:26 | QBTS | relative_to_spy | up | -0.42 | +0.31 | -2.53 |
| 10:33 | Cybersecurity (NET, CRWD, PANW, ZS, S, FTNT) | group_move | up | -0.48 | -0.45 | -1.20 |
| 10:52 | FLNC | relative_to_spy | down | -0.01 | -1.90 | -3.29 |
| 11:24 | CIFR | relative_to_spy | up | -2.03 | -3.91 | -2.17 |

### Movers flags (66)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | OXY | leaders | up | +0.68 | +0.15 | -0.49 |
| 09:31 | LLY | leaders | up | -1.21 | -2.08 | -1.66 |
| 09:31 | LAD | leaders | up | -1.14 | -0.15 | -0.43 |
| 09:31 | DASH | leaders | up | -2.02 | -0.46 | -1.36 |
| 09:31 | COST | leaders | up | -1.47 | -1.91 | -1.73 |
| 09:31 | AMGN | leaders | up | -2.52 | -3.44 | -3.23 |
| 09:31 | TTWO | leaders | up | -2.42 | -3.16 | -1.97 |
| 09:31 | NVO | leaders | up | -0.12 | -0.67 | -0.87 |
| 09:31 | COP | leaders | up | -1.34 | -1.21 | -1.01 |
| 09:31 | IONQ | leaders | up | +0.02 | +1.19 | +1.57 |
| 09:31 | WDC | laggards | down | +11.22 | +11.83 | +15.34 |
| 09:31 | DDOG | laggards | down | +3.56 | +5.48 | +5.11 |
| 09:31 | APP | laggards | down | -2.46 | -2.60 | -2.44 |
| 09:31 | QBTS | laggards | down | +6.43 | +8.81 | +9.77 |
| 09:31 | SNDK | laggards | down | +6.57 | +6.34 | +10.98 |
| 09:31 | STX | laggards | down | +8.62 | +10.45 | +12.92 |
| 09:31 | NBIS | laggards | down | +4.52 | +5.09 | +4.71 |
| 09:31 | AAOI | laggards | down | +4.82 | +9.50 | +9.87 |
| 09:31 | MU | laggards | down | +3.94 | +6.57 | +8.53 |
| 09:31 | CRDO | laggards | down | +6.15 | +9.83 | +11.53 |
| 09:32 | U | leaders | up | +3.94 | +4.56 | +7.79 |
| 09:32 | SONY | leaders | up | +0.29 | +0.16 | +0.68 |
| 09:32 | OKLO | leaders | up | -4.13 | -2.26 | -0.08 |
| 09:32 | FLNC | laggards | down | +10.97 | +10.15 | +7.19 |
| 09:33 | LCID | leaders | up | -4.68 | -0.85 | -0.71 |
| 09:33 | MRK | leaders | up | -1.68 | -2.37 | -1.90 |
| 09:33 | SHEL | leaders | up | -1.04 | -0.51 | -0.00 |
| 09:33 | DELL | laggards | down | +3.04 | +5.51 | +4.26 |
| 09:34 | DIS | leaders | up | -0.76 | -1.09 | -0.06 |
| 09:35 | CRM | laggards | down | +0.24 | +0.95 | +1.49 |
| 09:36 | RBLX | leaders | up | -2.37 | -1.66 | -0.39 |
| 09:37 | ROKU | leaders | up | -0.26 | — | +0.43 |
| 09:37 | NVDA | leaders | up | -0.78 | -1.75 | -2.40 |
| 09:38 | SPOT | leaders | up | -4.43 | -3.60 | -3.52 |
| 09:40 | KMX | leaders | up | +0.93 | +1.65 | +2.13 |
| 09:42 | ALAB | leaders | up | +3.35 | +3.70 | +4.06 |
| 09:44 | WBD | leaders | up | -0.07 | -0.75 | +0.64 |
| 09:45 | TDOC | laggards | down | +0.18 | +0.81 | +0.89 |
| 09:47 | PLTR | laggards | down | +2.38 | +2.41 | +2.82 |
| 09:48 | HSAI | laggards | down | +0.44 | +0.48 | +1.58 |
| 09:49 | HIMS | laggards | down | +0.70 | -0.15 | -0.08 |
| 09:50 | ARM | leaders | up | +4.71 | +3.21 | +3.68 |
| 09:53 | MSFT | leaders | up | +0.13 | +0.30 | +0.07 |
| 09:54 | CLSK | laggards | down | +2.72 | +1.82 | +1.67 |
| 09:55 | APLD | laggards | down | +4.32 | +4.81 | +3.94 |
| 09:56 | LUNR | leaders | up | +7.71 | +6.72 | +5.23 |
| 09:56 | PYPL | leaders | up | -0.40 | -0.14 | +0.26 |
| 09:58 | RKLB | leaders | up | +3.76 | +2.62 | +1.95 |
| 09:58 | ASTS | leaders | up | +5.77 | +3.37 | +1.50 |
| 09:58 | CRWD | laggards | down | +1.25 | +1.99 | +1.98 |
| 09:59 | NET | laggards | down | +2.61 | +2.46 | +1.45 |
| 10:00 | PANW | laggards | down | +1.95 | +2.49 | +1.96 |
| 10:01 | UBER | leaders | up | -0.49 | -0.13 | +1.08 |
| 10:04 | CRWV | laggards | down | +2.52 | +1.54 | +1.09 |
| 10:07 | PL | leaders | up | +3.51 | +2.07 | +1.06 |
| 10:07 | COHR | leaders | up | +5.01 | +2.56 | +1.29 |
| 10:08 | FLNC | leaders | up | -1.52 | -3.95 | -5.73 |
| 10:08 | NOW | laggards | down | +1.42 | +1.61 | +2.27 |
| 10:10 | CRDO | leaders | up | +0.84 | +1.99 | +0.86 |
| 10:10 | UAA | laggards | down | +1.83 | +1.57 | +2.78 |
| 10:12 | ADBE | laggards | down | +1.34 | +2.00 | +2.86 |
| 10:24 | CVS | laggards | down | +0.17 | +0.52 | +0.48 |
| 10:27 | CNC | laggards | down | -1.79 | -1.86 | -2.55 |
| 11:12 | FND | laggards | down | -0.36 | -0.50 | -1.93 |
| 11:22 | CIFR | leaders | up | -1.52 | -3.82 | -2.39 |
| 11:53 | STX | leaders | up | -1.28 | -0.55 | -0.24 |

## 2026-08-07

Usable symbol-minutes 64,531/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | OKLO | +14.15 | 11:33 | 09:31 |
| 2 | COHR | +12.83 | miss | 09:31 |
| 3 | IONQ | +11.25 | miss | 09:31 |
| 4 | PLTR | +9.71 | miss | 09:50 |
| 5 | LUNR | +9.23 | miss | 09:50 |
| 6 | RKLB | +8.85 | miss | 09:39 |
| 7 | AAOI | +8.57 | 10:04 | 09:31 |
| 8 | IREN | +8.09 | miss | 15:21 |
| 9 | RGTI | +7.92 | miss | 15:30 |
| 10 | CRDO | +7.83 | miss | 09:31 |
| 11 | HSAI | +7.67 | miss | 09:31 |
| 12 | MDB | +7.17 | miss | 09:35 |
| 13 | RDDT | +6.57 | 10:02 | 09:52 |
| 14 | LYFT | +6.50 | miss | miss |
| 15 | QBTS | +6.37 | miss | 09:43 |
| 16 | CIFR | -6.27 | 10:02 | 09:46 |
| 17 | ASTS | +6.19 | miss | miss |
| 18 | TDOC | +6.12 | miss | 10:07 |
| 19 | HPQ | +6.02 | miss | miss |
| 20 | HIMS | +5.90 | miss | miss |

### Radar flags (28)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | APLD | relative_to_spy | down | +0.76 | +0.60 | +1.66 |
| 10:02 | ARM | relative_to_spy | down | -0.03 | -0.21 | +1.17 |
| 10:02 | CIFR | relative_to_spy | down | +1.05 | +1.17 | +1.71 |
| 10:02 | CLSK | relative_to_spy | down | +0.87 | +0.25 | +1.35 |
| 10:02 | MARA | relative_to_spy | down | +1.38 | +1.76 | +3.09 |
| 10:02 | RDDT | relative_to_spy | up | +1.23 | +1.00 | -0.11 |
| 10:02 | RIOT | relative_to_spy | down | -0.50 | -0.39 | +0.24 |
| 10:02 | SNDK | relative_to_spy | down | -1.17 | -0.86 | +1.26 |
| 10:02 | STX | relative_to_spy | down | -1.10 | +1.70 | +4.01 |
| 10:02 | WULF | relative_to_spy | down | +0.54 | -0.29 | +0.02 |
| 10:02 | Bitcoin treasuries and miners (CLSK, MARA, RIOT, IREN) | group_move | down | +0.97 | +0.85 | +1.94 |
| 10:02 | Memory and storage (STX, SNDK, WDC, MU) | group_move | down | -0.89 | +0.03 | +1.90 |
| 10:02 | Neoclouds and AI hosting (CIFR, WULF, APLD, IREN, CRWV, NBIS, ORCL) | group_move | down | +0.74 | +0.66 | +1.50 |
| 10:04 | AAOI | relative_to_spy | up | -2.94 | -8.77 | -4.63 |
| 10:04 | UAA | relative_to_spy | up | +1.16 | +0.89 | +0.95 |
| 10:05 | WDC | relative_to_spy | down | -0.67 | -0.45 | +0.93 |
| 10:05 | Rideshare and delivery (DASH, LYFT, UBER, TSLA) | group_move | up | +0.63 | +0.60 | +0.14 |
| 10:06 | AI networking and connectivity (MRVL, CRDO, ALAB, ANET, AVGO) | group_move | down | +0.26 | +0.49 | +1.80 |
| 10:12 | Quantum computing (QBTS, IONQ, QUBT, RGTI) | group_move | down | +0.99 | +1.30 | +4.12 |
| 10:14 | MRVL | relative_to_spy | down | +0.70 | +2.55 | +4.74 |
| 10:15 | QBTS | relative_to_spy | down | +0.90 | +1.46 | +4.20 |
| 10:44 | Bitcoin treasuries and miners (COIN, MSTR, IREN, MARA, CLSK, RIOT) | group_move | up | -0.12 | +0.57 | +0.23 |
| 10:45 | Crypto and exchanges (COIN, MSTR, CRCL, MARA, HOOD, BULL, RIOT) | group_move | up | -0.49 | -0.15 | -0.63 |
| 10:51 | AAOI | relative_to_spy | down | -0.50 | +1.21 | +2.30 |
| 11:25 | AI networking and connectivity (COHR, CRDO, ALAB, MRVL, ANET) | group_move | up | +0.45 | +0.72 | +0.49 |
| 11:33 | OKLO | relative_to_spy | up | +0.96 | +0.94 | +0.63 |
| 11:34 | Space (LUNR, RKLB, ASTS, PL) | group_move | up | +1.26 | +0.44 | +0.80 |
| 11:35 | Memory and storage (STX, SNDK, WDC, MU) | group_move | up | -0.37 | -0.96 | -0.65 |

### Movers flags (59)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | AAOI | leaders | up | +3.60 | +2.48 | -2.25 |
| 09:31 | NET | leaders | up | +1.61 | -1.54 | -4.60 |
| 09:31 | COHR | leaders | up | +1.69 | +2.16 | +2.85 |
| 09:31 | OKLO | leaders | up | -1.09 | -0.96 | +3.77 |
| 09:31 | CLSK | leaders | up | -9.57 | -8.80 | -8.02 |
| 09:31 | WULF | leaders | up | -8.44 | -8.59 | -8.76 |
| 09:31 | CRDO | leaders | up | -2.51 | -1.65 | +0.01 |
| 09:31 | HSAI | leaders | up | -0.44 | +0.58 | +0.84 |
| 09:31 | CRWV | leaders | up | -2.74 | -2.79 | -0.21 |
| 09:31 | IONQ | leaders | up | +1.45 | +1.12 | +2.46 |
| 09:31 | UAA | laggards | down | +2.32 | +2.99 | +2.51 |
| 09:31 | CVS | laggards | down | +0.86 | +1.32 | +0.75 |
| 09:31 | CVX | laggards | down | +0.07 | -0.04 | +0.06 |
| 09:31 | XOM | laggards | down | -0.27 | -0.11 | -0.27 |
| 09:31 | WFC | laggards | down | +0.18 | +0.25 | -0.15 |
| 09:31 | DASH | laggards | down | +3.52 | +4.50 | +4.40 |
| 09:31 | RCAT | laggards | down | +2.18 | +2.96 | +3.28 |
| 09:31 | WMT | laggards | down | +0.85 | +0.82 | +0.44 |
| 09:31 | MA | laggards | down | -0.01 | -0.34 | -1.22 |
| 09:31 | OXY | laggards | down | -0.18 | +0.36 | +0.94 |
| 09:32 | CRCL | leaders | up | -0.17 | +1.80 | +0.24 |
| 09:32 | MSTR | leaders | up | +0.17 | +2.10 | +0.72 |
| 09:32 | MARA | laggards | down | -5.65 | -4.36 | -2.38 |
| 09:32 | WDC | laggards | down | -3.67 | -4.38 | -2.33 |
| 09:32 | LLY | laggards | down | +1.29 | +0.95 | -0.16 |
| 09:33 | U | leaders | up | -0.74 | -1.59 | -2.14 |
| 09:33 | AXP | laggards | down | +1.13 | +0.96 | -0.08 |
| 09:33 | COST | laggards | down | +0.58 | +0.55 | +0.24 |
| 09:34 | NOW | leaders | up | +0.80 | +1.29 | +0.03 |
| 09:34 | SCHW | laggards | down | +0.53 | +0.49 | +0.09 |
| 09:35 | MDB | leaders | up | -0.39 | +0.20 | +0.85 |
| 09:35 | DDOG | leaders | up | -0.69 | -1.24 | -2.04 |
| 09:35 | STX | laggards | down | -7.64 | -8.49 | -3.80 |
| 09:35 | MRK | laggards | down | +0.88 | -0.32 | +0.40 |
| 09:36 | AN | laggards | down | — | +1.25 | — |
| 09:37 | AMD | laggards | down | +0.83 | -1.22 | -0.80 |
| 09:37 | NBIS | laggards | down | -1.79 | -2.91 | -1.09 |
| 09:39 | RKLB | leaders | up | -1.11 | -0.07 | +0.82 |
| 09:39 | COP | laggards | down | +0.70 | +1.04 | +1.59 |
| 09:40 | DELL | laggards | down | -0.77 | -1.95 | +1.27 |
| 09:43 | QBTS | leaders | up | -5.23 | -4.25 | -2.80 |
| 09:46 | CIFR | laggards | down | -4.16 | -3.43 | -2.52 |
| 09:49 | WULF | laggards | down | -0.60 | -1.25 | -1.65 |
| 09:50 | LUNR | leaders | up | -0.61 | -1.60 | +2.67 |
| 09:50 | PLTR | leaders | up | +2.36 | +1.85 | +2.25 |
| 09:52 | RDDT | leaders | up | +1.85 | +1.34 | +1.47 |
| 09:56 | SNDK | laggards | down | -1.62 | -2.77 | -0.63 |
| 09:56 | FLNC | laggards | down | +0.37 | -0.57 | +1.49 |
| 09:57 | CLSK | laggards | down | +0.06 | -1.47 | +0.12 |
| 10:00 | RIOT | laggards | down | -0.01 | -0.99 | +0.18 |
| 10:01 | MU | laggards | down | -0.79 | -0.63 | +1.18 |
| 10:05 | UBER | leaders | up | +0.65 | +0.58 | -0.20 |
| 10:07 | TDOC | leaders | up | +1.26 | +1.03 | +0.48 |
| 10:08 | CVNA | leaders | up | +0.47 | +0.61 | -0.81 |
| 10:20 | ARM | laggards | down | -0.24 | +0.24 | +0.97 |
| 11:31 | V | laggards | down | +0.14 | +0.37 | +0.08 |
| 11:32 | CAT | laggards | down | +0.35 | +0.16 | +0.27 |
| 15:21 | IREN | leaders | up | -0.12 | — | — |
| 15:30 | RGTI | leaders | up | +0.66 | — | — |

## 2026-08-10

Usable symbol-minutes 64,419/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | COHR | -14.21 | 10:02 | 09:33 |
| 2 | DDOG | +11.51 | 10:02 | 09:45 |
| 3 | RCAT | +8.61 | miss | 09:31 |
| 4 | OKLO | -8.09 | miss | 09:31 |
| 5 | LCID | -6.08 | 10:02 | 09:46 |
| 6 | IREN | -6.01 | miss | 09:31 |
| 7 | CIEN | -5.96 | miss | 09:39 |
| 8 | PANW | +5.85 | miss | 09:37 |
| 9 | CLSK | -5.74 | miss | 11:41 |
| 10 | FND | -5.59 | miss | 09:36 |
| 11 | RIOT | -5.43 | miss | 09:31 |
| 12 | MARA | -5.22 | miss | 09:45 |
| 13 | ARM | -5.18 | miss | 09:34 |
| 14 | WULF | -5.12 | miss | 09:31 |
| 15 | ALAB | -5.04 | miss | miss |
| 16 | CRWD | +5.04 | miss | 09:44 |
| 17 | OXY | +4.93 | miss | 09:31 |
| 18 | CIFR | -4.92 | miss | 09:39 |
| 19 | SPOT | +4.88 | miss | 09:40 |
| 20 | ZS | +4.77 | miss | 10:00 |

### Radar flags (15)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | COHR | relative_to_spy | down | -2.70 | -5.97 | -4.02 |
| 10:02 | DDOG | relative_to_spy | up | +1.56 | +1.36 | +2.91 |
| 10:02 | LCID | relative_to_spy | down | +1.34 | +0.84 | +0.39 |
| 10:02 | Crypto and exchanges (MARA, CRCL, COIN, MSTR, RIOT, BULL, HOOD) | group_move | down | +0.67 | -0.00 | -0.14 |
| 10:02 | Cybersecurity (ZS, CRWD, PANW, S, FTNT) | group_move | up | -0.29 | -0.31 | -0.03 |
| 10:02 | Memory and storage (SNDK, WDC, MU, STX) | group_move | up | -0.14 | -0.53 | +0.07 |
| 10:02 | Space (RKLB, LUNR, ASTS, IRDM, PL) | group_move | down | — | -1.06 | -1.20 |
| 10:04 | MDB | relative_to_spy | up | -1.85 | -1.94 | -1.74 |
| 10:07 | UAA | relative_to_spy | down | -0.78 | -2.01 | -2.80 |
| 10:10 | AAOI | relative_to_spy | up | -9.94 | -10.64 | -8.61 |
| 10:12 | NBIS | relative_to_spy | up | -1.08 | -2.57 | -3.97 |
| 10:13 | AI networking and connectivity (ANET, ALAB, CRDO, MRVL, COHR, AVGO) | group_move | up | -2.67 | -3.46 | -3.29 |
| 10:13 | Quantum computing (QBTS, QUBT, IONQ, RGTI) | group_move | up | +0.11 | -0.52 | +0.03 |
| 10:32 | AAOI | relative_to_spy | down | -4.68 | -2.42 | -2.14 |
| 10:42 | AI networking and connectivity (ALAB, COHR, CRDO, ANET, MRVL, AVGO) | group_move | down | -0.57 | -0.42 | -0.77 |

### Movers flags (60)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | AAOI | leaders | up | -1.05 | -7.66 | -8.80 |
| 09:31 | SMCI | leaders | up | -0.85 | -0.89 | -1.95 |
| 09:31 | CRDO | leaders | up | -2.19 | -2.69 | -4.33 |
| 09:31 | RCAT | leaders | up | +1.04 | +2.42 | +4.13 |
| 09:31 | MRVL | leaders | up | -4.12 | -4.58 | -5.54 |
| 09:31 | ONON | leaders | up | -1.50 | -1.63 | -0.18 |
| 09:31 | RKLB | leaders | up | -2.03 | -2.22 | -5.44 |
| 09:31 | CRWV | leaders | up | -3.13 | -3.01 | -4.27 |
| 09:31 | OXY | leaders | up | +1.78 | +0.61 | +1.40 |
| 09:31 | UBER | leaders | up | +1.09 | +0.46 | +0.93 |
| 09:31 | INTC | laggards | down | +0.25 | +0.21 | +0.88 |
| 09:31 | OKLO | laggards | down | -3.95 | -3.27 | -4.55 |
| 09:31 | STX | laggards | down | +1.93 | +1.98 | +2.25 |
| 09:31 | UAA | laggards | down | -2.28 | -4.33 | -5.50 |
| 09:31 | WULF | laggards | down | -2.62 | -1.91 | -2.87 |
| 09:31 | AAPL | laggards | down | -0.10 | -0.11 | -0.21 |
| 09:31 | MU | laggards | down | +2.46 | +1.25 | +1.27 |
| 09:31 | AMD | laggards | down | +0.24 | +0.17 | +0.18 |
| 09:31 | RIOT | laggards | down | -1.75 | -1.63 | -2.81 |
| 09:31 | IREN | laggards | down | -1.24 | -1.67 | -2.69 |
| 09:32 | RBLX | leaders | up | +0.27 | -0.47 | -1.03 |
| 09:32 | DASH | laggards | down | +1.60 | +0.48 | -0.78 |
| 09:33 | HPQ | leaders | up | -0.62 | -1.60 | -2.25 |
| 09:33 | COHR | laggards | down | -4.76 | -6.97 | -8.85 |
| 09:33 | DDOG | laggards | down | +7.32 | +8.31 | +9.04 |
| 09:33 | LOW | laggards | down | -0.74 | -0.90 | -0.61 |
| 09:34 | IONQ | laggards | down | -1.56 | +0.21 | -0.36 |
| 09:34 | ARM | laggards | down | -2.68 | -2.40 | -2.73 |
| 09:35 | COP | leaders | up | +0.22 | +0.10 | +0.42 |
| 09:35 | CNC | leaders | up | -0.74 | -2.04 | -1.27 |
| 09:35 | NBIS | laggards | down | +4.20 | +4.10 | +2.06 |
| 09:36 | TTWO | leaders | up | -0.00 | -0.22 | +0.14 |
| 09:36 | FND | laggards | down | -1.73 | -1.84 | -1.84 |
| 09:37 | PANW | leaders | up | +1.91 | +1.38 | +2.00 |
| 09:38 | MDB | leaders | up | +2.40 | +0.85 | +1.17 |
| 09:38 | NET | laggards | down | +2.86 | +3.43 | +4.54 |
| 09:39 | XOM | leaders | up | +0.41 | +0.24 | +0.69 |
| 09:39 | CIEN | laggards | down | +1.86 | +0.50 | -0.65 |
| 09:39 | CIFR | laggards | down | -1.19 | -1.02 | -2.89 |
| 09:40 | SPOT | leaders | up | +1.79 | +1.28 | +1.90 |
| 09:40 | QUBT | laggards | down | +1.41 | +1.34 | +0.95 |
| 09:40 | QBTS | laggards | down | +2.07 | +1.33 | +1.08 |
| 09:41 | ASTS | laggards | down | +2.12 | +0.57 | -0.61 |
| 09:44 | CRWD | leaders | up | +1.13 | +1.00 | +2.06 |
| 09:45 | DDOG | leaders | up | +2.60 | +2.76 | +4.25 |
| 09:45 | MARA | laggards | down | +0.41 | -0.67 | -1.89 |
| 09:46 | LCID | laggards | down | -3.65 | -2.80 | -3.01 |
| 09:47 | FTNT | leaders | up | +1.00 | +0.40 | +0.14 |
| 09:50 | APLD | leaders | up | -1.20 | -2.77 | -3.46 |
| 09:51 | DELL | leaders | up | -0.31 | -0.32 | -0.11 |
| 09:52 | SNDK | leaders | up | -0.40 | -0.70 | -0.61 |
| 10:00 | ZS | leaders | up | +0.08 | -0.06 | +0.43 |
| 10:13 | LULU | laggards | down | +1.34 | +1.67 | +1.89 |
| 10:28 | PLTR | leaders | up | +0.93 | +0.36 | +0.56 |
| 10:54 | CVX | leaders | up | +0.09 | +0.17 | +0.72 |
| 10:54 | AAOI | laggards | down | +2.53 | +4.14 | +2.13 |
| 11:13 | S | leaders | up | +0.03 | +0.14 | +0.60 |
| 11:41 | CLSK | laggards | down | -0.02 | -0.26 | -0.26 |
| 13:21 | LUNR | laggards | down | +0.52 | -0.05 | -0.36 |
| 15:22 | CVNA | leaders | up | +0.23 | — | — |

## 2026-08-11

Usable symbol-minutes 64,277/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | ONON | -19.97 | miss | 09:31 |
| 2 | UAA | -8.71 | miss | 09:31 |
| 3 | RCAT | +6.92 | miss | 10:01 |
| 4 | CRCL | +6.45 | 10:07 | 09:39 |
| 5 | OKLO | +5.98 | miss | 10:24 |
| 6 | MDB | +5.72 | miss | 09:31 |
| 7 | CIFR | +5.71 | miss | 09:31 |
| 8 | APP | -5.67 | miss | 09:31 |
| 9 | NBIS | +5.27 | miss | 09:31 |
| 10 | DDOG | -5.05 | miss | 09:32 |
| 11 | LUNR | +4.76 | miss | 12:12 |
| 12 | RIOT | +4.65 | miss | 09:31 |
| 13 | BULL | +4.59 | miss | 14:30 |
| 14 | ASTS | +4.49 | miss | 09:32 |
| 15 | JD | -4.31 | miss | 09:31 |
| 16 | FLNC | +3.96 | miss | 09:31 |
| 17 | WULF | +3.71 | miss | 09:31 |
| 18 | HIMS | -3.65 | miss | 09:31 |
| 19 | ANET | +3.62 | miss | 10:21 |
| 20 | CRDO | +3.55 | miss | miss |

### Radar flags (3)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | RIOT | relative_to_spy | down | -3.15 | -3.34 | -3.77 |
| 10:07 | CRCL | relative_to_spy | up | -1.03 | -1.04 | -1.33 |
| 10:15 | Space (RKLB, PL, LUNR, ASTS, IRDM) | group_move | up | +0.49 | +0.24 | — |

### Movers flags (50)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | RIOT | leaders | up | -8.39 | -11.30 | -12.28 |
| 09:31 | CIFR | leaders | up | +1.59 | +0.67 | +0.16 |
| 09:31 | FLNC | leaders | up | -2.45 | -0.89 | -1.77 |
| 09:31 | WULF | leaders | up | +0.04 | -0.39 | -0.81 |
| 09:31 | MARA | leaders | up | -3.74 | -3.82 | -3.35 |
| 09:31 | CRWV | leaders | up | -3.33 | -4.14 | -4.14 |
| 09:31 | CLSK | leaders | up | -3.12 | -4.61 | -4.56 |
| 09:31 | IREN | leaders | up | +0.10 | -1.11 | -1.28 |
| 09:31 | NBIS | leaders | up | +0.01 | -0.36 | -0.33 |
| 09:31 | MDB | leaders | up | -0.93 | -0.69 | +0.95 |
| 09:31 | ONON | laggards | down | -0.66 | +1.30 | +1.85 |
| 09:31 | UAA | laggards | down | -3.05 | -2.98 | -2.76 |
| 09:31 | JD | laggards | down | -0.43 | -0.46 | -0.22 |
| 09:31 | RKLB | laggards | down | +0.49 | +2.21 | +2.27 |
| 09:31 | APP | laggards | down | -1.34 | -0.26 | -0.03 |
| 09:31 | HIMS | laggards | down | +0.05 | +1.34 | +1.78 |
| 09:31 | BIDU | laggards | down | -0.73 | -0.54 | -0.13 |
| 09:31 | BABA | laggards | down | -0.57 | -0.33 | -0.27 |
| 09:31 | LULU | laggards | down | +0.22 | +0.69 | +0.58 |
| 09:31 | HSAI | laggards | down | +1.05 | +1.57 | +1.30 |
| 09:32 | ASTS | leaders | up | -3.93 | -3.50 | -2.30 |
| 09:32 | DECK | laggards | down | +0.50 | +0.87 | +0.52 |
| 09:32 | CVNA | laggards | down | -0.74 | -0.33 | -0.65 |
| 09:32 | DDOG | laggards | down | -0.52 | -0.64 | -0.55 |
| 09:33 | SNDK | leaders | up | -1.39 | -1.25 | +0.42 |
| 09:33 | DELL | laggards | down | +0.42 | +0.86 | +0.48 |
| 09:34 | APLD | leaders | up | -0.48 | -0.78 | +0.41 |
| 09:35 | CAT | leaders | up | +0.80 | +0.75 | -0.12 |
| 09:35 | NET | laggards | down | +1.92 | +2.37 | +3.05 |
| 09:37 | AAOI | leaders | up | -4.12 | -3.81 | -1.48 |
| 09:38 | SMCI | leaders | up | -0.57 | -1.01 | -1.86 |
| 09:39 | CRCL | leaders | up | +5.10 | +3.73 | +3.17 |
| 09:46 | URI | leaders | up | +0.14 | -0.57 | -1.03 |
| 09:53 | ORCL | laggards | down | +0.80 | +0.20 | -0.50 |
| 09:56 | AAOI | laggards | down | +2.58 | +2.79 | +5.40 |
| 10:00 | FND | leaders | up | +0.25 | -0.23 | -0.77 |
| 10:01 | RCAT | leaders | up | +0.80 | +2.77 | +3.05 |
| 10:08 | SNAP | leaders | up | -0.50 | -0.00 | -0.53 |
| 10:21 | ANET | leaders | up | -0.57 | +0.01 | -1.20 |
| 10:21 | PDD | laggards | down | +0.59 | +0.93 | +0.57 |
| 10:24 | OKLO | leaders | up | +1.36 | +1.85 | +2.12 |
| 12:12 | LUNR | leaders | up | -0.44 | +0.20 | +0.50 |
| 13:02 | LYFT | leaders | up | +0.22 | +0.12 | -0.13 |
| 13:30 | TDOC | laggards | down | +0.17 | +0.10 | -0.04 |
| 13:36 | ADBE | laggards | down | +0.03 | +0.03 | -0.17 |
| 13:50 | STX | leaders | up | -0.23 | -0.06 | -0.10 |
| 14:12 | GOOGL | laggards | down | -0.21 | -0.46 | — |
| 14:14 | HPQ | laggards | down | -0.01 | +0.78 | — |
| 14:30 | BULL | leaders | up | +0.93 | +1.60 | — |
| 14:54 | PL | leaders | up | +0.15 | -0.58 | — |

## 2026-08-12

Usable symbol-minutes 64,259/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | NBIS | +33.89 | miss | 09:31 |
| 2 | CRWV | +19.03 | miss | 09:31 |
| 3 | SMCI | +18.77 | miss | 09:31 |
| 4 | CIEN | +11.24 | miss | 09:31 |
| 5 | DELL | +9.62 | miss | 13:31 |
| 6 | IREN | +9.61 | miss | 09:31 |
| 7 | CRDO | +8.01 | miss | 09:32 |
| 8 | COHR | +7.99 | miss | 09:31 |
| 9 | STX | +6.78 | miss | 09:42 |
| 10 | ANET | +6.14 | miss | 14:29 |
| 11 | SNAP | -5.88 | miss | 09:49 |
| 12 | LYFT | -5.72 | miss | 09:39 |
| 13 | SNDK | +5.51 | miss | 09:45 |
| 14 | CLSK | +5.48 | miss | 09:39 |
| 15 | AI | -5.42 | miss | 09:31 |
| 16 | ORCL | +5.11 | miss | miss |
| 17 | APP | -4.93 | miss | 14:07 |
| 18 | MU | +4.67 | miss | 09:45 |
| 19 | APLD | +4.67 | miss | 09:31 |
| 20 | UBER | -4.30 | miss | 09:54 |

### Radar flags (5)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:06 | Space (LUNR, RKLB, ASTS, PL, IRDM) | group_move | up | -0.82 | -1.04 | — |
| 10:07 | Memory and storage (SNDK, STX, MU, WDC) | group_move | up | +0.36 | +0.18 | +0.19 |
| 10:39 | Neoclouds and AI hosting (CIFR, IREN, WULF, APLD, CRWV, NBIS, ORCL) | group_move | down | +0.80 | +1.11 | +2.13 |
| 10:43 | Bitcoin treasuries and miners (IREN, MARA, RIOT, COIN, MSTR, CLSK) | group_move | down | +0.49 | +0.28 | +0.98 |
| 11:08 | AAOI | relative_to_spy | up | +0.88 | +0.43 | +0.97 |

### Movers flags (58)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | CRWV | leaders | up | -1.30 | -1.68 | -2.02 |
| 09:31 | NBIS | leaders | up | +4.89 | +6.37 | +9.29 |
| 09:31 | IREN | leaders | up | -1.33 | -2.82 | -3.80 |
| 09:31 | CIFR | leaders | up | -2.59 | -4.05 | -5.22 |
| 09:31 | CIEN | leaders | up | +2.43 | +1.26 | +3.13 |
| 09:31 | SMCI | leaders | up | +5.09 | +5.06 | +4.42 |
| 09:31 | APLD | leaders | up | -2.76 | -3.93 | -4.29 |
| 09:31 | WULF | leaders | up | -3.04 | -4.97 | -5.20 |
| 09:31 | RIOT | leaders | up | -4.88 | -5.76 | -5.15 |
| 09:31 | COHR | leaders | up | -1.94 | -2.27 | +0.38 |
| 09:31 | NVO | laggards | down | +0.71 | +0.65 | +1.14 |
| 09:31 | NOW | laggards | down | -1.61 | -0.74 | -0.50 |
| 09:31 | HIMS | laggards | down | -0.33 | +0.15 | +0.40 |
| 09:31 | BABA | laggards | down | -0.55 | -0.02 | -0.82 |
| 09:31 | CRM | laggards | down | -0.42 | -0.35 | -0.32 |
| 09:31 | AI | laggards | down | -1.65 | -1.53 | -1.76 |
| 09:31 | ADBE | laggards | down | -0.81 | -0.88 | -1.14 |
| 09:31 | JD | laggards | down | -0.75 | -0.46 | -0.50 |
| 09:31 | MDB | laggards | down | +1.25 | +1.94 | +2.22 |
| 09:31 | LLY | laggards | down | +1.07 | +1.10 | +2.48 |
| 09:32 | CRDO | leaders | up | -1.64 | -0.74 | +1.60 |
| 09:32 | CRCL | laggards | down | +0.17 | +0.58 | +0.08 |
| 09:32 | RKLB | laggards | down | +3.96 | +3.07 | +2.36 |
| 09:32 | RCAT | laggards | down | +0.25 | +0.31 | -0.55 |
| 09:32 | BIDU | laggards | down | -0.25 | +0.30 | -0.26 |
| 09:33 | S | laggards | down | +1.00 | +1.99 | +1.79 |
| 09:33 | PINS | laggards | down | -1.78 | -1.47 | -1.59 |
| 09:33 | PANW | laggards | down | +2.02 | +2.24 | +1.97 |
| 09:34 | MRVL | leaders | up | -1.11 | -1.57 | -1.00 |
| 09:34 | PLTR | laggards | down | -1.36 | -1.48 | -1.53 |
| 09:35 | OKLO | laggards | down | +0.07 | -0.90 | -2.43 |
| 09:39 | CLSK | leaders | up | +0.25 | -0.64 | -0.44 |
| 09:39 | LYFT | laggards | down | -1.56 | -2.52 | -3.69 |
| 09:40 | AAOI | laggards | down | +1.92 | +0.14 | +5.16 |
| 09:41 | INTC | leaders | up | -1.13 | -0.06 | -1.30 |
| 09:42 | STX | leaders | up | +2.47 | +2.99 | +2.14 |
| 09:43 | TTWO | laggards | down | -0.41 | -0.57 | -0.96 |
| 09:44 | LULU | laggards | down | -0.22 | -1.12 | -0.80 |
| 09:45 | MU | leaders | up | +0.53 | +1.27 | +0.68 |
| 09:45 | SNDK | leaders | up | +2.56 | +3.89 | +2.96 |
| 09:47 | WDC | leaders | up | -0.08 | +0.09 | -1.44 |
| 09:49 | SNAP | laggards | down | -0.74 | -1.42 | -1.27 |
| 09:50 | LAD | laggards | down | +1.69 | +1.27 | +1.81 |
| 09:53 | ZS | laggards | down | +1.34 | +2.04 | +1.66 |
| 09:54 | UBER | laggards | down | +0.77 | -0.22 | -1.25 |
| 09:58 | IBM | laggards | down | +0.43 | +0.29 | +0.86 |
| 10:01 | FND | laggards | down | +0.29 | +0.10 | +0.49 |
| 10:06 | HD | laggards | down | -0.19 | +0.02 | +0.86 |
| 10:07 | TDOC | laggards | down | +0.37 | +0.02 | +0.03 |
| 10:11 | LOW | laggards | down | -0.45 | +0.31 | +0.62 |
| 10:33 | ALAB | leaders | up | +0.45 | +1.84 | +2.12 |
| 10:49 | LCID | laggards | down | -1.01 | -0.22 | +0.51 |
| 11:56 | META | laggards | down | +0.05 | -0.06 | -0.62 |
| 13:31 | DELL | leaders | up | +0.31 | +0.39 | +1.23 |
| 14:07 | APP | laggards | down | -0.09 | -0.85 | — |
| 14:12 | SPOT | laggards | down | -0.09 | +0.14 | — |
| 14:29 | ANET | leaders | up | -0.21 | -0.44 | — |
| 15:44 | RIVN | laggards | down | — | — | — |

## 2026-08-13

Usable symbol-minutes 64,473/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | SNDK | +12.98 | 10:04 | 09:48 |
| 2 | COHR | -8.69 | miss | 09:31 |
| 3 | JD | -8.01 | miss | 09:33 |
| 4 | CIFR | -7.69 | miss | 09:31 |
| 5 | MDB | +7.17 | miss | 09:31 |
| 6 | WDC | +6.61 | miss | 09:47 |
| 7 | AAOI | -6.49 | miss | 09:35 |
| 8 | S | +6.21 | miss | 14:45 |
| 9 | HPQ | +6.20 | miss | 09:31 |
| 10 | PDD | -6.16 | miss | 09:36 |
| 11 | RIOT | -6.16 | miss | 09:32 |
| 12 | CLSK | -6.12 | miss | 10:56 |
| 13 | RBLX | +6.08 | miss | 14:09 |
| 14 | WULF | -5.82 | miss | 10:52 |
| 15 | NET | +5.52 | miss | 10:53 |
| 16 | ZS | +5.43 | miss | 14:38 |
| 17 | MARA | -5.16 | miss | 10:50 |
| 18 | CRCL | +5.05 | miss | 15:33 |
| 19 | NFLX | +4.73 | miss | 09:31 |
| 20 | HIMS | -4.70 | miss | 09:36 |

### Radar flags (14)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | ARM | relative_to_spy | up | +1.09 | +0.85 | -0.65 |
| 10:02 | HPQ | relative_to_spy | down | +1.98 | +2.66 | +2.13 |
| 10:02 | IREN | relative_to_spy | up | -1.98 | -5.35 | -6.56 |
| 10:02 | LUNR | relative_to_spy | up | -0.03 | -1.39 | -1.89 |
| 10:02 | BULL | relative_to_sector | up | -0.78 | -1.20 | -2.56 |
| 10:02 | AI networking and connectivity (ALAB, MRVL, CRDO, AVGO) | group_move | up | +1.03 | +1.35 | +0.59 |
| 10:02 | Memory and storage (SNDK, WDC, MU, STX) | group_move | up | +1.30 | +2.57 | +5.32 |
| 10:04 | SNDK | relative_to_spy | up | +0.82 | +1.78 | +10.90 |
| 10:15 | CRWV | relative_to_spy | down | +0.49 | +0.42 | -1.60 |
| 10:28 | SMCI | relative_to_spy | up | -0.12 | -0.36 | -4.01 |
| 10:56 | Quantum computing (IONQ, QBTS, RGTI, QUBT) | group_move | down | -0.99 | -1.03 | -1.63 |
| 10:58 | Bitcoin treasuries and miners (IREN, CLSK, MARA, RIOT, COIN, MSTR) | group_move | down | +0.50 | -0.74 | -1.70 |
| 10:59 | Neoclouds and AI hosting (IREN, CIFR, APLD, WULF, NBIS, ORCL, CRWV) | group_move | down | +0.48 | -0.81 | -2.08 |
| 14:44 | CRM | relative_to_spy | up | -1.21 | -0.32 | — |

### Movers flags (69)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | HPQ | leaders | up | -5.80 | -3.65 | -4.12 |
| 09:31 | IREN | leaders | up | +5.45 | +2.84 | +0.15 |
| 09:31 | DELL | leaders | up | -3.38 | -1.89 | -2.56 |
| 09:31 | NFLX | leaders | up | +0.46 | +0.51 | +0.05 |
| 09:31 | SMCI | leaders | up | +2.48 | +7.27 | +7.09 |
| 09:31 | HOOD | leaders | up | +1.91 | +1.40 | +0.79 |
| 09:31 | PLTR | leaders | up | -0.01 | -0.66 | -1.26 |
| 09:31 | CRWV | leaders | up | +3.20 | +0.17 | -0.29 |
| 09:31 | APP | leaders | up | +0.79 | +1.62 | +0.34 |
| 09:31 | MDB | leaders | up | +2.51 | +2.18 | +2.10 |
| 09:31 | LUNR | laggards | down | +15.21 | +14.60 | +13.70 |
| 09:31 | COHR | laggards | down | +1.81 | +1.24 | -0.46 |
| 09:31 | RKLB | laggards | down | +4.83 | +5.37 | +3.12 |
| 09:31 | PL | laggards | down | +1.76 | +3.35 | +3.00 |
| 09:31 | LCID | laggards | down | +0.05 | -1.74 | -0.66 |
| 09:31 | CIFR | laggards | down | +0.48 | -0.94 | -2.40 |
| 09:31 | RCAT | laggards | down | +0.32 | +2.86 | +1.94 |
| 09:31 | IRDM | laggards | down | +2.19 | +2.99 | +2.64 |
| 09:31 | ASTS | laggards | down | -0.04 | +0.00 | -1.26 |
| 09:31 | FLNC | laggards | down | +1.82 | +2.94 | +3.72 |
| 09:32 | RGTI | leaders | up | -0.00 | +1.43 | -0.47 |
| 09:32 | NBIS | leaders | up | +1.04 | +2.81 | -1.24 |
| 09:32 | UAA | leaders | up | -0.73 | -1.17 | -1.05 |
| 09:32 | ALAB | laggards | down | +3.77 | +5.57 | +6.05 |
| 09:32 | ANET | laggards | down | -0.06 | +0.18 | +0.71 |
| 09:32 | SONY | laggards | down | -0.09 | +0.12 | +0.26 |
| 09:32 | OXY | laggards | down | -1.00 | -0.51 | +0.05 |
| 09:32 | RIOT | laggards | down | +1.47 | +1.66 | +0.86 |
| 09:32 | COP | laggards | down | -0.78 | -0.73 | -0.37 |
| 09:32 | SPOT | laggards | down | +2.22 | +2.07 | +1.77 |
| 09:33 | DECK | leaders | up | -0.92 | -1.72 | -1.56 |
| 09:33 | JD | laggards | down | -3.68 | -5.31 | -5.76 |
| 09:33 | STX | laggards | down | +1.95 | +3.60 | +6.63 |
| 09:34 | BULL | leaders | up | +2.33 | +1.56 | +0.14 |
| 09:34 | IONQ | leaders | up | +0.75 | +1.45 | -1.54 |
| 09:35 | AAOI | laggards | down | +2.19 | +4.68 | +2.21 |
| 09:36 | BABA | laggards | down | -0.85 | -0.85 | -1.36 |
| 09:36 | HIMS | laggards | down | -0.41 | -0.99 | -1.01 |
| 09:36 | PDD | laggards | down | -2.25 | -2.60 | -3.75 |
| 09:39 | NVO | laggards | down | +0.45 | -0.10 | +0.49 |
| 09:42 | DDOG | leaders | up | -0.40 | -0.03 | -0.17 |
| 09:43 | MSTR | leaders | up | -0.10 | +0.44 | -1.37 |
| 09:45 | AI | laggards | down | -0.26 | -1.93 | -2.30 |
| 09:47 | CRDO | leaders | up | -0.31 | +1.34 | +0.21 |
| 09:47 | WDC | leaders | up | +1.88 | +3.52 | +3.91 |
| 09:47 | URI | laggards | down | +0.11 | -0.04 | — |
| 09:48 | ARM | leaders | up | +1.56 | +2.69 | +0.01 |
| 09:48 | SNDK | leaders | up | +0.22 | +2.74 | +9.63 |
| 09:48 | ONON | laggards | down | -0.65 | -0.28 | -0.14 |
| 09:50 | INTC | leaders | up | -0.55 | +0.46 | +0.20 |
| 09:53 | MRVL | leaders | up | +1.08 | +1.29 | +0.72 |
| 10:10 | XOM | laggards | down | +0.57 | +1.04 | +1.44 |
| 10:12 | SHEL | laggards | down | +0.49 | +0.76 | +1.08 |
| 10:15 | CIEN | leaders | up | +2.11 | +2.16 | +1.28 |
| 10:21 | TDOC | leaders | up | -0.22 | -0.45 | -1.58 |
| 10:25 | QBTS | leaders | up | -2.20 | -3.23 | -2.91 |
| 10:50 | MARA | laggards | down | -0.62 | -1.36 | -2.29 |
| 10:51 | MU | leaders | up | +1.40 | +0.37 | +1.46 |
| 10:52 | WULF | laggards | down | -0.12 | -1.42 | -2.35 |
| 10:53 | NET | leaders | up | -0.92 | +0.23 | +0.48 |
| 10:56 | CLSK | laggards | down | +1.03 | -0.67 | -1.97 |
| 11:16 | STX | leaders | up | -0.67 | -0.76 | -0.54 |
| 11:27 | NOW | laggards | down | +0.30 | +0.13 | +0.50 |
| 13:59 | NBIS | laggards | down | +0.21 | -0.60 | +2.02 |
| 14:09 | RBLX | leaders | up | +0.59 | +2.35 | — |
| 14:38 | ZS | leaders | up | +1.73 | +1.44 | — |
| 14:45 | S | leaders | up | +0.60 | +1.72 | — |
| 14:50 | OKLO | leaders | up | -0.18 | -1.33 | — |
| 15:33 | CRCL | leaders | up | — | — | — |

## 2026-08-14

Usable symbol-minutes 64,238/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | AAOI | +15.73 | 10:02 | 09:33 |
| 2 | RDDT | +12.83 | miss | 09:31 |
| 3 | NBIS | +9.07 | miss | 09:31 |
| 4 | RCAT | +9.00 | miss | 09:31 |
| 5 | LUNR | +8.46 | miss | 09:31 |
| 6 | CPRT | +7.75 | miss | 09:31 |
| 7 | CIFR | +7.63 | 13:17 | 13:10 |
| 8 | SNDK | +7.59 | 10:07 | 09:31 |
| 9 | WULF | +6.76 | miss | 09:34 |
| 10 | AMD | +6.69 | miss | 10:05 |
| 11 | STX | +5.85 | 10:04 | 09:31 |
| 12 | AVGO | -5.74 | miss | 09:31 |
| 13 | HSAI | -5.40 | miss | 09:31 |
| 14 | CLSK | +5.15 | miss | 13:19 |
| 15 | CRCL | -4.82 | miss | 09:31 |
| 16 | WDC | +4.61 | miss | 09:31 |
| 17 | NET | -4.35 | miss | 09:55 |
| 18 | OKLO | -4.26 | miss | 13:06 |
| 19 | MSTR | -3.98 | miss | 09:31 |
| 20 | F | +3.65 | miss | miss |

### Radar flags (9)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | AAOI | relative_to_spy | up | +1.44 | +2.15 | +2.28 |
| 10:02 | COHR | relative_to_spy | up | -1.48 | -2.26 | -4.62 |
| 10:02 | RCAT | relative_to_sector | down | -0.29 | +1.61 | +0.19 |
| 10:04 | STX | relative_to_spy | up | -2.38 | -1.82 | -3.09 |
| 10:06 | Memory and storage (STX, SNDK, WDC, MU) | group_move | up | -2.15 | -1.32 | -2.47 |
| 10:07 | SNDK | relative_to_spy | up | -2.17 | -1.28 | -2.20 |
| 10:37 | Memory and storage (STX, WDC, SNDK, MU) | group_move | down | +0.89 | -0.12 | +0.37 |
| 10:58 | Space (ASTS, LUNR, RKLB, PL) | group_move | down | -0.73 | -0.44 | +0.09 |
| 13:17 | CIFR | relative_to_spy | up | +0.83 | -0.00 | -0.29 |

### Movers flags (60)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | LUNR | leaders | up | -2.83 | -2.72 | -4.77 |
| 09:31 | RCAT | leaders | up | -5.58 | -5.27 | -4.14 |
| 09:31 | RDDT | leaders | up | +3.86 | +1.91 | +3.01 |
| 09:31 | SNDK | leaders | up | +0.39 | -1.58 | +0.63 |
| 09:31 | SONY | leaders | up | -0.94 | -0.76 | -0.83 |
| 09:31 | NBIS | leaders | up | +2.15 | +0.15 | +1.86 |
| 09:31 | WDC | leaders | up | +0.12 | -2.14 | -1.80 |
| 09:31 | MU | leaders | up | -0.40 | -0.56 | -0.79 |
| 09:31 | CPRT | leaders | up | +1.38 | +2.63 | +4.50 |
| 09:31 | STX | leaders | up | +4.12 | +1.46 | +1.44 |
| 09:31 | HSAI | laggards | down | -2.03 | -2.12 | -2.56 |
| 09:31 | MSTR | laggards | down | -0.43 | -0.95 | -1.23 |
| 09:31 | RIOT | laggards | down | +2.55 | +1.48 | -1.07 |
| 09:31 | AVGO | laggards | down | -1.72 | -2.57 | -3.32 |
| 09:31 | JD | laggards | down | +0.63 | +1.45 | +1.09 |
| 09:31 | CLSK | laggards | down | +2.46 | +2.87 | +1.55 |
| 09:31 | CIFR | laggards | down | +1.36 | +0.87 | +0.17 |
| 09:31 | MARA | laggards | down | +0.60 | +0.51 | -0.06 |
| 09:31 | CRCL | laggards | down | -1.83 | -2.62 | -3.35 |
| 09:31 | APLD | laggards | down | +1.61 | +1.13 | -0.60 |
| 09:32 | SNAP | leaders | up | -0.78 | -1.08 | -1.67 |
| 09:32 | RBLX | leaders | up | -1.01 | -1.21 | -0.19 |
| 09:32 | LLY | laggards | down | -0.38 | -0.31 | +0.13 |
| 09:32 | CIEN | laggards | down | +1.48 | +0.32 | -0.01 |
| 09:32 | HOOD | laggards | down | -0.16 | -0.23 | -0.34 |
| 09:32 | CRDO | laggards | down | -0.81 | -0.44 | -2.37 |
| 09:33 | AAOI | leaders | up | +9.46 | +10.73 | +11.26 |
| 09:33 | COHR | laggards | down | +5.77 | +4.20 | +1.39 |
| 09:33 | COIN | laggards | down | -0.89 | -1.59 | -1.49 |
| 09:34 | WULF | leaders | up | -0.71 | +0.05 | -1.04 |
| 09:34 | ADBE | laggards | down | -0.82 | -0.84 | -0.33 |
| 09:35 | APP | leaders | up | -0.94 | -0.79 | -0.53 |
| 09:36 | PINS | leaders | up | +0.07 | +0.17 | +0.30 |
| 09:39 | CRWV | leaders | up | -4.27 | -2.79 | -5.19 |
| 09:39 | SMCI | leaders | up | -0.38 | -1.55 | -3.01 |
| 09:39 | NOW | laggards | down | -1.16 | -0.35 | +1.07 |
| 09:44 | IREN | leaders | up | -2.89 | -2.58 | -5.10 |
| 09:44 | HPQ | laggards | down | +0.13 | -0.26 | -0.58 |
| 09:46 | RGTI | leaders | up | -0.64 | -0.55 | -1.70 |
| 09:46 | S | laggards | down | -1.23 | -1.39 | -0.70 |
| 09:48 | IONQ | leaders | up | +0.14 | -0.49 | -0.77 |
| 09:51 | COHR | leaders | up | -0.38 | -1.34 | -4.30 |
| 09:52 | CRM | laggards | down | +0.11 | -0.29 | +0.72 |
| 09:55 | NET | laggards | down | -0.42 | -0.76 | -0.32 |
| 09:58 | SPOT | leaders | up | +0.75 | +0.04 | -0.37 |
| 10:01 | FTNT | laggards | down | -0.22 | -0.04 | +0.58 |
| 10:02 | PANW | laggards | down | +0.71 | +0.20 | +0.36 |
| 10:05 | AMD | leaders | up | +1.27 | +1.02 | -0.23 |
| 10:05 | CRWD | laggards | down | +0.23 | +0.28 | +0.69 |
| 10:32 | SNOW | laggards | down | +0.28 | +0.36 | +0.73 |
| 11:23 | ALAB | laggards | down | +0.80 | +0.84 | +0.93 |
| 11:25 | ASTS | laggards | down | +0.03 | +1.56 | +2.09 |
| 11:31 | ONON | leaders | up | -0.59 | -1.49 | -1.21 |
| 12:48 | AI | laggards | down | +0.11 | -0.61 | -1.07 |
| 12:54 | ORCL | laggards | down | +0.11 | +0.05 | -1.35 |
| 12:59 | LCID | laggards | down | +1.23 | +0.74 | -1.94 |
| 13:06 | OKLO | laggards | down | +0.03 | -0.36 | -1.50 |
| 13:10 | CIFR | leaders | up | +3.29 | +2.52 | +2.26 |
| 13:16 | MDB | laggards | down | +0.54 | +0.40 | -0.43 |
| 13:19 | CLSK | leaders | up | -0.78 | -0.95 | -1.58 |

## 2026-08-17

Usable symbol-minutes 64,427/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | SNDK | +9.35 | miss | 09:31 |
| 2 | CRDO | +9.29 | miss | 09:31 |
| 3 | COHR | +8.27 | miss | 09:31 |
| 4 | LUNR | +7.68 | miss | 09:31 |
| 5 | RDDT | -7.16 | miss | 09:33 |
| 6 | CVNA | -6.80 | miss | 09:32 |
| 7 | MARA | +6.07 | miss | 12:00 |
| 8 | MRVL | +6.02 | miss | 09:31 |
| 9 | RIOT | +5.86 | miss | 13:04 |
| 10 | WDC | +5.82 | miss | 09:31 |
| 11 | RCAT | -5.73 | miss | 09:31 |
| 12 | MSTR | +5.46 | miss | 09:33 |
| 13 | S | -5.11 | miss | 09:31 |
| 14 | CRCL | +4.65 | miss | 09:38 |
| 15 | NOW | -4.61 | miss | 09:45 |
| 16 | MU | +4.60 | miss | 09:31 |
| 17 | CIEN | +4.30 | miss | 10:23 |
| 18 | MDB | -4.23 | miss | 10:25 |
| 19 | CIFR | +4.09 | miss | 09:47 |
| 20 | CNC | -4.06 | miss | 09:31 |

### Radar flags (1)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | Quantum computing (QUBT, IONQ, RGTI, QBTS) | group_move | up | +0.38 | +0.50 | +1.27 |

### Movers flags (54)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | ALAB | leaders | up | -1.91 | -3.49 | -3.03 |
| 09:31 | CRDO | leaders | up | +0.57 | +0.11 | +1.46 |
| 09:31 | LUNR | leaders | up | -0.91 | +1.13 | -1.05 |
| 09:31 | SNDK | leaders | up | +3.02 | +3.32 | +4.76 |
| 09:31 | MU | leaders | up | +0.89 | +0.71 | +1.98 |
| 09:31 | MRVL | leaders | up | +2.15 | +1.82 | +3.50 |
| 09:31 | WDC | leaders | up | +3.40 | +3.24 | +2.88 |
| 09:31 | COHR | leaders | up | +2.15 | +2.74 | +6.26 |
| 09:31 | AAOI | leaders | up | -0.67 | +0.27 | +2.40 |
| 09:31 | ZS | leaders | up | -1.10 | -1.54 | -0.94 |
| 09:31 | RCAT | laggards | down | +0.48 | +1.20 | +0.65 |
| 09:31 | SNAP | laggards | down | -1.74 | -0.24 | +0.60 |
| 09:31 | QBTS | laggards | down | +2.80 | +3.34 | +4.05 |
| 09:31 | RGTI | laggards | down | +2.88 | +3.33 | +3.36 |
| 09:31 | QUBT | laggards | down | +3.69 | +3.23 | +3.27 |
| 09:31 | IONQ | laggards | down | +2.44 | +3.90 | +4.35 |
| 09:31 | S | laggards | down | -1.58 | -2.12 | -1.43 |
| 09:31 | SONY | laggards | down | -0.04 | -0.26 | -0.18 |
| 09:31 | AI | laggards | down | -1.40 | -0.78 | -0.65 |
| 09:31 | CNC | laggards | down | -0.97 | -1.71 | -1.47 |
| 09:32 | PDD | leaders | up | -0.72 | -1.07 | -2.34 |
| 09:32 | CVNA | laggards | down | -0.71 | -0.13 | -1.18 |
| 09:33 | MSTR | leaders | up | -1.10 | -0.27 | +0.79 |
| 09:33 | RDDT | laggards | down | -1.80 | +0.59 | -0.88 |
| 09:33 | SMCI | laggards | down | -0.26 | -1.00 | -0.32 |
| 09:34 | RKLB | leaders | up | +1.87 | +1.79 | +0.51 |
| 09:34 | NBIS | laggards | down | +0.94 | -0.89 | +2.01 |
| 09:34 | CRWV | laggards | down | +0.59 | +0.69 | +2.91 |
| 09:35 | APP | leaders | up | -2.60 | -2.24 | -3.55 |
| 09:36 | DECK | laggards | down | -0.09 | -0.21 | +0.30 |
| 09:36 | FND | laggards | down | -1.02 | -0.10 | +0.01 |
| 09:38 | CRCL | leaders | up | -0.37 | -0.14 | +0.22 |
| 09:41 | NET | laggards | down | +0.30 | -0.22 | -0.49 |
| 09:43 | HPQ | laggards | down | +1.25 | +1.35 | +1.05 |
| 09:44 | PINS | laggards | down | +0.01 | -0.65 | -0.56 |
| 09:45 | NOW | laggards | down | +0.19 | +0.07 | -0.83 |
| 09:46 | RIVN | laggards | down | +0.13 | +1.11 | +0.52 |
| 09:46 | DDOG | laggards | down | -0.32 | -0.05 | +1.58 |
| 09:47 | CIFR | leaders | up | -0.71 | -1.24 | -1.17 |
| 09:48 | ASTS | leaders | up | +0.38 | -0.64 | -1.44 |
| 09:49 | ADBE | laggards | down | +0.21 | -0.13 | -0.93 |
| 10:01 | ORCL | laggards | down | +1.26 | +1.07 | +2.30 |
| 10:02 | DELL | laggards | down | -0.84 | +1.01 | +1.05 |
| 10:12 | NKE | laggards | down | -0.16 | -0.45 | -0.83 |
| 10:23 | CIEN | leaders | up | +1.76 | +2.63 | +3.32 |
| 10:25 | MDB | laggards | down | -0.23 | -0.55 | -0.94 |
| 10:36 | FLNC | laggards | down | -0.44 | -0.63 | -0.96 |
| 10:44 | TDOC | laggards | down | -0.04 | -0.19 | -0.03 |
| 11:04 | STX | leaders | up | -1.40 | -2.05 | -1.73 |
| 11:56 | IREN | leaders | up | -0.40 | +0.62 | -0.03 |
| 12:00 | MARA | leaders | up | -0.03 | -0.34 | -0.69 |
| 12:40 | META | laggards | down | -0.10 | -0.17 | +0.13 |
| 13:04 | RIOT | leaders | up | -2.38 | -2.19 | -1.94 |
| 15:28 | SPOT | laggards | down | -0.55 | — | — |

## 2026-08-18

Usable symbol-minutes 64,653/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | AAOI | -14.48 | 10:02 | 09:35 |
| 2 | CRDO | -12.35 | miss | 09:31 |
| 3 | CIFR | -12.32 | miss | 09:31 |
| 4 | COHR | -12.08 | miss | 09:31 |
| 5 | BIDU | -12.05 | miss | 09:31 |
| 6 | CRWV | -11.43 | miss | 09:31 |
| 7 | WULF | -10.57 | miss | 13:07 |
| 8 | STX | -8.48 | miss | 09:40 |
| 9 | SNDK | -8.34 | miss | 09:37 |
| 10 | CIEN | -8.23 | miss | 09:32 |
| 11 | APLD | -7.89 | miss | 11:45 |
| 12 | MRVL | -7.15 | miss | 09:35 |
| 13 | MARA | -7.10 | miss | miss |
| 14 | NBIS | -6.92 | miss | miss |
| 15 | WDC | -6.76 | miss | 09:36 |
| 16 | CVNA | -6.59 | 10:23 | 10:21 |
| 17 | LCID | -6.56 | miss | miss |
| 18 | MU | -6.34 | miss | miss |
| 19 | FLNC | -6.29 | miss | miss |
| 20 | ARM | -6.00 | miss | 09:31 |

### Radar flags (9)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | AAOI | relative_to_spy | down | +0.34 | -3.65 | -3.12 |
| 10:02 | HSAI | relative_to_spy | up | +0.01 | -2.45 | -1.56 |
| 10:02 | RCAT | relative_to_spy | up | -1.78 | -3.83 | -2.03 |
| 10:02 | AI networking and connectivity (CRDO, COHR, ALAB, MRVL, AVGO) | group_move | down | +0.23 | -1.79 | -0.89 |
| 10:11 | Bitcoin treasuries and miners (IREN, RIOT, MARA, CLSK, MSTR, COIN) | group_move | down | +1.05 | -0.56 | +0.07 |
| 10:11 | Neoclouds and AI hosting (WULF, APLD, IREN, CIFR, CRWV, NBIS, ORCL) | group_move | down | -0.53 | -2.17 | -2.29 |
| 10:13 | Memory and storage (STX, SNDK, MU, WDC) | group_move | down | -0.09 | -1.54 | -0.62 |
| 10:13 | Quantum computing (QUBT, QBTS, IONQ, RGTI) | group_move | down | -0.08 | -1.26 | +0.16 |
| 10:23 | CVNA | relative_to_spy | down | +0.60 | +1.81 | +3.17 |

### Movers flags (55)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | BABA | leaders | up | -0.66 | -0.55 | -1.12 |
| 09:31 | XOM | leaders | up | -0.42 | -0.23 | +0.44 |
| 09:31 | ADBE | leaders | up | +1.94 | +1.58 | +1.93 |
| 09:31 | CRM | leaders | up | +1.50 | +1.11 | +1.63 |
| 09:31 | SPOT | leaders | up | +2.87 | +2.71 | +4.06 |
| 09:31 | OXY | leaders | up | -1.14 | -0.77 | -0.39 |
| 09:31 | NFLX | leaders | up | +1.20 | +1.20 | +2.11 |
| 09:31 | COP | leaders | up | -0.38 | -0.06 | +0.19 |
| 09:31 | TGT | leaders | up | -0.01 | +0.14 | +0.22 |
| 09:31 | RDDT | leaders | up | -1.78 | -2.25 | -2.56 |
| 09:31 | HSAI | laggards | down | +8.25 | +8.77 | +8.79 |
| 09:31 | BIDU | laggards | down | -1.27 | -1.37 | -3.46 |
| 09:31 | COHR | laggards | down | -3.44 | -3.06 | -5.07 |
| 09:31 | ARM | laggards | down | -0.67 | -0.00 | -1.86 |
| 09:31 | CRDO | laggards | down | -3.40 | -3.40 | -6.52 |
| 09:31 | CIFR | laggards | down | -0.79 | -0.58 | -4.26 |
| 09:31 | CRWV | laggards | down | -2.23 | -1.56 | -2.91 |
| 09:31 | INTC | laggards | down | -0.93 | -0.58 | -1.72 |
| 09:31 | ASTS | laggards | down | -1.00 | -0.53 | +0.03 |
| 09:31 | QUBT | laggards | down | +0.44 | +0.30 | +0.18 |
| 09:32 | ZS | leaders | up | -0.19 | -1.28 | -2.00 |
| 09:32 | FTNT | leaders | up | -0.91 | -1.93 | -1.59 |
| 09:32 | LLY | leaders | up | +0.74 | +0.48 | +1.26 |
| 09:32 | HPQ | leaders | up | -0.26 | +0.11 | -0.14 |
| 09:32 | CIEN | laggards | down | -0.63 | -1.70 | -5.04 |
| 09:33 | CI | leaders | up | -0.26 | +0.33 | +0.48 |
| 09:34 | CVX | leaders | up | -0.98 | -0.88 | -0.72 |
| 09:34 | ALAB | laggards | down | -1.22 | -0.81 | -1.62 |
| 09:35 | ELV | leaders | up | +0.68 | +1.02 | +0.50 |
| 09:35 | PFE | leaders | up | -0.04 | -0.40 | -0.17 |
| 09:35 | AAOI | laggards | down | -1.69 | -3.48 | -5.84 |
| 09:35 | MRVL | laggards | down | -1.23 | -2.25 | -2.98 |
| 09:36 | MDB | leaders | up | -0.67 | -1.69 | -1.82 |
| 09:36 | PINS | leaders | up | +0.67 | +0.80 | +0.75 |
| 09:36 | WDC | laggards | down | -0.18 | -1.39 | -2.15 |
| 09:37 | DASH | leaders | up | +1.24 | +1.60 | +1.97 |
| 09:37 | SNAP | leaders | up | +0.05 | +0.11 | -0.30 |
| 09:37 | SNDK | laggards | down | -0.97 | -1.07 | -2.88 |
| 09:38 | S | leaders | up | -0.15 | -0.68 | -0.61 |
| 09:39 | RCAT | leaders | up | -0.12 | -2.65 | -3.28 |
| 09:40 | STX | laggards | down | -1.80 | -2.12 | -3.82 |
| 09:41 | NOW | leaders | up | +0.18 | -0.62 | -0.15 |
| 09:43 | DDOG | leaders | up | -1.41 | -2.07 | -1.75 |
| 09:44 | UBER | leaders | up | +0.41 | +0.52 | +0.48 |
| 09:49 | LULU | leaders | up | +1.69 | +2.41 | +2.43 |
| 09:51 | CNC | leaders | up | -0.15 | -0.26 | -0.53 |
| 10:21 | CVNA | laggards | down | +0.38 | +0.98 | +2.69 |
| 10:24 | TTWO | leaders | up | +0.24 | +0.07 | +0.11 |
| 10:32 | NVO | leaders | up | -0.35 | -0.42 | -0.06 |
| 10:47 | NKE | leaders | up | +0.94 | +0.21 | +0.69 |
| 11:34 | CPRT | leaders | up | -0.26 | -0.19 | -0.29 |
| 11:40 | MA | leaders | up | -0.22 | -0.28 | -0.13 |
| 11:45 | APLD | laggards | down | +0.79 | +1.51 | -0.28 |
| 11:52 | U | leaders | up | +0.25 | +0.35 | +1.03 |
| 13:07 | WULF | laggards | down | -1.95 | -3.09 | -4.19 |

## 2026-08-19

Usable symbol-minutes 64,695/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | HIMS | +13.30 | miss | 09:36 |
| 2 | MSTR | +12.47 | miss | 09:31 |
| 3 | MRK | +12.39 | miss | 09:31 |
| 4 | NBIS | -10.08 | 10:02 | 09:31 |
| 5 | MRVL | +9.64 | miss | 09:31 |
| 6 | CRCL | +9.35 | miss | 09:31 |
| 7 | COIN | +9.34 | miss | 09:34 |
| 8 | BULL | +8.74 | miss | 10:47 |
| 9 | CVNA | +8.16 | miss | 09:33 |
| 10 | STX | -8.08 | 10:14 | 10:11 |
| 11 | MARA | +7.49 | 10:58 | 11:07 |
| 12 | AAOI | -7.23 | 10:02 | 13:08 |
| 13 | CPRT | +7.22 | miss | 09:35 |
| 14 | WDC | -7.08 | 10:16 | 10:14 |
| 15 | DELL | -6.85 | 10:02 | 09:34 |
| 16 | COHR | -6.40 | 10:03 | 11:45 |
| 17 | NOW | +6.24 | miss | 09:41 |
| 18 | RIVN | +6.22 | miss | miss |
| 19 | CRWD | -5.51 | 10:10 | 09:31 |
| 20 | S | -5.41 | miss | 11:43 |

### Radar flags (32)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | AAOI | relative_to_spy | down | +0.84 | -0.56 | -0.12 |
| 10:02 | ALAB | relative_to_spy | down | -1.27 | -1.51 | -0.67 |
| 10:02 | APLD | relative_to_spy | down | +0.87 | +1.07 | +4.83 |
| 10:02 | DELL | relative_to_spy | down | -0.58 | -0.38 | +0.86 |
| 10:02 | INTC | relative_to_spy | down | +0.51 | +0.80 | +1.02 |
| 10:02 | NBIS | relative_to_spy | down | +2.69 | +3.42 | +4.92 |
| 10:02 | SNDK | relative_to_spy | down | -0.26 | -0.57 | +0.61 |
| 10:02 | AI networking and connectivity (ALAB, CRDO, COHR, MRVL, AVGO, ANET) | group_move | down | -0.32 | -0.28 | -0.02 |
| 10:02 | Cybersecurity (CRWD, NET, PANW, S, FTNT, ZS) | group_move | down | -0.95 | -0.54 | -0.06 |
| 10:02 | GPUs and AI compute chips (ARM, INTC, AMD, MRVL, AVGO, QCOM, NVDA, TSM) | group_move | down | +0.18 | +0.23 | +0.67 |
| 10:02 | Memory and storage (SNDK, STX, WDC, MU) | group_move | down | -0.53 | -1.29 | -0.08 |
| 10:02 | Neoclouds and AI hosting (NBIS, APLD, CRWV, IREN, CIFR, WULF, ORCL) | group_move | down | +1.51 | +2.28 | +5.37 |
| 10:02 | Obesity and big pharma (HIMS, MRK, LLY, AMGN, PFE, NVO) | group_move | up | -0.28 | -0.75 | -0.57 |
| 10:02 | Quantum computing (RGTI, IONQ, QUBT, QBTS) | group_move | down | +1.17 | +2.10 | +2.38 |
| 10:03 | COHR | relative_to_spy | down | +1.10 | +0.65 | +0.60 |
| 10:03 | CRDO | relative_to_spy | down | +0.22 | +0.37 | +0.70 |
| 10:03 | Space (PL, LUNR, ASTS, RKLB, IRDM) | group_move | down | +1.99 | +1.25 | +2.16 |
| 10:04 | ARM | relative_to_spy | down | +1.38 | +1.20 | +2.63 |
| 10:05 | RGTI | relative_to_spy | down | +0.55 | +1.86 | +1.95 |
| 10:10 | CRWD | relative_to_spy | down | -0.06 | +0.98 | +1.35 |
| 10:14 | STX | relative_to_spy | down | +0.85 | +0.61 | +1.12 |
| 10:16 | WDC | relative_to_spy | down | +0.47 | +1.42 | +1.14 |
| 10:40 | Space (ASTS, LUNR, PL, RKLB, IRDM) | group_move | up | -1.04 | -0.74 | — |
| 10:42 | NBIS | relative_to_spy | up | -0.08 | +0.42 | +2.21 |
| 10:43 | Bitcoin treasuries and miners (MARA, IREN, RIOT, CLSK, COIN, MSTR) | group_move | up | +2.70 | +5.27 | +5.71 |
| 10:43 | Crypto and exchanges (MARA, RIOT, BULL, CRCL, HOOD, COIN, MSTR) | group_move | up | +2.43 | +4.69 | +4.89 |
| 10:43 | Neoclouds and AI hosting (NBIS, IREN, CRWV, CIFR, APLD, WULF, ORCL) | group_move | up | +0.66 | +2.02 | +3.40 |
| 10:44 | Quantum computing (IONQ, RGTI, QUBT, QBTS) | group_move | up | +0.14 | +0.05 | +0.29 |
| 10:57 | Retail brokers and fintech (COIN, HOOD, BULL, SOFI) | group_move | up | +0.53 | +1.47 | +1.83 |
| 10:58 | MARA | relative_to_spy | up | +2.07 | +3.99 | +4.08 |
| 10:58 | RIOT | relative_to_spy | up | +2.21 | +3.20 | +2.01 |
| 13:27 | Bitcoin treasuries and miners (MSTR, IREN, CLSK, RIOT, COIN, MARA) | group_move | down | +0.36 | -0.11 | -1.15 |

### Movers flags (56)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | MRVL | leaders | up | -2.77 | -2.35 | -1.98 |
| 09:31 | MRK | leaders | up | +2.50 | +1.82 | +2.01 |
| 09:31 | CRCL | leaders | up | +2.94 | +3.68 | +6.52 |
| 09:31 | SNDK | leaders | up | -6.03 | -6.60 | -5.43 |
| 09:31 | AAOI | leaders | up | -6.30 | -5.79 | -5.25 |
| 09:31 | MSTR | leaders | up | +2.10 | +4.55 | +9.38 |
| 09:31 | QCOM | leaders | up | -1.58 | -1.54 | -1.30 |
| 09:31 | HOOD | leaders | up | -0.67 | +0.12 | +3.77 |
| 09:31 | FLNC | leaders | up | -3.43 | -2.48 | -1.58 |
| 09:31 | HD | leaders | up | +0.61 | +1.08 | -0.34 |
| 09:31 | NBIS | laggards | down | -6.82 | -4.91 | -2.26 |
| 09:31 | LUNR | laggards | down | -1.82 | -0.42 | -0.44 |
| 09:31 | RKLB | laggards | down | -2.33 | -0.64 | -0.61 |
| 09:31 | TGT | laggards | down | +8.62 | +7.60 | +8.37 |
| 09:31 | RCAT | laggards | down | -2.30 | -0.70 | +0.11 |
| 09:31 | AVGO | laggards | down | -2.77 | -3.18 | -2.57 |
| 09:31 | SNOW | laggards | down | -0.07 | -0.40 | -0.11 |
| 09:31 | CRWD | laggards | down | -3.92 | -5.02 | -4.37 |
| 09:31 | ASTS | laggards | down | -2.42 | -0.24 | -0.15 |
| 09:31 | RDDT | laggards | down | -0.20 | -1.07 | -0.31 |
| 09:32 | FND | leaders | up | +0.23 | +1.49 | -0.20 |
| 09:32 | LAD | leaders | up | +0.57 | +1.62 | +1.66 |
| 09:32 | CIFR | laggards | down | -3.85 | -1.80 | +0.98 |
| 09:32 | PL | laggards | down | -2.84 | -1.44 | -1.75 |
| 09:33 | ARM | leaders | up | -8.51 | -7.45 | -6.30 |
| 09:33 | CVNA | leaders | up | +0.14 | +2.18 | +2.69 |
| 09:33 | HSAI | leaders | up | -0.34 | +0.67 | +1.22 |
| 09:33 | GS | laggards | down | -0.26 | -0.51 | -0.85 |
| 09:34 | COIN | leaders | up | +1.34 | +3.01 | +7.92 |
| 09:34 | DELL | laggards | down | -5.94 | -5.60 | -4.83 |
| 09:34 | CRWV | laggards | down | -1.70 | -0.56 | +1.16 |
| 09:34 | RIOT | laggards | down | -2.96 | -1.31 | +4.74 |
| 09:35 | TGT | leaders | up | +1.28 | +1.20 | +1.59 |
| 09:35 | CPRT | leaders | up | +2.54 | +3.00 | +2.69 |
| 09:35 | APLD | laggards | down | -3.65 | -3.62 | -1.41 |
| 09:36 | HIMS | leaders | up | +2.62 | +1.64 | +2.69 |
| 09:36 | IREN | laggards | down | -3.07 | -1.03 | +1.59 |
| 09:36 | WULF | laggards | down | -3.00 | -2.17 | +0.90 |
| 09:38 | LLY | leaders | up | +1.21 | +0.80 | -0.32 |
| 09:39 | CLSK | laggards | down | -1.81 | -0.15 | +5.38 |
| 09:41 | NOW | leaders | up | +0.15 | +1.94 | +3.61 |
| 09:50 | AMGN | leaders | up | +0.22 | -0.11 | -0.57 |
| 09:54 | CRDO | laggards | down | -0.61 | +0.45 | -0.09 |
| 09:55 | PFE | leaders | up | +0.38 | -0.16 | -0.83 |
| 09:58 | ALAB | laggards | down | -3.04 | -1.93 | -2.06 |
| 10:03 | SPOT | leaders | up | +0.10 | +0.20 | -0.20 |
| 10:09 | PANW | laggards | down | -0.34 | +0.91 | +1.56 |
| 10:11 | STX | laggards | down | +0.56 | -0.83 | -0.11 |
| 10:14 | WDC | laggards | down | +1.49 | +2.08 | +1.95 |
| 10:40 | DDOG | laggards | down | +0.25 | +0.09 | -0.13 |
| 10:47 | BULL | leaders | up | +1.50 | +1.26 | +1.43 |
| 11:07 | MARA | leaders | up | +1.36 | +3.47 | +2.43 |
| 11:43 | S | laggards | down | +0.45 | +0.04 | -0.67 |
| 11:45 | COHR | laggards | down | -0.22 | +0.04 | -1.56 |
| 13:08 | AAOI | laggards | down | -1.12 | -1.68 | -2.37 |
| 15:15 | RGTI | laggards | down | +1.56 | — | — |

## 2026-08-20

Usable symbol-minutes 64,568/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | MARA | +16.28 | miss | 09:31 |
| 2 | RIOT | +9.17 | miss | 09:31 |
| 3 | CIFR | +9.15 | miss | 15:27 |
| 4 | CLSK | +8.81 | miss | 09:31 |
| 5 | MSTR | +8.65 | miss | 09:31 |
| 6 | COIN | +8.48 | miss | 09:31 |
| 7 | WMT | -8.31 | miss | 09:31 |
| 8 | DE | +7.78 | miss | 09:32 |
| 9 | CRCL | +7.29 | miss | 09:31 |
| 10 | WULF | +6.97 | miss | 09:36 |
| 11 | MRVL | +6.63 | miss | 09:32 |
| 12 | AAOI | +6.60 | 10:25 | 10:37 |
| 13 | HSAI | +5.62 | miss | 09:31 |
| 14 | MU | +4.81 | miss | miss |
| 15 | FLNC | -4.79 | miss | 09:31 |
| 16 | CRWD | -4.76 | miss | 09:34 |
| 17 | RGTI | -4.66 | miss | 10:17 |
| 18 | KMX | +4.40 | miss | 09:51 |
| 19 | ZS | -4.39 | miss | 09:37 |
| 20 | LCID | -4.14 | miss | 13:18 |

### Radar flags (6)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | HIMS | relative_to_spy | up | -1.21 | -1.03 | -2.64 |
| 10:21 | BULL | relative_to_spy | down | -1.93 | -2.00 | -2.43 |
| 10:23 | Memory and storage (STX, WDC, SNDK, MU) | group_move | up | +0.26 | -0.30 | -0.09 |
| 10:25 | AAOI | relative_to_spy | up | +1.02 | +1.91 | +0.90 |
| 11:13 | Quantum computing (RGTI, QUBT, IONQ, QBTS) | group_move | down | -0.44 | +0.05 | +0.95 |
| 11:20 | Crypto and exchanges (MSTR, CRCL, COIN, MARA, RIOT, BULL) | group_move | up | -0.62 | -0.75 | -0.10 |

### Movers flags (52)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | BULL | leaders | up | +3.59 | -3.61 | -3.55 |
| 09:31 | COIN | leaders | up | +0.26 | -0.72 | +1.85 |
| 09:31 | MSTR | leaders | up | +0.96 | -0.54 | +2.08 |
| 09:31 | HSAI | leaders | up | +3.58 | +0.65 | -0.26 |
| 09:31 | CLSK | leaders | up | -0.16 | -0.87 | +0.36 |
| 09:31 | MARA | leaders | up | +4.31 | +4.34 | +7.23 |
| 09:31 | HOOD | leaders | up | -2.21 | -4.26 | -4.45 |
| 09:31 | CRCL | leaders | up | +0.61 | +0.19 | +3.55 |
| 09:31 | SMCI | leaders | up | -1.17 | -1.31 | -4.11 |
| 09:31 | RIOT | leaders | up | +1.67 | +2.96 | +3.90 |
| 09:31 | WMT | laggards | down | -1.03 | -1.23 | -1.35 |
| 09:31 | BABA | laggards | down | +2.72 | +2.03 | +3.16 |
| 09:31 | FLNC | laggards | down | -0.59 | -1.04 | -2.69 |
| 09:31 | LOW | laggards | down | +2.66 | +2.16 | +3.42 |
| 09:31 | FND | laggards | down | -0.26 | -0.28 | +0.61 |
| 09:31 | COST | laggards | down | +1.19 | +1.19 | +1.54 |
| 09:31 | HD | laggards | down | +0.49 | +0.21 | +1.00 |
| 09:31 | RCAT | laggards | down | -1.27 | -2.40 | -3.89 |
| 09:31 | ARM | laggards | down | +0.91 | +0.95 | +1.06 |
| 09:31 | LUNR | laggards | down | -1.29 | -1.87 | -3.03 |
| 09:32 | MRVL | leaders | up | -3.80 | -0.90 | -1.13 |
| 09:32 | DE | leaders | up | +1.41 | +4.40 | +5.68 |
| 09:32 | UAA | laggards | down | +0.48 | +0.41 | +0.69 |
| 09:33 | OXY | leaders | up | +0.39 | +0.14 | +0.25 |
| 09:33 | MDB | laggards | down | -0.56 | +0.65 | -1.10 |
| 09:34 | CRWD | laggards | down | +0.85 | +0.43 | -2.30 |
| 09:34 | RDDT | laggards | down | -0.58 | -1.68 | -2.37 |
| 09:35 | COP | leaders | up | +0.83 | +1.12 | +1.18 |
| 09:35 | RKLB | laggards | down | -0.72 | -0.29 | -1.78 |
| 09:36 | WULF | leaders | up | -1.35 | -1.06 | -1.22 |
| 09:37 | HIMS | leaders | up | +2.01 | +1.06 | +0.58 |
| 09:37 | ZS | laggards | down | +0.59 | +0.34 | -0.66 |
| 09:38 | NET | laggards | down | +1.47 | +1.45 | -0.01 |
| 09:42 | RBLX | laggards | down | +0.87 | +0.54 | +0.55 |
| 09:43 | F | laggards | down | -1.45 | -1.95 | -0.96 |
| 09:46 | NBIS | laggards | down | +0.45 | +1.11 | -1.42 |
| 09:51 | KMX | leaders | up | -1.60 | +0.46 | +0.37 |
| 09:53 | IONQ | laggards | down | -0.61 | -1.78 | -3.20 |
| 09:53 | COHR | laggards | down | +3.02 | +3.78 | +2.51 |
| 09:54 | INTC | laggards | down | +1.26 | +1.56 | +1.92 |
| 09:58 | OKLO | laggards | down | -0.44 | -0.24 | -1.17 |
| 10:11 | LULU | laggards | down | -0.47 | -0.07 | +0.48 |
| 10:17 | RGTI | laggards | down | -1.12 | -3.38 | -3.64 |
| 10:26 | STX | leaders | up | -0.25 | -0.83 | -0.55 |
| 10:37 | AAOI | leaders | up | -0.31 | -1.02 | -0.64 |
| 11:09 | QBTS | laggards | down | -0.73 | -0.29 | +0.79 |
| 11:21 | QUBT | laggards | down | -0.07 | +0.37 | +0.38 |
| 11:23 | ASTS | laggards | down | -0.46 | -0.39 | -0.29 |
| 11:31 | ONON | laggards | down | -0.47 | +0.15 | -0.35 |
| 12:39 | PL | laggards | down | +0.26 | +0.79 | +0.71 |
| 13:18 | LCID | laggards | down | +0.93 | +2.17 | +1.63 |
| 15:27 | CIFR | leaders | up | +3.60 | — | — |

## 2026-08-21

Usable symbol-minutes 64,422/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | HOOD | +13.29 | 10:02 | 09:31 |
| 2 | RGTI | +11.08 | miss | 09:36 |
| 3 | QUBT | +9.17 | miss | 09:38 |
| 4 | BABA | -8.98 | miss | 09:31 |
| 5 | CIFR | -8.81 | 10:02 | 09:54 |
| 6 | QBTS | +7.99 | miss | 09:34 |
| 7 | COIN | +7.74 | miss | 09:31 |
| 8 | IONQ | +7.61 | miss | 09:36 |
| 9 | MRVL | -5.97 | 10:22 | 09:35 |
| 10 | RIOT | -5.96 | 10:17 | 10:26 |
| 11 | MSTR | +5.69 | miss | 09:31 |
| 12 | HIMS | +5.62 | miss | 10:48 |
| 13 | RIVN | +5.59 | miss | 09:55 |
| 14 | APLD | -5.42 | 10:17 | 09:57 |
| 15 | WULF | -5.33 | 10:39 | 10:37 |
| 16 | CLSK | -5.33 | 10:15 | 10:21 |
| 17 | SOFI | +5.17 | 10:02 | 09:49 |
| 18 | ASTS | +5.09 | miss | 09:31 |
| 19 | CRCL | +4.75 | miss | 09:31 |
| 20 | TSLA | +4.73 | miss | 10:31 |

### Radar flags (21)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | BULL | relative_to_spy | up | -3.15 | -4.02 | -4.12 |
| 10:02 | CIFR | relative_to_spy | down | -3.47 | -6.69 | -4.63 |
| 10:02 | HOOD | relative_to_spy | up | -2.05 | -1.60 | -1.52 |
| 10:02 | SOFI | relative_to_spy | up | -0.24 | -0.61 | +0.03 |
| 10:02 | Crypto and exchanges (HOOD, BULL, COIN, CRCL, MARA, MSTR) | group_move | up | -2.28 | -2.48 | -2.91 |
| 10:02 | Retail brokers and fintech (HOOD, BULL, SOFI, COIN, SCHW) | group_move | up | -1.37 | -1.22 | -1.31 |
| 10:04 | Neoclouds and AI hosting (CIFR, IREN, APLD, WULF, CRWV, NBIS) | group_move | down | -2.45 | -4.35 | -3.26 |
| 10:05 | IREN | relative_to_spy | down | -2.26 | -4.30 | -4.15 |
| 10:14 | Bitcoin treasuries and miners (IREN, CLSK, RIOT, MARA, MSTR, COIN) | group_move | down | -3.79 | -1.85 | -2.99 |
| 10:15 | CLSK | relative_to_spy | down | -5.16 | -3.14 | -4.41 |
| 10:15 | Space (ASTS, PL, LUNR, RKLB) | group_move | down | +0.03 | +1.51 | +2.32 |
| 10:17 | APLD | relative_to_spy | down | -2.02 | -0.52 | -1.20 |
| 10:17 | RIOT | relative_to_spy | down | -4.01 | -1.94 | -3.90 |
| 10:18 | AAOI | relative_to_spy | down | -0.66 | -0.59 | -0.34 |
| 10:19 | AI networking and connectivity (MRVL, ALAB, CRDO, COHR, ANET, AVGO) | group_move | down | -0.11 | -0.70 | -0.11 |
| 10:21 | MARA | relative_to_spy | down | -2.71 | -3.81 | -2.32 |
| 10:21 | Memory and storage (WDC, MU, STX, SNDK) | group_move | down | +0.85 | +0.80 | +0.98 |
| 10:22 | MRVL | relative_to_spy | down | -0.27 | -1.24 | -0.81 |
| 10:22 | Crypto and exchanges (RIOT, MARA, CRCL, BULL, MSTR, COIN, HOOD) | group_move | down | +0.30 | -0.30 | -0.37 |
| 10:39 | WULF | relative_to_spy | down | -2.51 | -2.74 | -2.93 |
| 11:14 | Quantum computing (RGTI, QUBT, QBTS, IONQ) | group_move | up | +0.41 | +1.35 | +1.02 |

### Movers flags (67)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | HOOD | leaders | up | +7.11 | +5.29 | +4.83 |
| 09:31 | COIN | leaders | up | +3.59 | +1.99 | +2.57 |
| 09:31 | IREN | leaders | up | -2.38 | -5.97 | -8.74 |
| 09:31 | MSTR | leaders | up | +0.26 | +0.88 | +1.82 |
| 09:31 | CRCL | leaders | up | +4.39 | +2.37 | +0.06 |
| 09:31 | CIFR | leaders | up | -7.65 | -10.51 | -13.09 |
| 09:31 | MARA | leaders | up | +4.13 | -1.16 | -4.77 |
| 09:31 | LUNR | leaders | up | -0.65 | -2.93 | -1.75 |
| 09:31 | WULF | leaders | up | -1.88 | -3.76 | -9.30 |
| 09:31 | ASTS | leaders | up | +0.38 | -2.17 | -0.52 |
| 09:31 | BABA | laggards | down | -2.13 | -2.98 | -2.64 |
| 09:31 | APP | laggards | down | -0.15 | -0.62 | -0.25 |
| 09:31 | BULL | laggards | down | +8.99 | +6.41 | +4.88 |
| 09:31 | CRWD | laggards | down | +0.68 | +0.56 | +0.55 |
| 09:31 | AMGN | laggards | down | +1.35 | +1.89 | +1.90 |
| 09:31 | LLY | laggards | down | +1.08 | +1.85 | +2.37 |
| 09:31 | NFLX | laggards | down | -0.66 | -0.09 | +0.24 |
| 09:31 | PINS | laggards | down | +0.44 | +0.52 | +1.55 |
| 09:31 | MSFT | laggards | down | +0.69 | +0.90 | +0.77 |
| 09:31 | AMZN | laggards | down | -0.10 | +0.25 | -0.37 |
| 09:32 | RIOT | leaders | up | -0.97 | -5.55 | -8.41 |
| 09:32 | CLSK | leaders | up | -1.57 | -6.34 | -9.68 |
| 09:32 | DE | laggards | down | +1.52 | +1.31 | +1.90 |
| 09:32 | AAPL | laggards | down | -0.48 | -0.35 | +0.38 |
| 09:32 | RBLX | laggards | down | +0.97 | -0.74 | +0.46 |
| 09:33 | CVNA | laggards | down | -0.07 | -0.83 | -0.78 |
| 09:33 | SNDK | laggards | down | +0.09 | +0.32 | -0.09 |
| 09:33 | INTC | laggards | down | -1.25 | -0.93 | -1.35 |
| 09:34 | QBTS | leaders | up | -0.19 | -0.06 | +1.44 |
| 09:34 | PDD | laggards | down | -0.65 | -0.68 | -0.21 |
| 09:35 | MRVL | laggards | down | -2.13 | -5.00 | -5.73 |
| 09:36 | RGTI | leaders | up | +0.92 | +1.02 | +3.56 |
| 09:36 | IONQ | leaders | up | +0.34 | +0.26 | +2.22 |
| 09:36 | PYPL | laggards | down | +0.96 | +1.03 | +0.15 |
| 09:37 | LCID | laggards | down | +0.36 | -0.49 | +0.83 |
| 09:38 | QUBT | leaders | up | +0.99 | +0.23 | +2.68 |
| 09:38 | AAOI | laggards | down | +0.80 | -2.89 | -1.67 |
| 09:38 | SNOW | laggards | down | +0.79 | +0.83 | +2.11 |
| 09:39 | CRDO | laggards | down | +0.06 | -0.59 | -0.24 |
| 09:40 | S | laggards | down | -0.57 | +0.43 | +0.66 |
| 09:41 | WDC | laggards | down | -0.48 | -0.46 | +0.57 |
| 09:42 | DDOG | laggards | down | +0.76 | +1.66 | +1.53 |
| 09:42 | NET | laggards | down | +1.09 | +2.99 | +3.76 |
| 09:44 | DASH | laggards | down | +1.22 | +2.34 | +2.30 |
| 09:45 | PANW | laggards | down | +0.98 | +2.05 | +2.29 |
| 09:46 | BULL | leaders | up | +0.59 | +0.27 | -0.99 |
| 09:46 | FTNT | laggards | down | +0.71 | +1.39 | +1.85 |
| 09:46 | SPOT | laggards | down | +1.47 | +2.19 | +2.10 |
| 09:47 | COHR | leaders | up | -2.04 | -4.23 | -6.37 |
| 09:49 | SOFI | leaders | up | +1.00 | +0.86 | +1.39 |
| 09:50 | NBIS | leaders | up | -4.59 | -3.80 | -3.04 |
| 09:50 | NOW | laggards | down | +0.98 | +1.39 | +1.93 |
| 09:53 | TDOC | laggards | down | -0.62 | +0.78 | +0.52 |
| 09:54 | CIFR | laggards | down | -3.78 | -7.85 | -6.08 |
| 09:54 | WMT | laggards | down | -0.11 | -0.35 | -0.55 |
| 09:55 | RIVN | leaders | up | -1.06 | -0.32 | +1.14 |
| 09:57 | APLD | laggards | down | -2.82 | -4.14 | -2.91 |
| 09:59 | ARM | laggards | down | -1.07 | -1.51 | -1.49 |
| 10:13 | ALAB | laggards | down | -2.08 | -2.15 | — |
| 10:21 | CLSK | laggards | down | -2.29 | -2.64 | -1.84 |
| 10:26 | RIOT | laggards | down | -1.27 | -1.33 | -2.30 |
| 10:30 | CRWV | laggards | down | +0.63 | +1.80 | +1.40 |
| 10:31 | TSLA | leaders | up | -0.02 | -0.68 | +0.45 |
| 10:37 | WULF | laggards | down | -3.23 | -3.33 | -3.24 |
| 10:40 | IREN | laggards | down | -0.03 | -0.81 | -0.72 |
| 10:43 | LULU | leaders | up | +1.03 | +0.60 | -0.07 |
| 10:48 | HIMS | leaders | up | +0.19 | +1.05 | +3.08 |

## 2026-08-24

Usable symbol-minutes 64,506/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | AAOI | -13.48 | miss | 09:31 |
| 2 | ASTS | -8.88 | miss | 11:48 |
| 3 | LUNR | -8.77 | miss | 09:31 |
| 4 | RGTI | -8.30 | miss | 11:33 |
| 5 | IONQ | -8.18 | miss | 09:34 |
| 6 | QBTS | -8.09 | miss | 11:49 |
| 7 | HIMS | -7.70 | miss | 09:32 |
| 8 | QUBT | -7.33 | miss | 09:43 |
| 9 | LCID | -7.33 | miss | 13:02 |
| 10 | RCAT | -6.88 | miss | 09:36 |
| 11 | MDB | -6.24 | miss | 11:31 |
| 12 | STX | -6.22 | miss | 09:31 |
| 13 | SNDK | -6.16 | miss | 09:31 |
| 14 | SNAP | +5.83 | miss | 10:24 |
| 15 | CIEN | -5.73 | miss | 09:31 |
| 16 | RKLB | -5.62 | miss | miss |
| 17 | MU | -5.53 | miss | 09:31 |
| 18 | OKLO | -5.41 | miss | miss |
| 19 | SMCI | -5.26 | 10:03 | 09:50 |
| 20 | WDC | -4.94 | miss | 09:46 |

### Radar flags (8)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | Memory and storage (STX, WDC, MU, SNDK) | group_move | down | +0.84 | +1.52 | +2.82 |
| 10:03 | SMCI | relative_to_spy | down | +1.48 | +1.65 | +3.22 |
| 10:03 | Quantum computing (QUBT, QBTS, RGTI, IONQ) | group_move | down | +0.96 | +0.99 | +0.28 |
| 10:16 | Crypto and exchanges (MARA, RIOT, MSTR, CRCL, HOOD, COIN, BULL) | group_move | up | +0.55 | +0.68 | -0.17 |
| 10:23 | Bitcoin treasuries and miners (MARA, MSTR, RIOT, CLSK, COIN, IREN) | group_move | up | -0.80 | +0.20 | -0.10 |
| 10:35 | AAOI | relative_to_spy | up | +0.30 | +0.02 | +1.45 |
| 10:39 | MARA | relative_to_spy | up | -3.62 | -2.80 | -3.07 |
| 12:00 | Crypto and exchanges (CRCL, MARA, MSTR, COIN, BULL, HOOD, RIOT) | group_move | down | +0.93 | -0.33 | -1.12 |

### Movers flags (56)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | CRCL | leaders | up | -2.98 | -0.17 | +0.64 |
| 09:31 | MSTR | leaders | up | -0.09 | +2.90 | +4.02 |
| 09:31 | COIN | leaders | up | -2.35 | -1.19 | -1.94 |
| 09:31 | MA | leaders | up | +0.84 | +0.80 | +0.82 |
| 09:31 | UNH | leaders | up | -0.04 | -0.16 | -0.14 |
| 09:31 | RBLX | leaders | up | +0.50 | +0.05 | +1.52 |
| 09:31 | UAA | leaders | up | -0.97 | -1.32 | -2.76 |
| 09:31 | V | leaders | up | +0.93 | +1.01 | +1.33 |
| 09:31 | PDD | leaders | up | -2.22 | -1.11 | -2.53 |
| 09:31 | LOW | leaders | up | +0.22 | +0.10 | -0.65 |
| 09:31 | AAOI | laggards | down | -1.29 | +2.68 | +4.17 |
| 09:31 | SNDK | laggards | down | -3.14 | -1.84 | -0.34 |
| 09:31 | COHR | laggards | down | -1.07 | -0.13 | +2.06 |
| 09:31 | LUNR | laggards | down | -1.62 | -1.72 | -1.21 |
| 09:31 | CRDO | laggards | down | -1.15 | -0.80 | +1.32 |
| 09:31 | ALAB | laggards | down | -0.15 | +1.06 | +3.10 |
| 09:31 | NBIS | laggards | down | -2.25 | -1.54 | +0.42 |
| 09:31 | CIEN | laggards | down | -2.70 | -1.14 | -0.48 |
| 09:31 | STX | laggards | down | -3.74 | -2.64 | -1.96 |
| 09:31 | MU | laggards | down | -2.97 | -2.72 | -2.36 |
| 09:32 | DELL | leaders | up | -5.50 | -3.57 | -4.39 |
| 09:32 | AXP | leaders | up | +0.80 | +1.19 | +0.61 |
| 09:32 | HIMS | laggards | down | -3.34 | -1.46 | -1.36 |
| 09:32 | MRVL | laggards | down | +0.34 | +0.80 | +1.53 |
| 09:33 | RIOT | leaders | up | -0.59 | +2.04 | +3.11 |
| 09:33 | HUM | leaders | up | +0.27 | +0.39 | -0.07 |
| 09:33 | WULF | leaders | up | -2.18 | +0.12 | +0.60 |
| 09:34 | FND | leaders | up | -0.06 | -0.71 | -0.80 |
| 09:34 | IONQ | laggards | down | -0.80 | -0.12 | -0.11 |
| 09:35 | TGT | leaders | up | +0.90 | +1.18 | +1.28 |
| 09:36 | CRWD | leaders | up | -2.21 | -1.74 | -2.02 |
| 09:36 | RCAT | laggards | down | -1.48 | -0.77 | -0.60 |
| 09:39 | LYFT | leaders | up | -0.48 | -0.24 | -1.04 |
| 09:40 | CVNA | leaders | up | +0.55 | +0.55 | +0.69 |
| 09:41 | DIS | leaders | up | +1.69 | +0.56 | -0.00 |
| 09:43 | WMT | leaders | up | -0.91 | -1.11 | -0.81 |
| 09:43 | QUBT | laggards | down | +0.65 | +0.96 | +0.18 |
| 09:45 | ELV | leaders | up | -0.91 | — | -1.47 |
| 09:46 | DE | leaders | up | -0.31 | +0.01 | -0.70 |
| 09:46 | WDC | laggards | down | -0.04 | +0.47 | +1.51 |
| 09:47 | HD | leaders | up | -0.14 | -0.72 | -1.30 |
| 09:48 | WFC | leaders | up | +0.64 | -0.17 | -0.62 |
| 09:50 | SMCI | laggards | down | -0.36 | -0.22 | +1.85 |
| 09:51 | SCHW | leaders | up | +0.19 | -0.31 | -0.82 |
| 10:00 | CRM | leaders | up | -0.47 | -0.65 | -1.35 |
| 10:04 | LULU | leaders | up | -0.29 | -1.30 | -1.87 |
| 10:06 | MARA | leaders | up | +4.38 | +0.39 | +0.49 |
| 10:24 | SNAP | leaders | up | -0.14 | +0.95 | +0.61 |
| 10:33 | CLSK | leaders | up | -0.71 | +1.12 | +0.31 |
| 10:44 | DASH | leaders | up | +0.05 | -0.06 | +0.39 |
| 11:31 | MDB | laggards | down | -0.47 | -0.96 | -0.22 |
| 11:33 | RGTI | laggards | down | -0.88 | -1.40 | -2.06 |
| 11:48 | ASTS | laggards | down | -1.55 | -1.47 | -2.34 |
| 11:49 | QBTS | laggards | down | -0.75 | -1.16 | -2.02 |
| 11:52 | COST | leaders | up | -0.02 | +0.34 | +0.32 |
| 13:02 | LCID | laggards | down | +0.86 | -0.32 | +0.20 |

## 2026-08-25

Usable symbol-minutes 64,437/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | OKLO | +11.22 | miss | 10:30 |
| 2 | SMCI | +9.04 | 10:02 | 09:33 |
| 3 | HOOD | +7.85 | miss | 09:37 |
| 4 | APLD | +6.97 | miss | 09:51 |
| 5 | SNAP | +6.73 | miss | 14:53 |
| 6 | CLSK | +6.55 | miss | 10:28 |
| 7 | RIOT | +6.18 | miss | 10:47 |
| 8 | RDDT | +6.07 | miss | 10:24 |
| 9 | CIFR | +5.87 | miss | 09:33 |
| 10 | IREN | +5.71 | miss | 09:37 |
| 11 | MARA | +5.49 | 10:35 | 10:26 |
| 12 | WULF | +5.11 | miss | 09:57 |
| 13 | UAA | -4.98 | miss | 09:31 |
| 14 | NBIS | +4.92 | miss | 09:31 |
| 15 | AAOI | +4.81 | miss | 09:31 |
| 16 | ZS | -4.66 | miss | 10:38 |
| 17 | AMD | +4.59 | miss | 09:31 |
| 18 | CRCL | +4.58 | miss | 13:46 |
| 19 | MRVL | +4.52 | miss | 09:31 |
| 20 | BULL | +4.49 | 10:27 | 10:23 |

### Radar flags (7)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | SMCI | relative_to_spy | up | -0.40 | +0.47 | +0.63 |
| 10:02 | Crypto and exchanges (HOOD, BULL, MARA, RIOT, MSTR, COIN) | group_move | up | +2.36 | +3.38 | +4.11 |
| 10:02 | Space (ASTS, LUNR, RKLB, PL) | group_move | down | -0.59 | +0.28 | +0.45 |
| 10:27 | BULL | relative_to_spy | up | -0.39 | -1.83 | -0.58 |
| 10:27 | Retail brokers and fintech (BULL, COIN, SOFI, HOOD, PYPL, SCHW) | group_move | up | +0.45 | +0.03 | +0.32 |
| 10:29 | Bitcoin treasuries and miners (COIN, MARA, MSTR, CLSK, RIOT) | group_move | up | +0.86 | +1.07 | +1.62 |
| 10:35 | MARA | relative_to_spy | up | -0.86 | -0.61 | +0.15 |

### Movers flags (69)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | FLNC | leaders | up | -3.76 | -4.15 | -2.20 |
| 09:31 | NBIS | leaders | up | -0.47 | -0.79 | -0.30 |
| 09:31 | MRVL | leaders | up | +2.96 | +2.19 | +2.59 |
| 09:31 | COHR | leaders | up | +1.92 | +0.63 | +0.51 |
| 09:31 | SNDK | leaders | up | -1.10 | -2.63 | -1.72 |
| 09:31 | PL | leaders | up | -2.19 | -2.67 | -3.18 |
| 09:31 | AMD | leaders | up | +0.88 | +0.69 | +2.00 |
| 09:31 | CIEN | leaders | up | +0.53 | -0.46 | +0.29 |
| 09:31 | AAOI | leaders | up | +3.15 | +2.27 | +2.55 |
| 09:31 | INTC | leaders | up | -0.77 | -1.11 | -1.06 |
| 09:31 | LULU | laggards | down | +0.17 | +0.50 | -0.69 |
| 09:31 | NKE | laggards | down | -0.22 | +1.08 | +0.51 |
| 09:31 | DECK | laggards | down | -0.64 | +0.04 | -0.73 |
| 09:31 | ONON | laggards | down | +0.42 | +1.19 | +0.47 |
| 09:31 | TGT | laggards | down | -1.95 | -1.02 | -0.70 |
| 09:31 | MSTR | laggards | down | +1.94 | +5.10 | +5.28 |
| 09:31 | MARA | laggards | down | +3.37 | +7.19 | +8.12 |
| 09:31 | CPRT | laggards | down | +0.10 | +1.13 | +1.41 |
| 09:31 | UAA | laggards | down | -0.68 | -0.51 | -1.39 |
| 09:31 | RIOT | laggards | down | +3.80 | +5.09 | +8.17 |
| 09:32 | WDC | leaders | up | -2.13 | -3.82 | -1.72 |
| 09:32 | DELL | leaders | up | +1.88 | +0.86 | +1.35 |
| 09:32 | STX | leaders | up | -0.20 | -1.53 | +0.40 |
| 09:32 | ADBE | laggards | down | +0.11 | +0.55 | +0.68 |
| 09:32 | XOM | laggards | down | +0.68 | +0.55 | +0.43 |
| 09:33 | SMCI | leaders | up | +3.55 | +4.25 | +4.46 |
| 09:33 | CIFR | leaders | up | -1.08 | +0.60 | +1.57 |
| 09:33 | COIN | laggards | down | +2.18 | +5.66 | +4.96 |
| 09:34 | MU | leaders | up | -1.61 | -1.83 | -1.05 |
| 09:34 | ALAB | leaders | up | -0.68 | -1.52 | -0.89 |
| 09:35 | AI | laggards | down | +0.42 | +0.77 | +1.02 |
| 09:35 | LOW | laggards | down | +0.95 | +0.79 | +1.19 |
| 09:36 | OXY | laggards | down | +0.27 | +0.14 | +0.06 |
| 09:37 | IREN | leaders | up | +0.33 | +1.35 | +2.29 |
| 09:37 | HOOD | leaders | up | -0.05 | +2.55 | +2.95 |
| 09:37 | LAD | laggards | down | — | — | +2.27 |
| 09:38 | SONY | laggards | down | +0.37 | -0.14 | +0.12 |
| 09:39 | GM | laggards | down | +0.48 | +0.36 | +0.74 |
| 09:40 | ARM | leaders | up | -0.13 | -0.50 | +0.06 |
| 09:40 | WMT | laggards | down | +0.33 | -0.32 | -0.10 |
| 09:43 | CRWV | leaders | up | +0.62 | -0.01 | -0.57 |
| 09:44 | LUNR | laggards | down | -0.03 | +0.69 | +2.46 |
| 09:46 | DE | laggards | down | -0.11 | -0.27 | -0.56 |
| 09:47 | CRDO | leaders | up | -1.83 | -1.79 | -2.05 |
| 09:50 | CRCL | laggards | down | +2.43 | +6.38 | +6.35 |
| 09:51 | APLD | leaders | up | +0.20 | +1.76 | +1.58 |
| 09:52 | U | laggards | down | -0.03 | +0.35 | +0.48 |
| 09:56 | CVNA | leaders | up | -1.04 | -0.98 | +0.14 |
| 09:57 | WULF | leaders | up | +0.13 | +1.07 | +0.86 |
| 10:01 | HIMS | leaders | up | -1.68 | -0.69 | +0.02 |
| 10:04 | RKLB | laggards | down | +0.55 | +0.88 | +0.71 |
| 10:08 | PANW | laggards | down | +0.96 | +0.92 | +0.49 |
| 10:17 | ASTS | laggards | down | +1.38 | +1.82 | +1.31 |
| 10:23 | BULL | leaders | up | +1.37 | +0.27 | +1.18 |
| 10:24 | RDDT | leaders | up | +0.06 | +0.90 | +1.43 |
| 10:26 | MARA | leaders | up | +1.08 | +1.84 | +2.05 |
| 10:28 | CLSK | leaders | up | +0.83 | +2.20 | +2.08 |
| 10:30 | OKLO | leaders | up | +3.54 | +4.19 | +4.14 |
| 10:31 | SNOW | laggards | down | +0.56 | +0.21 | +0.09 |
| 10:38 | ZS | laggards | down | +0.02 | -0.00 | -1.00 |
| 10:47 | RIOT | leaders | up | +0.18 | +1.69 | +2.11 |
| 10:49 | S | laggards | down | +0.07 | +0.09 | -0.83 |
| 11:32 | LYFT | laggards | down | +1.30 | +1.26 | +1.28 |
| 12:16 | CRWD | laggards | down | -0.29 | -0.64 | -2.29 |
| 13:11 | URI | laggards | down | — | -0.11 | -0.30 |
| 13:46 | CRCL | leaders | up | +0.24 | +0.57 | -0.94 |
| 14:01 | RGTI | leaders | up | -0.57 | -1.12 | — |
| 14:53 | SNAP | leaders | up | +1.47 | +0.54 | — |
| 15:19 | LCID | leaders | up | -0.44 | — | — |

## 2026-08-26

Usable symbol-minutes 64,423/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | QBTS | -9.53 | miss | 09:32 |
| 2 | SNAP | -8.47 | 10:02 | 09:35 |
| 3 | APLD | -6.89 | miss | 09:36 |
| 4 | HSAI | -6.69 | miss | 09:35 |
| 5 | IREN | -6.25 | miss | 09:31 |
| 6 | HIMS | -6.07 | miss | 09:31 |
| 7 | OKLO | -6.05 | 10:20 | 10:40 |
| 8 | RGTI | -5.93 | miss | 10:09 |
| 9 | LCID | -5.92 | miss | 09:48 |
| 10 | ANET | +5.90 | miss | 09:50 |
| 11 | MARA | -5.18 | miss | 09:31 |
| 12 | IONQ | -4.83 | miss | 10:01 |
| 13 | CLSK | -4.49 | miss | 09:31 |
| 14 | RDDT | -4.39 | miss | 13:30 |
| 15 | CIEN | +4.20 | miss | 09:33 |
| 16 | RBLX | -4.01 | miss | miss |
| 17 | WDC | +4.00 | miss | 09:31 |
| 18 | ARM | +3.91 | miss | 12:31 |
| 19 | NBIS | -3.64 | miss | 10:32 |
| 20 | LLY | -3.61 | miss | 09:37 |

### Radar flags (5)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | SNAP | relative_to_spy | down | +0.21 | -0.29 | -1.85 |
| 10:02 | Cybersecurity (FTNT, NET, ZS, CRWD, PANW, S) | group_move | up | -0.32 | -0.01 | -0.31 |
| 10:20 | OKLO | relative_to_spy | down | -1.59 | -1.92 | -3.05 |
| 10:28 | Quantum computing (QBTS, RGTI, QUBT, IONQ) | group_move | down | +0.05 | -0.27 | -0.90 |
| 11:07 | CRCL | relative_to_spy | down | +1.92 | +1.36 | +1.33 |

### Movers flags (67)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | META | leaders | up | -2.80 | -2.46 | -1.05 |
| 09:31 | ORCL | leaders | up | +0.64 | -0.36 | -0.74 |
| 09:31 | TTWO | leaders | up | -0.91 | -0.37 | -1.79 |
| 09:31 | WDC | leaders | up | +1.55 | +0.31 | +1.18 |
| 09:31 | DELL | leaders | up | +1.54 | +1.39 | +0.93 |
| 09:31 | OKLO | leaders | up | -0.77 | -3.81 | -6.03 |
| 09:31 | UAA | leaders | up | -0.16 | +0.35 | -0.51 |
| 09:31 | DASH | leaders | up | +0.28 | -0.01 | -0.14 |
| 09:31 | RBLX | leaders | up | -2.12 | -2.21 | -3.70 |
| 09:31 | STX | leaders | up | +0.87 | +0.24 | +1.44 |
| 09:31 | SCHW | laggards | down | +1.38 | +1.63 | +1.72 |
| 09:31 | MDB | laggards | down | +3.58 | +3.54 | +3.21 |
| 09:31 | MARA | laggards | down | +0.89 | +1.06 | -1.43 |
| 09:31 | ZS | laggards | down | +3.39 | +2.57 | +2.63 |
| 09:31 | NOW | laggards | down | +1.02 | +0.75 | +1.02 |
| 09:31 | HIMS | laggards | down | +0.43 | -0.95 | -1.91 |
| 09:31 | CLSK | laggards | down | +0.08 | +0.20 | -0.65 |
| 09:31 | PANW | laggards | down | +2.91 | +2.18 | +2.15 |
| 09:31 | SNOW | laggards | down | +2.10 | +1.93 | +1.76 |
| 09:31 | IREN | laggards | down | -1.54 | -1.81 | -2.55 |
| 09:32 | UBER | leaders | up | -1.84 | -2.13 | -2.40 |
| 09:32 | MSTR | laggards | down | +1.40 | +0.99 | -0.04 |
| 09:32 | QBTS | laggards | down | -2.34 | -4.58 | -5.76 |
| 09:32 | COIN | laggards | down | +0.91 | +1.12 | -0.11 |
| 09:33 | CIEN | leaders | up | -1.22 | -2.09 | -1.49 |
| 09:33 | APP | leaders | up | -1.52 | -1.42 | -2.39 |
| 09:33 | RIOT | laggards | down | +1.92 | +1.25 | +0.35 |
| 09:33 | WULF | laggards | down | +2.40 | +1.47 | +1.16 |
| 09:34 | DDOG | leaders | up | +3.32 | +0.92 | +1.27 |
| 09:35 | RDDT | leaders | up | -2.91 | -3.90 | -5.27 |
| 09:35 | SNAP | laggards | down | -3.97 | -4.26 | -5.84 |
| 09:35 | HSAI | laggards | down | -1.75 | -2.67 | -4.15 |
| 09:35 | CIFR | laggards | down | +1.35 | +0.79 | +1.28 |
| 09:35 | MRK | laggards | down | +0.88 | +1.11 | +0.40 |
| 09:36 | APLD | laggards | down | -1.00 | -2.14 | -2.24 |
| 09:37 | HUM | leaders | up | +0.46 | -0.87 | -2.05 |
| 09:37 | LLY | laggards | down | +0.28 | +1.27 | -0.12 |
| 09:38 | CNC | leaders | up | +1.42 | +0.85 | +0.62 |
| 09:39 | ELV | leaders | up | -0.24 | -1.14 | -1.35 |
| 09:39 | CI | leaders | up | -0.90 | -1.25 | -1.12 |
| 09:39 | UNH | leaders | up | -0.48 | -0.85 | -0.95 |
| 09:41 | HOOD | laggards | down | +1.27 | +1.01 | +0.00 |
| 09:46 | CRWV | leaders | up | -2.26 | -3.04 | -2.37 |
| 09:46 | NVO | laggards | down | +0.67 | +0.33 | -0.82 |
| 09:47 | AMD | leaders | up | -1.06 | -0.32 | -0.38 |
| 09:48 | LCID | laggards | down | -1.75 | -3.60 | -4.69 |
| 09:50 | ANET | leaders | up | +0.77 | +0.95 | +1.76 |
| 09:54 | FTNT | leaders | up | -0.20 | +0.31 | +0.03 |
| 09:54 | NET | leaders | up | +0.11 | +0.25 | +0.37 |
| 10:00 | JD | laggards | down | +0.83 | +0.57 | +0.29 |
| 10:01 | IONQ | laggards | down | -0.30 | -0.14 | -1.59 |
| 10:09 | RGTI | laggards | down | -2.20 | -2.44 | -2.69 |
| 10:14 | CRWD | leaders | up | -0.42 | -0.38 | -0.85 |
| 10:19 | ASTS | laggards | down | -1.45 | -1.34 | -0.97 |
| 10:21 | FLNC | laggards | down | -0.71 | -0.21 | -0.34 |
| 10:22 | TDOC | leaders | up | -0.46 | -0.58 | -0.22 |
| 10:30 | PLTR | leaders | up | -0.76 | -1.18 | -0.57 |
| 10:32 | NBIS | laggards | down | -0.25 | -0.11 | -0.31 |
| 10:40 | OKLO | laggards | down | +0.29 | -2.16 | -2.62 |
| 11:00 | CRCL | laggards | down | +1.58 | +0.73 | +0.18 |
| 11:10 | RIVN | laggards | down | -0.75 | -1.08 | -0.45 |
| 12:12 | CVS | leaders | up | -0.11 | -0.10 | -0.02 |
| 12:31 | ARM | leaders | up | +0.27 | +0.71 | +0.45 |
| 13:30 | RDDT | laggards | down | +0.14 | -0.15 | -0.58 |
| 14:01 | LUNR | laggards | down | -0.34 | -0.09 | — |
| 15:33 | HPQ | leaders | up | — | — | — |
| 15:49 | ALAB | leaders | up | — | — | — |

## 2026-08-27

Usable symbol-minutes 64,445/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | CRM | +21.93 | miss | 09:31 |
| 2 | CRWD | +19.84 | miss | 09:31 |
| 3 | PANW | +12.18 | miss | 09:31 |
| 4 | MSTR | +10.88 | 10:04 | 09:58 |
| 5 | S | +10.07 | miss | 09:31 |
| 6 | NOW | +9.38 | miss | 09:32 |
| 7 | ZS | +9.32 | miss | 09:31 |
| 8 | FTNT | +9.02 | miss | 13:05 |
| 9 | BULL | +8.34 | miss | 13:43 |
| 10 | NVDA | +8.08 | miss | 09:31 |
| 11 | MDB | +7.83 | miss | 09:42 |
| 12 | NET | +7.54 | miss | 09:35 |
| 13 | DDOG | +6.05 | miss | 09:31 |
| 14 | AI | +5.84 | miss | 09:38 |
| 15 | CLSK | +5.67 | 10:45 | 10:29 |
| 16 | HIMS | +5.48 | miss | miss |
| 17 | CRDO | +5.42 | miss | 09:31 |
| 18 | IONQ | +5.42 | miss | miss |
| 19 | MARA | +5.14 | 10:45 | 10:26 |
| 20 | ADBE | +5.08 | miss | miss |

### Radar flags (11)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | AI software and analytics (NOW, DDOG, PLTR, SNOW, AI, APP) | group_move | up | -0.33 | -0.39 | -0.65 |
| 10:02 | Cloud software and data (NOW, DDOG, CRM, MDB, SNOW, ADBE) | group_move | up | -0.26 | -0.05 | -0.72 |
| 10:02 | Cybersecurity (PANW, ZS, CRWD, NET, S, FTNT) | group_move | up | -0.15 | -0.11 | +0.08 |
| 10:02 | Memory and storage (WDC, SNDK, MU, STX) | group_move | down | +0.99 | +0.39 | -0.03 |
| 10:04 | MSTR | relative_to_spy | up | +0.14 | +1.60 | +3.50 |
| 10:04 | Crypto and exchanges (MSTR, COIN, HOOD, CRCL, BULL, MARA, RIOT) | group_move | up | +0.54 | +1.44 | +1.66 |
| 10:29 | Memory and storage (STX, WDC, SNDK, MU) | group_move | up | -0.79 | -1.57 | -1.90 |
| 10:39 | Bitcoin treasuries and miners (MARA, CLSK, RIOT, MSTR, IREN, COIN) | group_move | up | -0.03 | -0.10 | -0.95 |
| 10:45 | CLSK | relative_to_spy | up | -0.83 | -1.25 | -1.78 |
| 10:45 | MARA | relative_to_spy | up | -0.07 | -0.66 | -2.07 |
| 11:39 | LCID | relative_to_spy | up | -1.18 | -1.50 | -4.67 |

### Movers flags (57)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | CRM | leaders | up | +4.33 | +6.09 | +5.66 |
| 09:31 | CRWD | leaders | up | +4.45 | +5.93 | +5.81 |
| 09:31 | CRDO | leaders | up | -2.59 | -2.12 | -2.75 |
| 09:31 | NVDA | leaders | up | +0.44 | +0.69 | +0.52 |
| 09:31 | PANW | leaders | up | +4.19 | +3.65 | +4.63 |
| 09:31 | NBIS | leaders | up | -3.65 | -1.42 | -3.81 |
| 09:31 | ZS | leaders | up | +4.30 | +4.16 | +3.06 |
| 09:31 | DDOG | leaders | up | +3.66 | +1.32 | +1.21 |
| 09:31 | S | leaders | up | +2.32 | +2.14 | +2.37 |
| 09:31 | WULF | leaders | up | -0.17 | +0.82 | +0.68 |
| 09:31 | HPQ | laggards | down | +6.88 | +5.07 | +6.36 |
| 09:31 | NVO | laggards | down | -0.36 | -0.61 | -0.52 |
| 09:31 | MRK | laggards | down | +0.22 | +0.96 | +1.18 |
| 09:31 | UBER | laggards | down | -0.42 | -0.25 | -0.41 |
| 09:31 | BABA | laggards | down | -1.38 | -1.23 | -1.90 |
| 09:31 | AMGN | laggards | down | +1.16 | +1.57 | +2.01 |
| 09:31 | HD | laggards | down | +0.22 | +0.31 | +0.37 |
| 09:31 | DIS | laggards | down | +0.24 | -0.01 | -0.21 |
| 09:31 | LOW | laggards | down | -0.29 | -0.21 | +0.29 |
| 09:31 | LYFT | laggards | down | +0.19 | +0.80 | +1.22 |
| 09:32 | NOW | leaders | up | +4.24 | +4.29 | +3.08 |
| 09:32 | SPOT | laggards | down | -0.63 | -1.59 | -1.98 |
| 09:32 | DASH | laggards | down | -0.51 | -0.10 | -0.35 |
| 09:32 | AMD | laggards | down | +0.32 | +0.83 | +0.20 |
| 09:33 | AAOI | leaders | up | -5.04 | -4.73 | -5.68 |
| 09:33 | WFC | laggards | down | +0.79 | +0.73 | +1.14 |
| 09:33 | PDD | laggards | down | -0.48 | -0.83 | -2.01 |
| 09:34 | SNAP | laggards | down | +2.87 | +1.94 | +2.86 |
| 09:35 | NET | leaders | up | +0.42 | +0.77 | +0.38 |
| 09:35 | WDC | laggards | down | -2.98 | -0.29 | -0.88 |
| 09:38 | AI | leaders | up | +0.52 | -0.42 | +0.68 |
| 09:38 | NFLX | laggards | down | -0.49 | -0.59 | -0.71 |
| 09:39 | AMZN | laggards | down | +0.48 | +0.29 | -0.13 |
| 09:40 | CIFR | leaders | up | -0.78 | +2.20 | -0.68 |
| 09:41 | DE | laggards | down | -0.51 | -0.71 | -0.49 |
| 09:42 | MDB | leaders | up | +2.16 | +0.72 | +1.17 |
| 09:53 | STX | laggards | down | +2.31 | +2.55 | +1.16 |
| 09:57 | SNDK | laggards | down | +1.77 | +0.58 | +0.71 |
| 09:58 | MSTR | leaders | up | +1.63 | +3.55 | +5.21 |
| 10:08 | URI | laggards | down | +0.73 | +0.79 | +0.82 |
| 10:09 | CMI | laggards | down | +0.35 | +0.87 | +0.79 |
| 10:12 | SCHW | laggards | down | +0.38 | +0.23 | +0.46 |
| 10:21 | U | laggards | down | +0.41 | +0.82 | +0.13 |
| 10:26 | MARA | leaders | up | +1.22 | +0.82 | -0.82 |
| 10:29 | CLSK | leaders | up | +0.76 | -0.31 | -0.97 |
| 10:51 | TTWO | laggards | down | +1.13 | -0.24 | -0.53 |
| 10:56 | CIEN | laggards | down | +0.73 | +1.09 | +1.16 |
| 10:57 | WMT | laggards | down | +0.43 | +0.46 | +0.17 |
| 10:59 | COP | laggards | down | +0.44 | +0.39 | +0.30 |
| 11:03 | MU | laggards | down | -0.29 | -0.42 | -1.15 |
| 11:07 | DECK | laggards | down | +0.07 | -0.65 | -0.99 |
| 11:33 | LCID | leaders | up | -3.52 | -4.75 | -4.78 |
| 13:05 | FTNT | leaders | up | +0.41 | +1.40 | +2.26 |
| 13:43 | BULL | leaders | up | +0.08 | -0.43 | -0.77 |
| 14:22 | UAA | laggards | down | -0.29 | +0.22 | — |
| 15:14 | PCAR | laggards | down | -0.20 | — | — |
| 15:46 | COST | laggards | down | — | — | — |

## 2026-08-28

Usable symbol-minutes 64,477/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | PYPL | -12.48 | miss | 09:31 |
| 2 | IREN | -12.31 | miss | 09:31 |
| 3 | MRVL | -10.06 | miss | 09:31 |
| 4 | MARA | -9.88 | miss | 09:31 |
| 5 | CLSK | -9.73 | miss | 09:31 |
| 6 | CIFR | -9.31 | miss | 09:31 |
| 7 | RIOT | -8.82 | miss | 09:31 |
| 8 | HIMS | -8.68 | miss | 09:43 |
| 9 | RCAT | -8.29 | miss | 09:48 |
| 10 | IONQ | -7.45 | miss | 09:37 |
| 11 | APLD | -7.43 | miss | 09:31 |
| 12 | CRCL | -7.31 | miss | miss |
| 13 | MSTR | -7.12 | miss | 12:50 |
| 14 | WULF | -6.69 | miss | miss |
| 15 | COIN | -6.11 | miss | miss |
| 16 | ARM | -6.11 | miss | miss |
| 17 | AAOI | -6.00 | miss | 09:32 |
| 18 | SOFI | -5.61 | miss | miss |
| 19 | QUBT | -5.55 | miss | miss |
| 20 | OKLO | -5.39 | miss | miss |

### Radar flags (5)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | Cybersecurity (CRWD, FTNT, PANW, ZS, S, NET) | group_move | down | -0.50 | +0.15 | +0.69 |
| 10:04 | Memory and storage (SNDK, WDC, MU, STX) | group_move | up | +0.83 | -0.12 | -1.35 |
| 10:04 | Quantum computing (QBTS, IONQ, RGTI, QUBT) | group_move | down | -0.05 | -0.86 | -2.26 |
| 10:11 | Neoclouds and AI hosting (IREN, WULF, CIFR, APLD, NBIS, CRWV, ORCL) | group_move | down | +1.40 | +0.06 | -1.26 |
| 10:14 | Bitcoin treasuries and miners (MARA, IREN, CLSK, MSTR, RIOT, COIN) | group_move | down | +1.14 | +0.01 | -2.10 |

### Movers flags (54)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | HPQ | leaders | up | -2.31 | -0.93 | -0.45 |
| 09:31 | SONY | leaders | up | +0.95 | +0.40 | +0.33 |
| 09:31 | GM | leaders | up | -1.37 | -1.88 | -2.38 |
| 09:31 | CVNA | leaders | up | -0.48 | -1.73 | -1.29 |
| 09:31 | RBLX | leaders | up | +0.19 | +0.15 | +1.11 |
| 09:31 | APP | leaders | up | +2.66 | +3.41 | +2.84 |
| 09:31 | ONON | leaders | up | -0.51 | -0.86 | -1.00 |
| 09:31 | LULU | leaders | up | +0.71 | +1.00 | +1.22 |
| 09:31 | F | leaders | up | -1.47 | -1.74 | -1.94 |
| 09:31 | TTWO | leaders | up | -0.21 | +0.38 | +0.91 |
| 09:31 | PYPL | laggards | down | +3.09 | +3.11 | +2.46 |
| 09:31 | IREN | laggards | down | +0.67 | -0.90 | -3.38 |
| 09:31 | MRVL | laggards | down | -0.63 | +0.17 | -1.15 |
| 09:31 | CIFR | laggards | down | +1.38 | -0.08 | -2.79 |
| 09:31 | CLSK | laggards | down | -0.60 | -2.47 | -3.84 |
| 09:31 | NBIS | laggards | down | -0.33 | +0.38 | -0.06 |
| 09:31 | RIOT | laggards | down | -0.69 | -2.16 | -3.46 |
| 09:31 | MARA | laggards | down | -1.04 | -2.61 | -4.53 |
| 09:31 | S | laggards | down | -3.63 | -4.23 | -3.93 |
| 09:31 | APLD | laggards | down | +1.01 | -0.84 | -2.77 |
| 09:32 | AI | leaders | up | +1.10 | -0.71 | -1.20 |
| 09:32 | PINS | leaders | up | -0.30 | +0.01 | +0.15 |
| 09:32 | COHR | laggards | down | +1.34 | +2.75 | +1.24 |
| 09:32 | AAOI | laggards | down | +0.82 | +1.06 | -0.58 |
| 09:32 | PANW | laggards | down | -2.33 | -2.40 | +0.77 |
| 09:33 | MDB | leaders | up | -1.22 | -1.07 | -0.27 |
| 09:33 | SPOT | leaders | up | +0.80 | +1.14 | +2.30 |
| 09:34 | FND | leaders | up | -1.47 | -2.34 | -2.61 |
| 09:35 | SNAP | leaders | up | +0.86 | +0.53 | +1.51 |
| 09:35 | CRWD | laggards | down | -2.75 | -2.64 | -0.52 |
| 09:35 | ALAB | laggards | down | +1.22 | +2.65 | +0.77 |
| 09:36 | LAD | leaders | up | -1.23 | -1.86 | — |
| 09:37 | NOW | leaders | up | -0.17 | +1.07 | +2.30 |
| 09:37 | IONQ | laggards | down | -1.96 | -1.67 | -2.94 |
| 09:38 | TDOC | leaders | up | -1.28 | +0.20 | +0.50 |
| 09:39 | CRM | leaders | up | +0.42 | +0.78 | +1.14 |
| 09:39 | RIVN | laggards | down | -0.78 | -1.80 | -2.21 |
| 09:41 | BABA | leaders | up | +0.88 | +0.30 | +0.38 |
| 09:42 | META | leaders | up | +0.19 | -0.36 | +0.19 |
| 09:43 | WDC | leaders | up | -0.50 | -0.27 | -1.67 |
| 09:43 | HIMS | laggards | down | -2.54 | -2.61 | -3.52 |
| 09:48 | RCAT | laggards | down | -0.32 | -0.63 | -2.14 |
| 10:04 | LYFT | leaders | up | -0.51 | -0.37 | +0.05 |
| 10:06 | NKE | leaders | up | +0.02 | -0.22 | -0.00 |
| 10:14 | BAC | leaders | up | -0.68 | -0.17 | +0.29 |
| 10:22 | RDDT | leaders | up | +0.02 | -0.21 | -1.46 |
| 10:38 | FTNT | laggards | down | +0.30 | +1.41 | +0.69 |
| 10:39 | NFLX | leaders | up | +0.29 | +0.46 | +0.42 |
| 10:41 | AMZN | leaders | up | +1.12 | +1.76 | +1.64 |
| 12:29 | MSFT | leaders | up | +0.05 | +0.17 | -0.30 |
| 12:50 | MSTR | laggards | down | +0.20 | -0.00 | -0.42 |
| 13:01 | SCHW | leaders | up | -0.02 | -0.06 | +0.30 |
| 15:15 | DECK | leaders | up | -0.60 | — | — |
| 15:44 | UBER | leaders | up | — | — | — |

## 2026-08-31

Usable symbol-minutes 64,684/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | CRCL | +9.95 | miss | 09:41 |
| 2 | RBLX | +7.46 | 10:14 | 09:50 |
| 3 | HSAI | -7.16 | miss | 09:31 |
| 4 | TTWO | -6.37 | 10:02 | 09:32 |
| 5 | PINS | -6.08 | miss | 09:31 |
| 6 | CRWD | +6.07 | miss | 09:31 |
| 7 | TSLA | +5.80 | miss | 09:48 |
| 8 | SNDK | +5.80 | 15:54 | 09:41 |
| 9 | COIN | +5.61 | miss | 11:29 |
| 10 | IREN | +5.00 | miss | 09:35 |
| 11 | FND | -4.85 | miss | 09:32 |
| 12 | MSTR | +4.72 | miss | 11:33 |
| 13 | LYFT | -4.22 | miss | 09:52 |
| 14 | DE | +4.20 | miss | 09:31 |
| 15 | QCOM | +4.13 | miss | 09:33 |
| 16 | BABA | -3.81 | miss | 09:31 |
| 17 | UBER | -3.72 | miss | 09:41 |
| 18 | FTNT | +3.27 | miss | 09:34 |
| 19 | PANW | +3.14 | miss | 09:34 |
| 20 | RDDT | -3.09 | miss | 09:32 |

### Radar flags (5)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | TTWO | relative_to_spy | down | +0.74 | +0.07 | +0.62 |
| 10:02 | Gaming platforms (TTWO, U, APP) | group_move | down | +0.20 | -0.11 | +0.13 |
| 10:02 | Rideshare and delivery (LYFT, UBER, DASH) | group_move | down | +0.24 | -0.02 | +0.16 |
| 10:14 | RBLX | relative_to_spy | up | -0.44 | -1.26 | -0.04 |
| 15:54 | SNDK | relative_to_spy | up | — | — | — |

### Movers flags (61)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | CRWD | leaders | up | -0.63 | -0.57 | -0.87 |
| 09:31 | SNAP | leaders | up | -2.86 | -3.45 | -2.20 |
| 09:31 | DE | leaders | up | +0.29 | +0.63 | +0.68 |
| 09:31 | RCAT | leaders | up | -0.54 | -1.17 | -1.45 |
| 09:31 | OXY | leaders | up | +0.33 | -0.05 | -1.08 |
| 09:31 | XOM | leaders | up | +0.77 | +0.45 | -0.14 |
| 09:31 | CVX | leaders | up | +0.64 | +0.51 | -0.24 |
| 09:31 | COP | leaders | up | +0.60 | +0.29 | -0.86 |
| 09:31 | INTC | leaders | up | -0.67 | -1.01 | -1.32 |
| 09:31 | BIDU | leaders | up | -1.90 | -1.71 | -1.94 |
| 09:31 | PINS | laggards | down | -0.83 | -0.51 | -2.74 |
| 09:31 | HSAI | laggards | down | -1.47 | -1.41 | — |
| 09:31 | RIOT | laggards | down | +0.99 | +0.22 | +0.03 |
| 09:31 | NBIS | laggards | down | +1.14 | -0.33 | +0.19 |
| 09:31 | BABA | laggards | down | -0.90 | -0.77 | -0.88 |
| 09:31 | SMCI | laggards | down | +3.36 | +2.98 | +3.54 |
| 09:31 | CRWV | laggards | down | +1.38 | +0.95 | +1.39 |
| 09:31 | LUNR | laggards | down | +1.54 | +1.23 | +1.15 |
| 09:31 | TDOC | laggards | down | -1.92 | -0.22 | +0.57 |
| 09:31 | IONQ | laggards | down | +3.36 | +3.67 | +3.55 |
| 09:32 | DELL | leaders | up | -0.71 | -1.65 | -1.89 |
| 09:32 | ZS | leaders | up | -0.48 | -0.05 | -0.07 |
| 09:32 | ALAB | leaders | up | -0.31 | -1.07 | -0.95 |
| 09:32 | TTWO | laggards | down | -5.32 | -4.62 | -4.52 |
| 09:32 | RDDT | laggards | down | -1.76 | -0.32 | -1.15 |
| 09:32 | FND | laggards | down | -0.55 | -1.29 | -1.46 |
| 09:32 | PDD | laggards | down | -0.38 | +0.00 | +0.24 |
| 09:32 | LULU | laggards | down | +1.38 | +2.06 | +3.58 |
| 09:33 | QCOM | leaders | up | +0.53 | +0.48 | +0.24 |
| 09:33 | STX | laggards | down | +1.33 | +1.41 | +0.37 |
| 09:33 | HOOD | laggards | down | -0.45 | -0.60 | +0.62 |
| 09:33 | WDC | laggards | down | +0.91 | +0.52 | -0.42 |
| 09:34 | FTNT | leaders | up | -1.67 | -1.40 | -0.67 |
| 09:34 | PANW | leaders | up | -1.02 | -1.17 | -1.18 |
| 09:34 | CRDO | leaders | up | -3.01 | -3.40 | -3.58 |
| 09:35 | IREN | leaders | up | -1.04 | -1.68 | -0.73 |
| 09:35 | AMZN | laggards | down | -0.32 | -0.52 | -0.29 |
| 09:37 | CLSK | laggards | down | +0.10 | +0.26 | -0.03 |
| 09:38 | PYPL | laggards | down | +0.08 | +0.78 | +1.91 |
| 09:41 | SNDK | leaders | up | +0.14 | +0.79 | +0.34 |
| 09:41 | CRCL | leaders | up | -2.02 | -0.56 | +0.43 |
| 09:41 | UBER | laggards | down | -1.82 | -1.76 | -1.44 |
| 09:42 | APP | laggards | down | -0.31 | +0.14 | +0.06 |
| 09:45 | U | laggards | down | -0.49 | -0.59 | +0.19 |
| 09:46 | LCID | laggards | down | +0.33 | +1.29 | +2.42 |
| 09:48 | TSLA | leaders | up | +1.44 | +2.10 | +2.17 |
| 09:50 | RBLX | leaders | up | +3.44 | +1.72 | +2.03 |
| 09:52 | LYFT | laggards | down | -0.75 | -0.48 | +0.11 |
| 10:27 | RIVN | leaders | up | -1.18 | -1.13 | -2.20 |
| 10:28 | HIMS | leaders | up | -0.24 | +0.16 | +0.23 |
| 10:59 | LULU | leaders | up | -0.01 | +0.14 | -1.41 |
| 11:29 | COIN | leaders | up | +0.15 | +0.30 | +2.19 |
| 11:33 | MSTR | leaders | up | +0.14 | +0.32 | +0.63 |
| 11:41 | NOW | leaders | up | +0.61 | -0.12 | -0.11 |
| 11:51 | WULF | laggards | down | -0.14 | +0.77 | +1.18 |
| 11:52 | QUBT | leaders | up | -0.46 | -0.21 | -0.38 |
| 11:55 | MRVL | laggards | down | +0.07 | +0.65 | +0.15 |
| 12:00 | CRM | leaders | up | -0.27 | -0.05 | -0.12 |
| 12:27 | IONQ | leaders | up | +0.85 | -0.06 | -1.02 |
| 13:39 | CRDO | laggards | down | +0.17 | -0.09 | +0.08 |
| 15:33 | AI | leaders | up | — | — | — |

## 2026-09-01

Usable symbol-minutes 64,762/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | CRDO | -7.96 | miss | 09:41 |
| 2 | CRWD | -6.21 | miss | 09:54 |
| 3 | DELL | -6.11 | miss | 13:33 |
| 4 | S | -5.96 | miss | 10:34 |
| 5 | NET | -5.74 | miss | 11:34 |
| 6 | CRCL | -5.67 | miss | 09:31 |
| 7 | RIOT | -5.66 | miss | 09:31 |
| 8 | LCID | -5.50 | miss | 09:34 |
| 9 | MSTR | -5.38 | miss | 09:31 |
| 10 | COIN | -5.32 | miss | 09:34 |
| 11 | CIEN | -5.18 | miss | 09:46 |
| 12 | ALAB | -5.06 | miss | 09:32 |
| 13 | CIFR | -5.05 | miss | 09:31 |
| 14 | HPQ | +5.02 | miss | 09:31 |
| 15 | ASTS | -4.90 | miss | 10:02 |
| 16 | DDOG | -4.88 | miss | 12:47 |
| 17 | HSAI | +4.78 | miss | 09:46 |
| 18 | ZS | -4.63 | miss | 10:47 |
| 19 | FTNT | -4.63 | miss | 11:18 |
| 20 | CVS | +4.62 | miss | 09:31 |

### Radar flags (5)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | Cybersecurity (CRWD, S, ZS, NET, PANW, FTNT) | group_move | down | -1.07 | -1.41 | -2.32 |
| 10:02 | Space (PL, ASTS, LUNR, RKLB) | group_move | down | -0.26 | -0.06 | +0.27 |
| 10:04 | Bitcoin treasuries and miners (RIOT, CLSK, IREN, MARA, COIN) | group_move | down | -0.11 | +1.67 | +1.48 |
| 11:00 | Memory and storage (STX, WDC, MU, SNDK) | group_move | up | -0.43 | +0.32 | -0.52 |
| 11:03 | Bitcoin treasuries and miners (CLSK, RIOT, IREN, MARA) | group_move | up | +0.35 | +0.21 | -0.70 |

### Movers flags (66)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | HUM | leaders | up | -0.11 | +0.90 | -0.44 |
| 09:31 | LLY | leaders | up | -1.30 | -1.72 | -0.87 |
| 09:31 | COP | leaders | up | -1.08 | -0.86 | -0.54 |
| 09:31 | MRK | leaders | up | -0.62 | -0.87 | -1.03 |
| 09:31 | XOM | leaders | up | -0.27 | -0.70 | -0.57 |
| 09:31 | HPQ | leaders | up | -1.25 | -0.86 | -0.08 |
| 09:31 | CVX | leaders | up | -0.29 | -0.45 | -0.49 |
| 09:31 | CVS | leaders | up | +1.34 | +1.47 | +1.64 |
| 09:31 | DE | leaders | up | +0.30 | +0.75 | +0.79 |
| 09:31 | SHEL | leaders | up | -0.12 | -0.30 | +0.10 |
| 09:31 | MSTR | laggards | down | +1.17 | +1.24 | +0.09 |
| 09:31 | NBIS | laggards | down | -0.59 | -1.06 | +0.95 |
| 09:31 | CIFR | laggards | down | -1.69 | -1.81 | +0.61 |
| 09:31 | RIOT | laggards | down | -2.31 | -2.92 | -0.50 |
| 09:31 | CRCL | laggards | down | -2.28 | -1.95 | -1.41 |
| 09:31 | OKLO | laggards | down | -2.10 | -1.21 | -1.30 |
| 09:31 | CRWV | laggards | down | -0.45 | -0.88 | +0.20 |
| 09:31 | ORCL | laggards | down | -0.05 | -0.90 | -1.01 |
| 09:31 | RGTI | laggards | down | -1.68 | -1.53 | -1.67 |
| 09:31 | MARA | laggards | down | -1.58 | -1.76 | +0.08 |
| 09:32 | ELV | leaders | up | -0.16 | +0.65 | +0.68 |
| 09:32 | SONY | leaders | up | -0.61 | -0.05 | -0.47 |
| 09:32 | PFE | leaders | up | -0.69 | -0.83 | -1.21 |
| 09:32 | UNH | leaders | up | +0.21 | +0.32 | -0.16 |
| 09:32 | QCOM | laggards | down | -0.61 | -0.28 | +0.45 |
| 09:32 | ALAB | laggards | down | -2.15 | -3.21 | -2.18 |
| 09:32 | AI | laggards | down | -0.73 | -0.90 | -2.09 |
| 09:32 | INTC | laggards | down | -0.08 | -0.16 | +2.40 |
| 09:32 | PANW | laggards | down | -1.62 | -2.23 | -2.77 |
| 09:33 | CNC | leaders | up | -0.04 | +0.31 | -0.11 |
| 09:33 | CI | leaders | up | -0.55 | +0.14 | +0.23 |
| 09:33 | NVO | leaders | up | -0.97 | -1.49 | -1.33 |
| 09:33 | RBLX | laggards | down | +0.11 | +0.94 | +2.07 |
| 09:33 | MRVL | laggards | down | -0.44 | +1.18 | +1.81 |
| 09:33 | SNAP | laggards | down | -0.14 | +0.79 | -0.14 |
| 09:34 | BULL | laggards | down | +1.41 | +1.46 | +0.91 |
| 09:34 | LCID | laggards | down | -1.58 | -0.56 | -0.25 |
| 09:34 | COIN | laggards | down | -0.10 | +0.26 | -0.89 |
| 09:36 | HOOD | leaders | up | -1.32 | -0.60 | -0.40 |
| 09:37 | WULF | laggards | down | -0.27 | +1.20 | +3.35 |
| 09:37 | CLSK | laggards | down | -0.41 | -0.66 | +2.35 |
| 09:38 | IREN | laggards | down | +0.32 | +1.50 | +4.28 |
| 09:38 | APLD | laggards | down | +0.30 | +0.63 | +1.77 |
| 09:40 | WFC | leaders | up | -0.88 | -0.43 | -1.45 |
| 09:41 | CRDO | laggards | down | +0.34 | -0.52 | +1.36 |
| 09:42 | LULU | leaders | up | -1.28 | -0.89 | -2.03 |
| 09:42 | AAOI | laggards | down | -0.35 | +0.77 | +1.00 |
| 09:44 | APP | leaders | up | -2.01 | -0.31 | -0.81 |
| 09:44 | ARM | laggards | down | +0.57 | +1.63 | +2.01 |
| 09:46 | HSAI | leaders | up | +0.18 | +0.13 | +1.51 |
| 09:46 | CIEN | laggards | down | -0.88 | -0.56 | -0.46 |
| 09:52 | AAPL | leaders | up | +0.74 | +0.81 | +1.25 |
| 09:54 | CRWD | laggards | down | -0.72 | -1.85 | -2.30 |
| 10:02 | ASTS | laggards | down | -0.24 | +0.14 | +0.58 |
| 10:18 | C | leaders | up | -0.55 | -0.41 | -0.56 |
| 10:22 | TGT | leaders | up | -0.11 | -0.41 | -0.41 |
| 10:34 | S | laggards | down | -0.28 | -0.85 | -1.42 |
| 10:47 | ZS | laggards | down | -0.77 | -0.93 | -1.80 |
| 11:18 | FTNT | laggards | down | -0.10 | -0.57 | -0.22 |
| 11:34 | NET | laggards | down | -0.58 | -1.56 | -1.20 |
| 11:45 | SNDK | leaders | up | -0.32 | -1.53 | -1.84 |
| 11:46 | LUNR | laggards | down | -0.05 | -0.02 | +0.67 |
| 12:01 | META | leaders | up | -0.23 | -0.16 | +0.36 |
| 12:47 | DDOG | laggards | down | +1.06 | +0.72 | +0.55 |
| 13:33 | DELL | laggards | down | +0.70 | -0.25 | -1.25 |
| 14:27 | AMGN | leaders | up | -0.18 | -0.12 | — |

## 2026-09-02

Usable symbol-minutes 64,422/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | CRDO | -20.48 | 10:02 | 09:31 |
| 2 | DELL | +15.37 | miss | 09:31 |
| 3 | MDB | -13.99 | miss | 09:31 |
| 4 | ASTS | +11.38 | miss | 09:31 |
| 5 | PANW | -9.73 | miss | 09:31 |
| 6 | RDDT | +8.86 | miss | 09:31 |
| 7 | IREN | +7.11 | miss | 13:39 |
| 8 | DDOG | -6.97 | miss | 09:31 |
| 9 | PLTR | -6.26 | miss | 09:31 |
| 10 | CRWD | -5.86 | miss | 09:33 |
| 11 | S | -5.05 | miss | 09:35 |
| 12 | FTNT | -4.96 | miss | 09:42 |
| 13 | NET | -4.92 | miss | 09:36 |
| 14 | SNOW | -4.81 | miss | 09:31 |
| 15 | NOW | -4.77 | miss | 10:10 |
| 16 | RIOT | +4.31 | miss | 13:59 |
| 17 | UAA | +4.23 | miss | 09:36 |
| 18 | SOFI | +4.19 | miss | 10:09 |
| 19 | SNAP | +4.04 | miss | 09:51 |
| 20 | PYPL | +3.89 | miss | 10:42 |

### Radar flags (6)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | CRDO | relative_to_spy | down | +1.55 | -1.75 | -0.94 |
| 10:02 | Cybersecurity (FTNT, PANW, CRWD, NET, S, ZS) | group_move | down | +0.63 | +0.35 | -1.00 |
| 10:04 | DELL | relative_to_spy | down | -1.38 | -1.23 | +1.90 |
| 10:13 | Memory and storage (SNDK, WDC, STX, MU) | group_move | down | -0.03 | -0.69 | +0.32 |
| 10:15 | SMCI | relative_to_spy | down | +0.97 | -0.22 | +0.83 |
| 14:05 | Bitcoin treasuries and miners (RIOT, IREN, MARA, CLSK, MSTR, COIN) | group_move | up | +0.13 | +0.06 | — |

### Movers flags (62)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | DELL | leaders | up | -3.04 | -4.73 | -3.33 |
| 09:31 | ASTS | leaders | up | +2.93 | +5.31 | +2.63 |
| 09:31 | PL | leaders | up | +2.46 | +1.71 | -0.95 |
| 09:31 | NVO | leaders | up | +1.47 | +1.02 | +0.71 |
| 09:31 | HPQ | leaders | up | -0.86 | -2.45 | -1.94 |
| 09:31 | SMCI | leaders | up | -3.53 | -3.22 | -3.90 |
| 09:31 | RDDT | leaders | up | +3.76 | +4.77 | +4.47 |
| 09:31 | LULU | leaders | up | +1.30 | +1.11 | +0.19 |
| 09:31 | UBER | leaders | up | -0.73 | -0.99 | +0.17 |
| 09:31 | LLY | leaders | up | +0.79 | +0.21 | -0.34 |
| 09:31 | CRDO | laggards | down | -8.13 | -7.40 | -9.22 |
| 09:31 | MDB | laggards | down | -3.39 | -2.44 | -1.49 |
| 09:31 | PANW | laggards | down | -3.49 | -2.01 | -3.26 |
| 09:31 | DDOG | laggards | down | +0.54 | +0.23 | -1.17 |
| 09:31 | HSAI | laggards | down | +2.29 | +1.31 | +2.35 |
| 09:31 | PLTR | laggards | down | +0.00 | -1.11 | -3.93 |
| 09:31 | SNOW | laggards | down | -0.03 | +0.66 | -1.07 |
| 09:31 | MRVL | laggards | down | -0.59 | +0.26 | -0.14 |
| 09:31 | CIFR | laggards | down | +0.43 | +1.20 | +1.38 |
| 09:31 | CRWV | laggards | down | +0.32 | +1.53 | -0.07 |
| 09:32 | CRM | leaders | up | -1.09 | -3.49 | -4.05 |
| 09:32 | CNC | leaders | up | -1.19 | -1.00 | -0.36 |
| 09:32 | CRCL | laggards | down | +0.96 | +1.35 | +0.86 |
| 09:32 | BULL | laggards | down | +0.58 | +0.99 | -0.07 |
| 09:32 | MSTR | laggards | down | +1.02 | +0.79 | -0.45 |
| 09:33 | F | leaders | up | -0.96 | -1.18 | -2.07 |
| 09:33 | CRWD | laggards | down | -2.22 | -1.35 | -2.74 |
| 09:34 | COIN | laggards | down | +2.71 | +2.32 | +1.98 |
| 09:35 | CVNA | leaders | up | +0.07 | +0.23 | +1.28 |
| 09:35 | S | laggards | down | -0.97 | -0.42 | -1.57 |
| 09:36 | LUNR | leaders | up | -0.55 | -0.53 | -1.57 |
| 09:36 | UAA | leaders | up | +1.57 | +1.38 | +1.69 |
| 09:36 | NET | laggards | down | +0.94 | +0.69 | -1.05 |
| 09:37 | SPOT | leaders | up | +1.03 | +0.46 | +0.23 |
| 09:39 | MRK | leaders | up | -1.31 | -1.48 | -1.77 |
| 09:39 | WFC | leaders | up | +0.18 | +0.95 | +0.90 |
| 09:39 | ZS | laggards | down | +0.47 | +1.27 | -0.27 |
| 09:40 | SNDK | leaders | up | -2.50 | -1.96 | -1.75 |
| 09:41 | MU | leaders | up | -0.68 | -0.61 | -0.97 |
| 09:42 | FTNT | laggards | down | -1.66 | -1.63 | -2.44 |
| 09:47 | ALAB | laggards | down | +0.51 | -0.65 | -0.45 |
| 09:49 | META | leaders | up | +0.25 | +0.81 | -0.15 |
| 09:50 | COHR | laggards | down | +1.43 | -0.21 | -0.09 |
| 09:51 | SNAP | leaders | up | +0.88 | +2.15 | +1.75 |
| 09:54 | HIMS | leaders | up | -0.52 | -1.51 | -1.33 |
| 09:55 | WDC | laggards | down | +0.53 | -0.10 | +1.01 |
| 09:59 | NFLX | leaders | up | -0.79 | -0.64 | -1.14 |
| 10:09 | SOFI | leaders | up | +0.82 | +1.14 | +0.50 |
| 10:10 | NOW | laggards | down | -0.70 | -1.06 | -2.03 |
| 10:13 | SMCI | laggards | down | +1.27 | -0.03 | +1.43 |
| 10:22 | HOOD | leaders | up | -0.35 | -0.79 | -0.63 |
| 10:36 | STX | laggards | down | -1.33 | -1.00 | -0.48 |
| 10:42 | PYPL | leaders | up | -0.11 | +0.11 | +0.30 |
| 10:58 | ORCL | leaders | up | -0.55 | -1.17 | -0.68 |
| 11:02 | NVDA | leaders | up | +0.76 | +1.33 | +0.60 |
| 11:10 | LCID | leaders | up | +0.59 | -0.04 | +0.10 |
| 12:09 | TDOC | leaders | up | +0.95 | +1.08 | +1.02 |
| 12:24 | LYFT | leaders | up | +0.26 | -0.07 | -0.16 |
| 13:39 | IREN | leaders | up | +1.76 | +2.11 | +3.64 |
| 13:59 | RIOT | leaders | up | +1.11 | +1.48 | +0.43 |
| 14:57 | CIFR | leaders | up | -0.49 | -0.20 | — |
| 15:46 | AI | leaders | up | — | — | — |

## 2026-09-03

Usable symbol-minutes 64,606/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | MSTR | +16.51 | miss | 09:31 |
| 2 | HOOD | +15.52 | miss | 09:31 |
| 3 | SNOW | +15.51 | miss | 09:31 |
| 4 | CRCL | +15.41 | miss | 09:31 |
| 5 | CIFR | +13.38 | 10:30 | 10:16 |
| 6 | RIOT | +12.40 | 10:30 | 11:09 |
| 7 | CIEN | -11.41 | 10:02 | 09:31 |
| 8 | HSAI | +10.22 | miss | 09:31 |
| 9 | BULL | +10.06 | miss | 09:32 |
| 10 | CLSK | +9.99 | 10:30 | 10:20 |
| 11 | MARA | +9.75 | 10:27 | 10:20 |
| 12 | PL | -9.25 | 10:21 | 09:59 |
| 13 | COIN | +9.09 | miss | 09:31 |
| 14 | WULF | +8.47 | miss | miss |
| 15 | PLTR | +6.67 | 10:02 | 09:36 |
| 16 | NOW | +5.44 | miss | 09:31 |
| 17 | ORCL | +4.64 | miss | miss |
| 18 | CRWD | +4.63 | miss | miss |
| 19 | FLNC | -4.46 | miss | 09:31 |
| 20 | TSLA | +4.37 | miss | 09:50 |

### Radar flags (11)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | CIEN | relative_to_spy | down | -0.91 | +2.10 | +0.77 |
| 10:02 | PLTR | relative_to_spy | up | +0.65 | -1.18 | -0.26 |
| 10:17 | Bitcoin treasuries and miners (RIOT, MARA, CLSK, MSTR, COIN) | group_move | up | +2.50 | +3.25 | +3.67 |
| 10:20 | Crypto and exchanges (RIOT, MARA, CRCL, MSTR, HOOD, BULL, COIN) | group_move | up | +2.64 | +2.40 | +2.80 |
| 10:21 | PL | relative_to_spy | down | -2.08 | -1.48 | -2.69 |
| 10:27 | MARA | relative_to_spy | up | +2.17 | +2.40 | +0.62 |
| 10:30 | CIFR | relative_to_spy | up | +2.68 | +3.77 | +2.27 |
| 10:30 | CLSK | relative_to_spy | up | +1.69 | +1.62 | +0.09 |
| 10:30 | RIOT | relative_to_spy | up | +1.43 | +3.25 | +3.14 |
| 10:33 | Neoclouds and AI hosting (CIFR, WULF, ORCL, NBIS, CRWV, IREN, APLD) | group_move | up | +1.25 | +2.11 | +1.51 |
| 11:05 | Memory and storage (STX, WDC, MU, SNDK) | group_move | up | -0.37 | -0.90 | +0.38 |

### Movers flags (52)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | SNOW | leaders | up | -1.61 | -2.68 | -4.24 |
| 09:31 | HOOD | leaders | up | +3.10 | +6.44 | +5.74 |
| 09:31 | HSAI | leaders | up | +3.56 | +3.51 | +3.47 |
| 09:31 | DDOG | leaders | up | -3.21 | -3.03 | -3.07 |
| 09:31 | CPRT | leaders | up | +0.09 | -1.33 | -1.45 |
| 09:31 | MSTR | leaders | up | +2.59 | +6.50 | +7.57 |
| 09:31 | CRCL | leaders | up | +4.71 | +9.47 | +8.99 |
| 09:31 | COIN | leaders | up | +1.87 | +4.87 | +5.15 |
| 09:31 | NOW | leaders | up | +2.14 | +2.41 | +0.69 |
| 09:31 | ZS | leaders | up | -2.40 | -1.21 | -1.84 |
| 09:31 | FLNC | laggards | down | +0.01 | +0.58 | +0.68 |
| 09:31 | AVGO | laggards | down | -2.17 | -2.14 | -1.35 |
| 09:31 | WDC | laggards | down | -1.74 | -1.22 | +1.16 |
| 09:31 | ALAB | laggards | down | +0.51 | +1.81 | +3.92 |
| 09:31 | BABA | laggards | down | +0.29 | +0.55 | +0.44 |
| 09:31 | SMCI | laggards | down | +0.52 | +0.27 | +0.40 |
| 09:31 | STX | laggards | down | -1.99 | -2.39 | -0.51 |
| 09:31 | CIEN | laggards | down | -7.99 | -9.88 | -8.84 |
| 09:31 | ARM | laggards | down | -0.66 | -0.12 | +2.06 |
| 09:31 | COHR | laggards | down | -2.33 | -2.28 | -0.30 |
| 09:32 | BULL | leaders | up | +2.64 | +4.69 | +6.82 |
| 09:32 | SNAP | leaders | up | +1.61 | -0.72 | -1.75 |
| 09:32 | AAOI | laggards | down | -3.13 | -1.99 | +1.53 |
| 09:33 | NBIS | laggards | down | +0.57 | +2.81 | +4.76 |
| 09:34 | RBLX | leaders | up | -1.30 | -2.12 | -3.22 |
| 09:35 | AMD | laggards | down | +0.60 | +1.70 | +2.43 |
| 09:35 | MU | laggards | down | +1.23 | +0.55 | +1.91 |
| 09:36 | PLTR | leaders | up | +3.43 | +3.59 | +2.11 |
| 09:39 | SNDK | laggards | down | +0.93 | +0.49 | +1.12 |
| 09:40 | QCOM | laggards | down | -0.57 | +0.10 | +0.89 |
| 09:48 | PANW | laggards | down | +2.33 | +2.27 | +2.19 |
| 09:50 | TSLA | leaders | up | -0.07 | +0.79 | +1.10 |
| 09:50 | AI | laggards | down | +2.96 | +1.77 | +4.37 |
| 09:51 | PFE | laggards | down | -0.00 | +0.87 | +0.22 |
| 09:52 | HIMS | laggards | down | +0.58 | -0.40 | -1.42 |
| 09:59 | PL | laggards | down | -4.33 | -4.60 | -6.33 |
| 10:16 | CIFR | leaders | up | +3.82 | +4.85 | +5.35 |
| 10:20 | MARA | leaders | up | +3.86 | +4.47 | +2.99 |
| 10:20 | CLSK | leaders | up | +2.46 | +2.53 | +2.02 |
| 10:36 | LUNR | laggards | down | -0.23 | -0.96 | -0.91 |
| 10:59 | RDDT | laggards | down | +0.89 | +1.58 | +0.67 |
| 11:01 | PINS | laggards | down | -0.26 | -0.15 | -1.36 |
| 11:03 | DASH | laggards | down | +0.20 | +0.45 | -0.06 |
| 11:05 | UBER | laggards | down | +0.02 | -0.03 | -0.24 |
| 11:07 | TSM | laggards | down | +0.13 | +0.24 | +0.83 |
| 11:09 | RIOT | leaders | up | +1.05 | +1.54 | +1.33 |
| 11:09 | LULU | laggards | down | +0.35 | +0.25 | +0.38 |
| 11:34 | ASTS | laggards | down | -0.39 | -0.74 | +0.25 |
| 12:12 | LCID | laggards | down | +0.13 | +0.08 | +0.79 |
| 12:40 | NFLX | laggards | down | +0.85 | +1.78 | +0.89 |
| 12:46 | APP | laggards | down | -0.05 | -0.84 | -0.66 |
| 14:14 | DE | laggards | down | -0.16 | -0.19 | — |

## 2026-09-04

Usable symbol-minutes 64,299/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | LULU | -16.99 | miss | 09:31 |
| 2 | SNDK | +12.28 | miss | 09:31 |
| 3 | ALAB | +10.14 | 10:02 | 09:31 |
| 4 | NBIS | +7.87 | miss | 14:41 |
| 5 | IREN | +7.66 | miss | 10:35 |
| 6 | MRVL | +7.43 | miss | 09:33 |
| 7 | COHR | +6.99 | 10:02 | 09:35 |
| 8 | STX | +6.73 | miss | 09:31 |
| 9 | MU | +6.48 | miss | 09:31 |
| 10 | ADBE | -6.35 | miss | 09:31 |
| 11 | WDC | +6.25 | miss | 09:32 |
| 12 | CRWV | +6.06 | miss | 11:54 |
| 13 | TSLA | -5.54 | miss | 09:31 |
| 14 | AAOI | +5.52 | miss | 09:35 |
| 15 | AMD | +5.08 | miss | 09:32 |
| 16 | SNOW | -5.03 | miss | 09:55 |
| 17 | NFLX | -4.96 | miss | 10:59 |
| 18 | SMCI | +4.93 | miss | 09:42 |
| 19 | INTC | +4.89 | miss | 09:31 |
| 20 | RBLX | +4.72 | miss | 09:37 |

### Radar flags (4)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | ALAB | relative_to_spy | up | -1.63 | -0.05 | +0.69 |
| 10:02 | COHR | relative_to_spy | up | -0.73 | +0.21 | +0.87 |
| 10:02 | AI networking and connectivity (ALAB, COHR, CRDO, MRVL, ANET) | group_move | up | -0.26 | +0.61 | +0.73 |
| 10:02 | Memory and storage (STX, SNDK, WDC, MU) | group_move | up | -0.36 | +0.29 | +0.36 |

### Movers flags (49)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | ALAB | leaders | up | +7.84 | +6.44 | +7.84 |
| 09:31 | PL | leaders | up | -2.87 | -3.87 | -3.48 |
| 09:31 | ASTS | leaders | up | +2.03 | -1.60 | -2.11 |
| 09:31 | ORCL | leaders | up | -0.83 | +0.01 | -0.26 |
| 09:31 | BIDU | leaders | up | -0.81 | -0.40 | +0.75 |
| 09:31 | ARM | leaders | up | +2.29 | +2.09 | +1.17 |
| 09:31 | SNDK | leaders | up | +3.77 | +4.43 | +6.18 |
| 09:31 | STX | leaders | up | +4.36 | +3.21 | +3.25 |
| 09:31 | INTC | leaders | up | +1.87 | +1.96 | +2.26 |
| 09:31 | MU | leaders | up | +2.82 | +2.56 | +3.01 |
| 09:31 | LULU | laggards | down | +0.63 | +1.01 | +0.60 |
| 09:31 | ZS | laggards | down | +3.89 | +3.25 | +1.59 |
| 09:31 | ADBE | laggards | down | -1.74 | -1.66 | -0.90 |
| 09:31 | TSLA | laggards | down | -1.39 | -2.75 | -2.44 |
| 09:31 | MSTR | laggards | down | +0.29 | +0.15 | +1.06 |
| 09:31 | CRCL | laggards | down | -1.52 | -1.66 | +0.40 |
| 09:31 | COIN | laggards | down | -1.04 | -1.43 | -0.94 |
| 09:31 | AI | laggards | down | +1.63 | +1.82 | -1.24 |
| 09:31 | MDB | laggards | down | -0.14 | -0.02 | +1.37 |
| 09:31 | NVO | laggards | down | -0.72 | +0.09 | +0.65 |
| 09:32 | WDC | leaders | up | +2.61 | +1.36 | +1.35 |
| 09:32 | AMD | leaders | up | +1.18 | +0.96 | +1.36 |
| 09:32 | U | laggards | down | -0.01 | +0.90 | +1.62 |
| 09:32 | PYPL | laggards | down | -0.46 | -0.61 | -1.23 |
| 09:32 | SNAP | laggards | down | -0.03 | -0.32 | -1.08 |
| 09:33 | MRVL | leaders | up | +2.32 | +2.67 | +3.52 |
| 09:33 | HOOD | laggards | down | +1.05 | +1.00 | +2.41 |
| 09:33 | MARA | laggards | down | +0.98 | +0.89 | +1.13 |
| 09:33 | LCID | laggards | down | +1.88 | +1.34 | +1.25 |
| 09:35 | COHR | leaders | up | +3.05 | +2.41 | +3.12 |
| 09:35 | AAOI | leaders | up | +1.61 | +1.41 | +2.72 |
| 09:35 | NOW | laggards | down | +0.72 | +0.57 | +0.59 |
| 09:36 | BULL | laggards | down | +0.68 | -0.03 | +1.49 |
| 09:37 | RBLX | leaders | up | -0.58 | -0.41 | +0.45 |
| 09:38 | CIEN | leaders | up | -2.29 | -2.52 | -2.38 |
| 09:39 | SOFI | laggards | down | +0.73 | +1.03 | +1.50 |
| 09:40 | DELL | leaders | up | -1.94 | -3.38 | -1.37 |
| 09:42 | SMCI | leaders | up | +1.44 | +1.68 | +3.09 |
| 09:45 | CRDO | leaders | up | +1.84 | +0.54 | +0.80 |
| 09:45 | PLTR | laggards | down | -0.26 | -0.28 | -0.57 |
| 09:46 | ANET | leaders | up | -0.68 | -1.00 | -1.54 |
| 09:48 | DASH | laggards | down | +0.16 | +0.63 | +0.34 |
| 09:55 | SNOW | laggards | down | +0.66 | +2.26 | +0.55 |
| 10:35 | IREN | leaders | up | +0.16 | +0.94 | +1.41 |
| 10:57 | RCAT | laggards | down | +1.60 | +1.70 | +2.33 |
| 10:59 | NFLX | laggards | down | -0.51 | -0.94 | -1.19 |
| 11:46 | SPOT | laggards | down | -0.41 | -0.03 | +0.01 |
| 11:54 | CRWV | leaders | up | +0.11 | +0.69 | +1.13 |
| 14:41 | NBIS | leaders | up | +0.71 | +1.52 | — |

## 2026-09-08

Usable symbol-minutes 64,409/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | CRWV | +12.27 | miss | 09:31 |
| 2 | INTC | +9.60 | miss | 09:31 |
| 3 | AMGN | -9.53 | miss | 09:31 |
| 4 | WULF | +8.73 | miss | 13:36 |
| 5 | NBIS | +8.27 | miss | 09:31 |
| 6 | APLD | +7.91 | miss | 09:34 |
| 7 | COHR | +7.65 | 10:02 | 09:50 |
| 8 | FLNC | +7.22 | miss | 09:43 |
| 9 | QBTS | +7.12 | miss | 09:31 |
| 10 | STX | +7.04 | miss | 13:25 |
| 11 | CIEN | +6.87 | miss | 12:30 |
| 12 | CLSK | +6.77 | miss | 15:24 |
| 13 | ASTS | +6.66 | miss | 09:58 |
| 14 | AMD | +6.45 | miss | miss |
| 15 | LUNR | +6.42 | miss | miss |
| 16 | BIDU | -6.41 | miss | 09:31 |
| 17 | ALAB | -6.39 | miss | 09:34 |
| 18 | AAOI | +6.25 | miss | 09:48 |
| 19 | IREN | +5.58 | miss | 09:31 |
| 20 | OKLO | +5.49 | 10:02 | 09:39 |

### Radar flags (5)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | COHR | relative_to_spy | up | +2.98 | +3.73 | +2.59 |
| 10:02 | OKLO | relative_to_spy | up | -1.47 | -0.32 | +0.69 |
| 10:07 | Space (PL, LUNR, ASTS, RKLB, IRDM) | group_move | up | — | +0.60 | — |
| 12:24 | Quantum computing (IONQ, QBTS, RGTI, QUBT) | group_move | down | -0.17 | +0.24 | -3.07 |
| 13:51 | IONQ | relative_to_spy | down | -0.32 | -1.22 | -0.20 |

### Movers flags (46)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | QBTS | leaders | up | -0.67 | -1.06 | -0.34 |
| 09:31 | RGTI | leaders | up | -1.04 | -2.28 | -1.55 |
| 09:31 | IONQ | leaders | up | +0.80 | -0.46 | +0.51 |
| 09:31 | INTC | leaders | up | -1.21 | +0.92 | +2.06 |
| 09:31 | ORCL | leaders | up | -2.39 | -2.97 | -2.62 |
| 09:31 | CRWV | leaders | up | +1.99 | +1.31 | +7.75 |
| 09:31 | QCOM | leaders | up | -1.38 | -0.18 | -0.66 |
| 09:31 | NBIS | leaders | up | +0.69 | +0.57 | +4.50 |
| 09:31 | IREN | leaders | up | +1.73 | +1.98 | +3.59 |
| 09:31 | QUBT | leaders | up | +1.37 | +1.14 | +2.09 |
| 09:31 | BIDU | laggards | down | -0.45 | -0.38 | -0.52 |
| 09:31 | AMGN | laggards | down | -0.18 | -1.57 | -2.32 |
| 09:31 | DDOG | laggards | down | +1.52 | +1.83 | +2.41 |
| 09:31 | NOW | laggards | down | -0.53 | -0.65 | +0.52 |
| 09:31 | SONY | laggards | down | +0.07 | -0.17 | -0.54 |
| 09:31 | ZS | laggards | down | -1.01 | -1.42 | -1.25 |
| 09:31 | MDB | laggards | down | +2.07 | +1.79 | +1.65 |
| 09:31 | MSTR | laggards | down | +0.19 | +0.61 | -0.38 |
| 09:31 | LLY | laggards | down | +1.55 | +1.55 | +0.48 |
| 09:31 | MRK | laggards | down | +1.96 | +2.17 | +1.51 |
| 09:32 | CRCL | laggards | down | -0.26 | +0.54 | -1.18 |
| 09:32 | UBER | laggards | down | +0.79 | -0.04 | +0.12 |
| 09:32 | DASH | laggards | down | -1.34 | -1.89 | -2.61 |
| 09:32 | CRM | laggards | down | -1.40 | -1.60 | -0.41 |
| 09:33 | ADBE | laggards | down | -0.36 | -0.14 | +0.20 |
| 09:34 | APLD | leaders | up | +0.82 | +0.87 | +3.19 |
| 09:34 | ALAB | laggards | down | +0.97 | +0.38 | +1.03 |
| 09:37 | PL | laggards | down | +4.21 | +2.65 | +5.05 |
| 09:39 | OKLO | leaders | up | +2.48 | +1.64 | +2.14 |
| 09:43 | FLNC | leaders | up | +0.01 | +0.63 | +3.47 |
| 09:43 | LYFT | laggards | down | +1.06 | +0.37 | -0.09 |
| 09:48 | AAOI | leaders | up | +2.33 | +3.92 | +3.45 |
| 09:50 | COHR | leaders | up | +1.52 | +3.79 | +3.58 |
| 09:53 | S | laggards | down | +1.02 | +0.88 | +1.71 |
| 09:58 | ASTS | leaders | up | +0.03 | +0.67 | +1.26 |
| 09:58 | HPQ | laggards | down | +0.74 | -0.24 | -0.95 |
| 10:07 | FND | laggards | down | -0.50 | -0.69 | -1.08 |
| 10:34 | KMX | laggards | down | -0.14 | -0.40 | -0.64 |
| 11:17 | F | laggards | down | -0.10 | +0.22 | +0.27 |
| 11:50 | CPRT | laggards | down | -0.04 | -0.22 | -0.33 |
| 12:30 | CIEN | leaders | up | +0.15 | +0.67 | +1.27 |
| 12:33 | CIFR | leaders | up | +1.42 | +1.40 | +0.67 |
| 13:25 | STX | leaders | up | -0.41 | +0.26 | -0.24 |
| 13:36 | WULF | leaders | up | -0.19 | +0.79 | -0.30 |
| 15:24 | CLSK | leaders | up | -1.67 | — | — |
| 15:51 | LAD | laggards | down | — | — | — |

## 2026-09-09

Usable symbol-minutes 64,436/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | NET | +10.97 | miss | 09:31 |
| 2 | PINS | -8.77 | miss | 11:33 |
| 3 | CIFR | -8.23 | miss | 09:42 |
| 4 | FLNC | -7.87 | miss | 09:31 |
| 5 | LYFT | -7.79 | miss | 09:31 |
| 6 | DDOG | +7.62 | miss | 09:47 |
| 7 | LCID | -7.31 | miss | 10:11 |
| 8 | META | +7.02 | miss | 09:31 |
| 9 | RCAT | -6.03 | miss | 09:47 |
| 10 | IONQ | -5.29 | miss | 09:31 |
| 11 | ASTS | -5.13 | miss | 09:44 |
| 12 | MRVL | +4.72 | 10:02 | 09:34 |
| 13 | ALAB | +4.51 | 10:02 | 09:35 |
| 14 | CRWV | -4.43 | miss | 12:34 |
| 15 | HPQ | +4.38 | miss | 13:46 |
| 16 | LUNR | -4.25 | miss | 10:19 |
| 17 | IBM | +3.85 | miss | 13:44 |
| 18 | RKLB | -3.79 | miss | 10:35 |
| 19 | APLD | -3.67 | miss | 12:18 |
| 20 | WULF | -3.62 | miss | 12:10 |

### Radar flags (9)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | ALAB | relative_to_spy | up | -0.90 | -0.09 | +0.41 |
| 10:02 | HUM | relative_to_spy | down | +2.28 | +2.40 | +3.36 |
| 10:02 | MRVL | relative_to_spy | up | -1.25 | -0.95 | -0.90 |
| 10:02 | UNH | relative_to_spy | down | +1.62 | +2.08 | +2.68 |
| 10:02 | Managed care (HUM, UNH, CVS, CNC, ELV, CI) | group_move | down | +1.65 | +1.69 | +2.33 |
| 10:02 | Memory and storage (MU, SNDK, WDC, STX) | group_move | up | +0.13 | +0.50 | +0.25 |
| 10:02 | Space (RKLB, LUNR, ASTS, PL, IRDM) | group_move | down | -1.84 | -2.18 | — |
| 10:26 | Quantum computing (IONQ, QUBT, QBTS, RGTI) | group_move | down | +0.21 | -0.21 | +1.54 |
| 12:30 | Quantum computing (RGTI, QBTS, IONQ, QUBT) | group_move | up | -0.08 | -0.54 | +0.24 |

### Movers flags (73)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | META | leaders | up | +0.92 | -0.04 | +1.96 |
| 09:31 | NET | leaders | up | +4.60 | +4.54 | +6.13 |
| 09:31 | MSTR | leaders | up | -2.58 | -1.99 | -4.31 |
| 09:31 | HUM | leaders | up | -6.34 | -4.13 | -2.76 |
| 09:31 | CRCL | leaders | up | -2.72 | -2.17 | -3.72 |
| 09:31 | COIN | leaders | up | -2.08 | -1.51 | -3.02 |
| 09:31 | HOOD | leaders | up | -1.60 | -1.30 | -2.77 |
| 09:31 | CIEN | leaders | up | -1.76 | -2.39 | -2.28 |
| 09:31 | RKLB | leaders | up | -2.30 | -3.91 | -4.24 |
| 09:31 | MARA | leaders | up | -1.58 | -1.15 | -2.09 |
| 09:31 | LYFT | laggards | down | -2.20 | -0.47 | -1.79 |
| 09:31 | GOOGL | laggards | down | -0.12 | +0.34 | +0.24 |
| 09:31 | FND | laggards | down | +0.49 | +1.26 | +0.36 |
| 09:31 | IONQ | laggards | down | +0.52 | -3.13 | -2.90 |
| 09:31 | DECK | laggards | down | +1.41 | +1.05 | +0.36 |
| 09:31 | SNAP | laggards | down | +1.40 | +0.87 | -0.29 |
| 09:31 | LULU | laggards | down | -2.65 | -1.88 | -1.84 |
| 09:31 | AMZN | laggards | down | +0.05 | +0.07 | -0.21 |
| 09:31 | FLNC | laggards | down | -2.57 | -4.06 | -5.31 |
| 09:31 | KMX | laggards | down | +0.79 | +1.93 | +1.62 |
| 09:32 | QCOM | leaders | up | -0.94 | -1.14 | -2.28 |
| 09:32 | PL | leaders | up | -1.83 | -4.60 | -5.13 |
| 09:32 | DELL | leaders | up | +2.44 | +1.68 | +0.41 |
| 09:32 | OXY | leaders | up | -0.08 | +0.10 | -0.10 |
| 09:32 | NKE | laggards | down | +1.98 | +1.47 | +0.50 |
| 09:32 | GS | laggards | down | +0.61 | +1.69 | +1.30 |
| 09:32 | ROKU | laggards | down | +0.53 | +0.64 | — |
| 09:32 | APP | laggards | down | +0.67 | +1.32 | +1.15 |
| 09:33 | URI | leaders | up | -0.15 | +0.10 | +0.77 |
| 09:33 | CI | leaders | up | -3.16 | -1.87 | -1.63 |
| 09:33 | RDDT | laggards | down | +0.50 | +1.48 | +0.48 |
| 09:33 | U | laggards | down | +0.55 | +2.53 | +1.45 |
| 09:34 | COHR | leaders | up | +0.63 | -1.48 | -0.60 |
| 09:34 | MRVL | leaders | up | +4.62 | +3.05 | +2.96 |
| 09:34 | NBIS | leaders | up | -0.91 | -1.87 | -1.83 |
| 09:34 | SMCI | laggards | down | +1.94 | +2.10 | +0.62 |
| 09:35 | ALAB | leaders | up | +2.52 | +1.16 | +2.23 |
| 09:35 | ARM | leaders | up | +1.47 | -0.12 | -1.82 |
| 09:35 | DASH | laggards | down | -0.56 | +0.35 | -1.05 |
| 09:35 | CPRT | laggards | down | +0.46 | +0.44 | +0.24 |
| 09:36 | QBTS | laggards | down | +2.06 | -1.01 | -1.39 |
| 09:39 | CVX | leaders | up | -0.80 | -0.86 | -0.80 |
| 09:39 | XOM | leaders | up | -0.78 | -0.79 | -0.49 |
| 09:39 | TDOC | laggards | down | -0.79 | -0.43 | -0.17 |
| 09:39 | CNC | laggards | down | -1.83 | +1.80 | +2.15 |
| 09:40 | UNH | laggards | down | -3.24 | -0.86 | -0.25 |
| 09:40 | HIMS | laggards | down | -0.72 | +0.33 | +0.23 |
| 09:42 | CIFR | laggards | down | -0.12 | -1.68 | -4.89 |
| 09:44 | ASTS | laggards | down | -0.05 | -1.25 | -1.15 |
| 09:47 | DDOG | leaders | up | +1.91 | +3.60 | +4.26 |
| 09:47 | RCAT | laggards | down | -0.58 | -0.63 | -1.30 |
| 09:48 | AMD | leaders | up | +0.89 | +0.83 | +1.33 |
| 09:52 | RBLX | laggards | down | +0.53 | +0.87 | +0.56 |
| 09:53 | MU | leaders | up | +0.69 | +0.93 | -0.13 |
| 09:54 | HUM | laggards | down | +0.81 | +1.93 | — |
| 09:58 | CVS | laggards | down | +1.32 | +1.49 | +2.22 |
| 09:59 | SNDK | leaders | up | -0.34 | +0.05 | -0.88 |
| 10:11 | LCID | laggards | down | -2.39 | -3.30 | -3.91 |
| 10:19 | LUNR | laggards | down | -1.16 | -1.48 | -0.94 |
| 10:22 | ZS | leaders | up | +0.68 | +0.42 | -0.63 |
| 10:24 | RGTI | laggards | down | +0.35 | -0.74 | +1.57 |
| 10:35 | RKLB | laggards | down | +0.26 | +0.10 | +1.25 |
| 11:00 | WDC | leaders | up | -0.73 | +0.37 | +0.44 |
| 11:04 | CRDO | leaders | up | -1.05 | -0.84 | -2.03 |
| 11:33 | PINS | laggards | down | -2.68 | -2.55 | -2.73 |
| 12:10 | WULF | laggards | down | -0.48 | -0.81 | +0.36 |
| 12:18 | APLD | laggards | down | +0.16 | +0.05 | +0.89 |
| 12:34 | CRWV | laggards | down | -0.30 | -0.90 | -1.15 |
| 12:40 | MDB | leaders | up | -0.33 | -0.69 | -0.77 |
| 12:48 | IREN | laggards | down | -0.02 | +0.91 | +0.73 |
| 13:44 | IBM | leaders | up | +0.06 | +0.47 | +1.28 |
| 13:46 | HPQ | leaders | up | +0.64 | +2.49 | +3.02 |
| 14:13 | SOFI | laggards | down | -0.09 | +0.10 | — |

## 2026-09-10

Usable symbol-minutes 64,388/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | RDDT | +6.68 | miss | 09:36 |
| 2 | OKLO | -5.72 | miss | 10:09 |
| 3 | ELV | +5.55 | miss | 09:31 |
| 4 | CRWV | -5.53 | miss | 09:31 |
| 5 | WULF | -5.18 | miss | 09:31 |
| 6 | CIFR | -5.08 | miss | 09:31 |
| 7 | INTC | -4.97 | miss | 09:33 |
| 8 | MDB | +4.92 | miss | 09:42 |
| 9 | ORCL | -4.78 | miss | 14:37 |
| 10 | DELL | -4.75 | miss | 10:26 |
| 11 | ALAB | -4.73 | miss | 09:31 |
| 12 | SNAP | +4.55 | miss | 10:21 |
| 13 | NBIS | -4.49 | miss | 09:45 |
| 14 | RIOT | -4.48 | miss | 09:31 |
| 15 | APLD | -4.41 | miss | 09:31 |
| 16 | HSAI | -4.32 | miss | 09:40 |
| 17 | MU | -4.30 | miss | 09:33 |
| 18 | AAPL | +4.16 | miss | 09:31 |
| 19 | CRDO | -3.93 | miss | 09:35 |
| 20 | WDC | -3.83 | miss | 09:31 |

### Radar flags (5)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | Cybersecurity (ZS, CRWD, PANW, FTNT, S, NET) | group_move | up | -0.61 | -0.12 | -0.06 |
| 10:02 | Space (LUNR, ASTS, PL, RKLB) | group_move | up | -0.58 | -1.08 | -1.94 |
| 10:28 | Bitcoin treasuries and miners (IREN, CLSK, RIOT, MARA, COIN) | group_move | up | +1.69 | +0.41 | -0.65 |
| 10:30 | CIFR | relative_to_spy | up | -0.13 | -0.72 | -1.09 |
| 10:30 | Neoclouds and AI hosting (CIFR, WULF, IREN, APLD, CRWV, ORCL, NBIS) | group_move | up | +0.40 | -0.18 | -1.60 |

### Movers flags (67)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | ELV | leaders | up | -0.88 | -2.70 | -2.13 |
| 09:31 | CNC | leaders | up | +1.52 | +0.05 | -0.14 |
| 09:31 | CI | leaders | up | -0.92 | -1.59 | -1.60 |
| 09:31 | HUM | leaders | up | +0.63 | -0.39 | -0.95 |
| 09:31 | XOM | leaders | up | -1.16 | -1.86 | -1.57 |
| 09:31 | AN | leaders | up | -1.94 | — | — |
| 09:31 | CVS | leaders | up | -0.50 | -1.60 | -1.74 |
| 09:31 | AAPL | leaders | up | -0.17 | -0.15 | +1.06 |
| 09:31 | COP | leaders | up | -1.06 | -2.00 | -1.52 |
| 09:31 | NOW | leaders | up | +0.89 | -0.15 | +0.76 |
| 09:31 | CIFR | laggards | down | -2.09 | +2.55 | +1.72 |
| 09:31 | CRWV | laggards | down | -0.21 | +1.41 | +2.11 |
| 09:31 | RIOT | laggards | down | +0.60 | +2.98 | +2.48 |
| 09:31 | APLD | laggards | down | +1.78 | +3.14 | +2.61 |
| 09:31 | CLSK | laggards | down | +0.87 | +2.36 | +3.39 |
| 09:31 | ARM | laggards | down | +0.14 | +0.34 | +0.28 |
| 09:31 | WULF | laggards | down | +0.03 | +2.56 | +1.46 |
| 09:31 | FLNC | laggards | down | +0.38 | +1.12 | +0.90 |
| 09:31 | ALAB | laggards | down | -1.97 | -0.86 | +0.39 |
| 09:31 | WDC | laggards | down | -0.71 | +0.43 | -0.29 |
| 09:32 | SHEL | leaders | up | -0.84 | -1.22 | -1.34 |
| 09:32 | CVX | leaders | up | -1.78 | -2.15 | -1.77 |
| 09:32 | UNH | leaders | up | -0.28 | -1.71 | -1.86 |
| 09:32 | MARA | laggards | down | +1.28 | +1.48 | +1.50 |
| 09:32 | MSTR | laggards | down | +3.48 | +2.16 | +2.25 |
| 09:33 | INTC | laggards | down | -0.78 | -0.84 | -0.07 |
| 09:33 | MU | laggards | down | +0.89 | +0.70 | -0.24 |
| 09:34 | RCAT | leaders | up | +1.20 | +2.54 | +1.02 |
| 09:34 | KMX | leaders | up | -1.29 | -0.38 | -0.84 |
| 09:34 | SNDK | laggards | down | +0.76 | +0.60 | +0.07 |
| 09:34 | COHR | laggards | down | +4.59 | +4.74 | +3.22 |
| 09:35 | WMT | leaders | up | -0.57 | -0.55 | -1.30 |
| 09:35 | CRDO | laggards | down | +0.07 | +1.07 | +1.38 |
| 09:36 | RDDT | leaders | up | +2.65 | +4.89 | +4.21 |
| 09:37 | LUNR | leaders | up | -1.02 | +0.48 | -1.23 |
| 09:37 | ASTS | leaders | up | +0.29 | +0.64 | -1.44 |
| 09:37 | RKLB | leaders | up | -0.22 | +0.66 | -0.46 |
| 09:40 | PL | leaders | up | -0.98 | -0.97 | -2.52 |
| 09:40 | HSAI | laggards | down | -0.66 | -0.31 | -0.47 |
| 09:41 | COHR | leaders | up | -1.83 | -0.50 | -2.76 |
| 09:42 | MDB | leaders | up | +1.25 | +1.99 | +1.85 |
| 09:45 | NBIS | laggards | down | -0.42 | +0.07 | -0.18 |
| 09:46 | SNOW | leaders | up | -0.08 | -1.01 | -1.45 |
| 09:47 | FTNT | leaders | up | -0.68 | -0.58 | -0.05 |
| 09:47 | PANW | leaders | up | -1.44 | -0.80 | -0.16 |
| 09:50 | CRWD | leaders | up | -1.26 | -0.76 | +0.15 |
| 09:51 | PINS | leaders | up | -0.21 | +0.23 | -0.17 |
| 09:55 | F | leaders | up | +0.81 | +1.19 | +0.88 |
| 10:05 | APP | leaders | up | +1.26 | +0.89 | +1.29 |
| 10:09 | OKLO | laggards | down | +1.96 | +1.39 | +0.91 |
| 10:21 | SNAP | leaders | up | +0.89 | +0.41 | +0.85 |
| 10:22 | TTWO | leaders | up | +0.17 | +0.64 | +1.22 |
| 10:23 | RIVN | leaders | up | +0.29 | -1.07 | -0.71 |
| 10:26 | DELL | laggards | down | +0.01 | +0.41 | -0.17 |
| 10:28 | CIEN | leaders | up | -0.86 | -1.73 | -2.72 |
| 10:38 | URI | laggards | down | -0.43 | -0.71 | -0.82 |
| 10:42 | CVNA | laggards | down | -0.26 | +0.44 | -0.77 |
| 11:36 | STX | laggards | down | -0.09 | -0.54 | +0.37 |
| 11:39 | S | leaders | up | -0.09 | +0.65 | +0.04 |
| 12:42 | LCID | leaders | up | -1.13 | -1.45 | -2.87 |
| 12:47 | QCOM | leaders | up | -0.81 | -1.14 | -1.68 |
| 13:13 | UBER | leaders | up | -0.74 | -1.27 | -0.51 |
| 13:47 | AAOI | laggards | down | -0.14 | -0.08 | -0.24 |
| 13:52 | DASH | leaders | up | -0.49 | -0.30 | -0.59 |
| 14:11 | GM | leaders | up | -0.04 | +0.18 | — |
| 14:37 | ORCL | laggards | down | -0.20 | -0.83 | — |
| 15:07 | HPQ | leaders | up | -0.43 | — | — |

## 2026-09-11

Usable symbol-minutes 64,322/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | DELL | +11.12 | 10:02 | 09:31 |
| 2 | OKLO | -10.03 | miss | 09:31 |
| 3 | HPQ | +7.55 | 10:09 | 09:32 |
| 4 | SMCI | +6.42 | 10:28 | 10:12 |
| 5 | CLSK | +5.94 | 10:05 | 09:31 |
| 6 | CIFR | +4.86 | 10:18 | 09:42 |
| 7 | ANET | +4.76 | miss | 09:32 |
| 8 | STX | -4.58 | miss | 09:34 |
| 9 | SNDK | -4.35 | 10:02 | 09:33 |
| 10 | MDB | -3.97 | miss | 09:32 |
| 11 | MARA | +3.96 | 10:06 | 09:31 |
| 12 | WDC | -3.84 | miss | 09:36 |
| 13 | U | +3.64 | miss | 14:33 |
| 14 | CIEN | +3.63 | miss | 09:31 |
| 15 | CPRT | -3.45 | miss | 09:34 |
| 16 | ARM | +3.32 | miss | 13:29 |
| 17 | COHR | +3.31 | miss | 09:31 |
| 18 | UNH | -3.22 | miss | 09:49 |
| 19 | MRVL | +3.17 | miss | 09:33 |
| 20 | PANW | -3.17 | miss | 09:32 |

### Radar flags (14)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | DELL | relative_to_spy | up | +1.28 | +1.07 | +1.08 |
| 10:02 | SNDK | relative_to_sector | down | +0.16 | +0.14 | +0.39 |
| 10:02 | Bitcoin treasuries and miners (MSTR, CLSK, MARA, COIN, RIOT) | group_move | up | +0.36 | +0.16 | -0.07 |
| 10:02 | Consumer hardware (DELL, HPQ, AAPL) | group_move | up | +1.19 | +1.08 | +0.11 |
| 10:02 | Crypto and exchanges (MSTR, MARA, COIN, CRCL, BULL, HOOD, RIOT) | group_move | up | -0.52 | -0.32 | -1.07 |
| 10:02 | Memory and storage (SNDK, STX, WDC, MU) | group_move | down | +0.14 | -0.71 | -0.07 |
| 10:04 | MSTR | relative_to_spy | up | -0.84 | -0.62 | -2.19 |
| 10:05 | CLSK | relative_to_spy | up | +0.13 | +0.61 | +0.56 |
| 10:06 | MARA | relative_to_spy | up | -1.15 | -0.70 | -0.88 |
| 10:09 | HPQ | relative_to_spy | up | +0.79 | -0.45 | -2.51 |
| 10:09 | Quantum computing (RGTI, IONQ, QBTS, QUBT) | group_move | up | -1.17 | +0.31 | +0.65 |
| 10:18 | CIFR | relative_to_sector | up | -1.66 | -0.18 | +0.47 |
| 10:21 | CIFR | relative_to_spy | up | -2.21 | -0.59 | -0.79 |
| 10:28 | SMCI | relative_to_spy | up | -0.29 | -1.71 | -2.32 |

### Movers flags (67)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | ORCL | leaders | up | -5.78 | -6.75 | -7.23 |
| 09:31 | COHR | leaders | up | -4.14 | -3.12 | -2.00 |
| 09:31 | AAOI | leaders | up | -1.35 | -0.91 | -1.61 |
| 09:31 | MARA | leaders | up | +2.98 | +3.37 | +3.60 |
| 09:31 | CIEN | leaders | up | -0.76 | +0.77 | +1.71 |
| 09:31 | DELL | leaders | up | +6.12 | +7.29 | +6.86 |
| 09:31 | FND | leaders | up | -1.22 | -1.84 | -1.92 |
| 09:31 | CPRT | leaders | up | -4.69 | -3.77 | -2.73 |
| 09:31 | CRWV | leaders | up | -1.28 | -0.94 | -1.12 |
| 09:31 | CLSK | leaders | up | +3.06 | +5.16 | +5.78 |
| 09:31 | OKLO | laggards | down | -2.20 | -3.01 | -4.96 |
| 09:31 | NVO | laggards | down | -0.35 | -0.77 | -0.79 |
| 09:31 | HSAI | laggards | down | +0.23 | -0.23 | +0.20 |
| 09:31 | FTNT | laggards | down | +0.46 | -0.61 | -1.09 |
| 09:31 | SNOW | laggards | down | +1.05 | -0.17 | -0.32 |
| 09:31 | CRWD | laggards | down | +1.84 | -0.38 | -1.23 |
| 09:31 | DDOG | laggards | down | +1.40 | +0.01 | -0.13 |
| 09:31 | APP | laggards | down | -0.28 | +0.53 | +1.74 |
| 09:31 | ADBE | laggards | down | -0.45 | -0.42 | -0.11 |
| 09:31 | HOOD | laggards | down | +1.23 | +0.98 | +0.87 |
| 09:32 | UAA | leaders | up | -1.02 | +0.22 | -0.46 |
| 09:32 | HPQ | leaders | up | +4.35 | +6.33 | +3.47 |
| 09:32 | ANET | leaders | up | +1.72 | +2.65 | +2.34 |
| 09:32 | MDB | laggards | down | +0.14 | -0.31 | -1.18 |
| 09:32 | LUNR | laggards | down | +1.98 | +0.30 | -0.76 |
| 09:32 | PANW | laggards | down | +0.49 | -0.98 | -2.21 |
| 09:32 | PDD | laggards | down | +0.19 | +0.24 | +0.43 |
| 09:33 | SNAP | leaders | up | -1.79 | -2.25 | -2.11 |
| 09:33 | INTC | leaders | up | +1.48 | +0.44 | +0.56 |
| 09:33 | MRVL | leaders | up | +1.20 | +0.71 | +1.94 |
| 09:33 | SNDK | laggards | down | -2.97 | -3.02 | -2.57 |
| 09:33 | COP | laggards | down | +0.67 | +0.13 | -0.48 |
| 09:33 | IONQ | laggards | down | +1.81 | +1.21 | +2.62 |
| 09:33 | XOM | laggards | down | +1.22 | +0.69 | +0.03 |
| 09:34 | ALAB | leaders | up | -0.36 | +0.34 | -0.41 |
| 09:34 | CPRT | laggards | down | +0.41 | +0.40 | +1.66 |
| 09:34 | STX | laggards | down | -3.45 | -2.57 | -3.17 |
| 09:36 | WDC | laggards | down | -1.43 | -0.84 | -1.73 |
| 09:37 | DECK | leaders | up | -0.58 | -0.30 | -0.40 |
| 09:37 | RDDT | leaders | up | -2.28 | -2.24 | -1.96 |
| 09:37 | META | leaders | up | -0.55 | -0.91 | -0.85 |
| 09:37 | AAPL | leaders | up | -0.13 | +0.34 | +0.50 |
| 09:38 | QCOM | leaders | up | +0.91 | +0.54 | +1.72 |
| 09:38 | OXY | laggards | down | +0.81 | +0.56 | +0.15 |
| 09:41 | ZS | laggards | down | +2.55 | +2.07 | +1.77 |
| 09:42 | CIFR | leaders | up | +0.96 | +2.52 | +3.60 |
| 09:42 | WULF | leaders | up | +1.40 | +1.66 | +3.11 |
| 09:42 | HIMS | laggards | down | +0.23 | +0.39 | +0.62 |
| 09:49 | UNH | laggards | down | -0.11 | -1.49 | -1.44 |
| 09:51 | UBER | laggards | down | -0.09 | -0.96 | -0.99 |
| 09:52 | MSTR | leaders | up | +2.09 | +1.51 | +0.66 |
| 09:53 | CRCL | leaders | up | +0.12 | +0.79 | -0.88 |
| 09:56 | RIVN | leaders | up | -2.46 | -1.85 | -2.72 |
| 09:56 | PINS | laggards | down | +0.48 | +0.70 | +0.73 |
| 09:57 | LAD | laggards | down | +0.21 | +1.13 | — |
| 10:00 | CVNA | laggards | down | -0.47 | +1.51 | +1.41 |
| 10:02 | COIN | leaders | up | +0.30 | +0.85 | -0.60 |
| 10:04 | AMGN | laggards | down | -0.20 | +0.20 | -0.01 |
| 10:05 | RIOT | leaders | up | -1.10 | -0.77 | -0.89 |
| 10:07 | MU | laggards | down | +1.17 | +0.61 | +0.90 |
| 10:12 | SMCI | leaders | up | +2.95 | +1.53 | +1.12 |
| 10:22 | ORCL | laggards | down | +2.00 | +1.63 | +0.34 |
| 11:11 | NET | laggards | down | -0.44 | +0.35 | +0.17 |
| 11:20 | FLNC | leaders | up | -0.95 | -0.11 | -0.41 |
| 13:29 | ARM | leaders | up | +0.11 | -0.33 | -0.83 |
| 14:33 | U | leaders | up | -0.03 | +0.55 | — |
| 15:48 | IBM | leaders | up | — | — | — |

## 2026-09-14

Usable symbol-minutes 64,488/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | ZS | +16.97 | miss | 09:31 |
| 2 | S | +14.93 | miss | 09:31 |
| 3 | CRWD | +14.30 | miss | 09:31 |
| 4 | PANW | +13.54 | 10:12 | 09:31 |
| 5 | RBLX | +13.17 | miss | 09:31 |
| 6 | COHR | -12.28 | miss | 09:31 |
| 7 | ALAB | -11.29 | miss | 09:31 |
| 8 | COIN | +9.68 | miss | 09:31 |
| 9 | FTNT | +9.49 | miss | 09:31 |
| 10 | ARM | -9.29 | miss | 09:31 |
| 11 | AAOI | -8.67 | miss | 09:31 |
| 12 | NET | +8.22 | miss | 09:36 |
| 13 | CIEN | -8.11 | miss | 09:34 |
| 14 | CRCL | +7.97 | miss | 09:31 |
| 15 | SMCI | -7.93 | miss | 09:31 |
| 16 | NOW | +7.86 | miss | 09:31 |
| 17 | CRDO | -7.45 | miss | 09:35 |
| 18 | WULF | -7.14 | miss | 09:41 |
| 19 | MRVL | -6.87 | miss | 09:31 |
| 20 | CIFR | -6.76 | miss | 09:31 |

### Radar flags (6)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | Bitcoin treasuries and miners (MARA, CLSK, IREN, COIN, MSTR, RIOT) | group_move | up | +0.88 | -0.36 | +0.33 |
| 10:02 | Cybersecurity (ZS, CRWD, PANW, NET, S, FTNT) | group_move | up | +2.11 | +3.75 | +3.95 |
| 10:09 | Memory and storage (STX, SNDK, WDC, MU) | group_move | up | -0.43 | -0.63 | -0.44 |
| 10:11 | Neoclouds and AI hosting (CIFR, IREN, APLD, NBIS, WULF, CRWV, ORCL) | group_move | up | -0.92 | -1.71 | -1.68 |
| 10:12 | PANW | relative_to_spy | up | +0.94 | +2.55 | +1.91 |
| 10:30 | Quantum computing (RGTI, QBTS, IONQ, QUBT) | group_move | up | -1.06 | -0.01 | +0.38 |

### Movers flags (37)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | CRWD | leaders | up | +3.32 | +5.76 | +7.90 |
| 09:31 | NOW | leaders | up | -0.97 | -1.01 | +0.77 |
| 09:31 | S | leaders | up | +3.29 | +5.69 | +9.77 |
| 09:31 | ZS | leaders | up | +3.81 | +6.77 | +9.94 |
| 09:31 | FTNT | leaders | up | +0.47 | +2.11 | +3.58 |
| 09:31 | RBLX | leaders | up | +1.91 | +2.85 | +6.13 |
| 09:31 | COIN | leaders | up | +2.76 | +1.95 | +2.38 |
| 09:31 | CPRT | leaders | up | -1.53 | +0.43 | +0.81 |
| 09:31 | CRCL | leaders | up | -0.82 | -0.70 | -0.32 |
| 09:31 | PANW | leaders | up | +4.09 | +7.30 | +9.20 |
| 09:31 | ARM | laggards | down | +0.64 | +2.07 | -0.61 |
| 09:31 | MRVL | laggards | down | +1.89 | +2.64 | +2.03 |
| 09:31 | AAOI | laggards | down | +1.51 | +2.03 | +1.54 |
| 09:31 | ALAB | laggards | down | +0.20 | -0.15 | -1.49 |
| 09:31 | NBIS | laggards | down | +4.28 | +4.87 | +3.76 |
| 09:31 | MARA | laggards | down | +5.02 | +6.23 | +4.86 |
| 09:31 | COHR | laggards | down | -1.53 | -1.91 | -1.80 |
| 09:31 | CIFR | laggards | down | +2.34 | +4.12 | +2.57 |
| 09:31 | SMCI | laggards | down | +0.96 | +1.43 | +1.22 |
| 09:31 | INTC | laggards | down | +1.04 | +1.76 | +2.34 |
| 09:32 | SPOT | leaders | up | +1.34 | +0.68 | +0.86 |
| 09:33 | ADBE | leaders | up | -1.12 | -0.20 | -0.42 |
| 09:33 | SNDK | laggards | down | +0.93 | +1.90 | +1.61 |
| 09:33 | MU | laggards | down | -0.35 | +0.77 | +1.41 |
| 09:34 | CIEN | laggards | down | +0.43 | +0.83 | +0.75 |
| 09:35 | CRDO | laggards | down | -0.17 | -0.23 | +0.20 |
| 09:36 | NET | leaders | up | +1.88 | +1.63 | +2.56 |
| 09:40 | APLD | laggards | down | +2.76 | +1.93 | +1.49 |
| 09:41 | WULF | laggards | down | +2.42 | +1.77 | +0.58 |
| 09:46 | DELL | laggards | down | +1.47 | -0.63 | +0.53 |
| 09:47 | ANET | laggards | down | +1.71 | +1.54 | +0.62 |
| 10:02 | HIMS | leaders | up | -0.49 | +0.09 | +1.38 |
| 10:14 | MSTR | leaders | up | -0.96 | -0.26 | -0.43 |
| 10:33 | CRWV | laggards | down | -0.41 | +0.69 | +0.29 |
| 10:45 | AMD | laggards | down | +0.05 | +1.31 | +1.57 |
| 11:08 | AI | leaders | up | -0.15 | +0.85 | +1.93 |
| 13:46 | BAC | laggards | down | -0.34 | -0.59 | -0.24 |

## 2026-09-15

Usable symbol-minutes 64,461/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | CRCL | -10.96 | miss | 09:31 |
| 2 | COIN | -9.64 | miss | 09:31 |
| 3 | WULF | -5.88 | miss | 10:13 |
| 4 | RIOT | -5.51 | miss | 09:31 |
| 5 | CVNA | -5.14 | miss | 10:03 |
| 6 | CIEN | +5.05 | miss | 09:31 |
| 7 | MSTR | -4.90 | miss | 09:31 |
| 8 | QCOM | +4.71 | miss | 09:31 |
| 9 | TTWO | -4.48 | miss | 11:28 |
| 10 | CLSK | -4.44 | miss | 09:31 |
| 11 | S | +4.31 | miss | 11:59 |
| 12 | PINS | -4.26 | miss | 09:33 |
| 13 | APLD | -4.26 | miss | 14:44 |
| 14 | COP | +3.79 | miss | 09:37 |
| 15 | BULL | -3.74 | miss | 09:31 |
| 16 | FND | -3.74 | miss | miss |
| 17 | STX | -3.73 | miss | 09:37 |
| 18 | LAD | -3.53 | miss | miss |
| 19 | CRWD | +3.48 | miss | 11:48 |
| 20 | DECK | -3.30 | miss | 10:10 |

### Radar flags (5)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:13 | Space (RKLB, LUNR, ASTS, PL, IRDM) | group_move | down | — | — | — |
| 12:33 | Space (LUNR, ASTS, RKLB, PL) | group_move | up | +1.21 | +0.19 | +0.81 |
| 14:47 | Crypto and exchanges (COIN, CRCL, MSTR, HOOD, MARA, BULL, RIOT) | group_move | down | +2.73 | +1.67 | — |
| 15:18 | Crypto and exchanges (HOOD, CRCL, COIN, MSTR, MARA, BULL, RIOT) | group_move | up | -1.21 | — | — |
| 15:19 | Bitcoin treasuries and miners (COIN, MSTR, CLSK, MARA, IREN, RIOT) | group_move | up | -1.15 | — | — |

### Movers flags (55)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | COHR | leaders | up | +0.09 | +0.27 | -0.59 |
| 09:31 | AAOI | leaders | up | +0.40 | -0.38 | -1.64 |
| 09:31 | QCOM | leaders | up | +1.72 | +1.13 | +1.99 |
| 09:31 | RKLB | leaders | up | -0.58 | -0.93 | -2.82 |
| 09:31 | ANET | leaders | up | +0.68 | +0.37 | +1.01 |
| 09:31 | CIEN | leaders | up | -1.17 | +1.58 | +2.14 |
| 09:31 | WFC | leaders | up | +1.01 | +0.29 | -1.40 |
| 09:31 | MRVL | leaders | up | +2.12 | +0.98 | +1.12 |
| 09:31 | INTC | leaders | up | +1.07 | +0.56 | +0.45 |
| 09:31 | ARM | leaders | up | +3.85 | +2.15 | +1.86 |
| 09:31 | CRCL | laggards | down | -2.85 | -2.97 | -2.30 |
| 09:31 | COIN | laggards | down | -1.28 | -1.69 | -0.29 |
| 09:31 | MSTR | laggards | down | -0.24 | -0.58 | +1.23 |
| 09:31 | HOOD | laggards | down | -0.28 | -0.29 | +1.28 |
| 09:31 | CLSK | laggards | down | +0.75 | -0.27 | +0.45 |
| 09:31 | MARA | laggards | down | +1.02 | +0.53 | +1.72 |
| 09:31 | BULL | laggards | down | -1.05 | -1.52 | -0.85 |
| 09:31 | RIOT | laggards | down | -0.86 | -1.24 | -1.13 |
| 09:31 | SONY | laggards | down | -0.35 | -0.19 | +0.34 |
| 09:31 | IREN | laggards | down | +0.37 | +0.11 | -1.46 |
| 09:32 | DELL | leaders | up | +4.12 | +2.39 | +1.64 |
| 09:32 | C | leaders | up | -0.07 | -1.21 | -2.08 |
| 09:32 | APP | laggards | down | +1.45 | +1.18 | +1.33 |
| 09:32 | SNOW | laggards | down | -1.02 | -0.97 | -0.15 |
| 09:33 | PINS | laggards | down | -0.34 | -1.50 | -1.54 |
| 09:33 | NFLX | laggards | down | -0.56 | -0.72 | -0.42 |
| 09:34 | ADBE | laggards | down | -0.09 | -0.22 | +0.76 |
| 09:34 | RIVN | laggards | down | +0.39 | +0.86 | -0.13 |
| 09:35 | AMD | leaders | up | +1.38 | +0.75 | +0.05 |
| 09:36 | LCID | laggards | down | +1.99 | +2.36 | +0.53 |
| 09:37 | SNAP | leaders | up | -0.90 | -1.58 | -1.32 |
| 09:37 | OXY | leaders | up | +0.29 | +0.25 | +0.73 |
| 09:37 | COP | leaders | up | -0.16 | -0.30 | +0.93 |
| 09:37 | STX | laggards | down | -0.03 | -0.40 | -1.36 |
| 09:40 | WDC | laggards | down | +2.14 | +0.83 | +0.56 |
| 09:41 | LUNR | leaders | up | -4.09 | -3.00 | -3.79 |
| 09:42 | AI | laggards | down | +0.42 | -0.62 | -0.05 |
| 09:43 | CRDO | leaders | up | -0.61 | -1.00 | -1.47 |
| 09:45 | ORCL | laggards | down | +0.10 | +1.42 | +1.68 |
| 10:03 | CVNA | laggards | down | +0.03 | -0.71 | -0.93 |
| 10:10 | DECK | laggards | down | +0.18 | +0.09 | +0.03 |
| 10:13 | WULF | laggards | down | -1.10 | -0.94 | -1.46 |
| 10:42 | SHEL | leaders | up | +0.35 | +0.60 | +0.62 |
| 11:15 | XOM | leaders | up | +0.37 | +0.55 | +0.43 |
| 11:25 | ASTS | laggards | down | +0.31 | +1.47 | +2.59 |
| 11:28 | TTWO | laggards | down | -0.43 | -0.19 | -0.05 |
| 11:29 | SOFI | laggards | down | +0.86 | +0.68 | +1.14 |
| 11:48 | CRWD | leaders | up | -0.48 | +0.78 | +0.53 |
| 11:56 | NOW | leaders | up | +0.31 | -0.01 | -1.18 |
| 11:59 | S | leaders | up | +0.71 | +1.69 | +0.71 |
| 12:27 | TDOC | leaders | up | +0.22 | +1.09 | +0.10 |
| 12:31 | RCAT | leaders | up | +0.52 | +0.33 | +0.25 |
| 13:23 | CIFR | laggards | down | +0.48 | +0.30 | +1.45 |
| 14:44 | APLD | laggards | down | +0.66 | +0.07 | — |
| 14:48 | CVX | leaders | up | -0.10 | +0.09 | — |

## 2026-09-16

Usable symbol-minutes 64,583/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | CIFR | +11.24 | miss | 09:31 |
| 2 | BULL | -10.76 | miss | 09:31 |
| 3 | RCAT | -10.48 | miss | 09:32 |
| 4 | CRDO | +7.82 | miss | 09:32 |
| 5 | COHR | +7.36 | miss | 09:31 |
| 6 | ALAB | +7.03 | miss | 09:33 |
| 7 | WULF | +6.65 | miss | 09:31 |
| 8 | CRCL | -6.34 | 10:02 | 09:33 |
| 9 | OXY | -6.11 | miss | 09:31 |
| 10 | COP | -5.71 | miss | 09:31 |
| 11 | RBLX | -5.15 | miss | 09:47 |
| 12 | HOOD | -5.02 | miss | 09:37 |
| 13 | APLD | +4.58 | miss | 09:31 |
| 14 | INTC | +4.47 | miss | 09:31 |
| 15 | DELL | +4.08 | miss | 09:32 |
| 16 | MRVL | +4.05 | miss | 09:41 |
| 17 | COIN | -3.97 | miss | 10:12 |
| 18 | IBM | -3.94 | miss | 09:31 |
| 19 | SMCI | +3.84 | miss | 15:59 |
| 20 | RIOT | +3.74 | miss | 09:58 |

### Radar flags (1)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | CRCL | relative_to_spy | down | -1.25 | -0.32 | +0.35 |

### Movers flags (49)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | CIFR | leaders | up | +4.34 | +5.43 | +7.25 |
| 09:31 | INTC | leaders | up | -0.72 | -0.54 | -0.21 |
| 09:31 | COHR | leaders | up | +1.06 | +2.10 | +2.18 |
| 09:31 | CIEN | leaders | up | -1.28 | -1.65 | -1.32 |
| 09:31 | AAOI | leaders | up | -1.27 | -0.04 | -0.22 |
| 09:31 | APLD | leaders | up | +0.78 | +1.03 | +1.32 |
| 09:31 | CRWV | leaders | up | +0.59 | +0.03 | +0.85 |
| 09:31 | NBIS | leaders | up | +0.02 | +0.84 | +1.73 |
| 09:31 | WULF | leaders | up | +0.46 | +1.42 | +2.02 |
| 09:31 | IREN | leaders | up | -0.40 | +0.71 | +1.67 |
| 09:31 | BULL | laggards | down | -2.43 | -2.23 | -3.87 |
| 09:31 | IBM | laggards | down | -0.40 | -0.38 | -0.17 |
| 09:31 | COP | laggards | down | -1.51 | -1.74 | -2.73 |
| 09:31 | OXY | laggards | down | -1.77 | -2.21 | -3.23 |
| 09:31 | ZS | laggards | down | +2.16 | +1.47 | +3.17 |
| 09:31 | AI | laggards | down | -0.79 | +0.34 | +0.38 |
| 09:31 | CVX | laggards | down | -0.29 | -0.38 | -1.36 |
| 09:31 | XOM | laggards | down | -0.71 | -0.97 | -1.78 |
| 09:31 | CRWD | laggards | down | +0.88 | +0.75 | +2.45 |
| 09:31 | NOW | laggards | down | +0.97 | +0.76 | +0.74 |
| 09:32 | CRDO | leaders | up | +2.27 | +3.51 | +3.91 |
| 09:32 | DELL | leaders | up | +0.74 | +0.74 | +2.05 |
| 09:32 | AXP | laggards | down | -0.83 | -0.64 | -0.52 |
| 09:32 | RCAT | laggards | down | -2.01 | -1.62 | -5.47 |
| 09:32 | ADBE | laggards | down | -0.09 | -0.04 | -1.06 |
| 09:33 | ARM | leaders | up | -0.11 | -0.67 | -0.37 |
| 09:33 | ALAB | leaders | up | +0.91 | +2.29 | +2.92 |
| 09:33 | CRCL | laggards | down | -4.70 | -5.64 | -4.75 |
| 09:34 | LCID | laggards | down | -0.79 | -0.46 | -0.08 |
| 09:35 | AMD | leaders | up | +0.41 | +0.88 | +1.15 |
| 09:36 | WDC | leaders | up | +0.21 | +0.66 | +0.17 |
| 09:36 | PL | laggards | down | +1.45 | +1.11 | +2.08 |
| 09:37 | HOOD | laggards | down | -0.41 | -1.87 | -3.04 |
| 09:41 | MRVL | leaders | up | +1.31 | +0.79 | -0.12 |
| 09:47 | RBLX | laggards | down | -0.89 | -0.31 | -1.02 |
| 09:58 | RIOT | leaders | up | +0.01 | -0.24 | +0.66 |
| 09:59 | RIVN | laggards | down | +0.91 | +1.20 | +0.62 |
| 10:02 | ORCL | leaders | up | -1.52 | -1.96 | -1.73 |
| 10:06 | APP | laggards | down | +2.02 | +3.22 | +1.99 |
| 10:12 | COIN | laggards | down | +0.12 | -0.10 | -1.65 |
| 10:50 | MSTR | laggards | down | -0.16 | -0.31 | -0.07 |
| 11:08 | SHEL | laggards | down | +0.37 | +0.40 | +0.47 |
| 11:11 | SNOW | leaders | up | -0.53 | -1.23 | -1.14 |
| 13:50 | ONON | leaders | up | +0.02 | +0.30 | -0.64 |
| 14:00 | AN | laggards | down | — | +0.04 | -0.51 |
| 15:03 | PCAR | laggards | down | +0.04 | — | — |
| 15:29 | ANET | leaders | up | +0.61 | — | — |
| 15:45 | GS | laggards | down | — | — | — |
| 15:59 | SMCI | leaders | up | — | — | — |

## 2026-09-17

Usable symbol-minutes 64,735/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | FLNC | -16.49 | miss | 09:31 |
| 2 | AN | -11.62 | miss | 11:23 |
| 3 | OKLO | +10.18 | miss | 09:42 |
| 4 | IONQ | +8.37 | miss | 09:41 |
| 5 | SMCI | +8.36 | 10:50 | 09:39 |
| 6 | ALAB | +7.92 | miss | 09:34 |
| 7 | QBTS | +7.59 | miss | 10:08 |
| 8 | ARM | +7.44 | miss | 09:31 |
| 9 | APLD | +7.03 | miss | 09:31 |
| 10 | RGTI | +6.98 | miss | 09:41 |
| 11 | INTC | +6.54 | miss | 09:37 |
| 12 | RIOT | +6.38 | miss | 09:31 |
| 13 | LAD | -6.31 | 11:44 | 11:26 |
| 14 | WULF | +5.88 | miss | 09:31 |
| 15 | LUNR | +5.50 | 10:02 | 09:40 |
| 16 | RKLB | +5.33 | miss | 10:16 |
| 17 | CRWV | -5.30 | miss | 09:31 |
| 18 | AMD | +5.23 | miss | 11:34 |
| 19 | SNDK | +5.08 | miss | 09:35 |
| 20 | PL | +4.92 | miss | 15:44 |

### Radar flags (24)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | CIFR | relative_to_spy | down | +0.90 | +3.70 | +3.43 |
| 10:02 | IREN | relative_to_spy | down | -0.03 | +1.08 | +1.17 |
| 10:02 | NBIS | relative_to_spy | down | -0.29 | +0.84 | +0.16 |
| 10:02 | CLSK | relative_to_sector | down | -0.38 | +2.00 | +3.11 |
| 10:02 | LUNR | relative_to_sector | up | -0.21 | +0.20 | -0.54 |
| 10:02 | MARA | relative_to_sector | down | +0.54 | +2.44 | +4.91 |
| 10:02 | Bitcoin treasuries and miners (IREN, CLSK, MARA, RIOT) | group_move | down | +0.16 | +2.04 | +3.10 |
| 10:02 | Cybersecurity (CRWD, PANW, ZS, S, FTNT, NET) | group_move | up | +1.93 | +0.96 | -0.00 |
| 10:02 | Neoclouds and AI hosting (CIFR, IREN, NBIS, WULF, APLD, CRWV) | group_move | down | -0.01 | +1.83 | +1.97 |
| 10:02 | Space (LUNR, RKLB, ASTS, PL, IRDM) | group_move | up | +0.03 | +0.19 | — |
| 10:03 | LCID | relative_to_spy | up | -2.32 | -1.99 | -1.27 |
| 10:03 | WULF | relative_to_sector | down | +1.05 | +3.63 | +3.41 |
| 10:04 | Quantum computing (QBTS, RGTI, IONQ, QUBT) | group_move | up | +0.52 | +2.05 | +2.28 |
| 10:05 | CLSK | relative_to_spy | down | +1.75 | +3.70 | +5.04 |
| 10:05 | Gaming platforms (RBLX, APP, TTWO, U) | group_move | down | +0.57 | -0.09 | +0.01 |
| 10:07 | APLD | relative_to_spy | down | +0.93 | +3.11 | +4.37 |
| 10:07 | MARA | relative_to_spy | down | +1.93 | +3.80 | +6.64 |
| 10:23 | COHR | relative_to_spy | down | +0.80 | +0.68 | +0.66 |
| 10:25 | Memory and storage (STX, WDC, SNDK, MU) | group_move | down | +0.49 | +0.86 | +0.23 |
| 10:50 | SMCI | relative_to_sector | up | -1.20 | -1.54 | -0.11 |
| 10:54 | Bitcoin treasuries and miners (CLSK, MARA, RIOT, IREN) | group_move | up | -1.15 | +0.50 | +1.27 |
| 10:59 | Neoclouds and AI hosting (CIFR, WULF, APLD, IREN, NBIS, CRWV, ORCL) | group_move | up | -1.16 | -0.56 | +0.11 |
| 11:28 | Space (LUNR, RKLB, ASTS, PL, IRDM) | group_move | down | — | — | — |
| 11:44 | LAD | relative_to_spy | down | +1.53 | +0.70 | -0.33 |

### Movers flags (55)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | CIFR | leaders | up | -8.44 | -8.21 | -5.43 |
| 09:31 | NBIS | leaders | up | -5.98 | -7.96 | -7.86 |
| 09:31 | WULF | leaders | up | -3.98 | -4.47 | -1.99 |
| 09:31 | IREN | leaders | up | -5.84 | -6.45 | -5.63 |
| 09:31 | APLD | leaders | up | -2.28 | -3.66 | -1.33 |
| 09:31 | ARM | leaders | up | +1.47 | +0.07 | -0.40 |
| 09:31 | CLSK | leaders | up | -4.17 | -5.14 | -3.05 |
| 09:31 | RIOT | leaders | up | -2.01 | -1.78 | +0.04 |
| 09:31 | MRVL | leaders | up | +2.08 | -0.44 | -0.28 |
| 09:31 | LCID | leaders | up | +5.43 | +5.35 | +2.93 |
| 09:31 | FLNC | laggards | down | +2.61 | +1.78 | +3.52 |
| 09:31 | PANW | laggards | down | +2.41 | +4.77 | +3.44 |
| 09:31 | CRWD | laggards | down | +4.01 | +6.46 | +4.59 |
| 09:31 | RDDT | laggards | down | -1.27 | -2.06 | -1.00 |
| 09:31 | CRWV | laggards | down | -2.41 | -3.09 | -1.92 |
| 09:31 | S | laggards | down | +3.69 | +6.24 | +4.60 |
| 09:31 | CRM | laggards | down | -1.11 | -0.65 | -0.64 |
| 09:31 | FTNT | laggards | down | +2.59 | +4.13 | +3.32 |
| 09:31 | CPRT | laggards | down | -1.31 | -1.82 | -2.32 |
| 09:31 | NET | laggards | down | +2.81 | +5.08 | +4.01 |
| 09:32 | LYFT | laggards | down | -0.93 | -0.04 | +0.26 |
| 09:33 | CIEN | leaders | up | +1.72 | -0.78 | -1.68 |
| 09:33 | ADBE | laggards | down | +0.20 | +0.54 | +1.46 |
| 09:34 | ALAB | leaders | up | +2.39 | -0.91 | -0.45 |
| 09:34 | NOW | laggards | down | +0.80 | +1.31 | +1.19 |
| 09:35 | SNDK | leaders | up | -0.36 | -0.78 | -0.12 |
| 09:37 | COHR | leaders | up | -2.39 | -4.03 | -5.13 |
| 09:37 | INTC | leaders | up | +1.89 | +2.35 | +2.85 |
| 09:38 | MU | leaders | up | -0.04 | +0.47 | +0.02 |
| 09:38 | ONON | laggards | down | -1.33 | -1.49 | -1.34 |
| 09:39 | SMCI | leaders | up | +0.12 | +3.14 | +3.75 |
| 09:39 | UAA | laggards | down | -1.29 | -1.22 | -1.42 |
| 09:40 | LUNR | leaders | up | +3.49 | +2.51 | +1.91 |
| 09:40 | APP | laggards | down | -0.54 | -1.36 | -1.60 |
| 09:41 | RGTI | leaders | up | +0.94 | +1.30 | +2.63 |
| 09:41 | IONQ | leaders | up | +1.42 | +2.80 | +3.26 |
| 09:42 | ASTS | leaders | up | +0.40 | -0.11 | -0.53 |
| 09:42 | OKLO | leaders | up | +0.99 | +1.05 | +5.34 |
| 09:45 | SPOT | laggards | down | +0.02 | +0.00 | -0.73 |
| 09:46 | GS | laggards | down | +1.10 | +1.36 | +1.99 |
| 09:50 | PINS | laggards | down | +0.48 | +0.72 | -0.29 |
| 09:58 | C | laggards | down | -0.14 | +0.25 | +1.18 |
| 10:08 | QBTS | leaders | up | +1.28 | +1.96 | +2.43 |
| 10:16 | RKLB | leaders | up | +0.15 | -1.55 | -0.30 |
| 10:25 | SCHW | laggards | down | +0.20 | +0.41 | +0.65 |
| 10:27 | MDB | leaders | up | +1.12 | +0.92 | +0.29 |
| 10:45 | TTWO | laggards | down | -0.27 | +0.17 | +0.43 |
| 11:23 | AN | laggards | down | -2.45 | -3.25 | -7.40 |
| 11:26 | LAD | laggards | down | -2.30 | -0.94 | — |
| 11:34 | AMD | leaders | up | -0.20 | +0.81 | +0.25 |
| 12:53 | DIS | laggards | down | +0.37 | +0.56 | +0.34 |
| 14:59 | DASH | laggards | down | -0.16 | +0.24 | — |
| 15:44 | PL | leaders | up | — | — | — |
| 15:55 | CI | laggards | down | — | — | — |
| 15:56 | TDOC | laggards | down | — | — | — |

## 2026-09-18

Usable symbol-minutes 64,542/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | MSTR | +16.50 | 10:02 | 09:31 |
| 2 | MARA | +13.87 | miss | 09:31 |
| 3 | COIN | +11.78 | miss | 09:31 |
| 4 | SNDK | +11.11 | miss | 09:56 |
| 5 | HOOD | +9.24 | miss | 09:31 |
| 6 | RIOT | +8.67 | miss | 09:31 |
| 7 | CLSK | +8.51 | miss | 09:33 |
| 8 | CIFR | +8.38 | miss | 09:31 |
| 9 | CRCL | +7.98 | miss | 09:31 |
| 10 | IREN | +7.48 | miss | 09:39 |
| 11 | AAOI | +7.37 | miss | 09:34 |
| 12 | COHR | +7.34 | miss | 09:31 |
| 13 | BULL | +7.12 | miss | 09:32 |
| 14 | STX | +7.05 | miss | 10:22 |
| 15 | APLD | +6.72 | miss | miss |
| 16 | ASTS | -6.56 | miss | 09:32 |
| 17 | LUNR | -5.76 | 10:02 | 09:34 |
| 18 | QCOM | -5.70 | miss | 11:11 |
| 19 | GM | -4.98 | miss | 10:28 |
| 20 | RCAT | -4.74 | miss | 09:38 |

### Radar flags (8)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | LUNR | relative_to_spy | down | +0.05 | -1.35 | -0.59 |
| 10:02 | MSTR | relative_to_spy | up | +0.66 | +2.42 | +3.12 |
| 10:02 | QBTS | relative_to_spy | down | -0.84 | -1.36 | -0.44 |
| 10:02 | Bitcoin treasuries and miners (MSTR, COIN, MARA, CLSK, RIOT, IREN) | group_move | up | -0.25 | +0.95 | +1.88 |
| 10:02 | Crypto and exchanges (MSTR, COIN, MARA, HOOD, CRCL, BULL, RIOT) | group_move | up | +0.59 | +1.61 | +1.78 |
| 10:02 | Quantum computing (QBTS, RGTI, IONQ, QUBT) | group_move | down | -0.45 | -1.01 | -0.31 |
| 10:02 | Space (LUNR, ASTS, RKLB, PL) | group_move | down | -0.15 | -1.04 | -0.64 |
| 10:15 | Neoclouds and AI hosting (NBIS, CIFR, IREN, APLD, WULF, ORCL, CRWV) | group_move | down | +1.48 | +1.53 | +1.88 |

### Movers flags (51)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | HOOD | leaders | up | +0.94 | +2.26 | +3.33 |
| 09:31 | CRCL | leaders | up | +2.43 | +3.38 | +2.81 |
| 09:31 | MSTR | leaders | up | +5.57 | +6.27 | +8.06 |
| 09:31 | CIFR | leaders | up | +0.46 | -1.91 | -0.83 |
| 09:31 | MARA | leaders | up | +4.35 | +3.09 | +5.20 |
| 09:31 | COHR | leaders | up | +0.69 | +0.15 | +1.23 |
| 09:31 | HIMS | leaders | up | -2.00 | -2.88 | -3.08 |
| 09:31 | COIN | leaders | up | +3.87 | +5.79 | +7.43 |
| 09:31 | RIOT | leaders | up | +0.95 | +0.28 | +1.21 |
| 09:31 | CIEN | leaders | up | -2.64 | -2.89 | -3.15 |
| 09:31 | NFLX | laggards | down | +1.90 | +2.69 | +2.43 |
| 09:31 | SONY | laggards | down | -0.04 | +0.24 | +0.78 |
| 09:31 | SMCI | laggards | down | -1.03 | -2.37 | -2.60 |
| 09:31 | SHEL | laggards | down | +0.39 | +0.55 | +0.56 |
| 09:31 | PANW | laggards | down | -2.36 | -2.86 | -2.69 |
| 09:31 | FTNT | laggards | down | -1.19 | -1.84 | -1.46 |
| 09:31 | CPRT | laggards | down | +0.56 | +0.53 | +0.26 |
| 09:31 | S | laggards | down | -1.21 | -2.09 | -2.66 |
| 09:31 | SPOT | laggards | down | -1.10 | -0.35 | +0.06 |
| 09:31 | URI | laggards | down | +0.13 | — | +1.18 |
| 09:32 | BULL | leaders | up | +1.73 | +2.21 | +2.59 |
| 09:32 | GOOGL | leaders | up | -0.24 | -1.73 | -1.74 |
| 09:32 | FLNC | laggards | down | -3.40 | -2.83 | -4.03 |
| 09:32 | ORCL | laggards | down | -1.76 | -1.40 | -1.56 |
| 09:32 | ASTS | laggards | down | -3.96 | -4.22 | -5.21 |
| 09:32 | DDOG | laggards | down | -0.62 | -0.55 | -1.20 |
| 09:32 | ZS | laggards | down | -0.27 | +0.12 | +1.14 |
| 09:33 | AVGO | leaders | up | +0.31 | +0.23 | -0.36 |
| 09:33 | BABA | leaders | up | +1.35 | +1.25 | +1.36 |
| 09:33 | CLSK | leaders | up | -0.85 | -1.82 | +1.27 |
| 09:33 | NET | laggards | down | -2.54 | -3.23 | -2.59 |
| 09:33 | RBLX | laggards | down | +0.81 | +0.11 | +1.17 |
| 09:33 | RKLB | laggards | down | -2.95 | -3.33 | -3.77 |
| 09:34 | AAOI | leaders | up | -2.22 | -1.86 | -0.09 |
| 09:34 | PL | laggards | down | -1.63 | -1.81 | -2.75 |
| 09:34 | LUNR | laggards | down | -3.47 | -3.33 | -4.15 |
| 09:35 | CRDO | leaders | up | -0.54 | -0.22 | -0.74 |
| 09:38 | RCAT | laggards | down | -0.67 | +0.56 | -1.15 |
| 09:39 | IREN | leaders | up | -2.79 | -1.55 | -1.14 |
| 09:39 | OKLO | laggards | down | -2.09 | -1.06 | -1.83 |
| 09:40 | IONQ | laggards | down | -2.39 | -2.58 | -3.24 |
| 09:41 | QBTS | laggards | down | -2.29 | -2.45 | -3.05 |
| 09:56 | SNDK | leaders | up | +1.21 | +2.07 | +2.71 |
| 10:02 | RGTI | laggards | down | -0.65 | -1.26 | -0.56 |
| 10:22 | STX | leaders | up | +0.71 | +0.24 | +0.80 |
| 10:28 | GM | laggards | down | -0.38 | -1.39 | -1.42 |
| 11:11 | QCOM | laggards | down | +0.08 | -1.09 | -0.64 |
| 15:07 | AN | laggards | down | +0.76 | — | — |
| 15:12 | F | laggards | down | +0.32 | — | — |
| 15:45 | LCID | laggards | down | — | — | — |
| 15:56 | APP | laggards | down | — | — | — |

## 2026-09-21

Usable symbol-minutes 64,694/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | ARM | +15.61 | miss | 09:31 |
| 2 | LUNR | +11.38 | miss | 09:32 |
| 3 | ALAB | +10.81 | miss | 09:42 |
| 4 | INTC | +10.59 | miss | 09:31 |
| 5 | META | +9.79 | miss | 09:35 |
| 6 | NVO | -9.51 | miss | 09:31 |
| 7 | WBD | +9.24 | miss | 09:31 |
| 8 | AMD | +8.40 | miss | 09:31 |
| 9 | MSTR | +7.92 | miss | 09:31 |
| 10 | QCOM | +7.74 | miss | 11:11 |
| 11 | NET | +7.12 | miss | 11:02 |
| 12 | RKLB | +6.69 | miss | 09:33 |
| 13 | HPQ | -5.77 | miss | 09:37 |
| 14 | APP | +5.63 | miss | 14:36 |
| 15 | RBLX | +5.62 | miss | 09:31 |
| 16 | DDOG | +5.03 | miss | miss |
| 17 | CRDO | +4.92 | miss | 09:59 |
| 18 | COP | -4.81 | miss | 09:31 |
| 19 | XOM | -4.75 | miss | 09:31 |
| 20 | MDB | +4.64 | 10:02 | 10:04 |

### Radar flags (5)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | MDB | relative_to_spy | up | -0.63 | -1.76 | -1.39 |
| 10:02 | SNAP | relative_to_spy | up | -0.04 | -1.35 | -1.11 |
| 10:02 | Cybersecurity (CRWD, NET, S, ZS, FTNT, PANW) | group_move | up | -0.02 | +0.29 | +0.48 |
| 10:02 | Memory and storage (STX, WDC, SNDK, MU) | group_move | down | -0.27 | +0.39 | -0.76 |
| 10:07 | Social and ads (APP, SNAP, RDDT, META, PINS, GOOGL) | group_move | up | -0.24 | -0.80 | +0.28 |

### Movers flags (56)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | INTC | leaders | up | -0.15 | +1.52 | +3.61 |
| 09:31 | ARM | leaders | up | +3.39 | +3.33 | +5.16 |
| 09:31 | CRCL | leaders | up | -4.30 | -4.31 | -5.63 |
| 09:31 | MSTR | leaders | up | +0.43 | -0.62 | -0.47 |
| 09:31 | WBD | leaders | up | +2.46 | +2.41 | +2.16 |
| 09:31 | RBLX | leaders | up | -1.43 | -0.16 | -0.28 |
| 09:31 | COIN | leaders | up | -0.72 | -0.60 | -1.09 |
| 09:31 | STX | leaders | up | -3.82 | -4.04 | -4.05 |
| 09:31 | CIEN | leaders | up | -0.67 | -0.29 | -0.91 |
| 09:31 | AMD | leaders | up | +3.84 | +3.97 | +4.16 |
| 09:31 | NVO | laggards | down | -1.61 | -2.83 | -2.91 |
| 09:31 | CRWD | laggards | down | +5.41 | +5.17 | +5.13 |
| 09:31 | OXY | laggards | down | -1.13 | -1.32 | -1.88 |
| 09:31 | ZS | laggards | down | +5.04 | +5.27 | +4.55 |
| 09:31 | FTNT | laggards | down | +2.88 | +2.69 | +3.21 |
| 09:31 | XOM | laggards | down | -1.27 | -1.62 | -2.08 |
| 09:31 | PANW | laggards | down | +2.98 | +3.07 | +2.85 |
| 09:31 | DDOG | laggards | down | +3.97 | +4.30 | +4.82 |
| 09:31 | COP | laggards | down | -1.53 | -2.20 | -2.59 |
| 09:31 | HUM | laggards | down | -0.64 | -0.27 | — |
| 09:32 | LUNR | leaders | up | +2.01 | +1.87 | +3.93 |
| 09:32 | SMCI | leaders | up | +0.11 | +0.15 | -0.82 |
| 09:32 | HOOD | leaders | up | -2.78 | -1.98 | -2.24 |
| 09:32 | LLY | laggards | down | +2.21 | +2.21 | +2.05 |
| 09:32 | FLNC | laggards | down | +0.16 | +1.26 | +0.34 |
| 09:32 | AMGN | laggards | down | +2.27 | +2.06 | +2.10 |
| 09:32 | AVGO | laggards | down | +0.57 | +0.45 | +0.63 |
| 09:32 | MRK | laggards | down | +1.99 | +1.23 | +1.49 |
| 09:32 | LOW | laggards | down | -1.32 | -0.67 | -0.08 |
| 09:33 | RKLB | leaders | up | +0.60 | +0.63 | +1.29 |
| 09:33 | OKLO | leaders | up | -0.19 | +0.24 | -0.72 |
| 09:33 | CPRT | laggards | down | -1.16 | -1.48 | -0.78 |
| 09:34 | ASTS | leaders | up | -0.05 | +0.13 | -0.29 |
| 09:34 | ORCL | laggards | down | +0.73 | +0.75 | +1.34 |
| 09:34 | CVX | laggards | down | -1.06 | -1.41 | -1.65 |
| 09:35 | META | leaders | up | +2.08 | +1.52 | +1.65 |
| 09:35 | SPOT | laggards | down | +1.05 | +0.78 | +1.40 |
| 09:35 | CVS | laggards | down | -0.80 | -0.87 | -0.69 |
| 09:36 | APLD | laggards | down | +0.00 | +0.53 | +1.50 |
| 09:36 | DASH | laggards | down | +0.59 | +0.87 | +0.59 |
| 09:37 | HPQ | laggards | down | -1.64 | -1.74 | -2.35 |
| 09:42 | ALAB | leaders | up | +0.83 | -0.02 | +1.28 |
| 09:42 | AN | laggards | down | -0.46 | -0.41 | +1.37 |
| 09:45 | ADBE | laggards | down | +0.69 | +0.42 | +0.24 |
| 09:53 | PCAR | laggards | down | -0.30 | -0.49 | -0.63 |
| 09:59 | CRDO | leaders | up | +0.14 | -0.84 | -1.01 |
| 10:02 | UAA | laggards | down | -0.21 | -2.40 | -1.96 |
| 10:04 | MDB | leaders | up | -1.15 | -2.09 | -2.00 |
| 10:05 | SNAP | leaders | up | -0.10 | -1.51 | -1.37 |
| 10:52 | ONON | laggards | down | +0.66 | +1.38 | +2.00 |
| 11:02 | NET | leaders | up | +0.35 | +0.45 | +0.43 |
| 11:11 | QCOM | leaders | up | +1.06 | +0.61 | +1.48 |
| 11:28 | SNDK | laggards | down | -0.52 | -0.14 | -2.11 |
| 11:38 | SHEL | laggards | down | -0.30 | -0.47 | -0.33 |
| 11:55 | ELV | laggards | down | +0.06 | +0.15 | -0.10 |
| 14:36 | APP | leaders | up | +0.41 | +1.29 | — |

## 2026-09-22

Usable symbol-minutes 64,656/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | ONON | +7.59 | miss | 09:31 |
| 2 | SNDK | +6.83 | 10:02 | 09:33 |
| 3 | ALAB | +6.68 | miss | 09:36 |
| 4 | SCHW | -6.09 | miss | 09:31 |
| 5 | MDB | +5.02 | miss | 11:50 |
| 6 | MU | +5.02 | miss | 10:02 |
| 7 | PINS | -4.99 | miss | 11:48 |
| 8 | STX | +4.86 | 10:02 | 09:46 |
| 9 | DELL | -4.57 | miss | 09:32 |
| 10 | ADBE | -4.50 | miss | 10:06 |
| 11 | AMGN | +4.36 | miss | 09:31 |
| 12 | FND | +3.91 | miss | 09:31 |
| 13 | WFC | -3.90 | miss | 09:52 |
| 14 | HIMS | +3.70 | miss | 10:10 |
| 15 | WDC | +3.68 | 10:02 | 09:48 |
| 16 | COHR | -3.45 | miss | 09:31 |
| 17 | JPM | -3.40 | miss | 09:51 |
| 18 | LUNR | +3.32 | miss | miss |
| 19 | ARM | +3.21 | miss | 11:11 |
| 20 | RIOT | +3.12 | miss | 09:52 |

### Radar flags (5)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | SNDK | relative_to_spy | up | -0.71 | -1.77 | -0.85 |
| 10:02 | STX | relative_to_spy | up | -1.51 | -2.81 | -3.52 |
| 10:02 | WDC | relative_to_spy | up | -1.44 | -2.40 | -3.27 |
| 10:02 | Memory and storage (STX, WDC, SNDK, MU) | group_move | up | -0.67 | -1.71 | -1.75 |
| 10:14 | Bitcoin treasuries and miners (MARA, RIOT, CLSK, IREN, MSTR, COIN) | group_move | up | -0.96 | -1.37 | -1.58 |

### Movers flags (82)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | ONON | leaders | up | +3.31 | +3.76 | +1.91 |
| 09:31 | SOFI | leaders | up | -4.13 | -4.38 | -3.45 |
| 09:31 | FND | leaders | up | -1.37 | -0.28 | -1.27 |
| 09:31 | DECK | leaders | up | -2.00 | -2.29 | -3.31 |
| 09:31 | BABA | leaders | up | -0.44 | -1.44 | -2.29 |
| 09:31 | AMGN | leaders | up | -0.39 | -1.11 | +1.98 |
| 09:31 | NOW | leaders | up | -3.62 | -3.92 | -3.61 |
| 09:31 | DASH | leaders | up | +0.17 | -1.16 | -0.90 |
| 09:31 | UAA | leaders | up | -0.66 | -0.83 | -1.70 |
| 09:31 | LOW | leaders | up | -0.89 | -0.48 | -0.52 |
| 09:31 | COHR | laggards | down | +4.14 | +1.48 | -0.78 |
| 09:31 | AAOI | laggards | down | +3.48 | +1.08 | -1.85 |
| 09:31 | CMI | laggards | down | +0.58 | +0.06 | -0.37 |
| 09:31 | LLY | laggards | down | +0.87 | +1.63 | +3.27 |
| 09:31 | WDC | laggards | down | +7.12 | +5.26 | +2.21 |
| 09:31 | AMZN | laggards | down | +1.31 | +1.09 | +0.53 |
| 09:31 | CRDO | laggards | down | +1.88 | +4.63 | +2.15 |
| 09:31 | CAT | laggards | down | +0.86 | +0.73 | +0.22 |
| 09:31 | COP | laggards | down | +0.22 | +0.17 | +0.87 |
| 09:31 | SCHW | laggards | down | -2.03 | -4.62 | -5.04 |
| 09:32 | RKLB | leaders | up | -0.20 | -1.06 | -0.61 |
| 09:32 | NKE | leaders | up | -0.23 | -0.34 | -1.21 |
| 09:32 | DELL | laggards | down | +0.76 | -0.81 | -1.74 |
| 09:32 | CLSK | laggards | down | +3.11 | +4.24 | +3.57 |
| 09:32 | OXY | laggards | down | +0.57 | +0.96 | +1.54 |
| 09:33 | SNDK | leaders | up | +5.01 | +4.44 | +2.96 |
| 09:33 | AN | leaders | up | -0.75 | -1.83 | — |
| 09:33 | HSAI | laggards | down | — | +0.18 | -0.13 |
| 09:33 | FLNC | laggards | down | -1.16 | -1.52 | -0.46 |
| 09:34 | CRCL | leaders | up | -2.10 | -3.17 | -2.59 |
| 09:34 | CVX | laggards | down | +1.06 | +1.21 | +1.42 |
| 09:34 | OKLO | laggards | down | -0.18 | -0.73 | +3.39 |
| 09:34 | ASTS | laggards | down | +1.30 | +0.70 | +1.41 |
| 09:35 | FTNT | laggards | down | -0.33 | -0.41 | -0.13 |
| 09:35 | LUNR | laggards | down | +0.90 | -0.47 | +1.36 |
| 09:36 | ALAB | leaders | up | +1.69 | +2.70 | +3.69 |
| 09:36 | TDOC | leaders | up | -1.32 | -2.11 | -2.99 |
| 09:36 | RBLX | laggards | down | -1.71 | -1.53 | -0.44 |
| 09:37 | NBIS | leaders | up | +1.28 | +0.65 | -1.25 |
| 09:38 | ORCL | leaders | up | -1.47 | -1.83 | -1.76 |
| 09:39 | APP | laggards | down | +0.35 | +0.85 | +1.21 |
| 09:40 | NFLX | laggards | down | +0.01 | -0.49 | -0.57 |
| 09:40 | QBTS | laggards | down | -1.05 | -1.07 | -0.97 |
| 09:41 | RGTI | laggards | down | -0.84 | -0.32 | +0.05 |
| 09:42 | COIN | laggards | down | +0.79 | +0.20 | +1.10 |
| 09:44 | APLD | leaders | up | -0.10 | -1.74 | -1.37 |
| 09:46 | STX | leaders | up | +0.03 | +0.72 | -1.67 |
| 09:46 | CRWV | leaders | up | +1.44 | +0.13 | -1.16 |
| 09:47 | TTWO | laggards | down | -0.22 | -0.50 | -0.44 |
| 09:48 | WDC | leaders | up | +1.34 | +0.29 | -2.06 |
| 09:50 | PANW | laggards | down | +1.37 | +1.06 | +0.96 |
| 09:50 | ZS | laggards | down | +1.17 | +1.13 | +1.68 |
| 09:51 | JPM | laggards | down | -0.82 | -1.56 | -1.80 |
| 09:52 | RIOT | leaders | up | +1.11 | +0.12 | -0.57 |
| 09:52 | WFC | laggards | down | -0.63 | -1.79 | -2.08 |
| 09:53 | MS | laggards | down | -1.44 | -1.81 | -1.14 |
| 09:54 | IREN | leaders | up | +0.79 | -0.48 | -0.69 |
| 09:56 | CIFR | leaders | up | -0.06 | -0.23 | -0.72 |
| 10:02 | MU | leaders | up | +0.97 | +0.14 | +0.62 |
| 10:02 | NVO | laggards | down | +0.95 | +1.23 | +0.80 |
| 10:06 | ADBE | laggards | down | -1.00 | -1.61 | -2.06 |
| 10:08 | MARA | leaders | up | +1.09 | -0.50 | +0.40 |
| 10:10 | HIMS | leaders | up | +0.07 | +1.00 | +0.20 |
| 10:15 | C | laggards | down | -0.77 | -1.09 | -0.06 |
| 10:30 | LYFT | laggards | down | +0.89 | +1.13 | +0.68 |
| 10:52 | BAC | laggards | down | -0.47 | +0.10 | +0.04 |
| 11:06 | MRVL | leaders | up | -0.41 | +0.05 | +0.12 |
| 11:11 | ARM | leaders | up | -0.85 | +0.12 | +0.14 |
| 11:12 | CNC | laggards | down | +0.15 | +0.70 | +0.18 |
| 11:14 | MRK | leaders | up | -0.05 | -0.62 | -1.00 |
| 11:19 | PYPL | leaders | up | -2.14 | -2.74 | -2.86 |
| 11:26 | OKLO | leaders | up | -0.51 | -0.43 | -0.92 |
| 11:37 | CLSK | leaders | up | -0.23 | -0.95 | -0.25 |
| 11:42 | HPQ | laggards | down | +0.71 | +0.15 | +0.23 |
| 11:48 | PINS | laggards | down | -0.01 | -0.37 | -1.81 |
| 11:50 | MDB | leaders | up | -0.34 | +1.99 | +3.58 |
| 11:53 | V | laggards | down | +0.36 | +0.90 | +0.80 |
| 11:57 | CRDO | leaders | up | -0.44 | -0.17 | -0.79 |
| 12:30 | LCID | laggards | down | +1.36 | +2.08 | +2.84 |
| 12:35 | ASTS | leaders | up | +0.74 | +0.26 | +1.86 |
| 13:34 | RDDT | laggards | down | -0.44 | -1.23 | -0.63 |
| 13:35 | SPOT | laggards | down | -0.93 | -1.40 | -0.60 |

## 2026-09-23

Usable symbol-minutes 64,534/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | HIMS | -5.98 | miss | 10:07 |
| 2 | PANW | +5.72 | miss | 10:45 |
| 3 | CRWD | +5.69 | miss | 10:46 |
| 4 | LUNR | -5.44 | miss | 09:31 |
| 5 | SNAP | -5.15 | miss | 09:31 |
| 6 | IONQ | +5.14 | miss | 09:31 |
| 7 | ASTS | -5.10 | miss | 09:31 |
| 8 | FLNC | +4.98 | miss | 09:31 |
| 9 | WULF | -4.93 | miss | 15:10 |
| 10 | AAOI | -4.83 | miss | 09:32 |
| 11 | BULL | -4.72 | miss | 10:24 |
| 12 | PLTR | +4.40 | miss | 09:37 |
| 13 | RCAT | -4.32 | miss | 09:36 |
| 14 | BABA | -4.02 | miss | 09:31 |
| 15 | HSAI | -3.90 | miss | 09:31 |
| 16 | APLD | -3.87 | miss | miss |
| 17 | CLSK | -3.77 | miss | miss |
| 18 | UAA | -3.71 | miss | 09:46 |
| 19 | QBTS | -3.55 | miss | miss |
| 20 | NOW | +3.48 | miss | 09:37 |

### Radar flags (3)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | Quantum computing (IONQ, QBTS, RGTI) | group_move | down | -0.29 | +0.12 | -1.18 |
| 10:09 | Quantum computing (IONQ, QUBT, RGTI, QBTS) | group_move | up | -1.07 | +0.49 | -0.63 |
| 10:34 | Space (LUNR, RKLB, ASTS, PL, IRDM) | group_move | down | +0.03 | +0.33 | — |

### Movers flags (68)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | IONQ | leaders | up | -5.05 | -4.55 | -4.42 |
| 09:31 | QBTS | leaders | up | -5.83 | -5.95 | -7.19 |
| 09:31 | QUBT | leaders | up | -2.21 | -2.17 | -1.36 |
| 09:31 | RGTI | leaders | up | -3.32 | -3.92 | -4.06 |
| 09:31 | FLNC | leaders | up | +1.49 | +1.27 | +3.03 |
| 09:31 | CRWV | leaders | up | -0.35 | -1.37 | +0.76 |
| 09:31 | ONON | leaders | up | -0.81 | +0.05 | +2.04 |
| 09:31 | DELL | leaders | up | +1.11 | -0.04 | -0.12 |
| 09:31 | SMCI | leaders | up | +0.80 | -1.44 | -0.87 |
| 09:31 | TSLA | leaders | up | +0.74 | -0.74 | -0.39 |
| 09:31 | APP | laggards | down | -2.12 | -0.96 | -0.17 |
| 09:31 | BABA | laggards | down | -0.34 | -0.39 | -0.23 |
| 09:31 | LUNR | laggards | down | +2.01 | -0.75 | -0.52 |
| 09:31 | BIDU | laggards | down | -0.36 | -0.22 | +0.13 |
| 09:31 | HSAI | laggards | down | -2.14 | -2.39 | -1.15 |
| 09:31 | ASTS | laggards | down | +1.53 | -0.40 | -0.04 |
| 09:31 | PDD | laggards | down | +0.40 | +0.76 | +0.76 |
| 09:31 | STX | laggards | down | +0.42 | +1.24 | +1.51 |
| 09:31 | SNAP | laggards | down | -1.79 | -3.07 | -3.50 |
| 09:31 | PL | laggards | down | +0.85 | -0.06 | +0.68 |
| 09:32 | IBM | leaders | up | +0.67 | +1.00 | +1.29 |
| 09:32 | CIEN | laggards | down | -0.48 | +0.00 | +1.54 |
| 09:32 | LCID | laggards | down | -1.04 | -1.53 | -1.33 |
| 09:32 | AAOI | laggards | down | -0.40 | -1.19 | +0.30 |
| 09:32 | WDC | laggards | down | +1.42 | +1.89 | +3.06 |
| 09:32 | ORCL | laggards | down | +1.12 | +0.40 | +1.34 |
| 09:33 | HPQ | leaders | up | -0.54 | -1.88 | -0.42 |
| 09:33 | NKE | leaders | up | -1.42 | -0.73 | -0.49 |
| 09:33 | HIMS | leaders | up | -3.25 | -3.27 | -3.87 |
| 09:34 | META | leaders | up | +1.26 | +0.61 | +1.66 |
| 09:34 | MA | leaders | up | +0.05 | +0.56 | -0.04 |
| 09:35 | LLY | leaders | up | -1.74 | -0.91 | -1.72 |
| 09:35 | CVNA | laggards | down | -0.65 | -0.52 | -0.52 |
| 09:36 | CVX | leaders | up | +0.98 | +1.30 | +1.37 |
| 09:36 | WMT | leaders | up | -0.36 | -0.18 | -0.81 |
| 09:36 | RCAT | laggards | down | +1.44 | +1.06 | +1.99 |
| 09:36 | OKLO | laggards | down | +1.80 | +1.34 | +1.24 |
| 09:37 | NOW | leaders | up | -0.59 | -1.03 | +0.76 |
| 09:37 | SNOW | leaders | up | -0.62 | -1.70 | -0.06 |
| 09:37 | PLTR | leaders | up | +1.06 | +1.20 | +2.51 |
| 09:37 | MSFT | leaders | up | -0.70 | -1.15 | -0.73 |
| 09:38 | CRCL | leaders | up | -2.38 | -3.36 | -3.08 |
| 09:39 | CRM | leaders | up | +0.11 | +0.04 | +0.96 |
| 09:40 | DDOG | leaders | up | +0.17 | +0.66 | +1.42 |
| 09:44 | MDB | leaders | up | -0.87 | -0.71 | +0.56 |
| 09:46 | DE | leaders | up | +1.11 | +0.42 | +0.36 |
| 09:46 | UAA | laggards | down | +0.53 | +0.08 | +0.52 |
| 09:47 | HOOD | leaders | up | -1.37 | -1.39 | +0.04 |
| 09:48 | NET | leaders | up | -1.29 | -1.59 | -0.17 |
| 09:49 | KMX | laggards | down | +0.56 | +0.77 | +3.10 |
| 09:50 | COHR | laggards | down | -0.28 | +0.76 | +1.03 |
| 09:51 | ZS | leaders | up | -1.95 | -0.13 | -0.26 |
| 09:52 | RDDT | laggards | down | -1.17 | -1.64 | -0.33 |
| 10:07 | COP | leaders | up | +0.69 | +0.51 | +1.02 |
| 10:07 | DASH | laggards | down | +0.12 | +0.35 | +0.99 |
| 10:07 | HIMS | laggards | down | +1.37 | +0.79 | +0.68 |
| 10:08 | OXY | leaders | up | +0.76 | +0.41 | +1.28 |
| 10:13 | XOM | leaders | up | +0.36 | -0.26 | -0.05 |
| 10:24 | BULL | laggards | down | +0.10 | -0.14 | +0.57 |
| 10:45 | PANW | leaders | up | +0.59 | +1.07 | +1.04 |
| 10:46 | CRWD | leaders | up | +1.22 | +2.48 | +2.79 |
| 11:02 | CIFR | leaders | up | -0.91 | -2.99 | -3.43 |
| 11:32 | GOOGL | laggards | down | +0.04 | -0.56 | -0.51 |
| 11:41 | SNDK | laggards | down | +0.03 | -0.32 | -0.31 |
| 12:25 | KMX | leaders | up | +0.03 | -0.44 | +0.41 |
| 15:00 | FTNT | leaders | up | +0.07 | +0.37 | — |
| 15:10 | WULF | laggards | down | -0.65 | — | — |
| 15:17 | U | leaders | up | -0.15 | — | — |

## 2026-09-24

Usable symbol-minutes 64,629/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | ARM | -7.80 | miss | 09:31 |
| 2 | PL | +7.65 | miss | 10:41 |
| 3 | NBIS | +7.53 | miss | 09:31 |
| 4 | U | -6.00 | 14:47 | 09:37 |
| 5 | IONQ | +5.82 | miss | 09:41 |
| 6 | BULL | -5.02 | miss | 09:42 |
| 7 | WDC | -4.85 | miss | 09:31 |
| 8 | RIOT | -4.82 | miss | 09:31 |
| 9 | RKLB | +4.78 | miss | 10:07 |
| 10 | META | +4.58 | miss | 09:31 |
| 11 | QBTS | +4.07 | miss | 12:19 |
| 12 | INTC | +3.99 | miss | 09:46 |
| 13 | CRWV | +3.80 | miss | 09:32 |
| 14 | GM | -3.74 | miss | 09:40 |
| 15 | ORCL | -3.39 | miss | 09:31 |
| 16 | SNDK | -3.38 | miss | 09:32 |
| 17 | RCAT | +3.27 | miss | 13:20 |
| 18 | COHR | -3.24 | miss | 09:32 |
| 19 | HIMS | +3.22 | miss | 14:26 |
| 20 | RGTI | +3.17 | miss | 12:29 |

### Radar flags (9)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:12 | Neoclouds and AI hosting (ORCL, APLD, IREN, CRWV, CIFR, WULF, NBIS) | group_move | down | +1.59 | +0.06 | +0.17 |
| 11:05 | Bitcoin treasuries and miners (CLSK, MSTR, COIN, MARA, RIOT, IREN) | group_move | down | -0.22 | -0.14 | +0.37 |
| 11:05 | Crypto and exchanges (MSTR, COIN, MARA, CRCL, RIOT, HOOD, BULL) | group_move | down | -0.02 | -0.18 | +0.18 |
| 12:30 | Space (LUNR, PL, ASTS, RKLB) | group_move | up | +0.43 | +1.36 | +0.63 |
| 12:31 | Quantum computing (IONQ, QBTS, QUBT, RGTI) | group_move | up | -0.18 | -0.15 | +1.10 |
| 12:43 | Oil majors (OXY, COP, XOM, CVX, SHEL) | group_move | down | +0.70 | +0.88 | +0.45 |
| 14:42 | Gaming platforms (U, RBLX, TTWO, APP) | group_move | down | -1.12 | +0.86 | — |
| 14:47 | U | relative_to_spy | down | -3.12 | +2.50 | — |
| 15:34 | U | relative_to_spy | up | — | — | — |

### Movers flags (88)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | CRCL | leaders | up | -2.23 | -0.36 | -1.85 |
| 09:31 | META | leaders | up | +0.01 | +0.82 | +1.09 |
| 09:31 | NBIS | leaders | up | +3.31 | +5.72 | +4.03 |
| 09:31 | TGT | leaders | up | +0.12 | -0.69 | -0.74 |
| 09:31 | CRM | leaders | up | -1.41 | -0.50 | +0.27 |
| 09:31 | OXY | leaders | up | +0.27 | +0.53 | +0.92 |
| 09:31 | XOM | leaders | up | +0.23 | +0.60 | +0.85 |
| 09:31 | TTWO | leaders | up | -1.67 | -0.97 | -1.02 |
| 09:31 | RBLX | leaders | up | -0.37 | +0.11 | -1.19 |
| 09:31 | ADBE | leaders | up | -1.75 | -1.57 | -1.64 |
| 09:31 | ORCL | laggards | down | -2.70 | -0.99 | -0.27 |
| 09:31 | ARM | laggards | down | +0.57 | +0.76 | -2.89 |
| 09:31 | IREN | laggards | down | +0.59 | +1.49 | -0.55 |
| 09:31 | ALAB | laggards | down | +1.54 | +1.53 | +2.39 |
| 09:31 | AAOI | laggards | down | +3.19 | +1.97 | +1.27 |
| 09:31 | FLNC | laggards | down | -0.75 | -0.17 | -1.31 |
| 09:31 | WDC | laggards | down | -0.43 | -0.26 | -1.02 |
| 09:31 | CIFR | laggards | down | +1.56 | +4.06 | +0.44 |
| 09:31 | MRVL | laggards | down | +0.94 | +0.58 | +0.29 |
| 09:31 | RIOT | laggards | down | +0.94 | +2.09 | -0.39 |
| 09:32 | CRWV | leaders | up | -2.28 | -1.91 | -3.41 |
| 09:32 | DIS | leaders | up | -0.29 | -0.41 | -0.45 |
| 09:32 | COIN | leaders | up | -3.23 | -1.57 | -2.74 |
| 09:32 | TDOC | leaders | up | -1.77 | -0.67 | -1.99 |
| 09:32 | DASH | leaders | up | -3.04 | -2.99 | -3.49 |
| 09:32 | ONON | leaders | up | -1.24 | -1.93 | -2.24 |
| 09:32 | SNDK | laggards | down | +0.28 | +1.36 | -0.33 |
| 09:32 | CRDO | laggards | down | +2.08 | +0.95 | +1.38 |
| 09:32 | COHR | laggards | down | +1.19 | +0.22 | +0.35 |
| 09:33 | LLY | leaders | up | +1.45 | +1.47 | +1.83 |
| 09:33 | MSTR | leaders | up | -2.05 | -0.16 | -1.92 |
| 09:33 | MU | laggards | down | +0.07 | +1.00 | +0.91 |
| 09:34 | DELL | laggards | down | +0.63 | -0.24 | -0.58 |
| 09:36 | KMX | leaders | up | -2.70 | -2.99 | — |
| 09:36 | PFE | leaders | up | +0.36 | +0.50 | +0.17 |
| 09:36 | HIMS | laggards | down | +0.63 | +2.28 | +2.46 |
| 09:37 | U | laggards | down | -0.17 | +1.17 | +1.30 |
| 09:37 | CAT | laggards | down | +0.62 | +0.40 | -0.06 |
| 09:38 | MRK | leaders | up | -0.06 | -0.37 | -1.03 |
| 09:39 | CVNA | laggards | down | +1.51 | +2.27 | +1.63 |
| 09:39 | BIDU | laggards | down | -1.12 | -1.30 | -0.82 |
| 09:39 | RCAT | laggards | down | +0.26 | +0.13 | +0.44 |
| 09:40 | WULF | leaders | up | -2.78 | -1.73 | -4.55 |
| 09:40 | CIFR | leaders | up | -3.25 | -1.64 | -4.51 |
| 09:40 | APLD | leaders | up | -2.98 | -2.44 | -5.01 |
| 09:40 | GM | laggards | down | +0.50 | +0.24 | -0.04 |
| 09:41 | IONQ | leaders | up | -2.98 | -0.83 | -1.40 |
| 09:42 | BULL | laggards | down | -2.21 | -2.45 | -2.59 |
| 09:43 | IBM | laggards | down | -0.57 | -0.17 | -0.04 |
| 09:44 | COP | leaders | up | +0.06 | +0.38 | +0.98 |
| 09:45 | AAOI | leaders | up | -2.23 | -3.05 | -2.71 |
| 09:46 | INTC | leaders | up | -0.44 | -0.75 | -1.64 |
| 09:46 | URI | laggards | down | +0.47 | +0.33 | +0.92 |
| 09:48 | HOOD | laggards | down | +1.47 | +1.73 | +0.85 |
| 09:48 | OKLO | laggards | down | +0.12 | -0.23 | -0.29 |
| 09:51 | ASTS | laggards | down | +1.88 | +3.04 | +2.86 |
| 09:54 | SHEL | leaders | up | -0.01 | +0.02 | +0.08 |
| 09:55 | NVO | leaders | up | -0.20 | -0.29 | -0.88 |
| 10:02 | LCID | laggards | down | +0.38 | +0.68 | +2.16 |
| 10:02 | QCOM | laggards | down | +0.94 | +0.79 | +0.69 |
| 10:04 | V | leaders | up | -0.17 | -0.26 | -0.06 |
| 10:07 | RKLB | leaders | up | +0.33 | +0.94 | +0.79 |
| 10:09 | SMCI | laggards | down | -0.71 | -0.70 | -0.57 |
| 10:11 | RIVN | leaders | up | -0.32 | -1.14 | -1.57 |
| 10:24 | NET | leaders | up | +0.56 | +0.59 | +1.03 |
| 10:27 | LULU | laggards | down | +0.13 | +0.38 | +1.22 |
| 10:31 | PINS | leaders | up | -0.80 | -0.86 | -1.22 |
| 10:41 | PL | leaders | up | +0.46 | +0.86 | +4.55 |
| 11:23 | MARA | laggards | down | +0.29 | +0.79 | -0.10 |
| 11:26 | DDOG | leaders | up | -0.13 | -0.37 | -0.18 |
| 11:35 | APLD | laggards | down | +0.55 | +1.61 | +3.65 |
| 11:36 | CLSK | laggards | down | +0.98 | +1.05 | +1.35 |
| 11:57 | KMX | laggards | down | -0.56 | -0.52 | +0.35 |
| 12:00 | DASH | laggards | down | +0.75 | +1.56 | +1.03 |
| 12:14 | FND | laggards | down | +1.45 | +0.90 | +1.12 |
| 12:17 | LUNR | leaders | up | +0.73 | +2.28 | +2.16 |
| 12:18 | ASTS | leaders | up | +1.66 | +2.60 | +2.42 |
| 12:19 | QBTS | leaders | up | +0.97 | +0.65 | +2.04 |
| 12:21 | CPRT | laggards | down | -0.22 | -0.37 | -0.04 |
| 12:22 | MDB | laggards | down | +0.19 | -0.03 | +0.10 |
| 12:29 | RGTI | leaders | up | -0.38 | -0.66 | +0.00 |
| 13:06 | HPQ | laggards | down | -0.17 | +0.13 | +0.99 |
| 13:20 | RCAT | leaders | up | -0.13 | -0.70 | -0.61 |
| 14:24 | RBLX | laggards | down | -0.42 | +1.72 | — |
| 14:26 | HIMS | leaders | up | -0.76 | -0.61 | — |
| 15:16 | STX | laggards | down | +0.20 | — | — |
| 15:20 | DE | laggards | down | +0.32 | — | — |
| 15:47 | F | laggards | down | — | — | — |

## 2026-09-25

Usable symbol-minutes 64,679/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | ZS | -10.60 | miss | 09:31 |
| 2 | S | -7.22 | miss | 09:31 |
| 3 | CRDO | +7.11 | miss | 09:31 |
| 4 | RBLX | -5.44 | miss | 09:32 |
| 5 | IREN | -4.93 | miss | 09:31 |
| 6 | CRCL | -4.84 | miss | 09:31 |
| 7 | FLNC | +4.68 | miss | 09:31 |
| 8 | DELL | +4.47 | miss | 09:31 |
| 9 | PANW | -4.44 | miss | 09:32 |
| 10 | CVS | +4.25 | miss | 11:45 |
| 11 | PYPL | +4.10 | miss | 10:17 |
| 12 | HUM | +4.09 | miss | 09:32 |
| 13 | INTC | -3.99 | miss | 09:32 |
| 14 | WULF | -3.92 | miss | 09:43 |
| 15 | META | -3.88 | miss | 09:31 |
| 16 | DDOG | +3.82 | miss | 09:31 |
| 17 | SMCI | +3.67 | miss | 09:33 |
| 18 | APLD | -3.54 | miss | 13:41 |
| 19 | FTNT | -3.46 | miss | 09:35 |
| 20 | CRWD | -3.45 | miss | 09:38 |

### Radar flags (3)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:07 | Bitcoin treasuries and miners (MARA, IREN, CLSK, RIOT, COIN, MSTR) | group_move | down | +0.16 | +0.43 | +0.75 |
| 10:10 | Neoclouds and AI hosting (CIFR, IREN, WULF, APLD, CRWV, NBIS, ORCL) | group_move | down | -0.28 | -0.48 | +0.72 |
| 11:21 | Quantum computing (IONQ, RGTI, QUBT, QBTS) | group_move | up | -1.18 | -0.24 | -0.93 |

### Movers flags (59)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | ARM | leaders | up | -0.26 | -1.13 | -0.65 |
| 09:31 | DDOG | leaders | up | +3.19 | +2.66 | +1.67 |
| 09:31 | CRDO | leaders | up | -1.31 | -0.50 | +0.92 |
| 09:31 | CIFR | leaders | up | -3.51 | -5.27 | -3.97 |
| 09:31 | FLNC | leaders | up | +1.69 | +3.63 | +1.43 |
| 09:31 | SONY | leaders | up | -0.08 | -0.01 | -0.17 |
| 09:31 | RIVN | leaders | up | -1.49 | -1.22 | -1.88 |
| 09:31 | SNDK | leaders | up | -1.24 | -1.97 | -0.91 |
| 09:31 | TSLA | leaders | up | -3.45 | -3.59 | -3.77 |
| 09:31 | DELL | leaders | up | +2.17 | +2.24 | +3.37 |
| 09:31 | ZS | laggards | down | -3.75 | -5.04 | -5.76 |
| 09:31 | U | laggards | down | +2.70 | +2.07 | +1.59 |
| 09:31 | IREN | laggards | down | -3.17 | -3.62 | -2.55 |
| 09:31 | META | laggards | down | -1.14 | -1.51 | -1.79 |
| 09:31 | NKE | laggards | down | +0.70 | +1.37 | +1.03 |
| 09:31 | OXY | laggards | down | -0.07 | -0.15 | +0.01 |
| 09:31 | COP | laggards | down | +0.54 | +0.53 | +0.46 |
| 09:31 | CRCL | laggards | down | -2.53 | -3.32 | -3.91 |
| 09:31 | S | laggards | down | -1.75 | -1.62 | -2.70 |
| 09:31 | MDB | laggards | down | +2.88 | +0.67 | +0.15 |
| 09:32 | HUM | leaders | up | -0.33 | +0.33 | +4.42 |
| 09:32 | ANET | leaders | up | -0.64 | -1.64 | -1.61 |
| 09:32 | LCID | leaders | up | -0.98 | -1.07 | -2.05 |
| 09:32 | MRVL | leaders | up | -0.78 | -1.34 | -0.08 |
| 09:32 | CLSK | laggards | down | -1.61 | -3.36 | -1.77 |
| 09:32 | INTC | laggards | down | +0.08 | +0.07 | -1.00 |
| 09:32 | PANW | laggards | down | -0.65 | -1.09 | -0.84 |
| 09:32 | RBLX | laggards | down | -1.12 | -1.48 | -2.03 |
| 09:32 | MARA | laggards | down | -2.68 | -3.72 | -2.57 |
| 09:33 | SMCI | leaders | up | +2.17 | +1.59 | +1.71 |
| 09:33 | TDOC | laggards | down | -0.29 | -0.61 | +0.81 |
| 09:34 | SNOW | leaders | up | +0.21 | +0.16 | -0.53 |
| 09:34 | OKLO | leaders | up | -2.74 | -3.15 | -2.02 |
| 09:35 | ALAB | leaders | up | -2.31 | -1.56 | -1.01 |
| 09:35 | MU | leaders | up | -1.21 | -1.92 | -2.48 |
| 09:35 | MSFT | leaders | up | +0.78 | +1.26 | +1.09 |
| 09:35 | FTNT | laggards | down | -0.51 | -0.53 | +0.10 |
| 09:38 | CRWD | laggards | down | -0.18 | +0.41 | +1.03 |
| 09:39 | QCOM | leaders | up | +0.80 | +0.93 | +2.22 |
| 09:41 | HIMS | laggards | down | +0.19 | +0.61 | +2.75 |
| 09:42 | TSLA | laggards | down | +1.02 | +0.05 | +0.38 |
| 09:43 | WULF | laggards | down | -0.94 | -1.32 | -2.00 |
| 09:49 | RIOT | laggards | down | -1.53 | -0.59 | -0.60 |
| 09:50 | COIN | laggards | down | +0.07 | -0.05 | -0.47 |
| 09:52 | COST | leaders | up | +0.15 | -0.30 | +0.14 |
| 09:55 | LUNR | leaders | up | -1.03 | -2.49 | -1.65 |
| 09:56 | NET | laggards | down | -0.46 | -0.81 | -0.80 |
| 10:00 | PL | leaders | up | -2.83 | -3.45 | -2.34 |
| 10:17 | PYPL | leaders | up | +1.96 | +1.12 | +1.89 |
| 10:32 | CIFR | laggards | down | +1.23 | +1.77 | +1.53 |
| 10:33 | CRWV | laggards | down | -0.12 | +0.18 | +0.29 |
| 11:21 | RGTI | leaders | up | -1.10 | -0.39 | -1.32 |
| 11:32 | AI | laggards | down | -0.15 | +0.90 | +1.27 |
| 11:45 | CVS | leaders | up | -0.01 | -0.13 | -0.01 |
| 12:57 | COHR | leaders | up | -0.65 | -0.56 | -0.72 |
| 13:00 | AAOI | leaders | up | -2.35 | -2.60 | -2.13 |
| 13:41 | APLD | laggards | down | +0.11 | -0.43 | -0.48 |
| 14:03 | AN | leaders | up | +0.10 | -0.04 | — |
| 14:12 | GM | leaders | up | -0.00 | -0.81 | — |

## 2026-09-28

Usable symbol-minutes 64,625/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | MDB | -17.71 | miss | 09:31 |
| 2 | RBLX | -9.12 | miss | 09:31 |
| 3 | ARM | -7.95 | 10:02 | 09:31 |
| 4 | CRDO | -7.93 | miss | 09:31 |
| 5 | DASH | -7.00 | miss | 09:36 |
| 6 | QCOM | -6.43 | miss | 09:36 |
| 7 | CVNA | -6.31 | miss | 09:31 |
| 8 | APLD | -5.81 | miss | 11:17 |
| 9 | PANW | +5.37 | miss | 09:37 |
| 10 | RIOT | -5.26 | miss | 15:38 |
| 11 | INTC | -4.92 | miss | 09:41 |
| 12 | CIFR | -4.84 | miss | 11:07 |
| 13 | IREN | -4.71 | miss | 15:17 |
| 14 | META | -4.05 | miss | 09:39 |
| 15 | ZS | +4.03 | 10:02 | 09:38 |
| 16 | COHR | -3.78 | miss | 10:01 |
| 17 | AAOI | -3.77 | miss | 09:59 |
| 18 | RDDT | -3.77 | miss | miss |
| 19 | FLNC | -3.71 | miss | 09:31 |
| 20 | RIVN | -3.65 | miss | miss |

### Radar flags (4)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | ARM | relative_to_spy | down | -0.95 | -0.77 | -0.47 |
| 10:02 | MDB | relative_to_spy | up | +0.30 | +0.93 | +2.41 |
| 10:02 | ZS | relative_to_spy | up | -1.36 | -0.47 | +1.20 |
| 10:02 | Cybersecurity (ZS, PANW, NET, S, FTNT, CRWD) | group_move | up | -0.60 | +0.17 | +1.86 |

### Movers flags (61)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | APP | leaders | up | -2.34 | -2.73 | -2.37 |
| 09:31 | NVDA | leaders | up | +0.54 | +0.23 | +0.07 |
| 09:31 | IONQ | leaders | up | +2.45 | +1.26 | -0.50 |
| 09:31 | SHEL | leaders | up | -0.14 | +0.03 | +0.46 |
| 09:31 | XOM | leaders | up | +0.24 | +0.14 | +0.53 |
| 09:31 | CVX | leaders | up | -0.01 | +0.29 | +0.77 |
| 09:31 | OXY | leaders | up | -0.84 | -0.89 | -0.59 |
| 09:31 | COIN | leaders | up | -0.54 | -1.79 | -2.35 |
| 09:31 | COP | leaders | up | -0.47 | -0.74 | -0.45 |
| 09:31 | JD | leaders | up | -0.51 | +0.22 | +0.28 |
| 09:31 | MDB | laggards | down | +6.33 | +7.71 | +11.79 |
| 09:31 | NOW | laggards | down | +1.10 | +1.23 | +1.76 |
| 09:31 | SNOW | laggards | down | +1.69 | +1.93 | +3.81 |
| 09:31 | RBLX | laggards | down | -3.49 | -3.63 | -1.79 |
| 09:31 | CRM | laggards | down | +0.29 | +1.60 | +2.02 |
| 09:31 | FLNC | laggards | down | -1.33 | +1.29 | -0.39 |
| 09:31 | SNAP | laggards | down | +0.01 | +1.21 | +1.19 |
| 09:31 | CRDO | laggards | down | -2.78 | -4.72 | -5.66 |
| 09:31 | ARM | laggards | down | -4.96 | -5.87 | -5.28 |
| 09:31 | CVNA | laggards | down | -2.17 | -1.27 | -3.53 |
| 09:32 | NBIS | leaders | up | -0.40 | -0.85 | -3.84 |
| 09:32 | TGT | leaders | up | +0.75 | +0.87 | +0.53 |
| 09:32 | AVGO | leaders | up | -1.11 | -1.28 | -1.15 |
| 09:32 | DDOG | laggards | down | +4.19 | +3.95 | +5.32 |
| 09:32 | PYPL | laggards | down | +1.93 | +2.07 | +1.80 |
| 09:33 | HUM | leaders | up | +0.81 | -0.18 | -0.34 |
| 09:33 | ANET | leaders | up | -1.34 | -1.18 | -1.12 |
| 09:33 | CRCL | laggards | down | +0.87 | -0.74 | +0.23 |
| 09:35 | CRWD | leaders | up | -0.12 | -0.23 | +1.85 |
| 09:36 | LLY | leaders | up | -0.45 | -0.14 | -0.07 |
| 09:36 | DASH | laggards | down | -1.84 | -0.91 | -1.08 |
| 09:36 | QCOM | laggards | down | -2.19 | -2.52 | -1.71 |
| 09:37 | PANW | leaders | up | +0.18 | +0.22 | +2.37 |
| 09:38 | MARA | leaders | up | -0.50 | -2.18 | -3.20 |
| 09:38 | ZS | leaders | up | +1.71 | +1.25 | +2.46 |
| 09:38 | ADBE | laggards | down | +0.61 | +1.73 | +2.15 |
| 09:39 | META | laggards | down | -0.10 | -0.14 | +0.20 |
| 09:41 | INTC | laggards | down | -0.44 | -1.27 | -2.47 |
| 09:44 | CNC | leaders | up | -0.51 | +0.12 | -0.29 |
| 09:51 | WMT | leaders | up | -0.40 | +0.35 | +0.05 |
| 09:59 | AAOI | laggards | down | -0.30 | -2.19 | -1.67 |
| 10:01 | COHR | laggards | down | -1.30 | -1.69 | -1.80 |
| 10:03 | U | laggards | down | +0.77 | +1.84 | +1.25 |
| 10:11 | SNDK | laggards | down | -0.95 | -0.33 | +0.27 |
| 10:13 | NKE | leaders | up | +0.50 | +0.16 | +0.13 |
| 10:13 | WDC | laggards | down | -0.02 | +0.94 | +1.43 |
| 10:21 | LUNR | leaders | up | -1.81 | -1.96 | -1.47 |
| 10:37 | KMX | leaders | up | -0.56 | -1.59 | -1.63 |
| 11:07 | S | leaders | up | +0.57 | +0.83 | +0.41 |
| 11:07 | CIFR | laggards | down | +0.48 | +0.82 | +0.25 |
| 11:17 | APLD | laggards | down | -0.42 | +0.08 | +0.34 |
| 11:18 | ALAB | laggards | down | +0.07 | +1.51 | +1.46 |
| 11:20 | PDD | leaders | up | -0.01 | -0.31 | -0.17 |
| 11:24 | FTNT | leaders | up | +0.39 | -0.19 | -0.33 |
| 11:36 | NET | leaders | up | +0.27 | +0.40 | +0.11 |
| 12:40 | DDOG | leaders | up | +0.08 | +0.50 | -0.02 |
| 13:15 | MSTR | leaders | up | -0.07 | -0.28 | -0.96 |
| 13:57 | HPQ | leaders | up | +0.07 | -0.44 | -1.09 |
| 14:13 | STX | leaders | up | -0.40 | -0.38 | — |
| 15:17 | IREN | laggards | down | -0.45 | — | — |
| 15:38 | RIOT | laggards | down | — | — | — |

## 2026-09-29

Usable symbol-minutes 64,776/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | CVNA | +5.39 | miss | 09:31 |
| 2 | DASH | +5.07 | miss | 09:37 |
| 3 | KMX | +4.92 | miss | 09:31 |
| 4 | MRVL | +4.70 | miss | 09:31 |
| 5 | LCID | +4.54 | miss | 11:23 |
| 6 | FLNC | +4.45 | miss | 09:31 |
| 7 | LAD | -4.37 | miss | 13:06 |
| 8 | AAOI | +4.16 | miss | 09:40 |
| 9 | ORCL | +4.10 | 10:26 | 10:18 |
| 10 | LUNR | -4.09 | miss | 09:40 |
| 11 | ARM | +3.83 | miss | 09:32 |
| 12 | APLD | +3.77 | miss | 10:29 |
| 13 | COHR | +3.64 | miss | 09:31 |
| 14 | LULU | -3.50 | miss | 09:31 |
| 15 | META | +3.42 | miss | 15:57 |
| 16 | CIEN | +3.30 | miss | 09:55 |
| 17 | RKLB | -3.27 | miss | 10:16 |
| 18 | S | +2.69 | miss | 09:35 |
| 19 | AN | -2.64 | miss | 12:03 |
| 20 | URI | -2.63 | miss | 10:12 |

### Radar flags (5)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | Space (ASTS, PL, RKLB, LUNR, IRDM) | group_move | down | +0.09 | -0.44 | -0.52 |
| 10:04 | ASTS | relative_to_spy | down | -0.14 | -0.78 | -1.44 |
| 10:15 | Gaming platforms (U, RBLX, APP, TTWO) | group_move | up | -0.08 | -0.02 | -0.21 |
| 10:26 | ORCL | relative_to_spy | up | +0.18 | -1.46 | -1.68 |
| 10:33 | Neoclouds and AI hosting (ORCL, CRWV, CIFR, APLD, WULF, IREN, NBIS) | group_move | up | -1.25 | -2.42 | -2.42 |

### Movers flags (71)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | KMX | leaders | up | -0.32 | -1.23 | -2.97 |
| 09:31 | ASTS | leaders | up | -3.83 | -4.86 | -6.23 |
| 09:31 | CVNA | leaders | up | +1.15 | +2.07 | +2.33 |
| 09:31 | FLNC | leaders | up | -0.64 | +0.52 | +0.68 |
| 09:31 | MRVL | leaders | up | +1.30 | +1.31 | +1.61 |
| 09:31 | AVGO | leaders | up | +0.54 | +0.74 | +0.02 |
| 09:31 | COIN | leaders | up | -1.80 | -1.45 | -2.51 |
| 09:31 | COHR | leaders | up | +2.49 | +4.15 | +2.73 |
| 09:31 | HIMS | leaders | up | +0.16 | -0.68 | -2.05 |
| 09:31 | RGTI | leaders | up | -1.68 | -1.73 | -2.20 |
| 09:31 | U | laggards | down | -0.33 | +2.16 | +1.79 |
| 09:31 | OXY | laggards | down | +0.70 | +0.74 | +1.08 |
| 09:31 | SHEL | laggards | down | +0.79 | +0.75 | +0.83 |
| 09:31 | AAPL | laggards | down | +0.04 | -0.25 | -0.07 |
| 09:31 | CVX | laggards | down | +0.99 | +0.64 | +1.27 |
| 09:31 | COP | laggards | down | +1.24 | +1.13 | +1.89 |
| 09:31 | XOM | laggards | down | +0.53 | +0.47 | +1.25 |
| 09:31 | JD | laggards | down | -0.09 | +0.05 | -0.09 |
| 09:31 | WMT | laggards | down | -1.51 | -1.39 | -1.04 |
| 09:31 | LULU | laggards | down | -1.16 | -1.17 | -1.00 |
| 09:32 | NFLX | leaders | up | -0.59 | +0.11 | -0.33 |
| 09:32 | ARM | leaders | up | +2.56 | +3.19 | +2.76 |
| 09:32 | WDC | leaders | up | -1.51 | -1.11 | -2.77 |
| 09:32 | NKE | laggards | down | +0.36 | +0.50 | +0.44 |
| 09:33 | NBIS | leaders | up | +0.76 | +3.57 | +1.71 |
| 09:33 | MU | leaders | up | -0.16 | +0.68 | -0.59 |
| 09:33 | MDB | laggards | down | +1.95 | +1.37 | +0.59 |
| 09:35 | S | leaders | up | -1.54 | -1.57 | -0.68 |
| 09:35 | CRDO | laggards | down | +2.33 | +4.94 | +2.81 |
| 09:36 | PDD | laggards | down | +0.37 | +0.38 | +0.40 |
| 09:37 | DASH | leaders | up | +0.60 | +0.65 | +1.34 |
| 09:38 | IONQ | leaders | up | -1.96 | -2.78 | -2.08 |
| 09:39 | DDOG | laggards | down | -0.78 | +0.15 | +0.88 |
| 09:40 | AAOI | leaders | up | +2.53 | +4.61 | +3.25 |
| 09:40 | LUNR | laggards | down | -0.03 | +0.26 | +0.73 |
| 09:40 | PANW | laggards | down | -1.73 | -1.12 | -0.89 |
| 09:41 | HOOD | leaders | up | -1.38 | -1.56 | -2.40 |
| 09:41 | RBLX | laggards | down | +1.77 | +1.86 | +1.53 |
| 09:42 | HPQ | laggards | down | +1.18 | +0.45 | +0.48 |
| 09:43 | INTC | laggards | down | +2.17 | +3.36 | +2.55 |
| 09:44 | FTNT | laggards | down | +0.76 | +0.57 | +1.34 |
| 09:44 | ZS | laggards | down | +1.06 | +0.63 | +1.25 |
| 09:49 | CRWV | leaders | up | +0.05 | +2.37 | -0.22 |
| 09:53 | ALAB | leaders | up | +0.86 | +0.50 | +1.50 |
| 09:55 | CIEN | leaders | up | -0.51 | -2.12 | -1.70 |
| 09:57 | CRDO | leaders | up | -0.37 | -0.54 | -1.34 |
| 09:58 | SPOT | laggards | down | +0.56 | +0.51 | +1.02 |
| 10:02 | PL | laggards | down | +0.28 | -0.13 | -0.90 |
| 10:04 | NVO | laggards | down | -0.03 | -0.04 | +0.24 |
| 10:09 | LYFT | leaders | up | -0.78 | -0.81 | -0.95 |
| 10:11 | TGT | laggards | down | -0.56 | -0.48 | +0.13 |
| 10:12 | URI | laggards | down | -1.67 | -3.48 | -2.93 |
| 10:16 | RKLB | laggards | down | +0.87 | -0.14 | -0.50 |
| 10:18 | ORCL | leaders | up | +3.88 | +2.01 | +1.74 |
| 10:29 | APLD | leaders | up | -0.48 | -2.10 | -1.57 |
| 10:31 | CNC | laggards | down | +0.18 | +0.72 | +0.54 |
| 10:33 | CVS | laggards | down | +0.49 | +0.74 | +0.26 |
| 10:37 | PFE | laggards | down | +0.30 | +0.31 | +0.27 |
| 10:40 | MRK | laggards | down | +0.53 | +0.66 | +1.23 |
| 11:01 | MSTR | laggards | down | -0.92 | -0.73 | -0.30 |
| 11:23 | LCID | leaders | up | -0.51 | -0.99 | -1.80 |
| 11:32 | QBTS | laggards | down | +0.70 | +0.23 | +0.10 |
| 11:37 | STX | laggards | down | +0.36 | -0.03 | +0.21 |
| 12:00 | TDOC | laggards | down | -0.45 | -0.22 | -0.34 |
| 12:03 | AN | laggards | down | -0.18 | -1.10 | -1.48 |
| 12:22 | ASTS | laggards | down | -0.40 | -1.53 | -0.78 |
| 13:02 | QCOM | laggards | down | +0.82 | +0.75 | +0.62 |
| 13:06 | LAD | laggards | down | — | — | — |
| 13:30 | NOW | laggards | down | +0.16 | +0.35 | +1.05 |
| 13:43 | CRCL | laggards | down | -0.15 | +0.24 | -1.07 |
| 15:57 | META | leaders | up | — | — | — |

## 2026-09-30

Usable symbol-minutes 64,747/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | KMX | -6.75 | miss | 09:31 |
| 2 | AI | +6.49 | miss | 09:36 |
| 3 | RIOT | -5.59 | miss | 09:39 |
| 4 | MARA | -5.30 | miss | 09:42 |
| 5 | APP | -4.78 | miss | 09:31 |
| 6 | UAA | +4.66 | miss | 14:05 |
| 7 | GM | -4.11 | miss | 10:00 |
| 8 | HIMS | +4.00 | miss | 09:36 |
| 9 | CIFR | -3.94 | miss | 09:34 |
| 10 | INTC | +3.91 | miss | 09:32 |
| 11 | APLD | -3.89 | miss | 09:34 |
| 12 | MDB | +3.59 | miss | 09:31 |
| 13 | NOW | +3.34 | miss | 11:16 |
| 14 | U | +3.25 | miss | 10:22 |
| 15 | ADBE | +3.11 | miss | 14:53 |
| 16 | RBLX | +3.10 | miss | 12:23 |
| 17 | CLSK | -3.03 | miss | 09:42 |
| 18 | SNOW | +3.01 | miss | 10:18 |
| 19 | HOOD | -3.00 | 10:02 | 09:36 |
| 20 | HSAI | +2.98 | miss | 09:43 |

### Radar flags (8)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | AAOI | relative_to_spy | down | -0.59 | -1.08 | -1.09 |
| 10:02 | COIN | relative_to_spy | down | -0.87 | -0.43 | -0.28 |
| 10:02 | HOOD | relative_to_spy | down | -0.61 | -1.24 | -0.71 |
| 10:02 | Bitcoin treasuries and miners (COIN, MSTR, MARA, RIOT, CLSK, IREN) | group_move | down | -1.03 | -0.97 | -1.00 |
| 10:02 | Crypto and exchanges (COIN, MSTR, HOOD, MARA, RIOT, CRCL, BULL) | group_move | down | -0.80 | -0.88 | -0.96 |
| 10:02 | Gaming platforms (RBLX, U, TTWO, APP) | group_move | up | -0.32 | -0.65 | -0.41 |
| 10:02 | Retail brokers and fintech (COIN, HOOD, BULL, PYPL, SCHW) | group_move | down | -0.27 | -0.37 | -0.50 |
| 10:02 | Space (RKLB, LUNR, ASTS, PL, IRDM) | group_move | up | -0.88 | -0.95 | -2.38 |

### Movers flags (82)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | MSTR | leaders | up | -4.03 | -5.41 | -5.31 |
| 09:31 | HOOD | leaders | up | -4.99 | -5.97 | -6.13 |
| 09:31 | NBIS | leaders | up | -2.28 | -3.57 | -4.18 |
| 09:31 | COIN | leaders | up | -5.20 | -6.23 | -5.63 |
| 09:31 | AAOI | leaders | up | -4.85 | -5.59 | -6.86 |
| 09:31 | CRCL | leaders | up | -2.75 | -3.59 | -3.92 |
| 09:31 | SMCI | leaders | up | -3.03 | -3.36 | -3.93 |
| 09:31 | MDB | leaders | up | +2.51 | +3.82 | +3.40 |
| 09:31 | FLNC | leaders | up | -2.27 | -1.68 | -3.05 |
| 09:31 | CRWV | leaders | up | -0.96 | -1.40 | -1.58 |
| 09:31 | APP | laggards | down | +1.12 | +0.65 | +0.45 |
| 09:31 | KMX | laggards | down | -2.93 | -3.05 | -3.50 |
| 09:31 | META | laggards | down | +0.24 | -0.71 | -0.07 |
| 09:31 | V | laggards | down | -0.58 | -0.33 | -0.15 |
| 09:31 | TSLA | laggards | down | -1.12 | +0.17 | -0.87 |
| 09:31 | PINS | laggards | down | +2.05 | +2.91 | +2.96 |
| 09:31 | U | laggards | down | +3.18 | +3.51 | +5.09 |
| 09:31 | UNH | laggards | down | -1.95 | -1.51 | -0.71 |
| 09:31 | ORCL | laggards | down | -0.47 | -0.14 | +0.08 |
| 09:31 | MS | laggards | down | -0.67 | -0.43 | -0.80 |
| 09:32 | IONQ | leaders | up | +2.65 | +0.82 | -2.16 |
| 09:32 | INTC | leaders | up | -0.78 | -0.91 | -0.48 |
| 09:32 | MA | laggards | down | -0.71 | -0.70 | -0.38 |
| 09:32 | SPOT | laggards | down | +0.22 | +0.25 | +0.58 |
| 09:32 | NFLX | laggards | down | +0.09 | +0.09 | +0.02 |
| 09:32 | CVNA | laggards | down | -0.05 | -0.09 | -1.43 |
| 09:33 | RGTI | leaders | up | +0.95 | -0.51 | -2.13 |
| 09:33 | LUNR | leaders | up | +2.05 | +0.49 | -1.39 |
| 09:33 | RKLB | leaders | up | +2.73 | +2.22 | -0.16 |
| 09:33 | MRK | laggards | down | -0.53 | -0.55 | -0.99 |
| 09:34 | SONY | leaders | up | -0.79 | -0.65 | -1.32 |
| 09:34 | QUBT | leaders | up | +1.03 | -0.49 | -1.20 |
| 09:34 | WULF | laggards | down | +0.12 | -0.38 | -0.55 |
| 09:34 | APLD | laggards | down | -1.01 | -1.67 | -2.30 |
| 09:34 | CIEN | laggards | down | -0.93 | -1.67 | -2.50 |
| 09:34 | CIFR | laggards | down | -0.77 | -1.52 | -2.17 |
| 09:36 | HIMS | leaders | up | +2.38 | +3.39 | +4.85 |
| 09:36 | AI | leaders | up | +3.17 | +2.35 | +2.25 |
| 09:36 | HOOD | laggards | down | +1.25 | +0.37 | +0.37 |
| 09:36 | WDC | laggards | down | +1.29 | +2.03 | +2.98 |
| 09:37 | ASTS | leaders | up | +2.73 | +2.23 | +1.44 |
| 09:37 | BULL | laggards | down | +0.13 | -0.08 | -0.65 |
| 09:37 | DASH | laggards | down | +1.02 | +1.19 | — |
| 09:38 | DDOG | leaders | up | -1.76 | -1.30 | -0.87 |
| 09:38 | SNAP | leaders | up | +3.01 | +2.07 | +1.57 |
| 09:38 | COHR | laggards | down | -0.99 | -2.06 | -1.74 |
| 09:39 | RIOT | laggards | down | -1.27 | -2.12 | -1.66 |
| 09:39 | CI | laggards | down | -2.33 | -1.57 | -0.63 |
| 09:41 | MRVL | laggards | down | -0.44 | -0.88 | +0.13 |
| 09:42 | HPQ | leaders | up | -2.70 | -1.34 | -0.78 |
| 09:42 | MARA | laggards | down | +0.01 | -0.32 | -1.08 |
| 09:42 | CLSK | laggards | down | -0.05 | -0.34 | -0.73 |
| 09:42 | AAOI | laggards | down | -0.20 | -0.94 | -1.21 |
| 09:43 | HSAI | leaders | up | +0.24 | -0.08 | +0.05 |
| 09:43 | FLNC | laggards | down | +3.84 | +3.06 | +1.33 |
| 09:45 | CRM | leaders | up | +0.08 | +0.70 | +0.50 |
| 09:46 | HUM | laggards | down | +0.41 | +2.14 | — |
| 09:48 | PL | leaders | up | +0.10 | -0.44 | -1.49 |
| 09:49 | RDDT | leaders | up | +1.26 | -0.42 | -1.06 |
| 09:56 | CNC | laggards | down | +0.76 | +1.76 | +1.69 |
| 10:00 | GM | laggards | down | +0.17 | -0.38 | -1.58 |
| 10:03 | QBTS | leaders | up | -1.17 | -1.33 | -2.87 |
| 10:06 | CVS | laggards | down | +1.08 | +1.08 | +1.02 |
| 10:14 | OKLO | leaders | up | -0.41 | -1.06 | -2.56 |
| 10:18 | SNOW | leaders | up | +0.91 | +1.45 | +1.15 |
| 10:22 | U | leaders | up | +0.14 | +0.67 | +0.66 |
| 10:24 | COIN | laggards | down | -0.05 | +0.31 | +0.98 |
| 10:36 | ARM | laggards | down | -0.31 | +0.20 | +0.09 |
| 10:57 | PANW | leaders | up | +0.29 | +0.38 | +0.13 |
| 11:02 | ALAB | laggards | down | -0.22 | -0.52 | +1.03 |
| 11:02 | CRDO | laggards | down | -0.21 | +0.14 | +0.57 |
| 11:16 | NOW | leaders | up | +0.08 | -0.14 | -0.52 |
| 11:49 | GOOGL | leaders | up | -0.11 | -0.16 | -0.44 |
| 11:53 | S | leaders | up | -0.57 | -0.86 | -1.25 |
| 12:23 | RBLX | leaders | up | -0.25 | -0.76 | -0.05 |
| 12:27 | F | laggards | down | +0.36 | +0.58 | +0.47 |
| 12:33 | TTWO | leaders | up | -0.02 | -0.35 | -0.94 |
| 12:45 | LAD | laggards | down | +1.10 | +3.62 | +3.36 |
| 13:59 | PYPL | laggards | down | -0.41 | +0.22 | +0.32 |
| 14:05 | UAA | leaders | up | +0.71 | +0.18 | — |
| 14:44 | FND | laggards | down | +0.05 | +0.14 | — |
| 14:53 | ADBE | leaders | up | +0.12 | +0.37 | — |

## 2026-10-01

Usable symbol-minutes 64,949/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | COHR | +10.72 | 10:11 | 09:51 |
| 2 | AAOI | +7.94 | 10:15 | 10:00 |
| 3 | CRDO | +7.72 | miss | 09:31 |
| 4 | CIEN | +7.59 | miss | 10:15 |
| 5 | U | +6.37 | miss | 09:31 |
| 6 | RDDT | +4.80 | miss | 09:34 |
| 7 | LAD | +4.70 | miss | 14:06 |
| 8 | MSTR | +4.66 | miss | 09:38 |
| 9 | AN | +4.62 | miss | 10:52 |
| 10 | SNAP | +4.45 | miss | 15:51 |
| 11 | OXY | +4.38 | miss | 09:40 |
| 12 | UAA | +3.86 | miss | 12:24 |
| 13 | S | +3.65 | miss | 11:32 |
| 14 | DIS | -3.58 | miss | 09:40 |
| 15 | AMGN | -3.56 | miss | 12:00 |
| 16 | APP | -3.32 | miss | 09:31 |
| 17 | ASTS | -3.27 | miss | 09:41 |
| 18 | URI | +3.15 | miss | miss |
| 19 | CLSK | -2.97 | miss | 09:51 |
| 20 | CRM | +2.92 | miss | 09:31 |

### Radar flags (5)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:05 | Neoclouds and AI hosting (CIFR, WULF, APLD, NBIS, CRWV, IREN, ORCL) | group_move | down | +0.43 | +0.44 | +0.64 |
| 10:11 | COHR | relative_to_spy | up | +3.34 | +3.22 | +4.13 |
| 10:15 | AAOI | relative_to_spy | up | +0.74 | +1.22 | +1.30 |
| 10:18 | Space (RKLB, LUNR, ASTS, PL, IRDM) | group_move | up | -0.13 | -1.39 | — |
| 13:30 | Bitcoin treasuries and miners (CLSK, RIOT, MARA, MSTR, IREN, COIN) | group_move | up | -0.31 | -1.07 | -1.37 |

### Movers flags (86)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | IBM | leaders | up | -0.29 | -0.03 | -1.87 |
| 09:31 | LCID | leaders | up | -4.04 | -4.05 | -3.98 |
| 09:31 | NOW | leaders | up | -0.05 | -1.21 | -2.76 |
| 09:31 | CRM | leaders | up | +0.24 | -0.09 | -1.68 |
| 09:31 | RKLB | leaders | up | +0.81 | +1.23 | -0.15 |
| 09:31 | ADBE | leaders | up | -0.56 | -0.60 | -2.27 |
| 09:31 | GOOGL | leaders | up | -1.90 | -2.25 | -2.47 |
| 09:31 | U | leaders | up | -0.16 | +2.76 | +2.22 |
| 09:31 | CRDO | leaders | up | +1.83 | +2.75 | +3.17 |
| 09:31 | DDOG | leaders | up | +0.05 | -0.77 | -1.02 |
| 09:31 | DE | laggards | down | +0.50 | -0.69 | -0.56 |
| 09:31 | INTC | laggards | down | +0.48 | +0.51 | +1.41 |
| 09:31 | APP | laggards | down | +0.55 | -0.75 | -1.28 |
| 09:31 | CVNA | laggards | down | -0.79 | -1.18 | -3.60 |
| 09:31 | LAD | laggards | down | +0.21 | +1.35 | — |
| 09:31 | PANW | laggards | down | +1.32 | +0.78 | +0.55 |
| 09:31 | NBIS | laggards | down | -0.78 | -1.34 | -0.44 |
| 09:31 | AAPL | laggards | down | +0.38 | +0.74 | +0.13 |
| 09:31 | CRWD | laggards | down | +2.58 | +1.92 | +1.65 |
| 09:31 | C | laggards | down | -1.80 | -2.11 | -2.67 |
| 09:32 | ASTS | leaders | up | -1.33 | -0.67 | -2.33 |
| 09:32 | TDOC | leaders | up | -2.50 | -2.25 | -2.63 |
| 09:32 | MDB | laggards | down | +3.06 | +3.35 | +3.22 |
| 09:32 | STX | laggards | down | +0.44 | -0.41 | +0.49 |
| 09:32 | MRVL | laggards | down | +0.06 | +0.52 | +2.40 |
| 09:33 | BABA | leaders | up | +0.04 | -0.95 | -1.52 |
| 09:33 | FTNT | laggards | down | +1.42 | +1.36 | +1.41 |
| 09:33 | LLY | laggards | down | +0.70 | +0.55 | +0.95 |
| 09:34 | RDDT | leaders | up | +0.91 | +0.99 | -0.08 |
| 09:34 | PYPL | leaders | up | +0.39 | -0.38 | -0.30 |
| 09:34 | S | laggards | down | +2.18 | +2.32 | +3.21 |
| 09:34 | XOM | laggards | down | +2.23 | +2.21 | +2.41 |
| 09:35 | LULU | leaders | up | +0.02 | -0.03 | -0.49 |
| 09:35 | NET | laggards | down | +1.97 | +1.76 | +3.07 |
| 09:36 | MSFT | leaders | up | -0.18 | -0.42 | -0.94 |
| 09:36 | MU | laggards | down | -0.12 | +0.15 | +1.03 |
| 09:36 | WDC | laggards | down | +0.35 | -0.05 | +0.49 |
| 09:36 | SMCI | laggards | down | +0.18 | +0.50 | +0.61 |
| 09:38 | MSTR | leaders | up | +1.04 | +1.57 | +0.71 |
| 09:38 | HPQ | leaders | up | +0.93 | +1.37 | +0.80 |
| 09:38 | AI | laggards | down | +0.37 | +0.03 | +0.41 |
| 09:38 | LUNR | laggards | down | +1.89 | +2.84 | +0.08 |
| 09:38 | FND | laggards | down | -0.88 | -0.56 | -0.75 |
| 09:39 | COIN | leaders | up | +0.13 | +0.34 | -0.16 |
| 09:39 | UAA | laggards | down | +2.25 | +2.71 | +2.90 |
| 09:40 | OXY | leaders | up | +1.34 | +1.67 | +1.73 |
| 09:40 | IREN | laggards | down | -1.12 | -0.12 | -0.23 |
| 09:40 | DIS | laggards | down | -0.33 | -0.77 | -1.09 |
| 09:40 | HD | laggards | down | -0.47 | -0.33 | -0.11 |
| 09:41 | ASTS | laggards | down | +1.72 | +2.32 | +0.13 |
| 09:41 | TTWO | laggards | down | -0.85 | -0.49 | -0.64 |
| 09:42 | BAC | laggards | down | -0.77 | -0.69 | -0.47 |
| 09:43 | FLNC | laggards | down | +0.18 | +0.73 | +1.43 |
| 09:43 | RIOT | laggards | down | -3.33 | -2.25 | -3.65 |
| 09:44 | LOW | laggards | down | -0.40 | -0.50 | -0.03 |
| 09:46 | CIFR | laggards | down | -1.99 | -1.36 | -2.14 |
| 09:47 | HIMS | laggards | down | -0.48 | +0.51 | -0.64 |
| 09:48 | CRCL | leaders | up | -0.45 | -1.06 | -1.11 |
| 09:51 | COHR | leaders | up | +6.22 | +6.95 | +8.60 |
| 09:51 | CLSK | laggards | down | -2.58 | -1.47 | -2.93 |
| 09:54 | CI | laggards | down | +0.04 | +1.11 | +0.79 |
| 09:54 | CNC | laggards | down | -1.27 | -0.01 | +1.11 |
| 09:55 | ALAB | leaders | up | -2.14 | -1.00 | -0.24 |
| 09:58 | PLTR | leaders | up | -0.14 | -0.96 | -1.26 |
| 09:59 | ELV | laggards | down | +0.53 | +0.67 | +0.43 |
| 10:00 | AAOI | leaders | up | +1.95 | +3.66 | +3.95 |
| 10:04 | DELL | laggards | down | +1.69 | +1.06 | +2.36 |
| 10:05 | APLD | laggards | down | +1.12 | +1.13 | +1.31 |
| 10:15 | CIEN | leaders | up | +1.71 | +2.65 | +3.71 |
| 10:20 | MARA | laggards | down | +0.69 | +0.03 | -0.51 |
| 10:52 | AN | leaders | up | — | +1.12 | — |
| 11:06 | MS | laggards | down | +0.12 | +0.62 | +1.27 |
| 11:21 | COP | leaders | up | +0.19 | -0.27 | -0.92 |
| 11:32 | S | leaders | up | -0.16 | +0.04 | +0.14 |
| 11:43 | MDB | leaders | up | -0.20 | -0.39 | -0.65 |
| 12:00 | AMGN | laggards | down | -0.20 | -0.37 | -0.47 |
| 12:24 | UAA | leaders | up | -0.18 | +1.16 | +1.18 |
| 12:36 | NFLX | laggards | down | +0.19 | +0.29 | -0.08 |
| 12:54 | GOOGL | laggards | down | +0.47 | +0.63 | +0.27 |
| 13:25 | PDD | laggards | down | -0.30 | -0.07 | -0.23 |
| 13:55 | OKLO | laggards | down | -0.15 | -0.88 | -0.59 |
| 13:57 | RCAT | laggards | down | -0.19 | -0.16 | +0.24 |
| 14:06 | LAD | leaders | up | +0.13 | +0.72 | — |
| 15:51 | SNAP | leaders | up | — | — | — |
| 15:58 | TDOC | laggards | down | — | — | — |
| 15:59 | AVGO | laggards | down | — | — | — |

## 2026-10-02

Usable symbol-minutes 64,684/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | WDC | -10.96 | miss | 09:31 |
| 2 | STX | -10.95 | miss | 09:31 |
| 3 | PL | +7.69 | 10:13 | 09:50 |
| 4 | AAOI | +6.97 | 10:06 | 10:07 |
| 5 | QBTS | -5.51 | miss | 14:53 |
| 6 | APP | -5.39 | miss | 09:31 |
| 7 | COHR | +4.85 | miss | 11:08 |
| 8 | SNDK | -4.53 | miss | 09:31 |
| 9 | SPOT | -4.51 | miss | 09:34 |
| 10 | ARM | +4.44 | miss | 09:31 |
| 11 | NKE | -4.38 | miss | 09:31 |
| 12 | APLD | +4.31 | miss | 09:31 |
| 13 | HSAI | -4.19 | miss | 09:32 |
| 14 | RKLB | +4.17 | 10:12 | 09:32 |
| 15 | COIN | -4.06 | miss | 10:54 |
| 16 | LUNR | +3.96 | 10:05 | 09:50 |
| 17 | TSLA | +3.91 | miss | 11:13 |
| 18 | RIVN | -3.86 | 10:02 | 09:44 |
| 19 | URI | +3.80 | miss | 14:14 |
| 20 | NBIS | +3.79 | miss | 10:56 |

### Radar flags (14)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | CRDO | relative_to_spy | up | -0.06 | -0.91 | -1.63 |
| 10:02 | RIVN | relative_to_spy | down | +2.77 | +2.86 | +1.18 |
| 10:02 | Bitcoin treasuries and miners (MARA, IREN, RIOT, CLSK) | group_move | up | -0.54 | -2.73 | -4.68 |
| 10:02 | Neoclouds and AI hosting (APLD, WULF, NBIS, IREN, CIFR) | group_move | up | +0.83 | -0.72 | -2.48 |
| 10:05 | LUNR | relative_to_spy | up | +1.18 | -0.12 | -2.15 |
| 10:05 | AI networking and connectivity (CRDO, ALAB, COHR, AVGO) | group_move | up | -0.28 | -0.20 | -0.58 |
| 10:05 | Space (LUNR, PL, ASTS, RKLB) | group_move | up | +1.03 | +0.30 | -0.44 |
| 10:06 | AAOI | relative_to_spy | up | +1.65 | +1.53 | +1.22 |
| 10:12 | RKLB | relative_to_sector | up | +0.78 | -1.09 | -1.20 |
| 10:13 | PL | relative_to_spy | up | +0.60 | -0.29 | +0.55 |
| 10:18 | Crypto and exchanges (COIN, CRCL, MSTR, HOOD, MARA) | group_move | down | -0.45 | -2.08 | -3.51 |
| 10:37 | Bitcoin treasuries and miners (MARA, MSTR, CLSK, COIN, RIOT, IREN) | group_move | down | -1.74 | -2.49 | -3.51 |
| 10:54 | Memory and storage (STX, WDC, SNDK, MU) | group_move | down | +0.04 | +1.57 | +0.94 |
| 11:21 | Space (LUNR, ASTS, RKLB, PL, IRDM) | group_move | down | +0.16 | +0.56 | +0.67 |

### Movers flags (61)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | ARM | leaders | up | +1.01 | +1.78 | +2.67 |
| 09:31 | APLD | leaders | up | +3.54 | +4.92 | +0.61 |
| 09:31 | MSTR | leaders | up | -1.01 | -3.17 | -3.92 |
| 09:31 | COIN | leaders | up | -2.53 | -4.22 | -5.84 |
| 09:31 | MRVL | leaders | up | -0.24 | -1.14 | -1.77 |
| 09:31 | HOOD | leaders | up | -0.51 | +0.70 | -0.32 |
| 09:31 | U | leaders | up | -1.07 | -2.00 | -2.03 |
| 09:31 | WULF | leaders | up | +3.06 | +4.51 | +0.96 |
| 09:31 | CRCL | leaders | up | -1.08 | -1.67 | -3.79 |
| 09:31 | INTC | leaders | up | +0.58 | +0.25 | -1.46 |
| 09:31 | STX | laggards | down | +4.49 | +4.87 | +1.73 |
| 09:31 | WDC | laggards | down | +0.18 | -0.76 | -3.80 |
| 09:31 | NKE | laggards | down | +0.70 | +1.20 | +0.74 |
| 09:31 | APP | laggards | down | -0.12 | +1.73 | -0.07 |
| 09:31 | ALAB | laggards | down | +3.42 | +3.33 | +2.56 |
| 09:31 | SNDK | laggards | down | -0.32 | +0.01 | -1.47 |
| 09:31 | CVX | laggards | down | +1.24 | +0.28 | +1.12 |
| 09:31 | JD | laggards | down | -0.38 | -0.43 | -0.82 |
| 09:31 | OXY | laggards | down | +1.04 | +0.01 | +0.77 |
| 09:31 | LULU | laggards | down | +0.73 | +0.10 | -0.82 |
| 09:32 | RKLB | leaders | up | +1.50 | +2.67 | +0.89 |
| 09:32 | MARA | leaders | up | +3.34 | +1.39 | -2.45 |
| 09:32 | CLSK | leaders | up | +2.12 | +1.16 | -1.81 |
| 09:32 | CIFR | leaders | up | +0.58 | +1.02 | -1.65 |
| 09:32 | HSAI | laggards | down | -0.78 | — | -0.84 |
| 09:32 | BABA | laggards | down | -0.38 | +0.15 | -0.58 |
| 09:33 | BULL | leaders | up | +0.27 | +1.46 | +0.77 |
| 09:33 | ASTS | laggards | down | +3.12 | +2.97 | +2.08 |
| 09:34 | RIOT | leaders | up | +2.14 | +1.21 | -1.95 |
| 09:34 | SPOT | laggards | down | -1.85 | -0.57 | -1.28 |
| 09:34 | PDD | laggards | down | -0.31 | -0.04 | -0.43 |
| 09:36 | MDB | laggards | down | +0.91 | +3.29 | +3.61 |
| 09:36 | RDDT | laggards | down | +0.58 | +1.13 | +0.57 |
| 09:37 | IREN | leaders | up | +1.96 | +1.63 | -1.41 |
| 09:41 | CRDO | leaders | up | +3.02 | +2.94 | +1.43 |
| 09:42 | SNAP | laggards | down | +3.72 | +3.78 | +3.77 |
| 09:44 | RIVN | laggards | down | -0.64 | +0.68 | -0.17 |
| 09:50 | LUNR | leaders | up | +2.49 | +2.79 | -0.82 |
| 09:50 | PL | leaders | up | +1.86 | +3.59 | +2.23 |
| 09:51 | SNOW | laggards | down | +1.77 | +1.74 | +1.67 |
| 09:58 | LCID | laggards | down | +1.31 | +1.62 | — |
| 10:04 | F | laggards | down | +0.71 | +0.66 | -0.24 |
| 10:05 | SCHW | laggards | down | +0.23 | +0.14 | -0.11 |
| 10:07 | AAOI | leaders | up | +0.61 | +0.55 | +0.36 |
| 10:07 | NOW | laggards | down | +0.42 | +0.39 | +0.15 |
| 10:17 | KMX | laggards | down | +0.54 | -0.55 | -0.50 |
| 10:20 | SMCI | leaders | up | -0.62 | -2.52 | -2.05 |
| 10:25 | ADBE | laggards | down | +0.52 | +0.63 | +0.03 |
| 10:47 | PFE | laggards | down | +0.12 | -0.01 | -0.52 |
| 10:51 | MU | laggards | down | -0.37 | +0.16 | -0.19 |
| 10:54 | COIN | laggards | down | -0.71 | -2.14 | -1.85 |
| 10:56 | NBIS | leaders | up | -0.87 | -0.75 | -1.26 |
| 11:08 | COHR | leaders | up | -0.48 | +0.05 | -0.26 |
| 11:13 | TSLA | leaders | up | +0.74 | +0.42 | +0.31 |
| 11:34 | TDOC | laggards | down | -0.39 | -0.57 | -0.60 |
| 12:22 | DELL | leaders | up | -0.31 | -0.16 | -0.10 |
| 13:39 | CRCL | laggards | down | -0.18 | -0.52 | -0.67 |
| 14:14 | URI | leaders | up | -0.22 | -0.63 | — |
| 14:45 | MSTR | laggards | down | +0.12 | +1.44 | — |
| 14:53 | QBTS | laggards | down | -0.94 | -1.91 | — |
| 15:42 | QUBT | laggards | down | — | — | — |

## 2026-10-05

Usable symbol-minutes 64,669/65,910. No usable minutes: TCEHY. Daily ranking covers 145/146 stocks. Excluded: TCEHY.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | WDC | +5.67 | miss | 09:31 |
| 2 | WULF | -5.19 | 10:02 | 09:37 |
| 3 | NBIS | -4.89 | miss | 09:47 |
| 4 | AAOI | +4.50 | miss | 09:31 |
| 5 | APP | +4.45 | miss | 09:31 |
| 6 | TDOC | +4.22 | miss | 12:58 |
| 7 | U | +4.07 | miss | 09:38 |
| 8 | BABA | +4.00 | miss | 09:31 |
| 9 | MRK | -3.97 | miss | 10:06 |
| 10 | STX | +3.81 | miss | 09:31 |
| 11 | IREN | -3.74 | miss | 09:34 |
| 12 | QUBT | -3.61 | miss | 10:35 |
| 13 | LUNR | -3.53 | miss | 09:31 |
| 14 | CRDO | -3.49 | miss | 09:31 |
| 15 | PINS | +3.48 | miss | 09:32 |
| 16 | HUM | +3.37 | miss | 13:28 |
| 17 | APLD | -3.35 | miss | 09:33 |
| 18 | INTC | -3.31 | miss | 09:31 |
| 19 | CRWV | -3.16 | miss | 15:52 |
| 20 | QCOM | -2.88 | miss | 15:46 |

### Radar flags (3)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | CIFR | relative_to_spy | down | +0.84 | +2.17 | +1.58 |
| 10:02 | WULF | relative_to_spy | down | -0.40 | +0.14 | -0.47 |
| 10:02 | Bitcoin treasuries and miners (MARA, CLSK, IREN, RIOT, MSTR) | group_move | down | +0.07 | +0.30 | -0.42 |

### Movers flags (63)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | WDC | leaders | up | +0.48 | +0.97 | +0.80 |
| 09:31 | STX | leaders | up | +0.58 | -0.40 | -0.60 |
| 09:31 | APP | leaders | up | +1.86 | +2.77 | +3.24 |
| 09:31 | AAOI | leaders | up | -3.38 | -3.79 | -4.31 |
| 09:31 | RDDT | leaders | up | -1.19 | -1.74 | -0.93 |
| 09:31 | BABA | leaders | up | +0.13 | +0.57 | +1.47 |
| 09:31 | MRVL | leaders | up | -3.12 | -2.19 | -2.17 |
| 09:31 | WFC | leaders | up | -1.06 | -0.30 | -0.82 |
| 09:31 | COIN | leaders | up | +1.04 | +0.95 | +0.79 |
| 09:31 | JD | leaders | up | -0.08 | +0.19 | +0.13 |
| 09:31 | INTC | laggards | down | +0.12 | +0.79 | +0.72 |
| 09:31 | AN | laggards | down | -0.20 | -0.40 | +1.33 |
| 09:31 | LUNR | laggards | down | -2.40 | +0.22 | -1.64 |
| 09:31 | AMD | laggards | down | +1.07 | +1.19 | +1.08 |
| 09:31 | RKLB | laggards | down | -0.90 | -0.08 | -0.91 |
| 09:31 | CRDO | laggards | down | -3.08 | -2.29 | -2.06 |
| 09:31 | TGT | laggards | down | -1.16 | -1.75 | -1.63 |
| 09:31 | SONY | laggards | down | -0.09 | -0.33 | -0.56 |
| 09:31 | QBTS | laggards | down | -1.71 | -1.33 | -1.46 |
| 09:31 | RGTI | laggards | down | -1.30 | -1.38 | -1.47 |
| 09:32 | MSTR | leaders | up | -0.37 | -0.58 | -1.33 |
| 09:32 | CRCL | leaders | up | -0.06 | +1.61 | +0.08 |
| 09:32 | PINS | leaders | up | +0.12 | +0.07 | +0.15 |
| 09:32 | SNAP | leaders | up | -0.27 | -0.79 | -0.89 |
| 09:32 | LAD | laggards | down | -2.09 | -1.16 | — |
| 09:32 | PL | laggards | down | -0.48 | +0.49 | +0.01 |
| 09:32 | NKE | laggards | down | -1.18 | -1.68 | -1.01 |
| 09:33 | HSAI | leaders | up | +1.63 | +0.67 | +0.96 |
| 09:33 | APLD | laggards | down | -0.42 | -1.39 | -2.09 |
| 09:33 | IONQ | laggards | down | +0.38 | -0.51 | -1.57 |
| 09:34 | IREN | laggards | down | -1.09 | -2.21 | -2.29 |
| 09:34 | CIFR | laggards | down | -2.42 | -2.26 | -1.89 |
| 09:36 | ZS | leaders | up | +0.70 | +1.12 | +1.14 |
| 09:36 | DELL | laggards | down | +1.01 | +0.76 | +0.76 |
| 09:36 | KMX | laggards | down | -0.14 | +0.16 | +1.68 |
| 09:37 | CLSK | laggards | down | -0.68 | -0.54 | -1.66 |
| 09:37 | RIOT | laggards | down | +0.83 | +0.16 | -0.31 |
| 09:37 | WULF | laggards | down | -2.08 | -2.58 | -3.09 |
| 09:38 | U | leaders | up | +1.62 | +2.59 | +3.51 |
| 09:40 | MARA | laggards | down | +0.53 | -0.32 | -0.59 |
| 09:41 | ORCL | leaders | up | -0.28 | -0.69 | -1.96 |
| 09:44 | MSFT | leaders | up | -1.11 | -1.15 | -1.40 |
| 09:44 | FLNC | laggards | down | +1.96 | +1.07 | +1.79 |
| 09:47 | PDD | leaders | up | -0.72 | -0.60 | -0.13 |
| 09:47 | DASH | leaders | up | -1.99 | -0.87 | -1.03 |
| 09:47 | NBIS | laggards | down | +0.71 | -0.10 | -0.26 |
| 09:53 | COHR | laggards | down | +1.00 | +1.11 | +1.25 |
| 10:06 | MRK | laggards | down | -0.77 | -0.99 | -0.86 |
| 10:14 | NET | leaders | up | +0.93 | +1.07 | +1.40 |
| 10:35 | QUBT | laggards | down | +0.13 | -0.48 | +0.14 |
| 10:44 | BIDU | leaders | up | +0.01 | -0.01 | -0.35 |
| 11:00 | HPQ | laggards | down | +0.07 | +0.25 | +0.07 |
| 11:02 | LULU | laggards | down | -0.04 | +0.57 | +0.89 |
| 11:30 | ALAB | leaders | up | +0.34 | -1.00 | -0.08 |
| 12:30 | GM | leaders | up | -0.04 | -0.12 | +0.23 |
| 12:37 | TSM | leaders | up | -0.06 | +0.15 | +0.43 |
| 12:58 | TDOC | leaders | up | +0.32 | -0.09 | +1.65 |
| 13:28 | HUM | leaders | up | — | — | +1.91 |
| 13:47 | FND | leaders | up | +0.13 | -0.44 | -0.40 |
| 14:43 | ONON | leaders | up | -0.21 | +0.06 | — |
| 15:22 | CRM | laggards | down | +0.20 | — | — |
| 15:46 | QCOM | laggards | down | — | — | — |
| 15:52 | CRWV | laggards | down | — | — | — |

## 2026-10-06

Usable symbol-minutes 64,253/65,910. No usable minutes: TCEHY, WBD. Daily ranking covers 144/146 stocks. Excluded: TCEHY, WBD.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | CIEN | +13.30 | miss | 10:09 |
| 2 | STX | -9.73 | miss | 09:31 |
| 3 | WDC | -7.48 | miss | 09:31 |
| 4 | ASTS | +7.46 | miss | 09:31 |
| 5 | ALAB | +7.03 | miss | 09:31 |
| 6 | NBIS | +6.89 | miss | 09:31 |
| 7 | OKLO | +6.62 | miss | 09:31 |
| 8 | AAOI | +6.52 | miss | 09:31 |
| 9 | PL | +6.42 | miss | 09:31 |
| 10 | MRVL | +5.26 | 10:02 | 09:34 |
| 11 | LUNR | +4.84 | miss | 09:31 |
| 12 | ZS | +4.63 | miss | 09:31 |
| 13 | FLNC | +4.42 | miss | 10:01 |
| 14 | CRWV | +4.41 | miss | 11:44 |
| 15 | LAD | -4.01 | miss | 09:31 |
| 16 | INTC | -3.73 | miss | 10:33 |
| 17 | CPRT | -3.55 | miss | 09:32 |
| 18 | ANET | +3.54 | miss | 15:25 |
| 19 | DELL | +3.38 | miss | 09:41 |
| 20 | CRDO | +3.38 | 10:02 | 09:46 |

### Radar flags (4)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | CRDO | relative_to_spy | up | -0.43 | -0.39 | -0.60 |
| 10:02 | MRVL | relative_to_spy | up | -1.20 | -2.14 | -1.77 |
| 10:02 | AI networking and connectivity (MRVL, CRDO, ALAB, AVGO, ANET, COHR) | group_move | up | -0.37 | -0.20 | -0.17 |
| 10:02 | Space (ASTS, PL, RKLB, LUNR, IRDM) | group_move | up | -1.58 | -1.64 | -2.72 |

### Movers flags (59)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | ALAB | leaders | up | +2.70 | +2.05 | +1.24 |
| 09:31 | AAOI | leaders | up | -1.20 | -1.17 | -0.37 |
| 09:31 | ZS | leaders | up | +0.24 | -0.75 | -1.52 |
| 09:31 | PL | leaders | up | +2.59 | +2.22 | +0.86 |
| 09:31 | ASTS | leaders | up | +5.31 | +4.15 | +1.96 |
| 09:31 | OKLO | leaders | up | +3.70 | +4.42 | +4.00 |
| 09:31 | NBIS | leaders | up | +2.58 | +2.14 | +4.49 |
| 09:31 | LUNR | leaders | up | +2.18 | +0.43 | +0.15 |
| 09:31 | RKLB | leaders | up | +2.74 | +0.94 | -0.09 |
| 09:31 | AMD | leaders | up | -1.30 | -0.47 | +0.81 |
| 09:31 | WDC | laggards | down | -3.18 | -4.15 | -3.69 |
| 09:31 | STX | laggards | down | -3.39 | -5.03 | -5.46 |
| 09:31 | AN | laggards | down | -0.98 | — | -1.87 |
| 09:31 | PINS | laggards | down | -1.36 | -1.10 | -1.06 |
| 09:31 | LAD | laggards | down | -1.60 | -2.44 | — |
| 09:31 | BABA | laggards | down | -0.94 | -1.29 | -1.39 |
| 09:31 | FND | laggards | down | +1.43 | +1.16 | +1.53 |
| 09:31 | U | laggards | down | +0.10 | +0.35 | -0.57 |
| 09:31 | NVO | laggards | down | -0.40 | -0.67 | -0.50 |
| 09:31 | SPOT | laggards | down | +1.26 | +1.28 | +1.82 |
| 09:32 | PANW | leaders | up | +1.34 | +0.27 | -0.56 |
| 09:32 | RBLX | laggards | down | +1.22 | +2.64 | +2.74 |
| 09:32 | PDD | laggards | down | +0.28 | +0.48 | +0.67 |
| 09:32 | CPRT | laggards | down | -1.46 | -1.89 | -1.75 |
| 09:33 | FTNT | leaders | up | -1.73 | -1.79 | -1.91 |
| 09:33 | CRWD | leaders | up | +0.21 | -0.56 | -0.70 |
| 09:33 | NKE | laggards | down | +0.81 | +1.62 | +2.13 |
| 09:34 | MRVL | leaders | up | +4.90 | +3.27 | +1.98 |
| 09:34 | OXY | laggards | down | +0.12 | +0.86 | +0.98 |
| 09:35 | APLD | leaders | up | -1.33 | -2.15 | -2.08 |
| 09:37 | IONQ | leaders | up | -1.75 | -2.49 | -4.13 |
| 09:37 | SNDK | laggards | down | +0.57 | -0.98 | -0.79 |
| 09:38 | QUBT | leaders | up | -2.08 | -3.17 | -3.52 |
| 09:38 | DECK | laggards | down | +0.97 | +1.32 | +2.66 |
| 09:41 | DELL | leaders | up | +1.34 | +0.44 | -0.08 |
| 09:46 | CRDO | leaders | up | -0.48 | +0.25 | -0.11 |
| 09:52 | TDOC | laggards | down | +0.80 | +1.71 | +1.32 |
| 09:53 | RDDT | laggards | down | +0.27 | +1.16 | +0.32 |
| 09:53 | APP | laggards | down | +0.27 | +0.35 | +0.22 |
| 09:59 | HIMS | laggards | down | -0.11 | +0.96 | +0.47 |
| 10:01 | FLNC | leaders | up | -1.48 | -1.79 | -1.66 |
| 10:02 | HUM | laggards | down | -0.47 | +0.33 | -0.91 |
| 10:03 | CVS | laggards | down | -0.52 | -0.75 | -0.49 |
| 10:09 | CIEN | leaders | up | +1.94 | +3.07 | +3.19 |
| 10:17 | AMGN | laggards | down | -0.04 | +1.22 | +1.11 |
| 10:33 | INTC | laggards | down | +0.19 | -0.65 | -1.23 |
| 10:39 | CIFR | laggards | down | +1.85 | +1.96 | +1.72 |
| 10:45 | CLSK | laggards | down | +1.54 | +1.05 | +0.30 |
| 10:47 | RIOT | laggards | down | +1.77 | +1.52 | +1.37 |
| 11:44 | CRWV | leaders | up | -0.61 | +0.17 | +0.93 |
| 11:48 | AVGO | leaders | up | +0.12 | +0.18 | +0.79 |
| 12:10 | NET | laggards | down | +0.30 | +0.44 | +1.22 |
| 12:28 | MARA | laggards | down | +0.37 | +0.34 | -0.11 |
| 12:31 | CRM | laggards | down | -0.26 | -0.29 | -0.76 |
| 13:40 | CVNA | laggards | down | +0.44 | +0.45 | +1.25 |
| 14:21 | HOOD | laggards | down | -0.56 | -0.48 | — |
| 15:12 | SNAP | leaders | up | -1.16 | — | — |
| 15:24 | COIN | laggards | down | +0.05 | — | — |
| 15:25 | ANET | leaders | up | -0.04 | — | — |

## 2026-10-07

Usable symbol-minutes 64,173/65,910. No usable minutes: TCEHY, WBD. Daily ranking covers 144/146 stocks. Excluded: TCEHY, WBD.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | BULL | -18.85 | miss | 09:31 |
| 2 | MSTR | -6.55 | miss | 09:31 |
| 3 | LCID | -6.25 | miss | 14:00 |
| 4 | IREN | -6.03 | miss | 11:11 |
| 5 | CLSK | -6.03 | miss | 09:35 |
| 6 | CIFR | -5.82 | miss | 11:01 |
| 7 | APLD | -5.80 | miss | 10:25 |
| 8 | AAOI | -5.61 | miss | 09:38 |
| 9 | CAT | -5.51 | miss | 09:58 |
| 10 | MARA | -5.32 | miss | 09:35 |
| 11 | SPOT | +5.32 | miss | 09:36 |
| 12 | NBIS | -4.85 | miss | 09:31 |
| 13 | CRWD | -4.57 | miss | miss |
| 14 | MU | +4.30 | miss | 10:26 |
| 15 | IONQ | -4.26 | miss | 13:38 |
| 16 | OKLO | -4.25 | miss | 09:31 |
| 17 | FLNC | -4.24 | miss | 09:31 |
| 18 | PL | -4.18 | miss | 09:32 |
| 19 | LUNR | -4.08 | miss | 09:33 |
| 20 | RKLB | -3.94 | miss | miss |

### Radar flags (0)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| — | No flags | — | — | — | — | — |

### Movers flags (60)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | CI | leaders | up | -0.30 | +0.04 | -0.04 |
| 09:31 | COP | leaders | up | -0.38 | -0.79 | -1.46 |
| 09:31 | U | leaders | up | -1.74 | -2.41 | -2.05 |
| 09:31 | AAPL | leaders | up | -0.64 | -0.50 | -0.52 |
| 09:31 | CVS | leaders | up | +0.69 | +1.83 | +1.44 |
| 09:31 | LLY | leaders | up | +1.31 | +1.56 | +2.83 |
| 09:31 | NOW | leaders | up | -0.97 | -0.97 | -0.77 |
| 09:31 | XOM | leaders | up | -0.31 | -0.65 | -1.11 |
| 09:31 | HUM | leaders | up | -0.69 | -1.17 | -1.54 |
| 09:31 | OXY | leaders | up | -0.41 | -0.76 | -1.35 |
| 09:31 | BULL | laggards | down | +2.71 | +2.95 | +2.70 |
| 09:31 | ALAB | laggards | down | +0.23 | +1.10 | +1.17 |
| 09:31 | OKLO | laggards | down | -0.01 | -0.19 | -0.90 |
| 09:31 | CRCL | laggards | down | +0.14 | -0.30 | -0.05 |
| 09:31 | CIEN | laggards | down | +2.77 | +3.60 | +3.58 |
| 09:31 | MSTR | laggards | down | -0.55 | -1.24 | -1.74 |
| 09:31 | FLNC | laggards | down | -2.62 | -2.57 | -2.39 |
| 09:31 | CRDO | laggards | down | -0.11 | +0.99 | +0.83 |
| 09:31 | NBIS | laggards | down | +0.09 | -0.74 | -2.25 |
| 09:31 | COHR | laggards | down | -0.89 | -0.59 | -0.77 |
| 09:32 | CVX | leaders | up | -1.03 | -1.59 | -1.94 |
| 09:32 | PL | laggards | down | -2.18 | -0.89 | -1.83 |
| 09:32 | ASTS | laggards | down | -1.88 | -2.47 | -2.81 |
| 09:33 | PFE | leaders | up | +0.80 | +0.62 | +1.28 |
| 09:33 | LUNR | laggards | down | -1.29 | -0.73 | -1.98 |
| 09:33 | RCAT | laggards | down | -0.49 | -0.60 | -0.88 |
| 09:34 | INTC | leaders | up | -0.23 | +0.23 | -0.29 |
| 09:34 | HPQ | leaders | up | -0.08 | -0.39 | +0.24 |
| 09:34 | SMCI | leaders | up | +0.08 | -0.35 | +0.35 |
| 09:35 | MDB | leaders | up | -1.66 | -1.04 | -1.46 |
| 09:35 | PLTR | leaders | up | -1.40 | -2.00 | -1.51 |
| 09:35 | MARA | laggards | down | +0.27 | -0.53 | -2.22 |
| 09:35 | CLSK | laggards | down | +0.41 | -0.39 | -1.89 |
| 09:35 | RIOT | laggards | down | +1.31 | +0.57 | -0.36 |
| 09:36 | AMGN | leaders | up | +1.95 | +1.50 | +1.88 |
| 09:36 | SPOT | leaders | up | +0.17 | +0.66 | +2.49 |
| 09:38 | PINS | leaders | up | -1.01 | -0.88 | -0.04 |
| 09:38 | AAOI | laggards | down | -1.30 | -1.29 | -1.43 |
| 09:41 | MA | leaders | up | -0.17 | -0.06 | -0.15 |
| 09:43 | DELL | leaders | up | +0.48 | -0.25 | -0.24 |
| 09:44 | NVO | leaders | up | -0.25 | +0.31 | +0.93 |
| 09:45 | CNC | leaders | up | -0.03 | +0.01 | -0.89 |
| 09:58 | CAT | laggards | down | -0.20 | -1.18 | -1.24 |
| 10:01 | WMT | leaders | up | +0.31 | +0.53 | +0.40 |
| 10:02 | COST | leaders | up | -0.09 | +0.27 | +0.30 |
| 10:09 | MRK | leaders | up | +0.01 | -0.18 | +0.24 |
| 10:17 | ELV | leaders | up | -0.02 | -0.03 | -0.25 |
| 10:19 | SNDK | leaders | up | +2.07 | +2.16 | +2.54 |
| 10:20 | SNOW | leaders | up | -0.65 | -1.12 | -0.99 |
| 10:25 | APLD | laggards | down | +0.02 | -1.37 | -1.21 |
| 10:26 | MU | leaders | up | +0.60 | +1.06 | +1.89 |
| 10:49 | DE | laggards | down | +1.29 | +1.78 | +2.06 |
| 10:52 | UNH | leaders | up | -0.35 | -0.53 | -0.35 |
| 11:01 | CIFR | laggards | down | -0.34 | -0.35 | -0.96 |
| 11:11 | IREN | laggards | down | +0.11 | -0.44 | -0.33 |
| 11:48 | RDDT | leaders | up | -0.29 | +0.17 | +0.99 |
| 13:38 | IONQ | laggards | down | +0.59 | +0.98 | +0.69 |
| 14:00 | LCID | laggards | down | -0.29 | -1.83 | -0.37 |
| 15:18 | RBLX | leaders | up | -0.39 | — | — |
| 15:33 | JD | leaders | up | — | — | — |

## 2026-10-08

Usable symbol-minutes 64,283/65,910. No usable minutes: TCEHY, WBD. Daily ranking covers 144/146 stocks. Excluded: TCEHY, WBD.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | AAOI | -13.16 | miss | 09:31 |
| 2 | COHR | -9.20 | miss | 09:31 |
| 3 | ALAB | -8.79 | miss | 12:51 |
| 4 | RIOT | -8.75 | miss | 09:33 |
| 5 | CRWV | -7.34 | miss | 09:31 |
| 6 | CLSK | -7.30 | miss | 09:34 |
| 7 | IREN | -7.28 | miss | 09:31 |
| 8 | NBIS | -6.93 | miss | 09:40 |
| 9 | CIFR | -6.86 | miss | 09:31 |
| 10 | ARM | -6.06 | miss | 09:31 |
| 11 | ASTS | -5.71 | miss | 09:47 |
| 12 | OKLO | -5.69 | miss | 10:54 |
| 13 | ORCL | -5.06 | miss | miss |
| 14 | INTC | -4.92 | miss | 09:31 |
| 15 | WULF | -4.79 | miss | 09:32 |
| 16 | HIMS | -4.59 | miss | 10:28 |
| 17 | LUNR | -4.50 | miss | 10:06 |
| 18 | SNDK | -4.48 | miss | miss |
| 19 | RKLB | -4.47 | miss | miss |
| 20 | LOW | +4.45 | miss | 12:44 |

### Radar flags (6)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | Bitcoin treasuries and miners (RIOT, CLSK, MARA, IREN, MSTR, COIN) | group_move | down | +1.16 | +0.64 | -1.06 |
| 10:02 | Neoclouds and AI hosting (APLD, CIFR, IREN, NBIS, WULF, CRWV, ORCL) | group_move | down | +1.03 | +0.24 | -0.43 |
| 10:02 | Quantum computing (IONQ, RGTI, QBTS, QUBT) | group_move | down | +0.27 | -0.21 | -1.18 |
| 10:02 | Space (ASTS, LUNR, PL, RKLB) | group_move | down | +0.27 | +0.05 | -1.88 |
| 12:52 | Neoclouds and AI hosting (ORCL, CRWV, NBIS, CIFR, IREN, APLD, WULF) | group_move | down | -0.26 | +0.24 | +0.87 |
| 12:55 | AI networking and connectivity (ALAB, CRDO, MRVL, COHR, AVGO, ANET) | group_move | down | -0.59 | +0.12 | -0.09 |

### Movers flags (61)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | SHEL | leaders | up | +0.11 | +0.59 | +0.62 |
| 09:31 | OXY | leaders | up | -0.15 | -0.19 | +0.24 |
| 09:31 | BULL | leaders | up | -4.83 | -2.46 | -3.74 |
| 09:31 | PLTR | leaders | up | +1.38 | +0.59 | +0.48 |
| 09:31 | CVX | leaders | up | +0.34 | +0.47 | +0.82 |
| 09:31 | COP | leaders | up | +0.21 | +0.40 | +1.01 |
| 09:31 | U | leaders | up | +0.42 | +0.07 | -0.60 |
| 09:31 | XOM | leaders | up | +0.38 | +0.21 | +0.90 |
| 09:31 | GOOGL | leaders | up | -1.32 | -1.24 | -1.43 |
| 09:31 | NOW | leaders | up | -0.34 | -1.34 | -2.70 |
| 09:31 | AAOI | laggards | down | -0.08 | +0.14 | -4.72 |
| 09:31 | COHR | laggards | down | +0.18 | +0.79 | -1.77 |
| 09:31 | ARM | laggards | down | -0.82 | +0.28 | -0.10 |
| 09:31 | CRWV | laggards | down | -1.55 | -0.48 | -1.68 |
| 09:31 | INTC | laggards | down | -0.47 | +1.40 | +0.03 |
| 09:31 | CIFR | laggards | down | -3.32 | -2.95 | -4.93 |
| 09:31 | CRDO | laggards | down | +1.72 | +3.79 | +1.30 |
| 09:31 | IREN | laggards | down | -2.88 | -2.12 | -3.50 |
| 09:31 | MRVL | laggards | down | +0.07 | +0.61 | -0.27 |
| 09:31 | CIEN | laggards | down | +1.27 | +1.11 | -0.14 |
| 09:32 | BABA | leaders | up | -1.61 | -2.37 | -2.65 |
| 09:32 | APLD | leaders | up | -3.92 | -2.88 | -2.84 |
| 09:32 | WULF | laggards | down | -1.97 | -1.23 | -3.74 |
| 09:33 | ADBE | leaders | up | -0.34 | -1.13 | -1.73 |
| 09:33 | RIOT | laggards | down | -3.27 | -1.98 | -5.05 |
| 09:33 | SMCI | laggards | down | +0.04 | +0.46 | -1.47 |
| 09:34 | CLSK | laggards | down | -2.81 | -2.50 | -4.13 |
| 09:36 | APP | laggards | down | +0.82 | +1.69 | +1.49 |
| 09:37 | LYFT | leaders | up | -0.72 | -0.06 | -0.83 |
| 09:38 | SPOT | leaders | up | -0.46 | +0.03 | -0.78 |
| 09:38 | MARA | laggards | down | -0.15 | -0.26 | -1.29 |
| 09:39 | HOOD | laggards | down | +0.94 | +2.28 | +1.91 |
| 09:39 | MSTR | laggards | down | +1.52 | +2.43 | +0.82 |
| 09:40 | NBIS | laggards | down | -0.68 | +0.47 | -1.21 |
| 09:45 | NFLX | leaders | up | +0.78 | +0.71 | +0.82 |
| 09:46 | WMT | leaders | up | +0.22 | +0.32 | +0.89 |
| 09:46 | PL | laggards | down | -0.03 | +0.47 | -1.98 |
| 09:47 | ASTS | laggards | down | -1.32 | -0.87 | -2.62 |
| 09:49 | TTWO | leaders | up | +0.38 | +0.69 | +1.80 |
| 09:50 | CRWD | leaders | up | +0.23 | -0.01 | -1.18 |
| 09:51 | SNOW | leaders | up | +0.39 | +0.91 | +1.07 |
| 09:51 | DDOG | leaders | up | +0.19 | +0.62 | +0.94 |
| 10:03 | ZS | leaders | up | +0.04 | -0.12 | +0.61 |
| 10:06 | LUNR | laggards | down | +0.30 | -0.28 | -1.77 |
| 10:14 | RDDT | leaders | up | +0.88 | +0.76 | +0.69 |
| 10:20 | HUM | laggards | down | +0.27 | -0.25 | +0.86 |
| 10:21 | LLY | laggards | down | -0.05 | +0.34 | -0.08 |
| 10:25 | RBLX | laggards | down | +1.29 | +1.13 | +1.46 |
| 10:28 | HIMS | laggards | down | -0.05 | -0.09 | -2.16 |
| 10:54 | OKLO | laggards | down | -1.15 | -2.56 | -3.31 |
| 10:59 | LCID | laggards | down | +0.61 | +0.14 | +0.55 |
| 11:10 | MDB | leaders | up | -0.66 | -0.70 | -1.08 |
| 11:26 | FLNC | laggards | down | +1.04 | +0.86 | -1.09 |
| 11:30 | TGT | leaders | up | +0.35 | +0.63 | +1.65 |
| 12:33 | ONON | leaders | up | +0.20 | +0.48 | +0.54 |
| 12:44 | LOW | leaders | up | +0.95 | +1.93 | +1.58 |
| 12:51 | ALAB | laggards | down | -1.57 | -0.42 | -0.20 |
| 12:53 | HD | leaders | up | +0.71 | +1.07 | +0.82 |
| 13:45 | DECK | leaders | up | -0.20 | -0.06 | -0.38 |
| 13:59 | CPRT | leaders | up | -0.52 | -0.03 | +0.16 |
| 15:50 | IBM | leaders | up | — | — | — |

## 2026-10-09

Usable symbol-minutes 64,102/65,910. No usable minutes: TCEHY, WBD. Daily ranking covers 144/146 stocks. Excluded: TCEHY, WBD.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | ASTS | -11.08 | 10:02 | 09:31 |
| 2 | HUM | +10.96 | miss | 09:31 |
| 3 | HIMS | +9.59 | miss | 09:42 |
| 4 | HPQ | -7.50 | miss | 09:31 |
| 5 | ZS | +7.20 | miss | 09:31 |
| 6 | SNOW | +6.82 | miss | 10:02 |
| 7 | DDOG | +6.51 | miss | 12:14 |
| 8 | SNAP | +5.71 | miss | 09:32 |
| 9 | BULL | +5.45 | miss | 09:31 |
| 10 | DE | -5.45 | miss | 12:17 |
| 11 | RBLX | +5.05 | 10:02 | 09:43 |
| 12 | CIEN | +5.00 | miss | 09:31 |
| 13 | NET | +4.97 | miss | 09:34 |
| 14 | BABA | +4.76 | miss | 09:31 |
| 15 | PLTR | +4.57 | miss | miss |
| 16 | PANW | +4.49 | miss | miss |
| 17 | LUNR | -4.32 | miss | 09:46 |
| 18 | CRWD | +3.97 | miss | miss |
| 19 | CRCL | +3.94 | 10:27 | 10:10 |
| 20 | ARM | -3.87 | miss | 09:47 |

### Radar flags (11)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | ASTS | relative_to_spy | down | -0.99 | -0.96 | -7.08 |
| 10:02 | COHR | relative_to_spy | down | +1.07 | +1.31 | +0.52 |
| 10:02 | CRDO | relative_to_spy | down | +1.63 | +2.30 | +0.28 |
| 10:02 | RBLX | relative_to_spy | up | +0.05 | +0.45 | +1.27 |
| 10:02 | AI networking and connectivity (COHR, CRDO, ALAB, MRVL, AVGO, ANET) | group_move | down | +0.74 | +0.94 | +0.24 |
| 10:02 | Space (ASTS, PL, LUNR, RKLB, IRDM) | group_move | down | -0.06 | +0.09 | — |
| 10:12 | AAOI | relative_to_spy | down | +0.82 | +3.70 | +2.06 |
| 10:14 | HUM | relative_to_sector | down | +0.04 | +0.19 | +0.25 |
| 10:18 | HUM | relative_to_spy | down | +0.77 | +1.32 | +1.18 |
| 10:27 | CRCL | relative_to_sector | up | -0.62 | -0.65 | -0.26 |
| 10:30 | CRCL | relative_to_spy | up | -1.42 | -1.43 | -1.00 |

### Movers flags (61)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | HUM | leaders | up | +0.06 | -1.35 | -0.64 |
| 09:31 | AAOI | leaders | up | -4.26 | -2.37 | -2.79 |
| 09:31 | COHR | leaders | up | -5.34 | -4.83 | -4.68 |
| 09:31 | CRDO | leaders | up | -4.85 | -4.14 | -4.32 |
| 09:31 | CIEN | leaders | up | -3.51 | -0.60 | -0.24 |
| 09:31 | BABA | leaders | up | +1.37 | +0.90 | +1.39 |
| 09:31 | BULL | leaders | up | -0.19 | +1.11 | +4.75 |
| 09:31 | HSAI | leaders | up | +0.43 | — | — |
| 09:31 | RDDT | leaders | up | -0.59 | +0.13 | -0.69 |
| 09:31 | ZS | leaders | up | +0.31 | +1.58 | +2.33 |
| 09:31 | HPQ | laggards | down | -1.22 | -2.45 | -2.63 |
| 09:31 | ASTS | laggards | down | -6.32 | -7.33 | -12.42 |
| 09:31 | AAPL | laggards | down | -0.05 | +0.08 | +0.52 |
| 09:31 | AXP | laggards | down | +1.18 | +0.87 | +1.18 |
| 09:31 | CVS | laggards | down | -0.19 | -0.56 | -0.10 |
| 09:31 | NKE | laggards | down | +0.81 | +1.21 | +1.77 |
| 09:31 | NFLX | laggards | down | +0.68 | +0.82 | -0.07 |
| 09:31 | KMX | laggards | down | -0.14 | -0.32 | -0.88 |
| 09:31 | OXY | laggards | down | +1.73 | +1.41 | +1.51 |
| 09:31 | DASH | laggards | down | +1.93 | +2.03 | +1.87 |
| 09:32 | DELL | leaders | up | -2.24 | -2.38 | -2.65 |
| 09:32 | ANET | leaders | up | -0.38 | -0.65 | -0.25 |
| 09:32 | SNAP | leaders | up | +1.14 | +2.05 | +4.29 |
| 09:32 | APLD | laggards | down | -0.35 | +0.29 | -1.37 |
| 09:32 | UAA | laggards | down | +1.82 | +1.21 | +1.85 |
| 09:32 | RCAT | laggards | down | -2.00 | -0.89 | -1.31 |
| 09:33 | ORCL | leaders | up | -0.55 | +1.47 | +1.17 |
| 09:33 | CLSK | laggards | down | +0.18 | +1.19 | +0.73 |
| 09:33 | CIFR | laggards | down | +0.24 | +0.15 | +0.38 |
| 09:33 | MARA | laggards | down | -0.97 | -0.29 | -0.75 |
| 09:34 | NET | leaders | up | -0.92 | -1.20 | +0.08 |
| 09:34 | PL | laggards | down | -1.06 | -0.97 | -1.19 |
| 09:34 | LAD | laggards | down | +1.32 | +0.99 | — |
| 09:36 | ELV | leaders | up | -0.79 | -0.43 | +0.01 |
| 09:36 | ALAB | laggards | down | -0.94 | +0.23 | -0.30 |
| 09:37 | QCOM | laggards | down | +1.30 | +1.01 | +0.73 |
| 09:38 | UNH | leaders | up | -1.45 | -1.68 | -2.22 |
| 09:38 | RKLB | laggards | down | +0.84 | +0.35 | -0.00 |
| 09:40 | CNC | leaders | up | -0.81 | -1.38 | -1.75 |
| 09:42 | HIMS | leaders | up | +1.22 | +0.43 | +1.16 |
| 09:43 | RBLX | leaders | up | +2.13 | +3.14 | +3.53 |
| 09:43 | SMCI | laggards | down | -0.80 | -1.95 | -1.28 |
| 09:46 | LUNR | laggards | down | +0.34 | +0.21 | -1.90 |
| 09:47 | ARM | laggards | down | -0.10 | -0.27 | -0.76 |
| 09:49 | PINS | leaders | up | -0.81 | -0.58 | +0.62 |
| 09:52 | TSLA | leaders | up | -0.61 | -0.20 | -1.63 |
| 09:52 | MRVL | laggards | down | +0.08 | +0.05 | +0.62 |
| 09:59 | FND | laggards | down | -1.19 | -0.77 | -1.40 |
| 10:01 | PDD | leaders | up | -0.15 | -0.05 | +0.67 |
| 10:02 | SNOW | leaders | up | +1.02 | +0.87 | +1.32 |
| 10:10 | CRCL | leaders | up | +2.82 | +1.61 | +3.12 |
| 10:16 | COIN | leaders | up | +1.30 | -0.06 | +1.43 |
| 10:17 | MSTR | leaders | up | -0.78 | -1.42 | -0.24 |
| 10:24 | LOW | laggards | down | -0.33 | -0.21 | -0.26 |
| 11:15 | RGTI | laggards | down | -0.33 | +0.01 | -0.04 |
| 12:14 | DDOG | leaders | up | +1.35 | +1.70 | +1.46 |
| 12:17 | DE | laggards | down | -1.16 | -0.88 | -1.09 |
| 12:54 | RIVN | laggards | down | -0.51 | -0.12 | -0.06 |
| 14:06 | IREN | laggards | down | -0.19 | -0.01 | — |
| 15:40 | INTC | laggards | down | — | — | — |
| 15:55 | AMD | laggards | down | — | — | — |

## 2026-10-12

Usable symbol-minutes 64,093/65,910. No usable minutes: TCEHY, WBD. Daily ranking covers 144/146 stocks. Excluded: TCEHY, WBD.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | CIEN | -9.89 | miss | 09:33 |
| 2 | LCID | -9.31 | miss | 09:31 |
| 3 | IONQ | -9.01 | 10:08 | 09:31 |
| 4 | AAOI | -8.11 | miss | 09:31 |
| 5 | COHR | -7.81 | miss | 09:31 |
| 6 | CRDO | -7.19 | miss | 09:31 |
| 7 | OKLO | -7.12 | miss | 09:35 |
| 8 | PL | -7.04 | miss | 14:12 |
| 9 | QUBT | -6.79 | miss | 10:02 |
| 10 | CVNA | -6.56 | miss | 15:29 |
| 11 | RCAT | -6.53 | miss | 15:27 |
| 12 | SNDK | -5.91 | miss | 09:31 |
| 13 | QBTS | -5.64 | miss | 09:58 |
| 14 | RGTI | -5.50 | miss | 09:56 |
| 15 | HSAI | -5.50 | miss | 09:31 |
| 16 | ALAB | -5.23 | miss | 09:31 |
| 17 | NBIS | -4.92 | miss | 09:31 |
| 18 | SNAP | +4.88 | miss | 09:31 |
| 19 | FLNC | -4.78 | miss | miss |
| 20 | SMCI | -4.42 | miss | 09:33 |

### Radar flags (4)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:08 | IONQ | relative_to_spy | down | +0.58 | -0.48 | +0.62 |
| 10:08 | AI software and analytics (AI, APP, NOW, SNOW, PLTR, DDOG) | group_move | down | -0.75 | -0.39 | -1.14 |
| 10:08 | Quantum computing (IONQ, RGTI, QUBT, QBTS) | group_move | down | +0.39 | -0.20 | -0.18 |
| 10:12 | AI | relative_to_spy | down | -1.53 | -0.91 | -2.31 |

### Movers flags (49)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | AI | leaders | up | +0.30 | -2.80 | -1.87 |
| 09:31 | ASTS | leaders | up | +0.19 | +1.09 | +0.43 |
| 09:31 | NOW | leaders | up | -1.42 | -2.29 | -2.55 |
| 09:31 | CRM | leaders | up | -0.54 | -0.29 | -0.68 |
| 09:31 | META | leaders | up | +0.29 | +1.03 | +1.05 |
| 09:31 | SNAP | leaders | up | +0.25 | +1.83 | +0.87 |
| 09:31 | IREN | leaders | up | -0.56 | -0.15 | -0.97 |
| 09:31 | COP | leaders | up | +0.38 | -0.01 | +0.44 |
| 09:31 | SHEL | leaders | up | +0.28 | -0.09 | +0.13 |
| 09:31 | DDOG | leaders | up | -2.17 | -2.43 | -2.68 |
| 09:31 | AAOI | laggards | down | -1.30 | -2.17 | -3.27 |
| 09:31 | LCID | laggards | down | +0.09 | -2.86 | -4.81 |
| 09:31 | CRDO | laggards | down | -0.91 | -2.00 | -2.08 |
| 09:31 | ALAB | laggards | down | +1.06 | +0.72 | -0.21 |
| 09:31 | MU | laggards | down | -0.28 | -0.45 | +0.20 |
| 09:31 | NBIS | laggards | down | -0.37 | -0.96 | -1.84 |
| 09:31 | COHR | laggards | down | -0.42 | -1.53 | -4.08 |
| 09:31 | SNDK | laggards | down | -2.90 | -3.41 | -2.53 |
| 09:31 | IONQ | laggards | down | -3.57 | -5.76 | -5.93 |
| 09:31 | HSAI | laggards | down | -2.30 | -4.02 | -2.61 |
| 09:32 | APP | leaders | up | -2.20 | -2.68 | -1.81 |
| 09:32 | CVX | leaders | up | +0.25 | -0.24 | -0.07 |
| 09:32 | XOM | leaders | up | +0.47 | +0.12 | +0.38 |
| 09:33 | AAPL | leaders | up | -0.02 | -0.11 | -0.62 |
| 09:33 | CIEN | laggards | down | -1.22 | -1.81 | -4.81 |
| 09:33 | SMCI | laggards | down | +0.82 | -0.04 | -1.41 |
| 09:34 | MSTR | leaders | up | +0.08 | -0.63 | -1.59 |
| 09:35 | OKLO | laggards | down | -0.37 | -1.12 | -1.03 |
| 09:37 | HIMS | leaders | up | -0.13 | -0.32 | -1.33 |
| 09:48 | OXY | leaders | up | -0.14 | -0.43 | -0.32 |
| 09:56 | COIN | leaders | up | -0.46 | -1.22 | -1.06 |
| 09:56 | RGTI | laggards | down | -0.32 | +0.03 | -0.43 |
| 09:58 | QBTS | laggards | down | -0.45 | -0.19 | -1.06 |
| 10:02 | QUBT | laggards | down | -1.02 | -1.08 | -1.67 |
| 10:10 | ELV | leaders | up | +0.00 | -0.17 | -0.01 |
| 10:14 | DE | leaders | up | +0.30 | +0.17 | -0.26 |
| 10:14 | RDDT | laggards | down | -0.24 | +0.09 | +0.80 |
| 10:31 | CNC | leaders | up | -0.10 | +0.23 | +0.52 |
| 10:33 | MRVL | laggards | down | +0.98 | +0.88 | +2.34 |
| 10:36 | PCAR | leaders | up | -0.33 | -0.16 | -0.37 |
| 10:38 | URI | leaders | up | +0.14 | +0.18 | -0.44 |
| 10:40 | CVS | leaders | up | -0.34 | -0.44 | -0.20 |
| 13:21 | RBLX | leaders | up | +0.20 | +1.54 | +1.60 |
| 14:12 | PL | laggards | down | -0.35 | -0.52 | — |
| 14:33 | MA | leaders | up | -0.16 | -0.48 | — |
| 15:13 | TDOC | leaders | up | +1.21 | — | — |
| 15:27 | RCAT | laggards | down | -0.44 | — | — |
| 15:29 | CVNA | laggards | down | -0.75 | — | — |
| 15:44 | NKE | leaders | up | — | — | — |

## 2026-10-13

Usable symbol-minutes 64,392/65,910. No usable minutes: TCEHY, WBD. Daily ranking covers 144/146 stocks. Excluded: TCEHY, WBD.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | CIFR | -12.76 | miss | 09:31 |
| 2 | ASTS | -8.53 | miss | 09:31 |
| 3 | S | -6.42 | miss | 09:31 |
| 4 | C | -5.59 | miss | 14:07 |
| 5 | LUNR | -5.28 | miss | 10:15 |
| 6 | PL | -5.00 | miss | 10:21 |
| 7 | PINS | +4.45 | miss | 09:54 |
| 8 | HSAI | -4.35 | miss | 09:38 |
| 9 | ORCL | +4.24 | miss | 09:49 |
| 10 | IONQ | -4.23 | miss | 12:16 |
| 11 | FLNC | -4.09 | miss | 10:01 |
| 12 | TTWO | -4.06 | miss | 10:10 |
| 13 | RCAT | -3.79 | miss | 12:30 |
| 14 | MU | -3.61 | miss | 09:31 |
| 15 | RGTI | -3.54 | miss | miss |
| 16 | MARA | -3.48 | miss | miss |
| 17 | APLD | -3.47 | miss | 09:31 |
| 18 | AI | +3.46 | miss | 09:48 |
| 19 | CAT | -3.31 | miss | 11:27 |
| 20 | WFC | -3.08 | miss | miss |

### Radar flags (5)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | MDB | relative_to_spy | up | -1.96 | -3.02 | -3.59 |
| 10:02 | Managed care (UNH, HUM, CVS, CI, CNC, ELV) | group_move | down | -0.78 | -0.09 | +0.91 |
| 10:04 | Big banks (JPM, C, WFC, GS, MS, BAC) | group_move | down | +0.67 | +1.06 | +0.55 |
| 10:05 | HIMS | relative_to_sector | up | -0.18 | -0.37 | -0.57 |
| 10:13 | HUM | relative_to_spy | down | +1.42 | +1.02 | +2.36 |

### Movers flags (71)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | UNH | leaders | up | -4.32 | -4.87 | -4.17 |
| 09:31 | GS | leaders | up | -1.94 | -1.10 | -1.23 |
| 09:31 | JPM | leaders | up | -2.33 | -1.71 | -0.78 |
| 09:31 | FND | leaders | up | -1.81 | -1.68 | -0.97 |
| 09:31 | AAPL | leaders | up | -0.46 | -0.09 | -0.30 |
| 09:31 | CNC | leaders | up | -1.38 | -2.34 | -0.32 |
| 09:31 | LOW | leaders | up | -1.24 | -0.56 | -0.53 |
| 09:31 | CVS | leaders | up | -2.63 | -2.75 | -1.86 |
| 09:31 | MSFT | leaders | up | +0.06 | -0.04 | -0.32 |
| 09:31 | DECK | leaders | up | -1.63 | -0.80 | -0.82 |
| 09:31 | CIFR | laggards | down | -2.94 | -2.08 | -0.82 |
| 09:31 | STX | laggards | down | +1.61 | +3.01 | +3.87 |
| 09:31 | ASTS | laggards | down | -2.17 | -3.27 | -1.84 |
| 09:31 | WDC | laggards | down | +0.39 | +2.42 | +2.83 |
| 09:31 | CRDO | laggards | down | +0.43 | -1.00 | -1.93 |
| 09:31 | ALAB | laggards | down | +1.38 | +2.43 | +1.53 |
| 09:31 | S | laggards | down | +3.54 | +3.26 | +3.10 |
| 09:31 | MU | laggards | down | +0.85 | +0.96 | -0.00 |
| 09:31 | APLD | laggards | down | -2.52 | -0.24 | -0.36 |
| 09:31 | ANET | laggards | down | +2.02 | +0.35 | -0.55 |
| 09:32 | ELV | leaders | up | -1.60 | -2.37 | -1.88 |
| 09:32 | CI | leaders | up | -3.43 | -3.19 | -2.15 |
| 09:32 | HUM | leaders | up | -4.13 | -6.71 | -5.24 |
| 09:32 | HPQ | leaders | up | +1.28 | +1.44 | +1.08 |
| 09:32 | MRVL | laggards | down | +4.13 | +3.60 | +3.52 |
| 09:33 | UAA | leaders | up | -3.29 | -3.17 | -3.12 |
| 09:33 | NOW | leaders | up | +0.15 | -0.33 | -0.30 |
| 09:34 | CRM | leaders | up | +2.42 | +0.40 | +0.86 |
| 09:34 | WULF | laggards | down | +0.50 | +0.23 | +1.16 |
| 09:35 | ZS | leaders | up | +1.62 | +0.40 | +0.30 |
| 09:35 | HIMS | laggards | down | +4.30 | +4.12 | +4.01 |
| 09:36 | TDOC | leaders | up | -2.52 | -2.57 | -0.04 |
| 09:36 | MDB | leaders | up | +4.42 | +2.67 | +1.24 |
| 09:37 | IREN | laggards | down | +0.40 | +2.48 | +2.98 |
| 09:38 | IBM | leaders | up | +0.51 | +0.21 | +0.87 |
| 09:38 | HSAI | laggards | down | +0.17 | -0.19 | +0.81 |
| 09:38 | NBIS | laggards | down | +0.74 | +1.54 | +1.42 |
| 09:41 | FTNT | leaders | up | -1.66 | -1.95 | -2.72 |
| 09:42 | MSTR | leaders | up | +0.19 | +0.11 | -1.04 |
| 09:42 | SNOW | leaders | up | -1.03 | -1.63 | -2.13 |
| 09:42 | CLSK | laggards | down | +0.94 | +0.76 | +0.56 |
| 09:45 | CRWD | leaders | up | -0.81 | -1.34 | -1.88 |
| 09:46 | APP | leaders | up | -0.71 | -0.95 | -1.27 |
| 09:47 | META | leaders | up | +1.14 | +1.54 | +0.82 |
| 09:48 | AI | leaders | up | -1.11 | -1.05 | -0.20 |
| 09:49 | ORCL | leaders | up | -0.34 | -0.59 | -0.87 |
| 09:51 | SNAP | leaders | up | +2.88 | +1.08 | +0.62 |
| 09:51 | DDOG | leaders | up | -1.24 | -2.49 | -2.78 |
| 09:53 | QCOM | leaders | up | -0.38 | -0.42 | -0.30 |
| 09:54 | PINS | leaders | up | +0.90 | +0.15 | +1.52 |
| 10:01 | FLNC | laggards | down | +0.73 | -0.32 | -1.18 |
| 10:10 | TTWO | laggards | down | +1.73 | +1.48 | +1.36 |
| 10:12 | HUM | laggards | down | +0.71 | +1.28 | +2.59 |
| 10:13 | RDDT | leaders | up | -0.57 | -0.54 | -1.76 |
| 10:15 | LUNR | laggards | down | -1.33 | -1.42 | -1.29 |
| 10:19 | PDD | leaders | up | +1.12 | +1.38 | -0.02 |
| 10:21 | PL | laggards | down | -0.39 | -0.16 | +0.14 |
| 10:48 | COP | leaders | up | +0.07 | +0.46 | +0.11 |
| 11:10 | GM | leaders | up | +0.23 | +0.12 | +0.56 |
| 11:12 | LYFT | leaders | up | +0.07 | -0.29 | -0.21 |
| 11:25 | HOOD | leaders | up | -0.31 | -0.41 | -0.51 |
| 11:27 | CAT | laggards | down | -0.43 | -0.24 | +0.04 |
| 11:38 | AAOI | laggards | down | +1.20 | +2.04 | +0.94 |
| 12:16 | IONQ | laggards | down | +0.73 | +0.16 | -0.22 |
| 12:30 | RCAT | laggards | down | +0.40 | +0.33 | +0.41 |
| 12:56 | DE | leaders | up | -0.02 | +0.21 | +0.47 |
| 14:07 | C | laggards | down | -0.11 | -0.06 | — |
| 14:47 | CVNA | leaders | up | -0.48 | -0.61 | — |
| 15:09 | CRWV | laggards | down | -0.06 | — | — |
| 15:51 | RIOT | leaders | up | — | — | — |
| 15:59 | AMD | leaders | up | — | — | — |

## 2026-10-14

Usable symbol-minutes 64,468/65,910. No usable minutes: TCEHY, WBD. Daily ranking covers 144/146 stocks. Excluded: TCEHY, WBD.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | CRWV | -14.38 | 10:02 | 09:31 |
| 2 | WULF | -11.56 | miss | 09:31 |
| 3 | CIFR | -11.26 | miss | 09:31 |
| 4 | IREN | -11.10 | miss | 09:31 |
| 5 | AAOI | -10.74 | miss | 11:27 |
| 6 | DELL | -10.19 | miss | 09:31 |
| 7 | U | -10.13 | miss | 09:31 |
| 8 | ASTS | -9.38 | miss | 09:33 |
| 9 | CIEN | -9.11 | miss | 15:08 |
| 10 | QBTS | -9.01 | miss | 09:31 |
| 11 | NBIS | -9.00 | miss | 09:31 |
| 12 | MARA | -8.58 | miss | miss |
| 13 | CRDO | -8.54 | miss | miss |
| 14 | IONQ | -8.45 | miss | 09:32 |
| 15 | LUNR | -8.44 | miss | miss |
| 16 | APLD | -8.34 | miss | 09:35 |
| 17 | RIOT | -8.34 | miss | 13:46 |
| 18 | COHR | -8.11 | miss | miss |
| 19 | CLSK | -8.03 | miss | 09:58 |
| 20 | ORCL | -7.75 | miss | 09:37 |

### Radar flags (6)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | CRWV | relative_to_spy | down | +1.36 | +1.41 | -0.60 |
| 10:02 | Bitcoin treasuries and miners (IREN, CLSK, RIOT, MARA, COIN, MSTR) | group_move | down | -0.52 | -0.32 | -1.59 |
| 10:02 | Neoclouds and AI hosting (CRWV, IREN, NBIS, APLD, WULF, ORCL, CIFR) | group_move | down | +0.23 | +0.87 | -0.65 |
| 10:05 | Crypto and exchanges (HOOD, CRCL, MSTR, COIN, RIOT, MARA, BULL) | group_move | down | -0.09 | -0.60 | -1.22 |
| 10:09 | Retail brokers and fintech (HOOD, SOFI, COIN, BULL, PYPL) | group_move | down | +0.46 | -0.45 | -0.29 |
| 10:24 | Rideshare and delivery (LYFT, DASH, UBER) | group_move | down | -0.10 | -0.65 | -0.24 |

### Movers flags (38)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | UNH | leaders | up | +1.94 | +1.00 | +1.63 |
| 09:31 | TTWO | leaders | up | -0.43 | -0.22 | -0.68 |
| 09:31 | WMT | leaders | up | +0.43 | +0.49 | +0.95 |
| 09:31 | CVS | leaders | up | +0.39 | +0.83 | +1.03 |
| 09:31 | PFE | leaders | up | +1.70 | +1.53 | +1.98 |
| 09:31 | ELV | leaders | up | -0.83 | -1.00 | -1.18 |
| 09:31 | CI | leaders | up | +0.08 | -0.10 | +0.36 |
| 09:31 | CNC | leaders | up | +0.04 | -0.41 | -0.19 |
| 09:31 | HUM | leaders | up | +0.21 | +0.14 | +0.74 |
| 09:31 | LLY | leaders | up | +2.50 | +3.07 | +3.38 |
| 09:31 | CRWV | laggards | down | -7.39 | -6.31 | -6.95 |
| 09:31 | BAC | laggards | down | -0.15 | +0.70 | +1.57 |
| 09:31 | CIFR | laggards | down | -1.38 | -0.81 | -1.70 |
| 09:31 | U | laggards | down | -2.45 | -1.27 | -2.95 |
| 09:31 | DELL | laggards | down | -2.12 | -2.74 | -4.24 |
| 09:31 | WULF | laggards | down | -3.73 | -4.54 | -5.15 |
| 09:31 | PANW | laggards | down | +0.03 | +1.33 | +0.71 |
| 09:31 | NBIS | laggards | down | -5.74 | -5.59 | -4.08 |
| 09:31 | IREN | laggards | down | -5.68 | -4.90 | -4.82 |
| 09:31 | QBTS | laggards | down | -1.12 | -1.52 | -1.65 |
| 09:32 | BABA | leaders | up | -0.90 | -1.06 | -1.65 |
| 09:32 | CVX | leaders | up | -0.24 | +0.03 | +0.39 |
| 09:32 | IONQ | laggards | down | +0.83 | -0.16 | -1.09 |
| 09:33 | NOW | leaders | up | -0.45 | -0.79 | -1.24 |
| 09:33 | ASTS | laggards | down | -2.28 | -2.56 | -2.74 |
| 09:35 | AAPL | leaders | up | +0.18 | +0.50 | +0.63 |
| 09:35 | ADBE | leaders | up | +0.22 | -0.05 | -0.24 |
| 09:35 | APLD | laggards | down | -2.38 | -1.40 | -2.24 |
| 09:36 | AMGN | leaders | up | +1.62 | +1.64 | +1.65 |
| 09:36 | MRK | leaders | up | +1.11 | +0.74 | +1.65 |
| 09:37 | ORCL | laggards | down | -0.94 | -1.38 | -0.82 |
| 09:58 | CLSK | laggards | down | -0.69 | +0.08 | -1.83 |
| 10:06 | COST | leaders | up | +0.04 | +0.37 | +1.36 |
| 11:27 | AAOI | laggards | down | -0.86 | -2.10 | -2.41 |
| 12:36 | XOM | leaders | up | +0.07 | +0.17 | +0.33 |
| 13:46 | RIOT | laggards | down | -0.38 | -0.62 | +0.08 |
| 15:08 | CIEN | laggards | down | +0.16 | — | — |
| 15:10 | TGT | leaders | up | -0.04 | — | — |

## 2026-10-15

Usable symbol-minutes 64,647/65,910. No usable minutes: TCEHY, WBD. Daily ranking covers 144/146 stocks. Excluded: TCEHY, WBD.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | WULF | +9.07 | 10:48 | 14:27 |
| 2 | CRCL | +9.04 | 10:57 | 10:55 |
| 3 | IONQ | +9.04 | miss | 12:04 |
| 4 | QUBT | +8.11 | miss | 11:12 |
| 5 | RGTI | +7.85 | miss | 15:12 |
| 6 | RBLX | +7.27 | miss | 12:16 |
| 7 | DELL | -7.08 | miss | 09:31 |
| 8 | RDDT | +6.96 | miss | 10:24 |
| 9 | RKLB | -6.93 | miss | 09:31 |
| 10 | QBTS | +6.24 | miss | 15:37 |
| 11 | APP | +6.24 | miss | 09:40 |
| 12 | LCID | +6.10 | miss | 12:36 |
| 13 | COIN | +6.03 | miss | 14:44 |
| 14 | NOW | +5.85 | miss | 10:08 |
| 15 | SOFI | +5.83 | miss | 15:44 |
| 16 | HIMS | +5.70 | miss | 15:39 |
| 17 | CRWV | +5.66 | miss | miss |
| 18 | CPRT | +5.35 | miss | 09:31 |
| 19 | KMX | +5.34 | miss | 09:31 |
| 20 | MSTR | +5.34 | miss | miss |

### Radar flags (15)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | IREN | relative_to_spy | down | -0.82 | +2.29 | +4.21 |
| 10:02 | Neoclouds and AI hosting (IREN, WULF, NBIS, CIFR, APLD, CRWV) | group_move | down | -0.37 | +3.54 | +5.31 |
| 10:02 | Social and ads (RDDT, APP, SNAP, PINS, GOOGL, META) | group_move | up | +0.18 | +0.36 | +0.54 |
| 10:02 | Space (RKLB, LUNR, ASTS, PL) | group_move | down | +1.95 | +3.67 | +5.38 |
| 10:13 | Space (PL, LUNR, RKLB, ASTS) | group_move | up | +1.36 | +2.90 | +2.31 |
| 10:15 | Gaming platforms (U, APP, TTWO, RBLX) | group_move | up | -0.23 | +0.11 | +0.32 |
| 10:24 | Quantum computing (RGTI, QUBT, QBTS, IONQ) | group_move | up | +2.32 | +4.25 | +4.30 |
| 10:25 | Crypto and exchanges (MSTR, HOOD, CRCL, BULL, MARA, COIN, RIOT) | group_move | up | +2.11 | +3.64 | +3.44 |
| 10:46 | CIFR | relative_to_spy | up | +1.05 | -0.07 | +1.44 |
| 10:46 | AI networking and connectivity (ALAB, CRDO, COHR, MRVL, AVGO, ANET) | group_move | up | +0.69 | -0.48 | -0.74 |
| 10:46 | Bitcoin treasuries and miners (IREN, RIOT, CLSK, MSTR, MARA, COIN) | group_move | up | +1.84 | +1.27 | +2.25 |
| 10:46 | Neoclouds and AI hosting (CIFR, WULF, IREN, APLD, NBIS, CRWV, ORCL) | group_move | up | +2.47 | +1.27 | +2.73 |
| 10:48 | IREN | relative_to_spy | up | +1.03 | -1.08 | +1.51 |
| 10:48 | WULF | relative_to_spy | up | +3.06 | +1.27 | +3.02 |
| 10:57 | CRCL | relative_to_spy | up | +1.10 | +0.69 | +1.77 |

### Movers flags (59)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | FND | leaders | up | -1.92 | -2.33 | -1.34 |
| 09:31 | LAD | leaders | up | +1.92 | +2.13 | +1.15 |
| 09:31 | AN | leaders | up | +2.26 | +1.10 | — |
| 09:31 | WMT | leaders | up | +0.09 | -0.07 | -1.50 |
| 09:31 | KMX | leaders | up | +0.51 | -0.04 | — |
| 09:31 | CPRT | leaders | up | +0.91 | +0.71 | +0.99 |
| 09:31 | HD | leaders | up | +0.49 | +0.57 | -0.23 |
| 09:31 | LOW | leaders | up | +0.38 | +0.99 | +0.24 |
| 09:31 | LULU | leaders | up | +1.54 | +1.37 | +2.34 |
| 09:31 | AMGN | leaders | up | +0.04 | +0.02 | -0.06 |
| 09:31 | RKLB | laggards | down | -6.85 | -5.23 | -3.30 |
| 09:31 | CIFR | laggards | down | -4.05 | -3.60 | +2.36 |
| 09:31 | CRWV | laggards | down | -1.47 | -1.10 | +2.64 |
| 09:31 | AAOI | laggards | down | -4.21 | -2.25 | +1.77 |
| 09:31 | NBIS | laggards | down | -4.72 | -4.43 | +0.74 |
| 09:31 | DELL | laggards | down | -3.56 | -4.01 | -3.06 |
| 09:31 | COHR | laggards | down | -4.73 | -3.04 | -1.71 |
| 09:31 | APLD | laggards | down | -3.55 | -3.86 | +0.58 |
| 09:31 | SNDK | laggards | down | -2.25 | -0.90 | +2.16 |
| 09:31 | IREN | laggards | down | -7.01 | -6.79 | -3.73 |
| 09:32 | DECK | leaders | up | -0.26 | -0.21 | +0.86 |
| 09:32 | MRK | leaders | up | -0.58 | -1.18 | -1.01 |
| 09:32 | NKE | leaders | up | +1.52 | +1.65 | +2.14 |
| 09:32 | CIEN | laggards | down | +1.29 | +0.87 | +2.96 |
| 09:33 | ADBE | leaders | up | +2.19 | +2.10 | +1.32 |
| 09:33 | STX | laggards | down | -1.24 | -0.29 | +1.23 |
| 09:35 | SMCI | laggards | down | +0.09 | +0.26 | +2.59 |
| 09:38 | NFLX | leaders | up | -0.51 | -0.06 | -0.55 |
| 09:40 | APP | leaders | up | +1.30 | +2.13 | +2.29 |
| 09:42 | CLSK | laggards | down | +0.38 | +1.58 | +2.41 |
| 09:44 | LLY | leaders | up | +1.37 | +1.47 | +1.89 |
| 09:55 | NVO | leaders | up | -0.86 | -0.81 | -0.53 |
| 09:58 | WULF | laggards | down | +0.39 | +7.59 | +7.09 |
| 10:08 | NOW | leaders | up | -0.10 | +0.84 | +0.45 |
| 10:12 | CRM | leaders | up | -0.54 | +0.58 | -0.20 |
| 10:13 | RIOT | laggards | down | +1.86 | +3.95 | +3.52 |
| 10:24 | RDDT | leaders | up | +0.78 | +1.37 | +0.67 |
| 10:26 | ANET | laggards | down | +0.75 | +0.96 | +0.93 |
| 10:37 | CVNA | leaders | up | +0.52 | -0.04 | -0.08 |
| 10:55 | CRCL | leaders | up | +1.61 | +1.32 | +2.13 |
| 10:59 | INTC | laggards | down | +0.66 | +1.53 | +0.69 |
| 11:05 | WDC | laggards | down | -0.40 | +0.02 | -0.43 |
| 11:12 | QUBT | leaders | up | -0.19 | -1.28 | -0.94 |
| 11:20 | NET | laggards | down | -0.25 | -0.49 | -1.27 |
| 11:25 | AMD | laggards | down | -0.10 | +0.23 | +0.17 |
| 12:04 | IONQ | leaders | up | -0.34 | +0.43 | +0.61 |
| 12:16 | RBLX | leaders | up | -0.02 | -0.24 | +0.47 |
| 12:31 | UNH | leaders | up | -0.28 | -0.78 | -0.65 |
| 12:36 | LCID | leaders | up | +0.15 | +0.03 | +1.08 |
| 13:26 | HSAI | laggards | down | +0.38 | -0.07 | +0.31 |
| 14:27 | WULF | leaders | up | +2.87 | +4.88 | — |
| 14:44 | COIN | leaders | up | -0.20 | +1.20 | — |
| 15:12 | RGTI | leaders | up | +1.70 | — | — |
| 15:13 | SCHW | laggards | down | +0.06 | — | — |
| 15:13 | CRWD | laggards | down | +0.40 | — | — |
| 15:37 | QBTS | leaders | up | — | — | — |
| 15:39 | HIMS | leaders | up | — | — | — |
| 15:40 | ASTS | leaders | up | — | — | — |
| 15:44 | SOFI | leaders | up | — | — | — |

## 2026-10-16

Usable symbol-minutes 64,539/65,910. No usable minutes: TCEHY, WBD. Daily ranking covers 144/146 stocks. Excluded: TCEHY, WBD.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | NBIS | -11.07 | miss | 09:31 |
| 2 | CRWV | -10.80 | miss | 09:31 |
| 3 | RIOT | -10.38 | miss | 13:01 |
| 4 | APLD | -10.37 | miss | 09:31 |
| 5 | IREN | -10.08 | miss | 09:31 |
| 6 | LCID | -9.46 | miss | 12:06 |
| 7 | CIFR | -9.45 | miss | 09:32 |
| 8 | CLSK | -9.05 | miss | 09:31 |
| 9 | SMCI | -8.75 | miss | 09:36 |
| 10 | FLNC | -8.69 | miss | 09:33 |
| 11 | AAOI | -8.64 | miss | 09:36 |
| 12 | MARA | -8.50 | miss | 09:34 |
| 13 | MSTR | -8.45 | miss | 09:31 |
| 14 | IONQ | -7.83 | miss | 09:31 |
| 15 | ASTS | -7.44 | miss | 09:31 |
| 16 | SNOW | -7.32 | 10:02 | 09:58 |
| 17 | QBTS | -6.97 | miss | 09:31 |
| 18 | RKLB | -6.88 | miss | miss |
| 19 | MDB | -6.78 | 10:02 | 10:06 |
| 20 | S | -6.55 | 10:02 | 10:03 |

### Radar flags (15)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | CRWD | relative_to_spy | down | -1.68 | -1.64 | -3.45 |
| 10:02 | DDOG | relative_to_spy | down | -1.00 | +0.19 | -1.51 |
| 10:02 | FTNT | relative_to_spy | down | -0.38 | -0.54 | -2.63 |
| 10:02 | MDB | relative_to_spy | down | -2.36 | -2.42 | -3.70 |
| 10:02 | NET | relative_to_spy | down | -0.09 | +0.80 | -0.86 |
| 10:02 | S | relative_to_spy | down | -1.42 | -1.98 | -4.61 |
| 10:02 | SNOW | relative_to_spy | down | -1.64 | -0.81 | -2.68 |
| 10:02 | ZS | relative_to_spy | down | -2.12 | -1.92 | -3.60 |
| 10:02 | AI software and analytics (SNOW, DDOG, PLTR, NOW, AI) | group_move | down | -1.41 | -1.05 | -3.71 |
| 10:02 | Cloud software and data (SNOW, DDOG, MDB, NOW, CRM, ADBE, ORCL) | group_move | down | -1.99 | -1.80 | -2.58 |
| 10:02 | Cybersecurity (NET, S, ZS, CRWD, FTNT, PANW) | group_move | down | -1.23 | -1.11 | -3.13 |
| 11:03 | Bitcoin treasuries and miners (MSTR, MARA, IREN, RIOT, CLSK, COIN) | group_move | down | -0.14 | -1.82 | -2.46 |
| 11:05 | Quantum computing (QBTS, IONQ, QUBT, RGTI) | group_move | down | -0.84 | -1.59 | -1.86 |
| 11:09 | Neoclouds and AI hosting (CIFR, IREN, APLD, WULF, NBIS, CRWV, ORCL) | group_move | down | +0.37 | -1.15 | -1.50 |
| 11:10 | Space (LUNR, RKLB, ASTS, PL, IRDM) | group_move | down | — | -0.67 | -0.91 |

### Movers flags (79)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | NOW | leaders | up | -3.87 | -6.22 | -7.38 |
| 09:31 | SNOW | leaders | up | -6.87 | -7.93 | -8.54 |
| 09:31 | FND | leaders | up | +1.22 | -1.20 | -0.73 |
| 09:31 | MDB | leaders | up | -5.97 | -7.69 | -8.90 |
| 09:31 | SHEL | leaders | up | +0.23 | +0.44 | +0.58 |
| 09:31 | CRM | leaders | up | -1.85 | -4.15 | -4.29 |
| 09:31 | F | leaders | up | +1.43 | +1.54 | +1.75 |
| 09:31 | SONY | leaders | up | +0.03 | -0.22 | +0.05 |
| 09:31 | ZS | leaders | up | -4.88 | -6.09 | -7.20 |
| 09:31 | CVX | leaders | up | -0.13 | -0.32 | -0.02 |
| 09:31 | CRWV | laggards | down | -0.70 | -0.30 | -1.78 |
| 09:31 | IREN | laggards | down | -0.77 | -0.02 | -2.31 |
| 09:31 | IONQ | laggards | down | +0.91 | +1.54 | -1.24 |
| 09:31 | NBIS | laggards | down | -1.84 | -2.01 | -3.54 |
| 09:31 | APLD | laggards | down | -0.11 | +0.03 | -2.76 |
| 09:31 | ASTS | laggards | down | +1.87 | +2.05 | -0.13 |
| 09:31 | QBTS | laggards | down | +1.16 | +1.51 | -1.67 |
| 09:31 | CLSK | laggards | down | +0.03 | +0.09 | -1.58 |
| 09:31 | MSTR | laggards | down | -0.97 | +0.02 | -2.45 |
| 09:31 | MU | laggards | down | -0.65 | -0.08 | +0.53 |
| 09:32 | AAPL | leaders | up | -0.80 | -0.55 | -0.21 |
| 09:32 | PLTR | leaders | up | -4.40 | -4.72 | -7.02 |
| 09:32 | S | leaders | up | -5.58 | -6.91 | -8.85 |
| 09:32 | CIFR | laggards | down | +1.65 | +1.36 | -2.49 |
| 09:32 | ALAB | laggards | down | -0.37 | -0.64 | +0.02 |
| 09:32 | SNDK | laggards | down | -0.66 | -0.28 | +0.37 |
| 09:33 | SOFI | leaders | up | -0.46 | -0.76 | -2.21 |
| 09:33 | TGT | leaders | up | -0.38 | -1.08 | -0.90 |
| 09:33 | XOM | leaders | up | -0.68 | -0.86 | -0.40 |
| 09:33 | FLNC | laggards | down | +0.45 | +0.65 | -1.05 |
| 09:33 | ARM | laggards | down | +0.21 | +0.09 | +0.02 |
| 09:34 | RDDT | leaders | up | -0.75 | -0.84 | -1.57 |
| 09:34 | JPM | leaders | up | +0.21 | +0.45 | +0.72 |
| 09:34 | C | leaders | up | +0.52 | +1.01 | +1.19 |
| 09:34 | LAD | leaders | up | +1.32 | +1.04 | — |
| 09:34 | MARA | laggards | down | +1.88 | +2.90 | +0.35 |
| 09:35 | ONON | leaders | up | -0.27 | -0.85 | -1.54 |
| 09:36 | BULL | leaders | up | -0.55 | -1.26 | -2.59 |
| 09:36 | WFC | leaders | up | -0.55 | +0.10 | +0.23 |
| 09:36 | CVNA | leaders | up | +0.27 | -0.18 | -1.59 |
| 09:36 | KMX | leaders | up | +1.46 | +1.22 | +1.66 |
| 09:36 | SMCI | laggards | down | -0.83 | -0.28 | -2.69 |
| 09:36 | COHR | laggards | down | -0.99 | -0.27 | -1.05 |
| 09:36 | AAOI | laggards | down | +0.50 | +0.60 | -2.21 |
| 09:37 | WDC | laggards | down | -0.85 | +0.60 | -0.05 |
| 09:37 | CRDO | laggards | down | +0.61 | +2.94 | +1.60 |
| 09:38 | GM | leaders | up | +0.19 | +0.10 | +0.46 |
| 09:38 | NET | laggards | down | -1.99 | -0.99 | -2.55 |
| 09:40 | DDOG | laggards | down | -0.96 | -1.11 | -1.96 |
| 09:40 | CRWD | laggards | down | +0.29 | +0.11 | -3.25 |
| 09:40 | FTNT | laggards | down | -0.12 | +0.06 | -2.58 |
| 09:41 | TSLA | leaders | up | -0.82 | -1.49 | -2.31 |
| 09:42 | AN | leaders | up | +0.55 | +0.46 | +0.50 |
| 09:44 | PANW | laggards | down | -0.20 | +0.25 | -2.80 |
| 09:46 | GS | leaders | up | -0.96 | -0.87 | -1.03 |
| 09:54 | STX | laggards | down | -0.31 | -0.40 | -0.19 |
| 09:57 | LOW | leaders | up | -0.72 | -0.72 | -0.37 |
| 09:58 | SNOW | laggards | down | -1.21 | -0.79 | -2.66 |
| 09:59 | HD | leaders | up | -0.59 | -0.56 | -0.25 |
| 10:03 | S | laggards | down | -0.82 | -1.69 | -4.45 |
| 10:06 | COP | leaders | up | -0.47 | +0.03 | +0.92 |
| 10:06 | MDB | laggards | down | -0.96 | -2.28 | -2.56 |
| 10:08 | UAA | leaders | up | -0.91 | -0.60 | -0.72 |
| 10:20 | AXP | leaders | up | -0.34 | +0.27 | -0.27 |
| 10:22 | BAC | leaders | up | -0.07 | +0.29 | -0.20 |
| 10:32 | ZS | laggards | down | +0.20 | -0.73 | -0.74 |
| 10:41 | RCAT | leaders | up | -2.42 | -2.78 | -3.84 |
| 10:53 | LLY | leaders | up | +0.43 | +0.15 | +0.12 |
| 11:21 | DIS | leaders | up | -0.11 | -0.64 | -0.94 |
| 11:55 | AI | laggards | down | -0.57 | -1.26 | -1.30 |
| 12:03 | OXY | leaders | up | +0.40 | +1.67 | +1.93 |
| 12:06 | LCID | laggards | down | -0.99 | -0.57 | -0.85 |
| 12:35 | COST | leaders | up | +0.41 | +0.35 | +0.66 |
| 12:49 | MRK | leaders | up | +0.19 | +0.25 | +0.22 |
| 13:01 | CMI | leaders | up | +0.13 | -0.44 | -0.34 |
| 13:01 | RIOT | laggards | down | -0.44 | -1.50 | -2.82 |
| 13:22 | WMT | leaders | up | -0.03 | +0.16 | -0.14 |
| 14:53 | CI | leaders | up | +0.04 | -0.09 | — |
| 15:11 | CPRT | leaders | up | -0.64 | — | — |

## 2026-10-19

Usable symbol-minutes 64,430/65,910. No usable minutes: TCEHY, WBD. Daily ranking covers 144/146 stocks. Excluded: TCEHY, WBD.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | APLD | +6.22 | miss | 09:31 |
| 2 | WDC | +5.66 | miss | 09:32 |
| 3 | SNDK | +5.10 | miss | 09:31 |
| 4 | DDOG | +4.94 | miss | 09:31 |
| 5 | AMZN | +4.56 | miss | 10:11 |
| 6 | PLTR | +3.94 | miss | 10:33 |
| 7 | MRVL | +3.64 | miss | 09:32 |
| 8 | HSAI | +3.60 | miss | 09:34 |
| 9 | KMX | -3.57 | miss | 13:29 |
| 10 | TSLA | +3.34 | miss | 13:47 |
| 11 | BULL | -3.22 | miss | 10:07 |
| 12 | FND | -3.21 | miss | 09:31 |
| 13 | COIN | -3.14 | miss | 13:09 |
| 14 | AAOI | +3.06 | miss | 09:31 |
| 15 | OKLO | -3.03 | miss | 10:03 |
| 16 | CIEN | +3.02 | miss | 09:32 |
| 17 | SCHW | -3.01 | miss | 09:33 |
| 18 | STX | +2.99 | miss | 09:36 |
| 19 | ANET | +2.95 | miss | miss |
| 20 | WFC | -2.89 | miss | 09:33 |

### Radar flags (1)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | Quantum computing (IONQ, RGTI, QBTS, QUBT) | group_move | down | +0.49 | +1.03 | +1.85 |

### Movers flags (69)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | APLD | leaders | up | +0.87 | +1.40 | +3.39 |
| 09:31 | RCAT | leaders | up | -5.13 | -5.44 | -5.27 |
| 09:31 | SNDK | leaders | up | +0.85 | +0.93 | +1.49 |
| 09:31 | ASTS | leaders | up | +0.46 | -0.52 | -0.08 |
| 09:31 | NBIS | leaders | up | -3.04 | -2.46 | -1.39 |
| 09:31 | CRDO | leaders | up | -3.96 | -3.73 | -0.34 |
| 09:31 | DDOG | leaders | up | -0.83 | +1.10 | +1.48 |
| 09:31 | IREN | leaders | up | -1.26 | -0.97 | +0.62 |
| 09:31 | INTC | leaders | up | -0.59 | -0.39 | +0.40 |
| 09:31 | AAOI | leaders | up | -3.43 | -3.17 | +0.29 |
| 09:31 | FND | laggards | down | -0.40 | -0.36 | -0.37 |
| 09:31 | SHEL | laggards | down | +0.87 | +0.20 | -0.43 |
| 09:31 | PYPL | laggards | down | +1.15 | +0.82 | +0.64 |
| 09:31 | CRM | laggards | down | +0.39 | +0.37 | +0.80 |
| 09:31 | DIS | laggards | down | +0.39 | +0.25 | +0.41 |
| 09:31 | SNAP | laggards | down | +1.55 | +1.34 | +1.19 |
| 09:31 | CI | laggards | down | +1.06 | -0.18 | -1.02 |
| 09:31 | NFLX | laggards | down | -0.56 | -0.56 | -0.69 |
| 09:31 | GM | laggards | down | +0.46 | -0.30 | -0.43 |
| 09:31 | CVS | laggards | down | +1.41 | +0.33 | -0.13 |
| 09:32 | WDC | leaders | up | +0.63 | +0.24 | +1.83 |
| 09:32 | MRVL | leaders | up | -0.80 | +0.29 | +2.29 |
| 09:32 | CIEN | leaders | up | -0.86 | -1.43 | +0.54 |
| 09:32 | CPRT | laggards | down | -1.06 | -0.47 | -0.68 |
| 09:32 | HD | laggards | down | +0.23 | +0.22 | +0.37 |
| 09:32 | LLY | laggards | down | +0.72 | +0.46 | -0.35 |
| 09:33 | CRWV | leaders | up | -3.84 | -2.47 | -2.11 |
| 09:33 | SMCI | leaders | up | -0.61 | -1.07 | +0.21 |
| 09:33 | CVNA | laggards | down | +0.86 | +0.97 | +1.05 |
| 09:33 | WFC | laggards | down | +0.34 | +0.05 | -0.57 |
| 09:33 | SCHW | laggards | down | -0.75 | -1.32 | -1.18 |
| 09:34 | HSAI | leaders | up | +0.11 | -0.26 | +2.00 |
| 09:35 | DELL | leaders | up | -2.19 | -2.12 | -1.20 |
| 09:35 | SPOT | laggards | down | -0.97 | -1.05 | -0.83 |
| 09:36 | STX | leaders | up | -0.76 | -0.49 | +0.52 |
| 09:37 | CAT | laggards | down | -0.05 | +0.04 | +0.76 |
| 09:38 | META | laggards | down | -1.13 | -0.80 | -0.05 |
| 09:38 | LOW | laggards | down | -0.03 | -0.10 | -0.40 |
| 09:38 | PCAR | laggards | down | -0.81 | -1.34 | -0.86 |
| 09:39 | MU | leaders | up | -0.35 | +0.38 | +1.27 |
| 09:39 | IONQ | laggards | down | -1.34 | -0.23 | +0.08 |
| 09:42 | LULU | laggards | down | +0.38 | -0.02 | +0.34 |
| 09:44 | WULF | leaders | up | -0.59 | +0.23 | +1.00 |
| 09:45 | AMD | leaders | up | -1.53 | -0.50 | -0.07 |
| 09:45 | RDDT | laggards | down | -0.38 | -0.19 | +0.31 |
| 09:50 | CLSK | leaders | up | -0.75 | +0.26 | +0.88 |
| 09:52 | DE | laggards | down | -0.40 | -1.04 | -0.88 |
| 10:03 | OKLO | laggards | down | -0.62 | -0.24 | +0.76 |
| 10:03 | RIVN | laggards | down | -0.13 | +0.40 | +0.41 |
| 10:04 | RGTI | laggards | down | +1.04 | +1.62 | +2.64 |
| 10:07 | BULL | laggards | down | -0.79 | -0.31 | -0.27 |
| 10:08 | HIMS | laggards | down | +1.50 | +3.50 | +2.89 |
| 10:11 | AMZN | leaders | up | +0.38 | +1.30 | +1.44 |
| 10:11 | FLNC | laggards | down | +0.50 | +1.01 | +1.37 |
| 10:33 | PLTR | leaders | up | +0.78 | +1.12 | +1.18 |
| 10:36 | CMI | laggards | down | +0.42 | +0.69 | +0.46 |
| 11:03 | COP | laggards | down | -0.07 | +0.10 | +0.50 |
| 11:15 | AMGN | laggards | down | +0.00 | +0.06 | +0.43 |
| 11:42 | CNC | laggards | down | +0.09 | -0.19 | -0.49 |
| 11:53 | F | laggards | down | -0.08 | -0.22 | -0.37 |
| 13:09 | COIN | laggards | down | -0.13 | -0.12 | -0.76 |
| 13:29 | KMX | laggards | down | -1.25 | -1.16 | -0.76 |
| 13:45 | CRWV | laggards | down | -0.09 | -0.77 | +2.67 |
| 13:47 | TSLA | leaders | up | -0.24 | -0.18 | -0.10 |
| 14:13 | MARA | laggards | down | -0.35 | +0.03 | — |
| 15:12 | C | laggards | down | -0.08 | — | — |
| 15:42 | BAC | laggards | down | — | — | — |
| 15:47 | HOOD | laggards | down | — | — | — |
| 15:53 | MDB | leaders | up | — | — | — |

## 2026-10-20

Usable symbol-minutes 64,290/65,910. No usable minutes: TCEHY, WBD. Daily ranking covers 144/146 stocks. Excluded: TCEHY, WBD.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | TDOC | +8.04 | miss | 09:31 |
| 2 | HSAI | +7.95 | miss | 09:31 |
| 3 | GM | -7.18 | miss | 09:31 |
| 4 | LCID | +5.32 | miss | 15:23 |
| 5 | CRCL | +5.20 | miss | 09:49 |
| 6 | MDB | +4.68 | miss | 10:03 |
| 7 | MSTR | +4.59 | 10:16 | 10:07 |
| 8 | IREN | -4.34 | miss | 09:31 |
| 9 | KMX | +3.87 | miss | 12:49 |
| 10 | RCAT | -3.75 | miss | 12:11 |
| 11 | ADBE | +3.57 | miss | 09:31 |
| 12 | HIMS | +3.43 | miss | 10:31 |
| 13 | ARM | -3.40 | miss | 09:53 |
| 14 | AI | +3.30 | miss | 11:51 |
| 15 | LLY | +3.16 | miss | 09:31 |
| 16 | WDC | +3.10 | miss | 14:19 |
| 17 | AMGN | +2.96 | miss | 09:36 |
| 18 | MRK | +2.92 | miss | 09:32 |
| 19 | HPQ | +2.87 | miss | 14:47 |
| 20 | CNC | +2.84 | miss | miss |

### Radar flags (16)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:04 | Crypto and exchanges (CRCL, MSTR, BULL, MARA, HOOD, COIN, RIOT) | group_move | up | +2.27 | +2.55 | +1.96 |
| 10:07 | AI networking and connectivity (COHR, CRDO, ALAB, MRVL, AVGO, ANET) | group_move | up | +0.61 | +1.13 | +0.89 |
| 10:10 | Neoclouds and AI hosting (CIFR, CRWV, NBIS, APLD, IREN, WULF, ORCL) | group_move | up | +3.05 | +2.15 | +2.04 |
| 10:11 | Bitcoin treasuries and miners (MSTR, CLSK, IREN, MARA, RIOT, COIN) | group_move | up | +3.43 | +2.32 | +1.62 |
| 10:14 | ASTS | relative_to_spy | up | +1.59 | +0.86 | +0.08 |
| 10:14 | CIFR | relative_to_spy | up | +4.12 | +0.77 | +1.67 |
| 10:14 | Space (ASTS, RKLB, PL, LUNR) | group_move | up | +1.66 | +0.21 | -0.05 |
| 10:16 | MSTR | relative_to_sector | up | +2.14 | +1.19 | +1.43 |
| 10:16 | Quantum computing (QUBT, IONQ, QBTS, RGTI) | group_move | up | +1.82 | +0.16 | -0.14 |
| 10:20 | CRWV | relative_to_spy | up | +3.92 | +2.90 | +2.00 |
| 10:20 | MARA | relative_to_spy | up | +1.71 | +0.91 | +0.36 |
| 10:23 | WULF | relative_to_spy | up | +0.96 | -0.55 | -0.43 |
| 10:25 | IREN | relative_to_spy | up | +1.05 | -1.22 | -1.20 |
| 10:27 | CLSK | relative_to_spy | up | +1.04 | -0.48 | -0.15 |
| 10:30 | RIOT | relative_to_spy | up | -0.21 | -1.09 | -0.91 |
| 11:14 | Neoclouds and AI hosting (IREN, CIFR, NBIS, WULF, APLD, CRWV, ORCL) | group_move | down | +0.23 | +0.76 | +0.23 |

### Movers flags (74)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | HSAI | leaders | up | +1.90 | +4.18 | +2.42 |
| 09:31 | LLY | leaders | up | +1.60 | +1.88 | +1.64 |
| 09:31 | NOW | leaders | up | +0.11 | -1.28 | -0.41 |
| 09:31 | ADBE | leaders | up | +1.31 | -0.31 | +0.68 |
| 09:31 | UAA | leaders | up | -0.00 | -0.11 | -0.56 |
| 09:31 | SHEL | leaders | up | -0.90 | -2.36 | -1.74 |
| 09:31 | CI | leaders | up | +0.45 | +0.07 | +0.67 |
| 09:31 | NVO | leaders | up | -0.03 | -0.03 | +0.33 |
| 09:31 | COP | leaders | up | -1.16 | -3.11 | -2.03 |
| 09:31 | TDOC | leaders | up | +2.94 | +2.89 | +5.08 |
| 09:31 | GM | laggards | down | +0.05 | -0.76 | -0.98 |
| 09:31 | AAOI | laggards | down | +2.49 | +5.41 | +4.48 |
| 09:31 | CIFR | laggards | down | -0.08 | +7.09 | +4.42 |
| 09:31 | IREN | laggards | down | -1.84 | +3.29 | +1.20 |
| 09:31 | COHR | laggards | down | +1.43 | +4.48 | +4.28 |
| 09:31 | CRDO | laggards | down | +0.54 | +3.80 | +3.98 |
| 09:31 | LCID | laggards | down | -2.15 | +0.50 | -0.46 |
| 09:31 | RIOT | laggards | down | -0.47 | +4.45 | +3.28 |
| 09:31 | NBIS | laggards | down | +0.04 | +3.79 | +2.69 |
| 09:31 | ALAB | laggards | down | +2.84 | +4.26 | +3.20 |
| 09:32 | MRK | leaders | up | -0.03 | -0.54 | -0.01 |
| 09:32 | PFE | leaders | up | +0.14 | -0.99 | +0.17 |
| 09:32 | CLSK | laggards | down | +2.57 | +7.14 | +5.65 |
| 09:32 | CRWV | laggards | down | -0.31 | +6.09 | +5.97 |
| 09:33 | TGT | leaders | up | +0.02 | -1.22 | -0.88 |
| 09:33 | UNH | leaders | up | +0.09 | -0.05 | +1.02 |
| 09:33 | ASTS | laggards | down | -0.13 | +4.08 | +3.82 |
| 09:36 | AMGN | leaders | up | +0.05 | -0.04 | +0.10 |
| 09:37 | LOW | leaders | up | -0.26 | -0.40 | -0.34 |
| 09:40 | FND | leaders | up | -0.36 | +0.97 | +1.14 |
| 09:47 | HD | leaders | up | -1.47 | -1.33 | -0.58 |
| 09:49 | CRCL | leaders | up | +1.35 | +2.33 | +1.30 |
| 09:49 | BULL | leaders | up | +0.64 | +1.27 | +0.26 |
| 09:53 | ARM | laggards | down | +1.67 | +2.44 | +1.90 |
| 09:57 | META | laggards | down | +1.11 | +1.09 | +0.99 |
| 09:58 | HUM | leaders | up | -0.72 | -0.30 | +0.64 |
| 09:58 | LUNR | laggards | down | +3.76 | +3.35 | +1.59 |
| 09:59 | SPOT | leaders | up | -0.26 | -0.92 | -1.10 |
| 09:59 | SOFI | leaders | up | +1.09 | +1.54 | +0.80 |
| 10:03 | MDB | leaders | up | +0.04 | -0.58 | +0.22 |
| 10:03 | CPRT | laggards | down | -0.55 | +0.97 | +1.90 |
| 10:07 | MSTR | leaders | up | +3.20 | +3.95 | +3.02 |
| 10:08 | HOOD | leaders | up | +1.23 | +0.71 | -0.26 |
| 10:14 | QUBT | leaders | up | +1.58 | +0.16 | -0.72 |
| 10:15 | DDOG | laggards | down | -0.59 | -0.70 | -0.36 |
| 10:16 | CRM | laggards | down | +0.13 | +0.61 | +0.20 |
| 10:18 | UBER | laggards | down | +0.19 | +0.18 | -0.50 |
| 10:18 | PANW | laggards | down | -0.70 | -0.51 | -0.68 |
| 10:25 | MARA | leaders | up | +1.75 | +0.55 | +0.57 |
| 10:25 | OXY | laggards | down | -0.60 | +0.44 | +0.76 |
| 10:26 | XOM | laggards | down | -0.74 | -0.45 | +0.35 |
| 10:29 | APLD | leaders | up | -0.48 | -1.78 | -1.94 |
| 10:29 | COP | laggards | down | -0.16 | +0.90 | +1.24 |
| 10:30 | CVX | laggards | down | -0.02 | +0.57 | +0.91 |
| 10:31 | HIMS | leaders | up | +0.67 | +2.28 | +1.87 |
| 10:38 | COIN | leaders | up | -0.91 | -2.25 | -2.18 |
| 10:45 | CRWV | leaders | up | -2.21 | -2.70 | -1.58 |
| 10:55 | FLNC | leaders | up | -1.16 | -1.32 | -1.13 |
| 10:57 | ANET | laggards | down | +0.32 | -0.16 | -0.17 |
| 11:14 | CVNA | leaders | up | -0.23 | -0.50 | -0.70 |
| 11:14 | NET | laggards | down | +0.10 | +0.62 | +0.48 |
| 11:30 | PL | laggards | down | -0.53 | -0.25 | +0.67 |
| 11:45 | CRWD | laggards | down | +0.53 | +0.91 | +0.85 |
| 11:51 | AI | leaders | up | +0.70 | +0.99 | +1.11 |
| 12:11 | RCAT | laggards | down | +0.51 | +0.21 | +0.07 |
| 12:32 | F | laggards | down | +0.05 | +0.23 | +0.47 |
| 12:41 | DASH | laggards | down | -0.10 | +0.43 | +1.09 |
| 12:49 | KMX | leaders | up | -0.60 | -0.52 | -0.61 |
| 14:04 | GOOGL | laggards | down | -0.14 | -0.28 | — |
| 14:19 | WDC | leaders | up | -0.03 | +0.17 | — |
| 14:20 | SNAP | leaders | up | -0.29 | -0.42 | — |
| 14:32 | NFLX | laggards | down | -0.10 | -0.31 | — |
| 14:47 | HPQ | leaders | up | -0.37 | -0.22 | — |
| 15:23 | LCID | leaders | up | +0.90 | — | — |

## 2026-10-21

Usable symbol-minutes 64,428/65,910. No usable minutes: TCEHY, WBD. Daily ranking covers 144/146 stocks. Excluded: TCEHY, WBD.

### Closing top 20

| Rank | Ticker | vs SPY (pp) | Radar ET | Movers ET |
|---|---|---|---|---|
| 1 | LAD | -10.67 | miss | 10:39 |
| 2 | SMCI | +9.02 | miss | 09:31 |
| 3 | APLD | +8.01 | miss | 09:31 |
| 4 | ZS | +7.32 | miss | 09:52 |
| 5 | MSTR | +7.01 | miss | 10:43 |
| 6 | HSAI | -6.24 | miss | 09:31 |
| 7 | MDB | +6.18 | miss | 11:43 |
| 8 | AN | -6.01 | miss | 10:23 |
| 9 | DDOG | +5.97 | miss | 09:41 |
| 10 | NFLX | -5.84 | miss | 09:31 |
| 11 | CRDO | +5.75 | miss | 09:31 |
| 12 | WULF | +5.72 | miss | 09:31 |
| 13 | CIEN | +5.15 | miss | 09:35 |
| 14 | RKLB | +4.92 | miss | 09:37 |
| 15 | KMX | -4.85 | miss | 10:38 |
| 16 | UAA | -4.83 | miss | 09:41 |
| 17 | NET | +4.80 | miss | 09:47 |
| 18 | DELL | +4.74 | miss | 09:31 |
| 19 | CRWD | +4.74 | miss | 10:30 |
| 20 | QUBT | +4.40 | miss | miss |

### Radar flags (7)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 10:02 | CIFR | relative_to_spy | down | +0.49 | +1.14 | +0.03 |
| 10:02 | AI networking and connectivity (MRVL, ALAB, ANET, CRDO, COHR, AVGO) | group_move | down | +0.35 | +0.12 | +0.26 |
| 10:02 | Bitcoin treasuries and miners (IREN, RIOT, CLSK, MARA, COIN, MSTR) | group_move | down | +1.27 | +2.36 | +2.53 |
| 10:02 | Memory and storage (SNDK, STX, WDC, MU) | group_move | down | +0.79 | +0.48 | +0.89 |
| 10:02 | Neoclouds and AI hosting (CIFR, NBIS, CRWV, IREN, ORCL, WULF, APLD) | group_move | down | +0.92 | +1.47 | +1.14 |
| 10:27 | Cybersecurity (PANW, ZS, CRWD, NET, S, FTNT) | group_move | up | -0.81 | -0.88 | -0.26 |
| 10:49 | Bitcoin treasuries and miners (IREN, MARA, MSTR, CLSK, RIOT, COIN) | group_move | up | -0.48 | -0.30 | +0.19 |

### Movers flags (53)

| ET | Ticker or group (members) | Rule | Side | +30 | +60 | +120 |
|---|---|---|---|---|---|---|
| 09:31 | SMCI | leaders | up | +0.38 | -0.07 | -2.37 |
| 09:31 | CRDO | leaders | up | -3.03 | -2.33 | -3.05 |
| 09:31 | DELL | leaders | up | -3.22 | -2.20 | -3.73 |
| 09:31 | WULF | leaders | up | -2.09 | -1.28 | -2.07 |
| 09:31 | LAD | leaders | up | -3.84 | -7.57 | — |
| 09:31 | APLD | leaders | up | -0.98 | -0.67 | +1.18 |
| 09:31 | IREN | leaders | up | -4.34 | -3.63 | -2.09 |
| 09:31 | CIFR | leaders | up | -5.07 | -4.91 | -4.64 |
| 09:31 | LCID | leaders | up | -2.75 | -3.36 | -5.22 |
| 09:31 | STX | leaders | up | -2.92 | -2.13 | -2.06 |
| 09:31 | HSAI | laggards | down | -0.94 | -1.63 | -1.18 |
| 09:31 | NFLX | laggards | down | +2.49 | +0.75 | +0.09 |
| 09:31 | BABA | laggards | down | -0.72 | -1.70 | -1.69 |
| 09:31 | SPOT | laggards | down | +1.94 | +1.54 | +2.02 |
| 09:31 | GOOGL | laggards | down | -0.16 | -0.55 | -0.37 |
| 09:31 | JD | laggards | down | -1.32 | -2.09 | -2.33 |
| 09:31 | LLY | laggards | down | +0.79 | +0.56 | +0.16 |
| 09:31 | DASH | laggards | down | +0.09 | +0.55 | -1.08 |
| 09:31 | PDD | laggards | down | -1.75 | -2.64 | -2.75 |
| 09:31 | DECK | laggards | down | -0.51 | -0.51 | -0.64 |
| 09:32 | CRM | laggards | down | +0.90 | +1.47 | +1.80 |
| 09:32 | ONON | laggards | down | -0.28 | -0.32 | -1.15 |
| 09:33 | LUNR | leaders | up | +1.24 | -0.35 | -2.09 |
| 09:33 | FTNT | laggards | down | +1.73 | +3.13 | +2.09 |
| 09:34 | BIDU | laggards | down | -0.36 | -0.96 | -0.79 |
| 09:35 | CIEN | leaders | up | +0.29 | +0.23 | -0.67 |
| 09:35 | AAOI | leaders | up | -1.40 | -2.40 | -3.36 |
| 09:35 | LULU | laggards | down | +0.41 | -0.81 | -0.96 |
| 09:35 | LYFT | laggards | down | +0.66 | +1.04 | +0.84 |
| 09:36 | RIOT | leaders | up | -2.48 | -2.13 | -2.53 |
| 09:37 | PL | leaders | up | -0.20 | -0.97 | -2.19 |
| 09:37 | RKLB | leaders | up | +0.86 | +0.57 | +0.12 |
| 09:38 | ELV | laggards | down | -1.15 | +0.20 | +1.53 |
| 09:39 | SNDK | laggards | down | +1.36 | +2.42 | +3.02 |
| 09:41 | DDOG | leaders | up | +2.30 | +2.76 | +3.44 |
| 09:41 | UAA | laggards | down | -0.15 | -0.68 | -1.49 |
| 09:42 | NBIS | laggards | down | +0.91 | +2.13 | +3.25 |
| 09:42 | CRWV | laggards | down | -0.49 | +0.97 | +2.08 |
| 09:44 | ORCL | laggards | down | +0.79 | +0.94 | +1.26 |
| 09:47 | NET | leaders | up | +0.65 | +1.19 | +2.67 |
| 09:50 | TSLA | leaders | up | -0.15 | -0.62 | -0.62 |
| 09:52 | ZS | leaders | up | +2.25 | +1.66 | +1.53 |
| 10:15 | F | laggards | down | +0.02 | -0.68 | -0.54 |
| 10:16 | GM | laggards | down | +0.30 | -0.54 | -0.52 |
| 10:23 | AN | laggards | down | -1.13 | -1.76 | — |
| 10:30 | CRWD | leaders | up | -0.89 | -1.10 | -0.32 |
| 10:38 | KMX | laggards | down | +0.19 | +1.07 | +0.54 |
| 10:39 | LAD | laggards | down | +0.37 | -0.11 | -3.17 |
| 10:43 | MSTR | leaders | up | +2.57 | +2.84 | +3.71 |
| 10:55 | MARA | leaders | up | -0.41 | -0.12 | -0.10 |
| 10:58 | CRCL | leaders | up | +0.54 | +1.23 | +1.17 |
| 11:31 | COIN | leaders | up | -0.03 | +0.09 | +0.32 |
| 11:43 | MDB | leaders | up | +0.90 | +1.81 | +1.67 |
