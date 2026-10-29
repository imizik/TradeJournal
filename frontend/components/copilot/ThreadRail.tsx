"use client";

import { useCallback, useEffect, useMemo, useState, type MouseEvent, type ReactNode } from "react";
import Link from "next/link";
import { KBD, useJumpKey } from "@/components/copilot/CommandPalette";
import PlanATrade from "@/components/copilot/PlanATrade";
import type { HomeActions } from "@/components/copilot/CopilotPanel";
import { WHAT_MATTERS_PROMPT, type InvestigationSummary } from "@/lib/copilot";
import {
  DESK_GROUPS, getClosedThisWeek, getDeskThreads, nyDay, reviewSkipped, type DeskDay, type DeskGroup, type DeskThread, type DeskThreads, type DeskTone,
} from "@/lib/desk";
import { cn } from "@/lib/utils";

const REFRESH_MS = 60_000;
const SEEN_KEY = "desk.seen.v1";
export const TONE: Record<DeskTone, string> = {
  attention: "text-primary", loss: "text-rose-300", gain: "text-emerald-300", info: "text-foreground", muted: "text-muted-foreground",
};
const BAR: Record<DeskTone, string> = {
  attention: "bg-primary", loss: "bg-rose-400", gain: "bg-emerald-400", info: "bg-foreground", muted: "bg-muted-foreground",
};
/** Each group's dot: rose for what needs a decision, sky for what is near or new, amber for what waits on the owner. */
const DOT: Record<DeskGroup, string> = {
  pinned: "bg-muted-foreground", act: "bg-rose-400", near: "bg-sky-400", draft: "bg-primary", new: "bg-sky-400", watch: "bg-muted-foreground",
};
/** New since you looked and Watching show this many rows, the rest behind "+N more", so a busy day reads as about ten. */
const SHOWN: Partial<Record<DeskGroup, number>> = { new: 5, watch: 3 };
const PHASE: Record<NonNullable<DeskDay["phase"]>, string> = { pre: "Pre-market", regular: "Market open", post: "After hours", closed: "Market closed" };
const SOURCE: Record<string, string> = { positions: "positions", plans: "plans", investigations: "investigations", radar: "Radar", thesis: "thesis watch" };
/** Shown before the first read and when it fails: the pinned Briefing still works. Review my week lives in ⌘K and the
 * Briefing, so the server's pinned week row is not listed. */
const PINNED: DeskThread[] = [
  { key: "briefing", group: "pinned", symbol: null, title: "Briefing", instrument: null, value: null, meter: null, investigationId: null,
    tradeId: null, radarEventId: null, path: null, changedAt: null, close: null, status: { text: "What matters right now? One turn across everything", tone: "muted" } },
];
const ASKS: Record<string, { name: string; prompt: string; hint: string }> = {
  briefing: { name: "What matters right now?", prompt: WHAT_MATTERS_PROMPT, hint: "One copilot turn across your positions, watches and open investigations" },
};
/** A real number sets in the desk's mono face; a word never does. */
export const numeric = (text: string) => /^[+−-]?\$?\d/.test(text);

// "New since you looked" is remembered in this browser only, and a blocked store reads as nothing seen.
function readSeen(): Record<string, number> {
  try { return JSON.parse(window.localStorage.getItem(SEEN_KEY) ?? "{}") ?? {}; } catch { return {}; }
}
function writeSeen(seen: Record<string, number>) {
  try { window.localStorage.setItem(SEEN_KEY, JSON.stringify(seen)); } catch { /* a private window keeps nothing */ }
}

/** New since you looked, calm: one row per symbol, a Radar hit ahead of thesis news, newest first. A row with no symbol
 * stands alone. */
function onePerSymbol(items: DeskThread[]) {
  const radar = (row: DeskThread) => row.key.startsWith("radar:");
  const ranked = [...items].sort((a, b) => Number(radar(b)) - Number(radar(a)) || (b.changedAt ?? 0) - (a.changedAt ?? 0));
  const kept = new Set<string>();
  return ranked.filter(row => !row.symbol || (!kept.has(row.symbol) && !!kept.add(row.symbol)));
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

function Row({ row, unread, active, actions, seen, skipped }: {
  row: DeskThread; unread: boolean; active: boolean; actions: HomeActions; seen(row: DeskThread): void; skipped: boolean;
}) {
  // After the close a row still asking its review says so in a muted amber; one skipped today says that instead.
  const asking = !!row.close && !row.close.reviewed;
  const status = asking && skipped ? { text: "Skipped today", tone: "muted" as const } : row.status;
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
      <p className={cn("truncate text-xs", TONE[status.tone], asking && !skipped && "text-primary/75")} title={status.text}>{status.text}</p>
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
 * on Act now and Near a trigger only. "New since you looked" is remembered in this browser. ``onRows`` gets the rows in
 * the order shown, for the desk's J / K and its palette. New since you looked keeps one row per symbol; it and Watching
 * show their ``SHOWN`` rows and "+N more". Conversations closed this week wait in a collapsed footer. ``phase`` (the
 * day's phase button) sits under the day line. A change of ``refresh`` reads the list again (a review just saved).
 */
export default function ThreadRail({ actions, active = null, onRows, phase = null, refresh = 0 }: {
  actions: HomeActions; active?: string | null; onRows?(rows: DeskThread[]): void; phase?: ReactNode; refresh?: number;
}) {
  const [data, setData] = useState<DeskThreads | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [closed, setClosed] = useState<InvestigationSummary[]>([]);
  const [more, setMore] = useState<Partial<Record<DeskGroup, boolean>>>({});
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
      getClosedThisWeek(signal).then(setClosed).catch(() => { /* the footer is extra */ });
    };
    read();
    const timer = setInterval(() => { if (document.visibilityState === "visible") read(); }, REFRESH_MS);
    const shown = () => { if (document.visibilityState === "visible") read(); };
    document.addEventListener("visibilitychange", shown);
    return () => { controller.abort(); clearInterval(timer); document.removeEventListener("visibilitychange", shown); };
  }, [refresh]);

  const unread = (row: DeskThread) => row.group === "new" && row.changedAt !== null && row.changedAt > (seen[row.key] ?? 0);
  const mark = useCallback((rows: DeskThread[]) => setSeen(current => {
    const next = { ...current };
    for (const row of rows) if (row.changedAt !== null) next[row.key] = row.changedAt;
    writeSeen(next);
    return next;
  }), []);

  const rows = data?.threads ?? [];
  const served = rows.filter(r => r.group === "pinned" && r.key !== "week");
  const pinned = served.length ? served : PINNED;
  const itemsOf = (id: DeskGroup) => {
    const items = id === "pinned" ? pinned : rows.filter(r => r.group === id);
    return id === "new" ? onePerSymbol(items) : items;
  };
  // Opening a symbol's new row sees everything new on that symbol, folded rows included.
  const seenRow = (row: DeskThread) => mark(row.group === "new" && row.symbol ? rows.filter(r => r.group === "new" && r.symbol === row.symbol) : [row]);
  const ordered = useMemo(() => DESK_GROUPS.flatMap(g => itemsOf(g.id)), [data, seen]); // eslint-disable-line react-hooks/exhaustive-deps -- rows and unread come from these two
  useEffect(() => { onRows?.(ordered); }, [ordered, onRows]);
  const jumpKey = useJumpKey();
  const day = data ? nyDay(new Date(data.asOf)) : null;
  const missing = Object.entries(data?.sections ?? {}).filter(([name, state]) => state === "unavailable" && SOURCE[name]).map(([name]) => SOURCE[name]);

  const group = (id: DeskGroup, title: string) => {
    const items = itemsOf(id);
    const fresh = id === "new" ? items.filter(unread).length : 0;
    if (id !== "pinned" && id !== "act" && !items.length) return null;
    if (id === "act" && !data) return null;
    const limit = SHOWN[id] ?? items.length;
    const capped = items.length > limit;
    const shown = capped && !more[id] ? items.slice(0, limit) : items;
    return (
      <section key={id} aria-label={title} className="space-y-0.5">
        <div className="flex items-center gap-2 px-2.5">
          <span aria-hidden className={cn("h-1.5 w-1.5 shrink-0 rounded-full", DOT[id])} />
          <h3 className={cn("text-[11px] font-medium uppercase tracking-wide", id === "act" && items.length ? "text-primary" : "text-muted-foreground")}>{title}</h3>
          {fresh > 0 && (
            <button type="button" onClick={() => mark(rows.filter(r => r.group === "new"))} className="-my-3 min-h-11 px-1 text-[11px] text-muted-foreground hover:text-foreground sm:my-0 sm:min-h-0">Mark seen</button>
          )}
          {id !== "pinned" && items.length > 0 && <span className="ml-auto text-[11px] tabular-nums text-muted-foreground" aria-label={`${items.length} ${items.length === 1 ? "thread" : "threads"}`}>{items.length}</span>}
        </div>
        {id === "act" && !items.length ? (
          <p className="px-2.5 py-1 text-xs text-muted-foreground">
            {data?.sections.positions === "unavailable" ? "Positions unavailable right now." : "Clear. Nothing needs a decision right now."}
          </p>
        ) : (
          <ul className="space-y-0.5">
            {shown.map(row => (
              <Row key={row.key} row={row} unread={unread(row)} actions={actions} seen={seenRow}
                skipped={!!(day && row.symbol && row.close && reviewSkipped(day, row.symbol))}
                active={!!active && row.investigationId === active} />
            ))}
          </ul>
        )}
        {capped && (
          <button type="button" aria-expanded={!!more[id]} onClick={() => setMore(open => ({ ...open, [id]: !open[id] }))}
            className="min-h-11 w-full rounded-md px-2.5 text-left text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8">
            {more[id] ? "Show fewer" : <>+<span className="tabular-nums">{items.length - limit}</span> more</>}
          </button>
        )}
      </section>
    );
  };

  return (
    <nav aria-label="Thread list" className="space-y-3 text-sm">
      {data ? <DayLine data={data} /> : !error && <p className="px-2.5 text-xs text-muted-foreground">Reading what is live…</p>}
      {error && <p className="px-2.5 text-xs text-muted-foreground">{data ? "Not refreshed" : "Threads unavailable"}: {error}</p>}
      {phase && <div className="px-2.5">{phase}</div>}
      {DESK_GROUPS.map(g => group(g.id, g.title))}
      {data && missing.length > 0 && <p className="px-2.5 text-xs text-muted-foreground">Unavailable right now: {missing.join(", ")}.</p>}
      {data?.quoteIssue && <p className="px-2.5 text-xs text-muted-foreground">Prices: {data.quoteIssue}</p>}
      {data && <div className="px-2.5"><PlanATrade origin="copilot" className="inline-flex min-h-11 items-center gap-1.5 text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline sm:min-h-0" /></div>}
      {closed.length > 0 && (
        <details className="group border-t pt-2">
          <summary className="flex min-h-11 cursor-pointer list-none items-center rounded-md px-2.5 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8 [&::-webkit-details-marker]:hidden">
            Closed this week<span className="ml-auto tabular-nums">{closed.length}</span>
          </summary>
          <ul className="mt-1 space-y-0.5">
            {closed.map(row => (
              <li key={row.id}>
                <Link href={`/copilot-lab?investigation=${row.id}`} title={row.title}
                  onClick={event => { if (plain(event)) { event.preventDefault(); actions.open(row.id); } }}
                  className={cn("block min-h-11 rounded-md px-2.5 py-1.5 text-sm hover:bg-secondary", active === row.id && "bg-secondary ring-1 ring-border")}>
                  <span className="flex min-w-0 items-baseline gap-1.5">
                    <span className="shrink-0 font-semibold text-foreground">{row.symbol ?? row.title}</span>
                    {row.symbol && <span className="min-w-0 truncate text-xs text-muted-foreground">{row.title}</span>}
                  </span>
                  {row.conclusion && <span className="block truncate text-xs text-muted-foreground">{row.conclusion}</span>}
                </Link>
              </li>
            ))}
          </ul>
        </details>
      )}
      <p data-testid="desk-keys" className="hidden items-center gap-1 whitespace-nowrap border-t px-2.5 pt-3 text-[11px] text-muted-foreground md:flex">
        <kbd className={KBD}>J</kbd><kbd className={KBD}>K</kbd>move<kbd className={cn(KBD, "ml-1.5")}>{jumpKey}</kbd>jump
        <kbd className={cn(KBD, "ml-1.5")}>N</kbd>plan<kbd className={cn(KBD, "ml-1.5")}>]</kbd>context
      </p>
    </nav>
  );
}
