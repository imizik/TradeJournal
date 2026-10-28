"use client";

import { useMemo, useRef, useState } from "react";
import CopilotPanel, { type HomeActions, type PanelLink } from "@/components/copilot/CopilotPanel";
import DecisionBar from "@/components/copilot/DecisionBar";
import Inspector from "@/components/copilot/Inspector";
import ThreadRail from "@/components/copilot/ThreadRail";
import DeskThreadTop from "@/components/copilot/ThreadHead";
import { useCopilotOn } from "@/components/copilot/useCopilotOn";
import type { DeskCommand, DeskHooks, DeskTab, DeskThreadRef } from "@/lib/desk";
import styles from "./CopilotLab.module.css";

const TABS: { id: DeskTab; label: string }[] = [{ id: "now", label: "Now" }, { id: "thread", label: "Thread" }, { id: "context", label: "Context" }];

/**
 * The Copilot desk, the full-page lab: the thread list (``ThreadRail``), the conversation and the inspector
 * side by side, so what is live stays in view while a conversation runs. A phone shows one at a time behind three tabs.
 * While the lab is off only the conversation shows, saying so.
 */
export default function CopilotLab({ link = null }: { link?: PanelLink | null }) {
  const on = useCopilotOn();
  // A deep link (a ping, a Radar row, a chip) opens on its conversation, so a phone's composer is on the first screen.
  const [tab, setTab] = useState<DeskTab>(link ? "thread" : "now");
  const [command, setCommand] = useState<DeskCommand | null>(null);
  const [thread, setThread] = useState<DeskThreadRef | null>(null);
  const [deciding, setDeciding] = useState(false);
  const sent = useRef(0);
  const actions = useMemo<HomeActions>(() => ({
    open: id => { setCommand({ kind: "open", id, n: ++sent.current }); setTab("thread"); },
    ask: text => { setCommand({ kind: "ask", text, n: ++sent.current }); setTab("thread"); },
  }), []);
  const hooks = useMemo<DeskHooks>(() => ({ command, onThread: setThread }), [command]);
  return (
    <div className={styles.desk} data-on={on} data-tab={tab}>
      <header className={styles.bar}>
        <h1 className={styles.title}>Copilot Lab</h1>
        <p className={styles.note}>Research on read-only evidence. No orders; a plan, watch or revisit exists only once you confirm it.</p>
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
            <ThreadRail actions={actions} active={thread?.id ?? null} />
          </aside>
        )}
        <section aria-label="Conversation" className={styles.thread}>
          {/* One main element per thread: the header, then the decision when one is asked (the ladder shrinks to a line),
              else the full plan ladder; the conversation follows. */}
          {on && <DeskThreadTop thread={thread} compact={deciding} hero={
            <DecisionBar key={thread?.symbol ?? ""} symbol={thread?.symbol ?? null} onActive={setDeciding}
              fill={text => setCommand({ kind: "fill", text, n: ++sent.current })} />} />}
          <CopilotPanel variant="page" link={link} desk={hooks} />
        </section>
        {on && <aside aria-label="Context" className={styles.inspector}><Inspector thread={thread} /></aside>}
      </div>
    </div>
  );
}
