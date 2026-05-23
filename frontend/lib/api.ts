export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

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
  vwap_at_fill: number | null;
  gamma_at_fill: number | null;
  theta_at_fill: number | null;
  vega_at_fill: number | null;
  sma_20_at_fill: number | null;
  sma_50_at_fill: number | null;
  ema_9_at_fill: number | null;
  ema_20_at_fill: number | null;
  ema_9h_at_fill: number | null;
  rsi_14_at_fill: number | null;
  macd_at_fill: number | null;
  macd_signal_at_fill: number | null;
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

export type PositionQuote = {
  ticker: string;
  underlying_price: number | null;
  option_last_price: number | null;
  option_bid: number | null;
  option_ask: number | null;
  option_mid: number | null;
  option_iv: number | null;
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

export type DailyReview = {
  summary: string;
  day_grade: string;
  key_takeaways: string[];
  best_trade: {
    trade_id: string | null;
    ticker: string | null;
    reason: string;
  };
  worst_trade: {
    trade_id: string | null;
    ticker: string | null;
    reason: string;
  };
  patterns: string[];
  next_session_rules: string[];
};

export type DailyReviewResponse = {
  day: string;
  review: DailyReview;
  generated_at: string | null;
  trade_count: number;
};

export type DailyReviewIndexItem = {
  day: string;
  trade_count: number;
  saved: boolean;
  generated_at: string | null;
};

export type FillMarketContext = {
  fill_id: string;
  data_source: string;
  fetched_at: string;
  // Underlying price
  entry_underlying_price: number | null;
  entry_vwap: number | null;
  entry_vs_vwap_pct: number | null;
  entry_volume: number | null;
  cumulative_volume_at_entry: number | null;
  avg_daily_volume_20: number | null;
  simple_relative_volume: number | null;
  // Daily indicators
  entry_sma_20: number | null;
  entry_sma_50: number | null;
  entry_ema_9: number | null;
  entry_ema_20: number | null;
  entry_rsi_14: number | null;
  entry_macd: number | null;
  entry_macd_signal: number | null;
  entry_macd_histogram: number | null;
  entry_atr_14: number | null;
  entry_vs_ema9_pct: number | null;
  entry_vs_ema20_pct: number | null;
  // Intraday structure
  entry_day_high_so_far: number | null;
  entry_day_low_so_far: number | null;
  entry_day_range_used_pct: number | null;
  entry_distance_from_day_high_pct: number | null;
  entry_distance_from_day_low_pct: number | null;
  premarket_high: number | null;
  premarket_low: number | null;
  opening_range_5m_high: number | null;
  opening_range_5m_low: number | null;
  opening_range_15m_high: number | null;
  opening_range_15m_low: number | null;
  previous_day_high: number | null;
  previous_day_low: number | null;
  previous_day_close: number | null;
  entry_gap_pct: number | null;
  // Flags
  is_chase_entry: number | null;
  chase_score: number | null;
  is_trend_aligned: number | null;
  is_late_move: number | null;
  is_above_vwap: number | null;
  is_vwap_reclaim: number | null;
  is_opening_range_breakout: number | null;
  is_premarket_breakout: number | null;
  is_near_resistance_on_call_entry: number | null;
  is_near_support_on_put_entry: number | null;
  is_overnight: number | null;
  entry_time_bucket: string | null;
  dte_bucket: string | null;
  setup_quality_score: number | null;
  // RVOL (time-adjusted)
  rvol_time_adjusted: number | null;
  // Option moneyness
  moneyness_pct: number | null;
  is_itm: number | null;
  is_otm: number | null;
};

export type TradePathMetrics = {
  trade_id: string;
  data_source: string;
  fetched_at: string;
  hold_duration_bucket: string | null;
  exit_time_bucket: string | null;
  underlying_mfe_pct: number | null;
  underlying_mae_pct: number | null;
  time_to_underlying_mfe_minutes: number | null;
  time_to_underlying_mae_minutes: number | null;
  underlying_exit_efficiency: number | null;
  underlying_giveback_pct: number | null;
  moved_in_favor_first: number | null;
  post_exit_mfe_15m: number | null;
  post_exit_mfe_30m: number | null;
  post_exit_mfe_60m: number | null;
  time_to_post_exit_high_minutes: number | null;
  option_mfe_pct: number | null;
  option_mae_pct: number | null;
  option_max_price_seen: number | null;
  option_min_price_seen: number | null;
  time_to_option_mfe_minutes: number | null;
  option_exit_efficiency: number | null;
  option_giveback_pct: number | null;
};

export type CoverageStats = {
  fills: {
    total: number;
    polygon_enriched: number;
    polygon_missing: number;
    alpaca_enriched: number;
    alpaca_missing: number;
  };
  trades: {
    total_closed: number;
    path_metrics_done: number;
    path_metrics_missing: number;
  };
};

export type JobStatus = {
  running: boolean;
  done: number;
  total: number;
  current: string;
  enriched: number;
  error: string | null;
  job_id?: string | null;
  status?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
};

export type SyncJob = {
  job_type: string;
  label: string;
  description: string;
  advanced: boolean;
  status: "idle" | "queued" | "running" | "succeeded" | "failed" | "skipped";
  running: boolean;
  done: number;
  total: number;
  items_processed: number;
  errors_count: number;
  message: string | null;
  error_summary: string | null;
  job_id: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  last_run_at: string | null;
};

export type SyncSummary = {
  running: boolean;
  active_job: SyncJob | null;
  last_success_at: string | null;
  errors_count: number;
};

export type SyncRun = {
  id: string;
  job_type: string;
  label: string;
  status: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  items_processed: number;
  errors_count: number;
  error_summary: string | null;
  message: string | null;
};

export type AuditFillBar = {
  timestamp_utc: string;
  timestamp_et: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  bar_vwap: number | null;
  bars_back: number;
};

export type AuditFill = {
  fill_id: string;
  is_entry: boolean;
  side: string;
  executed_at_et: string;
  contracts: number;
  price: number;
  cache_file: string | null;
  cache_exists: boolean;
  total_bars_in_file: number;
  rth_bars_to_fill: number;
  pm_bars: number;
  or5_bars: number;
  raw_bar: AuditFillBar | null;
  bars_back: number | null;
  formulas: Record<string, string>;
  structure: {
    day_high_bar_et: string | null;
    day_low_bar_et: string | null;
    pm_high: number | null;
    pm_low: number | null;
    or5_high: number | null;
    or5_low: number | null;
    or15_high: number | null;
    or15_low: number | null;
  };
  stored: Record<string, number | null>;
  recomputed: Record<string, number | null>;
  discrepancies: string[];
};

export type AuditPath = {
  window_bars: number;
  window_start_et: string;
  window_end_et: string;
  entry_underlying_used?: number;
  bullish?: boolean;
  mfe_pct_recomputed?: number;
  mae_pct_recomputed?: number;
  mfe_bar_et?: string | null;
  mfe_bar_high?: number | null;
  mfe_bar_low?: number | null;
  mae_bar_et?: string | null;
  mae_bar_high?: number | null;
  mae_bar_low?: number | null;
  error?: string;
  stored: Record<string, number | null>;
};

export type AuditIndicators = {
  cache_file?: string;
  total_daily_bars_available?: number;
  earliest_bar?: string;
  latest_bar?: string;
  sma_20_bars_needed?: number;
  sma_50_bars_needed?: number;
  rsi_14_window?: number;
  warmup_note?: string;
  rsi_formula?: string;
  ema_formula?: string;
  error?: string;
};

export type TradeAudit = {
  trade_id: string;
  ticker: string;
  instrument_type: string;
  option_type: string | null;
  strike: number | null;
  expiration: string | null;
  direction: "bullish" | "bearish" | null;
  opened_at_et: string;
  closed_at_et: string | null;
  status: string;
  fills: AuditFill[];
  path: AuditPath | null;
  indicators: AuditIndicators | null;
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
  bulkTradeFills: (ids: string[]) => get<Record<string, Fill[]>>(`/trades/fills/bulk?ids=${ids.join(",")}`),
  fills: () => get<Fill[]>("/fills"),
  fill: (id: string) => get<Fill>(`/fills/${id}`),
  stats: (params?: string) => get<Stats>(`/stats${params ? `?${params}` : ""}`),
  createFill: (body: FillWriteInput) => post<{ fill: Fill; trades_rebuilt: number; anomalies: string[] }>("/fills", body),
  updateFill: (id: string, body: FillWriteInput) => put<{ fill: Fill; trades_rebuilt: number; anomalies: string[] }>(`/fills/${id}`, body),
  importFills: () => post<{ saved: number; skipped: number; enrich_started: boolean; enrich_total: number }>("/fills/import"),
  startGmailAuth: () => get<{ auth_url: string }>("/auth/gmail/start"),
  enrichMissing: (range: "day" | "week" | "month" | "all") => post<{ started: boolean; total_missing: number }>(`/fills/enrich?range=${range}`),
  enrichStatus: () => get<JobStatus>("/fills/enrich/status"),
  resyncAll: () => post<{ status: string; saved: number; skipped: number; trades_rebuilt: number; anomalies: string[] }>("/fills/resync-all"),
  rebuild: () => post<{ status: string; trades_rebuilt: number; anomalies: string[] }>("/rebuild"),
  reviewTrade: (id: string) => post<Trade>(`/trades/${id}/review`),
  dailyReviews: () => get<DailyReviewIndexItem[]>("/daily-review"),
  dailyReview: (day: string) => get<DailyReviewResponse | null>(`/daily-review/${day}`),
  reviewDay: (body: { day: string; trade_ids: string[] }) =>
    post<DailyReviewResponse>("/daily-review", body),
  positionQuotes: (positions: { ticker: string; expiration: string; strike: number; option_type: string }[]) =>
    post<PositionQuote[]>("/quotes/positions", { positions }),
  stockQuotes: (tickers: string[]) => get<Record<string, number | null>>(`/quotes?tickers=${tickers.join(",")}`),
  fillMarketContext: (fillId: string) => get<FillMarketContext>(`/market-context/fill/${fillId}`),
  bulkFillMarketContext: (fillIds: string[]) =>
    get<Record<string, FillMarketContext>>(`/market-context/fills/bulk?ids=${fillIds.join(",")}`),
  alpacaEnrichMissing: (range: "day" | "week" | "month" | "all", force?: boolean) =>
    post<{ started: boolean; total_missing: number }>(`/market-context/enrich?range=${range}${force ? "&force=true" : ""}`),
  alpacaEnrichStatus: () => get<JobStatus>("/market-context/enrich/status"),
  tradePathMetrics: (tradeId: string) => get<TradePathMetrics>(`/market-context/trade/${tradeId}`),
  computeTradePaths: (range: "day" | "week" | "month" | "all", force?: boolean) =>
    post<{ started: boolean; total_missing: number }>(`/market-context/trade-path/compute?range=${range}${force ? "&force=true" : ""}`),
  tradePathStatus: () => get<JobStatus>("/market-context/trade-path/status"),
  auditTrade: (tradeId: string) => get<TradeAudit>(`/market-context/audit/${tradeId}`),
  coverage: () => get<CoverageStats>("/market-context/coverage"),
  syncSummary: () => get<SyncSummary>("/sync/summary"),
  syncJobs: () => get<SyncJob[]>("/sync/jobs"),
  syncRuns: () => get<SyncRun[]>("/sync/runs"),
  runSyncPipeline: () => post<{ pipeline_run_id: string }>("/sync/pipeline/run"),
  runSyncJob: (jobType: string, range: "day" | "week" | "month" | "all" = "week", force = false) =>
    post<{ run_id: string; started: boolean; total: number }>(`/sync/jobs/${jobType}/run?range=${range}${force ? "&force=true" : ""}`),
  advancedRebuildAll: () => post<{ run_id: string }>("/sync/advanced/rebuild-all"),
  advancedResyncAll: () => post<{ run_id: string }>("/sync/advanced/resync-all"),
};
