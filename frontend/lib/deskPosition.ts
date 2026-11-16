/**
 * The desk's Position panel (``components/copilot/DeskPosition.tsx``; docs/copilot-lab.md § Where a held option stands):
 * the small arithmetic behind its figures and buttons, and its two saves. Every ticket it opens is the existing one
 * (``closeNowTicket``, ``closingTicket``, the roll ticket): copy-only, nothing is sent to Robinhood.
 *
 * - ``markNow``: a share's price now (an option's premium per share, as a quote shows it), from a live tick, else the
 *   book's mark (a contract's: premium x 100) over the shares a contract holds.
 * - ``planSide``: which way the plan's stock trade gains (its entry above its stop is long).
 * - ``levelsProblem``: why a new stop and target cannot be saved at the stock's price now (the stop on the losing side
 *   of the price, the target past the stop on the winning side), or null.
 * - ``panelCloseTicket``: the close-now ticket for some or all of the selected book row (a single long call or put).
 * - ``paperBreakEven``: a paper call's or put's break-even at expiry.
 * - ``savePlanLevels``: a real plan's stop moves through its own invalidation alert's rearm (the route the copilot's
 *   ``plan_stop`` card taps, at a fresh quote), then its target through ``PUT /copilot/plans/{id}/target``.
 */

import { apiUrl } from "@/lib/api";
import { rearmAlert } from "@/lib/alerts";
import { freshQuote, listAlerts } from "@/lib/copilot";
import { closeNowTicket, type CloseNowTicket } from "@/lib/closingTicket";
import { DESK_CHANGED_EVENT, legWorth } from "@/lib/deskAction";
import { tickFor, type DeskTicks } from "@/lib/deskTicks";
import type { DeskBook, DeskThread } from "@/lib/desk";

export type PlanSide = "long" | "short";

const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const price = (value: number) => value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** A share's price now and whether it is a live tick: the tick's last (already per share), else the book's mark (a
 * contract's for an option: the premium x 100) over ``tick.scale`` (100 a contract, 1 a share). Null without either. */
export function markNow(book: DeskBook | undefined, ticks: DeskTicks, now = Date.now() / 1000): { share: number; live: boolean } | null {
  const tick = book?.tick;
  const live = tick ? tickFor(ticks, tick.quote, now) : null;
  if (live && !live.stale) return { share: live.last, live: true };
  const scale = tick?.scale ?? (book?.option ? book.option.multiplier ?? 100 : 1);
  if (finite(book?.mark) && book.mark > 0 && finite(scale) && scale > 0) return { share: Math.round(book.mark / scale * 10000) / 10000, live: false };
  return live ? { share: live.last, live: false } : null;
}

/** Which way the plan's stock trade gains: an entry above the stop is long, below it short. Without both, the holding
 * says: a long call or long shares gain as the stock rises, a long put as it falls (a short option the other way). */
export function planSide(levels: { entry?: number | null; stop?: number | null }, holding: { option?: { side: string | null; direction: string | null } | null; sign?: number | null }): PlanSide | null {
  const { entry, stop } = levels;
  if (finite(entry) && finite(stop) && entry !== stop) return entry > stop ? "long" : "short";
  const o = holding.option;
  if (o && (o.side === "call" || o.side === "put") && (o.direction === "long" || o.direction === "short"))
    return (o.side === "call") === (o.direction === "long") ? "long" : "short";
  if (!o && (holding.sign === 1 || holding.sign === -1)) return holding.sign === 1 ? "long" : "short";
  return null;
}

/** Why ``stop`` and ``target`` (stock prices) cannot be saved with the stock at ``last``, or null. A long's stop sits
 * below the price and its target above the stop; a short's the other way round. ``target`` null: none. */
export function levelsProblem(side: PlanSide, last: number | null, stop: number | null, target: number | null): string | null {
  if (stop !== null && !(finite(stop) && stop > 0)) return "The stop must be a positive stock price.";
  if (target !== null && !(finite(target) && target > 0)) return "The target must be a positive stock price, or leave it blank.";
  const long = side === "long";
  if (stop !== null && finite(last) && last > 0 && (long ? stop >= last : stop <= last))
    return `The stock is at ${price(last)}: a ${long ? "long" : "short"} plan's stop goes ${long ? "below" : "above"} it.`;
  if (stop !== null && target !== null && (long ? target <= stop : target >= stop))
    return `A ${long ? "long" : "short"} plan's target goes ${long ? "above" : "below"} its stop.`;
  return null;
}

/** "Roth IRA ••8267": Robinhood's label and masked number, as the tickets name the account; null without them. */
export const accountWords = (book: DeskBook | undefined) => book?.account ? `${book.account.label}${book.account.masked ? ` ${book.account.masked}` : ""}` : null;

/** Contracts held by the selected row: Robinhood's count when matched, else the journal's. */
export const heldContracts = (book: DeskBook | undefined) => book?.quantity ?? book?.option?.quantity ?? null;

/** The close-now ticket for ``contracts`` of the selected row (a single long call or put), priced at the mark now from
 * the row's own worth (``legWorth``), as the copilot's close and trim cards price it; null when it cannot be honest. */
export function panelCloseTicket(row: DeskThread, ticks: DeskTicks, contracts: number): CloseNowTicket | null {
  const book = row.book;
  const held = heldContracts(book);
  if (!row.symbol || !book?.option || !finite(held)) return null;
  const worth = legWorth(book, ticks);
  return closeNowTicket({ symbol: row.symbol, legs: [{ terms: { ...book.option, quantity: held }, worth: worth.worth, markLive: worth.live }],
    account: accountWords(book), contracts });
}

/** A paper call's or put's break-even at expiry on the stock: the strike plus the premium paid a share for a call, less it
 * for a put (the open fill's ``per_share`` is signed cash, negative when paid). Null for shares, a spread or a credit. */
export function paperBreakEven(p: { instrument: string; option_type: string | null; per_share: number; legs: { action: string; strike: number | null }[] }): number | null {
  const [leg] = p.legs;
  if (p.instrument !== "option" || p.legs.length !== 1 || leg.action !== "buy" || !finite(leg.strike) || !finite(p.per_share) || p.per_share > 0) return null;
  const paid = -p.per_share;
  if (p.option_type === "call") return Math.round((leg.strike + paid) * 10000) / 10000;
  if (p.option_type === "put") return Math.round((leg.strike - paid) * 10000) / 10000;
  return null;
}

/** A real plan as the desk read it: its thread, its entry, its stop (its invalidation alert's price) and its target. */
export type PanelPlan = { investigationId: string; entry: number | null; stop: number | null; target: number | null };

/** The plan's invalidation alert, still at the stop the panel shows (as the ``plan_stop`` card checks): its id, or why
 * there is none. */
async function stopAlert(plan: PanelPlan): Promise<string> {
  const { alerts } = await listAlerts();
  // A plan role is only ever on a copilot plan's own alerts (``source_kind`` copilot), keyed by its thread.
  const found = alerts.find(a => a.plan_role === "invalidation" && a.source_id === plan.investigationId
    && plan.stop !== null && Math.abs(a.price - plan.stop) < 0.005);
  if (!found) throw new Error(`The plan's stop is not ${plan.stop !== null ? price(plan.stop) : "set"} any more, so nothing was changed. It shows again in a moment.`);
  return found.id;
}

async function putTarget(investigationId: string, target: number | null) {
  const response = await fetch(apiUrl(`/copilot/plans/${encodeURIComponent(investigationId)}/target`), {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ target }) });
  const reply = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof reply?.detail === "string" ? reply.detail : "The target was not saved. Try again.");
}

/** Saves a real plan's new stop and target: what changed only. The stop is the plan's invalidation alert armed again at
 * the new price from a fresh quote (as the copilot's ``plan_stop`` card does; refused on a stale quote or a stop already
 * past); the target is the plan card's price, a line with no alert. Returns what it said in words. */
export async function savePlanLevels({ symbol, plan, side, stop, target }: {
  symbol: string; plan: PanelPlan; side: PlanSide; stop: number | null; target: number | null;
}): Promise<{ text: string; stop: number | null; target: number | null }> {
  const stopMoved = stop !== null && (plan.stop === null || Math.abs(stop - plan.stop) >= 0.005);
  const targetMoved = target === null ? plan.target !== null : plan.target === null || Math.abs(target - plan.target) >= 0.005;
  if (!stopMoved && !targetMoved) return { text: "Nothing changed.", stop: plan.stop, target: plan.target };
  let last: number | null = null;
  let alertId: string | null = null;
  if (stopMoved) {
    alertId = await stopAlert(plan);
    const quote = await freshQuote(symbol);
    if (!quote.fresh || quote.last === null) throw new Error(`Moving the stop needs a live ${symbol} quote (its alert is armed from the price now), and there is none right now. Nothing was changed.`);
    last = quote.last;
  }
  const problem = levelsProblem(side, last, stop ?? plan.stop, target);
  if (problem) throw new Error(problem);
  const said: string[] = [];
  if (stopMoved) {
    await rearmAlert(alertId!, stop!, last!);
    said.push(`stop ${price(stop!)}${plan.stop !== null ? ` (was ${price(plan.stop)})` : ""}`);
  }
  let savedTarget = plan.target;
  let failed = "";
  if (targetMoved) {
    try {
      await putTarget(plan.investigationId, target);
      savedTarget = target;
      said.push(target === null ? "no target" : `target ${price(target)}${plan.target !== null ? ` (was ${price(plan.target)})` : ""}`);
    } catch (error) {
      if (!stopMoved) throw error;
      // The stop has already moved: say so, and why the target did not.
      failed = ` The target was not saved: ${error instanceof Error ? error.message : "try again"}`;
    }
  }
  window.dispatchEvent(new CustomEvent(DESK_CHANGED_EVENT, { detail: {} }));
  return { text: `Plan updated: ${symbol} ${said.join(", ")}.${failed}`, stop: stopMoved ? stop : plan.stop, target: savedTarget };
}
