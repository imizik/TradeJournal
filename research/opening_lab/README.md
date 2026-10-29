# Opening lab

Does Claude's judgment add value when deciding SPY/QQQ setups in the first half
hour of the US session — beyond simple rules and calibrated coin flips — and
does more context (gap, premarket, prior day, headlines, scheduled releases)
change that? This lab answers it on many sessions quickly, by replaying stored
history causally, and runs the identical pipeline live when wanted.

It replaces the earlier passive-cache design (`codex/opening-session-runner`),
whose opening data depended on someone having the right charts open and whose
scoring produced at most one data point per morning.

## How it works

At each checkpoint 09:30–10:00 ET (every five minutes) a **packet** is frozen
from data available at that instant (`packet.py`). Claude and every rule
baseline read packets and return the same **forecast** (`contract.py`):

- `spy_p_up`, `qqq_p_up` — probability that the return from the next minute's
  open to the close ten minutes later is above zero;
- `action` WAIT / LONG / SHORT on one symbol, and a short `reason`.

Every checkpoint is scored on its own (`evaluate.py`), so one session gives 14
probability forecasts and 7 take/skip choices. The scorecard reports Brier
score, log loss, calibration, directional accuracy, net take returns at 5/10/15
minutes after a 1 bp round-trip cost, selectivity (were the takes better than
what it skipped?), latency and cost. Every comparison is **paired** on the same
checkpoints, with confidence intervals that resample whole sessions, and says
"no detectable difference" unless the interval excludes zero. It also prints the
smallest effect the sample could have detected.

Three information **variants** isolate what context adds:

| Variant | Packet |
| --- | --- |
| `bars` | today's completed regular-session 1-minute bars only (the original narrow design) |
| `market` | + prior close and gap, premarket range/volume, prior-day levels, ATR, VWAP, session range, relative volume |
| `full` | + headlines visible by then (Alpaca/Benzinga, one-minute lag) and the day's scheduled CPI/FOMC/jobs releases |

Baselines (`baselines.py`, fixed parameters, never tuned on the replay window):
coin, always_long, momentum, fade_open, opening-range breakout, VWAP side, gap
fill. They always read the `market` packet.

Causality is tested, not assumed: rewriting any future bar, later news or later
daily row leaves every packet byte-identical (`tests/test_packet.py`). The
calendar date never reaches the model; replay sessions are after the models'
training cutoffs (July 2026 on).

## Data

- Minute bars: SIP, raw, from the app's Alpaca cache in the main checkout (read
  only); anything missing is fetched from Alpaca into `.cache/` (gitignored).
  Daily bars are fetched raw into `.cache/daily/` — the app's daily cache is
  dividend-adjusted and would shift prior closes and gaps.
  July 1 – October 27, 2026 is prefetched: 83 sessions, no gaps.
- Headlines: Alpaca/Benzinga, the complete window from the prior session's
  16:00 to 10:30 ET with no count cap (a cap would let later news decide which
  earlier headlines survive), cached in `.cache/news_v3/`. Each packet keeps up
  to 15 visible headlines: economic data and Fed first, then market-wide, then
  index heavyweights; routine single-name tape (halts, analyst actions) is
  dropped.
- Macro: `backend/app/data/macro_calendar.json` (CPI, FOMC, jobs only; no GDP,
  ISM, PCE or other 10:00 releases).
- No Tradier requests, streams or production routes. Nothing here touches the
  journal, a broker or the production server.

## Run

From the repository root, with the backend virtualenv:

```bash
backend/.venv/bin/python -m pytest research/opening_lab/tests -q
backend/.venv/bin/python -m research.opening_lab prefetch --start 2026-07-01 --end 2026-10-27
backend/.venv/bin/python -m research.opening_lab replay --run research/opening_lab/runs/baselines --start 2026-07-01 --end 2026-10-27 --model none
backend/.venv/bin/python -m research.opening_lab replay --run research/opening_lab/runs/sonnet --start 2026-07-01 --end 2026-10-27 --model claude-sonnet-5-5 --estimate
backend/.venv/bin/python -m research.opening_lab replay --run research/opening_lab/runs/sonnet --start 2026-07-01 --end 2026-07-14 --model claude-sonnet-5-5 --max-cost-usd 5
```

A model replay writes `run.json`, `records.jsonl`, `packets/` and
`report.txt`/`report.json` into the run directory (`--model fake` is a free dry
run). Defaults: adaptive thinking at medium effort. Re-running the same command
resumes: answered checkpoints are kept, provider errors and timeouts are asked
again (with the later checkpoints of that morning, whose prior decisions
changed), and answers are cached by packet, so nothing is billed twice.
`--max-cost-usd` is required for paid API runs and caps the run directory's
total recorded spend across invocations; an answer with unknown cost, or 20
provider errors in one invocation, also stops new calls. A different model,
effort or code version needs a new run directory. `--backend cli` uses
`claude -p` on the Claude plan instead of the API key (its cache entries are
kept separate).

`--prompt forced` (`prompt_forced.txt`) makes Claude pick LONG or SHORT at every
checkpoint, so its picks are graded even where the standard prompt would WAIT;
the agent is named with a `+forced` suffix. `report --run A --run B` prints one
scorecard over several runs, including model-vs-model comparisons on the same
variant (no run directory's report is overwritten).

## Trade mode (options-style)

`trade` (`trades.py`, `prompt_trade.txt`) asks the question an options buyer
faces. From 09:30 to 10:00, every five minutes, Claude answers WAIT, LONG or
SHORT on SPY or QQQ, with at most one trade a morning. Once in, it is asked HOLD
or EXIT every five minutes until it exits or 30 minutes pass. A trade is graded
like a same-day at-the-money option: net = move in its favour − 2 bp spread −
0.15 bp per minute held, in basis points of the underlying. A morning without a
trade scores 0. These costs are stated assumptions, not option quotes, and
convexity is ignored.

The full variant adds a `cross` section (`cross.py`), read from raw SIP bars
with the same visibility rule:
- rates, dollar, oil, gold, volatility and small caps: TLT, UUP, USO, GLD, VIXY,
  IWM;
- eight index heavyweights;
- the 11 sector funds, plus breadth counts.

Index futures aren't in Alpaca's stock feed, so SPY/QQQ premarket stands in for
the overnight read. Headlines now run to 10:30 (`.cache/news_v3/`), so
re-checks after 10:00 see 10:00 releases.

The scorecard compares, per morning and with paired session-bootstrap CIs:
- Claude's trades;
- the same entries with a fixed 15-minute exit, or held 30 minutes, which
  separates entry skill from exit skill;
- each rule's first signal held 15 minutes;
- no trade.

```bash
backend/.venv/bin/python -m research.opening_lab trade --run research/opening_lab/runs/sonnet-trade-cli --start 2026-07-01 --end 2026-10-27 --model claude-sonnet-5-5 --backend cli
backend/.venv/bin/python -m research.opening_lab trade-report --run research/opening_lab/runs/sonnet-trade-cli
```

## Your own entries

`mytrades` (`mytrades.py`, `prompt_mytrades.txt`) replays Claude at each
journal option trade opened between 09:30 and 10:29 ET, from July 2026 on.

- **Blind question.** At the entry minute, Claude is asked whether to buy
  CALLS, buy PUTS or PASS on that stock. It isn't told what the owner did.
- **Same information as then.** The packet uses the same visibility rule as the
  lab. It holds the stock's bars and features, the stock's own headlines,
  SPY/QQQ, the cross-market section and market-wide headlines and macro.
  Single-stock minutes and raw daily bars are fetched into `.cache/stocks/`.
- **Report.** It splits the owner's real P&L by Claude's call (agree, other
  side, pass), and shows who called the underlying's 15- and 30-minute
  direction.

The journal export, from the API's `/trades`, is read from a file and kept in
the gitignored `.cache/`. It runs on the Claude plan only (`--backend cli`).

```bash
backend/.venv/bin/python -m research.opening_lab mytrades --journal research/opening_lab/.cache/journal_trades.json --run research/opening_lab/runs/sonnet-mytrades-cli --model claude-sonnet-5-5 --backend cli
```

`live --run DIR --model … --variant full` runs one morning on live Alpaca data
(start before 09:30 ET): each packet freezes at checkpoint + 5 s and an answer
after 45 s is recorded as late. Score it after the close with `report --run DIR`.
Live SIP bars from Alpaca need a paid data plan; `--feed iex` is a partial tape.

## What this does not show

- Replay measures judgment on causally frozen history, not live latency or feed
  reliability; a handful of live mornings checks those separately.
- Outcomes are underlying markouts from 1-minute bars with an assumed 1 bp cost,
  not fills. Options need their own contract selection and point-in-time option
  quotes, and a target that clears an option's spread and decay, not just the
  sign of the move.
- Eighty sessions can detect only moderate effects (the report prints the
  minimum). A null result means "no detectable edge at this size", not "none".
