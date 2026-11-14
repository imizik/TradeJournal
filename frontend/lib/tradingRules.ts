/**
 * His own trading rules (backend ``app/engine/trading_rules.py``, docs/copilot-lab.md § My rules): the list, an entry's
 * checklist, a copied real order's checklist, and the followed-versus-broken split. A broken rule never blocks an order.
 */

import { apiUrl } from "@/lib/api";
import { PAPER_EVENT } from "@/lib/paperBook";

export type RuleKind = "max_size_pct" | "stop_set" | "no_open_minutes" | "max_open" | "min_dte";
export type Rule = { id: string; text: string; check: { kind: RuleKind; n?: number } | null };
/** pass · fail (broken) · na (does not apply) · unknown (can't check, with why) · ask (a tick-box not answered yet). */
export type RuleStatus = "pass" | "fail" | "na" | "unknown" | "ask";
export type RuleResult = { id: string; text: string; kind: RuleKind | "tick"; n: number | null; status: RuleStatus; reason: string };
export type RuleOutcome = "followed" | "broken" | "unclear";
type Group = { trades: number; pnl: number; win_rate: number | null };
export type RulesSplit = {
  followed: Group; broken: Group; unclear: Group; unrecorded: number;
  by_rule: { id: string; text: string; current: boolean; followed: Group; broken: Group; unchecked: number }[];
  /** Real only: copied checklists, matched to a closed trade through the plan's link, still open, unmatched. */
  checklists?: number; matched?: number; open?: number; unmatched?: number;
};
/** What a checklist checks: ``size`` is the most the entry can lose, in dollars. */
export type RuleEntry = { side: "paper" | "real"; instrument: "stock" | "option" | "spread"; expiry?: string | null; size?: number | null; stop?: number | null; last4?: string | null };

export const MAX_RULES = 8;
export const CHECK_WORDS: Record<RuleKind, { words: string; n: boolean; unit?: string }> = {
  max_size_pct: { words: "Size at most N% of the account", n: true, unit: "%" },
  stop_set: { words: "Stop set before entry", n: false },
  no_open_minutes: { words: "No entry in the first N minutes", n: true, unit: "min" },
  max_open: { words: "At most N open positions", n: true },
  min_dte: { words: "Option at least N days to expiry", n: true, unit: "days" },
};

async function send<T>(path: string, method: "POST" | "PUT", body: object): Promise<T> {
  const response = await fetch(apiUrl(path), { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const reply = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof reply?.detail === "string" ? reply.detail : `Request failed (${response.status}).`);
  return reply as T;
}

export async function saveRules(rules: Omit<Rule, "id">[] | Rule[]): Promise<Rule[]> {
  const reply = await send<{ rules: Rule[] }>("/copilot/rules", "PUT", { rules });
  window.dispatchEvent(new Event(PAPER_EVENT));  // the paper read carries the list and the split
  return reply.rules;
}
export function checkEntry(entry: RuleEntry, signal?: AbortSignal): Promise<{ rules: Rule[]; results: RuleResult[] }> {
  return fetch(apiUrl("/copilot/rules/check"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(entry), signal })
    .then(async r => { const body = await r.json().catch(() => null); if (!r.ok || !body) throw new Error(String(r.status)); return body; });
}
export function recordTicket(body: RuleEntry & { investigation_id: string; order_key: string; symbol: string; answers: Record<string, boolean> }) {
  return send<{ recorded: boolean; outcome?: RuleOutcome }>("/copilot/rules/ticket", "POST", body);
}

/** A tick-box he answered: ticked passes, left unticked is broken; an automatic result is the server's. */
export function answered(results: RuleResult[], ticked: Record<string, boolean>): RuleResult[] {
  return results.map(r => r.kind !== "tick" ? r : ticked[r.id] ? { ...r, status: "pass", reason: "You ticked it." } : { ...r, status: "fail", reason: "Not ticked." });
}
export function brokenCount(results: RuleResult[]) {
  return results.filter(r => r.status === "fail").length;
}
