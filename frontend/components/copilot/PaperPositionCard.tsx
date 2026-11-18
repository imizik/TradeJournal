"use client";

/**
 * One open paper position on the Paper home (``DeskPaper``), Robinhood-style: what it is worth now, how many at what
 * average, today's change and the total return. Tapping it opens the order sheet. A price that is not live is grey with
 * its time; no price at all says so, never a zero.
 */

import type { ReactNode } from "react";
import { useDeskTicks } from "@/lib/deskTicks";
import { paperPnl, paperSymbols, type PaperPosition } from "@/lib/paperBook";
import { cn } from "@/lib/utils";
import ModeMark from "./ModeMark";

export type PaperPositionCardProps = {
  position: PaperPosition;
  /** Today's dollar change for this position, supplied by the caller (omitted when null or undefined). */
  todayChange?: number | null;
  /** A small tag after the label (whose idea it was). */
  tag?: ReactNode;
  /** Whether its order sheet is open (for the button's aria-expanded). */
  expanded?: boolean;
  onOpen?(): void;
  className?: string;
};

const usd = (n: number) =>
  `$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const signedUsd = (n: number) => {
  const body = usd(n);
  if (body === "$0.00") return body;
  return `${n > 0 ? "+" : "−"}${body}`;
};

const valueUsd = (n: number) => {
  const body = usd(n);
  if (body === "$0.00") return body;
  return n < 0 ? `−${body}` : body;
};

const signedPct = (n: number) => {
  const body = `${Math.abs(n).toFixed(1)}%`;
  if (body === "0.0%") return body;
  return `${n > 0 ? "+" : "−"}${body}`;
};

const avgPrice = (perShare: number) => {
  const abs = Math.abs(perShare);
  return `$${abs.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: abs < 1 && abs !== 0 ? 4 : 2,
  })}`;
};

const asOf = (epoch: number) => `${new Date(epoch * 1000).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" })} ET`;

const toneOf = (n: number | null | undefined) => {
  if (n == null || Math.abs(n) < 0.005) return "text-muted-foreground";
  return n > 0 ? "text-emerald-300" : "text-rose-300";
};

function unitWord(instrument: PaperPosition["instrument"], count: number): string {
  const plural = count !== 1;
  if (instrument === "stock") return plural ? "shares" : "share";
  if (instrument === "spread") return plural ? "spreads" : "spread";
  return plural ? "contracts" : "contract";
}

export default function PaperPositionCard({
  position,
  todayChange = null,
  tag = null,
  expanded,
  onOpen,
  className,
}: PaperPositionCardProps) {
  const ticks = useDeskTicks(paperSymbols([position]));
  const pnl = paperPnl(position, ticks);

  // A live mark requires live ticks on every leg within the freshness window.
  const hasLiveMark = !!pnl && pnl.live && !pnl.stale;
  const currentValue = pnl
    ? pnl.live
      ? Math.round((pnl.pnl - position.basis) * 100) / 100
      : position.mark?.value ?? Math.round((pnl.pnl - position.basis) * 100) / 100
    : null;

  const today = todayChange != null && Number.isFinite(todayChange) ? todayChange : null;
  const startValue = currentValue != null && today !== null ? currentValue - today : null;
  const todayPct =
    today !== null && startValue != null && startValue > 0
      ? Math.round((today / startValue) * 1000) / 10
      : null;

  const qtyText = `${position.remaining.toLocaleString("en-US")} ${unitWord(position.instrument, position.remaining)}`;

  const cardClass = cn(
    "flex min-h-11 w-full flex-col gap-1 rounded-lg border border-dashed border-violet-400/40 bg-card px-3 py-2.5 text-left tabular-nums",
    onOpen && "cursor-pointer transition-colors hover:bg-secondary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-400/70",
    className,
  );

  const body = (
    <>
      <span className="flex items-baseline justify-between gap-2">
        <span className="flex min-w-0 items-center gap-1.5">
          <ModeMark mode="paper" short />
          <span className="truncate text-sm font-semibold text-foreground">{position.label}</span>
          {tag}
        </span>
        <span
          data-testid="paper-position-value"
          className={cn(
            "shrink-0 text-sm font-semibold",
            currentValue != null && hasLiveMark ? "text-foreground" : "text-muted-foreground",
          )}
        >
          {currentValue != null ? valueUsd(currentValue) : "—"}
        </span>
      </span>

      <span className="flex items-baseline justify-between gap-2 text-xs">
        <span className="min-w-0 truncate text-muted-foreground">
          {qtyText} · Avg {avgPrice(position.per_share)}
        </span>
        {today !== null && (
          <span data-testid="paper-position-today" className="shrink-0">
            <span className={hasLiveMark ? toneOf(today) : "text-muted-foreground"}>
              {signedUsd(today)}
              {todayPct != null && ` (${signedPct(todayPct)})`}
            </span>{" "}
            <span className="text-[11px] text-muted-foreground">today</span>
          </span>
        )}
      </span>

      <span className="flex items-baseline justify-between gap-2 text-xs">
        <span className="text-[11px] text-muted-foreground">Total return</span>
        <span
          data-testid="paper-pnl"
          className={cn(
            "shrink-0",
            pnl && hasLiveMark ? toneOf(pnl.pnl) : "text-muted-foreground",
          )}
        >
          {pnl ? (
            <>
              {signedUsd(pnl.pnl)}
              {pnl.pct != null && ` (${signedPct(pnl.pct)})`}
              {!hasLiveMark && <span className="ml-1 text-[11px]">as of {asOf(pnl.at)}</span>}
            </>
          ) : position.awaiting_close ? "Expired: settles on the close once it is read" : (
            "no price yet"
          )}
        </span>
      </span>
    </>
  );

  if (onOpen) {
    return (
      <button type="button" data-testid="paper-position-card" aria-expanded={expanded} onClick={onOpen} className={cardClass}>
        {body}
      </button>
    );
  }

  return (
    <div data-testid="paper-position-card" className={cardClass}>
      {body}
    </div>
  );
}
