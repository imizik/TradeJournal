"use client";

import { useGmailHealthSnapshot } from "@/lib/useGmailHealth";

const when = (value: string) => new Date(value).toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

/** One line under Attention: whether fills are still arriving, and when the last check was. */
export default function DataFreshness() {
  const { health, state, lastSuccessAt } = useGmailHealthSnapshot();
  const gmail = state === "unavailable" ? "status unavailable" : health ? health.status : "checking…";
  return <div aria-label="Import freshness" className="min-w-0 px-1 text-xs text-muted-foreground">
    <p className="tabular-nums">
      <span className="font-medium text-foreground">Import freshness</span> · Gmail: {gmail}
      {health?.last_import_at
        ? <> · Last successful import check: <time dateTime={health.last_import_at}>{when(health.last_import_at)} ET</time></>
        : health ? " · No successful import check recorded." : state === "unavailable" ? " · Import status could not load." : " · Checking import status…"}
    </p>
    {state === "unavailable" && <p className="mt-1 text-amber-300">{lastSuccessAt ? <>Showing historical import data; last status check {when(lastSuccessAt)} ET.</> : "Status will retry on the next shared refresh."}</p>}
  </div>;
}
