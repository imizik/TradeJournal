"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link2 } from "lucide-react";
import { hhmm } from "@/components/copilot/SessionTape";
import { fetchPlanLink, linkCapture, unlinkCapture, type LinkPlan, type PlanLinkPage } from "@/lib/captures";
import { fillsToLink, readNoPlan, saveNoPlan, type DeskThread } from "@/lib/desk";

/** How long a link can be undone here before the desk reads the list again (and the plan's thread picks up the position). */
export const UNDO_MS = 8_000;
/** The pass "N fills to link" started, kept for this tab: a fill opened by its symbol link remounts the desk. */
const PASS_KEY = "desk.linking.v1";
const BUTTON = "inline-flex min-h-11 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium disabled:opacity-50 sm:min-h-7";

/**
 * A fill waiting for its plan, at the top of its thread on the desk (docs/copilot-lab.md § The desk): "Bought NBIS 95C
 * 10:31 · Link to plan … / No plan", with the plans the linker suggests (the link ping's confirm page data,
 * ``GET /trades/{id}/plan-link``). Link calls the capture link route at once and offers Undo (the unlink route) for
 * ``UNDO_MS``; No plan writes nothing, as the confirm page's "Not this plan" does. ``titles`` names a plan by its desk
 * thread when the plan card saved it from one. ``onDone`` hears the fill is answered.
 */
export default function FillLinkBar({ tradeId, titles, onDone }: {
  tradeId: string; titles: Record<string, string>; onDone(tradeId: string, how: "linked" | "no_plan"): void;
}) {
  const [page, setPage] = useState<PlanLinkPage | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [linked, setLinked] = useState<LinkPlan | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const read = useCallback(() => fetchPlanLink(tradeId).then(setPage, () => setPage(null)), [tradeId]);
  useEffect(() => { void read(); }, [read]);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  if (!page) return null;
  const { trade, candidates } = page;
  // Linked elsewhere, or nothing left to suggest: the list's next read drops the row.
  if (!linked && (page.linked.length || !candidates.length)) return null;
  const name = (plan: LinkPlan) => (plan.investigation_id && titles[plan.investigation_id]) || plan.setup;
  const fill = `${trade.opened === "sold to open" ? "Sold" : "Bought"} ${trade.contract}${trade.opened_at_reliable ? ` ${hhmm(trade.opened_at)}` : ""}`;

  const link = async (plan: LinkPlan) => {
    setBusy(true);
    setError(null);
    try {
      await linkCapture(plan.capture_id, tradeId);
      setLinked(plan);
      timer.current = setTimeout(() => onDone(tradeId, "linked"), UNDO_MS);
    } catch (failure) {
      setError(`Not linked. ${failure instanceof Error ? failure.message : ""}`.trim());
      void read(); // another device may have linked it
    } finally {
      setBusy(false);
    }
  };
  const undo = async () => {
    if (!linked) return;
    if (timer.current) clearTimeout(timer.current);
    setBusy(true);
    setError(null);
    try {
      await unlinkCapture(linked.capture_id);
      setLinked(null);
      await read();
    } catch (failure) {
      setError(`Still linked. ${failure instanceof Error ? failure.message : ""}`.trim());
      timer.current = setTimeout(() => onDone(tradeId, "linked"), UNDO_MS);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div role="group" aria-label="Fill to link" data-testid="fill-link-bar"
      className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border border-primary/40 bg-primary/5 px-3 py-2 text-sm">
      <span className="inline-flex items-center gap-1.5 font-medium text-foreground">
        <Link2 size={14} aria-hidden className="text-primary" />{fill}
      </span>
      {linked ? (
        <>
          <span role="status" className="text-muted-foreground">Linked to plan &ldquo;{name(linked)}&rdquo;</span>
          <button type="button" onClick={() => void undo()} disabled={busy} className={`${BUTTON} ml-auto text-foreground hover:bg-secondary`}>Undo</button>
        </>
      ) : (
        <div className="flex flex-wrap items-center gap-1.5 sm:ml-auto">
          {candidates.map(plan => (
            <button key={plan.capture_id} type="button" onClick={() => void link(plan)} disabled={busy}
              title={`Captured ${hhmm(plan.received_at)}`}
              className={`${BUTTON} max-w-full border-primary/50 bg-primary text-primary-foreground hover:bg-primary/90`}>
              <span className="truncate">Link to plan &ldquo;{name(plan)}&rdquo;</span>
              {candidates.length > 1 && <span className="tabular-nums opacity-80">{hhmm(plan.received_at)}</span>}
            </button>
          ))}
          <button type="button" onClick={() => onDone(tradeId, "no_plan")} disabled={busy}
            title="Leaves this fill unplanned; nothing is linked" className={`${BUTTON} text-muted-foreground hover:bg-secondary hover:text-foreground`}>
            No plan
          </button>
        </div>
      )}
      {error && <p role="alert" className="basis-full text-xs text-primary">{error}</p>}
    </div>
  );
}

/** "2 fills to link": opens the first waiting fill's thread; each answer there opens the next. */
export function FillsToLink({ count, onStart }: { count: number; onStart(): void }) {
  if (!count) return null;
  return (
    <button type="button" onClick={onStart} title="Opens each fill waiting for its plan, one at a time"
      className="inline-flex min-h-11 w-full items-center justify-center gap-1.5 rounded-md border border-primary/50 px-3 text-xs font-semibold text-primary hover:bg-primary/10 sm:min-h-8">
      <Link2 size={13} aria-hidden /><span className="tabular-nums">{count}</span> {count === 1 ? "fill" : "fills"} to link
    </button>
  );
}

/**
 * The desk's fills waiting to link (``fillsToLink``, less those answered here): ``bar(symbol)`` is the bar for the open
 * symbol's thread, ``start`` opens the first through ``pick`` and each answer then opens the next, ``linked`` counts the
 * links made (the desk remounts its thread top on it). ``read`` asks the list to read again.
 */
export function useFillLinks(rows: DeskThread[], pick: (row: DeskThread) => void, read: () => void) {
  const [answered, setAnswered] = useState<string[]>([]); // linked or No plan here, before the list reads it back
  useEffect(() => { setAnswered(readNoPlan()); }, []); // eslint-disable-line react-hooks/set-state-in-effect -- the store is read after hydration
  const [linked, setLinked] = useState(0);
  const passing = useRef(false);
  useEffect(() => {
    try { passing.current = window.sessionStorage.getItem(PASS_KEY) === "1"; } catch { /* no pass to resume */ }
  }, []);
  const setPassing = useCallback((on: boolean) => {
    passing.current = on;
    try { if (on) window.sessionStorage.setItem(PASS_KEY, "1"); else window.sessionStorage.removeItem(PASS_KEY); } catch { /* this page only */ }
  }, []);
  const waiting = useMemo(() => fillsToLink(rows, answered), [rows, answered]);
  const titles = useMemo(() => Object.fromEntries(rows.filter(r => r.investigationId).map(r => [r.investigationId!, r.title])), [rows]);
  const start = useCallback(() => { setPassing(true); if (waiting[0]) pick(waiting[0]); }, [waiting, pick, setPassing]);
  const done = useCallback((tradeId: string, how: "linked" | "no_plan") => {
    const now = how === "no_plan" ? saveNoPlan(tradeId) : [tradeId];
    setAnswered(current => [...new Set([...current, ...now])]);
    if (how === "linked") setLinked(n => n + 1);
    read();
    const [next] = fillsToLink(rows, [...answered, ...now]);
    if (passing.current && next) pick(next);
    else setPassing(false);
  }, [rows, answered, pick, read, setPassing]);
  const bar = (symbol: string | null | undefined) => {
    const tradeId = symbol ? waiting.find(r => r.symbol === symbol)?.fillToLink : null;
    return tradeId ? <FillLinkBar key={tradeId} tradeId={tradeId} titles={titles} onDone={done} /> : null;
  };
  return { waiting, start, bar, linked };
}
