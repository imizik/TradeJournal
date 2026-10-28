"use client";

import { useEffect, useState, type ReactNode } from "react";
import { usePracticeLine } from "@/components/copilot/ReviewMyWeek";
import { getDeskSession, type DeskSession, type DeskSessionEvent } from "@/lib/desk";
import { cn } from "@/lib/utils";

const REFRESH_MS = 60_000;
const DOT: Record<DeskSessionEvent["kind"], string> = { fill: "bg-emerald-400", ping: "bg-primary", radar: "bg-sky-400", decision: "bg-foreground" };
const KIND: Record<DeskSessionEvent["kind"], [string, string]> = {
  fill: ["fill", "fills"], ping: ["ping", "pings"], radar: ["Radar event", "Radar events"], decision: ["decision", "decisions"],
};
const PHASE: Record<NonNullable<DeskSession["phase"]>, string> = { pre: "Pre-market", regular: "Market open", post: "After the close", closed: "Market closed" };
/** New York wall time without a leading zero ("9:30", "14:00"). */
const hhmm = (seconds: number) => new Date(seconds * 1000)
  .toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).replace(/^0/, "");
const pct = (value: number) => `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(2)}%`;
/** The open, every 90 minutes after it, and the close (a mark too near the close gives way to it): 9:30, 11:00, 12:30, 14:00, 16:00. */
const labelTimes = (open: number, close: number) => {
  const marks = [open];
  for (let at = open + 5400; at <= close - 2700; at += 5400) marks.push(at);
  return [...marks, close];
};
const num = (text: string | number) => <span className="tabular-nums">{text}</span>;

/**
 * The Briefing's day at a glance (docs/copilot-lab.md § The desk), shown at the top of the thread while the Briefing (or
 * no thread) is open: one strip of the regular session in New York time with a "now" marker, today's fills, pings,
 * Radar events and logged decisions as ticks by kind, the time stops still ahead as hollow ticks, SPY and QQQ beside the
 * title, and one quiet line (the next time stop, the practice goal, pings against the daily cap). Before the open it
 * says whether the prep is written; after the close it shows the whole day. One read (``GET /copilot/desk/session``)
 * a minute while the page is visible; read-only.
 */
export default function SessionTape() {
  const [data, setData] = useState<DeskSession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const practice = usePracticeLine(true);
  useEffect(() => {
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
  }, []);

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
  if (ahead[0]) facts.push(<>Next: <span className="text-foreground/80">{ahead[0].symbol} time stop {num(ahead[0].clock)}</span></>);
  if (practice) facts.push(practice);
  if (data.pings) facts.push(<>Pings {num(data.pings.sent)} of {num(data.pings.cap)}{data.pings.held > 0 && <> · {num(data.pings.held)} held</>}</>);

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
                className={cn("absolute top-[3px] -ml-[3px] h-1.5 w-1.5 rounded-full ring-2 ring-card", DOT[event.kind])} style={{ left: `${pos(event.at)}%` }} />
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
      {facts.length > 0 && (
        <p data-testid="session-facts" className="text-xs text-muted-foreground">
          {facts.map((fact, i) => <span key={i}>{i > 0 && " · "}{fact}</span>)}
        </p>
      )}
    </section>
  );
}
