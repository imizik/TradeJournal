// The journal on the chart (C3.1–C3.3): trade cards from fill arrows, open
// positions as lines, and links that open a past trade on its candles.
import { apiUrl } from "@/lib/api";
import { intradayInterval, type Interval } from "@/lib/charts";

/** Where an underlying price at an option fill came from. `single_venue`: one exchange's prints (IEX), not the chart's consolidated tape. */
export type ObservedUnderlying = { price: number; source: string; as_of?: number | null; single_venue: boolean };

/** An open trade on the chart's symbol (C3.2). `line` is the price drawn: a stock's average cost, an option's underlying at entry, or null. */
export type ChartPosition = {
  trade_id: string; account: string; last4: string; instrument: "stock" | "option"; contract: string;
  direction: "long" | "short"; open: number; avg_cost: number | null; realized: number; opened_at: number; exits: number[];
  line: number | null; underlying_at_entry: ObservedUnderlying | null; unit: "share" | "contract"; price_note: string;
};

export type CardFill = { id: string; role: "entry" | "exit"; side: string; qty: number; price: number; time: number; underlying: ObservedUnderlying | null };
export type MetricState = "current" | "stale" | "missing";
export type TradeCardData = {
  fill: { id: string; ticker: string; side: string; qty: number; price: number; time: number; instrument: string; contract: string } | null;
  trade: null | {
    id: string; ticker: string; instrument: "stock" | "option"; contract: string; option_type: string | null; strike: number | null; expiration: string | null;
    account: { name: string; last4: string } | null; status: "open" | "closed" | "expired"; direction: "long" | "short"; expired_worthless: boolean;
    opened_at: number; closed_at: number | null; hold_minutes: number | null; contracts: number; avg_entry: number; avg_exit: number | null;
    cost: number; realized_pnl: number | null; pnl_pct: number | null; unit: "share" | "contract"; price_note: string;
  };
  note?: string;
  fills?: CardFill[];
  position?: { open: number; avg_cost: number | null; realized: number } | null;
  path?: { state: MetricState; note: string; source?: string; fetched_at?: number | null } & Partial<Record<
    "underlying_mfe_pct" | "underlying_mae_pct" | "underlying_exit_efficiency" | "underlying_giveback_pct" | "moved_in_favor_first"
    | "option_mfe_pct" | "option_mae_pct" | "option_exit_efficiency", number | null>> & { option_path_quality?: string | null };
  context?: { state: MetricState; note: string; fill_id?: string; source?: string; as_of?: number | null; single_venue?: boolean;
    flags?: Record<string, boolean | null> } & Partial<Record<
    "entry_underlying_price" | "entry_vwap" | "entry_vs_vwap_pct" | "rvol_time_adjusted" | "simple_relative_volume" | "chase_score"
    | "entry_distance_from_day_high_pct" | "entry_distance_from_day_low_pct" | "entry_distance_from_premarket_high_pct"
    | "entry_distance_from_premarket_low_pct" | "entry_distance_from_prev_high_pct" | "entry_distance_from_prev_low_pct" | "entry_gap_pct", number | null>>;
};
export type OptionMark = { mark: number | null; mark_per_contract: number | null; basis: "mid" | "last" | null; bid: number | null; ask: number | null;
  last: number | null; provider: string | null; quoted_at: number | null; open_pnl: number | null };

async function read<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(apiUrl(path), { cache: "no-store", signal });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "The journal could not be read. Try again.");
  return body as T;
}
export const fetchFillCard = (id: string, signal?: AbortSignal) => read<TradeCardData>(`/charts/journal/fills/${encodeURIComponent(id)}`, signal);
export const fetchTradeCard = (id: string, signal?: AbortSignal) => read<TradeCardData>(`/charts/journal/trades/${encodeURIComponent(id)}`, signal);
export const fetchOptionMark = (id: string) => read<OptionMark>(`/charts/journal/trades/${encodeURIComponent(id)}/mark`);

/** A mark older than this reads as stale on the card. */
export const MARK_STALE_SECONDS = 5 * 60;

/** A stock position's open P&L at a price on the chart's own axis; options have no such number here (their mark is the card's request). */
export function stockOpenPnl(position: ChartPosition, last: number | null | undefined): number | null {
  if (position.instrument !== "stock" || position.avg_cost == null || last == null || !Number.isFinite(last)) return null;
  return (last - position.avg_cost) * position.open * (position.direction === "short" ? -1 : 1);
}

/** The price line's title: what it is, never letting an option line read as a premium. */
export function positionLineTitle(position: ChartPosition & { pnl?: number | null }): string {
  const size = `${position.open % 1 ? position.open.toFixed(2) : position.open}`;
  if (position.instrument !== "stock") return `${position.contract.replace(`${position.contract.split(" ")[0]} `, "")} ×${size} · underlying at entry`;
  const pnl = position.pnl == null ? "" : ` · ${position.pnl < 0 ? "−" : "+"}$${Math.abs(position.pnl).toFixed(2)} open`;
  return `Avg ${size} sh · ${position.account}${pnl}`;
}

/** A position's line on the chart's split-adjusted basis, like a saved level dated the day it opened. */
export const openedOn = (stamp: number) => new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date(stamp * 1000));

// --- Historical chart mode (C3.3) ---

/** A past trade or fill to show: its symbol and the moments to centre. */
export type PastView = { symbol: string; from: number; to: number; trade: string | null; fill: string | null };

/** The link from a trade or fill page. Times are UTC seconds. */
export function chartLink({ symbol, from, to, trade, fill }: { symbol: string; from: number; to?: number | null; trade?: string | null; fill?: string | null }): string {
  const query = new URLSearchParams({ symbol, from: String(from), to: String(to ?? from) });
  if (trade) query.set("trade", trade);
  if (fill) query.set("fill", fill);
  return `/charts?${query}`;
}

const TICKER = /^[A-Z][A-Z0-9./-]{0,14}$/;
const ID = /^[0-9a-f-]{36}$/i;

/** The view a `/charts?symbol=…&from=…` link asks for, or null for an ordinary visit. Anything malformed is ignored, not guessed at. */
export function parsePastView(search: string, now = Date.now() / 1000): PastView | null {
  const query = new URLSearchParams(search);
  const symbol = (query.get("symbol") ?? "").toUpperCase();
  const from = Number(query.get("from"));
  const to = Number(query.get("to") ?? from);
  // From 2000 to today: a time outside that is a broken link, not a trade.
  if (!TICKER.test(symbol) || !Number.isInteger(from) || !Number.isInteger(to) || from < 946684800 || to < from || to > now + 86400) return null;
  const trade = query.get("trade");
  const fill = query.get("fill");
  return { symbol, from, to, trade: trade && ID.test(trade) ? trade : null, fill: fill && ID.test(fill) ? fill : null };
}

/**
 * Where a history page should end so the view's candles are in it: the end of
 * the last day's extended session (20:00 New York) for intraday charts; for
 * daily and weekly charts, about three months later so the trade has context
 * on both sides. Never later than now.
 */
export function pastPageEnd(view: PastView, interval: Interval, now = Date.now() / 1000): number {
  if (!intradayInterval(interval)) return Math.floor(Math.min(now, view.to + 91 * 86400));
  const day = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(view.to * 1000));
  // 20:00 New York is 00:00 or 01:00 UTC the next day, by daylight saving; take the later and let the page stop at the last bar.
  const end = Date.parse(`${day}T20:00:00Z`) / 1000 + 5 * 3600;
  return Math.floor(Math.min(now, end));
}

/** A journal time (a New York wall clock without a zone, as the API returns it) as UTC seconds; null if unreadable. */
export function newYorkSeconds(wall: string | null | undefined): number | null {
  if (!wall) return null;
  if (/(Z|[+-]\d\d:?\d\d)$/.test(wall)) { const at = Date.parse(wall); return Number.isNaN(at) ? null : Math.floor(at / 1000); }
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/.exec(wall);
  if (!m) return null;
  const asUtc = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] ?? 0));
  const clock = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  const wanted = `${m[1]}-${m[2]}-${m[3]}, ${m[4]}:${m[5]}`;
  // New York is four or five hours behind UTC: the offset that gives back the same wall clock.
  for (const hours of [4, 5]) {
    const at = asUtc + hours * 3_600_000;
    if (clock.format(new Date(at)) === wanted) return Math.floor(at / 1000);
  }
  return Math.floor((asUtc + 5 * 3_600_000) / 1000); // a wall time skipped by the spring change
}
