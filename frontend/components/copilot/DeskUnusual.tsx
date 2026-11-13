"use client";

import { useEffect, useState } from "react";
import { Info } from "lucide-react";
import { apiUrl } from "@/lib/api";
import { contractLabel, type ChainPick, type ChainSide } from "@/components/copilot/DeskChain";
import { cn } from "@/lib/utils";

/**
 * Unusual options on his held and watched names (docs/copilot-lab.md § Unusual options), from ``GET /copilot/unusual``:
 * read once a minute while the lab is on (the server reads the option chains itself, paced, and answers from what it
 * keeps). The Feed shows the list behind its Unusual options filter; the Chain tab marks the matching contracts. Tapping a
 * row selects that contract in the Chain tab. Market data only: nothing here pings, rates or sends anything.
 */

export type UnusualRow = {
  symbol: string; held: boolean; contract: string; side: ChainSide; strike: number; expiration: string; volume: number;
  open_interest: number; ratio: number | null; last: number | null; read_at: number; stale: boolean;
};
export type UnusualTicker = { symbol: string; held: boolean; side: ChainSide; today: number; usual: number; multiple: number; sessions: number; read_at: number; stale: boolean };
export type UnusualReply = {
  state: "ok" | "none" | "unavailable"; session: "open" | "closed"; label: "live" | "at the close" | null; day: string | null;
  rule: string; rows: UnusualRow[]; tickers: UnusualTicker[]; unread: string[]; no_history: string[]; stale: string[];
  /** Names whose read came back short, so the whole-ticker check was skipped. */
  partial?: string[]; held: string[]; read_at?: number | null; message: string | null; simulated: boolean;
};

const READ_MS = 60_000;

export function useDeskUnusual(on: boolean): UnusualReply | null {
  const [data, setData] = useState<UnusualReply | null>(null);
  useEffect(() => {
    if (!on) return;
    const controller = new AbortController();
    const load = () => fetch(apiUrl("/copilot/unusual"), { cache: "no-store", signal: controller.signal })
      // A refusal is read through too, so the request ends (an unread body holds it open).
      .then(async r => (r.ok ? r.json() : r.text().catch(() => "").then(() => Promise.reject(new Error(String(r.status))))))
      .then((body: UnusualReply) => setData(body))
      .catch(() => { /* the last good list stays; nothing new is shown */ });
    load();
    const timer = setInterval(load, READ_MS);
    return () => { controller.abort(); clearInterval(timer); };
  }, [on]);
  return data;
}

export const unusualPick = (row: UnusualRow): ChainPick => ({ symbol: row.symbol, expiry: row.expiration, strike: row.strike, side: row.side });

/** The Chain tab's marks: the unusual contracts of ``symbol`` at ``expiry``, by "side:strike". */
export function unusualAt(reply: UnusualReply | null, symbol: string | null, expiry: string | null): Map<string, UnusualRow> {
  const out = new Map<string, UnusualRow>();
  for (const row of reply?.rows ?? []) {
    if (row.symbol === symbol && row.expiration === expiry) out.set(`${row.side}:${row.strike}`, row);
  }
  return out;
}

const num = (n: number) => n.toLocaleString("en-US");
const clock = (epoch: number) => new Date(epoch * 1000).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });
const dayText = (iso: string) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", weekday: "short", month: "short", day: "numeric" });
export const ratioText = (row: Pick<UnusualRow, "ratio">) => row.ratio === null ? "no open interest yet" : `${row.ratio}× OI`;

/** The Feed's Unusual options section. */
export function UnusualList({ reply, onPick }: { reply: UnusualReply | null; onPick(pick: ChainPick): void }) {
  if (!reply) return <p className="text-xs text-muted-foreground">Reading unusual options…</p>;
  const newest = reply.read_at ?? Math.max(0, ...reply.rows.map(r => r.read_at), ...reply.tickers.map(t => t.read_at));
  const when = reply.simulated ? "Simulated (sandbox fixture)"
    : reply.label === "live" ? `Live${newest ? ` · read ${clock(newest)} ET` : ""}`
    : reply.label === "at the close" && reply.day ? `At the close · ${dayText(reply.day)}${newest ? ` · last read ${clock(newest)} ET` : ""}` : null;
  const grey: string[] = [];
  if (reply.unread.length) grey.push(`${reply.label === "live" ? "Not read yet" : "No reading from that session"}: ${reply.unread.join(", ")}.`);
  if (reply.no_history.length) grey.push(`No volume history yet for ${reply.no_history.join(", ")}, so only the volume-vs-open-interest rule applies.`);
  if (reply.partial?.length) grey.push(`The whole-ticker check was skipped for ${reply.partial.join(", ")}: fewer than two expiries after today were read.`);
  if (reply.stale.length) grey.push(`Not read again lately (greyed): ${reply.stale.join(", ")}.`);
  return (
    <section data-testid="feed-unusual" aria-label="Unusual options" className="space-y-2">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <span className="font-medium text-foreground">Unusual options</span>
        {when && <span data-testid="unusual-when" className={cn(reply.simulated && "text-amber-300")}>{when}</span>}
        <span title={reply.rule} aria-label={reply.rule} role="img" data-testid="unusual-rule" className="inline-flex cursor-help items-center">
          <Info size={13} aria-hidden />
        </span>
      </p>
      {reply.tickers.length > 0 && (
        <ul data-testid="unusual-tickers" className="flex flex-wrap gap-1.5">
          {reply.tickers.map(t => (
            <li key={`${t.symbol}:${t.side}`} title={`${num(t.today)} ${t.side} contracts so far today against ${num(t.usual)} on a usual full day (last ${t.sessions} recorded sessions)`}
              className={cn("rounded-full border px-2 py-0.5 text-xs tabular-nums", t.stale && "opacity-60", t.held ? "border-foreground text-foreground" : "border-transparent bg-secondary text-muted-foreground")}>
              <span className="font-semibold text-foreground">{t.symbol}</span> {t.side}s {t.multiple}× usual
            </li>
          ))}
        </ul>
      )}
      {reply.state !== "ok" || (!reply.rows.length && reply.message) ? (
        <p className="rounded-md border bg-card px-3 py-2.5 text-xs text-muted-foreground">{reply.message ?? "Nothing unusual right now."}</p>
      ) : !reply.rows.length ? (
        <p className="rounded-md border bg-card px-3 py-2.5 text-xs text-muted-foreground">No contract on your names has traded unusually{reply.label === "live" ? " so far today" : ""}.</p>
      ) : (
        <ol className="divide-y rounded-lg border bg-card">
          {reply.rows.map(row => (
            <li key={row.contract} className={cn(row.stale && "opacity-60")}>
              <button type="button" data-testid="unusual-row" onClick={() => onPick(unusualPick(row))}
                title={`Select ${contractLabel(unusualPick(row))} in the Chain tab`}
                className="block w-full min-w-0 px-3 py-2 text-left hover:bg-secondary">
                <span className="flex min-w-0 items-baseline gap-2">
                  <span className="truncate font-mono text-sm font-semibold">{contractLabel(unusualPick(row))}</span>
                  {row.held && <span className="text-[11px] text-emerald-400">you hold {row.symbol}</span>}
                  <span className="ml-auto whitespace-nowrap text-xs tabular-nums text-orange-300">{ratioText(row)}</span>
                </span>
                <span className="block text-xs tabular-nums text-muted-foreground">
                  Vol {num(row.volume)} · OI {num(row.open_interest)} · Last {row.last === null ? "—" : row.last.toFixed(2)}
                  {row.stale ? ` · read ${clock(row.read_at)} ET, not live` : ""}
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}
      {grey.map(line => <p key={line} className="px-1 text-xs text-muted-foreground">{line}</p>)}
    </section>
  );
}
