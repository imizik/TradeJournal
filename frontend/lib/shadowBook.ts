import { apiUrl } from "./api";

export type ShadowLevel = { condition: string; price: number; interval: string | null };
export type ShadowPlan = {
  symbol: string; direction: "long" | "short"; instrument: "stock" | "calls" | "puts"; contract: string | null;
  entry_trigger: ShadowLevel; invalidation: ShadowLevel; target: number; time_stop: string; thesis: string; unit: string;
};
export type ShadowDecision = {
  id: string; radar_event_id: string; session_date: string;
  event: { kind: string; direction: "up" | "down"; symbols: string[]; first_seen_at: string; summary: string };
  decision: "deciding" | "plan" | "skip" | "error" | "not_decided" | "filtered";
  status: "deciding" | "skip" | "error" | "not_decided" | "filtered" | "pending_entry" | "open" | "exiting" | "exit" | "unresolved";
  reason: string | null; plan: ShadowPlan | null; model: string | null; decided_at: string | null;
  entry: { price: number; at: string; shares: number | null } | null;
  exit: { price: number; at: string; reason: string } | null;
  result: { pnl: number; return_pct: number | null } | null;
  unresolved: string | null;
};
export type ShadowWeek = {
  enabled: boolean; max_turns: number; week: { start: string; end: string };
  summary: {
    shadow: { decisions: number; turns: number; filtered: number; plans: number; closed: number; pnl_usd: number };
    owner: { state: "ok"; trades: number; pnl_usd: number } | { state: "unavailable" };
    note: string;
  };
  decisions: ShadowDecision[];
};

export async function getShadowWeek(week?: string, signal?: AbortSignal): Promise<ShadowWeek> {
  const response = await fetch(apiUrl(`/radar/shadow-book${week ? `?week=${encodeURIComponent(week)}` : ""}`), { cache: "no-store", signal });
  if (!response.ok) throw new Error("The shadow book could not be reached.");
  return response.json();
}

export const money = (value: number) => `${value < 0 ? "−" : "+"}$${Math.abs(value).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const EXIT_TEXT: Record<string, string> = {
  invalidation: "invalidation", target: "target", time_stop: "time stop", last_minute: "session's last minute",
};
export const exitText = (reason: string) => EXIT_TEXT[reason] ?? reason;

/** "Long NBIS calls 2026-10-24 120 call" / "Short AAPL stock". */
export const planTitle = (plan: ShadowPlan) =>
  `${plan.direction === "long" ? "Long" : "Short"} ${plan.symbol} ${plan.instrument === "stock" ? "stock" : plan.contract ?? plan.instrument}`;

/** Monday of the week holding ``day`` (YYYY-MM-DD), shifted by ``weeks``. */
export function weekShift(day: string, weeks: number): string {
  const d = new Date(`${day}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + 7 * weeks);
  return d.toISOString().slice(0, 10);
}
