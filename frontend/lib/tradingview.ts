import type { TradingViewSnapshotValue, TradingViewVerdict } from "@/lib/api";

/**
 * Backend datetimes are UTC-naive by repository convention, so they carry no
 * offset and `new Date(...)` would read them as local time.
 */
export function parseUtcNaive(value: string): Date {
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value);
  return new Date(hasZone ? value : `${value}Z`);
}

export function fmtAlertTime(value: string): string {
  return parseUtcNaive(value).toLocaleString();
}

export function verdictLabel(verdict: TradingViewVerdict | null): string {
  if (!verdict) return "—";
  return verdict.replace(/_/g, " ");
}

export function verdictClasses(verdict: TradingViewVerdict | null): string {
  switch (verdict) {
    case "long_scalp":
      return "bg-emerald-500/15 text-emerald-400";
    case "short_scalp":
      return "bg-sky-500/15 text-sky-400";
    case "wait":
      return "bg-amber-500/15 text-amber-400";
    case "no_trade":
      return "bg-red-500/15 text-red-400";
    default:
      return "bg-secondary text-muted-foreground";
  }
}

export function statusClasses(status: string): string {
  switch (status) {
    case "done":
      return "bg-emerald-500/15 text-emerald-400";
    case "pending":
    case "running":
      return "bg-sky-500/15 text-sky-400";
    case "skipped":
      return "bg-amber-500/15 text-amber-400";
    case "error":
      return "bg-red-500/15 text-red-400";
    default:
      return "bg-secondary text-muted-foreground";
  }
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
