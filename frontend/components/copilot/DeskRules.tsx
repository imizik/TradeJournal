"use client";

import { useEffect, useState } from "react";
import { Check, CircleHelp, Minus, X } from "lucide-react";
import { orderKey } from "@/lib/paperBook";
import {
  CHECK_WORDS, MAX_RULES, answered, brokenCount, checkEntry, recordTicket, saveRules,
  type Rule, type RuleEntry, type RuleKind, type RuleResult, type RulesSplit,
} from "@/lib/tradingRules";
import { cn } from "@/lib/utils";

/**
 * His own trading rules on the desk (docs/copilot-lab.md § My rules): the short list he writes once (Paper › Rules), the
 * checklist beside Paper and beside the Ticket's Copy (automatic checks already ticked or crossed with the reason; his
 * tick-boxes to answer), and the followed-versus-broken line under the paper score. A broken rule never blocks an order:
 * it says so in one line and he can still go ahead.
 */

const INPUT = "min-h-11 rounded-md border bg-background px-2 text-sm sm:min-h-8 sm:text-xs";
const BUTTON = "inline-flex min-h-11 items-center rounded-md border px-3 text-xs font-medium hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-45 sm:min-h-8";
const QUIET = "inline-flex min-h-11 items-center rounded-md px-3 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8";
const usd = (n: number) => `$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const signed = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : ""}${usd(n)}`;
const tone = (n: number) => n === 0 ? "text-muted-foreground" : n > 0 ? "text-emerald-300" : "text-rose-300";

const MARK = {
  pass: { icon: Check, cls: "text-emerald-400", word: "followed" },
  fail: { icon: X, cls: "text-rose-400", word: "broken" },
  na: { icon: Minus, cls: "text-muted-foreground", word: "does not apply" },
  unknown: { icon: CircleHelp, cls: "text-amber-300", word: "can't check" },
  ask: { icon: CircleHelp, cls: "text-muted-foreground", word: "to answer" },
} as const;

/** The entry's checklist from the server, re-read (once, after a pause) when what it checks changes; never on a timer. */
function useChecklist(entry: RuleEntry | null): { results: RuleResult[] | null; failed: boolean } {
  const [results, setResults] = useState<RuleResult[] | null>(null);
  const [failed, setFailed] = useState(false);
  const shape = entry ? JSON.stringify(entry) : "";
  useEffect(() => {
    if (!shape) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      checkEntry(JSON.parse(shape), controller.signal)
        .then(r => { setResults(r.results); setFailed(false); })
        // A server without the rules route (404) has no rules to show; anything else says it could not check.
        .catch(e => { if (!controller.signal.aborted) { if (String(e?.message) === "404") setResults([]); else setFailed(true); } });
    }, 350);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [shape]);
  return { results, failed };
}

/** The checklist: each rule's mark and reason; a tick-box rule is his to tick. Nothing at all when he has no rules. */
export function RulesChecklist({ entry, ticked, onTick }: { entry: RuleEntry | null; ticked: Record<string, boolean>; onTick(id: string, on: boolean): void }) {
  const { results, failed } = useChecklist(entry);
  if (failed && !results) return <p className="text-[11px] text-muted-foreground">Your rules could not be checked just now.</p>;
  if (!results || results.length === 0) return null;
  const shown = answered(results, ticked);
  const broken = brokenCount(shown);
  return (
    <div data-testid="rules-checklist" className="space-y-1 rounded-md border border-border/70 px-2 py-1.5">
      <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Your rules
        {broken > 0 && <span data-testid="rules-broken" role="status" className="ml-1.5 font-normal normal-case tracking-normal text-amber-300">
          · breaks {broken} of {shown.length}. You can still go ahead.</span>}
      </p>
      <ul className="space-y-0.5">
        {shown.map(r => {
          if (r.kind === "tick") {
            return (
              <li key={r.id} data-testid="rules-row" data-status={r.status} className="text-xs">
                <label className="flex min-h-8 cursor-pointer items-center gap-2 sm:min-h-0">
                  <input type="checkbox" checked={!!ticked[r.id]} onChange={e => onTick(r.id, e.target.checked)} className="size-4 accent-emerald-500 sm:size-3.5" />
                  <span>{r.text}</span>
                </label>
              </li>
            );
          }
          const m = MARK[r.status];
          const Icon = m.icon;
          return (
            <li key={r.id} data-testid="rules-row" data-status={r.status} className="flex items-start gap-2 text-xs">
              <Icon size={14} aria-label={m.word} className={cn("mt-px shrink-0", m.cls)} />
              <span className="min-w-0"><span>{r.text}</span><span className={cn("ml-1 text-[11px]", r.status === "unknown" ? "text-amber-300/90" : "text-muted-foreground")}>{r.status === "unknown" && !/^Can't check/.test(r.reason) ? "Can't check: " : ""}{r.reason}</span></span>
            </li>
          );
        })}
      </ul>
      {shown.some(r => r.kind === "tick") && <p className="text-[11px] text-muted-foreground">Tick the ones this trade follows; unticked counts as not followed.</p>}
    </div>
  );
}

/** Beside the Ticket's Copy all: the checklist for the real order, kept with each copy (the only moment the app sees). */
export function RealRules({ investigationId, symbol, entry, children }: {
  investigationId: string; symbol: string; entry: RuleEntry; children(onCopy: () => void): React.ReactNode;
}) {
  const [ticked, setTicked] = useState<Record<string, boolean>>({});
  const [kept, setKept] = useState<string | null>(null);
  const onCopy = () => {
    recordTicket({ ...entry, investigation_id: investigationId, order_key: orderKey(), symbol, answers: ticked })
      .then(r => setKept(r.recorded ? `Checklist kept with this copy${r.outcome === "broken" ? " (a rule broken)" : ""}; it counts once the plan links to the fill.` : null))
      .catch(() => setKept("The checklist could not be kept with this copy."));
  };
  return (
    <>
      <RulesChecklist entry={entry} ticked={ticked} onTick={(id, on) => setTicked(t => ({ ...t, [id]: on }))} />
      {children(onCopy)}
      {kept && <p data-testid="rules-kept" className="text-[11px] text-muted-foreground">{kept}</p>}
    </>
  );
}

type Draft = { id?: string; text: string; kind: RuleKind | ""; n: string };

/** His list: up to eight lines in his own words, each with an automatic check or none (a tick-box). */
export function RulesEditor({ rules, onDone }: { rules: Rule[]; onDone(): void }) {
  const [drafts, setDrafts] = useState<Draft[]>(() => rules.length
    ? rules.map(r => ({ id: r.id, text: r.text, kind: r.check?.kind ?? "", n: r.check?.n != null ? String(r.check.n) : "" }))
    : [{ text: "", kind: "", n: "" }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (i: number, patch: Partial<Draft>) => setDrafts(d => d.map((x, j) => j === i ? { ...x, ...patch } : x));
  const save = async () => {
    setBusy(true); setError(null);
    try {
      await saveRules(drafts.map(d => ({ ...(d.id ? { id: d.id } : {}), text: d.text,
        check: d.kind ? { kind: d.kind, ...(CHECK_WORDS[d.kind].n ? { n: d.n.trim() ? Number(d.n) : null } : {})  /* a blank N is refused, never read as 0 */ } : null })) as Rule[]);
      onDone();
    } catch (e) { setError(e instanceof Error ? e.message : "Not saved."); } finally { setBusy(false); }
  };
  return (
    <div data-testid="rules-editor" className="space-y-2 border-t border-dashed border-amber-400/30 px-3 py-2">
      <p className="text-xs text-muted-foreground">Your trading rules, in your own words. Each can have one check the app makes for you; the rest are tick-boxes you answer at each entry. Breaking one never blocks an order.</p>
      <ol className="space-y-1.5">
        {drafts.map((d, i) => (
          <li key={i} data-testid="rules-editor-row" className="flex flex-wrap items-center gap-1.5">
            <input aria-label={`Rule ${i + 1}`} maxLength={140} value={d.text} placeholder={d.kind ? CHECK_WORDS[d.kind].words.replace("N", d.n || "N") : "e.g. Only A+ setups"}
              onChange={e => set(i, { text: e.target.value })} className={cn(INPUT, "min-w-0 flex-1 basis-56")} />
            <select aria-label={`Rule ${i + 1} check`} value={d.kind} onChange={e => set(i, { kind: e.target.value as RuleKind | "" })} className={cn(INPUT, "max-w-[14rem]")}>
              <option value="">Tick-box (I answer)</option>
              {(Object.keys(CHECK_WORDS) as RuleKind[]).map(k => <option key={k} value={k}>{CHECK_WORDS[k].words}</option>)}
            </select>
            {d.kind && CHECK_WORDS[d.kind].n && (
              <label className="flex items-center gap-1 text-xs text-muted-foreground">N
                <input aria-label={`Rule ${i + 1} N`} inputMode="decimal" value={d.n} onChange={e => set(i, { n: e.target.value.replace(/[^\d.]/g, "") })} className={cn(INPUT, "w-16 tabular-nums")} />
                {CHECK_WORDS[d.kind].unit}
              </label>
            )}
            <button type="button" aria-label={`Remove rule ${i + 1}`} onClick={() => setDrafts(x => x.filter((_, j) => j !== i))} className={cn(QUIET, "px-2")}><X size={13} aria-hidden /></button>
          </li>
        ))}
      </ol>
      <div className="flex flex-wrap items-center gap-2">
        {drafts.length < MAX_RULES && <button type="button" onClick={() => setDrafts(x => [...x, { text: "", kind: "", n: "" }])} className={QUIET}>Add a rule</button>}
        <button type="button" data-testid="rules-save" disabled={busy} onClick={save} className={cn(BUTTON, "ml-auto border-amber-400/70 text-amber-100")}>Save rules</button>
        <button type="button" onClick={onDone} className={QUIET}>Cancel</button>
      </div>
      {error && <p role="alert" className="text-xs text-amber-300">{error}</p>}
      <p className="text-[11px] text-muted-foreground">Size is checked against paper cash on paper, and on real orders against the account&apos;s value from the desk&apos;s account line when it has one today; otherwise it says it can&apos;t check.</p>
    </div>
  );
}

function Cell({ g }: { g: { trades: number; pnl: number; win_rate: number | null } }) {
  if (g.trades === 0) return <span className="text-muted-foreground">—</span>;
  return <span className="whitespace-nowrap"><span className={tone(g.pnl)}>{signed(g.pnl)}</span><span className="text-muted-foreground"> {g.win_rate}%/{g.trades}</span></span>;
}

/** One line under the score: closed trades with every rule followed versus any broken (P&L, win rate / trades); a tap
 *  opens the split per rule. The real side counts only copied tickets whose plan links to the closed trade. */
export function RulesSplitLine({ paper, real }: { paper?: RulesSplit; real?: RulesSplit | null }) {
  const [open, setOpen] = useState(false);
  const has = (s?: RulesSplit | null) => !!s && s.followed.trades + s.broken.trades + s.unclear.trades > 0;
  if (!has(paper) && !real?.checklists) return null;
  const side = (name: string, s: RulesSplit | null | undefined, extra?: string) => (
    <span>
      <span className={name === "Paper" ? "text-amber-200" : "text-muted-foreground"}>{name} </span>
      {has(s) ? <>
        <span className="text-muted-foreground">followed </span><Cell g={s!.followed} />
        <span className="text-muted-foreground"> · broken </span><Cell g={s!.broken} />
        {s!.unclear.trades > 0 && <span className="text-muted-foreground"> · {s!.unclear.trades} unclear</span>}
      </> : <span className="text-muted-foreground">no checked trade closed yet</span>}
      {extra && <span className="text-muted-foreground"> · {extra}</span>}
    </span>
  );
  const realExtra = real?.checklists ? [real.unmatched ? `${real.unmatched} copied, not matched to a fill` : "", real.open ? `${real.open} still open` : ""].filter(Boolean).join(", ") : "";
  const rows = (s: RulesSplit | null | undefined) => (s?.by_rule ?? []).filter(r => r.followed.trades + r.broken.trades > 0);
  return (
    <div data-testid="rules-split" className="px-3 pt-0.5 text-[11px] tabular-nums">
      <button type="button" aria-expanded={open} onClick={() => setOpen(o => !o)} title="Closed trades by whether your rules were followed at the entry; tap for each rule"
        className="flex flex-wrap gap-x-2.5 text-left hover:underline hover:decoration-dotted hover:underline-offset-2">
        <span className="text-muted-foreground">Your rules:</span>
        {has(paper) && side("Paper", paper)}
        {real?.checklists ? side("Real", real, realExtra) : null}
      </button>
      {open && (
        <ul data-testid="rules-by-rule" className="mt-1 space-y-1 border-t border-border/50 pt-1">
          {([["Paper", paper], ["Real", real]] as const).flatMap(([name, s]) => rows(s).map(r => (
            <li key={`${name}-${r.id}`} data-testid="rules-by-rule-row">
              <p><span className={name === "Paper" ? "text-amber-200" : "text-muted-foreground"}>{name}</span> {r.text}{!r.current && <span className="text-muted-foreground"> (removed)</span>}</p>
              <p className="flex flex-wrap gap-x-2"><span><span className="text-muted-foreground">followed </span><Cell g={r.followed} /></span>
                <span><span className="text-muted-foreground">broken </span><Cell g={r.broken} /></span></p>
            </li>
          )))}
        </ul>
      )}
    </div>
  );
}
