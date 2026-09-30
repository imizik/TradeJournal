"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, ChartCandlestick, Check, Columns3, Crosshair, Expand, Link2, Loader2, Maximize2, Pause, Play, Plus, RefreshCw, Search, Trash2, X } from "lucide-react";
import PriceChart from "./PriceChart";
import SymbolPalette from "./SymbolPalette";
import { barClock, chartStreamUrl, createCrosshairLink, createRangeLink, DEFAULT_SETTINGS, etTime, fetchChartData, fetchChartHistory, INTERVALS, mergeBars, overlayLiveTicks, parseChartTick, price, restoreSettings, retainHistory, SMALL_HEIGHTS, STORAGE_KEY, validSymbol } from "@/lib/charts";
import type { ChartBar, ChartData, ChartSettings, ChartStreamTick, FillMarker, Indicators, Interval, SmallChartSize } from "@/lib/charts";

const INDICATORS: [keyof Indicators, string][] = [["ema9", "EMA 9"], ["ema20", "EMA 20"], ["ema50", "EMA 50"], ["ema200", "EMA 200"], ["vwap", "RTH VWAP"], ["volume", "Volume"], ["rsi", "RSI 14"], ["fills", "My fills"]];
const button = "inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-slate-700/60 px-2.5 text-xs transition-colors hover:bg-slate-800 disabled:opacity-40";
type OlderPanel = { bars: ChartBar[]; markers: FillMarker[]; exhausted: boolean; warmup: string; issue: string | null; loading: boolean };
type OlderState = { key: string; panels: Partial<Record<Interval, OlderPanel>> };

export default function ChartWorkspace() {
  const [settings, setSettings] = useState<ChartSettings>(DEFAULT_SETTINGS);
  const [ready, setReady] = useState(false);
  const [saved, setSaved] = useState(true);
  const [response, setResponse] = useState<{ key: string; data: ChartData } | null>(null);
  const [older, setOlder] = useState<OlderState>({ key: "", panels: {} });
  const [rollover, setRollover] = useState<{ key: string; before: number; pending: Interval[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [paused, setPaused] = useState(false);
  const [clock, setClock] = useState(0);
  const [stream, setStream] = useState<{ key: string; status: "connecting" | "connected" | "fallback"; ticks: ChartStreamTick[] }>({ key: "", status: "fallback", ticks: [] });
  const [symbolInput, setSymbolInput] = useState("");
  const [symbolError, setSymbolError] = useState("");
  const [drawing, setDrawing] = useState(false);
  const [levelPrice, setLevelPrice] = useState("");
  const [levelLabel, setLevelLabel] = useState("");
  const [levelError, setLevelError] = useState("");
  const [immersive, setImmersive] = useState(false);
  const [palette, setPalette] = useState(false);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [viewport, setViewport] = useState({ width: 1280, height: 900 });
  const link = useMemo(() => createCrosshairLink(), []);
  const rangeLink = useMemo(() => createRangeLink(), []);
  const inFlight = useRef(false);
  const refreshNow = useRef<() => void>(() => {});
  const lastRequest = useRef("");
  const historyFlights = useRef(new Map<Interval, AbortController>());
  const visibleTimes = useRef(new Map<Interval, { from: number; to: number }>());
  const lastWorkspaceDay = useRef<{ key: string; day: string } | null>(null);
  const intervalKey = (settings.layout === "single" ? settings.intervals.slice(0, 1) : settings.intervals).join(",");
  const watchlistKey = settings.watchlist.join(",");
  const requestKey = `${settings.symbol}|${settings.session}|${intervalKey}|${watchlistKey}`;
  const historyKey = `${settings.symbol}|${settings.session}|${intervalKey}`;
  const data = response?.key === requestKey ? response.data : null;
  const currentOlder = useMemo(() => older.key === historyKey ? older.panels : {}, [older, historyKey]);
  const hasData = !!data;
  const activeStream = stream.key === requestKey ? stream : null;
  const viewData = useMemo(() => {
    if (!data) return null;
    const live = overlayLiveTicks(data, activeStream?.ticks ?? [], settings.session);
    const panels = { ...live.panels };
    for (const interval of INTERVALS) {
      const tail = panels[interval];
      const past = currentOlder[interval];
      if (!tail || !past?.bars.length) continue;
      const bars = mergeBars(retainHistory(past.bars, tail.bars, visibleTimes.current.get(interval) ?? null), tail.bars);
      const times = new Set(bars.map((bar) => bar.time));
      panels[interval] = { bars, markers: [...new Map([...past.markers, ...tail.markers].filter((m) => times.has(m.time)).map((m) => [`${m.id}:${m.time}`, m])).values()] };
    }
    return { ...live, panels };
  }, [data, activeStream, settings.session, currentOlder]);
  const selected = data?.quotes.find((q) => q.symbol === settings.symbol);
  const levels = useMemo(() => settings.levels[settings.symbol] ?? [], [settings.levels, settings.symbol]);

  useEffect(() => { setSettings(restoreSettings()); setReady(true); }, []);
  useEffect(() => {
    historyFlights.current.forEach((controller) => controller.abort());
    historyFlights.current.clear();
    visibleTimes.current.clear();
    setOlder({ key: historyKey, panels: {} });
    setRollover(null);
  }, [historyKey]);

  const loadOlder = useCallback(async (interval: Interval, beforeOverride?: number, retry = false) => {
    if (interval === "1D" || interval === "1W" || historyFlights.current.has(interval) || !data) return;
    const past = currentOlder[interval];
    if (((past?.exhausted || past?.issue) && !retry) && beforeOverride === undefined) return;
    const before = beforeOverride ?? past?.bars[0]?.time ?? data.panels[interval]?.bars[0]?.time ?? Math.floor(Date.now() / 1000);
    const controller = new AbortController();
    historyFlights.current.set(interval, controller);
    setOlder((state) => state.key !== historyKey ? state : ({ ...state, panels: { ...state.panels,
      [interval]: { bars: past?.bars ?? [], markers: past?.markers ?? [], exhausted: past?.exhausted ?? false,
        warmup: past?.warmup ?? "pending", issue: null, loading: true } } }));
    let continuation: string | null = null;
    try {
      while (!controller.signal.aborted) {
        const page = await fetchChartHistory({ symbol: settings.symbol, interval, session: settings.session, before, continuation, signal: controller.signal });
        if (controller.signal.aborted) return;
        setOlder((state) => {
          if (state.key !== historyKey) return state;
          const prior = state.panels[interval];
          const live = data.panels[interval]?.bars ?? [];
          const combined = mergeBars(prior?.bars ?? [], page.bars);
          const retained = retainHistory(combined, live, visibleTimes.current.get(interval) ?? null);
          if (retained.length + live.length > 12000) return { ...state, panels: { ...state.panels, [interval]: {
            ...(prior ?? { bars: [], markers: [], exhausted: false, warmup: "pending", loading: false }),
            issue: "Visible candles fill the 12,000-candle limit. Zoom in before loading more.", loading: false } } };
          const times = new Set(retained.map((bar) => bar.time));
          const markers = [...new Map([...(prior?.markers ?? []), ...page.markers].filter((m) => times.has(m.time)).map((m) => [`${m.id}:${m.time}`, m])).values()];
          return { ...state, panels: { ...state.panels, [interval]: { bars: retained, markers,
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
      if (!controller.signal.aborted) setOlder((state) => state.key !== historyKey ? state : ({ ...state, panels: { ...state.panels,
        [interval]: { bars: state.panels[interval]?.bars ?? [], markers: state.panels[interval]?.markers ?? [],
          exhausted: false, warmup: state.panels[interval]?.warmup ?? "pending",
          issue: err instanceof Error ? err.message : "Older candles could not load.", loading: false } } }));
    } finally {
      if (historyFlights.current.get(interval) === controller) historyFlights.current.delete(interval);
      setOlder((state) => state.key !== historyKey || !state.panels[interval] ? state : ({ ...state,
        panels: { ...state.panels, [interval]: { ...state.panels[interval], loading: false } } }));
    }
  }, [data, currentOlder, historyKey, settings.symbol, settings.session]);
  useEffect(() => {
    if (!rollover || rollover.key !== historyKey || !data) return;
    const available = rollover.pending.filter((interval) => !historyFlights.current.has(interval));
    if (!available.length) return;
    available.forEach((interval) => { void loadOlder(interval, rollover.before); });
    setRollover((current) => current === rollover ? { ...current, pending: current.pending.filter((interval) => !available.includes(interval)) } : current);
  }, [rollover, historyKey, data, older, loadOlder]);
  useEffect(() => {
    if (!ready) return;
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(settings)); setSaved(true); }
    catch { setSaved(false); }
  }, [settings, ready]);
  useEffect(() => {
    const tick = () => setClock(Date.now() / 1000);
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, []);

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
    if (lastRequest.current !== requestKey) setError(null);
    const load = async () => {
      if (!alive || busy || document.hidden) return;
      busy = true;
      inFlight.current = true;
      controller = new AbortController();
      setLoading(true);
      try {
        const result = await fetchChartData({ ...DEFAULT_SETTINGS, symbol: settings.symbol, session: settings.session,
          intervals: intervalKey.split(",") as Interval[], watchlist: watchlistKey ? watchlistKey.split(",") : [], layout: "multi" }, controller.signal);
        if (alive) {
          const day = new Date(result.checked_at * 1000).toLocaleDateString("en-CA", { timeZone: "America/New_York" });
          if (lastWorkspaceDay.current?.key === requestKey && lastWorkspaceDay.current.day !== day) {
            setRollover({ key: historyKey, before: result.checked_at,
              pending: intervalKey.split(",").filter((interval): interval is Interval => interval !== "1D" && interval !== "1W") });
          }
          lastWorkspaceDay.current = { key: requestKey, day };
          setResponse({ key: requestKey, data: result }); setError(null);
        }
      } catch (err) {
        if (alive && !controller.signal.aborted) setError(err instanceof Error ? err.message : "Unable to refresh charts.");
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
  }, [ready, settings.symbol, settings.session, intervalKey, watchlistKey, requestKey, historyKey, paused]);

  useEffect(() => {
    if (!ready || !hasData || paused) return;
    let alive = true;
    let source: EventSource | null = null;
    const status = (value: "connecting" | "connected" | "fallback") => {
      if (alive) setStream((prior) => ({ key: requestKey, status: value, ticks: prior.key === requestKey ? prior.ticks : [] }));
    };
    const connect = () => {
      if (document.hidden || source) return;
      status("connecting");
      source = new EventSource(chartStreamUrl(settings.symbol));
      source.addEventListener("status", (event) => {
        try { status(JSON.parse((event as MessageEvent).data).state === "connected" ? "connected" : "fallback"); }
        catch { status("fallback"); }
      });
      source.addEventListener("tick", (event) => {
        try {
          const tick = parseChartTick(JSON.parse((event as MessageEvent).data));
          if (!alive || !tick || tick.symbol !== settings.symbol) return;
          setStream((prior) => ({ key: requestKey, status: "connected",
            ticks: [...(prior.key === requestKey ? prior.ticks : []).filter((old) => old.at > Date.now() / 1000 - 120), tick].slice(-120) }));
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
  }, [ready, hasData, paused, requestKey, settings.symbol]);

  // Intervals are workspace settings, not per-symbol, so they carry over.
  const chooseSymbol = (symbol: string) => {
    setSettings((s) => s.symbol === symbol ? s : ({ ...s, symbol, recent: [s.symbol, ...s.recent.filter((r) => r !== s.symbol && r !== symbol)].slice(0, 8) }));
    setDrawing(false); setSymbolInput(""); setSymbolError(""); setLevelPrice(""); setPalette(false);
  };
  const choose = useRef(chooseSymbol);
  const keys = useRef({ palette, immersive, watchlist: settings.watchlist, symbol: settings.symbol });
  useEffect(() => {
    choose.current = chooseSymbol;
    keys.current = { palette, immersive, watchlist: settings.watchlist, symbol: settings.symbol };
  });
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const state = keys.current;
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); setPalette((v) => !v); return; }
      if (state.palette) return;
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
  const addLevel = (value: number) => {
    if (!Number.isFinite(value) || value <= 0) { setLevelError("Enter a positive price."); return; }
    if (levels.length >= 30) { setLevelError("Remove a level before adding another (30 per symbol)."); return; }
    const level = { id: crypto.randomUUID(), price: value, label: levelLabel.trim().slice(0, 30) || `Level ${levels.length + 1}` };
    setSettings((s) => ({ ...s, levels: { ...s.levels, [s.symbol]: [...(s.levels[s.symbol] ?? []), level] } }));
    setDrawing(false); setLevelPrice(""); setLevelLabel(""); setLevelError("");
  };
  const candleAge = data?.fetched_at.intraday ? Math.max(0, Math.floor(clock - data.fetched_at.intraday)) : null;
  const oldData = !!error || !!data?.issues.length || (candleAge !== null && candleAge > 45);
  const intradayInterval = settings.intervals.find((interval) => interval !== "1D" && interval !== "1W");
  const latestCandle = intradayInterval ? viewData?.panels[intradayInterval]?.bars.at(-1) : undefined;
  const latestTick = activeStream?.ticks.at(-1);
  const streamedPrice = latestTick && latestTick.at > (data?.fetched_at.intraday ?? 0)
    && (settings.session === "extended" || latestTick.session === "regular") ? latestTick.price : null;
  const extendedPrice = settings.session === "extended" && latestCandle?.extended && latestCandle.time > (selected?.trade_time ?? 0) ? latestCandle.close : null;
  const shownPrice = streamedPrice ?? extendedPrice ?? selected?.last;
  const priceSource = streamedPrice !== null ? "Live trade" : extendedPrice !== null ? "Extended-hours candle" : "Tradier quote";
  const shownAt = streamedPrice !== null ? latestTick?.at : extendedPrice !== null ? latestCandle?.time : selected?.trade_time;
  const priceAge = shownAt ? Math.max(0, Math.floor(clock - shownAt)) : null;
  const clockFor = (interval: Interval) => barClock({ now: clock, interval, bars: viewData?.panels[interval]?.bars, session: settings.session,
    paused, delayed: !!data?.delayed, stale: oldData });
  const smallHeight = SMALL_HEIGHTS[settings.smallSize];
  const multi = settings.layout === "multi";
  // Immersive: the main chart fills the screen below the toolbar. On a tall,
  // wide screen the row of smaller charts also fits without scrolling.
  const fillHeight = viewport.height - 260;
  const withRow = multi && viewport.width >= 1280 && fillHeight - smallHeight - 70 >= 520;
  const mainHeight = immersive ? Math.max(420, withRow ? fillHeight - smallHeight - 70 : fillHeight) : 410;
  const showAside = !immersive || settings.immersiveWatchlist;
  const change = shownPrice != null && selected?.previous_close && selected.previous_close > 0
    ? (shownPrice / selected.previous_close - 1) * 100 : selected?.change_percentage;

  return (
    <div data-testid="chart-workspace" data-immersive={immersive || undefined} className={immersive
      ? "fixed inset-0 z-[70] space-y-2 overflow-y-auto overscroll-contain bg-[#0b1017] px-2 pb-[calc(0.5rem+env(safe-area-inset-bottom))] pl-[max(0.5rem,env(safe-area-inset-left))] pr-[max(0.5rem,env(safe-area-inset-right))] text-slate-300 sm:px-3"
      : "space-y-4 text-slate-300"}>
      <header className={`flex flex-wrap items-center justify-between gap-3 ${immersive ? "sticky top-0 z-20 -mx-2 bg-[#0b1017]/95 px-2 pb-2 pt-[max(0.5rem,env(safe-area-inset-top))] backdrop-blur sm:-mx-3 sm:px-3" : ""}`}>
        <div>{!immersive && <div className="mb-1 flex items-center gap-2 text-[10px] font-medium uppercase tracking-[0.18em] text-slate-500"><span className="h-1.5 w-1.5 rounded-full bg-sky-400" />Trade Journal / Markets</div>}
          <h1 className={`${immersive ? "text-base" : "text-2xl"} font-semibold tracking-tight text-slate-100`}>Charts</h1></div>
        <div className="flex flex-wrap items-center justify-end gap-2 text-xs">
          <span className="mr-1 hidden items-center gap-1.5 text-[11px] text-slate-500 lg:flex"><Check size={12} />{saved ? "Saved in this browser" : "Browser storage unavailable"}</span>
          <button className={`${button} hidden sm:inline-flex`} onClick={() => setPalette(true)} aria-label="Search symbols (Ctrl or Cmd+K)" title="Search symbols (⌘K / Ctrl+K)"><Search size={13} /><kbd className="text-[10px] text-slate-500">⌘K</kbd></button>
          {immersive && <button className={button} aria-pressed={settings.immersiveWatchlist} onClick={() => setSettings((s) => ({ ...s, immersiveWatchlist: !s.immersiveWatchlist }))}>{settings.immersiveWatchlist ? "Hide watchlist" : "Watchlist"}</button>}
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
            <button type="button" aria-label="Open symbol search" onClick={() => setPalette(true)} className="ml-2 rounded p-1 text-slate-500 hover:text-slate-200"><Search size={14} /></button><input aria-label="Chart symbol" value={symbolInput} placeholder={settings.symbol} onChange={(e) => setSymbolInput(e.target.value.toUpperCase())} maxLength={15} className="w-28 bg-transparent px-2 text-sm font-semibold uppercase text-slate-100 outline-none placeholder:text-slate-300" />
            <button type="submit" aria-label="Load symbol" className="mr-1 rounded p-1.5 hover:bg-slate-800"><ArrowUpRight size={14} /></button>
          </form>
          <div className="flex min-w-0 items-baseline gap-3" aria-label="Selected symbol quote"><span className="text-sm font-medium text-slate-200">{settings.symbol}</span><span className="font-mono text-2xl font-medium tracking-tight text-white">{price(shownPrice)}</span>
            <span className={`font-mono text-xs ${change != null && change < 0 ? "text-rose-400" : "text-emerald-400"}`}>{change == null ? "—" : `${change >= 0 ? "+" : ""}${change.toFixed(2)}%`}</span><span className="text-[10px] text-slate-500">{priceSource}</span></div>
          <div className="ml-auto flex items-center gap-2 text-[11px] text-slate-400" role="status">
            <span className={`h-1.5 w-1.5 rounded-full ${paused || oldData || data?.delayed ? "bg-amber-400" : data ? "bg-sky-400" : "bg-slate-600"}`} />
            {paused ? "Updates paused" : data?.delayed ? "Tradier sandbox · delayed" : activeStream?.status === "connected" ? "Tradier stream · studies refresh 15s" : "Tradier · 15s refresh"}
            {loading && <Loader2 size={12} className="animate-spin" />}
          </div>
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

      {error && <div role="alert" aria-label="Chart data error" className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-sm text-amber-200">{error}{data && <span className="ml-1">Showing the last successful data.</span>}</div>}
      {!!data?.issues.length && <div role="alert" aria-label="Chart data warning" className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-xs text-amber-200">Refresh incomplete. {data.issues.join(" ")} Check timestamps before using these charts.</div>}

      <div className={`grid min-w-0 gap-3 ${showAside ? "lg:grid-cols-[minmax(0,1fr)_230px]" : ""}`}>
        <div className="min-w-0 space-y-3">
          {viewData ? <>
            <PriceChart id="main" main symbol={settings.symbol} interval={settings.intervals[0]} session={settings.session} panel={viewData.panels[settings.intervals[0]]} indicators={settings.indicators} levels={levels} link={link} rangeLink={rangeLink} linkRange={settings.linkRange && multi} clock={clockFor(settings.intervals[0])} height={mainHeight} drawing={drawing} onDraw={addLevel} onInterval={(i) => setIntervalAt(0, i)}
              history={currentOlder[settings.intervals[0]]} onNeedHistory={(before) => void loadOlder(settings.intervals[0], before)} onRetryHistory={() => void loadOlder(settings.intervals[0], undefined, true)} onVisibleRange={(range) => visibleTimes.current.set(settings.intervals[0], range)} />
            {multi && <div className="grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
              {settings.intervals.slice(1).map((interval, index) => <div key={index} className={expanded === index ? "sm:col-span-2 xl:col-span-4" : "min-w-0"}>
                <PriceChart id={`Panel ${index + 2}`} symbol={settings.symbol} interval={interval} session={settings.session} panel={viewData.panels[interval]} indicators={settings.indicators} levels={levels} link={link} rangeLink={rangeLink} linkRange={settings.linkRange} clock={clockFor(interval)}
                  history={currentOlder[interval]} onNeedHistory={(before) => void loadOlder(interval, before)} onRetryHistory={() => void loadOlder(interval, undefined, true)} onVisibleRange={(range) => visibleTimes.current.set(interval, range)}
                  height={expanded === index ? Math.max(smallHeight, immersive ? Math.round(viewport.height * 0.6) : 420) : smallHeight} expanded={expanded === index}
                  onExpand={() => setExpanded((v) => v === index ? null : index)} onDraw={addLevel} onInterval={(i) => setIntervalAt(index + 1, i)} onFocus={() => { setExpanded(null); setSettings((s) => {
                    const frames = [...s.intervals]; [frames[0], frames[index + 1]] = [frames[index + 1], frames[0]]; return { ...s, intervals: frames };
                  }); }} />
              </div>)}
            </div>}
          </> : <div className="flex min-h-[490px] flex-col items-center justify-center rounded-lg border border-slate-700/50 bg-[#10151e] px-8 text-center">
            {loading ? <Loader2 className="mb-4 animate-spin text-sky-300" size={28} /> : <ChartCandlestick className="mb-4 text-slate-600" size={36} />}
            <p className="text-sm font-medium text-slate-200">{loading ? `Loading ${settings.symbol} candles…` : "Your chart workspace is ready"}</p>
            <p className="mt-2 max-w-md text-xs leading-6 text-slate-500">{loading ? "Loading shared intraday and daily history from Tradier." : "Charts appear when Tradier market data is available. Your watchlist, intervals, and levels are saved in this browser."}</p>
          </div>}
          <div className="flex flex-wrap items-center justify-between gap-2 px-1 text-[10px] text-slate-500">
            <span>{viewData?.intraday_as_of ? `Last minute candle ${etTime(viewData.intraday_as_of, true)} ${etTime(viewData.intraday_as_of)} ET` : "New York time"}{viewData?.intraday_as_of && " · latest candle may be forming"}</span>
            <span>{priceAge !== null ? `${priceSource} ${priceAge < 60 ? `${priceAge}s` : `${Math.floor(priceAge / 60)}m`} ago` : "No price timestamp"}</span>
          </div>
        </div>

        {showAside && <aside className="min-w-0 space-y-3">
          <section className="overflow-hidden rounded-lg border border-slate-700/50 bg-[#141b25]" aria-label="Watchlist">
            <div className="flex items-center justify-between border-b border-slate-700/40 px-3 py-3"><h2 className="text-xs font-medium text-slate-200">Watchlist <span className="ml-1 text-slate-500">{settings.watchlist.length}</span></h2>
              <button aria-label={`Add ${settings.symbol} to watchlist`} title={`Add ${settings.symbol}`} disabled={settings.watchlist.includes(settings.symbol) || settings.watchlist.length >= 30} onClick={() => setSettings((s) => ({ ...s, watchlist: [...s.watchlist, s.symbol] }))} className="rounded p-1 hover:bg-slate-800 disabled:opacity-30"><Plus size={14} /></button></div>
            <div className="grid grid-cols-[1fr_60px_54px_18px] gap-1 px-3 py-2 text-[9px] uppercase tracking-wider text-slate-600"><span>Symbol</span><span className="text-right">Quote</span><span className="text-right">Chg%</span></div>
            {settings.watchlist.map((symbol) => {
              const quote = data?.quotes.find((q) => q.symbol === symbol);
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
            {data?.fills.length ? <div className="space-y-3">{data.fills.slice(-5).reverse().map((fill) => <Link key={fill.id} href={`/fills/${fill.id}`} className="block text-[11px]"><span className="text-slate-300 hover:text-sky-300">{fill.label}</span><span className="mt-0.5 block text-[10px] text-slate-600">{etTime(fill.time, true)} · {etTime(fill.time)} ET</span></Link>)}{data.fills_truncated && <p className="text-[10px] text-amber-300">Most recent 1,000 fills shown.</p>}</div> : <p className="text-[11px] leading-5 text-slate-500">Your executions appear as arrows on the underlying chart when they fall inside a displayed candle.</p>}
          </section></>}
        </aside>}
      </div>

      {palette && <SymbolPalette current={settings.symbol} recent={settings.recent} watchlist={settings.watchlist} quotes={data?.quotes ?? []} onChoose={chooseSymbol} onClose={() => setPalette(false)} />}
      {!immersive && <footer className="flex flex-wrap items-start justify-between gap-3 border-t border-slate-800 pt-3 text-[10px] leading-5 text-slate-600">
        <p className="max-w-3xl">{data?.history_note ?? "US stock and ETF charts powered by Tradier."} RTH VWAP uses minute HLC3 and resets at 9:30 ET. Live trade prices update candles while connected; volume and studies reconcile from Tradier every 15 seconds. Watchlist quotes may show the regular close after hours.</p>
        <div className="text-right"><a href="https://www.tradingview.com/" target="_blank" rel="noreferrer" className="text-slate-500 hover:text-slate-300">TradingView Lightweight Charts™</a><a href="/lightweight-charts-NOTICE.txt" className="block">Copyright (с) 2025 TradingView, Inc.</a></div>
      </footer>}
    </div>
  );
}
