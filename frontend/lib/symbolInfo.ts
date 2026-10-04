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

/** How one Tradier dataset arrived: `none` means Tradier answered without rows (an ETF has no earnings). */
export type EventsBlock = {
  state: "ready" | "none" | "loading" | "unavailable"; source: string;
  /** When Tradier was read, in seconds; null when nothing is cached. */
  fetched_at: number | null; message: string | null;
};
/** The next report. Tradier gives dates only; `estimated` is Tradier's estimate, not the company's announcement. */
export type EarningsNext = { date: string; status: "confirmed" | "estimated"; label: string };
/** A past report: a confirmed date, one per fiscal quarter. */
export type EarningsReport = { date: string; label: string };
/**
 * A symbol's earnings (T1.4, C2.5). The workspace response sends every past
 * report, for markers; the Events tab, the latest eight.
 */
export type Earnings = EventsBlock & { next: EarningsNext | null; reports: EarningsReport[] };
export type Dividend = {
  ex_date: string; amount: number; currency: string; pay_date: string | null; record_date: string | null;
  declared: string | null; frequency: number | null; type: string;
};
export type Split = { ex_date: string; from: number; to: number; label: string };
export type SymbolEvents = {
  symbol: string; today: string; time_zone: string;
  earnings: Earnings & { time_note: string };
  dividends: EventsBlock & { next: Dividend | null; last: Dividend | null };
  splits: EventsBlock & { rows: Split[] };
};

export async function fetchSymbolEvents(symbol: string, signal: AbortSignal): Promise<SymbolEvents> {
  const response = await fetch(apiUrl(`/charts/symbol/${encodeURIComponent(symbol)}/events`), { signal, cache: "no-store" });
  if (!response.ok) throw new Error("Events unavailable. Try again.");
  return response.json();
}

/** One option leg of a straddle, as quoted (observed). */
export type StraddleLeg = { symbol: string; bid: number | null; ask: number | null; iv: number | null };
/**
 * The implied move for one expiration (T2.1): the at-the-money straddle's mid
 * (calculated), or why there is none. `tags` say which rows it answers:
 * the nearest expiration, the nearest Friday, the first after the next report.
 */
export type ImpliedMove = {
  tags: ("nearest" | "friday" | "earnings")[]; expiration: string; days: number;
  state: "ready" | "too_wide" | "none" | "unavailable"; reason?: string;
  move?: number; percent?: number; iv?: number | null; strike?: number;
  /** The staler leg's quote time and when the chain was read, in seconds. */
  quoted_at?: number | null; fetched_at?: number;
  call?: StraddleLeg; put?: StraddleLeg;
};
export type SymbolForecast = {
  symbol: string; today: string; source: string; spot: number | null; earnings: EarningsNext | null;
  state: "ready" | "none" | "unavailable"; message: string | null; moves: ImpliedMove[]; earnings_note?: string | null;
};

/** The Forecast tab (T2.1) at `spot`, the chart's latest price. */
export async function fetchSymbolForecast(symbol: string, signal: AbortSignal, spot: number | null): Promise<SymbolForecast> {
  const query = spot && spot > 0 ? `?spot=${spot}` : "";
  const response = await fetch(apiUrl(`/charts/symbol/${encodeURIComponent(symbol)}/forecast${query}`), { signal, cache: "no-store" });
  if (!response.ok) throw new Error("Forecast unavailable. Try again.");
  return response.json();
}

const newYorkDay = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" });
/** Calendar days from New York's today (at `now`, in ms) to `day` (YYYY-MM-DD). */
export function daysUntil(day: string, now: number): number {
  return Math.round((Date.parse(`${day}T00:00:00Z`) - Date.parse(`${newYorkDay.format(now)}T00:00:00Z`)) / 86_400_000);
}
export const BADGE_DAYS = 14;
/** The chart header's earnings badge: only from today through 14 days ahead, never for an unknown date. */
export function earningsBadge(next: EarningsNext | null | undefined, now: number): string | null {
  if (!next) return null;
  const days = daysUntil(next.date, now);
  if (days < 0 || days > BADGE_DAYS) return null;
  return `${days === 0 ? "Earnings today" : days === 1 ? "Earnings tomorrow" : `Earnings in ${days} d`}${next.status === "estimated" ? " · est." : ""}`;
}
const longDay = new Intl.DateTimeFormat("en-US", { timeZone: "UTC", weekday: "short", month: "short", day: "numeric", year: "numeric" });
/** A provider date (YYYY-MM-DD) as written: "Wed, Oct 28, 2026". It is a date, not a time, so no zone shifts it. */
export const eventDay = (day: string) => longDay.format(new Date(`${day}T00:00:00Z`));
export const readAt = (seconds: number | null) => seconds == null ? "not read yet"
  : `read ${new Date(seconds * 1000).toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} ET`;
