"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * The Ticket's Play check (docs/copilot-lab.md § Ticket, "Play check"; ``engine/play_check.py``): whether this is a play
 * he planned or one of his costly habits, and what holding it overnight costs. Facts and arithmetic from the server;
 * the only sums here scale its per-contract dollars by the count he types and judge the size rule again on the cost he
 * types (the server's ``fill_interrupts`` median and multiple). Compact when clean: two lines, opening up only for a
 * missing part, a habit that fired, or a hold that runs past today's close.
 */

type PlayLine = { part: "stop" | "target" | "time" | "size"; ok: boolean; text: string };
type Habit = { kind: string; line: string };
type AltRow = {
  name: "as_traded" | "deeper" | "spread" | "later" | "shares"; label: string; unit: "contracts" | "spreads" | "shares";
  state: "ok" | "stale" | "missing"; as_of?: number | null; reason?: string; units?: number; cost?: number; credit?: boolean;
  max_loss?: number | null; max_loss_note?: string | null; decay_day?: number | null; decay_pct?: number | null;
  hold_cost?: number | null; hold_cost_pct?: number | null; breakeven?: number | null; breakeven_move_pct?: number | null;
  vs_expected?: number | null; note?: string;
};
export type PlayCheckData = {
  play: { lines: PlayLine[]; missing: string[]; fill: string | null };
  habits: { state: "ok" | "quiet" | "error"; fired: Habit[]; size: { median: number; multiple: number; tail: string } | null; footer: string } | null;
  overnight: ({ state: "ok"; show: boolean; until: number; until_source: string; expires_first: boolean; trading_days: number;
    hold_days: number; greeks_as_of: string | null; expected_move_pct: number | null; basis: string; rows: AltRow[] }
    | { state: "stale" | "missing"; show: boolean; as_of?: number | null; reason?: string }) | null;
};

const SECTION = "text-[11px] font-medium uppercase tracking-wide text-muted-foreground";
const PART: Record<PlayLine["part"], string> = { stop: "Stop", target: "Target", time: "Time", size: "Size" };
const ALT_NAMES: Record<AltRow["name"], string> = { as_traded: "Yours", deeper: "Deeper", spread: "Debit spread", later: "Later expiry", shares: "Shares" };
const usd = (n: number) => `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const usd0 = (n: number) => `$${n.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
const signedPct = (n: number) => `${n < 0 ? "−" : "+"}${Math.abs(n).toFixed(1)}%`;
const clock = (epoch: number | null | undefined) => epoch ? new Date(epoch * 1000).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" }) + " ET" : "an unknown time";
const when = (epoch: number) => new Date(epoch * 1000).toLocaleString("en-US", { timeZone: "America/New_York", weekday: "short", month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit" }) + " ET";
const trim = (n: number) => String(Number(n.toFixed(2)));

/** The after-fill size rule on the cost he is about to pay (``fill_interrupts.large_size``): at least the multiple of
 *  his median, the server's tail after it, as the after-fill line reads. */
export function sizeLine(size: { median: number; multiple: number; tail: string } | null, paid: number | null): string | null {
  if (!size || paid === null || !(paid > 0) || paid < size.multiple * size.median - 1e-9) return null;
  return `Size: ${usd0(paid)} is ${(paid / size.median).toFixed(1)}× your median (${usd0(size.median)}); ${size.tail}`;
}

export default function PlayCheck({ check, investigationId, symbol, contracts, paid }: {
  check: PlayCheckData; investigationId: string; symbol: string; contracts: number | null; paid: number | null;
}) {
  const [open, setOpen] = useState(false);
  const { play, habits, overnight } = check;
  // The size rule is judged on what he typed; the others as the server judged them at the ticket's own count and limit.
  const fired = habits && habits.state === "ok" ? habits.fired.filter(h => h.kind !== "large_size").map(h => h.line) : [];
  const size = habits && habits.state === "ok" ? sizeLine(habits.size, paid) : null;
  if (size) fired.push(size);
  const edit = `/copilot-lab?investigation=${encodeURIComponent(investigationId)}`;
  const night = overnight?.state === "ok" ? overnight : null;
  const showNight = !!night && (night.show || open);
  const count = contracts && contracts > 0 ? contracts : 1;

  return (
    <div data-testid="play-check" className="space-y-2 rounded-lg border bg-card px-3 py-2 text-xs">
      {play.missing.length === 0 ? (
        <p data-testid="play-line" className="leading-5"><span className={cn(SECTION, "mr-2")}>Play</span>
          {play.lines.map((l, i) => <span key={l.part}>{i > 0 && <span className="text-muted-foreground"> · </span>}<span className="text-emerald-400">✓</span> {l.text}</span>)}
        </p>
      ) : (
        <div data-testid="play-line" className="space-y-0.5">
          <p className={SECTION}>Play</p>
          <ul className="space-y-0.5">
            {play.lines.map(l => (
              <li key={l.part} className={cn("leading-5", !l.ok && "text-amber-300")}>
                {l.ok ? <span className="text-emerald-400">✓</span> : <span aria-hidden>○</span>} {PART[l.part]}: {l.text}
              </li>
            ))}
          </ul>
          <p className="text-muted-foreground">{play.fill} <a href={edit} className="text-foreground underline underline-offset-2">Edit the plan</a></p>
        </div>
      )}

      {habits && habits.state !== "quiet" && (
        habits.state === "error" ? <p data-testid="play-habits" className="text-muted-foreground">Your habits could not be read just now.</p>
        : fired.length === 0 ? (
          <p data-testid="play-habits" className="leading-5"><span className={cn(SECTION, "mr-2")}>Your habits</span><span className="text-muted-foreground">none of your flagged habits</span></p>
        ) : (
          <div data-testid="play-habits" className="space-y-0.5">
            <p className={SECTION}>Your habits</p>
            <ul className="space-y-0.5">{fired.map(line => <li key={line} className="leading-5 text-amber-300">{line}</li>)}</ul>
            <p className="text-muted-foreground">{habits.footer}</p>
          </div>
        )
      )}

      {overnight && overnight.state !== "ok" && (
        <p data-testid="play-overnight" className="text-muted-foreground">
          Holding overnight: {overnight.state === "stale" ? `quote stale (last ${clock(overnight.as_of)}), no figures` : overnight.reason ?? "no figures"}
        </p>
      )}
      {night && !night.show && (
        <button type="button" onClick={() => setOpen(o => !o)} aria-expanded={open}
          className="inline-flex min-h-11 items-center gap-1 text-muted-foreground hover:text-foreground sm:min-h-6">
          {open ? <ChevronDown size={13} aria-hidden /> : <ChevronRight size={13} aria-hidden />}
          If you held it to the next close
        </button>
      )}
      {night && showNight && <Overnight night={night} symbol={symbol} count={count} counted={!!contracts && contracts > 0} />}
    </div>
  );
}

function Overnight({ night, symbol, count, counted }: {
  night: Extract<NonNullable<PlayCheckData["overnight"]>, { state: "ok" }>; symbol: string; count: number; counted: boolean;
}) {
  const mine = night.rows.find(r => r.name === "as_traded");
  const others = night.rows.filter(r => r.name !== "as_traded");
  const by = night.show ? `${night.until_source === "time stop" ? "your time stop" : `your ${night.until_source}`}, ${when(night.until)}` : `the next close, ${when(night.until)}`;
  const greeks = night.greeks_as_of ? ` · theta as of ${night.greeks_as_of}` : "";
  const expected = night.expected_move_pct !== null ? ` vs ±${night.expected_move_pct}% expected over that time` : "";
  return (
    <div data-testid="play-overnight" className="space-y-1">
      <p className={SECTION}>Holding overnight</p>
      <p className="text-muted-foreground">To {by}: {night.trading_days} trading day{night.trading_days === 1 ? "" : "s"}{night.expires_first ? "; the contract expires first" : ""}. {counted ? `For your ${count} contract${count === 1 ? "" : "s"}` : "For 1 contract"}.</p>
      {mine && mine.state === "ok" ? (
        <>
          <p>Time decay: {mine.decay_day != null ? `${usd(mine.decay_day * count)} a day${mine.decay_pct != null ? ` (${mine.decay_pct}% of the premium)` : ""}` : "no theta in the chain"}<span className="text-muted-foreground">{greeks}</span></p>
          <p>
            {mine.hold_cost != null && <>If {symbol} does not move: −{usd(mine.hold_cost * count)}{mine.hold_cost_pct != null ? ` (${mine.hold_cost_pct}%)` : ""} by then. </>}
            {mine.breakeven != null ? <>Break-even then: {symbol} {mine.breakeven.toFixed(2)}{mine.breakeven_move_pct != null ? ` (${signedPct(mine.breakeven_move_pct)})` : ""}</> : "No break-even inside the range searched"}
            <span className="text-muted-foreground">{expected}</span>
          </p>
        </>
      ) : mine && <p className="text-muted-foreground">Your contract: {mine.state === "stale" ? `quote stale (last ${clock(mine.as_of)})` : mine.reason}</p>}
      {others.length > 0 && (
        <div className="space-y-0.5 pt-1">
          <p className="text-muted-foreground">The same exposure (same delta as yours), at the mid:</p>
          <ul className="divide-y" aria-label="Same exposure">
            {others.map(r => (
              <li key={r.name} data-testid="play-alt" className={cn("py-1 leading-5", r.state !== "ok" && "text-muted-foreground")}>
                <span className="font-medium">{ALT_NAMES[r.name]}</span> <span className="text-muted-foreground">{r.label}</span>
                {r.state !== "ok" ? <span> · {r.state === "stale" ? `quote stale (last ${clock(r.as_of)})` : r.reason}</span> : (
                  <span className="block sm:inline">
                    <span className="hidden sm:inline"> · </span>{r.unit === "shares" ? Math.round((r.units ?? 0) * count) : trim((r.units ?? 0) * count)} {r.unit}
                    {" · "}{r.credit ? "takes in" : "costs"} {usd((r.cost ?? 0) * count)}
                    {" · "}most you can lose {r.max_loss != null ? usd(r.max_loss * count) : r.max_loss_note}
                    {" · "}{r.decay_day ? `${usd(r.decay_day * count)} a day` : "no time decay"}
                    {" · "}break-even then {r.breakeven != null ? `${r.breakeven.toFixed(2)}${r.breakeven_move_pct != null ? ` (${signedPct(r.breakeven_move_pct)})` : ""}` : "—"}
                    {r.note && <span className="text-amber-300"> · {r.note}</span>}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="text-muted-foreground">Arithmetic, not a pick: Black-Scholes at the volatility each contract&apos;s mid implies, price and volatility held.</p>
    </div>
  );
}
