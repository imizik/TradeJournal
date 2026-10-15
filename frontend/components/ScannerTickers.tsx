"use client";

import { useEffect, useState } from "react";
import { api, type ScannerSettings } from "@/lib/api";

const button = "inline-flex min-h-11 items-center justify-center rounded border px-3 text-sm hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-50";

export default function ScannerTickers() {
  const [saved, setSaved] = useState<ScannerSettings | null>(null);
  const [symbols, setSymbols] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function load() {
    setBusy(true);
    setError("");
    try {
      const current = await api.scannerSettings();
      setSaved(current);
      setSymbols(current.symbols);
      setInput("");
      setNotice("");
    } catch {
      setError("Could not load scanner tickers. Try reloading them.");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    let active = true;
    api.scannerSettings().then((current) => {
      if (active) { setSaved(current); setSymbols(current.symbols); }
    }).catch(() => {
      if (active) setError("Could not load scanner tickers. Try reloading them.");
    });
    return () => { active = false; };
  }, []);

  function withInput(): string[] | null {
    const added = input.trim() ? input.trim().toUpperCase().split(/[\s,]+/) : [];
    if (added.some((symbol) => !/^[A-Z][A-Z0-9./-]{0,14}$/.test(symbol))) {
      setError("Use ticker symbols such as AAPL or BRK.B, separated by commas or spaces.");
      return null;
    }
    const next = [...new Set([...symbols, ...added])];
    if (next.length > (saved?.max_symbols ?? 12)) {
      setError(`Choose up to ${saved?.max_symbols ?? 12} tickers. Remove one before adding another.`);
      return null;
    }
    setError("");
    return next;
  }

  function add() {
    const next = withInput();
    if (next) { setSymbols(next); setInput(""); }
  }

  async function save() {
    const next = withInput();
    if (!saved || !next) return;
    setBusy(true);
    setNotice("");
    try {
      const current = await api.saveScannerSettings(next, saved.revision);
      setSaved(current);
      setSymbols(current.symbols);
      setInput("");
      setEditing(false);
      setNotice("Saved. Applies on the next scan pass when the scanner is enabled.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save scanner tickers. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return <section aria-label="Scanner tickers" className="rounded-lg border bg-card p-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 className="text-sm font-semibold">Scanner tickers{saved && <span className="ml-2 font-normal text-muted-foreground">{(editing ? symbols : saved.symbols).length} / {saved.max_symbols}</span>}</h2>
      {saved && !editing && <button className={button} disabled={busy} onClick={() => { setEditing(true); setNotice(""); }}>Edit tickers</button>}
    </div>
    {!saved && !error && <p className="mt-2 text-sm text-muted-foreground">Loading tickers…</p>}
    {saved && <>
      <div className="mt-3 flex flex-wrap gap-2" aria-label={editing ? "Selected tickers" : "Saved tickers"}>
        {(editing ? symbols : saved.symbols).map((symbol) => editing
          ? <button key={symbol} aria-label={`Remove ${symbol}`} disabled={busy} onClick={() => { setSymbols(symbols.filter((s) => s !== symbol)); setError(""); }} className={`${button} gap-2 bg-secondary font-medium`}>{symbol}<span aria-hidden="true">×</span></button>
          : <span key={symbol} className="rounded bg-secondary px-2.5 py-1 text-sm font-medium">{symbol}</span>)}
      </div>
      {editing && <form className="mt-3" onSubmit={(event) => { event.preventDefault(); add(); }}>
        <label htmlFor="scanner-ticker-input" className="text-sm font-medium">Add tickers</label>
        <div className="mt-1 flex gap-2">
          <input id="scanner-ticker-input" value={input} onChange={(event) => setInput(event.target.value)} disabled={busy} autoCapitalize="characters" autoComplete="off" spellCheck={false} placeholder="e.g. MU, NVDA" aria-describedby="scanner-ticker-help" className="min-h-11 min-w-0 flex-1 rounded border bg-background px-3 text-sm uppercase placeholder:normal-case" />
          <button type="submit" disabled={busy || !input.trim()} className={button}>Add</button>
        </div>
        <p id="scanner-ticker-help" className="mt-2 text-xs text-muted-foreground">Up to {saved.max_symbols} US stock or ETF tickers. Market-data and option-contract availability still apply.</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" onClick={() => void save()} disabled={busy} className={`${button} bg-primary text-primary-foreground hover:bg-primary/90`}>{busy ? "Saving…" : "Save tickers"}</button>
          <button type="button" disabled={busy} className={button} onClick={() => { setSymbols(saved.symbols); setInput(""); setError(""); setEditing(false); }}>Cancel</button>
          <button type="button" disabled={busy} className={button} onClick={() => void load()}>Reload saved tickers</button>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">Changes are unsaved until you select Save tickers. An empty list pauses new setups.</p>
      </form>}
      {!saved.symbols.length && !editing && <p className="mt-2 text-sm text-amber-300">No tickers selected. New setups are paused.</p>}
      <p className="mt-3 text-xs text-muted-foreground">Applies to future scans on every device, regardless of the day shown below. Existing paper trades keep being monitored. Saving does not switch the scanner on.</p>
    </>}
    {error && <div className="mt-3"><p role="alert" className="break-words text-sm text-red-400">{error}</p>{!saved && <button className={`${button} mt-2`} disabled={busy} onClick={() => void load()}>Reload tickers</button>}</div>}
    {notice && <p role="status" className="mt-3 text-sm text-emerald-400">{notice}</p>}
  </section>;
}
