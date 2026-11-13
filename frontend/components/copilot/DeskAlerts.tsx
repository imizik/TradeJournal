"use client";

/*
 * The desk chart's Alerts list (docs/copilot-lab.md § The desk): the symbol's armed level alerts, the same rows Charts'
 * Alerts panel lists (``/charts/alerts``), opened from the chart's header. Each can be moved to another price (the
 * alert is armed again there, which way judged from the last price) or removed; a plan's own alert is changed from its
 * plan. No new kind of alert.
 */

import { useState, type FormEvent } from "react";
import { Bell, Trash2 } from "lucide-react";
import type { DeskChartAlert } from "@/lib/desk";
import { cn } from "@/lib/utils";

export function AlertsButton({ count, open, onToggle }: { count: number; open: boolean; onToggle(): void }) {
  return (
    <button type="button" aria-expanded={open} onClick={onToggle} data-testid="desk-alerts-toggle"
      aria-label={`Alerts on this symbol: ${count}`} title={open ? "Hide the alerts" : "This symbol's armed alerts: move or remove them"}
      className={cn("inline-flex min-h-11 items-center gap-1 rounded border px-1.5 text-xs tabular-nums sm:min-h-0 sm:py-0.5",
        open ? "border-foreground/60 text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
      <Bell size={12} aria-hidden className={count ? "text-amber-300" : undefined} />{count}
    </button>
  );
}

/** One row per alert: what it waits for, its label, Move (a price, then Move) and Remove. */
export function AlertList({ alerts, last, onMove, onRemove }: {
  alerts: DeskChartAlert[]; last: number | null; onMove(alert: DeskChartAlert, price: number): void; onRemove(alert: DeskChartAlert): void;
}) {
  const [moving, setMoving] = useState<{ id: string; text: string; bad: boolean } | null>(null);
  const submit = (event: FormEvent, alert: DeskChartAlert) => {
    event.preventDefault();
    const value = Number((moving?.text ?? "").replace(/[$,\s]/g, ""));
    if (!Number.isFinite(value) || value <= 0 || (last !== null && Math.abs(value - last) < 0.005)) { setMoving(m => m && { ...m, bad: true }); return; }
    setMoving(null);
    onMove(alert, Math.round(value * 100) / 100);
  };
  if (!alerts.length) {
    return <p data-testid="desk-chart-alerts" className="text-xs text-muted-foreground">No armed alerts on this symbol. Right-click or long-press the chart (or a line) to set one.</p>;
  }
  const button = "inline-flex min-h-11 items-center justify-center rounded px-1.5 text-xs sm:min-h-0 sm:py-0.5";
  return (
    <ul data-testid="desk-chart-alerts" aria-label="Alerts on this symbol" className="space-y-0.5 rounded border border-amber-300/20 p-1 text-xs tabular-nums">
      {alerts.map(alert => (
        <li key={alert.id} className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 px-1">
          <Bell size={12} aria-hidden className="shrink-0 text-amber-300" />
          <span className="text-amber-100">{alert.text}</span>
          {alert.label && <span className="min-w-0 truncate text-muted-foreground">· {alert.label}</span>}
          {!alert.removable ? <span className="ml-auto text-muted-foreground">change it from its plan</span>
            : moving?.id === alert.id ? (
              <form onSubmit={event => submit(event, alert)} className="ml-auto flex items-center gap-1">
                <input autoFocus inputMode="decimal" aria-label={`New price for ${alert.text}`} value={moving.text}
                  onChange={event => setMoving({ id: alert.id, text: event.target.value, bad: false })}
                  className={cn("min-h-11 w-20 rounded border bg-background px-1.5 text-xs sm:min-h-0 sm:py-0.5", moving.bad && "border-rose-400")} />
                <button type="submit" className={cn(button, "border text-foreground")}>Move</button>
                <button type="button" onClick={() => setMoving(null)} className={cn(button, "text-muted-foreground hover:text-foreground")}>Cancel</button>
              </form>
            ) : (
              <span className="ml-auto flex items-center gap-0.5">
                <button type="button" onClick={() => setMoving({ id: alert.id, text: alert.price.toFixed(2), bad: false })} aria-label={`Move alert: ${alert.text}`}
                  title="Arm it at another price" className={cn(button, "text-muted-foreground hover:text-foreground")}>Move</button>
                <button type="button" onClick={() => onRemove(alert)} aria-label={`Remove alert: ${alert.text}`} title="Remove it (you can undo)"
                  className={cn(button, "min-w-11 text-muted-foreground hover:text-rose-300 sm:min-w-0")}><Trash2 size={12} aria-hidden /></button>
              </span>
            )}
        </li>
      ))}
    </ul>
  );
}
