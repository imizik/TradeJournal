"use client";

import { useCallback, useEffect, useMemo, useState, type MouseEvent, type ReactNode } from "react";
import Link from "next/link";
import { KBD, useJumpKey } from "@/components/copilot/CommandPalette";
import PlanATrade from "@/components/copilot/PlanATrade";
import PlanList from "@/components/copilot/PlanList";
import type { HomeActions } from "@/components/copilot/CopilotPanel";
import type { InvestigationSummary } from "@/lib/copilot";
import {
  getDeskThreads, getSavedConversations, nyDay, reviewSkipped, type DeskDay, type DeskGroup, type DeskPlan, type DeskThread, type DeskThreads, type DeskTone,
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
const PHASE: Record<NonNullable<DeskDay["phase"]>, string> = { pre: "Pre-market", regular: "Market open", post: "After hours", closed: "Market closed" };
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

/** A ticker's subthreads: its conversations (title and date), the plan's and the exit review's named. */
function Children({ ticker, active, actions }: { ticker: Ticker; active: string | null; actions: HomeActions }) {
  const planOf = new Set(ticker.rows.filter(r => r.key.startsWith("plan:") && r.close?.kind !== "exit").map(r => r.investigationId));
  const exitOf = new Set(ticker.rows.filter(r => r.close?.kind === "exit").map(r => r.investigationId));
  return (
    <ul aria-label={`${ticker.symbol} threads`} className="ml-3.5 space-y-0.5 border-l pl-1.5">
      {ticker.conversations.map(talk => {
        const tag = exitOf.has(talk.id) ? "Exit review" : planOf.has(talk.id) ? "Plan" : null;
        return (
          <li key={talk.id}>
            <Link href={`/copilot-lab?investigation=${talk.id}`} title={talk.title} aria-current={active === talk.id ? "page" : undefined}
              onClick={event => { if (plain(event)) { event.preventDefault(); actions.open(talk.id); } }}
              className={cn("flex min-h-11 items-center gap-1.5 rounded-md px-2 py-1 text-xs hover:bg-secondary sm:min-h-8",
                active === talk.id ? "bg-secondary text-foreground" : "text-muted-foreground")}>
              {tag && <span className="shrink-0 rounded border px-1 text-[10px] leading-4">{tag}</span>}
              <span className="min-w-0 truncate">{talk.title}</span>
              <span className="ml-auto shrink-0 tabular-nums">{shortDay(talk.updated_at)}</span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function TickerRow({ ticker, open, active, actions, pick, skipped, unread }: {
  ticker: Ticker; open: boolean; active: string | null; actions: HomeActions; pick(ticker: Ticker): void; skipped: boolean; unread: boolean;
}) {
  const lead = ticker.lead;
  // After the close a row still asking its review says so in a muted amber; one skipped today says that instead.
  const asking = !!lead?.close && !lead.close.reviewed;
  const status = asking && skipped ? { text: "Skipped today", tone: "muted" as const } : ticker.status;
  const state = STATE[ticker.state];
  const here = open && (!active || ticker.conversations.every(t => t.id !== active) || ticker.conversations.length < 2);
  const meter = lead?.meter && (lead.group === "act" || lead.group === "near") ? lead.meter : null;
  return (
    <li>
      <button type="button" onClick={() => pick(ticker)} aria-expanded={ticker.conversations.length > 1 ? open : undefined}
        aria-label={[ticker.symbol, state.text, ticker.needs ? "needs you" : null].filter(Boolean).join(", ")} title={lead?.title}
        className={cn(box(here), open && !here && "bg-secondary/50")}>
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
      {open && ticker.conversations.length > 1 && <Children ticker={ticker} active={active} actions={actions} />}
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
 * The desk's thread list (docs/copilot-lab.md § The desk): **Main** (the Briefing, the market-wide thread) at the top, then
 * one row per ticker the owner has something on (a position, a plan, a waiting card, a conversation), from
 * ``GET /copilot/desk/threads`` and the latest saved conversations, refreshed each minute while the page is visible.
 * A ticker row shows its state, P&L and a "needs you" dot; tickers sort needs-you first, then held, armed plans and the
 * rest. Pressing a ticker opens its newest conversation (or follows its row's link when it has none) and, with more than
 * one, lists its conversations beneath as subthreads. Radar hits, alerts to answer and Review my week live inside Main.
 * ``onRows`` gets the desk rows in the order shown, for J / K and the palette; ``onSaved`` the saved conversations, for
 * the breadcrumb. All | Plans switches to the Plans view (``PlanList``) from the same read, remembered in this browser.
 */
export default function ThreadRail({ actions, active = null, activeSymbol = null, main = false, onRows, onSaved, phase = null, refresh = 0, pick }: {
  actions: HomeActions; active?: string | null; activeSymbol?: string | null; main?: boolean; onRows?(rows: DeskThread[]): void;
  onSaved?(saved: InvestigationSummary[]): void; phase?: ReactNode; refresh?: number; pick(row: DeskThread): void;
}) {
  const [data, setData] = useState<DeskThreads | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<InvestigationSummary[]>([]);
  const [more, setMore] = useState(false);
  const [opened, setOpened] = useState<string | null>(null);
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
  const needs = useCallback((row: DeskThread) => row.group === "act" || row.group === "draft" || !!row.fillToLink
    || (!!row.close && !row.close.reviewed && !(day && row.symbol && reviewSkipped(day, row.symbol))), [day]);
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
  const live = data?.plans.filter(p => p.stage === "armed" || p.stage === "in_position").length ?? 0;
  const missing = Object.entries(data?.sections ?? {}).filter(([name, state]) => state === "unavailable" && SOURCE[name]).map(([name]) => SOURCE[name]);
  // The open ticker: the one just pressed, until the open conversation changes; then the conversation's.
  useEffect(() => { setOpened(null); }, [activeSymbol]); // eslint-disable-line react-hooks/set-state-in-effect -- a new conversation takes over
  const openSymbol = opened ?? activeSymbol;
  const urgent = tickers.filter(t => t.needs || t.state === "held" || t.state === "armed");
  const quiet = tickers.filter(t => !urgent.includes(t));
  const shownQuiet = more ? quiet : quiet.slice(0, Math.max(QUIET_SHOWN, quiet.findIndex(t => t.symbol === openSymbol) + 1));

  const press = (ticker: Ticker) => {
    setOpened(ticker.symbol);
    mark(ticker.rows.filter(r => r.group === "new"));
    const newest = ticker.conversations[0];
    if (newest && !ticker.conversations.some(t => t.id === active)) actions.open(newest.id);
    else if (!newest && ticker.lead) pick(ticker.lead);
  };

  return (
    <nav aria-label="Thread list" className="space-y-3 text-sm">
      {data ? <DayLine data={data} /> : !error && <p className="px-2.5 text-xs text-muted-foreground">Reading what is live…</p>}
      {error && <p className="px-2.5 text-xs text-muted-foreground">{data ? "Not refreshed" : "Threads unavailable"}: {error}</p>}
      {phase && <div className="px-2.5">{phase}</div>}
      <div role="tablist" aria-label="Thread list view" className="mx-2.5 grid grid-cols-2 gap-1 rounded-md border p-0.5 text-xs">
        {(["threads", "plans"] as const).map(id => (
          <button key={id} type="button" role="tab" aria-selected={view === id} onClick={() => pickView(id)}
            className={cn("min-h-11 rounded px-2 sm:min-h-7", view === id ? "bg-secondary font-medium text-foreground" : "text-muted-foreground hover:text-foreground")}>
            {id === "threads" ? "All" : <>Plans{live > 0 && <span className="ml-1 tabular-nums text-muted-foreground" aria-label={`, ${live} live`}>{live}</span>}</>}
          </button>
        ))}
      </div>
      {view === "plans" ? data && <PlanList plans={data.plans} actions={actions} active={active} /> : (
        <>
          <section aria-label="Main" className="space-y-0.5">
            <button type="button" onClick={() => { setOpened(null); mark(radar); actions.home(); }} aria-current={main ? "page" : undefined}
              title="The market-wide thread: the day, Radar hits to rate, alerts to answer and Review my week" className={box(main)}>
              <span className="flex items-center gap-1.5">
                {radarNew > 0 ? <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-sky-400" /> : <span aria-hidden className="w-1.5 shrink-0" />}
                <span className="font-semibold text-foreground">Main</span>
                <span className="text-xs text-muted-foreground">Briefing</span>
                {radar.length > 0 && <span className="ml-auto shrink-0 text-xs tabular-nums text-muted-foreground" title="Radar hits since your last Radar visit; rate them in Main">{radar.length} Radar</span>}
              </span>
              <span className={cn("block truncate pl-3 text-xs", TONE[briefing?.status.tone ?? "muted"])}>{briefing?.status.text ?? "What matters right now? One turn across everything"}</span>
            </button>
            {loose.length > 0 && (
              <ul aria-label="Main threads" className="ml-3.5 space-y-0.5 border-l pl-1.5">
                {loose.map(talk => (
                  <li key={talk.id}>
                    <Link href={`/copilot-lab?investigation=${talk.id}`} title={talk.title} aria-current={active === talk.id ? "page" : undefined}
                      onClick={event => { if (plain(event)) { event.preventDefault(); actions.open(talk.id); } }}
                      className={cn("flex min-h-11 items-center gap-1.5 rounded-md px-2 py-1 text-xs hover:bg-secondary sm:min-h-8",
                        active === talk.id ? "bg-secondary text-foreground" : "text-muted-foreground")}>
                      <span className="min-w-0 truncate">{talk.title}</span>{talk.at && <span className="ml-auto shrink-0 tabular-nums">{shortDay(talk.at)}</span>}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
          {data && (
            <section aria-label="Tickers" className="space-y-0.5">
              <h3 className="flex items-center px-2.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Tickers<span className="ml-auto tabular-nums" aria-label={`${tickers.length} tickers`}>{tickers.length}</span>
              </h3>
              {!tickers.length && <p className="px-2.5 py-1 text-xs text-muted-foreground">
                {data.sections.positions === "unavailable" ? "Positions unavailable right now." : "Nothing open. Plan a trade to start a ticker."}
              </p>}
              <ul className="space-y-0.5">
                {[...urgent, ...shownQuiet].map(ticker => (
                  <TickerRow key={ticker.symbol} ticker={ticker} open={openSymbol === ticker.symbol} active={active} actions={actions} pick={press}
                    skipped={!!(day && ticker.lead?.close && reviewSkipped(day, ticker.symbol))} unread={ticker.rows.some(unread)} />
                ))}
              </ul>
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
