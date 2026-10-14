157 sessions; SPY trend-down days 19, trend-up days 24. Each check fires at most once a day, at the first check time it holds (10:30, 11:00, 12:00, 13:00, 14:00).

### down

| check | days fired | right | hit rate | caught | avg follow-on (ATR) | follow-on > 0 | median time |
|---|---|---|---|---|---|---|---|
| base (SPY 0.3 ATR + VWAP side) | 18 | 6 | 33% | 6/19 | -0.09 | 50% | 10:30 |
| breadth 70% | 0 | | | 0/19 | | | |
| SPY volume 1.3x | 4 | 0 | 0% | 0/19 | -0.40 | 50% | 11:00 |
| VIXY confirms | 9 | 2 | 22% | 2/19 | -0.26 | 33% | 11:00 |
| SPY+QQQ+IWM aligned | 15 | 4 | 27% | 4/19 | -0.12 | 33% | 10:30 |
| coiled prior day + base | 7 | 4 | 57% | 4/19 | +0.15 | 71% | 10:30 |
| afternoon new extreme | 29 | 14 | 48% | 14/19 | +0.04 | 62% | 13:00 |
| failed bounce | 38 | 9 | 24% | 9/19 | -0.00 | 47% | 13:00 |
| base + breadth | 0 | | | 0/19 | | | |
| base + breadth + volume | 0 | | | 0/19 | | | |
| breadth + VIXY | 0 | | | 0/19 | | | |
| 2 of breadth/volume/VIXY + base | 4 | 0 | 0% | 0/19 | -0.70 | 25% | 11:00 |

### up

| check | days fired | right | hit rate | caught | avg follow-on (ATR) | follow-on > 0 | median time |
|---|---|---|---|---|---|---|---|
| base (SPY 0.3 ATR + VWAP side) | 28 | 15 | 54% | 15/24 | +0.07 | 57% | 10:30 |
| breadth 70% | 0 | | | 0/24 | | | |
| SPY volume 1.3x | 5 | 4 | 80% | 4/24 | +0.26 | 80% | 11:00 |
| VIXY confirms | 7 | 5 | 71% | 5/24 | +0.17 | 57% | 10:30 |
| SPY+QQQ+IWM aligned | 17 | 5 | 29% | 5/24 | -0.15 | 41% | 10:30 |
| coiled prior day + base | 4 | 3 | 75% | 3/24 | +0.28 | 75% | 11:00 |
| afternoon new extreme | 41 | 20 | 49% | 20/24 | +0.01 | 51% | 13:00 |
| failed bounce | 29 | 9 | 31% | 9/24 | -0.03 | 59% | 13:00 |
| base + breadth | 0 | | | 0/24 | | | |
| base + breadth + volume | 0 | | | 0/24 | | | |
| breadth + VIXY | 0 | | | 0/24 | | | |
| 2 of breadth/volume/VIXY + base | 0 | | | 0/24 | | | |

