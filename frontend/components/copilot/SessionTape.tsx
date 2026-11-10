"use client";

import { useEffect, useState, type ReactNode } from "react";
import { EyeOff } from "lucide-react";
import { usePracticeLine } from "@/components/copilot/ReviewMyWeek";
import { getExposure } from "@/lib/copilot";
import { TONE, numeric } from "@/components/copilot/ThreadRail";
import { getDeskSession, reviewSkipped, type DeskSession, type DeskSessionEvent, type DeskThread } from "@/lib/desk";
import { cn } from "@/lib/utils";

const REFRESH_MS = 60_000;
// Amber is kept for what still needs you (a time stop ahead); what already happened stays quiet.
const DOT: Record<DeskSessionEvent["kind"], string> = { fill: "bg-emerald-400", ping: "bg-muted-foreground", radar: "bg-foreground/60", decision: "bg-foreground" };
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

/** "At risk now: $6,400 in 3 options · usual day $2,100", re-read with each session read (its ``as_of``); null when the
 * read fails or no long option is open. */
function useExposureLine(asOf: string | undefined): string | null {
  const [line, setLine] = useState<string | null>(null);
  useEffect(() => {
    if (!asOf) return;
    const controller = new AbortController();
    getExposure(controller.signal).then(now => setLine(now.line)).catch(() => {
      if (!controller.signal.aborted) setLine(null); /* the line is extra */
    });
    return () => controller.abort();
  }, [asOf]);
  return line;
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

const LABEL = "text-[11px] font-medium uppercase tracking-wide text-muted-foreground";
const ROW = "flex min-h-11 w-full min-w-0 flex-col justify-center gap-0.5 rounded-md px-2.5 py-1.5 text-left hover:bg-secondary sm:min-h-10";
const isRadar = (row: DeskThread) => row.key.startsWith("radar:");

/** One desk row as a button: the symbol, what the row is (a contract, a plan), its figure on the right, and its status
 * line (or ``line``) under it. Amber only when the row's own tone asks for the owner. */
function RowButton({ row, line, open }: { row: DeskThread; line?: ReactNode; open(row: DeskThread): void }) {
  const what = row.title && row.title !== row.symbol ? row.title : null;
  return (
    <button type="button" onClick={() => open(row)} className={ROW}>
      <span className="flex min-w-0 items-baseline gap-2">
        <span className="shrink-0 text-sm font-semibold text-foreground">{row.symbol ?? row.title}</span>
        {what && <span className="min-w-0 truncate text-xs text-muted-foreground" title={what}>{what}</span>}
        {row.value && <span className={cn("ml-auto shrink-0 text-xs", TONE[row.value.tone], numeric(row.value.text) && "tabular-nums")}>{row.value.text}</span>}
      </span>
      <span className={cn("block truncate text-xs", TONE[row.status.tone])}>{line ?? row.status.text}</span>
    </button>
  );
}

/** One ticker's follow switch on a Now row: Hide (an eye) on a followed one, Show again on one not followed. */
function FollowButton({ symbol, following, onFollow }: { symbol: string; following: boolean; onFollow(symbol: string, following: boolean): void }) {
  return following ? (
    <button type="button" onClick={() => onFollow(symbol, false)} aria-label={`Hide ${symbol}: not following`}
      title="Not following: hide this ticker from Now, the thread list and every count (Show again undoes it)"
      className="flex min-h-11 w-11 shrink-0 items-center justify-center rounded-md text-muted-foreground/70 hover:bg-secondary hover:text-foreground sm:min-h-10 sm:w-9">
      <EyeOff size={14} aria-hidden />
    </button>
  ) : (
    <button type="button" onClick={() => onFollow(symbol, true)}
      className="min-h-11 shrink-0 rounded-md px-2.5 text-xs font-medium text-primary hover:bg-secondary sm:min-h-8">Show again</button>
  );
}

/** "3 not followed ▾" at the bottom of a list: each ticker the owner hid, with Show again. Nothing when none. */
export function NotFollowed({ rows, open, onFollow }: { rows: DeskThread[]; open(row: DeskThread): void; onFollow(symbol: string, following: boolean): void }) {
  const [shown, setShown] = useState(false);
  const first = new Map<string, DeskThread>();
  for (const row of rows) if (row.symbol && !first.has(row.symbol)) first.set(row.symbol, row);
  if (!first.size) return null;
  return (
    <div data-testid="not-followed" className="mt-1 border-t pt-1">
      <button type="button" aria-expanded={shown} onClick={() => setShown(was => !was)}
        className="min-h-11 w-full rounded-md px-2.5 text-left text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8">
        <span className="tabular-nums">{first.size}</span> not followed {shown ? "▴" : "▾"}
      </button>
      {shown && (
        <ul aria-label="Not followed">
          {[...first.values()].map(row => (
            <li key={row.symbol} className="flex items-center gap-1">
              <div className="min-w-0 flex-1"><RowButton row={row} open={open} /></div>
              <FollowButton symbol={row.symbol!} following={false} onFollow={onFollow} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * Now's open positions (docs/copilot-lab.md § The desk): one row per open position the owner follows, from the thread
 * list's read, with its contract, unrealized P&L and its plan's nearest line (distance to invalidation, else the time
 * stop; "No plan yet" without one), plus a time stop still ahead today when the line names something else. Each row's
 * eye hides its ticker (``onFollow``); hidden ones sit behind "N not followed" at the bottom, each with Show again.
 * Then the followed armed plans near a trigger. A row opens its thread (``open``, the desk's ``pick``).
 */
export function NowPositions({ rows, stops, open, read, onFollow }: {
  rows: DeskThread[]; stops: DeskSession["time_stops"]; open(row: DeskThread): void; read: boolean;
  onFollow(symbol: string, following: boolean): Promise<void>;
}) {
  const [failed, setFailed] = useState<string | null>(null);
  const held = rows.filter(r => r.key.startsWith("trade:"));
  const positions = held.filter(r => !r.hidden);
  const near = rows.filter(r => r.group === "near" && !r.hidden);
  const follow = (symbol: string, following: boolean) => {
    setFailed(null);
    onFollow(symbol, following).catch(() => setFailed(`${symbol}: not saved. Try again.`));
  };
  const line = (row: DeskThread) => {
    const stop = stops.find(s => s.symbol === row.symbol);
    return stop && !/time stop/i.test(row.status.text) ? `${row.status.text} · time stop ${stop.clock}` : row.status.text;
  };
  return (
    <section aria-label="Open positions" data-testid="now-positions" className="mb-4 rounded-lg border bg-card p-1.5">
      <h2 className={cn(LABEL, "px-2.5 pb-1 pt-1")}>Open positions{positions.length > 0 && <> · <span className="tabular-nums">{positions.length}</span></>}</h2>
      {positions.length ? (
        <ul>{positions.map(row => (
          <li key={row.key} className="flex items-center gap-1">
            <div className="min-w-0 flex-1"><RowButton row={row} line={line(row)} open={open} /></div>
            {row.symbol && <FollowButton symbol={row.symbol} following onFollow={follow} />}
          </li>
        ))}</ul>
      ) : <p className="px-2.5 pb-1.5 text-xs text-muted-foreground">{!read ? "Reading positions…" : held.length ? "Only positions you don't follow are open." : "No open positions."}</p>}
      {near.length > 0 && (
        <>
          <h3 className={cn(LABEL, "mt-1 border-t px-2.5 pb-1 pt-2")}>Near a trigger</h3>
          <ul>{near.map(row => <li key={row.key}><RowButton row={row} open={open} /></li>)}</ul>
        </>
      )}
      <NotFollowed rows={held.filter(r => r.hidden)} open={open} onFollow={follow} />
      {failed && <p role="alert" className="px-2.5 pb-1 text-xs text-primary">{failed}</p>}
    </section>
  );
}

/**
 * What waits on the owner: each followed ticker's decision to make, card to confirm or close question still open
 * (``needsYou``), one row each opening its thread, then ``children`` (fills to link). Ratings of alerts and Radar hits
 * are optional and never wait here. ``quiet`` says nothing else waits.
 */
export function NowWaiting({ rows, day, open, quiet, children }: {
  rows: DeskThread[]; day: string; open(row: DeskThread): void; quiet: boolean; children?: ReactNode;
}) {
  const waiting = rows.filter(r => r.symbol && !r.hidden && r.group !== "pinned" && !isRadar(r) && (r.group === "act" || r.group === "draft"
    || (!!r.close && !r.close.reviewed && !reviewSkipped(day, r.symbol))));
  const line = (row: DeskThread) => row.group === "draft" ? `Card to confirm · ${row.status.text}`
    : row.group !== "act" && row.close ? row.close.question : row.status.text;
  return (
    <section aria-label="Waiting on you" data-testid="now-waiting" className="mb-4 space-y-2 rounded-lg border bg-card p-1.5">
      <h2 className={cn(LABEL, "px-2.5 pt-1")}>Waiting on you{waiting.length > 0 && <> · <span className="tabular-nums text-primary">{waiting.length}</span></>}</h2>
      {waiting.length > 0 && <ul>{waiting.map(row => <li key={row.key}><RowButton row={row} line={line(row)} open={open} /></li>)}</ul>}
      <div className="flex flex-wrap items-start gap-x-4 gap-y-2 px-2.5 pb-1.5 text-sm empty:hidden">{children}</div>
      {!waiting.length && quiet && <p className="px-2.5 pb-1.5 text-xs text-muted-foreground">Nothing waits on you right now.</p>}
    </section>
  );
}

/**
 * Now's day line (docs/copilot-lab.md § The desk), at the top of the desk's front door: the market phase with SPY, QQQ
 * and VIX (a phone too), one strip of the regular session in New York time with a "now" marker, today's fills, pings,
 * Radar events and logged decisions as ticks by kind, the time stops still ahead as hollow ticks, and one quiet line
 * (what is next: a time stop, else the open or the close; at risk now; the practice goal). Before the open it says
 * whether the prep is written; after the close it shows the whole day and how much of Close the day is done. ``data``
 * is the desk's one session read (``useDeskSession``); read-only.
 */
export default function SessionTape({ data, error, tally }: {
  data: DeskSession | null; error: string | null; tally: { done: number; total: number };
}) {
  const practice = usePracticeLine(true);
  const exposure = useExposureLine(data?.as_of);

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
  // After the close: how much of Close the day is answered (the desk's tally: close questions and fills).
  if (tally.total) facts.unshift(<span data-testid="briefing-reviewed">{num(tally.done)} of {num(tally.total)} done</span>);
  if (exposure) facts.push(<span data-testid="exposure-line">{exposure}</span>);
  if (practice) facts.push(practice);

  return (
    <section aria-label="Today's session" data-testid="session-tape" className="mb-4 space-y-2 rounded-lg border bg-card px-4 py-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Today</h2>
        <span className="text-sm text-foreground">{data.phase ? PHASE[data.phase] : "Market hours unknown"}</span>
        {data.indices.length > 0 && (
          <span className="ml-auto flex gap-3 text-xs md:hidden" data-testid="session-indices">
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
      {facts.length > 0 && (
        <p data-testid="session-facts" className="text-xs text-muted-foreground">
          {facts.map((fact, i) => <span key={i}>{i > 0 && " · "}{fact}</span>)}
        </p>
      )}
    </section>
  );
}
