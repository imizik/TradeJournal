"use client";

/**
 * The desk chart's one header row (docs/copilot-lab.md § The desk): the ticker, its last price and today's change, the
 * held contract, the Stock / Contract switch when it applies, the timeframes, then the chart's tools: "Studies · N" (a
 * menu of the study toggles), "Alerts · N" (the symbol's armed alerts), "Draw" (the pencil) and "More" (Replay, Tape,
 * Open in Charts, Reset). On a phone the studies and the pencil wait in More, so the row stays one line above the chart.
 *
 * A piece folded away on the desk (``DeskUse``: chart studies, Tape, Replay) is still one tap away in More, and counted:
 * its entry shows it for now, and Keep showing unfolds it.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { ChevronDown } from "lucide-react";
import { useAppAccess } from "@/components/AccessProvider";
import { useFolds } from "@/components/copilot/DeskUse";
import { PIECE } from "@/lib/deskUse";
import { DESK_TIMEFRAMES, type DeskTimeframe } from "@/lib/desk";
import { cn } from "@/lib/utils";

/** What the chart hands its header: its tools, built where their state lives (``DeskChart``). */
export type ChartTools = {
  /** "Studies · N": the menu of study toggles (a computer). */
  studies: ReactNode;
  /** The same toggles as a list, for the phone's More. */
  studyList: ReactNode;
  /** How many studies are on. */
  studiesOn: number;
  alerts: ReactNode;
  draw: ReactNode;
  /** The pencil, for the phone's More. */
  drawing: { on: boolean; disabled: boolean; toggle(): void };
  reset(): void;
  ready: boolean;
  /** A phone: the studies and the pencil wait in More. */
  narrow: boolean;
};

const BUTTON = "inline-flex min-h-11 items-center gap-1 whitespace-nowrap rounded border px-1.5 text-xs sm:min-h-0 sm:py-0.5";
export const headButton = (open: boolean) => cn(BUTTON, open ? "border-foreground/60 text-foreground" : "border-transparent text-muted-foreground hover:text-foreground");

/** A header button that opens a small menu under it; a tap outside or Escape closes it. */
export function ChartMenu({ label, title, testId, use, open, onOpen, align = "right", wide = false, chevron = true, children }: {
  label: ReactNode; title: string; testId: string; use?: string; open: boolean; onOpen(open: boolean): void;
  align?: "left" | "right"; wide?: boolean; chevron?: boolean; children: ReactNode;
}) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (event: Event) => { if (!box.current?.contains(event.target as Node)) onOpen(false); };
    const key = (event: KeyboardEvent) => { if (event.key === "Escape") { event.stopPropagation(); onOpen(false); } };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", key, true);
    return () => { document.removeEventListener("pointerdown", away); document.removeEventListener("keydown", key, true); };
  }, [open, onOpen]);
  return (
    <div ref={box} data-use={use} className="relative shrink-0">
      <button type="button" aria-expanded={open} aria-haspopup="true" data-testid={testId} title={title} onClick={() => onOpen(!open)} className={headButton(open)}>
        {label}{chevron && <ChevronDown size={12} aria-hidden />}
      </button>
      {open && (
        <div className={cn("absolute top-full z-[60] mt-1 max-h-[70svh] overflow-y-auto rounded-md border bg-popover p-1 text-xs shadow-lg", align === "right" ? "right-0" : "left-0",
          wide ? "w-[min(20rem,calc(100vw-2rem))]" : "min-w-52")}>
          {children}
        </div>
      )}
    </div>
  );
}

const ITEM = "flex min-h-11 w-full items-center rounded px-2 text-left text-foreground hover:bg-secondary sm:min-h-8";

/** One More entry for a piece that can fold: as usual when shown, else its name with "folded" and Keep showing. */
function FoldItem({ id, onOpen, children }: { id: string; onOpen(): void; children: ReactNode }) {
  const folds = useFolds();
  if (!folds.folded(id)) return <>{children}</>;
  const hidden = folds.hidden(id);
  return (
    <div className="flex items-center gap-2 rounded px-0.5" data-testid={`chart-more-folded-${id}`}>
      {hidden
        ? <button type="button" data-use={id} onClick={() => { folds.showNow(id); onOpen(); }} className={cn(ITEM, "flex-1")}>{PIECE.get(id)?.label ?? id}</button>
        : <div className="min-w-0 flex-1">{children}</div>}
      <span className="shrink-0 text-muted-foreground">{hidden ? "folded" : "for now"}</span>
      <button type="button" onClick={() => void folds.setFolded([id], false)} className="min-h-11 shrink-0 px-1 text-muted-foreground underline underline-offset-2 hover:text-foreground sm:min-h-8">Keep showing</button>
    </div>
  );
}

/**
 * The header row. ``reading`` is the price and today's change; ``held`` the held contract; ``view`` the Stock / Contract
 * switch; ``tools`` null while a held option's own chart is shown (no studies, alerts or drawing there).
 */
export function ChartHead({ symbol, reading, held, view, timeframe, onTimeframe, tools, onReplay, tape, onTape, charts }: {
  symbol: string; reading: ReactNode; held: string | null; view: ReactNode; timeframe: DeskTimeframe | null; onTimeframe(next: DeskTimeframe): void;
  tools: ChartTools | null; onReplay?(): void; tape: boolean; onTape(next: boolean): void; charts: string;
}) {
  const folds = useFolds();
  const { owner } = useAppAccess();
  const [more, setMore] = useState(false);
  const [studies, setStudies] = useState(false);
  const narrow = tools?.narrow ?? false;
  const studiesShown = !folds.hidden("chart.studies");
  const close = () => setMore(false);
  return (
    // One row on a computer (the held contract gives way first); on a phone the ticker and its price sit over the controls.
    <div data-testid="desk-chart-head" className="flex flex-wrap items-center gap-x-1.5 gap-y-1 sm:flex-nowrap">
      <span className="flex min-w-0 items-baseline gap-x-2 max-sm:w-full">
        <span data-testid="desk-chart-symbol" className="text-base font-semibold leading-5 text-foreground">{symbol}</span>
        {reading}
        {held && <span data-testid="desk-chart-held" className="min-w-0 truncate text-xs text-muted-foreground max-sm:hidden">{held}</span>}
      </span>
      {view}
      {timeframe && <div role="group" aria-label="Timeframe" className="flex shrink-0 gap-0.5">
        {DESK_TIMEFRAMES.map(item => (
          <button key={item} type="button" aria-pressed={timeframe === item} onClick={() => onTimeframe(item)}
            className={cn("min-h-11 min-w-11 rounded border px-2 text-xs tabular-nums sm:min-h-0 sm:min-w-0 sm:py-0.5",
              timeframe === item ? "border-foreground/60 text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
            {item}
          </button>
        ))}
      </div>}
      <span className="ml-auto flex shrink-0 items-center gap-0.5">
        {tools && !narrow && studiesShown && (
          <ChartMenu label={<>Studies<span className="tabular-nums"> · {tools.studiesOn}</span></>} title="Studies: show or hide each, with its value at the crosshair"
            testId="desk-studies-open" use="chart.studies" open={studies} onOpen={setStudies} wide chevron={false}>
            {tools.studies}
          </ChartMenu>
        )}
        {tools?.alerts}
        {tools && !narrow && tools.draw}
        <ChartMenu label="More" title="Replay, Tape, Open in Charts, Reset" testId="desk-chart-more" open={more} onOpen={setMore}>
          <div role="group" aria-label="More chart tools" className="flex flex-col">
            {tools && narrow && (
              <FoldItem id="chart.studies" onOpen={() => undefined}>
                <div className="border-b pb-1">
                  <p className="px-2 pb-0.5 pt-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Studies · {tools.studiesOn}</p>
                  {tools.studyList}
                </div>
              </FoldItem>
            )}
            {tools && !narrow && folds.folded("chart.studies") && (
              <FoldItem id="chart.studies" onOpen={() => { setMore(false); setStudies(true); }}>
                <button type="button" data-use="chart.studies" onClick={() => { setMore(false); setStudies(true); }} className={ITEM}>Studies · {tools.studiesOn}</button>
              </FoldItem>
            )}
            {tools && narrow && (
              <button type="button" aria-pressed={tools.drawing.on} disabled={tools.drawing.disabled} data-testid="desk-draw-toggle"
                aria-label={tools.drawing.on ? "Done drawing" : "Draw on the chart"} onClick={() => { close(); tools.drawing.toggle(); }}
                className={cn(ITEM, "disabled:opacity-40")}>{tools.drawing.on ? "Done drawing" : "Draw a line"}</button>
            )}
            {onReplay && (
              <FoldItem id="chart.replay" onOpen={() => { close(); onReplay(); }}>
                <button type="button" data-testid="replay-open" data-use="chart.replay" onClick={() => { close(); onReplay(); }}
                  title="Paper trade a past day, any time: the day replays bar by bar" className={cn(ITEM, "text-violet-200/90")}>Replay a past day</button>
              </FoldItem>
            )}
            {owner && (
              <FoldItem id="chart.tape" onOpen={() => { close(); onTape(true); }}>
                <button type="button" aria-pressed={tape} data-testid="tape-toggle" data-use="chart.tape" title="Level 2 and time & sales"
                  onClick={() => { close(); onTape(!tape); }} className={ITEM}>{tape ? "Hide Tape" : "Tape"}<span className="ml-1 text-muted-foreground">Level 2 · time &amp; sales</span></button>
              </FoldItem>
            )}
            <Link href={charts} onClick={close} className={ITEM}>Open in Charts →</Link>
            {tools && <button type="button" onClick={() => { close(); tools.reset(); }} disabled={!tools.ready} className={cn(ITEM, "disabled:opacity-40")}>Reset</button>}
          </div>
        </ChartMenu>
      </span>
    </div>
  );
}
