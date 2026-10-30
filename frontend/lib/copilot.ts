import { apiUrl } from "./api";
import type { AlertsPayload } from "./alerts";
import type { Capture, CaptureOrigin, CaptureSide, OriginKind } from "./captures";
import type { PlanPosition } from "@/components/dashboard/PlansCard";

export type CopilotStatus =
  | { enabled: false; reason: string }
  | { enabled: true; backend: "fake" | "anthropic" | "plan"; evidence: "fixture" | "live" | "replay"; model: string; effort: string;
      replay?: { at: string; session: string; passes_before: number; last_pass_at: string } | { error: string };
      fallbacks: boolean; key_configured: boolean; plan_configured: boolean; tools: string[];
      /** The models a turn may pick (the server's default first); absent on older servers. */
      models?: string[];
      /** The backends a turn may pick (the server's default first), and today's estimated API spend against its cap. */
      backends?: Backend[]; spend_today_usd?: number | null; daily_budget_usd?: number;
      /** copilot_alerts: whether the level-alert route accepts a watch confirmed here. transcriber: whether hold-to-talk
       * can use this server's speech to text (else the browser's own, where it has one). */
      capabilities?: { copilot_alerts: boolean; transcriber?: { configured: boolean; provider: string } };
      limits: { max_rounds: number; max_tool_calls: number; tool_timeout_s: number; turn_timeout_s: number } };

export type ToolEvent = {
  type: "tool"; id: string; name: string; status: "running" | "ok" | "error"; input?: Record<string, unknown>;
  summary?: string; ms?: number; provenance?: { source: string; kind: "recorded" | "fetched" | "cached" | "simulated" | "replay" | "saved" | "proposal"; as_of: string | number | null; state?: string | null };
  /** get_level_history only: the counts the plan card shows under its invalidation (never ids). */
  history?: LevelHistory;
  /** get_option_candidates only: the contracts the plan card offers as a pick list for its contract. */
  candidates?: OptionCandidates;
  /** get_trade_review only: the images it showed the model ("plan chart"). */
  looked_at?: string[];
  /** get_week_review only: the week's answered exit reviews, each opening its plan's thread (never sent to the model). */
  lessons?: WeekLessons;
  /** get_week_review only: open positions set to a long hold, each opening its plan's thread (never sent to the model). */
  long_holds?: WeekLongHolds;
};

/** The owner's exit lessons for the reviewed week: ``followed`` is what the answer opens with; ``thread`` the plan's
 * investigation, null in the simulated fixture (the row opens its symbol instead). */
export type WeekLessons = {
  exited: number; answered: number; simulated: boolean;
  rows: { symbol: string; followed: "yes" | "partly" | "no" | null; lesson: string; thread: string | null }[];
};

/** The long holds the desk never asks about day to day: days held, the plan's thesis in the owner's words (absent without
 * a plan) and ``thread`` the plan's investigation, null without one or in the simulated fixture (the row opens its symbol). */
export type WeekLongHolds = {
  simulated: boolean;
  rows: { symbol: string; contract: string; days_held: number; thesis: string | null; thread: string | null }[];
};

/** Real contracts from the option chain for the plan card's contract pick list: a short label ("Nov 13 '26 95C"), days to
 * expiry, ask per contract and per share, delta when the chain gives one, and the chains' read time (as_of). */
export type OptionPick = { label: string; days: number; ask_contract: number | null; ask?: number; delta?: number | null };
export type OptionCandidates = {
  symbol: string; direction: "long" | "short"; simulated: boolean; as_of?: string | null;
  picks: OptionPick[];
};

/** What the owner's own past trades in the symbol did at a level the same distance from their entry: evidence, not a rule. */
export type LevelHistory = {
  symbol: string; level: number; side: "below" | "above"; entry: number; distance_pct: number; trades: number; crossed: number;
  recovered: number; median_from_cross_pct: number | null; small: boolean; simulated: boolean;
};

export type TurnMetrics = {
  backend: string; evidence: string; model: string; first_text_ms: number | null; total_ms: number; rounds: number;
  /** First progress note, tool call or answer text; absent on turns saved before it was measured. */
  first_feedback_ms?: number | null; first_progress_ms?: number | null; max_silence_ms?: number;
  tool_calls: { name: string; status: string; ms: number }[];
  usage: { input_tokens: number; output_tokens: number; cache_read_input_tokens: number; cache_creation_input_tokens: number };
  /** For the plan backend, an API-price equivalent: the Claude plan is not billed per token. */
  cost_usd: number | null; billing?: "claude_plan";
};

export type CopilotEvent =
  | { type: "text"; delta: string }
  | { type: "progress"; text: string }
  | ToolEvent
  | ({ type: "proposal" } & Proposal)
  | { type: "error"; code: string; message: string }
  | { type: "done"; metrics: TurnMetrics };

/** A step the model proposed (propose_plan). It is only a card: nothing exists until the owner confirms it. Saved
 * with its answer: ``client_id`` is the card's one id for its replayable saves (minted when it arrives, so a Confirm
 * retried after a reload or from a second window returns the first plan, time stop or memory), and ``outcome`` is
 * what the owner did with it, so a reopened card comes back as it was left. */
export type Proposal = { id: string; client_id?: string; outcome?: ProposalOutcome } & (
  | { kind: "watch"; symbol: string; condition: "touches" | "crosses" | "closes_beyond"; price: number; interval: string | null;
      label: string; why: string; last?: number; as_of?: string | number | null }
  | { kind: "revisit"; question: string; horizon_days: number }
  | { kind: "memory"; memory_kind: "statement" | "thesis" | "preference" | "lesson"; symbol: string | null; text: string; interpretation?: string }
  | { kind: "trade_plan"; symbol: string; direction: "long" | "short"; instrument: "stock" | "calls" | "puts"; contract: string | null;
      thesis: string; entry_trigger: PlanLevel; invalidation: PlanLevel; time_stop: string | null; size_note: string | null;
      last?: number; as_of?: string | number | null }
  | { kind: "practice"; text: string; measure: PracticeMeasure; label: string; target: number | null; why: string });
/** ``confirmed``: Confirm ran (``note``: what it said; ``text``: the words a memory or practice saved; a plan card's
 * part results and fields as confirmed). ``dismissed``: the card stays hidden. Only a record of what happened on the
 * page: restoring one creates nothing. */
export type ProposalOutcome = { state: "confirmed" | "dismissed"; note?: string; text?: string;
  parts?: Partial<Record<"plan" | "entry" | "invalidation" | "timeStop", { state: "done" | "failed"; text: string }>>;
  fields?: { thesis: string; contract: string; entry: string; invalidation: string; time_stop: string; size_note: string; horizon?: "" | "day" | "swing" | "long" } };
export type PlanLevel = { condition: "touches" | "crosses" | "closes_beyond"; price: number; interval: string | null };
export type TradePlan = Extract<Proposal, { kind: "trade_plan" }>;

/** ``images``: an owner message's screenshot thumbnails (this browser only; the saved text carries SHARED_MARKER). */
export type Rating = "helped" | "didnt";
/** How one saved answer went (a small subset of its turn's metrics); what comes back on a reopened conversation. */
export type SavedMetrics = { first_text_ms?: number; total_ms?: number; rounds?: number; model?: string; backend?: string; tools?: string[]; error?: string };
export type LabMessage = { role: "user" | "assistant"; content: string; rating?: Rating; savedMetrics?: SavedMetrics; images?: string[]; progress?: string; proposals?: Proposal[]; tools?: ToolEvent[]; error?: { code: string; message: string }; metrics?: TurnMetrics };

/** One status read per page load, shared by the nav, the panels and every Ask copilot button. Only an answer is
 * kept: a failed read is tried again by the next caller. */
let statusOnce: Promise<CopilotStatus> | null = null;
export function copilotStatus(): Promise<CopilotStatus> {
  statusOnce ??= getCopilotStatus().catch(error => { statusOnce = null; throw error; });
  return statusOnce;
}

export async function getCopilotStatus(signal?: AbortSignal): Promise<CopilotStatus> {
  const response = await fetch(apiUrl("/copilot/status"), { cache: "no-store", signal });
  if (!response.ok) throw new Error(response.status === 403 ? "Copilot Lab is owner-only." : `Copilot Lab status failed (${response.status}).`);
  return response.json();
}

/** Parse one SSE frame ("event: x\ndata: {...}"); unknown or malformed frames are skipped. */
export function parseFrame(frame: string): CopilotEvent | null {
  const data = frame.split("\n").filter(line => line.startsWith("data:")).map(line => line.slice(5).trimStart()).join("\n");
  if (!data) return null;
  try {
    const event = JSON.parse(data);
    return event && typeof event.type === "string" ? event as CopilotEvent : null;
  } catch {
    return null;
  }
}

/** Stream one turn. History is text-only: the server re-reads evidence rather than trusting the browser. */
export type Backend = "anthropic" | "plan";
export const MODEL_KEY = "copilot.model";
export const BACKEND_KEY = "copilot.backend";

/** The backend the owner picked for their turns in this browser, when the server still offers it. */
export function pickedBackend(status: CopilotStatus | null): Backend | null {
  if (!status?.enabled || !status.backends || status.backends.length < 2) return null;
  try {
    const saved = window.localStorage.getItem(BACKEND_KEY) as Backend | null;
    return saved && status.backends.includes(saved) ? saved : null;
  } catch { return null; }
}

export function rememberBackend(backend: Backend | null) {
  try { if (backend) window.localStorage.setItem(BACKEND_KEY, backend); else window.localStorage.removeItem(BACKEND_KEY); } catch { /* per-browser convenience only */ }
}

/** The model the owner picked for their turns in this browser, when the server still offers it. */
export function pickedModel(status: CopilotStatus | null): string | null {
  if (!status?.enabled || !status.models || status.models.length < 2) return null;
  try {
    const saved = window.localStorage.getItem(MODEL_KEY);
    return saved && status.models.includes(saved) ? saved : null;
  } catch { return null; }
}

export function rememberModel(model: string | null) {
  try { if (model) window.localStorage.setItem(MODEL_KEY, model); else window.localStorage.removeItem(MODEL_KEY); } catch { /* per-browser convenience only */ }
}

/** Size it for me: the dollar risk per trade the owner last typed on a plan card in this browser, blank until then. */
export const RISK_KEY = "copilot.risk";

export function savedRisk(): string {
  try { return window.localStorage.getItem(RISK_KEY) ?? ""; } catch { return ""; }
}

export function rememberRisk(risk: string) {
  try { if (Number(risk) > 0) window.localStorage.setItem(RISK_KEY, risk); else window.localStorage.removeItem(RISK_KEY); } catch { /* per-browser convenience only */ }
}

/** Read it back: whether this browser speaks each finished answer, and how fast. */
export const SPEAK_KEY = "copilot.speak";
export const SPEAK_RATE_KEY = "copilot.speak-rate";
export const SPEAK_RATES = [0.9, 1, 1.2] as const;

export function speakOn(): boolean {
  try { return window.localStorage.getItem(SPEAK_KEY) === "on"; } catch { return false; }
}

export function rememberSpeak(on: boolean) {
  try { if (on) window.localStorage.setItem(SPEAK_KEY, "on"); else window.localStorage.removeItem(SPEAK_KEY); } catch { /* per-browser convenience only */ }
}

export function speakRate(): number {
  try {
    const saved = Number(window.localStorage.getItem(SPEAK_RATE_KEY));
    return (SPEAK_RATES as readonly number[]).includes(saved) ? saved : 1;
  } catch { return 1; }
}

export function rememberSpeakRate(rate: number) {
  try { if (rate === 1) window.localStorage.removeItem(SPEAK_RATE_KEY); else window.localStorage.setItem(SPEAK_RATE_KEY, String(rate)); } catch { /* per-browser convenience only */ }
}

const CARD_NAME: Record<Proposal["kind"], string> = { trade_plan: "plan", watch: "watch", revisit: "revisit", memory: "memory", practice: "practice" };
const SCALE: Record<string, string> = { k: "thousand", K: "thousand", M: "million", B: "billion" };
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const SIGN: Record<string, string> = { "+": "plus ", "-": "minus ", "−": "minus " };

/** One line of an answer as it should sound: markdown gone, prices in dollars, tickers spelled ("N B I S"). */
function speakLine(line: string): string {
  return line
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1").replace(/https?:\/\/\S+/g, "")
    .replace(/\*\*|__|`/g, "").replace(/(^|[^\w*])[*_]([^*_\n]+)[*_](?=[^\w*]|$)/g, "$1$2")
    .replace(/\b(\d{4})-(\d{2})-(\d{2})\b/g, (date: string, year: string, month: string, day: string) =>
      Number(month) >= 1 && Number(month) <= 12 ? `${MONTHS[Number(month) - 1]} ${Number(day)}, ${year}` : date)
    .replace(/(\d)\s*[–—-]\s*(?=\$?\d)/g, "$1 to ")
    .replace(/([+\-−]?)\$(\d[\d,]*)(?:\.(\d+))?(?:\s?([kKMB])\b)?/g, (_, sign: string, whole: string, decimals: string | undefined, scale: string | undefined) => {
      const dollars = whole.replace(/,/g, "");
      const said = scale ? `${dollars}${decimals ? `.${decimals}` : ""} ${SCALE[scale]} dollars`
        : decimals && Number(decimals.slice(0, 2).padEnd(2, "0")) ? (Number(dollars) ? `${dollars} dollars and ` : "")
          + `${Number(decimals.slice(0, 2).padEnd(2, "0"))} cents` : `${dollars} dollars`;
      return `${SIGN[sign] ?? ""}${said}`;
    })
    .replace(/\b(up|down)\s+[+\-−](?=\d)/gi, "$1 ")
    .replace(/(^|[\s(])([+\-−])(?=\d)/g, (_, before: string, sign: string) => `${before}${SIGN[sign]}`)
    .replace(/(\d),(?=\d{3}\b)/g, "$1").replace(/(\d),(?=\d{3}\b)/g, "$1")
    .replace(/(\d)%/g, "$1 percent")
    .replace(/(\d)R\b/g, "$1 R")
    .replace(/\b(\d+(?:\.\d+)?)([CP])\b/g, (_, strike: string, side: string) => `${strike} ${side === "C" ? "call" : "put"}`)
    .replace(/\$?\b([A-Z]{2,5})\b/g, (_, ticker: string) => ticker.split("").join(" "))
    .replace(/\s*(?:→|->)\s*/g, " to ").replace(/[≈~](?=\s?\d)/g, "about ").replace(/\s*&\s*/g, " and ").replace(/\s@\s/g, " at ")
    .replace(/[*#|>`]/g, "").replace(/\s+/g, " ").trim();
}

/** A finished answer as the phone reads it aloud: the simulated-model head skipped, list items read as sentences, and
 * one closing sentence when cards wait to be confirmed (never confirmed by voice). Tool rows and metrics are not
 * part of the text. An answer with no text says its error instead; a stopped turn says nothing. */
export function speechText(message: Pick<LabMessage, "content" | "proposals" | "error">): string {
  const sentences: string[] = [];
  for (const block of message.content.split(/\n{2,}/)) {
    if (/^_?\(Simulated model[\s\S]*\)_?$/.test(block.trim())) continue;
    for (const raw of block.split("\n")) {
      // The answer format's labels: "Verdict: Hold — The thesis…" reads "Hold. The thesis…", "Changes if: …" as a clause.
      const said = raw.replace(/^\s*\**verdict\**\s*:\s*\**([a-z]+)\**\s*(?:—|–|--|-|:)\s*/i, "$1. ").replace(/^\s*\**changes if\**\s*:\**\s*/i, "Changes if ");
      const line = speakLine(said.replace(/^\s*(?:#{1,6}\s+|>\s*|[-*•]\s+|\d+[.)]\s+)/, ""));
      if (!line) continue;
      sentences.push(/[.!?:;,]$/.test(line) ? line : `${line}.`);
    }
  }
  if (!sentences.length && message.error && message.error.code !== "stopped") sentences.push(message.error.message);
  const cards = message.proposals ?? [];
  if (cards.length === 1) sentences.push(`There is a ${CARD_NAME[cards[0].kind]} card to confirm.`);
  else if (cards.length > 1) {
    const kinds = new Set(cards.map(card => card.kind));
    sentences.push(`There are ${cards.length} ${kinds.size === 1 ? `${CARD_NAME[cards[0].kind]} ` : ""}cards to confirm.`);
  }
  return sentences.join(" ").replace(/\s+/g, " ").trim();
}

export async function streamTurn(history: { role: "user" | "assistant"; content: string }[], symbol: string | null,
  onEvent: (event: CopilotEvent) => void, signal: AbortSignal, model: string | null = null, imageIds: string[] = [],
  backend: Backend | null = null) {
  const response = await fetch(apiUrl("/copilot/chat"), {
    method: "POST", headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ messages: history, symbol, ...(model ? { model } : {}), ...(imageIds.length ? { image_ids: imageIds } : {}),
      ...(backend ? { backend } : {}) }),
    signal, cache: "no-store",
  });
  if (!response.ok || !response.body) {
    let detail = `Copilot request failed (${response.status}).`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (response.status === 422) detail = "The lab refused this conversation's shape; start a new investigation.";
    } catch { /* keep the status text */ }
    onEvent({ type: "error", code: `http_${response.status}`, message: detail });
    return;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    let cut = buffer.indexOf("\n\n");
    while (cut >= 0) {
      const event = parseFrame(buffer.slice(0, cut));
      buffer = buffer.slice(cut + 2);
      if (event) onEvent(event);
      cut = buffer.indexOf("\n\n");
    }
    if (done) break;
  }
}

export function asOfText(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "time unknown";
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) + " ET";
}

// --------------------------------------------------------------------------- the answer format

/** The words an answer may lead with, in step with ``SYSTEM_PROMPT``'s answer format (backend/app/ai/copilot.py). */
export const VERDICTS = ["Hold", "Wait", "Pass", "Focus", "Draft", "Pattern", "Broken", "Unclear"] as const;
export type Verdict = (typeof VERDICTS)[number];
/** An answer in the copilot's format: ``Verdict: Hold — The thesis has not broken.`` first, then the body, then an
 * optional ``Changes if: …`` last line, kept apart from the body. */
export type AnswerParts = { verdict: Verdict; headline: string; body: string; changesIf: string | null };

const VERDICT_LINE = /^\**verdict\**\s*:\s*\**([a-z]+)\**\s*(?:—|–|--|-|:)\s*(.+)$/i;
const CHANGES_LINE = /^(?:[-*]\s+)?\**changes if\**\s*:\**\s*(.+?)\**$/i;
const NOTE_LINE = /^_\(.*\)_$/; // the scripted model's own labels ("Simulated model …"), which a server may put first

/**
 * The answer's verdict, headline, body and Changes if line; null for an answer without that structure (one saved
 * before the format, a backend that ignores it, an unknown verdict word), which renders as plain text. Note lines
 * ahead of the Verdict line stay at the top of the body.
 */
export function answerParts(text: string): AnswerParts | null {
  const lines = text.split("\n");
  let at = 0;
  while (at < lines.length && (!lines[at].trim() || NOTE_LINE.test(lines[at].trim()))) at += 1;
  const found = VERDICT_LINE.exec(lines[at]?.trim() ?? "");
  const verdict = found && VERDICTS.find(v => v.toLowerCase() === found[1].toLowerCase());
  if (!found || !verdict) return null;
  const rest = [...lines.slice(0, at), ...lines.slice(at + 1)];
  // Only the answer's last line is its Changes if; one inside the body stays where the model put it.
  let last = rest.length - 1;
  while (last >= 0 && !rest[last].trim()) last -= 1;
  const changesIf = last >= 0 && CHANGES_LINE.test(rest[last].trim()) ? CHANGES_LINE.exec(rest[last].trim())![1].trim() : null;
  if (changesIf !== null) rest.splice(last, 1);
  return { verdict, headline: found[2].replace(/\*\*/g, "").trim(), body: rest.join("\n").trim(), changesIf: changesIf || null };
}

/** While an answer streams in, a first line that could still become the Verdict line ("Verd", "Verdict: Hold —") is not
 * shown yet. */
export function verdictPending(text: string): boolean {
  const lines = text.split("\n");
  const writing = lines[lines.length - 1].trim().replace(/\*/g, "").toLowerCase();
  const before = lines.slice(0, -1).some(line => line.trim() && !NOTE_LINE.test(line.trim()));
  return !before && writing.length > 0 && ("verdict:".startsWith(writing) || (writing.startsWith("verdict:") && !VERDICT_LINE.test(writing)));
}

// --------------------------------------------------------------------------- saved investigations

export type EvidenceRef = { tool: string; as_of?: string | number | null; kind?: NonNullable<ToolEvent["provenance"]>["kind"]; message?: number };
export type Findings = {
  summary: string; key_findings: string[]; counterpoints: string[]; what_would_change: string[];
  citations: { url: string; publisher?: string | null; published_at?: string | null; title?: string | null }[];
};
export type InvestigationSummary = {
  id: string; source: "copilot" | "research_job"; has_findings: boolean; title: string; symbol: string | null; status: "open" | "closed"; conclusion: string | null;
  revision: number; message_count: number; created_at: string; updated_at: string;
};
export type Investigation = InvestigationSummary & {
  transcript: { role: "user" | "assistant"; content: string; proposals?: Proposal[]; rating?: Rating; metrics?: SavedMetrics }[]; evidence: EvidenceRef[]; findings: Findings | null;
};
export type InvestigationFields = Pick<Investigation, "title" | "symbol" | "status" | "conclusion" | "transcript" | "evidence">;

async function investigationRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(`/copilot/investigations${path}`), { cache: "no-store", ...init,
    headers: init?.body ? { "Content-Type": "application/json" } : undefined });
  if (!response.ok) {
    let detail = `Saving failed (${response.status}).`;
    try { const body = await response.json(); if (typeof body?.detail === "string") detail = body.detail; } catch { /* keep the status */ }
    throw new Error(detail);
  }
  return response.json();
}

export const listInvestigations = (symbol?: string) =>
  investigationRequest<{ investigations: InvestigationSummary[] }>(`?limit=8${symbol ? `&symbol=${encodeURIComponent(symbol)}` : ""}`).then(r => r.investigations);
export const getInvestigation = (id: string) => investigationRequest<Investigation>(`/${encodeURIComponent(id)}`);
export const createInvestigation = (fields: InvestigationFields) =>
  investigationRequest<Investigation>("", { method: "POST", body: JSON.stringify(fields) });
export const updateInvestigation = (id: string, revision: number, fields: InvestigationFields) =>
  investigationRequest<Investigation>(`/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify({ ...fields, revision }) });
/** Records what the owner did with a saved card. It needs no revision: an open window's next save keeps it. */
export const saveOutcome = (id: string, proposalId: string, outcome: ProposalOutcome) =>
  investigationRequest<Investigation>(`/${encodeURIComponent(id)}/proposals/${encodeURIComponent(proposalId)}/outcome`,
    { method: "PUT", body: JSON.stringify(outcome) });
/** Records (or, with null, clears) the owner's rating of one saved answer. It needs no revision: an open window's next save keeps it. */
export const saveRating = (id: string, index: number, rating: Rating | null) =>
  investigationRequest<Investigation>(`/${encodeURIComponent(id)}/messages/${index}/rating`, { method: "PUT", body: JSON.stringify({ rating }) });
/** The small part of an answer's turn that is saved: its speed, model, tool names and error code. */
export function savedMetrics(m: LabMessage): SavedMetrics | undefined {
  const t = m.metrics;
  if (!t && !m.error) return m.savedMetrics;
  const out: SavedMetrics = t ? { first_text_ms: t.first_text_ms ?? undefined, total_ms: t.total_ms, rounds: t.rounds, model: t.model.slice(0, 80),
    backend: t.backend.slice(0, 40), tools: t.tool_calls.map(c => c.name).slice(0, 50) } : {};
  if (m.error) out.error = m.error.code.slice(0, 80);
  return Object.fromEntries(Object.entries(out).filter(([, v]) => v !== undefined)) as SavedMetrics;
}
/** The card's confirmed outcome as saved now (another window may have confirmed it), else null; a failed read is null. */
export async function confirmedElsewhere(id: string, proposalId: string): Promise<ProposalOutcome | null> {
  try {
    const card = (await getInvestigation(id)).transcript.flatMap(m => m.proposals ?? []).find(p => p.id === proposalId);
    return card?.outcome?.state === "confirmed" ? card.outcome : null;
  } catch { return null; /* Confirm's own saves still replay on the card's client id */ }
}
/** Cards kept per answer, as the server caps them. */
export const MAX_SAVED_PROPOSALS = 4;

// --------------------------------------------------------------------------- screenshots

/** What a message that carried a screenshot says in history and the saved transcript; the image itself is never kept. */
export const SHARED_MARKER = "[shared a screenshot]";
/** The message ready in the box when a screenshot arrives with no words of the owner's own. */
export const IMAGE_PREFILL = "Here is my chart. What do you see, and what would the plan be?";
export const MAX_IMAGES = 2;
export type SharedImage = { id: string; width: number; height: number; bytes: number };
export const imageUrl = (id: string) => apiUrl(`/copilot/images/${encodeURIComponent(id)}`);
/** A message's text as history and the saved transcript carry it: marked when it carried a screenshot. */
export const spokenText = (m: Pick<LabMessage, "content" | "images">) => m.images?.length ? `${SHARED_MARKER} ${m.content}` : m.content;

/** One screenshot for the next turn: processed and kept by the server for that turn (a day at most). */
export async function uploadImage(file: Blob): Promise<SharedImage> {
  const form = new FormData();
  form.append("image", file, file instanceof File ? file.name : "screenshot");
  const response = await fetch(apiUrl("/copilot/images"), { method: "POST", body: form, cache: "no-store" });
  if (!response.ok) {
    let detail = `The screenshot could not be attached (${response.status}).`;
    try { const body = await response.json(); if (typeof body?.detail === "string") detail = body.detail; } catch { /* keep the status */ }
    throw new Error(detail);
  }
  return response.json();
}

/** What is saved: the text of each message, each answer's cards with what was done with them, and, per answer, which
 * tools it used and how old their data was. A proposal is not evidence, so propose_plan is left out of the evidence. */
export function toSaved(messages: LabMessage[]): Pick<InvestigationFields, "transcript" | "evidence"> {
  return {
    transcript: messages.map(m => ({ role: m.role, content: spokenText(m),
      ...(m.role === "assistant" && m.rating ? { rating: m.rating } : {}),
      ...(m.role === "assistant" && savedMetrics(m) ? { metrics: savedMetrics(m) } : {}),
      // A card from the stream still carries its event type, which is not part of the proposal.
      ...(m.proposals?.length ? { proposals: m.proposals.slice(0, MAX_SAVED_PROPOSALS).map(card => Object.fromEntries(Object.entries(card).filter(([key]) => key !== "type")) as Proposal) } : {}) })),
    evidence: messages.flatMap((m, i) => (m.tools ?? []).filter(t => t.status === "ok" && t.provenance && t.name !== "propose_plan")
      .map(t => ({ tool: t.name, as_of: t.provenance!.as_of, kind: t.provenance!.kind, message: i }))),
  };
}

/** A saved conversation as messages; its cards come back as cards, with any outcome they were left with. */
export function fromSaved(saved: Investigation): LabMessage[] {
  return saved.transcript.map(({ metrics, ...m }, i) => ({ ...m, ...(metrics ? { savedMetrics: metrics } : {}), tools: saved.evidence.filter(e => e.message === i).map((e, j) => ({
    type: "tool" as const, id: `saved-${i}-${j}`, name: e.tool, status: "ok" as const,
    provenance: { source: "saved reference (re-read to see the data)", kind: e.kind ?? "cached", as_of: e.as_of ?? null },
  })) }));
}

// --------------------------------------------------------------------------- deep link

export const CONTEXT_MAX = 300;
const SYMBOL_RE = /^[A-Z][A-Z0-9.\-]{0,9}$/;

/** `/copilot-lab?symbol=X&context=...`: opens a new investigation prefilled, never sent on its own. */
/** The "What changed?" turn for a reopened investigation: the id goes in the text, so every backend can act on it. */
export const whatChangedPrompt = (investigationId: string) =>
  `What changed? Use get_investigation_changes for investigation ${investigationId}, then compare it with fresh group, peer, news and quote reads, and say whether the saved conclusion still holds.`;

export function copilotLabHref(symbol: string, context?: string, origin?: LinkOrigin | null, plan?: DrawnPlan | null) {
  const query = new URLSearchParams({ symbol: symbol.toUpperCase() });
  if (context?.trim()) query.set("context", context.trim().slice(0, CONTEXT_MAX));
  if (origin) query.set("origin", originParam(origin));
  if (plan) query.set("plan", drawnParam(plan));
  return `/copilot-lab?${query}`;
}

/** The levels the owner drew on Charts for a plan ("Plan this"): the plan card shows them beside the copilot's draft.
 * `trigger` is null when only the invalidation was drawn. */
export type DrawnPlan = { side: "long" | "short"; trigger: number | null; invalidation: number };
/** `trigger:95.90,invalidation:92.30,side:long` (no trigger part when only the invalidation was drawn). */
export const drawnParam = (plan: DrawnPlan) =>
  [plan.trigger !== null && `trigger:${plan.trigger.toFixed(2)}`, `invalidation:${plan.invalidation.toFixed(2)}`, `side:${plan.side}`].filter(Boolean).join(",");
/** The `plan` parameter, or null when it is not one Charts could have made. */
export function readDrawn(value: string): DrawnPlan | null {
  const parts = new Map(value.split(",").map(part => { const at = part.indexOf(":"); return [part.slice(0, at).trim(), part.slice(at + 1).trim()] as const; }));
  const number = (key: string) => { const raw = parts.get(key); const n = raw && /^\d+(\.\d{1,4})?$/.test(raw) ? Number(raw) : NaN; return n > 0 ? n : null; };
  const side = parts.get("side");
  const invalidation = number("invalidation");
  const trigger = parts.has("trigger") ? number("trigger") : null;
  if ((side !== "long" && side !== "short") || invalidation === null || (parts.has("trigger") && trigger === null)) return null;
  if (trigger !== null && (side === "long" ? trigger <= invalidation : trigger >= invalidation)) return null;
  return { side, trigger, invalidation };
}
/** Sent on the window when a plan card is confirmed (its plan saved), so Charts can label the levels it was drawn from. */
export const PLAN_CONFIRMED = "tradejournal:plan-confirmed";
export type PlanConfirmed = { symbol: string; side: "long" | "short"; entry: number; invalidation: number; drawn: DrawnPlan | null };

/** What prompted a plan, carried by a deep link as `origin=<kind>[:<ref>]` (docs/copilot-lab.md § Origin). */
export type LinkOrigin = { kind: OriginKind; ref: string | null };
const ORIGIN_KINDS: readonly OriginKind[] = ["radar_event", "thesis_watch", "premarket_prep", "chart", "dashboard", "copilot", "manual"];
const ORIGIN_REF_RE = /^[A-Za-z0-9:._-]{1,80}$/;
export const originParam = (origin: LinkOrigin) => origin.ref ? `${origin.kind}:${origin.ref}` : origin.kind;
/** `kind` or `kind:ref`; anything else is dropped. */
export function readOrigin(value: string): LinkOrigin | null {
  const at = value.indexOf(":");
  const kind = (at < 0 ? value : value.slice(0, at)).trim() as OriginKind;
  const ref = at < 0 ? "" : value.slice(at + 1).trim();
  if (!ORIGIN_KINDS.includes(kind) || (ref && !ORIGIN_REF_RE.test(ref))) return null;
  return { kind, ref: ref || null };
}
/** The plan card's origin: the conversation's link, with the context line it opened on; else the lab itself. */
export const planOrigin = (origin: LinkOrigin | null | undefined, context?: string): CaptureOrigin =>
  origin ? { ...origin, text: context?.trim() || null } : { kind: "copilot", ref: null, text: null };

/** The deep link's values, or null when there is none; an invalid symbol is dropped. */
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** The deep link's values, or null when there is none. `investigation` opens that saved investigation; a `context`
 * with it is the owner's question, ready in the message box (a plan alert's tap). */
export function readDeepLink(params: { symbol?: string | string[]; context?: string | string[]; investigation?: string | string[]; origin?: string | string[]; plan?: string | string[]; image?: string | string[]; radar?: string | string[] }) {
  const one = (value?: string | string[]) => (Array.isArray(value) ? value[0] : value) ?? "";
  const symbol = one(params.symbol).trim().toUpperCase();
  const context = one(params.context).replace(/\s+/g, " ").trim().slice(0, CONTEXT_MAX);
  const investigation = one(params.investigation).trim();
  const origin = readOrigin(one(params.origin));
  // A screenshot the phone's share sheet stored (app/share-target): attached, not sent.
  const image = /^[0-9a-f]{32}$/.test(one(params.image)) ? one(params.image) : null;
  // A desk Radar row: the desk opens on that hit's decision (watching, passing or planning).
  const radar = /^[A-Za-z0-9._-]{1,120}$/.test(one(params.radar)) ? one(params.radar) : null;
  if (UUID_RE.test(investigation)) return { symbol: "", context, investigation: investigation.toLowerCase(), origin, plan: null };
  // An origin alone (a prep ping with no investigation) still starts a conversation that records it.
  if (!symbol && !context && !origin && !image) return null;
  return { symbol: SYMBOL_RE.test(symbol) ? symbol : "", context, investigation: null, origin, plan: readDrawn(one(params.plan)), image,
    ...(radar && SYMBOL_RE.test(symbol) ? { radar } : {}) };
}

// --------------------------------------------------------------------------- research queue

export type ResearchJob = {
  id: string; kind: "question" | "radar_event" | "reassess"; status: "queued" | "running" | "done" | "failed" | "cancelled";
  input: { question?: string; symbols?: string[]; from_investigation?: string; investigation_id?: string };
  attempts: number; error: string | null; cost_usd: number | null; investigation_id: string | null;
  created_at: string; next_attempt_at?: string; finished_at: string | null;
  /** Set when a job finishes done: was it material, and what happened to its phone ping. */
  notify?: { material_change: boolean; material_reason: string; status: "sent" | "sending" | "skipped" | "failed" | "held";
    reason?: string; error?: string } | null;
};
export type ResearchJobs = { jobs: ResearchJob[]; queue_enabled: boolean; daily_budget_usd: number; spent_today_usd: number };
export const ACTIVE_JOB = new Set<ResearchJob["status"]>(["queued", "running"]);

async function queueRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(`/copilot/research-jobs${path}`), { cache: "no-store", ...init,
    headers: init?.body ? { "Content-Type": "application/json" } : undefined });
  if (!response.ok) {
    let detail = `Research request failed (${response.status}).`;
    try { const body = await response.json(); if (typeof body?.detail === "string") detail = body.detail; } catch { /* keep the status */ }
    throw new Error(detail);
  }
  return response.json();
}

/** With an investigation, only the jobs asked from it, so a busy queue cannot push them out of the page. */
export const listResearchJobs = (signal?: AbortSignal, fromInvestigation?: string) =>
  queueRequest<ResearchJobs>(`?limit=50${fromInvestigation ? `&from_investigation=${encodeURIComponent(fromInvestigation)}` : ""}`, { signal });
export const enqueueResearch = (question: string, symbols: string[], investigationId: string) =>
  queueRequest<{ job: ResearchJob; created: boolean; queue_enabled: boolean }>("", { method: "POST",
    body: JSON.stringify({ question, symbols, investigation_id: investigationId }) });

// --------------------------------------------------------------------------- open threads (the lab's home)

/** A section the server could not read. */
type Missing = { state: "unavailable" };
export type ThreadPosition = {
  symbol: string; instrument: "stock" | "option"; option?: { side: string; strike: number; expiry: string }; direction?: string;
  quantity?: number; unrealized_pct?: number | null; giveback?: "not armed" | "armed" | "fired"; peak_gain_pct?: number | null;
  days_to_expiry?: number; expires_today?: boolean; days_held?: number; held_minutes?: number;
};
/** One thesis-watch trigger for an open investigation: a new headline, a move since its evidence or the prior close, or
 * earnings within two trading days; ``delivery`` says whether the phone was told (sent), or why not. */
export type ThreadWatchTrigger = { kind: "news" | "move" | "earnings"; text: string; fired_at: string; delivery: "sending" | "sent" | "failed" | "skipped" | "held"; reason?: string | null; path: string };
export type ThreadInvestigation = { id: string; source: "copilot" | "research_job"; symbol?: string; title: string; status: string; conclusion?: string; updated_at: string; watch?: ThreadWatchTrigger[] };
/** An armed level alert ("level alert") or a waiting research job ("research job (<kind>)"). */
export type ThreadWatch = {
  watch: string; symbol?: string; price?: number; condition?: string; interval?: string; label?: string; armed_at?: string;
  status?: string; symbols?: string[]; question?: string; due?: string;
};
export type OpenThreads = {
  positions: { state: "ok"; count: number; positions: ThreadPosition[] } | Missing;
  investigations: { state: "ok"; investigations: ThreadInvestigation[] } | Missing;
  watches: { state: "ok"; watches: ThreadWatch[] } | Missing;
  as_of: string | null;
};
export const getOpenThreads = (signal?: AbortSignal) => request<OpenThreads>("/copilot/threads", { signal });
/** One armed copilot plan on the lab home's Plans board (``GET /copilot/plans``), nearest to a trigger first. A level
 * is ``armed`` (with its distance from ``last`` when a price was read) or ``hit`` (``hit_at``, epoch seconds); null when
 * that alert was never set or was deleted. */
export type PlanBoardLevel = { price: number; condition: string; interval: string | null; state: "armed" | "hit";
  distance_usd?: number; distance_pct?: number; hit_at?: number | null };
export type PlanBoardRow = {
  investigation_id: string; symbol: string; direction: "long" | "short" | null; thesis: string | null; last: number | null;
  entry: PlanBoardLevel | null; invalidation: PlanBoardLevel | null;
  time_stop: { text: string; due_at: number; state: string } | null;
  position: "in_position" | "closed" | "fill_to_link" | "waiting";
};
export type PlansBoard = { plans: PlanBoardRow[]; quotes_at: number | null; quote_issue: string | null };
export const getPlansBoard = (signal?: AbortSignal) => request<PlansBoard>("/copilot/plans", { signal });
/** A symbol's newest answered exit review (``copilot_plans.last_exit_lessons``): ``exited``, the New York date of the
 * plan's last exit; ``followed``, what the answer opens with; ``lesson``, the owner's own words. */
export type ExitLesson = { exited: string; followed: "yes" | "partly" | "no" | null; lesson: string };
/** The Charts dock's Copilot tab for one symbol (``GET /copilot/symbol/{symbol}``): its open positions with their plans
 * (the Dashboard Plans card's rows), its armed plans not yet in a position (the board's rows), and what is new on it.
 * A section whose source failed reads ``unavailable``; Radar reads ``off`` while it is not running. */
type LoopSection<T> = { state: "ok"; rows: T[] } | { state: "unavailable" };
export type SymbolLoop = {
  symbol: string; as_of: string;
  positions: LoopSection<PlanPosition>; plans: LoopSection<PlanBoardRow>;
  /** The symbol's newest answered exit review (null without one), for the plan card. */
  last_exit?: { state: "ok"; lesson: ExitLesson | null } | { state: "unavailable" };
  new: {
    radar: { state: "ok"; count: number; rows: { event_id: string; summary: string | null; first_seen_at: string }[] } | { state: "off" | "unavailable" };
    thesis: { state: "ok"; count: number; rows: { kind: string; text: string; fired_at: string | null }[] } | { state: "unavailable" };
  };
  quotes_at: number | null; quote_issue: string | null;
};
export const getSymbolLoop = (symbol: string, signal?: AbortSignal) => request<SymbolLoop>(`/copilot/symbol/${encodeURIComponent(symbol)}`, { signal });
/** The home's one button: a new conversation with no symbol and exactly this prompt. Never sent on open (a turn costs money). */
export const WHAT_MATTERS_PROMPT = "What matters right now across my open positions, armed watches and open investigations? Lead with anything that needs a decision today; say plainly if nothing does.";

// --------------------------------------------------------------------------- confirming a proposal

export type FreshQuote = { symbol: string; last: number | null; trade_time: number | null; fetched_at: number | null; age_s: number | null; issue: string | null; fresh: boolean };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), { cache: "no-store", ...init, headers: init?.body ? { "Content-Type": "application/json" } : undefined });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${response.status}).`);
  return body as T;
}

/** A spoken message as text, spoken tickers written as symbols: a clip for this server's transcriber (deleted once
 * read), or what the browser's own recognition heard. */
export type Transcribed = { text: string; heard: string; tickers: { heard: string; symbol: string }[]; provider: string };
export async function transcribeSpeech(input: { audio: Blob; ms: number } | { text: string }, signal?: AbortSignal): Promise<Transcribed> {
  const form = new FormData();
  if ("text" in input) form.append("text", input.text.slice(0, 4000));
  else {
    form.append("audio", input.audio, input.audio.type.includes("mp4") ? "clip.m4a" : "clip.webm");
    form.append("audio_ms", String(Math.round(input.ms)));
  }
  const response = await fetch(apiUrl("/copilot/transcribe"), { method: "POST", body: form, cache: "no-store", signal });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `Transcription failed (${response.status}).`);
  return body as Transcribed;
}

export const freshQuote = (symbol: string) => request<FreshQuote>(`/copilot/quote?symbol=${encodeURIComponent(symbol)}`);
export const enqueueRevisit = (investigationId: string, question: string, afterDays: number) =>
  request<{ job: ResearchJob; created: boolean; queue_enabled: boolean }>("/copilot/research-jobs/reassess",
    { method: "POST", body: JSON.stringify({ investigation_id: investigationId, question, after_days: afterDays }) });
/** A confirmed watch becomes an ordinary level alert, marked as coming from this investigation. */
export const createWatch = (investigationId: string, watch: Extract<Proposal, { kind: "watch" }>, reference: number) =>
  request<AlertsPayload>("/charts/alerts", { method: "POST", body: JSON.stringify({
    symbol: watch.symbol, price: watch.price, reference, condition: watch.condition, interval: watch.interval, session: "regular",
    source_kind: "copilot", source_id: investigationId, label: watch.label }) });
/** One of a confirmed plan's level alerts: an ordinary alert, marked as coming from this investigation, like a watch.
 * ``role`` says which level it is, so its phone message names the plan. */
export const createPlanAlert = (investigationId: string, symbol: string, level: PlanLevel, reference: number, label: string,
  role: PlanRole) =>
  request<AlertsPayload>("/charts/alerts", { method: "POST", body: JSON.stringify({
    symbol, price: level.price, reference, condition: level.condition, interval: level.interval, session: "regular",
    source_kind: "copilot", source_id: investigationId, label, plan_role: role }) });
export type PlanRole = "entry" | "invalidation";
/** When a plan card's time stop would ping (``due_at``, epoch seconds), or why it stays a note. ``enabled``: whether
 * this server sends time-stop pings (PLAN_TIME_STOPS_ENABLED). */
export type TimeStopPreview = { due_at: number; when: string; enabled: boolean } | { due_at: null; reason: string; enabled: boolean };
export type TimeStop = { id: string; symbol: string; text: string; due_at: number;
  delivery: "scheduled" | "pending" | "sending" | "sent" | "skipped" | "expired" | "unknown"; trade_id: string | null;
  error: string | null; delivered_at: number | null };
export type TimeStops = { time_stops: TimeStop[]; enabled: boolean };
export const previewTimeStop = (text: string, signal?: AbortSignal) =>
  request<TimeStopPreview>(`/copilot/time-stops/preview?text=${encodeURIComponent(text)}`, { signal });
/** ``clientId`` is the plan card's: a retried Confirm returns the first time stop. */
export const saveTimeStop = (clientId: string, investigationId: string, symbol: string, text: string) =>
  request<TimeStops>("/copilot/time-stops", { method: "POST", body: JSON.stringify({ client_id: clientId, investigation_id: investigationId, symbol, text }) });
export const listTimeStops = (investigationId: string, signal?: AbortSignal) =>
  request<TimeStops>(`/copilot/time-stops?investigation=${encodeURIComponent(investigationId)}`, { signal });
/** A confirmed plan is the owner's pre-trade plan: the existing capture route, discretionary, named "Copilot plan", so
 * capture linking suggests it for the trade when the fill arrives. ``clientId`` is minted once per card, so a retried
 * save returns the first plan instead of making a second. */
export const savePlanCapture = ({ investigation_id, ...body }: { client_id: string; underlying: string; account_id: string; side: CaptureSide;
  wording: string; note: string; investigation_id: string | null; origin: CaptureOrigin }) =>
  request<Capture>("/charts/captures", { method: "POST", body: JSON.stringify({
    ...body, client_captured_at: Date.now(), mode: "discretionary", setup_label: "Copilot plan",
    // The investigation rides in the context, so the one-tap link page can open it after linking.
    context: { state: "unavailable", reason: "Saved from a Copilot Lab plan card.", ...(investigation_id ? { investigation_id } : {}) }, image: false }) });
export const listAlerts = (signal?: AbortSignal) => request<AlertsPayload>("/charts/alerts", { signal });
/** A confirmed memory is saved through the existing Jo memory store as the owner's own statement (they edited and
 * confirmed the words), active at once, with the investigation it came from as its reference. */
export const operationId = () => typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
/** ``operation`` is minted once per card, so a Confirm retried after a lost response replays the same save instead of
 * writing a second memory (the store replays by operation id). */
export const saveMemory = (memory: Extract<Proposal, { kind: "memory" }>, text: string, investigationId: string | null, operation: string) =>
  request<{ id: string; memory_id: string; revision: number }>("/jo/memories", { method: "POST", body: JSON.stringify({
    operation_id: operation, kind: memory.memory_kind, symbol: memory.symbol, original_text: text,
    interpretation: memory.interpretation ?? null, source: "owner_statement",
    source_reference: investigationId ? `copilot:${investigationId}` : "copilot", status: "active", owner_confirmed: true }) });

// --------------------------------------------------------------------------- the practice goal (Review my week)

export type PracticeMeasure = "plan_before_entry" | "exit_at_invalidation" | "respond_to_giveback_15m" | "no_trade_after_hour_red"
  | "no_opening_while_green" | "max_trades_per_day";
/** One week of a goal's measure: ``hit`` of ``of`` (``text``, "2 of 3"), and whether it met the target (null without one). */
export type PracticeScore = { week_start: string; hit: number; of: number; text: string; of_what: string; share: number | null;
  met: boolean | null; source?: string };
export type PracticeGoal = { text: string; measure: PracticeMeasure; label: string; target: number | null; week_start: string; since: string };
/** ``this_week`` is null until the goal's first week starts. ``proposed`` (only when read for an investigation): the
 * practice card an automatic week review saved there, until it is confirmed. */
export type PracticeNow = { goal: PracticeGoal | null; this_week: PracticeScore | null; proposed?: Proposal | null };
export const getPractice = (signal?: AbortSignal, investigation?: string) =>
  request<PracticeNow>(`/copilot/practice${investigation ? `?investigation=${encodeURIComponent(investigation)}` : ""}`, { signal });
/** The automatic week review's saved investigations (``backend/app/engine/week_review_auto.py``) are titled this way. */
export const AUTO_WEEK_REVIEW_TITLE = "Week review ";
/** Confirming a practice card makes it the one active goal; the previous one ends. */
export const savePractice = (body: { text: string; measure: PracticeMeasure; target: number | null; investigation_id: string | null }) =>
  request<PracticeNow>("/copilot/practice", { method: "POST", body: JSON.stringify(body) });
/** "Practicing: exit at my invalidation · 2 of 3 this week" (or when it starts). */
export function practiceLine({ goal, this_week }: PracticeNow): string | null {
  if (!goal) return null;
  const starts = new Date(`${goal.week_start}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", weekday: "short", month: "short", day: "numeric" });
  return `Practicing: ${goal.label} · ${this_week ? `${this_week.text} this week` : `starts ${starts}`}`;
}
