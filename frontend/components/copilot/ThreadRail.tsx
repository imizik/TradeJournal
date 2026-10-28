"use client";

import { useCallback, useEffect, useState, type MouseEvent } from "react";
import Link from "next/link";
import PlanATrade from "@/components/copilot/PlanATrade";
import type { HomeActions } from "@/components/copilot/CopilotPanel";
import { PracticeLine, WEEK_REVIEW_CONTEXT } from "@/components/copilot/ReviewMyWeek";
import { WHAT_MATTERS_PROMPT } from "@/lib/copilot";
import { DESK_GROUPS, getDeskThreads, type DeskDay, type DeskGroup, type DeskThread, type DeskThreads, type DeskTone } from "@/lib/desk";
import { cn } from "@/lib/utils";

const REFRESH_MS = 60_000;
const SEEN_KEY = "desk.seen.v1";
const TONE: Record<DeskTone, string> = {
  attention: "text-primary", loss: "text-rose-300", gain: "text-emerald-300", info: "text-foreground", muted: "text-muted-foreground",
};
const BAR: Record<DeskTone, string> = {
  attention: "bg-primary", loss: "bg-rose-400", gain: "bg-emerald-400", info: "bg-foreground", muted: "bg-muted-foreground",
};
const PHASE: Record<NonNullable<DeskDay["phase"]>, string> = { pre: "Pre-market", regular: "Market open", post: "After hours", closed: "Market closed" };
const SOURCE: Record<string, string> = { positions: "positions", plans: "plans", investigations: "investigations", radar: "Radar", thesis: "thesis watch" };
/** Shown before the first read and when it fails: the two pinned rows still work. */
const PINNED: DeskThread[] = [
  { key: "briefing", group: "pinned", symbol: null, title: "Briefing", instrument: null, value: null, meter: null, investigationId: null,
    tradeId: null, radarEventId: null, path: null, changedAt: null, status: { text: "What matters right now? One turn across everything", tone: "muted" } },
  { key: "week", group: "pinned", symbol: null, title: "Review my week", instrument: null, value: null, meter: null, investigationId: null,
    tradeId: null, radarEventId: null, path: null, changedAt: null, status: { text: "Planned vs unplanned, follow-through, exits", tone: "muted" } },
];
const ASKS: Record<string, { name: string; prompt: string; hint: string }> = {
  briefing: { name: "What matters right now?", prompt: WHAT_MATTERS_PROMPT, hint: "One copilot turn across your positions, watches and open investigations" },
  week: { name: "Review my week", prompt: WEEK_REVIEW_CONTEXT, hint: "One copilot turn reviewing your latest trading week: planned vs unplanned, follow-through, alerts and exits" },
};
/** A real number sets in the desk's mono face; a word never does. */
const numeric = (text: string) => /^[+−-]?\$?\d/.test(text);

// "New since you looked" is remembered in this browser only, and a blocked store reads as nothing seen.
function readSeen(): Record<string, number> {
  try { return JSON.parse(window.localStorage.getItem(SEEN_KEY) ?? "{}") ?? {}; } catch { return {}; }
}
function writeSeen(seen: Record<string, number>) {
  try { window.localStorage.setItem(SEEN_KEY, JSON.stringify(seen)); } catch { /* a private window keeps nothing */ }
}

const plain = (event: MouseEvent) => !event.metaKey && !event.ctrlKey && !event.shiftKey && event.button === 0;

/** Where the underlying sits on its plan: 0 is the invalidation, the tick the entry. */
function Meter({ meter }: { meter: NonNullable<DeskThread["meter"]> }) {
  return (
    <div role="img" aria-label={`Underlying ${Math.round(meter.last)}% of the way from the invalidation; entry at ${Math.round(meter.entry)}%`}
      title="The underlying's price on the plan: invalidation at the left, the tick is the entry" className="relative mt-1.5 h-1 rounded-full bg-muted">
      <div className={cn("absolute inset-y-0 left-0 rounded-full opacity-60", BAR[meter.tone])} style={{ width: `${meter.last}%` }} />
      <div className="absolute -top-0.5 h-2 w-px bg-foreground/70" style={{ left: `${meter.entry}%` }} />
    </div>
  );
}

function Row({ row, unread, active, actions, seen }: {
  row: DeskThread; unread: boolean; active: boolean; actions: HomeActions; seen(row: DeskThread): void;
}) {
  const label = [row.symbol, row.symbol ? row.instrument ?? row.title : row.title].filter(Boolean).join(" ");
  const body = (
    <>
      <div className="flex min-w-0 items-baseline gap-1.5">
        {unread && <><span aria-hidden className="h-1.5 w-1.5 shrink-0 self-center rounded-full bg-primary" /><span className="sr-only">New:</span></>}
        <span className="shrink-0 font-semibold text-foreground">{row.symbol ?? row.title}</span>
        {row.symbol && (row.instrument ?? row.title) && <span className="min-w-0 truncate text-xs text-muted-foreground">{row.instrument ?? row.title}</span>}
        {row.value && (
          <span className={cn("ml-auto shrink-0 text-xs", TONE[row.value.tone], numeric(row.value.text) && "tabular-nums")}
            title={row.tradeId && numeric(row.value.text) ? "Unrealized P&L on this position (an option's own mark, not the underlying)" : undefined}>
            {row.value.text}
          </span>
        )}
      </div>
      <p className={cn("truncate text-xs", TONE[row.status.tone])} title={row.status.text}>{row.status.text}</p>
      {row.meter && (row.group === "act" || row.group === "near") && <Meter meter={row.meter} />}
    </>
  );
  const box = cn("block min-h-11 w-full rounded-md px-2.5 py-1.5 text-left text-sm hover:bg-secondary",
    active && "bg-secondary ring-1 ring-border", row.group === "new" && !unread && "opacity-70");
  const ask = ASKS[row.key];
  if (row.group === "pinned" && ask)
    return (
      <li>
        <button type="button" aria-label={ask.name} className={box} title={ask.hint} onClick={() => actions.ask(ask.prompt)}>{body}</button>
        {row.key === "week" && <PracticeLine className="px-2.5 pb-1 text-xs text-muted-foreground" />}
      </li>
    );
  const href = row.investigationId ? `/copilot-lab?investigation=${row.investigationId}` : row.path;
  if (!href) return <li className={box}>{body}</li>;
  return (
    <li>
      <Link href={href} aria-label={label} title={row.title} className={box}
        onClick={event => {
          seen(row);
          if (row.investigationId && plain(event)) { event.preventDefault(); actions.open(row.investigationId); }
        }}>
        {body}
      </Link>
    </li>
  );
}

function DayLine({ data }: { data: DeskThreads }) {
  const { phase, needYou, streak } = data.day;
  return (
    <p data-testid="desk-day" className="px-2.5 text-xs text-muted-foreground">
      {phase && <>{PHASE[phase]} · </>}
      {needYou ? <span className="text-primary"><span className="tabular-nums">{needYou}</span> need{needYou === 1 ? "s" : ""} you</span> : "Nothing needs you"}
      {streak && <> · plan streak <span className="tabular-nums">{streak.current}</span></>}
    </p>
  );
}

/**
 * The desk's thread list (docs/copilot-lab.md § The desk): one grouped list from ``GET /copilot/desk/threads`` in
 * ``DESK_GROUPS`` order, refreshed each minute while the page is visible. Pinned rows ask in the conversation (only
 * when pressed); a row with an investigation opens it in place, any other follows its deep link. Plan meters show
 * on Act now and Near a trigger only. "New since you looked" is remembered in this browser.
 */
export default function ThreadRail({ actions, active = null }: { actions: HomeActions; active?: string | null }) {
  const [data, setData] = useState<DeskThreads | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Rows arrive only after the first client read, so reading the store at first render cannot mismatch the server's.
  const [seen, setSeen] = useState<Record<string, number>>(() => typeof window === "undefined" ? {} : readSeen());
  useEffect(() => {
    let controller = new AbortController();
    const read = () => {
      controller.abort();
      controller = new AbortController();
      const signal = controller.signal;
      getDeskThreads(signal).then(next => { setData(next); setError(null); }).catch(failure => {
        if (!signal.aborted) setError(failure instanceof Error ? failure.message : "Threads are unavailable.");
      });
    };
    read();
    const timer = setInterval(() => { if (document.visibilityState === "visible") read(); }, REFRESH_MS);
    const shown = () => { if (document.visibilityState === "visible") read(); };
    document.addEventListener("visibilitychange", shown);
    return () => { controller.abort(); clearInterval(timer); document.removeEventListener("visibilitychange", shown); };
  }, []);

  const unread = (row: DeskThread) => row.group === "new" && row.changedAt !== null && row.changedAt > (seen[row.key] ?? 0);
  const mark = useCallback((rows: DeskThread[]) => setSeen(current => {
    const next = { ...current };
    for (const row of rows) if (row.changedAt !== null) next[row.key] = row.changedAt;
    writeSeen(next);
    return next;
  }), []);

  const rows = data?.threads ?? [];
  const pinned = rows.some(r => r.group === "pinned") ? rows.filter(r => r.group === "pinned") : PINNED;
  const missing = Object.entries(data?.sections ?? {}).filter(([name, state]) => state === "unavailable" && SOURCE[name]).map(([name]) => SOURCE[name]);

  const group = (id: DeskGroup, title: string) => {
    let items = id === "pinned" ? pinned : rows.filter(r => r.group === id);
    if (id === "new") items = [...items.filter(unread), ...items.filter(r => !unread(r))];
    const fresh = id === "new" ? items.filter(unread).length : 0;
    if (id !== "pinned" && id !== "act" && !items.length) return null;
    if (id === "act" && !data) return null;
    return (
      <section key={id} aria-label={title} className="space-y-0.5">
        <div className="flex items-baseline gap-2 px-2.5">
          <h3 className={cn("text-[11px] font-medium uppercase tracking-wide", id === "act" && items.length ? "text-primary" : "text-muted-foreground")}>{title}</h3>
          {id !== "pinned" && items.length > 0 && <span className="text-[11px] tabular-nums text-muted-foreground">{id === "new" ? fresh : items.length}</span>}
          {fresh > 0 && (
            <button type="button" onClick={() => mark(items)} className="-my-3 ml-auto min-h-11 px-1 text-[11px] text-muted-foreground hover:text-foreground sm:my-0 sm:min-h-0">Mark seen</button>
          )}
        </div>
        {id === "act" && !items.length ? (
          <p className="px-2.5 py-1 text-xs text-muted-foreground">
            {data?.sections.positions === "unavailable" ? "Positions unavailable right now." : "Clear. Nothing needs a decision right now."}
          </p>
        ) : (
          <ul className="space-y-0.5">
            {items.map(row => (
              <Row key={row.key} row={row} unread={unread(row)} actions={actions} seen={r => mark([r])}
                active={!!active && row.investigationId === active} />
            ))}
          </ul>
        )}
      </section>
    );
  };

  return (
    <nav aria-label="Thread list" className="space-y-3 text-sm">
      {data ? <DayLine data={data} /> : !error && <p className="px-2.5 text-xs text-muted-foreground">Reading what is live…</p>}
      {error && <p className="px-2.5 text-xs text-muted-foreground">{data ? "Not refreshed" : "Threads unavailable"}: {error}</p>}
      {DESK_GROUPS.map(g => group(g.id, g.title))}
      {data && missing.length > 0 && <p className="px-2.5 text-xs text-muted-foreground">Unavailable right now: {missing.join(", ")}.</p>}
      {data?.quoteIssue && <p className="px-2.5 text-xs text-muted-foreground">Prices: {data.quoteIssue}</p>}
      {data && <div className="px-2.5"><PlanATrade origin="copilot" className="inline-flex min-h-11 items-center gap-1.5 text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline sm:min-h-0" /></div>}
    </nav>
  );
}
