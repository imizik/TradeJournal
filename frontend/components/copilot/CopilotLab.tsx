"use client";

import { useMemo, useRef, useState } from "react";
import Link from "next/link";
import CopilotPanel, { type HomeActions, type PanelLink } from "@/components/copilot/CopilotPanel";
import LinkedActivity from "@/components/copilot/LinkedActivity";
import ThreadRail from "@/components/copilot/ThreadRail";
import { useCopilotOn } from "@/components/copilot/useCopilotOn";
import type { DeskCommand, DeskHooks, DeskTab, DeskThreadRef } from "@/lib/desk";
import styles from "./CopilotLab.module.css";

/** The inspector: what the open thread is linked to. Empty until a conversation is saved. */
function Inspector({ thread }: { thread: DeskThreadRef | null }) {
  if (!thread) return <p className="text-sm text-muted-foreground">Open a thread to see its alerts, plans and pings here.</p>;
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-sm">
        <span className="font-semibold text-foreground">{thread.symbol ?? "Across everything"}</span>
        {thread.symbol && <Link href={`/charts?symbol=${encodeURIComponent(thread.symbol)}`} className="ml-auto text-xs text-muted-foreground hover:text-primary">Open in Charts →</Link>}
      </div>
      <LinkedActivity key={thread.id} investigationId={thread.id} refreshKey={thread.refreshKey} />
    </div>
  );
}

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
          <CopilotPanel variant="page" link={link} desk={hooks} />
        </section>
        {on && <aside aria-label="Context" className={styles.inspector}><Inspector thread={thread} /></aside>}
      </div>
    </div>
  );
}
