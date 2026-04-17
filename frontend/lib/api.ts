export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type Fill = {
  id: string;
  account_id: string;
  ticker: string;
  instrument_type: string;
  side: string;
  contracts: number;
  price: number;
  executed_at: string;
  option_type: string | null;
  strike: number | null;
  expiration: string | null;
  raw_email_id: string;
  iv_at_fill: number | null;
  delta_at_fill: number | null;
  iv_rank_at_fill: number | null;
  underlying_price_at_fill: number | null;
};

export type Account = {
  id: string;
  name: string;
  type: string;
  last4: string;
};

export type Trade = {
  id: string;
  account_id: string;
  ticker: string;
  instrument_type: string;
  option_type: string | null;
  strike: number | null;
  expiration: string | null;
  contracts: number;
  avg_entry_premium: number;
  avg_exit_premium: number | null;
  total_premium_paid: number;
  realized_pnl: number | null;
  pnl_pct: number | null;
  hold_duration_mins: number | null;
  entry_time_bucket: string | null;
  expired_worthless: boolean;
  opened_at: string;
  closed_at: string | null;
  status: "open" | "closed" | "expired";
  ai_review: string | null;
};

export type Stats = {
  total_trades: number;
  open_trades: number;
  closed_trades: number;
  win_rate: number;
  total_pnl: number;
  total_premium_risked: number;
  today_pnl: number;
  avg_win_pct: number | null;
  avg_loss_pct: number | null;
  avg_hold_mins: number | null;
  expired_worthless_rate: number;
  by_ticker: Record<string, { count: number; win_rate: number; total_pnl: number; avg_pnl_pct: number }>;
  by_tag: Record<string, { count: number; win_rate: number; total_pnl: number; avg_pnl_pct: number }>;
  by_time_bucket: Record<string, { count: number; win_rate: number; total_pnl: number; avg_pnl_pct: number }>;
  behavioral_flags: Record<string, number>;
};

export type FillWriteInput = {
  account_id: string;
  ticker: string;
  instrument_type: "stock" | "option";
  side: string;
  contracts: number;
  price: number;
  executed_at: string;
  option_type?: "call" | "put";
  strike?: number;
  expiration?: string;
};

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`, { cache: "no-store" });
  if (!res.ok) throw await buildApiError(path, res);
  return res.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw await buildApiError(path, res);
  return res.json();
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await buildApiError(path, res);
  return res.json();
}

async function buildApiError(path: string, res: Response): Promise<Error> {
  let detail = "";

  try {
    const contentType = res.headers.get("content-type") ?? "";
    if (contentType.includes("application/json")) {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } else {
      const text = await res.text();
      if (text.trim()) detail = text.trim();
    }
  } catch {
    // Fall back to the status code when the response body can't be parsed.
  }

  return new Error(`API ${path} -> ${res.status}${detail ? `: ${detail}` : ""}`);
}

export const api = {
  accounts: () => get<Account[]>("/accounts"),
  trades: (params?: string) => get<Trade[]>(`/trades${params ? `?${params}` : ""}`),
  trade: (id: string) => get<Trade>(`/trades/${id}`),
  tradeFills: (id: string) => get<Fill[]>(`/trades/${id}/fills`),
  fills: () => get<Fill[]>("/fills"),
  fill: (id: string) => get<Fill>(`/fills/${id}`),
  stats: (params?: string) => get<Stats>(`/stats${params ? `?${params}` : ""}`),
  createFill: (body: FillWriteInput) => post<{ fill: Fill; trades_rebuilt: number; anomalies: string[] }>("/fills", body),
  updateFill: (id: string, body: FillWriteInput) => put<{ fill: Fill; trades_rebuilt: number; anomalies: string[] }>(`/fills/${id}`, body),
  importFills: () => post<{ saved: number; skipped: number }>("/fills/import"),
  resyncAll: () => post<{ status: string; saved: number; skipped: number; trades_rebuilt: number; anomalies: string[] }>("/fills/resync-all"),
  rebuild: () => post<{ status: string; trades_rebuilt: number; anomalies: string[] }>("/rebuild"),
};
