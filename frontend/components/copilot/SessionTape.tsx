"use client";

import { useEffect, useState, type ReactNode } from "react";
import { EyeOff } from "lucide-react";
import { TONE, numeric } from "@/components/copilot/ThreadRail";
import { getDeskSession, type DeskSession, type DeskThread } from "@/lib/desk";
import { cn } from "@/lib/utils";

const REFRESH_MS = 60_000;
/** New York wall time without a leading zero ("9:30", "14:00"). */
export const hhmm = (seconds: number) => new Date(seconds * 1000)
  .toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).replace(/^0/, "");
export const pct = (value: number) => `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(2)}%`;

/** ``GET /copilot/desk/session`` once a minute while the page is visible: the desk reads it once for its top bar, its
 * phase button, the strip and its lower block. */
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

/** The top bar's live line: Live, Pre-market, Closed 16:00 or Market closed with the New York clock of the session read
 * (re-read each minute), then SPY / QQQ / VIX's change. Nothing until the phase is known. */
export function DeskStatus({ data }: { data: DeskSession | null }) {
  if (!data?.phase) return null;
  const word = data.phase === "regular" ? "Live" : data.phase === "pre" ? "Pre-market"
    : data.close !== null && data.now >= data.close ? `Closed ${hhmm(data.close)}` : "Market closed";
  const closed = data.phase !== "regular" && data.phase !== "pre";
  return (
    <div data-testid="desk-status" className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1 text-xs">
      <span className="flex items-center gap-1.5 whitespace-nowrap text-muted-foreground">
        <span aria-hidden className={cn("h-1.5 w-1.5 rounded-full", data.phase === "regular" ? "bg-emerald-400 ring-[3px] ring-emerald-400/15" : "bg-muted-foreground")} />
        {word}{!closed && <> · <span data-testid="desk-clock" className="tabular-nums">{hhmm(data.now)} ET</span></>}
      </span>
      {data.indices.length > 0 && (
        <span data-testid="desk-indices" className="flex gap-3 whitespace-nowrap">
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

const ROW = "flex min-h-11 w-full min-w-0 flex-col justify-center gap-0.5 rounded-md px-2.5 py-1.5 text-left hover:bg-secondary sm:min-h-10";

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

/** One ticker's follow switch: Hide (an eye) on a followed one, Show again on one not followed. */
function FollowButton({ symbol, following, onFollow }: { symbol: string; following: boolean; onFollow(symbol: string, following: boolean): void }) {
  return following ? (
    <button type="button" onClick={() => onFollow(symbol, false)} aria-label={`Hide ${symbol}: not following`}
      title="Not following: hide this ticker from the desk, the thread list and every count, and silence its phone pings (Show again undoes it)"
      className="flex min-h-11 w-11 shrink-0 items-center justify-center rounded-md text-muted-foreground/70 hover:bg-secondary hover:text-foreground sm:min-h-10 sm:w-9">
      <EyeOff size={14} aria-hidden />
    </button>
  ) : (
    <button type="button" onClick={() => onFollow(symbol, true)}
      className="min-h-11 shrink-0 rounded-md px-2.5 text-xs font-medium text-primary hover:bg-secondary sm:min-h-8">Show again</button>
  );
}

/** "3 not followed · quiet on your phone too ▾" at the bottom of the book: each ticker the owner hid, with Show again.
 * Their phone pings are held by the backend's notification policy (``not_followed``). Nothing when none. */
export function NotFollowed({ rows, open, onFollow }: { rows: DeskThread[]; open(row: DeskThread): void; onFollow(symbol: string, following: boolean): void }) {
  const [shown, setShown] = useState(false);
  const first = new Map<string, DeskThread>();
  for (const row of rows) if (row.symbol && !first.has(row.symbol)) first.set(row.symbol, row);
  if (!first.size) return null;
  return (
    <div data-testid="not-followed" className="mt-1 border-t pt-1">
      <button type="button" aria-expanded={shown} onClick={() => setShown(was => !was)}
        className="min-h-11 w-full rounded-md px-2.5 text-left text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8">
        <span className="tabular-nums">{first.size}</span> not followed · quiet on your phone too {shown ? "▴" : "▾"}
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
