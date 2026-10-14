# Jo's market watch — design (proposed October 14, 2026)

**Status: proposed design, not selected for build.** Written at Isaac's request
after the October 14 CPI session. It extends the
[shadow trader design](shadow-trader-design.md) and reuses rules already
written in the [agentic trading roadmap](../agentic-trading-roadmap.md)
(macro and catalysts, thesis versions, morning pipeline, anti-hindsight).
It changes nothing that is live: [setup scanner S1](setup-scanner-contract.md),
its ten-session acceptance and [shadow S1](shadow-s1-contract.md) keep their
rules, records and gates. Codex owns the shadow and check-service backend;
selecting any slice below goes through the
[Dots delivery board](dots-integration.md#current-delivery-board).

## What Isaac wants

Jo should pay attention to the market on its own, form a view of the day from
macro events, news and the tape, and tell Isaac without being asked when
something meaningful develops — a directional day building, a view that
failed, or a strong opportunity. Not an alert every 20 minutes, and not
invented trades. On October 14 (CPI morning, persistent selling, repeated
failed bounces) Jo said nothing, because it only wakes when a scanner setup
email arrives and S1 has no setup for that kind of day.

## The reframe

Today the system is **setup-driven**: a scanner rule fires, Jo rates or shadows
that setup, a paper trade runs. This design adds an **observation-driven**
path beside it:

| | Setup path (live, unchanged) | Market watch (proposed) |
|---|---|---|
| Trigger | S1 candidate email | Schedule plus deterministic market events |
| Jo's output | TAKE/SKIP, Go/Wait/Pass on one setup | A timestamped market read; optionally a message to Isaac |
| Baseline | S1 rules-only paper trade | Simple frozen price checks scored on the same outcomes |
| Trades | S1 contract and exits | None in the first version; a separate idea book later |

S1 observations may become inputs to Jo's read, but Jo's read never changes
S1's candidates or paper trades. That keeps S1 a clean baseline.

## What the research says (exploratory, research branch only)

Research lives on branch `claude/research-s1-orb-breakdown-put` (no PR;
`research/s1_downside_puts/`). In-sample, March 2 – October 13, 2026, SPY
trend day = at least 0.5 daily ATR open-to-close with the close in the outer
30% of the day's range (a hindsight label).

- Downside setups added to S1 (opening-range breakdown put, trend-continuation
  put) did not beat realistic option costs (profit factor 0.91 and 0.83).
- Trades on days that, in hindsight, trended made money with a VWAP trailing
  exit (about +35% return on premium); chop days lost it back. Identifying the
  day early is the problem.
- No price, breadth, volume or VIXY check called down-trend days well by late
  morning (best about one in three). Afternoon checks caught most down days,
  but little move remained after them.
- Macro days are small samples: CPI and jobs mornings mostly ended choppy;
  FOMC days leaned down (3 of 5); a gap down after an 08:30 release followed
  through more often than an ordinary gap down (2 of 5 vs 2 of 29).

These are leads, not design assumptions. They justify testing whether a
judgment-based read does better than simple checks, scored prospectively.
They do not show that it will.

## Diagnose October 14 first (MW-0)

"Jo missed the day" has several possible causes with different fixes. Before
building, establish from logs which applied:

1. Jo never woke (no setup email, no schedule) — expected under the current design.
2. Jo woke but the data it needed was missing or stale (no calendar, no broad tape).
3. Jo retrieved the data but formed no directional view.
4. Jo formed a view but had no path or permission to message Isaac.

Sources: the check-service call log (`cloud_mcp_check_ledger.py`), the scanner
email events and Jo's task history as Isaac can see it. Record the answer here.

## Records and outcomes come first (MW-1)

Nothing is evaluated until these exist. All records are append-only.

**Market snapshot** (TradeJournal, deterministic). Each section carries its
source, observation time and age, and an explicit missing/stale flag:

- SPY, QQQ, IWM: price vs prior close, open, opening range and session VWAP;
  5-minute structure (higher/lower highs, VWAP tests and whether they held).
- The S1 universe the same way, as a narrow watchlist breadth (labelled as
  such, not market breadth).
- VIXY, labelled as a short-term VIX futures ETF, not spot VIX.
- Today's economic calendar from official sources (BLS, BEA, Fed), with the
  scheduled time; consensus and actual values only when a source with
  publication times supplies them. No invented surprise series.
- Headlines already fetched by the news service, with publication and
  retrieval times, per the roadmap's [Catalyst V1](../agentic-trading-roadmap.md#catalyst-v1) rules.
- S1 observations of the day (setups, outcomes so far), read-only.

**Market read** (Jo writes, TradeJournal stores). One record per revision:

- read time, snapshot ID and hash of the inputs Jo saw;
- main interpretation and one alternative, each with supporting and
  contradicting evidence (references to snapshot fields or cited sources);
- what would change the view (objective where possible: "SPY reclaims VWAP
  and holds two 5-minute closes");
- explicit forecasts, each a typed predicate with a horizon and probability,
  for example "SPY 60-minute return below 0, p = 0.65" or "SPY closes below
  the 13:00 price, p = 0.60";
- "mixed / no useful view" is a valid read; "selling persists but no good
  entry" is a valid read;
- what changed since the previous revision. A revision never edits an
  earlier one.

**Message record**: which read triggered it, delivery time and channel,
whether it was a correction, and Isaac's optional usefulness rating.

**Outcome definitions** (frozen before the first scored read):

- Every forecast is scored at its own horizon from the read time, never from
  the open: 30 and 60 minutes and to the close, using SPY completed 1-minute
  bars. Also record the worst move against the read and the move remaining
  after it.
- Calibration (Brier score) per horizon against a frozen base rate.
- Comparator: the simple checks from the research, evaluated at the same
  times with the same outcome definitions.
- Day level: a declared trend-day label (as above) to count false alarms
  (a directional read on a chop day) and missed days (a trend day with no
  directional read before 12:00). Late reads count as late, not as hits.
- Reads made while inputs were stale or missing stay in the denominator,
  labelled.

## Wake-ups and messages (MW-2)

**Observe often, message rarely.** TradeJournal runs the event detector; Jo
is called on:

- a schedule: about 08:50 (after 08:30 releases), 09:50, 11:00, 12:30, 14:00;
- deterministic events: a scheduled release time passed, SPY crossing or
  failing at VWAP or the opening range, a new session high/low after 11:00,
  a move of N daily ATR since Jo's last read. Thresholds are set once and
  versioned.

Each wake produces a read (possibly "no change"). A **message** goes to
Isaac only when the read changes what he should consider: a directional
view forms or strengthens past a stated probability, a view is invalidated,
or a specific opportunity appears. Another red candle is not a reason.
Budget: about three discretionary messages a day; a **correction** to an
earlier message is always sent, even over budget.

Message format: the read in one line, confidence as a probability on a named
forecast, the evidence, what would prove it wrong, and which trades fit or
should be avoided, with Isaac's recorded cautions (puts in the first 15
minutes, chasing extended moves, late-day holds) as flags rather than rules.

**Wake route.** Jo wakes today only through Gmail (setup emails). Options,
to be chosen with the shadow independence work: (a) a TradeJournal email per
scheduled or event wake — available now, inherits the same
`independence-unverified` limits; (b) MCP Events on the connector
([shadow S3](shadow-build-plan.md#s3--independence-later-research-gated));
(c) a scheduled Jo task, subject to plan usage limits. The market watch is
advice to Isaac, so route (a) is acceptable for it; its reads must not feed
Shadow Isaac decisions until independence is settled.

## Replay as evidence, with limits (MW-3)

Use replay to find failures and test the workflow, not to establish
performance:

- price history replays cleanly with sealed continuation (the
  [historical replay](dot-historical-replay-contract.md) pattern, extended
  from 15-minute shares to SPY/QQQ/IWM 5-minute bars — needs a focused check
  of those interfaces before calling it an extension);
- calendar times are reliable; consensus/actual values need publication-time
  sources;
- historical news needs original publication and revision times, which the
  current fetcher does not keep;
- the model may already know famous outcomes, so replay results are labelled
  `replay-hindsight-risk` and never pooled with live reads.

Candidate set: the 2026 macro days in the research table plus a matched
number of ordinary days, so false alarms are measured too.

## Later, gated on evidence

- **Idea book**: Jo's own paper trade ideas in either direction, recorded
  before the trigger with trigger, invalidation, contract and execution
  assumptions, priced like S1, kept separate from S1 and Shadow Isaac.
  Only after reads beat the comparator on false alarms and calibration.
- **Analog days and playbooks** (CPI, FOMC, jobs, expiration, earnings):
  only when enough recorded days of each type exist to say something.
- **Scorecard screen**: after the records and outcomes above exist.

## Smallest version and acceptance

MW-0 to MW-2 with no trades. It is accepted when, over at least 20 live
sessions including at least three scheduled macro days:

1. every scheduled wake and triggered event produced a read or a recorded
   failure, with input freshness visible;
2. every read's forecasts were scored at their horizons;
3. messages stayed within budget, every correction was sent, and Isaac rated
   each message;
4. the read-versus-comparator table (calibration, false alarms, missed days,
   move remaining after the read) is reported honestly, including "no
   advantage shown".

Twenty sessions may hold only a few trend days; the first result is
descriptive. Only a measured advantage justifies the idea book.

## Choices for Isaac

- Whether to select this as the next shadow/co-pilot slice, and who builds it.
- Message channel and budget (email, phone push via the existing ntfy alerts).
- Whether Jo's market reads may see his open positions (useful advice, but
  reads then cannot feed an independent shadow).
