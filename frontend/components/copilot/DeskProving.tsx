"use client";

import { useEffect, useState } from "react";
import { deskGet, everyDeskMinute } from "@/lib/deskMinute";
import { cn } from "@/lib/utils";
import ModeMark, { MODE_FRAME } from "./ModeMark";

/**
 * The paper proving ground (backend app/engine/proving_ground.py): every idea source (Radar setups, Jo's morning picks,
 * the 9:45 MU/NBIS rule) paper traded on one bracket, ranked by net dollars. A source graduates to unlabeled phone pings
 * after enough closed trades net positive; until then its pings say PAPER. Read-only.
 */

type Row = { source: string; name: string; closed: number; green: number; pnl: number; pnl_2x: number; avg: number | null;
  open: number; unresolved: number; exits: Record<string, number>; graduated: boolean };
type Recent = { source: string; day: string; symbol: string; direction: string; state: string; entry: number | null; exit: number | null;
  reason: string | null; pnl: number | null; note: string | null; contract: string | null };
export type ProvingGround = { enabled: boolean; graduate_trades: number;
  bracket: { take_profit: number; stop: number; hold_minutes: number; flat_minutes: number }; board: Row[]; recent: Recent[] };

const usd = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : ""}$${Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
const tone = (n: number | null) => n == null || n === 0 ? "text-muted-foreground" : n > 0 ? "text-emerald-300" : "text-rose-300";
const pct = (n: number) => `${Math.round(n * 100)}%`;
const REASON: Record<string, string> = { take_profit: "target", stop: "stop", time_stop: "60 min", session_close: "close" };

export function useProvingGround(on: boolean): { ground: ProvingGround | null; failed: boolean } {
  const [ground, setGround] = useState<ProvingGround | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!on) return;
    const controller = new AbortController();
    const load = () => deskGet("/copilot/desk/proving-ground", controller.signal)
      .then(async r => { const body = await r.json().catch(() => null); if (!r.ok || !body) throw new Error(String(r.status)); setGround(body); setFailed(false); })
      .catch(() => { if (!controller.signal.aborted) setFailed(true); });
    load();
    const stop = everyDeskMinute(load);
    return () => { controller.abort(); stop(); };
  }, [on]);
  return { ground, failed };
}

/** The one-line summary on the Practice block: the leading source, or why there is none. */
export function provingWords(ground: ProvingGround | null, failed: boolean): string {
  if (failed) return "· could not be read";
  if (!ground) return "· reading…";
  const lead = ground.board.find(r => r.closed > 0);
  if (!lead) return ground.enabled ? "· no closed paper trades yet" : "· off";
  return `· ${lead.name} ${usd(lead.pnl)} (${lead.closed}/${ground.graduate_trades})`;
}

export default function DeskProving({ ground, failed }: { ground: ProvingGround | null; failed: boolean }) {
  if (failed || !ground) {
    return <p data-testid="desk-proving-failed" className="px-1 text-xs text-muted-foreground">{failed ? "Could not read the proving ground; it reads again in a minute." : "Reading…"}</p>;
  }
  const b = ground.bracket;
  return (
    <section data-testid="desk-proving" aria-label="Paper proving ground" className={cn("rounded-md px-3 py-2", MODE_FRAME.paper)}>
      <p className="flex flex-wrap items-center gap-2"><span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Proving ground</span><ModeMark mode="paper" /></p>
      <p className="mt-1 text-xs text-muted-foreground">
        Every idea on paper, one contract: +{pct(b.take_profit)} target, −{pct(b.stop)} stop, out after {b.hold_minutes} min or {b.flat_minutes} min before the close.
        A source graduates to real pings at {ground.graduate_trades} closed trades net positive; until then its pings say PAPER.
        {!ground.enabled && " Off: nothing new is entered until it is switched on."}
      </p>
      <table className="mt-2 w-full text-xs tabular-nums" data-testid="desk-proving-board">
        <thead className="text-left text-muted-foreground"><tr>
          <th className="py-0.5 pr-2 font-normal">Source</th><th className="py-0.5 pr-2 font-normal">Closed</th>
          <th className="py-0.5 pr-2 font-normal">Green</th><th className="py-0.5 pr-2 font-normal">Net</th><th className="py-0.5 font-normal">Status</th>
        </tr></thead>
        <tbody>{ground.board.map(r => (
          <tr key={r.source} data-testid={`desk-proving-${r.source}`} className="border-t border-border/50">
            <td className="py-1 pr-2">{r.name}</td>
            <td className="py-1 pr-2">{r.closed}{r.open > 0 && <span className="text-muted-foreground"> +{r.open} open</span>}</td>
            <td className="py-1 pr-2">{r.closed ? `${r.green} of ${r.closed}` : "—"}</td>
            <td className="py-1 pr-2" title={`At twice the spread: ${usd(r.pnl_2x)}`}><span className={tone(r.closed ? r.pnl : null)}>{r.closed ? usd(r.pnl) : "—"}</span></td>
            <td className="py-1">{r.graduated ? <span className="text-emerald-300">Graduated</span> : <span className="text-muted-foreground">PAPER {Math.min(r.closed, ground.graduate_trades)}/{ground.graduate_trades}</span>}</td>
          </tr>
        ))}</tbody>
      </table>
      {ground.recent.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-xs tabular-nums" data-testid="desk-proving-recent">
          {ground.recent.map((t, i) => (
            <li key={i} className="flex flex-wrap justify-between gap-x-2">
              <span className="min-w-0 truncate text-muted-foreground">{t.day.slice(5)} · {t.symbol} {t.direction === "up" ? "call" : "put"} · {ground.board.find(r => r.source === t.source)?.name ?? t.source}</span>
              <span className="shrink-0">{t.state === "closed" && t.pnl != null
                ? <><span className={tone(t.pnl)}>{usd(t.pnl)}</span> <span className="text-muted-foreground">{REASON[t.reason ?? ""] ?? t.reason}</span></>
                : <span className="text-muted-foreground">{t.state === "unresolved" ? "unresolved" : t.state}</span>}</span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-1 text-[11px] text-muted-foreground">Ask in, bid out, $0.65 a side, checked once a minute. Paper results are a record, not proof of an edge.</p>
    </section>
  );
}
