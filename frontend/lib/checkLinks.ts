import { apiUrl } from "./api";

// Saved-advice links (Dots step 5): the journal's side. The check itself comes from the check owner reader.
export type CheckFacts = { ticker?: string | null; received_at?: string | null; instrument?: string | null;
  option_type?: string | null; strike?: number | string | null; expiration?: string | null };
export type ActivityFill = { fill_id: string; role: string; side: string; contracts: number; price: number; executed_at: number | null };
export type ActivityTrade = { trade_id: string; account: string | null; account_type: string | null; contract: string; status: string;
  contracts: number; opened_at: number | null; closed_at: number | null; realized_pnl: number | null;
  timing: "after" | "same_minute" | "same_day" | null; fills: ActivityFill[] };
export type LinkedActivity = { link_id: string; target: "trade" | "fill"; method: string; linked_at: number;
  trade: ActivityTrade | null; fill_id: string | null; note?: string };
export type Activity = { check_id: string; window: { from: number; to: number; days: number }; linked: LinkedActivity[];
  possible: ActivityTrade[]; history: { link_id: string; target: string; linked_at: number; unlinked_at: number | null }[] };
export type TradeCheckLink = { link_id: string; check_id: string; target: "trade" | "fill"; method: string; linked_at: number; fill_id: string | null };

function factsOf(facts: CheckFacts): Record<string, string> {
  return Object.fromEntries(Object.entries(facts).filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([key, value]) => [key, String(value)]));
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(apiUrl(path), { cache: "no-store", ...init });
  } catch {
    throw new Error("The journal could not be reached.");
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof data?.detail === "string" ? data.detail : `The journal answered ${response.status}.`);
  return data as T;
}

const post = (body: object): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const fetchActivity = (checkId: string, facts: CheckFacts) =>
  call<Activity>(`/jo/check-links/${checkId}/activity?${new URLSearchParams(factsOf(facts))}`);
export const linkActivity = (checkId: string, facts: CheckFacts, target: { trade_id: string } | { fill_id: string }) =>
  call<Activity>(`/jo/check-links/${checkId}/link`, post({ ...factsOf(facts), ...target }));
export const unlinkActivity = (checkId: string, facts: CheckFacts, linkId: string) =>
  call<Activity>(`/jo/check-links/${checkId}/links/${linkId}/unlink`, post(factsOf(facts)));
export const fetchTradeCheckLinks = (tradeId: string) => call<{ links: TradeCheckLink[] }>(`/jo/check-links/for-trade/${tradeId}`);
