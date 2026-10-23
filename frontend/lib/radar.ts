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
export type RadarHeadline = {
  headline: string; source: string | null; published_at: string; url: string; symbols: string[]; timing: "before" | "after";
};
export type RadarNews = { status: "found" | "none_found" | "unavailable"; checked_at: string; headlines: RadarHeadline[] };
export type RadarFeedEvent = RadarEvent & {
  latest_status: RadarRevision["status"] | null; revision_count: number; rating: RadarRating | null; news: RadarNews | null;
};
export type RadarCoverage = {
  passes_recorded: number; passes_expected: number; passes_failed: number; last_ok_pass_at: string | null;
  symbols_tracked: number; symbols_missing: string[]; universe_version: string; live: boolean;
};
export type RadarFeed = {
  state: "off" | "no_data" | "recording" | "stale"; reason: string | null; session: string | null; sessions?: string[];
  events: RadarFeedEvent[]; since_last_visit: string[]; last_visit_at: string | null; coverage: RadarCoverage | null; generated_at: string | null;
};
export type RadarDetail = {
  event: RadarEvent; revisions: RadarRevision[]; rating: RadarRating | null; news: RadarNews | null; news_checks: RadarNews[];
};

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

export const TIMING_TEXT: Record<RadarHeadline["timing"], string> = { before: "before the move", after: "after the move" };

/** "Source · 10:05 AM (before the move)"; the time is the day and time when it is not the event's session. */
export function headlineMeta(h: RadarHeadline, sessionDate: string): string {
  const day = new Intl.DateTimeFormat("en-CA", { timeZone: NY }).format(new Date(h.published_at));
  const when = day === sessionDate
    ? nyTime(h.published_at)
    : `${new Date(h.published_at).toLocaleDateString("en-US", { timeZone: NY, month: "short", day: "numeric" })} ${nyTime(h.published_at)}`;
  return `${h.source ? `${h.source} · ` : ""}${when} (${TIMING_TEXT[h.timing]})`;
}

/** The quiet news line on a card. It never says the news caused the move. */
export function newsLine(news: RadarNews | null, sessionDate: string): string {
  if (!news) return "News not checked yet";
  if (news.status === "unavailable") return "News unavailable — cause unknown";
  const first = news.headlines[0];
  if (news.status === "none_found" || !first) return "No news found — cause unknown";
  return `News nearby: ${first.headline} · ${headlineMeta(first, sessionDate)}`;
}

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

export type RadarGroup = { name: string; members: string[] };
export type GroupEndpoint = { price: number; retrieved_at: string; trade_at: string };
export type GroupComparison = {
  session_context?: GroupComparison;
  symbol: string; state: "off" | "ungrouped" | "insufficient" | "partial" | "stale" | "ready";
  reason: string | null; groups: RadarGroup[]; group: RadarGroup | null; universe_version: string;
  source: string; methodology: string; window_minutes: number | null; session: string | null; live: boolean; generated_at: string;
  window: { start: string; end: string; start_pass_id: number; end_pass_id: number } | null;
  rows: { symbol: string; role: "selected" | "peer" | "benchmark"; change_pct: number | null;
    reason: string | null; start: GroupEndpoint | null; end: GroupEndpoint | null }[];
  coverage: { peers_total: number; peers_available: number; peers_up: number; peers_down: number; missing: string[]; recorded_minutes: number; expected_minutes: number } | null;
};
export function getGroupComparison(symbol: string, group?: string, signal?: AbortSignal) {
  const query = new URLSearchParams({ symbol });
  if (group) query.set("group", group);
  return call<GroupComparison>(`/groups/compare?${query}`, { signal });
}
