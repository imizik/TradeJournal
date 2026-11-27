"use client";

import { useEffect, useState } from "react";
import { getDayCall, type DayCall, type DayCallFlip } from "@/lib/desk";
import { cn } from "@/lib/utils";

/**
 * The day call (docs/copilot-lab.md § The day call): Claude's risk-on, risk-off or mixed read of the session, at the top
 * of the copilot's column before a conversation starts. The server makes the call at 09:45 New York and asks again only
 * when one of its own flip checks holds or SPY moves sharply; this shows the latest call, what it flipped from, what
 * would flip it next, and its paper record so far. It is a paper call: nothing here tells him to buy or sell.
 */
const NAMES = { risk_on: "Risk on", risk_off: "Risk off", mixed: "Mixed" } as const;
const TONE = { risk_on: "text-emerald-300", risk_off: "text-rose-300", mixed: "text-amber-200" } as const;
const METRICS: Record<string, [string, boolean]> = {
  spy_price: ["SPY", false], spy_vs_vwap_pct: ["SPY vs VWAP", true], spy_from_open_pct: ["SPY from open", true],
  spy_day_pct: ["SPY on the day", true], qqq_day_pct: ["QQQ on the day", true], iwm_day_pct: ["IWM on the day", true],
  rsp_minus_spy_pct: ["RSP minus SPY", true], vix: ["VIX", false],
};

export function flipText(flip: DayCallFlip): string {
  const [name, pct] = METRICS[flip.metric] ?? [flip.metric, false];
  const value = pct ? `${flip.value > 0 ? "+" : ""}${flip.value.toFixed(2)}%` : flip.value.toFixed(2);
  return `${name} ${flip.op} ${value}`;
}

/** Today's day call, read every minute while ``active`` and the page is in view; null until the first answer. */
export function useDayCall(active: boolean): DayCall | null {
  const [found, setFound] = useState<DayCall | null>(null);
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    let timer = 0;
    const read = () => {
      if (document.visibilityState === "hidden") return;
      getDayCall(controller.signal).then(answer => {
        setFound(answer);
        if (!answer.enabled) {  // switched off on the server: no more reads until the page loads again
          window.clearInterval(timer);
          document.removeEventListener("visibilitychange", read);
        }
      }).catch(() => undefined);  // a missed read keeps the last one
    };
    read();
    timer = window.setInterval(read, 60_000);
    document.addEventListener("visibilitychange", read);
    return () => { controller.abort(); window.clearInterval(timer); document.removeEventListener("visibilitychange", read); };
  }, [active]);
  return found;
}

export function DeskDayCall({ found }: { found: DayCall }) {
  const calls = found.calls;
  const now = calls[calls.length - 1];
  if (!now) return null;
  const before = calls.length > 1 ? calls[calls.length - 2] : null;
  const flipped = before && before.call !== now.call ? before : null;
  const record = found.record;
  return (
    <section aria-label="Day call" data-testid="day-call" className="mb-2 rounded-lg border bg-card px-3 py-2.5">
      <p className="text-sm">
        <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Day call </span>
        <span data-testid="day-call-call" className={cn("font-semibold", TONE[now.call])}>{NAMES[now.call]}</span>
        <span className="text-xs text-muted-foreground"> · {flipped ? `since ${now.time_et}, was ${NAMES[flipped.call].toLowerCase()}` : `at ${now.time_et}`}</span>
      </p>
      <p data-testid="day-call-read" className="mt-1 text-sm text-foreground">{now.changed ?? now.read}</p>
      {now.flips.length > 0 && (
        <p data-testid="day-call-flips" className="mt-1 text-xs tabular-nums text-muted-foreground">
          Flips if {now.flips.map(flipText).join(" · ")}
        </p>
      )}
      <p data-testid="day-call-record" className="mt-1 text-[11px] text-muted-foreground">
        Paper call{calls.length > 1 ? ` · ${calls.length} calls today` : ""} · {record.scored
          ? `${record.right} of ${record.scored} right over ${record.days} ${record.days === 1 ? "day" : "days"}`
          : "no scored days yet"}
      </p>
    </section>
  );
}
