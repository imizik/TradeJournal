"use client";

import { memo, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import {
  AUTO_WEEK_REVIEW_TITLE, asOfText, copilotStatus, pickedModel, rememberModel, createInvestigation, fromSaved, getInvestigation, getPractice, listInvestigations, streamTurn, toSaved, planOrigin, updateInvestigation, whatChangedPrompt,
  IMAGE_PREFILL, MAX_IMAGES, imageUrl, spokenText, uploadImage,
  type CopilotStatus, type LinkOrigin, type Findings, type Investigation, type InvestigationSummary, type LabMessage, type LevelHistory, type Proposal, type ToolEvent, type TradePlan, type TurnMetrics, type OptionCandidates,
} from "@/lib/copilot";
import Link from "next/link";
import { ImagePlus, Loader2, X } from "lucide-react";
import { useAppAccess } from "@/components/AccessProvider";
import LinkedActivity from "@/components/copilot/LinkedActivity";
import ProposalCard from "@/components/copilot/ProposalCard";
import ResearchDeeper from "@/components/copilot/ResearchDeeper";
import TradePlanCard from "@/components/copilot/TradePlanCard";
import { useVoiceInput } from "@/components/copilot/VoiceInput";
import type { CaptureOrigin } from "@/lib/captures";
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
  owner_context: "Your context", get_owner_context: "Your context", get_trade_review: "Trade review",
  get_week_review: "Week review", get_level_history: "Your history here", get_option_candidates: "Option candidates",
};

/** The turn's latest get_option_candidates result for an options plan's symbol and view, when the model asked for it. */
function candidatesFor(tools: ToolEvent[], plan: TradePlan): OptionCandidates | null {
  if (plan.instrument === "stock") return null;
  const row = [...tools].reverse().find(t => t.name === "get_option_candidates" && t.status === "ok" && t.candidates
    && t.candidates.symbol === plan.symbol && t.candidates.direction === plan.direction);
  return row?.candidates ?? null;
}

/** The turn's get_level_history result for the plan's drafted invalidation, when the model asked for it. */
function historyFor(tools: ToolEvent[], plan: TradePlan): LevelHistory | null {
  const row = tools.find(t => t.name === "get_level_history" && t.status === "ok" && t.history
    && t.history.symbol === plan.symbol && t.history.level === plan.invalidation.price);
  return row?.history ?? null;
}

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
        {tools.flatMap(tool => tool.looked_at ?? []).length > 0 && (
          <span className="rounded bg-muted px-1.5 py-0.5 text-foreground/80">Looked at: {tools.flatMap(tool => tool.looked_at ?? []).join(", ")}</span>
        )}
        <span className="group-open:hidden">▸</span>
      </summary>
      <ul className="mt-1.5 space-y-1 border-l pl-3 text-muted-foreground">
        {tools.map(tool => (
          <li key={tool.id}>
            <span className="text-foreground">{TOOL_LABEL[tool.name] ?? tool.name}</span>
            {tool.input ? ` (${Object.values(tool.input).flat().join(", ")})` : ""}: {tool.summary ?? tool.status}
            {tool.provenance && <> · {tool.provenance.source} · as of {asOfText(tool.provenance.as_of)}</>}
            {tool.looked_at?.length ? <> · looked at the {tool.looked_at.join(" and ")}</> : null}
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

/** The lab's backing and evidence as two chips. The page's own description says what the lab may and may not do. */
function StatusLine({ status, error, model, onModel }: { status: CopilotStatus | null; error: string | null; compact?: boolean;
  model: string | null; onModel: (model: string | null) => void }) {
  if (error) return <p role="alert" className="rounded border border-rose-500/30 bg-rose-500/5 px-3 py-2 text-sm text-rose-300">{error}</p>;
  if (!status) return <p className="text-sm text-muted-foreground">Checking Copilot Lab…</p>;
  if (!status.enabled) return <p className="rounded border px-3 py-2 text-sm text-muted-foreground">{status.reason}</p>;
  const simulated = status.backend === "fake";
  return (
    <p className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      <span className={cn("rounded px-1.5 py-0.5", simulated ? "bg-amber-500/10 text-amber-300" : "bg-emerald-500/10 text-emerald-300")}>
        {simulated ? "Simulated model — no API calls" : status.backend === "plan" ? `Claude plan (no API credits) · ${model ?? status.model}` : `Claude API · ${model ?? status.model}`}
      </span>
      {!simulated && (status.models?.length ?? 0) > 1 && (
        <label className="inline-flex items-center gap-1">
          <span className="sr-only">Model</span>
          <select aria-label="Model" value={model ?? status.model} onChange={e => onModel(e.target.value === status.model ? null : e.target.value)}
            className="min-h-11 rounded border bg-background px-1.5 text-xs text-foreground sm:min-h-0">
            {status.models!.map(m => <option key={m} value={m}>{m}{m === status.model ? " (default)" : ""}</option>)}
          </select>
        </label>
      )}
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
    </p>
  );
}

/** ``origin``: what prompted the conversation (a Radar event, a ping, a page's Plan a trade); a confirmed plan records it.
 * ``image``: a screenshot the phone's share sheet stored, attached to the first message and not sent. */
export type PanelLink = { symbol: string; context: string; investigation: string | null; origin?: LinkOrigin | null; image?: string | null };
/** What the page's home (``home``) can do: start a conversation about no symbol with one prompt, or open a saved one. */
export type HomeActions = { ask(prompt: string): void; open(id: string): void };
/** What a page's strip above the panel's conversation (``strip``) can do: start a new conversation on the panel's
 * symbol with ``context`` as its context line (unsent, like a deep link), or open a saved one; neither while a turn runs. */
export type PanelActions = { busy: boolean; start(context: string, origin?: LinkOrigin | null): void; open(id: string): void };

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
 * ``home`` (page only) renders above an empty conversation while the lab is on and no investigation is open.
 * ``strip`` (panel only) renders above the conversation: the page's own view of its symbol (Charts' loop).
 */
function CopilotPanel({ link = null, variant = "page", pageSymbol, pageContext, onClose, home, strip }: {
  link?: PanelLink | null; variant?: "page" | "panel"; pageSymbol?: string; pageContext?: string; onClose?(): void;
  home?: (actions: HomeActions) => ReactNode; strip?: (actions: PanelActions) => ReactNode;
}) {
  const panel = variant === "panel";
  const { owner } = useAppAccess();
  const opening = link?.context && !link.investigation ? `Context: ${link.context}\n\n` : panel && pageContext ? `Context: ${pageContext}\n\n` : "";
  const [status, setStatus] = useState<CopilotStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [symbol, setSymbol] = useState(link?.symbol || pageSymbol || "NBIS");
  // The conversation's origin, from its link; a new or another investigation is the lab's own.
  const [origin, setOrigin] = useState<CaptureOrigin>(() => planOrigin(link?.origin, link?.context));
  const [messages, setMessages] = useState<LabMessage[]>([]);
  const [draft, setDraft] = useState(link?.image ? `${opening}${IMAGE_PREFILL}` : opening);
  // Screenshots for the next message: the server's id and this browser's thumbnail.
  const [attached, setAttached] = useState<{ id: string; url: string }[]>(() => link?.image ? [{ id: link.image, url: imageUrl(link.image) }] : []);
  const [attaching, setAttaching] = useState<{ state: "busy" | "error"; message?: string } | null>(null);
  const picker = useRef<HTMLInputElement | null>(null);
  const [spoken, setSpoken] = useState(false); // the draft ends with words just heard, waiting for review
  const box = useRef<HTMLTextAreaElement | null>(null);
  // The page symbol the owner chose not to follow; a later change offers again.
  const [kept, setKept] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // The model for this browser's turns, when the server offers more than one; the metrics line shows what answered.
  const [model, setModel] = useState<string | null>(null);
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
    if (saved.title.startsWith(AUTO_WEEK_REVIEW_TITLE)) void savedPractice(saved.id);
  }

  /** An automatic week review keeps the practice it proposed: its card returns under the answer until confirmed. */
  async function savedPractice(id: string) {
    let card: Proposal | null | undefined;
    try { card = (await getPractice(undefined, id)).proposed; } catch { return; /* the card is extra */ }
    if (!card) return;
    const shown = card;
    setMessages(list => {
      if (latest.current.current?.id !== id) return list;  // another conversation opened meanwhile
      const at = list.map(m => m.role).lastIndexOf("assistant");
      if (at < 0 || list[at].proposals?.some(p => p.id === shown.id)) return list;
      return list.map((m, i) => i === at ? { ...m, proposals: [...(m.proposals ?? []), shown] } : m);
    });
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
    setOrigin(planOrigin(null));
  }

  async function resume(id: string) {
    if (busy) return;
    setOrigin(planOrigin(null));
    try { open(await getInvestigation(id)); } catch (error) {
      setSaveState({ state: "error", message: error instanceof Error ? error.message : "Could not open that investigation." });
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    copilotStatus().then(next => {
      if (controller.signal.aborted) return;
      setStatus(next);
      setModel(pickedModel(next));
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
        // A plan alert's link carries the owner's own question instead.
        if (link?.investigation) setDraft(link.context || whatChangedPrompt(saved.id));
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

  /** One turn about ``about`` (the symbol box unless given; empty means no symbol). */
  async function send(text: string, about = symbol) {
    const shots = attached;
    const content = text.trim() || (shots.length ? IMAGE_PREFILL : "");
    if (!content || busy || !status?.enabled) return;
    // Text-only, alternating history within the server's limits (24 messages, 4,000 characters each,
    // 40,000 in all): the newest whole pairs are kept, long answers clipped, a failed empty answer left out.
    // Paired from the end, so a transcript that opens with an unanswered question (a research result) stays aligned.
    const pairs: { role: "user" | "assistant"; content: string }[][] = [];
    for (let i = messages.length - 1; i > 0;) {
      const [question, answer] = [messages[i - 1], messages[i]];
      if (question.role === "user" && answer.role === "assistant") {
        if (answer.content.trim())
          pairs.push([{ role: "user", content: spokenText(question).slice(0, MAX_CHARS) },
            { role: "assistant", content: clip(answer.content) }]);
        i -= 2;
      } else i -= 1;
    }
    const history: { role: "user" | "assistant"; content: string }[] = [{ role: "user", content: spokenText({ content, images: shots.map(s => s.url) }) }];
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
    setMessages(current => [...current, { role: "user", content, ...(shots.length ? { images: shots.map(s => s.url) } : {}) },
      { role: "assistant", content: "", tools: [] }]);
    setDraft("");
    setAttached([]);
    setSpoken(false);
    setBusy(true);
    const controller = new AbortController();
    abort.current = controller;
    try {
      await streamTurn(history, about.trim().toUpperCase() || null, event => {
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
      }, controller.signal, model, shots.map(s => s.id));
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

  /** Screenshots from the picker (the phone's camera roll or camera): stored by the server for the next message. With no
   * words of the owner's own in the box yet, the box gets a starting question. */
  async function attach(files: File[]) {
    const room = files.slice(0, MAX_IMAGES - attached.length);
    if (!room.length) return;
    setAttaching({ state: "busy" });
    try {
      for (const file of room) {
        const stored = await uploadImage(file);
        setAttached(list => [...list, { id: stored.id, url: URL.createObjectURL(file) }].slice(0, MAX_IMAGES));
      }
      setAttaching(null);
      setDraft(current => current.replace(/^Context: [^\n]*\n+/, "").trim() ? current : `${current}${IMAGE_PREFILL}`);
    } catch (error) {
      setAttaching({ state: "error", message: error instanceof Error ? error.message : "The screenshot could not be attached." });
    }
  }

  // A shared screenshot's thumbnail from this browser's own copy: the server deletes it once the turn that sends it ends.
  useEffect(() => {
    const id = link?.image;
    if (!id) return;
    const controller = new AbortController();
    fetch(imageUrl(id), { cache: "no-store", signal: controller.signal }).then(r => r.ok ? r.blob() : Promise.reject(new Error("gone")))
      .then(blob => { const url = URL.createObjectURL(blob); setAttached(list => list.map(a => a.id === id ? { ...a, url } : a)); })
      .catch(() => { if (!controller.signal.aborted) { setAttached(list => list.filter(a => a.id !== id)); setAttaching({ state: "error", message: "The shared screenshot is no longer stored; attach it again." }); } });
    return () => controller.abort();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- mount only; the page remounts the lab per deep link

  function startNew() {
    if (busy) return;
    setMessages([]);
    setCurrent(null);
    setConclusion("");
    setSaveState(null);
    remember(null);
    setOrigin(planOrigin(null));
  }

  /** From the page's strip: a new conversation on the page's symbol, ``context`` ready in the box and nothing sent.
   * Words the owner typed stay under the new context line. */
  function begin(context: string, from?: LinkOrigin | null) {
    if (busy) return;
    turns.current += 1; // like a send: a follow still reading drops its result rather than replacing this one
    const own = typed.current ? draft.replace(/^Context: [^\n]*\n+/, "") : "";
    setKept(null);
    fresh(pageSymbol || symbol);
    typed.current = !!own.trim();
    setDraft(`Context: ${context}\n\n${own}`.slice(0, 4000));
    setSpoken(false);
    setOrigin(planOrigin(from, context));
    box.current?.focus();
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

  // Spoken words join whatever is in the box (a context line, or what was typed) and, with auto-send on and no turn
  // running, go straight out; otherwise they wait in the box for a look and Send.
  const voice = useVoiceInput({ status, disabled: status?.enabled !== true, onText: (text, now) => {
    const next = `${draft}${draft && !/\s$/.test(draft) ? " " : ""}${text}`.slice(0, 4000);
    typed.current = true;
    if (now && !busy) { void send(next); return; }
    setDraft(next);
    setSpoken(true);
    box.current?.focus();
  } });

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
      <StatusLine status={status} error={statusError} compact={panel} model={model} onModel={next => { setModel(next); rememberModel(next); }} />
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

      {panel && strip?.({ busy, start: begin, open: id => { setKept(null); void resume(id); } })}

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

      {!panel && home && enabled && !current && !messages.length && home({
        // Across everything: no symbol, so the saved conversation has none either.
        ask: prompt => { if (!busy) { setSymbol(""); void send(prompt, ""); } },
        open: id => void resume(id),
      })}

      <div className={panel ? "min-h-[8rem] space-y-3 rounded border bg-card/40 p-2" : "min-h-[10rem] space-y-4 rounded border bg-card/40 p-3 sm:min-h-[16rem]"} aria-live="polite">
        {!messages.length && !current?.findings && (
          <p className="text-sm text-muted-foreground">
            Ask about an opportunity, push back on the read, then ask for a plan. Try: “{symbol || "NBIS"} looks like it might recover. Is the whole group confirming?”
          </p>
        )}
        {messages.map((message, i) => message.role === "user" ? (
          <div key={i} className="ml-auto max-w-[85%] whitespace-pre-wrap rounded bg-primary/10 px-3 py-2 text-sm text-foreground">
            {message.images?.length ? (
              <span className="mb-1.5 flex flex-wrap justify-end gap-1.5">
                {/* eslint-disable-next-line @next/next/no-img-element -- a local object URL */}
                {message.images.map((src, j) => <img key={j} src={src} alt="Shared screenshot" className="max-h-32 rounded border" />)}
              </span>
            ) : null}
            {message.content}
          </div>
        ) : (
          <div key={i} className="max-w-[95%]">
            {message.content ? <Prose text={message.content} /> : !message.error && !message.metrics && (
              <p className="text-sm italic text-muted-foreground" aria-label="Progress">{message.progress || waiting(message.tools ?? [])}</p>
            )}
            {message.error && <p role="alert" className="mt-1 text-sm text-rose-300">{message.error.message}</p>}
            {message.proposals?.map(proposal => proposal.kind === "trade_plan" ? (
              <TradePlanCard key={proposal.id} plan={proposal} investigationId={current?.id ?? null} origin={origin}
                history={historyFor(message.tools ?? [], proposal)} candidates={candidatesFor(message.tools ?? [], proposal)}
                alertsSupported={status?.enabled === true && !!status.capabilities?.copilot_alerts} onDone={() => setLinkedKey(key => key + 1)} />
            ) : (
              <ProposalCard key={proposal.id} proposal={proposal} investigationId={current?.id ?? null}
                alertsSupported={status?.enabled === true && !!status.capabilities?.copilot_alerts} onDone={() => setLinkedKey(key => key + 1)} />
            ))}
            <Evidence tools={message.tools ?? []} />
            {message.metrics && <Metrics metrics={message.metrics} />}
          </div>
        ))}
        <div ref={end} />
      </div>

      <div className={cn("space-y-1", panel && "sticky bottom-0 bg-[#121924] py-1")}>
      {voice.banner}
      {(attached.length > 0 || attaching) && (
        <div className="flex flex-wrap items-center gap-2" aria-label="Attached screenshots">
          {attached.map(shot => (
            <span key={shot.id} className="relative">
              {/* eslint-disable-next-line @next/next/no-img-element -- a local object URL or the private API */}
              <img src={shot.url} alt="Attached screenshot" className="h-14 w-auto max-w-[8rem] rounded border object-cover" />
              <button type="button" onClick={() => setAttached(list => list.filter(a => a.id !== shot.id))} disabled={busy}
                aria-label="Remove screenshot" className="absolute -right-2 -top-2 flex h-6 w-6 items-center justify-center rounded-full border bg-background text-muted-foreground hover:text-foreground">
                <X size={12} />
              </button>
            </span>
          ))}
          {attaching?.state === "busy" && <span className="text-xs text-muted-foreground">Attaching…</span>}
          {attaching?.state === "error" && <span role="alert" className="text-xs text-rose-300">{attaching.message}</span>}
        </div>
      )}
      <form onSubmit={e => { e.preventDefault(); void send(draft); }} className="flex items-end gap-2">
        <textarea ref={box} value={draft} onChange={e => { typed.current = true; if (!e.target.value.trim()) setSpoken(false); setDraft(e.target.value.slice(0, 4000)); }} rows={2} disabled={!enabled}
          onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(draft); } }}
          placeholder={enabled ? "Ask, challenge, or ask for a plan…" : "Copilot Lab is off"} aria-label="Message"
          className="min-h-[2.75rem] min-w-0 flex-1 resize-y rounded border bg-background px-3 py-2 text-base text-foreground disabled:opacity-50 sm:text-sm" />
        {busy
          ? <button type="button" onClick={() => abort.current?.abort()} className="min-h-11 rounded border px-3 py-2 text-sm">Stop</button>
          : <button type="submit" disabled={!enabled || (!draft.trim() && !attached.length)} className="min-h-11 rounded bg-primary px-3 py-2 text-sm text-primary-foreground disabled:opacity-40">Send</button>}
        <button type="button" aria-label="Attach a screenshot" title="Attach a screenshot (up to 2)" data-testid="copilot-attach"
          onClick={() => picker.current?.click()} disabled={!enabled || busy || attaching?.state === "busy" || attached.length >= MAX_IMAGES}
          className="flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded border text-muted-foreground hover:text-foreground disabled:opacity-40">
          {attaching?.state === "busy" ? <Loader2 className="h-5 w-5 animate-spin" /> : <ImagePlus className="h-5 w-5" />}
        </button>
        <input ref={picker} type="file" accept="image/*" multiple hidden aria-label="Screenshot file" data-testid="copilot-image-input"
          onChange={e => { void attach([...(e.target.files ?? [])]); e.target.value = ""; }} />
        {voice.button}
      </form>
      {voice.available && (
        <div className="flex flex-wrap items-center justify-between gap-x-3">
          {spoken ? <span role="status" className="text-xs text-sky-300">Heard you. Review the message, then Send.</span> : <span />}
          {voice.setting}
        </div>
      )}
      </div>
    </div>
  );
}

/** Memoized: the page around it (Charts' refreshes) re-renders the conversation only when its props change. */
export default memo(CopilotPanel);
