import type { TradingViewSnapshotValue, TradingViewVerdict } from "@/lib/api";
import { timeET } from "@/lib/format";

export function fmtAlertTime(value: string): string {
  return timeET(value, { year: true, seconds: true });
}

export function verdictLabel(verdict: TradingViewVerdict | null): string {
  if (!verdict) return "—";
  return verdict.replace(/_/g, " ");
}

export function verdictClasses(verdict: TradingViewVerdict | null): string {
  return verdict === "long_scalp" || verdict === "short_scalp" ? "bg-primary/15 text-primary" : "bg-secondary text-muted-foreground";
}

export function statusClasses(status: string): string {
  return status === "error" ? "bg-red-500/15 text-red-400" : "bg-secondary text-muted-foreground";
}

/** Snapshot scalars keep their exact source text; render it without coercing. */
export function snapshotText(value: TradingViewSnapshotValue): string {
  if (value.type === "null" || value.value === null) return "—";
  if (value.type === "boolean") return value.value ? "yes" : "no";
  return String(value.value);
}

/**
 * Postgres NUMERIC pads to the column scale, so a price stored as 268.4321
 * reads back as "268.432100000000". Trim for display at the string level:
 * parsing to a float to reformat would defeat storing it as exact text.
 */
export function fmtDecimal(value: string): string {
  if (!value.includes(".")) return value;
  const trimmed = value.replace(/0+$/, "").replace(/\.$/, "");
  return trimmed === "" || trimmed === "-" ? value : trimmed;
}

export function fmtScore(score: number | null | undefined): string {
  return score == null ? "—" : String(Math.round(score));
}
