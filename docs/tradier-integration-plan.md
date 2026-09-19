# Plan: Tradier as a live-quote provider

**Status (2026-09-18):** assessment only. Nothing is implemented. No decision
has been made beyond "investigate"; Phase 0 below is the smallest change that
would settle it with evidence.

**Audience:** a coding agent (Claude or Codex) implementing this cold, and the
account owner deciding whether it is worth doing. Read the referenced files
before writing code; do not guess signatures.

## The question this answers

A Tradier brokerage account was opened for API access. Where — if anywhere —
does it belong in a journal that already uses Polygon for historical bars and
Alpaca for market context and trade-path analysis?

## Conclusion first

**Adopt Tradier as a live-quote provider only. Keep Polygon and Alpaca exactly
as they are. Do not stream.**

Tradier replaces nothing historical: its 1-minute history reaches back 20 days
and it serves no data at all for expired option contracts, while
`enrich_fills()` and `compute_path_metrics_for_trades()` routinely reach back
months. Its value is entirely in the present tense.

The opening it fills is one this plan found rather than went looking for, and
it is not written down anywhere else:

> `backend/app/engine/quotes.py` prices every open position on the dashboard
> through **yfinance** — unofficial, unlicensed, undocumented latency — and
> downloads a whole option chain per `(ticker, expiration)` to read one
> contract. Meanwhile `fetch_option_snapshots()` in
> `backend/app/engine/alpaca.py` already returns option quotes, IV and greeks,
> and is used only by the scalper, never by the dashboard.

So the real question is not "Tradier vs Polygon/Alpaca." It is "what should
replace yfinance," and there are three candidates, two of which are already
paid for.

## What Tradier adds, against what we have

| Capability | Tradier | Today | Verdict |
|---|---|---|---|
| Real-time option NBBO (OPRA consolidated) | production, included with a brokerage account | yfinance (dashboard); Alpaca **indicative** feed (scalper) | **real gain** |
| Real-time underlying quote | consolidated feed | yfinance `fast_info`; Alpaca IEX (thin) | **real gain** |
| Greeks + IV | ORATS, **hourly**, carries `updated_at` | solved locally from the executed premium | cross-check only |
| Chain snapshot with greeks | one call per expiration | Alpaca chain snapshots | sideways |
| Historical daily bars | full lifetime; "may not be dividend adjusted" | Polygon, adjusted, cached | worse |
| Historical 1-min bars | **20 days** (10 with extended hours) | Polygon, full history, cached | **much worse** |
| Expired option history | **none** | Alpaca option bars drive `trade_path_metrics` | **disqualifying** |
| Streaming (WS + HTTP) | equities *and* OCC symbols | none | new, operationally expensive |

Sources are listed at the bottom. All of it is from Tradier's current docs at
`docs.tradier.com`; the older `documentation.tradier.com` URLs 308-redirect
there and some third-party summaries of them are stale.

## Event-triggered REST, not streaming

Three reasons, in order of weight:

1. **One market-data stream session per user, 5-minute idle expiry.** A laptop
   backend (`startdev.sh`) and a continuously hosted backend share one token,
   so one silently kicks the other. That is a new failure mode for a journal
   that reads quotes a few times a minute.
2. **The access pattern is bursty.** A Gmail push lands, an alert fires, a page
   loads. Between those, nothing needs a quote.
3. **A stream cannot capture a fill anyway.** It only records symbols
   subscribed in advance, and the contract about to be filled is unknown before
   the fill.

Streaming earns its keep for exactly one feature: a continuous intraday
mark-to-market trail for open positions — a real equity curve rather than a
dashboard-refresh sample. That is Phase 3, needs a supervised reconnect loop,
and should use a second token or an explicit "only the hosted process streams"
rule.

## Email delay: what a snapshot is and is not

Execution time is **not** lost to email latency. `_parse_dt()` in
`backend/app/engine/email_parser.py` reads the execution timestamp out of the
email body (`"%B %d, %Y %I:%M %p"`, ET). Sub-minute precision is lost;
the timestamp is not. `Fill.executed_at` is genuinely execution time, and email
arrival time appears nowhere in the schema.

A Tradier quote taken when the email lands is therefore a snapshot at
**T+lag**, and the only real mistake available is writing it into a
`*_at_fill` column.

### Proposed table (Phase 1) — not columns on `fill`

```
fill_quote_snapshot
  fill_id (PK, FK fill.id)
  provider                'tradier'
  provider_symbol         OCC symbol as sent
  executed_at             copied from the fill
  captured_at             when the request was made
  lag_seconds             captured_at - executed_at      <- the point of the table
  bid, ask, mid, last, bid_size, ask_size
  bid_date, ask_date, trade_date         <- Tradier's own ms timestamps, verbatim
  underlying_last, underlying_trade_date
  iv_mid, delta, gamma, theta, vega, smv_vol
  greeks_updated_at                      <- ORATS's timestamp, unmodified
  raw_json
```

Three rules to add to `docs/agent/domain-rules.md` when this lands:

- A snapshot is evidence about the moment **we found out**, never the moment we
  filled.
- Provider timestamps are stored as received. Never coalesce `captured_at` with
  `bid_date`; the gap between them *is* a data-quality signal.
- Anything displayed from this table carries its lag ("NBBO 4m12s after fill"),
  or it is not displayed.

### Can Tradier recover the missing context retroactively?

No, and it is worth being blunt about why:

- 1-minute timesales reach back 20 days (10 with extended hours), and expired
  options return nothing. Past three weeks, Tradier has nothing to offer.
- The fill minute is already reconstructed *better* elsewhere: `enrich_fills()`
  finds the exact minute bar (`_find_bar`) from Polygon and solves IV from the
  premium actually paid; option path comes from Alpaca option bars.
- A previously recorded stream could recover it, but only for symbols
  subscribed before the fill — unknowable for a new position.

The honest framing: the fill-time snapshot measures **email lag and the
slippage inside it**. It does not fill a hole. It produces a number that
currently cannot be computed at all — how far the market moved between
execution and the journal learning about it.

## Vendor greeks vs ours

Different questions; they must never share a column.

- **Ours** (`enricher.py`, the `implied_volatility` / `compute_greeks` pair):
  IV solved from the premium *actually paid*, against the Polygon minute-bar
  close at the fill minute, flat `RISK_FREE_RATE`, European BS, no dividends.
  It is execution-conditioned — paying the ask inflates it. For a journal that
  is a feature: it is what was transacted at.
- **Tradier/ORATS**: a fitted surface refreshed **hourly**, with an explicit
  `updated_at`. Never contemporaneous with a fill; can be ~60 minutes stale.

Rules:

1. Vendor greeks land in `fill_quote_snapshot` only. `iv_at_fill`,
   `delta_at_fill`, `vega_at_fill` stay locally computed. `trade_path_metrics`
   greek attribution stays pinned to our entry/exit greeks —
   `domain-rules.md` already requires Polygon enrichment before the path job,
   and that chain must not be broken.
2. Wherever a vendor greek is shown or put in an AI prompt, carry
   `greeks_updated_at` and a computed staleness. "Delta 0.42 (ORATS, 37m old)"
   is honest; "Delta 0.42" is not.
3. The genuinely valuable use is **live open-position risk** — book delta and
   theta right now — where hourly greeks against live NBBO are fine and nothing
   is computed today.
4. Free validation, worth running once as a script: for every options fill we
   also have our own IV. Comparing it to ORATS `mid_iv` at the nearest hour
   quantifies how much of the stored IV is execution noise.

## Rate-limit budget

Tradier production allows **120 requests/minute for `/markets`**, per access
token, in 1-minute windows, with `X-Ratelimit-Allowed` / `-Used` /
`-Available` / `-Expiry` on every response. Sandbox is 60/min but 15-minute
delayed with no greeks and no streaming — useless beyond shape testing.

Measured against this database (4,403 fills, 1,576 trades, 13 open positions of
which 1 is an option), batching underlyings and OCC symbols into one
`POST /v1/markets/quotes`:

| Consumer | Calls | Frequency | Peak/min |
|---|---|---|---|
| Dashboard open positions (~14 symbols) | 1 batched | per page load; 1/min if polling is ever added | 1 |
| Gmail push → new-fill snapshot | 1 batched per pipeline run | ~19 fills/session, batched; 10–20 runs/session | 1–2 |
| TradingView alert → underlying + contract | 1–2 | per alert | 2–4 in a burst |
| Chain call (only when strike unresolved) | 1 per expiration | rare | 1 |
| Retries (cap 2) | ×2 worst case | — | doubles the above |

**Steady state 1–3 calls/min; worst-case burst ~10/min. Under 10% of budget.**
Ten times the current trade volume still does not approach the ceiling.

The limiter should therefore be trivial: honor `X-Ratelimit-Available`, back
off on 429, stop. **Do not build another discovered-rate machine like the
Polygon one in `enricher.py`.** That design exists because Polygon's real
budget depends on an unknown plan; Tradier's is documented, uniform, and far
above what this system needs. There is nothing to discover.

For contrast: streaming open positions would take this to zero REST calls —
optimizing a number that is already ~2% of budget.

## Implementation

### Phase 0 — swap yfinance behind a flag (the whole first change)

- New `backend/app/engine/tradier.py`: thin `httpx` client, `TRADIER_API_KEY`
  and `TRADIER_BASE_URL` from env, one function
  `get_quotes(symbols, greeks=False)` that POSTs a comma-joined symbol list to
  `/v1/markets/quotes`, plus an `_occ_symbol()` helper (reuse the existing
  format in `backend/app/engine/trade_path.py` / `backend/app/engine/scalper.py`
  — do not write a third one).
- In `backend/app/engine/quotes.py`, add a provider seam:
  `QUOTES_PROVIDER=yfinance|tradier|alpaca`, keeping the `OptionQuoteResult`
  dataclass and the **per-share** option premium contract intact. Tradier
  returns per-share premium like yfinance, so the ×100 conversion in
  `frontend/lib/dashboard.ts` stays correct and no frontend change is needed.
- yfinance remains the fallback on exception.
- `backend/app/routers/quotes.py` is untouched. No migration. No schema change.

That is one new module plus a dispatch function.

### How to decide whether to adopt it

`backend/scripts/compare_quote_providers.py` (read-only, new): price today's
open positions through Tradier, yfinance **and** Alpaca option snapshots in the
same second; print bid, ask, mid, IV, spread %, and wall-clock latency per
provider. Run it several times across a session — open, mid, close, and once
after hours.

Adopt Tradier if it is consistently tighter and fresher. The three-way matters:
Alpaca is already paid for, and if its option feed holds up, promoting it costs
nothing and adds no vendor.

This lands where `scripts/verify.sh` does not reach — live external data — so
the comparison script **is** the verification, and `docs/agent/verification.md`
should say so rather than implying the suite covers it.

### Phase 1 — `fill_quote_snapshot`

Model + Alembic revision + a capture hook after fills are saved in the Gmail
push pipeline (`queue_gmail_push_pipeline` in `backend/app/routers/sync.py`).
Adds the lag measurement. ~1 call per sync.

### Phase 2 — alert-time option quote

`_gather_option()` in `backend/app/engine/scalper.py`, as an alternative to
Alpaca indicative snapshots. This is where consolidated NBBO matters most:
`_option_check()` rejects scalps on spread width, and indicative quotes can
misprice exactly that.

### Phase 3 — streaming recorder (only if the equity-curve feature is wanted)

Separate process, one-session discipline, supervised reconnect, session
re-creation on the 5-minute idle expiry.

### Boundaries

Keep all of this out of the TradingView ingress import graph.
`backend/tests/test_import_boundaries.py` will fail on a new import along that
path, and it should. Alert analysis runs in the private process, so Phase 2 is
unaffected.

## Costs, hosting, limitations

**Costs.** Per Tradier's FAQ, brokerage account holders get API market data at
no additional charge, and real-time is production-only and account-holder-only.
Plans are Lite (free, $0.35/contract), Pro ($10/mo, free equity/ETF option
commissions) and Pro Plus ($35/mo). The "$10 for market data" figure that
circulates is the **commission** plan, not a data fee. Using Tradier purely as
a data source while trading elsewhere, **Lite should suffice — and that is the
single most important thing to verify before building anything.**

**Hosting / restart.** REST-only needs one env var and holds no state: no
supervision, no reconnect logic, no new failure mode when the backend cycles.
That is most of the argument against streaming — the stream is the only part
that turns "continuously hosted backend" from a convenience into a requirement.

**Limitations to accept going in.** Greeks hourly, not live. No expired-option
history. 1-minute history capped at 20 days. Level 1 only. One stream session
per user. Sandbox is 15-minute delayed with no greeks and no streaming, so it
cannot be developed against meaningfully. API is personal-use-only absent a
Tradier Partner agreement. Historical daily bars may not be dividend-adjusted.

## Open questions — must be tested against the real account

None of these can be settled from documentation:

1. Does an **unfunded / Lite** account return real-time production data, or
   does entitlement require funding or accepting a market-data agreement?
2. Maximum symbols per `POST /v1/markets/quotes`, and whether OCC symbols batch
   cleanly alongside equities. A third-party review claims 100; Tradier's own
   docs state no limit. Trust neither until measured.
3. **SPXW and index options.** This journal holds 5 SPXW trades, and
   cash-settled index symbology is where broker APIs diverge most. Confirm the
   symbol form Tradier expects and that quotes and greeks come back.
4. Does `/v1/markets/timesales` accept OCC symbols, and at what depth? The docs
   are silent. This decides whether a missed Phase 1 snapshot can ever be
   backfilled within the 20-day window.
5. Observed `greeks.updated_at` staleness during RTH — truly hourly, or worse
   near the open?
6. Quote freshness against Alpaca indicative and yfinance, **measured**. This
   is the decision, and Phase 0's comparison script exists to make it.
7. Whether the token is shared with any other tool: both the one-session rule
   and the rate limit are per access token.

## Sources

Tradier documentation, read 2026-09-18:

- Rate limiting — https://docs.tradier.com/docs/rate-limiting
- Market data — https://docs.tradier.com/docs/market-data
- Get quotes — https://docs.tradier.com/reference/brokerage-api-markets-get-quotes
- Post quotes — https://docs.tradier.com/reference/brokerage-api-markets-post-quotes
- Option chains — https://docs.tradier.com/reference/brokerage-api-markets-get-options-chains
- Historical data — https://docs.tradier.com/docs/historical-data
- Timesales — https://docs.tradier.com/reference/brokerage-api-markets-get-timesales
- Streaming — https://docs.tradier.com/docs/streaming-data
- WebSocket market data — https://docs.tradier.com/reference/websocket-market-data-streaming
- HTTP streaming — https://docs.tradier.com/reference/http-streaming
- FAQ — https://docs.tradier.com/docs/faq
- Pricing — https://tradier.com/pricing
