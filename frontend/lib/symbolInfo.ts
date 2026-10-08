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

export type OverviewBlock = {
  state: "ready" | "none" | "loading" | "unavailable"; source: string;
  fetched_at: number | null; message: string | null;
};
export type OverviewCompany = OverviewBlock & { name: string | null; sector: string | null; employees: number | null; ipo_date: string | null; description: string | null };
export type OverviewRatios = OverviewBlock & { pe: number | null; price_to_sales: number | null; price_to_book: number | null; ev_to_ebitda: number | null; dividend_yield: number | null; beta_60_month: number | null };
export type OverviewStatistics = OverviewBlock & { market_cap: number | null; enterprise_value: number | null; shares_outstanding: number | null; institutional_ownership: number | null; average_volume_30_day: number | null; average_volume_90_day?: number | null };
export type SymbolOverview = {
  symbol: string; state: "ready" | "none" | "unavailable";
  datasets: { company: OverviewCompany; ratios: OverviewRatios; statistics: OverviewStatistics };
};

export async function fetchSymbolOverview(symbol: string, signal: AbortSignal): Promise<SymbolOverview> {
  const response = await fetch(apiUrl(`/charts/symbol/${encodeURIComponent(symbol)}/overview`), { signal, cache: "no-store" });
  if (!response.ok) throw new Error("Overview unavailable. Try again.");
  return response.json();
}

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
export type ReactionSession = {
  date: string; previous_date: string | null; state: "ready" | "unavailable"; reason: string | null;
  gap_pct: number | null; day_pct: number | null;
};
export type EarningsReaction = {
  report_date: string; label: string | null; state: "ready" | "unavailable"; reason: string | null;
  sessions: ReactionSession[]; reaction_date: string | null; gap_pct: number | null; reaction_pct: number | null;
};
export type ReactionSummary = {
  state: "ready" | "none" | "loading" | "unavailable"; message: string | null; source: string; fetched_at: number | null;
  earnings_fetched_at: number | null; earnings_stale: boolean; earnings_message: string | null;
  stale: boolean; price_basis: string; adjustment: Record<string, unknown>; rows: EarningsReaction[];
  usable_count: number; average_abs_pct: number | null; report_range: { from: string; to: string } | null;
};
export type SymbolForecast = {
  symbol: string; today: string; source: string; spot: number | null; earnings: EarningsNext | null;
  state: "ready" | "none" | "unavailable"; message: string | null; moves: ImpliedMove[]; earnings_note?: string | null;
};

/** Inferred earnings reactions (T2.2): read once per symbol, apart from the forecast so the implied move is never held up. */
export async function fetchSymbolReactions(symbol: string, signal: AbortSignal): Promise<ReactionSummary> {
  const response = await fetch(apiUrl(`/charts/symbol/${encodeURIComponent(symbol)}/reactions`), { signal, cache: "no-store" });
  if (!response.ok) throw new Error("Earnings reactions unavailable.");
  return response.json();
}

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

/** One headline (T1.2), already normalized by the backend from Alpaca (Benzinga) or Polygon. */
export type NewsArticle = {
  id: string; provider: "alpaca_benzinga" | "polygon"; publisher: string | null; headline: string; url: string;
  /** UTC ISO time. */
  published_at: string; summary: string | null; tickers: string[];
  /** Tags more than three symbols; Focused hides these. */
  roundup: boolean;
  /** Polygon's per-ticker opinion; never ours. */
  sentiment: { ticker: string; sentiment: "positive" | "negative" | "neutral"; reasoning: string | null }[];
  also_in: string[];
};
/** How one source went: `stale` serves an older copy (`age_seconds` old); `failed` and `not_configured` show nothing from it. */
export type NewsSource = { provider: string; label: string; state: "ok" | "stale" | "failed" | "not_configured"; fetched_at: number | null; age_seconds: number | null; message: string | null };
export type SymbolNews = {
  symbol: string; as_of: string; time_zone: string; days: number; sentiment_note: string;
  sources: NewsSource[]; articles: NewsArticle[];
};
export const NEWS_SHOWN = 20;
/** What the News tab lists: the newest 20, with Focused hiding articles that tag more than three symbols. */
export const listedNews = (articles: NewsArticle[], focused: boolean) => articles.filter((a) => !(focused && a.roundup)).slice(0, NEWS_SHOWN);

export async function fetchSymbolNews(symbol: string, signal: AbortSignal): Promise<SymbolNews> {
  const response = await fetch(apiUrl(`/charts/symbol/${encodeURIComponent(symbol)}/news`), { signal, cache: "no-store" });
  if (!response.ok) throw new Error("News unavailable. Try again.");
  return response.json();
}

/** "5 min ago", from the article's time to `now` (ms). */
export function ago(publishedAt: string, now: number): string {
  const minutes = Math.max(0, Math.floor((now - Date.parse(publishedAt)) / 60_000));
  return minutes < 1 ? "just now" : minutes < 60 ? `${minutes} min ago` : minutes < 1440 ? `${Math.floor(minutes / 60)} h ago` : `${Math.floor(minutes / 1440)} d ago`;
}
export const newYorkTime = (publishedAt: string) => `${new Date(publishedAt).toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} ET`;

export type AnalystBlock<T> = { state: "ready" | "none" | "unavailable"; source: string; provider?: string; fetched_at?: number; message?: string | null; note?: string; value?: T };
export type AnalystEstimate = { period: string; eps?: { avg: number; low: number | null; high: number | null; analysts: number | null; growth: number | null }; revenue?: { avg: number; low: number | null; high: number | null; analysts: number | null; growth: number | null } };
export type AnalystAction = { date: string; firm: string; to_grade: string | null; from_grade: string | null; action: string | null; target: number | null; prior_target: number | null };
export type AnalystBeat = { quarter: string; actual: number; estimate: number; surprise: number | null; result: "beat" | "miss" | "met" };
export type SymbolAnalysts = {
  symbol: string; state: "ready" | "none" | "unavailable";
  blocks: {
    targets: AnalystBlock<{ mean: number | null; median: number | null; high: number | null; low: number | null }>;
    ratings: AnalystBlock<{ strong_buy: number | null; buy: number | null; hold: number | null; sell: number | null; strong_sell: number | null }>;
    estimates: AnalystBlock<AnalystEstimate[]>; history: AnalystBlock<AnalystBeat[]>; actions: AnalystBlock<AnalystAction[]>;
  };
  providers: Record<string, { label: string; fetched_at: number | null; message: string | null }>;
};

/** Analyst targets, ratings, estimates and actions (T2.3), cached a day on the server. */
export async function fetchSymbolAnalysts(symbol: string, signal: AbortSignal): Promise<SymbolAnalysts> {
  const response = await fetch(apiUrl(`/charts/symbol/${encodeURIComponent(symbol)}/analysts`), { signal, cache: "no-store" });
  if (!response.ok) throw new Error("Analyst data unavailable. Try again.");
  return response.json();
}

/** The Short tab (T3.1): FINRA short interest, daily short volume and the borrow flag, normalized by the backend. */
export type ShortBlockMeta = {
  state: "ready" | "none" | "unavailable"; source: string; fetched_at: number | null; age_seconds: number | null;
  /** True when the read failed and the rows are an older copy; `message` says why. */
  stale: boolean; message: string | null; none_message?: string | null;
};
export type ShortInterest = ShortBlockMeta & {
  settlement_date?: string; short_interest?: number; avg_daily_volume?: number | null; days_to_cover?: number | null;
  settlement_note?: string; pct_note?: string; shares_outstanding?: number | null; shares_basis?: string | null;
  pct_of_shares_outstanding?: number | null; pct_message?: string | null;
  previous?: { settlement_date: string; short_interest: number; change_pct: number } | null;
};
export type ShortVolumeRow = { date: string; short_volume: number; total_volume: number; ratio_pct: number };
export type ShortVolume = ShortBlockMeta & { rows?: ShortVolumeRow[]; average_pct?: number; note?: string };
export type ShortBorrow = {
  state: "ready" | "unavailable"; source: string; fetched_at: number | null; age_seconds: number | null; stale: boolean;
  message: string | null; hard_to_borrow: boolean | null; note?: string;
};
export type SymbolShort = { symbol: string; as_of: string; time_zone: string; state: "ready" | "none" | "unavailable"; interest: ShortInterest; volume: ShortVolume; borrow: ShortBorrow };

export async function fetchSymbolShort(symbol: string, signal: AbortSignal): Promise<SymbolShort> {
  const response = await fetch(apiUrl(`/charts/symbol/${encodeURIComponent(symbol)}/short`), { signal, cache: "no-store" });
  if (!response.ok) throw new Error("Short data unavailable. Try again.");
  return response.json();
}

/** "2 d old", "5 h old": the age of a cached copy, from the backend's `age_seconds`. */
export const copyAge = (seconds: number | null) => seconds == null ? "age unknown"
  : seconds < 3600 ? `${Math.max(1, Math.floor(seconds / 60))} min old` : seconds < 86_400 ? `${Math.floor(seconds / 3600)} h old` : `${Math.floor(seconds / 86_400)} d old`;

/** The Peers strip (T3.4): Polygon's related companies with today's move from one Tradier quote call. */
export type PeerSource = { provider: string; label: string; state: "ok" | "stale" | "failed" | "not_configured"; fetched_at: number | null; age_seconds: number | null; message: string | null };
export type Peer = { symbol: string; name: string | null; last: number | null; change_percentage: number | null };
export type SymbolPeers = {
  symbol: string; as_of: string;
  /** `none`: Polygon lists no related companies (an ETF); `unavailable`: no list could be read. */
  state: "ready" | "none" | "unavailable";
  source: PeerSource; quotes: PeerSource; peers: Peer[];
};

export async function fetchSymbolPeers(symbol: string, signal: AbortSignal): Promise<SymbolPeers> {
  const response = await fetch(apiUrl(`/charts/symbol/${encodeURIComponent(symbol)}/peers`), { signal, cache: "no-store" });
  if (!response.ok) throw new Error("Peers unavailable.");
  return response.json();
}

/** One fiscal quarter from SEC EDGAR (T3.2). `gap` rows are Q4, reported only in the annual 10-K: every value null. */
export type FinancialQuarter = {
  start: string | null; end: string; gap: boolean; fiscal_year: number | null; fiscal_period: string | null; filed: string | null;
  revenue: number | null; gross_profit: number | null; operating_income: number | null; net_income: number | null; eps_diluted: number | null;
  gross_margin: number | null; operating_margin: number | null;
  revenue_yoy: number | null; net_income_yoy: number | null; eps_diluted_yoy: number | null;
};
export type SymbolFinancials = {
  symbol: string; state: "ready" | "none" | "unavailable"; message: string | null; source: string; entity: string | null;
  fetched_at: number | null; stale: boolean; latest_end: string | null; quarters: FinancialQuarter[];
};

/** The Financials tab (T3.2), cached on the server until the next 10-Q is due. */
export async function fetchSymbolFinancials(symbol: string, signal: AbortSignal): Promise<SymbolFinancials> {
  const response = await fetch(apiUrl(`/charts/symbol/${encodeURIComponent(symbol)}/financials`), { signal, cache: "no-store" });
  if (!response.ok) throw new Error("Financials unavailable. Try again.");
  return response.json();
}
