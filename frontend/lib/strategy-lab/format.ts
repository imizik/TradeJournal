import type { DecimalString } from "./types";

const EMPTY_VALUE = "—";

export function decimalToNumber(
  value: DecimalString | null | undefined,
): number | null {
  if (value == null || value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function formatDecimal(
  value: DecimalString | null | undefined,
  maximumFractionDigits = 2,
): string {
  const parsed = decimalToNumber(value);
  if (parsed == null) return EMPTY_VALUE;
  return new Intl.NumberFormat(undefined, {
    maximumFractionDigits,
  }).format(parsed);
}

export function formatMoney(
  value: DecimalString | null | undefined,
  currency = "USD",
  maximumFractionDigits = 2,
): string {
  const parsed = decimalToNumber(value);
  if (parsed == null) return EMPTY_VALUE;
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      minimumFractionDigits: Math.min(2, maximumFractionDigits),
      maximumFractionDigits,
    }).format(parsed);
  } catch {
    return `${currency} ${formatDecimal(value, maximumFractionDigits)}`;
  }
}

export function formatPercentPoints(
  value: DecimalString | null | undefined,
  maximumFractionDigits = 1,
): string {
  const parsed = decimalToNumber(value);
  if (parsed == null) return EMPTY_VALUE;
  return `${new Intl.NumberFormat(undefined, { maximumFractionDigits }).format(parsed)}%`;
}

export function formatWinRate(
  value: DecimalString | null | undefined,
  maximumFractionDigits = 1,
): string {
  const parsed = decimalToNumber(value);
  if (parsed == null) return EMPTY_VALUE;
  return new Intl.NumberFormat(undefined, {
    style: "percent",
    maximumFractionDigits,
  }).format(parsed);
}

export function formatDurationMinutes(
  value: DecimalString | number | null | undefined,
): string {
  if (value == null || value === "") return EMPTY_VALUE;
  const minutes = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(minutes)) return EMPTY_VALUE;
  if (minutes < 60) return `${formatCompactNumber(minutes)}m`;

  const hours = Math.floor(minutes / 60);
  const remaining = Math.round(minutes - hours * 60);
  return remaining ? `${hours}h ${remaining}m` : `${hours}h`;
}

function formatCompactNumber(value: number): string {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(value);
}

function utcDate(value: string | null | undefined): Date | null {
  if (!value?.trim()) return null;
  const trimmed = value.trim();
  const hasExplicitZone = /(?:z|[+-]\d{2}:?\d{2})$/i.test(trimmed);
  const parsed = new Date(hasExplicitZone ? trimmed : `${trimmed}Z`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function formatStrategyDateTime(
  value: string | null | undefined,
  sourceTimezone: string,
  options: Intl.DateTimeFormatOptions = {},
): string {
  const parsed = utcDate(value);
  if (!parsed) return EMPTY_VALUE;

  const defaults: Intl.DateTimeFormatOptions = {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  };

  try {
    return new Intl.DateTimeFormat(undefined, {
      ...defaults,
      ...options,
      timeZone: sourceTimezone,
    }).format(parsed);
  } catch {
    return new Intl.DateTimeFormat(undefined, {
      ...defaults,
      ...options,
      timeZone: "UTC",
    }).format(parsed);
  }
}

export function formatStrategyDate(value: string | null | undefined): string {
  if (!value?.trim()) return EMPTY_VALUE;
  const parsed = new Date(`${value.trim()}T12:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(parsed);
}
