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

/** Today's date in New York as YYYY-MM-DD, the form option expirations use. */
export function newYorkToday(now = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
}
