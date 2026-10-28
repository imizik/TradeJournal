"use client";

import type { PlanBoardRow } from "@/lib/copilot";
import type { DeskPosition } from "@/lib/desk";
import { cn } from "@/lib/utils";

/*
 * The open thread's plan as one scale: invalidation on the left, the entry, then 1R and 2R past it, with the live price
 * marked. R is the entry-to-invalidation distance; plans have no target, so 1R and 2R only measure, they are not exits.
 * The levels are the symbol's own, so for an option they are the underlying's, said in the title. Advice only.
 */

const LO = -1.15; // the scale, in R from the entry: a little room left of the invalidation, right of 2R
const HI = 2.3;
const at = (r: number) => `${(((Math.min(HI, Math.max(LO, r)) - LO) / (HI - LO)) * 100).toFixed(2)}%`;
const price = (value: number) => value.toFixed(2);
const signed = (value: number, digits: number) => `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(digits)}`;
const hhmm = (seconds: number) => new Date(seconds * 1000).toLocaleTimeString("en-GB", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit" });
const expiryDay = (iso: string) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric" });

/** Whole days from today (New York) to an ISO date. */
export function daysTo(iso: string, now = Date.now()) {
  const today = new Date(now).toLocaleDateString("en-CA", { timeZone: "America/New_York" });
  return Math.round((Date.parse(`${iso}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86_400_000);
}

export type Ladder = {
  long: boolean; entry: number; invalidation: number; risk: number; last: number | null;
  /** The live price in R from the entry: negative toward the invalidation. */
  r: number | null;
  /** 1R and 2R past the entry, in the trade's direction. */
  one: number; two: number;
};

/** The scale's numbers, or null when the plan lacks an entry or an invalidation (or they are equal). */
export function ladderOf(plan: PlanBoardRow): Ladder | null {
  if (!plan.entry || !plan.invalidation) return null;
  const entry = plan.entry.price, invalidation = plan.invalidation.price, risk = Math.abs(entry - invalidation);
  if (!risk) return null;
  const long = plan.direction ? plan.direction === "long" : entry > invalidation;
  const side = long ? 1 : -1;
  return { long, entry, invalidation, risk, last: plan.last, r: plan.last === null ? null : (side * (plan.last - entry)) / risk,
    one: entry + side * risk, two: entry + 2 * side * risk };
}

/** "3.1% above invalidation", toned by which side of it the price is on. */
function where(plan: PlanBoardRow, ladder: Ladder): { text: string; tone: string } {
  const level = plan.invalidation!;
  if (level.state === "hit") return { text: `Invalidation hit${level.hit_at ? ` at ${hhmm(level.hit_at)}` : ""}`, tone: "text-rose-300" };
  if (ladder.last === null) return { text: "No live price", tone: "text-muted-foreground" };
  const gap = ((ladder.last - ladder.invalidation) / ladder.last) * 100;
  const safe = ladder.long ? gap > 0 : gap < 0;
  return { text: `${Math.abs(gap).toFixed(1)}% ${gap > 0 ? "above" : "below"} invalidation`, tone: safe ? "text-foreground" : "text-rose-300" };
}

/** The quiet line under the ladder: the time stop, and an option's expiry. */
export function clockLine(plan: PlanBoardRow, position: DeskPosition | null): string {
  const parts: string[] = [];
  const stop = plan.time_stop;
  parts.push(!stop ? "No time stop" : stop.state === "pending" ? `Time stop ${hhmm(stop.due_at)}` : `Time stop ${hhmm(stop.due_at)} · ${stop.state}`);
  if (position?.option) {
    const days = daysTo(position.option.expiry);
    parts.push(days <= 0 ? "expires today" : `expires ${expiryDay(position.option.expiry)} · ${days} day${days === 1 ? "" : "s"}`);
  }
  return parts.join(" · ");
}

const CONDITION: Record<string, string> = { touches: "touches", crosses: "crosses", closes_beyond: "closes beyond" };

function Details({ plan, ladder, position }: { plan: PlanBoardRow; ladder: Ladder; position: DeskPosition | null }) {
  const option = position?.instrument === "option";
  const rows: [string, string][] = [
    ["Entry alert", `${CONDITION[plan.entry!.condition] ?? plan.entry!.condition} ${price(ladder.entry)}${plan.entry!.interval ? ` (${plan.entry!.interval})` : ""} · ${plan.entry!.state}`],
    ["Invalidation alert", `${CONDITION[plan.invalidation!.condition] ?? plan.invalidation!.condition} ${price(ladder.invalidation)}${plan.invalidation!.interval ? ` (${plan.invalidation!.interval})` : ""} · ${plan.invalidation!.state}`],
    [`1R (${option ? "underlying" : "a share"})`, price(ladder.risk)],
  ];
  if (position) {
    if (position.avg_entry != null) rows.push([option ? "Entry premium" : "Average cost", price(option ? position.avg_entry / 100 : position.avg_entry)]);
    rows.push(["Size", `${position.quantity} ${option ? `contract${position.quantity === 1 ? "" : "s"}` : `share${position.quantity === 1 ? "" : "s"}`}`]);
    if (position.unrealized_usd != null) rows.push(["Open P&L", `${position.unrealized_usd < 0 ? "−" : ""}$${Math.abs(position.unrealized_usd).toFixed(2)}`]);
  }
  return (
    <details className="text-xs text-muted-foreground">
      <summary className="w-fit cursor-pointer list-none hover:text-foreground [&::-webkit-details-marker]:hidden">Details</summary>
      <dl className="mt-2 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt>{label}</dt>
            {/* Words with numbers: aligned figures in the text face; the desk keeps monospace for figures alone. */}
            <dd className="text-foreground [font-variant-numeric:tabular-nums]">{value}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

/**
 * The plan ladder. Full: what the price is doing against the plan, the R multiple, the scale with its tick labels and
 * one quiet line (time stop, expiry), then Details. ``compact``: one line, invalidation · bar · 2R. ``dimmed`` for a plan
 * that is not armed yet. Renders nothing when the plan lacks an entry or an invalidation.
 */
export default function PlanLadder({ plan, position = null, compact = false, dimmed = false }: {
  plan: PlanBoardRow; position?: DeskPosition | null; compact?: boolean; dimmed?: boolean;
}) {
  const ladder = ladderOf(plan);
  if (!ladder) return null;
  const now = ladder.r === null ? null : at(ladder.r);
  const label = `Plan ladder: invalidation ${price(ladder.invalidation)}, entry ${price(ladder.entry)}, 2R ${price(ladder.two)}`
    + (ladder.last === null ? "" : `, last ${price(ladder.last)} (${signed(ladder.r!, 2)}R)`);
  const bar = (height: string) => (
    <div className={cn("relative", height)} aria-hidden="true">
      <div className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-l-full bg-rose-400/30" style={{ left: at(-1), width: `calc(${at(0)} - ${at(-1)})` }} />
      <div className="absolute right-0 top-1/2 h-1.5 -translate-y-1/2 rounded-r-full bg-emerald-400/20" style={{ left: at(0) }} />
      {[-1, 0, 1, 2].map(r => (
        <div key={r} className={cn("absolute top-1/2 w-px -translate-y-1/2", r === -1 ? "h-4 bg-rose-300" : r === 0 ? "h-4 bg-foreground/70" : "h-2.5 bg-muted-foreground/60")}
          style={{ left: at(r) }} />
      ))}
      {now && <div className="absolute top-1/2 h-5 w-0.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-foreground shadow-[0_0_0_3px_hsl(var(--background))]" style={{ left: now }} />}
    </div>
  );

  if (compact) return (
    <div role="img" aria-label={label} className={cn("grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2.5 text-xs", dimmed && "opacity-45")}>
      <span className="tabular-nums text-rose-300">{price(ladder.invalidation)}</span>
      {bar("h-5")}
      <span className="tabular-nums text-muted-foreground" title="2R past the entry: a measure, not a target">{price(ladder.two)}</span>
    </div>
  );

  const state = where(plan, ladder);
  const option = position?.instrument === "option";
  return (
    <section aria-label="Plan ladder" className={cn("space-y-2", dimmed && "opacity-45")}>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{option ? `Plan · ${plan.symbol} levels (underlying)` : "Plan"}</span>
        <span className={cn("font-medium", state.tone)}>{state.text}</span>
        {ladder.r !== null && (
          <span className={cn("ml-auto text-xs", ladder.r >= 0 ? "text-emerald-300" : "text-rose-300")}
            title={`Where ${plan.symbol} is, in multiples of the entry-to-invalidation distance (${price(ladder.risk)})`}>
            <span className="tabular-nums">{signed(ladder.r, 2)}R</span>{option && <span className="text-muted-foreground"> on {plan.symbol}</span>}
          </span>
        )}
      </div>
      <div role="img" aria-label={label} className="relative pt-5">
        {now && ladder.last !== null && (
          // Near an end the price tag leans inward, so a price far off the scale stays inside the pane.
          <span className={cn("absolute top-0 whitespace-nowrap rounded bg-foreground px-1.5 text-[11px] text-background",
            ladder.r! >= HI - 0.4 ? "-translate-x-full" : ladder.r! <= LO + 0.3 ? "" : "-translate-x-1/2")} style={{ left: now }}>
            <span className="tabular-nums">{price(ladder.last)}</span>
          </span>
        )}
        {bar("h-6")}
        <div className="relative h-8 text-xs">
          {([[-1, ladder.invalidation, "Invalidation", "text-rose-300"], [0, ladder.entry, plan.entry!.state === "hit" ? "Entry · hit" : "Entry", "text-foreground"],
            [1, ladder.one, "1R", "text-muted-foreground"], [2, ladder.two, "2R", "text-muted-foreground"]] as const).map(([r, value, word, tone]) => (
            <div key={r} title={r > 0 ? "A measure past the entry, not a target: the plan has none" : undefined}
              className={cn("absolute flex flex-col whitespace-nowrap", r === -1 ? "items-start" : r === 2 ? "-translate-x-full items-end" : "-translate-x-1/2 items-center")}
              style={{ left: at(r) }}>
              <span className={cn("tabular-nums", tone)}>{price(value)}</span>
              <span className="text-[11px] text-muted-foreground">{word}</span>
            </div>
          ))}
        </div>
      </div>
      <p className="text-xs text-muted-foreground">{clockLine(plan, position)}</p>
      <Details plan={plan} ladder={ladder} position={position} />
    </section>
  );
}
