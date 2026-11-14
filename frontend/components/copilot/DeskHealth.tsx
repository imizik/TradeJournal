"use client";

/**
 * Is everything behind the desk live? (docs/copilot-lab.md § Data health) One dot in the desk's top bar: green with "All
 * live" in grey when every running source is live, amber when one is stale or down (it names it), grey when one cannot
 * be told. A tap opens the list: each source, its state and last good time in plain words; a tap on a source says what
 * it affects and, where one already exists, the fix.
 *
 * The server's rows (``GET /copilot/desk/health``) ride the desk's minute request (``deskMinute``): no poll of its own.
 * Level 2 is the Tape's own moomoo session, so its row comes from the Tape (``reportLevel2``): "off" with no session,
 * never an error.
 */

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { api } from "@/lib/api";
import { getHealth, type DeskHealth, type HealthRow, type HealthState } from "@/lib/desk";
import { everyDeskMinute } from "@/lib/deskMinute";
import { cn } from "@/lib/utils";

// --------------------------------------------------------------------------- Level 2, from the Tape

export type Level2Health = { running: boolean; failed: boolean; symbol: string | null; at: number | null };
const OFF: Level2Health = { running: false, failed: false, symbol: null, at: null };
let level2: Level2Health = OFF;
const level2Listeners = new Set<() => void>();

/** The Tape says what its depth session is doing (``null`` when it closes or unmounts). */
export function reportLevel2(next: Level2Health | null) {
  const value = next ?? OFF;
  if (value.running === level2.running && value.failed === level2.failed && value.symbol === level2.symbol && value.at === level2.at) return;
  level2 = value;
  for (const listener of level2Listeners) listener();
}
const subscribeLevel2 = (listener: () => void) => { level2Listeners.add(listener); return () => { level2Listeners.delete(listener); }; };

const LEVEL2_AFFECTS = "Level 2 and the Tape under the chart. It runs only while you have a Tape session open.";
export function level2Row(state: Level2Health): HealthRow {
  if (state.failed) return { id: "level2", name: "Level 2", state: "down", line: `Session stopped${state.symbol ? ` · ${state.symbol}` : ""}`, last_at: state.at, affects: LEVEL2_AFFECTS,
    fix: { kind: "text", text: "Open the Tape again to start a new session." } };
  if (state.running) return { id: "level2", name: "Level 2", state: "live", line: `Live${state.symbol ? ` · ${state.symbol}` : ""}`, last_at: state.at, affects: LEVEL2_AFFECTS, fix: null };
  return { id: "level2", name: "Level 2", state: "off", line: "Off · no Tape session open", last_at: null, affects: LEVEL2_AFFECTS, fix: null };
}

// --------------------------------------------------------------------------- the strip

const BAD: HealthState[] = ["stale", "down", "low"];
const DOT: Record<HealthState, string> = {
  live: "bg-emerald-400", closed: "bg-muted-foreground/50", off: "bg-muted-foreground/50", quiet: "bg-muted-foreground/50",
  unknown: "bg-muted-foreground/50", stale: "bg-amber-400", down: "bg-amber-400", low: "bg-amber-400",
};
const WORD: Record<HealthState, string> = {
  live: "live", closed: "closed", off: "off", quiet: "quiet", unknown: "unknown", stale: "behind", down: "down", low: "low",
};

/** The dot's summary from every row: amber naming the worst, grey when something cannot be told, else green. */
export function summary(rows: HealthRow[] | null, failed: boolean): { tone: "ok" | "unknown" | "bad"; text: string } {
  if (!rows) return { tone: "unknown", text: failed ? "Health unknown" : "Checking…" };
  const bad = rows.filter(r => BAD.includes(r.state));
  if (bad.length === 1) return { tone: "bad", text: `${bad[0].name} ${WORD[bad[0].state]}` };
  if (bad.length > 1) return { tone: "bad", text: `${bad.length} sources behind` };
  const unknown = rows.filter(r => r.state === "unknown");
  if (failed) return { tone: "unknown", text: "Health unknown" };
  if (unknown.length) return { tone: "unknown", text: unknown.length === 1 ? `${unknown[0].name} unknown` : `${unknown.length} unknown` };
  return { tone: "ok", text: rows.some(r => r.state === "live") ? "All live" : "All fine · market closed" };
}

export default function DeskHealthDot() {
  const [data, setData] = useState<DeskHealth | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);
  const tape = useSyncExternalStore(subscribeLevel2, () => level2, () => OFF);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let controller = new AbortController();
    const read = () => {
      controller.abort();
      controller = new AbortController();
      getHealth(controller.signal).then(next => { setData(next); setFailed(false); })
        .catch(error => { if ((error as Error).name !== "AbortError") setFailed(true); });
    };
    read();
    const stop = everyDeskMinute(read);
    return () => { controller.abort(); stop(); };
  }, []);

  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent | TouchEvent) => { if (box.current && !box.current.contains(event.target as Node)) setOpen(false); };
    const key = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away);
    document.addEventListener("touchstart", away);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("touchstart", away); document.removeEventListener("keydown", key); };
  }, [open]);

  // Level 2 sits after prices, where it belongs among the market data.
  const rows = data ? data.sources.flatMap(r => r.id === "prices" ? [r, level2Row(tape)] : [r]) : null;
  // A failed read keeps the last rows but never shows them as fine.
  const said = summary(rows, failed);
  const dot = said.tone === "bad" ? "bg-amber-400" : said.tone === "ok" ? "bg-emerald-400" : "bg-muted-foreground/50";

  return (
    <div ref={box} className="relative">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} aria-haspopup="true" data-testid="desk-health"
        data-tone={said.tone} aria-label={`Data health: ${said.text}`} title="Is every source behind the desk live?"
        className={cn("inline-flex min-h-11 min-w-11 items-center justify-center gap-1.5 rounded-md px-2 text-xs sm:min-h-8",
          said.tone === "bad" ? "text-amber-300" : "text-muted-foreground", open ? "bg-secondary" : "hover:bg-secondary")}>
        <span aria-hidden className={cn("h-2 w-2 shrink-0 rounded-full", dot)} />
        <span className="hidden whitespace-nowrap sm:inline">{said.text}</span>
      </button>
      {open && (
        <div role="dialog" aria-label="Data health" data-testid="desk-health-list"
          className="absolute right-0 top-full z-50 mt-1 w-[min(22rem,calc(100vw-2rem))] rounded-md border bg-card p-1 text-xs shadow-lg max-sm:fixed max-sm:left-4 max-sm:right-4 max-sm:top-14 max-sm:w-auto">
          <p className="px-2 pb-1 pt-1.5 text-muted-foreground">
            {failed ? "Could not check just now; the next minute asks again." : "What feeds the desk. Tap one for what it affects."}
          </p>
          <ul>
            {(rows ?? []).map(row => <Source key={row.id} row={row} open={picked === row.id} onPick={() => setPicked(picked === row.id ? null : row.id)} />)}
          </ul>
        </div>
      )}
    </div>
  );
}

function Source({ row, open, onPick }: { row: HealthRow; open: boolean; onPick(): void }) {
  const bad = BAD.includes(row.state);
  return (
    <li data-testid={`health-${row.id}`} data-state={row.state}>
      <button type="button" onClick={onPick} aria-expanded={open}
        className="flex min-h-9 w-full items-center gap-2 rounded px-2 py-1 text-left hover:bg-secondary">
        <span aria-hidden className={cn("h-1.5 w-1.5 shrink-0 rounded-full", DOT[row.state])} />
        <span className="w-24 shrink-0 font-medium text-foreground">{row.name}</span>
        <span className={cn("min-w-0 flex-1", bad ? "text-amber-300" : "text-muted-foreground")}>
          {row.line}<span className="sr-only"> ({WORD[row.state]})</span>
        </span>
      </button>
      {open && (
        <div className="space-y-1 px-2 pb-2 pl-[1.375rem] text-muted-foreground" data-testid={`health-${row.id}-more`}>
          <p>{row.affects}</p>
          {row.fix?.kind === "text" && <p className="text-foreground/80">{row.fix.text}</p>}
          {row.fix?.kind === "gmail_reconnect" && <GmailReconnect />}
        </div>
      )}
    </li>
  );
}

/** Gmail's existing Reconnect (the banner's ``/auth/gmail/start``): nothing new, the same sign-in page. */
function GmailReconnect() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const go = async () => {
    setBusy(true);
    setError(null);
    try {
      const { auth_url } = await api.startGmailAuth();
      window.location.assign(auth_url);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };
  return (
    <>
      <button type="button" onClick={go} disabled={busy}
        className="rounded border border-amber-400/40 px-2 py-1 font-medium text-amber-200 hover:bg-amber-500/10 disabled:opacity-60">
        {busy ? "Opening…" : "Reconnect Gmail"}
      </button>
      {error && <p className="text-amber-300">{error}</p>}
    </>
  );
}
