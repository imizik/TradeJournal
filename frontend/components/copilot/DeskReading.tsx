"use client";

import { Flash } from "@/components/copilot/Ticks";
import { heldReading } from "@/lib/deskTicks";
import { signedPct, type DeskChartData } from "@/lib/desk";
import { cn } from "@/lib/utils";

// The desk chart's reading line and its time words (DeskChart.tsx), apart from the chart so the page can show them
// before the chart library has loaded.

const ET = "America/New_York";
export const clock = new Intl.DateTimeFormat("en-US", { timeZone: ET, hour: "numeric", minute: "2-digit" });
export const dayFmt = new Intl.DateTimeFormat("en-US", { timeZone: ET, month: "short", day: "numeric" });
export const price = (value: number) => value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
/** "10:05 ET" today, "Oct 20 10:05 ET" another day, "Oct 20" on daily candles. */
export function nyWhen(seconds: number, daily = false, now = Date.now() / 1000): string {
  const at = seconds * 1000;
  if (daily) return dayFmt.format(at);
  const sameDay = dayFmt.format(at) === dayFmt.format(now * 1000);
  return `${sameDay ? "" : `${dayFmt.format(at)} `}${clock.format(at)} ET`;
}

/**
 * The chart's reading, in two parts. ``head`` (in the header row, beside the symbol): the newest price and the day's
 * change against the previous close (``fallback``: the book's change today when the read has no previous close).
 * ``facts`` (on the quiet line under it): the distance from VWAP and from the plan's invalidation, volume against usual
 * for the time of day, and the as-of. A part with nothing behind it is left out. Both hold what they last showed for
 * ``symbol`` rather than blank or step back (``heldReading``).
 */
export function ReadingLine({ symbol, data, fallback = null, live = null, part }: {
  symbol: string; data: DeskChartData | null; fallback?: { pct: number; at: number } | null; part: "head" | "facts";
  /** The desk's live price (``lib/deskTicks.ts``): newer than the chart's last minute, it is the reading's price and time. */
  live?: { last: number; at: number; stale: boolean } | null;
}) {
  const read = data?.state === "ok" && data.symbol === symbol ? data.reading : null;
  const fresh = !!(read && live && !read.daily && live.at > read.at);
  const next = read ? {
    reading: fresh ? { ...read, last: live!.last, at: live!.at } : read,
    invalidation: data?.levels.find(level => level.role === "invalidation")?.price ?? null, ticked: fresh,
  } : null;
  const held = heldReading(symbol, next);
  if (!held) return part === "head" ? <span data-testid="desk-reading" /> : null;
  const { reading, invalidation } = held;
  const ticked = held.ticked && !!live;
  const { last, at, daily } = reading;
  // VWAP and RVol are the regular session's: after the close or before the open their time is not the price's.
  const sessionAt = reading.vwap_at !== null && !daily && Math.abs(reading.vwap_at - at) > 90 ? reading.vwap_at : null;
  const change = reading.prev_close ? (last / reading.prev_close - 1) * 100 : null;
  // The change: its figure in the header, its basis first on the facts line.
  const parts: { key: string; text: string; tone?: number; title?: string; head?: string }[] = [];
  if (change !== null) parts.push({ key: "change", head: signedPct(change, 2), text: `change vs prev close ${price(reading.prev_close!)}`, tone: change, title: `vs the previous close, ${price(reading.prev_close!)}` });
  // The header keeps the figure alone (its basis is the hover's and the ⓘ's), so the row fits beside the timeframes.
  else if (fallback) parts.push({ key: "change", head: signedPct(fallback.pct, 2), text: `change today from the book, ${nyWhen(fallback.at)}`, tone: fallback.pct, title: `The book's change today, as of ${nyWhen(fallback.at)}` });
  if (reading.vwap) {
    const away = (last / reading.vwap - 1) * 100;
    parts.push({ key: "vwap", text: `${signedPct(away, 2)} vs VWAP ${price(reading.vwap)}` });
  }
  if (invalidation) {
    const away = (last - invalidation) / last * 100;
    parts.push({ key: "invalidation", text: `${Math.abs(away).toFixed(1)}% ${away >= 0 ? "above" : "below"} invalidation ${price(invalidation)}` });
  }
  if (reading.rvol) parts.push({ key: "rvol", text: `vol ${reading.rvol.toFixed(1)}× usual` });
  if (part === "head") {
    const change = parts.find(p => p.key === "change");
    return (
      <span data-testid="desk-reading" className="flex items-baseline gap-1.5 whitespace-nowrap text-xs tabular-nums">
        <span data-testid="desk-reading-last" className={cn("text-sm text-foreground", ticked && live!.stale && "opacity-50")}><Flash value={last}>{price(last)}</Flash></span>
        {change && <span data-part="change" title={change.title} className={change.tone === undefined || change.tone === 0 ? "text-muted-foreground" : change.tone > 0 ? "text-emerald-300" : "text-rose-300"}>{change.head}</span>}
      </span>
    );
  }
  return (
    // The as-of first, so it is never the part out of view.
    <span data-testid="desk-reading-facts">
      <span>as of {nyWhen(at, daily)}{sessionAt !== null ? ` (VWAP${reading.rvol ? ", vol" : ""} ${nyWhen(sessionAt)})` : ""}</span>
      {parts.map(p => <span key={p.key} data-part={p.key}> · {p.text}</span>)}
    </span>
  );
}

