# Radar social buzz: feasibility study

October 24, 2026. A desk study only: no code, keys, sign-ups or scrapers. It asks
whether [Radar](radar.md) should gain a "social buzz / narrative" signal, an
unusual rise in discussion of a ticker, sector or narrative, that surfaces
opportunities outside Isaac's watchlist early enough to investigate (the
Discover step of the [end goal](product-roadmap.md#end-goal--october-22-2026)).

## Recommendation

**No-go on building a live buzz signal now. Go only for a free, record-only,
pre-registered forward test after the premarket pilot is scored.**

- The one free, low-friction source left (ApeWisdom's keyless Reddit
  mention counts) has no history API, so a back-test isn't possible and the
  only honest test runs forward. X is the only source with real intraday depth,
  and it's priced per post read, which rules out a market-wide sweep for a
  single user. Reddit's official API and Stocktwits are effectively closed to
  new personal builders.
- The research mostly says attention spikes are a *volume and volatility*
  signal that coincides with or follows price, with next-day reversal, not a
  dependable lead. That matches Radar's premarket finding that volume, options
  volume and headlines found almost none of the intraday moves earlier than
  price ([Premarket pilot](radar.md#premarket-pilot-record-only)).
- Confidence: moderate. The main thing that could flip it is a narrow
  sub-case: names that start trending on Reddit before the US open with little
  premarket move. No study tests that on 2026 data, which is why a small forward
  test is still worth $0 and a few hours.

The top risk: the signal mostly echoes moves Radar and Movers already
see, so it adds noise (bots, pumps, common-word tickers) without adding lead
time.

## What the repository already has

- **Prices:** Tradier quotes for the Radar list (169 stocks plus benchmarks)
  (`backend/app/data/radar_universe.json`); Alpaca SIP minutes, used for the
  October 12–23 back-test.
- **News:** Alpaca/Benzinga (`backend/app/engine/news.py`, used by
  `backend/app/engine/radar_news.py`) and Polygon `/v2/reference/news` with
  Polygon-supplied per-ticker sentiment (`backend/app/engine/symbol_info_news_feed.py`).
- **Ticker map:** SEC `company_tickers.json`, already fetched and cached by
  `backend/app/engine/symbol_info_financials_feed.py`. It would serve as the
  whitelist for ticker extraction.
- **FMP:** there's no Financial Modeling Prep integration in the code or docs,
  despite the brief. FMP's v4 `historical/social-sentiment` docs page is marked
  "legacy endpoint" ([FMP docs](https://site.financialmodelingprep.com/fr/developer/docs/social-sentiment-api),
  seen 2026-10-24). Adding FMP for that would mean a new paid provider for a
  deprecated feed. Not recommended.
- **Nothing social:** no Reddit, X or Stocktwits code anywhere.

Reuse option at no cost: a market-wide *headline-count* velocity from Alpaca
news (one request with no symbol filter returns all symbols). It's "narrative
buzz" from the press, not the crowd. The premarket back-test already found that
headlines rarely came before price, so it isn't a lead candidate. It belongs
under the existing "news nearby" context.

## Source comparison

Prices are for one personal user, as of the dates given. "Unverified" means only
third-party pages were reachable: this container couldn't fetch docs.x.com,
redditinc.com or apewisdom.io, so confirm before spending money.

| Source | Access today | Cost / month | Rate limit, history, latency | Terms risk for personal alerts | Signal quality | Fit |
|---|---|---|---|---|---|---|
| **ApeWisdom API** (Reddit-derived: WSB, r/stocks, r/options and others) | Public, no key. `GET /api/v1.0/filter/{filter}` ranks tickers with `mentions`, `mentions_24h_ago`, `upvotes` ([NexusFi listing](https://nexusfi.com/d/data-providers/ape-wisdom/); [AltIndex review](https://altindex.com/reviews/ape-wisdom) mentions a paid tier; unverified) | $0 | Rate-limited, number unpublished. **No history endpoint**, only a current snapshot with a 24-hour comparison; web timelines are not an API. Update cadence unpublished. | Low for us, unclear upstream: we would read a published aggregate, but ApeWisdom's own Reddit collection terms are not visible. It could disappear without notice. | Ticker extraction already done (quality unknown). Counts mentions, not unique authors, so one spammer can inflate it. Small-cap coverage is good; that is WSB's whole beat. | **Best test candidate.** No key, tiny volume (a few calls an hour). |
| **Reddit Data API** (official) | Since **Nov 11, 2025**, new OAuth access needs approval under the Responsible Builder Policy; self-service is closed ([r/redditdev announcement, mirror](https://r.datuan.dev/r/redditdev/comments/1oug31u/introducing_the_responsible_builder_policy_new/noh6fun)) | $0 if approved for non-commercial use; commercial is negotiated (third-party figures of ~$12k a year or month disagree: [socialcrawl, 2026](https://www.socialcrawl.dev/blog/reddit-api-key-limits-alternatives-2026), [octolens](https://octolens.com/blog/reddit-api-pricing)) | 100 queries/min per client (third-party, consistent). Listings reach back ~1,000 items; no historical search (Pushshift is closed to the public). Near real time. | Medium: personal and non-commercial plausibly fits, but approval is discretionary. Scraping old.reddit or JSON endpoints without OAuth breaks the terms. | Raw text: we would do our own ticker extraction and author dedupe (good: author IDs exist). WSB is bot-heavy and meme-heavy. | Only worth it if ApeWisdom proves the idea and author dedupe matters. Needs an access request (Isaac's call). |
| **X API v2** | Pay-per-use since Feb 6, 2026; free tier gone; legacy Basic and Pro migrated by Jun 1 and Sep 1, 2026 ([upload-post, 2026](https://www.upload-post.com/x-api-pricing/), [bundle.social, Jul 27, 2026](https://bundle.social/blog/x-api-pricing-2026-costs-limits); unverified) | ~$0.005 per post read, so $5 per 1k posts. A market-wide cashtag sweep of even 20k posts a day is about **$3,000/month**. Counts-only `Counts: All` appears at ~$0.01 per request ([docs.x.com pricing, snippet](https://docs.x.com/x-api/getting-started/pricing)): ~170 symbols hourly over 7 hours is about $250/month, and it only covers symbols you already list | Recent search ~450 req/15 min; 2M post reads/month cap on pay-per-use ([docs.x.com post cap](https://docs.x.com/x-api/fundamentals/post-cap)). Full archive exists at a cost. Seconds of latency. | Low for read-only personal use through the API; scraping is barred. | Worst spam: 71% of suspicious cashtag authors were classified as bots ([Cresci et al., ACM TWeb 2019](https://arxiv.org/abs/1804.04406)). Cashtags help extraction. | Too expensive for discovery outside the watchlist, which is the point of the feature. |
| **Stocktwits** | No working public developer access for new apps: integrators reported it removed ([OneUp help, Oct 4, 2024](https://help.oneupapp.io/en-us/article/does-oneup-support-stocktwits-1fxjlx0/)). Terms updated **Jul 10, 2026** bar scraping unless authorized in writing or through an approved API ([Stocktwits terms](https://stocktwits.com/about/legal/terms)) | n/a | The internal "trending" endpoint exists (third-party scrapers use it), but it's unsupported. | **High.** The only route today is scraping, which the terms forbid. | Best native fit (cashtags, finance-only users). | No-go unless Stocktwits offers a licensed feed. |
| **Google Trends API** | Alpha since **Jul 24, 2025**, gated by application, "very limited" ([Google Search Central](https://developers.google.com/search/blog/2025/07/trends-api)) | No published price | Daily/weekly granularity, no "Trending Now". | Low via the API; unofficial scrapers (pytrends-style) are a ToS risk. | Weekly-horizon attention signal (Da et al., below). Ticker vs word ambiguity is bad ("Apple"). | Wrong horizon for intraday Radar. |
| **Quiver Quantitative** WSB dataset | Paid API; "pricing starts at $10/month" per its package page ([PyPI quiverquant](https://pypi.org/project/quiverquant)); daily WSB mention counts, ~6,000 equities since Aug 2018 ([QuantConnect](https://quantconnect.com/docs/v2/writing-algorithms/datasets/quiver-quantitative/wallstreetbets)) | ~$10–30 (unverified tier) | Daily frequency, so it can't measure intraday lead. History back to 2018. | Low (licensed). | Pre-extracted from daily threads. | Only for an optional retrospective *next-day* test. |
| **Alpaca/Benzinga news** (in repo) | Already keyed | $0 extra | One fast page per call, history available. | Already in use. | Press, not crowd. Headlines rarely led price in the back-test. | Reuse for context, not for lead. |
| **Polygon news + sentiment** (in repo) | Already keyed; 15-minute cache budget | $0 extra | Per symbol. | Already in use. | Provider sentiment, press only. | Same as above. |

Other WSB mention dashboards (Swaggystocks-type sites) were not evaluated
individually; none showed up with a documented API, and they would duplicate
ApeWisdom for this test.

### Recommended stack and monthly cost

For the test: **ApeWisdom (free) + existing Alpaca SIP minutes and Radar
store = $0/month.** No key or sign-up; tiny request volume.

If the test passes and author dedupe turns out to matter, request Reddit API
access (still $0 if approved). Optionally, Quiver (~$10–30/month) for a
daily-horizon retrospective check. X stays excluded unless a single-digit list
of narratives justifies the ~$250/month counts approach, and that list wouldn't
be outside-the-watchlist discovery anyway.

## What the evidence says

The research consistently shows that attention moves with or after price, and
any return follow-through tends to reverse:

- **Attention predicts *lower* next-day returns; sentiment slightly higher.**
  Attention is highly correlated across Twitter, StockTwits and Seeking Alpha,
  even after controlling for news ([Cookson, Lu, Mullins & Niessner, "The Social
  Signal", JFE 158, Aug 2024](https://ideas.repec.org/a/eee/jfinec/v158y2024ics0304405x2400093x.html)).
  A buzz spike is mostly the crowd reacting to something.
- **WSB due diligence used to carry information, then stopped.** Before
  GameStop, WSB DD posts predicted returns and cash-flow news. After it, they
  didn't, as posts shifted to price-pressure and attention plays ([Bradley,
  Hanousek, Jame & Xiao, RFS 37(5), 2024](https://scholars.uky.edu/en/publications/place-your-bets-the-value-of-investment-research-on-reddits-walls/)).
  The relevant regime is the post-2021 one.
- **Search attention: a 2-week price rise, then reversal within the year**
  (Russell 3000, 2004–2008; [Da, Engelberg & Gao, JF 2011](https://projects.nber.org/confer/2009/mms09/Da_Engelberg_Gao.pdf)).
  That's a weekly horizon, and the effect is retail price pressure, not
  information.
- **StockTwits pressure reverses the next day** ([Awais, Sheffield thesis](https://etheses.whiterose.ac.uk/29647));
  pre-earnings social optimism reverses at the announcement (CUHK conference
  paper, [CUHK-RAPS-086](https://www.cuhk.edu.hk/fin/event/CUHK-RAPS-RCFS-Conference2024/Papers/CUHK-RAPS-086.pdf)).
- **Where a lead does show up, it's at volume *spikes*:** StockTwits
  polarity doesn't predict next-day returns on average, but does around sudden
  message-volume peaks ([SFI WP 21-33](https://www.sfi.ch/en/publications/n-21-33-event-studies-on-investor-sentiment)).
  StockTwits volume is a top predictor of *volatility* ([Audrino et al., IJF 2020](https://alexandria.unisg.ch/handle/20.500.14171/112549)).
  That's the one hook for a spike detector, and it points at "something will
  move", not a direction.
- **Bots and spam:** cashtag piggybacking. Coordinated bots attach low-value
  tickers to popular cashtags (Cresci et al., above). Any detector without author
  dedupe and age filters will mostly find pumps.

What's missing: no credible study tests *intraday*, pre-open Reddit buzz
against the first-hour move on recent data. The studies above are daily or
weekly. That gap is the only reason not to stop at no-go.

## Simplest attention-velocity detector (sketch, not built)

Unit: symbol × hour, with session-aware buckets (overnight 16:00–08:00 as one
bucket, then hourly 08:00–16:00 ET).

```
inputs per poll (ApeWisdom, all-stocks filter, top 100):
  symbol, mentions, mentions_24h_ago, upvotes, rank

ticker hygiene:
  keep only symbols in SEC company_tickers.json and with a US listing
  drop ETFs/indices unless the narrative is the point (keep a separate group view)
  common-word blocklist unless the source marks it as a cashtag:
    A, ALL, IT, ON, ARE, FOR, NOW, GO, BIG, OPEN, CEO, DD, YOLO, EV, AI, ONE, SO, RH, CAN, BE, HAS

per-symbol series:
  m[t]   = mentions in the bucket (delta between consecutive polls)
  base   = median and MAD of m for the same bucket-of-day over the previous 20 sessions
           (bucket-of-day matters: WSB volume swings with the clock and weekends)
  if fewer than 10 prior sessions observed -> no flag ("warming up")

spike when all hold:
  m[t] >= 15                                   # floor against small-count noise
  m[t] >= 3 * max(base.median, 1)
  (m[t] - base.median) / (1.4826 * base.MAD + 1) >= 4
  m[t] + m[t-1] > 2 * m[t-2] (still accelerating, not one burst)

author dedupe:
  ApeWisdom counts mentions, not authors -> not possible at this tier.
  With Reddit or X data: count unique authors per bucket, cap one author at 1 per bucket,
  ignore accounts under 30 days old or with >50% of posts on one ticker.

price-echo tag (always recorded, never hidden):
  move_at_flag = |return vs SPY since prior close| at flag time (Alpaca SIP minutes)
  echo  if move_at_flag >= 3 points
  lead  if move_at_flag <  3 points

narrative/sector rollup:
  sum spikes per Radar curated group / sector ETF; flag a group when >= 3 member symbols spike
  within 2 buckets (reuses the radar_universe groups; no new taxonomy)
```

Only "lead" flags are candidates for Radar. Echo flags are context: the
crowd noticed what Radar already shows.

## Pre-registered offline test

Retrospective intraday history doesn't exist at a usable cost (ApeWisdom has
none; X archive reads cost dollars per symbol-day; Pushshift is closed), so the
honest test is **forward and record-only**, like the premarket pilot. Everything
below is frozen before the first poll; changing it restarts the count.

**Setup.** Poll ApeWisdom all-stocks top 100 at 08:00, then hourly to 16:00 ET,
on 20 consecutive Radar sessions, into a separate append-only file. The first 10
sessions only build baselines; **sessions 11–20 are scored**. No screen, no
alerts. Prices come from Alpaca SIP minutes for any flagged symbol, not only the
Radar list, because the point is coverage outside it.

**Definitions** (Radar's own thresholds, so results compare with the premarket pilot):

- *Move:* the flagged symbol reaches ≥5 points against SPY (from prior close)
  at any minute between the flag and the next session's close.
- *Lead flag:* a flag with move_at_flag < 3 points.
- *Base rate:* for every lead flag, 5 random symbols with similar prior 20-day
  average dollar volume (±50%) and move_at_flag < 3 points, drawn at the same
  timestamp, from the SIP universe. Fixed seed.
- *New to Isaac:* not in the Radar universe, not on his watchlist, and not in the
  Movers top/bottom 10 or a saved Radar event at flag time.

**Pass (all must hold over sessions 11–20):**

1. Polls succeed on ≥ 9 of 10 scored sessions and ≥ 95% of polls overall.
2. Lead flags: median 1–10 per session (useful, not a firehose).
3. Lead precision ≥ 35%, **and** ≥ 2× the matched base rate (one-sided
   bootstrap over flags, p < 0.05).
4. Lead time: of lead flags that became moves, median ≥ 60 minutes between the
   flag and the minute the move first reached 3 points (enough time to investigate).
5. At least 4 lead flags that became moves were *new to Isaac* during the 10
   scored sessions, and Isaac rates at least half of those "worth a look" when
   shown afterward, blind to the outcome.
6. Echo share ≤ 80% of all flags (else it's a price mirror).

**Stop early** (after session 15): lead precision < 20%, more than 25 lead
flags in a session on 3+ sessions, or 3+ failed polling sessions.

**Pass earns:** a Reddit API access request plus author dedupe, rerun the same
test, and then a Radar card section. Phone alerts remain separate, as with the
premarket pilot. **Fail:** close the idea and record it here.

Optional, $10–30 once: a daily-horizon retrospective using Quiver's WSB counts
for 2024–2026. Same detector at day resolution; "move" is ≥5 points on day D+1
for a spike on day D measured at D's close. Same pass criteria 3 and 6. It
can kill the idea faster but can't confirm intraday lead.

## Uncertainty and open checks

- Prices and access rules come mostly from third-party pages dated 2026. The
  official X, Reddit and ApeWisdom pages couldn't be fetched from this container.
  Check X's Developer Console and ApeWisdom's API page before running anything.
- ApeWisdom's terms, its rate limit and how fresh its data is are unknown.
  Building a pilot on it means accepting it may vanish.
- Running the forward test is new recorder code plus a scheduled job: a
  separate, user-approved change. This document authorizes nothing.
