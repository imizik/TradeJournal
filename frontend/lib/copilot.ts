import { apiUrl } from "./api";
import type { AlertsPayload } from "./alerts";

export type CopilotStatus =
  | { enabled: false; reason: string }
  | { enabled: true; backend: "fake" | "anthropic" | "plan"; evidence: "fixture" | "live" | "replay"; model: string; effort: string;
      replay?: { at: string; session: string; passes_before: number; last_pass_at: string } | { error: string };
      fallbacks: boolean; key_configured: boolean; plan_configured: boolean; tools: string[];
      /** copilot_alerts: whether the level-alert route accepts a watch confirmed here. */
      capabilities?: { copilot_alerts: boolean };
      limits: { max_rounds: number; max_tool_calls: number; tool_timeout_s: number; turn_timeout_s: number } };

export type ToolEvent = {
  type: "tool"; id: string; name: string; status: "running" | "ok" | "error"; input?: Record<string, unknown>;
  summary?: string; ms?: number; provenance?: { source: string; kind: "recorded" | "fetched" | "cached" | "simulated" | "replay" | "saved" | "proposal"; as_of: string | number | null; state?: string | null };
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

/** A step the model proposed (propose_plan). It is only a card: nothing exists until the owner confirms it. */
export type Proposal = { id: string } & (
  | { kind: "watch"; symbol: string; condition: "touches" | "crosses" | "closes_beyond"; price: number; interval: string | null;
      label: string; why: string; last?: number; as_of?: string | number | null }
  | { kind: "revisit"; question: string; horizon_days: number }
  | { kind: "memory"; memory_kind: "statement" | "thesis" | "preference" | "lesson"; symbol: string | null; text: string; interpretation?: string });

export type LabMessage = { role: "user" | "assistant"; content: string; progress?: string; proposals?: Proposal[]; tools?: ToolEvent[]; error?: { code: string; message: string }; metrics?: TurnMetrics };

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
export async function streamTurn(history: { role: "user" | "assistant"; content: string }[], symbol: string | null,
  onEvent: (event: CopilotEvent) => void, signal: AbortSignal) {
  const response = await fetch(apiUrl("/copilot/chat"), {
    method: "POST", headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ messages: history, symbol }), signal, cache: "no-store",
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
  transcript: { role: "user" | "assistant"; content: string }[]; evidence: EvidenceRef[]; findings: Findings | null;
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

/** What is saved: the text of each message and, per answer, which tools it used and how old their data was.
 * A proposal is not evidence, so propose_plan is left out. */
export function toSaved(messages: LabMessage[]): Pick<InvestigationFields, "transcript" | "evidence"> {
  return {
    transcript: messages.map(m => ({ role: m.role, content: m.content })),
    evidence: messages.flatMap((m, i) => (m.tools ?? []).filter(t => t.status === "ok" && t.provenance && t.name !== "propose_plan")
      .map(t => ({ tool: t.name, as_of: t.provenance!.as_of, kind: t.provenance!.kind, message: i }))),
  };
}

export function fromSaved(saved: Investigation): LabMessage[] {
  return saved.transcript.map((m, i) => ({ ...m, tools: saved.evidence.filter(e => e.message === i).map((e, j) => ({
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

export function copilotLabHref(symbol: string, context?: string) {
  const query = new URLSearchParams({ symbol: symbol.toUpperCase() });
  if (context?.trim()) query.set("context", context.trim().slice(0, CONTEXT_MAX));
  return `/copilot-lab?${query}`;
}

/** The deep link's values, or null when there is none; an invalid symbol is dropped. */
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** The deep link's values, or null when there is none. `investigation` opens that saved investigation. */
export function readDeepLink(params: { symbol?: string | string[]; context?: string | string[]; investigation?: string | string[] }) {
  const one = (value?: string | string[]) => (Array.isArray(value) ? value[0] : value) ?? "";
  const symbol = one(params.symbol).trim().toUpperCase();
  const context = one(params.context).replace(/\s+/g, " ").trim().slice(0, CONTEXT_MAX);
  const investigation = one(params.investigation).trim();
  if (UUID_RE.test(investigation)) return { symbol: "", context: "", investigation: investigation.toLowerCase() };
  if (!symbol && !context) return null;
  return { symbol: SYMBOL_RE.test(symbol) ? symbol : "", context, investigation: null };
}

// --------------------------------------------------------------------------- research queue

export type ResearchJob = {
  id: string; kind: "question" | "radar_event" | "reassess"; status: "queued" | "running" | "done" | "failed" | "cancelled";
  input: { question?: string; symbols?: string[]; from_investigation?: string; investigation_id?: string };
  attempts: number; error: string | null; cost_usd: number | null; investigation_id: string | null;
  created_at: string; next_attempt_at?: string; finished_at: string | null;
  /** Set when a job finishes done: was it material, and what happened to its phone ping. */
  notify?: { material_change: boolean; material_reason: string; status: "sent" | "sending" | "skipped" | "failed";
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
export type ThreadInvestigation = { id: string; source: "copilot" | "research_job"; symbol?: string; title: string; status: string; conclusion?: string; updated_at: string };
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

export const freshQuote = (symbol: string) => request<FreshQuote>(`/copilot/quote?symbol=${encodeURIComponent(symbol)}`);
export const enqueueRevisit = (investigationId: string, question: string, afterDays: number) =>
  request<{ job: ResearchJob; created: boolean; queue_enabled: boolean }>("/copilot/research-jobs/reassess",
    { method: "POST", body: JSON.stringify({ investigation_id: investigationId, question, after_days: afterDays }) });
/** A confirmed watch becomes an ordinary level alert, marked as coming from this investigation. */
export const createWatch = (investigationId: string, watch: Extract<Proposal, { kind: "watch" }>, reference: number) =>
  request<AlertsPayload>("/charts/alerts", { method: "POST", body: JSON.stringify({
    symbol: watch.symbol, price: watch.price, reference, condition: watch.condition, interval: watch.interval, session: "regular",
    source_kind: "copilot", source_id: investigationId, label: watch.label }) });
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
