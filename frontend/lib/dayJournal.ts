import type { DayJournalEntry, DayJournalWrite, DayTradePlan } from "@/lib/api";

export const DAY_JOURNAL_KINDS = [
  ["outlook", "Morning plan"],
  ["update", "Daytime thought"],
  ["idea", "Idea"],
  ["reflection", "End-of-day reflection"],
] as const;

export type SavedDraft = { write: DayJournalWrite; attempted: boolean };

export function draftStorageKey(day: string) {
  return `tradejournal:day-journal:draft:${day}`;
}

export function readDraft(day: string): SavedDraft | null {
  try {
    const raw = localStorage.getItem(draftStorageKey(day));
    if (!raw) return null;
    const value = JSON.parse(raw) as SavedDraft;
    if (typeof value.write?.operation_id !== "string" || typeof value.write.text !== "string") return null;
    return value;
  } catch {
    return null;
  }
}

export function storeDraft(day: string, draft: SavedDraft | null) {
  try {
    if (draft) localStorage.setItem(draftStorageKey(day), JSON.stringify(draft));
    else localStorage.removeItem(draftStorageKey(day));
    return true;
  } catch {
    return false;
  }
}

export function timestampET(value: string) {
  const local = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})$/.exec(value);
  if (local) {
    const [, year, month, day, hourText, minute] = local;
    const hour = Number(hourText);
    const date = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
    return `${date.toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric", year: "numeric" })}, ${hour % 12 || 12}:${minute} ${hour >= 12 ? "PM" : "AM"} ET`;
  }
  return new Date(value).toLocaleString("en-US", {
    timeZone: "America/New_York", month: "short", day: "numeric", year: "numeric",
    hour: "numeric", minute: "2-digit", timeZoneName: "short",
  });
}

export function dateET(value: string) {
  const local = /^(\d{4})-(\d{2})-(\d{2}) /.exec(value);
  if (local) return `${local[1]}-${local[2]}-${local[3]}`;
  return new Date(value).toLocaleDateString("en-CA", { timeZone: "America/New_York" });
}

export function chartPathLink(symbol: string, day: string) {
  const noon = new Date(`${day}T12:00:00Z`);
  const offsetLabel = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", timeZoneName: "shortOffset" })
    .formatToParts(noon).find((part) => part.type === "timeZoneName")?.value ?? "GMT-5";
  const match = /^GMT([+-])(\d{1,2})(?::(\d{2}))?$/.exec(offsetLabel);
  const offsetMinutes = match ? (match[1] === "+" ? 1 : -1) * (Number(match[2]) * 60 + Number(match[3] ?? 0)) : -300;
  const midnight = Date.parse(`${day}T00:00:00Z`);
  const from = Math.floor((midnight + 4 * 60 * 60_000 - offsetMinutes * 60_000) / 1000);
  const to = Math.floor((midnight + 20 * 60 * 60_000 - offsetMinutes * 60_000) / 1000);
  return `/charts?${new URLSearchParams({ symbol: symbol.toUpperCase(), from: String(from), to: String(to) })}`;
}

export function kindLabel(kind: DayJournalEntry["kind"]) {
  // ``decision`` is logged from the Copilot desk's decision bar, never added here, so it has a label but no button.
  if (kind === "decision") return "Decision after an alert";
  // ``horizon`` and ``plan_ask`` are the desk's check-ins (a plan card, the thread header, "Want a plan for this?").
  if (kind === "horizon") return "Horizon";
  if (kind === "plan_ask") return "Plan question";
  return DAY_JOURNAL_KINDS.find(([value]) => value === kind)?.[1] ?? kind;
}

export function planText(plan: DayTradePlan) {
  return [plan.setup, plan.plan, plan.note].filter((part): part is string => typeof part === "string" && !!part.trim()).join(" · ");
}
