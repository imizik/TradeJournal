"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import CopilotPanel, { type HomeActions, type PanelLink } from "@/components/copilot/CopilotPanel";
import DecisionBar from "@/components/copilot/DecisionBar";
import LinkedActivity from "@/components/copilot/LinkedActivity";
import PlansBoard from "@/components/copilot/PlansBoard";
import { useCopilotOn } from "@/components/copilot/useCopilotOn";
import type { DeskCommand, DeskHooks, DeskTab, DeskThreadRef } from "@/lib/desk";
import styles from "./CopilotLab.module.css";
import { PracticeLine, WEEK_REVIEW_CONTEXT } from "@/components/copilot/ReviewMyWeek";
import { asOfText, getOpenThreads, WHAT_MATTERS_PROMPT, type OpenThreads, type ThreadPosition, type ThreadWatch, type ThreadWatchTrigger } from "@/lib/copilot";
import { cn } from "@/lib/utils";

const pct = (value: number | null | undefined) => value === null || value === undefined ? null : `${value > 0 ? "+" : ""}${value.toFixed(1)}%`;
const expiry = (iso: string) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric" });
const CONDITION: Record<string, string> = { touches: "touches", crosses: "crosses", closes_beyond: "closes beyond" };

function instrument(p: ThreadPosition) {
  if (p.instrument !== "option" || !p.option) return "stock";
  return `${p.option.strike}${p.option.side === "put" ? "P" : "C"} ${expiry(p.option.expiry)}`;
}

function clock(p: ThreadPosition) {
  if (p.instrument === "option" && p.days_to_expiry !== undefined)
    return p.expires_today ? "expires today" : `${p.days_to_expiry} day${p.days_to_expiry === 1 ? "" : "s"} to expiry`;
  if (p.held_minutes !== undefined) return `held ${p.held_minutes} min`;
  return p.days_held !== undefined ? `held ${p.days_held} day${p.days_held === 1 ? "" : "s"}` : null;
}

const Missing = () => <p className="text-muted-foreground">Unavailable right now.</p>;

const triggerLabel = (kind: ThreadWatchTrigger["kind"]) => (kind === "news" ? "News" : kind === "move" ? "Move" : "Earnings");

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="min-w-0 space-y-1">
      <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</h3>
      {children}
    </div>
  );
}

const None = ({ text }: { text: string }) => <p className="text-muted-foreground">{text}</p>;

/**
 * The lab's home: what is live before the first word. Positions, armed alerts, open investigations and waiting research
 * jobs, read once from ``GET /copilot/threads`` (no turn, no cost). "What matters right now?" and "Review my week" are the
 * only things that send, and only when pressed.
 */
function OpenThreadsBlock({ ask, open }: HomeActions) {
  const [threads, setThreads] = useState<OpenThreads | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    getOpenThreads(controller.signal).then(setThreads).catch(failure => {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "Open threads are unavailable.");
    });
    return () => controller.abort();
  }, []);

  const watches = threads?.watches.state === "ok" ? threads.watches.watches : [];
  const alerts = watches.filter(w => w.watch === "level alert");
  const jobs = watches.filter(w => w.watch.startsWith("research job"));
  const jobKind = (w: ThreadWatch) => w.watch.replace(/^research job \((.*)\)$/, "$1").replace("_", " ");

  return (
    <section aria-label="Open threads" className="space-y-3 rounded border bg-card/40 p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold text-foreground">Open threads</h2>
        {threads?.as_of && <span className="text-xs text-muted-foreground">as of {asOfText(threads.as_of)}</span>}
      </div>
      {/* The desk's thread list is narrow at every width, so the buttons and the groups stack. */}
      <div className="grid gap-2">
        <button type="button" onClick={() => ask(WHAT_MATTERS_PROMPT)}
          title="One copilot turn across your positions, watches and open investigations"
          className="min-h-11 rounded bg-primary px-3 py-2 text-sm font-medium text-primary-foreground sm:min-h-9 sm:py-1">
          What matters right now?
        </button>
        <button type="button" onClick={() => ask(WEEK_REVIEW_CONTEXT)}
          title="One copilot turn reviewing your latest trading week: planned vs unplanned, follow-through, alerts and exits"
          className="min-h-11 rounded border border-sky-500/60 px-3 py-2 text-sm text-sky-200 hover:bg-sky-500/15 sm:min-h-9 sm:py-1">
          Review my week
        </button>
      </div>
      <PracticeLine className="text-xs text-sky-200/80" />
      {error ? <p className="text-muted-foreground">Open threads unavailable: {error}</p>
        : !threads ? <p className="text-muted-foreground">Reading what is open…</p> : (
          <div className="grid gap-3">
            <Group title="Positions">
              {threads.positions.state !== "ok" ? <Missing />
                : !threads.positions.positions.length ? <None text="No open positions." /> : (
                  <ul className="space-y-1">
                    {threads.positions.positions.map((p, i) => (
                      <li key={`${p.symbol}-${i}`} className="break-words">
                        <span className="font-medium text-foreground">{p.symbol}</span> <span className="text-muted-foreground">{instrument(p)}</span>
                        {pct(p.unrealized_pct) && <> · <span className={(p.unrealized_pct ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300"}>{pct(p.unrealized_pct)}</span></>}
                        {p.giveback && <> · <span className={cn(p.giveback === "fired" && "text-amber-300")}>give-back {p.giveback}</span></>}
                        {clock(p) && <span className="text-muted-foreground"> · {clock(p)}</span>}
                      </li>
                    ))}
                    {threads.positions.count > threads.positions.positions.length && (
                      <li className="text-muted-foreground">+{threads.positions.count - threads.positions.positions.length} more</li>
                    )}
                  </ul>
                )}
            </Group>
            <Group title="Armed alerts">
              {threads.watches.state !== "ok" ? <Missing />
                : !alerts.length ? <None text="No armed alerts." /> : (
                  <ul className="space-y-1">
                    {alerts.map((a, i) => (
                      <li key={i} className="break-words">
                        <span className="font-medium text-foreground">{a.symbol}</span> {CONDITION[a.condition ?? ""] ?? a.condition} {a.price}
                        {a.interval ? ` (${a.interval})` : ""}{a.label && <span className="text-muted-foreground"> · {a.label}</span>}
                      </li>
                    ))}
                  </ul>
                )}
            </Group>
            <Group title="Open investigations">
              {threads.investigations.state !== "ok" ? <Missing />
                : !threads.investigations.investigations.length ? <None text="No open investigations." /> : (
                  <ul className="space-y-1.5">
                    {threads.investigations.investigations.map(item => (
                      <li key={item.id} className="break-words">
                        <Link href={`/copilot-lab?investigation=${item.id}`}
                          onClick={event => { if (!event.metaKey && !event.ctrlKey && !event.shiftKey && event.button === 0) { event.preventDefault(); open(item.id); } }}
                          className="text-foreground underline decoration-muted-foreground/50 underline-offset-2 hover:decoration-foreground">
                          {item.symbol ? `${item.symbol} · ` : ""}{item.source === "research_job" ? "research · " : ""}{item.title}
                        </Link>
                        {item.conclusion && <p className="text-muted-foreground">{item.conclusion}</p>}
                        {item.watch && item.watch.length > 0 && (
                          <ul aria-label={`New since ${item.title}`} className="mt-0.5 space-y-0.5 text-xs text-muted-foreground">
                            {item.watch.map((w, i) => (
                              <li key={i} className="break-words">
                                <span className="text-foreground">{triggerLabel(w.kind)}</span> · {w.text} · {asOfText(w.fired_at)}
                                {w.delivery === "sent" ? "" : ` · ${w.delivery}${w.reason ? ` (${w.reason})` : ""}`}
                              </li>
                            ))}
                          </ul>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
            </Group>
            <Group title="Waiting research">
              {threads.watches.state !== "ok" ? <Missing />
                : !jobs.length ? <None text="No research waiting." /> : (
                  <ul className="space-y-1">
                    {jobs.map((job, i) => (
                      <li key={i} className="break-words">
                        <span className="text-foreground">{jobKind(job)}</span> · {job.status}
                        {job.symbols?.length ? ` · ${job.symbols.join(", ")}` : ""}
                        {job.question && <span className="text-muted-foreground"> · {job.question}</span>}
                      </li>
                    ))}
                  </ul>
                )}
            </Group>
          </div>
        )}
    </section>
  );
}

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
 * The Copilot desk, the full-page lab: the thread list (Plans and Open threads), the conversation and the inspector
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
            <PlansBoard open={actions.open} />
            <OpenThreadsBlock {...actions} />
          </aside>
        )}
        <section aria-label="Conversation" className={styles.thread}>
          {on && <DecisionBar key={thread?.symbol ?? ""} symbol={thread?.symbol ?? null} fill={text => setCommand({ kind: "fill", text, n: ++sent.current })} />}
          <CopilotPanel variant="page" link={link} desk={hooks} />
        </section>
        {on && <aside aria-label="Context" className={styles.inspector}><Inspector thread={thread} /></aside>}
      </div>
    </div>
  );
}
