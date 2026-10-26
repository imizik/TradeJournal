import type { PriceLevel } from "./charts";
import type { Drawing } from "./drawings";
import { CONTEXT_MAX, type DrawnPlan } from "./copilot";

/**
 * Draw the plan: the owner's drawn price levels become a copilot plan's entry trigger and invalidation. A saved level,
 * a horizontal ray or a zone counts (a zone by its edge nearest the price); a trend line or a note does not.
 */
export type PlanSource = { id: string; kind: "level" | "ray" | "zone"; price: number; name: string | null; edge?: "upper" | "lower" };
/** Two drawn levels (`trigger` set) or one, the invalidation, with the copilot drafting the trigger. */
export type PlanPair = { side: "long" | "short"; trigger: PlanSource | null; invalidation: PlanSource };

const cents = (value: number) => Math.round(value * 100) / 100;
/** A level's default name ("Level 3") says nothing about it, so it is left out of the message. */
const DEFAULT_LABEL = /^Level \d+$/;

/** One level or drawing as a plan price, at the price the chart shows it; null for what has no single price. */
export function planSource(item: PriceLevel | Drawing, last: number | null): PlanSource | null {
  if (!("kind" in item)) return { id: item.id, kind: "level", price: cents(item.price), name: DEFAULT_LABEL.test(item.label) ? null : item.label };
  if (item.kind === "ray") return { id: item.id, kind: "ray", price: cents(item.points[0].price), name: null };
  if (item.kind !== "zone") return null;
  const [low, high] = [Math.min(item.points[0].price, item.points[1].price), Math.max(item.points[0].price, item.points[1].price)];
  // With no price to measure from, the upper edge.
  const upper = last === null || Math.abs(high - last) <= Math.abs(low - last);
  return { id: item.id, kind: "zone", price: cents(upper ? high : low), name: null, edge: upper ? "upper" : "lower" };
}

/**
 * Which drawn level is the trigger and which the invalidation, from the last price: the one nearer the price is the
 * trigger, so both below is a long off support, both above a short into resistance, and a pair around the price
 * breaks toward its nearer side. A long's trigger is above its invalidation; a short's below. `swap` trades the roles.
 * One level is the invalidation: below the price a long, above it a short. Null when two levels share a price.
 */
export function pairLevels(a: PlanSource, b: PlanSource | null, last: number | null, swap = false): PlanPair | null {
  if (!b) return { side: last !== null && a.price > last ? "short" : "long", trigger: null, invalidation: a };
  if (a.price === b.price) return null;
  const [upper, lower] = a.price > b.price ? [a, b] : [b, a];
  // A tie, or no price, reads as a long breakout.
  const upperNearer = last === null || Math.abs(upper.price - last) <= Math.abs(lower.price - last);
  const long = upperNearer !== swap;
  return long ? { side: "long", trigger: upper, invalidation: lower } : { side: "short", trigger: lower, invalidation: upper };
}

/** The structured form the copilot's plan card compares its draft with. */
export const drawnPlan = (pair: PlanPair): DrawnPlan => ({ side: pair.side, trigger: pair.trigger?.price ?? null, invalidation: pair.invalidation.price });

function where(source: PlanSource) {
  if (source.kind === "zone") return `the ${source.edge} edge of my drawn zone`;
  return source.name ? `my drawn level "${source.name.replace(/"/g, "'")}"` : "my drawn level";
}

/**
 * The owner's message, prefilled and unsent: "Plan a trade: NBIS from the 5m chart, last 94.35. Entry trigger 95.90
 * (my drawn level "Prior day low"). Invalidation 92.30 (my drawn level). Draft the plan around these levels; argue if
 * they are wrong." Cut to the deep link's limit.
 */
export function planMessage(symbol: string, interval: string, last: number | null, pair: PlanPair): string {
  const head = `Plan a trade: ${symbol} from the ${interval} chart${last === null ? "" : `, last ${last.toFixed(2)}`}.`;
  const body = pair.trigger
    ? `Entry trigger ${pair.trigger.price.toFixed(2)} (${where(pair.trigger)}). Invalidation ${pair.invalidation.price.toFixed(2)} (${where(pair.invalidation)}). Draft the plan around these levels; argue if they are wrong.`
    : `Invalidation ${pair.invalidation.price.toFixed(2)} (${where(pair.invalidation)}), a ${pair.side}. Draft the entry trigger and the plan around it; argue if it is wrong.`;
  return `${head} ${body}`.slice(0, CONTEXT_MAX);
}

/** "Long · entry 95.90 · invalidation 92.30", what the chip and the menu say they will send. */
export const pairText = (pair: PlanPair) =>
  `${pair.side === "long" ? "Long" : "Short"}${pair.trigger ? ` · entry ${pair.trigger.price.toFixed(2)}` : ""} · invalidation ${pair.invalidation.price.toFixed(2)}`;
