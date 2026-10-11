"use client";

import { useGmailHealthSnapshot } from "@/lib/useGmailHealth";

export default function DataFreshness() {
  const { health, state, lastSuccessAt } = useGmailHealthSnapshot();
  return <div aria-label="Import freshness" className="min-w-0 rounded-lg border bg-card px-4 py-3 text-xs">
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <p className="font-medium">Import freshness</p>
      <p className="text-muted-foreground">Gmail: {state === "unavailable" ? "status unavailable" : health ? health.status : "checking…"}</p>
    </div>
    <p className="mt-1 tabular-nums text-muted-foreground">
      {health?.last_import_at
        ? <>Last successful import check: <time dateTime={health.last_import_at}>{new Date(health.last_import_at).toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} ET</time></>
        : health ? "No successful import check recorded." : state === "unavailable" ? "Import status could not load." : "Checking import status…"}
    </p>
    {state === "unavailable" && <p className="mt-1 text-amber-300">{lastSuccessAt ? <>Showing historical import data; last status check {new Date(lastSuccessAt).toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} ET.</> : "Status will retry on the next shared refresh."}</p>}
    <p className="mt-1 text-muted-foreground">Position quote timestamps unavailable; marks are not labeled live.</p>
  </div>;
}
