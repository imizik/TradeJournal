"use client";

/**
 * The desk's mode (docs/copilot-lab.md § Real, paper and replay): Real, Paper or Replay, one switch in the top bar. It is
 * a view only: nothing is sent, and no order, account or book behaves differently.
 *
 * - Real: the desk as it always was.
 * - Paper: paper comes first without hiding real money. The centre wears the dashed PAPER frame, a ticket's main action
 *   is Buy on paper, the top bar shows the paper book's value beside the real accounts, each with its mark.
 * - Replay: Replay a past day (``DeskReplay``), however it opened (R, ⌘K, the copilot, Practice). Its own header carries
 *   the same switch, so one tap comes back to Real or Paper.
 *
 * Real or Paper is kept for this browser, as the desk's other choices are; a reload never opens in Replay.
 */

import { useSyncExternalStore } from "react";
import { paperSymbols, paperValue, type PaperBook } from "@/lib/paperBook";
import { useDeskTicks } from "@/lib/deskTicks";
import { cn } from "@/lib/utils";
import ModeMark, { MODE_CHIP, type Mode } from "./ModeMark";

const KEY = "desk.mode.v1";
export type ViewMode = Exclude<Mode, "replay">;

let kept: ViewMode | null = null;
const listeners = new Set<() => void>();
function read(): ViewMode {
  if (kept === null) {
    try { kept = window.localStorage.getItem(KEY) === "paper" ? "paper" : "real"; } catch { kept = "real"; }
  }
  return kept;
}
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; };

/** Real or Paper: the desk's view, kept for this browser. */
export const useDeskMode = (): ViewMode => useSyncExternalStore(subscribe, read, () => "real");

export function setDeskMode(next: ViewMode) {
  kept = next;
  try { window.localStorage.setItem(KEY, next); } catch { /* this visit only */ }
  for (const listener of listeners) listener();
}

const MODES: readonly { id: Mode; word: string; hint: string }[] = [
  { id: "real", word: "Real", hint: "Real: your accounts, as the desk always shows them" },
  { id: "paper", word: "Paper", hint: "Paper first: a ticket's main button is Buy on paper, the paper value beside the real. Nothing is sent; your real book stays." },
  { id: "replay", word: "Replay", hint: "Replay a past day ( R ). Not live, not real money." },
];

/** The three-way switch, each segment in its mark's look when picked. ``onPick`` gets the segment tapped (never the one
 * already picked). */
export function ModeSwitch({ mode, onPick, className }: { mode: Mode; onPick(next: Mode): void; className?: string }) {
  return (
    <div role="radiogroup" aria-label="Desk mode" data-testid="mode-switch" data-mode={mode}
      className={cn("inline-flex shrink-0 items-center gap-0.5 rounded-md border p-0.5", className)}>
      {MODES.map(({ id, word, hint }) => {
        const on = mode === id;
        return (
          <button key={id} type="button" role="radio" aria-checked={on} data-testid={`mode-${id}`} title={hint}
            onClick={() => { if (!on) onPick(id); }}
            className={cn("inline-flex min-h-9 items-center rounded px-2 text-[11px] font-semibold uppercase tracking-wide sm:min-h-6 sm:px-1.5",
              on ? MODE_CHIP[id] : "border border-transparent text-muted-foreground hover:bg-secondary hover:text-foreground")}>
            {word}
          </button>
        );
      })}
    </div>
  );
}

const usd = (n: number) => `$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const signed = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : ""}${usd(n)}`;

/** The paper book's value in Paper mode, with its mark: beside the real accounts in the top bar, under the switch on a
 * phone. Its prices are the ones the Practice block already asks for (no read of its own). A tap opens the paper book. */
export function PaperValue({ book, failed, onOpen, className }: { book: PaperBook | null; failed: boolean; onOpen(): void; className?: string }) {
  const ticks = useDeskTicks(paperSymbols(book?.positions));
  const value = book?.run && book.account ? paperValue(book, ticks) : null;
  const pnl = value && book?.run ? Math.round((value.value - book.run.starting_cash) * 100) / 100 : null;
  return (
    <button type="button" onClick={onOpen} data-testid="desk-paper-value" title="Your paper book: positions, orders and score. Not real money. ( P )"
      className={cn("inline-flex min-h-11 shrink-0 items-baseline gap-1.5 whitespace-nowrap rounded-md border border-dashed border-violet-400/50 px-2 py-1 text-xs hover:bg-secondary sm:min-h-0 sm:py-0.5", className)}>
      <ModeMark mode="paper" short className="self-center" />
      {!book ? <span className="text-muted-foreground">{failed ? "could not be read" : "reading…"}</span>
        : !book.run ? <span className="text-muted-foreground">not started</span>
        : value ? <>
          <span data-testid="paper-value-total" className={cn("tabular-nums text-foreground", value.stale && "opacity-60")}>{usd(value.value)}</span>
          {pnl !== null && <span className={cn("tabular-nums", pnl > 0 ? "text-emerald-300" : pnl < 0 ? "text-rose-300" : "text-muted-foreground")}>{signed(pnl)}</span>}
        </> : <span className="text-muted-foreground">needs a live price</span>}
    </button>
  );
}
