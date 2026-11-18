import { money } from "@/lib/format";
import { cn } from "@/lib/utils";
import ModeMark from "./ModeMark";

/**
 * One-line historical paper record for a kind of trade (intended for the real
 * order ticket, so the trader sees how similar paper trades have gone before
 * risking money). The real ticket shows it for the order's option type at this New York time (``usePaperRecord``).
 */

export type PaperRecord = {
  label: string;
  wins: number;
  losses: number;
  pnl: number;
  trades: number;
};

export type PaperRecordLineProps = {
  record: PaperRecord | null;
  minTrades?: number;
  className?: string;
};

function pnlTone(pnl: number, tooFew: boolean): string {
  const cents = Math.round(pnl * 100);
  if (tooFew || cents === 0 || !Number.isFinite(cents)) return "text-muted-foreground";
  return cents > 0 ? "text-emerald-300" : "text-rose-300";
}

export default function PaperRecordLine({
  record,
  minTrades = 5,
  className,
}: PaperRecordLineProps) {
  if (!record) return null;
  const tooFew = record.trades < minTrades;

  return (
    <p
      data-testid="paper-record-line"
      className={cn("text-xs tabular-nums text-muted-foreground", className)}
    >
      <ModeMark mode="paper" short />
      {" · "}
      <span>
        {record.label}: {record.wins}W {record.losses}L,{" "}
      </span>
      <span className={pnlTone(record.pnl, tooFew)}>
        {money(record.pnl, { signed: true })}
      </span>
      {tooFew && <span className="text-muted-foreground"> · too few to judge</span>}
    </p>
  );
}
