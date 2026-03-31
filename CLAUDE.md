# Trading Journal — Claude Code Context

## Who this is for
Isaac. Personal tool only. No auth, no multi-user, no deployment. Just works on localhost.

## What this does
Ingests Robinhood options trade confirmation emails → parses fills → reconstructs
trades using FIFO logic → surfaces performance stats + behavioral patterns via AI.

---

## MVP Scope (build only this)
- **One account:** Roth IRA (•••8267). Taxable is post-MVP.
- **Options only:** Stocks are post-MVP.
- **No auth:** Single user, localhost, no login needed.
- **Core loop:** Email → Fill → Trade → Stats → AI Review.

---

## Stack

| Layer | Tech | Notes |
|---|---|---|
| Frontend | Next.js 14 (App Router) | Already scaffolded |
| Styling | Tailwind CSS | Minimal, data-dense. No component library. |
| Data fetching | TanStack Query | Client-side cache + background refresh |
| Backend | FastAPI | Already scaffolded with stub routes |
| ORM | SQLModel | Pydantic + SQLAlchemy unified. Use this, not raw SQLAlchemy. |
| Database | SQLite | File at `backend/data/trade_journal.db`. No server. Gitignored. |
| Email | imaplib + APScheduler | Polls Gmail inside FastAPI process |
| Market data | Alpha Vantage + yfinance | IV enrichment. See enrichment section. |
| AI | Anthropic SDK (claude-sonnet-4-6) | Trade review + pattern detection |
| Migrations | Alembic | Already configured at `backend/alembic/` |
| Testing | pytest | Critical for FIFO reconstructor |

### Running locally
```bash
# Backend
cd backend && uvicorn app.main:app --reload   # :8000

# Frontend
cd frontend && npm run dev                     # :3000
```

---

## Project structure

What currently exists on disk (as of 2026-03-27):

```
/
├── frontend/
│   ├── app/
│   │   ├── layout.tsx                # Root layout + Nav
│   │   ├── page.tsx                  # Dashboard stub
│   │   ├── accounts/page.tsx         # Accounts stub
│   │   ├── fills/page.tsx            # Fills stub
│   │   └── trades/page.tsx           # Trade list stub
│   ├── components/
│   │   ├── Nav.tsx                   # Top nav component
│   │   └── ui/button.tsx
│   └── lib/
│       └── utils.ts
│
├── backend/
│   ├── app/
│   │   ├── main.py                   # FastAPI app entry point
│   │   ├── database.py               # SQLite engine, session factory
│   │   ├── models.py                 # All SQLModel classes (single file — see note below)
│   │   └── routers/
│   │       ├── accounts.py           # /accounts — stub
│   │       ├── fills.py              # /fills — stub
│   │       ├── trades.py             # /trades — stub
│   │       ├── stats.py              # /stats — stub
│   │       ├── rebuild.py            # /rebuild — stub
│   │       └── health.py             # /health
│   └── alembic/                      # Already configured; add migrations as schema evolves
│
├── CLAUDE.md                         # This file
└── .env                              # See env vars section
```

Still needs to be created:
```
backend/app/engine/
    reconstructor.py     # FIFO logic — most critical
    email_parser.py      # Robinhood email → ParsedFill
    enricher.py          # IV/delta via Black-Scholes + Alpha Vantage
backend/app/ai/
    reviewer.py          # Anthropic SDK trade review
backend/tests/
    test_reconstructor.py

frontend/app/
    trades/[id]/page.tsx
    analytics/page.tsx
frontend/lib/
    api.ts               # Typed fetch wrapper → FastAPI
```

**Note on `models.py`:** The current file has a generic schema (integer IDs, generic `Fill` with `symbol`/`side`/`qty`, generic `Trade`). This must be **replaced** with the options-specific schema defined in the Database schema section below before any further backend work. The `Email` and `Note` models can be dropped — email traceability is handled via `raw_email_id` on `Fill`.

---

## Environment variables (.env)
```
# Gmail
GMAIL_ADDRESS=isaac@gmail.com
GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx   # Google App Password, not regular password

# Alpha Vantage
ALPHA_VANTAGE_API_KEY=your_key_here      # Free tier: 25 req/day

# Anthropic
ANTHROPIC_API_KEY=your_key_here

# App
DATABASE_URL=sqlite:///./data/trade_journal.db
POLL_INTERVAL_MINUTES=5
```

---

## Database schema (SQLModel)

### Account
```python
id: uuid, name: str, type: str ("roth_ira"), last4: str ("8267")
```
MVP: seed one row on startup. Don't build account management UI.

### Fill (append-only — NEVER update or delete rows)
```python
id: uuid
account_id: uuid FK
ticker: str                  # underlying only — "SNDK" not "SNDK250327P00620000"
side: str                    # "buy_to_open" | "sell_to_close" | "buy_to_close" | "sell_to_open"
contracts: int               # number of contracts
price: float                 # per-contract premium in dollars (already ×1, not per-share)
executed_at: datetime        # tz-aware America/New_York — critical for 0DTE
option_type: str             # "call" | "put"
strike: float
expiration: date
raw_email_id: str            # IMAP UID for traceability back to source email

# Enriched after parse (all nullable — never block a fill on missing market data)
iv_at_fill: float | None
delta_at_fill: float | None
iv_rank_at_fill: float | None   # 0.0–1.0
underlying_price_at_fill: float | None

# Computed properties (not stored, derived)
# dte_at_fill → (expiration - executed_at.date()).days
# total_premium → price * contracts   (actual cash in/out)
# entry_time_bucket → "open" (9:30-10) | "mid" (10-3) | "close" (3-4)
```

### Trade (derived — always safe to delete + rebuild from fills)
```python
id: uuid
account_id: uuid FK
ticker: str
option_type: str             # "call" | "put"
strike: float
expiration: date
contracts: int               # max position size during trade
avg_entry_premium: float     # per contract
avg_exit_premium: float | None
total_premium_paid: float    # avg_entry × contracts (cash at risk)
realized_pnl: float | None
pnl_pct: float | None        # % gain/loss on premium — more useful than $ for options
hold_duration_mins: int | None
entry_time_bucket: str | None  # "open" | "mid" | "close"
expired_worthless: bool
roll_group_id: uuid | None   # links rolled positions (close+open share this)
opened_at: datetime
closed_at: datetime | None
status: str                  # "open" | "closed" | "expired"
ai_review: str | None        # raw JSON from reviewer.py
```

### TradeTag
```python
trade_id: uuid FK, tag_id: uuid FK
```

### Tag
```python
id: uuid, name: str, source: str  # "manual" | "auto" | "ai"
```
Example tags: `lotto`, `swing`, `scalp`, `revenge`, `oversize`

### TradeFill (junction)
```python
trade_id: uuid FK, fill_id: uuid FK, role: str  # "entry" | "exit"
```
This is what powers the fill timeline in the trade detail view.

---

## Core mental model — NEVER violate this

```
Fills = raw truth     → append-only, never modified
Trades = derived      → always reconstructable, safe to delete
```

`POST /rebuild` must:
1. Delete all rows in `trades` and `trade_fills`
2. Re-run reconstructor over all fills ordered by `executed_at` ASC
3. Be fully deterministic — same fills always produce same trades

---

## API routes

```
GET  /health

GET  /accounts

GET  /fills                         # all fills, newest first
POST /fills                         # manual fill entry
POST /fills/import                  # trigger email poll now

GET  /trades                        # ?status=open|closed|all  ?ticker=NVDA
GET  /trades/{id}
GET  /trades/{id}/fills             # fill timeline for trade detail view
POST /trades/{id}/tags              # add tag
POST /trades/{id}/review            # trigger AI review, store result

POST /rebuild                       # delete trades → recompute from fills

GET  /stats                         # see stats section
```

---

## FIFO Reconstructor (`backend/app/engine/reconstructor.py`)

**Most critical file. Build + test this before wiring to DB.**

### Algorithm
```
Input:  all fills for an account, ordered by executed_at ASC
Output: list of Trade objects + TradeFill junction rows

State:  position_queue: dict[contract_key → deque[lot]]
        where contract_key = (ticker, option_type, strike, expiration)
        and lot = {contracts: int, price: float, fill_id: uuid, opened_at: datetime}

For each fill:
  key = (ticker, option_type, strike, expiration)

  if side in ("buy_to_open", "sell_to_open"):
    push lot onto position_queue[key]
    if no open trade for this key → create new Trade (status=open)
    link fill to trade via TradeFill(role="entry")

  if side in ("sell_to_close", "buy_to_close"):
    pop from front of position_queue[key] (FIFO)
    handle partial lots (split if needed)
    compute realized_pnl for closed portion
    link fill to trade via TradeFill(role="exit")
    if queue empty → close trade, set status, compute hold_duration_mins

After all fills:
  any remaining lots in queue → trade status = "open"
```

### Key cases to handle + test
```python
# 1. Simple round trip
buy_to_open(2 contracts) → sell_to_close(2 contracts)
# Expected: 1 closed trade, pnl = (exit - entry) * 2

# 2. Partial exit
buy_to_open(4) → sell_to_close(2) → sell_to_close(2)
# Expected: 1 trade, 2 exit fills, pnl accumulates across exits

# 3. Scale in
buy_to_open(2) → buy_to_open(2) → sell_to_close(4)
# Expected: 1 trade, avg_entry = weighted average of both buys

# 4. 0DTE expired worthless
buy_to_open(1) → [no closing fill, expiration == executed_at.date()]
# Expected: trade status="expired", expired_worthless=True, pnl = -total_premium

# 5. Same ticker different strikes = separate trades
buy_to_open(NVDA 500c 3/28) and buy_to_open(NVDA 510c 3/28)
# Expected: 2 separate trades, keyed by (ticker, type, strike, expiration)
```

### Expired worthless detection
Run after processing all fills. For any open trade where `expiration < today`:
```python
trade.status = "expired"
trade.expired_worthless = True
trade.realized_pnl = -trade.total_premium_paid
trade.closed_at = datetime(expiration, 16, 0, tzinfo=ET)  # 4pm ET
```

---

## Email parser (`backend/app/engine/email_parser.py`)

**Not yet written. Build after reconstructor + models.**

Key behaviors:
- Filters by subject line first — only processes "Option order executed" emails
- Skips cancellations, replacements, order confirmations at subject level
- Returns `ParsedFill` dataclass (not a DB model — convert in the router)
- `side` is inferred: buy→buy_to_open, sell→sell_to_close (heuristic, reconstructor can correct)
- `raw_email_id` = IMAP UID for traceability
- iv/delta/iv_rank fields are None — enricher fills these in

Test against real Robinhood emails including:
- "Option order executed" → should parse correctly
- "GOOG order replaced" → should be ignored

---

## IV Enrichment (`backend/app/engine/enricher.py`)

Runs after email parsing, before saving fills to DB.
All enrichment fields are nullable — NEVER fail a fill save because enrichment failed.

### Strategy
```
1. underlying_price_at_fill
   → yfinance: ticker.history(date) → Close price on fill date
   → Good enough (EOD, not intraday — acceptable for behavioral analysis)

2. iv_at_fill
   → Back-calculate using Black-Scholes from:
     - market_price = fill.price (already have from email)
     - S = underlying_price_at_fill
     - K = fill.strike
     - T = fill.dte_at_fill / 365
     - r = 0.045  (update quarterly)
   → Use scipy.optimize.brentq to solve for sigma
   → Falls back to None if brentq fails (deep ITM/OTM edge cases)

3. delta_at_fill
   → Black-Scholes delta formula once IV is known
   → calls: N(d1),  puts: N(d1) - 1

4. iv_rank_at_fill
   → Alpha Vantage: fetch 52-week daily IV history for underlying
   → iv_rank = (iv_at_fill - iv_52w_low) / (iv_52w_high - iv_52w_low)
   → Cache Alpha Vantage responses (25 req/day free limit)
   → If AV quota exceeded: skip gracefully, set None
```

### Alpha Vantage rate limit handling
```python
# Cache responses in SQLite (simple kv table) to avoid hitting 25/day limit
# Key: f"av_iv_history_{ticker}_{date.today()}"  — refresh daily
# On 429 or empty response: log warning, return None, continue
```

---

## AI Review (`backend/app/ai/reviewer.py`)

Model: `claude-sonnet-4-6`
Trigger: `POST /trades/{id}/review` — on-demand, result stored in DB.

### What to pass in the prompt
```python
context = {
    "trade": {
        "ticker": trade.ticker,
        "option_type": trade.option_type,
        "strike": trade.strike,
        "expiration": str(trade.expiration),
        "contracts": trade.contracts,
        "avg_entry_premium": trade.avg_entry_premium,
        "avg_exit_premium": trade.avg_exit_premium,
        "total_premium_paid": trade.total_premium_paid,
        "realized_pnl": trade.realized_pnl,
        "pnl_pct": trade.pnl_pct,
        "hold_duration_mins": trade.hold_duration_mins,
        "entry_time_bucket": trade.entry_time_bucket,
        "expired_worthless": trade.expired_worthless,
        "tags": [t.name for t in trade.tags],
    },
    "fills": [
        {
            "side": f.side,
            "contracts": f.contracts,
            "price": f.price,
            "executed_at": str(f.executed_at),
            "iv_at_fill": f.iv_at_fill,
            "delta_at_fill": f.delta_at_fill,
            "iv_rank_at_fill": f.iv_rank_at_fill,
            "dte_at_fill": f.dte_at_fill,
        }
        for f in trade.fills
    ],
    # Recent context (last 5 closed trades before this one)
    "recent_trades": [ ... ]
}
```

### Behavioral flags to detect
```
1. bad_iv_entry      → iv_rank_at_fill > 0.7 on a buy_to_open
2. held_loser        → hold_duration_mins > 60 AND pnl_pct < -0.5
3. early_exit        → pnl_pct > 0 AND pnl_pct < 0.2 AND dte_at_fill > 2
4. oversize          → total_premium_paid > $500 (adjust threshold to Isaac's account)
5. revenge_trade     → this trade opened within 15 mins of previous trade closing at loss
```

### Response format
Ask Claude to return structured JSON:
```json
{
  "flags": ["bad_iv_entry", "held_loser"],
  "summary": "2-3 sentence plain english summary of what happened",
  "entry_quality": "good | neutral | poor",
  "exit_quality": "good | neutral | poor",
  "suggestions": ["specific actionable suggestion 1", "suggestion 2"]
}
```
Store raw JSON in `trade.ai_review` (text column). Parse on frontend.

---

## Stats endpoint (`GET /stats`)

```python
{
  # Overall
  "total_trades": int,
  "open_trades": int,
  "win_rate": float,           # closed profitable / total closed
  "total_pnl": float,
  "total_premium_risked": float,

  # Averages
  "avg_win_pct": float,        # avg pnl_pct on winners
  "avg_loss_pct": float,       # avg pnl_pct on losers
  "avg_hold_mins": float,

  # Breakdowns
  "by_tag": { "lotto": {...}, "swing": {...} },
  "by_ticker": { "NVDA": {...}, "TSLA": {...} },
  "by_time_bucket": { "open": {...}, "mid": {...}, "close": {...} },
  "expired_worthless_rate": float,

  # Behavioral (counts, not judgments)
  "revenge_trade_count": int,
  "oversize_count": int,
  "bad_iv_entry_count": int,
}
```

---

## Frontend pages

### Dashboard (`/`)
- Today's PnL (sum realized_pnl where closed_at = today)
- Open positions list (status=open trades)
- Last 10 closed trades with PnL
- Win rate + total PnL for the month

### Trade list (`/trades`)
- Sortable table: ticker | type | strike | expiry | entry | exit | PnL% | tag | status
- Filter by: status, ticker, tag, date range
- Click row → trade detail

### Trade detail (`/trades/[id]`)
- Fill timeline (ordered by executed_at, role labeled entry/exit)
- Trade summary card (all fields)
- AI review section (trigger button + display result)
- Manual tag input

### Analytics (`/analytics`)
- Win rate over time (chart)
- PnL by tag (bar)
- Entry time bucket breakdown
- Behavioral flag counts

---

## Build order (follow this)

```
✅ FastAPI app scaffolded (main.py, database.py, stub routers)
✅ Alembic configured
✅ Frontend scaffolded (layout, nav, stub pages)

TODO — in order:
1. Replace models.py with options-specific schema (Account, Fill, Trade, TradeFill, Tag, TradeTag)
2. Alembic migration for new schema
3. engine/reconstructor.py + tests/test_reconstructor.py  ← pure logic, no DB, most critical
4. Wire routers/fills.py + routers/trades.py to real DB
5. POST /rebuild — wire reconstructor to DB
6. engine/enricher.py — IV enrichment, nullable fields
7. engine/email_parser.py — Robinhood email → ParsedFill; wire into /fills/import
8. routers/stats.py — GET /stats
9. Frontend: lib/api.ts → dashboard → trade list → trades/[id] → analytics
10. ai/reviewer.py + POST /trades/{id}/review  ← AI layer last
```

---

## Coding conventions

- **SQLModel only** — never raw SQLAlchemy, never raw SQL unless unavoidable
- **Async FastAPI** — use `async def` for all route handlers
- **Never fail a fill save** — enrichment errors are logged and skipped, not raised
- **Never modify fills** — if a fill is wrong, add a new correcting fill, don't edit
- **Type everything** — Pydantic models for all request/response bodies
- **Rebuild must be idempotent** — calling it 10 times produces the same result as calling it once
- **Enrichment is best-effort** — nullable fields stay null rather than blocking the pipeline

## What NOT to build in MVP
- Auth / login
- Taxable account support
- Stock trade tracking
- CSV export
- Chart overlays (price chart at entry/exit)
- Automated AI tagging
- Real-time price tracking
