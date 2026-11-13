"use client";

/**
 * Where a held option stands, on the desk (docs/copilot-lab.md § The desk): break-even and the stock's distance to it,
 * days left, value at expiry if the stock stays put against value now, decay a day, the dollar move per $1 in the stock
 * and IV, with a small P&L-at-expiry line. The arithmetic is ``lib/optionStanding.ts``; this only lays it out. The
 * stock-price figures move with the desk's live prices (``lib/deskTicks.ts``); the Greeks are the book read's. Facts
 * only: nothing here tells the owner to buy, sell or hold.
 */

import { type ReactNode } from "react";
import type { DeskThread } from "@/lib/desk";
import { tickFor, useDeskTicks } from "@/lib/deskTicks";
import { price as priceText, todayNewYork } from "@/lib/charts";
import { mixedStructure, optionStanding, worthNow, type ExpiryCurve, type OptionGreeks, type Standing } from "@/lib/optionStanding";
import { Flash } from "@/components/copilot/Ticks";
import { cn } from "@/lib/utils";

/** Robinhood's Greeks older than this read as stale (the feed refreshes once a minute in market hours). */
const GREEKS_STALE_SECONDS = 180;

const clock = (seconds: number) => new Date(seconds * 1000).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });

/** Dollars, cents under $10 so a small figure never rounds to a misleading $0. */
function dollars(value: number, signed = false) {
  const abs = Math.abs(value);
  const text = abs.toLocaleString("en-US", abs < 10 && abs >= 0.005 ? { minimumFractionDigits: 2, maximumFractionDigits: 2 } : { maximumFractionDigits: 0 });
  const sign = value > 0 ? (signed ? "+" : "") : value < 0 ? "−" : "";
  return `${sign}$${text}`;
}
const pct = (value: number) => `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(1)}%`;

function greeksLine(greeks: OptionGreeks | null, now = Date.now() / 1000): { text: string; stale: boolean } {
  if (!greeks) return { text: "Greeks unavailable", stale: true };
  if (greeks.source === "robinhood") {
    const at = typeof greeks.as_of === "number" ? greeks.as_of : null;
    return { text: at === null ? "Greeks · Robinhood" : `Greeks · Robinhood ${clock(at)}`, stale: at === null || now - at > GREEKS_STALE_SECONDS };
  }
  // The app's own quote: hourly provider figures, their stamp as given (its time zone is the provider's).
  const stamp = typeof greeks.as_of === "string" ? greeks.as_of.slice(11, 16) : "";
  return { text: `Greeks · app quote, hourly${stamp ? ` (stamp ${stamp})` : ""}`, stale: true };
}

function Fig({ label, children, dim = false, testId }: { label: string; children: ReactNode; dim?: boolean; testId?: string }) {
  return (
    <span data-testid={testId} className={cn("min-w-0 max-w-full sm:whitespace-nowrap", dim && "opacity-50")}>
      <span className="text-muted-foreground">{label} </span><span className="text-foreground">{children}</span>
    </span>
  );
}

/** P&L at expiry across the range, a zero line, the stock now (white) and break-even (amber). */
export function ExpiryLine({ curve, now, breakEven, dim = false }: { curve: ExpiryCurve; now: number; breakEven: number; dim?: boolean }) {
  const W = 120, H = 26;
  const pnls = curve.points.map(p => p.pnl);
  const top = Math.max(...pnls, 0), bottom = Math.min(...pnls, 0);
  const x = (at: number) => (at - curve.lo) / (curve.hi - curve.lo) * W;
  const y = (pnl: number) => top === bottom ? H / 2 : 1 + (top - pnl) / (top - bottom) * (H - 2);
  const path = curve.points.map((p, i) => `${i ? "L" : "M"}${x(p.price).toFixed(1)},${y(p.pnl).toFixed(1)}`).join("");
  return (
    <svg data-testid="option-expiry-line" width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" className={cn("shrink-0 overflow-visible", dim && "opacity-50")}
      aria-label={`P&L at expiry from ${priceText(curve.lo)} to ${priceText(curve.hi)}: break-even ${priceText(breakEven)}, stock now ${priceText(now)}`}>
      <line x1={0} x2={W} y1={y(0)} y2={y(0)} stroke="hsl(var(--muted-foreground))" strokeOpacity={0.4} strokeDasharray="2 2" />
      <path d={path} fill="none" stroke="hsl(var(--muted-foreground))" strokeWidth={1.25} />
      <line x1={x(breakEven)} x2={x(breakEven)} y1={0} y2={H} stroke="#e9a23b" strokeWidth={1} />
      <line x1={x(now)} x2={x(now)} y1={0} y2={H} stroke="hsl(var(--foreground))" strokeWidth={1.25} />
    </svg>
  );
}

function useStanding(row: DeskThread, rows: readonly DeskThread[], fallback: { last: number; at: number } | null) {
  const book = row.book;
  const ticks = useDeskTicks([row.symbol, book?.tick?.quote]);
  const terms = book?.option ?? null;
  if (!book || !terms) return null;
  if (mixedStructure(row.symbol, terms, rows.map(r => ({ symbol: r.symbol, option: r.book?.option })))) return "unknown" as const;
  const live = tickFor(ticks, row.symbol);
  const stock = live ? { last: live.last, at: live.at, live: !live.stale } : fallback ? { ...fallback, live: false } : null;
  const standing = optionStanding(terms, { price: stock?.last, worth: worthNow(book, ticks), day: todayNewYork() });
  return standing ? { standing, stock } : terms.direction === "long" ? "incomplete" as const : "unknown" as const;
}

const INCOMPLETE = "Break-even and Greeks not shown: the book is missing this contract's side, strike, expiry or size.";
const UNKNOWN = "Break-even and Greeks not shown: a short or multi-leg position the book cannot read as one option.";

function distance(s: Standing) {
  const to = s.toBreakEven;
  if (!to) return null;
  if (to.past) return `${dollars(Math.abs(to.usd))} (${Math.abs(to.pct).toFixed(1)}%) past it`;
  return `needs ${dollars(to.usd, true)} (${pct(to.pct)})`;
}

/**
 * The selected option's standing under the centre's header. ``rows`` is the desk's book (a short option on the same
 * ticker means a structure the book cannot tell); ``fallback`` the stock's last price when the desk's ticker is not
 * running (the chart's last read).
 */
export function OptionStanding({ row, rows, fallback = null }: {
  row: DeskThread; rows: readonly DeskThread[]; fallback?: { last: number; at: number } | null;
}) {
  const read = useStanding(row, rows, fallback);
  if (read === null) return null;
  if (read === "unknown" || read === "incomplete") return <p data-testid="option-standing" className="text-xs text-muted-foreground">{read === "unknown" ? UNKNOWN : INCOMPLETE}</p>;
  const { standing: s, stock } = read;
  const dim = !!stock && !stock.live;
  const greeks = greeksLine(s.greeks);
  const missing = [s.decayPerDay === null && "decay", s.perDollar === null && "delta", s.ivPct === null && "IV"].filter((part): part is string => !!part);
  const days = s.daysLeft < 0 ? "Expired" : s.expiryNote ? `${s.expiryNote} · ${s.daysLeft}d` : `${s.daysLeft}d left`;
  return (
    <div data-testid="option-standing" className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs tabular-nums">
      <Fig label="Break-even" testId="standing-break-even">
        {s.breakEven === null ? <span className="text-muted-foreground">unavailable (no cost)</span> : <>
          {priceText(s.breakEven)}
          {s.toBreakEven && <span className={cn("text-muted-foreground", dim && "opacity-50")}> · stock <Flash value={stock?.last}>{priceText(stock!.last)}</Flash>{dim && ` (${clock(stock!.at)})`} {distance(s)}</span>}
        </>}
      </Fig>
      <Fig label="Expiry" testId="standing-expiry"><span className={cn(s.daysLeft <= 2 && "text-amber-300")}>{days}</span></Fig>
      <Fig label="If it stays here" testId="standing-at-expiry" dim={dim}>
        {s.atExpiry === null ? <span className="text-muted-foreground">stock price unavailable</span> : <>
          {dollars(s.atExpiry)} at expiry
          {s.worth !== null ? <> · {dollars(s.worth)} now · {s.timeValue! >= 0 ? `${dollars(s.timeValue!)} time value` : `${dollars(-s.timeValue!)} under intrinsic`}</>
            : <span className="text-muted-foreground"> · value now unavailable</span>}
        </>}
      </Fig>
      {s.decayPerDay !== null && <Fig label="Decay" testId="standing-decay" dim={greeks.stale}>{dollars(s.decayPerDay, true)}/day</Fig>}
      {s.perDollar !== null && <Fig label="Moves" testId="standing-delta" dim={greeks.stale}>about {dollars(s.perDollar, true)} per $1 up in {row.symbol}</Fig>}
      {s.ivPct !== null && <Fig label="IV" testId="standing-iv" dim={greeks.stale}>{s.ivPct.toFixed(0)}%</Fig>}
      {s.curve && s.breakEven !== null && stock && <ExpiryLine curve={s.curve} now={stock.last} breakEven={s.breakEven} dim={dim} />}
      <span data-testid="standing-greeks" className={cn("text-[11px]", greeks.stale ? "text-muted-foreground/70" : "text-muted-foreground")}>
        {missing.length === 3 ? "Greeks unavailable" : missing.length ? `${greeks.text} · ${missing.join(", ")} unavailable` : greeks.text}
      </span>
    </div>
  );
}

/** The same standing in one quiet line, under the selected book row. Nothing for a structure the book cannot read. */
export function OptionStandingLine({ row, rows, fallback = null }: {
  row: DeskThread; rows: readonly DeskThread[]; fallback?: { last: number; at: number } | null;
}) {
  const read = useStanding(row, rows, fallback);
  if (read === null || read === "unknown" || read === "incomplete") return null;
  const { standing: s, stock } = read;
  const parts: string[] = [];
  if (s.breakEven !== null) parts.push(`BE ${priceText(s.breakEven)}${s.toBreakEven ? ` ${s.toBreakEven.past ? "passed" : pct(s.toBreakEven.pct)}` : ""}`);
  if (s.timeValue !== null && s.timeValue >= 0) parts.push(`${dollars(s.timeValue)} time value`);
  if (s.decayPerDay !== null) parts.push(`${dollars(s.decayPerDay, true)}/day`);
  if (s.perDollar !== null) parts.push(`${dollars(s.perDollar, true)} per $1`);
  if (s.ivPct !== null) parts.push(`IV ${s.ivPct.toFixed(0)}%`);
  if (!s.greeks) parts.push("Greeks unavailable");
  return (
    <p data-testid="book-standing" className={cn("truncate px-3 pb-1.5 text-[11px] tabular-nums text-muted-foreground", stock && !stock.live && "opacity-70")}>
      {parts.join(" · ")}
    </p>
  );
}
