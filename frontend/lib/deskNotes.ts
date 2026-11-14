/**
 * His one-line notes on a trade from the desk ("why I'm in", "why I left"): ``GET``/``POST /copilot/desk/notes``
 * (backend/app/engine/trade_notes.py). Saved with the trade, on its plan when it has one; never a plan, and never a
 * change to a fill, a trade or its P&L.
 */

import { apiUrl } from "@/lib/api";
import type { DeskOrder, DeskThread } from "@/lib/desk";

export type DeskNote = { id: string; text: string; at: number | null };
/** ``trades``: each trade's notes, oldest first. ``fills``: each asked fill line's journal trade, or null while the
 * journal does not have its fill yet. */
export type DeskNotes = { trades: Record<string, DeskNote[]>; fills: Record<string, string | null> };
export type NoteTarget = { trade_id: string } | { symbol: string; contract: string };

export const NOTE_MAX = 300;

/** A book row's journal trade: ``trade:<id>`` rows are the journal's; a Robinhood-only row has none yet. */
export const rowTrade = (row: DeskThread): string | null => row.tradeId ?? (row.key.startsWith("trade:") ? row.key.slice(6) : null);
/** A fill line's key: its ticker, contract label and masked account, as the line shows them (the same contract in
 * another account is another trade). */
export const fillKey = (order: Pick<DeskOrder, "symbol" | "contract" | "account">) => `${order.symbol}|${order.contract}|${order.account.masked}`;

export async function getDeskNotes(trades: string[], fills: string[], signal?: AbortSignal): Promise<DeskNotes> {
  const query = new URLSearchParams();
  trades.forEach(id => query.append("trade", id));
  fills.forEach(key => query.append("fill", key));
  const response = await fetch(apiUrl(`/copilot/desk/notes?${query}`), { cache: "no-store", signal });
  if (!response.ok) throw new Error(`Request failed (${response.status}).`);
  return await response.json() as DeskNotes;
}

export async function addDeskNote(target: NoteTarget, text: string): Promise<{ trade_id: string; note: DeskNote }> {
  const response = await fetch(apiUrl("/copilot/desk/notes"), {
    method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...target, text }),
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof body?.detail === "string" ? body.detail : "Not saved. Try again.");
  return body as { trade_id: string; note: DeskNote };
}
