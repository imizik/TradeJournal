import { apiUrl } from "./api";

export type PlanState = "pending_activation" | "watching" | "triggered" | "invalidated" | "expired" | "cancelled" | "unavailable";
export type PlanBar = { time: number; end_time: number; open: number; high: number; low: number; close: number };
/** One recorded push result. "sent" means ntfy accepted it, never that the phone showed it. */
export type PlanDelivery = { event_state: PlanState | null; attempt: number; result: string; outcome: "sent" | "failed" | "unknown" | "not_sent";
  error_code: string | null; transport_receipt_id: string | null; occurred_at: string };
export type PlanView = {
  plan_id: string; actor: string; session_date: string; symbol: string; direction: "long" | "short";
  trigger_price: number; invalidation_price: number; confirm_bars: number; rationale: string;
  source: { kind: "check" | "stock_alert"; id: string; sha256: string; observed_at: string; price: number };
  expires_at: string; created_at: string; accepted_by_monitor: boolean; cancel_requested: boolean;
  state: PlanState; reason: string | null; state_at: string | null; monitoring: boolean; heartbeat_at: string | null;
  last_bar: (PlanBar & { consecutive: number }) | null; last_evaluated_at: string | null;
  events: { state: PlanState; reason: string; occurred_at: string; bar: PlanBar | null }[];
  deliveries: PlanDelivery[];
};
/** A watch Jo asked for that the app refused: nothing was saved or watched. Levels are what Jo sent. */
export type PlanRefusal = { refusal_id: string; actor: string; session_date: string; symbol: string | null; source_kind: "check" | "stock_alert" | null;
  direction: "long" | "short" | null; trigger_price: number | null; invalidation_price: number | null; confirm_bars: number | null;
  expires_at: string | null; reason: string; reason_code: "ticker_not_selected" | "monitor_off" | "no_session" | "daily_cap" | "other"; created_at: string };
/** Plain words for why a watch was refused, or Jo's raw refusal reason. */
export function refusalWords(r: PlanRefusal, max = 24) {
  const words = { ticker_not_selected: "not one of your scanner tickers", monitor_off: "the price-watch monitor wasn't running",
    no_session: "the market wasn't open", daily_cap: `today's ${max}-watch limit was reached`, other: "" }[r.reason_code];
  return words || r.reason.replace(/^./, (c) => c.toLowerCase());
}
/** "2 closes above 252, cancel below 245": the rule Jo asked for, as far as it was sent. */
export function refusalRule(r: PlanRefusal) {
  if (!r.direction || r.trigger_price == null) return null;
  const [above, below] = r.direction === "long" ? ["above", "below"] : ["below", "above"];
  return `${r.direction} · ${r.confirm_bars ?? "?"} ${r.confirm_bars === 1 ? "close" : "closes"} ${above} ${r.trigger_price}${r.invalidation_price != null ? `, cancel on a close ${below} ${r.invalidation_price}` : ""}`;
}
export type PlanReadiness = { heartbeat: "fresh" | "stale" | "missing" | "unreadable"; heartbeat_at?: string; monitor_enabled?: boolean;
  session_date?: string; session_open_at?: string | null; session_close_at?: string | null; session_open_now?: boolean;
  symbols?: string[]; selection_revision?: number };
export type PlansView = {
  checked_at: string; enabled: boolean; app_flag: boolean; stock_watch: boolean; configured: boolean;
  readiness: PlanReadiness; max_daily_plans: number; plans_today?: number; limit: number;
  delivery: { channel: string; configured: boolean }; plans: PlanView[];
  /** Absent from servers older than refusal receipts. */
  refusals?: PlanRefusal[];
};

export async function getPlans(signal?: AbortSignal): Promise<PlansView> {
  const response = await fetch(apiUrl("/jo/conditional-plans"), { cache: "no-store", signal });
  if (!response.ok) throw new Error("Price watches could not load. Monitoring status is unknown.");
  return response.json();
}
