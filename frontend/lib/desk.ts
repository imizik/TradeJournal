/**
 * The Copilot desk (`/copilot-lab`): shapes shared by the desk shell and the pieces that fill it.
 * The shell (`components/copilot/CopilotLab.tsx`) owns the layout and these hand-offs; the thread list, decision
 * bar, inspector and palette build against the types below. See docs/copilot-lab.md#the-desk.
 */

import type { PlanPosition } from "@/components/dashboard/PlansCard";
import { api, apiUrl } from "@/lib/api";
import type { InvestigationSummary, PlanBoardRow, PlansBoard } from "@/lib/copilot";

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
  /** A row with a position or a plan: how often the desk checks in on its symbol (``HORIZONS``); null for any other row. */
  horizon: DeskHorizon | null;
  /** After 16:00 New York on a weekday, a row its horizon asks about today: its close-of-day question (the decision
   * bar's; ``plan_ask`` is a position with no plan, asked once) and the first words of today's answer once one is saved. */
  close: { kind: "position" | "plan" | "plan_ask"; question: string; reviewed: string | null } | null;
};

/** How often the desk checks in after the close: a day trade every trading day, a swing on a day something happened to
 * it, a long hold never (Review my week looks at it). Saved as a ``horizon`` day-journal entry, its label the text. */
export type DeskHorizon = "day" | "swing" | "long";
export const HORIZONS: { id: DeskHorizon; label: string }[] = [
  { id: "day", label: "Day trade" }, { id: "swing", label: "Swing" }, { id: "long", label: "Long hold" },
];
const uid = () => typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;

/** Sets the symbol's horizon from today on. ``operationId`` makes a retry save once (a plan card passes its own). */
export const saveHorizon = (symbol: string, horizon: DeskHorizon, operationId = `horizon-${uid()}`) =>
  api.addDayJournalEntry(nyDay(), { operation_id: operationId, kind: "horizon", symbol,
    text: HORIZONS.find(h => h.id === horizon)!.label });

/** The default horizon for a plan card's time stop: a time stop due today makes it a day trade, else a swing. */
export const horizonFor = (dueAt: number | null | undefined) =>
  dueAt && nyDate(new Date(dueAt * 1000)) === nyDate(new Date()) ? "day" as const : "swing" as const;

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
  threads: (Omit<DeskThread, "investigationId" | "tradeId" | "radarEventId" | "changedAt" | "close" | "horizon"> &
    { investigation_id: string | null; trade_id: string | null; radar_event_id: string | null; changed_at: number | null;
      close?: DeskThread["close"]; horizon?: DeskHorizon | null })[];
};

const nyDate = (at: Date) => new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(at);

/** Saved conversations closed and last touched since Monday (New York), newest first, from the latest 50 saved. */
export async function getClosedThisWeek(signal?: AbortSignal): Promise<InvestigationSummary[]> {
  const response = await fetch(apiUrl("/copilot/investigations?limit=50"), { cache: "no-store", signal });
  if (!response.ok) throw new Error(`Request failed (${response.status}).`);
  const today = nyDate(new Date());
  const noon = Date.parse(`${today}T12:00:00Z`);
  const monday = new Date(noon - ((new Date(noon).getUTCDay() + 6) % 7) * 86_400_000).toISOString().slice(0, 10);
  const { investigations } = await response.json() as { investigations: InvestigationSummary[] };
  return investigations.filter(row => row.status === "closed" && nyDate(new Date(row.updated_at)) >= monday);
}

export async function getDeskThreads(signal?: AbortSignal): Promise<DeskThreads> {
  const response = await fetch(apiUrl("/copilot/desk/threads"), { cache: "no-store", signal });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${response.status}).`);
  const wire = body as Wire;
  return {
    asOf: wire.as_of, quotesAt: wire.quotes_at, quoteIssue: wire.quote_issue, sections: wire.sections,
    day: { phase: wire.day.phase, needYou: wire.day.need_you, streak: wire.day.streak },
    threads: wire.threads.map(({ investigation_id, trade_id, radar_event_id, changed_at, close, horizon, ...row }) => ({
      ...row, investigationId: investigation_id, tradeId: trade_id, radarEventId: radar_event_id, changedAt: changed_at, close: close ?? null,
      horizon: horizon ?? null,
    })),
  };
}

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

/** A close-of-day question skipped for the day, remembered in this browser only (``day`` is New York's, YYYY-MM-DD). */
const skipKey = (day: string, symbol: string) => `tradejournal:desk:review-skipped:${day}:${symbol}`;
export function reviewSkipped(day: string, symbol: string) {
  try { return localStorage.getItem(skipKey(day, symbol)) === "1"; } catch { return false; }
}
export function skipReview(day: string, symbol: string) {
  try { localStorage.setItem(skipKey(day, symbol), "1"); } catch { /* skipped for this visit only */ }
}

/** The close pass's order: one row per symbol still asking its close question today, in list order. */
export function toReview(rows: DeskThread[], day: string, done: ReadonlySet<string> = new Set()) {
  const seen = new Set<string>();
  return rows.filter(r => r.close && !r.close.reviewed && r.symbol && !done.has(r.symbol) && !reviewSkipped(day, r.symbol)
    && !seen.has(r.symbol) && !!seen.add(r.symbol));
}

/** Today in New York, YYYY-MM-DD. */
export const nyDay = (at: Date = new Date()) => nyDate(at);

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

/** The picture route's reserved id for the Briefing's chart: QQQ today with the day's fills and pings. */
export const DESK_MARKET = "market";

/** A thread named by its symbol alone (a position or plan with no saved conversation, a Radar hit): the Context pane's
 * routes read it as ``symbol:`` and the symbol, with its plan's lines and its open trade when it has them. */
export const deskSymbolThread = (symbol: string): DeskThreadRef => ({ id: `symbol:${symbol}`, symbol, title: symbol, refreshKey: 0 });

/** The thread chart's timeframes: today's minutes, recent sessions' 15-minute bars, a few months of daily bars. */
export const DESK_TIMEFRAMES = ["2m", "15m", "1D"] as const;
export type DeskTimeframe = (typeof DESK_TIMEFRAMES)[number];

/** The thread's picture (today's, or on ``timeframe``) as an object URL (the caller revokes it), or the server's reason
 * it is unavailable. */
export async function getDeskPicture(id: string, signal?: AbortSignal, timeframe?: DeskTimeframe): Promise<{ url: string } | { reason: string }> {
  const part = timeframe ? `picture?timeframe=${encodeURIComponent(timeframe)}` : "picture";
  const response = await fetch(deskPath(id, part), { cache: "no-store", signal });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    return { reason: typeof body?.detail === "string" ? body.detail : `The chart is unavailable (${response.status}).` };
  }
  return { url: URL.createObjectURL(await response.blob()) };
}

// --------------------------------------------------------------------------- the Briefing's session timeline

/** One thing that happened today, for the session strip; ``at`` is epoch seconds. */
export type DeskSessionEvent = { kind: "fill" | "ping" | "radar" | "decision"; at: number; symbol: string | null; text: string };

/** ``GET /copilot/desk/session``: today's regular session (``open``/``close`` null on a closed day), what happened in it,
 * the plan time stops still ahead, pings against the daily cap, the pre-market prep and SPY/QQQ/VIX. Times are epoch seconds. */
export type DeskSession = {
  as_of: string; now: number; day: string; phase: DeskDay["phase"]; open: number | null; close: number | null;
  events: DeskSessionEvent[]; time_stops: { symbol: string; at: number; clock: string }[];
  pings: { sent: number; held: number; cap: number } | null; prep: { at: number | null; line: string | null } | null;
  indices: { symbol: string; last: number | null; change_pct: number | null }[]; quote_issue: string | null;
  sections: Record<string, "ok" | "unavailable" | "off">;
};

export async function getDeskSession(signal?: AbortSignal): Promise<DeskSession> {
  const response = await fetch(apiUrl("/copilot/desk/session"), { cache: "no-store", signal });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${response.status}).`);
  return body as DeskSession;
}

// --------------------------------------------------------------------------- the alert scorecard

/** What one alert's contracts did after it (``GET /copilot/desk/scorecard``); dollars, against selling at the alert. */
export type ScorecardOutcome =
  | { state: "closed"; how: "sold" | "expired" | "sold_then_expired"; sell_at_alert_usd: number; basis: "bid" | "mark";
      actual_usd: number; vs_alert_usd: number; ended_at: number | null }
  | { state: "open"; sell_at_alert_usd: number; basis: "bid" | "mark"; sold_so_far_usd: number; contracts_left: number }
  | { state: "not_measured"; why: string };
export type ScorecardRow = {
  at: number; kind: string; kind_label: string; contract: string; symbol: string; pnl_pct_at_alert: number | null;
  decision: "holding" | "exiting" | null; decided_at: number | null; outcome: ScorecardOutcome;
};
export type ScorecardTally = { alerts: number; closed: number; better: number; worse: number; even: number; open: number; not_measured: number; vs_alert_usd: number };
export type AlertScorecard = {
  window_days: number; alerts: number; rows: ScorecardRow[]; truncated: boolean;
  summary: { holding: ScorecardTally; exiting: ScorecardTally; none: ScorecardTally };
  /** The Radar scorecard, from the same read; ``off`` while Radar is not recording. */
  radar?: RadarScorecard | { state: "off" | "unavailable"; reason: string | null };
};

// --------------------------------------------------------------------------- the Radar scorecard

/** A Radar decision on the desk, logged as a day-journal ``decision`` ("Watching. …", "Passing. …", "Planning. …"). */
export type RadarChoice = "watching" | "passing" | "planning";
export const radarChoice = (text: string): RadarChoice | null =>
  text.startsWith("Watching.") ? "watching" : text.startsWith("Passing.") ? "passing" : text.startsWith("Planning.") ? "planning" : null;
/** One stock hit: the decision after it, and the stock against SPY in the hit's direction (percent) an hour on and at the close. */
export type RadarScorecardRow = {
  event_id: string; at: number; symbol: string; kind: string; kind_label: string; direction: "up" | "down"; summary: string | null;
  decision: RadarChoice | null; decided_at: number | null; planned: boolean; traded: boolean;
  after: { hour_pct: number | null; close_pct: number | null; why: string | null };
};
export type RadarTally = { hits: number; measured: number; kept_going: number; avg_close_pct: number | null };
export type RadarScorecard = {
  state: "ok"; window_days: number; hits: number; rows: RadarScorecardRow[]; truncated: boolean;
  summary: Record<RadarChoice | "none", RadarTally>;
};

export async function getAlertScorecard(signal?: AbortSignal): Promise<AlertScorecard> {
  const response = await fetch(apiUrl("/copilot/desk/scorecard"), { cache: "no-store", signal });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${response.status}).`);
  return body as AlertScorecard;
}
