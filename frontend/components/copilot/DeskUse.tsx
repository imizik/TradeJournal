"use client";

/**
 * How he uses the desk, and folding away what he doesn't (docs/copilot-lab.md § How I use the desk; ``lib/deskUse.ts``).
 *
 * ``DeskUseProvider`` counts quietly while the desk is open (taps inside ``data-use`` pieces, time on screen every 15
 * seconds, opens from ``useCountOpen``) and holds this device size's folds. ``Fold`` is a piece that folds to a slim
 * labelled stub; ``FoldMore`` is an area's "More" for pieces that fold out of a row (centre tabs, chart tools, chatter).
 * A folded piece is one tap away: the stub or its "More" entry shows it for now, and "Keep showing" unfolds it.
 * ``FoldSuggestion`` is the one quiet card after 14 days of use; ``DeskUseView`` is "How I use the desk", where every
 * piece's use and its Fold / Show switch always are. Nothing ever folds without his tap.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ChevronDown, X } from "lucide-react";
import { PIECE, PIECES, TICK_MS, USE_EVENT, WINDOW_DAYS, addDays, countOpen, countSeen, countTap, deskSize, flush, foldable, nameList,
  pending, piecesOnScreen, readMeta, readUse, saveFolds, suggestions, type DeskSize, type Folds, type PieceUse, type UseMeta,
  type UseSummary } from "@/lib/deskUse";
import { cn } from "@/lib/utils";

type FoldApi = {
  size: DeskSize;
  /** Folded on this size and not shown for now. */
  hidden(id: string): boolean;
  /** Folded on this size (shown for now or not). */
  folded(id: string): boolean;
  showNow(id: string): void;
  setFolded(ids: string[], fold: boolean): Promise<void>;
  snooze(): Promise<void>;
  summary: UseSummary | null;
  error: string | null;
  openView(): void;
};
const NONE: FoldApi = { size: "desk", hidden: () => false, folded: () => false, showNow: () => undefined, setFolded: async () => undefined,
  snooze: async () => undefined, summary: null, error: null, openView: () => undefined };
const FoldContext = createContext<FoldApi>(NONE);
export const useFolds = () => useContext(FoldContext);

/** Counts one open each time ``shown`` turns true (a tab chosen, a drawer opened), however it was opened. */
export function useCountOpen(id: string, shown: boolean) {
  const was = useRef(false);
  useEffect(() => {
    if (shown && !was.current) countOpen(id);
    was.current = shown;
  }, [id, shown]);
}

const FOLDS_KEY = "desk.folds.v1";
const keptFolds = (size: DeskSize): Folds => {
  try { const all = JSON.parse(window.localStorage.getItem(FOLDS_KEY) ?? "{}"); return all[size] ?? { folded: [], snoozed_until: null }; } catch { return { folded: [], snoozed_until: null }; }
};
const keepFolds = (size: DeskSize, folds: Folds) => {
  try { const all = JSON.parse(window.localStorage.getItem(FOLDS_KEY) ?? "{}"); all[size] = folds; window.localStorage.setItem(FOLDS_KEY, JSON.stringify(all)); } catch { /* this view only */ }
};

/** The device size, following the window across 768 px (a phone turned on its side). */
function useDeskSize(): DeskSize | null {
  const [size, setSize] = useState<DeskSize | null>(null); // measured after hydration, so a phone never reads the computer's folds first
  useEffect(() => {
    const query = window.matchMedia("(max-width: 767px)");
    const read = () => setSize(deskSize());
    read();
    query.addEventListener("change", read);
    return () => query.removeEventListener("change", read);
  }, []);
  return size;
}

type DeskUse = FoldApi & { view: boolean; closeView(): void; onRead(summary: UseSummary): void; enabled: boolean };

/** The desk's counting and this size's folds. ``DeskUseRoot`` hands them to the pieces inside it. */
export function useDeskUse(enabled: boolean): DeskUse {
  const measured = useDeskSize();
  const size = measured ?? "desk";
  const [folds, setFolds] = useState<Folds>({ folded: [], snoozed_until: null });
  const [summary, setSummary] = useState<UseSummary | null>(null);
  const [now, setNow] = useState<ReadonlySet<string>>(() => new Set());
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState(false);
  // This size's folds: the device's last copy at once (nothing folded flashes in), then the server's.
  useEffect(() => {
    if (!enabled || !measured) return;
    setFolds(keptFolds(measured)); // eslint-disable-line react-hooks/set-state-in-effect -- the store is read after hydration
    const controller = new AbortController();
    readUse(measured, controller.signal).then(read => { setSummary(read); setFolds(read.folds); keepFolds(measured, read.folds); }, () => { /* the kept copy stands */ });
    // Another tab of this browser saved folds: follow them, so its next save does not undo this one's.
    const follow = (event: StorageEvent) => { if (event.key === FOLDS_KEY) setFolds(keptFolds(measured)); };
    window.addEventListener("storage", follow);
    return () => { controller.abort(); window.removeEventListener("storage", follow); };
  }, [enabled, measured]);

  // Counting: a tap inside a marked piece, and every 15 seconds the pieces on screen while the page shows. A save is
  // checked on the same tick and when the page shows again; never on its own timer, never while hidden.
  useEffect(() => {
    if (!enabled) return;
    const onTap = (event: MouseEvent) => {
      const piece = (event.target as Element | null)?.closest?.<HTMLElement>("[data-use]")?.dataset.use;
      if (piece) countTap(piece);
    };
    const tick = () => {
      if (document.visibilityState !== "visible") return;
      countSeen(piecesOnScreen(), TICK_MS / 1000);
      void flush();
    };
    const shown = () => { if (document.visibilityState === "visible") void flush(); };
    document.addEventListener("click", onTap, true);
    document.addEventListener("visibilitychange", shown);
    const timer = setInterval(tick, TICK_MS);
    void flush();
    return () => { document.removeEventListener("click", onTap, true); document.removeEventListener("visibilitychange", shown); clearInterval(timer); };
  }, [enabled]);

  const save = useCallback(async (next: Folds) => {
    const before = folds;
    setFolds(next); keepFolds(size, next); setError(null);
    try {
      const saved = await saveFolds(size, next);
      setFolds(saved); keepFolds(size, saved);
      setSummary(s => s && s.size === size ? { ...s, folds: saved } : s);
    } catch (failure) {
      setFolds(before); keepFolds(size, before);
      setError(failure instanceof Error ? failure.message : "Saving failed.");
    }
  }, [folds, size]);
  const folded = useMemo(() => new Set(folds.folded), [folds.folded]);
  const closeView = useCallback(() => setView(false), []);
  const ready = enabled && measured !== null;
  return useMemo<DeskUse>(() => !ready ? { ...NONE, view: false, closeView, onRead: setSummary, enabled: false } : {
    size,
    // Only a foldable piece ever folds, whatever a saved list says (a safety piece is always shown).
    folded: id => folded.has(id) && foldable(id),
    hidden: id => folded.has(id) && foldable(id) && !now.has(id),
    showNow: id => setNow(prev => prev.has(id) ? prev : new Set(prev).add(id)),
    setFolded: (ids, fold) => {
      const next = new Set(folded);
      for (const id of ids) if (fold && foldable(id)) next.add(id); else next.delete(id);
      if (fold) setNow(prev => { const rest = new Set(prev); ids.forEach(id => rest.delete(id)); return rest; });
      return save({ ...folds, folded: [...next].sort() });
    },
    snooze: () => save({ ...folds, snoozed_until: addDays(summary?.today ?? new Date().toISOString().slice(0, 10), WINDOW_DAYS) }),
    summary: summary && summary.size === size ? summary : null,
    error,
    openView: () => setView(true),
    view, closeView, onRead: setSummary, enabled: true,
  }, [ready, size, folded, now, folds, save, summary, error, view, closeView]);
}

/** Hands the desk's folds to every piece inside, and holds "How I use the desk". */
export function DeskUseRoot({ use, children }: { use: DeskUse; children: ReactNode }) {
  return (
    <FoldContext.Provider value={use}>
      {children}
      {use.enabled && <DeskUseView open={use.view} onClose={use.closeView} onRead={use.onRead} />}
    </FoldContext.Provider>
  );
}

const STUB = "flex min-h-11 w-full items-center gap-2 rounded-md border border-dashed px-2.5 text-left text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-7";

/**
 * A piece that folds to a slim labelled stub. Its children stay mounted while folded (hidden), so showing it is instant
 * and a piece that has nothing to show (a book switched off) leaves no stub either. Shown for now, a thin line on top
 * offers Keep showing.
 */
export function Fold({ id, compact = false, children }: { id: string; compact?: boolean; children: ReactNode }) {
  const folds = useFolds();
  const box = useRef<HTMLDivElement>(null);
  const [present, setPresent] = useState(false);
  useEffect(() => {
    const node = box.current;
    if (!node) return;
    const read = () => setPresent(node.childElementCount > 0);
    read();
    const watch = new MutationObserver(read);
    watch.observe(node, { childList: true });
    return () => watch.disconnect();
  }, []);
  const hidden = folds.hidden(id);
  const forNow = folds.folded(id) && !hidden;
  const label = PIECE.get(id)?.label ?? id;
  return (
    <>
      {hidden && present && (
        <button type="button" data-use={id} data-testid={`fold-stub-${id}`} onClick={() => folds.showNow(id)} title={`${label} is folded away. Tap to show it.`} className={cn(STUB, compact && "w-auto shrink-0 border-transparent px-1.5")}>
          <span><span className="font-medium">{label}</span> · folded</span>{!compact && <span className="ml-auto"> Show</span>}
        </button>
      )}
      {forNow && present && !compact && (
        <p data-testid={`fold-now-${id}`} className="flex items-center gap-2 px-1 text-[11px] text-muted-foreground">
          <span>Folded · shown for now</span>
          <button type="button" onClick={() => void folds.setFolded([id], false)} className="text-foreground underline underline-offset-2">Keep showing</button>
        </p>
      )}
      {forNow && present && compact && (
        <button type="button" data-testid={`fold-now-${id}`} onClick={() => void folds.setFolded([id], false)} title={`${label} is folded; shown for now`}
          className="shrink-0 text-[11px] text-muted-foreground underline underline-offset-2 hover:text-foreground">Keep showing</button>
      )}
      {/* Classes, not an inline style: the phone's ticker view hides the book column's other sections by CSS. */}
      <div ref={box} data-use={id} className={hidden ? "hidden" : "contents"}>{children}</div>
    </>
  );
}

/**
 * An area's "More": its folded pieces, each one tap from showing for now (``onOpen``) and a second from Keep showing.
 * Nothing renders while none of ``ids`` is folded away.
 */
export function FoldMore({ ids, onOpen, className }: { ids: string[]; onOpen(id: string): void; className?: string }) {
  const folds = useFolds();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const shown = ids.filter(id => folds.folded(id));
  useEffect(() => {
    if (!open) return;
    const away = (event: Event) => { if (!box.current?.contains(event.target as Node)) setOpen(false); };
    const key = (event: KeyboardEvent) => { if (event.key === "Escape") { event.stopPropagation(); setOpen(false); } };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", key, true);
    return () => { document.removeEventListener("pointerdown", away); document.removeEventListener("keydown", key, true); };
  }, [open]);
  if (!shown.length) return null;
  return (
    <div ref={box} className={cn("relative shrink-0", className)}>
      <button type="button" aria-expanded={open} data-testid="fold-more" onClick={() => setOpen(o => !o)} title="Pieces you folded away"
        className="inline-flex min-h-11 items-center gap-0.5 rounded px-1.5 text-xs text-muted-foreground hover:text-foreground sm:min-h-0 sm:py-0.5">
        More<ChevronDown size={12} aria-hidden />
      </button>
      {open && (
        <ul className="absolute right-0 top-full z-30 mt-1 min-w-56 rounded-md border bg-popover p-1 text-xs shadow-lg">
          {shown.map(id => (
            <li key={id} className="flex items-center gap-2 rounded px-1.5">
              <button type="button" data-use={id} onClick={() => { setOpen(false); folds.showNow(id); onOpen(id); }}
                className="min-h-11 flex-1 text-left text-foreground hover:underline sm:min-h-8">{PIECE.get(id)?.label ?? id}</button>
              {folds.hidden(id) ? <span className="text-muted-foreground">folded</span> : <span className="text-muted-foreground">shown for now</span>}
              <button type="button" onClick={() => void folds.setFolded([id], false)} className="min-h-11 text-muted-foreground underline underline-offset-2 hover:text-foreground sm:min-h-8">Keep showing</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The one quiet card after 14 days of desk use on this size: pieces opened or tapped at most once in that window. */
export function FoldSuggestion() {
  const folds = useFolds();
  const ids = suggestions(folds.summary, new Set(PIECES.filter(p => folds.folded(p.id)).map(p => p.id)));
  if (!ids.length) return null;
  return (
    <section aria-label="Fold suggestion" data-testid="fold-suggestion" className="rounded-md border bg-card/60 px-3 py-2 text-xs">
      <p className="text-foreground">You haven&apos;t opened {nameList(ids)} in 2 weeks. Fold {ids.length === 1 ? "it" : "them"}?</p>
      <p className="mt-0.5 text-muted-foreground">Folded pieces stay one tap away, and ⌘K still finds them.</p>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        <button type="button" onClick={() => void folds.setFolded(ids, true)} className="inline-flex min-h-11 items-center rounded-md border px-2.5 font-medium text-foreground hover:bg-secondary sm:min-h-7">Fold all</button>
        <button type="button" onClick={folds.openView} className="inline-flex min-h-11 items-center rounded-md border px-2.5 text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-7">Pick</button>
        <button type="button" onClick={() => void folds.snooze()} className="inline-flex min-h-11 items-center rounded-md px-2.5 text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-7">Not now</button>
      </div>
      {folds.error && <p role="alert" className="mt-1 text-amber-300">{folds.error}</p>}
    </section>
  );
}

const clock = (ms: number) => new Date(ms).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
const shortDay = (day: string) => new Date(`${day}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric" });
const minutes = (s: number) => s < 60 ? (s > 0 ? "under a minute" : "") : s < 3600 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`;

function useMeta(): UseMeta {
  const [meta, setMeta] = useState<UseMeta>({ lastTry: null, failedSince: null, lastSaved: null });
  useEffect(() => {
    const read = () => setMeta(readMeta());
    read();
    window.addEventListener(USE_EVENT, read);
    return () => window.removeEventListener(USE_EVENT, read);
  }, []);
  return meta;
}

/** "How I use the desk": every piece's last-14-day use on this device size, least used first, each with its switch. */
function DeskUseView({ open, onClose, onRead }: { open: boolean; onClose(): void; onRead(summary: UseSummary): void }) {
  const folds = useFolds();
  const dialog = useRef<HTMLDialogElement>(null);
  const meta = useMeta();
  const [read, setRead] = useState<{ summary: UseSummary | null; failed: boolean } | null>(null);
  useEffect(() => {
    const node = dialog.current;
    if (!node) return;
    if (open && !node.open) node.showModal();
    else if (!open && node.open) node.close();
  }, [open]);
  // Opening it saves what waits on this device first, so the list is current; a failed save is said, never shown as zeros.
  useEffect(() => {
    if (!open) return;
    let live = true;
    setRead(null); // eslint-disable-line react-hooks/set-state-in-effect -- a fresh read each time it opens
    flush(true).finally(() => readUse(folds.size).then(summary => { if (live) { setRead({ summary, failed: false }); onRead(summary); } },
      () => { if (live) setRead({ summary: null, failed: true }); }));
    return () => { live = false; };
  }, [open, folds.size, onRead]);
  const summary = read?.summary ?? null;
  const waiting = summary ? pending(folds.size, summary.window_start) : {};
  const use = (id: string): PieceUse => {
    const saved = summary?.pieces[id] ?? { opens: 0, taps: 0, seen_s: 0, last_used: null };
    const here = waiting[id] ?? [0, 0, 0];
    return { opens: saved.opens + here[0], taps: saved.taps + here[1], seen_s: saved.seen_s + here[2],
      last_used: here[0] + here[1] > 0 && summary ? summary.today : saved.last_used };
  };
  const rows = PIECES.map(p => ({ piece: p, use: use(p.id) }))
    .sort((a, b) => (a.use.opens + a.use.taps) - (b.use.opens + b.use.taps) || a.use.seen_s - b.use.seen_s);
  const days = summary?.days_with_use ?? 0;
  return (
    <dialog ref={dialog} aria-label="How I use the desk" data-testid="desk-use-view" onClose={onClose} onCancel={onClose}
      onClick={event => { if (event.target === dialog.current) onClose(); }}
      className="m-auto max-h-[85vh] w-[min(40rem,94vw)] overflow-y-auto rounded-lg border bg-background p-0 text-foreground backdrop:bg-black/60">
      <div className="sticky top-0 z-10 flex items-center gap-2 border-b bg-background px-4 py-2.5">
        <h2 className="text-sm font-semibold">How I use the desk</h2>
        <span className="text-xs text-muted-foreground">{folds.size === "phone" ? "on a phone" : "on a computer"} · last {WINDOW_DAYS} days</span>
        <button type="button" onClick={onClose} aria-label="Close" className="ml-auto inline-flex min-h-11 min-w-11 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8 sm:min-w-8">
          <X size={15} aria-hidden />
        </button>
      </div>
      <div className="space-y-2 px-4 py-3 text-xs">
        <p className="text-muted-foreground">The desk counts which pieces you open and tap, and how long they are on screen. No typing, no tickers. The counts stay in this app. Folding is separate for a computer and a phone.</p>
        {meta.failedSince !== null && (
          <p role="status" data-testid="desk-use-paused" className="rounded border border-amber-300/40 px-2 py-1 text-amber-200">
            Counts paused since {clock(meta.failedSince)}: they could not be saved. What this device counted since is kept here and included below; it saves when the app answers again.
          </p>
        )}
        {read?.failed && <p role="status" className="text-amber-200">Your desk use could not be read just now. Folds still work.</p>}
        {!read && <p className="text-muted-foreground">Reading…</p>}
        {summary && days < WINDOW_DAYS && <p className="text-muted-foreground">{days} of {WINDOW_DAYS} days counted so far. Suggestions to fold start after {WINDOW_DAYS} days.</p>}
        {folds.error && <p role="alert" className="text-amber-300">{folds.error}</p>}
        {summary && <ul className="divide-y rounded-md border">
          {rows.map(({ piece, use: u }) => {
            const folded = folds.folded(piece.id);
            const words = [u.opens ? `${u.opens} open${u.opens === 1 ? "" : "s"}` : "", u.taps ? `${u.taps} tap${u.taps === 1 ? "" : "s"}` : "",
              u.seen_s ? `on screen ${minutes(u.seen_s)}` : ""].filter(Boolean).join(" · ") || "not used";
            return (
              <li key={piece.id} data-testid={`desk-use-${piece.id}`} className="flex min-h-11 items-center gap-2 px-2.5 py-1.5">
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium text-foreground">{piece.label}<span className="ml-1.5 font-normal text-muted-foreground">{piece.area}</span></span>
                  <span className="block text-muted-foreground">{words}{u.last_used ? ` · last used ${shortDay(u.last_used)}` : " · never used"}</span>
                </span>
                {piece.safety ? <span className="shrink-0 text-muted-foreground" title="Holds positions, orders, alerts or a source down">Always shown</span>
                  : !piece.fold ? <span className="shrink-0 text-muted-foreground">Always shown</span>
                  : (
                    <div role="group" aria-label={`${piece.label}: fold or show`} className="inline-flex shrink-0 rounded-md border p-0.5">
                      {([[false, "Show"], [true, "Fold"]] as const).map(([fold, text]) => (
                        <button key={text} type="button" aria-pressed={folded === fold} onClick={() => { if (folded !== fold) void folds.setFolded([piece.id], fold); }}
                          className={cn("min-h-11 rounded px-2.5 sm:min-h-7", folded === fold ? "bg-secondary font-medium text-foreground" : "text-muted-foreground hover:text-foreground")}>{text}</button>
                      ))}
                    </div>
                  )}
              </li>
            );
          })}
        </ul>}
      </div>
    </dialog>
  );
}
