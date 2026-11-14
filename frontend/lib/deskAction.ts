import { DESK_TIMEFRAMES, stopWatching, watchSymbol, type DeskTimeframe } from "@/lib/desk";
import { createAlert, rearmAlert } from "@/lib/alerts";
import { freshQuote, listAlerts as listAllAlerts } from "@/lib/copilot";
import { isDebit } from "@/lib/spreadTicket";
import { closeNowTicket, type CloseNowTicket } from "@/lib/closingTicket";
import { addDeskNote, NOTE_SAVED_EVENT } from "@/lib/deskNotes";
import { tickFor, type DeskTicks } from "@/lib/deskTicks";
import type { DeskBook, DeskThread } from "@/lib/desk";

/**
 * The copilot's desk actions (docs/copilot-lab.md § Desk actions). The server's ``desk_action`` checked the request
 * against the desk and sent this card; nothing has happened yet. A view change (``show``) is applied when the card
 * arrives, with Undo; every other card waits for the owner's tap, which calls the desk's own route, the one the same
 * action by hand calls (alerts, the Watching list, the chart settings' levels, the Ticket tab, a plan's stop alert).
 * The ticket stays copy-only: nothing here places, stages or sends an order, and nothing reaches Robinhood.
 *
 * On a position he holds: ``close`` and ``trim`` open the Ticket tab's closing view at the mark now (``closeNowTicket``,
 * from the desk's own book row), ``note`` saves his note through the book row's pen route, and ``plan_idea`` follows
 * today's Radar setup card's own Plan it link, as the Feed's and the Scanner's Plan it do.
 */

export type DeskTab = "chart" | "chain" | "tape";
export type DeskAction = { made_at: number } & (
  | { action: "show"; symbol: string; timeframe: DeskTimeframe | null; tab: DeskTab }
  | { action: "alert"; symbol: string; price: number; side: "above" | "below"; label: string | null; last: number; as_of?: string | number | null }
  | { action: "watch" | "unwatch"; symbol: string }
  | { action: "draw"; symbol: string; price: number; label: string | null; last: number; as_of?: string | number | null }
  | { action: "ticket"; symbol: string; expiry: string; strike: number; option_type: "call" | "put"; investigation_id: string;
      /** A vertical spread's sold leg (``strike`` is the leg bought), same expiry and type. */
      short_strike?: number }
  | { action: "plan_stop"; symbol: string; price: number; was: number; investigation_id: string; alert_id: string;
      direction: "long" | "short"; last: number; as_of?: string | number | null }
  /** A position he holds (``copilot_actions._held_card``): its legs (the bought one first), ``contract`` in words, the
   * contracts held, sold and left, its P&L and what the sale brings in at the mark (null without Robinhood's numbers). */
  | ({ action: "close" | "trim"; symbol: string; legs: CardLeg[]; contract: string; held: number; contracts: number; remains: number;
      mark: number | null; proceeds: number | null; usd: number | null; quantity?: number; half?: boolean } & ContractPick)
  | ({ action: "note"; symbol: string; legs: CardLeg[]; contract: string; text: string } & ContractPick)
  /** Today's Radar setup card in ``symbol`` (a Scanner pick plans from it too). */
  | { action: "plan_idea"; symbol: string; direction: "long" | "short"; event_id: string; words: string; levels_line: string });
export type CardLeg = { trade_id: string | null; instrument: "option" | "stock"; direction: "long" | "short"; side: "call" | "put" | null;
  strike: number | null; expiry: string | null };
type ContractPick = { option_type?: "call" | "put"; strike?: number; expiry?: string };

/** A card older than this asks again rather than acting. */
export const STALE_AFTER_S = 24 * 3600;
/** A price card whose ticker has moved more than this since the card was made asks again. */
export const MOVED_PCT = 5;
export const ALERT_LABEL = "Set from the copilot";
const money = (value: number) => value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** What the card will do, in one line (the server's ``copilot_actions.line``): "Set alert: NBIS below 98.00". */
export function actionLine(card: DeskAction): string {
  switch (card.action) {
    case "show": return `Show ${card.symbol}${card.timeframe ? ` · ${card.timeframe}` : ""}${card.tab === "chain" ? " · Chain" : card.tab === "tape" ? " · Tape" : ""}`;
    case "alert": return `Set alert: ${card.symbol} ${card.side} ${money(card.price)}`;
    case "watch": return `Watch ${card.symbol}`;
    case "unwatch": return `Stop watching ${card.symbol}`;
    case "draw": return `Draw ${money(card.price)} on ${card.symbol}${card.label ? ` · ${card.label}` : ""}`;
    case "ticket": {
      const day = new Date(`${card.expiry}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric" });
      if (card.short_strike != null) {
        const low = Math.min(card.strike, card.short_strike), high = Math.max(card.strike, card.short_strike);
        return `Open ticket: ${card.symbol} ${low}/${high} ${card.option_type} ${isDebit(card.option_type, card.strike, card.short_strike) ? "debit" : "credit"} spread ${day}`;
      }
      return `Open ticket: ${card.symbol} ${card.strike} ${card.option_type} ${day}`;
    }
    case "plan_stop": return `Update plan: ${card.symbol} stop ${money(card.was)} → ${money(card.price)}`;
    case "close": return `Close ${card.symbol} ${card.contract} · all ${card.held}`;
    case "trim": return `Trim ${card.symbol} ${card.contract} · sell ${card.contracts} of ${card.held}, ${card.remains} left`;
    case "note": return `Note on ${card.symbol} ${card.contract}: ${card.text}`;
    case "plan_idea": return `Plan it: ${card.symbol} ${card.words}`;
  }
}

/** Dollars, signed when asked: "+$420", "−$63", "$1,230"; cents under $10 ("$4.50"), never one decimal. */
export function dollars(value: number, signed = false): string {
  const cents = Math.abs(value) < 10;
  const text = `$${Math.abs(value).toLocaleString("en-US", { minimumFractionDigits: cents ? 2 : 0, maximumFractionDigits: cents ? 2 : 0 })}`;
  return value < 0 ? `−${text}` : signed && value > 0 ? `+${text}` : text;
}

/** A position card's numbers as the desk's position data gave them when it was made: its P&L, and what the sale
 * brings in (or costs) at the mark. Null when the card has none (a position only the journal shows reads no mark). */
export function heldFacts(card: DeskAction): string | null {
  if (card.action !== "close" && card.action !== "trim") return null;
  const parts = [card.usd !== null ? `P&L ${dollars(card.usd, true)}` : null,
    card.proceeds !== null ? `${card.proceeds < 0 ? "costs about" : "about"} ${dollars(Math.abs(card.proceeds))} to ${card.action === "trim" ? `sell ${card.contracts}` : "close"} at the mark` : null]
    .filter(Boolean);
  return parts.length ? `${parts.join(" · ")}. The ticket reads the mark again when you tap.` : "The ticket reads the mark when you tap.";
}

/** The tap's verb. */
export function actionVerb(card: DeskAction): string {
  return { show: "Show it", alert: "Set it", watch: "Add", unwatch: "Remove", draw: "Draw", ticket: "Open ticket", plan_stop: "Update plan",
    close: "Open ticket", trim: "Open ticket", note: "Save note", plan_idea: "Plan it" }[card.action];
}

/** Why the card should not act now (it is a day old), or null. A price check needs a fresh quote and runs at the tap. */
export function staleByAge(card: DeskAction, nowS: number): string | null {
  return nowS - card.made_at > STALE_AFTER_S ? "This card is more than a day old, so it does not act. Ask again for a fresh one." : null;
}

/** Why a price card should not act at ``last`` (the ticker moved far since the card, or the level is now on the other
 * side), or null. */
export function staleByPrice(card: DeskAction, last: number): string | null {
  if (!("last" in card)) return null;
  const moved = Math.abs(last / card.last - 1) * 100;
  if (moved > MOVED_PCT) return `${card.symbol} has moved from ${money(card.last)} to ${money(last)} since this card, so it does not act. Ask again.`;
  if (card.action === "alert" && (card.side === "below" ? last <= card.price : last >= card.price))
    return `${card.symbol} is at ${money(last)}, already ${card.side} ${money(card.price)}. Ask again.`;
  if (card.action === "plan_stop" && (card.direction === "long" ? last <= card.price : last >= card.price))
    return `${card.symbol} is at ${money(last)}, already past a stop at ${money(card.price)}. Ask again.`;
  return null;
}

// --------------------------------------------------------------------------- the desk's view

/** Asks the desk page for its book rows of a card's position (``detail.rows``, one per leg, null where the book has none
 * now), or to follow a link in place (``detail.href``). Nobody cancelling means there is no desk on this page. */
export const DESK_POSITION_EVENT = "tradejournal:desk-position";
export const DESK_GO_EVENT = "tradejournal:desk-go";
export type PositionDetail = { symbol: string; legs: CardLeg[]; rows: (DeskThread | null)[] | null };

/** The book row that holds ``leg``: its journal trade's row, or for a position only Robinhood shows, its own row by
 * contract and side. Null when the book does not show it now. */
export function rowForLeg(rows: readonly DeskThread[], symbol: string, leg: CardLeg): DeskThread | null {
  if (leg.trade_id) return rows.find(r => r.book && (r.key === `trade:${leg.trade_id}` || r.tradeId === leg.trade_id)) ?? null;
  const same = rows.filter(r => r.book && r.key.startsWith("robinhood:") && r.symbol === symbol && r.book.option
    && r.book.option.side === leg.side && r.book.option.strike === leg.strike && r.book.option.expiry === leg.expiry
    && r.book.option.direction === leg.direction);
  return same.length === 1 ? same[0] : null;
}

/** What a held leg is worth now, the whole leg, by the positions' own formula: a fresh tick, else the book's mark, else
 * its cost and P&L (a short leg's P&L is its cost less its worth). With whether it came from a fresh tick. */
export function legWorth(book: DeskBook | undefined, ticks: DeskTicks): { worth: number | null; live: boolean } {
  const tick = book?.tick;
  const now = tick ? tickFor(ticks, tick.quote) : null;
  if (tick && now && !now.stale) return { worth: now.last * tick.scale * tick.quantity, live: true };
  const quantity = book?.quantity ?? tick?.quantity ?? book?.option?.quantity ?? null;
  if (book?.mark != null && quantity) return { worth: book.mark * quantity, live: false };
  if (tick && now) return { worth: now.last * tick.scale * tick.quantity, live: false };
  const cost = tick?.cost ?? book?.option?.cost ?? null;
  const sign = tick?.sign ?? (book?.option?.direction === "short" ? -1 : 1);
  return { worth: book?.usd != null && cost != null && quantity ? cost * quantity + sign * book.usd : null, live: false };
}

/** Asks the desk page to show a ticker, a tab, a timeframe or the Tape. A listener fills ``was`` with what it showed
 * before (for Undo) and cancels the event; nobody cancelling means there is no desk on this page. */
export const DESK_VIEW_EVENT = "tradejournal:desk-view";
/** The desk's lists changed by a card's tap (the Watching list, alerts, levels): read them again now. */
export const DESK_CHANGED_EVENT = "tradejournal:desk-changed";
export type CentreTab = "chart" | "grid" | "chain" | "check" | "ticket";
export type DeskView = { symbol?: string | null; tab?: CentreTab; timeframe?: DeskTimeframe; tape?: boolean; reveal?: boolean };
type ViewDetail = DeskView & { was: DeskView };

export const DESK_TIMEFRAME_KEY = "desk.chart.timeframe.v1";
export const DESK_TAPE_KEY = "desk.tape.v1";

function stored(storage: "session" | "local", key: string): string | null {
  try { return (storage === "session" ? window.sessionStorage : window.localStorage).getItem(key); } catch { return null; }
}
function store(storage: "session" | "local", key: string, value: string) {
  try { (storage === "session" ? window.sessionStorage : window.localStorage).setItem(key, value); } catch { /* this view only */ }
}

/** Shows ``view`` on the desk: the timeframe and the Tape are written where the chart reads them (so a chart that mounts
 * later opens on them), and the page's listeners move the centre. Returns what was shown before, or null when no desk
 * is on this page (nothing changed). */
export function showOnDesk(view: DeskView): DeskView | null {
  const detail: ViewDetail = { ...view, was: {} };
  const handled = !window.dispatchEvent(new CustomEvent(DESK_VIEW_EVENT, { detail, cancelable: true }));
  if (!handled) return null;
  if (view.timeframe) {
    const before = stored("session", DESK_TIMEFRAME_KEY);
    detail.was.timeframe = (DESK_TIMEFRAMES as readonly string[]).includes(before ?? "") ? before as DeskTimeframe : "2m";
    store("session", DESK_TIMEFRAME_KEY, view.timeframe);
  }
  if (view.tape !== undefined) {
    detail.was.tape = stored("local", DESK_TAPE_KEY) === "open";
    store("local", DESK_TAPE_KEY, view.tape ? "open" : "closed");
  }
  // The chart's own hooks follow what was just written.
  window.dispatchEvent(new CustomEvent(DESK_CHANGED_EVENT, { detail: { timeframe: view.timeframe, tape: view.tape } }));
  return detail.was;
}

/** The view a show card asks for. */
export function viewOf(card: Extract<DeskAction, { action: "show" }>): DeskView {
  return { symbol: card.symbol, tab: card.tab === "chain" ? "chain" : "chart", ...(card.timeframe ? { timeframe: card.timeframe } : {}),
    ...(card.tab === "tape" ? { tape: true } : {}) };
}

/** The show cards applied in this tab (by card id) and what each replaced, for Undo; a reopened conversation's cards are
 * not here, so they are never applied again by themselves. */
const shownHere = new Map<string, DeskView>();
/** Cards that arrived in this tab's stream: a show card among them applies itself once. */
const arrivedHere = new Set<string>();
export const markArrived = (id: string) => { arrivedHere.add(id); };
export const arrived = (id: string) => arrivedHere.has(id);
export const undoFor = (id: string) => shownHere.get(id) ?? null;
export function applyShow(id: string, card: Extract<DeskAction, { action: "show" }>): boolean {
  if (shownHere.has(id)) return true;
  const was = showOnDesk(viewOf(card));
  if (was) shownHere.set(id, was);
  return !!was;
}
export function undoShow(id: string): boolean {
  const was = shownHere.get(id);
  if (!was) return false;
  showOnDesk(was);
  shownHere.delete(id);
  return true;
}

// --------------------------------------------------------------------------- the taps

export type Done = { text: string; symbol?: string };

const changed = () => window.dispatchEvent(new CustomEvent(DESK_CHANGED_EVENT, { detail: {} }));

async function liveLast(symbol: string): Promise<number> {
  const quote = await freshQuote(symbol);
  if (!quote.fresh || quote.last === null) throw new Error(`The latest ${symbol} quote is stale or missing, so nothing was done. Try again in a minute.`);
  return quote.last;
}

/** Thrown when the card no longer fits the desk: the card says so and asks again instead of acting. */
export class Stale extends Error {}

/** A close or trim card's ticket from the desk's book as it is now, or why there is none. ``rows`` the desk's rows for
 * the card's legs (``DESK_POSITION_EVENT``), ``ticks`` its live prices. Throws ``Stale`` when he no longer holds what the
 * card was made for. */
export function ticketFromBook(card: Extract<DeskAction, { action: "close" | "trim" }>, rows: (DeskThread | null)[], ticks: DeskTicks): CloseNowTicket {
  if (rows.length !== card.legs.length || rows.some(r => !r?.book?.option))
    throw new Stale(`The desk's book does not show your ${card.symbol} ${card.contract} now, so no ticket was opened. Ask again.`);
  const books = rows.map(r => r!.book!);
  const held = books[0].quantity ?? books[0].option!.quantity;
  if (held !== card.held || books.some(b => (b.quantity ?? b.option!.quantity) !== held))
    throw new Stale(`You hold ${held ?? "an unknown number of"} ${card.symbol} ${card.contract} now, not ${card.held}. Ask again.`);
  const legs = books.map(b => { const w = legWorth(b, ticks); return { terms: { ...b.option!, quantity: held }, worth: w.worth, markLive: w.live }; });
  const account = books[0].account ? `${books[0].account.label}${books[0].account.masked ? ` ${books[0].account.masked}` : ""}` : null;
  const ticket = closeNowTicket({ symbol: card.symbol, legs, account, contracts: card.contracts });
  if (!ticket) throw new Error(`The desk has no mark for your ${card.symbol} ${card.contract} right now, so no ticket was opened. Try again in a minute.`);
  return ticket;
}

/** Brings the desk's centre forward where the copilot covers it (a phone's sheet, the sheet layout below 1180 px), with
 * nothing else changed: the ticket a card just opened is in view. */
export function revealCentre() {
  const detail: DeskView & { was: DeskView } = { reveal: true, was: {} };
  window.dispatchEvent(new CustomEvent(DESK_VIEW_EVENT, { detail, cancelable: true }));
}

/** What a close or trim card says once its ticket is open. */
export function ticketDone(t: CloseNowTicket): string {
  const what = t.contracts === t.held ? `all ${t.held}` : `${t.contracts} of ${t.held} (${t.remains} left)`;
  const price = `${t.credit ? "" : "a debit of "}${t.limit.toFixed(2)}`;
  return `Ticket open on the desk: close ${what} at about ${price}${t.markLive ? "" : " (the book's last mark)"}. Copy it into Robinhood; nothing is sent from here.`;
}

/** The tap for every card but ``show`` and ``draw`` (a level is drawn by ``DrawLevel``, which needs the chart settings'
 * hook): the same route the action by hand calls. Throws ``Stale`` or an Error with the reason in plain words. */
export async function runAction(card: DeskAction, nowS: number): Promise<Done> {
  const old = staleByAge(card, nowS);
  if (old) throw new Stale(old);
  switch (card.action) {
    case "alert": {
      const last = await liveLast(card.symbol);
      const moved = staleByPrice(card, last);
      if (moved) throw new Stale(moved);
      // As the desk chart's own "Alert here": an ordinary level alert, which way it waits judged from the price now.
      await createAlert({ symbol: card.symbol, price: card.price, reference: last, condition: "crosses", interval: null, session: "regular",
        source_kind: "level", source_id: "desk", label: card.label ?? ALERT_LABEL });
      changed();
      return { text: `Alert set: ${card.symbol} crosses ${card.side} ${money(card.price)}, regular hours.`, symbol: card.symbol };
    }
    case "watch":
      await watchSymbol(card.symbol);
      changed();
      return { text: `Added ${card.symbol} to Watching.`, symbol: card.symbol };
    case "unwatch":
      await stopWatching(card.symbol);
      changed();
      return { text: `${card.symbol} is off Watching.` };
    case "ticket": {
      const { openTicket } = await import("@/components/copilot/DeskTicket");
      // As the Chain's Put on ticket (and its spread): the plan's ticket with this contract or vertical, copy-only.
      openTicket(card.investigation_id, { expiry: card.expiry, strike: card.strike,
        ...(card.short_strike != null ? { short: card.short_strike, kind: card.option_type } : {}) });
      return { text: "Ticket open on the desk: copy it into Robinhood. Nothing is sent from here." };
    }
    case "plan_stop": {
      // The plan as it is now: its stop alert must still be the one the card was made for, at the price it read.
      const now = (await listAllAlerts()).alerts.find(a => a.id === card.alert_id);
      if (!now) throw new Stale("That plan's stop alert is gone, so nothing was changed. Ask again.");
      if (Math.abs(now.price - card.was) >= 0.005) throw new Stale(`The plan's stop is ${money(now.price)} now, not ${money(card.was)}. Ask again.`);
      const last = await liveLast(card.symbol);
      const moved = staleByPrice(card, last);
      if (moved) throw new Stale(moved);
      // The plan's own stop alert armed at the new price, as the desk's Move does for an alert.
      await rearmAlert(card.alert_id, card.price, last);
      changed();
      return { text: `Plan updated: ${card.symbol} stop ${money(card.price)} (was ${money(card.was)}).`, symbol: card.symbol };
    }
    case "note": {
      // As the book row's pen: the note saved with the journal trade, and the desk's book shows it at once.
      const saved = await addDeskNote({ trade_id: card.legs[0].trade_id! }, card.text);
      window.dispatchEvent(new CustomEvent(NOTE_SAVED_EVENT, { detail: saved }));
      return { text: `Saved on your ${card.symbol} ${card.contract}: “${saved.note.text}”. It shows under the position on the desk.`, symbol: card.symbol };
    }
    case "plan_idea": {
      // As the Feed's and the Scanner's Plan it: today's setup card opens on the desk, its plan for him to confirm there.
      const href = `/copilot-lab?${new URLSearchParams({ symbol: card.symbol, radar: card.event_id })}`;
      if (window.dispatchEvent(new CustomEvent(DESK_GO_EVENT, { detail: { href }, cancelable: true }))) window.location.assign(href);
      return { text: `The ${card.symbol} setup card is open: confirm the plan there. Nothing is saved until you do.`, symbol: card.symbol };
    }
    default:
      throw new Error("This card is not tapped here.");
  }
}
