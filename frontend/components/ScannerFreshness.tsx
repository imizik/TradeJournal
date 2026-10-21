"use client";

import { useEffect, useTransition } from "react";
import { useRouter } from "next/navigation";
import type { ScannerMonitoring } from "@/lib/api";

const REFRESH_SECONDS = 60;

function etTime(iso: string, seconds = true) {
  return new Date(iso).toLocaleTimeString("en-US", {
    timeZone: "America/New_York", hour: "numeric", minute: "2-digit", ...(seconds ? { second: "2-digit" } : {}),
  });
}

// The page load time says nothing about the scanner; only a judged bar does.
function monitoringText(m: ScannerMonitoring): { text: string; warn: boolean } {
  const judged = m.last_judged_bar_end
    ? `last judged the ${etTime(m.last_judged_bar_end, false)} ET bar close for ${m.symbols_judged} / ${m.symbols_selected} tickers`
    : "no setup bar judged yet today";
  switch (m.state) {
    case "fresh": return { text: `Current — ${judged}.`, warn: false };
    case "stale": return { text: `Stale — ${judged}; a newer bar should have been judged by now. Refreshing this page does not fix this.`, warn: true };
    case "outside_window": return { text: `Not scanning now (setup bars close 9:50 AM–3:00 PM ET) — ${judged}.`, warn: false };
    case "market_closed": return { text: "Market closed today — no scanning.", warn: false };
    case "calendar_unknown": return { text: "Market calendar unavailable, so scanning freshness is unknown.", warn: true };
    case "not_running": return { text: "Switched on but not running in this server process — no setups are being judged.", warn: true };
    default: return { text: "Switched off on this server.", warn: true };
  }
}

export default function ScannerFreshness({ updatedAt, monitoring, live }: { updatedAt: string; monitoring: ScannerMonitoring; live: boolean }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const refresh = () => startTransition(() => router.refresh());

  useEffect(() => {
    if (!live) return;
    const tick = () => { if (document.visibilityState === "visible") refresh(); };
    const timer = window.setInterval(tick, REFRESH_SECONDS * 1000);
    document.addEventListener("visibilitychange", tick);
    return () => { window.clearInterval(timer); document.removeEventListener("visibilitychange", tick); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live]);

  const status = monitoringText(monitoring);
  return (
    <section aria-label="Scanner freshness" className="space-y-1 rounded-lg border bg-card px-4 py-3 text-sm">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <button type="button" onClick={refresh} disabled={pending}
          className="inline-flex min-h-11 items-center rounded border px-3 hover:bg-secondary disabled:opacity-50">
          {pending ? "Refreshing…" : "Refresh"}
        </button>
        <span className="text-muted-foreground">
          Page updated at <span className="tabular-nums text-foreground">{etTime(updatedAt)} ET</span>
          {live ? ` · refreshes every ${REFRESH_SECONDS} s while this tab is visible` : " · past day, no auto-refresh"}
        </span>
      </div>
      <p className={status.warn ? "text-amber-300" : "text-muted-foreground"}>
        <span className="font-medium text-foreground">Scanner monitoring now:</span> {status.text}
        <span className="ml-1 text-xs">(checked {etTime(monitoring.checked_at)} ET)</span>
      </p>
    </section>
  );
}
