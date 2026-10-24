"use client";

import { memo, useCallback, useEffect, useRef, useState } from "react";
import {
  asOfText, copilotStatus, createInvestigation, fromSaved, getInvestigation, listInvestigations, streamTurn, toSaved,
  updateInvestigation, whatChangedPrompt, type CopilotStatus, type Findings, type Investigation, type InvestigationSummary, type LabMessage, type ToolEvent, type TurnMetrics,
} from "@/lib/copilot";
import Link from "next/link";
import { X } from "lucide-react";
import { useAppAccess } from "@/components/AccessProvider";
import LinkedActivity from "@/components/copilot/LinkedActivity";
import ProposalCard from "@/components/copilot/ProposalCard";
import ResearchDeeper from "@/components/copilot/ResearchDeeper";
import { cn } from "@/lib/utils";

/** This browser only: which saved investigation to reopen. The server copy is the source of truth. */
const CURRENT_KEY = "tradejournal.copilot-lab.current.v2";
type Current = Pick<Investigation, "id" | "revision" | "title" | "status" | "conclusion" | "source" | "findings" | "created_at">;
const remember = (id: string | null) => {
  try { if (id) window.localStorage.setItem(CURRENT_KEY, id); else window.localStorage.removeItem(CURRENT_KEY); } catch { /* convenience only */ }
};
const shortTime = (iso: string) => new Date(iso).toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
const KIND_TONE: Record<string, string> = {
  recorded: "bg-sky-500/10 text-sky-300", fetched: "bg-emerald-500/10 text-emerald-300",
  cached: "bg-muted text-muted-foreground", simulated: "bg-amber-500/10 text-amber-300", replay: "bg-violet-500/10 text-violet-300", saved: "bg-teal-500/10 text-teal-300",
};
const MAX_CHARS = 4000, MAX_MESSAGES = 23, MAX_TOTAL = 38_000;
const clip = (text: string) => text.length <= MAX_CHARS ? text : `${text.slice(0, MAX_CHARS - 12)} [clipped]`;
const UNAVAILABLE = new Set(["off", "unavailable", "failed", "error", "ungrouped", "not_configured"]);
const TOOL_LABEL: Record<string, string> = {
  get_group_comparison: "Group comparison", get_peer_moves: "Peer moves", get_symbol_news: "News",
  get_symbol_events: "Earnings", get_quotes: "Quotes", get_saved_research: "Saved research", propose_plan: "Proposal", get_investigation_changes: "What changed",
  get_chart_context: "Chart", get_positions: "Positions", get_trades: "Trades", get_memories: "Memories",
  owner_context: "Your context", get_owner_context: "Your context",
};

function inline(text: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={i} className="font-semibold text-foreground">{part.slice(2, -2)}</strong> : part);
}

const BULLET = /^\s*[-*] /;

/** Paragraphs and bullet lists; a run of bullet lines is a list even under a heading line in the same block. */
function Prose({ text }: { text: string }) {
  const runs: { list: boolean; lines: string[] }[] = [];
  for (const block of text.split(/\n{2,}/)) {
    let fresh = true;
    for (const line of block.split("\n")) {
      const list = BULLET.test(line);
      const last = runs[runs.length - 1];
      if (!fresh && last && last.list === list) last.lines.push(line);
      else runs.push({ list, lines: [line] });
      fresh = false;
    }
  }
  return (
    <div className="space-y-2 text-sm leading-relaxed text-foreground/90">
      {runs.map((run, i) => run.list
        ? <ul key={i} className="list-disc space-y-1 pl-5">{run.lines.map((line, j) => <li key={j}>{inline(line.replace(BULLET, ""))}</li>)}</ul>
        : <p key={i} className="whitespace-pre-wrap">{inline(run.lines.join("\n").replace(/^_\(([\s\S]*)\)_$/, "($1)"))}</p>)}
    </div>
  );
}

function Evidence({ tools }: { tools: ToolEvent[] }) {
  if (!tools.length) return null;
  return (
    <details className="group mt-2 text-xs">
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-1.5 text-muted-foreground">
        <span className="font-medium">Evidence</span>
        {tools.map(tool => {
          const missing = tool.status === "error" || UNAVAILABLE.has(tool.provenance?.state ?? "");
          return (
            <span key={tool.id} className={cn("rounded px-1.5 py-0.5", missing ? "bg-rose-500/10 text-rose-300" : tool.status === "running" ? "bg-muted text-muted-foreground" : KIND_TONE[tool.provenance?.kind ?? "cached"])}>
              {TOOL_LABEL[tool.name] ?? tool.name}{tool.status === "running" ? " …" : missing ? " · unavailable" : ` · ${tool.provenance?.kind}`}
            </span>
          );
        })}
        <span className="group-open:hidden">▸</span>
      </summary>
      <ul className="mt-1.5 space-y-1 border-l pl-3 text-muted-foreground">
        {tools.map(tool => (
          <li key={tool.id}>
            <span className="text-foreground">{TOOL_LABEL[tool.name] ?? tool.name}</span>
            {tool.input ? ` (${Object.values(tool.input).flat().join(", ")})` : ""}: {tool.summary ?? tool.status}
            {tool.provenance && <> · {tool.provenance.source} · as of {asOfText(tool.provenance.as_of)}</>}
            {tool.ms !== undefined && <> · {tool.ms} ms</>}
          </li>
        ))}
      </ul>
    </details>
  );
}

const waiting = (tools: ToolEvent[]) =>
  !tools.length ? "Thinking…" : tools.some(t => t.status === "running") ? "Reading evidence…" : "Weighing the evidence…";

function FindingsView({ findings, source, createdAt }: { findings: Findings; source: Current["source"]; createdAt: string }) {
  const list = (label: string, items: string[]) => items.length > 0 && (
    <div><p className="font-medium text-foreground">{label}</p><ul className="list-disc space-y-0.5 pl-5">{items.map((item, i) => <li key={i}>{item}</li>)}</ul></div>
  );
  return (
    <section aria-label="Findings" className="space-y-2 rounded border bg-card/40 p-3 text-sm text-foreground/90">
      <p className="text-xs text-muted-foreground">
        {source === "research_job" ? "Background research result" : "Saved findings"} · saved {shortTime(createdAt)} ET · text, not live data
      </p>
      <p>{findings.summary}</p>
      {list("Key findings", findings.key_findings)}
      {list("Counterpoints", findings.counterpoints)}
      {list("What would change the view", findings.what_would_change)}
      {findings.citations.length > 0 && (
        <ul className="space-y-0.5 text-xs text-muted-foreground">
          {findings.citations.map((c, i) => (
            <li key={i}>
              <a href={c.url} target="_blank" rel="noopener noreferrer" className="underline hover:text-foreground">{c.title || c.url}</a>
              {c.publisher ? ` · ${c.publisher}` : ""}{c.published_at ? ` · ${asOfText(c.published_at)}` : ""}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

const seconds = (ms: number | null) => ms === null ? "—" : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;

function Metrics({ metrics }: { metrics: TurnMetrics }) {
  const u = metrics.usage;
  const input = u.input_tokens + u.cache_read_input_tokens + u.cache_creation_input_tokens;
  const tokens = input + u.output_tokens;
  return (
    <p className="mt-1 text-[11px] tabular-nums text-muted-foreground">
      {metrics.model}
      {metrics.first_feedback_ms !== undefined && <> · first feedback {seconds(metrics.first_feedback_ms)}</>}
      {" "}· first text {seconds(metrics.first_text_ms)} · total {seconds(metrics.total_ms)}
      {metrics.max_silence_ms !== undefined && <> · longest wait {seconds(metrics.max_silence_ms)}</>}{" "}
      · {metrics.tool_calls.length} tool{metrics.tool_calls.length === 1 ? "" : "s"}
      {tokens > 0 && <> · {input.toLocaleString()} in{u.cache_read_input_tokens ? ` (${u.cache_read_input_tokens.toLocaleString()} cache read)` : ""} / {u.output_tokens.toLocaleString()} out</>}
      {metrics.cost_usd !== null && <> · ${metrics.cost_usd.toFixed(4)}{metrics.backend === "fake" ? " (no API call)" : metrics.backend === "plan" ? " API-equivalent · Claude plan (no API credits)" : " est."}</>}
    </p>
  );
}

function StatusLine({ status, error, compact = false }: { status: CopilotStatus | null; error: string | null; compact?: boolean }) {
  if (error) return <p role="alert" className="rounded border border-rose-500/30 bg-rose-500/5 px-3 py-2 text-sm text-rose-300">{error}</p>;
  if (!status) return <p className="text-sm text-muted-foreground">Checking Copilot Lab…</p>;
  if (!status.enabled) return <p className="rounded border px-3 py-2 text-sm text-muted-foreground">{status.reason}</p>;
  const simulated = status.backend === "fake";
  return (
    <p className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      <span className={cn("rounded px-1.5 py-0.5", simulated ? "bg-amber-500/10 text-amber-300" : "bg-emerald-500/10 text-emerald-300")}>
        {simulated ? "Simulated model — no API calls" : status.backend === "plan" ? `Claude plan (no API credits) · ${status.model}` : `Claude API · ${status.model}`}
      </span>
      {status.evidence === "replay" ? (
        <span className={cn("rounded px-1.5 py-0.5", status.replay && "error" in status.replay ? "bg-rose-500/10 text-rose-300" : "bg-violet-500/10 text-violet-300")}>
          {!status.replay ? "Replay" : "error" in status.replay ? `Replay unavailable: ${status.replay.error}`
            : `Replay · clock frozen at ${new Date(status.replay.at).toLocaleString("en-US", { timeZone: "America/New_York", weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} ET · recorded Radar data`}
        </span>
      ) : (
        <span className={cn("rounded px-1.5 py-0.5", status.evidence === "fixture" ? "bg-amber-500/10 text-amber-300" : "bg-sky-500/10 text-sky-300")}>
          {status.evidence === "fixture" ? "Simulated market data" : "Read-only TradeJournal data"}
        </span>
      )}
      {status.backend === "anthropic" && !status.key_configured && <span className="text-rose-300">API key not set</span>}
      {status.backend === "plan" && !status.plan_configured && <span className="text-rose-300">Plan token or Agent SDK not set up</span>}
      {!compact && <span>Read-only · up to {status.limits.max_tool_calls} tool calls per turn · conversations are saved; a proposed watch or revisit exists only once you confirm it</span>}
    </p>
  );
}

export type PanelLink = { symbol: string; context: string; investigation: string | null };

/** What is saved for a conversation: its title, symbol, status, conclusion, text and evidence references. */
function savedFields(messages: LabMessage[], current: Current | null, symbol: string,
  next: Partial<Pick<Current, "status" | "conclusion">> = {}) {
  return { title: current?.title ?? (messages[0].content.split("\n")[0].slice(0, 80) || "Untitled"),
    symbol: symbol.trim().toUpperCase() || null, status: next.status ?? current?.status ?? "open",
    conclusion: next.conclusion !== undefined ? next.conclusion : current?.conclusion ?? null, ...toSaved(messages) };
}

/**
 * One copilot conversation with its proposals, research and linked activity. ``variant="page"`` is the full
 * Copilot Lab (Recent, symbol, history, deep links). ``variant="panel"`` sits beside a page: it follows
 * ``pageSymbol``, resumes that symbol's latest open investigation, opens with ``pageContext`` as its context
 * line, offers (never forces) a switch when the page's symbol changes, and renders nothing unless the owner has
 * the lab on. ``link`` (a deep link, or Radar's drawer) starts a new investigation, prefilled and not sent.
 */
function CopilotPanel({ link = null, variant = "page", pageSymbol, pageContext, onClose }: {
  link?: PanelLink | null; variant?: "page" | "panel"; pageSymbol?: string; pageContext?: string; onClose?(): void;
}) {
  const panel = variant === "panel";
  const { owner } = useAppAccess();
  const opening = link?.context ? `Context: ${link.context}\n\n` : panel && pageContext ? `Context: ${pageContext}\n\n` : "";
  const [status, setStatus] = useState<CopilotStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [symbol, setSymbol] = useState(link?.symbol || pageSymbol || "NBIS");
  const [messages, setMessages] = useState<LabMessage[]>([]);
  const [draft, setDraft] = useState(opening);
  // The page symbol the owner chose not to follow; a later change offers again.
  const [kept, setKept] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const end = useRef<HTMLDivElement | null>(null);
  const [current, setCurrent] = useState<Current | null>(null);
  const [recent, setRecent] = useState<InvestigationSummary[]>([]);
  const [saveState, setSaveState] = useState<{ state: "saving" | "saved" | "error"; message?: string } | null>(null);
  const [conclusion, setConclusion] = useState("");
  const [linkedKey, setLinkedKey] = useState(0);
  const unsaved = useRef(false);
  // What an awaited follow re-checks when it resolves, since the owner may have typed or sent meanwhile.
  const turns = useRef(0); // sends so far
  const running = useRef(false);
  const shown = useRef(0); // messages on screen
  const typed = useRef(false); // the draft holds the owner's own words
  // The newest conversation, for saving it if the panel is closed mid-turn.
  const latest = useRef<{ messages: LabMessage[]; current: Current | null; symbol: string }>({ messages: [], current: null, symbol: "" });
  useEffect(() => {
    shown.current = messages.length;
    latest.current = { messages, current, symbol };
  });

  const refreshRecent = useCallback(() => { void listInvestigations().then(setRecent).catch(() => { /* the list is a convenience */ }); }, []);

  function open(saved: Investigation) {
    setMessages(fromSaved(saved));
    setSymbol(saved.symbol ?? "");
    setCurrent(saved);
    setConclusion(saved.conclusion ?? "");
    setSaveState(null);
    remember(saved.id);
  }

  /**
   * A panel's symbol: its latest open investigation, or a fresh conversation with the page's context line. The
   * reads take a moment; if the owner sends (or, when ``automatic``, the panel gets a conversation) before they
   * answer, the result is dropped rather than replacing a conversation mid-turn.
   */
  async function follow(target: string, signal?: AbortSignal, automatic = false) {
    const asked = turns.current;
    const stale = () => signal?.aborted || running.current || turns.current !== asked || (automatic && shown.current > 0);
    let found: InvestigationSummary | undefined;
    try { found = (await listInvestigations(target)).find(item => item.status === "open" && item.symbol === target); } catch { /* start fresh */ }
    if (stale()) return;
    if (found) {
      try {
        const saved = await getInvestigation(found.id);
        if (!stale()) open(saved);
        return;
      } catch { /* start fresh */ }
    }
    if (!stale()) fresh(target);
  }

  /** A new conversation on ``target``, with the page's context line ready, unless the owner has typed their own. */
  function fresh(target: string) {
    setMessages([]);
    setCurrent(null);
    setConclusion("");
    setSaveState(null);
    setSymbol(target);
    if (!typed.current) setDraft(pageContext ? `Context: ${pageContext}\n\n` : "");
    remember(null);
  }

  async function resume(id: string) {
    if (busy) return;
    try { open(await getInvestigation(id)); } catch (error) {
      setSaveState({ state: "error", message: error instanceof Error ? error.message : "Could not open that investigation." });
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    copilotStatus().then(next => {
      if (controller.signal.aborted) return;
      setStatus(next);
      if (!next.enabled) return;
      if (panel && !link) { void follow(pageSymbol || symbol, controller.signal, true); return; }
      if (panel) return; // Radar's drawer: a new investigation from its link
      void refreshRecent();
      let id: string | null = null;
      try { id = window.localStorage.getItem(CURRENT_KEY); } catch { /* start fresh */ }
      if (link?.investigation) id = link.investigation; // ?investigation=<id> opens that one
      else if (link) id = null; // a symbol or context link starts fresh rather than reopening the last investigation
      if (link && !link.investigation) remember(null);
      else if (id) getInvestigation(id).then(saved => {
        if (controller.signal.aborted) return;
        open(saved);
        // From an alert's link: the question is ready, but a turn costs money, so it is not sent.
        if (link?.investigation) setDraft(whatChangedPrompt(saved.id));
      }).catch(() => remember(null));
    }).catch(error => {
      if (!controller.signal.aborted) setStatusError(error instanceof Error ? error.message : "Copilot Lab is unavailable.");
    });
    return () => controller.abort();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- mount only; the page remounts the lab per deep link

  /** Save the whole investigation: created on its first answer, then updated against the revision it was read at. */
  async function persist(next: Partial<Pick<Current, "status" | "conclusion">> = {}) {
    if (!messages.length) return;
    const fields = savedFields(messages, current, symbol, next);
    setSaveState({ state: "saving" });
    try {
      const saved = current ? await updateInvestigation(current.id, current.revision, fields) : await createInvestigation(fields);
      setCurrent(saved);
      remember(saved.id);
      setSaveState({ state: "saved" });
      void refreshRecent();
    } catch (error) {
      setSaveState({ state: "error", message: error instanceof Error ? error.message : "Saving failed." });
    }
  }

  // Closed mid-turn (a dock tab, a sheet, Radar's drawer, leaving the page): stop the turn, which stops it on the
  // server too, and save what had arrived, so neither the answer so far nor the spend is lost from view.
  useEffect(() => () => {
    if (!abort.current) return;
    abort.current.abort();
    const { messages: said, current: saved, symbol: about } = latest.current;
    if (!said.length) return;
    const fields = savedFields(said, saved, about);
    void (saved ? updateInvestigation(saved.id, saved.revision, fields) : createInvestigation(fields)).catch(() => { /* best effort */ });
  }, []);

  useEffect(() => {
    if (busy || !unsaved.current) return;
    unsaved.current = false;
    void persist();
  }, [busy]); // eslint-disable-line react-hooks/exhaustive-deps -- save once per finished turn, with that render's messages

  // A panel scrolls its own list, never the page around it.
  useEffect(() => { end.current?.scrollIntoView({ block: panel ? "nearest" : "end" }); }, [messages, panel]);

  // The page's symbol changed: an empty panel simply follows; a conversation is never retargeted, only offered.
  const engaged = messages.length > 0 || current !== null;
  const offer = panel && !link && !!pageSymbol && status?.enabled === true && pageSymbol !== symbol && kept !== pageSymbol;
  useEffect(() => {
    if (!offer || engaged || busy || !pageSymbol) return;
    const controller = new AbortController();
    void follow(pageSymbol, controller.signal, true);
    return () => controller.abort();
  }, [pageSymbol]); // eslint-disable-line react-hooks/exhaustive-deps -- only a change of the page's symbol moves an empty panel

  const update = (fn: (last: LabMessage) => LabMessage) =>
    setMessages(current => [...current.slice(0, -1), fn(current[current.length - 1])]);

  async function send(text: string) {
    const content = text.trim();
    if (!content || busy || !status?.enabled) return;
    // Text-only, alternating history within the server's limits (24 messages, 4,000 characters each,
    // 40,000 in all): the newest whole pairs are kept, long answers clipped, a failed empty answer left out.
    // Paired from the end, so a transcript that opens with an unanswered question (a research result) stays aligned.
    const pairs: { role: "user" | "assistant"; content: string }[][] = [];
    for (let i = messages.length - 1; i > 0;) {
      const [question, answer] = [messages[i - 1], messages[i]];
      if (question.role === "user" && answer.role === "assistant") {
        if (answer.content.trim())
          pairs.push([{ role: "user", content: question.content.slice(0, MAX_CHARS) },
            { role: "assistant", content: clip(answer.content) }]);
        i -= 2;
      } else i -= 1;
    }
    const history: { role: "user" | "assistant"; content: string }[] = [{ role: "user", content }];
    let total = content.length;
    for (const pair of pairs) {
      const size = pair[0].content.length + pair[1].content.length;
      if (history.length + 2 > MAX_MESSAGES || total + size > MAX_TOTAL) break;
      history.unshift(...pair);
      total += size;
    }
    turns.current += 1;
    running.current = true;
    typed.current = false;
    setMessages(current => [...current, { role: "user", content }, { role: "assistant", content: "", tools: [] }]);
    setDraft("");
    setBusy(true);
    const controller = new AbortController();
    abort.current = controller;
    try {
      await streamTurn(history, symbol.trim().toUpperCase() || null, event => {
        if (event.type === "text") update(last => ({ ...last, content: last.content + event.delta }));
        else if (event.type === "progress") update(last => ({ ...last, progress: event.text }));
        else if (event.type === "proposal") update(last => ({ ...last, proposals: [...(last.proposals ?? []), event] }));
        else if (event.type === "tool") update(last => {
          const tools = last.tools ?? [];
          const at = tools.findIndex(t => t.id === event.id);
          // A note introduces the calls it precedes; once a result is back it is stale.
          return { ...last, progress: event.status === "running" ? last.progress : undefined,
            tools: at < 0 ? [...tools, event] : tools.map((t, i) => i === at ? { ...t, ...event } : t) };
        });
        else if (event.type === "error") update(last => ({ ...last, error: { code: event.code, message: event.message } }));
        else if (event.type === "done") update(last => ({ ...last, progress: undefined, metrics: event.metrics }));
      }, controller.signal);
    } catch (error) {
      update(last => ({ ...last, error: controller.signal.aborted ? { code: "stopped", message: "Stopped." }
        : { code: "network", message: error instanceof Error && error.message ? "Copilot Lab could not be reached." : "Copilot Lab failed." } }));
    } finally {
      unsaved.current = true;
      running.current = false;
      setBusy(false);
      abort.current = null;
    }
  }

  function startNew() {
    if (busy) return;
    setMessages([]);
    setCurrent(null);
    setConclusion("");
    setSaveState(null);
    remember(null);
  }

  /** A new conversation about a finished research result: its symbol, and the result as the opening context. */
  async function discuss(id: string) {
    if (busy) return;
    try {
      const result = await getInvestigation(id);
      startNew();
      if (result.symbol) setSymbol(result.symbol);
      const gist = result.conclusion || result.findings?.summary || "";
      setDraft(`Context: background research "${result.title}" (saved ${shortTime(result.created_at)} ET)${gist ? `: ${gist}` : ""}`.slice(0, 600) + "\n\n");
    } catch (error) {
      setSaveState({ state: "error", message: error instanceof Error ? error.message : "Could not open that result." });
    }
  }

  // The question a deeper job starts from: the latest one asked here, without its pasted context line.
  const topic = (messages.filter(m => m.role === "user").at(-1)?.content.replace(/^Context: [^\n]*\n+/, "").trim() || current?.title || "").slice(0, 500);

  const enabled = status?.enabled === true;
  // Beside another page the panel is the owner's, and only while the lab is on: otherwise it is not there at all.
  if (panel && (!owner || !enabled)) return null;
  const saving = saveState && (
    <span role={saveState.state === "error" ? "alert" : undefined}
      className={cn("text-xs", saveState.state === "error" ? "text-rose-300" : "text-muted-foreground")}>
      {saveState.state === "saving" ? "Saving…" : saveState.state === "saved" ? "Saved" : saveState.message}
    </span>
  );
  return (
    <div className={panel ? "space-y-2 p-2 text-sm" : "space-y-3"} data-testid={panel ? "copilot-panel" : undefined}>
      {panel && (
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-semibold text-foreground">Copilot · {symbol}</h2>
          {saving}
          <span className="ml-auto flex items-center gap-1">
            <button type="button" onClick={() => { if (!busy) { setKept(null); fresh(pageSymbol || symbol); } }} disabled={busy || (!messages.length && !current)}
              title="Leave this conversation saved and start fresh" className="min-h-11 rounded border px-2 py-0.5 text-xs text-muted-foreground hover:text-foreground disabled:opacity-40 sm:min-h-0">New</button>
            <Link href={current ? `/copilot-lab?investigation=${current.id}` : "/copilot-lab"}
              className="inline-flex min-h-11 items-center rounded border px-2 py-0.5 text-xs text-muted-foreground hover:text-foreground sm:min-h-0">Open in lab</Link>
            {onClose && <button type="button" onClick={onClose} aria-label="Close copilot" className="inline-flex min-h-11 items-center rounded border px-1.5 text-muted-foreground hover:text-foreground sm:min-h-0"><X size={14} /></button>}
          </span>
        </div>
      )}
      <StatusLine status={status} error={statusError} compact={panel} />
      {offer && engaged && pageSymbol && (
        <div role="status" aria-label="Symbol changed" className="flex flex-wrap items-center gap-2 rounded border border-amber-500/30 bg-amber-500/5 p-2 text-xs">
          <span className="text-foreground">The page is now on {pageSymbol}; this conversation is about {symbol}.</span>
          <button type="button" disabled={busy} onClick={() => { setKept(null); void follow(pageSymbol); }}
            className="min-h-11 rounded border px-2 py-0.5 hover:text-foreground disabled:opacity-40 sm:min-h-0">Switch to {pageSymbol}</button>
          <button type="button" onClick={() => setKept(pageSymbol)}
            className="min-h-11 rounded border px-2 py-0.5 text-muted-foreground hover:text-foreground sm:min-h-0">Keep {symbol}</button>
          {busy && <span className="text-muted-foreground">after this answer</span>}
        </div>
      )}
      {!panel && <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          Symbol
          <input value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase().replace(/[^A-Z0-9.\-]/g, "").slice(0, 10))}
            className="w-24 rounded border bg-background px-2 py-1 text-base uppercase text-foreground sm:text-sm" aria-label="Investigation symbol" />
        </label>
        <button type="button" onClick={startNew} disabled={busy || (!messages.length && !current)}
          className="min-h-11 rounded border px-2 py-1 text-xs text-muted-foreground hover:text-foreground disabled:opacity-40 sm:min-h-0">New investigation</button>
        {saving}
      </div>}

      {!panel && recent.length > 0 && (
        <nav aria-label="Recent investigations" className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-muted-foreground">Recent</span>
          {recent.map(item => (
            <button key={item.id} type="button" onClick={() => void resume(item.id)} disabled={busy}
              aria-current={item.id === current?.id ? "true" : undefined}
              className={cn("min-h-11 max-w-[16rem] truncate rounded border px-2 py-0.5 text-left disabled:opacity-40 sm:min-h-0",
                item.id === current?.id ? "border-primary/60 text-foreground" : "text-muted-foreground hover:text-foreground")}
              title={`${item.title}${item.conclusion ? ` — ${item.conclusion}` : ""} · ${shortTime(item.updated_at)}`}>
              {item.symbol ? `${item.symbol} · ` : ""}{item.source === "research_job" ? "research · " : ""}{item.status === "closed" ? "closed · " : ""}{item.title}
            </button>
          ))}
        </nav>
      )}

      {current && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span className={cn("rounded px-1.5 py-0.5", current.status === "open" ? "bg-emerald-500/10 text-emerald-300" : "bg-muted")}>{current.status}</span>
          <input value={conclusion} onChange={e => setConclusion(e.target.value.slice(0, 280))} disabled={busy}
            onBlur={() => { if ((conclusion.trim() || null) !== current.conclusion) void persist({ conclusion: conclusion.trim() || null }); }}
            onKeyDown={e => { if (e.key === "Enter") e.currentTarget.blur(); }}
            placeholder="One-line conclusion (optional)" aria-label="Conclusion"
            className="min-w-[12rem] flex-1 rounded border bg-background px-2 py-1 text-base text-foreground sm:text-xs" />
          <button type="button" disabled={busy} onClick={() => void persist({ status: current.status === "open" ? "closed" : "open" })}
            className="min-h-11 rounded border px-2 py-1 hover:text-foreground disabled:opacity-40 sm:min-h-0">{current.status === "open" ? "Close" : "Reopen"}</button>
          {messages.length > 0 && (
            <button type="button" disabled={busy || !enabled} onClick={() => void send(whatChangedPrompt(current.id))}
              title="One copilot turn: what changed since this investigation was last discussed"
              className="min-h-11 rounded border px-2 py-1 hover:text-foreground disabled:opacity-40 sm:min-h-0">What changed?</button>
          )}
        </div>
      )}
      {current && <ResearchDeeper key={`research-${current.id}`} investigationId={current.id} symbol={symbol} topic={topic}
        onFinished={refreshRecent} onOpenResult={id => void resume(id)} onDiscuss={id => void discuss(id)} />}

      {current && <LinkedActivity key={`linked-${current.id}`} investigationId={current.id} refreshKey={linkedKey} />}

      {current?.findings && <FindingsView findings={current.findings} source={current.source} createdAt={current.created_at} />}

      <div className={panel ? "min-h-[8rem] space-y-3 rounded border bg-card/40 p-2" : "min-h-[10rem] space-y-4 rounded border bg-card/40 p-3 sm:min-h-[16rem]"} aria-live="polite">
        {!messages.length && !current?.findings && (
          <p className="text-sm text-muted-foreground">
            Ask about an opportunity, push back on the read, then ask for a plan. Try: “{symbol || "NBIS"} looks like it might recover. Is the whole group confirming?”
          </p>
        )}
        {messages.map((message, i) => message.role === "user" ? (
          <div key={i} className="ml-auto max-w-[85%] whitespace-pre-wrap rounded bg-primary/10 px-3 py-2 text-sm text-foreground">{message.content}</div>
        ) : (
          <div key={i} className="max-w-[95%]">
            {message.content ? <Prose text={message.content} /> : !message.error && !message.metrics && (
              <p className="text-sm italic text-muted-foreground" aria-label="Progress">{message.progress || waiting(message.tools ?? [])}</p>
            )}
            {message.error && <p role="alert" className="mt-1 text-sm text-rose-300">{message.error.message}</p>}
            {message.proposals?.map(proposal => (
              <ProposalCard key={proposal.id} proposal={proposal} investigationId={current?.id ?? null}
                alertsSupported={status?.enabled === true && !!status.capabilities?.copilot_alerts} onDone={() => setLinkedKey(key => key + 1)} />
            ))}
            <Evidence tools={message.tools ?? []} />
            {message.metrics && <Metrics metrics={message.metrics} />}
          </div>
        ))}
        <div ref={end} />
      </div>

      <form onSubmit={e => { e.preventDefault(); void send(draft); }} className={cn("flex items-end gap-2", panel && "sticky bottom-0 bg-[#121924] py-1")}>
        <textarea value={draft} onChange={e => { typed.current = true; setDraft(e.target.value.slice(0, 4000)); }} rows={2} disabled={!enabled}
          onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(draft); } }}
          placeholder={enabled ? "Ask, challenge, or ask for a plan…" : "Copilot Lab is off"} aria-label="Message"
          className="min-h-[2.75rem] min-w-0 flex-1 resize-y rounded border bg-background px-3 py-2 text-base text-foreground disabled:opacity-50 sm:text-sm" />
        {busy
          ? <button type="button" onClick={() => abort.current?.abort()} className="min-h-11 rounded border px-3 py-2 text-sm">Stop</button>
          : <button type="submit" disabled={!enabled || !draft.trim()} className="min-h-11 rounded bg-primary px-3 py-2 text-sm text-primary-foreground disabled:opacity-40">Send</button>}
      </form>
    </div>
  );
}

/** Memoized: the page around it (Charts' refreshes) re-renders the conversation only when its props change. */
export default memo(CopilotPanel);
