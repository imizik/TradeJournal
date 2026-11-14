# QQQ overnight hold with quote fills: result (2026-11-14)

Protocol: [`research/qqq-overnight/protocol.json`](../qqq-overnight/protocol.json) (`qqq-overnight-20261114-v1`), registered in #815 before any overnight or intraday QQQ return was computed. It ran once on 2026-11-14 with the script as merged in #815. Aggregates are in [`results.json`](../qqq-overnight/results.json).

The rule: buy QQQ at 15:59:01 at the ask and sell at the next session's 09:30:01 at the bid, through weekends and holidays. Early-close entry days are left out. From 2016-01-04 to 2026-11-12 that gave 2,711 holds. Every one had an entry quote and an exit quote, and none had missing bars.

## Decision: worth a paper test

| Holds | Mean net a hold | 95% interval | 2016-2019 / 2020-2022 / 2023-2026 | Extra cent a side | Intraday, same days, no costs |
|---|---|---|---|---|---|
| 2,711 | +4.20 bp | +1.10 to +7.13 bp | +4.49 / +1.97 / +5.66 bp | +3.36 bp | +3.06 bp |

All four conditions held:
- the interval is above zero;
- every period is positive;
- the extra-cent stress stays positive;
- the net overnight mean is above the cost-free intraday mean on the same days.

This is the first registered market setup in this repository to reach "worth a paper test". It allows a QQQ overnight paper book on the desk with these exact rules, before any money.

## What it does and does not show

- **It is a way of holding the index, not an edge apart from it.** QQQ rose about 6.2 times from the first open to the last close (dividends left out). Holding it only overnight after costs grew $1 to $2.82, about 10% a year. Holding it only during the session grew $1 to $1.95 with no costs. The overnight hold kept less than half of buy-and-hold's growth and carried none of the session's moves.
- **Overnight did better than intraday, but only modestly:** +4.20 bp against +3.06 bp a day. The protocol required only that the overnight mean be higher. It did not test whether the difference is real, so "most of the gain comes overnight" is not shown here. Over this decade the gains were split between the two parts of the day.
- **It is not a hedge:** in 2022 the overnight hold averaged -7.7 bp a night against -4.4 bp intraday. A bear market hits it as hard as owning QQQ.
- **Costs are small:** the entry spread averaged 0.46 bp, and the same holds on bars with no costs averaged +4.64 bp. Fills from the quotes cost about 0.4 bp a hold.
- **By year:** positive in 10 of 11 years. 2016 was about flat (+0.2 bp), and 2024 was best (+10.7 bp).
- **By entry weekday (descriptive, not a rule):** Monday and Tuesday nights averaged about +10 bp and +9 bp. Wednesday, Thursday and Friday nights averaged +0.9, +1.2 and -0.4 bp. Friday-to-Monday holds earned nothing over the weekend. Choosing nights by weekday would be a new protocol tested on new data. It must not be picked from this table.
- **Not one lucky month:** without the best 1% of months the mean was +3.76 bp.

## Limits

- Fills assume the displayed best quote one second after the order. The 09:30:01 quote can be wider than later in the day. Neither order is an auction order.
- Dividends are left out of every line. That understates the overnight hold (about four dividends a year) and buy-and-hold.
- The overnight hold includes the last 59 seconds of the session and the closing auction. The intraday comparison ends at the 15:59 bar's close.
- Risk was not part of the test: volatility, drawdowns and gaps at the open were not measured. An overnight book takes every opening gap, including crash mornings.
