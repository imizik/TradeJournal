import { apiUrl } from "./api";

export type CopilotStatus =
  | { enabled: false; reason: string }
  | { enabled: true; backend: "fake" | "anthropic" | "plan"; evidence: "fixture" | "live" | "replay"; model: string; effort: string;
      replay?: { at: string; session: string; passes_before: number; last_pass_at: string } | { error: string };
      fallbacks: boolean; key_configured: boolean; plan_configured: boolean; tools: string[];
      limits: { max_rounds: number; max_tool_calls: number; tool_timeout_s: number; turn_timeout_s: number } };

export type ToolEvent = {
  type: "tool"; id: string; name: string; status: "running" | "ok" | "error"; input?: Record<string, unknown>;
  summary?: string; ms?: number; provenance?: { source: string; kind: "recorded" | "fetched" | "cached" | "simulated" | "replay" | "saved"; as_of: string | number | null; state?: string | null };
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
  | { type: "error"; code: string; message: string }
  | { type: "done"; metrics: TurnMetrics };

export type LabMessage = { role: "user" | "assistant"; content: string; progress?: string; tools?: ToolEvent[]; error?: { code: string; message: string }; metrics?: TurnMetrics };

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

export const listInvestigations = () => investigationRequest<{ investigations: InvestigationSummary[] }>("?limit=8").then(r => r.investigations);
export const getInvestigation = (id: string) => investigationRequest<Investigation>(`/${encodeURIComponent(id)}`);
export const createInvestigation = (fields: InvestigationFields) =>
  investigationRequest<Investigation>("", { method: "POST", body: JSON.stringify(fields) });
export const updateInvestigation = (id: string, revision: number, fields: InvestigationFields) =>
  investigationRequest<Investigation>(`/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify({ ...fields, revision }) });

/** What is saved: the text of each message and, per answer, which tools it used and how old their data was. */
export function toSaved(messages: LabMessage[]): Pick<InvestigationFields, "transcript" | "evidence"> {
  return {
    transcript: messages.map(m => ({ role: m.role, content: m.content })),
    evidence: messages.flatMap((m, i) => (m.tools ?? []).filter(t => t.status === "ok" && t.provenance)
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
export function copilotLabHref(symbol: string, context?: string) {
  const query = new URLSearchParams({ symbol: symbol.toUpperCase() });
  if (context?.trim()) query.set("context", context.trim().slice(0, CONTEXT_MAX));
  return `/copilot-lab?${query}`;
}

/** The deep link's values, or null when there is none; an invalid symbol is dropped. */
export function readDeepLink(params: { symbol?: string | string[]; context?: string | string[] }) {
  const one = (value?: string | string[]) => (Array.isArray(value) ? value[0] : value) ?? "";
  const symbol = one(params.symbol).trim().toUpperCase();
  const context = one(params.context).replace(/\s+/g, " ").trim().slice(0, CONTEXT_MAX);
  if (!symbol && !context) return null;
  return { symbol: SYMBOL_RE.test(symbol) ? symbol : "", context };
}

// --------------------------------------------------------------------------- research queue

export type ResearchJob = {
  id: string; kind: "question" | "radar_event" | "reassess"; status: "queued" | "running" | "done" | "failed" | "cancelled";
  input: { question?: string; symbols?: string[]; from_investigation?: string };
  attempts: number; error: string | null; cost_usd: number | null; investigation_id: string | null;
  created_at: string; finished_at: string | null;
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

export const listResearchJobs = (signal?: AbortSignal) => queueRequest<ResearchJobs>("?limit=50", { signal });
export const enqueueResearch = (question: string, symbols: string[], investigationId: string) =>
  queueRequest<{ job: ResearchJob; created: boolean; queue_enabled: boolean }>("", { method: "POST",
    body: JSON.stringify({ question, symbols, investigation_id: investigationId }) });
