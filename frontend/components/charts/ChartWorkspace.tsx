"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, ChartCandlestick, Check, Columns3, Crosshair, Expand, LayoutGrid, Link2, Loader2, Maximize2, Pause, Play, Plus, RefreshCw, Search, Trash2, X } from "lucide-react";
import LayoutMenu from "./LayoutMenu";
import PriceChart from "./PriceChart";
import SymbolPalette from "./SymbolPalette";
import { activeLayout, applyLayout, arrangementOf, chartStreamUrl, createCrosshairLink, createRangeLink, earlyClose, etTime, fetchChartData, fetchChartHistory, focusPanel, heldSymbols, INTERVALS, intradayInterval, liveTick, MAX_HELD_SYMBOLS, MAX_LAYOUTS, mergeBars, nameTaken, parseChartTick, price, retainHistory, shownPrice, SMALL_HEIGHTS, staleCandles, validSymbol } from "@/lib/charts";
import type { ChartBar, ChartData, ChartPanelData, ChartQuote, ChartSettings, ChartStreamTick, FillMarker, Indicators, Interval, PriceLevel, SmallChartSize, SymbolPanels } from "@/lib/charts";
import { createStreamStore, useClock, useStream } from "@/lib/chartStore";
import { useChartSettings } from "@/lib/chartSync";
import type { LiveFeed } from "@/lib/chartStore";

const INDICATORS: [keyof Indicators, string][] = [["ema9", "EMA 9"], ["ema20", "EMA 20"], ["ema50", "EMA 50"], ["ema200", "EMA 200"], ["vwap", "RTH VWAP"], ["volume", "Volume"], ["rsi", "RSI 14"], ["fills", "My fills"]];
const SYNC_TEXT = { loading: "Loading saved settings", saving: "Saving…", saved: "Saved", offline: "Saved in this browser · server unavailable" };
const button = "inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-slate-700/60 px-2.5 text-xs transition-colors hover:bg-slate-800 disabled:opacity-40";
type OlderPanel = { bars: ChartBar[]; markers: FillMarker[]; exhausted: boolean; warmup: string; issue: string | null; loading: boolean; calendarNote?: string | null };
/** Older history per frame (`symbol|interval`), for one session. */
type OlderState = { key: string; panels: Partial<Record<string, OlderPanel>> };
/** A symbol at an interval: what one panel draws, and the key its history is kept under. */
type Frame = { symbol: string; interval: Interval };
type Slot = Frame & { index: number };
const frameKey = (frame: Frame) => `${frame.symbol}|${frame.interval}`;
const NO_LEVELS: PriceLevel[] = [];

// The pieces of the toolbar and footer that move with every trade or second
// subscribe themselves, so the workspace above them does not re-render.
// The stream also carries symbols that panels hold: the headline reads only the
// main symbol's trades, so a SPY trade never hides the newest MRVL one.
const latestTrade = (ticks: ChartStreamTick[], symbol: string) => ticks.findLast((tick) => tick.symbol === symbol);
function LiveQuote({ live, quote, candle }: { live: LiveFeed; quote?: ChartQuote; candle?: ChartBar }) {
  const tick = useStream(live, (ticks) => latestTrade(ticks, live.symbol));
  const shown = shownPrice({ tick, quote, candle, scope: live });
  const change = shown.price != null && quote?.previous_close && quote.previous_close > 0
    ? (shown.price / quote.previous_close - 1) * 100 : quote?.change_percentage;
  return <div className="flex min-w-0 items-baseline gap-3" aria-label="Selected symbol quote"><span className="text-sm font-medium text-slate-200">{live.symbol}</span><span className="font-mono text-2xl font-medium tracking-tight text-white">{price(shown.price)}</span>
    <span className={`font-mono text-xs ${change != null && change < 0 ? "text-rose-400" : "text-emerald-400"}`}>{change == null ? "—" : `${change >= 0 ? "+" : ""}${change.toFixed(2)}%`}</span><span className="text-[10px] text-slate-500">{shown.source}</span></div>;
}

function FeedStatus({ live, paused, delayed, hasData, failed, loading }: { live: LiveFeed; paused: boolean; delayed: boolean; hasData: boolean; failed: boolean; loading: boolean }) {
  const stale = useClock((now) => staleCandles(now, live.fetched));
  const streaming = useStream(live, (_, state) => state.key === live.key && state.status === "connected");
  return <div className="ml-auto flex items-center gap-2 text-[11px] text-slate-400" role="status">
    <span className={`h-1.5 w-1.5 rounded-full ${paused || failed || stale || delayed ? "bg-amber-400" : hasData ? "bg-sky-400" : "bg-slate-600"}`} />
    {paused ? "Updates paused" : delayed ? "Tradier sandbox · delayed" : streaming ? "Tradier stream · studies refresh 15s" : "Tradier · 15s refresh"}
    {loading && <Loader2 size={12} className="animate-spin" />}
  </div>;
}

function LiveFooter({ live, quote, candle, asOf }: { live: LiveFeed; quote?: ChartQuote; candle?: ChartBar; asOf?: number | null }) {
  const minute = useStream(live, (ticks) => asOf === undefined ? 0
    : ticks.reduce((latest, tick) => liveTick(tick, live) ? Math.max(latest, tick.minute) : latest, asOf ?? 0));
  const tick = useStream(live, (ticks) => latestTrade(ticks, live.symbol));
  const shown = shownPrice({ tick, quote, candle, scope: live });
  const age = useClock((now) => shown.at ? Math.max(0, Math.floor(now - shown.at)) : null);
  return <div className="flex flex-wrap items-center justify-between gap-2 px-1 text-[10px] text-slate-500">
    <span>{minute ? `Last minute candle ${etTime(minute, true)} ${etTime(minute)} ET · latest candle may be forming` : "New York time"}</span>
    <span>{age !== null ? `${shown.source} ${age < 60 ? `${age}s` : `${Math.floor(age / 60)}m`} ago` : "No price timestamp"}</span>
  </div>;
}

export default function ChartWorkspace() {
  // Loaded from and saved to the server (lib/chartSync.ts); browser storage is the offline copy.
  const { settings, setSettings, ready, sync, merged, stored } = useChartSettings();
  const [response, setResponse] = useState<{ key: string; session: ChartSettings["session"]; data: ChartData } | null>(null);
  const [older, setOlder] = useState<OlderState>({ key: "", panels: {} });
  const [rollover, setRollover] = useState<{ key: string; before: number; pending: string[] } | null>(null);
  const [error, setError] = useState<{ key: string; message: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [paused, setPaused] = useState(false);
  const [symbolInput, setSymbolInput] = useState("");
  const [symbolError, setSymbolError] = useState("");
  const [drawing, setDrawing] = useState(false);
  const [levelPrice, setLevelPrice] = useState("");
  const [levelLabel, setLevelLabel] = useState("");
  const [levelError, setLevelError] = useState("");
  const [immersive, setImmersive] = useState(false);
  // The panel the symbol search chooses for: 0 is the main symbol.
  const [palette, setPalette] = useState<number | null>(null);
  const [layoutMenu, setLayoutMenu] = useState(false);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [viewport, setViewport] = useState({ width: 1280, height: 900 });
  const link = useMemo(() => createCrosshairLink(), []);
  const rangeLink = useMemo(() => createRangeLink(), []);
  const stream = useMemo(() => createStreamStore(), []);
  const inFlight = useRef(false);
  const refreshNow = useRef<() => void>(() => {});
  const lastRequest = useRef("");
  // History, its requests and visible ranges belong to a frame: a symbol at an interval.
  const historyFlights = useRef(new Map<string, AbortController>());
  const visibleTimes = useRef(new Map<string, { from: number; to: number }>());
  const lastWorkspaceDay = useRef<{ key: string; day: string } | null>(null);
  const { symbol, session } = settings;
  // Each visible panel's interval and symbol: its own, or the main one it follows.
  const slots = useMemo<Slot[]>(() => (settings.layout === "single" ? [0] : [0, 1, 2, 3, 4]).map((index) => ({
    index, interval: settings.intervals[index], symbol: (index && settings.panelSymbols[index]) || settings.symbol,
  })), [settings.layout, settings.intervals, settings.panelSymbols, settings.symbol]);
  // The intervals each symbol needs, main symbol first; three symbols at most.
  const wanted = useMemo(() => {
    const map = new Map<string, Interval[]>([[symbol, []]]);
    for (const slot of slots) {
      const frames = map.get(slot.symbol) ?? [];
      if (!frames.includes(slot.interval)) frames.push(slot.interval);
      map.set(slot.symbol, frames);
    }
    return map;
  }, [slots, symbol]);
  const intervalKey = (wanted.get(symbol) ?? []).join(",");
  const extrasKey = [...wanted].filter(([name]) => name !== symbol).sort(([a], [b]) => a.localeCompare(b))
    .map(([name, frames]) => `${name}:${frames.join(".")}`).join(",");
  const symbolsKey = [...wanted.keys()].sort().join(",");
  const framesKey = [...new Set(slots.map(frameKey))].sort().join(",");
  const watchlistKey = settings.watchlist.join(",");
  const requestKey = `${symbol}|${session}|${intervalKey}|${extrasKey}|${watchlistKey}`;
  const streamKey = `${symbolsKey}|${session}`;
  const data = response?.key === requestKey ? response.data : null;
  // Candles depend only on the symbol and session. While a request for a new
  // symbol, layout or watchlist loads, a panel keeps the newest response that
  // has its symbol, so reordered intervals and held symbols keep their candles.
  const feedFor = useCallback((name: string): SymbolPanels | undefined => {
    if (!response || response.session !== session) return undefined;
    return response.data.symbol === name ? response.data : response.data.extras?.[name];
  }, [response, session]);
  const current = response && response.session === session && response.data.symbol === symbol ? response.data : null;
  // The newest response of any request, for what is not about one symbol
  // (watchlist quotes, market hours, notes).
  const latest = response?.data;
  const requestFailed = error?.key === requestKey;
  const currentOlder = useMemo(() => older.key === session ? older.panels : {}, [older, session]);
  const hasData = !!current;
  const lives = useMemo(() => new Map([...wanted.keys()].map((name) => [name, {
    store: stream, key: streamKey, symbol: name, session, fetched: feedFor(name)?.fetched_at.intraday ?? 0,
  } satisfies LiveFeed])), [wanted, stream, streamKey, session, feedFor]);
  const live = lives.get(symbol)!;
  // Today's REST candles joined to older history, per frame. Streamed trades are
  // not in here: each chart applies them to its own panel (lib/chartStore.ts).
  const panels = useMemo(() => {
    const merged = new Map<string, ChartPanelData>();
    for (const slot of slots) {
      const key = frameKey(slot);
      const tail = feedFor(slot.symbol)?.panels[slot.interval];
      const past = currentOlder[key];
      if (!tail || merged.has(key)) continue;
      if (!past?.bars.length) { merged.set(key, tail); continue; }
      const bars = mergeBars(retainHistory(past.bars, tail.bars, visibleTimes.current.get(key) ?? null), tail.bars);
      const times = new Set(bars.map((bar) => bar.time));
      merged.set(key, { bars, markers: [...new Map([...past.markers, ...tail.markers].filter((m) => times.has(m.time)).map((m) => [`${m.id}:${m.time}`, m])).values()] });
    }
    return merged;
  }, [slots, feedFor, currentOlder]);
  const selected = latest?.quotes.find((q) => q.symbol === symbol);
  const levels = settings.levels[symbol] ?? NO_LEVELS;

  useEffect(() => {
    historyFlights.current.forEach((controller) => controller.abort());
    historyFlights.current.clear();
    visibleTimes.current.clear();
    setOlder({ key: session, panels: {} });
    setRollover(null);
  }, [session]);
  // History survives a frame moving between panels; a frame no longer shown lets its history go.
  useEffect(() => {
    const shown = new Set<string>(framesKey.split(","));
    historyFlights.current.forEach((controller, key) => { if (!shown.has(key)) { controller.abort(); historyFlights.current.delete(key); } });
    visibleTimes.current.forEach((_, key) => { if (!shown.has(key)) visibleTimes.current.delete(key); });
    setOlder((state) => Object.keys(state.panels).every((key) => shown.has(key)) ? state
      : { ...state, panels: Object.fromEntries(Object.entries(state.panels).filter(([key]) => shown.has(key))) });
  }, [framesKey]);

  const loadOlder = useCallback(async (frame: Frame, beforeOverride?: number, retry = false) => {
    const key = frameKey(frame);
    const feed = feedFor(frame.symbol);
    if (!intradayInterval(frame.interval) || historyFlights.current.has(key) || !feed) return;
    const past = currentOlder[key];
    if (((past?.exhausted || past?.issue) && !retry) && beforeOverride === undefined) return;
    const before = beforeOverride ?? past?.bars[0]?.time ?? feed.panels[frame.interval]?.bars[0]?.time ?? Math.floor(Date.now() / 1000);
    const controller = new AbortController();
    historyFlights.current.set(key, controller);
    setOlder((state) => state.key !== session ? state : ({ ...state, panels: { ...state.panels,
      [key]: { bars: past?.bars ?? [], markers: past?.markers ?? [], exhausted: past?.exhausted ?? false,
        warmup: past?.warmup ?? "pending", issue: null, loading: true } } }));
    let continuation: string | null = null;
    try {
      while (!controller.signal.aborted) {
        const page = await fetchChartHistory({ symbol: frame.symbol, interval: frame.interval, session, before, continuation, signal: controller.signal });
        if (controller.signal.aborted) return;
        setOlder((state) => {
          if (state.key !== session) return state;
          const prior = state.panels[key];
          const live = feed.panels[frame.interval]?.bars ?? [];
          const combined = mergeBars(prior?.bars ?? [], page.bars);
          const retained = retainHistory(combined, live, visibleTimes.current.get(key) ?? null);
          if (retained.length + live.length > 12000) return { ...state, panels: { ...state.panels, [key]: {
            ...(prior ?? { bars: [], markers: [], exhausted: false, warmup: "pending", loading: false }),
            issue: "Visible candles fill the 12,000-candle limit. Zoom in before loading more.", loading: false } } };
          const times = new Set(retained.map((bar) => bar.time));
          const markers = [...new Map([...(prior?.markers ?? []), ...page.markers].filter((m) => times.has(m.time)).map((m) => [`${m.id}:${m.time}`, m])).values()];
          return { ...state, panels: { ...state.panels, [key]: { bars: retained, markers,
            calendarNote: page.calendar_note ?? prior?.calendarNote ?? null,
            exhausted: page.exhausted, warmup: page.warmup, issue: page.issue?.code === "pending" ? null : page.issue?.message ?? null,
            loading: !!page.continuation && (!page.issue || page.issue.code === "pending" || page.issue.code === "rate_limited") } } };
        });
        if (!page.continuation || (page.issue && !["pending", "rate_limited"].includes(page.issue.code))) break;
        continuation = page.continuation;
        const delay = Math.max(250, Math.min(60_000, ((page.issue?.retry_at ?? Math.floor(Date.now() / 1000) + 1) * 1000) - Date.now()));
        await new Promise<void>((resolve) => {
          const timer = window.setTimeout(resolve, delay);
          controller.signal.addEventListener("abort", () => { window.clearTimeout(timer); resolve(); }, { once: true });
        });
      }
    } catch (err) {
      if (!controller.signal.aborted) setOlder((state) => state.key !== session ? state : ({ ...state, panels: { ...state.panels,
        [key]: { bars: state.panels[key]?.bars ?? [], markers: state.panels[key]?.markers ?? [],
          exhausted: false, warmup: state.panels[key]?.warmup ?? "pending",
          issue: err instanceof Error ? err.message : "Older candles could not load.", loading: false } } }));
    } finally {
      if (historyFlights.current.get(key) === controller) historyFlights.current.delete(key);
      setOlder((state) => state.key !== session || !state.panels[key] ? state : ({ ...state,
        panels: { ...state.panels, [key]: { ...state.panels[key], loading: false } } }));
    }
  }, [feedFor, currentOlder, session]);
  // Before 04:00, on weekends and on holidays today has no intraday bars yet:
  // open on the latest completed sessions instead of an empty chart.
  useEffect(() => {
    if (!data) return;
    for (const slot of slots) {
      const tail = (slot.symbol === data.symbol ? data : data.extras?.[slot.symbol])?.panels[slot.interval];
      if (!intradayInterval(slot.interval) || !tail || tail.bars.length || currentOlder[frameKey(slot)]) continue;
      void loadOlder(slot, data.checked_at);
    }
  }, [data, slots, currentOlder, loadOlder]);
  useEffect(() => {
    if (!rollover || rollover.key !== session || !data) return;
    const available = rollover.pending.filter((key) => !historyFlights.current.has(key));
    if (!available.length) return;
    available.forEach((key) => { const slot = slots.find((s) => frameKey(s) === key); if (slot) void loadOlder(slot, rollover.before); });
    setRollover((current) => current === rollover ? { ...current, pending: current.pending.filter((key) => !available.includes(key)) } : current);
  }, [rollover, session, data, older, slots, loadOlder]);
  useEffect(() => {
    const measure = () => setViewport({ width: window.innerWidth, height: window.innerHeight });
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);
  useEffect(() => {
    if (!immersive) return;
    const prior = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prior; };
  }, [immersive]);

  useEffect(() => {
    if (!ready) return;
    let alive = true;
    let busy = false;
    let controller: AbortController | null = null;
    const extras = Object.fromEntries(extrasKey.split(",").filter(Boolean).map((part) => {
      const [name, frames] = part.split(":");
      return [name, frames.split(".") as Interval[]];
    }));
    const load = async () => {
      if (!alive || busy || document.hidden) return;
      busy = true;
      inFlight.current = true;
      controller = new AbortController();
      setLoading(true);
      try {
        const result = await fetchChartData({ symbol, session, intervals: intervalKey.split(",") as Interval[],
          watchlist: watchlistKey ? watchlistKey.split(",") : [], extras }, controller.signal);
        if (alive) {
          const day = new Date(result.checked_at * 1000).toLocaleDateString("en-CA", { timeZone: "America/New_York" });
          if (lastWorkspaceDay.current?.key === session && lastWorkspaceDay.current.day !== day) {
            setRollover({ key: session, before: result.checked_at,
              pending: framesKey.split(",").filter((key) => intradayInterval(key.split("|")[1] as Interval)) });
          }
          lastWorkspaceDay.current = { key: session, day };
          setResponse({ key: requestKey, session, data: result }); setError(null);
        }
      } catch (err) {
        if (alive && !controller.signal.aborted) setError({ key: requestKey, message: err instanceof Error ? err.message : "Unable to refresh charts." });
      } finally {
        busy = false;
        if (alive) { inFlight.current = false; setLoading(false); }
      }
    };
    refreshNow.current = () => { void load(); };
    if (!paused || lastRequest.current !== requestKey) void load();
    else setLoading(false);
    lastRequest.current = requestKey;
    const onVisible = () => { if (!paused && !document.hidden) void load(); };
    const timer = paused ? undefined : window.setInterval(load, 15_000);
    document.addEventListener("visibilitychange", onVisible);
    return () => { alive = false; controller?.abort(); inFlight.current = false; if (timer) window.clearInterval(timer); document.removeEventListener("visibilitychange", onVisible); };
  }, [ready, symbol, session, intervalKey, extrasKey, watchlistKey, framesKey, requestKey, paused]);

  // One stream for every symbol on screen; each chart applies only its own symbol's trades.
  useEffect(() => {
    if (!ready || !hasData || paused) return;
    let alive = true;
    let source: EventSource | null = null;
    const symbols = symbolsKey.split(",");
    const status = (value: "connecting" | "connected" | "fallback") => { if (alive) stream.status(streamKey, value); };
    const connect = () => {
      if (document.hidden || source) return;
      status("connecting");
      source = new EventSource(chartStreamUrl(symbols));
      source.addEventListener("status", (event) => {
        try { status(JSON.parse((event as MessageEvent).data).state === "connected" ? "connected" : "fallback"); }
        catch { status("fallback"); }
      });
      source.addEventListener("tick", (event) => {
        try {
          const tick = parseChartTick(JSON.parse((event as MessageEvent).data));
          if (!alive || !tick || !symbols.includes(tick.symbol)) return;
          stream.tick(streamKey, tick);
        } catch { /* A malformed event cannot replace the last good REST snapshot. */ }
      });
      source.onerror = () => status("fallback");
    };
    const visibility = () => {
      if (document.hidden) { source?.close(); source = null; status("fallback"); }
      else connect();
    };
    connect();
    document.addEventListener("visibilitychange", visibility);
    return () => { alive = false; source?.close(); document.removeEventListener("visibilitychange", visibility); };
  }, [ready, hasData, paused, symbolsKey, streamKey, stream]);

  // Intervals are workspace settings, not per-symbol, so they carry over.
  const chooseSymbol = (symbol: string) => {
    setSettings((s) => s.symbol === symbol ? s : ({ ...s, symbol, recent: [s.symbol, ...s.recent.filter((r) => r !== s.symbol && r !== symbol)].slice(0, 8) }));
    setDrawing(false); setSymbolInput(""); setSymbolError(""); setLevelPrice(""); setPalette(null);
  };
  // A panel holds its own symbol (null: follow the main one). Two held symbols at most.
  const choosePanelSymbol = (index: number, held: string | null) => {
    const next = settings.panelSymbols.map((other, i) => i === index ? held : other);
    if (heldSymbols(next).length > MAX_HELD_SYMBOLS) {
      setSymbolError(`Charts show up to three symbols. Set another panel to follow ${settings.symbol} before adding ${held}.`);
      setPalette(null);
      return;
    }
    setSettings((s) => ({ ...s, panelSymbols: s.panelSymbols.map((other, i) => i === index ? held : other) }));
    setSymbolError(""); setPalette(null);
  };
  // Named layouts (C7.2) are arrangements saved in the shared settings: they
  // move intervals, held symbols, chart height and linked ranges, never the
  // main symbol, levels or watchlist.
  const inUse = activeLayout(settings);
  const chooseLayout = (id: string) => {
    setSettings((s) => { const layout = s.layouts.find((other) => other.id === id); return layout ? applyLayout(s, layout) : s; });
    setExpanded(null); setSymbolError(""); setLayoutMenu(false);
  };
  const saveLayout = (name: string) => setSettings((s) => s.layouts.length >= MAX_LAYOUTS || nameTaken(s.layouts, name) ? s
    : { ...s, layouts: [...s.layouts, { id: crypto.randomUUID(), name, ...arrangementOf(s) }] });
  const renameLayout = (id: string, name: string) => setSettings((s) => ({ ...s, layouts: s.layouts.map((layout) => layout.id === id ? { ...layout, name } : layout) }));
  const updateLayout = (id: string) => setSettings((s) => ({ ...s, layouts: s.layouts.map((layout) => layout.id === id ? { ...layout, ...arrangementOf(s) } : layout) }));
  const deleteLayout = (id: string) => setSettings((s) => ({ ...s, layouts: s.layouts.filter((layout) => layout.id !== id) }));
  const choose = useRef(chooseSymbol);
  const keys = useRef({ palette: palette !== null, layoutMenu, immersive, watchlist: settings.watchlist, symbol: settings.symbol });
  useEffect(() => {
    choose.current = chooseSymbol;
    keys.current = { palette: palette !== null, layoutMenu, immersive, watchlist: settings.watchlist, symbol: settings.symbol };
  });
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const state = keys.current;
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); setPalette((v) => v === null ? 0 : null); return; }
      if (state.palette || state.layoutMenu) return;
      if (event.key === "Escape" && state.immersive) { setImmersive(false); return; }
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable=true]")) return;
      if (event.altKey && (event.key === "ArrowDown" || event.key === "ArrowUp") && state.watchlist.length) {
        event.preventDefault();
        const index = state.watchlist.indexOf(state.symbol);
        const next = index < 0 ? 0 : (index + (event.key === "ArrowDown" ? 1 : -1) + state.watchlist.length) % state.watchlist.length;
        choose.current(state.watchlist[next]);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const watchKey = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    const rows = [...(event.currentTarget.closest("section")?.querySelectorAll<HTMLButtonElement>("[data-watch-row]") ?? [])];
    const index = rows.indexOf(event.currentTarget);
    const to = event.key === "ArrowDown" ? index + 1 : event.key === "ArrowUp" ? index - 1 : event.key === "Home" ? 0 : event.key === "End" ? rows.length - 1 : null;
    if (to === null || !rows.length) return;
    event.preventDefault();
    rows[Math.max(0, Math.min(rows.length - 1, to))].focus();
  };
  const submitSymbol = (event: React.FormEvent) => {
    event.preventDefault();
    const symbol = symbolInput.trim().toUpperCase();
    if (!validSymbol(symbol)) { setSymbolError("Enter a US stock or ETF ticker, such as MRVL."); return; }
    chooseSymbol(symbol);
  };
  const setIntervalAt = (index: number, value: Interval) => setSettings((s) => ({ ...s, intervals: s.intervals.map((v, i) => i === index ? value : v) }));
  // Levels belong to a symbol: one drawn on a panel holding SPY is an SPY level.
  const addLevel = (value: number, target = symbol) => {
    const existing = settings.levels[target] ?? NO_LEVELS;
    if (!Number.isFinite(value) || value <= 0) { setLevelError("Enter a positive price."); return; }
    if (existing.length >= 30) { setLevelError(`Remove a ${target} level before adding another (30 per symbol).`); return; }
    const level = { id: crypto.randomUUID(), price: value, label: levelLabel.trim().slice(0, 30) || `Level ${existing.length + 1}` };
    setSettings((s) => ({ ...s, levels: { ...s.levels, [target]: [...(s.levels[target] ?? []), level] } }));
    setDrawing(false); setLevelPrice(""); setLevelLabel(""); setLevelError("");
  };
  const failed = requestFailed || !!current?.issues.length;
  // A newer extended-hours candle can outrank the quote. Streamed trades outrank
  // both, so the REST candle (without them) is the one that matters here.
  const quoteSlot = slots.find((slot) => slot.symbol === symbol && intradayInterval(slot.interval));
  const latestCandle = quoteSlot ? panels.get(frameKey(quoteSlot))?.bars.at(-1) : undefined;
  const clockFor = (name: string) => ({ session, market: latest?.market, paused, delayed: !!latest?.delayed,
    failed: requestFailed || !!feedFor(name)?.issues.length, fetched: feedFor(name)?.fetched_at.intraday });
  // Until this request's candles arrive, each chart keeps its last frame under
  // a label naming what is loading. A failed request clears it instead.
  const pendingFor = (frame: Frame) => {
    if (!response || data || requestFailed || panels.has(frameKey(frame))) return null;
    if (response.session !== session) return `Loading ${session === "extended" ? "extended hours" : "regular hours"}…`;
    return `Loading ${feedFor(frame.symbol) ? frame.interval : frame.symbol}…`;
  };
  const heldIssues = [...wanted.keys()].filter((name) => name !== symbol).flatMap((name) => (feedFor(name)?.issues ?? []).map((issue) => `${name}: ${issue}`));
  const issues = [...(current?.issues ?? []), ...heldIssues];
  // Only unusual days get a label: early closes, weekday closures and a missing calendar.
  const market = latest?.market;
  const holiday = market?.status === "closed" && ![0, 6].includes(new Date(`${market.date}T12:00:00Z`).getUTCDay());
  const marketLabel = market?.note ?? earlyClose(market) ?? (holiday ? market?.description || "Market closed today" : null);
  const smallHeight = SMALL_HEIGHTS[settings.smallSize];
  const multi = settings.layout === "multi";
  // Immersive: the main chart fills the screen below the toolbar. On a tall,
  // wide screen the row of smaller charts also fits without scrolling.
  const fillHeight = viewport.height - 260;
  const withRow = multi && viewport.width >= 1280 && fillHeight - smallHeight - 70 >= 520;
  const mainHeight = immersive ? Math.max(420, withRow ? fillHeight - smallHeight - 70 : fillHeight) : 410;
  const showAside = !immersive || settings.immersiveWatchlist;

  return (
    <div data-testid="chart-workspace" data-immersive={immersive || undefined} className={immersive
      ? "fixed inset-0 z-[70] space-y-2 overflow-y-auto overscroll-contain bg-[#0b1017] px-2 pb-[calc(0.5rem+env(safe-area-inset-bottom))] pl-[max(0.5rem,env(safe-area-inset-left))] pr-[max(0.5rem,env(safe-area-inset-right))] text-slate-300 sm:px-3"
      : "space-y-4 text-slate-300"}>
      <header className={`flex flex-wrap items-center justify-between gap-3 ${immersive ? "sticky top-0 z-20 -mx-2 bg-[#0b1017]/95 px-2 pb-2 pt-[max(0.5rem,env(safe-area-inset-top))] backdrop-blur sm:-mx-3 sm:px-3" : ""}`}>
        <div>{!immersive && <div className="mb-1 flex items-center gap-2 text-[10px] font-medium uppercase tracking-[0.18em] text-slate-500"><span className="h-1.5 w-1.5 rounded-full bg-sky-400" />Trade Journal / Markets</div>}
          <h1 className={`${immersive ? "text-base" : "text-2xl"} font-semibold tracking-tight text-slate-100`}>Charts</h1></div>
        <div className="flex flex-wrap items-center justify-end gap-2 text-xs">
          <span role="status" aria-label="Chart settings" className={`mr-1 hidden items-center gap-1.5 text-[11px] lg:flex ${sync === "offline" || merged ? "text-amber-300" : "text-slate-500"}`}>{sync === "saving" || sync === "loading" ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}{sync !== "offline" && merged ? "Merged with changes from another device" : SYNC_TEXT[sync]}{sync === "offline" && !stored ? " · browser storage unavailable" : ""}</span>
          <button className={`${button} hidden sm:inline-flex`} onClick={() => setPalette(0)} aria-label="Search symbols (Ctrl or Cmd+K)" title="Search symbols (⌘K / Ctrl+K)"><Search size={13} /><kbd className="text-[10px] text-slate-500">⌘K</kbd></button>
          {immersive && <button className={button} aria-pressed={settings.immersiveWatchlist} onClick={() => setSettings((s) => ({ ...s, immersiveWatchlist: !s.immersiveWatchlist }))}>{settings.immersiveWatchlist ? "Hide watchlist" : "Watchlist"}</button>}
          <button className={button} onClick={() => setLayoutMenu(true)} aria-haspopup="dialog" aria-expanded={layoutMenu} title="Saved layouts"><LayoutGrid size={13} />Layouts{inUse && <span className="max-w-24 truncate text-sky-300">{inUse.name}</span>}</button>
          <button className={button} onClick={() => setSettings((s) => ({ ...s, layout: s.layout === "multi" ? "single" : "multi" }))} aria-label={settings.layout === "multi" ? "Show single chart" : "Show five charts"}>
            {settings.layout === "multi" ? <Maximize2 size={13} /> : <Columns3 size={13} />}{settings.layout === "multi" ? "Focus" : "Five charts"}</button>
          <button className={button} onClick={() => setPaused((v) => !v)} aria-label={paused ? "Resume chart updates" : "Pause chart updates"}>{paused ? <Play size={13} /> : <Pause size={13} />}{paused ? "Resume" : "Pause"}</button>
          <button className={button} disabled={loading} aria-label="Refresh charts" onClick={() => { if (!inFlight.current) refreshNow.current(); }}><RefreshCw size={13} className={loading ? "animate-spin" : ""} /></button>
          {immersive
            ? <button className={`${button} border-sky-500/60 bg-sky-500/15 text-sky-200 hover:bg-sky-500/25`} onClick={() => setImmersive(false)} aria-label="Exit full-screen charts"><X size={14} />Exit</button>
            : <button className={button} onClick={() => setImmersive(true)} aria-label="Enter full-screen charts" title="Full-screen charts"><Expand size={13} /><span className="hidden sm:inline">Full screen</span></button>}
        </div>
      </header>

      <div className="rounded-xl border border-slate-700/50 bg-[#141b25]">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-3 border-b border-slate-700/40 p-3">
          <form onSubmit={submitSymbol} className="relative flex h-9 items-center rounded-md border border-slate-700 bg-[#10151e]">
            <button type="button" aria-label="Open symbol search" onClick={() => setPalette(0)} className="ml-2 rounded p-1 text-slate-500 hover:text-slate-200"><Search size={14} /></button><input aria-label="Chart symbol" value={symbolInput} placeholder={settings.symbol} onChange={(e) => setSymbolInput(e.target.value.toUpperCase())} maxLength={15} className="w-28 bg-transparent px-2 text-sm font-semibold uppercase text-slate-100 outline-none placeholder:text-slate-300" />
            <button type="submit" aria-label="Load symbol" className="mr-1 rounded p-1.5 hover:bg-slate-800"><ArrowUpRight size={14} /></button>
          </form>
          <LiveQuote live={live} quote={selected} candle={latestCandle} />
          {marketLabel && <span aria-label="Market hours" title={market?.description ?? undefined} className={`rounded px-2 py-1 text-[11px] ${market?.note ? "bg-amber-400/10 text-amber-300" : "bg-slate-800 text-slate-300"}`}>{marketLabel}</span>}
          <FeedStatus live={live} paused={paused} delayed={!!latest?.delayed} hasData={hasData} failed={failed} loading={loading} />
        </div>
        <div className="flex flex-wrap items-center gap-1.5 px-3 py-2">
          {INTERVALS.map((interval) => <button key={interval} onClick={() => setIntervalAt(0, interval)} aria-pressed={settings.intervals[0] === interval} className={`rounded px-2 py-1.5 text-[11px] ${settings.intervals[0] === interval ? "bg-sky-400/15 text-sky-300" : "text-slate-400 hover:bg-slate-800"}`}>{interval}</button>)}
          <span className="mx-1 h-4 border-l border-slate-700" />
          <button className="rounded px-2 py-1.5 text-[11px] text-slate-400 hover:bg-slate-800" aria-pressed={settings.session === "extended"} onClick={() => setSettings((s) => ({ ...s, session: s.session === "extended" ? "regular" : "extended" }))}>{settings.session === "extended" ? "Extended hours on" : "Regular hours only"}</button>
          <button className={`ml-auto inline-flex items-center gap-1.5 rounded px-2 py-1.5 text-[11px] ${drawing ? "bg-blue-400/15 text-blue-300" : "text-slate-400 hover:bg-slate-800"}`} aria-pressed={drawing} onClick={() => setDrawing((v) => !v)}><Crosshair size={13} />{drawing ? "Cancel drawing" : "Draw price level"}</button>
        </div>
      </div>
      {symbolError && <p className="text-xs text-amber-300" role="alert">{symbolError}</p>}

      <div className="flex flex-wrap items-center gap-2" aria-label="Chart indicators">
        {INDICATORS.map(([key, label]) => <button key={key} aria-pressed={settings.indicators[key]} onClick={() => setSettings((s) => ({ ...s, indicators: { ...s.indicators, [key]: !s.indicators[key] } }))} className={`rounded-full border px-2.5 py-1 text-[10px] ${settings.indicators[key] ? "border-slate-600 bg-slate-800/60 text-slate-200" : "border-slate-800 text-slate-600"}`}>{label}</button>)}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button aria-pressed={settings.linkRange} onClick={() => setSettings((s) => ({ ...s, linkRange: !s.linkRange }))} title="Scroll and zoom every chart to the same time window"
            className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[10px] ${settings.linkRange ? "border-sky-500/50 bg-sky-400/10 text-sky-200" : "border-slate-800 text-slate-500"}`}><Link2 size={11} />Link time ranges</button>
          {multi && <div role="group" aria-label="Small chart height" className="flex overflow-hidden rounded-full border border-slate-800 text-[10px]">
            {(["compact", "normal", "tall"] as SmallChartSize[]).map((size) => <button key={size} aria-pressed={settings.smallSize === size} aria-label={`${size} small charts`} onClick={() => setSettings((s) => ({ ...s, smallSize: size }))}
              className={`px-2 py-1 ${settings.smallSize === size ? "bg-slate-800 text-slate-200" : "text-slate-500"}`}>{size === "compact" ? "S" : size === "normal" ? "M" : "L"}</button>)}
          </div>}
        </div>
      </div>

      {requestFailed && <div role="alert" aria-label="Chart data error" className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-sm text-amber-200">{error.message}{current && <span className="ml-1">Showing the last successful data.</span>}</div>}
      {!!issues.length && <div role="alert" aria-label="Chart data warning" className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-xs text-amber-200">Refresh incomplete. {issues.join(" ")} Check timestamps before using these charts.</div>}

      <div className={`grid min-w-0 gap-3 ${showAside ? "lg:grid-cols-[minmax(0,1fr)_230px]" : ""}`}>
        <div className="min-w-0 space-y-3">
          {response ? <>
            {slots.slice(0, 1).map((slot) => <PriceChart key={slot.index} id="main" main symbol={slot.symbol} interval={slot.interval} session={session} panel={panels.get(frameKey(slot))} pending={pendingFor(slot)} live={lives.get(slot.symbol)!} indicators={settings.indicators} levels={settings.levels[slot.symbol] ?? NO_LEVELS} link={link} rangeLink={rangeLink} linkRange={settings.linkRange && multi} clock={clockFor(slot.symbol)} height={mainHeight} drawing={drawing} onDraw={addLevel} onInterval={(i) => setIntervalAt(0, i)}
              history={currentOlder[frameKey(slot)]} onNeedHistory={(before) => void loadOlder(slot, before)} onRetryHistory={() => void loadOlder(slot, undefined, true)} onVisibleRange={(range) => visibleTimes.current.set(frameKey(slot), range)} />)}
            {multi && <div className="grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
              {slots.slice(1).map((slot) => { const index = slot.index - 1; return <div key={slot.index} className={expanded === index ? "sm:col-span-2 xl:col-span-4" : "min-w-0"}>
                <PriceChart id={`Panel ${slot.index + 1}`} symbol={slot.symbol} follows={!settings.panelSymbols[slot.index]} onPickSymbol={() => setPalette(slot.index)}
                  notice={slot.symbol !== symbol && settings.indicators.fills && feedFor(slot.symbol)?.fills_truncated ? `Most recent 1,000 ${slot.symbol} fills shown.` : null} interval={slot.interval} session={session} panel={panels.get(frameKey(slot))} pending={pendingFor(slot)} live={lives.get(slot.symbol)!} indicators={settings.indicators} levels={settings.levels[slot.symbol] ?? NO_LEVELS} link={link} rangeLink={rangeLink} linkRange={settings.linkRange} clock={clockFor(slot.symbol)}
                  history={currentOlder[frameKey(slot)]} onNeedHistory={(before) => void loadOlder(slot, before)} onRetryHistory={() => void loadOlder(slot, undefined, true)} onVisibleRange={(range) => visibleTimes.current.set(frameKey(slot), range)}
                  height={expanded === index ? Math.max(smallHeight, immersive ? Math.round(viewport.height * 0.6) : 420) : smallHeight} expanded={expanded === index}
                  onExpand={() => setExpanded((v) => v === index ? null : index)} onDraw={(value) => addLevel(value, slot.symbol)} onInterval={(i) => setIntervalAt(slot.index, i)}
                  onFocus={() => { setExpanded(null); setSettings((s) => focusPanel(s, slot.index)); }} />
              </div>; })}
            </div>}
          </> : <div className="flex min-h-[490px] flex-col items-center justify-center rounded-lg border border-slate-700/50 bg-[#10151e] px-8 text-center">
            {loading ? <Loader2 className="mb-4 animate-spin text-sky-300" size={28} /> : <ChartCandlestick className="mb-4 text-slate-600" size={36} />}
            <p className="text-sm font-medium text-slate-200">{loading ? `Loading ${settings.symbol} candles…` : "Your chart workspace is ready"}</p>
            <p className="mt-2 max-w-md text-xs leading-6 text-slate-500">{loading ? "Loading shared intraday and daily history from Tradier." : "Charts appear when Tradier market data is available. Your watchlist, intervals, and levels are saved to your workspace on every device."}</p>
          </div>}
          <LiveFooter live={live} quote={selected} candle={latestCandle} asOf={current ? current.intraday_as_of : undefined} />
        </div>

        {showAside && <aside className="min-w-0 space-y-3">
          <section className="overflow-hidden rounded-lg border border-slate-700/50 bg-[#141b25]" aria-label="Watchlist">
            <div className="flex items-center justify-between border-b border-slate-700/40 px-3 py-3"><h2 className="text-xs font-medium text-slate-200">Watchlist <span className="ml-1 text-slate-500">{settings.watchlist.length}</span></h2>
              <button aria-label={`Add ${settings.symbol} to watchlist`} title={`Add ${settings.symbol}`} disabled={settings.watchlist.includes(settings.symbol) || settings.watchlist.length >= 30} onClick={() => setSettings((s) => ({ ...s, watchlist: [...s.watchlist, s.symbol] }))} className="rounded p-1 hover:bg-slate-800 disabled:opacity-30"><Plus size={14} /></button></div>
            <div className="grid grid-cols-[1fr_60px_54px_18px] gap-1 px-3 py-2 text-[9px] uppercase tracking-wider text-slate-600"><span>Symbol</span><span className="text-right">Quote</span><span className="text-right">Chg%</span></div>
            {settings.watchlist.map((symbol) => {
              const quote = latest?.quotes.find((q) => q.symbol === symbol);
              return <div key={symbol} className={`group flex items-center border-l-2 ${settings.symbol === symbol ? "border-sky-400 bg-sky-400/5" : "border-transparent hover:bg-slate-800/50"}`}>
                <button data-watch-row onKeyDown={watchKey} onClick={() => chooseSymbol(symbol)} aria-label={`Chart ${symbol}`} aria-current={settings.symbol === symbol || undefined} className="grid min-w-0 flex-1 grid-cols-[1fr_60px_54px] items-center gap-1 py-3 pl-2.5 pr-1 text-[11px]"><span className="truncate text-left font-medium text-slate-200">{symbol}</span><span className="text-right font-mono text-slate-400">{price(quote?.last)}</span><span className={`text-right font-mono ${quote?.change_percentage != null && quote.change_percentage < 0 ? "text-rose-400" : "text-emerald-400"}`}>{quote?.change_percentage == null ? "—" : `${quote.change_percentage >= 0 ? "+" : ""}${quote.change_percentage.toFixed(2)}`}</span></button>
                <button aria-label={`Remove ${symbol} from watchlist`} className="mr-2 rounded p-0.5 text-slate-600 hover:text-rose-300" onClick={() => setSettings((s) => ({ ...s, watchlist: s.watchlist.filter((v) => v !== symbol) }))}><X size={12} /></button>
              </div>;
            })}
            {!settings.watchlist.length && <p className="px-3 pb-4 text-xs text-slate-500">Look up a ticker, then use + to add it.</p>}
          </section>

          {!immersive && <><section className="rounded-lg border border-slate-700/50 bg-[#141b25] p-3" aria-label="Saved price levels">
            <div className="mb-3 flex items-center justify-between"><h2 className="text-xs font-medium text-slate-200">{settings.symbol} levels</h2><span className="text-[10px] text-slate-600">{levels.length}/30</span></div>
            {levels.map((level) => <div key={level.id} className="mb-2 flex items-center gap-2 text-[11px]"><span className="h-px w-3 bg-blue-400" /><span className="min-w-0 flex-1 truncate text-slate-400">{level.label}</span><span className="font-mono text-blue-300">{price(level.price)}</span><button aria-label={`Delete ${level.label}`} onClick={() => setSettings((s) => ({ ...s, levels: { ...s.levels, [s.symbol]: (s.levels[s.symbol] ?? []).filter((v) => v.id !== level.id) } }))} className="p-1 text-slate-600 hover:text-rose-300"><Trash2 size={12} /></button></div>)}
            {!levels.length && <p className="mb-3 text-[11px] leading-5 text-slate-500">Save support, resistance, or a price you’re watching.</p>}
            <form onSubmit={(e) => { e.preventDefault(); addLevel(Number(levelPrice)); }} className="space-y-2">
              <input aria-label="Level label" placeholder="Label (optional)" value={levelLabel} maxLength={30} onChange={(e) => setLevelLabel(e.target.value)} className="h-8 w-full rounded border border-slate-700 bg-[#10151e] px-2 text-xs outline-none focus:border-sky-600" />
              <div className="flex gap-2"><input aria-label="Level price" type="number" step="any" min="0.000001" required placeholder="Price" value={levelPrice} onChange={(e) => setLevelPrice(e.target.value)} className="h-8 min-w-0 flex-1 rounded border border-slate-700 bg-[#10151e] px-2 font-mono text-xs outline-none focus:border-sky-600" /><button type="submit" aria-label="Save price level" className={button}><Plus size={14} /></button></div>
            </form>
            {levelError && <p role="alert" className="mt-2 text-[11px] text-amber-300">{levelError}</p>}
          </section>

          <section className="rounded-lg border border-slate-700/50 bg-[#141b25] p-3" aria-label="Journal executions"><h2 className="mb-3 text-xs font-medium text-slate-200">On your journal</h2>
            {current?.fills.length ? <div className="space-y-3">{current.fills.slice(-5).reverse().map((fill) => <Link key={fill.id} href={`/fills/${fill.id}`} className="block text-[11px]"><span className="text-slate-300 hover:text-sky-300">{fill.label}</span><span className="mt-0.5 block text-[10px] text-slate-600">{etTime(fill.time, true)} · {etTime(fill.time)} ET</span></Link>)}{current.fills_truncated && <p className="text-[10px] text-amber-300">Most recent 1,000 fills shown.</p>}</div> : <p className="text-[11px] leading-5 text-slate-500">Your executions appear as arrows on the underlying chart when they fall inside a displayed candle.</p>}
          </section></>}
        </aside>}
      </div>

      {palette !== null && <SymbolPalette current={palette ? slots.find((slot) => slot.index === palette)?.symbol ?? symbol : symbol} recent={settings.recent} watchlist={settings.watchlist} quotes={latest?.quotes ?? []}
        panel={palette ? { name: `Panel ${palette + 1}`, follow: symbol, held: settings.panelSymbols[palette] } : undefined}
        onChoose={(choice) => palette ? choosePanelSymbol(palette, choice) : chooseSymbol(choice)} onFollow={() => { if (palette) choosePanelSymbol(palette, null); }} onClose={() => setPalette(null)} />}
      {layoutMenu && <LayoutMenu layouts={settings.layouts} current={arrangementOf(settings)} onApply={chooseLayout} onSave={saveLayout} onRename={renameLayout}
        onUpdate={updateLayout} onDelete={deleteLayout} onClose={() => setLayoutMenu(false)} />}
      {!immersive && <footer className="flex flex-wrap items-start justify-between gap-3 border-t border-slate-800 pt-3 text-[10px] leading-5 text-slate-600">
        <p className="max-w-3xl">{latest?.history_note ?? "US stock and ETF charts powered by Tradier."} RTH VWAP uses minute HLC3 and resets at 9:30 ET. Live trade prices update candles while connected; volume and studies reconcile from Tradier every 15 seconds. Watchlist quotes may show the regular close after hours.</p>
        <div className="text-right"><a href="https://www.tradingview.com/" target="_blank" rel="noreferrer" className="text-slate-500 hover:text-slate-300">TradingView Lightweight Charts™</a><a href="/lightweight-charts-NOTICE.txt" className="block">Copyright (с) 2025 TradingView, Inc.</a></div>
      </footer>}
    </div>
  );
}
