import type { SetupCohort, SetupRecord, SetupTally } from "@/lib/copilot";

const usd = (n: number) => `${n < 0 ? "−" : ""}$${Math.round(Math.abs(n)).toLocaleString("en-US")}`;
const signedUsd = (n: number) => `${n >= 0 ? "+" : ""}${usd(n)}`;
const pct = (n: number) => `${n < 0 ? "−" : "+"}${Math.abs(n).toFixed(1)}%`;
const tally = (t: SetupTally) => `${t.trades} trades, ${Math.round((100 * t.won) / t.trades)}% won, ${signedUsd(t.pnl)}`;

/** "against a gap down of 1%+" for a call: what each gap relation means for the side. */
function gapWords(side: "call" | "put", relation: NonNullable<SetupCohort>["relation"]) {
  if (relation === "small") return "after a gap under 1%";
  const down = (side === "call") === (relation === "against");
  return `${relation} a gap ${down ? "down" : "up"} of 1%+`;
}

/** A sized option plan's premium against the owner's usual opening option premium, with his record at that size or
 * more when it is in his largest quarter; null without a size record. Shown with the plan card's sizing lines. */
export function premiumLine(setup: SetupRecord | null, premium: number | null | undefined): string | null {
  const size = setup?.size;
  if (!size || !premium || premium <= 0) return null;
  const top = premium >= size.top_quarter_from && size.top_quarter
    ? ` Your opening option trades of ${usd(size.top_quarter_from)}+: ${tally(size.top_quarter)}.` : "";
  return `This plan: ${usd(premium)} of premium, ${(premium / size.usual).toFixed(1)}× your usual ${usd(size.usual)}.${top}`;
}

/**
 * A draft option plan's setup, from the owner's own journal (``setup_record.for_symbol``): his closed opening option
 * trades on this side against or with today's gap, and below or above the 20-day average. Quiet lines of history,
 * never a verdict; a thin cohort or an unknown context shows nothing. The size line is ``premiumLine``.
 */
export default function SetupRecordLines({ symbol, side, setup }: { symbol: string; side: "call" | "put"; setup: SetupRecord | null }) {
  if (!setup) return null;
  const mine = side === "call" ? setup.calls : setup.puts;
  const lines: string[] = [];
  const { gap, trend } = mine;
  if (gap?.record && setup.gap_pct !== null)
    lines.push(`Gap ${pct(setup.gap_pct)}. Your opening ${side}s bought ${gapWords(side, gap.relation)}: ${tally(gap.record)}.`);
  if (trend?.record && setup.vs_sma_pct !== null) {
    // From the relation the cohort was matched on, never the sign: a call against the trend is below it, a put above.
    const where = (side === "call") === (trend.relation === "against") ? "below" : "above";
    lines.push(`${symbol} is ${Math.abs(setup.vs_sma_pct).toFixed(1)}% ${where} its 20-day average. Your opening ${side}s bought ${where} it: ${tally(trend.record)}.`);
  }
  if (!lines.length) return null;
  return (
    <div aria-label={`Your record for this ${symbol} setup`} className="space-y-0.5 text-xs text-muted-foreground">
      {lines.map(line => <p key={line}>{line}</p>)}
    </div>
  );
}
