"use client";

import { useEffect, useState } from "react";
import { deskGet, everyDeskMinute } from "@/lib/deskMinute";
import { cn } from "@/lib/utils";

/**
 * The QQQ overnight paper book (backend app/engine/overnight_book.py): the one rule that passed its registered test
 * (research/notes/qqq-overnight-2026-11-14.md), recorded live before any money. It buys QQQ at 15:59 at the ask and
 * sells at the next open at the bid; this section shows whether it holds now, the recorded nights and the running
 * result beside the backtest. Read-only: nothing here places anything.
 */

type Night = { day: string; status: "open" | "closed" | "missed"; entry_at: number | null; entry: number | null;
  exit_day: string | null; exit_at: number | null; exit: number | null; bp: number | null; dollars: number | null; note: string | null };
type Book = { enabled: boolean; state: "holding" | "flat"; symbol: string; stake: number;
  backtest: { mean_bp: number; years: string };
  nights: Night[]; totals: { closed: number; missed: number; mean_bp: number | null; dollars: number | null; up: number } };

const LABEL = "text-[11px] font-medium uppercase tracking-wide text-muted-foreground";
const SHOWN = 5;

const bp = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n).toFixed(1)} bp`;
const usd = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : ""}$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const tone = (n: number | null) => n == null || n === 0 ? "text-muted-foreground" : n > 0 ? "text-emerald-300" : "text-rose-300";
const date = (day: string) => new Date(`${day}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric" });
/** An exit after 09:35 New York time: the recorder could not sell at the open (the provider or the server was down). */
const late = (epoch: number | null) => {
  if (epoch == null) return false;
  const [h, m] = new Date(epoch * 1000).toLocaleTimeString("en-GB", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit" }).split(":").map(Number);
  return h * 60 + m > 9 * 60 + 35;
};
const time = (epoch: number) => new Date(epoch * 1000).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });

export default function DeskOvernight({ on }: { on: boolean }) {
  const [book, setBook] = useState<Book | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!on) return;
    const controller = new AbortController();
    const load = () => deskGet("/copilot/desk/overnight", controller.signal)
      // Read the body even when refused: an unread one keeps the request open (and the page never idle).
      .then(async r => { const body = await r.json().catch(() => null); if (!r.ok || !body) throw new Error(String(r.status)); setBook(body); setFailed(false); })
      .catch(() => { if (!controller.signal.aborted) setFailed(true); });
    load();
    const stop = everyDeskMinute(load);
    return () => { controller.abort(); stop(); };
  }, [on]);
  if (!on || (!book && !failed)) return null;
  if (book && !book.enabled && book.nights.length === 0) return null; // not switched on yet: nothing to show
  const held = book?.nights.find(n => n.status === "open");
  const t = book?.totals;
  return (
    <section data-testid="desk-overnight" aria-label="QQQ overnight paper book" className="mt-3 rounded-md border px-3 py-2">
      <span className={LABEL}>QQQ overnight · paper</span>
      {failed || !book ? (
        <p data-testid="desk-overnight-failed" className="mt-1 text-xs text-muted-foreground">Could not read the overnight book; it reads again in a minute.</p>
      ) : (
        <>
          <p data-testid="desk-overnight-state" className="mt-1 text-sm">
            {held && held.entry != null && held.entry_at != null
              ? <>Holding since {date(held.day)} {time(held.entry_at)} at {held.entry.toFixed(2)} (the ask). Sells at the next open, at the bid.</>
              : <>Flat. Buys at 3:59 PM on a full session{book.enabled ? "" : " once switched on"}.</>}
          </p>
          {t && t.closed > 0 && (
            <p data-testid="desk-overnight-totals" className="mt-1 text-xs text-muted-foreground tabular-nums">
              {t.closed} {t.closed === 1 ? "night" : "nights"} · avg <span className={tone(t.mean_bp)}>{bp(t.mean_bp ?? 0)}</span>
              {" "}· <span className={tone(t.dollars)}>{usd(t.dollars ?? 0)}</span> on ${book.stake.toLocaleString("en-US")} a night · {t.up} up
              {t.missed > 0 && <> · {t.missed} missed</>}
            </p>
          )}
          <p className="mt-0.5 text-[11px] text-muted-foreground">Backtest {book.backtest.years}: {bp(book.backtest.mean_bp)} a night after costs.</p>
          {book.nights.filter(n => n.status !== "open").length > 0 && (
            <ul className="mt-1 space-y-0.5 text-xs tabular-nums">
              {book.nights.filter(n => n.status !== "open").slice(0, SHOWN).map(n => (
                <li key={n.day} className="flex justify-between gap-2">
                  <span className="min-w-0 truncate text-muted-foreground">{date(n.day)}{n.exit_day ? ` → ${date(n.exit_day)}` : ""}{late(n.exit_at) ? " · late" : ""}</span>
                  {n.status === "missed"
                    ? <span className="shrink-0 whitespace-nowrap text-muted-foreground">missed: no fresh quote</span>
                    : <span className="shrink-0 whitespace-nowrap"><span className={cn(tone(n.bp))}>{bp(n.bp ?? 0)}</span> <span className={cn("ml-1", tone(n.dollars))}>{usd(n.dollars ?? 0)}</span></span>}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
