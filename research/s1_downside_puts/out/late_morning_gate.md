Late-morning SPY gate (11:00: SPY >= 0.3 daily ATR from the open, same side of VWAP every bar since 10:00);
entries from 'none'-gate trades on gated days, signal at/after 11:00, in the gate's direction. Cost 3% each side.

| window | side | exit | days gated | trades | win | PF | $/contract | total $ | return on premium |
|---|---|---|---|---|---|---|---|---|---|
| design | calls | s1 | 17 | 112 | 40% | 1.06 | 2.1 | 240 | -2.5% |
| design | calls | ema9 | 17 | 111 | 35% | 1.22 | 7.0 | 778 | +2.3% |
| design | calls | vwap | 17 | 58 | 28% | 0.83 | -10.5 | -612 | -11.4% |
| design | puts | s1 | 10 | 51 | 47% | 2.00 | 54.6 | 2785 | +3.0% |
| design | puts | ema9 | 10 | 41 | 37% | 0.87 | -6.0 | -244 | -1.8% |
| design | puts | vwap | 10 | 30 | 17% | 0.33 | -64.6 | -1937 | -1.2% |
| recent | calls | s1 | 2 | 13 | 54% | 2.49 | 44.1 | 573 | +21.2% |
| recent | calls | ema9 | 2 | 13 | 23% | 8.60 | 189.0 | 2457 | +105.4% |
| recent | calls | vwap | 2 | 6 | 67% | 18.22 | 560.9 | 3365 | +318.5% |
| recent | puts | s1 | 2 | 11 | 18% | 0.19 | -37.7 | -415 | -26.5% |
| recent | puts | ema9 | 2 | 10 | 0% | 0.00 | -37.9 | -379 | -24.4% |
| recent | puts | vwap | 2 | 7 | 14% | 0.12 | -50.4 | -353 | -41.4% |
