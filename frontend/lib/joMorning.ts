import { apiUrl } from "./api";

export type BriefEvidence = { id: string; kind: "fact" | "belief" | "estimate"; text: string; source: string; observed_at: string | null; retrieved_at: string };
/** An exact saved memory revision a packet referenced; later corrections do not replace it. */
export type BriefMemory = { id: string; memory_id: string; revision: number; status: string; symbol: string | null; received_at: string; redacted_at: string | null;
  body: { kind?: "statement" | "thesis" | "preference" | "lesson"; original_text?: string; interpretation?: string | null; source?: string } };
export type BriefItem = { symbol: string | null; what_matters: string; why_personal: string; what_changed: string; contrary_evidence: string; watch_out: string; evidence_ids: string[] };
export type MorningView = {
  day: string; state: "ready" | "waiting" | "missing" | "unavailable" | "redacted" | "closed";
  late: boolean; stale: boolean; archived: boolean; deadline: string | null; checked_at: string;
  automation: { enabled: boolean; last_pass: string | null; unavailable: boolean };
  packet: { id: string; redacted_at: string | null; memories?: BriefMemory[]; body: { as_of?: string; scope?: string; gaps?: string[]; evidence?: BriefEvidence[]; memory_revision_ids?: string[] } } | null;
  briefing: { id: string; received_at: string; redacted_at: string | null; body: { summary?: string; summary_evidence_ids?: string[]; items?: BriefItem[]; limitations?: string[]; supersedes_id?: string | null } } | null;
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
