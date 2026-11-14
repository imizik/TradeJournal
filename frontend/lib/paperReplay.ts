/**
 * Paper trading on a past day (backend ``app/engine/paper_replay.py``, docs/copilot-lab.md § Paper replay): the day's
 * minute bars, the replay clock and the replay run's orders. Every order names the replay moment; the server prices it
 * only from bars that ended by then. Paper only: nothing here places an order anywhere.
 */

import { apiUrl } from "@/lib/api";
import { PaperRefused, type PaperPosition, type PaperStats, type PaperWorkingOrder } from "@/lib/paperBook";

export const REPLAY_EVENT = "tradejournal:replay-changed";
export const SPEEDS = [1, 5, 20, 60] as const;
export type Speed = (typeof SPEEDS)[number];

export type ReplayBar = { time: number; open: number; high: number; low: number; close: number; volume: number };
export type ReplayDay = { date: string; open_at: number; close_at: number; early_close: boolean };
export type ReplayRunInfo = {
  id: string; day: string; starting_cash: number; started_at: number; open_at: number | null; close_at: number | null;
  symbols: string[]; realized: number; trades: number; left_open: number;
};
/** A closed replay trade: the paper position with the day replayed. ``verdict.kind`` adds flat (sold at the replayed
 *  close) and left (sold when he left the replay). */
export type ReplayTrade = Omit<PaperPosition, "verdict"> & { day: string; run_id: string; verdict?: { kind: string; text: string; auto?: boolean } };
export type ReplayScore = { score: PaperStats; runs: ReplayRunInfo[]; trades: ReplayTrade[] };
export type ReplayHome = ReplayScore & { days?: ReplayDay[]; spread_bps: number; options: string };
/** What the bars did while the clock ran: a limit filled, an automatic exit at the stop or target, a level touched with
 *  the switch off, or everything sold at the close (flat) or on leaving (left). */
export type ReplayHappening = {
  kind: "limit" | "stop" | "target" | "touch" | "flat" | "left"; symbol: string; label: string; at: number; price: number;
  side?: "open" | "close"; quantity?: number; pnl?: number; level?: "stop" | "target"; limit?: number;
};
export type ReplayView = {
  run: ReplayRunInfo; at: number; ended: boolean; score: PaperStats;
  account: { cash: number; collateral: number; reserved: number; buying_power: number; equity: number | null; pnl: number | null };
  positions: PaperPosition[]; orders: PaperWorkingOrder[]; closed: ReplayTrade[]; happened?: ReplayHappening[];
};
/** The confirm: the bar's close, the assumed half-spread and the price either side of it. */
export type ReplayQuote = {
  label: string; quantity: number; close: number; half_spread: number; bid: number; ask: number; bar: number; spread_bps: number;
  buying_power: number; buying_power_after?: number; fills_now: boolean; per_share?: number; cash?: number; pnl?: number;
  limit?: number; reserve?: number; expires_at?: number;
};
export type ReplayOrderReply = ReplayView & { filled: (ReplayQuote & { at: number }) | null; working: (ReplayQuote & { id: string }) | null; duplicate?: boolean };

async function call<T>(path: string, body?: object, signal?: AbortSignal): Promise<T> {
  const response = await fetch(apiUrl(path), body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal }
    : { cache: "no-store", signal });
  const reply = await response.json().catch(() => null);
  if (!response.ok) throw new PaperRefused(typeof reply?.detail === "string" ? reply.detail : `Request failed (${response.status}).`, response.status);
  return reply as T;
}

const changed = () => window.dispatchEvent(new Event(REPLAY_EVENT));

export const replayHome = (days: boolean, signal?: AbortSignal) => call<ReplayHome>(`/copilot/paper/replay${days ? "?with_days=true" : ""}`, undefined, signal);
export const replaySymbols = (day: string, signal?: AbortSignal) =>
  call<{ day: string; symbols: { symbol: string; why: "traded" | "watched" }[] }>(`/copilot/paper/replay/day?${new URLSearchParams({ day })}`, undefined, signal);
export const replayBars = (day: string, symbol: string, signal?: AbortSignal) =>
  call<{ symbol: string; day: string; open_at: number; close_at: number; bars: ReplayBar[] }>(`/copilot/paper/replay/bars?${new URLSearchParams({ day, symbol })}`, undefined, signal);
export async function startReplay(day: string) {
  const view = await call<ReplayView>("/copilot/paper/replay/runs", { day });
  changed();
  return view;
}
export async function stepReplay(runId: string, at: number, end = false) {
  const view = await call<ReplayView>("/copilot/paper/replay/step", { run_id: runId, at, end });
  if (end || view.ended || view.happened?.length) changed();
  return view;
}
export type ReplayAsk = {
  action: "open" | "close"; order_type: "market" | "limit"; limit_price?: number | null; quantity?: number | null;
  symbol?: string; instrument?: "stock"; position_id?: string; note?: string | null; stop?: number | null; target?: number | null; auto?: boolean;
};
export const previewReplay = (runId: string, at: number, ask: ReplayAsk) =>
  call<{ preview: ReplayQuote }>("/copilot/paper/replay/orders", { run_id: runId, at, preview: true, ...ask }).then(r => r.preview);
export async function orderReplay(runId: string, at: number, ask: ReplayAsk, key: string) {
  const reply = await call<ReplayOrderReply>("/copilot/paper/replay/orders", { run_id: runId, at, ...ask, order_key: key });
  changed();
  return reply;
}
export const cancelReplay = (runId: string, at: number, orderId: string) =>
  call<ReplayView>("/copilot/paper/replay/orders/cancel", { run_id: runId, at, order_id: orderId });
export const autoReplay = (runId: string, at: number, positionId: string, on: boolean, key: string) =>
  call<ReplayView>("/copilot/paper/replay/auto", { run_id: runId, at, position_id: positionId, on, order_key: key });

/** The bars shown at the replay clock: only those that ended by it. A bar still forming, and everything after, is the
 *  future and never drawn. */
export const shownBars = (bars: ReplayBar[], at: number) => bars.filter(b => b.time + 60 <= at);

/** Real milliseconds per replayed minute at a speed: 1× is real time, 60× one bar a second. */
export const msPerBar = (speed: Speed) => 60_000 / speed;

const ET = "America/New_York";
export const replayTime = (epoch: number) => new Date(epoch * 1000).toLocaleTimeString("en-US", { timeZone: ET, hour: "numeric", minute: "2-digit" });
export const replayDate = (iso: string) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", weekday: "short", month: "short", day: "numeric" });
/** "REPLAY · Thu Nov 13 · 10:42 AM ET": on every replay screen, so it is never taken for live. */
export const replayBadge = (day: string, at: number) => `REPLAY · ${replayDate(day)} · ${replayTime(at)} ET`;
