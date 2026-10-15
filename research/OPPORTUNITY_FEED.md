# Opportunity feed and Jo selection pilot

Isaac authorized an offline trial October 15, 2026. The objective is enough
plausible choices for Jo, independently of whether taking every setup passes
the factory profitability screen. This is a separate research track, never a
strategy pass or permission to replace live S1.

`backend/scripts/factory_opportunities.py` freezes a five-session discovery
pilot, February 5–9, 2024, using three already counted specs:
`s1-0b2c5f54ba` (S1 ORB), `s1-455b2eabc7` (S1 fade), and
`op-7f71884194` (15-minute ORB). Specs and dates are fixed before loading
pilot outcomes. No confirmation, exam, recent holdout or forward results are
used. Existing factory gates, counts and continuous search remain unchanged.

Admission needs valid directional risk, at least 1.25R planned target and
estimated underlying round-trip slippage no greater than 0.25R. The pilot uses
independent signal opportunities, without outcome-dependent position
suppression or daily loss halts. Fixed seeded sampling cycles across specs,
with at most 18 cards per session and three per ticker; identical ticker/time/
side opportunities are not duplicated. This feed is not a portfolio execution
simulation. Negative take-all discovery results do not exclude a feed.

Cards retain cutoff candles, signed context/level features, reference entry,
stop and reference target, family, dates and sources. Next-open fills and
outcomes are private. Prices restore future split factors to the decision's
basis; missing historical option quotes/spreads/eligibility are unavailable.
Source data may be retrospectively corrected; minute completeness, executable
option performance, independence and real latency are not established.

Build in the factory checkout with `ALPACA_DATA_FEED=sip`:

```
backend/.venv/bin/python backend/scripts/factory_opportunities.py build
```

It acquires the existing search/weekly writer locks and reserves up to 900
seconds from the current two-hour time cap. Successful runtime replaces the
reservation; interrupted runtime stays consumed. It reuses already tried IDs
rather than resetting/counting them again. The frozen batch cannot be replaced.

The batch is under `backend/data/factory/opportunities/pilot-20261015-v1/`.
Give Jo **only** `public/packets.json` and the public assignment. Do not give
Jo `operator-private/`, the ledger, or scoring output before all choices are
committed. This local file separation is an operator workflow, not a new
identity-authenticated endpoint. No live task or exchange is changed. Actual Jo
decisions must be collected separately; never substitute another model and
label those choices Jo.

Jo returns a JSON list containing each card's `id`, `decision` (`take`, `skip`
or `insufficient_data`), and nonempty `reason` of at most 1000 characters.
Import with `decide --choices PATH`. Exact retries are idempotent; conflicting
choices and unknown cards are refused. Local receipt time is recorded; imports
do not authenticate the author's identity. Every choice binds the public
manifest hash. `score` refuses an incomplete/changed manifest or a mismatched
private outcome seal.

After all decisions, compare Jo TAKEs with take-all, the predeclared
`day_move >= 0 AND trend >= 0` filter, and 1000 seeded random subsets matched
to Jo's TAKE count per session/spec. Report counts, unresolved outcomes,
mean/total R after factory costs and a descriptive random percentile. Five
correlated discovery sessions cannot establish selection skill or profitability.
A follow-on frozen out-of-sample study requires separate selection of untouched
dates and cannot reuse this pilot's outcomes as an exam.
