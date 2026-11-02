"use client";

import type { CSSProperties } from "react";
import { X } from "lucide-react";
import { etTime, intradayInterval, price } from "@/lib/charts";
import type { AutoLevel, AutoLevels, AutoZone, Interval, LevelEvent, LevelInteraction, OptionsInfo, RangesInfo } from "@/lib/charts";
import { formedName, isOption, isRange, KIND_NAMES, sourceName, spanName, STATE_NAMES } from "@/lib/autoLevels";
import { contracts, gammaText, openInterestChangeText, optionsAsOf } from "@/lib/optionsView";

function eventName(event: LevelEvent): string {
  const side = event.direction ? ` ${event.direction}` : "";
  if (event.event === "tested") return `Touched; left${side}`;
  if (event.event === "approached") return `Approached; left${side}`;
  return `${event.event === "broken" ? "Closed" : "Returned"}${side}`;
}
const STATE_STYLE: Record<LevelInteraction["state"], string> = {
  untested: "bg-secondary text-foreground/80", tested: "bg-foreground/10 text-foreground", broken: "bg-rose-400/10 text-rose-300",
  reclaimed: "bg-emerald-400/10 text-emerald-300", developing: "bg-amber-400/10 text-amber-300",
  touched: "bg-foreground/10 text-foreground", approached: "bg-border text-foreground/80",
};

/**
 * An automatic level's card (C2.3): what each member level is, where it came
 * from, when it formed and what kind of number it is, and how price has treated
 * it today on this chart's closed bars. Hovering a level shows it; a tap or click
 * keeps it open until the next one.
 */
export default function LevelCard({ zone, auto, interaction, interval, pinned, style, onClose }: {
  zone: AutoZone; auto: AutoLevels; interaction?: LevelInteraction; interval: Interval; pinned: boolean; style: CSSProperties; onClose(): void;
}) {
  const several = zone.members.length > 1;
  return <div role="tooltip" aria-label={`${zone.label} level card`} style={style}
    className={`absolute left-2 z-10 w-72 max-w-[calc(100%-1rem)] overflow-y-auto overscroll-contain rounded-md border border-border bg-card p-2.5 text-[11px] text-foreground/80 shadow-lg ${pinned ? "" : "pointer-events-none"}`}>
    <div className="flex items-start gap-2">
      <div className="min-w-0 flex-1">
        <div className="font-medium text-foreground">{zone.label}</div>
        <div className="font-mono text-[10px] text-muted-foreground">{spanName(zone)}{several && ` · ${zone.members.length} landmarks`}</div>
      </div>
      {pinned && <button aria-label="Close level card" onClick={onClose} className="-m-1 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-secondary hover:text-foreground"><X size={13} /></button>}
    </div>
    <div className="mt-2" aria-label="Interactions today">
      {!intradayInterval(interval) ? <p className="text-muted-foreground">How price met it today is read on intraday charts.</p>
        : !interaction ? <p className="text-muted-foreground">{auto.band === null ? "No daily ATR yet, so interactions are not read." : "Interactions are not read yet."}</p>
        : <>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${STATE_STYLE[interaction.state]}`}>{STATE_NAMES[interaction.state]}</span>
            {interaction.at_level && <span className="text-[10px] text-amber-300">Last closed candle touched</span>}
            {!interaction.at_level && interaction.near_level && <span className="text-[10px] text-muted-foreground">Last closed candle was nearby</span>}
          </div>
          {interaction.events.length > 0 && <ol className="mt-1 flex flex-wrap gap-x-2 font-mono text-[10px] text-muted-foreground">
            {interaction.events.map((event) => <li key={`${event.event}${event.time}`}>{eventName(event)} · confirmed {etTime(event.time)} ET</li>)}
          </ol>}
          <p className="mt-1 text-[10px] text-muted-foreground">Today, on closed {interval} bars{auto.session === "extended" ? ", including extended hours" : auto.session === "regular" ? ", regular hours" : ""}. Touches enter {spanName(zone)}.</p>
          {auto.band !== null && <p className="mt-1 text-[10px] text-muted-foreground">Nearby only: {price(zone.low - auto.band)}–{price(zone.high + auto.band)}. Approaches are not touches.</p>}
          {interaction.since !== undefined && interaction.last_close_at != null && interaction.state !== "developing" && <p className="mt-1 text-[10px] text-muted-foreground">History since {etTime(interaction.since)} ET for this confirmed combination; earlier bars are excluded.</p>}
          {interaction.since !== undefined && interaction.last_close_at == null && interaction.state !== "developing" && <p className="mt-1 text-[10px] text-muted-foreground">No closed candles for this confirmed combination yet.</p>}
          {interaction.state === "developing" && <p className="mt-1 text-[10px] text-muted-foreground">A member is still changing, so this combination has no fixed contact history.</p>}
          {interaction.last_close != null && interaction.last_close_at != null && <p className="mt-1 font-mono text-[10px] text-muted-foreground">Last closed candle: {price(interaction.last_close)} at {etTime(interaction.last_close_at)} ET.</p>}
        </>}
    </div>
    <ul className="mt-2 space-y-1 border-t border-border pt-2">
      {zone.members.map((member) => <li key={`${member.kind}@${member.price}@${member.bar_time}@${member.label}`}>
        <div className="flex justify-between gap-2">
          <span className="min-w-0 truncate"><span className="text-foreground">{member.label}</span> <span className="text-muted-foreground">{KIND_NAMES[member.kind] ?? member.kind}</span></span>
          <span className="shrink-0 font-mono">{price(member.price)}</span>
        </div>
        <div className="text-[10px] text-muted-foreground">{[member.evidence, sourceName(member), formedName(member)].filter(Boolean).join(" · ")}</div>
        {isOption(member) && auto.options && <OptionDetail member={member} options={auto.options} />}
        {isRange(member) && auto.ranges && <RangeDetail member={member} ranges={auto.ranges} />}
      </li>)}
    </ul>
    {zone.members.some(isOption) && auto.options && <p className="mt-2 border-t border-border pt-1.5 text-[10px] leading-4 text-muted-foreground">{optionsAsOf(auto.options)}</p>}
    {zone.members.some(isRange) && <p className="mt-2 border-t border-border pt-1.5 text-[10px] leading-4 text-muted-foreground">
      What the options market charged for a move either way by that expiration, from {auto.ranges?.source ?? "Tradier option chains"}: a price, not a forecast of where price will stay.</p>}
  </div>;
}

/** A band's name as the backend labels it: "0DTE" for today's expiration, else its weekday ("Fri"). */
const bandName = (band: RangesInfo["bands"][number]) => band.today ? "0DTE"
  : new Date(`${band.expiration}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", weekday: "short" });
const day = (iso: string) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", weekday: "short", month: "short", day: "numeric" });

/** An expected-move level's straddle (C2.7): which expiration, its price, and the price it was centred on when captured. */
function RangeDetail({ member, ranges }: { member: AutoLevel; ranges: RangesInfo }) {
  const high = member.kind === "expected_move_high";
  // By the label the backend gives each band's levels ("EM 0DTE high", "EM Fri low"): two bands can end on the same cent.
  const band = ranges.bands.find((row) => `EM ${bandName(row)} ${high ? "high" : "low"}` === member.label);
  if (!band) return null;
  return <p aria-label={`Straddle ${day(band.expiration)}`} className="mt-0.5 text-[10px] leading-4 text-muted-foreground">
    {band.today ? "Today's (0DTE)" : `${day(band.expiration)}'s`} {price(band.strike)} straddle cost {price(band.move)} ({(band.percent * 100).toFixed(2)}%) at {etTime(band.captured_at)} ET,
    {" "}{high ? "added to" : "taken from"} {price(band.anchor)}, the price then{band.iv === null ? "" : `; IV ${(band.iv * 100).toFixed(1)}%`}.</p>;
}

/** An option strike's numbers (C4.4): open interest and volume per side with their ranks, gamma, and how far it is from the price. */
function OptionDetail({ member, options }: { member: AutoLevel; options: OptionsInfo }) {
  if (member.kind === "gamma_flip") return <p className="mt-0.5 text-[10px] leading-4 text-amber-200/80">
    {options.flip?.note} Searched {price(options.flip?.low)}–{price(options.flip?.high)}, each strike&apos;s IV and the time held.</p>;
  if (member.kind === "max_pain") return <p className="mt-0.5 text-[10px] leading-4 text-orange-200/80">
    {options.max_pain ? `${day(options.max_pain.expiration)} expiration. ${options.max_pain.note}` : "Max pain is not available."}</p>;
  const row = options.strikes?.find((strike) => strike.strike === member.price);
  if (!row) return null;
  const away = options.spot ? (row.strike / options.spot - 1) * 100 : null;
  const measure = options.mode === "volume" ? "volume" : options.mode === "gamma" ? "gamma" : "open interest";
  return <dl aria-label={`Strike ${price(row.strike)}`} className="mt-1 grid grid-cols-[auto_1fr] gap-x-2 font-mono text-[10px] text-muted-foreground">
    <dt className="font-sans text-muted-foreground">Calls</dt><dd>OI {contracts(row.call_oi)}{row.call_oi_rank ? ` (#${row.call_oi_rank})` : ""} · Vol {contracts(row.call_volume)}{row.call_volume_rank ? ` (#${row.call_volume_rank})` : ""}</dd>
    <dt className="font-sans text-muted-foreground">Puts</dt><dd>OI {contracts(row.put_oi)}{row.put_oi_rank ? ` (#${row.put_oi_rank})` : ""} · Vol {contracts(row.put_volume)}{row.put_volume_rank ? ` (#${row.put_volume_rank})` : ""}</dd>
    <dt className="font-sans text-muted-foreground">Δ OI</dt><dd aria-label={openInterestChangeText(row.oi_change)}>{openInterestChangeText(row.oi_change)}</dd>
    <dt className="font-sans text-muted-foreground">Gamma</dt><dd>{gammaText(row.gamma, !!options.signed && options.mode === "gamma")}</dd>
    <dt className="font-sans text-muted-foreground">Strike</dt><dd>{row.rank ? `#${row.rank} by ${measure}` : `not ranked by ${measure}`}{away === null ? "" : ` · ${away >= 0 ? "+" : ""}${away.toFixed(2)}% from ${price(options.spot)}`}</dd>
  </dl>;
}
