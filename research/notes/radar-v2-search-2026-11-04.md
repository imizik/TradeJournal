# Radar v2 historical search

**The opening-drive rule caught more intraday movers, but it failed the test for replacing Movers.** Across the 36 confirmation sessions, C06 caught 705 of 720 open-to-close targets against 553 for Movers. On the previous-close measure, it caught 627 against 682. C06 beat frozen Radar v0 on the registered balance of hit rate and precision on both labels. Across all 14 candidates, none exceeded both baselines on both labels. Against Movers, C06 won only on open-to-close (0.453 versus 0.412) and lost on close-to-close (0.424 versus 0.485).

C06 produced 70.8 flags per session versus 62.2 for Movers. Among shared open-to-close catches its median advantage was half a minute. On shared close-to-close catches it was four minutes later. At +60, 48.5% of its 2,413 scorable flags continued in the same direction and the mean excess move was +0.001 pp. Catching a name that ultimately moved a lot offered little evidence of further movement after the flag.

## What was fixed before confirmation

The protocol commit `849eecc57` set the split, 14 candidates, precision credit, shortlist order and success condition. The DESIGN lock `38dec4cc9` selected **C06, C11, C07** in that order using June 15–August 31 alone. The ranking maximized each candidate’s weaker label score. C06 flags the first move of at least 2 pp against SPY since the open with at least 0.5 pp in the same direction over the last five minutes. C11 also accepts gap holds and gap reversals. C07 flags a 2.5 pp move against SPY since the previous close.

September 1–October 21 was evaluated once, with all registered candidates in the same run. Only C06 could win the primary comparison. C11 and C07 were secondary. The other eleven results document the search, including failures. The engine freezes C06 as opt-in `radar-rules-v2`. The default is v0.

[Protocol and all candidate definitions](../radar-v2/protocol.json) · [Committed DESIGN picks](../radar-v2/design-picks.json)

## CONFIRM · 36 sessions

CC uses the previous close and OC uses the open. Lead is median minutes ahead of Movers, with the shared-catch count in parentheses. F1 is the harmonic mean of hit rate and protocol precision.

| Rule | Flags/day | CC hit | CC precision | CC F1 | CC lead (n) | OC hit | OC precision | OC F1 | OC lead (n) |
|---|---|---|---|---|---|---|---|---|---|
| v0 | 7.1 | 8.1% | 29.2% | 0.126 | -23.5 (58) | 10.1% | 34.6% | 0.157 | -22 (64) |
| Movers | 62.2 | 94.7% | 32.6% | 0.485 | +0 (682) | 76.8% | 28.2% | 0.412 | +0 (553) |
| C06 | 70.8 | 87.1% | 28.0% | 0.424 | -4 (597) | 97.9% | 29.5% | 0.453 | +0.5 (542) |
| C11 | 80.8 | 94.0% | 26.8% | 0.417 | -3 (646) | 97.9% | 26.6% | 0.419 | +1 (542) |
| C07 | 76.3 | 100.0% | 28.4% | 0.443 | +0 (682) | 87.1% | 26.1% | 0.401 | +0 (545) |
| C01 | 19.1 | 38.8% | 42.1% | 0.403 | -4 (268) | 16.9% | 21.8% | 0.191 | -4 (117) |
| C02 | 24.1 | 33.1% | 31.3% | 0.321 | -16 (229) | 30.1% | 27.8% | 0.289 | -8 (177) |
| C03 | 111.1 | 86.8% | 19.4% | 0.318 | -12 (597) | 90.1% | 19.8% | 0.324 | -3 (504) |
| C04 | 74.6 | 56.1% | 18.9% | 0.283 | -13 (378) | 60.6% | 19.6% | 0.296 | -4 (333) |
| C05 | 11.5 | 3.1% | 16.9% | 0.052 | +43 (19) | 18.6% | 35.8% | 0.245 | +78 (45) |
| C08 | 106.8 | 86.1% | 19.8% | 0.322 | -14 (589) | 89.0% | 20.0% | 0.327 | -2 (499) |
| C09 | 12.1 | 21.8% | 39.6% | 0.281 | -24.5 (154) | 19.2% | 33.9% | 0.245 | -16.5 (114) |
| C10 | 48.7 | 47.5% | 23.8% | 0.318 | -14 (322) | 52.8% | 25.3% | 0.342 | -5 (298) |
| C12 | 98.5 | 100.0% | 24.0% | 0.387 | +0 (682) | 99.9% | 23.5% | 0.380 | +4 (553) |
| C13 | 136.3 | 94.4% | 17.6% | 0.296 | -4 (647) | 93.5% | 17.3% | 0.291 | +0 (521) |
| C14 | 133.8 | 100.0% | 19.1% | 0.321 | +0 (682) | 99.4% | 18.8% | 0.316 | +3 (553) |

Directional continuation shows the share above zero, mean signed excess return in pp, and number with an exact endpoint. Total flags minus the scored count gives the missing count.

| Rule | Total flags | +30 positive / mean / n | +60 positive / mean / n | +120 positive / mean / n |
|---|---|---|---|---|
| v0 | 257 | 50.0% / +0.14 / 252 | 46.8% / -0.06 / 252 | 50.8% / +0.06 / 242 |
| Movers | 2239 | 48.5% / -0.02 / 2201 | 47.4% / -0.08 / 2171 | 47.6% / -0.02 / 2114 |
| C06 | 2549 | 49.7% / +0.04 / 2439 | 48.5% / +0.00 / 2413 | 48.7% / +0.02 / 2340 |
| C11 | 2909 | 48.6% / +0.01 / 2803 | 47.8% / -0.05 / 2779 | 48.1% / -0.02 / 2715 |
| C07 | 2748 | 48.2% / -0.01 / 2637 | 47.0% / -0.09 / 2573 | 47.8% / -0.03 / 2475 |
| C01 | 687 | 45.4% / -0.15 / 685 | 44.7% / -0.29 / 684 | 46.1% / -0.18 / 686 |
| C02 | 867 | 47.8% / -0.08 / 835 | 46.8% / -0.12 / 814 | 46.9% / -0.12 / 746 |
| C03 | 3999 | 47.6% / -0.02 / 3921 | 48.2% / -0.03 / 3889 | 48.5% / -0.02 / 3834 |
| C04 | 2687 | 47.9% / -0.00 / 2647 | 48.2% / -0.04 / 2637 | 48.4% / -0.01 / 2582 |
| C05 | 413 | 55.0% / +0.29 / 413 | 52.3% / +0.22 / 413 | 52.1% / +0.04 / 411 |
| C08 | 3844 | 46.9% / -0.03 / 3754 | 46.8% / -0.06 / 3711 | 46.6% / -0.04 / 3656 |
| C09 | 434 | 39.2% / -0.16 / 423 | 43.1% / -0.24 / 408 | 46.9% / -0.13 / 373 |
| C10 | 1753 | 47.6% / +0.01 / 1723 | 48.5% / -0.01 / 1708 | 49.3% / +0.04 / 1676 |
| C12 | 3547 | 48.8% / +0.03 / 3429 | 47.5% / -0.04 / 3376 | 48.2% / -0.02 / 3271 |
| C13 | 4908 | 47.3% / -0.03 / 4819 | 47.7% / -0.05 / 4792 | 47.7% / -0.05 / 4727 |
| C14 | 4815 | 47.9% / +0.00 / 4692 | 47.1% / -0.04 / 4625 | 46.6% / -0.04 / 4528 |

## DESIGN · 54 sessions

CC uses the previous close and OC uses the open. Lead is median minutes ahead of Movers, with the shared-catch count in parentheses. F1 is the harmonic mean of hit rate and protocol precision.

| Rule | Flags/day | CC hit | CC precision | CC F1 | CC lead (n) | OC hit | OC precision | OC F1 | OC lead (n) |
|---|---|---|---|---|---|---|---|---|---|
| v0 | 17.3 | 19.8% | 29.7% | 0.238 | -24 (208) | 25.3% | 34.3% | 0.291 | -16 (225) |
| Movers | 58.7 | 92.5% | 35.1% | 0.509 | +0 (999) | 72.7% | 29.9% | 0.424 | +0 (785) |
| C06 | 86.4 | 91.2% | 27.7% | 0.425 | -4 (910) | 99.4% | 27.5% | 0.430 | +1 (781) |
| C11 | 97.6 | 96.3% | 26.9% | 0.420 | -3 (962) | 99.4% | 26.1% | 0.414 | +2 (781) |
| C07 | 94.8 | 100.0% | 25.8% | 0.410 | +0 (999) | 90.9% | 24.8% | 0.390 | +1 (785) |
| C01 | 24.5 | 44.3% | 41.6% | 0.429 | -4 (452) | 19.5% | 25.2% | 0.220 | -4 (201) |
| C02 | 24.8 | 30.6% | 31.9% | 0.313 | -20 (319) | 30.9% | 31.5% | 0.312 | -15.5 (258) |
| C03 | 134.5 | 91.8% | 21.3% | 0.346 | -13 (923) | 95.9% | 20.9% | 0.344 | -4 (759) |
| C04 | 88.6 | 52.9% | 18.9% | 0.279 | -14 (534) | 57.1% | 18.9% | 0.284 | -6 (450) |
| C05 | 14.5 | 3.7% | 25.5% | 0.065 | +28.5 (38) | 21.4% | 38.3% | 0.275 | +31 (84) |
| C08 | 131.3 | 92.6% | 21.7% | 0.351 | -14 (929) | 95.2% | 21.1% | 0.345 | -5 (757) |
| C09 | 13.6 | 22.7% | 39.0% | 0.287 | -30.5 (236) | 23.4% | 39.4% | 0.294 | -23 (209) |
| C10 | 58.6 | 45.9% | 23.8% | 0.314 | -13 (464) | 51.8% | 24.7% | 0.335 | -6 (408) |
| C12 | 117.6 | 100.0% | 23.6% | 0.382 | +0 (999) | 99.8% | 23.0% | 0.374 | +4 (785) |
| C13 | 161.4 | 97.6% | 19.4% | 0.324 | -4 (978) | 97.4% | 18.7% | 0.314 | -1 (771) |
| C14 | 159.7 | 100.0% | 20.2% | 0.336 | +0 (999) | 99.6% | 19.6% | 0.328 | +3 (785) |

Directional continuation shows the share above zero, mean signed excess return in pp, and number with an exact endpoint. Total flags minus the scored count gives the missing count.

| Rule | Total flags | +30 positive / mean / n | +60 positive / mean / n | +120 positive / mean / n |
|---|---|---|---|---|
| v0 | 934 | 49.0% / +0.01 / 909 | 45.8% / -0.21 / 900 | 49.0% / -0.06 / 887 |
| Movers | 3168 | 49.9% / -0.05 / 3104 | 50.3% / -0.02 / 3077 | 51.3% / +0.03 / 3022 |
| C06 | 4664 | 50.8% / +0.12 / 4482 | 51.3% / +0.15 / 4435 | 50.6% / +0.12 / 4334 |
| C11 | 5270 | 50.7% / +0.10 / 5100 | 51.8% / +0.14 / 5061 | 50.3% / +0.12 / 4973 |
| C07 | 5120 | 49.8% / -0.05 / 4976 | 49.8% / -0.04 / 4921 | 49.3% / -0.03 / 4778 |
| C01 | 1323 | 50.9% / +0.01 / 1321 | 53.0% / +0.08 / 1322 | 50.3% / +0.05 / 1322 |
| C02 | 1338 | 48.6% / +0.01 / 1276 | 50.1% / -0.02 / 1231 | 48.6% / -0.00 / 1131 |
| C03 | 7261 | 49.4% / +0.05 / 7140 | 49.8% / +0.05 / 7095 | 49.8% / +0.05 / 7021 |
| C04 | 4784 | 51.8% / +0.11 / 4727 | 51.3% / +0.09 / 4709 | 50.9% / +0.09 / 4664 |
| C05 | 785 | 57.3% / +0.53 / 785 | 55.9% / +0.56 / 784 | 52.0% / +0.39 / 783 |
| C08 | 7092 | 49.6% / +0.08 / 6966 | 50.3% / +0.06 / 6915 | 50.1% / +0.05 / 6830 |
| C09 | 736 | 47.7% / -0.04 / 690 | 48.5% / -0.10 / 664 | 46.8% / -0.10 / 611 |
| C10 | 3164 | 50.5% / +0.10 / 3146 | 50.6% / +0.08 / 3138 | 51.0% / +0.10 / 3104 |
| C12 | 6353 | 50.4% / +0.02 / 6167 | 50.6% / +0.04 / 6108 | 49.8% / +0.03 / 5975 |
| C13 | 8715 | 50.6% / +0.07 / 8585 | 51.0% / +0.07 / 8534 | 50.0% / +0.06 / 8464 |
| C14 | 8623 | 49.4% / +0.02 / 8463 | 50.0% / +0.03 / 8397 | 49.4% / +0.02 / 8254 |


## Interpretation and reproduction

Each session contributes 20 tracked stocks per label, ranked by their absolute move versus SPY. A catch requires the correct side. Both labels use the raw daily close. CC uses the previous scheduled close on the current share basis and OC uses the raw daily open. The signal uses only completed minute bars. An OC hit can occur as late as the close. Precision awards each flag one credit if it catches its directional target or gains at least 2 pp against SPY in its direction by exactly +60. A missing +60 endpoint earns only any available target credit. F1 here combines that registered precision with hit rate. v0 keeps its original group flags and repeat events. A group can earn continuation credit through its fixed basket.

The #665 price snapshot contains opens and closes only. A separate volume fetch filled 110 regular sessions, including 20 warm-up sessions. Each surge uses the previous minute’s volume against that minute’s mean over the prior 20 scheduled sessions. Missing volume excludes that comparison. The run reused #665’s published v0 and Movers timestamps after verifying the price snapshot’s SHA-256. Labels and forward returns were recomputed from prices at full replay precision. The canonical offline commands below regenerate the baseline flags directly. The JSON summaries contain input hashes for each split.

The roster was assembled on October 21. Prior publication of #665 exposed baseline results for the whole period, and both splits share the same roster. These limits, the small number of sessions, and the gap between minute-end SIP bars and live quote snapshots limit generalization. The recorder also applies its existing quote-quality checks, including a usable previous close for the event evidence. The offline opening-drive calculation needs only the opening and intraday prices. All stock-days with minute prices in this snapshot had a comparable previous close. The forward returns are stock-minus-SPY observations without execution costs or fills.

From the backend directory, with the existing #665 snapshot, use an empty results directory to reproduce the study.

```sh
ALPACA_DATA_FEED=sip python -m scripts.radar_volume_snapshot VOLUME --cache-root ALPACA_CACHE
python -m scripts.radar_v2_search design PRICE_SNAPSHOT VOLUME --out RESULTS
python -m scripts.radar_v2_search confirm PRICE_SNAPSHOT VOLUME --out RESULTS
```

The per-session appendix records flag counts, hits, credited flags, shared lead times and horizon counts, positives and signed sums. Each JSONL line is one session.

[DESIGN appendix](../radar-v2/design-sessions.jsonl) · [CONFIRM appendix](../radar-v2/confirm-sessions.jsonl) · [DESIGN totals and input hashes](../radar-v2/design-summary.json) · [CONFIRM totals and input hashes](../radar-v2/confirm-summary.json)
