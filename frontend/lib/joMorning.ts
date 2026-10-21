import { apiUrl } from "./api";

export type BriefEvidence = { id: string; kind: "fact" | "belief" | "estimate"; text: string; source: string; observed_at: string | null; retrieved_at: string };
/** An exact saved memory revision a packet referenced; later corrections do not replace it. */
export type BriefMemory = { id: string; memory_id: string; revision: number; status: string; symbol: string | null; received_at: string; redacted_at: string | null;
  body: { kind?: MemoryKind; original_text?: string; interpretation?: string | null; source?: MemorySource; source_reference?: string | null } };
export type MemoryKind = "statement" | "thesis" | "preference" | "lesson";
export type MemorySource = "owner_statement" | "owner_import" | "jo_proposal";
export type MemoryStatus = "proposed" | "active" | "retired";
export type MemorySave = { operation_id: string; memory_id?: string; base_revision?: number; kind: MemoryKind; symbol: string | null; original_text: string;
  interpretation: string | null; source: MemorySource; source_reference?: string | null; status: MemoryStatus; owner_confirmed: boolean };
export type BriefItem = { symbol: string | null; what_matters: string; why_personal: string; what_changed: string; contrary_evidence: string; watch_out: string; evidence_ids: string[] };
export type BriefOpportunity = BriefItem & { status: "conditional" | "research_only"; entry_trigger: string; invalidation: string; timeframe: string };
export type WatchdogNotice = { kind: string; title: string; recovered: boolean; outcome: "sent" | "failed" | "unknown"; at: string; attempts?: number };
/** The scheduled obligation for a date: judged on when the brief reached the journal. Origin is never observed. */
export type MorningDelivery = {
  calendar: string; publication: "published" | "missing" | "pending" | "not_expected" | "unknown";
  fulfilment: "on_time" | "late" | "missing" | "pending" | "not_expected" | "unknown";
  deadline: string | null; publish_at: string | null; packet_id: string | null; published_at: string | null;
  briefing_id: string | null; available_at: string | null; submitted_at: string | null;
  import_lag_seconds: number | null; late_by_seconds: number | null; origin: "unknown"; other_briefings: number;
  context_read?: "recorded" | "not_recorded" | "unknown"; context_read_at?: string | null;
  notifications: { chatgpt: "not_observable"; watchdog: { state: "on" | "off" | "unknown"; checked_at: string | null; notices: WatchdogNotice[] } | null };
};
/** One weekday of the month calendar's briefing marks (``GET /jo/morning?month=``). */
export type MorningMonthDay = { day: string; publication: MorningDelivery["publication"]; fulfilment: MorningDelivery["fulfilment"];
  deadline: string | null; available_at: string | null; late_by_seconds: number | null; watchdog_notices: WatchdogNotice[] };
export type MorningMonth = { month: string; checked_at: string; configuration_error: boolean; days: MorningMonthDay[] };
export type MorningView = {
  day: string; state: "ready" | "waiting" | "missing" | "unavailable" | "redacted" | "closed";
  late: boolean; stale: boolean; archived: boolean; deadline: string | null; checked_at: string;
  automation: { enabled: boolean; last_pass: string | null; unavailable: boolean; configuration_error?: boolean; last_status?: string | null;
    pending?: { count: number; oldest_submitted_at: string | null; unreadable: number } | null };
  delivery?: MorningDelivery;
  packet: { id: string; redacted_at: string | null; memories?: BriefMemory[]; body: { as_of?: string; scope?: string; gaps?: string[]; evidence?: BriefEvidence[]; memory_revision_ids?: string[] } } | null;
  briefing: { id: string; received_at: string; redacted_at: string | null; body: { prompt_version?: string; opportunities?: BriefOpportunity[]; urgent_positions?: BriefItem[]; summary?: string; summary_evidence_ids?: string[]; items?: BriefItem[]; limitations?: string[]; supersedes_id?: string | null } } | null;
  versions: { id: string; received_at: string; redacted: boolean }[];
  feedback: { rating: "useful" | "meh" | "missed" | null; first_opened_at: string | null };
};

export async function getMorning(day: string, id: string | null, signal?: AbortSignal): Promise<MorningView> {
  const query = new URLSearchParams({ day });
  if (id) query.set("briefing_id", id);
  const response = await fetch(apiUrl(`/jo/morning?${query}`), { cache: "no-store", signal });
  if (!response.ok) throw new Error("The briefing could not load. Your saved records have not changed.");
  return response.json();
}

export async function saveBriefFeedback(id: string, body: { opened?: boolean; rating?: "useful" | "meh" | "missed" }): Promise<MorningView["feedback"]> {
  const response = await fetch(apiUrl(`/jo/briefings/${id}/feedback`), { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!response.ok) throw new Error("Feedback was not saved. Please retry.");
  return response.json();
}

/** Latest revision of each memory with this status. */
export async function listMemories(status: MemoryStatus | "retired", signal?: AbortSignal): Promise<{ items: BriefMemory[]; limit: number }> {
  const response = await fetch(apiUrl(`/jo/memories?status=${status}&limit=100`), { cache: "no-store", signal });
  if (!response.ok) throw new Error("Saved memories could not load. Nothing was changed.");
  return response.json();
}

export class MemorySaveError extends Error { constructor(message: string, readonly status: number) { super(message); } }

/** Appends one owner-confirmed revision. A 409 means the memory changed since it was loaded. */
export async function saveMemory(body: MemorySave): Promise<BriefMemory> {
  let response: Response;
  try {
    response = await fetch(apiUrl("/jo/memories"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  } catch {
    throw new Error("Couldn’t reach the app, so it’s unknown whether this saved. The list has been reloaded; check it before saving again. An unchanged retry cannot save twice.");
  }
  if (response.ok) return response.json();
  const detail = await response.json().then((body) => typeof body?.detail === "string" ? body.detail : "", () => "");
  const message = response.status === 409 && detail.startsWith("Operation ID") ? "This retry did not match the earlier attempt. The list has been reloaded; check whether the first version saved."
    : response.status === 409 ? "This memory changed since the page loaded. The list has been reloaded; check it and try again."
    : response.status === 422 ? "The app refused this memory as invalid. Check the wording and symbol."
    : response.status >= 500 ? "The app had an error, so it’s unknown whether this saved. The list has been reloaded; check it before saving again. An unchanged retry cannot save twice."
    : `Not saved (error ${response.status}).`;
  throw new MemorySaveError(message, response.status);
}
