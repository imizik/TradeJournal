/**
 * Money as the app writes it everywhere: the sign before the dollar sign and
 * thousands separated ("-$3,199", "+$1,821.82", "$11,836.00"). A missing value
 * is an em dash.
 */
export function money(value: number | null | undefined, { signed = false, cents = true }: { signed?: boolean; cents?: boolean } = {}): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const digits = cents ? 2 : 0;
  const body = `$${Math.abs(value).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
  const sign = value < 0 ? "-" : signed ? "+" : "";
  // Zero, or a tiny amount that rounds to it, carries no sign: never "-$0" or "+$0".
  return body === `$${(0).toFixed(digits)}` ? body : `${sign}${body}`;
}

/** A share or contract count: whole numbers as they are, fractional shares to two places (four under one). */
export function quantity(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toLocaleString("en-US", { maximumFractionDigits: Math.abs(value) < 1 ? 4 : 2 });
}

type StampOptions = { year?: boolean; seconds?: boolean };

const hasZone = (value: string) => /(?:Z|[+-]\d{2}:?\d{2})$/.test(value);

function stamp(date: Date, timeZone: string, { year = false, seconds = false }: StampOptions): string {
  if (Number.isNaN(date.getTime())) return "—";
  return `${date.toLocaleString("en-US", {
    timeZone, month: "short", day: "numeric", ...(year ? { year: "numeric" } : {}),
    hour: "numeric", minute: "2-digit", ...(seconds ? { second: "2-digit" } : {}),
  })} ET`;
}

/**
 * A moment the server recorded, in New York time and labelled so ("Oct 23, 3:30 PM ET").
 * Backend datetimes without an offset are UTC by repository convention; numbers are epoch milliseconds.
 */
export function timeET(value: string | number | null | undefined, options: StampOptions = {}): string {
  if (value == null || value === "") return "—";
  const date = typeof value === "number" ? new Date(value) : new Date(hasZone(value) ? value : `${value}Z`);
  return stamp(date, "America/New_York", options);
}

/**
 * A fill or trade time, which the backend keeps as a naive New York wall clock: shown as written
 * and labelled ET, whatever zone the page happens to render in.
 */
export function wallClockET(value: string | null | undefined, options: StampOptions = {}): string {
  if (!value) return "—";
  return hasZone(value) ? stamp(new Date(value), "America/New_York", options) : stamp(new Date(`${value}Z`), "UTC", options);
}

/** Today's date in New York as YYYY-MM-DD, the form option expirations use. */
export function newYorkToday(now = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
}

/** The Monday of a YYYY-MM-DD date's week, as YYYY-MM-DD; ``days`` shifts it by whole days first. */
export function mondayOf(day: string, days = 0): string {
  const date = new Date(`${day}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  date.setUTCDate(date.getUTCDate() - ((date.getUTCDay() + 6) % 7));
  return date.toISOString().slice(0, 10);
}

/**
 * An expiration, or a journal timestamp's New York wall date, as a short
 * calendar date ("Oct 9"), with the year when it is not this year ("Jan 15, 2027").
 */
export function fmtDate(value: string, thisYear: number) {
  const [year, month, day] = value.slice(0, 10).split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric", ...(year === thisYear ? {} : { year: "numeric" }) });
}

/** Keep the full option identity visible even when its detail columns are hidden. */
export function contractName(trade: { ticker: string; strike?: number | null; expiration?: string | null; option_type?: string | null }) {
  const expiry = trade.expiration;
  const date = expiry ? fmtDate(expiry, Number(expiry.slice(0, 4))) : null;
  const year = expiry?.slice(2, 4);
  const side = trade.option_type === "call" ? "C" : trade.option_type === "put" ? "P" : "";
  return `${trade.ticker} ${trade.strike ?? "—"}${side}${date ? ` · ${date} '${year}` : ""}`;
}


const SIDE_LABELS: Record<string, string> = {
  buy_to_open: "Buy to open",
  sell_to_close: "Sell to close",
  buy_to_close: "Buy to close",
  sell_to_open: "Sell to open",
  buy: "Buy",
  sell: "Sell",
};

/** A fill's side in words ("buy_to_open" -> "Buy to open"); anything unknown shows as stored. */
export const sideLabel = (side: string) => SIDE_LABELS[side] ?? side;
