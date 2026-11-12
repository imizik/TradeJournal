"use client";

import { useEffect, useState } from "react";
import { useKept } from "@/components/copilot/DeskMemory";
import { fetchPositionContext, type PositionRecord, type SinceLine } from "@/lib/chartJournal";
import { cn } from "@/lib/utils";

/*
 * "Since you entered": one open position's thesis and what changed since the entry, from its one record
 * (GET /charts/journal/positions/{symbol}/context, backend engine/trader_context.py). Shared by the Copilot desk's
 * thread header and Charts' Holding context, so both say the same thing. It leads with at most three plain lines (P&L
 * and the mark; the plan's invalidation and time stop, or "No plan saved"; what changed since the entry). Every line as
 * the record wrote it, with its source and time, and every input that is missing ("unavailable", never zero) waits
 * behind "Sources and gaps", in muted grey. Times are New York time. ``collapsible`` (a thread with a conversation)
 * starts as one summary line that opens on tap. Read when shown, then each minute while the page is visible. Read-only.
 */

const REFRESH_MS = 60_000;
const SOURCE: Record<PositionRecord["thesis"]["source"], string> = {
  plan_card: "Plan card", plan_sheet: "Charts plan", companion: "Adopted by the companion", none: "No plan",
};
const NY = "America/New_York";

/** The values a since-entry line carries beside its text (``_line(**values)`` in trader_context.py); any may be absent. */
type Values = SinceLine & {
  now?: number; entry?: number; change_pct?: number; invalidation?: number; from_invalidation_pct?: number; mark?: number;
  symbol_pct?: number | null; spy_pct?: number | null; count?: number; days_to_expiry?: number;
};

export const clockOf = (iso: string | null) => {
  if (!iso) return null;
  const at = new Date(iso);
  return Number.isNaN(at.getTime()) ? null : at.toLocaleTimeString("en-US", { timeZone: NY, hour: "numeric", minute: "2-digit" });
};

/** A time in New York: the clock alone today, with the weekday and date on another day. */
const whenOf = (iso: string | null, now = new Date()) => {
  const clock = clockOf(iso);
  if (!clock || !iso) return null;
  const day = (d: Date) => d.toLocaleDateString("en-US", { timeZone: NY });
  const at = new Date(iso);
  return day(at) === day(now) ? clock : `${at.toLocaleDateString("en-US", { timeZone: NY, weekday: "short", month: "short", day: "numeric" })} ${clock}`;
};

const signed = (n: number, digits = 1) => `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n).toFixed(digits)}%`;
const num = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);

export function thesisText(record: PositionRecord): string {
  const t = record.thesis;
  if (t.source === "none") return "No plan saved for this position: no thesis, invalidation or time stop on file.";
  const words = t.text ? (t.text_is_guess ? `${t.text} (the companion's guess)` : t.text) : "No thesis in words.";
  const level = t.invalidation ? ` Invalidation ${t.invalidation.price.toFixed(2)} (${t.invalidation.state}).` : "";
  return `${SOURCE[t.source]}: ${words}${level}`;
}

/** The headline line in New York time (the record's own text names UTC). */
function headlineText(line: Values): string {
  const count = line.count ?? line.headlines?.length;
  const newest = whenOf(line.headlines?.[0]?.at ?? null);
  if (!num(count)) return line.text;
  if (count === 0) return "No headline naming it since the entry";
  return `${count} headline${count === 1 ? "" : "s"} naming it since the entry${newest ? `, newest ${newest} ET` : ""}`;
}

type Fact = { key: string; text: string; short: string };

/** The three plain lines: what it is worth, where the plan stands, what changed. A missing input is left to the fold. */
export function sinceFacts(record: PositionRecord): Fact[] {
  const lines = (record.since_entry?.lines ?? []) as Values[];
  const ok = (key: string) => lines.find(l => l.key === key && l.state === "ok");
  const option = lines.some(l => l.key === "iv" || l.key === "group");  // only an option's record has these lines
  const facts: Fact[] = [];
  const under = ok("underlying");

  const mark = ok("mark");
  if (mark) {
    if (num(mark.mark) && num(mark.entry)) {
      // An option's mark per share, as the thread header shows it (the journal keeps it per contract).
      const per = option ? 100 : 1, pnl = num(mark.change_pct) ? `P&L ${signed(mark.change_pct)} · ` : "";
      const text = `${pnl}${option ? "option mark" : "price"} ${(mark.mark / per).toFixed(2)} (entry ${(mark.entry / per).toFixed(2)})`;
      facts.push({ key: "pnl", text, short: num(mark.change_pct) ? `P&L ${signed(mark.change_pct)}` : text });
    } else facts.push({ key: "pnl", text: mark.text, short: mark.text });
  }

  const thesis = record.thesis;
  if (thesis.source === "none") facts.push({ key: "plan", text: "No plan saved", short: "No plan saved" });
  else {
    const level = num(under?.invalidation) ? under.invalidation : thesis.invalidation?.price;
    const gap = under?.from_invalidation_pct;
    const invalidation = !num(level) ? "no invalidation in the plan"
      : num(gap) ? `${Math.abs(gap).toFixed(1)}% ${gap >= 0 ? "above" : "below"} the ${level.toFixed(2)} invalidation`
      : `invalidation ${level.toFixed(2)}`;
    const stop = thesis.time_stop;
    const due = stop?.due_at ? whenOf(stop.due_at) : null;
    const timeStop = due ? `time stop ${due} ET` : stop?.text ? `time stop ${stop.text}` : "no time stop";
    facts.push({ key: "plan", text: `${invalidation} · ${timeStop}`, short: invalidation });
  }

  const changed: string[] = [];
  if (under && num(under.change_pct)) changed.push(`${record.symbol} ${signed(under.change_pct, 2)} since entry`);
  const group = ok("group");
  if (group && num(group.spy_pct)) {
    const peers = /(\d+ of \d+ peers lower, \d+ higher)/.exec(group.text)?.[1];
    changed.push(`SPY ${signed(group.spy_pct, 2)}${peers ? `, ${peers}` : ""}`);
  }
  const news = ok("headlines");
  if (news) {
    const count = news.count ?? news.headlines?.length;
    if (num(count)) changed.push(count === 0 ? "no headlines" : `${count} headline${count === 1 ? "" : "s"}`);
  }
  if (changed.length) facts.push({ key: "changed", text: changed.join(" · "), short: changed[0] });
  return facts;
}

/** The record's lines, for a record the caller already read. */
export function SinceEntryLines({ record, className, collapsible = false }: { record: PositionRecord; className?: string; collapsible?: boolean }) {
  const [open, setOpen] = useState(!collapsible);
  const since = record.since_entry;
  const facts = sinceFacts(record);
  const gaps = (since?.lines ?? []).filter(l => l.state !== "ok").length + (since ? 0 : 1);
  const asOf = since ? clockOf(since.as_of) : null;
  const title = <span className="font-medium text-foreground">Since you entered</span>;
  return (
    <section aria-label="Since you entered" data-testid="since-entry" className={cn("space-y-1.5 text-xs", className)}>
      {collapsible ? (
        <button type="button" aria-expanded={open} onClick={() => setOpen(was => !was)}
          className="flex min-h-8 w-full min-w-0 items-center gap-1.5 text-left text-muted-foreground hover:text-foreground">
          <span aria-hidden>{open ? "▾" : "▸"}</span>{title}
          {!open && facts.length > 0 && <span className="truncate" data-testid="since-entry-summary">· {facts.map(f => f.short).join(" · ")}</span>}
        </button>
      ) : <p className="text-muted-foreground">{title} · {record.contract}</p>}
      {open && <>
        {facts.length > 0 && (
          <ul aria-label="Since entry facts" className="space-y-1 text-sm text-foreground">
            {facts.map(f => <li key={f.key} data-fact={f.key}>{f.text}</li>)}
          </ul>
        )}
        <details className="text-muted-foreground" data-testid="since-entry-sources">
          <summary className="cursor-pointer py-1 hover:text-foreground">Sources and gaps{gaps ? ` · ${gaps} unavailable` : ""}</summary>
          <div className="mt-1 space-y-1.5">
            <p>{record.contract}{asOf ? ` · as of ${asOf} ET` : ""}</p>
            <p data-testid="since-entry-thesis">{thesisText(record)}</p>
            {since ? (
              <ul className="space-y-1">
                {since.lines.map(line => (
                  <li key={line.key} data-state={line.state} className="flex flex-wrap gap-x-2">
                    <span>{line.key === "headlines" && line.state === "ok" ? headlineText(line) : line.text}</span>
                    <span className="opacity-80">{line.source}{clockOf(line.as_of) ? ` · ${clockOf(line.as_of)} ET` : ""}</span>
                    {line.headlines?.length ? (
                      <ul className="basis-full space-y-0.5 pl-3">
                        {line.headlines.map(h => <li key={`${h.at}${h.headline}`}>{h.headline}{h.publisher ? ` · ${h.publisher}` : ""}{clockOf(h.at) ? ` · ${whenOf(h.at)} ET` : ""}</li>)}
                      </ul>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : <p>Since-entry lines unavailable.</p>}
            {record.decisions.length > 0 && (
              <p>Your decisions: {record.decisions.map(d => d.text).filter(Boolean).join(" · ")}</p>
            )}
          </div>
        </details>
      </>}
    </section>
  );
}

/** Reads the symbol's records and shows the one for ``tradeId`` (else the first). Nothing while there is no position. On
 * the desk the symbol's last read (its "as of" on it) shows at once while the fresh one is on the way. */
export default function SinceEntry({ symbol, tradeId = null, className, collapsible = false }: {
  symbol: string; tradeId?: string | null; className?: string; collapsible?: boolean;
}) {
  const [read, setRead] = useState<{ symbol: string; records: PositionRecord[] } | { symbol: string; error: true } | null>(null);
  const [kept, keep] = useKept<PositionRecord[]>(`desk.since:${symbol}`);
  useEffect(() => {
    let controller = new AbortController();
    const load = () => {
      controller.abort();
      controller = new AbortController();
      const signal = controller.signal;
      fetchPositionContext(symbol, signal)
        .then(data => { if (!signal.aborted) { setRead({ symbol, records: data.positions }); keep(data.positions); } })
        .catch(() => { if (!signal.aborted) setRead({ symbol, error: true }); });
    };
    load();
    const timer = setInterval(() => { if (document.visibilityState === "visible") load(); }, REFRESH_MS);
    return () => { controller.abort(); clearInterval(timer); };
  }, [symbol, keep]);
  const shown = read?.symbol === symbol ? read : kept ? { symbol, records: kept } : null;
  if (!shown) return null;
  if ("error" in shown) return <p role="status" className={cn("text-xs text-muted-foreground", className)}>Since-entry context unavailable right now.</p>;
  const record = shown.records.find(r => r.trade_id === tradeId) ?? shown.records[0];
  return record ? <SinceEntryLines record={record} className={className} collapsible={collapsible} /> : null;
}
