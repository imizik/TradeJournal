import type { MorningMonth } from "./joMorning";
import type { MarketReadsView } from "./marketReads";
import type { PlansView } from "./conditionalPlans";
export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

/** Relative browser requests stay on the private frontend origin. Server-side
 * fetch needs an absolute internal URL; it never inherits a browser Host header. */
export function apiUrl(path: string): string {
  const base = typeof window === "undefined" && API.startsWith("/")
    ? process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8080"
    : API;
  return `${base}${path}`;
}

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

export type Health = {
  status: string;
  environment: {
    name: string;
    backend: string;
    /** Redacted "host/database" (or filename). Never contains credentials. */
    identity: string;
    is_local: boolean;
    destructive_requires_confirmation: boolean;
  };
};

export type DecisionRecord = {
  id: string;
  operation_id: string;
  opportunity_id: string;
  actor: string;
  decision: "take" | "wait" | "skip";
  symbol: string;
  received_at: string;
  input_cutoff: string;
  policy_version: string;
  policy_hash: string;
  evidence: Record<string, unknown>;
  evidence_sha256: string;
  plan: Record<string, unknown>;
  rationale: string;
  wait_condition: string | null;
  wait_expiry: string | null;
  record_sha256: string;
  status: "practice_draft_unarmed";
};

export type PaperEvent = {
  type: string; key: string; at: number; seq: number; recorded_at: number; source: string;
  reconstructed: boolean; delivery: string | null; delivery_error: string | null;
  [field: string]: unknown;
};

export type PaperOutcome = {
  cost_version: string; entry_fill: number; exit_fill: number; net_per_share: number; planned_r: number;
  entry_to_stop_exposure: number; exit_kind: string; ambiguous: boolean; gap: boolean;
};

export type PaperState = {
  record_id: string;
  status: "unarmed" | "armed" | "triggered" | "open" | "closed" | "expired" | "missed" | "rejected" | "unresolved";
  policy_version: string | null;
  events: PaperEvent[];
  outcome: PaperOutcome | null;
  outcome_x3: PaperOutcome | null;
};

export type DecisionContext = {
  context_id: string;
  symbol: string;
  captured_at: string;
  provider: string;
  context_sha256: string;
  price_facts: { name: string; value: number; source: string; formed_at: string; observed_at: string; unit: string; split_basis: string }[];
  packet: Record<string, unknown>;
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
  win_rate: number | null;
  total_pnl: number;
  total_premium_risked: number;
  today_pnl: number;
  avg_win_pct: number | null;
  avg_loss_pct: number | null;
  avg_hold_mins: number | null;
  expired_worthless_rate: number;
  by_ticker: Record<string, { count: number; win_rate: number | null; total_pnl: number; avg_pnl_pct: number | null }>;
  by_tag: Record<string, { count: number; win_rate: number | null; total_pnl: number; avg_pnl_pct: number | null }>;
  by_time_bucket: Record<string, { count: number; win_rate: number | null; total_pnl: number; avg_pnl_pct: number | null }>;
  behavioral_flags: Record<string, number>;
};

export type AnalyticsSummary = {
  count: number;
  pnl_count: number;
  percentage_count: number;
  entry_days: number;
  total_pnl: number | null;
  expectancy: number | null;
  median_pnl: number | null;
  win_rate: number | null;
  profit_factor: number | null;
  no_losses: boolean;
  avg_winner: number | null;
  avg_loser: number | null;
  avg_pnl_pct: number | null;
};

export type AnalyticsGroup = AnalyticsSummary & { label: string; trade_ids: string[] };
export type AnalyticsDimension = "ticker" | "entry_time" | "tag" | "hold_duration" | "instrument" | "repeat_entry";
export type Analytics = {
  summary: AnalyticsSummary & { max_drawdown: number | null };
  coverage: { missing_pnl: number; missing_percentage: number; undated_closed_in_scope: number };
  curve: { date: string; pnl: number; cumulative_pnl: number }[];
  concentration: {
    limit: number; removed_count: number; winner_pnl: number | null;
    gross_profit_share: number | null; remaining_pnl: number | null; trade_ids: string[];
  }[];
  breakdowns: Record<AnalyticsDimension, AnalyticsGroup[]>;
  trades: (Pick<Trade, "id" | "account_id" | "ticker" | "instrument_type" | "option_type" | "strike" | "expiration" | "opened_at" | "status" | "realized_pnl" | "pnl_pct"> & { closed_at: string })[];
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
  source_data_stale?: boolean;
  source_data_stale_reason?: string;
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
  /** Prompt v2 (plan reviews): the last review's rules checked, today vs the trader's normal, what data was missing. */
  rules_check?: RuleCheck[];
  vs_baseline?: string[];
  data_gaps?: string[];
  /** Prompt v3: the day's market backdrop in a sentence or two, and each captured plan against what was done. */
  market_read?: string;
  plan_vs_execution?: PlanCheck[];
  generated_by?: string;
  expectation_checks?: {
    entry_id: string;
    expected: string;
    observed: string;
    assessment: "supported" | "invalidated" | "mixed" | "unresolved";
    evidence: string;
  }[];
};

export type DayJournalEntry = {
  id: string;
  operation_id: string;
  day: string;
  kind: "outlook" | "update" | "idea" | "reflection" | "decision" | "horizon" | "plan_ask" | "plan_done";
  text: string;
  symbol: string | null;
  not_traded: boolean;
  created_at: string;
  actor: "owner";
};
export type DayTradePlan = {
  captured_at: string;
  underlying?: string | null;
  side?: string | null;
  setup?: string | null;
  plan?: string | null;
  note?: string | null;
  later_notes?: { text: string; created_at: string; kind?: string | null }[];
  marked_not_taken?: boolean;
  [key: string]: unknown;
};
export type DayTradePlans = { by_trade?: Record<string, DayTradePlan[]>; not_traded?: DayTradePlan[] };
export type DayJournal = { day: string; entries: DayJournalEntry[]; trade_plans: DayTradePlans };
export type DayJournalWrite = {
  operation_id: string;
  kind: DayJournalEntry["kind"];
  text: string;
  symbol?: string | null;
  not_traded?: boolean;
};

export type RuleCheck = { rule: string; set_on: string; result: "kept" | "broken" | "partly" | "not_tested"; evidence: string };
export type PlanCheck = { ticker: string; planned: string; did: string; result: "followed" | "deviated" | "partly" | "no_plan" };

/** The nightly reviews on the Claude plan (backend app/jobs/plan_reviews.py): the last run's status file. */
export type PlanRunnerStatus = {
  configured: boolean;
  status: null | {
    started_at: string; finished_at: string | null;
    state: "running" | "ok" | "failed" | "nothing" | "interrupted";
    message: string; written: { day: string; reason: string; grade: string | null }[];
    failed: { day: string; reason: string; error: string }[];
    usage: { input_tokens: number; output_tokens: number; api_equivalent_usd: number }; model: string | null;
  };
};

export type MonthlyFinding = { finding: string; evidence: string };
export type MonthlyReview = {
  summary: string;
  month_grade: string;
  edge: MonthlyFinding[];
  leaks: MonthlyFinding[];
  recurring_patterns: MonthlyFinding[];
  rules_scorecard: { rule: string; kept: number; broken: number; verdict: "keep" | "tighten" | "drop" | "now_a_habit" }[];
  last_commitment_check: { commitment: string; result: "kept" | "broken" | "partly" | "unclear"; evidence: string } | null;
  one_commitment: string;
  vs_last_month: string[];
  data_gaps: string[];
  generated_by?: string;
};
export type MonthlyReviewResponse = { month: string; review: MonthlyReview; generated_at: string | null; trade_count: number };
export type MonthlyReviewIndexItem = { month: string; closed_trades: number; saved: boolean; grade: string | null; generated_at: string | null };

export type WeeklyRuleKey = "winner_to_red" | "held_hour_red" | "expiry_day";
export type WeeklyResult = "kept" | "partly" | "broken" | "not_enough";
export type WeeklyTradeRow = {
  trade_id: string | null; contract: string; opened_at: number | null; closed_at: number | null; status: string;
  realized_pnl: number | null; state: "kept" | "broke" | "unmeasured" | null;
};
export type WeeklyRule = {
  week_start: string; rule_key: WeeklyRuleKey | null; rule_text: string | null; label: string | null; params: Record<string, number>;
  note: string | null; chosen_at: number | null; result: WeeklyResult | null; result_source: "suggested" | "changed" | null;
};
export type WeeklyRuleCheck = {
  entered: number; closed: number; tested: number; broke: number; kept: number; unmeasured: number; order_unclear: number;
  suggested: WeeklyResult; trades: WeeklyTradeRow[]; still_open: WeeklyTradeRow[]; frozen: boolean; checked_at?: number | null;
};
export type WeeklyLeak = { key: WeeklyRuleKey; label: string; rule_text: string; count: number; pnl: number; unmeasured: number; trades: WeeklyTradeRow[] };
export type WeeklyReview = {
  week_start: string; week_end: string; in_progress: boolean;
  summary: { trades: number; pnl: number; wins: number; losses: number };
  coverage: { trades: number; with_path: number; accounts: string[] };
  leaks: WeeklyLeak[];
  previous: (WeeklyRule & { check?: WeeklyRuleCheck }) | null;
  chosen: WeeklyRule | null;
  history: WeeklyRule[];
  rules: { key: WeeklyRuleKey; label: string; rule_text: string }[];
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
  /** Realized P&L of the trades that closed that day; null when none closed with a recorded P&L. */
  closed_pnl?: number | null;
  saved: boolean;
  generated_at: string | null;
  source_data_stale: boolean;
};

export type FillMarketContext = {
  calculation_version: string | null;
  entry_context_as_of: string | null;
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
  calculation_version: string | null;
  option_path_quality: string | null;
  option_peak_total_pnl: number | null;
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
  option_peak_unrealized_pnl: number | null;
  option_worst_unrealized_pnl: number | null;
  option_giveback_from_peak: number | null;
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
  phase?: string | null;
  wait_provider?: string | null;
  wait_reason?: string | null;
  wait_until?: string | null;
  error: string | null;
  job_id?: string | null;
  status?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  updated_at?: string | null;
};

/** One open-trade phone alert, as `GET /trades/{id}/phone-alerts` lists it (the trade page reads the rest). */
export type TradePhoneAlert = { id: string; kind: "giveback" | "expiry_first" | "expiry_final" | "hold_hour"; detected_at: number;
  contracts: number; gain: number | null; gain_pct: number | null; peak_gain: number | null; peak_gain_pct: number | null };

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
  phase: string | null;
  wait_provider: string | null;
  wait_reason: string | null;
  wait_until: string | null;
  progress_unit: string;
  api_provider?: string;
  rate_limit_per_minute?: number;
  job_id: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string | null;
  last_run_at: string | null;
};

export type SyncSummary = {
  running: boolean;
  active_job: SyncJob | null;
  last_success_at: string | null;
  errors_count: number;
};

export type GmailHealth = {
  status: "live" | "degraded" | "down" | "off";
  message: string;
  action: "reconnect_gmail" | null;
  listener_enabled: boolean;
  last_notification_at: string | null;
  last_import_at: string | null;
  watch_expires_at: string | null;
  // Changes whenever imported fills or rebuilt trades change.
  data_version: string;
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
  context_as_of?: string | null;
  checks?: ValidationCheck[];
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
  reference_revision?: string;
  validation?: {
    checks: ValidationCheck[];
    broker_verification: string;
    limits?: string[];
    option?: { values: Record<string, number | null>; reason: string | null; bars?: number; peak_minute?: string | null; samples?: { timestamp: string; quantity: number; cost_basis: number; realized: number; favorable: number; adverse: number; total: number }[] } | null;
    underlying?: { samples?: { timestamp: string; high: number; low: number }[] } | null;
  };
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

export type ValidationCheck = {
  field: string;
  fill_id?: string;
  stored?: number | string | null;
  reference?: number | string | null;
  difference?: number | null;
  status: "matched" | "mismatch" | "stale" | "unavailable" | "error";
  kind?: string;
  reason?: string | null;
};

export type TradingViewAnalysisStatus =
  | "pending"
  | "running"
  | "done"
  | "skipped"
  | "error";

export type TradingViewVerdict =
  | "no_trade"
  | "wait"
  | "long_scalp"
  | "short_scalp";

export type ScannerEventRow = Record<string, unknown> & { at: string };

export type ScannerShadowRow = {
  publication: "written" | "expired" | null;
  decision: "take" | "skip" | null;
  reason: string | null;
  unresolved_reason: string | null;
  timing: "on_time" | "late" | null;
  clean_order: boolean | null;
  labels: string[];
  status: "not_published" | "no_contract" | "awaiting_decision" | "no_response" | "skipped" | "late" | "pending_entry" | "open" | "exiting" | "exit" | "unresolved";
  entry: ScannerEventRow | null;
  exit: ScannerEventRow | null;
  exit_intent: ScannerEventRow | null;
  result: { pnl: number; pnl_2x_spread: number; return_on_premium: number | null } | null;
};

export type ScannerIsaacTrade = {
  trade_id: string;
  contract: { ticker: string; option_type: string | null; strike: number | null; expiration: string | null };
  opened_at: string;
  status: string;
  realized_pnl: number | null;
  pnl_per_contract: number | null;
  assisted: boolean;
  contract_differs: boolean;
};

export type ScannerIsaacRow = {
  traded: boolean;
  trade_id: string | null;
  contract: ScannerIsaacTrade["contract"] | null;
  opened_at: string | null;
  status: string | null;
  realized_pnl: number | null;
  pnl_per_contract: number | null;
  assisted: boolean;
  contract_differs: boolean;
  extra_trade_ids: string[];
  trades: ScannerIsaacTrade[];
};

type Evidence = "not enough" | "sufficient count";
export type ScannerDisagreement = {
  count: number;
  rules_priced: number;
  rules_pnl: number;
  shadow_priced: number;
  shadow_pnl: number;
  isaac_priced: number;
  isaac_pnl_per_contract: number;
  isaac_pnl_dollars: number;
  evidence: Evidence;
};
export type ScannerIsaacScore = {
  setups: number;
  traded: number;
  assisted: number;
  independent: number;
  closed: number;
  priced: number;
  pnl_per_contract: number;
  pnl_dollars: number;
  evidence: Evidence;
  group_evidence: { assisted: Evidence; independent: Evidence; closed: Evidence };
  disagreements: Record<"shadow_only" | "isaac_only" | "both_took" | "both_passed", ScannerDisagreement>;
};

export type ScannerScorecard = {
  not_published: number;
  shadow_setups: number;
  isaac: ScannerIsaacScore;
  independent: ScannerIsaacScore;
  setups: number;
  decisions: number;
  take: number;
  skip: number;
  late: number;
  no_response: number;
  unresolved: number;
  rules_priced: number;
  shadow_priced: number;
  skipped_priced: number;
  rules_pnl: number;
  shadow_pnl: number;
  skipped_rules_pnl: number;
  clean_order: number;
  evidence: "not enough" | "sufficient count";
  group_evidence: {
    rules: "not enough" | "sufficient count";
    takes: "not enough" | "sufficient count";
    skipped: "not enough" | "sufficient count";
  };
};

export type ScannerCandidateRow = {
  id: string;
  scanner_version: string;
  params_hash: string;
  symbol: string;
  setup: "fade" | "orb";
  direction: "long" | "short";
  bar_end: string;
  detected_at: string;
  stop: number;
  target: number;
  flags: string[];
  facts: Record<string, number | string | string[]>;
  contract: {
    symbol: string;
    expiration: string;
    option_type: string;
    strike: number;
    delta: number;
    bid: number;
    ask: number;
  } | null;
  status: "no_contract" | "pending_entry" | "open" | "exiting" | "exit" | "unresolved";
  shadow: ScannerShadowRow;
  isaac: ScannerIsaacRow;
  // The latest the rules paper trade exits: its 60-minute time stop, or flat-by-close when earlier.
  paper_deadline: { at: string; kind: "time_stop" | "flat" } | null;
  events: Record<string, ScannerEventRow>;
};

export type ScannerMonitoring = {
  state: "off" | "not_running" | "market_closed" | "calendar_unknown" | "outside_window" | "fresh" | "stale";
  checked_at: string;
  last_judged_bar_end: string | null;
  symbols_judged: number;
  symbols_selected: number;
};

export type ScannerSettings = { symbols: string[]; revision: number; max_symbols: number };

export type ScannerDay = {
  date: string;
  scanner_version: string;
  params_hash: string;
  enabled: boolean;
  totals: {
    candidates: number;
    trades: number;
    resolved: number;
    unresolved: number;
    no_contract: number;
    pnl: number;
    pnl_2x_spread: number;
    wins: number;
  };
  scorecard: { day: ScannerScorecard; cumulative: ScannerScorecard };
  candidates: ScannerCandidateRow[];
  session: "open" | "closed" | "unknown";
  monitoring: ScannerMonitoring;
};

export type TradingViewAlert = {
  alert_id: string;
  contract_version: number;
  parser_revision: string;
  indicator_version: string;
  content_sha256: string;
  raw_payload_sha256: string;
  symbol: string;
  timeframe: string;
  setup: string;
  side: "long" | "short";
  /** Exact decimal text, never a JS number. */
  price: string;
  bar_time_ms: number;
  bar_time: string;
  received_at: string;
  updated_at: string;
  analysis_status: TradingViewAnalysisStatus;
  analysis_attempts: number;
  analysis_started_at: string | null;
  analysis_completed_at: string | null;
  scorer_revision: string | null;
  verdict: TradingViewVerdict | null;
  confidence: "low" | "medium" | "high" | null;
  analysis_error_code: string | null;
};

/** Tagged so exact decimal text and original scalar types stay distinguishable. */
export type TradingViewSnapshotValue = {
  type: "null" | "boolean" | "string" | "number";
  value: boolean | string | null;
};

export type TradingViewScalpPlanLevel = {
  level: string;
  price: number | null;
  description?: string;
};

export type TradingViewScalpAssessment = {
  verdict: TradingViewVerdict;
  confidence: "low" | "medium" | "high";
  bias: string;
  market_state: string;
  style: string;
  setup_score: number | null;
  liquidity_score: number | null;
  risk_score: number | null;
  reasons_for: string[];
  reasons_against: string[];
  missing: string[];
  trigger: TradingViewScalpPlanLevel | null;
  invalidation: TradingViewScalpPlanLevel | null;
  targets: TradingViewScalpPlanLevel[];
  data_source_notes?: string[];
  disclaimer?: string;
};

export type TradingViewAlertDetail = TradingViewAlert & {
  payload_json: string;
  levels: Record<string, TradingViewSnapshotValue>;
  context: Record<string, TradingViewSnapshotValue>;
  assessment: { assessment?: TradingViewScalpAssessment } | null;
  analysis_error: string | null;
};

export function createApi(fetcher: typeof fetch = (input, init) => fetch(input, init)) {
async function get<T>(path: string): Promise<T> {
  const res = await fetcher(apiUrl(path), { cache: "no-store" });
  if (!res.ok) throw await buildApiError(path, res);
  return res.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetcher(apiUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw await buildApiError(path, res);
  return res.json();
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetcher(apiUrl(path), {
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

return {
  practiceRuns: () => get<{ runs: { id: string; day: string }[] }>("/practice/runs"),
  decisions: () => get<{ decisions: DecisionRecord[] }>("/decisions"),
  decision: (id: string) => get<DecisionRecord>(`/decisions/${encodeURIComponent(id)}`),
  paperState: (id: string) => get<PaperState>(`/decisions/${encodeURIComponent(id)}/paper`),
  armPaperPlan: (id: string, operationId: string) => post<PaperState>(`/decisions/${encodeURIComponent(id)}/arm`, { operation_id: operationId }),
  freezeDecisionContext: (symbol: string, operationId: string) => post<DecisionContext>(`/decisions/context/${encodeURIComponent(symbol)}`, { operation_id: operationId }),
  createDecision: (body: { operation_id: string; opportunity_id: string; actor: string; decision: string; symbol: string; context_id: string; rationale?: string; wait_condition?: string; wait_expiry?: string; plan?: Record<string, unknown> }) =>
    post<DecisionRecord>("/decisions", body),
  accounts: () => get<Account[]>("/accounts"),
  trades: (params?: string) => get<Trade[]>(`/trades${params ? `?${params}` : ""}`),
  trade: (id: string) => get<Trade>(`/trades/${id}`),
  tradeFills: (id: string) => get<Fill[]>(`/trades/${id}/fills`),
  bulkTradeFills: (ids: string[]) => get<Record<string, Fill[]>>(`/trades/fills/bulk?ids=${ids.join(",")}`),
  fills: () => get<Fill[]>("/fills"),
  fill: (id: string) => get<Fill>(`/fills/${id}`),
  stats: (params?: string) => get<Stats>(`/stats${params ? `?${params}` : ""}`),
  analytics: (params?: string) => get<Analytics>(`/stats/analytics${params ? `?${params}` : ""}`),
  createFill: (body: FillWriteInput) => post<{ fill: Fill; trades_rebuilt: number; anomalies: string[] }>("/fills", body),
  updateFill: (id: string, body: FillWriteInput) => put<{ fill: Fill; trades_rebuilt: number; anomalies: string[] }>(`/fills/${id}`, body),
  importFills: () => post<{ saved: number; skipped: number; enrich_started: boolean; enrich_total: number }>("/fills/import"),
  startGmailAuth: () => get<{ auth_url: string }>("/auth/gmail/start"),
  enrichMissing: (range: "day" | "week" | "month" | "all") => post<{ started: boolean; total_missing: number }>(`/fills/enrich?range=${range}`),
  enrichStatus: () => get<JobStatus>("/fills/enrich/status"),
  resyncAll: (confirm?: string) => post<{ status: string; saved: number; skipped: number; trades_rebuilt: number; anomalies: string[] }>("/fills/resync-all", confirm ? { confirm } : undefined),
  rebuild: () => post<{ status: string; trades_rebuilt: number; anomalies: string[] }>("/rebuild"),
  reviewTrade: (id: string) => post<Trade>(`/trades/${id}/review`),
  dailyReviews: () => get<DailyReviewIndexItem[]>("/daily-review"),
  planRunner: () => get<PlanRunnerStatus>("/daily-review/runner"),
  dailyReview: (day: string) => get<DailyReviewResponse | null>(`/daily-review/${day}`),
  dayJournal: (day: string) => get<DayJournal>(`/day-journal/${day}`),
  addDayJournalEntry: (day: string, body: DayJournalWrite) => post<DayJournalEntry>(`/day-journal/${day}/entries`, body),
  monthlyReviews: () => get<MonthlyReviewIndexItem[]>("/monthly-review"),
  joMorningMonth: (month: string) => get<MorningMonth>(`/jo/morning?month=${encodeURIComponent(month)}`),
  joMarketReadsMonth: (month: string) => get<MarketReadsView>(`/jo/market-reads?month=${encodeURIComponent(month)}`),
  joPlans: () => get<PlansView>("/jo/conditional-plans"),
  monthlyReview: (month: string) => get<MonthlyReviewResponse | null>(`/monthly-review/${month}`),
  reviewMonth: (month: string) => post<MonthlyReviewResponse>("/monthly-review", { month }),
  weeklyReview: (week: string) => get<WeeklyReview>(`/weekly-review/${week}`),
  chooseWeeklyRule: (week: string, rule_key: WeeklyRuleKey | null, note: string | null) =>
    put<WeeklyReview>(`/weekly-review/${week}`, { rule_key, note }),
  confirmWeeklyResult: (week: string, result: WeeklyResult) => put<WeeklyReview>(`/weekly-review/${week}/result`, { result }),
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
  gmailHealth: () => get<GmailHealth>("/gmail/health"),
  syncJobs: () => get<SyncJob[]>("/sync/jobs"),
  levelAlerts: () => get<import("./alerts").AlertsPayload>("/charts/alerts"),
  tradePhoneAlerts: (tradeId: string) => get<{ alerts: TradePhoneAlert[] }>(`/trades/${encodeURIComponent(tradeId)}/phone-alerts`),
  symbolEvents: (symbol: string) => get<import("./symbolInfo").SymbolEvents>(`/charts/symbol/${encodeURIComponent(symbol)}/events`),
  syncRuns: () => get<SyncRun[]>("/sync/runs"),
  runSyncPipeline: () => post<{ pipeline_run_id: string }>("/sync/pipeline/run"),
  runSyncJob: (jobType: string, range: "day" | "week" | "month" | "all" = "week", force = false) =>
    post<{ run_id: string; started: boolean; total: number }>(`/sync/jobs/${jobType}/run?range=${range}${force ? "&force=true" : ""}`),
  advancedRebuildAll: () => post<{ run_id: string }>("/sync/advanced/rebuild-all"),
  advancedResyncAll: (confirm?: string) => post<{ run_id: string }>("/sync/advanced/resync-all", confirm ? { confirm } : undefined),
  health: () => get<Health>("/health"),
  scannerDay: (day?: string) => get<ScannerDay>(`/scanner/day${day ? `?day=${encodeURIComponent(day)}` : ""}`),
  scannerSettings: () => get<ScannerSettings>("/scanner/settings"),
  saveScannerSettings: (symbols: string[], base_revision: number) => put<ScannerSettings>("/scanner/settings", { symbols, base_revision }),
  tradingViewAlerts: (params?: string) =>
    get<TradingViewAlert[]>(`/tradingview/alerts${params ? `?${params}` : ""}`),
  tradingViewAlert: (alertId: string) =>
    get<TradingViewAlertDetail>(`/tradingview/alerts/${encodeURIComponent(alertId)}`),
};

}
export const api = createApi();
