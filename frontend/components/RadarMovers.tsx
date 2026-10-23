"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { getMovers, groupLine, radarChartHref, isGap, moversHeader, pctText, type RadarMover, type RadarMovers } from "@/lib/radar";
import { cn } from "@/lib/utils";

const tone = (value: number | null) => (value == null ? "text-muted-foreground" : value > 0 ? "text-emerald-300" : value < 0 ? "text-rose-300" : "text-foreground");

function Table({ title, rows, movers, allGroups }: { title: string; rows: RadarMover[]; movers: RadarMovers; allGroups: boolean }) {
  return (
    <section aria-label={title} className="min-w-0 space-y-1">
      <h3 className="text-xs font-semibold text-foreground">{title}</h3>
      <table className="w-full table-fixed text-xs">
        <thead className="text-muted-foreground">
          <tr>
            <th className="w-[26%] pb-1 text-left font-medium">Symbol</th>
            <th className="pb-1 text-right font-medium">Day</th>
            <th className="pb-1 text-right font-medium">vs SPY</th>
            <th className="pb-1 text-right font-medium">vs sector</th>
            <th className="pb-1 text-right font-medium">15 min</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((m) => (
            <tr key={m.symbol} className="border-t" data-testid="radar-mover">
              <td className="py-1.5 pr-1 font-medium">
                <Link href={radarChartHref(m.symbol, movers, undefined, allGroups)} className="text-foreground underline decoration-muted-foreground/40 underline-offset-2 hover:decoration-foreground">{m.symbol}</Link>
                {isGap(m) && <span title="Gap: the move since the open is under a third of the day's move" className="ml-1 rounded bg-secondary px-1 py-px text-[10px] font-normal text-muted-foreground">gap</span>}
              </td>
              <td className={cn("py-1.5 text-right tabular-nums", tone(m.day_pct))}>{pctText(m.day_pct)}</td>
              <td className={cn("py-1.5 text-right tabular-nums", tone(m.vs_spy))}>{pctText(m.vs_spy)}</td>
              <td className="py-1.5 text-right tabular-nums">
                <span className={tone(m.vs_sector)}>{pctText(m.vs_sector)}</span>
                {m.sector && <span className="block text-[10px] text-muted-foreground">{m.sector}</span>}
              </td>
              <td className={cn("py-1.5 text-right tabular-nums", tone(m.last_15m_pct))}>{pctText(m.last_15m_pct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export default function RadarMovers({ session }: { session: string | undefined }) {
  // Keyed by the session it was read for, so a switch never shows the previous session's numbers.
  const [read, setRead] = useState<{ session: string | undefined; movers: RadarMovers } | null>(null);
  const movers = read && read.session === session ? read.movers : null;
  const [error, setError] = useState(false);
  const [allGroups, setAllGroups] = useState(false);

  useEffect(() => { queueMicrotask(() => setAllGroups(new URLSearchParams(window.location.search).get("groups") === "all")); }, []);
  const toggleGroups = () => {
    const next = !allGroups;
    setAllGroups(next);
    const url = new URL(window.location.href);
    if (next) url.searchParams.set("groups", "all"); else url.searchParams.delete("groups");
    window.history.replaceState(window.history.state, "", url);
  };

  useEffect(() => {
    const controller = new AbortController();
    const load = () => getMovers(session, controller.signal).then(
      (next) => { setRead({ session, movers: next }); setError(false); },
      (e) => { if ((e as Error).name !== "AbortError") setError(true); });
    void load();
    const timer = setInterval(() => { if (document.visibilityState === "visible") void load(); }, 60_000);
    const onVisible = () => { if (document.visibilityState === "visible") void load(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { controller.abort(); clearInterval(timer); document.removeEventListener("visibilitychange", onVisible); };
  }, [session]);

  const restored = useRef(false);
  useEffect(() => {
    if (!movers || restored.current) return;
    let target: string;
    try { target = decodeURIComponent(window.location.hash.slice(1)); } catch { return; }
    if (target !== "radar-movers" && !movers.groups.some((g) => target === `radar-group-${g.name}`)) return;
    const element = document.getElementById(target);
    if (element) { element.scrollIntoView({ block: "start" }); restored.current = true; }
  }, [movers, allGroups]);

  const ranked = movers?.header != null;
  return (
    <section id="radar-movers" aria-label="Movers now" className="space-y-3 rounded-lg border bg-card p-3" data-testid="radar-movers">
      <div>
        <h2 className="text-sm font-semibold text-foreground">Movers now</h2>
        <p className="text-xs text-muted-foreground">A plain ranking of the latest recorded pass, not alerts. Biggest and smallest moves against SPY; nothing here is a signal.</p>
      </div>
      {error && <p role="alert" className="text-xs text-amber-300">Movers could not be refreshed. Showing the last reading.</p>}
      {!movers && !error && <p role="status" className="text-xs text-muted-foreground">Loading movers…</p>}
      {movers && !ranked && <p className="text-xs text-muted-foreground" data-testid="radar-movers-empty">{movers.reason ?? "No movers to show yet."}</p>}
      {movers && ranked && (
        <>
          <p className={cn("text-sm font-medium tabular-nums", movers.state === "stale" ? "text-amber-300" : "text-foreground")} data-testid="radar-movers-header">{moversHeader(movers)}</p>
          {movers.state === "stale" && <p className="text-xs text-amber-300">{movers.reason}</p>}
          <div className="grid gap-4 md:grid-cols-2">
            <Table title="Leaders" rows={movers.leaders} movers={movers} allGroups={allGroups} />
            <Table title="Laggards" rows={movers.laggards} movers={movers} allGroups={allGroups} />
          </div>
          <p className="text-[11px] text-muted-foreground">
            Day is versus the previous close. 15 min is versus the pass about 15 minutes earlier{movers.header?.has_earlier_pass ? "" : " (none recorded yet)"}.
            “gap” marks a move since the open under a third of the day move (a simple label). Sector is its ETF. {movers.missing.length > 0 ? `${movers.missing.length} ${movers.missing.length === 1 ? "symbol" : "symbols"} had no usable quote and ${movers.missing.length === 1 ? "is" : "are"} left out.` : ""}
          </p>
          <div className="space-y-1">
            <h3 className="text-xs font-semibold text-foreground">Groups, by size of median move against SPY</h3>
            <ul className="space-y-1">
              {movers.groups.slice(0, allGroups ? undefined : 10).map((g) => <li key={g.name} id={`radar-group-${g.name}`} className="text-xs text-muted-foreground" data-testid="radar-mover-group">
                <span>{groupLine(g)}</span>
                {g.most && <Link href={radarChartHref(g.most.symbol, movers, g.name, allGroups)}
                  className="ml-2 inline-flex min-h-11 items-center text-sky-300 underline underline-offset-2"
                  aria-label={`Compare ${g.name} in Charts with ${g.most.symbol}`}>Compare in Charts</Link>}
              </li>)}
            </ul>
            {movers.groups.length > 10 && (
              <button type="button" onClick={toggleGroups} aria-expanded={allGroups}
                className="h-9 rounded-md border px-3 text-xs font-medium text-muted-foreground hover:bg-secondary hover:text-foreground">
                {allGroups ? "Show fewer groups" : `Show all ${movers.groups.length} groups`}
              </button>
            )}
          </div>
        </>
      )}
    </section>
  );
}
