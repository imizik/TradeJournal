"use client";

import { memo, useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import {
  AUTO_WEEK_REVIEW_TITLE, answerParts, asOfText, verdictPending, copilotStatus, pickedModel, rememberModel, pickedBackend, rememberBackend, createInvestigation, fromSaved, getInvestigation, getPractice, listInvestigations, saveOutcome, streamTurn, toSaved, planOrigin, updateInvestigation, whatChangedPrompt, IMAGE_PREFILL, MAX_IMAGES, imageUrl, spokenText, uploadImage,
  type Backend, type CopilotStatus, type LinkOrigin, type Findings, type Investigation, type InvestigationSummary, type LabMessage, type LevelHistory, type Proposal, type ProposalOutcome, type ToolEvent, type TradePlan, type TurnMetrics, type OptionCandidates, type DrawnPlan,
} from "@/lib/copilot";
import Link from "next/link";
import { Eye, ImagePlus, Loader2, MoreHorizontal, Plus, X } from "lucide-react";
import MarkPlanDone from "@/components/copilot/MarkPlanDone";
import { useAppAccess } from "@/components/AccessProvider";
import ExitLessons from "@/components/copilot/ExitLessons";
import LongHolds from "@/components/copilot/LongHolds";
import LinkedActivity from "@/components/copilot/LinkedActivity";
import ProposalCard from "@/components/copilot/ProposalCard";
import ResearchDeeper from "@/components/copilot/ResearchDeeper";
import TradePlanCard from "@/components/copilot/TradePlanCard";
import { useSpeakAnswer } from "@/components/copilot/SpeakAnswer";
import { useVoiceInput } from "@/components/copilot/VoiceInput";
import { newClientId, type CaptureOrigin } from "@/lib/captures";
import { getDeskPicture, type DeskHooks } from "@/lib/desk";
import { cn } from "@/lib/utils";

/** This browser only: which saved investigation to reopen. The server copy is the source of truth. */
const CURRENT_KEY = "tradejournal.copilot-lab.current.v2";
type Current = Pick<Investigation, "id" | "revision" | "title" | "status" | "conclusion" | "source" | "findings" | "created_at">;
const remember = (id: string | null) => {
  try { if (id) window.localStorage.setItem(CURRENT_KEY, id); else window.localStorage.removeItem(CURRENT_KEY); } catch { /* convenience only */ }
};
const shortTime = (iso: string) => new Date(iso).toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
const MAX_CHARS = 4000, MAX_MESSAGES = 23, MAX_TOTAL = 38_000;
const clip = (text: string) => text.length <= MAX_CHARS ? text : `${text.slice(0, MAX_CHARS - 12)} [clipped]`;
const UNAVAILABLE = new Set(["off", "unavailable", "failed", "error", "ungrouped", "not_configured"]);
const TOOL_LABEL: Record<string, string> = {
  get_group_comparison: "Group comparison", get_peer_moves: "Peer moves", get_symbol_news: "News",
  get_symbol_events: "Earnings", get_quotes: "Quotes", get_saved_research: "Saved research", propose_plan: "Proposal", get_investigation_changes: "What changed",
  get_chart_context: "Chart", get_positions: "Positions", get_trades: "Trades", get_memories: "Memories",
  owner_context: "Your context", get_owner_context: "Your context", get_trade_review: "Trade review",
  get_week_review: "Week review", get_level_history: "Your history here", get_option_candidates: "Option candidates",
  get_moment: "That moment",
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
const NOTE = /^_\(([\s\S]*)\)_$/; // a label the server adds ("Simulated model …"), shown quietly

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
        : NOTE.test(run.lines.join("\n"))
          ? <p key={i} className="text-xs text-muted-foreground">{run.lines.join("\n").replace(NOTE, "($1)")}</p>
          : <p key={i} className="whitespace-pre-wrap">{inline(run.lines.join("\n"))}</p>)}
    </div>
  );
}

/** An answer in the copilot's format (docs/copilot-lab.md § How the copilot reasons): the verdict and the headline, the
 * thesis · timing · contract read, the body, the case against set off, and a plain Changes if line. An answer without the format reads as plain text, as before. */
function Answer({ text }: { text: string }) {
  const parts = answerParts(text);
  if (!parts) return <Prose text={text} />;
  return (
    <div className="space-y-2" data-testid="copilot-answer">
      <p className="flex items-baseline gap-2">
        <span data-testid="copilot-verdict" className="shrink-0 rounded bg-primary/15 px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-primary">
          {parts.verdict}
        </span>
        <strong className="text-sm font-semibold leading-snug text-foreground">{parts.headline}</strong>
      </p>
      {parts.read && (
        <p data-testid="copilot-read" className="text-xs text-muted-foreground">
          {parts.read.map((part, i) => (
            <span key={part.label}>{i > 0 && " · "}{part.label} <span className="font-medium text-foreground">{part.value}</span></span>
          ))}
        </p>
      )}
      {parts.body && <Prose text={parts.body} />}
      {parts.against && (
        <p data-testid="copilot-against" className="border-l-2 border-amber-300/60 pl-2 text-sm">
          <span className="font-medium text-amber-300">Against</span> {parts.against}
        </p>
      )}
      {parts.changesIf && <p className="text-sm text-muted-foreground">Changes if {parts.changesIf}</p>}
    </div>
  );
}

/** What the answer read, folded into one line. The line still says what was unavailable, stale, partial, simulated or a
 * replay; opening it lists each source and the turn's model, timings and cost. */
function Sources({ tools, metrics }: { tools: ToolEvent[]; metrics?: TurnMetrics }) {
  const read = tools.filter(tool => tool.name !== "propose_plan"); // a proposal is its card, not a source
  if (!read.length && !metrics) return null;
  const missing = (tool: ToolEvent) => tool.status === "error" || UNAVAILABLE.has(tool.provenance?.state ?? "");
  const count = (test: (tool: ToolEvent) => boolean) => read.filter(test).length;
  const unavailable = count(missing), stale = count(t => !missing(t) && t.provenance?.state === "stale");
  const partial = count(t => !missing(t) && t.provenance?.state === "partial"), reading = count(t => t.status === "running");
  const kinds = new Set(read.map(t => t.provenance?.kind));
  const looked = read.flatMap(t => t.looked_at ?? []);
  const line = [`Sources · ${read.length || "none"}`, unavailable && `${unavailable} unavailable`, stale && `${stale} stale`,
    partial && `${partial} partial`, kinds.has("simulated") && "simulated", kinds.has("replay") && "replay", reading && "reading…"]
    .filter(Boolean).join(" · ");
  return (
    <details className="group mt-2 text-xs" data-testid="copilot-sources">
      <summary className="inline-flex min-h-11 cursor-pointer list-none items-center gap-1 text-muted-foreground hover:text-foreground sm:min-h-0">
        {line}<span aria-hidden className="group-open:rotate-90">▸</span>
      </summary>
      <ul className="mt-1.5 space-y-1 border-l pl-3 text-muted-foreground">
        {read.map(tool => (
          <li key={tool.id}>
            <span className={missing(tool) ? "text-rose-300" : "text-foreground"}>
              {TOOL_LABEL[tool.name] ?? tool.name} · {tool.status === "running" ? "reading" : missing(tool) ? "unavailable" : tool.provenance?.kind}
            </span>
            {tool.input ? ` (${Object.values(tool.input).flat().join(", ")})` : ""}: {tool.summary ?? tool.status}
            {tool.provenance && <> · {tool.provenance.source} · as of {asOfText(tool.provenance.as_of)}</>}
            {tool.ms !== undefined && <> · {tool.ms} ms</>}
          </li>
        ))}
        {looked.length > 0 && <li>Looked at: {looked.join(", ")}</li>}
      </ul>
      {metrics && <Metrics metrics={metrics} />}
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
    <p className="mt-1 text-[11px] text-muted-foreground">
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

/** The lab's backing and evidence as two chips, or (``quiet``, the desk) one small line. The page's own description says
 * what the lab may and may not do. */
const BACKEND_LABEL: Record<Backend, string> = { plan: "Claude plan (no API credits)", anthropic: "Claude API (credits)" };

function StatusLine({ status, error, model, onModel, backend, onBackend, quiet = false }: { status: CopilotStatus | null; error: string | null; quiet?: boolean;
  model: string | null; onModel: (model: string | null) => void; backend: Backend | null; onBackend: (backend: Backend | null) => void }) {
  if (error) return <p role="alert" className="rounded border border-rose-500/30 bg-rose-500/5 px-3 py-2 text-sm text-rose-300">{error}</p>;
  if (!status) return <p className="text-sm text-muted-foreground">Checking Copilot Lab…</p>;
  if (!status.enabled) return <p className="rounded border px-3 py-2 text-sm text-muted-foreground">{status.reason}</p>;
  const simulated = status.backend === "fake";
  const effective = backend ?? status.backend;
  // A chip's tone; on the desk's quiet line every part is plain text, a dot between each.
  const chip = (tone: string) => quiet ? undefined : cn("rounded px-1.5 py-0.5", tone);
  const pick = quiet ? "min-h-11 rounded border-0 bg-transparent text-[11px] text-muted-foreground hover:text-foreground sm:min-h-0"
    : "min-h-11 rounded border bg-background px-1.5 text-xs text-foreground sm:min-h-0";
  return (
    <p data-testid="copilot-status" className={quiet
      ? "flex min-w-0 flex-wrap items-center gap-x-1.5 text-[11px] text-muted-foreground [&>*+*]:before:mr-1.5 [&>*+*]:before:content-['·']"
      : "flex flex-wrap items-center gap-2 text-xs text-muted-foreground"}>
      <span className={chip(simulated ? "bg-amber-500/10 text-amber-300" : "bg-emerald-500/10 text-emerald-300")}>
        {simulated ? "Simulated model — no API calls" : effective === "plan" ? `Claude plan (no API credits) · ${model ?? status.model}` : `Claude API · ${model ?? status.model}`}
      </span>
      {!simulated && (status.backends?.length ?? 0) > 1 && (
        <label className="inline-flex items-center gap-1">
          <span className="sr-only">Backend</span>
          <select aria-label="Backend" value={effective} onChange={e => onBackend(e.target.value === status.backend ? null : e.target.value as Backend)}
            className={pick}>
            {status.backends!.map(b => <option key={b} value={b}>{BACKEND_LABEL[b]}{b === status.backend ? " (default)" : ""}</option>)}
          </select>
        </label>
      )}
      {!simulated && effective === "anthropic" && status.spend_today_usd != null && status.daily_budget_usd != null && (
        <span className={status.spend_today_usd >= status.daily_budget_usd ? cn(chip("bg-rose-500/10"), "text-rose-300") : chip("bg-muted")}>
          API today ${status.spend_today_usd.toFixed(2)} of ${status.daily_budget_usd.toFixed(2)}
        </span>
      )}
      {!simulated && (status.models?.length ?? 0) > 1 && (
        <label className="inline-flex items-center gap-1">
          <span className="sr-only">Model</span>
          <select aria-label="Model" value={model ?? status.model} onChange={e => onModel(e.target.value === status.model ? null : e.target.value)}
            className={pick}>
            {status.models!.map(m => <option key={m} value={m}>{m}{m === status.model ? " (default)" : ""}</option>)}
          </select>
        </label>
      )}
      {status.evidence === "replay" ? (
        <span className={status.replay && "error" in status.replay ? cn(chip("bg-rose-500/10"), "text-rose-300") : chip("bg-violet-500/10 text-violet-300")}>
          {!status.replay ? "Replay" : "error" in status.replay ? `Replay unavailable: ${status.replay.error}`
            : `Replay · clock frozen at ${new Date(status.replay.at).toLocaleString("en-US", { timeZone: "America/New_York", weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} ET · recorded Radar data`}
        </span>
      ) : (
        <span className={chip(status.evidence === "fixture" ? "bg-amber-500/10 text-amber-300" : "bg-sky-500/10 text-sky-300")}>
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
export type PanelLink = { symbol: string; context: string; investigation: string | null; origin?: LinkOrigin | null; plan?: DrawnPlan | null; image?: string | null;
  /** A Radar hit's event id: the desk opens on its decision. */
  radar?: string | null };
/** What the page's home (``home``) can do: start a conversation about no symbol with one prompt, or open a saved one. */
export type HomeActions = { ask(prompt: string): void; open(id: string): void };
/** What a page's strip above the panel's conversation (``strip``) can do: start a new conversation on the panel's
 * symbol with ``context`` as its context line (unsent, like a deep link), or open a saved one; neither while a turn runs.
 * ``chart``: that conversation's first Send also attaches the page's chart (``look``), within the two-image cap. */
export type PanelActions = { busy: boolean; start(context: string, origin?: LinkOrigin | null, plan?: DrawnPlan | null, chart?: boolean): void; open(id: string): void };
/** A page's own chart for "Look at my chart" (``look``): its image and one line of what it shows. */
export type ChartLook = { image: Blob; line: string };

/** A suggestion chip above the desk's message box. */
type Suggestion = { label: string; title?: string; run(): void };

/** The message box's toolbar look for the voice hooks' own buttons: borderless icons, compact on a wide screen. */
const TOOL = "[&>button]:rounded-lg [&>button]:border-transparent [&>button:hover]:bg-secondary md:[&>button]:min-h-9 md:[&>button]:min-w-9";

/** How close to the bottom (px) still counts as reading the end of the conversation. */
const FOLLOW_PX = 80;
/** Scroll events this soon (ms) after the panel scrolled itself are its own, not the reader's. */
const AUTO_MS = 150;

/** The element that scrolls the conversation: a dock or drawer's own scroller, or null for the page itself. */
function scrollParent(node: HTMLElement | null): HTMLElement | null {
  for (let el = node?.parentElement ?? null; el; el = el.parentElement) {
    const { overflowY } = getComputedStyle(el);
    if (overflowY === "auto" || overflowY === "scroll") return el;
  }
  return null;
}

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
 * ``look`` (panel only) offers "Look at my chart": the page's chart goes out as an image with its line, in one turn.
 * ``desk`` (page only) is the Copilot desk's hand-off: its thread list opens investigations or asks through
 * ``command``, the open investigation goes up through ``onThread``, and its activity shows in the desk's inspector.
 */
function CopilotPanel({ link = null, variant = "page", pageSymbol, pageContext, onClose, home, strip, look, desk }: {
  link?: PanelLink | null; variant?: "page" | "panel"; pageSymbol?: string; pageContext?: string; onClose?(): void;
  home?: (actions: HomeActions) => ReactNode; strip?: (actions: PanelActions) => ReactNode; look?: () => Promise<ChartLook>;
  desk?: DeskHooks;
}) {
  const panel = variant === "panel";
  const { owner } = useAppAccess();
  const opening = link?.context && !link.investigation ? `Context: ${link.context}\n\n` : panel && pageContext ? `Context: ${pageContext}\n\n` : "";
  const [status, setStatus] = useState<CopilotStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [symbol, setSymbol] = useState(link?.symbol || pageSymbol || "NBIS");
  // The conversation's origin, from its link; a new or another investigation is the lab's own.
  const [origin, setOrigin] = useState<CaptureOrigin>(() => planOrigin(link?.origin, link?.context));
  // The levels the owner drew for this conversation's plan (Charts' "Plan this"), shown beside the plan card's prices.
  const [drawn, setDrawn] = useState<DrawnPlan | null>(link?.plan ?? null);
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
  const [answered, setAnswered] = useState(0); // turns whose done event arrived: each is read aloud when the speaker is on
  // The model for this browser's turns, when the server offers more than one; the metrics line shows what answered.
  const [model, setModel] = useState<string | null>(null);
  const [backend, setBackend] = useState<Backend | null>(null);
  const abort = useRef<AbortController | null>(null);
  const end = useRef<HTMLDivElement | null>(null);
  // The reader is at the bottom, so new text scrolls into view. A side panel is a chat and opens on its latest message;
  // the page opens a thread at its top (header and decision first) and follows once the owner sends.
  const following = useRef(variant === "panel");
  const autoAt = useRef(0); // when the panel last scrolled itself
  const scroller = useRef<HTMLElement | null>(null); // a dock or drawer's own scroller; null for the page
  const root = useRef<HTMLDivElement | null>(null);
  const [current, setCurrent] = useState<Current | null>(null);
  const [recent, setRecent] = useState<InvestigationSummary[]>([]);
  const [saveState, setSaveState] = useState<{ state: "saving" | "saved" | "error"; message?: string } | null>(null);
  const [conclusion, setConclusion] = useState("");
  const [linkedKey, setLinkedKey] = useState(0);
  // The desk's composer: the thread menu (conclusion, Close), typing a symbol for the scope chip, a phone's "+" tray.
  const [menu, setMenu] = useState(false);
  const [scoping, setScoping] = useState(false);
  const [tray, setTray] = useState(false);
  const menuBox = useRef<HTMLDivElement | null>(null);
  const lesson = useRef<HTMLInputElement | null>(null);
  const unsaved = useRef(false);
  const persisting = useRef(false);
  // Card outcomes recorded while their card may not be saved yet (a turn running, or its save in flight): sent once
  // the save lands. Keyed by card id; a switch to another conversation drops them (its messages carried them).
  const pendingOutcomes = useRef(new Map<string, ProposalOutcome>());
  // What an awaited follow re-checks when it resolves, since the owner may have typed or sent meanwhile.
  const turns = useRef(0); // sends so far
  const running = useRef(false);
  const shown = useRef(0); // messages on screen
  const typed = useRef(false); // the draft holds the owner's own words
  const lookOnSend = useRef(false); // the next Send attaches the page's chart (a strip's start with ``chart``)
  // The newest conversation, for saving it if the panel is closed mid-turn.
  const latest = useRef<{ messages: LabMessage[]; current: Current | null; symbol: string }>({ messages: [], current: null, symbol: "" });
  useEffect(() => {
    shown.current = messages.length;
    latest.current = { messages, current, symbol };
  });

  const refreshRecent = useCallback(() => { void listInvestigations().then(setRecent).catch(() => { /* the list is a convenience */ }); }, []);

  function open(saved: Investigation) {
    following.current = panel;
    lookOnSend.current = false; // a saved conversation is not the strip's: its Send attaches nothing unasked
    setMenu(false);
    pendingOutcomes.current.clear();
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
      // Already kept with the conversation (in any answer, maybe with what was done with it): not added again.
      if (at < 0 || list.some(m => m.proposals?.some(p => p.id === shown.id))) return list;
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
    following.current = panel;
    pendingOutcomes.current.clear();
    setMessages([]);
    setCurrent(null);
    setConclusion("");
    setSaveState(null);
    setSymbol(target);
    if (!typed.current) setDraft(pageContext ? `Context: ${pageContext}\n\n` : "");
    remember(null);
    setOrigin(planOrigin(null));
    setDrawn(null);
    lookOnSend.current = false;
  }

  async function resume(id: string) {
    if (busy) return;
    setOrigin(planOrigin(null));
    setDrawn(null);
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
      setBackend(pickedBackend(next));
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
    persisting.current = true;
    try {
      const saved = current ? await updateInvestigation(current.id, current.revision, fields) : await createInvestigation(fields);
      setCurrent(saved);
      remember(saved.id);
      setSaveState({ state: "saved" });
      void refreshRecent();
      const pending = [...pendingOutcomes.current];
      pendingOutcomes.current.clear();
      for (const [id, outcome] of pending) sendOutcome(saved.id, id, outcome);
    } catch (error) {
      setSaveState({ state: "error", message: error instanceof Error ? error.message : "Saving failed." });
    } finally {
      persisting.current = false;
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
  // Follow a streaming answer only while the reader is at the bottom: scrolled up to read, they stay where they are.
  // Wheel, touch and paging keys stop following at once (a scroll event can arrive after the next chunk already scrolled
  // down); the position re-pins when they come back to the end. Their own send follows again, as does opening a conversation in a side panel.
  useEffect(() => {
    const box = scrollParent(end.current);
    scroller.current = box;
    const target: HTMLElement | Window = box ?? window;
    const read = () => {
      if (performance.now() - autoAt.current < AUTO_MS) return; // our own scroll, not the reader's
      const el = box ?? document.scrollingElement;
      if (el) following.current = el.scrollHeight - el.scrollTop - el.clientHeight < FOLLOW_PX;
    };
    const wheel = (event: WheelEvent) => { if (event.deltaY < 0) following.current = false; };
    const touch = () => { following.current = false; };
    const key = (event: KeyboardEvent) => { if (["ArrowUp", "PageUp", "Home"].includes(event.key) && !(event.target as HTMLElement)?.closest?.("textarea, input")) following.current = false; };
    target.addEventListener("scroll", read, { passive: true });
    target.addEventListener("wheel", wheel as EventListener, { passive: true });
    target.addEventListener("touchmove", touch, { passive: true });
    window.addEventListener("keydown", key);
    return () => {
      target.removeEventListener("scroll", read);
      target.removeEventListener("wheel", wheel as EventListener);
      target.removeEventListener("touchmove", touch);
      window.removeEventListener("keydown", key);
    };
  }, [status?.enabled]); // the conversation renders once the status read says the lab is on
  // The message box grows with what is typed, up to a cap (a dock's share of its height, 40% of the page), then scrolls.
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    const cap = panel ? 224 : Math.round(window.innerHeight * 0.4);
    el.style.height = `${Math.min(el.scrollHeight, cap)}px`;
    el.style.overflowY = el.scrollHeight > cap ? "auto" : "hidden";
  }, [draft, panel, status?.enabled]);
  // To the very end, so the newest line sits above the pinned message box instead of under it.
  const pin = useCallback(() => {
    if (!following.current) return;
    autoAt.current = performance.now();
    const box = scroller.current;
    if (box) box.scrollTop = box.scrollHeight;
    else if (panel) end.current?.scrollIntoView({ block: "nearest" }); // a panel never scrolls the page around it
    else window.scrollTo({ top: document.documentElement.scrollHeight });
  }, [panel]);
  useEffect(pin, [messages, pin]);
  // What grows after the last chunk (the finished answer's cards, the suggestions, the message box's rows) keeps the end
  // in view too, while following.
  useEffect(() => {
    const node = root.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => pin());
    observer.observe(node);
    return () => observer.disconnect();
  }, [pin, status?.enabled]);

  // The page's symbol changed: an empty panel simply follows; a conversation is never retargeted, only offered.
  const engaged = messages.length > 0 || current !== null;
  const offer = panel && !link && !!pageSymbol && status?.enabled === true && pageSymbol !== symbol && kept !== pageSymbol;
  useEffect(() => {
    if (!offer || engaged || busy || !pageSymbol) return;
    const controller = new AbortController();
    void follow(pageSymbol, controller.signal, true);
    return () => controller.abort();
  }, [pageSymbol]); // eslint-disable-line react-hooks/exhaustive-deps -- only a change of the page's symbol moves an empty panel

  // The desk's thread list: open a saved investigation or ask across everything, never while a turn runs.
  useEffect(() => {
    const command = desk?.command;
    if (!command || busy || status?.enabled !== true) return;
    if (command.kind === "open") void resume(command.id).then(() => { if (command.text) fill(command.text); });
    else if (command.kind === "fill") fill(command.text);
    else { setSymbol(""); void send(command.text, ""); }
  }, [desk?.command]); // eslint-disable-line react-hooks/exhaustive-deps -- each command acts once, when it arrives

  // The desk's inspector follows the open investigation.
  const onThread = desk?.onThread;
  useEffect(() => {
    onThread?.(current ? { id: current.id, symbol: symbol || null, title: current.title, refreshKey: linkedKey } : null);
  }, [onThread, current?.id, current?.title, symbol, linkedKey]); // eslint-disable-line react-hooks/exhaustive-deps -- the reported fields, not the whole record

  // The thread menu closes on a press outside it or Escape.
  useEffect(() => {
    if (!menu) return;
    const away = (event: PointerEvent) => { if (!menuBox.current?.contains(event.target as Node)) setMenu(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setMenu(false); };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", away); document.removeEventListener("keydown", escape); };
  }, [menu]);

  /** Words in the message box, unsent, with the cursor after them (the decision bar's Ask why, a suggestion). */
  function fill(text: string) {
    typed.current = true;
    setDraft(text.slice(0, 4000));
    window.setTimeout(() => { const el = box.current; if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); } }, 0);
  }

  const update = (fn: (last: LabMessage) => LabMessage) =>
    setMessages(current => [...current.slice(0, -1), fn(current[current.length - 1])]);

  /** A card was confirmed or dismissed: the conversation keeps it, and a saved investigation records it at once. A card
   * that may not be saved yet (its turn running or its save still to land) is recorded once that save lands. */
  function recordOutcome(id: string, outcome: ProposalOutcome) {
    setMessages(list => list.map(m => m.proposals?.some(p => p.id === id)
      ? { ...m, proposals: m.proposals.map(p => p.id === id ? { ...p, outcome } : p) } : m));
    if (!current || running.current || unsaved.current || persisting.current) pendingOutcomes.current.set(id, outcome);
    else sendOutcome(current.id, id, outcome);
  }
  const sendOutcome = (investigation: string, id: string, outcome: ProposalOutcome) =>
    void saveOutcome(investigation, id, outcome).catch(() => setSaveState({ state: "error",
      message: "What you did with that card was not saved, so after a reload it may offer Confirm again (a retried Confirm does not save a plan or memory twice)." }));

  /** One turn about ``about`` (the symbol box unless given; empty means no symbol). */
  async function send(text: string, about = symbol, shots = attached) {
    const content = text.trim() || (shots.length ? IMAGE_PREFILL : "");
    if (!content || busy || running.current || !status?.enabled) return;
    following.current = true; // the owner's own message: show it and follow the answer
    if (lookOnSend.current && look && shots.length < MAX_IMAGES) {
      lookOnSend.current = false;
      running.current = true; // a second press while the chart is read sends nothing
      setBusy(true); // nor can another conversation open under it
      setAttaching({ state: "busy" });
      try {
        const { image } = await look();
        const stored = await uploadImage(image);
        shots = [...shots, { id: stored.id, url: URL.createObjectURL(image) }];
        setAttaching(null);
      } catch { // the words still go out: the chart is context, not the question
        setAttaching({ state: "error", message: "The chart could not be attached, so your message went without it." });
      }
      running.current = false;
    }
    lookOnSend.current = false;
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
    // The evidence the latest answer read, kept on the server: the copilot reuses it for a follow-up instead of reading again.
    const carry = [...messages].reverse().find(m => m.role === "assistant" && m.carry)?.carry ?? null;
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
        // Each card gets its one id for its replayable saves here, and keeps it in the saved investigation. Its id is
        // made unique in the conversation, which keeps its outcome: the plan backend numbers calls per turn.
        else if (event.type === "proposal") setMessages(list => {
          const taken = new Set(list.flatMap(m => m.proposals ?? []).map(p => p.id));
          let id = event.id;
          for (let n = 2; taken.has(id); n += 1) id = `${event.id}.${n}`;
          const last = list[list.length - 1];
          return [...list.slice(0, -1), { ...last, proposals: [...(last.proposals ?? []), { ...event, id, client_id: newClientId() }] }];
        });
        else if (event.type === "tool") update(last => {
          const tools = last.tools ?? [];
          const at = tools.findIndex(t => t.id === event.id);
          // A note introduces the calls it precedes; once a result is back it is stale.
          return { ...last, progress: event.status === "running" ? last.progress : undefined,
            tools: at < 0 ? [...tools, event] : tools.map((t, i) => i === at ? { ...t, ...event } : t) };
        });
        else if (event.type === "error") update(last => ({ ...last, error: { code: event.code, message: event.message } }));
        else if (event.type === "done") { update(last => ({ ...last, progress: undefined, metrics: event.metrics, carry: event.carry_id ?? undefined })); setAnswered(n => n + 1); }
      }, controller.signal, model, shots.map(s => s.id), backend, carry);
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

  /** "Look at my chart": the page's chart joins any attached screenshot (two at most) and goes out at once, with the
   * owner's own words from the box when there are some. */
  async function lookAtChart(see = look) {
    if (!see || busy) return;
    if (attached.length >= MAX_IMAGES) { setAttaching({ state: "error", message: "Two screenshots are attached; remove one to add the chart." }); return; }
    setAttaching({ state: "busy" });
    try {
      const { image, line } = await see();
      const stored = await uploadImage(image);
      setAttaching(null);
      const own = draft.replace(/^Context: [^\n]*\n+/, "").trim();
      await send(own ? `Context: ${line}.\n\n${own}` : `Context: ${line}. What do you see?`, symbol,
        [...attached, { id: stored.id, url: URL.createObjectURL(image) }]);
    } catch (error) {
      setAttaching({ state: "error", message: error instanceof Error ? error.message : "The chart could not be read." });
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

  /** The desk's "Look at my chart": the Context pane's picture of the thread's symbol today, with the plan's lines. */
  async function deskChart(): Promise<ChartLook> {
    if (!current) throw new Error("The chart needs a saved conversation.");
    const picture = await getDeskPicture(current.id);
    if ("reason" in picture) throw new Error(picture.reason);
    let image: Blob;
    try { image = await fetch(picture.url).then(r => r.blob()); } finally { URL.revokeObjectURL(picture.url); }
    return { image, line: `${symbol} today's minute chart, with the plan's entry and invalidation lines` };
  }

  function startNew() {
    if (busy) return;
    setMenu(false);
    setMessages([]);
    setCurrent(null);
    setConclusion("");
    setSaveState(null);
    remember(null);
    setOrigin(planOrigin(null));
    setDrawn(null);
    lookOnSend.current = false;
  }

  /** From the page's strip: a new conversation on the page's symbol, ``context`` ready in the box and nothing sent.
   * Words the owner typed stay under the new context line. */
  function begin(context: string, from?: LinkOrigin | null, plan?: DrawnPlan | null, chart = false) {
    if (busy) return;
    turns.current += 1; // like a send: a follow still reading drops its result rather than replacing this one
    const own = typed.current ? draft.replace(/^Context: [^\n]*\n+/, "") : "";
    setKept(null);
    fresh(pageSymbol || symbol);
    typed.current = !!own.trim();
    setDraft(`Context: ${context}\n\n${own}`.slice(0, 4000));
    setSpoken(false);
    setOrigin(planOrigin(from, context));
    setDrawn(plan ?? null);
    lookOnSend.current = chart && !!look;
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

  const last = messages.at(-1);
  const speak = useSpeakAnswer({ ready: status !== null, turn: answered, message: last?.role === "assistant" ? last : null, busy, listening: voice.listening, disabled: status?.enabled !== true });

  const enabled = status?.enabled === true;
  // Beside another page the panel is the owner's, and only while the lab is on: otherwise it is not there at all.
  if (panel && (!owner || !enabled)) return null;
  const saving = saveState && (
    <span role={saveState.state === "error" ? "alert" : undefined}
      className={cn("text-xs", saveState.state === "error" ? "text-rose-300" : "text-muted-foreground")}>
      {saveState.state === "saving" ? "Saving…" : saveState.state === "saved" ? "Saved" : saveState.message}
    </span>
  );
  const messageBox = (
    <textarea ref={box} value={draft} onChange={e => { typed.current = true; if (!e.target.value.trim()) setSpoken(false); setDraft(e.target.value.slice(0, 4000)); }} rows={3} disabled={!enabled}
      onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(draft); } }}
      placeholder={enabled ? "Ask, challenge, or ask for a plan…" : "Copilot Lab is off"} aria-label="Message"
      className="block min-h-[4.75rem] w-full resize-none bg-transparent px-3 pb-1 pt-2.5 text-base leading-relaxed text-foreground outline-none placeholder:text-muted-foreground disabled:opacity-50 sm:text-sm" />
  );
  const sendButton = busy
    ? <button type="button" onClick={() => abort.current?.abort()} className="min-h-11 rounded-lg border px-4 text-sm md:min-h-9">Stop</button>
    : <button type="submit" disabled={!enabled || (!draft.trim() && !attached.length)} className="min-h-11 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-40 md:min-h-9">Send</button>;
  const attachButton = (
    <button type="button" aria-label="Attach a screenshot" title="Attach a screenshot (up to 2)" data-testid="copilot-attach"
      onClick={() => picker.current?.click()} disabled={!enabled || busy || attaching?.state === "busy" || attached.length >= MAX_IMAGES}
      className="flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-lg text-muted-foreground hover:bg-secondary hover:text-foreground disabled:opacity-40 md:min-h-9 md:min-w-9">
      {attaching?.state === "busy" ? <Loader2 className="h-[18px] w-[18px] animate-spin" /> : <ImagePlus className="h-[18px] w-[18px]" />}
    </button>
  );
  const pickerInput = (
    <input ref={picker} type="file" accept="image/*" multiple hidden aria-label="Screenshot file" data-testid="copilot-image-input"
      onChange={e => { void attach([...(e.target.files ?? [])]); e.target.value = ""; }} />
  );
  // The answer being read stops the moment the mic is pressed, before it starts listening.
  // On the desk it is round, the main button on a phone.
  const mic = (
    <span onPointerDownCapture={speak.stop} onKeyDownCapture={speak.stop} className={cn("contents", TOOL, desk
      && "max-md:[&>button]:h-12 max-md:[&>button]:w-12 max-md:[&>button]:rounded-full max-md:[&>button[aria-pressed=false]]:border-primary/50 max-md:[&>button[aria-pressed=false]]:text-primary")}>
      {voice.button}
    </span>
  );
  // The desk's next steps from the thread's state, two to four of them; each sends one turn, fills the box or opens the menu.
  const planned = messages.some(m => m.proposals?.some(p => p.kind === "trade_plan"));
  const offered: (Suggestion | false | null | undefined | "")[] = !desk || !enabled ? [] : [
    current && messages.length > 0 && { label: "What changed?", title: "One copilot turn: what changed since this investigation was last discussed",
      run: () => void send(whatChangedPrompt(current.id)) },
    current && symbol && { label: "Look at my chart", title: `Send today's ${symbol} chart from the Context pane and ask what the copilot sees`,
      run: () => void lookAtChart(deskChart) },
    planned && { label: "Size it", title: "Put a sizing question in the box, unsent: you add the dollars at risk",
      run: () => fill("Size it: with this plan's entry and invalidation, how many shares or contracts keep the loss at the invalidation to $") },
    current?.status === "open" && messages.length > 0 && { label: "Close with a lesson", title: "Write the one-line lesson, then close the thread",
      run: () => { setMenu(true); window.setTimeout(() => lesson.current?.focus(), 0); } },
    !current && !messages.length && symbol && { label: `Is ${symbol}'s group confirming?`, run: () => void send(`Is ${symbol}'s group confirming the move?`) },
    !current && !messages.length && symbol && { label: "Plan a trade", run: () => void send(`Plan a trade on ${symbol}.`) },
  ];
  const suggestions = offered.filter((item): item is Suggestion => !!item).slice(0, 4);
  return (
    <div className={panel ? "space-y-2 p-2 text-sm" : "space-y-3"} ref={root} data-testid={panel ? "copilot-panel" : undefined}>
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
      {desk ? (
        // The desk: one quiet line (what answers, what data), then New and the thread's menu.
        <div className="flex items-center gap-2">
          <StatusLine quiet status={status} error={statusError} model={model} onModel={next => { setModel(next); rememberModel(next); }}
            backend={backend} onBackend={next => { setBackend(next); rememberBackend(next); }} />
          <span className="ml-auto flex shrink-0 items-center gap-1 text-[11px] text-muted-foreground">
            {saveState?.state !== "error" && saving}
            {current?.status === "closed" && <span>Closed</span>}
            <button type="button" onClick={startNew} disabled={busy || (!messages.length && !current)} title="Leave this conversation saved and start a new one"
              className="min-h-11 rounded px-2 hover:text-foreground disabled:opacity-40 sm:min-h-7">New</button>
            {current && (
              <div ref={menuBox} className="relative">
                <button type="button" onClick={() => setMenu(open => !open)} aria-expanded={menu} aria-haspopup="true" aria-label="Thread actions"
                  className="flex min-h-11 min-w-11 items-center justify-center rounded hover:text-foreground sm:min-h-7 sm:min-w-7">
                  <MoreHorizontal size={16} />
                </button>
                {menu && (
                  <div role="group" aria-label="Thread actions" className="absolute right-0 top-full z-20 mt-1 w-72 max-w-[calc(100vw-2rem)] space-y-2 rounded border bg-card p-2 text-xs shadow-lg">
                    <input ref={lesson} value={conclusion} onChange={e => setConclusion(e.target.value.slice(0, 280))} disabled={busy}
                      onKeyDown={e => {
                        if (e.key !== "Enter") return;
                        e.preventDefault();
                        if ((conclusion.trim() || null) !== current.conclusion) void persist({ conclusion: conclusion.trim() || null });
                        setMenu(false);
                      }}
                      placeholder="One-line conclusion or lesson" aria-label="Conclusion"
                      className="w-full rounded border bg-background px-2 py-1 text-base text-foreground sm:text-xs" />
                    <div className="flex justify-end gap-1.5">
                      <button type="button" disabled={busy || (conclusion.trim() || null) === current.conclusion}
                        onClick={() => { void persist({ conclusion: conclusion.trim() || null }); setMenu(false); }}
                        className="min-h-11 rounded border px-2 text-muted-foreground hover:text-foreground disabled:opacity-40 sm:min-h-7">Save</button>
                      <button type="button" disabled={busy}
                        onClick={() => { void persist({ status: current.status === "open" ? "closed" : "open", conclusion: conclusion.trim() || null }); setMenu(false); }}
                        className="min-h-11 rounded border px-2 text-foreground hover:bg-muted disabled:opacity-40 sm:min-h-7">{current.status === "open" ? "Close thread" : "Reopen"}</button>
                    </div>
                    {desk?.planDone && (
                      <MarkPlanDone investigationId={current.id} symbol={desk.planDone.symbol} onDone={() => { setMenu(false); desk.planDone?.done(); }} />
                    )}
                  </div>
                )}
              </div>
            )}
          </span>
        </div>
      ) : (
        <StatusLine status={status} error={statusError} model={model} onModel={next => { setModel(next); rememberModel(next); }}
          backend={backend} onBackend={next => { setBackend(next); rememberBackend(next); }} />
      )}
      {/* A failed save says so on its own line, where a long message can wrap. */}
      {desk && saveState?.state === "error" && saving}
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
      {!panel && !desk && <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          Symbol
          <input value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase().replace(/[^A-Z0-9.\-]/g, "").slice(0, 10))}
            className="w-24 rounded border bg-background px-2 py-1 text-base uppercase text-foreground sm:text-sm" aria-label="Investigation symbol" />
        </label>
        <button type="button" onClick={startNew} disabled={busy || (!messages.length && !current)}
          className="min-h-11 rounded border px-2 py-1 text-xs text-muted-foreground hover:text-foreground disabled:opacity-40 sm:min-h-0">New investigation</button>
        {saving}
      </div>}

      {!panel && !desk && recent.length > 0 && (
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

      {current && !desk && (
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

      {current && !desk && <LinkedActivity key={`linked-${current.id}`} investigationId={current.id} refreshKey={linkedKey} />}

      {current?.findings && <FindingsView findings={current.findings} source={current.source} createdAt={current.created_at} />}

      {!panel && home && enabled && !current && !messages.length && home({
        // Across everything: no symbol, so the saved conversation has none either.
        ask: prompt => { if (!busy) { setSymbol(""); void send(prompt, ""); } },
        open: id => void resume(id),
      })}

      <div className={panel ? "space-y-4 py-1" : "space-y-5 py-2"} aria-live="polite">
        {!messages.length && !current?.findings && (
          <p className="text-sm text-muted-foreground">
            Ask about an opportunity, push back on the read, then ask for a plan. Try: “{symbol || "NBIS"} looks like it might recover. Is the whole group confirming?”
          </p>
        )}
        {messages.map((message, i) => message.role === "user" ? (
          <div key={i} className="ml-auto w-fit max-w-[85%] whitespace-pre-wrap rounded-xl rounded-br-sm bg-secondary px-3 py-2 text-sm text-foreground">
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
            {message.content && !(busy && i === messages.length - 1 && verdictPending(message.content)) ? <Answer text={message.content} /> : !message.error && !message.metrics && (
              <p className="text-sm italic text-muted-foreground" aria-label="Progress">{message.progress || waiting(message.tools ?? [])}</p>
            )}
            {message.error && <p role="alert" className="mt-1 text-sm text-rose-300">{message.error.message}</p>}
            {(message.tools ?? []).filter(t => t.lessons).slice(-1).map(t => <ExitLessons key={t.id} lessons={t.lessons!} />)}
            {(message.tools ?? []).filter(t => t.long_holds).slice(-1).map(t => <LongHolds key={t.id} holds={t.long_holds!} />)}
            {message.proposals?.map(proposal => proposal.kind === "trade_plan" ? (
              <TradePlanCard key={proposal.id} plan={proposal} investigationId={current?.id ?? null} origin={origin} drawn={drawn}
                history={historyFor(message.tools ?? [], proposal)} candidates={candidatesFor(message.tools ?? [], proposal)}
                alertsSupported={status?.enabled === true && !!status.capabilities?.copilot_alerts} onDone={() => setLinkedKey(key => key + 1)}
                onOutcome={outcome => recordOutcome(proposal.id, outcome)} />
            ) : (
              <ProposalCard key={proposal.id} proposal={proposal} investigationId={current?.id ?? null}
                alertsSupported={status?.enabled === true && !!status.capabilities?.copilot_alerts} onDone={() => setLinkedKey(key => key + 1)}
                onOutcome={outcome => recordOutcome(proposal.id, outcome)} />
            ))}
            <Sources tools={message.tools ?? []} metrics={message.metrics} />
          </div>
        ))}
        <div ref={end} />
      </div>

      {/* On the desk the box stays in reach while the conversation scrolls; a phone keeps it above the tab bar. */}
      <div className={cn("space-y-1", panel && "sticky bottom-0 bg-[#121924] py-1",
        desk && "sticky bottom-[calc(4.5rem+env(safe-area-inset-bottom))] z-10 bg-background py-2 md:bottom-0")}>
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
      {look && (
        <button type="button" onClick={() => void lookAtChart()} data-testid="copilot-look"
          disabled={!enabled || busy || attaching?.state === "busy" || (!!pageSymbol && symbol !== pageSymbol)}
          title={pageSymbol && symbol !== pageSymbol ? `This conversation is about ${symbol}; the chart shows ${pageSymbol}.` : "Send the chart as you see it, with your levels, and ask what the copilot sees"}
          className="inline-flex min-h-11 items-center gap-1.5 rounded border px-2.5 text-xs text-muted-foreground hover:text-foreground disabled:opacity-40 sm:min-h-0 sm:py-1">
          <Eye size={14} /> Look at my chart
        </button>
      )}
      {suggestions.length > 0 && (
        <div role="group" aria-label="Suggestions" className="-mx-1 flex gap-1.5 overflow-x-auto px-1 max-md:[scrollbar-width:none] md:flex-wrap">
          {suggestions.map(item => (
            <button key={item.label} type="button" onClick={item.run} disabled={busy} title={item.title}
              className="min-h-11 shrink-0 rounded-full border px-3 text-xs text-muted-foreground hover:border-primary/50 hover:text-foreground disabled:opacity-40 md:min-h-7">
              {item.label}
            </button>
          ))}
        </div>
      )}
      {/* One box: (on the desk, what the conversation is about,) the text, then a toolbar inside it. The text area gets the
          full width at every size, even in a narrow dock; a phone desk keeps attach and read-aloud behind "+". */}
      <form onSubmit={e => { e.preventDefault(); void send(draft); }}
        className="rounded-xl border bg-background transition-colors focus-within:border-primary/50">
        {desk && (
            <div className="flex min-h-7 items-center px-2 pt-1.5 text-xs">
              {symbol ? (
                <span className="inline-flex items-center gap-0.5 rounded-full bg-muted py-0.5 pl-2 pr-0.5 text-foreground" data-testid="copilot-scope">
                  About {symbol}
                  <button type="button" onClick={() => setSymbol("")} disabled={busy} aria-label="Ask across everything"
                    title={`Ask across everything, not just ${symbol}`}
                    className="inline-flex h-6 w-6 items-center justify-center rounded-full text-muted-foreground hover:text-foreground disabled:opacity-40">
                    <X size={12} />
                  </button>
                </span>
              ) : scoping ? (
                <input autoFocus aria-label="Investigation symbol" placeholder="Symbol" disabled={busy}
                  onBlur={e => { setSymbol(e.target.value); setScoping(false); }}
                  onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); box.current?.focus(); } if (e.key === "Escape") { e.currentTarget.value = ""; setScoping(false); } }}
                  onChange={e => { e.target.value = e.target.value.toUpperCase().replace(/[^A-Z0-9.\-]/g, "").slice(0, 10); }}
                  className="w-24 rounded border bg-background px-2 py-0.5 text-base uppercase text-foreground sm:text-xs" />
              ) : (
                <button type="button" onClick={() => setScoping(true)} disabled={busy} data-testid="copilot-scope"
                  className="rounded-full px-1 text-muted-foreground hover:text-foreground disabled:opacity-40">Across everything · add a symbol</button>
              )}
            </div>
        )}
        {messageBox}
        <div className="flex items-center gap-1 px-1.5 pb-1.5">
          {desk && (
            <button type="button" onClick={() => setTray(open => !open)} aria-expanded={tray} aria-label="More: attach, read aloud"
              className="flex min-h-11 min-w-11 items-center justify-center rounded-lg text-muted-foreground hover:bg-secondary hover:text-foreground md:hidden">
              <Plus className={cn("h-5 w-5 transition-transform", tray && "rotate-45")} />
            </button>
          )}
          {/* While an answer is read aloud its Stop stays in view on a phone. */}
          <span className={cn("items-center gap-1", desk ? cn("md:flex", tray ? "flex" : "hidden") : "flex")}>{attachButton}</span>
          <span className={cn("items-center", TOOL, desk ? cn("md:flex", tray || speak.speaking ? "flex" : "hidden") : "flex")}>{speak.button}</span>
          <span className="flex-1" />
          {mic}
          {sendButton}
        </div>
        {pickerInput}
      </form>
      {desk && <p className="px-1 text-[11px] text-muted-foreground">Research on read-only evidence. No orders: a plan, watch or revisit exists only once you confirm it.</p>}
      {(voice.available || speak.available) && (
        <div className="flex flex-wrap items-center justify-between gap-x-3">
          {spoken ? <span role="status" className="text-xs text-sky-300">Heard you. Review the message, then Send.</span> : <span />}
          <span className={cn("flex flex-wrap items-center gap-x-3", desk && !tray && "max-md:hidden")}>{voice.setting}{speak.setting}</span>
        </div>
      )}
      </div>
    </div>
  );
}

/** Memoized: the page around it (Charts' refreshes) re-renders the conversation only when its props change. */
export default memo(CopilotPanel);
