"use client";

/*
 * The centre's Grid (docs/copilot-lab.md § The desk): 4, 6 or 9 small live charts of the names he cares about, so he can
 * watch several at once. Slots fill with his followed held positions, then his Watching list (``lib/deskGrid.ts``); he
 * can pin a name to a slot. The size, the timeframe and the pins are kept on this device.
 *
 * Each tile: the ticker, its last price and day change (the desk's shared ticker), today's 1-minute or 5-minute candles
 * after the last half hour of the previous session (grey), today's VWAP and his plan and alert levels as thin lines, and
 * the earnings tag when there is one. No studies menu, no zoom: a click opens the name on the full Chart tab in place.
 *
 * One batched bars read for every tile (``GET /copilot/desk/grid``) when the names change, then at most once a minute
 * while the Grid shows, the session is on and the browser tab is visible; between reads the shared ticker moves each
 * tile's last candle (and starts the next one).
 */

import { memo, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Pin, PinOff } from "lucide-react";
import {
  CandlestickSeries, ColorType, CrosshairMode, LineSeries, LineStyle, createChart,
  type AutoscaleInfo, type IChartApi, type IPriceLine, type ISeriesApi, type UTCTimestamp,
} from "lightweight-charts";
import { useKeptState } from "@/components/copilot/DeskMemory";
import { EarningsTag } from "@/components/copilot/EarningsTag";
import { Flash } from "@/components/copilot/Ticks";
import { signedPct, type DeskEvents, type DeskSparks } from "@/lib/desk";
import {
  DEFAULT_LAYOUT, GRID_SIZES, GRID_TIMEFRAMES, getDeskGrid, gridSlots, gridTicker, pinTo, readGridLayout, saveGridLayout,
  type GridBar, type GridLayout, type GridLevel, type GridRead, type GridTile,
} from "@/lib/deskGrid";
import { tickFor, useDeskTicks } from "@/lib/deskTicks";
import { cn } from "@/lib/utils";

const REFRESH_MS = 60_000;
const PENDING_MS = 5_000;
const PENDING_TRIES = 3;
const LEVEL_REACH = 0.04; // a level within 4% of the price stays in the tile's view; a farther one is left off its scale
const UP = "#2bc9a4", DOWN = "#ee617a", PRIOR = "#5b5b63";
const LEVEL_COLOR: Record<GridLevel["role"], string> = { entry: "#7db3f0", invalidation: "#fca5a5", alert: "#f4c66bb0" };
const HEIGHT: Record<GridLayout["size"], string> = { 4: "h-28 sm:h-52", 6: "h-28 sm:h-40", 9: "h-28 sm:h-32" };
const COLUMNS: Record<GridLayout["size"], string> = { 4: "grid-cols-2", 6: "grid-cols-2 sm:grid-cols-3", 9: "grid-cols-2 sm:grid-cols-3" };

const price = (value: number) => value.toFixed(value >= 1 ? 2 : 4);
const tone = (value: number | null | undefined) => value == null || value === 0 ? "text-muted-foreground" : value > 0 ? "text-emerald-300" : "text-rose-300";

type Live = { last: number; at: number; stale: boolean } | null;

/** A newer read's tile, except that a pending or failed one keeps the tile already shown for the same session. */
function merge(prev: GridRead | null, next: GridRead): GridRead {
  if (!prev || prev.timeframe !== next.timeframe || prev.day !== next.day) return next;
  const rows = { ...prev.rows, ...next.rows };
  for (const [symbol, row] of Object.entries(next.rows)) {
    if (row.state !== "ok" && prev.rows[symbol]?.state === "ok") rows[symbol] = prev.rows[symbol];
  }
  return { ...next, rows };
}

export default function DeskGrid({ held, watched, hidden, sparks, earnings, selected, onOpen }: {
  /** Followed held tickers, in the book's order. */
  held: string[];
  /** The Watching list's tickers, in its order (none held). */
  watched: string[];
  /** Tickers set to Not following: never in a slot. */
  hidden: ReadonlySet<string>;
  sparks: DeskSparks | null;
  earnings: DeskEvents | null;
  selected: string | null;
  /** A tile's click: the name on the full Chart tab, in place. */
  onOpen(symbol: string): void;
}) {
  const [layout, setLayout] = useState<GridLayout>(DEFAULT_LAYOUT);
  const [ready, setReady] = useState(false);
  useEffect(() => { setLayout(readGridLayout()); setReady(true); }, []); // eslint-disable-line react-hooks/set-state-in-effect -- the store is read after hydration
  const change = (next: GridLayout) => { setLayout(next); saveGridLayout(next); };

  const slots = useMemo(() => gridSlots(layout, held, watched, hidden), [layout, held, watched, hidden]);
  const symbols = useMemo(() => slots.filter((s): s is string => !!s), [slots]);
  const key = `${symbols.join(",")}|${layout.timeframe}`;

  const [read, setRead] = useKeptState<GridRead | null>("desk.grid", null);
  const shown = useRef(read);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!ready || !symbols.length) return;
    const controller = new AbortController();
    let timer: number | undefined;
    let pendingTries = 0;
    const next = (ms: number) => { timer = window.setTimeout(run, ms); };
    function run() {
      if (document.visibilityState !== "visible") { next(REFRESH_MS); return; } // hidden: no read until it shows
      getDeskGrid(symbols, layout.timeframe, controller.signal).then(found => {
        const merged = merge(shown.current, found);
        shown.current = merged;
        setRead(merged);
        setFailed(false);
        const pending = Object.values(found.rows).some(r => r.state === "pending");
        if (pending && pendingTries++ < PENDING_TRIES) next(PENDING_MS);
        else if (found.live) next(REFRESH_MS);
      }).catch(() => {
        if (controller.signal.aborted) return;
        setFailed(true);
        next(REFRESH_MS);
      });
    }
    run();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [ready, key]); // eslint-disable-line react-hooks/exhaustive-deps -- the key names the symbols and the timeframe

  const ticks = useDeskTicks(symbols);
  const data = read && read.timeframe === layout.timeframe ? read : null;
  const day = earnings?.today ?? data?.day ?? "";
  const [editing, setEditing] = useState<number | null>(null);

  return (
    <div className="space-y-2" data-testid="desk-grid" data-size={layout.size} data-timeframe={layout.timeframe}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <div role="group" aria-label="Charts in the grid" className="flex gap-1">
          {GRID_SIZES.map(size => (
            <button key={size} type="button" aria-pressed={layout.size === size} onClick={() => { change({ ...layout, size }); setEditing(null); }}
              className={cn("min-h-11 min-w-11 rounded border px-2 text-xs tabular-nums sm:min-h-0 sm:min-w-0 sm:py-0.5",
                layout.size === size ? "border-foreground/60 text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
              {size}
            </button>
          ))}
        </div>
        <div role="group" aria-label="Candles" className="flex gap-1">
          {GRID_TIMEFRAMES.map(tf => (
            <button key={tf} type="button" aria-pressed={layout.timeframe === tf} onClick={() => change({ ...layout, timeframe: tf })}
              className={cn("min-h-11 min-w-11 rounded border px-2 text-xs tabular-nums sm:min-h-0 sm:min-w-0 sm:py-0.5",
                layout.timeframe === tf ? "border-foreground/60 text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
              {tf}
            </button>
          ))}
        </div>
        <span className="ml-auto text-xs text-muted-foreground">
          {failed ? "Bars could not be read just now; trying again in a minute." : data && !data.live ? `Last session · ${data.day}` : "Held first, then Watching"}
        </span>
      </div>
      <ul className={cn("grid gap-1.5", COLUMNS[layout.size])} aria-label="Grid">
        {slots.map((symbol, slot) => (
          <li key={slot} data-testid="grid-tile" data-slot={slot} data-symbol={symbol ?? ""} data-pinned={layout.pins[slot] === symbol && !!symbol}
            className={cn("relative min-w-0 rounded-md border bg-background/40", symbol && symbol === selected ? "border-foreground/40" : "border-border",
              !symbol && "border-dashed")}>
            {editing === slot ? (
              <PinForm slot={slot} onPin={name => { change(pinTo(layout, slot, name)); setEditing(null); }} onCancel={() => setEditing(null)} heightClass={HEIGHT[layout.size]} />
            ) : symbol ? (
              <Tile symbol={symbol} tile={data?.rows[symbol]} step={data?.step ?? 60} live={!!data?.live}
                tick={tickFor(ticks, symbol)} spark={sparks?.rows[symbol] ?? null} tag={earnings?.rows[symbol]} day={day}
                pinned={layout.pins[slot] === symbol} heightClass={HEIGHT[layout.size]}
                onOpen={() => onOpen(symbol)} onPin={() => change(pinTo(layout, slot, layout.pins[slot] === symbol ? null : symbol))}
                onReplace={() => setEditing(slot)} />
            ) : (
              <div className={cn("flex flex-col items-center justify-center gap-1 p-2 text-xs text-muted-foreground", HEIGHT[layout.size])}>
                <span>Empty slot</span>
                <button type="button" onClick={() => setEditing(slot)} className="min-h-11 rounded border px-2 hover:text-foreground sm:min-h-0 sm:py-0.5">Pin a ticker</button>
              </div>
            )}
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted-foreground">
        Grey candles: the last half hour of the previous session. Lines: <span style={{ color: "#f5e6a1" }}>VWAP</span>, your
        {" "}<span style={{ color: LEVEL_COLOR.entry }}>entry</span>, <span style={{ color: LEVEL_COLOR.invalidation }}>invalidation</span> and
        {" "}<span style={{ color: LEVEL_COLOR.alert }}>alerts</span>. Click a chart to open it.
      </p>
    </div>
  );
}

function PinForm({ slot, onPin, onCancel, heightClass }: { slot: number; onPin(name: string): void; onCancel(): void; heightClass: string }) {
  const [text, setText] = useState("");
  const [bad, setBad] = useState(false);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const name = gridTicker(text);
    if (!name) { setBad(true); return; }
    onPin(name);
  };
  return (
    <form onSubmit={submit} className={cn("flex flex-col justify-center gap-1.5 p-2", heightClass)}>
      <input autoFocus value={text} onChange={e => { setText(e.target.value); setBad(false); }} aria-label={`Ticker for slot ${slot + 1}`}
        placeholder="Ticker" maxLength={10} className="min-h-11 rounded border bg-background px-2 text-sm uppercase sm:min-h-8" />
      {bad && <span className="text-xs text-rose-300">Not a ticker.</span>}
      <div className="flex gap-1.5">
        <button type="submit" className="min-h-11 rounded border px-2 text-xs text-foreground sm:min-h-0 sm:py-0.5">Pin here</button>
        <button type="button" onClick={onCancel} className="min-h-11 rounded px-2 text-xs text-muted-foreground hover:text-foreground sm:min-h-0 sm:py-0.5">Cancel</button>
      </div>
    </form>
  );
}

const Tile = memo(function Tile({ symbol, tile, step, live, tick, spark, tag, day, pinned, heightClass, onOpen, onPin, onReplace }: {
  symbol: string; tile: GridTile | undefined; step: number; live: boolean; tick: (Live & { change_pct: number | null }) | null;
  spark: DeskSparks["rows"][string] | null; tag: DeskEvents["rows"][string] | undefined; day: string; pinned: boolean; heightClass: string;
  onOpen(): void; onPin(): void; onReplace(): void;
}) {
  const ticked = tick && !tick.stale ? tick : null;
  const last = ticked?.last ?? (tile?.last ?? spark?.last ?? null);
  const change = ticked?.change_pct ?? spark?.change_pct ?? tile?.change_pct ?? null;
  const bars = tile?.state === "ok" ? tile.bars : null;
  return (
    <div className="flex flex-col">
      {/* On a phone the price and change wrap under the ticker and its buttons; one line from sm up. */}
      <div className="flex min-w-0 flex-wrap items-center gap-x-1.5 px-1.5 pt-1 text-xs sm:flex-nowrap">
        <button type="button" onClick={onOpen} className="min-h-11 shrink-0 font-semibold text-foreground hover:underline sm:min-h-0">{symbol}</button>
        <span aria-hidden className="hidden h-0 basis-full max-sm:order-2 max-sm:block" />
        {last != null && <span data-testid="grid-last" className={cn("tabular-nums text-foreground max-sm:order-3", tick?.stale && "opacity-50")}><Flash value={last}>{price(last)}</Flash></span>}
        {change != null && <span data-testid="grid-change" className={cn("tabular-nums max-sm:order-3", tone(change))}>{signedPct(change, 2)}</span>}
        <EarningsTag tag={tag} day={day} className="text-[10px] max-sm:order-3" />
        <span className="ml-auto flex shrink-0 items-center max-sm:order-1">
          <button type="button" aria-pressed={pinned} onClick={onPin} aria-label={pinned ? `Unpin ${symbol} from this slot` : `Pin ${symbol} to this slot`}
            title={pinned ? "Pinned here: click to let the slot fill itself again" : "Keep this name in this slot"}
            className={cn("inline-flex min-h-11 min-w-11 items-center justify-center rounded sm:min-h-6 sm:min-w-6", pinned ? "text-foreground" : "text-muted-foreground/60 hover:text-foreground")}>
            {pinned ? <Pin size={12} aria-hidden /> : <PinOff size={12} aria-hidden />}
          </button>
          <button type="button" onClick={onReplace} aria-label={`Put another ticker in ${symbol}'s slot`} title="Put another ticker here"
            className="inline-flex min-h-11 min-w-11 items-center justify-center rounded text-muted-foreground/60 hover:text-foreground sm:min-h-6 sm:min-w-6">⋯</button>
        </span>
      </div>
      <button type="button" onClick={onOpen} aria-label={`Open ${symbol} on the chart`} className={cn("relative block w-full cursor-pointer", heightClass)}>
        {bars ? <TileChart bars={bars} levels={tile!.levels} step={step} live={live} tick={ticked} />
          : <span className="flex h-full items-center justify-center text-xs text-muted-foreground">
              {tile?.state === "unavailable" ? "No bars for this session" : "Loading bars…"}
            </span>}
      </button>
    </div>
  );
});

type Parts = { chart: IChartApi; candles: ISeriesApi<"Candlestick">; vwap: ISeriesApi<"Line">; lines: IPriceLine[] };

const candle = (b: GridBar) => ({
  time: b.time as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close,
  ...(b.prior ? { color: PRIOR, wickColor: PRIOR } : b.extended ? { color: (b.close >= b.open ? UP : DOWN) + "80", wickColor: (b.close >= b.open ? UP : DOWN) + "80" } : {}),
});

/** One tile's chart: candles, VWAP and the levels, no axis of time, no crosshair, no zoom or pan (a click opens the
 * full chart). The ticker moves the last candle, and starts the next once its time comes. */
function TileChart({ bars, levels, step, live, tick }: { bars: GridBar[]; levels: GridLevel[]; step: number; live: boolean; tick: Live }) {
  const host = useRef<HTMLDivElement>(null);
  const parts = useRef<Parts | null>(null);
  const shownBars = useRef(bars);
  const shownLevels = useRef(levels);
  const forming = useRef<GridBar | null>(null);

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const chart = createChart(element, {
      autoSize: true,
      // The library's logo shows once, on the Chart tab's chart (as Charts shows it on its main pane only).
      layout: { background: { type: ColorType.Solid, color: "#0e0e10" }, textColor: "#8d8d96", fontSize: 9, attributionLogo: false },
      grid: { vertLines: { visible: false }, horzLines: { color: "#18181b" } },
      crosshair: { mode: CrosshairMode.Hidden },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: 0.06 }, entireTextOnly: true },
      timeScale: { visible: false, borderVisible: false, rightOffset: 1, minBarSpacing: 0.1 },
      handleScroll: false, handleScale: false,
    });
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: UP, downColor: DOWN, wickUpColor: UP, wickDownColor: DOWN, borderVisible: false, priceLineVisible: false, lastValueVisible: true,
      autoscaleInfoProvider: (original: () => AutoscaleInfo | null) => {
        const found = original();
        const data = shownBars.current;
        if (!found?.priceRange || !data.length) return found;
        const last = data[data.length - 1].close;
        const near = shownLevels.current.map(l => l.price).filter(p => Math.abs(p - last) / last <= LEVEL_REACH);
        if (!near.length) return found;
        return { ...found, priceRange: { minValue: Math.min(found.priceRange.minValue, ...near), maxValue: Math.max(found.priceRange.maxValue, ...near) } };
      },
    });
    const vwap = chart.addSeries(LineSeries, {
      color: "#f5e6a1aa", lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, autoscaleInfoProvider: () => null,
    });
    parts.current = { chart, candles, vwap, lines: [] };
    const fit = () => chart.timeScale().fitContent();
    chart.timeScale().subscribeSizeChange(fit);
    return () => { chart.timeScale().unsubscribeSizeChange(fit); parts.current = null; chart.remove(); };
  }, []);

  useEffect(() => {
    const current = parts.current;
    if (!current) return;
    shownBars.current = bars;
    shownLevels.current = levels;
    forming.current = null;
    current.candles.setData(bars.map(candle));
    current.vwap.setData(bars.map(b => b.vwap == null ? { time: b.time as UTCTimestamp } : { time: b.time as UTCTimestamp, value: b.vwap }));
    for (const line of current.lines) current.candles.removePriceLine(line);
    const last = bars.length ? bars[bars.length - 1].close : null;
    current.lines = levels.filter(l => last != null && Math.abs(l.price - last) / last <= LEVEL_REACH).map(level => current.candles.createPriceLine({
      price: level.price, color: LEVEL_COLOR[level.role], lineWidth: 1, lineStyle: level.role === "alert" ? LineStyle.Dotted : LineStyle.Dashed,
      axisLabelVisible: false, title: "",
    }));
    current.chart.timeScale().fitContent();
  }, [bars, levels]);

  useEffect(() => {
    const current = parts.current;
    if (!current || !tick || !live || !bars.length) return;
    const lastBar = forming.current ?? bars[bars.length - 1];
    if (lastBar.prior || tick.at < lastBar.time) return;
    const slot = Math.floor(tick.at / step) * step;
    const next: GridBar = slot >= lastBar.time + step
      ? { time: slot, open: lastBar.close, high: Math.max(lastBar.close, tick.last), low: Math.min(lastBar.close, tick.last), close: tick.last, volume: 0, extended: false, vwap: null, prior: false }
      : { ...lastBar, high: Math.max(lastBar.high, tick.last), low: Math.min(lastBar.low, tick.last), close: tick.last };
    forming.current = next;
    current.candles.update(candle(next));
    if (next.time !== lastBar.time) current.chart.timeScale().fitContent();
  }, [tick, live, bars, step]);

  return <div ref={host} aria-hidden className="absolute inset-0" data-testid="grid-chart" data-bars={bars.length} />;
}
