"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Menu, MessagesSquare, PanelRight, Plus, Search } from "lucide-react";
import { openNavMenu, useFoldedNav } from "@/components/Nav";
import CommandPalette, { KBD, useJumpKey, type PaletteCommand } from "@/components/copilot/CommandPalette";
import CopilotPanel, { type HomeActions, type PanelLink } from "@/components/copilot/CopilotPanel";
import DecisionBar from "@/components/copilot/DecisionBar";
import { FillsToLink, useFillLinks } from "@/components/copilot/FillLinkBar";
import RadarDecision from "@/components/copilot/RadarDecision";
import Inspector from "@/components/copilot/Inspector";
import { planContext } from "@/components/copilot/PlanATrade";
import { WEEK_REVIEW_CONTEXT } from "@/components/copilot/ReviewMyWeek";
import AlertScorecard from "@/components/copilot/AlertScorecard";
import BriefingExtras from "@/components/copilot/BriefingExtras";
import SessionTape, { DeskStatus, useDeskSession } from "@/components/copilot/SessionTape";
import ThreadRail from "@/components/copilot/ThreadRail";
import DeskThreadTop, { HorizonPick } from "@/components/copilot/ThreadHead";
import { useCopilotOn } from "@/components/copilot/useCopilotOn";
import { WHAT_MATTERS_PROMPT, copilotLabHref } from "@/lib/copilot";
import { afterClose, deskSymbolThread, nyDay, saveHorizon, toReview, type DeskCommand, type DeskHorizon, type DeskHooks, type DeskTab, type DeskThread, type DeskThreadRef } from "@/lib/desk";
import { cn } from "@/lib/utils";
import styles from "./CopilotLab.module.css";

const TABS: { id: DeskTab; label: string }[] = [{ id: "now", label: "Now" }, { id: "thread", label: "Thread" }, { id: "context", label: "Context" }];
const CONTEXT_KEY = "desk.context.v1";
/** The close pass in progress (its New York day), kept for this tab: a thread with no conversation opens by its link. */
const CLOSING_KEY = "desk.closing.v1";
/** "Plan a trade" with nothing known: the owner names the ticker. The thread list's own button makes the same link. */
const PLAN_HREF = copilotLabHref("", planContext(), { kind: "copilot", ref: null });
const PREP_PROMPT = "Prep the day: what is armed, what news or earnings touch my positions and watches, and what would change a plan before the open?";
/** A Briefing conversation keeps its question's first line as its title (CopilotPanel's ``savedFields``). */
const BRIEFING_TITLE = WHAT_MATTERS_PROMPT.split("\n")[0].slice(0, 80);
const ARM_PROMPT = "Arm today's plans: for each plan I mean to trade today, check its entry, invalidation and time stop against the pre-market, and propose any alert or time stop still missing for me to confirm.";
const CLOSE_PROMPT = "Close the day: for each position and plan today, did I follow the plan, and what is the one thing to repeat or change tomorrow?";

/** Typing somewhere: a desk key never fires there. */
function typing(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) || target.closest("[role=textbox]") !== null;
}

/**
 * The Copilot desk, the full-page lab: the thread list (``ThreadRail``), the conversation and the inspector
 * side by side, so what is live stays in view while a conversation runs. A phone shows one at a time behind three tabs.
 * While the lab is off only the conversation shows, saying so. ⌘K (Ctrl+K) or Jump to… opens the palette; while not
 * typing, J / K open the next or previous thread, N starts a plan and ] hides or shows the Context pane.
 */
export default function CopilotLab({ link = null }: { link?: PanelLink | null }) {
  const on = useCopilotOn();
  const router = useRouter();
  const navFolded = useFoldedNav();
  const session = useDeskSession(on);
  // A deep link (a ping, a Radar row, a chip) opens on its conversation, so a phone's composer is on the first screen.
  const [tab, setTab] = useState<DeskTab>(link ? "thread" : "now");
  const [command, setCommand] = useState<DeskCommand | null>(null);
  const [thread, setThread] = useState<DeskThreadRef | null>(null);
  const [rows, setRows] = useState<DeskThread[]>([]);
  const [palette, setPalette] = useState(false);
  // Hidden or shown is remembered in this browser; a blocked store keeps the pane shown.
  const [contextShown, setContextShown] = useState(true);
  useEffect(() => {
    try { setContextShown(window.localStorage.getItem(CONTEXT_KEY) !== "hidden"); } catch { /* shown */ } // eslint-disable-line react-hooks/set-state-in-effect -- the store is read after hydration
  }, []);
  const toggleContext = useCallback(() => setContextShown(shown => {
    try { window.localStorage.setItem(CONTEXT_KEY, shown ? "hidden" : "shown"); } catch { /* this visit only */ }
    return !shown;
  }), []);
  const jumpKey = useJumpKey();
  const desk = useRef<HTMLDivElement>(null);
  const [deciding, setDeciding] = useState(false);
  const sent = useRef(0);
  const actions = useMemo<HomeActions>(() => ({
    open: id => { setCommand({ kind: "open", id, n: ++sent.current }); setTab("thread"); },
    ask: text => { setCommand({ kind: "ask", text, n: ++sent.current }); setTab("thread"); },
  }), []);
  const fill = useCallback((text: string) => { setCommand({ kind: "fill", text, n: ++sent.current }); setTab("thread"); }, []);
  // The thread list's Plan a trade link: a new conversation with "Plan a trade: " in the box, unsent. Already there,
  // the same link would not remount the lab, so the page reloads it.
  const planTrade = useCallback(() => {
    if (`${window.location.pathname}${window.location.search}` === PLAN_HREF) window.location.assign(PLAN_HREF);
    else router.push(PLAN_HREF);
  }, [router]);
  const [refresh, setRefresh] = useState(0);
  // Mark plan done in the thread menu: only for a plan row (armed and not entered, or exited), never a held position's.
  const [planSymbol, setPlanSymbol] = useState<string | null>(null);
  const hooks = useMemo<DeskHooks>(() => ({ command, onThread: setThread,
    planDone: planSymbol ? { symbol: planSymbol, done: () => setRefresh(n => n + 1) } : null }), [command, planSymbol]);

  // A row opens the way the thread list opens it: an investigation in place, anything else by its link.
  const pick = useCallback((row: DeskThread) => {
    if (row.investigationId) actions.open(row.investigationId);
    else if (row.path) router.push(row.path);
  }, [actions, router]);

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
  // question; an answer or Skip opens the next, and the last one ends the pass. With none left it puts the day's
  // question in the box, unsent. Nothing goes to the model.
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
  const left = toReview(rows, nyDay()); // the list reads a review back on the refresh it triggers
  const closeDay = useCallback(() => {
    const [next] = toReview(rows, nyDay(), reviewed.current);
    setClosing(!!next);
    if (next) review(next);
    else fill(CLOSE_PROMPT);
  }, [rows, review, fill, setClosing]);
  const onReviewed = useCallback((symbol: string) => {
    reviewed.current.add(symbol);
    setRefresh(n => n + 1);
    if (!closing.current) return;
    const [next] = toReview(rows, nyDay(), reviewed.current);
    setClosing(!!next);
    if (next) review(next);
  }, [rows, review, setClosing]);

  // The thread list's phase button: before the open on a weekday, Arm today's plans (its question in the message box,
  // unsent; nothing is armed until a card is confirmed); after 16:00, Close the day.
  const phaseAction = dayPhase === "pre" ? { label: "Arm today's plans", hint: "Puts a question about today's plans in the box, unsent" }
    : dayPhase === "close" ? { label: left.length ? `Close the day · ${left.length} to review` : "Close the day",
      hint: left.length ? "Opens each thread on its close question, one at a time" : "Puts a close-of-day question in the box, unsent" } : null;
  const runPhase = useCallback(() => { if (dayPhase === "pre") fill(ARM_PROMPT); else closeDay(); }, [fill, dayPhase, closeDay]);

  const commands = useMemo<PaletteCommand[]>(() => [
    { id: "plan", name: "Plan a trade", hint: "A new plan; you name the symbol. Nothing is sent.", key: "N", run: planTrade },
    { id: "week", name: "Review my week", hint: "One turn: planned vs unplanned, follow-through, exits", run: () => actions.ask(WEEK_REVIEW_CONTEXT) },
    { id: "matters", name: "What matters right now?", hint: "One turn across your positions, watches and investigations", run: () => actions.ask(WHAT_MATTERS_PROMPT) },
    ...(dayPhase === "pre" ? [{ id: "prep", name: "Prep the day", hint: "Puts a prep question in the box, unsent", run: () => fill(PREP_PROMPT) }] : []),
    ...(dayPhase === "close" ? [{ id: "close", name: "Close the day", hint: "Each thread's close question, one at a time. Nothing is sent.", run: closeDay }] : []),
  ], [actions, dayPhase, fill, planTrade, closeDay]);

  // J / K walk the threads that open in place, in list order; pinned rows ask and other rows leave the page, so they are skipped.
  const step = useCallback((by: 1 | -1) => {
    const openable = rows.filter(r => r.investigationId);
    if (!openable.length) return;
    const at = openable.findIndex(r => r.investigationId === thread?.id);
    const next = at < 0 ? (by > 0 ? 0 : openable.length - 1) : (at + by + openable.length) % openable.length;
    actions.open(openable[next].investigationId!);
  }, [rows, thread?.id, actions]);

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
  }, [on, step, planTrade, toggleContext]);

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
  const linkRow = !thread && link?.symbol ? deskRow(link.symbol) : null;

  // Fills waiting for their plan: one bar at the top of the symbol's thread, and "N fills to link" opening each in turn.
  const fills = useFillLinks(rows, pick, () => setRefresh(n => n + 1));

  // The Context pane shows the day while no symbol is open: the Briefing, a thread about no symbol, or no thread at all
  // (a deep link naming a symbol waits for its thread instead).
  const day = thread ? !thread.symbol : !link?.symbol;
  // A deep link naming a symbol shows its Context by the symbol until a conversation is saved, then by that conversation.
  const linkSymbol = link?.symbol;
  const context = useMemo(() => thread ?? (linkSymbol ? deskSymbolThread(linkSymbol) : null), [thread, linkSymbol]);

  return (
    <div ref={desk} className={styles.desk} data-on={on} data-tab={tab} data-context={contextShown ? "shown" : "hidden"}>
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
        {on && (
          <div className={styles.barActions}>
            <button type="button" onClick={() => setPalette(true)} aria-label="Jump to a thread or command" aria-haspopup="dialog"
              className="inline-flex min-h-11 min-w-11 items-center justify-center gap-2 rounded-md border bg-card px-2.5 text-xs text-muted-foreground hover:text-foreground sm:min-h-8">
              {/* A phone keeps the bar on one line: icons only, as the button's label already says. */}
              <Search size={14} aria-hidden /><span className="hidden sm:inline">Jump to…</span><kbd className={cn(KBD, "hidden md:inline")}>{jumpKey}</kbd>
            </button>
            <button type="button" onClick={planTrade} title="A new plan; you name the symbol. Nothing is sent. ( N )"
              className="inline-flex min-h-11 min-w-11 items-center justify-center gap-1.5 rounded-md bg-foreground px-3 text-xs font-semibold text-background hover:bg-foreground/90 sm:min-h-8">
              <Plus size={14} aria-hidden /><span className="sr-only sm:not-sr-only">New plan</span>
            </button>
            <button type="button" onClick={toggleContext} aria-pressed={contextShown} aria-label="Context pane" title="Show or hide the Context pane ( ] )"
              className={cn(styles.contextToggle, "inline-flex h-8 w-8 items-center justify-center rounded-md border text-muted-foreground hover:text-foreground", !contextShown && "bg-secondary")}>
              <PanelRight size={15} aria-hidden />
            </button>
          </div>
        )}
      </header>
      {on && (
        <div role="tablist" aria-label="Desk" className={styles.tabs}>
          {TABS.map(item => (
            <button key={item.id} type="button" role="tab" aria-selected={tab === item.id} onClick={() => setTab(item.id)}>
              {item.id === "thread" ? thread?.symbol || item.label : item.label}
            </button>
          ))}
        </div>
      )}
      <div className={styles.panes}>
        {on && (
          <aside aria-label="Threads" className={styles.rail}>
            <ThreadRail actions={actions} active={thread?.id ?? null} onRows={setRows} refresh={refresh} phase={(phaseAction || fills.waiting.length > 0) && <div className="space-y-1.5">
              {phaseAction && (
                <button type="button" onClick={runPhase} title={phaseAction.hint}
                  className="min-h-11 w-full rounded-md bg-primary px-3 text-xs font-semibold text-primary-foreground hover:bg-primary/90 sm:min-h-8">
                  {phaseAction.label}
                </button>
              )}
              <FillsToLink count={fills.waiting.length} onStart={fills.start} />
            </div>} />
          </aside>
        )}
        <section aria-label="Conversation" className={styles.thread}>
          {/* The Briefing (or no thread) opens on the day at a glance. Any other thread has one main element: the header,
              then the decision when one is asked (the ladder shrinks to a line), else the full plan ladder; the conversation follows. */}
          {/* A position ping's link names only the symbol when no plan conversation exists: it opens on the decision.
              A desk Radar row names the hit too: it opens on watching, passing or planning it. */}
          {on && (!thread && link?.symbol && link.radar ? (
            <RadarDecision key={link.radar} eventId={link.radar} symbol={link.symbol} fill={fill} />
          ) : !thread && link?.symbol && !link.investigation ? (
            <div className="mb-4 space-y-3">
              {/* No conversation, so no thread header: the symbol's horizon sits on its own line. */}
              {linkRow?.horizon && (
                <p className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span className="font-medium text-foreground">{link.symbol}</span>
                  <HorizonPick horizon={linkRow.horizon} onChange={horizon => changeHorizon(link.symbol, horizon)} />
                </p>
              )}
              {fills.bar(link.symbol)}
              <DecisionBar key={link.symbol} symbol={link.symbol} {...barFor(link.symbol)} onActive={setDeciding} fill={fill} onReviewed={onReviewed} />
            </div>
          ) : !thread || (!thread.symbol && thread.title === BRIEFING_TITLE) ? <>{fills.waiting.length > 0 && <div className="mb-4"><FillsToLink count={fills.waiting.length} onStart={fills.start} /></div>}<SessionTape data={session.data} error={session.error} rows={rows} /><BriefingExtras onReviewWeek={() => actions.ask(WEEK_REVIEW_CONTEXT)} /><AlertScorecard /></> : (
            <DeskThreadTop key={fills.linked} thread={thread} compact={deciding} horizon={threadRow?.horizon ?? null} stage={threadRow?.close?.kind === "exit" ? "Exited" : null} onHorizon={horizon => changeHorizon(thread.symbol, horizon)} hero={
              <>{fills.bar(thread.symbol)}<DecisionBar key={thread.symbol ?? ""} symbol={thread.symbol ?? null} {...barFor(thread.symbol)} onActive={setDeciding} fill={fill} onReviewed={onReviewed} /></>} />
          ))}
          <CopilotPanel variant="page" link={link} desk={hooks} />
        </section>
        {on && <aside aria-label="Context" className={styles.inspector}><Inspector thread={context} day={day} /></aside>}
      </div>
      {on && <CommandPalette open={palette} onClose={() => setPalette(false)} threads={rows.filter(r => r.group !== "pinned")} commands={commands} onThread={pick} />}
    </div>
  );
}
