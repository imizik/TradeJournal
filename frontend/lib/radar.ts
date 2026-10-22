import { apiUrl } from "./api";

export type RadarRating = "useful" | "already_knew" | "too_late" | "irrelevant";
export const RATINGS: { value: RadarRating; label: string }[] = [
  { value: "useful", label: "Useful" },
  { value: "already_knew", label: "Already knew" },
  { value: "too_late", label: "Too late" },
  { value: "irrelevant", label: "Irrelevant" },
];

export type RadarEvidence = { symbol: string; pass_id: number; retrieved_at: string; last: number; change_pct: number };
export type RadarEvent = {
  event_id: string; session_date: string; rule_version: string; universe_version: string;
  kind: "relative_to_spy" | "relative_to_sector" | "group_move"; direction: "up" | "down";
  symbols: string[]; benchmark: string; group: string | null; first_seen_at: string; summary: string;
  measures: Record<string, number>; evidence: RadarEvidence[];
  coverage: { passes_expected: number; passes_recorded: number; symbols_missing: string[] };
  chart: Record<string, string>;
};
export type RadarRevision = {
  event_id: string; revision: number; recorded_at: string; status: "extended" | "faded" | "reversed" | "corrected";
  measures: Record<string, number>; evidence: RadarEvidence[]; note: string;
};
export type RadarFeedEvent = RadarEvent & { latest_status: RadarRevision["status"] | null; revision_count: number; rating: RadarRating | null };
export type RadarCoverage = {
  passes_recorded: number; passes_expected: number; passes_failed: number; last_ok_pass_at: string | null;
  symbols_tracked: number; symbols_missing: string[]; universe_version: string; live: boolean;
};
export type RadarFeed = {
  state: "off" | "no_data" | "recording" | "stale"; reason: string | null; session: string | null; sessions?: string[];
  events: RadarFeedEvent[]; since_last_visit: string[]; last_visit_at: string | null; coverage: RadarCoverage | null; generated_at: string | null;
};
export type RadarDetail = { event: RadarEvent; revisions: RadarRevision[]; rating: RadarRating | null };

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(`/radar${path}`), { cache: "no-store", ...init });
  if (!response.ok) throw new Error("Radar could not be reached.");
  return response.json();
}

export const getFeed = (session?: string, since?: string | null, signal?: AbortSignal) => {
  const query = new URLSearchParams();
  if (session) query.set("session", session);
  if (since) query.set("since", since);
  return call<RadarFeed>(`/feed${query.size ? `?${query}` : ""}`, { signal });
};
export const getEvent = (id: string) => call<RadarDetail>(`/events/${encodeURIComponent(id)}`);
export const recordVisit = (visitedAt?: string | null) =>
  call<{ visited_at: string; previous_visit_at: string | null }>("/visits", {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(visitedAt ? { visited_at: visitedAt } : {}),
  });
export const rateEvent = (id: string, rating: RadarRating) =>
  call<{ rating: RadarRating }>(`/events/${encodeURIComponent(id)}/feedback`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ rating }),
  });

const NY = "America/New_York";
export const nyTime = (iso: string, seconds = false) =>
  new Date(iso).toLocaleTimeString("en-US", { timeZone: NY, hour: "numeric", minute: "2-digit", ...(seconds ? { second: "2-digit" } : {}) });

export const MEASURE_LABELS: Record<string, string> = {
  change_pct: "Change", benchmark_change_pct: "Benchmark change", relative_pct: "Ahead / behind", volume_ratio: "Volume vs usual",
};
export function measureText(key: string, value: number) {
  if (key === "volume_ratio") return `${value.toFixed(1)}×`;
  if (key.endsWith("_pct")) return `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(1)}%`;
  return String(value);
}

export const STATUS_TEXT: Record<RadarRevision["status"], string> = {
  extended: "Extended", faded: "Faded", reversed: "Reversed", corrected: "Corrected",
};

/** The one-line recording status shown above the feed. */
export function coverageLine(feed: RadarFeed): string {
  const c = feed.coverage;
  if (feed.state === "off") return feed.reason ? `Radar is off. ${feed.reason}` : "Radar is off.";
  if (feed.state === "no_data" || !c) return "No recorded session yet.";
  const missing = c.symbols_missing.length ? ` · ${c.symbols_missing.length} missing` : "";
  const passes = `${c.passes_recorded} of ${c.passes_expected} passes`;
  const last = c.last_ok_pass_at ? nyTime(c.last_ok_pass_at, true) : "none";
  if (feed.state === "stale") return `Stale since ${c.last_ok_pass_at ? nyTime(c.last_ok_pass_at) : "the open"} · ${passes}${missing}`;
  return `${c.live ? "Recording" : "Recorded"} · ${c.symbols_tracked} symbols · last pass ${last} · ${passes}${missing}`;
}
