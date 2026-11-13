"use client";

import { useEffect, useState, type ReactNode } from "react";
import { afterClose, getDayRead, type DayRead as Read } from "@/lib/desk";

/**
 * The day read (docs/copilot-lab.md § The day read): after the close, the copilot panel opens with four to six lines on
 * the owner's day, written once a day on the server from the day report's facts (realised and open P&L by account, what
 * had a plan, the one thing that cost or saved the most and why, one thing to do differently tomorrow), and Ask more to
 * carry the read and its facts into the conversation. Cost and noise are the point:
 * - nothing is asked before 16:00 New York on a weekday; after it, one ask on the first open, and the server keeps the
 *   read for the day, so a reload or a second tab gets the same read and no call;
 * - a second read only on his Refresh;
 * - a day with no fills and no plans is one grey line, a spent day's budget one grey line, and nothing asks for a rating.
 */
const ET = "America/New_York";
const clock = (epoch: number) => new Date(epoch * 1000).toLocaleTimeString("en-US", { timeZone: ET, hour: "numeric", minute: "2-digit" });
const money = (usd: number) => `$${usd.toFixed(2)}`;

export function DayRead({ render, onAskMore }: { render(text: string): ReactNode; onAskMore(text: string, at: string, facts: string): void }) {
  const [closed, setClosed] = useState(false);
  useEffect(() => {
    const tick = () => setClosed(afterClose(new Date().toISOString()));
    tick();
    const timer = window.setInterval(tick, 60_000);
    return () => window.clearInterval(timer);
  }, []);
  const [read, setRead] = useState<Read | null>(null);
  const [reading, setReading] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const [asked, setAsked] = useState(0); // his Refresh taps

  useEffect(() => {
    if (!closed) return;
    const controller = new AbortController();
    setReading(true); setFailed(null); // eslint-disable-line react-hooks/set-state-in-effect -- the ask starts here
    getDayRead(asked > 0, controller.signal).then(result => { setRead(result); setReading(false); }).catch(error => {
      if (controller.signal.aborted) return;
      setReading(false);
      setFailed(error instanceof Error ? error.message : String(error));
    });
    return () => controller.abort();
  }, [closed, asked]);

  if (!closed || read?.state === "early" || (!read && !reading && !failed)) return null;
  const today = read?.today;
  const refresh = (label: string) => (
    <button type="button" disabled={reading} onClick={() => setAsked(n => n + 1)} data-testid="day-read-refresh"
      className="min-h-11 underline-offset-2 hover:text-foreground hover:underline disabled:opacity-50 sm:min-h-0">{reading ? "Reading…" : label}</button>
  );
  if (read?.state === "quiet" && !reading) {
    return <p data-testid="day-read" className="text-sm text-muted-foreground"><span data-testid="day-read-quiet">{read.text}</span></p>;
  }
  return (
    <section aria-label="Read of your day" data-testid="day-read" className="space-y-1.5 rounded-lg border bg-card/60 px-3 py-2.5">
      <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Your day</p>
      {read?.state === "ok" && read.text ? (
        <>
          <div data-testid="day-read-text">{render(read.text)}</div>
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span data-testid="day-read-age">Read {read.at ? `at ${clock(read.at)}` : ""}{today ? ` · ${today.count} today · ${money(today.cost_usd)}` : ""}</span>
            <button type="button" onClick={() => onAskMore(read.text!, read.at ? clock(read.at) : "", read.facts ?? "")} data-testid="day-read-ask"
              className="inline-flex min-h-11 items-center rounded-md border border-primary/50 px-2.5 text-xs font-medium text-foreground hover:bg-secondary sm:min-h-7">
              Ask more
            </button>
            {refresh("Refresh")}
          </p>
        </>
      ) : reading ? (
        <p data-testid="day-read-wait" className="text-sm italic text-muted-foreground">Reading your day…</p>
      ) : (
        <p data-testid="day-read-none" className="text-sm text-muted-foreground">
          {read?.state === "budget" || read?.state === "none" ? read.message : `No read of your day: ${failed ?? read?.message}`}
          {read?.state !== "budget" && <span className="ml-2">{refresh(read?.state === "none" ? "Refresh" : "Try again")}</span>}
        </p>
      )}
    </section>
  );
}
