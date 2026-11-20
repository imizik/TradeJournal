"use client";

import { useEffect, useState } from "react";
import { deskGet, everyDeskMinute } from "@/lib/deskMinute";
import { cn } from "@/lib/utils";
import ModeMark, { MODE_FRAME } from "./ModeMark";
import PaperCoverage, { type Coverage } from "./PaperCoverage";

/**
 * The QQQ intraday momentum paper book (backend app/engine/intraday_momentum_book.py): the rule and settings that passed
 * their registered exam (research/notes/qqq-intraday-momentum-2026-11-14.md), recorded live at 1x before any money. Each
 * hour from 10:00 it goes long above the noise band and VWAP, short below, stops on the band or VWAP, and is flat by
 * 15:59. This section shows what it holds now, the recorded days and the running result beside the exam. Read-only.
 */

type Trade = { side: number; entry_at: number; entry: number; exit_at: number | null; exit: number | null; how: string | null;
  entry_source?: string | null; exit_source?: string | null };
/** ``backup``: a check or fill that day used Alpaca because Tradier failed. */
type Day = { day: string; bp: number; dollars: number; trades: Trade[]; backup?: boolean };
export type MomentumBook = { enabled: boolean; symbol: string; stake: number; now: number; backtest: { mean_bp: number; years: string };
  holding: { side: number; entry_at: number; entry: number; entry_source?: string | null } | null; days: Day[];
  coverage?: Coverage | null;
  totals: { days: number; days_traded: number; mean_bp: number | null; dollars: number | null; up: number; missed_checks: number } };

const LABEL = "text-[11px] font-medium uppercase tracking-wide text-muted-foreground";
const SHOWN = 5;

const bp = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n).toFixed(1)} bp`;
const usd = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : ""}$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const tone = (n: number | null) => n == null || n === 0 ? "text-muted-foreground" : n > 0 ? "text-emerald-300" : "text-rose-300";
const date = (day: string) => new Date(`${day}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric" });
const time = (epoch: number) => new Date(epoch * 1000).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });
const nyDay = (epoch: number) => new Date(epoch * 1000).toLocaleDateString("en-CA", { timeZone: "America/New_York" });
const sameDay = (a: number, b: number) => nyDay(a) === nyDay(b);
const word = (side: number) => side > 0 ? "Long" : "Short";

/** The momentum book: read on mount and on the desk's shared minute (joining its one request) while the desk is on. */
export function useMomentumBook(on: boolean): { book: MomentumBook | null; failed: boolean } {
  const [book, setBook] = useState<MomentumBook | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!on) return;
    const controller = new AbortController();
    const load = () => deskGet("/copilot/desk/momentum", controller.signal)
      // Read the body even when refused: an unread one keeps the request open (and the page never idle).
      .then(async r => { const body = await r.json().catch(() => null); if (!r.ok || !body) throw new Error(String(r.status)); setBook(body); setFailed(false); })
      .catch(() => { if (!controller.signal.aborted) setFailed(true); });
    load();
    const stop = everyDeskMinute(load);
    return () => { controller.abort(); stop(); };
  }, [on]);
  return { book, failed };
}

/** Whether the momentum book has anything to show: nothing until it reads, nor before it is switched on with no record. */
export const momentumShown = ({ book, failed }: { book: MomentumBook | null; failed: boolean }) =>
  (!!book || failed) && !(book && !book.enabled && book.days.length === 0 && !book.holding);

/** The momentum book's full section (the desk's Practice block opens it in place). */
export default function DeskMomentum({ book, failed }: { book: MomentumBook | null; failed: boolean }) {
  if (!momentumShown({ book, failed })) return null;
  const t = book?.totals;
  return (
    <section data-testid="desk-momentum" aria-label="QQQ intraday momentum paper book" className={cn("rounded-md px-3 py-2", MODE_FRAME.paper)}>
      <p className="flex flex-wrap items-center gap-2"><span className={LABEL}>QQQ intraday momentum</span><ModeMark mode="paper" /></p>
      {failed || !book ? (
        <p data-testid="desk-momentum-failed" className="mt-1 text-xs text-muted-foreground">Could not read the momentum book; it reads again in a minute.</p>
      ) : (
        <>
          <p data-testid="desk-momentum-state" className="mt-1 text-sm">
            {book.holding
              ? <>{word(book.holding.side)} since {sameDay(book.holding.entry_at, book.now) ? "" : `${date(nyDay(book.holding.entry_at))} `}{time(book.holding.entry_at)} at {book.holding.entry.toFixed(2)}{book.holding.entry_source && book.holding.entry_source !== "tradier" ? " (Alpaca backup)" : ""}. {sameDay(book.holding.entry_at, book.now) ? "Checks on the hour; flat by 3:59 PM." : "Left open by an outage; it closes at the next open."}</>
              : <>Flat. Checks QQQ on the hour from 10:00{book.enabled ? "" : " once switched on"}.</>}
          </p>
          {t && t.days > 0 && (
            <p data-testid="desk-momentum-totals" className="mt-1 text-xs text-muted-foreground tabular-nums">
              {t.days} {t.days === 1 ? "day" : "days"} ({t.days_traded} traded) · avg <span className={tone(t.mean_bp)}>{bp(t.mean_bp ?? 0)}</span>
              {" "}· <span className={tone(t.dollars)}>{usd(t.dollars ?? 0)}</span> on ${book.stake.toLocaleString("en-US")} · {t.up} up
            </p>
          )}
          {!!t?.missed_checks && <p className="mt-1 text-xs text-muted-foreground">{t.missed_checks} {t.missed_checks === 1 ? "check" : "checks"} marked missed by the recorder.</p>}
          <PaperCoverage coverage={book.coverage} unit="check" />
          <p className="mt-0.5 text-[11px] text-muted-foreground">Exam {book.backtest.years}: {bp(book.backtest.mean_bp)} a day at 1x; most days are flat or small losses.</p>
          {book.days.length > 0 && (
            <ul className="mt-1 space-y-0.5 text-xs tabular-nums">
              {book.days.slice(0, SHOWN).map(d => (
                <li key={d.day} className="flex flex-wrap justify-between gap-x-2">
                  <span className="min-w-0 truncate text-muted-foreground">
                    {date(d.day)}{d.trades.length === 0 ? " · no trade" : ` · ${d.trades.map(x => `${word(x.side).toLowerCase()} ${x.how ?? ""}`.trim()).join(", ")}`}
                  </span>
                  <span className="shrink-0 whitespace-nowrap"><span className={cn(tone(d.bp))}>{bp(d.bp)}</span> <span className={cn("ml-1", tone(d.dollars))}>{usd(d.dollars)}</span></span>
                  {d.backup && <span data-testid="desk-momentum-backup" className="basis-full pl-2 text-[11px] text-sky-300/80">Alpaca backup: Tradier failed</span>}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
