"use client";

import { useEffect, useId, useState } from "react";
import type { ReactNode } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { readAt } from "@/lib/symbolInfo";

/** Small group heading used by every symbol-info tab. */
export const HEADING = "text-[10px] font-medium uppercase tracking-wider text-slate-500";

/**
 * One fact on one line: the label on the left in muted text (it truncates, with the full text in
 * the row's hover title), the value on the right in the tabular mono style. The value never
 * shrinks or wraps, so a number is never cut off at the dock's 256px width. With `explain`, the
 * label is a button: a tap (or click) shows what the number means on a line under it, and the
 * hover title carries the same text, so a phone gets it too.
 */
export function Row({ label, value, title, tone, hint, explain }: { label: string; value: ReactNode; title?: string; tone?: string; hint?: string; explain?: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const tip = [title ?? hint ?? label, explain].filter(Boolean).join("\n\n");
  return <div title={tip} className="flex flex-wrap items-baseline justify-between gap-x-2 py-0.5">
    <dt className="min-w-0 flex-1 truncate text-slate-500">{explain
      ? <button type="button" aria-expanded={open} aria-controls={`${id}-why`} onClick={() => setOpen(!open)}
        className="max-w-full truncate text-left underline decoration-slate-600 decoration-dotted underline-offset-2 hover:text-slate-300">{label}</button>
      : label}</dt>
    <dd className={`shrink-0 whitespace-nowrap font-mono ${tone ?? "text-slate-200"}`}>{value}</dd>
    {explain && open && <dd id={`${id}-why`} data-explain className="basis-full pb-1 pt-0.5 text-[10px] leading-4 text-slate-400">{explain}</dd>}
  </div>;
}

/**
 * One foldable block of a symbol-info tab: an edged box with its own header, so blocks read as
 * separate at a glance. The fold is remembered on this device only; until then `defaultOpen` decides.
 */
export function Block({ name, title, defaultOpen = true, side, children }: { name: string; title: string; defaultOpen?: boolean; side?: ReactNode; children: ReactNode }) {
  const id = useId();
  const key = `tradejournal.charts.info.${name}.open.v1`;
  const [chosen, setChosen] = useState<boolean | null>(null);
  useEffect(() => {
    try { const saved = localStorage.getItem(key); if (saved === "1" || saved === "0") queueMicrotask(() => setChosen(saved === "1")); } catch { /* device storage is optional */ }
  }, [key]);
  const open = chosen ?? defaultOpen;
  const toggle = () => {
    setChosen(!open);
    try { localStorage.setItem(key, open ? "0" : "1"); } catch { /* keep working without storage */ }
  };
  return <section aria-label={title} className="overflow-hidden rounded-md border border-slate-700/60 bg-slate-950/40">
    <h3 className="flex items-center gap-1 bg-slate-800/40 pr-2">
      <button type="button" aria-expanded={open} aria-controls={`${id}-body`} onClick={toggle}
        className="flex min-h-11 min-w-0 flex-1 items-center gap-1 px-2 text-left text-[10px] font-semibold uppercase tracking-wider text-slate-300 hover:text-slate-100 lg:min-h-7">
        {open ? <ChevronDown size={12} className="shrink-0 text-slate-500" aria-hidden /> : <ChevronRight size={12} className="shrink-0 text-slate-500" aria-hidden />}
        <span className="truncate">{title}</span>
      </button>
      {side}
    </h3>
    {open && <div id={`${id}-body`} className="space-y-1.5 px-2.5 pb-2.5 pt-2">{children}</div>}
  </section>;
}

/** A list of `Row`s. */
export const Rows = ({ children }: { children: ReactNode }) => <dl className="space-y-0.5">{children}</dl>;

export type FooterSource = { source: string; /** Seconds; `undefined` leaves the time out, `null` says "not read yet". */ at?: number | null; label?: string };

/**
 * The one source line at the bottom of a tab. Sources that read at the same time are listed once;
 * the hover title keeps which block each came from. Stale, partial, estimated or unofficial notes
 * are not part of this line: they stay inline where they apply.
 */
export function SourceFooter({ items, note }: { items: FooterSource[]; note?: ReactNode }) {
  const text = (item: FooterSource) => item.at === undefined ? item.source : `${item.source} · ${readAt(item.at)}`;
  // Sources read at the same moment share one time: "A, B · read Oct 5, 9:40 AM ET".
  const groups = new Map<string, { at: number | null | undefined; sources: string[] }>();
  for (const item of items) {
    const group = groups.get(String(item.at)) ?? { at: item.at, sources: [] };
    if (!group.sources.includes(item.source)) group.sources.push(item.source);
    groups.set(String(item.at), group);
  }
  const line = [...groups.values()].map((group) => text({ source: group.sources.join(" + "), at: group.at })).join("; ");
  return <div className="space-y-1 border-t border-slate-800 pt-2 text-[10px] leading-4 text-slate-500" data-source-footer>
    <p title={items.map((item) => `${item.label ? `${item.label}: ` : ""}${text(item)}`).join("\n")}>{line}</p>
    {note}
  </div>;
}

/**
 * What a number means, shown when its label is tapped. General context only: how to read it and
 * what it is usually compared with, never a verdict on this symbol.
 */
export const EXPLAIN = {
  week52: "Where the price sits between its lowest and highest trade of the last year. Near the top: buyers have been in control; near the bottom: the stock is out of favor or under pressure.",
  marketCap: "Share price × shares outstanding: what the market values the whole company at. Large caps (>$10B) usually move less on news than small caps (<$2B).",
  enterpriseValue: "Market cap plus debt minus cash: roughly what it would cost to buy the whole business. Far above market cap means heavy debt; below it means a large cash pile.",
  shares: "Shares that exist. Watch it over time: a rising count dilutes holders (new stock, stock pay); a falling count means buybacks.",
  held: "Share of the stock owned by funds and institutions. High (>70%) means big money moves the price; low means it trades more on retail flow.",
  volume: "Average shares traded per day over 30 days. Compare today's volume with it: well above average means unusual interest; low volume makes moves less reliable and fills wider.",
  pe: "Price ÷ the last 12 months' earnings per share: what you pay for $1 of profit. High means the market expects fast growth (or profits are temporarily low); low can mean value or trouble. Compare within the same industry. The S&P 500 has averaged about 16 over the long run and higher in recent years. Blank when earnings are negative.",
  ps: "Market cap ÷ the last 12 months' revenue. Useful when there are no profits yet. Software and chip makers often trade above 10; retailers and industrials usually below 2.",
  pb: "Price ÷ book value (assets minus debts) per share. Near or below 1 says the market values the company at about what it owns; asset-light companies (software, brands) are naturally much higher.",
  evEbitda: "Enterprise value ÷ operating cash profit before interest, tax and depreciation. Compares companies regardless of debt. Around 10–15 is common for mature companies; well above means growth is priced in.",
  dividend: "Yearly dividend ÷ price. Most growth stocks pay little or none; a very high yield (>6%) can mean the price fell because the payout is at risk.",
  beta: "How much the stock has moved with the market over 5 years. 1 moves like the S&P 500; 2 moves about twice as much in either direction; below 1 is calmer.",
} as const;
