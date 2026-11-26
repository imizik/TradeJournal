"use client";

import { useEffect, useState, type ReactNode } from "react";
import PingsRows, { alertsVerdict, radarVerdict } from "@/components/copilot/PingsRows";
import { getDayReport, getDeskPings, signedPct, type CheckedCallRow, type CheckTally, type DayReport as Report, type DeskPings, type DeskThread } from "@/lib/desk";
import { cn } from "@/lib/utils";

const ET = "America/New_York";
const tone = (value: number) => (value > 0 ? "text-emerald-300" : value < 0 ? "text-rose-300" : "text-muted-foreground");
const clock = (iso: string) => new Date(iso).toLocaleTimeString("en-US", { timeZone: ET, hour: "numeric", minute: "2-digit" });
const price = (value: number) => value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const ENTRY_WORDS = { planned: "plan saved first", late: "plan saved after the fill", unplanned: "no plan", pending: "plan being linked" } as const;
const DECISION_WORDS = { planned: "you planned it", passed: "you passed", neither: "no plan, not passed" } as const;

/** "5 up, 7 down": only the parts that happened, each counted from the price when he checked (the label says so once).
 * Calls with no price to score them by are in the count but never spelled out. Counts, never advice. */
export function checkedParts(t: CheckTally): string {
  return [t.up && `${t.up} up`, t.down && `${t.down} down`, t.flat && `${t.flat} flat`].filter(Boolean).join(", ");
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
 * position alerts and alerted Radar hits), Calls checked (scored from the price when he checked to the close, the
 * last 30 days first) and Open without a plan (the followed options with no invalidation or time stop: the one place the
 * desk names them; the book shows no tag for it and the strip never asks). Realized P&L is the top bar's. A line with
 * nothing in it is absent; a day with nothing says so in one sentence. The app scores everything itself and asks for no
 * rating; facts and counts, no advice. ``rows`` are the desk's rows; ``onOpen`` opens one.
 */
export default function DayReport({ rows = [], rowsRead = true, onOpen }: { rows?: DeskThread[]; rowsRead?: boolean; onOpen?(row: DeskThread): void } = {}) {
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
  const measuredChecks = report?.checks?.rows.filter(r => r.state === "measured") ?? [];
  const card = report?.card ?? null;
  const unplanned = rows.filter(r => (r.key.startsWith("trade:") || r.key.startsWith("robinhood:")) && r.symbol && !r.hidden && r.book
    && r.instrument !== "stock" && !(r.book.planned ?? r.book.state !== "no_plan"));
  const bySymbol = [...new Set(unplanned.map(r => r.symbol!))];
  const details = showToday || pingParts.length > 0 || !!calls || bySymbol.length > 0;
  if (!details && !card) {
    if (!rowsRead) return null; // the positions are not read yet: not yet "nothing"
    return <p data-testid="day-report-card" className="rounded-lg border bg-card px-3 py-2.5 text-xs text-muted-foreground">Nothing to report today: no entries, pings, checked calls or open options without a plan.</p>;
  }
  return (
    <div data-testid="day-report-card" className="overflow-hidden rounded-lg border bg-card">
      {card && <Headline card={card} />}
      {details && (
        // With the headline, the rows sit behind one Details tap; an older backend without it shows them as before.
        <details data-testid="day-report-details" className={cn("group/details", card && "border-t")} open={!card || undefined}>
          {card && (
            <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 px-3 py-2 text-xs text-muted-foreground hover:text-foreground [&::-webkit-details-marker]:hidden">
              <span className="flex-1">Details</span><span aria-hidden className="group-open/details:rotate-180">▾</span>
            </summary>
          )}
          <div className={cn("divide-y", card && "border-t")}>
      {showToday && (
        <Line label="Today" testId="report-today" summary={
          entries && <span data-testid="report-today-line">{/* only the figures in the mono face */}<span className="tabular-nums">{entries.entries}</span> {entries.entries === 1 ? "entry" : "entries"}, <span className="tabular-nums">{entries.planned}</span> with a plan saved before the fill</span>}>
          {entries && entries.rows.length > 0 ? (
            <ul className="space-y-1.5 text-xs">
              {entries.rows.map((e, i) => (
                <li key={`${e.at}-${i}`} data-testid="report-entry" className="flex flex-wrap items-baseline gap-x-2">
                  <span className="font-medium text-foreground">{e.contract}</span>
                  <span className="text-muted-foreground">{new Date(e.at * 1000).toLocaleTimeString("en-US", { timeZone: ET, hour: "numeric", minute: "2-digit" })} · {ENTRY_WORDS[e.state]}</span>
                  {e.notes?.map((note, n) => <span key={n} data-testid="report-entry-note" className="basis-full text-muted-foreground">“{note}”</span>)}
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
          {measuredChecks.length > 0
            ? <ul className="space-y-2.5">{measuredChecks.map(row => <CheckRow key={row.id} row={row} />)}</ul>
            : <p className="text-xs text-muted-foreground">No call checked today could be scored yet.</p>}
        </Line>
      )}
      {/* The laptop's line only: a phone's card is the day at a glance, and planning is not asked of it there. */}
      {bySymbol.length > 0 && (
        <div className="max-md:hidden">
        <Line label="Open without a plan" testId="report-noplan" summary={<span data-testid="noplan-verdict">{bySymbol.join(", ")}</span>}>
          <ul className="space-y-1.5 text-xs">
            {unplanned.map(r => (
              <li key={r.key}>
                <button type="button" data-testid="report-noplan-row" onClick={() => onOpen?.(r)} disabled={!onOpen}
                  className="flex min-h-11 w-full flex-wrap items-baseline gap-x-2 text-left sm:min-h-0">
                  <span className="font-medium text-foreground">{r.title}</span>
                  {r.value && <span className={cn("tabular-nums", r.value.tone === "gain" ? "text-emerald-300" : r.value.tone === "loss" ? "text-rose-300" : "text-muted-foreground")}>{r.value.text}</span>}
                </button>
              </li>
            ))}
          </ul>
        </Line>
        </div>
      )}
          </div>
        </details>
      )}
    </div>
  );
}

const usd0 = (v: number) => `${v > 0.005 ? "+" : v < -0.005 ? "−" : ""}$${Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
const premium = (perContract: number) => `$${(perContract / 100).toFixed(2)}`;
/** "tomorrow" only when the next session is the next calendar day; a Friday card names Monday (as the 4:30 ping does). */
function nextLabel(day: string, next: string | null) {
  if (!next) return "tomorrow";
  const d = new Date(`${next}T12:00:00Z`);
  return d.getTime() - new Date(`${day}T12:00:00Z`).getTime() === 86_400_000 ? "tomorrow"
    : d.toLocaleDateString("en-US", { weekday: "short", timeZone: "UTC" });
}

/** The day in three lines, the same card the 4:30 ping sends (``app/engine/day_card.py``): realized P&L over the trades
 * closed today, the cut pings acted on, and what expires next session with its cut line. A line with nothing is absent. */
function Headline({ card }: { card: NonNullable<Report["card"]> }) {
  return (
    <div data-testid="day-card" className="space-y-1.5 px-3 py-3">
      <p className="flex items-baseline gap-2">
        <span className="text-sm text-muted-foreground">Realized today</span>
        {card.closed > 0
          ? <span data-testid="day-card-pnl" className={cn("text-2xl font-semibold tabular-nums", tone(card.pnl))}>{usd0(card.pnl)}</span>
          : <span data-testid="day-card-pnl" className="text-sm text-muted-foreground">nothing closed</span>}
        {card.closed > 0 && <span className="text-xs text-muted-foreground">{card.closed} closed</span>}
      </p>
      {card.cut.pings > 0 && (
        <p data-testid="day-card-cut" className="text-sm">
          Cut pings: <span className={cn("font-semibold tabular-nums", card.cut.acted < card.cut.pings ? "text-amber-300" : "text-emerald-300")}>
            acted on {card.cut.acted} of {card.cut.pings}</span>
        </p>
      )}
      {card.expiring.length > 0 && (
        <p data-testid="day-card-expiring" className="text-sm">
          <span className="text-muted-foreground">Expires {nextLabel(card.day, card.next_day)}: </span>
          {card.expiring.map((e, i) => (
            <span key={e.contract}>{i > 0 && "; "}<span className="font-medium text-foreground">{e.contract}</span> ×{e.contracts}
              {e.cut != null && <span className="text-muted-foreground">, cut line {premium(e.cut)}</span>}</span>
          ))}
        </p>
      )}
    </div>
  );
}
