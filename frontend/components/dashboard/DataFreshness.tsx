"use client";

import { useGmailHealth } from "@/lib/useGmailHealth";

export default function DataFreshness() {
  const health = useGmailHealth();
  return <div aria-label="Import freshness" className="min-w-0 rounded-lg border bg-card px-4 py-3 text-xs">
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <p className="font-medium">Import freshness</p>
      <p className="text-muted-foreground">Gmail: {health ? health.status === "off" ? "off" : health.status : "checking…"}</p>
    </div>
    <p className="mt-1 tabular-nums text-muted-foreground">
      {health?.last_import_at
        ? <>Last successful import check: <time dateTime={health.last_import_at}>{new Date(health.last_import_at).toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} ET</time></>
        : health ? "No successful import check recorded." : "Checking import status…"}
    </p>
    <p className="mt-1 text-muted-foreground">Position quote timestamps unavailable; marks are not labeled live.</p>
  </div>;
}
