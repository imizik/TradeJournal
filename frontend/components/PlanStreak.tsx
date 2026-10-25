"use client";

import Link from "next/link";
import { useSyncExternalStore } from "react";
import { Flame } from "lucide-react";
import { useAppAccess } from "@/components/AccessProvider";
import { apiUrl } from "@/lib/api";
import { cn } from "@/lib/utils";

/** The plan streak (GET /charts/captures/streak): the owner's latest entries planned before entry, newest first. */
export type PlanStreak = {
  show: boolean; since: number; tracking: boolean; current: number; best: number; pending: number;
  this_week: { planned: number; total: number; pending: number; start: number };
  last_break: { contract: string; short: string; entry_time: number; reason: "no_plan" | "late" } | null;
};

export const REVIEW_WEEK = `/copilot-lab?${new URLSearchParams({ context: "Review my week" })}`;
const POLL_MS = 5 * 60_000;

// One read shared by every chip (sidebar, rail, phone header, menu): on mount, every five
// minutes while the tab is visible, and again when the window regains focus.
let streak: PlanStreak | null = null;
let timer: ReturnType<typeof setInterval> | null = null;
const listeners = new Set<() => void>();

async function refresh() {
  try {
    const response = await fetch(apiUrl("/charts/captures/streak"), { cache: "no-store" });
    if (!response.ok) return;
    streak = await response.json();
    listeners.forEach((listener) => listener());
  } catch { /* keep the last answer */ }
}

function onFocus() {
  if (!document.hidden) void refresh();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  if (listeners.size === 1) {
    void refresh();
    timer = setInterval(() => { if (!document.hidden) void refresh(); }, POLL_MS);
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      if (timer) clearInterval(timer);
      timer = null;
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onFocus);
    }
  };
}

const noop = () => () => {};
const read = () => streak;
const none = () => null;

function at(seconds: number): string {
  const when = new Date(seconds * 1000);
  const day = (d: Date) => d.toLocaleDateString("en-US", { timeZone: "America/New_York" });
  const time = when.toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit", hour12: false });
  return day(when) === day(new Date()) ? time : `${when.toLocaleDateString("en-US", { timeZone: "America/New_York", weekday: "short" })} ${time}`;
}

function describe(s: PlanStreak): string {
  const run = s.current === 1 ? "1 entry planned before entry" : `${s.current} entries in a row planned before entry`;
  const week = `This week ${s.this_week.planned} of ${s.this_week.total} planned`;
  const pending = s.pending ? ` ${s.pending} waiting to be linked.` : "";
  const last = s.last_break ? ` Last unplanned: ${s.last_break.contract} at ${at(s.last_break.entry_time)}${s.last_break.reason === "late" ? " (plan saved late)" : ""}.` : "";
  return `Plan streak: ${s.current ? run : "0 planned"}. ${week}, best ${s.best}.${pending}${last} Open Review my week.`;
}

/**
 * The nav's plan streak chip, owner-only and hidden until tracking is on or a plan exists.
 * ``full`` sits in the sidebar, ``menu`` in the phone menu, ``compact`` in the phone title bar, ``rail`` in the charts rail.
 */
export default function PlanStreakChip({ variant = "full", onNavigate }: { variant?: "full" | "menu" | "compact" | "rail"; onNavigate?: () => void }) {
  const { owner } = useAppAccess();
  const data = useSyncExternalStore(owner ? subscribe : noop, owner ? read : none, none);
  if (!owner || !data?.show) return null;
  const lit = data.current > 0;
  const label = describe(data);
  // The rail and the phone title bar carry the count alone; the label says the rest. In the title bar the
  // 44px tap area absorbs the bar's gaps (-mx-2) so the title and the sync line keep their room.
  const text = variant === "rail" || variant === "compact" ? `${data.current}`
    : lit ? `${data.current} planned`
    : !data.last_break ? "0 planned"
    : `0 planned · last: ${data.last_break.short} ${at(data.last_break.entry_time)}`;
  return (
    <Link href={REVIEW_WEEK} onClick={onNavigate} aria-label={label} title={variant === "rail" ? undefined : label} data-testid={`plan-streak-${variant}`}
      className={cn("flex shrink-0 items-center gap-1 rounded-md text-[11px] font-medium tabular-nums transition-colors hover:bg-secondary hover:text-foreground",
        lit ? "text-foreground" : "text-muted-foreground",
        variant === "rail" ? "h-10 w-10 justify-center" : variant === "compact" ? "-mx-2 h-11 min-w-11 justify-center px-2"
          : variant === "menu" ? "mt-1 -ml-2 min-h-11 min-w-0 max-w-full px-2" : "mt-1 -ml-1 min-w-0 max-w-full px-1 py-0.5")}>
      <Flame aria-hidden className={cn("h-3.5 w-3.5 shrink-0", lit ? "text-amber-400" : "text-muted-foreground")} />
      <span className="truncate">{text}</span>
    </Link>
  );
}
