/**
 * The Copilot desk (`/copilot-lab`): shapes shared by the desk shell and the pieces that fill it.
 * The shell (`components/copilot/CopilotLab.tsx`) owns the layout and these hand-offs; the thread list, decision
 * bar, inspector and palette build against the types below. See docs/copilot-lab.md#the-desk.
 */

/** The phone's three tabs; on a wide screen every pane shows at once. */
export type DeskTab = "now" | "thread" | "context";

/** What the desk asks the conversation to do: open a saved investigation, send one prompt across everything, or put a
 * question in the message box unsent (the decision bar's Ask why). */
export type DeskCommand = { kind: "open"; id: string; n: number } | { kind: "ask"; text: string; n: number } | { kind: "fill"; text: string; n: number };

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
 * One Act-now row of ``GET /today`` (backend/app/routers/today.py): an open position with the reasons it needs a decision,
 * the plan's invalidation and time stop beside them, and the latest phone alert's time (epoch seconds).
 */
export type DeskActRow = {
  trade_id: string; symbol: string; contract: string; direction: string | null;
  reasons: { kind: string; text: string }[];
  invalidation: { price: number; condition: string; state: "armed" | "hit"; distance_pct?: number; hit_at?: number | null } | null;
  time_stop: { clock: string; state: string; due_at: number } | null;
  latest_alert: { kind: string; at: number } | null;
};

const ORDER = ["invalidation_hit", "giveback", "invalidation_near", "time_stop", "expires_today"];
const hhmm = (seconds: number) => new Date(seconds * 1000).toLocaleTimeString("en-GB", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit" });

/**
 * What the decision bar says for one Act-now row: what fired and when, what the plan says, the day-journal text for each
 * choice, and the quiet line after it. ``trigger`` is the newest known trigger time (epoch seconds: the latest phone alert,
 * an invalidation hit, a time stop coming due), so a decision logged before it does not hide the bar. Advice only: nothing here places, sizes or sends an order.
 */
export function deskDecision(row: DeskActRow) {
  const reasons = [...row.reasons].sort((a, b) => ORDER.indexOf(a.kind) - ORDER.indexOf(b.kind));
  const top = reasons[0];
  const level = row.invalidation;
  const price = level?.price.toFixed(2);
  const gaveBack = row.latest_alert?.kind === "giveback" ? row.latest_alert.at : null;
  const fired = top?.kind === "giveback" ? `Give-back fired${gaveBack ? ` at ${hhmm(gaveBack)}` : ""}`
    : top?.kind === "invalidation_hit" ? `Invalidation ${price} hit${level?.hit_at ? ` at ${hhmm(level.hit_at)}` : ""}`
    : top?.text ?? "";
  // The hold side is where the level is not: a long put's or short stock's invalidation sits above the price. ``direction``
  // is the lot's (bought or sold), not the thesis's, so it is only the fallback when no distance was read.
  const levelAbove = level?.distance_pct !== undefined ? level.distance_pct > 0 : row.direction === "short";
  const holdSide = levelAbove ? "below" : "above";
  let plan: string | null = null;
  let planShort = "no plan on file";
  let next = "your next alert";
  if (level?.state === "hit") {
    plan = `Your plan's invalidation, ${price}, was hit.`;
    planShort = `plan's invalidation ${price} was hit`;
  } else if (level) {
    const gap = level.distance_pct;
    const side = gap === undefined ? null : gap < 0 ? "above" : "below";
    plan = `Your plan says hold while ${row.symbol} is ${holdSide} ${price}.${gap !== undefined ? ` It is ${Math.abs(gap).toFixed(1)}% ${side}.` : ""}`;
    planShort = `plan says hold ${holdSide} ${price}${gap !== undefined ? ` (${Math.abs(gap).toFixed(1)}% ${side})` : ""}`;
    const breakSide = levelAbove ? "above" : "below";
    next = level.condition === "touches" ? `a touch of ${price}` : level.condition === "crosses" ? `a cross ${breakSide} ${price}` : `a close ${breakSide} ${price}`;
  } else if (row.time_stop) {
    plan = `Your plan's time stop is ${row.time_stop.clock}.`;
    planShort = `plan's time stop ${row.time_stop.clock}`;
  }
  if (row.time_stop?.state === "pending" && (!level || level.state === "hit")) next = `the time stop at ${row.time_stop.clock}`;
  // Any later phone alert, a hit, or a time stop coming due (30 minutes out, when it joins Act now) answers a new question.
  const stopDue = reasons.some(r => r.kind === "time_stop") && row.time_stop ? row.time_stop.due_at - 30 * 60 : null;
  const triggers = [row.latest_alert?.at ?? null, level?.hit_at ?? null, stopDue].filter((t): t is number => typeof t === "number");
  return {
    fired: fired ? `${fired}.` : "",
    others: reasons.slice(1).map(r => r.text),
    plan,
    entry: (choice: DeskDecision["choice"]) => `${choice === "holding" ? "Holding" : "Exiting"}. ${fired}; ${planShort}.`,
    ask: `${fired} on ${row.symbol}; ${planShort}. Should I hold or exit here, and why?`,
    after: (choice: DeskDecision["choice"], at: string) => choice === "holding"
      ? `You logged holding at ${at}. Next check: ${next}.`
      : `You logged exiting at ${at}. Close it in Robinhood; the fill links to the plan on its own.`,
    trigger: triggers.length ? Math.max(...triggers) : null,
  };
}

/** A logged decision's choice, read back from its day-journal text ("Holding. …" / "Exiting. …"). */
export const decisionChoice = (text: string): DeskDecision["choice"] | null =>
  text.startsWith("Holding.") ? "holding" : text.startsWith("Exiting.") ? "exiting" : null;

/** After the regular close (16:00 New York) on a weekday, by ``at`` (an ISO time); holidays and early closes are not known here. */
export function afterClose(at: string) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", weekday: "short", hour: "2-digit", hourCycle: "h23" })
    .formatToParts(new Date(at)).map(p => [p.type, p.value]));
  return !["Sat", "Sun"].includes(parts.weekday) && Number(parts.hour) >= 16;
}
