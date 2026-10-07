# Swing strategies and the practice loop: roadmap

The shortest path from today's TradeJournal to this:

> I work normally. After the close, TradeJournal notices a setup worth my
> attention, my phone buzzes, I spend a minute on it, and the system records
> what I decided and what the rules then did.

Two tracks, one engine. **Research**: the [strategy factory](strategy-factory.md)
learns to judge swing trades held 1 to 16 sessions. **Practice**: the same
family code runs on each day's completed bars, sends the signal to the phone,
records Take or Skip, and tracks the rules' own trade forward.

**Status:** proposal, 2026-10-07. Nothing here is built. This plan takes
priority over the [Strategy Workbench](strategy-workbench-roadmap.md), whose
W0 remains a useful later step, and is weighed against Charts at the
[end](#first-slice-and-why-it-beats-more-charts).

## The one design choice that makes this small

**Decide at the close, act outside market hours.** A swing family reads the
session's final 30-minute bar (closing at 16:00) and signals then. The factory
already enters at the next bar's open, so the entry is the next session's
09:30 open. Everything the trader does fits around a workday:

| When | What |
|---|---|
| ~16:30 New York | the nightly job finds the day's signals and the phone buzzes |
| evening | one minute on the signal page: Take or Skip |
| before 09:30 | a market-on-open (or opening limit) order and a resting stop, placed at the broker |
| exit day, morning | a market-on-close order, when the rules exit on time |

That choice removes most of the hard parts of the factory's step 3:

- **No live stream.** The live path reads completed SIP minute bars after the
  close (the free plan's 15-minute delay has passed by 16:15). These are the
  same bars, from the same source, that the factory judged. The Tradier-versus-SIP
  mismatch check the step 3 plan worries about does not arise.
- **No new execution model.** `run_candidate` already handles a signal at a
  bar's close, entry at the next open, a stop through an overnight gap, and an
  exit at the last bar of the Nth session.
- **No "last bar" logic.** An entry window of `[1600, 1600]` restricts both
  the family and its random entries to the session's final bar. The eight
  13:00 early closes produce no signals, the same way historically and live.

## 1. What the repository already supports

| Piece | Where | Use here |
|---|---|---|
| Families decide one closed bar at a time | `factory_rules.py`, `on_bar` | the live path calls the same code |
| Execution model with overnight holds, gap fills, time exits | `run_candidate`, `Exits.max_sessions` | swing exits, unchanged |
| 30-minute bars from SIP minutes, daily bars built from them | `BarStore`, `Series.daily` | timeframe 30 is already allowed |
| Daily EMA/ATR, prior-session reads | `factory_data.daily_ema`, `daily_atr`, `prior` | trend and stop rules |
| 14 features, several meaningful at the close | `FeatureContext.at` | `trend`, `trend_slope`, `rel_strength`, `spy_trend`, `rvol` (full-day at the close), `gap`, `day_move`, `vol_ratio`, `spy_vol` |
| Gates, random entries, clustered t, the ledger, the bar | `factory_gates.py`, branch `factory/ledger` | judging, unchanged |
| Forward evidence (price after the fill against random) | `discovery_forward` | extend to session closes 1–16 |
| Weekly idea loop | `factory_brief.py`, `scripts/factory_week.sh` | proposes swing variants once families exist |
| Phone delivery with dedupe, claim, backoff, expiry | `level_alert_monitor.py`, `ntfy.py` | the same pattern for strategy signals |
| Durable jobs and lanes | `job_run`, `background-jobs.md` | the nightly signal job |
| Earnings history by quarter (date only), next report | Tradier calendars, `symbol_info_events.py` | earnings features and controls |
| News (Alpaca/Benzinga), with full text on request | `news.py` | prospective recording |
| Market gauges for the report | `packets.py` (Alpaca snapshots for SPY/QQQ/IWM/DIA/SMH and the universe file; yfinance `^VIX`, `^TNX`, live only) | not historical; shows which gauges the user reads |
| Option chains, daily OI snapshots since 2026-10-02 | `options_feed.py`, `options_recorder.py` | the later expression layer |
| Journal fills, trades, captures linked to entries | reconstructor, `capture_links.py` | compare a taken signal with what was executed |

## 2. What the ledger says about slower horizons

The recovery-swing lineage is the only idea that has made money before
costs. Read honestly:

| Version | Discovery | Confirmation |
|---|---|---|
| intraday-EMA reclaim, 2 sessions (`re-d5194badb1`) | +0.040R a trade, edge +0.051R, t 0.73 | — |
| daily-EMA reclaim (`re-d5bbe25d57`) | +0.154R, edge +0.164R, t 1.94 | — |
| daily-EMA, no first-bar trigger (`re-a9765cdc93`) | +0.180R, t 1.97 | — |
| daily-EMA + one-hour stall exit (`re-e608952717`) | +0.129R, t 2.11 | Oct 24–Jun 25 +0.186R; Jul 25–Mar 26 −0.055R; t 1.48 against 2.61 |
| daily-EMA + SPY up on the day (`re-f700e5e41e`) | +0.282R, t 2.59 | −0.009R, t 0.33 against 2.64 |
| daily-EMA held a third session (`re-3d2a12fb74`) | +0.194R, t 1.96 | — |

The forward evidence for the daily-EMA entry, against random entries:
+0.03R at 30 minutes, +0.05R at an hour, +0.11R at the close, **+0.21R at the
next session's close**, still rising.

What that does and does not suggest:

- **It is a reason to look at slower horizons, not evidence that any swing
  works.** The edge accrues over sessions rather than minutes, and the one
  exit that cut trades early (the stall exit) passed the screen and died in
  confirmation. That shape points at multi-day holds.
- **The discovery numbers are heavily selected.** Six factory variants and
  three hand-research readings of the same idea. Across six looks, chance
  alone tops t ≈ 2.39; the best discovery t was 2.59. That is barely above
  the luck line.
- **Confirmation has been seen for this lineage.** The second half
  (Jul 2025 – Mar 2026) collapsed twice. A daily-close version of the same
  reclaim is designed after those results, so its confirmation is not a
  clean test of it. Only its exam is. It must be labelled that way.
- **The third session did not help** (t 1.96 against 1.97), though the 2R
  target ends many trades before the hold matters. Holds and targets interact,
  and the forward curve is the cleaner read.
- **Everything is long, on 18 names picked in 2026, in a bull market.** Random
  entries on the same names net out average drift, but not the fact that the
  names were chosen for having trended.

## 3. The missing pieces

1. **A close-decision swing family.** All four families signal intraday.
   The daily-EMA reclaim triggers on 15-minute bars mid-session, so it cannot
   be practised around a job.
2. **Session-scale forward evidence.** Today it stops at the next close.
   Swing needs the edge at session closes 1, 2, 3, 5, 8, 10 and 16.
3. **A live path.** One function: the signals a spec gives on the last bar of
   a given day, from bars through that day. Plus a replay test showing it
   equals the historical run.
4. **The practice loop.** A nightly job, a signal record, a phone message, a
   Take/Skip page, the rules' trade followed forward.
5. **Swing features**: medium-term returns and relative strength (20 sessions),
   SPY's 20-session return (the weekly loop asked for this), distance from the
   20-session high, sessions to and since earnings.
6. **Earnings controls**, explicit and testable.
7. **A statistic that fits multi-week holds.** Week clusters understate
   dependence when a trade spans three weeks.
8. **Prospective recording** of news and context, so a clock starts now.

Everything else (macro datasets, news categories, options expression, a
broader universe) comes after the first family has a verdict and the loop
has been used.

## 4. Recommended architecture

```
research/specs ──► factory (Mac, factory/ledger) ──► ledger verdict
       │                                                  │
       └── candidate registry (research/candidates.json on main) ◄──┘
                     │  spec, stage, since
                     ▼
VPS, weekdays ~16:25 NY: factory_signals job (research lane)
   1. fetch today's SIP minutes for the universe into the factory cache
   2. for each active candidate: signals_on(spec, load, today)  ← same family code
   3. record strategy_signal rows (unique per candidate, ticker, signal time)
   4. phone: ntfy, the level-alert delivery pattern
   5. advance every open shadow trade: rerun the spec through today, match by signal time
                     ▼
/practice: the signal page (Take / Skip, before the next open), open shadow trades, history
```

- **`signals_on(spec, load, day)`** lives in `factory_gates.py` beside
  `discovery_trades`. It runs `run_candidate` on bars through `day` and
  returns the signals whose signal bar is that day's last. No other code
  decides a live signal.
- **The shadow trade is `run_candidate`'s trade**, read from a rerun through
  today and matched on ticker, side and signal time. It ignores Take and Skip,
  so the record of the rules can never be bent by a decision.
- **The candidate registry is a file on main**, `research/candidates.json`:
  spec (canonical), its id (checked against `spec_id` at load), stage, the
  date the stage began, and a one-line reason. A stage change is a reviewed
  commit, so the history is git's. No admin UI.
- **One table**, `strategy_signal`: candidate id and stage at the time,
  ticker, side, signal time, stop, planned exit session, features at the
  signal, code commit, notified/delivered times, decision (take / skip /
  none) with time and optional reason, and the shadow trade's state (pending,
  open, closed, no fill) with entry, exit, R and exit reason. Delivery fields
  follow `level_alert_event`.
- **Where it runs:** the VPS, always on, with Alpaca keys and ntfy already
  configured. It needs the factory's minute history from June 2023 for the
  universe, because daily EMAs are seeded from the start of the bars and
  parity has to be exact. That history is fetched once into a factory cache
  under `/var/lib/tradejournal`, then a day at a time. The chart history store
  holds SIP minutes too; whether it can serve as the source is a check
  (compare bars for the same minutes), not an assumption.

## 5. The first swing families

All decide at the close on 30-minute bars, enter at the next open, stop on
a daily-ATR rule and leave on time (`max_sessions`) with no target. A time
exit is the fewest-parameter exit and the easiest to execute from a desk job.
Defaults are fixed **before any run** and are textbook values, not fits. The
session-horizon forward evidence shows 1–16 sessions for information; no gate
reads it.

### 1. `trend_pullback`: a pullback within an intact uptrend

- **Rule.** Uptrend: close above the daily EMA 50, and the EMA 50 higher than
  10 sessions ago. Pullback: at least two of the last five closes at or below
  the daily EMA 20. Trigger: a close back above the EMA 20 and above the prior
  session's high. Stop: 0.25 daily ATR under the lowest low of the last five
  sessions. Exit: the close of session 8. Long only (`sides` exists for later).
- **Why it is worth testing.** Short-term reversal inside medium-term
  momentum is one of the better-documented patterns: Jegadeesh (1990) on
  one-week to one-month reversal, Jegadeesh and Titman (1993) on momentum.
  It is the daily-close form of the ledger's only before-cost lead, with the
  trend condition that lineage never had. It covers the "recovery/reclaim
  around the daily EMA" and "relative-strength leaders pulling back" ideas
  in one family; relative strength becomes a filter.
- **What weakens it.** It is related to a lineage whose confirmation has been
  seen (§2). Its exam is the clean test. Long only, in a period that mostly
  rose.

### 2. `range_breakout`: momentum continuation after consolidation

- **Rule.** Trigger: a close above the highest close of the prior 20
  sessions. Optional consolidation (`max_range_atr`, unset by default): the
  prior 10 sessions' high-to-low range at most that many daily ATRs. Stop:
  1.5 daily ATR under the signal close. Exit: the close of session 10. Long by
  default, `sides` for the short mirror.
- **Why it is worth testing.** Time-series momentum is among the most
  replicated effects across assets (Moskowitz, Ooi and Pedersen, 2012). The
  20-day breakout is its oldest trading form, with very few parameters. It
  shares nothing with the ledger, so its confirmation is a clean test. Its
  natural trade count suits 18 names: roughly one signal per name per month
  before the one-position rule.
- **What weakens it.** Single-stock momentum at days-to-weeks horizons is
  weaker than at months, and the universe was picked from names that
  trended (§10's control universe addresses this).

### 3. `earnings_continuation`: post-catalyst drift (after a decision)

- **Rule.** At the close of the first full session after a report, when the
  reaction is known whether the report came before the open or after the
  close: a gap of at least 1 daily ATR in either direction and a close in the
  gap's direction's top 30% of the range. Enter next open in that direction,
  stop at the reaction session's opposite extreme, exit at session 10.
- **Why it is worth testing.** Post-earnings drift is the most studied
  anomaly in this list (Bernard and Thomas, 1989). The trigger is a price
  reaction, which is as-of exact, and earnings dates go back to 2010.
- **Why it is third.** Eighteen names give about 70 reports in the
  discovery period, and the screen needs 100 trades. It needs a broader
  universe (decision 4) before it can be judged.

Deferred as families: sector/theme momentum (needs sector ETFs and a dated
map, §6), failed breakdown after an oversold move (reversal evidence is
strongest in small, illiquid stocks; weak prior for megacaps), and
regime-dependent long/short. Regime enters as **filters** on the families
above, not as its own family.

### Holds without a parameter hunt

- Each family has one declared hold, chosen before any run.
- The forward evidence reports the edge against random entries at session
  closes 1, 2, 3, 5, 8, 10 and 16 from discovery data only. It is the honest
  place to see where an entry's information lives.
- A different hold is a new candidate with a new id and counts toward the bar
  if it reaches confirmation. Seven holds tried one by one would cost seven
  candidates, which is the point.

### The statistic for long holds

Edge t is clustered by week. A ten-session trade spans two or three weeks,
so neighbouring clusters share market moves and the t is overstated. For
specs whose `max_sessions` exceeds 5, cluster by calendar month. That is
more conservative, and it leaves every existing spec untouched (none holds
past three sessions). This must be decided before the first swing spec is
judged ([decision 2](#13-decisions-for-the-user)). The cost is honest: 15 months of
discovery is about 15 clusters, so only a large effect can pass the screen.
That is the main argument for longer history later.

## 6. Macro and regime features

The rule: a macro feature exists only if its value at the decision time can
be rebuilt exactly as it was then. Three tiers, cheapest first.

**Tier 1: ETFs on the same SIP pipeline.** Identical timestamps, sessions,
splits and as-of behaviour as the stocks. Adding them is a longer `prepare`
list and new feature names:

| Question | Feature (new names; earlier ids unaffected) | Built from |
|---|---|---|
| Market trend, medium term | `spy_ret_20`, `qqq_trend` | SPY, QQQ |
| Breadth: equal weight vs cap weight | `rsp_vs_spy_20` | RSP, SPY |
| Small caps vs large | `iwm_vs_spy_20` | IWM |
| Sector relative strength | `sector_rs_20` | the name's sector ETF (dated, hand-kept map) |
| Risk-on vs defensive leadership | `cyclical_vs_defensive_20` | XLY+XLK against XLP+XLU |
| Rates direction | `tlt_ret_5`, `tlt_ret_20` | TLT (IEF as a check) |
| Dollar | `uup_ret_20` | UUP |
| Oil, gold | `uso_ret_20`, `gld_ret_20` | USO, GLD |
| Name's own medium-term move | `ret_20`, `rs_20`, `dist_high_20` | the name, SPY |

**Tier 2: daily official series, used with a lag.**

- **VIX level:** Cboe's daily history (free, back to 1990). The close prints
  around 16:15, after a 16:00 decision, so a decision reads the **prior**
  session's VIX.
- **Treasury yields (10-year, 2-year, the spread):** FRED. Posted with a
  lag, so read two sessions back unless ALFRED vintages show the value was
  out sooner.
- Each series is a dated snapshot file with its fetch time. A refetch makes
  a new version, never an edit.

**Tier 3: scheduled events.** FOMC, CPI, payrolls and PCE dates are
published in advance. A hand-kept file with each schedule's publication
date and source is point-in-time safe. Features: `sessions_to_fomc`,
`sessions_to_cpi`, `sessions_to_jobs`, and `macro_event_in_hold` (whether
one falls inside the planned hold, which is known at entry because the hold
is fixed).

**The reaction, not just the occurrence.** Once an event's session has
closed, its market reaction is a price fact: `spy_ret_last_cpi`,
`spy_ret_last_fomc` (SPY's return on the event session, in ATR) and
`sessions_since_*`. These answer "the market liked the print" without any
interpretation.

**Not available:** consensus estimates and surprises (no free
point-in-time source), true breadth such as % of S&P names above their
50-day (needs point-in-time constituents), geopolitical scores.
Geopolitics enters only through prices (oil, gold, defense ETFs such as ITA)
or, later, news categories (§7).

**Where your macro reading fits:** as a hypothesis written before a run
("defense names continue after a geopolitical shock when oil also rises"),
expressed with these features. It never enters as a discretionary override
of a signal. A Skip with the reason "macro" is recorded, and the shadow
record shows whether those skips helped.

## 7. News and catalysts

**Record now; backfill only after a probe.** Time is the scarce input. Every
day not recorded is lost, as the options recorder's rationale says. A
nightly append of the day's Alpaca/Benzinga articles for the universe and
the sector ETFs costs nothing and starts the clock.

### Layers

1. **Raw articles, append-only:** `(source, article_id, revision,
   created_at, updated_at, fetched_at, symbols, headline, summary, url,
   content_hash)`. A changed article is a new revision row.
2. **Deterministic features first.** These need no model:

| Feature | Definition |
|---|---|
| `news_any_24h`, `news_count_3d` | articles with the ticker in `symbols`, counted up to the decision time |
| `news_specific_share` | share of those tagged with at most two symbols (ticker-specific vs a broad roundup) |
| `stories_3d` | independent stories: articles clustered by headline similarity within 12 hours |
| `catalyst_age` | sessions since the first story of the latest cluster |
| `news_z_20` | count against the ticker's own trailing 20-session average, because Benzinga's volume changes over the years |

3. **Categories, bounded and versioned:** earnings_guidance, analyst_action,
   mna, product_customer_contract, regulatory_legal, geopolitical, ai_semis,
   crypto, energy, defense, plus scope (ticker / sector / market). Stored per
   `(article, revision, classifier, taxonomy_version)` with the input hash.
   A stored key is never recomputed.
4. **Feature names carry the version** (`cat_defense_3d_v1`), so
   reclassifying makes new features and every earlier spec id keeps its
   meaning.

### The catalyst signal is mostly price and volume

The most robust "something happened" signal is in the bars: `rvol` at the
close, `gap`, `day_move`, and the reaction session's range. They are as-of
exact and already exist. Research should use them first. News categories
later answer which kinds of shock continue, which is the useful question.

### Risks, explicitly

| Risk | Rule |
|---|---|
| **Lookahead by timestamp** | an article counts only if `created_at` plus two minutes is before the decision; live, the receive time is used |
| **Revisions** | backfilled text is the latest revision: marked approximate. Prospectively the first revision seen is kept |
| **Model knowledge** | a model trained after the events knows how a 2023 headline played out. No LLM tone or importance labels on history. Historical categories come from a versioned rules classifier; LLM classification runs prospectively only, frozen at ingestion |
| **Model-version drift** | the classifier id includes model id and prompt hash; a new model is a new classifier and new features. Agreement between rules and LLM is measured on the prospective record before either is trusted |
| **Availability and survivorship** | coverage per source per day is stored. A day the source has nothing for the whole tape is NaN, not zero. Coverage of smaller names and of earlier years is thinner, hence `news_z_20` |
| **No LLM decides a trade** | categories are inputs to specs written in advance. Nothing reads an article and says buy |

**The probe before any backfill:** articles per name per month across
2023-07 to 2026-03, gaps, and how revisions behave, recorded the way
[the symbol info roadmap](symbol-info-roadmap.md#what-the-apis-actually-return)
records its probes. If discovery coverage is thin, historical news features
are not built and news stays prospective.

## 8. Earnings and event risk

Event handling is a setting, never a hidden assumption. Each value is a
separate candidate with its own id.

| Setting | Values | Meaning |
|---|---|---|
| `earnings` (exits) | `hold` (default: no special handling) · `skip_if_in_hold` · `exit_before` | `skip_if_in_hold`: no entry when a report date falls within the planned hold. `exit_before`: leave at the close of the session before the report date |
| filters | `sessions_to_earnings`, `sessions_since_earnings` | e.g. only within 10 sessions after a report (drift) |
| `macro_event_in_hold` | filter, 0/1 | hold or avoid FOMC/CPI/payrolls |

- **Dates without a time of day** (Tradier gives dates only). `exit_before`
  exits a day early for an after-close report, which is conservative.
  Post-earnings rules act at the close of the session after the report date,
  when the reaction is known either way.
- **Historical dates are the dates that happened**, not those announced
  beforehand. For holds of at most 16 sessions most dates are confirmed in
  advance, so the error is small; the dataset is marked approximate. The
  history is a frozen snapshot file, so a refetch cannot change a past run.
  From now on a daily snapshot records which dates were known, with
  Tradier's Confirmed/Estimated status.
- **Company events beyond earnings** (investor days, product events) have
  no reliable dated history. Prospective only, through news categories.

## 9. Historical data: what is needed and what exists

| Data | Have | Need | As-of quality |
|---|---|---|---|
| SIP minutes, 18 names + SPY, June 2023 → | yes, Mac factory cache | the same on the VPS for the live path | exact |
| QQQ, IWM, RSP, sector SPDRs, SMH, TLT, IEF, UUP, USO, GLD, ITA | live snapshots only | SIP minutes from June 2023 via `prepare` | exact |
| A control universe (the ETFs above) | — | the same fetch | exact; no survivorship among them |
| Daily bars before June 2023 | Tradier daily from 1970 (chart cache, memory only); Alpaca daily cache with `adjustment=all` (dividends adjusted, unlike the factory) | only if longer history is chosen (decision 4) | exact prices; the **universe** is the problem (below) |
| VIX daily | yfinance live gauge only | Cboe history file | prior session |
| Treasury yields | yfinance `^TNX` live only | FRED / ALFRED file | two sessions back |
| FOMC / CPI / payrolls schedules | none (the market report web-searches them) | hand-kept file with sources | exact |
| Earnings dates | Tradier calendar, to 2010, date only | frozen snapshot + daily prospective snapshots | approximate |
| News | Alpaca API, live use | nightly recorder now; probe before backfill | revisions approximate |
| Option chains | daily OI by strike for the 18 names since 2026-10-02; live chains | the recorder as is | prospective only |
| Point-in-time universe (constituents, delisted names) | none | only for longer history or stocks in play | — |

**Survivorship** is the deepest problem. The 18 names were picked in 2026
from the journal, several because they trended (NBIS, PLTR, COIN, MU, AVGO).
Long momentum tested on them is flattered by the choice. Random entries
remove the names' average drift, not the selection. The cheap control: run
every swing candidate on the ETF control universe too, as information. ETFs
were not picked by outcome and all existed throughout. The real fix (a
rule-chosen universe from a broad list with delisted names) is the same
building block the factory's stocks-in-play lead needs, and a person's
decision.

## 10. Anti-lookahead rules

1. A signal is decided at the close of its bar; entry is the next session's
   open; nothing after the signal bar is read (existing).
2. Daily values come from completed sessions. Today's daily bar is read only
   by a family whose window is the session's final bar. The existing test
   "features do not change when later bars do" is extended to every new
   feature.
3. External daily series are read only once published: VIX one session
   back, FRED two, unless vintages show otherwise.
4. Event schedules count only from their publication date. Earnings dates
   are approximate and frozen.
5. News counts from `created_at` plus latency. Revisions are marked. Missing
   coverage is NaN. No historical LLM labels beyond the rules classifier.
6. The universe is fixed in code before a run. No ticker is added or removed
   because of results. Survivorship is disclosed and a control universe run.
7. Splits are adjusted by the factory's own detection; dividends are not.
   That makes long holds slightly conservative for longs over ex-dates.
8. Holds and event settings are declared before a run. Changing one is a new
   candidate.
9. The live path is `signals_on`, the same family code. A replay mismatch
   stops alerts for that candidate.
10. Practice outcomes are holdout-period data. Ideas designed after watching
    them are labelled, like ideas designed after confirmation (§11).

## 11. Practice and paper workflow

### Stages

| Stage | Who gets it | Purpose | What the record means |
|---|---|---|---|
| **Research** | any spec | the factory judges it | the ledger verdict |
| **Practice** | a close-decision spec chosen by the user, validated or not | workflow: timing, clarity, fit, Take/Skip behaviour, fills, live parity | **nothing about profitability**. Every message and page says PRACTICE, not validated |
| **Paper** | verdict `passed`, or `awaiting_exam` (passed confirmation, fewer than 30 holdout trades) | forward evidence | for `awaiting_exam`, the forward record **is** the exam filling up, with the factory's exam rules |
| **Forward-validated** | a paper candidate meeting criteria written when it entered Paper | evidence that survived time | the pre-registered test, inconclusive allowed |
| **Live** | a person's decision, tiny fixed risk | real money | journal fills, linked to signals |

Promotion and demotion are commits to `research/candidates.json`, each with
its reason. Paper's criteria (minimum trades and months, mean R after costs
above zero, edge over random entries forward) and Live's size are written
into the file **before** the forward record starts, never after.

Paper keeps the factory's rule that a candidate is judged on the trades
without a person's decisions. The shadow trade is the record; Take/Skip is
a separate behavioural record.

### Why practice before validation is right here

The factory doc builds paper trading only after confirmation, to keep
unvalidated rules from being trusted. Practice keeps that protection by
being labelled and by never feeding a verdict. It answers questions the
factory cannot: does the message arrive by 16:30, can a setup be judged in
a minute, how many arrive in a week, would you actually take them, what do
real opening fills cost, and does the live path reproduce the factory. All of
that is needed before Paper means anything, and it takes weeks of calendar
time either way. Starting it while the factory judges the family costs
nothing.

**The leak, and the rule.** Practice outcomes fall in the holdout period
(April 2026 onward). Watching them and then designing a variant contaminates
that variant's exam. So:

- the practice page shows each trade, which cannot be hidden from someone
  who looks at charts, but **no aggregate performance** (mean R, win rate,
  total) for practice candidates;
- an idea designed after practice began, in the same family, is labelled
  "designed after practice" in its notes;
- at most **two** practice candidates at a time.

### The signal page (`/practice/{signal}`)

One screen, built for a minute on a phone:

- **Header:** PRACTICE or PAPER, candidate name, ticker, side.
- **The plan:** entry at the next open (last close shown), stop price and
  distance in % and R, exit session date, risk for the configured size.
- **Why it fired:** each condition of the family with its value at the close.
  For example: "close 3.1% above the EMA 50, which is up 4.2% over 10
  sessions; 3 of the last 5 closes at or below the EMA 20; closed above
  yesterday's high." Plus the features, and earnings and macro events inside
  the hold.
- **Chart:** daily bars with the EMAs, stop and the pullback marked.
- **Take / Skip**, with optional one-tap reasons: no time, unclear, extended,
  earnings, macro, already exposed, other. Deadline: the next open. After
  it, the signal is recorded as **no decision**.
- **Open shadow trades:** each one's state, today's stop and exit date. On
  exit days a morning message: "rules exit at today's close".

### Recorded and reviewed

Per signal: delivery delay, decision and its time, reason. Per taken
signal (step S6): the journal fill against the model's open (slippage), and
the actual exit against the rules' exit (adherence). Weekly: signals per
week, share decided in time, take rate, skip reasons, and for paper
candidates the shadow record against Take-only and Skip-only results.

## 12. Underlying versus options

**First:** does the underlying signal have evidence? Everything above is in
underlying R. Option selection adds strike, expiry, spread and IV noise that
would drown a 0.1–0.3R signal, so options stay out of signal research.

**Later, the expression layer**, only for Paper or later candidates: a pure
mapping from a signal (side, entry, stop, planned hold) and a chain
snapshot to a contract, with its assumptions shown:

| Choice | Default rule to test |
|---|---|
| DTE | at least the planned hold plus 15 sessions, so theta over the hold stays modest |
| Delta / moneyness | 0.55–0.70 calls (puts for shorts) |
| Spread | skip when the bid/ask exceeds 5% of the mid; record the quote |
| IV | IV against the name's trailing IV; the expected move against the stop distance |
| Premium | sized so the stop on the underlying risks the same R budget |
| Exits | the underlying's stop and time exit drive the option exit; no option-price targets at first |

It is evaluated **forward only**. The daily recorder and live chains give
real quotes from 2026-10-02 on; there is no option history to backtest.
Each paper signal records the would-be contract's quote at the decision
and at the next open, and a daily mark. The question it answers: how much of
the underlying's R survives as the expression, after spread and theta?

## 13. Decisions for the user

1. **Where the nightly job runs:** the VPS (recommended; always on, keys and
   ntfy present, a one-time history fetch) or the Mac (no fetch, missed
   alerts when it sleeps).
2. **Clustering for holds over five sessions:** by calendar month
   (recommended), decided before the first swing spec is judged.
3. **The control universe:** run swing candidates on the ETF list as well,
   as information (recommended), or as a gate.
4. **Longer history and a rule-chosen universe:** after the first two
   families' verdicts. Fifteen months of discovery cannot detect a small
   swing edge. Longer daily history helps only with a universe free of
   hindsight, which is the stocks-in-play building block.
5. **The practice candidate and its limits:** `trend_pullback` at defaults
   (recommended), at most two practice candidates, decisions due by the next
   open.
6. **Practice visibility:** no aggregate performance for practice
   candidates (recommended).
7. **The families' defaults** in §5, confirmed before any run, since a
   change after a run is a new candidate.
8. **Paper → Forward-validated criteria and the live size**, written before
   any candidate reaches Paper.
9. **Start the news and context recorder now** (recommended; cheap), or wait.
10. **Priority:** this plan ahead of the remaining Charts items and the
    Workbench.

## 14. Milestones

Each is one slice with its own proof. S1 and S2 are the shortest path; the
rest are conditional on use or on a verdict.

| ID | Deliverable | Done when |
|---|---|---|
| **S1** | `trend_pullback` at fixed defaults; session-scale forward evidence (closes 1–16); `signals_on`; the replay parity test; the month-cluster rule if decided | synthetic-bar tests for the family's arming, trigger, stop and exits; for every discovery session, `signals_on(day)` equals the full run's signals that day; every committed spec's id and trades unchanged; the user runs it through the factory on the Mac and the ledger has its line |
| **S2** | Practice loop: `research/candidates.json`, the `strategy_signal` table (a migration), the nightly job in the research lane, ntfy delivery, `/practice` with Take/Skip, shadow trades advanced nightly | a fixture day produces exactly the replayed signals; delivery is deduplicated across restarts; a shadow trade matches `run_candidate`'s trade; the page is checked on the phone on the private origin. Then real days |
| S3 | `range_breakout`; swing features (`ret_20`, `rs_20`, `spy_ret_20`, `dist_high_20`); ETF fetch and the control universe | new features pass the as-of test; earlier ids and trades unchanged |
| S4 | Earnings: frozen historical snapshot, daily prospective snapshot, `sessions_to/since_earnings`, the `earnings` exit setting | synthetic calendars prove each setting; a refetch cannot change a past run |
| S5 | Prospective recorder: daily news (raw, revisions), Cboe VIX and FRED yields snapshots | appends only; reruns are idempotent; coverage stored per day |
| S6 | Link taken signals to journal fills: slippage and adherence; weekly practice summary | links survive a rebuild (stable fill identity, per the product roadmap's rules) |
| S7 | Macro tier 1–3 features: sector map, ETF relative features, event schedule file, reaction features | as-of tests; schedule file carries sources and publication dates |
| S8 | Expression layer, forward only | each paper signal records a chosen contract with quotes; nothing changes the underlying record |
| S9 | Longer history / rule-chosen universe (decision 4), then `earnings_continuation` | — |
| later | News probe → rules classifier → prospective LLM categories | per §7 |

## 15. What not to build yet

- Intraday live signals, streaming bars, or anything that needs watching
  a 1- or 5-minute chart.
- Broker order placement. Orders are placed by hand, outside market hours.
- More than one new family before the first has a verdict and a week of
  practice.
- Partial exits, EMA-loss trailing exits, adaptive holds. The weekly loop
  asked for them; each is a new execution-model rule and waits until a
  family shows something worth refining.
- Historical news purchase or backfill, LLM classification, any tone score.
- FRED/Cboe/ETF macro features before S1–S2 are in use.
- Options backtests (no history) or option selection inside research.
- A candidate admin UI, the Workbench UI, dashboards of practice results.
- Automatic promotion between stages.
- New intraday variants of the recovery swing.

## First slice, and why it beats more Charts

**S1: one close-decision family (`trend_pullback`), session-scale forward
evidence, `signals_on` and its replay parity test, all inside the factory's
existing engine. No UI, no database, no change to any existing spec.**

It is one agent's slice. Its proof is entirely in the existing test suites on
synthetic bars. The family follows the pattern of the four that exist. The
live-path function is a thin call to `run_candidate`. The parity test is the
same kind as "a failed screen never loads later data". The user then runs one
factory command on the Mac and gets a verdict. S2 follows directly, and the
phone can buzz within about two slices.

Why it has higher expected value than the remaining Charts items:

1. **It matches the binding constraint.** The open Charts work (G0
   acceptance, retiring the TradingView loop, replay, older-session relative
   volume) improves watching a chart during the session. That is exactly
   the time the user does not have. A close-decision loop turns the factory
   into something tradeable around a job.
2. **Forward time is the scarce input, and it only accrues once started.**
   Practice weeks, paper records and recorded news cannot be bought later.
   Every week Charts goes first is a week of forward record that does not
   exist.
3. **It follows the only lead the evidence has.** The one idea with money
   before costs has its edge growing across sessions. The factory's own
   idea model is asking for swing exits, an earnings flag and a slower regime
   feature. The 1-minute families are finished; their forward evidence says
   no exit can save them.
4. **It produces a decision either way.** A verdict on a family plus a few
   weeks of Take/Skip data says whether to continue, change horizon or stop.
   A chart feature produces no evidence about trading.
5. **Charts is largely built.** Thirty-plus items are done, and the product
   roadmap already recommends pausing chart-parity expansion after G0. G0's
   real-session check can run alongside without competing for build time.

The honest downside: the likeliest single outcome is that `trend_pullback`
fails, as everything so far has. Then S1 still leaves a working live path
and a clean test of a slower horizon, and S2 still teaches whether you would
trade such signals at all. That is cheaper to learn now than after more
features.
