# Trade Journal

Monorepo for tracking trades, fills, and accounts.

## Structure

- **`/frontend`** — Next.js (TypeScript, App Router), Tailwind, shadcn/ui
- **`/backend`** — FastAPI (Python 3.10+), SQLite, SQLModel, Alembic

## Run locally

### Backend

```bash
cd backend
pip install -e .
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API: http://localhost:8000  
Docs: http://localhost:8000/docs

### Frontend

Requires Node.js >= 18.17.0.

```bash
cd frontend
npm install
npm run dev
```

App: http://localhost:3000

## Gmail Push Ingest

The backend can receive Gmail Pub/Sub push notifications and run a near-real-time Robinhood ingest pipeline.

Backend endpoints:

| Method | Path | Description |
|--------|------|-------------|
| POST | `/gmail/watch` | Register or renew the Gmail mailbox watch |
| GET | `/gmail/watch/status` | Show the saved watch state |
| POST | `/gmail/push` | Pub/Sub push webhook |

Environment:

```bash
GMAIL_PUBSUB_TOPIC=projects/YOUR_PROJECT_ID/topics/YOUR_TOPIC
GMAIL_WATCH_LABEL_IDS=INBOX
GMAIL_PUBSUB_VERIFICATION_TOKEN=choose-a-long-random-token
GMAIL_WATCH_AUTOSTART=true
```

Use a Gmail filter/label for Robinhood execution emails and set `GMAIL_WATCH_LABEL_IDS` to that Gmail label ID if you want push events limited to Robinhood mail. Google Pub/Sub must push to your public HTTPS backend URL, for example:

```text
https://YOUR_PUBLIC_BACKEND/gmail/push?token=choose-a-long-random-token
```

After the topic/subscription exists and Gmail OAuth is connected, register the watch:

```bash
curl -X POST http://localhost:8000/gmail/watch
```

Gmail watches expire, so renew this at least daily or set `GMAIL_WATCH_AUTOSTART=true` to let the backend renew it every 24 hours. Each push event queues `gmail_push`, which imports new Gmail fills, rebuilds derived trades when new fills are saved, then runs Polygon, Alpaca, and trade-path enrichment.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/accounts` | List accounts |
| POST | `/accounts` | Create account |
| GET | `/fills?account=combined\|roth\|taxable` | List fills |
| POST | `/fills/import` | Import fills (JSON) |
| POST | `/rebuild` | Rebuild trades from fills (FIFO) |
| GET | `/trades?account=...` | List trades |
| GET | `/stats?account=...` | Get stats |

## Database

SQLite database at `backend/data/trade_journal.db`.

Tables: `accounts`, `emails`, `fills`, `trades`, `trade_fills`, `tags`, `trade_tags`, `notes`.
