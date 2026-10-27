# SPY/QQQ morning pullback: frozen paper specification v1

Frozen October 27, 2026, America/New_York. Document identifier:
`spy-qqq-morning-pullback-paper-v1`. This is **not a Factory candidate ID**.

Status: specification only; unimplemented, untested and inactive. The owner
authorized prior-trial comparison and a specification freeze, not a backtest,
candidate reservation, paper collection, build, broker action or activation.
The accompanying `freeze.sha256` seals this document and `prior-trial-audit.json`.
Changing a rule requires a new version and an explicit change record before
observations are evaluated; it does not reset research lineage or attempt counts.

## Prior-trial decision

**No exact or rule-equivalent implementation was found in the inspected records.**
This is a semantic comparison of rules, not a comparison of trading outcomes.
The closest predecessors are related intraday hypotheses, so this is not an
independent discovery or evidence that the proposed setup has an edge.

The authoritative checkout was `/Users/user/TradeJournal-factory`, on
`factory/ledger`. Its 146 ledger records contain 84 distinct IDs: 76 IDs with
structured specifications and eight legacy-only IDs. Nine hand-research entries
are present; one shares an ID with a later structured recovery-swing spec.
Reservations and completion records were deduplicated by ID, not counted as
separate strategies. These counts do not assert that 84 evaluations completed.

| Structured family | Distinct IDs | Material difference from this specification |
|---|---:|---|
| `vwap_reclaim` | 13 | Requires crossing VWAP from the other side, EMA confirmation and a break of the arming bar. This setup stays on one side of VWAP and requires an ordered pullback after three five-minute closes. |
| `opening_range_breakout` | 15 | Requires a break of an opening-range boundary; this setup has no opening-range entry condition. |
| `failed_breakout` | 12 | Requires rejection of the prior day's high/low and confirmation; this setup has no prior-day level condition. |
| `recovery_swing` | 23 | Arms below a prior daily EMA, then reclaims an EMA on 15-minute bars; this setup has neither condition. |
| `s1_research` | 12 | Uses scanner ORB or stretched-price VWAP fade on five-minute bars; neither has this pullback sequence. |
| `etf_bil_exploratory_v1` | 1 | Daily ETF allocation/accounting experiment, not intraday option execution. |

All 77 JSON files under the research checkout's `research/specs/` were inspected
through rule-field extraction. The extra file is not an extra ledger ID. The
four core family implementations and their runner classes were compared at all
71 code references recorded in the ledger: available class definitions have one
AST form each, excluding class docstrings. ORB is absent at five earlier refs.
No recorded code reference was unavailable. AST comparison establishes consistency
of those class definitions only, not every dependency or historical runtime.
The S1 adapter and scanner source also each have one byte-identical form across
the 12 code references associated with the recorded S1 IDs.

The eight legacy-only IDs cover two Market Map versions, four VWAP variants and
two NBIS variants. Archived Pine/rule documents were recovered read-only from
Git revision `8f343d79`; current Python Market Map and scanner rule sources were
also inspected. Market Map retests require a previously broken opening-range or
prior-day level and EMA conditions. They overlap conceptually with continuation
but do not express this exact sequence. The archive does not preserve a complete
execution manifest for every old manual experiment; an unrecorded discretionary
equivalent cannot be ruled out. No claim of global strategy novelty is made.

See `prior-trial-audit.json` for IDs, rule-field digests, source-file hashes and
code references. No period metrics, verdicts, trade rows or protected exam
artifacts are copied into the audit. Existing documentation/spec notes contain
older research summaries; those summaries were not used to choose these rules.
No historical market bars, option paths or performance runs were opened here.

## Scope and fixed choices

| Item | Frozen value |
|---|---|
| Underlyings | SPY and QQQ only; separately recorded, not independent market samples |
| Instrument | Buy one standard call for a long signal or one standard put for a short signal |
| Trading clock | America/New_York; source/receipt timestamps retained in UTC |
| Signal closes | 09:45:00 inclusive to 11:00:00 exclusive |
| Actual paper entry | Must also be before 11:00:00 |
| Structure | Completed one-minute bars; aligned five-minute trend bars |
| Opportunity budget | First eligible trend arm and its first pullback per ETF per session; no rearm |
| Portfolio | One reserved/pending/open position across both ETFs; at most two entries per session |
| Target | 1.5 underlying R; no partial exits or trailing stop |
| Time exit | 15 elapsed minutes after paper entry; absolute exit intent by 11:15 ET |
| Position size | Exactly one contract for paper dollar accounting; no account-level return or sizing claim |
| Mode | Disabled paper specification, no order endpoint or automatic activation |

The 15-minute cap, 1.5R target, expiry range, liquidity bounds and latency settings
are design choices, not estimated optima. The earlier invalidation study did not
validate a universal time or option-percentage stop. This version adds no news,
RVOL, EMA, dealer-positioning, earnings or discretionary chart filters.

## Market data and causal clock

1. Use consolidated, unadjusted regular-session ETF data and genuine consolidated
   option NBBO observations. IEX-only, delayed/sandbox and indicative option feeds
   are ineligible. Record the actual provider/feed; no silent provider fallback.
   Provider entitlement, completeness and timestamp semantics remain unverified.
2. Minute bars cover `[09:30,09:31)`, etc. Five-minute bars aggregate exactly five
   contiguous minute bars anchored at 09:30. A bar is usable only after its end.
   Use the first completed version actually received, retaining revisions without
   retrospectively changing a decision. Require finite positive prices, valid
   OHLC ordering and nonnegative volume; duplicate/conflicting or missing minutes
   invalidate that ETF for the rest of the session. No forward filling.
3. Session VWAP at minute end m is
   `sum(((high + low + close) / 3) * volume) / sum(volume)` from 09:30 through m.
   Zero cumulative volume is unavailable. This bar-based VWAP is explicit; do not
   substitute a chart provider's differently calculated VWAP. Five-minute closes
   use VWAP at their respective ends, not the current value for all three bars.
4. Each minute is decided at its end plus five seconds. Required bars must have
   arrived by that deadline. Later arrival invalidates that ETF's session; do not
   reconstruct a missed decision. Both ETFs use this same deadline, so simultaneous
   signals can be resolved without waiting for whichever feed happens to win.
5. Eligible live observations retain exchange/source time, local receipt time,
   symbol, feed and sequence where supplied. Source time must not be in the future
   relative to receipt. The receiving clock must be synchronized within 100 ms;
   unknown synchronization makes the session ineligible. Freeze the calendar/feed
   identity before any separately authorized collection.
6. Observe only a verified exchange session opening at 09:30 with scheduled close
   after 11:15. Normal 13:00 early closes use the same morning window. Unknown
   calendars, late openings or halts refuse new entries. A known feed outage or
   monitoring-process heartbeat gap over five seconds while exposed makes the
   position unresolved. A quiet stream with verified connection health is not by
   itself a missing-trade interval. Do not backfill an outage into a paper fill.
   A future capture must record process/connection health at least once a second;
   unknown health refuses entry. This requirement does not start a collector.

## Exact signal state machine

State is independent per ETF and resets only at the next exchange session.
All strict inequalities below reject equality. Let `s=+1` for calls and `s=-1`
for puts. Only information available by the minute decision deadline is used.

**Waiting for a trend.** At the first five-minute close in the signal window
whose three most recent completed five-minute closes `C1,C2,C3` satisfy
`s*(C2-C1)>0` and `s*(C3-C2)>0`, with `s*(Cj-VWAPj)>0` for each j, arm that side.
For calls the three closes rise above VWAP; puts mirror this below VWAP. There
is at most one arm per ETF per day, even if it later fails. No pre-arm minute
is retrospectively counted as the pullback. Earliest arm is 09:45.

**Waiting for the first pullback.** After arming, the first minute with
`s*(close_m-close_(m-1))<0` begins the pullback. Before then, neutral or
trend-direction closes may continue. At each new five-minute close the same
three-close trend test must still hold for the armed side; otherwise retire the
ETF for the session. At a five-minute boundary perform this check before the
one-minute pullback/trigger check.

**Staying on the VWAP side.** Every one-minute bar after the arm, including the
pullback and trigger, must have `low > its bar-end VWAP` for calls or
`high < its bar-end VWAP` for puts. Failure retires the ETF. This is a comparison
of the completed bar's extreme with its endpoint VWAP; it does not assert an
unobserved intrabar VWAP path.

**Pullback and confirmation.** The pullback consists of one to three consecutive
adverse-close minute bars as defined above. Beginning with the minute after the
first pullback bar, a call triggers on `close > preceding_bar.high`; a put
triggers on `close < preceding_bar.low`. If no trigger, another adverse-close bar
extends the pullback up to three bars. A fourth adverse-close bar, an unchanged
close, or a favorable close that does not clear the preceding bar's extreme
retires the ETF. The confirmation may follow the third pullback bar, but cannot
itself be counted as an adverse pullback bar. No second pullback is sought.

**Structural stop.** Freeze `L=min(pullback lows)` for calls or
`L=max(pullback highs)` for puts; the trigger bar is not part of the pullback.
Reject a call trigger whose low is at/below L, or a put trigger whose high is
at/above L, because it already invalidated the structure. No ATR or tick buffer
is added. Earliest possible trigger is 09:47 (one post-arm pullback minute and
one subsequent confirmation minute).

**Admission.** Save every trigger and its disposition. A trigger is used up even
if busy, unavailable or rejected. Existing pending entry, open position or
unresolved exposure blocks both ETFs. If both trigger on the same bar, SPY takes
the portfolio slot and QQQ is recorded `skipped_simultaneous`; there is no fallback
to QQQ if SPY later fails contract/fill checks. The tie-break is administrative,
not based on expected profitability. A busy signal is not queued for later entry.

## Option selection

For an admitted signal, reserve the portfolio slot at decision time `Tsignal`.
Use the first complete listing/chain response received after Tsignal and by
`Tsignal + 10 seconds`. If unavailable, record `no_chain` and release the slot;
the ETF remains used up. No search across later snapshots for a better contract.

1. Let `Sselect` be the latest eligible regular-session ETF trade received by the
   chain response time, with source age at most two seconds at that time. Missing
   or ambiguous trade data yields `no_underlying_reference`.
2. From contracts actually listed in that response, choose the earliest expiration
   with **2 through 5 calendar days**, inclusive, from the entry session's ET date.
   No eligible expiration means `no_expiry`; no 0DTE/1DTE/6DTE fallback.
3. Require the matching call/put type, exact underlying/root SPY or QQQ, USD premium,
   multiplier 100 and confirmed standard delivery of 100 shares of that ETF.
   Adjusted contracts are excluded. Uncertain deliverables, missing size metadata
   or conflicting OCC-symbol/strike/type/expiry fields that could affect which
   standard contract is nearest invalidate selection; do not skip past an unknown
   contract to choose a farther strike.
4. Calls: choose the largest listed strike **strictly below** Sselect. Puts: choose
   the smallest listed strike **strictly above** Sselect. An exactly ATM strike
   is excluded. Thus this is the nearest strictly ITM contract, not delta targeting.
   Duplicate identities at the chosen strike are a data error, not a tie-break.
5. Lock this contract. Do not switch strikes or expirations because its quote is
   unattractive. Delta, IV, open interest and volume may be recorded if present,
   but do not filter or rank contracts; their absence does not fabricate a value.

## Entry pricing and liquidity

Selection completes at `Tintent`. This is a simulated buy intent, never a broker
order. The latency allowance starts then, not at the earlier signal bar.

- Wait a fixed **two seconds**. Use the first same-contract consolidated two-sided
  quote received at or after `Tintent+2s` and at or before `Tintent+10s`, with both
  bid/ask source timestamps at/after Tintent+2s, neither more than two seconds old at
  receipt, and neither in the future. Require positive prices, `ask >= bid`, and
  displayed bid/ask sizes of at least one contract. A locked market is allowed;
  crossed, stale and malformed quotes are logged but are not valid observations.
- On that **first otherwise valid quote**, require `ask-bid <= $0.05` **and**
  `(ask-bid)/((ask+bid)/2) <= 0.02`. Failure is `spread_rejected`; do not wait for
  tightening. These are fixed feasibility constraints, not fitted thresholds.
- The latest eligible ETF trade already received must be no older than two
  seconds. Set its price to Sentry and require `s*(Sentry-L)>0`. Any observed
  structural-stop touch between signal and entry cancels entry, even if the ETF
  subsequently recovers. An outage or unknown ordering cannot be treated as no touch.
- Entry must occur before 11:00 ET. A late, absent or invalid reference gives an
  unfilled disposition; no later substitute. Fill one paper contract at the
  observed **ask**, with paper fill time equal to local quote receipt time.
- Freeze underlying `R=s*(Sentry-L)` and target `Sentry+s*1.5*R`; neither moves.
  R is ETF price distance, not option dollars or a guaranteed maximum loss.

This is an observable quote-price counterfactual. Displayed size does not prove
an order would fill, particularly after network/manual latency. No midpoint,
option last trade, OHLC low, theoretical price or retroactive fill is substituted.

## Monitoring, exit intent and exit pricing

Monitor eligible consolidated regular-session ETF trade events after entry.
An eligible print identifies the exact ETF, has finite positive price and size,
is eligible for the feed's regular last-sale/OHLC calculation, and is neither a
cancellation nor an out-of-sequence correction. Source time must be within the
regular session, not in the future, and no more than two seconds before receipt.
A missing condition/sequence interpretation is a data-contract failure, not a
permission to accept every print. A stale otherwise eligible print while exposed
makes the position unresolved because it may conceal the first crossing.
Only prints with source time at/after the paper-entry receipt time are eligible
to trigger; delayed pre-entry prints cannot stop or target a new position.
Record source and receipt times separately. The first trigger actually observed
creates one immutable sell intent; it is never moved to an earlier source time.

- Stop: `s*(trade_price-L) <= 0`.
- Target: `s*(trade_price-target) >= 0`.
- Time: local paper-entry receipt time plus 15 minutes, or 11:15 ET, whichever
  is earlier. This does not restart after delayed data or price recovery.
- If events have identical receipt time, process reliable source sequence first;
  when a timed exit ties with a known crossing, precedence is stop, target, time.
  If ordering between different crossing prints cannot be established, mark
  `unresolved_event_order` instead of inferring a path from minute OHLC.

For the first exit intent at Texit, apply the same two-second latency, ten-second
deadline and fresh two-sided quote requirements as entry, including both quote
side source times at/after Texit+2s. Sell at
the **bid** of the first valid quote. There is **no exit spread-percentage or
dollar-width rejection**: a costly but valid bid is still the liquidation price.
Require positive bid and displayed bid size of at least one; zero-bid/no-size
markets are unresolved, not assumed free liquidation. No partial exits or rolls.

No admissible quote by Texit+10s gives `unresolved_exit`, retains the position's
entry debit/exposure in the record and blocks all further session entries. A
monitoring outage, halt or missing event ordering while exposed is also unresolved.
Do not drop unresolved positions, extend the deadline until a better quote, mark
them as flat, or carry them into a new session as resolved trades. Later prices
may be retained as explicitly non-primary observations, never replacement fills.
Unresolved exposure blocks subsequent sessions until owner review; that review
cannot retrospectively create a primary fill.

Minute bars alone cannot implement these crossing semantics. A historical bar
that touches stop and target is insufficient; this specification requires an
ordered, timestamped event capture. Existing minute-bar replay or slow scanner
polling cannot be represented as compliant execution without separate proof.

## Costs, risk and future accounting

For a resolved one-contract observation, let A be entry ask and B be exit bid:

- Model all-in fees at **$1.00 per contract per side** ($2.00 round trip). This is
  a fixed research allowance, not a quotation or upper bound on the user's fees.
- Net paper dollars: `100*(B-A)-2.00`.
- Return on premium: `net_dollars/(100*A)`; this denominator excludes fees and
  must be labelled consistently. Also retain cash debit `100*A+1.00`.
- Required cost-stress view: add **one additional observed spread per side**:
  entry `A+(entry_ask-entry_bid)`, exit
  `max(0, B-(exit_ask-exit_bid))`, with the same $2 fees. Do not call this a fill
  or a statistical validation gate. No stress parameters may be selected later.
  Report stress dollars; if also reporting stress return, divide stress net dollars
  by 100 times the stressed entry price and label that denominator.
- For unresolved positions with actual paper exposure, report count and total
  entry debit at risk. Any future summary must separately show a sensitivity
  treating each unresolved position as full premium loss plus both model fees;
  never report resolved-only profitability as the complete strategy result.
- At most one long option contract is exposed at once. The structural ETF stop
  cannot guarantee the option loss. No borrowing, averaging, scale-ins, premium
  percentage stop, discretionary overrides or assumed borrowing are modelled.

No dollar risk budget, account size or suitability determination is inferred.
One contract is a measurement unit, not authorization to risk its premium live.
SPY and QQQ outcomes share market shocks; any later inference must preserve
day/week clustering and research lineage rather than count both as independent.

## Required evidence and authorization boundary

Any later authorized implementation must preserve: spec hash/version; calendar
and feed identity; original source/receipt times; input bars/VWAP and trend arm;
pullback members; signal and rejection reason; simultaneous/busy decisions;
chain response identity, Sselect and locked OCC contract; all quote eligibility
decisions; entry/exit intents and priced observations; Sentry/L/R/target; outages,
unresolved exposure, fees and observed spreads. Record no-trade sessions as well
as trades. Missing fields stay missing. No LLM TAKE/SKIP overlay is part of v1.

The next independently testable milestone is **fixture conformance**, if separately
authorized: mirrored sides, first-pullback retirement, five-minute boundaries,
simultaneous signals, calendar-DTE weekends, exact-ATM exclusion, adjusted-contract
refusal, stale/wide/zero-bid quotes, latency, stop-before-entry, both-cross ordering,
timeouts and unresolved-position blocking. Those fixtures have not been built or run.

The strategy specification is frozen; a study window, statistical decision plan
and authorized run are **not** established. No data collection begins from this
document. Existing Factory splits, ledger, budgets and gates stay untouched; no
scratch ledger, renamed retry or informal paper scoring may bypass them. Before
any performance evaluation, the owner must approve an eligible protocol and its
attempt accounting. Current Factory/scanner interfaces do not express this full
multi-timeframe, two-ETF portfolio and option-event execution specification.

No claim is made that current accounts provide the necessary feeds, that the
historical cache covers this design, or that existing infrastructure implements
it. Public provider documentation establishes only a possible data route:
[Alpaca](https://docs.alpaca.markets/us/docs/historical-option-data) describes
subscribed OPRA quotes, indicative-feed limitations and history from February
2024; [Tradier](https://docs.tradier.com/docs/quotes) describes consolidated data,
delayed sandbox data and lack of expired-option history. No authenticated market
request, credential read, order or account request was made for this freeze.

Both `com.tradejournal.factory-search` and `com.tradejournal.strategy-factory`
were confirmed unloaded. Live execution was not enabled. Source ledger, gate,
rule and budget-file hashes remained unchanged against the prior audit receipt.
