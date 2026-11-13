"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useKept } from "@/components/copilot/DeskMemory";
import { getDeskRead, type DeskRead as Read } from "@/lib/desk";

/**
 * The desk read (docs/copilot-lab.md § The desk read): when the owner selects a ticker and no conversation about it is
 * open, three or four lines on it in the copilot's answer voice, without his typing, and Ask more to carry them into the
 * conversation. Cost and noise are the point:
 * - a selection waits ``READ_WAIT_MS`` before asking, so clicking through the book asks for the one he stops on;
 * - a read kept for the ticker (here, then on the server) is shown with its age and asks for nothing until it expires;
 *   it is read again on Refresh, or once it expires while he is still on it with the page in view;
 * - a ticker he does not follow shows nothing; a spent day's budget is one grey line and no read;
 * - Auto-read off (this browser, kept in its storage) asks for nothing at all, and says so in one line to turn it on.
 * Nothing here asks him to rate or dismiss anything.
 */
export const READ_WAIT_MS = 1500;
const OFF_KEY = "desk.read.v1"; // "off": no automatic reads in this browser
const ET = "America/New_York";

// ``made`` and ``until``: this browser's clock when the read was made and when it stops being current.
type Kept = Read & { made: number; until: number };
const keptFrom = (read: Read): Kept => {
  const made = Date.now() - (read.age_s ?? 0) * 1000;
  // A second's margin: ``age_s`` is rounded, and asking before the server's read has expired would only get it back.
  return { ...read, made, until: made + Math.max(0, (read.expires_at ?? 0) - (read.at ?? 0) + 1) * 1000 };
};
const clock = (epoch: number) => new Date(epoch * 1000).toLocaleTimeString("en-US", { timeZone: ET, hour: "numeric", minute: "2-digit" });
const ago = (read: Kept, now: number) => {
  const minutes = Math.max(0, Math.floor((now - read.made) / 60_000));
  return minutes < 1 ? "just now" : `${minutes} min ago`;
};
const money = (usd: number) => `$${usd.toFixed(2)}`;

export function DeskRead({ symbol, render, onAskMore }: { symbol: string; render(text: string): ReactNode; onAskMore(text: string, at: string): void }) {
  const [on, setOn] = useState<boolean | null>(null); // null until this browser's setting is read
  useEffect(() => { try { setOn(window.localStorage.getItem(OFF_KEY) !== "off"); } catch { setOn(true); } }, []); // eslint-disable-line react-hooks/set-state-in-effect -- the store is read after hydration
  const [kept, keep] = useKept<Kept>(`desk.read:${symbol}`);
  const [read, setRead] = useState<Kept | null>(null);
  const [reading, setReading] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [asked, setAsked] = useState<{ symbol: string } | null>(null); // his Refresh (or Try again) on this ticker, a new object each tap
  // Another ticker forgets the Refresh, so coming back to this one never repeats it.
  const [askedOn, setAskedOn] = useState(symbol);
  if (askedOn !== symbol) { setAskedOn(symbol); setAsked(null); }
  const keptNow = useRef(kept);
  useEffect(() => { keptNow.current = kept; });

  useEffect(() => {
    if (!on) { setRead(null); setReading(false); setFailed(null); return; } // eslint-disable-line react-hooks/set-state-in-effect -- off asks nothing and shows no read
    const controller = new AbortController();
    const timers: number[] = [];
    let waitingForView: (() => void) | null = null;
    // ``quiet``: the server confirms a read already shown (it is kept there too, so no model call), and says "hidden" if he
    // has stopped following the ticker since.
    const fetchRead = (refresh: boolean, quiet = false) => {
      if (!quiet) { setReading(true); setFailed(null); }
      getDeskRead(symbol, refresh, controller.signal, quiet).then(result => {
        if (result.state === "none") { fetchRead(false); return; } // the server lost it (a restart): read it, visibly
        const next = keptFrom(result);
        keep(next); // a refusal or "hidden" replaces the kept read, so it is never shown again from here
        setRead(next);
        setReading(false);
        if (result.state === "ok") expireLater(next);
      }).catch(error => {
        if (controller.signal.aborted) return;
        if (quiet) { const shown = keptNow.current; if (shown?.state === "ok") expireLater(shown); return; } // the shown read stands until it expires
        setReading(false);
        setFailed(error instanceof Error ? error.message : String(error));
      });
    };
    // A read that expires while he is still on the ticker is read again; with the page out of view, once it is back. Not
    // forced: the server's read expires at the same moment, and two tabs on one ticker then share one call.
    const expireLater = (current: Kept) => {
      timers.push(window.setTimeout(() => {
        if (document.visibilityState === "visible") { fetchRead(false); return; }
        waitingForView = () => { if (document.visibilityState !== "visible") return; document.removeEventListener("visibilitychange", waitingForView!); waitingForView = null; fetchRead(false); };
        document.addEventListener("visibilitychange", waitingForView);
      }, Math.max(0, current.until - Date.now())));
    };
    const current = keptNow.current;
    if (asked?.symbol === symbol) fetchRead(true); // his Refresh: at once
    else if (current?.state === "ok" && current.until > Date.now()) {
      // The kept read at once, then confirmed after the same wait (its expiry is set from the confirmation).
      setRead(current); setReading(false); setFailed(null);
      timers.push(window.setTimeout(() => fetchRead(false, true), READ_WAIT_MS));
    }
    else { setRead(null); setReading(false); setFailed(null); timers.push(window.setTimeout(() => fetchRead(false), READ_WAIT_MS)); } // shows nothing while it waits
    return () => {
      controller.abort();
      timers.forEach(window.clearTimeout);
      if (waitingForView) document.removeEventListener("visibilitychange", waitingForView);
    };
  }, [symbol, on, asked, keep]);

  // The age line moves on by itself.
  useEffect(() => {
    if (read?.state !== "ok") return;
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, [read]);

  const turn = (next: boolean) => {
    try { window.localStorage.setItem(OFF_KEY, next ? "on" : "off"); } catch { /* this view only */ }
    setAsked(null);
    setOn(next);
  };
  if (on === null || read?.state === "hidden") return null;
  const today = read?.today;
  const switchLine = (
    <p data-testid="desk-read-switch" className="flex flex-wrap items-center gap-x-2 text-[11px] text-muted-foreground">
      {on ? <>Auto-read on{today ? <> · {today.count} today · {money(today.cost_usd)}</> : null}</> : "Auto-read is off"}
      <button type="button" onClick={() => turn(!on)} className="min-h-11 underline-offset-2 hover:text-foreground hover:underline sm:min-h-0">
        {on ? "Turn off" : "Turn on"}
      </button>
    </p>
  );
  const quiet = !(read?.state === "ok" && read.text) && !reading && read?.state !== "budget" && read?.state !== "error" && !failed;
  if (!on || quiet) return <section aria-label={`Read of ${symbol}`} data-testid="desk-read">{switchLine}</section>;
  return (
    <section aria-label={`Read of ${symbol}`} data-testid="desk-read" className="space-y-1.5 rounded-lg border bg-card/60 px-3 py-2.5">
      {read?.state === "ok" && read.text ? (
        <>
          <div data-testid="desk-read-text">{render(read.text)}</div>
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span data-testid="desk-read-age">Read {read.at ? `at ${clock(read.at)} · ` : ""}{ago(read, now)}</span>
            <button type="button" onClick={() => onAskMore(read.text!, read.at ? clock(read.at) : "")} data-testid="desk-read-ask"
              className="inline-flex min-h-11 items-center rounded-md border border-primary/50 px-2.5 text-xs font-medium text-foreground hover:bg-secondary sm:min-h-7">
              Ask more
            </button>
            <button type="button" disabled={reading} onClick={() => setAsked({ symbol })} data-testid="desk-read-refresh"
              className="min-h-11 hover:text-foreground disabled:opacity-50 sm:min-h-0">{reading ? "Reading…" : "Refresh"}</button>
          </p>
        </>
      ) : reading ? (
        <p data-testid="desk-read-wait" className="text-sm italic text-muted-foreground">Reading {symbol}…</p>
      ) : (
        <p data-testid="desk-read-none" className="text-sm text-muted-foreground">
          {read?.state === "budget" ? read.message : `No read of ${symbol}: ${failed ?? read?.message}`}
          {read?.state !== "budget" && <button type="button" onClick={() => setAsked({ symbol })} className="ml-2 min-h-11 underline-offset-2 hover:text-foreground hover:underline sm:min-h-0">Try again</button>}
        </p>
      )}
      {switchLine}
    </section>
  );
}
