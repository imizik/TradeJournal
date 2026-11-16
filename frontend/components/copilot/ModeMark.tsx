import { cn } from "@/lib/utils";

/**
 * The one mark that says whose money a ticket, book or figure is (docs/copilot-lab.md § Real, paper and replay), drawn
 * the same everywhere and read by shape and word, never by colour alone; violet is paper and replay only (amber means "needs you"):
 * - REAL: a solid light chip, with the account when known ("Real · Roth IRA ••8267"); its card has a solid left edge.
 * - PAPER: a dashed violet chip, "Paper · not real money" unless ``short``; its card has a dashed violet frame.
 * - REPLAY: a filled violet chip with the replayed day ("Replay · Fri, Nov 13").
 * The word is written in sentence case and shown in capitals, so text reads "Paper +$40.50" to tests and screen readers.
 */

export type Mode = "real" | "paper" | "replay";

const WORD: Record<Mode, string> = { real: "Real", paper: "Paper", replay: "Replay" };
/** Each mode's chip: the mark's own look, and the picked segment of the desk's mode switch (`DeskMode.tsx`). */
export const MODE_CHIP: Record<Mode, string> = {
  real: "border border-foreground/60 bg-foreground/10 text-foreground",
  paper: "border border-dashed border-violet-400/70 text-violet-200",
  replay: "border border-violet-400 bg-violet-400 text-black",
};

/** The frame of a card that holds one mode's money: REAL a solid left edge, PAPER and REPLAY a dashed violet border. */
export const MODE_FRAME: Record<Mode, string> = {
  real: "border-l-2 border-l-foreground/60 pl-3",
  paper: "border border-dashed border-violet-400/40",
  replay: "border border-dashed border-violet-400/40",
};

/** "Fri, Nov 13" for a calendar date (read in UTC so the day never shifts). */
export const modeDay = (day: string) => new Date(`${day}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", weekday: "short", month: "short", day: "numeric" });

export default function ModeMark({ mode, detail, short = false, className }: {
  mode: Mode;
  /** REAL: the account ("Roth IRA ••8267"); REPLAY: the day; PAPER: replaces "not real money". */
  detail?: string | null;
  /** PAPER only: the word alone, for a column head or a figure beside its REAL twin. */
  short?: boolean;
  className?: string;
}) {
  const extra = mode === "paper" && !short ? detail ?? "not real money" : detail;
  return (
    <span data-testid="mode-mark" data-mode={mode}
      className={cn("inline-flex shrink-0 items-center whitespace-nowrap rounded px-1 text-[10px] font-semibold uppercase leading-4 tracking-wide", MODE_CHIP[mode], className)}>
      {WORD[mode]}{extra && <span className="font-medium normal-case tracking-normal"> · {extra}</span>}
    </span>
  );
}

/** The first line of every real ticket: REAL, the account, and that he places it himself. */
export function RealTicketLine({ account }: { account: string | null | undefined }) {
  return (
    <p data-testid="ticket-real" className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
      <ModeMark mode="real" detail={account || null} />
      <span>you place it in Robinhood · nothing is sent</span>
    </p>
  );
}

/** A ticket's paper half: below a dashed divider, apart from the real order's buttons, with its own PAPER mark. (In the
 * desk's Paper mode the ticket's main action is paper instead, with no half: ``DeskTicket``'s ``PaperMain``.) */
export function PaperHalf({ children }: { children: React.ReactNode }) {
  return (
    <div role="group" aria-label="Paper, not real money" data-testid="ticket-paper" className="space-y-2 border-t border-dashed border-violet-400/40 pt-3">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <ModeMark mode="paper" />
        <span>practise the same order with no money</span>
      </p>
      {children}
    </div>
  );
}
