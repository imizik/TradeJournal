import { apiUrl } from "@/lib/api";

export type ReplayChoice = { decision: "hold" | "reduce" | "exit"; rationale: string | null; received_at: string };
export type ReplayCheckpoint = {
  id: "first-look" | "later-look";
  input_cutoff: string;
  decision_received_at: string | null;
  evidence_status: string;
  position: { contracts: number; entry_premium_per_contract: number | null; checkpoint_mark_per_contract: number | null; open_return_pct: number | null; peak_open_return_pct: number | null; mark_time: string | null; mark_source: string | null; mark_type: string | null; mark_observed_at: string | null; mark_published_at: string | null; mark_retrieved_at: string | null; option_contract: { right: string; strike: number; expiry: string; dte_at_entry: number }; entry_time: string | null; peak_mark_time: string | null; historical_bid_ask: string; greeks: string; news: string };
  original_plan: { source: string; state: string; text: string | null; captured_at: string | null };
  bars: { interval_start: string; interval_end: string; open: number; high: number; low: number; close: number; volume: number; observed_at: string; published_at: string; retrieved_at: string; source: string; price_basis: string }[];
  chart_context: import("@/lib/api").DecisionContext;
};
export type ReplayReveal = {
  checkpoint_id: string; choice: ReplayChoice; original_plan: ReplayCheckpoint["original_plan"]; checkpoint: ReplayCheckpoint;
  actual_action: { decision: string; contracts: number; at?: string; fill?: { price_per_contract: number; filled_at: string; source?: string; execution_status?: string } };
  continuation: { interval_start: string; interval_end: string; open: number; high: number; low: number; close: number; volume: number; observed_at: string; published_at: string; retrieved_at: string; source: string; price_basis: string }[];
  final_outcome?: { closed: boolean; actual_synthetic_fills: { contracts: number; price_per_contract: number; filled_at: string }[]; pnl: { value: number; unit: string; status: string }; later_retrospective_rationale: { status: string; reason: string } } | null;
};
export type ReplayAttempt = {
  attempt_id: string;
  operation_id: string;
  scenario_id: string;
  repeated: boolean;
  phase: "decision" | "complete";
  checkpoint: ReplayCheckpoint | null;
  choice: ReplayChoice | null;
  revealed: ReplayReveal[];
};
export type ReplayScenario = { id: string; title: string; symbol: string; instrument: string; description: string; checkpoint_count: number; repeat_status?: "new" | "repeat"; latest_attempt_id?: string | null; option_contract?: ReplayCheckpoint["position"]["option_contract"] };

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(apiUrl(path), { cache: "no-store", method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : `Replay request failed (${response.status}).`);
  return payload as T;
}

export const listReplayScenarios = () => request<{ scenarios: ReplayScenario[] }>("/practice/replay/scenarios");
export const getReplayAttempt = (id: string) => request<ReplayAttempt>(`/practice/replay/attempts/${encodeURIComponent(id)}`);
export const startReplayAttempt = (operationId: string) => request<ReplayAttempt>("/practice/replay/attempts", { operation_id: operationId });
export const saveReplayChoice = (id: string, checkpointId: string, decision: ReplayChoice["decision"], rationale: string) =>
  request<ReplayAttempt>(`/practice/replay/attempts/${encodeURIComponent(id)}/choice`, { checkpoint_id: checkpointId, decision, rationale: rationale.trim() || null });
export const revealReplayCheckpoint = (id: string, checkpointId: string) =>
  request<ReplayAttempt>(`/practice/replay/attempts/${encodeURIComponent(id)}/reveal`, { checkpoint_id: checkpointId });
