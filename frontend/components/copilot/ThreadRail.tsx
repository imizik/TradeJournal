"use client";

import { useCallback, useEffect, useMemo, useState, type MouseEvent, type ReactNode } from "react";
import Link from "next/link";
import { ChevronDown, ChevronRight, Home } from "lucide-react";
import { KBD, useJumpKey } from "@/components/copilot/CommandPalette";
import PlanATrade from "@/components/copilot/PlanATrade";
import PlanList from "@/components/copilot/PlanList";
import type { HomeActions } from "@/components/copilot/CopilotPanel";
import { AUTO_WEEK_REVIEW_TITLE, type InvestigationSummary } from "@/lib/copilot";
import {
  getDeskThreads, getSavedConversations, needsYou, nyDay, reviewSkipped, type DeskGroup, type DeskPlan, type DeskThread, type DeskThreads, type DeskTone,
} from "@/lib/desk";
import { cn } from "@/lib/utils";

const REFRESH_MS = 60_000;
const SEEN_KEY = "desk.seen.v1";
/** All threads or Plans, remembered in this browser. */
const VIEW_KEY = "desk.rail.v1";
export const TONE: Record<DeskTone, string> = {
  attention: "text-primary", loss: "text-rose-300", gain: "text-emerald-300", info: "text-foreground", muted: "text-muted-foreground",
};
const BAR: Record<DeskTone, string> = {
  attention: "bg-primary", loss: "bg-rose-400", gain: "bg-emerald-400", info: "bg-foreground", muted: "bg-muted-foreground",
};
const SOURCE: Record<string, string> = { positions: "positions", plans: "plans", investigations: "investigations", drafts: "waiting cards", radar: "Radar", thesis: "thesis watch" };
/** A ticker's state, in sort order after "needs you". */
type TickerState = "held" | "armed" | "exited" | "watching" | "closed";
const STATE: Record<TickerState, { text: string; tone: string }> = {
  held: { text: "Held", tone: "bg-emerald-400/10 text-emerald-300" },
  armed: { text: "Plan armed", tone: "bg-sky-400/10 text-sky-300" },
  exited: { text: "Exited", tone: "bg-secondary text-muted-foreground" },
  watching: { text: "Watching", tone: "bg-secondary text-muted-foreground" },
  closed: { text: "Closed", tone: "bg-secondary text-muted-foreground" },
};
const RANK: Record<TickerState, number> = { held: 0, armed: 1, exited: 2, watching: 3, closed: 4 };
/** Which row speaks for a ticker: the most urgent. */
const URGENCY: Record<DeskGroup, number> = { act: 0, near: 1, draft: 2, new: 3, watch: 4, pinned: 5 };
/** Tickers past the ones that need the owner, are held or have an armed plan: this many shown, the rest behind "+N more". */
const QUIET_SHOWN = 6;
/** A ticker's open conversations shown before "Earlier · N". */
const CHILDREN_SHOWN = 3;
/** A real number sets in the desk's mono face; a word never does. */
export const numeric = (text: string) => /^[+−-]?\$?\d/.test(text);
const shortDay = (iso: string) => new Date(iso).toLocaleDateString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric" });

// "New since you looked" is remembered in this browser only, and a blocked store reads as nothing seen.
function readSeen(): Record<string, number> {
  try { return JSON.parse(window.localStorage.getItem(SEEN_KEY) ?? "{}") ?? {}; } catch { return {}; }
}
function writeSeen(seen: Record<string, number>) {
  try { window.localStorage.setItem(SEEN_KEY, JSON.stringify(seen)); } catch { /* a private window keeps nothing */ }
}

const plain = (event: MouseEvent) => !event.metaKey && !event.ctrlKey && !event.shiftKey && event.button === 0;
const isRadar = (row: DeskThread) => row.key.startsWith("radar:");

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

/** One ticker: every desk row about it (a position, a plan, an exit review, a waiting card, news, an open conversation)
 * and its saved conversations, newest first. */
export type Ticker = {
  symbol: string; rows: DeskThread[]; lead: DeskThread | null; state: TickerState; needs: boolean;
  value: DeskThread["value"]; status: DeskThread["status"]; conversations: InvestigationSummary[]; changedAt: number;
};

/** The thread list's tickers in order: needs-you first, then held, armed plans, exited, watching, closed this week. */
export function tickersOf(rows: DeskThread[], plans: DeskPlan[], saved: InvestigationSummary[], needs: (row: DeskThread) => boolean): Ticker[] {
  const by = new Map<string, DeskThread[]>();
  for (const row of rows) {
    if (row.group === "pinned" || isRadar(row) || !row.symbol) continue;
    by.set(row.symbol, [...(by.get(row.symbol) ?? []), row]);
  }
  const talks = new Map<string, InvestigationSummary[]>();
  for (const talk of saved) if (talk.symbol) talks.set(talk.symbol, [...(talks.get(talk.symbol) ?? []), talk]);
  // A conversation closed this week keeps its ticker on the list; an older closed one shows only under a ticker that is.
  for (const [symbol, list] of talks) if (!by.has(symbol) && list.some(t => t.status === "closed" && closedThisWeek(t))) by.set(symbol, []);
  return [...by].map(([symbol, own]) => {
    const ranked = [...own].sort((a, b) => URGENCY[a.group] - URGENCY[b.group]);
    const lead = ranked[0] ?? null;
    const position = own.find(r => r.tradeId);
    const exit = own.find(r => r.close?.kind === "exit");
    const armed = plans.some(p => p.symbol === symbol && p.stage === "armed") || own.some(r => r.key.startsWith("plan:") && r.value?.text === "Armed");
    const state: TickerState = position ? "held" : armed ? "armed" : exit ? "exited" : own.length ? "watching" : "closed";
    const conversations = [...(talks.get(symbol) ?? [])].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
    const newest = Math.max(0, ...own.map(r => r.changedAt ?? 0), ...conversations.map(t => Date.parse(t.updated_at) / 1000));
    return {
      symbol, rows: ranked, lead, state, needs: own.some(needs), changedAt: newest, conversations,
      value: position?.value ?? exit?.value ?? null,
      status: lead?.status ?? { text: conversations[0]?.conclusion ?? conversations[0]?.title ?? "", tone: "muted" as const },
    };
  }).sort((a, b) => Number(b.needs) - Number(a.needs) || RANK[a.state] - RANK[b.state] || b.changedAt - a.changedAt);
}

function closedThisWeek(talk: InvestigationSummary) {
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date());
  const noon = Date.parse(`${today}T12:00:00Z`);
  const monday = new Date(noon - ((new Date(noon).getUTCDay() + 6) % 7) * 86_400_000).toISOString().slice(0, 10);
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date(talk.updated_at)) >= monday;
}

const box = (active: boolean) => cn("block min-h-11 w-full rounded-md px-2.5 py-1.5 text-left text-sm hover:bg-secondary", active && "bg-secondary ring-1 ring-border");

/** One conversation under Main or a ticker: its title and date. */
function Talk({ id, title, at, tag, active, actions }: { id: string; title: string; at: string | null; tag?: string | null; active: string | null; actions: HomeActions }) {
  return (
    <li>
      <Link href={`/copilot-lab?investigation=${id}`} title={title} aria-current={active === id ? "page" : undefined}
        onClick={event => { if (plain(event)) { event.preventDefault(); actions.open(id); } }}
        className={cn("flex min-h-11 items-center gap-1.5 rounded-md px-2 py-1 text-xs hover:bg-secondary sm:min-h-8",
          active === id ? "bg-secondary text-foreground" : "text-muted-foreground")}>
        {tag && <span className="shrink-0 rounded border px-1 text-[10px] leading-4">{tag}</span>}
        <span className="min-w-0 truncate">{title}</span>
        {at && <span className="ml-auto shrink-0 tabular-nums">{shortDay(at)}</span>}
      </Link>
    </li>
  );
}

/** "Earlier · 4" or "Closed · 3": conversations kept out of the way, opened in place. Nothing when none. */
function Fold({ label, opened = false, children, count }: { label: string; opened?: boolean; children: ReactNode; count: number }) {
  const [open, setOpen] = useState(false);
  if (!count) return null;
  const shown = open || opened;
  return (
    <li>
      <button type="button" aria-expanded={shown} onClick={() => setOpen(!shown)}
        className="flex min-h-11 w-full items-center gap-1 rounded-md px-2 text-left text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-7">
        {shown ? <ChevronDown size={12} aria-hidden /> : <ChevronRight size={12} aria-hidden />}{label} · <span className="tabular-nums">{count}</span>
      </button>
      {shown && <ul aria-label={label} className="space-y-0.5">{children}</ul>}
    </li>
  );
}

/** A ticker's open conversations in view (the newest, and always the open one), the other open ones, and the closed. */
function foldTalks(ticker: Ticker, active: string | null) {
  const open = ticker.conversations.filter(t => t.status !== "closed");
  const shown = open.filter((t, i) => i < CHILDREN_SHOWN || t.id === active);
  return { shown, earlier: open.filter(t => !shown.includes(t)), closed: ticker.conversations.filter(t => t.status === "closed") };
}

/** A ticker's subthreads: its newest open conversations (title and date; the plan's and the exit review's named), the
 * other open ones under Earlier and the closed ones under Closed. The open conversation always shows. */
function Children({ ticker, active, actions }: { ticker: Ticker; active: string | null; actions: HomeActions }) {
  const planOf = new Set(ticker.rows.filter(r => r.key.startsWith("plan:") && r.close?.kind !== "exit").map(r => r.investigationId));
  const exitOf = new Set(ticker.rows.filter(r => r.close?.kind === "exit").map(r => r.investigationId));
  const row = (talk: InvestigationSummary) => <Talk key={talk.id} id={talk.id} title={talk.title} at={talk.updated_at} active={active} actions={actions}
    tag={exitOf.has(talk.id) ? "Exit review" : planOf.has(talk.id) ? "Plan" : null} />;
  const { shown, earlier, closed } = foldTalks(ticker, active);
  return (
    <ul aria-label={`${ticker.symbol} threads`} className="ml-3.5 space-y-0.5 border-l pl-1.5">
      {shown.map(row)}
      <Fold label="Earlier" count={earlier.length}>{earlier.map(row)}</Fold>
      <Fold label="Closed" count={closed.length} opened={closed.some(t => t.id === active)}>{closed.map(row)}</Fold>
    </ul>
  );
}

function TickerRow({ ticker, open, expanded, onExpand, active, actions, pick, skipped, unread }: {
  ticker: Ticker; open: boolean; expanded: boolean; onExpand(): void; active: string | null; actions: HomeActions; pick(ticker: Ticker): void; skipped: boolean; unread: boolean;
}) {
  const lead = ticker.lead;
  // After the close a row still asking its review says so in a muted amber; one skipped today says that instead.
  const asking = !!lead?.close && !lead.close.reviewed;
  const status = asking && skipped ? { text: "Skipped today", tone: "muted" as const } : ticker.status;
  const state = STATE[ticker.state];
  const here = open && (!active || ticker.conversations.every(t => t.id !== active) || ticker.conversations.length < 2);
  const meter = lead?.meter && (lead.group === "act" || lead.group === "near") ? lead.meter : null;
  const many = ticker.conversations.length > 1;
  return (
    <li>
      <div className="flex items-stretch gap-0.5">
      <button type="button" onClick={() => pick(ticker)}
        aria-label={[ticker.symbol, state.text, ticker.needs ? "needs you" : null].filter(Boolean).join(", ")} title={lead?.title}
        className={cn(box(here), "min-w-0 flex-1", open && !here && "bg-secondary/50")}>
        <span className="flex min-w-0 items-center gap-1.5">
          {ticker.needs
            ? <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
            : unread ? <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-sky-400" /> : <span aria-hidden className="w-1.5 shrink-0" />}
          <span className="shrink-0 font-semibold text-foreground">{ticker.symbol}</span>
          <span className={cn("shrink-0 rounded px-1 text-[10px] leading-4", state.tone)}>{state.text}</span>
          {ticker.value && (
            <span className={cn("ml-auto shrink-0 text-xs", TONE[ticker.value.tone], numeric(ticker.value.text) && "tabular-nums")}
              title={lead?.tradeId && numeric(ticker.value.text) ? "Unrealized P&L on this position (an option's own mark, not the underlying)" : undefined}>
              {ticker.value.text}
            </span>
          )}
        </span>
        {status.text && <span className={cn("block truncate pl-3 text-xs", TONE[status.tone], asking && !skipped && "text-primary/75")} title={status.text}>{status.text}</span>}
        {meter && <div className="pl-3"><Meter meter={meter} /></div>}
      </button>
      {/* A ticker with one conversation keeps the column, so the P&L figures line up. */}
      {!many ? <span aria-hidden className="w-9 shrink-0" /> : (
        <button type="button" onClick={onExpand} aria-expanded={expanded} aria-label={`${expanded ? "Hide" : "Show"} ${ticker.symbol} threads`}
          title={`${ticker.conversations.length} conversations. This keeps the one you have open.`}
          className="flex w-9 shrink-0 items-center justify-center gap-0.5 rounded-md text-[11px] text-muted-foreground hover:bg-secondary hover:text-foreground">
          <span className="tabular-nums">{ticker.conversations.length}</span>{expanded ? <ChevronDown size={12} aria-hidden /> : <ChevronRight size={12} aria-hidden />}
        </button>
      )}
      </div>
      {many && expanded && <Children ticker={ticker} active={active} actions={actions} />}
    </li>
  );
}

function DayLine({ data, needYou }: { data: DeskThreads; needYou: number }) {
  const { streak } = data.day;
  return (
    <p data-testid="desk-day" className="px-2.5 text-xs text-muted-foreground">
      {needYou ? <span className="text-primary"><span className="tabular-nums">{needYou}</span> need{needYou === 1 ? "s" : ""} you</span> : "Nothing needs you"}
      {streak && <> · plan streak <span className="tabular-nums">{streak.current}</span></>}
    </p>
  );
}

/**
 * The desk's thread list (docs/copilot-lab.md § The desk): **Main** (the Briefing, the market-wide thread), pinned at the
 * top on a wide screen with today's conversations under it and the rest under Earlier, then one row per ticker the owner
 * has something on (a position, a plan, a waiting card, a conversation), from ``GET /copilot/desk/threads`` and the latest
 * saved conversations, refreshed each minute while the page is visible. A ticker row shows its state, P&L and a "needs
 * you" dot; tickers sort under Needs you, Held and armed, and Others. Pressing a ticker opens its newest conversation (or
 * follows its row's link when it has none) and shows its subthreads; with more than one, its count and arrow show or hide
 * them without changing the open conversation, and any number can stay open. Radar hits, alerts to answer and Review my
 * week live inside Main; ``toAnswer`` is how many are waiting.
 * ``onRows`` gets the desk rows in the order shown, for the palette; ``onWalk`` the conversations J / K walk, as the list
 * shows them (under Main, then each ticker: its subthreads when shown, else its newest); ``onSaved`` the saved conversations, for
 * the breadcrumb. All | Plans switches to the Plans view (``PlanList``) from the same read, remembered in this browser.
 */
export default function ThreadRail({ actions, active = null, activeSymbol = null, main = false, onRows, onWalk, onSaved, phase = null, refresh = 0, toAnswer = 0, pick }: {
  actions: HomeActions; active?: string | null; activeSymbol?: string | null; main?: boolean; onRows?(rows: DeskThread[]): void; onWalk?(ids: string[]): void;
  onSaved?(saved: InvestigationSummary[]): void; phase?: ReactNode; refresh?: number; toAnswer?: number; pick(row: DeskThread): void;
}) {
  const [data, setData] = useState<DeskThreads | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<InvestigationSummary[]>([]);
  const [more, setMore] = useState(false);
  const [opened, setOpened] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => new Set());
  const expand = useCallback((symbol: string, show = true) => setExpanded(was => {
    const next = new Set(was);
    if (show) next.add(symbol); else next.delete(symbol);
    return next;
  }), []);
  const [view, setView] = useState<"threads" | "plans">("threads");
  useEffect(() => {
    try { if (window.localStorage.getItem(VIEW_KEY) === "plans") setView("plans"); } catch { /* threads */ } // eslint-disable-line react-hooks/set-state-in-effect -- the store is read after hydration
  }, []);
  const pickView = (next: "threads" | "plans") => {
    setView(next);
    try { window.localStorage.setItem(VIEW_KEY, next); } catch { /* this visit only */ }
  };
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
      getSavedConversations(signal).then(setSaved).catch(() => { /* the subthreads are extra */ });
    };
    read();
    const timer = setInterval(() => { if (document.visibilityState === "visible") read(); }, REFRESH_MS);
    const shown = () => { if (document.visibilityState === "visible") read(); };
    document.addEventListener("visibilitychange", shown);
    return () => { controller.abort(); clearInterval(timer); document.removeEventListener("visibilitychange", shown); };
  }, [refresh]);
  useEffect(() => { onSaved?.(saved); }, [saved, onSaved]);

  const unread = (row: DeskThread) => row.group === "new" && row.changedAt !== null && row.changedAt > (seen[row.key] ?? 0);
  const mark = useCallback((rows: DeskThread[]) => setSeen(current => {
    const next = { ...current };
    for (const row of rows) if (row.changedAt !== null) next[row.key] = row.changedAt;
    writeSeen(next);
    return next;
  }), []);

  const rows = useMemo(() => data?.threads ?? [], [data]);
  const day = data ? nyDay(new Date(data.asOf)) : null;
  const needs = useCallback((row: DeskThread) => needsYou(row, day), [day]);
  const tickers = useMemo(() => tickersOf(rows, data?.plans ?? [], saved, needs), [rows, data, saved, needs]);
  const briefing = rows.find(r => r.key === "briefing");
  const radar = rows.filter(isRadar);
  const radarNew = radar.filter(unread).length;
  // Conversations about no ticker (a Briefing turn, a week review): the desk's own rows, then the other open ones saved.
  const loose = useMemo(() => {
    const own = rows.filter(r => !r.symbol && r.investigationId && r.group !== "pinned" && !isRadar(r)).map(r => ({
      id: r.investigationId!, title: r.title, at: saved.find(t => t.id === r.investigationId)?.updated_at ?? (r.changedAt ? new Date(r.changedAt * 1000).toISOString() : null) }));
    const seenIds = new Set(own.map(t => t.id));
    return [...own, ...saved.filter(t => !t.symbol && t.status === "open" && !seenIds.has(t.id)).map(t => ({ id: t.id, title: t.title, at: t.updated_at }))];
  }, [rows, saved]);
  const ordered = useMemo(() => [...rows.filter(r => r.group === "pinned"), ...tickers.flatMap(t => t.rows), ...rows.filter(isRadar)], [rows, tickers]);
  useEffect(() => { if (data) onRows?.(ordered); }, [data, ordered, onRows]); // once read: the placeholder is not the list
  const jumpKey = useJumpKey();
  const livePlans = data?.plans.filter(p => p.stage === "armed" || p.stage === "in_position").length ?? 0;
  // Under Main: today's conversations, the open one and the latest automatic week review; the rest wait under Earlier.
  const weekReview = loose.find(t => t.title.startsWith(AUTO_WEEK_REVIEW_TITLE));
  const looseShown = loose.filter(t => t === weekReview || t.id === active || (day && t.at && nyDay(new Date(t.at)) === day));
  const looseEarlier = loose.filter(t => !looseShown.includes(t));
  const missing = Object.entries(data?.sections ?? {}).filter(([name, state]) => state === "unavailable" && SOURCE[name]).map(([name]) => SOURCE[name]);
  // The open ticker: the one just pressed, until the open conversation changes; then the conversation's.
  useEffect(() => { setOpened(null); if (activeSymbol) expand(activeSymbol); }, [activeSymbol, expand]); // eslint-disable-line react-hooks/set-state-in-effect -- a new conversation takes over
  const openSymbol = opened ?? activeSymbol;
  const needing = tickers.filter(t => t.needs);
  const live = tickers.filter(t => !t.needs && (t.state === "held" || t.state === "armed"));
  const quiet = tickers.filter(t => !t.needs && !live.includes(t));
  const shownQuiet = more ? quiet : quiet.slice(0, Math.max(QUIET_SHOWN, quiet.findIndex(t => t.symbol === openSymbol) + 1));
  const walk = [...looseShown.map(t => t.id), ...[...needing, ...live, ...shownQuiet].flatMap(ticker => {
    if (!ticker.conversations.length) return ticker.rows.flatMap(r => r.investigationId ? [r.investigationId] : []);
    const shown = expanded.has(ticker.symbol) ? foldTalks(ticker, active).shown : [];
    const walked = ticker.conversations.filter(t => shown.includes(t) || t.id === active || (!shown.length && t === ticker.conversations[0]));
    return walked.map(t => t.id);
  })];
  const walkKey = [...new Set(walk)].join();
  useEffect(() => { onWalk?.(walkKey ? walkKey.split(",") : []); }, [walkKey, onWalk]);

  const press = (ticker: Ticker) => {
    setOpened(ticker.symbol);
    expand(ticker.symbol);
    mark(ticker.rows.filter(r => r.group === "new"));
    const newest = ticker.conversations[0];
    if (newest && !ticker.conversations.some(t => t.id === active)) actions.open(newest.id);
    else if (!newest && ticker.lead) pick(ticker.lead);
  };

  return (
    <nav aria-label="Thread list" className="space-y-3 text-sm">
      {data ? <DayLine data={data} needYou={needing.length} /> : !error && <p className="px-2.5 text-xs text-muted-foreground">Reading what is live…</p>}
      {error && <p className="px-2.5 text-xs text-muted-foreground">{data ? "Not refreshed" : "Threads unavailable"}: {error}</p>}
      {phase && <div className="px-2.5">{phase}</div>}
      <div role="tablist" aria-label="Thread list view" className="mx-2.5 grid grid-cols-2 gap-1 rounded-md border p-0.5 text-xs">
        {(["threads", "plans"] as const).map(id => (
          <button key={id} type="button" role="tab" aria-selected={view === id} onClick={() => pickView(id)}
            className={cn("min-h-11 rounded px-2 sm:min-h-7", view === id ? "bg-secondary font-medium text-foreground" : "text-muted-foreground hover:text-foreground")}>
            {id === "threads" ? "All" : <>Plans{livePlans > 0 && <span className="ml-1 tabular-nums text-muted-foreground" aria-label={`, ${livePlans} live`}>{livePlans}</span>}</>}
          </button>
        ))}
      </div>
      {view === "plans" ? data && <PlanList plans={data.plans} actions={actions} active={active} /> : (
        <>
          {/* Pinned where the list scrolls on its own: the conversations under it scroll away, Main does not. */}
          <section aria-label="Main" className="z-10 bg-background lg:sticky lg:top-0 lg:shadow-[0_-12px_0_0_hsl(var(--background)),0_6px_0_0_hsl(var(--background))]">
            <button type="button" onClick={() => { setOpened(null); mark(radar); actions.home(); }} aria-current={main ? "page" : undefined}
              title="The market-wide thread: the day, Radar hits to rate, alerts to answer and Review my week" className={cn(box(main), "border", !main && "bg-card")}>
              <span className="flex items-center gap-1.5">
                <Home size={14} aria-hidden className="shrink-0 text-muted-foreground" />
                <span className="font-semibold text-foreground">Main</span>
                {radarNew > 0 && <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-sky-400" />}
                <span className="ml-auto flex shrink-0 gap-2 text-xs tabular-nums text-muted-foreground">
                  {toAnswer > 0 && <span className="text-primary" title="Alerts to answer and Radar hits to rate, in Main">{toAnswer} to answer</span>}
                  {radar.length > 0 && <span title="Radar hits since your last Radar visit; rate them in Main">{radar.length} Radar</span>}
                </span>
              </span>
              <span className={cn("block truncate pl-5 text-xs", TONE[briefing?.status.tone ?? "muted"])}>{briefing?.status.text ?? "What matters right now? One turn across everything"}</span>
            </button>
          </section>
          {loose.length > 0 && (
            <ul aria-label="Main threads" className="ml-3.5 space-y-0.5 border-l pl-1.5">
              {looseShown.map(talk => <Talk key={talk.id} id={talk.id} title={talk.title} at={talk.at} active={active} actions={actions} />)}
              <Fold label="Earlier" count={looseEarlier.length}>
                {looseEarlier.map(talk => <Talk key={talk.id} id={talk.id} title={talk.title} at={talk.at} active={active} actions={actions} />)}
              </Fold>
            </ul>
          )}
          {data && (
            <section aria-label="Tickers" className="space-y-0.5">
              {!tickers.length && <p className="px-2.5 py-1 text-xs text-muted-foreground">
                {data.sections.positions === "unavailable" ? "Positions unavailable right now." : "Nothing open. Plan a trade to start a ticker."}
              </p>}
              {([["Needs you", needing], ["Held and armed", live], ["Others", shownQuiet]] as const).map(([title, group]) => group.length > 0 && (
                <div key={title} className="space-y-0.5">
                  <h3 className="px-2.5 pt-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{title}</h3>
                  <ul className="space-y-0.5">
                    {group.map(ticker => (
                      <TickerRow key={ticker.symbol} ticker={ticker} open={openSymbol === ticker.symbol} expanded={expanded.has(ticker.symbol)}
                        onExpand={() => expand(ticker.symbol, !expanded.has(ticker.symbol))} active={active} actions={actions} pick={press}
                        skipped={!!(day && ticker.lead?.close && reviewSkipped(day, ticker.symbol))} unread={ticker.rows.some(unread)} />
                    ))}
                  </ul>
                </div>
              ))}
              {quiet.length > shownQuiet.length || more ? (
                <button type="button" aria-expanded={more} onClick={() => setMore(open => !open)}
                  className="min-h-11 w-full rounded-md px-2.5 text-left text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8">
                  {more ? "Show fewer" : <>+<span className="tabular-nums">{quiet.length - shownQuiet.length}</span> more</>}
                </button>
              ) : null}
            </section>
          )}
        </>
      )}
      {data && missing.length > 0 && <p className="px-2.5 text-xs text-muted-foreground">Unavailable right now: {missing.join(", ")}.</p>}
      {data?.quoteIssue && <p className="px-2.5 text-xs text-muted-foreground">Prices: {data.quoteIssue}</p>}
      {data && <div className="px-2.5"><PlanATrade origin="copilot" className="inline-flex min-h-11 items-center gap-1.5 text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline sm:min-h-0" /></div>}
      <p data-testid="desk-keys" className="hidden items-center gap-1 whitespace-nowrap border-t px-2.5 pt-3 text-[11px] text-muted-foreground md:flex">
        <kbd className={KBD}>J</kbd><kbd className={KBD}>K</kbd>move<kbd className={cn(KBD, "ml-1.5")}>{jumpKey}</kbd>jump
        <kbd className={cn(KBD, "ml-1.5")}>N</kbd>plan<kbd className={cn(KBD, "ml-1.5")}>]</kbd>context
      </p>
    </nav>
  );
}
