/**
 * The Copilot desk (`/copilot-lab`): shapes shared by the desk shell and the pieces that fill it.
 * The shell (`components/copilot/CopilotLab.tsx`) owns the layout and these hand-offs; the thread list, decision
 * bar, inspector and palette build against the types below. See docs/copilot-lab.md#the-desk.
 */

import type { PlanPosition } from "@/components/dashboard/PlansCard";
import { apiUrl } from "@/lib/api";
import type { PlanBoardRow, PlansBoard } from "@/lib/copilot";

/** The phone's three tabs; on a wide screen every pane shows at once. */
export type DeskTab = "now" | "thread" | "context";

/** What the desk asks the conversation to do: open a saved investigation, or send one prompt across everything. */
export type DeskCommand = { kind: "open"; id: string; n: number } | { kind: "ask"; text: string; n: number };

/** The conversation's open investigation, reported up so the inspector can show its context. */
export type DeskThreadRef = { id: string; symbol: string | null; title: string; refreshKey: number };

/** How the conversation and the desk talk: commands down, the open thread up. */
export type DeskHooks = { command: DeskCommand | null; onThread(thread: DeskThreadRef | null): void };

/** The thread list's groups, in order: what needs a decision first, what is only being watched last. */
export type DeskGroup = "pinned" | "act" | "near" | "draft" | "new" | "watch";

export const DESK_GROUPS: { id: DeskGroup; title: string }[] = [
  { id: "pinned", title: "Pinned" },
  { id: "act", title: "Act now" },
  { id: "near", title: "Near a trigger" },
  { id: "draft", title: "Waiting for you" },
  { id: "new", title: "New since you looked" },
  { id: "watch", title: "Watching" },
];

export type DeskTone = "gain" | "loss" | "attention" | "info" | "muted";

/**
 * One row of the thread list. ``meter`` places the live price on the plan's track from the invalidation (0) to the
 * entry (``entry``, 0-100) and beyond; it is absent when there is no plan. Ids say what the row opens.
 */
export type DeskThread = {
  key: string;
  group: DeskGroup;
  symbol: string | null;
  title: string;
  instrument: string | null;
  value: { text: string; tone: DeskTone } | null;
  status: { text: string; tone: DeskTone };
  meter: { last: number; entry: number; tone: DeskTone } | null;
  investigationId: string | null;
  tradeId: number | null;
  radarEventId: string | null;
  /** Epoch seconds of the newest change, for "new since you looked". */
  changedAt: number | null;
};

/** A decision logged from the decision bar; saved as a day-journal entry of kind ``decision``. */
export type DeskDecision = { symbol: string; choice: "holding" | "exiting"; reason: string; investigationId: string | null; at: string };

/**
 * The open thread's plan and position, for the thread header and plan ladder. An option's ``mark`` and ``avg_entry``
 * are a contract each (the premium x 100), as the journal keeps them; a stock's are dollars a share.
 */
export type DeskPosition = PlanPosition & {
  option?: { side: string; strike: number; expiry: string } | null;
  mark?: number | null; avg_entry?: number | null; days_held?: number;
};
export type DeskThreadPlan = {
  /** The Plans board row for this investigation; its ``last`` and levels are the symbol's own (the underlying's). */
  plan: PlanBoardRow | null;
  position: DeskPosition | null;
  quotesAt: number | null;
  /** Neither read answered, so "no plan" would be a guess. */
  unavailable: boolean;
};

async function readJson<T>(path: string, signal?: AbortSignal): Promise<T | null> {
  try {
    const response = await fetch(apiUrl(path), { cache: "no-store", signal });
    return response.ok ? await response.json() as T : null;
  } catch (failure) {
    if (signal?.aborted) throw failure;
    return null;
  }
}

/**
 * ``GET /copilot/plans`` and ``GET /copilot/plans/positions`` for one thread. The plan is the board row for this
 * investigation. The position is the open one in its symbol: while that plan is in a position, preferably the one whose
 * plan has the same invalidation; with no plan on the board, any open position in the symbol; an armed plan not yet
 * entered shows none, so another trade's position is never shown as this plan's.
 */
export async function getThreadPlan(thread: Pick<DeskThreadRef, "id" | "symbol">, signal?: AbortSignal): Promise<DeskThreadPlan> {
  const [board, held] = await Promise.all([
    readJson<PlansBoard>("/copilot/plans", signal),
    thread.symbol ? readJson<{ positions: DeskPosition[] }>("/copilot/plans/positions", signal) : Promise.resolve(null),
  ]);
  const plan = board?.plans.find(row => row.investigation_id === thread.id) ?? null;
  const symbol = thread.symbol ?? plan?.symbol ?? null;
  const open = (held?.positions ?? []).filter(row => row.symbol === symbol);
  let position: DeskPosition | null = null;
  if (!plan) position = open[0] ?? null;
  else if (plan.position === "in_position")
    position = open.find(row => plan.invalidation && row.plan?.invalidation?.price === plan.invalidation.price)
      ?? open.find(row => row.plan) ?? open[0] ?? null;
  return { plan, position, quotesAt: board?.quotes_at ?? null, unavailable: !board && !held };
}

// --------------------------------------------------------------------------- the Context pane

/** The Context pane's tabs: the chart opens first; the timeline and the owner's history wait until asked for. */
export type ContextTab = "chart" | "timeline" | "history";

/** One thing that touched the thread (``GET /copilot/desk/{id}/timeline``); ``at`` is epoch seconds. */
export type DeskTimelineRow = {
  kind: "alert" | "time_stop" | "revisit" | "fill" | "thesis" | "ping" | "decision";
  at: number; text: string; detail: string | null;
};
export type DeskTimeline = { state: "ok"; symbol: string | null; rows: DeskTimelineRow[]; count: number; unavailable: string[]; recent_days: number };

/** The owner's record at the plan's invalidation (``GET /copilot/desk/{id}/history``): won and not won among the past
 * trades that crossed a level this far from their entry while held, and one sentence from those counts. */
export type DeskHistory =
  | { state: "ok"; symbol: string; level: number; side: "below" | "above"; entry: number; entry_from: "planned" | "current";
      distance_pct: number; trades: number; crossed: number; won: number; not_won: number; recovered: number;
      median_from_cross_pct: number | null; small: boolean; window_days: number; sentence: string; note: string; simulated: boolean }
  | { state: "missing" | "unavailable"; symbol?: string; reason: string };

const deskPath = (id: string, part: string) => apiUrl(`/copilot/desk/${encodeURIComponent(id)}/${part}`);

async function deskRead<T>(id: string, part: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(deskPath(id, part), { cache: "no-store", signal });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${response.status}).`);
  return body as T;
}

export const getDeskTimeline = (id: string, signal?: AbortSignal) => deskRead<DeskTimeline>(id, "timeline", signal);
export const getDeskHistory = (id: string, signal?: AbortSignal) => deskRead<DeskHistory>(id, "history", signal);

/** Today's picture for the thread as an object URL (the caller revokes it), or the server's reason it is unavailable. */
export async function getDeskPicture(id: string, signal?: AbortSignal): Promise<{ url: string } | { reason: string }> {
  const response = await fetch(deskPath(id, "picture"), { cache: "no-store", signal });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    return { reason: typeof body?.detail === "string" ? body.detail : `The chart is unavailable (${response.status}).` };
  }
  return { url: URL.createObjectURL(await response.blob()) };
}
