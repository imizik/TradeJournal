"use client";

import { useEffect, useState, type ReactNode } from "react";
import PingsRows, { alertsVerdict, radarVerdict } from "@/components/copilot/PingsRows";
import { getDayReport, getDeskPings, signedPct, type CheckedCallRow, type CheckTally, type DayReport as Report, type DeskPings } from "@/lib/desk";
import { cn } from "@/lib/utils";

const ET = "America/New_York";
const tone = (value: number) => (value > 0 ? "text-emerald-300" : value < 0 ? "text-rose-300" : "text-muted-foreground");
const clock = (iso: string) => new Date(iso).toLocaleTimeString("en-US", { timeZone: ET, hour: "numeric", minute: "2-digit" });
const price = (value: number) => value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const ENTRY_WORDS = { planned: "plan saved first", late: "plan saved after the fill", unplanned: "no plan", pending: "plan being linked" } as const;
const DECISION_WORDS = { planned: "you planned it", passed: "you passed", neither: "no plan, not passed" } as const;

/** "5 up, 7 down, 2 not measured": only the parts that happened, each counted from the price when he checked (the label
 * says so once). Counts, never advice. */
export function checkedParts(t: CheckTally): string {
  return [t.up && `${t.up} up`, t.down && `${t.down} down`, t.flat && `${t.flat} flat`,
    t.not_measured && `${t.not_measured} not measured`].filter(Boolean).join(", ");
}

/** The calls line after its label: the last 30 days first ("14 · 5 up, 7 down, 2 not measured"), then today's. Null when
 * nothing was checked in the window. The label is ``callsLabel``. */
export const callsLabel = (days: number) => `Calls checked, last ${days} days, since you checked`;
export function callsLine(checks: NonNullable<Report["checks"]>): string | null {
  const month = checks.window;
  if (!month.checked) return null;
  const today = checks.today;
  return `${month.checked}${checkedParts(month) ? ` · ${checkedParts(month)}` : ""} · Today: ${today.checked ? `${today.checked}${checkedParts(today) ? ` (${checkedParts(today)})` : ""}` : "none"}`;
}

/** One line that opens its rows on tap. */
function Line({ label, sep = " · ", summary, testId, children }: { label: string; sep?: string; summary: ReactNode; testId: string; children: ReactNode }) {
  return (
    <details className="group" data-testid={testId}>
      <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 px-3 py-2 [&::-webkit-details-marker]:hidden">
        <span className="min-w-0 flex-1 text-xs text-foreground/90">
          <span className="font-medium text-foreground">{label}</span>
          <span className="text-muted-foreground">{sep}</span>{summary}
        </span>
        <span aria-hidden className="text-xs text-muted-foreground group-open:rotate-180">▾</span>
      </summary>
      <div className="border-t px-3 py-3">{children}</div>
    </details>
  );
}

function CheckRow({ row }: { row: CheckedCallRow }) {
  const measured = row.state === "measured" && row.stock;
  return (
    <li data-testid="checked-call" className="space-y-0.5 text-xs">
      <p className="flex flex-wrap items-baseline gap-x-2">
        <span className="font-medium text-foreground">{row.label}</span>
        <span className="text-muted-foreground">{clock(row.checked_at)} · {row.verdict ?? "no verdict"} · {DECISION_WORDS[row.decision]}</span>
      </p>
      {measured ? (
        <p className="text-muted-foreground">
          {row.symbol} <span className="tabular-nums">{price(row.stock!.at_check)} → {price(row.stock!.close)}</span>{" "}
          <span className={cn("tabular-nums font-medium", tone(row.stock!.pct))}>{signedPct(row.stock!.pct, 1)}</span> at the close
          {row.contract
            ? <> · contract <span className="tabular-nums">{price(row.contract.at_check)} → {price(row.contract.close)}</span>{" "}
              <span className={cn("tabular-nums font-medium", tone(row.contract.pct))}>{signedPct(row.contract.pct, 0)}</span></>
            : row.contract_note ? <> · contract: {row.contract_note}</> : null}
          {row.way && <> · <span className="text-foreground/85">reads {row.way}{row.way !== "flat" ? " since you checked" : ""}</span></>}
        </p>
      ) : <p className="text-muted-foreground">Not measured: {row.why}</p>}
    </li>
  );
}

/**
 * The cockpit's after-close day report (docs/copilot-lab.md § The desk): one card, three single lines that each open
 * their rows on tap, in this order: Today (entries and how many had a plan before the fill), How the pings did (today's
 * position alerts and alerted Radar hits) and Calls checked (scored from the price when he checked to the close, the
 * last 30 days first). Realized P&L is the top bar's and an open position without a plan is the book's (its No plan tag),
 * so neither is repeated here. A line with nothing in it is absent; a day with nothing says so in one sentence. The app
 * scores everything itself and asks for no rating; facts and counts, no advice.
 */
export default function DayReport() {
  const [report, setReport] = useState<Report | null | undefined>(undefined);
  const [pings, setPings] = useState<DeskPings | null | undefined>(undefined);
  useEffect(() => {
    const controller = new AbortController();
    getDayReport(controller.signal).then(setReport).catch(() => { if (!controller.signal.aborted) setReport(null); /* the card is extra */ });
    getDeskPings(controller.signal, true).then(setPings).catch(() => { if (!controller.signal.aborted) setPings(null); });
    return () => controller.abort();
  }, []);
  if (report === undefined || pings === undefined) return null;

  const entries = report?.entries ?? null;
  const showToday = (entries?.entries ?? 0) > 0;
  const alerts = pings?.alerts.rows ?? [], hits = pings?.radar.rows ?? [];
  const pingParts = [alertsVerdict(alerts), radarVerdict(hits)].filter(Boolean);
  const calls = report?.checks ? callsLine(report.checks) : null;
  if (!showToday && !pingParts.length && !calls) {
    return <p data-testid="day-report-card" className="rounded-lg border bg-card px-3 py-2.5 text-xs text-muted-foreground">Nothing to report today: no entries, pings or checked calls.</p>;
  }
  return (
    <div data-testid="day-report-card" className="divide-y overflow-hidden rounded-lg border bg-card">
      {showToday && (
        <Line label="Today" testId="report-today" summary={
          entries && <span data-testid="report-today-line">{/* only the figures in the mono face */}<span className="tabular-nums">{entries.entries}</span> {entries.entries === 1 ? "entry" : "entries"}, <span className="tabular-nums">{entries.planned}</span> with a plan saved before the fill</span>}>
          {entries && entries.rows.length > 0 ? (
            <ul className="space-y-1.5 text-xs">
              {entries.rows.map((e, i) => (
                <li key={`${e.at}-${i}`} data-testid="report-entry" className="flex flex-wrap items-baseline gap-x-2">
                  <span className="font-medium text-foreground">{e.contract}</span>
                  <span className="text-muted-foreground">{new Date(e.at * 1000).toLocaleTimeString("en-US", { timeZone: ET, hour: "numeric", minute: "2-digit" })} · {ENTRY_WORDS[e.state]}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </Line>
      )}
      {pingParts.length > 0 && pings && (
        <Line label="How the pings did" testId="report-pings" summary={<span data-testid="pings-verdict">{pingParts.join(" · ")}</span>}>
          <PingsRows data={pings} />
        </Line>
      )}
      {calls && report?.checks && (
        <Line label={callsLabel(report.checks.window.days)} sep=": " testId="report-calls" summary={<span data-testid="calls-verdict">{calls}</span>}>
          {report.checks.rows.length > 0
            ? <ul className="space-y-2.5">{report.checks.rows.map(row => <CheckRow key={row.id} row={row} />)}</ul>
            : <p className="text-xs text-muted-foreground">No call checked today.</p>}
          <p className="mt-2.5 text-xs text-muted-foreground">
            Up and down are the contract&apos;s move when both its prices are known, otherwise the stock&apos;s (reversed for a put), from the
            price when you checked to the close; never the price in the post. Nothing here needs an answer.
          </p>
        </Line>
      )}
    </div>
  );
}
