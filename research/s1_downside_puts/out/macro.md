## Day mix

- All sessions: 157 days: trend-down 19 (12%), trend-up 24 (15%), choppy 114
- CPI: 7 days: trend-down 1 (14%), trend-up 0 (0%), choppy 6
- PPI: 7 days: trend-down 1 (14%), trend-up 3 (43%), choppy 3
- jobs: 7 days: trend-down 1 (14%), trend-up 0 (0%), choppy 6
- FOMC: 5 days: trend-down 3 (60%), trend-up 0 (0%), choppy 2
- Any 08:30 release (CPI/PPI/jobs): 21 days: trend-down 3 (14%), trend-up 3 (14%), choppy 15
- No release: 132 days: trend-down 14 (11%), trend-up 21 (16%), choppy 97

## Gap after an 08:30 release (SPY open vs prior close, daily ATRs)

| day | release | gap | day type |
|---|---|---|---|
| 2026-03-06 | jobs | -0.90 | choppy |
| 2026-03-11 | CPI | +0.04 | choppy |
| 2026-03-18 | PPI/FOMC | -0.24 | trend_down |
| 2026-04-10 | CPI | +0.13 | choppy |
| 2026-04-14 | PPI | +0.16 | trend_up |
| 2026-05-08 | jobs | +0.49 | choppy |
| 2026-05-12 | CPI | -0.36 | choppy |
| 2026-05-13 | PPI | +0.04 | trend_up |
| 2026-06-05 | jobs | -0.75 | trend_down |
| 2026-06-10 | CPI | -0.44 | trend_down |
| 2026-06-11 | PPI | +0.38 | trend_up |
| 2026-07-02 | jobs | +0.15 | choppy |
| 2026-07-14 | CPI | +0.19 | choppy |
| 2026-07-15 | PPI | +0.27 | choppy |
| 2026-08-07 | jobs | +0.27 | choppy |
| 2026-08-12 | CPI | +0.46 | choppy |
| 2026-08-13 | PPI | +0.28 | choppy |
| 2026-09-04 | jobs | -0.21 | choppy |
| 2026-09-10 | PPI | -0.80 | choppy |
| 2026-09-11 | CPI | +1.29 | choppy |
| 2026-10-02 | jobs | +0.95 | choppy |

- gap down >= 0.2 ATR: release days trend down 3/7; other days 5/39

- gap up >= 0.2 ATR: release days trend up 1/8; other days 11/49

- gap down >= 0.3 ATR: release days trend down 2/5; other days 2/29

- gap up >= 0.3 ATR: release days trend up 1/5; other days 8/43

- gap down >= 0.5 ATR: release days trend down 1/3; other days 1/14

- gap up >= 0.5 ATR: release days trend up 0/2; other days 6/24

## Detection checks on release days vs other days (hit rate = fired days that trended that way)

| check | side | release days | other days |
|---|---|---|---|
| 2 of breadth/volume/VIXY + base | down | 0/0 | 0/4 |
| 2 of breadth/volume/VIXY + base | up | 0/0 | 0/0 |
| SPY volume 1.3x | down | 0/0 | 0/4 |
| SPY volume 1.3x | up | 0/0 | 4/5 |
| SPY+QQQ+IWM aligned | down | 1/1 | 3/14 |
| SPY+QQQ+IWM aligned | up | 0/1 | 5/16 |
| VIXY confirms | down | 1/1 | 1/8 |
| VIXY confirms | up | 0/0 | 5/7 |
| afternoon new extreme | down | 3/4 | 11/25 |
| afternoon new extreme | up | 3/4 | 17/37 |
| base (SPY 0.3 ATR + VWAP side) | down | 1/2 | 5/16 |
| base (SPY 0.3 ATR + VWAP side) | up | 1/4 | 14/24 |
| coiled prior day + base | down | 1/1 | 3/6 |
| coiled prior day + base | up | 0/0 | 3/4 |
| failed bounce | down | 1/4 | 8/34 |
| failed bounce | up | 1/3 | 8/26 |
