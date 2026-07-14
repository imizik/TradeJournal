export type DecimalString = string;
export type StrategyVersionStatus =
  | "draft"
  | "challenger"
  | "champion"
  | "shadow"
  | "retired";
export type ExecutionTiming = "bar_close" | "next_bar" | "intrabar" | "unknown";
export type SessionMode = "regular" | "extended" | "custom";
export type CommissionType =
  | "none"
  | "percent"
  | "cash_per_order"
  | "cash_per_contract"
  | "custom";
export type SlippageType =
  | "none"
  | "ticks"
  | "percent"
  | "cash_per_order"
  | "custom";
export type StrategyRunMetricsStatus = "pending" | "ready" | "stale";
export type StrategyTradeDirection = "long" | "short";
export type StrategyTradeOutcome = "winner" | "loser" | "breakeven" | "unknown";

export type StrategyParameters = Record<string, unknown>;
export type RawCsvRow = Record<string, string | null>;

export interface StrategyDefinition {
  id: string;
  name: string;
  description: string | null;
  setup_type: string;
  created_at: string;
  updated_at: string;
}

export interface StrategyCreateInput {
  name: string;
  description?: string | null;
  setup_type?: string;
}

export interface StrategyVersionSummary {
  id: string;
  strategy_definition_id: string;
  parent_version_id: string | null;
  version_label: string;
  source_fingerprint: string;
  source_reference: string | null;
  change_summary: string | null;
  hypothesis: string | null;
  parameters: StrategyParameters;
  entry_rule_summary: string | null;
  exit_rule_summary: string | null;
  execution_timing: ExecutionTiming;
  session_mode: SessionMode;
  commission_type: CommissionType;
  commission_value: DecimalString | null;
  slippage_type: SlippageType;
  slippage_value: DecimalString | null;
  pyramiding: number;
  known_limitations: string | null;
  repainting_risk_notes: string | null;
  lookahead_risk_notes: string | null;
  status: StrategyVersionStatus;
  created_at: string;
  updated_at: string;
  locked: boolean;
}

export interface StrategyVersionDetail extends StrategyVersionSummary {
  pine_source: string;
}

export interface StrategyDetail extends StrategyDefinition {
  versions: StrategyVersionSummary[];
}

export interface StrategyVersionCreateInput {
  version_label: string;
  parent_version_id?: string | null;
  pine_source: string;
  source_reference?: string | null;
  change_summary?: string | null;
  hypothesis?: string | null;
  parameters?: StrategyParameters;
  entry_rule_summary?: string | null;
  exit_rule_summary?: string | null;
  execution_timing?: ExecutionTiming;
  session_mode?: SessionMode;
  commission_type?: CommissionType;
  commission_value?: DecimalString | null;
  slippage_type?: SlippageType;
  slippage_value?: DecimalString | null;
  pyramiding?: number;
  known_limitations?: string | null;
  repainting_risk_notes?: string | null;
  lookahead_risk_notes?: string | null;
  status?: StrategyVersionStatus;
}

export interface ImportIssue {
  level: string;
  code: string;
  message: string;
  trade_number: number | null;
  row_number: number | null;
}

export interface RejectedStrategyTrade {
  trade_number: number | null;
  issue_count: number;
  issues: ImportIssue[];
  issues_truncated: boolean;
  raw_row_count: number;
  raw_rows: RawCsvRow[];
  raw_rows_truncated: boolean;
}

export interface ParsedStrategyTradePreview {
  trade_number: number;
  direction: StrategyTradeDirection;
  entry_at: string;
  exit_at: string;
  entry_at_raw: string;
  exit_at_raw: string;
  entry_price: DecimalString;
  exit_price: DecimalString;
  quantity: DecimalString;
  net_pnl: DecimalString | null;
  return_pct: DecimalString | null;
  mfe: DecimalString | null;
  mfe_pct: DecimalString | null;
  mae: DecimalString | null;
  mae_pct: DecimalString | null;
  cumulative_pnl: DecimalString | null;
  cumulative_return_pct: DecimalString | null;
  duration_bars: number | null;
  duration_minutes: number;
  entry_signal: string | null;
  exit_signal: string | null;
  entry_comment: string | null;
  exit_comment: string | null;
  feature_snapshot: Record<string, unknown>;
  raw_entry_row: RawCsvRow;
  raw_exit_row: RawCsvRow;
  warning_count: number;
  warnings: ImportIssue[];
  warnings_truncated: boolean;
}

export interface ImportVersionContext {
  id: string;
  version_label: string;
  source_fingerprint: string;
  hypothesis: string | null;
  parameters: StrategyParameters;
  execution_timing: ExecutionTiming;
  session_mode: SessionMode;
  commission_type: CommissionType;
  commission_value: DecimalString | null;
  slippage_type: SlippageType;
  slippage_value: DecimalString | null;
  pyramiding: number;
}

export interface StrategyRunImportPreview {
  source_file_name: string | null;
  source_sha256: string;
  source_timezone: string;
  preview_fingerprint: string;
  encoding: string;
  headers: string[];
  mapping: Record<string, string>;
  source_row_count: number;
  accepted_row_count: number;
  skipped_row_count: number;
  rejected_row_count: number;
  accepted_trade_count: number;
  rejected_trade_count: number;
  warning_count: number;
  warnings: ImportIssue[];
  warnings_truncated: boolean;
  rejected_trades: RejectedStrategyTrade[];
  rejected_trades_truncated: boolean;
  trades: ParsedStrategyTradePreview[];
  preview_truncated: boolean;
  observed_start_at: string | null;
  observed_end_at: string | null;
  duplicate_run_id: string | null;
  can_commit: boolean;
  version: ImportVersionContext;
}

export interface StrategyRunImportMetadata {
  strategy_version_id: string;
  expected_version_fingerprint: string;
  expected_source_sha256: string;
  expected_preview_fingerprint: string;
  symbol: string;
  timeframe: string;
  source_timezone: string;
  backtest_start?: string | null;
  backtest_end?: string | null;
  initial_capital?: DecimalString | null;
  currency?: string;
  extended_hours?: boolean;
  notes?: string | null;
}

export interface StrategyRunImportResult {
  run_id: string;
  strategy_version_id: string;
  version_fingerprint: string;
  source_sha256: string;
  source_file_name: string | null;
  imported_trade_count: number;
  imported_row_count: number;
  skipped_row_count: number;
  rejected_row_count: number;
  warning_count: number;
  metrics_status: "pending";
}

export interface StrategyRunSummary {
  id: string;
  strategy_definition_id: string;
  strategy_name: string;
  setup_type: string;
  strategy_version_id: string;
  version_label: string;
  version_status: StrategyVersionStatus;
  symbol: string;
  timeframe: string;
  source_timezone: string;
  backtest_start: string | null;
  backtest_end: string | null;
  observed_start_at: string | null;
  observed_end_at: string | null;
  currency: string;
  source_file_name: string | null;
  imported_at: string;
  trade_count: number;
  metrics_status: StrategyRunMetricsStatus;
  metrics_calculated_at: string | null;
  total_net_pnl: DecimalString | null;
  net_return_pct: DecimalString | null;
  expectancy: DecimalString | null;
  max_drawdown_pct: DecimalString | null;
  win_rate: DecimalString | null;
}

export interface StrategyRunDetail extends StrategyRunSummary {
  version_hypothesis: string | null;
  version_change_summary: string | null;
  version_fingerprint: string;
  source: string;
  initial_capital: DecimalString | null;
  parameters: StrategyParameters;
  commission_type: CommissionType;
  commission_value: DecimalString | null;
  slippage_type: SlippageType;
  slippage_value: DecimalString | null;
  execution_timing: ExecutionTiming;
  session_mode: SessionMode;
  extended_hours: boolean;
  pyramiding: number;
  notes: string | null;
  source_sha256: string | null;
  source_warning_count: number;
  created_at: string;
}

export interface StrategyRunTrade {
  id: string;
  run_id: string;
  trade_number: number;
  direction: StrategyTradeDirection;
  entry_at: string | null;
  exit_at: string | null;
  entry_at_raw: string | null;
  exit_at_raw: string | null;
  entry_price: DecimalString | null;
  exit_price: DecimalString | null;
  quantity: DecimalString | null;
  net_pnl: DecimalString | null;
  return_pct: DecimalString | null;
  mfe: DecimalString | null;
  mfe_pct: DecimalString | null;
  mae: DecimalString | null;
  mae_pct: DecimalString | null;
  cumulative_pnl: DecimalString | null;
  cumulative_return_pct: DecimalString | null;
  duration_bars: number | null;
  duration_minutes: number | null;
  entry_signal: string | null;
  exit_signal: string | null;
  created_at: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export type StrategyRunList = PaginatedResponse<StrategyRunSummary>;
export type StrategyRunTradeList = PaginatedResponse<StrategyRunTrade>;

export interface StrategyRunListFilters {
  strategyId?: string;
  versionId?: string;
  limit?: number;
  offset?: number;
}

export interface StrategyRunTradeFilters {
  direction?: StrategyTradeDirection;
  outcome?: StrategyTradeOutcome;
  entryDateFrom?: string;
  entryDateTo?: string;
  limit?: number;
  offset?: number;
}

export interface StrategyMetricBreakdown {
  trade_count: number;
  pnl_covered_count: number;
  pnl_missing_count: number;
  return_pct_covered_count: number;
  wins: number;
  losses: number;
  breakeven: number;
  win_rate: DecimalString | null;
  average_winner: DecimalString | null;
  average_loser: DecimalString | null;
  payoff_ratio: DecimalString | null;
  total_pnl: DecimalString | null;
  expectancy: DecimalString | null;
  profit_factor: DecimalString | null;
  average_return_pct: DecimalString | null;
}

export interface MetricFieldCoverage {
  available: number;
  missing: number;
  invalid?: number;
  chronologically_usable?: number;
}

export interface StrategyMetricsCoverage {
  schema_version: number;
  total_trades: number;
  fields: Record<string, MetricFieldCoverage>;
  outcomes: {
    wins: number;
    losses: number;
    breakeven: number;
  };
  denominators: Record<string, number | DecimalString | null>;
  initial_capital: {
    value: DecimalString | null;
    usable_for_percent: boolean;
  };
  accounting_complete: boolean;
  chronology_complete: boolean;
  net_return_basis: string;
  net_return_fallback_trade_number: number | null;
  max_drawdown_basis: string;
  max_drawdown_pct_basis: string;
  top_profit_contribution_basis: string;
  source_timezone: string;
  equity_order: string[];
  undefined_metrics: Record<string, string>;
}

export interface StrategyEquityPoint {
  sequence: number;
  trade_number: number | null;
  exit_at: string | null;
  net_pnl: DecimalString | null;
  cumulative_net_pnl: DecimalString;
  equity: DecimalString;
}

export interface StrategyDrawdownPoint {
  sequence: number;
  trade_number: number | null;
  exit_at: string | null;
  peak_equity: DecimalString;
  drawdown: DecimalString;
  drawdown_pct: DecimalString | null;
}

export interface StrategyRunMetrics {
  run_id: string;
  calculation_version: string;
  calculated_at: string;
  trade_count: number;
  winning_trades: number;
  losing_trades: number;
  // This is the one Strategy Lab percentage represented as a 0..1 ratio.
  win_rate: DecimalString | null;
  average_winner: DecimalString | null;
  average_loser: DecimalString | null;
  payoff_ratio: DecimalString | null;
  expectancy: DecimalString | null;
  profit_factor: DecimalString | null;
  total_net_pnl: DecimalString | null;
  // All remaining *_pct fields are percentage points (4.25 means 4.25%).
  net_return_pct: DecimalString | null;
  max_drawdown: DecimalString | null;
  max_drawdown_pct: DecimalString | null;
  average_mfe: DecimalString | null;
  median_mfe: DecimalString | null;
  average_mae: DecimalString | null;
  median_mae: DecimalString | null;
  average_holding_minutes: DecimalString | null;
  top_1_profit_contribution_pct: DecimalString | null;
  top_3_profit_contribution_pct: DecimalString | null;
  top_5_profit_contribution_pct: DecimalString | null;
  long_summary: StrategyMetricBreakdown;
  short_summary: StrategyMetricBreakdown;
  time_bucket_summary: Record<string, StrategyMetricBreakdown>;
  coverage: StrategyMetricsCoverage;
  equity_curve: StrategyEquityPoint[];
  drawdown_curve: StrategyDrawdownPoint[];
  findings: unknown[];
}

export interface PreviewStrategyRunImportInput {
  strategyVersionId: string;
  sourceTimezone: string;
  file: File;
}

export interface CommitStrategyRunImportInput {
  metadata: StrategyRunImportMetadata;
  file: File;
}
