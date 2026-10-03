import { apiUrl } from "./api";

export type SymbolTrade = {
  id: string;
  account_id: string;
  account_name: string;
  last4: string;
  instrument_type: string;
  option_type: string | null;
  strike: number | null;
  expiration: string | null;
  status: string;
  realized_pnl: number | null;
  hold_duration_mins: number | null;
  opened_at: string;
  closed_at: string | null;
};

export type SymbolJournal = {
  symbol: string;
  source: string;
  as_of: string;
  time_zone: string;
  total_trades: number;
  closed_trades: number;
  missing_pnl: number;
  realized_pnl: number | null;
  win_rate: number | null;
  average_hold_mins: number | null;
  hold_samples: number;
  best_trade: SymbolTrade | null;
  worst_trade: SymbolTrade | null;
  last_traded_at: string | null;
  open_positions: SymbolTrade[];
  recent_trades: SymbolTrade[];
};

export async function fetchSymbolJournal(symbol: string, signal: AbortSignal): Promise<SymbolJournal> {
  const response = await fetch(apiUrl(`/charts/symbol/${encodeURIComponent(symbol)}/you`), { signal, cache: "no-store" });
  if (!response.ok) throw new Error("Journal unavailable. Try again.");
  return response.json();
}
