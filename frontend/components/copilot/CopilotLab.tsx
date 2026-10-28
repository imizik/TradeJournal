"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { PanelRight, Search } from "lucide-react";
import CommandPalette, { KBD, useJumpKey, type PaletteCommand } from "@/components/copilot/CommandPalette";
import CopilotPanel, { type HomeActions, type PanelLink } from "@/components/copilot/CopilotPanel";
import DecisionBar from "@/components/copilot/DecisionBar";
import Inspector from "@/components/copilot/Inspector";
import { planContext } from "@/components/copilot/PlanATrade";
import { WEEK_REVIEW_CONTEXT } from "@/components/copilot/ReviewMyWeek";
import SessionTape from "@/components/copilot/SessionTape";
import ThreadRail from "@/components/copilot/ThreadRail";
import DeskThreadTop from "@/components/copilot/ThreadHead";
import { useCopilotOn } from "@/components/copilot/useCopilotOn";
import { WHAT_MATTERS_PROMPT, copilotLabHref } from "@/lib/copilot";
import { afterClose, type DeskCommand, type DeskHooks, type DeskTab, type DeskThread, type DeskThreadRef } from "@/lib/desk";
import { cn } from "@/lib/utils";
import styles from "./CopilotLab.module.css";

const TABS: { id: DeskTab; label: string }[] = [{ id: "now", label: "Now" }, { id: "thread", label: "Thread" }, { id: "context", label: "Context" }];
const CONTEXT_KEY = "desk.context.v1";
/** "Plan a trade" with nothing known: the owner names the ticker. The thread list's own button makes the same link. */
const PLAN_HREF = copilotLabHref("", planContext(), { kind: "copilot", ref: null });
const PREP_PROMPT = "Prep the day: what is armed, what news or earnings touch my positions and watches, and what would change a plan before the open?";
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
  const hooks = useMemo<DeskHooks>(() => ({ command, onThread: setThread }), [command]);

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

  const commands = useMemo<PaletteCommand[]>(() => [
    { id: "plan", name: "Plan a trade", hint: "A new plan; you name the symbol. Nothing is sent.", key: "N", run: planTrade },
    { id: "week", name: "Review my week", hint: "One turn: planned vs unplanned, follow-through, exits", run: () => actions.ask(WEEK_REVIEW_CONTEXT) },
    { id: "matters", name: "What matters right now?", hint: "One turn across your positions, watches and investigations", run: () => actions.ask(WHAT_MATTERS_PROMPT) },
    ...(dayPhase === "pre" ? [{ id: "prep", name: "Prep the day", hint: "Puts a prep question in the box, unsent", run: () => fill(PREP_PROMPT) }] : []),
    ...(dayPhase === "close" ? [{ id: "close", name: "Close the day", hint: "Puts a close-of-day question in the box, unsent", run: () => fill(CLOSE_PROMPT) }] : []),
  ], [actions, dayPhase, fill, planTrade]);

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
      if (event.defaultPrevented || event.isComposing || palette || typing(event.target)) return;
      const key = event.key.toLowerCase();
      // ⌘K or Ctrl+K on any platform: outside a field neither does anything in the browser.
      if (key === "k" && (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey) {
        event.preventDefault();
        setPalette(true);
        return;
      }
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (key === "j" || key === "k") { event.preventDefault(); step(key === "j" ? 1 : -1); }
      else if (key === "n" && !event.shiftKey) { event.preventDefault(); planTrade(); }
      else if (event.key === "]") { event.preventDefault(); toggleContext(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [on, palette, step, planTrade, toggleContext]);

  return (
    <div className={styles.desk} data-on={on} data-tab={tab} data-context={contextShown ? "shown" : "hidden"}>
      <header className={styles.bar}>
        <h1 className={styles.title}>Copilot Lab</h1>
        <p className={styles.note}>Research on read-only evidence. No orders; a plan, watch or revisit exists only once you confirm it.</p>
        {on && (
          <div className={styles.barActions}>
            <button type="button" onClick={() => setPalette(true)} aria-label="Jump to a thread or command" aria-haspopup="dialog"
              className="inline-flex min-h-11 items-center gap-2 rounded-md border bg-card px-2.5 text-xs text-muted-foreground hover:text-foreground sm:min-h-8">
              <Search size={14} aria-hidden />Jump to…<kbd className={cn(KBD, "hidden md:inline")}>{jumpKey}</kbd>
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
            <ThreadRail actions={actions} active={thread?.id ?? null} onRows={setRows} />
          </aside>
        )}
        <section aria-label="Conversation" className={styles.thread}>
          {on && <DecisionBar key={thread?.symbol ?? ""} symbol={thread?.symbol ?? null} fill={fill} />}
          {/* The Briefing (or no thread) opens on the day at a glance; a symbol's thread on its header and plan. */}
          {on && (thread?.symbol ? <DeskThreadTop thread={thread} /> : <SessionTape />)}
          <CopilotPanel variant="page" link={link} desk={hooks} />
        </section>
        {on && <aside aria-label="Context" className={styles.inspector}><Inspector thread={thread} /></aside>}
      </div>
      {on && <CommandPalette open={palette} onClose={() => setPalette(false)} threads={rows.filter(r => r.group !== "pinned")} commands={commands} onThread={pick} />}
    </div>
  );
}
