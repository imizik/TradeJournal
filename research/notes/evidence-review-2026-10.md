# Evidence review: short-horizon equity effects for a Factory restart

2026-10-24. Input for whenever the owner restarts the Strategy Factory, which has
been paused as off-goal since 2026-10-16. This note is not a reason to restart it.

**Question.** Which published intraday or short-swing equity effects have the best
evidence of surviving realistic costs in large, liquid US stocks? Which of them can
the Factory test with the data it has?

**Hygiene.** The author did not read `research/ledger.jsonl`, the weekly reports,
run folders or trade files, and ran nothing. The only repository inputs were
[the Factory document](../../docs/strategy-factory.md) and the spec parser and gates
in `backend/app/engine/factory_rules.py` and `factory_gates.py`, read for spec shapes
and gate mechanics. The ranking below comes from the literature and the Factory's
structure, not from any Factory outcome. The weekly review still refuses anything
the ledger already holds, and that check stays with the review, not this note.

**Source quality.** The sandbox could reach search results but not publisher pages,
so most figures come from abstracts, repository pages or the authors' own summaries.
A figure taken from a secondary summary is marked *(secondary)*. Check those against
the paper before relying on one.

## Short answer

Almost nothing in this literature has strong evidence of surviving costs in large,
liquid US stocks at intraday horizons. Effects that clearly survive costs either live
in index futures and ETFs, where trading costs are tiny (market intraday momentum,
the overnight premium), or come from a broad cross-section where small, illiquid or
newly "in play" names do the work (stocks-in-play ORB, reversal, PEAD). For the
Factory there are three constraints on top of that, all of which follow from its
design rather than its results:

1. **Only 18 names plus SPY have discovery data.** The screen reads 2023-07-03 to
   2024-09-30. QQQ, IWM and VIXY (from 2026-01) and the 40 other large caps (from
   2026-03) start after the screen and after the first confirmation half, so no
   candidate can lean on them. (The 2026-03 names do fall inside the exam window.)
   Building sector proxies from them, or using them for breadth, does not work for
   any candidate that has to pass the screen first.
2. **A one-ticker candidate cannot pass confirmation.** The gate "still above 0
   without its best ticker" is NaN with one ticker and fails (`factory_gates.py`).
   So a SPY-only rule is out, and market-timing ideas have to be traded through the
   18 names.
3. **An unconditional premium cannot beat random.** Random entries use the
   candidate's own window, sides and exits, so "buy every name at 15:50, sell at the
   open" is the same trade as its baseline. Only conditional timing or selection
   shows up as edge: which days, which names, which side.

**What the bar demands.** Clustered by week, t ≈ (weekly information ratio) × √weeks.
The two confirmation halves cover 2024-10-01 to 2026-03-31, about 78 weeks. At the
bar of t ≥ 2.61 (K = 10, as of the Factory document; higher if more candidates have
reached confirmation since), the edge over random needs a weekly IR of about 0.30,
roughly **2.1 annualized**. The screen alone (t ≥ 2 over about 65 weeks) needs about
1.8. This is a rough calculation that treats weekly sums as independent. Most
published anomalies report Sharpe ratios of 0.5–1.5 at their best. An effect with a
published Sharpe near 1 is not detectable here even if it is fully real, so spending
a candidate on it buys nothing.

**Costs.** Per side, the Factory charges the larger of one tick or 1 bp, on entries,
stops and closing exits (targets fill flat). At these names' prices that is about
1–2 bp per side. As a share of R, costs shrink as the stop widens: about 1% of R at a
daily-ATR stop, but 5–20% at stops a tenth of an ATR beyond a one-minute setup. So an
effect has to be worth tens of basis points per trade, or be measured against a stop
on the daily-ATR scale.

## The effects

| Effect | Best evidence after costs, liquid US stocks | Published since/replicated | Factory can test now? |
|---|---|---|---|
| ORB in stocks in play | Large net figures, but one practitioner study and a broad universe | No independent peer-reviewed replication found | A proxy only: existing family + `rvol` filter |
| Market intraday momentum | Survives costs in index ETFs/futures; Sharpe ≈ 1 | Replicated across markets; signs of decay in the 0DTE era (weak sources) | Needs a new family, and fails the power test anyway |
| Sector/peer momentum, lead-lag | Monthly/weekly, in small or neglected firms; minute-level is sparse and brief | Classic results replicated; decay not tested here | No: no sector ETFs, no history for the wider universe |
| Overnight vs intraday | The pattern is robust; trading it cheaply means futures/ETFs | Long-lived; one related drift faded after publication | Only conditional versions, and only with a new family |
| Short-horizon PEAD | None in large caps since about 2006 | Decayed; disputed in 2025 | No: no point-in-time earnings dates or surprises |
| Recovery after selloffs | Reversal fails costs except as liquidity provision in high-VIX spells | Robust but illiquid-stock effect | Yes (`recovery_swing`), but few independent episodes |
| VWAP mean reversion | No primary evidence found | — | Yes (`vwap_reclaim`, `vwap_distance`); not worth a candidate |

### 1. Opening range breakouts in "stocks in play"

- **Claim.** Zarattini, Barbon and Aziz ([SSRN 4729284](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284))
  run a 5-minute ORB on more than 7,000 US stocks, 2016–2023, delisted names
  included. They trade only each day's top 20 by opening relative volume (the
  first 5 minutes' volume against its 14-day average). They report about 1,637%
  net over the period, Sharpe 2.81 and an annual alpha of about 36%, against about
  198% for the S&P 500 *(abstract/author summaries)*. The plain ORB across all
  stocks was weak: about 29% over eight years *(secondary)*. Per secondary
  write-ups, the rules are: trade in the direction of the first 5-minute candle,
  stop at 10% of the 14-day ATR, flat at the close, and costs are commissions only.
- **Strength.** Practitioners wrote it, and one author sells day-trading education.
  It is a working paper, not peer reviewed, its slippage treatment is unverified,
  and no independent post-2023 test of the filtered version turned up. The headline
  Sharpe is the only one in this review that clears the Factory's roughly 2.1. It
  comes from ranking across thousands of names, though, many of them small, and no
  large-cap subsample turned up. The mechanism (news-driven attention days) applies
  to mega caps on earnings and news days, but nobody has shown the size there.
- **Data.** A broad daily universe from 2016 or at least 2023-06, delisted names
  included, opening-volume ranking, and spread-scaled costs.
- **Factory now.** Only as a proxy. `opening_range_breakout` exists, and `rvol`
  (session volume so far against the same time of day over 10 sessions) at the first
  signal bar closely approximates opening relative volume. An absolute `rvol`
  threshold on 18 names is not the paper's cross-sectional top 20, though. A null
  result would not refute the paper; a pass would point to the broad-universe test.

### 2. Intraday momentum (first half-hour predicts last half-hour)

- **Claim.** Gao, Han, Li and Zhou, [JFE 2018](https://doi.org/10.1016/j.jfineco.2018.05.009):
  on SPY, 1993–2013, the return from the prior close to 10:00 predicts the last
  half-hour return. R² is 1.6% in sample and about 1.4% out of sample, and the effect
  is stronger on volatile, high-volume and news days. A last-half-hour timing rule
  earned about 6.67% a year at a Sharpe near 1.08 *(secondary for the Sharpe)*,
  before costs that are small for SPY.
- **Replication.** Baltussen, Da, Lammers and Martens, [JFE 2021](https://doi.org/10.1016/j.jfineco.2021.04.029),
  find it in more than 60 futures from 1974 to 2020. They attribute it to gamma
  hedging by option dealers and leveraged-ETF rebalancing, and find it reverses
  over the following days. Li, Sakkas and Urquhart, [JFM 2022](https://doi.org/10.1016/j.finmar.2021.100619),
  find it in and out of sample in most of 16 developed markets. Zarattini, Aziz and
  Barbon's "Beat the Market" ([working paper](https://www.alexandria.unisg.ch/handle/20.500.14171/122124))
  trades an earlier-entry SPY variant, 2007–2024, at a net Sharpe of 1.33. **Decay:**
  one 2026 SSRN working paper ([7290621](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7290621),
  seen only in a search snippet; a second search could not find it) reports an
  out-of-sample Sharpe of 0.39 for that variant from mid-2024. Blog retests in the
  0DTE era say the unconditional effect is gone. Treat the decay as plausible, not
  established.
- **Stock-level twist.** Baltussen, Da and Soebhag, "End-of-Day Reversal"
  ([working paper, 2025](https://www3.nd.edu/~zda/EOD.pdf)): in the cross-section of
  US stocks, a stock's own early-day return *negatively* predicts its last
  half-hour return. That effect is distinct from market momentum, comes mostly from
  buying pressure on intraday losers, and is linked to retail attention buying and
  to short sellers cutting risk before the close. Heston, Korajczyk and Sadka,
  [JF 2010](https://arxiv.org/abs/1005.3535), add that a stock's return in a
  half-hour slot continues in the same slot on later days, while returns in adjacent
  slots reverse (bid-ask bounce).
- **Data.** SPY or futures minute bars (available), optionally dealer gamma (not
  available).
- **Factory now.** No family enters at a clock time. Even with one, the trade is a
  single market-direction bet a day, so 18 names add little independent evidence.
  At a published Sharpe near 1 (less if it has decayed) it fails the roughly 2.1
  requirement above. **Not worth a candidate.** The stock-level end-of-day reversal
  is different: it is cross-sectional, which is the comparison the per-ticker
  random baseline makes. See shortlist item 2.

### 3. Sector and peer momentum, lead-lag

- **Claim.** Within an industry, big firms lead small ones because industry news
  diffuses slowly, more so for small, neglected industries and for bad news (Hou,
  [RFS 2007](https://doi.org/10.1093/revfin/hhm003)). A customer's returns predict
  its suppliers' with long-short alphas above 150 bp a month (Cohen and Frazzini,
  [JF 2008](https://doi.org/10.1111/j.1540-6261.2008.01379.x)). At the
  minute level, LASSO on the whole cross-section of lagged one-minute returns
  forecasts the next minute out of sample. The useful predictors are sparse,
  short-lived and mostly news-hit stocks (Chinco, Clark-Joseph and Ye,
  [JF 2019](https://doi.org/10.1111/jofi.12733)).
- **Strength for this use.** The large lead-lag effects run at monthly or weekly
  horizons and concentrate in less-followed firms. Among mega caps that move
  together, peer news shows up within seconds to minutes. That is too fast for the
  next-bar-open fills here and too small for 1–2 bp per side. No source found
  shows a sector or peer lead-lag rule surviving costs intraday in large caps.
- **Data.** Sector ETFs or point-in-time industry and customer-supplier maps, with
  history for the whole peer set.
- **Factory now.** No. There are no sector ETFs, and the wider names have no
  discovery history. The only peer set available is groups within the 18 (for
  example NVDA, AMD, AVGO, MU, MRVL), which would need a new feature, and the
  evidence does not justify building it.

### 4. Overnight versus intraday returns

- **Claim.** For 1993–2006, US index and stock returns were earned overnight and
  were near zero intraday. SPY's overnight-minus-day spread was about 6.8 bp a day
  (Cliff, Cooper and Gulen, [SSRN 1004081](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1004081)
  *(secondary for the numbers)*). Across 14 strategies, momentum profits come
  overnight and most others come intraday, usually with opposite signs; the authors
  call it a tug of war between clienteles (Lou, Polk and Skouras, [JFE 2019](https://eprints.lse.ac.uk/87481/)).
  Among the 3,000 largest stocks, 1996–2008, high-attention names rise overnight
  and give it back during the day (Berkman, Koch, Tuttle and Zhang,
  [JFQA 2012](https://doi.org/10.1017/S0022109012000270)), roughly +0.1% a night and
  −0.07% a day *(secondary, working-paper version)*. Mispricing factors earn during
  the day and lose in the last half hour as arbitrageurs avoid overnight margin and
  borrowing fees (Bogousslavsky, [JFE 2021](https://doi.org/10.1016/j.jfineco.2020.07.020)).
- **Decay.** In futures, nearly all of the equity premium arrived between 2 and 3 a.m.
  ET (Boyarchenko, Larsen and Whelan, [RFS 2023](https://doi.org/10.1093/rfs/hhad020)).
  A 2026 note by the same authors reportedly finds that window flat in 2021–25
  *(secondary, not read)*. The attention-reversal evidence ends in 2008.
- **Strength.** The pattern is among the most robust here. The cheap way to trade it
  is unconditionally, in futures or ETFs, and that version is invisible to the
  Factory's random baseline. The conditional, single-stock versions are older and
  have not been retested after costs in the 2020s.
- **Data.** Regular-session bars give the prior close and the open, which is enough.
  Exact closing-auction and opening-auction prices are not modelled.
- **Factory now.** Only with a clock-time family (shortlist item 2). A
  close-to-open hold is possible with `max_sessions` and `max_minutes`, but no
  family enters at a fixed time.

### 5. Post-earnings drift at short horizons

- **Claim.** Classic PEAD is real but sits in illiquid stocks. A long-short strategy
  earned about 0.04% a month in the most liquid stocks against 2.43% in the least
  liquid, and costs absorb 70–100% of paper profits (Chordia, Goyal, Sadka, Sadka
  and Shivakumar, [FAJ 2009](https://ideas.repec.org/a/taf/ufajxx/v65y2009i4p18-32.html)).
  Prices now absorb the surprise on the announcement day, and PEAD in large stocks
  has been "non-existent since 2006" (Martineau, [CFR 2022](https://doi.org/10.1561/104.00000122)).
  Two papers accepted in 2025 dispute that; a reconciliation argues the gap comes
  from research design ([UCLA Anderson Review](https://anderson-review.ucla.edu/is-post-earnings-announcement-drift-a-thing-again/)).
- **Decay.** It is the standard example of an anomaly that decayed. Across 97
  predictors, returns run 26% lower out of sample and 58% lower after publication
  (McLean and Pontiff, [JF 2016](https://doi.org/10.1111/jofi.12365)).
- **Data.** Point-in-time announcement dates and times, and consensus surprises.
- **Factory now.** No. There is no earnings calendar (the document refuses calendar
  features without a point-in-time source). `gap` catches announcement days but not
  the surprise's sign relative to expectations. Weakest prior in this list for large
  caps.

### 6. Recovery after large selloffs

- **Claim.** Short-term reversal is concentrated in high-turnover, illiquid stocks,
  and contrarian profits fall short of trading costs (Avramov, Chordia and Goyal,
  [JF 2006](https://doi.org/10.1111/j.1540-6261.2006.01060.x)). Reversal returns
  pay for providing liquidity, and they jump when the VIX is high, even for industry
  portfolios that earn little on average (Nagel, [RFS 2012](https://www.nber.org/papers/w17653)).
  Large moves without news reverse, while moves that come with information drift
  (Savor, [JFE 2012](https://doi.org/10.1016/j.jfineco.2012.06.011)). For the
  largest, most heavily traded stocks the monthly sign flips: high-turnover stocks
  show short-term *momentum*, which survives costs (Medhat and Schmeling,
  [RFS 2022](https://doi.org/10.1093/rfs/hhab055)). Older work finds rebounds of
  about two days after extreme 10-day losses that may not pay after costs (Bremer
  and Sweeney, [JF 1991](https://ideas.repec.org/a/bla/jfinan/v46y1991i2p747-54.html)),
  and opening overreactions in S&P futures that lose most of their significance
  after a bid-ask cost proxy (Grant, Wolf and Yu, [JBF 2005](https://doi.org/10.1016/j.jbankfin.2004.04.006)).
- **Strength for large caps.** Weak unconditionally. The defensible version is
  conditional: market-wide, no-news dips in high-volatility spells. Those are
  exactly the trades that cluster by week, so 15 months of discovery hold only a
  handful of independent episodes.
- **Data.** Daily bars (available), market volatility (`spy_vol` is available; VIXY
  only from 2026-01), and ideally news flags (not available).
- **Factory now.** Yes: `recovery_swing` with `spy_vol` and `rel_strength` filters
  expresses "market-wide dip in a volatile market". The weekly clustering will
  leave it short of the bar for any plausible effect size, so it is not shortlisted.

### 7. VWAP-based mean reversion

- **Claim.** No peer-reviewed study testing intraday reversion to VWAP in stocks
  after costs turned up. In the academic literature VWAP is an execution
  benchmark. The best-known VWAP paper is a trend rule with the opposite sign:
  long above VWAP, short below, on QQQ, 2018–2023 (Zarattini and Aziz,
  [SSRN 4631351](https://ssrn.com/abstract=4631351)). Public replications report
  much weaker numbers. At the minute scale, the reversal that shows up is mostly
  bid-ask bounce (Heston, Korajczyk and Sadka, above).
- **Data.** Minute bars (available).
- **Factory now.** Testable already (`vwap_reclaim`, the `vwap_distance` feature),
  but it has the weakest published support and the cost profile of a one-minute
  setup. Not worth a candidate.

## Ranked shortlist for a restart

Ranked by expected information per candidate, given the evidence, the data and the
bar. Fewer is fine: if item 1 fails and item 2's paper does not show the effect in
the largest stocks, the honest next step is item 3 or nothing.

1. **Stocks-in-play proxy, existing family.** `opening_range_breakout` at its
   defaults (5-minute range, stop at the far side, flat by the close, two entries
   and two losses a session), with one filter, `{"feature": "rvol", "min": 2.0}`,
   on the core tickers. The 2.0 is set in advance as "an unusually busy open for a
   mega cap": in practice earnings and news days. It is not to be swept: one
   candidate, one threshold. Evidence: Zarattini, Barbon and Aziz, where relative
   volume did the work and the plain ORB did not. Caveat: an absolute threshold on 18
   names is not a cross-sectional top 20, and earnings seasons cluster these days by
   week, which cuts power. A failure does not refute the paper.
2. **Missing building block: a clock-entry family. First candidate: the stock-level
   end-of-day reversal.** The family enters each ticker once a session at the
   start of `window`, on the given side, when the filters pass. Its stop is a fixed
   multiple of daily ATR(14), so the random baseline can use the same rule at any
   bar. The usual exits apply. The window should span 15 minutes, for example
   `[1530, 1544]`, so each session also gets one random entry. Candidate: long only,
   fill at 15:30, filter `day_move` ≤ −1.0 (down at least one daily ATR from the
   open), stop 1.0 daily ATR, flat at the close. Evidence: Baltussen, Da and
   Soebhag (a cross-sectional effect, which matches the per-ticker random baseline;
   its retail-attention mechanism suits names like TSLA, NVDA, PLTR and COIN),
   with Bogousslavsky as related support. **Gate before spending it:** read
   the paper's size and recent-period breakdowns, and spend the candidate only if
   the effect in the largest stocks clearly exceeds about 2 bp per trade. The same
   family would also express the overnight attention reversal and market intraday
   momentum. The power argument above rules out the latter, and the former's
   evidence ends in 2008, so neither should get a candidate first.
3. **Missing building block: a rule-chosen stocks-in-play universe.** This is
   already a lead in the Factory document. Each morning, rank a broad list (delisted
   names included, nothing picked by hand) by opening relative volume. Costs scale
   with the quoted spread, and a few multi-symbol quote calls must be able to rank
   opening volume live. Then the one candidate is the paper's own rules verbatim:
   top 20, first-candle direction, 10% ATR stop, flat at the close. It is the only
   effect here with a published Sharpe above the Factory's bar, and the only fair
   test of it. Whether to build it is the owner's call: it needs bought history back
   to at least 2023-06 and a cost model change, which is consequential Factory work.

Not shortlisted: market intraday momentum (fails the power test at its published
strength), unconditional overnight holds (invisible to the baseline), short-horizon
PEAD (absent in large caps; no calendar data), sector or peer lead-lag (wrong horizon
and universe; no data), conditional recovery swings (too few independent episodes),
and VWAP mean reversion (no primary evidence).
