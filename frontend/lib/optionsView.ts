import type { OptionsInfo, OptionsMeasure, OptionsScope } from "./charts";

/**
 * Words and numbers for the options levels (C4.4), the strike ladder (C4.5) and
 * the Forecast tab (T2.1). Every figure says what kind of number it is: open
 * interest and volume are observed, gamma calculated, signed gamma assumed.
 */

export const MEASURE_NAMES: Record<OptionsMeasure, string> = { oi: "Open interest", volume: "Volume", gamma: "Gamma" };
export const SCOPE_NAMES: Record<OptionsScope, string> = { nearest: "0DTE / nearest", week: "This week", all: "Within 45 days" };

const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
/** A contract count, compact ("12.3K"); a dash where the provider gave nothing. */
export const contracts = (value: number | null | undefined) => value == null ? "—" : compact.format(value);

/** Dollar gamma for a 1% move: "$1.2M per 1%"; signed ones carry their sign and say they are assumed. */
export function gammaText(value: number | null | undefined, signed: boolean): string {
  if (value == null) return "unavailable";
  const amount = `$${compact.format(Math.abs(value))} per 1%`;
  return signed ? `${value >= 0 ? "+" : "−"}${amount} net (assumed side)` : `${amount} (calculated)`;
}

const clock = (seconds: number) => new Date(seconds * 1000).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });

/** Where the numbers come from and how old each part is. */
export function optionsAsOf(info: OptionsInfo): string {
  return [
    info.scope_note,
    info.fetched_at ? `${info.source} read ${clock(info.fetched_at)} ET` : null,
    "open interest is OCC's overnight figure for the prior close",
    info.greeks_updated_at ? `IV stamped ${info.greeks_updated_at} by the provider` : null,
    info.spot ? `gamma recomputed at ${info.spot.toFixed(2)}` : null,
    info.missing && Object.keys(info.missing).length ? `missing on ${Object.entries(info.missing).map(([what, count]) => `${count} ${what.replace("_", " ")}`).join(", ")} contract${Object.values(info.missing).some((n) => n !== 1) ? "s" : ""}` : null,
    info.excluded && Object.keys(info.excluded).length ? `other roots left out: ${Object.entries(info.excluded).map(([root, count]) => `${root} ${count}`).join(", ")}` : null,
    info.max_pain_reason,
  ].filter(Boolean).join(" · ") + ".";
}
