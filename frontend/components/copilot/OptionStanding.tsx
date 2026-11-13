"use client";

/**
 * Where a held option stands, on the desk (docs/copilot-lab.md § The desk): break-even and the stock's distance to it,
 * days left, value at expiry if the stock stays put against value now, decay a day, the dollar move per $1 in the stock
 * and IV, with a small P&L-at-expiry line. The arithmetic is ``lib/optionStanding.ts``; this only lays it out. The
 * stock-price figures move with the desk's live prices (``lib/deskTicks.ts``); the Greeks are the book read's. Facts
 * only: nothing here tells the owner to buy, sell or hold. With a plan, "Close at target" / "Close at stop" open the
 * Ticket as a closing sell to copy (``lib/closingTicket.ts``); they are absent when any input is missing.
 */

import { useEffect, useMemo, useRef, useState, type PointerEvent, type ReactNode } from "react";
import type { DeskThread } from "@/lib/desk";
import { tickFor, useDeskTicks } from "@/lib/deskTicks";
import { price as priceText, todayNewYork } from "@/lib/charts";
import {
  EARNINGS_IV_KEPT, MARK_TOLERANCE, RATE, addDays, dayAfterEarnings, daysLeft, mixedStructure, optionStanding, whatIfAt,
  whatIfCurve, whatIfModel, whatIfRange, worthNow, type ExpiryCurve, type OptionGreeks, type Standing,
  type WhatIfModel,
} from "@/lib/optionStanding";
import { CLOSING_LABEL, closingTicket, type ClosingAt, type ClosingTicket } from "@/lib/closingTicket";
import { openClosingTicket } from "@/components/copilot/DeskTicket";
import { Flash } from "@/components/copilot/Ticks";
import { cn } from "@/lib/utils";

/** Robinhood's Greeks older than this read as stale (the feed refreshes once a minute in market hours). */
const GREEKS_STALE_SECONDS = 180;

const clock = (seconds: number) => new Date(seconds * 1000).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });

/** Dollars, cents under $10 so a small figure never rounds to a misleading $0. */
function dollars(value: number, signed = false) {
  const abs = Math.abs(value);
  const text = abs.toLocaleString("en-US", abs < 10 && abs >= 0.005 ? { minimumFractionDigits: 2, maximumFractionDigits: 2 } : { maximumFractionDigits: 0 });
  const sign = value > 0 ? (signed ? "+" : "") : value < 0 ? "−" : "";
  return `${sign}$${text}`;
}
const pct = (value: number) => `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(1)}%`;

function greeksLine(greeks: OptionGreeks | null, now = Date.now() / 1000): { text: string; stale: boolean } {
  if (!greeks) return { text: "Greeks unavailable", stale: true };
  if (greeks.source === "robinhood") {
    const at = typeof greeks.as_of === "number" ? greeks.as_of : null;
    return { text: at === null ? "Greeks · Robinhood" : `Greeks · Robinhood ${clock(at)}`, stale: at === null || now - at > GREEKS_STALE_SECONDS };
  }
  // The app's own quote: hourly provider figures, their stamp as given (its time zone is the provider's).
  const stamp = typeof greeks.as_of === "string" ? greeks.as_of.slice(11, 16) : "";
  return { text: `Greeks · app quote, hourly${stamp ? ` (stamp ${stamp})` : ""}`, stale: true };
}

function Fig({ label, children, dim = false, testId }: { label: string; children: ReactNode; dim?: boolean; testId?: string }) {
  return (
    <span data-testid={testId} className={cn("min-w-0 max-w-full sm:whitespace-nowrap", dim && "opacity-50")}>
      <span className="text-muted-foreground">{label} </span><span className="text-foreground">{children}</span>
    </span>
  );
}

/** P&L at expiry across the range, a zero line, the stock now (white) and break-even (amber). */
export function ExpiryLine({ curve, now, breakEven, dim = false }: { curve: ExpiryCurve; now: number; breakEven: number; dim?: boolean }) {
  const W = 120, H = 26;
  const pnls = curve.points.map(p => p.pnl);
  const top = Math.max(...pnls, 0), bottom = Math.min(...pnls, 0);
  const x = (at: number) => (at - curve.lo) / (curve.hi - curve.lo) * W;
  const y = (pnl: number) => top === bottom ? H / 2 : 1 + (top - pnl) / (top - bottom) * (H - 2);
  const path = curve.points.map((p, i) => `${i ? "L" : "M"}${x(p.price).toFixed(1)},${y(p.pnl).toFixed(1)}`).join("");
  return (
    <svg data-testid="option-expiry-line" width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" className={cn("shrink-0 overflow-visible", dim && "opacity-50")}
      aria-label={`P&L at expiry from ${priceText(curve.lo)} to ${priceText(curve.hi)}: break-even ${priceText(breakEven)}, stock now ${priceText(now)}`}>
      <line x1={0} x2={W} y1={y(0)} y2={y(0)} stroke="hsl(var(--muted-foreground))" strokeOpacity={0.4} strokeDasharray="2 2" />
      <path d={path} fill="none" stroke="hsl(var(--muted-foreground))" strokeWidth={1.25} />
      <line x1={x(breakEven)} x2={x(breakEven)} y1={0} y2={H} stroke="#e9a23b" strokeWidth={1} />
      <line x1={x(now)} x2={x(now)} y1={0} y2={H} stroke="hsl(var(--foreground))" strokeWidth={1.25} />
    </svg>
  );
}

function useStanding(row: DeskThread, rows: readonly DeskThread[], fallback: { last: number; at: number } | null) {
  const book = row.book;
  const ticks = useDeskTicks([row.symbol, book?.tick?.quote]);
  const terms = book?.option ?? null;
  if (!book || !terms) return null;
  if (mixedStructure(row.symbol, terms, rows.map(r => ({ symbol: r.symbol, option: r.book?.option })))) return "unknown" as const;
  const live = tickFor(ticks, row.symbol);
  const stock = live ? { last: live.last, at: live.at, live: !live.stale } : fallback ? { ...fallback, live: false } : null;
  const worth = worthNow(book, ticks);
  const standing = optionStanding(terms, { price: stock?.last, worth, day: todayNewYork() });
  if (!standing) return terms.direction === "long" ? "incomplete" as const : "unknown" as const;
  // The plan's exits as closing tickets: each only with every input it needs (``closingTicket``), else no button.
  const optionTick = book.tick ? tickFor(ticks, book.tick.quote) : null;
  // Robinhood's label and masked number (a matched row): the journal's account name never leaves the server here.
  const account = book.account ? `${book.account.label}${book.account.masked ? ` ${book.account.masked}` : ""}` : null;
  const closing = (["target", "stop"] as ClosingAt[]).flatMap((at): ClosingTicket[] => {
    const ticket = closingTicket({ symbol: row.symbol, at, terms, levels: book.plan_levels, account, worth,
      stock: stock ? { last: stock.last, at: stock.at } : null, markLive: !!optionTick && !optionTick.stale });
    return ticket ? [ticket] : [];
  });
  return { standing, stock, terms, closing };
}

/** "Close at target" and "Close at stop": each opens the desk's Ticket as a closing sell to copy into Robinhood. */
function CloseButtons({ closing, className }: { closing: ClosingTicket[]; className?: string }) {
  if (!closing.length) return null;
  return (
    <span data-testid="close-from-plan" className={cn("inline-flex flex-wrap gap-1.5", className)}>
      {closing.map(t => (
        <button key={t.at} type="button" onClick={() => openClosingTicket(t)}
          title={`A closing sell of your ${t.contracts} contract${t.contracts === 1 ? "" : "s"} on the Ticket, priced for ${t.symbol} at ${priceText(t.level)}. Nothing is sent.`}
          className="inline-flex min-h-11 items-center rounded-md border px-2.5 text-xs font-medium text-foreground hover:bg-secondary sm:min-h-7">
          {CLOSING_LABEL[t.at]}
        </button>
      ))}
    </span>
  );
}

const INCOMPLETE = "Break-even and Greeks not shown: the book is missing this contract's side, strike, expiry or size.";
const UNKNOWN = "Break-even and Greeks not shown: a short or multi-leg position the book cannot read as one option.";

function distance(s: Standing) {
  const to = s.toBreakEven;
  if (!to) return null;
  if (to.past) return `${dollars(Math.abs(to.usd))} (${Math.abs(to.pct).toFixed(1)}%) past it`;
  return `needs ${dollars(to.usd, true)} (${pct(to.pct)})`;
}

/**
 * The selected option's standing under the centre's header. ``rows`` is the desk's book (a short option on the same
 * ticker means a structure the book cannot tell); ``fallback`` the stock's last price when the desk's ticker is not
 * running (the chart's last read). ``levels`` (the plan's, on the underlying) and ``earnings`` (the next report's date)
 * feed the folded What if… under it.
 */
export function OptionStanding({ row, rows, fallback = null, levels = {}, earnings = null }: {
  row: DeskThread; rows: readonly DeskThread[]; fallback?: { last: number; at: number } | null;
  levels?: PlanLevels; earnings?: string | null;
}) {
  const read = useStanding(row, rows, fallback);
  const [open, setOpen] = useWhatIfOpen();
  if (read === null) return null;
  if (read === "unknown" || read === "incomplete") return <p data-testid="option-standing" className="text-xs text-muted-foreground">{read === "unknown" ? UNKNOWN : INCOMPLETE}</p>;
  const { standing: s, stock, closing } = read;
  const dim = !!stock && !stock.live;
  const greeks = greeksLine(s.greeks);
  const missing = [s.decayPerDay === null && "decay", s.perDollar === null && "delta", s.ivPct === null && "IV"].filter((part): part is string => !!part);
  const days = s.daysLeft < 0 ? "Expired" : s.expiryNote ? `${s.expiryNote} · ${s.daysLeft}d` : `${s.daysLeft}d left`;
  const what = whatIfModel(read.terms, { price: stock?.last, worth: s.worth, day: todayNewYork(), nyMinute: nyMinuteNow() });
  return (
    <div className="space-y-2">
    <div data-testid="option-standing" className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs tabular-nums">
      <Fig label="Break-even" testId="standing-break-even">
        {s.breakEven === null ? <span className="text-muted-foreground">unavailable (no cost)</span> : <>
          {priceText(s.breakEven)}
          {s.toBreakEven && <span className={cn("text-muted-foreground", dim && "opacity-50")}> · stock <Flash value={stock?.last}>{priceText(stock!.last)}</Flash>{dim && ` (${clock(stock!.at)})`} {distance(s)}</span>}
        </>}
      </Fig>
      <Fig label="Expiry" testId="standing-expiry"><span className={cn(s.daysLeft <= 2 && "text-amber-300")}>{days}</span></Fig>
      <Fig label="If it stays here" testId="standing-at-expiry" dim={dim}>
        {s.atExpiry === null ? <span className="text-muted-foreground">stock price unavailable</span> : <>
          {dollars(s.atExpiry)} at expiry
          {s.worth !== null ? <> · {dollars(s.worth)} now · {s.timeValue! >= 0 ? `${dollars(s.timeValue!)} time value` : `${dollars(-s.timeValue!)} under intrinsic`}</>
            : <span className="text-muted-foreground"> · value now unavailable</span>}
        </>}
      </Fig>
      {s.decayPerDay !== null && <Fig label="Decay" testId="standing-decay" dim={greeks.stale}>{dollars(s.decayPerDay, true)}/day</Fig>}
      {s.perDollar !== null && <Fig label="Moves" testId="standing-delta" dim={greeks.stale}>about {dollars(s.perDollar, true)} per $1 up in {row.symbol}</Fig>}
      {s.ivPct !== null && <Fig label="IV" testId="standing-iv" dim={greeks.stale}>{s.ivPct.toFixed(0)}%</Fig>}
      {s.curve && s.breakEven !== null && stock && <ExpiryLine curve={s.curve} now={stock.last} breakEven={s.breakEven} dim={dim} />}
      <span data-testid="standing-greeks" className={cn("text-[11px]", greeks.stale ? "text-muted-foreground/70" : "text-muted-foreground")}>
        {missing.length === 3 ? "Greeks unavailable" : missing.length ? `${greeks.text} · ${missing.join(", ")} unavailable` : greeks.text}
      </span>
      {what && ("reason" in what
        ? <span data-testid="what-if-off" className="text-[11px] text-muted-foreground">What if… unavailable: {what.reason}</span>
        : <button type="button" data-testid="what-if-toggle" aria-expanded={open} onClick={() => setOpen(!open)}
            className="min-h-11 rounded px-1 text-[11px] text-muted-foreground underline decoration-dotted underline-offset-2 hover:text-foreground sm:min-h-0">
            What if…{open ? " ▴" : " ▾"}
          </button>)}
      <CloseButtons closing={closing} />
    </div>
    {open && what && !("reason" in what) && (
      <OptionWhatIf key={`${row.key}:${read.terms.strike}:${read.terms.expiry}`} model={what} symbol={row.symbol ?? ""}
        breakEven={s.breakEven} levels={levels} earnings={earnings} />
    )}
    </div>
  );
}

// --------------------------------------------------------------------------- what if

/** The plan's levels on the underlying, from the desk chart's read: entry, invalidation and the optional saved target. */
export type PlanLevels = { entry?: number | null; stop?: number | null; target?: number | null };

const OPEN_KEY = "desk.whatIf.open";
/** Open or folded, remembered on this browser (read after hydration). */
function useWhatIfOpen(): [boolean, (next: boolean) => void] {
  const [open, setOpen] = useState(false);
  useEffect(() => { try { setOpen(window.localStorage.getItem(OPEN_KEY) === "open"); } catch { /* folded */ } }, []); // eslint-disable-line react-hooks/set-state-in-effect -- the store is read after hydration
  return [open, (next: boolean) => {
    setOpen(next);
    try { window.localStorage.setItem(OPEN_KEY, next ? "open" : "folded"); } catch { /* this view only */ }
  }];
}

const nyMinuteFormat = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hourCycle: "h23", hour: "2-digit", minute: "2-digit" });
function nyMinuteNow() {
  const parts = nyMinuteFormat.formatToParts(new Date());
  const part = (type: string) => Number(parts.find(p => p.type === type)?.value ?? 0);
  return part("hour") * 60 + part("minute");
}
const shortDay = (day: string) => new Date(`${day}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", weekday: "short", month: "short", day: "numeric" });

const CAVEAT = `An estimate, not a quote: Black-Scholes with European exercise, no dividends and a ${(RATE * 100).toFixed(0)}% rate, `
  + "holding IV where it is. US stock options can be exercised early, so a deep in-the-money option (a put most of all) can "
  + "be worth a little more than this. Real prices also move with IV, the bid-ask spread and news.";

/**
 * What if…: drag the stock price and the date (today to expiry) and read the option's estimated value and the P&L there,
 * with the P&L across stock prices on that date (today's price, break-even and the plan's levels marked). Presets put
 * the stock at the plan's stop or target, or step past the next earnings with the stock unchanged and IV lower by a
 * stated share. Estimates from ``whatIfModel`` (lib/optionStanding.ts); nothing here says what to do.
 */
function OptionWhatIf({ model: m, symbol, breakEven, levels, earnings }: {
  model: WhatIfModel; symbol: string; breakEven: number | null; levels: PlanLevels; earnings: string | null;
}) {
  const span = Math.max(0, daysLeft(m.expiry, m.day));
  const marks = [levels.entry, levels.stop, levels.target, breakEven].filter((v): v is number => typeof v === "number" && v > 0);
  // The range holds still while the stock ticks (the sliders would creep), but widens when the plan's levels arrive.
  const [anchor] = useState(() => ({ ...m }));
  const marksKey = marks.join(",");
  const range = useMemo(() => whatIfRange(anchor, marksKey ? marksKey.split(",").map(Number) : []), [anchor, marksKey]);
  const [chosen, setChosen] = useState<number | null>(null); // null: follow today's price
  const [offset, setOffset] = useState(0);
  const [crush, setCrush] = useState(false);
  const afterReport = dayAfterEarnings(earnings, m.day, m.expiry);
  const price = chosen ?? m.price;
  const day = addDays(m.day, Math.min(offset, span));
  const crushed = crush && !!afterReport && day >= afterReport;
  const iv = crushed ? m.iv * EARNINGS_IV_KEPT : m.iv;
  const at = whatIfAt(m, { price, day, iv });
  const curve = whatIfCurve(m, { day, iv, lo: range.lo, hi: range.hi });
  const move = (price - m.price) / m.price * 100;
  const left = daysLeft(m.expiry, day);
  const dayText = offset === 0 ? "Today" : left <= 0 ? `${shortDay(day)} · expiry (intrinsic value)` : `${shortDay(day)} · ${left}d before expiry`;
  const clampPrice = (value: number) => Math.min(range.hi, Math.max(range.lo, value));

  const preset = (button: string, title: string | null, onClick: () => void, testId: string) => (
    <button key={testId} type="button" data-testid={testId} disabled={!!title} title={title ?? undefined} onClick={onClick}
      className="min-h-11 rounded border border-border px-2 text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-40 disabled:hover:text-muted-foreground sm:min-h-0 sm:py-0.5">
      {button}
    </button>
  );

  return (
    <div data-testid="what-if" className="space-y-2 rounded border border-border/60 p-2 text-xs tabular-nums">
      <div className="flex flex-wrap gap-1.5">
        {preset(levels.target ? `At my target ${priceText(levels.target)}` : "At my target", levels.target ? null : "This plan has no target: add one on its plan card",
          () => { setChosen(clampPrice(levels.target!)); setCrush(false); }, "what-if-target")}
        {preset(levels.stop ? `At my stop ${priceText(levels.stop)}` : "At my stop", levels.stop ? null : "No stop saved in a plan for this position",
          () => { setChosen(clampPrice(levels.stop!)); setCrush(false); }, "what-if-stop")}
        {preset("If earnings is flat", afterReport ? null : "No earnings report before this expiry",
          () => { setChosen(null); setOffset(daysLeft(afterReport!, m.day)); setCrush(true); }, "what-if-earnings")}
        {preset("Reset", null, () => { setChosen(null); setOffset(0); setCrush(false); }, "what-if-reset")}
      </div>
      <label className="grid grid-cols-[3.5rem_1fr] items-center gap-x-2 gap-y-0.5 sm:grid-cols-[3.5rem_1fr_11rem]">
        <span className="text-muted-foreground">{symbol}</span>
        <input type="range" data-testid="what-if-price" aria-label={`${symbol} price`} min={range.lo} max={range.hi} step={range.step} value={price}
          onChange={e => setChosen(Number(e.target.value))} className="w-full accent-foreground" />
        <span className="col-start-2 text-foreground sm:col-start-3">{priceText(price)} <span className="text-muted-foreground">({move >= 0.05 ? "+" : move <= -0.05 ? "−" : ""}{Math.abs(move).toFixed(1)}% from now)</span></span>
      </label>
      <label className="grid grid-cols-[3.5rem_1fr] items-center gap-x-2 gap-y-0.5 sm:grid-cols-[3.5rem_1fr_11rem]">
        <span className="text-muted-foreground">Date</span>
        <input type="range" data-testid="what-if-date" aria-label="Date" min={0} max={span} step={1} value={Math.min(offset, span)} disabled={span === 0}
          onChange={e => { const next = Number(e.target.value); setOffset(next); if (afterReport && addDays(m.day, next) < afterReport) setCrush(false); }}
          className="w-full accent-foreground" />
        <span data-testid="what-if-day" className="col-start-2 text-foreground sm:col-start-3">{dayText}</span>
      </label>
      <p data-testid="what-if-result" className="text-sm text-foreground">
        Worth about {dollars(at.value)} <span className="text-muted-foreground">({priceText(at.share)} a share)</span>
        {at.pnl !== null
          ? <> · P&L <span className={at.pnl >= 0 ? "text-emerald-300" : "text-rose-300"}>{dollars(at.pnl, true)}{at.pnlPct !== null && ` (${pct(at.pnlPct)})`}</span></>
          : <span className="text-muted-foreground"> · P&L unavailable (no cost)</span>}
      </p>
      <WhatIfCurve curve={curve} lo={range.lo} hi={range.hi} now={m.price} chosen={price} breakEven={breakEven} levels={levels}
        pnl={m.cost !== null} onPick={value => setChosen(clampPrice(value))} />
      {crushed && <p data-testid="what-if-crush" className="text-[11px] text-amber-200">
        After the {shortDay(earnings!)} report, IV assumed to fall from {(m.iv * 100).toFixed(0)}% to {(iv * 100).toFixed(0)}% ({Math.round((1 - EARNINGS_IV_KEPT) * 100)}% lower): a plain assumption, not a forecast. The report&apos;s time of day is not published{earnings === m.day ? "; it is today, and if it is already out, today's IV has already dropped and this counts the drop twice" : ""}.
      </p>}
      <p data-testid="what-if-basis" className="text-[11px] text-muted-foreground">
        <span title={CAVEAT} className="cursor-help underline decoration-dotted underline-offset-2">Estimate</span>{" "}
        {m.ivSource === "mark" && m.check
          ? <>from the IV today&apos;s mark implies, {(m.iv * 100).toFixed(0)}%: the quoted IV {(m.givenIv * 100).toFixed(0)}% priced it at {priceText(m.check.model)} against the {priceText(m.check.mark)} mark, more than {(MARK_TOLERANCE * 100).toFixed(0)}% off.</>
          : m.check
            ? <>from IV {(m.iv * 100).toFixed(0)}%, held steady; it prices today at {priceText(m.check.model)} against the {priceText(m.check.mark)} mark.</>
            : <>from IV {(m.iv * 100).toFixed(0)}%, held steady; not checked against a mark (none on the book).</>}
      </p>
    </div>
  );
}

/** P&L (value without a cost) across stock prices on the chosen date: a zero line, today's price (white), break-even at
 * expiry (amber), the plan's entry (sky) and stop (rose), and the chosen price (a dot). Click or drag to pick a price. */
function WhatIfCurve({ curve, lo, hi, now, chosen, breakEven, levels, pnl, onPick }: {
  curve: { price: number; y: number }[]; lo: number; hi: number; now: number; chosen: number; breakEven: number | null;
  levels: PlanLevels; pnl: boolean; onPick: (price: number) => void;
}) {
  const W = 320, H = 72;
  const box = useRef<SVGSVGElement>(null);
  const ys = curve.map(p => p.y);
  const top = Math.max(...ys, 0), bottom = Math.min(...ys, 0);
  const x = (at: number) => (at - lo) / (hi - lo) * W;
  const y = (v: number) => top === bottom ? H / 2 : 2 + (top - v) / (top - bottom) * (H - 4);
  const path = curve.map((p, i) => `${i ? "L" : "M"}${x(p.price).toFixed(1)},${y(p.y).toFixed(1)}`).join("");
  const near = curve.reduce((best, p) => Math.abs(p.price - chosen) < Math.abs(best.price - chosen) ? p : best, curve[0]);
  const pick = (e: PointerEvent<SVGSVGElement>) => {
    const rect = box.current?.getBoundingClientRect();
    if (rect && rect.width > 0) onPick(lo + (e.clientX - rect.left) / rect.width * (hi - lo));
  };
  const marks = [
    { at: now, color: "hsl(var(--foreground))", label: `now ${priceText(now)}`, dash: undefined },
    breakEven !== null ? { at: breakEven, color: "#e9a23b", label: `break-even at expiry ${priceText(breakEven)}`, dash: undefined } : null,
    levels.entry ? { at: levels.entry, color: "#7dd3fc", label: `entry ${priceText(levels.entry)}`, dash: "3 2" } : null,
    levels.stop ? { at: levels.stop, color: "#fda4af", label: `stop ${priceText(levels.stop)}`, dash: "3 2" } : null,
    levels.target ? { at: levels.target, color: "#6ee7b7", label: `target ${priceText(levels.target)}`, dash: "3 2" } : null,
  ].filter((m): m is NonNullable<typeof m> => !!m && m.at >= lo && m.at <= hi);
  return (
    <div className="space-y-1">
      <div className="relative">
      <svg ref={box} data-testid="what-if-curve" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img"
        className="h-[72px] w-full cursor-crosshair touch-none overflow-visible"
        aria-label={`${pnl ? "P&L" : "Value"} on the chosen date from ${priceText(lo)} to ${priceText(hi)}`}
        onPointerDown={e => { e.currentTarget.setPointerCapture(e.pointerId); pick(e); }}
        onPointerMove={e => { if (e.buttons) pick(e); }}>
        <line x1={0} x2={W} y1={y(0)} y2={y(0)} stroke="hsl(var(--muted-foreground))" strokeOpacity={0.4} strokeDasharray="2 2" vectorEffect="non-scaling-stroke" />
        <path d={path} fill="none" stroke="hsl(var(--muted-foreground))" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
        {marks.map(m => <line key={m.label} x1={x(m.at)} x2={x(m.at)} y1={0} y2={H} stroke={m.color} strokeWidth={1} strokeDasharray={m.dash} vectorEffect="non-scaling-stroke" />)}
        <line x1={x(chosen)} x2={x(chosen)} y1={0} y2={H} stroke="hsl(var(--foreground))" strokeOpacity={0.25} vectorEffect="non-scaling-stroke" />
      </svg>
      {/* The dot in HTML so the stretched viewBox does not squash it. */}
      <span data-testid="what-if-dot" className="pointer-events-none absolute size-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-foreground"
        style={{ left: `${x(near.price) / W * 100}%`, top: `${y(near.y)}px` }} />
      </div>
      <p className="flex flex-wrap gap-x-3 text-[11px] text-muted-foreground">
        <span>{pnl ? "P&L" : "Value"} on this date, {priceText(lo)}–{priceText(hi)}:</span>
        {marks.map(m => <span key={m.label} style={{ color: m.color }}>{m.label}</span>)}
      </p>
    </div>
  );
}

/** The same standing in one quiet line, under the selected book row. Nothing for a structure the book cannot read. */
export function OptionStandingLine({ row, rows, fallback = null }: {
  row: DeskThread; rows: readonly DeskThread[]; fallback?: { last: number; at: number } | null;
}) {
  const read = useStanding(row, rows, fallback);
  if (read === null || read === "unknown" || read === "incomplete") return null;
  const { standing: s, stock, closing } = read;
  const parts: string[] = [];
  if (s.breakEven !== null) parts.push(`BE ${priceText(s.breakEven)}${s.toBreakEven ? ` ${s.toBreakEven.past ? "passed" : pct(s.toBreakEven.pct)}` : ""}`);
  if (s.timeValue !== null && s.timeValue >= 0) parts.push(`${dollars(s.timeValue)} time value`);
  if (s.decayPerDay !== null) parts.push(`${dollars(s.decayPerDay, true)}/day`);
  if (s.perDollar !== null) parts.push(`${dollars(s.perDollar, true)} per $1`);
  if (s.ivPct !== null) parts.push(`IV ${s.ivPct.toFixed(0)}%`);
  // A missing Greeks read is said once, in the chart's standing above, not again on the book row.
  if (!parts.length) return <CloseButtons closing={closing} className="px-3 pb-2" />;
  return (
    <>
      <p data-testid="book-standing" className={cn("truncate px-3 pb-1.5 text-[11px] tabular-nums text-muted-foreground", stock && !stock.live && "opacity-70")}>
        {parts.join(" · ")}
      </p>
      <CloseButtons closing={closing} className="px-3 pb-2" />
    </>
  );
}
