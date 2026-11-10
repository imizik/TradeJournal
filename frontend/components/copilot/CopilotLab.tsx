"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ChartCandlestick, Menu, MessagesSquare, PanelLeft, PanelRight, Plus, Search } from "lucide-react";
import { openNavMenu, useFoldedNav } from "@/components/Nav";
import ClosePass, { closeSteps } from "@/components/copilot/ClosePass";
import CommandPalette, { KBD, useJumpKey, type PaletteCommand } from "@/components/copilot/CommandPalette";
import CopilotPanel, { rememberedThread, type HomeActions, type PanelLink } from "@/components/copilot/CopilotPanel";
import DecisionBar from "@/components/copilot/DecisionBar";
import FillLinkBar, { FillsToLink, useFillLinks } from "@/components/copilot/FillLinkBar";
import RadarDecision from "@/components/copilot/RadarDecision";
import Inspector from "@/components/copilot/Inspector";
import { ThreadAlertAnswers, ThreadHitRating } from "@/components/copilot/ProofAnswers";
import PingsRecap from "@/components/copilot/PingsRecap";
import { planContext } from "@/components/copilot/PlanATrade";
import { WEEK_REVIEW_CONTEXT } from "@/components/copilot/ReviewMyWeek";
import ArmChecklist from "@/components/copilot/ArmChecklist";
import BriefingExtras from "@/components/copilot/BriefingExtras";
import SessionTape, { DeskStatus, NowPositions, NowWaiting, useDeskSession } from "@/components/copilot/SessionTape";
import MorningBrief from "@/components/copilot/MorningBrief";
import PreviousDays from "@/components/copilot/PreviousDays";
import ThreadRail from "@/components/copilot/ThreadRail";
import { ScalpShortlistNudge } from "@/components/ScalpShortlistPanel";
import DeskThreadTop, { HorizonPick } from "@/components/copilot/ThreadHead";
import { useCopilotOn } from "@/components/copilot/useCopilotOn";
import { WHAT_MATTERS_PROMPT, copilotLabHref, mainChatLabel, type InvestigationSummary } from "@/lib/copilot";
import { afterClose, answerSymbol, deskSymbolThread, needingCount, nyDay, saveFollow, saveHorizon, threadInUrl, toReview, type DeskCommand, type DeskHorizon, type DeskHooks, type DeskTab, type DeskThread, type DeskThreadRef } from "@/lib/desk";
import { cn } from "@/lib/utils";
import styles from "./CopilotLab.module.css";

const CONTEXT_KEY = "desk.context.v1";
const THREADS_KEY = "desk.threads.v1";
/** The close pass in progress (its New York day), kept for this tab: a thread with no conversation opens by its link. */
const CLOSING_KEY = "desk.closing.v1";
/** "Plan a trade" with nothing known: the owner names the ticker. The thread list's own button makes the same link. */
const PLAN_HREF = copilotLabHref("", planContext(), { kind: "copilot", ref: null });
const PREP_PROMPT = "Prep the day: what is armed, what news or earnings touch my positions and watches, and what would change a plan before the open?";
const ARM_PROMPT = "Arm today's plans: for each plan I mean to trade today, check its entry, invalidation and time stop against the pre-market, and propose any alert or time stop still missing for me to confirm.";
const CLOSE_PROMPT = "Close the day: for each position and plan today, did I follow the plan, and what is the one thing to repeat or change tomorrow?";

const shortDay = (iso: string) => new Date(iso).toLocaleDateString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric" });

/** You are here: "Now › a conversation about no ticker", or "NBIS › its conversation · Oct 29". Now goes back to the
 * desk's front door. */
function Breadcrumb({ thread, link, saved, onMain }: { thread: DeskThreadRef | null; link: PanelLink | null; saved: InvestigationSummary[]; onMain(): void }) {
  const symbol = thread ? thread.symbol : link?.symbol || null;
  const at = thread && saved.find(t => t.id === thread.id)?.updated_at;
  const leaf = thread ? thread.title : symbol ? (link?.radar ? "Radar hit" : "Decision") : null;
  return (
    <nav aria-label="You are here" data-testid="desk-breadcrumb" className="z-10 mb-3 flex min-w-0 items-baseline gap-1.5 bg-background py-1 text-xs text-muted-foreground lg:sticky lg:top-0 lg:shadow-[0_-24px_0_0_hsl(var(--background))]">
      {symbol ? <span className="shrink-0 font-semibold text-foreground">{symbol}</span> : (
        <button type="button" onClick={onMain} className="shrink-0 font-semibold hover:text-foreground hover:underline">Now</button>
      )}
      {leaf && <><span aria-hidden>›</span><span className="min-w-0 truncate text-foreground" title={leaf}>{leaf}</span></>}
      {at && <span className="shrink-0 tabular-nums">· {shortDay(at)}</span>}
    </nav>
  );
}

/** Typing somewhere: a desk key never fires there. */
function typing(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) || target.closest("[role=textbox]") !== null;
}

/**
 * The Copilot desk. It opens on Now (``daily``): the day line, open positions, what waits on the owner, today's pings
 * and Radar, the morning brief or Close the day, then today's conversation (Main chat) and its message box. Threads and
 * Context are side panes; a phone shows one pane at a time behind tabs, Now first.
 * While the lab is off only the conversation shows, saying so. ⌘K (Ctrl+K) or Jump to… opens the palette; while not
 * typing, J / K open the next or previous thread, N starts a plan, [ toggles Threads and ] toggles Context.
 */
export default function CopilotLab({ link = null, close = false, daily = false }: { link?: PanelLink | null; close?: boolean; daily?: boolean }) {
  const on = useCopilotOn();
  const router = useRouter();
  const navFolded = useFoldedNav();
  const session = useDeskSession(on);
  // Now, a deep link (a ping, a Radar row, a chip) and a saved thread all open on the conversation pane, so a phone's
  // first screen is what the address names.
  const [tab, setTab] = useState<DeskTab>("thread");
  const [command, setCommand] = useState<DeskCommand | null>(null);
  const [thread, setThread] = useState<DeskThreadRef | null>(null);
  // Now: today's Main chat (or the desk's bare address while it opens) with the day above it. An earlier day's Main chat
  // is that day's conversation only.
  const today = session.data?.day ?? nyDay();
  const onNow = thread ? !!thread.mainDay && thread.mainDay === today : daily;
  const [rows, setRows] = useState<DeskThread[]>([]);
  const [rowsRead, setRowsRead] = useState(false);
  const readRows = useCallback((next: DeskThread[]) => { setRows(next); setRowsRead(true); }, []);
  const needYouCount = needingCount(rows, nyDay());
  const [saved, setSaved] = useState<InvestigationSummary[]>([]);
  const [palette, setPalette] = useState(false);
  // Side panes open on request; explicit choices are remembered in this browser.
  const [contextShown, setContextShown] = useState(false);
  const [threadsShown, setThreadsShown] = useState(false);
  useEffect(() => {
    try { setContextShown(window.localStorage.getItem(CONTEXT_KEY) === "shown"); } catch { /* hidden */ } // eslint-disable-line react-hooks/set-state-in-effect -- the store is read after hydration
    try { setThreadsShown(window.localStorage.getItem(THREADS_KEY) === "shown"); } catch { /* hidden */ } // eslint-disable-line react-hooks/set-state-in-effect -- the store is read after hydration
  }, []);
  const toggleContext = useCallback(() => setContextShown(shown => {
    try { window.localStorage.setItem(CONTEXT_KEY, shown ? "hidden" : "shown"); } catch { /* this visit only */ }
    return !shown;
  }), []);
  const toggleThreads = useCallback(() => setThreadsShown(shown => {
    try { window.localStorage.setItem(THREADS_KEY, shown ? "hidden" : "shown"); } catch { /* this visit only */ }
    return !shown;
  }), []);
  const jumpKey = useJumpKey();
  const desk = useRef<HTMLDivElement>(null);
  const [deciding, setDeciding] = useState(false);
  const sent = useRef(0);
  const actions = useMemo<HomeActions>(() => ({
    open: id => { setCommand({ kind: "open", id, n: ++sent.current }); setTab("thread"); },
    ask: text => { setCommand({ kind: "ask", text, n: ++sent.current }); setTab("thread"); },
    // Back to Now from any thread or deep link, without carrying its conversation into the new view.
    home: () => {
      setTab("thread");
      window.location.assign("/copilot-lab");
    },
  }), []);
  const fill = useCallback((text: string) => { setCommand({ kind: "fill", text, n: ++sent.current }); setTab("thread"); }, []);
  // Plan a trade (the desk bar's New plan, N and ⌘K): a new conversation with "Plan a trade: " in the box, unsent. Already there,
  // the same link would not remount the lab, so the page reloads it.
  const planTrade = useCallback(() => {
    if (`${window.location.pathname}${window.location.search}` === PLAN_HREF) window.location.assign(PLAN_HREF);
    else router.push(PLAN_HREF);
  }, [router]);
  const [refresh, setRefresh] = useState(0);
  // Mark plan done in the thread menu: only for a plan row (armed and not entered, or exited), never a held position's.
  const [planSymbol, setPlanSymbol] = useState<string | null>(null);
  // A decision or an alert still asking today: a conversation opens on it, at the top of the thread.
  const asking = deciding || !!session.data?.to_answer?.alerts?.rows.some(a => a.today && !a.feedback && a.symbol === thread?.symbol);
  const [turnText, setTurnText] = useState<string | null>(null);
  // Now opens at its top, above the day's conversation, as a thread asking something does.
  const hooks = useMemo<DeskHooks>(() => ({ command, onThread: setThread, holdTop: asking || onNow, onAnswer: setTurnText,
    planDone: planSymbol ? { symbol: planSymbol, done: () => setRefresh(n => n + 1) } : null }), [command, planSymbol, asking, onNow]);

  // The open thread is in the address, so Back and a reload come back to it: opening another adds a step, and the thread
  // the desk reopened by itself takes the bare address's place. Only the address changes, so the lab stays mounted.
  const addressed = useRef<string | null>(null);
  const reopened = useRef<string | null>(null);
  useEffect(() => {
    reopened.current = rememberedThread();
    if (threadInUrl()) setTab("thread"); // eslint-disable-line react-hooks/set-state-in-effect -- the address is read after hydration
  }, []);
  const threadId = thread?.id ?? null;
  const threadMain = !!thread?.mainDay;
  useEffect(() => {
    if (threadId === addressed.current) return;
    // Only the Main chat Now opened (or the thread the desk reopened) takes the bare address's place; a thread the owner
    // opens from Now adds a step, so Back returns to Now even before (or without) today's Main chat.
    const quiet = !addressed.current && ((daily && threadMain) || threadId === reopened.current);
    addressed.current = threadId;
    reopened.current = null;
    if (threadId === threadInUrl() || (!threadId && !window.location.search)) return;
    window.history[quiet ? "replaceState" : "pushState"](null, "", threadId ? `/copilot-lab?thread=${threadId}` : "/copilot-lab?view=new");
  }, [threadId, threadMain, daily]);
  useEffect(() => {
    const back = () => {
      const id = threadInUrl();
      if (id) actions.open(id);
      else window.location.reload(); // a deep link's address: its question comes back with it
    };
    window.addEventListener("popstate", back);
    return () => window.removeEventListener("popstate", back);
  }, [actions]);

  // A row opens the way the thread list opens it: an investigation in place, anything else by its link.
  const pick = useCallback((row: DeskThread) => {
    if (row.investigationId) actions.open(row.investigationId);
    else if (row.path) router.push(row.path);
  }, [actions, router]);

  // A row on Now opens the way the thread list's ticker does: its own conversation, else the symbol's newest open one,
  // else its link; a position whose link leaves the desk (its trade page) opens the symbol's desk view instead.
  const openRow = useCallback((row: DeskThread) => {
    const talk = saved.filter(t => t.symbol && t.symbol === row.symbol && t.status !== "closed").sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0];
    if (row.investigationId) actions.open(row.investigationId);
    else if (talk) actions.open(talk.id);
    else if (row.path?.startsWith("/copilot-lab") || !row.symbol) pick(row);
    else router.push(`/copilot-lab?${new URLSearchParams({ symbol: row.symbol })}`);
  }, [actions, pick, router, saved]);

  // Fills waiting for their plan: one bar at the top of the symbol's thread, and "N fills to link" opening each in turn.
  const fills = useFillLinks(rows, pick, () => setRefresh(n => n + 1));

  // The day's phase command: Prep the day before the open on a weekday, Close the day after 16:00 (New York clock).
  const [dayPhase, setDayPhase] = useState<"pre" | "close" | null>(null);
  useEffect(() => {
    const read = () => {
      const now = new Date();
      const parts = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
        .formatToParts(now).map(p => [p.type, p.value]));
      const minute = Number(parts.hour) * 60 + Number(parts.minute);
      const weekday = !["Sat", "Sun"].includes(parts.weekday);
      setDayPhase(afterClose(now.toISOString()) ? "close" : weekday && minute >= 4 * 60 && minute < 9 * 60 + 30 ? "pre" : null);
    };
    read();
    const timer = setInterval(read, 60_000);
    return () => clearInterval(timer);
  }, []);

  // Close the day: a pass through each thread still asking its close question (``toReview``, list order). Each opens on its
  // question; an answer or Skip opens the next. Then, in the conversation pane, the fills waiting to link
  // (``closeSteps``), one at a time; the last one ends the pass. With none left it puts the day's question in the box,
  // unsent. Alert and Radar ratings are never asked here. Nothing goes to the model.
  const reviewed = useRef(new Set<string>()); // answered or skipped this visit, before the list reads it back
  const closing = useRef(false);
  useEffect(() => {
    try { closing.current = window.sessionStorage.getItem(CLOSING_KEY) === nyDay(); } catch { /* no pass to resume */ }
  }, []);
  const setClosing = useCallback((on: boolean) => {
    closing.current = on;
    try { if (on) window.sessionStorage.setItem(CLOSING_KEY, nyDay()); else window.sessionStorage.removeItem(CLOSING_KEY); } catch { /* this page only */ }
  }, []);
  const review = useCallback((row: DeskThread) => {
    if (row.investigationId) actions.open(row.investigationId);
    else router.push(`/copilot-lab?${new URLSearchParams({ symbol: row.symbol! })}`); // opens on the symbol's question
  }, [actions, router]);
  const [passed, setPassed] = useState<ReadonlySet<string>>(() => new Set()); // answered or skipped this visit
  const steps = dayPhase === "close" ? closeSteps(fills.waiting, passed) : [];
  const [answering, setAnswering] = useState(false);
  const pass = useCallback((id: string) => setPassed(prev => new Set(prev).add(id)), []);
  const left = toReview(rows, nyDay()).length + steps.length; // the list reads a review back on the refresh it triggers
  // "N of M done": every followed thread asked today (one per symbol) and, after 16:00, the fills to link. A skip is not done.
  const asked = new Map(rows.filter(r => r.close && r.symbol && !r.hidden).map(r => [r.symbol, !!r.close!.reviewed]));
  const fillsHere = dayPhase === "close" ? fills.answeredHere : 0;
  const tally = {
    done: [...asked.values()].filter(Boolean).length + fillsHere,
    total: asked.size + (dayPhase === "close" ? fills.waiting.length : 0) + fillsHere,
  };
  const closeDay = useCallback(() => {
    const [next] = toReview(rows, nyDay(), reviewed.current);
    setClosing(!!next);
    if (next) review(next);
    else if (steps.length) { setAnswering(true); setTab("thread"); }
    else fill(CLOSE_PROMPT);
  }, [rows, review, fill, setClosing, steps.length]);
  // ``?close=1`` (the evening review ping) starts the pass once the list and the session have read, after the close: the
  // first unreviewed thread by a page load of its link (the pass carries on in this tab), else the fills to link here. With nothing left, or read before the close (a tab kept open stays as it is), the desk just opens.
  const closeLink = useRef(close);
  const sessionRead = !!(session.data || session.error);
  useEffect(() => {
    if (!closeLink.current || !rows.length || !sessionRead) return;
    closeLink.current = false;
    if (dayPhase !== "close") return;
    const [next] = toReview(rows, nyDay());
    if (next) {
      setClosing(true);
      window.location.replace(next.investigationId ? `/copilot-lab?investigation=${next.investigationId}`
        : `/copilot-lab?${new URLSearchParams({ symbol: next.symbol! })}`);
    } else if (steps.length) { setAnswering(true); setTab("thread"); } // eslint-disable-line react-hooks/set-state-in-effect -- the link starts the pass once
  }, [rows, sessionRead, dayPhase, setClosing, steps.length]);
  const onReviewed = useCallback((symbol: string) => {
    reviewed.current.add(symbol);
    setRefresh(n => n + 1);
    if (!closing.current) return;
    const [next] = toReview(rows, nyDay(), reviewed.current);
    setClosing(!!next);
    if (next) review(next);
    else if (steps.length) setAnswering(true);
  }, [rows, review, setClosing, steps.length]);
  const closeStep = answering ? steps[0] : undefined;
  useEffect(() => { if (answering && !steps.length) setAnswering(false); }, [answering, steps.length]); // eslint-disable-line react-hooks/set-state-in-effect -- the last answer ends the pass

  // The desk bar's phase action: before the open on a weekday, Arm today's plans (a checklist of the armed plans in the
  // conversation pane; nothing is armed, sized or sent from it); after 16:00, Close the day.
  const [arming, setArming] = useState(false);
  // Opening another thread leaves the checklist or the pass; Main chat arriving under Now (a first open, from no thread)
  // does not, so ?close=1's pass or an early Arm survives a Main chat that loads after it started.
  const lastThread = useRef<string | null>(null);
  useEffect(() => {
    const was = lastThread.current;
    lastThread.current = thread?.id ?? null;
    if (was !== null) { setArming(false); setAnswering(false); }
  }, [thread?.id]);
  const phaseAction = dayPhase === "pre" ? { label: "Arm today's plans", hint: "Each armed plan: still good, change or drop. Nothing is sent." }
    : dayPhase === "close" ? { label: left ? `Close the day · ${left} to review` : "Close the day",
      hint: left ? "Each thread's close question, then the fills to link, one at a time"
        : "Puts a close-of-day question in the box, unsent" } : null;
  const runPhase = useCallback(() => {
    if (dayPhase !== "pre") closeDay();
    else { setArming(true); setTab("thread"); }
  }, [dayPhase, closeDay]);

  const commands = useMemo<PaletteCommand[]>(() => [
    { id: "plan", name: "Plan a trade", hint: "A new plan; you name the symbol. Nothing is sent.", key: "N", run: planTrade },
    { id: "week", name: "Review my week", hint: "One turn: planned vs unplanned, follow-through, exits", run: () => actions.ask(WEEK_REVIEW_CONTEXT) },
    { id: "matters", name: "What matters right now?", hint: "One turn across your positions, watches and investigations", run: () => actions.ask(WHAT_MATTERS_PROMPT) },
    ...(dayPhase === "pre" ? [{ id: "prep", name: "Prep the day", hint: "Puts a prep question in the box, unsent", run: () => fill(PREP_PROMPT) }] : []),
    ...(dayPhase === "close" ? [{ id: "close", name: "Close the day", hint: "Each close question and fill to link, one at a time. Nothing is sent.", run: closeDay }] : []),
  ], [actions, dayPhase, fill, planTrade, closeDay]);

  // J / K walk the conversations the thread list shows, subthreads included, in its order.
  const [walk, setWalk] = useState<string[]>([]);
  const step = useCallback((by: 1 | -1) => {
    if (!walk.length) return;
    const at = walk.indexOf(thread?.id ?? "");
    const next = at < 0 ? (by > 0 ? 0 : walk.length - 1) : (at + by + walk.length) % walk.length;
    actions.open(walk[next]);
  }, [walk, thread?.id, actions]);

  useEffect(() => {
    if (!on) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.isComposing || typing(event.target)) return;
      // The open dialog itself, not state: Escape closes it before React re-renders this listener.
      if (desk.current?.querySelector("dialog[open]")) return;
      const key = event.key.toLowerCase();
      // ⌘K or Ctrl+K on any platform: outside a field neither does anything in the browser.
      if (key === "k" && (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey) {
        event.preventDefault();
        setPalette(true);
        return;
      }
      if (event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
      if (key === "j" || key === "k") { event.preventDefault(); step(key === "j" ? 1 : -1); }
      else if (event.key === "[") { event.preventDefault(); toggleThreads(); }
      else if (key === "n" && !event.repeat) {
        // A new plan leaves this conversation: never over words not yet sent.
        const box = desk.current?.querySelector<HTMLTextAreaElement>("textarea[aria-label='Message']");
        if (box?.value.trim()) return;
        event.preventDefault();
        planTrade();
      }
      // The pane hides only where the panes sit side by side; a phone keeps its tabs.
      else if (event.key === "]" && (desk.current?.clientWidth ?? 0) >= 760) { event.preventDefault(); toggleContext(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [on, step, planTrade, toggleContext, toggleThreads]);

  // The open symbol's row in the thread list (a position or a plan): its close question and horizon, as the list shows them.
  const deskRow = useCallback((symbol: string | null | undefined) =>
    symbol ? rows.find(r => r.symbol === symbol && r.close) ?? rows.find(r => r.symbol === symbol && r.horizon) ?? null : null, [rows]);
  const barFor = (symbol: string | null) => {
    const row = deskRow(symbol);
    return { close: row?.close ?? null, plan: row ? () => pick(row) : undefined };
  };
  const threadRow = deskRow(thread?.symbol);
  const markable = threadRow && threadRow.key === `plan:${thread?.id}` && threadRow.value?.text !== "In position" ? threadRow.symbol : null;
  useEffect(() => { setPlanSymbol(markable); }, [markable]); // eslint-disable-line react-hooks/set-state-in-effect -- from the list's read
  const changeHorizon = useCallback(async (symbol: string | null | undefined, horizon: DeskHorizon) => {
    if (!symbol) return;
    await saveHorizon(symbol, horizon);
    setRefresh(n => n + 1);
  }, []);
  // Following a ticker: shown at once (the thread list applies ``follow`` ahead of its next read), saved as a day-journal
  // entry so every device agrees; a failed save puts it back and the caller says so.
  const [follow, setFollow] = useState<Readonly<Record<string, boolean>>>({});
  const changeFollow = useCallback(async (symbol: string, following: boolean) => {
    setFollow(prev => ({ ...prev, [symbol]: following }));
    try {
      await saveFollow(symbol, following);
    } catch (failure) {
      setFollow(prev => ({ ...prev, [symbol]: !following }));
      throw failure;
    }
    setRefresh(n => n + 1);
  }, []);
  const followRead = useCallback((symbol: string) => setFollow(prev => {
    const next = { ...prev };
    delete next[symbol];
    return next;
  }), []);
  // A ticker's follow switch for its header: null when the desk has no row about it.
  const followingOf = (symbol: string | null | undefined) =>
    symbol && rows.some(r => r.symbol === symbol) ? !rows.some(r => r.symbol === symbol && r.hidden) : null;
  const linkRow = !thread && link?.symbol ? deskRow(link.symbol) : null;
  const alertRows = session.data?.to_answer?.alerts?.rows; // a position's thread offers its alerts sent today a rating

  // The Context pane shows the day while no symbol is open: the Briefing, a thread about no symbol, or no thread at all
  // (a deep link naming a symbol waits for its thread instead).
  const day = thread ? !thread.symbol : !link?.symbol;
  const showNow = on && onNow && !arming && !closeStep;
  // A deep link naming a symbol shows its Context by the symbol until a conversation is saved, then by that conversation.
  const linkSymbol = link?.symbol;
  const context = useMemo(() => thread ?? (linkSymbol ? deskSymbolThread(linkSymbol) : null), [thread, linkSymbol]);
  // A conversation about no ticker (Main chat) charts the ticker its latest turn is about, when it names one.
  const known = useMemo(() => rows.flatMap(r => r.symbol ? [r.symbol] : []), [rows]);
  const focus = day ? answerSymbol(turnText, known) : null;

  return (
    <div ref={desk} className={styles.desk} data-on={on} data-tab={tab} data-context={contextShown ? "shown" : "hidden"} data-threads={threadsShown ? "shown" : "hidden"}>
      <header className={styles.bar}>
        {/* A wide screen folds the app's navigation into this button, so the desk has the full width; a phone keeps its tabs. */}
        {navFolded && (
          <button type="button" onClick={openNavMenu} aria-label="Open menu" title="All pages, sync and the plan streak"
            className="-ml-1.5 hidden h-8 items-center gap-1.5 rounded-md px-2 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground md:inline-flex">
            <Menu size={15} aria-hidden />Menu
          </button>
        )}
        <h1 className={styles.title}><MessagesSquare size={17} aria-hidden />Desk</h1>
        {on && <DeskStatus data={session.data} />}
        {on && <ScalpShortlistNudge />}
        {on && (
          <div className={styles.barActions}>
            {/* The desk's front door; filled in while it is on screen. A phone's first tab is Now, so the bar hides it there. */}
            <Link href="/copilot-lab" aria-current={onNow ? "page" : undefined} title="The day, your positions, what waits on you and today's conversation"
              className={cn(styles.daily, "inline-flex h-8 items-center whitespace-nowrap rounded-md border px-2.5 text-xs", onNow ? "bg-secondary font-medium text-foreground" : "text-muted-foreground hover:text-foreground")}>Now</Link>
            <button type="button" onClick={toggleThreads} aria-pressed={threadsShown}
              aria-label={`Threads${!phaseAction && needYouCount > 0 ? `, ${needYouCount} need you` : ""}`} title="Show or hide the thread list ( [ )"
              className={cn(styles.paneToggle, "inline-flex h-8 items-center justify-center gap-1.5 rounded-md border px-2 text-xs text-muted-foreground hover:text-foreground", threadsShown && "bg-secondary")}>
              <PanelLeft size={15} aria-hidden />
              {!phaseAction && needYouCount > 0 && <span className="tabular-nums text-primary">{needYouCount}</span>}
            </button>
            <button type="button" onClick={() => setPalette(true)} aria-label="Jump to a thread or command" aria-haspopup="dialog"
              className="inline-flex min-h-11 min-w-11 items-center justify-center gap-2 rounded-md border bg-card px-2.5 text-xs text-muted-foreground hover:text-foreground sm:min-h-8">
              {/* A phone keeps the bar on one line: icons only, as the button's label already says. */}
              <Search size={14} aria-hidden /><span className="hidden sm:inline">Jump to…</span><kbd className={cn(KBD, "hidden md:inline")}>{jumpKey}</kbd>
            </button>
            <button type="button" onClick={planTrade} title="A new plan; you name the symbol. Nothing is sent. ( N )"
              className="inline-flex min-h-11 min-w-11 items-center justify-center gap-1.5 rounded-md border px-2.5 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8">
              <Plus size={14} aria-hidden /><span className="sr-only sm:not-sr-only">New plan</span>
            </button>
            {/* Now carries the phase action in its own block while it is on screen; anywhere else it sits here, at every width. */}
            {phaseAction && !(showNow && tab === "thread") && <button type="button" onClick={runPhase} title={phaseAction.hint}
              className="inline-flex min-h-11 items-center rounded-md border px-2.5 text-xs font-medium text-foreground hover:bg-secondary md:min-h-8">{phaseAction.label}</button>}
            <button type="button" onClick={toggleContext} aria-pressed={contextShown} aria-label="Context pane" title="Show or hide market context ( ] )"
              className={cn(styles.contextToggle, "inline-flex h-8 items-center justify-center gap-1.5 rounded-md border px-2 text-xs text-muted-foreground hover:text-foreground", contextShown && "bg-secondary")}>
              <PanelRight size={15} aria-hidden />
            </button>
          </div>
        )}
      </header>
      {on && (
        <div role="tablist" aria-label="Desk" className={styles.tabs}>
          {/* Now first; the open thread gets its own tab only while it is not Now. Now from a thread goes back to the front door. */}
          <button type="button" role="tab" aria-selected={tab === "thread" && onNow} onClick={() => (onNow ? setTab("thread") : actions.home())}>Now</button>
          <button type="button" role="tab" aria-selected={tab === "threads"} onClick={() => setTab("threads")}>Threads</button>
          {!onNow && (
            <button type="button" role="tab" aria-selected={tab === "thread"} onClick={() => setTab("thread")}>
              {thread?.symbol || link?.symbol || (thread?.mainDay ? "Main chat" : "Thread")}
            </button>
          )}
          <button type="button" role="tab" aria-selected={tab === "context"} onClick={() => setTab("context")}>Context</button>
        </div>
      )}
      <div className={styles.panes}>
        {on && (
          <aside aria-label="Threads" className={styles.rail}>
            <ThreadRail actions={actions} active={thread?.id ?? null} activeSymbol={thread ? thread.symbol : link?.symbol ?? null} main={onNow}
              pick={pick} onRows={readRows} onWalk={setWalk} onSaved={setSaved} refresh={refresh} follow={follow} onFollow={changeFollow} onFollowRead={followRead}
              phase={fills.waiting.length > 0 && <FillsToLink count={fills.waiting.length} onStart={fills.start} />} />
          </aside>
        )}
        <section aria-label="Conversation" className={styles.thread}>
          {/* One reading column, centred however wide the pane is: lines stay short enough to read at a glance. */}
          <div className="mx-auto w-full max-w-[46rem]">
          {/* Now: the day line, followed open positions, what waits on the owner, how the pings did, today's Radar, the
              day's phase action and the morning brief, then today's conversation under its heading. Every count opens
              what it counts; nothing asks for a rating. */}
          {showNow && (
            <div data-testid="now">
              <SessionTape data={session.data} error={session.error} tally={tally} />
              <NowPositions rows={rows} stops={(session.data?.time_stops ?? []).filter(stop => stop.at > (session.data?.now ?? 0))} open={openRow} read={rowsRead}
                onFollow={changeFollow} />
              <NowWaiting rows={rows} day={nyDay()} open={openRow} quiet={!fills.waiting.length}>
                {fills.waiting.length > 0 && <div className="basis-full"><FillsToLink count={fills.waiting.length} onStart={fills.start} /></div>}
              </NowWaiting>
              <PingsRecap />
              <BriefingExtras onReviewWeek={() => actions.ask(WEEK_REVIEW_CONTEXT)} onWhatMatters={() => actions.ask(WHAT_MATTERS_PROMPT)}
                session={session.data} radar={rows.filter(r => r.key.startsWith("radar:"))} />
              {phaseAction && (
                <div data-testid="now-phase" className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-card px-4 py-3">
                  <span className="text-xs text-muted-foreground">{phaseAction.hint}</span>
                  <button type="button" onClick={runPhase} className="inline-flex min-h-11 items-center rounded-md border border-primary/50 px-3 text-xs font-semibold text-primary hover:bg-primary/10 sm:min-h-8">{phaseAction.label}</button>
                </div>
              )}
              <MorningBrief prep={session.data?.prep} fill={fill} />
            </div>
          )}
          {on && thread?.mainDay && (
            <div className="mb-4 flex flex-wrap items-start justify-between gap-2">
              <h2 className="text-lg font-semibold">{mainChatLabel({ title: thread.title, main_day: thread.mainDay })}</h2><PreviousDays active={thread.id} open={actions.open} />
            </div>
          )}
          {on && !thread?.mainDay && (thread || link) && <Breadcrumb thread={thread} link={link} saved={saved} onMain={actions.home} />}
          {/* Any other thread has one main element: the header, then the decision when one is asked (the ladder shrinks to a
              line), else the full plan ladder; the conversation follows. */}
          {/* A position ping's link names only the symbol when no plan conversation exists: it opens on the decision.
              A desk Radar row names the hit too: it opens on watching, passing or planning it. */}
          {on && arming && (
            <ArmChecklist onClose={() => setArming(false)} onDropped={() => setRefresh(n => n + 1)}
              ask={() => { setArming(false); fill(ARM_PROMPT); }}
              change={(plan, text) => { setArming(false); setCommand({ kind: "open", id: plan.investigationId!, text, n: ++sent.current }); setTab("thread"); }} />
          )}
          {on && !arming && closeStep && (
            <ClosePass key={closeStep.id} done={tally.done} total={tally.total}
              onSkip={() => pass(closeStep.id)} onEnd={() => { setAnswering(false); setClosing(false); }} body={
                <FillLinkBar tradeId={closeStep.id} titles={fills.titles} onDone={(id, how) => { fills.answer(id, how); pass(id); }} />} />
          )}
          {on && !arming && !closeStep && (!thread && link?.symbol && link.radar ? (
            <><RadarDecision key={link.radar} eventId={link.radar} symbol={link.symbol} fill={fill} /><ThreadHitRating key={`rate-${link.radar}`} eventId={link.radar} /></>
          ) : !thread && link?.symbol && !link.investigation ? (
            <div className="mb-4 space-y-3">
              {/* An open position, planned or not, still gets its header and since-entry lines. */}
              {/* Held: the header row carries the symbol and its horizon. Not held: they sit on their own line. */}
              <DeskThreadTop thread={deskSymbolThread(link.symbol)} heldOnly compact={deciding} horizon={linkRow?.horizon ?? null}
                onHorizon={horizon => changeHorizon(link.symbol, horizon)} following={followingOf(link.symbol)}
                onFollow={following => changeFollow(link.symbol!, following)} fallback={
                <p className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Link href={`/charts?symbol=${encodeURIComponent(link.symbol)}`} aria-label={`Open ${link.symbol} chart`} title={`Open ${link.symbol} in Charts`}
                    className="inline-flex items-center gap-1 font-medium text-foreground underline-offset-2 hover:text-primary hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary">{link.symbol}<ChartCandlestick size={13} aria-hidden className="text-muted-foreground" /></Link>
                  {linkRow?.horizon && <HorizonPick horizon={linkRow.horizon} onChange={horizon => changeHorizon(link.symbol, horizon)} />}
                </p>} />
              {fills.bar(link.symbol)}
              <DecisionBar key={link.symbol} symbol={link.symbol} {...barFor(link.symbol)} onActive={setDeciding} fill={fill} onReviewed={onReviewed} />
              <ThreadAlertAnswers symbol={link.symbol} rows={alertRows} />
            </div>
          ) : thread && !thread.mainDay ? (
            <DeskThreadTop key={fills.linked} thread={thread} compact={deciding} horizon={threadRow?.horizon ?? null} stage={threadRow?.close?.kind === "exit" ? "Exited" : null} adopted={threadRow?.adopted ?? false} onHorizon={horizon => changeHorizon(thread.symbol, horizon)}
              following={followingOf(thread.symbol)} onFollow={following => changeFollow(thread.symbol!, following)} hero={
              <>{fills.bar(thread.symbol)}<DecisionBar key={thread.symbol ?? ""} symbol={thread.symbol ?? null} {...barFor(thread.symbol)} onActive={setDeciding} fill={fill} onReviewed={onReviewed} />
                <ThreadAlertAnswers symbol={thread.symbol ?? null} rows={alertRows} /></>} />
          ) : null)}
          <CopilotPanel variant="page" link={link} desk={hooks} daily={daily} />
          </div>
        </section>
        {on && <aside aria-label="Context" className={styles.inspector}><Inspector thread={context} day={day} focus={focus} /></aside>}
      </div>
      {on && <CommandPalette open={palette} onClose={() => setPalette(false)} threads={rows.filter(r => r.group !== "pinned")} commands={commands} onThread={pick} onConversation={actions.open} />}
    </div>
  );
}
