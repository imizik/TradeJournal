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
