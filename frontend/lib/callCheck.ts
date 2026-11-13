/** Check a call (docs/copilot-lab.md § Check a call): a Discord trade call checked by the copilot, kept with the price at
 * the check. Read and written through ``/copilot/checks`` (backend ``routers/copilot_checks.py``). */
import { apiUrl } from "./api";
import { CONTEXT_MAX, copilotLabHref } from "./copilot";

export type CallReading = {
  ticker: string | null; expiry: string | null; strike: number | null; side: "call" | "put" | null;
  entry: number | null; stop: number | null; target: number | null;
};
export type CallCard = { headline: string | null; tiles: [string, string][]; against: string | null; changes_if: string | null;
  others: string[]; note: string | null };
export type CheckedCall = {
  id: string; checked_at: string; day: string; source: "desk" | "telegram"; raw: string; symbol: string | null;
  reading: CallReading; verdict: "Pass" | "Wait" | "Draft" | null; card: CallCard; underlying_price: number | null;
  outcome: "passed" | null; outcome_at: string | null; planned: boolean; plan_href: string | null;
};

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), { cache: "no-store", ...init, headers: init?.body ? { "Content-Type": "application/json" } : undefined });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${response.status}).`);
  return body as T;
}

export const checkCall = (text: string) => call<CheckedCall>("/copilot/checks", { method: "POST", body: JSON.stringify({ text }) });
export const checkedToday = async (signal?: AbortSignal) => (await call<{ day: string; checks: CheckedCall[] }>("/copilot/checks", { signal })).checks;
export const passCall = (id: string) => call<CheckedCall>(`/copilot/checks/${encodeURIComponent(id)}/pass`, { method: "POST" });

export const LEVELS = ["entry", "stop", "target"] as const;
export type Level = (typeof LEVELS)[number];
export const FIELD_LABEL: Record<keyof CallReading, string> = {
  ticker: "Ticker", expiry: "Expiry", strike: "Strike", side: "Call or put", entry: "Entry price", stop: "Stop", target: "Target" };

const num = (value: number) => String(Number(value.toFixed(2)));
/** "11/27", or "11/11 (0DTE)" on the day it was checked. */
export function expiryWords(iso: string | null, day?: string): string | null {
  if (!iso) return null;
  const [, m, d] = iso.split("-").map(Number);
  return iso === day ? `${m}/${d} (0DTE)` : `${m}/${d}`;
}
export function fieldText(check: CheckedCall, key: keyof CallReading): string | null {
  const value = check.reading[key];
  if (value == null) return null;
  if (key === "expiry") return expiryWords(value as string, check.day);
  return typeof value === "number" ? num(value) : String(value);
}
/** "QQQ 660 put 11/11 (0DTE)": the contract as far as it was read. */
export const contractWords = (check: CheckedCall) =>
  [check.reading.ticker, check.reading.strike != null && num(check.reading.strike), check.reading.side, expiryWords(check.reading.expiry, check.day)]
    .filter(Boolean).join(" ");

/** The plan flow for the call's symbol (``call_check.plan_href``): the poster's levels and any blank he set, as editable
 * text in the message box, with the check as the plan's origin. A plan, never a ticket. */
export function planHref(check: CheckedCall, mine: Partial<Record<Level, string>> = {}): string | null {
  if (!check.symbol) return null;
  const posted = LEVELS.flatMap(k => check.reading[k] != null ? [`posted ${k} ${num(check.reading[k] as number)}`] : []);
  const set = LEVELS.flatMap(k => check.reading[k] == null && mine[k]?.trim() ? [`my ${k} ${mine[k]!.trim()}`] : []);
  const levels = [...posted, ...set].join("; ");
  const context = `Plan a trade: ${contractWords(check)}, from a Discord call I checked${levels ? ` (${levels})` : ""}. My own entry trigger, invalidation, target and time stop:`;
  return copilotLabHref(check.symbol, context.replace(/\s+/g, " ").slice(0, CONTEXT_MAX), { kind: "checked_call", ref: check.id });
}
