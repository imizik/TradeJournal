"use client";

import { useEffect, useState, type ReactNode } from "react";
import { usePracticeLine } from "@/components/copilot/ReviewMyWeek";
import { getDeskSession, type DeskSession, type DeskSessionEvent, type DeskThread } from "@/lib/desk";
import { cn } from "@/lib/utils";

const REFRESH_MS = 60_000;
// Amber is kept for what still needs you (a time stop ahead); what already happened stays quiet.
const DOT: Record<DeskSessionEvent["kind"], string> = { fill: "bg-emerald-400", ping: "bg-muted-foreground", radar: "bg-sky-400", decision: "bg-foreground" };
const KIND: Record<DeskSessionEvent["kind"], [string, string]> = {
  fill: ["fill", "fills"], ping: ["ping", "pings"], radar: ["Radar event", "Radar events"], decision: ["decision", "decisions"],
};
const PHASE: Record<NonNullable<DeskSession["phase"]>, string> = { pre: "Pre-market", regular: "Market open", post: "After the close", closed: "Market closed" };
/** New York wall time without a leading zero ("9:30", "14:00"). */
export const hhmm = (seconds: number) => new Date(seconds * 1000)
  .toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).replace(/^0/, "");
export const pct = (value: number) => `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(2)}%`;
/** The open, every 90 minutes after it, and the close (a mark too near the close gives way to it): 9:30, 11:00, 12:30, 14:00, 16:00. */
const labelTimes = (open: number, close: number) => {
  const marks = [open];
  for (let at = open + 5400; at <= close - 2700; at += 5400) marks.push(at);
  return [...marks, close];
};
const num = (text: string | number) => <span className="tabular-nums">{text}</span>;

/** ``GET /copilot/desk/session`` once a minute while the page is visible: the desk reads it once for its bar, its phase
 * button and the Briefing. */
export function useDeskSession(on: boolean): { data: DeskSession | null; error: string | null } {
  const [data, setData] = useState<DeskSession | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!on) return;
    let controller = new AbortController();
    const read = () => {
      controller.abort();
      controller = new AbortController();
      const signal = controller.signal;
      getDeskSession(signal).then(next => { setData(next); setError(null); }).catch(failure => {
        if (!signal.aborted) setError(failure instanceof Error ? failure.message : "Today's session is unavailable.");
      });
    };
    read();
    const timer = setInterval(() => { if (document.visibilityState === "visible") read(); }, REFRESH_MS);
    const shown = () => { if (document.visibilityState === "visible") read(); };
    document.addEventListener("visibilitychange", shown);
    return () => { controller.abort(); clearInterval(timer); document.removeEventListener("visibilitychange", shown); };
  }, [on]);
  return { data, error };
}

/** The desk bar's live line: Live, Pre-market or Closed 16:00 by the session read, then SPY / QQQ / VIX's change (wide
 * screens only). Nothing until the phase is known. */
export function DeskStatus({ data }: { data: DeskSession | null }) {
  if (!data?.phase) return null;
  const word = data.phase === "regular" ? "Live" : data.phase === "pre" ? "Pre-market"
    : data.close !== null && data.now >= data.close ? `Closed ${hhmm(data.close)}` : "Market closed";
  return (
    <div data-testid="desk-status" className="flex min-w-0 items-center gap-4 text-xs">
      <span className="flex items-center gap-1.5 whitespace-nowrap text-muted-foreground">
        <span aria-hidden className={cn("h-1.5 w-1.5 rounded-full", data.phase === "regular" ? "bg-emerald-400 ring-[3px] ring-emerald-400/15" : "bg-muted-foreground")} />
        {word}
      </span>
      {data.indices.length > 0 && (
        <span data-testid="desk-indices" className="hidden gap-3 whitespace-nowrap md:flex">
          {data.indices.map(row => (
            <span key={row.symbol}>
              <span className="text-muted-foreground">{row.symbol}</span>{" "}
              {row.change_pct === null ? <span className="text-muted-foreground">—</span>
                : <span className={cn("tabular-nums", row.change_pct >= 0 ? "text-emerald-300" : "text-rose-300")}>{pct(row.change_pct)}</span>}
            </span>
          ))}
        </span>
      )}
    </div>
  );
}

/** The Briefing's numbers: open positions, what needs a decision, the nearest armed trigger and pings against the cap. */
function Numbers({ data, rows }: { data: DeskSession; rows: DeskThread[] }) {
  const positions = new Set(rows.filter(r => r.tradeId).map(r => r.tradeId)).size;
  const needYou = rows.filter(r => r.group === "act").length;
  const near = rows.find(r => r.group === "near");
  const cells: [string, ReactNode, string?][] = [
    ["Positions", num(positions)],
    ["Needs you", num(needYou), needYou ? "text-primary" : undefined],
    ["Nearest trigger", near ? <>{near.symbol ?? near.title} · <span className="tabular-nums">{near.status.text}</span></> : "None", near ? undefined : "text-muted-foreground"],
    ["Pings today", data.pings ? <>{num(data.pings.sent)} of {num(data.pings.cap)}{data.pings.held > 0 && <span className="text-muted-foreground"> · {num(data.pings.held)} held</span>}</> : "—"],
  ];
  return (
    <dl data-testid="briefing-numbers" className="grid grid-cols-2 border-t pt-2 sm:grid-cols-4">
      {cells.map(([label, value, tone], i) => (
        <div key={label} className={cn("min-w-0 py-1", i % 2 === 1 && "border-l pl-3", i > 1 && "sm:border-l sm:pl-3", i === 2 && "border-t sm:border-t-0", i === 3 && "border-t sm:border-t-0")}>
          <dt className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{label}</dt>
          <dd className={cn("truncate text-sm font-semibold text-foreground", tone)}>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * The Briefing's day at a glance (docs/copilot-lab.md § The desk), shown at the top of the thread while the Briefing (or
 * no thread) is open: one strip of the regular session in New York time with a "now" marker, today's fills, pings,
 * Radar events and logged decisions as ticks by kind, the time stops still ahead as hollow ticks, SPY and QQQ beside the
 * title, a numbers row (positions, needs you, the nearest trigger, pings against the daily cap; ``rows`` are the thread
 * list's) and one quiet line (what is next: a time stop, else the open or the close; the practice goal). Before the open
 * it says whether the prep is written; after the close it shows the whole day. ``data`` is the desk's one session read
 * (``useDeskSession``); read-only.
 */
export default function SessionTape({ data, error, rows, tally }: {
  data: DeskSession | null; error: string | null; rows: DeskThread[]; tally: { done: number; total: number };
}) {
  const practice = usePracticeLine(true);

  if (!data) return error ? <p className="mb-4 text-xs text-muted-foreground">Today&apos;s session is unavailable: {error}</p> : null;
  const { open, close, now } = data;
  const span = open !== null && close !== null && close > open ? close - open : null;
  const pos = (at: number) => (span === null || open === null ? 0 : Math.min(100, Math.max(0, ((at - open) / span) * 100)));
  const done = pos(now);
  const live = span !== null && open !== null && close !== null && now > open && now < close;
  const before = open !== null && now < open;
  const ahead = data.time_stops.filter(stop => stop.at > now);
  const counts = (Object.keys(KIND) as DeskSessionEvent["kind"][])
    .map(kind => [kind, data.events.filter(e => e.kind === kind).length] as const).filter(([, n]) => n > 0)
    .map(([kind, n]) => `${n} ${KIND[kind][n === 1 ? 0 : 1]}`);
  const summary = [counts.length ? `So far: ${counts.join(", ")}.` : "Nothing yet today.",
    ahead.length ? `Ahead: ${ahead.map(s => `${s.symbol} time stop ${s.clock}`).join(", ")}.` : ""].join(" ").trim();

  const facts: ReactNode[] = [];
  if (before || data.phase === "pre")
    facts.push(data.prep?.at ? <>Prep written {num(hhmm(data.prep.at))}</> : data.prep ? "Prep written" : "No prep yet today");
  // What is next: the nearest time stop, else the open (before it) or the close (during the session).
  const next = ahead[0] ? <>{ahead[0].symbol} time stop {num(ahead[0].clock)}</>
    : before && open !== null ? <>the open {num(hhmm(open))}</> : live && close !== null ? <>the close {num(hhmm(close))}</> : null;
  if (next) facts.push(<>Next: <span className="text-foreground/80">{next}</span></>);
  // After the close: how much of Close the day is answered (the desk's tally: close questions, alerts, Radar hits, fills).
  if (tally.total) facts.unshift(<span data-testid="briefing-reviewed">{num(tally.done)} of {num(tally.total)} done</span>);
  if (practice) facts.push(practice);

  return (
    <section aria-label="Today's session" data-testid="session-tape" className="mb-4 space-y-2 rounded-lg border bg-card px-4 py-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Today</h2>
        <span className="text-sm text-foreground">{data.phase ? PHASE[data.phase] : "Market hours unknown"}</span>
        {data.indices.length > 0 && (
          <span className="ml-auto flex gap-3 text-xs" data-testid="session-indices">
            {data.indices.map(row => (
              <span key={row.symbol}>
                <span className="text-muted-foreground">{row.symbol}</span>{" "}
                {row.change_pct === null ? <span className="text-muted-foreground">—</span>
                  : <span className={cn("tabular-nums", row.change_pct >= 0 ? "text-emerald-300" : "text-rose-300")}>{pct(row.change_pct)}</span>}
              </span>
            ))}
          </span>
        )}
      </div>
      {span !== null && open !== null ? (
        <div>
          <div role="img" aria-label={summary} title={summary} data-testid="session-strip" className="relative h-3">
            <div className="absolute inset-x-0 top-[5px] h-0.5 rounded-full bg-muted" />
            <div className="absolute left-0 top-[5px] h-0.5 rounded-full bg-muted-foreground/60" style={{ width: `${done}%` }} />
            {data.events.map((event, i) => (
              <span key={`${event.kind}-${event.at}-${i}`} data-kind={event.kind} title={`${hhmm(event.at)} · ${event.text}`}
                className={cn("absolute top-[3px] -ml-[3px] h-1.5 w-1.5 rounded-full ring-2 ring-card", DOT[event.kind],
                  (event.at < open || event.at > open + span) && "opacity-50")} style={{ left: `${pos(event.at)}%` }} />
            ))}
            {ahead.map(stop => (
              <span key={`${stop.symbol}-${stop.at}`} data-kind="time_stop" title={`${stop.clock} · ${stop.symbol} time stop`}
                className="absolute top-[2px] -ml-1 h-2 w-2 rounded-full border-[1.5px] border-primary bg-card" style={{ left: `${pos(stop.at)}%` }} />
            ))}
            {live && <span data-testid="session-now" className="absolute top-0 -ml-px h-3 w-0.5 rounded-sm bg-foreground" style={{ left: `${done}%` }} />}
          </div>
          <div aria-hidden data-testid="session-labels" className="relative mt-1 h-3 text-[10px] tabular-nums text-muted-foreground">
            {labelTimes(open, open + span).map((at, i, all) => (
              <span key={at} className={cn("absolute", i === 0 ? "" : i === all.length - 1 ? "-translate-x-full" : "-translate-x-1/2")}
                style={{ left: `${pos(at)}%` }}>{hhmm(at)}</span>
            ))}
          </div>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">{data.sections.hours === "unavailable" ? "Market hours are unavailable right now." : "No regular session today."}</p>
      )}
      <Numbers data={data} rows={rows} />
      {facts.length > 0 && (
        <p data-testid="session-facts" className="text-xs text-muted-foreground">
          {facts.map((fact, i) => <span key={i}>{i > 0 && " · "}{fact}</span>)}
        </p>
      )}
    </section>
  );
}
