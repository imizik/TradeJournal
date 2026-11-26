"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { api, type DecisionRecord } from "@/lib/api";
import { useDeskTicks } from "@/lib/deskTicks";
import { paperPnl, paperSymbols, type PaperBook, type PaperStats } from "@/lib/paperBook";
import DeskMomentum, { momentumShown, useMomentumBook } from "./DeskMomentum";
import DeskOvernight, { overnightShown, useOvernightBook } from "./DeskOvernight";
import DeskPaper from "./DeskPaper";
import DeskProving, { provingWords, useProvingGround } from "./DeskProving";
import { ReplayPractice, useReplayPractice } from "./DeskReplay";
import { GoalsLine } from "./DeskGoals";
import { RulesEditor, RulesSplitLine } from "./DeskRules";
import { Fold } from "./DeskUse";
import ModeMark, { type Mode } from "./ModeMark";
import WhatsWorking from "./WhatsWorking";
import PersonalReplay from "@/components/PersonalReplay";
import PracticeDecisions from "@/components/PracticeDecisions";
import PracticeRoutine from "@/components/PracticeRoutine";
import ScalpShortlistPanel from "@/components/ScalpShortlistPanel";

/**
 * The lower half of the desk's left column (docs/copilot-lab.md § The desk), under the book, Watching and the day's block:
 * - **My rules and goals** (``RulesAndGoals``): one neutral line ("4 rules · followed on 3 of 5 trades · goals 1 of 2
 *   this week ▸"), outside any paper frame because rules and goals cover real trades too. It opens in place to the
 *   followed / broken split, the rules editor and the goals line with its editor.
 * - **Practice** (``Practice``): one block with a line each for his paper book, the QQQ overnight and momentum paper
 *   books and Replay, each with its mark and figure; a line opens in place to its full section. The paper line is open
 *   whenever a paper position or working paper order exists (unless he closed it), so open paper risk is never folded
 *   out of sight. What is open is kept for this browser tab (``sessionStorage``).
 * ⌘K and the desk's keys open a line with ``openDeskPlace``. Nothing here reads anything the sections did not already read.
 */

const LABEL = "text-[11px] font-medium uppercase tracking-wide text-muted-foreground";
const KEPT = "desk.practice.v1";
const OPEN_EVENT = "desk-open-place";

/** A place under the book: a Practice line, or the rules-and-goals line. */
export type DeskPlace = "paper" | "overnight" | "momentum" | "replay" | "daily" | "saved-decisions" | "scalp" | "decision-replay" | "rules";
/** Opens a place in place (⌘K, a desk key); the caller scrolls to it once it shows. */
export const openDeskPlace = (place: DeskPlace) => window.dispatchEvent(new CustomEvent<DeskPlace>(OPEN_EVENT, { detail: place }));
function useOpenPlace(open: (place: DeskPlace) => void) {
  useEffect(() => {
    const on = (event: Event) => open((event as CustomEvent<DeskPlace>).detail);
    window.addEventListener(OPEN_EVENT, on);
    return () => window.removeEventListener(OPEN_EVENT, on);
  }, [open]);
}

const usd = (n: number) => `$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const signed = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : ""}${usd(n)}`;
const bp = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n).toFixed(1)} bp`;
const tone = (n: number | null | undefined) => n == null || n === 0 ? "text-muted-foreground" : n > 0 ? "text-emerald-300" : "text-rose-300";
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

// ------------------------------------------------------------------------------------------------ how I'm doing

/** "How I'm doing · this week": his closed REAL and PAPER trades since Monday, side by side (trades, P&L, win rate), in
 *  one neutral block outside the paper frame. From the paper read's ``score.week``; nothing until it lands. Replay keeps
 *  its own score in its REPLAY line. Folds like the column's other pieces (``scorecard``). Its foot opens What's working
 *  in place (``WhatsWorking``). */
export function HowImDoing({ book }: { book: PaperBook | null }) {
  const week = book?.score?.week;
  if (!week) return null;
  const sides: [Mode, PaperStats][] = [["real", week.real], ["paper", week.paper]];
  const rows: [string, (s: PaperStats) => ReactNode][] = [
    ["Trades", s => s.trades],
    ["P&L", s => s.trades === 0 ? "—" : <span className={tone(s.pnl)}>{signed(s.pnl)}</span>],
    ["Win rate", s => s.win_rate == null ? "—" : `${s.win_rate}%`],
  ];
  return (
    <section aria-label="How I'm doing this week" data-testid="desk-scorecard" className="rounded-lg border bg-card px-3 pb-2 pt-2"
      title={`Closed trades since Monday ${week.monday.slice(5).replace("-", "/")} (New York): real beside paper`}>
      <h2 className={LABEL}>How I&apos;m doing<span className="font-normal normal-case tracking-normal"> · this week</span></h2>
      <table className="mt-1 w-full text-xs tabular-nums">
        <thead>
          <tr>
            <th className="w-1/3 text-left font-normal"><span className="sr-only">Closed this week</span></th>
            {sides.map(([mode]) => <th key={mode} scope="col" className="py-0.5 text-right font-normal"><ModeMark mode={mode} short /></th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map(([name, cell]) => (
            <tr key={name} className="border-t border-border/50">
              <th scope="row" className="py-0.5 text-left font-normal text-muted-foreground">{name}</th>
              {sides.map(([mode, s]) => <td key={mode} data-testid={`scorecard-${mode}`} className="text-right text-foreground/90">{cell(s)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      {/* Where the money comes from and where it leaks, real beside paper: opens in place (and from ⌘K). */}
      <WhatsWorking />
    </section>
  );
}

// ------------------------------------------------------------------------------------------------ rules and goals

/** "4 rules · followed on 3 of 5 trades · goals 1 of 2 this week ▸", opening in place. Nothing until the paper read lands
 *  (it carries his rules, the split and his goals). */
export function RulesAndGoals({ book }: { book: PaperBook | null }) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  useOpenPlace(useCallback((place: DeskPlace) => { if (place === "rules") setOpen(true); }, []));
  if (!book) return null;
  const rules = book.my_rules ?? [];
  const splits = [book.score?.paper.rules, book.score?.real_rules].flatMap(s => s ? [s] : []);
  const followed = splits.reduce((n, s) => n + s.followed.trades, 0);
  const judged = splits.reduce((n, s) => n + s.followed.trades + s.broken.trades + s.unclear.trades, 0);
  const goals = book.goals;
  const met = goals?.progress.filter(p => !p.stale && p.ok === true).length ?? 0;
  const week = goals?.label ? goals.label.toLowerCase() : "this week";
  const parts = [
    rules.length ? `My ${plural(rules.length, "rule")}` : "No rules written yet",
    judged ? `followed on ${followed} of ${plural(judged, "trade")}` : null,
    goals ? (goals.goals.length ? `goals ${met} of ${goals.goals.length} ${week}` : `no goals ${week}`) : null,
  ].filter(Boolean);
  return (
    <section aria-label="My rules and goals" data-testid="rules-goals" data-use="paper.rules" className="rounded-lg border bg-card">
      <button type="button" aria-expanded={open} data-testid="rules-goals-toggle" onClick={() => setOpen(o => !o)} title="Your own trading rules and this week's goals: real trades and paper"
        className="flex min-h-11 w-full items-center gap-2 rounded-lg px-3 py-1.5 text-left text-xs hover:bg-secondary sm:min-h-8">
        <span data-testid="rules-goals-line" className="min-w-0 flex-1 text-foreground/90">{parts.join(" · ")}</span>
        <span aria-hidden className="text-muted-foreground">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div className="space-y-1 border-t pb-2 pt-1">
          <RulesSplitLine paper={book.score?.paper.rules} real={book.score?.real_rules} />
          <p className="flex flex-wrap items-baseline gap-x-2 px-3 pt-0.5 text-[11px] text-muted-foreground">
            <button type="button" aria-expanded={editing} data-testid="rules-toggle" onClick={() => setEditing(e => !e)}
              className="inline-flex min-h-11 items-center text-xs text-foreground underline-offset-2 hover:underline sm:min-h-0">
              {rules.length ? `Edit my rules (${rules.length})` : "Write my rules"}</button>
            <span>checked at each entry, real and paper; breaking one never blocks an order</span>
          </p>
          {editing && <RulesEditor rules={rules} onDone={() => setEditing(false)} />}
          <GoalsLine goals={goals} />
        </div>
      )}
    </section>
  );
}

// ------------------------------------------------------------------------------------------------ practice

type Kept = Partial<Record<string, boolean>>;

/** Which lines are open, kept for this browser tab. */
function useKeptOpen(): [Kept, (key: string, open: boolean) => void, (keys: string[]) => void] {
  const [kept, setKept] = useState<Kept>({});
  useEffect(() => {
    try { setKept(JSON.parse(window.sessionStorage.getItem(KEPT) ?? "{}")); } catch { /* all closed */ } // eslint-disable-line react-hooks/set-state-in-effect -- the store is read after hydration
  }, []);
  const write = useCallback((change: Kept) => setKept(prev => {
    const next = { ...prev, ...change };
    try { window.sessionStorage.setItem(KEPT, JSON.stringify(next)); } catch { /* this view only */ }
    return next;
  }), []);
  const set = useCallback((key: string, open: boolean) => write({ [key]: open }), [write]);
  const openAll = useCallback((keys: string[]) => write(Object.fromEntries(keys.map(k => [k, true]))), [write]);
  return [kept, set, openAll];
}

/** One Practice line: its mark, name and figure, opening its full section in place. ``toggle`` false: nothing to open. */
function Line({ id, mode, name, open, onToggle, extra, children, section }: {
  id: string; mode: Mode; name: string; open: boolean; onToggle?(): void; extra?: ReactNode; children: ReactNode; section: ReactNode;
}) {
  const body = (
    <>
      <ModeMark mode={mode} short />
      <span className="font-medium text-foreground">{name}</span>
      <span className="contents tabular-nums text-muted-foreground">{children}</span>
    </>
  );
  return (
    <div data-testid={`practice-${id}`} className="border-t">
      <div className="flex items-center">
        {onToggle ? (
          <button type="button" aria-expanded={open} data-testid={`practice-line-${id}`} onClick={onToggle}
            className="flex min-h-11 min-w-0 flex-1 flex-wrap items-center gap-x-1.5 gap-y-0.5 px-3 py-1.5 text-left text-xs hover:bg-secondary sm:min-h-8">
            {body}<span aria-hidden className="ml-auto pl-1 text-muted-foreground">{open ? "▾" : "▸"}</span>
          </button>
        ) : <p data-testid={`practice-line-${id}`} className="flex min-h-11 min-w-0 flex-1 flex-wrap items-center gap-x-1.5 gap-y-0.5 px-3 py-1.5 text-xs sm:min-h-8">{body}</p>}
        {extra}
      </div>
      {open && onToggle && <div className="px-2 pb-2">{section}</div>}
    </div>
  );
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function DeskPracticeDecisions({ focusId }: { focusId?: string }) {
  const [records, setRecords] = useState<DecisionRecord[] | null>(null);
  const [error, setError] = useState("");
  const [reloadNonce, setReloadNonce] = useState(0);

  useEffect(() => {
    let active = true;
    void api.decisions().then(async ({ decisions }) => {
      const next = [...decisions];
      if (focusId && UUID_RE.test(focusId) && !next.some((r) => r.id === focusId)) {
        const focused = await api.decision(focusId).catch(() => null);
        if (focused) next.unshift(focused);
      }
      if (!active) return;
      setRecords(next);
      setError("");
    }).catch((err) => {
      if (!active) return;
      setError(err instanceof Error ? err.message : "Could not load saved decisions.");
    });
    return () => { active = false; };
  }, [focusId, reloadNonce]);

  const onSaved = useCallback((record: DecisionRecord) => {
    setRecords((prev) => prev ? [record, ...prev.filter((r) => r.id !== record.id)] : [record]);
    setReloadNonce((n) => n + 1);
  }, []);

  if (error) {
    return (
      <div className="space-y-2 py-2 text-xs">
        <p role="alert" className="text-red-400">{error}</p>
        <button type="button" onClick={() => { setError(""); setReloadNonce((n) => n + 1); }} className="underline">Retry</button>
      </div>
    );
  }
  if (records === null) return <p role="status" className="py-2 text-xs text-muted-foreground">Loading saved decisions…</p>;
  return <PracticeDecisions records={records} focusId={focusId} onSaved={onSaved} />;
}

/**
 * The Practice block: Paper (his own paper book), QQQ overnight, QQQ momentum and Replay, plus Daily practice,
 * Saved decisions, 9:40 scalp shortlist and Decision replay lab, one line each. Each main line keeps its piece id
 * (``paper``, ``strategy.overnight``, ``strategy.momentum``, ``replay.practice``), so a piece he folded away is still
 * a slim stub here.
 */
export function Practice({ on, paper, symbol, review, onReplay, onPick, startOpen = false }: {
  /** A phone keeps the whole block under More already, so there it starts open. */
  startOpen?: boolean;
  on: boolean; paper: { book: PaperBook | null; failed: boolean }; symbol: string | null;
  /** The newest Friday paper review, at the top of the paper section. */
  review?: ReactNode;
  /** Opens Replay: paper trading on a past day. */
  onReplay(): void;
  /** Shows a paper position's ticker on the desk, with its Position panel under the chart. */
  onPick?(symbol: string): void;
}) {
  const searchParams = useSearchParams();
  const urlDecision = searchParams.get("decision") ?? undefined;
  const urlPracticeRun = searchParams.get("practice_run") ?? undefined;
  const [decisionFocus, setDecisionFocus] = useState<string | undefined>(urlDecision);
  const [practiceRunFocus, setPracticeRunFocus] = useState<string | undefined>(urlPracticeRun);
  const overnight = useOvernightBook(on);
  const momentum = useMomentumBook(on);
  const proving = useProvingGround(on);
  const replay = useReplayPractice();
  const [kept, set, openAll] = useKeptOpen();
  useEffect(() => {
    if (urlDecision) {
      setDecisionFocus(urlDecision); // eslint-disable-line react-hooks/set-state-in-effect -- preserve focus if CopilotLab updates query params
      set("saved-decisions", true);
    }
    if (urlPracticeRun) {
      setPracticeRunFocus(urlPracticeRun);
      set("daily", true);
    }
    if (window.location.hash === "#scalp-shortlist") {
      set("scalp", true);
      requestAnimationFrame(() => document.getElementById("scalp-shortlist")?.scrollIntoView({ block: "nearest" }));
    }
  }, [urlDecision, urlPracticeRun, set]);
  const book = paper.book;
  const positions = book?.positions ?? [];
  const orders = book?.orders ?? [];
  // Open paper risk: the paper line opens by itself, and his choice while risk is open is kept apart from his choice
  // while none is, so closing it on a quiet day never hides tomorrow's open position.
  const risk = positions.length > 0 || orders.length > 0;
  const paperKey = risk ? "paper.risk" : "paper";
  const isOpen = (key: string, fallback = false) => kept[key] ?? fallback;
  // The last position closed (or order canceled) while the line was open: it stays open, so the fill's result and the
  // section's own state stay on screen. Adjusted during render, so the section never unmounts in between.
  const [riskWas, setRiskWas] = useState(risk);
  if (riskWas !== risk) {
    setRiskWas(risk);
    if (riskWas && !risk && isOpen("paper.risk", true)) set("paper", true);
  }
  useOpenPlace(useCallback((place: DeskPlace) => {
    if (place === "paper") openAll(["practice", "paper", "paper.risk"]);
    else if (place !== "rules") openAll(["practice", place]);
  }, [openAll]));
  // On the laptop the whole block is one line until he opens it (November 27, 2026: it took more of the left column
  // than his real book). Open paper risk, a line he left open, or a link into one shows it without asking.
  const shown = kept.practice ?? (startOpen || risk || !!urlDecision || !!urlPracticeRun || Object.entries(kept).some(([key, open]) => key !== "practice" && open));
  const ticks = useDeskTicks(paperSymbols(book?.positions)); // the same prices the paper section asks for: no read of its own

  const pnls = positions.map(p => paperPnl(p, ticks)).filter(p => p !== null);
  const openPnl = pnls.length ? Math.round(pnls.reduce((sum, p) => sum + p.pnl, 0) * 100) / 100 : null;
  const paperWords = !book ? <span>· {paper.failed ? "could not be read" : "reading…"}</span>
    : !book.run ? <span>· not started</span> : <>
      <span>· {positions.length ? `${positions.length} open` : orders.length ? "nothing open" : "nothing open or working"}</span>
      {orders.length > 0 && <span>· {orders.length} working</span>}
      {positions.length > 0 && openPnl !== null && <span data-testid="practice-paper-pnl" className={pnls.some(p => p.stale) ? "text-muted-foreground" : tone(openPnl)}>{signed(openPnl)}</span>}
      {/* A position with no price yet is left out of that sum, and the line says so rather than passing it as the total. */}
      {positions.length > pnls.length && <span data-testid="practice-paper-unpriced">· {positions.length - pnls.length} not priced</span>}
      {positions.length === 0 && book.score && book.score.paper.trades > 0 && <span><span className={tone(book.score.paper.pnl)}>{signed(book.score.paper.pnl)}</span> closed</span>}
    </>;

  const night = overnight.book;
  const held = night?.nights.find(n => n.status === "open");
  const nights = night?.totals;
  const day = momentum.book;
  const days = day?.totals;
  const card = replay;
  const replayed = !!card && card.runs.length > 0;

  return (
    <section aria-label="Practice" data-testid="desk-practice" className="rounded-lg border bg-card">
      <h2 className={LABEL}>
        <button type="button" data-testid="practice-toggle" aria-expanded={shown} onClick={() => set("practice", !shown)}
          className="flex min-h-11 w-full items-center px-3 text-left uppercase tracking-wide hover:bg-secondary sm:min-h-8">
          Practice<span className="font-normal normal-case tracking-normal">&nbsp;· not real money</span>
          <span aria-hidden className="ml-auto pl-1">{shown ? "▾" : "▸"}</span>
        </button>
      </h2>
      {shown && <>
      <Fold id="paper">
        <Line id="paper" mode="paper" name="Mine" open={isOpen(paperKey, risk)} onToggle={() => set(paperKey, !isOpen(paperKey, risk))}
          section={<DeskPaper book={book} failed={paper.failed} symbol={symbol} top={review} onPick={onPick} />}>{paperWords}</Line>
      </Fold>
      <Fold id="strategy.overnight">
        {overnightShown(overnight) && (
          <Line id="overnight" mode="paper" name="QQQ overnight" open={isOpen("overnight")} onToggle={() => set("overnight", !isOpen("overnight"))}
            section={<DeskOvernight {...overnight} />}>
            {overnight.failed || !night ? <span>· could not be read</span> : <>
              <span>· {held ? "holding" : "flat"}</span>
              {nights && nights.closed > 0 && <span title={`average over ${plural(nights.closed, "night")}`}>· <span className={tone(nights.mean_bp)}>{bp(nights.mean_bp ?? 0)}</span> avg</span>}
              {!isOpen("overnight") && !!night.coverage?.missing && <span>· {plural(night.coverage.missing, "unrecorded window")}</span>}
              {!isOpen("overnight") && !!night.coverage?.unknown_days && <span>· calendar incomplete</span>}
            </>}
          </Line>
        )}
      </Fold>
      <Fold id="strategy.momentum">
        {momentumShown(momentum) && (
          <Line id="momentum" mode="paper" name="QQQ momentum" open={isOpen("momentum")} onToggle={() => set("momentum", !isOpen("momentum"))}
            section={<DeskMomentum {...momentum} />}>
            {momentum.failed || !day ? <span>· could not be read</span> : <>
              <span>· {day.holding ? (day.holding.side > 0 ? "long" : "short") : "flat"}</span>
              {days && days.days > 0 && <span title={`average over ${plural(days.days, "day")}`}>· <span className={tone(days.mean_bp)}>{bp(days.mean_bp ?? 0)}</span> avg</span>}
              {!isOpen("momentum") && !!day.coverage?.missing && <span>· {plural(day.coverage.missing, "unrecorded check")}</span>}
              {!isOpen("momentum") && !!day.coverage?.unknown_days && <span>· calendar incomplete</span>}
            </>}
          </Line>
        )}
      </Fold>
      <Line id="proving" mode="paper" name="Proving ground" open={isOpen("proving")} onToggle={() => set("proving", !isOpen("proving"))}
        section={<DeskProving {...proving} />}>
        <span data-testid="practice-proving-words">{provingWords(proving.ground, proving.failed)}</span>
      </Line>
      <Fold id="replay.practice">
        <Line id="replay" mode="replay" name={replayed ? plural(card!.score.trades, "trade") : "Past days"} open={isOpen("replay")}
          onToggle={replayed ? () => set("replay", !isOpen("replay")) : undefined} section={<ReplayPractice card={card} />}
          extra={<button type="button" data-testid="practice-replay-open" onClick={onReplay} title="Paper trade a past day, any time: the day replays bar by bar"
            className="inline-flex min-h-11 shrink-0 items-center px-3 text-xs text-violet-200/80 hover:text-violet-100 sm:min-h-8">Replay a day</button>}>
          {replayed ? <span className={tone(card!.score.pnl)}>{signed(card!.score.pnl)}</span> : <span>bar by bar, scored apart</span>}
        </Line>
      </Fold>
      <Line id="daily" mode="paper" name="Daily practice" open={isOpen("daily")} onToggle={() => set("daily", !isOpen("daily"))}
        section={<PracticeRoutine initialRunId={practiceRunFocus} />}>
        <span>· morning setups &amp; choices</span>
      </Line>
      <Line id="saved-decisions" mode="paper" name="Saved decisions" open={isOpen("saved-decisions")} onToggle={() => set("saved-decisions", !isOpen("saved-decisions"))}
        section={<DeskPracticeDecisions focusId={decisionFocus} />}>
        <span>· frozen choices &amp; paper plans</span>
      </Line>
      <Line id="scalp" mode="paper" name="9:40 scalp shortlist" open={isOpen("scalp")} onToggle={() => set("scalp", !isOpen("scalp"))}
        section={<div id="scalp-shortlist" className="scroll-mt-4"><ScalpShortlistPanel history embedded /></div>}>
        <span>· 20-session opening study &amp; rules</span>
      </Line>
      <Line id="decision-replay" mode="replay" name="Decision replay lab" open={isOpen("decision-replay")} onToggle={() => set("decision-replay", !isOpen("decision-replay"))}
        section={<PersonalReplay embedded />}>
        <span>· two frozen moments</span>
      </Line>
      </>}
    </section>
  );
}
