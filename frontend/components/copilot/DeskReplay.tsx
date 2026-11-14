"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries, ColorType, CrosshairMode, HistogramSeries, LineStyle, createChart, createSeriesMarkers,
  type IChartApi, type IPriceLine, type ISeriesApi, type ISeriesMarkersPluginApi, type SeriesMarker, type Time, type UTCTimestamp,
} from "lightweight-charts";
import { Pause, Play, SkipForward } from "lucide-react";
import { PaperRefused, orderKey, type PaperPosition, type PaperStats } from "@/lib/paperBook";
import {
  REPLAY_EVENT, SPEEDS, autoReplay, cancelReplay, expiryShort, msPerBar, orderReplay, previewReplay, replayBadge, replayBars, replayDate,
  replayHome, replayOptions, replaySymbols, replayTime, shownBars, startReplay, stepReplay,
  type ReplayAsk, type ReplayBar, type ReplayHappening, type ReplayHome, type ReplayOptions, type ReplayQuote, type ReplayScore,
  type ReplayTrade, type ReplayView, type Speed,
} from "@/lib/paperReplay";
import { cn } from "@/lib/utils";

/**
 * Replay on the desk (docs/copilot-lab.md § Paper replay): pick a past trading day and a ticker, and the day plays
 * forward from 9:30 ET a bar at a time (play, pause, 1×/5×/20×/60×, one bar), with the paper ticket priced from the
 * replayed bars. Only bars that ended by the replay clock are drawn; nothing else of the live desk shows while it runs,
 * and leaving puts the live desk back exactly as it was (it stays mounted underneath). Shares, or one call or put that
 * traded that day priced from its own trade bars (on a day older than the contracts' minute history, options are off
 * with the reason). Replay trades are their own runs, scored apart from live paper and real trades.
 */

const LABEL = "text-[11px] font-medium uppercase tracking-wide text-muted-foreground";
const BUTTON = "inline-flex min-h-11 items-center justify-center gap-1.5 rounded-md border px-3 text-xs font-medium hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-45 sm:min-h-8";
const QUIET = "inline-flex min-h-11 items-center rounded-md px-3 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8";
const INPUT = "min-h-11 rounded-md border bg-background px-2 text-sm tabular-nums sm:min-h-8 sm:text-xs";
const AMBER = "border-amber-400/70 text-amber-100";

const usd = (n: number) => `$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const signed = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : ""}${usd(n)}`;
const toneOf = (n: number | null | undefined) => n == null || n === 0 ? "text-muted-foreground" : n > 0 ? "text-emerald-300" : "text-rose-300";
const px = (n: number) => n.toFixed(2);
const words = (e: unknown) => e instanceof Error ? e.message : "Not filled.";
/** What a row names: the ticker for shares, the contract ("NBIS $100 Call 11/21/26") for an option. */
const named = (x: { instrument?: string; symbol: string; label: string }) => x.instrument === "option" ? x.label : x.symbol;

/** "10:42 AM ET — Limit filled: bought 10 NBIS at 99.10." */
function happeningText(h: ReplayHappening): string {
  const when = `${replayTime(h.at)} ET`;
  const qty = h.quantity != null ? `${h.quantity.toLocaleString("en-US")} ` : "";
  const pnl = h.pnl != null ? ` (${signed(h.pnl)})` : "";
  const name = named(h);
  switch (h.kind) {
    case "limit": return `${when}: limit filled, ${h.side === "close" ? "sold" : "bought"} ${qty}${name} at ${px(h.price)}${pnl}.`;
    case "stop": case "target": return `${when}: auto exit at the ${h.kind}, sold ${qty}${name} at ${px(h.price)}${pnl}.`;
    case "touch": return `${when}: ${h.symbol} touched your ${h.level} ${px(h.price)}. Close automatically is off, so nothing was sold.`;
    case "flat": return `${when}: the day closed, sold ${qty}${name} at ${px(h.price)}${pnl}.`;
    case "left": return `${when}: you left the replay, sold ${qty}${name} at ${px(h.price)}${pnl}.`;
    case "expired": return `${when}: ${qty}${name} expired, settled at ${px(h.price)} from ${h.symbol}'s ${h.stock != null ? px(h.stock) : ""} close${pnl}.`;
  }
}

// --- the chart -------------------------------------------------------------------------------------------------------

const clockFmt = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });

type Parts = { chart: IChartApi; candles: ISeriesApi<"Candlestick">; volume: ISeriesApi<"Histogram">; markers: ISeriesMarkersPluginApi<Time>; lines: IPriceLine[] };

/** The replayed candles (only bars that ended by the clock), volume, his replay fills and his stop, target and limit lines. */
export function ReplayChart({ symbol, bars, positions, closed, orders }: {
  symbol: string; bars: ReplayBar[]; positions: PaperPosition[]; closed: ReplayTrade[]; orders: ReplayView["orders"];
}) {
  const host = useRef<HTMLDivElement>(null);
  const parts = useRef<Parts | null>(null);
  const drawn = useRef<{ first: number | null; count: number }>({ first: null, count: 0 });

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const chart = createChart(element, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#0e0e10" }, textColor: "#8d8d96", fontSize: 10 },
      grid: { vertLines: { color: "#1b1b1e" }, horzLines: { color: "#1b1b1e" } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#27272a", scaleMargins: { top: 0.08, bottom: 0.22 } },
      timeScale: { borderColor: "#27272a", secondsVisible: false, rightOffset: 6,
        // One day on the axis: clock times only.
        tickMarkFormatter: (time: Time) => typeof time === "number" ? clockFmt.format(time * 1000) : null },
      localization: { timeFormatter: (time: Time) => typeof time === "number" ? `${clockFmt.format(time * 1000)} ET` : "" },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      kineticScroll: { mouse: false, touch: false },
    });
    const candles = chart.addSeries(CandlestickSeries, { upColor: "#2bc9a4", downColor: "#ee617a", wickUpColor: "#2bc9a4", wickDownColor: "#ee617a", borderVisible: false });
    const volume = chart.addSeries(HistogramSeries, { priceScaleId: "", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    parts.current = { chart, candles, volume, markers: createSeriesMarkers(candles, []), lines: [] };
    drawn.current = { first: null, count: 0 };
    return () => { parts.current = null; chart.remove(); };
  }, []);

  // Bars only ever grow while the clock runs: append them (the view follows the newest bar); a new day redraws.
  useEffect(() => {
    const p = parts.current;
    if (!p) return;
    const candle = (b: ReplayBar) => ({ time: b.time as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close });
    const vol = (b: ReplayBar) => ({ time: b.time as UTCTimestamp, value: b.volume, color: b.close >= b.open ? "#2bc9a455" : "#ee617a55" });
    const first = bars[0]?.time ?? null;
    if (first !== drawn.current.first || bars.length < drawn.current.count) {
      p.candles.setData(bars.map(candle));
      p.volume.setData(bars.map(vol));
      if (bars.length) p.chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, bars.length - 150), to: bars.length + 6 });
    } else {
      for (const b of bars.slice(drawn.current.count)) { p.candles.update(candle(b)); p.volume.update(vol(b)); }
    }
    drawn.current = { first, count: bars.length };
  }, [bars]);

  // His replay fills as arrows; his stop, target and working limits as lines.
  useEffect(() => {
    const p = parts.current;
    if (!p) return;
    const minute = (t: number) => (Math.floor(t / 60) * 60) as UTCTimestamp;
    const last = bars.length ? bars[bars.length - 1].time : 0;
    const marks: SeriesMarker<Time>[] = [];
    for (const pos of [...positions, ...closed]) {
      if (pos.symbol !== symbol) continue;
      marks.push({ time: minute(pos.opened_at), position: "belowBar", shape: "arrowUp", color: "#fef3c7", text: `P ${pos.quantity}` });
      for (const exit of pos.exits ?? []) marks.push({ time: minute(exit.at), position: "aboveBar", shape: "arrowDown", color: "#fde68a", text: `P ${exit.quantity}` });
    }
    p.markers.setMarkers(marks.filter(m => (m.time as number) <= last).sort((a, b) => (a.time as number) - (b.time as number)));
    for (const line of p.lines) p.candles.removePriceLine(line);
    p.lines = [];
    const add = (price: number, color: string, title: string, dashed = false) =>
      p.lines.push(p.candles.createPriceLine({ price, color, lineWidth: 1, lineStyle: dashed ? LineStyle.Dashed : LineStyle.Solid, axisLabelVisible: true, title }));
    for (const pos of positions) {
      if (pos.symbol !== symbol) continue;
      if (pos.stop != null) add(pos.stop, "#fca5a5", "stop");
      if (pos.target != null) add(pos.target, "#86efac", "target");
    }
    // An option's limit is a premium, not a stock price: only share limits are drawn on the stock's chart.
    for (const o of orders) if (o.symbol === symbol && o.instrument === "stock") add(o.limit, "#fcd34d", `limit ${o.side === "close" ? "sell" : "buy"}`, true);
  }, [bars, positions, closed, orders, symbol]);

  return <div ref={host} data-testid="replay-chart" role="img" aria-label={`${symbol} replayed one-minute candles up to the replay clock`}
    className="h-[300px] w-full overflow-hidden rounded-md border sm:h-[420px]" />;
}

// --- the scorecard ---------------------------------------------------------------------------------------------------

function ScoreLine({ score }: { score: PaperStats }) {
  return (
    <p data-testid="replay-score" className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs tabular-nums text-muted-foreground">
      <span>{score.trades} trade{score.trades === 1 ? "" : "s"}</span>
      <span className={toneOf(score.pnl)}>{signed(score.pnl)}</span>
      {score.win_rate != null && <span>{score.win_rate}% won</span>}
      {score.avg_win != null && <span>avg win {usd(score.avg_win)}</span>}
      {score.avg_loss != null && <span>avg loss {usd(score.avg_loss)}</span>}
    </p>
  );
}

function TradeRows({ trades, days = true }: { trades: ReplayTrade[]; days?: boolean }) {
  return (
    <ul className="divide-y divide-border/60">
      {trades.map(t => (
        <li key={t.id} data-testid="replay-trade" className="space-y-0.5 py-1.5 text-xs">
          <div className="flex flex-wrap items-baseline gap-x-2">
            {days && <span className="text-muted-foreground">{replayDate(t.day)}</span>}
            <span className="font-medium text-foreground" data-testid="replay-trade-name">{t.quantity.toLocaleString("en-US")} {named(t)}</span>
            <span className="tabular-nums text-muted-foreground">in {px(Math.abs(t.per_share))} · {replayTime(t.opened_at)}</span>
            <span className={cn("ml-auto tabular-nums", toneOf(t.realized))}>{signed(t.realized)}</span>
          </div>
          {t.verdict && <p className="text-muted-foreground">{t.verdict.text}</p>}
          {t.note && <p className="text-foreground/80">“{t.note}”</p>}
        </li>
      ))}
    </ul>
  );
}

/** Replay practice on the live desk, under the Paper section: every replay's closed trades, apart from live paper and
 *  real trades. Read on mount and after a replay changes; nothing shows until there is a replay. */
export function ReplayPractice() {
  const [card, setCard] = useState<ReplayScore | null>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    const load = () => replayHome(false, controller.signal).then(setCard).catch(() => { /* the section stays hidden */ });
    load();
    window.addEventListener(REPLAY_EVENT, load);
    return () => { controller.abort(); window.removeEventListener(REPLAY_EVENT, load); };
  }, []);
  if (!card || card.runs.length === 0) return null;
  return (
    <section aria-label="Replay practice" data-testid="replay-practice" className="space-y-1.5 rounded-md border border-dashed px-3 py-2">
      <button type="button" aria-expanded={open} onClick={() => setOpen(o => !o)} className="flex min-h-11 w-full items-center gap-2 text-left sm:min-h-0">
        <span className={LABEL}>Replay practice</span>
        <span className="text-[11px] text-muted-foreground">past days · not live paper</span>
        <span className="ml-auto text-xs text-muted-foreground">{open ? "▴" : "▾"}</span>
      </button>
      <ScoreLine score={card.score} />
      {open && (card.trades.length ? <TradeRows trades={card.trades} /> : <p className="text-xs text-muted-foreground">No closed replay trades yet.</p>)}
    </section>
  );
}

// --- the ticket ------------------------------------------------------------------------------------------------------

/** The confirm line: what the replayed bar says and the assumed spread, so the price is never mistaken for a quote. */
function quoteWords(q: ReplayQuote, buying: boolean) {
  if (q.instrument === "option") {
    const range = `${px(q.low ?? q.close)}–${px(q.high ?? q.close)}`;
    const from = q.half_from === "range" ? `half that minute's ${range} range`
      : `the ${q.half_from === "min" ? "1¢ minimum" : "0.5% floor"} (that minute's ${range} range was narrower)`;
    return `The contract's ${replayTime(q.bar)} trade bar closed at ${px(q.close)}; ${buying ? "buying pays" : "selling takes"} that `
      + `${buying ? "plus" : "less"} ${px(q.half_spread)} = ${px(buying ? q.ask : q.bid)} a share, ×${q.multiplier ?? 100} a contract. `
      + `Trades carry no bid or ask: est. spread ±$${px(q.half_spread)}, from ${from}.${q.stock != null ? ` The stock was ${px(q.stock)}.` : ""}`;
  }
  const bps = (q.spread_bps / 100).toFixed(2).replace(/0$/, "");
  return `The ${replayTime(q.bar)} bar closed at ${px(q.close)}; ${buying ? "buying pays" : "selling takes"} that ${buying ? "plus" : "less"} a `
    + `${px(q.half_spread)} half-spread = ${px(buying ? q.ask : q.bid)}. Replayed bars carry no bid or ask, so the spread is assumed: ${bps}% of the price, each half rounded up to the cent.`;
}

type Picked = { option_type: "call" | "put"; expiry: string; strike: number; label: string };

/** The replay ticket's option picker: a call or a put, an expiration, then the strikes around the stock's price at the
 *  clock whose contracts traded that day (each with its last trade by the clock), or a strike he names. Each contract
 *  is checked once, when he picks; contracts with no trades that day are not offered. */
function OptionPicker({ day, symbol, at, picked, onPick }: {
  day: string; symbol: string; at: number; picked: Picked | null; onPick(p: Picked | null): void;
}) {
  const [kind, setKind] = useState<"call" | "put">(picked?.option_type ?? "call");
  const [expiry, setExpiry] = useState<string | null>(picked?.expiry ?? null);
  const [found, setFound] = useState<ReplayOptions | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [typed, setTyped] = useState("");

  const load = useCallback(async (ask: { option_type?: "call" | "put"; expiry?: string; strike?: number }) => {
    setChecking(true); setError(null);
    try {
      const next = await replayOptions({ day, symbol, at, ...ask });
      setFound(prev => ask.strike != null && prev?.contracts && next.contracts
        ? { ...next, contracts: [...prev.contracts.filter(c => c.strike !== ask.strike), ...next.contracts].sort((a, b) => a.strike - b.strike),
          missing: [...new Set([...prev.missing, ...next.missing])].sort((a, b) => a - b) }
        : next);
    } catch (e) { setError(words(e)); } finally { setChecking(false); }
  }, [day, symbol, at]);
  // The expirations once, when the picker opens (at the clock then): no contract is read until he picks an expiration.
  const opened = useRef(at);
  useEffect(() => {
    const controller = new AbortController();
    replayOptions({ day, symbol, at: opened.current }, controller.signal).then(setFound)
      .catch(e => { if (!controller.signal.aborted) setError(words(e)); });
    return () => controller.abort();
  }, [day, symbol]);

  const pick = (k: "call" | "put", e: string) => { setKind(k); setExpiry(e); onPick(null); void load({ option_type: k, expiry: e }); };
  const strikes = found?.option_type === kind && found.expiry === expiry ? found : null;
  return (
    <div data-testid="replay-option-picker" className="space-y-1.5 rounded-md border p-2 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <div role="radiogroup" aria-label="Call or put" className="inline-flex rounded-md border">
          {(["call", "put"] as const).map(k => (
            <button key={k} type="button" role="radio" aria-checked={kind === k} onClick={() => expiry ? pick(k, expiry) : setKind(k)}
              className={cn("min-h-11 px-3 first:rounded-l-md last:rounded-r-md sm:min-h-8", kind === k ? "bg-amber-400/15 text-amber-100" : "text-muted-foreground hover:bg-secondary")}>
              {k === "call" ? "Call" : "Put"}
            </button>
          ))}
        </div>
        {found?.price != null && <span className="tabular-nums text-muted-foreground">{symbol} {px(found.price)} at {replayTime(found.at)}</span>}
      </div>
      {found && found.expiries.length > 0 && (
        <div role="radiogroup" aria-label="Expiration" className="flex flex-wrap gap-1.5">
          {found.expiries.map(e => (
            <button key={e} type="button" role="radio" aria-checked={expiry === e} data-testid="replay-expiry" onClick={() => pick(kind, e)}
              className={cn("min-h-11 rounded-md border px-2 sm:min-h-8", expiry === e ? "border-amber-400/70 bg-amber-400/10 text-amber-100" : "text-muted-foreground hover:bg-secondary")}>
              {expiryShort(e)}{e === day ? " · 0DTE" : ""}
            </button>
          ))}
        </div>
      )}
      {found && !expiry && <p className="text-muted-foreground">Pick an expiration: the strikes near {px(found.price ?? 0)} are checked for trades that day.</p>}
      {checking && <p className="text-muted-foreground" role="status">Checking which contracts traded that day…</p>}
      {strikes?.contracts && (
        <>
          {strikes.contracts.length > 0 ? (
            <div role="radiogroup" aria-label="Contract" className="flex flex-wrap gap-1.5">
              {strikes.contracts.map(c => {
                const on = picked?.strike === c.strike && picked.expiry === strikes.expiry && picked.option_type === strikes.option_type;
                return (
                  <button key={c.occ} type="button" role="radio" aria-checked={on} data-testid="replay-contract"
                    onClick={() => onPick({ option_type: kind, expiry: strikes.expiry!, strike: c.strike, label: c.label })}
                    className={cn("min-h-11 rounded-md border px-2 tabular-nums sm:min-h-8", on ? "border-amber-400/70 bg-amber-400/10 text-amber-100" : "text-foreground hover:bg-secondary")}>
                    ${c.strike}<span className="ml-1 text-muted-foreground">{px(c.last.price)}</span>
                  </button>
                );
              })}
            </div>
          ) : !checking && <p data-testid="replay-no-contracts" className="text-amber-300">No {kind} near {px(strikes.price ?? 0)} for {expiryShort(strikes.expiry!)} has traded by {replayTime(strikes.at)}.</p>}
          {strikes.missing.length > 0 && <p className="text-muted-foreground">Not offered, no trade by {replayTime(strikes.at)}: {strikes.missing.map(m => `$${m}`).join(", ")}.</p>}
          {strikes.waiting.length > 0 && (
            <p className="text-amber-300">Not checked yet: {strikes.waiting.map(m => `$${m}`).join(", ")}. {strikes.waiting_reason}{" "}
              <button type="button" onClick={() => void load({ option_type: kind, expiry: strikes.expiry! })} className="underline">Check again</button>
            </p>
          )}
          <div className="flex flex-wrap items-center gap-1.5">
            <label className="flex items-center gap-1.5 text-muted-foreground">Other strike $
              <input aria-label="Replay option strike" inputMode="decimal" value={typed} onChange={e => setTyped(e.target.value.replace(/[^\d.]/g, ""))} className={cn(INPUT, "w-20")} />
            </label>
            <button type="button" disabled={checking || !(Number(typed) > 0)} onClick={() => void load({ option_type: kind, expiry: strikes.expiry!, strike: Number(typed) })} className={BUTTON}>Check</button>
          </div>
          <p className="text-[11px] text-muted-foreground">Last trade by {replayTime(strikes.at)} ET; nothing after the clock is used. Review prices it again at the clock.</p>
        </>
      )}
      {error && <p role="alert" className="text-amber-300">{error}</p>}
    </div>
  );
}

function Ticket({ view, at, symbol, options, onView, pause }: {
  view: ReplayView; at: number; symbol: string; options: string; onView(view: ReplayView): void; pause(): void;
}) {
  const off = view.run.options_off ?? null;
  const [what, setWhat] = useState<"stock" | "option">("stock");
  const [picked, setPicked] = useState<Picked | null>(null);
  const option = what === "option" && !off;
  const [qty, setQty] = useState("10");
  const [type, setType] = useState<"market" | "limit">("market");
  const [limit, setLimit] = useState("");
  const [stop, setStop] = useState("");
  const [target, setTarget] = useState("");
  const [auto, setAuto] = useState(false);
  const [note, setNote] = useState("");
  const [quoted, setQuoted] = useState<{ at: number; quote: ReplayQuote } | null>(null);
  // A confirm holds only at the moment it was priced: once the clock moves on, Review prices it again.
  const preview = quoted && quoted.at === at ? quoted.quote : null;
  const setPreview = (quote: ReplayQuote | null) => setQuoted(quote ? { at, quote } : null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [key, setKey] = useState("");
  const qtyN = Number(qty);
  const limitN = Number(limit);
  const level = (text: string) => text.trim() ? Number(text) : null;
  const ask = (): ReplayAsk => ({ action: "open", order_type: type, limit_price: type === "limit" ? limitN : null, quantity: qtyN, symbol,
    ...(option && picked ? { instrument: "option" as const, option_type: picked.option_type, expiry: picked.expiry, strike: picked.strike } : { instrument: "stock" as const }),
    note: note.trim() || null, stop: level(stop), target: level(target), auto });
  const valid = Number.isInteger(qtyN) && qtyN > 0 && (type === "market" || limitN > 0) && (!option || !!picked);
  const name = option && picked ? picked.label : symbol;
  const choose = (next: "stock" | "option") => { setWhat(next); setPreview(null); setLimit(""); if (next === "option" && qty === "10") setQty("1"); if (next === "stock" && qty === "1") setQty("10"); };

  const review = async () => {
    pause();
    setBusy(true); setError(null); setDone(null); setKey(orderKey());
    try {
      const found = await previewReplay(view.run.id, at, ask());
      setPreview(found);
      if (type === "limit" && !limit) setLimit(px(found.close));
    } catch (e) { setPreview(null); setError(words(e)); } finally { setBusy(false); }
  };
  const send = async () => {
    setBusy(true); setError(null);
    try {
      const reply = await orderReplay(view.run.id, at, ask(), key);
      onView(reply);
      setDone(reply.filled ? `Paper (replay): bought ${qtyN} ${name} at ${px(-(reply.filled.per_share ?? 0))}, ${replayTime(reply.filled.at)} ET.`
        : reply.working ? `Paper limit working: buy ${qtyN} ${name} at ${px(limitN)} or better until the replayed close or your cancel.` : "Already sent.");
      setPreview(null);
    } catch (e) { setError(words(e)); } finally { setBusy(false); }
  };

  return (
    <section aria-label="Replay ticket" data-testid="replay-ticket" className="space-y-2 rounded-md border border-dashed border-amber-400/50 p-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-200">Paper · replay · not real money</p>
        <div role="radiogroup" aria-label="What to trade" className="ml-auto inline-flex rounded-md border text-xs">
          <button type="button" role="radio" aria-checked={!option} onClick={() => choose("stock")}
            className={cn("min-h-11 rounded-l-md px-3 sm:min-h-8", !option ? "bg-amber-400/15 text-amber-100" : "text-muted-foreground hover:bg-secondary")}>{symbol} shares</button>
          <button type="button" role="radio" aria-checked={option} disabled={!!off} title={off ?? undefined} data-testid={off ? "replay-options-off" : "replay-option"}
            onClick={() => choose("option")}
            className={cn("min-h-11 rounded-r-md px-3 disabled:cursor-not-allowed disabled:opacity-45 sm:min-h-8", option ? "bg-amber-400/15 text-amber-100" : "text-muted-foreground hover:bg-secondary")}>Option</button>
        </div>
      </div>
      {off ? <p className="text-[11px] text-muted-foreground" data-testid="replay-options-reason">{off}</p>
        : option && <p className="text-[11px] text-muted-foreground" data-testid="replay-options-reason">{options}</p>}
      {option && <OptionPicker day={view.run.day} symbol={symbol} at={at} picked={picked} onPick={p => { setPicked(p); setPreview(null); setLimit(""); }} />}
      <div className="flex flex-wrap items-center gap-2">
        <div role="radiogroup" aria-label="Order type" className="inline-flex rounded-md border text-xs">
          {(["market", "limit"] as const).map(t => (
            <button key={t} type="button" role="radio" aria-checked={type === t} onClick={() => { setType(t); setPreview(null); }}
              className={cn("min-h-11 px-3 first:rounded-l-md last:rounded-r-md sm:min-h-8", type === t ? "bg-amber-400/15 text-amber-100" : "text-muted-foreground hover:bg-secondary")}>
              {t === "market" ? "Market" : "Limit"}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">{option ? "Contracts" : "Shares"}
          <input aria-label="Replay quantity" inputMode="numeric" value={qty} onChange={e => { setQty(e.target.value.replace(/[^\d]/g, "")); setPreview(null); }} className={cn(INPUT, "w-20")} />
        </label>
        {type === "limit" && (
          <label className="flex items-center gap-1.5 text-xs text-muted-foreground">Limit $
            <input aria-label="Replay limit price" inputMode="decimal" value={limit} onChange={e => { setLimit(e.target.value.replace(/[^\d.]/g, "")); setPreview(null); }} className={cn(INPUT, "w-20")} />
          </label>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">{option ? `Stop (${symbol} $)` : "Stop"}
          <input aria-label="Replay stop" inputMode="decimal" placeholder="$" value={stop} onChange={e => { setStop(e.target.value.replace(/[^\d.]/g, "")); setPreview(null); }} className={cn(INPUT, "w-20")} />
        </label>
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">{option ? `Target (${symbol} $)` : "Target"}
          <input aria-label="Replay target" inputMode="decimal" placeholder="$" value={target} onChange={e => { setTarget(e.target.value.replace(/[^\d.]/g, "")); setPreview(null); }} className={cn(INPUT, "w-20")} />
        </label>
        <label className="flex min-h-11 items-center gap-1.5 text-xs text-muted-foreground sm:min-h-0">
          <input type="checkbox" checked={auto} onChange={e => { setAuto(e.target.checked); setPreview(null); }} disabled={!stop.trim() && !target.trim()} />Close automatically at stop/target
        </label>
      </div>
      <input aria-label="Replay note" maxLength={280} placeholder="Why (optional, one line)" value={note} onChange={e => { setNote(e.target.value); setPreview(null); }} className={cn(INPUT, "w-full")} />
      {preview && (
        <div data-testid="replay-confirm" className="space-y-1 rounded-md bg-amber-400/5 p-2 text-xs">
          {preview.fills_now ? (
            <p className="text-sm tabular-nums text-foreground">Buy {preview.quantity.toLocaleString("en-US")} {name} at {px(-(preview.per_share ?? 0))}: costs {usd(preview.cash ?? 0)}.</p>
          ) : (
            <p className="text-sm tabular-nums text-foreground">Buy limit {preview.quantity.toLocaleString("en-US")} {name} at {px(preview.limit ?? limitN)}: holds {usd(preview.reserve ?? 0)} until it fills.</p>
          )}
          <p className="text-muted-foreground">{quoteWords(preview, true)}</p>
          {!preview.fills_now && <p className="text-muted-foreground">{preview.instrument === "option"
            ? "It fills on a later minute the contract trades whose low plus that minute's half-spread reaches your limit: at the limit, or at that minute's open plus the half-spread when lower. A minute without a trade fills nothing. A day order: until the replayed close or your cancel."
            : <>It fills on a later bar whose low plus the half-spread reaches your limit: at the limit, or at that bar&apos;s open plus the half-spread when lower. A day order: until the replayed close or your cancel.</>}</p>}
          {preview.instrument === "option" && (stop.trim() || target.trim()) && <p className="text-muted-foreground">Stop and target are {symbol} prices, judged on the stock&apos;s bars; an automatic exit sells at the contract&apos;s next traded minute.</p>}
          {preview.buying_power_after != null && <p className="text-muted-foreground">Paper buying power after: {preview.buying_power_after < 0 ? "−" : ""}{usd(preview.buying_power_after)}.</p>}
        </div>
      )}
      {error && <p role="alert" data-testid="replay-refused" className="text-xs text-amber-300">{error}</p>}
      {done && <p role="status" data-testid="replay-done" className="text-xs text-emerald-300">{done}</p>}
      <div className="flex flex-wrap gap-2">
        {preview
          ? <button type="button" data-testid="replay-fill" disabled={busy || !valid} onClick={send} className={cn(BUTTON, AMBER)}>{preview.fills_now ? "Fill on paper" : "Place limit on paper"}</button>
          : <button type="button" data-testid="replay-review" disabled={busy || !valid || view.ended} onClick={review} className={cn(BUTTON, AMBER)}>Review at {replayTime(at)}</button>}
        {preview && <button type="button" onClick={() => setPreview(null)} className={QUIET}>Cancel</button>}
      </div>
      <p className="text-[11px] text-muted-foreground">Trading pauses the replay; press Play to go on.</p>
    </section>
  );
}

// --- the replay run's book -------------------------------------------------------------------------------------------

function Position({ p, view, at, onView, pause }: { p: PaperPosition; view: ReplayView; at: number; onView(v: ReplayView): void; pause(): void }) {
  const [quoted, setQuoted] = useState<{ at: number; quote: ReplayQuote } | null>(null);
  const selling = quoted && quoted.at === at ? quoted.quote : null;  // priced at this moment only
  const setSelling = (quote: ReplayQuote | null) => setQuoted(quote ? { at, quote } : null);
  const [limit, setLimit] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [key, setKey] = useState("");
  const free = p.remaining - (p.held ?? 0);
  const close = (type: "market" | "limit"): ReplayAsk => ({ action: "close", order_type: type, position_id: p.id, quantity: free, limit_price: type === "limit" ? Number(limit) : null });
  const review = async () => {
    pause(); setBusy(true); setError(null); setKey(orderKey());
    try { const q = await previewReplay(view.run.id, at, close("market")); setSelling(q); setLimit(px(q.close)); } catch (e) { setError(words(e)); } finally { setBusy(false); }
  };
  const send = async (type: "market" | "limit") => {
    setBusy(true); setError(null);
    try { onView(await orderReplay(view.run.id, at, close(type), key)); setSelling(null); } catch (e) { setError(words(e)); } finally { setBusy(false); }
  };
  const toggle = async (on: boolean) => {
    pause(); setError(null);
    try { onView(await autoReplay(view.run.id, at, p.id, on, orderKey())); } catch (e) { setError(words(e)); }
  };
  const mark = p.mark;
  return (
    <li data-testid="replay-position" className="space-y-1 py-2 text-xs">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-sm font-medium text-foreground">{p.remaining.toLocaleString("en-US")} {named(p)}</span>
        <span className="tabular-nums text-muted-foreground">in {px(Math.abs(p.per_share))}{mark ? ` · now ${px(mark.per_share)}` : ""}</span>
        <span className={cn("ml-auto tabular-nums", toneOf(mark?.pnl))}>{mark ? signed(mark.pnl) : "—"}</span>
      </div>
      {(p.stop != null || p.target != null) && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-muted-foreground">
          {p.stop != null && <span>stop {px(p.stop)}{p.touched?.stop ? ` · touched ${replayTime(p.touched.stop)}` : ""}</span>}
          {p.target != null && <span>target {px(p.target)}{p.touched?.target ? ` · touched ${replayTime(p.touched.target)}` : ""}</span>}
          <label className="flex min-h-11 items-center gap-1.5 sm:min-h-0">
            <input type="checkbox" checked={!!p.auto} onChange={e => toggle(e.target.checked)} aria-label={`Close ${p.symbol} automatically at stop/target`} />Close automatically
          </label>
          {p.exiting && <span className="text-amber-200">{p.instrument === "option" ? "selling at the contract's next traded minute" : <>selling at the next bar&apos;s open</>}</span>}
        </div>
      )}
      {p.note && <p className="text-foreground/80">“{p.note}”</p>}
      {selling ? (
        <div data-testid="replay-sell-confirm" className="space-y-1 rounded-md bg-amber-400/5 p-2">
          <p className="text-sm tabular-nums text-foreground">Sell {selling.quantity.toLocaleString("en-US")} {named(p)} at {px(selling.bid)}: {selling.pnl != null ? `${selling.pnl >= 0 ? "makes" : "loses"} ${usd(selling.pnl)}` : ""}.</p>
          <p className="text-muted-foreground">{quoteWords(selling, false)}</p>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" data-testid="replay-sell" disabled={busy} onClick={() => send("market")} className={cn(BUTTON, AMBER)}>Sell on paper</button>
            <label className="flex items-center gap-1.5 text-muted-foreground">or a sell limit $
              <input aria-label={`Sell limit for ${p.symbol}`} inputMode="decimal" value={limit} onChange={e => setLimit(e.target.value.replace(/[^\d.]/g, ""))} className={cn(INPUT, "w-20")} />
            </label>
            <button type="button" disabled={busy || !(Number(limit) > 0)} onClick={() => send("limit")} className={BUTTON}>Place sell limit</button>
            <button type="button" onClick={() => setSelling(null)} className={QUIET}>Cancel</button>
          </div>
        </div>
      ) : free > 0 && !view.ended && <button type="button" data-testid="replay-close" disabled={busy} onClick={review} className={BUTTON}>Sell…</button>}
      {error && <p role="alert" className="text-amber-300">{error}</p>}
    </li>
  );
}

function RunBook({ view, at, onView, pause, log }: { view: ReplayView; at: number; onView(v: ReplayView): void; pause(): void; log: ReplayHappening[] }) {
  const acct = view.account;
  const cancel = async (id: string) => { pause(); try { onView(await cancelReplay(view.run.id, at, id)); } catch { /* the next step shows it */ } };
  return (
    <section aria-label="This replay" data-testid="replay-book" className="space-y-2">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
        <span className={LABEL}>This replay</span>
        <span className="text-xs tabular-nums text-muted-foreground">cash {usd(acct.cash)} · buying power {usd(acct.buying_power)}</span>
        {acct.pnl != null && <span className={cn("ml-auto text-xs tabular-nums", toneOf(acct.pnl))}>{signed(acct.pnl)}</span>}
      </div>
      {view.positions.length > 0 && <ul className="divide-y divide-border/60">{view.positions.map(p => <Position key={p.id} p={p} view={view} at={at} onView={onView} pause={pause} />)}</ul>}
      {view.orders.length > 0 && (
        <ul className="space-y-1">
          {view.orders.map(o => (
            <li key={o.id} data-testid="replay-order" className="flex flex-wrap items-center gap-2 text-xs">
              <span className="text-foreground">{o.side === "close" ? "Sell" : "Buy"} limit {o.quantity.toLocaleString("en-US")} {named(o)} at {px(o.limit)}</span>
              <span className="text-muted-foreground">working</span>
              <button type="button" onClick={() => cancel(o.id)} className={QUIET}>Cancel</button>
            </li>
          ))}
        </ul>
      )}
      {view.positions.length === 0 && view.orders.length === 0 && view.closed.length === 0 && (
        <p className="text-xs text-muted-foreground">Nothing yet. Play the day and use the ticket when you would trade.</p>
      )}
      {log.length > 0 && (
        <ul aria-label="What happened" data-testid="replay-log" className="space-y-0.5 text-xs text-muted-foreground">
          {log.slice(-5).reverse().map((h, i) => <li key={`${h.at}-${h.kind}-${i}`}>{happeningText(h)}</li>)}
        </ul>
      )}
      {view.closed.length > 0 && (
        <div className="space-y-1">
          <div className="flex items-baseline gap-2"><span className={LABEL}>Closed in this replay</span><ScoreLine score={view.score} /></div>
          <TradeRows trades={view.closed} days={false} />
        </div>
      )}
      {(view.positions.length > 0 || view.orders.length > 0) && !view.ended && (
        <p className="text-[11px] text-muted-foreground">Leaving sells what is open at the clock&apos;s price and ends working orders; at the replayed close everything is sold.</p>
      )}
    </section>
  );
}

// --- the replay mode -------------------------------------------------------------------------------------------------

type Loaded = { key: string; bars: ReplayBar[]; open_at: number; close_at: number };

export default function DeskReplay({ symbol, onLeave }: { symbol: string | null; onLeave(): void }) {
  const [home, setHome] = useState<ReplayHome | null>(null);
  const [homeError, setHomeError] = useState<string | null>(null);
  const [day, setDay] = useState<string | null>(null);
  const [ticker, setTicker] = useState(symbol ?? "");
  const [typed, setTyped] = useState(false);
  const [suggested, setSuggested] = useState<{ day: string; symbols: { symbol: string; why: string }[] } | null>(null);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [missing, setMissing] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [view, setView] = useState<ReplayView | null>(null);
  const [at, setAt] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<Speed>(5);
  const [log, setLog] = useState<ReplayHappening[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [leaving, setLeaving] = useState(false);
  const name = ticker.trim().toUpperCase();
  const keyOf = (d: string, s: string) => `${d}|${s}`;

  useEffect(() => {
    const controller = new AbortController();
    replayHome(true, controller.signal).then(found => { setHome(found); setDay(d => d ?? found.days?.[0]?.date ?? null); })
      .catch(e => { if (!controller.signal.aborted) setHomeError(words(e)); });
    return () => controller.abort();
  }, []);

  // The tickers he traded or watches that day; the first becomes the default until he types one.
  useEffect(() => {
    if (!day || view) return;
    const controller = new AbortController();
    replaySymbols(day, controller.signal).then(found => {
      setSuggested(found);
      // Default: a ticker he traded that day, else the desk's selected one, else the first he watches.
      const traded = found.symbols.find(s => s.why === "traded");
      if (!typed && (traded || (!symbol && found.symbols.length))) setTicker((traded ?? found.symbols[0]).symbol);
    }).catch(() => setSuggested({ day, symbols: [] }));
    return () => controller.abort();
  }, [day, view, typed, symbol]);

  // The day's bars for the ticker: ready, or the reason the day is greyed out.
  useEffect(() => {
    if (!day || !/^[A-Z][A-Z0-9.-]{0,9}$/.test(name) || view) return;
    const key = keyOf(day, name);
    if (loaded?.key === key || missing[key]) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true);
      replayBars(day, name, controller.signal)
        .then(found => setLoaded({ key, bars: found.bars, open_at: found.open_at, close_at: found.close_at }))
        .catch(e => { if (!controller.signal.aborted) setMissing(m => ({ ...m, [key]: words(e) })); })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 350);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [day, name, view, loaded?.key, missing]);

  const ready = !!day && loaded?.key === keyOf(day, name);
  const reason = day ? missing[keyOf(day, name)] : undefined;

  const start = async () => {
    if (!day || !ready) return;
    setError(null);
    try {
      const started = await startReplay(day);
      setView(started); setAt(loaded!.open_at); setLog([]); setPlaying(false);
    } catch (e) { setError(words(e)); }
  };

  // The clock: one replayed minute per tick at the chosen speed, stopping at the close.
  const closeAt = loaded?.close_at ?? 0;
  const ended = !!view && at >= closeAt;
  const running = playing && !ended;  // the clock stops itself at the close
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setAt(a => Math.min(a + 60, closeAt)), msPerBar(speed));
    return () => window.clearInterval(timer);
  }, [running, speed, closeAt]);

  // Bring the run to the clock when something works on the bars (an open position or a working order) or at the close;
  // one request at a time, the newest clock next.
  const sending = useRef<number | null>(null);
  const wanted = useRef(0);
  const apply = useCallback((next: ReplayView) => {
    setView(prev => prev && next.run.id === prev.run.id && next.at >= prev.at ? next : prev);  // a late, older answer never rolls it back
    if (next.happened?.length) setLog(l => [...l, ...next.happened!]);
  }, []);
  const sync = useCallback((target: number) => {
    wanted.current = target;
    if (sending.current !== null || !view) return;
    const runId = view.run.id;
    const send = (clock: number) => {
      sending.current = clock;
      stepReplay(runId, clock).then(next => { apply(next); setError(null); })
        // An order recorded at a later clock while this step was out refuses it; the next step catches up.
        .catch(e => { if (!(e instanceof PaperRefused && e.status === 409 && /only goes forward/.test(e.message))) setError(words(e)); })
        .finally(() => {
        sending.current = null;
        if (wanted.current > clock) send(wanted.current);
      });
    };
    send(target);
  }, [view, apply]);
  const busy = !!view && (view.positions.length > 0 || view.orders.length > 0);
  useEffect(() => {
    if (!view || at <= view.at) return;
    if (busy || (at >= closeAt && !view.ended)) sync(at);
  }, [at, view, busy, closeAt, sync]);

  const pause = useCallback(() => setPlaying(false), []);
  const onView = useCallback((next: ReplayView) => apply(next), [apply]);

  const leave = async () => {
    setPlaying(false);
    if (view && busy && !view.ended) {
      setLeaving(true);
      try { apply(await stepReplay(view.run.id, at, true)); } catch { /* the run keeps what is open; the scorecard says so */ }
      setLeaving(false);
    }
    onLeave();
  };
  const another = () => { setView(null); setLog([]); setPlaying(false); };

  const shown = useMemo(() => view && loaded ? shownBars(loaded.bars, at) : [], [loaded, at, view]);
  const last = shown.length ? shown[shown.length - 1] : null;

  return (
    <div data-testid="desk-replay" className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
      {/* The badge: amber, first, on every replay screen, so a replayed price is never taken for live. */}
      <div className="sticky top-0 z-10 -mx-3 -mt-3 flex flex-wrap items-center gap-2 border-b border-amber-400/40 bg-[#1a1408] px-3 py-2">
        <span data-testid="replay-badge" role="status" className="rounded bg-amber-400 px-2 py-0.5 text-xs font-bold tracking-wide text-black tabular-nums">
          {view ? replayBadge(view.run.day, at) : day ? `REPLAY · ${replayDate(day)} · not started` : "REPLAY"}
        </span>
        {view && (
          <div className="flex flex-wrap items-center gap-1">
            <button type="button" data-testid="replay-play" aria-label={running ? "Pause the replay" : "Play the replay"} disabled={ended} onClick={() => setPlaying(!running)}
              className={cn(BUTTON, "min-w-11 border-amber-400/60 text-amber-100")}>{running ? <Pause size={14} aria-hidden /> : <Play size={14} aria-hidden />}</button>
            <button type="button" data-testid="replay-step" aria-label="Step one bar" disabled={ended} onClick={() => { setPlaying(false); setAt(a => Math.min(a + 60, closeAt)); }}
              className={cn(BUTTON, "min-w-11")}><SkipForward size={14} aria-hidden /><span className="max-sm:sr-only">1 bar</span></button>
            <div role="radiogroup" aria-label="Replay speed" className="inline-flex rounded-md border text-xs">
              {SPEEDS.map(s => (
                <button key={s} type="button" role="radio" aria-checked={speed === s} onClick={() => setSpeed(s)}
                  className={cn("min-h-11 min-w-11 px-2 tabular-nums first:rounded-l-md last:rounded-r-md sm:min-h-8 sm:min-w-0", speed === s ? "bg-amber-400/15 text-amber-100" : "text-muted-foreground hover:bg-secondary")}>{s}×</button>
              ))}
            </div>
          </div>
        )}
        <button type="button" data-testid="replay-leave" disabled={leaving} onClick={leave} className={cn(BUTTON, "ml-auto")}>
          {leaving ? "Selling what is open…" : "Back to live"}
        </button>
      </div>

      {homeError && <p role="alert" className="text-xs text-amber-300">Replay is unavailable right now: {homeError}</p>}

      {!view && (
        <section aria-label="Pick a day" data-testid="replay-setup" className="space-y-3">
          <p className="text-sm text-foreground">Practice paper trading on a past day. The chart starts at the open and plays forward; fills are priced from that day&apos;s bars, and these trades are scored apart from live paper and your real trades.</p>
          <div className="space-y-1.5">
            <span className={LABEL}>Day</span>
            <div role="radiogroup" aria-label="Replay day" className="flex flex-wrap gap-1.5">
              {(home?.days ?? []).map(d => {
                const why = missing[keyOf(d.date, name)];
                return (
                  <button key={d.date} type="button" role="radio" aria-checked={day === d.date} data-testid="replay-day" data-missing={why ? "true" : undefined}
                    title={why ?? (d.early_close ? "Early close" : undefined)} onClick={() => setDay(d.date)}
                    className={cn("min-h-11 rounded-md border px-2.5 text-xs sm:min-h-8", day === d.date ? "border-amber-400/70 bg-amber-400/10 text-amber-100" : "text-muted-foreground hover:bg-secondary",
                      why && "line-through opacity-45")}>
                    {replayDate(d.date)}{d.early_close ? " ·½" : ""}
                  </button>
                );
              })}
              {!home && !homeError && <span className="text-xs text-muted-foreground">Reading the market calendar…</span>}
            </div>
          </div>
          <div className="space-y-1.5">
            <span className={LABEL}>Ticker</span>
            <div className="flex flex-wrap items-center gap-1.5">
              <input aria-label="Replay ticker" value={ticker} maxLength={10} onChange={e => { setTyped(true); setTicker(e.target.value.toUpperCase().replace(/[^A-Z0-9.-]/g, "")); }}
                className={cn(INPUT, "w-24 uppercase")} />
              {suggested?.day === day && suggested.symbols.slice(0, 8).map(s => (
                <button key={s.symbol} type="button" onClick={() => { setTyped(true); setTicker(s.symbol); }} title={s.why === "traded" ? "You traded it that day" : "On your watchlist"}
                  className={cn("min-h-11 rounded-md border px-2 text-xs sm:min-h-8", name === s.symbol ? "border-foreground/60 text-foreground" : "text-muted-foreground hover:bg-secondary")}>
                  {s.symbol}{s.why === "traded" && <span className="ml-1 text-amber-200">•</span>}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-muted-foreground">• traded that day. Not-followed tickers are left out.</p>
          </div>
          {reason ? <p role="alert" data-testid="replay-missing" className="text-xs text-amber-300">{day ? replayDate(day) : ""} is greyed out for {name}: {reason}</p>
            : ready ? <p data-testid="replay-ready" className="text-xs text-muted-foreground">{name} on {replayDate(day!)}: {loaded!.bars.filter(b => b.time >= loaded!.open_at && b.time < loaded!.close_at).length} minute bars, from {replayTime(loaded!.open_at)} to {replayTime(loaded!.close_at)} ET.</p>
            : loading ? <p className="text-xs text-muted-foreground">Reading {name}&apos;s minute bars…</p> : null}
          {error && <p role="alert" className="text-xs text-amber-300">{error}</p>}
          <button type="button" data-testid="replay-start" disabled={!ready} onClick={start} className={cn(BUTTON, AMBER)}>Start the replay at {loaded && ready ? replayTime(loaded.open_at) : "9:30 AM"}</button>
          {home && home.runs.length > 0 && (
            <div className="space-y-1 border-t pt-3">
              <span className={LABEL}>Replay practice so far</span>
              <ScoreLine score={home.score} />
              {home.trades.length > 0 && <TradeRows trades={home.trades.slice(0, 10)} />}
            </div>
          )}
        </section>
      )}

      {view && loaded && (
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_380px]">
          <div className="min-w-0 space-y-2">
            <div className="flex flex-wrap items-baseline gap-x-3">
              <span className="text-base font-semibold text-foreground">{name}</span>
              {last ? <span className="text-xs tabular-nums text-muted-foreground">{px(last.close)} at {replayTime(last.time + 60)} ET</span>
                : <span className="text-xs text-muted-foreground">the open: press Play or step one bar</span>}
            </div>
            <ReplayChart symbol={name} bars={shown} positions={view.positions} closed={view.closed} orders={view.orders} />
            <p className="text-[11px] text-muted-foreground">One-minute candles to the replay clock, premarket included; nothing after it is drawn. Pale arrows are your replay fills.</p>
            {ended && (
              <div data-testid="replay-over" className="flex flex-wrap items-center gap-2 rounded-md border border-amber-400/40 p-2 text-xs">
                <span className="text-foreground">The replayed day is over{view.closed.length ? `: ${signed(view.score.pnl)} on ${view.score.trades} trade${view.score.trades === 1 ? "" : "s"}` : ""}.</span>
                <button type="button" onClick={another} className={BUTTON}>Replay another day</button>
              </div>
            )}
          </div>
          <div className="min-w-0 space-y-3">
            {!ended && <Ticket view={view} at={at} symbol={name} options={home?.options ?? ""} onView={onView} pause={pause} />}
            <RunBook view={view} at={at} onView={onView} pause={pause} log={log} />
            {error && <p role="alert" className="text-xs text-amber-300">{error}</p>}
          </div>
        </div>
      )}
    </div>
  );
}

