"use client";

import { useEffect, useState } from "react";
import { deskGet, everyDeskMinute } from "@/lib/deskMinute";
import type { DeskChartMark } from "@/lib/desk";

/**
 * The QQQ intraday momentum paper book's view of today on the desk chart (backend ``intraday_momentum_book.today_view``,
 * carried by ``GET /copilot/desk/momentum`` as ``today``): its noise band as two thin lines stepping at each hourly
 * check, the hours still ahead faint, and its paper entries and exits as small pale marks lettered M. Read only from the
 * book's own records; nothing when the book is off, has no check today, or the read fails (never an earlier read kept).
 */

export type MomentumToday = {
  day: string; until: number;
  checks: { minute: number; at: number; status: "done" | "missed"; price: number | null; upper: number | null; lower: number | null; vwap: number | null }[];
  ahead: { minute: number; at: number; upper: number; lower: number }[];
  trades: { side: number; entry_at: number; entry: number; exit_at: number | null; exit: number | null; how: string | null; bp: number | null }[];
};
/** One step of the band: its value from one check to the next (the last to the close); ``ahead`` for an hour not checked yet. */
export type BandStep = { from: number; to: number; upper: number; lower: number; ahead: boolean };

/** The band's steps: a done check holds until the next check (done, missed or ahead) or the close; a missed one draws nothing. */
export function bandSteps(today: MomentumToday): BandStep[] {
  const stamps = [
    ...today.checks.map(c => ({ at: c.at, upper: c.status === "done" ? c.upper : null, lower: c.status === "done" ? c.lower : null, ahead: false })),
    ...today.ahead.map(a => ({ at: a.at, upper: a.upper as number | null, lower: a.lower as number | null, ahead: true })),
  ].sort((a, b) => a.at - b.at);
  const out: BandStep[] = [];
  stamps.forEach((s, i) => {
    if (s.upper == null || s.lower == null) return;
    out.push({ from: s.at, to: stamps[i + 1]?.at ?? today.until, upper: s.upper, lower: s.lower, ahead: s.ahead });
  });
  return out;
}

/** The step holding ``at``, if any. */
export const bandAt = (steps: BandStep[], at: number) => steps.find(s => s.from <= at && at < s.to) ?? null;

const HOW: Record<string, string> = { stop: "stopped", close: "closed (3:59 PM)", "late close": "closed late" };
const bpText = (bp: number) => `${bp > 0 ? "+" : bp < 0 ? "−" : ""}${Math.abs(bp).toFixed(1)} bp`;

/** Today's paper entries and exits as chart marks: a long's entry a buy, its exit a sell (a short's the other way). */
export function bandMarks(today: MomentumToday): DeskChartMark[] {
  const out: DeskChartMark[] = [];
  for (const t of today.trades) {
    const word = t.side > 0 ? "Long" : "Short";
    out.push({ kind: "momentum", at: t.entry_at, price: t.entry, side: t.side > 0 ? "buy" : "sell", text: `${word} entry ${t.entry.toFixed(2)} (paper)` });
    if (t.exit_at != null && t.exit != null) {
      out.push({ kind: "momentum", at: t.exit_at, price: t.exit, side: t.side > 0 ? "sell" : "buy",
        text: `${word} ${HOW[t.how ?? ""] ?? "closed"} ${t.exit.toFixed(2)}${t.bp != null ? ` · ${bpText(t.bp)}` : ""} (paper)` });
    }
  }
  return out;
}

/** Today's view while ``active`` (QQQ on intraday candles), read on the desk's minute; null when off, empty or failed. */
export function useMomentumToday(active: boolean): MomentumToday | null {
  const [today, setToday] = useState<MomentumToday | null>(null);
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    const load = () => deskGet("/copilot/desk/momentum", controller.signal)
      // Read the body even when refused: an unread one keeps the request open (and the page never idle).
      .then(async r => {
        const body = await r.json().catch(() => null);
        if (!r.ok || !body) throw new Error(String(r.status));
        setToday(body.enabled && body.today?.checks?.length ? body.today : null);
      })
      .catch(() => { if (!controller.signal.aborted) setToday(null); }); // a failed read draws nothing, never the last one
    load();
    const stop = everyDeskMinute(load);
    return () => { controller.abort(); stop(); setToday(null); };
  }, [active]);
  return active ? today : null;
}
