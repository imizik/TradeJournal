import type { ReactNode } from "react";
import { readAt } from "@/lib/symbolInfo";

/** Small group heading used by every symbol-info tab. */
export const HEADING = "text-[10px] font-medium uppercase tracking-wider text-slate-500";

/**
 * One fact on one line: the label on the left in muted text (it truncates, with the full text in
 * the row's hover title), the value on the right in the tabular mono style. The value never
 * shrinks or wraps, so a number is never cut off at the dock's 256px width.
 */
export function Row({ label, value, title, tone, hint }: { label: string; value: ReactNode; title?: string; tone?: string; hint?: string }) {
  return <div title={title ?? hint ?? label} className="flex items-baseline justify-between gap-2 py-0.5">
    <dt className="min-w-0 truncate text-slate-500">{label}</dt>
    <dd className={`shrink-0 whitespace-nowrap font-mono ${tone ?? "text-slate-200"}`}>{value}</dd>
  </div>;
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
