"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, ChartCandlestick, Check, Columns3, Crosshair, Loader2, Maximize2, Pause, Play, Plus, RefreshCw, Search, Trash2, X } from "lucide-react";
import PriceChart from "./PriceChart";
import { createCrosshairLink, DEFAULT_SETTINGS, etTime, fetchChartData, INTERVALS, price, restoreSettings, STORAGE_KEY, validSymbol } from "@/lib/charts";
import type { ChartData, ChartSettings, Indicators, Interval } from "@/lib/charts";

const INDICATORS: [keyof Indicators, string][] = [["ema9", "EMA 9"], ["ema20", "EMA 20"], ["ema50", "EMA 50"], ["ema200", "EMA 200"], ["vwap", "RTH VWAP"], ["volume", "Volume"], ["rsi", "RSI 14"], ["fills", "My fills"]];
const button = "inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-slate-700/60 px-2.5 text-xs transition-colors hover:bg-slate-800 disabled:opacity-40";

export default function ChartWorkspace() {
  const [settings, setSettings] = useState<ChartSettings>(DEFAULT_SETTINGS);
  const [ready, setReady] = useState(false);
  const [saved, setSaved] = useState(true);
  const [response, setResponse] = useState<{ key: string; data: ChartData } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [paused, setPaused] = useState(false);
  const [clock, setClock] = useState(0);
  const [symbolInput, setSymbolInput] = useState("");
  const [symbolError, setSymbolError] = useState("");
  const [drawing, setDrawing] = useState(false);
  const [levelPrice, setLevelPrice] = useState("");
  const [levelLabel, setLevelLabel] = useState("");
  const [levelError, setLevelError] = useState("");
  const link = useMemo(() => createCrosshairLink(), []);
  const inFlight = useRef(false);
  const refreshNow = useRef<() => void>(() => {});
  const lastRequest = useRef("");
  const intervalKey = (settings.layout === "single" ? settings.intervals.slice(0, 1) : settings.intervals).join(",");
  const watchlistKey = settings.watchlist.join(",");
  const requestKey = `${settings.symbol}|${settings.session}|${intervalKey}|${watchlistKey}`;
  const data = response?.key === requestKey ? response.data : null;
  const selected = data?.quotes.find((q) => q.symbol === settings.symbol);
  const levels = useMemo(() => settings.levels[settings.symbol] ?? [], [settings.levels, settings.symbol]);

  useEffect(() => { setSettings(restoreSettings()); setReady(true); }, []);
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
        if (alive) { setResponse({ key: requestKey, data: result }); setError(null); }
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
  }, [ready, settings.symbol, settings.session, intervalKey, watchlistKey, requestKey, paused]);

  const chooseSymbol = (symbol: string) => {
    setSettings((s) => ({ ...s, symbol }));
    setDrawing(false); setSymbolInput(""); setSymbolError(""); setLevelPrice("");
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
  const quoteAge = selected?.trade_time ? Math.max(0, Math.floor(clock - selected.trade_time)) : null;
  const candleAge = data?.fetched_at.intraday ? Math.max(0, Math.floor(clock - data.fetched_at.intraday)) : null;
  const oldData = !!error || !!data?.issues.length || (candleAge !== null && candleAge > 45);
  const change = selected?.change_percentage;

  return (
    <div className="space-y-4 text-slate-300">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div><div className="mb-1 flex items-center gap-2 text-[10px] font-medium uppercase tracking-[0.18em] text-slate-500"><span className="h-1.5 w-1.5 rounded-full bg-sky-400" />Trade Journal / Markets</div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-100">Charts</h1></div>
        <div className="flex items-center gap-2 text-xs">
          <span className="mr-1 hidden items-center gap-1.5 text-[11px] text-slate-500 sm:flex"><Check size={12} />{saved ? "Saved in this browser" : "Browser storage unavailable"}</span>
          <button className={button} onClick={() => setSettings((s) => ({ ...s, layout: s.layout === "multi" ? "single" : "multi" }))} aria-label={settings.layout === "multi" ? "Show single chart" : "Show five charts"}>
            {settings.layout === "multi" ? <Maximize2 size={13} /> : <Columns3 size={13} />}{settings.layout === "multi" ? "Focus" : "Five charts"}</button>
          <button className={button} onClick={() => setPaused((v) => !v)} aria-label={paused ? "Resume chart updates" : "Pause chart updates"}>{paused ? <Play size={13} /> : <Pause size={13} />}{paused ? "Resume" : "Pause"}</button>
          <button className={button} disabled={loading} aria-label="Refresh charts" onClick={() => { if (!inFlight.current) refreshNow.current(); }}><RefreshCw size={13} className={loading ? "animate-spin" : ""} /></button>
        </div>
      </header>

      <div className="rounded-xl border border-slate-700/50 bg-[#141b25]">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-3 border-b border-slate-700/40 p-3">
          <form onSubmit={submitSymbol} className="relative flex h-9 items-center rounded-md border border-slate-700 bg-[#10151e]">
            <Search size={14} className="ml-3 text-slate-500" /><input aria-label="Chart symbol" value={symbolInput} placeholder={settings.symbol} onChange={(e) => setSymbolInput(e.target.value.toUpperCase())} maxLength={15} className="w-28 bg-transparent px-2 text-sm font-semibold uppercase text-slate-100 outline-none placeholder:text-slate-300" />
            <button type="submit" aria-label="Load symbol" className="mr-1 rounded p-1.5 hover:bg-slate-800"><ArrowUpRight size={14} /></button>
          </form>
          <div className="flex min-w-0 items-baseline gap-3" aria-label="Selected symbol quote"><span className="text-sm font-medium text-slate-200">{settings.symbol}</span><span className="font-mono text-2xl font-medium tracking-tight text-white">{price(selected?.last)}</span>
            <span className={`font-mono text-xs ${change != null && change < 0 ? "text-rose-400" : "text-emerald-400"}`}>{change == null ? "—" : `${change >= 0 ? "+" : ""}${change.toFixed(2)}%`}</span></div>
          <div className="ml-auto flex items-center gap-2 text-[11px] text-slate-400" role="status">
            <span className={`h-1.5 w-1.5 rounded-full ${paused || oldData || data?.delayed ? "bg-amber-400" : data ? "bg-sky-400" : "bg-slate-600"}`} />
            {paused ? "Updates paused" : data?.delayed ? "Tradier sandbox · delayed" : "Tradier · 15s refresh"}
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
        <span className="ml-auto text-[10px] text-slate-500">Linked symbols & crosshairs</span>
      </div>

      {error && <div role="alert" aria-label="Chart data error" className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-sm text-amber-200">{error}{data && <span className="ml-1">Showing the last successful data.</span>}</div>}
      {!!data?.issues.length && <div role="alert" aria-label="Chart data warning" className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-xs text-amber-200">Refresh incomplete. {data.issues.join(" ")} Check timestamps before using these charts.</div>}

      <div className="grid min-w-0 gap-3 lg:grid-cols-[minmax(0,1fr)_230px]">
        <div className="min-w-0 space-y-3">
          {data ? <>
            <PriceChart id="main" main symbol={settings.symbol} interval={settings.intervals[0]} panel={data.panels[settings.intervals[0]]} indicators={settings.indicators} levels={levels} link={link} drawing={drawing} onDraw={addLevel} onInterval={(i) => setIntervalAt(0, i)} />
            {settings.layout === "multi" && <div className="grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
              {settings.intervals.slice(1).map((interval, index) => <PriceChart key={index} id={`Panel ${index + 2}`} symbol={settings.symbol} interval={interval} panel={data.panels[interval]} indicators={settings.indicators} levels={levels} link={link} onDraw={addLevel} onInterval={(i) => setIntervalAt(index + 1, i)} onFocus={() => setSettings((s) => {
                const frames = [...s.intervals]; [frames[0], frames[index + 1]] = [frames[index + 1], frames[0]]; return { ...s, intervals: frames };
              })} />)}
            </div>}
          </> : <div className="flex min-h-[490px] flex-col items-center justify-center rounded-lg border border-slate-700/50 bg-[#10151e] px-8 text-center">
            {loading ? <Loader2 className="mb-4 animate-spin text-sky-300" size={28} /> : <ChartCandlestick className="mb-4 text-slate-600" size={36} />}
            <p className="text-sm font-medium text-slate-200">{loading ? `Loading ${settings.symbol} candles…` : "Your chart workspace is ready"}</p>
            <p className="mt-2 max-w-md text-xs leading-6 text-slate-500">{loading ? "Loading shared intraday and daily history from Tradier." : "Charts appear when Tradier market data is available. Your watchlist, intervals, and levels are saved in this browser."}</p>
          </div>}
          <div className="flex flex-wrap items-center justify-between gap-2 px-1 text-[10px] text-slate-500">
            <span>{data?.intraday_as_of ? `Last minute candle ${etTime(data.intraday_as_of, true)} ${etTime(data.intraday_as_of)} ET` : "New York time"}{data?.intraday_as_of && " · latest candle may be forming"}</span>
            <span>{quoteAge !== null ? `Last trade ${quoteAge < 60 ? `${quoteAge}s` : `${Math.floor(quoteAge / 60)}m`} ago` : "No quote timestamp"}</span>
          </div>
        </div>

        <aside className="min-w-0 space-y-3">
          <section className="overflow-hidden rounded-lg border border-slate-700/50 bg-[#141b25]" aria-label="Watchlist">
            <div className="flex items-center justify-between border-b border-slate-700/40 px-3 py-3"><h2 className="text-xs font-medium text-slate-200">Watchlist <span className="ml-1 text-slate-500">{settings.watchlist.length}</span></h2>
              <button aria-label={`Add ${settings.symbol} to watchlist`} title={`Add ${settings.symbol}`} disabled={settings.watchlist.includes(settings.symbol) || settings.watchlist.length >= 30} onClick={() => setSettings((s) => ({ ...s, watchlist: [...s.watchlist, s.symbol] }))} className="rounded p-1 hover:bg-slate-800 disabled:opacity-30"><Plus size={14} /></button></div>
            <div className="grid grid-cols-[1fr_60px_54px_18px] gap-1 px-3 py-2 text-[9px] uppercase tracking-wider text-slate-600"><span>Symbol</span><span className="text-right">Last</span><span className="text-right">Chg%</span></div>
            {settings.watchlist.map((symbol) => {
              const quote = data?.quotes.find((q) => q.symbol === symbol);
              return <div key={symbol} className={`group flex items-center border-l-2 ${settings.symbol === symbol ? "border-sky-400 bg-sky-400/5" : "border-transparent hover:bg-slate-800/50"}`}>
                <button onClick={() => chooseSymbol(symbol)} aria-label={`Chart ${symbol}`} className="grid min-w-0 flex-1 grid-cols-[1fr_60px_54px] items-center gap-1 py-3 pl-2.5 pr-1 text-[11px]"><span className="truncate text-left font-medium text-slate-200">{symbol}</span><span className="text-right font-mono text-slate-400">{price(quote?.last)}</span><span className={`text-right font-mono ${quote?.change_percentage != null && quote.change_percentage < 0 ? "text-rose-400" : "text-emerald-400"}`}>{quote?.change_percentage == null ? "—" : `${quote.change_percentage >= 0 ? "+" : ""}${quote.change_percentage.toFixed(2)}`}</span></button>
                <button aria-label={`Remove ${symbol} from watchlist`} className="mr-2 rounded p-0.5 text-slate-600 hover:text-rose-300" onClick={() => setSettings((s) => ({ ...s, watchlist: s.watchlist.filter((v) => v !== symbol) }))}><X size={12} /></button>
              </div>;
            })}
            {!settings.watchlist.length && <p className="px-3 pb-4 text-xs text-slate-500">Look up a ticker, then use + to add it.</p>}
          </section>

          <section className="rounded-lg border border-slate-700/50 bg-[#141b25] p-3" aria-label="Saved price levels">
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
          </section>
        </aside>
      </div>

      <footer className="flex flex-wrap items-start justify-between gap-3 border-t border-slate-800 pt-3 text-[10px] leading-5 text-slate-600">
        <p className="max-w-3xl">{data?.history_note ?? "US stock and ETF charts powered by Tradier."} RTH VWAP uses minute HLC3 and resets at 9:30 ET. Charts refresh while visible; this version does not stream ticks.</p>
        <div className="text-right"><a href="https://www.tradingview.com/" target="_blank" rel="noreferrer" className="text-slate-500 hover:text-slate-300">TradingView Lightweight Charts™</a><a href="/lightweight-charts-NOTICE.txt" className="block">Copyright (с) 2025 TradingView, Inc.</a></div>
      </footer>
    </div>
  );
}
