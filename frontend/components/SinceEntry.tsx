"use client";

import { useEffect, useState } from "react";
import { fetchPositionContext, type PositionRecord } from "@/lib/chartJournal";
import { cn } from "@/lib/utils";

/*
 * "Since you entered": one open position's thesis and what changed since the entry, from its one record
 * (GET /charts/journal/positions/{symbol}/context, backend engine/trader_context.py). Shared by the Copilot desk's
 * thread header and Charts' Holding context, so both say the same thing. Each line names its source and time; a missing
 * input reads "unavailable", never zero. Read when shown, then each minute while the page is visible. Read-only.
 */

const REFRESH_MS = 60_000;
const SOURCE: Record<PositionRecord["thesis"]["source"], string> = {
  plan_card: "Plan card", plan_sheet: "Charts plan", companion: "Adopted by the companion", none: "No plan",
};

export const clockOf = (iso: string | null) => {
  if (!iso) return null;
  const at = new Date(iso);
  return Number.isNaN(at.getTime()) ? null : at.toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });
};

export function thesisText(record: PositionRecord): string {
  const t = record.thesis;
  if (t.source === "none") return "No plan saved for this position: no thesis, invalidation or time stop on file.";
  const words = t.text ? (t.text_is_guess ? `${t.text} (the companion's guess)` : t.text) : "No thesis in words.";
  const level = t.invalidation ? ` Invalidation ${t.invalidation.price.toFixed(2)} (${t.invalidation.state}).` : "";
  return `${SOURCE[t.source]}: ${words}${level}`;
}

/** The record's lines, for a record the caller already read. */
export function SinceEntryLines({ record, className }: { record: PositionRecord; className?: string }) {
  const since = record.since_entry;
  return (
    <section aria-label="Since you entered" data-testid="since-entry" className={cn("space-y-1.5 text-xs", className)}>
      <p className="text-muted-foreground">
        <span className="font-medium text-foreground">Since you entered</span>
        {since && clockOf(since.as_of) && <> · as of {clockOf(since.as_of)} ET</>} · {record.contract}
      </p>
      <p className="text-muted-foreground" data-testid="since-entry-thesis">{thesisText(record)}</p>
      {since ? (
        <ul className="space-y-1">
          {since.lines.map(line => (
            <li key={line.key} data-state={line.state} className="flex flex-wrap gap-x-2">
              <span className={line.state === "ok" ? "text-foreground" : "text-amber-300"}>{line.text}</span>
              <span className="text-muted-foreground">{line.source}{clockOf(line.as_of) ? ` · ${clockOf(line.as_of)}` : ""}</span>
              {line.headlines?.length ? (
                <ul className="basis-full space-y-0.5 pl-3 text-muted-foreground">
                  {line.headlines.map(h => <li key={`${h.at}${h.headline}`}>{h.headline}{h.publisher ? ` · ${h.publisher}` : ""}</li>)}
                </ul>
              ) : null}
            </li>
          ))}
        </ul>
      ) : <p className="text-amber-300">Since-entry lines unavailable.</p>}
      {record.decisions.length > 0 && (
        <p className="text-muted-foreground">Your decisions: {record.decisions.map(d => d.text).filter(Boolean).join(" · ")}</p>
      )}
    </section>
  );
}

/** Reads the symbol's records and shows the one for ``tradeId`` (else the first). Nothing while there is no position. */
export default function SinceEntry({ symbol, tradeId = null, className }: { symbol: string; tradeId?: string | null; className?: string }) {
  const [read, setRead] = useState<{ symbol: string; records: PositionRecord[] } | { symbol: string; error: true } | null>(null);
  useEffect(() => {
    let controller = new AbortController();
    const load = () => {
      controller.abort();
      controller = new AbortController();
      const signal = controller.signal;
      fetchPositionContext(symbol, signal)
        .then(data => { if (!signal.aborted) setRead({ symbol, records: data.positions }); })
        .catch(() => { if (!signal.aborted) setRead({ symbol, error: true }); });
    };
    load();
    const timer = setInterval(() => { if (document.visibilityState === "visible") load(); }, REFRESH_MS);
    return () => { controller.abort(); clearInterval(timer); };
  }, [symbol]);
  if (!read || read.symbol !== symbol) return null;
  if ("error" in read) return <p role="status" className={cn("text-xs text-amber-300", className)}>Since-entry context unavailable right now.</p>;
  const record = read.records.find(r => r.trade_id === tradeId) ?? read.records[0];
  return record ? <SinceEntryLines record={record} className={className} /> : null;
}
