/**
 * The Copilot desk (`/copilot-lab`): shapes shared by the desk shell and the pieces that fill it.
 * The shell (`components/copilot/CopilotLab.tsx`) owns the layout and these hand-offs; the thread list, decision
 * bar, inspector and palette build against the types below. See docs/copilot-lab.md#the-desk.
 */

import type { PanelLink } from "@/components/copilot/CopilotPanel";
import type { PlanPosition } from "@/components/dashboard/PlansCard";
import type { AlertFeedback } from "@/lib/alertFeedback";
import { api, apiUrl } from "@/lib/api";
import { UUID_RE, readDeepLink, type ExitLesson, type InvestigationSummary, type PlanBoardLevel, type PlanBoardRow, type PlansBoard } from "@/lib/copilot";
import type { OptionTerms } from "@/lib/optionStanding";
import type { RadarRating } from "@/lib/radar";

/** The phone's three tabs; on a wide screen every pane shows at once. */
export type DeskTab = "threads" | "thread" | "context";

/** What the desk asks the conversation to do: open a saved investigation (with ``text`` in the box, unsent), send one
 * prompt across everything, put a question in the message box unsent (the decision bar's Ask why), or leave the open
 * conversation saved and go back to Main (``home``). */
export type DeskCommand = { kind: "open"; id: string; n: number; text?: string } | { kind: "ask"; text: string; n: number } | { kind: "fill"; text: string; n: number } | { kind: "home"; n: number }
  /** A desk link the desk follows in place (``deskLinkIn``): a new conversation on it, as a fresh load of it starts. */
  | { kind: "link"; link: PanelLink; n: number }
  /** Now in place: today's Main chat, as the desk's bare address opens it. */
  | { kind: "now"; n: number };

/** The conversation's open investigation, reported up so the inspector can show its context. */
export type DeskThreadRef = { id: string; symbol: string | null; title: string; refreshKey: number; mainDay?: string | null };

/** How the conversation and the desk talk: commands down, the open thread up. ``planDone`` is there while the open
 * thread has a plan that can be marked done (the thread menu's Mark plan done): its symbol, and ``done`` hears it was. */
export type DeskHooks = { command: DeskCommand | null; onThread(thread: DeskThreadRef | null): void; planDone?: { symbol: string; done(): void } | null;
  /** Something at the top of the thread still asks for an answer: a conversation opens there, not on its latest turn. */
  holdTop?: boolean;
  /** The latest question and its finished answer, so the Context pane can follow the ticker they are about. */
  onAnswer?(text: string | null): void };

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
  close: { kind: "position" | "plan" | "plan_ask" | "exit"; question: string; reviewed: string | null } | null;
  /** The open trade whose fill waits to be linked to a plan (a position the link ping offers plans for, or the plan the
   * linker suggests it for); its thread top links it inline (``FillLinkBar``). */
  fillToLink: string | null;
  /** A position the copilot adopted after an unplanned entry (its draft or confirmed plan is the thread's). */
  adopted?: boolean;
  /** A ticker the owner set to "Not following" (``saveFollow``): kept out of Now's lists, the thread list's groups and
   * every "needs you" count, behind one "N not followed" line; it asks no close-of-day question. */
  hidden: boolean;
  /** An open position's book line for the desk's left column (``_book`` in copilot_desk.py): unrealized P&L, expiry
   * (ISO date, an option's), days held, the plan's track (``meter``'s shape; null without entry and invalidation), the
   * signed distance to the invalidation in percent, and one state. Absent on any other row. */
  book?: DeskBook;
};

/** The book row's one tag (``_book_state`` in copilot_desk.py; docs/copilot-lab.md § The book's tag). */
export type DeskBookState = "past_stop" | "near_stop" | "giving_back" | "no_plan" | "on_plan";
export type DeskBook = {
  usd: number | null; pct: number | null; expiry: string | null; days_held: number | null;
  track: { last: number; entry: number; tone: DeskTone } | null; state: DeskBookState; stop_pct: number | null;
  /** A confirmed invalidation or time stop (an adopted draft is not yet a plan); absent from an older backend. */
  planned?: boolean;
  /** Only while the Robinhood feed is live (docs/robinhood-read-feed.md): ``matched`` (P&L, quantity and mark are
   * Robinhood's), ``new`` (Robinhood shows it, the journal does not yet) or ``not_on_robinhood`` (left as the journal has
   * it). ``mark`` is a contract's (the premium x 100) or a share's. */
  live?: "matched" | "new" | "not_on_robinhood";
  quantity?: number | null;
  mark?: number | null;
  account?: { label: string; masked: string };
  /** What the live prices need to move the P&L in place (``_tick`` in copilot_desk.py; ``tickedBook`` in deskTicks.ts):
   * the symbol to quote (an option's OCC symbol), 100 for a contract or 1 for a share, the cost and quantity in those
   * units, and the side. Absent or null when the P&L is not derived from a price the desk can quote. */
  tick?: { quote: string; scale: number; cost: number; quantity: number; sign: 1 | -1 } | null;
  /** A held option's terms for its standing (``_option_terms`` / ``_live_terms`` in copilot_desk.py; ``optionStanding`` in
   * optionStanding.ts): contract, side, size, cost a contract and the Greeks with their source and time. Null for a stock. */
  option?: OptionTerms | null;
  /** Robinhood's working orders and today's fills on this contract (``_order_lines`` in copilot_desk.py); absent when
   * there are none or the order-history read is off, signed out or stale. */
  orders?: DeskOrder[];
  /** The plan's two exits on the underlying (its invalidation and saved target; null without one), for the closing
   * ticket (``lib/closingTicket.ts``). Absent from an older backend. */
  plan_levels?: { stop: number | null; target: number | null };
};

/** One Robinhood order on the desk (docs/robinhood-order-fills.md § On the desk): still working (``working``, with what
 * has ``filled`` so far), or filled today. Prices are a share's (an option's premium as quoted). ``pairing`` says whether
 * the journal has the fill yet: ``provisional`` until its email arrives and matches, then ``matched``; ``differs`` when
 * the email disagrees; ``roll`` for a two-leg order (left to its email); ``recurring`` for a recurring buy Robinhood
 * never emails. Display only: the app never places, changes or
 * cancels an order. */
export type DeskOrder = {
  contract: string; symbol: string; instrument: "option" | "stock"; action: string; working: boolean;
  /** ``net``: a roll's price, the whole order's credit or debit (not one leg's). */
  quantity: number | null; filled: number; price_kind: "limit" | "market" | "stop" | "net"; limit: number | null; avg: number | null;
  placed_at: number | null; filled_at: number | null; account: { label: string; masked: string };
  pairing: "provisional" | "matched" | "differs" | "roll" | "recurring" | null;
};

/** The Robinhood feed's state on the desk (docs/robinhood-read-feed.md). ``ok`` (with ``joined``) drives the book;
 * anything else leaves the book exactly as the journal has it. Account numbers only ever arrive masked. */
export type DeskLiveAccount = { label: string; masked: string; total_value: number | null; cash: number | null; buying_power: number | null };
export type DeskLive = {
  state: "off" | "signed_out" | "expired" | "loading" | "unavailable" | "stale" | "ok";
  as_of?: number; issue?: string | null; joined?: boolean; accounts?: DeskLiveAccount[];
  /** Orders with no followed book row to sit on (no position yet, or the fill closed it): the book's "Orders" group. */
  orders?: DeskOrder[];
};
export const liveOn = (live: DeskLive | null | undefined) => live?.state === "ok" && live.joined === true;

/** Reads Robinhood now (at most once every 15 seconds on the server); then re-read the desk. */
export async function refreshRobinhood(): Promise<DeskLive> {
  const response = await fetch(apiUrl("/copilot/desk/robinhood/refresh"), { method: "POST", cache: "no-store" });
  if (!response.ok) throw new Error(`Request failed (${response.status}).`);
  return await response.json() as DeskLive;
}

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

/** Follows a ticker again, or stops following it (Now's Hide, the thread header, Show again): a ``follow`` entry; the
 * newest one wins, on every device. */
export const saveFollow = (symbol: string, following: boolean) =>
  api.addDayJournalEntry(nyDay(), { operation_id: `follow-${uid()}`, kind: "follow", symbol, text: following ? "Following" : "Not following" });

/** Ends the symbol's plan from now on (its exit review answered or skipped, or Mark done): a ``plan_done`` entry. */
export const savePlanDone = (symbol: string, text: "Exit reviewed" | "Exit review skipped" | "Marked done", day = nyDay()) =>
  api.addDayJournalEntry(day, { operation_id: `plan-done-${uid()}`, kind: "plan_done", symbol, text });

/** The default horizon for a plan card's time stop: a time stop due today makes it a day trade, else a swing. */
export const horizonFor = (dueAt: number | null | undefined) =>
  dueAt && nyDate(new Date(dueAt * 1000)) === nyDate(new Date()) ? "day" as const : "swing" as const;

/** A decision logged from the decision bar; saved as a day-journal entry of kind ``decision``. */
export type DeskDecision = { symbol: string; choice: "holding" | "exiting"; reason: string; investigationId: string | null; at: string };

/** The day's one line above the groups: the market phase (null when unknown), how many rows need a decision, the plan streak. */
export type DeskDay = { phase: "pre" | "regular" | "post" | "closed" | null; needYou: number; streak: { current: number; best: number } | null };

/** One plan in the thread list's Plans view, by ``stage``: armed (not yet in a position), in position (a fill waiting to be
 * linked counts, ``note`` "Fill to link"), exited (its exit review waiting) or done (``note`` the ``plan_done`` text), the
 * last two over the last seven days. Levels are on the underlying (``PlanBoardLevel``); ``r`` is where the underlying sits
 * in units of the plan's risk, in a position only; ``at`` (epoch seconds) is the exit or done time. A done plan whose alerts
 * and time stop were all deleted has no ``investigationId``. */
export type DeskPlanStage = "armed" | "in_position" | "exited" | "done";
export type DeskPlan = {
  stage: DeskPlanStage; symbol: string; investigationId: string | null; instrument: string | null; thesis: string | null;
  horizon: DeskHorizon; last: number | null; entry: PlanBoardLevel | null; invalidation: PlanBoardLevel | null;
  timeStop: PlanBoardRow["time_stop"]; r: number | null; at: number | null; note: string | null;
  /** An armed plan's symbol's newest answered exit review, for Arm today's plans; null without one. */
  lastExit: ExitLesson | null;
};

/** ``GET /copilot/desk/threads``: every row in group order, the Plans view, and each source's state (one failure reads
 * unavailable). */
export type DeskThreads = {
  asOf: string; quotesAt: number | null; quoteIssue: string | null; day: DeskDay; threads: DeskThread[]; plans: DeskPlan[];
  sections: Record<string, "ok" | "unavailable" | "off">; robinhood: DeskLive;
};

type Wire = {
  as_of: string; quotes_at: number | null; quote_issue: string | null; sections: DeskThreads["sections"]; robinhood?: DeskLive;
  day: { phase: DeskDay["phase"]; need_you: number; streak: DeskDay["streak"] };
  threads: (Omit<DeskThread, "investigationId" | "tradeId" | "radarEventId" | "changedAt" | "close" | "horizon" | "fillToLink" | "hidden"> &
    { investigation_id: string | null; trade_id: string | null; radar_event_id: string | null; changed_at: number | null;
      close?: DeskThread["close"]; horizon?: DeskHorizon | null; fill_to_link?: string | null; hidden?: boolean })[];
  plans?: (Omit<DeskPlan, "investigationId" | "timeStop" | "lastExit"> &
    { investigation_id: string | null; time_stop: DeskPlan["timeStop"]; last_exit?: ExitLesson | null })[];
};

const nyDate = (at: Date) => new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(at);

/** The latest 50 saved conversations, open and closed, newest first: the thread list's subthreads and the breadcrumb. */
export async function getSavedConversations(signal?: AbortSignal): Promise<InvestigationSummary[]> {
  const response = await fetch(apiUrl("/copilot/investigations?limit=50"), { cache: "no-store", signal });
  if (!response.ok) throw new Error(`Request failed (${response.status}).`);
  return ((await response.json()) as { investigations: InvestigationSummary[] }).investigations;
}

/** Every saved conversation whose title, symbol or conclusion holds the words, newest first; Jump's reach past the list. */
export async function searchConversations(query: string, signal?: AbortSignal): Promise<InvestigationSummary[]> {
  const response = await fetch(apiUrl(`/copilot/investigations?limit=50&q=${encodeURIComponent(query)}`), { cache: "no-store", signal });
  if (!response.ok) throw new Error(`Request failed (${response.status}).`);
  return ((await response.json()) as { investigations: InvestigationSummary[] }).investigations;
}

export async function getDeskThreads(signal?: AbortSignal): Promise<DeskThreads> {
  const response = await fetch(apiUrl("/copilot/desk/threads"), { cache: "no-store", signal });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${response.status}).`);
  const wire = body as Wire;
  return {
    asOf: wire.as_of, quotesAt: wire.quotes_at, quoteIssue: wire.quote_issue, sections: wire.sections, robinhood: wire.robinhood ?? { state: "off" },
    day: { phase: wire.day.phase, needYou: wire.day.need_you, streak: wire.day.streak },
    threads: wire.threads.map(({ investigation_id, trade_id, radar_event_id, changed_at, close, horizon, fill_to_link, hidden, ...row }) => ({
      ...row, investigationId: investigation_id, tradeId: trade_id, radarEventId: radar_event_id, changedAt: changed_at, close: close ?? null,
      horizon: horizon ?? null, fillToLink: fill_to_link ?? null, hidden: !!hidden,
    })),
    plans: (wire.plans ?? []).map(({ investigation_id, time_stop, last_exit, ...plan }) =>
      ({ ...plan, investigationId: investigation_id, timeStop: time_stop, lastExit: last_exit ?? null })),
  };
}

// "No plan" for a waiting fill writes nothing, as the confirm page's "Not this plan" does: the fill simply stays
// unplanned. This browser remembers the answer so the desk stops asking; a blocked store asks again next visit.
const NO_PLAN_KEY = "desk.no-plan.v1";
export function readNoPlan(): string[] {
  try { return JSON.parse(window.localStorage.getItem(NO_PLAN_KEY) ?? "[]") ?? []; } catch { return []; }
}
export function saveNoPlan(tradeId: string): string[] {
  const next = [tradeId, ...readNoPlan().filter(id => id !== tradeId)].slice(0, 50);
  try { window.localStorage.setItem(NO_PLAN_KEY, JSON.stringify(next)); } catch { /* this visit only */ }
  return next;
}

/** The fills waiting to link, one row per trade in list order (a position and its suggested plan are one fill), less
 * those answered here (``done``: "No plan", or linked before the list reads it back). */
export function fillsToLink(rows: DeskThread[], done: ReadonlySet<string> | string[] = []) {
  const skip = new Set(done);
  return rows.filter(r => r.fillToLink && !r.hidden && !skip.has(r.fillToLink) && !!skip.add(r.fillToLink));
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
  return rows.filter(r => r.close && !r.close.reviewed && r.symbol && !r.hidden && !done.has(r.symbol) && !reviewSkipped(day, r.symbol)
    && !seen.has(r.symbol) && !!seen.add(r.symbol));
}

/** Today in New York, YYYY-MM-DD. */
export const nyDay = (at: Date = new Date()) => nyDate(at);

/** Does this row put a "needs you" dot on its ticker: a decision to make, a card waiting, a fill to link or a close
 * question not answered or skipped today. A ticker not followed never does. */
export const needsYou = (row: DeskThread, day: string | null) => !row.hidden && (row.group === "act" || row.group === "draft" || !!row.fillToLink
  || (!!row.close && !row.close.reviewed && !(day && row.symbol && reviewSkipped(day, row.symbol))));
/** The desk's one "needs you" count: tickers with the dot. */
export const needingCount = (rows: DeskThread[], day: string | null) =>
  new Set(rows.filter(r => r.symbol && r.group !== "pinned" && !r.key.startsWith("radar:") && needsYou(r, day)).map(r => r.symbol)).size;

/** The conversation the address names (?thread=, or a deep link's ?investigation=), lower case; null when none. */
/** The parameters a desk link may carry and still be followed in place: a symbol, its context line, its origin and drawn plan. */
const IN_PLACE = new Set(["symbol", "context", "origin", "plan"]);

/** A desk address (``/copilot-lab?…``) the desk can follow without reloading: a symbol or context link with nothing else
 * (no investigation, Radar hit, screenshot, close pass, ticket or thread). Null for anything a fresh load must handle. */
export function deskLinkIn(href: string): PanelLink | null {
  let url: URL;
  try { url = new URL(href, "http://desk.invalid"); } catch { return null; }
  if (url.pathname !== "/copilot-lab" || [...url.searchParams.keys()].some(key => !IN_PLACE.has(key))) return null;
  const link = readDeepLink(Object.fromEntries(url.searchParams));
  return link && !link.investigation ? link : null;
}

export function threadInUrl() {
  const params = new URLSearchParams(window.location.search);
  const id = params.get("thread") ?? params.get("investigation");
  return id && UUID_RE.test(id) ? id.toLowerCase() : null;
}

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

/** Market and sector funds an answer about the day often names, besides the owner's own tickers. */
const MARKET_FUNDS = ["SPY", "QQQ", "IWM", "DIA", "SMH", "SOXX", "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLC", "XLRE",
  "KRE", "XBI", "IGV", "ARKK", "TLT", "GLD", "SLV", "USO"];

/** Words in capitals an answer uses that are never its subject. */
const NOT_TICKERS = new Set(["I", "A", "AM", "PM", "ET", "EST", "EDT", "AH", "CPI", "PPI", "PCE", "FOMC", "FED", "GDP", "NFP", "IV", "HV", "ATM",
  "OTM", "ITM", "DTE", "OI", "EPS", "AI", "USD", "ETF", "ETFS", "EOD", "EOW", "RSI", "MACD", "EMA", "SMA", "VWAP", "ATH", "ATL", "YTD", "IPO",
  "CEO", "CFO", "US", "USA", "UK", "EU", "NYSE", "OK", "PT", "PNL", "TA", "PDT", "TLDR", "NOT", "AND", "THE", "OR", "IF", "NO", "YES", "BUY",
  "SELL", "HOLD", "WAIT", "PASS", "FOCUS", "DRAFT", "PATTERN", "BROKEN", "UNCLEAR", "NOW", "ASAP", "FYI", "MAX", "MIN", "FOMO", "YOLO",
  "OPEX", "ROI", "TP", "SL", "JOLTS", "ISM", "PMI", "DCA", "IMO", "BTW", "EOM", "MOC", "MOO", "RTH", "LEAPS", "LEAP", "OTC", "SEC", "IRA",
  "ER", "PE", "EV", "FCF", "YOY", "QOQ", "BE", "OK", "TBD", "NA", "PR", "AH", "PRE", "POST"]);
const MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec";
/** A ticker followed by a contract: "IREN Dec-18 calls", "IREN 12/18 30C", "IREN $30 calls", "IREN 30C". */
const CONTRACT = new RegExp(`\\b([A-Z]{1,5})\\s+(?:(?:${MONTHS})[a-z]*\\.?[- ]?\\d{1,2}\\b|\\d{1,2}\\/\\d{1,2}(?:\\/\\d{2,4})?\\b|\\$?\\d+(?:\\.\\d+)?\\s?(?:[CP]\\b|calls?\\b|puts?\\b))`, "g");

/**
 * The ticker a conversation about no symbol is about (``text``: the latest question, then its answer), for the centre's
 * chart: the one in the answer's verdict headline first, then the one named with a contract, then the one mentioned
 * most (``known``, the owner's tickers, the market funds and any named with a contract), and only then the first of
 * those mentioned; null when nothing is clearly the subject (the centre then shows the market). A word in capitals
 * that is no ticker never counts.
 */
export function answerSymbol(text: string | null, known: Iterable<string>): string | null {
  if (!text) return null;
  const tickers = new Set([...known, ...MARKET_FUNDS]);
  // 1. The verdict headline ("Verdict: Pass — IREN Dec-18 calls …"): its first ticker that is a known one or is named
  //    with a contract there, so a word like OPEX or FOMO in a headline never becomes the chart.
  const headline = (text.split("\n").map(line => /^\**verdict\**\s*:\s*\**[a-z]+\**\s*(?:—|–|--|-|:|\.)\s*(.+)$/i.exec(line.trim())).find(Boolean)?.[1] ?? "").replace(/\*\*/g, "");
  const withContract = new Set([...headline.matchAll(CONTRACT)].map(match => match[1]));
  for (const [word] of headline.matchAll(/\b[A-Z]{1,5}\b/g)) if (tickers.has(word) || (!NOT_TICKERS.has(word) && withContract.has(word))) return word;
  // 2. A ticker named with a contract.
  const contracts = [...text.matchAll(CONTRACT)].map(match => match[1]).filter(word => tickers.has(word) || !NOT_TICKERS.has(word));
  if (contracts.length) return contracts[0];
  // 3. The most mentioned, ties to the first mentioned (4.).
  const counts = new Map<string, number>();
  for (const [word] of text.matchAll(/\b[A-Z]{1,5}\b/g)) if (tickers.has(word)) counts.set(word, (counts.get(word) ?? 0) + 1);
  let best: string | null = null;
  for (const [word, n] of counts) if (best === null || n > counts.get(best)!) best = word;
  return best;
}

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

/** ``GET /copilot/desk/{id}/chart``: the cockpit centre's chart as data (``id`` a thread, ``symbol:X`` or ``market``).
 * Times are epoch seconds; ``step`` is a candle's seconds; ``extended`` candles are the pre-market or after hours. A mark
 * with no ``price`` sits on its candle. ``time_stop`` is the plan's time stop while still ahead. ``live``: bars can still
 * change, so the desk reads again each minute. ``state`` "unavailable" carries no bars and the reason. */
export type DeskChartMark = { kind: "fill" | "ping" | "radar"; at: number; price: number | null; side: "buy" | "sell" | null; text: string };
export type DeskChartData = {
  symbol: string; timeframe: DeskTimeframe; step: number; as_of: number; live: boolean;
  state: "ok" | "unavailable"; reason: string | null;
  bars: { time: number; open: number; high: number; low: number; close: number; volume: number; extended: boolean }[];
  /** One value per candle, null where the study has none (VWAP outside the regular session, an average still warming,
   * RVol on an earlier session): 2m and 15m carry ``vwap``, ``ema9``, ``ema21``, ``rvol``; 1D ``ema21``, ``sma50``,
   * ``sma200`` and ``rvol`` (the day's volume over the 30 days before it). */
  studies: Partial<Record<DeskStudySeries, (number | null)[]>>;
  /** Intraday: the previous close and today's pre-market high and low, each only when known. */
  reference: { key: "prev_close" | "pm_high" | "pm_low"; price: number; label: string }[];
  /** The reading line: the newest price (``daily``: a daily candle's, so its time is a date), the previous session's
   * close, and the RTH VWAP and RVol as of the newest regular-session minute. */
  reading: { last: number; at: number; daily: boolean; prev_close: number | null; vwap: number | null; vwap_at: number | null; rvol: number | null } | null;
  levels: { role: "entry" | "invalidation" | "target"; price: number; label: string; id?: string }[];
  /** The symbol's other armed level alerts; one from a plan is not removable here. */
  alerts: DeskChartAlert[];
  marks: DeskChartMark[];
  time_stop: { at: number; text: string } | null;
  events?: DeskChartEvents;
};
/** The chart's known events (``desk_events.chart``): the symbol's next and most recent earnings (dates only: the calendar
 * publishes no time of day), the implied move into the next one when its option chain is already cached, and on SPY, QQQ
 * and IWM the macro days (FOMC, CPI, jobs) from the first candle to three weeks ahead. Absent from an older backend. */
export type DeskChartEvents = {
  earnings: { next: { date: string; status: string | null; label: string | null;
    implied: { expiration: string; move: number | null; percent: number | null } | null } | null;
    last: { date: string; label: string | null } | null } | null;
  macro: { date: string; time: string; kind: "fomc" | "cpi" | "jobs"; name: string }[];
  note: string | null;
};
export type DeskStudySeries = "vwap" | "ema9" | "ema21" | "sma50" | "sma200" | "rvol";
export type DeskChartAlert = { id: string; price: number; text: string; label: string | null; removable: boolean;
  condition: "touches" | "crosses" | "closes_beyond"; interval: string | null; session: "regular" | "extended" };

export async function getDeskChart(id: string, timeframe: DeskTimeframe, signal?: AbortSignal): Promise<DeskChartData> {
  return deskRead<DeskChartData>(id, `chart?timeframe=${encodeURIComponent(timeframe)}`, signal);
}

/** The symbol's headlines on the desk chart (``desk_news.build``): one marker per group of headlines on candles a few
 * minutes apart, at the group's first candle (``time``). ``emphasis``: a headline was published within a few minutes of a
 * move well beyond the day's typical candle (``move``); a move with no headline has no marker. ``before``: published
 * before its candle opened (pre-market on the 15m chart, between sessions). ``state`` "hidden" for a ticker set to Not
 * following, "none" off the intraday charts, "unavailable" when the headline source could not be read. */
export type DeskNewsItem = { at: number; before: boolean; session: "regular" | "pre-market" | "after hours" | "overnight" | "weekend";
  headline: string; source: string; url: string };
export type DeskNewsGroup = { time: number; count: number; items: DeskNewsItem[]; emphasis: boolean;
  move: { start: number; end: number; pct: number; range_pct: number } | null };
export type DeskChartNews = { symbol: string | null; timeframe: DeskTimeframe; as_of: number; state: "ok" | "none" | "hidden" | "unavailable";
  reason: string | null; source?: string; groups: DeskNewsGroup[];
  /** Set when the one page of newest headlines was full: headlines before this time may be missing. */
  complete_from?: number | null };

export async function getDeskChartNews(id: string, timeframe: DeskTimeframe, signal?: AbortSignal): Promise<DeskChartNews> {
  return deskRead<DeskChartNews>(id, `news?timeframe=${encodeURIComponent(timeframe)}`, signal);
}

// --------------------------------------------------------------------------- the Briefing's session timeline

/** One thing that happened today, for the session strip; ``at`` is epoch seconds. */
export type DeskSessionEvent = { kind: "fill" | "ping" | "radar" | "decision"; at: number; symbol: string | null; text: string };

/** ``GET /copilot/desk/session``: today's regular session (``open``/``close`` null on a closed day), what happened in it,
 * the plan time stops still ahead, phone-ping counts, the pre-market prep and SPY/QQQ/VIX. Times are epoch seconds. */
export type DeskSession = {
  as_of: string; now: number; day: string; phase: DeskDay["phase"]; open: number | null; close: number | null;
  events: DeskSessionEvent[]; time_stops: { symbol: string; at: number; clock: string }[];
  pings: { sent: number; held: number; cap: number | null } | null;
  /** Today's morning brief: its first line, and (absent from an older backend) its saved lines, whether the turn failed
   * and the raw facts stand in, and the path of its thread. */
  prep: { at: number | null; line: string | null; lines?: string[]; fallback?: boolean; path?: string | null } | null;
  indices: { symbol: string; last: number | null; change_pct: number | null }[]; quote_issue: string | null;
  /** Realized P&L of the trades closed today (New York); null when unread, absent from an older backend. */
  realized_today?: number | null;
  /** What waits on the owner's answer for /proof: ``count`` in the proof's scope, ``rows`` today's then the newest waiting.
   * Null when that source is off or unavailable; absent from an older backend. */
  to_answer?: { alerts: { count: number; rows: DeskAlertToAnswer[] } | null; radar: { count: number; rows: DeskHitToRate[] } | null };
  sections: Record<string, "ok" | "unavailable" | "off">;
};
/** A sent position alert and the trade its feedback is saved against (``PUT /trades/{trade_id}/phone-alerts/{id}/feedback``). */
export type DeskAlertToAnswer = { id: string; trade_id: string; symbol: string; contract: string; kind: string; at: number; today: boolean;
  feedback: AlertFeedback | null };
/** A Radar event of the newest rule version (``POST /radar/events/{event_id}/feedback``); ``kind`` is the feed's words. */
export type DeskHitToRate = { event_id: string; symbol: string | null; kind: string; at: number | null; today: boolean; rating: RadarRating | null };

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

// --------------------------------------------------------------------------- Now's "How the pings did"

/** One alerted Radar hit or setup card: the stock against SPY the way Radar flagged it (percent) an hour on and at the
 * close, and a setup card's paper result (``pnl`` dollars per contract) when it has one. */
export type PingsRadarRow = {
  event_id: string; at: number; symbol: string; kind: string; kind_label: string; direction: "up" | "down"; summary: string | null;
  after: { hour_pct: number | null; close_pct: number | null; why: string | null }; setup: boolean;
  paper: { state: "none" | "pending" | "open" | "closed" | "unresolved"; pnl: number | null; exit_reason: string | null; note: string | null } | null;
};
/** ``GET /copilot/desk/pings``: each phone ping since the previous trading session (``since``) and what followed. */
export type DeskPings = {
  day: string; since: string;
  alerts: { state: "ok" | "unavailable"; rows: ScorecardRow[] };
  radar: { state: "ok" | "off" | "unavailable"; reason: string | null; rows: PingsRadarRow[] };
};

/** ``dayOnly``: just today's pings (the day report), else everything since the previous trading session. */
export async function getDeskPings(signal?: AbortSignal, dayOnly = false): Promise<DeskPings> {
  const response = await fetch(apiUrl(`/copilot/desk/pings${dayOnly ? "?day_only=true" : ""}`), { cache: "no-store", signal });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${response.status}).`);
  return body as DeskPings;
}

// --------------------------------------------------------------------------- the day report

/** One checked call scored from the price when he checked to the close (``engine/day_report.py``). ``way`` is the contract's
 * move when both its prices are known, else the stock's (reversed for a put); null when not measured. */
export type CheckedCallRow = {
  id: string; checked_at: string; day: string; symbol: string | null; label: string; verdict: string | null; side: "call" | "put" | null;
  decision: "planned" | "passed" | "neither"; state: "measured" | "not_measured"; why: string | null; way: "up" | "down" | "flat" | null;
  basis?: "stock" | "contract"; contract_note?: string | null;
  stock?: { at_check: number; close: number; pct: number }; contract?: { at_check: number; close: number; pct: number } | null;
};
export type CheckTally = { checked: number; up: number; down: number; flat: number; not_measured: number };
/** ``GET /copilot/desk/day-report``: today's entries and the checked calls; a part is null when it could not be read. */
export type DayReport = {
  day: string; as_of: string;
  entries: { entries: number; planned: number; late: number; pending: number;
    rows: { contract: string; state: "planned" | "late" | "unplanned" | "pending"; at: number }[] } | null;
  checks: { rows: CheckedCallRow[]; today: CheckTally; window: CheckTally & { days: number }; capped: boolean } | null;
  sections: Record<string, "ok" | "unavailable">;
};

export async function getDayReport(signal?: AbortSignal): Promise<DayReport> {
  const response = await fetch(apiUrl("/copilot/desk/day-report"), { cache: "no-store", signal });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${response.status}).`);
  return body as DayReport;
}

// --------------------------------------------------------------------------- the book's sparklines

/** ``GET /copilot/desk/sparks``: each symbol's closes today (thinned), its change today and SPY's. A Watching row
 * (``watch``) also carries its last price, and may have a change with no line. */
export type DeskSparks = { as_of: string; rows: Record<string, { points: number[]; change_pct: number | null; last?: number | null }>; spy_change_pct: number | null };

export async function getDeskSparks(symbols: string[], signal?: AbortSignal, watch: string[] = []): Promise<DeskSparks> {
  const query = new URLSearchParams({ symbols: symbols.join(","), ...(watch.length ? { watch: watch.join(",") } : {}) });
  const response = await fetch(apiUrl(`/copilot/desk/sparks?${query}`), { cache: "no-store", signal });
  if (!response.ok) throw new Error(`Request failed (${response.status}).`);
  return await response.json() as DeskSparks;
}

// --------------------------------------------------------------------------- the desk read

/** ``POST /copilot/desk/read`` (``backend/app/engine/desk_read.py``): a few lines on a selected ticker, kept per ticker on
 * the server (30 minutes in the session, longer outside it). ``hidden``: a ticker he does not follow, nothing shown;
 * ``budget``: the day's copilot budget has no room for a read; ``none``: asked ``keptOnly`` and nothing is kept there. ``today``: the day's reads, refusals and their cost. */
export type DeskReadToday = { count: number; refused: number; cost_usd: number };
export type DeskRead = {
  state: "ok" | "hidden" | "budget" | "error" | "none"; text?: string; at?: number; expires_at?: number; age_s?: number; cached?: boolean;
  cost_usd?: number; message?: string; today?: DeskReadToday | null;
};
export async function getDeskRead(symbol: string, refresh = false, signal?: AbortSignal, keptOnly = false): Promise<DeskRead> {
  const response = await fetch(apiUrl("/copilot/desk/read"), { method: "POST", cache: "no-store", signal,
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbol, refresh, kept_only: keptOnly }) });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${response.status}).`);
  return body as DeskRead;
}

// --------------------------------------------------------------------------- earnings on the book and Watching rows

/** One symbol's earnings tag (``desk_events.tag``): ``grey`` within ``window`` trading days, ``amber`` when a held option
 * expires on or after the report (``through``: those expiries). A symbol with no known date has no row. */
export type DeskEarningsTag = { symbol: string; date: string; status: string | null; trading_days: number; label: string;
  tone: "grey" | "amber"; through: string[] };
/** ``GET /copilot/desk/events``: ``loading`` says a calendar is still on its way, so read again shortly. */
export type DeskEvents = { state: "ok" | "unavailable"; today: string; window?: number; note?: string; rows: Record<string, DeskEarningsTag>; loading: boolean };

export async function getDeskEvents(symbols: string[], held: { symbol: string; expiry: string }[], signal?: AbortSignal): Promise<DeskEvents> {
  const query = new URLSearchParams({ symbols: symbols.join(","), held: held.map(h => `${h.symbol}:${h.expiry}`).join(",") });
  const response = await fetch(apiUrl(`/copilot/desk/events?${query}`), { cache: "no-store", signal });
  if (!response.ok) throw new Error(`Request failed (${response.status}).`);
  return await response.json() as DeskEvents;
}

// --------------------------------------------------------------------------- the Watching list

/** ``GET /copilot/desk/watching``: the watched symbols he follows (the app's watchlist, the Charts one, in its order),
 * each one's armed levels (a plan's entry or invalidation, or a chart alert) and a Radar setup card today, and the
 * Robinhood connection's state for the import. Prices come from the sparks read. */
export type DeskWatching = {
  state: "ok" | "unavailable"; symbols: string[]; count?: number; max?: number;
  levels: Record<string, { price: number; role: "entry" | "invalidation" | null }[]>;
  setups: Record<string, { at: number | null; event_id: string }>;
  imported_at?: string | null; robinhood?: "ready" | "off" | "signed_out" | "expired" | "loading" | "unavailable" | "stale" | "ok";
};
/** His own Robinhood lists the import offers (one read, on his tap). */
export type WatchLists = { state: string; lists: { id: string; name: string; emoji: string; count: number; ticked: boolean }[]; not_offered: number };
export type WatchImported = { state: string; line?: string; added?: string[]; watching?: DeskWatching };

async function watchCall<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), { cache: "no-store", ...init, headers: init?.body ? { "Content-Type": "application/json" } : undefined });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${response.status}).`);
  return body as T;
}
export const getWatching = (signal?: AbortSignal) => watchCall<DeskWatching>("/copilot/desk/watching", { signal });
export const watchSymbol = (symbol: string) => watchCall<DeskWatching>("/copilot/desk/watching", { method: "POST", body: JSON.stringify({ symbol }) });
export const stopWatching = (symbol: string) => watchCall<DeskWatching>(`/copilot/desk/watching/${encodeURIComponent(symbol)}`, { method: "DELETE" });
export const getWatchLists = () => watchCall<WatchLists>("/copilot/desk/watching/robinhood");
export const importWatchLists = (lists: string[]) => watchCall<WatchImported>("/copilot/desk/watching/robinhood", { method: "POST", body: JSON.stringify({ lists }) });

// --------------------------------------------------------------------------- the cockpit's Needs-you strip

/** One thing waiting on the owner's decision now, for the strip: ``rank`` is its place in the strip's order
 * (``deskNeeds``); ``at`` (epoch seconds) is when it started, when known. */
export type DeskNeedKind = "alert" | "level" | "card" | "expiring" | "fill";
export type DeskNeed = { key: string; kind: DeskNeedKind; rank: number; symbol: string | null; title: string; detail: string | null;
  row: DeskThread | null; at: number | null };

/** Days from ``day`` (YYYY-MM-DD) to ``iso`` (YYYY-MM-DD), by the calendar. */
export const daysTo = (iso: string, day: string) => Math.round((Date.parse(`${iso}T12:00:00Z`) - Date.parse(`${day}T12:00:00Z`)) / 86_400_000);
export const money = (value: number) => `${value > 0 ? "+" : value < 0 ? "−" : ""}$${Math.abs(value).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
export const signedPct = (value: number, digits = 0) => `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(digits)}%`;

/** A position alert's kind in the strip's words; an expiry alert is the strip's expiring item instead. */
const ALERT_WORDS: Record<string, string> = { giveback: "give-back alert", wrong_way: "wrong-way alert", hold_hour: "held-an-hour alert" };
const EXPIRY_ALERTS = new Set(["expiry_first", "expiry_final", "expiry_eve"]);
const nyClock = (seconds: number) => new Date(seconds * 1000).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });

/**
 * What needs a decision now, in the strip's documented order (docs/copilot-lab.md § The Needs-you strip), followed
 * tickers only. Nothing else may appear: never "no plan" on its own, a plan offer, an expiry later than today, Close the
 * day or a rating.
 * 1. a position alert that fired today and is not yet answered (give-back, wrong way, held an hour; ``alerts``, the
 *    session read's; a rating on the phone or the desk counts as the decision);
 * 2. a confirmed plan's level reached: a position past its invalidation, or an armed plan whose entry or invalidation
 *    was hit today (``plans``); or a card waiting for Confirm or Dismiss;
 * 3. before the close, an option that expires today, with or without a plan (after 16:00 it has expired);
 * 4. before the close, the fills waiting to link to a plan (one item).
 * Within a rank the thread list's order holds. An item about a ticker the owner opened today (``opened``: symbol to
 * epoch seconds of the latest open) clears itself: an alert or a level hit before that open, anything else for the day.
 */
export function deskNeeds({ rows, alerts = [], plans = [], day, closing, fills, opened = {} }: {
  rows: DeskThread[]; alerts?: DeskAlertToAnswer[]; plans?: DeskPlan[]; day: string; closing: boolean; fills: number;
  opened?: Readonly<Record<string, number>>;
}): DeskNeed[] {
  const followed = rows.filter(r => r.symbol && !r.hidden && r.group !== "pinned" && !r.key.startsWith("radar:"));
  const hidden = new Set(rows.filter(r => r.hidden && r.symbol).map(r => r.symbol!));
  const needs: DeskNeed[] = [];
  const seen = new Set<string>();
  const cleared = (need: DeskNeed) => {
    const at = need.symbol ? opened[need.symbol] : undefined;
    return at !== undefined && (need.at === null || need.at <= at);
  };
  const add = (need: DeskNeed) => { if (!seen.has(need.key) && !cleared(need)) { seen.add(need.key); needs.push(need); } };
  const positionOf = (symbol: string, tradeId?: string) =>
    followed.find(r => tradeId && r.key === `trade:${tradeId}`) ?? followed.find(r => r.symbol === symbol && r.book) ?? followed.find(r => r.symbol === symbol) ?? null;
  for (const alert of alerts) {
    if (!alert.today || alert.feedback || EXPIRY_ALERTS.has(alert.kind) || hidden.has(alert.symbol)) continue; // answered: decided
    const row = positionOf(alert.symbol, alert.trade_id);
    if (!row) continue; // no longer held, or a ticker not followed
    add({ key: `alert:${alert.id}`, kind: "alert", rank: 1, symbol: alert.symbol, row, at: alert.at,
      title: `${alert.contract}: ${ALERT_WORDS[alert.kind] ?? "position alert"} at ${nyClock(alert.at)}`, detail: null });
  }
  for (const row of followed.filter(r => r.book?.state === "past_stop"))
    add({ key: `level:${row.key}`, kind: "level", rank: 2, symbol: row.symbol, row, at: null, title: `${row.title}: past its invalidation`, detail: null });
  for (const plan of plans.filter(p => p.stage === "armed" && !hidden.has(p.symbol) && followed.some(r => r.symbol === p.symbol))) {
    for (const [role, level] of [["entry", plan.entry], ["invalidation", plan.invalidation]] as const) {
      if (level?.state !== "hit" || !level.hit_at || nyDay(new Date(level.hit_at * 1000)) !== day) continue;
      const row = followed.find(r => r.investigationId === plan.investigationId) ?? positionOf(plan.symbol);
      add({ key: `level:plan:${plan.investigationId ?? plan.symbol}:${role}`, kind: "level", rank: 2, symbol: plan.symbol, row, at: level.hit_at,
        title: `${plan.symbol} plan: ${role} ${level.price.toFixed(2)} reached at ${nyClock(level.hit_at)}`, detail: plan.thesis });
    }
  }
  for (const row of followed.filter(r => r.group === "draft"))
    add({ key: `card:${row.key}`, kind: "card", rank: 2, symbol: row.symbol, row, at: null, title: `${row.symbol}: a card to confirm or dismiss`, detail: row.status.text });
  for (const row of followed) {
    if (closing || !row.book?.expiry || row.instrument === "stock" || daysTo(row.book.expiry, day) !== 0) continue;
    add({ key: `expiring:${row.key}`, kind: "expiring", rank: 3, symbol: row.symbol, row, at: null, title: `${row.title} expires today`, detail: null });
  }
  if (!closing && fills > 0)
    add({ key: `fills:${fills}`, kind: "fill", rank: 4, symbol: null, row: null, at: null, title: `${fills} fill${fills === 1 ? "" : "s"} to link to a plan`, detail: null });
  return needs.sort((a, b) => a.rank - b.rank);
}

/** The tickers the owner opened today (a book row, the strip, a thread or a position's desk view), in this browser:
 * symbol to epoch seconds of the latest open. An open clears that ticker's strip items (``deskNeeds``). */
const OPENED_KEY = "desk.opened.v1";
export function readOpened(day: string): Record<string, number> {
  try {
    const saved = JSON.parse(window.localStorage.getItem(OPENED_KEY) ?? "null");
    return saved?.day === day && saved.at && typeof saved.at === "object" ? saved.at : {};
  } catch { return {}; }
}
export function saveOpened(day: string, symbol: string, at = Math.floor(Date.now() / 1000)): Record<string, number> {
  const next = { ...readOpened(day), [symbol]: at };
  try { window.localStorage.setItem(OPENED_KEY, JSON.stringify({ day, at: next })); } catch { /* this visit only */ }
  return next;
}

/** What the desk looked like when the owner last left it, for "Since you looked" (this browser only), by position (the
 * row's key), so two contracts on one ticker stay apart. */
export type DeskLook = { at: number; pnl: Record<string, number>; contracts: Record<string, string> };
const LOOK_KEY = "desk.looked.v2";
export function readLook(): DeskLook | null {
  try {
    const saved = JSON.parse(window.localStorage.getItem(LOOK_KEY) ?? "null");
    return saved && typeof saved.at === "number" && saved.pnl ? saved as DeskLook : null;
  } catch { return null; }
}
export function saveLook(look: DeskLook) {
  try { window.localStorage.setItem(LOOK_KEY, JSON.stringify(look)); } catch { /* this visit only */ }
}

/**
 * "Since you looked": at most ``max`` lines, comparing the followed positions now with ``look`` (by symbol) and counting
 * today's fills, pings and Radar events after it (a ticker not followed counts in none). Each P&L move is the change
 * since then (the book row has the P&L now), biggest first (a move under $25 and 10% is left out); a position opened or
 * closed since says so; the counts close the list.
 */
export function sinceLines(look: DeskLook, rows: DeskThread[], events: DeskSessionEvent[], max = 4): string[] {
  const now = new Map(rows.filter(r => r.book && r.symbol && !r.hidden && !r.key.startsWith("robinhood:")).map(r => [r.key, r]));
  const lines: { weight: number; text: string }[] = [];
  for (const [key, row] of now) {
    const usd = row.book!.usd;
    if (!(key in look.pnl)) lines.push({ weight: 1e9, text: `${row.title} opened` });
    else if (usd !== null) {
      const was = look.pnl[key];
      const moved = Math.abs(usd - was);
      if (moved >= 25 && moved >= Math.abs(was) * 0.1) lines.push({ weight: moved, text: `${row.title} ${money(usd - was)}` });
    }
  }
  for (const key of Object.keys(look.pnl)) if (!now.has(key) && !rows.some(r => r.key === key && r.hidden))
    lines.push({ weight: 1e9 - 1, text: `${look.contracts[key] ?? "A position"} closed` });
  const hidden = new Set(rows.filter(r => r.hidden && r.symbol).map(r => r.symbol));
  const after = events.filter(e => e.at > look.at && !(e.symbol && hidden.has(e.symbol)));
  const count = (kind: DeskSessionEvent["kind"], one: string, many: string) => {
    const n = after.filter(e => e.kind === kind).length;
    return n ? `${n} ${n === 1 ? one : many}` : null;
  };
  const counts = [count("fill", "fill", "fills"), count("ping", "ping", "pings"), count("radar", "Radar event", "Radar events")].filter(Boolean);
  const top = lines.sort((a, b) => b.weight - a.weight).map(l => l.text).slice(0, counts.length ? max - 1 : max);
  return counts.length ? [...top, counts.join(" · ")] : top;
}
