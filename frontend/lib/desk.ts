/**
 * The Copilot desk (`/copilot-lab`): shapes shared by the desk shell and the pieces that fill it.
 * The shell (`components/copilot/CopilotLab.tsx`) owns the layout and these hand-offs; the thread list, decision
 * bar, inspector and palette build against the types below. See docs/copilot-lab.md#the-desk.
 */

import { apiUrl } from "./api";

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
 * entry (``entry``, 0-100) and beyond; it is absent when there is no plan. Ids say what the row opens: an investigation
 * opens in place; otherwise ``path`` is a deep link (a Radar event, planning a position, a trade).
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
  tradeId: string | null;
  radarEventId: string | null;
  path: string | null;
  /** Epoch seconds of the newest change, for "new since you looked". */
  changedAt: number | null;
};

/** A decision logged from the decision bar; saved as a day-journal entry of kind ``decision``. */
export type DeskDecision = { symbol: string; choice: "holding" | "exiting"; reason: string; investigationId: string | null; at: string };

/** The day's one line above the groups: the market phase (null when unknown), how many rows need a decision, the plan streak. */
export type DeskDay = { phase: "pre" | "regular" | "post" | "closed" | null; needYou: number; streak: { current: number; best: number } | null };

/** ``GET /copilot/desk/threads``: every row in group order, and each source's state (one failure reads unavailable). */
export type DeskThreads = {
  asOf: string; quotesAt: number | null; quoteIssue: string | null; day: DeskDay; threads: DeskThread[];
  sections: Record<string, "ok" | "unavailable" | "off">;
};

type Wire = {
  as_of: string; quotes_at: number | null; quote_issue: string | null; sections: DeskThreads["sections"];
  day: { phase: DeskDay["phase"]; need_you: number; streak: DeskDay["streak"] };
  threads: (Omit<DeskThread, "investigationId" | "tradeId" | "radarEventId" | "changedAt"> &
    { investigation_id: string | null; trade_id: string | null; radar_event_id: string | null; changed_at: number | null })[];
};

export async function getDeskThreads(signal?: AbortSignal): Promise<DeskThreads> {
  const response = await fetch(apiUrl("/copilot/desk/threads"), { cache: "no-store", signal });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${response.status}).`);
  const wire = body as Wire;
  return {
    asOf: wire.as_of, quotesAt: wire.quotes_at, quoteIssue: wire.quote_issue, sections: wire.sections,
    day: { phase: wire.day.phase, needYou: wire.day.need_you, streak: wire.day.streak },
    threads: wire.threads.map(({ investigation_id, trade_id, radar_event_id, changed_at, ...row }) => ({
      ...row, investigationId: investigation_id, tradeId: trade_id, radarEventId: radar_event_id, changedAt: changed_at,
    })),
  };
}
