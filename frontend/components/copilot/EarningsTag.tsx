"use client";

import { useEffect, useMemo, useState } from "react";
import { getDeskEvents, type DeskEarningsTag, type DeskEvents, type DeskThread } from "@/lib/desk";
import { cn } from "@/lib/utils";

/** Dates do not move intraday: the tags are read again every half hour, and shortly after a read that found a calendar
 * still loading (its first read for a symbol runs in the background on the server). */
const REREAD_MS = 30 * 60_000;
const LOADING_MS = 20_000;
const LOADING_TRIES = 3;

/** Held options' expiries by symbol, from the followed book rows (a stock has none). */
export function heldExpiries(rows: DeskThread[]): { symbol: string; expiry: string }[] {
  const seen = new Set<string>();
  return rows.flatMap(r => {
    const expiry = r.book?.expiry;
    if (!r.symbol || !expiry || r.instrument === "stock") return [];
    const key = `${r.symbol}:${expiry}`;
    if (seen.has(key)) return [];
    seen.add(key);
    return [{ symbol: r.symbol, expiry }];
  });
}

/** The earnings tags for the followed book rows and the Watching list (``GET /copilot/desk/events``): one read for all of
 * them. Nothing when the read fails: the tags are extra, and never guessed. */
export function useDeskEvents(on: boolean, rows: DeskThread[], watched: string[]): DeskEvents | null {
  const [data, setData] = useState<DeskEvents | null>(null);
  const symbols = useMemo(() => [...new Set([...rows.flatMap(r => r.symbol ? [r.symbol] : []), ...watched])].sort().join(","), [rows, watched]);
  const held = useMemo(() => heldExpiries(rows).map(h => `${h.symbol}:${h.expiry}`).sort().join(","), [rows]);
  useEffect(() => {
    if (!on || !symbols) return;
    const controller = new AbortController();
    let tries = 0;
    let retry: number | undefined;
    const read = () => {
      window.clearTimeout(retry);
      getDeskEvents(symbols.split(","), held ? held.split(",").map(pair => { const [symbol, expiry] = pair.split(":"); return { symbol, expiry }; }) : [], controller.signal)
        .then(next => {
          setData(next);
          if (next.loading && tries++ < LOADING_TRIES) retry = window.setTimeout(read, LOADING_MS);
        })
        .catch(() => { /* the tags are extra */ });
    };
    read();
    const timer = window.setInterval(() => { if (document.visibilityState === "visible") { tries = 0; read(); } }, REREAD_MS);
    return () => { controller.abort(); window.clearInterval(timer); window.clearTimeout(retry); };
  }, [on, symbols, held]);
  return on ? data : null;
}

const WEEKDAY = new Intl.DateTimeFormat("en-US", { weekday: "short", timeZone: "UTC" });
const MONTH_DAY = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
const at = (iso: string) => new Date(`${iso}T12:00:00Z`);
const gap = (iso: string, day: string) => Math.round((at(iso).getTime() - at(day).getTime()) / 86_400_000);

/** "Thu" within the coming week, "today", else "Nov 24". */
export function dayWord(iso: string, day: string): string {
  const n = gap(iso, day);
  return n === 0 ? "today" : n > 0 && n < 7 ? WEEKDAY.format(at(iso)) : MONTH_DAY.format(at(iso));
}

const TIME = "time of day not published";

/** The position header's one line for a held option, or null: "Earnings Thu, before your Fri expiry · time of day not
 * published" when the report falls inside the contract's life. */
export function earningsLine(tag: DeskEarningsTag | undefined, expiry: string | null | undefined, day: string): string | null {
  if (!tag || !expiry || expiry < tag.date) return null;
  const when = `Earnings ${dayWord(tag.date, day)}${tag.status === "estimated" ? " (estimated)" : ""}`;
  return expiry === tag.date ? `${when}, the day your contract expires · ${TIME}` : `${when}, before your ${dayWord(expiry, day)} expiry · ${TIME}`;
}

/** The tag's hover text: the date, whether it is confirmed, and why it is amber. */
export function tagTitle(tag: DeskEarningsTag, day: string): string {
  const date = `${WEEKDAY.format(at(tag.date))} ${MONTH_DAY.format(at(tag.date))}`;
  const status = tag.status === "estimated" ? "estimated, not yet confirmed" : tag.status ?? "date";
  const away = tag.trading_days === 0 ? "today" : `${tag.trading_days} trading day${tag.trading_days === 1 ? "" : "s"} away`;
  const inside = tag.through.length ? ` Your ${tag.through.map(e => dayWord(e, day)).join(", ")} contract expires after it.` : "";
  return `Earnings ${date} (${status}), ${away}.${inside} Time of day not published.`;
}

/** The book's or Watching row's short tag: grey within 7 trading days, amber when a held option lives through the report. */
export function EarningsTag({ tag, day, className }: { tag: DeskEarningsTag | undefined; day: string; className?: string }) {
  if (!tag) return null;
  const amber = tag.tone === "amber";
  return (
    <span data-testid="earnings-tag" data-tone={tag.tone} title={tagTitle(tag, day)}
      className={cn("rounded border px-1 tabular-nums", amber ? "border-amber-300/50 text-amber-200" : "border-foreground/15 text-muted-foreground", className)}>
      {tag.label}
    </span>
  );
}

/** The position header's line for a held option whose life spans the next report (``earningsLine``); nothing otherwise. */
export function PositionEarnings({ row, earnings }: { row: DeskThread | null; earnings: DeskEvents | null }) {
  const expiry = row && row.instrument !== "stock" ? row.book?.expiry : null;
  const line = row?.symbol && earnings ? earningsLine(earnings.rows[row.symbol], expiry, earnings.today) : null;
  if (!line) return null;
  return <p data-testid="position-earnings" className="text-xs text-amber-200">{line}</p>;
}
